# ============================================================
# MAIN MONITOR CLASS - COMPLETE WITH WEBHOOK & FAST ENTRY CHECKING
# ✅ FIXED: Full price evolution with ENCODER (400B per point)
# ✅ FIXED: Delegates to firebase_helpers for consistent encoding
# ✅ FIXED: Trade mode check in filter step (prevents "Trading not allowed")
# ✅ FIXED: Trade mode check in execution (adds to permanent exclusion)
# ✅ FIXED: Pre-validation during symbol discovery
# ✅ FIXED: _state_lock initialization BEFORE symbol discovery
# ✅ FIXED: ALL state variables initialized BEFORE symbol discovery
# ✅ REMOVED: Stability system, EMA200, Long-term trend
# ✅ REMOVED: GNN (moved to ai_controller.py on port 5002)
# ✅ FIXED: Price evolution updates every 60 seconds
# ✅ NEW: Discount zone display in logs
# ✅ NEW: Entry confidence displayed alongside overall confidence
# ✅ NEW: Price evolution ENCODER (18KB → 400B per point)
# ✅ NEW: analysis_at_close captured and saved to Firebase
# ✅ FIXED: Firebase doc_id consistency (use "trade_" prefix)
# ✅ FIXED: Position cache properly populated for monitor-opened trades
# ✅ FIXED: SL/TP hit detection for monitor-opened trades
# ✅ FIXED: Price evolution does NOT update for closed trades
# ✅ FIXED: NASDAQ stocks use .NAS suffix
# ✅ FIXED: NYSE stocks use .NYSE suffix
# ✅ FIXED: profit_usd now correctly saved from webhook and position monitor
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

import json
import time
import logging
import threading
import sys
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import traceback
import random
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .monitor_config import config
from .monitor_models import SymbolStatus, TradeResult
from flask import Flask, request, jsonify

from core.asset_analysis import analyze_institutional_signal
from core.mt5_connector import connect_mt5, shutdown_mt5, is_mt5_connected
from core.execution import (
    execute_trade,
    get_open_positions,
    is_market_closed,
    check_volatility,
    check_spread_status,
    get_open_positions_count,
    close_position,
    get_position_details,
    resolve_close_reason,
    set_symbol_exchange_map,
    get_trade_history
)
# The close reconstruction below shares these with api/execute_copy_trade.py --
# see core/broker_facts.py for why they are not duplicated.
from core.broker_facts import closing_deal, contract_size
# Used by _save_analysis_at_close_to_firebase, which referenced it without
# importing it -- a NameError on every monitor-path close, so analysis_at_close
# was never saved for any trade the monitor itself took.
from monitor.firebase_helpers import make_json_safe, _direction_of_record

# ============================================================
# ✅ NEW: PRICE EVOLUTION ENCODER IMPORTS
# ============================================================
try:
    from ai.price_evolution_encoder import PriceEvolutionEncoder
    from ai.price_evolution_decoder import PriceEvolutionDecoder
    from ai.price_evolution_bridge import PriceEvolutionBridge
except ImportError:
    PriceEvolutionEncoder = None
    PriceEvolutionDecoder = None
    PriceEvolutionBridge = None
    print("⚠️ Price evolution encoder not available")

# ============================================================
# IMPORT FIREBASE HELPERS
# ============================================================
from .firebase_helpers import (
    save_trade_open_to_firebase,
    update_trade_price_in_firebase as fb_update_price,
    save_trade_close_to_firebase,
    save_trailing_stop_to_firebase,
    process_webhook_close,
    process_trailing_webhook,
    monitor_position_updates
)

# Configure logging to print to console
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)


# ============================================================
# WEBHOOK ROUTES - DEPRECATED (use hybrid_monitor.py routes)
# ============================================================

def register_webhook_routes(app, monitor):
    """
    DEPRECATED: Webhook routes are now defined in hybrid_monitor.py
    This function is kept for backward compatibility but does nothing.
    """
    print("⚠️ register_webhook_routes is deprecated - webhook routes are in hybrid_monitor.py")
    pass


# ============================================================
# MAIN MONITOR CLASS
# ============================================================

class CryptoMultiSymbolMonitor:
    
    # ============================================================
    # CONSTANTS
    # ============================================================
    
    MAX_SIMULTANEOUS_TRADES = 100000  # data-collection mode: unlimited
    # ✅ TRIPLED (was 10) to widen the watched set and raise trade rate.
    # This is the LIVE value: MultiSymbolMonitor does its own
    # valid_symbols[:TOP_SYMBOLS_COUNT] slice and never constructs
    # MonitorFilter, so monitor_config.Config.TOP_SYMBOLS_COUNT feeds a
    # different (unused) path. Both are raised so they cannot drift further.
    #
    # 30 is inside the 65-symbol DISPLAY_SYMBOLS universe, so the slice is not
    # asking for symbols that do not exist. Note the real gate above it is
    # MIN_CONFIDENCE_THRESHOLD: only symbols scoring >= 65 reach this slice,
    # so if fewer than 30 clear that bar, this raise alone will not triple
    # anything -- the confidence bar would have to move, and that changes
    # which trades are taken, not merely how many.
    # ✅ 10x the original 10. Note the DISPLAY_SYMBOLS universe is 65, so a
    # value of 100 does not mean "100 symbols" -- it means the slice stops
    # limiting anything, and every symbol clearing MIN_CONFIDENCE_THRESHOLD
    # is watched. That threshold is now the only gate left above this line.
    #
    # That last sentence was wrong, and the error was expensive:
    # _run_filter_step() ALSO compared its pass-count against this value and
    # returned False when short. With a 64-symbol universe, 45 passing and a
    # cap of 100, the gate could never be satisfied -- _refresh_top_symbols()
    # was never called, top_symbols stayed empty, and the monitor ran healthy
    # and idle forever, opening no trades. A cap and a floor are opposite
    # quantities; they now have separate names.
    TOP_SYMBOLS_COUNT = 100
    # The floor. Must be <= the number of symbols that realistically pass the
    # market-conditions filter, or the monitor refuses to start.
    MIN_SYMBOLS_TO_TRADE = 3
    MIN_CONFIDENCE_THRESHOLD = 65
    
    SCAN_INTERVAL = 5
    FILTER_INTERVAL = 7200
    FILTER_RETRY_INTERVAL = 60
    REPLACEMENT_CHECK_INTERVAL = 60
    
    FILTER_THREADS = 4
    MONITOR_THREADS = 3
    FILTER_TIMEOUT = 5
    MONITOR_TIMEOUT = 10
    
    REPLACEMENT_COOLDOWN = 180
    SYMBOL_COOLDOWN = 5
    
    FIXED_TRADE_SIZE_USD = 200
    # Fraction of FIXED_TRADE_SIZE_USD, not of the account. 0.02 -> $4 risk.
    # See the note in monitor_config.py before changing it.
    RISK_PER_TRADE = 0.02
    MAX_SPREAD = 50
    STRATEGY_MAGIC = 1001
    TRADE_DEVIATION = 20
    MAX_TRADES_PER_SYMBOL = 100000  # data-collection mode: same symbol allowed
    
    # ✅ Price evolution update interval - 60 seconds (1 minute)
    PRICE_UPDATE_INTERVAL = 60
    
    # Reanalysis
    SYMBOL_REANALYSIS_INTERVAL = 300
    SYMBOL_REANALYSIS_BATCH_SIZE = 5
    STALE_SYMBOL_THRESHOLD = 600
    
    # ============================================================
    # SYMBOLS - WITH BROKER DISCOVERY
    # ============================================================
    
    # 21 symbols removed 2026-09-10, measured against the sizing targets
    # (margin $200 budget, $4 risk) with calculate_lot_proper on live quotes:
    #
    #   risk unreachable -- spread so wide the stop hits its 1000-pip cap:
    #     GE $1.23  AXP $1.24  NAS100 $2.44  NIKKEI225 $2.46  MRK $2.76
    #     US30 $2.80  HK50 $3.19  USOIL/UKOIL $3.00
    #   margin under half the $200 budget (1-pip stop floor binds first):
    #     CAC40 $24  GILD $30  HK50 $39  XAGEUR $45  ASX200 $47  XAGUSD $51
    #     MRNA $55  ABBV $61  FTSE100 $65  IBM $77  SNOW $84  AUDCHF $97
    #   wrong instrument entirely:
    #     CAC40 -> CACC.NAS (a NASDAQ stock, not the French index)
    #     NAS100 -> NDX1.ETR (Frankfurt tracker, not the US index)
    #     DAX40 -> no broker symbol at all
    #
    # AUDCHF is the costliest of these: it closed at -$40.61 and -$33.96
    # against a $4 budget before the risk guard landed.
    
    # ============================================================
    # 🛑 PREVIOUS SYMBOLS (STOCKS, FOREX, INDICES, COMMODITIES) COMMENTED OUT FOR WEEKEND:
    # DISPLAY_SYMBOLS = [
    #     "XAUUSD", "XAUEUR", "EURUSD", "GBPUSD",
    #     "USDCAD", "AUDUSD", "NZDUSD", "USDCHF",
    #     "EURGBP", "EURCAD", "GBPAUD", "AUDNZD",
    #     "AUDCAD", "SPX500", "AAPL.NAS", "MSFT.NAS",
    #     "GOOGL.NAS", "AMZN.NAS", "NVDA.NAS", "META.NAS",
    #     "TSLA.NAS", "AMD.NAS", "INTC.NAS", "CSCO.NAS",
    #     "ORCL.NAS", "QCOM.NAS", "MU.NAS", "PLTR.NAS",
    #     "UBER.NAS", "PYPL.NAS", "JNJ.NYSE", "PFE.NYSE",
    #     "WMT.NYSE", "MCD.NYSE", "SBUX.NYSE", "DIS.NYSE",
    #     "KO.NYSE", "XOM.NYSE", "CVX.NYSE", "JPM.NYSE",
    #     "MA.NYSE", "SPY.NYSE", "QQQ.NAS", "SMH.NAS"
    # ]
    # ============================================================

    # ✅ WEEKEND CRYPTO ONLY LIST (IC MARKETS MT5 CRYPTOCURRENCIES)
    DISPLAY_SYMBOLS = [
        "BTCUSD", "ETHUSD", "BCHUSD", "LTCUSD", "XRPUSD",
        "SOLUSD", "ADAUSD", "DOTUSD", "DOGUSD", "BNBUSD",
        "AVAXUSD", "LINKUSD", "UNIUSD", "MATICUSD", "ATOMUSD",
        "NEARUSD", "ALGOUSD", "XLMUSD", "VETUSD", "ICPUSD",
        "FILUSD", "TRXUSD", "ETCUSD", "XTZUSD", "EOSUSD",
        "AAVEUSD", "SANDUSD", "MANAUSD", "AXSUSD", "THETAUSD",
        "FTMUSD", "CRVUSD", "SNXUSD", "DYDXUSD", "GALAUSD",
        "DSHUSD", "EMCUSD", "NMCUSD", "PPCUSD", "LNKUSD"
    ]
    
    BROKER_PATTERNS = {
        # ============================================================
        # 🛑 PREVIOUS BROKER PATTERNS COMMENTED OUT:
        # "SPX500": ["SPX500", "US500", "SP500", "SPX", "S&P500"],
        # "NAS100": ["NAS100", "US100", "NDX", "NASDAQ", "NAS"],
        # "US30": ["US30", "DJ30", "DOW", "DJI", "US30"],
        # "DAX40": ["DAX40", "GER40", "DAX", "GER30"],
        # "FTSE100": ["FTSE100", "UK100", "FTSE"],
        # "CAC40": ["CAC40", "FRA40", "CAC"],
        # "ASX200": ["ASX200", "AUS200"],
        # "NIKKEI225": ["NIKKEI225", "JP225", "NIKKEI"],
        # "HK50": ["HK50", "HKEX"],
        # "USOIL": ["USOIL", "WTI", "CL", "XTIUSD"],
        # "UKOIL": ["UKOIL", "BRENT", "BR", "XBRUSD"],
        # # ✅ NASDAQ STOCKS
        # "AAPL.NAS": ["AAPL.NAS", "AAPL", "AAPL.nq", "AAPL.ny", "AAPL.OQ"],
        # "MSFT.NAS": ["MSFT.NAS", "MSFT", "MSFT.nq", "MSFT.ny", "MSFT.OQ"],
        # "GOOGL.NAS": ["GOOGL.NAS", "GOOGL", "GOOGL.nq", "GOOGL.ny", "GOOG"],
        # "AMZN.NAS": ["AMZN.NAS", "AMZN", "AMZN.nq", "AMZN.ny", "AMZN.OQ"],
        # "NVDA.NAS": ["NVDA.NAS", "NVDA", "NVDA.nq", "NVDA.ny", "NVDA.OQ"],
        # "META.NAS": ["META.NAS", "META", "META.nq", "META.ny", "META.OQ"],
        # "TSLA.NAS": ["TSLA.NAS", "TSLA", "TSLA.nq", "TSLA.ny", "TSLA.OQ"],
        # "AMD.NAS": ["AMD.NAS", "AMD", "AMD.nq", "AMD.ny", "AMD.OQ"],
        # "INTC.NAS": ["INTC.NAS", "INTC", "INTC.nq", "INTC.ny", "INTC.OQ"],
        # "CSCO.NAS": ["CSCO.NAS", "CSCO", "CSCO.nq", "CSCO.ny", "CSCO.OQ"],
        # "ORCL.NAS": ["ORCL.NAS", "ORCL", "ORCL.nq", "ORCL.ny"],
        # "IBM.NAS": ["IBM.NAS", "IBM", "IBM.nq", "IBM.ny"],
        # "QCOM.NAS": ["QCOM.NAS", "QCOM", "QCOM.nq", "QCOM.ny", "QCOM.OQ"],
        # "MU.NAS": ["MU.NAS", "MU", "MU.nq", "MU.ny", "MU.OQ"],
        # "PLTR.NAS": ["PLTR.NAS", "PLTR", "PLTR.nq", "PLTR.ny"],
        # "SNOW.NAS": ["SNOW.NAS", "SNOW", "SNOW.nq", "SNOW.ny"],
        # "UBER.NAS": ["UBER.NAS", "UBER", "UBER.nq", "UBER.ny"],
        # "PYPL.NAS": ["PYPL.NAS", "PYPL", "PYPL.nq", "PYPL.ny", "PYPL.OQ"],
        # # ✅ NYSE STOCKS
        # "JNJ.NYSE": ["JNJ.NYSE", "JNJ", "JNJ.nq", "JNJ.ny"],
        # "PFE.NYSE": ["PFE.NYSE", "PFE", "PFE.nq", "PFE.ny"],
        # "MRK.NYSE": ["MRK.NYSE", "MRK", "MRK.nq", "MRK.ny"],
        # "ABBV.NYSE": ["ABBV.NYSE", "ABBV", "ABBV.nq", "ABBV.ny"],
        # "GILD.NYSE": ["GILD.NYSE", "GILD", "GILD.nq", "GILD.ny"],
        # "MRNA.NYSE": ["MRNA.NYSE", "MRNA", "MRNA.nq", "MRNA.ny"],
        # "WMT.NYSE": ["WMT.NYSE", "WMT", "WMT.nq", "WMT.ny"],
        # "MCD.NYSE": ["MCD.NYSE", "MCD", "MCD.nq", "MCD.ny"],
        # "SBUX.NYSE": ["SBUX.NYSE", "SBUX", "SBUX.nq", "SBUX.ny", "SBUX.OQ"],
        # "DIS.NYSE": ["DIS.NYSE", "DIS", "DIS.nq", "DIS.ny"],
        # "KO.NYSE": ["KO.NYSE", "KO", "KO.nq", "KO.ny"],
        # "XOM.NYSE": ["XOM.NYSE", "XOM", "XOM.nq", "XOM.ny"],
        # "CVX.NYSE": ["CVX.NYSE", "CVX", "CVX.nq", "CVX.ny"],
        # "GE.NYSE": ["GE.NYSE", "GE", "GE.nq", "GE.ny"],
        # "JPM.NYSE": ["JPM.NYSE", "JPM", "JPM.nq", "JPM.ny"],
        # "MA.NYSE": ["MA.NYSE", "MA", "MA.nq", "MA.ny"],
        # "AXP.NYSE": ["AXP.NYSE", "AXP", "AXP.nq", "AXP.ny"],
        # # ETFs
        # "SPY.NYSE": ["SPY.NYSE", "SPY", "SPY.nq", "SPY.ny"],
        # "QQQ.NAS": ["QQQ.NAS", "QQQ", "QQQ.nq", "QQQ.ny"],
        # "SMH.NAS": ["SMH.NAS", "SMH", "SMH.nq", "SMH.ny"],
        # "VTI.NYSE": ["VTI.NYSE", "VTI", "VTI.nq", "VTI.ny"],
        # "XAUUSD": ["XAUUSD", "GOLD", "XAU"],
        # "XAGUSD": ["XAGUSD", "SILVER", "XAG"],
        # "XAUEUR": ["XAUEUR"],
        # "XAGEUR": ["XAGEUR"],
        # "EURUSD": ["EURUSD"],
        # "GBPUSD": ["GBPUSD"],
        # "USDCAD": ["USDCAD"],
        # "AUDUSD": ["AUDUSD"],
        # "AUDCAD": ["AUDCAD"],
        # "AUDNZD": ["AUDNZD"],
        # "AUDCHF": ["AUDCHF"],
        # "NZDUSD": ["NZDUSD"],
        # "USDCHF": ["USDCHF"],
        # "EURGBP": ["EURGBP"],
        # "EURCAD": ["EURCAD"],
        # "GBPAUD": ["GBPAUD"],
        # ============================================================

        # ✅ IC MARKETS CRYPTOCURRENCY BROKER PATTERNS
        "BTCUSD": ["BTCUSD", "Bitcoin", "BTCUSD.raw", "BTCUSD.pro", "BTCUSDT"],
        "ETHUSD": ["ETHUSD", "Ethereum", "ETHUSD.raw", "ETHUSD.pro", "ETHUSDT"],
        "BCHUSD": ["BCHUSD", "Bitcoin Cash", "BCHUSD.raw", "BCHUSD.pro", "BCHUSDT"],
        "LTCUSD": ["LTCUSD", "Litecoin", "LTCUSD.raw", "LTCUSD.pro", "LTCUSDT"],
        "XRPUSD": ["XRPUSD", "Ripple", "XRPUSD.raw", "XRPUSD.pro", "XRPUSDT"],
        "SOLUSD": ["SOLUSD", "Solana", "SOLUSD.raw", "SOLUSD.pro", "SOLUSDT"],
        "ADAUSD": ["ADAUSD", "Cardano", "ADAUSD.raw", "ADAUSD.pro", "ADAUSDT"],
        "DOTUSD": ["DOTUSD", "Polkadot", "DOTUSD.raw", "DOTUSD.pro", "DOTUSDT"],
        "DOGUSD": ["DOGUSD", "DOGEUSD", "Dogecoin", "DOGUSD.raw", "DOGEUSDT"],
        "BNBUSD": ["BNBUSD", "Binance Coin", "BNBUSD.raw", "BNBUSD.pro", "BNBUSDT"],
        "AVAXUSD": ["AVAXUSD", "Avalanche", "AVAXUSD.raw", "AVAXUSDT"],
        "LINKUSD": ["LINKUSD", "LNKUSD", "Chainlink", "LINKUSD.raw", "LINKUSDT"],
        "UNIUSD": ["UNIUSD", "Uniswap", "UNIUSD.raw", "UNIUSDT"],
        "MATICUSD": ["MATICUSD", "Polygon", "MATICUSD.raw", "MATICUSDT"],
        "ATOMUSD": ["ATOMUSD", "Cosmos", "ATOMUSD.raw", "ATOMUSDT"],
        "NEARUSD": ["NEARUSD", "NEAR", "NEARUSD.raw", "NEARUSDT"],
        "ALGOUSD": ["ALGOUSD", "Algorand", "ALGOUSD.raw", "ALGOUSDT"],
        "XLMUSD": ["XLMUSD", "Stellar", "XLMUSD.raw", "XLMUSDT"],
        "VETUSD": ["VETUSD", "VeChain", "VETUSD.raw", "VETUSDT"],
        "ICPUSD": ["ICPUSD", "Internet Computer", "ICPUSD.raw", "ICPUSDT"],
        "FILUSD": ["FILUSD", "Filecoin", "FILUSD.raw", "FILUSDT"],
        "TRXUSD": ["TRXUSD", "Tron", "TRXUSD.raw", "TRXUSDT"],
        "ETCUSD": ["ETCUSD", "Ethereum Classic", "ETCUSD.raw", "ETCUSDT"],
        "XTZUSD": ["XTZUSD", "Tezos", "XTZUSD.raw", "XTZUSDT"],
        "EOSUSD": ["EOSUSD", "EOS", "EOSUSD.raw", "EOSUSDT"],
        "AAVEUSD": ["AAVEUSD", "Aave", "AAVEUSD.raw", "AAVEUSDT"],
        "SANDUSD": ["SANDUSD", "The Sandbox", "SANDUSD.raw", "SANDUSDT"],
        "MANAUSD": ["MANAUSD", "Decentraland", "MANAUSD.raw", "MANAUSDT"],
        "AXSUSD": ["AXSUSD", "Axie Infinity", "AXSUSD.raw", "AXSUSDT"],
        "THETAUSD": ["THETAUSD", "Theta Network", "THETAUSD.raw", "THETAUSDT"],
        "FTMUSD": ["FTMUSD", "Fantom", "FTMUSD.raw", "FTMUSDT"],
        "CRVUSD": ["CRVUSD", "Curve", "CRVUSD.raw", "CRVUSDT"],
        "SNXUSD": ["SNXUSD", "Synthetix", "SNXUSD.raw", "SNXUSDT"],
        "DYDXUSD": ["DYDXUSD", "dYdX", "DYDXUSD.raw", "DYDXUSDT"],
        "GALAUSD": ["GALAUSD", "Gala", "GALAUSD.raw", "GALAUSDT"],
        "DSHUSD": ["DSHUSD", "DASHUSD", "Dash", "DSHUSD.raw"],
        "EMCUSD": ["EMCUSD", "Emercoin", "EMCUSD.raw"],
        "NMCUSD": ["NMCUSD", "Namecoin", "NMCUSD.raw"],
        "PPCUSD": ["PPCUSD", "Peercoin", "PPCUSD.raw"],
        "LNKUSD": ["LNKUSD", "LINKUSD", "Chainlink", "LNKUSD.raw"]
    }
    
    SYMBOL_EXCHANGE_MAP = {
        # ============================================================
        # 🛑 PREVIOUS SYMBOL_EXCHANGE_MAP COMMENTED OUT:
        # "XAUUSD": "FX", "XAGUSD": "FX", "XAUEUR": "FX", "XAGEUR": "FX",
        # "EURUSD": "FX", "GBPUSD": "FX", "USDCAD": "FX", "AUDUSD": "FX",
        # "NZDUSD": "FX", "USDCHF": "FX", "EURGBP": "FX", "EURCAD": "FX",
        # "GBPAUD": "FX", "AUDNZD": "FX", "AUDCAD": "FX", "AUDCHF": "FX",
        # "USOIL": "COMMODITY", "UKOIL": "COMMODITY",
        # "SPX500": "NYSE", "NAS100": "NASDAQ", "US30": "NYSE",
        # "DAX40": "XETRA", "FTSE100": "LSE", "CAC40": "EURONEXT",
        # "ASX200": "ASX", "NIKKEI225": "JPX", "HK50": "HKEX",
        # # NASDAQ Stocks
        # "AAPL.NAS": "NASDAQ", "MSFT.NAS": "NASDAQ", "GOOGL.NAS": "NASDAQ",
        # "AMZN.NAS": "NASDAQ", "NVDA.NAS": "NASDAQ", "META.NAS": "NASDAQ",
        # "TSLA.NAS": "NASDAQ", "AMD.NAS": "NASDAQ", "INTC.NAS": "NASDAQ",
        # "CSCO.NAS": "NASDAQ", "ORCL.NAS": "NASDAQ", "IBM.NAS": "NASDAQ",
        # "QCOM.NAS": "NASDAQ", "MU.NAS": "NASDAQ", "PLTR.NAS": "NASDAQ",
        # "SNOW.NAS": "NASDAQ", "UBER.NAS": "NASDAQ", "PYPL.NAS": "NASDAQ",
        # # NYSE Stocks
        # "JNJ.NYSE": "NYSE", "PFE.NYSE": "NYSE", "MRK.NYSE": "NYSE",
        # "ABBV.NYSE": "NYSE", "GILD.NYSE": "NYSE", "MRNA.NYSE": "NYSE",
        # "WMT.NYSE": "NYSE", "MCD.NYSE": "NYSE", "SBUX.NYSE": "NYSE",
        # "DIS.NYSE": "NYSE", "KO.NYSE": "NYSE", "XOM.NYSE": "NYSE",
        # "CVX.NYSE": "NYSE", "GE.NYSE": "NYSE", "JPM.NYSE": "NYSE",
        # "MA.NYSE": "NYSE", "AXP.NYSE": "NYSE",
        # # ETFs
        # "SPY.NYSE": "NYSE", "QQQ.NAS": "NASDAQ", "SMH.NAS": "NASDAQ",
        # "VTI.NYSE": "NYSE"
        # ============================================================

        # ✅ IC MARKETS CRYPTOCURRENCIES (CRYPTO EXCHANGE CLASSIFICATION)
        "BTCUSD": "CRYPTO", "ETHUSD": "CRYPTO", "BCHUSD": "CRYPTO", "LTCUSD": "CRYPTO", "XRPUSD": "CRYPTO",
        "SOLUSD": "CRYPTO", "ADAUSD": "CRYPTO", "DOTUSD": "CRYPTO", "DOGUSD": "CRYPTO", "BNBUSD": "CRYPTO",
        "AVAXUSD": "CRYPTO", "LINKUSD": "CRYPTO", "UNIUSD": "CRYPTO", "MATICUSD": "CRYPTO", "ATOMUSD": "CRYPTO",
        "NEARUSD": "CRYPTO", "ALGOUSD": "CRYPTO", "XLMUSD": "CRYPTO", "VETUSD": "CRYPTO", "ICPUSD": "CRYPTO",
        "FILUSD": "CRYPTO", "TRXUSD": "CRYPTO", "ETCUSD": "CRYPTO", "XTZUSD": "CRYPTO", "EOSUSD": "CRYPTO",
        "AAVEUSD": "CRYPTO", "SANDUSD": "CRYPTO", "MANAUSD": "CRYPTO", "AXSUSD": "CRYPTO", "THETAUSD": "CRYPTO",
        "FTMUSD": "CRYPTO", "CRVUSD": "CRYPTO", "SNXUSD": "CRYPTO", "DYDXUSD": "CRYPTO", "GALAUSD": "CRYPTO",
        "DSHUSD": "CRYPTO", "EMCUSD": "CRYPTO", "NMCUSD": "CRYPTO", "PPCUSD": "CRYPTO", "LNKUSD": "CRYPTO"
    }
    
    def __init__(self):
        # ✅ Set the exchange map for market detection
        set_symbol_exchange_map(self.SYMBOL_EXCHANGE_MAP)
        print(f"✅ Symbol exchange map set with {len(self.SYMBOL_EXCHANGE_MAP)} symbols")
        
        # Copy constants to instance
        for key, value in self.__class__.__dict__.items():
            if not key.startswith('_') and not callable(value) and key.isupper():
                setattr(self, key, value)
        
        # ✅ CRITICAL: Initialize ALL locks BEFORE anything else
        self._state_lock = threading.RLock()
        self._executed_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._reanalysis_lock = threading.Lock()
        self._fast_entry_lock = threading.Lock()
        self._restart_lock = threading.Lock()
        
        # ✅ NEW: PERSISTENT THREAD POOLS — created ONCE, reused for the life
        # of the process. Previously _run_filter_step / _refresh_top_symbols /
        # _run_monitor_step each did `with ThreadPoolExecutor(...) as executor:`,
        # spinning up a brand new pool of OS threads every cycle (every 5s for
        # the monitor step) and blocking on executor.shutdown(wait=True) on the
        # way out. If any single worker call ever hung (a stalled MT5/network
        # call), that shutdown() blocked forever and froze the entire main
        # loop, with a fresh never-finishing pool piling up every cycle after.
        # Reusing one pool per role removes both problems: no thread churn,
        # and a hung task just occupies one pool slot instead of freezing
        # everything downstream of it.
        self._filter_pool = ThreadPoolExecutor(max_workers=self.FILTER_THREADS, thread_name_prefix="Filter")
        self._monitor_pool = ThreadPoolExecutor(max_workers=self.MONITOR_THREADS, thread_name_prefix="Monitor")
        
        # ✅ CRITICAL: Initialize ALL state variables BEFORE symbol discovery
        self.permanently_excluded: Set[str] = set()
        self.long_term_excluded: Set[str] = set()
        self.filtered_symbols: Set[str] = set()
        self.top_symbols: List[SymbolStatus] = []
        self.open_positions: Dict[str, int] = {}
        self.symbol_status_map: Dict[str, SymbolStatus] = {}
        self._executing_symbols: Set[str] = set()
        self._executed_recently: Set[str] = set()
        self._refreshing = False
        self._reanalysis_queue: List[str] = []
        
        # ✅ NEW: Initialize price evolution encoder
        self.price_encoder = PriceEvolutionEncoder() if PriceEvolutionEncoder else None
        self.price_decoder = PriceEvolutionDecoder() if PriceEvolutionDecoder else None
        self.price_bridge = PriceEvolutionBridge() if PriceEvolutionBridge else None
        
        if self.price_encoder:
            print("✅ Price evolution encoder initialized (18KB → 400B per point)")
        else:
            print("⚠️ Price evolution encoder not available - using raw data")
        
        # ✅ Now safe to discover symbols
        self.symbol_mt5_map = {}
        self.mt5_symbols = []
        self._discover_mt5_symbols()
        
        # Symbols - Only use discovered symbols
        self.symbols = list(self.symbol_mt5_map.keys())
        self.symbols = [s for s in self.symbols if self.symbol_mt5_map.get(s) != "NOT_FOUND"]
        
        self._last_replacement_time = 0
        self._last_filter_time = 0
        self._last_reanalysis_time = 0
        self._filter_retry_count = 0
        
        self.stop_event = threading.Event()
        self.running = False
        self.position_monitor_thread = None
        self.health_thread = None
        self.main_thread = None
        self.webhook_thread = None
        
        # ✅ NEW: Self-restart control (see restart_now / enable_auto_restart
        # further down). Auto-restart is OFF by default — call
        # enable_auto_restart() explicitly (or hit the hybrid_monitor.py
        # /monitor/restart/auto route) to turn it on.
        self._restart_thread = None
        self._restarting = False
        self._auto_restart_enabled = False
        self._auto_restart_interval = 3600  # seconds
        self._last_restart_time = time.time()
        self._restart_count = 0
        
        # Track webhook-closed tickets
        self._webhook_closed_tickets: Set[int] = set()
        
        # Position data cache for fallback
        self._position_data_cache: Dict[int, Dict] = {}
        
        # Fast entry checking
        self._fast_entry_symbols: Set[str] = set()
        self._fast_entry_thread = None
        self._fast_entry_interval = 10
        
        # Last price update time for 60-second interval
        # ✅ FIXED: was a single scalar shared by EVERY open position.
        # _update_trade_price_in_firebase() is called once per position per
        # pass, so the first ticket to update set the global clock and every
        # OTHER open position returned early for the next PRICE_UPDATE_INTERVAL
        # seconds. With N concurrent trades at most one of them ever got a
        # price_evolution point, and with same-symbol/unlimited concurrency
        # enabled essentially none did.
        #
        # Measured in Firestore before this fix: three trades open ~3.3h each
        # (~200 expected points apiece at a 60s interval) held 2, 1 and 1
        # points, with metrics.price_updates_count == 1 and last_price_update
        # equal to the OPEN timestamp -- update_price had never once run.
        #
        # price_evolution IS the forward walk every model reads, so this was
        # not a telemetry gap; it silently emptied the training data.
        # Keyed by ticket now, so each position is throttled independently.
        self._last_price_update_time: Dict[int, float] = {}
        
        # ✅ REMOVED: GNN - moved to ai_controller.py on port 5002
        
        # Stats
        self.stats = {
            "start_time": None,
            "total_scans": 0,
            "filtered_count": 0,
            "trades_executed": 0,
            "trades_closed": 0,
            "filter_errors": 0,
            "monitor_errors": 0,
            "execution_errors": 0,
            "last_filter_time": 0,
            "last_refresh_time": 0,
            "filter_retry_count": 0,
            "firebase_saves": 0,
            "firebase_errors": 0,
            "reanalysis_count": 0,
            "webhook_closes": 0,
            "fast_entry_checks": 0,
            "trailing_updates": 0,
            "price_updates": 0
        }
        
        # Log file
        self.log_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "multi_symbol_log.json"
        self._init_log_file()
        
        # Firebase
        self.firebase = self._get_firebase()
        
        # Sync positions
        self._sync_open_positions()
        
        print(f"✅ Monitor initialized: {len(self.symbols)} symbols discovered in MT5")
        print(f"✅ Confidence threshold: {self.MIN_CONFIDENCE_THRESHOLD}%")
        print(f"✅ Scan interval: {self.SCAN_INTERVAL}s")
        print(f"✅ Fast entry check: Every {self._fast_entry_interval}s")
        print(f"✅ Price evolution update: Every {self.PRICE_UPDATE_INTERVAL}s (1 minute)")
        print(f"✅ Stability system: REMOVED")
        print(f"✅ EMA200 check: REMOVED")
        print(f"✅ Long-term trend check: REMOVED")
        print(f"✅ Reanalysis: Every {self.SYMBOL_REANALYSIS_INTERVAL//60} minutes")
        print(f"✅ Filter interval: {self.FILTER_INTERVAL}s")
        print(f"✅ Trade size: ${self.FIXED_TRADE_SIZE_USD}, Risk: {self.RISK_PER_TRADE*100}%")
        if self.price_encoder:
            print(f"✅ Price evolution ENCODER: 18KB → 400B per point (97.8% reduction)")
        print(f"✅ analysis_at_close: Captured and saved to Firebase")
        print(f"✅ GNN: REMOVED - Running in ai_controller.py on port 5002")
    
    # ============================================================
    # MT5 SYMBOL DISCOVERY
    # ============================================================
    
    def _discover_mt5_symbols(self):
        """
        ✅ FIXED: Discover MT5 symbols with trade mode validation.
        """
        try:
            all_mt5_symbols = mt5.symbols_get()
            if not all_mt5_symbols:
                print("⚠️ No MT5 symbols found")
                for display in self.DISPLAY_SYMBOLS:
                    self.symbol_mt5_map[display] = display
                return
            
            self.mt5_symbols = [s.name for s in all_mt5_symbols]
            print(f"📊 Found {len(self.mt5_symbols)} symbols in MT5")
            
            for display in self.DISPLAY_SYMBOLS:
                found = False
                patterns = self.BROKER_PATTERNS.get(display, [display])
                
                for pattern in patterns:
                    if pattern in self.mt5_symbols:
                        self.symbol_mt5_map[display] = pattern
                        print(f"✅ {display} -> {pattern} (exact match)")
                        found = True
                        break
                
                if found:
                    # ✅ Check if trading is allowed for this symbol
                    mt5_symbol = self.symbol_mt5_map[display]
                    symbol_info = mt5.symbol_info(mt5_symbol)
                    if symbol_info:
                        if symbol_info.trade_mode not in [
                            mt5.SYMBOL_TRADE_MODE_FULL, 
                            mt5.SYMBOL_TRADE_MODE_LONGONLY, 
                            mt5.SYMBOL_TRADE_MODE_SHORTONLY
                        ]:
                            print(f"⚠️ {display} -> {mt5_symbol} (Trading NOT allowed - excluded)")
                            self.symbol_mt5_map[display] = "NOT_TRADABLE"
                            with self._state_lock:
                                self.permanently_excluded.add(display)
                    continue
                
                display_lower = display.lower()
                for mt5_name in self.mt5_symbols:
                    mt5_lower = mt5_name.lower()
                    if display_lower in mt5_lower or mt5_lower in display_lower:
                        self.symbol_mt5_map[display] = mt5_name
                        print(f"✅ {display} -> {mt5_name} (partial match)")
                        found = True
                        break
                
                if not found:
                    for pattern in patterns:
                        pattern_lower = pattern.lower()
                        for mt5_name in self.mt5_symbols:
                            if pattern_lower in mt5_name.lower():
                                self.symbol_mt5_map[display] = mt5_name
                                print(f"✅ {display} -> {mt5_name} (pattern match: {pattern})")
                                found = True
                                break
                        if found:
                            break
                
                if found:
                    # ✅ Check if trading is allowed for this symbol
                    mt5_symbol = self.symbol_mt5_map[display]
                    symbol_info = mt5.symbol_info(mt5_symbol)
                    if symbol_info:
                        if symbol_info.trade_mode not in [
                            mt5.SYMBOL_TRADE_MODE_FULL, 
                            mt5.SYMBOL_TRADE_MODE_LONGONLY, 
                            mt5.SYMBOL_TRADE_MODE_SHORTONLY
                        ]:
                            print(f"⚠️ {display} -> {mt5_symbol} (Trading NOT allowed - excluded)")
                            self.symbol_mt5_map[display] = "NOT_TRADABLE"
                            with self._state_lock:
                                self.permanently_excluded.add(display)
                
                if not found:
                    self.symbol_mt5_map[display] = "NOT_FOUND"
                    print(f"❌ {display}: Not found in MT5")
            
            found_count = sum(1 for v in self.symbol_mt5_map.values() if v != "NOT_FOUND" and v != "NOT_TRADABLE")
            print(f"📊 Mapped {found_count}/{len(self.DISPLAY_SYMBOLS)} tradable symbols")
            
        except Exception as e:
            print(f"❌ Error discovering MT5 symbols: {e}")
            for display in self.DISPLAY_SYMBOLS:
                self.symbol_mt5_map[display] = display
    
    # ============================================================
    # FIREBASE
    # ============================================================
    
    def _get_firebase(self):
        try:
            from core.firebase import get_firebase_service
            firebase = get_firebase_service()
            if firebase and firebase.is_healthy():
                print("🔥 Firebase connected")
            else:
                print("⚠️ Firebase not available")
            return firebase
        except Exception as e:
            print(f"⚠️ Firebase error: {e}")
            return None
    
    # ============================================================
    # POSITION SYNC
    # ============================================================
    
    def _sync_open_positions(self):
        try:
            positions = get_open_positions()
            with self._state_lock:
                self.open_positions.clear()
                for pos in positions:
                    symbol = pos.get("symbol", "")
                    ticket = pos.get("ticket", 0)
                    if symbol and ticket:
                        self.open_positions[symbol] = ticket
                        if symbol in self.symbol_status_map:
                            self.symbol_status_map[symbol].in_position = True
                            self.symbol_status_map[symbol].ticket = ticket
                if positions:
                    print(f"📊 Synced {len(self.open_positions)} open positions")
        except Exception as e:
            print(f"❌ Failed to sync positions: {e}")
    
    # ============================================================
    # LOGGING
    # ============================================================
    
    def _init_log_file(self):
        if not self.log_path.exists():
            initial_data = {
                "monitor_info": {
                    "created_at": datetime.now().isoformat(),
                    "total_symbols": len(self.symbols),
                    "reanalysis_interval": self.SYMBOL_REANALYSIS_INTERVAL,
                    "logging_policy": "ONLY_EXECUTED_TRADES"
                },
                "executed_trades": [],
                "positions": [],
                "closed_trades": [],
                "summary": {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_profit": 0.0
                }
            }
            self._write_log(initial_data)
    
    def _write_log(self, data: dict):
        try:
            with open(self.log_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"❌ Failed to write log: {e}")
    
    def _read_log(self) -> dict:
        try:
            if self.log_path.exists():
                with open(self.log_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"executed_trades": [], "positions": [], "closed_trades": []}
        except Exception:
            return {"executed_trades": [], "positions": [], "closed_trades": []}
    
    def _log_executed_trade(self, trade_result: TradeResult):
        if not trade_result.success:
            return
        
        try:
            log_data = self._read_log()
            execution_entry = {
                "timestamp": trade_result.timestamp,
                "symbol": trade_result.symbol,
                "success": trade_result.success,
                "ticket": trade_result.ticket,
                "order_type": trade_result.order_type,
                "entry_price": trade_result.entry_price,
                "stop_loss": trade_result.stop_loss,
                "take_profit": trade_result.take_profit,
                "take_profit_2": trade_result.take_profit_2,
                "take_profit_3": trade_result.take_profit_3,
                "volume": trade_result.volume,
                "actual_risk_usd": trade_result.actual_risk_usd,
                "actual_margin": trade_result.actual_margin,
                "magic": trade_result.magic,
                "comment": trade_result.comment,
            }
            
            if trade_result.full_analysis:
                execution_entry["full_analysis"] = trade_result.full_analysis
            
            log_data["executed_trades"].append(execution_entry)
            summary = log_data.get("summary", {"total_trades": 0, "winning_trades": 0, "losing_trades": 0, "total_profit": 0.0})
            summary["total_trades"] += 1
            log_data["summary"] = summary
            
            if len(log_data["executed_trades"]) > 500:
                log_data["executed_trades"] = log_data["executed_trades"][-500:]
            
            self._write_log(log_data)
            print(f"📝 EXECUTION LOGGED: {trade_result.symbol} (Ticket: {trade_result.ticket})")
            
        except Exception as e:
            print(f"❌ Failed to log execution: {e}")
    
    def _log_closed_trade(self, symbol: str, ticket: int, close_reason: str, profit: float, 
                          price_open: float, price_close: float, volume: float, sl: float, tp: float):
        try:
            log_data = self._read_log()
            executed_trade = None
            for trade in log_data.get("executed_trades", []):
                if trade.get("ticket") == ticket:
                    executed_trade = trade
                    break
            
            closed_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "ticket": ticket,
                "close_reason": close_reason,
                "profit": profit,
                "price_open": price_open,
                "price_close": price_close,
                "volume": volume,
                "sl": sl,
                "tp": tp,
                "is_winning": profit > 0,
                "original_analysis": executed_trade.get("full_analysis") if executed_trade else None
            }
            
            log_data["closed_trades"].append(closed_entry)
            summary = log_data.get("summary", {"total_trades": 0, "winning_trades": 0, "losing_trades": 0, "total_profit": 0.0})
            if profit > 0:
                summary["winning_trades"] += 1
            else:
                summary["losing_trades"] += 1
            summary["total_profit"] = round(summary["total_profit"] + profit, 2)
            log_data["summary"] = summary
            
            if len(log_data["closed_trades"]) > 1000:
                log_data["closed_trades"] = log_data["closed_trades"][-1000:]
            
            self._write_log(log_data)
            print(f"📝 CLOSED TRADE LOGGED: {symbol} (Ticket: {ticket}) - ${profit:.2f}")
            
        except Exception as e:
            print(f"❌ Failed to log closed trade: {e}")
    
    def _update_positions_log(self):
        try:
            positions = get_open_positions()
            log_data = self._read_log()
            log_data["positions"] = positions
            self._write_log(log_data)
        except Exception as e:
            print(f"❌ Failed to update positions log: {e}")
    
    # ============================================================
    # FIREBASE HELPERS
    # ============================================================
    
    def _save_trade_open_to_firebase(self, trade_result: TradeResult, analysis_result: Dict[str, Any]):
        return save_trade_open_to_firebase(
            firebase_service=self.firebase,
            trade_result=trade_result,
            analysis_result=analysis_result,
            symbol_mt5_map=self.symbol_mt5_map,
            fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
            risk_per_trade=self.RISK_PER_TRADE,
            stats=self.stats
        )
    
    # ============================================================
    # ✅ FIXED: UPDATE TRADE PRICE IN FIREBASE (USING ENCODER FROM HELPERS)
    # ✅ FIXED: Delegates to firebase_helpers for consistent encoding
    # ✅ FIXED: Ensures 18KB → 400B per point (97.8% reduction)
    # ============================================================
    
    def _update_trade_price_in_firebase(self, ticket: int, position: Dict[str, Any]):
        """
        ✅ FIXED: Update trade price with ENCODED M1, M5, H1 analysis.
        Delegates to firebase_helpers for consistent encoding.
        Updates every 60 seconds (1 minute).
        Size: 18KB → 400B per point (97.8% reduction)
        """
        current_time = time.time()
        if (current_time - self._last_price_update_time.get(ticket, 0.0)
                < self.PRICE_UPDATE_INTERVAL):
            return
        
        # ✅ Check if trade is already closed in Firebase
        if self.firebase:
            try:
                existing_trade = self.firebase.get_trade(str(ticket))
                if existing_trade:
                    existing_close = existing_trade.get("close_data", {})
                    existing_close_price = existing_close.get("close_price", 0)
                    if existing_close_price != 0:
                        print(f"⏭️ Trade {ticket} already closed in Firebase - skipping price evolution update")
                        return
            except Exception as e:
                print(f"⚠️ Could not check Firebase for ticket {ticket}: {e}")
        
        self._last_price_update_time[ticket] = current_time
        self.stats["price_updates"] = self.stats.get("price_updates", 0) + 1
        
        # ============================================================
        # ✅ DELEGATE TO FIREBASE HELPERS FOR CONSISTENT ENCODING
        # ============================================================
        return fb_update_price(
            firebase_service=self.firebase,
            ticket=ticket,
            position=position,
            symbol_mt5_map=self.symbol_mt5_map,
            fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
            risk_per_trade=self.RISK_PER_TRADE
        )
    
    # ============================================================
    # ✅ NEW: CAPTURE ANALYSIS AT CLOSE
    # ============================================================
    
    def _capture_analysis_at_close(self, symbol: str, order_type: str, 
                                    profit_usd: float = 0.0) -> Dict[str, Any]:
        """
        ✅ NEW: Capture FULL analyze_institutional_signal at trade close.
        ✅ FIXED: Include profit_usd in the captured analysis
        Returns FULL RAW analysis for M1, M5, H1.
        """
        mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
        
        if mt5_symbol == "NOT_FOUND" or mt5_symbol == "NOT_TRADABLE":
            return {}
        
        result = {
            "m1": {},
            "m5": {},
            "h1": {},
            "profit_usd": profit_usd,
            "profit_percent": 0.0,
            "result": "WIN" if profit_usd > 0 else "LOSS"
        }
        
        print(f"📊 Capturing analysis at CLOSE for {symbol} - Profit: ${profit_usd:.2f}")
        
        # M1 Analysis at Close
        try:
            m1_result = analyze_institutional_signal(
                symbol=mt5_symbol,
                order_type=order_type,
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="M1",
                debug=False
            )
            if m1_result.get("success", False):
                result["m1"] = m1_result
                print(f"   M1: Captured (Conf: {m1_result.get('⭐ CONFIDENCE', '0%')})")
        except Exception as e:
            print(f"   M1: Error - {e}")
        
        # M5 Analysis at Close
        try:
            m5_result = analyze_institutional_signal(
                symbol=mt5_symbol,
                order_type=order_type,
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="M5",
                debug=False
            )
            if m5_result.get("success", False):
                result["m5"] = m5_result
                print(f"   M5: Captured (Conf: {m5_result.get('⭐ CONFIDENCE', '0%')})")
        except Exception as e:
            print(f"   M5: Error - {e}")
        
        # H1 Analysis at Close
        try:
            h1_result = analyze_institutional_signal(
                symbol=mt5_symbol,
                order_type=order_type,
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="H1",
                debug=False
            )
            if h1_result.get("success", False):
                result["h1"] = h1_result
                print(f"   H1: Captured (Conf: {h1_result.get('⭐ CONFIDENCE', '0%')})")
        except Exception as e:
            print(f"   H1: Error - {e}")
        
        return result
    
    # ============================================================
    # ✅ FIXED: SAVE ANALYSIS AT CLOSE TO FIREBASE (WITH PROFIT)
    # ============================================================
    
    def _save_analysis_at_close_to_firebase(self, ticket: int, symbol: str, 
                                             order_type: str, close_analysis: Dict[str, Any]):
        """
        ✅ FIXED: Save analysis_at_close to Firebase with correct doc_id and profit.
        """
        if not self.firebase:
            return False
        
        try:
            # Extract profit from close_analysis
            profit_usd = close_analysis.get("profit_usd", 0.0)
            profit_percent = close_analysis.get("profit_percent", 0.0)
            result = close_analysis.get("result", "UNKNOWN")
            
            # Build analysis_at_close data WITH PROFIT
            analysis_at_close = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "order_type": order_type,
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "result": result,
                "m1_analysis_raw": close_analysis.get("m1", {}),
                "m5_analysis_raw": close_analysis.get("m5", {}),
                "h1_analysis_raw": close_analysis.get("h1", {}),
                "⭐ CONFIDENCE": close_analysis.get("m1", {}).get("⭐ CONFIDENCE", "0%"),
                "🎯 FINAL_DECISION": close_analysis.get("m1", {}).get("🎯 FINAL_DECISION", "HOLD"),
                "💰 ENTRY": close_analysis.get("m1", {}).get("💰 ENTRY", 0),
                "🛑 STOP_LOSS": close_analysis.get("m1", {}).get("🛑 STOP_LOSS", 0),
                "🎯 TAKE_PROFIT_1": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_1", 0),
                "🎯 TAKE_PROFIT_2": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_2", 0),
                "🎯 TAKE_PROFIT_3": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_3", 0),
                "📊 LOT_SIZE": close_analysis.get("m1", {}).get("📊 LOT_SIZE", 0),
                "💵 RISK_USD": close_analysis.get("m1", {}).get("💵 RISK_USD", 0),
                "📈 REWARD_USD": close_analysis.get("m1", {}).get("📈 REWARD_USD", 0),
                "💰 MARGIN_REQUIRED_USD": close_analysis.get("m1", {}).get("💰 MARGIN_REQUIRED_USD", 0),
                "🚀 SIMPLE_ACTION": close_analysis.get("m1", {}).get("🚀 SIMPLE_ACTION", "HOLD"),
                "🚀 REASON": close_analysis.get("m1", {}).get("🚀 REASON", ""),
                "📈 RISK_REWARD": close_analysis.get("m1", {}).get("📈 RISK_REWARD", "1:0"),
            }
            
            # Make JSON-safe
            analysis_at_close_safe = make_json_safe(analysis_at_close)
            
            # ✅ FIXED: Use "trade_" prefix for doc_id
            doc_id = f"trade_{ticket}"
            self.firebase._write_immediate(
                "trades", 
                doc_id, 
                {"analysis_at_close": analysis_at_close_safe}, 
                "update"
            )
            
            print(f"✅ analysis_at_close saved for {symbol} (Ticket: {ticket}) - Profit: ${profit_usd:.2f}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to save analysis_at_close: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # ============================================================
    # ✅ FIXED: SAVE TRADE CLOSE TO FIREBASE (WITH PROFIT)
    # ============================================================
    
    def _save_trade_close_to_firebase(self, symbol: str, ticket: int, close_reason: str, 
                                       profit: float, price_open: float, price_close: float, 
                                       volume: float, sl: float, tp: float, 
                                       is_webhook: bool = False,
                                       close_analysis: Dict[str, Any] = None):
        """
        ✅ FIXED: Save trade close with correct profit from webhook or monitor.
        """
        # ✅ CHECK IF ALREADY CLOSED IN FIREBASE
        if self.firebase:
            try:
                existing_trade = self.firebase.get_trade(str(ticket))
                if existing_trade:
                    existing_close = existing_trade.get("close_data", {})
                    existing_close_price = existing_close.get("close_price", 0)
                    if existing_close_price != 0:
                        print(f"⚠️ Trade {ticket} already closed in Firebase - skipping duplicate save")
                        return False
            except Exception as e:
                print(f"⚠️ Could not check Firebase: {e}")
        
        # ✅ Calculate profit percent
        profit_percent = 0.0
        if price_open > 0 and volume > 0:
            # Calculate based on pip value approximation
            pip_value = 0.0001  # Default for forex
            symbol_upper = symbol.upper()
            if "JPY" in symbol_upper:
                pip_value = 0.01
            elif "XAU" in symbol_upper or "GOLD" in symbol_upper:
                pip_value = 0.01
            elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
                pip_value = 0.001
            elif ".NAS" in symbol_upper or ".NYSE" in symbol_upper:
                pip_value = 0.01
            elif any(c in symbol_upper for c in ["BTC", "ETH", "SOL", "BNB", "LTC", "XRP"]):
                pip_value = 0.01
            
            # Notional uses the REAL contract size, not the FX 100000: that
            # constant is 1000x wrong on gold and wrong again on oil, so the
            # percentage it produced was meaningless for anything but FX.
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            size = contract_size(mt5_symbol)
            notional = price_open * volume * size if size else 0
            profit_percent = (profit / notional) * 100 if notional else 0.0

        # ✅ If close_analysis not provided, capture it now
        if close_analysis is None:
            # Direction is LOOKED UP, never inferred from the price move.
            # `"BUY" if price_close > price_open else "SELL"` derives the
            # direction from the OUTCOME -- it records which way the price
            # went and calls it the trade. That is the same defect fixed in
            # monitor/firebase_helpers.py, and this was a second copy of it:
            # here it selected which side _capture_analysis_at_close analysed,
            # so a losing trade had its close analysed from the wrong side.
            order_type = _direction_of_record(ticket) or "BUY"
            close_analysis = self._capture_analysis_at_close(symbol, order_type, profit)
            # Add profit percent to analysis
            close_analysis["profit_percent"] = profit_percent
        
        # ✅ Save analysis_at_close to Firebase
        self._save_analysis_at_close_to_firebase(
            # Looked up, not inferred from the price move -- see
            # core/broker_facts.py and monitor/firebase_helpers._direction_of_record.
            ticket, symbol,
            _direction_of_record(ticket) or "BUY",
            close_analysis
        )
        
        # ✅ Then save the close data
        return save_trade_close_to_firebase(
            firebase_service=self.firebase,
            symbol=symbol,
            ticket=ticket,
            close_reason=close_reason,
            profit=profit,
            price_open=price_open,
            price_close=price_close,
            volume=volume,
            sl=sl,
            tp=tp,
            symbol_mt5_map=self.symbol_mt5_map,
            fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
            risk_per_trade=self.RISK_PER_TRADE,
            is_webhook=is_webhook,
            close_analysis=close_analysis
        )
    
    def _save_trailing_stop_to_firebase(self, ticket: int, symbol: str, action: str,
                                         sl_price: float, profit_pips: float,
                                         step_pips: float, price: float = None,
                                         entry_price: float = None, timestamp: str = None):
        self.stats["trailing_updates"] = self.stats.get("trailing_updates", 0) + 1
        return save_trailing_stop_to_firebase(
            firebase_service=self.firebase,
            ticket=ticket,
            symbol=symbol,
            action=action,
            sl_price=sl_price,
            profit_pips=profit_pips,
            step_pips=step_pips,
            price=price,
            entry_price=entry_price,
            timestamp=timestamp
        )
    
    # ============================================================
    # ✅ FIXED: WEBHOOK HANDLERS - PROPERLY PASS PROFIT
    # ============================================================
    
    def handle_webhook_close(self, symbol: str, ticket: int, close_reason: str,
                              profit: float, price_open: float, price_close: float,
                              volume: float, sl: float, tp: float, close_time: str):
        """✅ FIXED: Handle webhook order closure with correct profit."""
        print("=" * 80)
        print(f"📨 WEBHOOK CLOSE: {symbol} (Ticket: {ticket}) - {close_reason}")
        print(f"   Profit: ${profit:.2f} | Open: {price_open} | Close: {price_close}")
        print(f"   Volume: {volume} | SL: {sl} | TP: {tp}")
        print("=" * 80)
        
        self.stats["webhook_closes"] = self.stats.get("webhook_closes", 0) + 1
        
        # ✅ Capture analysis at close with profit from webhook
        # Webhook close: direction still comes from the record, never from
        # which way the price happened to move.
        order_type = _direction_of_record(ticket) or "BUY"
        close_analysis = self._capture_analysis_at_close(symbol, order_type, profit)
        
        # ✅ Save directly with profit from webhook
        result = self._save_trade_close_to_firebase(
            symbol=symbol,
            ticket=ticket,
            close_reason=close_reason,
            profit=profit,  # ✅ PASS PROFIT FROM WEBHOOK!
            price_open=price_open,
            price_close=price_close,
            volume=volume,
            sl=sl,
            tp=tp,
            is_webhook=True,
            close_analysis=close_analysis
        )
        
        if result:
            with self._state_lock:
                self._webhook_closed_tickets.add(ticket)
                # Clean up from local state
                if symbol in self.open_positions:
                    del self.open_positions[symbol]
                if symbol in self.symbol_status_map:
                    self.symbol_status_map[symbol].in_position = False
                    self.symbol_status_map[symbol].ticket = None
                if ticket in self._position_data_cache:
                    del self._position_data_cache[ticket]
                self.stats["trades_closed"] = self.stats.get("trades_closed", 0) + 1
            
            self._update_positions_log()
            print(f"✅ Webhook close processed successfully for {symbol} (Profit: ${profit:.2f})")
        else:
            print(f"❌ Webhook close failed for {symbol}")
        
        return result
    
    def handle_trailing_webhook(self, data: Dict[str, Any]):
        """Handle trailing stop webhook using firebase_helpers."""
        print(f"📨 TRAILING WEBHOOK: {data}")
        
        return process_trailing_webhook(
            firebase_service=self.firebase,
            monitor=self,
            data=data
        )
    
    # ============================================================
    # FILTER STEP - ✅ FIXED: Added trade mode check
    # ============================================================
    
    def _check_market_conditions(self, symbol: str) -> Dict[str, Any]:
        """
        ✅ FIXED: Check market conditions including trade mode.
        """
        result = {"symbol": symbol, "passed": False, "reasons": []}
        
        try:
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            if mt5_symbol == "NOT_FOUND":
                result["reasons"].append(f"Symbol '{symbol}' not found in MT5")
                return result
            
            if mt5_symbol == "NOT_TRADABLE":
                result["reasons"].append(f"Symbol '{symbol}' is not tradable")
                return result
            
            info = mt5.symbol_info(mt5_symbol)
            if not info:
                result["reasons"].append(f"Symbol '{mt5_symbol}' not available")
                return result
            
            # ✅ Check if trading is allowed for this symbol
            if info.trade_mode not in [
                mt5.SYMBOL_TRADE_MODE_FULL, 
                mt5.SYMBOL_TRADE_MODE_LONGONLY, 
                mt5.SYMBOL_TRADE_MODE_SHORTONLY
            ]:
                result["reasons"].append(f"Trading not allowed for {mt5_symbol}")
                # Add to permanent exclusion
                with self._state_lock:
                    self.permanently_excluded.add(symbol)
                return result
            
            """  market_status = is_market_closed(mt5_symbol)
            is_closed = market_status.get("is_closed", True)
            success = market_status.get("success", False)
            
            if not success:
                result["reasons"].append(f"Market status check failed for {mt5_symbol}")
                return result
            
            if is_closed:
                reason = market_status.get("reason", "Market closed")
                result["reasons"].append(reason)
                return result
            
            volatility = check_volatility(mt5_symbol)
            if not volatility.get("success", False):
                result["reasons"].append("Volatility check failed")
                return result
            
            if volatility.get("volatility_level") == "HIGH":
                result["reasons"].append("Volatility too high")
                return result
            """
            """ spread = check_spread_status(mt5_symbol)
            if not spread.get("success", False):
                result["reasons"].append("Spread check failed")
                return result
            
            if not spread.get("is_acceptable", False):
                spread_pips = spread.get("spread_pips", 0)
                max_spread = spread.get("max_spread", 30)
                result["reasons"].append(f"Spread too high ({spread_pips:.1f} > {max_spread})")
                return result """
            
            result["passed"] = True
            return result
            
        except Exception as e:
            result["reasons"].append(f"Error: {str(e)}")
            return result
    
    def _filter_worker(self, symbols: List[str]) -> List[Dict[str, Any]]:
        results = []
        for symbol in symbols:
            if self.stop_event.is_set():
                break
            
            result = self._check_market_conditions(symbol)
            results.append(result)
        
        return results
    
    def _run_filter_step(self):
        print(f"{'='*60}")
        print(f"🔍 FILTERING {len(self.symbols)} SYMBOLS")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        chunk_size = max(2, len(self.symbols) // self.FILTER_THREADS)
        chunks = [self.symbols[i:i + chunk_size] for i in range(0, len(self.symbols), chunk_size)]
        
        passed_symbols = []
        all_results = []
        
        # ✅ FIXED: reuse the persistent pool instead of creating a brand new
        # ThreadPoolExecutor (and blocking on its shutdown) every filter cycle.
        futures = [self._filter_pool.submit(self._filter_worker, chunk) for chunk in chunks]
        try:
            for future in as_completed(futures, timeout=20):
                try:
                    results = future.result(timeout=5)
                    all_results.extend(results)
                    for result in results:
                        if result.get("passed", False):
                            passed_symbols.append(result["symbol"])
                except Exception as e:
                    print(f"❌ Filter worker error: {e}")
                    self.stats["filter_errors"] += 1
        except TimeoutError:
            done = sum(1 for f in futures if f.done())
            print(f"⏰ Filter step timed out — {done}/{len(futures)} chunks finished, using what we have")
            self.stats["filter_errors"] += 1
        
        with self._state_lock:
            self.filtered_symbols = set(passed_symbols)
            self.stats["filtered_count"] = len(passed_symbols)
            self.stats["last_filter_time"] = time.time()
        
        elapsed = time.time() - start_time
        
        print(f"{'='*60}")
        print(f"✅ FILTER COMPLETE: {len(passed_symbols)}/{len(self.symbols)} symbols passed in {elapsed:.1f}s")
        print(f"{'='*60}")
        print(f"📊 PASSED SYMBOLS ({len(passed_symbols)}):")
        if passed_symbols:
            print(f"   {', '.join(passed_symbols)}")
        else:
            print("   (none)")
        
        excluded_results = [r for r in all_results if not r.get("passed", False)]
        if excluded_results:
            print(f"📊 EXCLUDED SYMBOLS ({len(excluded_results)}):")
            for r in excluded_results:
                reasons = ", ".join(r.get("reasons", []))
                print(f"   ❌ {r['symbol']}: {reasons}")
        
        print(f"{'='*60}")
        
        if len(passed_symbols) < self.MIN_SYMBOLS_TO_TRADE:
            print(f"⚠️ Only {len(passed_symbols)} symbols passed filter (need {self.MIN_SYMBOLS_TO_TRADE})")
            self._filter_retry_count += 1
            self.stats["filter_retry_count"] = self._filter_retry_count
            return False
        
        self._filter_retry_count = 0
        return True
    
    # ============================================================
    # REFRESH TOP SYMBOLS
    # ============================================================
    
    def _check_confidence(self, symbol: str) -> Dict[str, Any]:
        try:
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            if mt5_symbol == "NOT_FOUND" or mt5_symbol == "NOT_TRADABLE":
                return {"symbol": symbol, "confidence": 0}
            
            result = analyze_institutional_signal(
                symbol=mt5_symbol,
                order_type="BUY",
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="M1",
                debug=False
            )
            
            if not result.get("success", False):
                return {"symbol": symbol, "confidence": 0}
            
            final_verdict = result.get("final_verdict", {})
            overall_confidence = final_verdict.get("probability_percent", 0)
            
            # ✅ FIXED: Extract Entry Confidence without a false "== 50" sentinel.
            # timing_confidence can legitimately BE 50 (neutral weight), so we must
            # use presence-of-key (None) rather than value-equality to detect "missing".
            entry_analysis = result.get("entry_analysis", {})
            entry_confidence = entry_analysis.get("timing_confidence")
            if entry_confidence is None:
                micro_structure = entry_analysis.get("micro_structure", {})
                entry_confidence = micro_structure.get("timing_confidence")
                if entry_confidence is None:
                    # ✅ FIXED: was a final hardcoded 50 fallback — for symbols
                    # where micro-structure was never computed (e.g. INVALID_ZONE),
                    # this made "Entry: 50%" show up as if it were real data. None
                    # now propagates through to display as "N/A" instead.
                    entry_confidence = micro_structure.get("entry_confidence")
            
            discount = entry_analysis.get("discount", {})
            is_at_discount = discount.get("is_already_at_discount", False)
            discount_quality = discount.get("discount_quality", "NONE")
            
            return {
                "symbol": symbol, 
                "overall_confidence": overall_confidence,
                "entry_confidence": entry_confidence,
                "full_response": result,
                "discount": {
                    "is_at_discount": is_at_discount,
                    "quality": discount_quality
                }
            }
        except Exception as e:
            return {"symbol": symbol, "overall_confidence": 0, "entry_confidence": 0}
    
    def _refresh_worker(self, symbols: List[str]) -> List[Dict[str, Any]]:
        results = []
        for symbol in symbols:
            if self.stop_event.is_set():
                break
            with self._state_lock:
                if symbol in self.open_positions:
                    continue
            try:
                result = self._check_confidence(symbol)
                results.append(result)
            except Exception:
                pass
        return results
    
    def _refresh_top_symbols(self):
        with self._state_lock:
            symbols_to_check = [s for s in self.filtered_symbols if s not in self.open_positions]
        
        if not symbols_to_check:
            print("⚠️ No symbols to check for confidence")
            return []
        
        with self._refresh_lock:
            if self._refreshing:
                return []
            self._refreshing = True
        
        try:
            print(f"📊 Checking confidence for {len(symbols_to_check)} symbols...")
            chunk_size = max(1, min(len(symbols_to_check) // self.FILTER_THREADS, 3))
            chunks = [symbols_to_check[i:i + chunk_size] for i in range(0, len(symbols_to_check), chunk_size)]
            all_results = []
            
            # ✅ FIXED: reuse the persistent pool instead of creating a new
            # ThreadPoolExecutor (and blocking on its shutdown) every cycle.
            futures = [self._filter_pool.submit(self._refresh_worker, chunk) for chunk in chunks]
            try:
                for future in as_completed(futures, timeout=20):
                    try:
                        results = future.result(timeout=8)
                        all_results.extend(results)
                    except Exception:
                        pass
            except TimeoutError:
                done = sum(1 for f in futures if f.done())
                print(f"⏰ Refresh timed out — {done}/{len(futures)} chunks finished, using what we have")
            
            valid_symbols = []
            for item in all_results:
                overall_conf = item.get("overall_confidence", 0)
                if overall_conf >= self.MIN_CONFIDENCE_THRESHOLD:
                    valid_symbols.append(item)
            
            valid_symbols.sort(key=lambda x: x.get("overall_confidence", 0), reverse=True)
            top = valid_symbols[:self.TOP_SYMBOLS_COUNT]
            
            with self._state_lock:
                self.top_symbols = []
                top_symbols_at_discount = set()
                for item in top:
                    symbol = item["symbol"]
                    overall_conf = item.get("overall_confidence", 0)
                    entry_conf = item.get("entry_confidence", 0)
                    entry_conf_display = "N/A" if entry_conf is None else f"{entry_conf}%"
                    discount_info = item.get("discount", {})
                    is_at_discount = discount_info.get("is_at_discount", False)
                    discount_quality = discount_info.get("quality", "NONE")
                    
                    discount_str = ""
                    if is_at_discount:
                        discount_str = f" 💰 DISCOUNT ({discount_quality})"
                        top_symbols_at_discount.add(symbol)
                    
                    status = SymbolStatus(
                        symbol=symbol,
                        confidence=overall_conf,
                        is_active=True,
                        exchange=self.SYMBOL_EXCHANGE_MAP.get(symbol, "CRYPTO"),
                        reason=f"Overall: {overall_conf}% | Entry: {entry_conf_display}{discount_str}",
                        last_check_time=time.time()
                    )
                    self.top_symbols.append(status)
                    self.symbol_status_map[symbol] = status
                
                self.stats["last_refresh_time"] = time.time()
            
            # ✅ FIXED: _fast_entry_symbols was never populated anywhere in this file —
            # it was only ever drained via .discard(), so the fast-entry-check thread
            # (which polls every 10s) had nothing to check and both "Fast Entry Symbols"
            # and "Fast Entry Checks" stayed permanently at 0. Symbols that are already
            # at a valid discount zone are exactly the ones that need tight 10s polling
            # for a confirmation candle, so we sync the set to match them here.
            with self._fast_entry_lock:
                self._fast_entry_symbols = top_symbols_at_discount
            
            if top:
                print(f"📈 Top {len(top)} symbols:")
                for i, item in enumerate(top, 1):
                    symbol = item['symbol']
                    overall_conf = item.get("overall_confidence", 0)
                    entry_conf = item.get("entry_confidence", 0)
                    entry_conf_display = "N/A" if entry_conf is None else f"{entry_conf}%"
                    discount_info = item.get("discount", {})
                    is_at_discount = discount_info.get("is_at_discount", False)
                    discount_str = " 💰 DISCOUNT!" if is_at_discount else ""
                    print(f"  #{i}: {symbol} - Overall: {overall_conf}% | Entry: {entry_conf_display}{discount_str}")
            else:
                print(f"⚠️ No symbols above {self.MIN_CONFIDENCE_THRESHOLD}% confidence")
            
            return top
        finally:
            self._refreshing = False
    
    # ============================================================
    # FAST ENTRY CHECK
    # ============================================================
    
    def _fast_entry_check_loop(self):
        """Dedicated thread to check executable symbols every 10 seconds."""
        print("🚀 Fast entry check thread started (every 10s)")
        while not self.stop_event.is_set():
            try:
                with self._fast_entry_lock:
                    symbols_to_check = list(self._fast_entry_symbols)
                
                if symbols_to_check:
                    print(f"⚡ Fast entry check: {len(symbols_to_check)} symbols")
                    
                    for symbol in symbols_to_check:
                        try:
                            with self._state_lock:
                                if symbol in self.open_positions:
                                    with self._fast_entry_lock:
                                        self._fast_entry_symbols.discard(symbol)
                                    continue
                                if symbol in self._executing_symbols:
                                    continue
                            
                            result = self._check_entry(symbol)
                            self.stats["fast_entry_checks"] = self.stats.get("fast_entry_checks", 0) + 1
                            
                            if result.get("should_enter", False):
                                overall_conf = result.get("overall_confidence", 0)
                                entry_conf = result.get("entry_confidence", 0)
                                entry_conf_display = "N/A" if entry_conf is None else f"{entry_conf}%"
                                print(f"⚡ FAST ENTRY TRIGGERED: {symbol} (Overall: {overall_conf}% | Entry: {entry_conf_display})")
                                full_response = result.get("full_response", {})
                                trade_result = self._execute_trade(symbol, full_response)
                                
                                if trade_result.success:
                                    print(f"✅✅✅ FAST EXECUTED: {symbol} - Ticket: {trade_result.ticket}")
                                    with self._executed_lock:
                                        self._executed_recently.add(symbol)
                                        self._executing_symbols.discard(symbol)
                                    with self._fast_entry_lock:
                                        self._fast_entry_symbols.discard(symbol)
                                else:
                                    if "Maximum" not in trade_result.error:
                                        print(f"❌ Fast execute failed: {symbol} - {trade_result.error}")
                                    with self._executed_lock:
                                        self._executing_symbols.discard(symbol)
                            
                        except Exception as e:
                            print(f"❌ Fast entry check error for {symbol}: {e}")
                
                time.sleep(self._fast_entry_interval)
                
            except Exception as e:
                print(f"❌ Fast entry loop error: {e}")
                time.sleep(5)
    
    # ============================================================
    # ENTRY CHECK - ✅ FIXED: Shows both overall and entry confidence
    # ============================================================
    
    def _check_entry(self, symbol: str) -> Dict[str, Any]:
        try:
            with self._state_lock:
                if symbol in self.open_positions:
                    return {"symbol": symbol, "should_enter": False}
                if symbol in self._executed_recently or symbol in self._executing_symbols:
                    return {"symbol": symbol, "should_enter": False}
            
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            if mt5_symbol == "NOT_FOUND" or mt5_symbol == "NOT_TRADABLE":
                return {"symbol": symbol, "should_enter": False}
            
            result = analyze_institutional_signal(
                symbol=mt5_symbol,
                order_type="BUY",
                fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                risk_per_trade=self.RISK_PER_TRADE,
                timeframe="M1",
                debug=False
            )
            
            if not result.get("success", False):
                return {"symbol": symbol, "should_enter": False}
            
            entry_analysis = result.get("entry_analysis", {})
            final_verdict = result.get("final_verdict", {})
            
            should_enter = entry_analysis.get("should_enter", False)
            overall_confidence = final_verdict.get("probability_percent", 0)
            
            # ✅ FIXED: Extract Entry Confidence without a false "== 50" sentinel.
            # timing_confidence can legitimately BE 50 (neutral weight), so we must
            # use presence-of-key (None) rather than value-equality to detect "missing".
            entry_confidence = entry_analysis.get("timing_confidence")
            if entry_confidence is None:
                micro_structure = entry_analysis.get("micro_structure", {})
                entry_confidence = micro_structure.get("timing_confidence")
                if entry_confidence is None:
                    # ✅ FIXED: was a final hardcoded 50 fallback — for symbols
                    # where micro-structure was never computed (e.g. INVALID_ZONE),
                    # this made "Entry: 50%" show up as if it were real data. None
                    # now propagates through to display as "N/A" instead.
                    entry_confidence = micro_structure.get("entry_confidence")
            
            discount = entry_analysis.get("discount", {})
            is_at_discount = discount.get("is_already_at_discount", False)
            discount_quality = discount.get("discount_quality", "NONE")
            discount_str = " 💰 DISCOUNT!" if is_at_discount else ""
            
            # ✅ FIXED: Display BOTH confidences. entry_confidence can now be None
            # (e.g. INVALID_ZONE, where timing genuinely isn't computed) — show
            # "N/A" instead of silently formatting None as if it were a number.
            entry_confidence_display = "N/A" if entry_confidence is None else f"{entry_confidence}%"
            print(f"📊 {symbol}: Overall: {overall_confidence}% | Entry: {entry_confidence_display} | Action: {'✅ ENTER' if should_enter else '⏳ WAIT'}{discount_str}")
            
            if should_enter and overall_confidence >= self.MIN_CONFIDENCE_THRESHOLD:
                print(f"🚀 ENTRY SIGNAL: {symbol} (Overall: {overall_confidence}% | Entry: {entry_confidence_display}){discount_str}")
                
                return {
                    "symbol": symbol,
                    "should_enter": True,
                    "overall_confidence": overall_confidence,
                    "entry_confidence": entry_confidence,
                    "full_response": result,
                    "discount": {
                        "is_at_discount": is_at_discount,
                        "quality": discount_quality
                    }
                }
            else:
                reason = ""
                if not should_enter:
                    reason = "Entry conditions not met"
                elif overall_confidence < self.MIN_CONFIDENCE_THRESHOLD:
                    reason = f"Overall {overall_confidence}% < {self.MIN_CONFIDENCE_THRESHOLD}%"
                
                print(f"⏳ {symbol}: {reason}")
                
                return {
                    "symbol": symbol,
                    "should_enter": False,
                    "reason": reason,
                    "overall_confidence": overall_confidence,
                    "entry_confidence": entry_confidence,
                    "discount": {
                        "is_at_discount": is_at_discount,
                        "quality": discount_quality
                    }
                }
                
        except Exception as e:
            print(f"❌ Entry check error for {symbol}: {e}")
            return {"symbol": symbol, "should_enter": False}
    
    def _monitor_worker(self, symbol: str) -> Dict[str, Any]:
        try:
            return self._check_entry(symbol)
        except Exception as e:
            print(f"❌ Monitor worker error for {symbol}: {e}")
            return {"symbol": symbol, "should_enter": False}
    
    # ============================================================
    # MONITOR STEP
    # ============================================================
    
    def _run_monitor_step(self):
        self._sync_open_positions()
        current_time = time.time()
        
        with self._state_lock:
            for status in self.top_symbols:
                if status.is_active and not status.in_position:
                    if current_time - status.last_check_time > self.STALE_SYMBOL_THRESHOLD:
                        with self._reanalysis_lock:
                            if status.symbol not in self._reanalysis_queue:
                                self._reanalysis_queue.append(status.symbol)
                                print(f"🔄 Added stale symbol: {status.symbol}")
        
        with self._state_lock:
            symbols_to_monitor = []
            for s in self.top_symbols:
                if (s.is_active and not s.in_position and 
                    s.symbol not in self._executed_recently and
                    s.symbol not in self._executing_symbols):
                    if current_time - s.last_check_time >= self.SYMBOL_COOLDOWN:
                        symbols_to_monitor.append(s.symbol)
        
        if not symbols_to_monitor:
            return
        
        monitor_count = min(len(symbols_to_monitor), self.MONITOR_THREADS)
        
        # ✅ FIXED: reuse the persistent pool instead of creating/tearing down
        # a new ThreadPoolExecutor every 5-second scan cycle. The old
        # `with ThreadPoolExecutor(...) as executor:` blocked on
        # shutdown(wait=True) on exit — one hung worker call froze this whole
        # loop (and every symbol behind it) forever, with a fresh
        # never-finishing pool piling up every cycle after. A hung task now
        # just occupies one pool slot instead of freezing everything.
        futures = []
        for symbol in symbols_to_monitor[:monitor_count]:
            future = self._monitor_pool.submit(self._monitor_worker, symbol)
            futures.append((symbol, future))
        
        for symbol, future in futures:
            try:
                result = future.result(timeout=10)
                
                if result.get("should_enter", False):
                    with self._executed_lock:
                        self._executing_symbols.add(symbol)
                    
                    try:
                        full_response = result.get("full_response", {})
                        trade_result = self._execute_trade(symbol, full_response)
                        
                        if trade_result.success:
                            print(f"✅✅✅ EXECUTED: {symbol} - Ticket: {trade_result.ticket}")
                            with self._executed_lock:
                                self._executed_recently.add(symbol)
                                self._executing_symbols.discard(symbol)
                            with self._state_lock:
                                if symbol in self.symbol_status_map:
                                    self.symbol_status_map[symbol].last_check_time = time.time()
                        else:
                            if "Maximum" not in trade_result.error:
                                print(f"❌ Failed: {symbol} - {trade_result.error}")
                            with self._executed_lock:
                                self._executing_symbols.discard(symbol)
                    except Exception as e:
                        print(f"❌ Execution error: {symbol} - {e}")
                        with self._executed_lock:
                            self._executing_symbols.discard(symbol)
                else:
                    with self._state_lock:
                        if symbol in self.symbol_status_map:
                            self.symbol_status_map[symbol].last_check_time = time.time()
            except TimeoutError:
                print(f"⏰ Monitor timeout for {symbol}")
                future.cancel()
                with self._executed_lock:
                    self._executing_symbols.discard(symbol)
            except Exception as e:
                print(f"❌ Monitor error for {symbol}: {e}")
                with self._executed_lock:
                    self._executing_symbols.discard(symbol)
    
    # ============================================================
    # REANALYSIS
    # ============================================================
    
    def _run_symbol_reanalysis(self):
        current_time = time.time()
        if current_time - self._last_reanalysis_time < self.SYMBOL_REANALYSIS_INTERVAL:
            return
        
        with self._reanalysis_lock:
            self._last_reanalysis_time = current_time
            self.stats["reanalysis_count"] += 1
        
        with self._state_lock:
            eligible_symbols = [s for s in self.filtered_symbols if s not in self.open_positions]
        
        if not eligible_symbols:
            return
        
        with self._reanalysis_lock:
            if not self._reanalysis_queue:
                shuffled = eligible_symbols.copy()
                random.shuffle(shuffled)
                self._reanalysis_queue = shuffled
        
        with self._reanalysis_lock:
            batch = self._reanalysis_queue[:self.SYMBOL_REANALYSIS_BATCH_SIZE]
            self._reanalysis_queue = self._reanalysis_queue[self.SYMBOL_REANALYSIS_BATCH_SIZE:]
        
        if not batch:
            return
        
        print(f"🔄 Reanalyzing batch ({len(batch)} symbols): {batch}")
        
        for symbol in batch:
            try:
                with self._state_lock:
                    if symbol in self.open_positions:
                        continue
                
                mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
                if mt5_symbol == "NOT_FOUND" or mt5_symbol == "NOT_TRADABLE":
                    continue
                
                result = analyze_institutional_signal(
                    symbol=mt5_symbol,
                    order_type="BUY",
                    fixed_trade_size_usd=self.FIXED_TRADE_SIZE_USD,
                    risk_per_trade=self.RISK_PER_TRADE,
                    timeframe="M1",
                    debug=False
                )
                
                if not result.get("success", False):
                    continue
                
                final_verdict = result.get("final_verdict", {})
                confidence = final_verdict.get("probability_percent", 0)
                
                with self._state_lock:
                    found = False
                    for status in self.top_symbols:
                        if status.symbol == symbol:
                            if confidence > status.confidence:
                                old_conf = status.confidence
                                status.confidence = confidence
                                status.last_check_time = time.time()
                                print(f"📊 {symbol}: {old_conf}% → {confidence}%")
                            found = True
                            break
                    
                    if not found and confidence >= self.MIN_CONFIDENCE_THRESHOLD:
                        if len(self.top_symbols) < self.TOP_SYMBOLS_COUNT:
                            status = SymbolStatus(
                                symbol=symbol,
                                confidence=confidence,
                                is_active=True,
                                exchange=self.SYMBOL_EXCHANGE_MAP.get(symbol, "CRYPTO"),
                                reason="🔵 NEW",
                                last_check_time=time.time()
                            )
                            self.top_symbols.append(status)
                            self.symbol_status_map[symbol] = status
                            print(f"➕ Added new symbol: {symbol} @ {confidence}%")
                        else:
                            lowest = min(self.top_symbols, key=lambda x: x.confidence)
                            if confidence > lowest.confidence:
                                old_symbol = lowest.symbol
                                lowest.symbol = symbol
                                lowest.confidence = confidence
                                lowest.exchange = self.SYMBOL_EXCHANGE_MAP.get(symbol, "CRYPTO")
                                lowest.reason = "🔄 REPLACED"
                                lowest.last_check_time = time.time()
                                if old_symbol in self.symbol_status_map:
                                    del self.symbol_status_map[old_symbol]
                                self.symbol_status_map[symbol] = lowest
                                print(f"🔄 Replaced {old_symbol} with {symbol} @ {confidence}%")
            except Exception as e:
                print(f"❌ Reanalysis error for {symbol}: {e}")
        
        with self._state_lock:
            self.top_symbols.sort(key=lambda x: x.confidence, reverse=True)
    
    # ============================================================
    # EXECUTION - ✅ FIXED: Trade mode check with permanent exclusion
    # ============================================================
    
    def _validate_trade_params(self, symbol: str, order_type: str, entry_price: float, 
                               stop_loss: float, take_profit: float) -> Tuple[bool, str]:
        mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
        if mt5_symbol == "NOT_FOUND":
            return False, f"Symbol not found: {symbol}"
        
        symbol_info = mt5.symbol_info(mt5_symbol)
        if not symbol_info:
            return False, f"Symbol info not found: {symbol}"
        
        min_sl_pips = 1
        
        if "JPY" in mt5_symbol:
            pip_size = 0.01
        elif any(x in mt5_symbol for x in ["XAU", "GOLD"]):
            pip_size = 0.01 if symbol_info.digits == 2 else 0.1
        elif any(x in mt5_symbol for x in ["XAG", "SILVER"]):
            pip_size = 0.001 if symbol_info.digits == 3 else 0.01
        elif any(x in mt5_symbol for x in ["BTC", "ETH", "SOL", "BNB", "LTC", "XRP"]):
            pip_size = 0.01 if symbol_info.digits == 2 else (0.1 if symbol_info.digits == 1 else symbol_info.point)
        else:
            pip_size = 0.0001 if symbol_info.digits in [4, 5] else symbol_info.point
        
        if order_type == "BUY":
            sl_distance = (entry_price - stop_loss) / pip_size
            tp_distance = (take_profit - entry_price) / pip_size
        else:
            sl_distance = (stop_loss - entry_price) / pip_size
            tp_distance = (entry_price - take_profit) / pip_size
        
        if sl_distance < min_sl_pips:
            return False, f"SL too tight: {sl_distance:.1f} pips (min {min_sl_pips})"
        if tp_distance < min_sl_pips:
            return False, f"TP too close: {tp_distance:.1f} pips (min {min_sl_pips})"
        
        return True, "Valid"
    
    def _execute_trade(self, symbol: str, analysis_result: Dict[str, Any]) -> TradeResult:
        """
        ✅ FIXED: Execute trade with trade mode validation.
        ✅ FIXED: Populate position cache for fallback detection.
        """
        try:
            with self._state_lock:
                if len(self.open_positions) >= self.MAX_SIMULTANEOUS_TRADES:
                    return TradeResult(symbol, False, error="Max trades reached")
                if symbol in self.open_positions:
                    return TradeResult(symbol, False, error="Already in trade")
            
            final_verdict = analysis_result.get("final_verdict", {})
            if not final_verdict:
                return TradeResult(symbol, False, error="No final_verdict")
            
            stop_loss = final_verdict.get("stop_loss")
            take_profit_1 = final_verdict.get("take_profit_1")
            entry_price = final_verdict.get("entry_price")
            confidence = final_verdict.get("probability_percent", 0)
            
            config_data = analysis_result.get("config", {})
            order_type = config_data.get("executed_direction", "BUY")
            
            if not stop_loss:
                return TradeResult(symbol, False, error="No stop loss")
            if not take_profit_1:
                return TradeResult(symbol, False, error="No take profit")
            
            mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
            if mt5_symbol == "NOT_FOUND":
                return TradeResult(symbol, False, error=f"Symbol {symbol} not found in MT5")
            
            # ✅ NEW: Check if trading is allowed BEFORE any other checks
            symbol_info = mt5.symbol_info(mt5_symbol)
            if not symbol_info:
                return TradeResult(symbol, False, error=f"Symbol info not found: {symbol}")
            
            if symbol_info.trade_mode not in [
                mt5.SYMBOL_TRADE_MODE_FULL, 
                mt5.SYMBOL_TRADE_MODE_LONGONLY, 
                mt5.SYMBOL_TRADE_MODE_SHORTONLY
            ]:
                # ✅ Add to permanent exclusion to prevent future attempts
                with self._state_lock:
                    self.permanently_excluded.add(symbol)
                    if symbol in self.filtered_symbols:
                        self.filtered_symbols.discard(symbol)
                    if symbol in self.top_symbols:
                        self.top_symbols = [s for s in self.top_symbols if s.symbol != symbol]
                    if symbol in self.symbol_status_map:
                        del self.symbol_status_map[symbol]
                print(f"❌ Trading not allowed for {symbol} - permanently excluded")
                return TradeResult(symbol, False, error=f"Trading not allowed for {symbol}")
            
            tick = mt5.symbol_info_tick(mt5_symbol)
            if not tick:
                return TradeResult(symbol, False, error="Cannot get tick data")
            
            current_ask = tick.ask
            current_bid = tick.bid
            
            if order_type == "BUY":
                entry_price = current_ask
                sl_distance = abs(entry_price - stop_loss)
                tp_distance = abs(take_profit_1 - entry_price)
                if sl_distance < 0.0001:
                    sl_distance = 0.0010
                if tp_distance < 0.0001:
                    tp_distance = 0.0010
                stop_loss = entry_price - sl_distance
                take_profit_1 = entry_price + tp_distance
            else:
                entry_price = current_bid
                sl_distance = abs(entry_price - stop_loss)
                tp_distance = abs(take_profit_1 - entry_price)
                if sl_distance < 0.0001:
                    sl_distance = 0.0010
                if tp_distance < 0.0001:
                    tp_distance = 0.0010
                stop_loss = entry_price + sl_distance
                take_profit_1 = entry_price - tp_distance
            
            is_valid, validation_msg = self._validate_trade_params(symbol, order_type, entry_price, stop_loss, take_profit_1)
            if not is_valid:
                return TradeResult(symbol, False, error=validation_msg)
            
            print(f"   Direction: {order_type}, Entry: {entry_price}, SL: {stop_loss}, TP1: {take_profit_1}")
            print(f"💹 EXECUTING: {symbol} {order_type}")
            
            execution_result = execute_trade(
                symbol=mt5_symbol,
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
                enable_trailing_stop=False,
            )
            
            success = execution_result.get("success", False)
            ticket = execution_result.get("ticket")
            price = execution_result.get("price")
            
            trade_result = TradeResult(
                symbol=symbol,
                success=success,
                ticket=ticket,
                entry_price=price,
                stop_loss=execution_result.get("stop_loss"),
                take_profit=execution_result.get("take_profit"),
                take_profit_2=execution_result.get("take_profit_2"),
                take_profit_3=execution_result.get("take_profit_3"),
                volume=execution_result.get("volume"),
                actual_margin=execution_result.get("actual_margin"),
                actual_risk_usd=execution_result.get("actual_risk_usd"),
                risk_percent_used=execution_result.get("risk_percent_used"),
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
            
            self._log_executed_trade(trade_result)
            
            if success and ticket:
                with self._state_lock:
                    self.open_positions[symbol] = ticket
                    # ✅ FIXED: Store ALL position data in cache for fallback
                    self._position_data_cache[ticket] = {
                        "symbol": symbol,
                        "price_open": price,
                        "volume": execution_result.get("volume", 0),
                        "sl": stop_loss,
                        "tp": take_profit_1,
                        "tp2": execution_result.get("take_profit_2"),
                        "tp3": execution_result.get("take_profit_3"),
                        "order_type": order_type,
                        "magic": self.STRATEGY_MAGIC,
                        "entry_time": time.time(),
                        "risk_usd": execution_result.get("actual_risk_usd", 0)
                    }
                    self.stats["trades_executed"] += 1
                    if symbol in self.symbol_status_map:
                        self.symbol_status_map[symbol].in_position = True
                        self.symbol_status_map[symbol].ticket = ticket
                        self.symbol_status_map[symbol].entry_price = price
                self._update_positions_log()
                print(f"💰 {symbol} opened at {price} (Cache stored for fallback)")
                self._save_trade_open_to_firebase(trade_result, analysis_result)
            else:
                error_msg = execution_result.get("error", "Unknown error")
                print(f"❌ Trade failed for {symbol}: {error_msg}")
                # ✅ If error is "Trading not allowed", add to permanent exclusion
                if "Trading not allowed" in error_msg or "trading not allowed" in error_msg.lower():
                    with self._state_lock:
                        self.permanently_excluded.add(symbol)
                        if symbol in self.filtered_symbols:
                            self.filtered_symbols.discard(symbol)
                        if symbol in self.top_symbols:
                            self.top_symbols = [s for s in self.top_symbols if s.symbol != symbol]
                        if symbol in self.symbol_status_map:
                            del self.symbol_status_map[symbol]
                    print(f"🚫 {symbol} permanently excluded due to trading restriction")
            
            return trade_result
            
        except Exception as e:
            print(f"❌ Execution error for {symbol}: {e}")
            print(traceback.format_exc())
            return TradeResult(symbol, False, error=str(e))
    
    # ============================================================
    # ✅ FIXED: POSITION MONITOR - DETECTS SL/TP HITS WITH CORRECT PROFIT
    # ============================================================
    
    def _position_monitor_loop(self):
        """Monitor open positions and detect when they close (SL/TP hits)."""
        last_cleanup = time.time()
        checked_tickets = set()
        
        while not self.stop_event.is_set():
            try:
                current_time = time.time()
                
                # Cleanup every 60 seconds
                if current_time - last_cleanup >= 60:
                    with self._executed_lock:
                        self._executed_recently.clear()
                        self._executing_symbols.clear()
                    last_cleanup = current_time
                
                # ✅ FIXED: this iterated `self.open_positions`, a dict keyed
                # by SYMBOL holding ONE ticket. With MAX_TRADES_PER_SYMBOL > 1
                # a second position on the same symbol OVERWRITES the first
                # there (see _sync_open_positions and the post-execution
                # registration), so every earlier position on that symbol
                # became invisible to this loop: no price_evolution, no close
                # detection, no analysis_at_close. The trade simply vanished
                # from the record while still being live at the broker.
                #
                # Driven from TICKET-keyed state now -- the broker's own open
                # positions unioned with _position_data_cache (which is keyed
                # by ticket and carries the symbol). A ticket present in the
                # cache but absent from MT5 is exactly the "it closed" signal
                # this loop is looking for, so that case still works.
                pairs = {}
                try:
                    for pos in (get_open_positions() or []):
                        tk, sym = pos.get("ticket"), pos.get("symbol")
                        if tk and sym:
                            pairs[tk] = sym
                except Exception as exc:
                    print(f"⚠️ Could not enumerate MT5 positions: {exc}")

                with self._state_lock:
                    for tk, data in self._position_data_cache.items():
                        sym = (data or {}).get("symbol")
                        if tk and sym:
                            pairs.setdefault(tk, sym)
                    # Legacy symbol-keyed state, so nothing registered only
                    # there is dropped during the transition.
                    for sym, tk in self.open_positions.items():
                        if tk and sym:
                            pairs.setdefault(tk, sym)

                for ticket, symbol in list(pairs.items()):
                    try:
                        if not ticket:
                            continue
                        
                        # Skip if already processed
                        if ticket in checked_tickets:
                            continue
                        
                        # Check if webhook already closed this
                        with self._state_lock:
                            if ticket in self._webhook_closed_tickets:
                                print(f"✅ {symbol} (ticket: {ticket}) already closed via webhook")
                                self._cleanup_closed_position(symbol, ticket)
                                checked_tickets.add(ticket)
                                continue
                        
                        # Check position in MT5
                        position = get_position_details(ticket)
                        
                        if not position:
                            # ✅ POSITION CLOSED IN MT5 (SL/TP HIT)
                            print(f"📉 {symbol} closed (ticket: {ticket}) - SL/TP HIT detected")
                            
                            # Check if already closed in Firebase (prevent duplicate saves)
                            already_closed = False
                            if self.firebase:
                                try:
                                    existing_trade = self.firebase.get_trade(str(ticket))
                                    if existing_trade:
                                        existing_close = existing_trade.get("close_data", {})
                                        existing_close_price = existing_close.get("close_price", 0)
                                        if existing_close_price != 0:
                                            print(f"   ✅ Trade {ticket} already closed in Firebase (price: {existing_close_price})")
                                            already_closed = True
                                except Exception as e:
                                    print(f"⚠️ Could not check Firebase: {e}")
                            
                            if not already_closed:
                                # Get cached data
                                cached = self._position_data_cache.get(ticket, {})
                                
                                # Get profit from MT5 trade history (MOST ACCURATE)
                                profit = 0.0
                                price_open = cached.get("price_open", 0)
                                price_close = 0.0
                                volume = cached.get("volume", 0)
                                sl = cached.get("sl", 0)
                                tp = cached.get("tp", 0)
                                order_type = cached.get("order_type", "BUY")
                                
                                # Try to get from trade history (most accurate)
                                try:
                                    history = get_trade_history(last_n_days=1)
                                    if history.get("success", False):
                                        for trade in history.get("trades", []):
                                            if trade.get("entry_ticket") == ticket:
                                                profit = trade.get("net_profit", 0)
                                                if not price_open:
                                                    price_open = trade.get("entry_price", 0)
                                                price_close = trade.get("exit_price", 0)
                                                if not volume:
                                                    volume = trade.get("volume", 0)
                                                if not sl:
                                                    sl = trade.get("entry_sl", 0)
                                                if not tp:
                                                    tp = trade.get("entry_tp", 0)
                                                print(f"   📊 Trade history: profit=${profit:.2f}, close={price_close}")
                                                break
                                except Exception as e:
                                    print(f"⚠️ Could not get trade history: {e}")
                                
                                # Ask the broker how it actually closed.
                                #
                                # This replaced an estimate that used the STOP
                                # LOSS as the exit whenever the history lookup
                                # missed, and then multiplied the move by a
                                # hardcoded 100000 -- the FX contract size --
                                # for every symbol. On UKOIL that recorded a
                                # "profit" of $8,500.00 for a fraction of a lot.
                                if price_close == 0 or profit == 0:
                                    deal = closing_deal(ticket)
                                    if deal:
                                        price_close = deal["price_close"]
                                        profit = deal["profit"]
                                        if not volume:
                                            volume = deal["volume"]
                                        print(f"   📒 Broker deal: close={price_close}, "
                                              f"profit=${profit:.2f}")

                                # Last resort, and only with the REAL contract
                                # size. If it is unknown, leave the profit alone
                                # rather than scale the move by a guess.
                                if profit == 0 and price_open > 0 and price_close > 0 and volume > 0:
                                    mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
                                    size = contract_size(mt5_symbol)
                                    if size:
                                        move = (price_close - price_open) if order_type == "BUY" \
                                            else (price_open - price_close)
                                        profit = move * volume * size
                                        print(f"   💰 Calculated profit: ${profit:.2f} "
                                              f"(contract size {size})")
                                    else:
                                        print(f"   ⚠️ No contract size for {mt5_symbol} - "
                                              f"leaving profit unset rather than guessing")
                                
                                # If we have valid close data, save it
                                if price_open != 0 and price_close != 0 and volume != 0:
                                    print(f"   💾 Saving SL/TP close for {symbol} - Profit: ${profit:.2f}")
                                    self._save_trade_close_to_firebase(
                                        symbol=symbol,
                                        ticket=ticket,
                                        # ✅ FIXED: was the literal "SL_TP_HIT"
                                        # on every close, which merged "hit
                                        # target" and "hit stop" into one
                                        # label and made close_reason useless
                                        # for learning. Resolved from the
                                        # server's DEAL_REASON instead.
                                        close_reason=resolve_close_reason(ticket),
                                        profit=profit,
                                        price_open=price_open,
                                        price_close=price_close,
                                        volume=volume,
                                        sl=sl,
                                        tp=tp,
                                        is_webhook=False
                                    )
                                else:
                                    print(f"   ⚠️ Incomplete close data for {symbol}")
                            
                            # Clean up cache
                            if ticket in self._position_data_cache:
                                del self._position_data_cache[ticket]
                            
                            # Clean up local state
                            self._cleanup_closed_position(symbol, ticket)
                            checked_tickets.add(ticket)
                            
                        else:
                            # Position still open - update price evolution
                            self._update_trade_price_in_firebase(ticket, position)
                            
                    except Exception as e:
                        print(f"⚠️ Position monitor error for {symbol} (ticket: {ticket}): {e}")
                        pass
                        
                # Remove old tickets from checked set (keep last 1000)
                if len(checked_tickets) > 1000:
                    checked_tickets = set(list(checked_tickets)[-500:])
                    
                time.sleep(2)
                
            except Exception as e:
                print(f"⚠️ Position monitor loop error: {e}")
                time.sleep(5)
    
    def _cleanup_closed_position(self, symbol: str, ticket: int):
        """✅ Helper: Clean up a closed position from local state."""
        with self._state_lock:
            if symbol in self.open_positions:
                del self.open_positions[symbol]
                self.stats["trades_closed"] = self.stats.get("trades_closed", 0) + 1
            if symbol in self.symbol_status_map:
                self.symbol_status_map[symbol].in_position = False
                self.symbol_status_map[symbol].ticket = None
                self.symbol_status_map[symbol].entry_price = None
        
        self._update_positions_log()
        
        with self._fast_entry_lock:
            self._fast_entry_symbols.discard(symbol)
        
        print(f"✅ Cleaned up closed position: {symbol} (ticket: {ticket})")
    
    # ============================================================
    # HEALTH MONITOR
    # ============================================================
    
    def _health_monitor_loop(self):
        last_report = 0
        while not self.stop_event.is_set():
            try:
                current_time = time.time()
                if current_time - last_report >= 60:
                    self._print_health_report()
                    last_report = time.time()
                time.sleep(10)
            except Exception:
                time.sleep(10)
    
    def _print_health_report(self):
        with self._state_lock:
            trades = len(self.open_positions)
            filtered = len(self.filtered_symbols)
            top = len(self.top_symbols)
            executed = self.stats["trades_executed"]
            firebase_saves = self.stats.get("firebase_saves", 0)
            reanalysis = self.stats.get("reanalysis_count", 0)
            webhook_closes = self.stats.get("webhook_closes", 0)
            fast_checks = self.stats.get("fast_entry_checks", 0)
            price_updates = self.stats.get("price_updates", 0)
            
            with self._fast_entry_lock:
                fast_symbols = list(self._fast_entry_symbols)
        
        print(f"{'='*80}")
        print(f"🏥 HEALTH UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        print(f"📊 Status Summary:")
        print(f"   🟢 Running: {self.running}")
        print(f"   📈 Open Trades: {trades}/{self.MAX_SIMULTANEOUS_TRADES}")
        print(f"   🔍 Filtered Symbols: {filtered}")
        print(f"   ⭐ Top Symbols: {top}/{self.TOP_SYMBOLS_COUNT}")
        print(f"   ✅ Total Executed: {executed}")
        print(f"   🔥 Firebase Saves: {firebase_saves}")
        print(f"   🔄 Reanalysis Cycles: {reanalysis}")
        print(f"   📨 Webhook Closes: {webhook_closes}")
        print(f"   ⚡ Fast Entry Checks: {fast_checks}")
        print(f"   📈 Price Updates (1min): {price_updates}")
        print(f"   🚀 Fast Entry Symbols: {len(fast_symbols)}")
        if fast_symbols:
            print(f"      {', '.join(fast_symbols)}")
        
        print(f"{'-'*80}")
        print(f"📊 TOP SYMBOLS (Overall | Entry):")
        for status in self.top_symbols[:5]:
            print(f"   {status.symbol}: {status.reason}")
        
        # ✅ Show permanently excluded symbols
        with self._state_lock:
            if self.permanently_excluded:
                print(f"{'-'*80}")
                print(f"🚫 PERMANENTLY EXCLUDED SYMBOLS:")
                print(f"   {', '.join(sorted(self.permanently_excluded))}")
        
        # ✅ Show position cache status
        with self._state_lock:
            cache_size = len(self._position_data_cache)
            print(f"{'-'*80}")
            print(f"📦 Position Cache:")
            print(f"   Size: {cache_size}")
            if cache_size > 0:
                print(f"   Tickets: {list(self._position_data_cache.keys())[:5]}")
        
        print(f"{'='*80}")
    
    # ============================================================
    # MAIN LOOP
    # ============================================================
    
    def _main_loop(self):
        print("🚀 Monitor started")
        try:
            filter_success = self._run_filter_step()
            if filter_success:
                self._refresh_top_symbols()
            else:
                print("⚠️ Not enough symbols passed initial filter")
        except Exception as e:
            print(f"❌ Initial filter/refresh error: {e}")
            print(traceback.format_exc())
        self._last_filter_time = time.time()
        self._last_reanalysis_time = time.time()
        
        while not self.stop_event.is_set():
            try:
                current_time = time.time()
                
                if current_time - self._last_filter_time >= self.FILTER_INTERVAL:
                    filter_success = self._run_filter_step()
                    if filter_success:
                        self._refresh_top_symbols()
                    self._last_filter_time = current_time
                
                if current_time - self._last_reanalysis_time >= self.SYMBOL_REANALYSIS_INTERVAL:
                    self._run_symbol_reanalysis()
                    self._last_reanalysis_time = current_time
                
                self._run_monitor_step()
                
                with self._state_lock:
                    self.stats["total_scans"] += 1
            except Exception as e:
                # ✅ FIXED: previously nothing here caught exceptions from a
                # scan cycle, so a single bad call (e.g. a TimeoutError
                # bubbling out of a thread-pool step) would silently kill
                # this entire thread forever — health/position-monitor
                # threads would keep reporting "healthy" while no
                # scanning/trading happened again until an external
                # restart. Now we log it, count it, and keep going.
                print(f"❌ Main loop cycle error (continuing): {e}")
                print(traceback.format_exc())
                with self._state_lock:
                    self.stats["monitor_errors"] = self.stats.get("monitor_errors", 0) + 1
            
            time.sleep(self.SCAN_INTERVAL)
        
        print("Monitor stopped")
    
    # ============================================================
    # ✅ NEW: SELF-RESTART SYSTEM (Option B — full process re-exec)
    # ============================================================
    #
    # Why a full process re-exec instead of an in-process "soft reset":
    #   - Open trades are NOT this bot's state to lose. get_open_positions()
    #     queries MT5/the broker directly, and _sync_open_positions() rebuilds
    #     self.open_positions from that live query on every __init__ and on
    #     every position-monitor tick. So a full restart is safe for open
    #     trades by construction — nothing needs to be saved/restored.
    #   - os.execv() replaces the ENTIRE process image (heap, threads, GC
    #     state, native library handles) with a brand new interpreter, same
    #     PID. There is nothing left over to leak, by definition — including
    #     things an in-process reset CAN'T reach: native/C-level memory (MT5's
    #     own buffers, numpy/pandas buffers from analysis calls) and plain
    #     allocator fragmentation, which gc.collect() never touches. An
    #     in-process reset is also only as safe as its thread.join(timeout=X)
    #     calls — if a worker is genuinely hung, the join just times out and
    #     the reset proceeds anyway, leaving that old thread running forever
    #     in the background while a new one starts on top of it. os.execv has
    #     no equivalent failure mode: it doesn't matter whether anything is
    #     hung, because the whole process is replaced regardless.
    
    def restart_now(self, reason: str = "manual", delay: float = 0.0) -> bool:
        """
        Gracefully stop the monitor and re-execute the current process from
        scratch (same PID, brand new interpreter + memory). Safe for open
        MT5 positions — they live at the broker and are re-synced
        automatically the moment the new process starts back up.
        
        Args:
            reason: short label, only used for logging/stats.
            delay: seconds to wait before restarting. Pass a small delay
                   (e.g. 1.0) when triggering this from an HTTP handler so
                   the response can be sent back to the caller first.
        
        Returns:
            True if a restart was scheduled, False if one was already in
            progress (duplicate trigger).
        """
        with self._restart_lock:
            if self._restarting:
                print(f"⚠️ Restart already in progress, ignoring duplicate trigger ({reason})")
                return False
            self._restarting = True
        
        def _do_restart():
            try:
                if delay > 0:
                    time.sleep(delay)
                
                print(f"{'='*60}")
                print(f"♻️  SELF-RESTART TRIGGERED — reason: {reason}")
                print(f"{'='*60}")
                
                self._restart_count += 1
                self._last_restart_time = time.time()
                
                # 1. Graceful stop: joins all threads, does one last
                #    position sync from MT5, writes the positions log.
                self.stop()
                
                # 2. Release the MT5 terminal connection cleanly so the
                #    fresh process can reconnect without contention.
                try:
                    shutdown_mt5()
                    print("✅ MT5 connection closed")
                except Exception as e:
                    print(f"⚠️ MT5 shutdown error (continuing anyway): {e}")
                
                # 3. Replace this process image with a fresh interpreter,
                #    running the exact same command line. __main__ reruns
                #    top to bottom: reconnects MT5, rebuilds the monitor
                #    (fresh memory, fresh threads, fresh pools), and — in
                #    hybrid_monitor.py — restarts the Flask app too.
                print("🚀 Re-executing process now...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            
            except Exception as e:
                print(f"❌ Self-restart failed: {e}")
                print(traceback.format_exc())
                with self._restart_lock:
                    self._restarting = False
        
        threading.Thread(target=_do_restart, name="SelfRestart", daemon=True).start()
        return True
    
    def enable_auto_restart(self, interval_seconds: int = 3600):
        """Turn on the scheduled self-restart watchdog (default: every hour)."""
        with self._restart_lock:
            self._auto_restart_enabled = True
            self._auto_restart_interval = max(60, int(interval_seconds))
            self._last_restart_time = time.time()
        print(f"✅ Auto-restart enabled — every {self._auto_restart_interval}s")
    
    def disable_auto_restart(self):
        """Turn off the scheduled self-restart watchdog. Does not cancel a restart already in flight."""
        with self._restart_lock:
            self._auto_restart_enabled = False
        print("🛑 Auto-restart disabled")
    
    def get_restart_status(self) -> Dict[str, Any]:
        with self._restart_lock:
            enabled = self._auto_restart_enabled
            interval = self._auto_restart_interval
            last = self._last_restart_time
            count = self._restart_count
            restarting = self._restarting
        now = time.time()
        return {
            "auto_restart_enabled": enabled,
            "interval_seconds": interval,
            "seconds_since_last_restart": round(now - last, 1),
            "seconds_until_next_restart": round(max(0, interval - (now - last)), 1) if enabled else None,
            "restart_count": count,
            "restart_in_progress": restarting,
        }
    
    def _restart_watchdog_loop(self):
        """Background loop: fires restart_now() once the auto-restart interval elapses."""
        while not self.stop_event.is_set():
            try:
                with self._restart_lock:
                    enabled = self._auto_restart_enabled
                    interval = self._auto_restart_interval
                    elapsed = time.time() - self._last_restart_time
                    restarting = self._restarting
                if enabled and not restarting and elapsed >= interval:
                    self.restart_now(reason=f"scheduled ({interval}s interval)")
                    return  # process is about to be replaced; nothing left to watch
                time.sleep(5)
            except Exception as e:
                print(f"⚠️ Restart watchdog error: {e}")
                time.sleep(5)
    
    # ============================================================
    # PUBLIC METHODS
    # ============================================================
    
    def start_non_blocking(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        with self._state_lock:
            self.stats["start_time"] = datetime.now().isoformat()
        
        self._fast_entry_thread = threading.Thread(
            target=self._fast_entry_check_loop,
            name="FastEntryCheck",
            daemon=True
        )
        self._fast_entry_thread.start()
        
        self.position_monitor_thread = threading.Thread(
            target=self._position_monitor_loop,
            name="PositionMonitor",
            daemon=True
        )
        self.position_monitor_thread.start()
        
        self.health_thread = threading.Thread(
            target=self._health_monitor_loop,
            name="HealthMonitor",
            daemon=True
        )
        self.health_thread.start()
        
        self.main_thread = threading.Thread(
            target=self._main_loop,
            name="MainController",
            daemon=True
        )
        self.main_thread.start()
        
        self._restart_thread = threading.Thread(
            target=self._restart_watchdog_loop,
            name="RestartWatchdog",
            daemon=True
        )
        self._restart_thread.start()
        
        print("✅ Monitor running with Fast Entry Check & Webhook support")
        if self.price_encoder:
            print("✅ Price evolution ENCODER: 18KB → 400B per point (97.8% reduction)")
        print("✅ Trading not allowed symbols are permanently excluded")
        print("✅ Displaying Overall + Entry confidence")
        print("✅ analysis_at_close: Captured and saved to Firebase")
        print("✅ Firebase doc_id format: trade_{ticket}")
        print("✅ Position cache: Enabled for SL/TP fallback detection")
        if self._auto_restart_enabled:
            print(f"✅ Auto-restart: every {self._auto_restart_interval//60} minutes (open trades preserved)")
        else:
            print("ℹ️ Auto-restart: disabled (call enable_auto_restart() or POST /monitor/restart/auto to turn on)")
        print("✅ GNN: REMOVED - Running in ai_controller.py on port 5002")
    
    def stop(self):
        if not self.running:
            return
        print("Stopping monitor...")
        self.stop_event.set()
        self.running = False        
        for thread in [self.position_monitor_thread, self.health_thread, self.main_thread,
                       self._fast_entry_thread, self._restart_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)
        # ✅ NEW: shut down the persistent thread pools too. wait=False so a
        # stuck worker (e.g. a hung MT5/network call) can never block stop()
        # itself from returning — any in-flight task is just abandoned.
        for pool in (self._filter_pool, self._monitor_pool):
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # cancel_futures was added in Python 3.9
                pool.shutdown(wait=False)
        self._sync_open_positions()
        self._update_positions_log()
        print("✅ Monitor stopped")
    
    def force_refresh(self):
        print("🔄 Manual refresh triggered")
        self._run_filter_step()
        self._refresh_top_symbols()
    
    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            status = {
                "running": self.running,
                "filtered_count": len(self.filtered_symbols),
                "top_count": len(self.top_symbols),
                "open_positions": self.open_positions,
                "stats": self.stats,
                "fast_entry_symbols": list(self._fast_entry_symbols) if hasattr(self, '_fast_entry_symbols') else [],
                "webhook_closed_tickets": len(self._webhook_closed_tickets) if hasattr(self, '_webhook_closed_tickets') else 0,
                "price_update_interval": self.PRICE_UPDATE_INTERVAL,
                "permanently_excluded": list(self.permanently_excluded) if hasattr(self, 'permanently_excluded') else [],
                "position_cache_size": len(self._position_data_cache),
                "price_encoder": self.price_encoder is not None,
                "gnn": "REMOVED - Running on port 5002",
                "restart": self.get_restart_status(),
            }
            return status