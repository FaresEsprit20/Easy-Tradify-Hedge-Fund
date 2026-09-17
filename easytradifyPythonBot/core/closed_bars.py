# ============================================================
# CLOSED BARS -- a live analysis sees the bars a replay sees
# ============================================================
# FILE: core/closed_bars.py
#
# mt5.copy_rates_from_pos(symbol, tf, 0, n) ends with the bar still FORMING:
# its high, low, close and volume are a partial minute (or hour). A replay
# (core/mt5_shim.py) serves only CLOSED bars. So until 2026-09-15 every
# component -- RSI, MACD, zones, sweeps, the H1 trend, the trend cascade,
# the volume ratio -- was computed live on a half-finished bar and in the
# price-history study on complete ones, and every measurement taken on
# history described numbers the live engine never produced. The live volume
# ratio of a bar ten seconds old read 0.02 and fired the low-volume veto.
#
# Inside `closed_bars_context()` every copy_rates_from_pos call skips the
# forming bar (start position + 1). Ticks are untouched: the current price
# still comes from the live quote. Re-entrant and thread-safe: the patch is
# installed on first entry and removed when the last analysis leaves.
# ============================================================

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict

_lock = threading.Lock()
_depth = 0
_original = None


def _closed_copy_rates_from_pos(symbol, timeframe, start_pos, count):
    return _original(symbol, timeframe, (start_pos or 0) + 1, count)


@contextmanager
def closed_bars_context():
    global _depth, _original
    import MetaTrader5 as mt5

    with _lock:
        if _depth == 0:
            _original = mt5.copy_rates_from_pos
            mt5.copy_rates_from_pos = _closed_copy_rates_from_pos
        _depth += 1
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0 and _original is not None:
                mt5.copy_rates_from_pos = _original
                _original = None


def is_active() -> bool:
    return _depth > 0


def get_status() -> Dict[str, Any]:
    return {"component": "closed_bars", "active_analyses": _depth}
