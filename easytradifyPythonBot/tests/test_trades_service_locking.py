# ============================================================
# TRADES SERVICE -- LOCK REENTRANCY REGRESSION
# ============================================================
# Every trade open hung, forever, and the trade was never recorded. The stack
# (via faulthandler on a live hang) was:
#
#   trade_sink.record_open
#     -> trades_service.upsert_trade
#       -> trades_service.collection
#         -> trades_service._ensure_indexes   <- acquires self._lock
#           -> trades_service.client          <- acquires self._lock AGAIN
#
# `self._lock` was a threading.Lock, which is NOT reentrant, so the thread
# blocked waiting for a lock it already held. Nothing timed out and nothing
# raised: the position filled in MT5 and the process sat there.
#
# WHY IT HID
# ----------
# The inner acquisition only happens when `self._client is None`. Any call
# that reaches `client` WITHOUT holding the lock -- is_healthy(), get_status(),
# a raw pymongo connection in a diagnostic script -- sets `_client` first, and
# then `_ensure_indexes` never re-enters. So every health check passed and
# reported `mongo_healthy: True` while live writes deadlocked. The trigger is
# specifically: `collection` touched FIRST in a fresh process, which is exactly
# what record_open does.
#
# These tests therefore construct the service the way the live path does --
# no client injected, `collection` touched first -- and run it under a
# deadline, because the failure mode is a hang, not an exception.
# ============================================================

import threading

import pytest


class _FakeCollection:
    def __init__(self):
        self.indexes = []

    def create_index(self, keys, **kwargs):
        self.indexes.append(kwargs.get("name"))
        return kwargs.get("name")


class _FakeDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


class _FakeClient:
    """Stands in for MongoClient: no server, no network, no timeouts."""

    def __init__(self, *args, **kwargs):
        self._dbs = {}

    def __getitem__(self, name):
        return self._dbs.setdefault(name, _FakeDB())


def _fresh_service(monkeypatch):
    """A TradesService exactly as the live path builds it: no client injected."""
    import pymongo

    monkeypatch.setattr(pymongo, "MongoClient", _FakeClient)

    from core.mongo.trades_service import TradesService
    return TradesService()          # _client is None -- this is the trigger


def test_lock_is_reentrant():
    """
    The direct invariant. `_ensure_indexes` reads `self.client` while holding
    this lock, so a non-reentrant Lock deadlocks the calling thread against
    itself. Stated separately from the behavioural test below because it says
    plainly what the constraint is.
    """
    from core.mongo.trades_service import TradesService

    service = TradesService(client=object())
    assert isinstance(service._lock, type(threading.RLock())), (
        "_lock must be an RLock: _ensure_indexes() holds it and then reads "
        "self.client, whose property acquires the same lock")

    # And it must actually survive being taken twice by one thread.
    with service._lock:
        with service._lock:
            pass


def test_collection_touched_first_does_not_deadlock(monkeypatch):
    """
    The live sequence: fresh process, `collection` before any health call.

    Run on a worker with a deadline -- on the old code this never returns, so
    an ordinary call would hang the whole suite rather than fail it.
    """
    service = _fresh_service(monkeypatch)

    result = {}

    def touch():
        try:
            result["collection"] = service.collection
        except Exception as exc:            # a raise is a failure, but not a hang
            result["error"] = exc

    worker = threading.Thread(target=touch, daemon=True, name="collection-first")
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), (
        "DEADLOCK: `collection` never returned. _ensure_indexes() is holding "
        "_lock while `client` tries to acquire it -- this is the bug that hung "
        "every trade open and lost the record.")
    assert "error" not in result, f"collection raised: {result.get('error')}"
    assert result.get("collection") is not None


def test_indexes_are_created_once_on_first_touch(monkeypatch):
    """
    The deadlock made the index step unreachable, so confirm it actually runs
    -- and only once, since it is guarded by `_indexes_ready`.
    """
    service = _fresh_service(monkeypatch)

    collection = service.collection
    created_first = list(collection.indexes)

    assert "uniq_trade_id" in created_first, (
        "the unique ticket index must exist: two documents for one ticket "
        "would be two contradictory records of the same money")

    service.collection                      # second touch
    assert collection.indexes == created_first, (
        "indexes were recreated -- _indexes_ready is not short-circuiting")


def test_concurrent_first_touch_from_several_threads(monkeypatch):
    """
    record_open runs on a Flask request thread while the position monitor and
    health threads are live, so first touch can genuinely race. The lock has to
    make that safe without reintroducing the self-deadlock.
    """
    service = _fresh_service(monkeypatch)

    errors = []
    barrier = threading.Barrier(4)

    def touch():
        try:
            barrier.wait(timeout=5)
            service.collection
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=touch, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "deadlock under concurrent first touch"
    assert not errors, f"errors under concurrency: {errors}"
