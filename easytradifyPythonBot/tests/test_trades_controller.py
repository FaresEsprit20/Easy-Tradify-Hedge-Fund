"""
The trades HTTP contract.

The service's guarantees are tested in test_trades_service.py. What matters
here is the contract a client sees, and specifically the parts that are easy
to get wrong in a way no one notices until a client breaks:

  * every response, success or failure, has the same envelope
  * exception TYPE maps to the right status -- 400 the caller's fault, 404 not
    an error, 503 ours and retryable. Collapsing them into 500 makes retry
    logic impossible to write.
  * a JSON API answers JSON even for 404/405 and malformed bodies; Flask's
    defaults return HTML, which breaks client error handling at exactly the
    moment it is needed
  * hard delete and purge cannot be reached without an explicit confirmation
"""

import json

import pytest

from core.mongo.trades_service import (
    TradeNotFound,
    TradeStorageError,
    TradeValidationError,
)


@pytest.fixture
def client(monkeypatch):
    """The app, with the service replaced by a controllable stub."""
    import api.trades_controller as controller

    class StubService:
        def __init__(self):
            self.calls = []
            self.raise_with = None

        def _maybe_raise(self):
            if self.raise_with:
                raise self.raise_with

        def list_trades(self, **kwargs):
            self.calls.append(("list_trades", kwargs))
            self._maybe_raise()
            return {"items": [{"trade_id": "trade_1"}],
                    "pagination": {"page": 1, "page_size": 25, "total": 1,
                                   "pages": 1, "has_next": False,
                                   "has_previous": False},
                    "sort": {"by": "opened_at", "dir": "desc"},
                    "heavy_fields_included": kwargs.get("include_heavy", False)}

        def get_trade(self, trade_id, **kwargs):
            self.calls.append(("get_trade", trade_id, kwargs))
            self._maybe_raise()
            return {"trade_id": f"trade_{trade_id}"}

        def get_price_evolution(self, trade_id, **kwargs):
            self.calls.append(("get_price_evolution", trade_id, kwargs))
            self._maybe_raise()
            return {"trade_id": trade_id, "points": [{"price": 1.1}],
                    "pagination": {"offset": 0, "limit": 500, "total": 1,
                                   "has_next": False}}

        def create_trade(self, body):
            self.calls.append(("create_trade", body))
            self._maybe_raise()
            return {"trade_id": "trade_new"}

        def upsert_trade(self, body):
            self.calls.append(("upsert_trade", body))
            self._maybe_raise()
            return {"trade_id": "trade_new"}

        def update_trade(self, trade_id, patch):
            self.calls.append(("update_trade", trade_id, patch))
            self._maybe_raise()
            return {"trade_id": trade_id, **patch}

        def append_price_point(self, trade_id, point):
            self.calls.append(("append_price_point", trade_id, point))
            self._maybe_raise()
            return 7

        def close_trade(self, trade_id, close_data, analysis_at_close=None):
            self.calls.append(("close_trade", trade_id, close_data))
            self._maybe_raise()
            return {"trade_id": trade_id, "status": "CLOSED"}

        def delete_trade(self, trade_id, **kwargs):
            self.calls.append(("delete_trade", trade_id, kwargs))
            self._maybe_raise()
            return {"trade_id": trade_id, "mode": kwargs["mode"].value}

        def restore_trade(self, trade_id):
            self.calls.append(("restore_trade", trade_id))
            self._maybe_raise()
            return {"trade_id": trade_id, "deleted_at": None}

        def purge_deleted(self, **kwargs):
            self.calls.append(("purge_deleted", kwargs))
            self._maybe_raise()
            return {"dry_run": not kwargs.get("confirm"), "would_delete": 3}

        def stats(self, symbol=None):
            self.calls.append(("stats", symbol))
            self._maybe_raise()
            return {"total": 5, "win_rate_percent": 60.0}

        def get_status(self):
            self.calls.append(("get_status",))
            return {"healthy": self.healthy, "config": {"uri": "mongodb://h"}}

        healthy = True

    stub = StubService()
    monkeypatch.setattr(controller, "get_trades_service", lambda: stub)
    app = controller.create_app()
    app.config["TESTING"] = True
    test_client = app.test_client()
    test_client.stub = stub
    return test_client


def body_of(response):
    return json.loads(response.data)


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------

def test_every_response_uses_the_same_envelope(client):
    """A client must not have to guess which shape it received."""
    ok = client.get("/api/v1/trades")
    assert ok.status_code == 200
    payload = body_of(ok)
    assert set(payload) >= {"success", "data", "error", "request_id", "timestamp"}
    assert payload["success"] is True and payload["error"] is None

    client.stub.raise_with = TradeNotFound("no trade trade_9")
    bad = client.get("/api/v1/trades/9")
    failure = body_of(bad)
    assert set(failure) >= {"success", "data", "error", "request_id"}
    assert failure["success"] is False
    assert failure["error"]["code"] == "not_found"


def test_a_request_id_is_always_present_for_correlating_logs(client):
    assert body_of(client.get("/api/v1/trades"))["request_id"]


# --------------------------------------------------------------------------
# status mapping -- the part retry logic depends on
# --------------------------------------------------------------------------

@pytest.mark.parametrize("exc, status, code", [
    (TradeValidationError("bad page_size"), 400, "validation_error"),
    (TradeNotFound("no trade"), 404, "not_found"),
    (TradeStorageError("connection refused"), 503, "storage_unavailable"),
    (RuntimeError("boom"), 500, "internal_error"),
])
def test_exception_type_maps_to_the_right_status(client, exc, status, code):
    client.stub.raise_with = exc
    response = client.get("/api/v1/trades")
    assert response.status_code == status
    assert body_of(response)["error"]["code"] == code


def test_internal_error_text_is_never_returned_to_the_caller(client):
    """Internal messages carry queries, table names and sometimes URIs."""
    client.stub.raise_with = RuntimeError("mongodb://admin:hunter2@prod/db down")
    response = client.get("/api/v1/trades")
    assert response.status_code == 500
    assert "hunter2" not in response.get_data(as_text=True)
    assert "prod" not in response.get_data(as_text=True)


def test_storage_failure_is_retryable_not_a_client_error(client):
    """503 tells a client to retry; 400 tells it to give up. They differ."""
    client.stub.raise_with = TradeStorageError("timeout")
    assert client.get("/api/v1/trades").status_code == 503


# --------------------------------------------------------------------------
# JSON everywhere
# --------------------------------------------------------------------------

def test_unknown_routes_answer_json_not_html(client):
    response = client.get("/api/v1/trades/../../etc/passwd")
    assert response.status_code in (404, 405)
    assert body_of(response)["success"] is False


def test_wrong_method_answers_json(client):
    response = client.put("/api/v1/trades")
    assert response.status_code == 405
    assert body_of(response)["error"]["code"] == "method_not_allowed"


def test_a_missing_json_body_is_a_clear_400(client):
    response = client.post("/api/v1/trades", data="not json",
                           content_type="text/plain")
    assert response.status_code == 400
    assert body_of(response)["error"]["code"] == "validation_error"


def test_a_non_object_json_body_is_rejected(client):
    response = client.post("/api/v1/trades", json=[1, 2, 3])
    assert response.status_code == 400


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

def test_pagination_and_sorting_reach_the_service(client):
    client.get("/api/v1/trades?page=3&page_size=10&sort_by=symbol&sort_dir=asc")
    _, kwargs = client.stub.calls[-1]
    assert kwargs["page"] == 3 and kwargs["page_size"] == 10
    assert kwargs["sort_by"] == "symbol" and kwargs["sort_dir"] == "asc"


def test_filters_reach_the_service(client):
    client.get("/api/v1/trades?symbol=EURUSD&status=CLOSED")
    _, kwargs = client.stub.calls[-1]
    assert kwargs["filters"] == {"symbol": "EURUSD", "status": "CLOSED"}


def test_a_non_numeric_page_is_a_400_not_a_crash(client):
    response = client.get("/api/v1/trades?page=abc")
    assert response.status_code == 400
    assert "integer" in body_of(response)["error"]["message"]


def test_a_non_boolean_flag_is_a_400(client):
    response = client.get("/api/v1/trades?include_heavy=maybe")
    assert response.status_code == 400


def test_heavy_fields_are_off_unless_asked_for(client):
    client.get("/api/v1/trades")
    assert client.stub.calls[-1][1]["include_heavy"] is False
    client.get("/api/v1/trades?include_heavy=true")
    assert client.stub.calls[-1][1]["include_heavy"] is True


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

def test_create_returns_201_and_upsert_returns_200(client):
    assert client.post("/api/v1/trades", json={"ticket": 1}).status_code == 201
    assert client.stub.calls[-1][0] == "create_trade"

    assert client.post("/api/v1/trades?upsert=true",
                       json={"ticket": 1}).status_code == 200
    assert client.stub.calls[-1][0] == "upsert_trade"


def test_appending_a_price_point_reports_the_new_count(client):
    response = client.post("/api/v1/trades/1/price-evolution", json={"price": 1.1})
    assert response.status_code == 201
    assert body_of(response)["data"]["price_evolution_count"] == 7


# --------------------------------------------------------------------------
# deletes
# --------------------------------------------------------------------------

def test_delete_defaults_to_soft(client):
    client.delete("/api/v1/trades/1")
    _, _, kwargs = client.stub.calls[-1]
    assert kwargs["mode"].value == "soft"
    assert kwargs["confirm"] is False


def test_an_unknown_delete_mode_is_rejected(client):
    response = client.delete("/api/v1/trades/1?mode=obliterate")
    assert response.status_code == 400
    assert "mode must be one of" in body_of(response)["error"]["message"]


def test_hard_delete_passes_confirmation_through_explicitly(client):
    client.delete("/api/v1/trades/1?mode=hard&confirm=true")
    _, _, kwargs = client.stub.calls[-1]
    assert kwargs["mode"].value == "hard" and kwargs["confirm"] is True


def test_the_actor_is_recorded_from_the_header(client):
    """A destructive action should say who asked for it."""
    client.delete("/api/v1/trades/1", headers={"X-Actor": "fares"})
    assert client.stub.calls[-1][2]["actor"] == "fares"


def test_purge_is_a_dry_run_by_default(client):
    response = client.post("/api/v1/trades/purge")
    assert client.stub.calls[-1][1]["confirm"] is False
    assert body_of(response)["data"]["dry_run"] is True


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_health_returns_503_when_the_database_is_down(client):
    """
    A health endpoint answering 200 with {"healthy": false} is not a health
    endpoint -- no load balancer or monitor reads the body.
    """
    assert client.get("/api/v1/trades/health").status_code == 200
    client.stub.healthy = False
    assert client.get("/api/v1/trades/health").status_code == 503
