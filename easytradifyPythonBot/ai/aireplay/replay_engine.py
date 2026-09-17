# ============================================================
# AI_MarketReplay -- PHASE 3, items 1-6
# Event model, temporal aligner, reality/decision reconstruction,
# first-divergence detection, attribution
# ============================================================
#
# Implements readme sections 16 (Replay Event Model), 17 (Replay Decision
# Timeline) and 18 (Replay Error Attribution).
#
# WHAT REPLAY IS FOR
# ------------------
# Not "did the trade win". The specification's question is: what did the
# strategy believe at T0, what actually happened afterwards, and WHERE did the
# two first part company. A loss with a divergence at T+1 is a different
# defect from a loss with a divergence at T+9, and the outcome alone cannot
# tell them apart.
#
# THE FOUR FIRSTS
# ---------------
# Section 17 is explicit that these are distinct and "not necessarily the same
# timestamp":
#
#   first_anomaly            something unusual appeared
#   first_prediction_error   reality contradicted the stated read
#   first_decision_error     the system should have acted and did not
#   first_material_divergence  the thesis broke by more than noise
#
# Collapsing them into one number is what makes post-mortems useless: "the
# trade lost" is not a diagnosis, and neither is a single divergence bar when
# the anomaly preceded it by four bars.
#
# WHAT THIS CAN AND CANNOT SEE
# ----------------------------
# The pre-trade events (CANDIDATE_DETECTED, CONFIRMATION,
# MICROSTRUCTURE_TRIGGER, RISK_APPROVAL) are not in historical storage -- the
# live pipeline never emitted them, and ai/aireplay/recorder.py exists to fix
# that going forward. Their absence limits explaining WHY an entry was taken.
# It does not block divergence detection, which is entirely about what
# happened AFTER entry, and for that both halves are already stored: the T0
# belief in analysis_at_open and the reality path in price_evolution, which
# carries its own per-timeframe analysis at every point.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import Provenance, SCHEMA_VERSION, content_hash, utc_now

REPLAY_ENGINE_VERSION = "1.0"


class EventType(str, Enum):
    """Readme section 16 event types (the subset historical data supports)."""

    MARKET_SNAPSHOT = "MARKET_SNAPSHOT"
    FEATURE_SNAPSHOT = "FEATURE_SNAPSHOT"
    SYNTHESIS_UPDATE = "SYNTHESIS_UPDATE"
    PRICE_UPDATE = "PRICE_UPDATE"
    POSITION_UPDATE = "POSITION_UPDATE"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    EXIT_EVENT = "EXIT_EVENT"
    OUTCOME_EVENT = "OUTCOME_EVENT"


class FailureClass(str, Enum):
    """Readme section 18 attribution layers."""

    DATA = "DATA"
    FEATURE = "FEATURE"
    STRUCTURE = "STRUCTURE"
    LIQUIDITY = "LIQUIDITY"
    MICROSTRUCTURE = "MICROSTRUCTURE"
    MARKET_SYNTHESIS = "MARKET_SYNTHESIS"
    CALIBRATION = "CALIBRATION"
    TRADE_QUALITY = "TRADE_QUALITY"
    EXECUTION = "EXECUTION"
    SPREAD = "SPREAD"
    REGIME = "REGIME"
    UNKNOWN = "UNKNOWN"


@dataclass
class ReplayEvent:
    """Readme section 16. `available_at` is what makes lookahead checkable."""

    event_id: str
    event_type: EventType
    timestamp: str
    source: str
    payload: Dict[str, Any] = field(default_factory=dict)
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    available_at: Optional[str] = None
    index: int = 0
    version: str = SCHEMA_VERSION
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return payload


class EventStream:
    """
    Immutable chronological event stream (readme section 16).

    `up_to(index)` is the lookahead firewall: any analysis of what was
    knowable at a point must go through it rather than indexing the list
    directly, so a future event cannot be read by accident.
    """

    def __init__(self, events: Sequence[ReplayEvent]):
        # Sorted by (timestamp, index): index breaks ties so events recorded
        # within the same second keep the order they occurred, which a plain
        # timestamp sort would scramble.
        self._events: Tuple[ReplayEvent, ...] = tuple(
            sorted(events, key=lambda e: (str(e.timestamp), e.index)))

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    def __getitem__(self, index: int) -> ReplayEvent:
        return self._events[index]

    @property
    def events(self) -> Tuple[ReplayEvent, ...]:
        return self._events

    def up_to(self, index: int) -> Tuple[ReplayEvent, ...]:
        """Everything knowable at `index`, inclusive. Never beyond."""
        return self._events[: index + 1]

    def of_type(self, event_type: EventType) -> List[ReplayEvent]:
        return [e for e in self._events if e.event_type is event_type]

    def is_ordered(self) -> bool:
        stamps = [(str(e.timestamp), e.index) for e in self._events]
        return stamps == sorted(stamps)

    def hash(self) -> str:
        return content_hash({"events": [e.to_dict() for e in self._events]})


# ---------------------------------------------------------------------------
# Item 1 + 2 -- event model and temporal alignment
# ---------------------------------------------------------------------------

def build_event_stream(canonical_trade: Any) -> EventStream:
    """
    Phase 1 CanonicalTrade -> chronological event stream.

    Every price_evolution point yields BOTH a PRICE_UPDATE (what the market
    did) and a FEATURE_SNAPSHOT (what the analysis said at that moment). The
    pairing is what makes divergence detectable: reality and belief, sampled
    together, over the life of the trade.
    """
    timestamps = getattr(canonical_trade, "timestamps", {}) or {}
    symbol = getattr(canonical_trade, "symbol", None)
    decision_at = timestamps.get("decision_at")
    provenance = getattr(canonical_trade, "provenance", None) or Provenance()
    events: List[ReplayEvent] = []
    index = 0

    def add(event_type: EventType, timestamp: Any, source: str,
            payload: Dict[str, Any], timeframe: Optional[str] = None) -> None:
        nonlocal index
        if not timestamp:
            return
        events.append(ReplayEvent(
            event_id=f"{getattr(canonical_trade, 'trade_id', '')}:{event_type.value}:{index}",
            event_type=event_type, timestamp=str(timestamp), source=source,
            payload=payload, symbol=symbol, timeframe=timeframe,
            available_at=str(timestamp), index=index, provenance=provenance,
        ))
        index += 1

    decision_state = getattr(canonical_trade, "decision_state", {}) or {}
    execution = getattr(canonical_trade, "execution", {}) or {}

    add(EventType.MARKET_SNAPSHOT, decision_at, "analysis_at_open",
        dict(decision_state.get("market_snapshot") or {}))
    add(EventType.FEATURE_SNAPSHOT, decision_at, "analysis_at_open",
        dict(decision_state.get("deterministic") or {}))
    add(EventType.SYNTHESIS_UPDATE, decision_at, "analysis_at_open",
        dict(decision_state.get("market_synthesis") or {}))
    add(EventType.EXECUTION_RESULT, decision_at, "execution",
        {k: execution.get(k) for k in
         ("entry_price", "stop_loss", "take_profit", "size", "spread")})

    for point in getattr(canonical_trade, "price_evolution", []) or []:
        if not isinstance(point, Mapping):
            continue
        stamp = point.get("timestamp")
        add(EventType.PRICE_UPDATE, stamp, "price_evolution", {
            "price": point.get("price"),
            "distance_from_entry_pips": point.get("distance_from_entry_pips"),
            "spread": point.get("spread"),
            "volume": point.get("volume"),
        })
        analysis = point.get("analysis") or {}
        for timeframe in ("m1", "m5", "h1"):
            block = analysis.get(timeframe)
            if isinstance(block, Mapping) and block:
                add(EventType.FEATURE_SNAPSHOT, stamp, f"price_evolution.{timeframe}",
                    dict(block), timeframe=timeframe)

    outcome = getattr(canonical_trade, "outcome", {}) or {}
    exit_at = timestamps.get("exit_at")
    add(EventType.EXIT_EVENT, exit_at, "close_data",
        {"exit_price": outcome.get("exit_price"), "result": outcome.get("result")})
    add(EventType.OUTCOME_EVENT, exit_at, "close_data", dict(outcome))

    return EventStream(events)


# ---------------------------------------------------------------------------
# Item 3 -- market reality reconstruction
# ---------------------------------------------------------------------------

@dataclass
class MarketReality:
    """What the market actually did at one point after the decision."""

    index: int
    timestamp: str
    price: float
    return_r: float
    mfe_r: float
    mae_r: float
    adverse_excursion_r: float
    bars_since_decision: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def reconstruct_reality(canonical_trade: Any) -> List[MarketReality]:
    """
    The realised path in R (readme section 12 / Phase 3 item 3).

    Expressed in R rather than pips so a divergence threshold means the same
    thing on XAGUSD and EURUSD -- otherwise "material" would silently mean
    something different per instrument.
    """
    execution = getattr(canonical_trade, "execution", {}) or {}
    entry_price = execution.get("entry_price")
    stop_loss = execution.get("stop_loss")
    if not entry_price or not stop_loss:
        return []

    risk = abs(float(entry_price) - float(stop_loss))
    if not risk or not math.isfinite(risk):
        return []

    direction = str(getattr(canonical_trade, "direction", "BUY") or "BUY").upper()
    sign = -1 if direction in ("SELL", "SHORT") else 1

    reality: List[MarketReality] = []
    best = worst = 0.0

    for position, point in enumerate(
            getattr(canonical_trade, "price_evolution", []) or []):
        if not isinstance(point, Mapping) or point.get("price") is None:
            continue
        price = float(point["price"])
        current = sign * (price - float(entry_price)) / risk
        best, worst = max(best, current), min(worst, current)

        reality.append(MarketReality(
            index=len(reality),
            timestamp=str(point.get("timestamp") or ""),
            price=price,
            return_r=round(current, 4),
            mfe_r=round(best, 4),
            mae_r=round(worst, 4),
            # How far the position sat against itself: the quantity a stop is
            # actually exposed to, and the one "material" is measured in.
            adverse_excursion_r=round(-worst if worst < 0 else 0.0, 4),
            bars_since_decision=position + 1,
        ))

    # The exit is ground truth and belongs on the path. Without it the reality
    # reconstruction ended at the last SAMPLE before the close, which is not
    # where the trade ended: on a fixture closing at +2R after a final
    # observation at +0.4R it reported 0.4R, understating the outcome, capping
    # the oracle bound BELOW the actual return (capture ratio 1.2), and
    # putting this module into permanent disagreement with the counterfactual
    # simulator, which correctly falls back to the close.
    close_price = (getattr(canonical_trade, "outcome", {}) or {}).get("exit_price")
    if close_price is not None and reality:
        price = float(close_price)
        current = sign * (price - float(entry_price)) / risk
        best, worst = max(best, current), min(worst, current)
        reality.append(MarketReality(
            index=len(reality),
            timestamp=str((getattr(canonical_trade, "timestamps", {}) or {}).get(
                "exit_at") or ""),
            price=price,
            return_r=round(current, 4),
            mfe_r=round(best, 4),
            mae_r=round(worst, 4),
            adverse_excursion_r=round(-worst if worst < 0 else 0.0, 4),
            bars_since_decision=len(reality) + 1,
        ))
    return reality


# ---------------------------------------------------------------------------
# Item 4 -- decision reconstruction
# ---------------------------------------------------------------------------

@dataclass
class ReconstructedDecision:
    """What the strategy believed at T0, and nothing it learned later."""

    decision_id: str
    symbol: Optional[str]
    direction: Optional[str]
    decision_timestamp: Optional[str]
    stated_probability: Optional[float]
    structural_bias: Optional[str]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    synthesis_hash: Optional[str] = None
    conflicts_at_entry: List[Dict[str, Any]] = field(default_factory=list)
    uncertainty_at_entry: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def reconstruct_decision(canonical_trade: Any) -> ReconstructedDecision:
    """
    Rebuild the T0 belief from the Decision Genome (Phase 3 item 4).

    Uses only decision-time state. The outcome is never consulted, so the
    reconstruction is what replay compares reality against rather than
    something already contaminated by knowing how it ended.
    """
    from ..market_synthesis import synthesise_trade

    genome = getattr(canonical_trade, "genome", None)
    execution = getattr(canonical_trade, "execution", {}) or {}
    synthesis = synthesise_trade(canonical_trade)

    verdict = (getattr(canonical_trade, "decision_state", {}) or {}).get(
        "market_synthesis") or {}
    probability = verdict.get("probability_percent")
    if isinstance(probability, (int, float)) and probability > 1:
        probability = float(probability) / 100.0

    return ReconstructedDecision(
        decision_id=getattr(canonical_trade, "trade_id", ""),
        symbol=getattr(canonical_trade, "symbol", None),
        direction=getattr(canonical_trade, "direction", None),
        decision_timestamp=(getattr(canonical_trade, "timestamps", {}) or {}).get(
            "decision_at"),
        stated_probability=probability if isinstance(probability, float) else None,
        structural_bias=synthesis.multi_timeframe.get("local_state"),
        entry_price=execution.get("entry_price"),
        stop_loss=execution.get("stop_loss"),
        take_profit=execution.get("take_profit"),
        synthesis_hash=synthesis.synthesis_hash(),
        conflicts_at_entry=[c.to_dict() for c in synthesis.conflicts],
        uncertainty_at_entry=(synthesis.uncertainty or {}).get("level"),
    )


# ---------------------------------------------------------------------------
# Item 5 -- first divergence (readme section 17)
# ---------------------------------------------------------------------------

@dataclass
class DivergencePoint:
    kind: str
    index: Optional[int]
    timestamp: Optional[str]
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# An adverse excursion below this is ordinary noise. Above it, the thesis is
# in trouble. Expressed in R so it means the same on every instrument.
MATERIAL_ADVERSE_R = 0.5
ANOMALY_ADVERSE_R = 0.2


def detect_divergences(
    decision: ReconstructedDecision,
    reality: Sequence[MarketReality],
    stream: Optional[EventStream] = None,
) -> Dict[str, Any]:
    """
    The four firsts (readme section 17), computed separately.

    The specification is explicit that these need not share a timestamp, and
    the gap between them is the diagnosis: an anomaly at T+1 followed by a
    material divergence at T+6 says the warning was there and nothing acted on
    it -- a decision failure. Both at T+6 says the move was simply abrupt --
    a prediction failure. One number cannot express that difference.
    """
    firsts: Dict[str, Optional[DivergencePoint]] = {
        "first_anomaly": None,
        "first_prediction_error": None,
        "first_decision_error": None,
        "first_material_divergence": None,
    }

    peak_r = 0.0
    for point in reality:
        peak_r = max(peak_r, point.mfe_r)

        # Anomaly: the position moved against itself at all, beyond jitter.
        if firsts["first_anomaly"] is None and point.adverse_excursion_r >= ANOMALY_ADVERSE_R:
            firsts["first_anomaly"] = DivergencePoint(
                kind="first_anomaly", index=point.index, timestamp=point.timestamp,
                detail=f"adverse excursion reached {point.adverse_excursion_r}R",
                evidence={"adverse_excursion_r": point.adverse_excursion_r},
            )

        # Prediction error: the trade went the other way. The stated read was
        # directionally wrong at this point, whatever happened later.
        if firsts["first_prediction_error"] is None and point.return_r < 0:
            firsts["first_prediction_error"] = DivergencePoint(
                kind="first_prediction_error", index=point.index,
                timestamp=point.timestamp,
                detail=f"return went negative ({point.return_r}R)",
                evidence={"return_r": point.return_r,
                          "stated_probability": decision.stated_probability},
            )

        # Material divergence: past the point where this is noise.
        if firsts["first_material_divergence"] is None and \
                point.adverse_excursion_r >= MATERIAL_ADVERSE_R:
            firsts["first_material_divergence"] = DivergencePoint(
                kind="first_material_divergence", index=point.index,
                timestamp=point.timestamp,
                detail=(f"adverse excursion {point.adverse_excursion_r}R exceeded "
                        f"the material threshold {MATERIAL_ADVERSE_R}R"),
                evidence={"adverse_excursion_r": point.adverse_excursion_r,
                          "mae_r": point.mae_r},
            )

        # Decision error: the trade had a real gain and gave it back. Holding
        # was a choice, and this is where it started costing.
        if firsts["first_decision_error"] is None and peak_r >= 1.0 and \
                point.return_r <= peak_r - 1.0:
            firsts["first_decision_error"] = DivergencePoint(
                kind="first_decision_error", index=point.index,
                timestamp=point.timestamp,
                # Phrased as "peak -> current" rather than only the giveback:
                # a 2.25R giveback from a 2.0R peak reads as impossible until
                # you see it ended at -0.25R.
                detail=(f"fell from a {peak_r}R peak to {point.return_r}R "
                        f"({round(peak_r - point.return_r, 4)}R given back) "
                        f"without exiting"),
                evidence={"peak_r": peak_r, "return_r": point.return_r},
            )

    ordered = [p for p in firsts.values() if p and p.index is not None]
    earliest = min(ordered, key=lambda p: p.index) if ordered else None

    return {
        **{name: (point.to_dict() if point else None)
           for name, point in firsts.items()},
        "earliest": earliest.to_dict() if earliest else None,
        # The gap is the finding: a warning that preceded the damage means
        # something was available to act on and was not acted on.
        "anomaly_preceded_divergence": bool(
            firsts["first_anomaly"] and firsts["first_material_divergence"]
            and firsts["first_anomaly"].index < firsts["first_material_divergence"].index
        ),
        "material_threshold_r": MATERIAL_ADVERSE_R,
    }


# ---------------------------------------------------------------------------
# Item 6 -- attribution (readme section 18)
# ---------------------------------------------------------------------------

def attribute_failure(
    decision: ReconstructedDecision,
    reality: Sequence[MarketReality],
    divergences: Mapping[str, Any],
    canonical_trade: Any = None,
) -> Dict[str, Any]:
    """
    Candidate failure classes with their evidence (readme section 18).

    The specification requires attribution to "distinguish correlation from
    causation", so this returns ranked CANDIDATES with the evidence behind
    each, never a verdict. A component that was present when a trade failed is
    a suspect, not a cause, and the difference is exactly what the replay
    specification refuses to let the system forget.
    """
    candidates: List[Dict[str, Any]] = []

    if not reality:
        return {
            "failure_class": FailureClass.DATA.value,
            "responsible_component_candidates": [{
                "component": FailureClass.DATA.value,
                "evidence": "no reconstructable price path",
                "confidence": "HIGH",
            }],
            "confidence": "HIGH",
            "caveat": "attribution identifies candidates, not causes",
        }

    final = reality[-1]
    execution = getattr(canonical_trade, "execution", {}) or {}

    # Cost: a spread large against the stop decides outcomes arithmetically,
    # before any read of the market is involved.
    spread = execution.get("spread")
    entry, stop = execution.get("entry_price"), execution.get("stop_loss")
    if spread and entry and stop:
        stop_pips = abs(float(entry) - float(stop)) / 0.0001
        if stop_pips:
            ratio = float(spread) / stop_pips
            if ratio >= 0.34:
                candidates.append({
                    "component": FailureClass.SPREAD.value,
                    "evidence": f"spread was {ratio:.0%} of the stop distance",
                    "confidence": "HIGH" if ratio >= 0.5 else "MEDIUM",
                })

    if decision.conflicts_at_entry:
        candidates.append({
            "component": FailureClass.MARKET_SYNTHESIS.value,
            "evidence": (f"{len(decision.conflicts_at_entry)} unresolved conflict(s) "
                         f"at entry: "
                         f"{decision.conflicts_at_entry[0].get('description')}"),
            "confidence": "MEDIUM",
        })

    if decision.uncertainty_at_entry == "HIGH":
        candidates.append({
            "component": FailureClass.TRADE_QUALITY.value,
            "evidence": "synthesis reported HIGH uncertainty at entry",
            "confidence": "MEDIUM",
        })

    if decision.stated_probability is not None and final.return_r < 0 \
            and decision.stated_probability >= 0.7:
        candidates.append({
            "component": FailureClass.CALIBRATION.value,
            "evidence": (f"stated {decision.stated_probability:.0%} and lost "
                         f"({final.return_r}R)"),
            "confidence": "LOW",   # one trade cannot establish miscalibration
        })

    if divergences.get("first_decision_error"):
        candidates.append({
            "component": FailureClass.TRADE_QUALITY.value,
            "evidence": divergences["first_decision_error"]["detail"],
            "confidence": "MEDIUM",
        })

    if divergences.get("anomaly_preceded_divergence"):
        candidates.append({
            "component": FailureClass.MICROSTRUCTURE.value,
            "evidence": "an adverse move was visible before the thesis broke",
            "confidence": "LOW",
        })

    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    candidates.sort(key=lambda c: rank.get(c["confidence"], 3))

    return {
        "failure_class": (candidates[0]["component"] if candidates
                          else FailureClass.UNKNOWN.value),
        "responsible_component_candidates": candidates,
        "confidence": candidates[0]["confidence"] if candidates else "NONE",
        "evidence": [c["evidence"] for c in candidates],
        "affected_decisions": [decision.decision_id],
        "market_regime": None,
        "caveat": (
            "these are candidates correlated with the failure, not established "
            "causes; a component present at a loss is a suspect"),
    }


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_trade(canonical_trade: Any) -> Dict[str, Any]:
    """
    One trade -> full replay result (Phase 3 items 1-6).

    Raises on anything that is not a replayable record. Every field here is
    read with getattr, which happily returns None for `None` or a string --
    so without this guard, junk produced a complete-looking replay result with
    empty sections rather than being rejected, and replay_trades() silently
    turned two pieces of garbage into two records.
    """
    if not hasattr(canonical_trade, "trade_id") or not getattr(
            canonical_trade, "trade_id", None):
        raise ValueError(
            f"not a replayable record: {type(canonical_trade).__name__}")

    stream = build_event_stream(canonical_trade)
    decision = reconstruct_decision(canonical_trade)
    reality = reconstruct_reality(canonical_trade)
    divergences = detect_divergences(decision, reality, stream)
    attribution = attribute_failure(decision, reality, divergences, canonical_trade)

    outcome = getattr(canonical_trade, "outcome", {}) or {}
    return {
        "replay_version": REPLAY_ENGINE_VERSION,
        "trade_id": getattr(canonical_trade, "trade_id", None),
        "symbol": getattr(canonical_trade, "symbol", None),
        "events": len(stream),
        "event_stream_hash": stream.hash(),
        "decision": decision.to_dict(),
        "reality": [r.to_dict() for r in reality],
        "divergences": divergences,
        "attribution": attribution,
        "outcome": {
            "result": outcome.get("result"),
            "return": outcome.get("return"),
            "final_return_r": reality[-1].return_r if reality else None,
        },
        "replayed_at": utc_now(),
    }


def replay_trades(canonical_trades: Sequence[Any]) -> List[Dict[str, Any]]:
    results = []
    for trade in canonical_trades or []:
        try:
            results.append(replay_trade(trade))
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.replay_engine",
        "version": REPLAY_ENGINE_VERSION,
        "phase": "3 - Replay (items 1-6)",
        "implements": {
            "event_model": True,               # item 1, readme 16
            "temporal_aligner": True,          # item 2
            "market_reality": True,            # item 3
            "decision_reconstruction": True,   # item 4
            "first_divergence": True,          # item 5, readme 17
            "attribution": True,               # item 6, readme 18
        },
        # Phase 3 items 7-14, located rather than assumed. This list said
        # "not yet built" long after most of it was built, in a status
        # endpoint -- the one place a stale claim is most likely to be
        # believed without checking.
        "built_elsewhere": {
            "counterfactual_branching": "ai/aireplay/counterfactual.py",
            "ab": "ai/model_governance.py (+ native in ai_gnn, ai_adversarial)",
            "ablation": "non_rl_intelligence.ExperimentEngine.ablate_components",
            "replay_reports": "core/replay_forensics.py, core/phase_report.py",
            "historical_simulator": "core/replay.py + core/mt5_shim.py",
            "counterfactual_simulator": "ai_reinforcement.CounterfactualSimulator",
            "simulator_replay_consistency_tests": "ai/aireplay/consistency.py",
        },
        "not_yet_built": [
            # Genuinely absent: needs generated scenarios, which needs a
            # generator nothing has validated against this dataset.
            "stress_replay",
        ],
        "four_firsts": [
            "first_anomaly", "first_prediction_error",
            "first_decision_error", "first_material_divergence"],
        "material_threshold_r": MATERIAL_ADVERSE_R,
        "attribution_claims_causation": False,
        "limitation": (
            "pre-trade events (CANDIDATE_DETECTED, CONFIRMATION, "
            "MICROSTRUCTURE_TRIGGER, RISK_APPROVAL) are recorded for NEW "
            "trades when AIREPLAY_RECORD_LIVE is enabled (see "
            "aireplay.live_recording), but remain absent from historical "
            "storage, which limits explaining WHY an entry was taken; it does "
            "not affect divergence detection, which concerns what happened "
            "after entry"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "component": "aireplay.replay_engine", "ok": False, "checks": {}}
    try:
        from .data_engine import extract_replay_records

        records = extract_replay_records(trades or [])
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["records"] = len(records)

        if records:
            result = replay_trade(records[0])
            stream = build_event_stream(records[0])

            report["checks"]["events_built"] = len(stream)
            report["checks"]["stream_is_ordered"] = stream.is_ordered()
            report["checks"]["reality_points"] = len(result["reality"])
            report["checks"]["divergences_computed"] = sorted(
                k for k in result["divergences"] if k.startswith("first_"))
            report["checks"]["attribution_candidates"] = len(
                result["attribution"]["responsible_component_candidates"])
            report["checks"]["deterministic"] = (
                stream.hash() == build_event_stream(records[0]).hash())

            report["ok"] = bool(
                report["checks"]["stream_is_ordered"]
                and report["checks"]["deterministic"]
                and report["checks"]["events_built"] > 0
            )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "REPLAY_ENGINE_VERSION", "EventType", "FailureClass", "ReplayEvent",
    "EventStream", "MarketReality", "ReconstructedDecision", "DivergencePoint",
    "MATERIAL_ADVERSE_R", "ANOMALY_ADVERSE_R",
    "build_event_stream", "reconstruct_reality", "reconstruct_decision",
    "detect_divergences", "attribute_failure", "replay_trade", "replay_trades",
    "get_status", "self_check",
]
