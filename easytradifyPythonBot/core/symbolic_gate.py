"""
NEURO-SYMBOLIC GATE  (Stage 9 of the decoupled AI pipeline)
===========================================================
FILE: core/symbolic_gate.py

Hard first-order predicates over a trade's own arithmetic. Every rule
is a pure boolean function of facts already computed upstream: no
market fetches, no clock, no model, no scoring. A rule either holds or
it does not, and one that does not ends the decision.

WHAT THIS IS *NOT*: A SECOND VETO ENGINE

core/veto_engine.py already owns market-condition vetoes -- session,
news, weekend, ADX/choppiness, ATR, wick reversal, volume, spread cap,
candle age. This module deliberately does not restate any of them.
Duplicating a threshold across two files is how the two drift and the
system starts disagreeing with itself, which is the exact failure
core/coherence.py exists to catch.

This layer answers a different question. The veto engine asks "are
market conditions acceptable right now?" This asks "is the trade we
just constructed internally coherent as an economic proposition?" --
a question about arithmetic, not about the market, and one nothing in
the pipeline currently asks.

WHY IT EXISTS

The replay found a trade the whole stack was willing to take that no
rule anywhere could refuse:

    stop 33.3 pips, spread 20.0 pips  ->  spread is 60% of the risk

The position must cross the spread twice, so the loss trigger sat
13 pips away while the win trigger sat 53. On 22.8% of decisions the
spread exceeded the ENTIRE stop, meaning the trade was resolved at a
loss by arithmetic before price moved at all. Measured across 1856
decisions:

    spread/stop 0.50-0.60   35.2% win     spread/stop 0.80+   18.6% win

Not one gate objected, because every gate was reading indicators and
none was reading the trade's own cost structure. That is precisely the
class of failure a symbolic layer is for: the model can be as
confident as it likes and the arithmetic still says no.

FAILING CLOSED

These are unbreakable risk parameters, so an unprovable rule is a
failed rule. If a fact a rule needs is missing, the rule reports
CANNOT_EVALUATE and the gate blocks -- consistent with this codebase's
governing invariant that missing or invalid data must never become
positive evidence. That is the opposite of the veto engine's
fail-OPEN behaviour on internal error, and deliberately so: a veto
failing open declines to add an objection, while a safety invariant
failing open asserts that the trade is safe, which it has not shown.
"""

from typing import Any, Callable, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# The trade must be able to outlive its own entry cost. At 0.33 the
# spread is a third of the risk; beyond that the cost structure, not
# the setup, decides the outcome. Kept here rather than in the shared
# config because it is this gate's own operating point -- the config's
# SL_MIN_SPREAD_MULTIPLE (3.0) is the sizing floor that should normally
# keep trades well clear of it, and this is the independent check that
# the sizing actually did its job.
MAX_SPREAD_TO_STOP = 0.34

# A stop closer than this to the broker's own minimum stop level is
# not a stop, it is a rounding error waiting to be rejected server-side.
MIN_ABSOLUTE_STOP_PIPS = 1.0


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and float("-inf") < f < float("inf") else None


class Rule:
    """
    One invariant.

    `check` returns True when the rule HOLDS. Returning None means the
    facts needed were absent, which fails closed.
    """

    __slots__ = ("name", "check", "explain", "requires")

    def __init__(self, name: str, requires: List[str],
                 check: Callable[[Dict[str, Any]], Optional[bool]],
                 explain: Callable[[Dict[str, Any]], str]):
        self.name = name
        self.requires = requires
        self.check = check
        self.explain = explain


def _spread_to_stop(f) -> Optional[bool]:
    spread, stop = _num(f.get("spread_pips")), _num(f.get("sl_pips"))
    if spread is None or stop is None or stop <= 0:
        return None
    return (spread / stop) <= MAX_SPREAD_TO_STOP


def _spread_to_stop_msg(f) -> str:
    spread, stop = _num(f.get("spread_pips")), _num(f.get("sl_pips"))
    if spread is None or stop is None or stop <= 0:
        return "spread or stop distance unavailable"
    r = spread / stop
    return (f"spread {spread:.1f}p is {r:.0%} of the {stop:.1f}p stop "
            f"(limit {MAX_SPREAD_TO_STOP:.0%}) -- the cost of entry, not the "
            f"setup, would decide this trade")


def _stop_positive(f) -> Optional[bool]:
    stop = _num(f.get("sl_pips"))
    return None if stop is None else stop >= MIN_ABSOLUTE_STOP_PIPS


def _target_beyond_cost(f) -> Optional[bool]:
    """
    The target must clear the round-trip spread by a real margin.

    A take-profit inside the spread is not a profit -- price reaching
    it still closes the position for less than it cost to open.
    """
    tp, spread = _num(f.get("tp_pips")), _num(f.get("spread_pips"))
    if tp is None or spread is None:
        return None
    return tp > spread


def _target_beyond_cost_msg(f) -> str:
    tp, spread = _num(f.get("tp_pips")), _num(f.get("spread_pips"))
    if tp is None or spread is None:
        return "target or spread unavailable"
    return (f"take-profit {tp:.1f}p does not clear the {spread:.1f}p spread -- "
            f"hitting the target would still close at a loss")


def _rr_computable(f) -> Optional[bool]:
    """
    R:R must be a measured fact, not an assumed one.

    core/risk_reward.py returns valid=False when the geometry is
    unsound; this refuses to proceed on that rather than reading
    `.ratio` (which is deliberately 0.0 in that case) as a number.
    """
    v = f.get("rr_valid")
    return None if v is None else bool(v)


def _direction_declared(f) -> Optional[bool]:
    d = f.get("direction")
    if not isinstance(d, str):
        return None
    return d.strip().upper() in ("BUY", "SELL")


def _lot_positive(f) -> Optional[bool]:
    lot = _num(f.get("lot_size"))
    return None if lot is None else lot > 0


RULES: List[Rule] = [
    Rule("direction_declared", ["direction"], _direction_declared,
         lambda f: f"direction {f.get('direction')!r} is neither BUY nor SELL"),
    Rule("stop_is_real", ["sl_pips"], _stop_positive,
         lambda f: (f"stop distance {f.get('sl_pips')} is below the "
                    f"{MIN_ABSOLUTE_STOP_PIPS}p minimum")),
    Rule("rr_is_measured", ["rr_valid"], _rr_computable,
         lambda f: "risk:reward could not be computed from the trade's own geometry"),
    Rule("spread_within_stop", ["spread_pips", "sl_pips"], _spread_to_stop,
         _spread_to_stop_msg),
    Rule("target_clears_spread", ["tp_pips", "spread_pips"], _target_beyond_cost,
         _target_beyond_cost_msg),
    Rule("lot_is_positive", ["lot_size"], _lot_positive,
         lambda f: f"lot size {f.get('lot_size')} is not a tradable quantity"),
]


def evaluate_symbolic_gate(facts: Dict[str, Any], *,
                           skip_rules: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Evaluate every invariant against one decision's facts.

    `facts` is engine_replay._capture()'s flat dict, or anything with
    the same keys -- spread_pips, sl_pips, tp_pips, rr_valid,
    direction, lot_size.

    Unlike the veto engine this does NOT short-circuit. Knowing a trade
    broke three invariants rather than one is the difference between a
    fixable setup and a broken configuration, and evaluating six
    boolean expressions costs nothing worth saving.

    Returns:
        passed        every rule held
        violations    [{rule, reason, evaluable}]
        evaluated     rules that produced a verdict
        blocked_by    first violated rule name, for one-line logging
    """
    skip = set(skip_rules or ())
    violations: List[Dict[str, Any]] = []
    evaluated = 0

    for rule in RULES:
        if rule.name in skip:
            continue
        try:
            verdict = rule.check(facts)
        except Exception as e:
            # A rule that crashes has not shown the trade to be safe.
            violations.append({"rule": rule.name, "evaluable": False,
                               "reason": f"rule raised {type(e).__name__}: {e}"})
            continue

        if verdict is None:
            missing = [k for k in rule.requires if facts.get(k) is None]
            violations.append({
                "rule": rule.name, "evaluable": False,
                "reason": (f"cannot evaluate -- missing {', '.join(missing) or 'inputs'}"
                           f" (a safety invariant that cannot be proven is not assumed)"),
            })
            continue

        evaluated += 1
        if not verdict:
            violations.append({"rule": rule.name, "evaluable": True,
                               "reason": rule.explain(facts)})

    passed = not violations
    return {
        "passed": passed,
        "violations": violations,
        "evaluated": evaluated,
        "rules_total": len(RULES) - len(skip),
        "blocked_by": violations[0]["rule"] if violations else None,
        "reason": ("all symbolic invariants hold" if passed
                   else "; ".join(v["reason"] for v in violations[:3])),
    }
