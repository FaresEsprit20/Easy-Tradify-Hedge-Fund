"""Long history: MT5 H1 bid bars (2010 onward) with the ask side rebuilt from real spreads.

MT5 history bars are bid-only and their `spread` field is the bar's minimum (often 0). The ask side is
bid + the symbol's median true spread for that broker hour, measured on the MT5 tick bars (ticks_m1).
At H4/D1 setup scales the spread is a small fraction of the stop, so this fidelity is sufficient.
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

from engine_v2.data.bars import Bars
from engine_v2.data.replay import STUDY, TICKS_DIR

HISTORY_DIR = f"{STUDY}/mt5_bars"
HISTORY_DIR_V3 = f"{STUDY}/mt5_bars_v3"     # pairs fetched for the unseen-data test (spread profile stored inside)
UNSEEN_SYMBOLS = ["USDCAD", "AUDNZD", "AUDCAD", "AUDCHF", "AUDJPY", "CHFJPY", "EURAUD", "EURCHF", "EURNZD", "EURCAD",
                  "GBPCHF", "CADCHF", "CADJPY", "GBPAUD", "GBPCAD", "GBPNZD", "NZDCAD", "NZDCHF", "NZDJPY"]
LONG_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY",
                "XAUUSD", "XAGUSD"]
HISTORY_START = 1286409600  # 2010-10-07, first bar common to the long symbols


@lru_cache(maxsize=None)
def spread_by_hour(symbol: str) -> np.ndarray:
    v3 = f"{HISTORY_DIR_V3}/{symbol}.npz"
    if not os.path.exists(f"{TICKS_DIR}/{symbol}.npz") and os.path.exists(v3):
        return np.load(v3)["spread_by_hour"]
    z = np.load(f"{TICKS_DIR}/{symbol}.npz")
    spread = z["ask_close"] - z["bid_close"]
    hour = (z["time"] % 86400) // 3600
    out = np.array([np.median(spread[hour == h]) if (hour == h).any() else np.nan for h in range(24)])
    return np.where(np.isfinite(out), out, np.nanmedian(out))


@lru_cache(maxsize=16)
def load_h1(symbol: str) -> Bars:
    path = f"{HISTORY_DIR}/{symbol}.npz"
    z = np.load(path) if os.path.exists(path) else None
    if symbol in UNSEEN_SYMBOLS or z is None or "H1" not in z.files:
        path = f"{HISTORY_DIR_V3}/{symbol}.npz"
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        z = np.load(path)
    h = z["H1"]
    h = h[h["time"] >= HISTORY_START]
    t = h["time"].astype(np.int64)
    sp = spread_by_hour(symbol)[(t % 86400) // 3600]
    o, hi, lo, c = (h[k].astype(float) for k in ("open", "high", "low", "close"))
    nan = np.full(len(t), np.nan)
    keep = np.r_[True, t[1:] > t[:-1]] & (lo > 0)
    bars = Bars(symbol, "H1", t, o, hi, lo, c, o + sp, hi + sp, lo + sp, c + sp,
                h["tick_volume"].astype(float), nan, nan.copy())
    idx = np.flatnonzero(keep)
    from engine_v2.data.bars import _ARRAYS
    return Bars(symbol, "H1", *(getattr(bars, n)[idx] for n in _ARRAYS))
