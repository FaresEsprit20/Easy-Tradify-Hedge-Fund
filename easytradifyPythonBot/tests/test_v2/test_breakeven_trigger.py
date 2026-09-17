import numpy as np
import pytest

from engine_v2.market_model.context import Context
from engine_v2.setup import Setup
from engine_v2.sim.outcome import simulate
from tests.test_v2.helpers import m1_bars


def _setup(ctx, be_r):
    t0 = int(ctx.m1.time[0])
    return Setup("SMC", "test", "EURUSD", "M15", "BUY", t0, t0 + 500 * 60,
                 {"order_type": "LIMIT", "price": 1.1000}, {"price": 1.0990},
                 [{"price": 1.1020, "share": 0.5}, {"price": 1.1030, "share": 0.5}],
                 management={"breakeven_after_target": 1, "breakeven_at_r": be_r}).validate()


def _path():
    # fill at 1.1000, rally to about +0.7R on the bid (1.1008), then collapse through the original stop
    return list(np.linspace(1.1010, 1.0998, 10)) + list(np.linspace(1.0998, 1.1008, 10)) + list(np.linspace(1.1008, 1.0970, 30))


def test_without_trigger_the_trade_loses_1r():
    ctx = Context("EURUSD", m1_bars(_path(), spread=0.0002))
    assert simulate(_setup(ctx, None), ctx).gross_r == pytest.approx(-1.0)


def test_breakeven_trigger_at_half_r_turns_it_into_a_scratch():
    ctx = Context("EURUSD", m1_bars(_path(), spread=0.0002))
    o = simulate(_setup(ctx, 0.5), ctx)
    assert o.exit_reason == "stop"
    assert o.gross_r == pytest.approx(0.0, abs=1e-9)
