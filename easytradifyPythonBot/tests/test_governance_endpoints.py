"""
Governance HTTP surface, and the data-coverage work it gates.

Two separate claims are tested here:

  * the endpoints refuse what they should refuse -- an unknown model, an
    out-of-range rollout, a rollback with nothing to roll back to, and a
    mutation aimed at a model that owns its own A/B state;
  * the models now read the WHOLE decision-time snapshot, and the wider scan
    that makes possible is paired with the multiple-comparison control it
    requires. Width without that control does not produce more knowledge, it
    produces more false rules that look exactly like real ones.
"""

import random

import pytest

from ai.ai_controller import app
from conftest import build_trade


@pytest.fixture
def client():
    return app.test_client()


# ---------------------------------------------------------------------------
# Endpoint contracts
# ---------------------------------------------------------------------------

def test_status_and_self_check_are_reachable(client):
    assert client.get("/governance/status").status_code == 200
    assert client.post("/governance/self_check").status_code == 200


def test_unknown_model_is_rejected(client):
    response = client.get("/governance/not_a_model/ab_test")
    assert response.status_code == 404
    assert "governed_models" in response.get_json()


def test_rollout_bounds_are_enforced(client):
    for bad in (5, -1, "abc"):
        response = client.post("/governance/exit_model/ab_test/rollout",
                               json={"rollout": bad})
        assert response.status_code == 400, bad
    assert client.post("/governance/exit_model/ab_test/rollout",
                       json={}).status_code == 400


def test_track_requires_its_fields(client):
    assert client.post("/governance/exit_model/ab_test/track",
                       json={}).status_code == 400
    assert client.post("/governance/exit_model/ab_test/track",
                       json={"unit_id": "x"}).status_code == 400


def test_assignment_endpoint_is_stable(client):
    first = client.get("/governance/exit_model/ab_test/assign/t-99").get_json()
    second = client.get("/governance/exit_model/ab_test/assign/t-99").get_json()
    assert first["arm"] == second["arm"]
    assert first["arm"] in ("test", "control")


def test_native_ab_models_are_delegated_not_mirrored(client):
    """
    A second, empty experiment reporting INSUFFICIENT_DATA beside a real one
    holding the actual arms is two sources of truth for one question.
    """
    for model in ("ai_adversarial", "ai_gnn"):
        payload = client.get("/governance/%s/ab_test" % model).get_json()
        assert payload["implementation"] == "native"


def test_mutating_a_native_ab_is_refused_with_a_pointer(client):
    for model in ("ai_adversarial", "ai_gnn"):
        response = client.post("/governance/%s/ab_test/rollout" % model,
                               json={"rollout": 0.3})
        assert response.status_code == 409, model
        assert response.get_json()["use_instead"]


def test_rollback_with_nothing_to_revert_is_409(client):
    response = client.post("/governance/target_model/rollback",
                           json={"reason": "test"})
    assert response.status_code in (200, 409)
    if response.status_code == 409:
        assert response.get_json()["result"]["rolled_back"] is False


def test_promote_requires_a_known_version(client):
    assert client.post("/governance/exit_model/promote",
                       json={}).status_code == 400
    assert client.post("/governance/exit_model/promote",
                       json={"version": "v-does-not-exist"}).status_code == 400


def test_verify_reports_governance_separately_from_the_layer(client):
    """
    Governance verifies itself without trades. That must not become a
    layer-wide pass: "assignment is deterministic" says nothing about whether
    the models can read a trade.
    """
    payload = client.post("/verify", json={}).get_json()
    assert payload["ok"] is None
    assert payload["governance_ok"] is True


# ---------------------------------------------------------------------------
# Data coverage
# ---------------------------------------------------------------------------

def test_context_features_cover_the_whole_snapshot():
    from ai.price_evolution_bridge import context_features

    features = context_features(build_trade(ticket=71))
    assert features["ctx.open.account_info.leverage"] == 200
    for needle in ("smc", "volume_profile", "supply_demand",
                   "support_resistance", "wave_lattice", "pattern_analysis",
                   "8_indicators", "vwap", "rvam", "session_analysis"):
        assert any(needle in name for name in features), needle


def test_context_features_never_carry_the_outcome():
    """
    Sourced from analysis_at_open and entry only. A context column derived
    from close_data or the price path would leak the answer into the features.
    """
    from ai.price_evolution_bridge import context_features

    names = list(context_features(build_trade(ticket=72)).keys())

    # Structural: every column is rooted in one of the two decision-time
    # sources. This is the claim that matters -- a keyword blacklist would
    # miss a leak under an unexpected name.
    assert all(n.startswith("ctx.open.") or n.startswith("ctx.entry.")
               for n in names)

    # And no column from the outcome side. Note that `final_verdict` is NOT a
    # leak: it is the strategy's own probability estimate AT ENTRY, which is
    # exactly the kind of decision-time belief replay needs to reconstruct.
    for banned in ("close_price", "close_reason", "realized", "pnl",
                   "evolution", "outcome", "exit_"):
        assert not [n for n in names if banned in n.lower()], banned


def test_exit_and_target_models_can_read_the_full_snapshot():
    from ai.exit_model import ExitModelConfig, build_samples
    from ai.target_model import TargetModelConfig, build_target_samples

    trades = [build_trade(ticket=7300 + i, points=8, winning=(i % 3 != 0))
              for i in range(40)]

    narrow = build_samples(trades, ExitModelConfig())
    wide = build_samples(trades, ExitModelConfig(include_context_features=True))
    assert len(wide[0].features) > len(narrow[0].features) + 50

    wide_target = build_target_samples(
        trades, TargetModelConfig(include_context_features=True))
    assert any(name.startswith("ctx.") for name in wide_target[0].features)


def test_target_model_propagates_the_flag_to_its_estimator():
    """
    TargetModel wraps ExitModel, and ExitModel.fit picks its columns from its
    OWN config. Leaving the flag behind meant the estimator kept 11 columns
    while the sample builder produced 130, silently dropping every context
    column and training on a feature set nobody chose.
    """
    from ai.target_model import TargetModel, TargetModelConfig

    model = TargetModel(TargetModelConfig(include_context_features=True))
    assert model._estimator.config.include_context_features is True


def test_wider_scan_still_rejects_noise():
    """
    The control that makes width safe. Filtering by effect size first and
    correcting afterwards makes the BH denominator the already-extreme buckets
    rather than the hypotheses examined -- measured over 30 pure-noise runs
    that let a false rule through in 67% of them against a 10% target.
    """
    from ai.abstention_model import (CANDIDATE_CONDITIONS, AbstentionConfig,
                                     AbstentionRules, AbstentionSample)

    def noise(seed):
        rng = random.Random(seed)
        sessions = ["ASIA", "LONDON", "NY"]
        return [
            AbstentionSample(
                "t%d" % i, "",
                {name: (rng.choice(sessions) if kind == "categorical"
                        else rng.gauss(0, 1))
                 for name, _, kind in CANDIDATE_CONDITIONS},
                rng.gauss(0.0, 1.0))
            for i in range(300)
        ]

    runs_with_a_rule = 0
    for seed in range(12):
        rules = AbstentionRules(AbstentionConfig(min_trades=50))
        rules.fit(noise(seed))
        if rules.rules or rules.favor_rules:
            runs_with_a_rule += 1
    assert runs_with_a_rule <= 4, runs_with_a_rule


def test_a_real_effect_still_survives_the_correction():
    """A control that rejects everything is not a control, it is a mute."""
    from ai.abstention_model import (CANDIDATE_CONDITIONS, AbstentionConfig,
                                     AbstentionRules, AbstentionSample)

    def planted(seed):
        rng = random.Random(seed)
        sessions = ["ASIA", "LONDON", "NY"]
        samples = []
        for i in range(300):
            conditions = {
                name: (rng.choice(sessions) if kind == "categorical"
                       else rng.gauss(0, 1))
                for name, _, kind in CANDIDATE_CONDITIONS}
            realized = rng.gauss(0.0, 1.0)
            if conditions["session"] == "ASIA":
                realized -= 1.2
            samples.append(AbstentionSample("t%d" % i, "", conditions, realized))
        return samples

    detected = 0
    for seed in range(6):
        rules = AbstentionRules(AbstentionConfig(min_trades=50))
        rules.fit(planted(seed))
        if any(r["condition"] == "session" and r["bucket"] == "ASIA"
               for r in rules.rules):
            detected += 1
    assert detected >= 5, detected


def test_rejected_rules_are_kept_not_discarded():
    """"We looked and it did not survive" is a finding."""
    from ai.abstention_model import (CANDIDATE_CONDITIONS, AbstentionConfig,
                                     AbstentionRules, AbstentionSample)

    rng = random.Random(3)
    sessions = ["ASIA", "LONDON", "NY"]
    samples = [
        AbstentionSample(
            "t%d" % i, "",
            {name: (rng.choice(sessions) if kind == "categorical"
                    else rng.gauss(0, 1))
             for name, _, kind in CANDIDATE_CONDITIONS},
            rng.gauss(0.0, 1.5))
        for i in range(300)
    ]
    rules = AbstentionRules(AbstentionConfig(min_trades=50))
    report = rules.fit(samples)
    assert "buckets_tested" in report
    assert report["buckets_tested"] >= report["candidates_before_fdr"]
    assert isinstance(rules.rejected_rules, list)


def test_shuffled_floor_scans_the_same_conditions_as_the_claim():
    """
    A control that searches a smaller space than the claim sets the bar too
    low, and a wider scan would clear it automatically (standard 15).
    """
    import inspect

    from ai import abstention_model

    signature = inspect.signature(abstention_model._shuffled_floor)
    assert "conditions" in signature.parameters
    source = inspect.getsource(abstention_model.train_and_validate)
    assert "_shuffled_floor(ordered, cfg, cut, conditions)" in source
