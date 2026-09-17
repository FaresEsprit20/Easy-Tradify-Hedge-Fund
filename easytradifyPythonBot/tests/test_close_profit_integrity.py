# ============================================================
# CLOSE PROFIT INTEGRITY -- REGRESSION TESTS
# ============================================================
# A gold SELL (ticket 1921310773) closed at 4391.10 for +$4.77. It was stored
# as closing at 4392.07 for -$3960.00, is_winning=False. Both numbers were
# manufactured, by two separate defects in the close reconstruction:
#
#   1. INVENTED EXIT. When the trade-history lookup missed -- which it
#      routinely does in the moment right after a close -- the code fell back
#      to `price_close = sl`, i.e. it assumed every trade closed at its stop.
#      That is simply false for a manual or webhook close. 4392.07 was the
#      stop, not the exit.
#
#   2. FX CONTRACT SIZE ON EVERYTHING.
#          profit = (price_open - price_close) * volume * 100000
#      100000 is the FX convention. XAUUSD's contract is 100 ounces, so this
#      is 1000x wrong on gold:
#          (4391.63 - 4392.07) * 0.09 * 100000 = -3960
#      against a true -0.44 * 0.09 * 100 = -3.96 for that (wrong) exit, and
#      +4.77 for the real one.
#
# Profit is the LABEL for every model in ai/. A fabricated label is worse than
# a missing row: nothing downstream can tell it apart from a real one. So the
# close is now taken from the broker's own deal record, and when the broker
# has no answer the trade is left unsaved rather than guessed at.
# ============================================================

import io

import pytest

from api import execute_copy_trade as ect


# --------------------------------------------------------------------------
# contract size
# --------------------------------------------------------------------------

class _Info:
    def __init__(self, size):
        self.trade_contract_size = size


def test_contract_size_comes_from_the_broker(monkeypatch):
    monkeypatch.setattr(ect.mt5, "symbol_info", lambda s: _Info(100.0))
    assert ect._contract_size("XAUUSD") == 100.0

    monkeypatch.setattr(ect.mt5, "symbol_info", lambda s: _Info(100000.0))
    assert ect._contract_size("EURUSD") == 100000.0


@pytest.mark.parametrize("info", [None, _Info(None), _Info(0)])
def test_contract_size_is_none_when_unknown(monkeypatch, info):
    """
    None, not a 100000 default. The caller skips the profit calculation on
    None; a default would reinstate the exact 1000x error on gold.
    """
    monkeypatch.setattr(ect.mt5, "symbol_info", lambda s: info)
    assert ect._contract_size("XAUUSD") is None


def test_contract_size_survives_a_broken_mt5(monkeypatch):
    def boom(_):
        raise RuntimeError("terminal not connected")

    monkeypatch.setattr(ect.mt5, "symbol_info", boom)
    assert ect._contract_size("XAUUSD") is None


# --------------------------------------------------------------------------
# the broker's closing deal
# --------------------------------------------------------------------------

class _Deal:
    def __init__(self, entry, price, volume, profit, swap=0.0, commission=0.0):
        self.entry = entry
        self.price = price
        self.volume = volume
        self.profit = profit
        self.swap = swap
        self.commission = commission


IN = 0
OUT = 1


def test_closing_deal_reads_the_real_exit_and_profit(monkeypatch):
    """The case that was stored wrong: gold SELL, +$4.77 at 4391.10."""
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT_BY", 3, raising=False)
    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: [
        _Deal(IN, 4391.63, 0.09, 0.0),
        _Deal(OUT, 4391.10, 0.09, 4.77),
    ])

    deal = ect._closing_deal(1921310773)
    assert deal["price_close"] == pytest.approx(4391.10)
    assert deal["profit"] == pytest.approx(4.77)
    assert deal["volume"] == pytest.approx(0.09)


def test_closing_deal_includes_swap_and_commission(monkeypatch):
    """Realised P/L is what hit the account, not the raw price difference."""
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: [
        _Deal(OUT, 1.16334, 0.34, 10.00, swap=-0.50, commission=-1.25),
    ])
    assert ect._closing_deal(1)["profit"] == pytest.approx(8.25)


def test_closing_deal_counts_the_entry_commission_too(monkeypatch):
    """
    The real gold SELL, ticket 1921339470, exactly as the broker recorded it:
    commission is charged on BOTH legs. Counting only the exit reported -3.02
    against a true -3.34, so a tenth of the loss went missing -- and on small
    positions the round-trip cost is a large share of the result.
    """
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: [
        _Deal(IN, 4396.21, 0.09, 0.0, commission=-0.32),
        _Deal(OUT, 4396.51, 0.09, -2.70, commission=-0.32),
    ])

    deal = ect._closing_deal(1921339470)
    assert deal["profit"] == pytest.approx(-3.34)
    # Price and volume still come from the closing leg only.
    assert deal["price_close"] == pytest.approx(4396.51)
    assert deal["volume"] == pytest.approx(0.09)


def test_closing_deal_volume_weights_partial_closes(monkeypatch):
    """
    A position closed in parts has one honest average exit, not whichever
    fill happened to be last.
    """
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: [
        _Deal(OUT, 100.0, 0.75, 30.0),
        _Deal(OUT, 200.0, 0.25, 10.0),
    ])
    deal = ect._closing_deal(1)
    assert deal["price_close"] == pytest.approx(125.0)   # not 150 (unweighted)
    assert deal["profit"] == pytest.approx(40.0)
    assert deal["volume"] == pytest.approx(1.0)


def test_closing_deal_returns_none_when_broker_has_no_answer(monkeypatch):
    """
    None is the whole point. The caller must leave the trade unsaved rather
    than invent an exit -- see the guard test below.
    """
    monkeypatch.setattr(ect, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: [])
    assert ect._closing_deal(1, retries=2, delay=0) is None

    monkeypatch.setattr(ect.mt5, "history_deals_get", lambda **kw: None)
    assert ect._closing_deal(1, retries=2, delay=0) is None


def test_closing_deal_ignores_entry_only_deals(monkeypatch):
    """An open with no close yet is not a close."""
    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    monkeypatch.setattr(ect.mt5, "history_deals_get",
                        lambda **kw: [_Deal(IN, 4391.63, 0.09, 0.0)])
    assert ect._closing_deal(1, retries=2, delay=0) is None


def test_closing_deal_retries_before_giving_up(monkeypatch):
    """
    The deal is not always in the terminal's history the instant the position
    leaves the open list. That race is what sent the old code to its fallback.
    """
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return []
        return [_Deal(OUT, 4391.10, 0.09, 4.77)]

    monkeypatch.setattr(ect.mt5, "DEAL_ENTRY_OUT", OUT, raising=False)
    monkeypatch.setattr(ect.mt5, "history_deals_get", flaky)

    deal = ect._closing_deal(1, retries=4, delay=0)
    assert deal is not None and deal["profit"] == pytest.approx(4.77)
    assert calls["n"] == 3


# --------------------------------------------------------------------------
# source guards -- both defects are easy to reintroduce and invisible in data
# --------------------------------------------------------------------------

def _close_block():
    src = io.open(ect.__file__, encoding="utf-8").read()
    start = src.index("SL/TP HIT detected")
    return src[start:start + 9000]


def test_the_stop_loss_is_never_used_as_the_exit_price():
    block = _close_block()
    assert "price_close = sl" not in block, (
        "the exit price is being taken from the stop loss again -- that "
        "assumes every trade closed at its stop, which is false for manual "
        "and webhook closes")
    assert "price_close = tp" not in block, (
        "same defect via the take profit")


def test_no_hardcoded_fx_contract_size():
    block = _close_block()
    assert "* 100000" not in block, (
        "the FX contract size is hardcoded again -- this is 1000x wrong on "
        "XAUUSD and turned +$4.77 into -$3960")
    assert "_contract_size(" in block, "profit must use the broker's contract size"


def test_close_is_sourced_from_the_broker_deal():
    assert "_closing_deal(" in _close_block(), (
        "the close must come from the broker's deal record, which already "
        "accounts for swap, commission and partial fills")
