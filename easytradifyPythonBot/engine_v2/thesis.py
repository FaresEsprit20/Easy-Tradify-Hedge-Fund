"""Thesis conditions, evaluated on closed bars of a timeframe. Shared by replay simulation and the live manager.

Each item is a dict:
  type          "close_beyond" | "closes_inside" | "close_beyond_series"
  tf            timeframe whose closes are checked
  applies_to    "pending" | "open" | "both"
  until_target  item active only while fewer than this many targets were hit (None = always)
  after_target  item active only once at least this many targets were hit (None = always)

  close_beyond:        level, beyond ("above" | "below")
  closes_inside:       low, high, count (consecutive closes strictly inside)
  close_beyond_series: series ("bb_mid"), beyond
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NEVER = np.iinfo(np.int64).max


def _series(ctx, name: str, tf: str) -> np.ndarray:
    """Named exit lines on closed bars of `tf`:
    bb_mid; donchian_low_N / donchian_high_N (extreme of the N bars BEFORE the current one);
    chandelier_long_N_K / chandelier_short_N_K (highest high of the last N bars - K x ATR(N), and mirror)."""
    if name == "bb_mid":
        return ctx.bollinger(tf)[1]
    key = ("series", tf, name)
    if key in ctx._cache:
        return ctx._cache[key]
    b = ctx.bars(tf)
    parts = name.split("_")
    if parts[0] == "donchian":
        n = int(parts[2])
        src = b.low if parts[1] == "low" else b.high
        roll = pd.Series(src).rolling(n, min_periods=n)
        out = (roll.min() if parts[1] == "low" else roll.max()).shift(1).to_numpy()
    elif parts[0] == "chandelier":
        n, k = int(parts[2]), float(parts[3])
        from engine_v2.market_model.indicators import atr as _atr
        a = _atr(b.high, b.low, b.close, n)
        if parts[1] == "long":
            out = pd.Series(b.high).rolling(n, min_periods=n).max().to_numpy() - k * a
        else:
            out = pd.Series(b.low).rolling(n, min_periods=n).min().to_numpy() + k * a
    else:
        raise KeyError(name)
    ctx._cache[key] = out
    return out


def active(item: dict, phase: str, targets_hit: int) -> bool:
    applies = item.get("applies_to", "open")
    if applies != "both" and applies != phase:
        return False
    ut, at = item.get("until_target"), item.get("after_target")
    if ut is not None and targets_hit >= ut:
        return False
    if at is not None and targets_hit < at:
        return False
    return True


def first_break_time(item: dict, ctx, start_time: int, until_time: int) -> int:
    """Close time of the first bar of item['tf'] closing in (start_time, until_time] that breaks the item."""
    b = ctx.bars(item["tf"])
    ct = b.close_time
    a = int(np.searchsorted(ct, start_time, side="right"))
    z = int(np.searchsorted(ct, until_time, side="right"))
    if a >= z:
        return NEVER
    close = b.close[a:z]
    kind = item["type"]
    if kind == "close_beyond":
        cond = close > item["level"] if item["beyond"] == "above" else close < item["level"]
        hit = np.flatnonzero(cond)
        return int(ct[a + hit[0]]) if len(hit) else NEVER
    if kind == "closes_inside":
        inside = (close > item["low"]) & (close < item["high"])
        run = 0
        for k, v in enumerate(inside):
            run = run + 1 if v else 0
            if run >= item["count"]:
                return int(ct[a + k])
        return NEVER
    if kind == "close_beyond_series":
        s = _series(ctx, item["series"], item["tf"])[a:z]
        with np.errstate(invalid="ignore"):
            cond = close < s if item["beyond"] == "below" else close > s
        hit = np.flatnonzero(cond)
        return int(ct[a + hit[0]]) if len(hit) else NEVER
    raise KeyError(kind)


def earliest_break(items: list[dict], ctx, phase: str, targets_hit: int, start_time: int, until_time: int) -> int:
    best = NEVER
    for it in items:
        if active(it, phase, targets_hit):
            best = min(best, first_break_time(it, ctx, start_time, until_time))
    return best
