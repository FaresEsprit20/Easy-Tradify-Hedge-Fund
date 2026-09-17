# ============================================================
# DISPLACEMENT CONFIRMATION
# ============================================================
# FILE: core/displacement_confirmation.py
#
# "At the zone" (proximity) and "confirmed by the zone" (displacement)
# are different things. asset_analysis.py's at_poi flag was previously
# pure proximity -- is_at_zone (supply/demand) and is_price_in_fvg
# (ICT) both just check whether the current/recent price sits inside
# the zone's price bounds, with no check for HOW price got there. A
# slow drift into a level and a decisive, strong-bodied candle
# actually breaking through it look identical to a pure proximity
# check, but they mean very different things -- "price touched it but
# never respected it" is a real, common loss pattern this catches.
#
# Displacement (ICT/SMC terminology): a candle with a large body
# relative to both its own range AND to typical recent volatility
# (ATR) -- decisive, one-directional movement, not a doji/small-body
# candle that happens to overlap the zone.
# ============================================================

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Body must be at least this fraction of the candle's own high-low
# range (rules out long-wick/small-body candles that merely poke into
# the zone without real conviction).
DISPLACEMENT_MIN_BODY_RANGE_RATIO = 0.6

# Body must also be at least this multiple of ATR (rules out a
# small-but-clean-bodied candle on an otherwise quiet bar from
# counting as "displacement" just because its own range happened to be
# small too).
DISPLACEMENT_MIN_BODY_ATR_MULTIPLIER = 0.8

# How many of the most recent bars to check for a qualifying candle.
DEFAULT_LOOKBACK_BARS = 5


def check_displacement_confirmation(
    rates,
    zone_low: float,
    zone_high: float,
    zone_direction: str,
    pip_size: float,
    atr_pips: float,
    lookback_bars: int = DEFAULT_LOOKBACK_BARS,
) -> Dict[str, Any]:
    """
    Checks whether a strong-bodied candle has actually broken INTO the
    zone [zone_low, zone_high] in the last `lookback_bars`, in the
    direction that would confirm the zone, rather than price merely
    drifting into proximity.

    zone_direction: "DEMAND"/"BULLISH" -- looking for a strong bullish
      candle whose LOW reaches into/through the zone (buyers stepping
      in decisively at support).
    zone_direction: "SUPPLY"/"BEARISH" -- looking for a strong bearish
      candle whose HIGH reaches into/through the zone (sellers stepping
      in decisively at resistance).

    For a single-price zone (an SD zone's zone_level, rather than a
    range like an FVG), pass the same value for zone_low and zone_high.
    """
    empty = {"available": False, "confirmed": False, "reason": "insufficient data"}
    if rates is None or len(rates) < lookback_bars or zone_low is None or zone_high is None or pip_size <= 0:
        return empty

    is_demand = zone_direction.upper() in ("DEMAND", "BULLISH", "BUY")
    candidates = rates[-lookback_bars:]

    for bar in candidates:
        try:
            o, h, l, c = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4])
        except (IndexError, TypeError, ValueError):
            continue

        body = abs(c - o)
        candle_range = h - l
        if candle_range <= 0:
            continue

        body_ratio = body / candle_range
        body_pips = body / pip_size
        is_bullish_candle = c > o

        if is_demand:
            reached_zone = l <= zone_high
            directionally_confirming = is_bullish_candle
        else:
            reached_zone = h >= zone_low
            directionally_confirming = not is_bullish_candle

        strong_body = (
            body_ratio >= DISPLACEMENT_MIN_BODY_RANGE_RATIO
            and (atr_pips <= 0 or body_pips >= DISPLACEMENT_MIN_BODY_ATR_MULTIPLIER * atr_pips)
        )

        if reached_zone and directionally_confirming and strong_body:
            return {
                "available": True,
                "confirmed": True,
                "body_pips": round(body_pips, 1),
                "body_range_ratio": round(body_ratio, 2),
                "reason": (
                    f"{'Bullish' if is_bullish_candle else 'Bearish'} displacement candle "
                    f"({body_pips:.1f}p body, {body_ratio:.0%} of its range) broke into the "
                    f"{zone_direction} zone -- confirmed, not just proximity"
                ),
            }

    return {
        "available": True,
        "confirmed": False,
        "reason": (
            f"No strong-bodied displacement candle broke into the {zone_direction} zone in the "
            f"last {lookback_bars} bars -- price is near it but hasn't been confirmed by real "
            f"conviction yet (proximity only)"
        ),
    }