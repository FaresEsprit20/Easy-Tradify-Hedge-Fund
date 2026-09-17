"""Unseen-data proof: v3 categories, unchanged, on 19 FX pairs never used to build or choose any rule.

    python -m engine_v2.run.unseen
"""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine_v2.run.replay_v21 import CATEGORIES, run_symbol

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "v3"
PORTFOLIO = ("SMC", "STRUCTURE", "TREND", "MOMENTUM")


def cell(g):
    t = [r for r in g if r["status"] == "FILLED_CLOSED"]
    if not t:
        return {"trades": 0}
    net = np.array([r["net_r"] for r in t])
    return {"trades": len(t), "win_rate": round(float(np.mean([r["win"] for r in t])), 4),
            "net_r": round(float(net.mean()), 4), "total_r": round(float(net.sum()), 1),
            "net_r_se": round(float(net.std(ddof=1) / np.sqrt(len(t))), 4) if len(t) > 1 else None}


def main():
    from engine_v2.data.history import UNSEEN_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    with ProcessPoolExecutor(12) as ex:
        for cat in CATEGORIES:
            rows = [r for part in ex.map(run_symbol, [cat] * len(UNSEEN_SYMBOLS), UNSEEN_SYMBOLS) for r in part]
            all_rows.extend(rows)
    with open(OUT / "unseen_journal.jsonl", "w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")
    report = {c: cell([r for r in all_rows if r["category"] == c]) for c in CATEGORIES}
    report["PORTFOLIO_4"] = cell([r for r in all_rows if r["category"] in PORTFOLIO])
    yr = lambda r: datetime.fromtimestamp(r["created_at"], tz=timezone.utc).year
    report["PORTFOLIO_4_by_year"] = {y: cell([r for r in all_rows if r["category"] in PORTFOLIO and yr(r) == y])
                                     for y in sorted({yr(r) for r in all_rows})}
    (OUT / "unseen_summary.json").write_text(json.dumps(report, indent=1))
    for k, v in report.items():
        if k.endswith("by_year"):
            for y, c in v.items():
                print(f"   {y}: {c}")
        else:
            print(f"{k:16s} {v}")


if __name__ == "__main__":
    main()
