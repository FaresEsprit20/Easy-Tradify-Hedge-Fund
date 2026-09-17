"""SMC: liquidity sequence (specs/categories/smc.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import base_context, rollover, secure_half, stop_buffer, two_targets
from engine_v2.market_model.liquidity import pool_sweeps
from engine_v2.market_model.location import room_to_opposing_level_r
from engine_v2.market_model.structure import last_swing_levels
from engine_v2.market_model.zones import displacement, fvg
from engine_v2.setup import Setup

CATEGORY = "SMC"
TF = "M15"
TFS = {"setup": "H4", "context": "D1"}          # v2.1: the scale the rules were measured at
ROOM_MIN_R = 0.5                                # v2.1: next opposing D1 level at least 0.5R beyond entry
SMC_POOLS = ("prior_day", "asia", "equal")      # v2.1: prior-week sweeps removed
PARTIAL_AT_R = 0.5                              # v3: half off at +0.5R, breakeven, runner to the pool
SMC_BOS_WINDOW = 8
SMC_ENTRY_BARS = 12
TIME_STOP_BARS = 96
T2_MAX_R = 6.0
T2_FALLBACK_R = 3.0


def _opposing_pool(ctx, b, d: int, m: int, t1: float, entry: float, risk: float) -> float | None:
    """Nearest untaken pool beyond T1 in the trade direction, within T2_MAX_R."""
    t = int(b.close_time[m])
    day = t // 86400
    cands = []
    day_keys = sorted(k for k in ctx.day_levels if k < day)
    day_start = int(np.searchsorted(b.time, day * 86400))
    if day_keys:
        ph, pl = ctx.day_levels[day_keys[-1]]
        cands.append(pl if d < 0 else ph)
    wk = (day + 3) // 7
    wkeys = sorted(k for k in ctx.week_levels if k < wk)
    if wkeys:
        wh, wl = ctx.week_levels[wkeys[-1]]
        cands.append(wl if d < 0 else wh)
    if day in ctx.asia_levels and t >= day * 86400 + 9 * 3600:
        ah, al = ctx.asia_levels[day]
        cands.append(al if d < 0 else ah)
    lo_so_far = b.low[day_start:m + 1].min() if m >= day_start else np.inf
    hi_so_far = b.high[day_start:m + 1].max() if m >= day_start else -np.inf
    best = None
    for c in cands:
        if d < 0:
            if c < t1 and c < lo_so_far and entry - c <= T2_MAX_R * risk and (best is None or c > best):
                best = c
        else:
            if c > t1 and c > hi_so_far and c - entry <= T2_MAX_R * risk and (best is None or c < best):
                best = c
    return best


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    tf = T["setup"]
    b = ctx.bars(tf)
    n = len(b)
    atr = ctx.atr(tf)
    sw = ctx.swings(tf)
    last_hi, last_lo = last_swing_levels(sw, n)
    disp = displacement(b.open, b.high, b.low, b.close, atr)
    fvgs = {1: fvg(b.high, b.low, atr, 1), -1: fvg(b.high, b.low, atr, -1)}
    spread = b.spread
    out: list[Setup] = []
    for sweep in pool_sweeps(ctx, tf):
        i = sweep.idx
        if sweep.pool not in SMC_POOLS:
            continue
        if i + 1 >= n or rollover(int(b.time[i]), tf) or not (atr[i] > 0):
            continue
        d = -sweep.pool_side          # swept a high -> SELL
        x = sweep.extreme
        level = last_lo[i] if d < 0 else last_hi[i]
        if not np.isfinite(level):
            continue
        bos = None
        for m in range(i, min(i + SMC_BOS_WINDOW, n)):
            if m > i and ((b.high[m] > x) if d < 0 else (b.low[m] < x)):
                break                   # extreme exceeded before the break: no sequence
            if (b.close[m] < level) if d < 0 else (b.close[m] > level):
                bos = m
                break
        if bos is None:
            continue
        leg = slice(i, bos + 1)
        if not (disp[leg] == d).any():
            continue
        flags, tops, bots = fvgs[d]
        f_idx = np.flatnonzero(flags[leg])
        if len(f_idx) == 0:
            continue
        f = i + int(f_idx[-1])
        top, bot = float(tops[f]), float(bots[f])   # for bearish FVG: top > bottom as well
        hi_, lo_ = max(top, bot), min(top, bot)
        entry = (hi_ + lo_) / 2.0
        a = float(atr[bos])
        stop = x - d * stop_buffer(a, float(spread[bos]))
        risk = (entry - stop) * d
        if risk <= 0:
            continue
        created = int(b.close_time[bos])
        room = room_to_opposing_level_r(ctx, created, entry, risk, d)
        if room < ROOM_MIN_R:
            continue
        leg_ext = float(b.low[leg].min()) if d < 0 else float(b.high[leg].max())
        t1 = leg_ext
        pool = _opposing_pool(ctx, b, d, bos, t1 if (t1 - entry) * d >= risk else entry + d * risk, entry, risk)
        t2 = pool if pool is not None else entry + d * T2_FALLBACK_R * risk
        targets = two_targets(entry, t1, t2, risk, d, reason1="leg extreme",
                              reason2="opposing pool" if pool is not None else f"{T2_FALLBACK_R}R")
        if PARTIAL_AT_R:
            targets = secure_half(entry, risk, d, targets[-1], PARTIAL_AT_R)
        ctx_info = base_context(ctx, created, T["context"])
        rng = abs(x - leg_ext)
        ctx_info.update({
            "pool": sweep.pool,
            "premium_side": bool(((entry - leg_ext) * -d) >= 0.5 * rng) if rng > 0 else False,
            "fvg_atr": round((hi_ - lo_) / a, 3),
            "displacement_atr": round(float(((b.high[leg] - b.low[leg]) / a).max()), 3),
            "risk_atr": round(risk / a, 3),
            "room_r": round(room, 3),
        })
        s = Setup(
            category=CATEGORY, variant="fvg_mid", symbol=ctx.symbol, timeframe=tf,
            side="BUY" if d > 0 else "SELL", created_at=created, valid_until=created + SMC_ENTRY_BARS * TF_SECONDS[tf],
            entry={"order_type": "LIMIT", "price": float(entry)},
            stop={"price": float(stop), "reason": "beyond sweep extreme"},
            targets=targets,
            management={"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_BARS},
            thesis=[],                  # v2.1: invalidation is the sweep extreme (the stop), not an FVG close
            context=ctx_info,
            location={"type": "FVG", "proximal": lo_ if d < 0 else hi_, "distal": hi_ if d < 0 else lo_,
                      "sources": [sweep.pool]},
            trigger={"type": "sweep_then_bos", "sweep_time": int(b.time[i]), "bar_time": int(b.time[bos]),
                     "pool_level": sweep.level, "sweep_extreme": x},
        )
        try:
            out.append(s.validate())
        except ValueError:
            continue
    return out
