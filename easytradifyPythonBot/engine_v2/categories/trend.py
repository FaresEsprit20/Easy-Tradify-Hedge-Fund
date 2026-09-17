"""TREND: pullback continuation (specs/categories/trend.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import at_least_r, base_context, rollover, secure_half
from engine_v2.market_model.location import volatility_percentile
from engine_v2.market_model.structure import DOWN, UP
from engine_v2.setup import Setup

CATEGORY = "TREND"
IMPULSE_MIN_ATR = 2.0
ENTRY_VALID_M15 = 4
TIME_STOP_M15 = 96
STOP_BUFFER_H1_ATR = 0.10
TFS = {"impulse": "H4", "context": "D1", "trigger": "H1"}   # v2.1: the scale the rules were measured at
VOL_PCT_MAX = 0.33       # v2.1: pullbacks only in a calm market (ATR in its lowest third of 250 bars)
PARTIAL_AT_R = 0.5       # v3: half off at +0.5R, breakeven, runner to 2.5R


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    it_, ct, tt = T["impulse"], T["context"], T["trigger"]
    h1, m15 = ctx.bars(it_), ctx.bars(tt)
    a_h1 = ctx.atr(it_)
    sw = ctx.swings(it_)
    tr_h1, tr_h4 = ctx.trend(it_), ctx.trend(ct)
    bos_up, bos_dn, *_ = ctx.bos(tt)
    er = ctx.efficiency_ratio(it_)
    out: list[Setup] = []
    order = np.argsort(sw.available_idx, kind="stable")
    kinds, prices, idxs, avails = sw.kind[order], sw.price[order], sw.idx[order], sw.available_idx[order]
    for p in range(1, len(order)):
        # impulse = swing (kind a) followed by confirmed opposite swing (kind b)
        k_prev, k_cur = kinds[p - 1], kinds[p]
        if k_prev == k_cur:
            continue
        d = 1 if k_cur == 1 else -1          # swing high confirmed after swing low = up impulse
        L, H = prices[p - 1], prices[p]
        av = int(avails[p])
        a = float(a_h1[av])
        if not (a > 0) or (H - L) * d < IMPULSE_MIN_ATR * a:
            continue
        # context at impulse confirmation
        t_conf = int(h1.close_time[av])
        i4 = ctx.last_closed_index(ct, t_conf)
        want = UP if d > 0 else DOWN
        if tr_h1[av] != want or i4 < 0 or tr_h4[i4] != want:
            continue
        f38 = H - d * 0.382 * abs(H - L)
        f62 = H - d * 0.618 * abs(H - L)
        z_lo, z_hi = min(f38, f62), max(f38, f62)
        # pullback extreme so far: from the impulse extreme bar to the confirmation bar
        seg = slice(int(idxs[p]), av + 1)
        extreme = float(h1.low[seg].min()) if d > 0 else float(h1.high[seg].max())
        touched = (extreme <= z_hi) if d > 0 else (extreme >= z_lo)
        # scan M15 from confirmation until the next H1 swing of the same kind is confirmed (new impulse)
        j0 = int(np.searchsorted(m15.time, t_conf, side="left"))
        nxt = p + 2 if p + 2 < len(order) else None
        end_t = int(h1.close_time[avails[nxt]]) if nxt is not None else int(m15.close_time[-1])
        j1 = int(np.searchsorted(m15.time, end_t, side="left"))
        for j in range(j0, min(j1, len(m15))):
            c = m15.close[j]
            if (c < L) if d > 0 else (c > L):
                break
            if d > 0:
                extreme = min(extreme, float(m15.low[j]))
                touched = touched or m15.low[j] <= z_hi
            else:
                extreme = max(extreme, float(m15.high[j]))
                touched = touched or m15.high[j] >= z_lo
            if touched and ((bos_up[j]) if d > 0 else (bos_dn[j])):
                created = int(m15.close_time[j])
                if rollover(created, tt):
                    break
                vp = volatility_percentile(ctx, tt, created)
                if vp is None or vp > VOL_PCT_MAX:
                    break
                i1 = ctx.last_closed_index(it_, created)
                i4b = ctx.last_closed_index(ct, created)
                if tr_h1[i1] != want or tr_h4[i4b] != want:
                    break
                spread = float(m15.spread[j])
                entry = (m15.high[j] + spread) if d > 0 else (m15.low[j] - spread)
                a_now = float(a_h1[i1])
                stop = extreme - d * STOP_BUFFER_H1_ATR * a_now
                risk = (entry - stop) * d
                if risk <= 0:
                    break
                t1 = at_least_r(entry, H, risk, d, 1.0)
                t2 = entry + d * 2.5 * risk
                if (t2 - t1) * d < 0.5 * risk:
                    t2 = t1 + d * 0.5 * risk
                depth = abs(H - extreme) / abs(H - L)
                c_info = base_context(ctx, created, ct)
                c_info.update({"retrace_band": "38-50" if depth < 0.5 else "50-62+", "impulse_atr": round(abs(H - L) / a, 2),
                               "er_h1": round(float(er[i1]), 3) if np.isfinite(er[i1]) else None,
                               "risk_atr": round(risk / a_now, 3), "vol_pct": round(vp, 3)})
                s = Setup(CATEGORY, "pullback", ctx.symbol, tt, "BUY" if d > 0 else "SELL", created,
                          created + ENTRY_VALID_M15 * TF_SECONDS[tt], {"order_type": "STOP", "price": float(entry)},
                          {"price": float(stop), "reason": "beyond pullback extreme"},
                          secure_half(entry, risk, d, {"price": float(t2), "reason": "2.5R"}, PARTIAL_AT_R) if PARTIAL_AT_R else
                          [{"price": float(t1), "share": 0.5, "reason": "impulse extreme"},
                           {"price": float(t2), "share": 0.5, "reason": "2.5R"}],
                          management={"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_M15},
                          thesis=[{"type": "close_beyond", "tf": it_, "level": float(L),
                                   "beyond": "below" if d > 0 else "above", "applies_to": "both"}],
                          context=c_info,
                          location={"type": "fib_38_62", "proximal": z_hi if d > 0 else z_lo,
                                    "distal": z_lo if d > 0 else z_hi, "sources": ["h1_impulse"]},
                          trigger={"type": "m15_bos", "bar_time": int(m15.time[j])})
                try:
                    out.append(s.validate())
                except ValueError:
                    pass
                break
    return out
