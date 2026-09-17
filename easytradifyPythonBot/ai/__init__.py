# ============================================================
# AI PACKAGE
# ============================================================
#
# ✅ FIXED: this file used to hard-import ~15 submodules
# (ai_scorer, ai_adaptive, ai_performance, ai_data, ai_component_trainer,
# ai_ensemble, ai_predictor, ai_meta_learner, ai_correction, ai_evolution,
# ai_self_correction, ai_calibration) that do not exist anywhere in this
# directory, plus `AIReinforcement` from ai_reinforcement.py (rewritten
# since as standalone research scaffolding with no such class) and
# `AIAssetAnalyzer`/`analyze_institutional_signal_ai` from
# ai_asset_analysis.py (0 bytes). Every one of those was an unconditional
# `from .x import y` -- so `import ai`, or `from ai.<anything> import X`,
# raised ImportError unconditionally, on every process start.
#
# That silently broke every caller that guards its own import of this
# package with try/except ImportError (core/asset_analysis_gnn.py's
# `from ai.ai_gnn import AssetGraphNeuralNetwork`, and the
# price_evolution_* imports in monitor/) -- GNN_AVAILABLE was
# permanently False, and price-evolution compression silently disabled,
# with no error ever surfacing.
#
# This now only imports what actually exists in this directory. Legacy
# names with no corresponding module are simply not exported -- adding
# them back requires writing those modules for real, not re-declaring
# imports that point at nothing.
# ============================================================

__version__ = "2.3.0"

# ============================================================
# CONFIGURATION
# ============================================================

from .ai_config import AIConfig, default_config

# ============================================================
# GRAPH NEURAL NETWORK (CROSS-ASSET LEARNING)
# ============================================================
# Kept try/except-guarded (torch/MT5-adjacent optional deps can still be
# genuinely absent in some environments) -- but with ai_config fixed
# above, this now actually succeeds instead of always failing.

try:
    from .ai_gnn import AssetGraphNeuralNetwork
    from .ai_gnn_lightweight import LightweightGNNFetcher
    HAS_GNN = True
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"GNN unavailable: {e}")
    HAS_GNN = False
    AssetGraphNeuralNetwork = None
    LightweightGNNFetcher = None

# ============================================================
# ADVERSARIAL TRAINING
# ============================================================

from .ai_adversarial import AIAdversarial

# ============================================================
# SELF-CORRECTION (evidence-only redesign; see root_cause_*.py)
# ============================================================

from .root_cause_models import RootCauseAnalysisResult, FailureDiagnosis
from .root_cause_trackers import RootCauseEvidenceTracker
from .root_cause_analyzers import RootCauseAnalyzer

# ============================================================
# PRICE EVOLUTION ENCODER / DECODER / BRIDGE
# ============================================================

from .price_evolution_maps import EvolutionMaps
from .price_evolution_encoder import PriceEvolutionEncoder
from .price_evolution_decoder import PriceEvolutionDecoder
from .price_evolution_bridge import PriceEvolutionBridge

# ============================================================
# ASSET DIAGNOSTIC (offline/manual dev tool)
# ============================================================

from .ai_asset_diagnostic import AssetDiagnostic, run_diagnostic

# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    '__version__',

    # Configuration
    'AIConfig',
    'default_config',

    # GNN
    'AssetGraphNeuralNetwork',
    'LightweightGNNFetcher',
    'HAS_GNN',

    # Adversarial
    'AIAdversarial',

    # Self-correction
    'RootCauseAnalysisResult',
    'FailureDiagnosis',
    'RootCauseEvidenceTracker',
    'RootCauseAnalyzer',

    # Price evolution
    'EvolutionMaps',
    'PriceEvolutionEncoder',
    'PriceEvolutionDecoder',
    'PriceEvolutionBridge',

    # Diagnostic
    'AssetDiagnostic',
    'run_diagnostic',
]
