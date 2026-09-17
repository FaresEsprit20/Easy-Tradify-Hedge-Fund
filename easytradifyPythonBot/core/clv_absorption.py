# ============================================================
# CLV ABSORPTION -- PHASE 2 ITEM 2
# ============================================================
#
# Readme section 8: "Close Location Value and absorption analysis help
# identify situations where price movement and participation disagree."
#
# WHAT CLV MEASURES
# -----------------
# Where the close sits inside the bar's range:
#
#     CLV = ((close - low) - (high - close)) / (high - low)
#
# +1 means the bar closed on its high, -1 on its low, 0 exactly mid-range. It
# is a statement about who won the bar, and it is scale-free -- a EURUSD bar
# and an XAUUSD bar are directly comparable, which a pip-denominated measure
# would not be.
#
# WHAT ABSORPTION MEANS
# ---------------------
# Effort without result. High participation and a small range in the same bar
# says orders were filled without moving price, which means someone was on the
# other side taking everything offered. That is the signature worth detecting:
# not the volume, and not the small range, but the two together.
#
# The disagreement is the signal. A high-volume bar that travels a long way is
# ordinary continuation and carries no information beyond the move itself.
#
# WHY NEUTRAL AND UNAVAILABLE ARE DIFFERENT RETURNS
# -------------------------------------------------
# A bar with zero range has no CLV -- the denominator is zero, and the honest
# answer is "undefined", not 0.0. Returning 0.0 would place it exactly
# mid-range, which is a measurement claiming perfect balance, and downstream
# an undefined bar and a genuinely balanced bar would be indistinguishable.
# Every function here returns None for unmeasurable and reports availability
# separately.
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

CLV_VERSION = "1.0"

# A bar counts as high participation at this multiple of the recent median
# volume. Median rather than mean: volume distributions are heavily skewed by
# news bars, and one spike drags a mean far enough to hide everything else.
HIGH_VOLUME_MULTIPLE = 1.5

# And as a narrow range at this fraction of the recent median range.
NARROW_RANGE_FRACTION = 0.7

# |CLV| below this is an indecisive close.
INDECISIVE_CLV = 0.3


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> Optional[float]:
    usable = sorted(v for v in values if v is not None)
    if not usable:
        return None
    middle = len(usable) // 2
    if len(usable) % 2:
        return usable[middle]
    return (usable[middle - 1] + usable[middle]) / 2.0


def close_location_value(high: Any, low: Any, close: Any) -> Optional[float]:
    """
    Where the close sits in the bar's range, in [-1, 1].

    Returns None for a zero-range bar rather than 0.0. Zero is "closed exactly
    mid-range", which is a real and different observation from "this bar
    cannot be measured".
    """
    high, low, close = _number(high), _number(low), _number(close)
    if high is None or low is None or close is None:
        return None
    span = high - low
    if span <= 0:
        return None
    value = ((close - low) - (high - close)) / span
    # Guards against a close reported outside its own bar, which happens in
    # real feeds and would otherwise produce |CLV| > 1.
    return max(-1.0, min(1.0, value))


def bar_absorption(bar: Mapping[str, Any], median_volume: Optional[float],
                   median_range: Optional[float]) -> Dict[str, Any]:
    """
    Whether one bar shows effort without result.

    Absorption requires BOTH high participation and a contained range. Either
    alone is unremarkable: a quiet bar with a small range is just a quiet bar,
    and a heavy bar that travelled is ordinary continuation.
    """
    high, low = _number(bar.get("high")), _number(bar.get("low"))
    close, volume = _number(bar.get("close")), _number(bar.get("volume"))
    clv = close_location_value(high, low, close)

    if clv is None or high is None or low is None:
        return {"available": False, "reason": "bar has no measurable range",
                "clv": None, "absorption": False}

    bar_range = high - low
    heavy = (median_volume is not None and volume is not None
             and median_volume > 0
             and volume >= median_volume * HIGH_VOLUME_MULTIPLE)
    narrow = (median_range is not None and median_range > 0
              and bar_range <= median_range * NARROW_RANGE_FRACTION)

    absorption = bool(heavy and narrow)
    return {
        "available": True,
        "clv": round(clv, 6),
        "range": round(bar_range, 8),
        "volume": volume,
        "high_participation": heavy,
        "narrow_range": narrow,
        "absorption": absorption,
        # Which side absorbed: a heavy narrow bar closing high means sellers
        # were absorbed by buyers, and vice versa.
        "absorbed_side": (None if not absorption
                          else "sellers_absorbed" if clv > INDECISIVE_CLV
                          else "buyers_absorbed" if clv < -INDECISIVE_CLV
                          else "two_sided"),
        "indecisive": abs(clv) < INDECISIVE_CLV,
    }


def analyze_clv_absorption(bars: Sequence[Mapping[str, Any]],
                           lookback: int = 20) -> Dict[str, Any]:
    """
    CLV and absorption across a window of bars.

    `lookback` sets the baseline for "high volume" and "narrow range". Those
    are relative terms and this is the only place they are given meaning; a
    fixed threshold would mean something different on every symbol and
    timeframe.
    """
    usable = [bar for bar in (bars or []) if isinstance(bar, Mapping)]
    if len(usable) < 3:
        return {
            "available": False,
            "reason": "need at least 3 bars, got %d" % len(usable),
            "version": CLV_VERSION,
        }

    window = usable[-lookback:] if lookback else usable
    volumes = [_number(bar.get("volume")) for bar in window]
    ranges = []
    for bar in window:
        high, low = _number(bar.get("high")), _number(bar.get("low"))
        ranges.append(high - low if high is not None and low is not None else None)

    median_volume = _median([v for v in volumes if v is not None])
    median_range = _median([r for r in ranges if r is not None])

    results = [bar_absorption(bar, median_volume, median_range) for bar in window]
    measurable = [r for r in results if r["available"]]
    if not measurable:
        return {
            "available": False,
            "reason": "no bar in the window had a measurable range",
            "version": CLV_VERSION,
        }

    clvs = [r["clv"] for r in measurable]
    absorption_bars = [r for r in measurable if r["absorption"]]
    latest = results[-1]

    mean_clv = sum(clvs) / len(clvs)
    return {
        "available": True,
        "version": CLV_VERSION,
        "bars_examined": len(window),
        "bars_measurable": len(measurable),
        "mean_clv": round(mean_clv, 6),
        "latest_clv": latest.get("clv"),
        "latest": latest,
        "absorption_bars": len(absorption_bars),
        "absorption_rate": round(len(absorption_bars) / len(measurable), 4),
        "recent_absorption": bool(latest.get("absorption")),
        "absorbed_side": latest.get("absorbed_side"),
        # The disagreement the readme asks for, stated plainly: participation
        # was high and price did not travel.
        "effort_without_result": bool(absorption_bars),
        "median_volume": median_volume,
        "median_range": median_range,
        "claims_direction": False,
        "interpretation": (
            "absorption marks bars where participation and movement "
            "disagreed; it says someone took the other side, not which way "
            "price goes next"),
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "clv_absorption",
        "version": CLV_VERSION,
        "phase": "2 - item 2 (CLV Absorption)",
        "formula": "CLV = ((close - low) - (high - close)) / (high - low)",
        "thresholds": {
            "high_volume_multiple": HIGH_VOLUME_MULTIPLE,
            "narrow_range_fraction": NARROW_RANGE_FRACTION,
            "indecisive_clv": INDECISIVE_CLV,
        },
        "baseline": "median of the lookback window, not mean",
        "zero_range_bar": "returns None, never 0.0",
        "claims_direction": False,
    }


def self_check(bars: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove CLV is correct at its extremes and absorption needs both conditions.

    The endpoint cases matter more than the middle: a sign error in CLV is
    invisible on ordinary bars and inverts every reading on decisive ones.
    """
    report: Dict[str, Any] = {
        "component": "clv_absorption", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        checks["close_on_high_is_plus_one"] = (
            close_location_value(10, 0, 10) == 1.0)
        checks["close_on_low_is_minus_one"] = (
            close_location_value(10, 0, 0) == -1.0)
        checks["mid_range_is_zero"] = close_location_value(10, 0, 5) == 0.0
        # Undefined, not neutral.
        checks["zero_range_is_none"] = close_location_value(5, 5, 5) is None
        checks["missing_input_is_none"] = (
            close_location_value(None, 0, 5) is None)
        checks["clv_is_bounded"] = (
            close_location_value(10, 0, 99) == 1.0)

        # Absorption needs BOTH high volume and a narrow range.
        heavy_wide = bar_absorption(
            {"high": 20, "low": 0, "close": 19, "volume": 1000}, 100.0, 5.0)
        light_narrow = bar_absorption(
            {"high": 1, "low": 0, "close": 0.9, "volume": 10}, 100.0, 5.0)
        heavy_narrow = bar_absorption(
            {"high": 1, "low": 0, "close": 0.9, "volume": 1000}, 100.0, 5.0)
        checks["volume_alone_is_not_absorption"] = not heavy_wide["absorption"]
        checks["narrow_alone_is_not_absorption"] = not light_narrow["absorption"]
        checks["both_together_is_absorption"] = heavy_narrow["absorption"]
        checks["absorbed_side_identified"] = (
            heavy_narrow["absorbed_side"] == "sellers_absorbed")

        # Too little data must refuse rather than return a confident empty.
        checks["thin_input_refuses"] = (
            analyze_clv_absorption([{"high": 1, "low": 0, "close": 1}])
            ["available"] is False)

        if bars:
            analysis = analyze_clv_absorption(bars)
            checks["analysis_available"] = analysis.get("available")
            checks["bars_examined"] = analysis.get("bars_examined")

        report["ok"] = all(
            bool(value) for key, value in checks.items()
            if key not in ("bars_examined",))
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "CLV_VERSION", "close_location_value", "bar_absorption",
    "analyze_clv_absorption", "get_status", "self_check",
]
