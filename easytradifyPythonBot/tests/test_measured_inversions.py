"""
Two inversions the replay measured, and nothing more than what it measured
(2026-09-17). Both were found by the operator's method: instead of asking "does
this rule let winners through", ask "what happens if it is turned around".

  1. confirmation is BACKWARDS. A decision the bar confirmed won 28.0%; one it
     did not won 30.3% -- and it holds in every category once each band is
     judged against its own free barrier rate. ENTRY_RULE_POLARITY flips what
     counts as passing; the condition itself is still measured and recorded
     unchanged. (discount looked the same on raw win rate and did NOT survive
     that control -- see the config.)

  2. The engine's chosen SIDE loses to its own opposite by 2.7 points of win
     rate (29.2% vs 32.0%) on 60,853 decisions scored both ways on the same
     bars. INVERT_ENTRY_DIRECTION trades the other side.

These reduce the loss. They do not make the system profitable and these tests do
not pretend otherwise: both sides of every trade still lose, and
test_the_inversion_is_not_claimed_to_be_profitable keeps that on the record.
"""

import pathlib

import pytest

from core import asset_analysis_config as cfg
from core.entry_engine import (BLOCK, OBSERVE, RULE_ORDER, RULE_STATUS, RULE_STATUS_INVERTED,
                               EntryEngine)

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. the two backwards rules
# ---------------------------------------------------------------------------

def test_only_the_two_measured_rules_are_inverted():
    """Polarity is evidence, not taste: exactly the two rules the replay flipped."""
    # discount looked identical on raw win rate but FLIPS in SMC and is FLAT in
    # TREND once each band is judged against its own free barrier rate, so it is
    # NOT inverted. Only what survived the geometry control is here.
    assert cfg.ENTRY_RULE_POLARITY == {"confirmation": -1}
    assert all(name in RULE_ORDER for name in cfg.ENTRY_RULE_POLARITY)
    # and an inverted rule only blocks because it was measured to help that way
    assert cfg.ENTRY_RULE_MODES["confirmation"] == "block"
    assert cfg.ENTRY_RULE_MODES["discount"] == "observe"


def test_an_inverted_rule_passes_on_the_opposite_condition():
    """The bar that confirms the side now FAILS the rule, and vice versa."""
    from tests.test_entry_rule_table import BEARISH_BAR, BULLISH_BAR, _decide, _engine

    # BUY: a bullish bar confirms the side, a bearish one does not
    confirmed = _decide(_engine(), candle_data=BULLISH_BAR)
    not_confirmed = _decide(_engine(), candle_data=BEARISH_BAR)
    assert confirmed["rules"]["confirmation"]["passed"] is False      # confirmed -> too late
    assert not_confirmed["rules"]["confirmation"]["passed"] is True
    # the reading itself is still recorded, so old decisions stay comparable
    assert confirmed["rules"]["confirmation"]["polarity"] == -1
    assert "INVERTED" in confirmed["rules"]["confirmation"]["why"]


def test_an_inverted_rule_reports_why_it_really_blocked():
    """WAITING_CONFIRMATION would be a lie when the block happened BECAUSE it confirmed."""
    assert RULE_STATUS_INVERTED == {"confirmation": "ALREADY_CONFIRMED"}
    assert RULE_STATUS["confirmation"] == "WAITING_CONFIRMATION"      # the un-inverted name survives
    for name in RULE_STATUS_INVERTED:
        assert cfg.ENTRY_RULE_POLARITY.get(name) == -1


def test_a_rule_with_no_reading_stays_unmeasurable_when_inverted():
    """None is 'the rule could not be evaluated' -- inverting must not turn it into a pass."""
    engine = EntryEngine({"rule_modes": {name: OBSERVE for name in RULE_ORDER}})
    d = engine.get_entry_decision(symbol="EURUSD", best_direction="BUY", current_price=1.0860,
                                  zone_level=1.0840, zone_type="DEMAND", zone_grade="B",
                                  candle_data=None, volume_spike=False, at_poi=False,
                                  best_probability=78.0, pip_size=0.0001, atr_pips=10.0,
                                  probability_floor=75.0)
    assert d["rules"]["confirmation"]["passed"] is None


# ---------------------------------------------------------------------------
# 2. the direction
# ---------------------------------------------------------------------------

def test_the_traded_side_is_the_opposite_of_the_analysis():
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    block = src[src.index("measured direction inversion"):src.index("[DIRECTION INVERTED]")]
    assert 'best_direction = "SELL" if str(best_direction).upper() == "BUY" else "BUY"' in block
    # the probability must follow the side actually traded, not the one dropped
    assert "best_probability = side_probability(best_direction" in block
    # and the veto record must describe the traded side
    assert 'directional_veto_info["chosen_direction_was_vetoed"]' in block


def test_the_flip_happens_before_setups_so_the_geometry_is_coherent():
    """A setup's stop and target are direction-specific: flipping after they are
    chosen would trade one side with the other side's levels."""
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert src.index("INVERT_ENTRY_DIRECTION:") < src.index("strategy_setup = pick_strategy_setup(")


# ---------------------------------------------------------------------------
# 3. what these changes do NOT do
# ---------------------------------------------------------------------------

def test_the_inversion_is_not_claimed_to_be_profitable():
    """Both sides lose. The config says so, and it stays saying so."""
    src = (ROOT / "core" / "asset_analysis_config.py").read_text(encoding="utf-8")
    block = src[src.index("Direction inversion"):src.index("INVERT_ENTRY_DIRECTION =")]
    assert "HONEST LIMIT" in block
    assert "BOTH sides" in block and "lose" in block
    assert "Demo only" in block
    # the measured numbers travel with the switch, so nobody has to trust a memory
    for number in ("29.2%", "32.0%", "-0.168R", "-0.729R", "60,853"):
        assert number in block, number
