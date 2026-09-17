"""
Simulator / replay consistency -- Phase 3 item 14.

Three separate code paths walk a historical trade forward and compute a
return. This suite is the guard against them drifting apart -- the failure
mode this codebase has hit repeatedly with two swing detectors, two
lot-sizers and two liquidity-sweep detectors.
"""

import pytest

from ai.aireplay import extract_replay_records
from ai.aireplay.consistency import (
    CONSISTENCY_VERSION,
    MAGNITUDE_TOLERANCE_R,
    SimulatorResult,
    compare_simulators,
    consistency_report,
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


WINNER = ([1.0860, 1.0875, 1.0890], 1.0890)
LOSER = ([1.0840, 1.0830], 1.0830)


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

def test_all_three_simulators_run():
    comparison = compare_simulators(record(*WINNER))
    names = {s["simulator"] for s in comparison["simulators"]}
    assert names == {
        "replay_engine.reality",
        "counterfactual.actual",
        "ai_reinforcement.counterfactual",
    }


def test_simulators_agree_on_a_winner():
    """Three independently-written paths, different units, same answer."""
    comparison = compare_simulators(record(*WINNER))
    assert comparison["comparable"] is True
    assert comparison["consistent"] is True, comparison["disagreements"]

    returns = [s["final_return_r"] for s in comparison["simulators"]
               if s["available"]]
    assert all(r == pytest.approx(2.0, abs=MAGNITUDE_TOLERANCE_R) for r in returns)


def test_simulators_agree_on_a_loser():
    comparison = compare_simulators(record(*LOSER))
    assert comparison["consistent"] is True, comparison["disagreements"]
    assert all(s["sl_hit"] for s in comparison["simulators"] if s["available"])


def test_rl_simulator_receives_the_stop_and_target():
    """
    Regression: the adapter passed only price and direction, so RL's
    extract_sl_tp() saw NaN, exited at 'horizon_end' and reported tp_hit
    False on a trade that plainly hit its target. This module then reported
    that as drift -- a false alarm, and a consistency check that cries wolf
    trains you to ignore it.
    """
    result = next(s for s in compare_simulators(record(*WINNER))["simulators"]
                  if s["simulator"] == "ai_reinforcement.counterfactual")
    assert result["available"] is True
    assert result["exit_reason"] == "take_profit"
    assert result["tp_hit"] is True


def test_short_trades_agree():
    comparison = compare_simulators(
        record([1.0840, 1.0810], 1.0810, entry=1.0850, stop=1.0870,
               target=1.0810, direction="SELL"))
    assert comparison["consistent"] is True, comparison["disagreements"]


# ---------------------------------------------------------------------------
# Disagreement detection
# ---------------------------------------------------------------------------

def test_disagreement_on_magnitude_is_reported(monkeypatch):
    """The check must be capable of failing, or it proves nothing."""
    import ai.aireplay.consistency as module

    monkeypatch.setattr(
        module, "_rl_result",
        lambda trade: SimulatorResult(
            "ai_reinforcement.counterfactual", True, final_return_r=99.0))

    comparison = compare_simulators(record(*WINNER))
    assert comparison["consistent"] is False
    fields = {d["field"] for d in comparison["disagreements"]}
    assert "final_return_r" in fields


def test_disagreement_on_outcome_sign_is_high_severity(monkeypatch):
    import ai.aireplay.consistency as module

    monkeypatch.setattr(
        module, "_rl_result",
        lambda trade: SimulatorResult(
            "ai_reinforcement.counterfactual", True, final_return_r=-2.0))

    disagreements = compare_simulators(record(*WINNER))["disagreements"]
    sign = [d for d in disagreements if d["field"] == "outcome_sign"]
    assert sign and sign[0]["severity"] == "HIGH"


def test_hit_flag_disagreement_is_reported(monkeypatch):
    import ai.aireplay.consistency as module

    monkeypatch.setattr(
        module, "_rl_result",
        lambda trade: SimulatorResult(
            "ai_reinforcement.counterfactual", True,
            final_return_r=2.0, tp_hit=False, sl_hit=False))

    fields = {d["field"] for d in
              compare_simulators(record(*WINNER))["disagreements"]}
    assert "tp_hit" in fields


def test_tolerance_absorbs_legitimate_differences():
    """
    Implementations differ on whether the close price or the last observation
    ends the trade. That is not drift.
    """
    assert MAGNITUDE_TOLERANCE_R > 0
    comparison = compare_simulators(record([1.0860, 1.0870], close=1.0872))
    assert comparison["consistent"] is True


# ---------------------------------------------------------------------------
# Unavailability
# ---------------------------------------------------------------------------

def test_unavailable_simulator_is_reported_not_hidden():
    trade = build_trade(ticket=1)
    trade["entry"]["stop_loss"] = None
    comparison = compare_simulators(extract_replay_records([trade])[0])
    unavailable = [s for s in comparison["simulators"] if not s["available"]]
    assert unavailable
    assert all(s["error"] for s in unavailable)


def test_a_single_simulator_is_not_comparable():
    """One opinion is not agreement."""
    trade = build_trade(ticket=1)
    trade["entry"]["stop_loss"] = None
    comparison = compare_simulators(extract_replay_records([trade])[0])
    assert comparison["comparable"] is False


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------

def test_report_across_trades_is_consistent():
    records = ([record(*WINNER, ticket=i) for i in range(1, 4)]
               + [record(*LOSER, ticket=i) for i in range(10, 13)])
    summary = consistency_report(records)
    assert summary["verdict"] == "CONSISTENT"
    assert summary["disagreement_rate"] == 0.0
    assert summary["comparable"] == 6


def test_report_surfaces_a_drift_rate(monkeypatch):
    """
    One disagreeing trade is a bug to chase; a third of them means the
    implementations have genuinely drifted.
    """
    import ai.aireplay.consistency as module
    monkeypatch.setattr(
        module, "_rl_result",
        lambda trade: SimulatorResult(
            "ai_reinforcement.counterfactual", True, final_return_r=42.0))

    summary = consistency_report([record(*WINNER, ticket=i) for i in range(1, 4)])
    assert summary["verdict"] == "DRIFTED"
    assert summary["disagreement_rate"] == 1.0
    assert summary["examples"]


def test_report_handles_no_trades():
    summary = consistency_report([])
    assert summary["verdict"] == "NOT_COMPARABLE"
    assert summary["trades"] == 0


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def test_status_admits_the_duplication():
    """
    Honest about why this module exists: three implementations of one
    mechanic, the oldest of which predates the other two.
    """
    status = get_status()
    assert len(status["simulators_compared"]) == 3
    assert "predates" in status["known_duplication"]
    assert status["raises_on_disagreement"] is False


def test_self_check_reports_drift_without_failing(trades):
    """
    `ok` means the check ran. Drift is a finding to surface, not a reason to
    report the checker itself as broken.
    """
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["verdict"] in ("CONSISTENT", "DRIFTED")


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["records"] == 0
