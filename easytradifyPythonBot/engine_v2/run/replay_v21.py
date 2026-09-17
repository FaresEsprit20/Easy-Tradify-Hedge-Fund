"""v2.1 replay: categories at their default (H4/D1) scale with the v2.1 rules, 16 years of MT5 H1 history.

Writes journals in the standard format (reports/v2/v21/<category>_journal.jsonl) so the probability table
can be built from them, and prints v2.0 (standard exits) next to v2.1.

    python -m engine_v2.run.replay_v21
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from engine_v2.run.replay import MODULES
from engine_v2.run.replay_history import HOLDOUT

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "v21"
HTF = Path(__file__).resolve().parents[2] / "reports" / "v2" / "htf" / "summary.json"
CATEGORIES = ("SMC", "STRUCTURE", "TREND", "MOMENTUM", "MEAN_REVERSION", "WAVE")


def run_symbol(category: str, symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    rows = []
    for s in mod.propose(ctx):
        o = simulate(s, ctx)
        rows.append({"id": s.id, "category": category, "variant": s.variant, "symbol": symbol, "side": s.side,
                     "created_at": s.created_at, "period": "holdout" if s.created_at >= HOLDOUT else "discovery",
                     "context": s.context, "status": o.status, "win": o.win, "net_r": o.net_r, "gross_r": o.gross_r,
                     "commission_r": o.commission_r, "targets_hit": o.targets_hit, "exit_reason": o.exit_reason,
                     "mfe_r": o.mfe_r, "mae_r": o.mae_r})
    return rows


def cell(g):
    t = [r for r in g if r["status"] == "FILLED_CLOSED"]
    if not t:
        return {"trades": 0}
    net = np.array([r["net_r"] for r in t])
    return {"trades": len(t), "win_rate": round(float(np.mean([r["win"] for r in t])), 4),
            "net_r": round(float(net.mean()), 4),
            "net_r_se": round(float(net.std(ddof=1) / np.sqrt(len(t))), 4) if len(t) > 1 else None}


def main():
    from engine_v2.data.history import LONG_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    old = json.loads(HTF.read_text()) if HTF.exists() else {}
    summary = {}
    with ProcessPoolExecutor(11) as ex:
        for cat in CATEGORIES:
            rows = [r for part in ex.map(run_symbol, [cat] * len(LONG_SYMBOLS), LONG_SYMBOLS) for r in part]
            with open(OUT / f"{cat.lower()}_journal.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            summary[cat] = {p: cell([r for r in rows if r["period"] == p]) for p in ("discovery", "holdout")}
            for p in ("discovery", "holdout"):
                v20 = (old.get(cat, {}).get(p) or {}).get("standard_exits") or {}
                v21 = summary[cat][p]
                print(f"{cat:15s} {p:9s} v2.0 n={v20.get('trades', 0):5d} won={v20.get('win_rate', 0):.1%} net={v20.get('net_r', 0):+.3f}"
                      f"  ->  v2.1 n={v21.get('trades', 0):5d} won={v21.get('win_rate', 0):.1%} net={v21.get('net_r', 0):+.3f} se={v21.get('net_r_se') or 0:.3f}",
                      flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
