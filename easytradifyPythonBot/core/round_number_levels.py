# ============================================================
# ROUND-NUMBER / PSYCHOLOGICAL LEVEL S/R
# ============================================================
# FILE: core/round_number_levels.py
#
# Institutional and retail orders cluster at round, "psychological"
# price levels (the .00 "big figure" and the .50 half-level) largely
# independent of where any swing point, supply/demand zone, or SMC
# order block happens to sit -- round numbers are S/R because enough
# market participants treat them as S/R (clustered stop/limit/take-
# profit orders), not because of any chart geometry. The existing
# support_resistance indicator (pivot/swing-based) will never find
# this on its own; this is a genuinely separate structural read.
#
# Deliberately pip-based (not price-based) so it scales correctly
# across instrument conventions (4-decimal FX majors, 2-decimal JPY
# pairs, metals) without per-symbol special-casing: MAJOR_ROUND_STEP
# and MINOR_ROUND_STEP are both derived from pip_size, matching the
# same convention used throughout this codebase (swing_points.py's
# MIN_SWING_SIZE_PIPS, etc).
#
# Standalone module: surfaced directly in asset_analysis.py's output
# ("indicators" -> "round_numbers") as its own structural read,
# independent of any other indicator or aggregation.
# ============================================================

from typing import Dict, Any, List, Optional
import math

# The classic "big figure" -- 100 pips (e.g. 1.1500 -> 1.1600 -> 1.1700
# for a 4-decimal FX pair; 150.00 -> 151.00 for a JPY pair).
MAJOR_ROUND_STEP_PIPS = 100

# The half-level between two big figures (e.g. 1.1550), also
# well-attested as a real (if weaker) psychological level.
MINOR_ROUND_STEP_PIPS = 50

# How close price needs to be to a round level, in pips, to treat it
# as an active "magnet" right now (approaching resistance/support).
DEFAULT_PROXIMITY_PIPS = 5.0

# Score scale matches core/indicators.py's get_sr_recommendation()
# (0-100 unsigned "how strong is this read", direction carried
# separately by `recommendation`) since this is a structural sibling
# of that indicator (support_resistance).
SCORE_FRESH_BREAKOUT = 80
SCORE_MAJOR_MAGNET = 65
SCORE_MINOR_MAGNET = 50


def analyze_round_number_levels(
    current_price: float,
    pip_size: float,
    recent_closes: Optional[List[float]] = None,
    proximity_pips: float = DEFAULT_PROXIMITY_PIPS,
) -> Dict[str, Any]:
    """
    Locate the nearest major/minor round-number levels around
    current_price and turn them into the same {recommendation, score,
    confidence, reason} shape core/indicators.py's other components use,
    so this reads as a normal standalone structural indicator wherever
    it's consumed (see asset_analysis.py's "indicators" -> "round_numbers"
    output section).

    Three distinct reads, in priority order:
      1. Fresh major-level breakout (recent_closes shows price just
         crossed a big-figure level) -- round-number breaks often run
         once cleared, since the crowd of orders sitting AT the level
         has just been absorbed/triggered.
      2. Price currently approaching a round level from either side
         (a "magnet") -- classic bounce/rejection zone, direction
         depends on which side of the level price is approaching from.
      3. Nothing nearby -- NEUTRAL, but the nearest levels above/below
         are still reported (useful as plain S/R reference info
         regardless of whether this component's own vote fires).
    """
    if pip_size is None or pip_size <= 0 or current_price is None or current_price <= 0:
        return {
            "available": False,
            "recommendation": "NEUTRAL",
            "score": 0,
            "confidence": 0,
            "reason": "invalid price/pip_size",
        }

    major_step = pip_size * MAJOR_ROUND_STEP_PIPS
    minor_step = pip_size * MINOR_ROUND_STEP_PIPS

    nearest_major_below = math.floor(current_price / major_step) * major_step
    nearest_major_above = nearest_major_below + major_step
    nearest_minor_below = math.floor(current_price / minor_step) * minor_step
    nearest_minor_above = nearest_minor_below + minor_step

    dist_major_above_pips = round((nearest_major_above - current_price) / pip_size, 4)
    dist_major_below_pips = round((current_price - nearest_major_below) / pip_size, 4)
    dist_minor_above_pips = round((nearest_minor_above - current_price) / pip_size, 4)
    dist_minor_below_pips = round((current_price - nearest_minor_below) / pip_size, 4)

    # ✅ Major and minor levels coincide by construction every time
    # (major_step is an exact multiple of minor_step -- every big figure
    # IS also a minor-step multiple), so at those coincidence points the
    # raw float distances can differ by a sub-pip epsilon in either
    # direction depending on floating-point rounding noise, and a naive
    # min()-by-distance can misclassify an obvious major level (e.g.
    # 1.1600) as "minor" purely from that noise. Distances are rounded
    # above to kill the noise, and major is explicitly preferred
    # whenever the two are within that same rounding tolerance of each
    # other, since a major level is never "just" a minor one.
    TIE_TOLERANCE_PIPS = 0.01

    def _pick_candidate(major_dist, major_level, minor_dist, minor_level):
        if abs(major_dist - minor_dist) <= TIE_TOLERANCE_PIPS:
            return (major_level, major_dist, "major")
        return (major_level, major_dist, "major") if major_dist < minor_dist else (minor_level, minor_dist, "minor")

    resistance_candidates = [_pick_candidate(dist_major_above_pips, nearest_major_above, dist_minor_above_pips, nearest_minor_above)]
    resistance_candidates = [c for c in resistance_candidates if c[1] > 0.01]
    nearest_resistance = resistance_candidates[0] if resistance_candidates else None

    support_candidates = [_pick_candidate(dist_major_below_pips, nearest_major_below, dist_minor_below_pips, nearest_minor_below)]
    support_candidates = [c for c in support_candidates if c[1] > 0.01]
    nearest_support = support_candidates[0] if support_candidates else None

    # --- 1. Fresh major-level breakout ---
    fresh_major_breakout = None
    if recent_closes and len(recent_closes) >= 2:
        prev_close = recent_closes[-2]
        prev_major_below = math.floor(prev_close / major_step) * major_step
        if prev_major_below != nearest_major_below:
            direction = "UP" if current_price > prev_close else "DOWN"
            crossed_level = nearest_major_below if direction == "UP" else nearest_major_below + major_step
            fresh_major_breakout = {"direction": direction, "level": round(crossed_level, 6)}

    # --- 2. Active magnet (nearer of resistance/support, if within proximity) ---
    magnet_level, magnet_type, magnet_strength, magnet_distance_pips = None, None, None, None
    if nearest_resistance and nearest_resistance[1] <= proximity_pips:
        magnet_level, magnet_distance_pips, magnet_strength = nearest_resistance
        magnet_type = "resistance"
    if nearest_support and nearest_support[1] <= proximity_pips:
        if magnet_level is None or nearest_support[1] < magnet_distance_pips:
            magnet_level, magnet_distance_pips, magnet_strength = nearest_support
            magnet_type = "support"
    magnet_active = magnet_level is not None

    # --- Turn into recommendation/score/reason ---
    if fresh_major_breakout:
        recommendation = "BUY" if fresh_major_breakout["direction"] == "UP" else "SELL"
        score = SCORE_FRESH_BREAKOUT
        confidence = 70
        reason = (
            f"Fresh break of major round number {fresh_major_breakout['level']:.5f} -- "
            f"round-number breaks often run once the resting order cluster there is absorbed"
        )
    elif magnet_active and magnet_type == "resistance":
        recommendation = "SELL"
        score = SCORE_MAJOR_MAGNET if magnet_strength == "major" else SCORE_MINOR_MAGNET
        confidence = 60 if magnet_strength == "major" else 50
        reason = (
            f"Price approaching {magnet_strength} round-number resistance at {magnet_level:.5f} "
            f"({magnet_distance_pips:.1f} pips away) -- classic rejection zone, independent of any swing point"
        )
    elif magnet_active and magnet_type == "support":
        recommendation = "BUY"
        score = SCORE_MAJOR_MAGNET if magnet_strength == "major" else SCORE_MINOR_MAGNET
        confidence = 60 if magnet_strength == "major" else 50
        reason = (
            f"Price approaching {magnet_strength} round-number support at {magnet_level:.5f} "
            f"({magnet_distance_pips:.1f} pips away) -- classic bounce zone, independent of any swing point"
        )
    else:
        recommendation = "NEUTRAL"
        score = 0
        confidence = 30
        reason = "No round number within proximity range"

    return {
        "available": True,
        "recommendation": recommendation,
        "score": score,
        "confidence": confidence,
        "reason": reason,
        "nearest_major_above": round(nearest_major_above, 6),
        "nearest_major_below": round(nearest_major_below, 6),
        "nearest_minor_above": round(nearest_minor_above, 6),
        "nearest_minor_below": round(nearest_minor_below, 6),
        "distance_to_resistance_pips": round(nearest_resistance[1], 1) if nearest_resistance else None,
        "distance_to_support_pips": round(nearest_support[1], 1) if nearest_support else None,
        "magnet_active": magnet_active,
        "magnet_level": round(magnet_level, 6) if magnet_level is not None else None,
        "magnet_type": magnet_type,
        "magnet_strength": magnet_strength,
        "fresh_major_breakout": fresh_major_breakout,
    }


def check_round_number_confluence(
    zone_price: float,
    pip_size: float,
    proximity_pips: float = DEFAULT_PROXIMITY_PIPS,
) -> Dict[str, Any]:
    """
    Standalone confluence check for a SPECIFIC zone/level the system
    already identified some other way (a supply/demand zone, an SMC
    order block, an FVG boundary, etc.) -- "does this technical level
    ALSO happen to sit on a round psychological number." Two
    independent reasons a level matters is stronger evidence than one;
    this is meant to be layered onto an existing zone's own score, not
    to replace analyze_round_number_levels() above (which stands on its
    own even when no other zone was found nearby).
    """
    result = analyze_round_number_levels(zone_price, pip_size, recent_closes=None, proximity_pips=proximity_pips)
    if not result.get("available"):
        return {"confluent": False, "reason": "invalid input"}

    # At the zone's own price, "resistance" vs "support" framing doesn't
    # apply (there's no direction of approach to speak of) -- only
    # whether SOME round level sits right at/near this exact price.
    dist_r = result.get("distance_to_resistance_pips")
    dist_s = result.get("distance_to_support_pips")
    candidates = [d for d in (dist_r, dist_s) if d is not None]
    nearest_dist = min(candidates) if candidates else None

    confluent = nearest_dist is not None and nearest_dist <= proximity_pips
    return {
        "confluent": confluent,
        "distance_pips": round(nearest_dist, 1) if nearest_dist is not None else None,
        "reason": (
            f"Zone sits within {nearest_dist:.1f} pips of a round psychological level"
            if confluent else "No round number near this zone"
        ),
    }