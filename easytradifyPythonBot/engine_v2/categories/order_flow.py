"""ORDER_FLOW: the auction around the prior day's value area (specs/categories/order_flow.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.categories._common import base_context, rollover, stop_buffer
from engine_v2.setup import Setup

CATEGORY = "ORDER_FLOW"
TF = "M15"
OF_BACK_INSIDE = 2
OF_ACCEPT = 3
ACCEPT_VALID_BARS = 8
TIME_STOP_BARS = 48
DAY_START_SECONDS = 3600


def _delta(b, i: int):
    u, dn = b.up_ticks[i], b.down_ticks[i]
    if not (np.isfinite(u) and np.isfinite(dn)):
        return None
    return int(np.sign(u - dn))


def propose(ctx) -> list[Setup]:
    b = ctx.bars(TF)
    atr = ctx.atr(TF)
    day = b.time // 86400
    prof_days = np.array(sorted(ctx.profiles), dtype=np.int64)
    out: list[Setup] = []
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    for s, e in zip(starts, np.r_[starts[1:], len(day)]):
        dnum = int(day[s])
        k = int(np.searchsorted(prof_days, dnum)) - 1
        if k < 0 or prof_days[k] < dnum - 4:
            continue
        P = ctx.profiles[int(prof_days[k])]
        vah, val, poc = P.vah, P.val, P.poc
        if not vah > val:
            continue
        s0 = s + int(np.searchsorted(b.time[s:e], dnum * 86400 + DAY_START_SECONDS))
        if s0 >= e:
            continue
        first_close = b.close[s0]
        open_loc = "inside" if val < first_close < vah else ("above" if first_close >= vah else "below")
        done = {("failed_auction", 1): False, ("failed_auction", -1): False,
                ("acceptance", 1): False, ("acceptance", -1): False}

        def emit(variant, d, m, order_type, entry, stop, t1, t2, thesis, valid_bars, extra):
            created = int(b.close_time[m])
            if rollover(created):
                return
            risk = (entry - stop) * d
            if risk <= 0:
                return
            a = float(atr[m])
            info = base_context(ctx, created)
            info.update({"va_width_atr": round((vah - val) / a, 2) if a > 0 else None, "open_location": open_loc,
                         "delta_sign": _delta(b, m), "risk_atr": round(risk / a, 3) if a > 0 else None, **extra})
            st = Setup(CATEGORY, variant, ctx.symbol, TF, "BUY" if d > 0 else "SELL", created,
                       created + valid_bars * 900, {"order_type": order_type, "price": float(entry)},
                       {"price": float(stop), "reason": "beyond excursion" if variant == "failed_auction" else "1 ATR inside value"},
                       [{"price": float(t1), "share": 0.5, "reason": "T1"}, {"price": float(t2), "share": 0.5, "reason": "T2"}],
                       management={"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_BARS},
                       thesis=thesis, context=info,
                       location={"type": "value_area", "vah": vah, "val": val, "poc": poc},
                       trigger={"type": variant, "bar_time": int(b.time[m])})
            try:
                out.append(st.validate())
            except ValueError:
                pass

        # ---------- failed auction ----------
        for d in (-1, 1):                        # SELL above VAH, BUY below VAL
            edge = vah if d < 0 else val
            outside = (b.high[s0:e] > vah) if d < 0 else (b.low[s0:e] < val)
            hits = np.flatnonzero(outside)
            if len(hits) == 0:
                continue
            x0 = s0 + int(hits[0])
            run = 0
            for m in range(x0, e):
                inside = val < b.close[m] < vah
                run = run + 1 if inside else 0
                if run >= OF_BACK_INSIDE:
                    ext = float(b.high[x0:m + 1].max()) if d < 0 else float(b.low[x0:m + 1].min())
                    a = float(atr[m])
                    if not a > 0:
                        break
                    entry = float(b.close[m])
                    stop = ext - d * stop_buffer(a, float(b.spread[m]))
                    risk = (entry - stop) * d
                    if risk <= 0:
                        break
                    t1 = poc if (poc - entry) * d >= risk else entry + d * risk
                    t2 = (val if d < 0 else vah) if ((val if d < 0 else vah) - entry) * d >= 1.5 * risk else entry + d * 1.5 * risk
                    if (t2 - t1) * d <= 0:
                        t2 = t1 + d * 0.5 * risk
                    emit("failed_auction", d, m, "MARKET", entry, stop, t1, t2,
                         [{"type": "close_beyond", "tf": TF, "level": edge, "beyond": "above" if d < 0 else "below",
                           "applies_to": "open"}], 1, {"excursion_atr": round(abs(ext - edge) / a, 2)})
                    break

        # ---------- acceptance ----------
        if open_loc != "inside":
            continue
        for d in (1, -1):                         # BUY above VAH, SELL below VAL
            edge = vah if d > 0 else val
            run = 0
            for m in range(s0, e):
                beyond = (b.close[m] > vah) if d > 0 else (b.close[m] < val)
                run = run + 1 if beyond else 0
                if run >= OF_ACCEPT:
                    a = float(atr[m])
                    if not a > 0:
                        break
                    entry = edge
                    stop = entry - d * max(1.0 * a, stop_buffer(a, float(b.spread[m])))
                    risk = (entry - stop) * d
                    prev_ext = P.high if d > 0 else P.low
                    t1 = entry + d * risk
                    t2 = prev_ext if (prev_ext - entry) * d >= 2 * risk else entry + d * 2 * risk
                    emit("acceptance", d, m, "LIMIT", entry, stop, t1, t2,
                         [{"type": "closes_inside", "tf": TF, "low": val, "high": vah, "count": 2, "applies_to": "open"}],
                         ACCEPT_VALID_BARS, {})
                    break
    return out
