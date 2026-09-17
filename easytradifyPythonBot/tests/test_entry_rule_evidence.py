"""ai/entry_rule_evidence.py: per-rule evidence for the entry rule table."""

import random

import pytest

from ai import entry_rule_evidence as ev

G = "precision|M15x1|1R"
DAY = 86400.0


def _row(i, good_passed, bad_passed, r_own, r_other, probability=True, symbol="EURUSD"):
    return {"symbol": symbol, "ts": 1_780_012_800 + i * 3600.0, "direction": "BUY",
            "rules": {"probability": probability, "good": good_passed, "bad": bad_passed,
                      "timing": None},
            "results": {G: {"BUY": r_own, "SELL": r_other}}}


def _dataset(n=1200, seed=7, flip_bad=True):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        good = rng.random() < 0.5
        bad = rng.random() < 0.5
        late = i >= n // 2
        # "good" genuinely lifts its own side in both halves; "bad" lifts it early and hurts it late
        r = rng.gauss(0.0, 1.0) + (0.4 if good else -0.4)
        if flip_bad:
            r += (0.3 if bad else -0.3) * (-1 if late else 1)
        rows.append(_row(i, good, bad, r, rng.gauss(0.0, 1.0)))
    return rows


def test_cluster_stats_counts_days_not_decisions():
    rows = [_row(i, True, True, 1.0 if i % 2 else -0.5, 0.0) for i in range(48)]   # 2 days of hours
    s = ev.results(rows, G)
    assert s["n"] == 48 and s["clusters"] == 2
    assert s["won"] == 0.5 and s["net_r"] == pytest.approx(0.25)


def test_the_opposite_side_is_read_from_the_other_bracket():
    rows = [_row(i, True, True, 1.0, -1.0) for i in range(10)]
    assert ev.results(rows, G)["net_r"] == 1.0
    assert ev.results(rows, G, opposite=True)["net_r"] == -1.0


def test_not_measurable_and_observed_rules_never_block():
    row = _row(0, False, True, 0.0, 0.0)
    assert ev.blocked_by(row, {"good": ev.BLOCK, "timing": ev.BLOCK}) == ["good"]
    assert ev.blocked_by(row, {"good": ev.OBSERVE}) == []


def test_a_rule_that_helps_in_both_halves_keeps_block_and_a_flipping_rule_does_not():
    rep = ev.report(_dataset(), {"probability": "block", "good": "block", "bad": "block", "timing": "block"},
                    [G], G)
    assert rep["verdict"]["good"]["mode"] == ev.BLOCK
    assert rep["verdict"]["good"]["lift_early"] > 0 and rep["verdict"]["good"]["lift_late"] > 0
    assert rep["verdict"]["bad"]["mode"] == ev.OBSERVE
    assert rep["verdict_modes"]["bad"] == ev.OBSERVE


def test_a_rule_too_rare_to_be_shown_to_help_does_not_block():
    rep = ev.report(_dataset(n=120), {"probability": "block", "good": "block", "bad": "block"}, [G], G)
    assert rep["verdict"]["good"]["mode"] == ev.OBSERVE and rep["verdict"]["good"]["was"] == ev.BLOCK
    assert rep["verdict"]["good"]["why"].startswith("unproven")


def test_rules_are_judged_inside_the_probability_band():
    rows = _dataset()
    for row in rows[::2]:
        row["rules"]["probability"] = False
        row["results"][G]["BUY"] = -5.0 if row["rules"]["good"] else 5.0   # outside the band it inverts
    rep = ev.report(rows, {"probability": "block", "good": "block"}, [G], G)
    assert rep["verdict"]["good"]["mode"] == ev.BLOCK


def test_the_pass_line_needs_every_condition():
    ok = {"n": 300, "won": 0.65, "net_r": 0.20, "t": 2.0}
    assert ev.meets_pass_line(ok)
    for key, bad in (("n", 299), ("won", 0.649), ("net_r", 0.199), ("t", 1.99)):
        assert not ev.meets_pass_line({**ok, key: bad})


def test_the_markdown_names_every_rule():
    rep = ev.report(_dataset(), {"probability": "block", "good": "block", "bad": "block"}, [G], G)
    md = ev.to_markdown(rep, "test")
    for name in ("probability", "good", "bad"):
        assert f"| {name} |" in md


# ---------------------------------------------------------------------------
# the live decision log
# ---------------------------------------------------------------------------

def _decision_doc(key="EURUSD|m|AUTO", direction="SELL", with_rules=True):
    from datetime import datetime, timezone
    snapshot = {"ea_es": "WAITING_DISCOUNT"}
    if with_rules:
        snapshot.update({"ea_r_zn_p": True, "ea_r_pr_p": True, "ea_r_ds_p": False, "ea_r_tm_p": None})
    return {"key": key, "symbol": "EURUSD", "direction": direction,
            "decided_at": datetime(2026, 9, 18, 9, 30),            # naive UTC, as MongoDB returns it
            "snapshot": snapshot, "engine": {"fingerprint": "abc"}}


def _outcome_doc(key="EURUSD|m|AUTO", status="ok"):
    return {"decision_key": key, "status": status,
            "engine": {"result": {"how": "STOP", "r_gross": -1.0, "r_net": -1.6}},
            "grid": {"precision|M15x1|1R|BUY": {"r_net": 0.9}, "precision|M15x1|1R|SELL": {"r_net": -1.1},
                     "scalp|M5x1|1R|SELL": {"r_net": None}}}


def test_a_live_decision_becomes_a_row_with_its_rules_and_both_sides():
    row = ev.row_from_decision(_decision_doc(), _outcome_doc())
    assert row["rules"] == {"zone": True, "probability": True, "discount": False, "timing": None}
    assert row["results"]["precision|M15x1|1R"] == {"BUY": 0.9, "SELL": -1.1}
    assert row["results"]["engine"] == {"SELL": -1.6}
    assert "scalp|M5x1|1R" not in row["results"]
    assert row["ts"] == 1789723800.0 and row["engine"] == "abc"


def test_unusable_live_decisions_are_skipped():
    assert ev.row_from_decision(_decision_doc(), _outcome_doc(status="no_ticks")) is None
    assert ev.row_from_decision(_decision_doc(), None) is None
    assert ev.row_from_decision(_decision_doc(with_rules=False), _outcome_doc()) is None   # before the rule table
    assert ev.row_from_decision(_decision_doc(direction="NEUTRAL"), _outcome_doc()) is None
