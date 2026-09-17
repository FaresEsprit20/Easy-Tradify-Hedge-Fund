# ============================================================
# STRESS REPLAY -- PHASE 3 ITEM 10
# ============================================================
#
# THE QUESTION
# ------------
# Counterfactual branching asks "what would a different RULE have done on
# these prices". Stress replay asks the opposite: what would THIS rule have
# done had the world been slightly worse. A decision that survives only under
# the exact conditions it happened to meet has no margin, and nothing else in
# this package measures margin.
#
# THE CRITICAL DISTINCTION FROM COUNTERFACTUALS
# ---------------------------------------------
# `counterfactual.py` walks alternative rules over the RECORDED prices, so
# every branch is historical truth. Stress replay MODIFIES the prices. Its
# outputs are therefore simulations, and they are labelled as such
# everywhere: `is_historical_truth` is False on every scenario, and
# `uses_only_historical_prices` is False on every report.
#
# That distinction is not pedantry. Quoting a stressed result beside a
# counterfactual one, both as "what would have happened", is how a system
# starts reporting fiction with the same confidence as measurement. The
# consistency checker treats them differently for the same reason.
#
# WHAT A RESULT MEANS
# -------------------
# The useful output is the BREAKING POINT: the smallest stress magnitude at
# which the outcome flips. A trade that survives 3x its actual spread had
# margin; one that flips at 1.1x was a coin toss that landed well. Neither is
# a prediction about the next trade -- it is a statement about how much of
# this outcome was robust and how much was luck.
#
# WHAT IT DELIBERATELY DOES NOT DO
# --------------------------------
# It does not invent volatility regimes, generate synthetic paths from a
# fitted process, or extrapolate beyond the recorded window. Every stressed
# path is the real path with a bounded, explicit perturbation applied. A
# generated path would require a generator validated against this dataset,
# and nothing here has been.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

STRESS_VERSION = "1.0"

# Multipliers applied to each stress family. 1.0 is always included so the
# unstressed baseline is computed by the SAME code path as the stressed runs
# -- a baseline computed separately can differ for reasons that have nothing
# to do with stress, and then every delta is wrong.
DEFAULT_MAGNITUDES = (1.0, 1.5, 2.0, 3.0)


@dataclass
class StressScenario:
    """One perturbation applied at one magnitude, and what it produced."""

    family: str
    magnitude: float
    realized_r: Optional[float] = None
    exit_index: Optional[int] = None
    exit_reason: Optional[str] = None
    outcome_flipped: Optional[bool] = None
    note: Optional[str] = None

    # Never historical truth. The prices were modified.
    is_historical_truth: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sign(direction: Any) -> int:
    text = str(direction or "").upper()
    if text.startswith("S") or text in ("-1", "SELL", "SHORT"):
        return -1
    return 1


def _walk(prices: Sequence[float], entry: float, stop: float,
          target: Optional[float], sign: int) -> Dict[str, Any]:
    """
    Walk a path to its first stop/target touch, or to its end.

    Shared by every scenario INCLUDING the baseline, so a difference between
    two runs can only come from the perturbation.
    """
    risk = abs(entry - stop)
    if not risk or not math.isfinite(risk):
        return {"realized_r": None, "exit_index": None, "exit_reason": "no_risk"}

    for index, price in enumerate(prices):
        moved = sign * (price - entry)
        if moved <= -risk:
            return {"realized_r": -1.0, "exit_index": index, "exit_reason": "stop"}
        if target is not None:
            distance = abs(target - entry)
            if distance and moved >= distance:
                return {"realized_r": distance / risk, "exit_index": index,
                        "exit_reason": "target"}

    final = sign * (prices[-1] - entry) / risk if prices else None
    return {"realized_r": final, "exit_index": len(prices) - 1 if prices else None,
            "exit_reason": "close"}


# ---------------------------------------------------------------------------
# Stress families
# ---------------------------------------------------------------------------

def stress_spread(prices: Sequence[float], entry: float, magnitude: float,
                  spread: float, sign: int) -> Dict[str, Any]:
    """
    Wider spread: a worse fill, and every level reached later.

    Applied as a shift AGAINST the position, which is the only direction a
    spread can hurt. Modelling it symmetrically would let a wider spread
    improve a trade, which is not a thing that happens.
    """
    penalty = abs(spread) * magnitude * sign
    return {"entry": entry + penalty,
            "prices": list(prices),
            "note": "entry worsened by %.5f" % abs(penalty)}


def stress_slippage(prices: Sequence[float], entry: float, magnitude: float,
                    slippage: float, sign: int) -> Dict[str, Any]:
    """Every price shifted against the position: persistent adverse execution."""
    shift = abs(slippage) * magnitude * sign
    return {"entry": entry,
            "prices": [price - shift for price in prices],
            "note": "all prices shifted %.5f against the position" % abs(shift)}


def stress_volatility(prices: Sequence[float], entry: float, magnitude: float,
                      sign: int) -> Dict[str, Any]:
    """
    Excursions scaled around the entry, path shape preserved.

    Only the AMPLITUDE of each move changes; the order and sign of every move
    is untouched. That keeps the scenario a stress of the same trade rather
    than a different trade wearing its timestamps.
    """
    return {"entry": entry,
            "prices": [entry + (price - entry) * magnitude for price in prices],
            "note": "excursions scaled %.2fx around entry" % magnitude}


def stress_gap(prices: Sequence[float], entry: float, magnitude: float,
               sign: int, risk: float) -> Dict[str, Any]:
    """
    An adverse gap at the midpoint: the risk a stop cannot protect against.

    Sized in R -- half the stop distance per unit of magnitude -- NOT as a
    fraction of the path's own range. Scaling it by the range made the
    smallest gap tested larger than most stops, so this family flipped every
    trade at magnitude 1.0 and `most_fragile_to` came back "gap" for the whole
    cohort. A stress that always breaks is not a measurement, it is a constant
    wearing a result's clothes.

    Placed mid-path rather than at entry because a gap before entry is just a
    worse fill, which stress_spread already covers.
    """
    if len(prices) < 3:
        return {"entry": entry, "prices": list(prices),
                "note": "path too short to gap"}
    midpoint = len(prices) // 2
    jump = abs(risk) * 0.5 * magnitude * sign
    stressed = list(prices)
    for index in range(midpoint, len(stressed)):
        stressed[index] -= jump
    return {"entry": entry, "prices": stressed,
            "note": "adverse gap of %.2fR at observation %d"
                    % (abs(jump) / abs(risk) if risk else 0.0, midpoint)}


STRESS_FAMILIES = ("spread", "slippage", "volatility", "gap")


def stress_trade(canonical_trade: Any,
                 magnitudes: Sequence[float] = DEFAULT_MAGNITUDES,
                 families: Sequence[str] = STRESS_FAMILIES) -> Dict[str, Any]:
    """
    Every stress family at every magnitude, for one trade.

    Returns the baseline, the scenarios, and the breaking point per family.
    A trade whose path cannot be reconstructed is skipped explicitly rather
    than returning an empty result that reads like "nothing broke it".
    """
    from .counterfactual import build_path

    path = build_path(canonical_trade)
    if path is None or not getattr(path, "usable", False):
        return {
            "version": STRESS_VERSION,
            "trade_id": getattr(canonical_trade, "trade_id", None),
            "skipped": "no reconstructable price path",
            "scenarios": [],
            "uses_only_historical_prices": False,
        }

    prices = list(path.prices)
    entry = path.entry_price
    stop = path.stop_loss
    target = path.take_profit
    # TradePath already resolved the direction sign when it reconstructed the
    # path. Re-deriving it here would be a second implementation of one rule,
    # and the two could disagree without anything noticing.
    sign = path.sign

    entry_data = getattr(canonical_trade, "execution", None) or {}
    if not isinstance(entry_data, Mapping):
        entry_data = {}
    spread = entry_data.get("spread_at_entry")
    try:
        spread = abs(float(spread)) if spread is not None else abs(entry) * 1e-4
    except (TypeError, ValueError):
        spread = abs(entry) * 1e-4
    slippage = spread

    baseline = _walk(prices, entry, stop, target, sign)
    baseline_r = baseline["realized_r"]
    baseline_won = (baseline_r or 0.0) > 0

    scenarios: List[StressScenario] = []
    for family in families:
        for magnitude in magnitudes:
            if family == "spread":
                stressed = stress_spread(prices, entry, magnitude, spread, sign)
            elif family == "slippage":
                stressed = stress_slippage(prices, entry, magnitude, slippage, sign)
            elif family == "volatility":
                stressed = stress_volatility(prices, entry, magnitude, sign)
            elif family == "gap":
                stressed = stress_gap(prices, entry, magnitude, sign,
                                      path.risk)
            else:
                continue

            walked = _walk(stressed["prices"], stressed["entry"], stop,
                           target, sign)
            realized = walked["realized_r"]
            scenarios.append(StressScenario(
                family=family,
                magnitude=magnitude,
                realized_r=(round(realized, 4) if realized is not None else None),
                exit_index=walked["exit_index"],
                exit_reason=walked["exit_reason"],
                outcome_flipped=(None if realized is None
                                 else (realized > 0) != baseline_won),
                note=stressed["note"],
            ))

    return {
        "version": STRESS_VERSION,
        "trade_id": getattr(canonical_trade, "trade_id", None),
        "baseline_r": (round(baseline_r, 4) if baseline_r is not None else None),
        "baseline_exit_reason": baseline["exit_reason"],
        "scenarios": [s.to_dict() for s in scenarios],
        "breaking_points": breaking_points(scenarios),
        "margin": margin_summary(scenarios),
        # The load-bearing disclaimer. These paths were modified.
        "uses_only_historical_prices": False,
        "is_simulation": True,
        "why": ("counterfactual branching walks alternative rules over the "
                "recorded prices and is historical truth; this modifies the "
                "prices and is not"),
    }


def breaking_points(scenarios: Sequence[StressScenario]) -> Dict[str, Any]:
    """
    The smallest magnitude at which each family flips the outcome.

    None means the family never flipped it within the magnitudes tested --
    which is NOT the same as "cannot be flipped", and is reported as
    `survived_to` so the distinction is visible rather than inferred from a
    null.
    """
    result: Dict[str, Any] = {}
    families = sorted({s.family for s in scenarios})
    for family in families:
        rows = sorted((s for s in scenarios if s.family == family),
                      key=lambda s: s.magnitude)
        flipped = [s for s in rows if s.outcome_flipped]
        if flipped:
            result[family] = {
                "breaks_at": min(s.magnitude for s in flipped),
                "survived_to": None,
            }
        else:
            result[family] = {
                "breaks_at": None,
                "survived_to": max((s.magnitude for s in rows), default=None),
            }
    return result


def margin_summary(scenarios: Sequence[StressScenario]) -> Dict[str, Any]:
    """
    How much of this outcome was robust.

    `fragile` means some family flipped it at the smallest stress tested --
    the outcome depended on conditions being exactly as good as they were.
    """
    points = breaking_points(scenarios)
    breaks = [v["breaks_at"] for v in points.values() if v["breaks_at"]]
    smallest = min(breaks) if breaks else None
    return {
        "families_tested": len(points),
        "families_that_flipped": len(breaks),
        "smallest_breaking_magnitude": smallest,
        "fragile": bool(smallest is not None and smallest <= 1.5),
        "interpretation": (
            "a trade that flips at 1.0-1.5x had no margin; one that survives "
            "3x was robust to the conditions tested. Neither predicts the "
            "next trade -- both describe how much of THIS outcome was luck"),
    }


def stress_trades(records: Sequence[Any],
                  magnitudes: Sequence[float] = DEFAULT_MAGNITUDES
                  ) -> List[Dict[str, Any]]:
    """Batch form. Unusable records are skipped, never guessed at."""
    results = []
    for record in records or []:
        try:
            results.append(stress_trade(record, magnitudes))
        except Exception:
            continue
    return results


def aggregate_stress(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Fragility across a cohort.

    The cohort number is the one worth acting on: a single fragile trade is an
    anecdote, a portfolio where 60% flip at 1.5x spread is a spread problem.
    """
    usable = [r for r in results if not r.get("skipped")]
    if not usable:
        return {"trades": 0, "fragile_fraction": None,
                "reason": "no trade had a reconstructable path"}

    fragile = [r for r in usable if (r.get("margin") or {}).get("fragile")]
    per_family: Dict[str, int] = {}
    for result in usable:
        for family, point in (result.get("breaking_points") or {}).items():
            if point.get("breaks_at") is not None:
                per_family[family] = per_family.get(family, 0) + 1

    return {
        "trades": len(usable),
        "skipped": len(results) - len(usable),
        "fragile_trades": len(fragile),
        "fragile_fraction": round(len(fragile) / len(usable), 4),
        "flips_by_family": dict(sorted(per_family.items())),
        "most_fragile_to": (max(per_family, key=per_family.get)
                            if per_family else None),
        "is_simulation": True,
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.stress",
        "version": STRESS_VERSION,
        "phase": "3 - item 10 (stress replay)",
        "families": list(STRESS_FAMILIES),
        "default_magnitudes": list(DEFAULT_MAGNITUDES),
        "uses_only_historical_prices": False,
        "is_simulation": True,
        "generates_synthetic_paths": False,
        "how": ("each scenario is the RECORDED path with one bounded, "
                "explicit perturbation applied; nothing is generated from a "
                "fitted process"),
        "reports": ["breaking_points", "margin", "aggregate fragility"],
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove stress actually stresses, and that it is labelled as simulation.

    `baseline_matches_unstressed` is load-bearing: the 1.0 magnitude runs
    through the same code as every stressed scenario, so if it disagrees with
    the baseline the perturbation is leaking into the control and every delta
    reported here is wrong.
    """
    report: Dict[str, Any] = {
        "component": "aireplay.stress", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        checks["labelled_as_simulation"] = (
            get_status()["uses_only_historical_prices"] is False)

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; stress not exercised"
            return report

        from .data_engine import extract_replay_records

        records = extract_replay_records(trades)
        if not records:
            report["ok"] = False
            report["reason"] = "no trade could be canonicalised"
            return report

        result = stress_trade(records[0])
        scenarios = result.get("scenarios") or []
        checks["scenarios_produced"] = len(scenarios)
        checks["every_scenario_is_simulation"] = all(
            not s["is_historical_truth"] for s in scenarios)

        # The 1.0 magnitude of volatility scales excursions by 1.0, i.e. not
        # at all, so it must reproduce the baseline exactly.
        neutral = [s for s in scenarios
                   if s["family"] == "volatility" and s["magnitude"] == 1.0]
        checks["baseline_matches_unstressed"] = bool(
            neutral and neutral[0]["realized_r"] == result["baseline_r"])

        # Stress must be monotone in the direction of harm: a larger adverse
        # shift can never improve the result.
        slippage = sorted((s for s in scenarios if s["family"] == "slippage"),
                          key=lambda s: s["magnitude"])
        returns = [s["realized_r"] for s in slippage
                   if s["realized_r"] is not None]
        checks["harm_is_monotone"] = all(
            returns[i] >= returns[i + 1] - 1e-9 for i in range(len(returns) - 1))

        checks["reports_breaking_points"] = bool(result.get("breaking_points"))
        checks["reports_margin"] = bool(result.get("margin"))

        aggregate = aggregate_stress(stress_trades(records))
        checks["aggregate_reports_fraction"] = (
            aggregate.get("fragile_fraction") is not None)

        required = ("labelled_as_simulation", "every_scenario_is_simulation",
                    "baseline_matches_unstressed", "harm_is_monotone",
                    "reports_breaking_points", "reports_margin")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "STRESS_VERSION", "STRESS_FAMILIES", "DEFAULT_MAGNITUDES",
    "StressScenario", "stress_trade", "stress_trades", "aggregate_stress",
    "breaking_points", "margin_summary", "get_status", "self_check",
]
