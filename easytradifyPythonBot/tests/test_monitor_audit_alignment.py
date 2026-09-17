"""
The monitor's stored summaries against the snapshot analyze_institutional_signal()
produces today (real payloads: tests/fixtures/asset_analysis_snapshots_2026_09_17.json).

m1_audit (monitor/trade_persistence._audit_slice) read vwap, ttm_squeeze,
liquidity_events, rvam, trend_analysis and session_analysis at the top level after
core/analysis_groups.reshape() had moved them under analysis.<GROUP>.data, so every
one of those fields was null on every stored trade. analysis_at_close stored a
"📈 RISK_REWARD" key the analysis never publishes, so it was "1:0" on every close.
"""

import json
from pathlib import Path

import pytest

from monitor import trade_persistence as tp

FIXTURE = Path(__file__).parent / "fixtures" / "asset_analysis_snapshots_2026_09_17.json"


def _snapshots():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshots"]


@pytest.fixture(params=sorted(_snapshots()))
def snapshot(request):
    return _snapshots()[request.param]


def test_the_audit_reads_the_grouped_blocks(snapshot):
    audit = tp._audit_slice(snapshot)
    assert audit["schema"] == tp.AUDIT_SCHEMA_VERSION == 2
    for section, field in (("vwap", "zone"), ("vwap", "deviation_sigma"), ("squeeze", "state"),
                           ("liquidity", "bias"), ("liquidity", "event_count"),
                           ("rvam", "classification"), ("regime", "trend"), ("regime", "adx"),
                           ("regime", "session_state"), ("regime", "atr_pips"),
                           ("zone", "type"), ("zone", "grade"), ("strategy", "winner"),
                           ("strategy", "final_probability"), ("direction", "traded"),
                           ("decision", "probability")):
        assert audit[section][field] is not None, f"{section}.{field} is null on a live snapshot"


def test_the_audit_values_are_the_snapshot_values(snapshot):
    audit = tp._audit_slice(snapshot)
    groups = snapshot["analysis"]
    assert audit["vwap"]["zone"] == groups["MOMENTUM"]["data"]["vwap"]["zone"]
    assert audit["rvam"]["classification"] == groups["MOMENTUM"]["data"]["rvam"]["classification"]
    assert audit["regime"]["session_state"] == groups["CONTEXT"]["data"]["session"]["session_close_state"]
    assert audit["regime"]["trend"] == groups["TREND"]["data"]["trend"]["trend"]
    assert audit["strategy"]["winner"] == snapshot["strategy_groups"]["winner"]
    assert set(audit["strategy"]["groups"]) == set(snapshot["strategy_groups"]["groups"])
    assert set(audit["confluence_chain"]) == {
        k.replace("_final_score", "") for k in snapshot["final_verdict"] if k.endswith("_final_score")}


def test_the_audit_carries_no_key_whose_source_was_deleted(snapshot):
    audit = tp._audit_slice(snapshot)
    assert "gates" not in audit and "coherence" not in audit
    assert not {"quality_grade", "position_cost_grades", "position_pct"} & set(audit["zone"])
    assert "aligned" not in audit["liquidity"]


def test_the_confluence_chain_keeps_each_block_whole(snapshot):
    chain = tp._audit_slice(snapshot)["confluence_chain"]
    assert chain["gnn"]["final_score"] == snapshot["final_verdict"]["gnn_final_score"]["final_score"]
    assert "gnn_contribution" in chain["gnn"]


def test_the_close_record_takes_risk_reward_from_the_analysis(monkeypatch, snapshot):
    stored = {}

    def capture(ticket, analysis):
        stored.update(analysis)
        return True

    monkeypatch.setattr("monitor.trade_sink.record_analysis_at_close", capture)
    ok = tp.save_analysis_at_close(1, snapshot["config"]["symbol"], "BUY",
                                   {"m1": snapshot, "profit_usd": -4.0, "result": "LOSS"})
    assert ok
    assert stored["📈 RISK_REWARD"] == snapshot["final_verdict"]["risk_reward_ratio"]


def test_a_close_without_analysis_does_not_invent_a_ratio(monkeypatch):
    stored = {}
    monkeypatch.setattr("monitor.trade_sink.record_analysis_at_close",
                        lambda ticket, analysis: stored.update(analysis) or True)
    assert tp.save_analysis_at_close(1, "EURUSD", "BUY", {"m1": {}, "result": "UNKNOWN"})
    assert stored["📈 RISK_REWARD"] is None
