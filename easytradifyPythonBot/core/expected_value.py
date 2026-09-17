# ============================================================
# EXPECTED VALUE SCORING
# ============================================================
# FILE: core/expected_value.py
#
# Turns EV = p_win * reward_pips - (1-p_win) * risk_pips - spread_pips
# into an actual scored, weighted VOICE in calculate_unified_indicator_
# score()'s consensus -- not a separate advisory block, not a hard gate.
# A 60%-confidence trade at 1:3 R:R can out-score a 78%-confidence trade
# at 1:1 now, the same way any other indicator's disagreement shows up:
# by pulling weighted_score in its direction, visible in `breakdown`,
# never by silently vetoing anything on its own.
# ============================================================

from typing import Dict, Any


def calculate_expected_value_pips(
    p_win_pct: float,
    reward_pips: float,
    risk_pips: float,
    spread_pips: float = 0.0,
) -> float:
    """
    EV in pips, net of spread. p_win_pct is 0-100 (matches best_probability's
    existing scale throughout this codebase, not 0-1).
    """
    p = max(0.0, min(1.0, p_win_pct / 100.0))
    return (p * reward_pips) - ((1 - p) * risk_pips) - spread_pips


def score_expected_value(
    p_win_pct: float,
    reward_pips: float,
    risk_pips: float,
    spread_pips: float,
    best_direction: str,
) -> Dict[str, Any]:
    """
    Same output contract as every other indicator scorer in this file
    (score/confidence/recommendation/reason) so it slots directly into
    calculate_unified_indicator_score()'s `indicators` dict and weighted
    vote, exactly like bollinger/macd/rsi/etc. already do.

    recommendation is only ever best_direction or NEUTRAL -- EV measures
    whether THIS trade's risk/reward is favorable, not evidence for the
    opposite direction, so a bad EV never casts a vote for the other side.
    It still pulls the numeric score negative, which is what actually
    drags weighted_score down -- the vote-counting and the score-summing
    are separate mechanisms in calculate_unified_indicator_score, and
    this uses both honestly: negative score, but no directional flip-vote.
    """
    if risk_pips is None or risk_pips <= 0:
        return {
            "recommendation": "NEUTRAL", "score": 0, "confidence": 0,
            "reason": "No valid risk (stop-loss) distance to compute EV from",
        }

    ev_pips = calculate_expected_value_pips(p_win_pct, reward_pips, risk_pips, spread_pips)
    r_multiple = ev_pips / risk_pips  # EV expressed in units of risk taken

    if r_multiple >= 0.5:
        score, confidence = 15, 80
        reason = f"Strong positive EV: {ev_pips:+.1f} pips ({r_multiple:+.2f}R) at {p_win_pct:.0f}% win prob"
        rec = best_direction
    elif r_multiple >= 0.15:
        score, confidence = 8, 65
        reason = f"Positive EV: {ev_pips:+.1f} pips ({r_multiple:+.2f}R) at {p_win_pct:.0f}% win prob"
        rec = best_direction
    elif r_multiple > 0:
        score, confidence = 3, 50
        reason = f"Marginally positive EV: {ev_pips:+.1f} pips ({r_multiple:+.2f}R) -- thin edge"
        rec = best_direction
    elif r_multiple > -0.15:
        score, confidence = -5, 50
        reason = f"Marginally negative EV: {ev_pips:+.1f} pips ({r_multiple:+.2f}R) -- thin against"
        rec = "NEUTRAL"
    else:
        score, confidence = -15, 75
        reason = f"Negative EV: {ev_pips:+.1f} pips ({r_multiple:+.2f}R) at {p_win_pct:.0f}% win prob -- risk/reward doesn't justify entry even though probability alone passed the threshold"
        rec = "NEUTRAL"

    return {
        "recommendation": rec,
        "score": score,
        "confidence": confidence,
        "reason": reason,
        "ev_pips": round(ev_pips, 2),
        "r_multiple": round(r_multiple, 3),
    }