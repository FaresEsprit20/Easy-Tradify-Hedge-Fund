"""Imbalances (FVG), displacement bars and supply/demand zones on closed mid bars."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FVG_MIN_ATR = 0.10
DISPLACEMENT_ATR = 1.2
DISPLACEMENT_BODY = 0.6
BASE_MAX_ATR = 1.2
BASE_BODY_MAX = 0.5
DEPARTURE_ATR = 1.5
DEPARTURE_WITHIN = 3


def fvg(high: np.ndarray, low: np.ndarray, atr: np.ndarray, side: int):
    """Per bar i: (flag, top, bottom). Bullish (side=+1): low[i] > high[i-2]."""
    n = len(high)
    flag = np.zeros(n, dtype=bool)
    top = np.full(n, np.nan)
    bottom = np.full(n, np.nan)
    if n < 3:
        return flag, top, bottom
    h2, l2 = np.r_[np.nan, np.nan, high[:-2]], np.r_[np.nan, np.nan, low[:-2]]
    with np.errstate(invalid="ignore"):
        if side > 0:
            gap = low - h2
            flag = gap >= FVG_MIN_ATR * atr
            top, bottom = np.where(flag, low, np.nan), np.where(flag, h2, np.nan)
        else:
            gap = l2 - high
            flag = gap >= FVG_MIN_ATR * atr
            top, bottom = np.where(flag, l2, np.nan), np.where(flag, high, np.nan)
    return flag, top, bottom


def displacement(open_, high, low, close, atr) -> np.ndarray:
    """+1 bullish displacement bar, -1 bearish, 0 none."""
    rng = high - low
    body = np.abs(close - open_)
    with np.errstate(invalid="ignore"):
        ok = (rng >= DISPLACEMENT_ATR * atr) & (body >= DISPLACEMENT_BODY * rng)
    return np.where(ok, np.sign(close - open_), 0).astype(np.int8)


@dataclass
class Zone:
    side: int              # +1 demand, -1 supply
    proximal: float
    distal: float
    base_start: int
    base_end: int
    departure_idx: int     # available at the close of this bar
    leg_extreme: float     # highest high (demand) / lowest low (supply) from base start to departure
    departure_atr: float   # departure distance in ATR


def supply_demand_zones(open_, high, low, close, atr) -> list[Zone]:
    n = len(close)
    rng = high - low
    body = np.abs(close - open_)
    with np.errstate(invalid="ignore", divide="ignore"):
        small = (rng > 0) & (body <= BASE_BODY_MAX * rng)
    zones: list[Zone] = []
    used_bases: set[tuple[int, int]] = set()
    for d in range(4, n):
        a = atr[d]
        if not (a > 0):
            continue
        for side in (1, -1):
            found = None
            for b in (d - 1, d - 2, d - 3):
                if b < 0 or d - b > DEPARTURE_WITHIN:
                    continue
                for k in (3, 2, 1):
                    s = b - k + 1
                    if s < 0 or not small[s:b + 1].all():
                        continue
                    base_hi, base_lo = high[s:b + 1].max(), low[s:b + 1].min()
                    if base_hi - base_lo > BASE_MAX_ATR * atr[b]:
                        continue
                    if side > 0:
                        level = base_hi + DEPARTURE_ATR * atr[b]
                        if close[d] < level or close[d - 1] >= level:
                            continue
                        if b + 1 < d and (close[b + 1:d] < base_lo).any():
                            continue
                        proximal = np.maximum(open_[s:b + 1], close[s:b + 1]).max()
                        found = Zone(1, float(proximal), float(base_lo), s, b, d,
                                     float(high[s:d + 1].max()), float((close[d] - base_hi) / atr[b]))
                    else:
                        level = base_lo - DEPARTURE_ATR * atr[b]
                        if close[d] > level or close[d - 1] <= level:
                            continue
                        if b + 1 < d and (close[b + 1:d] > base_hi).any():
                            continue
                        proximal = np.minimum(open_[s:b + 1], close[s:b + 1]).min()
                        found = Zone(-1, float(proximal), float(base_hi), s, b, d,
                                     float(low[s:d + 1].min()), float((base_lo - close[d]) / atr[b]))
                    break
                if found:
                    break
            if found and (found.base_start, found.base_end) not in used_bases:
                used_bases.add((found.base_start, found.base_end))
                zones.append(found)
    return zones
