# ai/setup_lab.py
"""
Setup lab: complete trade setups (liquidity sweeps of session levels, their
breakout counterparts, ...) defined precisely and traded on bid/ask quotes, so
an upgrade of a strategy group is decided by what the setup EARNS, on several
market regimes, not by what a single field reads.

Quote sources (same field names: time, bid_*/ask_* OHLC per minute):
  mt5         tick-built minute quotes, broker clock (UTC+3/+2), 2026-05..
              (tick_bars.py, PRICE_QUOTE_DIR)
  dukascopy   Dukascopy BID and ASK minute candles, UTC, 2021..2026-05
              (dukascopy_m1.py, DUKASCOPY_DIR)

Trading day = New York 17:00 to 17:00 (the FX day). Sessions are UTC hours.

Setups (each mirrored for the other side):
  pdh_sweep      an M15 bar trades above the previous day's high and, within
                 RECLAIM_BARS, an M15 bar CLOSES back below it -> SELL at the
                 next minute; stop above the sweep extreme + buffer
  asia_sweep     same with the Asia session range (00:00-06:00 UTC), during
                 London hours 06:00-11:00 UTC
  pdh_break      control: an M15 close above the previous day's high that is
                 still above it RECLAIM_BARS later -> BUY
Targets: 1R, 2R and the setup's own objective (the opposite side of the level's
range midpoint). Every trade carries the features a trader would argue about:
sweep depth, bars to reclaim, hour, previous-day range, daily trend, how much
of the average daily range is already used.

    python -m ai.setup_lab run --source mt5
    python -m ai.setup_lab run --source dukascopy
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
DUKASCOPY_DIR = Path(os.getenv("DUKASCOPY_DIR") or ROOT / "reports" / "cache" / "dukascopy")
OUT_DIR = Path(os.getenv("SETUP_LAB_DIR") or ROOT / "reports" / "cache" / "setup_lab")

M15 = 900
ATR_N = 14
RECLAIM_BARS = 4
BUFFER_ATR = 0.25
HOLD_MINUTES = 1440
SESSION_HOURS = {"pdh": (6, 17), "asia": (6, 11)}
ASIA_HOURS = (0, 6)
COMMISSION_PER_LOT = 7.03
RISK_USD = 4.0


# ============================================================
# QUOTES
# ============================================================

def load_source(symbol: str, source: str) -> Optional[Dict[str, np.ndarray]]:
    """Minute quotes with a UTC time column `utc`."""
    if source == "mt5":
        path = QUOTE_DIR / f"{symbol}.npz"
        if not path.exists():
            return None
        with np.load(path) as z:
            q = {k: z[k] for k in z.files}
        q["utc"] = q["time"] - broker_offsets(q["time"])
    else:
        files = sorted(glob.glob(str(DUKASCOPY_DIR / f"{symbol}_*.npz")))
        if not files:
            return None
        parts = [dict(np.load(f)) for f in files]
        q = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        order = np.argsort(q["time"], kind="stable")
        q = {k: v[order] for k, v in q.items()}
        q["utc"] = q["time"]
    for f in ("open", "high", "low", "close"):
        if f"mid_{f}" not in q:
            q[f"mid_{f}"] = (q[f"bid_{f}"] + q[f"ask_{f}"]) / 2
    return q


def _dst_bounds(year: int):
    march = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)
    november = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
    end = november + timedelta(days=(6 - november.weekday()) % 7)
    return start.timestamp(), end.timestamp()


def us_dst(utc: np.ndarray) -> np.ndarray:
    out = np.zeros(utc.size, bool)
    years = np.array([datetime.fromtimestamp(int(t), timezone.utc).year for t in utc[[0, -1]]])
    for y in range(int(years.min()), int(years.max()) + 1):
        a, b = _dst_bounds(y)
        out |= (utc >= a) & (utc < b)
    return out


def broker_offsets(broker_time: np.ndarray) -> np.ndarray:
    """This broker: UTC+3 under US DST, UTC+2 otherwise."""
    approx = broker_time - 10800
    return np.where(us_dst(approx), 10800, 7200)


def trading_day(utc: np.ndarray) -> np.ndarray:
    """Index of the FX day (New York 17:00 to 17:00)."""
    ny = utc - np.where(us_dst(utc), 4 * 3600, 5 * 3600)
    return (ny + 7 * 3600) // 86400


# ============================================================
# BARS AND LEVELS
# ============================================================

def m15(q: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
    key = q["utc"] // M15
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], key.size]
    b = {"utc": key[starts] * M15, "open": q["mid_open"][starts],
         "high": np.maximum.reduceat(q["mid_high"], starts), "low": np.minimum.reduceat(q["mid_low"], starts),
         "close": q["mid_close"][ends - 1], "end": ends}
    pc = np.r_[b["close"][0], b["close"][:-1]]
    tr = np.maximum(b["high"] - b["low"], np.maximum(abs(b["high"] - pc), abs(b["low"] - pc)))
    atr = np.full(tr.size, np.nan)
    if tr.size > ATR_N:
        cs = np.cumsum(tr)
        atr[ATR_N:] = (cs[ATR_N:] - cs[:-ATR_N]) / ATR_N
    b["atr"] = atr
    return b


def daily_levels(q: Mapping[str, np.ndarray]) -> Dict[int, Dict[str, float]]:
    """Per FX day: high, low, open, close and the Asia-session high/low."""
    day = trading_day(q["utc"])
    hour = (q["utc"] % 86400) // 3600
    out: Dict[int, Dict[str, float]] = {}
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], day.size]
    for s, e in zip(starts, ends):
        if e - s < 600:                      # a partial day (holiday, data gap)
            continue
        d = int(day[s])
        rec = {"high": float(q["mid_high"][s:e].max()), "low": float(q["mid_low"][s:e].min()),
               "open": float(q["mid_open"][s]), "close": float(q["mid_close"][e - 1])}
        asia = (hour[s:e] >= ASIA_HOURS[0]) & (hour[s:e] < ASIA_HOURS[1])
        if asia.sum() >= 240:
            rec["asia_high"] = float(q["mid_high"][s:e][asia].max())
            rec["asia_low"] = float(q["mid_low"][s:e][asia].min())
        out[d] = rec
    return out


# ============================================================
# SETUPS
# ============================================================

def sweep_signals(b: Mapping[str, np.ndarray], day_of_bar: np.ndarray, levels: Mapping[int, Mapping[str, float]],
                  kind: str) -> List[Dict[str, Any]]:
    """Sweep-and-reclaim of the previous day's (kind 'pdh') or today's Asia
    (kind 'asia') high and low, plus the held-breakout control."""
    hour = (b["utc"] % 86400) // 3600
    lo_h, hi_h = SESSION_HOURS[kind]
    out = []
    days = np.unique(day_of_bar)
    adr = {}
    ordered = sorted(levels)
    for k, d in enumerate(ordered):
        prev = [levels[x]["high"] - levels[x]["low"] for x in ordered[max(0, k - 20):k]]
        adr[d] = float(np.mean(prev)) if len(prev) >= 10 else None
    for d in days:
        if kind == "pdh":
            ref = levels.get(int(d) - 1)
            if not ref:
                continue
            hi_level, lo_level = ref["high"], ref["low"]
        else:
            ref = levels.get(int(d))
            if not ref or "asia_high" not in ref:
                continue
            hi_level, lo_level = ref["asia_high"], ref["asia_low"]
        idx = np.flatnonzero((day_of_bar == d) & (hour >= lo_h) & (hour < hi_h))
        if idx.size < RECLAIM_BARS + 2:
            continue
        mid = (hi_level + lo_level) / 2
        prev_day = levels.get(int(d) - 1) or {}
        daily_trend = np.sign(prev_day.get("close", 0) - prev_day.get("open", 0)) if prev_day else 0
        for side_level, level, sign in (("high", hi_level, -1), ("low", lo_level, 1)):
            swept_at = None
            done_sweep = done_break = False
            for n, i in enumerate(idx):
                a = b["atr"][i]
                if not np.isfinite(a) or a <= 0:
                    continue
                beyond = b["high"][i] > level if sign < 0 else b["low"][i] < level
                closed_beyond = b["close"][i] > level if sign < 0 else b["close"][i] < level
                if swept_at is None and beyond:
                    swept_at = n
                if swept_at is not None and not done_sweep and n - swept_at <= RECLAIM_BARS and not closed_beyond:
                    seg = idx[swept_at:n + 1]
                    extreme = b["high"][seg].max() if sign < 0 else b["low"][seg].min()
                    so_far = idx[:n + 1]
                    used = (b["high"][so_far].max() - b["low"][so_far].min()) / adr[int(d)] if adr.get(int(d)) else None
                    out.append({"setup": f"{kind}_sweep", "bar": int(i), "side": sign, "level": level,
                                "extreme": float(extreme), "objective": mid if kind == "asia" else
                                (lo_level + (hi_level - lo_level) * 0.5), "atr": float(a),
                                "depth_atr": float(abs(extreme - level) / a), "bars_to_reclaim": int(n - swept_at),
                                "hour": int(hour[i]), "range_atr": float((hi_level - lo_level) / a),
                                "daily_trend_with": int(daily_trend == sign), "adr_used": used, "day": int(d)})
                    done_sweep = True
                if not done_break and closed_beyond and n + RECLAIM_BARS < idx.size:
                    later = idx[n + RECLAIM_BARS]
                    held = b["close"][later] > level if sign < 0 else b["close"][later] < level
                    if held:
                        seg = idx[n:n + RECLAIM_BARS + 1]
                        pullback = b["low"][seg].min() if sign < 0 else b["high"][seg].max()
                        out.append({"setup": f"{kind}_break", "bar": int(later), "side": -sign, "level": level,
                                    "extreme": float(pullback), "objective": None, "atr": float(b["atr"][later]),
                                    "depth_atr": float(abs(b["close"][later] - level) / b["atr"][later]),
                                    "bars_to_reclaim": RECLAIM_BARS, "hour": int(hour[later]),
                                    "range_atr": float((hi_level - lo_level) / b["atr"][later]),
                                    "daily_trend_with": int(daily_trend == -sign), "adr_used": None, "day": int(d)})
                    done_break = True
                if done_sweep and done_break:
                    break
    return out


def trade(q: Mapping[str, np.ndarray], b: Mapping[str, np.ndarray], sig: Mapping[str, Any],
          usd_per_price_per_lot: float) -> List[Dict[str, Any]]:
    from ai.price_history_study import quote_bracket

    k = int(b["end"][sig["bar"]])            # first minute after the signal bar closed
    if k >= q["time"].size - 30:
        return []
    side = sig["side"]
    entry = float(q["ask_open"][k] if side > 0 else q["bid_open"][k])
    stop = sig["extreme"] - side * BUFFER_ATR * sig["atr"]
    risk = side * (entry - stop)
    if risk <= 0:
        return []
    rows = []
    targets = [("1R", risk), ("2R", 2 * risk)]
    if sig.get("objective") is not None and side * (sig["objective"] - entry) > 0:
        targets.append(("objective", side * (sig["objective"] - entry)))
    rpl = risk * usd_per_price_per_lot
    for name, reward in targets:
        br = quote_bracket(q, k, HOLD_MINUTES, risk, reward, side)
        if not br:
            continue
        rows.append({**{kk: v for kk, v in sig.items() if kk != "bar"}, "target": name, "reward_r": round(reward / risk, 3),
                     "utc": int(q["utc"][k]), "result": br["result"], "r": br["r"],
                     "commission_r": round(COMMISSION_PER_LOT / rpl, 4), "affordable": bool(0.01 * rpl <= RISK_USD * 1.1),
                     "risk_atr": round(risk / sig["atr"], 3)})
    return rows


def run_symbol(args) -> Dict[str, Any]:
    symbol, source = args
    from ai.price_history_study import usd_per_price_unit_per_lot

    q = load_source(symbol, source)
    usd = usd_per_price_unit_per_lot(symbol)
    if q is None or not usd:
        return {"symbol": symbol, "error": "no data"}
    b = m15(q)
    day_of_bar = trading_day(b["utc"])
    levels = daily_levels(q)
    rows = []
    for kind in ("pdh", "asia"):
        for sig in sweep_signals(b, day_of_bar, levels, kind):
            for row in trade(q, b, sig, usd):
                rows.append({"symbol": symbol, **row})
    out = OUT_DIR / source
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{symbol}.json").write_text(json.dumps(rows))
    return {"symbol": symbol, "trades": len(rows)}


def self_check() -> Dict[str, Any]:
    utc = np.array([datetime(2026, 7, 1, 20, 59, tzinfo=timezone.utc).timestamp(),
                    datetime(2026, 7, 1, 21, 0, tzinfo=timezone.utc).timestamp()], dtype=np.int64)
    d = trading_day(utc)
    assert d[1] == d[0] + 1, d              # 17:00 New York (EDT) = 21:00 UTC starts the FX day
    bt = np.array([int(datetime(2026, 7, 1, 12, tzinfo=timezone.utc).timestamp()) + 10800])
    assert broker_offsets(bt)[0] == 10800
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "setup_lab", "setups": ["pdh_sweep", "pdh_break", "asia_sweep", "asia_break"],
            "reclaim_bars": RECLAIM_BARS, "buffer_atr": BUFFER_ATR}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "check"))
    ap.add_argument("--source", default="mt5", choices=("mt5", "dukascopy"))
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
    else:
        from ai.price_history_study import SYMBOLS
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            for res in pool.imap_unordered(run_symbol, [(s, a.source) for s in SYMBOLS]):
                print(res, flush=True)
