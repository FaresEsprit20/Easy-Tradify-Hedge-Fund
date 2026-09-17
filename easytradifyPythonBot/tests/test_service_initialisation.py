"""
GNN and adversarial availability, and the credential path that gated it.

Two defects, both of which presented as a healthy-looking process:

  * `initialize_services()` was reachable only from `main()`. Serve the same
    app any other way -- `gunicorn ai_controller:app`, `waitress-serve`,
    importing `app` into a parent process -- and `_gnn` and `_adversarial`
    stay None forever. Every GNN and adversarial endpoint answers "not
    initialized" while the server returns 200 on everything else, and
    /verify reports `available: False` with no explanation.
  * `api/` was missing from the Firebase credential search, so any process
    started from the package root came up in OFFLINE MODE. That is not a
    degraded connection: the service queues writes in memory and never
    flushes them, because the batch processor only starts once `initialized`
    is True. The bot worked only because it happens to run from `api/`.

Both are the same shape as the rest of this codebase's history -- a component
silently inert while everything reports success.
"""

import os

import pytest

from conftest import build_trade


@pytest.fixture
def client():
    from ai.ai_controller import app
    return app.test_client()


def test_services_initialise_without_main(client):
    """
    The fix. `main()` is never called by a WSGI server, so initialisation
    cannot depend on it.
    """
    import ai.ai_controller as controller

    client.get("/health") if any(
        r.rule == "/health" for r in controller.app.url_map.iter_rules()
    ) else client.get("/governance/status")

    assert controller._initialized is True
    assert controller._gnn is not None, "GNN never initialised"
    assert controller._adversarial is not None, "adversarial never initialised"


def test_gnn_and_adversarial_endpoints_do_not_report_uninitialised(client):
    """These returned 400 'not initialized' on every call under a WSGI server."""
    for route in ("/gnn/status", "/adversarial/status",
                  "/gnn/ab_test", "/adversarial/ab_test"):
        response = client.get(route)
        assert response.status_code == 200, (route, response.get_json())


def test_verify_reports_them_available(client):
    trades = [build_trade(ticket=7700 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    payload = client.post("/verify", json={"trades": trades}).get_json()

    assert payload["unavailable_components"] == []
    for name in ("gnn", "adversarial"):
        component = payload["components"][name]
        assert component["available"] is True, name
        assert component["self_check"]["ok"] is True, name


def test_an_unavailable_component_explains_itself(client):
    """
    `available: False` with no reason is what sent this investigation down the
    wrong path twice. When it happens, it must say why.
    """
    trades = [build_trade(ticket=7800 + i, points=8) for i in range(60)]
    payload = client.post("/verify", json={"trades": trades}).get_json()
    for name in ("gnn", "adversarial"):
        component = payload["components"][name]
        assert "unavailable_reason" in component
        if component["available"]:
            assert component["unavailable_reason"] is None


def test_initialisation_is_idempotent(client):
    """
    It runs on every request through a before_request hook, so it has to be
    cheap and repeatable. Measured at 0.00s once Firebase is a singleton.
    """
    import ai.ai_controller as controller

    client.get("/governance/status")
    first_gnn = controller._gnn
    for _ in range(5):
        client.get("/governance/status")
    assert controller._gnn is first_gnn


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def _credentials_present():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.exists(os.path.join(root, "api", "firebase-credentials.json"))


def test_api_directory_is_in_the_credential_search():
    """
    Its absence is why the controller and the replay CLI both came up offline
    from the package root. Asserted against the source rather than by
    connecting, so this holds on a machine with no credentials at all.
    """
    import inspect

    from core.firebase import firebase_service

    source = inspect.getsource(firebase_service.FirebaseService._init_firebase)
    assert '"api", "firebase-credentials.json"' in source


@pytest.mark.skipif(not _credentials_present(),
                    reason="no credentials file on this machine")
def test_connects_online_from_the_package_root():
    """
    OFFLINE MODE here is not a degraded connection -- writes queue in memory
    and are never flushed. A process that reports healthy while silently
    discarding every write is the worst available outcome.
    """
    os.environ.pop("FIREBASE_CREDENTIALS_PATH", None)
    from core.firebase import get_firebase_service

    service = get_firebase_service()
    assert service.initialized is True
    assert service.is_healthy() is True
