"""
The price-evolution maps, encoder, decoder and bridge against the snapshot
analyze_institutional_signal() produces TODAY.

The fixture is not hand-written: tests/fixtures/asset_analysis_snapshots_2026_09_17.json
holds real payloads captured read-only on 2026-09-17 (the smallest set of the
twelve captures that together contain every field, list and detector block seen).
Hand-written fixtures are how this layer drifted before -- they kept describing
components 1_trend_bias..8_indicators long after the engine stopped producing
them, and every test stayed green while the stored codes read nothing.

"The maps match the snapshot 100%" is asserted as three falsifiable facts:
  1. every path of a live snapshot is placed (field, list or detector block);
  2. every field code names a path a snapshot produces, or a documented branch;
  3. encode -> decode reproduces the snapshot exactly, and the codes alone
     reproduce every mapped scalar exactly.

Set TRADIFY_LIVE_SNAPSHOT=1 (MT5 running) to re-check against a fresh capture.
"""

import json
import os
from pathlib import Path

import pytest

from ai.price_evolution_bridge import PriceEvolutionBridge
from ai.price_evolution_decoder import PriceEvolutionDecoder
from ai.price_evolution_encoder import PriceEvolutionEncoder
from ai.price_evolution_maps import (
    ANALYSIS_GROUPS, COMPACT_CODES, FIELDS, FIELDS_BY_CODE, GROUP_CODES, LIST_PATHS, MISSING,
    NULLABLE_CONTAINERS, OPTIONAL_TEMPLATES, READING_CODES, RESERVED_KEYS, STATE_READINGS,
    STRATEGY_GROUPS, TOP_LEVEL_KEYS, EvolutionMaps)

FIXTURE = Path(__file__).parent / "fixtures" / "asset_analysis_snapshots_2026_09_17.json"
MAPS = EvolutionMaps()


def _snapshots():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshots"]


@pytest.fixture(params=sorted(_snapshots()))
def snapshot(request):
    return _snapshots()[request.param]


def _observed_templates(snapshots):
    seen = set()
    for snap in snapshots:
        for field in FIELDS:
            if MAPS.get_path(snap, field.path) is not MISSING:
                seen.add(field.template)
    return seen


# ---------------------------------------------------------------------------
# 1. every path is placed
# ---------------------------------------------------------------------------

def test_the_fixture_is_the_current_grouped_snapshot(snapshot):
    assert set(snapshot) == set(TOP_LEVEL_KEYS)
    assert MAPS.layout(snapshot) == "grouped"
    assert set(snapshot["analysis"]) == set(ANALYSIS_GROUPS)


def test_every_path_of_a_live_snapshot_is_placed(snapshot):
    report = MAPS.coverage(snapshot)
    assert report["unmapped"] == [], f"paths the maps cannot place: {report['unmapped'][:10]}"
    assert report["removed_sections_present"] == []
    assert report["missing_top_level"] == []
    assert report["matches"] is True
    assert report["fields"] > 400 and report["data_blocks"] > 30


# ---------------------------------------------------------------------------
# 2. no stale codes, no gaps in the registries
# ---------------------------------------------------------------------------

def test_every_code_names_a_path_a_snapshot_produces():
    seen = _observed_templates(_snapshots().values())
    stale = sorted({f.template for f in FIELDS} - seen - set(OPTIONAL_TEMPLATES))
    assert stale == [], f"codes for paths no snapshot produces: {stale}"


def test_optional_branches_are_real_fields():
    templates = {f.template for f in FIELDS}
    assert set(OPTIONAL_TEMPLATES) <= templates


def test_codes_are_unique_and_never_collide_with_blob_keys():
    codes = [f.code for f in FIELDS] + list(NULLABLE_CONTAINERS)
    assert len(codes) == len(set(codes))
    assert not set(codes) & set(RESERVED_KEYS)
    assert len({f.path for f in FIELDS}) == len(FIELDS)


def test_every_group_and_reading_in_core_has_a_code():
    """A group or reading added in core must be named in the maps, loudly."""
    assert set(ANALYSIS_GROUPS) <= set(GROUP_CODES)
    assert set(STRATEGY_GROUPS) <= set(ANALYSIS_GROUPS)
    assert set(STATE_READINGS) <= set(READING_CODES)


def test_every_list_path_exists_in_the_snapshots():
    snaps = list(_snapshots().values())
    for path in LIST_PATHS:
        if path.startswith(("strategy_groups.groups.", "analysis.")):
            continue        # expanded per group; the templates are checked below
        assert any(isinstance(MAPS.get_path(s, tuple(path.split("."))), list) for s in snaps), path


# ---------------------------------------------------------------------------
# 3. exact round trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("compact", [False, True])
def test_encode_decode_reproduces_the_snapshot_exactly(snapshot, compact):
    encoder = PriceEvolutionEncoder()
    blob = encoder.encode(snapshot, compact=compact)
    assert encoder.last_validation["ok"], encoder.last_validation["problems"]
    assert PriceEvolutionDecoder().decode(blob) == snapshot


def test_the_codes_alone_reproduce_every_mapped_scalar(snapshot):
    blob = PriceEvolutionEncoder().encode(snapshot)
    codes_only = {k: v for k, v in blob.items() if k not in ("full_analysis_z", "full_analysis")}
    decoded = PriceEvolutionDecoder().decode(codes_only)

    assert decoded["_decoded_from"] == "field_codes"
    for field in FIELDS:
        value = MAPS.get_path(snapshot, field.path)
        if value is MISSING or isinstance(value, (dict, list)):
            continue
        assert MAPS.get_path(decoded, field.path) == value, ".".join(field.path)
    assert "data" not in (decoded.get("analysis", {}).get("TREND") or {}), \
        "a codes-only decode must not pretend to carry detector blocks"


def test_a_null_runner_up_survives_the_codes():
    snap = next(s for s in _snapshots().values()
                if MAPS.get_path(s, ("entry_analysis", "strategy", "runner_up")) is None)
    blob = PriceEvolutionEncoder().encode(snap)
    codes_only = {k: v for k, v in blob.items() if k != "full_analysis_z"}
    decoded = PriceEvolutionDecoder().decode(codes_only)
    assert MAPS.get_path(decoded, ("entry_analysis", "strategy", "runner_up")) is None


def test_the_compact_point_carries_the_decision_subset_and_stays_small(snapshot):
    blob = PriceEvolutionEncoder().encode(snapshot, compact=True)
    carried = {k for k in blob if k in FIELDS_BY_CODE}
    present = {c for c in COMPACT_CODES
               if MAPS.get_path(snapshot, FIELDS_BY_CODE[c].path) not in (MISSING,)
               and not isinstance(MAPS.get_path(snapshot, FIELDS_BY_CODE[c].path), (dict, list))}
    assert carried == present
    for must in ("fv_pp", "fv_bd", "sg_win", "sg_fp", "dd_td", "vt_tr", "ea_se", "ed_sl"):
        assert must in blob, must
    assert len(json.dumps(blob, ensure_ascii=False)) < 25_000


# ---------------------------------------------------------------------------
# drift is reported, never swallowed
# ---------------------------------------------------------------------------

def test_an_unknown_label_is_kept_verbatim(snapshot):
    snap = json.loads(json.dumps(snapshot))
    snap["final_verdict"]["market_regime"] = "A_REGIME_THE_MAPS_HAVE_NEVER_SEEN"
    blob = PriceEvolutionEncoder().encode(snap, compact=True)
    assert blob["fv_mrg"] == "A_REGIME_THE_MAPS_HAVE_NEVER_SEEN"


def test_a_new_engine_field_is_reported_and_still_stored(snapshot):
    snap = json.loads(json.dumps(snapshot))
    snap["strategy_groups"]["a_field_added_later"] = 7
    blob = PriceEvolutionEncoder().encode(snap, compact=True)
    assert "strategy_groups.a_field_added_later" in blob["unmapped_paths"]
    assert PriceEvolutionDecoder().decode(blob)["strategy_groups"]["a_field_added_later"] == 7


def test_a_flat_or_legacy_payload_is_labelled(analysis):
    report = MAPS.coverage(analysis)
    assert report["layout"] == "flat"
    assert "components" in report["removed_sections_present"]
    assert report["matches"] is False


# ---------------------------------------------------------------------------
# the bridge on a trade stored exactly the way the monitor stores one
# ---------------------------------------------------------------------------

def _stored_trade():
    """monitor/trade_persistence.py shapes: open envelope, compact points, close envelope."""
    snaps = list(_snapshots().values())
    first = snaps[0]
    later = json.loads(json.dumps(first))
    later["final_verdict"]["probability_percent"] = first["final_verdict"]["probability_percent"] - 9.0
    flip = "SELL" if first["final_verdict"]["best_direction"] == "BUY" else "BUY"
    later["final_verdict"]["best_direction"] = flip
    later["vetos"]["triggered"] = True
    later["vetos"]["reason"] = "High spread (50.0p > 40.0)"

    encoder = PriceEvolutionEncoder()
    points = []
    for i, snap in enumerate((first, first, later)):
        points.append({
            "timestamp": f"2026-09-17T03:{i * 3:02d}:00+00:00",
            "price": 100.0 + i, "profit_usd": float(i), "profit_percent": 0.1 * i,
            "distance_from_entry_pips": 3.0 * i, "spread": 1.2, "volume": 0.01,
            "risk_state": {"sl": 99.0, "tp": 102.0, "break_even_applied": False},
            "microstructure": {"available": False, "reason": "fixture"},
            "analysis": {"m1": encoder.encode(snap, compact=True)},
            "_encoded": True, "_audit_schema": 1, "_tf_included": ["m1"],
        })
    return {
        "trade_id": "trade_1", "ticket": 1, "symbol": first["config"]["symbol"],
        "order_type": first["config"]["executed_direction"],
        "direction": first["config"]["executed_direction"], "status": "CLOSED",
        "opened_at": "2026-09-17T03:00:00+00:00", "closed_at": "2026-09-17T03:09:00+00:00",
        "entry": {"price": 100.0, "volume": 0.01, "stop_loss": 99.0, "take_profit": 102.0},
        "analysis_at_open": {
            "timestamp": "2026-09-17T03:00:00+00:00", "m1_analysis_raw": first, "m1_audit": {},
            "_encoded": False, "_audit_schema": 1, "trailing_stop": {"enabled": False},
            "⭐ CONFIDENCE": first["⭐ CONFIDENCE"], "🎯 FINAL_DECISION": first["🎯 FINAL_DECISION"],
        },
        "price_evolution": points,
        "close_data": {"close_reason": "STOP_LOSS", "profit_usd": -4.0, "is_winning": False},
        "analysis_at_close": {"timestamp": "2026-09-17T03:09:00+00:00", "result": "LOSS",
                              "m1_analysis_raw": later},
    }


def test_the_open_snapshot_is_reachable_and_matches_the_maps():
    bridge = PriceEvolutionBridge()
    canonical = bridge.to_canonical(_stored_trade())
    open_analysis = canonical["analysis_at_open"]
    assert open_analysis["final_verdict"]["probability_ledger"]
    assert open_analysis["strategy_groups"]["groups"]

    coverage = bridge.feature_coverage(_stored_trade())
    assert coverage["schema"]["matches"] is True
    assert coverage["schema"]["unmapped_paths"] == []
    for group in STRATEGY_GROUPS:
        assert group in coverage["analysis_groups_with_features"], group


def test_every_stored_point_decodes_to_the_full_snapshot():
    canonical = PriceEvolutionBridge().to_canonical(_stored_trade())
    first = list(_snapshots().values())[0]
    assert canonical["price_evolution"][0]["analysis"]["m1"] == first


def test_decision_record_component_scores_are_the_scored_groups():
    trade = _stored_trade()
    record = PriceEvolutionBridge().to_decision_record(trade)
    groups = trade["analysis_at_open"]["m1_analysis_raw"]["strategy_groups"]["groups"]
    expected = {g: v["score"] for g, v in groups.items() if v.get("scored")}
    assert expected, "fixture has no scored group"
    assert record["component_scores"] == expected


def test_learning_data_follows_the_current_snapshot_through_the_trade():
    trade = _stored_trade()
    data = PriceEvolutionBridge().extract_learning_data(trade["price_evolution"])

    assert data["schema"]["matches"] is True
    probability = data["probability"]["probability_percent"]
    assert probability["count"] == 3 and probability["biggest_drop"]["drop"] == pytest.approx(9.0)
    changes = data["direction"]["changes"]["best_direction"]
    assert len(changes) == 1 and changes[0]["index"] == 2
    first = trade["analysis_at_open"]["m1_analysis_raw"]
    assert data["vetos"]["triggered"]["true"] == 2 * int(bool(first["vetos"]["triggered"])) + 1
    assert data["vetos"]["triggered"]["last"] is True
    assert data["market"]["price"]["count"] == 3
    assert set(data["strategy_groups"]["groups"]) == set(STRATEGY_GROUPS)
    assert set(data["state_readings"]) == set(STATE_READINGS)
    scored = [g for g, v in data["strategy_groups"]["groups"].items() if v["score"]["count"]]
    assert scored, "no group score was tracked across the points"


def test_snapshots_carry_current_features_without_outcomes():
    snapshots = PriceEvolutionBridge().to_snapshots(_stored_trade())
    assert len(snapshots) == 4
    assert "open.strategy_groups.final_probability" in snapshots[0]
    assert "m1.final_verdict.probability_percent" in snapshots[1]
    for snap in snapshots:
        assert not any("profit_usd" in k or "analysis_at_close" in k for k in snap)


# ---------------------------------------------------------------------------
# optional: against a fresh capture from the running engine
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("TRADIFY_LIVE_SNAPSHOT") != "1",
                    reason="set TRADIFY_LIVE_SNAPSHOT=1 with MT5 running")
def test_a_fresh_live_capture_still_matches_the_maps():
    import MetaTrader5 as mt5
    from core.asset_analysis import analyze_institutional_signal

    assert mt5.initialize(), mt5.last_error()
    try:
        live = analyze_institutional_signal(symbol="EURUSD", order_type="AUTO",
                                            fixed_trade_size_usd=200.0, risk_per_trade=0.02,
                                            leverage=200, timeframe="M1")
    finally:
        mt5.shutdown()
    live = MAPS.make_json_safe(live)
    assert live.get("success") is True, live.get("error")
    report = MAPS.coverage(live)
    assert report["matches"], report["unmapped"][:20]
    stale = sorted({f.template for f in FIELDS}
                   - _observed_templates(list(_snapshots().values()) + [live])
                   - set(OPTIONAL_TEMPLATES))
    assert stale == [], stale
