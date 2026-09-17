"""Replay a category over the full history: setup journal + summary by period and variant.

    python -m engine_v2.run.replay SMC [--symbols EURUSD GBPUSD ...] [--workers 8]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HOLDOUT_START = int(datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp())  # broker-time label
OUT_DIR = Path(__file__).resolve().parents[2] / "reports" / "v2"
MODULES = {"SMC": "smc", "STRUCTURE": "structure", "TREND": "trend", "ORDER_FLOW": "order_flow",
           "MOMENTUM": "momentum", "MEAN_REVERSION": "mean_reversion", "WAVE": "wave", "CROSS_ASSET": "cross_asset"}


def run_symbol(category: str, symbol: str) -> list[dict]:
    from engine_v2.data.replay import load_m1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_m1(symbol))
    if category == "CROSS_ASSET":
        if symbol not in mod.PAIRS:
            return []
        legs = mod.PAIRS[symbol][:2]
        ctxs = {symbol: ctx, **{leg: Context(leg, load_m1(leg)) for leg in legs}}
        setups = [s for s in mod.propose_multi(ctxs) if s.symbol == symbol]
    else:
        setups = mod.propose(ctx)
    rows = []
    for s in setups:
        o = simulate(s, ctx)
        rows.append({
            "id": s.id, "category": s.category, "variant": s.variant, "symbol": s.symbol, "side": s.side,
            "created_at": s.created_at, "period": "holdout" if s.created_at >= HOLDOUT_START else "discovery",
            "entry": s.entry, "stop": s.stop["price"], "targets": [t["price"] for t in s.targets],
            "context": s.context, "status": o.status, "fill_time": o.fill_time, "fill_price": o.fill_price,
            "exit_time": o.exit_time, "exit_reason": o.exit_reason, "targets_hit": o.targets_hit,
            "gross_r": o.gross_r, "commission_r": o.commission_r, "net_r": o.net_r,
            "mfe_r": o.mfe_r, "mae_r": o.mae_r, "win": o.win,
        })
    return rows


def summarize(rows: list[dict], keys=("period",)) -> list[dict]:
    traded = [r for r in rows if r["status"] == "FILLED_CLOSED"]
    groups: dict[tuple, list[dict]] = {}
    for r in traded:
        groups.setdefault(tuple(r[k] if k in r else r["context"].get(k) for k in keys), []).append(r)
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        net = np.array([x["net_r"] for x in g])
        wins = np.array([x["win"] for x in g])
        reached_t1 = np.mean([x["targets_hit"] >= 1 for x in g])
        out.append({**dict(zip(keys, key)), "trades": len(g), "win_rate": round(float(wins.mean()), 4),
                    "net_r": round(float(net.mean()), 4), "gross_r": round(float(np.mean([x["gross_r"] for x in g])), 4),
                    "commission_r": round(float(np.mean([x["commission_r"] for x in g])), 4),
                    "t1_rate": round(float(reached_t1), 4),
                    "net_r_se": round(float(net.std(ddof=1) / np.sqrt(len(net))), 4) if len(net) > 1 else None})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 4))
    args = ap.parse_args(argv)
    from engine_v2.data.replay import available_symbols
    symbols = args.symbols or available_symbols()
    t0 = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(args.workers) as ex:
        for part in ex.map(run_symbol, [args.category] * len(symbols), symbols):
            rows.extend(part)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = args.category.lower()
    with open(OUT_DIR / f"{stem}_journal.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    summary = {"category": args.category, "symbols": symbols, "seconds": round(time.time() - t0, 1),
               "setups": len(rows), "statuses": statuses,
               "by_period": summarize(rows, ("period",)),
               "by_period_variant": summarize(rows, ("period", "variant")),
               "by_period_side": summarize(rows, ("period", "side"))}
    (OUT_DIR / f"{stem}_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("category", "seconds", "setups", "statuses", "by_period",
                                                "by_period_variant")}, indent=1))


if __name__ == "__main__":
    main()
