# ============================================================
# RETEST-OVER-FIRST-TOUCH CONFIRMATION
# ============================================================
# FILE: core/retest_confirmation.py
#
# Buying the initial break of a level is the classic breakout-trap
# entry: price pokes through, triggers the crowd of breakout orders,
# then fails and reverses. Waiting for price to break, pull back to
# retest the level, and hold there (confirming the old resistance is
# now support, or vice versa) is the mechanical, classic fix -- it
# gives up some of the move but cuts a real class of breakout-trap
# losses.
#
# A small state machine over recent closes, not a specific detector --
# reusable against any breakout level from any source (a round number,
# a support/resistance pivot, a supply/demand zone boundary, etc.).
# ============================================================

from typing import Dict, Any
import logging

from core.asset_analysis_config import atr_relative_pips

logger = logging.getLogger(__name__)

# How decisively a close must clear the level to count as a genuine
# break, in pips (rules out a wick/noise poke through the level).
# ✅ All three of these are FLOORS now, scaled by ATR at call time.
#
# 2 / 5 / 2.5 pips are sane on a 10-pip-ATR FX major. On XAGUSD (ATR
# 47-76) a 2-pip "decisive break" is noise -- roughly 3% of one bar's
# range -- so breaks confirm on ticks, while a 5-pip retest tolerance is
# narrower than the spread, so genuine retests are missed. Live payloads
# show this module stuck between NO_BREAK and BROKEN_AWAITING_RETEST and
# never once reaching RETEST_CONFIRMED.
#
# Fractions chosen so the three keep their RELATIVE proportions (a break
# must clear more than the retest failure buffer, which is tighter than
# the retest tolerance) rather than being picked independently.
BREAK_CONFIRM_PIPS = 2.0
BREAK_CONFIRM_ATR_FRACTION = 0.05

# How close price needs to come back to the level, in pips, to count
# as a retest of it.
DEFAULT_RETEST_TOLERANCE_PIPS = 5.0
RETEST_TOLERANCE_ATR_FRACTION = 0.12

# How far back through the old level price is allowed to close during/
# after the retest before it counts as a failed retest (invalidated
# breakout), rather than just a normal pullback that held.
RETEST_FAILURE_TOLERANCE_PIPS = 2.5
RETEST_FAILURE_ATR_FRACTION = 0.06

DEFAULT_LOOKBACK_BARS = 20


def check_retest_confirmation(
    rates,
    breakout_level: float,
    breakout_direction: str,
    pip_size: float,
    lookback_bars: int = DEFAULT_LOOKBACK_BARS,
    retest_tolerance_pips: float = DEFAULT_RETEST_TOLERANCE_PIPS,
    atr_pips: float = None,
) -> Dict[str, Any]:
    """
    breakout_direction: "UP" (price broke above breakout_level, looking
    to confirm a retest-and-hold from above) or "DOWN" (broke below,
    retest-and-hold from below).

    Walks the closes in order looking for: (1) a bar that closed
    decisively beyond breakout_level -- the break itself; (2) a later
    bar that pulled back to within retest_tolerance_pips of the level --
    the retest; (3) every close after the retest staying on the
    breakout side (within RETEST_FAILURE_TOLERANCE_PIPS) -- the hold.
    `phase` reports exactly where in that sequence price currently is,
    since "hasn't broken yet" and "broke but failed the retest" are
    both NOT confirmed but mean very different things.
    """
    empty = {"available": False, "confirmed": False, "phase": "NO_DATA", "reason": "insufficient data"}
    if rates is None or len(rates) < 3 or breakout_level is None or pip_size <= 0:
        return empty

    # ✅ scale all three bands to the instrument (no-ops when atr_pips is None)
    break_confirm_pips = atr_relative_pips(BREAK_CONFIRM_PIPS, atr_pips, BREAK_CONFIRM_ATR_FRACTION)
    retest_tolerance_pips = atr_relative_pips(retest_tolerance_pips, atr_pips, RETEST_TOLERANCE_ATR_FRACTION)
    failure_tolerance_pips = atr_relative_pips(RETEST_FAILURE_TOLERANCE_PIPS, atr_pips, RETEST_FAILURE_ATR_FRACTION)

    is_up = breakout_direction.upper() == "UP"
    window = rates[-lookback_bars:] if len(rates) >= lookback_bars else rates
    closes = [float(r[4]) for r in window]

    break_confirm_price = breakout_level + (break_confirm_pips * pip_size if is_up else -break_confirm_pips * pip_size)

    break_idx = None
    for i, c in enumerate(closes):
        if (is_up and c >= break_confirm_price) or (not is_up and c <= break_confirm_price):
            break_idx = i
            break

    if break_idx is None:
        return {
            "available": True,
            "confirmed": False,
            "phase": "NO_BREAK",
            "reason": f"price hasn't decisively broken {breakout_direction} through {breakout_level:.5f} yet",
        }

    retest_idx = None
    for i in range(break_idx + 1, len(closes)):
        if abs(closes[i] - breakout_level) <= retest_tolerance_pips * pip_size:
            retest_idx = i
            break

    if retest_idx is None:
        return {
            "available": True,
            "confirmed": False,
            "phase": "BROKEN_AWAITING_RETEST",
            "reason": (
                f"broke {breakout_direction} through {breakout_level:.5f} but hasn't pulled back to "
                f"retest it yet -- entering now would be buying the initial break, not a confirmed retest"
            ),
        }

    failure_threshold = failure_tolerance_pips * pip_size
    held = True
    for i in range(retest_idx + 1, len(closes)):
        c = closes[i]
        if is_up and c < breakout_level - failure_threshold:
            held = False
            break
        if not is_up and c > breakout_level + failure_threshold:
            held = False
            break

    if not held:
        return {
            "available": True,
            "confirmed": False,
            "phase": "RETEST_FAILED",
            "reason": f"retested {breakout_level:.5f} but closed back through it -- breakout invalidated",
        }

    return {
        "available": True,
        "confirmed": True,
        "phase": "RETEST_CONFIRMED",
        "reason": f"broke {breakout_direction} through {breakout_level:.5f}, retested, and held -- confirmed",
    }