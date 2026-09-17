# ============================================================
# MULTI-DEGREE TREND CASCADE
# ============================================================
# FILE: core/trend_cascade.py
#
# Lightweight EMA-slope alignment check across M5/M15/H1/H4 -- "are the
# higher degrees actually agreeing with this trade, or is the entry
# timeframe the odd one out."
#
# Deliberately does NOT run the existing full multi-timeframe pattern
# pipeline (analyze_patterns_multi_timeframe() in asset_analysis.py,
# which pulls 500 bars x up to 5 timeframes and runs full Elliott-wave/
# chart-pattern detection per timeframe -- real cost, and overkill for
# a simple "which way is each degree leaning" read). This only pulls
# enough bars for one 20-period EMA warm-up plus a small slope lookback
# per timeframe (see BARS_NEEDED), then reduces each timeframe to a
# single slope sign: rising / falling / flat.
#
# Wired into asset_analysis.py the same way the existing H1-alignment
# bonus already is: applied to best_probability BEFORE analyze_entry()
# is called (not just a post-hoc display adjustment), so cascade
# agreement can actually help a borderline setup clear the entry
# engine's probability threshold, and cascade disagreement can actually
# keep a trade from firing -- consistent with the ticket's "apply to
# entry filter" framing.
# ============================================================

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

# Timeframe -> weight in the cascade score. Weights sum to 1.0, so the
# weighted average of per-timeframe slope signs (+1 / 0 / -1) lands in
# [-1, +1]: +1 would mean every timeframe is cleanly rising, -1 every
# timeframe cleanly falling.
TREND_CASCADE_WEIGHTS: Dict[str, float] = {
    "M5": 0.1,
    "M15": 0.2,
    "H1": 0.3,
    "H4": 0.4,
}

EMA_PERIOD = 20

# Compare the current EMA value against the EMA this many bars back to
# get a slope, rather than reacting to single-bar EMA wobble.
SLOPE_LOOKBACK_BARS = 3

# Bars fetched per timeframe: one EMA warm-up + slope lookback + a small
# buffer. This is the "no full pattern analysis required" saving --
# analyze_patterns_multi_timeframe() pulls 500 bars/timeframe for real
# pattern detection; this only needs a fraction of that for a slope sign.
# ✅ FIXED (2026-09-15): was EMA_PERIOD + SLOPE_LOOKBACK_BARS + 10 = 33 bars,
# so the EMA had ~13 bars to settle after its SMA seed and the 3-bar slope was
# mostly start-up transient.
BARS_NEEDED = 200
# A slope smaller than this share of the timeframe's own ATR is flat. The
# fixed 0.3-pip threshold was nothing on H4 (and on metals), so the cascade
# was almost never flat -- a noisy sign on 78% of study bars.
FLAT_SLOPE_ATR_FRACTION = 0.1
ATR_BARS = 14

# A slope smaller than this (in pips, over SLOPE_LOOKBACK_BARS bars) is
# treated as FLAT (sign 0) instead of up/down, so noise on a quiet
# timeframe doesn't get counted as directional agreement OR disagreement.
FLAT_SLOPE_PIPS_THRESHOLD = 0.3

# Only act on the cascade once it's reasonably decisive -- timeframes
# splitting close to evenly (score near 0) shouldn't move probability
# either way.
TREND_CASCADE_MIN_ABS_SCORE_TO_ACT = 0.3

# Probability-chain effect sizes, same order of magnitude as the
# existing H1-alignment bonus (+10 / -15) elsewhere in this pipeline --
# scaled by how decisive the cascade is (see calculate_trend_cascade_
# final_score below).
TREND_CASCADE_MAX_BONUS = 12.0
TREND_CASCADE_MAX_PENALTY = -18.0

# The cascade DECIDES the traded side when it is decisive and disagrees with
# the analysis. Not a veto: the trade is still taken, on the cascade's side.
#
# Measured on the 111 stored trades with tick paths (ai/component_forensics):
#   * trade direction right 70.5% when the cascade agreed vs 40.7% when it
#     disagreed (lift +29.8 pts, p=0.008), consistent across both halves;
#   * as a -18 probability nudge it did not stop 27 of 88 counter-cascade
#     trades from clearing the entry threshold;
#   * flipping those trades instead: direction right 59.0% -> 63.8%, total
#     -41.7R -> -25.6R with the current bracket.
# ✅ TURNED OFF 2026-09-16. The evidence above came from 111 stored trades
# whose outcomes were measured on bid-only M1 bars; re-measured on the price
# history with tick-accurate bid/ask brackets (110,603 snapshots, the live
# market-stop trade) the flip earns nothing:
#     flipped by cascade   n 38992 (35.3%)  side right 41.5%  -0.190R
#     not flipped          n 71611 (64.7%)  side right 42.0%  -0.185R
# It also forced the entry gate to test the REJECTED side's probability (a
# live snapshot: SELL entered at 74.3% while its own probability_sell was
# 6.6%), because the flipped side rarely clears the floor on its own score.
# The cascade still moves the probability (calculate_trend_cascade_final_score);
# it no longer decides the side. Set True to restore the flip.
TREND_CASCADE_DECIDES_DIRECTION = False


def cascade_direction_override(cascade_result: Dict[str, Any],
                               best_direction: str) -> Optional[str]:
    """The side to trade instead of `best_direction`, or None to keep it.

    Only a decisive, available cascade (|score| >= the act threshold) that
    points the OTHER way overrides. A neutral, partial-but-indecisive or
    unavailable cascade never changes the direction.
    """
    if not TREND_CASCADE_DECIDES_DIRECTION or not isinstance(cascade_result, dict):
        return None
    if not cascade_result.get("available"):
        return None
    try:
        score = float(cascade_result.get("score") or 0.0)
    except (TypeError, ValueError):
        return None
    if abs(score) < TREND_CASCADE_MIN_ABS_SCORE_TO_ACT:
        return None
    cascade_side = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(cascade_result.get("direction"))
    if cascade_side is None or best_direction not in ("BUY", "SELL"):
        return None
    return cascade_side if cascade_side != best_direction else None


def _ema_series(values: List[float], period: int) -> List[float]:
    """
    Full EMA series, O(n) incremental. Same shape as calculations.py's
    _calculate_macd()._ema_series() helper, duplicated locally so this
    module has no dependency on calculations.py's private (underscore)
    internals.
    """
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    series = [ema]
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
        series.append(ema)
    return series


def _timeframe_slope_sign(closes: List[float], pip_size: float,
                         highs: Optional[List[float]] = None, lows: Optional[List[float]] = None) -> Optional[int]:
    """+1 rising / -1 falling / 0 flat / None if there isn't enough data.

    Flat is judged against the timeframe's own ATR when highs/lows are given
    (FLAT_SLOPE_ATR_FRACTION), else against the legacy pip threshold."""
    ema = _ema_series(closes, EMA_PERIOD)
    if len(ema) < SLOPE_LOOKBACK_BARS + 1:
        return None
    slope = ema[-1] - ema[-1 - SLOPE_LOOKBACK_BARS]
    if highs and lows and len(closes) > ATR_BARS:
        n = len(closes)
        tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
              for i in range(n - ATR_BARS, n)]
        atr = sum(tr) / ATR_BARS
        if atr > 0:
            if abs(slope) < FLAT_SLOPE_ATR_FRACTION * atr:
                return 0
            return 1 if slope > 0 else -1
    slope_pips = slope / pip_size if pip_size > 0 else 0.0
    if abs(slope_pips) < FLAT_SLOPE_PIPS_THRESHOLD:
        return 0
    return 1 if slope_pips > 0 else -1


def get_trend_cascade(symbol: str, pip_size: float) -> Dict[str, Any]:
    """
    Fetch M5/M15/H1/H4 and compute the weighted EMA-slope-sign cascade.

    Degrades gracefully (available=False) if MT5 isn't reachable at all.
    A timeframe that individually fails to fetch or doesn't have enough
    bars yet is simply excluded from the weighted sum -- remaining
    weights are deliberately NOT renormalized up to 1.0, so a partial
    (e.g. 3-of-4 timeframe) cascade reads as weaker evidence rather than
    being inflated to look as confident as a full one. weight_coverage
    reports how much of the full 1.0 weight was actually available.
    """
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        return {
            "available": False,
            "score": 0.0,
            "direction": "NEUTRAL",
            "timeframes": {},
            "weight_coverage": 0.0,
            "reason": f"MT5 unavailable: {e}",
        }

    tf_map = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
    }

    per_tf: Dict[str, Any] = {}
    weighted_sum = 0.0
    weight_used = 0.0

    for tf_name, tf_const in tf_map.items():
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, BARS_NEEDED)
        except Exception as e:
            per_tf[tf_name] = {"slope_sign": None, "reason": f"fetch error: {e}"}
            continue

        if rates is None or len(rates) < EMA_PERIOD + SLOPE_LOOKBACK_BARS:
            got = 0 if rates is None else len(rates)
            per_tf[tf_name] = {"slope_sign": None, "reason": f"insufficient bars ({got})"}
            continue

        # MT5 rates column order: time=0, open=1, high=2, low=3, close=4,
        # tick_volume=5 -- same convention used throughout indicators.py
        # and swing_points.py.
        closes = [float(r[4]) for r in rates]
        sign = _timeframe_slope_sign(closes, pip_size,
                                     [float(r[2]) for r in rates], [float(r[3]) for r in rates])
        per_tf[tf_name] = {"slope_sign": sign}

        if sign is not None:
            weight = TREND_CASCADE_WEIGHTS[tf_name]
            weighted_sum += weight * sign
            weight_used += weight

    if weight_used <= 0:
        return {
            "available": False,
            "score": 0.0,
            "direction": "NEUTRAL",
            "timeframes": per_tf,
            "weight_coverage": 0.0,
            "reason": "no timeframe had enough data",
        }

    score = weighted_sum
    if score >= TREND_CASCADE_MIN_ABS_SCORE_TO_ACT:
        direction = "BULLISH"
    elif score <= -TREND_CASCADE_MIN_ABS_SCORE_TO_ACT:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "available": True,
        "score": round(score, 3),
        "direction": direction,
        "timeframes": per_tf,
        "weight_coverage": round(weight_used, 2),
        "reason": f"cascade score {score:+.2f} from {weight_used:.0%} of full timeframe weight",
    }


def calculate_trend_cascade_final_score(
    cascade_result: Dict[str, Any],
    base_probability: float,
    best_direction: str,
) -> Dict[str, Any]:
    """
    Turns the cascade score into a signed probability adjustment, in the
    same {"final_score": ...} shape calculate_gnn_final_score() /
    calculate_smc_final_score() / etc. already use in asset_analysis.py,
    so this slots into that same probability chain.
    """
    if not cascade_result.get("available"):
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "aligned": None,
            "reason": cascade_result.get("reason", "cascade unavailable"),
        }

    score = cascade_result["score"]
    direction = cascade_result["direction"]

    if direction == "NEUTRAL" or abs(score) < TREND_CASCADE_MIN_ABS_SCORE_TO_ACT:
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "aligned": None,
            "reason": f"cascade indecisive (score {score:+.2f})",
        }

    aligned = (
        (best_direction == "BUY" and direction == "BULLISH") or
        (best_direction == "SELL" and direction == "BEARISH")
    )

    # Scale linearly with |score| between "just decisive" and a fully
    # unanimous cascade (|score| == 1.0), so a bare-minimum cascade only
    # nudges probability while a unanimous 4-timeframe cascade gets the
    # full bonus/penalty.
    scale = min(1.0, abs(score))
    if aligned:
        adjustment = round(TREND_CASCADE_MAX_BONUS * scale, 1)
        reason = f"{best_direction} aligned with {direction} cascade (score {score:+.2f})"
    else:
        adjustment = round(TREND_CASCADE_MAX_PENALTY * scale, 1)
        reason = f"{best_direction} against {direction} cascade (score {score:+.2f})"

    final_score = max(5.0, min(95.0, base_probability + adjustment))
    return {
        "final_score": round(final_score, 1),
        "adjustment": adjustment,
        "aligned": aligned,
        "reason": reason,
    }