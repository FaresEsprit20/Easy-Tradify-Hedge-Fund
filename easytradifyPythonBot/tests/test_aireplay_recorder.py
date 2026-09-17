"""
Decision snapshot recorder.

This runs inside a real-money path, so the load-bearing tests are the safety
contract: it must never raise, never influence a decision, and never lose a
trade to protect a diagnostic.
"""

import pytest

from ai.aireplay import EventType
from ai.aireplay.recorder import (
    RECORDER_VERSION,
    SNAPSHOT_FIELD,
    DecisionSnapshotRecorder,
    get_recorder,
    reset_recorder,
)

from conftest import build_analysis


class FakeFirebase:
    def __init__(self, fail=False):
        self.appended = []
        self.fail = fail

    def append_to_array(self, collection, doc_id, field, value):
        if self.fail:
            raise RuntimeError("firebase down")
        self.appended.append((collection, doc_id, field, value))


@pytest.fixture(autouse=True)
def _reset():
    reset_recorder()
    yield
    reset_recorder()


# ---------------------------------------------------------------------------
# The safety contract
# ---------------------------------------------------------------------------

def test_recording_never_raises_on_bad_input():
    """
    A telemetry bug must not abort a trade. Deliberately the opposite of this
    package's usual fail-loudly stance: the only thing lost here is a
    diagnostic record.
    """
    recorder = DecisionSnapshotRecorder()
    for bad in (None, object(), {"cycle": ...}, [1, 2, 3]):
        recorder.record(trade_id=1, event_type=EventType.CONFIRMATION,
                        decision=bad)
    assert recorder.stats["recorded"] >= 0   # reached here at all


def test_persistence_failure_is_swallowed():
    recorder = DecisionSnapshotRecorder(FakeFirebase(fail=True))
    recorder.candidate_detected(1, "EURUSD", build_analysis())
    assert recorder.stats["persist_failures"] == 1
    assert recorder.stats["recorded"] == 1      # still recorded in memory


def test_recording_returns_nothing():
    """Nothing downstream may branch on whether recording worked."""
    recorder = DecisionSnapshotRecorder()
    assert recorder.candidate_detected(1, "EURUSD", build_analysis()) is None
    assert recorder.risk_approval(1, True) is None
    assert recorder.exit_decision(1, "SL") is None


def test_works_without_persistence():
    """The live path must not care whether Firebase is available."""
    recorder = DecisionSnapshotRecorder(firebase_service=None)
    recorder.confirmation(1, {"should_enter": True})
    assert len(recorder.timeline(1)) == 1
    assert recorder.stats["persisted"] == 0


def test_unidentified_events_are_dropped_not_guessed():
    recorder = DecisionSnapshotRecorder()
    recorder.candidate_detected(None, "EURUSD", build_analysis())
    assert recorder.stats["dropped_no_trade_id"] == 1
    assert recorder.buffer == []


def test_buffer_is_bounded():
    """A long-running monitor must not grow memory without limit."""
    recorder = DecisionSnapshotRecorder(buffer_limit=10)
    for i in range(50):
        recorder.confirmation(1, {"should_enter": True})
    assert len(recorder.buffer) == 10


# ---------------------------------------------------------------------------
# The five previously unrecordable events
# ---------------------------------------------------------------------------

def test_records_every_previously_missing_event_type():
    """
    These are exactly the events Phase 1 could not recover from storage, and
    the reason first-divergence detection was blocked.
    """
    recorder = DecisionSnapshotRecorder()
    analysis = build_analysis()

    recorder.candidate_detected(7, "EURUSD", analysis)
    recorder.confirmation(7, {"should_enter": True, "reason": "confirmed"})
    recorder.microstructure_trigger(7, {"timing_ready": True, "timing_confidence": 82})
    recorder.rl_decision(7, "ENTER", {"q_values": [0.1, 0.9]})
    recorder.risk_approval(7, True, reasons=[], risk_state={"drawdown": 0.02})
    recorder.management(7, "PROTECT", {"new_sl": 1.0860})
    recorder.exit_decision(7, "TRAILING_STOP", {"price": 1.0885})

    recorded = [s.event_type for s in recorder.timeline(7)]
    for event in (EventType.CANDIDATE_DETECTED, EventType.CONFIRMATION,
                  EventType.MICROSTRUCTURE_TRIGGER, EventType.RL_DECISION,
                  EventType.RISK_APPROVAL, EventType.MANAGEMENT,
                  EventType.EXIT_DECISION):
        assert event in recorded, event


def test_timeline_is_ordered_and_scoped_to_one_trade():
    recorder = DecisionSnapshotRecorder()
    recorder.candidate_detected(1, "EURUSD", build_analysis())
    recorder.candidate_detected(2, "GBPUSD", build_analysis())
    recorder.confirmation(1, {"should_enter": True})

    timeline = recorder.timeline(1)
    assert len(timeline) == 2
    assert all(s.trade_id == "1" for s in timeline)
    assert timeline[0].event_type is EventType.CANDIDATE_DETECTED


def test_snapshots_are_temporally_valid():
    """Section 26.6 permits only fields available at the snapshot timestamp."""
    recorder = DecisionSnapshotRecorder()
    recorder.confirmation(1, {"should_enter": True})
    assert all(s.is_temporally_valid() for s in recorder.timeline(1))


def test_rejection_is_recorded_as_faithfully_as_approval():
    """
    A refused trade is evidence too -- and it is the only record that a gate
    fired at all, since a rejected trade never reaches storage.
    """
    recorder = DecisionSnapshotRecorder()
    recorder.risk_approval(9, False, reasons=["daily loss limit"])
    recorder.confirmation(9, {"should_enter": False, "reason": "no confirmation"})

    decisions = [s.decision["action"] for s in recorder.timeline(9)]
    assert "REJECTED" in decisions
    assert "NOT_CONFIRMED" in decisions


# ---------------------------------------------------------------------------
# Pre-trade events
#
# CANDIDATE_DETECTED, CONFIRMATION and MICROSTRUCTURE_TRIGGER occur before the
# broker returns a ticket, and snapshots live inside the trade document -- so
# the earliest and most diagnostically valuable events have nowhere to be
# written at the moment they happen.
# ---------------------------------------------------------------------------

def test_pre_trade_events_are_not_persisted():
    """
    Writing a provisional key would create a Firestore record for a candidate
    that may never become a trade -- fictional trades in the collection replay
    treats as ground truth.
    """
    firebase = FakeFirebase()
    recorder = DecisionSnapshotRecorder(firebase)
    key = recorder.provisional_key("EURUSD", "2026-09-01T10:00:00Z")

    recorder.candidate_detected(key, "EURUSD", build_analysis())
    recorder.confirmation(key, {"should_enter": True})

    assert firebase.appended == []
    assert len(recorder.timeline(key)) == 2


def test_binding_a_ticket_flushes_pre_trade_events():
    firebase = FakeFirebase()
    recorder = DecisionSnapshotRecorder(firebase)
    key = recorder.provisional_key("EURUSD", "2026-09-01T10:00:00Z")

    recorder.candidate_detected(key, "EURUSD", build_analysis())
    recorder.microstructure_trigger(key, {"timing_ready": True})
    assert firebase.appended == []

    bound = recorder.bind_trade(key, 555)
    assert bound == 2
    assert len(firebase.appended) == 2
    assert all(doc_id == "trade_555" for _, doc_id, _, _ in firebase.appended)
    assert recorder.timeline(key) == []
    assert len(recorder.timeline(555)) == 2


def test_binding_rewrites_snapshot_identity():
    recorder = DecisionSnapshotRecorder()
    key = recorder.provisional_key("EURUSD")
    recorder.confirmation(key, {"should_enter": True})
    recorder.bind_trade(key, 777)

    snapshot = recorder.timeline(777)[0]
    assert snapshot.trade_id == "777"
    assert snapshot.snapshot_id.startswith("777:")


def test_candidates_that_never_trade_are_dropped():
    """
    Correct behaviour: there is no trade document to attach them to, and
    inventing one would put fictional trades in Firebase.
    """
    firebase = FakeFirebase()
    recorder = DecisionSnapshotRecorder(firebase)
    key = recorder.provisional_key("EURUSD")

    recorder.candidate_detected(key, "EURUSD", build_analysis())
    recorder.confirmation(key, {"should_enter": False, "reason": "no confirmation"})

    assert recorder.drop_provisional(key) == 2
    assert recorder.timeline(key) == []
    assert firebase.appended == []


def test_binding_without_a_ticket_does_nothing():
    recorder = DecisionSnapshotRecorder()
    key = recorder.provisional_key("EURUSD")
    recorder.confirmation(key, {"should_enter": True})
    assert recorder.bind_trade(key, None) == 0
    assert len(recorder.timeline(key)) == 1


def test_binding_leaves_other_candidates_alone():
    recorder = DecisionSnapshotRecorder()
    a = recorder.provisional_key("EURUSD", "t1")
    b = recorder.provisional_key("GBPUSD", "t2")
    recorder.confirmation(a, {"should_enter": True})
    recorder.confirmation(b, {"should_enter": True})

    recorder.bind_trade(a, 111)
    assert len(recorder.timeline(111)) == 1
    assert len(recorder.timeline(b)) == 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_persists_to_the_trade_document():
    firebase = FakeFirebase()
    recorder = DecisionSnapshotRecorder(firebase)
    recorder.confirmation(555, {"should_enter": True})

    collection, doc_id, field, value = firebase.appended[0]
    assert collection == "trades"
    assert doc_id == "trade_555"
    assert field == SNAPSHOT_FIELD
    assert value["event_type"] == EventType.CONFIRMATION.value


def test_does_not_double_prefix_an_already_prefixed_id():
    """
    The exact bug this codebase hit four times: trade_trade_{ticket}
    documents that nothing ever reads.
    """
    firebase = FakeFirebase()
    DecisionSnapshotRecorder(firebase).confirmation("trade_555", {"should_enter": True})
    assert firebase.appended[0][1] == "trade_555"


def test_persisted_payload_is_json_safe():
    class Odd:
        def __repr__(self):
            return "<odd>"

    firebase = FakeFirebase()
    recorder = DecisionSnapshotRecorder(firebase)
    recorder.management(1, "PROTECT", {"weird": Odd(), "n": 1.5, "ok": True})

    value = firebase.appended[0][3]
    assert value["execution_state"]["weird"] == "<odd>"
    assert value["execution_state"]["n"] == 1.5


# ---------------------------------------------------------------------------
# Shared instance and status
# ---------------------------------------------------------------------------

def test_shared_recorder_is_reused():
    first = get_recorder()
    first.confirmation(1, {"should_enter": True})
    assert get_recorder() is first
    assert len(get_recorder().timeline(1)) == 1


def test_shared_recorder_gains_persistence_later():
    """Firebase often initialises after the first analysis has already run."""
    recorder = get_recorder()
    assert recorder.firebase is None

    firebase = FakeFirebase()
    recorder = get_recorder(firebase)
    recorder.confirmation(1, {"should_enter": True})
    assert firebase.appended


def test_status_declares_the_safety_contract():
    status = DecisionSnapshotRecorder().get_status()
    assert status["safety"]["additive_only"] is True
    assert status["safety"]["never_raises"] is True
    assert status["safety"]["recomputes_nothing"] is True
    assert EventType.RISK_APPROVAL.value in status["records_event_types"]


def test_status_counts_failures_rather_than_hiding_them():
    recorder = DecisionSnapshotRecorder(FakeFirebase(fail=True))
    recorder.confirmation(1, {"should_enter": True})
    assert recorder.get_status()["stats"]["persist_failures"] == 1
