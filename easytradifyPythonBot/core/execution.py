# ============================================================
# core/execution.py - COMPLETE FIXED VERSION WITH WEBHOOK FOR TRAILING STOP
# ============================================================

import MetaTrader5 as mt5
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import threading
import time
from dataclasses import dataclass, field
import math
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any

import json
import requests

# Spread-aware stop floor. calculate_lot() below derives its stop from
# the account's risk budget, which on a wide-spread instrument lands the
# stop near the spread itself -- see the note at "7b. MINIMUM STOP
# DISTANCE" for the measured consequences.
from core.asset_analysis_config import (SL_MIN_SPREAD_MULTIPLE, MAX_LOT_TRIM_FRACTION, USE_MARKET_STOP,
                                        MAX_RISK_PER_TRADE)

logger = logging.getLogger(__name__)

# =====================================================
# ERROR CODES
# =====================================================
class ErrorCode:
    UNKNOWN_ERROR = 1000
    INVALID_PARAMETERS = 1001
    MT5_NOT_INITIALIZED = 1002
    SYMBOL_NOT_FOUND = 2000
    SYMBOL_LOCKED = 2001
    SYMBOL_NOT_VISIBLE = 2002
    MAX_TRADES_REACHED = 3000
    MAX_TRADES_PER_SYMBOL_REACHED = 3001
    SPREAD_TOO_HIGH = 3002
    TRADE_FAILED = 3003
    REQUOTE_ERROR = 3004
    INVALID_ORDER_TYPE = 3005
    TRADE_DEVIATION_TOO_HIGH = 3006
    POSITION_NOT_FOUND = 4000
    CLOSE_POSITION_FAILED = 4001
    MODIFY_SL_FAILED = 4002
    MODIFY_TP_FAILED = 4003
    PARTIAL_CLOSE_FAILED = 4004
    INVALID_VOLUME = 4005
    LOT_CALCULATION_FAILED = 5000
    PIP_VALUE_CALCULATION_FAILED = 5001
    MARGIN_CALCULATION_FAILED = 5002
    ACCOUNT_INFO_FAILED = 6000


# =====================================================
# CUSTOM EXCEPTIONS
# =====================================================
class TradingException(Exception):
    def __init__(self, error_code: int, message: str, details: Optional[Dict] = None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class SymbolNotFoundException(TradingException):
    def __init__(self, symbol: str):
        super().__init__(ErrorCode.SYMBOL_NOT_FOUND, f"Symbol {symbol} not found", {"symbol": symbol})


class SpreadTooHighException(TradingException):
    def __init__(self, symbol: str, current_spread: float, max_spread: float):
        super().__init__(ErrorCode.SPREAD_TOO_HIGH, f"Spread {current_spread:.1f} > {max_spread}", 
                        {"symbol": symbol, "current_spread": current_spread, "max_spread": max_spread})


class PositionNotFoundException(TradingException):
    def __init__(self, ticket: int):
        super().__init__(ErrorCode.POSITION_NOT_FOUND, f"Position {ticket} not found", {"ticket": ticket})


class ClosePositionFailedException(TradingException):
    def __init__(self, ticket: int, retcode: int):
        super().__init__(ErrorCode.CLOSE_POSITION_FAILED, f"Failed to close position {ticket}", 
                        {"ticket": ticket, "retcode": retcode})


class ModifySLFailedException(TradingException):
    def __init__(self, ticket: int, retcode: int):
        super().__init__(ErrorCode.MODIFY_SL_FAILED, f"Failed to modify SL for position {ticket}", 
                        {"ticket": ticket, "retcode": retcode})


# =====================================================
# SAFE DICT CONVERTER
# =====================================================
def safe_dict(obj):
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    return obj


# =====================================================
# GLOBAL STATE
# =====================================================
_active_trails: Dict[int, Dict] = {}
_trail_monitor_running = False
_monitor_thread = None
_trail_stats = {
    "total_updates": 0,
    "breakeven_applied": 0,
    "trailing_updates": 0,
    "last_update_time": 0
}
_symbol_exchange_map: Dict[str, str] = {}

# =====================================================
# BREAK-EVEN STATUS TRACKING
# =====================================================
# Keyed by ticket (position ticket). Records the break-even state for a
# position for as long as it stays open, and is snapshotted onto the
# trade-history record when the position closes so closed trades keep
# a permanent record of whether break-even was applied.
_break_even_status: Dict[int, Dict[str, Any]] = {}

# Closed-trade break-even snapshots, keyed by ticket, so get_trade_history()
# can still report break-even status after _break_even_status is cleaned up.
_break_even_history: Dict[int, Dict[str, Any]] = {}

# =====================================================
# MULTI TAKE-PROFIT (TP2 / TP3) TRACKING
# =====================================================
# MT5 only supports a single native TP per position. When TP2/TP3 are
# supplied, we skip setting a native TP and instead track the split
# levels here; the trailing/position monitor watches price and issues
# partial closes as each level is reached.
_multi_tp_positions: Dict[int, Dict[str, Any]] = {}

# =====================================================
# TRAILING STOP WEBHOOK
# =====================================================
_trailing_webhook_url = "http://localhost:5001/trailing/update"
_trailing_webhook_enabled = False


def set_symbol_exchange_map(exchange_map: Dict[str, str]):
    """Set the symbol exchange map from the monitor."""
    global _symbol_exchange_map
    _symbol_exchange_map = exchange_map
    logger.info(f"✅ Symbol exchange map set with {len(exchange_map)} symbols")


def get_exchange_for_symbol(symbol: str) -> Optional[str]:
    """Get exchange for a symbol from SYMBOL_EXCHANGE_MAP."""
    global _symbol_exchange_map
    if _symbol_exchange_map:
        return _symbol_exchange_map.get(symbol)
    return None


def enable_trailing_webhook(url: str = "http://localhost:5001/trailing/update"):
    """Enable webhook for trailing stop updates."""
    global _trailing_webhook_url, _trailing_webhook_enabled
    _trailing_webhook_url = url
    _trailing_webhook_enabled = True
    logger.info(f"✅ Trailing stop webhook enabled: {url}")


def disable_trailing_webhook():
    """Disable webhook for trailing stop updates."""
    global _trailing_webhook_enabled
    _trailing_webhook_enabled = False
    logger.info("Trailing stop webhook disabled")


def send_trailing_webhook(ticket: int, symbol: str, action: str, 
                          sl_price: float, profit_pips: float = 0.0, 
                          step_pips: float = 0.0, price: float = None,
                          entry_price: float = None, profit_usd: float = None,
                          usd_distance: float = None):
    """Send trailing stop update via webhook."""
    if not _trailing_webhook_enabled:
        return
    
    try:
        data = {
            "event": "TRAILING_STOP",
            "ticket": ticket,
            "symbol": symbol,
            "action": action,  # "BREAKEVEN" or "TRAIL"
            "sl_price": sl_price,
            "profit_pips": round(profit_pips, 1),
            "step_pips": step_pips,
            "profit_usd": round(profit_usd, 2) if profit_usd is not None else None,
            "usd_distance": usd_distance,
            "price": price,
            "entry_price": entry_price,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Send async to avoid blocking
        def _send():
            try:
                response = requests.post(_trailing_webhook_url, json=data, timeout=1)
                if response.status_code != 200:
                    logger.debug(f"Trailing webhook failed: {response.status_code}")
                else:
                    logger.debug(f"✅ Trailing webhook sent: {symbol} ticket={ticket} action={action}")
            except Exception as e:
                logger.debug(f"Trailing webhook error: {e}")
        
        thread = threading.Thread(target=_send, daemon=True)
        thread.start()
        
    except Exception as e:
        logger.debug(f"Failed to send trailing webhook: {e}")


# =====================================================
# PROBABILITY OF HIT
# =====================================================
def calculate_probability_of_hit(symbol: str, entry_price: float, stop_loss: float, take_profit: float, 
                                   order_type: str, lookback_period: int = 100) -> float:
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, lookback_period)
        if rates is None or len(rates) < 20:
            return 0.5
        
        price_changes = []
        for i in range(1, len(rates)):
            high_low_range = (rates[i][2] - rates[i][3]) / entry_price
            price_changes.append(high_low_range)
        
        avg_volatility = np.mean(price_changes) if price_changes else 0.01
        
        if order_type.upper() == "BUY":
            sl_distance = abs(entry_price - stop_loss) / entry_price
            tp_distance = abs(take_profit - entry_price) / entry_price
        else:
            sl_distance = abs(entry_price - stop_loss) / entry_price
            tp_distance = abs(entry_price - take_profit) / entry_price
        
        current_spread = get_current_spread(symbol)
        spread_penalty = min(0.1, current_spread / 100)
        
        if sl_distance + tp_distance > 0:
            base_probability = tp_distance / (sl_distance + tp_distance)
        else:
            base_probability = 0.5
        
        volatility_factor = 1 - min(0.3, avg_volatility * 10)
        
        trend_strength = calculate_trend_strength(symbol, lookback_period)
        trend_factor = 0.5 + (trend_strength * 0.3) if order_type.upper() == "BUY" else 0.5 - (trend_strength * 0.3)
        trend_factor = max(0.2, min(0.8, trend_factor))
        
        final_probability = base_probability * volatility_factor * trend_factor * (1 - spread_penalty)
        final_probability = max(0.05, min(0.95, final_probability))
        
        return round(final_probability, 4)
        
    except Exception as e:
        logger.error(f"Failed to calculate probability of hit: {e}")
        return 0.5


def get_current_spread(symbol: str) -> float:
    try:
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick and info:
            return (tick.ask - tick.bid) / info.point
    except:
        pass
    return 0


def calculate_trend_strength(symbol: str, lookback_period: int = 100) -> float:
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, lookback_period)
        if rates is None or len(rates) < 20:
            return 0
        
        plus_dm = []
        minus_dm = []
        tr = []
        
        for i in range(1, len(rates)):
            high_diff = rates[i][2] - rates[i-1][2]
            low_diff = rates[i-1][3] - rates[i][3]
            
            plus_dm.append(max(high_diff, 0) if high_diff > low_diff else 0)
            minus_dm.append(max(low_diff, 0) if low_diff > high_diff else 0)
            
            true_range = max(
                rates[i][2] - rates[i][3],
                abs(rates[i][2] - rates[i-1][4]),
                abs(rates[i][3] - rates[i-1][4])
            )
            tr.append(true_range)
        
        if not tr:
            return 0
            
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
        
        if atr == 0:
            return 0
            
        plus_di = np.mean(plus_dm[-14:]) / atr if len(plus_dm) >= 14 else np.mean(plus_dm) / atr
        minus_di = np.mean(minus_dm[-14:]) / atr if len(minus_dm) >= 14 else np.mean(minus_dm) / atr
        
        if plus_di + minus_di > 0:
            dx = abs(plus_di - minus_di) / (plus_di + minus_di)
        else:
            dx = 0
            
        return min(1.0, dx)
        
    except Exception as e:
        logger.error(f"Failed to calculate trend strength: {e}")
        return 0


# =====================================================
# MARKET FUNCTIONS - SINGLE DEFINITION
# =====================================================

def is_market_closed(symbol: str) -> Dict[str, Any]:
    """
    Determine if a market is closed using the age of the latest MT5 tick.

    Works well for:
      - Forex
      - Metals
      - Commodities
      - Indices
      - CFDs

    It does NOT rely on bid/ask because MT5 keeps the last quote after
    the market closes.
    """

    try:

        info = mt5.symbol_info(symbol)

        if info is None:
            return {
                "success": False,
                "symbol": symbol,
                "is_closed": True,
                "is_tradable": False,
                "reason": "Symbol not found"
            }

        if not info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            return {
                "success": True,
                "symbol": symbol,
                "is_closed": True,
                "is_tradable": False,
                "reason": "No tick received from broker"
            }

        # --------------------------------------------------
        # Calculate tick age
        # --------------------------------------------------

        now = datetime.now(timezone.utc).timestamp()

        tick_age = now - tick.time

        # --------------------------------------------------
        # Threshold (seconds)
        # --------------------------------------------------

        # 3 minutes is a reasonable default for Forex/CFDs.
        MAX_TICK_AGE = 180

        if tick_age > MAX_TICK_AGE:
            return {
                "success": True,
                "symbol": symbol,
                "is_closed": True,
                "is_tradable": False,
                "reason": f"Last tick is {int(tick_age)} seconds old",
                "tick_age_seconds": int(tick_age),
                "last_tick_time": datetime.fromtimestamp(
                    tick.time,
                    timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            }

        bid = tick.bid
        ask = tick.ask

        spread = 0.0

        if info.point > 0:
            spread = (ask - bid) / info.point

            if info.digits in (3, 5):
                spread /= 10

        return {
            "success": True,
            "symbol": symbol,
            "is_closed": False,
            "is_tradable": True,
            "reason": f"Live quote ({int(tick_age)} seconds old)",
            "tick_age_seconds": int(tick_age),
            "last_tick_time": datetime.fromtimestamp(
                tick.time,
                timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "bid": bid,
            "ask": ask,
            "spread_pips": round(spread, 1)
        }

    except Exception as e:

        return {
            "success": False,
            "symbol": symbol,
            "is_closed": True,
            "is_tradable": False,
            "reason": str(e)
        }


def check_volatility(symbol: str, lookback_period: int = 20) -> Dict[str, Any]:
    try:
        atr = get_atr_value(symbol, lookback_period)
        if atr == 0:
            return {
                "success": False,
                "error": "Failed to calculate ATR",
                "volatility_level": "UNKNOWN"
            }
        
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {
                "success": False,
                "error": "No tick data available",
                "volatility_level": "UNKNOWN"
            }
        
        current_price = tick.ask if tick.ask > 0 else tick.bid
        volatility_percent = (atr / current_price) * 100 if current_price > 0 else 0
        
        info = mt5.symbol_info(symbol)
        if info:
            if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
                pip_size = 0.01 if info.digits == 2 else 0.1
            elif "XAG" in symbol.upper() or "SILVER" in symbol.upper():
                pip_size = 0.001 if info.digits == 3 else 0.01
            elif "JPY" in symbol.upper():
                pip_size = 0.01
            else:
                pip_to_points = 10 if info.digits in [3, 5] else 1
                pip_size = info.point * pip_to_points
        else:
            pip_size = 0.0001
        
        atr_pips = atr / pip_size if pip_size > 0 else 0
        
        if volatility_percent < 0.3:
            level = "LOW"
        elif volatility_percent < 1.0:
            level = "NORMAL"
        else:
            level = "HIGH"
        
        return {
            "success": True,
            "symbol": symbol,
            "volatility_level": level,
            "atr_value": round(atr, 5),
            "atr_pips": round(atr_pips, 2),
            "volatility_percent": round(volatility_percent, 2),
            "lookback_period": lookback_period,
            "current_price": current_price,
            "description": f"{level} volatility ({volatility_percent:.2f}% of price)"
        }
        
    except Exception as e:
        logger.error(f"Failed to check volatility for {symbol}: {e}")
        return {
            "success": False,
            "error": str(e),
            "volatility_level": "UNKNOWN"
        }


def check_spread_status(symbol: str, max_spread_pips: float = 30) -> Dict[str, Any]:
    try:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {
                "success": False,
                "error": "No tick data available",
                "spread_status": "UNKNOWN"
            }
        
        info = mt5.symbol_info(symbol)
        if not info:
            return {
                "success": False,
                "error": f"Symbol {symbol} not found",
                "spread_status": "UNKNOWN"
            }
        
        spread_points = (tick.ask - tick.bid) / info.point if info.point > 0 else 0
        if info.digits in [3, 5]:
            spread_pips = spread_points / 10
        else:
            spread_pips = spread_points
        
        if spread_pips < 5:
            status = "GOOD"
            description = f"Excellent spread ({spread_pips:.1f} pips)"
            recommendation = "TRADE"
            is_acceptable = True
        elif spread_pips <= 30:
            status = "NORMAL"
            description = f"Normal spread ({spread_pips:.1f} pips)"
            recommendation = "TRADE"
            is_acceptable = True
        else:
            status = "HIGH"
            description = f"High spread ({spread_pips:.1f} pips) - NOT TRADEABLE"
            recommendation = "AVOID"
            is_acceptable = False
        
        return {
            "success": True,
            "symbol": symbol,
            "spread_status": status,
            "spread_points": round(spread_points, 2),
            "spread_pips": round(spread_pips, 1),
            "bid": tick.bid,
            "ask": tick.ask,
            "max_allowed_pips": max_spread_pips,
            "is_acceptable": is_acceptable,
            "description": description,
            "recommendation": recommendation
        }
        
    except Exception as e:
        logger.error(f"Failed to check spread for {symbol}: {e}")
        return {
            "success": False,
            "error": str(e),
            "spread_status": "UNKNOWN"
        }


# =====================================================
# POSITIONS
# =====================================================
def get_open_positions(symbol: Optional[str] = None) -> List[Dict]:
    try:
        if not mt5.terminal_info():
            logger.error("MT5 terminal not connected")
            return []
        
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            error = mt5.last_error()
            logger.error(f"positions_get() returned None. MT5 error: {error}")
            return []

        if len(positions) == 0:
            return []

        formatted_positions = []
        for pos in positions:
            try:
                info = mt5.symbol_info(pos.symbol)
                if not info:
                    continue
                
                digits = info.digits
                commission = getattr(pos, 'commission', 0.0)
                if commission is None:
                    commission = 0.0
                
                total_profit = pos.profit + pos.swap + commission

                be_status = _break_even_status.get(pos.ticket, {})

                formatted_positions.append({
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": "BUY" if pos.type == 0 else "SELL",
                    "volume": pos.volume,
                    "price_open": round(pos.price_open, digits),
                    "price_current": round(pos.price_current, digits),
                    "stop_loss": round(pos.sl, digits) if pos.sl and pos.sl > 0 else None,
                    "take_profit": round(pos.tp, digits) if pos.tp and pos.tp > 0 else None,
                    "profit_usd": round(pos.profit, 2),
                    "swap_usd": round(pos.swap, 2),
                    "commission_usd": round(commission, 2),
                    "total_profit_usd": round(total_profit, 2),
                    "magic": pos.magic,
                    "comment": pos.comment,
                    "time": datetime.fromtimestamp(pos.time).isoformat() if pos.time else None,
                    "has_break_even": be_status.get("has_break_even", pos.ticket in _active_trails and
                                       _active_trails[pos.ticket].get("break_even_enabled", False)),
                    "break_even_applied": be_status.get("break_even_applied", False),
                    "break_even_trigger": be_status.get("break_even_trigger"),
                    "break_even_trigger_type": be_status.get("break_even_trigger_type"),
                })
                
            except Exception as e:
                logger.error(f"Error formatting position {pos.ticket}: {e}")
                continue

        return formatted_positions

    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        return []


def get_open_positions_count(symbol: Optional[str] = None) -> int:
    return len(get_open_positions(symbol))


# =====================================================
# TRADE HISTORY
# =====================================================
# ============================================================
# CLOSE REASON -- RESOLVED FROM THE SERVER, NOT GUESSED
# ============================================================

# MT5 sets DEAL_REASON on the closing deal. It is the only authoritative
# answer to "did this hit target or stop", and it is what both this function
# and mq5/AutoTradeWebhook.mq5 now read.
DEAL_REASON_LABELS = {
    0: "MANUAL",        # DEAL_REASON_CLIENT
    1: "MANUAL",        # DEAL_REASON_MOBILE
    2: "MANUAL",        # DEAL_REASON_WEB
    3: "EXPERT",        # DEAL_REASON_EXPERT  -- closed by an EA
    4: "STOP_LOSS",     # DEAL_REASON_SL
    5: "TAKE_PROFIT",   # DEAL_REASON_TP
    6: "STOP_OUT",      # DEAL_REASON_SO     -- margin stop-out
}


def resolve_close_reason(ticket: int, lookback_days: int = 7) -> str:
    """
    Why a position actually closed: TAKE_PROFIT, STOP_LOSS, STOP_OUT,
    EXPERT, MANUAL -- or UNKNOWN when the server does not say.

    Replaces the hardcoded "SL_TP_HIT" that several call sites wrote for every
    close regardless of what happened. That string conflates the two outcomes
    the whole system is trying to learn from: a trade that reached target and
    a trade that hit its stop were recorded identically, so any analysis
    grouping by close reason was grouping noise.

    Returns UNKNOWN rather than a plausible default. A wrong label here is
    worse than a missing one -- it is silently wrong in the training data.
    """
    try:
        import MetaTrader5 as mt5
    except Exception:
        return "UNKNOWN"

    try:
        from datetime import datetime, timedelta
        end = datetime.now() + timedelta(days=1)
        start = end - timedelta(days=lookback_days + 1)
        deals = mt5.history_deals_get(start, end)
        if not deals:
            return "UNKNOWN"

        # The CLOSING deal for this position: entry is OUT (or OUT_BY).
        exits = [
            d for d in deals
            if getattr(d, "position_id", None) == int(ticket)
            and getattr(d, "entry", None) in (mt5.DEAL_ENTRY_OUT,
                                              mt5.DEAL_ENTRY_OUT_BY)
        ]
        if not exits:
            return "UNKNOWN"

        # Last one wins for a position closed in several partial fills.
        deal = max(exits, key=lambda d: getattr(d, "time", 0))
        reason = getattr(deal, "reason", None)
        if reason is None:
            return "UNKNOWN"
        return DEAL_REASON_LABELS.get(int(reason), "UNKNOWN")
    except Exception as exc:
        logger.warning(f"resolve_close_reason({ticket}) failed: {exc}")
        return "UNKNOWN"


def get_trade_history(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    symbol: Optional[str] = None,
    magic: Optional[int] = None,
    last_n_days: Optional[int] = None
) -> Dict[str, Any]:
    try:
        from datetime import timezone, timedelta

        force_history_sync()
        
        now = datetime.now(timezone.utc)

        if last_n_days is not None:
            from_date = now - timedelta(days=last_n_days)
            to_date = now

        if from_date is None:
            from_date = now - timedelta(days=30)
        if to_date is None:
            to_date = now

        from_timestamp = int(from_date.timestamp())
        to_timestamp = int(to_date.timestamp())

        logger.info(f"Fetching history from {from_date} to {to_date}")

        deals = None
        for attempt in range(5):
            if symbol:
                deals = mt5.history_deals_get(from_timestamp, to_timestamp, group=symbol)
            else:
                deals = mt5.history_deals_get(from_timestamp, to_timestamp)
            
            if deals is not None and len(deals) > 0:
                logger.info(f"Found {len(deals)} deals on attempt {attempt + 1}")
                break
            logger.warning(f"Attempt {attempt + 1}: No deals found, retrying...")
            time.sleep(0.5)

        if deals is None:
            error = mt5.last_error()
            logger.error(f"history_deals_get() returned None. MT5 error: {error}")
            return {"success": False, "error": f"MT5 error: {error}", "deals": [], "summary": {}}

        entry_map = {
            mt5.DEAL_ENTRY_IN:     "entry",
            mt5.DEAL_ENTRY_OUT:    "exit",
            mt5.DEAL_ENTRY_INOUT:  "reverse",
            mt5.DEAL_ENTRY_OUT_BY: "close_by",
        }

        positions_map = {}
        for deal in deals:
            if deal.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue

            if magic is not None and deal.magic != magic:
                continue

            position_id = deal.position_id
            if position_id not in positions_map:
                positions_map[position_id] = {"entry": [], "exit": []}
            
            entry_type = entry_map.get(deal.entry, "unknown")
            if entry_type == "entry":
                positions_map[position_id]["entry"].append(deal)
            elif entry_type == "exit":
                positions_map[position_id]["exit"].append(deal)

        formatted = []
        for deal in deals:
            if deal.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue

            if magic is not None and deal.magic != magic:
                continue

            net_profit = round(deal.profit + deal.swap + deal.commission + deal.fee, 2)
            deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)

            formatted.append({
                "ticket":       deal.ticket,
                "order":        deal.order,
                "position_id":  deal.position_id,
                "symbol":       deal.symbol,
                "type":         "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                "entry":        entry_map.get(deal.entry, "unknown"),
                "volume":       deal.volume,
                "price":        deal.price,
                # NOTE: no separate "profit" field - net_profit already includes
                # profit + swap + commission + fee combined, avoiding duplicate/
                # inconsistent profit reporting across endpoints.
                "swap":         round(deal.swap, 2),
                "commission":   round(deal.commission, 2),
                "fee":          round(deal.fee, 2),
                "net_profit":   net_profit,
                "magic":        deal.magic,
                "comment":      deal.comment,
                "time":         deal_time.isoformat(),
                "time_msc":     deal.time_msc,
            })

        grouped_trades = []
        for position_id, deals_data in positions_map.items():
            entry_deals = deals_data["entry"]
            exit_deals = deals_data["exit"]

            if not entry_deals:
                continue

            entry_deal = entry_deals[0]
            
            if exit_deals:
                total_profit = sum(d.profit for d in exit_deals)
                total_swap = sum(d.swap for d in exit_deals)
                total_commission = sum(d.commission for d in exit_deals)
                total_fee = sum(d.fee for d in exit_deals)
                total_net_profit = total_profit + total_swap + total_commission + total_fee
                is_closed = True
                exit_time = datetime.fromtimestamp(exit_deals[-1].time, tz=timezone.utc).isoformat()
                exit_price = exit_deals[-1].price
                exit_tickets = [d.ticket for d in exit_deals]
            else:
                total_profit = 0
                total_swap = 0
                total_commission = 0
                total_fee = 0
                total_net_profit = 0
                is_closed = False
                exit_time = None
                exit_price = None
                exit_tickets = []

            entry_ticket = entry_deal.ticket
            be_status = _break_even_status.get(entry_ticket) or _break_even_history.get(entry_ticket) or {}

            grouped_trades.append({
                "position_id": position_id,
                "symbol": entry_deal.symbol,
                "type": "BUY" if entry_deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                "entry_ticket": entry_ticket,
                "exit_tickets": exit_tickets,
                "volume": entry_deal.volume,
                "entry_price": entry_deal.price,
                "exit_price": exit_price,
                "entry_time": datetime.fromtimestamp(entry_deal.time, tz=timezone.utc).isoformat(),
                "entry_timestamp": entry_deal.time,
                "exit_time": exit_time,
                # NOTE: no separate "profit" field - net_profit already includes
                # profit + swap + commission + fee combined.
                "swap": round(total_swap, 2),
                "commission": round(total_commission, 2),
                "fee": round(total_fee, 2),
                "net_profit": round(total_net_profit, 2),
                "is_closed": is_closed,
                "magic": entry_deal.magic,
                "comment": entry_deal.comment,
                "has_break_even": be_status.get("has_break_even", False),
                "break_even_applied": be_status.get("break_even_applied", False),
                "break_even_trigger": be_status.get("break_even_trigger"),
                "break_even_trigger_type": be_status.get("break_even_trigger_type"),
            })

        # Latest trades first.
        grouped_trades.sort(key=lambda t: t["entry_timestamp"], reverse=True)
        for t in grouped_trades:
            t.pop("entry_timestamp", None)

        closed_trades = [t for t in grouped_trades if t["is_closed"]]
        profits = [t["net_profit"] for t in closed_trades]
        winners = [p for p in profits if p > 0]
        losers = [p for p in profits if p < 0]

        total_profit = round(sum(profits), 2) if profits else 0
        win_rate = round(len(winners) / len(profits) * 100, 2) if profits else 0
        avg_win = round(sum(winners) / len(winners), 2) if winners else 0
        avg_loss = round(sum(losers) / len(losers), 2) if losers else 0
        profit_factor = (
            round(sum(winners) / abs(sum(losers)), 2)
            if losers and sum(losers) != 0 else None
        )
        expectancy = round(
            (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss), 2
        ) if profits else 0

        symbol_stats: Dict[str, Any] = {}
        for t in closed_trades:
            s = t["symbol"]
            if s not in symbol_stats:
                symbol_stats[s] = {"trades": 0, "net_profit": 0.0, "wins": 0, "losses": 0}
            symbol_stats[s]["trades"] += 1
            symbol_stats[s]["net_profit"] = round(symbol_stats[s]["net_profit"] + t["net_profit"], 2)
            if t["net_profit"] > 0:
                symbol_stats[s]["wins"] += 1
            elif t["net_profit"] < 0:
                symbol_stats[s]["losses"] += 1

        for s in symbol_stats:
            t = symbol_stats[s]["trades"]
            symbol_stats[s]["win_rate"] = round(symbol_stats[s]["wins"] / t * 100, 2) if t else 0

        summary = {
            "total_deals": len(formatted),
            "closed_trades": len(closed_trades),
            "open_trades_in_history": len(grouped_trades) - len(closed_trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "total_profit": total_profit,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "by_symbol": symbol_stats,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        }

        logger.info(
            f"Trade history: {len(closed_trades)} closed trades | "
            f"P&L: ${total_profit} | Win rate: {win_rate}%"
        )

        return {
            "success": True,
            "deals": formatted,
            "trades": grouped_trades,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"Failed to get trade history: {e}")
        return {"success": False, "error": str(e), "deals": [], "summary": {}}


def force_history_sync() -> bool:
    try:
        mt5.positions_get()
        time.sleep(0.3)
        mt5.account_info()
        time.sleep(0.3)
        mt5.symbols_get()
        time.sleep(0.3)
        logger.info("MT5 history sync completed")
        return True
    except Exception as e:
        logger.error(f"Failed to sync MT5 history: {e}")
        return False


# =====================================================
# CHECK FUNCTIONS
# =====================================================
def check_spread(symbol: str, max_spread: float) -> None:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if not tick or not info:
        raise SymbolNotFoundException(symbol)
    spread = (tick.ask - tick.bid) / info.point
    if spread > max_spread:
        raise SpreadTooHighException(symbol, spread, max_spread)


def validate_symbol(symbol: str) -> None:
    info = mt5.symbol_info(symbol)
    if not info:
        raise SymbolNotFoundException(symbol)
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            raise SymbolNotFoundException(symbol)


def get_pip_value(symbol: str, lot_size: float) -> float:
    info = mt5.symbol_info(symbol)
    if not info:
        raise SymbolNotFoundException(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        raise TradingException(ErrorCode.PIP_VALUE_CALCULATION_FAILED, f"Cannot get tick for {symbol}", {"symbol": symbol})
    
    tick_value = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, lot_size, tick.bid, tick.bid + info.point * 10)
    if tick_value:
        return abs(tick_value) / 10
    else:
        contract_size = info.trade_contract_size if info.trade_contract_size else 100000
        pip_size = info.point * (10 if info.digits in [3, 5] else 1)
        return lot_size * contract_size * pip_size


def _order_spread_pips(tick, symbol_info) -> Optional[float]:
    """Spread of a quote, in the platform's pip unit. None if unmeasurable."""
    try:
        if not tick or not tick.ask or not tick.bid or tick.ask < tick.bid:
            return None
        pip, _, _ = get_pip_info(symbol_info)
        return round((tick.ask - tick.bid) / pip, 2) if pip else None
    except Exception:
        return None


def get_pip_info(symbol_info) -> Tuple[float, float, int]:
    point = float(symbol_info.point) if symbol_info.point else 0.00001
    digits = int(symbol_info.digits) if symbol_info.digits else 5
    
    symbol_upper = symbol_info.name.upper()
    
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        pip_size = 0.01 if digits == 2 else 0.1
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        pip_size = 0.001 if digits == 3 else 0.01
    elif "JPY" in symbol_upper:
        pip_size = 0.01
    else:
        pip_to_points = 10 if digits in [3, 5] else 1
        pip_size = point * pip_to_points
    
    return pip_size, point, digits


# =====================================================
# LOT CALCULATION - FIXED RISK BASED ($10 = 5% of $200)
# =====================================================
# =====================================================
# LOT CALCULATION - DYNAMIC SL OPTIMIZATION
# WITH COMPLETE OUTPUT INCLUDING MARGIN
# =====================================================

def calculate_lot(
    symbol: str, 
    fixed_trade_size_usd: float, 
    risk_per_trade: float, 
    leverage: int = 200, 
    order_type: str = "BUY", 
    min_stop_pips_override: Optional[float] = None
) -> Dict[str, Any]:
    """
    ✅ FIXED: Find optimal lot that maximizes margin usage while keeping risk ≤ $10.
    ✅ Uses dynamic SL - the tighter the SL, the larger the lot.
    ✅ Tries to get margin as close to $200 as possible.
    ✅ Returns ALL fields including actual_margin.
    """
    
    # ============================================================
    # 1. GET SYMBOL AND CURRENT PRICE
    # ============================================================
    
    info = mt5.symbol_info(symbol)
    if not info:
        raise Exception(f"Symbol info not found: {symbol}")
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        raise Exception(f"No tick data for {symbol}")
    
    if order_type.upper() == "BUY":
        current_price = tick.ask
        order_type_mt5 = mt5.ORDER_TYPE_BUY
    else:
        current_price = tick.bid
        order_type_mt5 = mt5.ORDER_TYPE_SELL
    
    # ============================================================
    # 2. GET ACCOUNT INFO
    # ============================================================
    
    account = mt5.account_info()
    actual_leverage = account.leverage if account and account.leverage else leverage
    
    # ============================================================
    # 3. CALCULATE PIP INFO
    # ============================================================
    
    digits = info.digits
    pip_size, _, _ = get_pip_info(info)
    contract_size = float(info.trade_contract_size) if info.trade_contract_size else 100000
    volume_step = info.volume_step if info.volume_step else 0.01
    volume_min = info.volume_min if info.volume_min else 0.01
    volume_max = info.volume_max if info.volume_max else 100
    
    # ============================================================
    # 4. TARGETS
    # ============================================================
    
    target_risk = fixed_trade_size_usd * risk_per_trade  # $10 (5% of $200)
    target_margin = fixed_trade_size_usd  # $200
    
    # ============================================================
    # 5. FIND MAX LOT ALLOWED BY MARGIN ($200)
    # ============================================================
    
    min_lot = 0.01
    max_lot = 100.0
    max_margin_lot = 0.01
    
    for _ in range(50):
        mid_lot = (min_lot + max_lot) / 2
        margin = mt5.order_calc_margin(
            order_type_mt5,
            symbol,
            mid_lot,
            current_price
        )
        
        if margin is None or margin <= 0:
            margin = (mid_lot * contract_size * current_price) / actual_leverage
        
        if margin <= target_margin:
            max_margin_lot = mid_lot
            min_lot = mid_lot
        else:
            max_lot = mid_lot
    
    max_margin_lot = math.floor(max_margin_lot / volume_step) * volume_step
    max_margin_lot = max(volume_min, min(max_margin_lot, volume_max))
    max_margin_lot = round(max_margin_lot, 2)
    
    # ============================================================
    # 6. ✅ DYNAMIC SL: Find LOT and SL that BOTH hit targets
    # ============================================================
    
    test_lot = max_margin_lot
    
    # Calculate pip value for this lot
    if order_type.upper() == "BUY":
        test_price = current_price + (pip_size * 1.0)
    else:
        test_price = current_price - (pip_size * 1.0)
    
    pip_value = mt5.order_calc_profit(
        order_type_mt5,
        symbol,
        test_lot,
        current_price,
        test_price
    )
    
    if pip_value and pip_value > 0:
        pip_value_per_pip = abs(pip_value) / 1.0
    else:
        pip_value_per_pip = test_lot * contract_size * pip_size
    
    # Required SL for target risk with this lot
    if pip_value_per_pip > 0:
        required_sl_pips = target_risk / pip_value_per_pip
    else:
        required_sl_pips = 5.0
    
    # ============================================================
    # 7. ✅ CHECK IF SL IS TOO TIGHT - REDUCE LOT IF NEEDED
    # ============================================================
    
    MIN_SL_PIPS = 1.0  # Minimum reasonable SL
    MAX_SL_PIPS = 1000.0  # Maximum reasonable SL
    
    while required_sl_pips < MIN_SL_PIPS and test_lot > volume_min:
        test_lot = max(volume_min, test_lot - volume_step)
        test_lot = round(test_lot, 2)
        
        if order_type.upper() == "BUY":
            test_price = current_price + (pip_size * 1.0)
        else:
            test_price = current_price - (pip_size * 1.0)
        
        pip_value = mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            test_lot,
            current_price,
            test_price
        )
        
        if pip_value and pip_value > 0:
            pip_value_per_pip = abs(pip_value) / 1.0
        else:
            pip_value_per_pip = test_lot * contract_size * pip_size
        
        if pip_value_per_pip > 0:
            required_sl_pips = target_risk / pip_value_per_pip
        else:
            required_sl_pips = 5.0
    
    if required_sl_pips > MAX_SL_PIPS:
        required_sl_pips = MAX_SL_PIPS

    # ============================================================
    # 7b. MINIMUM STOP DISTANCE  (spread-aware)
    # ============================================================
    # Same defect, same fix as core/calculations.py's
    # calculate_lot_proper(): everything above derives the stop from the
    # ACCOUNT (target_risk / pip_value at the largest lot margin allows)
    # and never consults the market, and `min_stop_pips_override` was
    # accepted here, passed by callers, and never read.
    #
    # This copy is the one that matters most: calculate_lot() is what
    # api/execute_copy_trade.py and api/execution_controller.py call to
    # size REAL orders. Fixing calculations.py alone left the live path
    # on the broken version -- a static check for parameters that are
    # accepted and never read is what surfaced it, after a manual audit
    # had already missed it.
    #
    # On XAGUSD the unguarded version produced a ~33-pip stop against a
    # 20-pip spread on every decision; 22.8% of trades had a spread wider
    # than their entire stop and were losing at entry as a matter of
    # arithmetic. Dollar risk is held constant -- the lot is scaled down
    # by the same ratio the stop is widened.
    _sl_floor = float(MIN_SL_PIPS)
    _floor_reasons = []
    try:
        _spread_now = ((tick.ask - tick.bid) / pip_size
                       if tick.ask and tick.bid and tick.ask > tick.bid and pip_size > 0
                       else 0.0)
    except (AttributeError, TypeError, ZeroDivisionError):
        _spread_now = 0.0

    if _spread_now > 0:
        _sf = _spread_now * SL_MIN_SPREAD_MULTIPLE
        if _sf > _sl_floor:
            _sl_floor = _sf
            _floor_reasons.append(f"spread {_spread_now:.1f}p x {SL_MIN_SPREAD_MULTIPLE}")

    if min_stop_pips_override is not None:
        try:
            _ov = float(min_stop_pips_override)
            if _ov > _sl_floor:
                _sl_floor = _ov
                _floor_reasons.append(f"min_stop_pips_override {_ov:.1f}p")
        except (TypeError, ValueError):
            logger.warning(f"[LOT] {symbol}: ignoring non-numeric "
                           f"min_stop_pips_override {min_stop_pips_override!r}")

    _sl_floor = min(_sl_floor, MAX_SL_PIPS)

    if required_sl_pips < _sl_floor:
        _widened_from = required_sl_pips
        _shrink = _widened_from / _sl_floor if _sl_floor > 0 else 1.0
        required_sl_pips = _sl_floor
        _scaled = math.floor((test_lot * _shrink) / volume_step) * volume_step
        _scaled = round(max(volume_min, min(_scaled, volume_max)), 2)
        logger.info(
            f"[LOT] {symbol}: stop widened {_widened_from:.1f}p -> "
            f"{required_sl_pips:.1f}p ({', '.join(_floor_reasons)}); "
            f"lot {test_lot} -> {_scaled} to hold risk at ${target_risk:.2f}")
        if test_lot * _shrink < volume_min:
            logger.warning(
                f"[LOT] {symbol}: a {required_sl_pips:.1f}p stop at the minimum "
                f"lot {volume_min} risks more than the ${target_risk:.2f} budget "
                f"-- this setup is too expensive to take at this size")
        test_lot = _scaled

    # ============================================================
    # 8. ✅ FINAL LOT = test_lot
    # ============================================================
    
    final_lot = test_lot
    final_sl_pips = required_sl_pips
    
    # ============================================================
    # 9. CALCULATE ACTUAL VALUES
    # ============================================================
    
    if order_type.upper() == "BUY":
        sl_price = current_price - (final_sl_pips * pip_size)
        tp_price = current_price + (final_sl_pips * 2 * pip_size)  # 2:1 R:R
    else:
        sl_price = current_price + (final_sl_pips * pip_size)
        tp_price = current_price - (final_sl_pips * 2 * pip_size)
    
    actual_risk = abs(mt5.order_calc_profit(
        order_type_mt5,
        symbol,
        final_lot,
        current_price,
        sl_price
    ))
    
    if actual_risk is None or actual_risk <= 0:
        actual_risk = final_sl_pips * pip_value_per_pip  # NOT * final_lot: pip_value_per_pip is already the value AT final_lot
    
    # ✅ CALCULATE ACTUAL MARGIN
    actual_margin = mt5.order_calc_margin(
        order_type_mt5,
        symbol,
        final_lot,
        current_price
    )
    
    if actual_margin is None or actual_margin <= 0:
        actual_margin = (final_lot * contract_size * current_price) / actual_leverage
    
    # ============================================================
    # 10. ✅ VERIFY BOTH CONSTRAINTS
    # ============================================================
    
    actual_risk = round(actual_risk, 2)
    actual_margin = round(actual_margin, 2)
    final_sl_pips = round(final_sl_pips, 1)
    
    warnings = []
    
    # Risk check (UNCHANGED FROM ORIGINAL - margin untouched here)
    if actual_risk > target_risk:
        warnings.append(f"Risk ${actual_risk:.2f} exceeds target ${target_risk:.2f}")
        final_lot = final_lot * (target_risk / actual_risk) * 0.99
        final_lot = math.floor(final_lot / volume_step) * volume_step
        final_lot = max(volume_min, min(final_lot, volume_max))
        final_lot = round(final_lot, 2)
        
        if order_type.upper() == "BUY":
            test_price = current_price + (pip_size * 1.0)
        else:
            test_price = current_price - (pip_size * 1.0)
        
        pip_value = mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            test_price
        )
        
        if pip_value and pip_value > 0:
            pip_value_per_pip = abs(pip_value) / 1.0
        else:
            pip_value_per_pip = final_lot * contract_size * pip_size
        
        if pip_value_per_pip > 0:
            final_sl_pips = target_risk / pip_value_per_pip
            final_sl_pips = round(final_sl_pips, 1)
        else:
            final_sl_pips = 5.0
        
        if order_type.upper() == "BUY":
            sl_price = current_price - (final_sl_pips * pip_size)
        else:
            sl_price = current_price + (final_sl_pips * pip_size)
        
        actual_risk = abs(mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            sl_price
        ))
        
        if actual_risk is None or actual_risk <= 0:
            actual_risk = final_sl_pips * pip_value_per_pip  # NOT * final_lot: pip_value_per_pip is already the value AT final_lot
        
        actual_margin = mt5.order_calc_margin(
            order_type_mt5,
            symbol,
            final_lot,
            current_price
        )
        
        if actual_margin is None or actual_margin <= 0:
            actual_margin = (final_lot * contract_size * current_price) / actual_leverage
        
        actual_risk = round(actual_risk, 2)
        actual_margin = round(actual_margin, 2)
    
    # Margin check (UNCHANGED FROM ORIGINAL - identical to the uploaded file,
    # not touched or refactored - margin logic/threshold is exactly as-is)
    if actual_margin > target_margin:
        warnings.append(f"Margin ${actual_margin:.2f} exceeds target ${target_margin:.2f}")
        final_lot = final_lot * (target_margin / actual_margin) * 0.99
        final_lot = math.floor(final_lot / volume_step) * volume_step
        final_lot = max(volume_min, min(final_lot, volume_max))
        final_lot = round(final_lot, 2)
        
        if order_type.upper() == "BUY":
            test_price = current_price + (pip_size * 1.0)
        else:
            test_price = current_price - (pip_size * 1.0)
        
        pip_value = mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            test_price
        )
        
        if pip_value and pip_value > 0:
            pip_value_per_pip = abs(pip_value) / 1.0
        else:
            pip_value_per_pip = final_lot * contract_size * pip_size
        
        if pip_value_per_pip > 0:
            final_sl_pips = target_risk / pip_value_per_pip
            final_sl_pips = round(final_sl_pips, 1)
        else:
            final_sl_pips = 5.0
        
        if order_type.upper() == "BUY":
            sl_price = current_price - (final_sl_pips * pip_size)
        else:
            sl_price = current_price + (final_sl_pips * pip_size)
        
        actual_risk = abs(mt5.order_calc_profit(
            order_type_mt5,
            symbol,
            final_lot,
            current_price,
            sl_price
        ))
        
        if actual_risk is None or actual_risk <= 0:
            actual_risk = final_sl_pips * pip_value_per_pip  # NOT * final_lot: pip_value_per_pip is already the value AT final_lot
        
        actual_margin = mt5.order_calc_margin(
            order_type_mt5,
            symbol,
            final_lot,
            current_price
        )
        
        if actual_margin is None or actual_margin <= 0:
            actual_margin = (final_lot * contract_size * current_price) / actual_leverage
        
        actual_risk = round(actual_risk, 2)
        actual_margin = round(actual_margin, 2)

    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # STRICT RISK GUARANTEE -- stop first, then a BOUNDED lot trim
    #
    # What stood here recomputed the stop from scratch for every candidate
    # lot:  sl_pips = target_risk / pip_value(lot).  That makes risk equal
    # target_risk by construction for ANY lot, so the loop's exit test
    # (risk < 0.995 x target) could never become true -- it just ran its
    # 100-iteration cap every single call, walking the lot down by
    # 100 * volume_step.  On the .NYSE/.NAS stocks (step 0.10) that is a
    # flat -10.00 lots: MCD sized at 13.00 came back as 3.00, $38.10 of
    # margin against a $200 target.
    #
    # The risk it reported was fiction as well.  order_calc_profit() from
    # the entry to a STOP returns a NEGATIVE number -- it is a loss -- so
    # the `risk_raw > 0` test threw away the broker's real answer on every
    # call and fell through to `lot * sl_pips * pip_value_per_pip`, in
    # which pip_value_per_pip is ALREADY the value for that lot.  The
    # surplus factor of `lot` is the phantom "risk = target x lot" that is
    # stored on every trade in the collection: $1.39 recorded against a
    # 0.34-lot EURUSD whose true risk was $4.08.
    #
    # Correct order of operations: the lot is set by the margin target and
    # STAYS there; risk is steered with the stop, which is free to move.
    # The lot is trimmed only when the stop is already on its spread floor
    # and cannot tighten further -- and then only within
    # MAX_LOT_TRIM_FRACTION, so the margin target is never abandoned the
    # way it was above.
    # ------------------------------------------------------------
    _pvpp_base_lot = final_lot
    _pvpp_base = pip_value_per_pip

    def _risk_of(lot: float, stop_price: float) -> float:
        """Broker-true risk for a lot/stop, unrounded.

        abs() rather than a `> 0` test: a stop is a loss and MT5 reports it
        negative, which is exactly what the previous version mistook for a
        failed call.
        """
        r = mt5.order_calc_profit(order_type_mt5, symbol, lot,
                                  current_price, stop_price)
        if r is not None and r != 0:
            return abs(r)
        # Fallback only when MT5 declines to answer. _pvpp_base is the pip
        # value AT _pvpp_base_lot, so it is rescaled to `lot` -- never
        # multiplied by `lot` on top of itself.
        pips = abs(stop_price - current_price) / pip_size if pip_size > 0 else 0.0
        per_pip = (_pvpp_base * (lot / _pvpp_base_lot)) if _pvpp_base_lot > 0 else _pvpp_base
        return pips * per_pip

    def _stop_for(pips: float) -> float:
        return (current_price - pips * pip_size) if order_type.upper() == "BUY"             else (current_price + pips * pip_size)

    safety_margin = 0.995  # land just UNDER target, never on it
    safe_target_risk_raw = target_risk * safety_margin  # unrounded
    actual_risk_raw = _risk_of(final_lot, sl_price)

    # --- 1. Steer with the STOP. Lot and margin untouched. ------------
    if actual_risk_raw > 0:
        _want_pips = round(final_sl_pips * (safe_target_risk_raw / actual_risk_raw), 1)
        _want_pips = max(_sl_floor, min(_want_pips, MAX_SL_PIPS))
        if abs(_want_pips - final_sl_pips) >= 0.05:
            final_sl_pips = _want_pips
            sl_price = _stop_for(final_sl_pips)
            actual_risk_raw = _risk_of(final_lot, sl_price)

    # --- 2. Stop is pinned at its floor and risk is still over budget.
    #        Trim the lot, bounded, with the stop now held FIXED (which is
    #        what makes the loop actually converge). --------------------
    _lot_floor = max(volume_min,
                     round(math.floor((final_lot * MAX_LOT_TRIM_FRACTION) / volume_step)
                           * volume_step, 2))
    _lot_before_trim = final_lot
    reduction_attempts = 0
    while (actual_risk_raw >= safe_target_risk_raw
           and round(final_lot - volume_step, 2) >= _lot_floor
           and reduction_attempts < 200):
        candidate_lot = round(final_lot - volume_step, 2)
        if candidate_lot == final_lot:
            break
        final_lot = candidate_lot
        actual_risk_raw = _risk_of(final_lot, sl_price)  # stop held fixed
        reduction_attempts += 1

    if reduction_attempts:
        logger.info(
            f"[LOT] {symbol}: stop pinned at floor {final_sl_pips:.1f}p; lot "
            f"trimmed {_lot_before_trim} -> {final_lot} "
            f"(floor {_lot_floor}) to bring risk to ${actual_risk_raw:.2f}")

    # pip_value_per_pip is a RETURNED field and callers size from it, so it
    # has to describe the lot actually being sent, not the one this block
    # started with.
    pip_value_per_pip = _risk_of(final_lot, _stop_for(1.0))

    if actual_risk_raw >= target_risk:
        # Say so rather than shrinking silently past the trim bound.
        warnings.append(
            f"Risk ${actual_risk_raw:.4f} still >= target ${target_risk:.2f} at lot "
            f"{final_lot} with a {final_sl_pips:.1f}p stop "
            f"(spread floor {_sl_floor:.1f}p, lot floor {_lot_floor})")


    # Recompute TP alongside the final SL so it stays at the 2:1 R:R ratio.
    if order_type.upper() == "BUY":
        tp_price = current_price + (final_sl_pips * 2 * pip_size)
    else:
        tp_price = current_price - (final_sl_pips * 2 * pip_size)

    actual_risk = round(actual_risk_raw, 2)

    # Margin is re-derived exactly once here for the FINAL lot, using the
    # identical original formula/fallback - no new margin logic, no new
    # threshold, just keeping the returned margin_required accurate for
    # whatever lot the stop-loss tightening above landed on.
    actual_margin = mt5.order_calc_margin(order_type_mt5, symbol, final_lot, current_price)
    if actual_margin is None or actual_margin <= 0:
        actual_margin = (final_lot * contract_size * current_price) / actual_leverage
    actual_margin = round(actual_margin, 2)

    # ============================================================
    # 11. LOG RESULTS
    # ============================================================
    
    logger.info(f"✅ LOT CALCULATION (DYNAMIC SL OPTIMIZATION):")
    logger.info(f"   Symbol: {symbol}")
    logger.info(f"   Current Price: {current_price}")
    logger.info(f"   Target Risk: ${target_risk:.2f}")
    logger.info(f"   Target Margin: ${target_margin:.2f}")
    logger.info(f"   Max Margin Lot: {max_margin_lot:.2f}")
    logger.info(f"   Final Lot: {final_lot:.2f}")
    logger.info(f"   SL: {final_sl_pips:.1f} pips")
    # These two lines used to print a hardcoded checkmark whatever the
    # numbers were, so a $12.00 risk against a $4.00 target still logged as
    # "✅" and the sizing looked healthy while it was not. The mark is
    # derived now.
    logger.info(f"   Actual Risk: ${actual_risk:.2f} vs target ${target_risk:.2f} "
                f"{'✅' if actual_risk < target_risk else '❌ OVER TARGET'}")
    logger.info(f"   Actual Margin: ${actual_margin:.2f} vs target ${target_margin:.2f} "
                f"{'✅' if actual_margin <= target_margin else '❌ OVER TARGET'}")
    logger.info(f"   Gap to Target Margin: ${target_margin - actual_margin:.2f}")
    
    if warnings:
        logger.warning(f"⚠️ WARNINGS:")
        for w in warnings:
            logger.warning(f"   - {w}")
    
    # ============================================================
    # 12. ✅ RETURN - INCLUDING ALL FIELDS
    # ============================================================
    
    return {
        "success": True,
        "data": {
            "lot": final_lot,
            "actual_risk": actual_risk,
            "margin_required": actual_margin,  # ✅ THIS IS THE FIELD
            "pip_value": round(pip_value_per_pip, 4),
            "stop_loss_price": round(sl_price, digits),
            "stop_loss_pips": final_sl_pips,
            "take_profit_price": round(tp_price, digits),
            "target_risk": target_risk,
            "target_margin": target_margin,
            "fixed_trade_size_usd": fixed_trade_size_usd,
            "risk_per_trade": risk_per_trade,
            "leverage": actual_leverage,
            "risk_percent": round(actual_risk / account.balance * 100, 2) if account else 0,
            "margin_percent": round(actual_margin / account.balance * 100, 2) if account else 0,
            "current_price": current_price,
            "warnings": warnings,
            "max_margin_lot": max_margin_lot,
            "margin_gap": round(target_margin - actual_margin, 2),
            "risk_strictly_below_target": actual_risk < target_risk,
            "risk_safety_margin_percent": round((1 - safety_margin) * 100, 2)
        }
    }
    
# =====================================================
# BREAK-EVEN + USD/PIPS TRAILING STOP ENGINE
# =====================================================

def _profit_usd_from_entry(position, current_price: float) -> float:
    try:
        order_type = mt5.ORDER_TYPE_BUY if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_SELL
        value = mt5.order_calc_profit(order_type, position.symbol, position.volume, position.price_open, current_price)
        return float(value) if value is not None else 0.0
    except Exception as e:
        logger.error(f"Failed to calculate profit distance for {position.symbol}: {e}")
        return 0.0


def _usd_price_distance(symbol: str, volume: float, usd_distance: float, reference_price: float, direction: str) -> Optional[float]:
    """Convert USD stop distance to price distance using MT5 profit calculation."""
    if usd_distance <= 0 or volume <= 0 or reference_price <= 0:
        return None
    info = mt5.symbol_info(symbol)
    if not info or info.point <= 0:
        return None
    direction = direction.upper()
    if direction not in ("BUY", "SELL"):
        return None

    close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
    sign = -1.0 if direction == "BUY" else 1.0

    def loss_for_distance(distance: float) -> float:
        target_price = reference_price + sign * distance
        value = mt5.order_calc_profit(close_type, symbol, volume, reference_price, target_price)
        return abs(float(value)) if value is not None else 0.0

    low = 0.0
    high = info.point
    target = float(usd_distance)
    for _ in range(60):
        if reference_price + sign * high <= 0:
            return None
        if loss_for_distance(high) >= target:
            break
        high *= 2.0
    else:
        return None

    for _ in range(50):
        mid = (low + high) / 2.0
        if loss_for_distance(mid) < target:
            low = mid
        else:
            high = mid
    return high


def calculate_profit_usd(ticket: int) -> Dict[str, Any]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        raise PositionNotFoundException(ticket)
    pos = position[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    if not tick:
        raise TradingException(ErrorCode.UNKNOWN_ERROR, f"No tick available for {pos.symbol}")
    current_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
    profit_usd = _profit_usd_from_entry(pos, current_price)
    return {"success": True, "ticket": ticket, "symbol": pos.symbol, "profit_usd": round(profit_usd, 2),
            "current_price": current_price, "entry_price": pos.price_open}


def get_break_even_status(ticket: int) -> Dict[str, Any]:
    """Return the current break-even status for a position (open or closed)."""
    if ticket in _break_even_status:
        return {"success": True, "ticket": ticket, **_break_even_status[ticket]}
    if ticket in _break_even_history:
        return {"success": True, "ticket": ticket, **_break_even_history[ticket]}
    return {"success": True, "ticket": ticket, "has_break_even": False, "break_even_applied": False,
            "break_even_trigger": None, "break_even_trigger_type": None, "break_even_price": None}


def _record_break_even_status(ticket: int, symbol: str, applied: bool, trigger_type: str,
                               trigger_value: float, breakeven_price: Optional[float] = None):
    """Track break-even state for a position so it can be surfaced on positions/history."""
    existing = _break_even_status.get(ticket, {})
    _break_even_status[ticket] = {
        "symbol": symbol,
        "has_break_even": True,
        # Sticky: once applied, stays applied even if this call didn't (re)trigger it.
        "break_even_applied": applied or existing.get("break_even_applied", False),
        "break_even_trigger": trigger_value,
        "break_even_trigger_type": trigger_type,
        "break_even_price": breakeven_price if breakeven_price is not None else existing.get("break_even_price"),
    }


def _clear_break_even_status(ticket: int):
    """Move a position's break-even status into history and drop it from the live map."""
    status = _break_even_status.pop(ticket, None)
    if status is not None:
        _break_even_history[ticket] = status


def apply_break_even(ticket: int, pips_distance: Optional[float] = None, usd_distance: Optional[float] = None) -> Dict[str, Any]:
    """Move SL to entry after exactly one configured pips/USD trigger is reached."""
    if (pips_distance is None) == (usd_distance is None):
        return {"success": False, "error": "Exactly one of pips_distance or usd_distance must be provided"}
    if pips_distance is not None and pips_distance <= 0:
        return {"success": False, "error": "pips_distance must be > 0"}
    if usd_distance is not None and usd_distance <= 0:
        return {"success": False, "error": "usd_distance must be > 0"}

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        raise PositionNotFoundException(ticket)
    pos = positions[0]
    info = mt5.symbol_info(pos.symbol)
    tick = mt5.symbol_info_tick(pos.symbol)
    if not info or not tick:
        return {"success": False, "error": f"Missing symbol/tick data for {pos.symbol}"}

    current_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
    profit_usd = _profit_usd_from_entry(pos, current_price)

    if usd_distance is not None:
        reached = profit_usd >= usd_distance
        trigger_type = "usd_distance"
        trigger_value = usd_distance
    else:
        pip_size, _, _ = get_pip_info(info)
        profit_pips = ((current_price - pos.price_open) / pip_size if pos.type == mt5.POSITION_TYPE_BUY
                       else (pos.price_open - current_price) / pip_size)
        reached = profit_pips >= pips_distance
        trigger_type = "pips_distance"
        trigger_value = pips_distance

    if not reached:
        _record_break_even_status(ticket, pos.symbol, False, trigger_type, trigger_value)
        return {"success": True, "applied": False, "ticket": ticket, "symbol": pos.symbol,
                "trigger_type": trigger_type, "trigger_distance": trigger_value,
                "profit_usd": round(profit_usd, 2), "message": "Break-even trigger not reached"}

    be_price = round(pos.price_open, info.digits)
    current_sl = pos.sl if pos.sl and pos.sl > 0 else None
    if pos.type == mt5.POSITION_TYPE_BUY:
        if current_sl is not None and current_sl >= be_price:
            _record_break_even_status(ticket, pos.symbol, True, trigger_type, trigger_value, be_price)
            return {"success": True, "applied": False, "already_at_or_better": True, "ticket": ticket,
                    "symbol": pos.symbol, "breakeven_price": be_price, "profit_usd": round(profit_usd, 2)}
    else:
        if current_sl is not None and current_sl <= be_price:
            _record_break_even_status(ticket, pos.symbol, True, trigger_type, trigger_value, be_price)
            return {"success": True, "applied": False, "already_at_or_better": True, "ticket": ticket,
                    "symbol": pos.symbol, "breakeven_price": be_price, "profit_usd": round(profit_usd, 2)}

    result = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": be_price, "tp": pos.tp})
    if not result or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
        raise ModifySLFailedException(ticket, getattr(result, "retcode", -1) if result else -1)

    _trail_stats["breakeven_applied"] += 1
    _trail_stats["total_updates"] += 1
    _trail_stats["last_update_time"] = time.time()
    _record_break_even_status(ticket, pos.symbol, True, trigger_type, trigger_value, be_price)
    logger.info(f"Break-even applied: {pos.symbol} ticket={ticket} SL={be_price} profit=${profit_usd:.2f}")
    if _trailing_webhook_enabled:
        send_trailing_webhook(ticket, pos.symbol, "BREAKEVEN", be_price, 0.0, 0.0, current_price,
                              pos.price_open, profit_usd, usd_distance)
    return {"success": True, "applied": True, "ticket": ticket, "symbol": pos.symbol,
            "breakeven_price": be_price, "profit_usd": round(profit_usd, 2),
            "trigger_type": trigger_type, "trigger_distance": trigger_value}


def start_trailing_monitor(interval_seconds: float = 1.0):
    global _trail_monitor_running, _monitor_thread
    if _trail_monitor_running:
        return
    _trail_monitor_running = True
    def monitor_loop():
        while _trail_monitor_running:
            try:
                update_all_trailing_stops()
                time.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Trailing monitor error: {e}")
    _monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    _monitor_thread.start()
    logger.info("Auto position-management monitor started")


def stop_trailing_monitor():
    global _trail_monitor_running
    _trail_monitor_running = False


def update_all_trailing_stops():
    # Union of tickets under trailing/break-even management and tickets with a
    # TP2/TP3 split pending, so multi-TP positions get monitored even when
    # break-even/trailing weren't separately enabled for them.
    tickets = set(_active_trails.keys()) | set(_multi_tp_positions.keys())
    for ticket in list(tickets):
        config = _active_trails.get(ticket, {})
        try:
            update_single_trailing_stop(ticket, config)
        except Exception as e:
            logger.error(f"Failed to update position management for {ticket}: {e}")


def update_single_trailing_stop(ticket: int, config: Dict):
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        if ticket in _active_trails:
            del _active_trails[ticket]
        _clear_break_even_status(ticket)
        _multi_tp_positions.pop(ticket, None)
        return

    pos = positions[0]
    info = mt5.symbol_info(pos.symbol)
    tick = mt5.symbol_info_tick(pos.symbol)
    if not info or not tick:
        return

    # Multi-TP (TP2/TP3) partial-close management, independent of break-even/trailing.
    if ticket in _multi_tp_positions:
        _check_multi_tp_levels(ticket, pos, info, tick)

    # Independent break-even method.
    if config.get("break_even_enabled"):
        be_result = apply_break_even(
            ticket,
            pips_distance=config.get("break_even_pips_distance"),
            usd_distance=config.get("break_even_usd_distance")
        )
        if be_result.get("applied"):
            refreshed = mt5.positions_get(ticket=ticket)
            if not refreshed:
                return
            pos = refreshed[0]
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return

    if not config.get("trailing_enabled"):
        return

    current_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
    profit_usd = _profit_usd_from_entry(pos, current_price)
    usd_distance = config.get("usd_distance")
    pips_distance = config.get("pips_distance")

    if usd_distance is not None:
        price_distance = _usd_price_distance(
            pos.symbol, pos.volume, float(usd_distance), current_price,
            "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        )
        if price_distance is None or profit_usd < float(usd_distance):
            return
        distance_text = f"${float(usd_distance):.2f}"
    else:
        if pips_distance is None or pips_distance <= 0:
            return
        pip_size, _, _ = get_pip_info(info)
        price_distance = float(pips_distance) * pip_size
        profit_pips = ((current_price - pos.price_open) / pip_size if pos.type == mt5.POSITION_TYPE_BUY
                       else (pos.price_open - current_price) / pip_size)
        if profit_pips < float(pips_distance):
            return
        distance_text = f"{float(pips_distance):g} pips"

    if pos.type == mt5.POSITION_TYPE_BUY:
        trail_price = round(current_price - price_distance, info.digits)
        current_sl = pos.sl if pos.sl and pos.sl > 0 else None
        should_update = current_sl is None or trail_price > current_sl
    else:
        trail_price = round(current_price + price_distance, info.digits)
        current_sl = pos.sl if pos.sl and pos.sl > 0 else None
        should_update = current_sl is None or trail_price < current_sl

    min_distance = max(info.trade_stops_level, info.trade_freeze_level) * info.point
    if pos.type == mt5.POSITION_TYPE_BUY:
        trail_price = min(trail_price, round(current_price - min_distance, info.digits)) if min_distance > 0 else trail_price
        should_update = current_sl is None or trail_price > current_sl
    else:
        trail_price = max(trail_price, round(current_price + min_distance, info.digits)) if min_distance > 0 else trail_price
        should_update = current_sl is None or trail_price < current_sl

    if not should_update:
        return
    if pos.type == mt5.POSITION_TYPE_BUY and trail_price >= current_price:
        return
    if pos.type == mt5.POSITION_TYPE_SELL and trail_price <= current_price:
        return

    result = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": trail_price, "tp": pos.tp})
    if result and result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
        config["last_sl"] = trail_price
        _trail_stats["trailing_updates"] += 1
        _trail_stats["total_updates"] += 1
        _trail_stats["last_update_time"] = time.time()
        logger.info(f"Trailing stop updated: {pos.symbol} ticket={ticket} SL={trail_price} distance={distance_text} profit=${profit_usd:.2f}")
        if _trailing_webhook_enabled:
            send_trailing_webhook(ticket, pos.symbol, "TRAIL", trail_price, 0.0,
                                  float(pips_distance or 0.0), current_price, pos.price_open,
                                  profit_usd, usd_distance)
    else:
        logger.warning(f"Trailing SL update failed for {ticket}: retcode={getattr(result, 'retcode', None) if result else None}")


def _check_multi_tp_levels(ticket: int, pos, info, tick):
    """Check TP2/TP3 levels for a position and partial-close as each is reached."""
    config = _multi_tp_positions.get(ticket)
    if not config:
        return

    current_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
    is_buy = pos.type == mt5.POSITION_TYPE_BUY

    for level in config["levels"]:
        if level["closed"]:
            continue

        level_price = level["price"]
        reached = (current_price >= level_price) if is_buy else (current_price <= level_price)
        if not reached:
            continue

        # Last remaining level closes whatever volume is left (avoids leaving dust
        # open due to rounding across the earlier partial closes).
        remaining_levels = [l for l in config["levels"] if not l["closed"]]
        is_last_level = len(remaining_levels) == 1

        try:
            fresh = mt5.positions_get(ticket=ticket)
            if not fresh:
                level["closed"] = True
                continue
            current_volume = fresh[0].volume

            if is_last_level:
                volume_to_close = current_volume
            else:
                volume_to_close = round(config["original_volume"] * level["percent"] / 100.0, 2)
                volume_step = info.volume_step if info.volume_step else 0.01
                volume_to_close = math.floor(volume_to_close / volume_step) * volume_step
                volume_to_close = min(volume_to_close, current_volume)

            if volume_to_close is None or volume_to_close <= 0:
                level["closed"] = True
                continue

            if volume_to_close >= current_volume:
                # Closing everything - use close_position to fully close cleanly.
                close_position(ticket)
            else:
                partial_close_position(ticket, volume_to_close)

            level["closed"] = True
            logger.info(f"Multi-TP level {level['label']} hit for ticket={ticket} at {level_price}, "
                        f"closed {volume_to_close} ({level['percent']}%)")
            if _trailing_webhook_enabled:
                send_trailing_webhook(ticket, pos.symbol, f"TP_{level['label']}", level_price,
                                      price=current_price, entry_price=pos.price_open)
        except PositionNotFoundException:
            level["closed"] = True
        except Exception as e:
            logger.error(f"Multi-TP partial close failed for ticket={ticket} level={level['label']}: {e}")

    if all(l["closed"] for l in config["levels"]):
        _multi_tp_positions.pop(ticket, None)


def get_active_trails() -> Dict[str, Any]:
    status = []
    for ticket, config in _active_trails.items():
        status.append({"ticket": ticket, "symbol": config.get("symbol"),
                       "distance_type": "usd" if config.get("usd_distance") is not None else "pips",
                       "usd_distance": config.get("usd_distance"), "pips_distance": config.get("pips_distance"),
                       "break_even_enabled": config.get("break_even_enabled", False),
                       "last_sl": config.get("last_sl"),
                       "age_seconds": round(time.time() - config.get("created_at", time.time()), 1)})
    return {"success": True, "active_trails": status, "count": len(status), "stats": _trail_stats}


def get_trail_stats() -> Dict[str, Any]:
    return {"total_updates": _trail_stats["total_updates"], "breakeven_applied": _trail_stats["breakeven_applied"],
            "trailing_updates": _trail_stats["trailing_updates"], "last_update_time": _trail_stats["last_update_time"],
            "active_trails": len(_active_trails)}


# =====================================================
# POSITION MANAGEMENT
# =====================================================
def close_position(ticket: int, deviation: int = 20) -> Dict[str, Any]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        raise PositionNotFoundException(ticket)
    position = position[0]
    symbol = position.symbol
    volume = position.volume
    
    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask
    
    close_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": deviation,
        "magic": position.magic,
        "comment": "Closed by API",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }
    
    result = mt5.order_send(close_request)
    
    if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = getattr(result, "retcode", None) if result else None
        raise ClosePositionFailedException(ticket, retcode or -1)
    
    # Send webhook for closure
    if ticket in _active_trails:
        config = _active_trails[ticket]
        if _trailing_webhook_enabled:
            send_trailing_webhook(
                ticket=ticket,
                symbol=config.get("symbol", symbol),
                action="CLOSED",
                sl_price=config.get("last_sl", 0),
                profit_pips=0,
                step_pips=config.get("step_pips", 5)
            )
        del _active_trails[ticket]

    _clear_break_even_status(ticket)
    _multi_tp_positions.pop(ticket, None)

    time.sleep(0.5)
    
    verify_position = mt5.positions_get(ticket=ticket)
    if verify_position:
        logger.warning(f"Position {ticket} still open after close")
    
    logger.info(f"Position {ticket} closed. Profit: ${position.profit:.2f}")
    
    force_history_sync()
    
    return {
        "success": True,
        "ticket": ticket,
        "symbol": symbol,
        "profit": position.profit,
        "close_price": price,
        "volume": volume
    }


def close_all_positions(symbol: Optional[str] = None, deviation: int = 20) -> Dict[str, Any]:
    positions = get_open_positions(symbol)
    if not positions:
        return {"success": True, "closed_count": 0, "message": "No positions to close"}
    
    results = []
    total_profit = 0
    errors = []
    
    for pos in positions:
        ticket = pos.get("ticket")
        try:
            result = close_position(ticket, deviation)
            results.append(result)
            total_profit += result.get("profit", 0)
        except TradingException as e:
            errors.append({"ticket": ticket, "error_code": e.error_code, "error_message": e.message})
    
    success_count = len(results)
    closed_tickets = [r.get("ticket") for r in results]
    for ticket in list(_active_trails.keys()):
        if ticket not in closed_tickets:
            del _active_trails[ticket]
    for ticket in closed_tickets:
        _clear_break_even_status(ticket)
        _multi_tp_positions.pop(ticket, None)
    
    return {"success": success_count > 0, "closed_count": success_count, "failed_count": len(errors),
            "total_profit": total_profit, "results": results, "errors": errors if errors else None}


def modify_stop_loss(ticket: int, new_sl_price: float) -> Dict[str, Any]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        raise PositionNotFoundException(ticket)
    position = position[0]
    old_sl = position.sl
    
    request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": new_sl_price, "tp": position.tp}
    result = mt5.order_send(request)
    
    if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = getattr(result, "retcode", None) if result else None
        raise ModifySLFailedException(ticket, retcode or -1)
    
    logger.info(f"Stop loss updated for {ticket}: {old_sl} -> {new_sl_price}")
    return {"success": True, "ticket": ticket, "new_sl": new_sl_price, "old_sl": old_sl}


def modify_take_profit(ticket: int, new_tp_price: float) -> Dict[str, Any]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        raise PositionNotFoundException(ticket)
    position = position[0]
    old_tp = position.tp
    
    request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": position.sl, "tp": new_tp_price}
    result = mt5.order_send(request)
    
    if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = getattr(result, "retcode", None) if result else None
        raise TradingException(ErrorCode.MODIFY_TP_FAILED, f"Failed to modify take profit for position {ticket}",
                               {"ticket": ticket, "retcode": retcode})
    
    logger.info(f"Take profit updated for {ticket}: {old_tp} -> {new_tp_price}")
    return {"success": True, "ticket": ticket, "new_tp": new_tp_price, "old_tp": old_tp}


def partial_close_position(ticket: int, volume_to_close: float, deviation: int = 20) -> Dict[str, Any]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        raise PositionNotFoundException(ticket)
    position = position[0]
    
    if volume_to_close >= position.volume:
        raise TradingException(ErrorCode.INVALID_VOLUME,
                               f"Volume to close ({volume_to_close}) must be less than position volume ({position.volume})",
                               {"ticket": ticket, "requested_volume": volume_to_close, "position_volume": position.volume})
    
    symbol = position.symbol
    
    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask
    
    close_request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume_to_close, "type": order_type,
                     "position": ticket, "price": price, "deviation": deviation, "magic": position.magic,
                     "comment": f"Partial close {volume_to_close}", "type_time": mt5.ORDER_TIME_GTC,
                     "type_filling": mt5.ORDER_FILLING_IOC}
    result = mt5.order_send(close_request)
    
    if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = getattr(result, "retcode", None) if result else None
        raise TradingException(ErrorCode.PARTIAL_CLOSE_FAILED, f"Partial close failed for position {ticket}",
                               {"ticket": ticket, "retcode": retcode})
    
    logger.info(f"Partially closed {volume_to_close} of position {ticket}")
    return {"success": True, "ticket": ticket, "closed_volume": volume_to_close, "remaining_volume": position.volume - volume_to_close}


def get_position_details(ticket: int) -> Optional[Dict[str, Any]]:
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return None
    return safe_dict(position[0])


# =====================================================
# EXECUTE TRADE - WITH TRAILING STOP WEBHOOK
# =====================================================

def volume_for_kept_stop(risk_per_lot_usd: float, target_risk_usd: float, margin_first_lot: float,
                         volume_min: float, volume_step: float, volume_max: float,
                         cap_at_margin_lot: bool = True):
    """(volume, risk at the stop) when the caller's stop is kept.

    The largest broker-valid volume whose loss at the stop fits the budget
    (core/market_stop.lot_for_risk), never above the margin-first lot when
    cap_at_margin_lot -- so a strategy setup's lot starts from the $200 trade
    size and only shrinks. At a very tight stop the budget would allow a
    bigger lot than $200 buys; the cap keeps the trade size. The caller
    refuses the order when even the broker minimum risks too much.
    """
    from core.market_stop import lot_for_risk

    volume = lot_for_risk(risk_per_lot_usd, target_risk_usd, volume_min, volume_step, volume_max)
    if cap_at_margin_lot and margin_first_lot and margin_first_lot > 0:
        volume = max(volume_min, min(volume, margin_first_lot))
    return round(volume, 2), volume * risk_per_lot_usd


def execute_trade(
    symbol: str, 
    order_type: str, 
    strategy_magic: int, 
    fixed_trade_size_usd: float, 
    risk_per_trade: float,
    max_spread: float, 
    trade_deviation: int = 20, 
    # DATA-COLLECTION MODE: repeated entries on the same symbol are allowed
    # and concurrency is effectively unlimited. These are the DEFAULTS -- the
    # monitor still passes its own values explicitly; raising them here means
    # a caller that omits the argument is not silently capped at 1 per symbol.
    # Finite sentinels rather than 0/None because both checks below are `>=`
    # comparisons and core/portfolio_risk_service.py rejects <= 0.
    max_trades_per_symbol: int = 100000,
    max_simultaneous_trades: int = 100000, 
    min_stop_pips_override: Optional[float] = None, 
    comment: str = "AI Trade", 
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,

    # ============================================================
    # OPTIONAL TP2 / TP3 - MT5 only supports one native TP per order,
    # so when these are provided the position is split into partial
    # closes managed by the trailing/position monitor instead.
    # ============================================================
    take_profit_2_price: Optional[float] = None,
    take_profit_3_price: Optional[float] = None,

    # ============================================================
    # SIMPLIFIED TRAILING STOP - ONLY 2 PARAMS
    # ============================================================
    enable_break_even: bool = False,
    break_even_pips_distance: Optional[float] = None,
    break_even_usd_distance: Optional[float] = None,
    enable_trailing_stop: bool = False,
    trailing_pips: Optional[float] = None,
    trailing_usd_distance: Optional[float] = None,
    keep_stop: bool = False,
) -> Dict[str, Any]:
    """
    Execute a trade - AUTO-CALCULATES SL from risk_per_trade if not provided.
    TP is OPTIONAL - only set if provided by caller.

    keep_stop: the caller's stop is a strategy's own invalidation level (a
    strategy setup, core/strategy_setups.py): it is kept, and the lot is the
    margin-first lot shrunk until the loss at that stop fits the budget --
    never larger than the margin-first lot. Refused when even the broker's
    minimum volume would lose more than the budget.
    """
    
    # ============================================================
    # VALIDATE INPUT PARAMETERS
    # ============================================================
    
    if not symbol or not isinstance(symbol, str):
        return {"success": False, "error": "Invalid symbol parameter"}
    
    if order_type.upper() not in ["BUY", "SELL"]:
        return {"success": False, "error": f"Invalid order_type: {order_type}"}
    
    if fixed_trade_size_usd <= 0:
        return {"success": False, "error": f"Invalid fixed_trade_size_usd: {fixed_trade_size_usd}"}
    
    if risk_per_trade <= 0 or risk_per_trade > 1:
        return {"success": False, "error": f"Invalid risk_per_trade: {risk_per_trade}"}
    
    symbol = symbol.upper()
    order_type = order_type.upper()

    if enable_break_even:
        if (break_even_pips_distance is None) == (break_even_usd_distance is None):
            return {"success": False, "error": "Break-even requires exactly one of break_even_pips_distance or break_even_usd_distance"}
        if break_even_pips_distance is not None and break_even_pips_distance <= 0:
            return {"success": False, "error": "break_even_pips_distance must be > 0"}
        if break_even_usd_distance is not None and break_even_usd_distance <= 0:
            return {"success": False, "error": "break_even_usd_distance must be > 0"}

    if enable_trailing_stop:
        if (trailing_pips is None) == (trailing_usd_distance is None):
            return {"success": False, "error": "Trailing stop requires exactly one of trailing_pips or trailing_usd_distance"}
        if trailing_pips is not None and trailing_pips <= 0:
            return {"success": False, "error": "trailing_pips must be > 0"}
        if trailing_usd_distance is not None and trailing_usd_distance <= 0:
            return {"success": False, "error": "trailing_usd_distance must be > 0"}
    
    # ============================================================
    # CHECK MT5 CONNECTION
    # ============================================================
    
    try:
        if not mt5.terminal_info():
            return {"success": False, "error": "MT5 terminal not connected"}
    except Exception as e:
        return {"success": False, "error": f"MT5 connection error: {str(e)}"}
    
    # ============================================================
    # ACCOUNT INFO
    # ============================================================
    
    try:
        account = mt5.account_info()
        if not account:
            return {"success": False, "error": "Failed to get account information"}
        leverage = account.leverage if account.leverage else 200
    except Exception as e:
        return {"success": False, "error": f"Account info error: {str(e)}"}
    
    # ============================================================
    # CHECK TRADE LIMITS
    # ============================================================
    
    try:
        total_positions = get_open_positions_count()
        if total_positions >= max_simultaneous_trades:
            return {
                "success": False,
                "error": f"Max trades reached: {total_positions}/{max_simultaneous_trades}"
            }
        
        symbol_positions = get_open_positions_count(symbol)
        if symbol_positions >= max_trades_per_symbol:
            return {
                "success": False,
                "error": f"Max trades per symbol reached: {symbol_positions}/{max_trades_per_symbol}"
            }
    except Exception as e:
        pass
    
    # ============================================================
    # VALIDATE SYMBOL
    # ============================================================
    
    try:
        info = mt5.symbol_info(symbol)
        if not info:
            return {"success": False, "error": f"Symbol '{symbol}' not found"}
        
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                return {"success": False, "error": f"Symbol '{symbol}' could not be selected"}
            info = mt5.symbol_info(symbol)
            if not info:
                return {"success": False, "error": f"Symbol '{symbol}' not available"}
    except Exception as e:
        return {"success": False, "error": f"Symbol validation error: {str(e)}"}
    
    # ============================================================
    # GET MARKET DATA
    # ============================================================
    
    try:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"No tick data for {symbol}"}
        
        if tick.ask <= 0 or tick.bid <= 0:
            return {"success": False, "error": f"Invalid prices: ask={tick.ask}, bid={tick.bid}"}
        
        if order_type == "BUY":
            price = tick.ask
            mt5_order_type = mt5.ORDER_TYPE_BUY
            direction = "BUY"
        else:
            price = tick.bid
            mt5_order_type = mt5.ORDER_TYPE_SELL
            direction = "SELL"
            
    except Exception as e:
        return {"success": False, "error": f"Market data error: {str(e)}"}
    
    # ============================================================
    # CHECK SPREAD
    # ============================================================
    
    try:
        spread_points = (tick.ask - tick.bid) / info.point if info.point > 0 else 0
        if info.digits in [3, 5]:
            spread_pips = spread_points / 10
        else:
            spread_pips = spread_points
        
        if spread_pips > max_spread:
            return {
                "success": False,
                "error": f"Spread too high: {spread_pips:.1f}p > {max_spread}p"
            }
    except Exception as e:
        pass
    
    # ============================================================
    # CALCULATE LOT SIZE (ALWAYS DOES SL CALCULATION)
    # ============================================================
    
    # same ceiling as the analysis: the order may not risk more than the budget
    if isinstance(risk_per_trade, (int, float)) and risk_per_trade > MAX_RISK_PER_TRADE:
        logger.warning(f"[RISK] {symbol}: order asked for {risk_per_trade:.1%} -- capped at "
                       f"{MAX_RISK_PER_TRADE:.1%} (${fixed_trade_size_usd * MAX_RISK_PER_TRADE:.2f})")
        risk_per_trade = MAX_RISK_PER_TRADE

    try:
        lot_result = calculate_lot(
            symbol=symbol, 
            fixed_trade_size_usd=fixed_trade_size_usd, 
            risk_per_trade=risk_per_trade,
            leverage=leverage,
            order_type=order_type,
            min_stop_pips_override=min_stop_pips_override
        )
        
        if not lot_result.get("success", True):
            return {"success": False, "error": lot_result.get("error", "Lot calculation failed")}
        
        lot_data = lot_result.get("data", lot_result)
        
        if "lot" not in lot_data:
            return {
                "success": False,
                "error": f"Lot calculation error: 'lot' key missing from result: {lot_result}"
            }
        
        total_volume = round(lot_data["lot"], 2)
        
        if total_volume <= 0:
            return {"success": False, "error": f"Invalid lot size: {total_volume}"}
        
        if total_volume < info.volume_min:
            total_volume = info.volume_min
        if total_volume > info.volume_max:
            total_volume = info.volume_max
            
    except Exception as e:
        return {"success": False, "error": f"Lot calculation error: {str(e)}"}
    
    # ============================================================
    # ✅ SL: AUTO-CALCULATE FROM risk_per_trade IF NOT PROVIDED
    # ============================================================
    
    sl_price = None
    
    # ✅ If SL provided, use it (trust the caller)
    if stop_loss_price is not None and stop_loss_price > 0:
        sl_price = round(stop_loss_price, info.digits)
        logger.info(f"Using provided SL: {sl_price}")
    
    # ✅ If SL NOT provided, auto-calculate from lot_data
    if sl_price is None:
        # Use the SL from calculate_lot
        if "stop_loss_price" in lot_data and lot_data["stop_loss_price"]:
            sl_price = round(lot_data["stop_loss_price"], info.digits)
            logger.info(f"Auto-calculated SL from risk_per_trade: {sl_price} (risk={risk_per_trade*100}%)")
        else:
            # Fallback: calculate SL from pips
            sl_pips = lot_data.get("stop_loss_pips", 5.0)
            pip_size, _, _ = get_pip_info(info)
            
            if order_type == "BUY":
                sl_price = round(price - (sl_pips * pip_size), info.digits)
            else:
                sl_price = round(price + (sl_pips * pip_size), info.digits)
            
            logger.info(f"Fallback SL: {sl_price} ({sl_pips:.1f} pips)")
    
    # ============================================================
    # RISK RECONCILIATION -- MARGIN-FIRST
    # ============================================================
    # The sizing model is margin-first, by decision: calculate_lot_proper()
    # takes the largest lot that fits the $200 margin budget, then DERIVES the
    # stop distance that makes that lot risk exactly target_risk. Lot and stop
    # are two halves of one answer.
    #
    # The block above then adopted a caller-supplied `stop_loss_price`
    # verbatim ("trust the caller") while leaving the lot alone -- so the order
    # went out with a lot sized for one stop and a stop at another distance.
    # Measured cost: AUDCHF sized against a 1.2-pip stop, sent with a 10-pip
    # stop, closed at -$40.61 and -$33.96 against a $4.00 budget.
    #
    # The fix keeps the LOT (that is the $200 the operator asked for) and pulls
    # the STOP back to the distance that budget implies -- never tighter than
    # 3x the current spread, because a stop inside the spread is closed by the
    # bid/ask bounce rather than by the market.
    #
    # Shrinking the lot is the last resort only, for the case where even a
    # 3x-spread stop cannot fit the budget.
    # MARKET STOP (core/market_stop.py): the caller's stop is the market's
    # statement of where the trade is wrong, so it is kept and the LOT is
    # sized to the dollar risk. Refused, not silently over-risked, when even
    # the broker's minimum volume loses more than the budget at that stop.
    _market_sized = False
    if (USE_MARKET_STOP or keep_stop) and stop_loss_price is not None and stop_loss_price > 0 \
            and sl_price and total_volume > 0:
        from core.market_stop import lot_for_risk, MAX_RISK_OVERSHOOT
        _target_risk = fixed_trade_size_usd * risk_per_trade
        _mt5_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
        _per_lot = mt5.order_calc_profit(_mt5_type, symbol, 1.0, price, sl_price)
        if _per_lot is not None and _per_lot != 0:
            _per_lot = abs(float(_per_lot))
            total_volume, _risk = volume_for_kept_stop(
                _per_lot, _target_risk, total_volume, float(info.volume_min),
                float(info.volume_step or 0.01), float(info.volume_max),
                # the operator's sizing: the $200 margin-first lot is the ceiling
                cap_at_margin_lot=keep_stop and not USE_MARKET_STOP)
            if _risk > _target_risk * MAX_RISK_OVERSHOOT:
                return {"success": False,
                        "error": f"Stop {sl_price} risks ${_risk:.2f} at the minimum volume {total_volume} "
                                 f"against a ${_target_risk:.2f} budget"}
            lot_data["lot"] = total_volume
            lot_data["actual_risk"] = round(_risk, 2)
            _market_sized = True
            logger.info(f"[RISK] {symbol}: {'strategy setup' if keep_stop else 'market'} stop {sl_price} kept; "
                        f"lot {total_volume} risks ${_risk:.2f} (budget ${_target_risk:.2f})")

    if sl_price and sl_price > 0 and total_volume > 0 and not _market_sized:
        try:
            _target_risk = fixed_trade_size_usd * risk_per_trade
            _mt5_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
            _pip_size, _, _ = get_pip_info(info)
            _tick = mt5.symbol_info_tick(symbol)

            def _risk_of(lot, stop):
                _v = mt5.order_calc_profit(_mt5_type, symbol, lot, price, stop)
                return abs(_v) if _v is not None else None

            _risk_now = _risk_of(total_volume, sl_price)

            if _risk_now and _risk_now > _target_risk * 1.05:
                # Value of one pip at THIS lot, measured rather than derived.
                _per_pip = _risk_of(total_volume, price - _pip_size) if order_type == "BUY"                     else _risk_of(total_volume, price + _pip_size)

                if _per_pip and _per_pip > 0:
                    _needed_pips = _target_risk / _per_pip
                    _spread_pips = ((_tick.ask - _tick.bid) / _pip_size) if _tick else 0.0
                    _floor_pips = max(_spread_pips * 3.0, 1.0)
                    _final_pips = max(_needed_pips, _floor_pips)

                    _new_sl = (price - _final_pips * _pip_size) if order_type == "BUY"                         else (price + _final_pips * _pip_size)
                    _new_sl = round(_new_sl, info.digits)
                    _risk_after = _risk_of(total_volume, _new_sl)

                    logger.warning(
                        f"[RISK] {symbol}: stop {sl_price} implied ${_risk_now:.2f} at lot "
                        f"{total_volume} vs ${_target_risk:.2f} target -- stop moved to "
                        f"{_new_sl} ({_final_pips:.1f}p, floor {_floor_pips:.1f}p), risk now "
                        f"${(_risk_after or 0):.2f}. Lot held to keep margin on target.")
                    sl_price = _new_sl

                    # Last resort: the spread floor alone still blows the
                    # budget, so the lot has to give.
                    # 3x, not 1.5x. Margin-first is a deliberate choice: the
                    # operator wants the $200 position, and accepts that a
                    # 3x-spread stop puts risk somewhere in the $3-$11 band
                    # depending on the instrument's spread at the time
                    # (measured: EURUSD $4.08, EURCAD $4.43, XAUUSD $3.96,
                    # AUDCHF $8.13, NZDUSD $10.20, AUDNZD $11.49).
                    #
                    # Clamping at 1.5x would shrink the lot on half of those
                    # and quietly undo the decision. 3x still catches the case
                    # this guard exists for -- a 10-pip stop on a $200 AUDCHF
                    # lot risks $67.72, and that is what closed at -$40.61.
                    if _risk_after and _risk_after > _target_risk * 3.0:
                        _step = info.volume_step or 0.01
                        _scaled = math.floor((total_volume * (_target_risk / _risk_after)) / _step) * _step
                        _scaled = round(max(info.volume_min, _scaled), 2)
                        if _scaled < total_volume:
                            logger.warning(
                                f"[RISK] {symbol}: even a {_floor_pips:.1f}p stop risks "
                                f"${_risk_after:.2f} -- lot {total_volume} -> {_scaled}")
                            total_volume = _scaled
                            lot_data["lot"] = _scaled

            # Record what the position ACTUALLY risks, measured against the
            # stop being sent -- not what the sizing step hoped for.
            _final_risk = _risk_of(total_volume, sl_price)
            if _final_risk is not None:
                lot_data["actual_risk"] = round(_final_risk, 2)
        except Exception as _exc:
            logger.error(f"[RISK] {symbol}: could not verify risk ({_exc}) -- "
                         f"leaving lot {total_volume} and stop {sl_price} unchanged")

    # ============================================================
    # ✅ TP: ONLY SET IF PROVIDED (OPTIONAL)
    # ============================================================
    
    tp_price = None
    
    if take_profit_price is not None and take_profit_price > 0:
        tp_price = round(take_profit_price, info.digits)
        logger.info(f"Using provided TP: {tp_price}")
    else:
        logger.info("No TP provided - trade will be placed without take profit")

    # ============================================================
    # ✅ TP2 / TP3 (OPTIONAL) - MT5 only supports a single native TP,
    # so with multiple TPs we split the position across levels and
    # manage the partial closes via the position monitor instead of
    # relying on MT5's native TP for a full close at TP1.
    # ============================================================
    tp2_price = round(take_profit_2_price, info.digits) if take_profit_2_price and take_profit_2_price > 0 else None
    tp3_price = round(take_profit_3_price, info.digits) if take_profit_3_price and take_profit_3_price > 0 else None

    if tp3_price is not None and tp2_price is None:
        return {"success": False, "error": "take_profit_3_price requires take_profit_2_price to also be set"}
    if (tp2_price is not None or tp3_price is not None) and tp_price is None:
        return {"success": False, "error": "TP2/TP3 require take_profit_price (TP1) to also be set"}

    tp_levels = []  # [(label, price, percent)]
    use_native_tp = True
    if tp2_price is not None and tp3_price is not None:
        tp_levels = [("TP1", tp_price, 33.0), ("TP2", tp2_price, 33.0), ("TP3", tp3_price, 34.0)]
        use_native_tp = False
    elif tp2_price is not None:
        tp_levels = [("TP1", tp_price, 70.0), ("TP2", tp2_price, 30.0)]
        use_native_tp = False
    elif tp_price is not None:
        tp_levels = [("TP1", tp_price, 100.0)]
        use_native_tp = True

    # ============================================================
    # ✅ VALIDATE SL - MUST EXIST (MT5 REQUIRES SL)
    # ============================================================
    
    if sl_price is None or sl_price <= 0:
        return {
            "success": False,
            "error": "Stop loss is required and could not be auto-calculated from risk_per_trade"
        }
    
    # ============================================================
    # BUILD TRADE REQUEST
    # ============================================================
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": total_volume,
        "type": mt5_order_type,
        "price": price,
        "deviation": trade_deviation,
        "magic": strategy_magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "sl": sl_price  # SL IS ALWAYS REQUIRED
    }
    
    # ✅ Only add native TP if a single TP level is in play; with TP2/TP3
    # present, TP is managed via partial closes instead (see below).
    if tp_price is not None and tp_price > 0 and use_native_tp:
        request["tp"] = tp_price
    
    response = {
        "success": False,
        "ticket": None,
        "symbol": symbol,
        "order_type": direction,
        "volume": total_volume,
        "price": price,
        "stop_loss": sl_price,
        "take_profit": tp_price,  # May be None if not provided
        "take_profit_2": tp2_price,
        "take_profit_3": tp3_price,
        "take_profit_split": (
            [{"label": l, "price": p, "percent": pct} for l, p, pct in tp_levels]
            if not use_native_tp else None
        ),
        "actual_margin": round(lot_data.get("margin_required", 0), 2),
        "actual_risk_usd": round(lot_data.get("actual_risk", 0), 2),
        "risk_percent_used": round(risk_per_trade * 100, 1),
        # The spread of the SAME quote that priced this order (`tick`, read
        # above). The trade writer stores this as spread_at_entry; it used to
        # look for this key, find nothing, and store None on every trade.
        "spread_pips": _order_spread_pips(tick, info),
        "bid_at_entry": getattr(tick, "bid", None),
        "ask_at_entry": getattr(tick, "ask", None),
        "magic": strategy_magic,
        "comment": comment,
        "timestamp": datetime.now().isoformat(),
        "break_even": {
            "enabled": enable_break_even,
            "pips_distance": break_even_pips_distance if enable_break_even else None,
            "usd_distance": break_even_usd_distance if enable_break_even else None
        },
        "trailing_stop": {
            "enabled": enable_trailing_stop,
            "pips_distance": trailing_pips if enable_trailing_stop else None,
            "usd_distance": trailing_usd_distance if enable_trailing_stop else None
        },
        "note": ("TP is optional - only set if provided in request. When take_profit_2_price/"
                  "take_profit_3_price are also provided, MT5's native TP is not used; instead "
                  "the position is split and partially closed at each level by the monitor "
                  "(TP1+TP2: 70/30, TP1+TP2+TP3: 33/33/34).")
    }
    
    # ============================================================
    # EXECUTE WITH RETRY
    # ============================================================
    
    max_retries = 3
    retry_count = 0
    result = None
    
    while retry_count < max_retries:
        try:
            logger.info(f"=== EXECUTING TRADE (Attempt {retry_count + 1}) ===")
            logger.info(f"Symbol: {symbol} | Direction: {direction}")
            logger.info(f"Price: {price} | Volume: {total_volume}")
            logger.info(f"SL: {sl_price} | TP: {tp_price if tp_price else 'NOT SET'}")
            if enable_trailing_stop:
                logger.info(f"Trailing: ON (step={trailing_pips}p)")
            
            result = mt5.order_send(request)
            
            if not result:
                error = mt5.last_error()
                logger.error(f"MT5 order_send returned None. Error: {error}")
                retry_count += 1
                time.sleep(0.5)
                continue
            
            if result.retcode in [10008, 10009, 10010]:
                break
            
            if result.retcode in [10004, 10006]:
                logger.warning(f"Retcode {result.retcode}, retrying...")
                tick = mt5.symbol_info_tick(symbol)
                if direction == "BUY":
                    request["price"] = tick.ask
                else:
                    request["price"] = tick.bid
                retry_count += 1
                time.sleep(0.3)
                continue
            
            break
            
        except Exception as e:
            logger.error(f"Order send exception: {e}")
            retry_count += 1
            time.sleep(0.5)
            continue
    
    if not result:
        return {
            "success": False,
            "error": "Failed to execute trade: No result from MT5",
            **response
        }
    
    if result.retcode not in [10008, 10009, 10010]:
        error_msg = result.comment if result.comment else "Unknown error"
        return {
            "success": False,
            "error": error_msg,
            "retcode": result.retcode,
            **response
        }
    
    # ============================================================
    # TRADE SUCCESSFUL
    # ============================================================
    
    ticket = result.order
    response["success"] = True
    response["ticket"] = ticket

    # AI_MarketReplay: the trade now has a real ticket, so the pre-trade
    # events buffered during the entry decision can be re-keyed onto it and
    # written. This is the ONLY point at which they reach Firebase, and it is
    # reached only after an order actually filled -- a candidate that never
    # became a trade has no document to attach to, and persisting one anyway
    # would put fictional trades in the historical record.
    #
    # OFF unless AIREPLAY_RECORD_LIVE is set. Guarded here as well as inside,
    # because this line sits between a filled order and its bookkeeping.
    try:
        from ai.aireplay.live_recording import bind_execution

        bind_execution(symbol, ticket)
    except Exception:
        pass

    # Calculate probability if TP exists
    if sl_price and tp_price and tp_price > 0:
        try:
            probability = calculate_probability_of_hit(symbol, price, sl_price, tp_price, direction)
            response["probability_of_hit_percent"] = round(probability * 100, 1)
        except Exception:
            pass
    else:
        response["probability_of_hit_percent"] = None
        response["note"] = "TP not set - probability calculation skipped"
    
    # ============================================================
    # APPLY TRAILING STOP (if enabled)
    # ============================================================
    
    if enable_break_even or enable_trailing_stop:
        try:
            _active_trails[ticket] = {
                "symbol": symbol,
                "break_even_enabled": enable_break_even,
                "break_even_pips_distance": break_even_pips_distance,
                "break_even_usd_distance": break_even_usd_distance,
                "trailing_enabled": enable_trailing_stop,
                "pips_distance": trailing_pips,
                "usd_distance": trailing_usd_distance,
                "step_pips": trailing_pips,
                "last_sl": sl_price,
                "created_at": time.time()
            }
            if not _trail_monitor_running:
                start_trailing_monitor()
            if enable_trailing_stop:
                distance_text = f"${trailing_usd_distance:.2f}" if trailing_usd_distance is not None else f"{trailing_pips:g} pips"
                logger.info(f"Trailing stop enabled for {symbol} ticket={ticket} distance={distance_text}")
            if enable_break_even:
                be_text = f"${break_even_usd_distance:.2f}" if break_even_usd_distance is not None else f"{break_even_pips_distance:g} pips"
                logger.info(f"Break-even enabled for {symbol} ticket={ticket} trigger={be_text}")
                _record_break_even_status(
                    ticket, symbol, False,
                    "usd_distance" if break_even_usd_distance is not None else "pips_distance",
                    break_even_usd_distance if break_even_usd_distance is not None else break_even_pips_distance
                )
        except Exception as e:
            logger.warning(f"Failed to register position management: {e}")
            response["management_error"] = str(e)

    # ============================================================
    # REGISTER TP2/TP3 SPLIT (if enabled)
    # ============================================================

    if not use_native_tp and tp_levels:
        try:
            _multi_tp_positions[ticket] = {
                "symbol": symbol,
                "original_volume": total_volume,
                "levels": [{"label": l, "price": p, "percent": pct, "closed": False} for l, p, pct in tp_levels],
                "created_at": time.time()
            }
            if not _trail_monitor_running:
                start_trailing_monitor()
            logger.info(f"Multi-TP split registered for {symbol} ticket={ticket}: "
                        f"{[(l, p) for l, p, _ in tp_levels]}")
        except Exception as e:
            logger.warning(f"Failed to register multi-TP split: {e}")
            response["multi_tp_error"] = str(e)

    logger.info(f"=== TRADE EXECUTED SUCCESSFULLY ===")
    logger.info(f"Ticket: {ticket} | Symbol: {symbol} | Direction: {direction}")
    logger.info(f"Entry: {price} | Volume: {total_volume} | SL: {sl_price} | TP: {tp_price if tp_price else 'NOT SET'}")
    
    return response

# =====================================================
# ACCOUNT INFO
# =====================================================
def get_account_info() -> Dict[str, Any]:
    account = mt5.account_info()
    if not account:
        raise TradingException(ErrorCode.ACCOUNT_INFO_FAILED, "Failed to get account information",
                               {"mt5_connected": mt5.terminal_info() is not None})
    return {"success": True, "login": account.login, "balance": account.balance, "equity": account.equity,
            "margin": account.margin, "free_margin": account.margin_free, "margin_level": account.margin_level,
            "currency": account.currency, "profit": account.profit, "leverage": account.leverage}


# =====================================================
# SYMBOL INFO
# =====================================================
def get_symbol_info(symbol_name: str) -> Dict[str, Any]:
    try:
        info = mt5.symbol_info(symbol_name)
        if info is None:
            return {"success": False, "error": f"Symbol {symbol_name} not found"}
        
        tick = mt5.symbol_info_tick(symbol_name)
        
        standard_lot = 1.0
        margin_for_1_lot = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, symbol_name, standard_lot, tick.ask if tick else info.trade_contract_size
        )
        pip_value_for_1_lot = get_pip_value(symbol_name, standard_lot)
        
        micro_lot = 0.01
        margin_for_micro_lot = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, symbol_name, micro_lot, tick.ask if tick else info.trade_contract_size
        )
        pip_value_for_micro_lot = get_pip_value(symbol_name, micro_lot)
        
        min_volume = info.volume_min
        margin_for_min_lot = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, symbol_name, min_volume, tick.ask if tick else info.trade_contract_size
        ) if min_volume > 0 else 0
        
        current_spread_pips = 0
        if tick and info:
            # ✅ FIXED 2026-09-16: was divided by info.point, which is a POINT
            # not a pip -- 10x too large on 5-digit symbols. A live snapshot
            # reported 5.3 "pips" of spread beside a real 0.1.
            _pip_size, _, _ = get_pip_info(info)
            current_spread_pips = (tick.ask - tick.bid) / (_pip_size or info.point)
        
        trend_strength = calculate_trend_strength(symbol_name)
        volatility = get_atr_value(symbol_name) / (tick.ask if tick else 1) * 100 if tick else 0
        
        result = {
            "success": True,
            "symbol": info.name,
            "description": info.description,
            "path": info.path,
            "visible": info.visible,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
            "currency_margin": info.currency_margin,
            "digits": info.digits,
            "point": info.point,
            "contract_size": info.trade_contract_size,
            "tick_size": info.trade_tick_size,
            "tick_value": info.trade_tick_value,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "stops_level": info.trade_stops_level,
            "freeze_level": info.trade_freeze_level,
            "swap_long": info.swap_long,
            "swap_short": info.swap_short,
            "swap_rollover3days": info.swap_rollover3days,
            "margin_required_1_lot": margin_for_1_lot,
            "margin_required_micro_lot": margin_for_micro_lot,
            "margin_required_min_lot": margin_for_min_lot,
            "pip_value_1_lot": pip_value_for_1_lot,
            "pip_value_micro_lot": pip_value_for_micro_lot,
            "market_conditions": {
                "current_spread_pips": round(current_spread_pips, 1),
                "trend_strength": round(trend_strength, 3),
                "volatility_percent": round(volatility, 2),
                "average_true_range": round(get_atr_value(symbol_name), info.digits)
            },
            "time": info.time
        }
        
        if tick:
            result["bid"] = tick.bid
            result["ask"] = tick.ask
            result["last"] = tick.last
            result["volume"] = tick.volume
            result["spread_points"] = (tick.ask - tick.bid) / info.point
            
            if info.digits in [3, 5]:
                result["spread_pips"] = (tick.ask - tick.bid) / (info.point * 10)
            else:
                result["spread_pips"] = (tick.ask - tick.bid) / info.point
            
            result["tick_time"] = tick.time
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get symbol info for {symbol_name}: {e}")
        return {"success": False, "error": str(e)}

    # =====================================================
# SIMPLIFIED TRAILING STOP - WITH WEBHOOK
# =====================================================

def get_atr_value(symbol: str, period: int = 14) -> float:
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 1)
        if rates is None or len(rates) < period:
            return 0
        atr_sum = 0
        for i in range(1, period + 1):
            high = rates[i][2]
            low = rates[i][3]
            prev_close = rates[i-1][4]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            atr_sum += tr
        return atr_sum / period
    except Exception as e:
        logger.error(f"Failed to calculate ATR: {e}")
        return 0