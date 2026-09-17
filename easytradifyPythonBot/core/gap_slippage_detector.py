# ============================================================
# GAP & SLIPPAGE RISK DETECTOR
# ============================================================
# FILE: core/gap_slippage_detector.py
#
# Detects price gaps and estimates slippage risk conditions.
#
# ✅ CORRECTED HEADER. This block used to read "ADVISORY / REPORTING
# ONLY ... does NOT modify final_decision, does NOT set veto=True, does
# NOT force should_close_position ... advisory output only." That was
# true when written and is no longer true of the whole module: section 4
# (calculate_gap_slippage_final_score, added later and documented in
# place) applies a real, bounded probability penalty of up to
# GAP_SLIPPAGE_WEIGHT x 100 = 10 points, and it fires on essentially
# every bar -- live payloads show -3.5 (ELEVATED) and -8.0 (HIGH)
# routinely. A reader trusting the old header would undercount the
# probability chain by up to 10 points.
#
# What is still true, precisely:
#   - detect_price_gap() and assess_slippage_risk() are pure detection.
#   - build_gap_slippage_report()'s avoid_trade_recommended /
#     should_exit_recommended remain ADVISORY: nothing reads them, they
#     do not set veto, do not touch final_decision, and do not force a
#     position close.
#   - calculate_gap_slippage_final_score() is NOT advisory. It is wired
#     into best_probability in asset_analysis.py exactly like the other
#     post-entry adjustments, and it only ever subtracts (gap/thin-book
#     risk has no directional opinion -- see that function's own note).
# ============================================================

from typing import Dict, Any, List, Optional
import numpy as np


# ------------------------------------------------------------
# 1. PRICE GAP DETECTION
# ------------------------------------------------------------
# A gap: the open of a bar differs from the close of the previous bar by
# more than a pip threshold, with no trading in between (common around
# session opens, weekends, and high-impact news). Uses the raw OHLC
# `rates` array already available in asset_analysis.py's scope.
#
# rates column convention (matches order_flow_forensics.py / swing_points.py
# usage elsewhere in this codebase):
#   index 0 = time, 1 = open, 2 = high, 3 = low, 4 = close, 5 = tick_volume

def detect_price_gap(
    rates: np.ndarray,
    pip_size: float,
    gap_threshold_pips: float = 3.0,
    lookback_bars: int = 20,
) -> Dict[str, Any]:
    if rates is None or len(rates) < 2:
        return {"available": False, "reason": "insufficient rate data"}

    # Current gap: does the LATEST bar open away from the prior bar's close?
    # This is the one that actually matters for "should I enter right now."
    last_close_prev = float(rates[-2][4])
    last_open_cur = float(rates[-1][1])
    current_gap_pips = abs(last_open_cur - last_close_prev) / pip_size
    current_gap_detected = current_gap_pips >= gap_threshold_pips

    # Recent gap history, for context (how gap-prone has this window been).
    recent = rates[-lookback_bars:] if len(rates) >= lookback_bars else rates
    historical_gaps = []
    for i in range(1, len(recent)):
        prev_close = float(recent[i - 1][4])
        cur_open = float(recent[i][1])
        gap_pips = abs(cur_open - prev_close) / pip_size
        if gap_pips >= gap_threshold_pips:
            historical_gaps.append({
                "bar_index_from_start_of_window": i,
                "gap_pips": round(gap_pips, 2),
                "direction": "UP" if cur_open > prev_close else "DOWN",
            })

    return {
        "available": True,
        "current_gap_detected": current_gap_detected,
        "current_gap_pips": round(current_gap_pips, 2),
        "current_gap_direction": ("UP" if last_open_cur > last_close_prev else "DOWN") if current_gap_detected else None,
        "threshold_pips": gap_threshold_pips,
        "recent_gap_count": len(historical_gaps),
        "recent_gaps": historical_gaps,
        "note": (
            "current_gap_detected reflects the most recent bar only -- the "
            "one relevant to a trade decision made right now. recent_gaps "
            "is context (how gap-prone this window has been), not itself "
            "a reason to flag the current moment."
        ),
    }


# ------------------------------------------------------------
# 2. SLIPPAGE RISK ASSESSMENT
# ------------------------------------------------------------
# Slippage isn't directly observable from historical bars the way a gap
# is -- it's estimated from conditions known to correlate with it: an
# abnormally wide spread relative to what's allowed, extreme volatility,
# thin liquidity (low volume), and market-closed/near-close conditions
# (where the next fill may not happen until price has already moved).

def assess_slippage_risk(
    spread_pips: float,
    max_allowed_spread: float,
    atr_pips: float,
    extreme_volatility_threshold_pips: float,
    volume_ratio: float,
    is_market_open: bool,
    minutes_to_close: Optional[float] = None,
    near_close_minutes: float = 5.0,
) -> Dict[str, Any]:
    risk_factors: List[str] = []

    spread_ratio = (spread_pips / max_allowed_spread) if max_allowed_spread else 0
    if spread_ratio >= 0.7:
        risk_factors.append(
            f"Spread at {spread_pips:.1f} pips is {spread_ratio*100:.0f}% of the max allowed "
            f"({max_allowed_spread:.1f}) -- wide spreads are the most direct slippage signal."
        )

    if extreme_volatility_threshold_pips and atr_pips >= extreme_volatility_threshold_pips * 0.75:
        risk_factors.append(
            f"ATR at {atr_pips:.1f} pips is approaching the extreme-volatility threshold "
            f"({extreme_volatility_threshold_pips:.1f}) -- fast-moving markets fill worse than quoted."
        )

    if volume_ratio is not None and volume_ratio < 0.4:
        risk_factors.append(
            f"Volume ratio {volume_ratio:.2f}x is thin -- low liquidity means less depth at the "
            f"quoted price, increasing the chance of a worse fill."
        )

    if not is_market_open:
        risk_factors.append("Market is currently closed -- any pending order fills at the next open, not the current quote.")
    elif minutes_to_close is not None and 0 <= minutes_to_close <= near_close_minutes:
        risk_factors.append(
            f"Only {minutes_to_close:.0f} minutes to session close -- liquidity typically thins into "
            f"the close, and a fill may roll into the next session's open."
        )

    is_high_risk = len(risk_factors) >= 2  # two or more independent factors, not just one
    is_elevated_risk = len(risk_factors) == 1

    if is_high_risk:
        risk_level = "HIGH"
    elif is_elevated_risk:
        risk_level = "ELEVATED"
    else:
        risk_level = "NORMAL"

    return {
        "risk_level": risk_level,
        "is_high_risk": is_high_risk,
        "risk_factors": risk_factors,
        "spread_ratio_of_max": round(spread_ratio, 2),
    }


# ------------------------------------------------------------
# 3. TOP-LEVEL: combined advisory report
# ------------------------------------------------------------

def build_gap_slippage_report(
    rates: np.ndarray,
    pip_size: float,
    spread_pips: float,
    max_allowed_spread: float,
    atr_pips: float,
    extreme_volatility_threshold_pips: float,
    volume_ratio: float,
    is_market_open: bool,
    minutes_to_close: Optional[float] = None,
    gap_threshold_pips: float = 3.0,
) -> Dict[str, Any]:
    """
    ADVISORY ONLY. Returns detection results plus a recommended
    avoid_trade / should_exit reading -- neither of which is applied
    anywhere automatically. The caller decides whether/how to act on
    this; this function only reports.
    """
    gap = detect_price_gap(rates, pip_size, gap_threshold_pips=gap_threshold_pips)
    slippage = assess_slippage_risk(
        spread_pips=spread_pips,
        max_allowed_spread=max_allowed_spread,
        atr_pips=atr_pips,
        extreme_volatility_threshold_pips=extreme_volatility_threshold_pips,
        volume_ratio=volume_ratio,
        is_market_open=is_market_open,
        minutes_to_close=minutes_to_close,
    )

    gap_flag = gap.get("current_gap_detected", False)
    slippage_flag = slippage.get("is_high_risk", False)

    reasons = []
    if gap_flag:
        reasons.append(f"Current bar gapped {gap['current_gap_pips']} pips ({gap['current_gap_direction']}).")
    if slippage_flag:
        reasons.extend(slippage["risk_factors"])

    return {
        "gap": gap,
        "slippage": slippage,
        # Advisory recommendation only -- NOT wired into final_decision,
        # veto, or should_close_position. Surfaced for the caller/trader
        # to see and decide on, per explicit request that this stay
        # reporting-only rather than an automatic block.
        "recommendation": {
            "avoid_trade_recommended": gap_flag or slippage_flag,
            "should_exit_recommended": gap_flag or slippage_flag,
            "reasons": reasons,
        },
    }


# ------------------------------------------------------------
# 4. PROBABILITY-CHAIN CONTRIBUTION (✅ NEW)
# ------------------------------------------------------------
# ✅ NEW (per explicit request): the rest of this module stays exactly as
# documented above -- gap/slippage detection remains advisory, and
# avoid_trade_recommended / should_exit_recommended still do NOT touch
# final_decision or veto anywhere. This function is a deliberately
# separate, narrower thing: a bounded PROBABILITY PENALTY, wired into the
# same best_probability chain pattern/GNN/SMC/FVG-IFVG/order-flow already
# use.
#
# It's kept structurally different from those four on purpose. Pattern,
# GNN, SMC, FVG/IFVG, and order-flow are all DIRECTIONAL signals -- each
# one has an opinion about whether BUY or SELL is more likely correct.
# A gap or a thin book doesn't have a directional opinion; it tells you
# fill quality will be worse than the quoted price, symmetrically,
# whichever way you trade. So this only ever subtracts -- there's no
# "aligned"/"opposed" case here, and folding it into the directional
# chain functions the same way as the others would corrupt what
# alignment means for them. GAP_SLIPPAGE_WEIGHT bounds it the same way
# ORDER_FLOW_WEIGHT/SMC_WEIGHT/GNN_WEIGHT do for their own subsystems --
# a reasoned default, not a fitted coefficient (see this module's sibling
# files for the same "not backtested" caveat).
GAP_SLIPPAGE_WEIGHT = 0.10


def calculate_gap_slippage_final_score(
    gap_slippage_report: Dict[str, Any],
    base_probability: float,
) -> Dict[str, Any]:
    """
    Turns the existing advisory gap/slippage report into a bounded
    probability penalty. Deliberately does NOT set veto, does NOT touch
    final_decision, and does NOT replace avoid_trade_recommended /
    should_exit_recommended -- those stay advisory exactly as documented
    in build_gap_slippage_report(). This adds a second, narrower thing:
    a capped derate applied the same way the other post-entry
    adjustments in the chain are, so a gappy/thin-liquidity bar produces
    a lower probability_percent than an identical setup on a clean bar,
    instead of reporting an identical number either way.
    """
    gap = gap_slippage_report.get("gap", {}) or {}
    slippage = gap_slippage_report.get("slippage", {}) or {}

    penalty = 0.0
    reasons: List[str] = []

    if gap.get("current_gap_detected"):
        gap_pips = gap.get("current_gap_pips", 0) or 0
        gap_penalty = min(12.0, 6.0 + gap_pips * 0.5)
        penalty += gap_penalty
        reasons.append(f"Current bar gapped {gap_pips:.1f}p -- fill quality at entry is uncertain")

    risk_level = slippage.get("risk_level")
    if risk_level == "HIGH":
        penalty += 8.0
        reasons.append("Slippage risk HIGH (2+ independent risk factors present)")
    elif risk_level == "ELEVATED":
        penalty += 3.5
        reasons.append("Slippage risk ELEVATED (1 risk factor present)")

    max_penalty = GAP_SLIPPAGE_WEIGHT * 100
    penalty = min(penalty, max_penalty)

    final_score = max(5.0, base_probability - penalty)

    return {
        "gap_slippage_penalty": round(penalty, 2),
        "final_score": round(final_score, 2),
        "gap_slippage_weight_used": round(GAP_SLIPPAGE_WEIGHT * 100, 1),
        "reasons": reasons,
    }