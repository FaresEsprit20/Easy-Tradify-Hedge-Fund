"""Bid/ask/mid bars. M1 is the base; higher timeframes are resampled on broker time.

A bar's `time` is its OPEN time (broker epoch). It is CLOSED at `time + tf_seconds`; decisions only
ever see closed bars (`closed_upto`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine_v2.data.clock import TF_SECONDS


@dataclass
class Bars:
    symbol: str
    tf: str
    time: np.ndarray
    bid_open: np.ndarray
    bid_high: np.ndarray
    bid_low: np.ndarray
    bid_close: np.ndarray
    ask_open: np.ndarray
    ask_high: np.ndarray
    ask_low: np.ndarray
    ask_close: np.ndarray
    volume: np.ndarray
    up_ticks: np.ndarray
    down_ticks: np.ndarray
    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def tf_seconds(self) -> int:
        return TF_SECONDS[self.tf]

    def __len__(self) -> int:
        return len(self.time)

    def _mid(self, a: str, b: str) -> np.ndarray:
        key = f"mid_{a}"
        if key not in self._cache:
            self._cache[key] = (getattr(self, f"bid_{a}") + getattr(self, f"ask_{a}")) / 2.0
        return self._cache[key]

    @property
    def open(self):
        return self._mid("open", "open")

    @property
    def high(self):
        return self._mid("high", "high")

    @property
    def low(self):
        return self._mid("low", "low")

    @property
    def close(self):
        return self._mid("close", "close")

    @property
    def spread(self) -> np.ndarray:
        return self.ask_close - self.bid_close

    @property
    def close_time(self) -> np.ndarray:
        return self.time + self.tf_seconds

    def closed_upto(self, t: int) -> int:
        """Number of bars whose close time is <= t (so bars [0, n) are closed at time t)."""
        return int(np.searchsorted(self.close_time, t, side="right"))

    def index_at_or_after(self, t: int) -> int:
        """First bar whose OPEN time is >= t."""
        return int(np.searchsorted(self.time, t, side="left"))

    def slice(self, a: int, b: int) -> "Bars":
        return Bars(self.symbol, self.tf, *(getattr(self, n)[a:b] for n in _ARRAYS))

    def resample(self, tf: str) -> "Bars":
        if tf == self.tf:
            return self
        sec = TF_SECONDS[tf]
        if sec <= self.tf_seconds:
            raise ValueError(f"cannot resample {self.tf} to {tf}")
        key = self.time // sec * sec
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        ends = np.r_[starts[1:], len(key)] - 1
        out = Bars(
            self.symbol, tf, key[starts],
            self.bid_open[starts], np.maximum.reduceat(self.bid_high, starts),
            np.minimum.reduceat(self.bid_low, starts), self.bid_close[ends],
            self.ask_open[starts], np.maximum.reduceat(self.ask_high, starts),
            np.minimum.reduceat(self.ask_low, starts), self.ask_close[ends],
            np.add.reduceat(self.volume, starts),
            np.add.reduceat(np.nan_to_num(self.up_ticks, nan=0.0), starts),
            np.add.reduceat(np.nan_to_num(self.down_ticks, nan=0.0), starts),
        )
        has_flow = np.add.reduceat(np.isfinite(self.up_ticks).astype(np.int64), starts) > 0
        out.up_ticks = np.where(has_flow, out.up_ticks, np.nan)
        out.down_ticks = np.where(has_flow, out.down_ticks, np.nan)
        return out


_ARRAYS = ("time", "bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low",
           "ask_close", "volume", "up_ticks", "down_ticks")


def concat(parts: list[Bars]) -> Bars:
    parts = [p for p in parts if len(p)]
    if not parts:
        raise ValueError("no bars")
    return Bars(parts[0].symbol, parts[0].tf, *(np.concatenate([getattr(p, n) for p in parts]) for n in _ARRAYS))
