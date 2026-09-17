"""
The recorder, wired into the live trading path.

This is the one piece of AI_MarketReplay that runs between a signal and a real
order, so almost every test here asserts something the module must NOT do. The
feature -- a pre-trade timeline -- is worth little next to the guarantees:

  * OFF by default, so nothing changes until someone decides it should;
  * never raises into the caller, so a trade cannot fail to open because its
    telemetry did;
  * never mutates the decision, so a recorded run and an unrecorded run are
    the same run;
  * no network in the hot path, and nothing persisted until a real ticket
    exists -- a candidate that never became a trade must not appear in
    Firebase as though it had.

The last one is the reason replay refuses to synthesise these events from
history: a fictional trade in the record is worse than a missing one, because
every downstream model treats it as fact.
"""

import os

import pytest

from ai.aireplay import live_recording
from ai.aireplay.recorder import get_recorder, reset_recorder

FLAG = "AIREPLAY_RECORD_LIVE"

DECISION = {
    "allow_entry": True,
    "adjusted_probability": 72,
    "star_rating": 4,
    "confirmation_type": "ENGULFING",
    "confirmation_score": 80,
    "zone_grade": "B",
    "reason": "confirmed",
    "micro_structure": {"available": True, "entry_confidence": 78},
}


@pytest.fixture
def recording_on():
    previous = os.environ.get(FLAG)
    os.environ[FLAG] = "1"
    live_recording.reset()
    reset_recorder()
    yield
    if previous is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previous
    live_recording.reset()
    reset_recorder()


@pytest.fixture
def recording_off():
    previous = os.environ.get(FLAG)
    os.environ.pop(FLAG, None)
    live_recording.reset()
    reset_recorder()
    yield
    if previous is not None:
        os.environ[FLAG] = previous
    live_recording.reset()
    reset_recorder()


# ---------------------------------------------------------------------------
# The guarantees
# ---------------------------------------------------------------------------

def test_off_by_default(recording_off):
    """A telemetry feature that switches itself on is a change nobody approved."""
    assert live_recording.is_enabled() is False
    live_recording.record_entry_decision("EURUSD", DECISION)
    assert live_recording.pending_count() == 0
    assert get_recorder().stats.get("recorded", 0) == 0


def test_never_raises_on_anything(recording_on):
    """A trade must not fail to open because its telemetry choked."""
    for junk in (None, "string", 42, [], {"weird": object()}):
        live_recording.record_entry_decision("EURUSD", junk)
        live_recording.record_rl_decision("EURUSD", junk)
        live_recording.record_risk_approval("EURUSD", junk)
    live_recording.record_entry_decision(None, DECISION)
    live_recording.bind_execution(None, None)
    live_recording.abandon("never-seen")


def test_the_decision_is_never_mutated(recording_on):
    original = dict(DECISION)
    nested = dict(DECISION["micro_structure"])
    live_recording.record_entry_decision("EURUSD", DECISION)
    assert DECISION == original
    assert DECISION["micro_structure"] == nested


def test_nothing_is_persisted_before_a_ticket_exists(recording_on):
    """
    A candidate that never becomes a trade has no document to attach to, and
    inventing one would put fictional trades in the historical record.
    """
    live_recording.record_entry_decision("EURUSD", DECISION)
    assert get_recorder().stats.get("persisted", 0) == 0


def test_events_are_buffered_then_bound_to_the_real_ticket(recording_on):
    live_recording.record_entry_decision("EURUSD", DECISION)
    assert live_recording.pending_count() == 1
    bound = live_recording.bind_execution("EURUSD", 12345)
    assert bound >= 3
    assert get_recorder().timeline(12345)
    assert live_recording.pending_count() == 0


def test_an_abandoned_candidate_is_discarded(recording_on):
    live_recording.record_entry_decision("GBPUSD", DECISION)
    assert live_recording.abandon("GBPUSD") >= 2
    assert live_recording.pending_count() == 0


def test_one_key_per_symbol_not_one_per_tick(recording_on):
    """A symbol re-evaluated every tick would otherwise mint a key per tick."""
    for _ in range(10):
        live_recording.record_entry_decision("USDJPY", DECISION)
    assert live_recording.pending_count() == 1


def test_rejections_are_recorded_not_only_entries(recording_on):
    """
    Five of the eight return paths are early exits, and they are over 90% of
    real decisions. A timeline that only covers entries covers almost nothing.
    """
    rejected = {"allow_entry": False, "reason": "WAITING_CONFIRMATION",
                "zone_grade": "C"}
    live_recording.record_entry_decision("AUDUSD", rejected)
    assert live_recording.pending_count() == 1


# ---------------------------------------------------------------------------
# The seam, through the real engine
# ---------------------------------------------------------------------------

ENTRY_ARGS = dict(
    symbol="EURUSD", best_direction="BUY", current_price=1.0850,
    zone_level=1.0840, zone_type="DEMAND", zone_grade="B",
    candle_data={"open": 1.0845, "high": 1.0855, "low": 1.0838,
                 "close": 1.0850},
    volume_spike=True, at_poi=True, best_probability=72.0,
    pip_size=0.0001,
)


def test_recording_does_not_change_the_decision():
    """
    THE test. If a recorded run and an unrecorded run can differ, the
    recording is no longer telemetry -- it is part of the strategy, and every
    replay built on it is describing a system that did not run.
    """
    from core.entry_engine import EntryEngine

    engine = EntryEngine()
    previous = os.environ.get(FLAG)
    try:
        os.environ.pop(FLAG, None)
        live_recording.reset()
        reset_recorder()
        without = engine.get_entry_decision(**ENTRY_ARGS)

        os.environ[FLAG] = "1"
        live_recording.reset()
        reset_recorder()
        with_recording = engine.get_entry_decision(**ENTRY_ARGS)

        assert without == with_recording
    finally:
        if previous is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previous
        live_recording.reset()
        reset_recorder()


def test_the_seam_emits_the_pre_trade_timeline(recording_on):
    from core.entry_engine import EntryEngine

    EntryEngine().get_entry_decision(**ENTRY_ARGS)
    assert live_recording.pending_count() == 1
    assert get_recorder().stats.get("recorded", 0) >= 2
    assert get_recorder().stats.get("persisted", 0) == 0


def test_status_reports_the_flag_and_the_guarantees():
    status = live_recording.get_status()
    assert status["default"] == "OFF"
    assert status["env_flag"] == FLAG
    assert any("never raises" in g for g in status["guarantees"])
    assert "CANDIDATE_DETECTED" in status["events_emitted"]


def test_self_check_proves_the_safety_properties():
    report = live_recording.self_check()
    assert report["ok"] is True, report.get("error")
    for name in ("disabled_records_nothing", "decision_not_mutated",
                 "nothing_persisted_pre_trade", "no_fictional_trades"):
        assert report["checks"][name] is True
