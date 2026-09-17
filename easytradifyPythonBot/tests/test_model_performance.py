"""
Model performance: scorecards, drift, and the ensemble question.

Every model in this package could report whether it was FITTED; none could
report whether it was RIGHT once a trade settled. A model that trains
successfully and predicts badly looked identical to a good one from every
status endpoint in the system.

The metric is expectancy in R, never accuracy. A model right 70% of the time
taking +0.3R wins and -1.0R losses loses money; direction entropy here was
measured at 1.0000, so any metric rewarding "right" over "right when it pays"
selects for noise. Several tests below exist only to keep that from drifting
back.
"""

import tempfile

import pytest

from ai.model_governance import GovernanceStore
from ai.model_performance import (MIN_RECORDS_FOR_VERDICT, PerformanceTracker,
                                  PredictionRecord, brier_score, expectancy)


@pytest.fixture
def tracker():
    with tempfile.TemporaryDirectory() as directory:
        yield PerformanceTracker(GovernanceStore(directory))


def _fill(tracker, model, count, realized_r, outcome, **extra):
    for index in range(count):
        tracker.record(model, "%s-%d" % (model, index),
                       realized_r=realized_r, outcome=outcome, **extra)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_thin_sample_gets_no_verdict(tracker):
    _fill(tracker, "thin", 5, 3.0, 1)
    card = tracker.scorecard("thin")
    assert card["verdict"] == "INSUFFICIENT_DATA"
    assert str(MIN_RECORDS_FOR_VERDICT) in card["verdict_reason"]


def test_a_losing_model_is_reported_as_losing(tracker):
    _fill(tracker, "loser", 80, -1.0, 0)
    card = tracker.scorecard("loser")
    assert card["verdict"] == "NEGATIVE"
    assert card["expectancy_r"] == -1.0


def test_zero_variance_is_strong_evidence_not_unmeasurable(tracker):
    """
    A model returning exactly -1.0R on eighty consecutive trades has no
    sampling error to speak of. The first version of this branch called that
    UNMEASURABLE -- reporting the most clear-cut loser in the system as
    unknowable.
    """
    _fill(tracker, "constant", 60, -1.0, 0)
    assert tracker.scorecard("constant")["verdict"] == "NEGATIVE"
    _fill(tracker, "winner", 60, 2.0, 1)
    assert tracker.scorecard("winner")["verdict"] == "POSITIVE"


def test_a_coin_flip_is_not_positive(tracker):
    for index in range(200):
        tracker.record("noise", "n%d" % index,
                       realized_r=(1.0 if index % 2 else -1.0),
                       outcome=index % 2)
    assert tracker.scorecard("noise")["verdict"] != "POSITIVE"


def test_high_accuracy_with_negative_expectancy_is_not_positive(tracker):
    """
    The exact case accuracy hides: right 70% of the time and losing money.
    """
    for index in range(200):
        wins = index % 10 < 7
        tracker.record("accurate_loser", "a%d" % index,
                       realized_r=(0.3 if wins else -1.0),
                       outcome=1 if wins else 0)
    card = tracker.scorecard("accurate_loser")
    assert card["win_rate"] > 0.65
    assert card["expectancy_r"] < 0
    assert card["verdict"] == "NEGATIVE"


def test_brier_is_absent_when_no_probability_was_stated(tracker):
    _fill(tracker, "silent", 40, 1.0, 1)
    assert tracker.scorecard("silent")["brier"] is None


def test_brier_is_computed_when_probabilities_exist(tracker):
    for index in range(40):
        tracker.record("stated", "s%d" % index, probability=70,
                       realized_r=1.0, outcome=1)
    assert tracker.scorecard("stated")["brier"] is not None


def test_expectancy_of_nothing_is_none_not_zero():
    """Zero is a measurement. Nothing measured is not zero."""
    assert expectancy([]) is None
    assert brier_score([]) is None
    assert expectancy([PredictionRecord("m", "t")]) is None


def test_unsettled_records_are_counted_separately(tracker):
    tracker.record("mixed", "open-1", prediction="ENTER")
    _fill(tracker, "mixed", 10, 1.0, 1)
    card = tracker.scorecard("mixed")
    assert card["unsettled"] == 1
    assert card["settled"] == 10


# ---------------------------------------------------------------------------
# Temporal validity
# ---------------------------------------------------------------------------

def test_a_prediction_must_precede_its_outcome():
    backwards = PredictionRecord("m", "t", predicted_at="2026-02-01",
                                 settled_at="2026-01-01", outcome=1)
    assert not backwards.temporally_valid
    forwards = PredictionRecord("m", "t", predicted_at="2026-01-01",
                                settled_at="2026-02-01", outcome=1)
    assert forwards.temporally_valid


def test_missing_timestamps_are_not_treated_as_valid():
    assert not PredictionRecord("m", "t", outcome=1).temporally_valid


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------

def test_drift_refuses_on_thin_history(tracker):
    _fill(tracker, "short", 20, 1.0, 1)
    assert tracker.drift("short", window=50)["drifted"] is None


def test_drift_detects_a_real_shift(tracker):
    _fill(tracker, "shift", 60, 1.0, 1)
    for index in range(60):
        tracker.record("shift", "late-%d" % index, realized_r=-1.0, outcome=0)
    report = tracker.drift("shift", window=50)
    assert report["drifted"] is True
    assert report["delta_r"] < 0


def test_stable_performance_is_not_drift(tracker):
    """A difference inside two standard errors is sampling, not drift."""
    for index in range(200):
        tracker.record("stable", "s%d" % index,
                       realized_r=(1.0 if index % 2 else -1.0),
                       outcome=index % 2)
    assert tracker.drift("stable", window=50)["drifted"] is False


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------

def test_agreement_counts_one_outcome_per_trade(tracker):
    """
    A trade with six models attached must not count six times; doing so
    inflates every sample size sixfold and makes noise look significant.
    """
    for index in range(40):
        for model in ("a", "b", "c"):
            tracker.record(model, "shared-%d" % index, prediction="ENTER",
                           realized_r=1.0, outcome=1)
    report = tracker.agreement(["a", "b", "c"])
    assert report["unanimous"]["trades"] == 40
    assert report["trades_compared"] == 40


def test_agreement_needs_both_arms_before_it_will_conclude(tracker):
    for index in range(40):
        for model in ("a", "b"):
            tracker.record(model, "u-%d" % index, prediction="ENTER",
                           realized_r=1.0, outcome=1)
    assert tracker.agreement(["a", "b"])["verdict"] == "INSUFFICIENT_DATA"


def test_agreement_separates_unanimous_from_split(tracker):
    for index in range(40):
        tracker.record("a", "agree-%d" % index, prediction="ENTER",
                       realized_r=2.0, outcome=1)
        tracker.record("b", "agree-%d" % index, prediction="ENTER",
                       realized_r=2.0, outcome=1)
    for index in range(40):
        tracker.record("a", "split-%d" % index, prediction="ENTER",
                       realized_r=-1.0, outcome=0)
        tracker.record("b", "split-%d" % index, prediction="DECLINE",
                       realized_r=-1.0, outcome=0)
    report = tracker.agreement(["a", "b"])
    assert report["unanimous"]["trades"] == 40
    assert report["split"]["trades"] == 40
    assert report["difference_r"] == 3.0
    assert report["verdict"] == "AGREEMENT_CARRIES_SIGNAL"


def test_single_model_trades_are_not_agreement(tracker):
    """Agreement among one model is not agreement."""
    for index in range(40):
        tracker.record("solo", "t-%d" % index, prediction="ENTER",
                       realized_r=1.0, outcome=1)
    assert tracker.agreement(["solo"])["trades_compared"] == 0


# ---------------------------------------------------------------------------
# Coverage and persistence
# ---------------------------------------------------------------------------

def test_untracked_governed_models_are_named(tracker):
    """A governed model with no records is invisible, and silence reads as health."""
    coverage = tracker.coverage()
    assert coverage["untracked"]
    assert "exit_model" in coverage["untracked"]


def test_records_persist_across_instances():
    with tempfile.TemporaryDirectory() as directory:
        store = GovernanceStore(directory)
        first = PerformanceTracker(store)
        _fill(first, "kept", 10, 1.0, 1)
        second = PerformanceTracker(store)
        assert len(second.records.get("kept", [])) == 10


def test_ranking_names_the_unrankable_rather_than_burying_them(tracker):
    _fill(tracker, "scored", 60, 1.0, 1)
    _fill(tracker, "tooshort", 3, 1.0, 1)
    ranking = tracker.ranking()[0]
    assert [c["model"] for c in ranking["ranked"]] == ["scored"]
    assert "tooshort" in ranking["unrankable"]
