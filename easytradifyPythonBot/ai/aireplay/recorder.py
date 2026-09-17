# ============================================================
# DECISION SNAPSHOT RECORDER
# ============================================================
#
# Emits the event-level timeline readme section 26.6 requires, at the moment
# the live pipeline computes each event.
#
# WHY THIS HAS TO BE LIVE
# -----------------------
# Phase 1 can recover only EXECUTION and CLOSE from a stored trade. The other
# events -- CANDIDATE_DETECTED, CONFIRMATION, MICROSTRUCTURE_TRIGGER,
# RL_DECISION, RISK_APPROVAL, MANAGEMENT, EXIT_DECISION -- were never written,
# and reconstructing them afterwards from the opening analysis would produce a
# timeline that looks complete and is fiction. Replay would then attribute
# failures to events that never happened, which is worse than having no replay.
#
# Recording them as they occur is different in kind: the information is real
# and contemporaneous. That is the whole reason this module exists rather than
# a smarter extractor.
#
# THE SAFETY CONTRACT
# -------------------
# This runs inside a real-money path, so:
#
#   1. It is STRICTLY ADDITIVE. No caller consumes a return value to decide
#      anything. Recording cannot change what is traded.
#   2. It CANNOT RAISE. Every public method swallows its own failures and
#      counts them. A telemetry bug must never abort a trade or a close.
#   3. It is CHEAP. Snapshots are built from values the caller already has;
#      nothing is recomputed and no market data is fetched.
#
# Rule 2 is deliberately the opposite of this package's usual "fail loudly"
# stance. Elsewhere a silent failure hides a wrong answer; here the only thing
# lost is a diagnostic record, and losing a live position to protect a
# diagnostic would be the worse trade.
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from .models import (
    DecisionSnapshot,
    EventType,
    Provenance,
    SCHEMA_VERSION,
    utc_now,
)

RECORDER_VERSION = "1.0"
SNAPSHOT_FIELD = "decision_snapshots"

logger = logging.getLogger(__name__)


def _clean(payload: Any) -> Any:
    """Keep only JSON-safe scalars and containers; never raise on odd input."""
    if isinstance(payload, Mapping):
        return {str(k): _clean(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_clean(v) for v in payload]
    if isinstance(payload, (str, int, float, bool)) or payload is None:
        return payload
    return str(payload)


class DecisionSnapshotRecorder:
    """
    Records the decision timeline for one trading process.

    `firebase` is optional: without it snapshots are held in memory, which
    keeps the recorder usable in replay, in tests, and when Firebase is down
    -- the live path must not care whether persistence is available.
    """

    def __init__(self, firebase_service: Any = None,
                 collection: str = "trades",
                 buffer_limit: int = 500):
        self.firebase = firebase_service
        self.collection = collection
        self.buffer_limit = buffer_limit

        self.buffer: List[DecisionSnapshot] = []
        self.stats = {
            "recorded": 0,
            "persisted": 0,
            "persist_failures": 0,
            "build_failures": 0,
            "dropped_no_trade_id": 0,
        }

    # -- construction ----------------------------------------------------

    def _snapshot(
        self,
        trade_id: str,
        event_type: EventType,
        timestamp: Optional[str] = None,
        **sections: Any,
    ) -> Optional[DecisionSnapshot]:
        moment = timestamp or utc_now()
        try:
            return DecisionSnapshot(
                snapshot_id=f"{trade_id}:{event_type.value}:{moment}",
                trade_id=str(trade_id),
                event_type=event_type,
                timestamp=moment,
                # Contents are computed now, so they are available now.
                # Section 26.6 permits only fields available at the snapshot
                # timestamp, and this is what makes that checkable later.
                available_at=moment,
                provenance=Provenance(
                    schema_version=SCHEMA_VERSION,
                    analysis_version=RECORDER_VERSION,
                    source="live.recorder",
                ),
                **{k: _clean(v) for k, v in sections.items() if v is not None},
            )
        except Exception as exc:
            self.stats["build_failures"] += 1
            logger.debug(f"snapshot build failed ({event_type.value}): {exc}")
            return None

    def record(
        self,
        trade_id: Any,
        event_type: EventType,
        timestamp: Optional[str] = None,
        persist: bool = True,
        **sections: Any,
    ) -> None:
        """
        Record one event. Returns nothing on purpose: nothing downstream may
        branch on whether recording worked.
        """
        try:
            if not trade_id:
                self.stats["dropped_no_trade_id"] += 1
                return

            snapshot = self._snapshot(str(trade_id), event_type, timestamp, **sections)
            if snapshot is None:
                return

            self.buffer.append(snapshot)
            if len(self.buffer) > self.buffer_limit:
                del self.buffer[: len(self.buffer) - self.buffer_limit]
            self.stats["recorded"] += 1

            if persist:
                self._persist(snapshot)
        except Exception as exc:
            # The outer guard. Nothing in a telemetry path may escape into a
            # trading path.
            self.stats["build_failures"] += 1
            logger.debug(f"recorder failure swallowed: {exc}")

    def _persist(self, snapshot: DecisionSnapshot) -> None:
        if not self.firebase:
            return
        # A provisional key has no trade document yet. Writing it would create
        # a Firestore record for a candidate that may never become a trade --
        # fictional trades in the very collection replay treats as ground
        # truth. Guarded here rather than at each call site so no future
        # caller can bypass it.
        if str(snapshot.trade_id).startswith("pending:"):
            return
        try:
            self.firebase.append_to_array(
                self.collection,
                f"trade_{snapshot.trade_id}"
                if not str(snapshot.trade_id).startswith("trade_")
                else str(snapshot.trade_id),
                SNAPSHOT_FIELD,
                snapshot.to_dict(),
            )
            self.stats["persisted"] += 1
        except Exception as exc:
            self.stats["persist_failures"] += 1
            logger.debug(f"snapshot persist failed: {exc}")

    # -- the seven event points -----------------------------------------
    #
    # Each takes what the caller already holds. None recompute anything, so a
    # call site adds a dictionary lookup, not an analysis pass.

    def candidate_detected(self, trade_id: Any, symbol: str,
                           analysis: Mapping[str, Any], **kw: Any) -> None:
        """A setup first became eligible."""
        verdict = (analysis or {}).get("final_verdict") or {}
        self.record(
            trade_id, EventType.CANDIDATE_DETECTED,
            market_snapshot={"symbol": symbol},
            market_synthesis=verdict,
            decision={"action": "CANDIDATE", "symbol": symbol},
            probabilities={
                k: verdict.get(k) for k in
                ("probability_percent", "star_rating") if k in verdict},
            **kw,
        )

    def confirmation(self, trade_id: Any, entry_analysis: Mapping[str, Any],
                     **kw: Any) -> None:
        """The setup passed (or failed) confirmation."""
        self.record(
            trade_id, EventType.CONFIRMATION,
            decision={
                "action": "CONFIRMED"
                if (entry_analysis or {}).get("should_enter") else "NOT_CONFIRMED",
                "reason": (entry_analysis or {}).get("reason"),
            },
            trade_quality_state=entry_analysis,
            **kw,
        )

    def microstructure_trigger(self, trade_id: Any,
                               microstructure: Mapping[str, Any], **kw: Any) -> None:
        """The final local trigger became active."""
        micro = microstructure or {}
        self.record(
            trade_id, EventType.MICROSTRUCTURE_TRIGGER,
            market_snapshot=micro,
            decision={
                "action": "TRIGGER_READY" if micro.get("timing_ready") else "WAITING",
            },
            probabilities={"timing_confidence": micro.get("timing_confidence")},
            **kw,
        )

    def rl_decision(self, trade_id: Any, action: str,
                    rl_state: Optional[Mapping[str, Any]] = None, **kw: Any) -> None:
        """A specialised RL agent selected an action."""
        self.record(
            trade_id, EventType.RL_DECISION,
            rl_state=rl_state or {},
            decision={"action": action},
            **kw,
        )

    def risk_approval(self, trade_id: Any, approved: bool,
                      reasons: Optional[Any] = None,
                      risk_state: Optional[Mapping[str, Any]] = None, **kw: Any) -> None:
        """The portfolio risk gate approved or rejected the trade."""
        self.record(
            trade_id, EventType.RISK_APPROVAL,
            risk_state=risk_state or {},
            decision={
                "action": "APPROVED" if approved else "REJECTED",
                "reasons": reasons,
            },
            **kw,
        )

    def management(self, trade_id: Any, action: str,
                   state: Optional[Mapping[str, Any]] = None, **kw: Any) -> None:
        """A hold / protect / adjust decision while the position was open."""
        self.record(
            trade_id, EventType.MANAGEMENT,
            execution_state=state or {},
            decision={"action": action},
            **kw,
        )

    def exit_decision(self, trade_id: Any, reason: str,
                      state: Optional[Mapping[str, Any]] = None, **kw: Any) -> None:
        """An exit was decided (distinct from the resulting CLOSE)."""
        self.record(
            trade_id, EventType.EXIT_DECISION,
            execution_state=state or {},
            decision={"action": "EXIT", "reason": reason},
            **kw,
        )

    # -- pre-trade events ------------------------------------------------
    #
    # CANDIDATE_DETECTED, CONFIRMATION and MICROSTRUCTURE_TRIGGER all occur
    # BEFORE the broker returns a ticket, and snapshots live inside the trade
    # document. So the earliest and most diagnostically valuable events have
    # nowhere to be written at the moment they happen.
    #
    # They are therefore recorded against a provisional key (symbol plus the
    # analysis timestamp), held unpersisted, and flushed into the real trade
    # document once bind_trade() supplies the ticket. A candidate that never
    # becomes a trade keeps its provisional key and is discarded by
    # drop_provisional() -- which is correct: there is no trade document to
    # attach it to, and inventing one would put fictional trades in Firebase.

    @staticmethod
    def provisional_key(symbol: str, timestamp: Optional[str] = None) -> str:
        return f"pending:{symbol}:{timestamp or utc_now()}"

    def bind_trade(self, provisional: str, ticket: Any) -> int:
        """
        Re-key buffered pre-trade events onto the real ticket and persist them.

        Returns how many were bound, for telemetry only -- no caller branches
        on it.
        """
        bound = 0
        try:
            if not ticket:
                return 0
            for snapshot in self.buffer:
                if snapshot.trade_id != provisional:
                    continue
                snapshot.trade_id = str(ticket)
                snapshot.snapshot_id = (
                    f"{ticket}:{snapshot.event_type.value}:{snapshot.timestamp}")
                self._persist(snapshot)
                bound += 1
        except Exception as exc:
            logger.debug(f"bind_trade failure swallowed: {exc}")
        return bound

    def drop_provisional(self, provisional: str) -> int:
        """Discard pre-trade events for a candidate that never became a trade."""
        try:
            before = len(self.buffer)
            self.buffer = [s for s in self.buffer if s.trade_id != provisional]
            return before - len(self.buffer)
        except Exception:
            return 0

    # -- introspection ---------------------------------------------------

    def timeline(self, trade_id: Any) -> List[DecisionSnapshot]:
        """Buffered snapshots for one trade, in the order they occurred."""
        return [s for s in self.buffer if s.trade_id == str(trade_id)]

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "aireplay.recorder",
            "version": RECORDER_VERSION,
            "persistence": bool(self.firebase),
            "buffered": len(self.buffer),
            "stats": dict(self.stats),
            "records_event_types": [e.value for e in (
                EventType.CANDIDATE_DETECTED, EventType.CONFIRMATION,
                EventType.MICROSTRUCTURE_TRIGGER, EventType.RL_DECISION,
                EventType.RISK_APPROVAL, EventType.MANAGEMENT,
                EventType.EXIT_DECISION)],
            "safety": {
                "additive_only": True,
                "never_raises": True,
                "recomputes_nothing": True,
            },
        }


# Process-wide recorder, so a call site can emit without threading an object
# through every function between the monitor loop and the analysis engine.
_recorder: Optional[DecisionSnapshotRecorder] = None


def get_recorder(firebase_service: Any = None) -> DecisionSnapshotRecorder:
    global _recorder
    if _recorder is None:
        _recorder = DecisionSnapshotRecorder(firebase_service)
    elif firebase_service is not None and _recorder.firebase is None:
        _recorder.firebase = firebase_service
    return _recorder


def reset_recorder() -> None:
    """Test seam; not for production use."""
    global _recorder
    _recorder = None


__all__ = [
    "RECORDER_VERSION", "SNAPSHOT_FIELD", "DecisionSnapshotRecorder",
    "get_recorder", "reset_recorder",
]


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------
#
# Standard 12. `get_status` existed only as a method on the recorder, so the
# module-level call every other component answers raised AttributeError, and
# there was no self_check at all.
#
# This module is NOT wired into the live trading path -- that was deferred
# deliberately -- which makes verification more important rather than less:
# the day it is wired in, its behaviour under a candidate that never becomes a
# trade is the difference between a clean timeline and fictional trades in
# Firebase.

def get_status(recorder: Optional["DecisionSnapshotRecorder"] = None
               ) -> Dict[str, Any]:
    """Buffer state, and the fact that nothing calls this yet."""
    status = (recorder or get_recorder()).get_status()
    status.update({
        "component": "aireplay.recorder",
        "wired_into_live_trading": False,
        "why_not": ("emitting pre-trade events is a live-pipeline change and "
                    "was deliberately deferred; until then only EXECUTION and "
                    "CLOSE snapshots are recoverable from history"),
    })
    return status


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove buffering, re-keying and discarding behave.

    `unbound_candidate_is_dropped` is the one that matters. A candidate that
    never becomes a trade has no ticket to attach to, and persisting it anyway
    would write fictional trades into Firebase -- a corruption of the
    historical record that every downstream model would then treat as fact.
    """
    report: Dict[str, Any] = {
        "component": "aireplay.recorder", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        # No firebase_service: buffering must work without persistence, or the
        # recorder becomes a hard dependency on a network service.
        recorder = DecisionSnapshotRecorder(firebase_service=None)
        provisional = DecisionSnapshotRecorder.provisional_key("EURUSD")
        checks["provisional_key_is_namespaced"] = provisional.startswith("pending:")

        recorder.candidate_detected(provisional, "EURUSD", {"reason": "test"})
        recorder.confirmation(provisional, {"grade": "A"})
        checks["events_buffer"] = len(recorder.timeline(provisional)) == 2

        # Binding re-keys onto the real ticket.
        bound = recorder.bind_trade(provisional, 4242)
        checks["bind_rekeys_events"] = bound == 2
        checks["bound_events_carry_the_ticket"] = (
            len(recorder.timeline(4242)) == 2)
        checks["provisional_key_is_gone"] = not recorder.timeline(provisional)

        # A candidate that never became a trade is discarded, not invented.
        orphan = DecisionSnapshotRecorder.provisional_key("GBPUSD")
        recorder.candidate_detected(orphan, "GBPUSD", {"reason": "test"})
        dropped = recorder.drop_provisional(orphan)
        checks["unbound_candidate_is_dropped"] = (
            dropped == 1 and not recorder.timeline(orphan))

        # Binding with no ticket must be a no-op rather than a bad key.
        stray = DecisionSnapshotRecorder.provisional_key("USDJPY")
        recorder.candidate_detected(stray, "USDJPY", {})
        checks["bind_without_ticket_is_a_noop"] = (
            recorder.bind_trade(stray, None) == 0
            and len(recorder.timeline(stray)) == 1)

        checks["reports_not_wired_live"] = (
            get_status(recorder)["wired_into_live_trading"] is False)

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report
