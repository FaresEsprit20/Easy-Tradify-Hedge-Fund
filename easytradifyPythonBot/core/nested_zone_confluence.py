# ============================================================
# NESTED ZONE REQUIREMENT (HIGHER-TIMEFRAME BACKING)
# ============================================================
# FILE: core/nested_zone_confluence.py
#
# An M1 supply/demand zone or FVG sitting inside/near a level that ALSO
# matters on a higher timeframe (a real swing high/low on M15/H1/H4) is
# a genuine institutional level -- that's structure enough participants
# across enough timeframes actually reacted to. An M1-only zone with no
# higher-timeframe backing is far weaker (could just be M1 noise), but
# was previously scored identically to a genuinely nested one.
#
# Deliberately lightweight rather than running full supply/demand-zone
# detection on each higher timeframe (expensive, and PATTERN_ANALYSIS_
# CURRENT_TF_ONLY already disables the heavy multi-timeframe pattern
# pipeline for performance reasons): this pulls a modest bar sample per
# HTF and checks the M1 zone's level against genuine HTF swing points
# (core/swing_points.py -- same single source of truth used everywhere
# else in this codebase), which is a direct, cheap proxy for "did price
# actually turn here on a higher timeframe too."
# ============================================================

from typing import Dict, Any, List, Optional
import logging

from core.swing_points import find_swing_points, get_min_swing_size
from core.asset_analysis_config import atr_relative_pips

logger = logging.getLogger(__name__)

DEFAULT_TIMEFRAMES = ["M15", "H1", "H4"]
BARS_PER_TIMEFRAME = 150
SWING_LOOKBACK_BARS = 5
# How close the M1 zone must sit to a higher-timeframe swing to count as
# "backed by HTF structure".
#
# ✅ SCALED -- but scaled to EACH TIMEFRAME'S OWN ATR, not M1's.
#
# 15 pips is the whole question here. Live XAGUSD: nearest M15 swing 84
# pips away, H1 148, H4 1361 -- so `nested` was false on every payload and
# the -8.0 M1_ONLY penalty applied unconditionally.
#
# The tempting fix is to scale by M1 ATR, and it is wrong. These swings
# live on M15/H1/H4, whose ATR is roughly 3-8x M1's. Judging an H4 swing
# by an M1 bar's range measures the wrong instrument entirely -- 84 pips
# is 1.3x M1 ATR (sounds far) but only ~0.4x M15 ATR (which is close).
#
# So the ATR is computed per timeframe from the bars this function already
# fetches. No extra data, no extra calls.
DEFAULT_PROXIMITY_PIPS = 15.0
NESTED_ZONE_PROXIMITY_ATR_FRACTION = 0.5


def _atr_pips_from_rates(rates, pip_size: float, period: int = 14) -> float:
    """True-range average over `rates`, in pips.

    Computed locally rather than imported so this module keeps its "no
    dependency beyond swing_points" shape, and because the caller already
    holds exactly the bars needed.
    """
    if rates is None or len(rates) < period + 1 or not pip_size or pip_size <= 0:
        return 0.0
    trs = []
    for i in range(len(rates) - period, len(rates)):
        if i <= 0:
            continue
        high, low = float(rates[i][2]), float(rates[i][3])
        prev_close = float(rates[i - 1][4])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not trs:
        return 0.0
    return (sum(trs) / len(trs)) / pip_size

# Probability-chain effect sizes (same order of magnitude as the
# existing H1-alignment bonus elsewhere in this pipeline).
NESTED_ZONE_BONUS = 10.0
NESTED_ZONE_PENALTY = -8.0


def check_nested_zone_confluence(
    symbol: str,
    zone_level: float,
    pip_size: float,
    timeframes: Optional[List[str]] = None,
    proximity_pips: float = DEFAULT_PROXIMITY_PIPS,
) -> Dict[str, Any]:
    """
    Checks whether zone_level (an M1 SD-zone level or FVG midpoint)
    falls near a genuine swing high/low on any of `timeframes`.
    Degrades gracefully per-timeframe (a fetch failure on one TF
    doesn't invalidate the check on the others) and overall
    (available=False if MT5 itself isn't reachable).
    """
    if timeframes is None:
        timeframes = DEFAULT_TIMEFRAMES

    try:
        import MetaTrader5 as mt5
    except Exception as e:
        return {"available": False, "nested": False, "backing_timeframes": [], "reason": f"MT5 unavailable: {e}"}

    if zone_level is None or pip_size is None or pip_size <= 0:
        return {"available": False, "nested": False, "backing_timeframes": [], "reason": "invalid input"}

    tf_map = {
        "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }

    backing_timeframes: List[str] = []
    nearest_distance_pips: Optional[float] = None
    checked: List[Dict[str, Any]] = []

    for tf_name in timeframes:
        tf_const = tf_map.get(tf_name)
        if tf_const is None:
            checked.append({"timeframe": tf_name, "available": False, "reason": "unrecognized timeframe"})
            continue

        try:
            rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, BARS_PER_TIMEFRAME)
        except Exception as e:
            checked.append({"timeframe": tf_name, "available": False, "reason": f"fetch error: {e}"})
            continue

        if rates is None or len(rates) < (2 * SWING_LOOKBACK_BARS + 1):
            got = 0 if rates is None else len(rates)
            checked.append({"timeframe": tf_name, "available": False, "reason": f"insufficient bars ({got})"})
            continue

        # MT5 rates column order: time=0, open=1, high=2, low=3, close=4
        # -- same convention used throughout this codebase.
        highs = [float(r[2]) for r in rates]
        lows = [float(r[3]) for r in rates]
        # ✅ FIXED: called without pip_size. Same units bug as everywhere
        # else -- the min-swing table is in PIPS and must be converted
        # against the instrument's pip size. pip_size is already a
        # parameter of this function; it simply wasn't being passed on,
        # so HTF swing detection here ran with a threshold 10-100x too
        # permissive on non-FX-major symbols and "genuine HTF swing"
        # meant almost nothing.
        min_amplitude = get_min_swing_size(tf_name, pip_size)

        swing_highs = [s for s in find_swing_points(highs, lookback=SWING_LOOKBACK_BARS, min_amplitude=min_amplitude) if s["type"] == "high"]
        swing_lows = [s for s in find_swing_points(lows, lookback=SWING_LOOKBACK_BARS, min_amplitude=min_amplitude) if s["type"] == "low"]
        all_swings = swing_highs + swing_lows

        if not all_swings:
            checked.append({"timeframe": tf_name, "available": True, "backing": False, "reason": "no significant swings found"})
            continue

        nearest = min(all_swings, key=lambda s: abs(s["price"] - zone_level))
        dist_pips = abs(nearest["price"] - zone_level) / pip_size

        # ✅ Proximity scaled to THIS timeframe's own volatility, so an H4
        # swing is judged by H4's range rather than M1's.
        tf_atr_pips = _atr_pips_from_rates(rates, pip_size)
        tf_proximity = atr_relative_pips(
            proximity_pips, tf_atr_pips, NESTED_ZONE_PROXIMITY_ATR_FRACTION
        )
        backs = dist_pips <= tf_proximity

        checked.append({
            "timeframe": tf_name, "available": True, "backing": backs,
            "nearest_swing_price": round(nearest["price"], 6), "distance_pips": round(dist_pips, 1),
            "tf_atr_pips": round(tf_atr_pips, 1),
            "proximity_pips_used": round(tf_proximity, 1),
        })

        if backs:
            backing_timeframes.append(tf_name)
        if nearest_distance_pips is None or dist_pips < nearest_distance_pips:
            nearest_distance_pips = dist_pips

    nested = len(backing_timeframes) > 0
    return {
        "available": True,
        "nested": nested,
        "backing_timeframes": backing_timeframes,
        "nearest_distance_pips": round(nearest_distance_pips, 1) if nearest_distance_pips is not None else None,
        "checked": checked,
        "reason": (
            f"M1 zone at {zone_level:.5f} is backed by higher-timeframe structure on {', '.join(backing_timeframes)}"
            if nested else
            f"M1 zone at {zone_level:.5f} has no higher-timeframe backing -- M1-only, weaker level "
            f"(checked {len(checked)} timeframes, each against its own ATR-scaled band)"
        ),
    }


def calculate_nested_zone_final_score(
    nested_result: Dict[str, Any],
    base_probability: float,
    at_poi: bool,
) -> Dict[str, Any]:
    """
    Turns HTF-backing (or lack of it) into a signed probability
    adjustment, in the same {"final_score": ...} shape used throughout
    asset_analysis.py's probability chain. Only relevant when at_poi is
    True -- if the trade isn't actually forming off a zone at all, HTF
    backing of "the nearest zone" isn't meaningful and this is a no-op.
    """
    if not at_poi or not nested_result.get("available"):
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "signal": "NOT_APPLICABLE",
            "reason": "not trading off a zone, or HTF data unavailable",
        }

    if nested_result.get("nested"):
        adjustment = NESTED_ZONE_BONUS
        signal = "HTF_BACKED"
    else:
        adjustment = NESTED_ZONE_PENALTY
        signal = "M1_ONLY"

    final_score = max(5.0, min(95.0, base_probability + adjustment))
    return {
        "final_score": round(final_score, 1),
        "adjustment": adjustment,
        "signal": signal,
        "reason": nested_result.get("reason", ""),
        "nested_zone": nested_result,
    }