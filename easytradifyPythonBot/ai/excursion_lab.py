# ai/excursion_lab.py
"""
Are the components simply wrong, or right first and then given back?

A 44% win rate is consistent with two completely different diseases:

  wrong        price goes against the call from the first minute, and the
                 stop is hit without the trade ever being in profit
  given back   price goes the called way first -- often far -- and the exit
                 gives it back

They need opposite cures. The first needs a better signal; the second needs a
better exit, and no signal work will help it. This measures which one it is,
on tick bid/ask, for the side the engine actually chose:

  favourable_at    was the trade in profit 15 / 30 / 60 / 120 / 240 minutes in
  MFE              the best it ever got, in R, and when
  MAE              the worst it ever got, in R, and when
  gave_back        of the trades that reached +X R, how many still lost

and then, from the same joint distribution, what a fixed target/stop grid
would have earned -- which says directly how high a win rate is reachable and
at what expectancy.

    python -m ai.excursion_lab
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = Path(os.getenv("PRICE_STUDY_DIR") or ROOT / "reports" / "cache" / "study")
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
REPORT_DIR = ROOT / "reports"

STOP_H1_ATR = 1.5
HOLD_MINUTES = 1440
CHECKPOINTS = (15, 30, 60, 120, 240)
MFE_LEVELS = (0.25, 0.5, 0.75, 1.0, 1.5)
TARGET_GRID = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
STOP_GRID = (0.5, 1.0, 1.5, 2.0)


def excursions(q: Mapping[str, np.ndarray], k: int, side: int, risk: float) -> Optional[Dict[str, Any]]:
    """The whole path of one trade, in R, on the correct side of the book."""
    n = q["time"].size
    end = min(n, k + HOLD_MINUTES)
    if k >= end - 10 or risk <= 0:
        return None
    entry = float(q["ask_open"][k] if side > 0 else q["bid_open"][k])
    if side > 0:
        fav = (q["bid_high"][k:end] - entry) / risk          # a long books the bid
        adv = (q["bid_low"][k:end] - entry) / risk
        marks = (q["bid_close"][k:end] - entry) / risk
    else:
        fav = (entry - q["ask_low"][k:end]) / risk           # a short books the ask
        adv = (entry - q["ask_high"][k:end]) / risk
        marks = (entry - q["ask_close"][k:end]) / risk
    run_fav = np.maximum.accumulate(fav)
    run_adv = np.minimum.accumulate(adv)
    stopped = np.flatnonzero(run_adv <= -1.0)
    stop_i = int(stopped[0]) if stopped.size else None
    # the excursions that matter are the ones before the stop closes the trade
    limit = stop_i + 1 if stop_i is not None else fav.size
    mfe = float(run_fav[:limit].max())
    mae = float(run_adv[:limit].min())
    out = {"mfe": mfe, "mae": mae,
           "mfe_minute": int(np.argmax(fav[:limit])), "stopped": stop_i is not None,
           "final": float(marks[min(limit, marks.size) - 1])}
    for cp in CHECKPOINTS:
        i = min(cp, limit - 1)
        out[f"fav_{cp}"] = bool(marks[i] > 0) if i >= 0 else None
        out[f"mark_{cp}"] = float(marks[i]) if i >= 0 else None
    return out


def collect(symbol: str) -> List[Dict[str, Any]]:
    """Every snapshot, on the side the engine chose."""
    from ai.price_history_study import usd_per_price_unit_per_lot
    from core.strategy_groups import market_direction

    path = STUDY_DIR / f"{symbol}.labelled.jsonl.gz"
    qpath = QUOTE_DIR / f"{symbol}.npz"
    if not path.exists() or not qpath.exists():
        return []
    usd = usd_per_price_unit_per_lot(symbol) or 0.0
    with np.load(qpath) as z:
        q = {k: z[k] for k in z.files}
    qt = q["time"]
    rows: List[Dict[str, Any]] = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                break
            o = rec.get("outcome") or {}
            h1 = o.get("h1_atr")
            d = market_direction(rec.get("direction"))
            if not h1 or d not in (1, -1):
                continue
            k = int(np.searchsorted(qt, rec["ts"]))
            risk = STOP_H1_ATR * h1
            rpl = risk * usd
            if rpl <= 0 or 0.01 * rpl > 4.4 or k >= qt.size - HOLD_MINUTES:
                continue
            ex = excursions(q, k, d, risk)
            if ex:
                ex.update(symbol=symbol, ts=int(rec["ts"]), side=d, commission_r=7.03 / rpl)
                rows.append(ex)
    return rows


def diagnose(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    mfe = np.array([r["mfe"] for r in rows])
    mae = np.array([r["mae"] for r in rows])
    stopped = np.array([r["stopped"] for r in rows])
    out: Dict[str, Any] = {"n": len(rows)}
    out["was_right_at"] = {str(cp): round(100 * float(np.mean([r[f"fav_{cp}"] for r in rows])), 1)
                           for cp in CHECKPOINTS}
    out["reached_mfe"] = {str(lv): round(100 * float((mfe >= lv).mean()), 1) for lv in MFE_LEVELS}
    out["gave_back"] = {}
    for lv in MFE_LEVELS:
        reached = mfe >= lv
        if reached.sum() > 50:
            out["gave_back"][str(lv)] = round(100 * float(stopped[reached].mean()), 1)
    out["median_mfe"] = round(float(np.median(mfe)), 3)
    out["median_mae"] = round(float(np.median(mae)), 3)
    out["median_mfe_minute"] = int(np.median([r["mfe_minute"] for r in rows]))
    out["stopped_pct"] = round(100 * float(stopped.mean()), 1)
    return out


def target_grid(rows: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """What a fixed target/stop would have earned, from the same paths.

    The stop is scaled with the grid, so a 0.5 stop means half the distance and
    twice the lot -- R stays R, and commission per R doubles with it.
    """
    mfe = np.array([r["mfe"] for r in rows])
    mae = np.array([r["mae"] for r in rows])
    final = np.array([r["final"] for r in rows])
    comm = np.array([r["commission_r"] for r in rows])
    grid = []
    for stop in STOP_GRID:
        for target in TARGET_GRID:
            # in units of the original R: a stop at `stop` R, a target at `target` R
            hit_stop = mae <= -stop
            hit_target = mfe >= target
            # stop first unless the target was reached earlier: approximated by
            # requiring the target to be reached and the stop not
            win = hit_target & ~hit_stop
            loss = hit_stop
            open_end = ~win & ~loss
            r_per = np.where(win, target, np.where(loss, -stop, final))
            scale = 1.0 / stop                       # the same dollar risk over a shorter stop
            net = r_per * scale - comm * scale
            grid.append({"stop_r": stop, "target_r": target,
                         "win_pct": round(100 * float(win.mean()), 1),
                         "loss_pct": round(100 * float(loss.mean()), 1),
                         "open_pct": round(100 * float(open_end.mean()), 1),
                         "net_r": round(float(net.mean()), 4)})
    return grid


def get_status() -> Dict[str, Any]:
    return {"component": "excursion_lab", "checkpoints": list(CHECKPOINTS), "stop_h1_atr": STOP_H1_ATR}


def self_check() -> Dict[str, Any]:
    n = 300
    q = {"time": np.arange(n) * 60}
    for f in ("bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low", "ask_close"):
        q[f] = np.full(n, 1.0)
    # goes +0.8R in our favour and stays there a while, then reverses
    # through the stop -- the "right, then gave it back" shape
    q["bid_high"][10:40] = 1.008
    q["bid_close"][10:40] = 1.008
    q["bid_low"][100] = 0.985
    ex = excursions(q, 0, 1, 0.01)
    assert ex is not None
    assert round(ex["mfe"], 2) == 0.80, ex["mfe"]         # it WAS right, by 0.8R
    assert ex["stopped"] is True                          # and gave it all back
    assert ex["fav_15"] is True and ex["mfe_minute"] == 10
    return {"ok": True}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
        raise SystemExit
    rows: List[Dict[str, Any]] = []
    with Pool(8) as pool:
        for got in pool.imap_unordered(collect, SYMBOLS):
            rows += got
    print(f"{len(rows)} trades on the engine's own side\n")
    d = diagnose(rows)
    print("WAS THE CALL RIGHT, MINUTES IN?")
    for cp, pct in d["was_right_at"].items():
        print(f"   after {cp:>4s} min: {pct:5.1f}% in profit")
    print(f"\nHOW FAR IT GOT (median MFE {d['median_mfe']}R at minute {d['median_mfe_minute']}, "
          f"median MAE {d['median_mae']}R)")
    for lv, pct in d["reached_mfe"].items():
        gave = d["gave_back"].get(lv)
        extra = f"   -- of those, {gave}% still ended stopped" if gave is not None else ""
        print(f"   reached +{lv}R: {pct:5.1f}%{extra}")
    print(f"\nstopped out: {d['stopped_pct']}%")
    grid = target_grid(rows)
    print("\nWHAT A FIXED TARGET/STOP WOULD HAVE DONE (same paths)")
    print(f"   {'stop':>5s} {'target':>7s} {'win':>7s} {'loss':>7s} {'net R':>9s}")
    for g in sorted(grid, key=lambda x: -x["win_pct"])[:12]:
        print(f"   {g['stop_r']:5.2f} {g['target_r']:7.2f} {g['win_pct']:6.1f}% {g['loss_pct']:6.1f}% {g['net_r']:+9.4f}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "excursion_lab.json").write_text(json.dumps({"diagnosis": d, "grid": grid}, indent=1))
