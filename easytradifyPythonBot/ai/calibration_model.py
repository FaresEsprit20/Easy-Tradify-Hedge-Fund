# ============================================================
# PROBABILITY CALIBRATION
# ============================================================
#
# Maps the probability the engine STATES onto the hit rate it ACTUALLY achieves.
#
# WHY THIS IS THE HIGHEST-CERTAINTY MODEL IN THE PLAN
# ---------------------------------------------------
# analyze_institutional_signal() emits `probability_percent`, and almost every
# downstream gate consumes it: the EV gate, the R:R floor, conviction, position
# sizing. If it says 72% and reality is 45%, every one of those decisions is
# wrong in the same direction, and no amount of work elsewhere repairs that.
#
# Replay already showed the number pinned at 13.0 across five instruments whose
# ATR spans a factor of 245. A probability that constant is not a probability.
#
# WHY AUC IS THE WRONG GATE HERE
# ------------------------------
# Calibration and discrimination are different properties, and this is the one
# model in the package where that distinction decides the design:
#
#   DISCRIMINATION  can the score separate winners from losers? (AUC)
#   CALIBRATION     when it says 70%, do 70% of them win?       (ECE / Brier)
#
# A model that always predicts the base rate is PERFECTLY calibrated and
# completely useless. So calibration error alone cannot be the gate either --
# it is trivially satisfied by discarding all information. This module reports
# the Brier decomposition (reliability, resolution, uncertainty) so both halves
# stay visible, and gates on improving calibration WITHOUT destroying
# resolution.
#
# THE DIAGNOSTIC THAT MATTERS MOST
# --------------------------------
# Isotonic regression is monotone: it can rescale a score but never reorder it.
# So if the stated probability carries no ranking information, calibration can
# only recentre it on the base rate. `input_is_informative` reports that
# directly, because it decides whether ANY downstream consumer that weights by
# this probability -- position sizing, the EV gate, conviction -- is reading
# information or noise.
# ============================================================

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from sklearn.isotonic import IsotonicRegression
    SKLEARN_AVAILABLE = True
except ImportError:
    IsotonicRegression = None
    SKLEARN_AVAILABLE = False

from .exit_model import roc_auc

CALIBRATION_MODEL_VERSION = "1.0"

# Where the stated probability lives, in preference order. The engine has moved
# this field before, so the fallbacks are load-bearing rather than defensive
# padding -- reading a stale path would silently yield no samples at all.
PROBABILITY_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("final_verdict", "probability_percent"),
    ("final_verdict", "probability_percent_post_chain"),
    ("directional_analysis", "best_probability"),
    ("entry", "probability_of_hit_percent"),
    ("⭐ CONFIDENCE",),
)


@dataclass
class CalibrationConfig:
    min_trades: int = 50
    test_fraction: float = 0.3
    bins: int = 10

    # Gates. Calibration must improve materially, and must not buy that
    # improvement by throwing away the score's ability to rank.
    min_ece_improvement: float = 0.02
    max_brier_increase: float = 0.0

    # Guards the "improved calibration by discarding information" failure --
    # a calibrator that maps everything to the base rate is perfectly
    # calibrated and worthless.
    #
    # Gated on AUC rather than binned resolution, which falls as a pure
    # measurement artifact whenever calibration compresses predictions into
    # fewer bins (measured: a correct calibrator taking ECE 0.167 -> 0.071 was
    # refused over a 0.0126 "resolution loss").
    #
    # The tolerance is 0.05, not ~0, because isotonic regression does NOT
    # preserve AUC exactly. It preserves ORDER but introduces TIES: pooling
    # adjacent violators flattens ranges of input onto one output value, and
    # tied pairs score 0.5 in AUC. Measured on overconfident data: AUC
    # 0.640 -> 0.602 while ECE improved 0.096. That loss is the method working,
    # not failing. The failure being guarded is COLLAPSE toward the base rate,
    # which `min_calibrated_auc_sigma` catches directly.
    max_auc_loss: float = 0.05

    # After calibration the score must still rank significantly better than
    # chance. This is the real "did it throw the information away" test.
    min_calibrated_auc_sigma: float = 2.0

    # Below this spread the stated probability is effectively a constant and
    # there is nothing to calibrate -- the honest answer is to say so rather
    # than fit a curve to a point.
    min_input_std: float = 0.01

    # Informativeness is decided by significance, not a fixed margin. A flat
    # threshold cannot work across sample sizes: with 400 random-labelled rows
    # an AUC of 0.5375 is ordinary sampling noise, yet it clears any small
    # constant. `auc_significance_sigma` is how many standard errors above 0.5
    # the AUC must sit, using the Hanley-McNeil standard error.
    auc_significance_sigma: float = 2.0

    random_seed: int = 42


@dataclass
class CalibrationSample:
    trade_id: str
    timestamp: str
    stated_probability: float   # 0..1
    outcome: int                # 1 = win


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _as_probability(value: Any) -> Optional[float]:
    """
    Coerce to 0..1, tolerating '72.5%' strings and 0-100 scales.

    A bare 1.0 is ambiguous -- 1% or 100%? -- but every other value above 1
    is unambiguously a percentage, so scale detection keys off that rather
    than guessing per value.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().rstrip("%"))
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None

    value = float(value)
    if value > 1.0:
        value = value / 100.0
    return value if 0.0 <= value <= 1.0 else None


def _dig(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def build_calibration_samples(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[CalibrationConfig] = None,
    bridge: Any = None,
) -> List[CalibrationSample]:
    """
    One sample per closed trade: what was claimed, and what happened.

    Unlike the path models there is exactly one row per trade, so no group-aware
    splitting is needed -- but the split stays chronological, because a
    calibration curve fitted on later trades and tested on earlier ones would
    borrow from the future.
    """
    cfg = config or CalibrationConfig()
    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    samples: List[CalibrationSample] = []
    for trade in trades or []:
        try:
            canonical = bridge.to_canonical(trade)
        except Exception:
            continue

        outcome_payload = bridge.to_outcome(canonical)
        success = outcome_payload.get("success")
        if success is None:
            continue   # still open, or no resolvable result

        analysis = canonical.get("analysis_at_open") or {}
        merged = {**analysis, "entry": canonical.get("entry") or {}}

        probability = None
        for path in PROBABILITY_PATHS:
            probability = _as_probability(_dig(merged, path))
            if probability is not None:
                break
        if probability is None:
            continue

        trade_id = str(canonical.get("trade_id") or canonical.get("ticket") or "")
        if not trade_id:
            continue

        samples.append(CalibrationSample(
            trade_id=trade_id,
            timestamp=str(canonical.get("opened_at") or ""),
            stated_probability=probability,
            outcome=int(success),
        ))

    return samples


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def reliability_curve(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    bins: int = 10,
) -> List[Dict[str, Any]]:
    """Per-bucket stated vs observed rate -- the human-readable form of ECE."""
    buckets: List[Dict[str, Any]] = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        rows = [
            (p, y) for p, y in zip(probabilities, outcomes)
            if (low <= p < high) or (index == bins - 1 and p == 1.0)
        ]
        if not rows:
            continue
        buckets.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "count": len(rows),
            "stated": round(sum(p for p, _ in rows) / len(rows), 4),
            "observed": round(sum(y for _, y in rows) / len(rows), 4),
        })
    return buckets


def expected_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    bins: int = 10,
) -> Optional[float]:
    """Sample-weighted mean gap between stated and observed rates."""
    if not probabilities:
        return None
    total = len(probabilities)
    error = 0.0
    for bucket in reliability_curve(probabilities, outcomes, bins):
        error += (bucket["count"] / total) * abs(bucket["stated"] - bucket["observed"])
    return round(error, 6)


def brier_decomposition(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    bins: int = 10,
) -> Dict[str, Optional[float]]:
    """
    Brier = reliability - resolution + uncertainty.

    Reported in full because the two components pull in opposite directions and
    a single number hides the trade-off: reliability improves by being honest,
    resolution improves by being decisive, and a model can raise one by
    sacrificing the other. Gating on the score alone would accept exactly that.
    """
    if not probabilities:
        return {"brier": None, "reliability": None,
                "resolution": None, "uncertainty": None}

    total = len(probabilities)
    base_rate = sum(outcomes) / total
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / total

    reliability = resolution = 0.0
    for bucket in reliability_curve(probabilities, outcomes, bins):
        weight = bucket["count"] / total
        reliability += weight * (bucket["stated"] - bucket["observed"]) ** 2
        resolution += weight * (bucket["observed"] - base_rate) ** 2

    return {
        "brier": round(brier, 6),
        "reliability": round(reliability, 6),   # lower is better
        "resolution": round(resolution, 6),     # higher is better
        "uncertainty": round(base_rate * (1 - base_rate), 6),
        "base_rate": round(base_rate, 4),
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class CalibrationModel:
    """
    Isotonic (monotone) mapping from stated probability to observed hit rate.

    Isotonic rather than Platt because the relationship need not be sigmoid --
    the failure it is correcting is arbitrary miscalibration, not a known
    parametric distortion. Persisted as JSON breakpoints: readable, auditable,
    and no pickle.
    """

    def __init__(self, config: Optional[CalibrationConfig] = None):
        self.config = config or CalibrationConfig()
        self.thresholds: List[float] = []
        self.values: List[float] = []
        self.fitted = False
        self.metadata: Dict[str, Any] = {}

    def fit(self, samples: Sequence[CalibrationSample]) -> Dict[str, Any]:
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required to fit the calibrator.")
        if len(samples) < self.config.min_trades:
            raise ValueError(
                f"Need >= {self.config.min_trades} resolved trades, got {len(samples)}.")

        outcomes = [s.outcome for s in samples]
        if len(set(outcomes)) < 2:
            raise ValueError("Training data contains a single outcome class.")

        probabilities = [s.stated_probability for s in samples]
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(probabilities, outcomes)

        self.thresholds = [float(x) for x in model.X_thresholds_]
        self.values = [float(y) for y in model.y_thresholds_]
        self.fitted = True
        self.metadata = {
            "version": CALIBRATION_MODEL_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "samples": len(samples),
            "base_rate": round(sum(outcomes) / len(outcomes), 4),
            "breakpoints": len(self.thresholds),
        }
        return dict(self.metadata)

    def calibrate(self, probability: float) -> float:
        """Piecewise-linear interpolation over the fitted breakpoints."""
        if not self.fitted:
            raise RuntimeError("Call fit() or load() before calibrating.")
        value = _as_probability(probability)
        if value is None:
            raise ValueError(f"Not a probability: {probability!r}")

        if value <= self.thresholds[0]:
            return self.values[0]
        if value >= self.thresholds[-1]:
            return self.values[-1]

        for index in range(1, len(self.thresholds)):
            if value <= self.thresholds[index]:
                x0, x1 = self.thresholds[index - 1], self.thresholds[index]
                y0, y1 = self.values[index - 1], self.values[index]
                if x1 == x0:
                    return y1
                return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
        return self.values[-1]

    def calibrate_many(self, probabilities: Sequence[float]) -> List[float]:
        return [self.calibrate(p) for p in probabilities]

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "version": CALIBRATION_MODEL_VERSION,
                "thresholds": self.thresholds,
                "values": self.values,
                "config": asdict(self.config),
                "metadata": self.metadata,
            }, handle, indent=2)
        return path

    def load(self, path: str) -> "CalibrationModel":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("version") != CALIBRATION_MODEL_VERSION:
            raise ValueError(
                f"Artifact version {payload.get('version')} != "
                f"{CALIBRATION_MODEL_VERSION}. Retrain rather than loading.")
        self.thresholds = list(payload["thresholds"])
        self.values = list(payload["values"])
        self.metadata = payload.get("metadata", {})
        self.fitted = True
        return self


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def auc_standard_error(auc: float, n_positive: int, n_negative: int) -> Optional[float]:
    """
    Hanley-McNeil standard error of an AUC.

    Needed because "is this AUC above 0.5" is a question about significance,
    not distance: 0.54 is noise at n=100 and a real effect at n=100_000.
    """
    if not n_positive or not n_negative:
        return None
    q1 = auc / (2.0 - auc)
    q2 = 2.0 * auc * auc / (1.0 + auc)
    variance = (
        auc * (1.0 - auc)
        + (n_positive - 1) * (q1 - auc * auc)
        + (n_negative - 1) * (q2 - auc * auc)
    ) / (n_positive * n_negative)
    return math.sqrt(variance) if variance > 0 else None


def diagnose_input(
    samples: Sequence[CalibrationSample],
    config: Optional[CalibrationConfig] = None,
) -> Dict[str, Any]:
    """
    Is the stated probability worth calibrating at all?

    This is the most consequential output in the module. Isotonic regression is
    monotone, so it can rescale a score but never reorder it: if the stated
    probability cannot rank winners above losers, calibration can only recentre
    everything on the base rate. Anything that weights by this probability would
    then treat every trade identically -- so this answer, not the calibrator
    merely existing, is what says whether the score is usable downstream.
    """
    cfg = config or CalibrationConfig()
    if not samples:
        return {"samples": 0, "input_is_informative": None}

    probabilities = [s.stated_probability for s in samples]
    outcomes = [s.outcome for s in samples]
    mean = sum(probabilities) / len(probabilities)
    std = math.sqrt(sum((p - mean) ** 2 for p in probabilities) / len(probabilities))
    auc = roc_auc(outcomes, probabilities)

    n_positive = sum(outcomes)
    n_negative = len(outcomes) - n_positive
    standard_error = (
        auc_standard_error(auc, n_positive, n_negative) if auc is not None else None)
    sigma = (
        abs(auc - 0.5) / standard_error
        if auc is not None and standard_error else None)

    notes = []
    if std < cfg.min_input_std:
        notes.append(
            f"stated probability is effectively constant (std {std:.4f}); "
            "there is no ordering to calibrate")
    if sigma is not None and sigma < cfg.auc_significance_sigma:
        notes.append(
            f"stated probability does not rank outcomes beyond noise "
            f"(AUC {auc:.4f}, {sigma:.1f} sigma); calibration can only "
            "recentre it on the base rate")
    elif sigma is None:
        notes.append("AUC could not be assessed (one outcome class)")

    return {
        "samples": len(samples),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "min": round(min(probabilities), 4),
        "max": round(max(probabilities), 4),
        "distinct_values": len(set(round(p, 4) for p in probabilities)),
        "auc": round(auc, 4) if auc is not None else None,
        "auc_standard_error": round(standard_error, 4) if standard_error else None,
        "auc_sigma": round(sigma, 2) if sigma is not None else None,
        "base_rate": round(sum(outcomes) / len(outcomes), 4),
        "input_is_informative": bool(
            std >= cfg.min_input_std
            and sigma is not None
            and sigma >= cfg.auc_significance_sigma
        ),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Training with promotion gates
# ---------------------------------------------------------------------------

def train_and_validate(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[CalibrationConfig] = None,
    bridge: Any = None,
) -> Dict[str, Any]:
    """
    Fit a calibrator and decide whether it earns promotion.

    Gates, in the order they matter:
      1. calibration error must fall materially
      2. resolution must not collapse -- otherwise the "improvement" is just
         the model discarding information and predicting the base rate
      3. Brier must not worsen overall
    """
    cfg = config or CalibrationConfig()
    report: Dict[str, Any] = {
        "version": CALIBRATION_MODEL_VERSION, "promoted": False}

    samples = build_calibration_samples(trades, cfg, bridge)
    report["samples"] = len(samples)
    report["diagnostics"] = diagnose_input(samples, cfg)

    if len(samples) < cfg.min_trades:
        report["rejected_because"] = (
            f"{len(samples)} resolved trades with a stated probability < "
            f"required {cfg.min_trades}")
        return report

    ordered = sorted(samples, key=lambda s: (s.timestamp, s.trade_id))
    cut = max(1, int(len(ordered) * (1.0 - cfg.test_fraction)))
    train, test = ordered[:cut], ordered[cut:]
    report["train_samples"], report["test_samples"] = len(train), len(test)
    if not test:
        report["rejected_because"] = "no trades left to hold out"
        return report

    model = CalibrationModel(cfg)
    try:
        report["fit"] = model.fit(train)
    except (ValueError, ImportError) as exc:
        report["rejected_because"] = str(exc)
        return report

    raw = [s.stated_probability for s in test]
    outcomes = [s.outcome for s in test]
    calibrated = model.calibrate_many(raw)

    report["before"] = {
        "ece": expected_calibration_error(raw, outcomes, cfg.bins),
        **brier_decomposition(raw, outcomes, cfg.bins),
        "reliability_curve": reliability_curve(raw, outcomes, cfg.bins),
    }
    report["after"] = {
        "ece": expected_calibration_error(calibrated, outcomes, cfg.bins),
        **brier_decomposition(calibrated, outcomes, cfg.bins),
        "reliability_curve": reliability_curve(calibrated, outcomes, cfg.bins),
    }

    before, after = report["before"], report["after"]
    reasons = []

    if before["ece"] is None or after["ece"] is None:
        reasons.append("calibration error could not be computed on the held-out set")
    else:
        improvement = before["ece"] - after["ece"]
        report["ece_improvement"] = round(improvement, 6)
        if improvement < cfg.min_ece_improvement:
            reasons.append(
                f"calibration error improved by {improvement:.4f} < required "
                f"{cfg.min_ece_improvement}")

    # Reported for information; NOT gated. See max_auc_loss for why binned
    # resolution is the wrong instrument here.
    report["resolution_loss"] = round(
        (before["resolution"] or 0.0) - (after["resolution"] or 0.0), 6)

    auc_before = roc_auc(outcomes, raw)
    auc_after = roc_auc(outcomes, calibrated)
    report["auc_before"] = round(auc_before, 4) if auc_before is not None else None
    report["auc_after"] = round(auc_after, 4) if auc_after is not None else None
    if auc_before is not None and auc_after is not None:
        auc_loss = auc_before - auc_after
        report["auc_loss"] = round(auc_loss, 6)
        if auc_loss > cfg.max_auc_loss:
            reasons.append(
                f"ranking power fell too far (AUC {auc_before:.4f} -> "
                f"{auc_after:.4f}, loss {auc_loss:.4f} > {cfg.max_auc_loss})")

        # The collapse test: did calibration destroy ranking that was there?
        #
        # Applied ONLY when the raw score ranked significantly on this same
        # held-out set. Calibration's job is to fix the LEVEL, not to prove
        # discrimination -- demanding significance from the output when the
        # input never had it would reject correct calibrators for a defect in
        # the upstream probability. Both sides are measured on the test set so
        # the comparison is like for like; measuring input significance on the
        # full sample and output significance on the split is not.
        n_positive = sum(outcomes)
        n_negative = len(outcomes) - n_positive
        raw_error = auc_standard_error(auc_before, n_positive, n_negative)
        calibrated_error = auc_standard_error(auc_after, n_positive, n_negative)

        raw_sigma = abs(auc_before - 0.5) / raw_error if raw_error else None
        sigma = abs(auc_after - 0.5) / calibrated_error if calibrated_error else None
        report["raw_auc_sigma"] = round(raw_sigma, 2) if raw_sigma else None
        report["calibrated_auc_sigma"] = round(sigma, 2) if sigma else None

        raw_ranked = (
            raw_sigma is not None and raw_sigma >= cfg.min_calibrated_auc_sigma)
        if raw_ranked and sigma is not None and sigma < cfg.min_calibrated_auc_sigma:
            reasons.append(
                f"calibration destroyed ranking that was present "
                f"(AUC {auc_before:.4f} at {raw_sigma:.1f} sigma -> "
                f"{auc_after:.4f} at {sigma:.1f} sigma)")

    brier_increase = (after["brier"] or 0.0) - (before["brier"] or 0.0)
    report["brier_change"] = round(brier_increase, 6)
    if brier_increase > cfg.max_brier_increase:
        reasons.append(f"Brier score worsened by {brier_increase:.4f}")

    # Not a rejection: a calibrator over an uninformative score is still
    # honest, it simply cannot rank. Downstream sizing needs to know.
    if not report["diagnostics"].get("input_is_informative"):
        report["warning"] = (
            "stated probability carries little or no ranking information; "
            "calibration corrects its level but cannot create discrimination. "
            "Anything weighting by this score would size every trade alike.")

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
            "calibration_model",
            payload={key: value for key, value in report.items()
                     if key not in ("model", "rules_model", "governance")},
            metrics={key: report.get(key) for key in ("brier_change", "samples", "ece")
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

def get_status(model: Optional[CalibrationModel] = None) -> Dict[str, Any]:
    cfg = CalibrationConfig()
    return {
        "component": "calibration_model",
        "version": CALIBRATION_MODEL_VERSION,
        "sklearn_available": SKLEARN_AVAILABLE,
        "trainable": SKLEARN_AVAILABLE,
        "model_loaded": bool(model and model.fitted),
        "metadata": model.metadata if model else {},
        "method": "isotonic (monotone, non-parametric)",
        "measures": ["ece", "brier", "reliability", "resolution"],
        "gates_on_auc": False,
        "why_not_auc": (
            "calibration and discrimination are different properties; a base-rate "
            "predictor is perfectly calibrated and useless, so resolution is "
            "gated alongside calibration error"),
        "promotion_gates": {
            "min_ece_improvement": cfg.min_ece_improvement,
            "max_auc_loss": cfg.max_auc_loss,
            "max_brier_increase": cfg.max_brier_increase,
            "min_trades": cfg.min_trades,
        },
        "informativeness_decides": (
            "whether any downstream consumer weighting by this probability is "
            "reading information or noise"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None) -> Dict[str, Any]:
    """Prove extraction works and report whether the input is worth calibrating."""
    report: Dict[str, Any] = {
        "component": "calibration_model", "ok": False, "checks": {}}
    try:
        samples = build_calibration_samples(trades or [], CalibrationConfig(), bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["samples_built"] = len(samples)

        if samples:
            report["checks"]["probabilities_in_range"] = all(
                0.0 <= s.stated_probability <= 1.0 for s in samples)
            report["checks"]["outcomes_binary"] = {
                s.outcome for s in samples} <= {0, 1}
            report["diagnostics"] = diagnose_input(samples)
            report["checks"]["input_is_informative"] = (
                report["diagnostics"]["input_is_informative"])
            report["ok"] = bool(
                report["checks"]["probabilities_in_range"]
                and report["checks"]["outcomes_binary"]
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
                report["reason"] = "no trade carried both a stated probability and a resolved outcome"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "CALIBRATION_MODEL_VERSION", "PROBABILITY_PATHS", "CalibrationConfig",
    "CalibrationSample", "CalibrationModel", "build_calibration_samples",
    "reliability_curve", "expected_calibration_error", "brier_decomposition",
    "diagnose_input", "auc_standard_error", "train_and_validate",
    "get_status", "self_check",
]
