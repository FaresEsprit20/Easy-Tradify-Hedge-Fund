# scripts/backfill_trade_leverage.py
"""
Copy each stored trade's leverage to a top-level `leverage` field.

WHY
---
Trades come from three MT5 accounts (1:200, 1:300, 1:500). Every trade already
records its leverage, but only deep in the analysis snapshot:

    analysis_at_open.m1_analysis_raw.account_info.leverage

That path cannot be indexed usefully, cannot be sorted on by the trade API, and
is stripped from list responses as a heavy field. New trades now write a
top-level `leverage` at open (monitor/firebase_helpers._account_at_open); this
brings the existing ones into line.

WHAT IT DOES NOT DO
-------------------
* It never overwrites. Only documents with NO top-level `leverage` are touched,
  so running it twice is a no-op and a value written live at open always wins.
* It copies a value the trade already holds. Nothing is inferred, estimated or
  recomputed -- a trade with no nested leverage is left alone and reported.

Usage:
    python scripts/backfill_trade_leverage.py            # dry run
    python scripts/backfill_trade_leverage.py --apply    # write
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mongo.trade_query import LEVERAGE_NESTED, leverage_of  # noqa: E402
from core.mongo.trades_service import get_trades_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    args = parser.parse_args()

    col = get_trades_service().collection
    missing = {"leverage": {"$exists": False}}

    candidates = list(col.find(missing, {"trade_id": 1, LEVERAGE_NESTED: 1}))
    plan = Counter()
    unresolved = []

    for doc in candidates:
        lev = leverage_of(doc)
        if lev is None:
            unresolved.append(doc.get("trade_id"))
        else:
            plan[lev] += 1

    print(f"trades without top-level leverage: {len(candidates)}")
    for lev, n in sorted(plan.items()):
        print(f"   would set leverage={lev:<4} on {n} trade(s)")
    if unresolved:
        print(f"   no leverage recorded anywhere (left untouched): {len(unresolved)}")
        for trade_id in unresolved[:10]:
            print(f"      {trade_id}")

    if not args.apply:
        print("\ndry run -- re-run with --apply to write")
        return 0

    written = 0
    for doc in candidates:
        lev = leverage_of(doc)
        if lev is None:
            continue
        # The $exists guard is repeated in the update itself, so a trade that
        # gained a live value between the read above and this write keeps it.
        result = col.update_one({"_id": doc["_id"], "leverage": {"$exists": False}},
                                {"$set": {"leverage": lev}})
        written += result.modified_count

    print(f"\nwrote leverage on {written} trade(s)")
    remaining = col.count_documents(missing)
    print(f"trades still without top-level leverage: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
