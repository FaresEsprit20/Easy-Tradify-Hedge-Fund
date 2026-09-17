# ai/participation_lab.py
"""
Why did price move? Nothing in the system has ever asked.

Every reading in core/state_readings.py answers WHERE price is, and all
thirteen land on the 44.6% baseline. core/behaviour_readings.py added what
price is DOING, and that separates a fade from a follow by 0.026-0.039R --
real, stable across all three periods, and still short of the ~0.045R toll.

This asks the third question. A move fades when it was caused by something
that exhausts: a stop-run, a thin push through an empty book, one order in a
quiet hour. A move continues when it carries information. Those two look
identical on a price chart and completely different in participation, and the
bars have carried tick volume the whole time.

    hypothesis   fade a move that is NOT backed by participation
                 follow -- or at least do not fade -- one that is

The normalisation is the part that decides whether this measures anything.
Volume has a violent time-of-day cycle, so raw volume would only rediscover
that London is busier than Tokyo, and a "high participation" bucket would be
a London bucket. Each bar is therefore compared against the expanding mean
for its OWN hour of day, computed from prior bars only -- participation means
"unusual for this hour", and the measure cannot see the future.

Both barriers, both actions and gross-of-commission numbers are reported, so
it is visible whether a cell clears the toll or merely looks better than its
neighbour.

    python -m ai.participation_lab
    python -m ai.participation_lab check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from ai.mean_reversion_lab import (COMMISSION_PER_LOT, COOLDOWN_BARS, HOLD_BARS, MAX_COST_SHARE,
                                   RISK_USD, STALL_BARS, STOP_ATR, TARGET_R, cost_share, series)
from ai.strategy_selector_lab import (COMPRESSION_LOOKBACK, EXTENDED_ATR, MEAN_BARS, VEL_BARS,
                                      behaviour_columns, state_of)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

MOVE_BARS = VEL_BARS + STALL_BARS      # the window whose participation is measured
MIN_HOUR_HISTORY = 30                  # prior same-hour bars before the ratio means anything
# A ladder rather than three bins, because the first run came back monotonic:
# fade-minus-follow rose THIN +0.021 -> NORMAL +0.037 -> HEAVY +0.062 inside
# MOMENTUM_RUNNING, and rose in REVERSION_READY and EXPANDING too. Monotonic
# across an ordered variable in three independent states is the evidence; the
# ladder asks how far up it goes before it turns over.
BUCKET_EDGES = ((0.0, 0.8, "THIN"), (0.8, 1.3, "NORMAL"), (1.3, 2.0, "HEAVY"),
                (2.0, 3.0, "VERY_HEAVY"), (3.0, float("inf"), "CLIMAX"))
BUCKETS = tuple(name for _, _, name in BUCKET_EDGES)
THIN_BELOW = 0.8
HEAVY_ABOVE = 1.3


def participation(s: Mapping[str, np.ndarray]) -> np.ndarray:
    """Window volume over the expanding mean for that hour of day, prior only.

    NaN until an hour has MIN_HOUR_HISTORY prior observations, so early bars
    are excluded rather than compared against a mean built from two samples.
    """
    vol, hour = s["volume"], s["hour"]
    window = np.full(vol.size, np.nan)
    if vol.size > MOVE_BARS:
        c = np.cumsum(np.insert(vol, 0, 0.0))
        window[MOVE_BARS - 1:] = c[MOVE_BARS:] - c[:-MOVE_BARS]

    out = np.full(vol.size, np.nan)
    for h in np.unique(hour):
        idx = np.flatnonzero(hour == h)
        w = window[idx]
        ok = np.isfinite(w)
        if ok.sum() <= MIN_HOUR_HISTORY:
            continue
        # expanding mean of the PRIOR same-hour windows: shift by one so the
        # bar being judged is never part of its own reference
        vals = np.where(ok, w, 0.0)
        counts = np.cumsum(ok.astype(float))
        sums = np.cumsum(vals)
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


def trades(symbol: str) -> List[Dict[str, Any]]:
    from ai.deep_history_lab import bracket_on_bid_bars, spread_pips, spread_table, ROLLOVER_BROKER_HOURS
    from ai.price_history_study import symbol_specs, usd_per_price_unit_per_lot

    s = series(symbol)
    if s is None:
        return []
    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    usd = usd_per_price_unit_per_lot(symbol)
    if not pip or not usd:
        return []
    spread = spread_pips(spread_table(), symbol, s["hour"]) * pip
    close, atr, low, high = s["close"], s["atr"], s["low"], s["high"]
    c = behaviour_columns(s)
    part = participation(s)
    share = None
    rows: List[Dict[str, Any]] = []
    last: Dict[tuple, int] = {}
    start = max(MEAN_BARS + 2 * STALL_BARS, COMPRESSION_LOOKBACK) + 1
    for i in range(start, close.size - HOLD_BARS - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0 or s["hour"][i] in ROLLOVER_BROKER_HOURS:
            continue
        state = state_of(c, i)
        pot = bucket_of(part[i])
        if state is None or pot is None:
            continue
        key = (state, pot)
        if i - last.get(key, -10 ** 9) < COOLDOWN_BARS:
            continue
        move = close[i] - close[i - VEL_BARS]
        if move == 0:
            continue
        follow = 1 if move > 0 else -1
        ext = c["extension"][i]
        fade = (-1 if ext > 0 else 1) if abs(ext) >= EXTENDED_ATR else -follow
        risk = STOP_ATR * a
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        if share is None:
            share = cost_share(symbol, float(a))
        commission = COMMISSION_PER_LOT / rpl
        k = i + 1
        sl = slice(k, k + HOLD_BARS)
        for action, side in (("follow", follow), ("fade", fade)):
            entry = float(close[i] + (spread[i] if side > 0 else 0.0))
            stop = entry - side * risk
            target = entry + side * TARGET_R * risk
            result, r = bracket_on_bid_bars(low[sl], high[sl], close[sl], s["hour"][sl],
                                            spread[sl], side, entry, stop, target)
            if result == "NONE":
                continue
            rows.append({"symbol": symbol, "ts": int(s["t"][k]), "state": state, "bucket": pot,
                         "action": action, "won": result == "TARGET", "gross": r,
                         "net": r - commission, "ratio": round(float(part[i]), 3),
                         # commission in R falls as the market's own volatility
                         # rises: risk is a fixed $4, so a wider H1 ATR means a
                         # smaller lot carries it and the fixed $7.03 round trip
                         # is a smaller fraction of the risk. Kept per trade so
                         # the toll can be conditioned on rather than assumed.
                         "commission_r": round(float(commission), 4),
                         "cost_share": share})
        last[key] = i
    return rows


def cell(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    from ai.deep_history_lab import periods

    if len(rows) < 100:
        return {"n": len(rows)}
    ts = np.array([r["ts"] for r in rows], dtype=float)
    net = np.array([r["net"] for r in rows])
    gross = np.array([r["gross"] for r in rows])
    won = np.array([r["won"] for r in rows])
    out = {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1),
           "gross_r": round(float(gross.mean()), 4), "net_r": round(float(net.mean()), 4)}
    for name, m in periods(ts).items():
        out[name] = round(float(net[m].mean()), 4) if m.sum() > 30 else None
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "participation_lab", "buckets": list(BUCKETS),
            "asks": "was the move backed by participation"}


def self_check() -> Dict[str, Any]:
    """The normaliser must remove the hour-of-day cycle and see no future."""
    n = 24 * 400
    hour = np.tile(np.arange(24), n // 24)
    # a violent intraday cycle plus one genuine burst at a quiet hour
    vol = 100.0 + 900.0 * (np.sin(hour / 24 * 2 * np.pi) + 1)
    s = {"volume": vol.copy(), "hour": hour}
    flat = participation(s)
    ok = np.isfinite(flat)
    spread_across_hours = float(np.nanstd([np.nanmean(flat[hour == h]) for h in range(24)]))

    burst = vol.copy()
    burst[-5] *= 20
    p_burst = participation({"volume": burst, "hour": hour})
    # the bar BEFORE the burst must be unaffected: no lookahead
    no_lookahead = abs(float(p_burst[-7]) - float(flat[-7])) < 1e-9
    checks = {
        "hour_cycle_removed": spread_across_hours < 0.05,
        "mean_is_about_one": 0.9 < float(np.nanmean(flat[ok])) < 1.1,
        "burst_reads_heavy": float(np.nanmax(p_burst[-5:])) > HEAVY_ABOVE,
        "no_lookahead": no_lookahead,
        "early_bars_excluded": not np.isfinite(flat[0]),
    }
    return {"component": "participation_lab", "ok": all(checks.values()), "checks": checks,
            "hour_spread": round(spread_across_hours, 5)}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS
    from ai.strategy_selector_lab import STATES

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    args = ap.parse_args()
    if args.cmd == "check":
        print(json.dumps(self_check(), indent=1))
        raise SystemExit

    rows: List[Dict[str, Any]] = []
    with Pool(8) as pool:
        for got in pool.imap_unordered(trades, SYMBOLS):
            rows += got
    cheap = [r for r in rows if (r.get("cost_share") or 1) <= MAX_COST_SHARE]
    print(f"{len(rows)} trades, {len(cheap)} inside the cost gate\n")
    print("Does participation say whether to fade? gross is before commission.\n")
    print(f"{'state':18s} {'volume':8s} {'action':7s} {'n':>6s} {'won':>7s} {'gross':>9s} "
          f"{'net R':>9s} {'disc':>9s} {'valid':>9s} {'holdout':>9s}")
    summary: Dict[str, Any] = {}
    for state in STATES:
        for b in BUCKETS:
            got = {}
            for action in ("follow", "fade"):
                sel = [r for r in cheap if r["state"] == state and r["bucket"] == b and r["action"] == action]
                rep = cell(sel)
                got[action] = rep
                if rep.get("n", 0) < 100:
                    continue
                print(f"{state:18s} {b:8s} {action:7s} {rep['n']:6d} {rep['won_pct']:6.1f}% "
                      f"{rep['gross_r']:+9.4f} {rep['net_r']:+9.4f} "
                      + " ".join(f"{(rep.get(p) if rep.get(p) is not None else float('nan')):+9.4f}"
                                 for p in ("discovery", "validation", "holdout")))
            if got.get("fade", {}).get("net_r") is not None and got.get("follow", {}).get("net_r") is not None:
                print(f"{'':18s} {'':8s} {'fade-follow':>7s} {'':6s} {'':7s} "
                      f"{got['fade']['gross_r'] - got['follow']['gross_r']:+9.4f}")
            summary.setdefault(state, {})[b] = got
        print()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "participation_lab.json").write_text(json.dumps(summary, indent=1))
    print("written: reports/participation_lab.json")
