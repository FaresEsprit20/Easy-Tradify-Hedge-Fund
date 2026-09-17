"""
strategic_plan_v5_live_data.md, phases 0-2: engine stamp, decision log, results,
reconciliation and the job loop. No MT5 and no MongoDB: fakes stand in for both,
and the snapshots are the real payloads captured on 2026-09-17.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ai import data_jobs, data_reconciliation, decision_outcomes
from ai.price_evolution_decoder import PriceEvolutionDecoder
from core import decision_log, engine_version

FIXTURE = Path(__file__).parent / "fixtures" / "asset_analysis_snapshots_2026_09_17.json"


def _snapshot():
    snaps = json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshots"]
    return next(v for k, v in snaps.items() if k.startswith("original_"))


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def update_one(self, flt, update, upsert=False):
        self.updates.append((flt, update, upsert))

    def find(self, flt=None, projection=None, sort=None):
        return FakeCursor(self.docs)


class FakeCursor(list):
    def limit(self, n):
        return self


# ---------------------------------------------------------------------------
# engine stamp
# ---------------------------------------------------------------------------

def test_the_engine_stamp_names_code_config_and_commit():
    engine_version.reset_for_tests()
    stamp = engine_version.engine_stamp()
    assert set(stamp) >= {"git_commit", "code_hash", "config", "fingerprint"}
    assert stamp["config"]["use_market_stop"] is False
    assert engine_version.engine_stamp() is stamp          # computed once per process
    assert engine_version.short_stamp() == {"fingerprint": stamp["fingerprint"],
                                            "git_commit": stamp["git_commit"]}


def test_a_config_change_changes_the_fingerprint(monkeypatch):
    engine_version.reset_for_tests()
    before = engine_version.engine_stamp()["fingerprint"]
    real = engine_version._config
    monkeypatch.setattr(engine_version, "_config", lambda: {**real(), "use_market_stop": True})
    engine_version.reset_for_tests()
    assert engine_version.engine_stamp()["fingerprint"] != before
    engine_version.reset_for_tests()


# ---------------------------------------------------------------------------
# decision log
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_log(monkeypatch):
    monkeypatch.setenv("DECISION_LOG", "1")
    decision_log._stored.clear()
    decision_log._stored_minute = None
    decision_log._order_flow_taken.clear()
    monkeypatch.setattr(decision_log, "_order_flow",
                        lambda symbol, minute: {"available": False, "reason": "test"})
    yield
    decision_log._stored.clear()
    decision_log._stored_minute = None


@pytest.mark.parametrize("symbol,expected", [
    ("EURUSD", True), ("XAUUSD", True), ("US500", True), ("XTIUSD", True),
    ("CSCO.NAS", False), ("META.NAS-24", False), ("BTCUSD", False), ("", False)])
def test_only_target_markets_are_logged(symbol, expected):
    assert decision_log.is_target_market(symbol) is expected


def test_the_record_carries_the_whole_snapshot(clean_log):
    snap = _snapshot()
    now = datetime(2026, 9, 17, 5, 30, 12, tzinfo=timezone.utc)
    doc = decision_log.build_record(snap, "GBPJPY", now=now)
    assert doc["key"] == "GBPJPY|2026-09-17T05:30:00+00:00|AUTO"
    assert doc["decided_at"] == now
    assert doc["snapshot_ok"] is True
    assert PriceEvolutionDecoder().decode(doc["snapshot"]) == snap
    assert doc["engine"]["fingerprint"]
    assert doc["direction"] in ("BUY", "SELL")


def test_one_snapshot_per_minute_replaced_only_by_an_entry(clean_log):
    snap = _snapshot()
    col = FakeCollection()
    t0 = datetime(2026, 9, 17, 5, 30, 5, tzinfo=timezone.utc)

    assert decision_log.record(snap, symbol="GBPJPY", is_replay=False, collection=col, now=t0)
    first = col.updates[-1][1]
    assert "snapshot" in first["$set"] and "order_flow" in first["$set"]

    assert decision_log.record(snap, symbol="GBPJPY", is_replay=False, collection=col,
                               now=t0 + timedelta(seconds=20))
    light = col.updates[-1][1]
    assert "snapshot" not in light.get("$set", {}) and light["$inc"] == {"seen_count": 1}

    entering = json.loads(json.dumps(snap))
    entering["entry_analysis"]["should_enter"] = True
    assert decision_log.record(entering, symbol="GBPJPY", is_replay=False, collection=col,
                               now=t0 + timedelta(seconds=40))
    replaced = col.updates[-1][1]
    assert replaced["$set"]["entered"] is True and "snapshot" in replaced["$set"]

    assert decision_log.record(snap, symbol="GBPJPY", is_replay=False, collection=col,
                               now=t0 + timedelta(seconds=70))
    assert "snapshot" in col.updates[-1][1]["$set"], "a new minute stores a new snapshot"


def test_replays_other_markets_and_failures_are_not_logged(clean_log):
    col = FakeCollection()
    snap = _snapshot()
    assert decision_log.record(snap, symbol="GBPJPY", is_replay=True, collection=col) is False
    assert decision_log.record(snap, symbol="CSCO.NAS", is_replay=False, collection=col) is False
    assert decision_log.record({"success": False, "error": "x"}, symbol="GBPJPY",
                               is_replay=False, collection=col) is False
    assert decision_log.record("garbage", symbol="GBPJPY", is_replay=False, collection=col) is False
    assert col.updates == []


# ---------------------------------------------------------------------------
# results on ticks
# ---------------------------------------------------------------------------

def _ticks(mids, spread=0.0002, start=1_000.0, step=1.0):
    mids = np.asarray(mids, float)
    t = start + step * np.arange(mids.size)
    return t, mids - spread / 2, mids + spread / 2


def test_a_buy_that_reaches_its_target_wins_target_r_minus_commission():
    t, bid, ask = _ticks([1.1000, 1.1005, 1.1010, 1.1022, 1.1030])
    res = decision_outcomes.walk(t, bid, ask, 0, "BUY", 0.0010, 0.0020, 3600, commission_r=0.1)
    assert res["how"] == "TARGET" and res["r_gross"] == 2.0 and res["r_net"] == 1.9


def test_a_gap_through_the_stop_fills_worse_than_the_stop():
    t, bid, ask = _ticks([1.1000, 1.0998, 1.0980])
    res = decision_outcomes.walk(t, bid, ask, 0, "BUY", 0.0010, 0.0010, 3600, commission_r=None)
    assert res["how"] == "STOP" and res["r_gross"] < -1.0 and res["r_net"] is None


def test_a_sell_stop_is_hit_on_the_ask():
    t, bid, ask = _ticks([1.1000, 1.1004, 1.1012])
    res = decision_outcomes.walk(t, bid, ask, 0, "SELL", 0.0010, 0.0010, 3600, commission_r=0.0)
    assert res["how"] == "STOP" and res["r_gross"] <= -1.0


def test_no_barrier_within_the_hold_exits_on_the_last_quote():
    t, bid, ask = _ticks([1.1000, 1.1001, 1.1002], step=10.0)
    res = decision_outcomes.walk(t, bid, ask, 0, "BUY", 0.0050, 0.0050, 15, commission_r=0.0)
    assert res["how"] == "TIMEOUT"
    assert res["r_gross"] == pytest.approx((bid[1] - ask[0]) / 0.0050, abs=1e-4)


def test_entry_is_the_first_quote_after_the_decision():
    t, bid, ask = _ticks([1.2000, 1.1000, 1.1010, 1.1020, 1.1030], start=100.0)
    decision = {"key": "k", "symbol": "EURUSD", "direction": "BUY",
                "decided_at": datetime.fromtimestamp(100.5, tz=timezone.utc),
                "stop_loss_pips": 10.0, "take_profit_pips": 20.0}
    out = decision_outcomes.evaluate(decision, t, bid, ask, pip=0.0001,
                                     atrs={"M1": 0.0005, "M5": 0.0010, "M15": 0.0020, "H1": 0.0040})
    assert out["status"] == "ok"
    assert out["entry_ask"] == pytest.approx(ask[1])          # the 1.2000 quote is before the decision
    assert out["engine"]["result"]["how"] == "TARGET"
    assert {"scalp|M1x1|1R|BUY", "scalp|M1x1|1R|SELL", "precision|H1x1|2R|SELL"} <= set(out["grid"])
    assert out["path"]["unit"] == "engine_stop" and out["path"]["mfe_5"] > 0


def test_a_decision_without_a_quote_after_it_is_not_scored():
    t, bid, ask = _ticks([1.1, 1.1], start=100.0)
    decision = {"key": "k", "direction": "BUY", "decided_at": datetime.fromtimestamp(500, tz=timezone.utc)}
    assert decision_outcomes.evaluate(decision, t, bid, ask, pip=0.0001, atrs={})["status"] == \
        "no_quote_after_decision"


def test_atr_is_the_mean_true_range_of_closed_bars():
    high = np.array([2.0] * 16)
    low = np.array([1.0] * 16)
    close = np.array([1.5] * 16)
    assert decision_outcomes.atr(high, low, close) == pytest.approx(1.0)
    assert decision_outcomes.atr(high[:5], low[:5], close[:5]) is None


# ---------------------------------------------------------------------------
# reconciliation and the job loop
# ---------------------------------------------------------------------------

def test_reconciliation_grades_every_closed_position(tmp_path, monkeypatch):
    monkeypatch.setattr(data_reconciliation, "REPORT_DIR", tmp_path)
    positions = [{"position_id": t, "profit": p, "commission": -0.3, "swap": 0.0}
                 for t, p in ((1, 5.0), (2, -4.0), (3, -4.0), (4, 5.0))]
    trades = FakeCollection([
        {"ticket": 1, "status": "CLOSED", "engine": {"fingerprint": "f"}, "price_evolution_count": 12,
         "analysis_at_open": {"m1_analysis_raw": {"success": True}}},
        {"ticket": 2, "status": "OPEN"},
        {"ticket": 3, "status": "CLOSED", "price_evolution_count": 3,
         "analysis_at_open": {"m1_analysis_raw": {"success": True}}},
    ])
    report = data_reconciliation.reconcile(positions=positions, trades=trades)
    assert report["counts"] == {"ok": 1, "not_closed": 1, "no_engine": 1, "missing": 1}
    assert report["tickets"]["missing"] == [4]
    assert report["mt5_won"] == 2 and report["complete"] is False
    assert Path(report["path"]).exists()


def test_one_failing_job_does_not_stop_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(data_jobs, "HEARTBEAT", tmp_path / "hb.json")

    def boom():
        raise RuntimeError("tick server down")

    monkeypatch.setattr(decision_outcomes, "fill", boom)
    monkeypatch.setattr(data_reconciliation, "reconcile", lambda days=7: {"counts": {"ok": 0}})
    monkeypatch.setattr(data_reconciliation, "import_history", lambda days=90: {"imported": 0})
    report = data_jobs.cycle(daily=True)
    assert report["decision_outcomes"]["ok"] is False
    assert report["reconciliation"]["ok"] is True and report["history_import"]["ok"] is True
    assert (tmp_path / "hb.json").exists()
