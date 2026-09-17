# core/mongo/trade_query.py
"""
JSON-body trade queries: validation and translation into a MongoDB query.

WHY A SEPARATE MODULE
---------------------
The translation is pure -- a dict in, a query out -- so it lives apart from the
service and can be tested without a database. That matters here more than
usual, because the bug this module replaces was a translation bug that no
database test would have caught: the GET filters for `close_reason` and
`result` targeted TOP-LEVEL fields that exist on zero stored trades. The real
values live under `close_data`, so `?close_reason=STOP_LOSS` returned an empty
page instead of 89 trades, and did so without an error. An empty result is a
perfectly valid answer, which is exactly why it went unnoticed.

Every filterable name below is therefore mapped to the path the data ACTUALLY
occupies, and `FIELD_PATHS` is the single place that mapping lives.

THE BODY
--------
Named to match the platform's PaginationAndFilteringDto (page, size, sortField,
sortDirection) so the Java and Angular layers pass it through unchanged. Every
filter accepts a scalar or a list; a list means "any of".

    {
      "page": 1, "size": 25,
      "sortField": "closedAt", "sortDirection": "DESC",

      "status":      ["CLOSED"],
      "outcome":     ["WIN"],            WIN | LOSS | BREAKEVEN | UNSCORED
      "leverage":    [300, 500],
      "symbol":      ["EURUSD", "GBPUSD"],
      "direction":   "SELL",
      "closeReason": ["TAKE_PROFIT"],

      "profitUsd":       {"min": 0, "max": 50},
      "volume":          {"min": 0.1},
      "durationSeconds": {"max": 3600},

      "openedFrom": "2026-09-11T00:00:00Z", "openedTo": "...",
      "closedFrom": "...",                  "closedTo": "...",

      "search": "EUR",
      "includeDeleted": false,
      "includeHeavy": false,
      "withSummary": true
    }
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


class TradeQueryError(ValueError):
    """A body that cannot be turned into a safe query. Always a 400."""


# ============================================================
# WHERE THE DATA ACTUALLY LIVES
# ============================================================
# Confirmed against the stored collection, not assumed from a schema:
#   close_reason / profit / duration   -> close_data.*   (top level: 0 of 120)
#   leverage                            -> analysis_at_open.m1_analysis_raw
#                                          .account_info.leverage  (120 of 120)
LEVERAGE_NESTED = "analysis_at_open.m1_analysis_raw.account_info.leverage"

FIELD_PATHS: Dict[str, str] = {
    "symbol": "symbol",
    "status": "status",
    "direction": "direction",
    "ticket": "ticket",
    "tradeId": "trade_id",
    "closeReason": "close_data.close_reason",
    # leverage is special-cased in _leverage_clause -- see there.
}

RANGE_PATHS: Dict[str, str] = {
    "profitUsd": "close_data.profit_usd",
    "profitPercent": "close_data.profit_percent",
    "volume": "entry.volume",
    "durationSeconds": "close_data.duration_seconds",
    "exitSlippage": "close_data.exit_slippage",
    "exitSpread": "close_data.exit_spread",
}

# The two timestamps are stored as DIFFERENT BSON types, confirmed on all 120
# trades: `opened_at` is a naive ISO string ("2026-09-10T02:11:50.362594", UTC
# -- it agrees with closed_at to within seconds of write lag), while
# `closed_at` is a real datetime.
#
# MongoDB compares by type bracket, so a datetime bound against a string field
# matches NOTHING, silently. The existing GET `opened_from` filter does exactly
# that and has never returned a row. Each bound is therefore coerced to the
# type its field actually holds.
DATE_PATHS: Dict[str, Tuple[str, str, str]] = {
    "openedFrom": ("opened_at", "$gte", "str"),
    "openedTo": ("opened_at", "$lte", "str"),
    "closedFrom": ("closed_at", "$gte", "date"),
    "closedTo": ("closed_at", "$lte", "date"),
}

SORT_PATHS: Dict[str, str] = {
    "openedAt": "opened_at",
    "closedAt": "closed_at",
    "symbol": "symbol",
    "status": "status",
    "direction": "direction",
    "profitUsd": "close_data.profit_usd",
    "volume": "entry.volume",
    "durationSeconds": "close_data.duration_seconds",
    "leverage": "leverage",
}

OUTCOMES = ("WIN", "LOSS", "BREAKEVEN", "UNSCORED")

STATUSES = ("OPEN", "CLOSED")
DIRECTIONS = ("BUY", "SELL")

MAX_SIZE = 200
MAX_LIST = 100

KNOWN_KEYS = frozenset(
    {"page", "size", "sortField", "sortDirection", "outcome", "leverage",
     "search", "includeDeleted", "includeHeavy", "withSummary", "fields"}
    | set(FIELD_PATHS) | set(RANGE_PATHS) | set(DATE_PATHS)
)


# ============================================================
# PUBLIC
# ============================================================

def build(body: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate a request body and return everything the service needs.

    Returns a dict with: query, sort, page, size, include_heavy, with_summary,
    fields, applied (the normalised filters, echoed back to the caller).

    Unknown keys are REJECTED rather than ignored. A typo like `levrage` that is
    silently dropped returns every trade and looks like a working filter --
    the same failure mode as the broken close_reason filter this replaces.
    """
    body = dict(body or {})

    unknown = sorted(set(body) - KNOWN_KEYS)
    if unknown:
        raise TradeQueryError(
            f"unknown field(s) {unknown}; allowed: {sorted(KNOWN_KEYS)}")

    clauses: List[Dict[str, Any]] = []
    applied: Dict[str, Any] = {}

    if not _bool(body.get("includeDeleted"), "includeDeleted"):
        clauses.append({"deleted_at": None})

    # ---- equality / membership ----------------------------------------
    for key, path in FIELD_PATHS.items():
        values = _list(body.get(key), key)
        if not values:
            continue
        if key == "status":
            values = _enum(values, STATUSES, key)
        elif key == "direction":
            values = _enum(values, DIRECTIONS, key)
        elif key == "ticket":
            values = [_int(v, key) for v in values]
        else:
            values = [str(v).strip() for v in values if str(v).strip()]
        if values:
            clauses.append({path: {"$in": values}})
            applied[key] = values

    # ---- leverage -------------------------------------------------------
    leverages = _list(body.get("leverage"), "leverage")
    if leverages:
        leverages = sorted({_int(v, "leverage") for v in leverages})
        clauses.append(_leverage_clause(leverages))
        applied["leverage"] = leverages

    # ---- outcome ---------------------------------------------------------
    outcomes = _list(body.get("outcome"), "outcome")
    if outcomes:
        outcomes = _enum(outcomes, OUTCOMES, "outcome")
        clauses.append(_outcome_clause(outcomes))
        applied["outcome"] = outcomes

    # ---- numeric ranges --------------------------------------------------
    for key, path in RANGE_PATHS.items():
        bounds = body.get(key)
        if bounds is None:
            continue
        if not isinstance(bounds, Mapping):
            raise TradeQueryError(f"{key} must be an object like {{\"min\": 0, \"max\": 10}}")
        extra = set(bounds) - {"min", "max"}
        if extra:
            raise TradeQueryError(f"{key} accepts only min/max, got {sorted(extra)}")

        clause: Dict[str, Any] = {}
        for edge, op in (("min", "$gte"), ("max", "$lte")):
            if bounds.get(edge) is not None:
                clause[op] = _float(bounds[edge], f"{key}.{edge}")
        if "$gte" in clause and "$lte" in clause and clause["$gte"] > clause["$lte"]:
            raise TradeQueryError(f"{key}.min is greater than {key}.max")
        if clause:
            clauses.append({path: clause})
            applied[key] = dict(bounds)

    # ---- dates -----------------------------------------------------------
    windows: Dict[str, Dict[str, Any]] = {}
    for key, (path, op, kind) in DATE_PATHS.items():
        if body.get(key):
            moment = _date(body[key], key)
            windows.setdefault(path, {})[op] = (
                stored_string(moment) if kind == "str" else moment)
            applied[key] = body[key]
    for path, window in windows.items():
        clauses.append({path: window})

    # ---- free-text search ------------------------------------------------
    search = body.get("search")
    if search is not None and str(search).strip():
        escaped = re.escape(str(search).strip())
        clauses.append({"$or": [
            # Anchored, so it can use the symbol index.
            {"symbol": {"$regex": f"^{escaped}", "$options": "i"}},
            {"close_data.close_reason": {"$regex": escaped, "$options": "i"}},
            {"comment": {"$regex": escaped, "$options": "i"}},
            {"trade_id": {"$regex": escaped, "$options": "i"}},
        ]})
        applied["search"] = str(search).strip()

    # Several of the clauses above are themselves $or documents (leverage,
    # outcome, search). Merging them into one flat dict would let the last
    # "$or" overwrite the others -- a leverage filter silently discarded by a
    # search box. $and keeps every one of them.
    if not clauses:
        query: Dict[str, Any] = {}
    elif len(clauses) == 1:
        query = clauses[0]
    else:
        query = {"$and": clauses}

    # ---- sort & paging ---------------------------------------------------
    sort_field = body.get("sortField") or "openedAt"
    if sort_field not in SORT_PATHS:
        raise TradeQueryError(
            f"cannot sort by {sort_field!r}; allowed: {sorted(SORT_PATHS)}")

    sort_dir = str(body.get("sortDirection") or "DESC").upper()
    if sort_dir not in ("ASC", "DESC"):
        raise TradeQueryError("sortDirection must be ASC or DESC")

    page = _int(body.get("page", 1), "page")
    size = _int(body.get("size", 25), "size")
    if page < 1:
        raise TradeQueryError("page must be at least 1")
    if not 1 <= size <= MAX_SIZE:
        # Refused, not clamped: someone asking for 5,000 rows has a wrong
        # expectation and should hear so, not quietly receive 200.
        raise TradeQueryError(f"size must be between 1 and {MAX_SIZE}")

    fields = body.get("fields")
    if fields is not None and not isinstance(fields, list):
        raise TradeQueryError("fields must be a list of field names")

    return {
        "query": query,
        "sort": (SORT_PATHS[sort_field], 1 if sort_dir == "ASC" else -1),
        "sort_echo": {"sortField": sort_field, "sortDirection": sort_dir},
        "page": page,
        "size": size,
        "include_heavy": _bool(body.get("includeHeavy"), "includeHeavy"),
        "with_summary": _bool(body.get("withSummary", True), "withSummary"),
        "fields": fields,
        "applied": applied,
    }


def leverage_of(doc: Mapping[str, Any]) -> Optional[int]:
    """A trade's leverage: the top-level field if present, else the nested one."""
    value = doc.get("leverage")
    if value is None:
        node: Any = doc
        for part in LEVERAGE_NESTED.split("."):
            node = node.get(part) if isinstance(node, Mapping) else None
            if node is None:
                break
        value = node
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def profit_of(doc: Mapping[str, Any]) -> Optional[float]:
    """Measured close profit, or None when the trade cannot be scored."""
    value = (doc.get("close_data") or {}).get("profit_usd")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ============================================================
# CLAUSES
# ============================================================

def _leverage_clause(leverages: List[int]) -> Dict[str, Any]:
    """Match leverage wherever the trade records it.

    Top-level `leverage` is written on new trades and backfilled onto old ones,
    but the monitor process only picks up the writer change when it restarts.
    Until it does, freshly opened trades carry leverage ONLY in the nested
    analysis block -- so matching the top-level field alone would drop exactly
    the newest trades from a leverage filter, with no error.
    """
    return {"$or": [
        {"leverage": {"$in": leverages}},
        {LEVERAGE_NESTED: {"$in": leverages}},
    ]}


def _outcome_clause(outcomes: List[str]) -> Dict[str, Any]:
    """Win/loss from the MEASURED profit, not the stored `is_winning` flag.

    `is_winning` is derived and was written by more than one code path; the
    profit is what the broker reported. Scoring from the flag would let a stale
    or miscomputed boolean decide which bucket a trade lands in.

    UNSCORED is closed-but-no-profit. It is a data problem, not a result, and
    making it selectable is how you find those rows rather than having them
    silently vanish from both the win and the loss counts.
    """
    options: List[Dict[str, Any]] = []
    for outcome in outcomes:
        if outcome == "WIN":
            options.append({"close_data.profit_usd": {"$gt": 0}})
        elif outcome == "LOSS":
            options.append({"close_data.profit_usd": {"$lt": 0}})
        elif outcome == "BREAKEVEN":
            options.append({"close_data.profit_usd": 0})
        elif outcome == "UNSCORED":
            options.append({"status": "CLOSED", "close_data.profit_usd": None})
    return options[0] if len(options) == 1 else {"$or": options}


# ============================================================
# COERCION
# ============================================================

def _list(value: Any, key: str) -> List[Any]:
    if value is None or value == "":
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    if len(items) > MAX_LIST:
        raise TradeQueryError(f"{key} accepts at most {MAX_LIST} values")
    for item in items:
        # A document here would be passed to Mongo as an operator -- the
        # injection route this whole module exists to close.
        if isinstance(item, (Mapping, list, tuple, set)):
            raise TradeQueryError(f"{key} values must be scalars")
    return items


def _enum(values: Iterable[Any], allowed: Tuple[str, ...], key: str) -> List[str]:
    normalised = [str(v).strip().upper() for v in values]
    bad = sorted({v for v in normalised if v not in allowed})
    if bad:
        raise TradeQueryError(f"{key} has invalid value(s) {bad}; allowed: {list(allowed)}")
    return list(dict.fromkeys(normalised))


def _int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise TradeQueryError(f"{key} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise TradeQueryError(f"{key} must be an integer, got {value!r}")
    if number != int(number):
        raise TradeQueryError(f"{key} must be an integer, got {value!r}")
    return int(number)


def _float(value: Any, key: str) -> float:
    if isinstance(value, bool):
        raise TradeQueryError(f"{key} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise TradeQueryError(f"{key} must be a number, got {value!r}")


def _bool(value: Any, key: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise TradeQueryError(f"{key} must be true or false")


def stored_string(moment: datetime) -> str:
    """A datetime in exactly the form `opened_at` is stored: naive UTC ISO with
    microseconds. Uniform width is what makes string comparison chronological;
    "2026-09-10T02:11" and "2026-09-10T02:11:50.362594" would not sort
    together correctly."""
    # A naive datetime is taken as UTC, NOT local. `astimezone()` on a naive
    # value assumes the machine's zone, which would silently shift every date
    # filter by the server's UTC offset.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _date(value: Any, key: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise TradeQueryError(f"{key} must be an ISO-8601 datetime, got {value!r}")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
