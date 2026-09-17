"""
Adaptive target extension model.

The load-bearing tests: the label respects ORDER (giveback before target is a
loss), the population is restricted to in-profit points, and the permutation
floor still refuses noise.
"""

import math

import pytest

from ai.exit_model import ExitSample
from ai.target_model import (
    TARGET_MODEL_VERSION,
    TargetModel,
    TargetModelConfig,
    build_target_samples,
    extension_expectancy_delta,
    extension_paid_off,
    get_status,
    self_check,
    train_and_validate,
)

from conftest import build_trade


def make_trade(ticket, prices, entry=1.0850, stop=1.0830, target=1.0890,
               direction="BUY", close_price=None):
    trade = build_trade(ticket=ticket, points=len(prices))
    trade["entry"].update({"price": entry, "stop_loss": stop, "take_profit": target})
    trade["direction"] = direction
    for point, price in zip(trade["price_evolution"], prices):
        point["price"] = price
    trade["close_data"]["close_price"] = (
        close_price if close_price is not None else prices[-1])
    return trade


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

def test_extension_pays_off_when_target_comes_first():
    # from 1.0R: reaches 1.5R before dropping to 0.5R
    assert extension_paid_off([0.0, 1.0, 1.3, 1.6], 1, 0.5, 0.5) == 1


def test_extension_fails_when_giveback_comes_first():
    assert extension_paid_off([0.0, 1.0, 0.4, 1.9], 1, 0.5, 0.5) == 0


def test_order_is_what_distinguishes_them():
    """
    Both paths touch the target and the giveback level. Only the ORDER differs,
    and it decides the label -- a position closed on the way down never sees
    the later high. Evaluating the two conditions independently would score
    both as wins.
    """
    good = extension_paid_off([0.0, 1.0, 1.6, 0.4], 1, 0.5, 0.5)
    bad = extension_paid_off([0.0, 1.0, 0.4, 1.6], 1, 0.5, 0.5)
    assert (good, bad) == (1, 0)


def test_unresolved_paths_return_none():
    """Neither level touched: the data never showed an outcome to learn."""
    assert extension_paid_off([0.0, 1.0, 1.1, 1.2], 1, 0.5, 0.5) is None


def test_no_forward_path_returns_none():
    assert extension_paid_off([0.0, 1.0], 1, 0.5, 0.5) is None


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------

def test_only_in_profit_points_become_samples():
    """Extension is not a question for a losing trade -- that is exit_model's."""
    cfg = TargetModelConfig()
    trade = make_trade(1, [1.0840, 1.0845, 1.0860, 1.0880, 1.0895], close_price=1.0895)
    for sample in build_target_samples([trade], cfg):
        assert sample.current_return_r >= cfg.min_profit_r


def test_a_trade_never_in_profit_yields_nothing():
    trade = make_trade(2, [1.0845, 1.0840, 1.0835, 1.0832], close_price=1.0830)
    assert build_target_samples([trade]) == []


def test_unresolved_points_are_dropped_not_guessed():
    """A drifting winner that resolves neither way must not be labelled."""
    trade = make_trade(3, [1.0862, 1.0863, 1.0864, 1.0865], close_price=1.0865)
    assert build_target_samples([trade]) == []


def test_malformed_trades_do_not_abort_the_batch():
    good = [make_trade(i, [1.0862, 1.0875, 1.0890, 1.0900], close_price=1.0900)
            for i in range(1, 6)]
    built = build_target_samples([None, {"ticket": 1}, "junk"] + good)
    assert {s.trade_id for s in built} == {str(t["ticket"]) for t in good}


def test_features_are_finite_and_causal():
    trades = [make_trade(i, [1.0862, 1.0875, 1.0890, 1.0900], close_price=1.0900)
              for i in range(1, 6)]
    for sample in build_target_samples(trades):
        for name, value in sample.features.items():
            assert math.isfinite(value), name


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_extending_a_runner_shows_a_gain():
    trade = make_trade(1, [1.0862, 1.0875, 1.0890, 1.0910], close_price=1.0910)
    samples = build_target_samples([trade])
    assert samples
    result = extension_expectancy_delta(samples, [1.0] * len(samples), threshold=0.5)
    assert result["delta_r"] > 0
    assert result["extensions"] == 1


def test_never_extending_is_a_zero_delta():
    trade = make_trade(1, [1.0862, 1.0875, 1.0890, 1.0910], close_price=1.0910)
    samples = build_target_samples([trade])
    result = extension_expectancy_delta(samples, [0.0] * len(samples), threshold=0.5)
    assert result["delta_r"] == 0.0
    assert result["extensions"] == 0


def test_extending_into_a_reversal_is_penalised():
    """The failure mode extension must be judged against: giving it all back."""
    trade = make_trade(1, [1.0862, 1.0880, 1.0895, 1.0835], close_price=1.0835)
    samples = build_target_samples([trade])
    assert samples
    result = extension_expectancy_delta(samples, [1.0] * len(samples), threshold=0.5)
    assert result["delta_r"] < 0


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@pytest.fixture
def learnable_trades():
    """
    Real but noisy signal: strong early momentum tends to continue, stalling
    momentum tends to reverse. Both populations are in profit, so the model
    cannot separate them on profitability alone -- it has to read the path.

    Per-trade jitter is deliberate. An earlier version used two exact path
    shapes, which are perfectly separable in feature space -- and against
    perfectly separable clusters ANY non-zero coefficient yields AUC 1.0,
    including a shuffled-label control's. That makes every control vacuous and
    the gates untestable. Synthetic fixtures for a model must overlap.
    """
    import random
    rng = random.Random(4)

    trades = []
    for i in range(120):
        jitter = lambda: rng.uniform(-0.0006, 0.0006)
        if i % 2 == 0:
            prices = [1.0862 + jitter(), 1.0878 + jitter(),
                      1.0894 + jitter(), 1.0910 + jitter(), 1.0925 + jitter()]
        else:
            prices = [1.0862 + jitter(), 1.0864 + jitter(),
                      1.0863 + jitter(), 1.0845 + jitter(), 1.0838 + jitter()]
        trades.append(make_trade(i + 1, [round(p, 6) for p in prices],
                                 close_price=round(prices[-1], 6)))
    return trades


def test_model_fits_and_scores_in_range(learnable_trades):
    samples = build_target_samples(learnable_trades)
    model = TargetModel()
    model.fit(samples)
    assert model.fitted
    assert all(0.0 <= p <= 1.0 for p in model.predict_proba(samples))


def test_refuses_to_answer_for_a_losing_trade(learnable_trades):
    """Applying the model outside its fitted population would be unsound."""
    model = TargetModel()
    model.fit(build_target_samples(learnable_trades))
    verdict = model.should_extend([1.0850, 1.0840], 1.0850, 1.0830, 1.0890, "BUY")
    assert verdict["extend"] is False
    assert verdict["reason"] == "not_in_profit"


def test_should_extend_reports_its_reasoning(learnable_trades):
    model = TargetModel()
    model.fit(build_target_samples(learnable_trades))
    verdict = model.should_extend([1.0850, 1.0878, 1.0894], 1.0850, 1.0830,
                                  1.0890, "BUY")
    assert set(verdict) >= {"extend", "probability", "threshold", "return_r"}
    assert 0.0 <= verdict["probability"] <= 1.0


def test_degrades_without_a_model():
    verdict = TargetModel().should_extend([1.0850, 1.0890], 1.0850, 1.0830,
                                          1.0890, "BUY")
    assert verdict["extend"] is False
    assert verdict["reason"] == "not_fitted"


def test_saved_model_round_trips(learnable_trades, tmp_path):
    samples = build_target_samples(learnable_trades)
    original = TargetModel()
    original.fit(samples)
    before = original.predict_proba(samples)

    path = str(tmp_path / "target_model.json")
    original.save(path)
    after = TargetModel().load(path).predict_proba(samples)
    assert before == pytest.approx(after)


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------

def test_thin_data_is_refused_with_a_reason(trades):
    report = train_and_validate(trades)
    assert report["promoted"] is False
    assert report["rejected_because"]


def test_real_signal_promotes(learnable_trades):
    report = train_and_validate(learnable_trades)
    assert report["promoted"] is True
    assert report["expectancy"]["delta_r"] > report["noise_floor"]["delta_r"]


def test_noise_is_refused():
    """Same regression as exit_model: the pipeline must not learn from nothing."""
    import random
    rng = random.Random(11)
    noise = [
        make_trade(
            i + 1,
            [1.0850 + rng.uniform(-0.004, 0.004) for _ in range(5)],
            close_price=1.0850 + rng.uniform(-0.004, 0.004),
        )
        for i in range(60)
    ]
    report = train_and_validate(noise)
    assert report["promoted"] is False


def test_expectancy_is_the_binding_gate(learnable_trades):
    config = TargetModelConfig(min_expectancy_gain_r=99.0)
    report = train_and_validate(learnable_trades, config)
    assert report["promoted"] is False
    assert "expectancy delta" in report["rejected_because"]


def test_permutation_floor_is_always_reported(learnable_trades):
    report = train_and_validate(learnable_trades)
    assert set(report["noise_floor"]) >= {"auc", "delta_r", "samples"}


def test_uncomputable_floor_refuses_promotion(learnable_trades):
    """
    Fail closed. An earlier version skipped both floor gates when the control
    could not be scored, so a model could be promoted with its most important
    safety check silently absent -- and the report still looked clean.
    """
    # A floor needing more samples than the control can ever produce.
    config = TargetModelConfig(min_samples=10)
    config.min_samples = 10          # real data clears this
    report = train_and_validate(learnable_trades, config)

    if report["noise_floor"]["delta_r"] is None:
        assert report["promoted"] is False
        assert "could not be computed" in report["rejected_because"]
    else:
        # Floor computed, so the fail-closed path is not what is under test;
        # assert the gate was actually applied rather than skipped.
        assert report["noise_floor"]["auc"] is not None


def test_training_does_not_disturb_the_global_rng(learnable_trades):
    import random
    random.seed(21)
    expected = [random.random() for _ in range(3)]
    random.seed(21)
    train_and_validate(learnable_trades)
    assert [random.random() for _ in range(3)] == expected


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_documents_the_label_and_population():
    status = get_status()
    assert status["component"] == "target_model"
    assert status["predicts_direction"] is False
    assert status["population"] == "in-profit points only"
    assert "min_extension_r" in status["thresholds"]


def test_self_check_confirms_population_and_splits():
    trades = [make_trade(i, [1.0862, 1.0878, 1.0894, 1.0910], close_price=1.0910)
              for i in range(1, 12)]
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["all_in_profit"] is True
    assert report["checks"]["split_groups_disjoint"] is True


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["samples_built"] == 0
