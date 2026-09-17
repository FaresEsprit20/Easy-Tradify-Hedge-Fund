# ============================================================
# TRADES SERVICE -- MONGODB
# ============================================================
# FILE: core/mongo/trades_service.py
#
# The only module that reads or writes the trades collection. Everything else
# calls these methods, exactly as the rest of the codebase calls
# FirebaseService rather than touching Firestore -- that boundary is why this
# migration is a one-file job instead of a rewrite, and it is worth keeping.
#
# WHAT THIS FIXES THAT THE FIRESTORE PATH COULD NOT
# -------------------------------------------------
#   * price_evolution is a plain array again, appended with $push: atomic,
#     server-side, O(1). On Firestore it was read-modify-write, so adding
#     point N rewrote all N, and the 1 MiB document limit stopped the append
#     silently after two points. 16 MB holds a full trade.
#   * Deletes have a STRATEGY instead of being one irreversible verb. A trade
#     is evidence of what the system did with money; the default is soft
#     delete, hard delete is gated, and an OPEN trade is refused outright.
#   * Pagination and sorting are bounded and whitelisted, so a caller cannot
#     ask for an unindexed sort or an unbounded page.
#
# LEAKAGE
# -------
# `analysis_at_open` is the decision snapshot and `analysis_at_close` carries
# outcome information. Nothing here merges them, and `list_trades` excludes
# both by default -- a caller that wants outcome data has to ask for it, so
# it cannot arrive by accident in a feature set.
# ============================================================

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .mongo_config import (
    DOCUMENT_SIZE_WARN_RATIO,
    MONGO_MAX_DOCUMENT_BYTES,
    MongoConfig,
    get_mongo_config,
)

logger = logging.getLogger(__name__)

TRADES_SERVICE_VERSION = "1.0"


# ============================================================
# ERRORS -- distinct types, because callers must react differently
# ============================================================

class TradeStorageError(RuntimeError):
    """The database could not satisfy the request (down, timeout, refused)."""


class TradeNotFound(LookupError):
    """No trade with that id. Distinct from 'the database is unavailable'."""


class TradeValidationError(ValueError):
    """The caller's input is wrong. Never retried, never a 5xx."""


class DeleteMode(str, Enum):
    """
    How a trade is removed.

    SOFT is the default everywhere. A trade document is the only record of
    what the system did with real money, and "we deleted it" is not an
    acceptable answer to a later question about a loss.
    """

    SOFT = "soft"        # reversible: sets deleted_at, hidden from queries
    ARCHIVE = "archive"  # moved to the archive collection, out of the hot path
    HARD = "hard"        # irreversible: gated behind an explicit confirmation


# ============================================================
# QUERY SAFETY
# ============================================================

# Sorting is restricted to fields that are INDEXED. An arbitrary sort field
# means a collection scan on every request, which is fine on 3 documents and
# takes the database down at 200,000. A whitelist also means a caller cannot
# smuggle an operator into the sort specification.
SORTABLE_FIELDS = frozenset({
    "opened_at", "closed_at", "created_at", "updated_at",
    "symbol", "status", "direction", "profit_usd", "trade_id",
})

FILTERABLE_FIELDS = frozenset({
    "symbol", "status", "direction", "close_reason", "result", "ticket",
})

# Where each GET filter / sort name actually lives in a stored trade.
#
# Before this map, `close_reason` and `result` were queried as TOP-LEVEL
# fields, and sorting by `profit_usd` sorted on a top-level field -- none of
# which exist on a single stored trade (0 of 120; the values are under
# `close_data`). The filters returned empty pages and the sort was a no-op,
# with no error either way, because an empty result is a valid answer.
FIELD_PATHS = {
    "close_reason": "close_data.close_reason",
    "profit_usd": "close_data.profit_usd",
}

# Numeric fields that accept a {min, max} range rather than an equality term.
# Kept separate from FILTERABLE_FIELDS because the two are validated
# differently: an equality filter takes a scalar, a range takes bounds, and
# accepting a range document on an equality field is how an operator gets
# injected into a query.
RANGE_FIELDS = {
    "profit_usd": "close_data.profit_usd",
    "profit_percent": "close_data.profit_percent",
    "volume": "entry.volume",
    "duration_seconds": "close_data.duration_seconds",
}

# Fields a free-text search looks at. Anchored prefix on symbol (indexed),
# substring elsewhere -- deliberately a short list, because an unbounded
# multi-field regex across a large collection is a denial of service.
SEARCHABLE_FIELDS = ("symbol", "close_reason", "comment", "trade_id")

# Heavy fields, excluded from list responses unless explicitly requested.
# analysis_at_open alone measured ~180KB; price_evolution runs to megabytes.
# A list endpoint that returned them would move gigabytes to render a table.
HEAVY_FIELDS = ("price_evolution", "analysis_at_open", "analysis_at_close")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


class TradesService:
    """CRUD for the trades collection, with the guarantees stated above."""

    def __init__(self, config: Optional[MongoConfig] = None, client: Any = None):
        self.config = config or get_mongo_config()
        self._client = client
        # RLock, NOT Lock. `_ensure_indexes()` holds this lock and then reads
        # `self.client`, whose property takes the same lock to build the client
        # on first use. With a plain threading.Lock that is a self-deadlock: the
        # thread blocks waiting for a lock it already owns, forever.
        #
        # It only fires when `collection` is the FIRST thing touched in a
        # process -- which is exactly what trade_sink.record_open() does -- so
        # it hid from every diagnostic that called is_healthy() or get_status()
        # first (those reach `client` WITHOUT holding the lock, so `_client` is
        # already set by the time `_ensure_indexes` runs and the inner
        # acquisition never happens). Live, it hung every single trade open:
        # the trade filled in MT5 and the record never reached Mongo.
        self._lock = threading.RLock()
        self._indexes_ready = False

    # --------------------------------------------------------
    # connection
    # --------------------------------------------------------

    @property
    def client(self):
        """
        The MongoClient, created on first use.

        Lazy because constructing this must not be able to stop a trading
        process from starting: a degraded database should be reported, not
        fatal at import time.
        """
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        from pymongo import MongoClient
                        self._client = MongoClient(
                            self.config.uri, **self.config.client_kwargs())
                        logger.info("Mongo client created for %s",
                                    self.config.safe_uri)
                    except Exception as exc:
                        # Log the REDACTED uri. The raw one carries the password.
                        logger.error("Mongo client creation failed for %s: %s",
                                     self.config.safe_uri, exc)
                        raise TradeStorageError(
                            f"could not create Mongo client: {exc}") from exc
        return self._client

    @property
    def collection(self):
        self._ensure_indexes()
        return self.client[self.config.database][self.config.collection]

    @property
    def archive(self):
        return self.client[self.config.database][self.config.archive_collection]

    def is_healthy(self) -> bool:
        """
        Whether the SERVER answered -- not whether a client object exists.

        pymongo builds a MongoClient without contacting anything, so holding
        one proves nothing. This is the only honest health signal.
        """
        try:
            self.client.admin.command("ping")
            return True
        except Exception as exc:
            logger.warning("Mongo ping failed: %s", exc)
            return False

    def _ensure_indexes(self) -> None:
        """
        Create indexes once per process.

        Every index here backs a query this service actually issues. Creating
        them lazily rather than in a migration script means a fresh
        environment is correct on first use instead of correct only if
        somebody remembered to run something.
        """
        if self._indexes_ready:
            return
        with self._lock:
            if self._indexes_ready:
                return
            try:
                from pymongo import ASCENDING, DESCENDING

                col = self.client[self.config.database][self.config.collection]
                # Unique: a trade is identified by its broker ticket, and two
                # documents for one ticket would mean two contradictory
                # records of the same money.
                col.create_index([("trade_id", ASCENDING)], unique=True,
                                 name="uniq_trade_id")
                col.create_index([("ticket", ASCENDING)], name="ix_ticket")
                col.create_index([("symbol", ASCENDING),
                                  ("opened_at", DESCENDING)], name="ix_symbol_opened")
                col.create_index([("status", ASCENDING),
                                  ("closed_at", DESCENDING)], name="ix_status_closed")
                col.create_index([("opened_at", DESCENDING)], name="ix_opened")
                # Leverage is a first-class dimension: trades come from three
                # accounts at 1:200/1:300/1:500, and the win-rate split by
                # leverage is one of the main questions asked of this data.
                col.create_index([("leverage", ASCENDING),
                                  ("closed_at", DESCENDING)], name="ix_leverage_closed")
                # Partial index: only soft-deleted documents are indexed, so
                # this stays small no matter how many live trades exist.
                col.create_index([("deleted_at", ASCENDING)], name="ix_deleted",
                                 partialFilterExpression={"deleted_at": {"$type": "date"}})
                self._indexes_ready = True
                logger.info("Mongo trade indexes ensured")
            except Exception as exc:
                # An index failure must not block reads and writes -- they are
                # merely slower without it.
                logger.warning("Could not ensure Mongo indexes: %s", exc)
                self._indexes_ready = True

    # --------------------------------------------------------
    # helpers
    # --------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _doc_id(trade_id: Any) -> str:
        """
        Canonical id.

        Accepts a bare ticket or an already-prefixed id, because both spellings
        exist in this codebase -- the Firestore path had a real bug where
        `trade_{id}` was applied twice and every existence check silently
        looked up `trade_trade_123`, which never exists.
        """
        text = str(trade_id).strip()
        if not text:
            raise TradeValidationError("trade_id is required")
        return text if text.startswith("trade_") else f"trade_{text}"

    @staticmethod
    def _strip_mongo_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Drop `_id`; it is an ObjectId and is not JSON-serialisable."""
        if doc is None:
            return None
        doc.pop("_id", None)
        return doc

    def _document_size(self, doc: Mapping[str, Any]) -> int:
        try:
            import bson
            return len(bson.BSON.encode(dict(doc)))
        except Exception:
            import json
            return len(json.dumps(doc, default=str).encode("utf-8"))

    def _guard_document_size(self, trade_id: str, doc: Mapping[str, Any]) -> None:
        """
        Refuse a write that would exceed the document ceiling, and warn well
        before it.

        Checked BEFORE writing on purpose. On Firestore the equivalent limit
        was discovered only when appends started failing, by which point the
        forward walk for that trade was already truncated and nothing said so.
        """
        size = self._document_size(doc)
        if size >= MONGO_MAX_DOCUMENT_BYTES:
            raise TradeStorageError(
                f"trade {trade_id} is {size} bytes, over MongoDB's "
                f"{MONGO_MAX_DOCUMENT_BYTES}-byte document limit -- refusing "
                f"the write rather than truncating the record")
        if size >= MONGO_MAX_DOCUMENT_BYTES * DOCUMENT_SIZE_WARN_RATIO:
            logger.warning(
                "trade %s is %d bytes (%.0f%% of the document limit) -- "
                "price_evolution will stop accepting points soon",
                trade_id, size, 100.0 * size / MONGO_MAX_DOCUMENT_BYTES)

    # --------------------------------------------------------
    # CREATE
    # --------------------------------------------------------

    def create_trade(self, trade: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Insert a new trade. Fails if the ticket already exists.

        Use `upsert_trade` for the open path, where a retry after a timeout
        must not create a second record for one position.
        """
        if not isinstance(trade, Mapping):
            raise TradeValidationError("trade must be a mapping")
        ticket = trade.get("ticket") or trade.get("trade_id")
        if not ticket:
            raise TradeValidationError("trade requires a ticket or trade_id")

        doc = dict(trade)
        doc["trade_id"] = self._doc_id(ticket)
        doc.setdefault("status", "OPEN")
        doc.setdefault("price_evolution", [])
        doc["created_at"] = doc.get("created_at") or self._now()
        doc["updated_at"] = self._now()
        doc["deleted_at"] = None
        self._guard_document_size(doc["trade_id"], doc)

        try:
            from pymongo.errors import DuplicateKeyError
            try:
                self.collection.insert_one(doc)
            except DuplicateKeyError as exc:
                raise TradeValidationError(
                    f"trade {doc['trade_id']} already exists") from exc
        except (TradeValidationError, TradeStorageError):
            raise
        except Exception as exc:
            raise TradeStorageError(f"insert failed: {exc}") from exc

        return self._strip_mongo_id(doc)

    def upsert_trade(self, trade: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Create or update by trade_id -- idempotent.

        This is what the open path uses: a network timeout followed by a retry
        must converge on ONE record, not two contradictory ones.
        """
        if not isinstance(trade, Mapping):
            raise TradeValidationError("trade must be a mapping")
        ticket = trade.get("ticket") or trade.get("trade_id")
        if not ticket:
            raise TradeValidationError("trade requires a ticket or trade_id")

        doc_id = self._doc_id(ticket)
        # `price_evolution` is EXCLUDED from $set on purpose. It is seeded by
        # $setOnInsert below so an update can never blank an existing forward
        # walk -- and MongoDB rejects the same path appearing in both operators
        # ("would create a conflict at 'price_evolution'"). Leaving it in $set
        # made every upsert fail, which meant record_open() mirrored NOTHING
        # while the fail-soft sink swallowed the error and kept trading.
        doc = {k: v for k, v in trade.items()
               if k not in ("_id", "trade_id", "price_evolution")}
        doc["updated_at"] = self._now()

        try:
            self.collection.update_one(
                {"trade_id": doc_id},
                {
                    "$set": doc,
                    "$setOnInsert": {
                        "trade_id": doc_id,
                        "created_at": self._now(),
                        "deleted_at": None,
                        # Only seeded on insert: an update must never blank an
                        # existing forward walk.
                        "price_evolution": list(trade.get("price_evolution") or []),
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            raise TradeStorageError(f"upsert failed: {exc}") from exc

        return self.get_trade(doc_id)

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------

    def get_trade(self, trade_id: Any, include_deleted: bool = False,
                  fields: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """One trade. Raises TradeNotFound rather than returning None."""
        doc_id = self._doc_id(trade_id)
        query: Dict[str, Any] = {"trade_id": doc_id}
        if not include_deleted:
            query["deleted_at"] = None

        projection = {f: 1 for f in fields} if fields else None
        try:
            doc = self.collection.find_one(query, projection)
        except Exception as exc:
            raise TradeStorageError(f"read failed: {exc}") from exc

        if doc is None:
            raise TradeNotFound(f"no trade {doc_id}")
        return self._strip_mongo_id(doc)

    def list_trades(self, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                    sort_by: str = "opened_at", sort_dir: str = "desc",
                    filters: Optional[Mapping[str, Any]] = None,
                    opened_from: Optional[str] = None,
                    opened_to: Optional[str] = None,
                    include_deleted: bool = False,
                    include_heavy: bool = False,
                    search: Optional[str] = None,
                    ranges: Optional[Mapping[str, Mapping[str, Any]]] = None,
                    fields: Optional[Iterable[str]] = None,
                    cursor: Optional[str] = None) -> Dict[str, Any]:
        """
        A page of trades, with the total, sorted and filtered.

        Heavy fields are excluded unless `include_heavy` -- a list of 25 trades
        with price_evolution attached is tens of megabytes, and no table needs
        it. That is the difference between a usable endpoint and one that
        times out at 200 trades.

        `cursor` switches to keyset pagination. Offset paging re-scans every
        skipped document, so page 400 costs 400 pages of work; a cursor is
        constant-time at any depth. Offset paging is kept because a UI needs
        page numbers and a total, and it is correct up to a few thousand rows
        -- the cursor is for exports and for walking the whole collection.
        """
        page = max(1, int(page or 1))
        page_size = int(page_size or DEFAULT_PAGE_SIZE)
        if page_size < 1:
            raise TradeValidationError("page_size must be at least 1")
        if page_size > MAX_PAGE_SIZE:
            # Capped, not silently clamped: a caller asking for 10,000 rows has
            # a wrong expectation and should be told, not quietly given 200.
            raise TradeValidationError(
                f"page_size {page_size} exceeds the maximum of {MAX_PAGE_SIZE}")

        if sort_by not in SORTABLE_FIELDS:
            raise TradeValidationError(
                f"cannot sort by {sort_by!r}; allowed: {sorted(SORTABLE_FIELDS)}")
        if sort_dir not in ("asc", "desc"):
            raise TradeValidationError("sort_dir must be 'asc' or 'desc'")

        query = self._build_query(filters, opened_from, opened_to,
                                  include_deleted, search, ranges)
        projection = self._projection(fields, include_heavy)

        # Keyset pagination: continue after the last id of the previous page.
        if cursor:
            query = dict(query)
            query["trade_id"] = ({"$lt": cursor} if sort_dir == "desc"
                                 else {"$gt": cursor})

        try:
            from pymongo import ASCENDING, DESCENDING
            direction = ASCENDING if sort_dir == "asc" else DESCENDING
            finder = (self.collection
                      .find(query, projection)
                      # trade_id breaks ties, so the order is TOTAL. Without
                      # it two documents with equal sort keys can appear on
                      # two consecutive pages, or on neither.
                      .sort([(FIELD_PATHS.get(sort_by, sort_by), direction),
                             ("trade_id", direction)]))
            if not cursor:
                finder = finder.skip((page - 1) * page_size)
            items = [self._strip_mongo_id(d) for d in finder.limit(page_size)]
            total = self.collection.count_documents(query)
        except Exception as exc:
            raise TradeStorageError(f"list failed: {exc}") from exc

        pages = (total + page_size - 1) // page_size if page_size else 0
        next_cursor = items[-1].get("trade_id") if items else None
        return {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": pages,
                "has_next": (len(items) == page_size) if cursor else page < pages,
                "has_previous": page > 1,
                "next_cursor": next_cursor,
                "mode": "cursor" if cursor else "offset",
            },
            "sort": {"by": sort_by, "dir": sort_dir},
            "heavy_fields_included": bool(include_heavy),
        }

    @staticmethod
    def _projection(fields: Optional[Iterable[str]],
                    include_heavy: bool) -> Optional[Dict[str, int]]:
        """
        What to fetch.

        An explicit field list wins -- a caller that names five columns should
        not be sent megabytes of analysis. Otherwise the heavy fields are
        excluded unless asked for. MongoDB forbids mixing inclusion and
        exclusion in one projection, so these are two separate shapes rather
        than one merged dict.
        """
        if fields:
            wanted = {f.strip() for f in fields if f and f.strip()}
            if not wanted:
                return None
            wanted.add("trade_id")  # identity is never optional
            return {f: 1 for f in wanted}
        return None if include_heavy else {f: 0 for f in HEAVY_FIELDS}

    def _build_query(self, filters: Optional[Mapping[str, Any]] = None,
                     opened_from: Optional[str] = None,
                     opened_to: Optional[str] = None,
                     include_deleted: bool = False,
                     search: Optional[str] = None,
                     ranges: Optional[Mapping[str, Mapping[str, Any]]] = None,
                     ) -> Dict[str, Any]:
        """
        Translate request parameters into a query.

        Only whitelisted fields are honoured, and every value is used as data
        -- an equality term, a bounded range, or an escaped regex. A caller
        cannot inject an operator document, so no request can become
        `{"$where": ...}` or an unindexed scan of the whole collection.
        """
        query: Dict[str, Any] = {}
        if not include_deleted:
            query["deleted_at"] = None

        for key, value in (filters or {}).items():
            if key not in FILTERABLE_FIELDS:
                raise TradeValidationError(
                    f"cannot filter by {key!r}; allowed: {sorted(FILTERABLE_FIELDS)}")
            if value is None or value == "":
                continue
            if key == "result":
                # There is no stored `result` field. WIN/LOSS is scored from the
                # measured close profit, the same rule POST /query uses.
                outcome = str(value).strip().upper()
                if outcome == "WIN":
                    query["close_data.profit_usd"] = {"$gt": 0}
                elif outcome == "LOSS":
                    query["close_data.profit_usd"] = {"$lt": 0}
                elif outcome == "BREAKEVEN":
                    query["close_data.profit_usd"] = 0
                else:
                    raise TradeValidationError(
                        f"result must be WIN, LOSS or BREAKEVEN, got {value!r}")
                continue

            path = FIELD_PATHS.get(key, key)
            if isinstance(value, (list, tuple, set)):
                query[path] = {"$in": [str(v) for v in value]}
            elif isinstance(value, str) and "," in value:
                # "EURUSD,XAUUSD" -> multi-value, the shape a UI filter sends.
                query[path] = {"$in": [v.strip() for v in value.split(",") if v.strip()]}
            else:
                query[path] = value

        for key, bounds in (ranges or {}).items():
            if key not in RANGE_FIELDS:
                raise TradeValidationError(
                    f"cannot range-filter by {key!r}; allowed: "
                    f"{sorted(RANGE_FIELDS)}")
            clause: Dict[str, Any] = {}
            for edge, op in (("min", "$gte"), ("max", "$lte")):
                if bounds.get(edge) is not None and bounds.get(edge) != "":
                    try:
                        clause[op] = float(bounds[edge])
                    except (TypeError, ValueError):
                        raise TradeValidationError(
                            f"{key}.{edge} must be a number, got {bounds[edge]!r}")
            if clause:
                query[RANGE_FIELDS[key]] = clause

        # `opened_at` is stored as a naive UTC ISO STRING on every trade, not a
        # BSON date. MongoDB compares by type bracket, so the datetime this used
        # to bind matched nothing -- opened_from/opened_to have never returned a
        # row. The bound is rendered in the stored format instead, which sorts
        # chronologically because every value has the same width.
        from .trade_query import stored_string
        window: Dict[str, Any] = {}
        if opened_from:
            window["$gte"] = stored_string(self._parse_time(opened_from, "opened_from"))
        if opened_to:
            window["$lte"] = stored_string(self._parse_time(opened_to, "opened_to"))
        if window:
            query["opened_at"] = window

        if search:
            text = str(search).strip()
            if text:
                # Escaped, so a user string is never compiled as a pattern; the
                # symbol clause is anchored so it can use the symbol index.
                import re as _re
                escaped = _re.escape(text)
                clauses = [{"symbol": {"$regex": f"^{escaped}", "$options": "i"}}]
                clauses += [{field: {"$regex": escaped, "$options": "i"}}
                            for field in SEARCHABLE_FIELDS if field != "symbol"]
                query["$or"] = clauses
        return query

    @staticmethod
    def _parse_time(value: Any, label: str) -> datetime:
        if isinstance(value, datetime):
            return value
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception as exc:
            raise TradeValidationError(
                f"{label} is not an ISO-8601 timestamp: {value!r}") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    # ================================================================
    # JSON-BODY QUERY
    # ================================================================

    def query_trades(self, body: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """A filtered, sorted page of trades, described by a JSON body.

        Translation and validation live in `core.mongo.trade_query`; this method
        only executes. See that module for the body shape and for why each field
        maps where it does.

        With `withSummary` (the default) the response also carries win/loss
        figures for the WHOLE filtered set -- not just the page -- broken down
        by leverage. A win rate computed over the 25 rows on screen would change
        every time the user paged, and would say nothing about the filter.
        """
        from . import trade_query

        try:
            spec = trade_query.build(body)
        except trade_query.TradeQueryError as exc:
            raise TradeValidationError(str(exc)) from exc

        sort_path, sort_dir = spec["sort"]
        projection = self._projection(spec["fields"], spec["include_heavy"])

        try:
            finder = (self.collection
                      .find(spec["query"], projection)
                      # trade_id breaks ties so the order is total; without it,
                      # rows with equal sort keys can repeat across pages.
                      .sort([(sort_path, sort_dir), ("trade_id", sort_dir)])
                      .skip((spec["page"] - 1) * spec["size"])
                      .limit(spec["size"]))
            items = [self._strip_mongo_id(d) for d in finder]
            total = self.collection.count_documents(spec["query"])
        except Exception as exc:
            raise TradeStorageError(f"query failed: {exc}") from exc

        # The page never includes the heavy analysis block, which is exactly
        # where older trades keep their leverage. Lift it onto each row so a
        # table can show the column without requesting megabytes per row.
        for item in items:
            if item.get("leverage") is None:
                lev = trade_query.leverage_of(item)
                if lev is not None:
                    item["leverage"] = lev

        if items and any(item.get("leverage") is None for item in items) \
                and not spec["include_heavy"]:
            self._attach_leverage(items)

        pages = (total + spec["size"] - 1) // spec["size"]

        result: Dict[str, Any] = {
            "items": items,
            "pagination": {
                "page": spec["page"],
                "size": spec["size"],
                "total": total,
                "pages": pages,
                "hasNext": spec["page"] < pages,
                "hasPrevious": spec["page"] > 1,
            },
            "sort": spec["sort_echo"],
            "appliedFilters": spec["applied"],
        }

        if spec["with_summary"]:
            result["summary"] = self._summarise(spec["query"])

        return result

    def _attach_leverage(self, items: List[Dict[str, Any]]) -> None:
        """Fetch ONLY the nested leverage for rows that lack the top-level copy."""
        from . import trade_query

        missing = [i["trade_id"] for i in items
                   if i.get("leverage") is None and i.get("trade_id")]
        if not missing:
            return
        try:
            found = {
                d["trade_id"]: trade_query.leverage_of(d)
                for d in self.collection.find(
                    {"trade_id": {"$in": missing}},
                    {"trade_id": 1, trade_query.LEVERAGE_NESTED: 1})
            }
        except Exception as exc:  # decoration, never worth failing the page
            logger.warning(f"leverage lookup failed: {exc}")
            return
        for item in items:
            if item.get("leverage") is None and item.get("trade_id") in found:
                item["leverage"] = found[item["trade_id"]]

    def _summarise(self, query: Mapping[str, Any]) -> Dict[str, Any]:
        """Win/loss figures over the full filtered set, overall and per leverage.

        Computed in the database with $facet rather than by pulling documents,
        so it costs the same at 120 trades as at 120,000.

        TWO THINGS THIS IS CAREFUL ABOUT
        --------------------------------
        * An unscored trade (closed, no profit) is excluded from win AND loss.
          In BSON ordering null sorts below every number, so a naive
          `$lt: ["$profit", 0]` counts every null as a loss -- quietly
          inflating the loss count with rows that have no result at all.
        * Win rate divides by SCORED trades, not by all trades. Open positions
          have no outcome yet, and counting them in the denominator makes a
          strategy look worse the more positions it currently holds.
        """
        from . import trade_query

        profit = "$close_data.profit_usd"
        scored = {"$and": [{"$ne": [{"$ifNull": [profit, None]}, None]}]}
        won = {"$and": [scored, {"$gt": [profit, 0]}]}
        lost = {"$and": [scored, {"$lt": [profit, 0]}]}

        def group(key: Any) -> Dict[str, Any]:
            return {"$group": {
                "_id": key,
                "trades": {"$sum": 1},
                "open": {"$sum": {"$cond": [{"$eq": ["$status", "OPEN"]}, 1, 0]}},
                "closed": {"$sum": {"$cond": [{"$eq": ["$status", "CLOSED"]}, 1, 0]}},
                "scored": {"$sum": {"$cond": [scored, 1, 0]}},
                "wins": {"$sum": {"$cond": [won, 1, 0]}},
                "losses": {"$sum": {"$cond": [lost, 1, 0]}},
                "netProfit": {"$sum": {"$cond": [scored, profit, 0]}},
                "grossProfit": {"$sum": {"$cond": [won, profit, 0]}},
                "grossLoss": {"$sum": {"$cond": [lost, profit, 0]}},
            }}

        leverage_expr = {"$ifNull": ["$leverage", "$" + trade_query.LEVERAGE_NESTED]}

        pipeline = [
            {"$match": dict(query)},
            {"$facet": {
                "overall": [group(None)],
                "byLeverage": [group(leverage_expr), {"$sort": {"_id": 1}}],
            }},
        ]

        try:
            facets = next(iter(self.collection.aggregate(pipeline)), {})
        except Exception as exc:
            logger.warning(f"summary aggregation failed: {exc}")
            return {"available": False, "error": str(exc)}

        overall = (facets.get("overall") or [{}])[0]
        return {
            "available": True,
            "overall": self._shape_bucket(overall),
            "byLeverage": [
                {"leverage": b.get("_id"), **self._shape_bucket(b)}
                for b in facets.get("byLeverage") or []
            ],
        }

    # Below this many scored trades a win rate is noise, not a finding. It is
    # reported as a flag on each bucket rather than hidden, so a 0% win rate on
    # three trades is visibly a small sample and not a verdict on leverage.
    SMALL_SAMPLE = 30

    @classmethod
    def _shape_bucket(cls, raw: Mapping[str, Any]) -> Dict[str, Any]:
        scored = int(raw.get("scored") or 0)
        wins = int(raw.get("wins") or 0)
        losses = int(raw.get("losses") or 0)
        gross_profit = float(raw.get("grossProfit") or 0.0)
        gross_loss = float(raw.get("grossLoss") or 0.0)
        net = float(raw.get("netProfit") or 0.0)

        return {
            "trades": int(raw.get("trades") or 0),
            "open": int(raw.get("open") or 0),
            "closed": int(raw.get("closed") or 0),
            "scored": scored,
            "unscored": int(raw.get("closed") or 0) - scored,
            "wins": wins,
            "losses": losses,
            "breakeven": scored - wins - losses,
            "winRate": round(wins / scored * 100, 2) if scored else None,
            "netProfit": round(net, 2),
            "avgProfit": round(net / scored, 2) if scored else None,
            "avgWin": round(gross_profit / wins, 2) if wins else None,
            "avgLoss": round(gross_loss / losses, 2) if losses else None,
            # None, not infinity, when there are no losses -- a profit factor of
            # "inf" on two trades is the kind of number that gets quoted.
            "profitFactor": (round(gross_profit / abs(gross_loss), 2)
                             if gross_loss else None),
            "smallSample": scored < cls.SMALL_SAMPLE,
        }

    def filter_catalog(self) -> Dict[str, Any]:
        """Every filter the query endpoint accepts, with the values that exist.

        Built from the live collection so a UI never offers a leverage, symbol
        or close reason that would return nothing. Counts are over non-deleted
        trades.
        """
        from . import trade_query

        leverage_expr = {"$ifNull": ["$leverage", "$" + trade_query.LEVERAGE_NESTED]}
        profit = "$close_data.profit_usd"

        def counts(expr: Any) -> List[Dict[str, Any]]:
            return [{"$group": {"_id": expr, "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}}]

        pipeline = [
            {"$match": {"deleted_at": None}},
            {"$facet": {
                "status": counts("$status"),
                "direction": counts("$direction"),
                "symbol": counts("$symbol"),
                "closeReason": counts("$close_data.close_reason"),
                "leverage": counts(leverage_expr),
                "outcome": counts({"$switch": {
                    "branches": [
                        {"case": {"$ne": ["$status", "CLOSED"]}, "then": "OPEN"},
                        {"case": {"$eq": [{"$ifNull": [profit, None]}, None]},
                         "then": "UNSCORED"},
                        {"case": {"$gt": [profit, 0]}, "then": "WIN"},
                        {"case": {"$lt": [profit, 0]}, "then": "LOSS"},
                    ],
                    "default": "BREAKEVEN",
                }}),
                "ranges": [{"$group": {
                    "_id": None,
                    "profitUsdMin": {"$min": profit},
                    "profitUsdMax": {"$max": profit},
                    "volumeMin": {"$min": "$entry.volume"},
                    "volumeMax": {"$max": "$entry.volume"},
                    "durationSecondsMin": {"$min": "$close_data.duration_seconds"},
                    "durationSecondsMax": {"$max": "$close_data.duration_seconds"},
                    "openedFrom": {"$min": "$opened_at"},
                    "openedTo": {"$max": "$opened_at"},
                    "closedFrom": {"$min": "$closed_at"},
                    "closedTo": {"$max": "$closed_at"},
                }}],
            }},
        ]

        try:
            facets = next(iter(self.collection.aggregate(pipeline)), {})
        except Exception as exc:
            raise TradeStorageError(f"filter catalog failed: {exc}") from exc

        def values(name: str) -> List[Dict[str, Any]]:
            return [{"value": b["_id"], "count": b["count"]}
                    for b in facets.get(name) or [] if b.get("_id") is not None]

        ranges = (facets.get("ranges") or [{}])[0]
        ranges.pop("_id", None)
        for key, value in list(ranges.items()):
            if isinstance(value, datetime):
                ranges[key] = value.isoformat()

        return {
            "filters": {
                "status": {"type": "enum", "values": values("status")},
                "outcome": {
                    "type": "enum",
                    # OPEN is shown for completeness of the counts but is not a
                    # selectable outcome -- filter on status for that.
                    "values": [v for v in values("outcome") if v["value"] != "OPEN"],
                    "note": "Scored from close_data.profit_usd. UNSCORED = closed with no profit recorded.",
                },
                "leverage": {"type": "enum", "values": values("leverage")},
                "symbol": {"type": "enum", "values": values("symbol")},
                "direction": {"type": "enum", "values": values("direction")},
                "closeReason": {"type": "enum", "values": values("closeReason")},
                "profitUsd": {"type": "range",
                              "min": ranges.get("profitUsdMin"), "max": ranges.get("profitUsdMax")},
                "volume": {"type": "range",
                           "min": ranges.get("volumeMin"), "max": ranges.get("volumeMax")},
                "durationSeconds": {"type": "range",
                                    "min": ranges.get("durationSecondsMin"),
                                    "max": ranges.get("durationSecondsMax")},
                "profitPercent": {"type": "range"},
                "exitSlippage": {"type": "range"},
                "exitSpread": {"type": "range"},
                "openedFrom": {"type": "datetime", "earliest": ranges.get("openedFrom")},
                "openedTo": {"type": "datetime", "latest": ranges.get("openedTo")},
                "closedFrom": {"type": "datetime", "earliest": ranges.get("closedFrom")},
                "closedTo": {"type": "datetime", "latest": ranges.get("closedTo")},
                "ticket": {"type": "list"},
                "tradeId": {"type": "list"},
                "search": {"type": "text",
                           "note": "Symbol prefix, close reason, comment or trade id."},
            },
            "sortFields": sorted(trade_query.SORT_PATHS),
            "sortDirections": ["ASC", "DESC"],
            "maxPageSize": trade_query.MAX_SIZE,
        }

    def get_price_evolution(self, trade_id: Any, *, offset: int = 0,
                            limit: int = 500) -> Dict[str, Any]:
        """
        A slice of one trade's forward walk.

        Paged separately from the trade because it is the large part: ~180
        points at ~20KB is several megabytes, which no caller wants attached
        to a summary. `$slice` does the paging server-side, so the rest of the
        array never leaves the database.
        """
        doc_id = self._doc_id(trade_id)
        offset = max(0, int(offset or 0))
        limit = max(1, min(int(limit or 500), 2000))
        try:
            doc = self.collection.find_one(
                {"trade_id": doc_id, "deleted_at": None},
                {"price_evolution": {"$slice": [offset, limit]}, "trade_id": 1})
            if doc is None:
                raise TradeNotFound(f"no trade {doc_id}")
            total = self.collection.aggregate([
                {"$match": {"trade_id": doc_id}},
                {"$project": {"n": {"$size": {"$ifNull": ["$price_evolution", []]}}}},
            ])
            count = next(iter(total), {}).get("n", 0)
        except TradeNotFound:
            raise
        except Exception as exc:
            raise TradeStorageError(f"price_evolution read failed: {exc}") from exc

        return {
            "trade_id": doc_id,
            "points": doc.get("price_evolution") or [],
            "pagination": {"offset": offset, "limit": limit, "total": count,
                           "has_next": offset + limit < count},
        }

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    # Fields a generic update may never touch. Identity and the audit trail
    # are set by this service, not by callers.
    IMMUTABLE_FIELDS = frozenset({"_id", "trade_id", "created_at", "deleted_at",
                                  "deleted_by", "deleted_reason"})

    def update_trade(self, trade_id: Any, patch: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Merge fields into a trade.

        Rejects identity and audit fields rather than ignoring them: silently
        dropping part of a caller's update is how two components end up
        disagreeing about what was written.
        """
        doc_id = self._doc_id(trade_id)
        if not isinstance(patch, Mapping) or not patch:
            raise TradeValidationError("patch must be a non-empty mapping")

        illegal = set(patch) & self.IMMUTABLE_FIELDS
        if illegal:
            raise TradeValidationError(
                f"these fields cannot be updated directly: {sorted(illegal)}")

        update = dict(patch)
        update["updated_at"] = self._now()
        try:
            result = self.collection.update_one(
                {"trade_id": doc_id, "deleted_at": None}, {"$set": update})
        except Exception as exc:
            raise TradeStorageError(f"update failed: {exc}") from exc

        if result.matched_count == 0:
            raise TradeNotFound(f"no trade {doc_id}")
        return self.get_trade(doc_id)

    def update_trailing_stop(self, trade_id: Any, trailing: Mapping[str, Any]) -> None:
        """Record a trailing-stop move: the current state, and the move in history.

        Trailing-stop updates were only ever written to Firestore -- the helper
        had no Mongo write at all -- so no trade in this collection records how
        its stop moved. That is the difference between knowing a STOP_LOSS close
        was a trailed stop locking in profit and reading it as a plain loss.

        `trailing_stop` holds the latest state (what the Firestore field held);
        `trailing_stop_history` accumulates every move with `$push`, atomically.
        """
        doc_id = self._doc_id(trade_id)
        if not isinstance(trailing, Mapping) or not trailing:
            raise TradeValidationError("trailing stop data must be a non-empty mapping")

        now = self._now()
        entry = dict(trailing)
        entry.setdefault("recorded_at", now)
        try:
            result = self.collection.update_one(
                {"trade_id": doc_id, "deleted_at": None},
                {"$set": {"trailing_stop": dict(trailing), "updated_at": now},
                 "$push": {"trailing_stop_history": entry}},
            )
        except Exception as exc:
            raise TradeStorageError(f"trailing stop update failed: {exc}") from exc
        if result.matched_count == 0:
            raise TradeNotFound(f"no trade {doc_id}")

    def append_price_point(self, trade_id: Any, point: Mapping[str, Any]) -> int:
        """
        One point onto the forward walk. Returns the new length.

        `$push` is atomic and server-side. The Firestore equivalent read the
        whole array, appended locally and wrote it back, which was quadratic
        and stopped working entirely at the 1 MiB document limit.
        """
        doc_id = self._doc_id(trade_id)
        if not isinstance(point, Mapping) or not point:
            raise TradeValidationError("price point must be a non-empty mapping")

        try:
            result = self.collection.update_one(
                {"trade_id": doc_id, "deleted_at": None},
                {"$push": {"price_evolution": dict(point)},
                 "$set": {"updated_at": self._now()},
                 "$inc": {"price_evolution_count": 1}},
            )
        except Exception as exc:
            # A document that has outgrown the limit reports it here. Say so
            # explicitly -- the Firestore version failed silently and the
            # forward walk simply stopped growing.
            raise TradeStorageError(
                f"appending a price point to {doc_id} failed: {exc}") from exc

        if result.matched_count == 0:
            raise TradeNotFound(f"no trade {doc_id}")

        doc = self.collection.find_one({"trade_id": doc_id},
                                       {"price_evolution_count": 1})
        return int((doc or {}).get("price_evolution_count") or 0)

    def close_trade(self, trade_id: Any, close_data: Mapping[str, Any],
                    analysis_at_close: Optional[Mapping[str, Any]] = None
                    ) -> Dict[str, Any]:
        """Mark a trade closed and attach its close record."""
        doc_id = self._doc_id(trade_id)
        update: Dict[str, Any] = {
            "status": "CLOSED",
            "close_data": dict(close_data or {}),
            "closed_at": (close_data or {}).get("closed_at") or self._now(),
            "updated_at": self._now(),
        }
        if analysis_at_close is not None:
            update["analysis_at_close"] = dict(analysis_at_close)

        try:
            result = self.collection.update_one(
                {"trade_id": doc_id, "deleted_at": None}, {"$set": update})
        except Exception as exc:
            raise TradeStorageError(f"close failed: {exc}") from exc
        if result.matched_count == 0:
            raise TradeNotFound(f"no trade {doc_id}")
        return self.get_trade(doc_id)

    # --------------------------------------------------------
    # DELETE -- strategies, not one irreversible verb
    # --------------------------------------------------------

    def delete_trade(self, trade_id: Any, *, mode: DeleteMode = DeleteMode.SOFT,
                     reason: Optional[str] = None, actor: str = "api",
                     confirm: bool = False,
                     allow_open: bool = False) -> Dict[str, Any]:
        """
        Remove a trade under an explicit strategy.

        SOFT (default) sets `deleted_at` and hides the trade from queries. It
        is reversible with `restore_trade`.

        ARCHIVE copies the document to the archive collection and removes it
        from the hot one -- for trades that are finished and no longer worth
        paging past, without discarding them.

        HARD destroys it and requires `confirm=True`. A trade is the only
        record of what the system did with money; the confirmation exists so
        that an irreversible action cannot be reached by a default argument.

        An OPEN trade is refused in every mode unless `allow_open`. Deleting
        the record of a position that is still live at the broker leaves money
        at risk with nothing describing it.
        """
        doc_id = self._doc_id(trade_id)
        mode = DeleteMode(mode)

        existing = self.collection.find_one({"trade_id": doc_id},
                                            {"status": 1, "deleted_at": 1})
        if existing is None:
            raise TradeNotFound(f"no trade {doc_id}")

        if existing.get("status") == "OPEN" and not allow_open:
            raise TradeValidationError(
                f"trade {doc_id} is still OPEN -- refusing to delete the record "
                f"of a live position. Close it first, or pass allow_open.")

        if mode is DeleteMode.SOFT:
            if existing.get("deleted_at"):
                return {"trade_id": doc_id, "mode": mode.value,
                        "already_deleted": True}
            self.collection.update_one(
                {"trade_id": doc_id},
                {"$set": {"deleted_at": self._now(),
                          "deleted_by": actor,
                          "deleted_reason": reason,
                          "updated_at": self._now()}})
            return {"trade_id": doc_id, "mode": mode.value, "reversible": True}

        if mode is DeleteMode.ARCHIVE:
            doc = self.collection.find_one({"trade_id": doc_id})
            if doc is None:
                raise TradeNotFound(f"no trade {doc_id}")
            doc["archived_at"] = self._now()
            doc["archived_by"] = actor
            doc["archive_reason"] = reason
            # Write to the archive BEFORE removing from the hot collection --
            # the reverse order loses the trade if the second step fails.
            self.archive.replace_one({"trade_id": doc_id}, doc, upsert=True)
            self.collection.delete_one({"trade_id": doc_id})
            return {"trade_id": doc_id, "mode": mode.value, "reversible": True,
                    "archive_collection": self.config.archive_collection}

        # HARD
        if not confirm:
            raise TradeValidationError(
                f"hard delete of {doc_id} requires confirm=True -- this "
                f"destroys the only record of a real trade and cannot be undone")
        result = self.collection.delete_one({"trade_id": doc_id})
        return {"trade_id": doc_id, "mode": mode.value, "reversible": False,
                "deleted": result.deleted_count}

    def restore_trade(self, trade_id: Any) -> Dict[str, Any]:
        """Undo a soft delete."""
        doc_id = self._doc_id(trade_id)
        result = self.collection.update_one(
            {"trade_id": doc_id},
            {"$set": {"deleted_at": None, "updated_at": self._now()},
             "$unset": {"deleted_by": "", "deleted_reason": ""}})
        if result.matched_count == 0:
            raise TradeNotFound(f"no trade {doc_id}")
        return self.get_trade(doc_id)

    def purge_deleted(self, *, older_than_days: int = 30,
                      confirm: bool = False, limit: int = 1000) -> Dict[str, Any]:
        """
        Permanently remove trades soft-deleted more than N days ago.

        Requires `confirm=True` and reports a dry-run count otherwise, so the
        blast radius is visible before anything is destroyed. `limit` bounds a
        single call: an unbounded purge is a long-running write that blocks
        the collection.
        """
        if older_than_days < 1:
            raise TradeValidationError("older_than_days must be at least 1")
        cutoff = self._now() - timedelta(days=int(older_than_days))
        query = {"deleted_at": {"$ne": None, "$lt": cutoff}}

        try:
            candidates = self.collection.count_documents(query)
            if not confirm:
                return {"dry_run": True, "would_delete": candidates,
                        "older_than_days": older_than_days,
                        "cutoff": cutoff.isoformat(),
                        "hint": "pass confirm=true to actually delete"}
            ids = [d["trade_id"] for d in
                   self.collection.find(query, {"trade_id": 1}).limit(int(limit))]
            deleted = self.collection.delete_many(
                {"trade_id": {"$in": ids}}).deleted_count if ids else 0
        except Exception as exc:
            raise TradeStorageError(f"purge failed: {exc}") from exc

        return {"dry_run": False, "deleted": deleted, "candidates": candidates,
                "older_than_days": older_than_days, "cutoff": cutoff.isoformat()}

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    def stats(self, *, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggregate counts and performance, computed IN the database.

        This is the operation Firestore could not express at all: it needed a
        composite index per query shape and returned [] when one was missing,
        which read identically to "no trades".
        """
        match: Dict[str, Any] = {"deleted_at": None}
        if symbol:
            match["symbol"] = symbol
        try:
            pipeline = [
                {"$match": match},
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "profit_usd": {"$sum": {"$ifNull": ["$close_data.profit_usd", 0]}},
                    "wins": {"$sum": {"$cond": [
                        {"$gt": [{"$ifNull": ["$close_data.profit_usd", 0]}, 0]}, 1, 0]}},
                }},
            ]
            rows = list(self.collection.aggregate(pipeline))
        except Exception as exc:
            raise TradeStorageError(f"stats failed: {exc}") from exc

        by_status = {r["_id"] or "UNKNOWN": {
            "count": r["count"], "profit_usd": round(r["profit_usd"], 2),
            "wins": r["wins"]} for r in rows}
        closed = by_status.get("CLOSED", {})
        total_closed = closed.get("count", 0)
        return {
            "by_status": by_status,
            "total": sum(v["count"] for v in by_status.values()),
            "closed": total_closed,
            "wins": closed.get("wins", 0),
            "win_rate_percent": (round(100.0 * closed.get("wins", 0) / total_closed, 2)
                                 if total_closed else None),
            "net_profit_usd": round(sum(v["profit_usd"] for v in by_status.values()), 2),
            "symbol": symbol,
        }

    def count_trades(self, **kwargs) -> int:
        """How many trades match, without fetching any of them."""
        try:
            return self.collection.count_documents(self._build_query(**kwargs))
        except Exception as exc:
            raise TradeStorageError(f"count failed: {exc}") from exc

    def trade_exists(self, trade_id: Any) -> bool:
        """Existence without transferring the document."""
        try:
            return self.collection.count_documents(
                {"trade_id": self._doc_id(trade_id)}, limit=1) > 0
        except Exception as exc:
            raise TradeStorageError(f"exists check failed: {exc}") from exc

    def distinct_values(self, field: str,
                        include_deleted: bool = False) -> List[Any]:
        """
        The distinct values of one field -- what a UI needs to populate a
        filter dropdown without downloading every trade to derive it.

        Restricted to filterable fields: `distinct` on an unindexed field
        scans the collection.
        """
        if field not in FILTERABLE_FIELDS:
            raise TradeValidationError(
                f"cannot list distinct {field!r}; allowed: "
                f"{sorted(FILTERABLE_FIELDS)}")
        query = {} if include_deleted else {"deleted_at": None}
        try:
            return sorted(v for v in self.collection.distinct(field, query)
                          if v is not None)
        except Exception as exc:
            raise TradeStorageError(f"distinct failed: {exc}") from exc

    # --------------------------------------------------------
    # BULK
    # --------------------------------------------------------

    def bulk_upsert(self, trades: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        """
        Upsert many trades in one round trip.

        Uses an UNORDERED bulk write, so one bad document does not abort the
        rest -- the failures are reported individually instead. Ordered writes
        stop at the first error, which on an import means an unknown fraction
        of the batch silently did not land.
        """
        rows = [t for t in (trades or []) if isinstance(t, Mapping)]
        if not rows:
            raise TradeValidationError("no trades supplied")
        if len(rows) > 1000:
            raise TradeValidationError(
                f"batch of {len(rows)} exceeds the 1000-document limit")

        try:
            from pymongo import UpdateOne
            operations = []
            for trade in rows:
                ticket = trade.get("ticket") or trade.get("trade_id")
                if not ticket:
                    raise TradeValidationError(
                        "every trade needs a ticket or trade_id")
                doc_id = self._doc_id(ticket)
                payload = {k: v for k, v in trade.items()
                           if k not in ("_id", "trade_id")}
                payload["updated_at"] = self._now()
                operations.append(UpdateOne(
                    {"trade_id": doc_id},
                    {"$set": payload,
                     "$setOnInsert": {"trade_id": doc_id,
                                      "created_at": self._now(),
                                      "deleted_at": None}},
                    upsert=True))
            result = self.collection.bulk_write(operations, ordered=False)
        except TradeValidationError:
            raise
        except Exception as exc:
            raise TradeStorageError(f"bulk upsert failed: {exc}") from exc

        return {"requested": len(rows),
                "inserted": result.upserted_count,
                "modified": result.modified_count,
                "matched": result.matched_count}

    def bulk_delete(self, trade_ids: Iterable[Any], *,
                    mode: DeleteMode = DeleteMode.SOFT,
                    reason: Optional[str] = None, actor: str = "api",
                    confirm: bool = False) -> Dict[str, Any]:
        """
        Delete many trades under one strategy.

        Each id goes through `delete_trade`, so every protection applies to
        every document -- OPEN trades are still refused, hard delete still
        needs confirmation. A bulk path that skipped those checks would be a
        way to reach exactly the destructive operations they exist to guard.
        """
        ids = [t for t in (trade_ids or [])]
        if not ids:
            raise TradeValidationError("no trade_ids supplied")

        results, failures = [], []
        for trade_id in ids:
            try:
                results.append(self.delete_trade(
                    trade_id, mode=mode, reason=reason, actor=actor,
                    confirm=confirm))
            except (TradeNotFound, TradeValidationError) as exc:
                failures.append({"trade_id": str(trade_id),
                                 "error": type(exc).__name__,
                                 "message": str(exc)})
        return {"requested": len(ids), "deleted": len(results),
                "failed": len(failures), "results": results,
                "failures": failures}

    # --------------------------------------------------------
    # STREAMING -- for the AI layer, which reads the whole collection
    # --------------------------------------------------------

    def iter_trades(self, *, batch_size: int = 50, include_heavy: bool = True,
                    **query_kwargs) -> Iterable[Dict[str, Any]]:
        """
        Stream every matching trade, oldest first.

        A generator rather than a list because the AI layer trains on the
        WHOLE collection, and a trade with its forward walk is megabytes --
        materialising 200 of them at once is gigabytes of resident memory for
        no reason.

        Sorted by trade_id and paged with a keyset cursor rather than skip, so
        the cost per batch is constant no matter how deep the walk goes.
        """
        query = self._build_query(**query_kwargs)
        projection = None if include_heavy else {f: 0 for f in HEAVY_FIELDS}
        batch_size = max(1, min(int(batch_size or 50), 200))
        last_id = None

        try:
            from pymongo import ASCENDING
            while True:
                page_query = dict(query)
                if last_id is not None:
                    page_query["trade_id"] = {"$gt": last_id}
                batch = list(self.collection.find(page_query, projection)
                             .sort([("trade_id", ASCENDING)])
                             .limit(batch_size))
                if not batch:
                    return
                for doc in batch:
                    last_id = doc.get("trade_id")
                    yield self._strip_mongo_id(doc)
                if len(batch) < batch_size:
                    return
        except Exception as exc:
            raise TradeStorageError(f"stream failed: {exc}") from exc

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    def performance_stats(self, **query_kwargs) -> Dict[str, Any]:
        """
        Win rate, expectancy, payoff and profit factor over the matching set.

        Expectancy is reported in BOTH dollars and R where a stop distance is
        recorded. R is the one that means anything across symbols -- $10 on
        gold and $10 on EURUSD are not comparable risks, and averaging them
        produces a number that describes neither.
        """
        query = self._build_query(**query_kwargs)
        query["status"] = "CLOSED"
        try:
            rows = list(self.collection.find(query, {
                "close_data.profit_usd": 1, "entry.price": 1,
                "entry.stop_loss": 1, "close_data.close_price": 1,
                "direction": 1, "symbol": 1, "_id": 0}))
        except Exception as exc:
            raise TradeStorageError(f"performance stats failed: {exc}") from exc

        if not rows:
            return {"trades": 0, "note": "no closed trades match"}

        profits, r_multiples = [], []
        for row in rows:
            profit = ((row.get("close_data") or {}).get("profit_usd"))
            if isinstance(profit, (int, float)):
                profits.append(float(profit))
            entry = row.get("entry") or {}
            close = (row.get("close_data") or {}).get("close_price")
            ep, sl = entry.get("price"), entry.get("stop_loss")
            if all(isinstance(v, (int, float)) for v in (ep, sl, close)) and ep != sl:
                sign = 1 if row.get("direction") == "BUY" else -1
                r_multiples.append(sign * (close - ep) / abs(ep - sl))

        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        gross_win, gross_loss = sum(wins), abs(sum(losses))

        def mean(values):
            return round(sum(values) / len(values), 4) if values else None

        return {
            "trades": len(rows),
            "with_profit": len(profits),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_percent": (round(100.0 * len(wins) / len(profits), 2)
                                 if profits else None),
            "net_profit_usd": round(sum(profits), 2) if profits else None,
            "expectancy_usd": mean(profits),
            "average_win_usd": mean(wins),
            "average_loss_usd": mean(losses),
            # Payoff is the lever when win rate is near random -- measured on
            # this account's own history, direction entropy is ~1.0.
            "payoff_ratio": (round(mean(wins) / abs(mean(losses)), 3)
                             if wins and losses and mean(losses) else None),
            "profit_factor": (round(gross_win / gross_loss, 3)
                              if gross_loss else None),
            "best_usd": round(max(profits), 2) if profits else None,
            "worst_usd": round(min(profits), 2) if profits else None,
            "r_multiple": {
                "measurable_trades": len(r_multiples),
                "expectancy_r": mean(r_multiples),
                "total_r": round(sum(r_multiples), 4) if r_multiples else None,
            },
        }

    def stats_by_symbol(self, limit: int = 50, **query_kwargs) -> List[Dict[str, Any]]:
        """Per-symbol breakdown, computed in the database."""
        query = self._build_query(**query_kwargs)
        query["status"] = "CLOSED"
        try:
            pipeline = [
                {"$match": query},
                {"$group": {
                    "_id": "$symbol",
                    "trades": {"$sum": 1},
                    "net_profit_usd": {"$sum": {"$ifNull": ["$close_data.profit_usd", 0]}},
                    "wins": {"$sum": {"$cond": [
                        {"$gt": [{"$ifNull": ["$close_data.profit_usd", 0]}, 0]}, 1, 0]}},
                }},
                {"$sort": {"net_profit_usd": -1}},
                {"$limit": max(1, min(int(limit or 50), 200))},
            ]
            rows = list(self.collection.aggregate(pipeline))
        except Exception as exc:
            raise TradeStorageError(f"by-symbol stats failed: {exc}") from exc

        return [{
            "symbol": r["_id"],
            "trades": r["trades"],
            "wins": r["wins"],
            "win_rate_percent": (round(100.0 * r["wins"] / r["trades"], 2)
                                 if r["trades"] else None),
            "net_profit_usd": round(r["net_profit_usd"], 2),
        } for r in rows]

    def stats_timeseries(self, granularity: str = "day",
                         **query_kwargs) -> List[Dict[str, Any]]:
        """Trades and profit bucketed by day, week or month."""
        units = {"day": "%Y-%m-%d", "week": "%Y-W%V", "month": "%Y-%m"}
        if granularity not in units:
            raise TradeValidationError(
                f"granularity must be one of {sorted(units)}")
        query = self._build_query(**query_kwargs)
        query["status"] = "CLOSED"
        try:
            pipeline = [
                {"$match": query},
                {"$group": {
                    "_id": {"$dateToString": {"format": units[granularity],
                                              "date": "$closed_at"}},
                    "trades": {"$sum": 1},
                    "net_profit_usd": {"$sum": {"$ifNull": ["$close_data.profit_usd", 0]}},
                    "wins": {"$sum": {"$cond": [
                        {"$gt": [{"$ifNull": ["$close_data.profit_usd", 0]}, 0]}, 1, 0]}},
                }},
                {"$sort": {"_id": 1}},
            ]
            rows = list(self.collection.aggregate(pipeline))
        except Exception as exc:
            raise TradeStorageError(f"timeseries failed: {exc}") from exc

        return [{"period": r["_id"], "trades": r["trades"], "wins": r["wins"],
                 "net_profit_usd": round(r["net_profit_usd"], 2)} for r in rows]

    def get_status(self) -> Dict[str, Any]:
        """Health and configuration, safe to publish -- no credentials."""
        healthy = self.is_healthy()
        status = {
            "service": "trades",
            "version": TRADES_SERVICE_VERSION,
            "healthy": healthy,
            "config": self.config.to_dict(),
        }
        if healthy:
            try:
                status["documents"] = self.collection.count_documents({})
                status["soft_deleted"] = self.collection.count_documents(
                    {"deleted_at": {"$ne": None}})
                status["archived"] = self.archive.count_documents({})
            except Exception as exc:
                status["counts_error"] = str(exc)
        return status


_SERVICE: Optional[TradesService] = None
_SERVICE_LOCK = threading.Lock()


def get_trades_service(config: Optional[MongoConfig] = None) -> TradesService:
    """
    The process-wide service.

    Shared so the connection pool is shared: a new MongoClient per caller
    would open a new pool each time and exhaust the server's connections.
    """
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = TradesService(config)
        return _SERVICE
