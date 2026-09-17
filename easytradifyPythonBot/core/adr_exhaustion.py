# ============================================================
# AVERAGE DAILY RANGE (ADR) EXHAUSTION CHECK
# ============================================================
# FILE: core/adr_exhaustion.py
#
# If most of a session's "typical" range has already been used, the
# statistics shift: a trade that EXTENDS today's already-established
# move (continuation/breakout in the same direction price has already
# been running) has worse odds than usual, while a trade that FADES
# today's move (mean-reversion, betting the exhausted move stalls/
# reverts) has better odds than usual. Nothing in this pipeline
# currently adjusts for that.
#
# Deliberately doesn't require a separate "setup type" classification
# system (continuation vs mean-reversion tags don't exist anywhere in
# this codebase) -- instead it compares the PROPOSED trade direction
# against the sign of today's own net move so far (today's current
# price vs today's open), which is a direct, self-contained proxy for
# "is this trade extending or fading what today has already done."
# ============================================================

from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

# Standard 20-trading-day ADR baseline.
ADR_LOOKBACK_DAYS = 20

# Once this fraction of the ADR baseline has already been used today,
# the exhaustion adjustment kicks in.
ADR_EXHAUSTION_THRESHOLD_PCT = 0.80

# Probability-chain effect sizes (same order of magnitude as the
# existing H1-alignment bonus elsewhere in this pipeline).
ADR_EXHAUSTION_CONTINUATION_PENALTY = -12.0  # extending an already-exhausted move

# Fading an already-exhausted move. Was a +8 BONUS, on the theory that a
# stretched day snaps back. Measured 2026-09-15 on the 111 stored trades with
# tick paths, once the day's range was used up:
#     fading the move      n=17  win 12%  -0.99R   (halves -1.46 / -0.45)
#     extending the move   n=23  win  9%  -1.14R   (halves -0.51 / -1.36)
#     not exhausted        n=71  win 24%  +0.02R
# An exhausted day loses in BOTH directions -- the range needed to reach the
# target is gone -- so fading it is penalised the same as extending it.
ADR_EXHAUSTION_MEANREVERSION_PENALTY = -12.0


def get_adr_exhaustion(symbol: str, pip_size: float, current_price: float,
                        lookback_days: int = ADR_LOOKBACK_DAYS) -> Dict[str, Any]:
    """
    Fetches daily (D1) bars and compares today's range-used-so-far
    against the average daily range over the prior `lookback_days`
    COMPLETED days (today's own still-forming bar is excluded from the
    baseline average -- it would understate the baseline on any day
    that hasn't finished yet).

    Degrades gracefully (available=False) if MT5 isn't reachable or
    there isn't enough daily history yet.
    """
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        return {"available": False, "exhausted": False, "reason": f"MT5 unavailable: {e}"}

    if pip_size is None or pip_size <= 0:
        return {"available": False, "exhausted": False, "reason": "invalid pip_size"}

    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, lookback_days + 1)
    except Exception as e:
        return {"available": False, "exhausted": False, "reason": f"fetch error: {e}"}

    if rates is None or len(rates) < lookback_days + 1:
        got = 0 if rates is None else len(rates)
        return {"available": False, "exhausted": False, "reason": f"insufficient daily bars ({got}/{lookback_days + 1})"}

    # MT5 rates column order: time=0, open=1, high=2, low=3, close=4 --
    # same convention used throughout this codebase (indicators.py,
    # swing_points.py).
    completed_days = rates[:-1]   # exclude today's still-forming bar
    today = rates[-1]

    daily_ranges_pips = [(float(r[2]) - float(r[3])) / pip_size for r in completed_days]
    adr_pips = sum(daily_ranges_pips) / len(daily_ranges_pips) if daily_ranges_pips else 0.0

    today_open = float(today[1])
    today_high = float(today[2])
    today_low = float(today[3])
    # Use current_price (live) rather than today's bar high/low for
    # "range used so far", since today's bar's own high/low already
    # includes the current price by construction but current_price is
    # the freshest read available between D1 bar refreshes.
    today_high_so_far = max(today_high, current_price)
    today_low_so_far = min(today_low, current_price)
    today_range_pips = (today_high_so_far - today_low_so_far) / pip_size

    pct_of_adr_used = (today_range_pips / adr_pips) if adr_pips > 0 else 0.0
    exhausted = pct_of_adr_used >= ADR_EXHAUSTION_THRESHOLD_PCT

    if current_price > today_open:
        today_net_direction = "UP"
    elif current_price < today_open:
        today_net_direction = "DOWN"
    else:
        today_net_direction = "FLAT"

    return {
        "available": True,
        "adr_pips": round(adr_pips, 1),
        "today_range_pips": round(today_range_pips, 1),
        "pct_of_adr_used": round(pct_of_adr_used, 3),
        "exhausted": exhausted,
        "today_net_direction": today_net_direction,
        "today_open": today_open,
        "lookback_days": lookback_days,
        "reason": (
            f"{pct_of_adr_used:.0%} of {lookback_days}-day ADR ({adr_pips:.1f}p) already used today "
            f"({today_range_pips:.1f}p) -- {'EXHAUSTED' if exhausted else 'normal'}"
        ),
    }


def calculate_adr_exhaustion_final_score(
    adr_result: Dict[str, Any],
    base_probability: float,
    best_direction: str,
) -> Dict[str, Any]:
    """
    Turns ADR exhaustion into a signed probability adjustment, in the
    same {"final_score": ...} shape calculate_gnn_final_score() / etc.
    already use in asset_analysis.py's probability chain.

    Only acts once the session is actually exhausted (>= ADR_EXHAUSTION_
    THRESHOLD_PCT of the baseline used) -- a normal, non-exhausted
    session is a no-op regardless of direction.
    """
    if not adr_result.get("available") or not adr_result.get("exhausted"):
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "signal": "NONE",
            "reason": adr_result.get("reason", "ADR not exhausted / unavailable"),
        }

    net_dir = adr_result.get("today_net_direction")
    extends_move = (best_direction == "BUY" and net_dir == "UP") or (best_direction == "SELL" and net_dir == "DOWN")
    fades_move = (best_direction == "SELL" and net_dir == "UP") or (best_direction == "BUY" and net_dir == "DOWN")

    if extends_move:
        adjustment = ADR_EXHAUSTION_CONTINUATION_PENALTY
        signal = "CONTINUATION_PENALIZED"
        reason = f"{best_direction} extends today's already-exhausted move - {adr_result['reason']}"
    elif fades_move:
        adjustment = ADR_EXHAUSTION_MEANREVERSION_PENALTY
        signal = "FADE_PENALIZED"
        reason = f"{best_direction} fades today's already-exhausted move (exhausted days lose both ways) - {adr_result['reason']}"
    else:
        adjustment = 0.0
        signal = "NONE"
        reason = "ADR exhausted but today's net direction is flat/unclear"

    final_score = max(5.0, min(95.0, base_probability + adjustment))
    return {
        "final_score": round(final_score, 1),
        "adjustment": adjustment,
        "signal": signal,
        "reason": reason,
    }