"""WAVE: completed price structures (specs/categories/wave.md)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import at_least_r, base_context, rollover
from engine_v2.market_model.location import weekday
from engine_v2.setup import Setup

CATEGORY = "WAVE"
WY_RANGE_BARS = 30
WY_MAX_HEIGHT_ATR = 4.0
WY_TOUCH_ATR = 0.25
WY_SPRING_ATR = 0.10
WY_TEST_BARS = 10
WY_TEST_BAND_ATR = 0.5
DB_EQUAL_ATR = 0.30
DB_MIN_BARS, DB_MAX_BARS = 5, 60
DB_NECK_ATR = 1.5
DB_MAX_STOP_ATR = 4.0
EW_W1_ATR = 3.0
EW_RETRACE = (0.50, 0.786)
H1_ENTRY_VALID = 3
TIME_STOP_H1 = 72
TFS = {"pattern": "H4", "trigger": "H1", "context": "D1"}   # v2.1: the scale the rules were measured at
WY_ENABLED = False       # v2.1: the Wyckoff definition lost in both periods; off until rebuilt
NO_FRIDAY = True         # v2.1: Friday pattern entries lose in both periods (weekend)


def _setup(ctx, variant, tf, d, created, valid_bars, tf_sec, entry, stop, targets, thesis, info, location, trigger,
           time_stop_bars):
    s = Setup(CATEGORY, variant, ctx.symbol, tf, "BUY" if d > 0 else "SELL", created, created + valid_bars * tf_sec,
              {"order_type": "STOP", "price": float(entry)}, {"price": float(stop), "reason": "structure invalidation"},
              targets, management={"breakeven_after_target": 1, "time_stop_bars": time_stop_bars},
              thesis=thesis, context=info, location=location, trigger=trigger)
    try:
        return s.validate()
    except ValueError:
        return None


def _wyckoff(ctx, out, T):
    b = ctx.bars(T["pattern"])
    n = len(b)
    atr = ctx.atr(T["pattern"])
    hi_roll = pd.Series(b.high).rolling(WY_RANGE_BARS).max().shift(1).to_numpy()
    lo_roll = pd.Series(b.low).rolling(WY_RANGE_BARS).min().shift(1).to_numpy()
    for s in range(WY_RANGE_BARS + 1, n - 1):
        a = atr[s - 1]
        rh, rl = hi_roll[s], lo_roll[s]
        if not (a > 0) or not np.isfinite(rh) or rh - rl > WY_MAX_HEIGHT_ATR * a:
            continue
        w = slice(s - WY_RANGE_BARS, s)
        for d in (1, -1):
            if d > 0:
                if not (b.low[s] < rl - WY_SPRING_ATR * a and b.close[s] > rl):
                    continue
                if (np.abs(b.low[w] - rl) <= WY_TOUCH_ATR * a).sum() < 2 or (np.abs(b.high[w] - rh) <= WY_TOUCH_ATR * a).sum() < 2:
                    continue
            else:
                if not (b.high[s] > rh + WY_SPRING_ATR * a and b.close[s] < rh):
                    continue
                if (np.abs(b.low[w] - rl) <= WY_TOUCH_ATR * a).sum() < 2 or (np.abs(b.high[w] - rh) <= WY_TOUCH_ATR * a).sum() < 2:
                    continue
            spring_ext = b.low[s] if d > 0 else b.high[s]
            edge = rl if d > 0 else rh
            for t in range(s + 1, min(s + 1 + WY_TEST_BARS, n)):
                if (b.close[t] < spring_ext) if d > 0 else (b.close[t] > spring_ext):
                    break
                near = abs((b.low[t] if d > 0 else b.high[t]) - edge) <= WY_TEST_BAND_ATR * a
                if near and b.volume[t] < b.volume[s] and ((b.close[t] > b.open[t]) if d > 0 else (b.close[t] < b.open[t])):
                    created = int(b.close_time[t])
                    if rollover(created, T["pattern"]):
                        break
                    spread = float(b.spread[t])
                    entry = (b.high[t] + spread) if d > 0 else (b.low[t] - spread)
                    stop = spring_ext - d * WY_SPRING_ATR * a
                    risk = (entry - stop) * d
                    if risk <= 0:
                        break
                    mid = (rh + rl) / 2.0
                    t1 = at_least_r(entry, mid, risk, d, 1.0)
                    t2 = at_least_r(entry, rh if d > 0 else rl, risk, d, 2.0)
                    if (t2 - t1) * d < 0.5 * risk:
                        t2 = t1 + d * 0.5 * risk
                    info = base_context(ctx, created, T["context"])
                    info.update({"range_atr": round((rh - rl) / a, 2), "risk_atr": round(risk / a, 3)})
                    st = _setup(ctx, "wyckoff_spring" if d > 0 else "wyckoff_upthrust", T["pattern"], d, created, H1_ENTRY_VALID, TF_SECONDS[T["pattern"]],
                                entry, stop,
                                [{"price": float(t1), "share": 0.5, "reason": "range mid"},
                                 {"price": float(t2), "share": 0.5, "reason": "opposite range edge"}],
                                [{"type": "close_beyond", "tf": T["pattern"], "level": float(spring_ext),
                                  "beyond": "below" if d > 0 else "above", "applies_to": "both"}],
                                info, {"type": "trading_range", "high": float(rh), "low": float(rl)},
                                {"type": "spring_test", "spring_time": int(b.time[s]), "bar_time": int(b.time[t])},
                                TIME_STOP_H1)
                    if st:
                        out.append(st)
                    break


def _ordered_swings(ctx, tf):
    sw = ctx.swings(tf)
    o = np.argsort(sw.available_idx, kind="stable")
    return sw.kind[o], sw.price[o], sw.idx[o], sw.available_idx[o]


def _double(ctx, out, T):
    b = ctx.bars(T["pattern"])
    n = len(b)
    atr = ctx.atr(T["pattern"])
    kind, price, idx, avail = _ordered_swings(ctx, T["pattern"])
    for p in range(2, len(kind)):
        k1, k2, k3 = kind[p - 2], kind[p - 1], kind[p]
        if not (k1 == k3 and k2 == -k1):
            continue
        d = 1 if k1 == -1 else -1                  # two lows -> double bottom -> BUY
        b1, neck, b2 = price[p - 2], price[p - 1], price[p]
        a = float(atr[avail[p]])
        gap = idx[p] - idx[p - 2]
        if not (a > 0) or abs(b1 - b2) > DB_EQUAL_ATR * a or not (DB_MIN_BARS <= gap <= DB_MAX_BARS):
            continue
        worst = min(b1, b2) if d > 0 else max(b1, b2)
        best = max(b1, b2) if d > 0 else min(b1, b2)
        if (neck - best) * d < DB_NECK_ATR * a:
            continue
        for t in range(int(avail[p]) + 1, min(int(avail[p]) + 1 + DB_MAX_BARS, n)):
            if (b.close[t] < worst) if d > 0 else (b.close[t] > worst):
                break
            if (b.close[t] > neck) if d > 0 else (b.close[t] < neck):
                created = int(b.close_time[t])
                if rollover(created, T["pattern"]) or (NO_FRIDAY and weekday(created) == 4):
                    break
                spread = float(b.spread[t])
                entry = (b.high[t] + spread) if d > 0 else (b.low[t] - spread)
                stop = worst - d * 0.10 * a
                if (entry - stop) * d > DB_MAX_STOP_ATR * a:
                    stop = (neck + worst) / 2.0
                risk = (entry - stop) * d
                if risk <= 0:
                    break
                t1 = entry + d * risk
                t2 = at_least_r(entry, neck + (neck - worst), risk, d, 2.0)
                info = base_context(ctx, created, T["context"])
                info.update({"height_atr": round(abs(neck - worst) / a, 2), "risk_atr": round(risk / a, 3)})
                st = _setup(ctx, "double_bottom" if d > 0 else "double_top", T["pattern"], d, created, H1_ENTRY_VALID, TF_SECONDS[T["pattern"]],
                            entry, stop,
                            [{"price": float(t1), "share": 0.5, "reason": "1R"},
                             {"price": float(t2), "share": 0.5, "reason": "measured move"}],
                            [],          # v2.1 standard exits: the stop is the invalidation
                            info, {"type": "double", "neckline": float(neck), "bottoms": [float(b1), float(b2)]},
                            {"type": "neckline_break", "bar_time": int(b.time[t])}, TIME_STOP_H1)
                if st:
                    out.append(st)
                break


def _elliott(ctx, out, T):
    h1, m15 = ctx.bars(T["pattern"]), ctx.bars(T["trigger"])
    atr = ctx.atr(T["pattern"])
    bos_up, bos_dn, *_ = ctx.bos(T["trigger"])
    kind, price, idx, avail = _ordered_swings(ctx, T["pattern"])
    for p in range(2, len(kind)):
        k0, k1, k2 = kind[p - 2], kind[p - 1], kind[p]
        if not (k0 == k2 and k1 == -k0):
            continue
        d = 1 if k0 == -1 else -1                  # low, high, low -> up impulse wave 2
        L0, P1, L2 = price[p - 2], price[p - 1], price[p]
        a = float(atr[avail[p]])
        w1 = (P1 - L0) * d
        if not (a > 0) or w1 < EW_W1_ATR * a or (L2 - L0) * d <= 0:
            continue
        retr = (P1 - L2) * d / w1
        if not (EW_RETRACE[0] <= retr <= EW_RETRACE[1]):
            continue
        t_conf = int(h1.close_time[avail[p]])
        j0 = int(np.searchsorted(m15.time, t_conf, side="left"))
        end = int(np.searchsorted(m15.time, t_conf + 120 * TF_SECONDS[T["pattern"]], side="left"))
        for j in range(j0, min(end, len(m15))):
            c = m15.close[j]
            if ((c < L2) or (c > P1)) if d > 0 else ((c > L2) or (c < P1)):
                break
            if bos_up[j] if d > 0 else bos_dn[j]:
                created = int(m15.close_time[j])
                if rollover(created, T["pattern"]) or (NO_FRIDAY and weekday(created) == 4):
                    break
                spread = float(m15.spread[j])
                entry = (m15.high[j] + spread) if d > 0 else (m15.low[j] - spread)
                stop = L2 - d * 0.20 * a
                risk = (entry - stop) * d
                if risk <= 0:
                    break
                t1 = at_least_r(entry, P1, risk, d, 1.0)
                t2 = at_least_r(entry, L2 + d * 1.618 * w1, risk, d, 2.0)
                if (t2 - t1) * d < 0.5 * risk:
                    t2 = t1 + d * 0.5 * risk
                info = base_context(ctx, created, T["context"])
                info.update({"wave1_atr": round(w1 / a, 2), "retrace": round(float(retr), 3), "risk_atr": round(risk / a, 3)})
                st = _setup(ctx, "elliott_w2", T["trigger"], d, created, 4, TF_SECONDS[T["trigger"]], entry, stop,
                            [{"price": float(t1), "share": 0.5, "reason": "wave 1 extreme"},
                             {"price": float(t2), "share": 0.5, "reason": "wave 3 = 1.618 x wave 1"}],
                            [],          # v2.1 standard exits: the stop is the invalidation
                            info, {"type": "wave2", "L0": float(L0), "P1": float(P1), "L2": float(L2)},
                            {"type": "m15_bos", "bar_time": int(m15.time[j])}, 120 * TF_SECONDS[T["pattern"]] // TF_SECONDS[T["trigger"]])
                if st:
                    out.append(st)
                break


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    out: list[Setup] = []
    if WY_ENABLED:
        _wyckoff(ctx, out, T)
    _double(ctx, out, T)
    _elliott(ctx, out, T)
    return out
