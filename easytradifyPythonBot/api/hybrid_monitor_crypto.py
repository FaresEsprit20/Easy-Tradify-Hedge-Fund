# api/hybrid_monitor.py
# ============================================================
# MAIN ENTRY - FLASK APP & ROUTES
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

import signal
import sys
import os
import time
import logging
import json
import traceback
import threading
from datetime import datetime
from flask import Flask, request, jsonify

# Add parent directory to path so monitor package is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from monitor package
from monitor import CryptoMultiSymbolMonitor, config
from core.mt5_connector import connect_mt5, shutdown_mt5

logger = logging.getLogger(__name__)


# ============================================================
# FILE LOG -- SO A CRASH LEAVES A TRACE
# ============================================================
# This module reports everything through print(), not logging, so a logging
# FileHandler alone would capture almost nothing. The monitor died silently
# once already: the process was gone with no log file anywhere on disk and no
# terminal still holding its output, which made "is it even running?"
# unanswerable after the fact. So tee stdout/stderr to a file instead of
# converting several hundred print() calls.
#
# Appends, and stamps the PID, because debug=True runs the Werkzeug reloader:
# parent and child are two processes writing the same file.
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_PATH = os.path.join(LOG_DIR, "hybrid_monitor.log")


# The health block alone prints ~600 KB/min, so an uncapped log is ~900 MB/day
# and fills the disk during an ordinary weekend run. Rotate on size and keep a
# bounded number of files: the recent past is what a post-mortem needs.
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_BACKUPS = 3
_log_lock = threading.Lock()
# ONE handle shared by the stdout and stderr tees. It must be module-level
# rather than per-_Tee: with a handle each, a rotation on stdout would close
# the file stderr still held, and stderr logging would die silently at the
# first rotation -- losing exactly the output a post-mortem needs.
_log_handle = None


class _Tee:
    """Write to the real stream and to the shared log file. Never raise."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        try:
            self._stream.write(text)
        except Exception:
            pass
        try:
            # Both the parent and the reloader child hold a _Tee, and worker
            # threads print concurrently; rotation must not run twice at once.
            with _log_lock:
                global _log_handle
                _log_handle.write(text)
                # Unbuffered: a crash must not lose the lines explaining it.
                _log_handle.flush()
                if _log_handle.tell() >= LOG_MAX_BYTES:
                    self._rotate()
        except Exception:
            pass
        return len(text)

    @staticmethod
    def _rotate():
        """Caller holds _log_lock."""
        global _log_handle
        try:
            _log_handle.close()
        except Exception:
            pass
        try:
            oldest = f"{LOG_PATH}.{LOG_BACKUPS}"
            if os.path.exists(oldest):
                os.remove(oldest)
            for i in range(LOG_BACKUPS - 1, 0, -1):
                src, dst = f"{LOG_PATH}.{i}", f"{LOG_PATH}.{i+1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            if os.path.exists(LOG_PATH):
                os.replace(LOG_PATH, f"{LOG_PATH}.1")
        except Exception:
            pass
        # Reopen regardless: losing the log is bad, losing stdout is worse.
        _log_handle = open(LOG_PATH, "a", encoding="utf-8",
                           errors="replace", buffering=1)

    def flush(self):
        for target in (self._stream, _log_handle):
            try:
                target.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._stream.fileno()


def _start_file_log():
    global _log_handle
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        # errors="replace": the log must survive an emoji on a cp1252 box,
        # which is exactly the class of failure that has taken this process
        # down before (see the console_safe note at the top of this file).
        _log_handle = open(LOG_PATH, "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception as exc:
        print(f"⚠️ Could not open log file {LOG_PATH}: {exc}")
        return

    _log_handle.write(f"\n{'='*80}\n"
                      f"=== MONITOR START pid={os.getpid()} {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                      f"{'='*80}\n")
    _log_handle.flush()

    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # The uncaught exception that ends the process, and the one that quietly
    # kills a worker thread while the process keeps running healthy-looking.
    def _log_uncaught(exc_type, exc_value, exc_tb):
        print(f"\n💥 UNCAUGHT {exc_type.__name__}: {exc_value}")
        print("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught
    threading.excepthook = lambda args: print(
        f"\n💥 UNCAUGHT in thread {args.thread_name if hasattr(args, 'thread_name') else '?'}: "
        f"{args.exc_type.__name__}: {args.exc_value}\n"
        + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    )

    print(f"📝 Logging to {LOG_PATH}")


_start_file_log()

app = Flask(__name__)

monitor = None
monitor_lock = threading.Lock()


# ============================================================
# ROUTES
# ============================================================

@app.route('/monitor/start', methods=['POST'])
def start_monitor():
    global monitor
    with monitor_lock:
        if monitor and monitor.running:
            return jsonify({'success': False, 'message': 'Monitor already running'}), 400
        try:
            monitor = CryptoMultiSymbolMonitor()
            monitor.start_non_blocking()
            return jsonify({'success': True, 'message': 'Monitor started'}), 200
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/monitor/stop', methods=['POST'])
def stop_monitor():
    global monitor
    with monitor_lock:
        if not monitor or not monitor.running:
            return jsonify({'success': False, 'message': 'Monitor not running'}), 400
        monitor.stop()
        return jsonify({'success': True, 'message': 'Monitor stopped'}), 200


# ============================================================
# ✅ NEW: SELF-RESTART CONTROL
# ============================================================
# All of this is just a thin HTTP wrapper around monitor's own
# restart_now() / enable_auto_restart() / disable_auto_restart() /
# get_restart_status() methods (monitor_core.py). The actual restart
# mechanism (Option B — os.execv, full process re-exec) lives there;
# this file only exposes control over it. Open MT5 positions are
# unaffected by any of these — they live at the broker and are
# re-synced automatically the moment the new process comes back up.

@app.route('/monitor/restart', methods=['POST'])
def restart_monitor():
    """Gracefully stop, close MT5, and re-exec this whole process right now
    (same PID, brand new interpreter). Optional JSON body: {"reason": "..."}."""
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'manual (api)')
    triggered = monitor.restart_now(reason=reason, delay=1.0)
    if not triggered:
        return jsonify({'success': False, 'message': 'A restart is already in progress'}), 409
    return jsonify({
        'success': True,
        'message': f'Restart triggered ({reason}) — process re-execs in ~1s'
    }), 200


@app.route('/monitor/restart/auto', methods=['POST'])
def configure_auto_restart():
    """Enable/disable/configure the scheduled self-restart watchdog.
    JSON body: {"enabled": true, "interval_seconds": 3600}"""
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    data = request.get_json(silent=True) or {}
    enabled = data.get('enabled')
    interval = data.get('interval_seconds', 3600)
    if enabled is None:
        return jsonify({'success': False, 'message': "Body must include 'enabled': true/false"}), 400
    if enabled:
        monitor.enable_auto_restart(interval_seconds=interval)
    else:
        monitor.disable_auto_restart()
    return jsonify({'success': True, 'status': monitor.get_restart_status()}), 200


@app.route('/monitor/restart/status', methods=['GET'])
def get_restart_status_route():
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    return jsonify({'success': True, 'status': monitor.get_restart_status()}), 200


@app.route('/monitor/shutdown', methods=['POST'])
def shutdown_monitor():
    """Fully stop the monitor AND exit the process — no restart. Use
    /monitor/restart (or start the process again externally) to come back up."""
    global monitor

    def _delayed_exit():
        time.sleep(1.0)  # let the HTTP response above flush first
        try:
            if monitor:
                monitor.stop()
        finally:
            shutdown_mt5()
            os._exit(0)

    threading.Thread(target=_delayed_exit, name="Shutdown", daemon=True).start()
    return jsonify({
        'success': True,
        'message': 'Shutting down in ~1s. Process will exit and must be started externally.'
    }), 200


@app.route('/monitor/refresh', methods=['POST'])
def refresh_monitor():
    global monitor
    if not monitor or not monitor.running:
        return jsonify({'success': False, 'message': 'Monitor not running'}), 400
    monitor.force_refresh()
    return jsonify({'success': True, 'message': 'Refresh triggered'}), 200


@app.route('/monitor/status', methods=['GET'])
def get_status():
    global monitor
    if not monitor:
        return jsonify({'running': False}), 200
    return jsonify(monitor.get_status()), 200


@app.route('/health', methods=['GET'])
def health():
    global monitor
    return jsonify({
        'running': monitor is not None and monitor.running,
        'port': 5001,
        'webhook_port': 5001,
        'timestamp': datetime.now().isoformat()
    }), 200


@app.route('/monitor/logs', methods=['GET'])
def get_monitor_logs():
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    
    try:
        log_data = monitor._read_log()
        executions = log_data.get("executed_trades", [])
        
        symbol = request.args.get('symbol')
        if symbol:
            executions = [e for e in executions if e.get("symbol") == symbol.upper()]
        
        limit = request.args.get('limit', 100, type=int)
        executions = executions[-limit:]
        positions = log_data.get("positions", [])
        summary = log_data.get("summary", {})
        
        return jsonify({
            'success': True,
            'count': len(executions),
            'executions': executions,
            'positions': positions,
            'summary': summary,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/monitor/executions', methods=['GET'])
def get_executions():
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    
    try:
        log_data = monitor._read_log()
        executions = log_data.get("executed_trades", [])
        
        symbol = request.args.get('symbol')
        if symbol:
            executions = [e for e in executions if e.get("symbol") == symbol.upper()]
        
        limit = request.args.get('limit', 100, type=int)
        executions = executions[-limit:]
        
        return jsonify({
            'success': True,
            'count': len(executions),
            'executions': executions,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/monitor/closed_trades', methods=['GET'])
def get_closed_trades():
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    
    try:
        log_data = monitor._read_log()
        closed_trades = log_data.get("closed_trades", [])
        
        symbol = request.args.get('symbol')
        if symbol:
            closed_trades = [t for t in closed_trades if t.get("symbol") == symbol.upper()]
        
        limit = request.args.get('limit', 100, type=int)
        closed_trades = closed_trades[-limit:]
        
        return jsonify({
            'success': True,
            'count': len(closed_trades),
            'closed_trades': closed_trades,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# UI FEEDS
# ============================================================
# Added so the Angular dashboard stops inventing this data. Each one is backed
# by state the monitor already holds -- nothing here is computed for display.


@app.route('/monitor/gate-events', methods=['GET'])
def get_gate_events():
    """Recent veto/gate decisions, newest first.

    Backed by the veto engine's chronological stream, which records every check
    exactly as the decision path evaluated it. A check ABSENT from a decision
    did not run (check_all_vetos short-circuits on the first veto) and is not
    reported as a pass -- those are different facts.

    Query: limit (default 100), symbol, vetoed_only (true/false)
    """
    try:
        from core.veto_engine import get_veto_engine

        limit = int(request.args.get('limit', 100))
        symbol = request.args.get('symbol') or None
        vetoed_only = str(request.args.get('vetoed_only', '')).lower() in ('1', 'true', 'yes')

        engine = get_veto_engine()
        events = engine.get_recent_gate_events(
            limit=limit, symbol=symbol, vetoed_only=vetoed_only)

        return jsonify({
            'success': True,
            'count': len(events),
            'events': events,
            # The per-gate tally answers "which check is blocking everything?",
            # which a flat feed cannot once it is longer than a screen.
            'summary': engine.get_gate_summary(window_seconds=600.0),
        }), 200

    except Exception as e:
        logger.error(f"[/monitor/gate-events] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/watchlist', methods=['GET'])
def get_watchlist():
    """Live quotes for the symbols the monitor is tracking.

    Read straight from MT5 rather than from any cache, so a stale price cannot
    be presented as current. A symbol MT5 will not quote is omitted rather than
    returned with zeros -- a 0.00000 bid renders as a real price.
    """
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialised'}), 400

    try:
        import MetaTrader5 as mt5

        with monitor._state_lock:
            symbols = [s.symbol for s in monitor.top_symbols]
            if not symbols:
                symbols = sorted(monitor.filtered_symbols)

        limit = int(request.args.get('limit', 24))
        symbols = symbols[:max(1, limit)]

        items = []
        for symbol in symbols:
            mt5_symbol = monitor.symbol_mt5_map.get(symbol, symbol) \
                if hasattr(monitor, 'symbol_mt5_map') else symbol

            tick = mt5.symbol_info_tick(mt5_symbol)
            if not tick or not tick.bid or not tick.ask:
                continue

            # 32 M5 bars: enough for a sparkline and a session change, cheap
            # enough to fetch for two dozen symbols on every poll.
            rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M5, 0, 32)
            series = [float(r['close']) for r in rates] if rates is not None and len(rates) else []

            last = float(tick.bid)
            change_pct = 0.0
            if series and series[0]:
                change_pct = (last - series[0]) / series[0] * 100.0

            items.append({
                'symbol': symbol,
                'last': last,
                'bid': float(tick.bid),
                'ask': float(tick.ask),
                'change_pct': round(change_pct, 3),
                'series': series,
                'updated_at': time.time(),
            })

        return jsonify({'success': True, 'count': len(items), 'items': items}), 200

    except Exception as e:
        logger.error(f"[/monitor/watchlist] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/threads', methods=['GET'])
def get_threads():
    """The monitor's worker pools, as they are actually configured and running.

    Reports pool capacity and live thread counts. It does NOT claim to know
    which symbol each worker holds: the pools are plain ThreadPoolExecutors and
    nothing records that mapping, so inventing a per-worker symbol would be
    fabrication dressed as telemetry.
    """
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialised'}), 400

    try:
        import threading as _threading

        def pool_state(pool, label, configured):
            if pool is None:
                return {'name': label, 'configured': configured, 'alive': 0, 'queued': None}

            alive = sum(1 for t in _threading.enumerate()
                        if t.is_alive() and t.name.startswith(label))
            queue = getattr(pool, '_work_queue', None)
            return {
                'name': label,
                'configured': configured,
                'alive': alive,
                'queued': queue.qsize() if queue is not None else None,
            }

        pools = [
            pool_state(getattr(monitor, '_filter_pool', None), 'Filter',
                       getattr(monitor, 'FILTER_THREADS', None)),
            pool_state(getattr(monitor, '_monitor_pool', None), 'Monitor',
                       getattr(monitor, 'MONITOR_THREADS', None)),
        ]

        with monitor._state_lock:
            tracked = len(monitor.top_symbols)
            in_position = len(monitor.open_positions)

        return jsonify({
            'success': True,
            'running': bool(monitor.running),
            'pools': pools,
            'tracked_symbols': tracked,
            'open_positions': in_position,
        }), 200

    except Exception as e:
        logger.error(f"[/monitor/threads] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/top_symbols', methods=['GET'])
def get_top_symbols():
    global monitor
    if not monitor or not monitor.running:
        return jsonify({'success': False, 'message': 'Monitor is not running'}), 400
    
    with monitor._state_lock:
        top = []
        for s in monitor.top_symbols:
            top.append({
                'symbol': s.symbol,
                'confidence': s.confidence,
                'is_active': s.is_active,
                'in_position': s.in_position,
                'ticket': s.ticket,
                'exchange': s.exchange,
                'reason': s.reason,
                'entry_price': s.entry_price,
                'last_check_time': s.last_check_time,
                'stability_status': getattr(s, 'stability_status', 'UNKNOWN')
            })
        
        return jsonify({
            'success': True,
            'count': len(top),
            'top_symbols': top,
            'timestamp': datetime.now().isoformat()
        }), 200


@app.route('/monitor/filtered_symbols', methods=['GET'])
def get_filtered_symbols():
    global monitor
    if not monitor or not monitor.running:
        return jsonify({'success': False, 'message': 'Monitor is not running'}), 400
    
    with monitor._state_lock:
        return jsonify({
            'success': True,
            'count': len(monitor.filtered_symbols),
            'symbols': list(monitor.filtered_symbols),
            'permanently_excluded': list(monitor.permanently_excluded),
            'long_term_excluded': list(monitor.long_term_excluded),
            'timestamp': datetime.now().isoformat()
        }), 200


@app.route('/monitor/stability/status', methods=['GET'])
def get_stability_status():
    global monitor
    if not monitor or not monitor.running:
        return jsonify({'success': False, 'message': 'Monitor is not running'}), 400
    
    # Stability system has been removed
    return jsonify({
        'success': True,
        'message': 'Stability system has been removed',
        'stability': {'enabled': False, 'status': 'DEPRECATED'},
        'timestamp': datetime.now().isoformat()
    }), 200


@app.route('/monitor/logs/clear', methods=['POST'])
def clear_monitor_logs():
    global monitor
    if not monitor:
        return jsonify({'success': False, 'message': 'Monitor not initialized'}), 400
    
    try:
        log_data = monitor._read_log()
        log_data["executed_trades"] = []
        log_data["closed_trades"] = []
        log_data["summary"] = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit": 0.0
        }
        monitor._write_log(log_data)
        return jsonify({'success': True, 'message': 'Logs cleared'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# FIREBASE STATUS ENDPOINTS
# ============================================================

@app.route('/monitor/firebase/status', methods=['GET'])
def get_firebase_status():
    try:
        from core.firebase import get_firebase_service
        firebase = get_firebase_service()
        return jsonify({
            'success': True,
            'status': firebase.get_status() if firebase else {'connected': False},
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/firebase/trades/<trade_id>', methods=['GET'])
def get_firebase_trade(trade_id):
    try:
        from core.firebase import get_firebase_service
        firebase = get_firebase_service()
        if not firebase:
            return jsonify({'success': False, 'message': 'Firebase not available'}), 500
        
        trade = firebase.get_trade(trade_id)
        if trade:
            return jsonify({'success': True, 'trade': trade}), 200
        return jsonify({'success': False, 'message': f'Trade {trade_id} not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/firebase/trades', methods=['GET'])
def get_firebase_trades():
    try:
        from core.firebase import get_firebase_service
        firebase = get_firebase_service()
        if not firebase:
            return jsonify({'success': False, 'message': 'Firebase not available'}), 500
        
        status = request.args.get('status', 'all')
        limit = request.args.get('limit', 100, type=int)
        
        if status == 'open':
            trades = firebase.get_active_trades()
        else:
            trades = firebase.get_closed_trades(limit)
        
        return jsonify({
            'success': True,
            'count': len(trades),
            'trades': trades,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/firebase/test', methods=['GET'])
def test_firebase():
    try:
        from core.firebase import get_firebase_service
        firebase = get_firebase_service()
        if not firebase:
            return jsonify({'success': False, 'message': 'Firebase not initialized'}), 500
        
        test_data = {
            "test": True,
            "timestamp": datetime.now().isoformat(),
            "message": "Test write from monitor"
        }
        
        firebase._write_immediate("test", "test_doc", test_data, "set")
        
        return jsonify({
            'success': True,
            'message': 'Firebase test successful',
            'status': firebase.get_status()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# NEWS AND SESSION STATUS ENDPOINTS
# ============================================================

@app.route('/monitor/news/status', methods=['GET'])
def get_news_status():
    try:
        from core.news_veto import get_veto_engine
        engine = get_veto_engine()
        cache = engine._get_cache()
        return jsonify({
            'success': True,
            'status': cache.get_cache_status(),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/session/status', methods=['GET'])
def get_session_status():
    try:
        from core.session_manager import get_session_manager
        manager = get_session_manager()
        return jsonify({
            'success': True,
            'status': manager.get_cache_status(),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/news/refresh', methods=['POST'])
def refresh_news():
    try:
        from core.news_veto import get_veto_engine
        engine = get_veto_engine()
        cache = engine._get_cache()
        cache.force_refresh()
        return jsonify({'success': True, 'message': 'News cache refreshed'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/monitor/session/refresh', methods=['POST'])
def refresh_session():
    try:
        from core.session_manager import get_session_manager
        manager = get_session_manager()
        manager.force_refresh()
        return jsonify({'success': True, 'message': 'Session cache refreshed'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# ✅ WEBHOOK ROUTES - COMPLETE WITH DEBUGGING
# ============================================================

@app.route('/webhook/trade', methods=['POST'])
def webhook_trade():
    """Handle trade close webhook from MT5"""
    global monitor
    
    if not monitor:
        print("❌ Monitor not initialized")
        return jsonify({'error': 'Monitor not initialized'}), 500
    
    try:
        # Get raw data first
        raw_data = request.get_data(as_text=True)
        print("=" * 80)
        print(f"📨 RAW WEBHOOK DATA RECEIVED (len={len(raw_data)}):")
        print(raw_data[:1000] if raw_data else "(empty)")
        print("=" * 80)
        
        if not raw_data:
            print("❌ Empty webhook data received")
            return jsonify({'error': 'Empty data'}), 400
        
        try:
            data = request.get_json()
        except Exception as e:
            print(f"❌ Failed to parse JSON: {e}")
            return jsonify({'error': f'Invalid JSON: {str(e)}'}), 400
        
        if not data:
            print("❌ No JSON data parsed")
            return jsonify({'error': 'No JSON data'}), 400
            
        print(f"📨 PARSED WEBHOOK DATA:")
        print(json.dumps(data, indent=2))
        print("=" * 80)
        
        # Extract data
        symbol = data.get('symbol')
        ticket = data.get('ticket')
        close_reason = data.get('close_reason', 'SL_TP_HIT')
        
        # Convert to float with error handling
        try:
            profit = float(data.get('profit', 0))
        except (ValueError, TypeError):
            profit = 0.0
            
        try:
            price_open = float(data.get('price_open', 0))
        except (ValueError, TypeError):
            price_open = 0.0
            
        try:
            price_close = float(data.get('price_close', 0))
        except (ValueError, TypeError):
            price_close = 0.0
            
        try:
            volume = float(data.get('volume', 0))
        except (ValueError, TypeError):
            volume = 0.0
            
        try:
            sl = float(data.get('sl', 0))
        except (ValueError, TypeError):
            sl = 0.0
            
        try:
            tp = float(data.get('tp', 0))
        except (ValueError, TypeError):
            tp = 0.0
            
        close_time = data.get('time', datetime.now().isoformat())
        
        print(f"📊 EXTRACTED DATA:")
        print(f"   Symbol: {symbol}")
        print(f"   Ticket: {ticket}")
        print(f"   Close Reason: {close_reason}")
        print(f"   Profit: ${profit:.2f}")
        print(f"   Price Open: {price_open}")
        print(f"   Price Close: {price_close}")
        print(f"   Volume: {volume}")
        print(f"   SL: {sl}")
        print(f"   TP: {tp}")
        print("=" * 80)
        
        # Validate required fields
        if not symbol or not ticket:
            print(f"❌ Webhook missing symbol or ticket: {data}")
            return jsonify({'error': 'Missing symbol or ticket'}), 400
        
        # Check for zero values
        if price_open == 0 or price_close == 0 or volume == 0:
            print(f"⚠️ WEBHOOK HAS ZERO VALUES for {symbol} (Ticket: {ticket})")
            print(f"   This means the MQL5 EA is NOT sending proper data!")
            print(f"   Check your EA's SendWebhookClose function")
        
        # Process via monitor
        print(f"🔄 Processing webhook close for {symbol} (Ticket: {ticket})...")
        result = monitor.handle_webhook_close(
            symbol=symbol,
            ticket=int(ticket),
            close_reason=close_reason,
            profit=profit,
            price_open=price_open,
            price_close=price_close,
            volume=volume,
            sl=sl,
            tp=tp,
            close_time=close_time
        )
        
        if result:
            print(f"✅ Webhook processed successfully for {symbol} (Ticket: {ticket})")
            return jsonify({'status': 'success', 'message': f'Trade {ticket} closed'})
        else:
            print(f"❌ Webhook processing failed for {symbol} (Ticket: {ticket})")
            return jsonify({'status': 'error', 'message': 'Failed to close trade'}), 500
                
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/trailing', methods=['POST'])
def webhook_trailing():
    """Handle trailing stop webhook from MT5"""
    global monitor
    
    if not monitor:
        print("❌ Monitor not initialized")
        return jsonify({'error': 'Monitor not initialized'}), 500
    
    try:
        raw_data = request.get_data(as_text=True)
        print(f"📨 TRAILING WEBHOOK RAW: {raw_data[:500] if raw_data else '(empty)'}")
        
        data = request.get_json()
        if not data:
            print(f"❌ Failed to parse trailing webhook JSON")
            return jsonify({'error': 'Invalid JSON'}), 400
            
        print(f"📨 TRAILING WEBHOOK DATA: {json.dumps(data, indent=2)}")
        
        result = monitor.handle_trailing_webhook(data)
        
        if result:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error'}), 500
                
    except Exception as e:
        print(f"❌ Trailing webhook error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/health', methods=['GET'])
def webhook_health():
    """Webhook health check"""
    global monitor
    return jsonify({
        'status': 'healthy',
        'open_positions': len(monitor.open_positions) if monitor else 0,
        'running': monitor is not None and monitor.running,
        'webhook_closed_tickets': len(monitor._webhook_closed_tickets) if monitor and hasattr(monitor, '_webhook_closed_tickets') else 0,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/webhook/test', methods=['POST'])
def webhook_test():
    """Test endpoint to verify webhook data format"""
    try:
        raw_data = request.get_data(as_text=True)
        print("=" * 80)
        print(f"📨 TEST WEBHOOK RAW: {raw_data}")
        print("=" * 80)
        
        data = request.get_json()
        if not data:
            print(f"❌ Failed to parse JSON")
            return jsonify({'error': 'Invalid JSON'}), 400
            
        print(f"📨 TEST WEBHOOK PARSED:")
        print(json.dumps(data, indent=2))
        print("=" * 80)
        
        return jsonify({
            'status': 'success',
            'received': data,
            'message': 'Test webhook received successfully'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/debug', methods=['GET'])
def webhook_debug():
    """Debug endpoint to check webhook configuration"""
    global monitor
    
    return jsonify({
        'monitor_initialized': monitor is not None,
        'monitor_running': monitor.running if monitor else False,
        'webhook_closed_tickets': len(monitor._webhook_closed_tickets) if monitor and hasattr(monitor, '_webhook_closed_tickets') else 0,
        'open_positions': len(monitor.open_positions) if monitor else 0,
        'webhook_url': 'http://192.168.100.3:5001/webhook/trade',
        'trailing_url': 'http://192.168.100.3:5001/webhook/trailing',
        'test_url': 'http://192.168.100.3:5001/webhook/test',
        'timestamp': datetime.now().isoformat()
    })


# ============================================================
# MAIN
# ============================================================

def signal_handler(sig, frame):
    print("\n🛑 Shutting down...")
    global monitor
    if monitor:
        monitor.stop()
    shutdown_mt5()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("\n" + "=" * 50)
    print("🎯 HYBRID MONITOR - FINAL VERSION")
    print("=" * 50)
    print("\n📋 Configuration:")
    print(f"   Stability: REMOVED")
    print(f"   Reanalysis: Every {config.SYMBOL_REANALYSIS_INTERVAL//60} minutes")
    print(f"   Trade size: ${config.FIXED_TRADE_SIZE_USD}")
    print(f"   Risk per trade: {config.RISK_PER_TRADE*100}%")
    print("=" * 50 + "\n")
    
    print("🔌 Connecting to MT5...")
    if not connect_mt5():
        print("❌ Failed to connect to MT5")
        sys.exit(1)
    print("✅ MT5 Connected\n")
    
    # ✅ CREATE AND START MONITOR
    global monitor
    monitor = CryptoMultiSymbolMonitor()
    monitor.start_non_blocking()
    
    print("\n✅ Routes registered:")
    print("   📊 Monitor Routes:")
    print("      POST /monitor/start")
    print("      POST /monitor/stop")
    print("      POST /monitor/refresh")
    print("      GET  /monitor/status")
    print("      GET  /monitor/logs")
    print("      GET  /monitor/executions")
    print("      GET  /monitor/closed_trades")
    print("      GET  /monitor/top_symbols")
    print("      GET  /monitor/filtered_symbols")
    
    print("\n   📨 Webhook Routes:")
    print("      POST /webhook/trade     - Trade closure (MT5)")
    print("      POST /webhook/trailing  - Trailing stop")
    print("      POST /webhook/test      - Test endpoint")
    print("      GET  /webhook/health    - Health check")
    print("      GET  /webhook/debug     - Debug info")
    
    print("\n   🔥 Firebase Routes:")
    print("      GET /monitor/firebase/status")
    print("      GET /monitor/firebase/trades")
    print("      GET /monitor/firebase/trades/<trade_id>")
    print("      GET /monitor/firebase/test")
    
    print("\n   📰 News & Session Routes:")
    print("      GET /monitor/news/status")
    print("      POST /monitor/news/refresh")
    print("      GET /monitor/session/status")
    print("      POST /monitor/session/refresh")
    
    print("\n🚀 Starting API on port 5001...")
    print(f"📨 Webhook URL: http://192.168.100.3:5001/webhook/trade")
    print(f"📊 Health Check: http://192.168.100.3:5001/health")
    print(f"🧪 Test Endpoint: http://192.168.100.3:5001/webhook/test")
    print("=" * 50 + "\n")
    
    # use_reloader=False: the Werkzeug reloader forks a second process and
    # restarts it on any source change. For a long-running collection run
    # that is actively harmful -- it doubles the process tree, restarts the
    # monitor mid-session whenever a file is touched, and emits
    # 'WinError 10038 not a socket' on every teardown. Two monitor trees
    # were found running at once against the same account, each
    # independently taking the same signals (AUDCHF filled 3x in 4s,
    # EURUSD 2x in 1s) -- duplicate real trades, and duplicate rows that
    # are not independent observations.
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True,
            use_reloader=False)


if __name__ == "__main__":
    main()