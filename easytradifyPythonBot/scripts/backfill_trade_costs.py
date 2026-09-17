# scripts/backfill_trade_costs.py
"""
Fill spread_at_entry, risk_reward_ratio, close_data.exit_spread and
close_data.exit_slippage on stored trades.

WHY
---
None of the four was ever measured:

  spread_at_entry          None on every trade -- the writer read a key the
                           execution response never contained.
  risk_reward_ratio        None on every trade -- nothing ever assigned it.
  close_data.exit_spread   0.0 on every closed trade -- a hardcoded literal.
  close_data.exit_slippage 0.0 on every closed trade -- same literal.

The writers are fixed (core/broker_facts, monitor/firebase_helpers); this
brings the stored history into line.

SOURCES, IN ORDER OF PREFERENCE
-------------------------------
  risk_reward_ratio  computed from the trade's own stored entry/stop/target.
                     Exact: these are the prices the order was placed at.
  spread_at_entry    MT5 tick history at opened_at ("tick_history"), else the
                     analysis snapshot's spread ("analysis"). Tick history is
                     market data, so it covers trades from every account.
  exit_spread        MT5 tick history at closed_at ("tick_history").
  exit_slippage      fill vs the stop/target that triggered the close. None for
                     a manual or EA close -- there was no level to slip from.

WHAT IT WILL NOT TOUCH
----------------------
* A risk_reward_ratio or spread_at_entry that already has a value.
* Exit fields on any trade that carries `close_data.exit_spread_source` -- that
  marker is written only by the fixed close path, so its values are measured.
  Trades WITHOUT it were written by the old path, whose 0.0 is the literal.
* Nothing is estimated. Where no source exists the field stays None and the
  trade is listed.

Usage:
    python scripts/backfill_trade_costs.py            # dry run
    python scripts/backfill_trade_costs.py --apply    # write
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MetaTrader5 as mt5  # noqa: E402

from core.broker_facts import (exit_slippage_pips, risk_reward_ratio,  # noqa: E402
                               spread_at_pips)
from core.mongo.trades_service import get_trades_service  # noqa: E402

ANALYSIS_SPREAD = "analysis_at_open.m1_analysis_raw.entry_details.spread_pips"


def analysis_spread(doc):
    node = doc
    for part in ANALYSIS_SPREAD.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return None
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()} -- tick history unavailable.")
        print("Aborting rather than falling back silently for every trade.")
        return 1
    # No mt5.shutdown(): process exit releases this connection, and the live
    # monitor shares the terminal.

    col = get_trades_service().collection
    projection = {"trade_id": 1, "symbol": 1, "status": 1, "direction": 1,
                  "opened_at": 1, "closed_at": 1, "entry": 1, "close_data": 1,
                  "risk_reward_ratio": 1, "spread_at_entry": 1, ANALYSIS_SPREAD: 1}

    stats = Counter()
    unresolved = []
    updates = []

    for doc in col.find({"deleted_at": None}, projection):
        sets = {}
        symbol = doc.get("symbol")
        entry = doc.get("entry") or {}

        # ---- reward:risk ----
        if doc.get("risk_reward_ratio") is None:
            rr = risk_reward_ratio(entry.get("price"), entry.get("stop_loss"),
                                   entry.get("take_profit"))
            if rr is not None:
                sets["risk_reward_ratio"] = rr
                stats["rr_filled"] += 1
            else:
                stats["rr_unresolvable"] += 1

        # ---- entry spread ----
        if doc.get("spread_at_entry") is None:
            spread = spread_at_pips(symbol, doc.get("opened_at"))
            source = "tick_history"
            if spread is None:
                spread, source = analysis_spread(doc), "analysis"
            if spread is not None:
                sets["spread_at_entry"] = spread
                sets["spread_at_entry_source"] = source
                stats[f"entry_spread_{source}"] += 1
            else:
                stats["entry_spread_unresolved"] += 1
                unresolved.append((doc.get("trade_id"), symbol, "spread_at_entry"))

        # ---- exit spread + slippage (old close path only) ----
        close = doc.get("close_data")
        if doc.get("status") == "CLOSED" and isinstance(close, dict) \
                and "exit_spread_source" not in close:
            spread = spread_at_pips(symbol, doc.get("closed_at"))
            sets["close_data.exit_spread"] = spread
            sets["close_data.exit_spread_source"] = "tick_history" if spread is not None else None
            stats["exit_spread_filled" if spread is not None else "exit_spread_unresolved"] += 1
            if spread is None:
                unresolved.append((doc.get("trade_id"), symbol, "exit_spread"))

            slippage = exit_slippage_pips(
                symbol, doc.get("direction") or close.get("order_type"),
                close.get("close_reason"), close.get("close_price"),
                close.get("sl"), close.get("tp"))
            # None is a real answer for manual/EA closes: replaces the literal
            # 0.0 that claimed a perfect fill.
            sets["close_data.exit_slippage"] = slippage
            stats["slippage_measured" if slippage is not None else "slippage_not_applicable"] += 1

        if sets:
            updates.append((doc["_id"], doc.get("trade_id"), sets))

    print(f"trades to update: {len(updates)}")
    for key in sorted(stats):
        print(f"   {key:<28} {stats[key]}")
    if unresolved:
        print(f"\nunresolved ({len(unresolved)}) -- left as None, nothing estimated:")
        for trade_id, symbol, field in unresolved[:15]:
            print(f"   {trade_id:<22} {symbol:<12} {field}")

    print("\nsample:")
    for _, trade_id, sets in updates[:5]:
        shown = {k.replace("close_data.", "cd."): v for k, v in sets.items()}
        print(f"   {trade_id:<22} {shown}")

    if not args.apply:
        print("\ndry run -- re-run with --apply to write")
        return 0

    written = 0
    for _id, _, sets in updates:
        written += col.update_one({"_id": _id}, {"$set": sets}).modified_count
    print(f"\nwrote {written} trade(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
