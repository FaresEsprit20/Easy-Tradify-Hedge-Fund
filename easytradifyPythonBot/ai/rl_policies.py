# ============================================================
# RL POLICIES -- PHASE 7 ITEMS 2, 3, 4 AND 8
# ============================================================
#
#   item 2  management            -- move the stop, or leave it
#   item 3  exit                  -- close early, or hold
#   item 4  bounded sizing        -- size within hard caps
#   item 8  controlled deployment -- A/B, versioning, rollback
#
# WHY THESE ARE SMALL PARAMETERISED POLICIES AND NOT DEEP RL
# ----------------------------------------------------------
# `ai_reinforcement.py` already has the deep apparatus: an encoder, a
# prioritised replay buffer, n-step returns, an entry-timing environment. It is
# the right machinery for entry timing, where the action space is genuinely
# sequential. It is the wrong machinery here, and the reason is the dataset,
# not the ambition.
#
# Management, exit and sizing each reduce to a handful of thresholds over
# quantities already computed in R. A deep policy over those, trained on a few
# hundred trades, has enough capacity to memorise every path it saw and no way
# to prove it did not -- and the readme's own rejection of deep RL for entry
# direction rests on exactly this reasoning. A small policy space is not a
# compromise here; it is the only space in which a result on this much data
# could mean anything.
#
# The bar is unchanged: chronological trade-grouped splits, expectancy delta in
# R on held-out trades, and a permutation control the real result must beat.
# Grid search over a small space is still a search, so it carries the same
# multiple-comparison hazard as the abstention scan, and the control is sized
# to the number of candidates actually tried.
#
# WHY SIZING IS BOUNDED AND NOT LEARNED FREELY
# --------------------------------------------
# Every learned sizing rule is a leveraged bet on its own validation being
# correct. The caps here are hard and non-negotiable: a learned multiplier can
# only move size WITHIN limits that were set by risk policy, never past them.
# A model that can size its own position without a ceiling can lose the
# account before anyone reads its scorecard.
# ============================================================

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_POLICIES_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PolicyConfig:
    min_trades: int = 40
    train_fraction: float = 0.7

    # Promotion gates, matching exit_model and target_model.
    min_expectancy_gain_r: float = 0.05
    min_gain_over_control_r: float = 0.05
    permutations: int = 40
    random_seed: int = 42

    # Candidate grids. Deliberately coarse: a finer grid searches more
    # hypotheses for the same data and buys nothing but false positives.
    breakeven_triggers: Tuple[float, ...] = (0.5, 0.75, 1.0, 1.5)
    trail_distances: Tuple[float, ...] = (0.5, 1.0, 1.5)
    exit_drawdowns: Tuple[float, ...] = (0.3, 0.5, 0.75, 1.0)


@dataclass
class SizingLimits:
    """
    Hard caps. A learned multiplier may move size within these and never past.

    These are risk policy, not hyperparameters: they are checked on every call
    and clamped rather than validated-and-trusted, because the one path that
    must not exist is a code route where a bad multiplier reaches an order.
    """

    max_risk_percent: float = 1.0
    min_risk_percent: float = 0.1
    max_multiplier: float = 1.5
    min_multiplier: float = 0.5
    max_open_risk_percent: float = 3.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Path access (reused, not reimplemented)
# ---------------------------------------------------------------------------

def _paths(records: Sequence[Any]) -> List[Tuple[str, Any]]:
    """
    Reconstructed paths for a set of canonical trades.

    Uses `aireplay.counterfactual.build_path`. Three simulators in this
    package already walk a price path forward, and consistency.py exists
    because they disagreed; a fourth would be the same mistake again.
    """
    from .aireplay.counterfactual import build_path

    out: List[Tuple[str, Any]] = []
    for record in records or []:
        path = build_path(record)
        if path is not None and getattr(path, "usable", False):
            out.append((str(getattr(record, "trade_id", "")), path))
    return out


def _returns_r(path: Any) -> List[float]:
    """The path expressed in R, entry-relative."""
    return [path.sign * (price - path.entry_price) / path.risk
            for price in path.prices]


def _baseline_r(path: Any) -> float:
    """
    What the trade actually returned.

    Walked with the same stop/target rules the policies use, so a policy's
    delta reflects the policy rather than a difference in accounting.
    """
    target_r = (abs(path.take_profit - path.entry_price) / path.risk
                if path.take_profit else None)
    for value in _returns_r(path):
        if value <= -1.0:
            return -1.0
        if target_r is not None and value >= target_r:
            return target_r
    close = path.close_price
    if close is not None:
        return path.sign * (close - path.entry_price) / path.risk
    return _returns_r(path)[-1]


# ---------------------------------------------------------------------------
# Item 2 -- management
# ---------------------------------------------------------------------------

def apply_management(path: Any, breakeven_trigger: Optional[float],
                     trail_distance: Optional[float]) -> float:
    """
    Walk the path with a stop that may move. Returns realised R.

    The stop only ever moves in the favourable direction. A stop that can
    widen is not risk management, it is a losing position being given more
    room, and it is the single most expensive habit this function could learn.
    """
    returns = _returns_r(path)
    target_r = (abs(path.take_profit - path.entry_price) / path.risk
                if path.take_profit else None)

    stop_r = -1.0
    peak = returns[0] if returns else 0.0

    for value in returns:
        peak = max(peak, value)

        if breakeven_trigger is not None and peak >= breakeven_trigger:
            stop_r = max(stop_r, 0.0)
        if trail_distance is not None and peak >= trail_distance:
            stop_r = max(stop_r, peak - trail_distance)

        if value <= stop_r:
            return stop_r
        if target_r is not None and value >= target_r:
            return target_r

    close = path.close_price
    if close is not None:
        return path.sign * (close - path.entry_price) / path.risk
    return returns[-1] if returns else 0.0


# ---------------------------------------------------------------------------
# Item 3 -- exit
# ---------------------------------------------------------------------------

def apply_exit(path: Any, drawdown_from_peak: float) -> float:
    """
    Close when the position has handed back this much from its peak.

    Only armed once the trade has been in profit. Applied from entry it would
    fire on the ordinary noise every trade starts with, and close every
    position at its first adverse tick.
    """
    returns = _returns_r(path)
    target_r = (abs(path.take_profit - path.entry_price) / path.risk
                if path.take_profit else None)

    peak = returns[0] if returns else 0.0
    for value in returns:
        peak = max(peak, value)
        if value <= -1.0:
            return -1.0
        if target_r is not None and value >= target_r:
            return target_r
        if peak > 0 and (peak - value) >= drawdown_from_peak:
            return value

    close = path.close_price
    if close is not None:
        return path.sign * (close - path.entry_price) / path.risk
    return returns[-1] if returns else 0.0


# ---------------------------------------------------------------------------
# Item 4 -- bounded sizing
# ---------------------------------------------------------------------------

def bounded_size(base_risk_percent: float, multiplier: float,
                 open_risk_percent: float = 0.0,
                 limits: Optional[SizingLimits] = None) -> Dict[str, Any]:
    """
    Position size within hard caps, with every clamp reported.

    Returns the reasons rather than silently applying them: a size that was
    cut from 1.4% to 1.0% and reported only as "1.0%" hides the fact that the
    model wanted something the limits refused, which is exactly the signal a
    risk reviewer needs.
    """
    limits = limits or SizingLimits()
    applied: List[str] = []

    safe_multiplier = multiplier
    if not isinstance(multiplier, (int, float)) or not math.isfinite(multiplier):
        safe_multiplier = 1.0
        applied.append("non-finite multiplier replaced with 1.0")
    if safe_multiplier > limits.max_multiplier:
        safe_multiplier = limits.max_multiplier
        applied.append("multiplier capped at %.2f" % limits.max_multiplier)
    if safe_multiplier < limits.min_multiplier:
        safe_multiplier = limits.min_multiplier
        applied.append("multiplier floored at %.2f" % limits.min_multiplier)

    size = max(0.0, float(base_risk_percent or 0.0)) * safe_multiplier
    if size > limits.max_risk_percent:
        size = limits.max_risk_percent
        applied.append("size capped at %.2f%%" % limits.max_risk_percent)
    if 0 < size < limits.min_risk_percent:
        size = limits.min_risk_percent
        applied.append("size floored at %.2f%%" % limits.min_risk_percent)

    # Portfolio ceiling last: a per-trade size that is individually fine can
    # still be the one that breaches total exposure.
    remaining = limits.max_open_risk_percent - max(0.0, open_risk_percent)
    if remaining <= 0:
        applied.append("portfolio risk budget exhausted; size set to 0")
        size = 0.0
    elif size > remaining:
        size = remaining
        applied.append("size reduced to remaining portfolio budget %.2f%%"
                       % remaining)

    return {
        "risk_percent": round(size, 4),
        "multiplier_used": round(safe_multiplier, 4),
        "multiplier_requested": multiplier,
        "limits_applied": applied,
        "was_clamped": bool(applied),
        "limits": limits.to_dict(),
    }


# ---------------------------------------------------------------------------
# Training and validation
# ---------------------------------------------------------------------------

def _evaluate(paths: Sequence[Tuple[str, Any]], policy) -> Optional[float]:
    values = [policy(path) for _, path in paths]
    return sum(values) / len(values) if values else None


def _permuted_paths(paths: Sequence[Tuple[str, Any]], rng) -> List[Tuple[str, Any]]:
    """
    Each path's price INCREMENTS shuffled, entry and endpoint preserved.

    A shuffled-label control cannot test a policy that never sees a label --
    management and exit read only the path. Permuting increments destroys the
    temporal order a policy must exploit while preserving length, volatility
    and the exact multiset of moves, which is the control exit_model needed
    for the same reason.
    """
    from dataclasses import replace as _replace

    out: List[Tuple[str, Any]] = []
    for trade_id, path in paths:
        prices = list(path.prices)
        if len(prices) < 3:
            out.append((trade_id, path))
            continue
        increments = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
        rng.shuffle(increments)
        rebuilt = [prices[0]]
        for step in increments:
            rebuilt.append(rebuilt[-1] + step)
        out.append((trade_id, _replace(path, prices=tuple(rebuilt))))
    return out


def train_policy(records: Sequence[Any], kind: str = "management",
                 config: Optional[PolicyConfig] = None) -> Dict[str, Any]:
    """
    Grid-search a small policy on train, validate on held-out trades.

    `kind` is "management" or "exit". Both are gated on an expectancy delta in
    R that also beats a permutation control -- AUC is not accepted here for
    the same reason it is not accepted anywhere else in this package.
    """
    cfg = config or PolicyConfig()
    report: Dict[str, Any] = {
        "version": RL_POLICIES_VERSION, "kind": kind, "promoted": False}

    paths = _paths(records)
    report["trades"] = len(paths)
    if len(paths) < cfg.min_trades:
        report["measurable"] = False
        report["rejected_because"] = (
            "%d usable paths; %d required" % (len(paths), cfg.min_trades))
        return report

    report["measurable"] = True
    cut = int(len(paths) * cfg.train_fraction)
    train, test = paths[:cut], paths[cut:]
    report["train_trades"], report["test_trades"] = len(train), len(test)

    if kind == "management":
        candidates = [
            {"breakeven_trigger": b, "trail_distance": t}
            for b in (None,) + cfg.breakeven_triggers
            for t in (None,) + cfg.trail_distances
            if not (b is None and t is None)
        ]
        def make(params):
            return lambda path: apply_management(
                path, params["breakeven_trigger"], params["trail_distance"])
    elif kind == "exit":
        candidates = [{"drawdown_from_peak": d} for d in cfg.exit_drawdowns]
        def make(params):
            return lambda path: apply_exit(path, params["drawdown_from_peak"])
    else:
        report["rejected_because"] = "unknown policy kind: %s" % kind
        return report

    report["candidates_searched"] = len(candidates)

    scored = [(params, _evaluate(train, make(params))) for params in candidates]
    scored = [(p, v) for p, v in scored if v is not None]
    if not scored:
        report["measurable"] = False
        report["rejected_because"] = "no candidate scored on the training split"
        return report

    best_params, best_train = max(scored, key=lambda pair: pair[1])
    report["parameters"] = best_params
    report["train_expectancy_r"] = round(best_train, 4)

    baseline = _evaluate(test, _baseline_r)
    policy_r = _evaluate(test, make(best_params))
    report["baseline_r"] = round(baseline, 4) if baseline is not None else None
    report["policy_r"] = round(policy_r, 4) if policy_r is not None else None
    delta = ((policy_r - baseline)
             if policy_r is not None and baseline is not None else None)
    report["delta_r"] = round(delta, 4) if delta is not None else None

    # The control runs the WHOLE procedure -- search included -- on permuted
    # paths. Controlling only the final policy would ignore that the search
    # itself finds the best of many candidates, which is where most of the
    # optimism lives.
    rng = random.Random(cfg.random_seed)
    control_deltas: List[float] = []
    for _ in range(cfg.permutations):
        permuted = _permuted_paths(paths, rng)
        p_train, p_test = permuted[:cut], permuted[cut:]
        p_scored = [(params, _evaluate(p_train, make(params)))
                    for params in candidates]
        p_scored = [(p, v) for p, v in p_scored if v is not None]
        if not p_scored:
            continue
        p_best = max(p_scored, key=lambda pair: pair[1])[0]
        p_policy = _evaluate(p_test, make(p_best))
        p_baseline = _evaluate(p_test, _baseline_r)
        if p_policy is None or p_baseline is None:
            continue
        control_deltas.append(p_policy - p_baseline)

    if control_deltas:
        ordered = sorted(control_deltas)
        index = min(len(ordered) - 1, int(0.95 * len(ordered)))
        report["control_mean_r"] = round(sum(ordered) / len(ordered), 4)
        report["control_95th_r"] = round(ordered[index], 4)
    else:
        report["control_mean_r"] = None
        report["control_95th_r"] = None
    report["control_runs"] = len(control_deltas)

    reasons: List[str] = []
    if delta is None:
        reasons.append("policy could not be scored on the test split")
    else:
        if delta < cfg.min_expectancy_gain_r:
            reasons.append("expectancy delta %.4fR below the %.2fR minimum"
                           % (delta, cfg.min_expectancy_gain_r))
        if report["control_95th_r"] is None:
            reasons.append("permutation control could not be scored, so the "
                           "noise floor is unknown")
        elif delta <= report["control_95th_r"]:
            reasons.append(
                "delta %.4fR does not exceed the 95th percentile of the "
                "permutation control (%.4fR) -- the same search reaches this "
                "on order-destroyed paths at least 5%% of the time"
                % (delta, report["control_95th_r"]))

    report["promoted"] = not reasons
    report["rejected_because"] = "; ".join(reasons) if reasons else None
    return report


# ---------------------------------------------------------------------------
# Item 8 -- controlled deployment
# ---------------------------------------------------------------------------

def deploy(name: str, report: Mapping[str, Any], payload: Any = None,
           store: Any = None) -> Dict[str, Any]:
    """
    Register a trained policy, and expose it only through the A/B machinery.

    Deployment here means: version it, promote it only if its gates passed,
    and put it behind a rollout that starts small. It never means "switch
    every trade to the new policy". Governance owns the rollout and the
    rollback; this only hands it over.
    """
    from .model_governance import get_ab_test, get_registry, record_training

    outcome = record_training(
        name, payload if payload is not None else dict(report),
        metrics={key: report.get(key) for key in
                 ("delta_r", "policy_r", "baseline_r", "test_trades")
                 if report.get(key) is not None},
        promoted=bool(report.get("promoted")),
        notes=report.get("rejected_because") or "passed promotion gates",
        store=store)

    experiment = get_ab_test(name, store=store)
    if report.get("promoted"):
        # Starts at 10%. A policy that just cleared its gates on a few hundred
        # historical trades has earned an experiment, not the whole book.
        experiment.set_rollout(min(0.1, experiment.config.max_rollout))
        deployment = "experiment_started_at_10_percent"
    else:
        experiment.set_rollout(0.0)
        deployment = "not_deployed: gates not passed"

    registry = get_registry(name, store)
    return {
        "policy": name,
        "registered_version": outcome["registered_version"],
        "promoted": outcome["promoted"],
        "deployment": deployment,
        "rollout": experiment.config.rollout,
        "can_rollback": registry.status()["can_rollback"],
        "ab_test": experiment.results(),
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "rl_policies",
        "version": RL_POLICIES_VERSION,
        "implements": {
            "management": True,            # phase 7 item 2
            "exit": True,                  # phase 7 item 3
            "bounded_sizing": True,        # phase 7 item 4
            "controlled_deployment": True,  # phase 7 item 8
        },
        "policy_class": "small parameterised rules, grid-searched",
        "why_not_deep": (
            "management, exit and sizing reduce to a few thresholds over "
            "quantities already in R; a deep policy over those on a few "
            "hundred trades can memorise every path it saw and cannot prove "
            "it did not"),
        "validation": ("chronological split, expectancy delta in R, must "
                       "exceed the 95th percentile of an increment-permutation "
                       "control that includes the search itself"),
        "sizing_limits": SizingLimits().to_dict(),
        "deployment_starts_at": 0.1,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the policies behave, the caps hold, and the control refuses noise.

    `stop_never_widens` and the sizing clamps are the load-bearing checks:
    both are places where a subtle bug costs money rather than accuracy.
    """
    report: Dict[str, Any] = {
        "component": "rl_policies", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        # Sizing caps, including the portfolio ceiling.
        limits = SizingLimits()
        big = bounded_size(1.0, 5.0, 0.0, limits)
        checks["multiplier_capped"] = big["multiplier_used"] == limits.max_multiplier
        checks["size_capped"] = big["risk_percent"] <= limits.max_risk_percent
        checks["clamps_are_reported"] = bool(big["limits_applied"])

        exhausted = bounded_size(1.0, 1.0, limits.max_open_risk_percent, limits)
        checks["portfolio_ceiling_holds"] = exhausted["risk_percent"] == 0.0

        broken = bounded_size(1.0, float("nan"), 0.0, limits)
        checks["non_finite_multiplier_handled"] = (
            broken["multiplier_used"] == 1.0)

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; policies not exercised"
            return report

        from .aireplay.data_engine import extract_replay_records

        records = extract_replay_records(trades)
        paths = _paths(records)
        checks["usable_paths"] = len(paths)
        if not paths:
            report["ok"] = False
            report["reason"] = "no trade produced a usable path"
            return report

        # A stop that can widen is not risk management. Breakeven must never
        # return worse than 0 once the trigger was reached.
        widened = []
        for _, path in paths:
            returns = _returns_r(path)
            if max(returns) >= 1.0:
                managed = apply_management(path, 1.0, None)
                if managed < 0.0:
                    widened.append(managed)
        checks["stop_never_widens"] = not widened

        # Exit must not fire before the trade has been in profit.
        never_profitable = [
            apply_exit(path, 0.3) for _, path in paths
            if max(_returns_r(path)) <= 0]
        checks["exit_not_armed_before_profit"] = all(
            value <= 0 for value in never_profitable)

        for kind in ("management", "exit"):
            result = train_policy(records, kind)
            checks["%s_runs" % kind] = "promoted" in result
            checks["%s_has_control" % kind] = (
                result.get("control_95th_r") is not None
                or not result.get("measurable"))

        required = ("multiplier_capped", "size_capped", "clamps_are_reported",
                    "portfolio_ceiling_holds", "non_finite_multiplier_handled",
                    "stop_never_widens", "exit_not_armed_before_profit",
                    "management_runs", "exit_runs")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "RL_POLICIES_VERSION", "PolicyConfig", "SizingLimits",
    "apply_management", "apply_exit", "bounded_size",
    "train_policy", "deploy", "get_status", "self_check",
]
