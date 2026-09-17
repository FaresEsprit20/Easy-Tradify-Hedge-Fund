"""Location service: where a trade sits in the higher-timeframe picture, known at its creation time.

Shared by the categories (v2.1 rules) and by the forensics tool, so a rule and its evidence use one definition.
"""
from __future__ import annotations

import numpy as np

ROOM_CAP_R = 10.0
RANGE_DAYS = 20
VOL_LOOKBACK = 250


def room_to_opposing_level_r(ctx, t: int, entry: float, risk: float, d: int, tf: str = "D1") -> float:
    """Distance from entry to the nearest confirmed opposing swing beyond it (resistance for a BUY), in R."""
    j = ctx.last_closed_index(tf, t)
    if j < 0 or risk <= 0:
        return ROOM_CAP_R
    sw = ctx.swings(tf)
    known = sw.available_idx <= j
    lv = sw.price[known & (sw.kind == (1 if d > 0 else -1))]
    beyond = lv[(lv - entry) * d > 0]
    if len(beyond) == 0:
        return ROOM_CAP_R
    room = beyond.min() - entry if d > 0 else entry - beyond.max()
    return float(min(room / risk, ROOM_CAP_R))


def range_position(ctx, t: int, entry: float, d: int, days: int = RANGE_DAYS) -> float | None:
    """Entry's place in the last `days` D1 bars' range, side-adjusted: 0 = best price for the side (discount
    for a BUY, premium for a SELL), 1 = worst."""
    j = ctx.last_closed_index("D1", t)
    if j < days - 1:
        return None
    d1 = ctx.bars("D1")
    hi, lo = float(d1.high[j - days + 1:j + 1].max()), float(d1.low[j - days + 1:j + 1].min())
    pos = (entry - lo) / (hi - lo) if hi > lo else 0.5
    return pos if d > 0 else 1.0 - pos


def trend_age(ctx, t: int, tf: str = "D1") -> int | None:
    """Closed bars the current structure trend state of `tf` has lasted."""
    j = ctx.last_closed_index(tf, t)
    if j < 0:
        return None
    tr = ctx.trend(tf)
    k = j
    while k > 0 and tr[k - 1] == tr[j]:
        k -= 1
    return int(j - k)


def trend_alignment(ctx, t: int, d: int, tf: str = "D1") -> str | None:
    j = ctx.last_closed_index(tf, t)
    if j < 0:
        return None
    v = ctx.trend(tf)[j]
    return "aligned" if v == d else ("against" if v == -d else "neutral")


def volatility_percentile(ctx, tf: str, t: int, lookback: int = VOL_LOOKBACK) -> float | None:
    """Share of the last `lookback` bars whose ATR was below the current ATR (0 = calmest)."""
    i = ctx.last_closed_index(tf, t)
    atr = ctx.atr(tf)
    if i < lookback or not (atr[i] > 0):
        return None
    return float((atr[i - lookback:i + 1] < atr[i]).mean())


def weekday(t: int) -> int:
    """0 = Monday ... 4 = Friday (broker time)."""
    return int((t // 86400 + 3) % 7)
