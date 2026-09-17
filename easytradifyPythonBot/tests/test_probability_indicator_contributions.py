"""
Indicator contributions in calculate_real_probability, re-set from the stored
trades' tick paths (see the MEASURED INDICATOR CONTRIBUTIONS section in
core/asset_analysis_config.py).
"""

import pytest

from core import calculations as calc
from core.asset_analysis_config import (MACD_SCORE_AGAINST, MACD_SCORE_FADING,
                                        MACD_SCORE_TURNING_WITH, MACD_SCORE_WITH)


@pytest.mark.parametrize("signal, side, expected", [
    ("BULLISH", "BUY", MACD_SCORE_WITH),
    ("BEARISH", "SELL", MACD_SCORE_WITH),
    ("NEUTRAL_BEARISH", "BUY", MACD_SCORE_TURNING_WITH),     # histogram turned up under zero
    ("NEUTRAL_BULLISH", "SELL", MACD_SCORE_TURNING_WITH),
    ("NEUTRAL_BULLISH", "BUY", MACD_SCORE_FADING),           # was +8: momentum rolling over
    ("NEUTRAL_BEARISH", "SELL", MACD_SCORE_FADING),          # was +15
    ("BEARISH", "BUY", MACD_SCORE_AGAINST),
    ("BULLISH", "SELL", MACD_SCORE_AGAINST),
    ("NEUTRAL", "BUY", 0.0),
    (None, "SELL", 0.0),
    ("garbage", "BUY", 0.0),
])
def test_macd_follows_momentum(signal, side, expected):
    assert calc._macd_contribution(signal, side) == expected


@pytest.mark.parametrize("signal", ["BULLISH", "BEARISH", "NEUTRAL_BULLISH", "NEUTRAL_BEARISH", "NEUTRAL"])
def test_macd_is_symmetric(signal):
    mirror = {"BULLISH": "BEARISH", "BEARISH": "BULLISH", "NEUTRAL_BULLISH": "NEUTRAL_BEARISH",
              "NEUTRAL_BEARISH": "NEUTRAL_BULLISH", "NEUTRAL": "NEUTRAL"}[signal]
    assert calc._macd_contribution(signal, "BUY") == calc._macd_contribution(mirror, "SELL")


def _probability(**overrides):
    args = dict(trend="NEUTRAL", order_type="BUY", sd_grade="B", is_at_zone=True,
                wyckoff_score=0, wyckoff_phase="CONSOLIDATION", volume_ratio=1.0, rsi_val=50.0,
                ict_signal_type="NONE", adx_val=25.0, bb_signal="NEUTRAL", macd_signal="NEUTRAL",
                stoch_signal="NEUTRAL", symbol="EURUSD", atr_pips=1.0, timeframe="M1")
    args.update(overrides)
    return calc.calculate_real_probability(**args)[2]


def test_breakdown_uses_new_macd():
    assert _probability(macd_signal="NEUTRAL_BULLISH")["macd"] == MACD_SCORE_FADING


def test_trend_bollinger_stochastic_are_scaled():
    b = _probability(trend="BULLISH", bb_signal="BULLISH", stoch_signal="BULLISH_X", bb_band_width=1.0)
    assert b["trend"] == 10 * calc.PROB_SCALE_TREND
    assert b["bb"] == calc.BB_SCORE_BULLISH * calc.PROB_SCALE_BOLLINGER
    assert b["stochastic"] == 5 * calc.PROB_SCALE_STOCHASTIC


def test_rsi_impact_and_low_adx_penalty_removed():
    b = _probability(rsi_val=35.0, adx_val=12.0)
    assert b["rsi_impact"] == 0.0
    assert b["adx_penalty"] == 0.0


def test_signal_cap_counts_fading_momentum_as_bearish():
    b = _probability(macd_signal="NEUTRAL_BULLISH")
    assert b["bearish_signal_count"] >= 1
    b = _probability(macd_signal="NEUTRAL_BEARISH")
    assert b["bearish_signal_count"] == 0
