# ============================================================
# MID-TRADE EXIT MODEL
# ============================================================
#
# Predicts, DURING a trade, whether continuing to hold will hurt.
#
# WHY THIS AND NOT DIRECTION PREDICTION
# -------------------------------------
# Replay measured direction entropy at 1.0000 -- a fair coin at every timeframe
# tested -- and meta-labeling confirmed it (AUC 0.5034 vs a 0.5092 shuffled
# control) and was refused promotion. Entry direction carries no signal in this
# data, so nothing here tries to forecast it.
#
# An unfolding trade is a different problem. A position 70% of the way to its
# stop, whose structure has deteriorated since entry, is drawn from a visibly
# different distribution than one that is not. That is a classification of an
# observed state, not a forecast of the future.
#
# Expectancy does not need a better hit rate:
#
#     E = (win_rate x avg_win) - (loss_rate x avg_loss)
#
# With win rate near 50%, the payoff ratio is the whole lever. Cutting losers
# early moves avg_loss, which is why this is the highest-impact model available
# on a coin-flip direction signal.
#
# LABEL
# -----
# `final_return_R < current_return_R` -- did holding from this point hurt?
# That is the decision actually being made, and it is well defined at every
# point in the trade. "Did the trade lose" is a weaker target: a winner that
# gives back most of its gain should still have been exited.
#
# LEAKAGE
# -------
# Features at point k are computed from points 0..k ONLY. The label comes from
# the trade's end, which is legitimate supervision at training time and never a
# feature. Splits are grouped by trade, because samples drawn from one trade
# share an outcome and would otherwise leak across the split -- the same hazard
# train_meta_label.py handles with purged CV.
# ============================================================

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from sklearn.linear_model import LogisticRegression
    SKLEARN_AVAILABLE = True
except ImportError:
    LogisticRegression = None
    SKLEARN_AVAILABLE = False

EXIT_MODEL_VERSION = "1.0"

# Feature order is part of the persisted artifact; appending is safe, reordering
# is not. A model loaded against a different order would score silently wrong.
FEATURE_NAMES: Tuple[str, ...] = (
    "bars_elapsed",
    "return_r",
    "mfe_r",
    "mae_r",
    "drawdown_from_peak_r",
    "bars_since_mfe",
    "room_to_stop",
    "progress_to_target",
    "velocity_r",
    "path_volatility_r",
    "adverse_fraction",
)


@dataclass
class ExitModelConfig:
    min_bars_before_exit: int = 2
    min_training_trades: int = 30
    min_samples: int = 100
    test_fraction: float = 0.3

    # Promotion gates. Deliberately mirrors train_meta_label.py: a model must
    # beat a shuffled-label control, not merely exceed 0.5.
    min_auc: float = 0.55
    min_auc_over_control: float = 0.02
    min_expectancy_gain_r: float = 0.05

    # ------------------------------------------------------------------
    # NOISE-FLOOR GATE  (added after this pipeline promoted a model on
    # pure random walks: AUC 0.777, +0.34R, beating its shuffled control)
    # ------------------------------------------------------------------
    # The label `final_return_R < current_return_R` is, within a single
    # trade, nearly a function of current_return_R -- because `final` is
    # constant for that trade and current_return_R is also a FEATURE. The
    # model can therefore learn "am I near the peak of my own path", and
    # leaving near a realised peak beats holding to the endpoint on ANY
    # path, signal or not.
    #
    # A shuffled-LABEL control cannot detect this: shuffling destroys the
    # structure, so real data beats it even when the real data is noise.
    # A synthetic random walk cannot either -- it has to guess the data's
    # statistical character, and a driftless walk is far less exit-timing
    # exploitable than an iid-around-a-level series, so it sets the bar in
    # the wrong place.
    #
    # The control that works is permuting each trade's price INCREMENTS
    # (see permuted_path_trades): entry, endpoint, length, volatility and
    # the exact multiset of moves are all preserved, and only their ORDER
    # is destroyed. A genuinely temporal edge must degrade under that; an
    # "exit near the path peak" artifact survives it and is refused.
    min_delta_over_noise_r: float = 0.10
    min_auc_over_noise: float = 0.05

    exit_threshold: float = 0.65
    random_seed: int = 42

    # Off by default. The bridge yields ~486 analysis features per snapshot;
    # with a few hundred trades that overfits badly, and the path features
    # below carry most of the decision-relevant signal. Enable only once the
    # trade count genuinely supports the width.
    include_analysis_features: bool = False

    # ------------------------------------------------------------------
    # DECISION-TIME CONTEXT (SMC, volume profile, S/R, patterns, waves,
    # indicators, session, vetos, leverage -- the full opening snapshot)
    # ------------------------------------------------------------------
    # This model decided from 11 price-path features and nothing else, while
    # the bridge was already extracting ~125 analysis features per trade that
    # no model read. The evidence existed; nothing consumed it.
    #
    # Still OFF by default, and that is not timidity. These columns are
    # CONSTANT within a trade, so with trade-grouped splits they let the model
    # identify the trade rather than the situation, and ~123 extra columns on
    # a few hundred trades is a memorisation machine. The safeguard is that
    # turning this on does not promote anything: the increment-permutation
    # noise floor and the expectancy gates still have to be cleared, and they
    # are exactly the controls that caught this pipeline promoting a model on
    # pure random walks. Enable it, measure it, and let the gates answer.
    include_context_features: bool = False

    # Logistic regression, persisted as plain JSON coefficients. Chosen over
    # gradient boosting on two grounds: it is the better-conditioned model at
    # this sample size, and it serialises without pickle -- loading a pickle
    # is arbitrary code execution, and meta_labeling.py already set the
    # no-pickle precedent for shipped artifacts.
    regularization_c: float = 1.0


# ---------------------------------------------------------------------------
# Causal path features
# ---------------------------------------------------------------------------

def _direction_sign(direction: Any) -> int:
    return -1 if str(direction).upper().strip() in {"SELL", "SHORT", "-1"} else 1


def path_features(
    prices: Sequence[float],
    index: int,
    entry_price: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    direction: Any,
) -> Optional[Dict[str, float]]:
    """
    Features describing the trade as of `index`, using prices[0..index] ONLY.

    Everything is expressed in R (multiples of the trade's own risk) so a
    XAGUSD trade and a EURUSD trade are directly comparable -- an absolute pip
    feature would make the model learn the instrument instead of the situation.

    Returns None when the trade has no measurable risk, since every feature
    here is defined as a fraction of it.
    """
    if index < 1 or index >= len(prices) or not entry_price:
        return None

    sign = _direction_sign(direction)
    risk = abs(entry_price - stop_loss) if stop_loss else 0.0
    if not risk or not math.isfinite(risk):
        return None

    # The causal slice. Everything below is computed from this and nothing else.
    window = prices[: index + 1]
    returns_r = [sign * (price - entry_price) / risk for price in window]

    current = returns_r[-1]
    mfe = max(returns_r)
    mae = min(returns_r)
    peak_index = returns_r.index(mfe)

    if len(returns_r) >= 4:
        velocity = (returns_r[-1] - returns_r[-4]) / 3.0
    else:
        velocity = returns_r[-1] - returns_r[0]

    mean_r = sum(returns_r) / len(returns_r)
    variance = sum((r - mean_r) ** 2 for r in returns_r) / len(returns_r)

    target_distance = abs(take_profit - entry_price) if take_profit else 0.0
    progress_to_target = (
        (sign * (window[-1] - entry_price)) / target_distance
        if target_distance else 0.0
    )

    return {
        "bars_elapsed": float(index),
        "return_r": current,
        "mfe_r": mfe,
        "mae_r": mae,
        # How much of the best unrealized gain has already been handed back --
        # the clearest single deterioration signal in the set.
        "drawdown_from_peak_r": mfe - current,
        "bars_since_mfe": float(index - peak_index),
        # 1.0 = at entry, 0.0 = at the stop. Below 0 means already through it.
        "room_to_stop": 1.0 + current,
        "progress_to_target": progress_to_target,
        "velocity_r": velocity,
        "path_volatility_r": math.sqrt(variance),
        "adverse_fraction": sum(1 for r in returns_r if r < 0) / len(returns_r),
    }


@dataclass
class ExitSample:
    trade_id: str
    timestamp: str
    index: int
    features: Dict[str, float]
    label: int
    current_return_r: float
    final_return_r: float


def build_samples(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[ExitModelConfig] = None,
    bridge: Any = None,
) -> List[ExitSample]:
    """
    One sample per (trade, evolution point).

    `trade_id` is carried on every sample so splits can be grouped by trade.
    Without that grouping the same trade appears on both sides of the split and
    validation scores are meaningless -- adjacent points of one trade are nearly
    identical rows sharing a single outcome.
    """
    cfg = config or ExitModelConfig()
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
        entry_price = entry.get("price")
        stop_loss = entry.get("stop_loss")
        if not entry_price or not stop_loss:
            continue

        evolution = canonical.get("price_evolution") or []
        prices = [entry_price] + [
            point.get("price") for point in evolution
            if isinstance(point, dict) and point.get("price") is not None
        ]
        if len(prices) < cfg.min_bars_before_exit + 2:
            continue

        sign = _direction_sign(canonical.get("direction"))
        risk = abs(entry_price - stop_loss)
        if not risk:
            continue

        # Computed once per trade, not once per evolution point: these values
        # are decision-time constants, and recomputing them per point would
        # cost a full canonicalisation per sample for an identical result.
        context: Dict[str, float] = {}
        if cfg.include_context_features:
            from .price_evolution_bridge import context_features
            context = context_features(trade, bridge)

        # The label's source of truth. Preferred over the last observed price,
        # because the final evolution point is not necessarily the fill.
        close_price = (canonical.get("close_data") or {}).get("close_price")
        final_price = close_price if close_price else prices[-1]
        final_return_r = sign * (final_price - entry_price) / risk

        trade_id = str(canonical.get("trade_id") or canonical.get("ticket") or "")
        if not trade_id:
            continue

        analysis_features = {}
        for index in range(cfg.min_bars_before_exit, len(prices) - 1):
            features = path_features(
                prices, index, entry_price, stop_loss,
                entry.get("take_profit"), canonical.get("direction"),
            )
            if features is None:
                continue

            if cfg.include_context_features:
                features = {**features, **context}

            if cfg.include_analysis_features:
                point = evolution[index - 1] if 0 < index <= len(evolution) else {}
                analysis_features = {
                    f"analysis.{k}": v
                    for k, v in bridge._features(
                        (point.get("analysis") or {}).get("m1") or {}, "m1"
                    ).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
                features = {**features, **analysis_features}

            current_return_r = features["return_r"]
            samples.append(ExitSample(
                trade_id=trade_id,
                timestamp=str(canonical.get("opened_at") or ""),
                index=index,
                features=features,
                # Did holding from here hurt?
                label=int(final_return_r < current_return_r),
                current_return_r=current_return_r,
                final_return_r=final_return_r,
            ))

    return samples


def split_by_trade(
    samples: Sequence[ExitSample],
    test_fraction: float = 0.3,
) -> Tuple[List[ExitSample], List[ExitSample]]:
    """
    Chronological split on whole trades.

    Grouping is the point: a random row-level split would place points 4 and 5
    of the same trade on opposite sides, and the model would score brilliantly
    by recognising a trade it had already seen.
    """
    ordered_ids: List[str] = []
    for sample in sorted(samples, key=lambda s: (s.timestamp, s.trade_id)):
        if sample.trade_id not in ordered_ids:
            ordered_ids.append(sample.trade_id)

    if len(ordered_ids) < 2:
        return list(samples), []

    cut = max(1, int(len(ordered_ids) * (1.0 - test_fraction)))
    train_ids = set(ordered_ids[:cut])

    train = [s for s in samples if s.trade_id in train_ids]
    test = [s for s in samples if s.trade_id not in train_ids]
    return train, test


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    """Rank-based AUC; None when only one class is present."""
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None

    ranked = sorted(zip(scores, labels), key=lambda pair: pair[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        rank_sum += sum(average_rank for _, y in ranked[i:j + 1] if y == 1)
        i = j + 1

    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def expectancy_delta(
    samples: Sequence[ExitSample],
    scores: Sequence[float],
    threshold: float,
) -> Dict[str, Any]:
    """
    The acceptance criterion. AUC is not.

    Simulates the exit policy per trade: leave at the first point scoring above
    `threshold`, otherwise hold to the close. Reports mean R either way. A model
    that ranks well but does not move expectancy is not worth deploying -- the
    same standard that correctly stopped meta-labeling from shipping.
    """
    by_trade: Dict[str, List[Tuple[ExitSample, float]]] = {}
    for sample, score in zip(samples, scores):
        by_trade.setdefault(sample.trade_id, []).append((sample, score))

    baseline, with_policy, exits = [], [], 0
    for rows in by_trade.values():
        rows.sort(key=lambda pair: pair[0].index)
        final_r = rows[0][0].final_return_r
        baseline.append(final_r)

        realized = final_r
        for sample, score in rows:
            if score >= threshold:
                realized = sample.current_return_r
                exits += 1
                break
        with_policy.append(realized)

    if not baseline:
        return {"trades": 0, "baseline_r": None, "policy_r": None, "delta_r": None}

    mean_baseline = sum(baseline) / len(baseline)
    mean_policy = sum(with_policy) / len(with_policy)
    return {
        "trades": len(baseline),
        "baseline_r": round(mean_baseline, 4),
        "policy_r": round(mean_policy, 4),
        "delta_r": round(mean_policy - mean_baseline, 4),
        "early_exits": exits,
        "exit_rate": round(exits / len(baseline), 3),
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ExitModel:
    """
    Standardized logistic regression over causal path features.

    Persisted as JSON -- coefficients, scaler statistics, feature order and
    training provenance -- so an artifact can be read and audited without
    executing it, and cannot carry code the way a pickle can.
    """

    def __init__(self, config: Optional[ExitModelConfig] = None):
        self.config = config or ExitModelConfig()
        self.feature_names: List[str] = list(FEATURE_NAMES)
        self.coefficients: List[float] = []
        self.intercept: float = 0.0
        self.means: List[float] = []
        self.scales: List[float] = []
        self.fitted = False
        self.metadata: Dict[str, Any] = {}

    # -- vectorisation ----------------------------------------------------

    def _matrix(self, samples: Sequence[ExitSample]) -> List[List[float]]:
        return [
            [float(s.features.get(name, 0.0)) for name in self.feature_names]
            for s in samples
        ]

    def _standardize(self, rows: List[List[float]]) -> List[List[float]]:
        return [
            [(value - mean) / scale
             for value, mean, scale in zip(row, self.means, self.scales)]
            for row in rows
        ]

    # -- fitting ----------------------------------------------------------

    def fit(self, samples: Sequence[ExitSample]) -> Dict[str, Any]:
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required to fit the exit model.")
        if len({s.trade_id for s in samples}) < self.config.min_training_trades:
            raise ValueError(
                f"Need >= {self.config.min_training_trades} distinct trades, "
                f"got {len({s.trade_id for s in samples})}."
            )

        labels = [s.label for s in samples]
        if len(set(labels)) < 2:
            raise ValueError("Training data contains a single class.")

        if (self.config.include_analysis_features
                or self.config.include_context_features):
            extra = sorted({
                key for s in samples for key in s.features
                if key not in FEATURE_NAMES
            })
            self.feature_names = list(FEATURE_NAMES) + extra

        rows = self._matrix(samples)
        columns = list(zip(*rows))
        self.means = [sum(col) / len(col) for col in columns]
        self.scales = []
        for col, mean in zip(columns, self.means):
            variance = sum((v - mean) ** 2 for v in col) / len(col)
            deviation = math.sqrt(variance)
            # A constant column would divide by zero; 1.0 leaves it centred at
            # zero and therefore inert rather than infinite.
            self.scales.append(deviation if deviation > 1e-12 else 1.0)

        model = LogisticRegression(
            C=self.config.regularization_c,
            max_iter=1000,
            random_state=self.config.random_seed,
        )
        model.fit(self._standardize(rows), labels)

        self.coefficients = [float(c) for c in model.coef_[0]]
        self.intercept = float(model.intercept_[0])
        self.fitted = True
        self.metadata = {
            "version": EXIT_MODEL_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "samples": len(samples),
            "trades": len({s.trade_id for s in samples}),
            "positive_rate": round(sum(labels) / len(labels), 4),
            "feature_count": len(self.feature_names),
        }
        return dict(self.metadata)

    # -- inference --------------------------------------------------------

    def predict_proba(self, samples: Sequence[ExitSample]) -> List[float]:
        if not self.fitted:
            raise RuntimeError("Call fit() or load() before predicting.")
        scores = []
        for row in self._standardize(self._matrix(samples)):
            z = self.intercept + sum(c * v for c, v in zip(self.coefficients, row))
            z = max(-60.0, min(60.0, z))   # keep exp() finite
            scores.append(1.0 / (1.0 + math.exp(-z)))
        return scores

    def should_exit(
        self,
        prices: Sequence[float],
        entry_price: float,
        stop_loss: float,
        take_profit: Optional[float],
        direction: Any,
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Live decision for an open trade, given its price path so far.

        `prices` must start at entry and contain only observed prices. Returns
        a verdict plus the probability behind it, never a bare boolean, so the
        caller can log why.
        """
        index = len(prices) - 1
        features = path_features(prices, index, entry_price, stop_loss,
                                 take_profit, direction)
        if features is None or not self.fitted:
            return {"exit": False, "probability": None,
                    "reason": "insufficient_data" if features is None else "not_fitted"}

        sample = ExitSample("live", "", index, features, 0,
                            features["return_r"], 0.0)
        probability = self.predict_proba([sample])[0]
        cut = self.config.exit_threshold if threshold is None else threshold
        return {
            "exit": probability >= cut,
            "probability": round(probability, 4),
            "threshold": cut,
            "return_r": round(features["return_r"], 4),
            "drawdown_from_peak_r": round(features["drawdown_from_peak_r"], 4),
        }

    # -- persistence ------------------------------------------------------

    def save(self, path: str) -> str:
        payload = {
            "version": EXIT_MODEL_VERSION,
            "feature_names": self.feature_names,
            "coefficients": self.coefficients,
            "intercept": self.intercept,
            "means": self.means,
            "scales": self.scales,
            "config": asdict(self.config),
            "metadata": self.metadata,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    def load(self, path: str) -> "ExitModel":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if payload.get("version") != EXIT_MODEL_VERSION:
            raise ValueError(
                f"Artifact version {payload.get('version')} != {EXIT_MODEL_VERSION}. "
                "Feature semantics may differ; retrain rather than loading."
            )

        self.feature_names = list(payload["feature_names"])
        self.coefficients = list(payload["coefficients"])
        self.intercept = float(payload["intercept"])
        self.means = list(payload["means"])
        self.scales = list(payload["scales"])
        self.metadata = payload.get("metadata", {})
        self.fitted = True
        return self


# ---------------------------------------------------------------------------
# Noise floor
# ---------------------------------------------------------------------------

def permuted_path_trades(
    trades: Sequence[Mapping[str, Any]],
    seed: int = 0,
    bridge: Any = None,
    pool_across_trades: bool = False,
) -> List[Dict[str, Any]]:
    """
    Each real trade with its price INCREMENTS shuffled.

    This is the control that actually works here. A synthetic random walk does
    not: it has to guess the data's statistical character, and guessing wrong
    sets the bar in the wrong place -- a driftless walk and an
    iid-around-a-level series have very different exit-timing exploitability,
    and only one of them resembles the data.

    Permuting increments avoids guessing entirely. Entry, endpoint, length,
    volatility and the exact multiset of moves are all preserved -- the sum of
    increments is unchanged, so the trade still ends where it ended. The ONLY
    thing destroyed is the order in which the moves arrived.

    So the comparison is precise: a model whose edge is genuinely temporal
    (structure deteriorating over time) must lose ground when time is
    scrambled. A model whose "edge" is really "leave near the path's peak"
    scores the same on both, because peaks survive permutation -- and is
    correctly refused.

    `pool_across_trades` widens the null. Within-trade permutation preserves
    each trade's ENDPOINT, because the increments still sum to the same total.
    That is the right control when the label is about path shape (exit_model),
    but too weak when the label is endpoint-adjacent (target_model asks whether
    price runs further, which per-trade drift largely determines) -- the
    control would retain the very structure under test. Pooling increments
    across all trades and dealing them back out removes per-trade drift as
    well, while preserving the global distribution of moves.
    """
    import random as _random
    rng = _random.Random(seed)

    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    # Pass 1: collect usable trades and their increments.
    collected = []
    for index, trade in enumerate(trades or []):
        try:
            canonical = bridge.to_canonical(trade)
        except Exception:
            continue

        entry = canonical.get("entry") or {}
        entry_price = entry.get("price")
        evolution = canonical.get("price_evolution") or []
        prices = [p.get("price") for p in evolution
                  if isinstance(p, dict) and p.get("price") is not None]
        if not entry_price or len(prices) < 3:
            continue

        series = [entry_price] + prices
        collected.append((
            index, canonical, entry, entry_price,
            [b - a for a, b in zip(series, series[1:])],
        ))

    pool: List[float] = []
    if pool_across_trades:
        pool = [inc for _, _, _, _, increments in collected for inc in increments]
        rng.shuffle(pool)

    permuted, cursor = [], 0
    for index, canonical, entry, entry_price, increments in collected:
        if pool_across_trades:
            # Same count, drawn from the global pool: per-trade drift is gone.
            increments = pool[cursor:cursor + len(increments)]
            cursor += len(increments)
            if len(increments) < 3:
                continue
        else:
            increments = list(increments)
            rng.shuffle(increments)

        walked, price = [], entry_price
        for increment in increments:
            price += increment
            walked.append(price)

        permuted.append({
            "trade_id": f"perm-{index}",
            "ticket": f"perm-{index}",
            "symbol": canonical.get("symbol", "PERM"),
            "direction": canonical.get("direction", "BUY"),
            "opened_at": canonical.get("opened_at") or f"2026-01-01T00:{index:02d}:00Z",
            "entry": dict(entry),
            "analysis_at_open": {},
            "price_evolution": [
                {"timestamp": f"t{i}", "price": p} for i, p in enumerate(walked)
            ],
            # Within-trade permutation preserves the sum of increments and so
            # the endpoint; pooling deliberately does not.
            "close_data": {"close_price": walked[-1]},
        })
    return permuted


def _pipeline_score(
    trades: Sequence[Mapping[str, Any]],
    cfg: ExitModelConfig,
    bridge: Any = None,
) -> Dict[str, Any]:
    """Run fit -> predict -> score end to end. Used for both real and noise."""
    samples = build_samples(trades, cfg, bridge)
    if len(samples) < cfg.min_samples:
        return {"auc": None, "delta_r": None, "samples": len(samples)}

    train, test = split_by_trade(samples, cfg.test_fraction)
    if not test:
        return {"auc": None, "delta_r": None, "samples": len(samples)}

    model = ExitModel(cfg)
    try:
        model.fit(train)
    except (ValueError, ImportError) as exc:
        return {"auc": None, "delta_r": None, "error": str(exc)}

    scores = model.predict_proba(test)
    expectancy = expectancy_delta(test, scores, cfg.exit_threshold)
    return {
        "auc": roc_auc([s.label for s in test], scores),
        "delta_r": expectancy.get("delta_r"),
        "expectancy": expectancy,
        "samples": len(samples),
        "model": model,
        "test": test,
        "scores": scores,
    }


# ---------------------------------------------------------------------------
# Training with promotion gates
# ---------------------------------------------------------------------------

def train_and_validate(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[ExitModelConfig] = None,
    bridge: Any = None,
) -> Dict[str, Any]:
    """
    Fit, validate against a shuffled control, and decide promotion.

    `promoted` is only true when the model beats a shuffled-label control AND
    improves expectancy on held-out trades. Ranking ability alone is not
    sufficient; train_meta_label.py refused a model on exactly this basis and
    was right to.
    """
    import random as _random

    cfg = config or ExitModelConfig()
    report: Dict[str, Any] = {"version": EXIT_MODEL_VERSION, "promoted": False}

    samples = build_samples(trades, cfg, bridge)
    report["samples"] = len(samples)
    report["trades"] = len({s.trade_id for s in samples})

    if len(samples) < cfg.min_samples:
        report["rejected_because"] = (
            f"{len(samples)} samples < required {cfg.min_samples}")
        return report

    train, test = split_by_trade(samples, cfg.test_fraction)
    report["train_samples"], report["test_samples"] = len(train), len(test)
    if not test:
        report["rejected_because"] = "not enough distinct trades to hold any out"
        return report

    model = ExitModel(cfg)
    try:
        report["fit"] = model.fit(train)
    except (ValueError, ImportError) as exc:
        report["rejected_because"] = str(exc)
        return report

    scores = model.predict_proba(test)
    labels = [s.label for s in test]
    auc = roc_auc(labels, scores)
    report["test_auc"] = round(auc, 4) if auc is not None else None

    # Shuffled-label control, instance-scoped RNG so fitting a model never
    # perturbs the global stream.
    rng = _random.Random(cfg.random_seed)
    shuffled = list(train)
    shuffled_labels = [s.label for s in shuffled]
    rng.shuffle(shuffled_labels)
    control_samples = [
        ExitSample(s.trade_id, s.timestamp, s.index, s.features, y,
                   s.current_return_r, s.final_return_r)
        for s, y in zip(shuffled, shuffled_labels)
    ]
    control = ExitModel(cfg)
    control_auc = None
    try:
        control.fit(control_samples)
        control_auc = roc_auc(labels, control.predict_proba(test))
    except (ValueError, ImportError):
        pass
    report["control_auc"] = round(control_auc, 4) if control_auc is not None else None

    report["expectancy"] = expectancy_delta(test, scores, cfg.exit_threshold)

    # Noise floor: the same pipeline run on volatility-matched random walks.
    # Whatever it extracts from those is what the procedure produces from
    # nothing, and a real model has to clear it.
    noise = _pipeline_score(
        permuted_path_trades(trades, cfg.random_seed, bridge), cfg, bridge)
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

    # Fail closed: an uncomputable gate is an unmet gate. Skipping the floor
    # when the control cannot be scored would promote a model with its most
    # important safety check silently absent, and the report would look clean.
    if noise_delta is None or noise_auc is None:
        reasons.append(
            "noise floor could not be computed "
            f"({noise.get('samples', 0)} control samples, "
            f"{noise.get('error', 'insufficient data')}) -- refusing to promote "
            "without it")
    else:
        if delta is not None and delta - noise_delta < cfg.min_delta_over_noise_r:
            reasons.append(
                f"expectancy delta {delta}R does not beat the noise floor "
                f"{noise_delta}R by {cfg.min_delta_over_noise_r}R -- the same "
                f"pipeline achieves this on permuted paths")
        if auc is not None and auc - noise_auc < cfg.min_auc_over_noise:
            reasons.append(
                f"AUC {report['test_auc']} does not beat the noise-floor AUC "
                f"{round(noise_auc, 4)} by {cfg.min_auc_over_noise}")

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
            "exit_model",
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

def get_status(model: Optional[ExitModel] = None) -> Dict[str, Any]:
    cfg = ExitModelConfig()
    return {
        "component": "exit_model",
        "version": EXIT_MODEL_VERSION,
        "sklearn_available": SKLEARN_AVAILABLE,
        "trainable": SKLEARN_AVAILABLE,
        "model_loaded": bool(model and model.fitted),
        "feature_count": len(model.feature_names) if model else len(FEATURE_NAMES),
        "metadata": model.metadata if model else {},
        "promotion_gates": {
            "min_auc": cfg.min_auc,
            "min_auc_over_control": cfg.min_auc_over_control,
            "min_expectancy_gain_r": cfg.min_expectancy_gain_r,
            "min_training_trades": cfg.min_training_trades,
        },
        "exit_threshold": cfg.exit_threshold,
        "predicts_direction": False,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None) -> Dict[str, Any]:
    """
    Prove the sample-building path, including that features are causal.

    Returns the failure reason instead of raising, so it is safe to poll.
    """
    report: Dict[str, Any] = {"component": "exit_model", "ok": False, "checks": {}}
    try:
        samples = build_samples(trades or [], ExitModelConfig(), bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["samples_built"] = len(samples)
        report["checks"]["distinct_trades"] = len({s.trade_id for s in samples})

        if samples:
            train, test = split_by_trade(samples)
            train_ids = {s.trade_id for s in train}
            test_ids = {s.trade_id for s in test}
            report["checks"]["split_groups_disjoint"] = not (train_ids & test_ids)
            report["checks"]["label_balance"] = round(
                sum(s.label for s in samples) / len(samples), 3)
            report["checks"]["features_per_sample"] = len(samples[0].features)
            report["checks"]["no_nan_features"] = all(
                math.isfinite(v) for s in samples for v in s.features.values()
            )
            report["ok"] = bool(
                report["checks"]["split_groups_disjoint"]
                and report["checks"]["no_nan_features"]
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
                report["reason"] = "no exit samples could be built from the supplied trades"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "EXIT_MODEL_VERSION", "FEATURE_NAMES", "ExitModelConfig", "ExitSample",
    "ExitModel", "path_features", "build_samples", "split_by_trade",
    "roc_auc", "expectancy_delta", "train_and_validate", "permuted_path_trades",
    "get_status", "self_check",
]
