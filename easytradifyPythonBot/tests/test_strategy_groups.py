"""Strategy groups: each group scored alone, the highest sets the probability."""

import pathlib

import pytest

from core import asset_analysis_config as cfg
from core import strategy_groups as sg


def payload():
    return {
        "indicators": {
            "trend": {"recommendation": "BUY", "confidence": 80},
            "rsi": {"recommendation": "SELL", "confidence": 50},
            "stochastic": {"recommendation": "NEUTRAL", "confidence": 40},
            "bollinger_bands": {"recommendation": "SELL", "confidence": 30},
            "macd": {"signal": "BULLISH", "confidence": 80},
            "supply_demand": {"recommendation": "IMMEDIATE_BUY", "confidence": 85},
            "support_resistance": {"recommendation": "WATCH_BEARISH"},
        },
        "trend_cascade": {"available": True, "direction": "BULLISH", "score": 0.7},
        "higher_timeframe": {"trend": "BULLISH"},
        "ttm_squeeze": {"momentum_direction": "UP"},
        "final_verdict": {"adr_exhaustion_final_score": {"adjustment": -12.0},
                          "gap_slippage_final_score": {"gap_slippage_penalty": 3.5}},
    }


def test_each_group_is_scored_alone_and_the_best_wins():
    result = sg.score_groups(payload(), "BUY")
    assert result["winner"] in ("TREND", "MOMENTUM")
    best = max(g["score"] for g in result["groups"].values() if g["scored"])
    assert result["best_score"] == best
    assert result["ranked"][0]["score"] == best


def test_context_and_opposition_apply_after_the_max():
    result = sg.score_groups(payload(), "BUY")
    assert result["context_total"] == -15.5
    expected = result["best_score"] - result["opposition"] - 15.5
    assert result["final_probability"] == round(max(5.0, min(95.0, expected)), 1)


def test_opposition_is_how_far_the_most_opposed_group_sits_below_50():
    result = sg.score_groups(payload(), "BUY")
    worst = min(g["score"] for g in result["groups"].values() if g["scored"])
    assert result["most_opposed"] == result["ranked"][-1]["group"]
    assert result["opposition"] == round(max(0.0, 50.0 - worst), 1)


def test_contested_bar_is_flagged_not_discounted():
    """Ambiguity is published; it is no longer subtracted from the winner.

    The opposition term used to drag a contested bar to 50 on both sides. On
    61,950 tick-labelled decisions it was penalising exactly the bars that
    measure best -- 1-2 groups agreeing returns -0.130R, six agreeing -0.278R --
    so it is gone, and the conflict is surfaced instead.
    """
    # a two-sided bar between groups that can DECIDE: the trend group reads BUY
    # and the fitted reversion process says the fade is earned, so it reads SELL.
    # (A cross-asset view no longer makes a bar contested: it is advisory.)
    ou = sg._ou_payload(True)
    p = {**ou, "higher_timeframe": {"trend": "BULLISH"},
         "trend_confirmation": {"m1_price_vs_ema200": "above"},
         "volatility_protection": {"trading_regime": {"state": "RANGING_CALM"}},
         "indicators": {**ou["indicators"], "trend": {"recommendation": "BUY", "confidence": 100}}}
    buy, sell = sg.score_groups(p, "BUY"), sg.score_groups(p, "SELL")
    assert sg.OPPOSITION_WEIGHT == 0.0
    assert buy["opposition"] == 0.0 and sell["opposition"] == 0.0
    # the conflict is visible from either side, so nothing reads certain silently
    assert buy["contested"] is True and sell["contested"] is True
    assert buy["other_side_best"] >= 50.0 and sell["other_side_best"] >= 50.0
    # and the winner keeps its own score -- no other group's number touches it
    assert buy["final_probability"] == buy["best_score"]


def test_cross_group_agreement_is_published_not_scored():
    p = {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
         "indicators": {"trend": {"recommendation": "BUY", "confidence": 100}},
         "higher_timeframe": {"trend": "BULLISH"},
         "trend_confirmation": {"m1_price_vs_ema200": "above"}}
    r = sg.score_groups(p, "BUY")
    assert r["groups_agreeing"] >= 1 and r["groups_scored"] >= 1
    assert r["final_probability"] == r["best_score"]   # agreement adds nothing


def test_the_hour_of_day_is_published_but_does_not_move_the_probability():
    """Operator rule (2026-09-17): no session or news rules. The dead-session
    reading is recorded (counts=False) and left out of the probability."""
    p = {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
         "indicators": {"trend": {"recommendation": "BUY", "confidence": 100}},
         "higher_timeframe": {"trend": "BULLISH"},
         "trend_confirmation": {"m1_price_vs_ema200": "above"}}
    live = sg.score_groups(dict(p, clock={"broker_hour": 9}), "BUY")
    roll = sg.score_groups(dict(p, clock={"broker_hour": 0}), "BUY")
    assert roll["final_probability"] == live["final_probability"]
    assert {"name": "dead session", "points": -sg.DEAD_SESSION_PENALTY[0], "counts": False} in roll["context"]
    assert roll["context_total"] == live["context_total"]
    assert sg.score_groups(p, "BUY")["final_probability"] == live["final_probability"]


def test_smc_members_are_trend_confirmed():
    smc = _members("SMC")
    p = {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
         "indicators": {"ict_concepts": {"type": "BEARISH"}}}
    assert smc["ICT FVG type (trend-confirmed)"](p) is None
    p["indicators"]["ict_concepts"]["type"] = "BULLISH"
    assert smc["ICT FVG type (trend-confirmed)"](p) == (1, 1.0)


def test_no_opposition_leaves_the_max_untouched():
    p = {"indicators": {"trend": {"recommendation": "BUY", "confidence": 100}},
         "trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0}}
    result = sg.score_groups(p, "BUY")
    assert result["opposition"] == 0.0 and result["final_probability"] == result["best_score"]


def test_dead_members_removed():
    names = {name for _, name, _ in sg.MEMBERS}
    assert "VWAP context" not in names and "DXY confluence" not in names


def _members(group):
    return {name: reader for g, name, reader in sg.MEMBERS if g == group}


def test_zone_readings_count_only_with_the_trend():
    base = {"trend_cascade": {"available": True, "direction": "BEARISH", "score": -1.0},
            "indicators": {"supply_demand": {"recommendation": "IMMEDIATE_BUY", "confidence": 85}}}
    sd = _members("STRUCTURE")["supply / demand (trend-confirmed)"]
    assert sd(base) is None                      # demand zone against a bearish cascade: silent


def _ou(tradeable=True, side=-1):
    """A bar where the fitted process does (or does not) earn a counter-trend fade."""
    return {"trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0},
            "ou_reversion": {"available": True, "tradeable": tradeable, "side": side,
                             "size_multiple": 1.8, "z": -1.8, "forward_t": 4.1},
            "indicators": {"rsi": {"recommendation": "SELL", "confidence": 60},
                           "stochastic": {"recommendation": "SELL", "confidence": 60}}}


def test_reversion_is_gated_by_the_fitted_process_not_the_trend():
    """The defect that kept mean reversion off every auction.

    Members used to be trend-confirmed, so an overbought reading in an uptrend
    -- the one call the group exists to make -- returned None, and the group
    could only ever vote WITH the trend. The gate is now the OU fit: a fade
    counts when the process earns it, whatever the trend is doing.
    """
    rsi = _members("MEAN_REVERSION")["RSI extreme (OU-gated)"]
    assert rsi({"indicators": {"rsi": {"recommendation": "SELL", "confidence": 60}}}) is None
    assert rsi(_ou(tradeable=False)) is None       # fit does not clear its statistical bar
    assert rsi(_ou(tradeable=True)) == (-1, 0.6)   # earned: fades AGAINST a bullish cascade


def test_ou_member_sizes_by_the_dislocation():
    ou = _members("MEAN_REVERSION")["OU dislocation (fitted half-life)"]
    assert ou(_ou(tradeable=False)) is None
    side, strength = ou(_ou(tradeable=True))
    assert side == -1 and strength == pytest.approx(0.6)   # size_multiple 1.8, capped at 3
    assert ou({"ou_reversion": {"tradeable": True, "side": 0}}) is None


def test_every_mean_reversion_member_needs_the_fit():
    """No member may be admitted by an indicator's opinion alone again."""
    members = _members("MEAN_REVERSION")
    assert len(members) >= sg.MIN_GROUP_MEMBERS
    for name, reader in members.items():
        assert reader(_ou(tradeable=False)) is None, name


def test_bollinger_and_premium_read_as_continuation():
    p = {"indicators": {"bollinger_bands": {"recommendation": "SELL", "confidence": 100}},
         "smc": {"analysis": {"premium_discount": {"zone": "PREMIUM"}}},
         "trend_cascade": {"available": True, "direction": "BULLISH", "score": 1.0}}
    # a band walk is a continuation thesis, so it sits with the continuation
    # readings -- inside MEAN_REVERSION it was inverted against that group's
    # own members and the three cancelled each other toward 50
    assert _members("MOMENTUM")["Bollinger band walk (continuation)"](p)[0] == 1
    assert "Bollinger band walk (continuation)" not in _members("MEAN_REVERSION")
    assert _members("SMC")["premium / discount (continuation)"](p)[0] == 1


def test_gnn_direction_only_in_ranging_regimes():
    gnn = _members("CROSS_ASSET")["GNN direction (ranging regimes)"]
    p = {"gnn": {"analysis": {"gnn_direction": 0.05}},
         "volatility_protection": {"trading_regime": {"state": "RANGING_CALM"}}}
    assert gnn(p) == (1, 1.0)
    p["volatility_protection"]["trading_regime"]["state"] = "TRENDING_CALM"
    assert gnn(p) is None


def test_score_is_side_relative():
    buy, sell = sg.score_groups(payload(), "BUY"), sg.score_groups(payload(), "SELL")
    assert buy["groups"]["TREND"]["score"] > 50 > sell["groups"]["TREND"]["score"]
    assert buy["groups"]["TREND"]["score"] + sell["groups"]["TREND"]["score"] == 100.0


def test_group_needs_two_members():
    result = sg.score_groups(payload(), "BUY")
    assert result["groups"]["SMC"]["scored"] is False
    assert "member" in result["groups"]["SMC"]["reason"]


def test_nothing_readable_gives_no_probability():
    result = sg.score_groups({}, "BUY")
    assert result["final_probability"] is None and result["winner"] is None


def test_scores_stay_inside_clamp():
    p = payload()
    p["indicators"] = {k: {"recommendation": "BUY", "confidence": 100} for k in ("trend", "rsi", "stochastic", "bollinger_bands")}
    result = sg.score_groups(p, "BUY")
    assert all(5.0 <= g["score"] <= 95.0 for g in result["groups"].values() if g["scored"])


def test_self_check_passes():
    assert sg.self_check()["ok"] is True


def test_switch_on_and_wired_before_entry_decision():
    assert cfg.USE_STRATEGY_GROUP_PROBABILITY is True
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    assert src.index("score_groups(_sg_payload, best_direction, only=strategy_selection)") < src.index('"ENTRY_DECISION"')
    assert '_ledger_step(probability_ledger, "strategy_groups"' in src


def test_momentum_and_order_flow_members_are_trend_confirmed():
    names = {name for g, name, _ in sg.MEMBERS if g in ("MOMENTUM", "ORDER_FLOW")}
    # every member is either confirmed by the trend or is itself a
    # continuation reading -- nothing in these groups fades
    assert names and all(name.endswith(("(trend-confirmed)", "(continuation)")) for name in names)
    assert "stochastic cross (trend-confirmed)" in names


def test_mean_reversion_members_are_all_ou_bound():
    """No member of this group may be admitted by trend agreement again."""
    names = {name for g, name, _ in sg.MEMBERS if g == "MEAN_REVERSION"}
    assert names and all("OU" in name or "half-life" in name for name in names)
    assert len(names) >= sg.MIN_GROUP_MEMBERS


def test_momentum_votes_with_the_trend_only():
    macd = _members("MOMENTUM")["MACD momentum (trend-confirmed)"]
    up = {"indicators": {"macd": {"signal": "BULLISH", "confidence": 80}},
          "trend_cascade": {"available": True, "direction": "BULLISH", "score": 0.7}}
    down = dict(up, trend_cascade={"available": True, "direction": "BEARISH", "score": -0.7})
    assert macd(up) == (1, 0.8)
    assert macd(down) is None


def test_group_scale_has_its_own_entry_floor():
    assert cfg.STRATEGY_GROUP_MIN_PROBABILITY == 75.0
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    floor = src.index("probability_floor = (STRATEGY_GROUP_MIN_PROBABILITY")
    entry = src.index("entry_result = analyze_entry(")
    assert floor < entry
    # applied once, by the entry rule table -- no second copy after the engine
    assert "probability_floor=probability_floor" in src[entry:entry + 1200]
    assert "best_probability < probability_floor" not in src
    assert '"min_probability_for_entry": probability_floor' in src


def test_other_side_is_published_not_acted_on():
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "asset_analysis.py").read_text(encoding="utf-8")
    block = src[src.index('strategy_groups_result["other_side"]'):src.index("_ledger_step(probability_ledger, \"strategy_groups\"")]
    assert "best_direction =" not in block


def test_cost_penalty_is_break_even_arithmetic():
    p = {"global_anticheat": {"spread_pips": 0.3}, "config": {"symbol": "GBPAUD"},
         "entry_details": {"stop_loss_pips": 1.5, "take_profit_pips": 8, "risk_usd": 3.96, "lot_size": 0.37}}
    cost = sg.trading_cost(p)
    expected_cost = 0.3 / 1.5 + 0.37 * sg.COMMISSION_PER_LOT_ROUND_TRIP / 3.96
    assert abs(cost["cost_r"] - round(expected_cost, 3)) < 1e-9
    assert abs(cost["penalty_points"] - round(100 * expected_cost / (1 + 8 / 1.5), 2)) < 1e-9


def test_cost_is_applied_as_context():
    p = payload()
    p.update({"global_anticheat": {"spread_pips": 0.3}, "config": {"symbol": "EURUSD"},
              "entry_details": {"stop_loss_pips": 1.5, "take_profit_pips": 8, "risk_usd": 3.96, "lot_size": 0.37}})
    with_cost = sg.score_groups(p, "BUY")
    names = {c["name"] for c in with_cost["context"]}
    assert "trading cost" in names
    assert with_cost["context_total"] == round(-15.5 - with_cost["cost"]["penalty_points"], 2)


def test_conviction_counts_strategy_groups_not_the_old_chain():
    from core.conviction import CONVICTION_WEIGHTS, evaluate_conviction
    assert "strategy_groups" in CONVICTION_WEIGHTS and "confluence_chain" not in CONVICTION_WEIGHTS
    result = {"strategy_groups": {"enabled": True, "groups": {
                  "TREND": {"scored": True, "score": 80}, "SMC": {"scored": True, "score": 30},
                  "WAVE": {"scored": True, "score": 70}}},
              "final_verdict": {"smc_final_score": {"aligned": False}, "gnn_final_score": {"aligned": False}}}
    comp = evaluate_conviction(result, direction="BUY")["components"]["strategy_groups"]
    assert abs(comp["score"] - 2 / 3) < 1e-3 and "SMC" in comp["detail"]


def test_declined_gate_turns_off_the_flag_the_monitor_reads():
    from core.asset_analysis import _decline_entry, _entry_is_live
    result = {"entry_analysis": {"should_enter": True, "simple_action": "ENTER NOW"},
              "final_verdict": {"verdict": "SELL NOW"}}
    assert _entry_is_live(result)
    _decline_entry(result, "CONVICTION - conviction 0.40 below minimum 0.55")
    assert result["entry_analysis"]["should_enter"] is False
    assert result["entry_analysis"]["execution"] == "DO_NOTHING"
    assert result["final_verdict"]["simple_action"] == "HOLD"
    assert not _entry_is_live(result)


def test_smc_and_structure_compete_in_the_auction():
    """Operator decision 2026-09-17: every strategy group competes, and the winner
    trades its own setup. On the history replay every group's decisions measured
    at the same base rate as the zone study that had silenced these two."""
    # advisory only (operator, 2026-09-17): cross-asset is the GNN's view, momentum
    # is trend counted twice and rides along as a strength reading instead
    assert sg.MEASURED_EMPTY_GROUPS == ("CROSS_ASSET", "MOMENTUM")
    r = sg.score_groups(sg._loud_smc("BUY"), "BUY")
    assert r["winner"] == "SMC"
    assert r["groups"]["SMC"].get("counts_in_decision", True) is not False
    assert any(x["group"] == "SMC" for x in r["ranked"])


def test_a_named_group_can_still_be_silenced(monkeypatch):
    monkeypatch.setattr(sg, "MEASURED_EMPTY_GROUPS", ("SMC",))
    r = sg.score_groups(sg._loud_smc("BUY"), "BUY")
    assert r["groups"]["SMC"]["scored"] is True
    assert r["groups"]["SMC"]["counts_in_decision"] is False
    assert all(x["group"] != "SMC" for x in r["ranked"])


def test_the_strongest_group_wins_when_trend_and_smc_both_speak():
    payload = dict(sg._loud_smc("BUY"),
                   trend_cascade={"available": True, "direction": "BULLISH", "score": 1.0},
                   higher_timeframe={"trend": "BULLISH"},
                   trend_confirmation={"m1_price_vs_ema200": "above"})
    payload["indicators"] = dict(payload["indicators"],
                                 trend={"recommendation": "BUY", "confidence": 100})
    r = sg.score_groups(payload, "BUY")
    best = max(x["score"] for x in r["ranked"])
    assert r["best_score"] == best and r["groups"][r["winner"]]["score"] == best
    assert {"TREND", "SMC"} <= {x["group"] for x in r["ranked"]}


def test_cross_asset_is_advisory_and_cannot_be_traded():
    """Operator, 2026-09-17: the GNN's cross-asset reading is published, never traded."""
    payload = {"gnn": {"analysis": {"available": True, "gnn_direction": 1.0, "recommendation": "BULLISH",
                                    "recommendation_score": 100.0, "data_quality": "MT5"}},
               "volatility_protection": {"trading_regime": {"state": "RANGING_CALM"}}}
    r = sg.score_groups(payload, "BUY")
    assert "CROSS_ASSET" in sg.MEASURED_EMPTY_GROUPS
    assert r["winner"] != "CROSS_ASSET"
    assert all(x["group"] != "CROSS_ASSET" for x in r["ranked"])
    assert r["groups"]["CROSS_ASSET"]["counts_in_decision"] is False
