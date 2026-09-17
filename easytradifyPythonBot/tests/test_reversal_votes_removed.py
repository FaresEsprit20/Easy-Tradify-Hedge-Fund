"""
Reversal votes do not move probability or the entry decision.

On the stored trades RSI adaptive (31% right), round numbers (33%) and wave C
(38%) called reversals where M1 continued. Their last route into a trade was
family voting, removed 2026-09-15. These tests fail if any of them is wired
back in.
"""

import ast
import pathlib

from core import asset_analysis_config as cfg

SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")
REVERSAL_NAMES = ("rsi_adaptive", "round_number_result", "wave_c_indicator", "wave_c_reversal_setup")


def test_adaptive_rsi_does_not_replace_rsi():
    assert cfg.USE_ADAPTIVE_OSCILLATOR_BANDS is False


def test_no_probability_step_reads_a_reversal_vote():
    """Nothing assigned to best_probability may be computed from them."""
    tree = ast.parse(SOURCE)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "best_probability" for t in node.targets):
            used = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            offenders += [name for name in REVERSAL_NAMES if name in used]
    assert offenders == []


def test_no_ledger_step_for_them():
    steps = {line.split('"')[1] for line in SOURCE.splitlines()
             if "_ledger_step(probability_ledger, \"" in line}
    assert not steps & {"rsi_adaptive", "round_numbers", "wave_c"}


def test_entry_decision_is_not_given_them():
    start = SOURCE.index("get_entry_decision(")
    call = SOURCE[start:SOURCE.index(")\n", SOURCE.index("is_replay", start))]
    for name in REVERSAL_NAMES:
        assert name not in call
