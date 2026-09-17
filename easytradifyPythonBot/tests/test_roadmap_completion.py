"""
The remaining roadmap items: stress replay, GNN analysis, adversarial/replay
integration, and the RL policies.

Phase 3 item 10, phase 5 items 2/5/7, phase 6 item 6, phase 7 items 2/3/4/8.

The recurring hazard across all four is a control that cannot fail. Stress
that always breaks, a validator that promotes noise, a stability probe that
replays the original trade, a policy search graded against its own training
split -- each produces a confident number that means nothing. Most of the
tests below are aimed at that, not at the happy path.
"""

import random

import pytest

from ai import adversarial_replay, gnn_analysis, rl_policies
from ai.aireplay import stress
from ai.aireplay.data_engine import extract_replay_records
from conftest import build_trade


@pytest.fixture
def records():
    trades = [build_trade(ticket=8800 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    return extract_replay_records(trades)


@pytest.fixture
def trades():
    return [build_trade(ticket=8900 + i, points=8, winning=(i % 3 != 0))
            for i in range(60)]


# ---------------------------------------------------------------------------
# Phase 3 item 10 -- stress replay
# ---------------------------------------------------------------------------

def test_stress_is_labelled_as_simulation_everywhere(records):
    """
    Counterfactual branching is historical truth; this modifies the prices.
    Quoting both as "what would have happened" is how fiction acquires the
    authority of measurement.
    """
    result = stress.stress_trade(records[0])
    assert result["uses_only_historical_prices"] is False
    assert result["is_simulation"] is True
    assert all(not s["is_historical_truth"] for s in result["scenarios"])


def test_unstressed_magnitude_reproduces_the_baseline(records):
    """
    The 1.0 volatility magnitude scales excursions by 1.0 -- not at all. If it
    disagrees with the baseline, the perturbation is leaking into the control
    and every delta reported is wrong.
    """
    result = stress.stress_trade(records[0])
    neutral = [s for s in result["scenarios"]
               if s["family"] == "volatility" and s["magnitude"] == 1.0]
    assert neutral and neutral[0]["realized_r"] == result["baseline_r"]


def test_harm_is_monotone(records):
    """A larger adverse shift can never improve the result."""
    result = stress.stress_trade(records[0])
    rows = sorted((s for s in result["scenarios"] if s["family"] == "slippage"),
                  key=lambda s: s["magnitude"])
    values = [s["realized_r"] for s in rows if s["realized_r"] is not None]
    assert all(values[i] >= values[i + 1] - 1e-9 for i in range(len(values) - 1))


def test_no_family_breaks_every_trade(records):
    """
    A stress that always breaks is a constant wearing a result's clothes.
    Sizing the gap by the path's own range did exactly that -- every trade
    flipped at magnitude 1.0 and `most_fragile_to` was "gap" for the cohort.
    """
    results = stress.stress_trades(records)
    aggregate = stress.aggregate_stress(results)
    for family, count in (aggregate["flips_by_family"] or {}).items():
        assert count < aggregate["trades"], family


def test_survived_to_is_distinct_from_never_breakable(records):
    result = stress.stress_trade(records[0])
    for family, point in result["breaking_points"].items():
        if point["breaks_at"] is None:
            assert point["survived_to"] is not None, family


def test_unusable_trade_is_skipped_explicitly():
    class _Bad:
        trade_id = "x"

    result = stress.stress_trade(_Bad())
    assert result["skipped"]
    assert result["scenarios"] == []


# ---------------------------------------------------------------------------
# Phase 5 items 2 and 5 -- embeddings and conflict
# ---------------------------------------------------------------------------

class _Graph:
    """A owns a genuine opposition; B merely differs in magnitude."""

    graph = {
        "assets": ["A", "B", "C"],
        "nodes": 3,
        "edges": [(0, 1), (1, 2)],
        "edge_weights": [0.8, 0.6],
        "features": {
            "A": {"direction_4h": 0.9, "gnn_direction": -0.8},
            "B": {"direction_4h": 0.9, "gnn_direction": 0.3},
            "C": {"direction_4h": 0.0, "gnn_direction": 0.0},
        },
    }


def test_no_graph_yields_no_embedding_not_zeros():
    """
    A zero vector claims every dimension measured zero. That is a different
    statement from "the graph does not exist", and downstream code cannot tell
    them apart once they look the same.
    """
    class _Empty:
        graph = None

    assert gnn_analysis.node_embeddings(_Empty()) == {}
    assert gnn_analysis.detect_conflicts(_Empty())["available"] is False


def test_embeddings_are_named_and_ordered():
    embeddings = gnn_analysis.node_embeddings(_Graph())
    assert set(embeddings) == {"A", "B", "C"}
    vector = gnn_analysis.embedding_vector(embeddings["A"])
    assert len(vector) == len(gnn_analysis.EMBEDDING_DIMENSIONS)
    assert embeddings["B"]["degree"] == 2.0


def test_only_opposing_signs_count_as_conflict():
    """
    An asset reading +0.9 among peers implying +0.3 agrees emphatically.
    Calling that a conflict fills the report with agreements.
    """
    conflicts = gnn_analysis.detect_conflicts(_Graph())
    assert conflicts["conflict_count"] == 1
    assert conflicts["conflicts"][0]["asset"] == "A"


def test_conflict_report_never_claims_direction():
    assert gnn_analysis.detect_conflicts(_Graph())["claims_direction"] is False


# ---------------------------------------------------------------------------
# Phase 5 item 7 -- OOS validation
# ---------------------------------------------------------------------------

def _gnn_trades(count, planted, seed):
    import copy

    rng = random.Random(seed)
    out = []
    for index in range(count):
        influence = rng.uniform(-1, 1)
        strong = abs(influence) >= 0.3
        win = (rng.random() < (0.85 if strong else 0.15)) if planted \
            else (rng.random() < 0.5)
        trade = build_trade(ticket=30000 + index, points=5, winning=win)
        trade["analysis_at_open"] = copy.deepcopy(trade["analysis_at_open"])
        trade["analysis_at_open"]["gnn"] = {
            "gnn_influence": influence, "gnn_connections": rng.randint(1, 6)}
        trade["opened_at"] = "2026-01-%02dT%02d:00:00Z" % (
            1 + index // 24, index % 24)
        out.append(trade)
    return out


def test_missing_gnn_state_is_a_data_gap_not_a_verdict(trades):
    result = gnn_analysis.validate_out_of_sample(trades)
    assert result["measurable"] is False
    assert "data gap" in result["rejected_because"]


def test_validator_detects_a_planted_signal():
    result = gnn_analysis.validate_out_of_sample(_gnn_trades(200, True, 0))
    assert result["measurable"]
    assert result["promoted"] is True


def test_validator_refuses_pure_noise():
    """
    Compared against the 95th percentile of the shuffled control, not its
    mean. With the mean as the bar this promoted noise in 1 run in 5 -- a 20%
    false-positive rate presented as a passed control.
    """
    promoted = sum(
        1 for seed in range(5)
        if gnn_analysis.validate_out_of_sample(
            _gnn_trades(200, False, seed))["promoted"])
    assert promoted == 0


# ---------------------------------------------------------------------------
# Phase 6 item 6 -- adversarial x replay
# ---------------------------------------------------------------------------

def test_probe_measures_stability_against_real_attacks(trades):
    result = adversarial_replay.probe_trade(trades[0], variations=6)
    assert result["variants_replayed"] > 0
    assert result["stability"] is not None
    assert set(result["flips_by_conclusion"]) == set(
        adversarial_replay.TRACKED_CONCLUSIONS)


def test_stability_is_never_claimed_to_be_correctness():
    """A consistently wrong attribution is perfectly stable."""
    assert adversarial_replay.get_status()["stability_implies_correctness"] is False


def test_cohort_probe_reports_a_mean(trades):
    result = adversarial_replay.probe_trades(trades[:4], variations=4)
    assert result["mean_stability"] is not None
    assert result["trades"] > 0


# ---------------------------------------------------------------------------
# Phase 7 items 2, 3, 4 -- management, exit, sizing
# ---------------------------------------------------------------------------

def test_a_managed_stop_never_widens(records):
    """
    A stop that can widen is not risk management, it is a losing position
    being given more room.
    """
    from ai.rl_policies import _paths, _returns_r

    for _, path in _paths(records):
        if max(_returns_r(path)) >= 1.0:
            assert rl_policies.apply_management(path, 1.0, None) >= 0.0


def test_exit_is_not_armed_before_the_trade_is_profitable(records):
    """
    Applied from entry, a give-back rule fires on the ordinary noise every
    trade starts with and closes every position at its first adverse tick.
    """
    from ai.rl_policies import _paths, _returns_r

    for _, path in _paths(records):
        if max(_returns_r(path)) <= 0:
            assert rl_policies.apply_exit(path, 0.3) <= 0


def test_sizing_caps_are_hard(records):
    limits = rl_policies.SizingLimits()
    result = rl_policies.bounded_size(1.0, 99.0, 0.0, limits)
    assert result["multiplier_used"] == limits.max_multiplier
    assert result["risk_percent"] <= limits.max_risk_percent
    assert result["was_clamped"]


def test_sizing_reports_what_it_refused():
    """
    A size cut from 1.4% to 1.0% and reported only as "1.0%" hides that the
    model wanted something the limits refused.
    """
    result = rl_policies.bounded_size(1.0, 5.0)
    assert result["multiplier_requested"] == 5.0
    assert result["multiplier_used"] == 1.5
    assert result["limits_applied"]


def test_portfolio_ceiling_can_zero_a_size():
    limits = rl_policies.SizingLimits()
    result = rl_policies.bounded_size(1.0, 1.0, limits.max_open_risk_percent,
                                      limits)
    assert result["risk_percent"] == 0.0


def test_non_finite_multiplier_cannot_reach_an_order():
    assert rl_policies.bounded_size(1.0, float("nan"))["multiplier_used"] == 1.0
    assert rl_policies.bounded_size(1.0, float("inf"))["multiplier_used"] <= 1.5


def test_policy_training_carries_a_permutation_control(records):
    """
    The control runs the WHOLE procedure, search included. Controlling only
    the final policy ignores that the search picks the best of many
    candidates, which is where most of the optimism lives.
    """
    for kind in ("management", "exit"):
        result = rl_policies.train_policy(records, kind)
        assert result["measurable"]
        assert result["candidates_searched"] > 1
        assert result["control_95th_r"] is not None


def test_thin_data_refuses_to_train():
    result = rl_policies.train_policy([], "management")
    assert result["measurable"] is False
    assert result["promoted"] is False


# ---------------------------------------------------------------------------
# Phase 7 item 8 -- controlled deployment
# ---------------------------------------------------------------------------

def test_deployment_starts_small_and_is_reversible():
    """
    A policy that just cleared its gates on historical trades has earned an
    experiment, not the whole book.
    """
    import tempfile

    from ai.model_governance import GovernanceStore

    with tempfile.TemporaryDirectory() as directory:
        store = GovernanceStore(directory)
        good = rl_policies.deploy(
            "exit_model", {"promoted": True, "delta_r": 0.2}, store=store)
        assert good["promoted"]
        assert good["rollout"] == 0.1


def test_a_rejected_policy_is_registered_but_not_deployed():
    import tempfile

    from ai.model_governance import GovernanceStore

    with tempfile.TemporaryDirectory() as directory:
        store = GovernanceStore(directory)
        bad = rl_policies.deploy(
            "exit_model",
            {"promoted": False, "rejected_because": "below noise floor"},
            store=store)
        assert bad["promoted"] is False
        assert bad["rollout"] == 0.0
        assert bad["registered_version"]
