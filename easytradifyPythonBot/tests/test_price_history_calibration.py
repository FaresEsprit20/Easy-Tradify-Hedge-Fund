"""
The price-history study, the calibration it feeds, and the runtime scorer.

The calibrated model is only trustworthy if the engine evaluates EXACTLY the
function the study fitted: same reading keys, same transforms, same stacking.
These tests pin that parity, the edge features' direction conventions, and
the no-lookahead slice.
"""

import math

import numpy as np
import pytest

from core import asset_analysis_config as cfg
from core import edge_features
from core.calibrated_model import raw_reader, readings, score, _transform
from core.strategy_groups import MEMBERS


RATE_DTYPE = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")]


def _bars(closes, start=1_781_000_000 - 1_781_000_000 % 86400, spread=0.0002):
    closes = np.asarray(closes, dtype=float)
    arr = np.zeros(closes.size, dtype=RATE_DTYPE)
    arr["time"] = start + 60 * np.arange(closes.size)
    arr["close"] = closes
    arr["open"] = np.concatenate([[closes[0]], closes[:-1]])
    arr["high"] = np.maximum(arr["open"], closes) + spread
    arr["low"] = np.minimum(arr["open"], closes) - spread
    return arr


def test_momentum_reads_up_on_a_rising_market():
    rng = np.random.default_rng(1)
    closes = 1.10 + np.cumsum(0.00005 + rng.normal(0, 0.00003, 1600))
    f = edge_features.compute("EURUSD", _bars(closes))
    assert f["mom_60"] > 0 and f["mom_240"] > 0 and f["mom_1440"] > 0
    assert f["mom_agreement"] == 4
    assert f["mean_dist_60"] < 0      # stretched above the mean reads down


def test_currency_strength_is_base_minus_quote():
    rng = np.random.default_rng(2)
    up = 1.10 + np.cumsum(0.00005 + rng.normal(0, 0.00002, 400))
    down = 1.30 + np.cumsum(-0.00005 + rng.normal(0, 0.00002, 400))
    flat = 0.90 + rng.normal(0, 0.00002, 400)
    # EUR strong (EURUSD up, EURGBP up), USD weak (USDCHF down)
    peers = {"EURGBP": _bars(up * 0.8), "USDCHF": _bars(down * 0.7), "GBPCHF": _bars(flat + 0.3)}
    f = edge_features.compute("EURUSD", _bars(up), peers)
    assert f["ccy_strength_60"] > 0


def test_sweep_and_reclaim_reads_against_the_sweep():
    closes = np.full(200, 1.1000)
    closes[-10] = 1.1030          # spike above the prior hour's high...
    closes[-1] = 1.0999           # ...and back inside
    f = edge_features.compute("EURUSD", _bars(closes, spread=0.00001))
    assert f["sweep_reclaim"] == -1


def test_asia_break_uses_the_broker_clock_offset():
    day = 1_781_000_000 - 1_781_000_000 % 86400
    closes = np.full(900, 1.1000)
    closes[-1] = 1.1050
    bars = _bars(closes, start=day, spread=0.00001)
    now = int(bars["time"][-1]) + 60             # 15:00 broker = 12:00 UTC
    f = edge_features.compute("EURUSD", bars, now_ts=now, clock_offset_seconds=10800)
    assert f["asia_break"] == 1
    assert f["hour_utc"] == 12


def test_raw_reader_strips_every_repair_wrapper():
    by_name = {name: reader for _, name, reader in MEMBERS}
    trend_confirmed = by_name["trend indicator (trend-confirmed)"]
    continuation = by_name["Bollinger band walk (continuation)"]
    reversion = by_name["RSI extreme (OU-gated)"]
    assert raw_reader(trend_confirmed) is not trend_confirmed
    assert raw_reader(raw_reader(trend_confirmed)) is raw_reader(trend_confirmed)
    payload = {"indicators": {"bollinger_bands": {"recommendation": "BUY", "confidence": 60}}}
    assert continuation(payload)[0] == -1 and raw_reader(continuation)(payload)[0] == 1
    # the OU gate must strip too, or the calibration study would score the
    # gate instead of the reading underneath it
    rsi_payload = {"indicators": {"rsi": {"recommendation": "BUY", "confidence": 60}}}
    assert reversion(rsi_payload) is None                      # gated: no OU fit
    assert raw_reader(reversion)(rsi_payload) == (1, 0.6)      # the reading itself


def test_readings_keys_match_the_study_columns():
    from ai.component_calibration import slug

    # the OU fit is what admits a fade, so the reading speaks only when the
    # process says the dislocation is worth taking
    payload = {"trend_cascade": {"direction": "BULLISH", "score": 0.8, "available": True},
               "ou_reversion": {"available": True, "tradeable": True, "side": 1,
                                "size_multiple": 1.4, "z": 1.4},
               "indicators": {"rsi": {"recommendation": "BUY", "confidence": 70}}}
    values = readings(payload, {"mom_60": 1.5, "version": "1.0"})
    assert values["m_used_" + slug("RSI extreme (OU-gated)")] == pytest.approx(0.7)
    # M1 only (2026-09-18): the M5-H4 cascade member is silent, so it produces
    # no column -- the live model is not scored under M1_ONLY for this reason
    assert cfg.M1_ONLY and "m_raw_" + slug("trend cascade M5-H4") not in values
    assert values["e_mom_60"] == 1.5 and "e_version" not in values


def test_runtime_score_equals_the_fitted_model(monkeypatch):
    """Fit on a synthetic frame, export, and score one row both ways.

    This pins the scoring MATHS on an arbitrary planted feature (the cascade
    member). The member is silent under M1_ONLY, so the switch is off here --
    the arithmetic under test does not depend on which feature is planted."""
    import ai.component_calibration as cc
    monkeypatch.setattr(cfg, "M1_ONLY", False)

    rng = np.random.default_rng(3)
    n = 4000
    mom = rng.normal(0, 2, n)
    cascade = rng.choice([-1.0, 0.0, 1.0], n)
    y = np.where(rng.random(n) < 1 / (1 + np.exp(-(0.5 * np.tanh(mom / 2) + 0.3 * cascade))), 1, -1)
    frame = {
        "_n": n, "_member_groups": {cc.slug("trend cascade M5-H4"): "TREND"},
        "y": y.astype(object), "ts": (1_781_000_000 + 900 * np.arange(n)).astype(object),
        "cluster": np.array([f"S|{i // 40}" for i in range(n)], dtype=object),
        "side": np.ones(n, dtype=object), "br_buy": np.zeros(n, dtype=object),
        "br_sell": np.zeros(n, dtype=object), "cost_r": np.zeros(n, dtype=object),
        "e_mom_60": mom.astype(object), "m_raw_trend_cascade_m5_h4": cascade.astype(object),
    }
    names = ["e_mom_60", "m_raw_trend_cascade_m5_h4"]
    model = cc.fit_models(frame, names)
    doc = {"groups": {g: {k: v for k, v in info.items() if k in ("features", "scales", "coef", "intercept")}
                      for g, info in model["groups"].items()},
           "group_order": model["group_order"], "stack": model["stack"], "version": "test"}
    i = 17
    payload = {"trend_cascade": {"direction": "BULLISH" if cascade[i] > 0 else "BEARISH" if cascade[i] < 0 else "NEUTRAL",
                                 "score": 1.0, "available": True}}
    got = score(payload, "BUY", {"mom_60": float(mom[i])}, model=doc)
    # rounding in the exported coefficients allows a small difference
    assert got["p_up"] == pytest.approx(float(model["_p_stack"][i]), abs=2e-3)
    assert model["groups"]["MOMENTUM"]["coef"][0] > 0     # the planted edge was found


def test_score_is_monotone_in_every_reading():
    doc = {"version": "t", "group_order": ["MOMENTUM"],
           "groups": {"MOMENTUM": {"features": ["e_mom_60"], "scales": [1.0], "coef": [1.2], "intercept": 0.0}},
           "stack": {"coef": [1.0], "intercept": 0.0}}
    ps = [score({}, "BUY", {"mom_60": v}, model=doc)["probability"] for v in (-3, -1, 0, 1, 3)]
    assert ps == sorted(ps) and ps[0] < 50 < ps[-1]
    sell = score({}, "SELL", {"mom_60": 3}, model=doc)["probability"]
    assert sell == pytest.approx(100 - ps[-1], abs=0.11)


def test_no_model_installed_scores_nothing(tmp_path):
    from core.calibrated_model import load_model
    assert load_model(tmp_path / "missing.json") is None


def test_study_feed_never_serves_an_unclosed_bar():
    from ai.price_history_study import _fast_feed_class

    FastFeed = _fast_feed_class()
    m1 = _bars(np.full(400, 1.1))
    m5 = m1[::5].copy()
    feed = FastFeed({"M1": m1, "M5": m5}, symbol="EURUSD", base_timeframe="M1", pip_size=0.0001,
                    info_kwargs={"point": 0.00001})
    ts = int(m1["time"][300]) + 60 + 120          # 2 minutes into an M5 bar
    md = feed.at(ts)
    assert md is not None
    assert int(md.rates["time"][-1]) + 60 <= ts
    assert int(md.multi_tf_rates.get("M5", m5[:1])["time"][-1]) + 300 <= ts
    assert feed.verify_no_lookahead(ts, md) == []


def test_shards_partition_decision_times_and_raw_paths_find_them(tmp_path):
    import gzip, json
    import ai.price_history_study as study

    step = 15 * 60
    times = [1_781_000_000 - 1_781_000_000 % step + i * step for i in range(12)]
    owners = [[t for t in times if (t // step) % 3 == k] for k in range(3)]
    assert sorted(sum(owners, [])) == times and all(owners)
    for k in range(2):
        with gzip.open(tmp_path / f"EURUSD.s{k}of3.jsonl.gz", "wt") as fh:
            fh.write(json.dumps({"ts": owners[k][0]}) + "\n")
    (tmp_path / "EURUSD.labelled.jsonl.gz").write_bytes(b"")
    names = [p.name for p in study.raw_paths("EURUSD", tmp_path)]
    assert names == ["EURUSD.s0of3.jsonl.gz", "EURUSD.s1of3.jsonl.gz"]


def _decision_result():
    return {"config": {"executed_direction": "BUY"},
            "vetos": {"checks": {"session_veto": False, "news_veto": False}},
            "global_anticheat": {"spread_valid": True},
            "entry_analysis": {"should_enter": False},
            "final_verdict": {"entry_price": 1.1000, "stop_loss": 1.0990, "take_profit_1": 1.1030,
                              "probability_percent": 40.0}}


def test_calibrated_decision_enters_above_the_floor_only():
    from core.calibrated_model import entry_decision

    model = {"entry_floor": 60.0, "model_decides_direction": False}
    cal = {"probability": 64.0, "preferred_direction": "BUY", "preferred_probability": 64.0}
    assert entry_decision(_decision_result(), cal, model)["enter"] is True
    assert entry_decision(_decision_result(), dict(cal, probability=55.0), model)["enter"] is False


def test_hard_safety_still_blocks():
    from core.calibrated_model import entry_decision

    r = _decision_result()
    r["vetos"]["checks"]["news_veto"] = True
    d = entry_decision(r, {"probability": 90.0}, {"entry_floor": 60.0})
    assert d["enter"] is False and "news_veto" in d["reason"]
    r = _decision_result(); r["global_anticheat"]["spread_valid"] = False
    assert entry_decision(r, {"probability": 90.0}, {"entry_floor": 60.0})["enter"] is False


def test_model_side_flip_mirrors_the_plan_keeping_distances():
    from core.calibrated_model import entry_decision, apply_entry

    r = _decision_result()
    cal = {"probability": 30.0, "preferred_direction": "SELL", "preferred_probability": 70.0}
    d = entry_decision(r, cal, {"entry_floor": 65.0, "model_decides_direction": True})
    assert d["enter"] and d["flipped"]
    apply_entry(r, d)
    fv = r["final_verdict"]
    assert r["config"]["executed_direction"] == "SELL"
    assert fv["stop_loss"] == pytest.approx(1.1010) and fv["take_profit_1"] == pytest.approx(1.0970)
    assert r["entry_analysis"]["should_enter"] is True and fv["probability_percent"] == 70.0


def test_component_rule_conditions_read_the_study_row_shape():
    from core.component_rules import condition_holds, rule_reading

    row = {"indicators.supply_demand.recommendation": "IMMEDIATE_SELL", "indicators.supply_demand.zone_level": 1.1003,
           "close": 1.1000, "atr_pips": 1.0, "pip": 0.0001, "edges.hour_utc": 14, "ctx.regime": "TRENDING_CALM"}
    assert condition_holds("edges.hour_utc >= 13.0", row)
    assert condition_holds("(indicators.supply_demand.zone_level - price)/ATR <= 3.5", row)
    assert not condition_holds("(indicators.supply_demand.zone_level - price)/ATR <= 2.5", row)
    assert condition_holds("ctx.regime == TRENDING_CALM", row)
    rule = {"vote": "indicators.supply_demand.recommendation", "orientation": "as-is",
            "conditions": ["edges.hour_utc >= 13.0"]}
    assert rule_reading(rule, row) == -1
    assert rule_reading(dict(rule, orientation="inverted"), row) == 1
    assert rule_reading(dict(rule, conditions=["edges.hour_utc <= 7.0"]), row) is None


def test_live_model_row_matches_the_study_row():
    """The model is fitted on ai/component_repair._row(record) and scored live on
    core/result_leaves.model_row(result): same keys, same values."""
    from ai.component_repair import _row
    from ai.price_history_study import full_leaves
    from core.result_leaves import model_row

    result = {"indicators": {"rsi": {"recommendation": "BUY", "rsi_14": 25.0}},
              "volatility_protection": {"atr_pips": 1.2, "trading_regime": {"state": "RANGING_CALM"}},
              "config": {"symbol": "EURUSD"}}
    edges = {"version": "1.0", "hour_utc": 14, "mom_60": 1.5}
    record = {"ts": 1, "symbol": "EURUSD", "close": 1.1, "pip": 0.0001, "atr_pips": 1.2,
              "regime": "RANGING_CALM", "edges": edges, "full": full_leaves(result), "outcome": {}}
    live = model_row(result, edges, close=1.1, pip=0.0001)
    study = _row(record)
    for key, value in live.items():
        if key.startswith(("indicators.", "edges.")) or key in ("close", "pip", "atr_pips", "ctx.regime", "ctx.symbol"):
            assert study.get(key) == value, key


def test_raw_paths_follow_a_redirected_study_dir(tmp_path, monkeypatch):
    """Bound at definition, the default kept pointing at the original capture
    after STUDY_DIR was redirected -- the decision replay scored the wrong files."""
    import gzip
    import ai.price_history_study as study

    with gzip.open(tmp_path / "EURUSD.s0of1.jsonl.gz", "wt") as fh:
        fh.write("{}\n")
    monkeypatch.setattr(study, "STUDY_DIR", tmp_path)
    assert [p.parent for p in study.raw_paths("EURUSD")] == [tmp_path]


def _quotes(n=600, bid=1.0, spread=0.0001, start=1_781_000_000):
    q = {"time": start + 60 * np.arange(n)}
    for side, base in (("bid", bid), ("ask", bid + spread)):
        for f in ("open", "high", "low", "close"):
            q[f"{side}_{f}"] = np.full(n, base)
    return q


def _with_mid(q):
    q["mid_high"] = (q["bid_high"] + q["ask_high"]) / 2
    q["mid_low"] = (q["bid_low"] + q["ask_low"]) / 2
    q["mid_close"] = (q["bid_close"] + q["ask_close"]) / 2
    return q


def test_rollover_spread_spike_cannot_fake_a_short_target_or_a_direction():
    """Bid-only bars let a spread blowout 'hit' a short's target. On quotes the
    short exits on the ask, and the mid barrier does not move."""
    import ai.price_history_study as st
    q = _quotes()
    q["bid_low"][5] = 0.9950                 # spread blows out both ways
    q["ask_high"][5] = 1.0051
    q = _with_mid(q)
    rec = {"ts": int(q["time"][0]), "atr_pips": 5.0, "pip": 0.0001, "entry": 1.0, "stop": 1.0010,
           "target": 0.9980, "direction": "SELL", "cost": {"cost_r": 0.2}, "spread_pips": 0.1}
    out = st.label_record_quotes(rec, q)
    assert out["move_5atr"] == 0                              # mid stayed inside
    assert out["bracket_sell"]["result"] == "STOP"            # ask spiked through the stop
    assert out["bracket_buy"]["result"] == "STOP"             # bid spiked through the stop
    assert out["bracket_buy"]["entry"] == pytest.approx(1.0001)  # longs fill at the ask
    assert out["commission_r"] == pytest.approx(0.2 - 0.1 * 0.0001 / 0.001)


def test_quote_bracket_pays_the_spread_inside_r():
    import ai.price_history_study as st
    q = _with_mid(_quotes(n=10, spread=0.0002))
    b = st.quote_bracket(q, 0, 10, risk=0.001, reward=0.002, sign=1)
    assert b["result"] == "TIMEOUT" and b["r"] == pytest.approx(-0.2)   # enter ask, exit bid


def test_uncovered_record_gets_no_quote_outcome():
    import ai.price_history_study as st
    q = _with_mid(_quotes(n=10))
    assert st.label_record_quotes({"ts": int(q["time"][-1]) + 3600, "pip": 0.0001}, q) is None


def test_replay_margin_is_in_account_currency_not_quote_currency():
    """Live MT5 reports margin in dollars. The shim once returned yen for
    USDJPY, sizing every replayed JPY trade at the minimum lot."""
    from types import SimpleNamespace
    import MetaTrader5 as mt5
    from core.mt5_shim import replay_context
    info = SimpleNamespace(trade_contract_size=100000.0, trade_tick_size=0.001,
                           trade_tick_value=0.1 / 155.0 * 1000, name="USDJPY")
    md = SimpleNamespace(info=info, account=SimpleNamespace(leverage=200), multi_tf_rates={}, rates=None, tick=None)
    with replay_context(md):
        assert mt5.order_calc_margin(0, "USDJPY", 1.0, 155.0) == pytest.approx(500.0, rel=1e-6)


def test_state_readings_speak_where_the_labels_are_silent():
    """The point of core/state_readings.py: supply/demand says MONITOR on 96%
    of bars and support/resistance NEUTRAL on 70%, so their groups scored on
    2.1% and 5.9%. The state reads on nearly every bar."""
    from core.state_readings import readings, summary, MEASURED
    payload = {
        "entry_details": {"entry_price": 1.1000},
        "global_anticheat": {"atr_pips": 1.0},
        "indicators": {
            "supply_demand": {"recommendation": "MONITOR",            # the label says nothing
                              "debug": {"is_demand_zone": 0, "distance_to_zone_pips": 6.0}},
            "support_resistance": {"recommendation": "NEUTRAL", "r1": 1.1005, "s1": 1.0950},
            "volume_profile": {"poc": 1.0990, "vah": 1.1020, "val": 1.0980},
        },
    }
    state = readings(payload)
    assert state["STRUCTURE"]["supply_demand_side"]["side"] == "SELL"   # supply zone
    assert state["STRUCTURE"]["nearer_pivot_level"]["side"] == "SELL"   # resistance is closer
    assert state["ORDER_FLOW"]["poc_side"]["side"] == "SELL"            # price above the POC
    assert summary(state)["scored"] is False
    # each reading carries what it was worth, so nobody re-derives it
    for group in state.values():
        for name, r in group.items():
            assert r["holdout_won_pct"] == MEASURED[name]["won_pct"]
            assert r["scored"] is False


def test_no_state_reading_is_scored_until_it_clears_the_five_star_line():
    from core.state_readings import MEASURED, FIVE_STAR_WIN_PCT, FIVE_STAR_NET_R
    for name, m in MEASURED.items():
        earns = m["won_pct"] >= FIVE_STAR_WIN_PCT and m["net_r"] >= FIVE_STAR_NET_R
        assert not earns, f"{name} now clears the line -- wire it as a vote deliberately"


def test_grouped_payload_files_every_reading_and_keeps_readers_working():
    """core/analysis_groups.py moved 45 readings under the group that trades
    them. Readers written against the flat shape must keep working, and the
    model row must still answer to the names the rules were fitted on."""
    from core.analysis_groups import reshape, block, resolve
    from core.result_leaves import model_row
    flat = {
        "indicators": {"rsi": {"rsi_14": 56.5}, "supply_demand": {"zone_grade": "C"},
                       "cot_report": {"recommendation": "EXCLUDED (M1/M5)"}},
        "smc": {"analysis": {"recommendation": "BUY"}, "available": True},
        "components": {"trend": {"score": 1}},
        "final_verdict": {"probability_percent": 74.3},
        "volatility_protection": {"atr_pips": 0.9},
    }
    grouped = reshape(dict(flat), {"MEAN_REVERSION": {"score": 61.0, "scored": True}})
    assert grouped["analysis"]["MEAN_REVERSION"]["data"]["rsi"]["rsi_14"] == 56.5
    assert grouped["analysis"]["MEAN_REVERSION"]["score"] == 61.0
    assert "indicators" not in grouped and "smc" not in grouped
    assert "components" not in grouped                      # trash
    assert "cot_report" not in str(grouped)                 # constant on M1/M5
    assert grouped["final_verdict"]["probability_percent"] == 74.3   # the decision stays put
    # a flat-shape reader still finds its block
    assert block(grouped, "indicators")["rsi"]["rsi_14"] == 56.5
    assert block(grouped, "smc")["analysis"]["recommendation"] == "BUY"
    # and the rules' names still resolve in the model row
    row = model_row(grouped)
    assert row.get("indicators.rsi.rsi_14") == 56.5
    assert row.get("analysis.MEAN_REVERSION.data.rsi.rsi_14") == 56.5
    assert resolve("indicators.rsi.rsi_14") == "analysis.MEAN_REVERSION.data.rsi.rsi_14"
