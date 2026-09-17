"""Skipped setups: recorded only when live and declined; outcomes from the tick path."""

from datetime import datetime, timezone

import numpy as np

from ai import skipped_setup_outcomes as outcomes
from core import skipped_setups as ss


def analysis(should_enter=False, groups=True, verdict="⏸️ SKIP - POOR DISCOUNT"):
    return {
        "success": True,
        "entry_analysis": {"should_enter": should_enter, "entry_status": "POOR_DISCOUNT"},
        "final_verdict": {"verdict": verdict, "entry_price": 1.1000, "stop_loss": 1.0990,
                          "take_profit_1": 1.1030, "lot_size": 0.4, "risk_usd": 4.0},
        "entry_details": {"stop_loss_pips": 10, "take_profit_pips": 30, "lot_size": 0.4, "risk_usd": 4.0},
        "direction_decision": {"traded_direction": "BUY", "analysis_direction": "BUY"},
        "strategy_groups": ({"enabled": True, "final_probability": 82.0, "winner": "TREND",
                             "groups": {"TREND": {"scored": True, "score": 90.0}}} if groups else {"enabled": False}),
        "volatility_protection": {"atr_pips": 2.0},
        "config": {"min_probability_for_entry": 75.0},
    }


class FakeCollection:
    def __init__(self):
        self.calls = []

    def update_one(self, query, update, upsert=False):
        self.calls.append((query, update, upsert))


def test_declined_live_setup_is_recorded_once_per_minute():
    col = FakeCollection()
    assert ss.record(analysis(), symbol="EURUSD", is_replay=False, is_already_in_trade=False, collection=col)
    query, update, upsert = col.calls[0]
    assert upsert and query["key"].startswith("EURUSD|")
    doc = update["$set"]
    assert doc["skip_reason"] == "⏸️ SKIP - POOR DISCOUNT"
    assert doc["probability"] == 82.0 and doc["winner_group"] == "TREND" and doc["entry_floor"] == 75.0
    assert update["$setOnInsert"]["outcome"] is None and update["$inc"]["seen_count"] == 1


def test_not_recorded_when_entered_replayed_in_trade_or_without_groups():
    col = FakeCollection()
    assert not ss.record(analysis(should_enter=True), symbol="X", is_replay=False, is_already_in_trade=False, collection=col)
    assert not ss.record(analysis(), symbol="X", is_replay=True, is_already_in_trade=False, collection=col)
    assert not ss.record(analysis(), symbol="X", is_replay=False, is_already_in_trade=True, collection=col)
    assert not ss.record(analysis(groups=False), symbol="X", is_replay=False, is_already_in_trade=False, collection=col)
    assert col.calls == []


def test_recording_never_raises():
    class Broken:
        def update_one(self, *a, **k):
            raise RuntimeError("db down")
    assert ss.record(analysis(), symbol="X", is_replay=False, is_already_in_trade=False, collection=Broken()) is False


def _doc():
    return {"key": "EURUSD|x", "symbol": "EURUSD", "direction": "BUY", "entry_price": 1.1000,
            "stop_loss": 1.0990, "take_profit": 1.1030, "atr_pips": 2.0, "lot_size": 0.4, "risk_usd": 4.0,
            "minute_utc": datetime(2026, 9, 15, tzinfo=timezone.utc)}


def test_outcome_target_hit_before_stop():
    t = np.arange(5, dtype=float)
    bid = np.array([1.1000, 1.1010, 1.1020, 1.1031, 1.1000])
    out = outcomes.evaluate(_doc(), t, bid, bid + 0.0001, pip=0.0001)
    assert out["replay_result"] == "TARGET" and out["gross_r"] == 3.0
    assert out["net_r"] == round(3.0 - 0.4 * 7.03 / 4.0, 4)
    assert out["market_5atr"] == 1 and out["direction_right"] is True


def test_outcome_stop_hit_first():
    t = np.arange(4, dtype=float)
    bid = np.array([1.1000, 1.0995, 1.0989, 1.1040])
    out = outcomes.evaluate(_doc(), t, bid, bid + 0.0001, pip=0.0001)
    assert out["replay_result"] == "STOP" and out["gross_r"] == -1.0


def test_reason_families():
    assert outcomes._reason_family("⏸️ SKIP - POOR DISCOUNT") == "POOR DISCOUNT"
    assert outcomes._reason_family("⏸️ VETO - Extreme volatility (ATR=...)") == "EXTREME VOLATILITY"
    assert outcomes._reason_family("SKIP - Full-confluence probability 70% fell below the 75% floor") == "BELOW THE"
