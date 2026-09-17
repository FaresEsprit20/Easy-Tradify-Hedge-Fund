"""TREND (D1 trend following): 55-day breakout, 2 x ATR(20) initial stop, trailing exit. Textbook specs, no tuning.

Variants
  donchian_55_20      exit when a D1 close breaks the prior 20-day opposite extreme
  donchian_55_chand   exit when a D1 close crosses the 22-day chandelier (3 x ATR(22))
No fixed target: the runner stays until the trailing exit, the initial stop or the time stop.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine_v2.data.clock import TF_SECONDS
from engine_v2.setup import Setup

CATEGORY = "TREND"
TF = "D1"
BREAKOUT_DAYS = 55
STOP_ATR = 2.0
ATR_DAYS = 20
FAR_TARGET_R = 100.0
TIME_STOP_D1 = 500
EXITS = {"donchian_55_20": ("donchian_low_20", "donchian_high_20"),
         "donchian_55_chand": ("chandelier_long_22_3", "chandelier_short_22_3")}


def propose(ctx, tfs: dict | None = None) -> list[Setup]:
    from engine_v2.market_model.indicators import atr as _atr
    b = ctx.bars(TF)
    n = len(b)
    a = _atr(b.high, b.low, b.close, ATR_DAYS)
    hi55 = pd.Series(b.high).rolling(BREAKOUT_DAYS, min_periods=BREAKOUT_DAYS).max().shift(1).to_numpy()
    lo55 = pd.Series(b.low).rolling(BREAKOUT_DAYS, min_periods=BREAKOUT_DAYS).min().shift(1).to_numpy()
    out: list[Setup] = []
    for i in range(BREAKOUT_DAYS + 1, n - 1):
        if not (a[i] > 0) or not np.isfinite(hi55[i]):
            continue
        c, pc = b.close[i], b.close[i - 1]
        if c > hi55[i] and not (pc > hi55[i - 1]):
            d = 1
        elif c < lo55[i] and not (pc < lo55[i - 1]):
            d = -1
        else:
            continue
        created = int(b.close_time[i])
        entry = float(c)
        stop = entry - d * STOP_ATR * float(a[i])
        for variant, (long_exit, short_exit) in EXITS.items():
            s = Setup(CATEGORY, variant, ctx.symbol, TF, "BUY" if d > 0 else "SELL", created, created + 3600,
                      {"order_type": "MARKET", "price": entry},
                      {"price": float(stop), "reason": f"{STOP_ATR} x ATR({ATR_DAYS})"},
                      [{"price": float(entry + d * FAR_TARGET_R * STOP_ATR * a[i]), "share": 1.0, "reason": "runner (no fixed target)"}],
                      management={"breakeven_after_target": None, "time_stop_bars": TIME_STOP_D1},
                      thesis=[{"type": "close_beyond_series", "tf": TF, "series": long_exit if d > 0 else short_exit,
                               "beyond": "below" if d > 0 else "above", "applies_to": "open"}],
                      context={"breakout_days": BREAKOUT_DAYS, "atr": float(a[i]), "session": "D1"},
                      location={"type": "55-day breakout", "level": float(hi55[i] if d > 0 else lo55[i])},
                      trigger={"type": "d1_close_breakout", "bar_time": int(b.time[i])})
            try:
                out.append(s.validate())
            except ValueError:
                pass
    return out
