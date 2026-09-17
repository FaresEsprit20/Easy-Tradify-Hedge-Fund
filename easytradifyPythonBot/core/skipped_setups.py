# ============================================================
# SKIPPED SETUPS -- record what the engine declined, so gates can be measured
# ============================================================
# FILE: core/skipped_setups.py
#
# MongoDB holds only the trades that were TAKEN. Once the strategy groups made
# probability a real filter, the decisions that matter moved to the gates after
# it: "poor discount", "poor timing", wick reversal, the volatility veto,
# conviction. A gate cannot be judged on the trades it let through -- only on
# the ones it stopped. This records those.
#
# One document per symbol per UTC minute (upserted; the latest analysis in the
# minute wins, `seen_count` says how many there were). Only live analyses that
# reached the strategy-group decision and did NOT enter are recorded; replays
# and already-open positions are not. It never raises into the analysis.
#
# ai/skipped_setup_outcomes.py later fills in what each skipped setup would have
# done on the real tick path.
# ============================================================

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

SKIPPED_SETUPS_VERSION = "1.0"
ENV_FLAG = "SKIPPED_SETUP_RECORDER"
COLLECTION = "skipped_setups"

_warned = False
_indexed = False


def is_enabled() -> bool:
    """On by default; set SKIPPED_SETUP_RECORDER=0 to disable."""
    return str(os.getenv(ENV_FLAG, "1")).strip().lower() not in ("0", "false", "no", "off")


def _get(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, Mapping):
            return None
        d = d.get(key)
    return d


def entered(result: Mapping[str, Any]) -> bool:
    """The monitor's own entry signal: entry_analysis.should_enter.

    (final_verdict carries no `should_enter`; the monitor reads the entry
    analysis, so that is what decides whether a setup was taken.)
    """
    return bool(_get(result, "entry_analysis", "should_enter"))


def skip_reason(result: Mapping[str, Any]) -> str:
    """The most specific reason available, in the order the gates run."""
    fv = result.get("final_verdict") or {}
    if fv.get("conviction_declined"):
        return f"CONVICTION: {fv.get('conviction_reason')}"
    if fv.get("symbolic_blocked"):
        return f"SYMBOLIC: {fv.get('symbolic_reason')}"
    verdict = (fv.get("verdict") or _get(result, "entry_analysis", "final_decision")
               or result.get("🎯 FINAL_DECISION") or "")
    return str(verdict).strip() or "UNKNOWN"


def build_record(result: Mapping[str, Any], symbol: str,
                 now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The document to store, or None when this analysis is not a skipped setup."""
    if not isinstance(result, Mapping) or not result.get("success", True):
        return None
    groups = result.get("strategy_groups") or {}
    if not groups.get("enabled") or groups.get("final_probability") is None:
        return None
    if entered(result):
        return None

    now = now or datetime.now(timezone.utc)
    minute = now.replace(second=0, microsecond=0)
    fv = result.get("final_verdict") or {}
    ed = result.get("entry_details") or {}
    direction = _get(result, "direction_decision", "traded_direction") or fv.get("action")
    return {
        "key": f"{symbol}|{minute.isoformat()}",
        "symbol": symbol,
        "minute_utc": minute,
        "analyzed_at": now,
        "direction": direction,
        "analysis_direction": _get(result, "direction_decision", "analysis_direction"),
        "entry_price": fv.get("entry_price") or ed.get("entry_price"),
        "stop_loss": fv.get("stop_loss") or ed.get("stop_loss"),
        "take_profit": fv.get("take_profit_1") or ed.get("take_profit_1"),
        "stop_loss_pips": ed.get("stop_loss_pips") or fv.get("stop_loss_pips"),
        "take_profit_pips": ed.get("take_profit_pips") or fv.get("take_profit_pips"),
        "lot_size": ed.get("lot_size") or fv.get("lot_size"),
        "risk_usd": ed.get("risk_usd") or fv.get("risk_usd"),
        "spread_pips": _get(result, "global_anticheat", "spread_pips"),
        "atr_pips": _get(result, "volatility_protection", "atr_pips"),
        "probability": groups.get("final_probability"),
        "entry_floor": _get(result, "config", "min_probability_for_entry"),
        "winner_group": groups.get("winner"),
        "most_opposed_group": groups.get("most_opposed"),
        "group_scores": {name: g.get("score") for name, g in (groups.get("groups") or {}).items()
                         if isinstance(g, Mapping) and g.get("scored")},
        "other_side_probability": _get(groups, "other_side", "final_probability"),
        "cost": groups.get("cost"),
        "skip_reason": skip_reason(result),
        "entry_status": _get(result, "entry_analysis", "entry_status"),
        "veto_reason": _get(result, "vetos", "reason"),
        "conviction_passed": _get(result, "conviction", "passed"),
        "conviction_score": _get(result, "conviction", "conviction_score"),
        "version": SKIPPED_SETUPS_VERSION,
        "engine": _engine(),
    }


def _engine() -> Optional[Dict[str, Any]]:
    """Which engine produced the record (strategic_plan_v5 rule 2: never pool eras)."""
    try:
        from core.engine_version import short_stamp
        return short_stamp()
    except Exception:
        return None


def _collection():
    global _indexed
    from core.mongo import get_trades_service

    service = get_trades_service()
    col = service.client[service.config.database][COLLECTION]
    if not _indexed:
        col.create_index("key", unique=True)
        col.create_index([("minute_utc", 1)])
        col.create_index([("outcome", 1), ("minute_utc", 1)])
        _indexed = True
    return col


def record(result: Mapping[str, Any], *, symbol: str, is_replay: bool,
           is_already_in_trade: bool, collection=None) -> bool:
    """Store the analysis if it is a skipped live setup. Never raises."""
    global _warned
    if is_replay or is_already_in_trade or not is_enabled():
        return False
    try:
        doc = build_record(result, symbol)
        if doc is None:
            return False
        col = collection if collection is not None else _collection()
        first_seen = doc.pop("analyzed_at")
        col.update_one(
            {"key": doc["key"]},
            {"$set": {**doc, "last_seen": first_seen},
             "$setOnInsert": {"first_seen": first_seen, "outcome": None},
             "$inc": {"seen_count": 1}},
            upsert=True,
        )
        return True
    except Exception as exc:
        if not _warned:
            logger.warning(f"[SKIPPED SETUPS] recording unavailable ({exc}); continuing without it")
            _warned = True
        return False


def get_status() -> Dict[str, Any]:
    return {"component": "skipped_setups", "version": SKIPPED_SETUPS_VERSION, "enabled": is_enabled()}
