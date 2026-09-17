"""
Mid-trade exit model.

The load-bearing tests here are causality (features at k must not see k+1) and
group-disjoint splitting. Both failures are invisible in the metrics -- they
make the model look BETTER, which is why they need explicit tests.
"""

import math

import pytest

from ai.exit_model import (
    EXIT_MODEL_VERSION,
    FEATURE_NAMES,
    ExitModel,
    ExitModelConfig,
    build_samples,
    expectancy_delta,
    get_status,
    path_features,
    roc_auc,
    self_check,
    split_by_trade,
    train_and_validate,
)

from conftest import build_trade


def make_trade(ticket, prices, entry=1.0850, stop=1.0830, target=1.0890,
               direction="BUY", close_price=None):
    """A trade whose price path is exactly `prices` (excluding entry)."""
    trade = build_trade(ticket=ticket, points=len(prices))
    trade["entry"].update({"price": entry, "stop_loss": stop, "take_profit": target})
    trade["direction"] = direction
    for point, price in zip(trade["price_evolution"], prices):
        point["price"] = price
    trade["close_data"]["close_price"] = (
        close_price if close_price is not None else prices[-1])
    return trade


# ---------------------------------------------------------------------------
# Causality
# ---------------------------------------------------------------------------

def test_features_ignore_everything_after_the_index():
    """
    The defining property. Appending future prices must not change features
    computed at an earlier index -- if it does, the model is reading the future
    and every downstream metric is fiction.
    """
    prices = [1.0850, 1.0855, 1.0860, 1.0845, 1.0830]
    truncated = path_features(prices[:3], 2, 1.0850, 1.0830, 1.0890, "BUY")
    full = path_features(prices, 2, 1.0850, 1.0830, 1.0890, "BUY")
    assert truncated == full


def test_features_change_when_the_past_changes():
    """Guards against the check above passing because features are inert."""
    a = path_features([1.0850, 1.0855, 1.0860], 2, 1.0850, 1.0830, 1.0890, "BUY")
    b = path_features([1.0850, 1.0840, 1.0860], 2, 1.0850, 1.0830, 1.0890, "BUY")
    assert a["mae_r"] != b["mae_r"]


def test_r_units_make_instruments_comparable():
    """
    Identical risk-relative moves on instruments with different absolute
    scales must produce identical features, or the model learns the symbol.
    Both below are +1R: a 20-pip gain on 20-pip risk, and 50.0 on 50.0 risk.
    """
    tight = path_features([1.0850, 1.0870], 1, 1.0850, 1.0830, None, "BUY")
    wide = path_features([100.0, 150.0], 1, 100.0, 50.0, None, "BUY")
    assert tight["return_r"] == pytest.approx(1.0)
    assert tight["return_r"] == pytest.approx(wide["return_r"])


def test_direction_is_respected():
    up = path_features([1.0850, 1.0870], 1, 1.0850, 1.0830, None, "BUY")
    down = path_features([1.0850, 1.0870], 1, 1.0850, 1.0870, None, "SELL")
    assert up["return_r"] > 0
    assert down["return_r"] < 0


def test_room_to_stop_hits_zero_at_the_stop():
    features = path_features([1.0850, 1.0830], 1, 1.0850, 1.0830, None, "BUY")
    assert features["room_to_stop"] == pytest.approx(0.0)


def test_drawdown_from_peak_tracks_given_back_gains():
    features = path_features([1.0850, 1.0890, 1.0860], 2, 1.0850, 1.0830, None, "BUY")
    assert features["mfe_r"] == pytest.approx(2.0)
    assert features["return_r"] == pytest.approx(0.5)
    assert features["drawdown_from_peak_r"] == pytest.approx(1.5)
    assert features["bars_since_mfe"] == 1.0


def test_zero_risk_is_refused_not_guessed():
    """Every feature is a fraction of risk; without risk there is no feature."""
    assert path_features([1.0850, 1.0860], 1, 1.0850, 1.0850, None, "BUY") is None


# ---------------------------------------------------------------------------
# Sample construction
# ---------------------------------------------------------------------------

def test_builds_one_sample_per_usable_point(trades):
    samples = build_samples(trades)
    assert samples
    assert {s.trade_id for s in samples} == {str(t["ticket"]) for t in trades}


def test_label_is_did_holding_hurt():
    """A trade that peaks then collapses must be labelled 'should have left'."""
    trade = make_trade(1, [1.0870, 1.0890, 1.0860, 1.0830], close_price=1.0830)
    samples = build_samples(trade and [trade])
    early = min(samples, key=lambda s: s.index)
    assert early.final_return_r < early.current_return_r
    assert early.label == 1


def test_label_is_zero_when_holding_helped():
    trade = make_trade(2, [1.0855, 1.0860, 1.0870, 1.0890], close_price=1.0890)
    for sample in build_samples([trade]):
        assert sample.label == 0


def test_close_price_beats_last_observed_price():
    """The last evolution point is not necessarily the fill."""
    trade = make_trade(3, [1.0860, 1.0870, 1.0875], close_price=1.0830)
    sample = build_samples([trade])[0]
    assert sample.final_return_r < 0, "close_data price should define the outcome"


def test_trades_without_a_stop_are_skipped():
    trade = make_trade(4, [1.0860, 1.0870])
    trade["entry"]["stop_loss"] = None
    assert build_samples([trade]) == []


def test_malformed_trades_do_not_abort_the_batch(trades):
    built = build_samples([None, {"ticket": 1}, "junk"] + list(trades))
    assert {s.trade_id for s in built} == {str(t["ticket"]) for t in trades}


def test_features_are_finite(trades):
    for sample in build_samples(trades):
        for name, value in sample.features.items():
            assert math.isfinite(value), name


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def test_split_never_shares_a_trade(trades):
    """
    A row-level split would put points 4 and 5 of one trade on opposite sides
    and the model would score brilliantly by recognising a trade it had seen.
    """
    train, test = split_by_trade(build_samples(trades), test_fraction=0.3)
    assert train and test
    assert not ({s.trade_id for s in train} & {s.trade_id for s in test})


def test_split_is_chronological(trades):
    samples = build_samples(trades)
    train, test = split_by_trade(samples, test_fraction=0.3)
    assert max(s.timestamp for s in train) <= min(s.timestamp for s in test)


def test_single_trade_cannot_be_split():
    samples = build_samples([make_trade(1, [1.086, 1.087, 1.088])])
    train, test = split_by_trade(samples)
    assert test == []


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_auc_of_a_perfect_ranking_is_one():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)


def test_auc_of_an_inverted_ranking_is_zero():
    assert roc_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(0.0)


def test_auc_is_none_without_both_classes():
    assert roc_auc([1, 1, 1], [0.2, 0.5, 0.9]) is None


def test_expectancy_delta_rewards_cutting_a_loser():
    """A trade exited before it collapses must show a positive delta."""
    trade = make_trade(1, [1.0870, 1.0860, 1.0830], close_price=1.0830)
    samples = build_samples([trade])
    always_exit = [1.0] * len(samples)
    result = expectancy_delta(samples, always_exit, threshold=0.5)
    assert result["delta_r"] > 0
    assert result["early_exits"] >= 1


def test_expectancy_delta_is_zero_when_never_exiting():
    samples = build_samples([make_trade(1, [1.0870, 1.0860, 1.0830])])
    result = expectancy_delta(samples, [0.0] * len(samples), threshold=0.5)
    assert result["delta_r"] == 0.0
    assert result["early_exits"] == 0


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@pytest.fixture
def learnable_trades():
    """
    Trades with a real signal: those that peak then reverse end badly, those
    that rise steadily end well.

    60 trades, not 30: min_training_trades is checked against the TRAIN split,
    so clearing a gate of 30 at test_fraction=0.3 needs ~43 total.
    """
    trades = []
    for i in range(60):
        if i % 2 == 0:
            prices = [1.0860, 1.0890, 1.0870, 1.0845, 1.0830]
            close = 1.0830
        else:
            prices = [1.0855, 1.0862, 1.0870, 1.0880, 1.0890]
            close = 1.0890
        trades.append(make_trade(i + 1, prices, close_price=close))
    return trades


def test_model_fits_and_scores_in_range(learnable_trades):
    samples = build_samples(learnable_trades)
    model = ExitModel()
    model.fit(samples)
    assert model.fitted
    assert all(0.0 <= p <= 1.0 for p in model.predict_proba(samples))


def test_model_refuses_to_fit_on_too_few_trades():
    with pytest.raises(ValueError, match="distinct trades"):
        ExitModel().fit(build_samples([make_trade(1, [1.086, 1.087, 1.088])]))


def test_model_refuses_a_single_class(learnable_trades):
    samples = build_samples(learnable_trades)
    for sample in samples:
        sample.label = 1
    with pytest.raises(ValueError, match="single class"):
        ExitModel().fit(samples)


def test_predicting_before_fitting_raises():
    with pytest.raises(RuntimeError):
        ExitModel().predict_proba([])


def test_should_exit_reports_its_reasoning(learnable_trades):
    model = ExitModel()
    model.fit(build_samples(learnable_trades))
    verdict = model.should_exit([1.0850, 1.0890, 1.0860], 1.0850, 1.0830,
                                1.0890, "BUY")
    assert set(verdict) >= {"exit", "probability", "threshold", "return_r"}
    assert 0.0 <= verdict["probability"] <= 1.0


def test_should_exit_degrades_without_a_model():
    verdict = ExitModel().should_exit([1.0850, 1.0860], 1.0850, 1.0830, None, "BUY")
    assert verdict["exit"] is False
    assert verdict["reason"] == "not_fitted"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_saved_model_round_trips(learnable_trades, tmp_path):
    samples = build_samples(learnable_trades)
    original = ExitModel()
    original.fit(samples)
    before = original.predict_proba(samples)

    path = str(tmp_path / "exit_model.json")
    original.save(path)
    after = ExitModel().load(path).predict_proba(samples)
    assert before == pytest.approx(after)


def test_artifact_is_plain_json(learnable_trades, tmp_path):
    """No pickle: loading an artifact must not be able to execute code."""
    import json
    model = ExitModel()
    model.fit(build_samples(learnable_trades))
    path = str(tmp_path / "exit_model.json")
    model.save(path)

    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["feature_names"][:len(FEATURE_NAMES)] == list(FEATURE_NAMES)
    assert payload["version"] == EXIT_MODEL_VERSION


def test_version_mismatch_is_refused(learnable_trades, tmp_path):
    import json
    model = ExitModel()
    model.fit(build_samples(learnable_trades))
    path = str(tmp_path / "exit_model.json")
    model.save(path)

    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["version"] = "0.1"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    with pytest.raises(ValueError, match="version"):
        ExitModel().load(path)


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------

def test_training_reports_reason_when_data_is_thin(trades):
    report = train_and_validate(trades)
    assert report["promoted"] is False
    assert report["rejected_because"]


def test_promotion_requires_beating_the_shuffled_control(learnable_trades):
    report = train_and_validate(learnable_trades)
    assert "control_auc" in report
    assert "expectancy" in report
    if report["promoted"]:
        assert report["test_auc"] - report["control_auc"] >= 0.02
        assert report["expectancy"]["delta_r"] >= 0.05


def test_promotion_requires_expectancy_not_just_auc(learnable_trades):
    """A model that ranks well but does not move R must be refused."""
    config = ExitModelConfig(min_expectancy_gain_r=99.0)
    report = train_and_validate(learnable_trades, config)
    assert report["promoted"] is False
    assert "expectancy delta" in report["rejected_because"]


# ---------------------------------------------------------------------------
# Noise floor
#
# These exist because an earlier version of this pipeline PROMOTED a model
# trained on pure noise: AUC 0.777, +0.34R, beating its shuffled-label control.
# The label (`final < current`) is nearly a function of `current`, which is also
# a feature, so the model learned "am I near my own path's peak" -- an artifact
# that pays off on any path at all.
# ---------------------------------------------------------------------------

@pytest.fixture
def noise_trades():
    """iid prices around a level: no temporal signal, but very exit-exploitable."""
    import random
    rng = random.Random(7)
    return [
        make_trade(
            i + 1,
            [1.0850 + rng.uniform(-0.003, 0.003) for _ in range(5)],
            close_price=1.0850 + rng.uniform(-0.003, 0.003),
        )
        for i in range(60)
    ]


def test_permutation_preserves_everything_but_order(learnable_trades):
    from ai.exit_model import permuted_path_trades

    permuted = permuted_path_trades(learnable_trades, seed=1)
    assert len(permuted) == len(learnable_trades)

    original = learnable_trades[0]
    control = permuted[0]
    assert control["entry"]["price"] == original["entry"]["price"]
    assert len(control["price_evolution"]) == len(original["price_evolution"])
    # Increments are permuted, so their sum -- and therefore the endpoint -- holds.
    assert control["close_data"]["close_price"] == pytest.approx(
        original["close_data"]["close_price"])


def test_noise_is_refused(noise_trades):
    """The regression this whole gate exists for."""
    report = train_and_validate(noise_trades)
    assert report["promoted"] is False
    assert "noise floor" in (report["rejected_because"] or "")


def test_real_signal_still_promotes(learnable_trades):
    """The gate must not be so strict that nothing can ever pass it."""
    report = train_and_validate(learnable_trades)
    assert report["promoted"] is True
    assert report["expectancy"]["delta_r"] > report["noise_floor"]["delta_r"]


def test_noise_floor_is_always_reported(learnable_trades):
    report = train_and_validate(learnable_trades)
    assert set(report["noise_floor"]) >= {"auc", "delta_r", "samples"}


def test_training_does_not_disturb_the_global_rng(learnable_trades):
    import random
    random.seed(99)
    expected = [random.random() for _ in range(3)]
    random.seed(99)
    train_and_validate(learnable_trades)
    assert [random.random() for _ in range(3)] == expected


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_states_it_does_not_predict_direction():
    status = get_status()
    assert status["component"] == "exit_model"
    assert status["predicts_direction"] is False
    assert set(status["promotion_gates"]) >= {
        "min_auc", "min_auc_over_control", "min_expectancy_gain_r"}


def test_self_check_passes_and_confirms_disjoint_splits(trades):
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["split_groups_disjoint"] is True
    assert report["checks"]["no_nan_features"] is True


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["samples_built"] == 0
