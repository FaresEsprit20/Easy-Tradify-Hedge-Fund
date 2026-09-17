# ============================================================
# CANONICAL RISK:REWARD
# ============================================================
# FILE: core/risk_reward.py
#
# Phase 2 (Canonical Consistency). Before this module, R:R was computed
# at eight independent sites with three different failure behaviours:
#
#   asset_analysis.py:3087   tp1_pips / calculated_sl_pips ... else 2.0
#   asset_analysis.py:4499   tp1_pips / calculated_sl_pips   (unguarded)
#   asset_analysis_smc.py    six per-setup computations, five of them
#                            signed and direction-aware, one using abs()
#
# The `else 2.0` fallback was the serious one. MIN_ABSOLUTE_RISK_REWARD
# is 2.0 and the floor tests `< 2.0`, so a zero, missing or invalid
# stop-loss distance produced exactly 2.0 and PASSED the floor. The one
# number in the pipeline that is supposed to be a measured fact rather
# than a model estimate had a failure mode of "assume the requirement is
# met". That is the invariant "missing, invalid or stale data cannot
# silently become positive evidence" failing on the safety gate itself.
#
# Design rules for everything in this file:
#   1. FAIL CLOSED. An R:R that cannot be computed is not 2.0, not 0.0,
#      and not None-that-someone-will-compare-with-<. It is a result
#      object whose `valid` is False, and `passes_floor()` returns False
#      for it regardless of the floor.
#   2. DIRECTION-AWARE. Reward and risk are signed distances checked
#      against the trade direction. abs() is never used, because abs()
#      turns "target is on the wrong side of entry" into a healthy
#      number.
#   3. NO SILENT DEFAULTS. Every rejection carries a reason string that
#      names the specific input that failed.
#
# This module has no dependencies beyond the stdlib and does not import
# from core.* -- it sits at Tier 0 alongside swing_points.py.
# ============================================================

from typing import Dict, Any, Optional


# Sentinel used in reporting where a float is structurally required but
# no valid ratio exists. Deliberately 0.0 rather than 2.0: if some future
# call site forgets to check `.valid` and compares this against a floor,
# 0.0 fails the floor and the trade is rejected. The old 2.0 default
# passed it.
INVALID_RR_VALUE = 0.0


class RiskReward:
    """
    Result of one R:R computation.

    Callers MUST consult `.valid` (or use `.passes_floor()`, which folds
    the validity check in) before trusting `.ratio`. `.ratio` is
    INVALID_RR_VALUE when `.valid` is False.
    """

    __slots__ = ("ratio", "risk_pips", "reward_pips", "valid", "reason", "direction")

    def __init__(self, ratio: float, risk_pips: Optional[float], reward_pips: Optional[float],
                 valid: bool, reason: str, direction: Optional[str] = None):
        self.ratio = ratio
        self.risk_pips = risk_pips
        self.reward_pips = reward_pips
        self.valid = valid
        self.reason = reason
        self.direction = direction

    def passes_floor(self, minimum: float) -> bool:
        """
        The only correct way to test an R:R against a floor.

        An invalid R:R never passes, whatever the floor is. This is the
        single line that closes the `else 2.0` hole -- there is no value
        of `minimum` for which an uncomputable R:R is acceptable.
        """
        if not self.valid:
            return False
        # A target placed exactly on the floor (calculate_hybrid_take_profit,
        # TP1_FOLLOWS_RR_FLOOR) must pass it: (1.2 x stop + spread - spread) /
        # stop comes back as 1.1999999999999997 for about 6% of stop/spread
        # pairs, and a strict >= refused those trades by rounding alone.
        return self.ratio >= minimum - 1e-9

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ratio": round(self.ratio, 2),
            "risk_pips": round(self.risk_pips, 2) if self.risk_pips is not None else None,
            "reward_pips": round(self.reward_pips, 2) if self.reward_pips is not None else None,
            "valid": self.valid,
            "reason": self.reason,
            "direction": self.direction,
        }

    def display(self) -> str:
        """Reporting string. Never renders an invalid ratio as a number."""
        if not self.valid:
            return "1:N/A"
        return f"1:{round(self.ratio, 1)}"

    def __repr__(self) -> str:
        return f"<RiskReward {self.display()} valid={self.valid} reason={self.reason!r}>"


def _invalid(reason: str, direction: Optional[str] = None,
             risk_pips: Optional[float] = None,
             reward_pips: Optional[float] = None) -> RiskReward:
    return RiskReward(INVALID_RR_VALUE, risk_pips, reward_pips, False, reason, direction)


def _finite(x) -> bool:
    """True only for real, finite numbers. Rejects None, NaN, inf, non-numerics."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    # NaN != NaN; inf fails the bound check.
    return f == f and float("-inf") < f < float("inf")


def rr_from_pips(reward_pips, risk_pips, direction: Optional[str] = None) -> RiskReward:
    """
    R:R from pre-computed pip distances.

    Both distances must already be POSITIVE magnitudes measured in the
    correct direction by the caller. If the caller has raw prices, use
    rr_from_prices() instead -- it does the directional check for you.
    """
    if not _finite(risk_pips):
        return _invalid("Stop-loss distance is missing or not a finite number", direction)
    if not _finite(reward_pips):
        return _invalid("Take-profit distance is missing or not a finite number", direction,
                        risk_pips=float(risk_pips) if _finite(risk_pips) else None)

    risk = float(risk_pips)
    reward = float(reward_pips)

    if risk <= 0:
        # This is the case the old `else 2.0` swallowed.
        return _invalid(
            f"Stop-loss distance is {risk:.2f} pips -- R:R is undefined without a real risk distance",
            direction, risk_pips=risk, reward_pips=reward,
        )
    if reward <= 0:
        return _invalid(
            f"Take-profit distance is {reward:.2f} pips -- target is at or behind entry",
            direction, risk_pips=risk, reward_pips=reward,
        )

    return RiskReward(reward / risk, risk, reward, True, "computed from pip distances", direction)


def rr_from_prices(direction: str, entry_price, stop_loss, take_profit, pip_size) -> RiskReward:
    """
    R:R from raw prices, with the directional geometry enforced.

    This is the function that fixes the abs() defect. For a BUY the stop
    must sit BELOW entry and the target ABOVE it; for a SELL the mirror.
    A target on the wrong side of entry is rejected by name rather than
    being turned into a positive distance by abs().
    """
    # Coerced defensively rather than assumed to be a string: this
    # function must fail CLOSED on any malformed input, and an
    # AttributeError propagating out of an R:R check would be caught by
    # some caller's broad `except Exception` and turned into a
    # neutral/default result -- exactly the class of silent failure this
    # module exists to remove.
    d = direction.strip().upper() if isinstance(direction, str) else ""
    if d not in ("BUY", "SELL"):
        return _invalid(f"Direction {direction!r} is not BUY or SELL -- cannot orient R:R geometry", direction)

    for name, value in (("entry price", entry_price), ("stop loss", stop_loss),
                        ("take profit", take_profit), ("pip size", pip_size)):
        if not _finite(value):
            return _invalid(f"{name.capitalize()} is missing or not a finite number", d)

    entry = float(entry_price)
    sl = float(stop_loss)
    tp = float(take_profit)
    ps = float(pip_size)

    if ps <= 0:
        return _invalid(f"Pip size is {ps} -- cannot convert prices to pips", d)

    if d == "BUY":
        risk_price = entry - sl      # positive when the stop is below entry
        reward_price = tp - entry    # positive when the target is above entry
        if risk_price <= 0:
            return _invalid(
                f"BUY stop-loss {sl} is at or above entry {entry} -- stop is on the wrong side", d)
        if reward_price <= 0:
            return _invalid(
                f"BUY take-profit {tp} is at or below entry {entry} -- target is on the wrong side", d)
    else:
        risk_price = sl - entry      # positive when the stop is above entry
        reward_price = entry - tp    # positive when the target is below entry
        if risk_price <= 0:
            return _invalid(
                f"SELL stop-loss {sl} is at or below entry {entry} -- stop is on the wrong side", d)
        if reward_price <= 0:
            return _invalid(
                f"SELL take-profit {tp} is at or above entry {entry} -- target is on the wrong side", d)

    return rr_from_pips(reward_price / ps, risk_price / ps, d)