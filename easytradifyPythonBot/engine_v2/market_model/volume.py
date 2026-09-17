"""Volume services: developing daily VWAP and prior-day value area (POC/VAH/VAL)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

VALUE_AREA = 0.70
BIN_ATR = 0.02


def developing_vwap(time: np.ndarray, price: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """VWAP of the broker day so far, known at each M1 close."""
    day = time // 86400
    w = np.where(np.isfinite(volume) & (volume > 0), volume, 1e-9)
    df = pd.DataFrame({"day": day, "pv": price * w, "w": w})
    g = df.groupby("day", sort=False)
    return (g["pv"].cumsum() / g["w"].cumsum()).to_numpy()


@dataclass
class DayProfile:
    day: int        # broker day number (epoch // 86400)
    poc: float
    vah: float
    val: float
    high: float
    low: float


def day_profiles(time: np.ndarray, price: np.ndarray, high: np.ndarray, low: np.ndarray,
                 volume: np.ndarray, d1_atr_by_day: dict[int, float]) -> dict[int, DayProfile]:
    """Profile of each complete broker day. Use profile[day - 1] during `day`."""
    day = time // 86400
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(day)]
    out: dict[int, DayProfile] = {}
    prev_atr = None
    for s, e in zip(starts, ends):
        dnum = int(day[s])
        a = d1_atr_by_day.get(dnum - 1) or prev_atr
        prev_atr = d1_atr_by_day.get(dnum, prev_atr)
        if not a or e - s < 60:
            continue
        step = BIN_ATR * a
        p = price[s:e]
        w = volume[s:e]
        w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
        if w.sum() <= 0:
            w = np.ones_like(p)
        lo = p.min()
        bins = np.floor((p - lo) / step).astype(np.int64)
        hist = np.bincount(bins, weights=w)
        poc_b = int(np.argmax(hist))
        total = hist.sum()
        a_lo, a_hi, acc = poc_b, poc_b, hist[poc_b]
        while acc < VALUE_AREA * total and (a_lo > 0 or a_hi < len(hist) - 1):
            below = hist[a_lo - 1] if a_lo > 0 else -1.0
            above = hist[a_hi + 1] if a_hi < len(hist) - 1 else -1.0
            if above >= below:
                a_hi += 1
                acc += above
            else:
                a_lo -= 1
                acc += below
        out[dnum] = DayProfile(dnum, lo + (poc_b + 0.5) * step, lo + (a_hi + 1) * step, lo + a_lo * step,
                               float(high[s:e].max()), float(low[s:e].min()))
    return out
