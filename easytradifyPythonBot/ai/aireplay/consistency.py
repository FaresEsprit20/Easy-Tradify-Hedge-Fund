# ============================================================
# AI_MarketReplay -- PHASE 3, item 14
# Simulator / replay consistency
# ============================================================
#
# WHY THIS EXISTS
# ---------------
# Three separate pieces of code now walk a historical path forward from an
# entry, detect stop and target hits, and compute a return:
#
#   replay_engine.reconstruct_reality        (this package, in R)
#   counterfactual._simulate                 (this package, in R)
#   ai_reinforcement.CounterfactualSimulator (predates both, in percent)
#
# The third predates the other two. Building the second and third without
# reconciling them against it was a straightforward violation of the reuse
# rule -- and this codebase has been bitten by that exact pattern repeatedly:
# two swing detectors, two lot-sizers, two liquidity-sweep detectors, each
# pair silently disagreeing until someone measured them.
#
# Consolidating them is a larger change than it looks: they have different
# input types (CanonicalTrade vs RL snapshot sequences), different units
# (R vs percent) and different consumers. So the immediate remedy is to stop
# the disagreement being SILENT. This module runs all three on the same trade
# and reports where they differ.
#
# A disagreement here is a finding, not a test failure to be tuned away. If
# two simulators disagree about whether a trade hit its stop, at least one of
# them is wrong about history, and every conclusion drawn from it is suspect.
#
# WHAT AGREEMENT MEANS
# --------------------
# Not bitwise equality. The implementations legitimately differ in units and
# in how they treat the final bar, so the invariants checked are the ones that
# must hold regardless: the same exit reason, the same sign of outcome, and
# magnitudes that agree once converted to common units.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

CONSISTENCY_VERSION = "1.0"

# Magnitudes are compared after unit conversion, so an exact match is not
# expected: the implementations differ on whether the close price or the last
# observation ends the trade. This is wide enough to absorb that and narrow
# enough that a genuine divergence still fails.
MAGNITUDE_TOLERANCE_R = 0.25


@dataclass
class SimulatorResult:
    """One implementation's reading of the same historical trade."""

    simulator: str
    available: bool
    final_return_r: Optional[float] = None
    exit_reason: Optional[str] = None
    sl_hit: Optional[bool] = None
    tp_hit: Optional[bool] = None
    mfe_r: Optional[float] = None
    mae_r: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _reality_result(canonical_trade: Any) -> SimulatorResult:
    """replay_engine.reconstruct_reality -- the observed path, in R."""
    try:
        from .replay_engine import reconstruct_reality

        reality = reconstruct_reality(canonical_trade)
        if not reality:
            return SimulatorResult("replay_engine.reality", False,
                                   error="no reconstructable path")
        final = reality[-1]
        return SimulatorResult(
            simulator="replay_engine.reality", available=True,
            final_return_r=final.return_r,
            mfe_r=final.mfe_r, mae_r=final.mae_r,
            # Reality reconstruction reports what happened, not why it ended,
            # so hit flags are inferred from the excursions rather than
            # claimed. Inferring beyond that would invent detail.
            sl_hit=final.mae_r <= -1.0,
            tp_hit=final.mfe_r >= 2.0,
        )
    except Exception as exc:
        return SimulatorResult("replay_engine.reality", False,
                               error=f"{type(exc).__name__}: {exc}")


def _counterfactual_result(canonical_trade: Any) -> SimulatorResult:
    """counterfactual branch 'actual' -- the same trade as actually taken."""
    try:
        from .counterfactual import branch_trade

        result = branch_trade(canonical_trade)
        actual = next((b for b in result.get("branches") or []
                       if b["name"] == "actual"), None)
        if actual is None or actual.get("realized_r") is None:
            return SimulatorResult("counterfactual.actual", False,
                                   error=result.get("skipped") or "no actual branch")
        reason = actual["exit_reason"]
        return SimulatorResult(
            simulator="counterfactual.actual", available=True,
            final_return_r=actual["realized_r"],
            exit_reason=reason,
            sl_hit=reason == "stop",
            tp_hit=reason == "target",
        )
    except Exception as exc:
        return SimulatorResult("counterfactual.actual", False,
                               error=f"{type(exc).__name__}: {exc}")


def _rl_result(canonical_trade: Any) -> SimulatorResult:
    """
    ai_reinforcement.CounterfactualSimulator -- the pre-existing implementation.

    Its snapshots and percent units differ from this package's, so its output
    is converted to R here rather than compared raw. Torch may be absent, in
    which case it is reported unavailable rather than silently skipped.
    """
    try:
        from ..ai_reinforcement import CounterfactualSimulator, RLConfig

        execution = getattr(canonical_trade, "execution", {}) or {}
        entry_price, stop_loss = execution.get("entry_price"), execution.get("stop_loss")
        if not entry_price or not stop_loss:
            return SimulatorResult("ai_reinforcement.counterfactual", False,
                                   error="no entry/stop")

        risk = abs(float(entry_price) - float(stop_loss))
        if not risk:
            return SimulatorResult("ai_reinforcement.counterfactual", False,
                                   error="zero risk")

        direction = str(getattr(canonical_trade, "direction", "BUY") or "BUY").upper()
        sign = -1 if direction in ("SELL", "SHORT") else 1
        take_profit = execution.get("take_profit")

        # The entry snapshot MUST carry stop_loss and take_profit: RL's
        # simulator reads them via extract_sl_tp(), and without them it never
        # sees a target, exits at "horizon_end", and reports tp_hit False on a
        # trade that plainly hit its target. That produced a disagreement this
        # module reported as drift when it was purely an adapter fault -- and
        # a consistency check that cries wolf trains you to ignore it.
        entry_snapshot = {
            "price": float(entry_price),
            "direction": sign,
            "stop_loss": float(stop_loss),
        }
        if take_profit:
            entry_snapshot["take_profit"] = float(take_profit)

        snapshots = [entry_snapshot]
        for point in getattr(canonical_trade, "price_evolution", []) or []:
            if isinstance(point, Mapping) and point.get("price") is not None:
                snapshots.append({
                    "price": float(point["price"]),
                    "direction": sign,
                    "stop_loss": float(stop_loss),
                    **({"take_profit": float(take_profit)} if take_profit else {}),
                })
        # Walk to the actual exit, matching the other two simulators. Ending
        # at the last observation instead put this adapter into permanent
        # disagreement with them on every trade that closed away from its
        # final sample.
        exit_price = (getattr(canonical_trade, "outcome", {}) or {}).get("exit_price")
        if exit_price is not None and (
                len(snapshots) < 2 or snapshots[-1]["price"] != float(exit_price)):
            snapshots.append({
                "price": float(exit_price),
                "direction": sign,
                "stop_loss": float(stop_loss),
                **({"take_profit": float(take_profit)} if take_profit else {}),
            })

        if len(snapshots) < 2:
            return SimulatorResult("ai_reinforcement.counterfactual", False,
                                   error="insufficient snapshots")

        outcome = CounterfactualSimulator(RLConfig()).simulate(snapshots, 0)

        # percent-of-entry -> R
        def to_r(percent: Optional[float]) -> Optional[float]:
            if percent is None or not math.isfinite(percent):
                return None
            return round((percent / 100.0) * float(entry_price) / risk, 4)

        return SimulatorResult(
            simulator="ai_reinforcement.counterfactual", available=True,
            final_return_r=to_r(outcome.return_pct),
            mfe_r=to_r(outcome.mfe_pct), mae_r=to_r(-abs(outcome.mae_pct))
            if outcome.mae_pct is not None else None,
            exit_reason=outcome.reason,
            sl_hit=bool(outcome.sl_hit), tp_hit=bool(outcome.tp_hit),
        )
    except ImportError as exc:
        return SimulatorResult("ai_reinforcement.counterfactual", False,
                               error=f"unavailable: {exc}")
    except Exception as exc:
        return SimulatorResult("ai_reinforcement.counterfactual", False,
                               error=f"{type(exc).__name__}: {exc}")


def compare_simulators(canonical_trade: Any) -> Dict[str, Any]:
    """
    Run every simulator on one trade and report where they disagree.

    Disagreements are returned, not raised. The caller decides what to do
    about them, and a batch run must not stop at the first one.
    """
    results = [
        _reality_result(canonical_trade),
        _counterfactual_result(canonical_trade),
        _rl_result(canonical_trade),
    ]
    usable = [r for r in results if r.available and r.final_return_r is not None]

    disagreements: List[Dict[str, Any]] = []

    if len(usable) >= 2:
        returns = [r.final_return_r for r in usable]
        spread = max(returns) - min(returns)
        if spread > MAGNITUDE_TOLERANCE_R:
            disagreements.append({
                "field": "final_return_r",
                "spread": round(spread, 4),
                "tolerance": MAGNITUDE_TOLERANCE_R,
                "values": {r.simulator: r.final_return_r for r in usable},
                "severity": "HIGH",
            })

        signs = {(r.final_return_r > 0) for r in usable}
        if len(signs) > 1:
            disagreements.append({
                "field": "outcome_sign",
                "detail": "simulators disagree on whether the trade made money",
                "values": {r.simulator: r.final_return_r for r in usable},
                "severity": "HIGH",
            })

        for flag in ("sl_hit", "tp_hit"):
            claimed = {r.simulator: getattr(r, flag) for r in usable
                       if getattr(r, flag) is not None}
            if len(set(claimed.values())) > 1:
                disagreements.append({
                    "field": flag,
                    "detail": f"simulators disagree on {flag}",
                    "values": claimed,
                    "severity": "MEDIUM",
                })

    return {
        "trade_id": getattr(canonical_trade, "trade_id", None),
        "simulators": [r.to_dict() for r in results],
        "available_count": len(usable),
        "comparable": len(usable) >= 2,
        "consistent": not disagreements,
        "disagreements": disagreements,
    }


def consistency_report(canonical_trades: Sequence[Any]) -> Dict[str, Any]:
    """
    Consistency across many trades.

    Reports the RATE of disagreement rather than only a boolean: one
    disagreeing trade is a bug to chase, and a third of them disagreeing means
    the implementations have genuinely drifted apart.
    """
    comparisons = []
    for trade in canonical_trades or []:
        try:
            comparisons.append(compare_simulators(trade))
        except Exception:
            continue

    comparable = [c for c in comparisons if c["comparable"]]
    inconsistent = [c for c in comparable if not c["consistent"]]

    by_field: Dict[str, int] = {}
    for comparison in inconsistent:
        for disagreement in comparison["disagreements"]:
            by_field[disagreement["field"]] = by_field.get(
                disagreement["field"], 0) + 1

    return {
        "version": CONSISTENCY_VERSION,
        "trades": len(comparisons),
        "comparable": len(comparable),
        "consistent": len(comparable) - len(inconsistent),
        "inconsistent": len(inconsistent),
        "disagreement_rate": (
            round(len(inconsistent) / len(comparable), 4) if comparable else None),
        "disagreements_by_field": by_field,
        "examples": [c for c in inconsistent[:3]],
        "verdict": (
            "CONSISTENT" if comparable and not inconsistent
            else "DRIFTED" if inconsistent
            else "NOT_COMPARABLE"),
        "note": (
            "a disagreement is a finding, not a threshold to tune: if two "
            "simulators disagree about whether a trade hit its stop, at least "
            "one is wrong about history"),
    }


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.consistency",
        "version": CONSISTENCY_VERSION,
        "phase": "3 - Replay (item 14)",
        "simulators_compared": [
            "replay_engine.reality",
            "counterfactual.actual",
            "ai_reinforcement.counterfactual",
        ],
        "magnitude_tolerance_r": MAGNITUDE_TOLERANCE_R,
        "known_duplication": (
            "three implementations walk a historical path forward and compute "
            "a return; ai_reinforcement.CounterfactualSimulator predates the "
            "other two. Consolidating them is a larger change (different input "
            "types, units and consumers), so this module's purpose is to stop "
            "the disagreement being silent"),
        "raises_on_disagreement": False,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "component": "aireplay.consistency", "ok": False, "checks": {}}
    try:
        from .data_engine import extract_replay_records

        records = extract_replay_records(trades or [])
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["records"] = len(records)

        if records:
            summary = consistency_report(records)
            report["checks"]["comparable"] = summary["comparable"]
            report["checks"]["verdict"] = summary["verdict"]
            report["checks"]["disagreement_rate"] = summary["disagreement_rate"]
            report["checks"]["disagreements_by_field"] = summary[
                "disagreements_by_field"]
            # `ok` means the check RAN, not that the simulators agreed --
            # drift is a finding to surface, not a reason to report failure.
            report["ok"] = summary["comparable"] > 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "CONSISTENCY_VERSION", "MAGNITUDE_TOLERANCE_R", "SimulatorResult",
    "compare_simulators", "consistency_report", "get_status", "self_check",
]
