# ============================================================
# STANDALONE FIBONACCI CONFLUENCE
# ============================================================
# FILE: core/fib_confluence.py
#
# Fibonacci levels previously only existed inside Elliott Wave's own
# internal wave-count logic -- meaning a genuinely valid fib
# retracement/extension confluence at the entry zone was invisible
# unless a full, confirmed wave count happened to trigger first. This
# is a standalone layer: it measures retracement/extension levels off
# the most recent swing leg using the SAME swing detector everything
# else in this codebase uses (core/swing_points.py's find_swing_points
# -- single source of truth, see that file's own docstring), and
# checks any given entry zone against those levels directly, with no
# dependency on whether a wave count fired.
# ============================================================

from typing import Dict, Any, List, Optional
import logging

from core.swing_points import find_swing_points, get_min_swing_size
from core.asset_analysis_config import atr_relative_pips

logger = logging.getLogger(__name__)

# Standard retracement ratios (measured back INTO the most recent leg
# from its end).
FIB_RETRACEMENT_RATIOS = [0.382, 0.5, 0.618, 0.786]

# Standard extension ratios (measured beyond the leg, from its start,
# in the leg's own direction) -- these mark potential target/exhaustion
# zones rather than pullback-entry zones.
FIB_EXTENSION_RATIOS = [1.272, 1.618]

# How close a price needs to be to a fib level to count as "confluent".
#
# ✅ Kept as a FLOOR and scaled by ATR (see atr_relative_pips). 8 pips is
# 0.13 ATR on a 60-pip-ATR bar -- tight enough that this module reported
# "outside confluence range" on every payload observed, including one at
# 10.1 pips and one at 11.0, both of which are genuinely close on a bar
# that moves 60 pips.
#
# Observed distances span 0.17 - 1.69 ATR. A threshold at 0.25 ATR
# separates the two nearest from the four far ones, which is the shape a
# confluence flag should have: present sometimes, not constantly and not
# never.
DEFAULT_PROXIMITY_PIPS = 8.0
FIB_PROXIMITY_ATR_FRACTION = 0.25

# Swing detector lookback (bars on each side to qualify as a local
# extreme) -- matches the OHLC adapter's own default in swing_points.py.
SWING_LOOKBACK_BARS = 5

# Score scale matches core/round_number_levels.py's convention (0-100
# unsigned "how strong is this read", direction carried separately by
# `recommendation`).
SCORE_RETRACEMENT_CONFLUENCE = 60
SCORE_EXTENSION_CONFLUENCE = 45


def get_most_recent_swing_leg(rates, timeframe: str = "M1", lookback: int = SWING_LOOKBACK_BARS, pip_size: float = None,
                              atr_pips: float = None) -> Optional[Dict[str, Any]]:
    """
    Finds the most recent completed swing LEG (one swing point followed
    by the next, alternating high/low) using find_swing_points() --
    the exact same detector (and per-timeframe amplitude floor via
    get_min_swing_size()) used everywhere else in this codebase, so
    "what counts as a real swing" is answered identically here as it is
    for supply/demand zones and Elliott Wave.
    """
    if rates is None or len(rates) < (2 * lookback + 1):
        return None

    closes = [float(r[4]) for r in rates]
    # ✅ FIXED: called without pip_size, so the min-swing table (expressed
    # in PIPS) fell back to its 5-decimal-FX assumption -- 10x too
    # permissive on metals, 100x on JPY pairs and equities. This module's
    # own docstring claims it uses "the exact same detector (and
    # per-timeframe amplitude floor)" as everywhere else; without pip_size
    # it used the same detector with a different, broken floor.
    min_amplitude = get_min_swing_size(timeframe, pip_size, atr_pips)
    swings = find_swing_points(closes, lookback=lookback, min_amplitude=min_amplitude)

    if len(swings) < 2:
        return None

    leg_start, leg_end = swings[-2], swings[-1]
    if leg_start["type"] == leg_end["type"]:
        # Two swings of the same type back-to-back shouldn't happen
        # given find_swing_points()'s own alternation, but guard anyway
        # rather than measuring a "leg" between two highs or two lows.
        return None

    return {
        "start_price": leg_start["price"],
        "start_type": leg_start["type"],
        "start_index": leg_start["index"],
        "end_price": leg_end["price"],
        "end_type": leg_end["type"],
        "end_index": leg_end["index"],
    }


def calculate_fib_levels(leg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retracement levels are measured back from the leg's END toward its
    START (the classic "pull back into the move" zone); extension
    levels are measured beyond the leg's END, projected from its START
    in the same direction the leg itself moved.
    """
    start, end = leg["start_price"], leg["end_price"]
    diff = end - start
    direction = "UP" if leg["end_type"] == "high" else "DOWN"

    retracements = {ratio: end - diff * ratio for ratio in FIB_RETRACEMENT_RATIOS}
    extensions = {ratio: start + diff * ratio for ratio in FIB_EXTENSION_RATIOS}

    return {"direction": direction, "retracements": retracements, "extensions": extensions, "leg": leg}


def check_fib_confluence(
    zone_price: float,
    rates,
    pip_size: float,
    timeframe: str = "M1",
    proximity_pips: float = DEFAULT_PROXIMITY_PIPS,
    atr_pips: float = None,
) -> Dict[str, Any]:
    """
    Checks a specific price (an entry zone, an SD zone, an SMC order
    block, or just the current price) against the fib retracement/
    extension levels of the most recent swing leg, independent of
    whether Elliott Wave found a confirmed wave count.

    Returns the same {recommendation, score, confidence, reason} shape
    core/round_number_levels.py uses, so it can be surfaced the same
    way (a standalone entry in asset_analysis.py's "indicators" output
    section) -- retracement confluence gets a directional read matching
    the leg's own direction (classic "buy the pullback in an uptrend /
    sell the pullback in a downtrend" continuation read); extension
    confluence is a potential target/exhaustion zone and deliberately
    NOT given a directional lean on its own (it could mark either a
    breakout continuation or a blow-off top/bottom -- see core/
    exhaustion_filter.py for the dedicated climax-exhaustion read,
    which is the right tool for disambiguating that).
    """
    if pip_size is None or pip_size <= 0 or zone_price is None:
        return {"available": False, "confluent": False, "recommendation": "NEUTRAL", "score": 0, "reason": "invalid input"}

    # ✅ scale the proximity band to what this instrument actually moves
    proximity_pips = atr_relative_pips(proximity_pips, atr_pips, FIB_PROXIMITY_ATR_FRACTION)

    leg = get_most_recent_swing_leg(rates, timeframe=timeframe, pip_size=pip_size, atr_pips=atr_pips)
    if leg is None:
        return {
            "available": False,
            "confluent": False,
            "recommendation": "NEUTRAL",
            "score": 0,
            "confidence": 0,
            "reason": "no recent swing leg found (insufficient bars or no alternating high/low pair)",
        }

    fib_data = calculate_fib_levels(leg)

    candidates: List[Dict[str, Any]] = []
    for ratio, price in fib_data["retracements"].items():
        candidates.append({"ratio": ratio, "price": price, "kind": "retracement"})
    for ratio, price in fib_data["extensions"].items():
        candidates.append({"ratio": ratio, "price": price, "kind": "extension"})

    for c in candidates:
        c["distance_pips"] = abs(zone_price - c["price"]) / pip_size

    nearest = min(candidates, key=lambda c: c["distance_pips"])
    confluent = nearest["distance_pips"] <= proximity_pips

    if not confluent:
        return {
            "available": True,
            "confluent": False,
            "recommendation": "NEUTRAL",
            "score": 0,
            "confidence": 30,
            "nearest_fib_ratio": nearest["ratio"],
            "nearest_fib_kind": nearest["kind"],
            "distance_pips": round(nearest["distance_pips"], 1),
            "proximity_pips_used": round(proximity_pips, 1),
            "leg_direction": fib_data["direction"],
            "reason": f"Nearest fib level ({nearest['ratio']}) is {nearest['distance_pips']:.1f} pips away -- outside confluence range",
        }

    if nearest["kind"] == "retracement":
        # Leg ended UP (an upswing just completed) -> a retracement back
        # into it is a pullback-buy zone, the classic continuation read.
        # Leg ended DOWN -> mirror image, a pullback-sell zone.
        recommendation = "BUY" if fib_data["direction"] == "UP" else "SELL"
        score = SCORE_RETRACEMENT_CONFLUENCE
        confidence = 55
        reason = (
            f"Zone sits at the {nearest['ratio']} retracement of the most recent "
            f"{fib_data['direction'].lower()} swing leg ({nearest['distance_pips']:.1f} pips away) -- "
            f"classic pullback-continuation zone, independent of any Elliott Wave count"
        )
    else:
        # Extension confluence: a real, meaningful level, but genuinely
        # ambiguous on direction without more context -- surfaced as
        # NEUTRAL rather than guessing.
        recommendation = "NEUTRAL"
        score = SCORE_EXTENSION_CONFLUENCE
        confidence = 45
        reason = (
            f"Zone sits at the {nearest['ratio']} extension of the most recent "
            f"{fib_data['direction'].lower()} swing leg ({nearest['distance_pips']:.1f} pips away) -- "
            f"a real target/exhaustion level, but direction from here is genuinely ambiguous on its own"
        )

    return {
        "available": True,
        "confluent": True,
        "recommendation": recommendation,
        "score": score,
        "confidence": confidence,
        "nearest_fib_ratio": nearest["ratio"],
        "nearest_fib_kind": nearest["kind"],
        "nearest_fib_price": round(nearest["price"], 6),
        "distance_pips": round(nearest["distance_pips"], 1),
            "proximity_pips_used": round(proximity_pips, 1),
        "leg_direction": fib_data["direction"],
        "leg_start_price": round(leg["start_price"], 6),
        "leg_end_price": round(leg["end_price"], 6),
        "reason": reason,
    }