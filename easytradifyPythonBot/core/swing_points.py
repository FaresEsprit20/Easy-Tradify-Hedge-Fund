# ============================================================
# SWING POINT DETECTION - SINGLE SOURCE OF TRUTH
# ============================================================
# FILE: core/swing_points.py
#
# Previously duplicated in two places with two different (and both
# buggy) behaviors:
#
#   - patterns.py PatternRecognizer._find_swing_points(): filtered
#     candidate swings by comparing against the immediately PREVIOUS
#     BAR only (`abs(prices[i] - prices[i-1])`). That is not a swing
#     amplitude — it's a single-bar noise check — so a slow multi-bar
#     drift never accumulated into a "real" swing, and unrelated
#     single-bar jumps could pass the filter on their own.
#
#   - indicators.py _find_swing_points(): had NO amplitude filter at
#     all. Every local 5-bar pivot in the high/low series counted as
#     a swing regardless of size, so on M1 (where ATR can be a
#     fraction of a pip) sub-pip noise was accepted as legitimate
#     supply/demand zone candidates.
#
# Both now delegate to find_swing_points() / find_swing_points_ohlc()
# below, which measures amplitude against the last ACCEPTED swing
# (standard zigzag semantics), not the previous bar.
# ============================================================

from typing import Dict, List, Tuple, Optional
import numpy as np

# ✅ FIXED (units): this table is named ..._PIPS but held raw PRICE
# UNITS, calibrated for 5-decimal FX. Because it is an absolute price
# constant, the same entry means a completely different swing size on
# every instrument class:
#
#     M1 threshold 0.00005 price units
#       EURUSD (pip 0.0001) -> 0.500 pips   <- the intended calibration
#       XAGUSD (pip 0.001)  -> 0.050 pips   <- 10x too permissive
#       XAUUSD (pip 0.01)   -> 0.005 pips   <- 100x too permissive
#       USDJPY (pip 0.01)   -> 0.005 pips   <- 100x too permissive
#
# On XAGUSD live (ATR 49.2 pips) a "swing" needed to be 0.05 pips --
# roughly 0.1% of the bar's own average range -- so essentially every
# 5-bar pivot passed and the amplitude filter did nothing at all. That
# is the actual mechanism behind "Elliott waves / patterns are detecting
# noise on M1": not that M1 is unusable, but that the one filter meant
# to reject sub-noise swings was silently disabled on every non-FX-major
# symbol.
#
# The table now holds what its name says -- PIPS -- and is converted to
# price units against the instrument's own pip_size.
MIN_SWING_SIZE_PIPS = {
    "M1": 0.5,
    "M5": 1.5,
    "M15": 2.0,
    "M30": 3.0,
    "H1": 4.0,
}
DEFAULT_MIN_SWING_SIZE_PIPS = 0.5

# Used only when a caller does not supply pip_size. This is the pip size
# the old price-unit constants were implicitly calibrated against, so
# callers that have not been updated get byte-identical behaviour to
# before rather than a silent change.
_LEGACY_ASSUMED_PIP_SIZE = 0.0001


# Minimum swing as a share of the timeframe's bar ATR, used whenever ATR is
# known. The pip table is 0.5 pips on M1: about 0.5 ATR on EURUSD but 0.01 ATR
# on XAGUSD, where every wiggle became a "swing" (and so a zone, a sweep level,
# a fib leg). One ATR fraction means the same structure on every instrument.
MIN_SWING_SIZE_ATR_FRACTION = 0.5


def get_min_swing_size(timeframe: str, pip_size: float = None, atr_pips: float = None) -> float:
    """
    Timeframe-appropriate minimum swing amplitude, in PRICE UNITS.

    pip_size: the instrument's pip size. Pass it. Omitting it falls back
    to the 5-decimal-FX assumption the old absolute constants encoded,
    which is correct for EURUSD-like symbols and far too permissive for
    metals, JPY pairs and equities -- see the table comment above.
    """
    pips = MIN_SWING_SIZE_PIPS.get((timeframe or "M1").upper(), DEFAULT_MIN_SWING_SIZE_PIPS)
    if pip_size is None or pip_size <= 0:
        pip_size = _LEGACY_ASSUMED_PIP_SIZE
    if atr_pips and atr_pips > 0:
        return float(atr_pips) * MIN_SWING_SIZE_ATR_FRACTION * pip_size
    return pips * pip_size


def find_swing_points(prices: List[float], lookback: int = 2, min_amplitude: float = 0.0) -> List[Dict]:
    """
    Canonical swing high/low detector over a flat price series.

    A bar is a swing high/low if it is the local extreme over `lookback`
    bars on both sides AND its distance from the last ACCEPTED swing
    point (of either type) is at least `min_amplitude`. Measuring against
    the last accepted swing (rather than the previous single bar) is what
    makes this a real swing-size filter instead of a single-bar noise
    check — a slow drift across several small bars now correctly
    accumulates toward the threshold.

    Returns a list of {'type': 'high'|'low', 'price': float, 'index': int},
    ordered by index (ascending, i.e. oldest to newest).
    """
    if not prices or len(prices) < (2 * lookback + 1):
        return []

    swing_points: List[Dict] = []
    last_accepted_price: Optional[float] = None

    for i in range(lookback, len(prices) - lookback):
        # ✅ FIXED: a plateau (two or more bars tied at the exact same
        # price) used to make the WHOLE peak or trough invisible -- every
        # bar in the tie failed the strict '>'/'<' check against its
        # equal neighbor, so neither bar could claim to be the local
        # extreme, and the swing was silently dropped entirely. Real
        # OHLC data ties bars routinely (thin liquidity, discrete tick
        # sizes, or just a quiet minute) -- verified directly: a clean
        # peak with a 2-bar plateau at the top produced zero detected
        # swing points, while the identical shape with a single sharp bar
        # at the top was detected correctly. This matters most in exactly
        # the low-volatility, ranging conditions this system's wave and
        # pattern detectors get relied on most, since that's when ties
        # are most common.
        #
        # Switching the comparison to >=/<= lets a tied plateau still
        # qualify as the extreme it structurally is. The guard below
        # (skip if this bar's price repeats the previous bar's) then
        # ensures a multi-bar plateau still produces exactly ONE swing
        # point (registered at the first bar of the tie), not one
        # duplicate entry per tied bar -- so this only removes the
        # blind spot, it doesn't turn every flat stretch into a flood of
        # near-identical points.
        if i > 0 and prices[i] == prices[i - 1]:
            continue

        is_high = all(prices[i] >= prices[i - j] and prices[i] >= prices[i + j] for j in range(1, lookback + 1))
        is_low = all(prices[i] <= prices[i - j] and prices[i] <= prices[i + j] for j in range(1, lookback + 1))

        if not is_high and not is_low:
            continue

        if last_accepted_price is None or min_amplitude <= 0:
            amplitude_ok = True
        else:
            amplitude_ok = abs(prices[i] - last_accepted_price) >= min_amplitude

        if amplitude_ok:
            point_type = 'high' if is_high else 'low'
            swing_points.append({'type': point_type, 'price': prices[i], 'index': i})
            last_accepted_price = prices[i]

    return swing_points


def find_swing_points_ohlc(
    rates: np.ndarray,
    use_high: bool = True,
    lookback: int = 5,
    min_amplitude: float = 0.0
) -> Tuple[List[float], List[int]]:
    """
    OHLC adapter over find_swing_points() — single source of truth for
    supply/demand zone candidate levels. Adds the amplitude filter that
    indicators.py's old standalone version was missing entirely.

    use_high=True scans the bar HIGH column for local maxima (supply
    candidates); use_high=False scans the bar LOW column for local
    minima (demand candidates) — matching the original call convention.

    Returns (price_values, bar_open_times) for accepted points only.
    """
    if rates is None or len(rates) < (2 * lookback + 1):
        return [], []

    series = [float(r[2]) for r in rates] if use_high else [float(r[3]) for r in rates]
    raw = find_swing_points(series, lookback=lookback, min_amplitude=min_amplitude)

    wanted_type = 'high' if use_high else 'low'
    points = [p['price'] for p in raw if p['type'] == wanted_type]
    times = [int(rates[p['index']][0]) for p in raw if p['type'] == wanted_type]
    return points, times