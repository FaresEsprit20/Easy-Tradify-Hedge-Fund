# ============================================================
# DIAGNOSIS NARRATIVE -- EVIDENCE-GROUNDED NATURAL LANGUAGE
# ============================================================
#
# WHAT THIS IS
# ------------
# A readable account of why one trade went the way it did, generated from the
# artifacts replay and root cause already produced. Every sentence it emits
# carries the evidence paths that license it.
#
# WHY IT IS TEMPLATED AND NOT GENERATED
# -------------------------------------
# The obvious approach is to hand the evidence bundle to a language model and
# ask for an explanation. That is precisely the wrong tool for this job. A
# generated explanation is fluent whether or not the evidence supports it, and
# the one thing this system cannot afford is a confident-sounding cause that
# nothing measured. Every clause below is emitted only when a specific field
# exists, and carries the path it came from, so a reader can check any claim
# against the record. Fluency is worth nothing here; traceability is the
# entire product.
#
# HEDGING IS CALIBRATED, NOT DECORATIVE
# -------------------------------------
# The verb changes with what the evidence actually establishes:
#
#   causal_status  UNPROVEN   -> "is consistent with", "was present when"
#   causal_status  SUPPORTED  -> "would have been avoided by" (a counterfactual
#                                on the recorded path shows a better result)
#   causal_status  PROVEN     -> "caused"
#
# Replay reports responsible_component_candidates -- candidates, not causes --
# and that distinction survives into the prose. A component being present at a
# failure is not evidence that it produced one, and writing "X caused the
# loss" when the evidence says "X was in the room" is how a diagnostic system
# starts manufacturing false confidence at scale.
#
# THE CALIBRATION POINT
# ---------------------
# When the system stated 78% and the trade lost, the narrative says explicitly
# that a single outcome cannot falsify a probability -- only a cohort can.
# This matters because the most tempting reading of any individual loss is
# "the model was wrong", and acting on that reading one trade at a time is how
# a calibrated model gets tuned into an uncalibrated one.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

NARRATIVE_VERSION = "1.0"

# How confidently a clause may be phrased, given what the evidence supports.
_CAUSAL_VERBS = {
    "PROVEN": "caused",
    "SUPPORTED": "would have been avoided by changing",
    "UNPROVEN": "is consistent with",
}


@dataclass
class Statement:
    """One claim, and the evidence that licenses it."""

    text: str
    evidence: List[str] = field(default_factory=list)
    confidence: str = "OBSERVED"

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "evidence": list(self.evidence),
                "confidence": self.confidence}


@dataclass
class Narrative:
    trade_id: Any = None
    symbol: Optional[str] = None
    version: str = NARRATIVE_VERSION
    headline: str = ""
    sections: Dict[str, List[Statement]] = field(default_factory=dict)
    unanswerable: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "headline": self.headline,
            "sections": {
                name: [s.to_dict() for s in statements]
                for name, statements in self.sections.items()
            },
            "unanswerable": list(self.unanswerable),
        }

    def to_text(self) -> str:
        lines = [self.headline, "=" * len(self.headline)] if self.headline else []
        for name, statements in self.sections.items():
            if not statements:
                continue
            lines.append("")
            lines.append(name.replace("_", " ").upper())
            for statement in statements:
                lines.append("  - " + statement.text)
                if statement.evidence:
                    lines.append("      evidence: " + ", ".join(statement.evidence))
        if self.unanswerable:
            lines.append("")
            lines.append("NOT ANSWERABLE FROM THE RECORD")
            for item in self.unanswerable:
                lines.append("  - " + item)
        return "\n".join(lines)


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _r(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "unknown" if number is None else ("%.*fR" % (digits, number))


def _outcome_statements(bundle: Mapping[str, Any]) -> List[Statement]:
    outcome = bundle.get("outcome") or {}
    reality = bundle.get("reality") or []
    statements: List[Statement] = []

    pnl = _number(outcome.get("pnl") or outcome.get("profit"))
    reason = outcome.get("exit_reason") or outcome.get("close_reason")
    if pnl is not None:
        verb = "lost" if pnl < 0 else "made"
        text = "The trade %s %.2f" % (verb, abs(pnl))
        if reason:
            text += " and closed on %s" % reason
        statements.append(Statement(text + ".", ["outcome.pnl", "outcome.exit_reason"]))

    if reality:
        returns = [_number(point.get("return_r")) for point in reality]
        returns = [value for value in returns if value is not None]
        if returns:
            peak = max(returns)
            trough = min(returns)
            statements.append(Statement(
                "It reached %s in its favour and %s against before closing, "
                "over %d recorded observations."
                % (_r(peak), _r(trough), len(reality)),
                ["replay.reality[].return_r"]))
            if peak >= 0.5 and returns[-1] < peak - 0.5:
                statements.append(Statement(
                    "It was in profit at %s and finished at %s, a %s round "
                    "trip. This is a give-back rather than an immediate "
                    "rejection, and the two have different remedies: a "
                    "give-back points at exit and trail policy, a rejection "
                    "points at entry."
                    % (_r(peak), _r(returns[-1]), _r(peak - returns[-1])),
                    ["replay.reality[].return_r"]))
    return statements


def _belief_statements(bundle: Mapping[str, Any]) -> List[Statement]:
    synthesis = bundle.get("market_synthesis") or {}
    statements: List[Statement] = []

    probability = _number(synthesis.get("probability_percent"))
    stars = synthesis.get("star_rating")
    if probability is not None:
        text = "At entry the system stated %.0f%% probability" % probability
        if stars is not None:
            text += " and a %s star rating" % stars
        statements.append(Statement(
            text + ".", ["market_synthesis.probability_percent"]))

        outcome = bundle.get("outcome") or {}
        pnl = _number(outcome.get("pnl") or outcome.get("profit"))
        if pnl is not None and pnl < 0 and probability >= 60:
            # The most tempting and most damaging reading of a single loss.
            statements.append(Statement(
                "A %.0f%% call that loses is not by itself evidence of a "
                "miscalibrated model: at %.0f%%, roughly %.0f of every 10 such "
                "trades are expected to lose. Calibration is a property of a "
                "COHORT, and can only be judged over one -- see the "
                "calibration model's reliability curve, never a single trade."
                % (probability, probability, round((100 - probability) / 10.0)),
                ["market_synthesis.probability_percent", "outcome.pnl"],
                confidence="METHODOLOGICAL"))

    regime = synthesis.get("market_regime")
    if regime:
        statements.append(Statement(
            "The regime was read as %s." % regime,
            ["market_synthesis.market_regime"]))
    return statements


def _context_statements(bundle: Mapping[str, Any],
                        limit: int = 6) -> List[Statement]:
    """
    What the decision-time snapshot actually said, named specifically.

    Reported rather than interpreted. "Zone grade was B" is a fact in the
    record; "the zone was too weak" is a conclusion no evidence here supports.
    """
    deterministic = bundle.get("deterministic") or {}
    statements: List[Statement] = []

    interesting = (
        ("account_info", "leverage", "Leverage was %s to 1."),
        ("session_analysis", "session", "The session was %s."),
        ("volatility_protection", "atr_pips", "ATR at entry was %s pips."),
        ("higher_timeframe", "aligned", "Higher-timeframe alignment was %s."),
        ("news_analysis", "event_risk", "News event risk was %s."),
        ("nested_zone", "nested", "Nested-zone confirmation was %s."),
    )
    for section, key, template in interesting:
        block = deterministic.get(section)
        if isinstance(block, Mapping) and block.get(key) is not None:
            statements.append(Statement(
                template % block.get(key),
                ["deterministic.%s.%s" % (section, key)]))

    vetos = deterministic.get("vetos")
    if isinstance(vetos, Mapping):
        raised = [name for name, value in vetos.items() if value]
        if raised:
            statements.append(Statement(
                "Vetos raised at entry: %s. The trade was taken anyway, which "
                "is the decision worth examining." % ", ".join(sorted(raised)),
                ["deterministic.vetos"]))
        else:
            statements.append(Statement(
                "No veto fired at entry.", ["deterministic.vetos"]))

    components = deterministic.get("components")
    if isinstance(components, Mapping):
        statements.append(Statement(
            "%d component analyzers were consulted and recorded: %s."
            % (len(components), ", ".join(sorted(components)[:limit])),
            ["deterministic.components"]))
    return statements


def _divergence_statements(bundle: Mapping[str, Any]) -> List[Statement]:
    replay = bundle.get("replay") or {}
    divergences = replay.get("divergences") or []
    statements: List[Statement] = []

    if not replay.get("replay_version"):
        return statements

    first = divergences[0] if divergences else None
    if first:
        where = first.get("timestamp") or ("observation %s" % first.get("index"))
        statements.append(Statement(
            "The first divergence between what was expected and what happened "
            "was %s, at %s." % (first.get("category") or "unspecified", where),
            ["replay.divergences[0]"]))
        expected, observed = first.get("expected"), first.get("observed")
        if expected is not None and observed is not None:
            statements.append(Statement(
                "Expected %s; observed %s." % (expected, observed),
                ["replay.divergences[0].expected",
                 "replay.divergences[0].observed"]))

    if len(divergences) > 1:
        kinds = [d.get("category") or "unspecified" for d in divergences]
        statements.append(Statement(
            "%d divergences were recorded in total (%s). The FIRST is the one "
            "with diagnostic value -- everything after it may be a consequence "
            "rather than a cause." % (len(divergences), ", ".join(kinds)),
            ["replay.divergences"]))
    return statements


def _attribution_statements(bundle: Mapping[str, Any]) -> List[Statement]:
    replay = bundle.get("replay") or {}
    attributions = replay.get("attribution") or []
    failure_class = replay.get("failure_class")
    statements: List[Statement] = []

    if failure_class:
        statements.append(Statement(
            "Replay classified the failure as %s." % failure_class,
            ["replay.failure_class"]))

    for item in attributions[:4]:
        target = item.get("target") or "unnamed component"
        status = str(item.get("causal_status") or "UNPROVEN").upper()
        verb = _CAUSAL_VERBS.get(status, _CAUSAL_VERBS["UNPROVEN"])
        text = "%s %s this outcome" % (target, verb)
        if status == "UNPROVEN":
            text += (" -- it was present at the failure, which is not evidence "
                     "that it produced one")
        statements.append(Statement(
            text + ".", ["replay.attribution[].target"],
            confidence=status))
    return statements


def _counterfactual_statements(bundle: Mapping[str, Any]) -> List[Statement]:
    """
    What would have happened under a different rule, on the SAME prices.

    Implementable and oracle branches are separated explicitly. A branch that
    needed to know the future is a bound on what was achievable, never a
    change anyone could have made -- and quoting the two together is how a
    backtest starts promising returns nobody can capture.
    """
    replay = bundle.get("replay") or {}
    branches = replay.get("counterfactuals") or []
    statements: List[Statement] = []
    if not branches:
        return statements

    scored = [b for b in branches if _number(b.get("return")) is not None]
    if not scored:
        return statements

    actual = next((b for b in scored if b.get("scenario_id") == "actual"), None)
    actual_r = _number(actual.get("return")) if actual else None

    implementable = [b for b in scored if b.get("implementable")
                     and b.get("scenario_id") != "actual"]
    if implementable:
        best = max(implementable, key=lambda b: _number(b.get("return")))
        best_r = _number(best.get("return"))
        if actual_r is not None and best_r is not None and best_r > actual_r:
            statements.append(Statement(
                "On the same recorded prices, '%s' would have returned %s "
                "against the actual %s -- a difference of %s. This is a rule "
                "that could have been applied in advance."
                % (best.get("scenario_id"), _r(best_r), _r(actual_r),
                   _r(best_r - actual_r)),
                ["replay.counterfactuals[].return"], confidence="SUPPORTED"))
        else:
            statements.append(Statement(
                "No implementable alternative beat the actual result on this "
                "path. The decision rule is not obviously where the loss came "
                "from.", ["replay.counterfactuals"], confidence="SUPPORTED"))

    oracle = [b for b in scored if not b.get("implementable")]
    if oracle:
        best = max(oracle, key=lambda b: _number(b.get("return")))
        statements.append(Statement(
            "The best hindsight-only branch ('%s') reached %s. That is a BOUND "
            "on what this path offered, not a change anyone could have made: "
            "it required knowing the future."
            % (best.get("scenario_id"), _r(best.get("return"))),
            ["replay.counterfactuals[].implementable"],
            confidence="ORACLE_BOUND"))
    return statements


def _next_step_statements(result: Any) -> List[Statement]:
    statements: List[Statement] = []

    # Rendered from the fields these records ACTUALLY carry. Reading for a
    # `proposal`/`description` key that no producer emits silently dropped
    # every recommendation, and printed requirements as bare identifiers --
    # "causal_validation" tells a reader nothing they did not already know.
    for requirement in (getattr(result, "validation_requirements", None) or [])[:5]:
        if not isinstance(requirement, Mapping):
            if requirement:
                statements.append(Statement(str(requirement),
                                            ["validation_requirements"]))
            continue
        name = str(requirement.get("requirement") or "").replace("_", " ")
        if not name:
            continue
        text = "Before acting on this: %s" % name
        status = requirement.get("status")
        if status:
            text += " (%s)" % status
        reason = requirement.get("reason")
        if reason:
            text += ". %s" % reason
        statements.append(Statement(text.rstrip(".") + ".",
                                    ["validation_requirements"]))

    for proposal in (getattr(result, "recommendations", None) or [])[:4]:
        if not isinstance(proposal, Mapping):
            continue
        kind = str(proposal.get("type") or "EXPERIMENT").replace("_", " ").lower()
        target = proposal.get("target") or "an unnamed component"
        text = "Proposed %s on %s" % (kind, target)
        reason = proposal.get("reason")
        if reason:
            text += ", because %s" % reason
        requires = proposal.get("requires") or []
        if requires:
            text += ". It may not ship until it passes: %s" % ", ".join(
                str(item).replace("_", " ") for item in requires)
        status = str(proposal.get("causal_status") or "UNPROVEN").upper()
        text += (". The attribution behind it is %s, so this is a hypothesis "
                 "to test, not a change to apply" % status)
        statements.append(Statement(text + ".", ["recommendations"],
                                    confidence="PROPOSAL"))
    return statements


def narrate(result: Any, bundle: Optional[Mapping[str, Any]] = None) -> Narrative:
    """
    Turn an analysis result plus its evidence bundle into grounded prose.

    `bundle` is the input the analyzer read. It is accepted separately because
    the result object keeps only what it could interpret, while the narrative
    wants the raw decision-time context too -- session, leverage, vetos, the
    component list -- so it can name specifics instead of speaking in
    subsystem abstractions.
    """
    bundle = dict(bundle or {})
    narrative = Narrative(
        trade_id=getattr(result, "trade_id", bundle.get("trade_id")),
        symbol=getattr(result, "symbol", bundle.get("symbol")),
    )

    replay = bundle.get("replay") or {}
    if not replay.get("replay_version"):
        narrative.headline = "Diagnosis unavailable: no replay artifact"
        narrative.sections["what_is_missing"] = [Statement(
            "Replay did not run for this trade, so there is no reconstruction "
            "to compare the decision against. No cause is offered, because "
            "any cause stated here would be invented rather than measured.",
            ["replay"])]
        narrative.unanswerable = [
            "why the trade moved as it did",
            "which component, if any, was implicated",
            "whether a different rule would have helped",
        ]
        return narrative

    outcome = bundle.get("outcome") or {}
    pnl = _number(outcome.get("pnl") or outcome.get("profit"))
    failure_class = replay.get("failure_class") or "UNCLASSIFIED"
    verdict = "loss" if (pnl is not None and pnl < 0) else "win"
    narrative.headline = "Trade %s (%s): %s, classified %s" % (
        narrative.trade_id, narrative.symbol or "unknown symbol",
        verdict, failure_class)

    narrative.sections["what_happened"] = _outcome_statements(bundle)
    narrative.sections["what_the_system_believed"] = _belief_statements(bundle)
    narrative.sections["decision_time_context"] = _context_statements(bundle)
    narrative.sections["where_it_diverged"] = _divergence_statements(bundle)
    narrative.sections["what_the_evidence_implicates"] = (
        _attribution_statements(bundle))
    narrative.sections["what_would_have_worked"] = (
        _counterfactual_statements(bundle))
    narrative.sections["what_to_test_next"] = _next_step_statements(result)

    # Stated rather than left to be inferred from absence.
    if not (replay.get("counterfactuals") or []):
        narrative.unanswerable.append(
            "whether any alternative rule would have done better -- no "
            "counterfactual branches were produced")
    if not bundle.get("gnn"):
        narrative.unanswerable.append(
            "what GNN contributed -- the trade carries no GNN state")
    return narrative


def narrate_trade(trade: Mapping[str, Any], bridge: Any = None) -> Narrative:
    """Stored trade straight to a narrative."""
    from .root_cause_adapter import to_analysis_input
    from .root_cause_analyzers import RootCauseAnalyzer

    bundle = to_analysis_input(trade, bridge)
    result = RootCauseAnalyzer().analyze(bundle)
    return narrate(result, bundle)


def get_status() -> Dict[str, Any]:
    return {
        "component": "diagnosis_narrative",
        "version": NARRATIVE_VERSION,
        "generated_by": "deterministic templates over measured evidence",
        "uses_language_model": False,
        "why_not": ("a generated explanation reads as fluent whether or not "
                    "the evidence supports it; every clause here is emitted "
                    "only when a specific field exists and carries its path"),
        "causal_vocabulary": dict(_CAUSAL_VERBS),
        "sections": [
            "what_happened", "what_the_system_believed",
            "decision_time_context", "where_it_diverged",
            "what_the_evidence_implicates", "what_would_have_worked",
            "what_to_test_next",
        ],
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the narrative is grounded, hedged, and refuses when it should.

    The load-bearing check is `refuses_without_replay`: a diagnostic that
    produces confident prose from an empty record is worse than one that
    produces nothing, because it is indistinguishable from a real finding.
    """
    report: Dict[str, Any] = {
        "component": "diagnosis_narrative", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        empty = narrate(type("R", (), {"trade_id": "x", "symbol": "Y"})(), {})
        checks["refuses_without_replay"] = bool(empty.unanswerable) and (
            "unavailable" in empty.headline.lower())

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; narration not exercised"
            return report


        # Supplied trades that nothing can decode mean the DATA PATH failed,
        # and this must not report "verified" on the strength of its own
        # synthetic invariants. Those invariants hold on any input -- that is
        # what makes them invariants, and what makes them useless as evidence
        # that the pipeline works. Same discipline as standard 19.
        if True:
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades)
            checks["usable_trades"] = usable
            if usable == 0:
                report["ok"] = False
                report["reason"] = (
                    "no supplied trade could be decoded; the module's own "
                    "invariants passed, which says nothing about the pipeline")
                return report

        narrative = narrate_trade(trades[0])
        checks["produces_headline"] = bool(narrative.headline)
        checks["produces_text"] = len(narrative.to_text()) > 100

        statements = [s for group in narrative.sections.values() for s in group]
        checks["statements"] = len(statements)
        # Every claim must carry its evidence, or the narrative is prose.
        checks["every_statement_has_evidence"] = all(
            statement.evidence for statement in statements)
        # No unhedged causal verb unless something proved it.
        unproven = [s for s in statements if s.confidence == "UNPROVEN"]
        checks["unproven_claims_are_hedged"] = all(
            "caused" not in s.text or "not evidence" in s.text
            for s in unproven)

        required = ("refuses_without_replay", "produces_headline",
                    "produces_text", "every_statement_has_evidence",
                    "unproven_claims_are_hedged")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "NARRATIVE_VERSION", "Narrative", "Statement", "narrate", "narrate_trade",
    "get_status", "self_check",
]
