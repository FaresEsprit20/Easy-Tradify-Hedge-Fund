"""MEAN_REVERSION: stretch back to fair value (specs/categories/mean_reversion.md)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.categories._common import base_context, rollover
from engine_v2.market_model.indicators import rolling_std
from engine_v2.setup import Setup

CATEGORY = "MEAN_REVERSION"
TF = "M15"
TFS = {"setup": "H4", "er": "D1", "context": "D1"}   # v2.1: H4 measured 60%/65% won vs M15 53%/43%
MR_ER_MAX = 0.30
MR_SIGMA = 2.0
SIGMA_BARS = 96
RSI_EXTREME = 25.0
RSI_BACK = 30.0
LOOKBACK = 4
STOP_BARS = 8
STOP_BUFFER_ATR = 0.20
MR_TIME_BARS = 16


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    T = {**TFS, **(tfs or {})}
    tf = T["setup"]
    b = ctx.bars(tf)
    n = len(b)
    atr = ctx.atr(tf)
    rsi = ctx.rsi(tf)
    vwap = ctx.vwap_at_close(tf)
    dev = b.close - vwap
    sigma = rolling_std(dev, SIGMA_BARS)
    er = ctx.efficiency_ratio(T["er"])
    with np.errstate(invalid="ignore", divide="ignore"):
        z = dev / sigma
    out: list[Setup] = []
    armed = {1: True, -1: True}
    for i in range(max(SIGMA_BARS, STOP_BARS) + 1, n):
        # re-arm a side once price crosses back to VWAP
        if not armed[1] and b.close[i] >= vwap[i]:
            armed[1] = True
        if not armed[-1] and b.close[i] <= vwap[i]:
            armed[-1] = True
        for d in (1, -1):
            if not armed[d]:
                continue
            w = slice(i - LOOKBACK + 1, i + 1)
            if d > 0:
                cross = rsi[i - 1] <= RSI_BACK < rsi[i] and b.close[i] > b.open[i]
                extreme = np.nanmin(rsi[w]) < RSI_EXTREME
                stretched = np.nanmin(z[w]) <= -MR_SIGMA
            else:
                cross = rsi[i - 1] >= 100 - RSI_BACK > rsi[i] and b.close[i] < b.open[i]
                extreme = np.nanmax(rsi[w]) > 100 - RSI_EXTREME
                stretched = np.nanmax(z[w]) >= MR_SIGMA
            if not (cross and extreme and stretched):
                continue
            created = int(b.close_time[i])
            i1 = ctx.last_closed_index(T["er"], created)
            if i1 < 0 or not (er[i1] < MR_ER_MAX) or rollover(created, tf):
                continue
            a = float(atr[i])
            if not a > 0:
                continue
            entry = float(b.close[i])
            stop = (float(b.low[i - STOP_BARS + 1:i + 1].min()) - STOP_BUFFER_ATR * a) if d > 0 else \
                   (float(b.high[i - STOP_BARS + 1:i + 1].max()) + STOP_BUFFER_ATR * a)
            risk = (entry - stop) * d
            fair = float(vwap[i])
            if risk <= 0 or (fair - entry) * d <= 0:
                continue
            if (fair - entry) * d < risk:
                t1, t2 = entry + d * 0.5 * risk, entry + d * 1.0 * risk
            else:
                t1, t2 = entry + (fair - entry) / 2.0, fair
            info = base_context(ctx, created, T["context"])
            info.update({"stretch_sigma": round(float(np.nanmin(z[w]) if d > 0 else np.nanmax(z[w])), 2),
                         "vwap_distance_r": round((fair - entry) * d / risk, 2), "er_h1": round(float(er[i1]), 3),
                         "risk_atr": round(risk / a, 3)})
            s = Setup(CATEGORY, "vwap_stretch", ctx.symbol, tf, "BUY" if d > 0 else "SELL", created, created + TF_SECONDS[tf],
                      {"order_type": "MARKET", "price": entry}, {"price": float(stop), "reason": "beyond stretch extreme"},
                      [{"price": float(t1), "share": 0.5, "reason": "halfway to VWAP"},
                       {"price": float(t2), "share": 0.5, "reason": "VWAP"}],
                      management={"breakeven_after_target": 1, "time_stop_bars": MR_TIME_BARS},
                      thesis=[], context=info, location={"type": "vwap_stretch", "vwap": fair},
                      trigger={"type": "rsi_back_inside", "bar_time": int(b.time[i])})
            try:
                out.append(s.validate())
                armed[d] = False
            except ValueError:
                pass
    return out
