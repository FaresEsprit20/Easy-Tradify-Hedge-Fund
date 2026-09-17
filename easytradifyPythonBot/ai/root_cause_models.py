"""
EasyTradify - Root Cause Models
================================

Canonical, evidence-only domain models for post-trade diagnosis.

IMPORTANT:
    This module contains DATA CONTRACTS ONLY.
    It does not calculate indicators, patterns, market regimes, price statistics,
    confidence, GNN outputs, FVG state, liquidity state, or trading signals.

Root Cause consumes facts produced by upstream systems:
    Market Intelligence -> Market Synthesis -> Decision Snapshots -> Replay
    -> Outcome -> Root Cause

One fact must have one canonical producer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Urgency(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Phase(str, Enum):
    ENTRY = "entry"
    CONFIRMATION = "confirmation"
    TRIGGER = "trigger"
    MANAGEMENT = "management"
    EXIT = "exit"
    POST_TRADE = "post_trade"


class ComponentStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


class AttributionType(str, Enum):
    PRIMARY = "PRIMARY"
    CONTRIBUTING = "CONTRIBUTING"
    PROTECTIVE = "PROTECTIVE"
    EXECUTION = "EXECUTION"
    MANAGEMENT = "MANAGEMENT"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    OBSERVATION = "OBSERVATION"
    DECISION = "DECISION"
    DIVERGENCE = "DIVERGENCE"
    OUTCOME = "OUTCOME"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    CALIBRATION = "CALIBRATION"
    EXECUTION = "EXECUTION"
    REGIME = "REGIME"
    COMPONENT = "COMPONENT"


@dataclass(frozen=True)
class EvidenceRef:
    """Reference to an already-produced fact. No derived calculation is performed."""

    source: str
    path: str
    timestamp: Optional[str] = None
    available_at: Optional[str] = None
    version: Optional[str] = None
    value: Any = None
    quality: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionSnapshot:
    """Immutable-at-replay-time representation of what the system knew."""

    snapshot_id: str = ""
    trade_id: Any = None
    timestamp: str = ""
    phase: str = ""
    decision: Optional[str] = None
    decision_reason: Dict[str, Any] = field(default_factory=dict)
    market_synthesis: Dict[str, Any] = field(default_factory=dict)
    deterministic: Dict[str, Any] = field(default_factory=dict)
    gnn: Dict[str, Any] = field(default_factory=dict)
    non_rl: Dict[str, Any] = field(default_factory=dict)
    trade_quality: Dict[str, Any] = field(default_factory=dict)
    rl: Dict[str, Any] = field(default_factory=dict)
    risk_gate: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutcomeSnapshot:
    """Already-produced trade outcome. Root Cause never derives it from raw prices."""

    result: Optional[str] = None
    pnl: Optional[float] = None
    return_value: Optional[float] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    duration: Optional[float] = None
    exit_reason: Optional[str] = None
    execution: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Divergence:
    """A divergence already established by Replay or deterministic comparison."""

    divergence_id: str = ""
    timestamp: Optional[str] = None
    phase: Optional[str] = None
    category: str = ""
    expected: Any = None
    observed: Any = None
    magnitude: Any = None
    source: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Attribution:
    """Evidence-backed attribution. It is not a newly calculated component score."""

    target: str = ""
    attribution_type: AttributionType = AttributionType.UNKNOWN
    role: str = ""
    explanation: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)
    confidence: Optional[float] = None
    causal_status: str = "UNPROVEN"
    counterfactual_reference: Optional[str] = None


@dataclass
class CounterfactualResult:
    """Result supplied by the Counterfactual/Simulator layer."""

    scenario_id: str = ""
    action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    pnl: Optional[float] = None
    return_value: Optional[float] = None
    improvement: Optional[float] = None
    simulator_version: Optional[str] = None
    historical_path_reference: Optional[str] = None
    is_historical_truth: bool = True
    confidence: Optional[float] = None
    evidence: List[EvidenceRef] = field(default_factory=list)


@dataclass
class FailureDiagnosis:
    """Final diagnosis produced from existing evidence."""

    failure_class: str = "UNKNOWN"
    severity: Severity = Severity.LOW
    primary_cause: Optional[Attribution] = None
    contributing_causes: List[Attribution] = field(default_factory=list)
    protective_factors: List[Attribution] = field(default_factory=list)
    first_divergence: Optional[Divergence] = None
    counterfactuals: List[CounterfactualResult] = field(default_factory=list)
    confidence: Optional[float] = None
    causal_status: str = "UNPROVEN"
    explanation: str = ""


@dataclass
class ReplaySummary:
    """Replay output consumed by Root Cause."""

    replay_version: Optional[str] = None
    first_divergence: Optional[Dict[str, Any]] = None
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    attribution: List[Dict[str, Any]] = field(default_factory=list)
    failure_class: Optional[str] = None
    replay_score: Optional[float] = None
    counterfactuals: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RootCauseAnalysisResult:
    """Canonical Root Cause result.

    It stores references and conclusions. It deliberately does not contain
    duplicated indicator calculations or a second copy of market intelligence.
    """

    schema_version: str = "2.0"
    trade_id: Any = None
    symbol: str = ""
    profit: Optional[float] = None
    is_loss: Optional[bool] = None
    timestamp: str = ""

    outcome: OutcomeSnapshot = field(default_factory=OutcomeSnapshot)
    decision_snapshots: List[DecisionSnapshot] = field(default_factory=list)
    replay: ReplaySummary = field(default_factory=ReplaySummary)
    diagnosis: FailureDiagnosis = field(default_factory=FailureDiagnosis)

    evidence: List[EvidenceRef] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    validation_requirements: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    # Compatibility/reporting containers. They are populated only from supplied
    # upstream evidence; they are never recomputed here.
    component_evidence: Dict[str, Any] = field(default_factory=dict)
    market_synthesis: Dict[str, Any] = field(default_factory=dict)
    gnn_evidence: Dict[str, Any] = field(default_factory=dict)
    non_rl_evidence: Dict[str, Any] = field(default_factory=dict)
    execution_evidence: Dict[str, Any] = field(default_factory=dict)
    management_evidence: Dict[str, Any] = field(default_factory=dict)
    win_analysis: Dict[str, Any] = field(default_factory=dict)

    report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = [
    "Severity",
    "Urgency",
    "Phase",
    "ComponentStatus",
    "AttributionType",
    "EvidenceType",
    "EvidenceRef",
    "DecisionSnapshot",
    "OutcomeSnapshot",
    "Divergence",
    "Attribution",
    "CounterfactualResult",
    "FailureDiagnosis",
    "ReplaySummary",
    "RootCauseAnalysisResult",
]
