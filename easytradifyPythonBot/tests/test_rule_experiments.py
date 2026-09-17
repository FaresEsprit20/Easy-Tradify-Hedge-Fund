"""
Rule experiments: test a veto, then change it.

Motivated by a real finding. Replaying 215 MT5 trades with their analysis
recomputed from bars showed the ADX choppy-market veto pointing the wrong way
-- the trades it blocks were the only profitable group in the account, and the
trades it approves lose. At p=0.49 that settles nothing, which is exactly why
it becomes an experiment rather than an edit.

This code decides whether a live trade is blocked, so nearly every test here
asserts a refusal:

  * OFF by default, and every uncertain path leaves the veto ACTIVE. The
    failure that matters is suppressing a veto by accident, never keeping one.
  * No recommendation until the verdict is actionable -- significant AND
    directionally clear. A module whose output is "change a live trading rule"
    must not speak on an interim reading.
"""

import os

import pytest

from ai import rule_experiments as rx
from core.veto_engine import VetoEngine

FLAG = "AI_RULE_EXPERIMENTS"


@pytest.fixture
def experiments_on():
    previous = os.environ.get(FLAG)
    os.environ[FLAG] = "1"
    yield
    if previous is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previous


@pytest.fixture
def experiments_off():
    previous = os.environ.get(FLAG)
    os.environ.pop(FLAG, None)
    yield
    if previous is not None:
        os.environ[FLAG] = previous


# ---------------------------------------------------------------------------
# Failing safe
# ---------------------------------------------------------------------------

def test_off_by_default(experiments_off):
    assert rx.is_enabled() is False
    assert rx.should_suppress("choppy_market", "EURUSD") is False


def test_veto_engine_is_unchanged_when_experiments_are_off(experiments_off):
    """The whole live path must behave exactly as it does today."""
    engine = VetoEngine()
    assert engine._veto_active("choppy_market") is True
    assert engine._veto_active("choppy_market", unit_id="EURUSD") is True
    assert engine._veto_active("extreme_volatility", unit_id="EURUSD") is True


def test_explicit_disable_still_works(experiments_off):
    engine = VetoEngine()
    engine.disabled_vetos = {"choppy_market"}
    assert engine._veto_active("choppy_market") is False


def test_every_uncertain_path_keeps_the_veto_active(experiments_on):
    assert rx.should_suppress("not_an_experiment", "EURUSD") is False
    assert rx.should_suppress("choppy_market", None) is False
    engine = VetoEngine()
    assert engine._veto_active("choppy_market", unit_id=None) is True


def test_suppression_never_raises(experiments_on):
    for unit in (None, "", 0, [], {"weird": object()}):
        rx.should_suppress("choppy_market", unit)
        VetoEngine()._veto_active("choppy_market", unit_id=unit)


def test_only_the_experiment_veto_is_affected(experiments_on):
    """One experiment must not silently disable a different veto."""
    engine = VetoEngine({"disabled_vetos": ()})     # every check active: only the experiment may suppress
    for symbol in ("EURUSD", "GBPUSD", "XAUUSD", "USDCAD"):
        assert engine._veto_active("extreme_volatility", unit_id=symbol) is True
        assert engine._veto_active("news_veto", unit_id=symbol) is True


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def test_assignment_is_deterministic(experiments_on):
    units = ["SYM%d" % i for i in range(200)]
    first = [rx.should_suppress("choppy_market", u) for u in units]
    second = [rx.should_suppress("choppy_market", u) for u in units]
    assert first == second


def test_assignment_actually_splits(experiments_on):
    units = ["SYM%d" % i for i in range(400)]
    arms = [rx.should_suppress("choppy_market", u) for u in units]
    share = sum(arms) / len(arms)
    assert 0.05 < share < 0.45, share


# ---------------------------------------------------------------------------
# The recommendation -- the actual goal
# ---------------------------------------------------------------------------

def test_no_recommendation_without_evidence():
    """
    The default in a live trading system is to change nothing. A module that
    recommends a rule change on an interim reading is worse than no experiment.
    """
    change = rx.recommended_change("choppy_market")
    assert change["decision"] == "NO CHANGE"
    assert change["actionable"] is False
    assert change["reason"]


def test_unknown_experiment_is_rejected():
    assert "error" in rx.recommended_change("no_such_veto")
    assert "error" in rx.results("no_such_veto")


def test_the_experiment_defines_both_outcomes():
    """
    An experiment that only says what to do if it wins is not an experiment.
    """
    spec = rx.EXPERIMENTS["choppy_market"]
    assert spec["rule_change_if_test_wins"]
    assert spec["rule_change_if_control_wins"]


def test_the_experiment_carries_the_evidence_that_motivated_it():
    """Three months from now, someone has to be able to see why this ran."""
    evidence = rx.EXPERIMENTS["choppy_market"]["prior_evidence"]
    assert evidence["vetoed_n"] == 118
    assert evidence["approved_n"] == 97
    assert evidence["p_value"] == 0.49
    assert "not significant" in evidence["caveat"]


def test_status_states_what_it_fails_safe_to():
    status = rx.get_status()
    assert status["default"] == "OFF"
    assert "veto active" in status["fails_safe_to"]
    assert status["assignment_limitation"]


def test_self_check_proves_the_safety_properties():
    report = rx.self_check()
    assert report["ok"] is True, report.get("error")
    for name in ("disabled_suppresses_nothing", "unknown_veto_fails_safe",
                 "missing_id_fails_safe", "premature_change_refused"):
        assert report["checks"][name] is True


# ---------------------------------------------------------------------------
# The rule fixes themselves
#
# Measured on 215 real trades with the analysis recomputed at each entry:
#
#   rule set                                    n    mean R   win %   total R
#   today (choppy blocks, others inert)        97   -0.0890   37.1%     -8.6
#   invert choppy                             118   +0.0189   48.3%     +2.2
#   + enable against_ema                       91   +0.1255   49.5%    +11.4
#   + enable h1_conflict                       71   +0.1733   50.7%    +12.3
#
# The rule base was inverted in both directions at once: the veto that blocked
# the only profitable group was the one running, and the two that correctly
# identified losing setups could not stop a trade.
#
# THIS IS A POST-HOC FIT. Three rules were selected on the same 215 trades
# they were measured on, and n falls from 97 to 71 doing it. The tests below
# pin the BEHAVIOUR, not the claim -- the claim is what rule_experiments runs
# forward.
# ---------------------------------------------------------------------------

def test_choppy_rule_behaves_as_the_original_when_blocking():
    """
    The held-out evidence still favours "block". Recorded here because the
    live default no longer matches it, and the reason must not be lost.

    The invert default was once set on a full-sample measurement (+0.2623R,
    37.1% -> 50.7% win). Chronologically split it collapses:

        rule set              TRAIN        TEST     test win
        original rules      +0.0455R    -0.0348R      43.6%
        full "fix"          -0.0356R    -0.3789R      35.7%

    The original rules are best on held-out data. A default has to survive
    data it was not fitted on -- so "block" is what the evidence supports,
    and this test pins that behaviour whenever the mode is set.
    """
    engine = VetoEngine({"choppy_market_mode": "block"})
    assert engine.choppy_market_mode == "block"
    # 5.0 / 40.0 rather than 10.0 / 40.0: these assert the MODE (block vetoes a
    # choppy tape, lets a trending one through), not where the line sits. The
    # DEFAULT threshold has moved 25 -> 15 -> 10 as the veto was loosened for
    # data collection, and 10.0 now sits exactly on the boundary. Picking a
    # value well inside the choppy band keeps this testing the rule rather
    # than the current tuning.
    assert engine.check_choppy_market(5.0, "EURUSD")[0] is True
    assert engine.check_choppy_market(40.0, "EURUSD")[0] is False


def test_the_live_default_is_off_for_data_collection():
    """
    The shipped default is "off", which is NOT what the held-out comparison
    above supports. It is a deliberate data-collection setting: the choppy
    veto was the single largest blocker on the live tape (95 rejections in one
    window even after the ADX floor was cut 25 -> 15 -> 10), and trade count
    is currently the binding constraint on the whole research programme.

    This test exists so the divergence is explicit rather than discovered.
    Restore "block" -- and update this test -- before drawing any conclusion
    about expectancy from trades collected under it.
    """
    assert VetoEngine().choppy_market_mode == "off"
    # Off means off: neither a choppy nor a trending tape is vetoed here.
    assert VetoEngine().check_choppy_market(5.0, "EURUSD")[0] is False
    assert VetoEngine().check_choppy_market(40.0, "EURUSD")[0] is False


def test_the_hypothesis_is_still_available_for_an_experiment():
    engine = VetoEngine({"choppy_market_mode": "invert",
                         "enable_trend_vetoes": True})
    assert engine.check_choppy_market(40.0, "EURUSD")[0] is True
    assert engine.check_against_ema("BUY", 1.0800, 1.0900)[0] is True


def test_choppy_rule_supports_all_three_modes():
    # 5.0 is inside the choppy band whatever the current threshold — see the
    # note in test_choppy_rule_defaults_to_the_original_behaviour.
    assert VetoEngine({"choppy_market_mode": "block"}).check_choppy_market(
        5.0, "EURUSD")[0] is True
    assert VetoEngine({"choppy_market_mode": "off"}).check_choppy_market(
        5.0, "EURUSD")[0] is False
    assert VetoEngine({"choppy_market_mode": "off"}).check_choppy_market(
        40.0, "EURUSD")[0] is False


def test_an_unknown_mode_falls_back_rather_than_crashing():
    assert VetoEngine({"choppy_market_mode": "nonsense"}).check_choppy_market(
        40.0, "EURUSD")[0] is True


def test_the_trend_vetoes_stay_inert_until_validated():
    """
    against_ema and h1_conflict measured -0.215R and -0.164R on the setups
    they identify -- on the full sample. Enabling them made the held-out
    result WORSE (-0.358R, 28.6% win), so they stay off by default and the
    implementations remain available for an experiment.
    """
    engine = VetoEngine()
    assert engine.enable_trend_vetoes is False
    # The implementations still work when explicitly enabled.
    live = VetoEngine({"enable_trend_vetoes": True})
    assert live.check_against_ema("BUY", 1.0800, 1.0900)[0] is True
    assert live.check_h1_conflict("BUY", "BEARISH")[0] is True


def test_the_working_vetoes_pass_aligned_setups():
    engine = VetoEngine()
    assert engine.check_against_ema("BUY", 1.0950, 1.0900)[0] is False
    assert engine.check_h1_conflict("BUY", "NEUTRAL")[0] is False
    assert engine.check_h1_conflict("BUY", "BULLISH")[0] is False


def test_missing_inputs_do_not_veto():
    """A missing EMA or trend must not block a trade by accident."""
    engine = VetoEngine()
    assert engine.check_against_ema("BUY", 1.08, 0)[0] is False
    assert engine.check_against_ema("BUY", 0, 1.09)[0] is False
    assert engine.check_h1_conflict("BUY", "")[0] is False


def test_every_rule_change_is_revertible_by_config():
    """
    One config value each. A change to a live trading rule that cannot be
    undone without a code edit is not a change anyone should ship.
    """
    engine = VetoEngine({"choppy_market_mode": "invert",
                         "enable_trend_vetoes": True})
    assert engine.choppy_market_mode == "invert"
    assert engine.enable_trend_vetoes is True
    assert engine.check_choppy_market(40.0, "EURUSD")[0] is True


# ---------------------------------------------------------------------------
# rvam CONVICTION_MOVE
#
# Measured on 215 real trades with the analysis recomputed at entry:
#   aligned  (scored +10)  n=10  mean -0.5389R  win 10.0%
#   opposing (scored -12)  n=11  mean +0.1765R  win 45.5%
#
# The branch rewarded a 10%-win condition and penalised one performing at the
# base rate. Its own docstring says CONVICTION_MOVE "is only a mild
# endorsement... WITHOUT SAYING IT WILL CONTINUE" while the code awarded +10 --
# larger than ABSORPTION's +8. The ABSORPTION branch, which applies the
# opposite prior, measures correct.
#
# Default is neutral, NOT inverted: the evidence that +10 is wrong is good,
# the evidence that -10 is right is 21 trades at p=0.15.
# ---------------------------------------------------------------------------

def _rvam(classification, move_dir="UP"):
    return {"available": True, "classification": classification,
            "direction": move_dir}


def test_conviction_move_no_longer_rewards_the_losing_condition():
    import os

    from core.rvam import score_rvam_confirmation

    os.environ.pop("RVAM_CONVICTION_MODE", None)
    aligned = score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "BUY")
    assert aligned["score"] == 0, "aligned conviction still contributes points"
    assert "contradicted by measurement" in aligned["reason"]


def test_conviction_move_supports_all_three_modes():
    import os

    from core.rvam import score_rvam_confirmation

    try:
        os.environ["RVAM_CONVICTION_MODE"] = "continuation"
        assert score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "BUY")["score"] == 10
        os.environ["RVAM_CONVICTION_MODE"] = "exhaustion"
        assert score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "BUY")["score"] == -10
        assert score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "SELL")["score"] == 12
        os.environ["RVAM_CONVICTION_MODE"] = "neutral"
        assert score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "BUY")["score"] == 0
    finally:
        os.environ.pop("RVAM_CONVICTION_MODE", None)


def test_an_unknown_mode_falls_back_to_neutral():
    import os

    from core.rvam import score_rvam_confirmation

    try:
        os.environ["RVAM_CONVICTION_MODE"] = "nonsense"
        assert score_rvam_confirmation(_rvam("CONVICTION_MOVE"), "BUY")["score"] == 0
    finally:
        os.environ.pop("RVAM_CONVICTION_MODE", None)


def test_the_branch_that_measured_correct_is_untouched():
    """
    ABSORPTION returned +0.294R at 57.9% win on the condition it rewards.
    Only the branch the data contradicted was changed.
    """
    from core.rvam import score_rvam_confirmation

    assert score_rvam_confirmation(_rvam("ABSORPTION"), "SELL")["score"] == 8
    assert score_rvam_confirmation(_rvam("ABSORPTION"), "BUY")["score"] == -6


def test_the_unparticipated_warning_is_untouched():
    """The failure this module exists to catch is not part of this change."""
    from core.rvam import score_rvam_confirmation

    assert score_rvam_confirmation(_rvam("UNPARTICIPATED"), "BUY")["score"] == -8
    assert score_rvam_confirmation(
        _rvam("UNPARTICIPATED"), "BUY", is_breakout=True)["score"] == -15
