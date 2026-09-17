import numpy as np

from engine_v2.data.bars import Bars


def m1_bars(mids, start=1_780_000_000 - 1_780_000_000 % 86400 + 3 * 3600, spread=0.0002, highs=None, lows=None,
            symbol="EURUSD", volume=None):
    """M1 bid/ask bars from a mid path. Optional explicit mid highs/lows per bar."""
    mids = np.asarray(mids, dtype=float)
    n = len(mids)
    t = start + 60 * np.arange(n, dtype=np.int64)
    o = np.r_[mids[0], mids[:-1]]
    c = mids
    h = np.maximum(o, c) if highs is None else np.asarray(highs, float)
    lo = np.minimum(o, c) if lows is None else np.asarray(lows, float)
    half = spread / 2
    vol = np.ones(n) if volume is None else np.asarray(volume, float)
    return Bars(symbol, "M1", t, o - half, h - half, lo - half, c - half, o + half, h + half, lo + half, c + half,
                vol, np.full(n, np.nan), np.full(n, np.nan))
