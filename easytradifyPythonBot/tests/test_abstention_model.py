"""
Selective abstention.

The load-bearing tests: a real cost condition is found and pays off out of
sample; a random condition-outcome link is refused by the shuffled floor; and
declining everything is not allowed to count as a strategy.
"""

import math
import random

import pytest

from ai.abstention_model import (
    ABSTENTION_MODEL_VERSION,
    AbstentionConfig,
    AbstentionRules,
    AbstentionSample,
    abstention_expectancy,
    bucket_of,
    build_abstention_samples,
    get_status,
    quantile_edges,
    self_check,
    train_and_validate,
)

from conftest import build_trade


def make_trade(ticket, realized_r, spread=0.6, session="LONDON",
               zone_grade="B", timestamp=None, entry=1.0850, risk=0.0020):
    """A closed trade with a controlled realised R and entry conditions."""
    trade = build_trade(ticket=ticket, points=3, winning=realized_r > 0)
    trade["entry"].update({
        "price": entry,
        "stop_loss": entry - risk,
        "take_profit": entry + 2 * risk,
        "spread_at_entry": spread,
        "risk_percent_used": 0.4,
    })
    trade["direction"] = "BUY"
    trade["close_data"]["close_price"] = entry + realized_r * risk
    trade["analysis_at_open"]["session_analysis"] = {
        "session": session, "phase": "OPEN"}
    trade["analysis_at_open"]["components"]["4_supply_demand"]["zone_grade"] = zone_grade
    if timestamp:
        trade["opened_at"] = timestamp
    return trade


def costly_spread_trades(n=200, seed=5):
    """
    A real cost effect: wide spreads lose, normal spreads are fine.

    Mirrors what replay actually measured -- spread/stop >= 0.8 won 18.6% of
    the time -- rather than a direction signal.
    """
    rng = random.Random(seed)
    trades = []
    for i in range(n):
        wide = i % 3 == 0
        spread = rng.uniform(14.0, 19.0) if wide else rng.uniform(0.4, 2.0)
        realized = rng.gauss(-1.0, 0.3) if wide else rng.gauss(0.35, 0.8)
        trades.append(make_trade(
            i + 1, realized, spread=spread,
            timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z"))
    return trades


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_builds_one_sample_per_closed_trade():
    trades = [make_trade(i, 0.5) for i in range(1, 11)]
    assert len(build_abstention_samples(trades)) == 10


def test_realized_r_is_signed_by_direction():
    long_trade = make_trade(1, 2.0)
    sample = build_abstention_samples([long_trade])[0]
    assert sample.realized_r == pytest.approx(2.0)

    short_trade = make_trade(2, 0.0)
    short_trade["direction"] = "SELL"
    short_trade["entry"]["stop_loss"] = 1.0870
    short_trade["close_data"]["close_price"] = 1.0830   # profit for a short
    assert build_abstention_samples([short_trade])[0].realized_r > 0


def test_derived_cost_conditions_are_computed():
    """spread_to_stop is a ratio; replay implicated the ratio, not the field."""
    sample = build_abstention_samples([make_trade(1, 0.5, spread=10.0)])[0]
    assert sample.conditions["spread_to_stop"] == pytest.approx(10.0 / 20.0)


def test_categorical_conditions_are_read():
    sample = build_abstention_samples([make_trade(1, 0.5, session="ASIA")])[0]
    assert sample.conditions["session"] == "ASIA"
    assert sample.conditions["direction"] == "BUY"


def test_trades_without_a_close_price_are_skipped():
    trade = make_trade(1, 0.5)
    trade["close_data"] = {}
    assert build_abstention_samples([trade]) == []


def test_malformed_trades_do_not_abort_the_batch():
    good = [make_trade(i, 0.5) for i in range(1, 6)]
    built = build_abstention_samples([None, {"ticket": 1}, "junk"] + good)
    assert len(built) == len(good)


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def test_quantile_edges_are_deduplicated():
    """A spiky distribution should collapse, not produce empty bins."""
    assert quantile_edges([1.0] * 50, bins=5) == [1.0]


def test_bucket_assignment_is_ordered():
    edges = [1.0, 2.0, 3.0]
    assert bucket_of(0.5, edges) == "q0"
    assert bucket_of(2.5, edges) == "q2"
    assert bucket_of(9.9, edges) == "q3"


def test_missing_values_are_not_bucketed():
    assert bucket_of(None, [1.0]) is None


# ---------------------------------------------------------------------------
# Rule discovery
# ---------------------------------------------------------------------------

def test_finds_the_costly_condition():
    samples = build_abstention_samples(costly_spread_trades())
    rules = AbstentionRules()
    rules.fit(samples)
    assert any(r["condition"] == "spread_to_stop" for r in rules.rules)


def test_ignores_buckets_that_are_too_small():
    """Small buckets are where multiple-comparison noise lives."""
    config = AbstentionConfig(min_bucket_trades=1000)
    rules = AbstentionRules(config)
    rules.fit(build_abstention_samples(costly_spread_trades()))
    assert rules.rules == []


def test_ignores_buckets_that_are_merely_mediocre():
    config = AbstentionConfig(decline_below_r=-99.0)
    rules = AbstentionRules(config)
    rules.fit(build_abstention_samples(costly_spread_trades()))
    assert rules.rules == []


def test_refuses_to_fit_on_too_few_trades():
    with pytest.raises(ValueError, match="Need >="):
        AbstentionRules().fit(build_abstention_samples(
            [make_trade(i, 0.5) for i in range(1, 6)]))


def test_decline_verdict_names_its_evidence():
    """A declined trade must be explainable, not just refused."""
    samples = build_abstention_samples(costly_spread_trades())
    rules = AbstentionRules()
    rules.fit(samples)

    widest = max(samples, key=lambda s: s.conditions["spread_to_stop"] or 0)
    verdict = rules.should_decline(widest)
    assert verdict["decline"] is True
    assert verdict["condition"] and verdict["bucket"]
    assert verdict["bucket_trades"] >= AbstentionConfig().min_bucket_trades


def test_unfitted_rules_decline_nothing():
    sample = build_abstention_samples([make_trade(1, 0.5)])[0]
    assert AbstentionRules().should_decline(sample)["decline"] is False


# ---------------------------------------------------------------------------
# Learning from success, not only from loss
# ---------------------------------------------------------------------------

def mixed_session_trades(n=200, seed=3):
    """ASIA loses badly, NY wins strongly, LONDON is neutral."""
    rng = random.Random(seed)
    trades = []
    for i in range(n):
        session = ["ASIA", "NY", "LONDON"][i % 3]
        realized = {
            "ASIA": rng.gauss(-1.0, 0.3),
            "NY": rng.gauss(1.2, 0.4),
            "LONDON": rng.gauss(0.0, 0.5),
        }[session]
        trades.append(make_trade(
            i + 1, realized, session=session,
            timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z"))
    return trades


def test_finds_favourable_conditions_not_only_bad_ones():
    """
    Regression: the scan was one-sided. On this data it found ASIA at -1.03R
    and was blind to NY at +1.16R -- the strongest signal present. A system
    that only learns where it loses cannot say where to lean in.
    """
    rules = AbstentionRules()
    rules.fit(build_abstention_samples(mixed_session_trades()))

    assert any(r["bucket"] == "ASIA" for r in rules.rules), "missed the bad session"
    assert any(r["bucket"] == "NY" for r in rules.favor_rules), "missed the good session"


def test_assess_returns_all_three_stances():
    samples = build_abstention_samples(mixed_session_trades())
    rules = AbstentionRules()
    rules.fit(samples)

    stances = {
        session: rules.assess(
            next(s for s in samples if s.conditions["session"] == session)
        )["stance"]
        for session in ("ASIA", "NY", "LONDON")
    }
    assert stances == {"ASIA": "DECLINE", "NY": "FAVOR", "LONDON": "NEUTRAL"}


def test_decline_outranks_favor():
    """
    A realised loss outranks an estimated gain. If a trade matches both a
    decline and a favour rule, it must be declined.
    """
    sample = AbstentionSample("1", "t", {"session": "ASIA", "zone_grade": "A"}, 0.0)
    rules = AbstentionRules()
    rules.fitted = True
    rules.rules = [{"condition": "session", "bucket": "ASIA",
                    "trades": 20, "mean_r": -1.0, "vs_overall_r": -1.0}]
    rules.favor_rules = [{"condition": "zone_grade", "bucket": "A",
                          "trades": 20, "mean_r": 1.0, "vs_overall_r": 1.0}]
    assert rules.assess(sample)["stance"] == "DECLINE"


def test_favour_rules_are_validated_out_of_sample():
    report = train_and_validate(mixed_session_trades())
    validation = report["favor_validation"]
    assert validation["favored_trades"] > 0
    assert validation["holds_out_of_sample"] is True
    assert validation["favored_mean_r"] > validation["other_mean_r"]


def test_favour_rules_do_not_block_promotion():
    """
    Favour rules change ranking, not what is traded, so a weak favour set must
    not be able to veto an otherwise-sound decline set.
    """
    report = train_and_validate(costly_spread_trades())
    assert report["promoted"] is True


def test_favour_rules_survive_a_round_trip(tmp_path):
    original = AbstentionRules()
    original.fit(build_abstention_samples(mixed_session_trades()))
    assert original.favor_rules

    path = str(tmp_path / "abstention.json")
    original.save(path)
    assert AbstentionRules().load(path).favor_rules == original.favor_rules


def test_status_declares_symmetry():
    status = get_status()
    assert status["learns_from_success"] is True
    assert "both directions" in status["symmetry"]
    assert "favor_above_r" in status["promotion_gates"]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_declined_trades_score_zero_not_absent():
    """
    Dropping declined trades from the average would flatter the policy by
    comparing a filtered mean against an unfiltered one. Money not made on a
    skipped trade is zero, not missing.
    """
    samples = [
        AbstentionSample("1", "t", {"session": "ASIA"}, -2.0),
        AbstentionSample("2", "t", {"session": "LONDON"}, 1.0),
    ]
    rules = AbstentionRules()
    rules.fitted = True
    rules.rules = [{"condition": "session", "bucket": "ASIA",
                    "trades": 20, "mean_r": -2.0, "vs_overall_r": -1.5}]

    result = abstention_expectancy(rules, samples)
    assert result["baseline_r"] == pytest.approx(-0.5)   # (-2 + 1) / 2
    assert result["policy_r"] == pytest.approx(0.5)      # (0 + 1) / 2
    assert result["declined"] == 1


def test_expectancy_reports_declined_fraction():
    samples = build_abstention_samples(costly_spread_trades())
    rules = AbstentionRules()
    rules.fit(samples)
    result = abstention_expectancy(rules, samples)
    assert 0.0 < result["declined_fraction"] < 1.0


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------

def test_a_real_cost_effect_promotes():
    report = train_and_validate(costly_spread_trades())
    assert report["promoted"] is True
    assert report["expectancy"]["delta_r"] > 0
    assert report["rules"]


def test_random_outcomes_are_refused():
    """
    Scanning many buckets for the worst performers finds something in noise.
    The shuffled floor is what stops that becoming a strategy.
    """
    rng = random.Random(13)
    trades = [
        make_trade(i + 1, rng.gauss(0.0, 1.0),
                   spread=rng.uniform(0.4, 18.0),
                   session=rng.choice(["ASIA", "LONDON", "NY"]),
                   zone_grade=rng.choice(["A", "B", "C"]),
                   timestamp=f"2026-01-{(i % 28) + 1:02d}T10:00:00Z")
        for i in range(200)
    ]
    report = train_and_validate(trades)
    assert report["promoted"] is False


def test_declining_everything_is_refused():
    """Not trading is not a strategy."""
    config = AbstentionConfig(decline_below_r=99.0, min_bucket_trades=1,
                              max_declined_fraction=0.5)
    report = train_and_validate(costly_spread_trades(), config)
    assert report["promoted"] is False
    assert "not trading" in (report["rejected_because"] or "")


def test_thin_data_is_refused_with_a_reason():
    report = train_and_validate([make_trade(i, 0.5) for i in range(1, 11)])
    assert report["promoted"] is False
    assert "resolved trades" in report["rejected_because"]


def test_shuffled_floor_is_always_reported():
    report = train_and_validate(costly_spread_trades())
    assert "shuffle_floor" in report
    assert "delta_r" in report["shuffle_floor"]


def test_uncomputable_floor_refuses_promotion(monkeypatch):
    """Fail closed: an uncomputable gate is an unmet gate."""
    import ai.abstention_model as module
    monkeypatch.setattr(module, "_shuffled_floor",
                        lambda *a, **k: {"delta_r": None, "error": "forced"})
    report = train_and_validate(costly_spread_trades())
    assert report["promoted"] is False
    assert "could not be computed" in report["rejected_because"]


def test_training_does_not_disturb_the_global_rng():
    trades = costly_spread_trades()
    random.seed(41)
    expected = [random.random() for _ in range(3)]
    random.seed(41)
    train_and_validate(trades)
    assert [random.random() for _ in range(3)] == expected


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_rules_round_trip(tmp_path):
    samples = build_abstention_samples(costly_spread_trades())
    original = AbstentionRules()
    original.fit(samples)

    path = str(tmp_path / "abstention.json")
    original.save(path)
    loaded = AbstentionRules().load(path)

    assert loaded.rules == original.rules
    assert [loaded.should_decline(s)["decline"] for s in samples] == \
           [original.should_decline(s)["decline"] for s in samples]


def test_version_mismatch_is_refused(tmp_path):
    import json
    rules = AbstentionRules()
    rules.fit(build_abstention_samples(costly_spread_trades()))
    path = str(tmp_path / "abstention.json")
    rules.save(path)

    payload = json.load(open(path, encoding="utf-8"))
    payload["version"] = "0.1"
    json.dump(payload, open(path, "w", encoding="utf-8"))

    with pytest.raises(ValueError, match="version"):
        AbstentionRules().load(path)


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_states_it_is_not_meta_labeling():
    status = get_status()
    assert status["component"] == "abstention_model"
    assert status["is_meta_labeling"] is False
    assert status["predicts_direction"] is False
    assert status["target"] == "expectancy in R"
    assert "0.5034" in status["why_not_meta_labeling"]


def test_self_check_reports_condition_coverage():
    """Which conditions are actually populated decides what can be learned."""
    report = self_check(costly_spread_trades())
    assert report["ok"] is True
    assert report["checks"]["realized_r_finite"] is True
    assert "spread_to_stop" in report["checks"]["conditions_populated"]
    assert 0.0 <= report["checks"]["condition_coverage"]["session"] <= 1.0


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["samples_built"] == 0
