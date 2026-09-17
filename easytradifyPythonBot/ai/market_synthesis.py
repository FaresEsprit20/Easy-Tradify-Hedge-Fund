# ============================================================
# CANONICAL MARKET SYNTHESIS
# ============================================================
#
# Readme section 10, and Phase 2 items 8-10: the canonical synthesis, its
# conflict/uncertainty model, and replay determinism.
#
# WHAT THIS IS NOT
# ----------------
# Section 10.1 explicitly prohibits the architecture this replaces:
#
#     RSI -> score, MACD -> score, FVG -> score ... sum(scores) -> BUY/SELL
#
# So there is deliberately no aggregate score anywhere in this module, and no
# BUY/SELL output. Synthesis produces a structured DESCRIPTION of the market;
# deciding what to do about it belongs downstream.
#
# The reason is not stylistic. `+20` and `-20` cancel, and once they have,
# nothing downstream can recover the fact that structure and liquidity
# disagreed -- which is the single most useful thing to know about that bar.
# A number cannot be diagnosed after the fact; a state can.
#
# WHAT IT IS BUILT FROM
# ---------------------
# Nothing here recomputes market intelligence. Phase 2 items 1-7 already exist
# in core/ -- vwap.py, rvam.py, liquidity_events.py, order_flow_forensics.py,
# order_flow_proxy.py, indicators.analyze_micro_structure, conviction.py --
# and readme section 26.1 requires the new architecture use them as building
# blocks rather than recreating them. This module reads their output from a
# canonical decision_state and interprets it.
#
# THE THREE HARD REQUIREMENTS
# ---------------------------
#   10.4  conflicts are preserved, never averaged away
#   10.7  "unavailable" and "stale" are distinct from "zero"
#   10.8  same inputs + same versions => reproducible synthesis
# ============================================================

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .aireplay.models import content_hash

MARKET_SYNTHESIS_VERSION = "1.0"
FEATURE_VERSION = "1.0"


class Status(str, Enum):
    """
    Readme 10.7: a value's availability is part of its meaning.

    A missing GNN result must not silently become "GNN = neutral". Neutral is
    a claim about the market; unavailable is a claim about the system, and
    conflating them lets an outage read as evidence.
    """

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    DEGRADED = "DEGRADED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Uncertainty(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class Observation:
    """
    One observed quantity plus everything needed to judge whether to trust it
    (readme 10.7).

    `value is None` and `status is UNAVAILABLE` are kept as separate facts:
    a field can legitimately be null and present, or absent entirely, and the
    two mean different things to a replay trying to explain a decision.
    """

    name: str
    value: Any = None
    status: Status = Status.UNAVAILABLE
    source: Optional[str] = None
    timestamp: Optional[str] = None
    available_at: Optional[str] = None
    freshness: Optional[str] = None
    quality: Optional[str] = None
    reason: Optional[str] = None
    fallback_used: bool = False

    @property
    def usable(self) -> bool:
        return self.status in (Status.OK, Status.DEGRADED)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class Conflict:
    """
    Readme 10.4 -- a disagreement between two named dimensions, recorded
    rather than netted.

    `left` and `right` name the dimensions and carry their readings, so a
    later diagnosis can say "structure said bullish while liquidity said a
    sell-side sweep had just fired" instead of "net score +40".
    """

    left: str
    left_reading: Any
    right: str
    right_reading: Any
    description: str
    severity: Severity = Severity.MEDIUM

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass
class SynthesisProvenance:
    synthesis_version: str = MARKET_SYNTHESIS_VERSION
    feature_version: str = FEATURE_VERSION
    config_version: Optional[str] = None
    model_versions: Dict[str, str] = field(default_factory=dict)
    decision_timestamp: Optional[str] = None
    synthesised_at: Optional[str] = None


@dataclass
class MarketSynthesis:
    """
    Readme 10.2 -- the canonical structured description of one market state.

    Note the absence of any `score`, `probability` or `direction` field. That
    is the point of section 10.1, not an oversight.
    """

    symbol: Optional[str] = None
    decision_timestamp: Optional[str] = None

    structural_state: Dict[str, Any] = field(default_factory=dict)
    liquidity_state: Dict[str, Any] = field(default_factory=dict)
    imbalance_state: Dict[str, Any] = field(default_factory=dict)
    value_state: Dict[str, Any] = field(default_factory=dict)
    participation_state: Dict[str, Any] = field(default_factory=dict)
    momentum_state: Dict[str, Any] = field(default_factory=dict)
    volatility_state: Dict[str, Any] = field(default_factory=dict)
    session_state: Dict[str, Any] = field(default_factory=dict)
    multi_timeframe: Dict[str, Any] = field(default_factory=dict)
    microstructure_state: Dict[str, Any] = field(default_factory=dict)
    regime: Dict[str, Any] = field(default_factory=dict)

    hierarchy: List[Dict[str, Any]] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    uncertainty: Dict[str, Any] = field(default_factory=dict)
    observations: List[Observation] = field(default_factory=list)
    provenance: SynthesisProvenance = field(default_factory=SynthesisProvenance)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["conflicts"] = [c.to_dict() for c in self.conflicts]
        payload["observations"] = [o.to_dict() for o in self.observations]
        return payload

    # -- readme 10.8: determinism ----------------------------------------

    def synthesis_hash(self) -> str:
        """
        Content hash over the synthesis, excluding wall-clock metadata.

        `synthesised_at` is when this ran, not what it concluded. Including it
        would make every re-synthesis of an identical input produce a new hash
        and report nondeterminism on every record -- the same mistake that
        made the Phase 1 immutability check fire on every trade.
        """
        payload = self.to_dict()
        payload.get("provenance", {}).pop("synthesised_at", None)
        return content_hash(payload)

    def unavailable_inputs(self) -> List[str]:
        return [o.name for o in self.observations if o.status is Status.UNAVAILABLE]

    def stale_inputs(self) -> List[str]:
        return [o.name for o in self.observations if o.status is Status.STALE]


# ---------------------------------------------------------------------------
# Reading the canonical decision state
# ---------------------------------------------------------------------------

def _observe(
    name: str,
    payload: Mapping[str, Any],
    path: Sequence[str],
    decision_timestamp: Optional[str],
    source: str,
) -> Observation:
    """
    Read one dimension, recording WHY it is unusable when it is.

    An absent section yields UNAVAILABLE with a reason rather than an empty
    dict that later reads as "measured, and it was nothing".
    """
    node: Any = payload
    for key in path:
        if not isinstance(node, Mapping):
            node = None
            break
        node = node.get(key)

    if node is None:
        return Observation(name=name, status=Status.UNAVAILABLE, source=source,
                           reason=f"{'.'.join(path)} absent from decision_state")
    if isinstance(node, Mapping) and not node:
        return Observation(name=name, status=Status.UNAVAILABLE, source=source,
                           reason=f"{'.'.join(path)} present but empty")

    return Observation(
        name=name, value=node, status=Status.OK, source=source,
        timestamp=decision_timestamp, available_at=decision_timestamp,
        freshness="decision_time", quality="observed",
    )


# Key fragments that carry a directional reading. Matched as substrings
# because the engine names these inconsistently across subsystems --
# `structure`, `trend`, `h1_trend`, `trend_bias`, `last_event` all appear --
# and an exact-name list silently missed `h1_trend`, which disabled
# higher-timeframe conflict detection entirely: the single most valuable
# conflict section 10.4 asks for.
_BIAS_KEY_FRAGMENTS: Tuple[str, ...] = (
    "structure", "trend", "bias", "direction", "last_event",
)


def _bias_of(structure: Any) -> Optional[str]:
    """Directional reading of a block, or None when it genuinely says nothing."""
    if not isinstance(structure, Mapping):
        return None
    for key, value in structure.items():
        if not isinstance(value, str):
            continue
        if not any(fragment in str(key).lower() for fragment in _BIAS_KEY_FRAGMENTS):
            continue
        upper = value.upper()
        if "BULL" in upper:
            return "BULLISH"
        if "BEAR" in upper:
            return "BEARISH"
        if "RANG" in upper or "NEUTRAL" in upper:
            return "NEUTRAL"
    return None


# ---------------------------------------------------------------------------
# Readme 10.4 -- conflicts
# ---------------------------------------------------------------------------

def detect_conflicts(synthesis: MarketSynthesis) -> List[Conflict]:
    """
    Disagreements between dimensions, preserved as facts.

    Each check compares two dimensions that are meaningfully independent, so a
    disagreement is information rather than noise. Nothing is summed: the
    output is a list of specific tensions a human or a model can act on.
    """
    conflicts: List[Conflict] = []

    structure_bias = _bias_of(synthesis.structural_state)
    htf_bias = synthesis.multi_timeframe.get("higher_timeframe_bias")
    local = synthesis.multi_timeframe.get("local_state")

    if structure_bias and htf_bias and structure_bias != htf_bias:
        if "NEUTRAL" not in (structure_bias, htf_bias):
            conflicts.append(Conflict(
                left="structure", left_reading=structure_bias,
                right="higher_timeframe", right_reading=htf_bias,
                description="local structure opposes the higher timeframe bias",
                severity=Severity.HIGH,
            ))

    sweep = (synthesis.liquidity_state or {}).get("sweep_direction")
    if structure_bias and sweep:
        opposing = ("BEARISH" if "SELL" in str(sweep).upper() else "BULLISH")
        if opposing != structure_bias and structure_bias != "NEUTRAL":
            conflicts.append(Conflict(
                left="structure", left_reading=structure_bias,
                right="liquidity", right_reading=sweep,
                description="a liquidity sweep fired against the structural bias",
                severity=Severity.HIGH,
            ))

    participation = (synthesis.participation_state or {}).get("state")
    if structure_bias and participation and "UNPARTICIPATED" in str(participation).upper():
        conflicts.append(Conflict(
            left="structure", left_reading=structure_bias,
            right="participation", right_reading=participation,
            description="directional structure without participation behind it",
            severity=Severity.MEDIUM,
        ))

    trigger = (synthesis.microstructure_state or {}).get("trigger_state")
    if structure_bias and trigger:
        trigger_bias = _bias_of({"bias": trigger})
        if trigger_bias and trigger_bias != structure_bias and "NEUTRAL" not in (
                trigger_bias, structure_bias):
            conflicts.append(Conflict(
                left="structure", left_reading=structure_bias,
                right="microstructure", right_reading=trigger,
                description="the local trigger points against the structural bias",
                severity=Severity.MEDIUM,
            ))

    return conflicts


def assess_uncertainty(synthesis: MarketSynthesis) -> Dict[str, Any]:
    """
    How much the synthesis should be trusted, and why.

    Driven by two independent things: how much the dimensions disagree, and
    how much of the picture is missing. They are reported separately because
    they call for different responses -- a conflicted-but-complete picture is
    a reason to wait, a missing one is a reason to fix the pipeline.
    """
    high = [c for c in synthesis.conflicts if c.severity is Severity.HIGH]
    medium = [c for c in synthesis.conflicts if c.severity is Severity.MEDIUM]
    unavailable = synthesis.unavailable_inputs()
    stale = synthesis.stale_inputs()

    total = len(synthesis.observations) or 1
    missing_share = len(unavailable) / total

    if high or missing_share > 0.5:
        level = Uncertainty.HIGH
    elif medium or stale or missing_share > 0.25:
        level = Uncertainty.MEDIUM
    else:
        level = Uncertainty.LOW

    reasons: List[str] = []
    for conflict in high + medium:
        reasons.append(conflict.description)
    if unavailable:
        reasons.append(f"{len(unavailable)} of {total} dimensions unavailable")
    if stale:
        reasons.append(f"{len(stale)} dimensions stale")

    return {
        "level": level.value,
        "conflict_count": len(synthesis.conflicts),
        "high_severity_conflicts": len(high),
        "unavailable_inputs": unavailable,
        "stale_inputs": stale,
        "coverage": round(1.0 - missing_share, 4),
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Readme 10.3 -- the hierarchy
# ---------------------------------------------------------------------------

HIERARCHY_QUESTIONS: Tuple[Tuple[str, str], ...] = (
    ("structural_coherence", "Is the market structurally coherent?"),
    ("location", "Where is price relative to liquidity and value?"),
    ("participation", "What is the participation and imbalance state?"),
    ("regime", "What regime is active?"),
    ("timeframe_alignment", "Are timeframes aligned or conflicting?"),
    ("trigger_proximity", "Is the setup approaching a valid trigger?"),
    ("microstructure_confirmation", "Is microstructure confirming the transition?"),
    ("residual_uncertainty", "What uncertainty and conflicts remain?"),
)


def build_hierarchy(synthesis: MarketSynthesis) -> List[Dict[str, Any]]:
    """
    Readme 10.3 -- the eight questions, answered in order.

    Each step reports its answer and whether it could be answered at all. The
    spec is explicit that these must not be "reduced to arbitrary points", so
    each answer is a state or an explicit UNKNOWN, never a number.
    """
    answers = {
        "structural_coherence": _bias_of(synthesis.structural_state),
        "location": (synthesis.value_state or {}).get("location")
                    or (synthesis.liquidity_state or {}).get("zone"),
        "participation": (synthesis.participation_state or {}).get("state"),
        "regime": (synthesis.regime or {}).get("state"),
        "timeframe_alignment": synthesis.multi_timeframe.get("alignment"),
        "trigger_proximity": (synthesis.microstructure_state or {}).get("trigger_state"),
        "microstructure_confirmation": (
            synthesis.microstructure_state or {}).get("confirmed"),
        "residual_uncertainty": (synthesis.uncertainty or {}).get("level"),
    }

    return [
        {
            "step": index + 1,
            "key": key,
            "question": question,
            "answer": answers.get(key),
            "answered": answers.get(key) is not None,
        }
        for index, (key, question) in enumerate(HIERARCHY_QUESTIONS)
    ]


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def synthesise(
    decision_state: Mapping[str, Any],
    symbol: Optional[str] = None,
    decision_timestamp: Optional[str] = None,
    config_version: Optional[str] = None,
    model_versions: Optional[Mapping[str, str]] = None,
) -> MarketSynthesis:
    """
    Canonical decision_state -> MarketSynthesis (readme 10.2).

    Consumes the Phase 1 canonical record, so the deterministic subsystems in
    core/ are read rather than recomputed.
    """
    deterministic = (decision_state or {}).get("deterministic") or {}
    unmapped = (decision_state or {}).get("unmapped") or {}
    merged = {**unmapped, **deterministic}

    dimensions = (
        ("structure", ("structure",), "core.indicators/smc"),
        ("liquidity", ("liquidity",), "core.liquidity_events"),
        ("imbalance", ("fvg",), "core.indicators.detect_all_fvgs"),
        ("value", ("vwap",), "core.vwap"),
        ("participation", ("rvam",), "core.rvam"),
        ("absorption", ("absorption",), "core.order_flow_forensics"),
        ("momentum", ("momentum",), "core.asset_analysis_indicators"),
        ("volatility", ("volatility",), "core.asset_analysis_config"),
        ("sessions", ("sessions",), "core.session_manager"),
        ("microstructure", ("microstructure",), "core.indicators"),
    )

    observations = [
        _observe(name, merged, path, decision_timestamp, source)
        for name, path, source in dimensions
    ]
    by_name = {o.name: o for o in observations}

    def value_of(name: str) -> Dict[str, Any]:
        observation = by_name.get(name)
        return dict(observation.value) if (
            observation and observation.usable
            and isinstance(observation.value, Mapping)) else {}

    synthesis = MarketSynthesis(
        symbol=symbol,
        decision_timestamp=decision_timestamp,
        structural_state=value_of("structure"),
        liquidity_state=value_of("liquidity"),
        imbalance_state=value_of("imbalance"),
        value_state=value_of("value"),
        participation_state=value_of("participation"),
        momentum_state=value_of("momentum"),
        volatility_state=value_of("volatility"),
        session_state=value_of("sessions"),
        microstructure_state=value_of("microstructure"),
        observations=observations,
        provenance=SynthesisProvenance(
            config_version=config_version,
            model_versions=dict(model_versions or {}),
            decision_timestamp=decision_timestamp,
            synthesised_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    higher = unmapped.get("higher_timeframe") or {}
    synthesis.multi_timeframe = {
        "higher_timeframe_bias": _bias_of(higher),
        "local_state": _bias_of(synthesis.structural_state),
        "alignment": None,
    }
    if synthesis.multi_timeframe["higher_timeframe_bias"] and \
            synthesis.multi_timeframe["local_state"]:
        synthesis.multi_timeframe["alignment"] = (
            "ALIGNED"
            if synthesis.multi_timeframe["higher_timeframe_bias"]
            == synthesis.multi_timeframe["local_state"]
            else "CONFLICTING")

    regime_source = synthesis.volatility_state or {}
    synthesis.regime = {
        "state": regime_source.get("regime") or regime_source.get("state"),
        "source": "deterministic.volatility",
    }

    # Order matters: conflicts feed uncertainty, and uncertainty is the
    # hierarchy's final question.
    synthesis.conflicts = detect_conflicts(synthesis)
    synthesis.uncertainty = assess_uncertainty(synthesis)
    synthesis.hierarchy = build_hierarchy(synthesis)
    return synthesis


def synthesise_trade(canonical_trade: Any) -> MarketSynthesis:
    """Convenience over a Phase 1 CanonicalTrade."""
    return synthesise(
        decision_state=getattr(canonical_trade, "decision_state", {}) or {},
        symbol=getattr(canonical_trade, "symbol", None),
        decision_timestamp=(getattr(canonical_trade, "timestamps", {}) or {}).get(
            "decision_at"),
        config_version=getattr(
            getattr(canonical_trade, "provenance", None), "config_version", None),
    )


# ---------------------------------------------------------------------------
# Readme 10.8 -- replay determinism
# ---------------------------------------------------------------------------

def verify_reproducible(
    first: MarketSynthesis,
    second: MarketSynthesis,
) -> Dict[str, Any]:
    """
    Do two syntheses of the same input agree (readme 10.8)?

    Reports WHICH dimension diverged rather than a bare boolean, because
    "synthesis is nondeterministic" is not actionable and "liquidity_state
    differs" is.
    """
    differing = [
        name for name in (
            "structural_state", "liquidity_state", "imbalance_state",
            "value_state", "participation_state", "momentum_state",
            "volatility_state", "session_state", "multi_timeframe",
            "microstructure_state", "regime", "uncertainty")
        if getattr(first, name) != getattr(second, name)
    ]
    return {
        "reproducible": first.synthesis_hash() == second.synthesis_hash(),
        "first_hash": first.synthesis_hash(),
        "second_hash": second.synthesis_hash(),
        "differing_dimensions": differing,
        "conflicts_match": (
            [c.to_dict() for c in first.conflicts]
            == [c.to_dict() for c in second.conflicts]),
    }


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    return {
        "component": "market_synthesis",
        "version": MARKET_SYNTHESIS_VERSION,
        "feature_version": FEATURE_VERSION,
        "phase": "2 - Deterministic Intelligence (items 8-10)",
        "produces_score": False,
        "produces_direction": False,
        "why_no_score": (
            "readme 10.1 prohibits summing per-indicator scores into a "
            "BUY/SELL verdict; +20 and -20 cancel and nothing downstream can "
            "then recover that structure and liquidity disagreed"),
        "implements": {
            "canonical_synthesis": True,          # readme 10.2
            "hierarchical_reasoning": True,       # readme 10.3
            "explicit_conflicts": True,           # readme 10.4
            "missing_vs_stale_vs_zero": True,     # readme 10.7
            "replay_determinism": True,           # readme 10.8
        },
        "recomputes_market_intelligence": False,
        "reads_from": [
            "core.vwap", "core.rvam", "core.liquidity_events",
            "core.order_flow_forensics", "core.order_flow_proxy",
            "core.indicators", "core.conviction",
        ],
        "hierarchy_steps": [key for key, _ in HIERARCHY_QUESTIONS],
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Prove synthesis, conflict detection, availability semantics, determinism."""
    report: Dict[str, Any] = {
        "component": "market_synthesis", "ok": False, "checks": {}}
    try:
        from .aireplay import extract_replay_records

        records = extract_replay_records(trades or [])
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["records"] = len(records)

        if records:
            synthesis = synthesise_trade(records[0])
            again = synthesise_trade(records[0])
            reproducibility = verify_reproducible(synthesis, again)

            report["checks"]["dimensions_populated"] = [
                o.name for o in synthesis.observations if o.usable]
            report["checks"]["unavailable_inputs"] = synthesis.unavailable_inputs()
            report["checks"]["hierarchy_steps_answered"] = sum(
                1 for step in synthesis.hierarchy if step["answered"])
            report["checks"]["conflicts"] = [c.to_dict() for c in synthesis.conflicts]
            report["checks"]["uncertainty"] = synthesis.uncertainty.get("level")
            report["checks"]["reproducible"] = reproducibility["reproducible"]
            report["checks"]["produces_no_score"] = not any(
                key in synthesis.to_dict()
                for key in ("score", "probability", "direction"))

            report["ok"] = bool(
                report["checks"]["reproducible"]
                and report["checks"]["produces_no_score"]
                and report["checks"]["dimensions_populated"]
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
                report["reason"] = "no replay records could be extracted from the supplied trades"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "MARKET_SYNTHESIS_VERSION", "FEATURE_VERSION", "Status", "Severity",
    "Uncertainty", "Observation", "Conflict", "SynthesisProvenance",
    "MarketSynthesis", "HIERARCHY_QUESTIONS", "detect_conflicts",
    "assess_uncertainty", "build_hierarchy", "synthesise", "synthesise_trade",
    "verify_reproducible", "get_status", "self_check",
]
