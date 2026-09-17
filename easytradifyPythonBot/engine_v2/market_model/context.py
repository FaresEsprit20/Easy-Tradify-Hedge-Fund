"""One market model per symbol: bars per timeframe and every shared service, computed once and cached."""
from __future__ import annotations

from functools import cached_property

import numpy as np

from engine_v2.data.bars import Bars
from engine_v2.market_model import indicators as ind
from engine_v2.market_model import structure as st
from engine_v2.market_model import volume as vol
from engine_v2.market_model.zones import supply_demand_zones


class Context:
    def __init__(self, symbol: str, m1: Bars):
        self.symbol = symbol
        self.m1 = m1
        self._bars: dict[str, Bars] = {"M1": m1}
        self._cache: dict = {}

    # ---------- bars ----------
    def bars(self, tf: str) -> Bars:
        if tf not in self._bars:
            self._bars[tf] = self.m1.resample(tf)
        return self._bars[tf]

    def _memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # ---------- indicators ----------
    def atr(self, tf: str) -> np.ndarray:
        b = self.bars(tf)
        return self._memo(("atr", tf), lambda: ind.atr(b.high, b.low, b.close, 14))

    def swings(self, tf: str) -> st.Swings:
        b = self.bars(tf)
        return self._memo(("swings", tf), lambda: st.zigzag(b.high, b.low, b.close, self.atr(tf)))

    def trend(self, tf: str) -> np.ndarray:
        return self._memo(("trend", tf), lambda: st.trend_series(self.swings(tf), len(self.bars(tf))))

    def bos(self, tf: str):
        b = self.bars(tf)
        return self._memo(("bos", tf), lambda: st.bos_events(b.close, self.swings(tf), self.trend(tf)))

    def ema(self, tf: str, n: int) -> np.ndarray:
        return self._memo(("ema", tf, n), lambda: ind.ema(self.bars(tf).close, n))

    def rsi(self, tf: str, n: int = 14) -> np.ndarray:
        return self._memo(("rsi", tf, n), lambda: ind.rsi(self.bars(tf).close, n))

    def macd_hist(self, tf: str) -> np.ndarray:
        return self._memo(("macd", tf), lambda: ind.macd_hist(self.bars(tf).close))

    def bollinger(self, tf: str):
        return self._memo(("bb", tf), lambda: ind.bollinger(self.bars(tf).close, 20, 2.0))

    def keltner(self, tf: str):
        b = self.bars(tf)
        return self._memo(("kc", tf), lambda: ind.keltner(b.high, b.low, b.close, 20, 1.5))

    def efficiency_ratio(self, tf: str, n: int = 20) -> np.ndarray:
        return self._memo(("er", tf, n), lambda: ind.efficiency_ratio(self.bars(tf).close, n))

    # ---------- cross-timeframe lookup ----------
    def last_closed_index(self, tf: str, t: int) -> int:
        """Index of the last bar of `tf` closed at time t, or -1."""
        return self.bars(tf).closed_upto(t) - 1

    def value_at(self, tf: str, series: np.ndarray, t: int, default=np.nan):
        i = self.last_closed_index(tf, t)
        return series[i] if i >= 0 else default

    # ---------- volume ----------
    @cached_property
    def vwap_m1(self) -> np.ndarray:
        return vol.developing_vwap(self.m1.time, self.m1.close, self.m1.volume)

    def vwap_at_close(self, tf: str) -> np.ndarray:
        """Developing VWAP at the close of each `tf` bar (last M1 bar inside it)."""
        def build():
            b = self.bars(tf)
            last_m1 = np.searchsorted(self.m1.time, b.close_time, side="left") - 1
            return self.vwap_m1[np.clip(last_m1, 0, len(self.m1) - 1)]
        return self._memo(("vwap_close", tf), build)

    @cached_property
    def d1_atr_by_day(self) -> dict[int, float]:
        d1 = self.bars("D1")
        a = self.atr("D1")
        return {int(t // 86400): float(v) for t, v in zip(d1.time, a) if np.isfinite(v)}

    @cached_property
    def profiles(self) -> dict[int, vol.DayProfile]:
        return vol.day_profiles(self.m1.time, self.m1.close, self.m1.high, self.m1.low, self.m1.volume,
                                self.d1_atr_by_day)

    # ---------- zones ----------
    def sd_zones(self, tf: str):
        b = self.bars(tf)
        return self._memo(("sdz", tf), lambda: supply_demand_zones(b.open, b.high, b.low, b.close, self.atr(tf)))

    # ---------- day / week levels ----------
    @cached_property
    def day_levels(self):
        """dict day -> (high, low) of that complete broker day (mid)."""
        d1 = self.bars("D1")
        return {int(t // 86400): (float(h), float(l)) for t, h, l in zip(d1.time, d1.high, d1.low)}

    @cached_property
    def week_levels(self):
        """dict week key -> (high, low); week key = (day + 3) // 7 (weeks start Monday)."""
        d1 = self.bars("D1")
        wk = (d1.time // 86400 + 3) // 7
        out = {}
        for k in np.unique(wk):
            sel = wk == k
            out[int(k)] = (float(d1.high[sel].max()), float(d1.low[sel].min()))
        return out

    @cached_property
    def asia_levels(self):
        """dict day -> (high, low) of broker 01:00-09:00, available from 09:00 of that day."""
        m = self.m1
        day = m.time // 86400
        hour = (m.time % 86400) // 3600
        sel = (hour >= 1) & (hour < 9)
        out = {}
        if not sel.any():
            return out
        d = day[sel]
        hi, lo = m.high[sel], m.low[sel]
        starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
        for s, e in zip(starts, np.r_[starts[1:], len(d)]):
            if e - s >= 240:
                out[int(d[s])] = (float(hi[s:e].max()), float(lo[s:e].min()))
        return out
