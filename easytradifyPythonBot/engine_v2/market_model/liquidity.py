"""Liquidity pools and their first sweep (a bar that trades beyond the pool and closes back)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EQUAL_ATR = 0.10
EQUAL_SEARCH_BARS = 480  # M15 bars (5 days) an equal-high/low pool stays live
POOL_PRIORITY = {"prior_week": 0, "prior_day": 1, "asia": 2, "equal": 3}


@dataclass
class Sweep:
    idx: int          # bar index of the sweep bar (on the pool timeframe)
    pool_side: int    # +1 a HIGH pool was swept (bearish setup), -1 a LOW pool (bullish setup)
    level: float
    extreme: float    # sweep bar high (high pool) / low (low pool)
    pool: str


def _first_take(high, low, close, a: int, b: int, level: float, pool_side: int):
    """First bar in [a, b) that trades beyond `level`; returns (idx, is_sweep) or None."""
    if a >= b:
        return None
    seg = high[a:b] > level if pool_side > 0 else low[a:b] < level
    hit = np.flatnonzero(seg)
    if len(hit) == 0:
        return None
    j = a + int(hit[0])
    swept = close[j] < level if pool_side > 0 else close[j] > level
    return j, bool(swept)


def pool_sweeps(ctx, tf: str = "M15") -> list[Sweep]:
    b = ctx.bars(tf)
    high, low, close, time = b.high, b.low, b.close, b.time
    atr = ctx.atr(tf)
    day = time // 86400
    out: dict[tuple[int, int], Sweep] = {}

    def add(res, pool_side, level, pool):
        if res is None or not res[1]:
            return
        j = res[0]
        s = Sweep(j, pool_side, float(level), float(high[j] if pool_side > 0 else low[j]), pool)
        key = (j, pool_side)
        if key not in out or POOL_PRIORITY[pool] < POOL_PRIORITY[out[key].pool]:
            out[key] = s

    day_keys = sorted(ctx.day_levels)
    day_starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    day_ends = np.r_[day_starts[1:], len(day)]
    for s, e in zip(day_starts, day_ends):
        d = int(day[s])
        k = np.searchsorted(day_keys, d) - 1
        if k >= 0:
            ph, pl = ctx.day_levels[day_keys[k]]
            add(_first_take(high, low, close, s, e, ph, 1), 1, ph, "prior_day")
            add(_first_take(high, low, close, s, e, pl, -1), -1, pl, "prior_day")
        if d in ctx.asia_levels:
            ah, al = ctx.asia_levels[d]
            a0 = s + int(np.searchsorted(time[s:e], d * 86400 + 9 * 3600))
            add(_first_take(high, low, close, a0, e, ah, 1), 1, ah, "asia")
            add(_first_take(high, low, close, a0, e, al, -1), -1, al, "asia")

    week = (day + 3) // 7
    week_keys = sorted(ctx.week_levels)
    w_starts = np.flatnonzero(np.r_[True, week[1:] != week[:-1]])
    for s, e in zip(w_starts, np.r_[w_starts[1:], len(week)]):
        k = np.searchsorted(week_keys, int(week[s])) - 1
        if k >= 0:
            wh, wl = ctx.week_levels[week_keys[k]]
            add(_first_take(high, low, close, s, e, wh, 1), 1, wh, "prior_week")
            add(_first_take(high, low, close, s, e, wl, -1), -1, wl, "prior_week")

    sw = ctx.swings(tf)
    for kind in (1, -1):
        sel = np.flatnonzero(sw.kind == kind)
        for p, q in zip(sel[:-1], sel[1:]):
            a = atr[sw.available_idx[q]]
            if not (a > 0) or abs(sw.price[p] - sw.price[q]) > EQUAL_ATR * a:
                continue
            level = max(sw.price[p], sw.price[q]) if kind == 1 else min(sw.price[p], sw.price[q])
            start = int(sw.available_idx[q]) + 1
            add(_first_take(high, low, close, start, min(start + EQUAL_SEARCH_BARS, len(high)), level, kind),
                kind, level, "equal")

    return sorted(out.values(), key=lambda s: (s.idx, s.pool_side))
