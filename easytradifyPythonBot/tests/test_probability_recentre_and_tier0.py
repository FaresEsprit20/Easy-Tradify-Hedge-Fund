"""
Zone/ICT constant lift removed, every probability bar moved down by the same
amount, and unconfirmed (tier 0) entries disabled.
"""

import pytest

from core import asset_analysis_config as cfg
from core import calculations as calc
from core.entry_engine import ALLOW_UNCONFIRMED_ENTRIES, EntryEngine


def _breakdown(**overrides):
    args = dict(trend="NEUTRAL", order_type="BUY", sd_grade="A", is_at_zone=True,
                wyckoff_score=0, wyckoff_phase="CONSOLIDATION", volume_ratio=1.0, rsi_val=50.0,
                ict_signal_type="BULLISH", adx_val=25.0, bb_signal="NEUTRAL", macd_signal="NEUTRAL",
                stoch_signal="NEUTRAL", symbol="EURUSD", atr_pips=1.0, timeframe="M1")
    args.update(overrides)
    return calc.calculate_real_probability(**args)[2]


def test_zone_and_ict_add_nothing():
    b = _breakdown()
    assert b["zone"] == 0.0 and b["ict"] == 0.0


def test_ict_preflight_veto_still_applies():
    probability, _, b = calc.calculate_real_probability(
        trend="NEUTRAL", order_type="BUY", sd_grade="A", is_at_zone=True, wyckoff_score=0,
        wyckoff_phase="CONSOLIDATION", volume_ratio=1.0, rsi_val=50.0, ict_signal_type="BEARISH",
        adx_val=25.0, bb_signal="NEUTRAL", macd_signal="NEUTRAL", stoch_signal="NEUTRAL",
        symbol="EURUSD", atr_pips=1.0, timeframe="M1")
    assert b.get("veto") == "ICT_BEARISH_FOR_BUY"


@pytest.mark.parametrize("name, original", [
    ("MIN_PROBABILITY_FOR_ENTRY", 75), ("TRADE_PROBABILITY_MINIMUM", 75), ("STRONG_ENTRY_THRESHOLD", 85),
    ("DECISION_WAIT_THRESHOLD", 65), ("DECISION_MONITOR_THRESHOLD", 50), ("DECISION_STRONG_ENTRY", 85),
    ("DECISION_ENTRY_WITH_ZONE", 75), ("STAR_5_THRESHOLD", 85), ("STAR_4_THRESHOLD", 75),
    ("STAR_3_THRESHOLD", 65), ("STAR_2_THRESHOLD", 50), ("MINIMUM_PROBABILITY_FOR_TRADE", 75),
])
def test_every_probability_bar_moves_by_the_same_amount(name, original):
    assert getattr(cfg, name) == original - cfg.PROBABILITY_RECENTER_POINTS


def test_timing_confidence_is_not_recentred():
    assert cfg.MIN_ENTRY_CONFIDENCE == 65


def test_entry_tiers_carry_no_probability_or_candle_bar():
    """The tier table only labels the signal count now: the probability is
    judged once by the "probability" rule, and candle age by nothing."""
    engine = EntryEngine()
    assert all(set(t) == {"quality"} for t in engine.signal_thresholds.values())
    assert not hasattr(engine, "min_candle_progress")


def test_no_golden_signal_cannot_enter():
    assert ALLOW_UNCONFIRMED_ENTRIES is False
    engine = EntryEngine()
    assert 0 not in engine.signal_thresholds
    ok, count, kind = engine.evaluate_signals(
        momentum_burst=False, absorption=False, volume_spike=False, at_poi=False)
    assert ok is False and count == 0 and kind == "NO_SIGNAL"


def test_one_golden_signal_still_passes_the_signals_rule():
    engine = EntryEngine()
    ok, count, kind = engine.evaluate_signals(
        momentum_burst=False, absorption=True, volume_spike=False, at_poi=False)
    assert ok is True and count == 1 and kind == "MODERATE"
