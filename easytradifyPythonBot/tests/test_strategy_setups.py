"""
Each strategy group trades its own setup (core/strategy_setups.py, 2026-09-17):
the winning group's setup decides the entry and sets the stop, the target and a
lot that starts from the $200 trade size and only shrinks to hold the $4 budget.
"""

import pathlib

import pytest

from core import strategy_setups as ss
from core.entry_engine import BLOCK, OBSERVE, RULE_ORDER, SETUP_REPLACES, EntryEngine
from core.execution import volume_for_kept_stop

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _setup(direction="BUY", entry=1.0850, stop=1.0830, target=1.0880, **kw):
    return {"is_perfect_setup": True, "direction": direction, "entry_price": entry, "stop_loss": stop,
            "take_profit": target, "risk_pips": abs(entry - stop) / 0.0001,
            "reward_pips": None if target is None else abs(target - entry) / 0.0001, "risk_reward_ratio": "1:1.5",
            "lot_size": 0.2, "projected_risk_usd": 4.0, **kw}


# ---------------------------------------------------------------------------
# which setup a group trades
# ---------------------------------------------------------------------------

def test_each_setup_belongs_to_the_category_whose_idea_it_trades():
    assert set(ss.GROUP_SETUPS) == {"SMC", "MEAN_REVERSION", "TREND", "WAVE"}
    assert all(name in ss.SETUP_TITLES for names in ss.GROUP_SETUPS.values() for name in names)
    # SMC trades structure: order blocks, sweeps, fair value gaps
    assert ss.GROUP_SETUPS["SMC"] == ("smc_trade", "fvg_ifvg")
    # mean reversion fades an extreme back toward value -- including the
    # stochastic divergence reversal, which is not a momentum trade
    assert ss.GROUP_SETUPS["MEAN_REVERSION"] == ("bb_mean_reversion", "rsi_reversal", "stochastic_reversal")
    assert ss.GROUP_SETUPS["TREND"] == ("ema_crossover",)
    assert ss.GROUP_SETUPS["WAVE"] == ("wave_c",)
    # no setup: momentum (no continuation setup yet), structure, order flow, and
    # cross-asset, which is advisory and cannot be traded at all
    for group in ("MOMENTUM", "STRUCTURE", "ORDER_FLOW", "CROSS_ASSET"):
        assert group not in ss.GROUP_SETUPS
        assert ss.pick(group, {}, "BUY")["valid"] is None


def test_the_winning_groups_valid_setup_is_picked():
    pick = ss.pick("SMC", {"smc_trade": _setup()}, "BUY")
    assert pick["valid"] is True and pick["name"] == "smc_trade" and pick["group"] == "SMC"
    assert pick["stop_loss"] == 1.0830 and pick["take_profit"] == 1.0880 and pick["lot_size"] == 0.2


def test_the_next_setup_of_the_group_is_tried_when_the_first_is_not_valid():
    pick = ss.pick("SMC", {"smc_trade": {"is_perfect_setup": False, "reason": "confluence 2/6"},
                           "fvg_ifvg": _setup()}, "BUY")
    assert pick["valid"] is True and pick["name"] == "fvg_ifvg"


def test_a_setup_on_the_other_side_or_with_a_misplaced_stop_is_refused():
    wrong_side = ss.pick("WAVE", {"wave_c": _setup(direction="SELL", stop=1.0870, target=1.0820)}, "BUY")
    assert wrong_side["valid"] is False and "not the traded side" in wrong_side["why"]
    bad_stop = ss.pick("WAVE", {"wave_c": _setup(stop=1.0860)}, "BUY")
    assert bad_stop["valid"] is False and "wrong side" in bad_stop["why"]


def test_no_valid_setup_says_why_for_every_candidate():
    pick = ss.pick("MEAN_REVERSION", {"bb_mean_reversion": {"is_perfect_setup": False, "reason": "no band touch"}},
                   "SELL")
    assert pick["valid"] is False and pick["has_setups"] is True
    assert "bb_mean_reversion: no band touch" in pick["why"] and "rsi_reversal: not evaluated" in pick["why"]


@pytest.mark.parametrize("group", ["STRUCTURE", "ORDER_FLOW", "CROSS_ASSET", None])
def test_groups_without_a_setup_are_not_judged_by_one(group):
    pick = ss.pick(group, {"smc_trade": _setup()}, "BUY")
    assert pick["valid"] is None and pick["has_setups"] is False


def test_a_signal_exit_setup_keeps_its_stop_without_a_target():
    pick = ss.pick("TREND", {"ema_crossover": _setup(target=None, exit_type="SIGNAL_EXIT")}, "BUY")
    assert pick["valid"] is True and pick["take_profit"] is None and pick["exit_type"] == "SIGNAL_EXIT"


# ---------------------------------------------------------------------------
# the entry rule table with a strategy setup
# ---------------------------------------------------------------------------

QUIET_TAPE = ({"available": True}, False, False, False, False)
BEARISH_BAR = {"open": 1.0851, "high": 1.0852, "low": 1.0839, "close": 1.0840, "body_pips": 11.0,
               "upper_wick_pips": 1.0, "lower_wick_pips": 1.0, "candle_type": "normal"}
AWAY_FROM_ZONE = dict(symbol="EURUSD", best_direction="BUY", current_price=1.08600, zone_level=1.08400,
                      zone_type="DEMAND", zone_grade="E", candle_data=BEARISH_BAR, volume_spike=False,
                      at_poi=False, best_probability=78.0, pip_size=0.0001, atr_pips=10.0,
                      probability_floor=75.0)


def _engine(rule_modes=None):
    """Every rule blocking, so a rule that lets a decision through is the setup's doing.
    rule_modes overrides individual rules (the shipped mode for the rule under test)."""
    engine = EntryEngine({"rule_modes": {**{name: BLOCK for name in RULE_ORDER}, **(rule_modes or {})}})
    engine.get_micro_structure_signals = lambda *a, **k: (dict(QUIET_TAPE[0]),) + tuple(QUIET_TAPE[1:])
    return engine


def test_a_valid_setup_enters_where_the_generic_entry_would_not():
    setup = ss.pick("SMC", {"smc_trade": _setup()}, "BUY")
    d = _engine().get_entry_decision(**AWAY_FROM_ZONE, strategy_setup=setup)
    assert d["should_enter"] is True and d["entry_status"] == "STRATEGY_SETUP"
    assert d["rules"]["setup"]["passed"] is True and d["rules"]["setup"]["value"] == "smc_trade"
    for name in SETUP_REPLACES:
        assert d["rules"][name]["mode"] == OBSERVE
    assert d["rules"]["discount"]["passed"] is False            # still measured and recorded
    assert "SMC SMC trade setup" in d["reason"]


def test_a_group_whose_setups_are_not_valid_waits_for_them():
    setup = ss.pick("MEAN_REVERSION", {}, "BUY")
    d = _engine().get_entry_decision(**AWAY_FROM_ZONE, strategy_setup=setup)
    assert d["blocked_by"] == ["setup"] and d["entry_status"] == "NO_STRATEGY_SETUP"


def test_the_probability_band_still_applies_to_a_setup():
    setup = ss.pick("SMC", {"smc_trade": _setup()}, "BUY")
    d = _engine().get_entry_decision(**{**AWAY_FROM_ZONE, "best_probability": 60.0}, strategy_setup=setup)
    assert d["blocked_by"] == ["probability"]


def test_a_group_without_setups_keeps_the_generic_rules():
    setup = ss.pick("ORDER_FLOW", {}, "BUY")
    d = _engine().get_entry_decision(**AWAY_FROM_ZONE, strategy_setup=setup)
    assert d["rules"]["setup"]["passed"] is None
    assert d["rules"]["discount"]["mode"] == BLOCK and "discount" in d["blocked_by"]


# ---------------------------------------------------------------------------
# sizing: the $200 lot is the ceiling, it shrinks to hold $4
# ---------------------------------------------------------------------------

def test_a_wide_setup_stop_shrinks_the_lot_to_the_budget():
    # $12.50 per lot at this stop, $4 budget -> 0.32 lot, below the 0.39 margin-first lot
    volume, risk = volume_for_kept_stop(12.5, 4.0, 0.39, 0.01, 0.01, 100.0)
    assert volume == 0.32 and risk <= 4.0


def test_a_tight_setup_stop_never_raises_the_lot_above_the_trade_size():
    # $2 per lot: the budget would allow 2.0 lots, the $200 trade size buys 0.39
    volume, risk = volume_for_kept_stop(2.0, 4.0, 0.39, 0.01, 0.01, 100.0)
    assert volume == 0.39 and risk == pytest.approx(0.78)


def test_when_even_the_minimum_volume_is_over_budget_the_risk_says_so():
    volume, risk = volume_for_kept_stop(900.0, 4.0, 0.39, 0.01, 0.01, 100.0)
    assert volume == 0.01 and risk == pytest.approx(9.0)          # execute_trade refuses this order


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------

def test_setups_are_evaluated_before_the_entry_decision_and_published():
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert src.index("smc_trade_setup = evaluate_smc_trade_setup(") < src.index("entry_result = analyze_entry(")
    assert src.index("strategy_setup = pick_strategy_setup(") < src.index("entry_result = analyze_entry(")
    assert "strategy_setup=strategy_setup," in src
    assert '"stop_source": stop_source,' in src and '"strategy_setup": strategy_setup,' in src


def test_the_monitor_keeps_a_setups_stop_when_it_executes():
    src = (ROOT / "monitor" / "monitor_core.py").read_text(encoding="utf-8")
    assert 'keep_stop=str(final_verdict.get("stop_source") or "").startswith("strategy_setup")' in src


# ---------------------------------------------------------------------------
# targets follow the 1:1.2 floor (operator, 2026-09-17)
# ---------------------------------------------------------------------------

def test_tp1_sits_on_the_rr_floor_net_of_spread_and_passes_it():
    from core import asset_analysis_config as cfg
    from core.asset_analysis import calculate_hybrid_take_profit
    from core.risk_reward import rr_from_pips

    assert cfg.TP1_FOLLOWS_RR_FLOOR is True and cfg.MINIMUM_RISK_REWARD_M1 == 1.2
    assert cfg.MIN_ABSOLUTE_RISK_REWARD == 1.2
    misses = 0
    for sl10 in range(5, 60):
        for sp10 in range(0, 8):
            sl, spread = sl10 / 10, sp10 / 10
            tp1, tp2, tp3 = calculate_hybrid_take_profit(
                symbol="EURUSD", current_price=1.085, order_type="BUY", pip_size=0.0001, atr_pips=1.5,
                spread_pips=spread, sl_pips=sl, recent_swing_high=1.0900, recent_swing_low=1.0800)
            assert tp1 == pytest.approx(max(1.2 * sl + spread, 2 * spread + 1))
            assert tp1 < tp2 < tp3
            if not rr_from_pips(reward_pips=tp1 - spread, risk_pips=sl, direction="BUY").passes_floor(1.2):
                misses += 1
    assert misses == 0


def test_a_setup_keeps_its_own_target_only_if_it_pays_the_minimum_net_of_spread():
    # stop 20 pips, SMC's own target 30 pips: 1:1.5 gross, 1:1.45 net of a 1-pip spread -> traded as is
    ok = ss.pick("SMC", {"smc_trade": _setup(stop=1.0830, target=1.0880)}, "BUY", spread_pips=1.0, min_rr=1.2)
    assert ok["valid"] is True and ok["take_profit"] == 1.0880 and ok["net_risk_reward"] == pytest.approx(1.45)
    # stop 20 pips, target 24 pips: 1:1.2 gross, 1:1.15 net of the spread -> not traded, and not stretched
    short = ss.pick("SMC", {"smc_trade": _setup(stop=1.0830, target=1.0874)}, "BUY", spread_pips=1.0, min_rr=1.2)
    assert short["valid"] is False and "below the 1:1.2 minimum" in short["why"]


def test_the_default_minimum_is_the_configured_rr_floor():
    from core import asset_analysis_config as cfg
    assert cfg.MIN_ABSOLUTE_RISK_REWARD == 1.2
    even = ss.pick("WAVE", {"wave_c": _setup(stop=1.0830, target=1.0870)}, "BUY", spread_pips=0.0)
    assert even["valid"] is False                                   # 20-pip stop, 20-pip target: 1:1.0
    enough = ss.pick("WAVE", {"wave_c": _setup(stop=1.0830, target=1.0875)}, "BUY", spread_pips=0.0)
    assert enough["valid"] is True                                  # 25-pip target: 1:1.25


# ---------------------------------------------------------------------------
# which strategy decides: ALL (default) or one (operator, 2026-09-17)
# ---------------------------------------------------------------------------

def test_every_strategy_competes_by_default():
    from core import asset_analysis_config as cfg
    from core import strategy_groups as sg
    assert cfg.STRATEGY_SELECTION == "ALL"
    r = sg.score_groups(sg._loud_smc("BUY"), "BUY")
    assert r["selected"] == "ALL" and r["winner"] == "SMC"


def test_a_selected_strategy_decides_even_when_another_would_win():
    from core import strategy_groups as sg
    payload = dict(sg._loud_smc("BUY"),
                   trend_cascade={"available": True, "direction": "BULLISH", "score": 1.0},
                   higher_timeframe={"trend": "BULLISH"},
                   trend_confirmation={"m1_price_vs_ema200": "above"})
    payload["indicators"] = dict(payload["indicators"], trend={"recommendation": "BUY", "confidence": 100})
    for group in ("SMC", "TREND"):
        r = sg.score_groups(payload, "BUY", only=group)
        assert r["winner"] == group and [x["group"] for x in r["ranked"]] == [group]
        assert r["final_probability"] >= 5.0


def test_a_selected_strategy_without_a_reading_never_falls_back_to_another():
    from core import strategy_groups as sg
    r = sg.score_groups(sg._loud_smc("BUY"), "BUY", only="WAVE")
    assert r["final_probability"] == 5.0 and r["ranked"] == [] and "WAVE has no reading" in r["reason"]


def test_the_api_and_the_analysis_accept_a_strategy():
    api = (ROOT / "api" / "execution_controller.py").read_text(encoding="utf-8")
    assert "strategy=data.get('strategy')" in api
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert "strategy: Optional[str] = None," in src and "only=strategy_selection" in src
    assert '"strategy_selection": strategy_selection,' in src



def test_the_ev_gate_blocks_what_it_logs_and_judges_the_decisions_probability():
    """Live SPY.NYSE 2026-09-17: '[EV GATE] SKIP' was logged and the trade still
    executed, because the gate never touched entry_analysis."""
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    gate = src[src.index("NEGATIVE EXPECTED VALUE GATE"):src.index("ABSOLUTE R:R FLOOR (independent of probability)")]
    assert "p_win_pct=probability_at_decision" in gate
    assert 'entry_analysis["should_enter"] = False' in gate


# ---------------------------------------------------------------------------
# momentum is strength, not a strategy (operator + measurement, 2026-09-17)
# ---------------------------------------------------------------------------

def test_momentum_rides_on_every_decision_as_strength_and_never_blocks():
    from core import asset_analysis_config as cfg
    from core import strategy_groups as sg

    assert "MOMENTUM" in sg.MEASURED_EMPTY_GROUPS          # cannot win the auction
    assert cfg.ENTRY_RULE_MODES["momentum"] == "observe"    # recorded, never blocking
    engine = _engine(rule_modes={"momentum": OBSERVE})      # the mode the config ships
    strong = engine.get_entry_decision(**AWAY_FROM_ZONE, momentum_score=88.0)
    weak = engine.get_entry_decision(**AWAY_FROM_ZONE, momentum_score=20.0)
    silent = engine.get_entry_decision(**AWAY_FROM_ZONE)
    assert strong["rules"]["momentum"] == {**strong["rules"]["momentum"], "passed": True, "value": 88.0,
                                           "threshold": cfg.MOMENTUM_STRENGTH_MIN}
    assert weak["rules"]["momentum"]["passed"] is False
    assert silent["rules"]["momentum"]["passed"] is None    # momentum had no reading for this side
    assert "momentum" not in weak["blocked_by"]             # observed only


def test_the_analysis_publishes_momentum_beside_the_deciding_strategy():
    src = (ROOT / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert 'momentum_score=((strategy_groups_result.get("groups") or {}).get("MOMENTUM") or {}).get("score")' in src
    assert '"momentum": ((strategy_groups_result.get("groups") or {}).get("MOMENTUM") or {}).get("score")' in src
