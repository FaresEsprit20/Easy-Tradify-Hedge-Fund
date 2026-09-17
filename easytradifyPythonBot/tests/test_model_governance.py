"""
Model governance: A/B assignment, verdicts, and versioned rollback.

The audit that produced this module found A/B in 2 of 8 models and rollback in
none. Two failure shapes matter more than the features themselves:

  * an A/B split that cannot be shown to SPLIT, and a rollback that cannot be
    shown to MOVE the active version, are indistinguishable from stubs that
    return success;
  * a verdict that presents a threshold crossing as a result invites shipping
    noise.

Every claim below therefore carries a negative control.
"""

import random
import tempfile

import pytest

from ai.model_governance import (
    ABConfig,
    ABTest,
    GovernanceStore,
    ModelRegistry,
    record_training,
    two_proportion_z_test,
)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as directory:
        yield GovernanceStore(directory)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def test_assignment_is_deterministic(store):
    experiment = ABTest("t", ABConfig(rollout=0.5), store)
    ids = ["trade-%d" % i for i in range(500)]
    assert [experiment.assign(i) for i in ids] == [
        experiment.assign(i) for i in ids]


def test_assignment_actually_splits(store):
    """A split that never splits would pass every determinism check."""
    experiment = ABTest("t", ABConfig(rollout=0.5), store)
    arms = [experiment.assign("trade-%d" % i) for i in range(1000)]
    share = arms.count("test") / len(arms)
    assert 0.4 < share < 0.6, share


def test_rollout_controls_the_share(store):
    for rollout, low, high in ((0.1, 0.05, 0.16), (0.9, 0.84, 0.95)):
        experiment = ABTest("t%s" % rollout, ABConfig(rollout=rollout), store)
        arms = [experiment.assign("x-%d" % i) for i in range(1000)]
        share = arms.count("test") / len(arms)
        assert low < share < high, (rollout, share)


def test_assignment_survives_a_new_instance(store):
    """Restarts must not reassign trades between arms."""
    first = ABTest("t", ABConfig(rollout=0.35), store)
    before = {i: first.assign(i) for i in ("a", "b", "c", "d", "e")}
    second = ABTest("t", ABConfig(rollout=0.35), store)
    assert {i: second.assign(i) for i in before} == before


def test_hash_algorithm_is_honoured(store):
    """
    ai_gnn assigns with MD5 and ai_adversarial with SHA-256. Unifying the hash
    would reassign in-flight trades, so the choice is a parameter -- and it has
    to actually change the assignment, or the parameter is decoration.
    """
    sha = ABTest("sha", ABConfig(rollout=0.5, hash_algorithm="sha256"), store)
    md5 = ABTest("md5", ABConfig(rollout=0.5, hash_algorithm="md5"), store)
    ids = ["trade-%d" % i for i in range(200)]
    assert [sha.assign(i) for i in ids] != [md5.assign(i) for i in ids]


def test_unit_without_id_goes_to_control(store):
    assert ABTest("t", ABConfig(), store).assign(None) == "control"


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def test_identical_arms_are_not_significant(store):
    experiment = ABTest("null", ABConfig(min_samples=10), store)
    for index in range(300):
        experiment.track("u%d" % index, 1.0, index % 2)
    results = experiment.results()
    assert not results["significant"]
    assert not results["verdict_is_actionable"]


def test_thin_samples_never_produce_a_verdict(store):
    experiment = ABTest("thin", ABConfig(min_samples=30), store)
    for index in range(8):
        experiment.track("u%d" % index, 1.0, 1)
    results = experiment.results()
    assert results["status"] == "INSUFFICIENT_DATA"
    assert not results["verdict_is_actionable"]


def test_a_real_difference_is_detected(store):
    """A control that rejects everything is as useless as one that accepts it."""
    experiment = ABTest("real", ABConfig(min_samples=20, rollout=0.5), store)
    rng = random.Random(7)
    recorded = 0
    index = 0
    while recorded < 400:
        unit = "unit-%d" % index
        index += 1
        arm = experiment.assign(unit)
        win = 1 if rng.random() < (0.75 if arm == "test" else 0.35) else 0
        experiment.track(unit, 1.0 if win else -1.0, win, arm)
        recorded += 1
    results = experiment.results()
    assert results["status"] == "TEST_BETTER"
    assert results["significant"]
    assert results["verdict_is_actionable"]


def test_direction_and_significance_are_separate_fields(store):
    """
    A difference can have a sign and no reality. Collapsing the two into one
    field is how a rollout ships noise.
    """
    experiment = ABTest("sep", ABConfig(min_samples=5), store)
    for index in range(10):
        experiment.track("c%d" % index, 1.0, 1 if index < 4 else 0, "control")
    for index in range(10):
        experiment.track("t%d" % index, 1.0, 1 if index < 6 else 0, "test")
    results = experiment.results()
    assert results["direction"] == "TEST_BETTER"
    assert not results["significant"]
    assert not results["verdict_is_actionable"]


def test_z_test_reports_unmeasurable_rather_than_one(store):
    assert two_proportion_z_test(0, 0, 5, 10)["p_value"] is None
    assert two_proportion_z_test(5, 10, 0, 0)["p_value"] is None


def test_counters_persist(store):
    first = ABTest("persist", ABConfig(min_samples=5), store)
    for index in range(40):
        first.track("u%d" % index, 1.0, index % 2)
    second = ABTest("persist", ABConfig(min_samples=5), store)
    assert second.state["total_trades"] == first.state["total_trades"]


# ---------------------------------------------------------------------------
# Registry and rollback
# ---------------------------------------------------------------------------

def test_rollback_moves_the_active_version(store):
    registry = ModelRegistry("m", store)
    first = registry.register({"w": 1}, {"auc": 0.6})
    registry.promote(first.version)
    second = registry.register({"w": 2}, {"auc": 0.7})
    registry.promote(second.version)
    assert registry.active_version == second.version

    outcome = registry.rollback("expectancy collapsed")
    assert outcome["rolled_back"]
    assert registry.active_version == first.version


def test_rollback_refuses_when_there_is_nothing_to_return_to(store):
    """
    Called precisely when someone believes production is broken. A cheerful
    success that changed nothing is the worst available answer.
    """
    registry = ModelRegistry("empty", store)
    outcome = registry.rollback("try")
    assert outcome["rolled_back"] is False
    assert "no earlier promoted version" in outcome["reason"]

    only = registry.register({"w": 1}, {})
    registry.promote(only.version)
    assert registry.rollback("try again")["rolled_back"] is False


def test_rollback_preserves_the_artifact_it_left(store):
    """A version that looked bad on 40 trades may be fine on 400."""
    registry = ModelRegistry("keep", store)
    first = registry.register({"w": 1}, {})
    registry.promote(first.version)
    second = registry.register({"w": 2}, {})
    registry.promote(second.version)
    registry.rollback("bad")
    assert registry.get(second.version) is not None
    assert registry.get(second.version).retired_at is not None


def test_rollback_survives_a_restart(store):
    registry = ModelRegistry("restart", store)
    first = registry.register({"w": 1}, {})
    registry.promote(first.version)
    second = registry.register({"w": 2}, {})
    registry.promote(second.version)
    registry.rollback("bad")

    reloaded = ModelRegistry("restart", store)
    assert reloaded.active_version == first.version
    assert [h["action"] for h in reloaded.history][-1] == "rollback"


def test_registering_does_not_promote(store):
    registry = ModelRegistry("noauto", store)
    entry = registry.register({"w": 1}, {"auc": 0.99})
    assert registry.active_version is None
    assert entry.promoted_at is None


def test_trimming_never_discards_a_promoted_version(store):
    """
    Promoted versions are the set rollback can return to. Trimming one would
    make a rollback target vanish -- the single outcome this class exists to
    prevent.
    """
    registry = ModelRegistry("trim", store)
    keeper = registry.register({"w": "keep"}, {})
    registry.promote(keeper.version)
    for index in range(registry.MAX_UNPROMOTED_VERSIONS + 20):
        registry.register({"w": index}, {})
    assert registry.get(keeper.version) is not None
    unpromoted = [v for v in registry.versions if not v.promoted_at]
    assert len(unpromoted) <= registry.MAX_UNPROMOTED_VERSIONS


def test_record_training_registers_rejected_candidates(store):
    """
    "Tried and rejected" is the fact that stops a configuration being retried
    in three months. A registry of successes only cannot answer it.
    """
    outcome = record_training("exit_model", {"w": 1}, {"auc": 0.5},
                              promoted=False, notes="did not beat noise floor",
                              store=store)
    assert outcome["registered_version"]
    assert outcome["promoted"] is False
    assert outcome["active_version"] is None


def test_corrupt_state_file_does_not_take_the_layer_down(store):
    path = store._path("registry", "corrupt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{ not json at all")
    registry = ModelRegistry("corrupt", store)
    assert registry.versions == []
    assert registry.active_version is None
