"""
The standards audit, as a test.

Every component in the AI layer is checked against the rules this package sets
for itself, rather than against a claim in a document. Two of these caught
real gaps the moment they were first run:

  * `price_evolution_bridge` -- standard 1's single decode boundary, the point
    every model's view of a trade passes through -- had no `get_status` and no
    `self_check` at all. `/verify` had been printing "price_evolution: NO
    self_check" for as long as that endpoint existed.
  * four `self_check`s returned ok=True on pure garbage. Their synthetic
    invariants did hold, but invariants hold on ANY input; that is what makes
    them invariants and what makes them worthless as evidence that the
    pipeline works.

The garbage test is the important one. A check that cannot fail is
indistinguishable from a stub that returns success, and this codebase has
found that shape repeatedly: a coverage report that certified loss as
lossless, a gate that dropped what it could not measure, an adaptive weight
loop that iterated an empty set.
"""

import importlib
import inspect

import pytest

from conftest import build_trade

# Every module that participates in the AI layer's verification contract.
COMPONENTS = [
    "ai.exit_model", "ai.target_model", "ai.calibration_model",
    "ai.abstention_model", "ai.market_synthesis", "ai.trade_quality",
    "ai.ai_adversarial", "ai.ai_gnn", "ai.gnn_analysis",
    "ai.adversarial_replay", "ai.ai_reinforcement", "ai.rl_policies",
    "ai.non_rl_intelligence", "ai.model_governance", "ai.model_performance",
    "ai.ablation", "ai.root_cause_analyzers", "ai.root_cause_trackers",
    "ai.root_cause_adapter", "ai.diagnosis_narrative",
    "ai.price_evolution_bridge", "ai.aireplay.data_engine",
    "ai.aireplay.replay_engine", "ai.aireplay.counterfactual",
    "ai.aireplay.consistency", "ai.aireplay.recorder", "ai.aireplay.stress",
    "ai.aireplay.live_recording", "ai.rule_experiments",
    "ai.mt5_history", "ai.history_enrichment", "ai.trade_evaluation", "ai.component_scorecard",
    "ai.trade_forensics", "ai.component_forensics",
    "ai.price_history_study", "ai.component_calibration",
    "ai.component_repair", "ai.group_model", "ai.rebuild_report", "ai.field_evolution",
    "ai.structure_lab", "ai.setup_lab", "ai.state_readings", "core.state_readings",
    "ai.deep_history_lab", "core.analysis_groups",
    "core.clv_absorption",
]

# Not every component's subject is a trade, and the garbage test only means
# something for the ones whose subject IS. Classified by what each self_check
# actually consumes rather than by what its signature accepts -- three of these
# take a `trades` argument and ignore it, which the first run of this file
# surfaced as four failures that were the test's fault, not the modules'.
SELF_CONTAINED = {
    # Verify their own invariants; a trade is not their input.
    "ai.model_governance",      # A/B assignment and rollback
    "ai.model_performance",     # scoring, on synthetic records
    "ai.ai_gnn",                # its own graph and A/B state
    "ai.root_cause_trackers",   # snapshot indexing under both key spellings
    "ai.aireplay.recorder",     # buffering, re-keying, discarding
    "ai.aireplay.live_recording",  # the flag and the safety guarantees
    "ai.rule_experiments",      # assignment and the refusal to recommend
    "ai.component_validation",  # synthetic noise and planted signal
    "ai.mt5_history",           # broker history; its subject is MT5
    "ai.history_enrichment",    # recomputation; its subject is MT5
    "ai.price_history_study",   # barrier and bracket arithmetic on bars
    "ai.component_calibration", # statistics on synthetic vectors
    "ai.component_repair",      # rule search on synthetic vectors
    "ai.group_model",           # category map consistency
    "ai.rebuild_report",        # report assembly
    "ai.field_evolution",       # five-star line on synthetic periods
    "ai.structure_lab",         # structure detection on a synthetic series
    "ai.setup_lab",             # session clock and the FX day boundary
    "ai.state_readings",        # the keep/drop line on synthetic periods
    "core.state_readings",      # reads a synthetic payload
    "ai.deep_history_lab",      # bid-bar fills and the rollover exclusion
    "core.analysis_groups",     # the group map on a synthetic payload
}

# Consumes OHLCV bars, not trades.
BAR_CONSUMERS = {"core.clv_absorption"}

TRADE_CONSUMERS = [m for m in COMPONENTS
                   if m not in SELF_CONTAINED and m not in BAR_CONSUMERS]


def _bars(count=30, absorption=True):
    bars = [{"high": 100 + i * 0.5 + 1, "low": 100 + i * 0.5 - 1,
             "close": 100 + i * 0.5, "volume": 100.0} for i in range(count)]
    if absorption:
        bars.append({"high": 115.05, "low": 114.95, "close": 115.04,
                     "volume": 900.0})
    return bars


def _call(module, argument):
    check = module.self_check
    if not inspect.signature(check).parameters:
        return check()
    return check(argument)


@pytest.mark.parametrize("module_name", COMPONENTS)
def test_every_component_exposes_module_level_endpoints(module_name):
    """
    Standard 12. An interface that is right only if you already know its shape
    is not an interface: `non_rl_intelligence` had both, as methods, so the
    module-level call every other component answers raised AttributeError.
    """
    module = importlib.import_module(module_name)
    assert callable(getattr(module, "get_status", None)), module_name
    assert callable(getattr(module, "self_check", None)), module_name


@pytest.mark.parametrize("module_name", COMPONENTS)
def test_get_status_names_its_component(module_name):
    module = importlib.import_module(module_name)
    status = module.get_status()
    assert isinstance(status, dict)
    assert status.get("component") or status.get("phase") or status.get("version")


@pytest.mark.parametrize("module_name", COMPONENTS)
def test_self_check_returns_a_tri_state(module_name):
    """
    `ok` is True, False or None -- never absent, and never a truthy string.
    None means "not exercised", which a boolean cannot express (standard 19).
    """
    module = importlib.import_module(module_name)
    report = _call(module, None)
    assert isinstance(report, dict), module_name
    assert "ok" in report, module_name
    assert report["ok"] in (True, False, None), (module_name, report["ok"])


@pytest.mark.parametrize("module_name", TRADE_CONSUMERS)
def test_no_self_check_passes_on_garbage(module_name):
    """
    THE test. A self_check that reports ok=True on undecodable input has
    verified nothing about the pipeline and said the opposite.
    """
    module = importlib.import_module(module_name)
    report = _call(module, [{"garbage": True}, {"nonsense": 1}])
    assert report["ok"] is not True, (
        module_name, "reported ok=True on garbage input")


@pytest.mark.parametrize("module_name", TRADE_CONSUMERS)
def test_valid_data_is_not_reported_as_broken(module_name):
    """
    The other direction. A guard that refuses everything is as useless as one
    that accepts everything, and pins the whole-layer gate red.
    """
    module = importlib.import_module(module_name)
    trades = [build_trade(ticket=5200 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    report = _call(module, trades)
    assert report["ok"] is not False, (
        module_name, report.get("reason") or report.get("error"))


def test_every_component_reaches_the_whole_layer_gate():
    """
    A component missing from /verify is unverified no matter how good its own
    self_check is -- which is how GNN and adversarial were excluded from `ok`
    while the gate reported success.
    """
    from ai.ai_controller import app

    trades = [build_trade(ticket=5300 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    payload = app.test_client().post("/verify", json={"trades": trades}).get_json()

    assert payload["unverified_components"] == []
    for name, component in payload["components"].items():
        assert isinstance(component.get("self_check"), dict), name
        assert component["self_check"]["ok"] in (True, False, None), name


def test_the_decode_boundary_is_verifiable():
    """
    Standard 1's single decode boundary was the one component /verify could
    not check. Everything downstream reads trades through it.
    """
    from ai import price_evolution_bridge

    trades = [build_trade(ticket=5400 + i, points=6) for i in range(10)]
    report = price_evolution_bridge.self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["decode_is_idempotent"]
    assert report["checks"]["invents_no_fields"]
    assert report["checks"]["context_features_are_decision_time"]


def test_bar_consumers_refuse_garbage_and_accept_bars():
    """
    clv_absorption's subject is an OHLCV bar, not a trade. Feeding it trades
    is a category error -- and the first version of this file made it.
    """
    from core import clv_absorption

    assert clv_absorption.self_check([{"garbage": True}])["ok"] is not True
    good = clv_absorption.self_check(_bars())
    assert good["ok"] is True, good.get("error")


def test_self_contained_components_do_not_depend_on_trades():
    """
    These verify their own invariants. Stated explicitly so the garbage test's
    silence about them is a documented exemption rather than an oversight.
    """
    for module_name in sorted(SELF_CONTAINED):
        module = importlib.import_module(module_name)
        report = _call(module, None)
        assert report["ok"] is True, (module_name, report.get("error"))
