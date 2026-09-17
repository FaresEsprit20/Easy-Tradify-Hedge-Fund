"""
Entry foundation v2 (2026-09-17): the entry decision is one rule table.

Every rule is evaluated on every decision and published, the first blocking rule
names the entry_status, "observe" rules are recorded but never block, and each
rule is checked in one place -- the probability once (with the caller's floor),
the candle's age nowhere.
"""

import pathlib

import pytest

from core import asset_analysis_config as cfg
from core.entry_engine import BLOCK, OBSERVE, RULE_ORDER, RULE_STATUS, EntryEngine
from core.veto_engine import VetoEngine

MICRO_QUIET = ({"available": True, "timing_confidence": 50}, False, False, False, False)
MICRO_ABSORPTION = ({"available": True}, True, False, False, False)
MICRO_UNAVAILABLE = ({"available": False, "reason": "replay"}, False, False, False, False)

BULLISH_BAR = {"open": 1.0840, "high": 1.0852, "low": 1.0839, "close": 1.0851,
               "body_pips": 11.0, "upper_wick_pips": 1.0, "lower_wick_pips": 1.0,
               "candle_type": "normal"}
BEARISH_BAR = {"open": 1.0851, "high": 1.0852, "low": 1.0839, "close": 1.0840,
               "body_pips": 11.0, "upper_wick_pips": 1.0, "lower_wick_pips": 1.0,
               "candle_type": "normal"}

# price sitting on a grade-B demand zone, BUY: every rule can pass
AT_ZONE = dict(symbol="EURUSD", best_direction="BUY", current_price=1.08400,
               zone_level=1.08400, zone_type="DEMAND", zone_grade="B",
               candle_data=BULLISH_BAR, volume_spike=True, at_poi=False,
               best_probability=78.0, pip_size=0.0001, atr_pips=10.0,
               probability_floor=75.0)


def _engine(micro=MICRO_ABSORPTION, **config):
    # every rule blocking unless a test says otherwise: these tests pin the
    # mechanism, not the modes the evidence currently sets in the config
    config["rule_modes"] = {**{name: BLOCK for name in RULE_ORDER}, **config.get("rule_modes", {})}
    engine = EntryEngine(config)
    engine.get_micro_structure_signals = lambda *a, **k: (dict(micro[0]),) + tuple(micro[1:])
    return engine


def _decide(engine, **overrides):
    return engine.get_entry_decision(**{**AT_ZONE, **overrides})


def test_every_rule_is_published_on_every_decision_even_when_the_first_blocks():
    d = _decide(_engine(), zone_level=None)
    assert list(d["rules"]) == list(RULE_ORDER)
    for name, r in d["rules"].items():
        assert set(r) == {"passed", "mode", "value", "threshold", "why"}, name
    assert d["entry_status"] == "INVALID_ZONE"
    # later rules were still judged: the probability and the candle are measurable without a zone
    assert d["rules"]["probability"]["passed"] is True
    assert d["rules"]["confirmation"]["passed"] is True
    assert d["rules"]["discount"]["passed"] is None          # no zone: not measurable, not a failure


def test_all_rules_holding_enters_as_a_confirmed_discount():
    d = _decide(_engine())
    assert d["should_enter"] is True and d["blocked_by"] == []
    assert d["entry_status"] == "CONFIRMED_DISCOUNT"
    assert d["simple_action"] == "ENTER NOW" and d["execution"] == "EXECUTE_MARKET_ORDER"


def test_the_first_blocking_rule_names_the_status_and_all_blockers_are_listed():
    d = _decide(_engine(MICRO_QUIET), current_price=1.08600, candle_data=BEARISH_BAR,
                volume_spike=False, best_probability=70.0)
    assert d["should_enter"] is False
    assert d["blocked_by"] == ["signals", "probability", "discount", "confirmation", "timing"]
    assert d["entry_status"] == RULE_STATUS["signals"] == "NO_POTENTIAL"
    assert "also blocked by: probability, discount, confirmation, timing" in d["reason"]


@pytest.mark.parametrize("rule, overrides, status", [
    ("zone", dict(zone_grade="E"), "INVALID_ZONE"),
    ("probability", dict(best_probability=70.0), "INSUFFICIENT_PROBABILITY"),
    ("discount", dict(current_price=1.08600), "WAITING_DISCOUNT"),
    ("confirmation", dict(candle_data=BEARISH_BAR), "WAITING_CONFIRMATION"),
])
def test_each_rule_alone_blocks_with_its_own_status(rule, overrides, status):
    d = _decide(_engine(), **overrides)
    assert d["blocked_by"] == [rule] and d["entry_status"] == status


def test_timing_alone_blocks_with_poor_timing():
    d = _decide(_engine(MICRO_QUIET))          # volume spike keeps the signals rule
    assert d["blocked_by"] == ["timing"] and d["entry_status"] == "POOR_TIMING"


def test_a_zone_on_the_wrong_side_fails_discount_quality():
    d = _decide(_engine(), zone_type="SUPPLY")
    assert "discount_quality" in d["blocked_by"]
    assert "implies SELL" in d["rules"]["discount_quality"]["why"]


def test_an_observed_rule_is_recorded_but_never_blocks():
    engine = _engine(rule_modes={"discount": OBSERVE})
    d = _decide(engine, current_price=1.08600)
    assert d["rules"]["discount"] == {**d["rules"]["discount"], "passed": False, "mode": OBSERVE}
    assert d["should_enter"] is True and d["blocked_by"] == []
    assert d["entry_status"] == "RULES_PASSED"
    assert "observed, not blocking: discount" in d["reason"]


def test_an_unknown_mode_blocks():
    engine = _engine(rule_modes={"discount": "maybe"})
    assert engine.rule_modes["discount"] == BLOCK


def test_the_config_table_names_every_rule_once():
    assert set(cfg.ENTRY_RULE_MODES) == set(RULE_ORDER)
    assert set(cfg.ENTRY_RULE_MODES.values()) <= {BLOCK, OBSERVE}


# ---------------------------------------------------------------------------
# probability: checked once, with the caller's floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("probability, passed, why", [
    (78.0, True, "inside 75-83%"),
    (74.9, False, "below the 75% floor"),
    (90.0, False, "above the 83% ceiling"),
])
def test_the_probability_band_uses_the_callers_floor(probability, passed, why):
    d = _decide(_engine(), best_probability=probability)
    r = d["rules"]["probability"]
    assert r["passed"] is passed and why in r["why"] and r["threshold"] == "75-83"


def test_without_a_floor_the_engine_default_applies():
    d = _decide(_engine(), probability_floor=None, best_probability=60.0)
    assert d["rules"]["probability"]["passed"] is True
    assert cfg.TRADE_PROBABILITY_MINIMUM <= 60.0


def test_asset_analysis_checks_the_probability_only_through_the_rule_table():
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert "best_probability < probability_floor" not in src
    assert "probability_floor=probability_floor" in src


# ---------------------------------------------------------------------------
# candle age judges nothing; timing has no candle or spread penalty
# ---------------------------------------------------------------------------

def test_the_engine_takes_no_candle_age_input():
    with pytest.raises(TypeError):
        _decide(_engine(), candle_progress_pct=5.0)
    with pytest.raises(TypeError):
        _decide(_engine(), candle_ready=False)


def test_timing_confidence_has_no_candle_or_spread_penalty():
    engine = EntryEngine()
    assert engine.calculate_timing_confidence(False, True, False) == 65      # momentum burst
    assert engine.calculate_timing_confidence(True, False, False) == 85      # absorption
    assert engine.calculate_timing_confidence(False, False, False) == 50     # nothing on the tape


def test_the_candle_age_veto_records_but_does_not_block():
    engine = VetoEngine()
    assert "candle_too_young" in engine.disabled_vetos
    assert engine._veto_active("candle_too_young") is False
    vetoed, reason = engine.check_candle_too_young(False, 2.0, 0, 50.0, False, False)
    assert vetoed is True                     # the verdict is still computed and recorded
    assert VetoEngine({"disabled_vetos": ()})._veto_active("candle_too_young") is True


def test_a_setup_at_one_percent_of_the_minute_is_not_vetoed_for_its_age():
    engine = VetoEngine({"choppy_market_mode": "off"})
    veto, reason, _ = engine.check_all_vetos(
        symbol="EURUSD", best_direction="BUY", adx_val=30.0, atr_pips=5.0, trend="BULLISH",
        current_price=1.0850, ema_200=1.0800, h1_trend="BULLISH", m15_div_score=0, m15_rsi=50.0,
        upper_wick_pips=0.2, lower_wick_pips=0.2, body_pips=2.0, volume_ratio=1.5,
        spread_valid=True, spread_pips=0.2, max_allowed_spread=3, entry_triggered=False,
        candle_progress_pct=1.0, is_already_in_trade=False, session_result={},
        signal_count=1, probability=78.0)
    assert "young" not in reason.lower()


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

def test_in_replay_timing_is_not_measurable_and_does_not_block():
    d = _decide(_engine(MICRO_UNAVAILABLE), is_replay=True)
    assert d["rules"]["timing"]["passed"] is None
    assert d["timing_bypassed_replay"] is True and d["should_enter"] is True


def test_live_an_unavailable_tick_feed_still_fails_timing():
    d = _decide(_engine(MICRO_UNAVAILABLE))
    assert d["rules"]["timing"]["passed"] is False and d["blocked_by"] == ["timing"]


# ---------------------------------------------------------------------------
# no session or news rules (operator, 2026-09-17)
# ---------------------------------------------------------------------------

def _news_says_veto(symbol, direction, tolerance):
    return True, "High-impact news in 10 min"


def _vetos(engine, **overrides):
    args = dict(symbol="EURUSD", best_direction="BUY", adx_val=30.0, atr_pips=5.0, trend="BULLISH",
                current_price=1.0850, ema_200=1.0800, h1_trend="BULLISH", m15_div_score=0, m15_rsi=50.0,
                upper_wick_pips=0.2, lower_wick_pips=0.2, body_pips=2.0, volume_ratio=1.5,
                spread_valid=True, spread_pips=0.2, max_allowed_spread=3, entry_triggered=True,
                candle_progress_pct=50.0, is_already_in_trade=False, session_result={},
                news_veto_func=_news_says_veto, signal_count=1, probability=78.0)
    args.update(overrides)
    return engine.check_all_vetos(**args)


def test_the_news_veto_records_but_does_not_block_or_start_a_cooldown():
    engine = VetoEngine({"choppy_market_mode": "off"})
    veto, reason, _ = _vetos(engine)
    assert veto is False
    assert engine.get_veto_record("EURUSD")["news_veto"]["vetoed"] is True
    assert engine.check_cooldown("EURUSD") == (False, "")


def test_with_every_veto_active_news_still_blocks_and_starts_the_cooldown():
    engine = VetoEngine({"choppy_market_mode": "off", "disabled_vetos": ()})
    veto, reason, _ = _vetos(engine)
    assert veto is True and "news" in reason.lower()
    assert engine.check_cooldown("EURUSD")[0] is True
