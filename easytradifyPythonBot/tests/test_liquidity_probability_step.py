"""
Liquidity sweeps are a step in the probability chain.

Measured on the stored trades: direction right 65.7% when the sweep bias
agreed vs 40.6% when it opposed. Before this, the bias was output-only.
"""

import pathlib

import pytest

from core.liquidity_events import (LIQUIDITY_MAX_BONUS, LIQUIDITY_MAX_PENALTY,
                                   calculate_liquidity_final_score)


def summary(bias, buy_side=2, sell_side=1, available=True):
    return {"available": available, "bias": bias, "buy_side_sweeps": buy_side,
            "sell_side_sweeps": sell_side, "event_count": buy_side + sell_side}


@pytest.mark.parametrize("bias, side, adjustment, aligned", [
    ("BULLISH", "BUY", LIQUIDITY_MAX_BONUS, True),
    ("BEARISH", "SELL", LIQUIDITY_MAX_BONUS, True),
    ("BEARISH", "BUY", LIQUIDITY_MAX_PENALTY, False),
    ("BULLISH", "SELL", LIQUIDITY_MAX_PENALTY, False),
])
def test_bias_moves_probability(bias, side, adjustment, aligned):
    result = calculate_liquidity_final_score(summary(bias), 70.0, side)
    assert result["adjustment"] == adjustment
    assert result["aligned"] is aligned
    assert result["final_score"] == 70.0 + adjustment


@pytest.mark.parametrize("s, side", [
    ({"available": True, "bias": "NONE", "event_count": 0}, "BUY"),
    ({"available": False}, "SELL"),
    (None, "BUY"),
    (summary("BULLISH"), "HOLD"),
])
def test_no_evidence_moves_nothing(s, side):
    result = calculate_liquidity_final_score(s, 62.5, side)
    assert result["adjustment"] == 0.0
    assert result["final_score"] == 62.5
    assert result["aligned"] is None


def test_clamped_but_intended_kept():
    result = calculate_liquidity_final_score(summary("BULLISH"), 92.0, "BUY")
    assert result["final_score"] == 95.0
    assert result["intended"] == 102.0          # the ledger records the push the clamp absorbed


def test_opposed_bias_can_pull_below_threshold():
    """A counter-sweep entry at 80 must not stay comfortably above the 75 entry bar."""
    assert calculate_liquidity_final_score(summary("BEARISH"), 80.0, "BUY")["final_score"] < 75.0


def _source():
    return (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")


def test_step_is_in_the_chain_and_recorded():
    src = _source()
    assert '_ledger_step(probability_ledger, "liquidity_sweeps"' in src
    assert src.index("calculate_liquidity_final_score(liquidity_summary") < src.index('"liquidity_final_score": liquidity_final')


def test_events_variable_initialised_before_try():
    src = _source()
    assert src.index("_liq_events = None") < src.index("_liq_events = detect_liquidity_events(")
