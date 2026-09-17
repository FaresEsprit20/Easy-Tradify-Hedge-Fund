"""Simulator control: each setup's geometry replayed as a MARKET entry at its creation time, BOTH sides.

With no directional information and an unbiased simulator, the two sides average to about minus the
spread paid (in R). The difference between the setup's side and the opposite side is the timing's
directional content.

    python -m engine_v2.run.control SMC
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np

from engine_v2.run.replay import HOLDOUT_START, MODULES


def _mirror(s, side_mult: int, ctx):
    m = ctx.m1
    i0 = int(np.searchsorted(m.time, s.created_at))
    if i0 >= len(m):
        return None
    d0 = s.direction
    e0 = float(s.entry["price"])
    risk = (e0 - float(s.stop["price"])) * d0
    d = d0 * side_mult
    ref = float((m.bid_open[i0] + m.ask_open[i0]) / 2.0)
    rs = [(float(t["price"]) - e0) * d0 / risk for t in s.targets]
    return replace(s, side="BUY" if d > 0 else "SELL", entry={"order_type": "MARKET", "price": ref},
                   stop={"price": ref - d * risk, "reason": "control"},
                   targets=[{"price": ref + d * r * risk, "share": t["share"], "reason": "control"}
                            for r, t in zip(rs, s.targets)],
                   thesis=[], valid_until=s.created_at + 60)


def run_symbol(category: str, symbol: str):
    from engine_v2.data.replay import load_m1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_m1(symbol))
    rows = []
    for s in mod.propose(ctx):
        same, opp = _mirror(s, 1, ctx), _mirror(s, -1, ctx)
        if same is None:
            continue
        a, b = simulate(same, ctx), simulate(opp, ctx)
        if not (a.traded and b.traded):
            continue
        i0 = int(np.searchsorted(ctx.m1.time, s.created_at))
        spread_r = float((ctx.m1.ask_open[i0] - ctx.m1.bid_open[i0]) / a.risk_distance)
        rows.append({"period": "holdout" if s.created_at >= HOLDOUT_START else "discovery",
                     "same_gross": a.gross_r, "opp_gross": b.gross_r, "same_win": a.gross_r > 0,
                     "opp_win": b.gross_r > 0, "spread_r": spread_r})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args(argv)
    from engine_v2.data.replay import available_symbols
    syms = available_symbols()
    rows = []
    with ProcessPoolExecutor(args.workers) as ex:
        for part in ex.map(run_symbol, [args.category] * len(syms), syms):
            rows.extend(part)
    out = {"category": args.category}
    for period in ("discovery", "holdout"):
        g = [r for r in rows if r["period"] == period]
        if not g:
            continue
        same = np.array([r["same_gross"] for r in g]); opp = np.array([r["opp_gross"] for r in g])
        out[period] = {"n": len(g), "same_side_gross": round(float(same.mean()), 4),
                       "opposite_side_gross": round(float(opp.mean()), 4),
                       "both_sides_mean": round(float((same + opp).mean() / 2), 4),
                       "expected_about": round(-float(np.mean([r["spread_r"] for r in g])), 4),
                       "same_minus_opp": round(float((same - opp).mean()), 4),
                       "same_minus_opp_se": round(float((same - opp).std(ddof=1) / np.sqrt(len(g))), 4)}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
