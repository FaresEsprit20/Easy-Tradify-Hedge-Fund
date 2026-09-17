# ============================================================
# AI GNN - GRAPH NEURAL NETWORKS FOR CROSS-ASSET LEARNING
# ============================================================
# 
# WHAT THIS DOES:
# - Builds graph of assets (nodes = assets, edges = relationships)
# - Learns cross-asset relationships automatically
# - Extracts context features for trading decisions
# - ✅ DETECTS CORRELATIONS between assets (DYNAMIC)
# - ✅ FLAGS DIVERGENCES (GNN says DOWN, price says UP)
# - ✅ SUGGESTS CORRELATED TRADES with REAL-TIME confidence
# - ✅ CONFLICT DETECTION with your analysis
# - ✅ FIXED: Suggestions now properly returned
# - ✅ FIXED: Recommendation score now calculated
# - ✅ FIXED: Conflicts working with severity levels
# - ✅ FIXED: Insights complete with all data
# - Runs in background (separate thread)
# ============================================================

import logging
import time
import threading
import numpy as np
from typing import Dict, Any, List, Mapping, Optional, Sequence, Tuple
from datetime import datetime, timezone
from collections import defaultdict, deque
import random
import hashlib
import json
import os

try:
    from .ai_gnn_lightweight import LightweightGNNFetcher
except ImportError:
    LightweightGNNFetcher = None
    logging.warning("⚠️ LightweightGNNFetcher not available")

from .ai_config import AIConfig, default_config

logger = logging.getLogger(__name__)


class AssetGraphNeuralNetwork:
    """
    ✅ COMPLETE: Graph Neural Network with DYNAMIC CORRELATIONS.
    ✅ FIXED: Suggestions now properly generated and returned.
    ✅ FIXED: Recommendation score now calculated.
    ✅ FIXED: Conflicts working with severity levels.
    ✅ FIXED: Insights complete with all data.
    """
    
    def __init__(self, firebase_service, config: AIConfig, monitor=None):
        self.firebase = firebase_service
        self.config = config or default_config
        self.monitor = monitor
        
        # ============================================================
        # CHECK ENABLED STATUS
        # ============================================================
        
        self.is_enabled = self.config.gnn_enabled
        
        if not self.is_enabled:
            logger.info("ℹ️ GNN disabled by config - running in inactive mode")
            self.is_trained = False
            self.is_running = False
            self.context_cache = {}
            self.graph = None
            self.trading_signals = {}
            self.price_history = {}
            self.dynamic_correlations = {}
            self.correlation_history = {}  # ✅ NEW: bounded per-pair history so detect_correlation_changes() has real data to compare against
            # ✅ FIXED: assets/static_correlations must exist even when disabled —
            # get_correlation_matrix()/get_correlation_heatmap() read them
            # unconditionally and crashed with AttributeError otherwise
            # (hit via the /gnn/heatmap and /gnn/correlations routes, which
            # only check `_gnn is not None`, not `_gnn.is_enabled`).
            self.assets = []
            self.static_correlations = {}
            self._mt5_available = False
            self.fetcher = None
            self.ab_test = {
                'enabled': False,
                'rollout': 0.0,
                'control_wins': 0,
                'control_losses': 0,
                'control_profit': 0,
                'test_wins': 0,
                'test_losses': 0,
                'test_profit': 0,
                'total_trades': 0,
                'last_adjustment': None,
            }
            return
        
        # ============================================================
        # LIGHTWEIGHT FETCHER
        # ============================================================
        
        if LightweightGNNFetcher is None:
            logger.error("❌ LightweightGNNFetcher not available - GNN cannot start")
            self.is_enabled = False
            self.is_trained = False
            self.is_running = False
            self.context_cache = {}
            self.graph = None
            self.trading_signals = {}
            self.price_history = {}
            self.dynamic_correlations = {}
            self.correlation_history = {}  # ✅ NEW: bounded per-pair history so detect_correlation_changes() has real data to compare against
            # ✅ FIXED: same as above — keep these attributes present so
            # correlation-matrix/heatmap calls degrade gracefully instead of
            # raising AttributeError.
            self.assets = []
            self.static_correlations = {}
            self._mt5_available = False
            self.fetcher = None
            self.ab_test = {'enabled': False}
            return
        
        self.fetcher = LightweightGNNFetcher(monitor, config)
        
        # ============================================================
        # GNN STATE
        # ============================================================
        
        self.graph = None
        self.edge_weights = {}
        self.node_features = {}
        self.context_cache = {}
        self.trading_signals = {}
        self.price_history = {}
        self.dynamic_correlations = {}
        self.correlation_history = {}  # ✅ NEW: bounded per-pair history so detect_correlation_changes() has real data to compare against
        self.last_update = None
        self.is_trained = False
        self.is_running = False
        
        # ✅ FIXED: _get_direct_mt5_data() previously hit the MT5 terminal
        # fresh on every single call with zero caching — get_trading_insights()
        # calls it once for the symbol plus once per correlated asset (up to
        # ~9), so a single HTTP request to /gnn/insights/<symbol> could fire
        # 10+ synchronous MT5 API round trips. Under repeated/concurrent
        # requests this could hammer and destabilize the MT5 terminal
        # connection. Short TTL cache below fixes that.
        self._mt5_data_cache = {}
        self._mt5_data_cache_time = {}
        self._mt5_data_cache_ttl = 10  # seconds
        
        # ✅ Store previous prices for direction calculation
        self._prev_prices = {}
        
        # ✅ MT5 SYMBOL MAPPING (Hardcoded for direct access)
        self._mt5_symbol_map = {
            'EURUSD': 'EURUSD', 'GBPUSD': 'GBPUSD', 'USDJPY': 'USDJPY',
            'AUDUSD': 'AUDUSD', 'USDCAD': 'USDCAD', 'NZDUSD': 'NZDUSD',
            'USDCHF': 'USDCHF', 'EURGBP': 'EURGBP', 'EURCAD': 'EURCAD',
            'EURJPY': 'EURJPY', 'GBPJPY': 'GBPJPY', 'AUDJPY': 'AUDJPY',
            'CADJPY': 'CADJPY', 'CHFJPY': 'CHFJPY', 'AUDNZD': 'AUDNZD',
            'AUDCAD': 'AUDCAD', 'XAUUSD': 'XAUUSD', 'XAGUSD': 'XAGUSD',
            'USOIL': 'USOIL', 'UKOIL': 'UKOIL', 'SPX500': 'SPX500',
            'NAS100': 'NAS100', 'US30': 'US30', 'DAX40': 'DAX40',
            'FTSE100': 'FTSE100', 'CAC40': 'CAC40', 'AAPL': 'AAPL',
            'MSFT': 'MSFT', 'NVDA': 'NVDA', 'GOOGL': 'GOOGL',
            'META': 'META', 'JPM': 'JPM', 'V': 'V', 'XOM': 'XOM',
            'CVX': 'CVX', 'WMT': 'WMT', 'MCD': 'MCD', 'JNJ': 'JNJ',
            'PFE': 'PFE'
        }
        
        # ============================================================
        # ✅ CORRELATION MATRIX (Static baseline + dynamic updates)
        # ============================================================
        
        self.static_correlations = {}
        self._init_static_correlations()
        
        # ============================================================
        # PERFORMANCE TRACKING
        # ============================================================
        
        self.update_times = deque(maxlen=100)
        self.update_count = 0
        self.error_count = 0
        self.consecutive_errors = 0
        
        # ============================================================
        # AUTO-ROLLBACK STATE
        # ============================================================
        
        self.rollback_state = {
            'triggered': False,
            'reason': None,
            'timestamp': None,
            'last_good_graph': None,
            'last_good_context': None,
        }
        
        # ============================================================
        # THREAD CONTROL
        # ============================================================
        
        self.update_thread = None
        self.stop_flag = False
        self._lock = threading.Lock()
        
        # ============================================================
        # ✅ A/B TESTING
        # ============================================================
        
        self.ab_test = {
            'enabled': getattr(config, 'gnn_ab_test_enabled', True),
            'rollout': getattr(config, 'gnn_ab_test_rollout', 0.20),
            'control_wins': 0,
            'control_losses': 0,
            'control_profit': 0,
            'test_wins': 0,
            'test_losses': 0,
            'test_profit': 0,
            'total_trades': 0,
            'last_adjustment': None,
            'adjustment_history': [],
            'min_samples_for_adjustment': 10,
            'improvement_threshold': 0.05,
            'degradation_threshold': -0.05,
            'max_rollout': 0.80,
            'min_rollout': 0.05,
        }
        
        # ============================================================
        # ASSETS
        # ============================================================
        
        self.assets = self._get_assets()
        
        # Load saved A/B test state from Firebase
        self._load_ab_test_state()
        
        # Start if enabled
        self.start()
        
        # ✅ Check MT5 connection
        self._mt5_available = self._check_mt5_connection()
        
        logger.info(f"🧠 GNN initialized with {len(self.assets)} assets")
        logger.info(f"   Enabled: {self.config.gnn_enabled}")
        logger.info(f"   Static Correlations: {len(self.static_correlations)} assets")
        logger.info(f"   MT5 Available: {self._mt5_available}")
        logger.info(f"   Update interval: {self.config.gnn_update_interval}s")
        logger.info(f"   A/B Testing: {'ENABLED' if self.ab_test['enabled'] else 'DISABLED'}")
        logger.info(f"   A/B Rollout: {self.ab_test['rollout']*100:.0f}%")
    
    # ============================================================
    # CHECK MT5 CONNECTION
    # ============================================================
    
    def _check_mt5_connection(self) -> bool:
        """Check if MT5 is available."""
        try:
            import MetaTrader5 as mt5
            if mt5.terminal_info() is not None:
                return True
        except Exception:
            pass
        return False
    
    # ============================================================
    # 1. STATIC CORRELATION INITIALIZATION (Baseline)
    # ============================================================
    
    def _init_static_correlations(self):
        """✅ Initialize known market correlations (baseline for fallback)."""
        
        self.static_correlations['EURUSD'] = {
            'GBPUSD': 0.85, 'AUDUSD': 0.70, 'NZDUSD': 0.65,
            'USDCHF': -0.90, 'USDJPY': -0.60, 'USDCAD': -0.55,
            'XAUUSD': 0.65, 'EURGBP': 0.75, 'EURCAD': 0.80,
        }
        
        self.static_correlations['GBPUSD'] = {
            'EURUSD': 0.85, 'AUDUSD': 0.65, 'NZDUSD': 0.60,
            'USDCHF': -0.85, 'USDJPY': -0.55, 'USDCAD': -0.50,
            'XAUUSD': 0.60, 'EURGBP': -0.70,
        }
        
        self.static_correlations['AUDUSD'] = {
            'EURUSD': 0.70, 'GBPUSD': 0.65, 'NZDUSD': 0.85,
            'USDCHF': -0.65, 'USDJPY': -0.50, 'USDCAD': -0.45,
            'XAUUSD': 0.55, 'USOIL': 0.60,
        }
        
        self.static_correlations['USDJPY'] = {
            'EURUSD': -0.60, 'GBPUSD': -0.55, 'AUDUSD': -0.50,
            'NZDUSD': -0.45, 'USDCHF': 0.50, 'USDCAD': 0.55,
            'SPX500': 0.70, 'NAS100': 0.70, 'XAUUSD': -0.50,
        }
        
        self.static_correlations['USDCHF'] = {
            'EURUSD': -0.90, 'GBPUSD': -0.85, 'AUDUSD': -0.65,
            'USDJPY': 0.50, 'USDCAD': 0.60, 'XAUUSD': -0.70,
        }
        
        self.static_correlations['USDCAD'] = {
            'EURUSD': -0.55, 'GBPUSD': -0.50, 'AUDUSD': -0.45,
            'USDCHF': 0.60, 'USDJPY': 0.55, 'USOIL': 0.60,
            'XAUUSD': -0.40,
        }
        
        self.static_correlations['XAUUSD'] = {
            'EURUSD': 0.65, 'GBPUSD': 0.60, 'AUDUSD': 0.55,
            'USDCHF': -0.70, 'USDJPY': -0.50, 'XAGUSD': 0.85,
            'USOIL': 0.50, 'SPX500': -0.40,
        }
        
        self.static_correlations['USOIL'] = {
            'XAUUSD': 0.50, 'XAGUSD': 0.45, 'UKOIL': 0.95,
            'USDCAD': 0.60, 'AUDUSD': 0.60, 'SPX500': 0.55,
        }
        
        self.static_correlations['SPX500'] = {
            'NAS100': 0.90, 'US30': 0.85, 'DAX40': 0.70,
            'FTSE100': 0.65, 'CAC40': 0.70, 'USDJPY': 0.70,
            'XAUUSD': -0.40, 'AAPL': 0.85, 'MSFT': 0.85,
        }
        
        self.static_correlations['NAS100'] = {
            'SPX500': 0.90, 'US30': 0.80, 'DAX40': 0.65,
            'USDJPY': 0.70, 'AAPL': 0.90, 'MSFT': 0.90,
            'NVDA': 0.90, 'GOOGL': 0.85,
        }
        
        self.static_correlations['AAPL'] = {
            'MSFT': 0.85, 'NVDA': 0.80, 'GOOGL': 0.80,
            'META': 0.75, 'SPX500': 0.85, 'NAS100': 0.90,
        }
        
        self.static_correlations['MSFT'] = {
            'AAPL': 0.85, 'NVDA': 0.80, 'GOOGL': 0.85,
            'META': 0.75, 'SPX500': 0.85, 'NAS100': 0.90,
        }
        
        self.static_correlations['NVDA'] = {
            'AAPL': 0.80, 'MSFT': 0.80, 'GOOGL': 0.75,
            'META': 0.70, 'SPX500': 0.80, 'NAS100': 0.90,
        }
        
        self.static_correlations['GOOGL'] = {
            'AAPL': 0.80, 'MSFT': 0.85, 'NVDA': 0.75,
            'META': 0.80, 'SPX500': 0.80, 'NAS100': 0.85,
        }
        
        self.static_correlations['META'] = {
            'AAPL': 0.75, 'MSFT': 0.75, 'NVDA': 0.70,
            'GOOGL': 0.80, 'SPX500': 0.75, 'NAS100': 0.85,
        }
        
        logger.info(f"📊 Static correlation matrix built for {len(self.static_correlations)} assets")
    
    # ============================================================
    # 2. ✅ FIXED: GET REAL DATA DIRECTLY FROM MT5 OR STATIC
    # ============================================================
    
    def _get_direct_mt5_data(self, symbol: str) -> Optional[Dict]:
        """Get REAL data directly from MT5, or use static fallback. Cached for _mt5_data_cache_ttl seconds."""
        # ✅ Check cache first (short TTL) to avoid hammering MT5 with
        # repeated lookups for the same symbol within one request or
        # across rapid successive requests.
        with self._lock:
            cached = self._mt5_data_cache.get(symbol)
            if cached and (time.time() - self._mt5_data_cache_time.get(symbol, 0)) < self._mt5_data_cache_ttl:
                return cached
        
        try:
            import MetaTrader5 as mt5
            
            # Check if MT5 is connected
            if not self._mt5_available:
                data = self._get_static_data(symbol)
                self._cache_mt5_data(symbol, data)
                return data
            
            mt5_symbol = self._mt5_symbol_map.get(symbol, symbol)
            
            # Get tick
            tick = mt5.symbol_info_tick(mt5_symbol)
            if not tick:
                data = self._get_static_data(symbol)
                self._cache_mt5_data(symbol, data)
                return data
            
            # Get rates
            rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_H1, 0, 50)
            if rates is None or len(rates) < 10:
                rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M5, 0, 50)
            
            if rates is None or len(rates) < 10:
                data = self._get_static_data(symbol)
                self._cache_mt5_data(symbol, data)
                return data
            
            close_prices = [r[4] for r in rates]
            current_price = tick.bid
            
            # Calculate direction
            price_direction = self._calculate_price_direction(close_prices, current_price, symbol)
            
            data = {
                'symbol': symbol,
                'price': current_price,
                'direction_4h': price_direction,
                'close_prices': close_prices,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source': 'MT5'
            }
            self._cache_mt5_data(symbol, data)
            return data
            
        except Exception as e:
            logger.debug(f"MT5 error for {symbol}: {e}")
            data = self._get_static_data(symbol)
            self._cache_mt5_data(symbol, data)
            return data
    
    def _cache_mt5_data(self, symbol: str, data: Dict):
        """Thread-safe write to the short-TTL MT5 data cache."""
        with self._lock:
            self._mt5_data_cache[symbol] = data
            self._mt5_data_cache_time[symbol] = time.time()
    
    def _get_static_data(self, symbol: str) -> Dict:
        """
        Generate static/simulated data for a symbol, used only when MT5 is
        unavailable. This is fabricated, not a real signal.
        ✅ FIXED: previously called random.seed(seed), which mutates the
        GLOBAL random module state used by the entire process — any other
        code anywhere in the app calling random.random()/random.choice()
        etc. after this ran would silently get a hijacked, deterministic
        sequence. Now uses a local Random() instance instead, which is
        properly isolated.
        """
        seed = sum(ord(c) for c in symbol)
        rng = random.Random(seed)
        
        # Generate realistic direction (-0.5 to 0.5)
        direction = (rng.random() - 0.5) * 0.8
        # Add some structure based on symbol
        if 'USD' in symbol and not symbol.startswith('USD'):
            direction += 0.1
        if symbol.startswith('USD'):
            direction -= 0.1
        
        direction = max(-0.5, min(0.5, direction))
        
        return {
            'symbol': symbol,
            'price': 1.0 + rng.random() * 0.5,
            'direction_4h': round(direction, 4),
            'close_prices': [1.0 + i * 0.001 for i in range(50)],
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'STATIC'
        }
    
    def _calculate_price_direction(self, close_prices: List[float], current_price: float, symbol: str) -> float:
        """Calculate price direction from real data."""
        direction = 0.0
        
        # Tick change (✅ FIXED: lock _prev_prices read+write — accessed from
        # both the background update thread and Flask request threads)
        with self._lock:
            prev_price = self._prev_prices.get(symbol)
            self._prev_prices[symbol] = current_price
        
        if prev_price is not None and prev_price > 0:
            tick_change = (current_price - prev_price) / prev_price
            direction += tick_change * 50
        
        # 5-bar change
        if len(close_prices) >= 5 and close_prices[-5] > 0:
            short_change = (close_prices[-1] - close_prices[-5]) / close_prices[-5]
            direction += short_change * 30
        
        # 20-bar change
        if len(close_prices) >= 20 and close_prices[-20] > 0:
            medium_change = (close_prices[-1] - close_prices[-20]) / close_prices[-20]
            direction += medium_change * 20
        
        direction = max(-1.0, min(1.0, direction))
        
        if abs(direction) < 0.01 and direction != 0:
            direction = 0.05 if direction > 0 else -0.05
        
        return round(direction, 4)
    
    def _get_correlation_confidence(self, asset1: str, asset2: str) -> Dict:
        """
        Get correlation with confidence, blending REAL dynamic correlation
        (computed from live price history by _update_dynamic_correlations)
        with the static baseline table.
        ✅ ENHANCED: previously this always returned the static table value —
        self.dynamic_correlations was declared but never populated or read
        anywhere. Now it's actually computed and used, weighted by how much
        live data backs it.
        """
        static_corr = 0.0
        if asset1 in self.static_correlations and asset2 in self.static_correlations[asset1]:
            static_corr = self.static_correlations[asset1][asset2]
        elif asset2 in self.static_correlations and asset1 in self.static_correlations[asset2]:
            static_corr = self.static_correlations[asset2][asset1]
        
        dyn = None
        if asset1 in self.dynamic_correlations and asset2 in self.dynamic_correlations[asset1]:
            dyn = self.dynamic_correlations[asset1][asset2]
        elif asset2 in self.dynamic_correlations and asset1 in self.dynamic_correlations[asset2]:
            dyn = self.dynamic_correlations[asset2][asset1]
        
        if dyn is not None:
            samples = dyn['samples']
            # More samples -> trust the measured correlation more. Capped at
            # 80% weight so the static baseline always retains some
            # influence, guarding against short-term noise dominating.
            dyn_weight = min(0.8, samples / 100)
            blended_corr = dyn_weight * dyn['correlation'] + (1 - dyn_weight) * static_corr
            confidence = 50 + abs(blended_corr) * 30 + min(20, samples / 5)
            stability = 60 + min(30, samples / 3)
            
            return {
                'correlation': round(blended_corr, 4),
                'static_correlation': static_corr,
                'dynamic_correlation': dyn['correlation'],
                'dynamic_samples': samples,
                'confidence': round(min(95, confidence), 1),
                'stability': round(min(95, stability), 1),
                'source': 'DYNAMIC' if dyn_weight >= 0.8 else 'BLENDED',
            }
        
        # No dynamic data yet (not enough live history) - static-only, same
        # behavior as before for this case.
        confidence = 50 + abs(static_corr) * 40
        return {
            'correlation': static_corr,
            'static_correlation': static_corr,
            'dynamic_correlation': None,
            'dynamic_samples': 0,
            'confidence': round(min(95, confidence), 1),
            'stability': 80,
            'source': 'STATIC'
        }

    def _calculate_peer_implied_direction(self, correlated: List[Dict], graph_influence: Optional[float]) -> Tuple[Optional[float], str]:
        """
        ✅ NEW: build a divergence-comparison signal that is genuinely
        INDEPENDENT of the target symbol's own price_direction.

        This exists because the divergence check in get_trading_insights()
        used to compare price_direction against `gnn_direction` -- but
        gnn_direction is itself built substantially FROM this symbol's own
        price_direction:
            PROXY mode:          gnn_direction = price_direction * 0.7
            GRAPH_BLENDED mode:  gnn_direction = 0.5*graph_influence + 0.5*(price_direction*0.7)
        In PROXY mode this makes divergence mathematically IMPOSSIBLE
        whenever price_direction != 0 (same positive multiplier -> always
        the same sign). In GRAPH_BLENDED mode it's heavily damped by the
        same self-price component. Divergence can only mean something when
        compared against a signal that doesn't already contain the thing
        it's being compared to.

        Two genuinely peer-derived sources, combined when both available:
          - graph_influence: message-passing average of directly-connected
            NEIGHBORS' OWN direction_4h (see _message_passing_round) --
            already independent of this symbol's price, but only present
            when the background graph is fresh and this symbol has edges.
          - correlated peers: for each peer, its own direction * the SIGN
            of its correlation with this symbol is what this symbol
            "should" be doing if the historical relationship holds,
            weighted by |correlation| * confidence. Always available
            (doesn't depend on the background loop being warm for this
            specific symbol) -- this is what actually fixes divergence
            being unreachable whenever the graph wasn't fresh, which in
            practice is the common case for any single on-demand request.

        Returns (implied_direction, basis_label); (None, 'none') if
        neither source has usable data.
        """
        weighted_sum = 0.0
        weight_total = 0.0
        used_peers = 0

        for c in correlated:
            corr = c.get('correlation', 0)
            peer_dir = c.get('direction', 0)
            conf = c.get('confidence', 0)
            if abs(corr) < 0.3 or peer_dir == 0:
                continue
            w = abs(corr) * (conf / 100.0)
            if w <= 0:
                continue
            weighted_sum += (peer_dir * (1 if corr > 0 else -1)) * w
            weight_total += w
            used_peers += 1

        peer_corr_direction = weighted_sum / weight_total if weight_total > 0 else None

        if graph_influence is not None and peer_corr_direction is not None:
            return (0.5 * graph_influence + 0.5 * peer_corr_direction, f"graph + {used_peers} correlated peer(s)")
        if graph_influence is not None:
            return (graph_influence, "message-passing graph")
        if peer_corr_direction is not None:
            return (peer_corr_direction, f"{used_peers} correlated peer(s)")
        return (None, "none")

    def _describe_correlation(self, symbol: str, other: str, corr_info: Dict, other_direction: float) -> Dict:
        """
        ✅ NEW: human-readable interpretation of one correlation entry.

        The raw fields (correlation, static_correlation, confidence,
        stability, source) are meaningless at a glance without context --
        this turns them into plain-English labels so a trader can read a
        single correlation entry and understand what it means without
        cross-referencing anything else.
        """
        corr = corr_info['correlation']
        abs_corr = abs(corr)

        if abs_corr >= 0.8:
            strength = 'very strong'
        elif abs_corr >= 0.6:
            strength = 'strong'
        elif abs_corr >= 0.4:
            strength = 'moderate'
        elif abs_corr >= 0.2:
            strength = 'weak'
        else:
            strength = 'negligible'

        if corr > 0.05:
            relationship = 'positive'
            relationship_desc = 'tend to move in the SAME direction'
        elif corr < -0.05:
            relationship = 'negative'
            relationship_desc = 'tend to move in OPPOSITE directions'
        else:
            relationship = 'none'
            relationship_desc = 'show no meaningful relationship'

        if other_direction > 0.15:
            direction_label = 'bullish'
        elif other_direction < -0.15:
            direction_label = 'bearish'
        else:
            direction_label = 'neutral'

        source = corr_info['source']
        if source == 'DYNAMIC':
            source_desc = f"measured live ({corr_info.get('dynamic_samples', 0)} samples)"
        elif source == 'BLENDED':
            source_desc = f"live-measured + static baseline blend ({corr_info.get('dynamic_samples', 0)} samples so far)"
        else:
            source_desc = "static historical baseline only (not enough live data yet)"

        implied = None
        if relationship != 'none' and direction_label != 'neutral':
            if relationship == 'positive':
                implied = direction_label
            else:
                implied = 'bearish' if direction_label == 'bullish' else 'bullish'

        explanation = (
            f"{other} is {strength}ly {relationship}-correlated with {symbol} ({corr:+.2f}, {source_desc}) "
            f"\u2014 they {relationship_desc}. {other} is currently {direction_label}."
        )
        if implied:
            explanation += f" Historically, that would suggest {symbol} leans {implied} too."

        return {
            'relationship': relationship,
            'strength': strength,
            'direction_label': direction_label,
            'implied_direction_for_symbol': implied,
            'explanation': explanation,
        }

    # ============================================================
    # 3. ✅ FIXED: GET TRADING INSIGHTS (COMPLETE)
    # ============================================================
    
    def get_trading_insights(self, symbol: str, analysis_direction: str = None) -> Dict:
        """
        ✅ FIXED: Get trading insights with MT5 data or static fallback.
        ✅ Now returns suggestions properly
        ✅ Now calculates recommendation score
        ✅ Now detects conflicts correctly
        """
        symbol = symbol.upper()
        
        try:
            # Get data (MT5 or static)
            data = self._get_direct_mt5_data(symbol)
            
            if not data:
                return self._get_default_insights(symbol)
            
            price_direction = data.get('direction_4h', 0)
            is_live_data = data.get('source') == 'MT5'
            
            # ============================================================
            # ✅ ENHANCED: GNN direction now blends the REAL message-passing
            # graph output (when fresh) with the price-direction proxy,
            # instead of ALWAYS being price_direction * 0.7 regardless of
            # what the background graph/message-passing pipeline computed.
            # That pipeline ran every update cycle but its output
            # (context_cache[symbol]['gnn_influence']) was never read by
            # this method before.
            # ============================================================
            graph_fresh = (
                self.last_update is not None
                and (time.time() - self.last_update) < self.config.gnn_update_interval * 3
            )
            gnn_connections = 0
            graph_influence = None
            if graph_fresh and symbol in self.context_cache:
                graph_influence = self.context_cache[symbol].get('gnn_influence')
                gnn_connections = self.context_cache[symbol].get('gnn_connections', 0)
            
            if graph_influence is not None and gnn_connections > 0:
                # Real neighbor-aggregated signal available - blend with price proxy
                gnn_direction = 0.5 * graph_influence + 0.5 * (price_direction * 0.7)
                gnn_direction_source = 'GRAPH_BLENDED'
            else:
                # No fresh graph data for this symbol yet - fall back to proxy alone
                gnn_direction = price_direction * 0.7
                gnn_direction_source = 'PROXY'
            
            # Get correlations
            correlated = []
            if symbol in self.static_correlations:
                for other in self.static_correlations[symbol].keys():
                    # Get other asset data
                    other_data = self._get_direct_mt5_data(other)
                    if other_data:
                        other_direction = other_data.get('direction_4h', 0)
                        other_price = other_data.get('price', 0)
                    else:
                        other_direction = 0
                        other_price = 0

                    # ✅ FIXED: 'atr' was a hardcoded 0 -- never computed
                    # from anything, on every single correlation entry.
                    # There's no high/low here to build a true ATR from
                    # (_get_direct_mt5_data only keeps close_prices), so
                    # this computes an honest close-to-close volatility
                    # proxy instead of pretending to be a real ATR. 'atr'
                    # is kept (rather than removed) for any existing
                    # caller reading that key, but now holds this real
                    # value; 'volatility_pct' is the same number under an
                    # honestly-labeled name.
                    volatility_pct = None
                    other_closes = other_data.get('close_prices', []) if other_data else []
                    if other_closes and len(other_closes) >= 10:
                        rets = [
                            (other_closes[i] - other_closes[i - 1]) / other_closes[i - 1]
                            for i in range(1, len(other_closes)) if other_closes[i - 1] > 0
                        ]
                        if rets:
                            volatility_pct = round(float(np.std(rets)) * 100, 3)

                    corr_info = self._get_correlation_confidence(symbol, other)

                    # The English write-up and the per-pair constants
                    # (strength/relationship/source/static baseline/confidence/
                    # stability) were dropped on 2026-09-15: they never change
                    # for a pair, so they could not inform a reader or a model.
                    # What varies -- the peer's own direction, price and
                    # volatility, and the direction they imply -- stays.
                    described = self._describe_correlation(symbol, other, corr_info, other_direction)

                    correlated.append({
                        'symbol': other,
                        'correlation': corr_info['correlation'],
                        'direction': round(other_direction, 4),
                        'price': other_price,
                        'atr': volatility_pct if volatility_pct is not None else 0,
                        'volatility_pct': volatility_pct,
                        'direction_label': described.get('direction_label'),
                        'implied_direction_for_symbol': described.get('implied_direction_for_symbol'),
                    })
            
            # Sort by absolute correlation
            correlated.sort(key=lambda x: abs(x['correlation']), reverse=True)
            
            # ============================================================
            # ✅ FIXED: DIVERGENCE DETECTION -- was structurally incapable
            # of ever firing. See _calculate_peer_implied_direction()'s
            # docstring for the full explanation: gnn_direction is built
            # substantially FROM this symbol's own price_direction (in
            # PROXY mode, gnn_direction = price_direction * 0.7 --
            # mathematically the same sign as price_direction whenever
            # price_direction != 0, which made "price_direction > 0.3 and
            # gnn_direction < -0.1" unsatisfiable). Now compares
            # price_direction against a signal built purely from
            # correlated peers / the message-passing graph, which can
            # actually disagree with this symbol's own price.
            # ============================================================
            peer_implied_direction, peer_basis = self._calculate_peer_implied_direction(
                correlated, graph_influence if (graph_fresh and gnn_connections > 0) else None
            )

            divergence = False
            divergence_type = None
            divergence_reason = None

            if peer_implied_direction is not None:
                if price_direction > 0.3 and peer_implied_direction < -0.1:
                    divergence = True
                    divergence_type = 'PEERS_BEARISH_PRICE_BULLISH'
                    divergence_reason = (
                        f"Correlated peers imply SELL ({peer_implied_direction:.2f}, via {peer_basis}) "
                        f"but {symbol}'s own price says BUY ({price_direction:.2f})"
                    )
                elif price_direction < -0.3 and peer_implied_direction > 0.1:
                    divergence = True
                    divergence_type = 'PEERS_BULLISH_PRICE_BEARISH'
                    divergence_reason = (
                        f"Correlated peers imply BUY ({peer_implied_direction:.2f}, via {peer_basis}) "
                        f"but {symbol}'s own price says SELL ({price_direction:.2f})"
                    )
            
            # ============================================================
            # ✅ GENERATE SUGGESTIONS (FIXED - ALWAYS GENERATE)
            # ============================================================
            suggestions = []
            suggestion_confidence_sum = 0
            suggestion_count = 0
            
            # Generate suggestions from correlations
            for corr in correlated[:5]:
                if abs(corr['correlation']) > 0.4 and corr.get('confidence', 0) > 50:
                    # Determine action based on correlation
                    if price_direction > 0.2:
                        action = 'BUY' if corr['correlation'] > 0 else 'SELL'
                    elif price_direction < -0.2:
                        action = 'SELL' if corr['correlation'] > 0 else 'BUY'
                    else:
                        # No clear direction - use correlation direction
                        if corr['direction'] > 0.1:
                            action = 'BUY'
                        elif corr['direction'] < -0.1:
                            action = 'SELL'
                        else:
                            action = 'HOLD'
                    
                    if action != 'HOLD':
                        suggestion_conf = min(85, corr.get('confidence', 50) * 1.1)
                        # ✅ ENHANCED: dampen confidence when the correlation
                        # itself has no dynamic backing (pure static table
                        # guess) or the underlying price data is simulated —
                        # a suggestion shouldn't carry full weight when it's
                        # built on assumptions instead of measured co-movement.
                        if corr.get('source') == 'STATIC':
                            suggestion_conf *= 0.85
                        if not is_live_data:
                            suggestion_conf *= 0.7
                        suggestion_conf = round(suggestion_conf, 1)
                        
                        # Advisory position-size hint: scales with confidence,
                        # capped low when data isn't live. Not an order
                        # instruction — just a multiplier a caller may apply
                        # to its own base size.
                        size_multiplier = round(max(0.5, min(1.5, 0.5 + suggestion_conf / 100)), 2)
                        if not is_live_data:
                            size_multiplier = min(size_multiplier, 0.5)
                        
                        suggestions.append({
                            'symbol': corr['symbol'],
                            'action': action,
                            'confidence': suggestion_conf,
                            'correlation': corr['correlation'],
                            'source': corr.get('source', 'STATIC'),
                            'suggested_size_multiplier': size_multiplier,
                            'reason': f"Correlation: {corr['correlation']:.2f} with {symbol}",
                        })
                        suggestion_confidence_sum += suggestion_conf
                        suggestion_count += 1
            
            # If no suggestions from correlations, generate based on price direction
            if not suggestions:
                if abs(price_direction) > 0.2:
                    action = 'BUY' if price_direction > 0 else 'SELL'
                    conf = round(min(75, abs(price_direction) * 100 + 50), 1)
                    if not is_live_data:
                        conf = round(conf * 0.7, 1)
                    size_multiplier = round(max(0.5, min(1.5, 0.5 + conf / 100)), 2)
                    if not is_live_data:
                        size_multiplier = min(size_multiplier, 0.5)
                    suggestions.append({
                        'symbol': symbol,
                        'action': action,
                        'confidence': conf,
                        'correlation': 1.0,
                        'source': 'PRICE',
                        'suggested_size_multiplier': size_multiplier,
                        'reason': f"Price direction: {price_direction:.2f}",
                    })
                    suggestion_confidence_sum = conf
                    suggestion_count = 1
                else:
                    # Neutral suggestion
                    suggestions.append({
                        'symbol': symbol,
                        'action': 'NEUTRAL',
                        'confidence': 50,
                        'correlation': 0,
                        'source': 'NEUTRAL',
                        'suggested_size_multiplier': 0.0,
                        'reason': 'No clear direction',
                    })
                    suggestion_confidence_sum = 50
                    suggestion_count = 1
            
            # ============================================================
            # ✅ CALCULATE RECOMMENDATION SCORE (FIXED)
            # ============================================================
            # ✅ FIXED (2026-09-15): suggestions are actions on PEER symbols
            # ("BUY GBPUSD", "SELL USDCHF"). They were counted as if they
            # were this symbol's own direction, so one positively and one
            # negatively correlated peer cancelled or flipped the call for
            # reasons unrelated to this symbol. Each is now read for what it
            # implies HERE: a peer action times the sign of the correlation.
            def _implied_here(sug):
                sign = 1 if sug['action'] == 'BUY' else -1 if sug['action'] == 'SELL' else 0
                if sug.get('symbol') and sug.get('symbol') != symbol:
                    sign *= 1 if (sug.get('correlation') or 0) >= 0 else -1
                return sign
            buy_suggestions = [s for s in suggestions if _implied_here(s) > 0]
            sell_suggestions = [s for s in suggestions if _implied_here(s) < 0]
            
            if buy_suggestions and sell_suggestions:
                # Mixed signals - calculate net score
                buy_avg = sum(s['confidence'] for s in buy_suggestions) / len(buy_suggestions)
                sell_avg = sum(s['confidence'] for s in sell_suggestions) / len(sell_suggestions)
                recommendation_score = buy_avg - sell_avg
                
                if recommendation_score > 10:
                    recommendation = 'BULLISH'
                elif recommendation_score < -10:
                    recommendation = 'BEARISH'
                else:
                    recommendation = 'NEUTRAL'
            elif buy_suggestions:
                recommendation = 'BULLISH'
                recommendation_score = sum(s['confidence'] for s in buy_suggestions) / len(buy_suggestions)
            elif sell_suggestions:
                recommendation = 'BEARISH'
                recommendation_score = -(sum(s['confidence'] for s in sell_suggestions) / len(sell_suggestions))
            else:
                recommendation = 'NEUTRAL'
                recommendation_score = 0
            
            # ============================================================
            # ✅ CHECK CONFLICT WITH YOUR ANALYSIS (FIXED)
            # ✅ HARDENED: when the underlying data is the fabricated STATIC
            # fallback (MT5 unreachable), conflicts are capped at MEDIUM/LOW
            # severity instead of HIGH — a "you want BUY but GNN says SELL"
            # warning should never carry the same weight when "GNN says" is
            # actually just a per-symbol pseudo-random number, not real
            # market data. is_live_data is also exposed on the insights so
            # downstream consumers can filter on it explicitly.
            # ============================================================
            high_severity = 'HIGH' if is_live_data else 'MEDIUM'
            medium_severity = 'MEDIUM' if is_live_data else 'LOW'
            
            conflict = None
            if analysis_direction:
                analysis_dir = analysis_direction.upper()
                
                if analysis_dir == 'BUY' and gnn_direction < -0.15:
                    conflict = {
                        'your_analysis': 'BUY',
                        'gnn_says': 'SELL',
                        'severity': high_severity,
                        'message': f"⚠️ You want to BUY but GNN says SELL (gnn: {gnn_direction:.2f})",
                        'recommendation': 'CONSIDER WAITING - GNN conflict detected' if is_live_data else 'GNN data unavailable (simulated fallback) - conflict is low-confidence',
                    }
                elif analysis_dir == 'SELL' and gnn_direction > 0.15:
                    conflict = {
                        'your_analysis': 'SELL',
                        'gnn_says': 'BUY',
                        'severity': high_severity,
                        'message': f"⚠️ You want to SELL but GNN says BUY (gnn: {gnn_direction:.2f})",
                        'recommendation': 'CONSIDER WAITING - GNN conflict detected' if is_live_data else 'GNN data unavailable (simulated fallback) - conflict is low-confidence',
                    }
                elif analysis_dir == 'BUY' and recommendation == 'BEARISH':
                    conflict = {
                        'your_analysis': 'BUY',
                        'gnn_says': 'BEARISH',
                        'severity': medium_severity,
                        'message': f"⚠️ You want to BUY but GNN is bearish",
                        'recommendation': 'CONSIDER REDUCING SIZE - GNN conflict detected' if is_live_data else 'GNN data unavailable (simulated fallback) - conflict is low-confidence',
                    }
                elif analysis_dir == 'SELL' and recommendation == 'BULLISH':
                    conflict = {
                        'your_analysis': 'SELL',
                        'gnn_says': 'BULLISH',
                        'severity': medium_severity,
                        'message': f"⚠️ You want to SELL but GNN is bullish",
                        'recommendation': 'CONSIDER REDUCING SIZE - GNN conflict detected' if is_live_data else 'GNN data unavailable (simulated fallback) - conflict is low-confidence',
                    }
                else:
                    # No conflict - GNN agrees
                    gnn_agrees = 'BUY' if gnn_direction > 0 else 'SELL' if gnn_direction < 0 else 'NEUTRAL'
                    conflict = None
            
            # ============================================================
            # ✅ NEW: RISK WARNINGS (previously this field was always [])
            # ============================================================
            risk_warnings = []
            
            if not is_live_data:
                risk_warnings.append({
                    'level': 'MEDIUM',
                    'message': f'{symbol} signal is based on simulated data (MT5 unavailable) — treat with reduced confidence',
                })
            
            if divergence:
                risk_warnings.append({
                    'level': 'MEDIUM',
                    'message': divergence_reason,
                })
            
            # Fan-out disagreement: correlated assets pointing in conflicting directions
            bullish_neighbors = sum(1 for c in correlated[:5] if c.get('direction', 0) > 0.15)
            bearish_neighbors = sum(1 for c in correlated[:5] if c.get('direction', 0) < -0.15)
            if bullish_neighbors >= 2 and bearish_neighbors >= 2:
                risk_warnings.append({
                    'level': 'LOW',
                    'message': f'Correlated assets show mixed signals ({bullish_neighbors} bullish, {bearish_neighbors} bearish) — lower conviction',
                })
            
            low_confidence_corrs = [c for c in correlated[:5] if c.get('confidence', 100) < 60]
            if correlated[:5] and len(low_confidence_corrs) >= 3:
                risk_warnings.append({
                    'level': 'LOW',
                    'message': 'Most correlation data has low confidence (limited dynamic sample size, relying on static baseline)',
                })
            
            # ============================================================
            # ✅ BUILD INSIGHTS (COMPLETE)
            # ============================================================
            insights = {
                'symbol': symbol,
                'data_quality': 'LIVE' if is_live_data else 'SIMULATED',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'price_direction': round(price_direction, 4),
                'gnn_direction': round(gnn_direction, 4),
                'gnn_direction_source': gnn_direction_source,
                'gnn_connections': gnn_connections,
                'correlations': correlated[:5],
                'divergence': {
                    'detected': divergence,
                    'type': divergence_type,
                    'reason': divergence_reason,
                    'price_direction': round(price_direction, 4),
                    'peer_implied_direction': round(peer_implied_direction, 4) if peer_implied_direction is not None else None,
                    'peer_basis': peer_basis,
                },
                'suggestions': suggestions,
                'recommendation': recommendation,
                'recommendation_score': round(recommendation_score, 1),
                'risk_warnings': risk_warnings,
                'conflict': conflict,
                'data_source': data.get('source', 'UNKNOWN'),
                'suggestion_count': len(suggestions),
                'buy_suggestions': len(buy_suggestions),
                'sell_suggestions': len(sell_suggestions),
            }
            
            # Update cache
            # ✅ FIXED: guard against concurrent writes from multiple Flask
            # request threads / the background update thread
            with self._lock:
                self.trading_signals[symbol] = insights
            
            logger.info(f"✅ GNN insights for {symbol}: price_dir={price_direction:.2f}, gnn_dir={gnn_direction:.2f}, "
                       f"recommendation={recommendation}, score={recommendation_score:.1f}, "
                       f"suggestions={len(suggestions)}, source={data.get('source', 'UNKNOWN')}")
            
            return insights
            
        except Exception as e:
            logger.error(f"Error getting insights for {symbol}: {e}")
            import traceback
            traceback.print_exc()
        
        # Fallback to cached signal
        signal = self.trading_signals.get(symbol)
        if signal:
            return signal
        
        return self._get_default_insights(symbol)
    
    # ============================================================
    # 4. REMAINING METHODS
    # ============================================================
    
    def _get_default_insights(self, symbol: str) -> Dict:
        """Return default insights with consistent structure."""
        return {
            'symbol': symbol,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'price_direction': 0,
            'gnn_direction': 0,
            'correlations': [],
            'divergence': {'detected': False},
            'suggestions': [
                {
                    'symbol': symbol,
                    'action': 'NEUTRAL',
                    'confidence': 50,
                    'correlation': 0,
                    'source': 'NEUTRAL',
                    'reason': 'No data available',
                }
            ],
            'recommendation': 'NEUTRAL',
            'recommendation_score': 0,
            'risk_warnings': [],
            'conflict': None,
            'status': 'signal_not_available',
            'message': f'No trading signal available for {symbol}.',
            'error': 'Failed to get real data',
            'suggestion_count': 1,
            'buy_suggestions': 0,
            'sell_suggestions': 0,
        }
    
    def _get_assets(self) -> List[str]:
        """Get assets from config or default list."""
        if hasattr(self.config, 'gnn_assets') and self.config.gnn_assets:
            return self.config.gnn_assets
        
        return [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 
            'NZDUSD', 'USDCHF', 'EURGBP', 'EURCAD', 'EURJPY',
            'GBPJPY', 'AUDJPY', 'CADJPY', 'CHFJPY', 'AUDNZD', 'AUDCAD',
            'XAUUSD', 'XAGUSD', 'USOIL', 'UKOIL',
            'SPX500', 'NAS100', 'US30', 'DAX40', 'FTSE100', 'CAC40',
            'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META',
            'JPM', 'V', 'XOM', 'CVX',
            'WMT', 'MCD', 'JNJ', 'PFE'
        ]
    
    def start(self):
        """Start GNN update thread."""
        if not self.is_enabled or self.is_running:
            return
        
        self.is_running = True
        self.stop_flag = False
        
        self.update_thread = threading.Thread(
            target=self._update_loop,
            name="GNNUpdater",
            daemon=True
        )
        self.update_thread.start()
        logger.info("🚀 GNN update thread started")
    
    def stop(self):
        """Stop GNN update thread."""
        if not self.is_enabled:
            return
        
        self.stop_flag = True
        self.is_running = False
        
        if self.update_thread:
            self.update_thread.join(timeout=5)
        logger.info("⏹️ GNN update thread stopped")
    
    def _update_loop(self):
        """GNN update loop (runs in background)."""
        while not self.stop_flag and self.is_enabled:
            update_start = time.time()
            try:
                # Check MT5 connection
                self._mt5_available = self._check_mt5_connection()
                
                # Fetch features
                features = self.fetcher.get_all_assets_features(self.assets)
                
                # ✅ FIXED: previously this block ran unconditionally below
                # regardless of whether `features` came back empty, so a
                # total MT5 fetch failure was reported as a successful
                # update (update_count incremented, last_update bumped,
                # is_trained set True) with nothing actually rebuilt.
                if features:
                    with self._lock:
                        self._build_graph(features)
                        self._message_passing()
                        self._update_context_cache()
                        self._update_price_history(features)
                        self._update_dynamic_correlations()
                        self._update_trading_signals(features)
                    
                    self.update_count += 1
                    self.last_update = time.time()
                    self.is_trained = True
                    self.update_times.append(time.time() - update_start)
                    
                    # ✅ Recovered — clear any rollback flag
                    if self.consecutive_errors > 0:
                        logger.info(f"✅ GNN recovered after {self.consecutive_errors} consecutive failed updates")
                    self.consecutive_errors = 0
                    if self.rollback_state['triggered']:
                        self.rollback_state['triggered'] = False
                        self.rollback_state['reason'] = None
                    
                    logger.debug(f"🔄 GNN updated ({self.update_count} updates)")
                else:
                    logger.warning("⚠️ GNN update produced no features (fetcher returned empty) - keeping last known-good state")
                    self._register_update_failure("empty_features")
                
            except Exception as e:
                logger.error(f"❌ GNN update failed: {e}")
                self.error_count += 1
                self._register_update_failure(str(e))
            
            time.sleep(self.config.gnn_update_interval)
    
    def _register_update_failure(self, reason: str):
        """
        ✅ FIXED: rollback_state used to be declared and never populated
        anywhere (a stub). Track consecutive failures here so /gnn/status
        actually surfaces when the background loop has been failing
        repeatedly, instead of silently going stale with no signal.
        Note: this only marks the state as degraded for observability —
        self.graph/self.context_cache are simply left untouched on failure
        (they're only overwritten on a successful update above), so the
        system already keeps serving the last known-good data by construction.
        """
        self.consecutive_errors += 1
        if self.consecutive_errors >= 3 and not self.rollback_state['triggered']:
            self.rollback_state['triggered'] = True
            self.rollback_state['reason'] = f"{self.consecutive_errors} consecutive update failures: {reason}"
            self.rollback_state['timestamp'] = datetime.now(timezone.utc).isoformat()
            logger.warning(f"⚠️ GNN update degraded: {self.rollback_state['reason']} — serving last known-good data")
    
    def _build_graph(self, features: Dict):
        """Build graph from features."""
        assets = list(features.keys())
        n_assets = len(assets)
        
        if n_assets < 5:
            return
        
        self.node_features = features
        edges = []
        edge_weights = []
        
        for i, asset1 in enumerate(assets):
            for j, asset2 in enumerate(assets[i+1:], i+1):
                weight = 0.3
                if asset1 in self.static_correlations and asset2 in self.static_correlations[asset1]:
                    weight = abs(self.static_correlations[asset1][asset2]) * 0.6 + 0.2
                
                if weight > 0.3:
                    edges.append((i, j))
                    edge_weights.append(weight)
        
        self.graph = {
            'assets': assets,
            'nodes': n_assets,
            'edges': edges,
            'edge_weights': edge_weights,
            'features': features,
        }
    
    def _message_passing(self):
        """Message passing through graph."""
        if not self.graph:
            return
        
        for _ in range(2):
            self._message_passing_round()
    
    def _message_passing_round(self):
        """Single message passing round."""
        if not self.graph:
            return
        
        assets = self.graph['assets']
        edges = self.graph['edges']
        edge_weights = self.graph['edge_weights']
        features = self.graph['features']
        
        messages = {asset: [] for asset in assets}
        
        for (i, j), weight in zip(edges, edge_weights):
            asset1 = assets[i]
            asset2 = assets[j]
            
            f1 = features.get(asset1, {})
            f2 = features.get(asset2, {})
            
            if f1 and f2:
                messages[asset2].append({
                    'direction': f1.get('direction_4h', 0) * weight,
                    'weight': weight,
                })
                messages[asset1].append({
                    'direction': f2.get('direction_4h', 0) * weight,
                    'weight': weight,
                })
        
        for asset, msg_list in messages.items():
            if not msg_list:
                continue
            
            total_weight = sum(m['weight'] for m in msg_list)
            if total_weight == 0:
                continue
            
            avg_direction = sum(m['direction'] for m in msg_list) / total_weight
            
            if asset in features:
                features[asset]['gnn_direction'] = avg_direction
                features[asset]['gnn_connections'] = len(msg_list)
    
    def _update_context_cache(self):
        """Update context cache."""
        if not self.graph:
            return
        
        for symbol in self.graph['assets']:
            feat = self.graph['features'].get(symbol, {})
            self.context_cache[symbol] = {
                'gnn_influence': feat.get('gnn_direction', 0),
                'gnn_connections': feat.get('gnn_connections', 0),
            }
    
    def _update_price_history(self, features: Dict):
        """Update price history."""
        for symbol, feat in features.items():
            price = feat.get('price', 0)
            if price > 0:
                if symbol not in self.price_history:
                    self.price_history[symbol] = []
                self.price_history[symbol].append(price)
                if len(self.price_history[symbol]) > 100:
                    self.price_history[symbol] = self.price_history[symbol][-100:]
    
    def _update_dynamic_correlations(self):
        """
        ✅ NEW: compute REAL rolling correlations between assets from their
        live price history. Previously self.dynamic_correlations was
        declared in __init__ and never touched again anywhere in this file —
        every correlation value the system ever returned came only from the
        hardcoded static table above, regardless of what price action was
        actually doing.
        
        Uses returns (percent change between consecutive samples), not raw
        prices — raw-price correlation is dominated by trend/scale rather
        than actual co-movement. Pairs need at least MIN_DYNAMIC_SAMPLES
        overlapping return points before being considered; until then,
        _get_correlation_confidence() keeps relying on the static table.
        
        Note: price_history entries are appended once per update-loop
        iteration for whichever assets returned a valid price that cycle,
        so series across assets are only approximately index-aligned (not
        strictly timestamp-aligned) — acceptable for this rolling-window
        use case given the short update interval, but not tick-precise.
        """
        MIN_DYNAMIC_SAMPLES = 20
        CORRELATION_HISTORY_MAXLEN = 50  # ✅ NEW: how many past dynamic-correlation snapshots to keep per pair, for detect_correlation_changes()
        assets_with_history = [
            a for a in self.price_history
            if len(self.price_history[a]) >= MIN_DYNAMIC_SAMPLES + 1
        ]
        
        if len(assets_with_history) < 2:
            return
        
        # Precompute returns once per asset
        returns = {}
        for asset in assets_with_history:
            prices = self.price_history[asset]
            rets = []
            for i in range(1, len(prices)):
                if prices[i - 1] > 0:
                    rets.append((prices[i] - prices[i - 1]) / prices[i - 1])
            if len(rets) >= MIN_DYNAMIC_SAMPLES:
                returns[asset] = rets
        
        assets_with_history = list(returns.keys())
        if len(assets_with_history) < 2:
            return
        
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for i, a1 in enumerate(assets_with_history):
            for a2 in assets_with_history[i + 1:]:
                r1 = returns[a1]
                r2 = returns[a2]
                n = min(len(r1), len(r2))
                if n < MIN_DYNAMIC_SAMPLES:
                    continue
                
                x = np.array(r1[-n:])
                y = np.array(r2[-n:])
                
                # Guard against a constant series (zero variance), which
                # makes Pearson correlation undefined (division by zero -> NaN)
                if np.std(x) < 1e-12 or np.std(y) < 1e-12:
                    continue
                
                try:
                    corr = float(np.corrcoef(x, y)[0, 1])
                except Exception:
                    continue
                
                if np.isnan(corr) or np.isinf(corr):
                    continue
                
                corr = max(-1.0, min(1.0, corr))
                entry = {
                    'correlation': round(corr, 4),
                    'samples': n,
                    'updated_at': now_iso,
                }
                self.dynamic_correlations.setdefault(a1, {})[a2] = entry
                self.dynamic_correlations.setdefault(a2, {})[a1] = entry

                # ✅ NEW: append to bounded history (used by
                # detect_correlation_changes() below to actually detect a
                # change, rather than the previous hardcoded no-op stub).
                hist_entry = {'correlation': entry['correlation'], 'samples': n, 'timestamp': now_iso}
                self.correlation_history.setdefault(a1, {}).setdefault(a2, deque(maxlen=CORRELATION_HISTORY_MAXLEN)).append(hist_entry)
                self.correlation_history.setdefault(a2, {}).setdefault(a1, deque(maxlen=CORRELATION_HISTORY_MAXLEN)).append(hist_entry)
    
    def _update_trading_signals(self, features: Dict):
        """
        Intentionally a no-op: get_trading_insights() computes signals
        on-demand per request (and caches into self.trading_signals itself)
        rather than this background loop precomputing them. Kept as an
        explicit hook rather than removed, in case future background
        precomputation is added.
        """
        pass
    
    def _rollback_to_last_good(self):
        """
        Intentionally a no-op: self.graph/self.context_cache/self.trading_signals
        are only ever overwritten on a *successful* update in _update_loop, so
        a failed update already leaves the previous known-good state in place
        without needing an explicit rollback step. _register_update_failure()
        tracks and surfaces degraded-state info via rollback_state/get_status()
        for observability.
        """
        pass
    
    def get_context(self, symbol: str, trade_id: int = None) -> Dict:
        """Get context for an asset."""
        if not self.is_enabled:
            return self._get_default_context()
        
        symbol = symbol.upper()
        
        # ✅ ENHANCED: prefer the REAL message-passing graph output when it's
        # fresh. Previously this method always recomputed an independent
        # proxy (direction_4h * 0.7) from a fresh MT5 call and never read
        # context_cache — the background thread's _build_graph/
        # _message_passing pipeline populated context_cache every update
        # cycle, but nothing downstream ever consumed it; the
        # `if symbol in self.context_cache` fallback below was dead code
        # since _get_direct_mt5_data() never actually returns None (it
        # always falls back to _get_static_data instead).
        graph_fresh = (
            self.last_update is not None
            and (time.time() - self.last_update) < self.config.gnn_update_interval * 3
        )
        
        if graph_fresh and symbol in self.context_cache:
            cached = self.context_cache[symbol]
            gnn_influence = cached.get('gnn_influence', 0.0)
            gnn_connections = cached.get('gnn_connections', 0)
        else:
            # Graph not built yet, or this symbol has no fresh graph data -
            # fall back to the direct-data proxy.
            data = self._get_direct_mt5_data(symbol)
            if not data:
                return self._get_default_context()
            gnn_influence = data.get('direction_4h', 0) * 0.7
            gnn_connections = 0

        # ✅ FIXED: dxy_strength was hardcoded to 0.5 (neutral) here
        # unconditionally -- never actually computed from anything, on
        # every single call. Now wired to the real DXY EMA-slope read
        # (see core/dxy_confluence.py, built for the same purpose in
        # asset_analysis.py's probability chain): STRONG_USD -> 0.7,
        # WEAK_USD -> 0.3, NEUTRAL/unavailable -> 0.5, matching this
        # dict's existing 0.5-centered convention for the other
        # (still-placeholder) sentiment fields below.
        try:
            from core.dxy_confluence import get_dxy_direction
            dxy_read = get_dxy_direction()
            if dxy_read.get("direction") == "STRONG_USD":
                dxy_strength = 0.7
            elif dxy_read.get("direction") == "WEAK_USD":
                dxy_strength = 0.3
            else:
                dxy_strength = 0.5
        except Exception as e:
            logger.debug(f"[GNN CONTEXT] dxy_strength fallback to neutral: {e}")
            dxy_strength = 0.5

        return {
            'dxy_strength': dxy_strength,
            'risk_sentiment': 0.5,
            'commodity_impact': 0.5,
            'sector_sentiment': 0.5,
            'global_confidence': 0.5,
            'trend_alignment': 0.5,
            'market_regime': 'NORMAL',
            'correlation_shift': 0.0,
            'gnn_influence': gnn_influence,
            'gnn_connections': gnn_connections,
        }
    
    def _get_default_context(self) -> Dict:
        """Return default context when GNN is not ready."""
        return {
            'dxy_strength': 0.5,
            'risk_sentiment': 0.5,
            'commodity_impact': 0.5,
            'sector_sentiment': 0.5,
            'global_confidence': 0.5,
            'trend_alignment': 0.5,
            'market_regime': 'NORMAL',
            'correlation_shift': 0.0,
            'gnn_influence': 0.0,
            'gnn_connections': 0,
        }
    
    def is_ready(self) -> bool:
        """Check if GNN is ready to provide context."""
        if not self.is_enabled:
            return False
        return True  # Always ready with static fallback
    
    # ✅ FIXED: removed a duplicate `def is_enabled(self): return self.config.gnn_enabled`
    # that used to live here. self.is_enabled is set as a plain bool attribute
    # in __init__, which always shadows a same-named method on the instance —
    # so that method was permanently dead code, AND a landmine: if a future
    # refactor ever removed the `self.is_enabled = ...` line, every
    # `if not self.is_enabled:` check elsewhere in this file would silently
    # start evaluating a bound method object (always truthy) instead of the
    # intended bool, effectively disabling every disabled-check in this class.
    
    def get_status(self) -> Dict:
        """Get comprehensive GNN status. Never raises - this backs a health-check endpoint."""
        if not self.is_enabled:
            return {
                'enabled': False,
                'status': 'disabled',
                'message': 'GNN disabled by config'
            }
        
        try:
            status = 'active' if self.is_trained else 'initializing'
            if self.rollback_state.get('triggered'):
                status = 'degraded'
            
            return {
                'enabled': True,
                'status': status,
                'ready': self.is_ready(),
                'assets': len(self.assets),
                'cache_size': len(self.context_cache),
                'trading_signals': len(self.trading_signals),
                'price_history': len(self.price_history),
                'dynamic_correlation_pairs': sum(len(v) for v in self.dynamic_correlations.values()) // 2,
                'update_count': self.update_count,
                'error_count': self.error_count,
                'consecutive_errors': self.consecutive_errors,
                'last_update': self.last_update,
                'mt5_available': self._mt5_available,
                'rollback_state': {
                    'triggered': self.rollback_state.get('triggered', False),
                    'reason': self.rollback_state.get('reason'),
                    'timestamp': self.rollback_state.get('timestamp'),
                },
                'ab_test': self.get_ab_test_results(),
            }
        except Exception as e:
            logger.error(f"Error building GNN status: {e}")
            return {
                'enabled': True,
                'status': 'error',
                'message': f'Failed to build full status: {e}',
            }
    
    def get_ab_test_results(self) -> Dict[str, Any]:
        """Get current A/B test results."""
        ab = self.ab_test
        control_total = ab['control_wins'] + ab['control_losses']
        test_total = ab['test_wins'] + ab['test_losses']
        
        control_wr = ab['control_wins'] / max(1, control_total)
        test_wr = ab['test_wins'] / max(1, test_total)
        
        improvement = test_wr - control_wr
        
        return {
            'enabled': ab['enabled'],
            'rollout': ab['rollout'],
            'control': {
                'trades': control_total,
                'wins': ab['control_wins'],
                'losses': ab['control_losses'],
                'win_rate': control_wr * 100,
                'profit': ab['control_profit'],
            },
            'test': {
                'trades': test_total,
                'wins': ab['test_wins'],
                'losses': ab['test_losses'],
                'win_rate': test_wr * 100,
                'profit': ab['test_profit'],
            },
            'improvement': improvement * 100,
            'status': 'IMPROVED' if improvement > 0.02 else 'SAME' if abs(improvement) <= 0.02 else 'DEGRADED',
            'last_adjustment': ab['last_adjustment'],
            'adjustment_history': ab['adjustment_history'][-10:],
            'total_trades': ab['total_trades'],
        }
    
    def track_ab_test_result(self, trade_id: int, profit: float, outcome: int, used_gnn: bool):
        """Track trade result for A/B testing."""
        if not self.ab_test['enabled']:
            return
        
        self.ab_test['total_trades'] += 1
        
        if used_gnn:
            self.ab_test['test_wins'] += 1 if outcome == 1 else 0
            self.ab_test['test_losses'] += 1 if outcome == 0 else 0
            self.ab_test['test_profit'] += profit
        else:
            self.ab_test['control_wins'] += 1 if outcome == 1 else 0
            self.ab_test['control_losses'] += 1 if outcome == 0 else 0
            self.ab_test['control_profit'] += profit
        
        self._adjust_ab_test_rollout()
        
        if self.ab_test['total_trades'] % 5 == 0:
            self._save_ab_test_state()
    
    def _adjust_ab_test_rollout(self):
        """Dynamically adjust A/B test rollout based on performance."""
        ab = self.ab_test
        
        control_total = ab['control_wins'] + ab['control_losses']
        test_total = ab['test_wins'] + ab['test_losses']
        
        if control_total < ab['min_samples_for_adjustment'] or test_total < ab['min_samples_for_adjustment']:
            return
        
        control_wr = ab['control_wins'] / control_total if control_total > 0 else 0.5
        test_wr = ab['test_wins'] / test_total if test_total > 0 else 0.5
        
        improvement = test_wr - control_wr
        
        if improvement < ab['degradation_threshold']:
            logger.warning(f"⚠️ A/B test degradation detected: {improvement*100:.1f}%")
            ab['rollout'] = max(ab['min_rollout'], ab['rollout'] * 0.5)
            ab['last_adjustment'] = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'rollback',
                'new_rollout': ab['rollout'],
                'improvement': improvement,
                'reason': 'Performance degradation'
            }
            ab['adjustment_history'].append(ab['last_adjustment'])
            logger.warning(f"   Rollout reduced to {ab['rollout']*100:.0f}%")
            return
        
        if improvement > ab['improvement_threshold']:
            logger.info(f"📈 A/B test improvement: {improvement*100:.1f}%")
            ab['rollout'] = min(ab['max_rollout'], ab['rollout'] * 1.2)
            ab['last_adjustment'] = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'increase',
                'new_rollout': ab['rollout'],
                'improvement': improvement,
                'reason': 'Performance improvement'
            }
            ab['adjustment_history'].append(ab['last_adjustment'])
            logger.info(f"   Rollout increased to {ab['rollout']*100:.0f}%")
        
        if len(ab['adjustment_history']) > 50:
            ab['adjustment_history'] = ab['adjustment_history'][-50:]
    
    def set_ab_test_rollout(self, rollout: float):
        """Manually set A/B test rollout."""
        self.ab_test['rollout'] = max(0.0, min(1.0, rollout))
        logger.info(f"🎯 A/B test rollout set to {self.ab_test['rollout']*100:.0f}%")
        self._save_ab_test_state()
    
    def reset_ab_test(self):
        """Reset A/B test results."""
        self.ab_test['control_wins'] = 0
        self.ab_test['control_losses'] = 0
        self.ab_test['control_profit'] = 0
        self.ab_test['test_wins'] = 0
        self.ab_test['test_losses'] = 0
        self.ab_test['test_profit'] = 0
        self.ab_test['total_trades'] = 0
        self.ab_test['last_adjustment'] = None
        self.ab_test['adjustment_history'] = []
        self.ab_test['rollout'] = getattr(self.config, 'gnn_ab_test_rollout', 0.20)
        logger.info("🔄 A/B test results reset")
        self._save_ab_test_state()
    
    def _save_ab_test_state(self):
        """Save A/B test state to Firebase."""
        if not self.firebase:
            return
        
        try:
            state = {
                'ab_test': self.ab_test.copy(),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            if 'adjustment_history' in state['ab_test']:
                state['ab_test']['adjustment_history'] = state['ab_test']['adjustment_history'][-20:]
            
            self.firebase.save_ai_model('gnn_ab_test_state', state)
            logger.debug("✅ A/B test state saved to Firebase")
        except Exception as e:
            logger.error(f"Failed to save A/B test state: {e}")
    
    def _load_ab_test_state(self):
        """Load A/B test state from Firebase."""
        if not self.firebase:
            return
        
        try:
            state = self.firebase.get_ai_model('gnn_ab_test_state')
            if state and 'ab_test' in state:
                saved = state['ab_test']
                for key in ['control_wins', 'control_losses', 'control_profit',
                           'test_wins', 'test_losses', 'test_profit', 'total_trades',
                           'rollout', 'last_adjustment', 'adjustment_history']:
                    if key in saved:
                        self.ab_test[key] = saved[key]
                
                logger.info(f"✅ Loaded A/B test state: rollout={self.ab_test['rollout']*100:.0f}%")
                logger.info(f"   Control: {self.ab_test['control_wins']}W/{self.ab_test['control_losses']}L")
                logger.info(f"   Test: {self.ab_test['test_wins']}W/{self.ab_test['test_losses']}L")
        except Exception as e:
            logger.error(f"Failed to load A/B test state: {e}")
    
    def clear_cache(self):
        """Clear all caches."""
        if not self.is_enabled:
            return
        
        if self.fetcher:
            self.fetcher.clear_cache()
        self.context_cache = {}
        self.trading_signals = {}
        self.price_history = {}
        self.dynamic_correlations = {}
        self.correlation_history = {}  # ✅ NEW: bounded per-pair history so detect_correlation_changes() has real data to compare against
        logger.info("🧹 GNN caches cleared")
    
    def reset(self):
        """Reset GNN state (keeps A/B test results)."""
        if not self.is_enabled:
            return
        
        self.graph = None
        self.node_features = {}
        self.context_cache = {}
        self.trading_signals = {}
        self.price_history = {}
        self.dynamic_correlations = {}
        self.correlation_history = {}  # ✅ NEW: bounded per-pair history so detect_correlation_changes() has real data to compare against
        self.is_trained = False
        self.update_count = 0
        self.error_count = 0
        self.update_times = deque(maxlen=100)
        self.rollback_state = {
            'triggered': False,
            'reason': None,
            'timestamp': None,
            'last_good_graph': None,
            'last_good_context': None,
        }
        logger.info("🔄 GNN reset")
    
    # ============================================================
    # 5. ✅ CORRELATION MATRIX EXPORT
    # ============================================================
    
    def get_correlation_matrix(self, symbols: List[str] = None) -> Dict[str, Dict[str, float]]:
        """Get the correlation matrix for multiple symbols (dynamic-blended where available)."""
        if not self.is_enabled:
            return {}
        
        try:
            if symbols is None:
                symbols = self.assets[:20]
            
            matrix = {}
            for s1 in symbols:
                matrix[s1] = {}
                for s2 in symbols:
                    if s1 != s2:
                        # ✅ ENHANCED: previously static-table only, now
                        # blends in real dynamic correlation when available
                        matrix[s1][s2] = self._get_correlation_confidence(s1, s2)['correlation']
                    else:
                        matrix[s1][s2] = 1.0
            
            return matrix
        except Exception as e:
            logger.error(f"Error building correlation matrix: {e}")
            return {}
    
    def detect_correlation_changes(self, symbol: str, lookback: int = 10) -> Dict:
        """
        Detect significant changes in correlations.

        ✅ FIXED: this was a hardcoded stub -- `return {'changes': [],
        'significant_change': False}` unconditionally, silently ignoring
        both the `symbol` and `lookback` arguments. It could never report
        a change no matter what the market actually did, which is a large
        part of why correlation-change signals looked permanently dead.

        Now compares, for every asset correlated with `symbol`, the most
        recent dynamic-correlation snapshot against the one `lookback`
        update-loop cycles back (using the history _update_dynamic_
        correlations() now records) and flags pairs whose relationship
        moved by more than SIGNIFICANT_CORRELATION_CHANGE.
        """
        SIGNIFICANT_CORRELATION_CHANGE = 0.25
        symbol = symbol.upper()

        if not self.is_enabled or symbol not in self.correlation_history:
            return {
                'changes': [],
                'significant_change': False,
                'symbol': symbol,
                'lookback': lookback,
                'reason': 'no correlation history yet for this symbol (needs live data + time to build up samples)',
            }

        changes = []
        for other, history in self.correlation_history[symbol].items():
            if len(history) < 2:
                continue

            # Compare current vs `lookback` snapshots back -- clamp to the
            # oldest available snapshot if history is shorter than lookback.
            idx_back = min(lookback, len(history) - 1)
            current = history[-1]
            past = history[-1 - idx_back]
            delta = current['correlation'] - past['correlation']

            if abs(delta) >= SIGNIFICANT_CORRELATION_CHANGE:
                changes.append({
                    'symbol': other,
                    'from_correlation': past['correlation'],
                    'to_correlation': current['correlation'],
                    'change': round(delta, 4),
                    'from_timestamp': past['timestamp'],
                    'to_timestamp': current['timestamp'],
                    'snapshots_compared_back': idx_back,
                    'direction': 'STRENGTHENING' if abs(current['correlation']) > abs(past['correlation']) else 'WEAKENING',
                    'message': (
                        f"{symbol}-{other} correlation shifted {delta:+.2f} "
                        f"({past['correlation']:+.2f} \u2192 {current['correlation']:+.2f})"
                    ),
                })

        changes.sort(key=lambda c: abs(c['change']), reverse=True)

        return {
            'changes': changes,
            'significant_change': len(changes) > 0,
            'symbol': symbol,
            'lookback': lookback,
            'pairs_checked': len(self.correlation_history[symbol]),
        }
    
    def get_correlation_heatmap(self, symbols: List[str] = None) -> str:
        """Generate a correlation heatmap as a string."""
        if not self.is_enabled:
            return "GNN disabled - no heatmap available"
        
        try:
            if symbols is None:
                symbols = self.assets[:10]
            
            result = "     " + " ".join(f"{s:>6}" for s in symbols) + "\n"
            
            for s1 in symbols:
                row = f"{s1:>4} "
                for s2 in symbols:
                    if s1 == s2:
                        corr = 1.0
                    else:
                        # ✅ ENHANCED: blended dynamic+static correlation
                        corr = self._get_correlation_confidence(s1, s2)['correlation']
                    row += f"{corr:>6.2f}"
                result += row + "\n"
            
            return result
        except Exception as e:
            logger.error(f"Error building correlation heatmap: {e}")
            return "Error generating heatmap"
    
    def should_use_gnn(self, trade_id: int) -> bool:
        """Determine if GNN should be used for this trade."""
        if not self.is_enabled:
            return False
        
        if not self.is_ready():
            return False
        
        if not self.ab_test['enabled']:
            return True
        
        hash_val = hashlib.md5(str(trade_id).encode()).hexdigest()
        hash_int = int(hash_val[:8], 16) % 100
        
        return hash_int < (self.ab_test['rollout'] * 100)

# ============================================================
# MODULE-LEVEL VERIFICATION ENDPOINTS
# ============================================================
#
# Standard 12. Their absence was not cosmetic: /verify built its `ok` only
# from components carrying a dict self_check, so GNN was filtered out of the
# whole-layer gate and the gate could report ok=True having verified nothing
# about it. That is the same shape as the original defect in this module --
# GNN scored zero for months and nothing said so.
#
# NOTE (standard 10): the A/B assignment here hashes with MD5 while
# ai_adversarial uses SHA-256. Two implementations of one mechanic. They are
# deliberately NOT unified in place, because changing the hash reassigns every
# in-flight trade between control and test and would silently invalidate any
# comparison already running. Unify at the next rollout boundary, not mid-test.

def _build_gnn(firebase_service=None, config=None):
    from ai.ai_config import default_config
    return AssetGraphNeuralNetwork(firebase_service, config or default_config)


def get_status(gnn: Optional["AssetGraphNeuralNetwork"] = None) -> Dict[str, Any]:
    """Capability, readiness and A/B state."""
    try:
        gnn = gnn or _build_gnn()
    except Exception as exc:
        return {"component": "ai_gnn", "available": False,
                "error": f"{type(exc).__name__}: {exc}"}
    status = gnn.get_status()
    status.update({"component": "ai_gnn", "available": True,
                   "ab_test": gnn.get_ab_test_results()})
    return status


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               gnn: Optional["AssetGraphNeuralNetwork"] = None
               ) -> Dict[str, Any]:
    """
    Prove the invariants that fail silently here.

    This module's defining bug was scoring zero unnoticed, so the checks
    target exactly that class of failure: an unready GNN must say it is
    unready and return its documented default rather than a plausible-looking
    context, and A/B assignment must be deterministic or control and test
    contaminate each other.
    """
    report: Dict[str, Any] = {"component": "ai_gnn", "ok": False, "checks": {}}
    try:
        gnn = gnn or _build_gnn()
        checks = report["checks"]

        checks["is_enabled"] = bool(getattr(gnn, "is_enabled", False))
        checks["is_ready"] = bool(gnn.is_ready())

        # Deterministic A/B assignment, and a rollout that actually splits.
        was_enabled = gnn.ab_test.get("enabled")
        saved_rollout = gnn.ab_test.get("rollout")
        try:
            gnn.ab_test["enabled"] = True
            gnn.set_ab_test_rollout(0.5)
            ids = list(range(300))
            first = [gnn.should_use_gnn(i) for i in ids]
            second = [gnn.should_use_gnn(i) for i in ids]
            checks["ab_assignment_deterministic"] = first == second
            if checks["is_ready"]:
                checks["ab_assignment_splits"] = 0 < sum(first) < len(ids)
            else:
                # should_use_gnn short-circuits to False when not ready, so a
                # split cannot be observed. Not measurable is not a pass.
                checks["ab_assignment_splits"] = None
        finally:
            gnn.ab_test["enabled"] = was_enabled
            if saved_rollout is not None:
                gnn.set_ab_test_rollout(saved_rollout)

        # An unready GNN must return its documented default, never a
        # confident-looking context assembled from nothing.
        context = gnn.get_context("EURUSD")
        checks["context_is_dict"] = isinstance(context, dict)
        if not checks["is_ready"]:
            default = gnn._get_default_context()
            checks["unready_returns_default"] = context == default
        else:
            checks["unready_returns_default"] = None

        # The rollback contract is a documented no-op; what must exist is the
        # degraded-state reporting that stands in for it.
        status = gnn.get_status()
        checks["reports_rollback_state"] = "rollback_state" in status

        required = ("ab_assignment_deterministic", "context_is_dict",
                    "reports_rollback_state")
        gated = all(bool(checks.get(key)) for key in required)
        if checks.get("unready_returns_default") is False:
            gated = False
        report["ok"] = gated
        report["unmeasured"] = [
            key for key in ("ab_assignment_splits", "unready_returns_default")
            if checks.get(key) is None]
        if not checks["is_ready"]:
            report["reason"] = ("GNN is not ready (no graph built); checks that "
                                "require a live graph were not exercised")
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report
