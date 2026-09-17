# ai/decision_replay.py
"""
Held-out verification of the full live decision path.

Runs the REAL analyze_institutional_signal -- closed bars, every gate, the
installed calibrated model and component rules -- over the second half of the
study calendar (the half the model was not fitted on), then scores every
ENTRY it would have taken against the tick-free bar path that followed:

  success     the first 5-ATR barrier went the trade's way
  net R       the planned bracket (engine stop / target), minus spread and
              commission
  trades/day  how often it actually trades

    python -m ai.decision_replay run --step 15 --workers 16
    python -m ai.decision_replay score
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = Path(os.getenv("DECISION_REPLAY_DIR") or r"C:/Users/msi/tradify_study/decision_replay")


def _worker(args):
    symbol, step, start_ts, shard = args
    os.environ["PRICE_STUDY_DIR"] = str(REPLAY_DIR)
    import ai.price_history_study as study
    study.STUDY_DIR = REPLAY_DIR
    study.WARMUP_M1_BARS = 1500
    # only the held-out half: skip timestamps before start_ts
    m1 = study.load_history(symbol)["M1"]
    first = int(np.searchsorted(m1["time"].astype(np.int64), start_ts))
    study.WARMUP_M1_BARS = max(1500, first)
    try:
        return study.run_symbol(symbol, step, shard=shard, out_dir=REPLAY_DIR)
    except Exception as exc:
        return {"symbol": symbol, "fatal": repr(exc)[:300]}


def held_out_start() -> int:
    model = json.loads((ROOT / "core" / "calibrated_model.json").read_text())
    if model.get("test_start_ts"):
        return int(model["test_start_ts"])
    from ai.component_repair import Columns
    ts = Columns().num("ts").astype(np.float64)
    return int(np.nanmedian(ts) + 43200)


def run(step: int, workers: int, shards: int = 2) -> None:
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    start = held_out_start()
    jobs = [(s, step, start, (k, shards)) for s in SYMBOLS for k in range(shards)]
    with Pool(workers) as pool:
        for r in pool.imap_unordered(_worker, jobs):
            print(json.dumps({k: r.get(k) for k in ("symbol", "written", "errors", "fatal", "last_error")}), flush=True)


def score() -> Dict[str, Any]:
    import ai.price_history_study as study
    from ai.component_calibration import cluster_mean_z

    study.STUDY_DIR = REPLAY_DIR
    study.label(study.SYMBOLS)
    rows = []
    for rec in study.iter_records(study.SYMBOLS, labelled=True):
        if not rec.get("should_enter"):
            continue
        out = rec.get("outcome") or {}
        # The EXECUTED side: a model flip mirrors stop and target around entry,
        # so the plan itself says which side was sent; `direction` is the
        # engine's side before the model decided.
        entry, stop = rec.get("entry"), rec.get("stop")
        if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and entry != stop:
            side = 1 if stop < entry else -1
        else:
            d = str(rec.get("executed_direction") or rec.get("direction") or "").upper()
            side = 1 if d == "BUY" else -1 if d == "SELL" else 0
        y = out.get("move_5atr")
        br = out.get("bracket_buy" if side > 0 else "bracket_sell") or {}
        cost = (out["commission_r"] if out.get("source") == "quotes" and "commission_r" in out
                else (rec.get("cost") or {}).get("cost_r")) or 0.0
        rows.append({"symbol": rec["symbol"], "day": rec["ts"] // 86400,
                     "right": float(side == y) if y in (1, -1) and side else math.nan,
                     "net_r": (br.get("r") - cost) if isinstance(br.get("r"), (int, float)) else math.nan})
    if not rows:
        return {"entries": 0}
    clusters = np.array([f"{r['symbol']}|{r['day']}" for r in rows], dtype=object)
    right = np.array([r["right"] for r in rows])
    net = np.array([r["net_r"] for r in rows])
    acc, z, _ = cluster_mean_z(right, clusters)
    nr, nz, days = cluster_mean_z(net, clusters, null=0.0)
    n_days = len({r["day"] for r in rows})
    return {"entries": len(rows), "days_with_entries": n_days, "success_pct": round(100 * acc, 1), "z": round(z, 2),
            "net_r_per_trade": round(nr, 3), "net_z": round(nz, 2),
            "total_r": round(float(np.nansum(net)), 1)}


def self_check() -> Dict[str, Any]:
    return {"ok": REPLAY_DIR.name == "decision_replay" or bool(os.getenv("DECISION_REPLAY_DIR"))}


def get_status() -> Dict[str, Any]:
    return {"component": "decision_replay", "dir": str(REPLAY_DIR)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--step", type=int, default=15)
    r.add_argument("--workers", type=int, default=16)
    sub.add_parser("score")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.step, a.workers)
    else:
        print(json.dumps(score(), indent=1))
