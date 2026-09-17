# ============================================================
# TRADE QUALITY -- PHASE 2 ITEM 7
# ============================================================
#
# Readme 26.20 is unusually specific about what this must NOT be:
#
#     Do not recreate a giant arbitrary point system.
#     ...
#     It is not:
#         RSI = +10 / VWAP = +10 / GNN = +20 / RL = +30
#     because arbitrary points create false precision and encourage
#     redundant voting.
#
# So there is no score here. There is an EXPECTED RETURN, computed from
# quantities that mean something, plus a set of conditions that can withhold
# it. Those are different kinds of object and they are kept apart.
#
# HOW THE ASSESSMENT IS ACTUALLY REACHED
# --------------------------------------
# One equation carries the whole verdict:
#
#     E[R] = P(success) x reward_R - (1 - P(success)) x 1R
#
# That is not a weighting scheme; it is the definition of expectancy, and it
# is the only quantity that decides whether a trade is worth taking. Direction
# entropy in this system measured 1.0000, so P hovers near a coin flip and the
# whole lever is the reward leg -- which is exactly why a points system that
# lets six indicators vote a trade up is worse than useless here. It would
# manufacture confidence about the term that cannot move.
#
# Every other dimension is a GATE, not an addend. A gate can withhold the
# verdict or flag a concern; none of them can add points to a trade that has
# no expectancy. Redundant voting is impossible by construction because there
# is nothing to vote on.
#
# CALIBRATION IS A PRECONDITION, NOT A DIMENSION
# ----------------------------------------------
# E[R] is only as good as P. If the calibration model reports the stated
# probability carries no ranking information, then E[R] computed from it is
# arithmetic on noise, and this says so and withholds the verdict rather than
# reporting a confident number. That refusal is the single most valuable thing
# this module does.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

TRADE_QUALITY_VERSION = "1.0"

# Below this expected return a trade is not worth its spread. Stated once,
# here, rather than distributed across a scoring table.
MIN_ACCEPTABLE_EXPECTED_R = 0.10
MARGINAL_EXPECTED_R = 0.0


@dataclass
class Dimension:
    """
    One validated quantity, and whether it was actually available.

    `available` is separate from `value` because a missing dimension and a
    dimension measured at zero are different facts, and every scoring system
    that conflates them ends up rewarding absent data.
    """

    name: str
    value: Any = None
    available: bool = False
    source: str = ""
    concern: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeQuality:
    trade_id: Optional[str] = None
    symbol: Optional[str] = None
    version: str = TRADE_QUALITY_VERSION

    expected_r: Optional[float] = None
    probability: Optional[float] = None
    reward_r: Optional[float] = None

    verdict: str = "UNKNOWN"
    verdict_reason: str = ""
    withheld_because: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    dimensions: List[Dimension] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["dimensions"] = [d.to_dict() for d in self.dimensions]
        payload["dimensions_available"] = sum(
            1 for d in self.dimensions if d.available)
        payload["dimensions_total"] = len(self.dimensions)
        payload["is_a_point_score"] = False
        return payload


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def expected_return_r(probability: float, reward_r: float) -> float:
    """
    E[R] = p x reward - (1 - p) x 1R.

    The loss leg is fixed at 1R by definition: R IS the loss when the stop is
    hit. Anything else would be measuring the trade against a risk it never
    took.
    """
    return probability * reward_r - (1.0 - probability) * 1.0


def _collect_dimensions(bundle: Mapping[str, Any]) -> List[Dimension]:
    """
    The readme's list of validated quantities, each with its availability.

    Reported, never summed. Their job is to explain and to gate, and a reader
    who wants to know why a trade was flagged should be able to see the field
    that flagged it.
    """
    synthesis = bundle.get("market_synthesis") or {}
    deterministic = bundle.get("deterministic") or {}
    execution = bundle.get("execution") or {}
    risk = bundle.get("risk_gate") or {}

    def section(name: str) -> Mapping[str, Any]:
        value = deterministic.get(name)
        return value if isinstance(value, Mapping) else {}

    dimensions = [
        Dimension("probability", _number(synthesis.get("probability_percent")),
                  synthesis.get("probability_percent") is not None,
                  "market_synthesis.probability_percent"),
        Dimension("reward_r", _number(risk.get("risk_reward_ratio")),
                  risk.get("risk_reward_ratio") is not None,
                  "risk_gate.risk_reward_ratio"),
        Dimension("regime", synthesis.get("market_regime"),
                  bool(synthesis.get("market_regime")),
                  "market_synthesis.market_regime"),
        Dimension("gnn_context", bundle.get("gnn") or None,
                  bool(bundle.get("gnn")), "gnn"),
        Dimension("failure_probability",
                  (bundle.get("non_rl") or {}).get("failure_probability"),
                  (bundle.get("non_rl") or {}).get(
                      "failure_probability") is not None,
                  "non_rl.failure_probability"),
        Dimension("liquidity_quality", section("liquidity_events") or None,
                  bool(section("liquidity_events")), "deterministic.liquidity_events"),
        Dimension("microstructure", section("micro_structure") or None,
                  bool(section("micro_structure")), "deterministic.micro_structure"),
        Dimension("execution_quality",
                  execution.get("spread_at_entry"),
                  execution.get("spread_at_entry") is not None,
                  "execution.spread_at_entry"),
        Dimension("news_risk", section("news_analysis").get("event_risk"),
                  section("news_analysis").get("event_risk") is not None,
                  "deterministic.news_analysis.event_risk"),
        Dimension("vetos", section("vetos") or None,
                  bool(section("vetos")), "deterministic.vetos"),
    ]

    # Concerns are attached to the dimension that raised them, so a flag can
    # always be traced back to a field rather than appearing from nowhere.
    for dimension in dimensions:
        if dimension.name == "news_risk" and str(dimension.value).upper() in (
                "HIGH", "EXTREME"):
            dimension.concern = "elevated news event risk at entry"
        if dimension.name == "vetos" and isinstance(dimension.value, Mapping):
            raised = [k for k, v in dimension.value.items() if v]
            if raised:
                dimension.concern = "veto raised: " + ", ".join(sorted(raised))
        if dimension.name == "failure_probability":
            value = _number(dimension.value)
            if value is not None and value >= 0.6:
                dimension.concern = "model-estimated failure probability %.2f" % value
    return dimensions


def assess(bundle: Mapping[str, Any],
           probability_is_informative: Optional[bool] = None) -> TradeQuality:
    """
    Aggregate validated quantities into an expectancy, or refuse to.

    `probability_is_informative` comes from the calibration model's
    `diagnose_input`. When it is False the verdict is withheld: E[R] computed
    from a probability that carries no ranking information is arithmetic on
    noise, and a confident number there is worse than no number.
    """
    quality = TradeQuality(
        trade_id=bundle.get("trade_id"),
        symbol=bundle.get("symbol"),
        dimensions=_collect_dimensions(bundle),
    )
    by_name = {d.name: d for d in quality.dimensions}

    probability = _number(by_name["probability"].value)
    if probability is not None and probability > 1.0:
        probability = probability / 100.0
    reward = _number(by_name["reward_r"].value)

    quality.probability = probability
    quality.reward_r = reward
    quality.concerns = [d.concern for d in quality.dimensions if d.concern]

    if probability is None:
        quality.withheld_because.append(
            "no stated probability; expectancy cannot be computed")
    elif not 0.0 < probability < 1.0:
        quality.withheld_because.append(
            "stated probability %.4f is outside (0, 1)" % probability)
    if reward is None or reward <= 0:
        quality.withheld_because.append(
            "no positive reward-to-risk ratio; expectancy cannot be computed")
    if probability_is_informative is False:
        quality.withheld_because.append(
            "calibration reports the stated probability carries no ranking "
            "information, so any expectancy computed from it is arithmetic "
            "on noise")

    if quality.withheld_because:
        quality.verdict = "UNKNOWN"
        quality.verdict_reason = "; ".join(quality.withheld_because)
        return quality

    quality.expected_r = round(expected_return_r(probability, reward), 4)

    # A hard veto outranks the arithmetic. This is the one place a dimension
    # overrides E[R], and it can only ever REFUSE a trade -- never promote one.
    veto = by_name["vetos"].concern
    if veto:
        quality.verdict = "UNACCEPTABLE"
        quality.verdict_reason = (
            "%s (expectancy was %.4fR, but a veto is not outvoted by it)"
            % (veto, quality.expected_r))
        return quality

    if quality.expected_r >= MIN_ACCEPTABLE_EXPECTED_R:
        quality.verdict = "ACCEPTABLE"
    elif quality.expected_r > MARGINAL_EXPECTED_R:
        quality.verdict = "MARGINAL"
    else:
        quality.verdict = "UNACCEPTABLE"
    quality.verdict_reason = (
        "expected return %.4fR at p=%.3f and reward %.2fR"
        % (quality.expected_r, probability, reward))
    return quality


def assess_trade(trade: Mapping[str, Any], bridge: Any = None,
                 probability_is_informative: Optional[bool] = None
                 ) -> TradeQuality:
    """Stored trade straight to a quality assessment, via the replay adapter."""
    from .root_cause_adapter import to_analysis_input

    bundle = to_analysis_input(trade, bridge, include_counterfactuals=False)
    return assess(bundle, probability_is_informative)


def get_status() -> Dict[str, Any]:
    return {
        "component": "trade_quality",
        "version": TRADE_QUALITY_VERSION,
        "phase": "2 - item 7 (Trade Quality)",
        "is_a_point_score": False,
        "why_not": ("readme 26.20 forbids it: arbitrary points create false "
                    "precision and encourage redundant voting"),
        "decided_by": "E[R] = p x reward_R - (1 - p) x 1R",
        "gates_can_only_refuse": True,
        "withholds_when_uncalibrated": True,
        "thresholds": {
            "min_acceptable_expected_r": MIN_ACCEPTABLE_EXPECTED_R,
            "marginal_expected_r": MARGINAL_EXPECTED_R,
        },
        "dimensions": [d.name for d in _collect_dimensions({})],
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the expectancy is right, gates only refuse, and calibration gates it.

    `no_dimension_can_promote` is the load-bearing check: it is the property
    readme 26.20 actually demands, and the one a points system violates.
    """
    report: Dict[str, Any] = {
        "component": "trade_quality", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        # The arithmetic, at values with known answers.
        checks["expectancy_is_correct"] = (
            abs(expected_return_r(0.5, 3.0) - 1.0) < 1e-9
            and abs(expected_return_r(0.5, 1.0) - 0.0) < 1e-9
            and abs(expected_return_r(0.4, 2.0) - 0.2) < 1e-9)

        good = {"market_synthesis": {"probability_percent": 50},
                "risk_gate": {"risk_reward_ratio": 3.0}}
        assessed = assess(good)
        checks["acceptable_when_expectancy_positive"] = (
            assessed.verdict == "ACCEPTABLE" and assessed.expected_r == 1.0)

        poor = {"market_synthesis": {"probability_percent": 40},
                "risk_gate": {"risk_reward_ratio": 1.0}}
        checks["unacceptable_when_expectancy_negative"] = (
            assess(poor).verdict == "UNACCEPTABLE")

        # Missing inputs must withhold, not default.
        checks["withholds_without_probability"] = (
            assess({"risk_gate": {"risk_reward_ratio": 2.0}}).verdict == "UNKNOWN")
        checks["withholds_without_reward"] = (
            assess({"market_synthesis": {"probability_percent": 60}}).verdict
            == "UNKNOWN")

        # Calibration precondition.
        uncalibrated = assess(good, probability_is_informative=False)
        checks["withholds_when_uncalibrated"] = (
            uncalibrated.verdict == "UNKNOWN"
            and any("noise" in reason for reason in uncalibrated.withheld_because))

        # A veto refuses a good trade...
        vetoed = assess({**good, "deterministic": {"vetos": {"news": True}}})
        checks["veto_can_refuse"] = vetoed.verdict == "UNACCEPTABLE"

        # ...but nothing can promote a bad one. This is the property that
        # separates an aggregation layer from a point system.
        stacked = assess({
            **poor,
            "gnn": {"gnn_influence": 0.9},
            "non_rl": {"failure_probability": 0.01},
            "deterministic": {
                "liquidity_events": {"quality": "EXCELLENT"},
                "micro_structure": {"state": "PERFECT"},
                "news_analysis": {"event_risk": "NONE"},
            },
        })
        checks["no_dimension_can_promote"] = stacked.verdict == "UNACCEPTABLE"
        checks["never_reports_a_score"] = (
            "score" not in assessed.to_dict()
            and assessed.to_dict()["is_a_point_score"] is False)

        # Availability is reported, not inferred from a zero.
        checks["availability_is_explicit"] = (
            assess({}).to_dict()["dimensions_available"] == 0)

        trades = list(trades or [])
        checks["trades_in"] = len(trades)

        # Supplied trades that nothing can decode mean the DATA PATH failed,
        # and this must not report "verified" on the strength of its own
        # synthetic invariants. Those invariants hold on any input -- that is
        # what makes them invariants, and what makes them useless as evidence
        # that the pipeline works. Same discipline as standard 19.
        if trades:
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades)
            checks["usable_trades"] = usable
            if usable == 0:
                report["ok"] = False
                report["reason"] = (
                    "no supplied trade could be decoded; the module's own "
                    "invariants passed, which says nothing about the pipeline")
                return report

        if trades:
            assessed_trade = assess_trade(trades[0])
            checks["assesses_a_stored_trade"] = (
                assessed_trade.verdict in
                ("ACCEPTABLE", "MARGINAL", "UNACCEPTABLE", "UNKNOWN"))
            checks["dimensions_populated"] = sum(
                1 for d in assessed_trade.dimensions if d.available)

        required = [k for k in checks
                    if k not in ("trades_in", "dimensions_populated")]
        report["ok"] = all(bool(checks[key]) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "TRADE_QUALITY_VERSION", "MIN_ACCEPTABLE_EXPECTED_R", "Dimension",
    "TradeQuality", "expected_return_r", "assess", "assess_trade",
    "get_status", "self_check",
]
