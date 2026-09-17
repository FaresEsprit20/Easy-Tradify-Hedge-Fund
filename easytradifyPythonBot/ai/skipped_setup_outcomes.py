# ai/skipped_setup_outcomes.py
"""
What the setups the engine declined would have done.

core/skipped_setups.py records every live setup that reached the strategy-group
decision and was not entered, with its planned stop, target and skip reason.
Once a record is HORIZON_HOURS old, this reads the real tick path (MT5 tick
history -- market data, so it works for any account) and stores:

  market_5atr     which 5-ATR barrier price touched first: +1 up, -1 down, 0 none
  direction_right whether that agreed with the side the setup would have taken
  replay_result   TARGET / STOP / TIMEOUT for the planned bracket
  gross_r         the bracket's result in R, before costs
  net_r           after commission ($7.03/FX lot, $0.04/share round trip)

and `report()` summarises it per skip reason, so each gate is judged on the
trades it stopped:  a gate whose skipped setups would have made money is
costing trades; one whose skipped setups lose is earning its place.

    python -m ai.skipped_setup_outcomes            # fill due outcomes, print the report
    python -m ai.skipped_setup_outcomes --report   # report only
"""

from __future__ import annotations

import argparse
import logging
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

logger = logging.getLogger(__name__)

HORIZON_HOURS = 8
ATR_BARRIER = 5.0
COMMISSION_PER_LOT = 7.03
COMMISSION_PER_SHARE = 0.04
MIN_GROUP = 10


def evaluate(doc: Mapping[str, Any], t: np.ndarray, bid: np.ndarray, ask: np.ndarray,
             pip: float) -> Optional[Dict[str, Any]]:
    """Outcome of one skipped setup on its tick path (t = UTC seconds)."""
    from ai.trade_forensics import barrier

    direction = str(doc.get("direction") or "").upper()
    entry, stop, target = doc.get("entry_price"), doc.get("stop_loss"), doc.get("take_profit")
    if direction not in ("BUY", "SELL") or t.size < 3 or not pip:
        return None
    sign = 1 if direction == "BUY" else -1
    mid = (bid + ask) / 2
    out: Dict[str, Any] = {"filled_at": datetime.now(timezone.utc), "ticks": int(t.size)}

    atr = doc.get("atr_pips")
    if isinstance(atr, (int, float)) and atr > 0:
        path = (mid - mid[0]) / (atr * pip)
        up = np.argmax(path >= ATR_BARRIER) if (path >= ATR_BARRIER).any() else None
        dn = np.argmax(path <= -ATR_BARRIER) if (path <= -ATR_BARRIER).any() else None
        move = 0 if up is None and dn is None else (1 if dn is None or (up is not None and up < dn) else -1)
        out["market_5atr"] = move
        out["direction_right"] = None if move == 0 else move == sign

    if all(isinstance(v, (int, float)) and v for v in (entry, stop, target)):
        risk = abs(entry - stop)
        if risk > 0:
            exit_px = bid if sign > 0 else ask
            fav = sign * (exit_px - entry) / risk
            target_r = abs(target - entry) / risk
            r, seconds, how = barrier(fav, t, 1.0, target_r, 0.0)
            out.update(replay_result=how, gross_r=round(r, 4), seconds_to_exit=round(seconds, 1))
            lots, risk_usd = doc.get("lot_size"), doc.get("risk_usd")
            if isinstance(lots, (int, float)) and isinstance(risk_usd, (int, float)) and risk_usd > 0:
                share = str(doc.get("symbol", "")).upper().endswith((".NAS", ".NYSE"))
                commission_r = lots * (COMMISSION_PER_SHARE if share else COMMISSION_PER_LOT) / risk_usd
                out["net_r"] = round(r - commission_r, 4)
    return out


def _load_ticks(doc: Mapping[str, Any]):
    from ai.trade_forensics import load_ticks

    cache_id = "skip_" + re.sub(r"[^A-Za-z0-9]+", "_", str(doc["key"]))
    start = doc["minute_utc"]
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return load_ticks(cache_id, doc["symbol"], start, hours=HORIZON_HOURS)


def fill(collection=None, limit: int = 500) -> Dict[str, int]:
    """Fill outcomes for records old enough to have a full horizon."""
    from core.broker_facts import pip_size
    from core.skipped_setups import _collection

    col = collection if collection is not None else _collection()
    due = datetime.now(timezone.utc) - timedelta(hours=HORIZON_HOURS)
    stats = {"filled": 0, "no_ticks": 0, "not_evaluable": 0}
    for doc in col.find({"outcome": None, "minute_utc": {"$lte": due}}).limit(limit):
        ticks = _load_ticks(doc)
        if ticks is None:
            col.update_one({"_id": doc["_id"]}, {"$set": {"outcome": {"error": "no tick history"}}})
            stats["no_ticks"] += 1
            continue
        outcome = evaluate(doc, *ticks, pip=pip_size(doc["symbol"]) or 0.0001)
        if outcome is None:
            col.update_one({"_id": doc["_id"]}, {"$set": {"outcome": {"error": "not evaluable"}}})
            stats["not_evaluable"] += 1
            continue
        col.update_one({"_id": doc["_id"]}, {"$set": {"outcome": outcome}})
        stats["filled"] += 1
    return stats


def _reason_family(reason: str) -> str:
    """Group free-text reasons by the gate that produced them."""
    text = str(reason or "").upper()
    for key in ("CONVICTION", "SYMBOLIC", "POOR DISCOUNT", "POOR TIMING", "EXTREME VOLATILITY",
                "WICK REVERSAL", "BELOW THE", "PRICE TO REACH DISCOUNT", "DO NOTHING", "NO POTENTIAL",
                "INVALID ZONE", "SPREAD", "SESSION", "NEWS"):
        if key in text:
            return key
    return text[:40] or "UNKNOWN"


def report(collection=None) -> List[Dict[str, Any]]:
    from core.skipped_setups import _collection

    col = collection if collection is not None else _collection()
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for doc in col.find({"outcome.filled_at": {"$exists": True}}):
        groups[_reason_family(doc.get("skip_reason"))].append(doc)
    rows = []
    for reason, docs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        voted = [d["outcome"]["direction_right"] for d in docs if d["outcome"].get("direction_right") is not None]
        nets = [d["outcome"]["net_r"] for d in docs if d["outcome"].get("net_r") is not None]
        rows.append({
            "gate": reason, "skipped": len(docs),
            "direction_right_pct": round(100 * sum(voted) / len(voted), 1) if voted else None,
            "would_be_net_r": round(statistics.mean(nets), 3) if nets else None,
            "would_be_total_r": round(sum(nets), 1) if nets else None,
            "small_sample": len(docs) < MIN_GROUP,
        })
    return rows


def get_status() -> Dict[str, Any]:
    return {"component": "skipped_setup_outcomes", "horizon_hours": HORIZON_HOURS}


if __name__ == "__main__":
    logging.disable(logging.WARNING)
    parser = argparse.ArgumentParser(description="Outcomes of the setups the engine declined")
    parser.add_argument("--report", action="store_true", help="only print the report")
    args = parser.parse_args()
    if not args.report:
        print("fill:", fill())
    for row in report():
        print(row)
