# ============================================================
# AI_MarketReplay -- PHASE 3, item 7
# Counterfactual branching
# ============================================================
#
# Implements readme section 19 (and section 35.3, Level 2 of the simulator
# hierarchy): alternative branches from a common historical state, evaluated
# against the market path that actually occurred.
#
# WHY THIS IS THE SAFE KIND OF SIMULATION
# ---------------------------------------
# Nothing here invents a price. Every branch is scored against the real
# subsequent path, so a counterfactual answers "what would this policy have
# produced on the tape that actually happened" -- not "what might the market
# have done". That is why Level 2 carries no contamination risk while
# generated scenarios (Levels 3-4) do.
#
# THE DISTINCTION THAT MAKES OR BREAKS THIS
# -----------------------------------------
# Some branches are implementable and some are oracles.
#
#   IMPLEMENTABLE   the rule could have been evaluated at the branch point
#                   using only what was knowable then -- "exit if the position
#                   goes 0.5R against you" is a policy.
#
#   ORACLE          the rule needs the future -- "exit at the highest point
#                   the trade ever reached" is not a policy, it is hindsight
#                   wearing a policy's clothes.
#
# Both are useful: the oracle bounds how much was available to capture. But
# mixing them is the classic backtest self-deception, because an oracle branch
# always wins and always looks like an improvement you could have had. So
# `implementable` is a required field, comparison separates the two, and the
# headline result only ever ranks implementable branches.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

COUNTERFACTUAL_VERSION = "1.0"


@dataclass
class Branch:
    """One alternative decision, scored on the historical path."""

    name: str
    action: str
    implementable: bool
    realized_r: Optional[float] = None
    exit_index: Optional[int] = None
    exit_reason: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradePath:
    """The historical facts a branch is evaluated against."""

    prices: Tuple[float, ...]
    entry_price: float
    stop_loss: float
    take_profit: Optional[float]
    sign: int
    risk: float
    close_price: Optional[float] = None

    @property
    def usable(self) -> bool:
        return bool(self.prices) and self.risk > 0 and math.isfinite(self.risk)


def build_path(canonical_trade: Any) -> Optional[TradePath]:
    """Extract the historical path. Returns None when it cannot be trusted."""
    execution = getattr(canonical_trade, "execution", {}) or {}
    entry_price, stop_loss = execution.get("entry_price"), execution.get("stop_loss")
    if not entry_price or not stop_loss:
        return None

    risk = abs(float(entry_price) - float(stop_loss))
    if not risk or not math.isfinite(risk):
        return None

    prices = tuple(
        float(point["price"])
        for point in (getattr(canonical_trade, "price_evolution", []) or [])
        if isinstance(point, Mapping) and point.get("price") is not None
    )
    if not prices:
        return None

    direction = str(getattr(canonical_trade, "direction", "BUY") or "BUY").upper()
    outcome = getattr(canonical_trade, "outcome", {}) or {}
    close_price = float(outcome["exit_price"]) if outcome.get("exit_price") else None

    # The exit belongs on the path. Otherwise branch_exit_policy's oracle scans
    # observations only and can report a peak BELOW the actual close -- which
    # made the "upper bound" smaller than the thing it bounds.
    if close_price is not None and (not prices or prices[-1] != close_price):
        prices = prices + (close_price,)

    return TradePath(
        prices=prices,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        take_profit=float(execution["take_profit"]) if execution.get(
            "take_profit") else None,
        sign=-1 if direction in ("SELL", "SHORT") else 1,
        risk=risk,
        close_price=close_price,
    )


def _entry_for_delay(path: TradePath, delay: int) -> Tuple[Optional[float], int]:
    """
    Fill price and first observation index for a given delay.

    price_evolution[0] is the first observation AFTER entry, not the fill, so
    delay 0 must use the recorded entry_price. Using prices[0] instead scored
    the actual trade from the wrong basis entirely -- it turned a +2R target
    into +6.5R, and made the actual return exceed its own oracle bound.
    """
    if delay <= 0:
        return path.entry_price, 0
    if delay > len(path.prices):
        return None, delay
    # Waiting `delay` observations means filling at the last one observed.
    return path.prices[delay - 1], delay


def _simulate(
    path: TradePath,
    entry_index: int,
    stop_loss: float,
    take_profit: Optional[float],
    exit_at: Optional[int] = None,
    entry_price: Optional[float] = None,
) -> Tuple[Optional[float], Optional[int], str]:
    """
    Walk the real path forward from `entry_index` under one policy.

    Return is expressed in R against THAT branch's own risk, not the original
    trade's -- a wider stop takes a smaller position for the same money, so
    scoring it in the original R units would flatter it for free.

    A bar that could have touched both stop and target is resolved as the stop
    first. Without tick data the order is unknowable, and the pessimistic
    reading is the only honest one: the optimistic reading is how backtests
    manufacture edges that evaporate live.
    """
    if entry_index > len(path.prices):
        return None, None, "never_entered"

    entry = path.entry_price if entry_price is None else entry_price
    if entry is None:
        return None, None, "never_entered"

    risk = abs(entry - stop_loss)
    if not risk or not math.isfinite(risk):
        return None, None, "no_risk"

    for index in range(entry_index, len(path.prices)):
        price = path.prices[index]
        moved = path.sign * (price - entry)

        stop_distance = path.sign * (stop_loss - entry)
        if (path.sign > 0 and price <= stop_loss) or \
                (path.sign < 0 and price >= stop_loss):
            return round(stop_distance / risk, 4), index, "stop"

        if take_profit is not None:
            if (path.sign > 0 and price >= take_profit) or \
                    (path.sign < 0 and price <= take_profit):
                return round((path.sign * (take_profit - entry)) / risk, 4), \
                    index, "target"

        if exit_at is not None and index >= exit_at:
            return round(moved / risk, 4), index, "policy_exit"

    final = path.close_price if path.close_price is not None else path.prices[-1]
    return round((path.sign * (final - entry)) / risk, 4), \
        len(path.prices) - 1, "close"


# ---------------------------------------------------------------------------
# Branch families (readme 19)
# ---------------------------------------------------------------------------

def branch_entry_timing(path: TradePath, max_delay: int = 3) -> List[Branch]:
    """
    Enter now, or after N bars, or not at all (readme 35.4 action space).

    Implementable: waiting a fixed number of bars needs no knowledge of what
    those bars contain.
    """
    branches = [Branch(
        name="actual", action="ENTER_NOW", implementable=True,
        params={"delay_bars": 0},
    )]
    realized, exit_index, reason = _simulate(
        path, 0, path.stop_loss, path.take_profit,
        entry_price=path.entry_price)
    branches[0].realized_r, branches[0].exit_index, branches[0].exit_reason = (
        realized, exit_index, reason)

    for delay in range(1, max_delay + 1):
        fill, start = _entry_for_delay(path, delay)
        if fill is None or start >= len(path.prices):
            break
        realized, exit_index, reason = _simulate(
            path, start, path.stop_loss, path.take_profit, entry_price=fill)
        branches.append(Branch(
            name=f"enter_after_{delay}",
            action="ENTER_AFTER_N_BARS", implementable=True,
            realized_r=realized, exit_index=exit_index, exit_reason=reason,
            params={"delay_bars": delay, "fill_price": round(fill, 6)},
        ))

    branches.append(Branch(
        name="cancel", action="CANCEL", implementable=True,
        realized_r=0.0, exit_index=None, exit_reason="cancelled",
        params={},
        note="not trading is always available and always costs nothing",
    ))
    return branches


def branch_stop_policy(
    path: TradePath,
    multipliers: Sequence[float] = (0.5, 1.5, 2.0),
) -> List[Branch]:
    """
    The same entry with a wider or tighter stop.

    Scored in each branch's own R, so a wider stop is not credited for the
    larger absolute move it survives -- it is risking the same money over a
    longer distance, which means a smaller position.
    """
    branches = []
    for multiplier in multipliers:
        stop = path.entry_price - path.sign * path.risk * multiplier
        realized, exit_index, reason = _simulate(
            path, 0, stop, path.take_profit, entry_price=path.entry_price)
        branches.append(Branch(
            name=f"stop_x{multiplier}",
            action="ALTERNATIVE_STOP", implementable=True,
            realized_r=realized, exit_index=exit_index, exit_reason=reason,
            params={"stop_multiplier": multiplier, "stop_loss": round(stop, 6)},
        ))
    return branches


def branch_exit_policy(path: TradePath, adverse_r: float = 0.5) -> List[Branch]:
    """
    Leave when the position goes `adverse_r` against you, versus leaving at
    the best point the trade ever reached.

    The first is a policy. The second is an ORACLE and marked as such: it
    requires knowing the peak in advance, so it measures how much was
    available to capture rather than what could have been captured.
    """
    branches: List[Branch] = []

    trigger_index = None
    for index in range(len(path.prices)):
        moved = path.sign * (path.prices[index] - path.entry_price) / path.risk
        if moved <= -adverse_r:
            trigger_index = index
            break

    realized, exit_index, reason = _simulate(
        path, 0, path.stop_loss, path.take_profit, exit_at=trigger_index,
        entry_price=path.entry_price)
    branches.append(Branch(
        name=f"exit_on_{adverse_r}R_adverse",
        action="EXIT_ON_ADVERSE", implementable=True,
        realized_r=realized, exit_index=exit_index, exit_reason=reason,
        params={"adverse_r": adverse_r},
    ))

    best_index, best_r = None, None
    for index in range(len(path.prices)):
        moved = path.sign * (path.prices[index] - path.entry_price) / path.risk
        if best_r is None or moved > best_r:
            best_index, best_r = index, moved
    branches.append(Branch(
        name="exit_at_peak", action="ORACLE_EXIT", implementable=False,
        realized_r=round(best_r, 4) if best_r is not None else None,
        exit_index=best_index, exit_reason="oracle_peak",
        params={},
        note=("requires knowing the peak in advance; an upper bound on what "
              "was available, not an achievable policy"),
    ))
    return branches


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_branches(branches: Sequence[Branch]) -> Dict[str, Any]:
    """
    Rank branches, keeping oracles strictly out of the headline.

    An oracle branch always wins, so ranking the two together would report a
    guaranteed "improvement" on every trade ever examined -- which is how a
    backtest talks itself into an edge that cannot be traded.
    """
    scored = [b for b in branches if b.realized_r is not None]
    implementable = [b for b in scored if b.implementable]
    oracles = [b for b in scored if not b.implementable]

    actual = next((b for b in scored if b.name == "actual"), None)
    best = max(implementable, key=lambda b: b.realized_r) if implementable else None
    oracle_best = max(oracles, key=lambda b: b.realized_r) if oracles else None

    improvement = (
        round(best.realized_r - actual.realized_r, 4)
        if best and actual else None)

    return {
        "actual_r": actual.realized_r if actual else None,
        "best_implementable": best.to_dict() if best else None,
        "improvement_r": improvement,
        "better_alternative_existed": bool(improvement and improvement > 0),
        "ranked": [b.to_dict() for b in
                   sorted(implementable, key=lambda b: -b.realized_r)],
        "oracle_bound_r": oracle_best.realized_r if oracle_best else None,
        "capture_ratio": (
            round(actual.realized_r / oracle_best.realized_r, 4)
            if actual and oracle_best and oracle_best.realized_r
            and oracle_best.realized_r > 0 else None),
        "oracles_excluded_from_ranking": [b.name for b in oracles],
    }


def branch_trade(
    canonical_trade: Any,
    max_delay: int = 3,
    stop_multipliers: Sequence[float] = (0.5, 1.5, 2.0),
    adverse_r: float = 0.5,
) -> Dict[str, Any]:
    """All branch families for one trade, plus the comparison (readme 19)."""
    path = build_path(canonical_trade)
    if path is None or not path.usable:
        return {
            "trade_id": getattr(canonical_trade, "trade_id", None),
            "branches": [],
            "comparison": None,
            "skipped": "no reconstructable price path",
        }

    branches = (
        branch_entry_timing(path, max_delay)
        + branch_stop_policy(path, stop_multipliers)
        + branch_exit_policy(path, adverse_r)
    )
    return {
        "version": COUNTERFACTUAL_VERSION,
        "trade_id": getattr(canonical_trade, "trade_id", None),
        "branches": [b.to_dict() for b in branches],
        "comparison": compare_branches(branches),
        "uses_only_historical_prices": True,
    }


def aggregate_branches(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Which alternative policy would have helped across many trades.

    Averaged per branch NAME rather than per trade, because the question is
    whether a policy generalises. A branch that rescues one trade and ruins
    four is a worse policy than the actual one, and only the aggregate shows
    that.
    """
    totals: Dict[str, List[float]] = {}
    actual: List[float] = []

    for result in results or []:
        comparison = result.get("comparison") or {}
        if comparison.get("actual_r") is not None:
            actual.append(comparison["actual_r"])
        for branch in result.get("branches") or []:
            if branch.get("realized_r") is None or not branch.get("implementable"):
                continue
            totals.setdefault(branch["name"], []).append(branch["realized_r"])

    baseline = sum(actual) / len(actual) if actual else None
    policies = []
    for name, values in totals.items():
        mean = sum(values) / len(values)
        policies.append({
            "policy": name,
            "trades": len(values),
            "mean_r": round(mean, 4),
            "delta_vs_actual_r": (
                round(mean - baseline, 4) if baseline is not None else None),
        })
    policies.sort(key=lambda p: -(p["delta_vs_actual_r"] or 0))

    return {
        "trades": len(actual),
        "actual_mean_r": round(baseline, 4) if baseline is not None else None,
        "policies": policies,
        "best_policy": policies[0] if policies else None,
        "caveat": (
            "measured on the historical path only; a policy that helps here "
            "has not been shown to generalise out of sample"),
    }


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.counterfactual",
        "version": COUNTERFACTUAL_VERSION,
        "phase": "3 - Replay (item 7)",
        "invents_prices": False,
        "branch_families": [
            "entry_timing", "cancel", "stop_policy", "exit_policy"],
        "separates_oracle_from_implementable": True,
        "why": (
            "an oracle branch always wins, so ranking it alongside "
            "implementable policies would report a guaranteed improvement on "
            "every trade -- hindsight wearing a policy's clothes"),
        "ambiguous_bar_policy": "stop_first",
        "why_stop_first": (
            "without tick data the order of a stop and target touch in one bar "
            "is unknowable; the pessimistic reading is the only honest one"),
        "ambiguity_currently_reachable": False,
        "ambiguity_note": (
            "price_evolution stores scalar observations, not OHLC bars, and a "
            "single price cannot be beyond both the stop and the target at "
            "once -- so the stop-first ordering is currently unexercised. It "
            "is in place for when bar highs and lows are replayed, where the "
            "ambiguity is real and the optimistic reading is how backtests "
            "manufacture edges that evaporate live"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "component": "aireplay.counterfactual", "ok": False, "checks": {}}
    try:
        from .data_engine import extract_replay_records

        records = extract_replay_records(trades or [])
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["records"] = len(records)

        if records:
            results = [branch_trade(r) for r in records]
            branched = [r for r in results if r.get("branches")]
            report["checks"]["trades_branched"] = len(branched)

            if branched:
                first = branched[0]
                report["checks"]["branch_count"] = len(first["branches"])
                report["checks"]["oracles_excluded"] = first["comparison"][
                    "oracles_excluded_from_ranking"]
                report["checks"]["ranking_is_implementable_only"] = all(
                    b["implementable"] for b in first["comparison"]["ranked"])
                report["checks"]["aggregate"] = aggregate_branches(results)[
                    "best_policy"]
                report["ok"] = bool(
                    report["checks"]["ranking_is_implementable_only"]
                    and report["checks"]["branch_count"] > 0)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "COUNTERFACTUAL_VERSION", "Branch", "TradePath", "build_path",
    "branch_entry_timing", "branch_stop_policy", "branch_exit_policy",
    "compare_branches", "branch_trade", "aggregate_branches",
    "get_status", "self_check",
]
