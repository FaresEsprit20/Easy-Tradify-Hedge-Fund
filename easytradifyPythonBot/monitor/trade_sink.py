# ============================================================
# TRADE SINK -- MIRRORS LIVE TRADES INTO MONGODB
# ============================================================
# FILE: monitor/trade_sink.py
#
# The live monitor writes trades to Firestore. The AI layer now reads them
# from MongoDB. This is the seam that keeps both true.
#
# WHY A DUAL WRITE RATHER THAN A SWITCH
# -------------------------------------
# A hard cutover has no safe failure: if Mongo is down at the moment a trade
# opens, that trade has no record anywhere. Writing to both means the trading
# path keeps its existing, working store while the analysis path gets the one
# it can actually query -- and either can fail without taking the other with
# it.
#
# The Firestore path also physically cannot hold what the AI needs: a document
# is capped at 1 MiB and a trade with its forward walk is several megabytes,
# which is why price_evolution there had to become a subcollection. Mongo's
# 16 MB limit holds the whole trade as one document, so `price_evolution` is a
# plain array again -- the shape every model already expects.
#
# FAIL-SOFT, ABSOLUTELY
# ---------------------
# Nothing in this module may raise into a trading path. A telemetry failure
# must never prevent an order, a stop, or a close. Every entry point swallows
# and logs. That is the opposite of the rule everywhere else in this codebase
# -- normally silence is the enemy -- so failures are COUNTED and surfaced by
# get_status(), rather than being invisible.
# ============================================================

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

TRADE_SINK_VERSION = "1.0"

# Off unless enabled, so importing this module cannot change behaviour.
ENV_FLAG = "MONGO_TRADE_SINK"

_STATS: Dict[str, int] = {
    "opens_written": 0, "opens_failed": 0,
    "points_written": 0, "points_failed": 0,
    "closes_written": 0, "closes_failed": 0,
}
_LOCK = threading.Lock()
_WARNED = False


def is_enabled() -> bool:
    """Whether trades are mirrored to Mongo. Default ON; set to 0 to disable."""
    return str(os.getenv(ENV_FLAG, "1")).strip().lower() not in ("0", "false", "no", "off")


def _service():
    from core.mongo import get_trades_service
    return get_trades_service()


def _count(key: str) -> None:
    with _LOCK:
        _STATS[key] = _STATS.get(key, 0) + 1


def _warn_once(exc: Exception) -> None:
    """
    Log the first failure loudly, then stay quiet.

    A per-trade log line from a broken database would flood the monitor's
    output and hide the trading messages that matter. The counters in
    get_status() carry the ongoing truth.
    """
    global _WARNED
    if not _WARNED:
        _WARNED = True
        logger.error("Mongo trade sink failing (further errors suppressed; "
                     "see get_status): %s", exc)


# ============================================================
# WRITE PATHS
# ============================================================

def record_open(trade_data: Mapping[str, Any],
                analysis_at_open: Optional[Mapping[str, Any]] = None) -> bool:
    """
    Mirror a newly opened trade.

    Upsert, not insert: the monitor can retry after a timeout, and one
    position must never become two records.
    """
    if not is_enabled():
        return False
    try:
        ticket = trade_data.get("ticket")
        if not ticket:
            return False
        document = dict(trade_data)
        document["status"] = document.get("status") or "OPEN"
        if analysis_at_open:
            document["analysis_at_open"] = dict(analysis_at_open)
        # price_evolution is seeded empty and grown by $push, so a retry of
        # this call cannot wipe points already recorded.
        document.setdefault("price_evolution", [])
        _service().upsert_trade(document)
        _count("opens_written")
        return True
    except Exception as exc:
        _count("opens_failed")
        _warn_once(exc)
        return False


def record_price_point(ticket: Any, point: Mapping[str, Any]) -> bool:
    """
    Mirror one price-evolution point.

    `$push`, so this is O(1) and atomic regardless of how many points the
    trade already holds.
    """
    if not is_enabled():
        return False
    try:
        service = _service()
        try:
            service.append_price_point(ticket, point)
        except Exception:
            # The trade may not be mirrored yet (the sink was enabled
            # mid-trade, or the open write failed). Create a stub so the
            # forward walk is captured from here rather than discarded --
            # a partial walk is worth far more than none.
            service.upsert_trade({"ticket": ticket, "status": "OPEN",
                                  "price_evolution": []})
            service.append_price_point(ticket, point)
        _count("points_written")
        return True
    except Exception as exc:
        _count("points_failed")
        _warn_once(exc)
        return False


def record_close(ticket: Any, close_data: Mapping[str, Any],
                 analysis_at_close: Optional[Mapping[str, Any]] = None) -> bool:
    """Mirror the close record and the closing analysis."""
    if not is_enabled():
        return False
    try:
        service = _service()
        try:
            service.close_trade(ticket, close_data, analysis_at_close)
        except Exception:
            service.upsert_trade({"ticket": ticket, "status": "OPEN"})
            service.close_trade(ticket, close_data, analysis_at_close)
        _count("closes_written")
        return True
    except Exception as exc:
        _count("closes_failed")
        _warn_once(exc)
        return False


def record_trailing_stop(ticket: Any, trailing: Mapping[str, Any]) -> bool:
    """Mirror a trailing-stop move. Never raises into the trading loop."""
    if not is_enabled():
        return False
    try:
        _service().update_trailing_stop(ticket, trailing)
        _count("trailing_written")
        return True
    except Exception as exc:
        _count("trailing_failed")
        _warn_once(exc)
        return False


def record_analysis_at_close(ticket: Any, analysis: Mapping[str, Any]) -> bool:
    """Attach the closing analysis to a trade. Never raises into the loop."""
    if not is_enabled() or not analysis:
        return False
    try:
        _service().update_trade(ticket, {"analysis_at_close": dict(analysis)})
        _count("analysis_at_close_written")
        return True
    except Exception as exc:
        _count("analysis_at_close_failed")
        _warn_once(exc)
        return False


# ============================================================
# READ PATH
# ============================================================

def get_trade_record(ticket: Any) -> Optional[Dict[str, Any]]:
    """The stored trade, or None -- when it does not exist OR cannot be read.

    Replaces `firebase_service.get_trade()`, which the monitor used to decide
    things: whether a trade is already closed (to skip a duplicate close write
    and stop recording price points), and which direction it was opened in.
    Trades have not been written to Firestore for a long time, so every one of
    those lookups returned nothing -- the duplicate-close guard could never
    fire, and the direction lookup always fell through to its fallback.

    Returns None rather than raising, to keep the contract the callers were
    written against (`if existing and existing.get("status") == "CLOSED"`).
    An unreachable store therefore reads as "not found", which fails OPEN: the
    monitor proceeds with the write rather than skipping it. That is the safe
    direction here -- a redundant close write is idempotent, a skipped one
    loses the trade's result.
    """
    if not ticket:
        return None
    try:
        from core.mongo.trades_service import TradeNotFound
        try:
            return _service().get_trade(ticket)
        except TradeNotFound:
            return None
    except Exception as exc:
        _count("reads_failed")
        _warn_once(exc)
        return None


# ============================================================
# STATUS
# ============================================================

def get_status() -> Dict[str, Any]:
    """
    What the sink has managed to write, and whether Mongo is reachable.

    The failure counters are the point: this module deliberately swallows
    exceptions so trading cannot be interrupted, which would make a broken
    mirror invisible without them.
    """
    status: Dict[str, Any] = {
        "component": "trade_sink",
        "version": TRADE_SINK_VERSION,
        "enabled": is_enabled(),
        "stats": dict(_STATS),
    }
    failures = sum(v for k, v in _STATS.items() if k.endswith("_failed"))
    written = sum(v for k, v in _STATS.items() if k.endswith("_written"))
    status["failures"] = failures
    status["written"] = written
    status["degraded"] = failures > 0
    if is_enabled():
        try:
            status["mongo_healthy"] = _service().is_healthy()
        except Exception as exc:
            status["mongo_healthy"] = False
            status["error"] = str(exc)
    return status


def reset_stats() -> None:
    """Clear the counters. For tests."""
    global _WARNED
    with _LOCK:
        for key in _STATS:
            _STATS[key] = 0
    _WARNED = False
