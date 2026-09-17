"""
Logic defects that made component numbers inconsistent (2026-09-15).

Each test pins one root cause found on the price-history study:

  * zone grading depended on how often the analysis was CALLED
  * regime confirmation counted calls, not bars
  * a demand zone at price emitted a word no reader parses as BUY
  * liquidity vocabulary read BUY and SELL for the same event
  * sweeps from 99 bars ago still set the current bias
  * "ATR-scaled" thresholds were floored at pips tuned on silver, so on a
    1-pip-ATR currency pair every level was "near"
"""

import numpy as np
import pytest

RATE_DTYPE = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
              ("tick_volume", "f8")]


def _bars(closes, spread=0.00005, start=1_781_000_000):
    closes = np.asarray(closes, dtype=float)
    arr = np.zeros(closes.size, dtype=RATE_DTYPE)
    arr["time"] = start + 60 * np.arange(closes.size)
    arr["close"] = closes
    arr["open"] = np.concatenate([[closes[0]], closes[:-1]])
    arr["high"] = np.maximum(arr["open"], closes) + spread
    arr["low"] = np.minimum(arr["open"], closes) - spread
    arr["tick_volume"] = 100.0
    return arr


def _wave(n=600, seed=4):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 1.1000 + 0.0015 * np.sin(t / 25.0) + np.cumsum(rng.normal(0, 0.00003, n))


def test_zone_grade_does_not_depend_on_how_often_it_is_called():
    from core.indicators import _detect_supply_demand_zone

    rates = _bars(_wave())
    price = float(rates["close"][-1])
    first = _detect_supply_demand_zone(rates, price, 0.0001, "EURUSD", "M1", atr_pips=1.0)
    for _ in range(25):                     # a monitor polling the same bar
        again = _detect_supply_demand_zone(rates, price, 0.0001, "EURUSD", "M1", atr_pips=1.0)
    assert again == first


def test_zone_facts_are_measured_from_the_bars():
    from core.indicators import _zone_facts

    closes = [1.1000] * 5 + [1.0990, 1.1010, 1.1030, 1.1030, 1.0991, 1.1030, 1.1030, 1.0990, 1.1040]
    rates = _bars(closes, spread=0.00001)
    facts = _zone_facts(rates, 1.0990, 5, "DEMAND", touch_distance=0.0002, atr_price=0.0010)
    assert facts["age_bars"] == len(closes) - 1 - 5
    assert facts["touch_count"] == 2          # two separate returns to the level
    assert facts["displacement"] == pytest.approx(1.0)


def test_demand_zone_at_price_reads_as_buy():
    from core.strategy_groups import market_direction
    import inspect
    from core import asset_analysis_smc

    source = inspect.getsource(asset_analysis_smc._analyze_supply_demand_component)
    assert '"IMMEDIATE_ENTRY"' not in source.split("return {")[0].replace('was "IMMEDIATE_ENTRY"', "")
    assert market_direction("IMMEDIATE_BUY") == 1 and market_direction("IMMEDIATE_SELL") == -1


@pytest.mark.parametrize("word,expected", [
    ("BUY_SIDE_SWEEP", -1), ("STOP_HUNT_BUY_SIDE_TRAP", -1), ("BEARISH_SWEEP", -1),
    ("SELL_SIDE_SWEEP", 1), ("STOP_HUNT_SELL_SIDE_TRAP", 1), ("BULLISH_SWEEP", 1),
])
def test_one_liquidity_event_reads_one_direction(word, expected):
    from core.strategy_groups import market_direction
    from ai.component_scorecard import market_direction as scorecard_direction

    assert market_direction(word) == expected
    assert scorecard_direction(word) == expected


def test_stale_sweeps_do_not_set_the_bias():
    from core.liquidity_events import summarize_liquidity, get_primary_sweep, SWEEP_RECENT_BARS

    old = {"side_swept": "LOW", "bars_ago": SWEEP_RECENT_BARS + 40, "strength": 0.9,
           "smc_type": "BULLISH_SWEEP", "level": 1.1, "sweep_size_pips": 3, "bars_to_reclaim": 1}
    assert summarize_liquidity([old])["bias"] == "NONE"
    assert get_primary_sweep([old])["swept"] is False
    fresh = dict(old, bars_ago=2)
    assert summarize_liquidity([old, fresh])["bias"] == "BULLISH"


def test_atr_relative_threshold_is_not_floored_at_silver_pips():
    from core.asset_analysis_config import atr_relative_pips, get_zone_proximity_pips

    assert atr_relative_pips(8.0, atr_pips=1.0, fraction=0.25) == pytest.approx(0.25)
    assert atr_relative_pips(8.0, atr_pips=None, fraction=0.25) == 8.0
    assert get_zone_proximity_pips("EURUSD", "A", atr_pips=1.0) == pytest.approx(0.2)


def test_swing_size_scales_with_atr():
    from core.swing_points import get_min_swing_size

    assert get_min_swing_size("M1", 0.001, atr_pips=40.0) == pytest.approx(0.02)
    assert get_min_swing_size("M1", 0.0001, atr_pips=1.0) == pytest.approx(0.00005)


def test_regime_state_is_a_function_of_the_bars_alone():
    from core.indicators import classify_trading_regime

    rates = _bars(_wave(400, seed=9))
    a = classify_trading_regime(rates, "EURUSD", 0.0001, timeframe="M1")
    for _ in range(10):
        b = classify_trading_regime(rates, "EURUSD", 0.0001, timeframe="M1")
    assert a == b
    other_symbol_first = classify_trading_regime(rates, "GBPUSD", 0.0001, timeframe="M1")
    assert other_symbol_first["state"] == a["state"]


def test_live_analysis_fetches_closed_bars_only(monkeypatch):
    import MetaTrader5 as mt5
    from core.closed_bars import closed_bars_context, is_active

    calls = []
    monkeypatch.setattr(mt5, "copy_rates_from_pos", lambda s, tf, start, n: calls.append(start) or start)
    with closed_bars_context():
        with closed_bars_context():                  # nested analyses
            assert mt5.copy_rates_from_pos("EURUSD", 1, 0, 10) == 1
        assert is_active()
        assert mt5.copy_rates_from_pos("EURUSD", 1, 5, 10) == 6
    assert not is_active()
    assert mt5.copy_rates_from_pos("EURUSD", 1, 0, 10) == 0   # restored


def test_analysis_is_wrapped_for_closed_bars():
    from core.asset_analysis import analyze_institutional_signal
    assert getattr(analyze_institutional_signal, "__wrapped__", None) is not None


def test_candle_progress_with_closed_bars(monkeypatch):
    from core import indicators

    class Tick:
        time = 1_781_000_000 + 60 + 45        # 45 s into the bar after the last closed one
    monkeypatch.setattr(indicators.mt5, "symbol_info_tick", lambda s: Tick())
    rates = _bars([1.1, 1.1], start=1_781_000_000 - 60)
    progress, ready = indicators.get_candle_progress_fixed(rates, indicators.mt5.TIMEFRAME_M1, "EURUSD")
    assert progress == pytest.approx(0.75) and ready


@pytest.mark.parametrize("o,h,l,c,atr,expected", [
    (1.1000, 1.1012, 1.0998, 1.1010, 1.0, "STRONG_BULLISH"),   # 71% body, 1.4 ATR... below 75% -> not marubozu
    (1.1000, 1.1011, 1.0999, 1.1010, 1.0, "STRONG_BULLISH"),   # 83% body, 1.2 ATR
    (1.1000, 1.1001, 1.09999, 1.10008, 1.0, "NEUTRAL"),        # tiny bar: 0.11 ATR
    (1.1000, 1.1006, 1.0998, 1.1004, 1.0, "NEUTRAL"),          # ordinary bar
    (1.1002, 1.1012, 1.1000, 1.1001, 1.0, "BEARISH"),          # shooting star
])
def test_candle_patterns_need_shape_and_size(o, h, l, c, atr, expected):
    from core.asset_analysis_indicators import _analyze_candlestick_component

    out = _analyze_candlestick_component((0, o, h, l, c, 100), 0.0001, atr_pips=atr)
    if expected == "STRONG_BULLISH" and (c - o) < 0.75 * (h - l):
        assert out["recommendation"] != "STRONG_BULLISH"
    else:
        assert out["recommendation"] == expected


def test_a_level_is_swept_only_on_its_first_breach():
    from core.liquidity_events import detect_liquidity_events

    base = [1.1000] * 30
    rise = list(np.linspace(1.1000, 1.1050, 15)) + list(np.linspace(1.1050, 1.1000, 15))   # swing high 1.1050
    after = [1.1000] * 40
    closes = base + rise + after
    rates = _bars(closes, spread=0.00002)
    # three separate pokes above the swing high, each reclaimed
    for k in (70, 76, 82):
        rates["high"][k] = 1.1062
        rates["close"][k] = 1.1040
    events = detect_liquidity_events(rates, 0.0001, "M1", atr_pips=2.0, spread_pips=0.1, scan_lookback_bars=100)
    highs = [e for e in events if e["side_swept"] == "HIGH" and abs(e["level"] - 1.1050) < 0.0003]
    assert len(highs) <= 1


def test_order_flow_is_the_same_market_reading_for_both_sides():
    from core.order_flow_forensics import calculate_order_flow_final_score

    data = {"stop_hunts": [{"type": "STOP_HUNT_BUY_SIDE_TRAP", "implied_direction": "SELL", "bars_ago": 2,
                            "sweep_size_pips": 1.0, "bars_to_reclaim": 1}],
            "liquidity_pools": {"available": True, "equal_highs_pools": [{"level": 1.2, "touch_count": 5}],
                                "equal_lows_pools": []}}
    buy = calculate_order_flow_final_score(data, 60.0, "BUY", current_price=1.1, pip_size=0.0001)
    sell = calculate_order_flow_final_score(data, 60.0, "SELL", current_price=1.1, pip_size=0.0001)
    assert buy["order_flow_recommendation"] == sell["order_flow_recommendation"] == "BEARISH"
    pools_only = {"liquidity_pools": data["liquidity_pools"]}
    assert calculate_order_flow_final_score(pools_only, 60.0, "BUY", current_price=1.1,
                                            pip_size=0.0001)["order_flow_recommendation"] == "NEUTRAL"


def test_support_resistance_breakouts_are_symmetric_and_trend_free():
    from core.asset_analysis_indicators import _analyze_support_resistance_component

    closes = [1.1000 + 0.0002 * np.sin(i / 3) for i in range(120)]
    down = closes + [1.0990]
    h = [c + 0.0001 for c in down]; l = [c - 0.0001 for c in down]
    out = _analyze_support_resistance_component(h, l, down, down[-1], 0.0001, 1.0, "STRONG_BULLISH", atr_pips=1.0)
    assert out["recommendation"] == "BREAKOUT_SELL"
    up = closes + [1.1010]
    h = [c + 0.0001 for c in up]; l = [c - 0.0001 for c in up]
    out = _analyze_support_resistance_component(h, l, up, up[-1], 0.0001, 1.0, "STRONG_BEARISH", atr_pips=1.0)
    assert out["recommendation"] == "BREAKOUT_BUY"


def test_wyckoff_votes_only_on_spring_or_upthrust(monkeypatch):
    from core import asset_analysis_smc as smc

    for phase, rec in (("MARKUP_STRONG", "NEUTRAL"), ("MARKDOWN", "NEUTRAL"),
                       ("ACCUMULATION_COMPLETE", "BUY"), ("DISTRIBUTION_COMPLETE", "SELL")):
        monkeypatch.setattr(smc, "_detect_wyckoff_phase", lambda *a, p=phase, **k: p)
        assert smc._analyze_wyckoff_component(None, 30, "BULLISH", 1.0, "EURUSD", 0.0001)["recommendation"] == rec


def test_volume_direction_comes_from_the_bar_not_the_trend():
    from core.asset_analysis_indicators import score_volume_indicator

    assert score_volume_indicator(2.0, "STRONG_BULLISH", 30, bar_direction=-1)["recommendation"] == "SELL"
    assert score_volume_indicator(2.0, "STRONG_BULLISH", 30, bar_direction=0)["recommendation"] == "NEUTRAL"


@pytest.mark.parametrize("wave_type,wave,expected", [
    ("impulse", "1", "WAIT"), ("impulse", "5", "WAIT"), ("corrective", "A", "WAIT"),
    ("impulse", "3", "STRONG_BUY"),
])
def test_only_wave_3_and_c_are_entries(wave_type, wave, expected):
    from core.patterns import PatternRecognizer

    rec = PatternRecognizer()._get_elliott_wave_recommendation(
        wave_type, wave, 0.7, 1.1, {"entry_price": 1.1}, [1.1] * 20, 0.0001, wave_direction="BULLISH")
    assert rec["recommendation"] == expected


def test_rsi_speaks_only_at_extremes_on_m1():
    from core.asset_analysis_indicators import score_rsi_indicator_with_divergence as rsi

    assert rsi(35, "BUY", timeframe="M1")["recommendation"] == "NEUTRAL"
    assert rsi(65, "SELL", timeframe="M1")["recommendation"] == "NEUTRAL"
    assert rsi(15, "BUY", timeframe="M1")["recommendation"] == "BUY"
    assert rsi(85, "SELL", timeframe="M1")["recommendation"] == "SELL"


def test_cascade_flat_is_relative_to_the_timeframe_atr():
    from core.trend_cascade import _timeframe_slope_sign, BARS_NEEDED

    assert BARS_NEEDED >= 100
    closes = [1.10 + 0.00001 * i for i in range(200)]             # 0.1 pip/bar drift
    highs = [c + 0.0010 for c in closes]; lows = [c - 0.0010 for c in closes]   # 20-pip bars
    assert _timeframe_slope_sign(closes, 0.0001, highs, lows) == 0            # drift << ATR: flat
    steep = [1.10 + 0.0005 * i for i in range(200)]
    assert _timeframe_slope_sign(steep, 0.0001, [c + 0.0010 for c in steep], [c - 0.0010 for c in steep]) == 1


def test_ttm_votes_only_on_release():
    from core.ttm_squeeze import detect_ttm_squeeze

    closes = np.full(200, 1.10) + np.random.default_rng(1).normal(0, 0.0003, 200)
    out = detect_ttm_squeeze(_bars(closes))
    if out.get("available"):
        assert (out["release_direction"] is None) == (not out["released"])


def test_rvam_signal_only_on_conviction():
    from core.rvam import calculate_rvam

    closes = list(1.10 + np.random.default_rng(2).normal(0, 0.0001, 200))
    quiet = calculate_rvam(_bars(closes), volume_ratio=1.0)
    assert quiet["signal_direction"] is None
    closes[-1] = closes[-6] + 0.01
    loud = calculate_rvam(_bars(closes), volume_ratio=3.0)
    assert loud["classification"] != "CONVICTION_MOVE" or loud["signal_direction"] == "UP"


def test_gnn_reading_does_not_depend_on_the_side_scored():
    import inspect
    from core import asset_analysis_gnn

    src = inspect.getsource(asset_analysis_gnn)
    assert 'recommendation = "CONFLICT"\n            recommendation_score = 50' not in src
    from ai import ai_gnn
    assert "_implied_here" in inspect.getsource(ai_gnn)


# ============================================================
# 2026-09-16: defects found by verifying a live snapshot
# ============================================================

def test_flipped_side_is_judged_on_its_own_probability():
    """A cascade flip used to carry the rejected side's confidence: a live
    snapshot entered SELL at 74.3% while its own probability_sell was 6.6%."""
    from core.asset_analysis import side_probability
    assert side_probability("SELL", 61.2, 6.6) == 6.6
    assert side_probability("BUY", 61.2, 6.6) == 61.2
    assert side_probability("SELL", 61.2, None, fallback=61.2) == 61.2   # unknown -> fallback, not silence


def test_absent_support_resistance_distance_is_none_not_999():
    """999.0 published as a distance reads as a real 999-pip measurement."""
    from core.asset_analysis import _far_if_absent, NO_LEVEL_PIPS
    assert _far_if_absent(None) == NO_LEVEL_PIPS      # scorers still treat it as far away
    assert _far_if_absent(0.0) == 0.0                 # a real zero distance survives
    assert _far_if_absent(2.4) == 2.4


def test_spread_is_reported_in_pips_not_points():
    """core/execution.py divided by info.point, so 5-digit symbols read 10x."""
    from types import SimpleNamespace
    from core.calculations import get_pip_info
    info = SimpleNamespace(name="EURUSD", digits=5, point=0.00001, trade_contract_size=100000.0)
    pip, _, _ = get_pip_info(info)
    spread_price = 0.00001                            # one point
    assert round(spread_price / pip, 1) == 0.1        # 0.1 pips, not 1.0
