# ============================================================
# RULE EXPERIMENTS -- TEST A VETO, THEN CHANGE IT
# ============================================================
#
# WHY THIS EXISTS
# ---------------
# Replaying 215 real trades with their analysis recomputed found the ADX
# "choppy market" veto pointing the wrong way:
#
#     choppy-vetoed    n=118   mean +0.0189R   win 48.3%
#     not vetoed       n= 97   mean -0.0890R   win 37.1%
#
# The trades the veto blocks are the only profitable group in the account;
# the trades it approves lose. At p=0.49 that is not proof the veto is
# harmful -- it is proof it does not discriminate, and 215 trades cannot
# settle it either way. A 1,756-bucket scan over the same data survived
# nothing at all, so this is the one candidate worth spending an experiment
# on.
#
# WHAT THIS IS FOR
# ----------------
# Running that question forward as a controlled experiment, and -- the actual
# goal -- ENDING IN A RULE CHANGE. `recommended_change()` turns a settled
# experiment into the specific edit to make, or says plainly that the evidence
# does not support one yet. An experiment that never terminates in a decision
# is a dashboard.
#
# WHY THE VETO ENGINE MAKES THIS CLEAN
# ------------------------------------
# `VetoEngine._veto_active(name)` already separates "did this veto fire" from
# "is it allowed to block": a disabled veto still runs and still records its
# verdict, and only the block is suppressed. So both arms of the experiment
# produce identical telemetry and differ in exactly one respect -- whether the
# trade was stopped. That is the ideal shape for an A/B, and it was already
# there.
#
# A LIMITATION WORTH STATING: ASSIGNMENT IS CLUSTERED
# ---------------------------------------------------
# The veto call site has the SYMBOL in scope and no per-decision identifier,
# so arms are assigned per instrument. That makes this a cluster-randomised
# trial with ~27 units, not 215, and a symbol carrying its own edge lands
# wholly in one arm and biases the comparison. It is the honest shape of what
# is available today, not the ideal one.
#
# Trade-level assignment is strictly better and becomes possible the moment
# the decision path carries an id -- `aireplay.live_recording` already mints
# a provisional key per decision. Until then, read the verdict knowing the
# effective sample size is closer to the number of symbols than the number of
# trades, and give it correspondingly more time.
#
# SAFETY
# ------
# OFF unless AI_RULE_EXPERIMENTS is set. Assignment is deterministic on
# trade/symbol identity, so the same candidate always lands in the same arm.
# Nothing here raises into the veto path: a telemetry failure must never
# decide whether a trade is blocked.
# ============================================================

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

RULE_EXPERIMENTS_VERSION = "1.0"

_ENV_FLAG = "AI_RULE_EXPERIMENTS"

# Experiments currently defined. Each names the veto it suppresses in the
# TEST arm, and carries the evidence that motivated it, so a reader in three
# months can see why it was ever run.
EXPERIMENTS: Dict[str, Dict[str, Any]] = {
    "choppy_market": {
        "veto": "choppy_market",
        "hypothesis": (
            "the ADX choppy-market veto does not improve expectancy and may "
            "invert it"),
        "test_arm": "veto suppressed (trade allowed)",
        "control_arm": "veto blocks as today",
        "prior_evidence": {
            "source": "215 real MT5 trades, analysis recomputed from bars",
            "vetoed_mean_r": 0.0189, "vetoed_win_rate": 0.483, "vetoed_n": 118,
            "approved_mean_r": -0.0890, "approved_win_rate": 0.371,
            "approved_n": 97,
            "separation_r": -0.108, "p_value": 0.49,
            "caveat": ("not significant; 215 trades cannot settle it, which "
                       "is why this is an experiment and not a change"),
        },
        # The change to make if the test arm wins.
        "rule_change_if_test_wins": (
            "add 'choppy_market' to VetoEngine.disabled_vetos, or set the "
            "instrument ADX threshold to 0 in asset_analysis_config"),
        "rule_change_if_control_wins": (
            "keep the veto; the prior evidence was noise"),
    },
}


def is_enabled() -> bool:
    """Read live, so an experiment can be stopped without a restart."""
    return str(os.environ.get(_ENV_FLAG, "")).strip().lower() in (
        "1", "true", "yes", "on")


def _experiment_name(veto: str) -> str:
    return "rule_veto_" + veto


def _ab(veto: str):
    from .model_governance import ABConfig, get_ab_test

    # Starts at 20%: enough to accumulate a test arm at a realistic trade
    # rate, small enough that a wrong hypothesis costs little. Auto-adjust
    # stays off -- an experiment that widens its own exposure on an interim
    # reading is how a rollout chases noise.
    return get_ab_test(_experiment_name(veto),
                       ABConfig(rollout=0.2, min_samples=30, auto_adjust=False))


def should_suppress(veto: str, unit_id: Any) -> bool:
    """
    Is this candidate in the TEST arm, where the veto does not block?

    Returns False for anything unexpected. The failure mode that matters is
    suppressing a veto by accident, so every uncertain path keeps the veto
    active -- the behaviour that exists today.
    """
    if not is_enabled():
        return False
    try:
        if veto not in EXPERIMENTS or unit_id is None:
            return False
        return _ab(veto).in_test(unit_id)
    except Exception:
        return False


def record_outcome(veto: str, unit_id: Any, profit: float,
                   outcome: int) -> Dict[str, Any]:
    """Record one settled trade into whichever arm it was assigned."""
    if not is_enabled():
        return {"tracked": False, "reason": "experiments disabled"}
    try:
        if veto not in EXPERIMENTS:
            return {"tracked": False, "reason": "unknown experiment"}
        return _ab(veto).track(unit_id, profit, outcome)
    except Exception as exc:
        return {"tracked": False, "reason": type(exc).__name__}


def results(veto: str) -> Dict[str, Any]:
    """The governed A/B verdict for one rule experiment."""
    if veto not in EXPERIMENTS:
        return {"error": "unknown experiment: " + str(veto)}
    payload = dict(EXPERIMENTS[veto])
    payload["experiment"] = _experiment_name(veto)
    payload["enabled"] = is_enabled()
    try:
        payload["ab_test"] = _ab(veto).results()
    except Exception as exc:
        payload["ab_test"] = {"error": type(exc).__name__ + ": " + str(exc)}
    return payload


def recommended_change(veto: str) -> Dict[str, Any]:
    """
    The point of the whole exercise: what to change in the rule base.

    Only speaks when the experiment is BOTH statistically significant and
    directionally clear. `verdict_is_actionable` is governance's own field
    for that, and it requires a p-value below alpha as well as a delta
    outside the noise band -- a threshold crossing alone was never enough.

    Until then this returns "keep the current rule" with the reason, because
    the default in a live trading system has to be no change.
    """
    if veto not in EXPERIMENTS:
        return {"error": "unknown experiment: " + str(veto)}

    spec = EXPERIMENTS[veto]
    report = results(veto)
    ab = report.get("ab_test") or {}
    control = (ab.get("control") or {}).get("samples", 0)
    test = (ab.get("test") or {}).get("samples", 0)

    change: Dict[str, Any] = {
        "veto": veto,
        "experiment": _experiment_name(veto),
        "control_samples": control,
        "test_samples": test,
        "status": ab.get("status"),
        "significant": ab.get("significant"),
        "p_value": ab.get("p_value"),
        "actionable": bool(ab.get("verdict_is_actionable")),
    }

    if not ab.get("verdict_is_actionable"):
        change["decision"] = "NO CHANGE"
        change["reason"] = (
            "the experiment has not produced an actionable verdict "
            "(status %s, p=%s, control n=%s, test n=%s). The default in a "
            "live system is to change nothing."
            % (ab.get("status"), ab.get("p_value"), control, test))
        return change

    if ab.get("status") == "TEST_BETTER":
        change["decision"] = "CHANGE THE RULE"
        change["apply"] = spec["rule_change_if_test_wins"]
        change["reason"] = (
            "suppressing the veto beat leaving it in place: test %s vs "
            "control %s win rate, p=%s"
            % ((ab.get("test") or {}).get("win_rate"),
               (ab.get("control") or {}).get("win_rate"), ab.get("p_value")))
    else:
        change["decision"] = "KEEP THE RULE"
        change["apply"] = spec["rule_change_if_control_wins"]
        change["reason"] = (
            "the veto beat suppressing it; the replay finding was noise "
            "(p=%s)" % ab.get("p_value"))
    return change


def get_status() -> Dict[str, Any]:
    return {
        "component": "rule_experiments",
        "version": RULE_EXPERIMENTS_VERSION,
        "enabled": is_enabled(),
        "env_flag": _ENV_FLAG,
        "default": "OFF",
        "experiments": list(EXPERIMENTS),
        "seam": "VetoEngine._veto_active",
        "why_that_seam": (
            "a disabled veto still runs and still records its verdict; only "
            "the block is suppressed, so both arms produce identical "
            "telemetry and differ in exactly one respect"),
        "goal": ("end in a rule change: recommended_change() emits the "
                 "specific edit once the verdict is actionable"),
        "fails_safe_to": "veto active (today's behaviour)",
        "assignment_unit": "symbol (clustered; ~27 units, not 215 trades)",
        "assignment_limitation": (
            "a symbol carrying its own edge lands wholly in one arm; "
            "trade-level assignment is better and needs a per-decision id"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the experiment fails safe and refuses to recommend prematurely.

    `premature_change_refused` is the load-bearing one. This module's output
    is a change to a live trading rule; a version that recommends one on an
    interim reading would be worse than having no experiment at all.
    """
    report: Dict[str, Any] = {
        "component": "rule_experiments", "ok": False, "checks": {}}
    previous = os.environ.get(_ENV_FLAG)
    try:
        checks = report["checks"]

        # Disabled: nothing is ever suppressed.
        os.environ.pop(_ENV_FLAG, None)
        checks["disabled_suppresses_nothing"] = not should_suppress(
            "choppy_market", "t-1")

        os.environ[_ENV_FLAG] = "1"
        # Unknown experiments and missing ids fail safe.
        checks["unknown_veto_fails_safe"] = not should_suppress("nope", "t-1")
        checks["missing_id_fails_safe"] = not should_suppress(
            "choppy_market", None)

        # Assignment is deterministic and actually splits.
        ids = ["trade-%d" % i for i in range(300)]
        first = [should_suppress("choppy_market", i) for i in ids]
        second = [should_suppress("choppy_market", i) for i in ids]
        checks["assignment_deterministic"] = first == second
        checks["assignment_splits"] = 0 < sum(first) < len(ids)

        # A fresh experiment must not recommend anything.
        change = recommended_change("choppy_market")
        checks["premature_change_refused"] = change["decision"] == "NO CHANGE"
        checks["refusal_explains_itself"] = bool(change.get("reason"))

        # The spec carries its evidence and both outcomes.
        spec = EXPERIMENTS["choppy_market"]
        checks["carries_prior_evidence"] = bool(spec.get("prior_evidence"))
        checks["defines_both_outcomes"] = bool(
            spec.get("rule_change_if_test_wins")
            and spec.get("rule_change_if_control_wins"))

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if previous is None:
            os.environ.pop(_ENV_FLAG, None)
        else:
            os.environ[_ENV_FLAG] = previous
    return report


__all__ = [
    "RULE_EXPERIMENTS_VERSION", "EXPERIMENTS", "is_enabled",
    "should_suppress", "record_outcome", "results", "recommended_change",
    "get_status", "self_check",
]
