"""
Market stop: the stop comes from H1 volatility, the lot from the dollar risk.

Pins the arithmetic (ATR of closed H1 bars, lot rounded DOWN so the loss at
the stop never exceeds the budget), the plan served through the replay shim,
and that an instrument the budget cannot afford is reported as such.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from core import market_stop


def _h1(n=20, rng=0.0010, start=1_781_000_000):
    arr = np.zeros(n, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                             ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
    arr["time"] = start + 3600 * np.arange(n)
    arr["open"] = arr["close"] = 1.1000
    arr["high"] = 1.1000 + rng / 2
    arr["low"] = 1.1000 - rng / 2
    return arr


def test_h1_atr_is_the_mean_true_range_of_the_last_14_closed_bars():
    assert market_stop.h1_atr(_h1()) == pytest.approx(0.0010)
    assert market_stop.h1_atr(_h1(n=10)) is None


def test_lot_rounds_down_so_risk_never_exceeds_the_budget():
    # EURUSD: a 15-pip stop loses $150 per lot -> $4 buys 0.026 -> 0.02
    assert market_stop.lot_for_risk(150.0, 4.0, 0.01, 0.01, 100.0) == 0.02
    assert market_stop.lot_for_risk(100.0, 4.0, 0.01, 0.01, 100.0) == 0.04
    # unaffordable: the broker minimum is returned, the caller checks the risk
    assert market_stop.lot_for_risk(2500.0, 4.0, 0.01, 0.01, 100.0) == 0.01


def _market(ask=1.10010, bid=1.10000, tick_value=1.0, tick_size=0.00001, digits=5, name="EURUSD", rng=0.0010):
    info = SimpleNamespace(name=name, digits=digits, point=tick_size, trade_contract_size=100000.0,
                           trade_tick_size=tick_size, trade_tick_value=tick_value,
                           volume_min=0.01, volume_step=0.01, volume_max=100.0)
    h1 = _h1(rng=rng)
    return SimpleNamespace(info=info, account=SimpleNamespace(leverage=200, balance=1000.0),
                           tick=SimpleNamespace(ask=ask, bid=bid, last=ask, time=int(h1["time"][-1]) + 3600),
                           multi_tf_rates={"H1": h1}, rates=None)


def test_plan_sets_stop_target_and_lot_from_h1_volatility():
    from core.mt5_shim import replay_context
    md = _market()
    with replay_context(md):
        p = market_stop.plan("EURUSD", "BUY", 4.0, h1_rates=md.multi_tf_rates["H1"])
    # 4 x the 10-pip H1 ATR: widened 2026-09-16 after measuring the frontier
    expected_stop = 10.0 * market_stop.MARKET_STOP_H1_ATR_MULTIPLE
    assert p["stop_pips"] == pytest.approx(expected_stop)
    # plan() publishes pips rounded to one decimal
    assert p["target_pips"] == pytest.approx(expected_stop * market_stop.MARKET_TARGET_R, abs=0.05)
    assert p["entry"] == pytest.approx(1.10010)                  # a BUY fills at the ask
    assert p["stop_price"] == pytest.approx(1.10010 - expected_stop * 0.0001)
    assert p["risk_usd"] <= 4.0 and p["affordable"]
    # a wider stop means a smaller lot, which is why commission per R falls
    assert p["lot"] <= 0.02


def test_plan_reports_an_unaffordable_stop_instead_of_over_risking():
    from core.mt5_shim import replay_context
    # gold-like: $25 H1 ATR, $1 per 0.01 move per lot -> 0.01 lot risks $37.5
    md = _market(ask=3600.10, bid=3600.00, tick_value=1.0, tick_size=0.01, digits=2, name="XAUUSD", rng=25.0)
    md.info.trade_contract_size = 100.0
    with replay_context(md):
        p = market_stop.plan("XAUUSD", "SELL", 4.0, h1_rates=md.multi_tf_rates["H1"])
    assert p["lot"] == 0.01 and not p["affordable"]


def test_risk_per_trade_is_capped_for_every_caller():
    """api/execution_controller.py passes the request body straight through: a
    live snapshot on 2026-09-16 sized a $20 stop because a caller asked for 10%
    of the $200 budget. The operator trades $4."""
    import inspect
    from core.asset_analysis_config import MAX_RISK_PER_TRADE
    from core import asset_analysis, execution
    assert MAX_RISK_PER_TRADE == 0.02
    assert 200.0 * MAX_RISK_PER_TRADE == 4.0
    for module in (asset_analysis.analyze_institutional_signal, execution.execute_trade):
        src = inspect.getsource(module)
        assert "risk_per_trade = MAX_RISK_PER_TRADE" in src, module.__name__
