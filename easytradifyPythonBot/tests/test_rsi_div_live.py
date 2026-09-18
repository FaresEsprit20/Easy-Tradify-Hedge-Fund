"""
Operator decision, 2026-09-18: the demo bot trades ONLY the frozen RSI-extreme
divergence setup; the generic engine's entries are off. These tests pin the
safety of that: nothing is sent on a real account, the pivot stop is kept and
the lot is sized to $4, orders carry their own magic, and the 240-bar hold is
enforced on real positions.
"""

import pathlib
from types import SimpleNamespace

import pytest

from core import asset_analysis_config as cfg
from engine_v2.run import rsi_div_live as live

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO, REAL = 0, 2


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = DEMO
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1

    def __init__(self, mode=DEMO, positions=(), tick_time=0):
        self.mode, self._positions, self._tick_time = mode, list(positions), tick_time

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode)

    def positions_get(self, symbol=None):
        return tuple(p for p in self._positions if symbol is None or p.symbol == symbol)

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=self._tick_time)


@pytest.fixture
def sent(monkeypatch):
    import core.execution as ex
    calls = []

    def fake_execute_trade(**kw):
        calls.append(kw)
        return {"success": True, "ticket": 777, "price": kw["stop_loss_price"], "volume": 0.05}
    monkeypatch.setattr(ex, "execute_trade", fake_execute_trade)
    return calls


def test_only_the_rsi_divergence_setup_trades():
    assert cfg.GENERIC_ENTRIES_ENABLED is False
    assert cfg.RSI_DIV_M1_LIVE is True
    # operator priority: stop losing -- no order until the setup has proven itself
    assert cfg.RSI_DIV_M1_REQUIRE_CONFIRMED is True
    mon = (ROOT / "monitor" / "monitor_core.py").read_text(encoding="utf-8")
    gate = mon.index("if not _GENERIC_ON:")
    assert gate < mon.index('print(f"💹 EXECUTING: {symbol} {order_type}")')
    assert gate < mon.index("execution_result = execute_trade(")


def test_nothing_is_sent_before_the_setup_is_confirmed(sent):
    for status in ("PENDING (12/300 resolved)", "DIRECTION ONLY (310/300 resolved)", "DEAD (400/300 resolved)"):
        r = live.place(FakeMT5(), "EURUSD", 1, 1.1000, 0.0010, 0.0020, confirmed=False, status=status)
        assert r["placed"] is False and "CONFIRMED" in r["reason"] and status in r["reason"]
    assert sent == []


def test_nothing_is_sent_on_a_real_account(sent):
    r = live.place(FakeMT5(mode=REAL), "EURUSD", 1, 1.1000, 0.0010, 0.0020, confirmed=True)
    assert r["placed"] is False and "not a demo account" in r["reason"]
    assert sent == []


def test_nothing_is_sent_when_switched_off(sent, monkeypatch):
    monkeypatch.setattr(cfg, "RSI_DIV_M1_LIVE", False)
    r = live.place(FakeMT5(), "EURUSD", 1, 1.1000, 0.0010, 0.0020, confirmed=True)
    assert r["placed"] is False and sent == []


@pytest.mark.parametrize("side, sl, order_type", [(1, 1.0990, "BUY"), (-1, 1.1010, "SELL")])
def test_a_demo_order_keeps_the_pivot_stop_and_sizes_to_four_dollars(sent, side, sl, order_type):
    r = live.place(FakeMT5(), "EURUSD", side, 1.1000, 0.0010, None, confirmed=True)
    assert r["placed"] is True and r["ticket"] == 777
    kw = sent[0]
    assert kw["order_type"] == order_type
    assert kw["stop_loss_price"] == pytest.approx(sl)
    assert kw["take_profit_price"] is None                 # the exit is RSI, not a broker TP
    assert kw["keep_stop"] is True                         # the setup's stop, lot shrinks to hold $4
    assert kw["fixed_trade_size_usd"] * kw["risk_per_trade"] == pytest.approx(4.0)
    assert kw["strategy_magic"] == live.MAGIC != 1001     # distinct from the monitor's magic
    assert kw["max_trades_per_symbol"] == 1


def test_the_480_bar_cap_closes_only_this_setups_old_positions(monkeypatch):
    import core.execution as ex
    closed = []
    monkeypatch.setattr(ex, "close_position", lambda ticket, deviation=20: closed.append(ticket) or {"success": True})
    now = 1_800_000_000
    positions = [
        SimpleNamespace(ticket=1, symbol="EURUSD", magic=live.MAGIC, time=now - live.HOLD_SECONDS - 5),   # due
        SimpleNamespace(ticket=2, symbol="EURUSD", magic=live.MAGIC, time=now - 600),                     # young
        SimpleNamespace(ticket=3, symbol="GBPUSD", magic=1001, time=now - 10 * live.HOLD_SECONDS),        # not ours
    ]
    out = live.time_exits(FakeMT5(positions=positions, tick_time=now))
    assert closed == [1]
    assert out[0]["ticket"] == 1 and out[0]["closed"] is True


def test_the_verdict_is_the_pre_registered_one():
    from engine_v2.run import shadow_rsi_div_m1 as sh

    def book(n, net, opp):
        return {str(i): {"net_r": net, "opp_net_r": opp} for i in range(n)}
    assert sh.verdict(book(299, 1.0, -1.0)) == ("PENDING", 299)          # never before 300 trades
    assert sh.verdict(book(300, 0.10, -0.20)) == ("CONFIRMED", 300)      # makes money and beats its mirror
    assert sh.verdict(book(300, -0.05, -0.30))[0] == "DIRECTION ONLY"    # right side, still losing: no trading
    assert sh.verdict(book(300, 0.10, 0.20))[0] == "DEAD"                # makes money only because the market did
    # open (unresolved) shadow trades do not count
    b = book(300, 0.10, -0.20)
    b["open"] = {"symbol": "EURUSD"}
    assert sh.verdict(b) == ("CONFIRMED", 300)


def test_trading_stops_again_if_the_evidence_turns():
    from engine_v2.run import shadow_rsi_div_m1 as sh
    src = pathlib.Path(sh.__file__).read_text(encoding="utf-8")
    # the verdict is recomputed every cycle and passed to every single order
    assert "v, n_resolved = verdict(trades)" in src
    assert 'confirmed=(v == "CONFIRMED")' in src


def test_the_rsi_exit_closes_this_setups_positions_at_70_and_30(monkeypatch):
    import core.execution as ex
    closed = []
    monkeypatch.setattr(ex, "close_position", lambda ticket, deviation=20: closed.append(ticket) or {"success": True})
    positions = [
        SimpleNamespace(ticket=1, symbol="EURUSD", magic=live.MAGIC, type=0, time=0),   # BUY
        SimpleNamespace(ticket=2, symbol="EURUSD", magic=live.MAGIC, type=1, time=0),   # SELL
        SimpleNamespace(ticket=3, symbol="EURUSD", magic=1001, type=0, time=0),         # not ours
    ]
    live.rsi_exits(FakeMT5(positions=positions), "EURUSD", 69.0)
    assert closed == []                     # below 70: no exit
    live.rsi_exits(FakeMT5(positions=positions), "EURUSD", 71.0)
    assert closed == [1]                    # RSI >= 70 closes our BUY only
    closed.clear()
    live.rsi_exits(FakeMT5(positions=positions), "EURUSD", 29.0)
    assert closed == [2]                    # RSI <= 30 closes our SELL only
    closed.clear()
    live.rsi_exits(FakeMT5(positions=positions), "EURUSD", 50.0)
    assert closed == []
