# thread_monitor.py - IMPROVED VERSION with adaptive polling
# ONLY logs non-veto responses to file - veto responses are shown on console but NOT saved

import json
import time
import logging
import threading
import signal
import sys
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import core modules
from core.asset_analysis import analyze_institutional_signal
from core.mt5_connector import connect_mt5, shutdown_mt5, is_mt5_connected
from core.helpers import make_json_safe
from core.session_manager import get_session_manager
from core.news_veto import get_news_summary

# Configure logging - console only
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


class AdaptiveThreadMonitor:
    """
    Adaptive monitor that changes polling frequency based on market conditions.
    
    Polling Strategy:
    - NORMAL: 60 seconds (low activity, no signals)
    - WATCHING: 15 seconds (golden signals detected, waiting for discount)
    - CRITICAL: 5 seconds (price approaching discount zone)
    - ENTRY: 1 second (at discount, waiting for confirmation)
    
    LOGGING POLICY:
    - VETO responses: NOT logged to file (only console)
    - ENTRY SIGNALS: Logged to file
    - NORMAL/DISCOUNT APPROACH: Logged to file
    - ERRORS: Logged to file
    """
    
    # Polling intervals in seconds
    INTERVAL_NORMAL = 60      # No signals, just heartbeat
    INTERVAL_WATCHING = 15    # Golden signals detected
    INTERVAL_CRITICAL = 5     # Price approaching discount
    INTERVAL_ENTRY = 1        # At discount, waiting for confirmation
    
    def __init__(self):
        """Initialize the adaptive thread monitor with hardcoded asset configuration."""
        self.config = {
            "symbol": "USDCAD",
            "order_type": "BUY",
            "leverage": 200,
            "fixed_trade_size_usd": 200,
            "risk_per_trade": 0.1,
            "timeframe": "M1",
            "debug": False
        }
        
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.current_interval = self.INTERVAL_NORMAL
        self.last_state = "NORMAL"
        
        # Save log file in the parent directory (project root)
        self.log_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "log_monitor.json"
        
        # Track price action for discount detection
        self.last_price = None
        self.last_discount_distance = None
        self.discount_approach_count = 0
        self.consecutive_discount_checks = 0
        
        self.stats = {
            "total_checks": 0,
            "entry_signals": 0,
            "vetoes": 0,
            "errors": 0,
            "start_time": None,
            "last_check": None,
            "interval_changes": []
        }
        
        # Initialize log file
        self._init_log_file()
        
        logger.info(f"AdaptiveThreadMonitor initialized")
        logger.info(f"Asset: {self.config['symbol']} - {self.config['order_type']} - {self.config['timeframe']}")
        logger.info(f"Log file: {self.log_path.absolute()}")
        logger.info(f"Base interval: {self.INTERVAL_NORMAL}s (adaptive up to {self.INTERVAL_ENTRY}s)")
        logger.info(f"LOGGING POLICY: Only non-veto responses are saved to file")
    
    def _init_log_file(self):
        """Initialize the JSON log file if it doesn't exist."""
        if not self.log_path.exists():
            initial_data = {
                "monitor_info": {
                    "created_at": datetime.now().isoformat(),
                    "symbol": self.config["symbol"],
                    "order_type": self.config["order_type"],
                    "timeframe": self.config["timeframe"],
                    "adaptive_polling": True,
                    "intervals": {
                        "normal": self.INTERVAL_NORMAL,
                        "watching": self.INTERVAL_WATCHING,
                        "critical": self.INTERVAL_CRITICAL,
                        "entry": self.INTERVAL_ENTRY
                    },
                    "leverage": self.config["leverage"],
                    "fixed_trade_size_usd": self.config["fixed_trade_size_usd"],
                    "risk_per_trade": self.config["risk_per_trade"],
                    "logging_policy": "ONLY_NON_VETO_RESPONSES"
                },
                "logs": [],
                "price_history": []
            }
            self._write_log(initial_data)
            logger.info("Created new log_monitor.json")
    
    def _write_log(self, data: dict):
        """Write data to JSON log file."""
        try:
            with open(self.log_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to write to log file: {e}")
    
    def _read_log(self) -> dict:
        """Read existing log data."""
        try:
            if self.log_path.exists():
                with open(self.log_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "logs" not in data:
                        data = {"monitor_info": {}, "logs": [], "price_history": []}
                    if "price_history" not in data:
                        data["price_history"] = []
                    return data
            return {"monitor_info": {}, "logs": [], "price_history": []}
        except Exception as e:
            logger.error(f"Failed to read log file: {e}")
            return {"monitor_info": {}, "logs": [], "price_history": []}
    
    def _determine_polling_interval(self, full_response: Dict[str, Any]) -> int:
        """
        Dynamically determine polling interval based on market conditions.
        
        Returns:
            Interval in seconds
        """
        try:
            # Extract entry analysis
            entry_analysis = full_response.get("entry_analysis", {})
            discount = entry_analysis.get("discount", {})
            golden_signals = entry_analysis.get("golden_signals", {})
            
            is_at_discount = discount.get("is_at_discount", False)
            distance_to_discount = discount.get("distance_to_discount_pips", 999)
            discount_quality = discount.get("discount_quality", "NO_DISCOUNT")
            signal_count = golden_signals.get("signal_count", 0)
            
            # Store for trend detection
            self.last_discount_distance = distance_to_discount
            
            # CRITICAL: At discount, waiting for confirmation - fastest polling
            if is_at_discount and discount_quality != "NO_DISCOUNT":
                self.last_state = "ENTRY"
                self.consecutive_discount_checks += 1
                return self.INTERVAL_ENTRY
            
            # CRITICAL: Price very close to discount (within 10 pips)
            if distance_to_discount < 10 and distance_to_discount > 0:
                self.last_state = "CRITICAL"
                self.discount_approach_count += 1
                return self.INTERVAL_CRITICAL
            
            # WATCHING: Golden signals present, price moving toward discount
            if signal_count >= 2 or distance_to_discount < 30:
                self.last_state = "WATCHING"
                return self.INTERVAL_WATCHING
            
            # Check if price is trending toward discount (consecutive approaches)
            if self.discount_approach_count >= 3:
                self.last_state = "WATCHING_TREND"
                self.discount_approach_count = 0  # Reset after triggering
                return self.INTERVAL_WATCHING
            
            # NORMAL: No signals, no discount proximity
            self.last_state = "NORMAL"
            self.discount_approach_count = max(0, self.discount_approach_count - 1)
            self.consecutive_discount_checks = 0
            return self.INTERVAL_NORMAL
            
        except Exception as e:
            logger.debug(f"Error determining interval: {e}")
            return self.INTERVAL_NORMAL
    
    def _should_log_response(self, full_response: Dict[str, Any]) -> bool:
        """
        Determine if response should be logged to file.
        
        Returns:
            True if should log, False if should skip (veto responses)
        """
        try:
            # Check if there's a veto
            vetos = full_response.get("vetos", {})
            veto_triggered = vetos.get("triggered", False)
            
            # Also check entry analysis for veto
            entry_analysis = full_response.get("entry_analysis", {})
            final_decision = entry_analysis.get("final_decision", "")
            
            # Check pre_entry_passed
            pre_entry_passed = entry_analysis.get("pre_entry_passed", True)
            
            # Veto detected - DO NOT LOG
            if veto_triggered:
                return False
            
            # Check for "VETO" in final decision
            if "VETO" in str(final_decision).upper():
                return False
            
            # Check for "SKIP" in final decision (pre-entry failures)
            if "SKIP" in str(final_decision).upper():
                return False
            
            # If pre_entry_passed is False, it's a skip (don't log)
            if not pre_entry_passed:
                return False
            
            # Check if entry_triggered is False due to veto
            should_enter = entry_analysis.get("should_enter", False)
            reason = entry_analysis.get("reason", "")
            if not should_enter and "VETO" in str(reason).upper():
                return False
            
            # Log everything else (entry signals, discount approaches, normal monitoring)
            return True
            
        except Exception as e:
            logger.debug(f"Error determining if should log: {e}")
            return True  # Log on error to capture issues
    
    def _log_price_history(self, full_response: Dict[str, Any]):
        """Log price history for discount zone analysis (only for non-veto responses)."""
        try:
            # Only log price history if we're logging the response
            if not self._should_log_response(full_response):
                return
            
            entry_price = full_response.get("final_verdict", {}).get("entry_price")
            entry_analysis = full_response.get("entry_analysis", {})
            discount = entry_analysis.get("discount", {})
            
            if entry_price:
                price_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "price": entry_price,
                    "is_at_discount": discount.get("is_at_discount", False),
                    "distance_to_discount_pips": discount.get("distance_to_discount_pips"),
                    "discount_quality": discount.get("discount_quality"),
                    "zone_grade": discount.get("zone_grade"),
                    "polling_interval": self.current_interval,
                    "state": self.last_state
                }
                
                log_data = self._read_log()
                log_data["price_history"].append(price_entry)
                
                # Keep last 1000 price points
                if len(log_data["price_history"]) > 1000:
                    log_data["price_history"] = log_data["price_history"][-1000:]
                
                self._write_log(log_data)
        except Exception as e:
            logger.debug(f"Error logging price history: {e}")
    
    def _append_to_log(self, full_response: Dict[str, Any]):
        """
        Append FULL response to the JSON log file.
        ONLY called for non-veto responses.
        """
        # Skip logging entirely if this is a veto response
        if not self._should_log_response(full_response):
            logger.debug(f"[SKIP_LOG] Veto detected, response not saved to file")
            return
        
        safe_response = make_json_safe(full_response)
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": self.config["symbol"],
            "order_type": self.config["order_type"],
            "timeframe": self.config["timeframe"],
            "polling_interval": self.current_interval,
            "state": self.last_state,
            "response": safe_response
        }
        
        log_data = self._read_log()
        log_data["logs"].append(log_entry)
        
        # Keep last 2000 entries
        if len(log_data["logs"]) > 2000:
            log_data["logs"] = log_data["logs"][-2000:]
        
        log_data["monitor_info"]["last_updated"] = datetime.now().isoformat()
        self._write_log(log_data)
        logger.debug(f"[LOG_SAVED] Non-veto response saved to file")
    
    def _extract_summary(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key decision information for console output."""
        try:
            final_verdict = full_response.get("final_verdict", {})
            if final_verdict:
                return {
                    "action": final_verdict.get("simple_action", "UNKNOWN"),
                    "direction": final_verdict.get("action", "UNKNOWN"),
                    "verdict": final_verdict.get("verdict", "UNKNOWN"),
                    "confidence_percent": final_verdict.get("probability_percent", 0),
                    "star_rating": final_verdict.get("star_rating", 1),
                    "stars": final_verdict.get("stars_display", "☆")
                }
            
            decision = full_response.get("decision", {})
            return {
                "action": decision.get("action", "UNKNOWN"),
                "direction": decision.get("direction", "UNKNOWN"),
                "verdict": decision.get("verdict", "UNKNOWN"),
                "confidence_percent": decision.get("confidence_percent", 0),
                "star_rating": decision.get("star_rating", 1),
                "stars": decision.get("stars", "☆")
            }
        except Exception:
            return {
                "action": "UNKNOWN",
                "direction": "UNKNOWN",
                "verdict": "UNKNOWN",
                "confidence_percent": 0,
                "star_rating": 1,
                "stars": "☆"
            }
    
    def analyze_and_log(self) -> Optional[Dict[str, Any]]:
        """Perform analysis and log the FULL response (only if not veto)."""
        try:
            symbol = self.config["symbol"]
            order_type = self.config["order_type"]
            fixed_trade_size_usd = self.config["fixed_trade_size_usd"]
            risk_per_trade = self.config["risk_per_trade"]
            leverage = self.config["leverage"]
            timeframe = self.config["timeframe"]
            debug = self.config["debug"]
            
            # Show polling state in console
            state_emoji = {
                "NORMAL": "🔵",
                "WATCHING": "🟡",
                "WATCHING_TREND": "🟠",
                "CRITICAL": "🔴",
                "ENTRY": "🟢"
            }.get(self.last_state, "⚪")
            
            logger.info(f"{state_emoji} [{self.last_state}] Analyzing {symbol} ({timeframe}) - {order_type} (interval: {self.current_interval}s)")
            
            full_response = analyze_institutional_signal(
                symbol=symbol,
                order_type=order_type,
                fixed_trade_size_usd=fixed_trade_size_usd,
                risk_per_trade=risk_per_trade,
                leverage=leverage,
                timeframe=timeframe,
                debug=debug
            )
            
            if not full_response.get("success", False):
                error_msg = full_response.get("error", "Unknown error")
                logger.error(f"❌ Analysis failed: {error_msg}")
                
                # Always log errors (they are not vetos)
                error_response = {
                    "success": False,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }
                self._append_to_log(error_response)
                
                with self.lock:
                    self.stats["errors"] += 1
                return None
            
            # Check if this is a veto response
            is_veto = not self._should_log_response(full_response)
            
            # Log to file ONLY if not a veto
            if not is_veto:
                self._append_to_log(full_response)
                self._log_price_history(full_response)
                logger.debug(f"✅ Non-veto response logged to file")
            else:
                logger.debug(f"⏭️ Veto response - NOT saved to file (console only)")
            
            # Determine next polling interval based on results
            new_interval = self._determine_polling_interval(full_response)
            if new_interval != self.current_interval:
                with self.lock:
                    self.stats["interval_changes"].append({
                        "timestamp": datetime.now().isoformat(),
                        "from": self.current_interval,
                        "to": new_interval,
                        "reason": self.last_state
                    })
                logger.info(f"📊 Polling interval changed: {self.current_interval}s → {new_interval}s ({self.last_state})")
                self.current_interval = new_interval
            
            # Extract summary for console
            summary = self._extract_summary(full_response)
            
            # Extract discount info for detailed logging
            entry_analysis = full_response.get("entry_analysis", {})
            discount = entry_analysis.get("discount", {})
            
            # Extract veto info safely (handle None)
            vetos = full_response.get("vetos", {})
            veto_reason = vetos.get("reason")
            pre_entry_skip_reason = entry_analysis.get("pre_entry_skip_reason")
            
            # Update statistics
            with self.lock:
                self.stats["total_checks"] += 1
                self.stats["last_check"] = datetime.now().isoformat()
                
                if summary.get("action") == "ENTER NOW":
                    self.stats["entry_signals"] += 1
                    entry_price = full_response.get("final_verdict", {}).get("entry_price")
                    logger.info(f"✅✅✅ ENTRY SIGNAL: {summary.get('direction')} - Confidence: {summary.get('confidence_percent')}% - Stars: {summary.get('stars')} - Price: {entry_price}")
                    
                    # Log detailed discount info on entry
                    logger.info(f"   📍 Discount Info: {discount.get('discount_quality')} - {discount.get('distance_to_discount_pips')} pips from zone")
                    logger.info(f"   🎯 Zone Grade: {discount.get('zone_grade')} - Multiplier: {discount.get('grade_multiplier')}")
                    
                elif is_veto:
                    self.stats["vetoes"] += 1
                    # FIX: Handle None veto_reason safely
                    if veto_reason:
                        veto_display = veto_reason[:80] if len(veto_reason) > 80 else veto_reason
                    elif pre_entry_skip_reason:
                        veto_display = pre_entry_skip_reason[:80] if len(pre_entry_skip_reason) > 80 else pre_entry_skip_reason
                    else:
                        veto_display = "Unknown veto reason"
                    logger.info(f"⛔ VETO: {veto_display}... (NOT logged to file)")
                else:
                    # Show discount status for non-entry checks
                    if discount.get("is_at_discount"):
                        logger.info(f"🎯 At {discount.get('discount_quality')}: {discount.get('distance_to_discount_pips')} pips from zone (grade {discount.get('zone_grade')})")
                    elif discount.get("distance_to_discount_pips", 999) < 30:
                        logger.info(f"📍 Approaching discount: {discount.get('distance_to_discount_pips')} pips away")
                    else:
                        logger.info(f"📊 {summary.get('verdict', 'UNKNOWN')} - Conf: {summary.get('confidence_percent')}%")
            
            return full_response
            
        except Exception as e:
            logger.error(f"❌ Error during analysis: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            error_response = {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
            self._append_to_log(error_response)
            
            with self.lock:
                self.stats["errors"] += 1
            return None
    
    def _run_loop(self):
        """Main monitoring loop with adaptive intervals."""
        logger.info("Adaptive monitoring loop started")
        
        # Do initial analysis immediately
        self.analyze_and_log()
        
        # Then run with adaptive intervals
        while self.running:
            time.sleep(self.current_interval)
            if not self.running:
                break
            self.analyze_and_log()
        
        logger.info("Monitoring loop stopped")
    
    def start(self):
        """Start the monitoring thread."""
        if self.running:
            logger.warning("Monitor is already running")
            return
        
        self.running = True
        self.stats["start_time"] = datetime.now().isoformat()
        self.thread = threading.Thread(target=self._run_loop, name="AdaptiveMonitorThread", daemon=True)
        self.thread.start()
        logger.info(f"✅ Adaptive monitor started")
        self.print_status()
    
    def stop(self):
        """Stop the monitoring thread."""
        if not self.running:
            logger.warning("Monitor is not running")
            return
        
        logger.info("Stopping monitor...")
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        
        logger.info("✅ Monitor stopped")
        self.print_status()
    
    def print_status(self):
        """Print current monitoring status."""
        with self.lock:
            print("\n" + "=" * 70)
            print("📊 ADAPTIVE MONITOR STATUS")
            print("=" * 70)
            print(f"Asset: {self.config['symbol']}")
            print(f"Direction: {self.config['order_type']}")
            print(f"Timeframe: {self.config['timeframe']}")
            print(f"Current interval: {self.current_interval}s ({self.last_state})")
            print("-" * 70)
            print(f"Running: {self.running}")
            print(f"Total checks: {self.stats['total_checks']}")
            print(f"Entry signals: {self.stats['entry_signals']}")
            print(f"Vetoes: {self.stats['vetoes']}")
            print(f"Errors: {self.stats['errors']}")
            print(f"Interval changes: {len(self.stats.get('interval_changes', []))}")
            print(f"Started: {self.stats.get('start_time', 'N/A')}")
            print(f"Last check: {self.stats.get('last_check', 'N/A')}")
            print(f"Log file: {self.log_path.absolute()}")
            print(f"Logging policy: ONLY NON-VETO RESPONSES")
            print("=" * 70 + "\n")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        with self.lock:
            return self.stats.copy()
    
    def run_once(self) -> Optional[Dict[str, Any]]:
        """Run a single analysis and return result (useful for testing)."""
        return self.analyze_and_log()


# ============================================================
# Signal handlers for graceful shutdown
# ============================================================

monitor_instance = None


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    print("\n\n🛑 Shutdown signal received...")
    if monitor_instance:
        monitor_instance.stop()
    shutdown_mt5()
    sys.exit(0)


# ============================================================
# Main entry point
# ============================================================

def main():
    """Main function to run the adaptive thread monitor."""
    global monitor_instance
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    import argparse
    parser = argparse.ArgumentParser(description='Adaptive Thread Monitor for Trading Signals')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--status', action='store_true', help='Print status and exit')
    parser.add_argument('--symbol', type=str, help='Override symbol (default: XAGEUR)')
    parser.add_argument('--direction', type=str, choices=['BUY', 'SELL'], help='Override direction')
    parser.add_argument('--interval', type=int, help='Fixed interval override (disables adaptive)')
    
    args = parser.parse_args()
    
    # ============================================================
    # CONNECT TO MT5 FIRST
    # ============================================================
    print("\n" + "=" * 60)
    print("🔌 CONNECTING TO MT5...")
    print("=" * 60)
    
    if not connect_mt5():
        print("❌ Failed to connect to MT5")
        print("Please make sure MT5 is running and logged in")
        sys.exit(1)
    
    print("✅ MT5 Connected successfully\n")
    
    # Create monitor instance
    monitor_instance = AdaptiveThreadMonitor()
    
    # Override config
    if args.symbol:
        monitor_instance.config["symbol"] = args.symbol
        logger.info(f"Symbol overridden to: {args.symbol}")
    if args.direction:
        monitor_instance.config["order_type"] = args.direction
        logger.info(f"Direction overridden to: {args.direction}")
    if args.interval:
        # Fixed interval mode - disable adaptive
        monitor_instance.current_interval = args.interval
        logger.info(f"Fixed interval mode: {args.interval}s")
    
    if args.status:
        monitor_instance.print_status()
        return
    
    if args.once:
        result = monitor_instance.run_once()
        if result:
            print("\n✅ Analysis complete. Check log_monitor.json for full response.")
        return
    
    # Start monitoring
    print("\n" + "=" * 70)
    print("🚀 ADAPTIVE THREAD MONITOR STARTING")
    print("=" * 70)
    print(f"Asset: {monitor_instance.config['symbol']}")
    print(f"Direction: {monitor_instance.config['order_type']}")
    print(f"Timeframe: {monitor_instance.config['timeframe']}")
    print(f"Polling Strategy: ADAPTIVE")
    print(f"  - NORMAL: {AdaptiveThreadMonitor.INTERVAL_NORMAL}s (no signals)")
    print(f"  - WATCHING: {AdaptiveThreadMonitor.INTERVAL_WATCHING}s (signals detected)")
    print(f"  - CRITICAL: {AdaptiveThreadMonitor.INTERVAL_CRITICAL}s (approaching discount)")
    print(f"  - ENTRY: {AdaptiveThreadMonitor.INTERVAL_ENTRY}s (at discount)")
    print(f"Logging Policy: ONLY NON-VETO RESPONSES SAVED TO FILE")
    print(f"Log file: log_monitor.json")
    print("Press Ctrl+C to stop\n")
    
    monitor_instance.start()
    
    try:
        while monitor_instance.running:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)


if __name__ == "__main__":
    main()