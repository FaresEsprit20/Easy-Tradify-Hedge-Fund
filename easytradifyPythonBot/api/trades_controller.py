# ============================================================
# TRADES CONTROLLER API
# ============================================================
# FILE: api/trades_controller.py
# PORT: 5011
#
# ✅ Full CRUD over the trades collection (MongoDB)
# ✅ Pagination, sorting, filtering, search -- all bounded and whitelisted
# ✅ Delete strategies: soft (default), archive, hard (gated)
# ✅ Consistent URL pattern: /api/v1/trades/...
# ✅ Consistent response envelope on success AND failure
# ============================================================

# Console encoding, before anything logs. This module's log lines carry
# emoji; on a Windows cp1252 console writing one raises UnicodeEncodeError
# rather than printing a replacement character. That is not cosmetic -- the
# identical failure silently disabled the GNN for this entire project.
try:
    import core.console_safe  # noqa: F401
except Exception:
    pass

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mongo import (  # noqa: E402
    DeleteMode,
    TradeNotFound,
    TradeStorageError,
    TradeValidationError,
    get_trades_service,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1/trades"
trades_bp = Blueprint("trades", __name__)


# ============================================================
# RESPONSE ENVELOPE
# ============================================================
# Every response -- success or failure -- has the same top-level shape, so a
# client never has to branch on which kind it received before it can find the
# error. A `request_id` is echoed on both so a user-reported failure can be
# located in the logs without guessing from timestamps.

def _envelope(data: Any = None, meta: Optional[Dict[str, Any]] = None,
              error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "success": error is None,
        "data": data,
        "error": error,
        "request_id": getattr(request, "_trade_request_id", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if meta:
        body["meta"] = meta
    return body


def _ok(data: Any = None, meta: Optional[Dict[str, Any]] = None,
        status: int = 200) -> Tuple[Any, int]:
    return jsonify(_envelope(data=data, meta=meta)), status


def _fail(code: str, message: str, status: int,
          details: Any = None) -> Tuple[Any, int]:
    return jsonify(_envelope(error={"code": code, "message": message,
                                    "details": details})), status


def handle_errors(func):
    """
    Map exception TYPE to HTTP status, once, for every route.

    The three service exceptions mean genuinely different things and must not
    collapse into one status: a validation error is the caller's to fix (400),
    a missing trade is not an error condition at all (404), and a database
    outage is ours and is retryable (503). Returning 500 for all three tells a
    client nothing and makes retry logic impossible to write.

    An unexpected exception is logged in full and returned WITHOUT its text:
    internal messages carry table names, queries and occasionally connection
    strings.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        request._trade_request_id = uuid.uuid4().hex[:12]
        try:
            return func(*args, **kwargs)
        except TradeValidationError as exc:
            return _fail("validation_error", str(exc), 400)
        except TradeNotFound as exc:
            return _fail("not_found", str(exc), 404)
        except TradeStorageError as exc:
            logger.error("[%s] storage error: %s",
                         request._trade_request_id, exc)
            return _fail("storage_unavailable",
                         "The trades database is unavailable. Retry shortly.",
                         503)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] unhandled error in %s: %s",
                             request._trade_request_id, func.__name__, exc)
            return _fail("internal_error",
                         "An unexpected error occurred.", 500)
    return wrapper


# ============================================================
# REQUEST PARSING
# ============================================================

def _bool_arg(name: str, default: bool = False) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise TradeValidationError(
        f"{name} must be a boolean (true/false), got {raw!r}")


def _int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise TradeValidationError(f"{name} must be an integer, got {raw!r}")


def _json_body() -> Dict[str, Any]:
    """
    The JSON body, or a clear 400.

    `silent=True` because Flask's own parse failure raises a 400 whose message
    is an HTML page; a JSON API must answer with JSON even when the request
    was malformed.
    """
    body = request.get_json(silent=True)
    if body is None:
        raise TradeValidationError(
            "a JSON body is required (send Content-Type: application/json)")
    if not isinstance(body, dict):
        raise TradeValidationError("the JSON body must be an object")
    return body


# ============================================================
# READ
# ============================================================

@trades_bp.route(API_PREFIX, methods=["GET"])
@handle_errors
def list_trades():
    """
    GET /api/v1/trades

    Query parameters
      page, page_size          pagination (page_size capped by the service)
      sort_by, sort_dir        whitelisted field, asc|desc
      symbol, status,          equality filters (whitelisted)
      direction, close_reason,
      result, ticket
      opened_from, opened_to   ISO-8601 window on opened_at
      search                   symbol prefix, anchored and escaped
      include_deleted          include soft-deleted trades
      include_heavy            attach price_evolution and the analyses

    price_evolution and both analyses are EXCLUDED by default. A page of 25
    trades with them attached is tens of megabytes; the endpoint would time
    out on exactly the dataset it exists to browse.
    """
    filters = {key: request.args.get(key)
               for key in ("symbol", "status", "direction", "close_reason",
                           "result", "ticket")
               if request.args.get(key)}

    result = get_trades_service().list_trades(
        page=_int_arg("page", 1),
        page_size=_int_arg("page_size", 25),
        sort_by=request.args.get("sort_by", "opened_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
        filters=filters,
        opened_from=request.args.get("opened_from"),
        opened_to=request.args.get("opened_to"),
        include_deleted=_bool_arg("include_deleted", False),
        include_heavy=_bool_arg("include_heavy", False),
        search=request.args.get("search"),
    )
    return _ok(result["items"], meta={
        "pagination": result["pagination"],
        "sort": result["sort"],
        "filters": filters,
        "heavy_fields_included": result["heavy_fields_included"],
    })


def _query_kwargs() -> Dict[str, Any]:
    """The filter/search/range parameters shared by every query endpoint."""
    filters = {key: request.args.get(key)
               for key in ("symbol", "status", "direction", "close_reason",
                           "result", "ticket")
               if request.args.get(key)}
    ranges = {}
    for field in ("profit_usd", "profit_percent", "volume", "duration_seconds"):
        bounds = {edge: request.args.get(f"{field}_{edge}")
                  for edge in ("min", "max")
                  if request.args.get(f"{field}_{edge}") is not None}
        if bounds:
            ranges[field] = bounds
    return {
        "filters": filters,
        "ranges": ranges,
        "opened_from": request.args.get("opened_from"),
        "opened_to": request.args.get("opened_to"),
        "include_deleted": _bool_arg("include_deleted", False),
        "search": request.args.get("search") or request.args.get("q"),
    }


@trades_bp.route(f"{API_PREFIX}/search", methods=["GET"])
@handle_errors
def search_trades():
    """
    GET /api/v1/trades/search?q=EURUSD

    Free-text across symbol, close_reason, comment and trade_id. The symbol
    clause is anchored so it uses the index; every term is escaped, so a user
    string is never compiled as a pattern.
    """
    if not (request.args.get("q") or request.args.get("search")):
        raise TradeValidationError("q is required")
    result = get_trades_service().list_trades(
        page=_int_arg("page", 1), page_size=_int_arg("page_size", 25),
        sort_by=request.args.get("sort_by", "opened_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
        include_heavy=_bool_arg("include_heavy", False),
        **_query_kwargs())
    return _ok(result["items"], meta={"pagination": result["pagination"],
                                      "sort": result["sort"]})


@trades_bp.route(f"{API_PREFIX}/query", methods=["POST"])
@handle_errors
def query_trades():
    """
    POST /api/v1/trades/query            -- filters in a JSON body

    The preferred way to filter trades. The GET list endpoint takes query
    parameters, which cannot express "leverage 300 OR 500", a profit range and
    two date windows without turning into an unreadable URL -- and two of its
    filters (close_reason, result) never matched a stored trade at all.

    Body (every filter optional; a list means "any of"):

        {
          "page": 1, "size": 25,
          "sortField": "closedAt", "sortDirection": "DESC",
          "status": "CLOSED",
          "outcome": ["WIN"],                 WIN | LOSS | BREAKEVEN | UNSCORED
          "leverage": [300, 500],
          "symbol": ["EURUSD"], "direction": "SELL",
          "closeReason": ["TAKE_PROFIT", "STOP_LOSS"],
          "profitUsd": {"min": 0, "max": 50},
          "volume": {"min": 0.1}, "durationSeconds": {"max": 3600},
          "openedFrom": "2026-09-11T00:00:00Z", "closedTo": "...",
          "search": "EUR",
          "includeHeavy": false, "withSummary": true
        }

    Unknown keys are a 400, not ignored: a mistyped "levrage" that was silently
    dropped would return every trade and look like a working filter.

    GET /api/v1/trades/filters lists every accepted field with the values that
    currently exist.
    """
    body = request.get_json(silent=True)
    if body is None and request.data:
        raise TradeValidationError("request body must be valid JSON")
    if body is not None and not isinstance(body, dict):
        raise TradeValidationError("request body must be a JSON object")

    result = get_trades_service().query_trades(body or {})
    return _ok(result["items"], meta={
        "pagination": result["pagination"],
        "sort": result["sort"],
        "appliedFilters": result["appliedFilters"],
        "summary": result.get("summary"),
    })


@trades_bp.route(f"{API_PREFIX}/filters", methods=["GET"])
@handle_errors
def trade_filters():
    """
    GET /api/v1/trades/filters

    Every filter POST /query accepts, with the values present in the collection
    and how many trades carry each -- so a UI can build its controls from data
    and never offer a leverage or symbol that would return nothing.
    """
    return _ok(get_trades_service().filter_catalog())


@trades_bp.route(f"{API_PREFIX}/count", methods=["GET"])
@handle_errors
def count_trades():
    """GET /api/v1/trades/count -- how many match, without fetching them."""
    return _ok({"count": get_trades_service().count_trades(**_query_kwargs())})


@trades_bp.route(f"{API_PREFIX}/distinct/<field>", methods=["GET"])
@handle_errors
def distinct_values(field: str):
    """
    GET /api/v1/trades/distinct/symbol

    The values a filter dropdown needs, without downloading every trade to
    derive them client-side.
    """
    return _ok(get_trades_service().distinct_values(
        field, include_deleted=_bool_arg("include_deleted", False)))


@trades_bp.route(f"{API_PREFIX}/<trade_id>/exists", methods=["GET"])
@handle_errors
def trade_exists(trade_id: str):
    """GET /api/v1/trades/<id>/exists -- existence without the document."""
    return _ok({"trade_id": trade_id,
                "exists": get_trades_service().trade_exists(trade_id)})


@trades_bp.route(f"{API_PREFIX}/stats", methods=["GET"])
@handle_errors
def trade_stats():
    """GET /api/v1/trades/stats -- counts, win rate and net profit."""
    return _ok(get_trades_service().stats(symbol=request.args.get("symbol")))


@trades_bp.route(f"{API_PREFIX}/stats/performance", methods=["GET"])
@handle_errors
def performance_stats():
    """
    GET /api/v1/trades/stats/performance

    Win rate, expectancy, payoff and profit factor. Expectancy is reported in
    dollars AND in R -- R is the one comparable across symbols, since $10 on
    gold and $10 on EURUSD are not the same risk.
    """
    return _ok(get_trades_service().performance_stats(**_query_kwargs()))


@trades_bp.route(f"{API_PREFIX}/stats/by-symbol", methods=["GET"])
@handle_errors
def stats_by_symbol():
    """GET /api/v1/trades/stats/by-symbol -- per-symbol breakdown."""
    return _ok(get_trades_service().stats_by_symbol(
        limit=_int_arg("limit", 50), **_query_kwargs()))


@trades_bp.route(f"{API_PREFIX}/stats/timeseries", methods=["GET"])
@handle_errors
def stats_timeseries():
    """GET /api/v1/trades/stats/timeseries?granularity=day|week|month"""
    return _ok(get_trades_service().stats_timeseries(
        granularity=request.args.get("granularity", "day"), **_query_kwargs()))


# ============================================================
# DIAGNOSTICS -- so data defects surface without anyone looking
# ============================================================

@trades_bp.route(f"{API_PREFIX}/diagnostics", methods=["GET"])
@handle_errors
def diagnostics():
    """
    GET /api/v1/trades/diagnostics?limit=100&only_open=true&since_hours=24

    Scans recent trades and reports every way the record is wrong: a starved
    price_evolution, an unreachable analysis, an ambiguous close reason, a
    direction that disagrees with itself, a document nearing the size limit.

    Returns 200 with the report; `healthy` is TRI-STATE -- null when nothing
    was examined, because an empty collection cannot demonstrate that the
    pipeline works.
    """
    from core.mongo.trade_data_monitor import scan
    since = request.args.get("since_hours")
    report = scan(limit=_int_arg("limit", 100),
                  only_open=_bool_arg("only_open", False),
                  since_hours=int(since) if since else None)
    return _ok(report)


@trades_bp.route(f"{API_PREFIX}/diagnostics/self-check", methods=["POST"])
@handle_errors
def diagnostics_self_check():
    """
    POST /api/v1/trades/diagnostics/self-check

    Proves the monitor can FAIL -- feeds it a deliberately broken trade and
    requires the known defects to be detected, then a clean one and requires
    silence. A monitor that reports healthy on garbage is a stub.
    """
    from core.mongo.trade_data_monitor import self_check as monitor_check
    from ai.trade_repository import self_check as repo_check
    return _ok({"monitor": monitor_check(), "repository": repo_check()})


# ============================================================
# BULK
# ============================================================

@trades_bp.route(f"{API_PREFIX}/bulk", methods=["POST"])
@handle_errors
def bulk_upsert():
    """POST /api/v1/trades/bulk  {"trades": [...]} -- unordered bulk upsert."""
    body = _json_body()
    trades = body.get("trades")
    if not isinstance(trades, list):
        raise TradeValidationError("body must contain a 'trades' array")
    return _ok(get_trades_service().bulk_upsert(trades))


@trades_bp.route(f"{API_PREFIX}/bulk-delete", methods=["POST"])
@handle_errors
def bulk_delete():
    """
    POST /api/v1/trades/bulk-delete  {"trade_ids": [...], "mode": "soft"}

    Every id goes through the single-delete path, so OPEN trades are still
    refused and hard delete still needs confirmation. A bulk route that
    skipped those checks would be a way around the guards.
    """
    body = _json_body()
    ids = body.get("trade_ids")
    if not isinstance(ids, list) or not ids:
        raise TradeValidationError("body must contain a non-empty 'trade_ids' array")
    raw_mode = str(body.get("mode") or "soft").lower()
    try:
        mode = DeleteMode(raw_mode)
    except ValueError:
        raise TradeValidationError(
            f"mode must be one of {[m.value for m in DeleteMode]}")
    return _ok(get_trades_service().bulk_delete(
        ids, mode=mode, reason=body.get("reason"),
        actor=request.headers.get("X-Actor", "api"),
        confirm=bool(body.get("confirm"))))


@trades_bp.route(f"{API_PREFIX}/health", methods=["GET"])
@handle_errors
def trades_health():
    """
    GET /api/v1/trades/health

    Returns 503 when the database is unreachable, so a load balancer or
    monitor sees the failure in the STATUS CODE. A health endpoint that
    answers 200 with {"healthy": false} is not a health endpoint.
    """
    status = get_trades_service().get_status()
    return (jsonify(_envelope(data=status)), 200 if status.get("healthy") else 503)


@trades_bp.route(f"{API_PREFIX}/<trade_id>", methods=["GET"])
@handle_errors
def get_trade(trade_id: str):
    """GET /api/v1/trades/<id> -- one trade, in full."""
    return _ok(get_trades_service().get_trade(
        trade_id, include_deleted=_bool_arg("include_deleted", False)))


@trades_bp.route(f"{API_PREFIX}/<trade_id>/price-evolution", methods=["GET"])
@handle_errors
def get_price_evolution(trade_id: str):
    """
    GET /api/v1/trades/<id>/price-evolution?offset=&limit=

    Paged separately from the trade because it is the large part -- ~180
    points at ~20KB. `$slice` pages it server-side, so the rest of the array
    never leaves the database.
    """
    result = get_trades_service().get_price_evolution(
        trade_id, offset=_int_arg("offset", 0), limit=_int_arg("limit", 500))
    return _ok(result["points"], meta={"pagination": result["pagination"],
                                       "trade_id": result["trade_id"]})


# ============================================================
# WRITE
# ============================================================

@trades_bp.route(API_PREFIX, methods=["POST"])
@handle_errors
def create_trade():
    """
    POST /api/v1/trades

    `?upsert=true` makes it idempotent by trade_id -- which is what a retry
    after a timeout needs, so one position cannot become two records.
    """
    body = _json_body()
    service = get_trades_service()
    if _bool_arg("upsert", False):
        return _ok(service.upsert_trade(body), status=200)
    return _ok(service.create_trade(body), status=201)


@trades_bp.route(f"{API_PREFIX}/<trade_id>", methods=["PATCH"])
@handle_errors
def update_trade(trade_id: str):
    """PATCH /api/v1/trades/<id> -- merge fields. Identity fields refused."""
    return _ok(get_trades_service().update_trade(trade_id, _json_body()))


@trades_bp.route(f"{API_PREFIX}/<trade_id>/price-evolution", methods=["POST"])
@handle_errors
def append_price_point(trade_id: str):
    """POST /api/v1/trades/<id>/price-evolution -- append one point."""
    count = get_trades_service().append_price_point(trade_id, _json_body())
    return _ok({"trade_id": trade_id, "price_evolution_count": count},
               status=201)


@trades_bp.route(f"{API_PREFIX}/<trade_id>/close", methods=["POST"])
@handle_errors
def close_trade(trade_id: str):
    """POST /api/v1/trades/<id>/close -- attach the close record."""
    body = _json_body()
    return _ok(get_trades_service().close_trade(
        trade_id,
        close_data=body.get("close_data") or body,
        analysis_at_close=body.get("analysis_at_close")))


# ============================================================
# DELETE
# ============================================================

@trades_bp.route(f"{API_PREFIX}/<trade_id>", methods=["DELETE"])
@handle_errors
def delete_trade(trade_id: str):
    """
    DELETE /api/v1/trades/<id>?mode=soft|archive|hard

    soft (default)  reversible; hidden from queries, restorable
    archive         moved to the archive collection, still recoverable
    hard            destroyed; requires confirm=true

    An OPEN trade is refused unless allow_open=true: deleting the record of a
    position that is still live at the broker leaves money at risk with
    nothing describing it.
    """
    raw_mode = (request.args.get("mode") or "soft").lower()
    try:
        mode = DeleteMode(raw_mode)
    except ValueError:
        raise TradeValidationError(
            f"mode must be one of {[m.value for m in DeleteMode]}, "
            f"got {raw_mode!r}")

    result = get_trades_service().delete_trade(
        trade_id,
        mode=mode,
        reason=request.args.get("reason"),
        actor=request.headers.get("X-Actor", "api"),
        confirm=_bool_arg("confirm", False),
        allow_open=_bool_arg("allow_open", False),
    )
    return _ok(result)


@trades_bp.route(f"{API_PREFIX}/<trade_id>/restore", methods=["POST"])
@handle_errors
def restore_trade(trade_id: str):
    """POST /api/v1/trades/<id>/restore -- undo a soft delete."""
    return _ok(get_trades_service().restore_trade(trade_id))


@trades_bp.route(f"{API_PREFIX}/purge", methods=["POST"])
@handle_errors
def purge_trades():
    """
    POST /api/v1/trades/purge?older_than_days=30&confirm=true

    Without confirm this is a DRY RUN that reports how many trades it would
    destroy. The blast radius is visible before anything is lost.
    """
    return _ok(get_trades_service().purge_deleted(
        older_than_days=_int_arg("older_than_days", 30),
        confirm=_bool_arg("confirm", False),
        limit=_int_arg("limit", 1000)))


# ============================================================
# APP
# ============================================================

def create_app() -> Flask:
    """The controller as a standalone app, or register the blueprint yourself."""
    app = Flask(__name__)
    app.register_blueprint(trades_bp)

    @app.errorhandler(404)
    def _not_found(_):
        # Flask's default 404 is HTML. A JSON API answering HTML breaks every
        # client's error handling at exactly the moment it is needed.
        return _fail("route_not_found",
                     f"No route for {request.method} {request.path}", 404)

    @app.errorhandler(405)
    def _bad_method(_):
        return _fail("method_not_allowed",
                     f"{request.method} is not allowed on {request.path}", 405)

    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    port = int(os.getenv("TRADES_API_PORT", "5011"))
    print("=" * 60)
    print("TRADES CONTROLLER API")
    print("=" * 60)
    for rule in (
        "GET    /api/v1/trades",
        "GET    /api/v1/trades/stats",
        "GET    /api/v1/trades/health",
        "GET    /api/v1/trades/<id>",
        "GET    /api/v1/trades/<id>/price-evolution",
        "POST   /api/v1/trades            (?upsert=true)",
        "PATCH  /api/v1/trades/<id>",
        "POST   /api/v1/trades/<id>/price-evolution",
        "POST   /api/v1/trades/<id>/close",
        "DELETE /api/v1/trades/<id>       (?mode=soft|archive|hard&confirm=)",
        "POST   /api/v1/trades/<id>/restore",
        "POST   /api/v1/trades/purge      (?older_than_days=&confirm=)",
    ):
        print(f"   {rule}")
    print("=" * 60)
    create_app().run(host="0.0.0.0", port=port, debug=False)
