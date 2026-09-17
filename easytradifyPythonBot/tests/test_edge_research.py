"""
The edge-research tooling: it must find real signal and refuse fake signal.

These modules exist to answer "is this an edge?", so the only thing that makes
them trustworthy is that they can say NO. A search that always finds something
is worse than no search: it manufactures confidence, and this project has
already shipped one rule change on that basis that reversed out of sample.

Every test here plants a KNOWN answer and requires the tool to recover it --
including the negative cases, where the correct answer is "nothing here".

Three real bugs in the auditor were caught by exactly this discipline while it
was being written, and all three would have produced a clean-looking report
that had silently discarded the most interesting fields:

  * MIN_DISTINCT = 3 dropped every boolean flag (a flag has 2 values)
  * statistics.median on a binary field returns one of the two values, so
    `v > median` selects an EMPTY side and the field vanishes
  * after both fixes, audit() still failed -- it held a SECOND copy of the
    threshold logic inline, which the fix never reached
"""

import random

import pytest


# --------------------------------------------------------------------------
# component_audit_360
# --------------------------------------------------------------------------

def _planted_rows(n=240, seed=5):
    """Rows where one field perfectly predicts the outcome and others do not."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        signal = rng.choice([-1.0, 1.0])
        rows.append({
            "trade_id": "t%d" % i, "symbol": "X", "opened_at": "%04d" % i,
            "r": signal, "sign": 1,
            "features": {"real.signal": signal,
                         "junk.random": rng.gauss(0, 1),
                         "dead.constant": 1.0},
            "categoricals": {"market.regime": "TREND" if signal > 0 else "RANGE"},
        })
    return rows


def test_the_audit_recovers_a_planted_signal():
    from ai.component_audit_360 import audit

    report = audit(rows=_planted_rows(), permutations=40, folds=3)
    edges = {f["field"] for f in report.get("edges", [])}
    assert "real.signal" in edges, (
        "the audit failed to recover a field that perfectly predicts the "
        "outcome -- it cannot be trusted to find a subtler one")


def test_the_audit_does_not_promote_noise():
    from ai.component_audit_360 import audit

    report = audit(rows=_planted_rows(), permutations=40, folds=3)
    edges = {f["field"] for f in report.get("edges", [])}
    assert "junk.random" not in edges


def test_a_constant_field_is_reported_dead_not_skipped():
    """
    'This was never exercised' is a finding. Several components in this
    codebase sat dead while appearing to work -- a DXY basket with no symbol,
    an order-block status unreachable by construction.
    """
    from ai.component_audit_360 import audit

    report = audit(rows=_planted_rows(), permutations=20, folds=3)
    dead = {d["field"] for d in report.get("dead_sample", [])}
    assert "dead.constant" in dead


def test_binary_fields_are_splittable():
    """
    THE bug. statistics.median on a binary field returns one of the two
    values, so `v > median` yields an empty side and every boolean flag in
    the payload is silently discarded.
    """
    from ai.component_audit_360 import _split_point

    for values in ([0.0] * 30 + [1.0] * 70,      # uneven
                   [0.0] * 50 + [1.0] * 50,      # even
                   [-1.0] * 40 + [1.0] * 60):
        point = _split_point(values)
        assert point is not None
        assert any(v > point for v in values), "empty upper side"
        assert any(v <= point for v in values), "empty lower side"


def test_flatten_finds_nested_and_boolean_fields():
    from ai.component_audit_360 import flatten

    flat = flatten({
        "smc": {"order_block": {"detected": True, "score": 0.8},
                "events": [1, 2, 3]},
        "indicators": {"rsi": {"value": 71.2}},
        "_private": {"ignored": 1},
        "label": "not-a-number",
    })
    assert flat["smc.order_block.detected"] == 1.0     # bool -> 1/0
    assert flat["smc.order_block.score"] == 0.8
    assert flat["smc.events.count"] == 3.0             # list -> length
    assert flat["indicators.rsi.value"] == 71.2
    assert not any(k.startswith("_private") for k in flat)
    assert "label" not in flat                          # strings excluded


def test_categorical_fields_are_discovered():
    """
    Wyckoff phase, market regime, session, zone grade and Elliott wave labels
    are STRINGS, so every numeric-only analysis silently skipped them -- and
    they had never been scored against an outcome.
    """
    from ai.component_audit_360 import flatten_categorical

    cats = flatten_categorical({
        "components": {"wyckoff": {"phase": "ACCUMULATION"}},
        "session_analysis": {"session": "LONDON"},
        "entry_analysis": {"discount": {"zone_grade": "A"}},
        "price": 1.2345,
    })
    assert cats["components.wyckoff.phase"] == "ACCUMULATION"
    assert cats["session_analysis.session"] == "LONDON"
    assert cats["entry_analysis.discount.zone_grade"] == "A"


def test_quantile_profile_detects_shape():
    """A U-shaped relationship splits to zero at the median and is invisible."""
    from ai.component_audit_360 import quantile_profile

    rows = []
    for i in range(300):
        value = i / 300.0
        # U: profitable at both extremes, not in the middle
        r = 1.0 if (value < 0.2 or value > 0.8) else -1.0
        rows.append({"r": r, "sign": 1, "features": {"u.field": value},
                     "opened_at": "%04d" % i})
    profile = quantile_profile(rows, "u.field")
    assert profile is not None
    assert profile["u_shaped"] is True
    assert profile["monotonic"] is False


def test_mutual_information_sees_nonlinear_dependence():
    from ai.component_audit_360 import mutual_information

    rows = []
    for i in range(300):
        value = i / 300.0
        r = 1.0 if (value < 0.2 or value > 0.8) else -1.0
        rows.append({"r": r, "sign": 1, "features": {"u.field": value}})
    assert (mutual_information(rows, "u.field") or 0) > 0.1


def test_redundancy_finds_duplicated_measurements():
    """
    Two fields carrying the same information are DOUBLE-COUNTED by the
    probability chain, which adds contributions independently.
    """
    from ai.component_audit_360 import redundancy_clusters

    rng = random.Random(3)
    rows = []
    for i in range(120):
        base = rng.gauss(0, 1)
        rows.append({"r": 0.0, "sign": 1, "features": {
            "a.score": base,
            "b.same_thing": base * 2.0 + 0.001,   # perfectly correlated
            "c.unrelated": rng.gauss(0, 1),
        }})
    clusters = redundancy_clusters(rows, ["a.score", "b.same_thing", "c.unrelated"])
    assert any({"a.score", "b.same_thing"} <= set(c) for c in clusters)
    assert not any("c.unrelated" in c for c in clusters)


def test_audit_self_check_passes():
    from ai.component_audit_360 import self_check
    assert self_check()["ok"] is True


# --------------------------------------------------------------------------
# edge_discovery
# --------------------------------------------------------------------------

def test_edge_discovery_finds_a_planted_edge_and_rejects_noise():
    from ai.edge_discovery import self_check

    report = self_check()
    assert report["checks"]["recovers_planted_edge"] is True
    assert report["checks"]["rejects_pure_noise"] is True
    assert report["ok"] is True


def test_walk_forward_folds_never_train_on_the_future():
    """An expanding window must not let a fold see its own test block."""
    from ai.edge_discovery import walk_forward_folds

    rows = [{"opened_at": "%04d" % i, "r": 0.0} for i in range(200)]
    for train, test in walk_forward_folds(rows, 4):
        assert train and test
        assert max(r["opened_at"] for r in train) < min(r["opened_at"] for r in test)


def test_benjamini_hochberg_controls_false_discoveries():
    from ai.edge_discovery import benjamini_hochberg

    # 100 pure-noise p-values: at alpha=0.10 almost none may survive.
    rng = random.Random(1)
    noise = [rng.random() for _ in range(100)]
    assert sum(benjamini_hochberg(noise, alpha=0.10)) <= 3
    # a genuine effect among noise must still be found
    mixed = [0.00001] + noise
    assert benjamini_hochberg(mixed, alpha=0.10)[0] is True


def test_r_under_exit_never_discards_unresolved_trades():
    """
    Dropping trades that reach neither level is what made an earlier exit
    study report 77.6% win rate -- it silently measured a fifth of the data.
    """
    from ai.edge_discovery import r_under_exit

    row = {"r": 0.3, "path_r": [0.1, 0.2, 0.3]}      # never hits +2R or -1R
    assert r_under_exit(row, 2.0, 1.0) == pytest.approx(0.3)

    hit_target = {"r": 0.0, "path_r": [0.5, 1.2, 2.5]}
    assert r_under_exit(hit_target, 2.0, 1.0) == pytest.approx(2.0)

    hit_stop = {"r": 0.0, "path_r": [-0.4, -1.3]}
    assert r_under_exit(hit_stop, 2.0, 1.0) == pytest.approx(-1.0)


def test_flipping_direction_negates_the_path():
    from ai.edge_discovery import r_under_exit

    row = {"r": 0.0, "path_r": [0.2, 0.6, 1.1]}
    assert r_under_exit(row, 1.0, 1.0, flip=False) == pytest.approx(1.0)
    assert r_under_exit(row, 1.0, 1.0, flip=True) == pytest.approx(-1.0)


# --------------------------------------------------------------------------
# microstructure_features
# --------------------------------------------------------------------------

def test_microstructure_separates_a_trend_from_chop():
    from core.microstructure_features import self_check

    report = self_check()
    for name, passed in report["checks"].items():
        assert passed, "microstructure check failed: %s" % name


def test_microstructure_refuses_thin_data_instead_of_returning_zeros():
    """
    A zeroed feature is indistinguishable from a real reading of zero. The
    live system already had `timing_confidence` falling back to a CONSTANT 50
    on nearly every decision, which looked like a measurement for months.
    """
    from core.microstructure_features import compute

    result = compute([], 0.0001)
    assert result["available"] is False
    assert result.get("reason")
    assert "order_flow_imbalance" not in result


def test_microstructure_bias_is_signed_against_the_trade():
    """
    A component that reports a market read and lets the caller sign it will
    eventually be signed wrong -- `pattern` was inverted on every SELL.
    """
    from core.microstructure_features import directional_bias

    features = {"available": True, "imbalance_short": 0.4,
                "imbalance_long": 0.3, "intensity_acceleration": 1.1,
                "spread_stress": 1.0}
    buy = directional_bias(features, "BUY")
    sell = directional_bias(features, "SELL")

    assert buy["flow_supports_trade"] is True
    assert sell["flow_opposes_trade"] is True
    assert buy["flow_with_trade_short"] == pytest.approx(
        -sell["flow_with_trade_short"])


def test_microstructure_is_not_wired_into_probability_yet():
    """
    It has never been validated against outcomes on this account. Adding an
    unvalidated contributor to the probability chain is how `pattern` came to
    push 12 points the wrong way on 26% of trades.
    """
    from core.microstructure_features import directional_bias, get_status

    assert get_status()["wired_into_probability"] is False
    bias = directional_bias(
        {"available": True, "imbalance_short": 0.9, "imbalance_long": 0.9},
        "BUY")
    assert bias["contribution"] == 0.0


# --------------------------------------------------------------------------
# trade_repository
# --------------------------------------------------------------------------

def test_repository_keeps_outcome_fields_out_of_features():
    from ai.trade_repository import OUTCOME_FIELDS

    assert set(OUTCOME_FIELDS) == {"close_data", "analysis_at_close", "closed_at"}


def test_repository_r_multiple_is_direction_aware():
    from ai.trade_repository import _r_multiple

    long_win = {"direction": "BUY", "entry": {"price": 1.10, "stop_loss": 1.09},
                "close_data": {"close_price": 1.12}}
    short_win = {"direction": "SELL", "entry": {"price": 1.10, "stop_loss": 1.11},
                 "close_data": {"close_price": 1.08}}
    assert _r_multiple(long_win) == pytest.approx(2.0)
    assert _r_multiple(short_win) == pytest.approx(2.0)


def test_repository_r_multiple_refuses_a_zero_stop():
    from ai.trade_repository import _r_multiple

    assert _r_multiple({"direction": "BUY",
                        "entry": {"price": 1.1, "stop_loss": 1.1},
                        "close_data": {"close_price": 1.2}}) is None


# --------------------------------------------------------------------------
# strategy_families
# --------------------------------------------------------------------------

def test_strategy_family_self_check_passes():
    from ai.strategy_families import self_check
    assert self_check()["ok"] is True


def test_components_map_to_the_right_strategy():
    """
    The classification IS the hypothesis. If trend components land in the
    mean-reversion family the whole opposition analysis is meaningless.
    """
    from ai.strategy_families import classify

    assert classify("trend_cascade") == "TREND"
    assert classify("h1_alignment") == "TREND"
    assert classify("exhaustion") == "MEAN_REVERSION"
    assert classify("something_unmapped") is None

    # The coarse STRUCTURE and FLOW families were split into the finer ones
    # below. The opposition analysis is only meaningful at this granularity:
    # an SMC break of structure and a supply/demand zone are separate claims.
    assert classify("smc") == "SMC_STRUCTURE"
    assert classify("nested_zone") == "ZONES"
    assert classify("rvam") == "PARTICIPATION"

    # Longest token wins, so a more specific family is reachable even when a
    # shorter token of another family also matches. Under the old
    # first-match-wins rule "adr_exhaustion" was swallowed by
    # MEAN_REVERSION's "exhaustion" and EXHAUSTION_ADR was unreachable.
    assert classify("adr_exhaustion") == "EXHAUSTION_ADR"

    # PATTERN and ELLIOTT_WAVE are separate families: a chart pattern and an
    # Elliott count are different claims and were split apart. Anything still
    # expecting a single "WAVE" family predates that split.
    assert classify("pattern") == "PATTERN"
    assert classify("elliott") == "ELLIOTT_WAVE"
    assert classify("wave_lattice") == "ELLIOTT_WAVE"


def test_family_scores_are_relative_to_the_traded_direction():
    """
    Ledger deltas are signed against best_direction, which differs from the
    filled direction on ~19% of trades. Reading them in the wrong frame turned
    a +0.49R component edge into an apparent sign error.
    """
    from ai.strategy_families import family_scores

    ledger = [{"step": "trend_cascade", "delta": 10.0},
              {"step": "adr_exhaustion", "delta": -4.0}]
    analysis = {"best_direction": "BUY",
                "final_verdict": {"probability_ledger": ledger}}

    aligned = family_scores({"analysis_at_open": analysis, "direction": "BUY"})
    opposed = family_scores({"analysis_at_open": analysis, "direction": "SELL"})

    assert aligned["TREND"] == pytest.approx(10.0)
    assert opposed["TREND"] == pytest.approx(-10.0), (
        "scores must flip when the filled direction opposes best_direction")


def test_a_family_that_never_spoke_is_absent_not_zero():
    """'Did not contribute' and 'was neutral' are different facts."""
    from ai.strategy_families import family_scores

    scores = family_scores({
        "direction": "BUY",
        "analysis_at_open": {
            "best_direction": "BUY",
            "final_verdict": {"probability_ledger": [
                {"step": "pattern", "delta": 5.0}]}}})
    assert "PATTERN" in scores
    assert "TREND" not in scores


def test_opposition_is_discovered_not_assumed():
    """
    Hardcoding one opposing pair makes every other opposition invisible.
    Measured on real trades, trend/mean-reversion conflict on 91.2% of
    trades -- but other pairs conflict too and must be findable.
    """
    from ai.strategy_families import discover_opposition

    rows = []
    for i in range(120):
        good = 1.0 if i % 2 == 0 else -1.0
        rows.append({"r": good, "opened_at": "%04d" % i, "symbol": "X",
                     "scores": {"A": good * 5, "B": -good * 5, "C": good * 5},
                     "regime": None})
    found = {tuple(sorted(o["pair"])): o for o in discover_opposition(rows, min_both=20)}
    assert found[("A", "B")]["conflict_rate"] == 100.0
    assert found[("A", "C")]["conflict_rate"] == 0.0


def test_the_regime_field_chosen_must_actually_vary():
    """
    A label present on every trade but constant disables the whole regime
    analysis. `final_verdict.market_regime` is "NORMAL" on 213 of 215 trades,
    and picking it by distinct-count silently killed the regime test.
    """
    from ai.strategy_families import _pick_regime_field

    rows = []
    for i in range(100):
        rows.append({"regimes": {
            "constant.field": "NORMAL",
            # three categories but 98% one value -- worse than useless
            "lopsided.field": "A" if i < 98 else ("B" if i == 98 else "C"),
            "balanced.field": "TRENDING" if i % 2 else "RANGING",
        }})
    assert _pick_regime_field(rows) == "balanced.field"


def test_a_constant_regime_field_is_rejected_entirely():
    from ai.strategy_families import _pick_regime_field

    rows = [{"regimes": {"only.field": "NORMAL"}} for _ in range(100)]
    assert _pick_regime_field(rows) is None
