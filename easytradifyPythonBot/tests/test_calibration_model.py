"""
Probability calibration.

The load-bearing tests: calibration is gated on ECE *and* resolution, so a
base-rate predictor cannot pass; and the informativeness diagnostic must
correctly flag a constant probability -- the state replay actually measured.
"""

import math
import random

import pytest

from ai.calibration_model import (
    CALIBRATION_MODEL_VERSION,
    CalibrationConfig,
    CalibrationModel,
    CalibrationSample,
    brier_decomposition,
    build_calibration_samples,
    diagnose_input,
    expected_calibration_error,
    get_status,
    reliability_curve,
    self_check,
    train_and_validate,
)

from conftest import build_trade


def make_trade(ticket, stated_probability, winning, timestamp=None):
    """A closed trade stating `stated_probability` (as a percent) at entry."""
    trade = build_trade(ticket=ticket, points=3, winning=winning)
    trade["analysis_at_open"]["final_verdict"] = {
        "probability_percent": stated_probability * 100.0}
    if timestamp:
        trade["opened_at"] = timestamp
    return trade


def overconfident_trades(n=200, seed=3):
    """
    Systematically overconfident: stated 0.5-0.95, true rate roughly half the
    stated excess over 0.5. Miscalibrated but genuinely informative -- higher
    stated probability really does win more often.
    """
    rng = random.Random(seed)
    trades = []
    for i in range(n):
        stated = rng.uniform(0.5, 0.95)
        true_rate = 0.5 + (stated - 0.5) * 0.5
        trades.append(make_trade(
            i + 1, stated, rng.random() < true_rate,
            timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z"))
    return trades


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_builds_one_sample_per_resolved_trade():
    trades = [make_trade(i, 0.7, i % 2 == 0) for i in range(1, 11)]
    samples = build_calibration_samples(trades)
    assert len(samples) == 10
    assert all(0.0 <= s.stated_probability <= 1.0 for s in samples)


def test_percent_and_fraction_scales_both_land_in_0_1():
    trade = build_trade(ticket=1, points=3, winning=True)
    trade["analysis_at_open"]["final_verdict"] = {"probability_percent": 72.5}
    assert build_calibration_samples([trade])[0].stated_probability == pytest.approx(0.725)


def test_percent_string_is_parsed():
    """The engine emits '72.5%' in some fields."""
    trade = build_trade(ticket=1, points=3, winning=True)
    trade["analysis_at_open"].pop("final_verdict", None)
    trade["analysis_at_open"]["⭐ CONFIDENCE"] = "72.5%"
    assert build_calibration_samples([trade])[0].stated_probability == pytest.approx(0.725)


def test_falls_back_through_probability_paths():
    """The engine has moved this field before; the fallbacks are load-bearing."""
    trade = build_trade(ticket=1, points=3, winning=True)
    trade["analysis_at_open"].pop("final_verdict", None)
    trade["analysis_at_open"].pop("⭐ CONFIDENCE", None)
    trade["entry"]["probability_of_hit_percent"] = 64.0
    assert build_calibration_samples([trade])[0].stated_probability == pytest.approx(0.64)


def test_trades_without_a_stated_probability_are_skipped():
    trade = build_trade(ticket=1, points=3, winning=True)
    trade["analysis_at_open"] = {}
    trade["entry"].pop("probability_of_hit_percent", None)
    assert build_calibration_samples([trade]) == []


def test_unresolved_trades_are_skipped():
    trade = make_trade(1, 0.7, True)
    trade["close_data"] = {}
    assert build_calibration_samples([trade]) == []


def test_malformed_trades_do_not_abort_the_batch():
    good = [make_trade(i, 0.7, i % 2 == 0) for i in range(1, 6)]
    built = build_calibration_samples([None, {"ticket": 1}, "junk"] + good)
    assert len(built) == len(good)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_perfect_calibration_has_zero_error():
    probabilities = [0.0] * 50 + [1.0] * 50
    outcomes = [0] * 50 + [1] * 50
    assert expected_calibration_error(probabilities, outcomes) == pytest.approx(0.0)


def test_systematic_overconfidence_shows_up_as_error():
    probabilities = [0.9] * 100
    outcomes = [1] * 50 + [0] * 50          # claims 90%, delivers 50%
    assert expected_calibration_error(probabilities, outcomes) == pytest.approx(0.4)


def test_brier_decomposition_identity_holds():
    """Brier = reliability - resolution + uncertainty."""
    rng = random.Random(5)
    probabilities = [rng.uniform(0.1, 0.9) for _ in range(300)]
    outcomes = [1 if rng.random() < p else 0 for p in probabilities]

    parts = brier_decomposition(probabilities, outcomes, bins=10)
    rebuilt = parts["reliability"] - parts["resolution"] + parts["uncertainty"]
    assert rebuilt == pytest.approx(parts["brier"], abs=0.02)


def test_base_rate_predictor_is_calibrated_but_has_no_resolution():
    """
    The exact reason ECE alone cannot be the gate: this predictor is perfectly
    calibrated and completely useless.
    """
    outcomes = [1] * 60 + [0] * 40
    probabilities = [0.6] * 100
    parts = brier_decomposition(probabilities, outcomes, bins=10)
    assert parts["reliability"] == pytest.approx(0.0, abs=1e-6)
    assert parts["resolution"] == pytest.approx(0.0, abs=1e-6)


def test_reliability_curve_reports_stated_against_observed():
    probabilities = [0.15] * 20 + [0.85] * 20
    outcomes = [0] * 20 + [1] * 20
    curve = reliability_curve(probabilities, outcomes, bins=10)
    assert all(b["count"] > 0 for b in curve)
    assert sum(b["count"] for b in curve) == 40


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def test_constant_probability_is_flagged_as_uninformative():
    """
    Replay measured probability pinned at 13.0 across five instruments. This
    diagnostic is what makes that visible instead of silently calibrating a
    point into the base rate.
    """
    samples = [
        CalibrationSample(str(i), f"t{i}", 0.13, i % 2)
        for i in range(100)
    ]
    diagnosis = diagnose_input(samples)
    assert diagnosis["input_is_informative"] is False
    assert diagnosis["std"] == pytest.approx(0.0)
    assert any("constant" in note for note in diagnosis["notes"])


def test_probability_that_cannot_rank_is_flagged():
    """Varied but uninformative: spread without ordering power."""
    rng = random.Random(9)
    samples = [
        CalibrationSample(str(i), f"t{i}", rng.uniform(0.2, 0.8), rng.randint(0, 1))
        for i in range(400)
    ]
    diagnosis = diagnose_input(samples)
    assert diagnosis["input_is_informative"] is False
    assert any("rank" in note for note in diagnosis["notes"])


def test_informative_probability_is_recognised():
    samples = build_calibration_samples(overconfident_trades())
    diagnosis = diagnose_input(samples)
    assert diagnosis["input_is_informative"] is True
    assert diagnosis["notes"] == []


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def test_calibration_corrects_systematic_overconfidence():
    samples = build_calibration_samples(overconfident_trades())
    model = CalibrationModel()
    model.fit(samples)
    # Stated 0.9 should map materially below itself.
    assert model.calibrate(0.9) < 0.85


def test_calibrated_output_is_always_a_probability():
    model = CalibrationModel()
    model.fit(build_calibration_samples(overconfident_trades()))
    for value in (0.0, 0.05, 0.5, 0.95, 1.0):
        assert 0.0 <= model.calibrate(value) <= 1.0


def test_calibration_is_monotone():
    """
    Isotonic cannot reorder. This is why an uninformative input stays
    uninformative after calibration -- and why the diagnostic matters.
    """
    model = CalibrationModel()
    model.fit(build_calibration_samples(overconfident_trades()))
    values = [model.calibrate(p / 20) for p in range(21)]
    assert values == sorted(values)


def test_refuses_to_fit_on_too_few_trades():
    samples = [CalibrationSample(str(i), f"t{i}", 0.5, i % 2) for i in range(10)]
    with pytest.raises(ValueError, match="resolved trades"):
        CalibrationModel().fit(samples)


def test_refuses_a_single_outcome_class():
    samples = [CalibrationSample(str(i), f"t{i}", 0.5, 1) for i in range(100)]
    with pytest.raises(ValueError, match="single outcome"):
        CalibrationModel().fit(samples)


def test_calibrating_before_fitting_raises():
    with pytest.raises(RuntimeError):
        CalibrationModel().calibrate(0.5)


def test_saved_model_round_trips(tmp_path):
    samples = build_calibration_samples(overconfident_trades())
    original = CalibrationModel()
    original.fit(samples)
    probes = [0.1, 0.35, 0.6, 0.9]
    before = [original.calibrate(p) for p in probes]

    path = str(tmp_path / "calibration.json")
    original.save(path)
    after = [CalibrationModel().load(path).calibrate(p) for p in probes]
    assert before == pytest.approx(after)


def test_version_mismatch_is_refused(tmp_path):
    import json
    model = CalibrationModel()
    model.fit(build_calibration_samples(overconfident_trades()))
    path = str(tmp_path / "calibration.json")
    model.save(path)

    payload = json.load(open(path, encoding="utf-8"))
    payload["version"] = "0.1"
    json.dump(payload, open(path, "w", encoding="utf-8"))

    with pytest.raises(ValueError, match="version"):
        CalibrationModel().load(path)


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------

def test_miscalibrated_but_informative_data_promotes():
    report = train_and_validate(overconfident_trades())
    assert report["promoted"] is True
    assert report["ece_improvement"] >= 0.02
    assert report["after"]["ece"] < report["before"]["ece"]


def test_already_calibrated_data_is_refused():
    """Nothing to fix means nothing to promote."""
    rng = random.Random(17)
    trades = [
        make_trade(i + 1, p, rng.random() < p,
                   timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z")
        for i, p in enumerate(rng.uniform(0.2, 0.8) for _ in range(200))
    ]
    report = train_and_validate(trades)
    assert report["promoted"] is False
    assert "calibration error improved" in report["rejected_because"]


def test_thin_data_is_refused_with_a_reason():
    report = train_and_validate([make_trade(i, 0.7, i % 2 == 0) for i in range(1, 11)])
    assert report["promoted"] is False
    assert "resolved trades" in report["rejected_because"]


def test_constant_probability_warns_that_sizing_cannot_use_it():
    """
    The finding that decides whether the score is usable downstream at all:
    a calibrator over a constant score is honest and still cannot rank.
    """
    trades = [
        make_trade(i + 1, 0.13, i % 3 == 0,
                   timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z")
        for i in range(200)
    ]
    report = train_and_validate(trades)
    assert report["diagnostics"]["input_is_informative"] is False
    assert "warning" in report
    assert "size every trade alike" in report["warning"]


def test_information_loss_is_gated_alongside_calibration_error():
    """
    ECE alone is trivially satisfied by predicting the base rate, so a second
    gate must guard ranking power. It is AUC, not binned resolution: isotonic
    is monotone and preserves ranking exactly, while binned resolution falls
    as a measurement artifact whenever calibration compresses predictions.
    """
    status = get_status()
    assert status["gates_on_auc"] is False          # not gated for DISCRIMINATION
    assert "max_auc_loss" in status["promotion_gates"]   # gated for PRESERVATION


def test_a_calibrator_that_destroys_ranking_is_refused(monkeypatch):
    """The failure the second gate exists for: collapse to the base rate."""
    import ai.calibration_model as module

    class Collapsing(module.CalibrationModel):
        def calibrate(self, probability):
            return 0.5

    monkeypatch.setattr(module, "CalibrationModel", Collapsing)
    report = train_and_validate(overconfident_trades())
    assert report["promoted"] is False
    assert "ranking power fell" in report["rejected_because"]


def test_report_always_contains_both_reliability_curves():
    report = train_and_validate(overconfident_trades())
    assert report["before"]["reliability_curve"]
    assert report["after"]["reliability_curve"]


def test_training_does_not_disturb_the_global_rng():
    trades = overconfident_trades()
    random.seed(31)
    expected = [random.random() for _ in range(3)]
    random.seed(31)
    train_and_validate(trades)
    assert [random.random() for _ in range(3)] == expected


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_explains_why_it_does_not_gate_on_auc():
    status = get_status()
    assert status["component"] == "calibration_model"
    assert "base-rate predictor" in status["why_not_auc"]
    assert "information or noise" in status["informativeness_decides"]


def test_self_check_passes_and_reports_informativeness():
    report = self_check(overconfident_trades())
    assert report["ok"] is True
    assert report["checks"]["probabilities_in_range"] is True
    assert report["checks"]["input_is_informative"] is True


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["samples_built"] == 0
