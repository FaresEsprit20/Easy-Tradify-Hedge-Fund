"""
The trades service and its HTTP surface.

Runs against an in-memory stand-in for the collection, so the suite needs no
mongod. What is tested is the SERVICE's own guarantees -- the parts that would
silently do the wrong thing rather than fail loudly:

  * a page_size of 10,000 is refused, not quietly clamped
  * sorting and filtering accept only whitelisted, indexed fields
  * heavy fields are excluded from list responses by default
  * deleting an OPEN trade is refused
  * hard delete and purge require explicit confirmation
  * the URI never appears unredacted in anything publishable

The delete guarantees carry the most weight. A trade document is the only
record of what the system did with real money, and every one of these
protections exists because the alternative is an irreversible action reachable
from a default argument.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from core.mongo.mongo_config import MongoConfig, _redact
from core.mongo.trades_service import (
    DeleteMode,
    MAX_PAGE_SIZE,
    TradeNotFound,
    TradeValidationError,
    TradesService,
)


# --------------------------------------------------------------------------
# an in-memory collection, just enough for the service
# --------------------------------------------------------------------------

class FakeCollection:
    def __init__(self):
        self.docs = []

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _matches(doc, query):
        for key, cond in query.items():
            value = doc
            for part in key.split("."):
                value = (value or {}).get(part) if isinstance(value, dict) else None
            if isinstance(cond, dict):
                for op, operand in cond.items():
                    if op == "$ne" and value == operand:
                        return False
                    if op == "$lt" and not (value is not None and value < operand):
                        return False
                    if op == "$gte" and not (value is not None and value >= operand):
                        return False
                    if op == "$lte" and not (value is not None and value <= operand):
                        return False
                    if op == "$in" and value not in operand:
                        return False
                    if op == "$regex":
                        flags = re.I if "i" in cond.get("$options", "") else 0
                        if not (isinstance(value, str)
                                and re.search(operand, value, flags)):
                            return False
                    if op == "$type" and value is None:
                        return False
            elif value != cond:
                return False
        return True

    def _find(self, query):
        return [d for d in self.docs if self._matches(d, query)]

    # -- pymongo surface -------------------------------------------------
    def create_index(self, *a, **k):
        return "ok"

    def insert_one(self, doc):
        if any(d.get("trade_id") == doc.get("trade_id") for d in self.docs):
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("duplicate trade_id")
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("trade_id")})()

    def find_one(self, query, projection=None):
        found = self._find(query)
        if not found:
            return None
        doc = dict(found[0])
        if projection:
            slice_spec = None
            for key, spec in projection.items():
                if isinstance(spec, dict) and "$slice" in spec:
                    slice_spec = (key, spec["$slice"])
            if slice_spec:
                key, (offset, limit) = slice_spec
                doc = {key: (doc.get(key) or [])[offset:offset + limit],
                       "trade_id": doc.get("trade_id")}
            elif all(v == 0 for v in projection.values()):
                for key in projection:
                    doc.pop(key, None)
            else:
                doc = {k: v for k, v in doc.items() if k in projection}
        return doc

    def find(self, query, projection=None):
        docs = [dict(d) for d in self._find(query)]
        if projection and all(v == 0 for v in projection.values()):
            for d in docs:
                for key in projection:
                    d.pop(key, None)
        return FakeCursor(docs)

    def count_documents(self, query):
        return len(self._find(query))

    def update_one(self, query, update, upsert=False):
        found = self._find(query)
        if not found:
            if upsert:
                doc = dict(update.get("$setOnInsert") or {})
                doc.update(update.get("$set") or {})
                self.docs.append(doc)
                return type("R", (), {"matched_count": 0, "upserted_id": 1})()
            return type("R", (), {"matched_count": 0, "upserted_id": None})()
        doc = found[0]
        doc.update(update.get("$set") or {})
        for key in (update.get("$unset") or {}):
            doc.pop(key, None)
        for key, amount in (update.get("$inc") or {}).items():
            doc[key] = (doc.get(key) or 0) + amount
        for key, value in (update.get("$push") or {}).items():
            doc.setdefault(key, []).append(value)
        return type("R", (), {"matched_count": 1, "upserted_id": None})()

    def replace_one(self, query, doc, upsert=False):
        found = self._find(query)
        if found:
            self.docs[self.docs.index(found[0])] = dict(doc)
        elif upsert:
            self.docs.append(dict(doc))
        return type("R", (), {"matched_count": len(found)})()

    def delete_one(self, query):
        found = self._find(query)
        if found:
            self.docs.remove(found[0])
        return type("R", (), {"deleted_count": len(found[:1])})()

    def delete_many(self, query):
        found = self._find(query)
        for doc in found:
            self.docs.remove(doc)
        return type("R", (), {"deleted_count": len(found)})()

    @staticmethod
    def _path(doc, dotted):
        value = doc
        for part in str(dotted).lstrip("$").split("."):
            value = (value or {}).get(part) if isinstance(value, dict) else None
        return value

    def aggregate(self, pipeline):
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._matches(d, stage["$match"])]
            if "$project" in stage:
                docs = [{"n": len(d.get("price_evolution") or [])} for d in docs]
            if "$group" in stage:
                spec = stage["$group"]
                buckets = {}
                for doc in docs:
                    key = self._path(doc, spec["_id"])
                    row = buckets.setdefault(key, {"_id": key})
                    for field, op in spec.items():
                        if field == "_id":
                            continue
                        if "$sum" in op:
                            operand = op["$sum"]
                            if operand == 1:
                                amount = 1
                            elif isinstance(operand, dict) and "$ifNull" in operand:
                                amount = self._path(doc, operand["$ifNull"][0])                                     or operand["$ifNull"][1]
                            elif isinstance(operand, dict) and "$cond" in operand:
                                cond, yes, no = operand["$cond"]
                                left = cond["$gt"][0]
                                left = (self._path(doc, left["$ifNull"][0])
                                        or left["$ifNull"][1]) if isinstance(left, dict) else left
                                amount = yes if left > cond["$gt"][1] else no
                            else:
                                amount = self._path(doc, operand) or 0
                            row[field] = row.get(field, 0) + amount
                docs = list(buckets.values())
        return iter(docs)


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, spec):
        for field, direction in reversed(spec):
            self.docs.sort(key=lambda d: (d.get(field) is None, d.get(field)),
                           reverse=direction == -1)
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeService(TradesService):
    """TradesService wired to in-memory collections."""

    def __init__(self):
        super().__init__(config=MongoConfig(uri="mongodb://localhost:27017"))
        self._col = FakeCollection()
        self._arch = FakeCollection()
        self._indexes_ready = True

    @property
    def collection(self):
        return self._col

    @property
    def archive(self):
        return self._arch

    def is_healthy(self):
        return True


@pytest.fixture
def service():
    svc = FakeService()
    for i in range(5):
        svc.create_trade({
            "ticket": 1000 + i,
            "symbol": "EURUSD" if i % 2 == 0 else "XAUUSD",
            "direction": "BUY",
            "status": "CLOSED",
            "opened_at": datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=i),
            "close_data": {"profit_usd": 10.0 if i % 2 == 0 else -5.0},
            "analysis_at_open": {"final_verdict": {"probability_percent": 60 + i}},
            "price_evolution": [{"price": 1.1 + i / 1000}],
        })
    return svc


# --------------------------------------------------------------------------
# config / secrets
# --------------------------------------------------------------------------

def test_credentials_never_appear_in_anything_publishable():
    """A connection string in a log file is a leaked password."""
    cfg = MongoConfig(uri="mongodb://alice:s3cr3t@cluster.example.net/db")
    assert "s3cr3t" not in cfg.safe_uri
    assert "alice" not in cfg.safe_uri
    published = str(cfg.to_dict())
    assert "s3cr3t" not in published
    assert _redact("mongodb://u:p@h/d") == "mongodb://***:***@h/d"
    # A URI without credentials must survive intact rather than be mangled.
    assert _redact("mongodb://localhost:27017") == "mongodb://localhost:27017"


# --------------------------------------------------------------------------
# create / read
# --------------------------------------------------------------------------

def test_a_ticket_cannot_produce_two_records(service):
    """Two documents for one ticket means two contradictory records."""
    with pytest.raises(TradeValidationError):
        service.create_trade({"ticket": 1000, "symbol": "EURUSD"})


def test_upsert_is_idempotent(service):
    """A retry after a timeout must converge on ONE record."""
    before = service.collection.count_documents({})
    service.upsert_trade({"ticket": 1000, "symbol": "EURUSD", "status": "CLOSED"})
    service.upsert_trade({"ticket": 1000, "symbol": "EURUSD", "status": "CLOSED"})
    assert service.collection.count_documents({}) == before


def test_upsert_never_blanks_an_existing_forward_walk(service):
    """price_evolution is $setOnInsert -- an update must not wipe it."""
    service.append_price_point(1000, {"price": 1.2345})
    service.upsert_trade({"ticket": 1000, "symbol": "EURUSD"})
    assert len(service.get_trade(1000)["price_evolution"]) == 2


def test_both_id_spellings_resolve_to_one_trade(service):
    """The Firestore path had a real double-prefix bug here."""
    assert service.get_trade(1000)["trade_id"] == "trade_1000"
    assert service.get_trade("trade_1000")["trade_id"] == "trade_1000"


def test_a_missing_trade_is_not_found_not_none(service):
    with pytest.raises(TradeNotFound):
        service.get_trade(999999)


# --------------------------------------------------------------------------
# pagination / sorting / filtering
# --------------------------------------------------------------------------

def test_list_paginates_and_reports_totals(service):
    page = service.list_trades(page=1, page_size=2)
    assert len(page["items"]) == 2
    assert page["pagination"]["total"] == 5
    assert page["pagination"]["pages"] == 3
    assert page["pagination"]["has_next"] is True
    assert page["pagination"]["has_previous"] is False


def test_an_oversized_page_is_refused_not_silently_clamped(service):
    """
    A caller asking for 10,000 rows has a wrong expectation. Quietly giving
    them 200 leaves them believing they received everything.
    """
    with pytest.raises(TradeValidationError):
        service.list_trades(page_size=MAX_PAGE_SIZE + 1)


def test_sorting_is_restricted_to_indexed_fields(service):
    """An arbitrary sort field is a collection scan on every request."""
    with pytest.raises(TradeValidationError):
        service.list_trades(sort_by="close_data.profit_usd")
    with pytest.raises(TradeValidationError):
        service.list_trades(sort_by="opened_at", sort_dir="sideways")
    assert service.list_trades(sort_by="opened_at", sort_dir="asc")["items"]


def test_filtering_is_restricted_to_whitelisted_fields(service):
    """A caller must not be able to inject an operator document."""
    with pytest.raises(TradeValidationError):
        service.list_trades(filters={"$where": "true"})
    filtered = service.list_trades(filters={"symbol": "EURUSD"})
    assert {t["symbol"] for t in filtered["items"]} == {"EURUSD"}


def test_heavy_fields_are_excluded_from_lists_by_default(service):
    """
    25 trades with price_evolution attached is tens of megabytes. This is the
    difference between a usable endpoint and one that times out.
    """
    light = service.list_trades()["items"][0]
    assert "price_evolution" not in light
    assert "analysis_at_open" not in light

    heavy = service.list_trades(include_heavy=True)["items"][0]
    assert "price_evolution" in heavy


def test_a_bad_date_window_is_rejected_clearly(service):
    with pytest.raises(TradeValidationError):
        service.list_trades(opened_from="last tuesday")


# --------------------------------------------------------------------------
# update / append
# --------------------------------------------------------------------------

def test_identity_fields_cannot_be_updated(service):
    """Silently dropping part of an update makes components disagree."""
    for field in ("trade_id", "created_at", "deleted_at"):
        with pytest.raises(TradeValidationError):
            service.update_trade(1000, {field: "tampered"})


def test_appending_a_point_is_atomic_and_counted(service):
    assert service.append_price_point(1000, {"price": 1.5}) == 1
    assert service.append_price_point(1000, {"price": 1.6}) == 2
    assert len(service.get_trade(1000)["price_evolution"]) == 3


def test_price_evolution_pages_server_side(service):
    for i in range(10):
        service.append_price_point(1000, {"price": i})
    page = service.get_price_evolution(1000, offset=2, limit=3)
    assert len(page["points"]) == 3
    assert page["pagination"]["total"] == 11
    assert page["pagination"]["has_next"] is True


# --------------------------------------------------------------------------
# delete strategies -- the ones that matter most
# --------------------------------------------------------------------------

def test_an_open_trade_cannot_be_deleted(service):
    """
    Deleting the record of a position still live at the broker leaves money at
    risk with nothing describing it.
    """
    service.create_trade({"ticket": 7777, "symbol": "EURUSD", "status": "OPEN"})
    for mode in DeleteMode:
        with pytest.raises(TradeValidationError):
            service.delete_trade(7777, mode=mode, confirm=True)
    # ...but it is possible deliberately.
    assert service.delete_trade(7777, mode=DeleteMode.SOFT, allow_open=True)


def test_soft_delete_hides_but_keeps_and_restores(service):
    service.delete_trade(1000, reason="duplicate")
    with pytest.raises(TradeNotFound):
        service.get_trade(1000)
    assert service.get_trade(1000, include_deleted=True)["deleted_reason"] == "duplicate"
    assert service.list_trades()["pagination"]["total"] == 4

    service.restore_trade(1000)
    assert service.get_trade(1000)["deleted_at"] is None
    assert service.list_trades()["pagination"]["total"] == 5


def test_hard_delete_requires_explicit_confirmation(service):
    """An irreversible action must not be reachable from a default argument."""
    with pytest.raises(TradeValidationError):
        service.delete_trade(1000, mode=DeleteMode.HARD)
    assert service.collection.count_documents({}) == 5

    result = service.delete_trade(1000, mode=DeleteMode.HARD, confirm=True)
    assert result["reversible"] is False
    assert service.collection.count_documents({}) == 4


def test_archive_writes_before_it_removes(service):
    """The reverse order loses the trade if the second step fails."""
    service.delete_trade(1000, mode=DeleteMode.ARCHIVE, reason="old")
    assert service.collection.count_documents({"trade_id": "trade_1000"}) == 0
    assert service.archive.count_documents({"trade_id": "trade_1000"}) == 1


def test_purge_is_a_dry_run_until_confirmed(service):
    """The blast radius must be visible before anything is destroyed."""
    service.delete_trade(1000)
    # Backdate the deletion past the cutoff.
    stored = next(d for d in service.collection.docs
                  if d["trade_id"] == "trade_1000")
    stored["deleted_at"] = datetime.now(timezone.utc) - timedelta(days=90)

    dry = service.purge_deleted(older_than_days=30)
    assert dry["dry_run"] is True and dry["would_delete"] == 1
    assert service.collection.count_documents({}) == 5, "dry run deleted something"

    done = service.purge_deleted(older_than_days=30, confirm=True)
    assert done["deleted"] == 1
    assert service.collection.count_documents({}) == 4


def test_purge_never_touches_live_trades(service):
    service.purge_deleted(older_than_days=1, confirm=True)
    assert service.collection.count_documents({}) == 5


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------

def test_stats_are_computed_and_not_guessed(service):
    stats = service.stats()
    assert stats["total"] == 5
    assert stats["closed"] == 5
    assert stats["wins"] == 3
    assert stats["win_rate_percent"] == 60.0


def test_status_is_publishable(service):
    status = service.get_status()
    assert status["healthy"] is True
    assert "***" not in status["config"]["uri"]  # no creds in this URI at all
    assert status["config"]["max_document_bytes"] == 16 * 1024 * 1024
