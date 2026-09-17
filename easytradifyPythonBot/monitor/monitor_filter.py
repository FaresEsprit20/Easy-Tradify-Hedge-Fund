# monitor/monitor_filter.py
# ============================================================
# FILTER & MARKET CONDITIONS - WITH FULL LOGGING
# ============================================================

import logging
import time
import threading
from typing import Dict, Any, List, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import MetaTrader5 as mt5
from .monitor_config import config
from .monitor_models import SymbolStatus
from core.execution import is_market_closed, check_volatility, check_spread_status
from core.asset_analysis import analyze_institutional_signal
logger = logging.getLogger(__name__)


class FilterManager:
    """Manages symbol filtering and market conditions."""
    
    def __init__(self, monitor):
        self.monitor = monitor
        self._state_lock = monitor._state_lock
        self.stop_event = monitor.stop_event
        self.symbols = monitor.symbols
        self.FILTER_THREADS = config.FILTER_THREADS
        self.TOP_SYMBOLS_COUNT = config.TOP_SYMBOLS_COUNT
        self.MIN_SYMBOLS_TO_TRADE = config.MIN_SYMBOLS_TO_TRADE
        self.MIN_CONFIDENCE_THRESHOLD = config.MIN_CONFIDENCE_THRESHOLD
        self.FIXED_TRADE_SIZE_USD = config.FIXED_TRADE_SIZE_USD
        self.RISK_PER_TRADE = config.RISK_PER_TRADE
        
    def check_market_conditions(self, symbol: str) -> Dict[str, Any]:
        """Check if market conditions are acceptable for trading."""
        result = {"symbol": symbol, "passed": False, "reasons": []}
        
        try:
            market_status = is_market_closed(symbol)
            if not market_status.get("success", False) or market_status.get("is_closed", True):
                reason = market_status.get("reason", "Market closed")
                result["reasons"].append(reason)
                logger.debug(f"⏭️ {symbol}: {reason}")
                return result
            
            volatility = check_volatility(symbol)
            if not volatility.get("success", False) or volatility.get("volatility_level") == "HIGH":
                result["reasons"].append("Volatility too high")
                logger.debug(f"⏭️ {symbol}: Volatility too high")
                return result
            
            spread = check_spread_status(symbol)
            if not spread.get("success", False) or not spread.get("is_acceptable", False):
                result["reasons"].append("Spread too high")
                logger.debug(f"⏭️ {symbol}: Spread too high")
                return result
            
            result["passed"] = True
            logger.debug(f"✅ {symbol}: Market conditions passed")
            return result
            
        except Exception as e:
            result["reasons"].append(f"Error: {str(e)}")
            logger.error(f"❌ {symbol}: Market check error: {e}")
            return result
    
    def filter_worker(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Worker for filtering symbols."""
        results = []
        for symbol in symbols:
            if self.stop_event.is_set():
                break
            
            with self._state_lock:
                if symbol in self.monitor.permanently_excluded:
                    results.append({"symbol": symbol, "passed": False, "reason": "Permanently excluded"})
                    logger.debug(f"⏭️ {symbol}: Permanently excluded (EMA200)")
                    continue
            
            result = self.check_market_conditions(symbol)
            if result["passed"]:
                if self.monitor._check_ema200(symbol):
                    with self._state_lock:
                        self.monitor.permanently_excluded.add(symbol)
                    result["passed"] = False
                    result["reasons"].append("EMA200 veto")
                    logger.info(f"🚫 PERMANENTLY EXCLUDED: {symbol} (EMA200)")
                else:
                    if self.monitor._check_long_term_trend(symbol):
                        with self._state_lock:
                            self.monitor.long_term_excluded.add(symbol)
                        result["passed"] = False
                        result["reasons"].append("Long-term trend veto")
                        logger.info(f"🚫 TREND EXCLUDED: {symbol} (D1/W1 trend)")
            
            results.append(result)
        
        return results
    
    def run_filter_step(self) -> bool:
        """Run the filter step to find valid symbols."""
        logger.info(f"🔍 Filtering {len(self.symbols)} symbols...")
        start_time = time.time()
        
        chunk_size = max(2, len(self.symbols) // self.FILTER_THREADS)
        chunks = [self.symbols[i:i + chunk_size] for i in range(0, len(self.symbols), chunk_size)]
        
        passed_symbols = []
        
        with ThreadPoolExecutor(max_workers=self.FILTER_THREADS, thread_name_prefix="Filter") as executor:
            futures = [executor.submit(self.filter_worker, chunk) for chunk in chunks]
            
            for future in as_completed(futures, timeout=20):
                try:
                    results = future.result(timeout=5)
                    for result in results:
                        if result.get("passed", False):
                            passed_symbols.append(result["symbol"])
                except Exception as e:
                    logger.error(f"Filter worker error: {e}")
                    self.monitor.stats["filter_errors"] += 1
        
        with self._state_lock:
            self.monitor.filtered_symbols = set(passed_symbols)
            self.monitor.stats["filtered_count"] = len(passed_symbols)
            self.monitor.stats["last_filter_time"] = time.time()
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Filtered: {len(passed_symbols)}/{len(self.symbols)} symbols in {elapsed:.1f}s")
        logger.info(f"   Permanent excluded (EMA200): {len(self.monitor.permanently_excluded)}")
        logger.info(f"   Long-term excluded (Trend): {len(self.monitor.long_term_excluded)}")
        
        if len(passed_symbols) < self.MIN_SYMBOLS_TO_TRADE:
            logger.warning(f"⚠️ Only {len(passed_symbols)} symbols passed filter (need {self.MIN_SYMBOLS_TO_TRADE})")
            return False
        
        return True
    
    def check_confidence(self, symbol: str) -> Dict[str, Any]:
        """Check confidence for a single symbol."""
        try:
            result = analyze_institutional_signal(
                symbol=symbol,
                order_type="BUY",
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="M1",
                debug=False
            )
            
            if not result.get("success", False):
                logger.debug(f"⚠️ {symbol}: Analysis failed")
                return {"symbol": symbol, "confidence": 0}
            
            final_verdict = result.get("final_verdict", {})
            confidence = final_verdict.get("probability_percent", 0)
            
            logger.debug(f"📊 {symbol}: Confidence = {confidence}%")
            
            return {
                "symbol": symbol,
                "confidence": confidence,
                "full_response": result
            }
            
        except Exception as e:
            logger.error(f"❌ Confidence check error for {symbol}: {e}")
            return {"symbol": symbol, "confidence": 0}
    
    def refresh_worker(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Worker for refreshing symbol confidence."""
        results = []
        for symbol in symbols:
            if self.stop_event.is_set():
                break
            
            with self._state_lock:
                if (symbol in self.monitor.permanently_excluded or 
                    symbol in self.monitor.long_term_excluded or 
                    symbol in self.monitor.open_positions):
                    continue
            
            try:
                result = self.check_confidence(symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"Refresh worker error for {symbol}: {e}")
        
        return results
    
    def refresh_top_symbols(self) -> List[Dict[str, Any]]:
        """Refresh the top symbols list with confidence scores."""
        with self._state_lock:
            symbols_to_check = [
                s for s in self.monitor.filtered_symbols 
                if s not in self.monitor.open_positions 
                and s not in self.monitor.permanently_excluded
                and s not in self.monitor.long_term_excluded
            ]
        
        if not symbols_to_check:
            logger.info("⚠️ No symbols to check for confidence")
            return []
        
        with self.monitor._refresh_lock:
            if self.monitor._refreshing:
                return []
            self.monitor._refreshing = True
        
        try:
            logger.info(f"📊 Checking confidence for {len(symbols_to_check)} symbols...")
            start_time = time.time()
            
            chunk_size = max(1, min(len(symbols_to_check) // self.FILTER_THREADS, 3))
            chunks = [symbols_to_check[i:i + chunk_size] for i in range(0, len(symbols_to_check), chunk_size)]
            
            all_results = []
            
            with ThreadPoolExecutor(max_workers=self.FILTER_THREADS, thread_name_prefix="Refresh") as executor:
                futures = [executor.submit(self.refresh_worker, chunk) for chunk in chunks]
                
                for future in as_completed(futures, timeout=20):
                    try:
                        results = future.result(timeout=8)
                        all_results.extend(results)
                    except Exception as e:
                        logger.error(f"Refresh future error: {e}")
            
            valid_symbols = []
            for item in all_results:
                confidence = item.get("confidence", 0)
                if confidence >= self.MIN_CONFIDENCE_THRESHOLD:
                    valid_symbols.append(item)
                    logger.debug(f"✅ {item['symbol']}: {confidence}% >= {self.MIN_CONFIDENCE_THRESHOLD}%")
                else:
                    logger.debug(f"⏭️ {item['symbol']}: {confidence}% < {self.MIN_CONFIDENCE_THRESHOLD}%")
            
            valid_symbols.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            top = valid_symbols[:self.TOP_SYMBOLS_COUNT]
            
            with self._state_lock:
                self.monitor.top_symbols = []
                for item in top:
                    symbol = item["symbol"]
                    stable_signal = self.monitor.stability.get_stable_signal(symbol)
                    tracker = self.monitor.stability.tracker.get(symbol, {})
                    checks = len(tracker.get("checks", []))
                    
                    if stable_signal:
                        avg_conf = stable_signal.get("avg_confidence", 0)
                        if avg_conf >= 75:
                            stability_status = "✅ EXECUTABLE"
                        else:
                            stability_status = f"⏳ STABLE ({avg_conf:.0f}%)"
                    else:
                        stability_status = f"⏳ {checks}/{self.monitor.STABILITY_REQUIRED_CHECKS}"
                    
                    status = SymbolStatus(
                        symbol=symbol,
                        confidence=item.get("confidence", 0),
                        is_active=True,
                        exchange=self.monitor.SYMBOL_EXCHANGE_MAP.get(symbol, "FX"),
                        reason=stability_status,
                        stability_status=stability_status,
                        last_check_time=time.time()
                    )
                    self.monitor.top_symbols.append(status)
                    self.monitor.symbol_status_map[symbol] = status
                
                self.monitor.stats["last_refresh_time"] = time.time()
            
            elapsed = time.time() - start_time
            if top:
                logger.info(f"📈 Top {len(top)} symbols (in {elapsed:.1f}s):")
                for i, item in enumerate(top, 1):
                    symbol = item['symbol']
                    stable = self.monitor.stability.get_stable_signal(symbol)
                    if stable and stable.get("is_executable", False):
                        indicator = "✅"
                    elif stable:
                        indicator = "⏳"
                    else:
                        indicator = "🔍"
                    logger.info(f"  #{i}: {symbol} - Conf: {item.get('confidence', 0)}% {indicator}")
            else:
                logger.info(f"⚠️ No symbols above {self.MIN_CONFIDENCE_THRESHOLD}% confidence")
            
            return top
            
        finally:
            self.monitor._refreshing = False