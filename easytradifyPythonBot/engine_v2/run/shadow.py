"""Shadow run (roadmap phase 10): v2 on live data, journals every new setup, sends NO orders.

    python -m engine_v2.run.shadow --once
    python -m engine_v2.run.shadow            # loops at every M15 close
"""
from __future__ import annotations

import argparse
import json
import time

from engine_v2.analysis import analyze_context
from engine_v2.journal.journal import LIVE_JOURNAL, record
from engine_v2.probability.frequency import load_table

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD", "AUDNZD",
           "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY", "XAUUSD", "XAGUSD"]
HEARTBEAT = LIVE_JOURNAL.with_name("shadow_heartbeat.json")


def _seen_ids() -> set[str]:
    seen = set()
    if LIVE_JOURNAL.exists():
        with open(LIVE_JOURNAL) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["setup"]["id"])
                except (KeyError, json.JSONDecodeError):
                    continue
    return seen


def cycle(symbols, fixed_trade_size_usd: float, risk_per_trade: float) -> dict:
    from engine_v2.data.live import load_live_h1
    from engine_v2.market_model.context import Context
    from engine_v2.setup import Setup
    table = load_table()
    seen = _seen_ids()
    report = {"at": int(time.time()), "symbols": {}}
    for sym in symbols:
        try:
            ctx = Context(sym, load_live_h1(sym))
            res = analyze_context(ctx, fixed_trade_size_usd, risk_per_trade, table=table)
        except Exception as e:
            report["symbols"][sym] = {"error": repr(e)}
            continue
        new = 0
        for kind in ("setups", "not_tradeable"):
            for d in res[kind]:
                if d["id"] in seen:
                    continue
                fields = {k: d[k] for k in Setup.__dataclass_fields__ if k in d}
                s = Setup(**fields)
                record(s, "SHADOW_PROPOSED" if kind == "setups" else "SHADOW_NOT_TRADEABLE",
                       {"selected": bool(res["selected"] and res["selected"]["id"] == d["id"])})
                seen.add(d["id"])
                new += 1
        report["symbols"][sym] = {"as_of": res["as_of"], "live_setups": len(res["setups"]),
                                  "not_tradeable": len(res["not_tradeable"]), "new_journaled": new,
                                  "errors": res["category_errors"]}
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(report, indent=1))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--budget", type=float, default=200.0)
    ap.add_argument("--risk", type=float, default=0.02)
    ap.add_argument("--symbols", nargs="*", default=SYMBOLS)
    args = ap.parse_args(argv)
    import core.console_safe  # noqa: F401  UTF-8 output; a click in the window cannot freeze the loop
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        while True:
            rep = cycle(args.symbols, args.budget, args.risk)
            print(json.dumps({s: v.get("new_journaled", v.get("error")) for s, v in rep["symbols"].items()}), flush=True)
            if args.once:
                break
            now = time.time()
            time.sleep(900 - now % 900 + 20)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
