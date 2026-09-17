"""STRUCTURE: fresh supply/demand zones (specs/categories/structure.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import at_least_r, base_context, rollover, secure_half, stop_buffer
from engine_v2.market_model.indicators import engulfing, rejection
from engine_v2.market_model.location import range_position, trend_age, volatility_percentile
from engine_v2.setup import Setup

CATEGORY = "STRUCTURE"
ZONE_TF = "H1"
TRIGGER_TF = "M15"
TFS = {"zone": "D1", "trigger": "H4", "context": "D1"}   # v2.1: the scale the rules were measured at
# v3.0 (cross-pair validated 2026-09-17, engine_v2/run/crosspair.py): medium volatility regime + secure-half exits.
# The v2.1 location / trend-age filters were dropped: they did not survive leave-pairs-out validation.
VOL_PCT_LOW = 0.25       # ATR percentile (250 bars of the setup timeframe) must be above this ...
VOL_PCT_HIGH = 0.68      # ... and at most this
PARTIAL_AT_R = 0.5       # half off at +0.5R, breakeven, runner to the departure leg extreme
STRUCT_VALID_H1 = 120
TIME_STOP_H1 = 72
CONFIRM_VALID_M15 = 4
SR_TOL_ATR = 0.25


def _confluence(ctx, z, a: float, zt: str = ZONE_TF) -> dict:
    sw = ctx.swings(zt)
    lo, hi = min(z.proximal, z.distal), max(z.proximal, z.distal)
    known = sw.available_idx <= z.departure_idx
    near = known & (sw.price >= lo - SR_TOL_ATR * a) & (sw.price <= hi + SR_TOL_ATR * a)
    sr = int(near.sum()) >= 2
    fib = False
    prev = np.flatnonzero(known & (sw.idx < z.base_start))
    if len(prev) >= 2:
        p1, p2 = sw.price[prev[-2]], sw.price[prev[-1]]
        f50, f618 = p2 + 0.5 * (p1 - p2), p2 + 0.618 * (p1 - p2)
        flo, fhi = min(f50, f618), max(f50, f618)
        fib = not (fhi < lo or flo > hi)
    return {"sr_confluence": sr, "fib_confluence": fib}


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    zt, tt = T["zone"], T["trigger"]
    h1 = ctx.bars(zt)
    m15 = ctx.bars(tt)
    a_h1 = ctx.atr(zt)
    rej = {1: rejection(m15.open, m15.high, m15.low, m15.close, 1),
           -1: rejection(m15.open, m15.high, m15.low, m15.close, -1)}
    eng = {1: engulfing(m15.open, m15.close, 1), -1: engulfing(m15.open, m15.close, -1)}
    out: list[Setup] = []
    for z in ctx.sd_zones(zt):
        d = z.side
        dep = z.departure_idx
        if dep + 1 >= len(h1):
            continue
        a = float(a_h1[dep])
        avail_t = int(h1.close_time[dep])
        lo, hi = min(z.proximal, z.distal), max(z.proximal, z.distal)
        # lifecycle on M15 after availability: first touch and invalidation
        j0 = int(np.searchsorted(m15.time, avail_t, side="left"))
        horizon_t = avail_t + STRUCT_VALID_H1 * TF_SECONDS[zt]
        j1 = int(np.searchsorted(m15.time, horizon_t, side="left"))
        if j0 >= j1:
            continue
        touch = (m15.low[j0:j1] <= z.proximal) if d > 0 else (m15.high[j0:j1] >= z.proximal)
        t_idx = np.flatnonzero(touch)
        closes_beyond = (m15.close[j0:j1] < z.distal) if d > 0 else (m15.close[j0:j1] > z.distal)
        inv_idx = np.flatnonzero(closes_beyond)
        first_touch = j0 + int(t_idx[0]) if len(t_idx) else None
        invalid = j0 + int(inv_idx[0]) if len(inv_idx) else None
        conf = _confluence(ctx, z, a, zt)
        spread = float(np.median(h1.spread[max(0, dep - 5):dep + 1]))
        stop = z.distal - d * stop_buffer(a, spread)
        common_ctx = base_context(ctx, avail_t, T["context"])
        common_ctx.update(conf)
        common_ctx.update({"departure_atr": round(z.departure_atr, 3), "base_bars": z.base_end - z.base_start + 1})
        thesis = [{"type": "close_beyond", "tf": zt, "level": z.distal,
                   "beyond": "below" if d > 0 else "above", "applies_to": "both"}]
        mg = {"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_H1}

        def make(variant, created, valid_until, order_type, entry, extra_ctx, trigger):
            risk = (entry - stop) * d
            if risk <= 0:
                return None
            setup_tf = zt if variant == "first_touch" else tt
            vp = volatility_percentile(ctx, setup_tf, created)
            if vp is None or not (VOL_PCT_LOW < vp <= VOL_PCT_HIGH):
                return None
            rp = range_position(ctx, created, entry, d)
            age = trend_age(ctx, created, "D1")
            # v2.1 standard exits: T1 at the nearest opposing swing of the zone timeframe, T2 at the leg extreme
            sw = ctx.swings(zt)
            known = sw.available_idx <= ctx.last_closed_index(zt, created)
            lv = sw.price[known & (sw.kind == (1 if d > 0 else -1))]
            beyond = lv[(lv - entry) * d >= risk]
            t1 = float(beyond.min() if d > 0 else beyond.max()) if len(beyond) else entry + d * risk
            t2 = at_least_r(entry, z.leg_extreme, risk, d, 1.0)
            if (t2 - t1) * d < 0.5 * risk:
                t2 = t1 + d * 0.5 * risk
            extra_ctx = dict(extra_ctx, vol_pct=round(vp, 3), range_pos=round(rp, 3) if rp is not None else None,
                             d1_trend_age=age)
            targets = [{"price": float(t1), "share": 0.5, "reason": "nearest opposing swing"},
                       {"price": float(t2), "share": 0.5, "reason": "departure leg extreme"}]
            if PARTIAL_AT_R:
                targets = secure_half(entry, risk, d, targets[-1], PARTIAL_AT_R)
            c = dict(common_ctx, **extra_ctx, risk_atr=round(risk / a, 3))
            s = Setup(CATEGORY, variant, ctx.symbol, zt if variant == "first_touch" else tt,
                      "BUY" if d > 0 else "SELL", created, valid_until,
                      {"order_type": order_type, "price": float(entry)},
                      {"price": float(stop), "reason": "beyond zone distal edge"},
                      targets,
                      management=dict(mg, time_stop_bars=TIME_STOP_H1 if variant == "first_touch" else TIME_STOP_H1 * TF_SECONDS[zt] // TF_SECONDS[tt]),
                      thesis=thesis, context=c,
                      location={"type": "demand" if d > 0 else "supply", "proximal": z.proximal, "distal": z.distal,
                                "sources": ["sd_base"] + [k for k, v in conf.items() if v]},
                      trigger=trigger)
            try:
                return s.validate()
            except ValueError:
                return None

        # variant first_touch: limit resting at proximal from availability
        if not rollover(avail_t, zt):
            s = make("first_touch", avail_t, horizon_t, "LIMIT", z.proximal, {"zone_age_h": None},
                     {"type": "zone_available", "bar_time": int(h1.time[dep])})
            if s:
                out.append(s)
        # variant confirmation: first touch bar must be a rejection/engulfing close inside the zone
        if first_touch is not None and (invalid is None or invalid > first_touch):
            k = first_touch
            inside = (m15.low[k] <= z.proximal and m15.low[k] >= z.distal) if d > 0 else \
                     (m15.high[k] >= z.proximal and m15.high[k] <= z.distal)
            if inside and (rej[d][k] or eng[d][k]):
                created = int(m15.close_time[k])
                if not rollover(created, tt):
                    entry = (m15.high[k] + float(m15.spread[k])) if d > 0 else (m15.low[k] - float(m15.spread[k]))
                    s = make("confirmation", created, created + CONFIRM_VALID_M15 * TF_SECONDS[tt], "STOP", float(entry),
                             {"zone_age_h": round((created - avail_t) / 3600, 1)},
                             {"type": "rejection" if rej[d][k] else "engulfing", "bar_time": int(m15.time[k])})
                    if s:
                        out.append(s)
    return out
