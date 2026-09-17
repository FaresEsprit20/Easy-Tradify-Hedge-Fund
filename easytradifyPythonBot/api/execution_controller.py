# api/execution_controller.py
# ============================================================
# REST API CONTROLLER FOR SPRING BOOT INTEGRATION
# TP1 (native MT5 TP) + OPTIONAL TP2/TP3 (managed via partial closes,
# since MT5 only supports a single native TP per position)
# WITH BREAK-EVEN + PIP/USD-DISTANCE TRAILING STOP
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
import logging
import time
from datetime import datetime
import MetaTrader5 as mt5
import sys
import os
import math

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

logger = logging.getLogger(__name__)
api_bp = Blueprint('trading_api', __name__, url_prefix='/api/v1')
mt5_connected = False


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
# TRADE EXECUTION ENDPOINT - BREAK-EVEN + PIP/USD-DISTANCE POSITION MANAGEMENT
# ============================================================

@api_bp.route('/trade/execute', methods=['POST'])
def api_execute_trade():
    try:
        data = request.get_json()
        required_fields = ['symbol', 'order_type', 'strategy_magic', 
                          'fixed_trade_size_usd', 'risk_per_trade', 'max_spread']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        # Build execute_trade parameters
        params = {
            'symbol': data['symbol'].upper(),
            'order_type': data['order_type'].upper(),
            'strategy_magic': data['strategy_magic'],
            'fixed_trade_size_usd': float(data['fixed_trade_size_usd']),
            'risk_per_trade': float(data['risk_per_trade']),
            'max_spread': float(data['max_spread']),
            'trade_deviation': int(data.get('trade_deviation', 20)),
            'max_trades_per_symbol': int(data.get('max_trades_per_symbol', 1)),
            'max_simultaneous_trades': int(data.get('max_simultaneous_trades', 5)),
            'min_stop_pips_override': data.get('min_stop_pips_override'),
            'comment': data.get('comment', 'AI Trade')
        }
        
        # Add SL price if provided
        if data.get('stop_loss_price') is not None:
            params['stop_loss_price'] = float(data['stop_loss_price'])
        
        if data.get('take_profit_price') is not None:
            params['take_profit_price'] = float(data['take_profit_price'])

        # ✅ TP2 / TP3 are now real, applied levels - MT5's native TP only
        # supports one level, so execute_trade() splits the position and
        # partially closes it as each level is hit (see core/execution.py).
        if data.get('take_profit_2_price') is not None:
            params['take_profit_2_price'] = float(data['take_profit_2_price'])
        if data.get('take_profit_3_price') is not None:
            params['take_profit_3_price'] = float(data['take_profit_3_price'])
        
        # ============================================================
        # BREAK-EVEN + TRAILING STOP PARAMETERS
        # ============================================================
        # Position management: break-even and trailing are independent.
        # For each distance, exactly ONE of pips_distance or usd_distance may be used.
        params['enable_break_even'] = bool(data.get('enable_break_even', False))
        params['break_even_pips_distance'] = (
            float(data['break_even_pips_distance'])
            if data.get('break_even_pips_distance') is not None else None
        )
        params['break_even_usd_distance'] = (
            float(data['break_even_usd_distance'])
            if data.get('break_even_usd_distance') is not None else None
        )
        params['enable_trailing_stop'] = bool(data.get('enable_trailing_stop', False))
        params['trailing_pips'] = (
            float(data['trailing_pips']) if data.get('trailing_pips') is not None else None
        )
        params['trailing_usd_distance'] = (
            float(data['trailing_usd_distance'])
            if data.get('trailing_usd_distance') is not None else None
        )
        
        # Execute trade
        result = execute_trade(**params)

        # ============================================================
        # ✅ FIX: ACTUALLY ACTIVATE BREAK-EVEN / TRAILING MONITORING
        # ------------------------------------------------------------
        # execute_trade() only ECHOES enable_break_even/enable_trailing_stop
        # back in its response - it does NOT register the ticket into
        # _active_trails or start the monitor thread. The only code in
        # this file that does that lives in the two dedicated endpoints
        # (/position/break-even/enable/<ticket> and
        # /position/trailing/enable/<ticket>). Without this, a trade
        # opened here with enable_break_even/enable_trailing_stop=true
        # is never actually monitored. Replicate that same registration
        # here, using the trade's own ticket/symbol/SL, right after a
        # successful execute.
        # ============================================================
        ticket = result.get('ticket') if isinstance(result, dict) else None
        if result.get('success') and ticket and (params['enable_break_even'] or params['enable_trailing_stop']):
            try:
                from core.execution import _active_trails, start_trailing_monitor
                config = _active_trails.get(ticket, {})
                config['symbol'] = params['symbol']
                config.setdefault('created_at', time.time())
                if params['enable_break_even']:
                    config['break_even_enabled'] = True
                    config['break_even_pips_distance'] = params['break_even_pips_distance']
                    config['break_even_usd_distance'] = params['break_even_usd_distance']
                if params['enable_trailing_stop']:
                    config['trailing_enabled'] = True
                    config['pips_distance'] = params['trailing_pips']
                    config['usd_distance'] = params['trailing_usd_distance']
                    config['step_pips'] = params['trailing_pips']
                    config['last_sl'] = result.get('stop_loss')
                _active_trails[ticket] = config
                start_trailing_monitor()
                logger.info(f"✅ Break-even/trailing activated for ticket {ticket} at trade execution")
            except Exception as e:
                logger.error(f"⚠️ Failed to activate break-even/trailing for ticket {ticket}: {e}")
        
        return jsonify({'success': True, 'data': result, 'timestamp': datetime.now().isoformat()}), 200
        
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
        
        # Validate required fields
        required_fields = ['symbol', 'order_type', 'fixed_trade_size_usd', 'risk_per_trade']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing {field}'}), 400
        
        # Call the execution.py function
        result = analyze_institutional_signal(
            symbol=data['symbol'].upper(),
            order_type=data['order_type'].upper(),
            fixed_trade_size_usd=float(data['fixed_trade_size_usd']),
            risk_per_trade=float(data['risk_per_trade']),
            timeframe=data.get('timeframe', 'M1'),
            stop_loss_pips=data.get('stop_loss_pips'),
            take_profit_pips=data.get('take_profit_pips'),
            # "ALL" (default) or one strategy group, e.g. "SMC"
            strategy=data.get('strategy')
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
    """Get current market conditions with explanations for each metric"""
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
                    'explanation': 'Current spread in pips. Lower is better. >15 pips will trigger AVOID in trade analysis.',
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
    """
    Partially close a position using PUT method.
    
    Request body:
    {
        "volume_to_close": 0.05,  # Required: volume to close
        "deviation": 20           # Optional, default 20
    }
    """
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
    """
    Modify stop-loss using PUT method.
    
    Request body:
    {
        "sl_price": 1.12345  # Required: new stop-loss price
    }
    """
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
    """
    Modify take-profit using PUT method.
    
    Request body:
    {
        "tp_price": 1.12500  # Required: new take-profit price
    }
    """
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
    """
    Disable trailing stop for a position using PUT method.
    
    Request body: None (ticket in path)
    """
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
    """Get trailing stop status for all positions."""
    try:
        result = get_active_trails()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/trailing-stop/stats', methods=['GET'])
def api_get_trailing_stats():
    """Get trailing stop statistics."""
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
        
        # Calculate summary
        total_risk = 0
        total_reward = 0
        total_profit = 0
        total_probability = 0
        
        for p in positions:
            # Estimate risk from stop loss and volume
            if p.get('stop_loss') and p.get('price_open'):
                sl_distance = abs(p['price_open'] - p['stop_loss'])
                pip_value = sl_distance * p.get('volume', 0) * 10000  # Approximate
                risk = pip_value
                total_risk += risk
                p['risk_amount_usd'] = round(risk, 2)
            
            # Estimate reward from take profit
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
        
        # Check if position has trailing stop
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
    print("   - TP1 uses MT5's native TP field")
    print("   - Optional TP2/TP3 split the position into partial closes (70/30, or 33/33/34)")
    print("     since MT5 only supports one native TP - managed by the position monitor")
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
    
    print("\n" + "="*60)
    print("🚀 Starting Flask API on port 5000...")
    print("="*60)
    print("\n📋 Available Endpoints:")
    print("   POST   /api/v1/mt5/connect          - Connect to MT5")
    print("   POST   /api/v1/mt5/disconnect       - Disconnect from MT5")
    print("   GET    /api/v1/health               - Health check")
    print("   POST   /api/v1/trade/execute        - Execute trade (1 TP + Break-even + Trailing)")
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
    print("\n" + "="*60)
    
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)