"""
Phase 2 items 2 and 7: CLV Absorption, and Trade Quality.

Both were recorded as "already exist in core/" and neither did. The claim was
inherited from the readme's own progress table and repeated without being
checked -- `core/` has vwap.py and rvam.py, but nothing computed close
location value, and the many per-component scores (RSI, stochastic, pattern,
GNN, ADR) are not a Trade Quality layer.

The tests below are weighted toward the two properties each module could most
easily get wrong and still look right: a CLV sign error is invisible on
ordinary bars and inverts every decisive one, and a Trade Quality layer that
lets any dimension promote a trade has quietly become the point system readme
26.20 forbids.
"""

import pytest

from ai import trade_quality
from core import clv_absorption
from conftest import build_trade


# ---------------------------------------------------------------------------
# CLV Absorption (item 2)
# ---------------------------------------------------------------------------

def test_clv_endpoints_are_exact():
    """A sign error here is invisible mid-range and inverts decisive bars."""
    assert clv_absorption.close_location_value(10, 0, 10) == 1.0
    assert clv_absorption.close_location_value(10, 0, 0) == -1.0
    assert clv_absorption.close_location_value(10, 0, 5) == 0.0


def test_zero_range_bar_is_undefined_not_neutral():
    """
    0.0 means "closed exactly mid-range", which is a real observation. An
    unmeasurable bar must not be indistinguishable from a balanced one.
    """
    assert clv_absorption.close_location_value(5, 5, 5) is None
    assert clv_absorption.close_location_value(None, 0, 1) is None


def test_clv_is_bounded_when_a_feed_lies():
    """Real feeds report closes outside their own bar."""
    assert clv_absorption.close_location_value(10, 0, 99) == 1.0
    assert clv_absorption.close_location_value(10, 0, -99) == -1.0


def test_absorption_requires_both_conditions():
    """
    A quiet bar with a small range is just quiet; a heavy bar that travelled
    is ordinary continuation. The signature is the two together.
    """
    heavy_wide = clv_absorption.bar_absorption(
        {"high": 20, "low": 0, "close": 19, "volume": 1000}, 100.0, 5.0)
    light_narrow = clv_absorption.bar_absorption(
        {"high": 1, "low": 0, "close": 0.9, "volume": 10}, 100.0, 5.0)
    heavy_narrow = clv_absorption.bar_absorption(
        {"high": 1, "low": 0, "close": 0.9, "volume": 1000}, 100.0, 5.0)

    assert not heavy_wide["absorption"]
    assert not light_narrow["absorption"]
    assert heavy_narrow["absorption"]


def test_absorbed_side_follows_the_close():
    heavy_high = clv_absorption.bar_absorption(
        {"high": 1, "low": 0, "close": 0.95, "volume": 1000}, 100.0, 5.0)
    heavy_low = clv_absorption.bar_absorption(
        {"high": 1, "low": 0, "close": 0.05, "volume": 1000}, 100.0, 5.0)
    assert heavy_high["absorbed_side"] == "sellers_absorbed"
    assert heavy_low["absorbed_side"] == "buyers_absorbed"


def test_analysis_refuses_thin_input():
    result = clv_absorption.analyze_clv_absorption(
        [{"high": 1, "low": 0, "close": 1}])
    assert result["available"] is False
    assert "at least 3 bars" in result["reason"]


def test_analysis_finds_a_planted_absorption_bar():
    bars = [{"high": 100 + i * 0.5 + 1, "low": 100 + i * 0.5 - 1,
             "close": 100 + i * 0.5, "volume": 100.0} for i in range(30)]
    bars.append({"high": 115.05, "low": 114.95, "close": 115.04,
                 "volume": 900.0})
    result = clv_absorption.analyze_clv_absorption(bars)
    assert result["available"]
    assert result["recent_absorption"] is True
    assert result["effort_without_result"] is True


def test_clv_never_claims_direction():
    assert clv_absorption.get_status()["claims_direction"] is False


# ---------------------------------------------------------------------------
# Trade Quality (item 7)
# ---------------------------------------------------------------------------

def test_expectancy_arithmetic_is_correct():
    assert trade_quality.expected_return_r(0.5, 3.0) == pytest.approx(1.0)
    assert trade_quality.expected_return_r(0.5, 1.0) == pytest.approx(0.0)
    assert trade_quality.expected_return_r(0.4, 2.0) == pytest.approx(0.2)


def test_verdict_follows_expectancy():
    good = {"market_synthesis": {"probability_percent": 50},
            "risk_gate": {"risk_reward_ratio": 3.0}}
    poor = {"market_synthesis": {"probability_percent": 40},
            "risk_gate": {"risk_reward_ratio": 1.0}}
    assert trade_quality.assess(good).verdict == "ACCEPTABLE"
    assert trade_quality.assess(poor).verdict == "UNACCEPTABLE"


def test_no_dimension_can_promote_a_negative_expectancy():
    """
    THE property readme 26.20 demands. A point system fails this: stack enough
    favourable indicators and a bad trade votes itself up.
    """
    stacked = trade_quality.assess({
        "market_synthesis": {"probability_percent": 40},
        "risk_gate": {"risk_reward_ratio": 1.0},
        "gnn": {"gnn_influence": 0.95},
        "non_rl": {"failure_probability": 0.01},
        "deterministic": {
            "liquidity_events": {"quality": "EXCELLENT"},
            "micro_structure": {"state": "PERFECT"},
            "news_analysis": {"event_risk": "NONE"},
        },
    })
    assert stacked.verdict == "UNACCEPTABLE"


def test_a_veto_can_refuse_a_good_expectancy():
    """Gates refuse; they are not outvoted by arithmetic."""
    vetoed = trade_quality.assess({
        "market_synthesis": {"probability_percent": 50},
        "risk_gate": {"risk_reward_ratio": 3.0},
        "deterministic": {"vetos": {"news": True}},
    })
    assert vetoed.verdict == "UNACCEPTABLE"
    assert any("veto" in concern for concern in vetoed.concerns)


def test_verdict_is_withheld_without_its_inputs():
    assert trade_quality.assess(
        {"risk_gate": {"risk_reward_ratio": 2.0}}).verdict == "UNKNOWN"
    assert trade_quality.assess(
        {"market_synthesis": {"probability_percent": 60}}).verdict == "UNKNOWN"


def test_uncalibrated_probability_withholds_the_verdict():
    """
    E[R] from a probability with no ranking information is arithmetic on
    noise, and a confident number there is worse than no number.
    """
    result = trade_quality.assess(
        {"market_synthesis": {"probability_percent": 50},
         "risk_gate": {"risk_reward_ratio": 3.0}},
        probability_is_informative=False)
    assert result.verdict == "UNKNOWN"
    assert any("noise" in reason for reason in result.withheld_because)


def test_availability_is_explicit_not_inferred_from_zero():
    payload = trade_quality.assess({}).to_dict()
    assert payload["dimensions_available"] == 0
    assert payload["dimensions_total"] > 0


def test_output_is_not_a_score():
    payload = trade_quality.assess({
        "market_synthesis": {"probability_percent": 50},
        "risk_gate": {"risk_reward_ratio": 3.0}}).to_dict()
    assert payload["is_a_point_score"] is False
    assert "score" not in payload


def test_assesses_a_stored_trade():
    trade = build_trade(ticket=6500, points=6, winning=False)
    assessed = trade_quality.assess_trade(trade)
    assert assessed.verdict in (
        "ACCEPTABLE", "MARGINAL", "UNACCEPTABLE", "UNKNOWN")
    assert assessed.dimensions


# ---------------------------------------------------------------------------
# Ablation (phase 3 item 9)
#
# `ExperimentEngine.ablate_components` built ablated feature sets and nothing
# scored them -- the data half of an ablation, and the only half. A study that
# cannot measure the effect of a removal answers no question.
# ---------------------------------------------------------------------------

def test_dropping_a_section_actually_removes_it():
    """A prefix bug here would leave the section visible and be invisible."""
    from ai.ablation import _drop_section, _sections

    features = {
        "ctx.open.smc.confluence_count": 4.0,
        "ctx.open.smc.market_structure.last_event": 1.0,
        "ctx.open.account_info.leverage": 200.0,
        "return_r": 0.5,
    }
    dropped = _drop_section(features, "smc")
    assert not any(n.startswith("ctx.open.smc") for n in dropped)
    assert "ctx.open.account_info.leverage" in dropped
    assert "return_r" in dropped
    assert _sections(features) == ["account_info", "smc"]


def test_ablation_reports_a_noise_band():
    """
    Retraining on a different feature set moves the score even when the
    removed features were noise. Without a band, that variance is reported as
    a contribution.
    """
    from ai import ablation

    trades = [build_trade(ticket=6600 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    study = ablation.ablation_study(trades, max_sections=2, random_subsets=3)
    if study["measurable"]:
        assert study["noise_band"] is not None
        assert study["noise_band"]["threshold"] >= 0
        assert "harmful_sections" in study
    else:
        assert study["reason"]


def test_constant_sections_contribute_exactly_nothing():
    """
    These fixtures carry identical analysis across trades, so those columns
    are constant and removing them cannot change a score. A study reporting a
    contribution here would be reporting its own variance.
    """
    from ai import ablation

    trades = [build_trade(ticket=6700 + i, points=8, winning=(i % 3 != 0))
              for i in range(60)]
    study = ablation.ablation_study(trades, max_sections=3, random_subsets=3)
    if study["measurable"]:
        for row in study["sections"]:
            if row.get("contribution") is not None:
                assert row["contribution"] == 0.0


# ---------------------------------------------------------------------------
# Phase 0 item 7 -- closed trades stop receiving evolution updates
#
# The spec asks for this to be VERIFIED, and nothing verified it. `update_price`
# had one guard, `if not trade_id: return`, and would happily append to a
# CLOSED trade -- putting post-close prices into `price_evolution`, the field
# every model treats as the pre-close forward walk. The leakage firewall is
# enforced everywhere downstream and was open at the write.
# ---------------------------------------------------------------------------

class _FakeDoc:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None
        self.updates = []

    def to_dict(self):
        return dict(self._data or {})

    def get(self):
        return self

    def set(self, *args, **kwargs):
        self.updates.append(("set", args, kwargs))

    def update(self, *args, **kwargs):
        self.updates.append(("update", args, kwargs))


class _FakeCollection:
    def __init__(self, doc):
        self._doc = doc

    def document(self, _doc_id):
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self._doc = doc

    def collection(self, _name):
        return _FakeCollection(self._doc)


def _service_with(doc):
    from core.firebase.firebase_service import FirebaseService

    from core.firebase.firebase_config import FirebaseConfig

    service = FirebaseService.__new__(FirebaseService)
    service.db = _FakeDB(doc)
    service.initialized = True
    service.config = FirebaseConfig()
    service._convert_numpy_types = lambda value: value
    return service


def test_closed_trade_receives_no_further_evolution():
    doc = _FakeDoc({"status": "CLOSED", "price_evolution": [{"price": 1.0}]})
    _service_with(doc).update_price("t1", 1.23, 10.0, 1.0, 5.0)
    assert doc.updates == [], "a CLOSED trade was written to"


def test_open_trade_still_receives_evolution():
    """The guard must fail closed on CLOSED only -- not block live trades."""
    doc = _FakeDoc({"status": "OPEN", "price_evolution": [{"price": 1.0}]})
    _service_with(doc).update_price("t1", 1.23, 10.0, 1.0, 5.0)
    assert doc.updates, "an OPEN trade was refused an update"


def test_missing_status_does_not_block_updates():
    """
    Absence of a status is not evidence of closure. Blocking there would stop
    legitimate updates on any document written before the field existed.
    """
    doc = _FakeDoc({"price_evolution": []})
    _service_with(doc).update_price("t1", 1.23, 10.0, 1.0, 5.0)
    assert doc.updates
