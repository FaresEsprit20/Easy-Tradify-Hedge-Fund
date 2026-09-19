"""
engine_v2/run/rsi_div_h4.py -- RSI divergence on H4, demo orders.
Parity with the study (tradify_study/trend_m1_v1/parity_rsi_div_h4.py): 448 of
448 confirmation bars on 15 pairs of history_v6 H4 bars after warm-up.
"""
import pathlib

import numpy as np
import pytest

from engine_v2.run import rsi_div_h4 as h4

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIP = 0.0001


def test_the_frozen_setup():
    assert (h4.PIV, h4.MAX_GAP, h4.BOS_BARS, h4.WAIT, h4.TARGET_R, h4.HOLD_BARS) == (3, 60, 5, 10, 3.0, 120)
    assert h4.RISK_USD == 4.0 and h4.MIN_TRADES_FOR_VERDICT == 40 and h4.BRAKE_R == -10.0
    assert h4.MAGIC not in (20260918, 1001) and h4.JOURNAL.name == "rsi_div_h4_v1.jsonl"


def _market(confirm_now: bool):
    """two lows 10 bars apart, the second lower with higher RSI, then a rise; the
    last bar closes above the previous 5 highs only if confirm_now."""
    p = [1.20 - 0.002 * k for k in range(20)]            # fall into low 1 (RSI very low)
    p += [p[-1] + 0.0015, p[-1] + 0.0025, p[-1] + 0.003]  # bounce
    p += [p[-1] - 0.001 * k for k in range(1, 8)]         # slower fall into a LOWER low 2
    p += [p[-1] + 0.0004, p[-1] + 0.0005, p[-1] + 0.0006, p[-1] + 0.0006, p[-1] + 0.0006]
    p += [p[-1] + (0.004 if confirm_now else 0.0)]
    c = np.array(p)
    return c + 0.0002, c - 0.0002, c


def test_a_divergence_is_triggered_on_its_confirmation_bar_only():
    h, l, c = _market(True)
    sp = np.full(c.size, 0.00002)
    hits = h4.triggers_on_last_bar(h, l, c, sp, PIP)
    assert hits and hits[0][0] == 1                       # a BUY
    side, i, b, stop_px = hits[0]
    assert stop_px == pytest.approx(l[b] - PIP)
    h2, l2, c2 = _market(False)
    assert h4.triggers_on_last_bar(h2, l2, c2, sp, PIP) == []


def test_the_sell_is_the_mirror():
    h, l, c = _market(True)
    top = 3.0
    sp = np.zeros(c.size)
    hits = h4.triggers_on_last_bar(top - l, top - h, top - c, sp, PIP)
    assert hits and hits[0][0] == -1


def test_a_divergence_known_before_the_last_exit_is_ignored():
    h, l, c = _market(True)
    sp = np.zeros(c.size)
    side, i, b, _ = h4.triggers_on_last_bar(h, l, c, sp, PIP)[0]
    assert h4.triggers_on_last_bar(h, l, c, sp, PIP, not_before_bar=i) == []


def test_verdict_and_brake():
    mk = lambda r, o: {"net_r": r, "opp_net_r": o}
    assert h4.verdict({str(k): mk(0.1, -0.1) for k in range(10)})[0] == "PENDING"
    assert h4.verdict({str(k): mk(0.1, -0.1) for k in range(40)})[0] == "KEEP"
    assert h4.verdict({str(k): mk(-0.05, -0.3) for k in range(40)})[0] == "STOP"
    assert h4.verdict({str(k): mk(-1.0, 0.0) for k in range(10)})[0] == "BRAKE"   # -10R
    assert h4.orders_allowed("PENDING") and h4.orders_allowed("KEEP")
    assert not h4.orders_allowed("STOP") and not h4.orders_allowed("BRAKE")


def test_opposite_control():
    bars = [(1.1000, 1.1010, 1.0990, 1.1005), (1.1005, 1.1030, 1.1000, 1.1025)]
    # the taken trade was a BUY; the control SELLs at 1.1000 with a 20-pip stop
    assert h4.opposite_r(1, 1.1000, 0.0020, bars, [0.0, 0.0]) == pytest.approx(-1.0)   # 1.1030 >= 1.1020
    assert h4.opposite_r(1, 1.1000, 0.0040, bars, [0.0, 0.0]) == pytest.approx(-0.625)


def test_orders_are_guarded():
    src = (ROOT / "engine_v2" / "run" / "rsi_div_h4.py").read_text(encoding="utf-8")
    assert "refused: not a demo account" in src and "keep_stop=True" in src
    assert "max_trades_per_symbol=1" in src
    from core import asset_analysis_config as cfg
    assert cfg.RSI_DIV_H4_LIVE is True
