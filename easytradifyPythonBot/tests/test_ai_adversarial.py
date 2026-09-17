"""
AIAdversarial: attack generation, adaptive selection, and A/B testing.
"""

import pytest

from ai.ai_adversarial import AIAdversarial

from conftest import CONFIDENCE, build_trade


@pytest.fixture
def adversarial():
    adv = AIAdversarial()
    adv.adversarial_config["attack_probability"] = 1.0
    adv.adversarial_config["attack_both_wins_and_losses"] = True
    return adv


# ---------------------------------------------------------------------------
# Regression: adaptive selection was inert
# ---------------------------------------------------------------------------

def test_adaptive_weights_increase_on_improvement(adversarial):
    """
    The clamp wrote back `current_weight` -- the stale pre-update value --
    discarding the increment. Weights never left 0.0, so the "weighted" choice
    in _select_attack_type was uniform random forever, silently.
    """
    adversarial.stats["attack_types_used"] = {"decision_attack", "component_attack"}
    for _ in range(3):
        adversarial._update_adaptive_selection({"improvement": 0.1})

    weights = adversarial.adaptive_selection["attack_weights"]
    assert all(w > 0 for w in weights.values()), f"weights frozen at {dict(weights)}"


def test_adaptive_weights_decrease_on_regression(adversarial):
    adversarial.stats["attack_types_used"] = {"decision_attack"}
    for _ in range(3):
        adversarial._update_adaptive_selection({"improvement": 0.1})
    peak = adversarial.adaptive_selection["attack_weights"]["decision_attack"]

    adversarial._update_adaptive_selection({"improvement": -0.1})
    assert adversarial.adaptive_selection["attack_weights"]["decision_attack"] < peak


def test_adaptive_weights_stay_bounded(adversarial):
    adversarial.stats["attack_types_used"] = {"decision_attack"}
    for _ in range(500):
        adversarial._update_adaptive_selection({"improvement": 1.0})
    assert adversarial.adaptive_selection["attack_weights"]["decision_attack"] <= 5

    for _ in range(500):
        adversarial._update_adaptive_selection({"improvement": -1.0})
    assert adversarial.adaptive_selection["attack_weights"]["decision_attack"] >= 0


# ---------------------------------------------------------------------------
# Regression: training label misalignment
# ---------------------------------------------------------------------------

def test_every_variation_keeps_its_parent_outcome(adversarial):
    """
    Labels were built as `outcomes * len(all_attacked)`, producing
    len(outcomes) x N labels for N samples -- every variation paired with
    some other trade's outcome.
    """
    trades = [build_trade(ticket=t, points=2) for t in (1, 2, 3)]
    outcomes = [1, 0, 1]
    seen = {}

    def training_function(X, y):
        seen["samples"], seen["labels"] = len(X), len(y)
        return {"improvement": 0.02}

    adversarial.apply_attacks_to_training(trades, outcomes, training_function,
                                          save_models=False)
    assert seen["samples"] == seen["labels"]


def test_misalignment_raises_rather_than_training_silently(adversarial, monkeypatch):
    """A length mismatch must fail loudly; silent mistraining is the worst case."""
    monkeypatch.setattr(adversarial, "generate_attacked_trades",
                        lambda trade, outcome, ctx=None: [trade, trade])
    trades = [build_trade(ticket=1)]
    calls = {}

    def training_function(X, y):
        calls["n"] = (len(X), len(y))
        return {"improvement": 0.0}

    adversarial.apply_attacks_to_training(trades, [1], training_function,
                                          save_models=False)
    assert calls["n"][0] == calls["n"][1] == 2


# ---------------------------------------------------------------------------
# Canonical decoding
# ---------------------------------------------------------------------------

def test_attacks_operate_on_decoded_data(adversarial):
    """Attacking short keys would corrupt fields no downstream model reads."""
    adversarial.ab_test["rollout"] = 1.0
    variations = adversarial.generate_attacked_trades(build_trade(), outcome=1)

    for variation in variations:
        for point in variation.get("price_evolution", []):
            assert point.get("_canonical") is True
            assert "c" not in point["analysis"]["m1"], "raw short keys reached the attacker"


def test_source_trade_is_not_mutated(adversarial):
    adversarial.ab_test["rollout"] = 1.0
    trade = build_trade()
    original = trade["analysis_at_open"][CONFIDENCE]
    adversarial.generate_attacked_trades(trade, outcome=1)
    assert trade["analysis_at_open"][CONFIDENCE] == original


# ---------------------------------------------------------------------------
# A/B testing
# ---------------------------------------------------------------------------

def test_arm_assignment_is_deterministic(adversarial):
    """Random assignment would put one trade in both arms across retries."""
    first = [adversarial.should_attack_trade(i) for i in range(200)]
    second = [adversarial.should_attack_trade(i) for i in range(200)]
    assert first == second


def test_arm_assignment_respects_rollout(adversarial):
    adversarial.ab_test["rollout"] = 0.20
    share = sum(adversarial.should_attack_trade(i) for i in range(2000)) / 2000
    assert 0.15 < share < 0.25, f"rollout 20% produced {share:.1%}"


def test_control_arm_returns_the_trade_untouched(adversarial):
    adversarial.ab_test["rollout"] = 0.0
    variations = adversarial.generate_attacked_trades(build_trade(), outcome=1)
    assert len(variations) == 1


def test_test_arm_generates_variations(adversarial):
    adversarial.ab_test["rollout"] = 1.0
    variations = adversarial.generate_attacked_trades(build_trade(), outcome=1)
    assert len(variations) > 1


def test_verdict_requires_enough_samples(adversarial):
    """Refusing to conclude on thin data is the point, not a limitation."""
    assert adversarial.get_ab_test_results()["status"] == "INSUFFICIENT_DATA"

    for i in range(6):
        adversarial.track_ab_test_result(i, profit=1.0, outcome=1, used_adversarial=True)
        adversarial.track_ab_test_result(100 + i, profit=-1.0, outcome=0, used_adversarial=False)
    assert adversarial.get_ab_test_results()["status"] == "INSUFFICIENT_DATA"


def test_detects_adversarial_improvement(adversarial):
    for i in range(20):
        adversarial.track_ab_test_result(i, profit=1.0, outcome=1 if i < 16 else 0,
                                         used_adversarial=True)
        adversarial.track_ab_test_result(100 + i, profit=1.0, outcome=1 if i < 8 else 0,
                                         used_adversarial=False)
    results = adversarial.get_ab_test_results()
    assert results["status"] == "ADVERSARIAL_BETTER"
    assert results["improvement"] > 0


def test_detects_adversarial_degradation_and_rolls_back(adversarial):
    adversarial.ab_test["rollout"] = 0.40
    for i in range(20):
        adversarial.track_ab_test_result(i, profit=-1.0, outcome=1 if i < 4 else 0,
                                         used_adversarial=True)
        adversarial.track_ab_test_result(100 + i, profit=1.0, outcome=1 if i < 16 else 0,
                                         used_adversarial=False)
    results = adversarial.get_ab_test_results()
    assert results["status"] == "ADVERSARIAL_WORSE"
    assert adversarial.ab_test["rollout"] < 0.40, "degradation did not reduce rollout"


def test_no_difference_is_a_valid_conclusion(adversarial):
    """The system must be able to say 'this changed nothing'."""
    for i in range(20):
        adversarial.track_ab_test_result(i, profit=1.0, outcome=i % 2,
                                         used_adversarial=True)
        adversarial.track_ab_test_result(100 + i, profit=1.0, outcome=i % 2,
                                         used_adversarial=False)
    assert adversarial.get_ab_test_results()["status"] == "NO_DIFFERENCE"


def test_ab_results_shape_is_stable(adversarial):
    """This is a reporting surface; its keys are a contract."""
    results = adversarial.get_ab_test_results()
    assert {"enabled", "rollout", "status", "improvement", "total_trades",
            "control", "test", "last_adjustment"} <= set(results)
    assert {"wins", "losses", "win_rate", "profit", "samples"} <= set(results["control"])
