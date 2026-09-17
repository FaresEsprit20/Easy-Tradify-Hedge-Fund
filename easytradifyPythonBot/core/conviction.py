"""
CONVICTION FILTER
=================
FILE: core/conviction.py

Raises win rate by taking fewer trades, without touching R:R.

At the configured 2:1, break-even is 33% and a real 50% returns 50R per
hundred trades. Getting from 50% to 65% means being right more often on
the trades taken -- which means declining the ones the system is least
sure about. That is selectivity, and it is the only lever that raises win
rate without shrinking TP.

THE POINT: NOTHING HERE IS NEW EVIDENCE

Every input below is already computed on every bar and then discarded at
decision time:

  coherence          computed, reported, never consulted. A trade taken
                     while the system contradicts itself is a trade taken
                     on inputs known to be unreliable.
  gate margins       near_miss is calculated for every gate and used for
                     nothing. Clearing probability_threshold by 0.3 and
                     clearing it by 20 are recorded identically as "pass".
  confluence chain   ~12 checks each report aligned true/false. Their
                     adjustments are summed; the COUNT that agreed is
                     thrown away. Three checks opposing is materially
                     different from none opposing, and the sum can hide it.

So this adds no new indicator and fetches no new data. It requires the
system to agree with itself before risking money.

WHY A THRESHOLD AND NOT MORE PENALTIES

Probability already aggregates. Adding another additive term would just
be a thirteenth chain step, and the failure mode of an additive chain is
that strong scores in one place paper over refusals in another -- which
is how a setup with three opposing checks still reached 95%.

Conviction is a VETO, not a score. Any single hard requirement can
decline a trade regardless of how good the rest looks.
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coherence_component(result) -> Dict[str, Any]:
    """
    Self-consistency. A CRITICAL violation means two fields that gate the
    trade disagree -- the decision itself rests on something incoherent,
    and no amount of probability compensates for that.

    ERROR also hard-fails, not just CRITICAL. A 12-day XAGUSD replay
    (1856 decisions) measured coherence_violations > 0 -- CRITICAL and
    ERROR combined -- against 9.9 points of win-rate swing (18.5% with
    a violation vs 28.4% without, the largest predictive signal found
    in that sample, ahead of every one of the 11 evidence families).
    ERROR is defined one severity below CRITICAL ("a published field
    contradicts the value that decided -- anyone reading the output is
    misled"), which is still a decision-integrity failure, not a
    quality-of-evidence one. Scoring it at 0.4 let a strong rest-of-chain
    score carry a trade past it -- exactly what this module's own
    module docstring says conviction exists to prevent ("any single
    hard requirement can decline a trade regardless of how good the
    rest looks").
    """
    coh = result.get("coherence") or {}
    counts = coh.get("counts") or {}
    crit = int(counts.get("CRITICAL", 0) or 0)
    err = int(counts.get("ERROR", 0) or 0)

    if coh.get("coherent") is None:
        return {"score": 0.5, "hard_fail": False, "detail": "validator unavailable"}
    if crit:
        return {"score": 0.0, "hard_fail": True,
                "detail": f"{crit} CRITICAL coherence violation(s)"}
    if err:
        return {"score": 0.4, "hard_fail": True,
                "detail": f"{err} ERROR coherence violation(s)"}
    return {"score": 1.0, "hard_fail": False, "detail": "self-consistent"}


def _margin_component(result) -> Dict[str, Any]:
    """
    How comfortably the enforced gates were cleared.

    A gate passed by a hair is a coin flip on the next tick. near_miss is
    already computed for exactly this and consumed by nothing. Advisory
    gates are excluded -- they cannot block, so their margins say nothing
    about whether this trade was permitted.
    """
    gates = ((result.get("decision_snapshot") or {}).get("gates_with_margin")
             or result.get("gates") or [])
    enforced = [g for g in gates if isinstance(g, dict)
                and g.get("enforced", True) and g.get("passed")]
    if not enforced:
        return {"score": 0.5, "hard_fail": False, "detail": "no enforced gate data"}

    near = [g.get("gate") for g in enforced if g.get("near_miss")]
    # Normalise each margin against its own threshold so gates measured in
    # ADX, pips and percent are comparable.
    ratios = []
    for g in enforced:
        m, t = _num(g.get("margin")), _num(g.get("threshold"))
        if m is None or not t:
            continue
        ratios.append(max(0.0, m) / abs(t))
    weakest = min(ratios) if ratios else 0.5

    return {
        "score": max(0.0, min(1.0, weakest / 0.10)),   # 10% clearance = full marks
        "hard_fail": bool(near),
        "detail": (f"weakest gate cleared by {weakest:.1%} of its threshold"
                   + (f"; near-miss on {near}" if near else "")),
        "near_miss_gates": near,
    }


def _chain_component(result, direction) -> Dict[str, Any]:
    """
    How many confluence checks agreed, as a count rather than a sum.

    The chain sums adjustments, so one strongly-aligned check can mask
    three opposing ones. The count cannot be masked that way.
    """
    fv = result.get("final_verdict") or {}
    aligned = opposed = 0
    opposing_names: List[str] = []
    for k, v in fv.items():
        if not (k.endswith("_final_score") and isinstance(v, dict)):
            continue
        a = v.get("aligned")
        if a is True:
            aligned += 1
        elif a is False:
            opposed += 1
            opposing_names.append(k.replace("_final_score", ""))

    decided = aligned + opposed
    if not decided:
        return {"score": 0.5, "hard_fail": False, "detail": "no chain check took a side"}

    ratio = aligned / decided
    return {
        "score": ratio,
        # ✅ CHANGED: this hard-failed on `opposed >= 2`, on the reasoning
        # that two independent checks opposing is something the additive
        # sum can hide. Plausible, and measured false.
        #
        # A 4240-decision EURUSD replay scored it against outcomes:
        #
        #   hard-failed  n=2932  would-win 30.4%
        #   passed       n=1237  would-win 29.3%
        #
        # The setups it blocked went on to do slightly BETTER than the
        # ones it allowed. Within noise either way, which is the point:
        # it discriminates nothing. Meanwhile it was the single largest
        # consumer of trades left in the funnel -- 14 of the 15 setups
        # that survived the entry engine, the veto engine and the R:R
        # floor died here, leaving one trade in thirty days and no sample
        # to measure anything with.
        #
        # This module's own docstring says what to do about that: "If
        # conviction turns out not to predict wins, the audit will show
        # that and this should be loosened or dropped rather than
        # defended." The audit showed it.
        #
        # The signal is NOT discarded -- `score` still carries the
        # aligned/opposed ratio into the weighted total, so a chain in
        # open revolt still drags conviction down and can still decline a
        # trade via min_score. What it can no longer do is veto on its
        # own, unmeasured.
        "hard_fail": False,
        "detail": f"{aligned} aligned / {opposed} opposed"
                  + (f" ({', '.join(opposing_names)})" if opposing_names else "")
                  + (" [advisory: measured at +1.1pts discrimination, "
                     "no longer a hard fail]" if opposed >= 2 else ""),
    }


def _groups_component(result, direction) -> Dict[str, Any]:
    """
    How many strategy groups agree with the trade, as a count.

    Replaces the confluence-chain count while the strategy groups set the
    probability (2026-09-15). The chain's aligned/opposed flags describe
    additive steps that no longer decide anything; live, a USDCAD setup the
    groups scored 91.5 read "1 aligned / 5 opposed" on the chain and was
    marked down for it. Falls back to the chain count when the groups are
    off or produced nothing.
    """
    groups_result = result.get("strategy_groups") or {}
    groups = groups_result.get("groups") or {}
    scored = [g for g in groups.values() if isinstance(g, dict) and g.get("scored")]
    if not groups_result.get("enabled") or not scored:
        return _chain_component(result, direction)
    with_ = [name for name, g in groups.items() if isinstance(g, dict) and g.get("scored") and g.get("score", 50) > 50]
    against = [name for name, g in groups.items() if isinstance(g, dict) and g.get("scored") and g.get("score", 50) < 50]
    decided = len(with_) + len(against)
    if not decided:
        return {"score": 0.5, "hard_fail": False, "detail": "no strategy group took a side"}
    return {
        "score": len(with_) / decided,
        "hard_fail": False,
        "detail": f"{len(with_)} strategy groups with / {len(against)} against"
                  + (f" ({', '.join(against)})" if against else ""),
    }


# Weights for the soft score. Coherence carries most because it is the
# only component that speaks to whether the OTHER components can be
# trusted at all.
#
# family_consensus (0.25) was removed with family voting on 2026-09-15. The
# remaining weights keep their old proportions (0.35 : 0.25 : 0.15), rescaled
# to sum to 1.0.
CONVICTION_WEIGHTS = {
    "coherence": round(0.35 / 0.75, 4),
    "gate_margins": round(0.25 / 0.75, 4),
    "strategy_groups": round(0.15 / 0.75, 4),
}


def evaluate_conviction(result: Dict[str, Any],
                        direction: str,
                        min_score: float = 0.55,
                        allow_hard_fail_override: bool = False) -> Dict[str, Any]:
    """
    Should this trade be taken, given that the system already said yes?

    Returns a verdict plus the full breakdown, so a declined trade is
    explainable and -- once outcomes exist -- checkable. If conviction
    turns out not to predict wins, the audit will show that and this
    should be loosened or dropped rather than defended.
    """
    components = {
        "coherence": _coherence_component(result),
        "gate_margins": _margin_component(result),
        "strategy_groups": _groups_component(result, direction),
    }

    hard_fails = [k for k, c in components.items() if c.get("hard_fail")]
    score = sum(c["score"] * CONVICTION_WEIGHTS[k] for k, c in components.items())

    blocked = bool(hard_fails) and not allow_hard_fail_override
    if not blocked:
        blocked = score < min_score

    if hard_fails:
        reason = f"hard requirement failed: {', '.join(hard_fails)}"
    elif score < min_score:
        reason = f"conviction {score:.2f} below minimum {min_score:.2f}"
    else:
        reason = f"conviction {score:.2f}"

    return {
        "conviction_score": round(score, 3),
        "min_required": min_score,
        "passed": not blocked,
        "hard_fails": hard_fails,
        "reason": reason,
        "components": {k: {"score": round(c["score"], 3),
                           "hard_fail": c.get("hard_fail", False),
                           "detail": c.get("detail")}
                       for k, c in components.items()},
        "weights": CONVICTION_WEIGHTS,
    }