"""Market structure: ATR-threshold zigzag swings, trend by structure, BOS/CHoCH events.

Causality: a swing is only known at `available_idx` (the bar whose close confirmed the reversal).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SWING_ATR = 1.0
UP, DOWN, RANGE = 1, -1, 0


@dataclass
class Swings:
    kind: np.ndarray          # +1 swing high, -1 swing low
    price: np.ndarray
    idx: np.ndarray           # bar index of the extreme
    available_idx: np.ndarray  # bar index whose close confirmed it


def zigzag(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray,
           threshold: float = SWING_ATR) -> Swings:
    n = len(close)
    kinds, prices, idxs, avail = [], [], [], []
    finite = np.flatnonzero(np.isfinite(atr) & (atr > 0))
    if len(finite) == 0:
        return Swings(np.array([], np.int8), np.array([]), np.array([], np.int64), np.array([], np.int64))
    start = int(finite[0])
    direction = 0  # +1: rising leg (waiting for a swing high), -1: falling leg (waiting for a swing low)
    hi_p, hi_i, lo_p, lo_i = high[start], start, low[start], start
    for i in range(start + 1, n):
        a = atr[i]
        if not (a > 0):
            continue
        th = threshold * a
        if direction >= 0 and high[i] > hi_p:
            hi_p, hi_i = high[i], i
        if direction <= 0 and low[i] < lo_p:
            lo_p, lo_i = low[i], i
        if direction >= 0 and close[i] <= hi_p - th:
            kinds.append(1); prices.append(hi_p); idxs.append(hi_i); avail.append(i)
            direction = -1
            seg = low[hi_i:i + 1]
            k = int(np.argmin(seg))
            lo_p, lo_i = float(seg[k]), hi_i + k
        elif direction <= 0 and close[i] >= lo_p + th:
            kinds.append(-1); prices.append(lo_p); idxs.append(lo_i); avail.append(i)
            direction = 1
            seg = high[lo_i:i + 1]
            k = int(np.argmax(seg))
            hi_p, hi_i = float(seg[k]), lo_i + k
    return Swings(np.array(kinds, dtype=np.int8), np.array(prices, dtype=float),
                  np.array(idxs, dtype=np.int64), np.array(avail, dtype=np.int64))


def trend_series(sw: Swings, n: int) -> np.ndarray:
    """Structure trend known at the close of each bar: UP (HH+HL), DOWN (LH+LL), RANGE otherwise."""
    out = np.zeros(n, dtype=np.int8)
    highs: list[float] = []
    lows: list[float] = []
    state = RANGE
    order = np.argsort(sw.available_idx, kind="stable")
    k = 0
    for i in range(n):
        while k < len(order) and sw.available_idx[order[k]] <= i:
            j = order[k]
            (highs if sw.kind[j] == 1 else lows).append(sw.price[j])
            if len(highs) >= 2 and len(lows) >= 2:
                if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                    state = UP
                elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                    state = DOWN
                else:
                    state = RANGE
            k += 1
        out[i] = state
    return out


def last_swing_levels(sw: Swings, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Price of the last confirmed swing high / low known at the close of each bar (NaN before any)."""
    last_hi = np.full(n, np.nan)
    last_lo = np.full(n, np.nan)
    for kind, target in ((1, last_hi), (-1, last_lo)):
        sel = np.flatnonzero(sw.kind == kind)
        if len(sel) == 0:
            continue
        av = sw.available_idx[sel]
        pr = sw.price[sel]
        pos = np.searchsorted(av, np.arange(n), side="right") - 1
        ok = pos >= 0
        target[ok] = pr[pos[ok]]
    return last_hi, last_lo


def bos_events(close: np.ndarray, sw: Swings, trend: np.ndarray):
    """Boolean arrays (bos_up, bos_down, choch_up, choch_down) per bar close.

    BOS_UP at bar i: close[i] > last confirmed swing high known at bar i-1 and close[i-1] <= that level.
    CHoCH when the structure trend before the bar was the opposite.
    """
    n = len(close)
    last_hi, last_lo = last_swing_levels(sw, n)
    prev_hi = np.r_[np.nan, last_hi[:-1]]
    prev_lo = np.r_[np.nan, last_lo[:-1]]
    prev_close = np.r_[np.nan, close[:-1]]
    with np.errstate(invalid="ignore"):
        bos_up = (close > prev_hi) & ~(prev_close > prev_hi)
        bos_dn = (close < prev_lo) & ~(prev_close < prev_lo)
    prev_trend = np.r_[RANGE, trend[:-1]]
    return bos_up, bos_dn, bos_up & (prev_trend == DOWN), bos_dn & (prev_trend == UP), prev_hi, prev_lo
