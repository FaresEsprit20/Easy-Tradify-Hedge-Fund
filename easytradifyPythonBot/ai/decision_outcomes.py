# ai/decision_outcomes.py
"""
Results for the decision log (strategic_plan_v5_live_data.md, phase 2).

core/decision_log.py stores every live decision with its snapshot codes. Once a
decision is older than the holding window, this reads the real MT5 tick path
after it and stores, in `decision_outcomes` (never inside the decision):

  engine        the engine's own trade: its side, its stop and target distances
                re-anchored to the first quote after the decision (the executor
                re-anchors the same way), true bid/ask, commission in R
  grid          fixed geometries on BOTH sides (the other side is the
                random-side control):
                  scalp      stop 1x/2x ATR(M1) and 1x ATR(M5), target 0.5/1/2R
                  precision  stop 1x ATR(M15) and 1x ATR(H1), target 1/2R
  path          best (MFE) and worst (MAE) move in R of the engine stop after
                5, 15, 60 and 240 minutes

Rules the walk keeps (the same as every gate test):
  * entry is the first quote AFTER the decision time; nothing before it is read
  * a buy fills on the ask and exits on the bid, a sell the other way round
  * a stop fills at the quote that crossed it (gaps fill worse); a target fills
    at its level
  * no stop or target within HOLD_MINUTES: exit at the last quote of the window
  * risk is the operator's fixed $4, so R does not depend on the lot; commission
    in R comes from engine_v2 symbol facts (None when a symbol has no facts)

Ticks come only for symbols already in Market Watch: this module never calls
symbol_select.

    python -m ai.decision_outcomes            # fill due decisions, print counts
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import product
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

LABEL_VERSION = "1.0"
COLLECTION = "decision_outcomes"
HOLD_MINUTES = 240
DUE_MARGIN_MINUTES = 5
MAX_ENTRY_DELAY_SECONDS = 120
CHUNK_HOURS = 4
PATH_MINUTES = (5, 15, 60, 240)
ATR_BARS = 14
SCALP_STOPS = (("M1", 1.0), ("M1", 2.0), ("M5", 1.0))
SCALP_TARGETS = (0.5, 1.0, 2.0)
PRECISION_STOPS = (("M15", 1.0), ("H1", 1.0))
PRECISION_TARGETS = (1.0, 2.0)
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


# ------------------------------------------------------------------ the walk
def walk(t: np.ndarray, bid: np.ndarray, ask: np.ndarray, i: int, side: str,
         stop_dist: float, target_dist: float, hold_seconds: float,
         commission_r: Optional[float]) -> Optional[Dict[str, Any]]:
    """One bracket from quote i. Returns how it ended and its result in R."""
    if side not in ("BUY", "SELL") or not (stop_dist > 0) or not (target_dist > 0) or i >= t.size:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    fill = ask[i] if side == "BUY" else bid[i]
    end = int(np.searchsorted(t, t[i] + hold_seconds, side="right"))
    exits = (bid if side == "BUY" else ask)[i + 1:end]
    if exits.size == 0:
        r, how, seconds = 0.0, "NO_QUOTES", 0.0
    else:
        rel = sign * (exits - fill)
        stop_hit = np.flatnonzero(rel <= -stop_dist)
        target_hit = np.flatnonzero(rel >= target_dist)
        k_stop = int(stop_hit[0]) if stop_hit.size else None
        k_target = int(target_hit[0]) if target_hit.size else None
        if k_stop is None and k_target is None:
            r, how, k = float(rel[-1] / stop_dist), "TIMEOUT", exits.size - 1
        elif k_target is None or (k_stop is not None and k_stop <= k_target):
            r, how, k = float(rel[k_stop] / stop_dist), "STOP", k_stop
        else:
            r, how, k = float(target_dist / stop_dist), "TARGET", k_target
        seconds = float(t[i + 1 + k] - t[i])
    return {"how": how, "r_gross": round(r, 4),
            "r_net": None if commission_r is None else round(r - commission_r, 4),
            "seconds": round(seconds, 1)}


def path_extremes(t: np.ndarray, bid: np.ndarray, ask: np.ndarray, i: int, side: str,
                  unit: float, minutes: Sequence[int] = PATH_MINUTES) -> Dict[str, Any]:
    """Best and worst move in R (exit side against the fill) after each horizon."""
    if side not in ("BUY", "SELL") or not (unit > 0) or i >= t.size:
        return {}
    sign = 1.0 if side == "BUY" else -1.0
    fill = ask[i] if side == "BUY" else bid[i]
    exits = bid if side == "BUY" else ask
    out: Dict[str, Any] = {}
    for m in minutes:
        end = int(np.searchsorted(t, t[i] + m * 60, side="right"))
        window = exits[i + 1:end]
        if window.size == 0:
            out[f"mfe_{m}"] = out[f"mae_{m}"] = None
            continue
        rel = sign * (window - fill) / unit
        out[f"mfe_{m}"] = round(float(rel.max()), 4)
        out[f"mae_{m}"] = round(float(rel.min()), 4)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_BARS) -> Optional[float]:
    """Mean true range of the last n closed bars."""
    if close.size < n + 1:
        return None
    prev = close[:-1]
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    value = float(np.mean(tr[-n:]))
    return value if value > 0 else None


def evaluate(decision: Mapping[str, Any], t: np.ndarray, bid: np.ndarray, ask: np.ndarray,
             pip: Optional[float], atrs: Mapping[str, Optional[float]],
             commission_r_of=None) -> Dict[str, Any]:
    """The outcome document for one decision on its tick path (t = UTC seconds)."""
    decided_at = _epoch(decision.get("decided_at") or decision.get("last_seen") or decision.get("minute_utc"))
    out: Dict[str, Any] = {"decision_key": decision.get("key"), "symbol": decision.get("symbol"),
                           "decided_at": decided_at, "label_version": LABEL_VERSION,
                           "engine": decision.get("engine")}
    if decided_at is None or t.size == 0:
        return {**out, "status": "no_ticks"}
    i = int(np.searchsorted(t, decided_at, side="left"))
    if i >= t.size or t[i] - decided_at > MAX_ENTRY_DELAY_SECONDS:
        return {**out, "status": "no_quote_after_decision"}
    commission_r_of = commission_r_of or (lambda distance: None)
    hold = HOLD_MINUTES * 60
    out.update(status="ok", entry_seconds_after_decision=round(float(t[i] - decided_at), 3),
               entry_bid=float(bid[i]), entry_ask=float(ask[i]))

    side = str(decision.get("direction") or "").upper()
    stop_pips, target_pips = decision.get("stop_loss_pips"), decision.get("take_profit_pips")
    engine_stop = None
    if pip and isinstance(stop_pips, (int, float)) and isinstance(target_pips, (int, float)) \
            and stop_pips > 0 and target_pips > 0 and side in ("BUY", "SELL"):
        engine_stop, engine_target = stop_pips * pip, target_pips * pip
        out["engine"] = {**(decision.get("engine") or {}), "side": side, "stop_distance": engine_stop,
                         "target_r": round(engine_target / engine_stop, 4),
                         "result": walk(t, bid, ask, i, side, engine_stop, engine_target, hold,
                                        commission_r_of(engine_stop))}

    grid: Dict[str, Any] = {}
    for arena, stops, targets in (("scalp", SCALP_STOPS, SCALP_TARGETS),
                                  ("precision", PRECISION_STOPS, PRECISION_TARGETS)):
        for (tf, k), target_r, grid_side in product(stops, targets, ("BUY", "SELL")):
            unit = atrs.get(tf)
            if not unit:
                continue
            stop = k * unit
            grid[f"{arena}|{tf}x{k:g}|{target_r:g}R|{grid_side}"] = walk(
                t, bid, ask, i, grid_side, stop, target_r * stop, hold, commission_r_of(stop))
    out["grid"] = grid
    out["atr"] = {tf: v for tf, v in atrs.items()}

    unit = engine_stop or atrs.get("M1")
    if side in ("BUY", "SELL") and unit:
        out["path"] = {"unit": "engine_stop" if engine_stop else "atr_M1",
                       **path_extremes(t, bid, ask, i, side, unit)}
    return out


# ------------------------------------------------------------------ market data
def _epoch(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _selected(mt5, symbol: str) -> bool:
    info = mt5.symbol_info(symbol)
    return bool(info is not None and info.select)


def load_ticks(symbol: str, start_utc: datetime, end_utc: datetime):
    """(t UTC seconds, bid, ask) between two UTC datetimes; None if unavailable."""
    import MetaTrader5 as mt5
    from core.broker_facts import broker_offset_seconds

    if not _selected(mt5, symbol):
        return None
    offset = broker_offset_seconds(start_utc)
    ticks = mt5.copy_ticks_range(symbol, start_utc + timedelta(seconds=offset),
                                 end_utc + timedelta(seconds=offset), mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return None
    t = ticks["time_msc"].astype(np.float64) / 1000.0 - offset
    bid, ask = ticks["bid"].astype(np.float64), ticks["ask"].astype(np.float64)
    for arr in (bid, ask):          # one-sided updates carry the other side as 0
        valid = arr > 0
        if not valid.any():
            return None
        idx = np.where(valid, np.arange(arr.size), 0)
        np.maximum.accumulate(idx, out=idx)
        arr[:] = arr[idx]
    keep = (bid > 0) & (ask > 0)
    return t[keep], bid[keep], ask[keep]


def load_atrs(symbol: str, decided_at_utc: datetime) -> Dict[str, Optional[float]]:
    """ATR of the closed bars before the decision, per timeframe."""
    import MetaTrader5 as mt5
    from core.broker_facts import broker_offset_seconds

    offset = broker_offset_seconds(decided_at_utc)
    now_broker = decided_at_utc + timedelta(seconds=offset)
    frames = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    out: Dict[str, Optional[float]] = {}
    for name, frame in frames.items():
        seconds = TF_SECONDS[name]
        rates = mt5.copy_rates_range(symbol, frame, now_broker - timedelta(seconds=seconds * (ATR_BARS + 30)),
                                     now_broker)
        if rates is None or len(rates) == 0:
            out[name] = None
            continue
        closed = rates[rates["time"] + seconds <= now_broker.timestamp()]
        out[name] = atr(closed["high"].astype(float), closed["low"].astype(float),
                        closed["close"].astype(float)) if len(closed) else None
    return out


def _commission_r_of(symbol: str):
    try:
        from engine_v2.data.symbols import facts
        f = facts(symbol)
    except Exception:
        return lambda distance: None
    return lambda distance: round(f.commission_r(distance), 4) if distance and distance > 0 else None


# ------------------------------------------------------------------ fill
def _collections():
    from core.mongo import get_trades_service
    service = get_trades_service()
    db = service.client[service.config.database]
    outcomes = db[COLLECTION]
    outcomes.create_index("decision_key", unique=True)
    outcomes.create_index([("symbol", 1), ("decided_at", 1)])
    return db["decisions"], outcomes


def _decided(doc: Mapping[str, Any]) -> datetime:
    """When the stored snapshot was taken, as an aware UTC datetime."""
    value = doc.get("decided_at") or doc.get("last_seen") or doc.get("minute_utc")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _chunks(docs: Sequence[Mapping[str, Any]]) -> Iterable[List[Mapping[str, Any]]]:
    """Consecutive decisions of one symbol whose windows fit one tick read."""
    chunk: List[Mapping[str, Any]] = []
    for doc in docs:
        if chunk and _epoch(_decided(doc)) - _epoch(_decided(chunk[0])) > CHUNK_HOURS * 3600:
            yield chunk
            chunk = []
        chunk.append(doc)
    if chunk:
        yield chunk


def fill(limit: int = 5000, decisions=None, outcomes=None, now: Optional[datetime] = None) -> Dict[str, int]:
    """Label every decision whose holding window has passed."""
    import MetaTrader5 as mt5
    from core.broker_facts import pip_size

    if decisions is None or outcomes is None:
        decisions, outcomes = _collections()
    now = now or datetime.now(timezone.utc)
    due = now - timedelta(minutes=HOLD_MINUTES + DUE_MARGIN_MINUTES)
    stats: Dict[str, int] = defaultdict(int)
    if not mt5.initialize(timeout=20000):
        stats["mt5_unavailable"] += 1
        return dict(stats)

    pending = list(decisions.find({"outcome": None, "decided_at": {"$lte": due}},
                                  {"snapshot": 0, "order_flow": 0},
                                  sort=[("symbol", 1), ("decided_at", 1)]).limit(limit))
    by_symbol: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for doc in pending:
        by_symbol[doc["symbol"]].append(doc)

    for symbol, docs in by_symbol.items():
        pip = pip_size(symbol)
        commission_r_of = _commission_r_of(symbol)
        for chunk in _chunks(docs):
            first, last = _decided(chunk[0]), _decided(chunk[-1])
            ticks = load_ticks(symbol, first - timedelta(seconds=5),
                               last + timedelta(minutes=HOLD_MINUTES + 1))
            for doc in chunk:
                decided = _decided(doc)
                if ticks is None:
                    result = {"decision_key": doc["key"], "symbol": symbol, "status": "no_ticks",
                              "label_version": LABEL_VERSION}
                else:
                    result = evaluate(doc, *ticks, pip=pip, atrs=load_atrs(symbol, decided),
                                      commission_r_of=commission_r_of)
                result["computed_at"] = now
                outcomes.update_one({"decision_key": doc["key"]}, {"$set": result}, upsert=True)
                decisions.update_one({"_id": doc["_id"]}, {"$set": {"outcome": {
                    "status": result["status"], "label_version": LABEL_VERSION, "computed_at": now}}})
                stats[result["status"]] += 1
    return dict(stats)


def get_status() -> Dict[str, Any]:
    return {"component": "decision_outcomes", "label_version": LABEL_VERSION, "hold_minutes": HOLD_MINUTES,
            "collection": COLLECTION}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args(argv)
    print(fill(limit=args.limit))


if __name__ == "__main__":
    main()
