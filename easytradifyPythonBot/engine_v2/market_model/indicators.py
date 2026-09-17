"""Indicators on closed mid bars. Every value at index i is known at the close of bar i."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    prev = np.r_[close[0], close[:-1]]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    return _wilder(tr, n)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def rolling_std(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = _wilder(np.clip(d, 0, None), n)
    dn = _wilder(np.clip(-d, 0, None), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
        out = 100.0 - 100.0 / (1.0 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    return out


def macd_hist(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> np.ndarray:
    line = ema(close, fast) - ema(close, slow)
    return line - pd.Series(line).ewm(span=signal, adjust=False, min_periods=signal).mean().to_numpy()


def bollinger(close: np.ndarray, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = rolling_std(close, n)
    return mid - k * sd, mid, mid + k * sd


def keltner(high, low, close, n: int = 20, k: float = 1.5):
    mid = ema(close, n)
    a = atr(high, low, close, n)
    return mid - k * a, mid, mid + k * a


def efficiency_ratio(close: np.ndarray, n: int = 20) -> np.ndarray:
    change = np.abs(close - np.r_[np.full(n, np.nan), close[:-n]])
    vol = pd.Series(np.abs(np.diff(close, prepend=close[0]))).rolling(n, min_periods=n).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return change / vol


def rejection(open_, high, low, close, side: int) -> np.ndarray:
    """Bullish (side=+1): lower wick >= 50% of range, close in top third. Bearish mirrored."""
    rng = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        if side > 0:
            wick = np.minimum(open_, close) - low
            return (rng > 0) & (wick >= 0.5 * rng) & (close >= low + 2.0 / 3.0 * rng)
        wick = high - np.maximum(open_, close)
        return (rng > 0) & (wick >= 0.5 * rng) & (close <= high - 2.0 / 3.0 * rng)


def engulfing(open_, close, side: int) -> np.ndarray:
    po, pc = np.r_[np.nan, open_[:-1]], np.r_[np.nan, close[:-1]]
    if side > 0:
        return (close > open_) & (pc < po) & (close >= po) & (open_ <= pc)
    return (close < open_) & (pc > po) & (close <= po) & (open_ >= pc)
