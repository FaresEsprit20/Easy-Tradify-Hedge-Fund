# ============================================================
# DECISION LOG -- the whole snapshot of every live decision, minute by minute
# ============================================================
# FILE: core/decision_log.py
#
# strategic_plan_v5_live_data.md, phase 1. MongoDB `trades` holds the trades
# that were TAKEN and `skipped_setups` a summary of the ones the gates stopped.
# Neither is enough to learn from: a handful of trades a week cannot reach the
# 300 out-of-sample decisions the pass line needs.
#
# This records, for every live analysis of a target market, one document per
# symbol, per UTC minute, per requested direction (AUTO scans and the BUY/SELL
# analyses of open positions are different decisions):
#
#   snapshot     the WHOLE analysis, encoded by ai/price_evolution_encoder
#                (compact decision codes for queries + full_analysis_z, the
#                lossless compressed snapshot). PriceEvolutionDecoder().decode()
#                gives back every field, list and detector block.
#   decided_at   when that snapshot was taken -- results are measured from here
#   order_flow   live tick order flow over the previous 15 minutes, taken once
#                per symbol-minute (core/microstructure_features): the input
#                price history cannot reconstruct
#   engine       which engine produced it (core/engine_version)
#   entered      whether any analysis in the minute entered
#   outcome      null until ai/decision_outcomes.py fills it from real ticks
#
# One snapshot per minute, not one per scan: the first analysis in the minute
# is stored, and replaced only if a later analysis in the same minute ENTERS, so
# the stored snapshot is always the one the decision came from. Later scans only
# move `last_seen` and `seen_count`. That keeps the encoding (compression and a
# lossless check, a few milliseconds) off every scan of the live loop.
#
# Target markets only: FX, metals, stock indices, oil. Stock CFDs (a dot in the
# symbol) and crypto are left out, as the target is. Live analyses only.
# Never raises.
# ============================================================

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

DECISION_LOG_VERSION = "2.0"
ENV_FLAG = "DECISION_LOG"
COLLECTION = "decisions"
ORDER_FLOW_LOOKBACK_SECONDS = 900

CRYPTO_PREFIXES = ("BTC", "ETH", "LTC", "XRP", "BCH", "XLM", "DOG", "SOL", "ADA", "DOT", "BNB",
                   "EOS", "XTZ", "LNK", "UNI", "AVAX", "MATIC", "TRX", "SHIB")

_warned = False
_indexed = False
_stored: Dict[str, bool] = {}           # key -> entered flag of the stored snapshot
_stored_minute: Optional[str] = None
_order_flow_taken: Dict[str, str] = {}  # symbol -> minute already measured
_encoder = None


def is_enabled() -> bool:
    """On by default; set DECISION_LOG=0 to disable."""
    return str(os.getenv(ENV_FLAG, "1")).strip().lower() not in ("0", "false", "no", "off")


def is_target_market(symbol: str) -> bool:
    """FX, metals, stock indices and oil -- not stock CFDs, not crypto."""
    name = str(symbol or "").upper()
    if not name or "." in name:
        return False
    return not name.startswith(CRYPTO_PREFIXES)


def _get(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, Mapping):
            return None
        d = d.get(key)
    return d


def _get_encoder():
    global _encoder
    if _encoder is None:
        from ai.price_evolution_encoder import PriceEvolutionEncoder
        _encoder = PriceEvolutionEncoder()
    return _encoder


def decision_key(result: Mapping[str, Any], symbol: str, minute: datetime) -> str:
    requested = str(_get(result, "config", "user_requested_direction") or "AUTO").upper()
    return f"{symbol}|{minute.isoformat()}|{requested}"


def build_record(result: Mapping[str, Any], symbol: str,
                 now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The full document (with the whole snapshot), or None when this is not a loggable decision."""
    if not isinstance(result, Mapping) or not result.get("success", False):
        return None
    if not is_target_market(symbol):
        return None

    from core.engine_version import short_stamp

    encoder = _get_encoder()
    safe = encoder.maps.make_json_safe(dict(result))
    now = now or datetime.now(timezone.utc)
    minute = now.replace(second=0, microsecond=0)
    fv = safe.get("final_verdict") or {}
    ed = safe.get("entry_details") or {}
    groups = safe.get("strategy_groups") or {}

    return {
        "key": decision_key(safe, symbol, minute),
        "symbol": symbol,
        "minute_utc": minute,
        "decided_at": now,
        "requested_direction": str(_get(safe, "config", "user_requested_direction") or "AUTO").upper(),
        "entered": bool(_get(safe, "entry_analysis", "should_enter")),
        "direction": _get(safe, "direction_decision", "traded_direction") or fv.get("best_direction"),
        "winner_group": groups.get("winner"),
        "probability": fv.get("probability_percent"),
        "entry_price": ed.get("entry_price") or fv.get("entry_price"),
        "stop_loss_pips": ed.get("stop_loss_pips") or fv.get("stop_loss_pips"),
        "take_profit_pips": ed.get("take_profit_pips") or fv.get("take_profit_pips"),
        "lot_size": ed.get("lot_size") or fv.get("lot_size"),
        "risk_usd": ed.get("risk_usd"),
        "spread_pips": ed.get("spread_pips"),
        "snapshot": encoder.encode(safe, compact=True),
        "snapshot_ok": bool((encoder.last_validation or {}).get("ok")),
        "engine": short_stamp(),
        "version": DECISION_LOG_VERSION,
    }


def _order_flow(symbol: str, minute_key: str) -> Optional[Dict[str, Any]]:
    """Tick order flow over the last 15 minutes, once per symbol-minute."""
    if _order_flow_taken.get(symbol) == minute_key:
        return None
    _order_flow_taken[symbol] = minute_key
    try:
        from core.broker_facts import pip_size
        from core.microstructure_features import analyse

        pip = pip_size(symbol)
        if not pip:
            return {"available": False, "reason": "no pip size"}
        return analyse(symbol, pip, lookback_seconds=ORDER_FLOW_LOOKBACK_SECONDS)
    except Exception as exc:
        return {"available": False, "reason": f"order flow failed: {exc}"}


def _collection():
    global _indexed
    from core.engine_version import register
    from core.mongo import get_trades_service

    service = get_trades_service()
    col = service.client[service.config.database][COLLECTION]
    if not _indexed:
        col.create_index("key", unique=True)
        col.create_index([("minute_utc", 1)])
        col.create_index([("symbol", 1), ("decided_at", 1)])
        col.create_index([("outcome", 1), ("decided_at", 1)])
        register()
        _indexed = True
    return col


def _remember(key: str, minute_iso: str, entered: bool) -> None:
    global _stored_minute
    if _stored_minute != minute_iso:
        # keep the previous minute too, for analyses that straddle the boundary
        previous = {k: v for k, v in _stored.items() if _stored_minute and _stored_minute in k}
        _stored.clear()
        _stored.update(previous)
        _stored_minute = minute_iso
    _stored[key] = entered


def record(result: Mapping[str, Any], *, symbol: str, is_replay: bool,
           is_already_in_trade: bool = False, collection=None,
           now: Optional[datetime] = None) -> bool:
    """Store a live decision. Never raises."""
    global _warned
    if is_replay or not is_enabled() or not is_target_market(symbol):
        return False
    try:
        if not isinstance(result, Mapping) or not result.get("success", False):
            return False
        now = now or datetime.now(timezone.utc)
        minute = now.replace(second=0, microsecond=0)
        key = decision_key(result, symbol, minute)
        entered = bool(_get(result, "entry_analysis", "should_enter"))
        col = collection if collection is not None else _collection()

        if key in _stored and not (entered and not _stored[key]):
            # the minute's snapshot is already stored: only count the scan
            col.update_one({"key": key}, {"$set": {"last_seen": now}, "$inc": {"seen_count": 1},
                                          "$max": {"entered": entered}})
            return True

        doc = build_record(result, symbol, now=now)
        if doc is None:
            return False
        doc["is_already_in_trade"] = bool(is_already_in_trade)
        update: Dict[str, Any] = {
            "$set": {**doc, "last_seen": now},
            "$setOnInsert": {"first_seen": now, "outcome": None},
            "$inc": {"seen_count": 1},
        }
        flow = _order_flow(symbol, minute.isoformat())
        if flow is not None:
            update["$set"]["order_flow"] = flow
        col.update_one({"key": key}, update, upsert=True)
        _remember(key, minute.isoformat(), entered)
        return True
    except Exception as exc:
        if not _warned:
            logger.warning(f"[DECISION LOG] recording unavailable ({exc}); continuing without it")
            _warned = True
        return False


def get_status() -> Dict[str, Any]:
    return {"component": "decision_log", "version": DECISION_LOG_VERSION, "enabled": is_enabled(),
            "collection": COLLECTION}
