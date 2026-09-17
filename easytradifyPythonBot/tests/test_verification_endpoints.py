"""
Verification surfaces: the introspection APIs and the HTTP endpoints that
expose them.

These exist so the AI layer can be checked from outside rather than trusted.
"""

import pytest

from ai import ai_reinforcement
from ai.ai_adversarial import AIAdversarial
from ai.non_rl_intelligence import NonRLIntelligenceController

from conftest import build_trade


# ---------------------------------------------------------------------------
# Module-level introspection
# ---------------------------------------------------------------------------

def test_rl_status_reports_real_capability():
    status = ai_reinforcement.get_status()
    assert status["component"] == "reinforcement_learning"
    assert status["version"]
    # "off" and "on but untrainable" must be distinguishable.
    assert "torch_available" in status and "trainable" in status
    assert set(status["promotion_gates"]) == {
        "min_profit_factor", "min_baseline_delta", "max_drawdown"
    }


def test_rl_self_check_passes_on_real_trades(trades):
    report = ai_reinforcement.self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["sequences_built"] == len(trades)
    assert report["checks"]["never_concatenated"] is True
    assert report["checks"]["all_snapshots_priced"] is True


def test_rl_self_check_reports_failure_instead_of_raising():
    report = ai_reinforcement.self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["sequences_built"] == 0


def test_non_rl_status_reports_per_model_fit_state():
    status = NonRLIntelligenceController().get_status()
    assert status["component"] == "non_rl_intelligence"
    assert set(status["fitted"]) == {
        "outcome_predictor", "failure_classifier", "regime_model", "calibrator"
    }
    assert status["seeding_is_instance_scoped"] is True


def test_non_rl_self_check_asserts_no_leakage(trades):
    report = NonRLIntelligenceController().self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["no_leakage"] is True
    assert report["checks"]["leaked_features"] == []
    assert report["checks"]["records_built"] == len(trades)


def test_non_rl_self_check_would_catch_leakage(trades, monkeypatch):
    """The leakage check must actually be capable of failing."""
    import ai.non_rl_intelligence as module
    from ai.non_rl_intelligence import DecisionRecord

    def leaky(trade_list, bridge=None):
        return [DecisionRecord(
            decision_id="1", timestamp="2026-09-01T10:00:00Z",
            observation={"open.is_winning": 1.0}, outcome={"success": 1},
        )]

    monkeypatch.setattr(module, "decision_records_from_trades", leaky)
    report = NonRLIntelligenceController().self_check(trades)
    assert report["ok"] is False
    assert "open.is_winning" in report["checks"]["leaked_features"]


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    import ai.ai_controller as controller
    controller.app.config["TESTING"] = True
    return controller.app.test_client()


def test_controller_imports_and_serves(client):
    """
    Regression: this service could not start at all -- it imported
    ai_ab_testing and ai_diffusion, neither of which exists in the repo.
    """
    assert client.get("/health").status_code == 200


def test_rl_status_endpoint(client):
    response = client.get("/rl/status")
    assert response.status_code == 200
    assert response.get_json()["component"] == "reinforcement_learning"


def test_non_rl_status_endpoint(client):
    response = client.get("/non_rl/status")
    assert response.status_code == 200
    assert response.get_json()["component"] == "non_rl_intelligence"


def test_self_check_endpoints_report_pass_and_fail(client, trades):
    ok = client.post("/rl/self_check", json={"trades": trades})
    assert ok.status_code == 200 and ok.get_json()["ok"] is True

    bad = client.post("/rl/self_check", json={"trades": [{"junk": 1}]})
    assert bad.status_code == 422, "a failing self-check must not return 200"


def test_non_rl_self_check_endpoint(client, trades):
    response = client.post("/non_rl/self_check", json={"trades": trades})
    assert response.status_code == 200
    assert response.get_json()["checks"]["no_leakage"] is True


def test_exit_model_endpoints(client, trades):
    status = client.get("/exit_model/status")
    assert status.status_code == 200
    assert status.get_json()["predicts_direction"] is False

    ok = client.post("/exit_model/self_check", json={"trades": trades})
    assert ok.status_code == 200 and ok.get_json()["ok"] is True

    trained = client.post("/exit_model/train", json={"trades": trades})
    assert trained.status_code == 200
    # Too few trades to promote; the reason must be stated, not implied.
    assert trained.get_json()["promoted"] is False
    assert trained.get_json()["rejected_because"]

    assert client.post("/exit_model/train", json={}).status_code == 400


def test_target_model_endpoints(client, trades):
    status = client.get("/target_model/status")
    assert status.status_code == 200
    assert status.get_json()["population"] == "in-profit points only"

    ok = client.post("/target_model/self_check", json={"trades": trades})
    assert ok.status_code in (200, 422)

    trained = client.post("/target_model/train", json={"trades": trades})
    assert trained.status_code == 200
    assert trained.get_json()["promoted"] is False
    assert trained.get_json()["rejected_because"]

    assert client.post("/target_model/train", json={}).status_code == 400


def test_calibration_endpoints(client, trades):
    status = client.get("/calibration/status")
    assert status.status_code == 200
    assert status.get_json()["gates_on_auc"] is False

    checked = client.post("/calibration/self_check", json={"trades": trades})
    assert checked.status_code in (200, 422)

    trained = client.post("/calibration/train", json={"trades": trades})
    assert trained.status_code == 200
    assert trained.get_json()["promoted"] is False

    assert client.post("/calibration/train", json={}).status_code == 400


def test_abstention_endpoints(client, trades):
    status = client.get("/abstention/status")
    assert status.status_code == 200
    assert status.get_json()["is_meta_labeling"] is False

    checked = client.post("/abstention/self_check", json={"trades": trades})
    assert checked.status_code in (200, 422)

    trained = client.post("/abstention/train", json={"trades": trades})
    assert trained.status_code == 200
    assert trained.get_json()["promoted"] is False

    assert client.post("/abstention/train", json={}).status_code == 400


def test_replay_phase1_endpoints(client, trades):
    status = client.get("/replay/phase1/status")
    assert status.status_code == 200
    assert status.get_json()["synthesises_missing_events"] is False

    checked = client.post("/replay/phase1/self_check", json={"trades": trades})
    assert checked.status_code == 200 and checked.get_json()["ok"] is True

    extracted = client.post("/replay/phase1/extract", json={"trades": trades})
    assert extracted.status_code == 200
    body = extracted.get_json()
    assert body["extracted"] == len(trades)
    assert body["records"][0]["leakage"]["outcome_leaked"] == []

    assert client.post("/replay/phase1/extract", json={}).status_code == 400


def test_synthesis_endpoints(client, trades):
    status = client.get("/synthesis/status")
    assert status.status_code == 200
    assert status.get_json()["produces_score"] is False

    checked = client.post("/synthesis/self_check", json={"trades": trades})
    assert checked.status_code == 200 and checked.get_json()["ok"] is True

    result = client.post("/synthesis/synthesise", json={"trades": trades})
    assert result.status_code == 200
    body = result.get_json()
    assert body["synthesised"] == len(trades)
    first = body["results"][0]
    assert len(first["hierarchy"]) == 8
    assert first["uncertainty"]["level"] in ("LOW", "MEDIUM", "HIGH")
    assert first["synthesis_hash"]

    assert client.post("/synthesis/synthesise", json={}).status_code == 400


def test_replay_endpoints(client, trades):
    status = client.get("/replay/status")
    assert status.status_code == 200
    assert status.get_json()["attribution_claims_causation"] is False

    run = client.post("/replay/run", json={"trades": trades})
    assert run.status_code == 200
    body = run.get_json()
    assert body["replayed"] == len(trades)
    first = body["results"][0]
    assert set(first["divergences"]) >= {
        "first_anomaly", "first_prediction_error",
        "first_decision_error", "first_material_divergence"}

    assert client.post("/replay/run", json={}).status_code == 400


def test_counterfactual_endpoints(client, trades):
    status = client.get("/replay/counterfactual/status")
    assert status.status_code == 200
    assert status.get_json()["invents_prices"] is False

    result = client.post("/replay/counterfactual", json={"trades": trades})
    assert result.status_code == 200
    body = result.get_json()
    assert body["branched"] == len(trades)
    assert body["aggregate"]["policies"]

    assert client.post("/replay/counterfactual", json={}).status_code == 400


def test_consistency_endpoint(client, trades):
    result = client.post("/replay/consistency", json={"trades": trades})
    assert result.status_code == 200
    body = result.get_json()
    assert body["verdict"] in ("CONSISTENT", "DRIFTED", "NOT_COMPARABLE")
    assert "disagreement_rate" in body

    assert client.post("/replay/consistency", json={}).status_code == 400


def test_verify_endpoint_covers_every_component(client, trades):
    response = client.post("/verify", json={"trades": trades})
    assert response.status_code == 200

    report = response.get_json()
    assert {"gnn", "adversarial", "reinforcement_learning",
            "non_rl_intelligence", "price_evolution", "exit_model",
            "target_model", "calibration_model",
            "abstention_model", "aireplay_phase1",
            "market_synthesis", "replay_engine",
            "counterfactual", "simulator_consistency"} <= set(report["components"])
    assert report["ok"] is True
    coverage = report["components"]["price_evolution"]["coverage"]
    assert coverage["total_features"] > 50


def test_verify_endpoint_works_without_trades(client):
    response = client.post("/verify", json={})
    assert response.status_code == 200
    # No data to exercise means no verdict, not a false pass.
    assert response.get_json()["ok"] is None


def test_rollout_endpoint_validates_input(client):
    for bad in ({}, {"rollout": "abc"}, {"rollout": 5}, {"rollout": -1}):
        response = client.post("/adversarial/ab_test/rollout", json=bad)
        assert response.status_code in (400, 503), bad


def test_adversarial_ab_endpoints_round_trip(client):
    import ai.ai_controller as controller
    controller._adversarial = AIAdversarial()

    assert client.get("/adversarial/ab_test").status_code == 200

    set_response = client.post("/adversarial/ab_test/rollout", json={"rollout": 0.5})
    assert set_response.status_code == 200
    assert set_response.get_json()["rollout"] == 0.5

    tracked = client.post("/adversarial/ab_test/track",
                          json={"trade_id": 1, "outcome": 1, "profit": 10.0,
                                "used_adversarial": True})
    assert tracked.status_code == 200
    assert tracked.get_json()["total_trades"] == 1

    controller._adversarial = None


def test_track_endpoint_requires_identifiers(client):
    import ai.ai_controller as controller
    controller._adversarial = AIAdversarial()
    assert client.post("/adversarial/ab_test/track", json={"outcome": 1}).status_code == 400
    controller._adversarial = None


# ---------------------------------------------------------------------------
# Tri-state self_check, and the whole-layer gate
#
# `ok` was a boolean, and that single bit was hiding two different states.
# A module given data it could not sample from reported ok=False -- a working
# module called broken -- which pinned /verify red on thin data. Meanwhile
# /verify built its verdict ONLY from components carrying a dict self_check,
# so GNN and adversarial (which had none) were dropped from the numerator
# entirely: the gate could answer ok=True having verified nothing about the
# component the controller itself prints as ESSENTIAL.
# ---------------------------------------------------------------------------

import importlib

import pytest as _pytest

TRI_STATE_MODULES = [
    "exit_model", "target_model", "abstention_model",
    "calibration_model", "market_synthesis", "ai_reinforcement",
]


@_pytest.mark.parametrize("module_name", TRI_STATE_MODULES)
def test_undecodable_input_fails_rather_than_excusing_itself(module_name):
    """A broken data path must fail the gate, not report 'not exercised'."""
    module = importlib.import_module(f"ai.{module_name}")
    report = module.self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["usable_trades"] == 0
    assert "data path" in report["reason"]


@_pytest.mark.parametrize("module_name", TRI_STATE_MODULES)
def test_readable_input_never_reports_broken(module_name):
    """Valid trades must never make a healthy module report ok=False."""
    module = importlib.import_module(f"ai.{module_name}")
    trades = [build_trade(ticket=4100 + i, points=6, winning=(i % 3 != 0))
              for i in range(120)]
    report = module.self_check(trades)
    assert report["ok"] is not False, report.get("reason") or report.get("error")


def test_thin_data_is_not_exercised_rather_than_failed():
    """The distinction the boolean could not express."""
    from ai import target_model
    trades = [build_trade(ticket=4300 + i) for i in range(40)]
    report = target_model.self_check(trades)
    assert report["ok"] is None
    assert report["checks"]["samples_built"] == 0
    assert report["checks"]["usable_trades"] == len(trades)
    assert "data path" not in report["reason"]


def test_every_ai_module_exposes_module_level_endpoints():
    """Standard 12, checked rather than asserted in prose."""
    for module_name in TRI_STATE_MODULES + [
            "ai_adversarial", "non_rl_intelligence", "ai_gnn"]:
        module = importlib.import_module(f"ai.{module_name}")
        assert callable(getattr(module, "self_check", None)), module_name
        assert callable(getattr(module, "get_status", None)), module_name


def test_adversarial_self_check_is_deterministic():
    """It forces its own gates; a check decided by a coin flip proves nothing."""
    from ai import ai_adversarial
    trades = [build_trade(ticket=4500 + i) for i in range(10)]
    reports = [ai_adversarial.self_check(trades) for _ in range(3)]
    assert {r["ok"] for r in reports} == {True}
    assert {r["checks"]["adaptive_weights_move"] for r in reports} == {True}
    assert {r["checks"]["labels_aligned"] for r in reports} == {True}


def test_verify_gate_names_components_it_could_not_verify():
    """A component with no self_check must withhold ok, not vanish from it."""
    from ai.ai_controller import app

    trades = [build_trade(ticket=4700 + i, points=6) for i in range(60)]
    client = app.test_client()
    payload = client.post("/verify", json={"trades": trades}).get_json()

    assert payload["unverified_components"] == []
    assert isinstance(payload["not_exercised"], list)
    for name, component in payload["components"].items():
        if name == "price_evolution":
            continue
        assert isinstance(component.get("self_check"), dict), name
    assert payload["ok"] is True


def test_verify_without_trades_returns_no_verdict():
    """Nothing exercised must read as 'no verdict', never as a pass."""
    from ai.ai_controller import app

    payload = app.test_client().post("/verify", json={}).get_json()
    assert payload["ok"] is None
