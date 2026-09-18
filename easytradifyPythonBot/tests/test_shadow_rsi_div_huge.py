"""
engine_v2/run/shadow_rsi_div_huge.py -- shadow-only watch of the +-1600 M1 swing
RSI divergence (the one DEV pass of rsi_div_huge_swings.py, not confirmed).
Parity with the study: tradify_study/trend_m1_v1/parity_rsi_div_huge.py found
the same 41 of 41 signals on EURUSD, GBPUSD, USDJPY, AUDCAD.
"""
import pathlib

import numpy as np
import pytest

from engine_v2.run import shadow_rsi_div_huge as sh

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_frozen_setup():
    assert (sh.PIV, sh.MAX_GAP, sh.HOLD_BARS, sh.EXIT_BUY) == (1600, 32000, 4320, 70.0)
    assert sh.RISK_USD == 4.0 and sh.MIN_TRADES_FOR_VERDICT == 300
    assert sh.JOURNAL.name == "shadow_rsi_div_huge_v1.jsonl"


def test_it_never_places_orders():
    src = (ROOT / "engine_v2" / "run" / "shadow_rsi_div_huge.py").read_text(encoding="utf-8")
    for forbidden in ("order_send", "execute_trade", "rsi_div_live", "place("):
        assert forbidden not in src, forbidden


def _two_lows(second_rsi_higher: bool):
    """Two lows 3000 bars apart, the second lower; RSI at it higher or lower."""
    n = sh.PIV * 2 + 3000 + 1
    x = np.full(n, 1.2)
    a, b = sh.PIV, sh.PIV + 3000
    x[a], x[b] = 1.1, 1.0
    h, l = x + 0.0005, x.copy()
    r = np.full(n, 50.0)
    r[a], r[b] = 20.0, (35.0 if second_rsi_higher else 10.0)
    return h, l, r, a, b


def test_a_lower_low_with_higher_rsi_is_a_buy_on_the_bar_it_becomes_known():
    h, l, r, a, b = _two_lows(True)
    assert b == h.size - 1 - sh.PIV
    assert sh.signal_on_last_bar(h, l, r) == (1, b, a)
    assert sh.signal_on_last_bar(h[:-1], l[:-1], r[:-1]) is None      # not known one bar earlier


def test_no_divergence_when_rsi_confirms_the_low():
    h, l, r, _, _ = _two_lows(False)
    assert sh.signal_on_last_bar(h, l, r) is None


def test_the_sell_is_the_mirror():
    h, l, r, a, b = _two_lows(True)
    top = 3.0
    assert sh.signal_on_last_bar(top - l, top - h, 100 - r) == (-1, b, a)


def test_nights_count_the_wednesday_triple_and_skip_weekends():
    wed_noon = 1789560000                  # 2026-09-16 12:00 UTC, a Wednesday
    assert sh.nights(wed_noon, wed_noon + 3600) == 0
    assert sh.nights(wed_noon, wed_noon + 12 * 3600) == 3           # Wednesday 21:00
    assert sh.nights(wed_noon + 24 * 3600, wed_noon + 5 * 86400) == 2   # Thu + Fri, not Sat/Sun


def test_resolve_stop_first_then_rsi_exit():
    fill, stop = 1.1000, 0.0020
    bar = lambda lo, hi, close=None: (fill, hi, lo, close or fill, fill + 1e-5, hi + 1e-5, lo + 1e-5, (close or fill) + 1e-5)
    r, k = sh.resolve(1, fill, stop, [bar(1.0975, 1.1030)], [80.0])
    assert r == pytest.approx(-1.0) and k == 1                      # touching both: the stop
    r, k = sh.resolve(1, fill, stop, [bar(1.0990, 1.1010), bar(1.0995, 1.1030, 1.1020)], [60.0, 71.0])
    assert r == pytest.approx(1.0) and k == 2
    assert sh.resolve(1, fill, stop, [bar(1.0990, 1.1010)], [60.0]) is None
