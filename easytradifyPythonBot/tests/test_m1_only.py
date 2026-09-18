"""
M1 only (operator rule, 2026-09-18). Every signal, filter and trend reading is
computed on M1 bars; the live analysis requests no other timeframe.

The live check (a spy on every MT5 bar request during a real analysis) runs
with TRADIFY_LIVE_SNAPSHOT=1 and MT5 open. Before the switch one EURUSD
analysis made 18 M1 requests and 38 on M5/M15/H1/H4/D1; after it, 19 and 0.
"""

import os
import pathlib

import pytest

from core import asset_analysis_config as cfg
from core import strategy_groups as sg

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_m1_only_is_on():
    assert cfg.M1_ONLY is True


def _payload(cascade, m1_side, trend_rec):
    return {"trend_cascade": {"available": True, "direction": cascade, "score": 1.0},
            "higher_timeframe": {"trend": cascade},
            "trend_confirmation": {"m1_price_vs_ema200": m1_side},
            "indicators": {"trend": {"recommendation": trend_rec, "confidence": 80}}}


def _members(result):
    return result["groups"]["TREND"].get("members") or {}


def test_trend_confirmation_follows_the_m1_trend_not_the_cascade():
    member = dict((name, fn) for _, name, fn in sg.MEMBERS)["trend indicator (trend-confirmed)"]
    # the M5-H4 cascade says BUY, the M1 trend says SELL
    buy_reading = _payload("BULLISH", "below", "BUY")
    sell_reading = _payload("BULLISH", "below", "SELL")
    assert member(buy_reading) is None                     # agrees with the cascade only: not counted
    assert member(sell_reading) is not None and member(sell_reading)[0] == -1   # agrees with M1


def test_higher_timeframe_trend_members_are_silent():
    members = dict((name, fn) for _, name, fn in sg.MEMBERS)
    p = _payload("BULLISH", "above", "BUY")
    assert members["trend cascade M5-H4"](p) is None
    assert members["H1 trend"](p) is None
    assert members["price vs EMA200 (trend-confirmed)"](p) == (1, 0.5)     # the M1 member still votes


def test_every_higher_timeframe_consumer_is_gated_in_the_analysis():
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    for marker in ("M1_ONLY: not read (H1 trend)", "M1_ONLY: not read (M15 RSI divergence)",
                   "M1_ONLY: not read (M5-H4 trend cascade)", "M1_ONLY: not read (D1 range)",
                   "M1_ONLY: not read (OU fitted on H1)", "M1_ONLY: not read (GNN reads H1)"):
        assert marker in src, marker
    assert 'get_stochastic_divergence(symbol, "M1" if M1_ONLY else "M15")' in src
    mon = (ROOT / "monitor" / "monitor_core.py").read_text(encoding="utf-8")
    assert "M1_ONLY: M5 re-analysis at close not run" in mon
    assert "M1_ONLY: H1 re-analysis at close not run" in mon


@pytest.mark.skipif(os.environ.get("TRADIFY_LIVE_SNAPSHOT") != "1",
                    reason="set TRADIFY_LIVE_SNAPSHOT=1 with MT5 running")
def test_a_live_analysis_requests_only_m1_bars(monkeypatch):
    import MetaTrader5 as mt5
    monkeypatch.setenv("DECISION_LOG", "0")
    monkeypatch.setenv("SKIPPED_SETUP_RECORDER", "0")
    assert mt5.initialize(timeout=20000)
    seen = []
    for name in ("copy_rates_from_pos", "copy_rates_from", "copy_rates_range"):
        orig = getattr(mt5, name)

        def wrapped(symbol, timeframe, *a, _o=orig, **k):
            seen.append(timeframe)
            return _o(symbol, timeframe, *a, **k)
        monkeypatch.setattr(mt5, name, wrapped)
    from core import asset_analysis as aa
    r = aa.analyze_institutional_signal(symbol="EURUSD", order_type="AUTO", fixed_trade_size_usd=200.0,
                                        risk_per_trade=0.02, leverage=200, timeframe="M1")
    assert r.get("success")
    assert seen and all(tf == mt5.TIMEFRAME_M1 for tf in seen), sorted(set(seen))
