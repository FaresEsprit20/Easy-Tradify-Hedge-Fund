# ============================================================
# LIVE RECORDING -- WIRING THE RECORDER INTO THE TRADING PATH
# ============================================================
#
# WHAT THIS UNBLOCKS
# ------------------
# Replay could only ever recover EXECUTION and CLOSE snapshots, because the
# live pipeline never emitted anything else. First-divergence detection needs
# the pre-trade timeline -- when the candidate appeared, what confirmation it
# passed, what the microstructure trigger said, whether risk approved it -- and
# none of that existed in history. That is the single limitation stamped on
# `replay_engine.get_status()`.
#
# THIS RUNS INSIDE A REAL-MONEY TRADING PATH
# ------------------------------------------
# Which sets the design, not the feature list:
#
#   1. OFF BY DEFAULT. Nothing changes until AIREPLAY_RECORD_LIVE is set.
#      A telemetry feature that switches itself on in a live system is a
#      change nobody approved.
#   2. NOTHING ESCAPES. Every entry point is wrapped so no exception, from
#      here or from the recorder, can reach the caller. A trade must never
#      fail to open because its telemetry raised.
#   3. NOTHING IS MUTATED. The decision dict is read, never written. This
#      module cannot alter a decision even by accident, because it never
#      holds a reference it could assign through.
#   4. NO NETWORK IN THE HOT PATH. Pre-trade events buffer in memory
#      (persist=False) and are written only once a ticket exists. A candidate
#      that never becomes a trade is discarded -- persisting it would put
#      fictional trades in Firebase, which is worse than recording nothing.
#
# WHY ONE SEAM AND NOT FIFTEEN
# ----------------------------
# `EntryEngine.get_entry_decision` wraps an implementation with eight return
# paths. The codebase already learned this lesson once: diagnostics were
# hand-written into three of those paths and silently missing from the other
# five, which were 90% of real decisions. The fix there was structural -- do it
# once in the wrapper -- and the same argument applies here with more force,
# because each extra touch point in a live order path is another place a change
# can go wrong.
#
# The decision dict already carries micro_structure, confirmation state and the
# verdict, so the whole pre-trade timeline is derivable at that one seam.
# ============================================================

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Mapping, Optional

from .models import EventType, utc_now

LIVE_RECORDING_VERSION = "1.0"

_ENV_FLAG = "AIREPLAY_RECORD_LIVE"

# Provisional keys, per symbol, awaiting a ticket. Bounded: a symbol keeps only
# its most recent pending decision, so an unbound backlog cannot grow.
_PENDING: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()

# A pending candidate older than this is abandoned. Without it, a symbol that
# stops trading would pin its last provisional key forever and a much later
# execution would bind events from an unrelated decision.
PENDING_TTL_SECONDS = 900


def is_enabled() -> bool:
    """
    Recording is opt-in, checked on every call rather than cached.

    Read live so the flag can be turned OFF without a restart. Turning
    telemetry off during an incident should not require redeploying the thing
    having the incident.
    """
    return str(os.environ.get(_ENV_FLAG, "")).strip().lower() in (
        "1", "true", "yes", "on")


def _recorder():
    from .recorder import get_recorder
    return get_recorder()


def _seconds_between(later: str, earlier: str) -> float:
    from datetime import datetime

    try:
        end = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
        start = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        return abs((end - start).total_seconds())
    except Exception:
        return 0.0


def _prune(now: Optional[str] = None) -> None:
    now = now or utc_now()
    stale = [symbol for symbol, entry in _PENDING.items()
             if _seconds_between(now, entry["created_at"]) > PENDING_TTL_SECONDS]
    for symbol in stale:
        entry = _PENDING.pop(symbol, None)
        if entry:
            # Discarded, never persisted: there is no trade to attach it to.
            try:
                _recorder().drop_provisional(entry["key"])
            except Exception:
                pass


def record_entry_decision(symbol: str, result: Mapping[str, Any],
                          inputs: Optional[Mapping[str, Any]] = None) -> None:
    """
    Emit the pre-trade timeline from one entry decision.

    Called from `EntryEngine.get_entry_decision`. Reads `result`; never writes
    to it. Returns None unconditionally so no caller can branch on whether
    recording happened -- a decision that varies with telemetry state is a
    decision nobody can replay.
    """
    if not is_enabled():
        return
    try:
        if not symbol or not isinstance(result, Mapping):
            return

        from .recorder import DecisionSnapshotRecorder

        recorder = _recorder()
        now = utc_now()
        with _LOCK:
            _prune(now)
            existing = _PENDING.get(symbol)
            # One provisional key per symbol per decision cycle. A symbol
            # re-evaluated every tick would otherwise mint a key per tick.
            if existing and _seconds_between(
                    now, existing["created_at"]) <= PENDING_TTL_SECONDS:
                key = existing["key"]
            else:
                if existing:
                    recorder.drop_provisional(existing["key"])
                key = DecisionSnapshotRecorder.provisional_key(symbol, now)
                _PENDING[symbol] = {"key": key, "created_at": now,
                                    "events": 0}

        micro = result.get("micro_structure")
        micro = micro if isinstance(micro, Mapping) else {}

        # CANDIDATE_DETECTED: a setup was evaluated at all.
        recorder.candidate_detected(
            key, symbol,
            {"final_verdict": {
                "probability_percent": result.get("adjusted_probability")
                or result.get("probability"),
                "star_rating": result.get("star_rating"),
            }},
            persist=False)

        if micro:
            recorder.microstructure_trigger(key, micro, persist=False)

        # CONFIRMATION carries the verdict AND the reason, because the
        # rejections are the interesting rows: eight return paths and most
        # real decisions never reach an entry.
        recorder.confirmation(
            key,
            {
                "allow_entry": result.get("allow_entry"),
                "confirmation_type": result.get("confirmation_type"),
                "confirmation_score": result.get("confirmation_score"),
                "reason": result.get("reason"),
                "zone_grade": result.get("zone_grade"),
            },
            persist=False)

        with _LOCK:
            if symbol in _PENDING:
                _PENDING[symbol]["events"] += 3 if micro else 2
    except Exception:
        # Nothing from a telemetry path reaches a trading path. Deliberately
        # silent here rather than logging: this runs per decision, and a
        # failing logger in a hot loop is its own outage.
        return


def record_rl_decision(symbol: str, action: str,
                       rl_state: Optional[Mapping[str, Any]] = None) -> None:
    """RL_DECISION, attached to the symbol's pending candidate."""
    if not is_enabled():
        return
    try:
        with _LOCK:
            entry = _PENDING.get(symbol)
        if not entry:
            return
        _recorder().rl_decision(entry["key"], action, rl_state, persist=False)
    except Exception:
        return


def record_risk_approval(symbol: str, approved: bool,
                         risk_state: Optional[Mapping[str, Any]] = None) -> None:
    """RISK_APPROVAL. A rejection here is the last pre-trade event."""
    if not is_enabled():
        return
    try:
        with _LOCK:
            entry = _PENDING.get(symbol)
        if not entry:
            return
        _recorder().risk_approval(entry["key"], bool(approved),
                                  risk_state or {}, persist=False)
    except Exception:
        return


def bind_execution(symbol: str, ticket: Any) -> int:
    """
    A trade opened: re-key the buffered pre-trade events onto its ticket and
    persist them.

    This is the only point at which pre-trade events reach Firebase, and it is
    reached only when a real ticket exists. Returns a count for telemetry;
    no caller may branch on it.
    """
    if not is_enabled():
        return 0
    try:
        with _LOCK:
            entry = _PENDING.pop(symbol, None)
        if not entry or not ticket:
            return 0
        return _recorder().bind_trade(entry["key"], ticket)
    except Exception:
        return 0


def abandon(symbol: str) -> int:
    """
    A candidate that never became a trade. Its events are discarded.

    Not persisted, on purpose: there is no trade document to attach them to,
    and inventing one would write fictional trades into the historical record
    that every downstream model would then treat as fact.
    """
    if not is_enabled():
        return 0
    try:
        with _LOCK:
            entry = _PENDING.pop(symbol, None)
        if not entry:
            return 0
        return _recorder().drop_provisional(entry["key"])
    except Exception:
        return 0


def pending_count() -> int:
    with _LOCK:
        return len(_PENDING)


def reset() -> None:
    """Drop pending state. For tests and for a clean restart."""
    with _LOCK:
        _PENDING.clear()


def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.live_recording",
        "version": LIVE_RECORDING_VERSION,
        "enabled": is_enabled(),
        "env_flag": _ENV_FLAG,
        "default": "OFF",
        "pending_candidates": pending_count(),
        "pending_ttl_seconds": PENDING_TTL_SECONDS,
        "seam": "EntryEngine.get_entry_decision",
        "guarantees": [
            "never raises into the trading path",
            "never mutates the decision",
            "no network in the hot path (pre-trade events buffer only)",
            "unbound candidates are discarded, never persisted",
        ],
        "events_emitted": [
            EventType.CANDIDATE_DETECTED.value,
            EventType.MICROSTRUCTURE_TRIGGER.value,
            EventType.CONFIRMATION.value,
            EventType.RL_DECISION.value,
            EventType.RISK_APPROVAL.value,
        ],
    }


def self_check(trades: Optional[Any] = None) -> Dict[str, Any]:
    """
    Prove the safety properties, not the feature.

    Every check here is about what this module must NOT do. The feature is
    worth little; the guarantees are the whole point, because this code runs
    between a signal and an order.
    """
    report: Dict[str, Any] = {
        "component": "aireplay.live_recording", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        from .recorder import reset_recorder

        was_enabled = os.environ.get(_ENV_FLAG)

        # 1. OFF by default: no state touched, nothing recorded.
        try:
            os.environ.pop(_ENV_FLAG, None)
            reset()
            reset_recorder()
            record_entry_decision("EURUSD", {"allow_entry": True})
            checks["disabled_records_nothing"] = pending_count() == 0
        finally:
            pass

        # 2. Enabled: the timeline appears.
        os.environ[_ENV_FLAG] = "1"
        reset()
        reset_recorder()
        decision = {
            "allow_entry": True, "adjusted_probability": 72,
            "star_rating": 4, "confirmation_type": "ENGULFING",
            "micro_structure": {"available": True, "entry_confidence": 80},
            "reason": "ok",
        }
        record_entry_decision("EURUSD", decision)
        recorder = _recorder()
        with _LOCK:
            key = _PENDING["EURUSD"]["key"]
        checks["events_recorded"] = len(recorder.timeline(key)) == 3

        # 3. The decision is never mutated.
        before = dict(decision)
        record_entry_decision("EURUSD", decision)
        checks["decision_not_mutated"] = decision == before

        # 4. Nothing raises, whatever it is handed.
        for junk in (None, "string", 42, {"weird": object()}):
            record_entry_decision("EURUSD", junk)  # type: ignore[arg-type]
        record_entry_decision(None, decision)      # type: ignore[arg-type]
        checks["never_raises_on_junk"] = True

        # 5. Pre-trade events are NOT persisted before a ticket exists.
        checks["nothing_persisted_pre_trade"] = (
            recorder.stats.get("persisted", 0) == 0)

        # 6. Binding re-keys onto the real ticket.
        bound = bind_execution("EURUSD", 991122)
        checks["bind_rekeys_events"] = bound >= 3
        checks["pending_cleared_after_bind"] = pending_count() == 0

        # 7. An abandoned candidate is discarded, not persisted.
        reset()
        reset_recorder()
        record_entry_decision("GBPUSD", decision)
        dropped = abandon("GBPUSD")
        checks["abandoned_candidate_discarded"] = dropped >= 2
        checks["no_fictional_trades"] = pending_count() == 0

        # 8. One key per symbol per cycle, not one per tick.
        reset()
        reset_recorder()
        for _ in range(5):
            record_entry_decision("USDJPY", decision)
        checks["one_key_per_symbol"] = pending_count() == 1

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        try:
            if was_enabled is None:
                os.environ.pop(_ENV_FLAG, None)
            else:
                os.environ[_ENV_FLAG] = was_enabled
            reset()
        except Exception:
            pass
    return report


__all__ = [
    "LIVE_RECORDING_VERSION", "is_enabled", "record_entry_decision",
    "record_rl_decision", "record_risk_approval", "bind_execution",
    "abandon", "pending_count", "reset", "get_status", "self_check",
]
