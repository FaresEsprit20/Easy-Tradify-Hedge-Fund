"""v3 exit lab: fixed exit variants on the v2.1 setups (16 years, 11 symbols). Pick on discovery, report holdout.

  V0 as built
  V1 stop to breakeven once the trade is +0.5R
  V2 stop to breakeven once the trade is +1.0R
  V3 50% off at +0.5R, the rest at the last target, breakeven after the first
  V4 stop 25% closer (0.75 x distance), same target prices
  V5 V1 + V4

    python -m engine_v2.run.exit_lab
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from engine_v2.run.replay import MODULES
from engine_v2.run.replay_history import HOLDOUT

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "v3"
CATEGORIES = ("SMC", "STRUCTURE", "TREND", "MOMENTUM", "MEAN_REVERSION", "WAVE")
VARIANTS = ("V0", "V1", "V2", "V3", "V4", "V5")


def make_variant(s, v: str):
    d = s.direction
    e = float(s.entry["price"])
    stop = float(s.stop["price"])
    risk = (e - stop) * d
    mg = dict(s.management or {})
    if v == "V0":
        return s
    if v == "V1":
        return replace(s, management=dict(mg, breakeven_at_r=0.5))
    if v == "V2":
        return replace(s, management=dict(mg, breakeven_at_r=1.0))
    if v == "V3":
        return replace(s, targets=[{"price": e + d * 0.5 * risk, "share": 0.5, "reason": "+0.5R"},
                                   {"price": float(s.targets[-1]["price"]), "share": 0.5, "reason": "last target"}],
                       management=dict(mg, breakeven_after_target=1))
    tight = replace(s, stop={"price": e - d * 0.75 * risk, "reason": "0.75x stop"})
    if v == "V4":
        return tight
    if v == "V5":
        return replace(tight, management=dict(mg, breakeven_at_r=0.5))
    raise KeyError(v)


def run_symbol(category: str, symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    rows = []
    for s in mod.propose(ctx):
        rec = {"period": "holdout" if s.created_at >= HOLDOUT else "discovery"}
        ok = True
        for v in VARIANTS:
            try:
                o = simulate(make_variant(s, v).validate(), ctx)
            except ValueError:
                ok = False
                break
            if not o.traded:
                ok = False
                break
            rec[v] = (o.net_r, o.win)
        if ok:
            rows.append(rec)
    return rows


def main():
    from engine_v2.data.history import LONG_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    with ProcessPoolExecutor(11) as ex:
        for cat in CATEGORIES:
            rows = [r for part in ex.map(run_symbol, [cat] * len(LONG_SYMBOLS), LONG_SYMBOLS) for r in part]
            rep = {}
            for p in ("discovery", "holdout"):
                g = [r for r in rows if r["period"] == p]
                rep[p] = {v: {"n": len(g), "win": round(float(np.mean([r[v][1] for r in g])), 3) if g else None,
                              "net": round(float(np.mean([r[v][0] for r in g])), 3) if g else None} for v in VARIANTS}
            best = max(VARIANTS, key=lambda v: rep["discovery"][v]["net"] if rep["discovery"][v]["net"] is not None else -9)
            rep["chosen_on_discovery"] = best
            report[cat] = rep
            line = " | ".join(f"{v} {rep['discovery'][v]['win']:.0%}/{rep['discovery'][v]['net']:+.3f} -> {rep['holdout'][v]['win']:.0%}/{rep['holdout'][v]['net']:+.3f}" for v in VARIANTS)
            print(f"{cat:15s} n={rep['discovery']['V0']['n']}/{rep['holdout']['V0']['n']} chosen={best}\n    {line}", flush=True)
    (OUT / "exit_lab.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
