# ============================================================
# ADAPTIVE TARGET EXTENSION MODEL
# ============================================================
#
# Decides, for a trade already IN PROFIT, whether to let it run past its target
# or bank it now.
#
# WHY THIS IS NOT THE EXIT MODEL WITH A FLIPPED LABEL
# ---------------------------------------------------
# Labelling this `final_return_R > current_return_R` would be the exact
# complement of exit_model's label -- the same model trained twice, and it would
# inherit the same defect: that label is nearly a function of current_return_R,
# which is also a feature, so it can be "learned" from any path at all
# (exit_model.py promoted a model on pure noise before a permutation control
# caught it).
#
# Two things make this a genuinely different question:
#
#   POPULATION  only points where the trade is in profit. Extension is a
#               decision that does not exist for a losing trade.
#
#   LABEL       a forward path question, not an endpoint comparison: walking
#               forward from here, does price reach current + MIN_EXTENSION
#               before giving back MAX_GIVEBACK? That asks what happens next,
#               rather than comparing against a per-trade constant.
#
# WHY IT MATTERS FOR EXPECTANCY
# -----------------------------
#     E = (win_rate x avg_win) - (loss_rate x avg_loss)
#
# exit_model works on avg_loss. This works on avg_win, the other half. Targets
# are currently static ATR multiples, so every trade takes the same profit
# regardless of whether conditions favour continuation -- and on a coin-flip
# direction signal the right tail is where expectancy is won.
#
# REUSE
# -----
# Sample rows, the estimator, causal feature extraction, group-aware splitting,
# AUC and the permutation control are all imported from exit_model rather than
# reimplemented. Standard #10: this codebase has repeatedly been bitten by
# second implementations that silently diverged.
# ============================================================

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .exit_model import (
    ExitModel,
    ExitSample,
    SKLEARN_AVAILABLE,
    _direction_sign,
    path_features,
    permuted_path_trades,
    roc_auc,
    split_by_trade,
)

TARGET_MODEL_VERSION = "1.0"


@dataclass
class TargetModelConfig:
    # A trade must be this far in profit before extending is even a question.
    min_profit_r: float = 0.5

    # Extension "paid off" if price gains at least this much more...
    min_extension_r: float = 0.5
    # ...before handing back this much from the decision point. Without the
    # giveback leg the label would count extensions that only ever succeeded
    # after a drawdown no real position would have survived.
    max_giveback_r: float = 0.5

    min_bars_before_decision: int = 2
    min_training_trades: int = 30
    min_samples: int = 100
    test_fraction: float = 0.3

    min_auc: float = 0.55
    min_auc_over_control: float = 0.02
    min_expectancy_gain_r: float = 0.05

    # Permutation floor. See exit_model: a shuffled-label control cannot detect
    # a label/feature tautology, and a synthetic walk has to guess the data's
    # character. Permuting increments preserves everything but temporal order.
    min_delta_over_noise_r: float = 0.10
    min_auc_over_noise: float = 0.05

    extend_threshold: float = 0.60
    random_seed: int = 42
    regularization_c: float = 1.0

    # Decision-time context: the full opening snapshot (SMC, volume profile,
    # S/R, patterns, waves, indicators, session, vetos, leverage). Off by
    # default for the same reason as exit_model -- these columns are constant
    # within a trade and ~123 of them on a few hundred trades memorises rather
    # than generalises. The permutation noise floor above is what decides
    # whether they earned their place; this flag only lets them compete.
    include_context_features: bool = False


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------

def extension_paid_off(
    returns_r: Sequence[float],
    index: int,
    min_extension_r: float,
    max_giveback_r: float,
) -> Optional[int]:
    """
    Walking forward from `index`, is `current + min_extension_r` reached before
    price falls to `current - max_giveback_r`?

    Order matters, which is the point. A path that dips through the giveback
    level and only later reaches the target did NOT pay off -- the position
    would have been closed on the way down. Evaluating the two conditions
    independently would silently count those as wins.

    Returns None when neither level is touched before the trade ends: that is
    genuinely unresolved, and guessing a label for it would teach the model an
    outcome the data never showed.
    """
    if index < 0 or index >= len(returns_r) - 1:
        return None

    current = returns_r[index]
    target = current + min_extension_r
    floor = current - max_giveback_r

    for value in returns_r[index + 1:]:
        if value <= floor:
            return 0
        if value >= target:
            return 1
    return None


def build_target_samples(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[TargetModelConfig] = None,
    bridge: Any = None,
) -> List[ExitSample]:
    """
    One sample per (trade, in-profit point) with a resolved forward outcome.

    Reuses exit_model.path_features, so features are causal by the same
    construction and verified by the same tests.
    """
    cfg = config or TargetModelConfig()
    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    samples: List[ExitSample] = []

    for trade in trades or []:
        try:
            canonical = bridge.to_canonical(trade)
        except Exception:
            continue

        entry = canonical.get("entry") or {}
        entry_price, stop_loss = entry.get("price"), entry.get("stop_loss")
        if not entry_price or not stop_loss:
            continue

        risk = abs(entry_price - stop_loss)
        if not risk:
            continue

        evolution = canonical.get("price_evolution") or []
        prices = [entry_price] + [
            point.get("price") for point in evolution
            if isinstance(point, dict) and point.get("price") is not None
        ]
        if len(prices) < cfg.min_bars_before_decision + 2:
            continue

        sign = _direction_sign(canonical.get("direction"))
        close_price = (canonical.get("close_data") or {}).get("close_price")
        final_price = close_price if close_price else prices[-1]

        # The forward path used for labelling includes the close, so a trade
        # whose extension only materialised at the fill is still resolved.
        returns_r = [sign * (p - entry_price) / risk for p in prices]
        returns_r.append(sign * (final_price - entry_price) / risk)

        trade_id = str(canonical.get("trade_id") or canonical.get("ticket") or "")

        # Once per trade: decision-time constants, identical at every index.
        context: Dict[str, float] = {}
        if cfg.include_context_features:
            from .price_evolution_bridge import context_features
            context = context_features(trade, bridge)
        if not trade_id:
            continue

        for index in range(cfg.min_bars_before_decision, len(prices) - 1):
            current_return_r = returns_r[index]
            if current_return_r < cfg.min_profit_r:
                continue   # not a winner yet; extension is not the question

            label = extension_paid_off(
                returns_r, index, cfg.min_extension_r, cfg.max_giveback_r)
            if label is None:
                continue   # unresolved -- do not invent an outcome

            features = path_features(
                prices, index, entry_price, stop_loss,
                entry.get("take_profit"), canonical.get("direction"))
            if features is None:
                continue

            if cfg.include_context_features:
                features = {**features, **context}

            samples.append(ExitSample(
                trade_id=trade_id,
                timestamp=str(canonical.get("opened_at") or ""),
                index=index,
                features=features,
                label=label,
                current_return_r=current_return_r,
                final_return_r=returns_r[-1],
            ))

    return samples


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def extension_expectancy_delta(
    samples: Sequence[ExitSample],
    scores: Sequence[float],
    threshold: float,
) -> Dict[str, Any]:
    """
    Baseline banks profit at the first qualifying point; the policy holds to the
    close when the model says extend.

    This is the acceptance criterion, not AUC. Extending is only worth doing if
    the additional upside survives the trades where it reverses -- a model can
    be right most of the time and still lose money here, because the losses on
    a failed extension are larger than the gains on a successful one.
    """
    by_trade: Dict[str, List[Tuple[ExitSample, float]]] = {}
    for sample, score in zip(samples, scores):
        by_trade.setdefault(sample.trade_id, []).append((sample, score))

    baseline, policy, extended = [], [], 0
    for rows in by_trade.values():
        rows.sort(key=lambda pair: pair[0].index)
        first, first_score = rows[0]

        baseline.append(first.current_return_r)
        if first_score >= threshold:
            policy.append(first.final_return_r)
            extended += 1
        else:
            policy.append(first.current_return_r)

    if not baseline:
        return {"trades": 0, "baseline_r": None, "policy_r": None, "delta_r": None}

    mean_baseline = sum(baseline) / len(baseline)
    mean_policy = sum(policy) / len(policy)
    return {
        "trades": len(baseline),
        "baseline_r": round(mean_baseline, 4),
        "policy_r": round(mean_policy, 4),
        "delta_r": round(mean_policy - mean_baseline, 4),
        "extensions": extended,
        "extension_rate": round(extended / len(baseline), 3),
    }


class TargetModel:
    """
    Standardized logistic over causal path features.

    Wraps exit_model.ExitModel as the estimator rather than restating the
    fitting, scaling and JSON-persistence logic. Only the question differs.
    """

    def __init__(self, config: Optional[TargetModelConfig] = None):
        self.config = config or TargetModelConfig()
        self._estimator = ExitModel()
        self._estimator.config.regularization_c = self.config.regularization_c
        self._estimator.config.random_seed = self.config.random_seed
        self._estimator.config.min_training_trades = self.config.min_training_trades
        # Must be propagated, not merely set here. ExitModel.fit decides the
        # column list from ITS OWN config, so leaving this behind meant the
        # estimator kept the 11 default columns while build_target_samples
        # produced 130 -- _matrix silently dropping every context column and
        # training on a feature set nobody chose. It would have looked normal
        # and reported normal.
        self._estimator.config.include_context_features = (
            self.config.include_context_features)

    @property
    def fitted(self) -> bool:
        return self._estimator.fitted

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._estimator.metadata

    @property
    def feature_names(self) -> List[str]:
        return self._estimator.feature_names

    def fit(self, samples: Sequence[ExitSample]) -> Dict[str, Any]:
        info = self._estimator.fit(samples)
        info["model"] = "target_extension"
        info["version"] = TARGET_MODEL_VERSION
        return info

    def predict_proba(self, samples: Sequence[ExitSample]) -> List[float]:
        return self._estimator.predict_proba(samples)

    def should_extend(
        self,
        prices: Sequence[float],
        entry_price: float,
        stop_loss: float,
        take_profit: Optional[float],
        direction: Any,
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Live decision for an open, in-profit trade.

        Refuses to answer for a trade that is not yet in profit -- that is the
        exit model's question, and answering it here would apply a model
        outside the population it was fitted on.
        """
        index = len(prices) - 1
        features = path_features(prices, index, entry_price, stop_loss,
                                 take_profit, direction)
        if features is None:
            return {"extend": False, "probability": None, "reason": "insufficient_data"}
        if not self.fitted:
            return {"extend": False, "probability": None, "reason": "not_fitted"}
        if features["return_r"] < self.config.min_profit_r:
            return {"extend": False, "probability": None,
                    "reason": "not_in_profit",
                    "return_r": round(features["return_r"], 4)}

        sample = ExitSample("live", "", index, features, 0,
                            features["return_r"], 0.0)
        probability = self.predict_proba([sample])[0]
        cut = self.config.extend_threshold if threshold is None else threshold
        return {
            "extend": probability >= cut,
            "probability": round(probability, 4),
            "threshold": cut,
            "return_r": round(features["return_r"], 4),
            "progress_to_target": round(features["progress_to_target"], 4),
        }

    def save(self, path: str) -> str:
        return self._estimator.save(path)

    def load(self, path: str) -> "TargetModel":
        self._estimator.load(path)
        return self


# ---------------------------------------------------------------------------
# Training with promotion gates
# ---------------------------------------------------------------------------

def _pipeline_score(trades, cfg, bridge=None) -> Dict[str, Any]:
    samples = build_target_samples(trades, cfg, bridge)
    if len(samples) < cfg.min_samples:
        return {"auc": None, "delta_r": None, "samples": len(samples)}

    train, test = split_by_trade(samples, cfg.test_fraction)
    if not test:
        return {"auc": None, "delta_r": None, "samples": len(samples)}

    model = TargetModel(cfg)
    try:
        model.fit(train)
    except (ValueError, ImportError) as exc:
        return {"auc": None, "delta_r": None, "error": str(exc)}

    scores = model.predict_proba(test)
    expectancy = extension_expectancy_delta(test, scores, cfg.extend_threshold)
    return {
        "auc": roc_auc([s.label for s in test], scores),
        "delta_r": expectancy.get("delta_r"),
        "expectancy": expectancy,
        "samples": len(samples),
        "model": model,
        "test": test,
        "scores": scores,
    }


def train_and_validate(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[TargetModelConfig] = None,
    bridge: Any = None,
) -> Dict[str, Any]:
    """
    Fit, validate against both a shuffled-label control and a permutation floor,
    and decide promotion.

    Promotion requires beating BOTH controls on expectancy, not AUC alone.
    """
    import random as _random

    cfg = config or TargetModelConfig()
    report: Dict[str, Any] = {"version": TARGET_MODEL_VERSION, "promoted": False}

    samples = build_target_samples(trades, cfg, bridge)
    report["samples"] = len(samples)
    report["trades"] = len({s.trade_id for s in samples})
    report["positive_rate"] = (
        round(sum(s.label for s in samples) / len(samples), 4) if samples else None)

    if len(samples) < cfg.min_samples:
        report["rejected_because"] = (
            f"{len(samples)} in-profit resolved samples < required {cfg.min_samples}")
        return report

    train, test = split_by_trade(samples, cfg.test_fraction)
    report["train_samples"], report["test_samples"] = len(train), len(test)
    if not test:
        report["rejected_because"] = "not enough distinct trades to hold any out"
        return report

    model = TargetModel(cfg)
    try:
        report["fit"] = model.fit(train)
    except (ValueError, ImportError) as exc:
        report["rejected_because"] = str(exc)
        return report

    scores = model.predict_proba(test)
    labels = [s.label for s in test]
    auc = roc_auc(labels, scores)
    report["test_auc"] = round(auc, 4) if auc is not None else None
    report["expectancy"] = extension_expectancy_delta(
        test, scores, cfg.extend_threshold)

    rng = _random.Random(cfg.random_seed)
    shuffled_labels = [s.label for s in train]
    rng.shuffle(shuffled_labels)
    control = TargetModel(cfg)
    control_auc = None
    try:
        control.fit([
            ExitSample(s.trade_id, s.timestamp, s.index, s.features, y,
                       s.current_return_r, s.final_return_r)
            for s, y in zip(train, shuffled_labels)
        ])
        control_auc = roc_auc(labels, control.predict_proba(test))
    except (ValueError, ImportError):
        pass
    report["control_auc"] = round(control_auc, 4) if control_auc is not None else None

    # Pooled across trades, not permuted within them. Within-trade permutation
    # preserves each trade's endpoint, and this label is endpoint-adjacent --
    # "does price run further" is largely decided by per-trade drift -- so that
    # control would keep the structure it is supposed to remove. Measured: it
    # scored 0.99 AUC / 1.59R, above the real model, making the gate unpassable
    # for the wrong reason. Pooling removes per-trade drift while preserving
    # the global distribution of moves.
    noise = _pipeline_score(
        permuted_path_trades(trades, cfg.random_seed, bridge,
                             pool_across_trades=True),
        cfg, bridge)
    report["noise_floor"] = {
        "auc": round(noise["auc"], 4) if noise.get("auc") is not None else None,
        "delta_r": noise.get("delta_r"),
        "samples": noise.get("samples"),
    }

    reasons = []
    if auc is None or auc < cfg.min_auc:
        reasons.append(f"AUC {report['test_auc']} < {cfg.min_auc}")
    if control_auc is not None and auc is not None:
        if auc - control_auc < cfg.min_auc_over_control:
            reasons.append(
                f"AUC {report['test_auc']} does not beat shuffled control "
                f"{report['control_auc']} by {cfg.min_auc_over_control}")

    delta = report["expectancy"].get("delta_r")
    if delta is None or delta < cfg.min_expectancy_gain_r:
        reasons.append(
            f"expectancy delta {delta}R < required {cfg.min_expectancy_gain_r}R")

    noise_delta, noise_auc = noise.get("delta_r"), noise.get("auc")

    # Fail closed. An earlier version skipped both floor gates whenever the
    # permutation control could not be scored (too few resolved samples), so a
    # model could be promoted with its most important safety check silently
    # absent -- and the report would look clean. An uncomputable gate is an
    # unmet gate.
    if noise_delta is None or noise_auc is None:
        reasons.append(
            "permutation floor could not be computed "
            f"({noise.get('samples', 0)} control samples, "
            f"{noise.get('error', 'insufficient data')}) -- refusing to promote "
            "without it")
    else:
        if delta is not None and delta - noise_delta < cfg.min_delta_over_noise_r:
            reasons.append(
                f"expectancy delta {delta}R does not beat the permutation floor "
                f"{noise_delta}R by {cfg.min_delta_over_noise_r}R")
        if auc is not None and auc - noise_auc < cfg.min_auc_over_noise:
            reasons.append(
                f"AUC {report['test_auc']} does not beat the permutation-floor "
                f"AUC {round(noise_auc, 4)} by {cfg.min_auc_over_noise}")

    report["promoted"] = not reasons

    # Governance: record EVERY attempt, promote only what cleared the gates.
    #
    # Rejected candidates are registered too. "This configuration was tried on
    # this data and did not beat the noise floor" is the fact that stops it
    # being tried again in three months, and a registry of successes only
    # cannot answer it. Promotion is still decided above; this records.
    #
    # A governance failure must not fail training, but it must not be silent
    # either -- the error is reported in the same report rather than swallowed.
    try:
        from .model_governance import record_training
        report["governance"] = record_training(
            "target_model",
            payload={key: value for key, value in report.items()
                     if key not in ("model", "rules_model", "governance")},
            metrics={key: report.get(key) for key in ("test_auc", "expectancy_delta_r", "samples")
                     if report.get(key) is not None},
            promoted=bool(report["promoted"]),
            notes=report.get("rejected_because") or "passed promotion gates",
        )
    except Exception as exc:
        report["governance"] = {"error": type(exc).__name__ + ": " + str(exc)}
    report["rejected_because"] = "; ".join(reasons) if reasons else None
    report["model"] = model if report["promoted"] else None
    return report


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status(model: Optional[TargetModel] = None) -> Dict[str, Any]:
    cfg = TargetModelConfig()
    return {
        "component": "target_model",
        "version": TARGET_MODEL_VERSION,
        "sklearn_available": SKLEARN_AVAILABLE,
        "trainable": SKLEARN_AVAILABLE,
        "model_loaded": bool(model and model.fitted),
        "metadata": model.metadata if model else {},
        "label_definition": (
            "reaches current + min_extension_r before giving back max_giveback_r"),
        "population": "in-profit points only",
        "thresholds": {
            "min_profit_r": cfg.min_profit_r,
            "min_extension_r": cfg.min_extension_r,
            "max_giveback_r": cfg.max_giveback_r,
            "extend_threshold": cfg.extend_threshold,
        },
        "promotion_gates": {
            "min_auc": cfg.min_auc,
            "min_auc_over_control": cfg.min_auc_over_control,
            "min_expectancy_gain_r": cfg.min_expectancy_gain_r,
            "min_delta_over_noise_r": cfg.min_delta_over_noise_r,
        },
        "predicts_direction": False,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None) -> Dict[str, Any]:
    """Prove sample construction, population filtering and split disjointness."""
    report: Dict[str, Any] = {"component": "target_model", "ok": False, "checks": {}}
    cfg = TargetModelConfig()
    try:
        samples = build_target_samples(trades or [], cfg, bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["samples_built"] = len(samples)
        report["checks"]["distinct_trades"] = len({s.trade_id for s in samples})

        if samples:
            report["checks"]["all_in_profit"] = all(
                s.current_return_r >= cfg.min_profit_r for s in samples)
            report["checks"]["labels_binary"] = {s.label for s in samples} <= {0, 1}
            report["checks"]["positive_rate"] = round(
                sum(s.label for s in samples) / len(samples), 3)
            report["checks"]["no_nan_features"] = all(
                math.isfinite(v) for s in samples for v in s.features.values())

            train, test = split_by_trade(samples)
            report["checks"]["split_groups_disjoint"] = not (
                {s.trade_id for s in train} & {s.trade_id for s in test})

            report["ok"] = bool(
                report["checks"]["all_in_profit"]
                and report["checks"]["no_nan_features"]
                and report["checks"]["split_groups_disjoint"]
            )
        else:
            # Two different states were being collapsed into one here. `ok`
            # was left at its initialised False, which reported a working
            # module as broken whenever the data was merely thin -- and,
            # aggregated into /verify, pinned the whole-layer gate red until
            # people learned to ignore it. Reporting both as "not exercised"
            # would be the opposite error, letting a broken decode path pass
            # unnoticed. So they are separated: input nothing can read is a
            # FAILURE, valid input with nothing eligible is NOT EXERCISED.
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades or [])
            report["checks"]["usable_trades"] = usable
            if trades and usable == 0:
                report["ok"] = False
                report["reason"] = ("no supplied trade could be decoded; the "
                                    "data path, not the model, is the problem")
            else:
                report["ok"] = None
                report["reason"] = "no trade reached the minimum profit needed to sample an extension decision"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "TARGET_MODEL_VERSION", "TargetModelConfig", "TargetModel",
    "extension_paid_off", "build_target_samples",
    "extension_expectancy_delta", "train_and_validate",
    "get_status", "self_check",
]
