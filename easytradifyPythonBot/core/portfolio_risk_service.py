# ============================================================
# PORTFOLIO RISK MANAGEMENT SERVICE
# ============================================================
# FILE: core/portfolio_risk_service.py
# 
# ✅ Uses existing trades collection for profit calculation
# ✅ Complete portfolio risk management with:
#   - Daily/Monthly/YTD loss limits (ONLY %)
#   - Daily/Monthly/YTD profit tracking from actual trades
#   - Win rate tracking from closed trades
#   - Maximum drawdown monitoring (ONLY %)
#   - Per-order risk (default 5.0%)
#   - Account balance and leverage from MT5 (read-only)
#   - Firebase integration for persistence
#   - Funded account compliance (FTMO, etc.)
#   - Trade size in USD (editable)
# ============================================================

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import traceback

from core.mongo import get_portfolio_service
from core.mongo.trades_service import get_trades_service


try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk level categories."""
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    MAX_EXCEEDED = "MAX_EXCEEDED"


@dataclass
class PortfolioRiskConfig:
    """Portfolio risk configuration (user editable fields only)."""
    
    # Trade size (editable)
    trade_size_in_usd: float = 200.0

    # ============================================================
    # EXECUTION AUTOMATION SETTINGS (USER EDITABLE)
    # ============================================================
    # Break-even: enabled independently from trailing stop.
    enable_breakeven: bool = True
    auto_breakeven_usd: float = 5.0

    # Automatic trailing stop. USD distance is symbol-independent;
    # execution.py performs the symbol/volume-specific conversion.
    enable_auto_trailing_stop: bool = True
    auto_trailing_stop_usd: float = 5.0

    # Spread protection.
    auto_max_spread: bool = True
    max_spread: float = 30.0

    # Order execution deviation.
    auto_trade_deviation: bool = True
    trade_deviation: int = 20

    # Per-symbol trade limit.
    auto_max_trades_per_symbol: bool = True
    max_trades_per_symbol: int = 100000  # data-collection mode

    # Global simultaneous-trade limit.
    auto_max_simultaneous_trades: bool = True
    max_simultaneous_trades: int = 100000  # data-collection mode
    
    # Daily limits (ONLY PERCENTAGE)
    max_daily_loss_percent: float = 5.0
    max_daily_trades: int = 100000  # data-collection mode
    max_daily_win_target_percent: float = 10.0
    
    # Monthly limits (ONLY PERCENTAGE)
    max_monthly_loss_percent: float = 10.0
    max_monthly_trades: int = 100000  # data-collection mode
    max_monthly_win_target_percent: float = 25.0
    
    # YTD limits (ONLY PERCENTAGE)
    max_ytd_loss_percent: float = 15.0
    
    # Per-trade limits (ONLY PERCENTAGE)
    max_risk_per_trade_percent: float = 5.0
    
    # Drawdown limits (ONLY PERCENTAGE)
    max_drawdown_percent: float = 10.0
    
    # Consecutive loss limits
    max_consecutive_losses: int = 5
    max_daily_consecutive_losses: int = 3
    
    # Funded account compliance
    funded_account_type: str = "STANDARD"
    funded_account_rules: Dict[str, Any] = field(default_factory=dict)
    
    # Trading hours
    trading_start_hour: int = 0
    trading_end_hour: int = 23
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_size_in_usd": round(self.trade_size_in_usd, 2),
            "enable_breakeven": self.enable_breakeven,
            "auto_breakeven_usd": round(self.auto_breakeven_usd, 2),
            "enable_auto_trailing_stop": self.enable_auto_trailing_stop,
            "auto_trailing_stop_usd": round(self.auto_trailing_stop_usd, 2),
            "auto_max_spread": self.auto_max_spread,
            "max_spread": round(self.max_spread, 2),
            "auto_trade_deviation": self.auto_trade_deviation,
            "trade_deviation": self.trade_deviation,
            "auto_max_trades_per_symbol": self.auto_max_trades_per_symbol,
            "max_trades_per_symbol": self.max_trades_per_symbol,
            "auto_max_simultaneous_trades": self.auto_max_simultaneous_trades,
            "max_simultaneous_trades": self.max_simultaneous_trades,
            "max_daily_loss_percent": round(self.max_daily_loss_percent, 2),
            "max_daily_trades": self.max_daily_trades,
            "max_daily_win_target_percent": round(self.max_daily_win_target_percent, 2),
            "max_monthly_loss_percent": round(self.max_monthly_loss_percent, 2),
            "max_monthly_trades": self.max_monthly_trades,
            "max_monthly_win_target_percent": round(self.max_monthly_win_target_percent, 2),
            "max_ytd_loss_percent": round(self.max_ytd_loss_percent, 2),
            "max_risk_per_trade_percent": round(self.max_risk_per_trade_percent, 2),
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_daily_consecutive_losses": self.max_daily_consecutive_losses,
            "funded_account_type": self.funded_account_type,
            "funded_account_rules": self.funded_account_rules,
            "trading_start_hour": self.trading_start_hour,
            "trading_end_hour": self.trading_end_hour
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PortfolioRiskConfig':
        return cls(
            trade_size_in_usd=data.get("trade_size_in_usd", 200.0),
            enable_breakeven=bool(data.get("enable_breakeven", True)),
            auto_breakeven_usd=float(data.get("auto_breakeven_usd", 5.0)),
            enable_auto_trailing_stop=bool(data.get("enable_auto_trailing_stop", True)),
            auto_trailing_stop_usd=float(data.get("auto_trailing_stop_usd", 5.0)),
            auto_max_spread=bool(data.get("auto_max_spread", True)),
            max_spread=float(data.get("max_spread", 30.0)),
            auto_trade_deviation=bool(data.get("auto_trade_deviation", True)),
            trade_deviation=int(data.get("trade_deviation", 20)),
            auto_max_trades_per_symbol=bool(data.get("auto_max_trades_per_symbol", True)),
            max_trades_per_symbol=int(data.get("max_trades_per_symbol", 100000)),
            auto_max_simultaneous_trades=bool(data.get("auto_max_simultaneous_trades", True)),
            max_simultaneous_trades=int(data.get("max_simultaneous_trades", 100000)),
            max_daily_loss_percent=data.get("max_daily_loss_percent", 5.0),
            max_daily_trades=data.get("max_daily_trades", 100000),
            max_daily_win_target_percent=data.get("max_daily_win_target_percent", 10.0),
            max_monthly_loss_percent=data.get("max_monthly_loss_percent", 10.0),
            max_monthly_trades=data.get("max_monthly_trades", 100000),
            max_monthly_win_target_percent=data.get("max_monthly_win_target_percent", 25.0),
            max_ytd_loss_percent=data.get("max_ytd_loss_percent", 15.0),
            max_risk_per_trade_percent=data.get("max_risk_per_trade_percent", 5.0),
            max_drawdown_percent=data.get("max_drawdown_percent", 10.0),
            max_consecutive_losses=data.get("max_consecutive_losses", 5),
            max_daily_consecutive_losses=data.get("max_daily_consecutive_losses", 3),
            funded_account_type=data.get("funded_account_type", "STANDARD"),
            funded_account_rules=data.get("funded_account_rules", {}),
            trading_start_hour=data.get("trading_start_hour", 0),
            trading_end_hour=data.get("trading_end_hour", 23)
        )


@dataclass
class PortfolioStatus:
    """Current portfolio status."""
    timestamp: str
    account_balance: float
    account_equity: float
    account_leverage: int
    account_currency: str
    trade_size_in_usd: float
    
    # Daily
    daily_profit_usd: float
    daily_profit_percent: float
    daily_loss_usd: float
    daily_loss_percent: float
    daily_net_profit_usd: float
    daily_net_profit_percent: float
    daily_trades: int
    daily_wins: int
    daily_losses: int
    daily_win_rate: float
    daily_drawdown_percent: float
    daily_remaining_loss_percent: float
    daily_remaining_win_target_percent: float
    daily_consecutive_losses: int
    
    # Monthly
    monthly_profit_usd: float
    monthly_profit_percent: float
    monthly_loss_usd: float
    monthly_loss_percent: float
    monthly_net_profit_usd: float
    monthly_net_profit_percent: float
    monthly_trades: int
    monthly_wins: int
    monthly_losses: int
    monthly_win_rate: float
    monthly_drawdown_percent: float
    monthly_remaining_loss_percent: float
    monthly_remaining_win_target_percent: float
    
    # YTD
    ytd_profit_usd: float
    ytd_profit_percent: float
    ytd_loss_usd: float
    ytd_loss_percent: float
    ytd_net_profit_usd: float
    ytd_net_profit_percent: float
    ytd_trades: int
    ytd_wins: int
    ytd_losses: int
    ytd_win_rate: float
    ytd_drawdown_percent: float
    ytd_remaining_loss_percent: float
    
    # Overall
    overall_risk_level: RiskLevel
    max_drawdown_percent: float
    current_drawdown_percent: float
    consecutive_losses: int
    is_trading_allowed: bool
    trading_blocked_reasons: List[str]
    
    # Funded account specific
    funded_account_compliance: Dict[str, Any]
    
    # Current risk per trade
    max_risk_per_trade_percent: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "account_balance": round(self.account_balance, 2),
            "account_equity": round(self.account_equity, 2),
            "account_leverage": self.account_leverage,
            "account_currency": self.account_currency,
            "trade_size_in_usd": round(self.trade_size_in_usd, 2),
            "daily_profit_usd": round(self.daily_profit_usd, 2),
            "daily_profit_percent": round(self.daily_profit_percent, 2),
            "daily_loss_usd": round(self.daily_loss_usd, 2),
            "daily_loss_percent": round(self.daily_loss_percent, 2),
            "daily_net_profit_usd": round(self.daily_net_profit_usd, 2),
            "daily_net_profit_percent": round(self.daily_net_profit_percent, 2),
            "daily_trades": self.daily_trades,
            "daily_wins": self.daily_wins,
            "daily_losses": self.daily_losses,
            "daily_win_rate": round(self.daily_win_rate, 2),
            "daily_drawdown_percent": round(self.daily_drawdown_percent, 2),
            "daily_remaining_loss_percent": round(self.daily_remaining_loss_percent, 2),
            "daily_remaining_win_target_percent": round(self.daily_remaining_win_target_percent, 2),
            "daily_consecutive_losses": self.daily_consecutive_losses,
            "monthly_profit_usd": round(self.monthly_profit_usd, 2),
            "monthly_profit_percent": round(self.monthly_profit_percent, 2),
            "monthly_loss_usd": round(self.monthly_loss_usd, 2),
            "monthly_loss_percent": round(self.monthly_loss_percent, 2),
            "monthly_net_profit_usd": round(self.monthly_net_profit_usd, 2),
            "monthly_net_profit_percent": round(self.monthly_net_profit_percent, 2),
            "monthly_trades": self.monthly_trades,
            "monthly_wins": self.monthly_wins,
            "monthly_losses": self.monthly_losses,
            "monthly_win_rate": round(self.monthly_win_rate, 2),
            "monthly_drawdown_percent": round(self.monthly_drawdown_percent, 2),
            "monthly_remaining_loss_percent": round(self.monthly_remaining_loss_percent, 2),
            "monthly_remaining_win_target_percent": round(self.monthly_remaining_win_target_percent, 2),
            "ytd_profit_usd": round(self.ytd_profit_usd, 2),
            "ytd_profit_percent": round(self.ytd_profit_percent, 2),
            "ytd_loss_usd": round(self.ytd_loss_usd, 2),
            "ytd_loss_percent": round(self.ytd_loss_percent, 2),
            "ytd_net_profit_usd": round(self.ytd_net_profit_usd, 2),
            "ytd_net_profit_percent": round(self.ytd_net_profit_percent, 2),
            "ytd_trades": self.ytd_trades,
            "ytd_wins": self.ytd_wins,
            "ytd_losses": self.ytd_losses,
            "ytd_win_rate": round(self.ytd_win_rate, 2),
            "ytd_drawdown_percent": round(self.ytd_drawdown_percent, 2),
            "ytd_remaining_loss_percent": round(self.ytd_remaining_loss_percent, 2),
            "overall_risk_level": self.overall_risk_level.value,
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "current_drawdown_percent": round(self.current_drawdown_percent, 2),
            "consecutive_losses": self.consecutive_losses,
            "is_trading_allowed": self.is_trading_allowed,
            "trading_blocked_reasons": self.trading_blocked_reasons,
            "funded_account_compliance": self.funded_account_compliance,
            "max_risk_per_trade_percent": round(self.max_risk_per_trade_percent, 2)
        }


class PortfolioRiskService:
    """
    Portfolio Risk Management Service.
    
    Account balance and leverage are read from MT5 (read-only).
    All limits are in PERCENTAGE only.
    """
    
    # ============================================================
    # MONGO OPERATIONS
    # ============================================================

    def _load_from_mongo(self) -> bool:
        try:
            config_data = self.mongo_portfolio.load_config()
            if config_data:
                self.config = PortfolioRiskConfig.from_dict(config_data)
                logger.info("✅ Loaded portfolio config from MongoDB")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load from MongoDB: {e}")
            return False
    
    def _save_to_mongo(self) -> bool:
        try:
            config_data = self.config.to_dict()
            config_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.mongo_portfolio.save_config(config_data)
            
            if self._today_stats:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._today_stats["updated_at"] = datetime.now(timezone.utc).isoformat()
                self.mongo_portfolio.save_stats(self.COLLECTION_DAILY_STATS, today, self._today_stats)
            
            if self._month_stats:
                month = datetime.now(timezone.utc).strftime("%Y-%m")
                self._month_stats["updated_at"] = datetime.now(timezone.utc).isoformat()
                self.mongo_portfolio.save_stats(self.COLLECTION_MONTHLY_STATS, month, self._month_stats)
            
            if self._ytd_stats:
                year = datetime.now(timezone.utc).year
                self._ytd_stats["updated_at"] = datetime.now(timezone.utc).isoformat()
                self.mongo_portfolio.save_stats(self.COLLECTION_YTD_STATS, str(year), self._ytd_stats)
            
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save to MongoDB: {e}")
            return False

    # Firebase collections
    COLLECTION_TRADES = "trades"
    COLLECTION_PORTFOLIO = "portfolio_risk"
    COLLECTION_DAILY_STATS = "portfolio_daily_stats"
    COLLECTION_MONTHLY_STATS = "portfolio_monthly_stats"
    COLLECTION_YTD_STATS = "portfolio_ytd_stats"
    COLLECTION_CONFIG = "portfolio_config"
    
    def __init__(self, config: Optional[PortfolioRiskConfig] = None):
        self.config = config or PortfolioRiskConfig()
        
        self.mongo_portfolio = get_portfolio_service()
        self._lock = threading.RLock()
        
        # Account info from MT5 (cached)
        self._account_balance = 0.0
        self._account_equity = 0.0
        self._account_leverage = 0
        self._account_currency = "USD"
        self._last_account_update = 0
        
        # In-memory tracking
        self._today_stats: Optional[Dict] = None
        self._month_stats: Optional[Dict] = None
        self._ytd_stats: Optional[Dict] = None
        
        # Current session tracking
        self._consecutive_losses = 0
        self._daily_consecutive_losses = 0
        self._peak_balance = 0.0
        
        # Cache for closed trades
        self._closed_trades_cache: List[Dict[str, Any]] = []
        self._last_fetch_time = 0
        self._fetch_interval = 60
        
        # Initialize
        self._load_from_mongo()
        self._fetch_closed_trades()
        
        self._update_account_info()
        
        logger.info("✅ PortfolioRiskService initialized")
        logger.info(f"   Balance: ${self._account_balance:.2f}")
        logger.info(f"   Leverage: {self._account_leverage}")
        logger.info(f"   Trade Size: ${self.config.trade_size_in_usd}")
        logger.info(f"   Risk per Trade: {self.config.max_risk_per_trade_percent}%")
        logger.info(f"   Daily Loss Limit: {self.config.max_daily_loss_percent}%")
        logger.info(f"   Monthly Loss Limit: {self.config.max_monthly_loss_percent}%")
        logger.info(f"   Max Drawdown: {self.config.max_drawdown_percent}%")
    
    # ============================================================
    # ACCOUNT INFO (READ-ONLY FROM MT5)
    # ============================================================
    
    def _update_account_info(self) -> bool:
        """Update account information from MT5 (read-only)."""
        if not HAS_MT5:
            return False
        
        try:
            if not mt5.terminal_info():
                mt5.initialize()
            
            account_info = mt5.account_info()
            if account_info:
                self._account_balance = float(account_info.balance)
                self._account_equity = float(account_info.equity)
                self._account_leverage = int(account_info.leverage)
                self._account_currency = account_info.currency
                self._last_account_update = time.time()
                
                if self._account_balance > self._peak_balance:
                    self._peak_balance = self._account_balance
                
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Failed to get account info: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """Get current account balance from MT5."""
        self._update_account_info()
        return self._account_balance
    
    def get_account_equity(self) -> float:
        """Get current account equity from MT5."""
        self._update_account_info()
        return self._account_equity
    
    def get_account_leverage(self) -> int:
        """Get account leverage from MT5."""
        self._update_account_info()
        return self._account_leverage
    
    def get_account_currency(self) -> str:
        """Get account currency from MT5."""
        self._update_account_info()
        return self._account_currency
    
    # ============================================================
    # FETCH CLOSED TRADES FROM FIRESTORE
    # ============================================================
    
    def _fetch_closed_trades(self, force: bool = False) -> List[Dict[str, Any]]:
        """Closed trades, read from MongoDB.

        THIS USED TO READ FIRESTORE, AND RETURNED NOTHING.
        ---------------------------------------------------
        It queried `firebase.db.collection("trades")`, but trades have not been
        written to Firestore since TRADES_TO_FIRESTORE was turned off -- they
        live in `easytradify.trades` in Mongo. The query was valid, the
        collection was empty, and the failure was completely silent: every
        statistic downstream is computed from this list, so daily/monthly/YTD
        profit, win rate and consecutive losses all read as zero.

        That is not merely a cosmetic wrong number. `check_trading_allowed()`
        blocks on the daily loss limit, and a daily loss computed from an empty
        set is always 0.00 -- so the limit that exists to stop an account being
        blown could never fire, whatever had actually been lost that day.

        The returned shape is unchanged, so every caller and every statistic
        below works as written.
        """
        current_time = time.time()
        if not force and (current_time - self._last_fetch_time) < self._fetch_interval:
            return self._closed_trades_cache

        try:
            try:
                from core.mongo.trades_service import get_trades_service
            except ImportError:
                from mongo.trades_service import get_trades_service

            service = get_trades_service()

            # Paged rather than one huge read: the collection grows without
            # bound and `price_evolution` is tens of megabytes across a few
            # hundred trades. include_heavy stays False for exactly that reason.
            closed_trades: List[Dict[str, Any]] = []
            page = 1
            while True:
                result = service.list_trades(
                    page=page,
                    page_size=200,
                    sort_by="closed_at",
                    sort_dir="desc",
                    filters={"status": "CLOSED"},
                    include_heavy=False,
                )

                items = result.get("items") or result.get("trades") or []
                if not items:
                    break

                for data in items:
                    trade = self._closed_trade_from_document(data)
                    if trade is not None:
                        closed_trades.append(trade)

                # Stop at the last page, and hard-stop at a sane ceiling so a
                # runaway collection cannot hang the risk check.
                total = result.get("total")
                if len(items) < 200 or (total is not None and len(closed_trades) >= total):
                    break
                page += 1
                if page > 50:
                    logger.warning("Stopped reading closed trades at 10,000 rows")
                    break

            closed_trades.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)

            self._closed_trades_cache = closed_trades
            self._last_fetch_time = current_time

            logger.info(f"Loaded {len(closed_trades)} closed trades from MongoDB")
            return closed_trades

        except Exception as e:
            # Keep the previous cache rather than returning [] -- an empty list
            # here reads as "no losses today" and would re-open the limits that
            # this whole class exists to enforce.
            logger.error(f"Failed to fetch closed trades from MongoDB: {e}")
            return self._closed_trades_cache

    def _closed_trade_from_document(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """One stored trade -> the flat shape the statistics below expect.

        Returns None for a row that cannot be scored, rather than defaulting it
        to zero profit: a trade counted with a fabricated 0.00 quietly drags the
        win rate and the daily total toward a number nobody measured.
        """
        close_data = data.get("close_data") or {}

        profit_usd = close_data.get("profit_usd")
        if profit_usd is None:
            profit_usd = close_data.get("profit")
        if profit_usd is None:
            profit_usd = data.get("profit_usd")
        if profit_usd is None:
            return None

        try:
            profit_usd = float(profit_usd)
        except (TypeError, ValueError):
            return None

        entry = data.get("entry") or {}
        price_open = close_data.get("price_open") or entry.get("price") or data.get("price") or 0.0
        volume = close_data.get("volume") or entry.get("volume") or data.get("volume") or 0.0

        closed_at_dt = self._parse_closed_at(
            close_data.get("closed_at") or data.get("closed_at") or data.get("updated_at"))

        return {
            "ticket": data.get("ticket") or data.get("trade_id", 0),
            "symbol": data.get("symbol", "UNKNOWN"),
            # `direction` is the recorded order side. Never infer it from
            # whether price moved up or down -- that inference mislabelled
            # trades everywhere it appeared in this codebase.
            "order_type": data.get("direction") or data.get("order_type") or "BUY",
            "entry_price": price_open,
            "exit_price": close_data.get("close_price") or close_data.get("price") or 0.0,
            "profit_usd": profit_usd,
            "profit_percent": close_data.get("profit_percent", 0.0),
            # Derived, not trusted: a zero-profit scratch is not a win.
            "is_winning": profit_usd > 0,
            "close_reason": close_data.get("close_reason") or close_data.get("reason") or "UNKNOWN",
            "volume": volume,
            "closed_at": closed_at_dt.isoformat(),
            "timestamp": closed_at_dt,
            "date": closed_at_dt.strftime("%Y-%m-%d"),
            "month": closed_at_dt.strftime("%Y-%m"),
            "year": closed_at_dt.year,
        }

    @staticmethod
    def _parse_closed_at(value: Any) -> datetime:
        """Mongo hands back a datetime; the HTTP layer hands back an ISO string."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        # Unparseable: treat as now, so the trade lands in today's bucket rather
        # than 1970 where it would silently vanish from every period total.
        return datetime.now(timezone.utc)

    def _get_trades_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        closed_trades = self._fetch_closed_trades()
        return [t for t in closed_trades if t.get("date") == date_str]
    
    def _get_trades_for_month(self, month_str: str) -> List[Dict[str, Any]]:
        closed_trades = self._fetch_closed_trades()
        return [t for t in closed_trades if t.get("month") == month_str]
    
    def _get_trades_for_year(self, year: int) -> List[Dict[str, Any]]:
        closed_trades = self._fetch_closed_trades()
        return [t for t in closed_trades if t.get("year") == year]
    
    def _calculate_stats_from_trades(self, trades: List[Dict[str, Any]], 
                                     starting_balance: float) -> Dict[str, Any]:
        if not trades:
            return {
                "total_profit_usd": 0.0, "total_profit_percent": 0.0,
                "total_loss_usd": 0.0, "total_loss_percent": 0.0,
                "net_profit_usd": 0.0, "net_profit_percent": 0.0,
                "trades_count": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0.0, "max_drawdown_percent": 0.0,
                "ending_balance": starting_balance, "peak_balance": starting_balance
            }
        
        total_profit_usd = 0.0
        total_profit_percent = 0.0
        total_loss_usd = 0.0
        total_loss_percent = 0.0
        net_profit_usd = 0.0
        net_profit_percent = 0.0
        winning_trades = 0
        losing_trades = 0
        max_drawdown_percent = 0.0
        peak_balance = starting_balance
        current_balance = starting_balance
        
        for trade in trades:
            profit_usd = trade.get("profit_usd", 0.0)
            profit_percent = trade.get("profit_percent", 0.0)
            
            if profit_usd > 0:
                total_profit_usd += profit_usd
                total_profit_percent += profit_percent
                winning_trades += 1
            else:
                total_loss_usd += abs(profit_usd)
                total_loss_percent += abs(profit_percent)
                losing_trades += 1
            
            net_profit_usd += profit_usd
            net_profit_percent += profit_percent
            current_balance += profit_usd
            
            if current_balance > peak_balance:
                peak_balance = current_balance
            
            if peak_balance > 0:
                drawdown_percent = ((peak_balance - current_balance) / peak_balance) * 100
                if drawdown_percent > max_drawdown_percent:
                    max_drawdown_percent = drawdown_percent
        
        trades_count = len(trades)
        win_rate = (winning_trades / trades_count * 100) if trades_count > 0 else 0.0
        
        return {
            "total_profit_usd": total_profit_usd,
            "total_profit_percent": total_profit_percent,
            "total_loss_usd": total_loss_usd,
            "total_loss_percent": total_loss_percent,
            "net_profit_usd": net_profit_usd,
            "net_profit_percent": net_profit_percent,
            "trades_count": trades_count,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "max_drawdown_percent": max_drawdown_percent,
            "ending_balance": current_balance,
            "peak_balance": peak_balance
        }
    
    # ============================================================
    # STATS INITIALIZATION
    # ============================================================
    
    def _ensure_stats_initialized(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        year = datetime.now(timezone.utc).year
        balance = self._account_balance
        
        self._fetch_closed_trades()
        
        if self._today_stats is None or self._today_stats.get("date") != today:
            daily_trades = self._get_trades_for_date(today)
            daily_calc = self._calculate_stats_from_trades(daily_trades, balance)
            daily_calc["date"] = today
            self._today_stats = daily_calc
            logger.info(f"📊 Calculated daily stats for {today}")
        
        if self._month_stats is None or self._month_stats.get("month") != month:
            monthly_trades = self._get_trades_for_month(month)
            monthly_calc = self._calculate_stats_from_trades(monthly_trades, balance)
            monthly_calc["month"] = month
            self._month_stats = monthly_calc
            logger.info(f"📊 Calculated monthly stats for {month}")
        
        if self._ytd_stats is None or self._ytd_stats.get("year") != year:
            ytd_trades = self._get_trades_for_year(year)
            ytd_calc = self._calculate_stats_from_trades(ytd_trades, balance)
            ytd_calc["year"] = year
            self._ytd_stats = ytd_calc
            logger.info(f"📊 Calculated YTD stats for {year}")
    
    # ============================================================
    # DRAWDOWN CALCULATIONS
    # ============================================================
    
    def get_current_drawdown_percent(self) -> float:
        """Get current drawdown as percentage."""
        balance = self._account_balance
        peak = self._peak_balance or balance
        
        if self._today_stats and self._today_stats.get("peak_balance", 0) > peak:
            peak = self._today_stats.get("peak_balance", 0)
        if self._month_stats and self._month_stats.get("peak_balance", 0) > peak:
            peak = self._month_stats.get("peak_balance", 0)
        if self._ytd_stats and self._ytd_stats.get("peak_balance", 0) > peak:
            peak = self._ytd_stats.get("peak_balance", 0)
        
        if peak > 0:
            return max(0, (peak - balance) / peak * 100)
        return 0.0
    
    def get_max_drawdown_percent(self) -> float:
        """Get maximum historical drawdown as percentage."""
        max_dd = 0.0
        if self._today_stats:
            max_dd = max(max_dd, self._today_stats.get("max_drawdown_percent", 0))
        if self._month_stats:
            max_dd = max(max_dd, self._month_stats.get("max_drawdown_percent", 0))
        if self._ytd_stats:
            max_dd = max(max_dd, self._ytd_stats.get("max_drawdown_percent", 0))
        return max_dd
    
    # ============================================================
    # RISK CHECKING
    # ============================================================
    
    def check_trading_allowed(self, trade_risk_percent: Optional[float] = None) -> Tuple[bool, List[str], RiskLevel]:
        """
        Check if trading is allowed based on portfolio risk limits.
        
        Args:
            trade_risk_percent: Optional risk as percentage of account for this trade
        
        Returns:
            Tuple of (is_allowed, reasons, risk_level)
        """
        with self._lock:
            reasons = []
            
            self._update_account_info()
            self._ensure_stats_initialized()
            
            balance = self._account_balance
            
            if balance <= 0:
                reasons.append("Account balance is zero or negative")
                return False, reasons, RiskLevel.CRITICAL
            
            # Check trading hours
            current_hour = datetime.now(timezone.utc).hour
            if self.config.trading_start_hour <= self.config.trading_end_hour:
                if current_hour < self.config.trading_start_hour or current_hour > self.config.trading_end_hour:
                    reasons.append(f"Outside trading hours ({self.config.trading_start_hour}:00 - {self.config.trading_end_hour}:00 UTC)")
            
            # Daily loss limit
            daily_loss_percent = self._today_stats.get("total_loss_percent", 0) if self._today_stats else 0
            if daily_loss_percent >= self.config.max_daily_loss_percent:
                reasons.append(f"Daily loss limit reached: {daily_loss_percent:.2f}% >= {self.config.max_daily_loss_percent}%")
            
            # Daily win target
            daily_profit_percent = self._today_stats.get("total_profit_percent", 0) if self._today_stats else 0
            if daily_profit_percent >= self.config.max_daily_win_target_percent:
                reasons.append(f"Daily win target reached: {daily_profit_percent:.2f}% >= {self.config.max_daily_win_target_percent}%")
            
            # Daily trade count
            daily_trades = self._today_stats.get("trades_count", 0) if self._today_stats else 0
            if daily_trades >= self.config.max_daily_trades:
                reasons.append(f"Daily trade limit reached: {daily_trades}/{self.config.max_daily_trades}")
            
            # Monthly loss limit
            monthly_loss_percent = self._month_stats.get("total_loss_percent", 0) if self._month_stats else 0
            if monthly_loss_percent >= self.config.max_monthly_loss_percent:
                reasons.append(f"Monthly loss limit reached: {monthly_loss_percent:.2f}% >= {self.config.max_monthly_loss_percent}%")
            
            # Monthly win target
            monthly_profit_percent = self._month_stats.get("total_profit_percent", 0) if self._month_stats else 0
            if monthly_profit_percent >= self.config.max_monthly_win_target_percent:
                reasons.append(f"Monthly win target reached: {monthly_profit_percent:.2f}% >= {self.config.max_monthly_win_target_percent}%")
            
            # Monthly trade count
            monthly_trades = self._month_stats.get("trades_count", 0) if self._month_stats else 0
            if monthly_trades >= self.config.max_monthly_trades:
                reasons.append(f"Monthly trade limit reached: {monthly_trades}/{self.config.max_monthly_trades}")
            
            # YTD loss limit
            ytd_loss_percent = self._ytd_stats.get("total_loss_percent", 0) if self._ytd_stats else 0
            if ytd_loss_percent >= self.config.max_ytd_loss_percent:
                reasons.append(f"YTD loss limit reached: {ytd_loss_percent:.2f}% >= {self.config.max_ytd_loss_percent}%")
            
            # Drawdown limit
            current_drawdown_percent = self.get_current_drawdown_percent()
            if current_drawdown_percent >= self.config.max_drawdown_percent:
                reasons.append(f"Drawdown limit reached: {current_drawdown_percent:.2f}% >= {self.config.max_drawdown_percent}%")
            
            # Consecutive losses
            if self._consecutive_losses >= self.config.max_consecutive_losses:
                reasons.append(f"Max consecutive losses reached: {self._consecutive_losses}/{self.config.max_consecutive_losses}")
            
            if self._daily_consecutive_losses >= self.config.max_daily_consecutive_losses:
                reasons.append(f"Max daily consecutive losses reached: {self._daily_consecutive_losses}/{self.config.max_daily_consecutive_losses}")
            
            # Per-trade risk check
            if trade_risk_percent is not None:
                if trade_risk_percent > self.config.max_risk_per_trade_percent:
                    reasons.append(f"Trade risk {trade_risk_percent:.2f}% exceeds max {self.config.max_risk_per_trade_percent}%")
            
            # Determine risk level
            risk_level = RiskLevel.SAFE
            if reasons:
                critical_reasons = ["Account balance is zero or negative", "Daily loss limit reached", "Monthly loss limit reached", "YTD loss limit reached"]
                critical_count = sum(1 for r in reasons if any(cr in r for cr in critical_reasons))
                
                if critical_count > 0:
                    risk_level = RiskLevel.MAX_EXCEEDED
                elif len(reasons) >= 3:
                    risk_level = RiskLevel.CRITICAL
                elif len(reasons) >= 2:
                    risk_level = RiskLevel.WARNING
                else:
                    risk_level = RiskLevel.CAUTION
            
            if reasons:
                logger.warning(f"⚠️ Trading blocked for {len(reasons)} reasons: {', '.join(reasons)}")
            
            return len(reasons) == 0, reasons, risk_level
    
    def get_max_risk_for_trade(self) -> float:
        """Get the maximum risk percentage allowed for a trade."""
        return self.config.max_risk_per_trade_percent
    
    # ============================================================
    # UPDATE CONSECUTIVE LOSSES
    # ============================================================
    
    def update_consecutive_losses(self, trade_profit_usd: float):
        """Update consecutive loss counters based on trade result."""
        with self._lock:
            if trade_profit_usd >= 0:
                self._consecutive_losses = 0
                self._daily_consecutive_losses = 0
            else:
                self._consecutive_losses += 1
                self._daily_consecutive_losses += 1
    
    # ============================================================
    # STATUS
    # ============================================================
    
    def get_status(self, force_refresh: bool = False) -> PortfolioStatus:
        """Get current portfolio status."""
        with self._lock:
            if force_refresh:
                self._fetch_closed_trades(force=True)
            
            self._update_account_info()
            self._ensure_stats_initialized()
            
            balance = self._account_balance
            equity = self._account_equity
            leverage = self._account_leverage
            currency = self._account_currency
            
            daily = self._today_stats or {}
            monthly = self._month_stats or {}
            ytd = self._ytd_stats or {}
            
            is_allowed, reasons, risk_level = self.check_trading_allowed()
            funded_compliance = self._check_funded_account_compliance()
            
            return PortfolioStatus(
                timestamp=datetime.now(timezone.utc).isoformat(),
                account_balance=balance,
                account_equity=equity,
                account_leverage=leverage,
                account_currency=currency,
                trade_size_in_usd=self.config.trade_size_in_usd,
                
                daily_profit_usd=daily.get("total_profit_usd", 0),
                daily_profit_percent=daily.get("total_profit_percent", 0),
                daily_loss_usd=daily.get("total_loss_usd", 0),
                daily_loss_percent=daily.get("total_loss_percent", 0),
                daily_net_profit_usd=daily.get("net_profit_usd", 0),
                daily_net_profit_percent=daily.get("net_profit_percent", 0),
                daily_trades=daily.get("trades_count", 0),
                daily_wins=daily.get("winning_trades", 0),
                daily_losses=daily.get("losing_trades", 0),
                daily_win_rate=daily.get("win_rate", 0),
                daily_drawdown_percent=daily.get("max_drawdown_percent", 0),
                daily_remaining_loss_percent=max(0, self.config.max_daily_loss_percent - daily.get("total_loss_percent", 0)),
                daily_remaining_win_target_percent=max(0, self.config.max_daily_win_target_percent - daily.get("total_profit_percent", 0)),
                daily_consecutive_losses=self._daily_consecutive_losses,
                
                monthly_profit_usd=monthly.get("total_profit_usd", 0),
                monthly_profit_percent=monthly.get("total_profit_percent", 0),
                monthly_loss_usd=monthly.get("total_loss_usd", 0),
                monthly_loss_percent=monthly.get("total_loss_percent", 0),
                monthly_net_profit_usd=monthly.get("net_profit_usd", 0),
                monthly_net_profit_percent=monthly.get("net_profit_percent", 0),
                monthly_trades=monthly.get("trades_count", 0),
                monthly_wins=monthly.get("winning_trades", 0),
                monthly_losses=monthly.get("losing_trades", 0),
                monthly_win_rate=monthly.get("win_rate", 0),
                monthly_drawdown_percent=monthly.get("max_drawdown_percent", 0),
                monthly_remaining_loss_percent=max(0, self.config.max_monthly_loss_percent - monthly.get("total_loss_percent", 0)),
                monthly_remaining_win_target_percent=max(0, self.config.max_monthly_win_target_percent - monthly.get("total_profit_percent", 0)),
                
                ytd_profit_usd=ytd.get("total_profit_usd", 0),
                ytd_profit_percent=ytd.get("total_profit_percent", 0),
                ytd_loss_usd=ytd.get("total_loss_usd", 0),
                ytd_loss_percent=ytd.get("total_loss_percent", 0),
                ytd_net_profit_usd=ytd.get("net_profit_usd", 0),
                ytd_net_profit_percent=ytd.get("net_profit_percent", 0),
                ytd_trades=ytd.get("trades_count", 0),
                ytd_wins=ytd.get("winning_trades", 0),
                ytd_losses=ytd.get("losing_trades", 0),
                ytd_win_rate=ytd.get("win_rate", 0),
                ytd_drawdown_percent=ytd.get("max_drawdown_percent", 0),
                ytd_remaining_loss_percent=max(0, self.config.max_ytd_loss_percent - ytd.get("total_loss_percent", 0)),
                
                overall_risk_level=risk_level,
                max_drawdown_percent=self.get_max_drawdown_percent(),
                current_drawdown_percent=self.get_current_drawdown_percent(),
                consecutive_losses=self._consecutive_losses,
                is_trading_allowed=is_allowed,
                trading_blocked_reasons=reasons,
                funded_account_compliance=funded_compliance,
                max_risk_per_trade_percent=self.config.max_risk_per_trade_percent
            )
    
    def _check_funded_account_compliance(self) -> Dict[str, Any]:
        compliance = {"type": self.config.funded_account_type, "compliant": True, "violations": []}
        
        if self.config.funded_account_type == "STANDARD":
            return compliance
        
        if self.config.funded_account_type == "FTMO":
            if self.config.max_daily_loss_percent > 5.0:
                compliance["violations"].append(f"Daily loss limit {self.config.max_daily_loss_percent}% exceeds FTMO max 5%")
            if self.config.max_monthly_loss_percent > 10.0:
                compliance["violations"].append(f"Monthly loss limit {self.config.max_monthly_loss_percent}% exceeds FTMO max 10%")
            if self.config.max_drawdown_percent > 10.0:
                compliance["violations"].append(f"Drawdown limit {self.config.max_drawdown_percent}% exceeds FTMO max 10%")
            if self.config.max_risk_per_trade_percent > 1.0:
                compliance["violations"].append(f"Risk per trade {self.config.max_risk_per_trade_percent}% exceeds FTMO recommended 1%")
        
        if self.config.funded_account_type == "MFF":
            if self.config.max_daily_loss_percent > 5.0:
                compliance["violations"].append(f"Daily loss limit {self.config.max_daily_loss_percent}% exceeds MFF max 5%")
            if self.config.max_monthly_loss_percent > 12.0:
                compliance["violations"].append(f"Monthly loss limit {self.config.max_monthly_loss_percent}% exceeds MFF max 12%")
            if self.config.max_drawdown_percent > 12.0:
                compliance["violations"].append(f"Drawdown limit {self.config.max_drawdown_percent}% exceeds MFF max 12%")
        
        if self.config.funded_account_type == "TFT":
            if self.config.max_daily_loss_percent > 5.0:
                compliance["violations"].append(f"Daily loss limit {self.config.max_daily_loss_percent}% exceeds TFT max 5%")
            if self.config.max_monthly_loss_percent > 8.0:
                compliance["violations"].append(f"Monthly loss limit {self.config.max_monthly_loss_percent}% exceeds TFT max 8%")
            if self.config.max_drawdown_percent > 8.0:
                compliance["violations"].append(f"Drawdown limit {self.config.max_drawdown_percent}% exceeds TFT max 8%")
        
        if compliance["violations"]:
            compliance["compliant"] = False
        
        return compliance
    
    # ============================================================
    # CONFIGURATION METHODS
    # ============================================================
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """
        Update user-editable portfolio and execution configuration.

        Execution settings are intentionally stored here so the portfolio
        service is the single source of truth for their current values.
        Unknown fields are rejected instead of silently ignored.
        """
        with self._lock:
            try:
                if not isinstance(updates, dict):
                    raise ValueError("updates must be a dictionary")

                supported_fields = set(self.config.to_dict().keys())
                # Metadata is persisted by _save_to_mongo and is not a config field.
                unknown_fields = [key for key in updates if key not in supported_fields]
                if unknown_fields:
                    raise ValueError(
                        f"Unsupported portfolio configuration fields: {', '.join(unknown_fields)}"
                    )

                bool_fields = {
                    "enable_breakeven",
                    "enable_auto_trailing_stop",
                    "auto_max_spread",
                    "auto_trade_deviation",
                    "auto_max_trades_per_symbol",
                    "auto_max_simultaneous_trades",
                }
                float_fields = {
                    "trade_size_in_usd",
                    "auto_breakeven_usd",
                    "auto_trailing_stop_usd",
                    "max_spread",
                    "max_daily_loss_percent",
                    "max_daily_win_target_percent",
                    "max_monthly_loss_percent",
                    "max_monthly_win_target_percent",
                    "max_ytd_loss_percent",
                    "max_risk_per_trade_percent",
                    "max_drawdown_percent",
                }
                int_fields = {
                    "trade_deviation",
                    "max_trades_per_symbol",
                    "max_simultaneous_trades",
                    "max_daily_trades",
                    "max_monthly_trades",
                    "max_consecutive_losses",
                    "max_daily_consecutive_losses",
                    "trading_start_hour",
                    "trading_end_hour",
                }

                for key, value in updates.items():
                    if key in bool_fields:
                        if not isinstance(value, bool):
                            raise ValueError(f"{key} must be true or false")
                        setattr(self.config, key, value)
                    elif key in float_fields:
                        numeric_value = float(value)
                        if numeric_value < 0:
                            raise ValueError(f"{key} cannot be negative")
                        setattr(self.config, key, numeric_value)
                    elif key in int_fields:
                        int_value = int(value)
                        if int_value < 0:
                            raise ValueError(f"{key} cannot be negative")
                        setattr(self.config, key, int_value)
                    elif key == "funded_account_rules":
                        if not isinstance(value, dict):
                            raise ValueError("funded_account_rules must be a dictionary")
                        setattr(self.config, key, value)
                    elif key == "funded_account_type":
                        setattr(self.config, key, str(value).upper())
                    else:
                        setattr(self.config, key, value)

                if self.config.auto_breakeven_usd <= 0:
                    raise ValueError("auto_breakeven_usd must be greater than 0")
                if self.config.auto_trailing_stop_usd <= 0:
                    raise ValueError("auto_trailing_stop_usd must be greater than 0")
                if self.config.max_spread <= 0:
                    raise ValueError("max_spread must be greater than 0")
                if self.config.trade_deviation <= 0:
                    raise ValueError("trade_deviation must be greater than 0")
                if self.config.max_trades_per_symbol <= 0:
                    raise ValueError("max_trades_per_symbol must be greater than 0")
                if self.config.max_simultaneous_trades <= 0:
                    raise ValueError("max_simultaneous_trades must be greater than 0")

                saved = self._save_to_mongo()
                if not saved:
                    return False

                logger.info(f"✅ Portfolio config updated: {list(updates.keys())}")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to update config: {e}")
                return False
    
    def refresh_stats(self) -> bool:
        """Force refresh statistics from MongoDB."""
        with self._lock:
            self._fetch_closed_trades(force=True)
            self._ensure_stats_initialized()
            self._save_to_mongo()
            return True


# ============================================================
# SINGLETON INSTANCE
# ============================================================

_portfolio_risk_service = None


def get_portfolio_risk_service() -> PortfolioRiskService:
    global _portfolio_risk_service
    if _portfolio_risk_service is None:
        _portfolio_risk_service = PortfolioRiskService()
    return _portfolio_risk_service

