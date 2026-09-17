"""
AI_MarketReplay Phase 3 items 1-6.

The load-bearing tests: the event stream never exposes the future, the four
firsts of section 17 are genuinely distinct, and attribution reports
candidates rather than causes.
"""

import pytest

from ai.aireplay import extract_replay_records
from ai.aireplay.replay_engine import (
    ANOMALY_ADVERSE_R,
    MATERIAL_ADVERSE_R,
    EventStream,
    EventType,
    FailureClass,
    ReplayEvent,
    attribute_failure,
    build_event_stream,
    detect_divergences,
    get_status,
    reconstruct_decision,
    reconstruct_reality,
    replay_trade,
    replay_trades,
    self_check,
)

from conftest import build_trade


def record(prices, close=None, winning=False, ticket=901,
           entry=1.0850, stop=1.0830, target=1.0890, direction="BUY"):
    trade = build_trade(ticket=ticket, points=len(prices), winning=winning)
    trade["entry"].update({"price": entry, "stop_loss": stop, "take_profit": target})
    trade["direction"] = direction
    for point, price in zip(trade["price_evolution"], prices):
        point["price"] = price
    trade["close_data"]["close_price"] = close if close is not None else prices[-1]
    return extract_replay_records([trade])[0]


# ---------------------------------------------------------------------------
# Item 1 + 2 -- event model and temporal alignment
# ---------------------------------------------------------------------------

def test_stream_is_chronologically_ordered():
    stream = build_event_stream(record([1.0860, 1.0870, 1.0880]))
    assert stream.is_ordered()
    assert len(stream) > 0


def test_up_to_never_exposes_the_future():
    """The lookahead firewall. Indexing the list directly would bypass it."""
    stream = build_event_stream(record([1.0860, 1.0870, 1.0880]))
    for index in range(len(stream)):
        visible = stream.up_to(index)
        assert len(visible) == index + 1
        assert visible[-1] is stream[index]


def test_ties_preserve_recorded_order():
    """
    Events recorded within the same second must keep their order; a plain
    timestamp sort would scramble them.
    """
    events = [
        ReplayEvent(event_id=str(i), event_type=EventType.PRICE_UPDATE,
                    timestamp="2026-09-01T10:00:00Z", source="s", index=i)
        for i in range(5)
    ]
    stream = EventStream(list(reversed(events)))
    assert [e.index for e in stream] == [0, 1, 2, 3, 4]


def test_price_and_feature_events_are_paired():
    """
    The pairing is what makes divergence detectable: reality and belief,
    sampled together over the life of the trade.
    """
    stream = build_event_stream(record([1.0860, 1.0870]))
    assert len(stream.of_type(EventType.PRICE_UPDATE)) == 2
    assert stream.of_type(EventType.FEATURE_SNAPSHOT)


def test_stream_hash_is_deterministic():
    trade = record([1.0860, 1.0870])
    assert build_event_stream(trade).hash() == build_event_stream(trade).hash()


def test_events_carry_availability():
    for event in build_event_stream(record([1.0860])):
        assert event.available_at is not None


# ---------------------------------------------------------------------------
# Item 3 -- market reality
# ---------------------------------------------------------------------------

def test_reality_is_expressed_in_r():
    """
    R rather than pips, so a threshold means the same on XAGUSD and EURUSD.
    Entry 1.0850, stop 1.0830 => risk 20 pips; 1.0870 is +1R.
    """
    reality = reconstruct_reality(record([1.0870]))
    assert reality[0].return_r == pytest.approx(1.0)


def test_reality_tracks_excursions():
    reality = reconstruct_reality(record([1.0890, 1.0830]))
    assert reality[0].mfe_r == pytest.approx(2.0)
    assert reality[1].mfe_r == pytest.approx(2.0)     # peak is sticky
    assert reality[1].mae_r == pytest.approx(-1.0)
    assert reality[1].adverse_excursion_r == pytest.approx(1.0)


def test_short_direction_is_signed_correctly():
    reality = reconstruct_reality(
        record([1.0830], entry=1.0850, stop=1.0870, direction="SELL"))
    assert reality[0].return_r == pytest.approx(1.0)


def test_reality_is_empty_without_a_stop():
    trade = build_trade(ticket=1)
    trade["entry"]["stop_loss"] = None
    record_ = extract_replay_records([trade])[0]
    assert reconstruct_reality(record_) == []


# ---------------------------------------------------------------------------
# Item 4 -- decision reconstruction
# ---------------------------------------------------------------------------

def test_decision_reconstructs_the_t0_belief():
    decision = reconstruct_decision(record([1.0860]))
    assert decision.direction == "BUY"
    assert decision.entry_price == 1.0850
    assert decision.stated_probability == pytest.approx(0.725)
    assert decision.synthesis_hash


def test_decision_never_consults_the_outcome():
    """
    Reconstruction must be what reality is compared against, not something
    already contaminated by knowing how it ended.
    """
    won = reconstruct_decision(record([1.0890], close=1.0890, winning=True))
    lost = reconstruct_decision(record([1.0890], close=1.0830, winning=False))
    assert won.to_dict() == lost.to_dict()


# ---------------------------------------------------------------------------
# Item 5 -- the four firsts (readme 17)
# ---------------------------------------------------------------------------

def peaked_then_reversed():
    return record([1.0860, 1.0890, 1.0875, 1.0845, 1.0830], close=1.0830)


def test_all_four_firsts_are_computed():
    result = replay_trade(peaked_then_reversed())
    for name in ("first_anomaly", "first_prediction_error",
                 "first_decision_error", "first_material_divergence"):
        assert result["divergences"][name] is not None, name


def test_the_firsts_are_genuinely_distinct():
    """
    Readme 17: 'not necessarily the same timestamp'. The gap IS the
    diagnosis -- an anomaly before the damage means a warning existed and
    nothing acted on it.
    """
    divergences = replay_trade(peaked_then_reversed())["divergences"]
    assert divergences["first_anomaly"]["index"] < \
        divergences["first_material_divergence"]["index"]
    assert divergences["anomaly_preceded_divergence"] is True


def test_a_clean_winner_has_no_divergences():
    """Guards against a detector that fires on everything."""
    divergences = replay_trade(
        record([1.0860, 1.0870, 1.0880, 1.0890], close=1.0890, winning=True)
    )["divergences"]
    assert divergences["first_anomaly"] is None
    assert divergences["first_prediction_error"] is None
    assert divergences["first_material_divergence"] is None


def test_material_threshold_separates_noise_from_breakage():
    small = replay_trade(record([1.0860, 1.0844]))["divergences"]
    assert small["first_anomaly"] is not None            # 0.3R adverse
    assert small["first_material_divergence"] is None    # below 0.5R

    large = replay_trade(record([1.0860, 1.0835]))["divergences"]
    assert large["first_material_divergence"] is not None


def test_decision_error_requires_a_real_gain_given_back():
    """A trade that never gained cannot have given anything back."""
    divergences = replay_trade(record([1.0845, 1.0838, 1.0830]))["divergences"]
    assert divergences["first_decision_error"] is None
    assert divergences["first_prediction_error"] is not None


def test_decision_error_detail_is_readable():
    """
    A 2.25R giveback from a 2.0R peak reads as impossible until you see it
    ended below entry, so the message names both ends.
    """
    detail = replay_trade(peaked_then_reversed())[
        "divergences"]["first_decision_error"]["detail"]
    assert "peak" in detail and "given back" in detail


def test_earliest_divergence_is_reported():
    divergences = replay_trade(peaked_then_reversed())["divergences"]
    assert divergences["earliest"]["index"] == min(
        divergences[k]["index"] for k in
        ("first_anomaly", "first_prediction_error",
         "first_decision_error", "first_material_divergence")
        if divergences[k])


# ---------------------------------------------------------------------------
# Item 6 -- attribution (readme 18)
# ---------------------------------------------------------------------------

def test_attribution_returns_candidates_not_causes():
    """
    Readme 18 requires distinguishing correlation from causation. A component
    present at a loss is a suspect, not a cause.
    """
    attribution = replay_trade(peaked_then_reversed())["attribution"]
    assert attribution["responsible_component_candidates"]
    assert "candidates" in attribution["caveat"]
    assert get_status()["attribution_claims_causation"] is False


def test_candidates_are_ranked_by_confidence():
    candidates = replay_trade(peaked_then_reversed())[
        "attribution"]["responsible_component_candidates"]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ranks = [order[c["confidence"]] for c in candidates]
    assert ranks == sorted(ranks)


def test_wide_spread_is_attributed_with_high_confidence():
    """Cost decides outcomes arithmetically, before any market read."""
    trade = build_trade(ticket=5)
    trade["entry"].update({"price": 1.0850, "stop_loss": 1.0830,
                           "spread_at_entry": 12.0})
    for point, price in zip(trade["price_evolution"], [1.0860, 1.0830]):
        point["price"] = price
    trade["close_data"]["close_price"] = 1.0830

    attribution = replay_trade(extract_replay_records([trade])[0])["attribution"]
    spread = [c for c in attribution["responsible_component_candidates"]
              if c["component"] == FailureClass.SPREAD.value]
    assert spread and spread[0]["confidence"] == "HIGH"


def test_single_trade_miscalibration_is_low_confidence():
    """One trade cannot establish that a probability is miscalibrated."""
    candidates = replay_trade(peaked_then_reversed())[
        "attribution"]["responsible_component_candidates"]
    calibration = [c for c in candidates
                   if c["component"] == FailureClass.CALIBRATION.value]
    assert calibration and calibration[0]["confidence"] == "LOW"


def test_unreconstructable_trade_is_attributed_to_data():
    trade = build_trade(ticket=6)
    trade["entry"]["stop_loss"] = None
    attribution = replay_trade(extract_replay_records([trade])[0])["attribution"]
    assert attribution["failure_class"] == FailureClass.DATA.value


# ---------------------------------------------------------------------------
# Replay and verification surface
# ---------------------------------------------------------------------------

def test_replay_produces_a_complete_result():
    result = replay_trade(peaked_then_reversed())
    for key in ("replay_version", "trade_id", "events", "event_stream_hash",
                "decision", "reality", "divergences", "attribution", "outcome"):
        assert key in result, key


def test_replay_trades_skips_broken_records(trades):
    records = extract_replay_records(trades)
    assert len(replay_trades(records + [None, "junk"])) == len(records)


def test_status_states_what_is_not_built():
    """
    This list once said "not yet built" long after most of it was built --
    in a status endpoint, which is the place a stale claim is most likely to
    be believed without checking. It now names only what is genuinely absent,
    and says where the rest lives.
    """
    status = get_status()
    assert status["phase"].startswith("3")
    assert all(status["implements"].values())
    assert status["not_yet_built"] == ["stress_replay"]
    assert len(status["four_firsts"]) == 4


def test_status_locates_the_phase_3_items_built_elsewhere():
    """A claim that something exists has to say where."""
    import importlib
    import os

    built = get_status()["built_elsewhere"]
    for item in ("counterfactual_branching", "ablation", "historical_simulator",
                 "simulator_replay_consistency_tests"):
        assert built.get(item), item

    # The two that name a module path are checked to actually exist, so this
    # cannot rot into a second stale claim.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(root, "ai", "aireplay", "counterfactual.py"))
    assert os.path.exists(os.path.join(root, "ai", "aireplay", "consistency.py"))
    assert importlib.import_module("ai.model_governance")


def test_status_states_the_pre_trade_limitation():
    """Honest about what missing snapshots do and do not prevent."""
    limitation = get_status()["limitation"]
    assert "CANDIDATE_DETECTED" in limitation
    assert "after entry" in limitation


def test_self_check_passes(trades):
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["stream_is_ordered"] is True
    assert report["checks"]["deterministic"] is True
    assert len(report["checks"]["divergences_computed"]) == 4


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["records"] == 0


# ---------------------------------------------------------------------------
# The exit belongs on the path
#
# Regression found by running the CLI on the standard fixture rather than a
# bespoke one: the reality path ended at the last SAMPLE before the close, not
# at the close. On a trade closing at +2R after a final observation at +0.4R
# it reported 0.4R -- understating every outcome, capping the oracle bound
# BELOW the actual return (capture ratio 1.2), and putting the three
# simulators into permanent disagreement.
# ---------------------------------------------------------------------------

def test_reality_path_ends_at_the_exit_not_the_last_sample():
    trade = build_trade(ticket=1, points=3, winning=True)
    canonical = extract_replay_records([trade])[0]

    reality = reconstruct_reality(canonical)
    assert reality[-1].price == canonical.outcome["exit_price"]
    assert reality[-1].return_r == pytest.approx(2.0)


def test_oracle_bound_is_never_below_the_actual_return():
    """An upper bound smaller than the thing it bounds is not a bound."""
    from ai.aireplay.counterfactual import branch_trade

    for winning in (True, False):
        canonical = extract_replay_records(
            [build_trade(ticket=1, points=3, winning=winning)])[0]
        comparison = branch_trade(canonical)["comparison"]
        if comparison and comparison.get("oracle_bound_r") is not None:
            assert comparison["actual_r"] <= comparison["oracle_bound_r"]


def test_all_simulators_agree_on_the_standard_fixture():
    """
    The bespoke fixtures agreed while the standard one did not. Pin the
    standard one so a future change cannot quietly reintroduce the drift.
    """
    from ai.aireplay.consistency import consistency_report

    records = extract_replay_records(
        [build_trade(ticket=i, points=3 + i % 4, winning=i % 2 == 0)
         for i in range(1, 13)])
    summary = consistency_report(records)
    assert summary["verdict"] == "CONSISTENT", summary["examples"]
    assert summary["disagreement_rate"] == 0.0
