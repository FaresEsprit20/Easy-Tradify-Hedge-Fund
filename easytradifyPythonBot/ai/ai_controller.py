# ============================================================
# AI CONTROLLER
# ============================================================
# PORT: 5002
#
# The HTTP face of the ai/ package. 139 routes.
#
# NOTE ON THIS HEADER
# -------------------
# It previously claimed "14 GNN + 6 adversarial + 1 health = 21 endpoints"
# while the file already served well over a hundred. An index that is wrong is
# worse than no index -- it was read as the definitive list of what this
# service could do, and the research layer looked absent because of it. Rather
# than re-enumerate every route here and drift again, the groups are listed
# with their owning module; `GET /` is not served, so use the route table in
# Flask (`app.url_map`) for the authoritative list.
#
# ROUTE GROUPS
#   /health                     liveness
#   /gnn/*                      ai_gnn -- cross-asset graph (14 routes)
#   /gnn/analysis/*             ai_gnn analysis surface
#   /adversarial/*              ai_adversarial -- robustness probing
#   /adversarial/replay/*       adversarial_replay
#   /rl/*, /rl/policies/*       ai_reinforcement, rl_policies
#   /non_rl/*                   non_rl_intelligence
#   /exit_model/*               exit_model
#   /target_model/*             target_model
#   /calibration/*              calibration_model
#   /abstention/*               abstention_model
#   /replay/*                   replay engine, recorder, counterfactual, stress
#   /synthesis/*                market_synthesis
#   /ablation/*                 ablation studies
#   /clv_absorption/*           CLV / absorption
#   /trade_quality/*            trade quality scoring
#   /components/validation/*    component_validation
#   /rules/experiments/*        rule_experiments
#   /root_cause/*, /narrative/* root_cause_* , diagnosis_narrative
#   /performance/*              model_performance
#   /governance/*               model_governance -- A/B, promote, rollback
#   /verify                     whole-layer verification in one call
#
#   ADDED 2026-09-10 -- the research layer, which had no HTTP surface at all:
#   /research/*                 edge_discovery -- rule-space search, samples,
#                               measurement features, feature conditioning
#   /families/*                 strategy_families -- 23 categories, opposition
#   /repository/*               trade_repository -- the bridge every model
#                               reads stored trades through
#   /audit/*                    component_audit_360 -- the wide field scan
#   /history/*                  mt5_history + history_enrichment
#
# TRADES COME FROM MONGO
# ----------------------
# The older endpoints require `trades` in the request body and 400 without it,
# which predates trades living in MongoDB. Everything under /research,
# /families, /repository and /audit falls back to
# ai/trade_repository.load_trades() when the body omits them, so a bare POST
# analyses what has actually been collected.
#
# Full CRUD over the trades collection itself is a different service:
# api/trades_controller.py on port 5011.
# ============================================================

# Console encoding, before anything prints. This module's output carries emoji;
# on a Windows cp1252 console writing one raises UnicodeEncodeError rather than
# printing a replacement character.
#
# That is not cosmetic here -- it was fatal. initialize_services() prints a
# brain emoji, so `python ai/ai_controller.py` died with UnicodeEncodeError
# before Flask ever bound port 5002. The service could not start at all on this
# machine, while the as-built notes recorded it as "Starts and serves".
#
# It is the same defect that silently disabled the GNN for this entire project
# (ai.ai_gnn logs a brain emoji at import, the import raised, and a broad
# `except Exception` reported it as "GNN initialization failed"), and the same
# one api/hybrid_monitor.py guards against at its very first line.
import os as _os
import sys as _sys

# The project root must be on sys.path BEFORE core.console_safe can be
# imported: this file lives in ai/, so running it directly puts ai/ on the
# path and not the package root. The later sys.path.insert() below is too
# late -- the emoji print that kills startup happens at import time.
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    import core.console_safe  # noqa: F401
except Exception:
    pass

import signal
import sys
import os
import logging
import threading
from datetime import datetime
from flask import Flask, request, jsonify

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import AI components
from ai.ai_gnn import AssetGraphNeuralNetwork
from ai.ai_adversarial import AIAdversarial
from ai.ai_config import default_config

# ✅ FIXED: this module also imported ABTestingEngine from ai.ai_ab_testing and
# TradeDiffusionAugmenter from ai.ai_diffusion. Neither module exists in this
# repository, and neither name was referenced anywhere below -- they were dead
# imports that raised ModuleNotFoundError at import time, so this service could
# not start at all, on top of the empty ai_config.py that broke the whole
# package. Removed rather than stubbed: nothing used them.

from core.firebase import get_firebase_service

logger = logging.getLogger(__name__)
app = Flask(__name__)

# ============================================================
# GLOBAL INSTANCES
# ============================================================

_gnn = None
_adversarial = None
_firebase = None
_initialized = False
_lock = threading.RLock()
_config = default_config


# ============================================================
# INITIALIZATION
# ============================================================

def initialize_services():
    """Initialize GNN and Adversarial Training."""
    global _gnn, _adversarial, _firebase, _initialized
    
    with _lock:
        if _initialized:
            return True
        
        print("\n" + "=" * 60)
        print("🧠 AI CONTROLLER INITIALIZING")
        print("=" * 60)
        
        try:
            # 1. Get Firebase
            _firebase = get_firebase_service()
            if _firebase and _firebase.is_healthy():
                print("✅ Firebase connected")
            else:
                print("⚠️ Firebase not available - running without persistence")
            
            # 2. Initialize GNN (COMPLETE)
            try:
                _gnn = AssetGraphNeuralNetwork(
                    firebase_service=_firebase,
                    config=_config,
                    monitor=None
                )
                print("✅ GNN initialized successfully")
                print(f"   Assets: {len(_gnn.assets)}")
                print(f"   Enabled: {_gnn.is_enabled}")
                print(f"   Update interval: {_gnn.config.gnn_update_interval}s")
                print(f"   A/B Testing: {'ENABLED' if _gnn.ab_test['enabled'] else 'DISABLED'}")
            except Exception as e:
                print(f"❌ GNN initialization error: {e}")
                _gnn = None
            
            # 3. Initialize Adversarial (ESSENTIAL)
            try:
                _adversarial = AIAdversarial(
                    firebase_service=_firebase,
                    config=_config
                )
                print("✅ Adversarial Training initialized (ESSENTIAL MODE)")
                print(f"   Enabled: {_adversarial.adversarial_config['enabled']}")
                print(f"   Intensity: {_adversarial.adversarial_config['intensity']}")
                print(f"   Variations: {_adversarial.adversarial_config['variations_per_trade']}")
            except Exception as e:
                print(f"⚠️ Adversarial Training error: {e}")
                _adversarial = None
            
            _initialized = True
            print("=" * 60)
            print("✅ AI CONTROLLER READY ON PORT 5002")
            print(f"   GNN: {'ENABLED' if _gnn and _gnn.is_enabled else 'DISABLED'} (FULL)")
            print(f"   Adversarial: {'ENABLED' if _adversarial and _adversarial.adversarial_config['enabled'] else 'DISABLED'} (ESSENTIAL)")
            print("=" * 60 + "\n")
            
            return True
            
        except Exception as e:
            print(f"❌ AI Controller initialization error: {e}")
            return False


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    global _gnn, _adversarial, _initialized
    
    return jsonify({
        'status': 'healthy' if _initialized else 'initializing',
        'service': 'ai_controller',
        'port': 5002,
        'initialized': _initialized,
        'gnn': {
            'available': _gnn is not None,
            'enabled': _gnn.is_enabled if _gnn else False,
            'ready': _gnn.is_ready() if _gnn else False,
            'assets': len(_gnn.assets) if _gnn else 0,
        },
        'adversarial': {
            'available': _adversarial is not None,
            'enabled': _adversarial.adversarial_config['enabled'] if _adversarial else False,
        },
        'timestamp': datetime.now().isoformat()
    }), 200


# ============================================================
# ============================================================
# GNN ENDPOINTS (14 - COMPLETE)
# ============================================================
# ============================================================

# ---------- STATUS ----------

@app.route('/gnn/status', methods=['GET'])
def gnn_status():
    """Get GNN status."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        status = _gnn.get_status()
        return jsonify({
            'success': True,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- CONTEXT ----------

@app.route('/gnn/context/<symbol>', methods=['GET'])
def gnn_context(symbol):
    """
    Get GNN context for a symbol.
    Used in AI Asset Analyzer for feature extraction.
    Returns: dxy_strength, risk_sentiment, commodity_impact, sector_sentiment,
             global_confidence, trend_alignment, market_regime, 
             correlation_shift, gnn_influence, gnn_connections
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        trade_id = request.args.get('trade_id', None)
        if trade_id:
            trade_id = int(trade_id)
        
        context = _gnn.get_context(symbol.upper(), trade_id)
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'context': context,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- INSIGHTS (ALL IN ONE) ----------

@app.route('/gnn/insights/<symbol>', methods=['GET'])
def gnn_insights(symbol):
    """
    Get COMPLETE trading insights for a symbol.
    Includes: correlations, divergences, suggestions, contradictions, risk warnings.
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        analysis_direction = request.args.get('analysis_direction', None)
        if analysis_direction:
            analysis_direction = analysis_direction.upper()
            if analysis_direction not in ['BUY', 'SELL', 'HOLD']:
                analysis_direction = None
        
        insights = _gnn.get_trading_insights(symbol.upper(), analysis_direction)
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'insights': insights,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- CORRELATIONS ONLY ----------

@app.route('/gnn/correlations/<symbol>', methods=['GET'])
def gnn_correlations(symbol):
    """
    Get correlations for a symbol.
    Returns dynamic correlation matrix with confidence scores.
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        insights = _gnn.get_trading_insights(symbol.upper())
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'correlations': insights.get('correlations', []),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- DIVERGENCES ONLY ----------

@app.route('/gnn/divergences/<symbol>', methods=['GET'])
def gnn_divergences(symbol):
    """
    Check for divergences for a symbol.
    Returns: detected, type, reason, gnn_direction, price_direction
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        insights = _gnn.get_trading_insights(symbol.upper())
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'divergence': insights.get('divergence', {}),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- SUGGESTIONS ONLY ----------

@app.route('/gnn/suggestions/<symbol>', methods=['GET'])
def gnn_suggestions(symbol):
    """
    Get trade suggestions for a symbol.
    Returns: correlated symbols with BUY/SELL actions and confidence scores.
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        insights = _gnn.get_trading_insights(symbol.upper())
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'suggestions': insights.get('suggestions', []),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- CONFLICT/CONTRADICTION DETECTION ----------

@app.route('/gnn/conflict/<symbol>', methods=['GET'])
def gnn_conflict(symbol):
    """
    Check for CONTRADICTION between your analysis and GNN.
    Returns: your_analysis, gnn_says, severity, message, recommendation
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        analysis_direction = request.args.get('analysis_direction')
        if not analysis_direction:
            return jsonify({
                'success': False,
                'error': 'Missing analysis_direction parameter (BUY or SELL)'
            }), 400
        
        analysis_direction = analysis_direction.upper()
        if analysis_direction not in ['BUY', 'SELL']:
            return jsonify({
                'success': False,
                'error': 'analysis_direction must be BUY or SELL'
            }), 400
        
        insights = _gnn.get_trading_insights(symbol.upper(), analysis_direction)
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'your_analysis': analysis_direction,
            'conflict': insights.get('conflict', None),
            'gnn_insights': {
                'price_direction': insights.get('price_direction', 0),
                'gnn_direction': insights.get('gnn_direction', 0),
                'divergence_detected': insights.get('divergence', {}).get('detected', False),
                'correlations': len(insights.get('correlations', [])),
                'suggestions': len(insights.get('suggestions', [])),
            },
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- A/B TEST ----------

@app.route('/gnn/ab_test', methods=['GET'])
def gnn_ab_test():
    """Get GNN A/B test results."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        results = _gnn.get_ab_test_results()
        
        return jsonify({
            'success': True,
            'results': results,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- HEATMAP ----------

@app.route('/gnn/heatmap', methods=['GET'])
def gnn_heatmap():
    """Get correlation heatmap."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        symbols = request.args.get('symbols', '').split(',')
        if not symbols or symbols == ['']:
            symbols = None
        
        heatmap = _gnn.get_correlation_heatmap(symbols)
        
        return jsonify({
            'success': True,
            'heatmap': heatmap,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- CORRELATION CHANGES ----------

@app.route('/gnn/correlation_changes/<symbol>', methods=['GET'])
def gnn_correlation_changes(symbol):
    """
    Get correlation changes for a symbol.
    Detects significant changes in correlations (regime shifts).
    """
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        lookback = request.args.get('lookback', 10, type=int)
        changes = _gnn.detect_correlation_changes(symbol.upper(), lookback)
        
        return jsonify({
            'success': True,
            'symbol': symbol.upper(),
            'changes': changes,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- REFRESH ----------

@app.route('/gnn/refresh', methods=['POST'])
def gnn_refresh():
    """Force GNN refresh (clear cache)."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        _gnn.clear_cache()
        
        return jsonify({
            'success': True,
            'message': 'GNN cache cleared, will refresh on next update',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- RESET ----------

@app.route('/gnn/reset', methods=['POST'])
def gnn_reset():
    """Reset GNN state."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        _gnn.reset()
        
        return jsonify({
            'success': True,
            'message': 'GNN state reset',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- A/B TEST ROLLOUT ----------

@app.route('/gnn/ab_test/rollout', methods=['POST'])
def gnn_ab_test_rollout():
    """Set A/B test rollout percentage."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        rollout = data.get('rollout')
        if rollout is None:
            return jsonify({'success': False, 'error': 'rollout parameter required'}), 400
        
        _gnn.set_ab_test_rollout(float(rollout))
        
        return jsonify({
            'success': True,
            'message': f'A/B test rollout set to {float(rollout)*100:.0f}%',
            'rollout': float(rollout),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- TRACK RESULT ----------

@app.route('/gnn/track_result', methods=['POST'])
def gnn_track_result():
    """Track trade outcome for GNN A/B testing."""
    global _gnn
    
    if _gnn is None:
        return jsonify({
            'success': False,
            'error': 'GNN not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        trade_id = data.get('trade_id')
        profit = data.get('profit', 0)
        outcome = data.get('outcome', 0)  # 1 = WIN, 0 = LOSS
        gnn_used = data.get('gnn_used', False)
        
        if trade_id is None:
            return jsonify({'success': False, 'error': 'trade_id required'}), 400
        
        _gnn.track_ab_test_result(trade_id, profit, outcome, gnn_used)
        
        return jsonify({
            'success': True,
            'message': 'GNN result tracked',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# ============================================================
# ADVERSARIAL ENDPOINTS (6 - ESSENTIAL ONLY)
# ============================================================
# ============================================================

# ---------- STATUS ----------

# ============================================================
# ============================================================
# VERIFICATION ENDPOINTS
# ============================================================
# One reachable surface for "is this actually working", per component and
# combined. Every one of these is read-only and safe to poll.
# ============================================================
# ============================================================

@app.route('/adversarial/ab_test', methods=['GET'])
def adversarial_ab_test():
    """A/B state for adversarial training: control vs test, and the verdict."""
    global _adversarial
    if _adversarial is None:
        return jsonify({'error': 'Adversarial not initialized'}), 503
    return jsonify(_adversarial.get_ab_test_results()), 200


@app.route('/adversarial/ab_test/rollout', methods=['POST'])
def adversarial_set_rollout():
    """Manually override the adversarial rollout share."""
    global _adversarial
    if _adversarial is None:
        return jsonify({'error': 'Adversarial not initialized'}), 503

    payload = request.get_json(silent=True) or {}
    if 'rollout' not in payload:
        return jsonify({'error': "Missing 'rollout'"}), 400
    try:
        rollout = float(payload['rollout'])
    except (TypeError, ValueError):
        return jsonify({'error': "'rollout' must be a number"}), 400
    if not 0.0 <= rollout <= 1.0:
        return jsonify({'error': "'rollout' must be between 0 and 1"}), 400

    _adversarial.set_ab_test_rollout(rollout)
    return jsonify(_adversarial.get_ab_test_results()), 200


@app.route('/adversarial/ab_test/track', methods=['POST'])
def adversarial_track_result():
    """Record a settled trade into its A/B arm."""
    global _adversarial
    if _adversarial is None:
        return jsonify({'error': 'Adversarial not initialized'}), 503

    payload = request.get_json(silent=True) or {}
    if 'trade_id' not in payload or 'outcome' not in payload:
        return jsonify({'error': "Missing 'trade_id' or 'outcome'"}), 400

    _adversarial.track_ab_test_result(
        trade_id=payload['trade_id'],
        profit=payload.get('profit', 0.0),
        outcome=int(payload['outcome']),
        used_adversarial=payload.get('used_adversarial'),
    )
    return jsonify(_adversarial.get_ab_test_results()), 200


@app.route('/rl/status', methods=['GET'])
def rl_status():
    from ai import ai_reinforcement
    return jsonify(ai_reinforcement.get_status()), 200


@app.route('/rl/self_check', methods=['POST'])
def rl_self_check():
    """Prove the trade -> snapshot path on a supplied batch of trades."""
    from ai import ai_reinforcement
    payload = request.get_json(silent=True) or {}
    report = ai_reinforcement.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/non_rl/status', methods=['GET'])
def non_rl_status():
    from ai.non_rl_intelligence import NonRLIntelligenceController
    return jsonify(NonRLIntelligenceController().get_status()), 200


@app.route('/non_rl/self_check', methods=['POST'])
def non_rl_self_check():
    """Prove the trade -> DecisionRecord path, including the leakage check."""
    from ai.non_rl_intelligence import NonRLIntelligenceController
    payload = request.get_json(silent=True) or {}
    report = NonRLIntelligenceController().self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/exit_model/status', methods=['GET'])
def exit_model_status():
    from ai import exit_model
    return jsonify(exit_model.get_status()), 200


@app.route('/exit_model/self_check', methods=['POST'])
def exit_model_self_check():
    """Prove sample construction and group-disjoint splitting on real trades."""
    from ai import exit_model
    payload = request.get_json(silent=True) or {}
    report = exit_model.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/exit_model/train', methods=['POST'])
def exit_model_train():
    """
    Train and validate. Returns the promotion verdict, never a promoted model
    by default -- `rejected_because` is the useful output when it fails.
    """
    from ai import exit_model
    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    report = exit_model.train_and_validate(trades)
    report.pop('model', None)   # not JSON-serialisable; persist via save()
    return jsonify(report), 200


@app.route('/target_model/status', methods=['GET'])
def target_model_status():
    from ai import target_model
    return jsonify(target_model.get_status()), 200


@app.route('/target_model/self_check', methods=['POST'])
def target_model_self_check():
    from ai import target_model
    payload = request.get_json(silent=True) or {}
    report = target_model.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/target_model/train', methods=['POST'])
def target_model_train():
    from ai import target_model
    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    report = target_model.train_and_validate(trades)
    report.pop('model', None)
    return jsonify(report), 200


@app.route('/calibration/status', methods=['GET'])
def calibration_status():
    from ai import calibration_model
    return jsonify(calibration_model.get_status()), 200


@app.route('/calibration/self_check', methods=['POST'])
def calibration_self_check():
    """Also reports whether the stated probability is worth calibrating."""
    from ai import calibration_model
    payload = request.get_json(silent=True) or {}
    report = calibration_model.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/calibration/train', methods=['POST'])
def calibration_train():
    from ai import calibration_model
    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    report = calibration_model.train_and_validate(trades)
    report.pop('model', None)
    return jsonify(report), 200


@app.route('/abstention/status', methods=['GET'])
def abstention_status():
    from ai import abstention_model
    return jsonify(abstention_model.get_status()), 200


@app.route('/abstention/self_check', methods=['POST'])
def abstention_self_check():
    """Reports which pre-entry conditions are actually populated."""
    from ai import abstention_model
    payload = request.get_json(silent=True) or {}
    report = abstention_model.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/abstention/train', methods=['POST'])
def abstention_train():
    """Discover decline rules and report whether they survive out of sample."""
    from ai import abstention_model
    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    report = abstention_model.train_and_validate(trades)
    report.pop('rules_model', None)
    return jsonify(report), 200


@app.route('/replay/phase1/status', methods=['GET'])
def replay_phase1_status():
    from ai import aireplay
    return jsonify(aireplay.get_status()), 200


@app.route('/replay/phase1/self_check', methods=['POST'])
def replay_phase1_self_check():
    """Prove extraction, the temporal firewall and immutability detection."""
    from ai import aireplay
    payload = request.get_json(silent=True) or {}
    report = aireplay.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/replay/phase1/extract', methods=['POST'])
def replay_phase1_extract():
    """Stored trades -> canonical records, with their leakage reports."""
    from ai import aireplay
    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    records = aireplay.extract_replay_records(trades)
    return jsonify({
        'schema_version': aireplay.SCHEMA_VERSION,
        'extracted': len(records),
        'records': [{
            'trade_id': r.trade_id,
            'leakage': r.leakage_report(),
            'genome_sections': r.genome.market_state.populated_sections() if r.genome else [],
            'snapshots': [s.event_type.value for s in r.decision_snapshots],
            'fingerprint': aireplay.snapshot_fingerprint(r),
        } for r in records],
    }), 200


@app.route('/synthesis/status', methods=['GET'])
def synthesis_status():
    from ai import market_synthesis
    return jsonify(market_synthesis.get_status()), 200


@app.route('/synthesis/self_check', methods=['POST'])
def synthesis_self_check():
    from ai import market_synthesis
    payload = request.get_json(silent=True) or {}
    report = market_synthesis.self_check(payload.get('trades') or [])
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/synthesis/synthesise', methods=['POST'])
def synthesis_synthesise():
    """Canonical market synthesis per trade: state, conflicts, uncertainty."""
    from ai import aireplay
    from ai import market_synthesis

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    results = []
    for record in aireplay.extract_replay_records(trades):
        synthesis = market_synthesis.synthesise_trade(record)
        results.append({
            'trade_id': record.trade_id,
            'hierarchy': synthesis.hierarchy,
            'conflicts': [c.to_dict() for c in synthesis.conflicts],
            'uncertainty': synthesis.uncertainty,
            'multi_timeframe': synthesis.multi_timeframe,
            'unavailable_inputs': synthesis.unavailable_inputs(),
            'synthesis_hash': synthesis.synthesis_hash(),
        })
    return jsonify({
        'version': market_synthesis.MARKET_SYNTHESIS_VERSION,
        'synthesised': len(results),
        'results': results,
    }), 200


@app.route('/replay/recorder/status', methods=['GET'])
def replay_recorder_status():
    """Live decision-snapshot recorder: counts, and the safety contract."""
    from ai.aireplay import get_recorder
    return jsonify(get_recorder().get_status()), 200


@app.route('/replay/status', methods=['GET'])
def replay_engine_status():
    from ai.aireplay import replay_engine
    return jsonify(replay_engine.get_status()), 200


@app.route('/replay/run', methods=['POST'])
def replay_run():
    """Replay stored trades: timeline, the four firsts, and attribution."""
    from ai import aireplay
    from ai.aireplay import replay_engine

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    records = aireplay.extract_replay_records(trades)
    results = replay_engine.replay_trades(records)
    return jsonify({
        'replay_version': replay_engine.REPLAY_ENGINE_VERSION,
        'replayed': len(results),
        'results': [{
            'trade_id': r['trade_id'],
            'events': r['events'],
            'divergences': r['divergences'],
            'attribution': r['attribution'],
            'outcome': r['outcome'],
        } for r in results],
    }), 200


@app.route('/replay/counterfactual/status', methods=['GET'])
def counterfactual_status():
    from ai.aireplay import counterfactual
    return jsonify(counterfactual.get_status()), 200


@app.route('/replay/counterfactual', methods=['POST'])
def replay_counterfactual():
    """Branch stored trades: alternative entries, stops and exits."""
    from ai import aireplay
    from ai.aireplay import counterfactual

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    records = aireplay.extract_replay_records(trades)
    results = [counterfactual.branch_trade(r) for r in records]
    return jsonify({
        'version': counterfactual.COUNTERFACTUAL_VERSION,
        'branched': sum(1 for r in results if r.get('branches')),
        'aggregate': counterfactual.aggregate_branches(results),
        'results': results,
    }), 200


@app.route('/replay/consistency', methods=['POST'])
def replay_consistency():
    """Do the three trade simulators agree on the same historical trades?"""
    from ai import aireplay
    from ai.aireplay import consistency

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': "Missing 'trades'"}), 400

    records = aireplay.extract_replay_records(trades)
    return jsonify(consistency.consistency_report(records)), 200


# ============================================================
# PHASE 5, 6 AND 7 ENDPOINTS
# ============================================================


@app.route('/ablation/status', methods=['GET'])
def ablation_status():
    """Ablation target, noise band, and what a negative contribution means."""
    from ai import ablation
    return jsonify(ablation.get_status()), 200


@app.route('/ablation/self_check', methods=['POST'])
def ablation_self_check():
    from ai import ablation
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify(ablation.self_check(trades)), 200


@app.route('/ablation/study', methods=['POST'])
def ablation_study_endpoint():
    """
    What each analysis section contributes (phase 3 item 9).

    A NEGATIVE contribution is the finding worth acting on: the model did
    better without that section. Systems accumulate inputs and almost never
    remove them.
    """
    from ai import ablation

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400
    try:
        max_sections = payload.get('max_sections')
        max_sections = int(max_sections) if max_sections is not None else None
        subsets = int(payload.get('random_subsets', 8))
    except (TypeError, ValueError):
        return jsonify({'error': 'max_sections and random_subsets must be integers'}), 400
    return jsonify(ablation.ablation_study(trades, max_sections, subsets)), 200


@app.route('/clv_absorption/status', methods=['GET'])
def clv_absorption_status():
    """CLV formula, thresholds, and the zero-range policy (phase 2 item 2)."""
    from core import clv_absorption
    return jsonify(clv_absorption.get_status()), 200


@app.route('/clv_absorption/self_check', methods=['POST'])
def clv_absorption_self_check():
    from core import clv_absorption
    bars = (request.get_json(silent=True) or {}).get('bars') or []
    return jsonify(clv_absorption.self_check(bars)), 200


@app.route('/clv_absorption/analyze', methods=['POST'])
def clv_absorption_analyze():
    """
    Where participation and movement disagreed.

    Absorption needs BOTH high participation and a contained range; either
    alone is unremarkable.
    """
    from core import clv_absorption

    payload = request.get_json(silent=True) or {}
    bars = payload.get('bars') or []
    if not bars:
        return jsonify({'error': 'bars are required'}), 400
    try:
        lookback = int(payload.get('lookback', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'lookback must be an integer'}), 400
    return jsonify(clv_absorption.analyze_clv_absorption(bars, lookback)), 200


@app.route('/trade_quality/status', methods=['GET'])
def trade_quality_status():
    """Why this is an expectancy, not a point score (phase 2 item 7)."""
    from ai import trade_quality
    return jsonify(trade_quality.get_status()), 200


@app.route('/trade_quality/self_check', methods=['POST'])
def trade_quality_self_check():
    from ai import trade_quality
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify(trade_quality.self_check(trades)), 200


@app.route('/trade_quality/assess', methods=['POST'])
def trade_quality_assess():
    """
    Assess one trade, or refuse to.

    The verdict is E[R] = p x reward - (1 - p) x 1R. Gates can only REFUSE;
    no dimension can promote a trade that has no expectancy, which is the
    property readme 26.20 demands and a point system violates.
    """
    from ai import trade_quality

    payload = request.get_json(silent=True) or {}
    trade = payload.get('trade')
    if not isinstance(trade, dict):
        return jsonify({'error': 'a trade object is required'}), 400
    informative = payload.get('probability_is_informative')
    return jsonify(trade_quality.assess_trade(trade, None, informative).to_dict()), 200


@app.route('/gnn/analysis/status', methods=['GET'])
def gnn_analysis_status():
    """Embedding dimensions, conflict threshold, and the validation standard."""
    from ai import gnn_analysis
    return jsonify(gnn_analysis.get_status()), 200


@app.route('/gnn/analysis/self_check', methods=['POST'])
def gnn_analysis_self_check():
    from ai import gnn_analysis
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify(gnn_analysis.self_check(trades)), 200


@app.route('/gnn/embeddings', methods=['GET'])
def gnn_embeddings():
    """
    Per-asset embeddings from the live graph (phase 5 item 2).

    Returns an empty mapping when no graph has been built -- never a vector of
    zeros, which would be a claim that every dimension measured zero.
    """
    global _gnn
    from ai import ai_gnn, gnn_analysis

    source = _gnn or ai_gnn._build_gnn()
    embeddings = gnn_analysis.node_embeddings(source)
    return jsonify({
        'dimensions': list(gnn_analysis.EMBEDDING_DIMENSIONS),
        'assets': len(embeddings),
        'embeddings': embeddings,
        'graph_built': bool(embeddings),
    }), 200


@app.route('/gnn/conflicts', methods=['GET'])
def gnn_conflicts():
    """
    Assets moving against their correlated peers (phase 5 item 5).

    The information is in disagreement: a peer group moving together tells you
    what one chart already told you.
    """
    global _gnn
    from ai import ai_gnn, gnn_analysis

    source = _gnn or ai_gnn._build_gnn()
    return jsonify(gnn_analysis.detect_conflicts(source)), 200


@app.route('/gnn/validate', methods=['POST'])
def gnn_validate():
    """
    Does GNN context at entry predict anything, out of sample (item 7)?

    Built expecting to refuse: direction entropy measured 1.0000, and a graph
    over coin-flip instruments has no obvious reason to predict outcomes.
    """
    from ai import gnn_analysis

    trades = (request.get_json(silent=True) or {}).get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400
    return jsonify(gnn_analysis.validate_out_of_sample(trades)), 200


@app.route('/adversarial/replay/status', methods=['GET'])
def adversarial_replay_status():
    from ai import adversarial_replay
    return jsonify(adversarial_replay.get_status()), 200


@app.route('/adversarial/replay/self_check', methods=['POST'])
def adversarial_replay_self_check():
    from ai import adversarial_replay
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify(adversarial_replay.self_check(trades)), 200


@app.route('/adversarial/replay/probe', methods=['POST'])
def adversarial_replay_probe():
    """
    Does the DIAGNOSIS survive perturbation, not just the model (phase 6.6)?

    An attribution that flips when an unrelated field is nudged was reading
    noise, and every recommendation built on it inherits that.
    """
    from ai import adversarial_replay

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400
    variations = payload.get('variations', 6)
    try:
        variations = max(1, min(20, int(variations)))
    except (TypeError, ValueError):
        return jsonify({'error': 'variations must be an integer'}), 400
    return jsonify(adversarial_replay.probe_trades(trades, variations)), 200


@app.route('/rl/policies/status', methods=['GET'])
def rl_policies_status():
    """Policy class, sizing limits, and why these are not deep policies."""
    from ai import rl_policies
    return jsonify(rl_policies.get_status()), 200


@app.route('/rl/policies/self_check', methods=['POST'])
def rl_policies_self_check():
    from ai import rl_policies
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    report = rl_policies.self_check(trades)
    return jsonify(report), 200


@app.route('/rl/policies/train', methods=['POST'])
def rl_policies_train():
    """
    Train a management or exit policy (phase 7 items 2 and 3).

    Gated on an expectancy delta in R that exceeds the 95th percentile of an
    increment-permutation control which includes the parameter search itself.
    """
    from ai import rl_policies
    from ai.aireplay.data_engine import extract_replay_records

    payload = request.get_json(silent=True) or {}
    kind = payload.get('kind', 'management')
    if kind not in ('management', 'exit'):
        return jsonify({'error': "kind must be 'management' or 'exit'"}), 400
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400

    records = extract_replay_records(trades)
    if not records:
        return jsonify({'error': 'no trade could be canonicalised'}), 422
    return jsonify(rl_policies.train_policy(records, kind)), 200


@app.route('/rl/policies/size', methods=['POST'])
def rl_policies_size():
    """
    Bounded position size (phase 7 item 4).

    Every clamp is reported rather than silently applied: a size cut from 1.4%
    to 1.0% and reported only as "1.0%" hides that the model wanted something
    the limits refused.
    """
    from ai.rl_policies import SizingLimits, bounded_size

    payload = request.get_json(silent=True) or {}
    if 'base_risk_percent' not in payload:
        return jsonify({'error': 'base_risk_percent is required'}), 400
    try:
        base = float(payload['base_risk_percent'])
        multiplier = float(payload.get('multiplier', 1.0))
        open_risk = float(payload.get('open_risk_percent', 0.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'numeric fields must be numbers'}), 400

    overrides = payload.get('limits') or {}
    limits = SizingLimits(**{k: float(v) for k, v in overrides.items()
                             if hasattr(SizingLimits, k)}) if overrides \
        else SizingLimits()
    return jsonify(bounded_size(base, multiplier, open_risk, limits)), 200


@app.route('/rl/policies/deploy', methods=['POST'])
def rl_policies_deploy():
    """
    Hand a trained policy to governance (phase 7 item 8).

    Deployment means versioned, gated and behind a 10% rollout -- never
    "switch every trade to the new policy".
    """
    from ai import rl_policies

    payload = request.get_json(silent=True) or {}
    name = payload.get('name')
    report = payload.get('report')
    if not name or not isinstance(report, dict):
        return jsonify({'error': 'name and report are required'}), 400
    return jsonify(rl_policies.deploy(name, report)), 200


@app.route('/components/validation/status', methods=['GET'])
def component_validation_status():
    """How a component earns the right to vote, and the prior measurement."""
    from ai import component_validation
    return jsonify(component_validation.get_status()), 200


@app.route('/components/validation/self_check', methods=['POST'])
def component_validation_self_check():
    """Proves the method rejects noise and still finds a planted signal."""
    from ai import component_validation
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    report = component_validation.self_check(trades)
    return jsonify(report), (200 if report.get('ok') else 500)


@app.route('/components/validation/measure', methods=['POST'])
def component_validation_measure():
    """
    Out-of-sample discrimination for every component that votes.

    A hold rate near 0.5 is what NO discrimination looks like -- the training
    direction survived on half the components and reversed on the other half.
    """
    from ai import component_validation

    trades = (request.get_json(silent=True) or {}).get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400
    return jsonify(component_validation.validate(trades)), 200


@app.route('/components/validation/weights', methods=['POST'])
def component_validation_weights():
    """
    The weight each component has earned: 1.0 validated, 0.0 not proven.

    Weight 0 is not deletion -- the component still computes and can be
    re-validated once there are enough trades to settle it.
    """
    from ai import component_validation

    trades = (request.get_json(silent=True) or {}).get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400
    return jsonify(component_validation.recommended_weights(trades)), 200


@app.route('/rules/experiments', methods=['GET'])
def rule_experiments_status():
    """Which rule experiments exist, and the evidence that motivated them."""
    from ai import rule_experiments
    return jsonify(rule_experiments.get_status()), 200


@app.route('/rules/experiments/self_check', methods=['POST'])
def rule_experiments_self_check():
    """Proves the experiment fails safe and refuses premature recommendations."""
    from ai import rule_experiments
    report = rule_experiments.self_check()
    return jsonify(report), (200 if report.get('ok') else 500)


@app.route('/rules/experiments/<veto>', methods=['GET'])
def rule_experiment_results(veto):
    """The governed A/B verdict for one rule experiment."""
    from ai import rule_experiments
    payload = rule_experiments.results(veto)
    return jsonify(payload), (404 if payload.get('error') else 200)


@app.route('/rules/experiments/<veto>/recommendation', methods=['GET'])
def rule_experiment_recommendation(veto):
    """
    The point of the exercise: what to change in the rule base.

    Speaks only when the verdict is actionable -- significant AND
    directionally clear. Otherwise NO CHANGE, with the reason, because the
    default in a live trading system is to change nothing.
    """
    from ai import rule_experiments
    payload = rule_experiments.recommended_change(veto)
    return jsonify(payload), (404 if payload.get('error') else 200)


@app.route('/rules/experiments/<veto>/track', methods=['POST'])
def rule_experiment_track(veto):
    """Record one settled trade into its arm."""
    from ai import rule_experiments

    payload = request.get_json(silent=True) or {}
    if 'unit_id' not in payload or 'outcome' not in payload:
        return jsonify({'error': 'unit_id and outcome are required'}), 400
    result = rule_experiments.record_outcome(
        veto, payload['unit_id'], payload.get('profit', 0.0),
        payload['outcome'])
    return jsonify({'tracked': result,
                    'results': rule_experiments.results(veto)}), 200


@app.route('/replay/live_recording/status', methods=['GET'])
def live_recording_status():
    """
    Whether the pre-trade timeline is being recorded, and the guarantees.

    This is the one part of AI_MarketReplay that runs between a signal and a
    real order, so the status names what it will not do as much as what it
    does.
    """
    from ai.aireplay import live_recording
    return jsonify(live_recording.get_status()), 200


@app.route('/replay/live_recording/self_check', methods=['POST'])
def live_recording_self_check():
    """Proves OFF-by-default, no mutation, and no fictional trades."""
    from ai.aireplay import live_recording
    report = live_recording.self_check()
    return jsonify(report), (200 if report.get('ok') else 500)


@app.route('/replay/stress/status', methods=['GET'])
def replay_stress_status():
    """Stress families, magnitudes, and the simulation disclaimer."""
    from ai.aireplay import stress
    return jsonify(stress.get_status()), 200


@app.route('/replay/stress/self_check', methods=['POST'])
def replay_stress_self_check():
    """Proves stress stresses, harm is monotone, and the baseline is untouched."""
    from ai.aireplay import stress
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify(stress.self_check(trades)), 200


@app.route('/replay/stress', methods=['POST'])
def replay_stress():
    """
    How much margin these decisions had.

    Every scenario here MODIFIES the recorded prices, so unlike counterfactual
    branching none of it is historical truth. The response says so on every
    level, because quoting a stressed result beside a counterfactual one as
    "what would have happened" is how fiction acquires the authority of
    measurement.
    """
    from ai.aireplay import stress
    from ai.aireplay.data_engine import extract_replay_records

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []
    if not trades:
        return jsonify({'error': 'trades are required'}), 400

    records = extract_replay_records(trades)
    if not records:
        return jsonify({'error': 'no trade could be canonicalised'}), 422

    results = stress.stress_trades(records)
    return jsonify({
        'aggregate': stress.aggregate_stress(results),
        'per_trade': results[:50],
        'is_simulation': True,
    }), 200


# ============================================================
# ROOT CAUSE, NARRATIVE AND PERFORMANCE ENDPOINTS
# ============================================================
#
# Root cause had no HTTP surface at all, which is part of why it went so long
# without anyone noticing it produced nothing: 1,082 lines with no endpoint,
# no test file, and no self_check meant there was no way to ask it whether it
# worked short of reading it.


@app.route('/root_cause/status', methods=['GET'])
def root_cause_status():
    """Policy and capability of the root cause layer."""
    from ai import root_cause_adapter, root_cause_analyzers, root_cause_trackers
    return jsonify({
        'analyzer': root_cause_analyzers.get_status(),
        'tracker': root_cause_trackers.get_status(),
        'adapter': root_cause_adapter.get_status(),
    }), 200


@app.route('/root_cause/self_check', methods=['POST'])
def root_cause_self_check():
    """Prove the analyzer reads real evidence -- and refuses without it."""
    from ai import root_cause_adapter, root_cause_analyzers, root_cause_trackers
    trades = (request.get_json(silent=True) or {}).get('trades') or []
    return jsonify({
        'analyzer': root_cause_analyzers.self_check(trades),
        'tracker': root_cause_trackers.self_check(trades),
        'adapter': root_cause_adapter.self_check(trades),
    }), 200


@app.route('/root_cause/analyze', methods=['POST'])
def root_cause_analyze():
    """
    Diagnose one stored trade, end to end.

    Accepts the raw Firebase trade. The adapter builds the evidence bundle
    from replay artifacts; nothing here asks the caller to pre-assemble it,
    which was the gap that left this subsystem inert.
    """
    from ai.root_cause_adapter import analyze_trade, to_analysis_input

    payload = request.get_json(silent=True) or {}
    trade = payload.get('trade')
    if not isinstance(trade, dict):
        return jsonify({'error': 'a trade object is required'}), 400

    bundle = to_analysis_input(trade)
    if bundle.get('unusable'):
        return jsonify({'error': bundle['unusable']}), 422

    result = analyze_trade(trade)
    return jsonify({
        'result': result.to_dict() if hasattr(result, 'to_dict') else str(result),
        'report': result.report,
    }), 200


@app.route('/root_cause/coverage', methods=['POST'])
def root_cause_coverage():
    """
    Which evidence sections a given trade actually supports.

    Exists so "full data coverage" is a measurement rather than a claim: an
    empty section here means the stored trade had nothing in it, which is a
    different fact from the adapter having forgotten to map it.
    """
    from ai.root_cause_adapter import coverage

    trade = (request.get_json(silent=True) or {}).get('trade')
    if not isinstance(trade, dict):
        return jsonify({'error': 'a trade object is required'}), 400
    return jsonify(coverage(trade)), 200


@app.route('/root_cause/narrative', methods=['POST'])
def root_cause_narrative():
    """
    The diagnosis in plain language, with every claim carrying its evidence.

    `format=text` returns the rendered report; the default returns the
    structured statements so a caller can check each claim against its
    evidence paths rather than reading prose and trusting it.
    """
    from ai.diagnosis_narrative import narrate_trade

    payload = request.get_json(silent=True) or {}
    trade = payload.get('trade')
    if not isinstance(trade, dict):
        return jsonify({'error': 'a trade object is required'}), 400

    narrative = narrate_trade(trade)
    if payload.get('format') == 'text':
        return jsonify({'text': narrative.to_text()}), 200
    return jsonify(narrative.to_dict()), 200


@app.route('/narrative/status', methods=['GET'])
def narrative_status():
    """How the narrative is produced, and why no language model is involved."""
    from ai import diagnosis_narrative
    return jsonify(diagnosis_narrative.get_status()), 200


@app.route('/performance/status', methods=['GET'])
def performance_status():
    """Scorecards for every tracked model, plus which governed models are not."""
    from ai import model_performance
    return jsonify(model_performance.get_status()), 200


@app.route('/performance/self_check', methods=['POST'])
def performance_self_check():
    """Scoring, gating, drift and agreement, against known synthetic inputs."""
    from ai import model_performance
    report = model_performance.self_check()
    return jsonify(report), (200 if report.get('ok') else 500)


@app.route('/performance/record', methods=['POST'])
def performance_record():
    """
    Record what a model said about a trade, and what happened.

    Accepts one record or a list. `realized_r` is the field that matters:
    expectancy in R is the headline metric, because accuracy rewards being
    right rather than being right when it pays.
    """
    from ai.model_performance import get_tracker

    payload = request.get_json(silent=True) or {}
    rows = payload.get('records')
    if isinstance(rows, list):
        written = get_tracker().record_many(rows)
        return jsonify({'recorded': written}), 200

    model, trade_id = payload.get('model'), payload.get('trade_id')
    if not model or trade_id is None:
        return jsonify({'error': 'model and trade_id are required'}), 400
    fields = {k: v for k, v in payload.items() if k not in ('model', 'trade_id')}
    entry = get_tracker().record(model, trade_id, **fields)
    return jsonify({'recorded': entry.to_dict()}), 200


@app.route('/performance/<model_name>/scorecard', methods=['GET'])
def performance_scorecard(model_name):
    """One model's expectancy, with the sample size that produced it."""
    from ai.model_performance import get_tracker
    return jsonify(get_tracker().scorecard(model_name)), 200


@app.route('/performance/<model_name>/drift', methods=['GET'])
def performance_drift(model_name):
    """
    Recent performance against the earlier baseline.

    Reported as a difference with a standard error rather than a yes/no: a
    model whose expectancy fell 0.05R over 30 trades has not drifted, it has
    been observed on a Tuesday.
    """
    from ai.model_performance import get_tracker
    try:
        window = int(request.args.get('window', 50))
    except (TypeError, ValueError):
        return jsonify({'error': 'window must be an integer'}), 400
    return jsonify(get_tracker().drift(model_name, window)), 200


@app.route('/performance/ranking', methods=['GET'])
def performance_ranking():
    """Models by expectancy, with the unrankable named rather than buried."""
    from ai.model_performance import get_tracker
    return jsonify({'ranking': get_tracker().ranking()}), 200


@app.route('/performance/ensemble', methods=['GET'])
def performance_ensemble():
    """
    Whether model agreement carries information.

    The question that decides if an ensemble earns its latency: if outcomes
    are no better when the models agree, the extra models are decoration.
    """
    from ai.model_performance import get_tracker

    models = request.args.get('models')
    chosen = [m.strip() for m in models.split(',')] if models else None
    return jsonify(get_tracker().agreement(chosen)), 200


@app.route('/performance/reset', methods=['POST'])
def performance_reset():
    """Drop recorded performance history. Destructive and explicit."""
    from ai.model_performance import get_tracker

    payload = request.get_json(silent=True) or {}
    get_tracker().reset(payload.get('model'))
    return jsonify({'reset': payload.get('model') or 'all'}), 200


# ============================================================
# LAZY SERVICE INITIALISATION
# ============================================================
#
# `initialize_services()` was reachable only from `main()`, so GNN and
# adversarial existed only when this module was run as a script. Serve the
# same app any other way -- `gunicorn ai_controller:app`, `waitress-serve`,
# importing `app` into a parent process, a test client -- and `main()` never
# runs, `_gnn` and `_adversarial` stay None forever, and every GNN and
# adversarial endpoint answers "not initialized" while the process looks
# healthy. /verify reported them `available: False` for exactly this reason.
#
# Initialisation is idempotent (guarded by `_initialized` under `_lock`) and
# measured at 0.00s once Firebase is a cached singleton, so it is safe to
# attempt on request. Doing it at IMPORT time would be worse: importing a
# module should not open a Firebase connection, and the test suite imports
# this app.
#
# Failure here must not take down endpoints that do not need these services,
# so the error is recorded and the request proceeds -- the components then
# report `available: False` with a reason, which is the honest outcome and the
# one /verify already knows how to surface.

# Plain assignment: a module-level annotation is evaluated at import,
# and this file has no typing import of its own to lean on.
_init_error = None


@app.before_request
def _ensure_services_initialized():
    """Initialise on first request, so serving without main() works."""
    global _init_error

    if _initialized:
        return
    try:
        initialize_services()
    except Exception as exc:
        _init_error = f"{type(exc).__name__}: {exc}"
        logger.warning(f"deferred AI service initialisation failed: {_init_error}")


# ============================================================
# MODEL GOVERNANCE ENDPOINTS
# ============================================================
#
# One surface for every governed model, addressed by name, rather than a
# bespoke pair of routes per model. Adding a ninth model gets these for free;
# the per-model adversarial and GNN routes above exist only because those two
# had A/B before there was anywhere shared to put it.
#
# Read endpoints are GET. Everything that CHANGES exposure or the active
# version is POST and names the model explicitly in the path, so widening a
# rollout can never be something a browser does by following a link.


def _governed_or_404(model_name):
    """Reject unknown model names rather than silently creating a registry."""
    from ai.model_governance import GOVERNED_MODELS
    if model_name not in GOVERNED_MODELS:
        return jsonify({
            'error': 'unknown model: ' + str(model_name),
            'governed_models': list(GOVERNED_MODELS),
        }), 404
    return None


def _native_ab_results(model_name):
    """
    A/B state for the two models that own their own counters.

    Delegated rather than mirrored. ai_adversarial and ai_gnn kept their
    assignment hashes (SHA-256 and MD5) so in-flight trades were not
    reassigned, and their arm counters are already accumulating; serving a
    shared empty experiment alongside would answer the same question two
    different ways.
    """
    global _adversarial, _gnn
    if model_name == 'ai_adversarial':
        from ai import ai_adversarial as module
        source = _adversarial
        results = (source.get_ab_test_results() if source
                   else module.AIAdversarial().get_ab_test_results())
    elif model_name == 'ai_gnn':
        from ai import ai_gnn as module
        source = _gnn
        results = (source.get_ab_test_results() if source
                   else module._build_gnn().get_ab_test_results())
    else:
        return None
    results = dict(results)
    results['name'] = model_name
    results['implementation'] = 'native'
    results['note'] = ('this model owns its A/B counters; the shared '
                       'governance experiment is not used for it')
    return results


@app.route('/governance/status', methods=['GET'])
def governance_status():
    """A/B state and version registry for every governed model."""
    from ai import model_governance
    return jsonify(model_governance.get_status()), 200


@app.route('/governance/self_check', methods=['POST'])
def governance_self_check():
    """Prove assignment determinism, verdict honesty, and that rollback moves."""
    from ai import model_governance
    report = model_governance.self_check()
    return jsonify(report), (200 if report.get('ok') else 500)


@app.route('/governance/<model_name>/ab_test', methods=['GET'])
def governance_ab_test(model_name):
    """
    Current A/B verdict for one model.

    `verdict_is_actionable` is the only field an automated caller should key
    on: `direction` gives the sign of a difference, not whether it is real.
    """
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected

    native = _native_ab_results(model_name)
    if native is not None:
        return jsonify(native), 200

    from ai.model_governance import get_ab_test
    return jsonify(get_ab_test(model_name).results()), 200


@app.route('/governance/<model_name>/ab_test/assign/<unit_id>', methods=['GET'])
def governance_ab_assign(model_name, unit_id):
    """
    Which arm a given trade id falls in.

    Exposed so an assignment can be CHECKED from outside rather than trusted.
    It is deterministic by construction, which is exactly the property worth
    being able to verify independently.
    """
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    from ai.model_governance import get_ab_test
    experiment = get_ab_test(model_name)
    return jsonify({
        'model': model_name,
        'unit_id': unit_id,
        'arm': experiment.assign(unit_id),
        'bucket': experiment.bucket(unit_id),
        'rollout': experiment.config.rollout,
        'hash_algorithm': experiment.config.hash_algorithm,
    }), 200


@app.route('/governance/<model_name>/ab_test/track', methods=['POST'])
def governance_ab_track(model_name):
    """Record one settled trade into its arm."""

    if model_name in ('ai_adversarial', 'ai_gnn'):
        # Mutating a native experiment through this surface would change one
        # of two states and leave the other stale. Point the caller at the
        # endpoint that owns it rather than half-applying the change.
        return jsonify({
            'error': 'this model owns its A/B state',
            'use_instead': '/' + model_name.replace('ai_', '') + '/ab_test',
        }), 409
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    payload = request.get_json(silent=True) or {}
    if 'unit_id' not in payload or 'outcome' not in payload:
        return jsonify({'error': 'unit_id and outcome are required'}), 400

    from ai.model_governance import get_ab_test
    experiment = get_ab_test(model_name)
    result = experiment.track(
        payload.get('unit_id'), payload.get('profit', 0.0),
        payload.get('outcome'), payload.get('arm'))
    return jsonify({'tracked': result, 'results': experiment.results()}), 200


@app.route('/governance/<model_name>/ab_test/rollout', methods=['POST'])
def governance_set_rollout(model_name):
    """Set the test-arm share for one model."""

    if model_name in ('ai_adversarial', 'ai_gnn'):
        # Mutating a native experiment through this surface would change one
        # of two states and leave the other stale. Point the caller at the
        # endpoint that owns it rather than half-applying the change.
        return jsonify({
            'error': 'this model owns its A/B state',
            'use_instead': '/' + model_name.replace('ai_', '') + '/ab_test',
        }), 409
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    payload = request.get_json(silent=True) or {}
    if 'rollout' not in payload:
        return jsonify({'error': 'rollout is required'}), 400
    try:
        requested = float(payload['rollout'])
    except (TypeError, ValueError):
        return jsonify({'error': 'rollout must be a number in [0, 1]'}), 400
    if not 0.0 <= requested <= 1.0:
        return jsonify({'error': 'rollout must be in [0, 1]'}), 400

    from ai.model_governance import get_ab_test
    experiment = get_ab_test(model_name)
    experiment.set_rollout(requested)
    return jsonify(experiment.results()), 200


@app.route('/governance/<model_name>/ab_test/reset', methods=['POST'])
def governance_reset_ab(model_name):
    """
    Discard the accumulated arm counters.

    Destructive and deliberately explicit: the counters ARE the experiment,
    so resetting mid-test throws away the evidence rather than the verdict.
    """

    if model_name in ('ai_adversarial', 'ai_gnn'):
        # Mutating a native experiment through this surface would change one
        # of two states and leave the other stale. Point the caller at the
        # endpoint that owns it rather than half-applying the change.
        return jsonify({
            'error': 'this model owns its A/B state',
            'use_instead': '/' + model_name.replace('ai_', '') + '/ab_test',
        }), 409
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    from ai.model_governance import get_ab_test
    experiment = get_ab_test(model_name)
    experiment.reset()
    return jsonify(experiment.results()), 200


@app.route('/governance/<model_name>/registry', methods=['GET'])
def governance_registry(model_name):
    """Version history, active version, and whether a rollback is possible."""
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    from ai.model_governance import get_registry
    registry = get_registry(model_name)
    return jsonify({
        'status': registry.status(),
        'versions': [v.to_dict() for v in registry.versions],
        'history': registry.history[-20:],
    }), 200


@app.route('/governance/<model_name>/promote', methods=['POST'])
def governance_promote(model_name):
    """Make a registered version the active one."""
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    payload = request.get_json(silent=True) or {}
    version = payload.get('version')
    if not version:
        return jsonify({'error': 'version is required'}), 400

    from ai.model_governance import get_registry
    registry = get_registry(model_name)
    outcome = registry.promote(version, payload.get('reason', ''))
    return jsonify({'result': outcome, 'status': registry.status()}), (
        200 if outcome.get('promoted') else 400)


@app.route('/governance/<model_name>/rollback', methods=['POST'])
def governance_rollback(model_name):
    """
    Revert to the most recent previously promoted version.

    Returns 409 rather than 200 when there is nothing to roll back to. This
    endpoint is called precisely when someone believes production is broken,
    and a cheerful 200 that changed nothing is the worst answer available.
    """
    rejected = _governed_or_404(model_name)
    if rejected:
        return rejected
    payload = request.get_json(silent=True) or {}
    from ai.model_governance import get_registry
    registry = get_registry(model_name)
    outcome = registry.rollback(payload.get('reason', 'manual rollback'))
    return jsonify({'result': outcome, 'status': registry.status()}), (
        200 if outcome.get('rolled_back') else 409)


# ============================================================
# RESEARCH LAYER -- EDGE DISCOVERY, FAMILIES, REPOSITORY, AUDIT
# ============================================================
# Added 2026-09-10. These modules had no HTTP surface at all, which meant the
# actual research engine -- the rule-space search, the family analysis, the
# 1,251-field audit and the bridge every model reads trades through -- was
# reachable only from a Python REPL.
#
# ONE DIFFERENCE FROM THE ENDPOINTS ABOVE
# ---------------------------------------
# Every older endpoint requires `trades` in the request body and 400s without
# it. That predates trades living in MongoDB. These load from the store when
# the body omits them, via ai/trade_repository.load_trades(), so a bare POST
# analyses whatever has actually been collected.
#
# The repository is used deliberately rather than reading Mongo directly: it
# applies canonicalise(), which flattens the analysis_at_open envelope and
# decodes every price point. Raw documents look fine and yield nothing --
# strategy_families.build_rows() returns 0 rows on raw documents and all of
# them through the repository.
# ============================================================

def _trades_from(payload, status=None, limit=None):
    """
    Trades for a research call: the body's if supplied, otherwise the store's.

    Returns (trades, error_response_or_None). An empty store is reported as a
    409 with the reason, not as an empty success -- "the search found nothing"
    and "there was nothing to search" are different answers, and conflating
    them is how an empty collection reads as a negative result.
    """
    supplied = (payload or {}).get('trades')
    if supplied:
        return supplied, None

    from ai import trade_repository as repo
    kwargs = {}
    if status:
        kwargs['status'] = status
    if limit:
        kwargs['limit'] = limit
    trades = repo.load_trades(**kwargs)
    if not trades:
        return None, (jsonify({
            'error': 'no trades available',
            'detail': ('The trades collection returned nothing for status='
                       + str(status or 'any')
                       + '. Supply "trades" in the body to analyse an '
                         'explicit set instead.'),
            'source': 'ai.trade_repository.load_trades',
        }), 409)
    return trades, None


# ------------------------------------------------------------
# EDGE DISCOVERY -- the rule-space search
# ------------------------------------------------------------

@app.route('/research/status', methods=['GET'])
def research_status():
    from ai import edge_discovery
    return jsonify(edge_discovery.get_status()), 200


@app.route('/research/self_check', methods=['POST'])
def research_self_check():
    from ai import edge_discovery
    payload = request.get_json(silent=True) or {}
    report = edge_discovery.self_check(payload.get('trades') or None)
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/research/samples', methods=['POST'])
def research_samples():
    """
    One row per trade: ledger deltas re-expressed in the traded frame, the
    realised R, the price path, and the measurement features.

    Deltas are signed against `best_direction`, which differs from the filled
    direction on ~19% of trades -- reading them in the wrong frame turned a
    measured +0.49R component edge into an apparent sign error.
    """
    from ai import edge_discovery
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    rows = edge_discovery.extract_samples(trades)
    return jsonify({
        'trades_in': len(trades),
        'samples': len(rows),
        'dropped': len(trades) - len(rows),
        'components': edge_discovery.component_names(rows),
        'features': edge_discovery.feature_names(rows),
        'rows': rows if payload.get('include_rows') else None,
    }), 200


@app.route('/research/features', methods=['POST'])
def research_features():
    """
    The measurement channels a trade carries, flattened to numbers.

    microstructure_at_entry, strategy_family_scores and component_reads are
    recorded on every trade with contribution 0.0, and nothing in ai/ read them
    until this existed -- including the one edge confirmed from new information
    (order flow, +0.2646R, p=0.0180).
    """
    from ai import edge_discovery
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    rows = edge_discovery.extract_samples(trades)
    min_present = int(payload.get('min_present', 10))
    return jsonify({
        'samples': len(rows),
        'channels': list(edge_discovery.FEATURE_CHANNELS),
        'testable': edge_discovery.feature_names(rows, min_present=min_present),
        'min_present': min_present,
        'all_present': edge_discovery.feature_names(rows, min_present=1),
    }), 200


@app.route('/research/search', methods=['POST'])
def research_search():
    """
    Search the rule space: reweight the probability chain and rescore against
    the SAME real outcomes.

    Survivors are chosen on train folds, scored on held-out blocks, tested
    against a permutation null and corrected with Benjamini-Hochberg across
    every configuration tried. The permutation null in the response is the
    point: on 215 trades, the identical search against shuffled outcomes still
    found a best subset at 61.5%.
    """
    from ai import edge_discovery
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err

    kwargs = {k: payload[k] for k in (
        'max_components', 'folds', 'min_train', 'min_test',
        'target_win_rate', 'target_expectancy', 'alpha', 'permutations', 'seed'
    ) if k in payload}
    if 'thresholds' in payload:
        kwargs['thresholds'] = tuple(payload['thresholds'])
    if 'allow_flip' in payload:
        kwargs['allow_flip'] = bool(payload['allow_flip'])

    return jsonify(edge_discovery.search_all(trades=trades, **kwargs)), 200


@app.route('/research/search/features', methods=['POST'])
def research_search_features():
    """
    Does CONDITIONING on a measurement channel beat taking every trade?

    Thresholds come from the train fold only -- deriving them from the whole
    series is look-ahead and the easiest way to manufacture an edge here.
    Survivors clear a walk-forward, a permutation null and BH-FDR across every
    hypothesis tested.
    """
    from ai import edge_discovery
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err

    kwargs = {k: payload[k] for k in (
        'folds', 'min_train', 'min_test', 'alpha', 'permutations', 'seed'
    ) if k in payload}
    return jsonify(edge_discovery.search_features(trades=trades, **kwargs)), 200


# ------------------------------------------------------------
# STRATEGY FAMILIES -- 23 categories, opposition, regime
# ------------------------------------------------------------

@app.route('/families/status', methods=['GET'])
def families_status():
    from ai import strategy_families
    return jsonify(strategy_families.get_status()), 200


@app.route('/families/self_check', methods=['POST'])
def families_self_check():
    from ai import strategy_families
    report = strategy_families.self_check()
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/families/classify/<name>', methods=['GET'])
def families_classify(name):
    """
    Which family a component belongs to. Longest token wins, so a specific
    family stays reachable when a shorter token of another also matches --
    under first-match-wins, `adr_exhaustion` was swallowed by MEAN_REVERSION's
    `exhaustion` and EXHAUSTION_ADR was unreachable entirely.
    """
    from ai import strategy_families
    return jsonify({
        'component': name,
        'family': strategy_families.classify(name),
    }), 200


@app.route('/families/rows', methods=['POST'])
def families_rows():
    from ai import strategy_families
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    rows = strategy_families.build_rows(trades)
    return jsonify({
        'trades_in': len(trades),
        'rows': len(rows),
        'dropped': len(trades) - len(rows),
        'detail': rows if payload.get('include_rows') else None,
    }), 200


@app.route('/families/analyse', methods=['POST'])
def families_analyse():
    """
    A handful of pre-registered questions, not a search -- which is why this
    has real power where the 1,251-field audit had none.
    """
    from ai import strategy_families
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    kwargs = {k: payload[k] for k in ('min_group', 'folds', 'permutations')
              if k in payload}
    return jsonify(strategy_families.analyse(trades=trades, **kwargs)), 200


@app.route('/families/opposition', methods=['POST'])
def families_opposition():
    """
    Which families contradict each other, discovered rather than assumed.

    TREND and MEAN_REVERSION conflict on 91.2% of trades: the probability chain
    adds a buy signal to a sell signal nine times in ten.
    """
    from ai import strategy_families
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    rows = strategy_families.build_rows(trades)
    return jsonify({
        'rows': len(rows),
        'family_opposition': strategy_families.discover_opposition(rows),
        'component_opposition': strategy_families.component_opposition(trades),
    }), 200


# ------------------------------------------------------------
# TRADE REPOSITORY -- the bridge every model reads through
# ------------------------------------------------------------

@app.route('/repository/status', methods=['GET'])
def repository_status():
    from ai import trade_repository
    return jsonify(trade_repository.get_status()), 200


@app.route('/repository/self_check', methods=['POST'])
def repository_self_check():
    from ai import trade_repository
    payload = request.get_json(silent=True) or {}
    report = trade_repository.self_check(payload.get('trades') or None)
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/repository/trades', methods=['GET'])
def repository_trades():
    """
    Stored trades in the shape models read -- envelope flattened, price points
    decoded. Never returns raw Mongo documents.
    """
    from ai import trade_repository as repo
    kwargs = {}
    if request.args.get('limit'):
        kwargs['limit'] = int(request.args['limit'])
    if request.args.get('symbol'):
        kwargs['symbol'] = request.args['symbol']
    if request.args.get('status'):
        kwargs['status'] = request.args['status']
    trades = repo.load_trades(**kwargs)
    include = request.args.get('include_trades', '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'count': len(trades),
        'query': kwargs,
        'trades': trades if include else None,
    }), 200


@app.route('/repository/trades/<trade_id>', methods=['GET'])
def repository_trade(trade_id):
    from ai import trade_repository as repo
    try:
        return jsonify(repo.get_trade(trade_id)), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'trade_id': trade_id}), 404


@app.route('/repository/training_set', methods=['POST'])
def repository_training_set():
    """
    Features, path and labels returned SEPARATELY, not merged.

    analysis_at_open + entry is what was known at T0; price_evolution is the
    forward walk; close_data is the outcome and is labels only. Merging them
    and trusting discipline is how a model ends up predicting the past.
    """
    from ai import trade_repository as repo
    payload = request.get_json(silent=True) or {}
    kwargs = {k: payload[k] for k in ('limit', 'symbol', 'status') if k in payload}
    result = repo.load_training_set(**kwargs)
    if payload.get('include_data'):
        return jsonify(result), 200
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}
    return jsonify(summary), 200


# ------------------------------------------------------------
# COMPONENT AUDIT -- every scoreable field
# ------------------------------------------------------------

@app.route('/audit/status', methods=['GET'])
def audit_status():
    from ai import component_audit_360
    return jsonify(component_audit_360.get_status()), 200


@app.route('/audit/self_check', methods=['POST'])
def audit_self_check():
    from ai import component_audit_360
    payload = request.get_json(silent=True) or {}
    report = component_audit_360.self_check(payload.get('trades') or None)
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/audit/run', methods=['POST'])
def audit_run():
    """
    The wide scan across every discovered field.

    Reported with its own multiple-comparison correction, and worth reading
    alongside the permutation null: a wide scan over ~1,251 fields on a few
    hundred trades finds spectacular subsets in pure noise.
    """
    from ai import component_audit_360
    payload = request.get_json(silent=True) or {}
    trades, err = _trades_from(payload, status='CLOSED')
    if err:
        return err
    kwargs = {k: payload[k] for k in ('folds', 'permutations', 'alpha', 'seed')
              if k in payload}
    return jsonify(component_audit_360.audit(trades=trades, **kwargs)), 200


# ------------------------------------------------------------
# MT5 HISTORY + ENRICHMENT -- the research corpus
# ------------------------------------------------------------

@app.route('/history/status', methods=['GET'])
def history_status():
    from ai import mt5_history
    return jsonify(mt5_history.get_status()), 200


@app.route('/history/self_check', methods=['POST'])
def history_self_check():
    from ai import mt5_history
    payload = request.get_json(silent=True) or {}
    report = mt5_history.self_check(payload.get('trades') or None)
    return jsonify(report), 200 if report.get('ok') else 422


@app.route('/history/coverage', methods=['GET'])
def history_coverage():
    from ai import mt5_history
    days = int(request.args.get('days', 365))
    return jsonify(mt5_history.coverage(days=days)), 200


@app.route('/history/positions', methods=['GET'])
def history_positions():
    """
    Closed positions from the MT5 account, paired IN deal to OUT deal on
    position_id.

    Direction comes from the opening deal's type and profit from the broker's
    own deals -- never inferred from which way the price moved. That inference,
    which the live save path used to make, would have been wrong on 57.2% of
    these positions and would have manufactured a 98.8% win rate.
    """
    from ai import mt5_history
    days = int(request.args.get('days', 365))
    positions = mt5_history.load_positions(days=days)
    include = request.args.get('include_positions', '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'days': days,
        'count': len(positions),
        'positions': positions if include else None,
    }), 200


@app.route('/history/enrich', methods=['POST'])
def history_enrich():
    """
    Recompute the analysis for past trades from the bars as they stood at entry.

    Not simulated data -- the analysis layer is deterministic over bars, so this
    is the real analysis, recomputed. Every trade whose no-lookahead check finds
    a violation is refused rather than trusted.
    """
    from ai import history_enrichment, mt5_history
    payload = request.get_json(silent=True) or {}
    positions = payload.get('positions')
    if not positions:
        positions = mt5_history.load_positions(days=int(payload.get('days', 365)))
    if not positions:
        return jsonify({'error': 'no positions in MT5 history to enrich'}), 409
    limit = payload.get('limit')
    if limit:
        positions = positions[:int(limit)]
    trades = history_enrichment.enrich(positions)
    return jsonify({
        'positions_in': len(positions),
        'enriched': len(trades),
        'refused': len(positions) - len(trades),
        'trades': trades if payload.get('include_trades') else None,
    }), 200


@app.route('/verify', methods=['POST'])
def verify_all():
    """
    Whole-AI-layer verification in one call.

    POST {"trades": [...]} to exercise the data paths against real trades;
    with no body it still reports availability and A/B state. `ok` is only
    true when every component that ran reported ok, so this is usable as a
    single gate before trusting any AI output.
    """
    global _gnn, _adversarial
    from ai import ai_reinforcement
    from ai.non_rl_intelligence import NonRLIntelligenceController
    from ai.price_evolution_bridge import PriceEvolutionBridge

    payload = request.get_json(silent=True) or {}
    trades = payload.get('trades') or []

    report = {
        'timestamp': datetime.now().isoformat(),
        'trades_supplied': len(trades),
        'components': {},
    }

    from ai import ablation as _ablation
    report['components']['ablation'] = {
        'available': True,
        'status': _ablation.get_status(),
        # Ablation retrains once per section, so it is exercised on a slice
        # rather than the whole set: a verification endpoint that takes
        # minutes stops being run.
        'self_check': _ablation.self_check(trades[:40]) if trades else None,
    }

    from core import clv_absorption as _clv
    from ai import trade_quality as _trade_quality
    report['components']['clv_absorption'] = {
        'available': True,
        'status': _clv.get_status(),
        'self_check': _clv.self_check(),
    }
    report['components']['trade_quality'] = {
        'available': True,
        'status': _trade_quality.get_status(),
        'self_check': _trade_quality.self_check(trades) if trades else None,
    }

    from ai import (adversarial_replay as _adv_replay,
                    gnn_analysis as _gnn_analysis,
                    rl_policies as _rl_policies)
    report['components']['gnn_analysis'] = {
        'available': True,
        'status': _gnn_analysis.get_status(),
        'self_check': _gnn_analysis.self_check(trades) if trades else None,
    }
    report['components']['adversarial_replay'] = {
        'available': True,
        'self_check': _adv_replay.self_check(trades[:3]) if trades else None,
    }
    report['components']['rl_policies'] = {
        'available': True,
        'status': _rl_policies.get_status(),
        'self_check': _rl_policies.self_check(trades) if trades else None,
    }

    from ai import component_validation as _component_validation
    report['components']['component_validation'] = {
        'available': True,
        'status': _component_validation.get_status(),
        'self_check': _component_validation.self_check(),
    }

    from ai import rule_experiments as _rule_experiments
    report['components']['rule_experiments'] = {
        'available': True,
        'status': _rule_experiments.get_status(),
        'self_check': _rule_experiments.self_check(),
    }

    from ai.aireplay import live_recording as _live_recording
    report['components']['live_recording'] = {
        'available': True,
        'status': _live_recording.get_status(),
        'self_check': _live_recording.self_check(),
    }

    from ai.aireplay import stress as _stress
    report['components']['replay_stress'] = {
        'available': True,
        'status': _stress.get_status(),
        'self_check': _stress.self_check(trades) if trades else None,
    }

    from ai import (diagnosis_narrative as _narrative,
                    model_performance as _performance,
                    root_cause_adapter as _rc_adapter,
                    root_cause_analyzers as _rc_analyzers,
                    root_cause_trackers as _rc_trackers)
    report['components']['root_cause'] = {
        'available': True,
        'status': _rc_analyzers.get_status(),
        'self_check': _rc_analyzers.self_check(trades) if trades else None,
    }
    report['components']['root_cause_tracker'] = {
        'available': True,
        'self_check': _rc_trackers.self_check(trades),
    }
    report['components']['root_cause_adapter'] = {
        'available': True,
        'self_check': _rc_adapter.self_check(trades) if trades else None,
    }
    report['components']['diagnosis_narrative'] = {
        'available': True,
        'status': _narrative.get_status(),
        'self_check': _narrative.self_check(trades) if trades else None,
    }
    report['components']['model_performance'] = {
        'available': True,
        'self_check': _performance.self_check(),
    }

    from ai import model_governance as _governance
    report['components']['model_governance'] = {
        'available': True,
        'status': _governance.get_status(),
        'self_check': _governance.self_check(),
    }

    from ai import ai_gnn as _gnn_module
    report['components']['gnn'] = {
        'available': _gnn is not None,
        'unavailable_reason': _init_error if _gnn is None else None,
        'status': _gnn.get_status() if _gnn else None,
        'ab_test': _gnn.get_ab_test_results() if _gnn else None,
        'self_check': _gnn_module.self_check(trades, _gnn) if trades else None,
    }
    from ai import ai_adversarial as _adv_module
    report['components']['adversarial'] = {
        'available': _adversarial is not None,
        'unavailable_reason': _init_error if _adversarial is None else None,
        'ab_test': _adversarial.get_ab_test_results() if _adversarial else None,
        # Previously absent, which silently removed adversarial from `ok`
        # below -- the component this controller prints as ESSENTIAL was
        # excluded from the gate that exists to vouch for it.
        'self_check': (_adv_module.self_check(trades, _adversarial)
                       if trades else None),
    }
    report['components']['reinforcement_learning'] = {
        'status': ai_reinforcement.get_status(),
        'self_check': ai_reinforcement.self_check(trades) if trades else None,
    }

    controller = NonRLIntelligenceController()
    report['components']['non_rl_intelligence'] = {
        'status': controller.get_status(),
        'self_check': controller.self_check(trades) if trades else None,
    }

    from ai import (abstention_model, aireplay, calibration_model,
                    exit_model, market_synthesis, target_model)
    report['components']['exit_model'] = {
        'status': exit_model.get_status(),
        'self_check': exit_model.self_check(trades) if trades else None,
    }
    report['components']['target_model'] = {
        'status': target_model.get_status(),
        'self_check': target_model.self_check(trades) if trades else None,
    }
    report['components']['calibration_model'] = {
        'status': calibration_model.get_status(),
        'self_check': calibration_model.self_check(trades) if trades else None,
    }
    report['components']['abstention_model'] = {
        'status': abstention_model.get_status(),
        'self_check': abstention_model.self_check(trades) if trades else None,
    }
    report['components']['aireplay_phase1'] = {
        'status': aireplay.get_status(),
        'self_check': aireplay.self_check(trades) if trades else None,
    }
    report['components']['market_synthesis'] = {
        'status': market_synthesis.get_status(),
        'self_check': market_synthesis.self_check(trades) if trades else None,
    }
    from ai.aireplay import consistency, counterfactual, replay_engine
    report['components']['replay_engine'] = {
        'status': replay_engine.get_status(),
        'self_check': replay_engine.self_check(trades) if trades else None,
    }
    report['components']['counterfactual'] = {
        'status': counterfactual.get_status(),
        'self_check': counterfactual.self_check(trades) if trades else None,
    }
    report['components']['simulator_consistency'] = {
        'status': consistency.get_status(),
        'self_check': consistency.self_check(trades) if trades else None,
    }

    from ai import price_evolution_bridge as _bridge_module
    from ai.aireplay import recorder as _recorder_module

    report['components']['price_evolution'] = {
        'available': True,
        'status': _bridge_module.get_status(),
        # This is standard 1 -- the single decode boundary every model's view
        # of a trade passes through -- and it was the one component /verify
        # could not check. It printed "NO self_check" on every call.
        'self_check': _bridge_module.self_check(trades) if trades else None,
    }
    if trades:
        report['components']['price_evolution']['coverage'] = (
            PriceEvolutionBridge().feature_coverage(trades[0]))

    report['components']['recorder'] = {
        'available': True,
        'status': _recorder_module.get_status(),
        'self_check': _recorder_module.self_check(),
    }

    from ai import trade_evaluation as _evaluation
    report['components']['trade_evaluation'] = {
        'available': True,
        'status': _evaluation.get_status(),
        'self_check': _evaluation.self_check(trades) if trades else None,
    }

    # A component with no self_check used to be filtered out of this list
    # entirely, so `ok` could be True while GNN and adversarial had been
    # verified by nothing at all. An uncomputable gate is an unmet gate
    # (standard 16): components that cannot report are now NAMED, and they
    # withhold `ok` rather than being quietly dropped from the numerator.
    # `ok` is genuinely tri-state and is kept that way here. A component
    # reporting ok=None ran but could not exercise its checks (no eligible
    # samples in the supplied trades); collapsing that to False reported
    # working modules as broken, and collapsing it to True would vouch for
    # something nothing tested.
    checks = []
    unverified = []
    not_exercised = []
    for name, component in report['components'].items():
        verdict = component.get('self_check')
        if isinstance(verdict, dict):
            state = verdict.get('ok')
            if state is None:
                not_exercised.append(
                    f"{name}: {verdict.get('reason') or 'no reason given'}")
            else:
                checks.append(bool(state))
        elif trades:
            unverified.append(name)

    report['not_exercised'] = not_exercised

    report['unverified_components'] = unverified
    report['unavailable_components'] = [
        name for name, component in report['components'].items()
        if component.get('available') is False
    ]
    # Governance verifies itself without needing trades, so with no trades
    # supplied it is the only component that can report. That must NOT become
    # a layer-wide pass: "the A/B assignment is deterministic" says nothing
    # about whether the models can read a trade. With no trades, nothing
    # data-dependent ran, so the verdict stays None and governance is reported
    # on its own line.
    governance = report['components'].get('model_governance', {})
    report['governance_ok'] = (governance.get('self_check') or {}).get('ok')

    if not trades:
        report['ok'] = None
        report['not_exercised'] = not_exercised + [
            'every data-dependent component: no trades supplied']
    elif not checks:
        report['ok'] = None               # nothing exercised; no verdict
    else:
        report['ok'] = all(checks) and not unverified
    return jsonify(report), 200


@app.route('/adversarial/status', methods=['GET'])
def adversarial_status():
    """Get adversarial training status."""
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        status = _adversarial.get_status()
        return jsonify({
            'success': True,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- GENERATE ATTACKS ----------

@app.route('/adversarial/generate', methods=['POST'])
def adversarial_generate():
    """
    Generate attacked trades for training.
    Creates variations of trades with different attack patterns.
    """
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        trade = data.get('trade')
        outcome = data.get('outcome', 1)
        num_variations = data.get('num_variations', None)
        
        if not trade:
            return jsonify({'success': False, 'error': 'trade parameter required'}), 400
        
        # Override variations if specified
        if num_variations:
            original_variations = _adversarial.adversarial_config['variations_per_trade']
            _adversarial.adversarial_config['variations_per_trade'] = num_variations
        
        # Get GNN context if available
        symbol = trade.get('symbol', '')
        gnn_context = None
        if _gnn and symbol:
            gnn_context = _gnn.get_trading_insights(symbol)
            _adversarial.set_gnn_context(symbol, gnn_context)
        
        attacked_trades = _adversarial.generate_attacked_trades(trade, outcome, gnn_context)
        
        # Restore original variations
        if num_variations:
            _adversarial.adversarial_config['variations_per_trade'] = original_variations
        
        return jsonify({
            'success': True,
            'attacked_trades': attacked_trades,
            'count': len(attacked_trades),
            'gnn_used': gnn_context is not None,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- TRAIN ----------

@app.route('/adversarial/train', methods=['POST'])
def adversarial_train():
    """
    Apply adversarial attacks to training.
    Trains models on attacked versions of trades.
    """
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        trades = data.get('trades', [])
        outcomes = data.get('outcomes', [])
        symbol = data.get('symbol')
        component_name = data.get('component_name')
        save_models = data.get('save_models', True)
        
        if not trades or not outcomes:
            return jsonify({'success': False, 'error': 'trades and outcomes required'}), 400
        
        if len(trades) != len(outcomes):
            return jsonify({'success': False, 'error': 'trades and outcomes length mismatch'}), 400
        
        # Get GNN context if available
        gnn_context = None
        if _gnn and symbol:
            gnn_context = _gnn.get_trading_insights(symbol)
            _adversarial.set_gnn_context(symbol, gnn_context)
        
        # Define training function
        def training_function(attacked_trades, _):
            # Placeholder - actual training logic would go here
            return {
                'improvement': 0.05,
                'trained_count': len(attacked_trades),
                'success': True,
                'weights': {'sample_weight': 0.5}
            }
        
        result = _adversarial.apply_attacks_to_training(
            trades=trades,
            outcomes=outcomes,
            training_function=training_function,
            symbol=symbol,
            component_name=component_name,
            save_models=save_models
        )
        
        return jsonify({
            'success': True,
            'result': result,
            'gnn_used': gnn_context is not None,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- METRICS ----------

@app.route('/adversarial/metrics', methods=['GET'])
def adversarial_metrics():
    """Get attack metrics."""
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        metrics = {
            'total_attacks': _adversarial.stats['total_attacks_generated'],
            'attacks_applied': _adversarial.stats['total_attacks_applied'],
            'trades_attacked': _adversarial.stats['trades_attacked'],
            'success_rate': _adversarial.stats['attack_success_rate'],
            'diversity_score': _adversarial.stats['diversity_score'],
            'components_attacked': dict(_adversarial.stats['components_attacked']),
            'attack_types': dict(_adversarial.stats['attack_types_used']),
            'buffer_size': len(_adversarial.trade_buffer),
        }
        
        return jsonify({
            'success': True,
            'metrics': metrics,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- INTENSITY ----------

@app.route('/adversarial/intensity', methods=['POST'])
def adversarial_intensity():
    """Set attack intensity (0.0 - 1.0)."""
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        intensity = data.get('intensity')
        if intensity is None:
            return jsonify({'success': False, 'error': 'intensity parameter required'}), 400
        
        intensity = float(intensity)
        if not 0.0 <= intensity <= 1.0:
            return jsonify({'success': False, 'error': 'intensity must be between 0 and 1'}), 400
        
        _adversarial.adversarial_config['intensity'] = intensity
        _adversarial.save_metrics()
        
        return jsonify({
            'success': True,
            'message': f'Attack intensity set to {intensity:.2f}',
            'intensity': intensity,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- ENABLE/DISABLE ----------

@app.route('/adversarial/enable', methods=['POST'])
def adversarial_enable():
    """Enable or disable adversarial training."""
    global _adversarial
    
    if _adversarial is None:
        return jsonify({
            'success': False,
            'error': 'Adversarial training not initialized'
        }), 400
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        enabled = data.get('enabled')
        if enabled is None:
            return jsonify({'success': False, 'error': 'enabled parameter required'}), 400
        
        _adversarial.adversarial_config['enabled'] = bool(enabled)
        _adversarial.save_metrics()
        
        return jsonify({
            'success': True,
            'message': f'Adversarial training {"enabled" if enabled else "disabled"}',
            'enabled': bool(enabled),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# ---------- GENERATE ATTACKED TRADE DATA ----------

@app.route('/adversarial/generate_for_trade', methods=['POST'])
def adversarial_generate_for_trade():
    """
    Generate attacked trade variations for a specific trade,
    ensuring successful and failed trades are both processed for robust learning.
    """
    global _adversarial, _firebase
    
    if _adversarial is None:
        return jsonify({'success': False, 'error': 'Adversarial training not initialized'}), 400
    
    try:
        data = request.get_json()
        ticket = data.get('ticket')
        if not ticket:
            return jsonify({'success': False, 'error': 'Ticket required'}), 400
            
        # Get trade data from Firebase
        trade = _firebase.get_trade(str(ticket))
        if not trade:
            return jsonify({'success': False, 'error': f'Trade {ticket} not found'}), 404
        
        # Determine outcome for adversarial training
        # We need this to apply proper attacks (e.g., attack winners differently)
        outcome = 1 if trade.get('profit_usd', 0) > 0 else 0
        
        # Get GNN context if available
        gnn_context = None
        symbol = trade.get('symbol')
        if _gnn and symbol:
            gnn_context = _gnn.get_trading_insights(symbol)
            _adversarial.set_gnn_context(symbol, gnn_context)
            
        # Set intensity temporarily if provided, otherwise use config
        intensity = data.get('intensity')
        if intensity is not None:
            _adversarial.adversarial_config['intensity'] = float(intensity)
            
        # Generate variations using the correct method: generate_attacked_trades
        attacks = _adversarial.generate_attacked_trades(trade, outcome, gnn_context)
        
        return jsonify({
            'success': True,
            'ticket': ticket,
            'outcome': outcome,
            'variations_count': len(attacks),
            'variations': [a.get('analysis_at_open', {}) for a in attacks] # Subset for preview
        }), 200
        
    except Exception as e:
        logger.error(f"Adversarial generation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# MAIN
# ============================================================

def signal_handler(sig, frame):
    print("\n🛑 Shutting down AI Controller...")
    global _gnn, _adversarial
    if _gnn:
        _gnn.stop()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize services
    if not initialize_services():
        print("❌ Failed to initialize AI Controller")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("🧠 AI CONTROLLER ROUTES")
    print("=" * 60)
    
    print("\n📊 GNN (14 endpoints - COMPLETE):")
    print("   GET  /gnn/status")
    print("   GET  /gnn/context/<symbol>")
    print("   GET  /gnn/insights/<symbol>")
    print("   GET  /gnn/correlations/<symbol>")
    print("   GET  /gnn/divergences/<symbol>")
    print("   GET  /gnn/suggestions/<symbol>")
    print("   GET  /gnn/conflict/<symbol>          ← CONTRADICTION DETECTION")
    print("   GET  /gnn/ab_test")
    print("   GET  /gnn/heatmap")
    print("   GET  /gnn/correlation_changes/<symbol>")
    print("   POST /gnn/refresh")
    print("   POST /gnn/reset")
    print("   POST /gnn/ab_test/rollout")
    print("   POST /gnn/track_result")
    
    print("\n⚔️ Adversarial (7 endpoints):")
    print("   GET  /adversarial/status")
    print("   POST /adversarial/generate")
    print("   POST /adversarial/train")
    print("   GET  /adversarial/metrics")
    print("   POST /adversarial/intensity")
    print("   POST /adversarial/enable")
    print("   POST /adversarial/generate_for_trade")
    
    print("\n❤️ Health:")
    print("   GET  /health")
    
    print("\n" + "=" * 60)
    print("📂 STORAGE (Existing Collections Only)")
    print("   ai_component_models, ai_ensemble_models")
    print("   ai_performance_state, ai_config_state")
    print("   ai_training_data, ai_gnn_state")
    print("=" * 60)
    print("🚀 Starting AI Controller on port 5002...")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5002, debug=True, threaded=True)


if __name__ == "__main__":
    main()