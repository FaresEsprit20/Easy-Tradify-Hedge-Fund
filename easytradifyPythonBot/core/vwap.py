"""
VWAP ENGINE
===========
FILE: core/vwap.py

Volume-weighted average price, with session and anchored variants and
standard-deviation bands.

WHAT THIS ADDS THAT NOTHING ELSE PROVIDES

The system has three notions of "where price should be" and all of them
are price-only:

    Bollinger      mean +/- k*sigma of CLOSE. Volume never enters.
    EMA / pivots   price averages.
    POC / VAH/VAL  volume profile -- the closest existing analogue, but
                   it is a static histogram over a window, with no notion
                   of a session anchor and no dispersion bands.

VWAP is the first measure of value that is weighted by where business
actually got done, and it is the reference institutions size against.
Price 2 sigma above session VWAP is a different statement from price 2
sigma above a Bollinger band: the first says "extended relative to where
volume traded today", the second says "extended relative to recent
closes". Only the first has a participant behind it.

SESSION VS ANCHORED

    Session VWAP    resets each trading day. The standard intraday
                    reference for value.
    Anchored VWAP   resets from a chosen event -- a swing high, a
                    liquidity sweep, a breakout bar. Answers "what is the
                    average price everyone who traded since THAT moment
                    paid", which is what decides whether they are in
                    profit and therefore likely to defend or abandon a
                    level.

The anchored variant is where this pairs with the liquidity engine: the
average entry of everyone trapped by a sweep is exactly the level they
will defend.

BANDS

sigma is the volume-weighted standard deviation of price around VWAP,
not a simple stdev of closes. That distinction matters -- a level where
enormous volume traded pulls both the mean and the dispersion, which is
the entire point of using volume weighting in the first place.
"""

from typing import Dict, Any, List, Optional
import math
import logging

logger = logging.getLogger(__name__)

# Band multipliers. 1 sigma is the normal working range, 2 sigma is
# statistically extended, 3 sigma is where mean reversion becomes the
# base case in a range and a genuine trend day breaks out instead.
VWAP_BAND_SIGMAS = (1.0, 2.0, 3.0)

# Below this many bars a VWAP is not yet meaningful -- early session
# VWAP sits on top of price and says nothing.
VWAP_MIN_BARS = 10


def _typical_price(bar) -> Optional[float]:
    """(H+L+C)/3 -- the standard VWAP price input.

    Using close alone would discard the range the volume traded across,
    which is the information VWAP exists to capture.
    """
    try:
        return (float(bar[2]) + float(bar[3]) + float(bar[4])) / 3.0
    except (IndexError, TypeError, ValueError):
        return None


def _compute(bars) -> Optional[Dict[str, Any]]:
    """VWAP and volume-weighted sigma over a list of bars."""
    num = den = 0.0
    points: List[tuple] = []
    for b in bars:
        tp = _typical_price(b)
        if tp is None:
            continue
        try:
            vol = float(b[5])
        except (IndexError, TypeError, ValueError):
            vol = 0.0
        # A bar with no reported volume still happened. Weighting it at
        # zero would silently drop it from the average; weighting it at 1
        # keeps it in at minimum influence. On tick-volume feeds this is
        # rarely hit, but a feed that reports 0 for quiet bars would
        # otherwise produce a VWAP built only from busy ones.
        vol = max(vol, 1.0)
        num += tp * vol
        den += vol
        points.append((tp, vol))

    if den <= 0 or len(points) < 2:
        return None

    vwap = num / den
    # Volume-weighted variance: deviations weighted by the volume that
    # traded at them, so a heavily-traded level dominates dispersion the
    # same way it dominates the mean.
    var = sum(v * (tp - vwap) ** 2 for tp, v in points) / den
    return {"vwap": vwap, "sigma": math.sqrt(max(var, 0.0)), "volume": den, "bars": len(points)}


def _bands(vwap: float, sigma: float) -> Dict[str, float]:
    out = {}
    for k in VWAP_BAND_SIGMAS:
        out[f"upper_{k:g}"] = vwap + k * sigma
        out[f"lower_{k:g}"] = vwap - k * sigma
    return out


def _session_start_index(rates, session_bars: int) -> int:
    """Where the current session begins.

    Uses bar timestamps to find the most recent day boundary when they
    are available, and falls back to a fixed bar count when they are not
    -- a fabricated boundary is worse than an approximate one, but an
    approximate one beats refusing to compute.
    """
    n = len(rates)
    try:
        import datetime as _dt
        last_day = _dt.datetime.utcfromtimestamp(float(rates[-1][0])).date()
        for i in range(n - 1, max(0, n - session_bars * 3) - 1, -1):
            day = _dt.datetime.utcfromtimestamp(float(rates[i][0])).date()
            if day != last_day:
                return i + 1
    except (IndexError, TypeError, ValueError, OSError, OverflowError):
        pass
    return max(0, n - session_bars)


def calculate_vwap(rates,
                   current_price: float,
                   pip_size: float,
                   session_bars: int = 1440,
                   anchor_index: int = None) -> Dict[str, Any]:
    """
    Session VWAP, optional anchored VWAP, bands, and where price sits.

    anchor_index anchors a second VWAP from a specific bar -- pass the
    bar_index of a liquidity sweep or a displacement candle to get the
    average price paid by everyone who has traded since that event.

    Returns available=False rather than a neutral value when there is
    not enough data. A VWAP computed from three bars equals price and
    would read as "at value" when the truth is "unknown".
    """
    if rates is None or len(rates) < VWAP_MIN_BARS or not pip_size or pip_size <= 0:
        return {"available": False, "reason": f"needs {VWAP_MIN_BARS}+ bars"}

    start = _session_start_index(rates, session_bars)
    session = _compute(rates[start:])
    if not session:
        return {"available": False, "reason": "no usable volume in session window"}

    vwap, sigma = session["vwap"], session["sigma"]
    bands = _bands(vwap, sigma)

    # Position in sigma units -- the scale-free way to say "how extended".
    # Distance in pips is instrument-specific and has caused repeated
    # calibration bugs in this codebase; sigma is comparable everywhere.
    deviation_sigma = (current_price - vwap) / sigma if sigma > 0 else 0.0

    if deviation_sigma >= 3:
        zone = "EXTREME_ABOVE"
    elif deviation_sigma >= 2:
        zone = "EXTENDED_ABOVE"
    elif deviation_sigma >= 1:
        zone = "ABOVE_VALUE"
    elif deviation_sigma <= -3:
        zone = "EXTREME_BELOW"
    elif deviation_sigma <= -2:
        zone = "EXTENDED_BELOW"
    elif deviation_sigma <= -1:
        zone = "BELOW_VALUE"
    else:
        zone = "AT_VALUE"

    result = {
        "available": True,
        "session_vwap": round(vwap, 6),
        "sigma": round(sigma, 6),
        "sigma_pips": round(sigma / pip_size, 1),
        "bands": {k: round(v, 6) for k, v in bands.items()},
        "deviation_sigma": round(deviation_sigma, 2),
        "deviation_pips": round((current_price - vwap) / pip_size, 1),
        "zone": zone,
        "session_bars": session["bars"],
        "above_vwap": current_price > vwap,
    }

    if anchor_index is not None and 0 <= anchor_index < len(rates) - 2:
        anchored = _compute(rates[anchor_index:])
        if anchored:
            a_vwap, a_sigma = anchored["vwap"], anchored["sigma"]
            result["anchored"] = {
                "vwap": round(a_vwap, 6),
                "sigma_pips": round(a_sigma / pip_size, 1) if pip_size else None,
                "bars_since_anchor": len(rates) - anchor_index,
                "deviation_sigma": round((current_price - a_vwap) / a_sigma, 2) if a_sigma > 0 else 0.0,
                # Everyone who traded since the anchor is, on average,
                # in profit or in loss by this much. That is what decides
                # whether they defend the level or abandon it.
                "participants_in_profit": (
                    "LONGS" if current_price > a_vwap else "SHORTS"
                ),
            }

    return result


def score_vwap_context(vwap_result: Dict[str, Any],
                       direction: str,
                       regime: str = None) -> Dict[str, Any]:
    """
    Turn VWAP position into a verdict for a proposed trade.

    Regime-dependent, and that dependence is the whole point. Two sigma
    above VWAP means "sell the extension" in a range and "this is a trend
    day, do not fade it" in a trend. Reading it the same way in both is
    the exact error that makes Bollinger dangerous in trends -- so this
    refuses to give a verdict when regime is unknown rather than
    guessing.
    """
    if not vwap_result.get("available"):
        return {"score": 0, "stance": None, "reason": vwap_result.get("reason", "unavailable")}

    dev = vwap_result["deviation_sigma"]
    zone = vwap_result["zone"]
    is_buy = str(direction).upper() == "BUY"
    trending = regime in ("TRENDING", "STRONG_TREND", "TRENDING_CALM", "TRENDING_VOLATILE", "BREAKOUT")
    ranging = regime in ("RANGING", "RANGING_CALM", "RANGE", "LOW_VOLATILITY")

    if zone == "AT_VALUE":
        return {"score": 0, "stance": "NEUTRAL",
                "reason": f"price at value ({dev:+.2f} sigma) -- VWAP gives no edge either way"}

    extended_against = (is_buy and dev >= 2) or ((not is_buy) and dev <= -2)
    extended_with = (is_buy and dev <= -2) or ((not is_buy) and dev >= 2)

    if ranging:
        if extended_against:
            return {"score": -10, "stance": "FADE",
                    "reason": f"buying {dev:+.2f} sigma above value in a range -- chasing extension"}
        if extended_with:
            return {"score": 10, "stance": "MEAN_REVERT",
                    "reason": f"{direction} from {dev:+.2f} sigma -- mean reversion toward value"}
        return {"score": 3, "stance": "NEUTRAL", "reason": f"mildly off value ({dev:+.2f} sigma)"}

    if trending:
        # In a trend, distance from VWAP is participation, not excess.
        if extended_against:
            return {"score": 4, "stance": "CONTINUATION",
                    "reason": f"{dev:+.2f} sigma from value in a trend -- extension is the trend, not a fade"}
        if extended_with:
            return {"score": -8, "stance": "COUNTER_TREND",
                    "reason": f"{direction} against a trend that has run {dev:+.2f} sigma from value"}
        return {"score": 2, "stance": "NEUTRAL", "reason": f"near value in a trend ({dev:+.2f} sigma)"}

    # Regime unknown: report the position, decline the verdict. The whole
    # reason this module exists is that the same reading means opposite
    # things in different regimes.
    return {"score": 0, "stance": "UNKNOWN_REGIME",
            "reason": f"price {dev:+.2f} sigma from value; regime unknown so no directional read"}