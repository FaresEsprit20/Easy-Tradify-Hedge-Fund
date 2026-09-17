# ============================================================
# monitor/firebase_helpers.py -- COMPATIBILITY SHIM
# ============================================================
# The implementation moved to monitor/trade_persistence.py, which stores every
# trade in MongoDB and never touches Firebase.
#
# This module exists only so callers that have not been migrated yet keep
# working unchanged (api/execute_copy_trade.py, monitor/monitor_core_crypto.py,
# and tests that import it by this name). It forwards to trade_persistence and
# DISCARDS any `firebase_service` argument -- nothing here uses it, and nothing
# here connects to Firebase.
#
# monitor/monitor_core.py does not import this module.
#
# New code should import from monitor.trade_persistence directly.
# ============================================================

from monitor import trade_persistence as _tp

# Re-export everything, underscore helpers included (_direction_of_record,
# _normalise_direction, _risk_state, make_json_safe, ...). A plain `import *`
# would skip underscore names, and several callers import those explicitly.
globals().update({name: value for name, value in vars(_tp).items()
                  if not name.startswith("__")})


# ------------------------------------------------------------------
# Old names. Each drops the `firebase_service` argument, whether it arrives
# positionally (first) or by keyword, and forwards the rest.
# ------------------------------------------------------------------

def save_trade_open_to_firebase(firebase_service=None, *args, **kwargs):
    return _tp.save_trade_open(*args, **kwargs)


def update_trade_price_in_firebase(firebase_service=None, *args, **kwargs):
    return _tp.update_trade_price(*args, **kwargs)


def save_analysis_at_close_to_firebase(firebase_service=None, *args, **kwargs):
    return _tp.save_analysis_at_close(*args, **kwargs)


def save_trade_close_to_firebase(firebase_service=None, *args, **kwargs):
    return _tp.save_trade_close(*args, **kwargs)


def save_trailing_stop_to_firebase(firebase_service=None, *args, **kwargs):
    return _tp.save_trailing_stop(*args, **kwargs)


def process_webhook_close(firebase_service=None, *args, **kwargs):
    return _tp.process_webhook_close(*args, **kwargs)


def process_trailing_webhook(firebase_service=None, *args, **kwargs):
    return _tp.process_trailing_webhook(*args, **kwargs)


def monitor_position_updates(firebase_service=None, *args, **kwargs):
    return _tp.monitor_position_updates(*args, **kwargs)


def _is_trade_closed_in_firebase(firebase_service=None, ticket=None):
    return _tp.is_trade_closed(ticket)
