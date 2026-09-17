"""
The trend cascade decides the traded side when it is decisive and disagrees.

Measured on the stored trades: trade direction right 70.5% with the cascade vs
40.7% against it. The override must (a) flip only on a decisive, available
cascade, (b) never act as a veto, and (c) run BEFORE the stop/target/lot are
sized, or the bracket belongs to the side that was not traded.
"""

import ast
import pathlib

import pytest

from core import trend_cascade as tc
from core.trend_cascade import cascade_direction_override


def cascade(direction, score, available=True):
    return {"available": available, "direction": direction, "score": score}


@pytest.mark.parametrize("result, best, expected", [
    (cascade("BEARISH", -0.7), "BUY", "SELL"),
    (cascade("BULLISH", 1.0), "SELL", "BUY"),
    (cascade("BULLISH", 0.3), "SELL", "BUY"),          # exactly the act threshold
    (cascade("BULLISH", 0.8), "BUY", None),            # already agrees
    (cascade("BEARISH", -0.9), "SELL", None),
    (cascade("NEUTRAL", 0.1), "BUY", None),            # indecisive
    (cascade("BEARISH", -0.2), "BUY", None),           # below threshold
    (cascade("BEARISH", -1.0, available=False), "BUY", None),
    ({}, "BUY", None),
    (None, "BUY", None),
    (cascade("BEARISH", "garbage"), "BUY", None),
    (cascade("BEARISH", -1.0), "HOLD", None),
])
def test_override(result, best, expected, monkeypatch):
    """The override LOGIC, with the switch forced on -- it ships off (see
    test_cascade_does_not_decide_direction_by_default)."""
    monkeypatch.setattr(tc, "TREND_CASCADE_DECIDES_DIRECTION", True)
    assert cascade_direction_override(result, best) == expected


def test_cascade_does_not_decide_direction_by_default():
    """Turned off 2026-09-16. On tick-accurate brackets over 110,603 study
    snapshots the flip earned nothing -- flipped 41.5% right / -0.190R against
    unflipped 42.0% / -0.185R -- and it made the entry gate test the rejected
    side's probability. The cascade still nudges the probability."""
    assert tc.TREND_CASCADE_DECIDES_DIRECTION is False
    assert cascade_direction_override(cascade("BEARISH", -1.0), "BUY") is None


def test_switch_off_restores_nudge_only(monkeypatch):
    monkeypatch.setattr(tc, "TREND_CASCADE_DECIDES_DIRECTION", False)
    assert cascade_direction_override(cascade("BEARISH", -1.0), "BUY") is None


def _analysis_source():
    path = pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py"
    return path.read_text(encoding="utf-8")


def test_side_is_decided_before_sizing():
    source = _analysis_source()
    override = source.index("cascade_direction_override(trend_cascade_result, best_direction)")
    sizing = source.index("effective_order_type = best_direction")
    lot = source.index("lot_result = calculate_lot_proper(")
    assert override < sizing < lot


def test_cascade_is_read_once():
    """A second fetch could see a newer bar and contradict the side traded."""
    source = _analysis_source()
    assert source.count("get_trend_cascade(symbol, pip_size)") == 1


def test_flip_switches_to_the_traded_side_probability():
    """Superseded 2026-09-16 the earlier rule that the flip kept the rejected
    side's confidence. A live snapshot entered SELL at 74.3% while the same
    payload reported probability_sell 6.6%, and the flip earns nothing either
    way (110,603 study snapshots: flipped 41.5% right / -0.190R, unflipped
    42.0% / -0.185R), so the gate must test the side actually traded."""
    source = _analysis_source()
    start = source.index("_cascade_side = cascade_direction_override(")
    block = source[start:source.index("direction_decision = {", start)]
    assert "best_probability = side_probability(" in block
    assert "probability_buy, probability_sell" in block


def test_module_still_parses():
    ast.parse(_analysis_source())


def test_ict_veto_on_the_cascade_side_is_overruled_not_enforced():
    """Measured: ICT opposition to a cascade flip carries no information
    (49.0% vs 50.7% right on 35k study bars), so it must not reach coherence
    as a CRITICAL -- which conviction would turn into a blocked trade."""
    source = _analysis_source()
    start = source.index("_cascade_side = cascade_direction_override(")
    block = source[start:source.index("direction_decision = {", start)]
    assert 'startswith("ICT_")' in block
    assert 'directional_veto_info["veto_overruled_by_trend_cascade"]' in block


def test_coherence_is_silent_for_an_overruled_veto():
    from core.coherence import _check_direction_consistency

    vetoed = {"directional_analysis": {"directional_vetoes": {
        "buy_veto": None, "sell_veto": "ICT_BULLISH_FOR_SELL", "both_directions_vetoed": False,
        "chosen_direction_was_vetoed": False, "veto_overruled_by_trend_cascade": "ICT_BULLISH_FOR_SELL"}}}
    assert _check_direction_consistency(vetoed) == []
    vetoed["directional_analysis"]["directional_vetoes"]["chosen_direction_was_vetoed"] = True
    assert _check_direction_consistency(vetoed)[0]["invariant"] == "vetoed_direction_chosen"
