import numpy as np
import pytest

from engine_v2.market_model.context import Context
from engine_v2.setup import Setup
from engine_v2.sim.outcome import simulate
from tests.test_v2.helpers import m1_bars

SPREAD = 0.0002


def _setup(ctx, side="BUY", order="LIMIT", entry=1.1000, stop=1.0990, t1=1.1010, t2=1.1020, created_idx=0,
           valid_bars=500, thesis=None, time_stop=None):
    t0 = int(ctx.m1.time[created_idx])
    return Setup("SMC", "test", "EURUSD", "M15", side, t0, t0 + valid_bars * 60,
                 {"order_type": order, "price": entry}, {"price": stop, "reason": "t"},
                 [{"price": t1, "share": 0.5}, {"price": t2, "share": 0.5}],
                 management={"breakeven_after_target": 1, "time_stop_bars": time_stop},
                 thesis=thesis or []).validate()


def test_limit_buy_fills_on_ask_and_hits_both_targets():
    # mid rises from 1.1010 down to 1.0995 (fills limit at ask 1.1000), then up to 1.1030
    path = list(np.linspace(1.1010, 1.0995, 20)) + list(np.linspace(1.0995, 1.1030, 60))
    ctx = Context("EURUSD", m1_bars(path, spread=SPREAD))
    o = simulate(_setup(ctx), ctx)
    assert o.status == "FILLED_CLOSED"
    assert o.fill_price == pytest.approx(1.1000)
    assert o.targets_hit == 2 and o.exit_reason == "target2"
    r = 1.1000 - 1.0990
    assert o.gross_r == pytest.approx(0.5 * (1.1010 - 1.1000) / r + 0.5 * (1.1020 - 1.1000) / r, rel=1e-6)
    assert o.net_r == pytest.approx(o.gross_r - o.commission_r)
    assert o.win


def test_stop_first_when_stop_and_target_in_same_bar():
    path = [1.1010] * 5 + [1.1000]
    highs = [1.1011] * 5 + [1.1030]
    lows = [1.1009] * 5 + [1.0980]
    ctx = Context("EURUSD", m1_bars(path + [1.1000] * 5, spread=SPREAD, highs=highs + [1.1001] * 5,
                                    lows=lows + [1.0999] * 5))
    o = simulate(_setup(ctx), ctx)
    assert o.status == "FILLED_CLOSED"
    assert o.exit_reason == "stop" and o.gross_r == pytest.approx(-1.0)


def test_breakeven_after_t1_then_stop_at_entry():
    path = list(np.linspace(1.1010, 1.0995, 10)) + list(np.linspace(1.0995, 1.1015, 20)) + list(np.linspace(1.1015, 1.0970, 30))
    ctx = Context("EURUSD", m1_bars(path, spread=SPREAD))
    o = simulate(_setup(ctx), ctx)
    assert o.targets_hit == 1
    assert o.exit_reason == "breakeven_or_trail_stop"
    assert o.gross_r == pytest.approx(0.5, abs=1e-6)   # 0.5 x 1R, second half closed at entry


def test_expired_when_price_never_reaches_limit():
    ctx = Context("EURUSD", m1_bars(np.linspace(1.1050, 1.1060, 100), spread=SPREAD))
    assert simulate(_setup(ctx, valid_bars=50), ctx).status == "EXPIRED"


def test_sell_stop_order_fills_on_bid_and_exits_on_ask():
    path = list(np.linspace(1.1010, 1.0980, 40))
    ctx = Context("EURUSD", m1_bars(path + [1.0980] * 5, spread=SPREAD))
    s = _setup(ctx, side="SELL", order="STOP", entry=1.1000, stop=1.1010, t1=1.0990, t2=1.0985)
    o = simulate(s, ctx)
    assert o.status == "FILLED_CLOSED" and o.fill_price == pytest.approx(1.1000)
    assert o.targets_hit == 2


def test_time_stop_closes_at_next_open():
    ctx = Context("EURUSD", m1_bars([1.1010] * 3 + [1.0998] + [1.1002] * 200, spread=SPREAD))
    s = _setup(ctx, time_stop=1)          # 1 x M15 bar
    o = simulate(s, ctx)
    assert o.exit_reason == "time_stop"
    assert o.exit_time - o.fill_time == 15 * 60


def test_commission_r_is_lot_independent():
    from engine_v2.data.symbols import facts
    f = facts("EURUSD")
    assert f.commission_r(0.0010) == pytest.approx(7.03 / (0.0010 * f.usd_per_price_unit_per_lot))


def test_swap_is_charged_per_night_triple_on_wednesday():
    from engine_v2.data.symbols import facts
    # start Wednesday 2026-09-16 22:00 broker time; hold across Wednesday night and Thursday night
    start = 1789596000 - 1789596000 % 86400 + 22 * 3600
    n = 60 * 30
    path = [1.1010] * 3 + [1.0998] + [1.1002] * (n - 4)
    ctx = Context("EURUSD", m1_bars(path, start=start, spread=SPREAD))
    s = _setup(ctx, time_stop=110)   # 110 x M15 = 27.5h
    o = simulate(s, ctx)
    f = facts("EURUSD")
    assert o.nights == 4                         # Wednesday night x3 + Thursday night x1
    assert o.swap_r == pytest.approx(4 * f.swap_r_per_night(1, o.risk_distance))
    assert o.net_r == pytest.approx(o.gross_r - o.commission_r + o.swap_r)
