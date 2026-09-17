"""Live source: replay history (bid/ask M1) extended with bid/ask M1 bars built from MT5 ticks.

MT5 tick times are broker-clock epochs; copy_ticks_range takes broker-clock datetimes passed as
naive UTC (same convention as tradify_study/tick_bars.py). Only CLOSED minutes are returned.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone

import numpy as np

from engine_v2.data.bars import Bars, concat
from engine_v2.data.replay import load_m1


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def bars_from_ticks(symbol: str, t: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> Bars | None:
    keep = (bid > 0) & (ask > 0)
    t, bid, ask = t[keep], bid[keep], ask[keep]
    if t.size == 0:
        return None
    minute = t - t % 60
    starts = np.flatnonzero(np.r_[True, minute[1:] != minute[:-1]])
    ends = np.r_[starts[1:], t.size]

    def ohlc(x):
        return x[starts], np.maximum.reduceat(x, starts), np.minimum.reduceat(x, starts), x[ends - 1]

    mid = (bid + ask) / 2
    d = np.r_[0.0, np.diff(mid)]
    up = np.add.reduceat((d > 0).astype(float), starts)
    dn = np.add.reduceat((d < 0).astype(float), starts)
    bo, bh, bl, bc = ohlc(bid)
    ao, ah, al, ac = ohlc(ask)
    return Bars(symbol, "M1", minute[starts].astype(np.int64), bo, bh, bl, bc, ao, ah, al, ac,
                (ends - starts).astype(float), up, dn)


def fetch_recent_m1(symbol: str, since_broker_epoch: int, now_broker_epoch: int | None = None) -> Bars | None:
    mt5 = _mt5()
    if now_broker_epoch is None:
        info = mt5.symbol_info_tick(symbol)
        now_broker_epoch = int(info.time) if info else int(_time.time()) + 3 * 3600
    start = datetime.fromtimestamp(since_broker_epoch, tz=timezone.utc)
    end = datetime.fromtimestamp(now_broker_epoch, tz=timezone.utc) + timedelta(seconds=1)
    a = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
    if a is None or len(a) == 0:
        return None
    t = (a["time_msc"] // 1000).astype(np.int64)
    bars = bars_from_ticks(symbol, t, a["bid"].astype(float), a["ask"].astype(float))
    if bars is None:
        return None
    closed = bars.time + 60 <= now_broker_epoch
    idx = np.flatnonzero(closed)
    return bars.slice(0, int(idx[-1]) + 1) if len(idx) else None


def load_live_m1(symbol: str, lookback_days: int = 120) -> Bars:
    """Replay history for the lookback window, then MT5 tick bars after the last stored minute."""
    hist = load_m1(symbol)
    recent = fetch_recent_m1(symbol, int(hist.time[-1]) + 60)
    bars = concat([hist, recent]) if recent is not None and len(recent) else hist
    cutoff = int(bars.time[-1]) - lookback_days * 86400
    return bars.slice(int(np.searchsorted(bars.time, cutoff)), len(bars))


def load_live_h1(symbol: str, bars: int = 6000) -> Bars:
    """Long live context for the H4/D1 categories: MT5 H1 bid bars (closed only) with the ask side rebuilt
    from the symbol's real spread by broker hour (same construction as engine_v2/data/history.py)."""
    from engine_v2.data.history import spread_by_hour
    mt5 = _mt5()
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no H1 rates for {symbol}: {mt5.last_error()}")
    tick = mt5.symbol_info_tick(symbol)
    now = int(tick.time) if tick else int(rates["time"][-1]) + 3600
    rates = rates[rates["time"] + 3600 <= now]
    t = rates["time"].astype(np.int64)
    sp = spread_by_hour(symbol)[(t % 86400) // 3600]
    o, hi, lo, c = (rates[k].astype(float) for k in ("open", "high", "low", "close"))
    nan = np.full(len(t), np.nan)
    return Bars(symbol, "H1", t, o, hi, lo, c, o + sp, hi + sp, lo + sp, c + sp,
                rates["tick_volume"].astype(float), nan, nan.copy())
