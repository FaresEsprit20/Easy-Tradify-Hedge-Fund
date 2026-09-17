"""FVG/IFVG moves probability by at most +5 (aligned) / -1 (opposed).

It agreed with most stored trades yet the trades it opposed did better, so it
is no longer a +15 point booster.
"""

from core.asset_analysis_config import FVG_IFVG_WEIGHT
from core.asset_analysis_smc import calculate_fvg_ifvg_final_score


def test_weight_is_small():
    assert FVG_IFVG_WEIGHT <= 0.05


def test_full_strength_aligned_gap_adds_at_most_five():
    result = calculate_fvg_ifvg_final_score({"recommendation": "SELL", "score": -25}, 80.0, "SELL")
    assert result["fvg_ifvg_contribution"] == 5.0
    assert result["final_score"] == 85.0


def test_opposed_gap_costs_at_most_one():
    result = calculate_fvg_ifvg_final_score({"recommendation": "BUY", "score": 25}, 80.0, "SELL")
    assert result["fvg_ifvg_contribution"] == -1.0
