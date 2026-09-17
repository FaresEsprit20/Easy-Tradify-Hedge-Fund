# ai/management_lab.py
"""
How the trade is MANAGED, for the same entries.

Every study so far asked whether the engine can pick a side, and the answer is
no: 44% of its trades finish positive against 43.5% for a coin. That measures
one half of expectancy. The other half has never been measured here at all --
what happens after the entry: whether the stop moves, whether part comes off
early, whether it trails, how long it is given, and whether waiting for a
better fill pays for the trades it misses.

Those levers change money without needing any direction skill, so they are
worth measuring before another direction idea.

Every variant is run on the SAME entries (both sides of every snapshot, so no
selection sneaks in), filled and exited on tick quote bars -- a BUY enters at
the ask and exits on the bid, a SELL the other way -- with commission charged
at a lot sized to the $4 risk. Baseline is the live geometry: stop 1.5 x H1
ATR, target 1R, 24 hours.

    python -m ai.management_lab
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = Path(os.getenv("PRICE_STUDY_DIR") or ROOT / "reports" / "cache" / "study")
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
REPORT_DIR = ROOT / "reports"

HOLD_MINUTES = 1440
STOP_H1_ATR = 1.5
TARGET_R = 1.0
MIN_TRADES = 200


# ============================================================
# ONE TRADE, MANAGED
# ============================================================

def walk(q: Mapping[str, np.ndarray], k: int, side: int, entry: float, risk: float,
         target_r: float = TARGET_R, hold: int = HOLD_MINUTES,
         breakeven_at: Optional[float] = None, partial_at: Optional[float] = None,
         partial_fraction: float = 0.5, trail_atr: Optional[float] = None,
         atr_price: Optional[float] = None,
         quick_take_r: Optional[float] = None, quick_take_minutes: int = 60) -> Optional[float]:
    """Net R of one managed trade, minute by minute on quote bars.

    breakeven_at   move the stop to entry once this many R is seen
    partial_at     close `partial_fraction` at this many R, the rest runs on
    trail_atr      trail the stop this many ATR behind the best price seen
    quick_take_r   take the profit if it arrives within quick_take_minutes --
                   measured: a trade whose best point comes in the first hour
                   holds only 2.8% of the time, against 66.9% for one still
                   making progress after four hours. Early profit is noise.
    """
    n = q["time"].size
    end = min(n, k + hold)
    if k >= end or risk <= 0:
        return None
    if side > 0:                       # long: exits read the bid
        high, low, close = q["bid_high"][k:end], q["bid_low"][k:end], q["bid_close"][k:end]
    else:                              # short: exits read the ask
        high, low, close = q["ask_high"][k:end], q["ask_low"][k:end], q["ask_close"][k:end]
    stop = entry - side * risk
    target = entry + side * target_r * risk
    booked = 0.0                       # R already taken off the table
    size = 1.0
    best = entry
    for i in range(high.size):
        favourable = (high[i] - entry) * side if side > 0 else (entry - low[i]) * side * -1
        favourable = (high[i] - entry) if side > 0 else (entry - low[i])
        adverse_hit = (low[i] <= stop) if side > 0 else (high[i] >= stop)
        target_hit = (high[i] >= target) if side > 0 else (low[i] <= target)
        # the order inside a minute is unknowable: the stop is assumed first
        if adverse_hit:
            return booked + size * side * (stop - entry) / risk
        if quick_take_r is not None and i <= quick_take_minutes and favourable >= quick_take_r * risk:
            return booked + size * quick_take_r
        if partial_at is not None and size > 0.5 and favourable >= partial_at * risk:
            booked += partial_fraction * partial_at
            size -= partial_fraction
        if breakeven_at is not None and favourable >= breakeven_at * risk:
            stop = max(stop, entry) if side > 0 else min(stop, entry)
        if trail_atr is not None and atr_price:
            best = max(best, high[i]) if side > 0 else min(best, low[i])
            trailed = best - side * trail_atr * atr_price
            stop = max(stop, trailed) if side > 0 else min(stop, trailed)
        if target_hit:
            return booked + size * target_r
    return booked + size * side * (close[-1] - entry) / risk


VARIANTS: Dict[str, Dict[str, Any]] = {
    "live (stop 1.5 ATR, target 1R, 24h)": {},
    "target 2R": {"target_r": 2.0},
    "target 0.5R": {"target_r": 0.5},
    "breakeven at +0.5R": {"breakeven_at": 0.5},
    "breakeven at +0.3R": {"breakeven_at": 0.3},
    "half off at +0.5R, rest to 1R": {"partial_at": 0.5},
    "half off at +0.5R, rest to 2R": {"partial_at": 0.5, "target_r": 2.0},
    "trail 1 H1 ATR": {"trail_atr": 1.0},
    "trail 0.5 H1 ATR": {"trail_atr": 0.5},
    "take +0.3R if inside 60m, else 1R": {"quick_take_r": 0.3, "quick_take_minutes": 60},
    "take +0.5R if inside 60m, else 1R": {"quick_take_r": 0.5, "quick_take_minutes": 60},
    "take +0.5R if inside 120m, else 1R": {"quick_take_r": 0.5, "quick_take_minutes": 120},
    "take +0.75R if inside 60m, else 2R": {"quick_take_r": 0.75, "quick_take_minutes": 60, "target_r": 2.0},
    "take +0.5R inside 60m, else 2R": {"quick_take_r": 0.5, "quick_take_minutes": 60, "target_r": 2.0},
    "time stop 4h": {"hold": 240},
    "time stop 8h": {"hold": 480},
}


# ============================================================
# RUN
# ============================================================

def trades_for(symbol: str) -> List[Dict[str, Any]]:
    """Every snapshot's entry, both sides, with its market stop."""
    path = STUDY_DIR / f"{symbol}.labelled.jsonl.gz"
    qpath = QUOTE_DIR / f"{symbol}.npz"
    if not path.exists() or not qpath.exists():
        return []
    from ai.price_history_study import usd_per_price_unit_per_lot
    usd = usd_per_price_unit_per_lot(symbol) or 0.0
    with np.load(qpath) as z:
        q = {k: z[k] for k in z.files}
    qt = q["time"]
    out = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                break
            o = rec.get("outcome") or {}
            h1 = o.get("h1_atr")
            if not h1:
                continue
            k = int(np.searchsorted(qt, rec["ts"]))
            if k >= qt.size - HOLD_MINUTES // 2:
                continue
            risk = STOP_H1_ATR * h1
            rpl = risk * usd
            if rpl <= 0 or 0.01 * rpl > 4.4:            # unaffordable at the $4 risk
                continue
            out.append({"symbol": symbol, "ts": int(rec["ts"]), "k": k, "risk": risk,
                        "h1_atr": float(h1), "commission_r": 7.03 / rpl})
    return out


def measure(symbol: str) -> Dict[str, Any]:
    from ai.structure_lab import load_quotes

    q = load_quotes(symbol)
    if q is None:
        return {}
    rows = trades_for(symbol)
    out: Dict[str, List[Tuple[int, float]]] = {name: [] for name in VARIANTS}
    for t in rows:
        for name, kw in VARIANTS.items():
            for side in (1, -1):
                entry = float(q["ask_open"][t["k"]] if side > 0 else q["bid_open"][t["k"]])
                r = walk(q, t["k"], side, entry, t["risk"], atr_price=t["h1_atr"], **kw)
                if r is not None:
                    out[name].append((t["ts"], r - t["commission_r"]))
    return out


def report(collected: Mapping[str, List[Tuple[int, float]]]) -> Dict[str, Any]:
    from ai.component_repair import study_split

    result = {}
    for name, pairs in collected.items():
        if len(pairs) < MIN_TRADES:
            continue
        ts = np.array([p[0] for p in pairs], dtype=float)
        net = np.array([p[1] for p in pairs], dtype=float)
        train, test, hold, _, _ = study_split(ts)
        result[name] = {
            "n": len(pairs),
            "won_pct": round(100 * float((net > 0).mean()), 1),
            "net_r": round(float(net.mean()), 4),
            "holdout_won_pct": round(100 * float((net[hold] > 0).mean()), 1) if hold.any() else None,
            "holdout_net_r": round(float(net[hold].mean()), 4) if hold.any() else None,
            "validation_net_r": round(float(net[test].mean()), 4) if test.any() else None,
        }
    return result


def get_status() -> Dict[str, Any]:
    return {"component": "management_lab", "variants": len(VARIANTS), "stop_h1_atr": STOP_H1_ATR}


def self_check() -> Dict[str, Any]:
    n = 200
    q = {"time": np.arange(n) * 60}
    for f in ("bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low", "ask_close"):
        q[f] = np.full(n, 1.0)
    # price walks up 2R then collapses through the entry
    q["bid_high"][5] = 1.02
    q["bid_low"][50] = 0.97
    q["bid_close"][50] = 0.97
    plain = walk(q, 0, 1, 1.0, 0.01, target_r=5.0)                  # no management: rides it down
    be = walk(q, 0, 1, 1.0, 0.01, target_r=5.0, breakeven_at=0.5)   # stop at entry after +0.5R
    assert plain is not None and be is not None
    assert be > plain, (be, plain)
    assert abs(be) < 0.01, be                                       # breakeven means about zero
    part = walk(q, 0, 1, 1.0, 0.01, target_r=5.0, partial_at=1.0)   # half off at +1R
    assert part > plain
    return {"ok": True}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    ap.add_argument("--symbols", nargs="*", default=SYMBOLS)
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
        raise SystemExit
    merged: Dict[str, List[Tuple[int, float]]] = {name: [] for name in VARIANTS}
    with Pool(min(len(a.symbols), 8)) as pool:
        for got in pool.imap_unordered(measure, a.symbols):
            for name, pairs in (got or {}).items():
                merged[name] += pairs
    rep = report(merged)
    print(f"{'variant':38s} {'trades':>8s} {'won':>7s} {'net R':>9s} {'valid':>9s} {'HOLDOUT':>9s} {'won':>7s}")
    for name, v in sorted(rep.items(), key=lambda kv: -(kv[1]["holdout_net_r"] or -9)):
        print(f"{name:38s} {v['n']:8d} {v['won_pct']:6.1f}% {v['net_r']:+9.4f} "
              f"{v['validation_net_r']:+9.4f} {v['holdout_net_r']:+9.4f} {v['holdout_won_pct']:6.1f}%")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "management_lab.json").write_text(json.dumps(rep, indent=1))
