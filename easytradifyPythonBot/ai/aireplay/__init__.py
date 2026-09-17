# ============================================================
# AI_MarketReplay
# ============================================================
#
# Built in the order the readme's section 60 lays out. Phase 1 (Data
# Foundation) is complete; later phases add the modules the specification
# names -- replay_engine, intelligence_engine, experiment_engine,
# learning_engine, validation_engine, reporting_engine, cli.
#
#   PHASE 1  models.py       canonical schema, Decision Genome, temporal
#                            metadata, feature availability, snapshots
#            data_engine.py  extraction, immutability, replay records
#
# Imports are flat and unconditional here, unlike ai/__init__.py -- every
# module referenced below exists. That file listed ~15 modules that were never
# written, which made `import ai` fail permanently and silently disabled GNN.
# ============================================================

from .models import (
    REPLAY_MODELS_VERSION,
    SCHEMA_VERSION,
    Availability,
    CanonicalTrade,
    DecisionGenome,
    DecisionSnapshot,
    EventType,
    FeatureSpec,
    MarketState,
    Provenance,
    availability_of,
    content_hash,
    utc_now,
)
from .data_engine import (
    DATA_ENGINE_VERSION,
    analysis_coverage,
    build_genome,
    carry_unmapped,
    describe_features,
    detect_mutation,
    extract_decision_snapshots,
    extract_replay_records,
    get_status,
    self_check,
    snapshot_fingerprint,
    to_canonical_trade,
)

from .replay_engine import (
    REPLAY_ENGINE_VERSION,
    EventStream,
    ReplayEvent,
    build_event_stream,
    detect_divergences,
    reconstruct_decision,
    reconstruct_reality,
    replay_trade,
    replay_trades,
)
from .counterfactual import (
    COUNTERFACTUAL_VERSION,
    aggregate_branches,
    branch_trade,
)
from .consistency import (
    CONSISTENCY_VERSION,
    compare_simulators,
    consistency_report,
)
from .stress import (
    STRESS_VERSION,
    aggregate_stress,
    stress_trade,
    stress_trades,
)
from .recorder import (
    RECORDER_VERSION,
    DecisionSnapshotRecorder,
    get_recorder,
    reset_recorder,
)

__version__ = "1.0"
PHASE = "3 - Replay (items 1-7, 14); Phases 1-2 complete"

__all__ = [
    "__version__", "PHASE", "SCHEMA_VERSION", "REPLAY_MODELS_VERSION",
    "DATA_ENGINE_VERSION",
    "Availability", "EventType", "FeatureSpec", "Provenance", "MarketState",
    "DecisionGenome", "DecisionSnapshot", "CanonicalTrade",
    "availability_of", "content_hash", "utc_now",
    "build_genome", "describe_features", "to_canonical_trade",
    "analysis_coverage", "carry_unmapped",
    "extract_decision_snapshots", "extract_replay_records",
    "snapshot_fingerprint", "detect_mutation", "get_status", "self_check",
    "RECORDER_VERSION", "DecisionSnapshotRecorder", "get_recorder",
    "reset_recorder",
    "REPLAY_ENGINE_VERSION", "ReplayEvent", "EventStream",
    "build_event_stream", "reconstruct_reality", "reconstruct_decision",
    "detect_divergences", "replay_trade", "replay_trades",
    "COUNTERFACTUAL_VERSION", "branch_trade", "aggregate_branches",
    "CONSISTENCY_VERSION", "compare_simulators", "consistency_report",
    "STRESS_VERSION", "stress_trade", "stress_trades", "aggregate_stress",
]
