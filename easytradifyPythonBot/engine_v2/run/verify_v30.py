"""Verify the built v3.0 STRUCTURE (medium volatility + secure-half) on all 30 pairs.

    python -m engine_v2.run.verify_v30
"""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine_v2.run.replay_v21 import run_symbol

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "v3"


def main():
    from engine_v2.data.history import LONG_SYMBOLS, UNSEEN_SYMBOLS
    syms = LONG_SYMBOLS + UNSEEN_SYMBOLS
    with ProcessPoolExecutor(12) as ex:
        rows = [r for part in ex.map(run_symbol, ["STRUCTURE"] * len(syms), syms) for r in part]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "structure_v30_replay.json").write_text(json.dumps(rows))
    t = [r for r in rows if r["status"] == "FILLED_CLOSED"]

    def c(g, label):
        net = np.array([r["net_r"] for r in g])
        print(f"{label:28s} n={len(g):4d} won={np.mean([r['win'] for r in g]):.1%} net={net.mean():+.3f} "
              f"se={net.std(ddof=1) / np.sqrt(len(g)):.3f} total={net.sum():+.1f}R")

    c(t, "v3.0 STRUCTURE, 30 pairs")
    c([r for r in t if r["created_at"] < 1609459200], "  before 2021")
    c([r for r in t if r["created_at"] >= 1609459200], "  from 2021")
    c([r for r in t if r["symbol"] in UNSEEN_SYMBOLS], "  19 new pairs")
    year = lambda r: datetime.fromtimestamp(r["created_at"], tz=timezone.utc).year
    print(" ".join(f"{y}:{sum(r['net_r'] for r in t if year(r) == y):+.1f}" for y in sorted({year(r) for r in t})))
    eq = np.cumsum([r["net_r"] for r in sorted(t, key=lambda r: r["created_at"])])
    print("max drawdown R", round(float((np.maximum.accumulate(eq) - eq).max()), 1))


if __name__ == "__main__":
    main()
