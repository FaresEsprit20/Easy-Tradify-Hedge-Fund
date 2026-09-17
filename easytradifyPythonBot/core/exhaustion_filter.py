# ============================================================
# EXHAUSTION / CLIMAX FILTER
# ============================================================
# FILE: core/exhaustion_filter.py
#
# Detects a classic buying-climax / selling-climax reversal bar: range
# expansion, a volume spike, and a long rejection wick all firing on the
# SAME bar, followed by a next bar that fails to extend the move any
# further (no follow-through). One detector, used two ways:
#
#   - EXIT (asset_analysis.py, existing-position branch): a climax
#     AGAINST the open trade's own direction is an early-warning exit.
#     See calculate_exhaustion_exit_signal().
#
#   - ENTRY (asset_analysis.py, pre-entry-decision probability chain):
#     the SAME detection, applied direction-aware --
#       * best_direction CONTINUES the exhausted move (buying a blow-off
#         top, selling a blow-off bottom) -> hard probability penalty
#         (trend-entry blocker, "avoid buying top/selling bottom").
#       * best_direction FADES the exhausted move (counter-trend against
#         it) -> probability bonus (entry fade signal).
#     See calculate_exhaustion_final_score().
#
# All four conditions must agree for is_exhaustion=True -- deliberately
# strict (a rare, high-conviction signal), per the ticket's "exit when
# ALL FOUR conditions met" spec.
# ============================================================

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# Condition 1: the candidate bar's range (high-low) must be at least this
# multiple of ATR to count as "expanded."
RANGE_EXPANSION_ATR_MULTIPLIER = 1.5

# Condition 2: the candidate bar's volume must be at least this multiple
# of its own rolling average. Deliberately a higher bar than the
# general-purpose VOLUME_SPIKE_THRESHOLD_M1 (1.2x, asset_analysis_config.py)
# used elsewhere for routine entry timing -- a true climax bar is a much
# rarer, more extreme event than ordinary "volume picking up."
EXHAUSTION_VOLUME_SPIKE_MULTIPLIER = 2.0

# Condition 3: the dominant wick must be at least this multiple of the body.
EXHAUSTION_WICK_BODY_MULTIPLIER = 1.5

# Probability-chain effect sizes for the ENTRY use (see
# calculate_exhaustion_final_score). Large enough that, combined with the
# existing post-chain probability floor gate in asset_analysis.py, the
# block case reliably pushes a trade to SKIP rather than just denting the
# displayed number.
EXHAUSTION_BLOCK_PENALTY = -30.0   # buying a confirmed top / selling a confirmed bottom
EXHAUSTION_FADE_BONUS = 12.0       # fading a confirmed climax (same order of magnitude as the H1-alignment bonus)


def _bar_fields(bar) -> Dict[str, float]:
    """
    Extract OHLCV from one row of an MT5 rates array using the real
    field order: time=0, open=1, high=2, low=3, close=4, tick_volume=5.
    Spelled out explicitly (rather than assumed) because
    _analyze_candlestick_component() in asset_analysis.py was found to
    read open/low from the wrong positions -- see the fix note there.
    """
    return {
        "open": float(bar[1]),
        "high": float(bar[2]),
        "low": float(bar[3]),
        "close": float(bar[4]),
        "volume": float(bar[5]) if len(bar) > 5 else 0.0,
    }


def detect_exhaustion_climax(
    rates,
    pip_size: float,
    atr_pips: float,
    lookback: int = 20,
    timeframe: str = "M1",
) -> Dict[str, Any]:
    """
    NOTE ON `lookback`: it does NOT set an analysis window. It is used
    only in the data-sufficiency guard below. The volume baseline comes
    from get_volume_ratio()'s own VOLUME_BASELINE_BARS window (200 bars
    on M1), and every other condition reads a single bar. Named for what
    it looks like it does rather than what it does; documented rather
    than renamed, since it is part of the public signature.

    Evaluate the last fully CLOSED bar (rates[-2]) as a climax candidate,
    using the current/forming bar (rates[-1]) only to check condition 4
    (no follow-through yet). rates[-1] is still in progress in a live
    M1 loop, so it can't itself be judged a finished climax bar -- but it
    CAN already tell us whether the prior bar's move has continued.

    Returns a dict with each of the four condition flags plus
    is_exhaustion (True only if all four agree) and, when true, which
    side the climax pushed: BEARISH_CLIMAX (blow-off top, upper wick
    dominant) or BULLISH_CLIMAX (blow-off bottom, lower wick dominant) --
    same upper-wick/lower-wick -> bearish/bullish convention
    _analyze_candlestick_component() already uses for shooting_star/hammer.
    """
    empty = {
        "available": False,
        "is_exhaustion": False,
        "direction": None,
        "conditions": {
            "range_expansion": False,
            "volume_spike": False,
            "rejection_wick": False,
            "no_follow_through": False,
        },
        # ✅ ADDED: this path previously omitted "details" entirely while
        # the success path always includes it, so the shape of the
        # returned dict depended on whether detection ran. Any consumer
        # indexing result["details"] would KeyError only on the rare
        # short-data path -- the worst kind of shape inconsistency to
        # leave in, since it never shows up in normal operation.
        "details": {},
        "reason": "insufficient data",
    }
    if rates is None or len(rates) < lookback + 2 or pip_size <= 0:
        return empty

    climax = _bar_fields(rates[-2])   # last fully closed bar
    current = _bar_fields(rates[-1])  # forming bar -- follow-through check only

    body = abs(climax["close"] - climax["open"])
    total_range = climax["high"] - climax["low"]
    if total_range <= 0:
        return empty

    if climax["close"] >= climax["open"]:
        lower_wick = climax["open"] - climax["low"]
        upper_wick = climax["high"] - climax["close"]
    else:
        lower_wick = climax["close"] - climax["low"]
        upper_wick = climax["high"] - climax["open"]
    lower_wick = max(0.0, lower_wick)
    upper_wick = max(0.0, upper_wick)

    body_pips = body / pip_size
    range_pips = total_range / pip_size

    # Condition 1: range expansion vs ATR
    range_expansion = bool(atr_pips > 0 and range_pips >= (RANGE_EXPANSION_ATR_MULTIPLIER * atr_pips))

    # Condition 2: volume spike -- reuse get_volume_ratio()'s own
    # baseline-window averaging (core/indicators.py) instead of
    # re-deriving it, so "average volume" means the same thing here as
    # everywhere else in the pipeline. volumes excludes the still-forming
    # bar; its last entry is the climax bar itself (== volumes[-1] inside
    # get_volume_ratio).
    volumes = [float(r[5]) for r in rates[:-1]]
    try:
        from core.indicators import get_volume_ratio
        # ✅ FIXED: timeframe was hardcoded "M1" here. get_volume_ratio()
        # picks its averaging window from VOLUME_BASELINE_BARS, which is
        # 200 bars for M1 but 100 for M5/M15/M30/H1/H4 and 50 for D1 -- so
        # on any non-M1 run this measured the climax bar against a
        # 200-bar window the rest of the pipeline would never have used,
        # and "2.0x average volume" quietly meant a different thing here
        # than everywhere else. Now passed through from the caller.
        vol_ratio, _, _ = get_volume_ratio(volumes, timeframe=timeframe, candle_progress_pct=100)
    except Exception as e:
        logger.debug(f"[EXHAUSTION] get_volume_ratio unavailable, defaulting to 1.0x: {e}")
        vol_ratio = 1.0
    volume_spike = vol_ratio >= EXHAUSTION_VOLUME_SPIKE_MULTIPLIER

    # Condition 3: rejection wick. Dominant side decides climax direction.
    dominant_wick = "upper" if upper_wick >= lower_wick else "lower"
    wick_pips = (upper_wick if dominant_wick == "upper" else lower_wick) / pip_size
    if body_pips > 0:
        rejection_wick = wick_pips >= (EXHAUSTION_WICK_BODY_MULTIPLIER * body_pips)
    else:
        # Zero-body climax bar (rare, e.g. a perfect doji) -- still counts
        # if the wick itself is a meaningful fraction of ATR, otherwise a
        # huge-wick doji would fail this condition purely because there's
        # no body to compare against.
        rejection_wick = bool(atr_pips > 0 and wick_pips >= (EXHAUSTION_WICK_BODY_MULTIPLIER * 0.3 * atr_pips))

    climax_direction = "BEARISH_CLIMAX" if dominant_wick == "upper" else "BULLISH_CLIMAX"

    # Condition 4: no follow-through -- the current (forming) bar must
    # fail to extend price beyond the climax bar's extreme in the climax
    # bar's own directional push.
    if climax_direction == "BEARISH_CLIMAX":
        no_follow_through = current["high"] <= climax["high"]
    else:
        no_follow_through = current["low"] >= climax["low"]

    is_exhaustion = range_expansion and volume_spike and rejection_wick and no_follow_through

    conditions = {
        "range_expansion": range_expansion,
        "volume_spike": volume_spike,
        "rejection_wick": rejection_wick,
        "no_follow_through": no_follow_through,
    }
    details = {
        "range_pips": round(range_pips, 1),
        "atr_pips": round(atr_pips, 1),
        "volume_ratio": round(vol_ratio, 2),
        "body_pips": round(body_pips, 1),
        "wick_pips": round(wick_pips, 1),
        "dominant_wick": dominant_wick,
    }

    if is_exhaustion:
        reason = (
            f"{climax_direction} climax bar: range {range_pips:.1f}p "
            f"(>= {RANGE_EXPANSION_ATR_MULTIPLIER:.1f}x ATR {atr_pips:.1f}p), "
            f"volume {vol_ratio:.1f}x avg, {dominant_wick} wick {wick_pips:.1f}p "
            f"(>= {EXHAUSTION_WICK_BODY_MULTIPLIER:.1f}x body {body_pips:.1f}p), "
            f"no follow-through since"
        )
    else:
        failed = [k for k, v in conditions.items() if not v]
        reason = f"no climax (failed: {', '.join(failed)})" if failed else "no climax"

    return {
        "available": True,
        "is_exhaustion": is_exhaustion,
        "direction": climax_direction if is_exhaustion else None,
        "conditions": conditions,
        "details": details,
        "reason": reason,
    }


def calculate_exhaustion_exit_signal(
    exhaustion_result: Dict[str, Any],
    position_direction: str,
) -> Dict[str, Any]:
    """
    EXIT use (task 3): fires only when the detected climax opposes the
    direction of an existing trend trade -- a BEARISH_CLIMAX (blow-off
    top) against an open BUY, or a BULLISH_CLIMAX (blow-off bottom)
    against an open SELL. A climax that AGREES with the trade's own
    direction isn't an exit signal, it's just the trade still running.
    """
    if not exhaustion_result.get("is_exhaustion"):
        return {"should_exit": False, "reason": None}

    direction = exhaustion_result["direction"]
    opposes = (
        (position_direction == "BUY" and direction == "BEARISH_CLIMAX") or
        (position_direction == "SELL" and direction == "BULLISH_CLIMAX")
    )
    if not opposes:
        return {"should_exit": False, "reason": None}

    return {
        "should_exit": True,
        "reason": f"Exhaustion/climax exit ({direction}): {exhaustion_result['reason']}",
    }


def calculate_exhaustion_final_score(
    exhaustion_result: Dict[str, Any],
    base_probability: float,
    best_direction: str,
) -> Dict[str, Any]:
    """
    ENTRY use (task 4): same detection, applied as a signed probability
    adjustment, in the same {"final_score": ...} shape calculate_gnn_
    final_score() / calculate_smc_final_score() / etc. already use in
    asset_analysis.py's probability chain.

      - best_direction CONTINUES the exhausted move (buying a
        BEARISH_CLIMAX top, selling a BULLISH_CLIMAX bottom) -> hard
        penalty (trend-entry blocker).
      - best_direction FADES the exhausted move (the opposite case) ->
        bonus (entry fade signal) -- corroborating evidence for a
        counter-trend entry, not proof of one on its own, so it's sized
        smaller than the block penalty.
      - no exhaustion detected -> no-op.
    """
    if not exhaustion_result.get("is_exhaustion"):
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "signal": "NONE",
            "reason": exhaustion_result.get("reason", "no climax detected"),
        }

    direction = exhaustion_result["direction"]
    continues_move = (
        (best_direction == "BUY" and direction == "BEARISH_CLIMAX") or
        (best_direction == "SELL" and direction == "BULLISH_CLIMAX")
    )
    fades_move = (
        (best_direction == "SELL" and direction == "BEARISH_CLIMAX") or
        (best_direction == "BUY" and direction == "BULLISH_CLIMAX")
    )

    if continues_move:
        adjustment = EXHAUSTION_BLOCK_PENALTY
        signal = "TREND_ENTRY_BLOCKED"
        reason = f"Blocking {best_direction} into a {direction} - {exhaustion_result['reason']}"
    elif fades_move:
        adjustment = EXHAUSTION_FADE_BONUS
        signal = "FADE_CONFLUENCE"
        reason = f"{best_direction} fades confirmed {direction} - {exhaustion_result['reason']}"
    else:
        adjustment = 0.0
        signal = "NONE"
        reason = "climax detected but direction unclear"

    final_score = max(5.0, min(95.0, base_probability + adjustment))
    return {
        "final_score": round(final_score, 1),
        "adjustment": adjustment,
        "signal": signal,
        "reason": reason,
        "climax": exhaustion_result,
    }