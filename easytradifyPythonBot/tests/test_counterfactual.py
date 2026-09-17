"""
Counterfactual branching -- Phase 3 item 7.

The load-bearing tests: nothing invents a price, the entry basis is the fill
rather than the first observation, and oracle branches are kept out of the
headline ranking.
"""

import pytest

from ai.aireplay import extract_replay_records
from ai.aireplay.counterfactual import (
    COUNTERFACTUAL_VERSION,
    Branch,
    aggregate_branches,
    branch_entry_timing,
    branch_exit_policy,
    branch_stop_policy,
    branch_trade,
    build_path,
    compare_branches,
    get_status,
    self_check,
)

from conftest import build_trade


def record(prices, close=None, ticket=901, entry=1.0850, stop=1.0830,
           target=1.0890, direction="BUY"):
    trade = build_trade(ticket=ticket, points=len(prices))
    trade["entry"].update({"price": entry, "stop_loss": stop, "take_profit": target})
    trade["direction"] = direction
    for point, price in zip(trade["price_evolution"], prices):
        point["price"] = price
    trade["close_data"]["close_price"] = close if close is not None else prices[-1]
    return extract_replay_records([trade])[0]


DIP_THEN_RUN = [1.0838, 1.0845, 1.0870, 1.0890, 1.0900]


# ---------------------------------------------------------------------------
# The entry basis
# ---------------------------------------------------------------------------

def test_actual_branch_uses_the_fill_not_the_first_observation():
    """
    Regression: price_evolution[0] is the first observation AFTER entry, not
    the fill. Scoring from it turned a +2R target into +6.5R and made the
    actual return exceed its own oracle bound.
    """
    result = branch_trade(record(DIP_THEN_RUN, close=1.0900))
    actual = next(b for b in result["branches"] if b["name"] == "actual")
    assert actual["realized_r"] == pytest.approx(2.0)
    assert actual["exit_reason"] == "target"


def test_actual_never_exceeds_the_oracle_bound():
    """The oracle is an upper bound by construction; exceeding it is a bug."""
    comparison = branch_trade(record(DIP_THEN_RUN, close=1.0900))["comparison"]
    assert comparison["actual_r"] <= comparison["oracle_bound_r"]
    assert comparison["capture_ratio"] <= 1.0


def test_delayed_entry_fills_at_the_observed_price():
    path = build_path(record(DIP_THEN_RUN, close=1.0900))
    branches = {b.name: b for b in branch_entry_timing(path)}
    assert branches["enter_after_1"].params["fill_price"] == pytest.approx(1.0838)


# ---------------------------------------------------------------------------
# Oracle separation
# ---------------------------------------------------------------------------

def test_oracle_branches_are_marked():
    branches = branch_exit_policy(build_path(record(DIP_THEN_RUN)))
    oracle = next(b for b in branches if b.name == "exit_at_peak")
    assert oracle.implementable is False
    assert "hindsight" in (oracle.note or "").lower() or "not an achievable" in (
        oracle.note or "")


def test_oracles_are_excluded_from_the_ranking():
    """
    An oracle always wins, so ranking it with implementable policies would
    report a guaranteed improvement on every trade ever examined.
    """
    comparison = branch_trade(record(DIP_THEN_RUN, close=1.0900))["comparison"]
    assert "exit_at_peak" in comparison["oracles_excluded_from_ranking"]
    assert all(b["implementable"] for b in comparison["ranked"])
    assert comparison["best_implementable"]["implementable"] is True


def test_oracle_still_reported_as_a_bound():
    """It is not discarded -- it measures what was available to capture."""
    comparison = branch_trade(record(DIP_THEN_RUN, close=1.0900))["comparison"]
    assert comparison["oracle_bound_r"] is not None
    assert comparison["capture_ratio"] is not None


# ---------------------------------------------------------------------------
# Branch families (readme 19)
# ---------------------------------------------------------------------------

def test_entry_timing_finds_the_better_entry():
    """Entering after the dip keeps the structural stop but risks far less."""
    comparison = branch_trade(record(DIP_THEN_RUN, close=1.0900))["comparison"]
    assert comparison["better_alternative_existed"] is True
    assert comparison["best_implementable"]["name"].startswith("enter_after")
    assert comparison["improvement_r"] > 0


def test_cancel_is_always_available_and_costs_nothing():
    branches = {b.name: b for b in branch_entry_timing(build_path(record(DIP_THEN_RUN)))}
    assert branches["cancel"].realized_r == 0.0
    assert branches["cancel"].implementable is True


def test_tighter_stop_can_convert_a_winner_into_a_loss():
    branches = {b.name: b for b in
                branch_stop_policy(build_path(record(DIP_THEN_RUN, close=1.0900)))}
    assert branches["stop_x0.5"].exit_reason == "stop"
    assert branches["stop_x0.5"].realized_r < 0


def test_wider_stop_is_scored_in_its_own_r():
    """
    A wider stop risks the same money over a longer distance, so it takes a
    smaller position. Scoring it in the original R would flatter it for free.
    """
    branches = {b.name: b for b in
                branch_stop_policy(build_path(record(DIP_THEN_RUN, close=1.0900)))}
    assert branches["stop_x2.0"].realized_r < branches["stop_x1.5"].realized_r


def test_adverse_exit_policy_is_implementable():
    branches = branch_exit_policy(build_path(record([1.0840, 1.0835, 1.0830])))
    policy = next(b for b in branches if b.name.startswith("exit_on_"))
    assert policy.implementable is True


# ---------------------------------------------------------------------------
# Honesty constraints
# ---------------------------------------------------------------------------

def test_stop_is_checked_before_target():
    """
    The pessimistic ordering is in place, but scalar price observations cannot
    be beyond both levels at once -- so it is currently unexercised, and the
    status says so rather than claiming an active safeguard.
    """
    status = get_status()
    assert status["ambiguous_bar_policy"] == "stop_first"
    assert status["ambiguity_currently_reachable"] is False
    assert "OHLC" in status["ambiguity_note"] or "highs and lows" in status[
        "ambiguity_note"]


def test_a_price_through_the_stop_exits_at_the_stop():
    """Whatever happens later in the path, the stop ends it."""
    result = branch_trade(record([1.0825, 1.0900], close=1.0900))
    actual = next(b for b in result["branches"] if b["name"] == "actual")
    assert actual["exit_reason"] == "stop"
    assert actual["realized_r"] == pytest.approx(-1.0)


def test_nothing_is_invented():
    assert get_status()["invents_prices"] is False
    assert branch_trade(record(DIP_THEN_RUN))["uses_only_historical_prices"] is True


def test_short_direction_is_handled():
    result = branch_trade(record([1.0840, 1.0830], close=1.0830,
                                 entry=1.0850, stop=1.0870, target=1.0810,
                                 direction="SELL"))
    actual = next(b for b in result["branches"] if b["name"] == "actual")
    assert actual["realized_r"] > 0


def test_unreconstructable_trade_is_skipped_not_guessed():
    trade = build_trade(ticket=1)
    trade["entry"]["stop_loss"] = None
    result = branch_trade(extract_replay_records([trade])[0])
    assert result["branches"] == []
    assert result["skipped"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_aggregate_measures_policies_not_single_rescues():
    """
    A branch that rescues one trade and ruins four is a worse policy than the
    actual one, and only the aggregate shows that.
    """
    helped = [branch_trade(record(DIP_THEN_RUN, close=1.0900, ticket=i))
              for i in range(1, 4)]
    hurt = [branch_trade(record([1.0870, 1.0890, 1.0900], close=1.0900, ticket=i))
            for i in range(10, 14)]

    aggregate = aggregate_branches(helped + hurt)
    assert aggregate["trades"] == 7
    assert aggregate["actual_mean_r"] is not None
    assert all("delta_vs_actual_r" in p for p in aggregate["policies"])


def test_aggregate_excludes_oracles():
    results = [branch_trade(record(DIP_THEN_RUN, close=1.0900, ticket=i))
               for i in range(1, 4)]
    names = {p["policy"] for p in aggregate_branches(results)["policies"]}
    assert "exit_at_peak" not in names


def test_aggregate_states_it_has_not_shown_generalisation():
    results = [branch_trade(record(DIP_THEN_RUN, close=1.0900, ticket=i))
               for i in range(1, 3)]
    assert "out of sample" in aggregate_branches(results)["caveat"]


def test_aggregate_handles_no_results():
    assert aggregate_branches([])["trades"] == 0


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_declares_the_oracle_separation():
    status = get_status()
    assert status["separates_oracle_from_implementable"] is True
    assert "hindsight" in status["why"]


def test_self_check_passes(trades):
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["ranking_is_implementable_only"] is True
    assert "exit_at_peak" in report["checks"]["oracles_excluded"]


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["records"] == 0
