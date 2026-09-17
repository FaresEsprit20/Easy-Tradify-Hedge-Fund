import types

import pytest

from engine_v2.execution.orders import DryRunBroker, build_request, place
from engine_v2.manager.manager import LiveState, apply_actions, decide
from engine_v2.probability.frequency import MIN_SAMPLE, build_table, probability_for, wilson
from engine_v2.risk import size
from engine_v2.selection import select
from engine_v2.setup import InvalidSetup, Setup


def _s(side="BUY", entry=1.10, stop=1.09, t1=1.11, t2=1.12, **kw):
    return Setup("SMC", "fvg_mid", "EURUSD", "M15", side, 1000, 2000, {"order_type": "LIMIT", "price": entry},
                 {"price": stop}, [{"price": t1, "share": 0.5}, {"price": t2, "share": 0.5}], **kw)


def test_setup_rejects_stop_on_wrong_side():
    with pytest.raises(InvalidSetup):
        _s(stop=1.11).validate()


def test_setup_rejects_target_on_wrong_side_and_bad_shares():
    with pytest.raises(InvalidSetup):
        _s(t1=1.09).validate()
    s = _s()
    s.targets[1]["share"] = 0.4
    with pytest.raises(InvalidSetup):
        s.validate()


def test_risk_uses_caller_risk_capped_and_lot_follows_stop():
    s = _s(entry=1.1000, stop=1.0980).validate()          # 20 pips
    r = size(s, fixed_trade_size_usd=200, risk_per_trade=0.02)   # $4
    assert r["affordable"] and r["lot"] == pytest.approx(0.02)   # $4 / (0.002 x 100000)
    capped = size(s, 200, 0.10)                                   # asks 10%, capped to 2%
    assert capped["lot"] == r["lot"]


def test_risk_flags_unaffordable_instead_of_tightening_stop():
    s = _s(entry=1.1000, stop=1.0500).validate()           # 500 pips: min lot risks $50
    r = size(s, 200, 0.02)
    assert not r["affordable"] and r["lot"] == 0.0


def test_wilson_and_unknown_below_min_sample(tmp_path):
    lo, hi = wilson(65, 100)
    assert lo < 0.65 < hi
    rows = [{"category": "SMC", "variant": "fvg_mid", "side": "BUY", "status": "FILLED_CLOSED", "period": p,
             "win": i % 2 == 0, "net_r": 0.1, "context": {"h4_trend": 1}} for p in ("discovery", "holdout")
            for i in range(MIN_SAMPLE - 1)]
    path = tmp_path / "j.jsonl"
    import json
    path.write_text("\n".join(json.dumps(r) for r in rows))
    table = build_table([path])
    s = _s().validate()
    assert probability_for(s, table)["value"] is None       # 99 trades: unknown, never a guess


def test_probability_known_at_min_sample(tmp_path):
    import json
    rows = [{"category": "SMC", "variant": "fvg_mid", "side": "BUY", "status": "FILLED_CLOSED", "period": p,
             "win": i < 70, "net_r": 0.1, "context": {}} for p in ("discovery", "holdout") for i in range(100)]
    path = tmp_path / "j.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    p = probability_for(_s().validate(), build_table([path]))
    assert p["value"] == 0.70 and p["n"] == 100 and p["low"] < 0.70 < p["high"]


def test_selection_picks_highest_real_probability_among_tradeable():
    a, b, c = _s().validate(), _s().validate(), _s().validate()
    a.probability, a.risk = {"value": 0.55, "n": 200, "net_r": 0.05}, {"affordable": True}
    b.probability, b.risk = {"value": 0.62, "n": 150, "net_r": 0.10}, {"affordable": True}
    c.probability, c.risk = {"value": 0.90, "n": 150, "net_r": 0.20}, {"affordable": False}
    assert select([a, b, c]) is b
    assert select([c]) is None
    d = _s().validate()
    d.probability, d.risk = {"value": 0.70, "n": 300, "net_r": -0.02}, {"affordable": True}
    assert select([d]) is None                 # measured negative expectancy is never selected


def _mt5_stub():
    names = ["TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "ORDER_TYPE_BUY_LIMIT",
             "ORDER_TYPE_SELL_LIMIT", "ORDER_TYPE_BUY_STOP", "ORDER_TYPE_SELL_STOP", "ORDER_FILLING_IOC",
             "ORDER_FILLING_RETURN", "ORDER_TIME_GTC"]
    return types.SimpleNamespace(**{n: n for n in names})


def test_limit_setup_becomes_pending_buy_limit_with_last_target_as_tp():
    s = _s().validate()
    req = build_request(s, 0.02, 5, _mt5_stub())
    assert req["action"] == "TRADE_ACTION_PENDING" and req["type"] == "ORDER_TYPE_BUY_LIMIT"
    assert req["sl"] == 1.09 and req["tp"] == 1.12 and req["magic"] == 2002


def test_place_refuses_unaffordable_and_dry_run_never_sends_live():
    s = _s().validate()
    s.risk = {"affordable": False, "lot": 0, "reason": "too big"}
    assert place(s, DryRunBroker(), 5, _mt5_stub())["retcode"] == "NOT_TRADEABLE"
    s.risk = {"affordable": True, "lot": 0.02}
    broker = DryRunBroker()
    assert place(s, broker, 5, _mt5_stub())["retcode"] == "DRY_RUN" and len(broker.sent) == 1


def test_manager_partial_at_t1_moves_stop_to_breakeven_and_cancels_expired():
    s = _s(management={"breakeven_after_target": 1, "time_stop_bars": None}).validate()
    st = LiveState("FILLED", fill_time=1100, fill_price=1.10, current_stop=1.09)
    acts = decide(s, st, ctx=None, now=1200, bid=1.1105, ask=1.1107)
    assert [a["action"] for a in acts] == ["CLOSE_PARTIAL", "MOVE_STOP"]
    st = apply_actions(st, acts)
    assert st.targets_hit == 1 and st.current_stop == 1.10 and st.remaining_share == 0.5
    pending = LiveState("PENDING")
    assert decide(s, pending, None, now=2000, bid=1.2, ask=1.2)[0]["action"] == "CANCEL_PENDING"
