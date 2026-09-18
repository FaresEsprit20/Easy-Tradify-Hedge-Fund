"""DEMO order adapter for the frozen RSI-extreme divergence setup.

Operator decision, 2026-09-18: the generic engine's entries are OFF (no edge
was found in them; the live-engine replay showed about -0.6R per trade) and the
demo bot trades ONLY the RSI-extreme divergence setup, the one setup in the M1
audit that beat its own opposite side in both halves at every swing size.

The detector and the plan (entry, pivot stop, RSI 70/30 exit) live in
shadow_rsi_div_m1.py, frozen; this module only turns a journaled setup into a
DEMO order and enforces the exits a broker order cannot express: the RSI exit
(no price target is sent) and the study's 480-bar cap.

Safety, in order:
  * RSI_DIV_M1_LIVE off  -> nothing is sent
  * verdict not CONFIRMED (RSI_DIV_M1_REQUIRE_CONFIRMED) -> nothing is sent:
    the operator's priority is to stop losing, so no order goes out until the
    setup has proven on unseen live data that it makes money
  * not a DEMO account   -> refused (plan-v5 rule: demo until a rule passes)
  * the setup's stop is kept and the lot is sized to $4 under the $200
    margin-first ceiling (core.execution.execute_trade keep_stop=True), which
    refuses the order if even the minimum lot would risk more than the budget
  * one position per market (max_trades_per_symbol=1)
"""
from __future__ import annotations

from typing import Any, Dict, List

MAGIC = 20260918
COMMENT = "RSIdiv M1"
FIXED_TRADE_SIZE_USD = 200.0
RISK_PER_TRADE = 0.02          # $4 of the $200 trade size
MAX_SPREAD = 30                # the monitor's own limit
TRADE_DEVIATION = 20
HOLD_SECONDS = 480 * 60        # the study's 480 M1-bar cap


def live_enabled() -> bool:
    from core.asset_analysis_config import RSI_DIV_M1_LIVE
    return bool(RSI_DIV_M1_LIVE)


def require_confirmed() -> bool:
    from core.asset_analysis_config import RSI_DIV_M1_REQUIRE_CONFIRMED
    return bool(RSI_DIV_M1_REQUIRE_CONFIRMED)


def is_demo(mt5) -> bool:
    info = mt5.account_info()
    return info is not None and info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


def place(mt5, symbol: str, side: int, fill: float, stop: float, target,
          confirmed: bool = False, status: str = "") -> Dict[str, Any]:
    """Send the DEMO order for a journaled setup. Never raises; returns what happened.

    confirmed: the runner's pre-registered verdict currently reads CONFIRMED."""
    if not live_enabled():
        return {"placed": False, "reason": "RSI_DIV_M1_LIVE is off"}
    if require_confirmed() and not confirmed:
        return {"placed": False, "reason": f"not traded until the setup is CONFIRMED -- now {status}"}
    if not is_demo(mt5):
        return {"placed": False, "reason": "refused: not a demo account"}
    from core.execution import execute_trade
    sl = fill - side * stop
    tp = None if target is None else fill + side * target      # RSI exit: no broker TP
    try:
        res = execute_trade(symbol=symbol, order_type="BUY" if side == 1 else "SELL",
                            strategy_magic=MAGIC, fixed_trade_size_usd=FIXED_TRADE_SIZE_USD,
                            risk_per_trade=RISK_PER_TRADE, max_spread=MAX_SPREAD,
                            trade_deviation=TRADE_DEVIATION, max_trades_per_symbol=1,
                            comment=COMMENT, stop_loss_price=sl, take_profit_price=tp,
                            keep_stop=True)
    except Exception as e:                                # a failed order must not stop the runner
        return {"placed": False, "reason": f"execute_trade raised: {e!r}"[:300]}
    return {"placed": bool(res.get("success")), "ticket": res.get("ticket"),
            "price": res.get("price"), "volume": res.get("volume") or res.get("lot"),
            "requested_sl": sl, "requested_tp": tp,
            "stop_loss": res.get("stop_loss"), "take_profit": res.get("take_profit"),
            "reason": res.get("error") or res.get("message")}


def rsi_exits(mt5, symbol: str, rsi_now: float) -> List[Dict[str, Any]]:
    """Close this setup's positions on `symbol` once RSI reaches the exit level:
    BUY at >= 70, SELL at <= 30 (the frozen conventional exit)."""
    from engine_v2.run.shadow_rsi_div_m1 import EXIT_BUY
    closed = []
    for pos in mt5.positions_get(symbol=symbol) or ():
        if pos.magic != MAGIC:
            continue
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        if not (rsi_now >= EXIT_BUY if is_buy else rsi_now <= 100 - EXIT_BUY):
            continue
        from core.execution import close_position
        try:
            res = close_position(pos.ticket, deviation=TRADE_DEVIATION)
            closed.append({"ticket": pos.ticket, "symbol": symbol, "closed": bool(res.get("success")),
                           "rsi": round(rsi_now, 1)})
        except Exception as e:
            closed.append({"ticket": pos.ticket, "symbol": symbol, "closed": False, "reason": repr(e)[:200]})
    return closed


def time_exits(mt5) -> List[Dict[str, Any]]:
    """Close this setup's positions that have been open for the full hold.
    Ages are measured on the broker clock (tick time - position open time), so
    they survive restarts and ignore the local clock."""
    closed = []
    positions = mt5.positions_get() or ()
    for pos in positions:
        if pos.magic != MAGIC:
            continue
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None or tick.time - pos.time < HOLD_SECONDS:
            continue
        from core.execution import close_position
        try:
            res = close_position(pos.ticket, deviation=TRADE_DEVIATION)
            closed.append({"ticket": pos.ticket, "symbol": pos.symbol, "closed": bool(res.get("success")),
                           "age_min": round((tick.time - pos.time) / 60, 1)})
        except Exception as e:
            closed.append({"ticket": pos.ticket, "symbol": pos.symbol, "closed": False, "reason": repr(e)[:200]})
    return closed
