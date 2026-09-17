"""
Canonical Market Synthesis -- Phase 2 items 8-10.

The load-bearing tests are the three hard requirements: conflicts are
preserved rather than averaged (10.4), "unavailable" is distinct from "zero"
(10.7), and the same input reproduces the same synthesis (10.8). Plus the
prohibition that shapes the whole module: no aggregate score (10.1).
"""

import pytest

from ai.aireplay import extract_replay_records
from ai.market_synthesis import (
    HIERARCHY_QUESTIONS,
    Conflict,
    MarketSynthesis,
    Observation,
    Severity,
    Status,
    assess_uncertainty,
    build_hierarchy,
    detect_conflicts,
    get_status,
    self_check,
    synthesise,
    synthesise_trade,
    verify_reproducible,
)

from conftest import build_trade


def synth(mutate=None, ticket=555):
    trade = build_trade(ticket=ticket)
    if mutate:
        mutate(trade["analysis_at_open"])
    return synthesise_trade(extract_replay_records([trade])[0])


# ---------------------------------------------------------------------------
# 10.1 -- no aggregate score
# ---------------------------------------------------------------------------

def test_synthesis_produces_no_score():
    """
    The prohibition that shapes the module. +20 and -20 cancel, and once they
    have, nothing downstream can recover that structure and liquidity
    disagreed.
    """
    payload = synth().to_dict()
    for banned in ("score", "probability", "direction", "net", "total",
                   "weighted_score", "confidence"):
        assert banned not in payload, banned


def test_status_declares_the_prohibition():
    status = get_status()
    assert status["produces_score"] is False
    assert status["produces_direction"] is False
    assert "10.1" in status["why_no_score"] or "prohibits" in status["why_no_score"]


def test_synthesis_does_not_recompute_market_intelligence():
    """Phase 2 items 1-7 exist in core/; readme 26.1 requires reuse."""
    status = get_status()
    assert status["recomputes_market_intelligence"] is False
    assert "core.vwap" in status["reads_from"]
    assert "core.liquidity_events" in status["reads_from"]


# ---------------------------------------------------------------------------
# 10.2 -- structured named sub-states
# ---------------------------------------------------------------------------

def test_populates_the_named_dimensions():
    synthesis = synth()
    usable = {o.name for o in synthesis.observations if o.usable}
    for dimension in ("structure", "liquidity", "value", "participation",
                      "momentum", "volatility", "sessions"):
        assert dimension in usable, dimension


def test_dimensions_are_separate_fields_not_one_blob():
    synthesis = synth()
    assert synthesis.structural_state
    assert synthesis.value_state
    assert synthesis.participation_state
    assert synthesis.structural_state != synthesis.value_state


# ---------------------------------------------------------------------------
# 10.3 -- hierarchical reasoning
# ---------------------------------------------------------------------------

def test_hierarchy_asks_all_eight_questions_in_order():
    hierarchy = synth().hierarchy
    assert len(hierarchy) == len(HIERARCHY_QUESTIONS) == 8
    assert [step["step"] for step in hierarchy] == list(range(1, 9))
    assert [step["key"] for step in hierarchy] == [k for k, _ in HIERARCHY_QUESTIONS]


def test_hierarchy_answers_are_states_not_numbers():
    """Readme 10.3: these must not be 'reduced to arbitrary points'."""
    for step in synth().hierarchy:
        assert not isinstance(step["answer"], (int, float)) or isinstance(
            step["answer"], bool), step


def test_unanswerable_steps_are_marked_not_guessed():
    sparse = synth(lambda a: a.clear())
    assert all(step["answered"] is False for step in sparse.hierarchy[:7])


def test_uncertainty_is_the_final_question():
    hierarchy = synth().hierarchy
    assert hierarchy[-1]["key"] == "residual_uncertainty"
    assert hierarchy[-1]["answer"] in ("LOW", "MEDIUM", "HIGH")


# ---------------------------------------------------------------------------
# 10.4 -- explicit conflict representation
# ---------------------------------------------------------------------------

def test_opposing_timeframes_produce_a_conflict():
    """The headline case in readme 10.4."""
    synthesis = synth(lambda a: a["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    assert synthesis.multi_timeframe["alignment"] == "CONFLICTING"

    conflicts = [c for c in synthesis.conflicts if c.right == "higher_timeframe"]
    assert conflicts
    assert conflicts[0].severity is Severity.HIGH
    assert conflicts[0].left_reading == "BULLISH"
    assert conflicts[0].right_reading == "BEARISH"


def test_conflicts_are_preserved_not_averaged():
    """
    A conflict must survive as a structured fact naming both sides. Netting
    it to a number is the failure readme 10.4 exists to prevent.
    """
    synthesis = synth(lambda a: a["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    payload = synthesis.to_dict()

    assert payload["conflicts"]
    conflict = payload["conflicts"][0]
    for key in ("left", "left_reading", "right", "right_reading",
                "description", "severity"):
        assert key in conflict, key


def test_aligned_timeframes_produce_no_conflict():
    """Guards against a detector that fires on everything."""
    synthesis = synth()
    assert synthesis.multi_timeframe["alignment"] == "ALIGNED"
    assert not [c for c in synthesis.conflicts if c.right == "higher_timeframe"]


def test_bias_is_read_from_inconsistently_named_keys():
    """
    Regression: `_bias_of` matched exact key names, so `h1_trend` was missed
    and higher-timeframe conflict detection never fired at all -- the most
    valuable conflict the spec asks for, silently disabled.
    """
    from ai.market_synthesis import _bias_of
    assert _bias_of({"h1_trend": "BEARISH"}) == "BEARISH"
    assert _bias_of({"structure": "BULLISH"}) == "BULLISH"
    assert _bias_of({"trend_bias": "RANGING"}) == "NEUTRAL"
    assert _bias_of({"unrelated": "BULLISH"}) is None


def test_unparticipated_structure_is_flagged():
    synthesis = MarketSynthesis(
        structural_state={"structure": "BULLISH"},
        participation_state={"state": "UNPARTICIPATED"},
    )
    conflicts = detect_conflicts(synthesis)
    assert any(c.right == "participation" for c in conflicts)


def test_sweep_against_structure_is_high_severity():
    synthesis = MarketSynthesis(
        structural_state={"structure": "BULLISH"},
        liquidity_state={"sweep_direction": "SELL_SIDE"},
    )
    conflicts = [c for c in detect_conflicts(synthesis) if c.right == "liquidity"]
    assert conflicts and conflicts[0].severity is Severity.HIGH


# ---------------------------------------------------------------------------
# 10.7 -- missing vs stale vs zero
# ---------------------------------------------------------------------------

def test_absent_dimension_is_unavailable_not_neutral():
    """
    Readme 10.7: a missing GNN result must not silently become GNN = neutral.
    Neutral is a claim about the market; unavailable is a claim about the
    system, and conflating them lets an outage read as evidence.
    """
    synthesis = synth(lambda a: a.pop("vwap", None))
    value = next(o for o in synthesis.observations if o.name == "value")
    assert value.status is Status.UNAVAILABLE
    assert value.value is None
    assert value.reason


def test_empty_section_is_distinguished_from_missing_section():
    synthesis = synth(lambda a: a.update({"vwap": {}}))
    value = next(o for o in synthesis.observations if o.name == "value")
    assert value.status is Status.UNAVAILABLE
    assert "empty" in value.reason


def test_a_zero_value_is_not_treated_as_missing():
    """value = 0 is an observation; absence is not."""
    synthesis = synth(lambda a: a.update({"vwap": {"vwap": 0.0, "slope": 0.0}}))
    value = next(o for o in synthesis.observations if o.name == "value")
    assert value.status is Status.OK
    assert value.value == {"vwap": 0.0, "slope": 0.0}


def test_observations_carry_the_availability_contract():
    for observation in synth().observations:
        for attribute in ("status", "source", "timestamp", "available_at",
                          "freshness", "quality"):
            assert hasattr(observation, attribute), attribute


def test_unavailable_inputs_are_reported():
    synthesis = synth(lambda a: [a.pop(k, None) for k in ("vwap", "rvam")])
    unavailable = synthesis.unavailable_inputs()
    assert "value" in unavailable and "participation" in unavailable
    assert synthesis.uncertainty["coverage"] < 1.0


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------

def test_high_severity_conflict_raises_uncertainty():
    synthesis = synth(lambda a: a["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    assert synthesis.uncertainty["level"] == "HIGH"
    assert synthesis.uncertainty["high_severity_conflicts"] >= 1


def test_missing_data_raises_uncertainty_separately_from_conflict():
    """
    They call for different responses: a conflicted-but-complete picture is a
    reason to wait; a missing one is a reason to fix the pipeline.
    """
    synthesis = synth(lambda a: a.clear())
    assert synthesis.uncertainty["level"] == "HIGH"
    assert synthesis.uncertainty["conflict_count"] == 0
    assert synthesis.uncertainty["unavailable_inputs"]


def test_uncertainty_states_its_reasons():
    synthesis = synth(lambda a: a["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    assert synthesis.uncertainty["reasons"]


def test_clean_complete_state_is_low_uncertainty():
    assert synth().uncertainty["level"] == "LOW"


# ---------------------------------------------------------------------------
# 10.8 -- replay determinism
# ---------------------------------------------------------------------------

def test_same_input_reproduces_the_same_synthesis():
    record = extract_replay_records([build_trade(ticket=555)])[0]
    report = verify_reproducible(synthesise_trade(record), synthesise_trade(record))
    assert report["reproducible"] is True
    assert report["differing_dimensions"] == []
    assert report["conflicts_match"] is True


def test_hash_ignores_wall_clock_metadata():
    """
    `synthesised_at` is when this ran, not what it concluded. Including it
    would report nondeterminism on every record -- the same mistake that made
    the Phase 1 immutability check fire on every trade.
    """
    record = extract_replay_records([build_trade(ticket=555)])[0]
    first, second = synthesise_trade(record), synthesise_trade(record)

    # Force the timestamps apart rather than relying on clock resolution, so
    # this tests the property instead of accidentally passing.
    first.provenance.synthesised_at = "2026-01-01T00:00:00Z"
    second.provenance.synthesised_at = "2099-12-31T23:59:59Z"

    assert first.provenance.synthesised_at != second.provenance.synthesised_at
    assert first.synthesis_hash() == second.synthesis_hash()


def test_different_inputs_produce_different_hashes():
    """Guards against a hash that ignores content."""
    a = synth()
    b = synth(lambda x: x["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    assert a.synthesis_hash() != b.synthesis_hash()


def test_divergence_names_the_dimension():
    """'Synthesis is nondeterministic' is not actionable; naming it is."""
    a = synth()
    b = synth(lambda x: x["higher_timeframe"].update({"h1_trend": "BEARISH"}))
    report = verify_reproducible(a, b)
    assert report["reproducible"] is False
    assert "multi_timeframe" in report["differing_dimensions"]


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_reports_all_phase2_requirements():
    implements = get_status()["implements"]
    assert all(implements.values())
    for requirement in ("canonical_synthesis", "hierarchical_reasoning",
                        "explicit_conflicts", "missing_vs_stale_vs_zero",
                        "replay_determinism"):
        assert requirement in implements


def test_self_check_passes(trades):
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["reproducible"] is True
    assert report["checks"]["produces_no_score"] is True
    assert report["checks"]["dimensions_populated"]


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["records"] == 0


def test_synthesise_handles_an_empty_decision_state():
    synthesis = synthesise({}, symbol="EURUSD")
    assert synthesis.symbol == "EURUSD"
    assert len(synthesis.unavailable_inputs()) == len(synthesis.observations)
    assert synthesis.uncertainty["level"] == "HIGH"
