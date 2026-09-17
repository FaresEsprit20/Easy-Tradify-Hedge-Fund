# api/monitor_models.py
# ============================================================
# DATA CLASSES
# ============================================================

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime

@dataclass
class SymbolStatus:
    symbol: str
    confidence: float = 0.0
    is_active: bool = False
    is_trading: bool = False
    in_position: bool = False
    ticket: Optional[int] = None
    entry_price: Optional[float] = None
    reason: str = ""
    exchange: str = "FX"
    last_check_time: float = 0
    stability_status: str = "⏳ WAITING"

@dataclass
class TradeResult:
    symbol: str
    success: bool
    ticket: Optional[int] = None
    error: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None
    volume: Optional[float] = None
    actual_margin: Optional[float] = None
    actual_risk_usd: Optional[float] = None
    risk_percent_used: Optional[float] = None
    probability_of_hit_percent: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    magic: Optional[int] = None
    comment: Optional[str] = None
    order_type: str = "BUY"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    full_execution_response: Optional[Dict[str, Any]] = None
    analysis_data: Optional[Dict[str, Any]] = None
    trade_params: Optional[Dict[str, Any]] = None
    final_verdict: Optional[Dict[str, Any]] = None
    full_analysis: Optional[Dict[str, Any]] = None