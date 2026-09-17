# core/mt5_connector.py
import MetaTrader5 as mt5
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# =====================================================
# MT5 CONNECTION
# =====================================================

def connect_mt5(
    login: Optional[int] = None,
    password: Optional[str] = None,
    server: Optional[str] = None,
    path: Optional[str] = None
) -> bool:
    """
    Initialize and optionally login to MetaTrader 5
    
    Args:
        login: Account login number (optional)
        password: Account password (optional)
        server: Server name (optional)
        path: Path to MT5 terminal.exe (auto-detects if not provided)
    
    Returns:
        bool: True if connection successful
    """
    try:
        # Initialize MT5
        if path:
            initialized = mt5.initialize(path=path)
        else:
            initialized = mt5.initialize()
        
        if not initialized:
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False
        
        logger.info("MT5 initialized successfully")
        
        # Login if credentials provided
        if login and password and server:
            if mt5.login(login, password=password, server=server):
                account = mt5.account_info()
                logger.info(f"✅ Logged in to account: {account.login}")
                logger.info(f"   Balance: {account.balance} {account.currency}")
                return True
            else:
                logger.error(f"Login failed: {mt5.last_error()}")
                return False
        
        # Check if already logged in
        account = mt5.account_info()
        if account:
            logger.info(f"✅ Already logged in to account: {account.login}")
            logger.info(f"   Balance: {account.balance} {account.currency}")
        else:
            logger.warning("MT5 initialized but not logged in")
        
        return True
        
    except Exception as e:
        logger.error(f"MT5 connection error: {e}")
        return False

def shutdown_mt5() -> None:
    """Shutdown MetaTrader 5 connection"""
    try:
        mt5.shutdown()
        logger.info("MT5 connection shutdown")
    except Exception as e:
        logger.error(f"Error shutting down MT5: {e}")

def is_mt5_connected() -> bool:
    """Check if MT5 is connected and logged in"""
    try:
        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()
        return terminal_info is not None and account_info is not None
    except:
        return False

def get_account_summary() -> Optional[Dict[str, Any]]:
    """Get account summary"""
    if not is_mt5_connected():
        return None
    
    account = mt5.account_info()
    if account:
        return {
            'login': account.login,
            'balance': account.balance,
            'equity': account.equity,
            'margin': account.margin,
            'free_margin': account.margin_free,
            'margin_level': account.margin_level,
            'currency': account.currency,
            'profit': account.profit,
            'leverage': account.leverage
        }
    return None