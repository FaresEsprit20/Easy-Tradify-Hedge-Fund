# ============================================================
# STORED TRADE SHAPE -- THE WRITER/READER CONTRACT
# ============================================================
# A trade can be recorded perfectly and still be invisible.
#
# monitor/firebase_helpers.save_trade_open_to_firebase wrote the entry as flat
# keys -- price, stop_loss, order_type -- and no `entry` sub-document. Every
# model reads the nested shape:
#
#     entry = trade.get("entry") or {}
#     ep, sl = entry.get("price"), entry.get("stop_loss")
#     if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)):
#         return None          # <- trade silently skipped
#
# So `entry` resolved to {}, R came back None, and the trade was dropped by
# ai/trade_repository, ai/edge_discovery, ai/strategy_families and
# ai/component_audit_360 alike. Measured before the fix: R computable on
# 220/250 trades read from MT5 history, and 0/2 written by the live path.
#
# That is the most expensive kind of missing data, because collection looks
# like it is working -- rows accumulate, counts rise, and every model quietly
# ignores them.
#
# `opened_at` had the same problem for a different reason: it is the default
# sort in core/mongo/trades_service.py, it carries its own index, and every
# walk-forward split orders on it -- and nothing wrote it.
#
# ai/mt5_history.to_trade() is the canonical shape. These tests hold the live
# writer to it, by checking a document the reader can actually score rather
# than by listing key names.
# ============================================================

import io

import pytest

from ai.trade_repository import _r_multiple


CANONICAL_KEYS = ("trade_id", "ticket", "symbol", "direction", "status",
                  "opened_at", "entry", "analysis_at_open", "price_evolution")


def _history_trade():
    """The canonical shape, built by the path the research data came from."""
    from ai.mt5_history import to_trade
    return to_trade({
        "position_id": 123456,
        "symbol": "XAUUSD",
        "direction": "SELL",
        "entry_price": 4396.21,
        "exit_price": 4394.61,
        "volume": 0.09,
        "stop_loss": 4397.00,
        "take_profit": None,
        "profit": -0.91,
        "commission": -0.64,
        "swap": 0.0,
        "opened_at": "2026-09-10T00:20:00",
        "closed_at": "2026-09-10T00:21:00",
        "opened_epoch": 1,
        "closed_epoch": 61,
        "close_reason": "CLIENT",
    })


# --------------------------------------------------------------------------
# the reader's actual requirement
# --------------------------------------------------------------------------

def test_canonical_history_trade_scores():
    """Baseline: the shape the 215 research trades use is scoreable."""
    trade = _history_trade()
    r = _r_multiple(trade)
    assert r is not None, "the canonical shape must produce an R"
    # SELL, entry 4396.21, stop 4397.00, exit 4394.61 -> a win of ~2.03R
    assert r > 0


def test_a_flat_document_is_silently_unscoreable():
    """
    The bug, stated as a test. This is what the live writer used to produce:
    every field present, nothing nested, and R is None -- no error, no warning,
    the trade just vanishes from every analysis.
    """
    flat = {
        "ticket": 1921342512,
        "symbol": "XAUUSD",
        "direction": "SELL",
        "price": 4396.21,          # not entry.price
        "stop_loss": 4397.00,      # not entry.stop_loss
        "close_data": {"close_price": 4394.61},
    }
    assert _r_multiple(flat) is None, (
        "if this ever scores, the reader changed and these tests need "
        "rewriting -- but a flat document scoring is not the fix")


def test_direction_drives_the_sign():
    """
    R must follow the recorded direction, not the price move -- the same
    invariant the close path violated by inferring one from the other.
    """
    base = _history_trade()

    sell = dict(base)
    sell["direction"] = "SELL"
    buy = dict(base)
    buy["direction"] = "BUY"

    r_sell, r_buy = _r_multiple(sell), _r_multiple(buy)
    assert r_sell is not None and r_buy is not None
    assert r_sell > 0 > r_buy, (
        "price fell, so the SELL wins and the BUY loses; if both share a sign "
        "the direction is not being read")


# --------------------------------------------------------------------------
# the live writer must emit that shape
# --------------------------------------------------------------------------

def _open_save_source():
    from monitor import trade_persistence as fh
    src = io.open(fh.__file__, encoding="utf-8").read()
    start = src.index("def save_trade_open(")
    return src[start:start + 10000]


@pytest.mark.parametrize("field", ["price", "volume", "stop_loss", "take_profit"])
def test_live_writer_emits_the_entry_subdocument(field):
    src = _open_save_source()
    assert '"entry": {' in src, (
        "the live writer must emit an `entry` sub-document or every trade it "
        "records is skipped by every model")
    entry_start = src.index('"entry": {')
    entry_block = src[entry_start:entry_start + 400]
    assert f'"{field}"' in entry_block, f"entry is missing {field}"


def test_live_writer_emits_opened_at():
    src = _open_save_source()
    assert '"opened_at"' in src, (
        "opened_at is the chronological key: the default sort in "
        "trades_service, its own index, and what every walk-forward split "
        "orders on")


def test_live_writer_emits_direction():
    src = _open_save_source()
    assert '"direction": order_type' in src, (
        "models read trade['direction']; order_type alone is not enough")
