"""
The shadow runner for the RSI-extreme divergence setup (2026-09-18) is a
confirmation test: it only means something if it trades EXACTLY the setup the
M1 audit measured. These tests pin that.
"""

from pathlib import Path

import numpy as np
import pytest

from engine_v2.run import shadow_rsi_div_m1 as sh


def test_the_setup_is_frozen_as_measured():
    # 2026-09-18: the fixed 1:2 target became the conventional RSI exit (70 / 30)
    assert (sh.PIV, sh.LOOK, sh.RSI_N, sh.EXTREME, sh.EXIT_BUY, sh.HOLD_BARS) == (50, 1000, 14, 30.0, 70.0, 480)
    assert not hasattr(sh, "TARGET_R")
    assert sh.JOURNAL.name == "shadow_rsi_div_m1_v2.jsonl"     # the 1:2 trades do not count
    assert sh.RISK_USD == 4.0
    assert sh.MIN_TRADES_FOR_VERDICT == 300
    assert all(not s.startswith(("XAU", "XAG")) for s in sh.SYMBOLS) and len(sh.SYMBOLS) == 15


def test_the_runner_places_orders_only_through_the_demo_guarded_adapter():
    """The detector/journal module holds no order code of its own; every order
    goes through engine_v2/run/rsi_div_live.py, which refuses non-demo accounts."""
    src = Path(sh.__file__).read_text(encoding="utf-8")
    for forbidden in ("order_send", "execute_trade", "TRADE_ACTION"):
        assert forbidden not in src
    assert "rsi_div_live.place(" in src
    live_src = Path(sh.__file__).with_name("rsi_div_live.py").read_text(encoding="utf-8")
    assert "if not is_demo(mt5):" in live_src


def _series(second_low_step, ratio_up):
    """flat -> hard drop into low 1 (RSI near 0) -> bounce -> zigzag into low 2 -> rise."""
    p = [1.1000 + (0.0001 if i % 2 else -0.0001) for i in range(250)]
    for _ in range(50):
        p.append(p[-1] - 0.0004)                          # low 1 at index 299..300
    for _ in range(60):
        p.append(p[-1] + 0.0002)
    for k in range(60):                                   # zigzag decline into low 2
        p.append(p[-1] + (ratio_up * second_low_step if k % 2 else -second_low_step))
    if len(p) % 2 == 0:
        p.append(p[-1] - second_low_step)
    for _ in range(60):
        p.append(p[-1] + 0.0003)
    c = np.array(p)
    return c, c + 0.00005, c - 0.00005


def _confirmed_at_second_low(c, h, l):
    j = int(np.argmin(l[330:])) + 330                     # the second low
    n = j + sh.PIV + 1
    return sh.detect(h[:n], l[:n], c[:n]), j


def test_a_lower_low_with_a_higher_rsi_under_30_is_a_buy():
    c, h, l = _series(second_low_step=0.0009, ratio_up=1 / 3)
    hit, j = _confirmed_at_second_low(c, h, l)
    assert l[j] < l[250:330].min()                       # price made the lower low
    assert hit is not None and hit[0] == 1 and hit[1] == j
    assert hit[3] < sh.EXTREME


def test_no_regular_divergence_when_the_second_low_is_higher():
    c, h, l = _series(second_low_step=0.0003, ratio_up=1 / 3)   # shallow: second low stays above the first
    hit, j = _confirmed_at_second_low(c, h, l)
    assert l[j] > l[250:330].min()
    assert hit is None


def test_rsi_not_at_the_extreme_is_not_a_setup():
    c, h, l = _series(second_low_step=0.0009, ratio_up=0.8)    # lower low, but RSI ~45 at it
    hit, j = _confirmed_at_second_low(c, h, l)
    assert sh.rsi_wilder(c[:j + sh.PIV + 1])[j] > sh.EXTREME
    assert hit is None


def test_a_pivot_is_only_reported_once_its_window_has_closed():
    c, h, l = _series(second_low_step=0.0009, ratio_up=1 / 3)
    _, j = _confirmed_at_second_low(c, h, l)
    for n in range(j + 1, j + sh.PIV + 1):               # the 50 confirming bars have not all closed
        hit = sh.detect(h[:n], l[:n], c[:n])
        assert hit is None or hit[1] != j


def test_plan_matches_the_study():
    pip = 0.0001
    assert sh.plan(1, 1.1010, 1.1000, pip) == pytest.approx(0.0011)       # stop only: the exit is RSI
    assert sh.plan(1, 1.0995, 1.1000, pip) == pytest.approx(0.0002)       # already through the pivot


def test_resolve_stop_first_then_the_rsi_exit_then_the_cap():
    f, stop = 1.1000, 0.0010
    bar = lambda lo, hi, close=1.1000: (1.1000, hi, lo, close, 1.1001, hi + 0.0001, lo + 0.0001, close + 0.0001)
    # the stop wins even on a bar where RSI would also exit
    r, k = sh.resolve(1, f, stop, [bar(1.0985, 1.1030)], [75.0])
    assert (r, k) == (pytest.approx(-1.0), 1)
    # RSI reaches 70 on the second bar: out at that bar's bid close
    r, k = sh.resolve(1, f, stop, [bar(1.0995, 1.1005), bar(1.0999, 1.1020, close=1.1015)], [55.0, 71.0])
    assert (r, k) == (pytest.approx(1.5), 2)
    # a SELL exits when RSI reaches 30, at the ask close
    r, k = sh.resolve(-1, f, stop, [bar(1.0985, 1.1005, close=1.0986)], [29.0])
    assert k == 1 and r == pytest.approx((1.1000 - 1.0987) / 0.0010)
    # still open, then the 480-bar cap
    assert sh.resolve(1, f, stop, [bar(1.0995, 1.1005)] * 10, [50.0] * 10) is None
    r, k = sh.resolve(1, f, stop, [bar(1.0995, 1.1005)] * sh.HOLD_BARS, [50.0] * sh.HOLD_BARS)
    assert k == sh.HOLD_BARS and r == pytest.approx(0.0)


def test_the_control_closes_on_the_same_bar():
    f, stop = 1.1000, 0.0010
    bar = lambda lo, hi, close=1.1000: (1.1000, hi, lo, close, 1.1001, hi + 0.0001, lo + 0.0001, close + 0.0001)
    bars = [bar(1.0995, 1.1005), bar(1.0999, 1.1008, close=1.1006)]
    # the opposite (SELL) is held exactly as long as the taken BUY: closed at bar 2's ask close
    assert sh.resolve_matched(-1, f, stop, bars, 2) == pytest.approx((1.1000 - 1.1007) / 0.0010)
    # ... and still stopped out if price reaches its stop first
    bars = [bar(1.0995, 1.1005), bar(1.0999, 1.1020, close=1.1015)]
    assert sh.resolve_matched(-1, f, stop, bars, 2) == pytest.approx(-1.0)


def test_pivot_logic_equals_brute_force_on_real_m1_bars():
    p = Path(r"C:/Users/msi/tradify_study/ticks_m1/EURUSD.npz")
    if not p.exists():
        pytest.skip("study data not on this machine")
    z = np.load(p)
    lo = ((z["bid_low"] + z["ask_low"]) / 2)[:4000].astype(float)
    fast = sh.pivot_flags(lo, True)
    slow = np.zeros(lo.size, bool)
    for i in range(sh.PIV, lo.size - sh.PIV):
        slow[i] = lo[i] == lo[i - sh.PIV:i + sh.PIV + 1].min()
    assert np.array_equal(fast, slow)
