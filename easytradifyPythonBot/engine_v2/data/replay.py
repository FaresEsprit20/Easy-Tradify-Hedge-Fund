"""Replay source: Dukascopy bid/ask M1 (UTC -> broker time) followed by MT5 tick-built bid/ask M1.

Both are true bid/ask data. Where they overlap, the MT5 tick bars win.
"""
from __future__ import annotations

import glob
import os
from functools import lru_cache

import numpy as np

from engine_v2.data.bars import Bars, concat
from engine_v2.data.clock import utc_to_broker

STUDY = os.environ.get("TRADIFY_STUDY_DIR", "C:/Users/msi/tradify_study")
TICKS_DIR = f"{STUDY}/ticks_m1"
TICKS_DIR_V4 = f"{STUDY}/ticks_m1_v4"   # indices and oil (strategic plan v4)
TICKS_DIR_V5 = f"{STUDY}/ticks_m1_v5"   # FX minors/exotics and minor spot indices (Gate 1i)
DUKA_DIR = f"{STUDY}/dukascopy"


def _ticks_bars(symbol: str) -> Bars | None:
    path = f"{TICKS_DIR}/{symbol}.npz"
    if not os.path.exists(path):
        path = f"{TICKS_DIR_V4}/{symbol}.npz"
    if not os.path.exists(path):
        path = f"{TICKS_DIR_V5}/{symbol}.npz"
    if not os.path.exists(path):
        return None
    z = np.load(path)
    return Bars(symbol, "M1", z["time"].astype(np.int64),
                z["bid_open"], z["bid_high"], z["bid_low"], z["bid_close"],
                z["ask_open"], z["ask_high"], z["ask_low"], z["ask_close"],
                z["ticks"].astype(np.float64),
                z["up_ticks"].astype(np.float64), z["down_ticks"].astype(np.float64))


def _duka_bars(symbol: str) -> Bars | None:
    files = sorted(glob.glob(f"{DUKA_DIR}/{symbol}_*.npz"))
    if not files:
        return None
    parts = []
    for f in files:
        try:
            z = np.load(f)
            n = len(z["time"])
        except Exception:        # a file still being written by the downloader
            continue
        nan = np.full(n, np.nan)
        parts.append(Bars(symbol, "M1", utc_to_broker(z["time"]),
                          z["bid_open"], z["bid_high"], z["bid_low"], z["bid_close"],
                          z["ask_open"], z["ask_high"], z["ask_low"], z["ask_close"],
                          z["volume"].astype(np.float64), nan, nan.copy()))
    bars = concat(parts)
    order = np.argsort(bars.time, kind="stable")
    return bars.slice(0, len(bars)) if np.all(order == np.arange(len(order))) else _take(bars, order)


def _take(bars: Bars, idx: np.ndarray) -> Bars:
    from engine_v2.data.bars import _ARRAYS
    return Bars(bars.symbol, bars.tf, *(getattr(bars, n)[idx] for n in _ARRAYS))


def _clean(bars: Bars) -> Bars:
    """Drop duplicate minutes and bars with non-positive or crossed prices."""
    keep = np.r_[True, bars.time[1:] != bars.time[:-1]]
    ok = (bars.bid_low > 0) & (bars.ask_low > 0) & (bars.ask_close >= bars.bid_close) & \
         (bars.bid_high >= bars.bid_low) & (bars.ask_high >= bars.ask_low)
    return _take(bars, np.flatnonzero(keep & ok))


@lru_cache(maxsize=32)
def load_m1(symbol: str) -> Bars:
    ticks = _ticks_bars(symbol)
    duka = _duka_bars(symbol)
    if ticks is None and duka is None:
        raise FileNotFoundError(f"no replay data for {symbol}")
    if duka is None:
        return _clean(ticks)
    if ticks is None:
        return _clean(duka)
    duka = duka.slice(0, int(np.searchsorted(duka.time, ticks.time[0])))
    return _clean(concat([duka, ticks]))


def available_symbols() -> list[str]:
    names = {os.path.basename(p)[:-4] for p in glob.glob(f"{TICKS_DIR}/*.npz")}
    names |= {os.path.basename(p)[:-4] for p in glob.glob(f"{TICKS_DIR_V4}/*.npz")}
    names |= {os.path.basename(p)[:-4] for p in glob.glob(f"{TICKS_DIR_V5}/*.npz")}
    names |= {os.path.basename(p).split("_")[0] for p in glob.glob(f"{DUKA_DIR}/*.npz")}
    return sorted(names)
