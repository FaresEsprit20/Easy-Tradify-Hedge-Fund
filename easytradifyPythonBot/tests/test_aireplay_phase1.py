"""
AI_MarketReplay Phase 1 -- Data Foundation.

Covers the six items in the readme's section 60 Phase 1 list, against the
contracts in sections 21-26.6. The load-bearing tests are the temporal
firewall (section 23) and immutability detection (section 26): both fail
silently in production if wrong, and both make results look better rather
than worse when they leak.
"""

import pytest

from ai.aireplay import (
    SCHEMA_VERSION,
    Availability,
    CanonicalTrade,
    DecisionGenome,
    DecisionSnapshot,
    EventType,
    FeatureSpec,
    availability_of,
    build_genome,
    content_hash,
    describe_features,
    detect_mutation,
    extract_replay_records,
    get_status,
    self_check,
    snapshot_fingerprint,
    to_canonical_trade,
)
from ai.aireplay.models import FIELD_AVAILABILITY, strip_volatile

from conftest import build_trade


# ---------------------------------------------------------------------------
# Item 1 -- canonical trade schema (readme 22)
# ---------------------------------------------------------------------------

def test_extracts_the_canonical_sections(trade):
    record = to_canonical_trade(trade)
    assert isinstance(record, CanonicalTrade)
    assert record.schema_version == SCHEMA_VERSION
    for section in ("timestamps", "decision_state", "ai_state", "execution",
                    "management", "outcome", "replay"):
        assert hasattr(record, section)


def test_identity_is_preserved(trade):
    record = to_canonical_trade(trade)
    assert record.trade_id == "555"
    assert record.ticket == 555
    assert record.symbol == "EURUSD"
    assert record.direction == "BUY"


def test_requested_and_filled_execution_are_separated(trade):
    """
    Section 23 classes them differently: what was asked for is a decision,
    what came back is not knowable until it fills.
    """
    execution = to_canonical_trade(trade).execution
    assert execution["requested"]["price"] == 1.0850
    assert "spread_at_entry" in execution["filled"]


def test_documents_without_identity_are_refused():
    orphan = build_trade()
    orphan.pop("trade_id")
    orphan.pop("ticket")
    assert to_canonical_trade(orphan) is None


def test_malformed_documents_do_not_abort_extraction(trades):
    records = extract_replay_records([None, "junk", {"x": 1}] + list(trades))
    assert len(records) == len(trades)


def test_extraction_never_writes(trade):
    """Section 26: the historical record must not be mutated by reading it."""
    import copy
    before = copy.deepcopy(trade)
    to_canonical_trade(trade)
    assert trade == before


# ---------------------------------------------------------------------------
# Whole-snapshot coverage
#
# Regression: the semantic map absorbed 12 sections and silently discarded
# everything else -- measured at 16 of 24 sections lost, including
# account_info (leverage), all 21 numbered `components` sub-analyzers,
# pattern_analysis, family_vote, wave_lattice, vetos and the decision scalars.
# Nothing errored; the record was simply smaller than the truth.
# ---------------------------------------------------------------------------

def _contains_key(node, key):
    """Structural search, immune to JSON escaping of emoji keys."""
    if isinstance(node, dict):
        return key in node or any(_contains_key(v, key) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_contains_key(v, key) for v in node)
    return False


def test_extraction_loses_no_analysis_leaf(trade):
    """Every scalar in analysis_at_open must survive somewhere."""
    from ai.price_evolution_bridge import _flatten

    record = to_canonical_trade(trade)
    region = {"decision_state": record.decision_state, "ai_state": record.ai_state}

    source = _flatten(trade["analysis_at_open"])
    leaves = [k for k in source
              if not k.endswith((".count", ".sum", ".mean", ".min", ".max"))]
    tails = {k.split(".")[-1] for k in _flatten(region)}
    lost = [k for k in leaves if k.split(".")[-1] not in tails]

    assert not lost, f"analysis content dropped by extraction: {lost[:10]}"


def test_coverage_reports_no_dropped_sections(trade):
    coverage = to_canonical_trade(trade).decision_state["coverage"]
    assert coverage["dropped"] == []
    assert coverage["lossless"] is True
    assert coverage["total_sections"] == len(trade["analysis_at_open"])


def test_unmapped_sections_are_carried_verbatim(trade):
    """The sections the semantic map has no opinion about must still be here."""
    record = to_canonical_trade(trade)
    unmapped = record.decision_state["unmapped"]
    for section in ("account_info", "components", "pattern_analysis",
                    "family_vote", "wave_lattice", "vetos", "trend_cascade",
                    "nested_zone", "higher_timeframe", "news_analysis", "config"):
        assert section in unmapped, section


def test_every_component_sub_analyzer_survives(trade):
    """
    `components` holds ~21 numbered sub-analyzers and the semantic map reads
    two of them. Marking the whole key consumed would drop the other 19.
    """
    record = to_canonical_trade(trade)
    region = {"decision_state": record.decision_state}
    for component in trade["analysis_at_open"]["components"]:
        assert _contains_key(region, component), component


def test_leverage_survives(trade):
    record = to_canonical_trade(trade)
    assert _contains_key({"d": record.decision_state}, "leverage")


def test_fallback_only_sources_are_not_marked_consumed():
    """
    Regression: ttm_squeeze and vwap_context were listed as fully consumed,
    but they are FALLBACK paths -- _first_present stops at the first match, so
    with volatility_protection and vwap present they were never read. The
    coverage report certified a lossy extraction as lossless.
    """
    from ai.aireplay.data_engine import FULLY_CONSUMED_KEYS
    assert "ttm_squeeze" not in FULLY_CONSUMED_KEYS
    assert "vwap_context" not in FULLY_CONSUMED_KEYS


def test_renamed_sections_keep_their_content(trade):
    """A section moved to a semantic name must still carry its payload."""
    record = to_canonical_trade(trade)
    region = {"decision_state": record.decision_state}
    for probe in ("sweep_count", "stop_hunt_detected", "session",
                  "atr_pips", "probability_ledger"):
        assert _contains_key(region, probe), probe


def test_self_check_asserts_losslessness(trades):
    report = self_check(trades)
    assert report["checks"]["extraction_is_lossless"] is True
    assert report["checks"]["analysis_coverage"]["dropped"] == []


# ---------------------------------------------------------------------------
# Item 3 -- temporal metadata (readme 23)
# ---------------------------------------------------------------------------

def test_decision_view_excludes_outcome(trade):
    view = to_canonical_trade(trade).decision_view()
    assert "outcome" not in view
    assert "replay" not in view
    assert "price_evolution" not in view
    assert "decision_state" in view


def test_leakage_report_is_clean(trade):
    report = to_canonical_trade(trade).leakage_report()
    assert report["outcome_leaked"] == []
    assert report["unclassified_fields"] == []
    assert "outcome" in report["withheld_fields"]


def test_unregistered_fields_fail_closed():
    """
    A field nobody classified must become unavailable, not silently trusted.
    Forgetting to register something is the likely mistake; failing open would
    make that mistake invisible.
    """
    assert availability_of("a_field_nobody_registered") is Availability.UNCLASSIFIED


def test_every_registered_section_has_a_temporal_class(trade):
    record = to_canonical_trade(trade)
    for name in record.to_dict():
        if name in ("decision_snapshots", "genome", "execution"):
            continue
        assert name in FIELD_AVAILABILITY, f"{name} has no temporal class"


def test_outcome_view_is_the_complement(trade):
    record = to_canonical_trade(trade)
    assert set(record.outcome_view()) == {"outcome", "replay"}
    assert not set(record.outcome_view()) & set(record.decision_view())


# ---------------------------------------------------------------------------
# Item 4 -- feature availability metadata (readme 24)
# ---------------------------------------------------------------------------

def test_feature_specs_carry_the_contract_fields(trade):
    genome = build_genome(trade, include_features=True)
    assert genome.features
    spec = genome.features[0]
    for attribute in ("feature", "type", "source", "available_at",
                      "future_or_outcome_only", "version"):
        assert hasattr(spec, attribute)


def test_available_at_is_the_decision_time_not_now(trade):
    """
    A fabricated availability defeats the only check that can catch leakage.
    """
    genome = build_genome(trade, include_features=True)
    assert all(s.available_at == trade["opened_at"] for s in genome.features)


def test_missing_decision_time_yields_no_fabricated_availability():
    undated = build_trade()
    undated.pop("opened_at")
    specs = describe_features(undated["analysis_at_open"], None)
    assert specs and all(s.available_at is None for s in specs)


def test_feature_usability_respects_the_decision_timestamp():
    spec = FeatureSpec(feature="x", type="float", source="s",
                       available_at="2026-09-01T10:00:00Z")
    assert spec.is_usable_at("2026-09-01T10:05:00Z") is True
    assert spec.is_usable_at("2026-09-01T09:55:00Z") is False


def test_outcome_only_features_are_never_usable():
    spec = FeatureSpec(feature="pnl", type="float", source="outcome",
                       available_at="2026-09-01T09:00:00Z",
                       future_or_outcome_only=True)
    assert spec.is_usable_at("2026-09-01T10:00:00Z") is False


# ---------------------------------------------------------------------------
# Item 5 -- Decision Genome (readme 21)
# ---------------------------------------------------------------------------

def test_genome_populates_market_state_from_stored_analysis(trade):
    genome = build_genome(trade)
    populated = genome.market_state.populated_sections()
    for section in ("structure", "vwap", "rvam", "volume_profile",
                    "momentum", "sessions", "volatility"):
        assert section in populated, section


def test_absent_sections_stay_empty_rather_than_invented():
    sparse = build_trade()
    sparse["analysis_at_open"] = {"final_verdict": {"probability_percent": 60}}
    genome = build_genome(sparse)
    assert genome.market_state.vwap == {}
    assert genome.market_state.populated_sections() == []


def test_genome_never_reads_analysis_at_close(trade):
    """The genome is what was believed at T0. Outcome must not re-enter it."""
    poisoned = build_trade()
    poisoned["analysis_at_close"] = {"result": "WIN", "secret": "leaked"}
    genome = build_genome(poisoned)
    assert "leaked" not in str(genome.to_dict())


def test_genome_provenance_does_not_fabricate_versions():
    sparse = build_trade()
    sparse["analysis_at_open"] = {}
    provenance = build_genome(sparse).provenance
    assert provenance.analysis_version is None
    assert provenance.config_version is None


def test_genome_hash_is_content_addressed(trade):
    a = build_genome(trade)
    b = build_genome(build_trade(ticket=555))
    assert a.content_hash() == b.content_hash()


# ---------------------------------------------------------------------------
# Item 2 -- immutable snapshots (readme 26)
# ---------------------------------------------------------------------------

def test_reextraction_is_stable(trade):
    """
    Regression: `extracted_at` sat inside the hashed provenance, so every
    extraction of an unchanged trade produced a new hash and the immutability
    check reported a violation on every record.
    """
    first = snapshot_fingerprint(to_canonical_trade(trade))
    second = snapshot_fingerprint(to_canonical_trade(build_trade(ticket=555)))
    assert detect_mutation(first, second)["immutability_violated"] is False


def test_new_evolution_points_are_a_legal_update():
    """A trade legitimately gains evolution while open; its decision does not."""
    before = snapshot_fingerprint(to_canonical_trade(build_trade(points=3)))
    after = snapshot_fingerprint(to_canonical_trade(build_trade(points=6)))
    mutation = detect_mutation(before, after)
    assert mutation["decision_state_changed"] is False
    assert mutation["immutability_violated"] is False


def test_rewriting_the_decision_is_a_violation():
    """Section 26 requires a new version, never a rewrite of history."""
    before = snapshot_fingerprint(to_canonical_trade(build_trade()))
    rewritten = build_trade()
    rewritten["analysis_at_open"]["final_verdict"]["probability_percent"] = 99.0
    after = snapshot_fingerprint(to_canonical_trade(rewritten))

    mutation = detect_mutation(before, after)
    assert mutation["decision_state_changed"] is True
    assert mutation["immutability_violated"] is True


def test_volatile_metadata_is_stripped_before_hashing():
    payload = {"a": 1, "extracted_at": "2026-01-01", "n": {"extracted_at": "x", "b": 2}}
    assert strip_volatile(payload) == {"a": 1, "n": {"b": 2}}


def test_hash_ignores_key_order():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


# ---------------------------------------------------------------------------
# Decision snapshots (readme 26.6)
# ---------------------------------------------------------------------------

def test_recovers_execution_and_close_events(trade):
    events = [s.event_type for s in to_canonical_trade(trade).decision_snapshots]
    assert EventType.EXECUTION in events
    assert EventType.CLOSE in events


def test_snapshots_are_temporally_valid(trade):
    """Contents must not postdate the snapshot they are attached to."""
    for snapshot in to_canonical_trade(trade).decision_snapshots:
        assert snapshot.is_temporally_valid()


def test_unrecorded_events_are_not_synthesised(trade):
    """
    The live pipeline emits no CANDIDATE_DETECTED / CONFIRMATION / RL_DECISION
    events. Manufacturing them from the opening analysis would produce a
    timeline that looks complete and is fiction.
    """
    events = {s.event_type for s in to_canonical_trade(trade).decision_snapshots}
    for absent in (EventType.CANDIDATE_DETECTED, EventType.CONFIRMATION,
                   EventType.MICROSTRUCTURE_TRIGGER, EventType.RL_DECISION,
                   EventType.RISK_APPROVAL):
        assert absent not in events


def test_close_snapshot_is_omitted_without_a_close_time():
    open_trade = build_trade()
    open_trade.pop("closed_at")
    events = {s.event_type for s in to_canonical_trade(open_trade).decision_snapshots}
    assert EventType.CLOSE not in events


# ---------------------------------------------------------------------------
# Item 6 -- replay extraction, and the verification surface
# ---------------------------------------------------------------------------

def test_extracts_a_record_per_trade(trades):
    assert len(extract_replay_records(trades)) == len(trades)


def test_status_declares_what_it_cannot_recover():
    status = get_status()
    assert status["phase"] == "1 - Data Foundation"
    assert status["writes_to_firebase"] is False
    assert status["synthesises_missing_events"] is False
    assert all(status["implements"].values())
    assert EventType.RL_DECISION.value in status["unrecoverable_snapshot_types"]


def test_self_check_passes_on_real_shaped_trades(trades):
    report = self_check(trades)
    assert report["ok"] is True
    assert report["checks"]["no_outcome_in_decision_view"] is True
    assert report["checks"]["snapshots_temporally_valid"] is True
    assert report["checks"]["extraction_is_deterministic"] is True
    assert report["checks"]["unclassified_fields"] == []


def test_self_check_reports_failure_rather_than_raising():
    report = self_check([{"garbage": True}])
    assert report["ok"] is False
    assert report["checks"]["records_extracted"] == 0


# ---------------------------------------------------------------------------
# Snapshot coverage (the genome hop)
#
# analysis_coverage certified extraction "lossless" and was right at SECTION
# level on the CanonicalTrade -- while the EXECUTION snapshot that replay
# actually consumes carried 20 of 75 measured analysis leaves. The sections
# were rescued onto the canonical record and then dropped at the
# genome->snapshot hop, because DecisionGenome had no field for them.
# Nothing raised; the section-level report kept saying lossless.
# These tests measure the object replay consumes, at leaf level.
# ---------------------------------------------------------------------------

from ai.aireplay.data_engine import snapshot_coverage, to_canonical_trade


def _execution_snapshot(analysis):
    trade = {
        "trade_id": "COV1", "symbol": "EURUSD", "direction": "BUY",
        "status": "CLOSED", "opened_at": "2026-01-01T10:00:00+00:00",
        "closed_at": "2026-01-01T12:00:00+00:00",
        "entry": {"price": 1.1, "actual_risk_usd": 50.0},
        "close_data": {"close_price": 1.11, "close_reason": "TP"},
        "analysis_at_open": analysis,
    }
    canonical = to_canonical_trade(trade)
    return canonical, next(s for s in canonical.decision_snapshots
                           if s.event_type is EventType.EXECUTION)


def test_execution_snapshot_carries_every_analysis_leaf(analysis):
    _, snapshot = _execution_snapshot(analysis)
    coverage = snapshot_coverage(analysis, snapshot)
    assert coverage["lossless"], f"dropped from snapshot: {coverage['missing']}"
    assert coverage["present"] == coverage["analysis_leaves"]


def test_snapshot_coverage_detects_loss(analysis):
    """A coverage check that cannot fail proves nothing."""
    _, snapshot = _execution_snapshot(analysis)
    snapshot.deterministic_features.pop("account_info", None)
    coverage = snapshot_coverage(analysis, snapshot)
    assert not coverage["lossless"]
    assert any(item.startswith("account_info") for item in coverage["missing"])


def test_snapshot_carries_leverage_and_component_analyzers(analysis):
    """The sections named as non-negotiable: leverage, components, SMC."""
    _, snapshot = _execution_snapshot(analysis)
    features = snapshot.deterministic_features
    assert features["account_info"]["leverage"] == analysis["account_info"]["leverage"]
    assert features["components"] == analysis["components"]
    assert features["smc"] == analysis["smc"]
    for section in ("pattern_analysis", "wave_lattice", "vetos"):
        assert features[section] == analysis[section]


def test_snapshot_carries_every_subsystem_state(analysis):
    """Declared-but-unpopulated fields are silent loss, not absence."""
    enriched = dict(analysis)
    enriched["non_rl"] = {"consensus": 0.71}
    enriched["adversarial"] = {"survived": True}
    enriched["rl"] = {"action": "ENTER"}
    enriched["entry_analysis"] = {"grade": "A"}
    _, snapshot = _execution_snapshot(enriched)
    assert snapshot.non_rl_state == {"consensus": 0.71}
    assert snapshot.adversarial_state == {"survived": True}
    assert snapshot.rl_state == {"action": "ENTER"}
    assert snapshot.trade_quality_state == {"grade": "A"}
    assert snapshot_coverage(enriched, snapshot)["lossless"]


def test_genome_carries_unmapped_sections(analysis):
    """The hop where the loss happened."""
    canonical, _ = _execution_snapshot(analysis)
    genome = build_genome({"trade_id": "COV1", "analysis_at_open": analysis,
                           "entry": {}, "opened_at": "2026-01-01T10:00:00+00:00"})
    assert genome.unmapped, "genome dropped every unmapped section"
    assert "account_info" in genome.unmapped
    assert "components" in genome.unmapped
    assert canonical.decision_state["unmapped"].keys() == genome.unmapped.keys()


def test_semantic_sections_are_not_overwritten_by_raw(analysis):
    """Both views survive; a raw section never clobbers a semantic one."""
    _, snapshot = _execution_snapshot(analysis)
    features = snapshot.deterministic_features
    for section in ("structure", "momentum", "volatility", "sessions"):
        assert section in features
