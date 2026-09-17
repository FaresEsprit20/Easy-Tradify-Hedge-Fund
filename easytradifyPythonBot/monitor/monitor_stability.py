# monitor/monitor_stability.py
# ============================================================
# STABILITY TRACKING - 3 CHECKS, DIRECTION MUST MATCH
# ============================================================

import time
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# ✅ Use relative import
from .monitor_config import config

logger = logging.getLogger(__name__)

class StabilityTracker:
    """Handles stability checking for symbols."""
    
    def __init__(self):
        self.tracker: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_check: Dict[str, float] = {}
        self.stats = {
            "stable_signals": 0,
            "executable_signals": 0,
            "unstable_signals": 0
        }
    
    def should_check(self, symbol: str) -> bool:
        """Check if 30 seconds have passed since last check."""
        now = time.time()
        last = self._last_check.get(symbol, 0)
        if now - last >= config.STABILITY_CHECK_INTERVAL:
            self._last_check[symbol] = now
            return True
        return False
    
    def update(self, symbol: str, analysis_result: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Update stability tracker with new analysis."""
        if not self.should_check(symbol):
            return False, None
        
        with self._lock:
            if symbol not in self.tracker:
                self.tracker[symbol] = {
                    "checks": [],
                    "stable_signal": None,
                    "last_stable_time": 0,
                    "current_checks": 0,
                    "last_update": 0
                }
                logger.info(f"📊 {symbol}: Initializing stability tracker")
            
            tracker = self.tracker[symbol]
            
            # Extract data
            final_verdict = analysis_result.get("final_verdict", {})
            entry_analysis = analysis_result.get("entry_analysis", {})
            config_data = analysis_result.get("config", {})
            
            confidence = final_verdict.get("probability_percent", 0)
            direction = config_data.get("executed_direction", "BUY")
            should_enter = entry_analysis.get("should_enter", False)
            
            check = {
                "timestamp": time.time(),
                "datetime": datetime.now().isoformat(),
                "confidence": confidence,
                "direction": direction,
                "should_enter": should_enter,
                "verdict": final_verdict.get("verdict", ""),
                "entry_status": entry_analysis.get("entry_status", ""),
                "simple_action": entry_analysis.get("simple_action", ""),
                "stop_loss": final_verdict.get("stop_loss"),
                "take_profit_1": final_verdict.get("take_profit_1"),
                "entry_price": final_verdict.get("entry_price"),
                "buy_pct": final_verdict.get("buy_percentage", 0),
                "sell_pct": final_verdict.get("sell_percentage", 0),
                "trend": final_verdict.get("trend_direction", "NEUTRAL"),
                "adx": final_verdict.get("adx_value", 0),
            }
            
            tracker["checks"].append(check)
            if len(tracker["checks"]) > 20:
                tracker["checks"] = tracker["checks"][-20:]
            
            tracker["last_update"] = time.time()
            
            logger.info(f"📊 {symbol}: Check #{len(tracker['checks'])} - Conf: {check['confidence']}%, Dir: {check['direction']}, Enter: {should_enter}")
            
            # Get recent checks (within max age)
            recent_checks = self._get_recent_checks(tracker)
            
            # Log current state
            logger.info(f"📊 {symbol}: Recent checks: {len(recent_checks)}/{config.STABILITY_REQUIRED_CHECKS} required")
            
            # Evaluate stability
            is_stable, stability_data = self._evaluate(symbol, recent_checks)
            
            if is_stable:
                tracker["stable_signal"] = stability_data
                tracker["last_stable_time"] = time.time()
                tracker["current_checks"] = len(recent_checks)
                
                if stability_data.get("is_executable", False):
                    logger.info(f"✅ STABLE & EXECUTABLE for {symbol}: {stability_data['avg_confidence']:.1f}% (>=75%)")
                    logger.info(f"   Checks: {stability_data['num_checks']}, Direction: {stability_data['direction']}")
                    self.stats["executable_signals"] += 1
                else:
                    logger.info(f"✅ STABLE but WAITING for {symbol}: {stability_data['avg_confidence']:.1f}% (<75%)")
                    logger.info(f"   Need {75 - stability_data['avg_confidence']:.1f}% more for execution")
                    self.stats["stable_signals"] += 1
            else:
                tracker["stable_signal"] = None
                tracker["current_checks"] = len(recent_checks)
                
                # Log why not stable
                if len(recent_checks) < config.STABILITY_REQUIRED_CHECKS:
                    logger.info(f"⏳ {symbol}: Need {config.STABILITY_REQUIRED_CHECKS} checks, have {len(recent_checks)}")
                    if recent_checks:
                        oldest = recent_checks[0]["timestamp"]
                        age = time.time() - oldest
                        logger.info(f"   Oldest check: {age:.1f}s ago (max {config.STABILITY_MAX_AGE_SECONDS}s)")
                else:
                    confidences = [c.get("confidence", 0) for c in recent_checks[:config.STABILITY_REQUIRED_CHECKS]]
                    avg_conf = sum(confidences) / len(confidences) if confidences else 0
                    
                    if avg_conf < config.STABILITY_MINIMUM_THRESHOLD:
                        logger.info(f"⚠️ {symbol}: Avg conf {avg_conf:.1f}% < {config.STABILITY_MINIMUM_THRESHOLD}%")
                    else:
                        directions = [c.get("direction", "BUY") for c in recent_checks[:config.STABILITY_REQUIRED_CHECKS]]
                        if len(set(directions)) > 1:
                            logger.info(f"⚠️ {symbol}: Direction conflict: {set(directions)}")
                        elif max(confidences) - min(confidences) > config.STABILITY_MAX_DEVIATION:
                            logger.info(f"⚠️ {symbol}: Deviation too high: {min(confidences)}% - {max(confidences)}%")
            
            return is_stable, stability_data
    
    def _get_recent_checks(self, tracker: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get checks within the max age window."""
        now = time.time()
        max_age = config.STABILITY_MAX_AGE_SECONDS
        
        recent = []
        for check in reversed(tracker.get("checks", [])):
            if now - check["timestamp"] <= max_age:
                recent.append(check)
            else:
                break
        
        return recent
    
    def _evaluate(self, symbol: str, checks: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Evaluate if analysis is stable.
        - 3 checks required
        - Direction MUST match across all checks
        - Minimum 65% confidence for stability
        - Max 15% deviation
        - 75% confidence required for execution
        """
        if not checks:
            return False, None
        
        required = config.STABILITY_REQUIRED_CHECKS  # 3
        if len(checks) < required:
            return False, None
        
        recent = checks[:required]
        
        # Check 1: All must signal entry
        if not all(c.get("should_enter", False) for c in recent):
            logger.debug(f"⚠️ {symbol}: Not all checks signal entry")
            return False, None
        
        # Check 2: Direction MUST match across ALL checks
        directions = [c.get("direction", "BUY") for c in recent]
        if config.STABILITY_DIRECTION_MUST_MATCH and len(set(directions)) > 1:
            logger.debug(f"⚠️ {symbol}: Direction conflict: {set(directions)}")
            return False, None
        
        # Check 3: Confidence must be >= 65% for stability
        confidences = [c.get("confidence", 0) for c in recent]
        avg_confidence = sum(confidences) / len(confidences)
        
        if avg_confidence < config.STABILITY_MINIMUM_THRESHOLD:  # 65%
            logger.debug(f"⚠️ {symbol}: Avg confidence {avg_confidence:.1f}% < 65%")
            return False, None
        
        # Check 4: Max 15% deviation
        if max(confidences) - min(confidences) > config.STABILITY_MAX_DEVIATION:  # 15%
            logger.debug(f"⚠️ {symbol}: Confidence deviation too high")
            return False, None
        
        # All stability checks passed!
        direction = recent[0].get("direction", "BUY")
        
        # Check 5: For execution, confidence must be >= 75%
        is_executable = avg_confidence >= config.STABILITY_CONFIDENCE_THRESHOLD  # 75%
        
        stability_data = {
            "symbol": symbol,
            "direction": direction,
            "avg_confidence": round(avg_confidence, 1),
            "num_checks": len(recent),
            "all_match": True,
            "is_stable": True,
            "is_executable": is_executable,
            "time_elapsed": round(recent[-1]["timestamp"] - recent[0]["timestamp"], 1),
            "check_details": recent,
            "confidence_range": f"{min(confidences)}% - {max(confidences)}%"
        }
        
        return True, stability_data
    
    def get_stable_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stable signal if still valid."""
        with self._lock:
            if symbol not in self.tracker:
                return None
            
            tracker = self.tracker[symbol]
            signal = tracker.get("stable_signal")
            
            if not signal:
                return None
            
            if time.time() - tracker.get("last_stable_time", 0) > config.STABILITY_MAX_AGE_SECONDS:
                logger.debug(f"⏰ {symbol}: Stable signal expired")
                return None
            
            return signal
    
    def is_stable(self, symbol: str, analysis_result: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Check if analysis is stable AND executable."""
        is_stable, stability_data = self.update(symbol, analysis_result)
        
        if is_stable and stability_data:
            stable = self.get_stable_signal(symbol)
            if stable:
                return True, stable
        
        return False, None
    
    def reset(self, symbol: str):
        """Reset stability tracker for a symbol."""
        with self._lock:
            if symbol in self.tracker:
                self.tracker[symbol] = {
                    "checks": [],
                    "stable_signal": None,
                    "last_stable_time": 0,
                    "current_checks": 0,
                    "last_update": 0
                }
                self._last_check[symbol] = 0
                logger.debug(f"🔄 Reset stability for {symbol}")
    
    def get_status(self, symbol: str) -> Dict[str, Any]:
        """Get stability status for a symbol."""
        with self._lock:
            if symbol not in self.tracker:
                return {"has_stable_signal": False, "checks_count": 0}
            
            tracker = self.tracker[symbol]
            signal = tracker.get("stable_signal")
            
            return {
                "has_stable_signal": signal is not None,
                "checks_count": len(tracker.get("checks", [])),
                "current_checks": tracker.get("current_checks", 0),
                "is_executable": signal.get("is_executable", False) if signal else False,
                "avg_confidence": signal.get("avg_confidence", 0) if signal else 0,
                "last_stable_time": tracker.get("last_stable_time", 0),
                "last_update": tracker.get("last_update", 0),
                "required_checks": config.STABILITY_REQUIRED_CHECKS,
                "check_interval": config.STABILITY_CHECK_INTERVAL,
                "stable_threshold": config.STABILITY_MINIMUM_THRESHOLD,
                "executable_threshold": config.STABILITY_CONFIDENCE_THRESHOLD,
                "max_age_seconds": config.STABILITY_MAX_AGE_SECONDS
            }
    
    def get_all_status(self) -> Dict[str, Any]:
        """Get stability status for all symbols."""
        status = {}
        with self._lock:
            for symbol in self.tracker:
                status[symbol] = self.get_status(symbol)
        return status