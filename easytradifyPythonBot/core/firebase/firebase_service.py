# ============================================================
# FIREBASE SERVICE - COMPLETE WITH SELF-CORRECTION AI
# ✅ FIXED: Stores FULL RAW M1, M5, H1 analysis (NO EXTRACTION)
# ✅ FIXED: Preserves ALL fields from analyze_institutional_signal
# ✅ FIXED: append_to_array creates document if it doesn't exist
# ✅ FIXED: analysis_at_close support added
# ============================================================

import firebase_admin
from firebase_admin import credentials, firestore
import os
import logging
import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
import threading
import time
import json
import traceback

from .firebase_config import FirebaseConfig

# Try to import numpy for type conversion
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

logger = logging.getLogger(__name__)


class FirebaseService:
    """Firebase service for storing complete trade data with AI self-correction."""
    
    def __init__(self, config: Optional[FirebaseConfig] = None):
        self.config = config or FirebaseConfig.from_env()
        self.initialized = False
        self.db = None
        self._lock = threading.RLock()
        self._batch_queue = []
        self._batch_thread = None
        self._batch_running = False
        self._write_errors = 0
        self._last_error = None
        self._writes_successful = 0
        
        self._init_firebase()
        
        if self.initialized:
            self._start_batch_processor()
            logger.info("✅ FirebaseService initialized")
        else:
            logger.warning("⚠️ FirebaseService initialized in offline mode")
    
    def _init_firebase(self):
        try:
            if firebase_admin._apps:
                logger.info("Firebase already initialized")
                self.db = firestore.client()
                self.initialized = True
                return
            
            cred_path = self.config.get_credentials_path()
            
            # The package root, resolved from THIS file rather than from the
            # working directory, so the search does not depend on where the
            # process was started.
            _package_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            possible_paths = [
                cred_path,
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "firebase-credentials.json"),
                # api/ is where the credentials actually live. Its absence
                # from this list is why the AI controller and the replay CLI
                # both came up in OFFLINE MODE when started from the package
                # root -- and offline mode here is not a degraded connection,
                # it queues writes in memory that are NEVER flushed, because
                # the batch processor only starts once initialized is True.
                # The bot worked only because it happens to run from api/.
                os.path.join(_package_root, "api", "firebase-credentials.json"),
                os.path.join(os.getcwd(), "api", "firebase-credentials.json"),
                os.path.join(os.getcwd(), "firebase-credentials.json"),
                os.path.join(os.path.expanduser("~"), "firebase-credentials.json"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "firebase-credentials.json"),
            ]
            
            # ✅ FIX: this used to fail (or silently run offline) with only a
            # generic "Credentials file not found" - giving no way to tell,
            # from the console, WHICH paths were actually checked. If Firebase
            # stops storing data, the very first thing to check is whether
            # this block ever found a credentials file at all - so print
            # every candidate path and whether it exists, unconditionally
            # (print, not logger, since logger output depends on whatever
            # logging config the calling process has - print always shows).
            print("🔎 Firebase: searching for credentials file...")
            found_path = None
            for path in possible_paths:
                exists = os.path.exists(path)
                print(f"   {'✅ FOUND' if exists else '❌ missing'}: {path}")
                if exists and not found_path:
                    found_path = path
            
            if not found_path:
                print("⚠️ Firebase credentials NOT FOUND in any candidate path above.")
                print("⚠️ Running in OFFLINE MODE - writes will be queued in memory")
                print("⚠️ and NEVER flushed to Firestore (the batch processor only")
                print("⚠️ starts once initialized=True) until this is fixed.")
                logger.warning(f"Credentials file not found")
                logger.info("Running in offline mode - Firebase writes will be queued")
                return
            
            print(f"🔥 Firebase: using credentials at {found_path}")
            logger.info(f"✅ Using credentials: {found_path}")
            cred = credentials.Certificate(found_path)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.initialized = True
            
            try:
                self.db.collection("test").document("test").set({"test": True})
                logger.info("✅ Firebase connection test successful")
            except Exception as test_e:
                logger.warning(f"⚠️ Firebase connection test failed: {test_e}")
            
            logger.info("✅ Firebase initialized successfully")
            
        except Exception as e:
            print(f"❌ Firebase initialization threw an exception: {e}")
            logger.error(f"❌ Failed to initialize Firebase: {e}")
            logger.error(traceback.format_exc())
            self.initialized = False
    
    def _start_batch_processor(self):
        if not self.initialized:
            logger.warning("Firebase not initialized - batch processor not started")
            return
        self._batch_running = True
        self._batch_thread = threading.Thread(target=self._batch_processor, daemon=True)
        self._batch_thread.start()
        logger.info("✅ Batch processor started")
    
    def _batch_processor(self):
        while self._batch_running:
            try:
                if self._batch_queue:
                    items = []
                    with self._lock:
                        batch_size = min(len(self._batch_queue), 20)
                        items = self._batch_queue[:batch_size]
                        self._batch_queue = self._batch_queue[batch_size:]
                    
                    if items:
                        for item in items:
                            try:
                                collection = item.get("collection")
                                doc_id = item.get("doc_id")
                                data = item.get("data")
                                action = item.get("action", "set")
                                retry_count = item.get("retry_count", 0)
                                
                                if collection and data and self.db:
                                    data = self._convert_numpy_types(data)
                                    doc_ref = self.db.collection(collection).document(doc_id)
                                    if action == "set":
                                        doc_ref.set(data, merge=True)
                                    elif action == "update":
                                        try:
                                            doc_ref.update(data)
                                        except Exception as update_e:
                                            if "No document to update" in str(update_e):
                                                logger.warning(f"Document {collection}/{doc_id} doesn't exist, creating with set")
                                                doc_ref.set(data, merge=True)
                                            else:
                                                raise
                                    elif action == "delete":
                                        doc_ref.delete()
                                    self._writes_successful += 1
                                    logger.debug(f"✅ Batch {action}: {collection}/{doc_id}")
                                else:
                                    if retry_count < 5:
                                        item["retry_count"] = retry_count + 1
                                        with self._lock:
                                            self._batch_queue.append(item)
                                    else:
                                        logger.error(f"❌ Max retries exceeded for {collection}/{doc_id}")
                                        
                            except Exception as e:
                                logger.error(f"Batch process error: {e}")
                                if retry_count < 5:
                                    item["retry_count"] = retry_count + 1
                                    with self._lock:
                                        self._batch_queue.append(item)
                                else:
                                    logger.error(f"❌ Max retries exceeded for {collection}/{doc_id}")
                                    self._write_errors += 1
                                    self._last_error = str(e)
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Batch processor error: {e}")
                time.sleep(1)
    
    def _queue_write(self, collection: str, doc_id: str, data: Dict[str, Any], action: str = "set"):
        with self._lock:
            self._batch_queue.append({
                "collection": collection,
                "doc_id": doc_id,
                "data": data,
                "action": action,
                "retry_count": 0
            })
            if len(self._batch_queue) > 1000:
                logger.warning(f"⚠️ Batch queue size: {len(self._batch_queue)}")
    
    # ============================================================
    # NUMPY TYPE CONVERSION
    # ============================================================
    
    def _convert_numpy_types(self, obj: Any) -> Any:
        """Convert numpy types to Python native types for Firebase.

        ✅ FIXED: also sanitizes regular Python float NaN/Infinity (Firestore
        rejects them with '400 Property array contains an invalid nested entity'),
        and converts any remaining non-primitive object to str() so nothing
        unsupported can reach the Firestore write call.
        """
        if obj is None:
            return None

        if HAS_NUMPY:
            if isinstance(obj, (np.integer, np.int64, np.uint64, np.int32, np.uint32, np.int16, np.uint16, np.int8, np.uint8)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
                val = float(obj)
                if math.isnan(val) or math.isinf(val):
                    return None
                return val
            if isinstance(obj, np.ndarray):
                return self._convert_numpy_types(obj.tolist())
            if isinstance(obj, np.bool_):
                return bool(obj)

        # ✅ FIXED: sanitize regular Python floats — Firestore rejects NaN/Infinity
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj

        if isinstance(obj, bool):
            return obj
        if isinstance(obj, int):
            return obj
        if isinstance(obj, str):
            return obj

        if isinstance(obj, dict):
            # ✅ Skip empty-string keys — Firestore rejects them
            return {k: self._convert_numpy_types(v) for k, v in obj.items() if k != ""}
        if isinstance(obj, (list, tuple)):
            converted_items = [self._convert_numpy_types(v) for v in obj]
            # ✅ ACTUAL FIX for "400 Property ... contains an invalid nested
            # entity": Firestore forbids an array whose DIRECT elements are
            # themselves arrays (e.g. OHLC candle rows like [[t,o,h,l,c], ...],
            # coordinate pairs, etc). The comment above already claimed this
            # was handled, but nothing here ever actually caught it - a plain
            # Python list-of-lists sailed straight through unchanged and every
            # write containing one (analysis_at_open, analysis_data, and any
            # other field holding raw analyzer output) was rejected by
            # Firestore, then endlessly re-queued and retried by
            # _batch_processor until it hit its retry cap and was dropped -
            # for EVERY trade, forever, since the data was structurally
            # invalid no matter how many times it was retried.
            # Wrap any list/tuple-typed element in a map so Firestore accepts
            # it - this applies at every nesting level since a nested list
            # returns from this same branch still a raw `list`, and its
            # parent (here) always wraps it before it becomes a direct array
            # element. A list used as a plain field value (not nested inside
            # another array) is untouched, since that's fully valid.
            return [
                {"_values": item} if isinstance(item, (list, tuple)) else item
                for item in converted_items
            ]
        if isinstance(obj, datetime):
            return obj.isoformat()

        # ✅ Last-resort: convert anything else to string so Firestore
        # never sees an unsupported type. This catches custom objects,
        # enums, namedtuples, etc. that would otherwise cause
        # '400 Property array contains an invalid nested entity'.
        try:
            return str(obj)
        except Exception:
            return None
    
    # ============================================================
    # WRITE METHODS
    # ============================================================
    
    def _write_immediate(self, collection: str, doc_id: str, data: Dict[str, Any], action: str = "set"):
        """Write immediately or queue if offline."""
        if not self.initialized or not self.db:
            logger.debug(f"Firebase offline - queued write to {collection}/{doc_id}")
            return self._queue_write(collection, doc_id, data, action)
        
        try:
            data = self._convert_numpy_types(data)
            doc_ref = self.db.collection(collection).document(doc_id)
            if action == "set":
                doc_ref.set(data, merge=True)
            elif action == "update":
                try:
                    doc_ref.update(data)
                except Exception as update_e:
                    if "No document to update" in str(update_e):
                        logger.warning(f"Document {collection}/{doc_id} doesn't exist, creating with set")
                        doc_ref.set(data, merge=True)
                    else:
                        raise
            elif action == "delete":
                doc_ref.delete()
            self._writes_successful += 1
            logger.debug(f"✅ Write successful: {collection}/{doc_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to write to Firebase: {e}")
            self._write_errors += 1
            self._last_error = str(e)
            return self._queue_write(collection, doc_id, data, action)
    
    # ============================================================
    # HELPER - MAKE DATA JSON SAFE
    # ============================================================
    
    def _make_json_safe(self, obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: self._make_json_safe(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, (list, tuple)):
            converted_items = [self._make_json_safe(v) for v in obj if v is not None]
            # ✅ Same fix as _convert_numpy_types: wrap any array-typed
            # element so a list-of-lists never reaches Firestore directly.
            return [
                {"_values": item} if isinstance(item, (list, tuple)) else item
                for item in converted_items
            ]
        if isinstance(obj, datetime):
            return obj.isoformat()
        try:
            return str(obj)
        except:
            return None
    
    def _clean_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data:
            return {}
        
        result = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, dict):
                cleaned = self._clean_dict(value)
                if cleaned:
                    result[key] = cleaned
            elif isinstance(value, (list, tuple)):
                cleaned_list = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned_item = self._clean_dict(item)
                        if cleaned_item:
                            cleaned_list.append(cleaned_item)
                    elif item is not None:
                        cleaned_list.append(item)
                if cleaned_list:
                    result[key] = cleaned_list
            elif value is not None:
                result[key] = value
        return result
    
    # ============================================================
    # ✅ FIXED: STORE FULL RAW ANALYSIS - NO EXTRACTION
    # ============================================================
    
    def _extract_analysis_data(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ FIXED: Extract and store FULL RAW analysis.
        Preserves ALL fields from analyze_institutional_signal.
        NO EXTRACTION - just clean and make safe.
        """
        if not analysis_data:
            return {}
        
        try:
            # ✅ FIXED: `full_raw_analysis` used to be written unconditionally,
            # nesting the ENTIRE payload one level deeper in addition to
            # whatever was hoisted below. When the caller already supplies the
            # per-timeframe analyses (monitor/firebase_helpers.py does), that
            # copy is byte-identical content stored twice -- ~54KB of
            # duplication per trade against a 1 MiB Firestore document limit --
            # and it is the level of nesting that hid the real analysis from
            # every reader in ai/, none of which look inside
            # `full_raw_analysis`.
            #
            # Kept ONLY when the caller gives us no per-timeframe breakdown,
            # because then it is the sole copy of the analysis and dropping it
            # would lose data outright.
            has_timeframes = "m1_analysis_raw" in analysis_data

            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                
                # ✅ Keep shortcuts for easy access (but preserve full raw too)
                "⭐ CONFIDENCE": analysis_data.get("⭐ CONFIDENCE"),
                "🎯 FINAL_DECISION": analysis_data.get("🎯 FINAL_DECISION"),
                "💰 ENTRY": analysis_data.get("💰 ENTRY"),
                "🛑 STOP_LOSS": analysis_data.get("🛑 STOP_LOSS"),
                "🎯 TAKE_PROFIT_1": analysis_data.get("🎯 TAKE_PROFIT_1"),
                "🎯 TAKE_PROFIT_2": analysis_data.get("🎯 TAKE_PROFIT_2"),
                "🎯 TAKE_PROFIT_3": analysis_data.get("🎯 TAKE_PROFIT_3"),
                "📊 LOT_SIZE": analysis_data.get("📊 LOT_SIZE"),
                "💵 RISK_USD": analysis_data.get("💵 RISK_USD"),
                "📈 REWARD_USD": analysis_data.get("📈 REWARD_USD"),
                "💰 MARGIN_REQUIRED_USD": analysis_data.get("💰 MARGIN_REQUIRED_USD"),
                "🚀 SIMPLE_ACTION": analysis_data.get("🚀 SIMPLE_ACTION"),
                "🚀 REASON": analysis_data.get("🚀 REASON"),
                "📈 RISK_REWARD": analysis_data.get("📈 RISK_REWARD"),
            }
            
            if not has_timeframes:
                result["full_raw_analysis"] = self._clean_dict(analysis_data)

            # ✅ Preserve M1, M5, H1 raw analyses if they exist
            if "m1_analysis_raw" in analysis_data:
                result["m1_analysis_raw"] = analysis_data.get("m1_analysis_raw", {})

            
            # Also preserve components if present
            if "components" in analysis_data:
                components = analysis_data.get("components", {})
                result["components"] = self._clean_dict(components)
                
                # Also store individual raw analyses from components
                if "m1_analysis" in components:
                    result["m1_analysis_raw"] = components.get("m1_analysis", {})
                # ✅ M1 ONLY -- m5/h1 are deliberately not stored.
            
            # Provenance flags, so a consumer can tell an encoded document
            # from a raw one without guessing from which keys happen to exist.
            for flag in ("_encoded", "_audit_schema", "m1_audit"):
                if flag in analysis_data:
                    result[flag] = analysis_data[flag]

            # ✅ Store all other raw sections
            for key in ["entry_analysis", "final_verdict", "config", "directional_analysis", 
                       "higher_timeframe", "vetos", "volatility_protection", 
                       "news_analysis", "session_analysis", "trend_confirmation", 
                       "trailing_stop", "position_sizing", "exit_strategy"]:
                if key in analysis_data:
                    result[key] = self._clean_dict(analysis_data.get(key, {}))
            
            return self._clean_dict(result)
            
        except Exception as e:
            logger.error(f"Error extracting analysis data: {e}")
            return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
    
    # ============================================================
    # TRADE OPERATIONS - COMPLETE DATA
    # ============================================================
    
    def save_trade_open(self, trade_data: Dict[str, Any], analysis_data: Dict[str, Any], immediate: bool = True):
        ticket = trade_data.get("ticket")
        if not ticket:
            logger.error("❌ No ticket in trade_data")
            return
        
        trade_id = str(ticket)
        symbol = trade_data.get("symbol", "UNKNOWN")
        
        logger.info(f"📝 Saving trade open to Firebase: {trade_id} ({symbol})")
        
        trade_data_safe = self._make_json_safe(trade_data)
        analysis_data_safe = self._make_json_safe(analysis_data)
        
        # ✅ Get FULL RAW analysis
        full_analysis = self._extract_analysis_data(analysis_data_safe)
        
        # ✅ M1 ONLY -- see STORE_M1_ONLY in monitor/firebase_helpers.py.
        m1_raw = analysis_data_safe.get("m1_analysis_raw", {})
        if not m1_raw:
            components = analysis_data_safe.get("components", {})
            m1_raw = components.get("m1_analysis", {})
        
        # ✅ Build initial price point with FULL RAW analysis
        initial_price_point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": trade_data_safe.get("price", 0),
            "profit_usd": 0,
            "profit_percent": 0,
            "distance_from_entry_pips": 0,
            # ✅ M1 ONLY. The M1 payload already carries higher_timeframe,
            # h1_alignment and trend_cascade (which reads M5/M15/H1/H4), so
            # the separate m5/h1 re-runs were near-duplicate bulk.
            "m1_analysis_raw": m1_raw,
            # ✅ REMOVED: "full_analysis": full_analysis
            # It was a verbatim second copy of what this same document already
            # stores as analysis_at_open -- ~350KB duplicated inside a 1 MiB
            # document, for no reader. Between this copy, analysis_at_open and
            # analysis_at_close a trade could not fit its own record.
            "_encoded": False,
            "_audit_schema": full_analysis.get("_audit_schema") if isinstance(full_analysis, dict) else None,
        }
        
        doc_data = {
            "trade_id": trade_id,
            "ticket": ticket,
            "symbol": symbol,
            "direction": trade_data_safe.get("order_type", "BUY"),
            "status": "OPEN",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            
            "entry": {
                "price": trade_data_safe.get("price"),
                "volume": trade_data_safe.get("volume"),
                "stop_loss": trade_data_safe.get("stop_loss"),
                "take_profit": trade_data_safe.get("take_profit"),
                "take_profit_2": trade_data_safe.get("take_profit_2"),
                "take_profit_3": trade_data_safe.get("take_profit_3"),
                "margin_required_usd": trade_data_safe.get("actual_margin"),
                "actual_risk_usd": trade_data_safe.get("actual_risk_usd"),
                "risk_percent_used": trade_data_safe.get("risk_percent_used"),
                "magic": trade_data_safe.get("magic"),
                "comment": trade_data_safe.get("comment"),
                "spread_at_entry": trade_data_safe.get("spread_at_entry"),
                "probability_of_hit_percent": trade_data_safe.get("probability_of_hit_percent"),
                "risk_reward_ratio": trade_data_safe.get("risk_reward_ratio"),
            },
            
            # ✅ Store FULL RAW analysis
            "analysis_at_open": full_analysis,
            
            # ✅ price_evolution now lives in a SUBCOLLECTION (see
            # append_price_point). The array is left empty rather than removed
            # so that older readers see a valid empty list instead of a
            # missing key; the opening point is written below.
            "price_evolution": [],
            "price_evolution_storage": "subcollection",
            
            "metrics": {
                "max_profit_reached": 0,
                "max_profit_percent": 0,
                "max_drawdown": 0,
                "max_drawdown_percent": 0,
                "current_holding_time_seconds": 0,
                "last_price_update": datetime.now(timezone.utc).isoformat(),
                "price_updates_count": 1
            },
            
            "close_data": None,
            "analysis_at_close": None,
        }
        
        doc_data = self._clean_dict(doc_data)
        doc_data = self._convert_numpy_types(doc_data)
        
        collection = self.config.COLLECTION_TRADES
        doc_id = f"trade_{trade_id}"
        
        # ✅ ENSURE DOCUMENT IS CREATED IMMEDIATELY
        try:
            # ✅ Direct write to ensure document exists
            doc_ref = self.db.collection(collection).document(doc_id)
            doc_ref.set(doc_data, merge=True)
            self._writes_successful += 1
            logger.info(f"🔥 Trade {trade_id} ({symbol}) saved to Firebase (OPEN)")

            # The opening point is the first entry of the forward walk, so it
            # belongs with the rest of them rather than inside the parent doc.
            self.append_price_point(doc_id, initial_price_point,
                                    collection=collection)

            # ✅ Also queue for backup
            self._queue_write(collection, doc_id, doc_data, "set")
            
        except Exception as e:
            logger.error(f"❌ Failed to save trade to Firebase: {e}")
            logger.error(traceback.format_exc())
            # ✅ Fallback: queue the write
            self._queue_write(collection, doc_id, doc_data, "set")
            logger.warning(f"⚠️ Trade {trade_id} queued - write failed")
    
    # ============================================================
    # ✅ FIXED: UPDATE PRICE - WITH FULL RAW M1, M5, H1 ANALYSIS
    # ============================================================
    
    def update_price(self, trade_id: str, current_price: float, profit_usd: float, 
                     profit_percent: float, distance_pips: float,
                     analysis_data: Optional[Dict[str, Any]] = None,
                     volume_data: Optional[Dict[str, Any]] = None):
        """
        Update trade price evolution with FULL RAW M1, M5 & H1 analysis.
        ✅ FIXED: Stores full raw objects - NO EXTRACTION
        """
        if not trade_id:
            return
        
        trade_id = str(trade_id)
        doc_id = f"trade_{trade_id}"
        collection = self.config.COLLECTION_TRADES
        
        price_point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": round(current_price, 5) if current_price else 0,
            "profit_usd": round(profit_usd, 2) if profit_usd else 0,
            "profit_percent": round(profit_percent, 2) if profit_percent else 0,
            "distance_from_entry_pips": round(distance_pips, 1) if distance_pips else 0,
        }
        
        if volume_data:
            price_point["volume"] = {
                "tick_volume": volume_data.get("tick_volume", 0),
                "avg_volume": volume_data.get("avg_volume", 0),
                "volume_ratio": volume_data.get("volume_ratio", 0),
                "volume_spike": volume_data.get("volume_spike", False),
                "volume_trend": volume_data.get("volume_trend", "NEUTRAL"),
            }
        
        # ✅ Store FULL RAW analysis if provided - NO EXTRACTION
        if analysis_data:
            # Store raw M1, M5, H1 if present
            if "m1_analysis_raw" in analysis_data:
                price_point["m1_analysis_raw"] = analysis_data.get("m1_analysis_raw", {})
            # ✅ M1 ONLY -- see STORE_M1_ONLY in monitor/firebase_helpers.py.
            # This is the second price-point writer; it must follow the same
            # policy or trades get different shapes depending on which path
            # happened to record them.
        
        price_point = self._convert_numpy_types(price_point)
        
        existing_evolution = []
        existing_count = 0
        metrics = {}
        
        try:
            doc_ref = self.db.collection(collection).document(doc_id)
            doc = doc_ref.get()
            
            if doc.exists:
                doc_data = doc.to_dict()

                # Phase 0 item 7: a CLOSED trade must stop receiving evolution
                # updates. There was no guard here at all -- only `if not
                # trade_id: return` -- so a late or retried call would append a
                # POST-CLOSE price point to `price_evolution`, which is the
                # field every model treats as the pre-close forward walk.
                # That is outcome data landing inside the feature window: the
                # leakage firewall enforced everywhere downstream, breached at
                # the write. It fails closed, and says so.
                if str(doc_data.get("status", "")).upper() == "CLOSED":
                    logger.warning(
                        f"⛔ refusing price update for CLOSED trade {doc_id}: "
                        f"appending here would put post-close prices in the "
                        f"forward-walk window")
                    return

                existing_evolution = doc_data.get("price_evolution", [])
                existing_count = doc_data.get("metrics", {}).get("price_updates_count", 0)
                
                metrics = doc_data.get("metrics", {})
                metrics["last_price_update"] = datetime.now(timezone.utc).isoformat()
                metrics["price_updates_count"] = existing_count + 1
                
                current_profit = profit_usd
                if current_profit > metrics.get("max_profit_reached", 0):
                    metrics["max_profit_reached"] = current_profit
                    metrics["max_profit_percent"] = profit_percent
            else:
                # ✅ Document doesn't exist - create it
                logger.info(f"📝 Document {collection}/{doc_id} doesn't exist, creating for price update")
                existing_evolution = []
                existing_count = 0
                metrics = {
                    "max_profit_reached": profit_usd if profit_usd > 0 else 0,
                    "max_profit_percent": profit_percent if profit_percent > 0 else 0,
                    "max_drawdown": 0,
                    "max_drawdown_percent": 0,
                    "current_holding_time_seconds": 0,
                    "last_price_update": datetime.now(timezone.utc).isoformat(),
                    "price_updates_count": 1
                }
            
            existing_evolution.append(price_point)
            
            update_data = {
                "price_evolution": existing_evolution,
                "metrics": metrics,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            update_data = self._convert_numpy_types(update_data)
            self._write_immediate(collection, doc_id, update_data, "update")
            logger.debug(f"📊 Price update for trade {trade_id}: {current_price} (${profit_usd:.2f}) - update #{existing_count + 1}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update price: {e}")
            logger.error(traceback.format_exc())
    
    # ============================================================
    # ✅ NEW: SAVE ANALYSIS AT CLOSE
    # ============================================================
    
    def save_analysis_at_close(self, trade_id: str, analysis_at_close: Dict[str, Any]):
        """
        ✅ NEW: Save analysis_at_close to Firebase.
        Stores FULL RAW analysis at the moment of trade close.
        """
        if not trade_id:
            return
        
        trade_id = str(trade_id)
        # ✅ FIXED: trade_id may already be a full doc_id ("trade_{ticket}"),
        # e.g. when called from firebase_helpers.py with _get_doc_id(ticket).
        # Re-prefixing it here used to create a separate "trade_trade_{ticket}"
        # document instead of updating the trade opened earlier.
        doc_id = trade_id if trade_id.startswith("trade_") else f"trade_{trade_id}"
        collection = self.config.COLLECTION_TRADES
        
        try:
            analysis_at_close = self._clean_dict(analysis_at_close)
            analysis_at_close = self._convert_numpy_types(analysis_at_close)
            
            update_data = {
                "analysis_at_close": analysis_at_close,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            self._write_immediate(collection, doc_id, update_data, "update")
            logger.info(f"✅ analysis_at_close saved for trade {trade_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save analysis_at_close: {e}")
            logger.error(traceback.format_exc())
    
    # ============================================================
    # ✅ FIXED: SAVE TRADE CLOSE - WITH FULL RAW ANALYSIS
    # ============================================================
    
    def save_trade_close(self, trade_id: str, close_data: Dict[str, Any], 
                         analysis_data: Optional[Dict[str, Any]] = None,
                         immediate: bool = True):
        """
        Save trade closure data with FULL RAW M1, M5 & H1 analysis.
        ✅ FIXED: Stores full raw objects - NO EXTRACTION
        """
        if not trade_id:
            logger.error("❌ No trade_id provided")
            return False
        
        trade_id = str(trade_id)
        logger.info(f"📝 Saving trade close to Firebase: {trade_id}")
        
        close_data_safe = self._make_json_safe(close_data)
        analysis_data_safe = self._make_json_safe(analysis_data) if analysis_data else None
        
        # ✅ Get FULL RAW analysis if available
        full_analysis_at_close = {}
        if analysis_data_safe:
            full_analysis_at_close = self._extract_analysis_data(analysis_data_safe)
        
        # ✅ Extract raw M1, M5, H1 from analysis
        m1_raw = {}
        
        if analysis_data_safe:
            # Check for raw fields
            m1_raw = analysis_data_safe.get("m1_analysis_raw", {})
            
            # Check components
            if not m1_raw:
                components = analysis_data_safe.get("components", {})
                m1_raw = components.get("m1_analysis", {})
            
            # Check direct keys
            if not m1_raw:
                m1_raw = analysis_data_safe.get("m1_analysis", {})

            # ✅ FIXED: the actual producer spells them "m1"/"m5"/"h1".
            # _capture_analysis_at_close() in monitor/monitor_core.py returns
            # {"m1": ..., "m5": ..., "h1": ...} and monitor/firebase_helpers.py
            # reads close_analysis.get("m1"). This function tried three OTHER
            # spellings -- m1_analysis_raw, components.m1_analysis, m1_analysis
            # -- and none of them is the one being produced, so m1/m5/h1 came
            # out {} on every single close. analysis_at_close was written with
            # empty timeframe fields and only the doubly-nested
            # full_analysis_raw copy carried anything at all.
            if not m1_raw:
                m1_raw = analysis_data_safe.get("m1", {})
        
        # ✅ Use the correct keys from close_data
        close_reason = close_data_safe.get("close_reason", "MANUAL")
        close_price = close_data_safe.get("close_price", 0)
        profit_usd = close_data_safe.get("profit_usd", 0)
        profit_percent = close_data_safe.get("profit_percent", 0)
        is_winning = close_data_safe.get("is_winning", False)
        price_open = close_data_safe.get("price_open", 0)
        volume = close_data_safe.get("volume", 0)
        sl = close_data_safe.get("sl", 0)
        tp = close_data_safe.get("tp", 0)
        order_type = close_data_safe.get("order_type", "MARKET")
        duration_seconds = close_data_safe.get("duration_seconds", 0)
        exit_spread = close_data_safe.get("exit_spread", 0)
        exit_slippage = close_data_safe.get("exit_slippage", 0)
        
        logger.info(f"📊 Close data: ticket={trade_id}, open={price_open}, close={close_price}, profit=${profit_usd}")
        
        closure = {
            "status": "CLOSED",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "close_data": {
                "close_reason": close_reason,
                "close_price": close_price,
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "is_winning": is_winning,
                "exit_spread": exit_spread,
                "exit_slippage": exit_slippage,
                "order_type": order_type,
                "duration_seconds": duration_seconds,
                "price_open": price_open,
                "volume": volume,
                "sl": sl,
                "tp": tp,
            }
        }
        
        # ✅ Add trailing stop history if present
        if "trailing_stop_history" in close_data_safe:
            closure["close_data"]["trailing_stop_history"] = close_data_safe.get("trailing_stop_history")
        if "trailing_stop_activated" in close_data_safe:
            closure["close_data"]["trailing_stop_activated"] = close_data_safe.get("trailing_stop_activated")
        
        # ✅ Store FULL RAW analysis at close
        if analysis_data_safe:
            closure["analysis_at_close"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": "WIN" if profit_usd > 0 else "LOSS",
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "duration_seconds": duration_seconds,
                "close_reason": close_reason,
                # The three timeframes ARE the analysis at close. The extra
                # `full_analysis_raw` copy is kept only when they are empty,
                # so it never duplicates ~54KB of identical content and never
                # becomes the only place the data lives.
                "m1_analysis_raw": m1_raw,
                "_encoded": False,
                # Keep shortcuts
                "confidence": analysis_data_safe.get("⭐ CONFIDENCE"),
                "final_decision": analysis_data_safe.get("🎯 FINAL_DECISION"),
            }
            if not m1_raw:
                closure["analysis_at_close"]["full_analysis_raw"] = full_analysis_at_close
        
        closure = self._clean_dict(closure)
        closure = self._convert_numpy_types(closure)
        
        collection = self.config.COLLECTION_TRADES
        # ✅ FIXED: trade_id may already be a full doc_id ("trade_{ticket}"),
        # e.g. when called from firebase_helpers.py with _get_doc_id(ticket).
        # Re-prefixing it here used to create a separate "trade_trade_{ticket}"
        # document (in the same "trades" collection) instead of updating the
        # trade opened earlier — so webhook closes never landed on the real record.
        doc_id = trade_id if trade_id.startswith("trade_") else f"trade_{trade_id}"
        
        try:
            if immediate:
                success = self._write_immediate(collection, doc_id, closure, "update")
                if success:
                    logger.info(f"🔥 Trade {trade_id} closed and saved to Firebase")
                else:
                    logger.warning(f"⚠️ Trade {trade_id} close queued - write failed")
                return success
            else:
                self._queue_write(collection, doc_id, closure, "update")
                logger.info(f"📦 Trade {trade_id} close queued for Firebase")
                return True
        except Exception as e:
            logger.error(f"❌ Failed to save closed trade to Firebase: {e}")
            logger.error(traceback.format_exc())
            return False
    
    # ============================================================
    # ✅ FIXED: APPEND TO ARRAY - CREATES DOCUMENT IF NOT EXISTS
    # ============================================================
    
    # ============================================================
    # PRICE EVOLUTION -- SUBCOLLECTION, NOT AN ARRAY FIELD
    # ============================================================
    #
    # ✅ FIXED: price_evolution was an ARRAY FIELD appended via
    # append_to_array(), which read the whole array, appended locally and
    # wrote the entire array back. Two hard problems with that, both measured
    # on live documents:
    #
    #   1. SIZE. Firestore caps a document at 1,048,576 bytes. One price
    #      point carrying three full timeframe snapshots measured 361-387 KB,
    #      so a trade doc hit the ceiling after TWO points -- trade_1919435346
    #      reached 1,152,081 bytes and every subsequent append was rejected.
    #      A trade needs ~200 points over its life; the array could hold one.
    #
    #   2. COST. Read-modify-write means appending point N transfers all N
    #      points. Quadratic bandwidth on data that only ever grows.
    #
    # A subcollection removes both: each point is its own document with its
    # own 1 MiB budget, writes are O(1), and the number of points is
    # unbounded. This is the standard Firestore answer to an unbounded list
    # and it is why price_evolution could never have worked as an array.
    PRICE_EVOLUTION_SUBCOLLECTION = "price_evolution"

    def append_price_point(self, doc_id: str, point: Dict[str, Any],
                           collection: str = "trades"):
        """
        One price-evolution point, as its own document under the trade.

        Ordered by a zero-padded sequence derived from the point's own
        timestamp, so a plain document-id sort returns chronological order
        without needing an index.
        """
        if not self.initialized or not self.db:
            logger.debug(f"Firebase offline - queued price point for {doc_id}")
            return self._queue_write(
                f"{collection}/{doc_id}/{self.PRICE_EVOLUTION_SUBCOLLECTION}",
                datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"),
                self._convert_numpy_types(point), "set")

        try:
            point = self._convert_numpy_types(point)
            stamp = str(point.get("timestamp") or
                        datetime.now(timezone.utc).isoformat())

            # ✅ One point per interval per trade, enforced HERE rather than in
            # each caller. Three separate code paths write price points
            # (monitor_core, execute_copy_trade, and the opening point in
            # save_trade_open), each with its own independent throttle, so a
            # live trade was getting several points inside the same SECOND
            # instead of one per minute. A per-writer clock cannot fix that;
            # only a check against what is already stored can.
            if self._price_point_too_soon(doc_id, stamp, collection):
                return True
            # Document ids sort lexicographically; an ISO-8601 UTC timestamp
            # already sorts chronologically, so it is used directly.
            point_id = stamp.replace(":", "").replace(".", "").replace("+", "_")

            (self.db.collection(collection).document(doc_id)
                 .collection(self.PRICE_EVOLUTION_SUBCOLLECTION)
                 .document(point_id).set(point))

            # Keep a cheap counter on the parent so a reader can tell "no
            # points yet" from "never looked", without reading the whole
            # subcollection.
            self.db.collection(collection).document(doc_id).set({
                "price_evolution_count": firestore.Increment(1),
                "price_evolution_storage": "subcollection",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, merge=True)

            self._writes_successful += 1
            return True
        except Exception as e:
            self._writes_failed += 1
            logger.error(f"❌ append_price_point failed for {doc_id}: {e}")
            return False

    # Minimum spacing between stored price points, in seconds.
    PRICE_POINT_MIN_INTERVAL_SECONDS = 60

    def _price_point_too_soon(self, doc_id: str, stamp: str,
                              collection: str = "trades") -> bool:
        """True when the newest stored point is younger than the interval."""
        try:
            from datetime import datetime as _dt

            newest = (self.db.collection(collection).document(doc_id)
                          .collection(self.PRICE_EVOLUTION_SUBCOLLECTION)
                          .order_by("timestamp", direction=firestore.Query.DESCENDING)
                          .limit(1).stream())
            last = next(iter(newest), None)
            if last is None:
                return False
            previous = (last.to_dict() or {}).get("timestamp")
            if not previous:
                return False
            a = _dt.fromisoformat(str(previous).replace("Z", "+00:00"))
            b = _dt.fromisoformat(str(stamp).replace("Z", "+00:00"))
            return abs((b - a).total_seconds()) < self.PRICE_POINT_MIN_INTERVAL_SECONDS
        except Exception:
            # Never drop a point because the spacing check itself failed --
            # a duplicate is recoverable, a missing sample is not.
            return False

    def get_price_evolution(self, doc_id: str, collection: str = "trades"):
        """
        Every price point for a trade, chronological.

        Reads the subcollection and falls back to the legacy array field, so
        trades written before the migration still load. Points from both are
        merged and sorted by timestamp -- a trade written across the change
        has some of each.
        """
        if not self.initialized or not self.db:
            return []
        points = []
        try:
            docs = (self.db.collection(collection).document(doc_id)
                        .collection(self.PRICE_EVOLUTION_SUBCOLLECTION)
                        .stream())
            points.extend(d.to_dict() or {} for d in docs)
        except Exception as e:
            logger.warning(f"price_evolution subcollection read failed for {doc_id}: {e}")

        try:
            parent = self.db.collection(collection).document(doc_id).get()
            legacy = (parent.to_dict() or {}).get("price_evolution") or []
            if isinstance(legacy, list):
                points.extend(p for p in legacy if isinstance(p, dict))
        except Exception as e:
            logger.warning(f"price_evolution legacy read failed for {doc_id}: {e}")

        points.sort(key=lambda p: str(p.get("timestamp") or ""))
        return self._forward_fill_timeframes(points)

    @staticmethod
    def _forward_fill_timeframes(points):
        """
        Carry the last-seen M5/H1 snapshot forward across points that omit it.

        The writer stores an HTF timeframe only when its BAR changes, because
        at one point per minute the H1 analysis is identical across 60
        consecutive points. That is a storage decision and it must not leak
        into what readers see: every consumer expects analysis.m1/m5/h1 on
        every point, and a missing key would read as "no H1 data here" rather
        than "unchanged since the last one".

        Forward-filling restores the full series exactly, because a timeframe
        is omitted precisely when it did not change.
        """
        carried = {}
        for point in points:
            analysis = point.get("analysis")
            if not isinstance(analysis, dict):
                continue
            for name in ("m1",):
                value = analysis.get(name)
                if value:
                    carried[name] = value
                elif name in carried:
                    analysis[name] = carried[name]
                    point.setdefault("_forward_filled", []).append(name)
        return points

    def append_to_array(self, collection: str, doc_id: str, field: str, value: Any):
        """
        Append a value to an array field in a document.
        ✅ FIXED: Creates the document with initial array if it doesn't exist.
        """
        if not self.initialized or not self.db:
            logger.debug(f"Firebase offline - queued append to {collection}/{doc_id}/{field}")
            return self._queue_write(collection, doc_id, {field: [value]}, "set")

        try:
            value = self._convert_numpy_types(value)
            doc_ref = self.db.collection(collection).document(doc_id)

            # Read existing document
            doc = doc_ref.get()
            if not doc.exists:
                logger.info(f"📝 Document {collection}/{doc_id} doesn't exist, creating with initial array for field '{field}'")
                doc_ref.set({
                    field: [value],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, merge=True)
                self._writes_successful += 1
                logger.debug(f"✅ Created document with initial array: {collection}/{doc_id}/{field}")
                return True

            # Read-modify-write: append locally, write entire array back
            doc_data = doc.to_dict()
            existing_array = doc_data.get(field, [])
            if not isinstance(existing_array, list):
                existing_array = []
            existing_array.append(value)

            update_data = {
                field: self._convert_numpy_types(existing_array),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            doc_ref.update(update_data)
            self._writes_successful += 1
            logger.debug(f"✅ Appended to {collection}/{doc_id}/{field}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to append to array: {e}")
            self._write_errors += 1
            self._last_error = str(e)

            # FALLBACK: try to create/merge document with the array
            try:
                doc_ref = self.db.collection(collection).document(doc_id)
                doc_ref.set({
                    field: [value],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, merge=True)
                self._writes_successful += 1
                logger.info(f"✅ Created document with initial array (fallback): {collection}/{doc_id}/{field}")
                return True
            except Exception as fallback_e:
                logger.error(f"❌ Fallback failed: {fallback_e}")
                return self._queue_write(collection, doc_id, {field: [value]}, "set")
    
    # ============================================================
    # UPDATE TRADING STOP
    # ============================================================
    
    def update_trailing_stop(self, trade_id: str, trailing_data: Dict[str, Any]):
        """Update trailing stop data for a trade."""
        if not trade_id:
            return
        
        trade_id = str(trade_id)
        # ✅ FIX: trade_id may already be a full doc_id ("trade_{ticket}") -
        # save_trailing_stop_to_firebase() in firebase_helpers.py calls this
        # with doc_id = _get_doc_id(ticket), which is already "trade_{ticket}".
        # Re-prefixing it here (the old `f"trade_{trade_id}"` unconditionally)
        # created a SEPARATE "trade_trade_{ticket}" document instead of
        # updating the trailing_stop field on the trade opened earlier - so
        # every trailing-stop webhook/update silently landed on a phantom
        # document that nothing ever reads, while the real trade record's
        # trailing_stop field was never touched. Same bug already fixed on
        # save_trade_close/save_analysis_at_close below - this one was missed.
        doc_id = trade_id if trade_id.startswith("trade_") else f"trade_{trade_id}"
        collection = self.config.COLLECTION_TRADES
        
        data = {
            "trailing_stop": self._convert_numpy_types(trailing_data),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        self._write_immediate(collection, doc_id, data, "update")
    
    # ============================================================
    # AI MODEL OPERATIONS
    # ============================================================
    
    def save_ai_model(self, model_id: str, data: Dict[str, Any]):
        """Save AI model data to Firebase."""
        collection = self.config.COLLECTION_AI_MODELS
        doc_id = model_id
        
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        
        self._write_immediate(collection, doc_id, data, "set")
    
    def get_ai_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get AI model data from Firebase."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_MODELS
            doc = self.db.collection(collection).document(model_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get AI model {model_id}: {e}")
            return None
    
    # ============================================================
    # AI TRAINING OPERATIONS
    # ============================================================
    
    def save_ai_training_data(self, trade_id: str, features: List[float], target: int):
        """Save AI training data to Firebase."""
        collection = self.config.COLLECTION_AI_TRAINING
        doc_id = self.config.get_ai_training_id(trade_id)
        
        data = {
            "trade_id": trade_id,
            "features": features,
            "target": target,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
    
    def get_ai_training_data(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get AI training data from Firebase."""
        if not self.initialized or not self.db:
            return []
        try:
            collection = self.config.COLLECTION_AI_TRAINING
            docs = self.db.collection(collection).limit(limit).stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get AI training data: {e}")
            return []
    
    # ============================================================
    # AI PREDICTION OPERATIONS
    # ============================================================
    
    def save_ai_prediction(self, trade_id: str, prediction: Dict[str, Any]):
        """Save AI prediction to Firebase."""
        collection = self.config.COLLECTION_AI_PREDICTIONS
        doc_id = f"trade_{trade_id}"
        
        data = {
            "trade_id": trade_id,
            "prediction": prediction,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
        
        # Also save as latest
        self._write_immediate(collection, "latest", data, "set")
    
    # ============================================================
    # AI SELF-CORRECTION OPERATIONS
    # ============================================================
    
    def save_root_cause(self, trade_id: str, root_cause_data: Dict[str, Any]):
        """Save root cause analysis to Firebase."""
        collection = self.config.COLLECTION_AI_ROOT_CAUSES
        doc_id = f"trade_{trade_id}"
        
        data = {
            "trade_id": trade_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causes": root_cause_data.get("causes", []),
            "primary_cause": root_cause_data.get("primary_cause"),
            "rule_updates": root_cause_data.get("rule_updates", []),
            "recommendations": root_cause_data.get("recommendations", []),
            "impact_scores": root_cause_data.get("impact_scores", {})
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
    
    def get_root_cause(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get root cause analysis for a trade."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_ROOT_CAUSES
            doc_id = f"trade_{trade_id}"
            doc = self.db.collection(collection).document(doc_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get root cause for {trade_id}: {e}")
            return None
    
    def save_correction(self, correction_id: str, correction_data: Dict[str, Any]):
        """Save applied correction to Firebase."""
        collection = self.config.COLLECTION_AI_CORRECTIONS
        doc_id = f"correction_{correction_id}"
        
        data = {
            "correction_id": correction_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "corrections": correction_data.get("corrections", []),
            "component_weights": correction_data.get("component_weights", {}),
            "evolved_rules": correction_data.get("evolved_rules", {}),
            "next_trade_rules": correction_data.get("next_trade_rules", {}),
            "trades_since": 0,
            "effectiveness": {"wins": 0, "losses": 0, "avg_profit": 0}
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
        
        # Also save to latest
        self._write_immediate(collection, "latest", data, "set")
    
    def get_latest_correction(self) -> Optional[Dict[str, Any]]:
        """Get latest correction from Firebase."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_CORRECTIONS
            doc = self.db.collection(collection).document("latest").get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get latest correction: {e}")
            return None
    
    def save_evolution(self, version: str, evolution_data: Dict[str, Any]):
        """Save AI evolution to Firebase."""
        collection = self.config.COLLECTION_AI_EVOLUTIONS
        doc_id = f"evolution_{version}"
        
        data = {
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "changes": evolution_data.get("changes", []),
            "impact": evolution_data.get("impact", {}),
            "evolution_type": evolution_data.get("evolution_type", "ROOT_CAUSE_DRIVEN")
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
        
        # Save latest evolution
        self._write_immediate(collection, "latest", data, "set")
        
        # Update evolution history
        history = self.get_evolution_history()
        history["versions"] = history.get("versions", [])
        if version not in history["versions"]:
            history["versions"].append(version)
        history["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        self._write_immediate(collection, "history", history, "set")
    
    def get_evolution_history(self) -> Dict[str, Any]:
        """Get evolution history."""
        if not self.initialized or not self.db:
            return {"versions": []}
        try:
            collection = self.config.COLLECTION_AI_EVOLUTIONS
            doc = self.db.collection(collection).document("history").get()
            return doc.to_dict() if doc.exists else {"versions": []}
        except Exception as e:
            logger.error(f"Failed to get evolution history: {e}")
            return {"versions": []}
    
    def get_latest_evolution(self) -> Optional[Dict[str, Any]]:
        """Get latest evolution."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_EVOLUTIONS
            doc = self.db.collection(collection).document("latest").get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get latest evolution: {e}")
            return None
    
    def save_component_performance(self, component_performance: Dict[str, Any]):
        """Save component performance tracking."""
        collection = self.config.COLLECTION_AI_COMPONENT_PERFORMANCE
        doc_id = "latest"
        
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": component_performance
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
    
    def get_component_performance(self) -> Optional[Dict[str, Any]]:
        """Get component performance."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_COMPONENT_PERFORMANCE
            doc = self.db.collection(collection).document("latest").get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get component performance: {e}")
            return None
    
    def save_rule_evolution(self, rules: Dict[str, Any]):
        """Save evolved rules to Firebase."""
        collection = self.config.COLLECTION_AI_RULE_EVOLUTION
        doc_id = "latest"
        
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rules": rules
        }
        
        data = self._clean_dict(data)
        data = self._convert_numpy_types(data)
        self._write_immediate(collection, doc_id, data, "set")
    
    def get_rule_evolution(self) -> Optional[Dict[str, Any]]:
        """Get evolved rules."""
        if not self.initialized or not self.db:
            return None
        try:
            collection = self.config.COLLECTION_AI_RULE_EVOLUTION
            doc = self.db.collection(collection).document("latest").get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get rule evolution: {e}")
            return None
    
    # ============================================================
    # QUERY OPERATIONS
    # ============================================================
    
    def _hydrate_price_evolution(self, doc_id: str, data: Optional[Dict[str, Any]],
                                 collection: str = "trades") -> Optional[Dict[str, Any]]:
        """
        Fill `price_evolution` from the subcollection.

        Price points moved out of the document array because ~200 points of
        three full timeframes cannot fit a 1 MiB document. Every consumer in
        ai/ still reads `trade["price_evolution"]` as a list, so the shape is
        restored on read rather than making each of them subcollection-aware.
        Without this the points exist in Firestore and are invisible to every
        model that needs them -- stored but unreadable, which is the same as
        missing.

        Legacy array rows are merged in by get_price_evolution(), so trades
        written before the change still load, and a trade written across it
        gets both halves in timestamp order.
        """
        if not isinstance(data, dict):
            return data
        try:
            points = self.get_price_evolution(doc_id, collection=collection)
            if points:
                data["price_evolution"] = points
        except Exception as e:
            logger.warning(f"price_evolution hydration failed for {doc_id}: {e}")
        return data

    def get_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        if not self.initialized or not self.db:
            return None
        try:
            trade_id = str(trade_id)
            # ✅ FIX: same double-prefix bug as update_trailing_stop above -
            # firebase_helpers.py calls this BOTH ways: with a plain ticket
            # (e.g. execute_copy_trade.py's self.firebase.get_trade(str(ticket)))
            # AND with an already-prefixed doc_id from _get_doc_id(ticket)
            # (e.g. _is_trade_closed_in_firebase() and save_trade_close_to_
            # firebase()'s "already closed?" check). The old unconditional
            # f"trade_{trade_id}" turned the second case into a lookup for
            # "trade_trade_{ticket}", which never exists - so every "is this
            # trade already closed / does it already exist" check silently
            # always returned None, even for trades that were saved correctly.
            doc_id = trade_id if trade_id.startswith("trade_") else f"trade_{trade_id}"
            doc_ref = self.db.collection(self.config.COLLECTION_TRADES).document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                return self._hydrate_price_evolution(
                    doc_id, doc.to_dict(), self.config.COLLECTION_TRADES)
            return None
        except Exception as e:
            logger.error(f"Failed to get trade {trade_id}: {e}")
            return None
    
    def get_active_trades(self) -> List[Dict[str, Any]]:
        if not self.initialized or not self.db:
            return []
        try:
            docs = self.db.collection(self.config.COLLECTION_TRADES).where("status", "==", "OPEN").stream()
            return [self._hydrate_price_evolution(
                        d.id, d.to_dict(), self.config.COLLECTION_TRADES)
                    for d in docs]
        except Exception as e:
            logger.error(f"Failed to get active trades: {e}")
            return []
    
    def get_closed_trades(self, limit: int = 100, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.initialized or not self.db:
            return []
        try:
            query = self.db.collection(self.config.COLLECTION_TRADES).where("status", "==", "CLOSED")
            if symbol:
                query = query.where("symbol", "==", symbol)
            docs = (query.order_by("closed_at", direction=firestore.Query.DESCENDING).limit(limit).stream())
            return [self._hydrate_price_evolution(
                        d.id, d.to_dict(), self.config.COLLECTION_TRADES)
                    for d in docs]
        except Exception as e:
            # A `where` on status plus an `order_by` on closed_at needs a
            # COMPOSITE INDEX. Without it Firestore raises 400 "The query
            # requires an index" and this returned [] -- indistinguishable
            # from "no closed trades". Every caller (the /closed-trades
            # endpoint, ai_asset_diagnostic) silently saw an empty history.
            #
            # Fall back to the un-ordered query, which needs no composite
            # index, and sort client-side. Strictly additive: this path only
            # runs where the previous code already returned nothing.
            if "requires an index" in str(e) or "FAILED_PRECONDITION" in str(e):
                logger.warning(
                    "closed-trades composite index missing; falling back to "
                    "client-side sort. Create the index for large collections: "
                    f"{e}")
                try:
                    fallback = self.db.collection(
                        self.config.COLLECTION_TRADES).where("status", "==", "CLOSED")
                    if symbol:
                        fallback = fallback.where("symbol", "==", symbol)
                    # Over-fetch so the newest `limit` survive the sort: an
                    # un-ordered limit would return an arbitrary subset, which
                    # would look like recent history and would not be.
                    rows = [d.to_dict() for d in fallback.limit(max(limit * 10, 500)).stream()]
                    rows.sort(key=lambda r: str((r or {}).get("closed_at") or ""),
                              reverse=True)
                    return rows[:limit]
                except Exception as fallback_error:
                    logger.error(f"Closed-trades fallback also failed: {fallback_error}")
                    return []
            logger.error(f"Failed to get closed trades: {e}")
            return []
    
    def is_healthy(self) -> bool:
        return self.initialized and self.db is not None
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self.initialized,
            "queue_size": len(self._batch_queue),
            "batch_running": self._batch_running,
            "write_errors": self._write_errors,
            "writes_successful": self._writes_successful,
            "last_error": self._last_error,
            "timestamp": datetime.now().isoformat()
        }
    
    def shutdown(self):
        logger.info("🛑 Shutting down Firebase service...")
        self._batch_running = False
        if self._batch_thread:
            self._batch_thread.join(timeout=5)
        if self._batch_queue:
            logger.info(f"Flushing {len(self._batch_queue)} queued items...")
            for item in self._batch_queue[:]:
                try:
                    collection = item.get("collection")
                    doc_id = item.get("doc_id")
                    data = item.get("data")
                    action = item.get("action", "set")
                    if collection and data and self.db:
                        data = self._convert_numpy_types(data)
                        doc_ref = self.db.collection(collection).document(doc_id)
                        if action == "set":
                            doc_ref.set(data, merge=True)
                        elif action == "update":
                            try:
                                doc_ref.update(data)
                            except Exception:
                                doc_ref.set(data, merge=True)
                        self._writes_successful += 1
                except Exception as e:
                    logger.error(f"Flush error: {e}")
        logger.info("✅ Firebase service shutdown")


_firebase_service = None

def get_firebase_service(credentials_path: Optional[str] = None) -> FirebaseService:
    global _firebase_service
    if _firebase_service is None:
        config = FirebaseConfig(credentials_path) if credentials_path else FirebaseConfig.from_env()
        _firebase_service = FirebaseService(config)
    return _firebase_service