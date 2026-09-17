# ============================================================
# PORTFOLIO RISK MANAGEMENT CONTROLLER API
# ============================================================
# FILE: api/portfolio_risk_controller.py
# PORT: 5010
# 
# ✅ REST API for portfolio risk management
# ✅ Complete CRUD operations for risk configuration
# ✅ Real-time portfolio status
# ✅ Daily/Monthly/YTD statistics from trades collection
# ✅ Trading permission checks
# ✅ Funded account compliance monitoring
# ✅ All limits in PERCENTAGE only
# ✅ Consistent URL pattern: /api/v1/portfolio/...
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

import sys
import os
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import portfolio risk service
try:
    from core.portfolio_risk_service import (
        PortfolioRiskService,
        PortfolioRiskConfig,
        get_portfolio_risk_service,
        RiskLevel
    )
except ImportError as e:
    print(f"⚠️ Error importing from core: {e}")
    try:
        from portfolio_risk_service import (
            PortfolioRiskService,
            PortfolioRiskConfig,
            get_portfolio_risk_service,
            RiskLevel
        )
    except ImportError:
        print("❌ Could not import portfolio_risk_service")
        raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Initialize portfolio risk service
portfolio_service = None

# API Prefix
API_PREFIX = "/api/v1"


def init_portfolio_service():
    """Initialize the portfolio risk service."""
    global portfolio_service
    if portfolio_service is None:
        portfolio_service = get_portfolio_risk_service()
        logger.info("✅ Portfolio Risk Service initialized")
    return portfolio_service


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "portfolio_risk_controller",
        "port": 5010,
        "api_prefix": API_PREFIX,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service_initialized": portfolio_service is not None
    })


# ============================================================
# PORTFOLIO STATUS
# ============================================================

@app.route(f'{API_PREFIX}/portfolio/status', methods=['GET'])
def get_portfolio_status():
    """
    Get portfolio status.
    
    Query Parameters:
        refresh: bool - Force refresh from Firebase (default: false)
        summary: bool - Return lightweight summary (default: false)
    """
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        summary_only = request.args.get('summary', 'false').lower() == 'true'
        
        status = portfolio_service.get_status(force_refresh=refresh)
        
        if summary_only:
            return jsonify({
                "success": True,
                "summary": {
                    "timestamp": status.timestamp,
                    "account": {
                        "balance": status.account_balance,
                        "equity": status.account_equity,
                        "leverage": status.account_leverage,
                        "currency": status.account_currency
                    },
                    "trading": {
                        "is_allowed": status.is_trading_allowed,
                        "risk_level": status.overall_risk_level.value,
                        "blocked_reasons": status.trading_blocked_reasons
                    },
                    "trade_size_in_usd": status.trade_size_in_usd,
                    "max_risk_per_trade_percent": status.max_risk_per_trade_percent,
                    "daily": {
                        "net_profit_usd": status.daily_net_profit_usd,
                        "net_profit_percent": status.daily_net_profit_percent,
                        "trades": status.daily_trades,
                        "win_rate": status.daily_win_rate,
                        "remaining_loss_percent": status.daily_remaining_loss_percent,
                        "consecutive_losses": status.daily_consecutive_losses
                    },
                    "monthly": {
                        "net_profit_usd": status.monthly_net_profit_usd,
                        "net_profit_percent": status.monthly_net_profit_percent,
                        "trades": status.monthly_trades,
                        "win_rate": status.monthly_win_rate,
                        "remaining_loss_percent": status.monthly_remaining_loss_percent
                    },
                    "ytd": {
                        "net_profit_usd": status.ytd_net_profit_usd,
                        "net_profit_percent": status.ytd_net_profit_percent,
                        "trades": status.ytd_trades,
                        "win_rate": status.ytd_win_rate,
                        "remaining_loss_percent": status.ytd_remaining_loss_percent
                    },
                    "drawdown": {
                        "current_percent": status.current_drawdown_percent,
                        "max_percent": status.max_drawdown_percent
                    }
                }
            })
        
        return jsonify({
            "success": True,
            "status": status.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Error getting portfolio status: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# CONFIGURATION - UNIFIED CRUD
# ============================================================

@app.route(f'{API_PREFIX}/portfolio/config', methods=['GET', 'PUT'])
def portfolio_config():
    """
    GET: Get current portfolio configuration.
    PUT: Update portfolio configuration fields.
    """
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        if request.method == 'GET':
            return jsonify({
                "success": True,
                "config": portfolio_service.config.to_dict()
            })
        
        # PUT - Update config
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Filter valid fields
        updates = {}
        invalid_fields = []
        valid_fields = [
    'trade_size_in_usd',

    'max_daily_loss_percent',
    'max_daily_trades',
    'max_daily_win_target_percent',

    'max_monthly_loss_percent',
    'max_monthly_trades',
    'max_monthly_win_target_percent',

    'max_ytd_loss_percent',

    'max_risk_per_trade_percent',
    'max_drawdown_percent',

    'max_consecutive_losses',
    'max_daily_consecutive_losses',

    'funded_account_type',
    'funded_account_rules',

    'trading_start_hour',
    'trading_end_hour',

    # Trade execution limits
    'max_simultaneous_trades',
    'max_trades_per_symbol',
    'max_spread',
    'trade_deviation',

    # Automatic execution settings
    'auto_max_simultaneous_trades',
    'auto_max_trades_per_symbol',
    'auto_max_spread',
    'auto_trade_deviation',

    # Break-even settings
    'enable_breakeven',
    'auto_breakeven_usd',

    # Trailing stop settings
    'enable_auto_trailing_stop',
    'auto_trailing_stop_usd'
]
        
        for key, value in data.items():
            if value is not None:
                if key in valid_fields:
                    updates[key] = value
                else:
                    invalid_fields.append(key)
        
        if invalid_fields:
            return jsonify({
                "error": f"Invalid fields: {invalid_fields}",
                "valid_fields": valid_fields
            }), 400
        
        if not updates:
            return jsonify({"error": "No valid updates provided"}), 400
        
        success = portfolio_service.update_config(updates)
        
        if success:
            return jsonify({
                "success": True,
                "message": "Configuration updated successfully",
                "updated_fields": list(updates.keys()),
                "config": portfolio_service.config.to_dict()
            })
        else:
            return jsonify({"error": "Failed to update configuration"}), 500
        
    except Exception as e:
        logger.error(f"Error in portfolio config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route(f'{API_PREFIX}/portfolio/config/<field_name>', methods=['GET', 'PUT'])
def portfolio_config_field(field_name):
    """
    GET: Get a specific configuration field.
    PUT: Update a specific configuration field.
    """
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        valid_fields = [
            'trade_size_in_usd',
            'max_daily_loss_percent', 'max_daily_trades', 'max_daily_win_target_percent',
            'max_monthly_loss_percent', 'max_monthly_trades', 'max_monthly_win_target_percent',
            'max_ytd_loss_percent',
            'max_risk_per_trade_percent',
            'max_drawdown_percent',
            'max_consecutive_losses', 'max_daily_consecutive_losses',
            'funded_account_type', 'funded_account_rules',
            'trading_start_hour', 'trading_end_hour'
        ]
        
        if field_name not in valid_fields:
            return jsonify({
                "error": f"Field '{field_name}' not found",
                "valid_fields": valid_fields
            }), 404
        
        if request.method == 'GET':
            return jsonify({
                "success": True,
                "field": field_name,
                "value": getattr(portfolio_service.config, field_name)
            })
        
        # PUT - Update field
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        value = data.get('value')
        if value is None and data.get('value') is not False:
            return jsonify({"error": "Value cannot be None"}), 400
        
        success = portfolio_service.update_config({field_name: value})
        
        if success:
            return jsonify({
                "success": True,
                "message": f"Field '{field_name}' updated successfully",
                "field": field_name,
                "new_value": value,
                "config": portfolio_service.config.to_dict()
            })
        else:
            return jsonify({"error": "Failed to update field"}), 500
        
    except Exception as e:
        logger.error(f"Error in portfolio config field: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# TRADING PERMISSION CHECKS
# ============================================================

@app.route(f'{API_PREFIX}/portfolio/check_trading_allowed', methods=['POST'])
def check_trading_allowed():
    """
    Check if trading is allowed based on portfolio risk limits.
    
    Request Body:
        {
            "trade_risk_percent": float (optional)
        }
    """
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        data = request.get_json() or {}
        trade_risk_percent = data.get('trade_risk_percent')
        
        is_allowed, reasons, risk_level = portfolio_service.check_trading_allowed(
            trade_risk_percent=trade_risk_percent
        )

        # AI_MarketReplay RISK_APPROVAL. Recorded only when the caller names a
        # symbol, because the event has to attach to that symbol's pending
        # candidate; check_trading_allowed itself is portfolio-wide and has no
        # symbol to attach to. A rejection here is the last pre-trade event a
        # candidate ever gets, which makes it one of the more informative rows
        # in a replay. OFF unless AIREPLAY_RECORD_LIVE is set.
        try:
            from ai.aireplay.live_recording import record_risk_approval

            if data.get('symbol'):
                record_risk_approval(
                    data.get('symbol'), is_allowed,
                    {"risk_level": risk_level.value, "reasons": reasons,
                     "requested_risk_percent": trade_risk_percent})
        except Exception:
            pass

        return jsonify({
            "success": True,
            "is_trading_allowed": is_allowed,
            "risk_level": risk_level.value,
            "reasons": reasons,
            "requested_risk_percent": trade_risk_percent,
            "max_risk_per_trade_percent": portfolio_service.config.max_risk_per_trade_percent
        })
        
    except Exception as e:
        logger.error(f"Error checking trading allowed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route(f'{API_PREFIX}/portfolio/max_risk_for_trade', methods=['GET'])
def get_max_risk_for_trade():
    """Get the maximum risk percentage allowed for a trade."""
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        max_risk = portfolio_service.get_max_risk_for_trade()
        
        return jsonify({
            "success": True,
            "max_risk_per_trade_percent": max_risk
        })
        
    except Exception as e:
        logger.error(f"Error getting max risk: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# STATISTICS - UNIFIED
# ============================================================

@app.route(f'{API_PREFIX}/portfolio/stats', methods=['GET'])
def get_portfolio_stats():
    """
    Portfolio statistics for a period, computed from the stored trades.

    THIS USED TO READ PRE-COMPUTED FIRESTORE DOCUMENTS, AND ALWAYS 404ed.
    --------------------------------------------------------------------
    It fetched `daily_stats/<date>`, `monthly_stats/<month>` and
    `ytd_stats/<year>` from Firestore and returned 404 when the document was
    missing -- with no fallback. Nothing has written those documents since
    trades moved to MongoDB, so every call to this endpoint returned
    "No daily data found" regardless of how much had actually been traded.

    It now computes from the same MongoDB-backed trade list the risk checks
    use, so the number this reports and the number that gates trading cannot
    disagree. Reading a cached document while the limits read something else is
    precisely how a dashboard ends up reassuring you about a day it has no data
    for.

    Query Parameters:
        period: daily | monthly | ytd   (default: daily)
        date:   YYYY-MM-DD for daily, YYYY-MM for monthly, YYYY for ytd
    """
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503

        period = request.args.get('period', 'daily').lower()
        requested = request.args.get('date')
        now = datetime.now(timezone.utc)

        if period == 'daily':
            key = requested or now.strftime("%Y-%m-%d")
            trades = portfolio_service._get_trades_for_date(key)
        elif period == 'monthly':
            key = requested or now.strftime("%Y-%m")
            trades = portfolio_service._get_trades_for_month(key)
        elif period == 'ytd':
            key = requested or str(now.year)
            try:
                year = int(key)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": f"Invalid year: {key}"}), 400
            trades = portfolio_service._get_trades_for_year(year)
        else:
            return jsonify({
                "success": False,
                "error": f"Invalid period: {period}. Use daily, monthly or ytd."
            }), 400

        stats = portfolio_service._calculate_stats_from_trades(
            trades, portfolio_service.get_account_balance())

        # 200 with zero trades, not 404. "Nothing was traded today" is a real
        # and useful answer; 404 says the endpoint does not exist and sends the
        # caller looking for a bug that is not there.
        return jsonify({
            "success": True,
            "period": period,
            "date": key,
            "source": "mongodb",
            "trades_count": len(trades),
            "stats": stats
        })

    except Exception as e:
        logger.error(f"Error getting portfolio stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route(f'{API_PREFIX}/portfolio/drawdown', methods=['GET'])
def get_drawdown_info():
    """Get drawdown information."""
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        return jsonify({
            "success": True,
            "drawdown": {
                "current_percent": portfolio_service.get_current_drawdown_percent(),
                "max_percent": portfolio_service.get_max_drawdown_percent()
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting drawdown info: {e}")
        return jsonify({"error": str(e)}), 500


@app.route(f'{API_PREFIX}/portfolio/funded_compliance', methods=['GET'])
def get_funded_compliance():
    """Get funded account compliance information."""
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        status = portfolio_service.get_status()
        
        return jsonify({
            "success": True,
            "account_type": status.funded_account_compliance.get("type"),
            "compliant": status.funded_account_compliance.get("compliant"),
            "violations": status.funded_account_compliance.get("violations", [])
        })
        
    except Exception as e:
        logger.error(f"Error getting funded compliance: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# REFRESH
# ============================================================

@app.route(f'{API_PREFIX}/portfolio/refresh', methods=['POST'])
def refresh_stats():
    """Force refresh statistics from MongoDB."""
    try:
        if not portfolio_service:
            return jsonify({"error": "Portfolio service not initialized"}), 503
        
        success = portfolio_service.refresh_stats()
        
        return jsonify({
            "success": success,
            "message": "Statistics refreshed successfully" if success else "Failed to refresh",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error refreshing stats: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# MAIN
# ============================================================

def main():
    """Start the Portfolio Risk Controller API."""
    global portfolio_service
    
    import argparse
    parser = argparse.ArgumentParser(description='Portfolio Risk Controller API')
    parser.add_argument('--port', type=int, default=5010, help='Port to run the API on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    # Initialize Firebase service (optional)
    firebase_service = None
    try:
        try:
            from core.firebase import get_firebase_service
        except ImportError:
            from firebase import get_firebase_service
        
        firebase_service = get_firebase_service()
        logger.info("✅ Firebase service connected")
    except Exception as e:
        logger.warning(f"⚠️ Firebase service not available: {e}")
    
    # Initialize portfolio service
    portfolio_service = init_portfolio_service()
    
    logger.info("=" * 70)
    logger.info("🚀 PORTFOLIO RISK CONTROLLER API")
    logger.info("=" * 70)
    logger.info(f"   Host: {args.host}")
    logger.info(f"   Port: {args.port}")
    logger.info(f"   Debug: {args.debug}")
    logger.info(f"   API Prefix: {API_PREFIX}")
    logger.info("=" * 70)
    logger.info("📊 ENDPOINTS:")
    logger.info("   GET  /health")
    logger.info("   GET  /api/v1/portfolio/status")
    logger.info("   GET  /api/v1/portfolio/config")
    logger.info("   PUT  /api/v1/portfolio/config")
    logger.info("   GET  /api/v1/portfolio/config/<field>")
    logger.info("   PUT  /api/v1/portfolio/config/<field>")
    logger.info("   POST /api/v1/portfolio/check_trading_allowed")
    logger.info("   GET  /api/v1/portfolio/max_risk_for_trade")
    logger.info("   GET  /api/v1/portfolio/stats")
    logger.info("   GET  /api/v1/portfolio/drawdown")
    logger.info("   GET  /api/v1/portfolio/funded_compliance")
    logger.info("   POST /api/v1/portfolio/refresh")
    logger.info("=" * 70)
    
    try:
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Error: {e}")


if __name__ == "__main__":
    main()