# ============================================================
# LIGHTWEIGHT GNN FETCHER - FIXED WITH HARDCODED MT5 SYMBOLS
# ============================================================

import logging
import time
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import MetaTrader5 as mt5
import numpy as np

from core.calculations import get_pip_info

logger = logging.getLogger(__name__)


class LightweightGNNFetcher:
    """
    Lightweight data fetcher for GNN with REAL MT5 data.
    """
    
    def __init__(self, monitor, config):
        self.monitor = monitor
        self.config = config
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 30  # 30 seconds
        self._lock = threading.Lock()
        
        # ✅ Store previous prices for direction calculation
        self._prev_prices = {}
        
        # ✅ HARDCODED MT5 SYMBOL MAPPING (works without monitor)
        self.symbol_mt5_map = {
            # FX Pairs
            'EURUSD': 'EURUSD', 'GBPUSD': 'GBPUSD', 'USDJPY': 'USDJPY',
            'AUDUSD': 'AUDUSD', 'USDCAD': 'USDCAD', 'NZDUSD': 'NZDUSD',
            'USDCHF': 'USDCHF', 'EURGBP': 'EURGBP', 'EURCAD': 'EURCAD',
            'EURJPY': 'EURJPY', 'GBPJPY': 'GBPJPY', 'AUDJPY': 'AUDJPY',
            'CADJPY': 'CADJPY', 'CHFJPY': 'CHFJPY', 'AUDNZD': 'AUDNZD',
            'AUDCAD': 'AUDCAD',
            
            # Commodities
            'XAUUSD': 'XAUUSD', 'XAGUSD': 'XAGUSD',
            'USOIL': 'USOIL', 'UKOIL': 'UKOIL',
            'WTI': 'WTI', 'BRENT': 'BRENT',
            
            # Indices
            'SPX500': 'SPX500', 'NAS100': 'NAS100', 'US30': 'US30',
            'DAX40': 'DAX40', 'FTSE100': 'FTSE100', 'CAC40': 'CAC40',
            'SP500': 'SP500', 'NDX100': 'NDX100', 'DJ30': 'DJ30',
            'DAX30': 'DAX30', 'FTSE': 'FTSE', 'CAC': 'CAC',
            
            # Tech Stocks
            'AAPL': 'AAPL', 'MSFT': 'MSFT', 'NVDA': 'NVDA',
            'GOOGL': 'GOOGL', 'META': 'META', 'AMZN': 'AMZN',
            'TSLA': 'TSLA',
            
            # Financials/Energy
            'JPM': 'JPM', 'V': 'V', 'XOM': 'XOM', 'CVX': 'CVX',
            'BAC': 'BAC', 'WFC': 'WFC',
            
            # Consumer/Healthcare
            'WMT': 'WMT', 'MCD': 'MCD', 'JNJ': 'JNJ', 'PFE': 'PFE',
            'GE': 'GE', 'PG': 'PG', 'KO': 'KO', 'PEP': 'PEP',
        }
        
        # Exchange mapping
        self.exchange_map = {
            'EURUSD': 'FX', 'GBPUSD': 'FX', 'USDJPY': 'FX', 'AUDUSD': 'FX',
            'USDCAD': 'FX', 'NZDUSD': 'FX', 'USDCHF': 'FX', 'EURGBP': 'FX',
            'EURCAD': 'FX', 'EURJPY': 'FX', 'GBPJPY': 'FX', 'AUDJPY': 'FX',
            'CADJPY': 'FX', 'CHFJPY': 'FX', 'AUDNZD': 'FX', 'AUDCAD': 'FX',
            'XAUUSD': 'COMMODITY', 'XAGUSD': 'COMMODITY',
            'USOIL': 'COMMODITY', 'UKOIL': 'COMMODITY',
            'WTI': 'COMMODITY', 'BRENT': 'COMMODITY',
            'SPX500': 'INDEX', 'NAS100': 'INDEX', 'US30': 'INDEX',
            'DAX40': 'INDEX', 'FTSE100': 'INDEX', 'CAC40': 'INDEX',
            'SP500': 'INDEX', 'NDX100': 'INDEX', 'DJ30': 'INDEX',
            'DAX30': 'INDEX', 'FTSE': 'INDEX', 'CAC': 'INDEX',
            'AAPL': 'TECH', 'MSFT': 'TECH', 'NVDA': 'TECH',
            'GOOGL': 'TECH', 'META': 'TECH', 'AMZN': 'TECH',
            'TSLA': 'TECH',
            'JPM': 'FINANCE', 'V': 'FINANCE', 'BAC': 'FINANCE',
            'WFC': 'FINANCE',
            'XOM': 'ENERGY', 'CVX': 'ENERGY',
            'WMT': 'CONSUMER', 'MCD': 'CONSUMER', 'PG': 'CONSUMER',
            'KO': 'CONSUMER', 'PEP': 'CONSUMER',
            'JNJ': 'HEALTHCARE', 'PFE': 'HEALTHCARE', 'GE': 'INDUSTRIAL'
        }
        
        logger.info("🚀 LightweightGNNFetcher initialized with hardcoded MT5 symbols")
        logger.info(f"   Total symbols mapped: {len(self.symbol_mt5_map)}")
    
    def get_all_assets_features(self, assets: List[str]) -> Dict[str, Dict]:
        """Get features for all assets."""
        features = {}
        
        for symbol in assets:
            feat = self.get_asset_features(symbol)
            if feat:
                features[symbol] = feat
        
        return features
    
    def get_asset_features(self, symbol: str) -> Optional[Dict]:
        """Get features for a single asset."""
        # Check cache
        with self._lock:
            if symbol in self._cache:
                if time.time() - self._cache_time.get(symbol, 0) < self._cache_ttl:
                    return self._cache[symbol]
        
        # Generate features
        features = self._fetch_features(symbol)
        
        # Cache
        if features:
            with self._lock:
                self._cache[symbol] = features
                self._cache_time[symbol] = time.time()
        
        return features
    
    def _fetch_features(self, symbol: str) -> Dict:
        """Fetch REAL features for a symbol from MT5."""
        try:
            # ✅ Get MT5 symbol from hardcoded map
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            
            if mt5_symbol == "NOT_FOUND" or mt5_symbol == "NOT_TRADABLE":
                return self._get_default_features(symbol)
            
            # ✅ Get symbol info
            symbol_info = mt5.symbol_info(mt5_symbol)
            if not symbol_info:
                return self._get_default_features(symbol)
            
            # ✅ Get tick data (REAL-TIME)
            tick = mt5.symbol_info_tick(mt5_symbol)
            if not tick:
                return self._get_default_features(symbol)
            
            # ✅ Get rates for indicators (H1)
            rates_h1 = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_H1, 0, 100)
            if rates_h1 is None or len(rates_h1) < 20:
                rates_h1 = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M5, 0, 100)
            
            if rates_h1 is None or len(rates_h1) < 20:
                return self._get_default_features(symbol)
            
            # ✅ FIXED: atr_pips/spread used a hardcoded *10000 multiplier,
            # which is only correct for standard 4-decimal FX majors.
            # This fetcher's own symbol_mt5_map explicitly includes JPY
            # crosses (real pip_size 0.01, not 0.0001 -- *10000 makes
            # atr_pips ~100x too large), metals, indices, and individual
            # stocks (where "*10000" produces a nonsensical number
            # entirely, e.g. an AAPL ATR of $2 becoming "20000 pips").
            # get_pip_info() (core/calculations.py) is the same
            # instrument-aware pip-size lookup used throughout the rest
            # of this codebase, reusing the symbol_info already fetched
            # above rather than an extra MT5 call.
            pip_size, _, _ = get_pip_info(symbol_info)

            # Calculate features
            close_prices = [r[4] for r in rates_h1]
            high_prices = [r[2] for r in rates_h1]
            low_prices = [r[3] for r in rates_h1]
            volumes = [r[5] for r in rates_h1]
            
            # ✅ Get previous price for direction
            prev_price = self._prev_prices.get(symbol, tick.bid)
            current_price = tick.bid
            self._prev_prices[symbol] = current_price
            
            # ✅ Calculate DIRECTION from REAL price movement
            direction = self._calculate_direction_real(prev_price, current_price, close_prices)
            
            # ✅ ATR (volatility)
            atr = self._calculate_atr(high_prices, low_prices, close_prices, 14)
            
            # ✅ Volume ratio
            avg_volume = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
            current_volume = volumes[-1] if volumes else 1
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            # ✅ RSI
            rsi = self._calculate_rsi(close_prices, 14)
            
            # ✅ MACD
            macd, signal = self._calculate_macd(close_prices)
            
            # ✅ ADX (trend strength)
            adx = self._calculate_adx(high_prices, low_prices, close_prices, 14)
            
            # ✅ Exchange
            exchange = self.exchange_map.get(symbol, 'UNKNOWN')
            
            features = {
                'symbol': symbol,
                'exchange': exchange,
                'direction_4h': direction,
                'atr_pips': atr / pip_size if pip_size > 0 else atr * 10000,
                'volume_ratio': min(10, max(0.1, volume_ratio)),
                'price': tick.bid,
                'spread': (tick.ask - tick.bid) / pip_size if pip_size > 0 else (tick.ask - tick.bid) * 10000,
                'rsi_14': rsi,
                'macd': macd,
                'macd_signal': signal,
                'adx_14': adx,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            
            # ✅ Log first successful fetch to confirm
            if symbol not in self._cache:
                logger.debug(f"✅ Fetched real data for {symbol}: direction={direction:.3f}, price={tick.bid}")
            
            return features
            
        except Exception as e:
            logger.debug(f"Error fetching features for {symbol}: {e}")
            return self._get_default_features(symbol)
    
    def _calculate_direction_real(self, prev_price: float, current_price: float, close_prices: List[float]) -> float:
        """
        ✅ FIXED: Calculate REAL direction from price movement.
        Returns -1.0 to 1.0
        """
        direction = 0.0
        
        # 1. Current tick change (momentum)
        if prev_price > 0 and current_price > 0:
            tick_change = (current_price - prev_price) / prev_price
            direction += tick_change * 50  # Scale to -1 to 1
        
        # 2. Short-term trend (last 5 bars)
        if len(close_prices) >= 5:
            short_change = (close_prices[-1] - close_prices[-5]) / close_prices[-5] if close_prices[-5] > 0 else 0
            direction += short_change * 30
        
        # 3. Medium-term trend (last 20 bars)
        if len(close_prices) >= 20:
            medium_change = (close_prices[-1] - close_prices[-20]) / close_prices[-20] if close_prices[-20] > 0 else 0
            direction += medium_change * 20
        
        # 4. Clamp to [-1, 1]
        direction = max(-1.0, min(1.0, direction))
        
        # 5. If direction is very small but not zero, amplify slightly
        if abs(direction) < 0.01 and direction != 0:
            direction = 0.05 if direction > 0 else -0.05
        
        return round(direction, 4)
    
    def _calculate_direction(self, close_prices: List[float]) -> float:
        """Legacy method - kept for compatibility."""
        if len(close_prices) < 30:
            return 0
        
        ma_5 = sum(close_prices[-5:]) / 5
        ma_10 = sum(close_prices[-10:]) / 10
        ma_20 = sum(close_prices[-20:]) / 20
        ma_50 = sum(close_prices[-50:]) / 50 if len(close_prices) >= 50 else ma_20
        
        current = close_prices[-1]
        
        bullish = 0
        bearish = 0
        
        if current > ma_5:
            bullish += 1
        else:
            bearish += 1
        if ma_5 > ma_10:
            bullish += 1
        else:
            bearish += 1
        if ma_10 > ma_20:
            bullish += 1
        else:
            bearish += 1
        if ma_20 > ma_50:
            bullish += 1
        else:
            bearish += 1
        
        if bullish > bearish:
            strength = bullish / (bullish + bearish)
            return strength
        elif bearish > bullish:
            strength = bearish / (bullish + bearish)
            return -strength
        else:
            return 0.0
    
    def _calculate_rsi(self, close_prices: List[float], period: int = 14) -> float:
        """Calculate RSI."""
        if len(close_prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, period + 1):
            diff = close_prices[-i] - close_prices[-i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, close_prices: List[float]) -> tuple:
        """Calculate MACD."""
        if len(close_prices) < 26:
            return 0, 0
        
        def ema(data, period):
            if len(data) < period:
                return data[-1] if data else 0
            k = 2 / (period + 1)
            ema_val = data[0]
            for price in data[1:]:
                ema_val = price * k + ema_val * (1 - k)
            return ema_val
        
        ema_12 = ema(close_prices, 12)
        ema_26 = ema(close_prices, 26)
        macd = ema_12 - ema_26
        
        macd_values = []
        for i in range(9, len(close_prices)):
            e12 = ema(close_prices[:i+1], 12)
            e26 = ema(close_prices[:i+1], 26)
            macd_values.append(e12 - e26)
        
        if len(macd_values) >= 9:
            signal = ema(macd_values, 9)
            return macd, signal
        
        return macd, macd
    
    def _calculate_adx(self, high: List[float], low: List[float], 
                       close: List[float], period: int = 14) -> float:
        """Calculate ADX (trend strength)."""
        if len(close) < period + 1:
            return 25.0
        
        plus_dm = []
        minus_dm = []
        tr = []
        
        for i in range(1, min(len(close), period + 5)):
            up_move = high[-i] - high[-i-1] if i < len(high) else 0
            down_move = low[-i-1] - low[-i] if i < len(low) else 0
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
            
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
            
            hl = high[-i] - low[-i] if i < len(high) and i < len(low) else 0
            hc = abs(high[-i] - close[-i-1]) if i < len(high) else 0
            lc = abs(low[-i] - close[-i-1]) if i < len(low) else 0
            tr.append(max(hl, hc, lc))
        
        if len(plus_dm) < period:
            return 25.0
        
        atr = sum(tr[-period:]) / period
        plus_di = (sum(plus_dm[-period:]) / period) / atr * 100 if atr > 0 else 0
        minus_di = (sum(minus_dm[-period:]) / period) / atr * 100 if atr > 0 else 0
        
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        
        return min(100, dx)
    
    def _calculate_atr(self, high: List[float], low: List[float], 
                       close: List[float], period: int = 14) -> float:
        """Calculate ATR."""
        if len(close) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, min(len(close), period + 2)):
            hl = high[-i] - low[-i] if i < len(high) and i < len(low) else 0
            hc = abs(high[-i] - close[-i-1]) if i < len(high) else 0
            lc = abs(low[-i] - close[-i-1]) if i < len(low) else 0
            tr = max(hl, hc, lc)
            tr_values.append(tr)
        
        return sum(tr_values) / len(tr_values) if tr_values else 0
    
    def _get_default_features(self, symbol: str) -> Dict:
        """Get default features when data is unavailable."""
        return {
            'symbol': symbol,
            'exchange': self.exchange_map.get(symbol, 'UNKNOWN'),
            'direction_4h': 0.0,
            'atr_pips': 0.0,
            'volume_ratio': 1.0,
            'price': 0.0,
            'spread': 0.0,
            'rsi_14': 50.0,
            'macd': 0.0,
            'macd_signal': 0.0,
            'adx_14': 25.0,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    
    def clear_cache(self):
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._cache_time.clear()
            self._prev_prices.clear()
        logger.info("🧹 GNN fetcher cache cleared")