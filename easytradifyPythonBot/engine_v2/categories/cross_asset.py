"""CROSS_ASSET: cross rate vs the rate its legs imply (specs/categories/cross_asset.md).

Needs three symbols at once, so it exposes propose_multi(contexts) instead of propose(ctx).
"""
from __future__ import annotations

import numpy as np

from engine_v2.categories._common import base_context, rollover
from engine_v2.market_model.indicators import rolling_std
from engine_v2.setup import Setup

CATEGORY = "CROSS_ASSET"
TF = "M15"
CA_SIGMA = 2.5
CA_PERSIST = 3
SIGMA_BARS = 96
STOP_BUFFER_ATR = 0.20
TIME_STOP_BARS = 16
PAIRS = {"EURGBP": ("EURUSD", "GBPUSD", "div"), "EURJPY": ("EURUSD", "USDJPY", "mul"),
         "GBPJPY": ("GBPUSD", "USDJPY", "mul")}


def propose(ctx) -> list[Setup]:
    return []   # single-symbol entry point unused: see propose_multi


def propose_multi(ctxs: dict) -> list[Setup]:
    out: list[Setup] = []
    for cross, (leg_a, leg_b, op) in PAIRS.items():
        if not all(s in ctxs for s in (cross, leg_a, leg_b)):
            continue
        cx = ctxs[cross]
        c, A, B = cx.bars(TF), ctxs[leg_a].bars(TF), ctxs[leg_b].bars(TF)
        common = np.intersect1d(np.intersect1d(c.time, A.time), B.time)
        if len(common) < SIGMA_BARS + 10:
            continue
        ic = np.searchsorted(c.time, common)
        ia = np.searchsorted(A.time, common)
        ib = np.searchsorted(B.time, common)
        implied = A.close[ia] / B.close[ib] if op == "div" else A.close[ia] * B.close[ib]
        atr = cx.atr(TF)[ic]
        with np.errstate(invalid="ignore", divide="ignore"):
            dev = (c.close[ic] - implied) / atr
        sigma = rolling_std(dev, SIGMA_BARS)
        with np.errstate(invalid="ignore"):
            rich = dev >= CA_SIGMA * sigma
            cheap = dev <= -CA_SIGMA * sigma
        run_r = run_c = 0
        armed = True
        for k in range(len(common)):
            run_r = run_r + 1 if rich[k] else 0
            run_c = run_c + 1 if cheap[k] else 0
            if not armed:
                if np.isfinite(dev[k]) and np.isfinite(sigma[k]) and abs(dev[k]) < sigma[k]:
                    armed = True
                continue
            if run_r != CA_PERSIST and run_c != CA_PERSIST:
                continue
            d = -1 if run_r == CA_PERSIST else 1
            i = int(ic[k])
            created = int(c.close_time[i])
            a = float(atr[k])
            if rollover(created) or not a > 0:
                continue
            entry = float(c.close[i])
            w = slice(i - 2, i + 1)
            stop = (float(c.high[w].max()) + STOP_BUFFER_ATR * a) if d < 0 else (float(c.low[w].min()) - STOP_BUFFER_ATR * a)
            risk = (entry - stop) * d
            fair = float(implied[k])
            if risk <= 0 or (fair - entry) * d <= 0:
                continue
            if (fair - entry) * d < risk:
                t1, t2 = entry + d * 0.5 * risk, entry + d * risk
            else:
                t1, t2 = entry + (fair - entry) / 2.0, fair
            info = base_context(cx, created)
            info.update({"deviation_sigma": round(float(dev[k] / sigma[k]), 2), "legs": [leg_a, leg_b],
                         "risk_atr": round(risk / a, 3)})
            s = Setup(CATEGORY, "triangle_lag", cross, TF, "BUY" if d > 0 else "SELL", created, created + 900,
                      {"order_type": "MARKET", "price": entry}, {"price": float(stop), "reason": "beyond 3-bar extreme"},
                      [{"price": float(t1), "share": 0.5, "reason": "halfway to implied"},
                       {"price": float(t2), "share": 0.5, "reason": "implied rate"}],
                      management={"breakeven_after_target": 1, "time_stop_bars": TIME_STOP_BARS},
                      context=info, location={"type": "implied_rate", "implied": fair},
                      trigger={"type": "persistent_divergence", "bar_time": int(c.time[i])})
            try:
                out.append(s.validate())
                armed = False
            except ValueError:
                pass
    return out
