# ai/data_reconciliation.py
"""
Does MongoDB hold every trade the account actually made? (strategic_plan_v5, phase 0)

Two jobs:

  reconcile()        every CLOSED MT5 position in the window, matched to its Mongo
                     trade by ticket, and graded:
                       ok               trade, open snapshot, price points, close,
                                        engine stamp all present
                       missing          no Mongo trade at all
                       not_closed       Mongo still says OPEN
                       no_snapshot      no analysis_at_open.m1_analysis_raw
                       no_points        no price_evolution
                       no_engine        no engine stamp (recorded before stamping)
                     The report is written to logs/reconciliation/<date>.json.

  import_history()   MT5 closed positions into `mt5_history_trades` (source
                     mt5_history: result and costs only, no snapshot), so the
                     trades made before Mongo recording are counted without
                     being mixed into the live `trades` collection.

    python -m ai.data_reconciliation              # reconcile the last 7 days
    python -m ai.data_reconciliation --import     # also import 90 days of history
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

HISTORY_COLLECTION = "mt5_history_trades"
REPORT_DIR = Path(__file__).resolve().parents[1] / "logs" / "reconciliation"


def grade(position: Mapping[str, Any], trade: Optional[Mapping[str, Any]]) -> str:
    if not trade:
        return "missing"
    if str(trade.get("status") or "").upper() != "CLOSED":
        return "not_closed"
    if not ((trade.get("analysis_at_open") or {}).get("m1_analysis_raw")):
        return "no_snapshot"
    if not (trade.get("price_evolution_count") or trade.get("price_evolution")):
        return "no_points"
    if not trade.get("engine"):
        return "no_engine"
    return "ok"


def reconcile(days: int = 7, positions: Optional[Sequence[Mapping[str, Any]]] = None,
              trades=None, write: bool = True) -> Dict[str, Any]:
    """Grade every closed MT5 position in the window against MongoDB."""
    if positions is None:
        from ai.mt5_history import load_positions
        positions = load_positions(days=days)
    if trades is None:
        from core.mongo import get_trades_service
        trades = get_trades_service().collection

    tickets = [p["position_id"] for p in positions]
    projection = {"ticket": 1, "status": 1, "engine": 1, "price_evolution_count": 1,
                  "analysis_at_open.m1_analysis_raw.success": 1, "opened_at": 1}
    found: Dict[Any, Mapping[str, Any]] = {}
    for doc in trades.find({"ticket": {"$in": tickets}}, projection):
        found[doc.get("ticket")] = doc

    grades: Dict[str, List[Any]] = {}
    for p in positions:
        trade = found.get(p["position_id"])
        if trade is not None and "analysis_at_open" in trade:
            # the projection returns the nested flag; grade only needs presence
            trade = {**trade, "analysis_at_open": {"m1_analysis_raw": trade["analysis_at_open"].get("m1_analysis_raw")}}
        grades.setdefault(grade(p, trade), []).append(p["position_id"])

    net = [float(p.get("profit", 0)) + float(p.get("commission", 0)) + float(p.get("swap", 0)) for p in positions]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "mt5_closed_positions": len(positions),
        "mt5_won": sum(1 for n in net if n > 0),
        "mt5_net_usd": round(sum(net), 2),
        "counts": {k: len(v) for k, v in grades.items()},
        "tickets": {k: v[:200] for k, v in grades.items() if k != "ok"},
        "complete": set(grades) <= {"ok"},
    }
    if write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.json"
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        report["path"] = str(path)
    return report


def import_history(days: int = 90, positions: Optional[Sequence[Mapping[str, Any]]] = None,
                   collection=None) -> Dict[str, int]:
    """Upsert closed MT5 positions into mt5_history_trades (results and costs, no snapshot)."""
    from ai.mt5_history import to_trade

    if positions is None:
        from ai.mt5_history import load_positions
        positions = load_positions(days=days)
    if collection is None:
        from core.mongo import get_trades_service
        service = get_trades_service()
        collection = service.client[service.config.database][HISTORY_COLLECTION]
        collection.create_index("trade_id", unique=True)

    written = 0
    for p in positions:
        doc = to_trade(p)
        doc["costs"] = {"commission_usd": p.get("commission"), "swap_usd": p.get("swap")}
        doc["net_usd"] = round(float(p.get("profit", 0)) + float(p.get("commission", 0)) + float(p.get("swap", 0)), 2)
        doc["imported_at"] = datetime.now(timezone.utc)
        collection.update_one({"trade_id": doc["trade_id"]}, {"$set": doc}, upsert=True)
        written += 1
    return {"imported": written}


def get_status() -> Dict[str, Any]:
    return {"component": "data_reconciliation", "history_collection": HISTORY_COLLECTION,
            "report_dir": str(REPORT_DIR)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--import", dest="do_import", action="store_true")
    args = ap.parse_args(argv)
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        print(json.dumps(reconcile(days=args.days), indent=1))
        if args.do_import:
            print(import_history(days=90))
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
