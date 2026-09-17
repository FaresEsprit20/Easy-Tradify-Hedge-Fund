# ============================================================
# AI_MarketReplay -- PHASE 1: DATA FOUNDATION
# Canonical data contracts
# ============================================================
#
# Implements readme sections 21 (Decision Genome), 22 (Canonical Firebase
# Trade Data Contract), 23 (Firebase Temporal Data Rules), 24 (AI Data
# Contract), 26 (Immutable Historical Snapshots) and 26.6 (Decision
# Snapshots).
#
# THE CENTRAL IDEA
# ----------------
# Section 23 requires that "every field must have a clear temporal meaning"
# and that "outcome-only information must never be fed back into a historical
# decision as if it had been known at the time."
#
# Everywhere else in this package that rule is enforced by convention -- a
# hand-maintained tuple of banned substrings in the bridge, another in
# non_rl_intelligence, a third in ai_reinforcement. Three lists, three chances
# to drift, and a leak is invisible when it happens: it produces better
# validation numbers, not worse.
#
# Here the rule becomes a property of the data instead. Every canonical field
# is registered with an Availability, `decision_view()` is derived from that
# registry rather than from a blocklist, and a field nobody classified is
# treated as OUTCOME_ONLY. Forgetting to classify something therefore makes it
# unavailable rather than silently trusted -- the safe direction to fail.
# ============================================================

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

SCHEMA_VERSION = "1.0"
REPLAY_MODELS_VERSION = "1.0"


class Availability(str, Enum):
    """
    Temporal class of a field (readme section 23).

    UNCLASSIFIED exists so that "nobody registered this field" is a state the
    system can see and report, rather than a silent default. It is treated as
    strictly as OUTCOME_ONLY at every boundary.
    """

    AT_DECISION = "AT_DECISION"       # known when the decision was made
    DURING_TRADE = "DURING_TRADE"     # observed while the position was open
    OUTCOME_ONLY = "OUTCOME_ONLY"     # knowable only after the trade closed
    UNCLASSIFIED = "UNCLASSIFIED"


class EventType(str, Enum):
    """Decision snapshot types (readme section 26.6)."""

    CANDIDATE_DETECTED = "CANDIDATE_DETECTED"
    CONFIRMATION = "CONFIRMATION"
    MICROSTRUCTURE_TRIGGER = "MICROSTRUCTURE_TRIGGER"
    RL_DECISION = "RL_DECISION"
    RISK_APPROVAL = "RISK_APPROVAL"
    EXECUTION = "EXECUTION"
    MANAGEMENT = "MANAGEMENT"
    EXIT_DECISION = "EXIT_DECISION"
    CLOSE = "CLOSE"


# ---------------------------------------------------------------------------
# Section 23 -- the temporal registry
# ---------------------------------------------------------------------------
# Top-level canonical sections and when their contents become knowable. This
# is the single source of truth the leakage firewall is derived from; it
# replaces the three separate substring blocklists scattered through the
# package.
FIELD_AVAILABILITY: Dict[str, Availability] = {
    "trade_id": Availability.AT_DECISION,
    "schema_version": Availability.AT_DECISION,
    "ticket": Availability.AT_DECISION,
    "symbol": Availability.AT_DECISION,
    "direction": Availability.AT_DECISION,
    "strategy": Availability.AT_DECISION,
    "timeframe": Availability.AT_DECISION,
    "decision_state": Availability.AT_DECISION,
    "ai_state": Availability.AT_DECISION,
    "provenance": Availability.AT_DECISION,

    # Requested execution is a decision; what actually filled is not knowable
    # until it fills, so `execution` is split at the adapter rather than
    # classified wholesale.
    "execution_requested": Availability.AT_DECISION,
    "execution_filled": Availability.DURING_TRADE,

    "price_evolution": Availability.DURING_TRADE,
    "management": Availability.DURING_TRADE,
    "decision_snapshots": Availability.DURING_TRADE,

    "outcome": Availability.OUTCOME_ONLY,
    "replay": Availability.OUTCOME_ONLY,
    "timestamps": Availability.DURING_TRADE,
}


@dataclass
class FeatureSpec:
    """
    Per-feature metadata (readme section 24).

    `available_at` is the load-bearing field: it is what lets replay assert
    `available_at <= decision_timestamp` rather than trusting a name.
    """

    feature: str
    type: str
    source: str
    timestamp: Optional[str] = None
    available_at: Optional[str] = None
    timeframe: Optional[str] = None
    units: Optional[str] = None
    nullable: bool = True
    historical: bool = True
    future_or_outcome_only: bool = False
    version: str = SCHEMA_VERSION

    def is_usable_at(self, decision_timestamp: Optional[str]) -> bool:
        """Usable as a decision-time feature at `decision_timestamp`?"""
        if self.future_or_outcome_only:
            return False
        if not self.available_at or not decision_timestamp:
            # Unknown availability is not evidence of availability.
            return not self.future_or_outcome_only and self.available_at is None
        return self.available_at <= decision_timestamp


@dataclass
class Provenance:
    """Readme section 22 provenance block. Every value is nullable on purpose:
    an unknown version must read as unknown, never as a default."""

    analysis_version: Optional[str] = None
    model_versions: Dict[str, str] = field(default_factory=dict)
    config_version: Optional[str] = None
    data_version: Optional[str] = None
    feature_version: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    extracted_at: Optional[str] = None
    source: Optional[str] = None


@dataclass
class MarketState:
    """Readme section 21 market_state. Sections absent from a stored trade stay
    empty dicts rather than being invented."""

    structure: Dict[str, Any] = field(default_factory=dict)
    liquidity: Dict[str, Any] = field(default_factory=dict)
    fvg: Dict[str, Any] = field(default_factory=dict)
    vwap: Dict[str, Any] = field(default_factory=dict)
    rvam: Dict[str, Any] = field(default_factory=dict)
    absorption: Dict[str, Any] = field(default_factory=dict)
    volume_profile: Dict[str, Any] = field(default_factory=dict)
    order_flow: Dict[str, Any] = field(default_factory=dict)
    momentum: Dict[str, Any] = field(default_factory=dict)
    volatility: Dict[str, Any] = field(default_factory=dict)
    sessions: Dict[str, Any] = field(default_factory=dict)
    microstructure: Dict[str, Any] = field(default_factory=dict)

    def populated_sections(self) -> List[str]:
        return [name for name, value in asdict(self).items() if value]


@dataclass
class DecisionGenome:
    """
    Readme section 21 -- the canonical representation of one decision.

    Everything here is AT_DECISION by construction. There is deliberately no
    field for the outcome: the genome is what was believed, and mixing in what
    happened is precisely the error the temporal rules exist to prevent.
    """

    decision_id: str
    symbol: Optional[str] = None
    strategy: Optional[str] = None
    timeframe: Optional[str] = None
    decision_timestamp: Optional[str] = None

    market_state: MarketState = field(default_factory=MarketState)
    market_synthesis: Dict[str, Any] = field(default_factory=dict)
    gnn_state: Dict[str, Any] = field(default_factory=dict)
    non_rl_state: Dict[str, Any] = field(default_factory=dict)
    adversarial_state: Dict[str, Any] = field(default_factory=dict)
    trade_quality: Dict[str, Any] = field(default_factory=dict)
    rl_state: Dict[str, Any] = field(default_factory=dict)
    risk_state: Dict[str, Any] = field(default_factory=dict)

    # Every decision-time analysis section the semantic map does not absorb:
    # account_info (leverage, balance, equity), the numbered `components`
    # sub-analyzers, the SMC blocks beyond structure/liquidity_sweep,
    # pattern_analysis, wave_lattice, vetos, family_vote, nested_zone,
    # trend_cascade, higher_timeframe, news_analysis.
    #
    # Without this field the genome was a lossy hop: to_canonical_trade
    # rescued these into decision_state.unmapped, then build_genome dropped
    # them, so the snapshots replay actually walks carried 20 of 75 measured
    # analysis leaves. The canonical record looked complete while the replay
    # input was a fifth of it -- and nothing raised.
    unmapped: Dict[str, Any] = field(default_factory=dict)

    provenance: Provenance = field(default_factory=Provenance)

    features: List[FeatureSpec] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        """Stable hash of the decision content, for immutability checks."""
        return content_hash(self.to_dict())


@dataclass
class DecisionSnapshot:
    """
    Readme section 26.6 -- an event-level record.

    The spec is explicit that "only fields actually available at the snapshot
    timestamp are permitted", so `available_at` is required rather than
    optional: a snapshot that cannot say when its contents were knowable
    cannot be checked for leakage.
    """

    snapshot_id: str
    trade_id: str
    event_type: EventType
    timestamp: str
    available_at: str

    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    deterministic_features: Dict[str, Any] = field(default_factory=dict)
    market_synthesis: Dict[str, Any] = field(default_factory=dict)
    gnn_state: Dict[str, Any] = field(default_factory=dict)
    non_rl_state: Dict[str, Any] = field(default_factory=dict)
    adversarial_state: Dict[str, Any] = field(default_factory=dict)
    trade_quality_state: Dict[str, Any] = field(default_factory=dict)
    rl_state: Dict[str, Any] = field(default_factory=dict)
    risk_state: Dict[str, Any] = field(default_factory=dict)
    execution_state: Dict[str, Any] = field(default_factory=dict)

    decision: Dict[str, Any] = field(default_factory=dict)
    probabilities: Dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return payload

    def is_temporally_valid(self) -> bool:
        """Contents must not postdate the snapshot they are attached to."""
        return bool(self.available_at and self.timestamp
                    and self.available_at <= self.timestamp)


@dataclass
class CanonicalTrade:
    """
    Readme section 22 -- the versioned logical trade record.

    Section 22 is explicit that this is a logical contract rather than a claim
    about what Firebase currently holds, so every section defaults empty and
    the adapter fills only what the stored document actually contains.
    """

    trade_id: str
    schema_version: str = SCHEMA_VERSION
    ticket: Optional[Any] = None
    symbol: Optional[str] = None
    direction: Optional[str] = None
    strategy: Optional[str] = None
    timeframe: Optional[str] = None

    timestamps: Dict[str, Any] = field(default_factory=dict)
    decision_state: Dict[str, Any] = field(default_factory=dict)
    ai_state: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    price_evolution: List[Dict[str, Any]] = field(default_factory=list)
    management: Dict[str, Any] = field(default_factory=dict)
    outcome: Dict[str, Any] = field(default_factory=dict)
    replay: Dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    decision_snapshots: List[DecisionSnapshot] = field(default_factory=list)
    genome: Optional[DecisionGenome] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["decision_snapshots"] = [
            snapshot.to_dict() for snapshot in self.decision_snapshots]
        payload["genome"] = self.genome.to_dict() if self.genome else None
        return payload

    # -- section 23: the temporal firewall -------------------------------

    def decision_view(self) -> Dict[str, Any]:
        """
        Only what was knowable at decision time.

        Derived from FIELD_AVAILABILITY rather than from a blocklist, so an
        unregistered section is excluded by default. A leak here requires
        someone to actively classify outcome data as AT_DECISION, rather than
        merely forgetting to ban it.
        """
        view: Dict[str, Any] = {}
        for name, value in self.to_dict().items():
            if name in ("decision_snapshots", "genome"):
                continue
            if name == "execution":
                requested = (value or {}).get("requested")
                if requested:
                    view["execution_requested"] = requested
                continue
            if availability_of(name) is Availability.AT_DECISION:
                view[name] = value
        return view

    def outcome_view(self) -> Dict[str, Any]:
        """Labels and diagnosis: legitimate supervision, never features."""
        return {
            name: value for name, value in self.to_dict().items()
            if availability_of(name) is Availability.OUTCOME_ONLY
        }

    def leakage_report(self) -> Dict[str, Any]:
        """
        What the decision view contains, and what it correctly withholds.

        Reported rather than merely asserted: a firewall nobody can inspect is
        a firewall nobody can trust.
        """
        present = set(self.decision_view())
        withheld = sorted(
            name for name in self.to_dict()
            if availability_of(name) is not Availability.AT_DECISION
            and name not in ("decision_snapshots", "genome")
        )
        unclassified = sorted(
            name for name in self.to_dict()
            if name not in FIELD_AVAILABILITY
            and name not in ("decision_snapshots", "genome", "execution")
        )
        return {
            "decision_fields": sorted(present),
            "withheld_fields": withheld,
            "unclassified_fields": unclassified,
            "outcome_leaked": sorted(
                name for name in present
                if availability_of(name) is Availability.OUTCOME_ONLY
            ),
        }

    def content_hash(self) -> str:
        return content_hash(self.to_dict())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def availability_of(field_name: str) -> Availability:
    """
    Temporal class of a canonical field.

    Unregistered fields return UNCLASSIFIED, which every boundary treats as
    strictly as OUTCOME_ONLY. Failing closed is the only safe default: a new
    field that someone forgets to register must become unavailable, not
    silently trusted as decision-time data.
    """
    return FIELD_AVAILABILITY.get(field_name, Availability.UNCLASSIFIED)


# Extraction bookkeeping, not decision content. These must be stripped before
# hashing or every extraction of an unchanged trade produces a new hash, and
# the immutability check reports a violation on every single record --
# defeating the one thing it exists to detect.
VOLATILE_KEYS = frozenset({"extracted_at"})


def strip_volatile(payload: Any) -> Any:
    """Recursively drop extraction bookkeeping so hashes reflect content."""
    if isinstance(payload, Mapping):
        return {
            key: strip_volatile(value)
            for key, value in payload.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(payload, (list, tuple)):
        return [strip_volatile(item) for item in payload]
    return payload


def content_hash(payload: Mapping[str, Any]) -> str:
    """
    Stable SHA-256 over the payload's content (readme section 26).

    Sorted keys and a string fallback so the hash depends on content rather
    than on dict ordering or on types json cannot serialise -- otherwise
    "has this snapshot changed" would answer yes on an unchanged record.
    Volatile extraction metadata is stripped for the same reason.
    """
    encoded = json.dumps(
        strip_volatile(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "SCHEMA_VERSION", "REPLAY_MODELS_VERSION", "Availability", "EventType",
    "FIELD_AVAILABILITY", "FeatureSpec", "Provenance", "MarketState",
    "DecisionGenome", "DecisionSnapshot", "CanonicalTrade",
    "availability_of", "content_hash", "strip_volatile", "utc_now",
]
