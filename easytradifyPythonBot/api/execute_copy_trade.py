# api/execute_copy_trade.py
# ============================================================
# REST API CONTROLLER FOR SPRING BOOT INTEGRATION
# TP1 (native MT5 TP) + OPTIONAL TP2/TP3 (managed via partial closes,
# since MT5 only supports a single native TP per position)
# WITH BREAK-EVEN + PIP/USD-DISTANCE TRAILING STOP
# AUTO-CALCULATES SL FROM risk_per_trade
# TP IS OPTIONAL - ONLY SET IF PROVIDED
# ✅ COPY-TRADE MANAGER PORTED FROM monitor/monitor_core.py:
#    same Firebase trade-open/price-evolution/close saving,
#    same webhook close + trailing handlers, same JSON trade
#    logging, same thread-safe position-close (SL/TP) detection -
#    minus the market scanning/filtering, which this controller
#    doesn't need since trades arrive already decided.
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

from flask import Blueprint, request, jsonify
import json
import time
import logging
import threading
import traceback
from datetime import datetime, timezone
import MetaTrader5 as mt5
import sys
import os
import math
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.asset_analysis import analyze_institutional_signal

from core.execution import (
    execute_trade,
    get_open_positions,
    calculate_lot,
    close_position,
    get_trade_history,
    close_all_positions,
    modify_stop_loss,
    modify_take_profit,
    partial_close_position,
    get_position_details,
    get_account_info,
    get_active_trails,
    get_break_even_status,
    get_symbol_info,
    calculate_probability_of_hit,
    get_current_spread,
    calculate_trend_strength,
    get_atr_value,
    is_market_closed,
    check_volatility,
    check_spread_status,
    get_trail_stats,
    TradingException,
    ErrorCode
)

from core.mt5_connector import connect_mt5, shutdown_mt5

# ============================================================
# ✅ PORTED FROM monitor/monitor_core.py (MultiSymbolMonitor)
# Same TradeResult model + Firebase helpers the monitor uses,
# so copy-trade executions are saved through the exact same
# pipeline (open save, price evolution, close save, webhook
# close, trailing webhook) - just without the scanning/filter
# machinery, which copy-trade doesn't need.
# ============================================================
from monitor.monitor_models import TradeResult
from monitor.firebase_helpers import (
    save_trade_open_to_firebase,
    update_trade_price_in_firebase as fb_update_price,
    save_trade_close_to_firebase,
    save_trailing_stop_to_firebase,
    process_trailing_webhook,
)

logger = logging.getLogger(__name__)
api_bp = Blueprint('trading_api', __name__, url_prefix='/api/v1')
mt5_connected = False


def _num(value, default: float = 0.0) -> float:
    """
    A price/volume field as a number, whatever shape it arrived in.

    MT5 and the trade cache both use None for "not set" -- an absent take
    profit is None, not 0 -- and dict.get(key, 0) does NOT protect against
    that: the default applies only when the KEY is missing, never when its
    value is None. Comparing the result with `> 0` then raises TypeError,
    which is what wedged the position monitor in an endless close loop.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Both close paths -- this one and monitor/monitor_core.py -- reconstruct a
# close the same way, and used to hold separate identical copies of this logic
# carrying the same two defects (stop-loss used as the exit, FX contract size
# applied to gold and oil). It now lives in one place.
from core.broker_facts import contract_size as _contract_size, closing_deal as _closing_deal
from monitor.firebase_helpers import _direction_of_record, _normalise_direction


def make_json_safe(value):
    """Recursively convert a value into something json.dumps AND Firestore
    can handle. Mirrors firebase_service.py's _convert_numpy_types fixes:
    NaN/Infinity floats are rejected by Firestore (-> None), and so is any
    array whose direct elements are themselves arrays (-> wrap in a map).
    Without this, raw analyzer output embedded under analysis_at_open /
    analysis_data (candle-style list-of-lists, NaN indicators, etc.) gets
    rejected with '400 Property ... contains an invalid nested entity' on
    every single trade, and the failed write is endlessly re-queued and
    retried by the batch processor until it hits its retry cap and is
    silently dropped."""
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        converted_items = [make_json_safe(v) for v in value]
        return [
            {"_values": item} if isinstance(item, (list, tuple)) else item
            for item in converted_items
        ]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


# ============================================================
# COPY TRADE MANAGER
# ------------------------------------------------------------
# Thread-safe execution/firebase/webhook layer, structurally a
# 1:1 port of the equivalent sections of MultiSymbolMonitor:
#   KEPT:    firebase trade-open / price-evolution / close saving,
#            webhook close + trailing handling, JSON trade logging,
#            position-close detection (SL/TP hit polling), and the
#            background threads that drive all of the above.
#   DROPPED: MT5 symbol discovery/broker-pattern mapping, the
#            confidence filter, top-symbol refresh, fast-entry
#            scanning, and periodic re-analysis loops - copy-trade
#            receives already-decided trades from the caller
#            (Spring Boot / webhook), it does not scan the market.
# Same lock discipline as the monitor: one RLock guards all shared
# mutable state, and every public entry point (register_trade_open,
# webhook handlers, the monitor/health loops) takes it before
# touching open_positions / caches / stats.
# ============================================================

class CopyTradeManager:

    # Defaults only used for the M1/M5/H1 analysis snapshots saved
    # alongside a trade (analysis_at_open / analysis_at_close). The
    # actual trade size/risk for execution itself always comes from
    # the request that hit /trade/execute.
    DEFAULT_FIXED_TRADE_SIZE_USD = 200
    # Fraction of DEFAULT_FIXED_TRADE_SIZE_USD, not of the account.
    # 0.02 -> $4 risk. See the note in monitor/monitor_config.py.
    DEFAULT_RISK_PER_TRADE = 0.02

    # Same cadence as the monitor: encoded price-evolution snapshots
    # are written at most once per minute per ticket.
    PRICE_UPDATE_INTERVAL = 60

    def __init__(self, log_filename: str = "copy_trade_log.json"):
        # ✅ Same lock discipline as monitor_core.py
        self._state_lock = threading.RLock()

        # symbol -> ticket (kept identical in shape to monitor_core.py's
        # open_positions so it stays compatible with the firebase_helpers
        # functions that expect this attribute on the "monitor" object)
        self.open_positions: Dict[str, int] = {}
        # symbol -> mt5 symbol. Copy-trade executes whatever symbol the
        # caller already validated, so this is just an identity map
        # populated as trades open (no discovery/broker-pattern step).
        self.symbol_mt5_map: Dict[str, str] = {}
        self._position_data_cache: Dict[int, Dict[str, Any]] = {}
        self._webhook_closed_tickets = set()
        # Kept for compatibility with any firebase_helpers code that
        # touches monitor.symbol_status_map - copy-trade never populates it.
        self.symbol_status_map: Dict[str, Any] = {}

        self.FIXED_TRADE_SIZE_USD = self.DEFAULT_FIXED_TRADE_SIZE_USD
        self.RISK_PER_TRADE = self.DEFAULT_RISK_PER_TRADE

        self.stop_event = threading.Event()
        self.running = False
        self.position_monitor_thread: Optional[threading.Thread] = None
        self.health_thread: Optional[threading.Thread] = None

        self._last_price_update_time = 0

        self.stats = {
            "start_time": None,
            "trades_registered": 0,
            "trades_closed": 0,
            "firebase_saves": 0,
            "firebase_errors": 0,
            "webhook_closes": 0,
            "trailing_updates": 0,
            "price_updates": 0,
            "monitor_errors": 0,
        }

        self.log_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / log_filename
        self._init_log_file()

        self.firebase = self._get_firebase()

        self._sync_open_positions()

        print(f"✅ CopyTradeManager initialized (log: {self.log_path.name})")

    # ============================================================
    # FIREBASE CONNECTION
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
                        self.symbol_mt5_map.setdefault(symbol, symbol)
                if positions:
                    print(f"📊 Synced {len(self.open_positions)} open positions")
        except Exception as e:
            print(f"❌ Failed to sync positions: {e}")

    # ============================================================
    # LOGGING (identical structure/format to monitor_core.py)
    # ============================================================

    def _init_log_file(self):
        if not self.log_path.exists():
            initial_data = {
                "monitor_info": {
                    "created_at": datetime.now().isoformat(),
                    "source": "copy_trade_execute",
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
    # FIREBASE HELPERS (delegates to monitor.firebase_helpers,
    # identical to monitor_core.py)
    # ============================================================

    def _save_trade_open_to_firebase(self, trade_result: TradeResult, analysis_result: Dict[str, Any],
                                      fixed_trade_size_usd: float, risk_per_trade: float):
        return save_trade_open_to_firebase(
            firebase_service=self.firebase,
            trade_result=trade_result,
            analysis_result=analysis_result,
            symbol_mt5_map=self.symbol_mt5_map,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            stats=self.stats
        )

    def _update_trade_price_in_firebase(self, ticket: int, position: Dict[str, Any],
                                         fixed_trade_size_usd: float, risk_per_trade: float):
        current_time = time.time()
        if current_time - self._last_price_update_time < self.PRICE_UPDATE_INTERVAL:
            return

        if self.firebase:
            try:
                existing_trade = self.firebase.get_trade(str(ticket))
                if existing_trade:
                    existing_close = existing_trade.get("close_data", {})
                    if existing_close.get("close_price", 0) != 0:
                        print(f"⏭️ Trade {ticket} already closed in Firebase - skipping price evolution update")
                        return
            except Exception as e:
                print(f"⚠️ Could not check Firebase for ticket {ticket}: {e}")

        self._last_price_update_time = current_time
        self.stats["price_updates"] = self.stats.get("price_updates", 0) + 1

        return fb_update_price(
            firebase_service=self.firebase,
            ticket=ticket,
            position=position,
            symbol_mt5_map=self.symbol_mt5_map,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade
        )

    def _capture_analysis(self, symbol: str, order_type: str, profit_usd: float = 0.0,
                           fixed_trade_size_usd: float = None, risk_per_trade: float = None) -> Dict[str, Any]:
        """Capture the M1/M5/H1 analyze_institutional_signal snapshot - used both
        right after opening a trade (analysis_at_open) and right before closing
        it (analysis_at_close), exactly like monitor_core.py does at close."""
        fixed_trade_size_usd = fixed_trade_size_usd or self.DEFAULT_FIXED_TRADE_SIZE_USD
        risk_per_trade = risk_per_trade or self.DEFAULT_RISK_PER_TRADE
        mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)

        result = {
            "m1": {}, "m5": {}, "h1": {},
            "profit_usd": profit_usd,
            "profit_percent": 0.0,
            "result": "WIN" if profit_usd > 0 else "LOSS"
        }

        print(f"📊 Capturing analysis for {symbol} - Profit: ${profit_usd:.2f}")

        for timeframe, key in (("M1", "m1"), ("M5", "m5"), ("H1", "h1")):
            try:
                tf_result = analyze_institutional_signal(
                    symbol=mt5_symbol,
                    order_type=order_type,
                    fixed_trade_size_usd=fixed_trade_size_usd,
                    risk_per_trade=risk_per_trade,
                    timeframe=timeframe,
                    debug=False
                )
                if tf_result.get("success", False):
                    result[key] = tf_result
                    print(f"   {timeframe}: Captured (Conf: {tf_result.get('⭐ CONFIDENCE', '0%')})")
            except Exception as e:
                print(f"   {timeframe}: Error - {e}")

        return result

    def _save_analysis_snapshot_to_firebase(self, ticket: int, symbol: str, order_type: str,
                                             analysis: Dict[str, Any], stage: str = "close"):
        """stage is 'open' or 'close' - stored as analysis_at_open / analysis_at_close,
        same field layout monitor_core.py uses for analysis_at_close."""
        if not self.firebase:
            return False
        try:
            profit_usd = analysis.get("profit_usd", 0.0)
            profit_percent = analysis.get("profit_percent", 0.0)
            result = analysis.get("result", "UNKNOWN")

            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "order_type": order_type,
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "result": result,
                "m1_analysis_raw": analysis.get("m1", {}),
                "m5_analysis_raw": analysis.get("m5", {}),
                "h1_analysis_raw": analysis.get("h1", {}),
                "⭐ CONFIDENCE": analysis.get("m1", {}).get("⭐ CONFIDENCE", "0%"),
                "🎯 FINAL_DECISION": analysis.get("m1", {}).get("🎯 FINAL_DECISION", "HOLD"),
                "💰 ENTRY": analysis.get("m1", {}).get("💰 ENTRY", 0),
                "🛑 STOP_LOSS": analysis.get("m1", {}).get("🛑 STOP_LOSS", 0),
                "🎯 TAKE_PROFIT_1": analysis.get("m1", {}).get("🎯 TAKE_PROFIT_1", 0),
                "🎯 TAKE_PROFIT_2": analysis.get("m1", {}).get("🎯 TAKE_PROFIT_2", 0),
                "🎯 TAKE_PROFIT_3": analysis.get("m1", {}).get("🎯 TAKE_PROFIT_3", 0),
                "📊 LOT_SIZE": analysis.get("m1", {}).get("📊 LOT_SIZE", 0),
                "💵 RISK_USD": analysis.get("m1", {}).get("💵 RISK_USD", 0),
                "📈 REWARD_USD": analysis.get("m1", {}).get("📈 REWARD_USD", 0),
                "💰 MARGIN_REQUIRED_USD": analysis.get("m1", {}).get("💰 MARGIN_REQUIRED_USD", 0),
                "🚀 SIMPLE_ACTION": analysis.get("m1", {}).get("🚀 SIMPLE_ACTION", "HOLD"),
                "🚀 REASON": analysis.get("m1", {}).get("🚀 REASON", ""),
                "📈 RISK_REWARD": analysis.get("m1", {}).get("📈 RISK_REWARD", "1:0"),
            }

            snapshot_safe = make_json_safe(snapshot)
            doc_id = f"trade_{ticket}"
            field = "analysis_at_open" if stage == "open" else "analysis_at_close"
            self.firebase._write_immediate("trades", doc_id, {field: snapshot_safe}, "update")

            print(f"✅ {field} saved for {symbol} (Ticket: {ticket}) - Profit: ${profit_usd:.2f}")
            return True
        except Exception as e:
            print(f"❌ Failed to save analysis snapshot: {e}")
            traceback.print_exc()
            return False

    def _save_trade_close_to_firebase(self, symbol: str, ticket: int, close_reason: str,
                                       profit: float, price_open: float, price_close: float,
                                       volume: float, sl: float, tp: float,
                                       is_webhook: bool = False,
                                       close_analysis: Dict[str, Any] = None,
                                       fixed_trade_size_usd: float = None,
                                       risk_per_trade: float = None):
        """
        ✅ Ported from monitor_core.py: saves analysis_at_close then the close data.
        """
        fixed_trade_size_usd = fixed_trade_size_usd or self.DEFAULT_FIXED_TRADE_SIZE_USD
        risk_per_trade = risk_per_trade or self.DEFAULT_RISK_PER_TRADE

        # ✅ CHECK IF ALREADY CLOSED IN FIREBASE
        if self.firebase:
            try:
                existing_trade = self.firebase.get_trade(str(ticket))
                if existing_trade:
                    existing_close = existing_trade.get("close_data", {})
                    if existing_close.get("close_price", 0) != 0:
                        print(f"⚠️ Trade {ticket} already closed in Firebase - skipping duplicate save")
                        return False
            except Exception as e:
                print(f"⚠️ Could not check Firebase: {e}")

        profit_percent = 0.0
        if price_open > 0 and volume > 0:
            # Real contract size, not the FX 100000 -- see core/broker_facts.
            size = _contract_size(self.symbol_mt5_map.get(symbol, symbol))
            notional = price_open * volume * size if size else 0
            profit_percent = (profit / notional) * 100 if notional else 0.0

        if close_analysis is None:
            # Looked up, not inferred. `"BUY" if price_close > price_open`
            # derives the direction from the OUTCOME, which is the same defect
            # fixed in monitor/firebase_helpers.py and monitor/monitor_core.py;
            # this was the third copy. It selects which side the close is
            # analysed from, so a loser was analysed from the wrong side.
            order_type = _direction_of_record(ticket) or "BUY"
            close_analysis = self._capture_analysis(symbol, order_type, profit,
                                                      fixed_trade_size_usd, risk_per_trade)
            close_analysis["profit_percent"] = profit_percent

        self._save_analysis_snapshot_to_firebase(
            ticket, symbol,
            _direction_of_record(ticket) or "BUY",
            close_analysis, stage="close"
        )

        result = save_trade_close_to_firebase(
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
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            is_webhook=is_webhook,
            close_analysis=close_analysis
        )

        if result:
            self._log_closed_trade(symbol, ticket, close_reason, profit, price_open,
                                    price_close, volume, sl, tp)

        return result

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
    # TRADE REGISTRATION - called by /trade/execute right after
    # execute_trade() succeeds (this replaces the auto-analysis
    # half of monitor_core.py's _execute_trade - the decision to
    # trade already happened upstream/via the caller, this just
    # records + saves it exactly like the monitor would).
    # ============================================================

    def register_trade_open(self, symbol: str, order_type: str, execution_result: Dict[str, Any],
                             fixed_trade_size_usd: float, risk_per_trade: float,
                             mt5_symbol: Optional[str] = None,
                             capture_analysis: bool = True) -> TradeResult:
        mt5_symbol = mt5_symbol or symbol
        with self._state_lock:
            self.symbol_mt5_map[symbol] = mt5_symbol

        success = execution_result.get("success", False)
        ticket = execution_result.get("ticket")
        price = execution_result.get("price")

        # ✅ FIX: analysis-at-open is captured in the BACKGROUND, not inline
        # here. This method used to call self._capture_analysis(...) - three
        # sequential analyze_institutional_signal() calls (M1/M5/H1) - right
        # here, synchronously, on the same Flask request thread, immediately
        # after execute_trade() returns and BEFORE the HTTP response was sent.
        # That's exactly the window where a tight break-even/trailing distance
        # needs MT5 responsive, and execution_controller.py never does any of
        # this extra work after execute_trade(). Moving it to a daemon thread
        # keeps registration (logging/caching/open-save) fast and lets the
        # response return immediately, same timing as execution_controller.py.
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
            full_analysis=None,
        )

        self._log_executed_trade(trade_result)

        if success and ticket:
            with self._state_lock:
                self.open_positions[symbol] = ticket
                self._position_data_cache[ticket] = {
                    "symbol": symbol,
                    "price_open": price,
                    "volume": execution_result.get("volume", 0),
                    "sl": execution_result.get("stop_loss"),
                    "tp": execution_result.get("take_profit"),
                    "tp2": execution_result.get("take_profit_2"),
                    "tp3": execution_result.get("take_profit_3"),
                    "order_type": order_type,
                    "magic": execution_result.get("magic"),
                    "entry_time": time.time(),
                    "risk_usd": execution_result.get("actual_risk_usd", 0),
                    "fixed_trade_size_usd": fixed_trade_size_usd,
                    "risk_per_trade": risk_per_trade,
                }
                self.stats["trades_registered"] += 1
            self._update_positions_log()
            print(f"💰 {symbol} opened at {price} (ticket {ticket}) - registered for copy-trade tracking")

            # Save the open trade to Firebase right away, WITHOUT analysis
            # (analysis_result={}) so this stays fast too - the M1/M5/H1
            # snapshot is merged in moments later by the background thread.
            self._save_trade_open_to_firebase(trade_result, {}, fixed_trade_size_usd, risk_per_trade)

            if capture_analysis:
                threading.Thread(
                    target=self._capture_and_save_open_analysis_async,
                    args=(ticket, symbol, order_type, fixed_trade_size_usd, risk_per_trade),
                    name=f"OpenAnalysis-{ticket}",
                    daemon=True
                ).start()
        else:
            error_msg = execution_result.get("error", "Unknown error")
            print(f"❌ Trade registration skipped for {symbol}: {error_msg}")

        return trade_result

    def _capture_and_save_open_analysis_async(self, ticket: int, symbol: str, order_type: str,
                                               fixed_trade_size_usd: float, risk_per_trade: float):
        """Runs off the request thread and off the trade-open critical path,
        so it never competes with a just-opened trade's break-even/trailing
        setup for MT5 access. Fire-and-forget - failures are logged, never
        raised back to the caller."""
        try:
            analysis_result = self._capture_analysis(
                symbol, order_type, 0.0, fixed_trade_size_usd, risk_per_trade
            )
            self._save_analysis_snapshot_to_firebase(ticket, symbol, order_type, analysis_result, stage="open")
            if self.firebase:
                try:
                    self.firebase._write_immediate(
                        "trades", f"trade_{ticket}",
                        {"analysis_data": make_json_safe(analysis_result)}, "update"
                    )
                except Exception as e:
                    print(f"⚠️ Could not merge analysis_data for ticket {ticket}: {e}")
        except Exception as e:
            print(f"⚠️ Background open-analysis capture failed for {symbol} (ticket {ticket}): {e}")

    # ============================================================
    # WEBHOOK HANDLERS (identical to monitor_core.py)
    # ============================================================

    def handle_webhook_close(self, symbol: str, ticket: int, close_reason: str,
                              profit: float, price_open: float, price_close: float,
                              volume: float, sl: float, tp: float, close_time: str):
        """✅ Ported from monitor_core.py: handle webhook order closure with correct profit."""
        print("=" * 80)
        print(f"📨 WEBHOOK CLOSE: {symbol} (Ticket: {ticket}) - {close_reason}")
        print(f"   Profit: ${profit:.2f} | Open: {price_open} | Close: {price_close}")
        print(f"   Volume: {volume} | SL: {sl} | TP: {tp}")
        print("=" * 80)

        self.stats["webhook_closes"] = self.stats.get("webhook_closes", 0) + 1

        cached = self._position_data_cache.get(ticket, {})
        fixed_trade_size_usd = cached.get("fixed_trade_size_usd", self.DEFAULT_FIXED_TRADE_SIZE_USD)
        risk_per_trade = cached.get("risk_per_trade", self.DEFAULT_RISK_PER_TRADE)

        # Direction of record; the cache still holds it for an open position.
        order_type = (_normalise_direction(cached.get("order_type"))
                      or _direction_of_record(ticket) or "BUY")
        close_analysis = self._capture_analysis(symbol, order_type, profit, fixed_trade_size_usd, risk_per_trade)

        result = self._save_trade_close_to_firebase(
            symbol=symbol, ticket=ticket, close_reason=close_reason, profit=profit,
            price_open=price_open, price_close=price_close, volume=volume, sl=sl, tp=tp,
            is_webhook=True, close_analysis=close_analysis,
            fixed_trade_size_usd=fixed_trade_size_usd, risk_per_trade=risk_per_trade
        )

        if result:
            with self._state_lock:
                self._webhook_closed_tickets.add(ticket)
                if symbol in self.open_positions and self.open_positions[symbol] == ticket:
                    del self.open_positions[symbol]
                if ticket in self._position_data_cache:
                    del self._position_data_cache[ticket]
                self.stats["trades_closed"] = self.stats.get("trades_closed", 0) + 1

            self._update_positions_log()
            print(f"✅ Webhook close processed successfully for {symbol} (Profit: ${profit:.2f})")
        else:
            print(f"❌ Webhook close failed for {symbol}")

        return result

    def handle_trailing_webhook(self, data: Dict[str, Any]):
        """✅ Ported from monitor_core.py: handle trailing stop webhook using firebase_helpers."""
        print(f"📨 TRAILING WEBHOOK: {data}")
        return process_trailing_webhook(
            firebase_service=self.firebase,
            monitor=self,
            data=data
        )

    def handle_webhook_modify(self, symbol: str, ticket: int, sl: float, tp: float,
                               profit: float = 0.0, price_current: float = 0.0,
                               timestamp: str = None):
        """
        Handles the EA's "MODIFY" event (TradeWebhook.mq5's SendWebhookModify) -
        a live SL/TP change on an open position (break-even trigger, manual
        adjustment, trailing step, etc). Not a close, so it doesn't touch
        Firebase close_data - it just keeps our local cache fresh so that if
        the position later closes (via the position-monitor loop's SL/TP-hit
        fallback path), the profit/close calculation uses the latest SL/TP
        instead of whatever was cached at trade-open.
        """
        print(f"📨 WEBHOOK MODIFY: {symbol} (Ticket: {ticket}) SL={sl} TP={tp} Profit=${profit:.2f}")
        with self._state_lock:
            if ticket in self._position_data_cache:
                self._position_data_cache[ticket]['sl'] = sl
                self._position_data_cache[ticket]['tp'] = tp
        return True

    # ============================================================
    # POSITION MONITOR LOOP - detects SL/TP hits with correct profit
    # (identical detection logic to monitor_core.py)
    # ============================================================

    def _position_monitor_loop(self):
        checked_tickets = set()

        while not self.stop_event.is_set():
            try:
                with self._state_lock:
                    symbols_to_check = list(self.open_positions.keys())

                for symbol in symbols_to_check:
                    ticket = None
                    try:
                        ticket = self.open_positions.get(symbol)
                        if not ticket:
                            continue

                        if ticket in checked_tickets:
                            continue

                        with self._state_lock:
                            if ticket in self._webhook_closed_tickets:
                                print(f"✅ {symbol} (ticket: {ticket}) already closed via webhook")
                                self._cleanup_closed_position(symbol, ticket)
                                checked_tickets.add(ticket)
                                continue

                        position = get_position_details(ticket)

                        if not position:
                            # ✅ POSITION CLOSED IN MT5 (SL/TP HIT)
                            print(f"📉 {symbol} closed (ticket: {ticket}) - SL/TP HIT detected")

                            # try/finally: the cache delete and _cleanup_closed_position()
                            # below MUST run even if reconstructing the close data raises.
                            # They used to sit on the happy path, so one exception left the
                            # ticket in _position_data_cache, the next loop re-detected the
                            # same close, and it span forever at ~1 error per 2s -- never
                            # saving the trade. A close that cannot be reconstructed is a
                            # lost record; a close that cannot be cleaned up is a lost
                            # monitor.
                            try:
                                already_closed = False
                                if self.firebase:
                                    try:
                                        existing_trade = self.firebase.get_trade(str(ticket))
                                        if existing_trade:
                                            existing_close = existing_trade.get("close_data", {})
                                            if existing_close.get("close_price", 0) != 0:
                                                print(f"   ✅ Trade {ticket} already closed in Firebase")
                                                already_closed = True
                                    except Exception as e:
                                        print(f"⚠️ Could not check Firebase: {e}")

                                if not already_closed:
                                    cached = self._position_data_cache.get(ticket, {})
                                    profit = 0.0
                                    # _num, not .get(key, 0): the cache stores
                                    # execution_result.get("take_profit") with no default, so
                                    # the key is ALWAYS present and holds None on a trade
                                    # opened without a TP -- which is the documented normal
                                    # case ("optional - only set if provided"). .get(k, 0)
                                    # returns the default only when the key is MISSING, so it
                                    # handed None straight to `tp > 0` and raised
                                    # "'>' not supported between NoneType and int" on every
                                    # such close.
                                    price_open = _num(cached.get("price_open"))
                                    price_close = 0.0
                                    volume = _num(cached.get("volume"))
                                    sl = _num(cached.get("sl"))
                                    tp = _num(cached.get("tp"))
                                    order_type = cached.get("order_type") or "BUY"
                                    fixed_trade_size_usd = cached.get("fixed_trade_size_usd", self.DEFAULT_FIXED_TRADE_SIZE_USD)
                                    risk_per_trade = cached.get("risk_per_trade", self.DEFAULT_RISK_PER_TRADE)

                                    # Try to get from trade history (most accurate)
                                    try:
                                        history = get_trade_history(last_n_days=1)
                                        if history.get("success", False):
                                            for trade in history.get("trades", []):
                                                if trade.get("entry_ticket") == ticket:
                                                    # Same None hazard as the cache above:
                                                    # a history row can carry a null SL/TP.
                                                    profit = _num(trade.get("net_profit"))
                                                    if not price_open:
                                                        price_open = _num(trade.get("entry_price"))
                                                    price_close = _num(trade.get("exit_price"))
                                                    if not volume:
                                                        volume = _num(trade.get("volume"))
                                                    if not sl:
                                                        sl = _num(trade.get("entry_sl"))
                                                    if not tp:
                                                        tp = _num(trade.get("entry_tp"))
                                                    print(f"   📊 Trade history: profit=${profit:.2f}, close={price_close}")
                                                    break
                                    except Exception as e:
                                        print(f"⚠️ Could not get trade history: {e}")

                                    # Ask the broker how it actually closed.
                                    #
                                    # This replaces an estimate that assumed the
                                    # trade closed AT ITS STOP whenever the history
                                    # lookup missed -- which it routinely does in the
                                    # moment right after a close, and which is simply
                                    # false for a manual or webhook close. Observed:
                                    # a gold SELL closed at 4391.10 for +$4.77 was
                                    # stored at 4392.07 (its stop) for -$3960.
                                    if price_close == 0 or profit == 0:
                                        deal = _closing_deal(ticket)
                                        if deal:
                                            price_close = deal["price_close"]
                                            profit = deal["profit"]
                                            if not volume:
                                                volume = deal["volume"]
                                            print(f"   📒 Broker deal: close={price_close}, "
                                                  f"profit=${profit:.2f}")

                                    # Last resort, and only with the REAL contract
                                    # size. The old code multiplied by a hardcoded
                                    # 100000 (the FX convention) for every symbol,
                                    # which is 1000x wrong on gold's 100-ounce
                                    # contract. If the size is unknown, leave the
                                    # profit alone rather than scale it by a guess.
                                    if profit == 0 and price_open > 0 and price_close > 0 and volume > 0:
                                        mt5_symbol = self.symbol_mt5_map.get(symbol, symbol)
                                        size = _contract_size(mt5_symbol)
                                        if size:
                                            move = (price_close - price_open) if order_type == "BUY" \
                                                else (price_open - price_close)
                                            profit = move * volume * size
                                            print(f"   💰 Calculated profit: ${profit:.2f} "
                                                  f"(contract size {size})")
                                        else:
                                            print(f"   ⚠️ No contract size for {mt5_symbol} - "
                                                  f"leaving profit unset rather than guessing")

                                    if price_open != 0 and price_close != 0 and volume != 0:
                                        print(f"   💾 Saving SL/TP close for {symbol} - Profit: ${profit:.2f}")
                                        self._save_trade_close_to_firebase(
                                            symbol=symbol, ticket=ticket, close_reason="SL_TP_HIT",
                                            profit=profit, price_open=price_open, price_close=price_close,
                                            volume=volume, sl=sl, tp=tp, is_webhook=False,
                                            fixed_trade_size_usd=fixed_trade_size_usd, risk_per_trade=risk_per_trade
                                        )
                                    else:
                                        print(f"   ⚠️ Incomplete close data for {symbol}")

                            finally:
                                with self._state_lock:
                                    self._position_data_cache.pop(ticket, None)
                                self._cleanup_closed_position(symbol, ticket)
                                checked_tickets.add(ticket)

                        else:
                            # Position still open - update price evolution
                            cached = self._position_data_cache.get(ticket, {})
                            self._update_trade_price_in_firebase(
                                ticket, position,
                                cached.get("fixed_trade_size_usd", self.DEFAULT_FIXED_TRADE_SIZE_USD),
                                cached.get("risk_per_trade", self.DEFAULT_RISK_PER_TRADE)
                            )

                    except Exception as e:
                        self.stats["monitor_errors"] = self.stats.get("monitor_errors", 0) + 1
                        print(f"⚠️ Position monitor error for {symbol} (ticket: {ticket}): {e}")

                if len(checked_tickets) > 1000:
                    checked_tickets = set(list(checked_tickets)[-500:])

                time.sleep(2)

            except Exception as e:
                print(f"⚠️ Position monitor loop error: {e}")
                time.sleep(5)

    def _cleanup_closed_position(self, symbol: str, ticket: int):
        """✅ Helper: Clean up a closed position from local state."""
        with self._state_lock:
            if symbol in self.open_positions and self.open_positions[symbol] == ticket:
                del self.open_positions[symbol]
                self.stats["trades_closed"] = self.stats.get("trades_closed", 0) + 1

        self._update_positions_log()
        print(f"✅ Cleaned up closed position: {symbol} (ticket: {ticket})")

    # ============================================================
    # HEALTH MONITOR (lightweight version of monitor_core.py's)
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
            open_count = len(self.open_positions)
            registered = self.stats.get("trades_registered", 0)
            closed = self.stats.get("trades_closed", 0)
            firebase_saves = self.stats.get("firebase_saves", 0)
            webhook_closes = self.stats.get("webhook_closes", 0)
            price_updates = self.stats.get("price_updates", 0)
            cache_size = len(self._position_data_cache)

        print(f"{'='*80}")
        print(f"🏥 COPY-TRADE HEALTH - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        print(f"   🟢 Running: {self.running}")
        print(f"   📈 Open Tracked Positions: {open_count}")
        print(f"   ✅ Registered: {registered} | Closed: {closed}")
        print(f"   🔥 Firebase Saves: {firebase_saves}")
        print(f"   📨 Webhook Closes: {webhook_closes}")
        print(f"   📈 Price Updates: {price_updates}")
        print(f"   📦 Position Cache: {cache_size}")
        print(f"{'='*80}")

    # ============================================================
    # LIFECYCLE
    # ============================================================

    def start(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        with self._state_lock:
            self.stats["start_time"] = datetime.now().isoformat()

        self.position_monitor_thread = threading.Thread(
            target=self._position_monitor_loop, name="CopyTradePositionMonitor", daemon=True
        )
        self.position_monitor_thread.start()

        self.health_thread = threading.Thread(
            target=self._health_monitor_loop, name="CopyTradeHealthMonitor", daemon=True
        )
        self.health_thread.start()

        print("✅ CopyTradeManager running - position monitor & health threads started")

    def stop(self):
        if not self.running:
            return
        print("Stopping CopyTradeManager...")
        self.stop_event.set()
        self.running = False
        for thread in [self.position_monitor_thread, self.health_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)
        self._update_positions_log()
        print("✅ CopyTradeManager stopped")

    def get_status(self) -> Dict[str, Any]:
        # ✅ FIX: this used to report "firebase_connected": self.firebase is
        # not None - which is ALWAYS True, because _get_firebase() always
        # returns a FirebaseService object even when it's running fully
        # offline (no credentials found - see firebase_service.py's
        # _init_firebase). That gave a false "connected" reading no matter
        # what. Report real health via is_healthy() plus the service's own
        # queue/error counters, so an offline/broken Firebase is actually
        # visible here instead of silently reading as fine.
        firebase_status = None
        firebase_healthy = False
        if self.firebase is not None:
            try:
                firebase_healthy = self.firebase.is_healthy()
                firebase_status = self.firebase.get_status()
            except Exception as e:
                firebase_status = {"error": str(e)}

        with self._state_lock:
            return {
                "running": self.running,
                "open_tracked_positions": len(self.open_positions),
                "open_positions": dict(self.open_positions),
                "stats": self.stats,
                "webhook_closed_tickets": len(self._webhook_closed_tickets),
                "position_cache_size": len(self._position_data_cache),
                "price_update_interval": self.PRICE_UPDATE_INTERVAL,
                "firebase_connected": firebase_healthy,
                "firebase_status": firebase_status,
            }


# ✅ Single shared instance - the position monitor / health threads
# are started from create_app() / __main__ via copy_trade_manager.start()
copy_trade_manager = CopyTradeManager()


def handle_trading_exception(e: TradingException):
    error_response = {'success': False, 'error_code': e.error_code, 'error_message': e.message,
                      'details': e.details, 'timestamp': datetime.now().isoformat()}
    if e.error_code in [ErrorCode.SYMBOL_NOT_FOUND, ErrorCode.POSITION_NOT_FOUND]:
        return jsonify(error_response), 404
    elif e.error_code in [ErrorCode.SYMBOL_LOCKED, ErrorCode.MAX_TRADES_REACHED, 
                          ErrorCode.MAX_TRADES_PER_SYMBOL_REACHED, ErrorCode.SPREAD_TOO_HIGH]:
        return jsonify(error_response), 429
    elif e.error_code in [ErrorCode.TRADE_FAILED, ErrorCode.CLOSE_POSITION_FAILED,
                          ErrorCode.MODIFY_SL_FAILED, ErrorCode.MODIFY_TP_FAILED]:
        return jsonify(error_response), 400
    else:
        return jsonify(error_response), 500


# ============================================================
# HEALTH & CONNECTION ENDPOINTS
# ============================================================

@api_bp.route('/health', methods=['GET'])
def health_check():
    global mt5_connected
    try:
        mt5_connected = mt5.terminal_info() is not None
        return jsonify({'status': 'operational', 'mt5_connected': mt5_connected,
                        'timestamp': datetime.now().isoformat()}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@api_bp.route('/mt5/connect', methods=['POST'])
def api_connect_mt5():
    global mt5_connected
    try:
        data = request.get_json()
        required_fields = ['login', 'password', 'server']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        login = data['login']
        password = data['password']
        server = data['server']
        path = data.get('path', '')
        
        shutdown_mt5()
        
        if path:
            initialized = mt5.initialize(path=path)
        else:
            initialized = mt5.initialize()
        
        if not initialized:
            return jsonify({'success': False, 'error': f'MT5 init failed: {mt5.last_error()}'}), 500
        
        authorized = mt5.login(login, password=password, server=server)
        
        if not authorized:
            mt5.shutdown()
            return jsonify({'success': False, 'error': f'Login failed: {mt5.last_error()}'}), 401
        
        mt5_connected = True
        account_info = mt5.account_info()
        
        return jsonify({'success': True, 'message': 'Connected to MT5',
                        'account': {'login': account_info.login, 'balance': account_info.balance,
                                    'equity': account_info.equity, 'currency': account_info.currency}}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/mt5/disconnect', methods=['POST'])
def api_disconnect_mt5():
    global mt5_connected
    shutdown_mt5()
    mt5_connected = False
    return jsonify({'success': True, 'message': 'Disconnected from MT5'}), 200


# ============================================================
# MARKET STATUS ENDPOINTS
# ============================================================

@api_bp.route('/market/status/<string:symbol>', methods=['GET'])
def api_market_status(symbol):
    try:
        result = is_market_closed(symbol.upper())
        return jsonify(result), 200 if result.get('success') else 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/market/volatility/<string:symbol>', methods=['GET'])
def api_market_volatility(symbol):
    try:
        lookback_period = request.args.get('lookback', 20, type=int)
        result = check_volatility(symbol.upper(), lookback_period)
        return jsonify(result), 200 if result.get('success') else 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/market/spread/<string:symbol>', methods=['GET'])
def api_market_spread(symbol):
    try:
        max_spread_pips = request.args.get('max_spread', 30, type=float)
        result = check_spread_status(symbol.upper(), max_spread_pips)
        return jsonify(result), 200 if result.get('success') else 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# ✅ WEBHOOK ENDPOINTS - PORTED FROM MONITOR (same handlers,
# same Firebase save pipeline, just routed through copy_trade_manager)
# ============================================================

@api_bp.route('/webhook/close', methods=['POST'])
def api_webhook_close():
    """
    Broker/EA webhook fired when a copy-trade position closes (SL/TP hit,
    manual close on the terminal, etc). Mirrors monitor_core.py's
    handle_webhook_close - saves analysis_at_close + close_data to
    Firebase and updates local tracking, thread-safely.

    Request body:
    {
        "symbol": "EURUSD", "ticket": 123456, "close_reason": "SL_HIT",
        "profit": -12.34, "price_open": 1.0921, "price_close": 1.0905,
        "volume": 0.10, "sl": 1.0905, "tp": 1.0965,
        "close_time": "2026-08-14T10:15:00Z"
    }
    """
    try:
        data = request.get_json() or {}
        required_fields = ['symbol', 'ticket', 'close_reason', 'profit',
                            'price_open', 'price_close', 'volume']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400

        result = copy_trade_manager.handle_webhook_close(
            symbol=data['symbol'].upper(),
            ticket=int(data['ticket']),
            close_reason=data['close_reason'],
            profit=float(data['profit']),
            price_open=float(data['price_open']),
            price_close=float(data['price_close']),
            volume=float(data['volume']),
            sl=float(data.get('sl', 0) or 0),
            tp=float(data.get('tp', 0) or 0),
            close_time=data.get('close_time', datetime.now().isoformat())
        )
        return jsonify({'success': bool(result), 'data': {'ticket': data['ticket']}}), 200 if result else 400
    except Exception as e:
        logger.error(f"Webhook close error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/webhook/trailing', methods=['POST'])
def api_webhook_trailing():
    """Broker/EA webhook fired on a trailing-stop update. Mirrors
    monitor_core.py's handle_trailing_webhook - delegates to firebase_helpers."""
    try:
        data = request.get_json() or {}
        result = copy_trade_manager.handle_trailing_webhook(data)
        return jsonify({'success': bool(result), 'data': result if isinstance(result, dict) else {}}), 200
    except Exception as e:
        logger.error(f"Trailing webhook error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/webhook/trade', methods=['POST'])
def api_webhook_trade():
    """
    ✅ Combined webhook - matches TradeWebhook.mq5's SendHTTPRequest contract
    exactly (the same URL the EA already posts to for the monitor). The EA
    sends one JSON shape per event, dispatched by "event":

    CLOSE (from SendWebhookClose):
    {
        "event": "CLOSE", "close_reason": "STOP_LOSS", "symbol": "EURUSD",
        "ticket": 123456, "volume": 0.10, "price_open": 1.0921,
        "price_close": 1.0905, "profit": -12.34, "sl": 1.0905, "tp": 1.0965,
        "time": "2026.08.14 10:15:00"
    }

    MODIFY (from SendWebhookModify):
    {
        "event": "MODIFY", "symbol": "EURUSD", "ticket": 123456,
        "sl": 1.0910, "tp": 1.0965, "profit": 3.20,
        "price_current": 1.0918, "time": "2026.08.14 10:14:12"
    }

    Point the EA's second webhook input at this same path
    (http://<host>:5003/api/v1/webhook/trade) to mirror everything it
    already sends to the monitor.
    """
    try:
        data = request.get_json() or {}
        event = (data.get('event') or '').upper()

        if event == 'CLOSE':
            required_fields = ['symbol', 'ticket', 'close_reason', 'profit',
                                'price_open', 'price_close', 'volume']
            for field in required_fields:
                if field not in data:
                    return jsonify({'success': False, 'error': f'Missing {field}'}), 400

            result = copy_trade_manager.handle_webhook_close(
                symbol=data['symbol'].upper(),
                ticket=int(data['ticket']),
                close_reason=data['close_reason'],
                profit=float(data['profit']),
                price_open=float(data['price_open']),
                price_close=float(data['price_close']),
                volume=float(data['volume']),
                sl=float(data.get('sl', 0) or 0),
                tp=float(data.get('tp', 0) or 0),
                # the EA sends "time", not "close_time" - accept either
                close_time=data.get('close_time') or data.get('time') or datetime.now().isoformat()
            )
            return jsonify({'success': bool(result), 'data': {'ticket': data['ticket'], 'event': 'CLOSE'}}), 200 if result else 400

        elif event == 'MODIFY':
            for field in ['symbol', 'ticket']:
                if field not in data:
                    return jsonify({'success': False, 'error': f'Missing {field}'}), 400

            result = copy_trade_manager.handle_webhook_modify(
                symbol=data['symbol'].upper(),
                ticket=int(data['ticket']),
                sl=float(data.get('sl', 0) or 0),
                tp=float(data.get('tp', 0) or 0),
                profit=float(data.get('profit', 0) or 0),
                price_current=float(data.get('price_current', 0) or 0),
                timestamp=data.get('time')
            )
            return jsonify({'success': bool(result), 'data': {'ticket': data['ticket'], 'event': 'MODIFY'}}), 200

        else:
            return jsonify({'success': False, 'error': f"Unknown or missing 'event' (got: {data.get('event')!r})"}), 400

    except Exception as e:
        logger.error(f"Webhook trade error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/copy-trade/status', methods=['GET'])
def api_copy_trade_status():
    """Status of the copy-trade manager - tracked positions, Firebase
    connectivity, background thread state, and running stats."""
    try:
        return jsonify({'success': True, 'data': copy_trade_manager.get_status()}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# TRADE EXECUTION ENDPOINT - FOLLOWS EXACT SAME PATTERN AS COPY TRADE
# ============================================================

@api_bp.route('/trade/execute', methods=['POST'])
def api_execute_trade():
    """
    Execute a trade - AUTO-CALCULATES SL from risk_per_trade.
    TP is OPTIONAL - only set if provided in request.
    
    Request Body:
    {
        "symbol": "EURUSD",                     # Required
        "order_type": "BUY",                    # Required: BUY or SELL
        "strategy_magic": 1001,                 # Required
        "fixed_trade_size_usd": 200,            # Required
        "risk_per_trade": 0.05,                 # Required: 0.05 = 5% risk
        "max_spread": 30,                       # Required
        "trade_deviation": 20,                  # Optional, default 20
        "max_trades_per_symbol": 1,             # Optional, default 1
        "max_simultaneous_trades": 5,           # Optional, default 5
        "comment": "AI Trade",                  # Optional
        "stop_loss_price": 1.12245,             # Optional - if not provided, auto-calculated
        "take_profit_price": 1.12545,           # Optional - if not provided, NOT SET
        "take_profit_2_price": 1.12645,         # Optional - partial close level 2
        "take_profit_3_price": 1.12745,         # Optional - partial close level 3
        "min_stop_pips_override": 10,           # Optional
        "enable_trailing_stop": false,          # Optional, default false
        "trailing_pips": 5.0                    # Optional, default 5.0
    }
    """
    try:
        data = request.get_json()
        
        # ============================================================
        # VALIDATE REQUIRED FIELDS
        # ============================================================
        
        required_fields = ['symbol', 'order_type', 'strategy_magic', 
                          'fixed_trade_size_usd', 'risk_per_trade', 'max_spread']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        symbol = data['symbol'].upper()
        order_type = data['order_type'].upper()
        strategy_magic = int(data['strategy_magic'])
        fixed_trade_size_usd = float(data['fixed_trade_size_usd'])
        risk_per_trade = float(data['risk_per_trade'])
        max_spread = float(data['max_spread'])
        trade_deviation = int(data.get('trade_deviation', 20))
        max_trades_per_symbol = int(data.get('max_trades_per_symbol', 1))
        max_simultaneous_trades = int(data.get('max_simultaneous_trades', 5))
        min_stop_pips_override = data.get('min_stop_pips_override')
        comment = data.get('comment', 'AI Trade')
        
        # SL - Optional, if not provided auto-calculated from risk_per_trade
        stop_loss_price = None
        if data.get('stop_loss_price') is not None:
            stop_loss_price = float(data['stop_loss_price'])
        
        # TP - Optional, only set if provided
        take_profit_price = None
        if data.get('take_profit_price') is not None:
            take_profit_price = float(data['take_profit_price'])
        
        # ✅ TP2 / TP3 are now real, applied levels - MT5's native TP only
        # supports one level, so execute_trade() splits the position and
        # partially closes it as each level is hit (see core/execution.py).
        take_profit_2_price = None
        if data.get('take_profit_2_price') is not None:
            take_profit_2_price = float(data['take_profit_2_price'])
        
        take_profit_3_price = None
        if data.get('take_profit_3_price') is not None:
            take_profit_3_price = float(data['take_profit_3_price'])
        
        # Trailing stop
        enable_break_even = bool(data.get('enable_break_even', False))
        break_even_pips_distance = (float(data['break_even_pips_distance']) if data.get('break_even_pips_distance') is not None else None)
        break_even_usd_distance = (float(data['break_even_usd_distance']) if data.get('break_even_usd_distance') is not None else None)
        enable_trailing_stop = bool(data.get('enable_trailing_stop', False))
        trailing_pips = (float(data['trailing_pips']) if data.get('trailing_pips') is not None else None)
        trailing_usd_distance = (float(data['trailing_usd_distance']) if data.get('trailing_usd_distance') is not None else None)
        
        # ============================================================
        # EXECUTE TRADE - SAME AS COPY TRADE
        # ============================================================
        
        result = execute_trade(
            symbol=symbol,
            order_type=order_type,
            strategy_magic=strategy_magic,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            max_spread=max_spread,
            trade_deviation=trade_deviation,
            max_trades_per_symbol=max_trades_per_symbol,
            max_simultaneous_trades=max_simultaneous_trades,
            min_stop_pips_override=min_stop_pips_override,
            comment=comment,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            take_profit_2_price=take_profit_2_price,
            take_profit_3_price=take_profit_3_price,
            enable_break_even=enable_break_even,
            break_even_pips_distance=break_even_pips_distance,
            break_even_usd_distance=break_even_usd_distance,
            enable_trailing_stop=enable_trailing_stop,
            trailing_pips=trailing_pips,
            trailing_usd_distance=trailing_usd_distance
        )

        # ============================================================
        # ✅ FIX: ACTUALLY ACTIVATE BREAK-EVEN / TRAILING MONITORING
        # ------------------------------------------------------------
        # execute_trade() only ECHOES enable_break_even/enable_trailing_stop
        # back in its response - it does NOT register the ticket into
        # _active_trails or start the monitor thread. The only code in
        # this whole service that does that lives in the two dedicated
        # endpoints below (/position/break-even/enable/<ticket> and
        # /position/trailing/enable/<ticket>). Without this, a trade
        # opened here with enable_break_even/enable_trailing_stop=true
        # never actually gets monitored - confirmed live: execute
        # responds with "enabled": true, but the very next GET positions
        # call shows has_break_even/has_trailing_stop = false.
        # So: replicate that exact same registration here, using the
        # trade's own ticket/symbol/SL, right after a successful execute.
        # ============================================================
        ticket = result.get('ticket') if isinstance(result, dict) else None
        if result.get('success') and ticket and (enable_break_even or enable_trailing_stop):
            try:
                from core.execution import _active_trails, start_trailing_monitor
                config = _active_trails.get(ticket, {})
                config['symbol'] = symbol
                config.setdefault('created_at', time.time())
                if enable_break_even:
                    config['break_even_enabled'] = True
                    config['break_even_pips_distance'] = break_even_pips_distance
                    config['break_even_usd_distance'] = break_even_usd_distance
                if enable_trailing_stop:
                    config['trailing_enabled'] = True
                    config['pips_distance'] = trailing_pips
                    config['usd_distance'] = trailing_usd_distance
                    config['step_pips'] = trailing_pips
                    config['last_sl'] = result.get('stop_loss')
                _active_trails[ticket] = config
                start_trailing_monitor()
                logger.info(f"✅ Break-even/trailing activated for ticket {ticket} at trade execution")
            except Exception as e:
                logger.error(f"⚠️ Failed to activate break-even/trailing for ticket {ticket}: {e}")

        # ============================================================
        # ✅ REGISTER WITH COPY-TRADE MANAGER
        # Ported from monitor_core.py's _execute_trade: log the
        # execution, cache it for the position monitor, and save
        # open-trade + analysis-at-open to Firebase - same pipeline
        # the monitor uses for its own trades.
        # ============================================================
        try:
            copy_trade_manager.register_trade_open(
                symbol=symbol,
                order_type=order_type,
                execution_result=result,
                fixed_trade_size_usd=fixed_trade_size_usd,
                risk_per_trade=risk_per_trade,
                capture_analysis=bool(data.get('capture_analysis', True))
            )
        except Exception as e:
            logger.error(f"⚠️ copy_trade_manager.register_trade_open failed: {e}")
        
        return jsonify({
            'success': True,
            'data': result,
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# TRADE SIGNAL ANALYSIS ENDPOINT
# ============================================================

@api_bp.route('/trade/analyse', methods=['POST'])
def api_hedge_fund_signal():
    """
    ULTIMATE HEDGE FUND TRADING SIGNAL
    
    Returns 17-component analysis with:
    - Per-component anti-cheat validation
    - Entry timing for each component
    - Drawable trend lines, Fibonacci, S/R zones
    - Take profit suggestions
    - 5-star hedge fund rating
    - Final verdict with execution timing
    """
    try:
        data = request.get_json()
        
        required_fields = ['symbol', 'order_type', 'fixed_trade_size_usd', 'risk_per_trade']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        result = analyze_institutional_signal(
            symbol=data['symbol'].upper(),
            order_type=data['order_type'].upper(),
            fixed_trade_size_usd=float(data['fixed_trade_size_usd']),
            risk_per_trade=float(data['risk_per_trade']),
            timeframe=data.get('timeframe', 'M1'),
            stop_loss_pips=data.get('stop_loss_pips'),
            take_profit_pips=data.get('take_profit_pips')
        )
        
        if not result.get('success'):
            return jsonify({'success': False, 'error': result.get('error')}), 400
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# PROBABILITY CALCULATION ENDPOINT
# ============================================================

@api_bp.route('/trade/probability', methods=['POST'])
def api_calculate_probability():
    try:
        data = request.get_json()
        required_fields = ['symbol', 'entry_price', 'stop_loss', 'take_profit', 'order_type']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        probability = calculate_probability_of_hit(
            symbol=data['symbol'].upper(),
            entry_price=float(data['entry_price']),
            stop_loss=float(data['stop_loss']),
            take_profit=float(data['take_profit']),
            order_type=data['order_type'].upper()
        )
        
        return jsonify({
            'success': True,
            'probability_percent': round(probability * 100, 2),
            'probability_decimal': probability,
            'symbol': data['symbol'].upper(),
            'recommendation': 'HIGH_PROBABILITY' if probability > 0.65 else 
                             'MEDIUM_PROBABILITY' if probability > 0.45 else 
                             'LOW_PROBABILITY'
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# MARKET CONDITIONS ENDPOINT
# ============================================================

@api_bp.route('/market/conditions/<string:symbol>', methods=['GET'])
def api_get_market_conditions(symbol):
    try:
        spread = get_current_spread(symbol.upper())
        trend_strength = calculate_trend_strength(symbol.upper())
        atr = get_atr_value(symbol.upper())
        
        tick = mt5.symbol_info_tick(symbol.upper())
        info = mt5.symbol_info(symbol.upper())
        
        current_price = tick.ask if tick else 0
        volatility_percent = (atr / current_price * 100) if current_price > 0 else 0
        
        point = info.point if info else 0.00001
        pip_size = point * (10 if info.digits in [3, 5] else 1) if info else 0.0001
        atr_pips = atr / pip_size if pip_size > 0 else 0
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'current_price': current_price,
            'metrics': {
                'spread_pips': {
                    'value': round(spread, 1),
                    'explanation': 'Current spread in pips. Lower is better. >15 pips will trigger AVOID.',
                    'interpretation': 'Excellent' if spread <= 8 else 'Normal' if spread <= 15 else 'High - Will cause AVOID'
                },
                'atr_pips': {
                    'value': round(atr_pips, 1),
                    'explanation': 'Average True Range in pips. Measures average price movement.',
                    'interpretation': f'Price moves approximately {round(atr_pips, 1)} pips on average per bar'
                },
                'trend_strength': {
                    'value': round(trend_strength, 3),
                    'explanation': '0-1 scale. Higher = stronger trend.',
                    'interpretation': 'Ranging Market' if trend_strength < 0.3 else 'Weak Trend' if trend_strength < 0.6 else 'Strong Trend'
                },
                'volatility_percent': {
                    'value': round(volatility_percent, 2),
                    'explanation': 'Percentage of price movement. Higher = more risk.',
                    'interpretation': 'Low Volatility' if volatility_percent < 0.5 else 'Normal Volatility' if volatility_percent < 1.5 else 'High Volatility'
                }
            },
            'trading_recommendation': {
                'action': 'CAUTIOUS' if spread > 15 else 'NORMAL',
                'minimum_required_rr': '1:2',
                'minimum_required_probability': '75%',
                'suggested_stop_pips': max(round(atr_pips * 1.5, 1), spread * 2),
                'suggested_take_profit_pips': max(round(atr_pips * 2.5, 1), spread * 4),
                'suggested_trailing_stop': {
                    'enabled': True,
                    'step_pips': max(round(atr_pips * 0.3, 1), 3)
                }
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# POSITION MANAGEMENT ENDPOINTS
# ============================================================

@api_bp.route('/position/close/<int:ticket>', methods=['POST'])
def api_close_position(ticket):
    try:
        data = request.get_json() or {}
        deviation = data.get('deviation', 20)
        result = close_position(ticket, deviation)
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/partial-close/<int:ticket>', methods=['PUT'])
def api_partial_close_position(ticket):
    try:
        data = request.get_json()
        if not data or 'volume_to_close' not in data:
            return jsonify({'success': False, 'error': 'Missing volume_to_close'}), 400
        volume_to_close = float(data['volume_to_close'])
        deviation = data.get('deviation', 20)
        result = partial_close_position(ticket, volume_to_close, deviation)
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/positions/close/all', methods=['POST'])
def api_close_all_positions():
    try:
        data = request.get_json() or {}
        symbol = data.get('symbol')
        deviation = data.get('deviation', 20)
        result = close_all_positions(symbol, deviation)
        return jsonify({'success': result['success'], 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/<int:ticket>/stop-loss', methods=['PUT'])
def api_modify_stop_loss(ticket):
    try:
        data = request.get_json()
        if not data or 'sl_price' not in data:
            return jsonify({'success': False, 'error': 'Missing sl_price'}), 400
        sl_price = float(data['sl_price'])
        result = modify_stop_loss(ticket, sl_price)
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/<int:ticket>/take-profit', methods=['PUT'])
def api_modify_take_profit(ticket):
    try:
        data = request.get_json()
        if not data or 'tp_price' not in data:
            return jsonify({'success': False, 'error': 'Missing tp_price'}), 400
        tp_price = float(data['tp_price'])
        result = modify_take_profit(ticket, tp_price)
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# BREAK-EVEN ENDPOINTS (INDEPENDENT FROM TRAILING)
# ============================================================

@api_bp.route('/position/break-even/enable/<int:ticket>', methods=['PUT'])
def api_enable_break_even(ticket):
    """Enable an independent break-even trigger using pips OR USD."""
    try:
        data = request.get_json() or {}
        pips_distance = float(data['pips_distance']) if data.get('pips_distance') is not None else None
        usd_distance = float(data['usd_distance']) if data.get('usd_distance') is not None else None
        if (pips_distance is None) == (usd_distance is None):
            return jsonify({'success': False, 'error': 'Provide exactly one of pips_distance or usd_distance'}), 400
        if (pips_distance is not None and pips_distance <= 0) or (usd_distance is not None and usd_distance <= 0):
            return jsonify({'success': False, 'error': 'Break-even distance must be > 0'}), 400

        position = get_position_details(ticket)
        if not position:
            return jsonify({'success': False, 'error': f'Position {ticket} not found'}), 404
        from core.execution import _active_trails, start_trailing_monitor
        import time
        config = _active_trails.get(ticket, {})
        config.update({'symbol': position.get('symbol'), 'break_even_enabled': True,
                       'break_even_pips_distance': pips_distance,
                       'break_even_usd_distance': usd_distance,
                       'created_at': config.get('created_at', time.time())})
        _active_trails[ticket] = config
        start_trailing_monitor()
        trigger = f"${usd_distance:.2f}" if usd_distance is not None else f"{pips_distance:g} pips"
        return jsonify({'success': True, 'message': f'Break-even enabled for position {ticket}',
                        'data': {'ticket': ticket, 'break_even_pips_distance': pips_distance,
                                 'break_even_usd_distance': usd_distance, 'trigger': trigger,
                                 'symbol': position.get('symbol')}}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/break-even/disable/<int:ticket>', methods=['PUT'])
def api_disable_break_even(ticket):
    try:
        from core.execution import _active_trails
        if ticket not in _active_trails:
            return jsonify({'success': False, 'error': f'No active position management for position {ticket}'}), 404
        _active_trails[ticket]['break_even_enabled'] = False
        _active_trails[ticket]['break_even_pips_distance'] = None
        _active_trails[ticket]['break_even_usd_distance'] = None
        return jsonify({'success': True, 'message': f'Break-even disabled for position {ticket}', 'data': {'ticket': ticket}}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/break-even/apply/<int:ticket>', methods=['PUT'])
def api_apply_break_even(ticket):
    """Immediately evaluate/apply the break-even trigger."""
    try:
        data = request.get_json() or {}
        pips_distance = float(data['pips_distance']) if data.get('pips_distance') is not None else None
        usd_distance = float(data['usd_distance']) if data.get('usd_distance') is not None else None
        if (pips_distance is None) == (usd_distance is None):
            return jsonify({'success': False, 'error': 'Provide exactly one of pips_distance or usd_distance'}), 400
        from core.execution import apply_break_even
        result = apply_break_even(ticket, pips_distance=pips_distance, usd_distance=usd_distance)
        return jsonify(result), 200 if result.get('success') else 400
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# BREAK-EVEN STATUS ENDPOINT
# ============================================================

@api_bp.route('/position/break-even/status/<int:ticket>', methods=['GET'])
def api_get_break_even_status(ticket):
    """Query break-even status directly (works for open or recently-closed positions)."""
    try:
        result = get_break_even_status(ticket)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# TRAILING STOP ENDPOINTS (PUT Methods)
# ============================================================

@api_bp.route('/position/trailing/enable/<int:ticket>', methods=['PUT'])
def api_enable_trailing(ticket):
    """Enable trailing using exactly one distance unit: pips OR USD."""
    try:
        data = request.get_json() or {}
        trailing_pips = float(data['trailing_pips']) if data.get('trailing_pips') is not None else None
        trailing_usd_distance = float(data['trailing_usd_distance']) if data.get('trailing_usd_distance') is not None else None
        if (trailing_pips is None) == (trailing_usd_distance is None):
            return jsonify({'success': False, 'error': 'Provide exactly one of trailing_pips or trailing_usd_distance'}), 400
        if (trailing_pips is not None and trailing_pips <= 0) or (trailing_usd_distance is not None and trailing_usd_distance <= 0):
            return jsonify({'success': False, 'error': 'Trailing distance must be > 0'}), 400
        position = get_position_details(ticket)
        if not position:
            return jsonify({'success': False, 'error': f'Position {ticket} not found'}), 404
        from core.execution import _active_trails, start_trailing_monitor
        import time
        config = _active_trails.get(ticket, {})
        config.update({'symbol': position.get('symbol'), 'trailing_enabled': True,
                       'pips_distance': trailing_pips, 'usd_distance': trailing_usd_distance,
                       'step_pips': trailing_pips, 'last_sl': position.get('stop_loss'),
                       'created_at': config.get('created_at', time.time())})
        _active_trails[ticket] = config
        start_trailing_monitor()
        distance = f"${trailing_usd_distance:.2f}" if trailing_usd_distance is not None else f"{trailing_pips:g} pips"
        return jsonify({'success': True, 'message': f'Trailing stop enabled for position {ticket}',
                        'data': {'ticket': ticket, 'trailing_pips': trailing_pips,
                                 'trailing_usd_distance': trailing_usd_distance, 'distance': distance,
                                 'symbol': position.get('symbol')}}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/trailing/disable/<int:ticket>', methods=['PUT'])
def api_disable_trailing(ticket):
    try:
        from core.execution import _active_trails
        
        if ticket in _active_trails:
            del _active_trails[ticket]
            logger.info(f"✅ Trailing stop disabled for position {ticket}")
            return jsonify({
                'success': True, 
                'message': f'Trailing stop disabled for position {ticket}',
                'data': {'ticket': ticket}
            }), 200
        
        return jsonify({'success': False, 'error': f'No active trailing for position {ticket}'}), 404
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/trailing/update/<int:ticket>', methods=['PUT'])
def api_update_trailing(ticket):
    """Update trailing distance using pips OR USD."""
    try:
        data = request.get_json() or {}
        trailing_pips = float(data['trailing_pips']) if data.get('trailing_pips') is not None else None
        trailing_usd_distance = float(data['trailing_usd_distance']) if data.get('trailing_usd_distance') is not None else None
        if (trailing_pips is None) == (trailing_usd_distance is None):
            return jsonify({'success': False, 'error': 'Provide exactly one of trailing_pips or trailing_usd_distance'}), 400
        if (trailing_pips is not None and trailing_pips <= 0) or (trailing_usd_distance is not None and trailing_usd_distance <= 0):
            return jsonify({'success': False, 'error': 'Trailing distance must be > 0'}), 400
        from core.execution import _active_trails
        if ticket not in _active_trails:
            return jsonify({'success': False, 'error': f'No active position management for position {ticket}'}), 404
        _active_trails[ticket]['pips_distance'] = trailing_pips
        _active_trails[ticket]['usd_distance'] = trailing_usd_distance
        _active_trails[ticket]['step_pips'] = trailing_pips
        distance = f"${trailing_usd_distance:.2f}" if trailing_usd_distance is not None else f"{trailing_pips:g} pips"
        return jsonify({'success': True, 'message': f'Trailing stop updated for position {ticket}',
                        'data': {'ticket': ticket, 'trailing_pips': trailing_pips,
                                 'trailing_usd_distance': trailing_usd_distance, 'distance': distance,
                                 'symbol': _active_trails[ticket].get('symbol')}}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/position/trailing/status', methods=['GET'])
def api_get_trailing_status():
    try:
        result = get_active_trails()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/trailing-stop/stats', methods=['GET'])
def api_get_trailing_stats():
    try:
        result = get_trail_stats()
        return jsonify({'success': True, 'data': result}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# GET POSITIONS ENDPOINT
# ============================================================

@api_bp.route('/positions', methods=['GET'])
def api_get_positions():
    try:
        symbol = request.args.get('symbol')
        strategy_magic = request.args.get('magic', type=int)
        
        positions = get_open_positions(symbol)
        
        if strategy_magic:
            positions = [p for p in positions if p.get('magic') == strategy_magic]
        
        total_risk = 0
        total_reward = 0
        total_profit = 0
        total_probability = 0
        
        for p in positions:
            if p.get('stop_loss') and p.get('price_open'):
                sl_distance = abs(p['price_open'] - p['stop_loss'])
                pip_value = sl_distance * p.get('volume', 0) * 10000
                risk = pip_value
                total_risk += risk
                p['risk_amount_usd'] = round(risk, 2)
            
            if p.get('take_profit') and p.get('price_open'):
                tp_distance = abs(p['take_profit'] - p['price_open'])
                pip_value = tp_distance * p.get('volume', 0) * 10000
                reward = pip_value
                total_reward += reward
                p['potential_reward_usd'] = round(reward, 2)
            
            total_profit += p.get('profit_usd', 0)
        
        avg_probability = (total_probability / len(positions) * 100) if positions else 0
        
        return jsonify({
            'success': True, 
            'count': len(positions), 
            'positions': positions,
            'summary': {
                'total_risk_usd': round(total_risk, 2),
                'total_potential_reward_usd': round(total_reward, 2),
                'total_profit_usd': round(total_profit, 2),
                'avg_probability_percent': round(avg_probability, 1),
                'total_expected_value': round(total_reward - total_risk, 2)
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# CALCULATION ENDPOINTS
# ============================================================

@api_bp.route('/calculate-lot', methods=['POST'])
def api_calculate_lot():
    try:
        data = request.get_json()
        required_fields = ['symbol', 'fixed_trade_size_usd', 'risk_per_trade']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        result = calculate_lot(symbol=data['symbol'].upper(),
                                fixed_trade_size_usd=float(data['fixed_trade_size_usd']),
                                risk_per_trade=float(data['risk_per_trade']),
                                min_stop_pips_override=data.get('min_stop_pips_override'))
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# ACCOUNT ENDPOINTS
# ============================================================

@api_bp.route('/account', methods=['GET'])
def api_get_account():
    try:
        result = get_account_info()
        return jsonify({'success': True, 'data': result}), 200
    except TradingException as e:
        return handle_trading_exception(e)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# SYMBOL INFO ENDPOINTS
# ============================================================

@api_bp.route('/symbol/<string:symbol_name>', methods=['GET'])
def api_get_symbol_info(symbol_name):
    try:
        result = get_symbol_info(symbol_name.upper())
        return jsonify(result), 200 if result['success'] else 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/symbols', methods=['GET'])
def api_get_symbols():
    try:
        symbols = mt5.symbols_get()
        if not symbols:
            return jsonify({'success': False, 'error': 'No symbols found'}), 404
        
        symbol_list = []
        for symbol in symbols[:100]:
            tick = mt5.symbol_info_tick(symbol.name)
            symbol_list.append({
                'name': symbol.name,
                'description': symbol.description,
                'currency_base': symbol.currency_base,
                'currency_profit': symbol.currency_profit,
                'digits': symbol.digits,
                'volume_min': symbol.volume_min,
                'volume_max': symbol.volume_max,
                'bid': tick.bid if tick else None,
                'ask': tick.ask if tick else None,
                'spread_pips': (tick.ask - tick.bid) / symbol.point if tick else None
            })
        
        return jsonify({'success': True, 'count': len(symbol_list), 'symbols': symbol_list}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# TRADE HISTORY ENDPOINT
# ============================================================

@api_bp.route('/trades/history', methods=['GET'])
def api_get_trade_history():
    try:
        from datetime import timezone

        symbol      = request.args.get('symbol')
        magic       = request.args.get('magic', type=int)
        last_n_days = request.args.get('last_n_days', type=int)
        from_str    = request.args.get('from_date')
        to_str      = request.args.get('to_date')

        from_date = None
        to_date   = None

        if from_str:
            try:
                from_date = datetime.fromisoformat(from_str).replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid from_date format. Use ISO: 2025-01-01T00:00:00'}), 400

        if to_str:
            try:
                to_date = datetime.fromisoformat(to_str).replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid to_date format. Use ISO: 2025-06-01T00:00:00'}), 400

        result = get_trade_history(
            from_date   = from_date,
            to_date     = to_date,
            symbol      = symbol.upper() if symbol else None,
            magic       = magic,
            last_n_days = last_n_days
        )

        if not result['success']:
            return jsonify(result), 500

        return jsonify({
            'success':   True,
            'count':     len(result.get('trades', [])),
            'deals':     result.get('deals', []),
            'trades':    result.get('trades', []),
            'summary':   result.get('summary', {}),
            'timestamp': datetime.now().isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Trade history endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# OPEN POSITIONS ENDPOINT
# ============================================================

@api_bp.route('/positions/open', methods=['GET'])
def api_get_open_positions():
    try:
        symbol = request.args.get('symbol')
        magic  = request.args.get('magic', type=int)

        positions = get_open_positions(symbol.upper() if symbol else None)

        if magic:
            positions = [p for p in positions if p.get('magic') == magic]

        # ✅ FIX: get_active_trails()['active_trails'] is a list of dicts
        # (each with 'ticket', 'pips_distance', 'break_even_enabled', ...),
        # not (ticket, config) pairs - unpacking each dict as `t, c` throws
        # "too many values to unpack" as soon as a trail dict has more than
        # 2 keys, which it always does. Key it by ticket instead.
        _trails_list = get_active_trails().get('active_trails') or []
        active_trails = {trail.get('ticket'): trail for trail in _trails_list}
        
        for p in positions:
            p['has_trailing_stop'] = p.get('ticket') in active_trails
            if p.get('ticket') in active_trails:
                p['trailing_pips'] = active_trails[p['ticket']].get('pips_distance')
                p['trailing_usd_distance'] = active_trails[p['ticket']].get('usd_distance')
                p['break_even_enabled'] = active_trails[p['ticket']].get('break_even_enabled', False)
                p['break_even_pips_distance'] = active_trails[p['ticket']].get('break_even_pips_distance')
                p['break_even_usd_distance'] = active_trails[p['ticket']].get('break_even_usd_distance')

        total_risk        = sum(p.get('risk_amount_usd', 0) for p in positions)
        total_reward      = sum(p.get('potential_reward_usd', 0) for p in positions)
        total_profit      = sum(p.get('profit_usd', 0) for p in positions)
        total_ev          = sum(p.get('expected_value_usd', 0) for p in positions)
        avg_probability   = (
            round(sum(p.get('probability_of_hit', 0) for p in positions) / len(positions), 2)
            if positions else 0
        )

        return jsonify({
            'success':   True,
            'count':     len(positions),
            'positions': positions,
            'summary': {
                'total_risk_usd':            round(total_risk, 2),
                'total_potential_reward_usd': round(total_reward, 2),
                'total_profit_usd':          round(total_profit, 2),
                'total_expected_value_usd':  round(total_ev, 2),
                'avg_probability_percent':   avg_probability,
            },
            'timestamp': datetime.now().isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Get open positions endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# SINGLE POSITION ENDPOINT
# ============================================================

@api_bp.route('/position/<int:ticket>', methods=['GET'])
def api_get_position(ticket):
    try:
        position = get_position_details(ticket)
        if not position:
            return jsonify({'success': False, 'error': f'Position {ticket} not found'}), 404
        
        active_trails = get_active_trails()
        has_trailing = False
        trailing_pips = None
        trailing_usd_distance = None
        break_even_enabled = False
        break_even_pips_distance = None
        break_even_usd_distance = None
        
        if active_trails.get('active_trails'):
            for trail in active_trails['active_trails']:
                if trail.get('ticket') == ticket:
                    has_trailing = True
                    trailing_pips = trail.get('pips_distance')
                    trailing_usd_distance = trail.get('usd_distance')
                    break_even_enabled = trail.get('break_even_enabled', False)
                    break_even_pips_distance = trail.get('break_even_pips_distance')
                    break_even_usd_distance = trail.get('break_even_usd_distance')
                    break

        # Break-even status (whether the SL has actually been moved to entry yet),
        # as opposed to break_even_enabled above which just reflects config.
        be_status = get_break_even_status(ticket)
        
        formatted_position = {
            "ticket": position.get("ticket"),
            "symbol": position.get("symbol"),
            "type": "BUY" if position.get("type") == 0 else "SELL",
            "volume": position.get("volume"),
            "price_open": position.get("price_open"),
            "price_current": position.get("price_current"),
            "stop_loss": position.get("sl"),
            "take_profit": position.get("tp"),
            "profit_usd": round(position.get("profit", 0), 2),
            "swap_usd": round(position.get("swap", 0), 2),
            "commission_usd": round(position.get("commission", 0), 2),
            "total_profit_usd": round(position.get("profit", 0) + position.get("swap", 0) + position.get("commission", 0), 2),
            "magic": position.get("magic"),
            "comment": position.get("comment"),
            "time": datetime.fromtimestamp(position.get("time")).isoformat() if position.get("time") else None,
            "has_trailing_stop": has_trailing,
            "trailing_pips": trailing_pips,
            "trailing_usd_distance": trailing_usd_distance,
            "break_even_enabled": break_even_enabled,
            "break_even_pips_distance": break_even_pips_distance,
            "break_even_usd_distance": break_even_usd_distance,
            "has_break_even": be_status.get("has_break_even", break_even_enabled),
            "break_even_applied": be_status.get("break_even_applied", False),
            "break_even_trigger": be_status.get("break_even_trigger"),
            "break_even_trigger_type": be_status.get("break_even_trigger_type"),
        }
        
        return jsonify({'success': True, 'position': formatted_position}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# RISK MANAGEMENT ENDPOINT
# ============================================================

@api_bp.route('/risk/portfolio-summary', methods=['GET'])
def api_portfolio_risk_summary():
    try:
        positions = get_open_positions()
        
        if not positions:
            return jsonify({
                'success': True,
                'total_positions': 0,
                'total_risk_usd': 0,
                'total_potential_reward_usd': 0,
                'total_profit_usd': 0,
                'weighted_avg_probability': 0,
                'portfolio_expected_value': 0,
                'max_drawdown_risk': 0
            }), 200
        
        total_risk = sum(p.get('risk_amount_usd', 0) for p in positions)
        total_reward = sum(p.get('potential_reward_usd', 0) for p in positions)
        total_profit = sum(p.get('profit_usd', 0) for p in positions)
        
        total_probability_weight = sum(p.get('probability_of_hit', 0) * p.get('risk_amount_usd', 0) for p in positions)
        total_risk_weight = total_risk if total_risk > 0 else 1
        weighted_probability = total_probability_weight / total_risk_weight if total_risk_weight > 0 else 0
        
        portfolio_ev = sum(p.get('expected_value_usd', 0) for p in positions)
        
        symbol_groups = {}
        for p in positions:
            sym = p.get('symbol')
            if sym not in symbol_groups:
                symbol_groups[sym] = []
            symbol_groups[sym].append(p)
        
        correlation_risk = len(symbol_groups) / len(positions) if positions else 1
        
        return jsonify({
            'success': True,
            'total_positions': len(positions),
            'total_risk_usd': round(total_risk, 2),
            'total_potential_reward_usd': round(total_reward, 2),
            'total_profit_usd': round(total_profit, 2),
            'weighted_avg_probability': round(weighted_probability, 2),
            'portfolio_expected_value': round(portfolio_ev, 2),
            'max_drawdown_risk': round(total_risk * 0.7, 2),
            'correlation_diversification': round(1 - correlation_risk, 2),
            'unique_symbols': len(symbol_groups)
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# APP FACTORY
# ============================================================

def create_app():
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(api_bp)

    # ✅ Start the copy-trade manager's background threads (position
    # monitor + health report) alongside the Flask app, same as the
    # monitor starts its own threads in start_non_blocking().
    copy_trade_manager.start()
    
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        return response
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'success': False, 'error': 'Endpoint not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    return app


# ============================================================
# MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("Starting Python Trading API")
    print("="*60)
    print("\n📈 TAKE PROFIT:")
    print("   - TP1 uses MT5's native TP field (optional - only set if provided)")
    print("   - Optional TP2/TP3 split the position into partial closes (70/30, or 33/33/34)")
    print("     since MT5 only supports one native TP - managed by the position monitor")
    print("   - SL is AUTO-CALCULATED from risk_per_trade if not provided")
    print("\n📊 SIMPLIFIED TRAILING STOP:")
    print("   - Break-even: enable_break_even + exactly one break_even_pips_distance OR break_even_usd_distance")
    print("   - Trailing: enable_trailing_stop + exactly one trailing_pips OR trailing_usd_distance")
    print("   - USD distance is converted per-symbol using MT5 profit calculation")
    print("="*60)
    print("\nInitializing MT5...")
    
    if connect_mt5():
        print("✅ MT5 initialized successfully")
        account = mt5.account_info()
        if account:
            print(f"✅ Already logged in to: {account.login}")
            print(f"   Balance: {account.balance} {account.currency}")
            print(f"   Leverage: {account.leverage}")
        else:
            print("⚠️  MT5 initialized but not logged in")
            print("   Use POST /api/v1/mt5/connect with your credentials")
    else:
        print("❌ MT5 initialization failed")
        print("   Make sure MT5 terminal is running")
        exit(1)

    # ✅ Start position monitor + health threads before serving requests,
    # same lifecycle as MultiSymbolMonitor.start_non_blocking()
    copy_trade_manager.start()
    
    print("\n" + "="*60)
    print("🚀 Starting Flask API on port 5003...")
    print("="*60)
    print("\n📋 Available Endpoints:")
    print("   POST   /api/v1/mt5/connect          - Connect to MT5")
    print("   POST   /api/v1/mt5/disconnect       - Disconnect from MT5")
    print("   GET    /api/v1/health               - Health check")
    print("   POST   /api/v1/trade/execute        - Execute trade (auto SL, optional TP)")
    print("   POST   /api/v1/trade/analyse        - Analyze trade")
    print("   POST   /api/v1/trade/probability    - Calculate probability")
    print("   GET    /api/v1/positions            - Get all positions")
    print("   GET    /api/v1/positions/open       - Get open positions")
    print("   GET    /api/v1/position/<ticket>    - Get single position")
    print("   POST   /api/v1/position/close/<ticket> - Close position")
    print("   PUT    /api/v1/position/partial-close/<ticket> - Partial close")
    print("   PUT    /api/v1/position/<ticket>/stop-loss - Modify SL")
    print("   PUT    /api/v1/position/<ticket>/take-profit - Modify TP")
    print("   POST   /api/v1/positions/close/all  - Close all positions")
    print("   GET    /api/v1/account              - Get account info")
    print("   GET    /api/v1/symbol/<symbol>      - Get symbol info")
    print("   GET    /api/v1/symbols              - Get all symbols")
    print("   GET    /api/v1/market/conditions/<symbol> - Get market conditions")
    print("   GET    /api/v1/market/status/<symbol>    - Check market closed")
    print("   GET    /api/v1/market/volatility/<symbol> - Check volatility")
    print("   GET    /api/v1/market/spread/<symbol>    - Check spread")
    print("   GET    /api/v1/risk/portfolio-summary   - Portfolio risk")
    print("   PUT    /api/v1/position/break-even/enable/<ticket> - Enable break-even")
    print("   PUT    /api/v1/position/break-even/disable/<ticket> - Disable break-even")
    print("   PUT    /api/v1/position/break-even/apply/<ticket> - Apply/check break-even")
    print("   GET    /api/v1/position/break-even/status/<ticket> - Get break-even status")
    print("   PUT    /api/v1/position/trailing/enable/<ticket> - Enable trailing stop")
    print("   PUT    /api/v1/position/trailing/disable/<ticket> - Disable trailing stop")
    print("   PUT    /api/v1/position/trailing/update/<ticket> - Update trailing distance")
    print("   GET    /api/v1/position/trailing/status - Trailing stop status")
    print("   GET    /api/v1/trailing-stop/stats  - Trailing stop statistics")
    print("   GET    /api/v1/trades/history       - Get trade history")
    print("   POST   /api/v1/webhook/close        - Webhook: position closed (SL/TP/manual)")
    print("   POST   /api/v1/webhook/trailing     - Webhook: trailing stop update")
    print("   POST   /api/v1/webhook/trade        - Webhook: combined CLOSE/MODIFY (TradeWebhook.mq5)")
    print("   GET    /api/v1/copy-trade/status    - Copy-trade manager status")
    print("\n" + "="*60)
    
    app = create_app()
    app.run(host='0.0.0.0', port=5003, debug=False, threaded=True)