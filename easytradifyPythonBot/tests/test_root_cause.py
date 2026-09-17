"""
Root cause: the adapter, the analyzer, and the narrative.

Before this file existed there were 1,082 lines of diagnostic machinery with
no test, no self_check and no endpoint -- and it did not work. Fed a stored
trade it produced 0 component evidence, no diagnosis and 0 recommendations,
because nothing built the evidence bundle it reads. It was not broken in a way
that raised; it was broken in a way that rendered a complete-looking report
saying nothing.

Two failure shapes get most of the attention here:

  * silent shape mismatches between a producer and a consumer -- a dict where
    a list was expected, `deterministic_features` where `deterministic` was
    expected -- each of which yields an empty, confident result;
  * causal overreach in the prose. A diagnostic that says "X caused this" on
    evidence that only shows "X was present" manufactures false confidence at
    scale, and is worse than one that says nothing.
"""

import pytest

from ai import diagnosis_narrative, root_cause_adapter
from ai.root_cause_analyzers import RootCauseAnalyzer
from ai.root_cause_trackers import RootCauseEvidenceTracker
from conftest import build_trade


@pytest.fixture
def losing_trade():
    return build_trade(ticket=9100, points=6, winning=False)


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

def test_stored_trade_produces_a_populated_bundle(losing_trade):
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    assert bundle["decision_snapshots"]
    assert bundle["deterministic"]
    assert bundle["replay"]["replay_version"]


def test_divergences_arrive_as_records_not_key_strings(losing_trade):
    """
    aireplay returns divergences as a dict keyed by kind. Read directly, it
    iterates as its KEY STRINGS, and the analyzer discards each one silently
    because a str is not a Mapping -- producing an analysis that looks
    complete and contains nothing.
    """
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    divergences = bundle["replay"]["divergences"]
    assert divergences
    assert all(isinstance(item, dict) for item in divergences)
    assert all(item.get("category") for item in divergences)


def test_earliest_alias_is_not_counted_as_its_own_divergence(losing_trade):
    """
    `earliest` points at whichever divergence fired first. Emitting it as a
    record double-counts one event, so a narrative would report five
    divergences where four occurred.
    """
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    ids = [d.get("divergence_id") for d in bundle["replay"]["divergences"]]
    assert "earliest" not in ids
    assert len(ids) == len(set(ids))


def test_divergences_are_ordered_by_when_they_happened(losing_trade):
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    indexes = [d.get("index") for d in bundle["replay"]["divergences"]
               if isinstance(d.get("index"), int)]
    assert indexes == sorted(indexes)


def test_attributions_are_contributing_never_primary(losing_trade):
    """
    Replay reports components PRESENT at a failure. Presence is not causation,
    and PRIMARY would assert a finding no counterfactual established.
    """
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    for item in bundle["replay"]["attribution"]:
        assert item["attribution_type"] != "PRIMARY"
        assert item["causal_status"] == "UNPROVEN"


def test_counterfactuals_are_historical_truth(losing_trade):
    bundle = root_cause_adapter.to_analysis_input(losing_trade)
    branches = bundle["replay"]["counterfactuals"]
    assert branches
    assert all(b["is_historical_truth"] for b in branches)


def test_unusable_trade_says_so_rather_than_returning_empty():
    """
    An empty bundle reads like "we looked and found nothing wrong". A trade
    that could not be decoded has to say that instead.
    """
    bundle = root_cause_adapter.to_analysis_input({"garbage": True})
    assert bundle.get("unusable")


def test_coverage_is_measured_not_claimed(losing_trade):
    coverage = root_cause_adapter.coverage(losing_trade)
    assert coverage["sections_populated"] >= 5
    assert coverage["replay_available"]
    assert coverage["deterministic_sections"]


# ---------------------------------------------------------------------------
# The analyzer
# ---------------------------------------------------------------------------

def test_analysis_now_finds_component_evidence(losing_trade):
    """
    Was 0 for every trade: the tracker read `deterministic` while the snapshot
    emitted `deterministic_features`. A key mismatch between a producer and a
    consumer is invisible unless something insists on checking.
    """
    result = root_cause_adapter.analyze_trade(losing_trade)
    assert len(result.component_evidence) > 10
    assert result.evidence
    assert result.diagnosis is not None


def test_analyzer_refuses_to_name_a_cause_without_replay():
    """The whole value of this module rests on this refusal."""
    result = RootCauseAnalyzer().analyze({"trade_id": "none"})
    assert result.diagnosis.primary_cause is None
    assert result.diagnosis.failure_class == "UNKNOWN"
    assert "Replay" in result.diagnosis.explanation


def test_tracker_accepts_both_deterministic_spellings():
    tracker = RootCauseEvidenceTracker()
    legacy = tracker.index_component_evidence(
        [{"snapshot_id": "a", "deterministic": {"smc": {"x": 1}}}])
    canonical = tracker.index_component_evidence(
        [{"snapshot_id": "b", "deterministic_features": {"smc": {"x": 1}}}])
    assert "smc" in legacy and "smc" in canonical


def test_tracker_invents_nothing_for_an_empty_snapshot():
    assert RootCauseEvidenceTracker().index_component_evidence(
        [{"snapshot_id": "c"}]) == {}


# ---------------------------------------------------------------------------
# The narrative
# ---------------------------------------------------------------------------

def test_every_statement_carries_its_evidence(losing_trade):
    """Prose without a citation is prose. The citation is the product."""
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    statements = [s for group in narrative.sections.values() for s in group]
    assert statements
    assert all(s.evidence for s in statements)


def test_unproven_attributions_are_hedged_not_asserted(losing_trade):
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    implicated = narrative.sections["what_the_evidence_implicates"]
    for statement in implicated:
        if statement.confidence == "UNPROVEN":
            assert "is consistent with" in statement.text
            assert "not evidence that it produced one" in statement.text


def test_narrative_refuses_without_replay():
    """Confident prose from an empty record is worse than no prose."""
    narrative = diagnosis_narrative.narrate(
        type("R", (), {"trade_id": "x", "symbol": "Y"})(), {})
    assert "unavailable" in narrative.headline.lower()
    assert narrative.unanswerable


def test_oracle_branches_are_labelled_as_bounds(losing_trade):
    """
    A branch that needed to know the future is a bound on what was
    achievable, never a change anyone could have made. Quoting the two
    together is how a backtest starts promising uncapturable returns.
    """
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    for statement in narrative.sections["what_would_have_worked"]:
        if statement.confidence == "ORACLE_BOUND":
            assert "required knowing the future" in statement.text


def test_a_single_loss_does_not_indict_the_probability(losing_trade):
    """
    The most tempting reading of any individual loss is "the model was
    wrong". Acting on that one trade at a time is how a calibrated model gets
    tuned into an uncalibrated one.
    """
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    beliefs = " ".join(
        s.text for s in narrative.sections["what_the_system_believed"])
    assert "COHORT" in beliefs


def test_narrative_names_what_it_cannot_answer(losing_trade):
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    assert isinstance(narrative.unanswerable, list)
    assert narrative.to_text()


def test_narrative_reports_specific_context_not_abstractions(losing_trade):
    """Leverage, session and vetos by name -- not "risk was elevated"."""
    narrative = diagnosis_narrative.narrate_trade(losing_trade)
    context = " ".join(
        s.text for s in narrative.sections["decision_time_context"])
    assert "Leverage" in context
