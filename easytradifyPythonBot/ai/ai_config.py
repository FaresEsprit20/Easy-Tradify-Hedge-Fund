# ============================================================
# AI CONFIG - shared config object for the ai/ package
# ============================================================
# This file was empty (0 bytes), which made `ai/__init__.py`'s
# `from .ai_config import AIConfig, default_config` raise ImportError
# unconditionally -- breaking every import of the `ai` package,
# including `from ai.ai_gnn import AssetGraphNeuralNetwork`. That import
# is wrapped in try/except ImportError in core/asset_analysis_gnn.py,
# so the failure was silent: GNN_AVAILABLE was permanently False and
# every calculate_gnn_final_score() call degraded to a no-op, on every
# run, regardless of Python version, torch, or MT5 state.
#
# Field values below match what ai_gnn.py/ai_adversarial.py actually
# read off this object (grepped both files for `self.config.` /
# `getattr(self.config, ...)`), not a guess at unrelated functionality.
# ============================================================

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AIConfig:
    # --- GNN (ai_gnn.py) ---
    gnn_enabled: bool = True
    gnn_update_interval: float = 30.0
    gnn_assets: Optional[List[str]] = None

    # --- Adversarial training (ai_adversarial.py, all read via getattr) ---
    adversarial_training_enabled: bool = True
    adversarial_intensity: float = 0.7
    adversarial_variations: int = 50
    adversarial_attack_both: bool = True
    adversarial_apply_to_components: bool = True
    adversarial_apply_to_ensemble: bool = False
    adversarial_max_variations: int = 100
    adversarial_attack_probability: float = 0.8


default_config = AIConfig()
