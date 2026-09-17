# ai/pure_direction.py
"""
Is there ANY directional edge, before any cost at all?

Every number this project has produced conflates two different failures. A
tick result of -0.034R "gross" still pays the spread -- entry at the ask, exit
on the bid -- so it can mean either of:

    a real signal, worth +0.02R, minus a 0.05R toll
    no signal whatsoever, and the toll on top

Those call for opposite responses. The first makes cost and horizon the whole
problem; the second means no exit rule, instrument filter or cost structure
can ever help, because there is nothing to protect. Nothing measured so far
separates them.

This does, by removing every cost: barriers are placed on the MID price,
entry is the mid, and no commission is charged. Symmetric barriers at
1.5 x H1 ATR, so a coin flip scores 50% and 0.000R. What remains is direction
and nothing else.

The control is the point of the file as much as the test. ALWAYS_BUY runs the
same harness with a fixed side: it must land on 50% and 0.000R. If it does
not, the harness has a bias and every other row is measuring that bias --
which, given bid-only bars already faked an edge three times here, is the
first thing to rule out rather than the last.

Horizons are swept because "no edge" at 24h is a statement about 24h; a
signal that needs three days to pay would look identical to noise here.

    python -m ai.pure_direction
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from ai.participation_ticks import (BUCKETS, COOLDOWN_MIN, EXTENDED_ATR, MEAN_MIN, STALL_MIN,
                                    TICK_DIR, VEL_MIN, VELOCITY_MAX_ATR, bucket_of,
                                    h1_atr_per_minute, load, participation)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

STOP_ATR = 1.5
HORIZONS = (60, 240, 1440, 4320)     # 1h, 4h, 24h, 72h
ROLLOVER_HOUR = 0
ACTIONS = ("follow", "fade", "always_buy")


def walk_mid(mid_high: np.ndarray, mid_low: np.ndarray, mid_close: np.ndarray,
             k: int, hold: int, side: int, entry: float, risk: float) -> Optional[float]:
    """Symmetric barriers on the mid. No spread, no commission, no book side."""
    n = mid_close.size
    e = min(n, k + hold)
    if k >= e:
        return None
    stop = entry - side * risk
    target = entry + side * risk
    if side > 0:
        hit_s = mid_low[k:e] <= stop
        hit_t = mid_high[k:e] >= target
    else:
        hit_s = mid_high[k:e] >= stop
        hit_t = mid_low[k:e] <= target
    i_s = int(np.argmax(hit_s)) if hit_s.any() else None
    i_t = int(np.argmax(hit_t)) if hit_t.any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        return -1.0
    if i_t is not None:
        return 1.0
    return float(side * (mid_close[e - 1] - entry) / risk)


def trades(symbol: str) -> List[Dict[str, Any]]:
    q = load(symbol)
    if q is None:
        return []
    t = q["time"].astype(np.int64)
    hour = (t % 86400) // 3600
    mid, hi, lo = q["mid_close"], q["mid_high"], q["mid_low"]
    atr = h1_atr_per_minute(q)
    part = participation(q["ticks"], hour)
    rows: List[Dict[str, Any]] = []
    last = -10 ** 9
    start = MEAN_MIN + 2 * STALL_MIN + 1
    longest = max(HORIZONS)
    for k in range(start, t.size - longest):
        a = atr[k]
        if not np.isfinite(a) or a <= 0 or hour[k] == ROLLOVER_HOUR:
            continue
        if t[k] - last < COOLDOWN_MIN * 60:
            continue
        pot = bucket_of(part[k])
        if pot is None:
            continue
        mean4h = float(mid[k - MEAN_MIN:k].mean())
        extension = (mid[k] - mean4h) / a
        velocity = abs(mid[k] - mid[k - VEL_MIN]) / a
        if extension > 0:
            stalled = float(hi[k - STALL_MIN:k + 1].max()) <= float(hi[k - 2 * STALL_MIN:k - STALL_MIN].max())
        else:
            stalled = float(lo[k - STALL_MIN:k + 1].min()) >= float(lo[k - 2 * STALL_MIN:k - STALL_MIN].min())
        extended = abs(extension) >= EXTENDED_ATR
        if extended and stalled and velocity <= VELOCITY_MAX_ATR:
            state = "REVERSION_READY"
        elif velocity > VELOCITY_MAX_ATR:
            state = "MOMENTUM_RUNNING"
        else:
            state = "QUIET"
        move = mid[k] - mid[k - VEL_MIN]
        if move == 0:
            continue
        follow = 1 if move > 0 else -1
        fade = (-1 if extension > 0 else 1) if extended else -follow
        risk = STOP_ATR * a
        entry = float(mid[k])
        row = {"symbol": symbol, "ts": int(t[k]), "state": state, "bucket": pot}
        got = False
        for action, side in (("follow", follow), ("fade", fade), ("always_buy", 1)):
            for hold in HORIZONS:
                r = walk_mid(hi, lo, mid, k, hold, side, entry, risk)
                if r is None:
                    continue
                row[f"{action}_{hold}"] = r
                got = True
        if got:
            rows.append(row)
            last = t[k]
    return rows


def summarise(rows: List[Mapping[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    vals = np.array([r[key] for r in rows if key in r], dtype=float)
    if vals.size < 100:
        return None
    won = vals > 0
    # a symmetric-barrier coin flip is 50% and 0.000R; the interesting quantity
    # is how far from that this sits, in standard errors of its own mean
    se = float(vals.std(ddof=1) / np.sqrt(vals.size)) if vals.size > 1 else float("nan")
    return {"n": int(vals.size), "won_pct": round(100 * float(won.mean()), 1),
            "mean_r": round(float(vals.mean()), 4), "z": round(float(vals.mean() / se), 2) if se else None}


def get_status() -> Dict[str, Any]:
    return {"component": "pure_direction", "horizons": list(HORIZONS),
            "asks": "any directional edge before any cost"}


def self_check() -> Dict[str, Any]:
    """A random walk must score 50% and 0.000R through this harness."""
    rng = np.random.default_rng(11)
    n = 60000
    mid = 100 + np.cumsum(rng.normal(0, 0.01, n))
    hi = mid + 0.002
    lo = mid - 0.002
    out = [walk_mid(hi, lo, mid, k, 1440, 1, float(mid[k]), 0.05)
           for k in range(1000, n - 1440, 200)]
    vals = np.array([v for v in out if v is not None])
    won = float((vals > 0).mean())
    checks = {"enough_samples": vals.size > 200,
              "random_walk_is_a_coin_flip": abs(won - 0.5) < 0.05,
              "random_walk_pays_nothing": abs(float(vals.mean())) < 0.08,
              "tick_dir_present": TICK_DIR.exists()}
    return {"component": "pure_direction", "ok": all(checks.values()), "checks": checks,
            "control_won_pct": round(100 * won, 1), "control_mean_r": round(float(vals.mean()), 4)}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    a = ap.parse_args()
    if a.cmd == "check":
        print(json.dumps(self_check(), indent=1))
        raise SystemExit

    rows: List[Dict[str, Any]] = []
    with Pool(8) as pool:
        for got in pool.imap_unordered(trades, SYMBOLS):
            rows += got
    print(f"{len(rows)} entries on mid price -- NO spread, NO commission\n")
    print("A coin flip scores 50.0% and +0.0000R. z is the distance from zero"
          " in standard errors.\n")
    summary: Dict[str, Any] = {}
    print(f"{'state':18s} {'action':11s} {'horizon':>8s} {'n':>6s} {'won':>7s} {'mean R':>9s} {'z':>7s}")
    for state in ("ALL", "REVERSION_READY", "MOMENTUM_RUNNING", "QUIET"):
        sel = rows if state == "ALL" else [r for r in rows if r["state"] == state]
        for action in ACTIONS:
            for hold in HORIZONS:
                rep = summarise(sel, f"{action}_{hold}")
                if rep is None:
                    continue
                flag = ""
                if rep["z"] is not None and abs(rep["z"]) >= 3:
                    flag = "  <-- 3 sigma"
                print(f"{state:18s} {action:11s} {hold:8d} {rep['n']:6d} {rep['won_pct']:6.1f}% "
                      f"{rep['mean_r']:+9.4f} {rep['z']:+7.2f}{flag}")
                summary.setdefault(state, {})[f"{action}_{hold}"] = rep
        print()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "pure_direction.json").write_text(json.dumps(summary, indent=1))
    print("written: reports/pure_direction.json")
