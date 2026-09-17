# ============================================================
# MODEL PERFORMANCE -- PER-MODEL SCORECARDS AND ENSEMBLE ANALYSIS
# ============================================================
#
# WHAT THIS ANSWERS
# -----------------
# Which models are actually earning their place, and whether combining them
# beats using one. Every model in this package could report whether it was
# FITTED; none could report whether it was RIGHT once a trade settled. A model
# that trained successfully and predicts badly looked identical to a good one
# from every status endpoint in the system.
#
# EXPECTANCY IN R, NOT ACCURACY
# -----------------------------
# The headline metric is mean R per decision. Accuracy is close to useless
# here and actively misleading: a model that is right 70% of the time with
# +0.3R wins and -1.0R losses loses money, and a 40%-accurate model taking
# +3R wins prints. Direction entropy in this system was measured at 1.0000 --
# direction is a coin flip -- so any metric that rewards being right rather
# than being right when it pays will select for noise.
#
# WHAT THE ENSEMBLE SECTION IS FOR
# --------------------------------
# The genuinely useful question is not "which model is best" but "does the
# disagreement carry information". If every model agrees on every trade, the
# ensemble is one model wearing six hats and the extra five cost latency for
# nothing. If outcomes are materially better when models AGREE, then
# agreement is a tradeable filter and abstention has somewhere to look. That
# comparison is computed here, with sample sizes attached.
#
# WHAT THIS IS NOT
# ----------------
# Observational, not causal. These records are what the models said and what
# subsequently happened; nothing here randomised anything. A model that scores
# well may simply have been consulted on easier trades. Causal claims need the
# A/B machinery in model_governance, and the wording throughout keeps that
# distinction rather than blurring it.
# ============================================================

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

PERFORMANCE_VERSION = "1.0"

_LOCK = threading.RLock()

# Below this many settled records a model gets no verdict. Reporting an
# expectancy on nine trades is how a rounding error becomes a strategy.
MIN_RECORDS_FOR_VERDICT = 30


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@dataclass
class PredictionRecord:
    """
    One model's stated position on one trade, and what happened.

    `predicted_at` and `settled_at` are separate because the gap between them
    is the only thing that makes this a prediction rather than a description.
    A record whose prediction timestamp is missing cannot be shown to have
    preceded its outcome, and is reported as unverifiable rather than counted.
    """

    model: str
    trade_id: str
    prediction: Optional[str] = None          # e.g. ENTER / DECLINE / EXTEND
    probability: Optional[float] = None       # stated probability, if any
    outcome: Optional[int] = None             # 1 win, 0 loss
    realized_r: Optional[float] = None
    version: Optional[str] = None             # registry version in force
    arm: Optional[str] = None                 # A/B arm, if under experiment
    predicted_at: Optional[str] = None
    settled_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def settled(self) -> bool:
        return self.outcome is not None or self.realized_r is not None

    @property
    def temporally_valid(self) -> bool:
        """Prediction must precede settlement, or it is not a prediction."""
        if not self.predicted_at or not self.settled_at:
            return False
        return str(self.predicted_at) <= str(self.settled_at)


def expectancy(records: Sequence[PredictionRecord]) -> Optional[float]:
    """Mean R per decision. None when nothing resolved, never 0.0."""
    values = [_number(r.realized_r) for r in records]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def win_rate(records: Sequence[PredictionRecord]) -> Optional[float]:
    outcomes = [r.outcome for r in records if r.outcome is not None]
    return sum(outcomes) / len(outcomes) if outcomes else None


def brier_score(records: Sequence[PredictionRecord]) -> Optional[float]:
    """
    Mean squared error of stated probabilities.

    Only over records that carry BOTH a probability and an outcome. A model
    that states no probability gets None here rather than a flattering zero.
    """
    pairs = [(_number(r.probability), r.outcome) for r in records]
    pairs = [(p, o) for p, o in pairs if p is not None and o is not None]
    if not pairs:
        return None
    scaled = [(p / 100.0 if p > 1.0 else p, o) for p, o in pairs]
    return sum((p - o) ** 2 for p, o in scaled) / len(scaled)


def standard_error_of_mean(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


class PerformanceTracker:
    """
    Records what each model said and what happened, and scores it.

    Records are kept per model rather than aggregated on write, because the
    interesting questions -- drift, agreement, per-version comparison -- all
    need the individual rows. Aggregating early would answer today's question
    and destroy tomorrow's.
    """

    MAX_RECORDS_PER_MODEL = 5000

    def __init__(self, store: Any = None, name: str = "model_performance"):
        from .model_governance import GovernanceStore

        self.name = name
        self.store = store or GovernanceStore()
        self.records: Dict[str, List[PredictionRecord]] = {}
        self._load()

    # -- persistence --------------------------------------------------------

    def _path_name(self) -> str:
        return self.name

    def _load(self) -> None:
        raw = self.store.load_registry(self._path_name()) or {}
        for model, rows in (raw.get("records") or {}).items():
            self.records[model] = [
                PredictionRecord(**row) for row in rows if isinstance(row, Mapping)
            ]

    def _persist(self) -> None:
        self.store.save_registry(self._path_name(), {
            "version": PERFORMANCE_VERSION,
            "updated_at": _utc_now(),
            "records": {
                model: [r.to_dict() for r in rows[-self.MAX_RECORDS_PER_MODEL:]]
                for model, rows in self.records.items()
            },
        })

    # -- recording ----------------------------------------------------------

    def record(self, model: str, trade_id: Any, **fields: Any) -> PredictionRecord:
        """Record one model's position on one trade."""
        with _LOCK:
            entry = PredictionRecord(
                model=str(model), trade_id=str(trade_id), **fields)
            self.records.setdefault(entry.model, []).append(entry)
            self._persist()
            return entry

    def record_many(self, rows: Sequence[Mapping[str, Any]]) -> int:
        with _LOCK:
            count = 0
            for row in rows or []:
                data = dict(row)
                model = data.pop("model", None)
                trade_id = data.pop("trade_id", None)
                if model is None or trade_id is None:
                    continue
                entry = PredictionRecord(
                    model=str(model), trade_id=str(trade_id), **data)
                self.records.setdefault(entry.model, []).append(entry)
                count += 1
            self._persist()
            return count

    def settled_records(self, model: str) -> List[PredictionRecord]:
        return [r for r in self.records.get(model, []) if r.settled]

    # -- scoring ------------------------------------------------------------

    def scorecard(self, model: str) -> Dict[str, Any]:
        """
        One model's performance, with the sample size that produced it.

        `verdict` stays INSUFFICIENT_DATA below MIN_RECORDS_FOR_VERDICT no
        matter how good the numbers look. An expectancy computed on nine
        trades is a rounding error with a decimal point.
        """
        rows = self.records.get(model, [])
        settled = [r for r in rows if r.settled]
        returns = [v for v in (_number(r.realized_r) for r in settled)
                   if v is not None]

        mean_r = expectancy(settled)
        error = standard_error_of_mean(returns) if returns else None

        card: Dict[str, Any] = {
            "model": model,
            "records": len(rows),
            "settled": len(settled),
            "unsettled": len(rows) - len(settled),
            "expectancy_r": round(mean_r, 4) if mean_r is not None else None,
            "expectancy_standard_error": (
                round(error, 4) if error is not None else None),
            "win_rate": win_rate(settled),
            "brier": (round(brier_score(settled), 6)
                      if brier_score(settled) is not None else None),
            "temporally_valid": sum(1 for r in settled if r.temporally_valid),
            "versions_seen": sorted({r.version for r in rows if r.version}),
        }

        if len(settled) < MIN_RECORDS_FOR_VERDICT:
            card["verdict"] = "INSUFFICIENT_DATA"
            card["verdict_reason"] = (
                "%d settled records; %d required"
                % (len(settled), MIN_RECORDS_FOR_VERDICT))
            return card

        # Distinguishable from zero expectancy? Two standard errors is the
        # bar, and it is stated so a reader can disagree with it.
        if mean_r is None:
            card["verdict"] = "UNMEASURABLE"
        elif error is None or error == 0:
            # Zero variance is the STRONGEST evidence available, not the
            # weakest. A model returning exactly -1.0R on eighty consecutive
            # trades has no sampling error to speak of, and the first version
            # of this branch called that "UNMEASURABLE" -- reporting the most
            # clear-cut loser in the system as unknowable. Only a zero mean
            # with zero spread is genuinely uninformative.
            card["verdict"] = ("INDISTINGUISHABLE_FROM_ZERO" if mean_r == 0
                               else "POSITIVE" if mean_r > 0 else "NEGATIVE")
        elif mean_r > 2 * error:
            card["verdict"] = "POSITIVE"
        elif mean_r < -2 * error:
            card["verdict"] = "NEGATIVE"
        else:
            card["verdict"] = "INDISTINGUISHABLE_FROM_ZERO"
        card["verdict_reason"] = (
            "expectancy %.4fR against a standard error of %.4fR"
            % (mean_r, error) if (mean_r is not None and error is not None)
            else "expectancy or its error could not be computed")
        card["observational"] = True
        return card

    def all_scorecards(self) -> Dict[str, Any]:
        return {model: self.scorecard(model) for model in sorted(self.records)}

    def ranking(self) -> List[Dict[str, Any]]:
        """
        Models ordered by expectancy, with the unrankable named rather than
        silently sorted to the bottom.
        """
        cards = [self.scorecard(model) for model in sorted(self.records)]
        rankable = [c for c in cards if c.get("expectancy_r") is not None
                    and c["verdict"] != "INSUFFICIENT_DATA"]
        rankable.sort(key=lambda c: -c["expectancy_r"])
        unrankable = [c["model"] for c in cards if c not in rankable]
        return [{"ranked": rankable, "unrankable": unrankable}]

    # -- drift --------------------------------------------------------------

    def drift(self, model: str, window: int = 50) -> Dict[str, Any]:
        """
        Has recent performance moved away from the earlier baseline?

        Compares the last `window` settled records against everything before
        them. Reported as a difference with a standard error, not as a
        yes/no: a model whose expectancy fell 0.05R on 30 trades has not
        drifted, it has been observed on a Tuesday.
        """
        settled = self.settled_records(model)
        if len(settled) < 2 * window:
            return {
                "model": model, "drifted": None,
                "reason": "need %d settled records, have %d"
                          % (2 * window, len(settled)),
            }

        baseline, recent = settled[:-window], settled[-window:]
        baseline_r = expectancy(baseline)
        recent_r = expectancy(recent)
        if baseline_r is None or recent_r is None:
            return {"model": model, "drifted": None,
                    "reason": "no resolved returns in one of the periods"}

        baseline_values = [v for v in (_number(r.realized_r) for r in baseline)
                           if v is not None]
        recent_values = [v for v in (_number(r.realized_r) for r in recent)
                         if v is not None]
        baseline_error = standard_error_of_mean(baseline_values) or 0.0
        recent_error = standard_error_of_mean(recent_values) or 0.0
        combined = math.sqrt(baseline_error ** 2 + recent_error ** 2)
        delta = recent_r - baseline_r

        return {
            "model": model,
            "baseline_expectancy_r": round(baseline_r, 4),
            "recent_expectancy_r": round(recent_r, 4),
            "delta_r": round(delta, 4),
            "standard_error": round(combined, 4) if combined else None,
            "drifted": bool(combined and abs(delta) > 2 * combined),
            "baseline_samples": len(baseline),
            "recent_samples": len(recent),
            "note": ("a difference inside two standard errors is not drift, "
                     "it is sampling"),
        }

    # -- ensemble -----------------------------------------------------------

    def agreement(self, models: Optional[Sequence[str]] = None
                  ) -> Dict[str, Any]:
        """
        Do outcomes differ when models agree versus disagree?

        This is the question that decides whether an ensemble is worth its
        latency. If agreement carries no expectancy difference, the extra
        models are decoration; if it does, agreement is a filter abstention
        can use.

        Trades are grouped by id, and only trades where at least two models
        stated a prediction are counted -- "agreement" among one model is not
        agreement.
        """
        chosen = list(models or self.records.keys())
        by_trade: Dict[str, Dict[str, PredictionRecord]] = {}
        for model in chosen:
            for row in self.records.get(model, []):
                if row.prediction is None:
                    continue
                by_trade.setdefault(row.trade_id, {})[model] = row

        agreed: List[float] = []
        disagreed: List[float] = []
        compared = 0
        for rows in by_trade.values():
            if len(rows) < 2:
                continue
            returns = [_number(r.realized_r) for r in rows.values()]
            returns = [v for v in returns if v is not None]
            if not returns:
                continue
            compared += 1
            predictions = {r.prediction for r in rows.values()}
            # One R per trade, not one per model: a trade with six models
            # attached would otherwise count six times and inflate every
            # sample size sixfold.
            realized = returns[0]
            (agreed if len(predictions) == 1 else disagreed).append(realized)

        agreed_r = sum(agreed) / len(agreed) if agreed else None
        disagreed_r = sum(disagreed) / len(disagreed) if disagreed else None
        difference = (agreed_r - disagreed_r
                      if agreed_r is not None and disagreed_r is not None
                      else None)

        enough = (len(agreed) >= MIN_RECORDS_FOR_VERDICT
                  and len(disagreed) >= MIN_RECORDS_FOR_VERDICT)
        return {
            "models": chosen,
            "trades_compared": compared,
            "unanimous": {"trades": len(agreed),
                          "expectancy_r": (round(agreed_r, 4)
                                           if agreed_r is not None else None)},
            "split": {"trades": len(disagreed),
                      "expectancy_r": (round(disagreed_r, 4)
                                       if disagreed_r is not None else None)},
            "difference_r": round(difference, 4) if difference is not None else None,
            "verdict": ("AGREEMENT_CARRIES_SIGNAL"
                        if enough and difference is not None and difference > 0.1
                        else "NO_MEASURED_BENEFIT" if enough
                        else "INSUFFICIENT_DATA"),
            "why": ("if outcomes are no better when models agree, the extra "
                    "models are not adding information"),
            "observational": True,
        }

    def coverage(self) -> Dict[str, Any]:
        """Which governed models have any performance record at all."""
        from .model_governance import GOVERNED_MODELS

        tracked = set(self.records)
        return {
            "governed_models": list(GOVERNED_MODELS),
            "tracked": sorted(tracked),
            # Named explicitly: a governed model with no records is invisible
            # to every scorecard, and silence there reads like health.
            "untracked": sorted(set(GOVERNED_MODELS) - tracked),
            "records_total": sum(len(v) for v in self.records.values()),
        }

    def reset(self, model: Optional[str] = None) -> None:
        with _LOCK:
            if model:
                self.records.pop(model, None)
            else:
                self.records.clear()
            self._persist()


_TRACKER: Optional[PerformanceTracker] = None


def get_tracker(store: Any = None) -> PerformanceTracker:
    """Process-wide tracker. An explicit store bypasses the cache."""
    global _TRACKER
    if store is not None:
        return PerformanceTracker(store)
    with _LOCK:
        if _TRACKER is None:
            _TRACKER = PerformanceTracker()
        return _TRACKER


def reset_tracker() -> None:
    global _TRACKER
    with _LOCK:
        _TRACKER = None


def get_status() -> Dict[str, Any]:
    tracker = get_tracker()
    return {
        "component": "model_performance",
        "version": PERFORMANCE_VERSION,
        "headline_metric": "expectancy in R per decision",
        "why_not_accuracy": (
            "direction entropy here measured 1.0000; a metric that rewards "
            "being right rather than being right when it pays selects noise"),
        "min_records_for_verdict": MIN_RECORDS_FOR_VERDICT,
        "observational_only": True,
        "coverage": tracker.coverage(),
        "scorecards": tracker.all_scorecards(),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove scoring, gating, drift and agreement behave under known inputs.

    Built on synthetic records with known answers rather than on whatever
    happens to be stored: a scorecard that cannot be shown to report a
    NEGATIVE model as negative is not a scorecard.
    """
    report: Dict[str, Any] = {
        "component": "model_performance", "ok": False, "checks": {}}
    try:
        import tempfile

        from .model_governance import GovernanceStore

        checks = report["checks"]
        with tempfile.TemporaryDirectory() as directory:
            tracker = PerformanceTracker(GovernanceStore(directory))

            # A thin sample must refuse to produce a verdict.
            for index in range(5):
                tracker.record("thin", "t%d" % index, realized_r=3.0, outcome=1)
            checks["thin_sample_refuses_verdict"] = (
                tracker.scorecard("thin")["verdict"] == "INSUFFICIENT_DATA")

            # A clearly losing model must be reported as losing.
            for index in range(80):
                tracker.record("loser", "l%d" % index,
                               realized_r=-1.0, outcome=0, prediction="ENTER")
            loser = tracker.scorecard("loser")
            checks["negative_model_is_negative"] = loser["verdict"] == "NEGATIVE"
            checks["expectancy_in_r"] = loser["expectancy_r"] == -1.0

            # A coin-flip model must NOT read as positive.
            for index in range(120):
                tracker.record("noise", "n%d" % index,
                               realized_r=(1.0 if index % 2 else -1.0),
                               outcome=index % 2, prediction="ENTER")
            checks["noise_is_not_positive"] = (
                tracker.scorecard("noise")["verdict"]
                != "POSITIVE")

            # Brier only where a probability was actually stated.
            checks["brier_absent_without_probability"] = (
                tracker.scorecard("loser")["brier"] is None)

            # Drift must refuse on too little history, and detect a real shift.
            checks["drift_refuses_thin"] = (
                tracker.drift("thin", window=50)["drifted"] is None)
            for index in range(60):
                tracker.record("shift", "s%d" % index, realized_r=1.0, outcome=1)
            for index in range(60):
                tracker.record("shift", "x%d" % index, realized_r=-1.0, outcome=0)
            checks["drift_detected"] = bool(
                tracker.drift("shift", window=50).get("drifted"))

            # Agreement must count one R per TRADE, not one per model.
            for index in range(40):
                for model in ("a", "b"):
                    tracker.record(model, "shared%d" % index,
                                   prediction="ENTER", realized_r=1.0, outcome=1)
            agreement = tracker.agreement(["a", "b"])
            checks["agreement_counts_trades_not_rows"] = (
                agreement["unanimous"]["trades"] == 40)

            # Untracked governed models are named rather than hidden.
            checks["untracked_models_named"] = bool(
                tracker.coverage()["untracked"])

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "PERFORMANCE_VERSION", "MIN_RECORDS_FOR_VERDICT", "PredictionRecord",
    "PerformanceTracker", "get_tracker", "reset_tracker",
    "expectancy", "win_rate", "brier_score", "standard_error_of_mean",
    "get_status", "self_check",
]
