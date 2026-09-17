"""
PriceEvolutionBridge: the decode boundary and whole-trade feature extraction.

Every test here corresponds to a defect that was actually found in this
pipeline, not a hypothetical one.
"""

from ai.price_evolution_bridge import PriceEvolutionBridge, _flatten
from ai.price_evolution_decoder import PriceEvolutionDecoder
from ai.price_evolution_encoder import PriceEvolutionEncoder

from conftest import CONFIDENCE, TAKE_PROFIT_1, build_analysis, build_trade


# ---------------------------------------------------------------------------
# Storage round-trip
# ---------------------------------------------------------------------------

def test_encoder_decoder_roundtrip_is_lossless_for_every_subsystem(analysis):
    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))

    for section in ("smc", "volume_profile", "wave_lattice", "components",
                    "pattern_analysis", "vwap", "rvam", "liquidity_events",
                    "order_flow_forensics", "family_vote", "account_info"):
        assert decoded.get(section) == analysis[section], f"{section} lost in round-trip"


def test_roundtrip_preserves_scalar_formatting(analysis):
    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert decoded[CONFIDENCE] == analysis[CONFIDENCE]


# ---------------------------------------------------------------------------
# to_canonical - both storage shapes
# ---------------------------------------------------------------------------

def test_decodes_encoded_rows(bridge):
    canonical = bridge.to_canonical(build_trade(encoded=True))
    m1 = canonical["price_evolution"][0]["analysis"]["m1"]
    assert m1[CONFIDENCE] == "60%"
    assert m1["components"]["1_trend_bias"]["trend"] == "BULLISH"


def test_normalizes_legacy_raw_rows(bridge):
    """Rows written while the encoder import was broken use different keys."""
    canonical = bridge.to_canonical(build_trade(encoded=False))
    point = canonical["price_evolution"][0]
    assert set(point["analysis"]) == {"m1", "m5", "h1"}
    assert point["analysis"]["m1"][CONFIDENCE] == "60%"


# The one legitimate difference between the shapes: an encoded row knows when
# it was encoded. It is named for what it is, so nothing can mistake it for the
# decision timestamp -- unlike the phantom fields this replaced.
ENCODED_ONLY = {"encoded_at"}


def test_both_storage_shapes_decode_to_the_same_analysis(bridge):
    """
    Regression: the encoder stamped model_version="v4.0.1", success=False and
    timestamp=encode-time onto payloads containing none of them, so a decoded
    row was a superset of the raw row. Storage format must not change content.
    """
    enc = bridge.to_canonical(build_trade(encoded=True))["price_evolution"][0]
    raw = bridge.to_canonical(build_trade(encoded=False))["price_evolution"][0]

    enc_analysis = {k: v for k, v in enc["analysis"]["m1"].items()
                    if k not in ENCODED_ONLY}
    assert enc_analysis == raw["analysis"]["m1"]


def test_encoded_rows_add_nothing_but_labelled_provenance(bridge):
    """No field may appear on decode that the source analysis did not contain."""
    enc = bridge.to_canonical(build_trade(encoded=True))["price_evolution"][0]
    raw = bridge.to_canonical(build_trade(encoded=False))["price_evolution"][0]

    extra = set(enc["analysis"]["m1"]) - set(raw["analysis"]["m1"])
    assert extra == ENCODED_ONLY, f"phantom fields reappeared: {extra - ENCODED_ONLY}"
    for phantom in ("success", "model_version", "timestamp"):
        assert phantom not in enc["analysis"]["m1"]


def test_absent_success_flag_is_not_invented(bridge):
    """
    analyze_institutional_signal() only sets `success` on its error path, so
    defaulting it to False labelled every healthy decision as failed -- and a
    consumer filtering on it would have discarded the entire dataset.
    """
    analysis = build_analysis()
    assert "success" not in analysis

    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert "success" not in decoded


def test_real_success_flag_is_preserved(bridge):
    """Not inventing the field must not mean dropping a real one."""
    for value in (True, False):
        analysis = build_analysis()
        analysis["success"] = value
        decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
        assert decoded["success"] is value


def test_encode_time_is_never_passed_off_as_decision_time(bridge):
    """
    A price_evolution point is written minutes to hours after the decision it
    describes, so encode time masquerading as `timestamp` is not a rounding
    error -- it is the wrong moment entirely.
    """
    analysis = build_analysis()
    assert "timestamp" not in analysis

    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert "timestamp" not in decoded
    assert "encoded_at" in decoded, "encode time should be labelled, not discarded"


def test_real_timestamp_is_preserved(bridge):
    analysis = build_analysis()
    analysis["timestamp"] = "2026-09-01T10:00:00Z"
    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert decoded["timestamp"] == "2026-09-01T10:00:00Z"


def test_model_version_is_not_fabricated(bridge):
    analysis = build_analysis()
    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert "model_version" not in decoded

    analysis["model_version"] = "v9.1"
    decoded = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    assert decoded["model_version"] == "v9.1"


def test_to_canonical_is_idempotent(bridge, trade):
    """
    Regression: a canonical point carries no _encoded flag, so a second pass
    fell through to the raw branch, found no *_analysis_raw keys and blanked
    the analysis it had already decoded.
    """
    once = bridge.to_canonical(trade)
    twice = bridge.to_canonical(once)
    assert twice["price_evolution"][0]["analysis"] == once["price_evolution"][0]["analysis"]
    assert twice["price_evolution"][0]["analysis"]["m1"] != {}


def test_to_canonical_does_not_mutate_input(bridge, trade):
    before = trade["price_evolution"][0]["analysis"]["m1"].copy()
    bridge.to_canonical(trade)
    assert trade["price_evolution"][0]["analysis"]["m1"] == before


def test_analysis_at_open_is_left_alone(bridge, trade):
    """It is already stored raw; decoding it again would be wrong."""
    assert bridge.to_canonical(trade)["analysis_at_open"] == trade["analysis_at_open"]


def test_handles_malformed_input(bridge):
    assert bridge.to_canonical(None) == {}
    assert bridge.to_canonical({"ticket": 9}) == {"ticket": 9}
    assert bridge.to_canonical({"price_evolution": "not-a-list"})["price_evolution"] == "not-a-list"


def test_corrupt_blob_does_not_abort_the_trade(bridge):
    trade = build_trade()
    trade["price_evolution"][0]["analysis"]["m1"] = {"garbage": object()}
    canonical = bridge.to_canonical(trade)
    assert canonical["price_evolution"][0]["analysis"]["m5"][CONFIDENCE] == "60%"


# ---------------------------------------------------------------------------
# Feature extraction - 360 degree coverage
# ---------------------------------------------------------------------------

SUBSYSTEMS = ("account_info", "components", "smc", "volume_profile", "wave_lattice",
              "pattern_analysis", "vwap", "rvam", "liquidity_events",
              "order_flow_forensics", "family_vote", "ttm_squeeze", "trend_cascade",
              "nested_zone", "session_analysis", "news_analysis",
              "volatility_protection", "final_verdict", "vetos",
              "higher_timeframe", "config")


def test_every_subsystem_produces_features(bridge, trade):
    produced = bridge.feature_coverage(trade)["sections_with_features"]
    missing = [s for s in SUBSYSTEMS if s not in produced]
    assert not missing, f"analysis subsystems contributing nothing: {missing}"


def test_indicators_are_extracted_individually(bridge, trade):
    observation = bridge.to_decision_record(trade)["observation"]
    for indicator in ("rsi", "macd", "bollinger", "stochastic"):
        assert any(f"8_indicators.{indicator}" in k for k in observation), indicator


def test_leverage_and_account_state_survive(bridge, trade):
    observation = bridge.to_decision_record(trade)["observation"]
    assert observation["open.account_info.leverage"] == 200
    assert observation["open.account_info.balance"] == 5000.0


def test_lists_are_expanded_not_just_counted(bridge, trade):
    """
    Regression: lists were collapsed to `<name>.count`, discarding the
    probability ledger, SMC reasons and the pattern list wholesale.
    """
    observation = bridge.to_decision_record(trade)["observation"]
    steps = [k for k in observation if "probability_ledger" in k and k.endswith(".step")]
    assert len(steps) == 14, f"expected all 14 ledger steps, got {len(steps)}"
    assert any("smc.reasons.0" in k for k in observation)
    assert any("patterns.0.name" in k for k in observation)


def test_take_profit_levels_are_kept(bridge, trade):
    """
    Regression: the outcome filter matched the substring "profit", which also
    removed take_profit / TAKE_PROFIT_n -- targets chosen at T0, not outcomes.
    """
    observation = bridge.to_decision_record(trade)["observation"]
    assert any(TAKE_PROFIT_1 in k for k in observation)
    assert observation["entry.take_profit"] == 1.0890


def test_evolution_point_volume_block_is_captured(bridge, trade):
    snapshot = bridge.to_snapshots(trade)[1]
    for field in ("tick_volume", "avg_volume", "volume_ratio", "volume_spike"):
        assert f"point.volume.{field}" in snapshot, field


def test_no_unexplained_information_loss(bridge, trade):
    """
    Every leaf of the stored trade must be represented in the extracted
    features, except deliberately withheld outcome fields.
    """
    record = bridge.to_decision_record(trade)
    snapshots = bridge.to_snapshots(trade)
    produced = set(record["observation"]) | {k for s in snapshots for k in s}

    source = _flatten({
        "analysis_at_open": trade["analysis_at_open"],
        "entry": trade["entry"],
        "point": {k: v for k, v in trade["price_evolution"][0].items() if k != "analysis"},
    })
    leaves = [k for k in source
              if not k.endswith((".count", ".sum", ".mean", ".min", ".max"))]

    def represented(leaf):
        tail = leaf.split(".")[-1]
        return any(tail in feature for feature in produced)

    withheld = tuple(bridge._OUTCOME_TOKENS)
    unexplained = [
        leaf for leaf in leaves
        if not represented(leaf) and not any(t in leaf.lower() for t in withheld)
    ]
    assert not unexplained, f"information lost with no reason: {unexplained[:10]}"


def test_long_strings_are_truncated_not_dropped(bridge):
    trade = build_trade()
    trade["analysis_at_open"]["full_raw_analysis"] = "x" * 5000
    observation = bridge.to_decision_record(trade)["observation"]
    assert observation["open.full_raw_analysis.len"] == 5000.0
    assert len(observation["open.full_raw_analysis"]) == 200


def test_nulls_are_recorded_rather_than_vanishing(bridge):
    trade = build_trade()
    trade["analysis_at_open"]["vwap"]["slope"] = None
    observation = bridge.to_decision_record(trade)["observation"]
    assert observation["open.vwap.slope.is_null"] is True


# ---------------------------------------------------------------------------
# Leakage firewall
# ---------------------------------------------------------------------------

def test_close_side_data_never_becomes_a_feature(bridge, trade):
    record = bridge.to_decision_record(trade)
    snapshots = bridge.to_snapshots(trade)
    everything = set(record["observation"]) | {k for s in snapshots for k in s}

    banned = ("close_data", "analysis_at_close", "is_winning", "profit_percent",
              "profit_usd", "close_reason", "duration_seconds", "realized_return")
    leaked = [k for k in everything if any(b in k.lower() for b in banned)]
    assert not leaked, f"outcome data leaked into features: {leaked}"


def test_snapshots_carry_no_realized_profit(bridge, trade):
    """RL derives return by walking price itself; handing it profit is the answer."""
    for snapshot in bridge.to_snapshots(trade):
        assert not any("profit_usd" in k or "profit_percent" in k for k in snapshot)


# ---------------------------------------------------------------------------
# Outcome labels
# ---------------------------------------------------------------------------

def test_outcome_labels_a_winning_trade(bridge):
    outcome = PriceEvolutionBridge().to_outcome(build_trade(winning=True))
    assert outcome["success"] == 1
    assert outcome["tp_hit"] == 1 and outcome["sl_hit"] == 0
    assert outcome["time_to_tp"] == 420.0 and outcome["time_to_sl"] is None


def test_outcome_labels_a_losing_trade(bridge):
    outcome = bridge.to_outcome(build_trade(winning=False))
    assert outcome["success"] == 0
    assert outcome["sl_hit"] == 1 and outcome["tp_hit"] == 0
    assert outcome["realized_return"] == -0.9


def test_mfe_and_mae_come_from_the_evolution_series(bridge):
    """
    metrics{} is maintained incrementally and only ever moves one way; the
    series is the primary record, so it wins when both are present.
    """
    trade = build_trade(points=4)
    trade["price_evolution"][1]["profit_percent"] = 5.5
    trade["price_evolution"][2]["profit_percent"] = -2.25
    trade["metrics"] = {"max_profit_percent": 0.1, "max_drawdown_percent": 0.0}
    outcome = bridge.to_outcome(trade)
    assert outcome["mfe"] == 5.5
    assert outcome["mae"] == -2.25


def test_decision_record_shape(bridge, trade):
    record = bridge.to_decision_record(trade)
    assert set(record) == {"decision_id", "timestamp", "observation",
                           "outcome", "component_scores", "metadata"}
    assert record["decision_id"] == "555"
    # The strategy-group scores the decision used; an unscored group (WAVE) has
    # no score and must not be given one. The deleted `components` section no
    # longer contributes.
    assert record["component_scores"] == {"TREND": 75.0, "MOMENTUM": 41.9}
    assert record["metadata"]["evolution_points"] == 3
