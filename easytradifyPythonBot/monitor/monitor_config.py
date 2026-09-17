# api/monitor_config.py
# ============================================================
# ALL CONFIGURATION - ONE PLACE
# ============================================================

class Config:
    # Trading
    # DATA-COLLECTION MODE: effectively unlimited concurrency.
    # A finite sentinel rather than 0/-1 because every enforcement site is a
    # `>=` comparison and core/portfolio_risk_service.py rejects <= 0.
    MAX_SIMULTANEOUS_TRADES = 100000
    # ✅ TRIPLED (was 5). Kept in step with MultiSymbolMonitor's own
    # TOP_SYMBOLS_COUNT, which is the value actually used at runtime.
    #
    # This is a CAP -- "watch at most this many" -- applied as a
    # valid_symbols[:TOP_SYMBOLS_COUNT] slice. It is deliberately larger than
    # the whole symbol universe so the slice stops limiting anything. Do NOT
    # also use it as a minimum: see MIN_SYMBOLS_TO_TRADE below.
    TOP_SYMBOLS_COUNT = 100
    # The FLOOR: how many symbols must clear the market-conditions filter
    # before the monitor is willing to run at all. Separate from
    # TOP_SYMBOLS_COUNT because the two are opposite quantities, and
    # conflating them deadlocked the monitor: the filter gate compared a
    # pass-count against the cap, so with a 64-symbol universe it demanded
    # 100 passes, returned False forever, and _refresh_top_symbols() was
    # never called -- zero symbols watched, zero trades, indefinitely.
    MIN_SYMBOLS_TO_TRADE = 10
    MIN_CONFIDENCE_THRESHOLD = 65
    FIXED_TRADE_SIZE_USD = 200
    # NOT a percentage of the account. core/calculations.py computes
    #     target_risk = fixed_trade_size_usd * RISK_PER_TRADE
    # so this is a fraction of the $200 trade-size budget: 0.05 -> $10 of
    # risk, which on a $22k account is ~0.045% of equity, not 5%.
    # 0.02 -> $4 of risk. NOTE this is NOT the 1-2% of account you may mean:
    # 2% of a $22k account is ~$447. Account-percentage risk requires sizing
    # off equity, which this parameter cannot express.
    RISK_PER_TRADE = 0.02
    MAX_SPREAD = 30
    STRATEGY_MAGIC = 1001
    TRADE_DEVIATION = 20
    # DATA-COLLECTION MODE: repeated entries on the same symbol allowed.
    MAX_TRADES_PER_SYMBOL = 100000
    
    # Timing
    SCAN_INTERVAL = 5
    FILTER_INTERVAL = 7200
    FILTER_RETRY_INTERVAL = 60
    REPLACEMENT_CHECK_INTERVAL = 120
    TREND_RECHECK_INTERVAL = 120
    
    # ✅ OPTION 3: Increased cooldown to prevent replacement during stability
    REPLACEMENT_COOLDOWN = 180  # Changed from 60 to 180 seconds (3 minutes)
    
    SYMBOL_COOLDOWN = 5
    
    # Threads
    FILTER_THREADS = 4
    MONITOR_THREADS = 3
    FILTER_TIMEOUT = 5
    MONITOR_TIMEOUT = 10
    
    # Stability - 3 checks, direction must match, 65% stable, 75% execute
    STABILITY_REQUIRED_CHECKS = 3
    STABILITY_CHECK_INTERVAL = 30
    STABILITY_MINIMUM_THRESHOLD = 65
    STABILITY_CONFIDENCE_THRESHOLD = 75
    STABILITY_MAX_DEVIATION = 15
    STABILITY_DIRECTION_MUST_MATCH = True
    STABILITY_MAX_AGE_SECONDS = 120
    
    # Reanalysis - every 5 minutes
    SYMBOL_REANALYSIS_INTERVAL = 300
    SYMBOL_REANALYSIS_BATCH_SIZE = 5
    STALE_SYMBOL_THRESHOLD = 600
    
    # Symbols
    # Kept in step with MultiSymbolMonitor.DISPLAY_SYMBOLS -- see the note
    # there for why 21 symbols were removed on 2026-09-10.
    SYMBOL_EXCHANGE_MAP = {
        "XAUUSD": "FX", "XAUEUR": "FX", "EURUSD": "FX", "GBPUSD": "FX",
        "USDCAD": "FX", "AUDUSD": "FX", "NZDUSD": "FX", "USDCHF": "FX",
        "EURGBP": "FX", "EURCAD": "FX", "GBPAUD": "FX", "SPX500": "NYSE",
        "AAPL": "NASDAQ", "MSFT": "NASDAQ", "GOOGL": "NASDAQ", "AMZN": "NASDAQ",
        "NVDA": "NASDAQ", "META": "NASDAQ", "TSLA": "NASDAQ", "AMD": "NASDAQ",
        "INTC": "NASDAQ", "CSCO": "NASDAQ", "ORCL": "NYSE", "TXN": "NASDAQ",
        "QCOM": "NASDAQ", "AMAT": "NASDAQ", "MU": "NASDAQ", "PLTR": "NYSE",
        "UBER": "NYSE", "PYPL": "NASDAQ", "JNJ": "NYSE", "PFE": "NYSE",
        "WMT": "NYSE", "COST": "NASDAQ", "MCD": "NYSE", "SBUX": "NASDAQ",
        "DIS": "NYSE", "KO": "NYSE", "XOM": "NYSE", "CVX": "NYSE",
        "BA": "NYSE", "CAT": "NYSE", "LMT": "NYSE", "JPM": "NYSE",
        "BAC": "NYSE", "WFC": "NYSE", "V": "NYSE", "MA": "NYSE",
        "SPY": "NYSE", "QQQ": "NASDAQ", "VTI": "NYSE", "XLK": "NYSE",
        "XLF": "NYSE", "XLE": "NYSE", "XLV": "NYSE", "SMH": "NASDAQ"
    }

config = Config()