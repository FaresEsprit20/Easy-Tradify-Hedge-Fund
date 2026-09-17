# ============================================================
# MARKET STOP -- the stop comes from the market, the lot from the risk
# ============================================================
# FILE: core/market_stop.py
#
# The account stop (target_risk / pip value at the largest lot the $200
# margin allows) sat about one M1 ATR from entry: ordinary noise, so on
# tick-accurate bid/ask brackets a correct direction reached its target only
# 27% of the time, and the large lot made commission 0.4-0.7R per trade.
#
# Here the stop is MARKET_STOP_H1_ATR_MULTIPLE x ATR(14) of closed H1 bars,
# never inside SL_MIN_SPREAD_MULTIPLE x the spread; the target is
# MARKET_TARGET_R x the stop; the lot is the largest volume step whose loss
# at the stop stays within the dollar risk (2% of the budget). Tick grid,
# 17 symbols, selection period (ticks, 24h, both sides):
#
#   stop x H1 ATR  target  perfect-direction ceiling  random net  commission
#   1.0            1R      0.869                      -0.202R     0.074R
#   1.5            1R      0.872                      -0.158R     0.049R
#   2.0            1R      0.829                      -0.128R     0.037R
#
# When even the minimum volume risks more than MAX_RISK_OVERSHOOT x the
# budget (gold at $4), the plan says so (`affordable` False) instead of
# silently risking several times the budget.
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np

# ✅ 2026-09-16: widened from 1.5 ATR / 1R after measuring the exact
# win-rate vs expectancy frontier on 109,719 trades with first-touch
# resolution (tradify_study/frontier.py). A wider stop shrinks the lot, so
# commission per R falls with it, and the trade survives the give-back the
# excursion study found (72.7% of trades reach +0.25R, 70.6% still end at the
# stop; a peak inside the first hour holds only 2.8% of the time):
#
#   stop ATR  target ATR   win     net R    (holdout)
#   1.5       1.5          46.1%   -0.133   -0.141    <- what shipped this morning
#   3.0       0.375        83.7%   -0.081   -0.081
#   4.0       0.750        75.9%   -0.078   -0.077
#   4.0       0.375        86.4%   -0.063   -0.062
#   4.0       0.125        94.0%   -0.050   -0.048
#
# REVERTED 2026-09-16 by the operator's call, and the call is right: a 4 ATR
# stop with a 0.375 ATR target buys a 86% win rate by picking pennies in front
# of the stop. It improves the reported numbers without improving a single
# signal, and the expectancy stays negative either way. The geometry stays
# where the tick study put it; the work belongs in signal quality.
MARKET_STOP_H1_ATR_MULTIPLE = 1.5
MARKET_TARGET_R = 1.0
H1_ATR_BARS = 14
MAX_RISK_OVERSHOOT = 1.1


def h1_atr(rates, bars: int = H1_ATR_BARS) -> Optional[float]:
    """ATR over the last `bars` CLOSED H1 bars (the study's h1_atr_at)."""
    if rates is None or len(rates) < bars + 1:
        return None
    h = np.asarray(rates["high"], dtype=float)[-bars:]
    l = np.asarray(rates["low"], dtype=float)[-bars:]
    c = np.asarray(rates["close"], dtype=float)[-bars - 1:-1]
    v = float(np.maximum(h - l, np.maximum(abs(h - c), abs(l - c))).mean())
    return v if v > 0 else None


def lot_for_risk(risk_per_lot_usd: float, target_risk_usd: float, volume_min: float,
                 volume_step: float, volume_max: float) -> float:
    """Largest tradable volume whose loss at the stop is <= the budget; the
    broker minimum when even that is over budget (the caller checks)."""
    if risk_per_lot_usd <= 0:
        return volume_min
    step = volume_step or 0.01
    lot = math.floor((target_risk_usd / risk_per_lot_usd) / step + 1e-9) * step
    return round(max(volume_min, min(lot, volume_max)), 2)


def plan(symbol: str, side: str, target_risk_usd: float, h1_rates=None) -> Optional[Dict[str, Any]]:
    """Stop, target and lot for entering `side` now. None without market data."""
    import MetaTrader5 as mt5
    from core.asset_analysis_config import SL_MIN_SPREAD_MULTIPLE
    from core.calculations import get_pip_info
    from core.closed_bars import is_active as closed_bars_active

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None or not tick.ask or not tick.bid:
        return None
    if h1_rates is None:
        h1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, H1_ATR_BARS + 2)
        # outside a closed-bars analysis (and outside replay) the last bar is forming
        if h1_rates is not None and len(h1_rates) and not closed_bars_active():
            h1_rates = h1_rates[:-1]
    atr = h1_atr(h1_rates)
    if not atr:
        return None
    buy = str(side).upper() == "BUY"
    entry = float(tick.ask if buy else tick.bid)
    spread = float(tick.ask - tick.bid)
    stop_distance = max(MARKET_STOP_H1_ATR_MULTIPLE * atr, SL_MIN_SPREAD_MULTIPLE * spread)
    target_distance = MARKET_TARGET_R * stop_distance
    stop = entry - stop_distance if buy else entry + stop_distance
    target = entry + target_distance if buy else entry - target_distance
    order_type = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
    loss = mt5.order_calc_profit(order_type, symbol, 1.0, entry, stop)
    if loss is None or loss == 0:
        tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
        tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
        if tick_size <= 0 or tick_value <= 0:
            return None
        loss = stop_distance / tick_size * tick_value
    risk_per_lot = abs(float(loss))
    lot = lot_for_risk(risk_per_lot, target_risk_usd, float(info.volume_min or 0.01),
                       float(info.volume_step or 0.01), float(info.volume_max or 100.0))
    risk = lot * risk_per_lot
    # the margin THIS lot needs -- the analysis publishes it, and it must
    # describe the position actually sized here, not the one the account-derived
    # sizing would have taken
    margin = mt5.order_calc_margin(order_type, symbol, lot, entry)
    if margin is None or margin <= 0:
        leverage = float(getattr(mt5.account_info(), "leverage", 0) or 0) if mt5.account_info() else 0
        contract = float(getattr(info, "trade_contract_size", 0) or 0)
        margin = (lot * contract * entry / leverage) if leverage > 0 and contract > 0 else None
    pip_size, _, digits = get_pip_info(info)
    return {
        "side": "BUY" if buy else "SELL",
        "entry": round(entry, digits),
        "h1_atr": atr,
        "stop_price": round(stop, digits),
        "target_price": round(target, digits),
        "stop_pips": round(stop_distance / pip_size, 1),
        "target_pips": round(target_distance / pip_size, 1),
        "lot": lot,
        "risk_usd": round(risk, 2),
        "margin_usd": round(float(margin), 2) if margin else None,
        "target_risk_usd": round(target_risk_usd, 2),
        "affordable": risk <= target_risk_usd * MAX_RISK_OVERSHOOT,
        "stop_h1_atr_multiple": MARKET_STOP_H1_ATR_MULTIPLE,
        "target_r": MARKET_TARGET_R,
    }


def get_status() -> Dict[str, Any]:
    return {"component": "market_stop", "stop_h1_atr_multiple": MARKET_STOP_H1_ATR_MULTIPLE,
            "target_r": MARKET_TARGET_R}
