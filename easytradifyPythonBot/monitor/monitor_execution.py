# monitor/monitor_execution.py
# ============================================================
# TRADE EXECUTION LOGIC - WITH FULL CONSOLE LOGGING
# FIXED: Proper ask/bid from ticks, not symbol_info
# ============================================================

# Console encoding, before anything logs. This module's log lines carry
# emoji; on a Windows cp1252 console writing one raises UnicodeEncodeError
# rather than printing a replacement character. That is not cosmetic -- the
# identical failure silently disabled the GNN for this entire project (the
# ai.ai_gnn import logs a brain emoji, the import raised, and a broad
# `except Exception` reported it as 'GNN initialization failed'), and it
# ended every replay run with a traceback after the work was finished.
# In a live monitor the same line would take the process down mid-session.
try:
    import core.console_safe  # noqa: F401
except Exception:
    pass

import logging
import time
import threading
import math
from typing import Dict, Any, Tuple, Optional
import MetaTrader5 as mt5
import traceback

from .monitor_models import TradeResult
from core.execution import execute_trade

logger = logging.getLogger(__name__)


class ExecutionManager:
    """Manages trade execution and validation."""
    
    def __init__(self, monitor):
        self.monitor = monitor
        self._state_lock = monitor._state_lock
        self.MAX_SIMULTANEOUS_TRADES = monitor.MAX_SIMULTANEOUS_TRADES
        self.MAX_TRADES_PER_SYMBOL = monitor.MAX_TRADES_PER_SYMBOL
        self.FIXED_TRADE_SIZE_USD = monitor.FIXED_TRADE_SIZE_USD
        self.RISK_PER_TRADE = monitor.RISK_PER_TRADE
        self.MAX_SPREAD = monitor.MAX_SPREAD
        self.STRATEGY_MAGIC = monitor.STRATEGY_MAGIC
        self.TRADE_DEVIATION = monitor.TRADE_DEVIATION
        
    def _get_account_leverage(self) -> int:
        """Get leverage from MT5 account."""
        try:
            account_info = mt5.account_info()
            if account_info:
                leverage = account_info.leverage
                logger.info(f"📊 Account leverage: {leverage}")
                return leverage
        except Exception as e:
            logger.warning(f"⚠️ Could not get account leverage: {e}")
        return 200  # Default fallback
    
    def _get_current_prices(self, symbol: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Get current ask, bid, and spread from tick data."""
        try:
            # Ensure symbol is selected
            mt5.symbol_select(symbol, True)
            time.sleep(0.05)
            
            # Get tick data (this is the current price)
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                ask = tick.ask
                bid = tick.bid
                spread = ask - bid if ask and bid else 0
                logger.debug(f"📊 {symbol} Tick: Ask={ask}, Bid={bid}, Spread={spread}")
                return ask, bid, spread
            
            # Fallback: try symbol_info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                ask = symbol_info.ask
                bid = symbol_info.bid
                spread = ask - bid if ask and bid else 0
                logger.debug(f"📊 {symbol} SymbolInfo: Ask={ask}, Bid={bid}, Spread={spread}")
                return ask, bid, spread
            
            logger.error(f"❌ {symbol}: Cannot get prices")
            return None, None, None
            
        except Exception as e:
            logger.error(f"❌ {symbol}: Error getting prices: {e}")
            return None, None, None
    
    def validate_trade_params(self, symbol: str, order_type: str, entry_price: float, 
                              stop_loss: float, take_profit: float) -> Tuple[bool, str]:
        """Validate trade parameters before execution."""
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return False, f"Symbol info not found: {symbol}"
        
        # Get current prices from tick
        ask, bid, spread = self._get_current_prices(symbol)
        if ask is None or bid is None:
            return False, f"Cannot get current prices for {symbol}"
        
        # Calculate pip size
        if "JPY" in symbol:
            pip_size = 0.01
        elif any(x in symbol for x in ["XAU", "GOLD"]):
            pip_size = 0.01 if symbol_info.digits == 2 else 0.1
        elif any(x in symbol for x in ["XAG", "SILVER"]):
            pip_size = 0.001 if symbol_info.digits == 3 else 0.01
        else:
            pip_size = 0.0001 if symbol_info.digits in [4, 5] else symbol_info.point
        
        min_sl_pips = 1
        
        if order_type == "BUY":
            sl_distance = (entry_price - stop_loss) / pip_size
            tp_distance = (take_profit - entry_price) / pip_size
            
            # BUY must use ASK price
            if entry_price > ask:
                logger.warning(f"⚠️ {symbol}: BUY entry {entry_price} > ask {ask}")
                return False, f"BUY price {entry_price} > ask {ask}"
            if entry_price < ask * 0.999:  # Allow small deviation
                logger.warning(f"⚠️ {symbol}: BUY entry {entry_price} significantly below ask {ask}")
        else:
            sl_distance = (stop_loss - entry_price) / pip_size
            tp_distance = (entry_price - take_profit) / pip_size
            
            # SELL must use BID price
            if entry_price < bid:
                logger.warning(f"⚠️ {symbol}: SELL entry {entry_price} < bid {bid}")
                return False, f"SELL price {entry_price} < bid {bid}"
            if entry_price > bid * 1.001:  # Allow small deviation
                logger.warning(f"⚠️ {symbol}: SELL entry {entry_price} significantly above bid {bid}")
        
        logger.info(f"📊 {symbol}: SL={sl_distance:.1f}p, TP={tp_distance:.1f}p, min={min_sl_pips}p")
        
        if sl_distance < min_sl_pips:
            return False, f"SL too tight: {sl_distance:.1f} pips (min {min_sl_pips})"
        if tp_distance < min_sl_pips:
            return False, f"TP too close: {tp_distance:.1f} pips (min {min_sl_pips})"
        
        logger.info(f"✅ {symbol}: Trade params validated")
        return True, "Valid"
    
    def _calculate_full_margin_lot(self, symbol: str, order_type: str) -> Tuple[float, float, float, float]:
        """
        Calculate lot that uses full $200 margin with exact risk.
        
        Returns:
            (lot, sl_pips, margin_required, actual_risk)
        """
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"❌ {symbol}: Symbol info not found")
            return 0, 0, 0, 0
        
        # Get current price from tick
        ask, bid, _ = self._get_current_prices(symbol)
        if ask is None or bid is None:
            logger.error(f"❌ {symbol}: Cannot get current prices")
            return 0, 0, 0, 0
        
        # Use the correct price for the order type
        if order_type.upper() == "BUY":
            current_price = ask
        else:
            current_price = bid
        
        if current_price <= 0:
            logger.error(f"❌ {symbol}: Invalid price: {current_price}")
            return 0, 0, 0, 0
        
        contract_size = float(symbol_info.trade_contract_size) if symbol_info.trade_contract_size else 100000
        
        # Calculate pip size
        pip_size, _, _ = self._get_pip_info(symbol_info)
        pip_value_1_lot = contract_size * pip_size
        
        # Target risk
        target_risk = self.FIXED_TRADE_SIZE_USD * self.RISK_PER_TRADE
        
        # Get leverage
        leverage = self._get_account_leverage()
        
        logger.info(f"📊 {symbol}: Price={current_price}, Contract={contract_size}, PipSize={pip_size}, PipValue={pip_value_1_lot}")
        logger.info(f"📊 {symbol}: Leverage={leverage}, Target Risk=${target_risk:.2f}")
        
        # Calculate lot that uses exactly $200 margin
        max_margin_lot = (self.FIXED_TRADE_SIZE_USD * leverage) / (current_price * contract_size)
        
        # Round to volume step
        volume_step = symbol_info.volume_step if symbol_info.volume_step else 0.01
        volume_min = symbol_info.volume_min if symbol_info.volume_min else 0.01
        volume_max = symbol_info.volume_max if symbol_info.volume_max else 100
        
        lot = math.floor(max_margin_lot / volume_step) * volume_step
        lot = max(volume_min, min(lot, volume_max))
        lot = round(lot, 2)
        
        # Calculate SL distance needed for exact risk
        if lot > 0 and pip_value_1_lot > 0:
            sl_pips = target_risk / (lot * pip_value_1_lot)
        else:
            sl_pips = 5.0
        
        # Round SL to 0.5 pip increments
        sl_pips = round(sl_pips * 2) / 2
        sl_pips = max(sl_pips, 1.0)
        
        # Calculate actual values
        margin_required = (lot * current_price * contract_size) / leverage
        actual_risk = lot * sl_pips * pip_value_1_lot
        
        logger.info(f"📊 Full margin calculation for {symbol}:")
        logger.info(f"   Lot: {lot:.2f} (Margin: ${margin_required:.2f})")
        logger.info(f"   SL: {sl_pips:.1f}p | Risk: ${actual_risk:.2f} (Target: ${target_risk:.2f})")
        
        return lot, sl_pips, margin_required, actual_risk
    
    def _get_pip_info(self, symbol_info) -> Tuple[float, int, int]:
        """Get pip size, pip to points, and digits for a symbol."""
        digits = symbol_info.digits
        name = symbol_info.name
        
        if "JPY" in name:
            pip_size = 0.01
            pip_to_points = 1 if digits == 3 else 10 if digits == 2 else 1
        elif "XAU" in name or "GOLD" in name:
            pip_size = 0.01 if digits == 2 else 0.1
            pip_to_points = 10 if digits == 2 else 1
        elif "XAG" in name or "SILVER" in name:
            pip_size = 0.001 if digits == 3 else 0.01
            pip_to_points = 10 if digits == 3 else 1
        else:
            pip_size = 0.0001 if digits in [4, 5] else symbol_info.point
            pip_to_points = 10 if digits in [3, 5] else 1
        
        return pip_size, pip_to_points, digits
    
    def debug_mt5_error(self, symbol: str, order_type: str, entry_price: float, 
                         stop_loss: float, take_profit: float):
        """Debug MT5 order rejection."""
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"   ❌ Symbol info not found for {symbol}")
            return
        
        ask, bid, spread = self._get_current_prices(symbol)
        if ask is None or bid is None:
            logger.error(f"   ❌ Cannot get tick data for {symbol}")
            return
        
        logger.error(f"   📊 Symbol: {symbol}")
        logger.error(f"      Ask: {ask}, Bid: {bid}")
        logger.error(f"      Spread: {spread}")
        logger.error(f"      Digits: {symbol_info.digits}")
        logger.error(f"      Trade Mode: {symbol_info.trade_mode}")
        logger.error(f"      Stop Level: {symbol_info.trade_stops_level}")
        logger.error(f"      Freeze Level: {symbol_info.trade_freeze_level}")
        
        if order_type == "BUY":
            if entry_price >= ask:
                logger.error(f"      ❌ BUY price {entry_price} >= ask {ask}")
            if stop_loss >= entry_price:
                logger.error(f"      ❌ SL {stop_loss} >= entry {entry_price}")
            if take_profit <= entry_price:
                logger.error(f"      ❌ TP {take_profit} <= entry {entry_price}")
        else:
            if entry_price <= bid:
                logger.error(f"      ❌ SELL price {entry_price} <= bid {bid}")
            if stop_loss <= entry_price:
                logger.error(f"      ❌ SL {stop_loss} <= entry {entry_price}")
            if take_profit >= entry_price:
                logger.error(f"      ❌ TP {take_profit} >= entry {entry_price}")
        
        stop_level = symbol_info.trade_stops_level
        if stop_level > 0:
            point = symbol_info.point
            if order_type == "BUY":
                min_sl = entry_price - (stop_level * point)
                min_tp = entry_price + (stop_level * point)
            else:
                min_sl = entry_price + (stop_level * point)
                min_tp = entry_price - (stop_level * point)
            
            if stop_loss < min_sl:
                logger.error(f"      ❌ SL {stop_loss} too close, min allowed: {min_sl}")
            if order_type == "BUY" and take_profit > min_tp:
                logger.error(f"      ❌ TP {take_profit} too close, min allowed: {min_tp}")
            if order_type == "SELL" and take_profit < min_tp:
                logger.error(f"      ❌ TP {take_profit} too close, min allowed: {min_tp}")
    
    def execute_trade(self, symbol: str, analysis_result: Dict[str, Any]) -> TradeResult:
        """Execute a trade with full margin risk calculation."""
        try:
            # ============================================================
            # STEP 1: CHECK POSITION LIMITS
            # ============================================================
            with self._state_lock:
                current_positions = len(self.monitor.open_positions)
                if current_positions >= self.MAX_SIMULTANEOUS_TRADES:
                    logger.warning(f"⚠️ {symbol}: Max trades reached ({current_positions}/{self.MAX_SIMULTANEOUS_TRADES})")
                    return TradeResult(symbol, False, error="Max trades reached")
                if symbol in self.monitor.open_positions:
                    logger.warning(f"⚠️ {symbol}: Already in trade")
                    return TradeResult(symbol, False, error="Already in trade")
            
            logger.info(f"{'='*60}")
            logger.info(f"💹 EXECUTING TRADE: {symbol}")
            logger.info(f"{'='*60}")
            
            # ============================================================
            # STEP 2: EXTRACT ANALYSIS DATA
            # ============================================================
            final_verdict = analysis_result.get("final_verdict", {})
            if not final_verdict:
                logger.error(f"❌ {symbol}: No final_verdict in analysis")
                return TradeResult(symbol, False, error="No final_verdict")
            
            stop_loss = final_verdict.get("stop_loss")
            take_profit_1 = final_verdict.get("take_profit_1")
            entry_price = final_verdict.get("entry_price")
            confidence = final_verdict.get("probability_percent", 0)
            
            config_data = analysis_result.get("config", {})
            order_type = config_data.get("executed_direction", "BUY")
            
            logger.info(f"📊 Analysis Confidence: {confidence}%")
            logger.info(f"📊 Direction: {order_type}")
            logger.info(f"📊 Entry: {entry_price}, SL: {stop_loss}, TP1: {take_profit_1}")
            
            if not stop_loss:
                logger.error(f"❌ {symbol}: No stop loss")
                return TradeResult(symbol, False, error="No stop loss")
            if not take_profit_1:
                logger.error(f"❌ {symbol}: No take profit")
                return TradeResult(symbol, False, error="No take profit")
            
            # ============================================================
            # STEP 3: GET CURRENT MARKET PRICES
            # ============================================================
            ask, bid, spread = self._get_current_prices(symbol)
            if ask is None or bid is None:
                logger.error(f"❌ {symbol}: Cannot get current prices")
                return TradeResult(symbol, False, error="Cannot get current prices")
            
            logger.info(f"📊 Market: Ask={ask}, Bid={bid}, Spread={spread:.5f}")
            
            # ============================================================
            # STEP 4: CALCULATE LOT AND RISK
            # ============================================================
            # Use market price for entry based on order type
            if order_type == "BUY":
                entry_price = ask
            else:
                entry_price = bid
            
            logger.info(f"📊 Using entry price: {entry_price}")
            
            lot, sl_pips, margin_required, actual_risk = self._calculate_full_margin_lot(symbol, order_type)
            
            if lot <= 0:
                logger.error(f"❌ {symbol}: Cannot calculate lot")
                return TradeResult(symbol, False, error="Cannot calculate lot")
            
            logger.info(f"📊 Lot: {lot:.2f}")
            logger.info(f"📊 Margin Required: ${margin_required:.2f}")
            logger.info(f"📊 Target Risk: ${self.FIXED_TRADE_SIZE_USD * self.RISK_PER_TRADE:.2f} ({self.RISK_PER_TRADE*100:.1f}%)")
            logger.info(f"📊 Actual Risk: ${actual_risk:.2f}")
            logger.info(f"📊 SL Distance: {sl_pips:.1f} pips")
            
            # ============================================================
            # STEP 5: CALCULATE SL AND TP
            # ============================================================
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                logger.error(f"❌ {symbol}: Symbol info not found")
                return TradeResult(symbol, False, error="Symbol info not found")
            
            pip_size, pip_to_points, digits = self._get_pip_info(symbol_info)
            
            sl_distance = sl_pips * pip_size
            tp_distance = sl_pips * pip_size * 1.5  # 1.5:1 risk/reward
            
            if order_type == "BUY":
                stop_loss = entry_price - sl_distance
                take_profit_1 = entry_price + tp_distance
            else:
                stop_loss = entry_price + sl_distance
                take_profit_1 = entry_price - tp_distance
            
            # Round to digits
            stop_loss = round(stop_loss, digits)
            take_profit_1 = round(take_profit_1, digits)
            
            logger.info(f"📊 Final SL: {stop_loss} ({sl_pips:.1f} pips)")
            logger.info(f"📊 Final TP1: {take_profit_1} ({sl_pips * 1.5:.1f} pips)")
            
            # ============================================================
            # STEP 6: VALIDATE TRADE PARAMETERS
            # ============================================================
            is_valid, validation_msg = self.validate_trade_params(
                symbol, order_type, entry_price, stop_loss, take_profit_1
            )
            
            if not is_valid:
                if "SL too tight" in validation_msg:
                    logger.warning(f"⚠️ {symbol}: {validation_msg}, using minimum SL")
                    if symbol_info:
                        pip_size_min, _, _ = self._get_pip_info(symbol_info)
                        min_sl = 1 * pip_size_min
                        if order_type == "BUY":
                            stop_loss = entry_price - min_sl
                        else:
                            stop_loss = entry_price + min_sl
                        is_valid, validation_msg = self.validate_trade_params(
                            symbol, order_type, entry_price, stop_loss, take_profit_1
                        )
                        if not is_valid:
                            logger.warning(f"⚠️ {symbol}: {validation_msg}")
                            return TradeResult(symbol, False, error=validation_msg)
                    else:
                        return TradeResult(symbol, False, error=validation_msg)
                else:
                    logger.warning(f"⚠️ {symbol}: {validation_msg}")
                    return TradeResult(symbol, False, error=validation_msg)
            
            logger.info(f"✅ {symbol}: Trade params validated")
            
            # ============================================================
            # STEP 7: CHECK TRADING CONDITIONS
            # ============================================================
            if symbol_info.trade_mode not in [mt5.SYMBOL_TRADE_MODE_FULL, mt5.SYMBOL_TRADE_MODE_LONGONLY, mt5.SYMBOL_TRADE_MODE_SHORTONLY]:
                logger.error(f"❌ {symbol}: Trading not allowed (mode: {symbol_info.trade_mode})")
                return TradeResult(symbol, False, error=f"Trading not allowed")
            
            # ============================================================
            # STEP 8: EXECUTE TRADE
            # ============================================================
            logger.info(f"{'='*60}")
            logger.info(f"🚀 EXECUTING: {symbol} {order_type}")
            logger.info(f"   Entry: {entry_price}")
            logger.info(f"   SL: {stop_loss}")
            logger.info(f"   TP: {take_profit_1}")
            logger.info(f"   Lot: {lot:.2f}")
            logger.info(f"   Risk: ${actual_risk:.2f} ({self.RISK_PER_TRADE*100:.1f}%)")
            logger.info(f"   Margin: ${margin_required:.2f}")
            logger.info(f"{'='*60}")
            
            execution_result = execute_trade(
                symbol=symbol,
                order_type=order_type,
                strategy_magic=self.STRATEGY_MAGIC,
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                max_spread=self.MAX_SPREAD,
                trade_deviation=self.TRADE_DEVIATION,
                max_trades_per_symbol=self.MAX_TRADES_PER_SYMBOL,
                max_simultaneous_trades=self.MAX_SIMULTANEOUS_TRADES,
                comment=f"AI Trade - {symbol}",
                stop_loss_price=stop_loss,
                take_profit_price=take_profit_1,
                # a strategy setup's stop is its invalidation level: kept, lot sized to the budget
                keep_stop=str((analysis_result.get("final_verdict") or {}).get("stop_source") or "")
                .startswith("strategy_setup"),
            )
            
            success = execution_result.get("success", False)
            ticket = execution_result.get("ticket")
            price = execution_result.get("price")
            volume = execution_result.get("volume")
            
            # ============================================================
            # STEP 9: LOG RESULT
            # ============================================================
            if success and ticket:
                logger.info(f"{'='*60}")
                logger.info(f"✅✅✅ {symbol}: TRADE EXECUTED SUCCESSFULLY!")
                logger.info(f"   Ticket: {ticket}")
                logger.info(f"   Price: {price}")
                logger.info(f"   Volume: {volume}")
                logger.info(f"   SL: {execution_result.get('stop_loss')}")
                logger.info(f"   TP: {execution_result.get('take_profit')}")
                logger.info(f"   Risk: ${actual_risk:.2f} ({self.RISK_PER_TRADE*100:.1f}%)")
                logger.info(f"   Margin: ${margin_required:.2f}")
                logger.info(f"{'='*60}")
            else:
                error_msg = execution_result.get("error", "Unknown error")
                logger.error(f"{'='*60}")
                logger.error(f"❌ {symbol}: TRADE FAILED")
                logger.error(f"   Error: {error_msg}")
                logger.error(f"{'='*60}")
                if "Request executed" in error_msg:
                    self.debug_mt5_error(symbol, order_type, entry_price, stop_loss, take_profit_1)
            
            # ============================================================
            # STEP 10: RETURN RESULT
            # ============================================================
            return TradeResult(
                symbol=symbol,
                success=success,
                ticket=ticket,
                entry_price=price,
                stop_loss=execution_result.get("stop_loss"),
                take_profit=execution_result.get("take_profit"),
                take_profit_2=execution_result.get("take_profit_2"),
                take_profit_3=execution_result.get("take_profit_3"),
                volume=volume,
                actual_margin=margin_required,
                actual_risk_usd=actual_risk,
                risk_percent_used=self.RISK_PER_TRADE * 100,
                probability_of_hit_percent=execution_result.get("probability_of_hit_percent"),
                magic=execution_result.get("magic"),
                comment=execution_result.get("comment"),
                order_type=order_type,
                error=execution_result.get("error") if not success else None,
                full_execution_response=execution_result,
                final_verdict=final_verdict,
                full_analysis=analysis_result,
                analysis_data={
                    "confidence": confidence,
                    "reason": final_verdict.get("verdict"),
                    "entry_status": analysis_result.get("entry_analysis", {}).get("entry_status"),
                    "star_rating": final_verdict.get("star_rating"),
                }
            )
                
        except Exception as e:
            logger.error(f"❌ Execution error for {symbol}: {e}")
            logger.error(traceback.format_exc())
            self.monitor.stats["execution_errors"] += 1
            return TradeResult(symbol, False, error=str(e))