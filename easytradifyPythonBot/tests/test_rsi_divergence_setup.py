"""
core/rsi_divergence_setup.py -- the ONE definition of the RSI divergence setup
(2026-09-18). The app's RSI score, the app's RSI setup and the shadow runner all
read it, so these tests pin exactly what was measured:

  classic divergence at +-50-bar M1 swings, RSI < 20 (> 80) at the swing,
  confirmed by a break of structure within 60 bars (cancelled if the stop is
  reached first), stop at the swing -1 pip, no Fibonacci, exit at RSI 80/20 --
  for BUY and its mirror SELL.

Parity with the study (tradify_study/trend_m1_v1/parity_rsi_div_setup.py): at
the measured 30/70 levels, 157 of 158 study trades were reproduced bar by bar;
80/20 (operator, 2026-09-18) uses the same code with the two levels changed.
"""

import pathlib

import numpy as np
import pytest

from core import rsi_divergence_setup as rds

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIP = 0.0001


def test_the_setup_is_the_measured_one():
    assert (rds.PIV, rds.LOOK, rds.RSI_N, rds.BOS_BARS, rds.WAIT) == (50, 1000, 14, 5, 60)
    # 80/20 for entry and exit (operator, 2026-09-18)
    assert (rds.EXTREME, rds.EXIT_BUY, rds.HOLD_BARS) == (20.0, 80.0, 480)


def _series(tail):
    """flat -> hard drop into swing 1 (RSI near 0) -> bounce -> zigzag into a LOWER
    swing 2 with RSI ~18 (below 20, higher than at swing 1) -> 50 rising bars that confirm
    swing 2 -> `tail` (a list of per-bar price changes)."""
    p = [1.1000 + (0.0001 if i % 2 else -0.0001) for i in range(250)]
    for _ in range(50):
        p.append(p[-1] - 0.0004)
    for _ in range(60):
        p.append(p[-1] + 0.0002)
    for k in range(60):
        p.append(p[-1] + (0.0002 if k % 2 else -0.0009))      # RSI ~18 at swing 2
    if len(p) % 2 == 0:
        p.append(p[-1] - 0.0009)
    j = len(p) - 1                                   # swing 2
    for _ in range(rds.PIV):
        p.append(p[-1] + 0.0003)
    for d in tail:
        p.append(p[-1] + d)
    c = np.array(p)
    return c + 0.00005, c - 0.00005, c, j


def _state(tail):
    h, l, c, j = _series(tail)
    return rds.divergence_state(h, l, c, l, h, PIP), j, c


def _mirror_state(tail):
    """The same market upside down: every BUY divergence becomes a SELL one."""
    h, l, c, j = _series(tail)          # flipped below, so a rise becomes a fall
    top = 2.2
    mh, ml, mc = top - l, top - h, top - c
    return rds.divergence_state(mh, ml, mc, ml, mh, PIP), j, mc


def test_waits_for_the_break_of_structure():
    st, j, _ = _state([0.0] * 5)                     # flat: no bar closes above the last 5 highs
    assert st["status"] == "AWAITING_BOS" and st["side"] == 1 and st["swing_index"] == j
    assert st["rsi_at_swing"] < rds.EXTREME


def test_the_break_of_structure_on_the_last_bar_is_the_entry():
    st, j, c = _state([0.0] * 5 + [0.0010])
    assert st["status"] == "CONFIRMED" and st["bos_index"] == c.size - 1
    assert st["stop_price"] == pytest.approx(c[j] - 0.00005 - PIP)     # the swing low - 1 pip
    assert rds.current_setup(*_series([0.0] * 5 + [0.0010])[:3], _series([0.0] * 5 + [0.0010])[1],
                             _series([0.0] * 5 + [0.0010])[0], PIP) is not None


def test_a_break_of_structure_already_past_is_not_a_new_entry():
    st, _, _ = _state([0.0] * 5 + [0.0010, 0.0, 0.0])
    assert st["status"] == "NONE"


def test_reaching_the_stop_first_cancels_it():
    # price falls through the swing, then breaks out: no trade (the confirmation came too late)
    st, _, _ = _state([0.0] * 3 + [-0.0200, 0.0] + [0.0300])
    assert st["status"] == "NONE"


def test_it_expires_after_the_wait():
    st, _, _ = _state([0.0] * (rds.WAIT + 2))
    assert st["status"] == "NONE"


def test_the_rsi_reading_and_the_setup_follow_the_state():
    waiting, _, _ = _state([0.0] * 5)
    r = rds.score_indicator(waiting)
    assert r["recommendation"] == "BUY" and r["confidence"] == 75 and r["score"] > 0
    confirmed, _, c = _state([0.0] * 5 + [0.0010])
    r = rds.score_indicator(confirmed)
    assert r["recommendation"] == "BUY" and r["confidence"] == 95
    assert rds.score_indicator({"status": "NONE"}) is None          # RSI then scored on its own
    s = rds.setup_from_state(confirmed, "AUTO", float(c[-1]), "EURUSD")
    assert s["is_perfect_setup"] is True and s["direction"] == "BUY"
    assert s["take_profit"] is None and s["exit_type"] == "RSI_80_20"   # no Fibonacci
    assert s["stop_loss"] == pytest.approx(confirmed["stop_price"], abs=1e-5)
    assert rds.setup_from_state(confirmed, "SELL", float(c[-1]), "EURUSD")["is_perfect_setup"] is False
    assert rds.setup_from_state(waiting, "AUTO", float(c[-1]), "EURUSD")["is_perfect_setup"] is False


def test_the_sell_is_the_mirror_of_the_buy():
    waiting, _, _ = _mirror_state([0.0] * 5)
    assert waiting["status"] == "AWAITING_BOS" and waiting["side"] == -1
    assert waiting["rsi_at_swing"] > 100 - rds.EXTREME                  # RSI > 80 at the swing high
    confirmed, j, c = _mirror_state([0.0] * 5 + [0.0010])
    assert confirmed["status"] == "CONFIRMED" and confirmed["side"] == -1
    assert confirmed["stop_price"] > c[j]                                # stop ABOVE the swing high
    r = rds.score_indicator(confirmed)
    assert r["recommendation"] == "SELL" and r["score"] < 0 and r["confidence"] == 95
    s = rds.setup_from_state(confirmed, "AUTO", float(c[-1]), "EURUSD")
    assert s["is_perfect_setup"] is True and s["direction"] == "SELL" and s["take_profit"] is None
    assert rds.rsi_exit_hit(-1, 19.9) and not rds.rsi_exit_hit(-1, 20.1)   # a SELL exits at RSI 20
    assert rds.rsi_exit_hit(1, 80.0) and not rds.rsi_exit_hit(1, 79.9)     # a BUY at RSI 80


def test_the_app_reads_the_m1_divergence_everywhere_and_no_fibonacci():
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    # one M1 divergence state, read by the probability chain, the RSI score,
    # the RSI setup, the veto and the record -- the M15 divergence is gone
    assert "rsi_divergence_state = _rds.state_from_rates(" in src
    assert "rsi_indicator = _rds_reading or score_rsi_indicator_with_divergence(" in src
    assert "rsi_reversal_setup = _rds.setup_from_state(rsi_divergence_state" in src
    start = src.index('"rsi_14": round(')                  # the published RSI block
    rsi_block = src[start:src.index('"stochastic": {', start)]
    assert '"timeframe": "M1",' in rsi_block and "M15" not in rsi_block
    assert "get_m15_divergence" not in src
    # Fibonacci is out of the RSI part entirely
    smc = (ROOT / "core" / "asset_analysis_smc.py").read_text(encoding="utf-8")
    assert "evaluate_rsi_reversal_setup" not in src and "def evaluate_rsi_reversal_setup" not in smc
    from core import asset_analysis_config as cfg
    assert not any(n.startswith("RSI_REVERSAL_") for n in dir(cfg))
    # no Fibonacci in the code of the RSI setup (the docstring quotes the decision)
    import ast
    tree = ast.parse((ROOT / "core" / "rsi_divergence_setup.py").read_text(encoding="utf-8"))
    names = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
             | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
             | {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))})
    assert not any("fib" in n.lower() for n in names), [n for n in names if "fib" in n.lower()]


def test_the_shadow_runner_uses_the_same_definition():
    from engine_v2.run import shadow_rsi_div_m1 as sh
    assert sh.current_setup is rds.current_setup and sh.detect is rds.detect
    assert sh.JOURNAL.name == "shadow_rsi_div_m1_v4.jsonl"
    src = pathlib.Path(sh.__file__).read_text(encoding="utf-8")
    assert "hit = current_setup(mid_h, mid_l, mid_c, stop_low, stop_high, pip, not_before=not_before)" in src
