# ai/participation_ticks.py
"""
The participation finding, re-measured on true bid/ask ticks.

ai/participation_lab.py found something clean on four years of M15 bars: the
advantage of fading a move over following it rises monotonically with how
unusual that move's volume was for its hour of day.

    MOMENTUM_RUNNING, fade minus follow, gross
    THIN +0.021   NORMAL +0.037   HEAVY +0.049   VERY_HEAVY +0.070   CLIMAX +0.061

Monotone across an ordered variable, in three independent states, over 90,000
trades. The ordering is almost certainly real. The LEVEL is not trustworthy,
and that is the whole reason this file exists: the best cell was +0.0223R
gross, while the bar model is measured 0.05R optimistic against real ticks
(ai/deep_history_lab.MODEL_OPTIMISM_R). The entire claimed edge is smaller
than the known bias of the instrument that measured it, so on bars it cannot
be settled at all -- bid-only bars have already faked an edge twice in this
project.

Here there is no model to be optimistic. The M1 files in ticks_m1/ are built
from real ticks and carry both sides of the book plus an honest participation
count:

    bid/ask OHLC   fills and exits on the correct side, no spread model
    ticks          how many trades actually printed in the window
    mean_spread    what it really cost at that minute

If the ladder survives here, it is an edge. If it does not, the four-year
result was the bar model talking and the participation story dies with it.

    python -m ai.participation_ticks
    python -m ai.participation_ticks check
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
TICK_DIR = Path(os.getenv("TICK_M1_DIR") or "C:/Users/msi/tradify_study/ticks_m1")

MEAN_MIN = 240          # the 4h mean, as core/behaviour_readings.py
VEL_MIN = 15
STALL_MIN = 30
MOVE_MIN = VEL_MIN + STALL_MIN
EXTENDED_ATR = 1.0
VELOCITY_MAX_ATR = 0.3
STOP_ATR = 1.5
TARGET_R = 1.0
HOLD_MIN = 1440
COOLDOWN_MIN = 240
MIN_HOUR_HISTORY = 30
ROLLOVER_HOUR = 0
COMMISSION_PER_LOT = 7.03
RISK_USD = 4.0

BUCKET_EDGES = ((0.0, 0.8, "THIN"), (0.8, 1.3, "NORMAL"), (1.3, 2.0, "HEAVY"),
                (2.0, 3.0, "VERY_HEAVY"), (3.0, float("inf"), "CLIMAX"))
BUCKETS = tuple(n for _, _, n in BUCKET_EDGES)


def load(symbol: str) -> Optional[Dict[str, np.ndarray]]:
    path = TICK_DIR / f"{symbol}.npz"
    if not path.exists():
        return None
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def h1_atr_per_minute(q: Mapping[str, np.ndarray]) -> np.ndarray:
    """ATR of the last 14 CLOSED H1 bars, held constant across each minute."""
    t = q["time"].astype(np.int64)
    key = t // 3600
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], key.size]
    hi = np.maximum.reduceat(q["mid_high"], starts)
    lo = np.minimum.reduceat(q["mid_low"], starts)
    cl = q["mid_close"][ends - 1]
    pc = np.r_[cl[0], cl[:-1]]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    atr = np.full(tr.size, np.nan)
    if tr.size > 14:
        c = np.cumsum(np.insert(tr, 0, 0.0))
        rolling = (c[14:] - c[:-14]) / 14        # rolling[j] = ATR of hours j..j+13
        # the ATR of the 14 hours BEFORE this one, so the hour a trade is taken
        # in is not part of the volatility that sizes its own stop
        atr[14:] = rolling[:-1]
    out = np.full(t.size, np.nan)
    for i, (a, b) in enumerate(zip(starts, ends)):
        out[a:b] = atr[i]
    return out


def participation(ticks: np.ndarray, hour: np.ndarray) -> np.ndarray:
    """Ticks in the move window over the expanding mean for that hour, prior only."""
    window = np.full(ticks.size, np.nan)
    if ticks.size > MOVE_MIN:
        c = np.cumsum(np.insert(ticks.astype(float), 0, 0.0))
        window[MOVE_MIN - 1:] = c[MOVE_MIN:] - c[:-MOVE_MIN]
    out = np.full(ticks.size, np.nan)
    for h in np.unique(hour):
        idx = np.flatnonzero(hour == h)
        w = window[idx]
        ok = np.isfinite(w)
        if ok.sum() <= MIN_HOUR_HISTORY:
            continue
        counts = np.cumsum(ok.astype(float))
        sums = np.cumsum(np.where(ok, w, 0.0))
        prior_n = np.r_[0.0, counts[:-1]]
        prior_sum = np.r_[0.0, sums[:-1]]
        with np.errstate(invalid="ignore", divide="ignore"):
            mean_prior = np.where(prior_n >= MIN_HOUR_HISTORY, prior_sum / np.maximum(prior_n, 1), np.nan)
            out[idx] = np.where(mean_prior > 0, w / mean_prior, np.nan)
    return out


def bucket_of(ratio: float) -> Optional[str]:
    if not np.isfinite(ratio):
        return None
    for lo, hi, name in BUCKET_EDGES:
        if lo <= ratio < hi:
            return name
    return None


def walk(q: Mapping[str, np.ndarray], k: int, side: int, entry: float,
         stop: float, target: float) -> Optional[tuple]:
    """First touch on the correct side of the book; timeout marks to market."""
    n = q["time"].size
    e = min(n, k + HOLD_MIN)
    if k >= e:
        return None
    if side > 0:                                  # a BUY exits on the bid
        hit_s = q["bid_low"][k:e] <= stop
        hit_t = q["bid_high"][k:e] >= target
        last = float(q["bid_close"][e - 1])
    else:                                         # a SELL exits on the ask
        hit_s = q["ask_high"][k:e] >= stop
        hit_t = q["ask_low"][k:e] <= target
        last = float(q["ask_close"][e - 1])
    risk = abs(entry - stop)
    i_s = int(np.argmax(hit_s)) if hit_s.any() else None
    i_t = int(np.argmax(hit_t)) if hit_t.any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        return -1.0, False
    if i_t is not None:
        return abs(target - entry) / risk, True
    return side * (last - entry) / risk, False


def trades(symbol: str) -> List[Dict[str, Any]]:
    from ai.price_history_study import usd_per_price_unit_per_lot

    q = load(symbol)
    if q is None:
        return []
    usd = usd_per_price_unit_per_lot(symbol) or 0.0
    if usd <= 0:
        return []
    t = q["time"].astype(np.int64)
    hour = (t % 86400) // 3600
    mid, hi, lo = q["mid_close"], q["mid_high"], q["mid_low"]
    atr = h1_atr_per_minute(q)
    part = participation(q["ticks"], hour)
    rows: List[Dict[str, Any]] = []
    last: Dict[tuple, int] = {}
    start = MEAN_MIN + 2 * STALL_MIN + 1
    for k in range(start, t.size - HOLD_MIN):
        a = atr[k]
        if not np.isfinite(a) or a <= 0 or hour[k] == ROLLOVER_HOUR:
            continue
        ratio = part[k]
        pot = bucket_of(ratio)
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
        key = (state, pot)
        if t[k] - last.get(key, -10 ** 9) < COOLDOWN_MIN * 60:
            continue
        move = mid[k] - mid[k - VEL_MIN]
        if move == 0:
            continue
        follow = 1 if move > 0 else -1
        fade = (-1 if extension > 0 else 1) if extended else -follow
        risk = STOP_ATR * a
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        commission = COMMISSION_PER_LOT / rpl
        took = False
        for action, side in (("follow", follow), ("fade", fade)):
            entry = float(q["ask_open"][k] if side > 0 else q["bid_open"][k])
            got = walk(q, k, side, entry, entry - side * risk, entry + side * TARGET_R * risk)
            if got is None:
                continue
            r, won = got
            took = True
            rows.append({"symbol": symbol, "ts": int(t[k]), "state": state, "bucket": pot,
                         "action": action, "won": bool(won), "gross": float(r),
                         "net": float(r) - commission, "ratio": round(float(ratio), 3)})
        if took:
            last[key] = t[k]
    return rows


def cell(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    from ai.component_repair import study_split

    if len(rows) < 60:
        return {"n": len(rows)}
    ts = np.array([r["ts"] for r in rows], dtype=float)
    net = np.array([r["net"] for r in rows])
    gross = np.array([r["gross"] for r in rows])
    won = np.array([r["won"] for r in rows])
    _, test, hold, _, _ = study_split(ts)
    return {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1),
            "gross_r": round(float(gross.mean()), 4), "net_r": round(float(net.mean()), 4),
            "validation": round(float(net[test].mean()), 4) if test.sum() > 20 else None,
            "holdout": round(float(net[hold].mean()), 4) if hold.sum() > 20 else None}


def get_status() -> Dict[str, Any]:
    return {"component": "participation_ticks", "buckets": list(BUCKETS),
            "verifies": "ai/participation_lab.py on true bid/ask ticks"}


def self_check() -> Dict[str, Any]:
    n = 24 * 400
    hour = np.tile(np.arange(24), n // 24)
    ticks = 100.0 + 900.0 * (np.sin(hour / 24 * 2 * np.pi) + 1)
    p = participation(ticks, hour)
    ok = np.isfinite(p)
    spread = float(np.nanstd([np.nanmean(p[hour == h]) for h in range(24)]))
    checks = {"hour_cycle_removed": spread < 0.05,
              "mean_is_about_one": 0.9 < float(np.nanmean(p[ok])) < 1.1,
              "buckets_cover_the_line": bucket_of(0.5) == "THIN" and bucket_of(5.0) == "CLIMAX",
              "tick_dir_present": TICK_DIR.exists()}
    return {"component": "participation_ticks", "ok": all(checks.values()), "checks": checks}


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
    print(f"{len(rows)} trades on TRUE bid/ask ticks (no spread model, no optimism)\n")
    print(f"{'state':18s} {'volume':11s} {'action':7s} {'n':>6s} {'won':>7s} {'gross':>9s} "
          f"{'net R':>9s} {'valid':>9s} {'holdout':>9s}")
    summary: Dict[str, Any] = {}
    for state in ("REVERSION_READY", "MOMENTUM_RUNNING", "QUIET"):
        for b in BUCKETS:
            got = {}
            for action in ("follow", "fade"):
                sel = [r for r in rows if r["state"] == state and r["bucket"] == b and r["action"] == action]
                rep = cell(sel)
                got[action] = rep
                if rep.get("n", 0) < 60:
                    continue
                print(f"{state:18s} {b:11s} {action:7s} {rep['n']:6d} {rep['won_pct']:6.1f}% "
                      f"{rep['gross_r']:+9.4f} {rep['net_r']:+9.4f} "
                      f"{rep['validation'] if rep['validation'] is not None else float('nan'):+9.4f} "
                      f"{rep['holdout'] if rep['holdout'] is not None else float('nan'):+9.4f}")
            if got.get("fade", {}).get("gross_r") is not None and got.get("follow", {}).get("gross_r") is not None:
                print(f"{'':18s} {'':11s} {'fade-follow':>7s} {'':6s} {'':7s} "
                      f"{got['fade']['gross_r'] - got['follow']['gross_r']:+9.4f}   <- the ladder")
            summary.setdefault(state, {})[b] = got
        print()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "participation_ticks.json").write_text(json.dumps(summary, indent=1))
    print("written: reports/participation_ticks.json")
