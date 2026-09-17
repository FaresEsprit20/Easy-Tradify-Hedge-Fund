"""Rule audit: the same entries, with one management rule replaced by the category's standard practice.

Variants are defined from each school's usual trade management, not from the results:
  SMC        no FVG-close exit: the invalidation is the sweep extreme (the stop)
  MOMENTUM   no "back inside squeeze" exit before T1: the stop beyond the squeeze range is the invalidation
  ORDER_FLOW no thesis exits: the stop beyond the excursion / 1 ATR inside value is the invalidation
  WAVE       no thesis exits: the stop at the structure invalidation is the invalidation
  STRUCTURE  T1 at the nearest opposing H1 swing (at least 1R), T2 at the departure leg extreme

    python -m engine_v2.run.rule_audit
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np

from engine_v2.run.replay import HOLDOUT_START, MODULES

AUDITS = ("SMC", "MOMENTUM", "ORDER_FLOW", "WAVE", "STRUCTURE")


def _structure_targets(s, ctx):
    sw = ctx.swings("H1")
    d = s.direction
    e = float(s.entry["price"])
    risk = (e - float(s.stop["price"])) * d
    known = sw.available_idx <= ctx.last_closed_index("H1", s.created_at)
    kind = 1 if d > 0 else -1
    lv = sw.price[known & (sw.kind == kind)]
    beyond = lv[(lv - e) * d >= risk]
    t1 = float(beyond.min() if d > 0 else beyond.max()) if len(beyond) else e + d * risk
    t2 = float(s.targets[0]["price"])            # the original T1 = departure leg extreme
    if (t2 - t1) * d < 0.5 * risk:
        t2 = t1 + d * 0.5 * risk
    return [{"price": t1, "share": 0.5, "reason": "nearest opposing swing"},
            {"price": t2, "share": 0.5, "reason": "departure leg extreme"}]


def variant(category: str, s, ctx):
    if category in ("SMC", "ORDER_FLOW", "WAVE"):
        return replace(s, thesis=[t for t in s.thesis if t.get("applies_to") == "pending"])
    if category == "MOMENTUM":
        return replace(s, thesis=[t for t in s.thesis if t.get("until_target") is None])
    if category == "STRUCTURE":
        return replace(s, targets=_structure_targets(s, ctx))
    return s


def run_symbol(category: str, symbol: str):
    from engine_v2.data.replay import load_m1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_m1(symbol))
    out = []
    for s in mod.propose(ctx):
        a = simulate(s, ctx)
        b = simulate(variant(category, s, ctx).validate(), ctx)
        if a.traded and b.traded:
            out.append({"period": "holdout" if s.created_at >= HOLDOUT_START else "discovery",
                        "orig_net": a.net_r, "orig_win": a.win, "var_net": b.net_r, "var_win": b.win})
    return out


def main():
    from engine_v2.data.replay import available_symbols
    syms = available_symbols()
    report = {}
    with ProcessPoolExecutor(12) as ex:
        for cat in AUDITS:
            rows = [r for part in ex.map(run_symbol, [cat] * len(syms), syms) for r in part]
            report[cat] = {}
            for period in ("discovery", "holdout"):
                g = [r for r in rows if r["period"] == period]
                if not g:
                    continue
                o = np.array([r["orig_net"] for r in g]); v = np.array([r["var_net"] for r in g])
                report[cat][period] = {"n": len(g),
                                       "as_built_win": round(float(np.mean([r["orig_win"] for r in g])), 3),
                                       "as_built_net": round(float(o.mean()), 3),
                                       "school_rule_win": round(float(np.mean([r["var_win"] for r in g])), 3),
                                       "school_rule_net": round(float(v.mean()), 3),
                                       "diff_se": round(float((v - o).std(ddof=1) / np.sqrt(len(g))), 3)}
            print(cat, json.dumps(report[cat]), flush=True)


if __name__ == "__main__":
    main()
