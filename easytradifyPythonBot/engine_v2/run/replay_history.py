"""16-year replay of the categories one timeframe scale up, on MT5 H1 history with real spreads.

Scale "htf" (fixed before running):
  SMC            setup H4, context D1
  STRUCTURE      zones D1, trigger H4, context D1
  TREND          impulse H4, context D1, trigger H1
  MOMENTUM       setup H4, efficiency ratio D1, context D1
  MEAN_REVERSION setup H4, efficiency ratio D1, context D1
  WAVE           patterns H4, trigger H1, context D1
Discovery: 2010-10 -> 2020-12. Holdout: 2021-01 -> 2026-09.
Each setup is replayed twice: exits as built, and with the category's standard exits (engine_v2/run/rule_audit.py).

    python -m engine_v2.run.replay_history
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine_v2.run.replay import MODULES

HOLDOUT = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp())
OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "htf"
SCALE = {
    "SMC": {"setup": "H4", "context": "D1"},
    "STRUCTURE": {"zone": "D1", "trigger": "H4", "context": "D1"},
    "TREND": {"impulse": "H4", "context": "D1", "trigger": "H1"},
    "MOMENTUM": {"setup": "H4", "er": "D1", "context": "D1"},
    "MEAN_REVERSION": {"setup": "H4", "er": "D1", "context": "D1"},
    "WAVE": {"pattern": "H4", "trigger": "H1", "context": "D1"},
}


def standard_exits(category: str, s, ctx, tfs: dict):
    if category in ("SMC", "WAVE"):
        return replace(s, thesis=[t for t in s.thesis if t.get("applies_to") == "pending"])
    if category == "MOMENTUM":
        return replace(s, thesis=[t for t in s.thesis if t.get("until_target") is None])
    if category == "STRUCTURE":
        zt = tfs["zone"]
        sw = ctx.swings(zt)
        d = s.direction
        e = float(s.entry["price"])
        risk = (e - float(s.stop["price"])) * d
        known = sw.available_idx <= ctx.last_closed_index(zt, s.created_at)
        lv = sw.price[known & (sw.kind == (1 if d > 0 else -1))]
        beyond = lv[(lv - e) * d >= risk]
        t1 = float(beyond.min() if d > 0 else beyond.max()) if len(beyond) else e + d * risk
        t2 = float(s.targets[0]["price"])
        if (t2 - t1) * d < 0.5 * risk:
            t2 = t1 + d * 0.5 * risk
        return replace(s, targets=[{"price": t1, "share": 0.5}, {"price": t2, "share": 0.5}])
    return s


def run_symbol(category: str, symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    tfs = SCALE[category]
    rows = []
    for s in mod.propose(ctx, tfs):
        a = simulate(s, ctx)
        try:
            b = simulate(standard_exits(category, s, ctx, tfs).validate(), ctx)
        except ValueError:
            b = a
        rows.append({"category": category, "variant": s.variant, "symbol": symbol, "side": s.side,
                     "created_at": s.created_at, "period": "holdout" if s.created_at >= HOLDOUT else "discovery",
                     "context": s.context, "status": a.status,
                     "built_net": a.net_r, "built_win": a.win, "built_exit": a.exit_reason,
                     "std_status": b.status, "std_net": b.net_r, "std_win": b.win,
                     "commission_r": a.commission_r, "gross_r": a.gross_r})
    return rows


def summarize(rows, prefix):
    tr = [r for r in rows if r["status" if prefix == "built" else "std_status"] == "FILLED_CLOSED"]
    if not tr:
        return None
    net = np.array([r[f"{prefix}_net"] for r in tr])
    return {"trades": len(tr), "win_rate": round(float(np.mean([r[f"{prefix}_win"] for r in tr])), 4),
            "net_r": round(float(net.mean()), 4), "net_r_se": round(float(net.std(ddof=1) / np.sqrt(len(net))), 4) if len(net) > 1 else None}


def main():
    from engine_v2.data.history import LONG_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    with ProcessPoolExecutor(11) as ex:
        for cat in SCALE:
            rows = [r for part in ex.map(run_symbol, [cat] * len(LONG_SYMBOLS), LONG_SYMBOLS) for r in part]
            with open(OUT / f"{cat.lower()}_journal.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            rep = {}
            for period in ("discovery", "holdout"):
                g = [r for r in rows if r["period"] == period]
                rep[period] = {"exits_as_built": summarize(g, "built"), "standard_exits": summarize(g, "std")}
                variants = sorted({r["variant"] for r in g})
                if len(variants) > 1:
                    rep[period]["by_variant"] = {v: {"exits_as_built": summarize([r for r in g if r["variant"] == v], "built"),
                                                     "standard_exits": summarize([r for r in g if r["variant"] == v], "std")}
                                                 for v in variants}
            report[cat] = rep
            print(cat, json.dumps({p: {k: rep[p][k] for k in ("exits_as_built", "standard_exits")} for p in rep}), flush=True)
    (OUT / "summary.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
