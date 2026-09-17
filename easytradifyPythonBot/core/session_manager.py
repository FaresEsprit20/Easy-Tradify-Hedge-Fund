# core/session_manager.py
"""
Session Manager for Trading Assets - WITH CACHING + BACKGROUND REFRESH
Handles: Session times, weekend/holiday detection, minutes until close
Uses pandas_market_calendars (100% free, no API keys, offline)
Non-blocking: Returns cached data immediately while refreshing in background

FIXES APPLIED:
- Fixed deadlock risk in _background_refresh() by separating lock acquisition
- Added proper timezone validation for all datetime operations
- Added missing time import at module level
- Added health check method
- Added cache status method for debugging
- Improved error handling with specific exception types
- Added graceful degradation for calendar failures
"""

import pandas_market_calendars as mcal
import pandas as pd
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Tuple, Optional
import pytz
import logging
import time
from threading import Lock, Thread

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages trading sessions for all asset types.
    Handles VETO decisions for new entries based on session conditions.
    Non-blocking with background cache refresh.
    """
    
    def __init__(self, cache_ttl_seconds: int = 60):
        """
        Args:
            cache_ttl_seconds: How long to cache session data (default 60 seconds)
        """
        self.cache_ttl = cache_ttl_seconds
        self.cache = {}  # symbol -> session data
        self.last_fetch_time = 0
        self._lock = Lock()
        self._initialized = False
        self._is_refreshing = False
        self._refresh_thread = None
        self._last_error = None
        
        # Initialize calendars for different exchanges
        self.calendars = {}
        self._init_calendars()
        
        # Symbol to exchange mapping (45 symbols total)
        self.symbol_exchange_map = {
            # ============================================================
            # METALS - Gold & Silver (COMEX)
            # ============================================================
            "XAUUSD": "COMEX",
            "XAGUSD": "COMEX",
            "XAUEUR": "COMEX",
            "XAGEUR": "COMEX",
            "XAUJPY": "COMEX",
            "XAGJPY": "COMEX",
            
            # ============================================================
            # MAJOR FOREX (24/5 - no specific exchange, use FX)
            # ============================================================
            "EURUSD": "FX",
            "GBPUSD": "FX",
            "USDJPY": "FX",
            "USDCAD": "FX",
            "AUDUSD": "FX",
            "NZDUSD": "FX",
            "USDCHF": "FX",
            
            # ============================================================
            # FOREX CROSSES (24/5 - no specific exchange, use FX)
            # ============================================================
            "EURGBP": "FX",
            "EURJPY": "FX",
            "GBPJPY": "FX",
            "AUDJPY": "FX",
            "EURCAD": "FX",
            "GBPAUD": "FX",
            
            # ============================================================
            # MAJOR INDICES
            # ============================================================
            "SPX500": "NYSE",
            "NAS100": "NASDAQ",
            "US30": "NYSE",
            "DAX40": "XETRA",
            "FTSE100": "LSE",
            "NIKKEI": "TSE",
            "HK50": "HKEX",
            
            # ============================================================
            # COMMODITIES - OILS
            # ============================================================
            "USOIL": "NYMEX",
            "UKOIL": "ICE",
            
            # ============================================================
            # MAJOR STOCKS
            # ============================================================
            "AAPL": "NASDAQ",
            "MSFT": "NASDAQ",
            "GOOGL": "NASDAQ",
            "AMZN": "NASDAQ",
            "NVDA": "NASDAQ",
            "META": "NASDAQ",
            "TSLA": "NASDAQ",
            "JPM": "NYSE",
            "JNJ": "NYSE",
            "WMT": "NYSE",
            "XOM": "NYSE",
            "V": "NYSE",
            
            # ============================================================
            # MAJOR ETFS
            # ============================================================
            "SPY": "NYSE",
            "QQQ": "NASDAQ",
            "GLD": "NYSE",
            "SLV": "NYSE",
            "USO": "NYSE",
        }
        
        # Session close buffer (minutes before close to veto)
        self.close_buffer_minutes = 30
        
        # BOOM trade thresholds
        self.boom_min_gain_percent = 20
        self.boom_max_sl_pips = 15
        
        # Protection SL for overnight/weekend/holiday holds
        self.protection_sl_pips = 10
        
        logger.info(f"SessionManager initialized with {len(self.symbol_exchange_map)} symbols")
    
    def _init_calendars(self):
        """Initialize all required exchange calendars with error handling."""
        # exchange -> error string, for calendars that failed to load. An
        # entry here means every symbol on that exchange is silently running
        # on continuous-market rules unless callers check.
        self.calendar_load_failures = {}
        exchanges = [
            "COMEX", "NYMEX", "ICE",
            "NYSE", "NASDAQ", "XETRA", "LSE", "TSE", "HKEX"
        ]
        
        for exchange in exchanges:
            try:
                self.calendars[exchange] = mcal.get_calendar(exchange)
                logger.debug(f"Loaded calendar for {exchange}")
            except Exception as e:
                # ✅ FIXED: storing None here made a FAILED calendar
                # indistinguishable from "this symbol is FX and needs no
                # calendar" -- get_calendar() returns None for both, and
                # every consumer reads None as "continuous 24/5 market".
                # The consequence was silent and total: a COMEX/NYSE symbol
                # whose calendar failed to load got _is_market_open_sync()
                # == weekday() < 5 (open all day, every weekday, ignoring
                # actual exchange hours) and minutes_until_close == -2
                # ("no close time"), which makes
                # should_veto_pre_session_close() return "no veto"
                # unconditionally. That symbol's pre-close protection could
                # never fire again for the life of the process, and nothing
                # downstream could tell.
                #
                # Recorded explicitly so the degraded state is visible
                # rather than disguised as normal FX behaviour.
                logger.warning(f"Failed to load calendar for {exchange}: {e}")
                self.calendars[exchange] = None
                self.calendar_load_failures[exchange] = str(e)
    
    def get_exchange(self, symbol: str) -> str:
        """Get exchange for a symbol"""
        return self.symbol_exchange_map.get(symbol, "FX")
    
    def get_calendar(self, symbol: str):
        """
        Get calendar for a symbol's exchange.

        Returns None both for genuine FX symbols and for a non-FX symbol
        whose calendar failed to load. Callers that care about the
        difference must use is_calendar_degraded() -- see _init_calendars.
        """
        exchange = self.get_exchange(symbol)
        
        if exchange == "FX":
            return None
        
        return self.calendars.get(exchange)

    def is_calendar_degraded(self, symbol: str) -> bool:
        """
        True when this symbol's exchange is NOT FX but has no usable
        calendar -- i.e. it is being treated as a continuous 24/5 market by
        accident rather than by design.
        """
        exchange = self.get_exchange(symbol)
        if exchange == "FX":
            return False
        return self.calendars.get(exchange) is None
    
    def _ensure_timezone_aware(self, dt, default_tz=pytz.UTC):
        """Ensure a datetime is timezone-aware."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return default_tz.localize(dt)
        return dt
    
    def _calculate_session_data(self, symbol: str) -> Dict:
        """
        Calculate session data for a single symbol (synchronous).
        """
        try:
            exchange = self.get_exchange(symbol)
            is_open = self._is_market_open_sync(symbol)
            minutes_to_close = self._get_minutes_until_close_sync(symbol)
            is_trading_day_flag = self._is_trading_day_sync(symbol)
            
            return {
                "exchange": exchange,
                "is_market_open": is_open,
                "is_trading_day": is_trading_day_flag,
                "minutes_to_close": minutes_to_close,
                "calendar_degraded": self.is_calendar_degraded(symbol),
            }
        except Exception as e:
            logger.error(f"Error calculating session for {symbol}: {e}")
            return {
                "exchange": self.get_exchange(symbol),
                "is_market_open": True,  # Fail open
                "is_trading_day": True,  # Fail open
                "minutes_to_close": -1,
            }
    
    def _fetch_all_sessions_sync(self) -> Dict[str, Dict]:
        """
        Calculate session data for ALL symbols in ONE batch.
        Returns dict of symbol -> session data.
        """
        result = {}
        errors = 0
        
        for symbol in self.symbol_exchange_map.keys():
            try:
                result[symbol] = self._calculate_session_data(symbol)
            except Exception as e:
                logger.debug(f"Error calculating session for {symbol}: {e}")
                result[symbol] = {
                    "exchange": self.get_exchange(symbol),
                    "is_market_open": False,
                    "is_trading_day": False,
                    "minutes_to_close": -1,
                }
                errors += 1
        
        if errors > 0:
            logger.debug(f"[SESSION] Calculated session data for {len(result)} symbols ({errors} errors)")
        else:
            logger.debug(f"[SESSION] Calculated session data for {len(result)} symbols")
        
        return result
    
    def _background_refresh(self):
        """
        Background thread to refresh cache without blocking.
        FIXED: Separated lock acquisition to prevent deadlock.
        """
        # Check if already refreshing (outside the main lock to prevent deadlock)
        with self._lock:
            if self._is_refreshing:
                logger.debug("[SESSION] Background refresh already in progress, skipping")
                return
            self._is_refreshing = True
        
        try:
            logger.info("[SESSION] Background refresh started...")
            start_time = time.time()
            new_cache = self._fetch_all_sessions_sync()
            elapsed = time.time() - start_time
            
            with self._lock:
                if new_cache:
                    self.cache = new_cache
                    self.last_fetch_time = time.time()
                    self._initialized = True
                    self._last_error = None
                    logger.info(f"[SESSION] Background refresh completed successfully in {elapsed:.2f}s")
                else:
                    logger.warning("[SESSION] Background refresh failed, keeping old cache")
                    self._last_error = "Refresh returned empty cache"
        except Exception as e:
            logger.error(f"[SESSION] Background refresh error: {e}")
            self._last_error = str(e)
        finally:
            with self._lock:
                self._is_refreshing = False
    
    def _get_cached_session(self, symbol: str) -> Optional[Dict]:
        """Get cached session data for a symbol."""
        with self._lock:
            current_time = time.time()
            cache_expired = not self.cache or (current_time - self.last_fetch_time > self.cache_ttl)
            
            # If cache expired and not already refreshing, start background refresh
            if cache_expired and not self._is_refreshing and self._initialized:
                logger.debug(f"[SESSION] Cache expired, starting background refresh...")
                self._refresh_thread = Thread(target=self._background_refresh, daemon=True)
                self._refresh_thread.start()
            
            # Return existing cache (even if expired) while background refresh happens
            return self.cache.get(symbol) if self.cache else None
    
    # ============================================================
    # PUBLIC METHODS (Non-blocking, use cache)
    # ============================================================
    
    def is_market_open(self, symbol: str) -> bool:
        """Non-blocking market open check - uses cache."""
        cached = self._get_cached_session(symbol)
        if cached:
            return cached.get("is_market_open", False)
        # Fallback to synchronous calculation if cache empty
        return self._is_market_open_sync(symbol)
    
    def is_trading_day(self, symbol: str, check_date: date = None) -> bool:
        """Non-blocking trading day check - uses cache and MT5 status."""
        # ✅ NEW: If MT5 says market is open, it MUST be a trading day
        from core.execution import is_market_closed
        status = is_market_closed(symbol)
        if status.get("success", False) and not status.get("is_closed", True):
            return True
            
        # If MT5 is reachable and says closed, trust it
        if status.get("success", False) and status.get("is_closed", True):
            return False

        cached = self._get_cached_session(symbol)
        if cached:
            return cached.get("is_trading_day", False)
        return self._is_trading_day_sync(symbol, check_date)
    
    def get_minutes_until_close(self, symbol: str) -> float:
        """Non-blocking minutes until close - uses cache."""
        cached = self._get_cached_session(symbol)
        if cached:
            return cached.get("minutes_to_close", -1)
        return self._get_minutes_until_close_sync(symbol)
    
    def get_exchange_name(self, symbol: str) -> str:
        """Get exchange name for a symbol (no cache needed)."""
        return self.get_exchange(symbol)
    
    # ============================================================
    # SYNCHRONOUS METHODS (For cache warmup and fallback)
    # ============================================================
    
    def _is_trading_day_sync(self, symbol: str, check_date: date = None) -> bool:
        """Synchronous trading day check."""
        if check_date is None:
            check_date = date.today()
        
        calendar = self.get_calendar(symbol)
        
        if calendar is None:
            # For FX, trading happens weekdays only (24/5)
            return check_date.weekday() < 5
        
        try:
            schedule = calendar.schedule(
                start_date=check_date.strftime("%Y-%m-%d"),
                end_date=check_date.strftime("%Y-%m-%d")
            )
            return len(schedule) > 0
        except Exception as e:
            logger.error(f"Error checking trading day for {symbol}: {e}")
            # Fail open if we cannot verify trading day
            return True
    
    def _get_minutes_until_close_sync(self, symbol: str) -> float:
        """
        Synchronous minutes until close calculation.
        Returns:
            -1: Market closed for the day
            -2: Market open with no end time (FX)
            >0: Minutes until close
        """
        calendar = self.get_calendar(symbol)
        now_utc = datetime.now(pytz.UTC)
        
        # For FX (24/5 market)
        if calendar is None:
            # ✅ NEW: a non-FX symbol reaching this branch is running on FX
            # rules because its exchange calendar is missing, not because it
            # trades continuously. Behaviour is unchanged (deliberately --
            # changing it would start/stop trades on a code path that has
            # been silently wrong for a while), but it is no longer silent.
            if self.is_calendar_degraded(symbol):
                logger.warning(
                    f"[SESSION DEGRADED] {symbol} ({self.get_exchange(symbol)}): no exchange "
                    f"calendar loaded, falling back to continuous-market rules. Pre-close "
                    f"veto CANNOT fire for this symbol. Load error: "
                    f"{self.calendar_load_failures.get(self.get_exchange(symbol), 'unknown')}"
                )
            # Check if weekend
            if now_utc.weekday() >= 5:  # Saturday or Sunday
                return -1
            else:
                # FX markets close Friday 22:00 UTC, but we use -2 to indicate continuous trading
                return -2
        
        today_str = now_utc.strftime("%Y-%m-%d")
        try:
            schedule = calendar.schedule(start_date=today_str, end_date=today_str)
            
            if len(schedule) == 0:
                return -1
            
            market_close = schedule.iloc[0]['close']
            
            # Ensure timezone awareness
            market_close = self._ensure_timezone_aware(market_close, pytz.UTC)
            
            minutes_until = (market_close - now_utc).total_seconds() / 60
            return max(0, minutes_until)
            
        except Exception as e:
            logger.error(f"Error getting close time for {symbol}: {e}")
            return -1
    
    def _is_market_open_sync(self, symbol: str) -> bool:
        """Synchronous market open check using MT5 tick age."""
        from core.execution import is_market_closed
        
        # Prioritize MT5 tick-based check (more robust)
        status = is_market_closed(symbol)
        if status.get("success", False):
            return not status.get("is_closed", True)
            
        # Fallback if MT5 check fails
        logger.warning(f"MT5 market check failed for {symbol}: {status.get('reason')}. Falling back to calendar.")
        
        calendar = self.get_calendar(symbol)
        now_utc = datetime.now(pytz.UTC)
        
        # For FX (24/5 market)
        if calendar is None:
            # Market open on weekdays, closed on weekends
            return now_utc.weekday() < 5
        
        # Check if today is a trading day
        if not self._is_trading_day_sync(symbol):
            return False
        
        try:
            today_str = now_utc.strftime("%Y-%m-%d")
            schedule = calendar.schedule(start_date=today_str, end_date=today_str)
            
            if len(schedule) == 0:
                return False
            
            market_open = schedule.iloc[0]['open']
            market_close = schedule.iloc[0]['close']
            
            # Ensure timezone awareness
            market_open = self._ensure_timezone_aware(market_open, pytz.UTC)
            market_close = self._ensure_timezone_aware(market_close, pytz.UTC)
            
            return market_open <= now_utc <= market_close
            
        except Exception as e:
            logger.error(f"Error checking market open for {symbol}: {e}")
            return True # Fail open on error
    
    def warmup_cache(self):
        """Warm up cache on startup (synchronous, called once)."""
        logger.info("[SESSION] Warming up cache on startup...")
        start_time = time.time()
        
        with self._lock:
            if not self.cache:
                self.cache = self._fetch_all_sessions_sync()
                self.last_fetch_time = time.time()
                self._initialized = True
                elapsed = time.time() - start_time
                logger.info(f"[SESSION] Cache warmed up successfully in {elapsed:.2f}s")
            else:
                logger.info("[SESSION] Cache already exists, skipping warmup")
    
    def get_cache_status(self) -> Dict:
        """Get cache status for debugging."""
        with self._lock:
            age_seconds = time.time() - self.last_fetch_time if self.last_fetch_time > 0 else 0
            return {
                "initialized": self._initialized,
                "cached": len(self.cache) > 0,
                "cache_size": len(self.cache),
                "age_seconds": round(age_seconds, 1),
                "ttl_seconds": self.cache_ttl,
                "will_refresh_in": round(max(0, self.cache_ttl - age_seconds), 1),
                "is_refreshing": self._is_refreshing,
                "last_error": self._last_error,
            }
    
    def force_refresh(self):
        """Force refresh the cache (synchronous)."""
        logger.info("[SESSION] Force refreshing cache...")
        with self._lock:
            self.cache = self._fetch_all_sessions_sync()
            self.last_fetch_time = time.time()
            self._initialized = True
            self._is_refreshing = False
            self._last_error = None
    
    # ============================================================
    # BOOM TRADE AND VETO METHODS
    # ============================================================
    
    def is_boom_trade(self, expected_gain_percent: float, sl_pips: float) -> bool:
        """Check if trade qualifies as BOOM trade"""
        return expected_gain_percent >= self.boom_min_gain_percent and sl_pips < self.boom_max_sl_pips
    
    def should_veto_pre_session_close(self, symbol: str, expected_gain_percent: float, sl_pips: float) -> Tuple[bool, str, Optional[Dict]]:
        """Check if we should VETO a new entry due to session closing soon."""
        minutes_until = self.get_minutes_until_close(symbol)
        
        # -2 means continuous market (FX) with no close time
        if minutes_until == -2:
            return False, None, None
        
        # -1 means market closed
        if minutes_until == -1:
            return True, f"Market closed for {symbol}", None
        
        # Check if we're within the buffer zone before close
        if 0 < minutes_until < self.close_buffer_minutes:
            is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
            
            if is_boom:
                modifications = {
                    "modify_sl": True,
                    "new_sl_pips": self.protection_sl_pips,
                    "modify_tp": False,
                    "reason": f"BOOM trade allowed before close - using tight SL ({self.protection_sl_pips}p)"
                }
                return False, f"BOOM trade allowed before close: {expected_gain_percent:.0f}% expected", modifications
            else:
                return True, f"Session ends in {minutes_until:.0f} min - VETO (normal trade: {expected_gain_percent:.0f}% < 20%)", None
        
        return False, None, None
    
    def should_veto_weekend(self, symbol: str, expected_gain_percent: float, sl_pips: float) -> Tuple[bool, str, Optional[Dict]]:
        """Check if we should VETO a new entry before weekend."""
        now_utc = datetime.now(pytz.UTC)
        
        # Friday is weekday 4
        if now_utc.weekday() == 4:
            minutes_until = self.get_minutes_until_close(symbol)
            
            # For FX, Friday close is 22:00 UTC
            if self.get_exchange(symbol) == "FX":
                friday_close = now_utc.replace(hour=22, minute=0, second=0, microsecond=0)
                minutes_until = (friday_close - now_utc).total_seconds() / 60
            
            if 0 < minutes_until < self.close_buffer_minutes:
                is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
                
                if is_boom:
                    modifications = {
                        "modify_sl": True,
                        "new_sl_pips": self.protection_sl_pips,
                        "modify_tp": False,
                        "reason": f"BOOM trade allowed over weekend - using tight SL ({self.protection_sl_pips}p)"
                    }
                    return False, f"BOOM trade allowed over weekend: {expected_gain_percent:.0f}% expected", modifications
                else:
                    return True, f"Weekend close in {minutes_until:.0f} min - VETO (normal trade)", None
        
        return False, None, None
    
    def should_veto_holiday(self, symbol: str, expected_gain_percent: float, sl_pips: float) -> Tuple[bool, str, Optional[Dict]]:
        """Check if we should VETO a new entry before a market holiday."""
        now_utc = datetime.now(pytz.UTC)
        today_date = now_utc.date()
        tomorrow = today_date + timedelta(days=1)
        
        # Check if tomorrow is NOT a trading day (holiday)
        if not self._is_trading_day_sync(symbol, tomorrow):
            minutes_until = self.get_minutes_until_close(symbol)
            
            if 0 < minutes_until < self.close_buffer_minutes:
                is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
                
                if is_boom:
                    modifications = {
                        "modify_sl": True,
                        "new_sl_pips": self.protection_sl_pips,
                        "modify_tp": False,
                        "reason": f"BOOM trade allowed over holiday - using tight SL ({self.protection_sl_pips}p)"
                    }
                    return False, f"BOOM trade allowed over holiday: {expected_gain_percent:.0f}% expected", modifications
                else:
                    return True, f"Market holiday tomorrow - VETO (normal trade)", None
        
        return False, None, None
    
    def should_close_position_before_session_end(
        self, 
        symbol: str, 
        expected_gain_percent: float, 
        sl_pips: float,
        current_pnl_percent: float = 0
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Check if an EXISTING position should be closed or have TP/SL modified."""
        minutes_until = self.get_minutes_until_close(symbol)
        
        # -2 means continuous market (FX) - no need to close
        if minutes_until == -2:
            return False, None, None
        
        # -1 means market closed - must close
        if minutes_until == -1:
            return True, f"Market closed for {symbol} - close position", None
        
        # Check if we're within the buffer zone before close
        if 0 < minutes_until < self.close_buffer_minutes:
            is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
            
            if is_boom:
                modifications = {
                    "modify_sl": True,
                    "new_sl_pips": self.protection_sl_pips,
                    "modify_tp": False,
                    "reason": f"HOLD through close - BOOM trade, set tight SL to {self.protection_sl_pips}p"
                }
                return False, f"HOLD through close - BOOM trade", modifications
            else:
                return True, f"CLOSE before session end in {minutes_until:.0f} min - normal trade", None
        
        return False, None, None
    
    def get_session_summary(self, symbol: str, expected_gain_percent: float = 0, sl_pips: float = 0) -> Dict:
        """Get session summary for output."""
        exchange = self.get_exchange(symbol)
        is_open = self.is_market_open(symbol)
        minutes_to_close = self.get_minutes_until_close(symbol)
        is_trading_day_flag = self.is_trading_day(symbol)
        is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
        
        veto_triggered = False
        veto_reason = None
        
        if not is_open:
            veto_triggered = True
            veto_reason = f"Market closed for {symbol}"
        elif not is_trading_day_flag:
            veto_triggered = True
            veto_reason = f"No trading today for {symbol}"
        elif 0 < minutes_to_close < self.close_buffer_minutes:
            if not is_boom:
                veto_triggered = True
                veto_reason = f"Session ends in {minutes_to_close:.0f} min"
        
        return {
            "symbol": symbol,
            "exchange": exchange,
            "is_open": is_open,
            "is_trading_day": is_trading_day_flag,
            "minutes_to_close": round(minutes_to_close, 1) if minutes_to_close > 0 else minutes_to_close,
            "calendar_degraded": self.is_calendar_degraded(symbol),
            "veto_triggered": veto_triggered,
            "veto_reason": veto_reason,
        }
    
    def get_session_analysis(
        self, 
        symbol: str, 
        expected_gain_percent: float = 0, 
        sl_pips: float = 0,
        current_pnl_percent: float = 0,
        is_new_entry: bool = True
    ) -> Dict:
        """Complete session analysis for asset_analysis.py output."""
        exchange = self.get_exchange(symbol)
        is_open = self.is_market_open(symbol)
        minutes_to_close = self.get_minutes_until_close(symbol)
        is_trading_day_flag = self.is_trading_day(symbol)
        is_boom = self.is_boom_trade(expected_gain_percent, sl_pips)
        
        result = {
            "symbol": symbol,
            "exchange": exchange,
            "is_market_open": is_open,
            "is_trading_day": is_trading_day_flag,
            "minutes_to_close": round(minutes_to_close, 1) if minutes_to_close > 0 else minutes_to_close,
            "is_boom_trade": is_boom,
            "expected_gain_percent": expected_gain_percent,
            "sl_pips": sl_pips,
            "veto_triggered": False,
            "veto_reason": None,
            "modify_sl": False,
            "new_sl_pips": None,
            "new_sl_price": None,
            "modify_tp": False,
            "new_tp_pips": None,
            "new_tp_price": None,
            "modification_reason": None,
            "should_close": False,
            "close_reason": None,
        }
        
        if not is_new_entry:
            should_close, close_reason, modifications = self.should_close_position_before_session_end(
                symbol, expected_gain_percent, sl_pips, current_pnl_percent
            )
            
            if should_close:
                result["should_close"] = True
                result["close_reason"] = close_reason
                return result
            
            if modifications:
                result["modify_sl"] = modifications.get("modify_sl", False)
                result["new_sl_pips"] = modifications.get("new_sl_pips")
                result["new_sl_price"] = modifications.get("new_sl_price")
                result["modification_reason"] = modifications.get("reason")
            
            return result
        
        # New entry checks
        if not is_open:
            result["veto_triggered"] = True
            result["veto_reason"] = f"Market closed for {symbol}"
            return result
        
        if not is_trading_day_flag:
            result["veto_triggered"] = True
            result["veto_reason"] = f"No trading today for {symbol}"
            return result
        
        # Check pre-session close
        veto, reason, modifications = self.should_veto_pre_session_close(symbol, expected_gain_percent, sl_pips)
        if veto:
            result["veto_triggered"] = True
            result["veto_reason"] = reason
            return result
        if modifications:
            result["modify_sl"] = modifications.get("modify_sl", False)
            result["new_sl_pips"] = modifications.get("new_sl_pips")
            result["modification_reason"] = modifications.get("reason")
        
        # Check weekend
        veto, reason, modifications = self.should_veto_weekend(symbol, expected_gain_percent, sl_pips)
        if veto:
            result["veto_triggered"] = True
            result["veto_reason"] = reason
            return result
        if modifications and not result["modify_sl"]:
            result["modify_sl"] = modifications.get("modify_sl", False)
            result["new_sl_pips"] = modifications.get("new_sl_pips")
            result["modification_reason"] = modifications.get("reason")
        
        # Check holiday
        veto, reason, modifications = self.should_veto_holiday(symbol, expected_gain_percent, sl_pips)
        if veto:
            result["veto_triggered"] = True
            result["veto_reason"] = reason
            return result
        if modifications and not result["modify_sl"]:
            result["modify_sl"] = modifications.get("modify_sl", False)
            result["new_sl_pips"] = modifications.get("new_sl_pips")
            result["modification_reason"] = modifications.get("reason")
        
        return result
    
    def is_healthy(self) -> Dict:
        """Check if the session manager is healthy."""
        with self._lock:
            cache_age = time.time() - self.last_fetch_time if self.last_fetch_time > 0 else 999
            return {
                "initialized": self._initialized,
                "cache_valid": len(self.cache) > 0,
                "cache_age_seconds": round(cache_age, 1),
                "is_refreshing": self._is_refreshing,
                "last_error": self._last_error,
                "calendars_loaded": sum(1 for c in self.calendars.values() if c is not None),
                "total_calendars": len(self.calendars),
                # ✅ NEW: `calendars_loaded < total_calendars` was already
                # visible here, but only as a count -- it never said WHICH
                # exchange was missing, and a missing exchange silently
                # demotes all of its symbols to continuous-market rules
                # (see _init_calendars). Named explicitly so a health check
                # can act on it.
                "calendar_load_failures": dict(self.calendar_load_failures),
                "degraded_exchanges": sorted(self.calendar_load_failures.keys()),
            }


# ============================================================
# GLOBAL INSTANCE AND CONVENIENCE FUNCTIONS
# ============================================================

_session_manager = None

def get_session_manager() -> SessionManager:
    """Get or create the global session manager instance"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def warmup_session_cache():
    """Warm up session cache on application startup."""
    manager = get_session_manager()
    manager.warmup_cache()
    logger.info("[SESSION] Cache warmup initiated")


def get_session_analysis(
    symbol: str, 
    expected_gain_percent: float = 0, 
    sl_pips: float = 0,
    current_pnl_percent: float = 0,
    is_new_entry: bool = True
) -> Dict:
    """Get complete session analysis for asset_analysis.py output."""
    manager = get_session_manager()
    return manager.get_session_analysis(symbol, expected_gain_percent, sl_pips, current_pnl_percent, is_new_entry)


def get_session_summary(symbol: str, expected_gain_percent: float = 0, sl_pips: float = 0) -> Dict:
    """Get session summary for a symbol."""
    manager = get_session_manager()
    return manager.get_session_summary(symbol, expected_gain_percent, sl_pips)


def check_session_veto_for_new_entry(
    symbol: str, 
    expected_gain_percent: float = 0,
    sl_pips: float = 0
) -> Tuple[bool, str]:
    """Simplified veto check for new entries."""
    manager = get_session_manager()
    
    veto, reason, _ = manager.should_veto_pre_session_close(symbol, expected_gain_percent, sl_pips)
    if veto:
        return True, reason
    
    veto, reason, _ = manager.should_veto_weekend(symbol, expected_gain_percent, sl_pips)
    if veto:
        return True, reason
    
    veto, reason, _ = manager.should_veto_holiday(symbol, expected_gain_percent, sl_pips)
    if veto:
        return True, reason
    
    if not manager.is_market_open(symbol):
        return True, f"Market closed for {symbol}"
    
    return False, None


def check_session_close_for_existing_position(
    symbol: str,
    expected_gain_percent: float = 0,
    sl_pips: float = 0
) -> Tuple[bool, str]:
    """Simplified check for existing positions."""
    manager = get_session_manager()
    should_close, reason, _ = manager.should_close_position_before_session_end(symbol, expected_gain_percent, sl_pips)
    return should_close, reason


def get_minutes_to_market_close(symbol: str) -> float:
    """Get minutes until market close for a symbol."""
    manager = get_session_manager()
    return manager.get_minutes_until_close(symbol)


def is_market_open(symbol: str) -> bool:
    """Check if market is open for trading."""
    manager = get_session_manager()
    return manager.is_market_open(symbol)


def is_boom_trade(expected_gain_percent: float, sl_pips: float) -> bool:
    """Check if trade qualifies as BOOM trade."""
    manager = get_session_manager()
    return manager.is_boom_trade(expected_gain_percent, sl_pips)


def get_session_cache_status() -> Dict:
    """Get session cache status for debugging."""
    manager = get_session_manager()
    return manager.get_cache_status()


def get_session_health() -> Dict:
    """Get session manager health status."""
    manager = get_session_manager()
    return manager.is_healthy()