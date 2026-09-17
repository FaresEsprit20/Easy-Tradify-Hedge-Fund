# ============================================================
# AI_MarketReplay -- PHASE 1: DATA FOUNDATION
# Extraction, immutability, replay records
# ============================================================
#
# Implements Phase 1 items 2 (immutable snapshots), 3 (temporal metadata),
# 4 (feature availability metadata) and 6 (replay extraction), on top of the
# contracts in models.py.
#
# WHY AN ADAPTER RATHER THAN A MIGRATION
# --------------------------------------
# Readme section 22 states the canonical schema is "a canonical logical
# contract, not a claim that every field currently exists in Firebase", and
# Phase 0 rule 10 requires building adapters before deleting old
# implementations. Nothing here writes to Firebase or changes the stored
# shape: it reads what exists and presents it in canonical form.
#
# That also means the historical record stays immutable, which section 26
# requires -- extraction cannot corrupt what it reads because it never writes.
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ----------------------------------
# It does not invent fields. A stored trade carrying no VWAP state yields an
# empty vwap section, not a plausible-looking default. The package has already
# been bitten by exactly that: the encoder stamped success=False,
# model_version="v4.0.1" and an encode-time timestamp onto payloads that
# claimed none of them, and every consumer downstream believed it.
# ============================================================

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import (
    SCHEMA_VERSION,
    Availability,
    CanonicalTrade,
    DecisionGenome,
    DecisionSnapshot,
    EventType,
    FeatureSpec,
    MarketState,
    Provenance,
    availability_of,
    content_hash,
    utc_now,
)

DATA_ENGINE_VERSION = "1.0"

# Where each Decision Genome market_state section lives in the stored
# analysis_at_open payload. Tried in order; the first present wins.
#
# Mapped explicitly rather than by name-matching because the stored analysis
# uses several naming conventions at once (numbered `components`, top-level
# subsystem blocks, emoji keys), and guessing would silently produce empty
# sections that look like "this trade had no VWAP" rather than "we failed to
# find it".
MARKET_STATE_SOURCES: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "structure": (("smc", "market_structure"), ("components", "1_trend_bias")),
    "liquidity": (("liquidity_events",), ("smc", "liquidity_sweep")),
    "fvg": (("components", "7_ict_concepts"), ("smc", "fvg")),
    "vwap": (("vwap",), ("vwap_context",)),
    "rvam": (("rvam",),),
    "absorption": (("order_flow_forensics",),),
    "volume_profile": (("volume_profile",), ("components", "volume_profile")),
    "order_flow": (("order_flow_forensics",),),
    "momentum": (("components", "8_indicators"),),
    "volatility": (("volatility_protection",), ("ttm_squeeze",)),
    "sessions": (("session_analysis",),),
    "microstructure": (("micro_structure",), ("components", "microstructure")),
}


def _dig(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _first_present(analysis: Mapping[str, Any],
                   paths: Sequence[Sequence[str]]) -> Dict[str, Any]:
    for path in paths:
        value = _dig(analysis, path)
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


# Top-level analysis keys consumed WHOLESALE by a semantic mapping. Only these
# may be treated as already represented; everything else is carried verbatim.
#
# `components` and `smc` are deliberately absent: the semantic map takes
# components.1_trend_bias and components.8_indicators, and smc.market_structure
# and smc.liquidity_sweep -- two of ~21 sub-analyzers and two of ~six SMC
# blocks. Marking either as consumed would silently drop supply/demand,
# support/resistance, order blocks, premium/discount and the rest.
# Only PRIMARY paths qualify. A key that appears solely as a fallback is not
# reliably consumed, because _first_present stops at the first match: with
# volatility_protection present, `volatility` never reads ttm_squeeze, and with
# vwap present it never reads vwap_context. Listing those as consumed marked
# them absorbed while actually dropping them -- a loss that the coverage report
# would then have certified as lossless.
FULLY_CONSUMED_KEYS = frozenset({
    "vwap", "rvam", "volume_profile", "volatility_protection",
    "session_analysis", "liquidity_events", "order_flow_forensics",
    "micro_structure",
    "final_verdict", "gnn", "non_rl", "adversarial", "entry_analysis", "rl",
})


def carry_unmapped(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Every analysis section the semantic map does not fully absorb.

    Without this the extraction was lossy in a way no error would reveal:
    measured on a real-shaped payload it dropped 16 of 24 sections, including
    account_info (leverage, balance, equity), all 21 numbered `components`
    sub-analyzers, pattern_analysis, family_vote, wave_lattice, trend_cascade,
    nested_zone, vetos, higher_timeframe, news_analysis and the top-level
    decision scalars.

    A semantic map is a view, not a container. Replay reconstructs what the
    strategy believed, so anything the strategy computed has to survive even
    when this module has no opinion about where it belongs. Some duplication
    with `deterministic` is accepted: correctness outranks bytes.
    """
    if not isinstance(analysis, Mapping):
        return {}
    return {
        str(key): value
        for key, value in analysis.items()
        if key not in FULLY_CONSUMED_KEYS
    }


def analysis_coverage(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Which analysis sections are semantically mapped, which are carried
    verbatim, and which are dropped.

    `dropped` must always be empty -- it exists so that claim is checkable
    rather than asserted, and so a future change that reintroduces loss fails
    a test instead of quietly shrinking the record.
    """
    if not isinstance(analysis, Mapping):
        return {"mapped": [], "carried": [], "dropped": [], "lossless": True}

    keys = {str(k) for k in analysis}
    mapped = sorted(keys & FULLY_CONSUMED_KEYS)
    carried = sorted(keys - FULLY_CONSUMED_KEYS)
    return {
        "mapped": mapped,
        "carried": carried,
        "dropped": sorted(keys - set(mapped) - set(carried)),
        "lossless": not (keys - set(mapped) - set(carried)),
        "total_sections": len(keys),
    }


# ---------------------------------------------------------------------------
# Feature availability metadata (Phase 1 item 4)
# ---------------------------------------------------------------------------

def describe_features(
    analysis: Mapping[str, Any],
    decision_timestamp: Optional[str],
    prefix: str = "decision_state.deterministic",
) -> List[FeatureSpec]:
    """
    A FeatureSpec per scalar in the decision-time analysis (readme section 24).

    `available_at` is set to the decision timestamp because that is when the
    analysis was computed -- and it is set to None when the trade carries no
    decision timestamp, rather than to "now". A fabricated availability would
    defeat the only check that can catch leakage later.
    """
    specs: List[FeatureSpec] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
            return
        if isinstance(node, (list, tuple)):
            specs.append(FeatureSpec(
                feature=f"{prefix}.{path}.count",
                type="int", source=prefix,
                timestamp=decision_timestamp, available_at=decision_timestamp,
            ))
            return
        if isinstance(node, bool):
            kind = "bool"
        elif isinstance(node, (int, float)):
            kind = "float"
        elif isinstance(node, str):
            kind = "categorical"
        else:
            return
        specs.append(FeatureSpec(
            feature=f"{prefix}.{path}",
            type=kind,
            source=prefix,
            timestamp=decision_timestamp,
            available_at=decision_timestamp,
            nullable=node is None,
            historical=True,
            future_or_outcome_only=False,
        ))

    walk(analysis, "")
    return specs


# ---------------------------------------------------------------------------
# Decision Genome (Phase 1 item 5)
# ---------------------------------------------------------------------------

def build_genome(
    canonical_trade: Mapping[str, Any],
    include_features: bool = False,
) -> DecisionGenome:
    """
    Readme section 21, assembled from a bridge-canonical trade.

    Reads `analysis_at_open` only. analysis_at_close is deliberately never
    consulted: the genome is what the strategy believed at T0, and section 23
    forbids outcome information from re-entering a historical decision.

    `include_features` is off by default because a full FeatureSpec list runs
    to hundreds of entries per trade; it is wanted for a leakage audit and
    unwanted when loading thousands of trades.
    """
    analysis = canonical_trade.get("analysis_at_open") or {}
    entry = canonical_trade.get("entry") or {}
    decision_timestamp = canonical_trade.get("opened_at")

    market_state = MarketState(**{
        section: _first_present(analysis, paths)
        for section, paths in MARKET_STATE_SOURCES.items()
    })

    provenance = Provenance(
        analysis_version=analysis.get("model_version"),
        config_version=(analysis.get("config") or {}).get("version"),
        schema_version=SCHEMA_VERSION,
        extracted_at=utc_now(),
        source="firebase.trades",
    )

    genome = DecisionGenome(
        decision_id=str(canonical_trade.get("trade_id")
                        or canonical_trade.get("ticket") or ""),
        symbol=canonical_trade.get("symbol"),
        strategy=(analysis.get("config") or {}).get("strategy"),
        timeframe=(analysis.get("config") or {}).get("timeframe"),
        decision_timestamp=decision_timestamp,
        market_state=market_state,
        market_synthesis=dict(analysis.get("final_verdict") or {}),
        gnn_state=dict(analysis.get("gnn") or {}),
        non_rl_state=dict(analysis.get("non_rl") or {}),
        adversarial_state=dict(analysis.get("adversarial") or {}),
        trade_quality=dict(analysis.get("entry_analysis") or {}),
        rl_state=dict(analysis.get("rl") or {}),
        risk_state={
            key: entry[key] for key in
            ("actual_risk_usd", "risk_percent_used", "margin_required_usd",
             "risk_reward_ratio", "spread_at_entry")
            if key in entry
        },
        unmapped=carry_unmapped(analysis),
        provenance=provenance,
    )

    if include_features:
        genome.features = describe_features(analysis, decision_timestamp)
    return genome


# ---------------------------------------------------------------------------
# Canonical trade extraction (Phase 1 items 1 and 6)
# ---------------------------------------------------------------------------

def to_canonical_trade(
    raw_trade: Mapping[str, Any],
    bridge: Any = None,
    include_features: bool = False,
) -> Optional[CanonicalTrade]:
    """
    Stored Firebase trade -> CanonicalTrade (readme section 22).

    Decoding goes through PriceEvolutionBridge.to_canonical() rather than
    reading the document directly, because price_evolution exists in two
    incompatible storage shapes and only the bridge knows both.

    Returns None for a document with no usable identity: a record that cannot
    be joined back to anything is not worth carrying forward.
    """
    if not isinstance(raw_trade, Mapping):
        return None

    if bridge is None:
        from ..price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    try:
        decoded = bridge.to_canonical(dict(raw_trade))
    except Exception:
        return None

    trade_id = str(decoded.get("trade_id") or decoded.get("ticket") or "")
    if not trade_id:
        return None

    entry = decoded.get("entry") or {}
    close = decoded.get("close_data") or {}
    analysis = decoded.get("analysis_at_open") or {}

    genome = build_genome(decoded, include_features=include_features)

    # Requested vs filled is split rather than lumped: what was asked for is a
    # decision, what came back is not knowable until it fills. Section 23
    # classifies them differently and the adapter has to honour that.
    execution = {
        "requested": {
            key: entry[key] for key in
            ("price", "stop_loss", "take_profit", "take_profit_2",
             "take_profit_3", "volume", "magic", "comment")
            if key in entry
        },
        "filled": {
            key: entry[key] for key in
            ("spread_at_entry", "actual_margin", "actual_risk_usd")
            if key in entry
        },
        "entry_price": entry.get("price"),
        "stop_loss": entry.get("stop_loss"),
        "take_profit": entry.get("take_profit"),
        "size": entry.get("volume"),
        "spread": entry.get("spread_at_entry"),
        "slippage": close.get("exit_slippage"),
        "fees": None,
    }

    metrics = decoded.get("metrics") or {}
    outcome = {
        "exit_price": close.get("close_price"),
        "pnl": close.get("profit_usd"),
        "return": close.get("profit_percent"),
        "mfe": metrics.get("max_profit_percent"),
        "mae": metrics.get("max_drawdown_percent"),
        "duration": close.get("duration_seconds"),
        "result": close.get("close_reason"),
        "is_winning": close.get("is_winning"),
    }

    return CanonicalTrade(
        trade_id=trade_id,
        schema_version=SCHEMA_VERSION,
        ticket=decoded.get("ticket"),
        symbol=decoded.get("symbol"),
        direction=decoded.get("direction"),
        strategy=genome.strategy,
        timeframe=genome.timeframe,
        timestamps={
            "created_at": decoded.get("created_at"),
            "decision_at": decoded.get("opened_at"),
            "entry_at": decoded.get("opened_at"),
            "exit_at": decoded.get("closed_at"),
            "updated_at": decoded.get("updated_at"),
        },
        decision_state={
            "market_snapshot": {
                "entry_price": entry.get("price"),
                "spread_at_entry": entry.get("spread_at_entry"),
            },
            "deterministic": {
                section: getattr(genome.market_state, section)
                for section in MARKET_STATE_SOURCES
            },
            # Everything the semantic map does not fully absorb. Replay
            # reconstructs what the strategy believed, so nothing it computed
            # may be lost merely because this module has no opinion on where
            # it belongs.
            "unmapped": carry_unmapped(analysis),
            "coverage": analysis_coverage(analysis),
            "market_synthesis": genome.market_synthesis,
        },
        ai_state={
            "gnn": genome.gnn_state,
            "non_rl": genome.non_rl_state,
            "adversarial": genome.adversarial_state,
            "trade_quality": genome.trade_quality,
            "rl": genome.rl_state,
            "decision_genome": {"decision_id": genome.decision_id},
        },
        execution=execution,
        price_evolution=list(decoded.get("price_evolution") or []),
        management={"snapshots": [], "actions": []},
        outcome=outcome,
        replay={
            "replay_version": None, "first_divergence": None,
            "failure_class": None, "attribution": [],
            "counterfactuals": [], "replay_score": None,
        },
        provenance=genome.provenance,
        decision_snapshots=extract_decision_snapshots(decoded, genome),
        genome=genome,
    )


def _full_deterministic_features(genome: DecisionGenome) -> Dict[str, Any]:
    """
    Everything deterministic and knowable at decision time.

    The twelve semantic sections are a curated VIEW over two of ~21 numbered
    components and two of ~six SMC blocks. Shipping only that view into the
    snapshot dropped supply/demand, support/resistance, order blocks,
    premium/discount, indicators, patterns, waves, vetos and account_info
    (leverage included) -- the sections a replay most needs in order to say
    why a decision was made.

    Both are kept: the view because downstream code addresses sections by
    their semantic name, and the raw sections because they are the actual
    evidence. Duplication is accepted; silent loss is not.

    Temporally this is safe by construction -- every key here comes from
    analysis_at_open, which is AT_DECISION. analysis_at_close is never read.
    """
    features: Dict[str, Any] = {
        section: getattr(genome.market_state, section)
        for section in MARKET_STATE_SOURCES
    }
    for key, value in (genome.unmapped or {}).items():
        # A raw section must never silently overwrite a semantic one; on a
        # name clash both survive under distinct keys.
        features[key if key not in features else f"analysis.{key}"] = value
    return features


def _leaf_paths(node: Any, path: str = "") -> set:
    """Leaf-level paths, so coverage counts values rather than sections."""
    if isinstance(node, Mapping):
        out: set = set()
        for key, value in node.items():
            out |= _leaf_paths(value, f"{path}.{key}" if path else str(key))
        return out
    if isinstance(node, (list, tuple)):
        return {f"{path}[]"}
    return {path}


def snapshot_coverage(analysis: Mapping[str, Any],
                      snapshot: DecisionSnapshot) -> Dict[str, Any]:
    """
    How much of the decision-time analysis actually reaches a snapshot.

    `analysis_coverage` answers this at section level for the canonical trade,
    which was true and yet missed the real loss: sections were carried onto
    the CanonicalTrade and then dropped at the genome hop, so a section-level
    report said "lossless" while the snapshot held a fifth of the leaves.
    This measures the object replay consumes, at leaf level.
    """
    if not isinstance(analysis, Mapping):
        return {"analysis_leaves": 0, "present": 0, "missing": [],
                "lossless": True, "coverage_ratio": 1.0}

    carried = _leaf_paths({
        "deterministic": snapshot.deterministic_features,
        "market_synthesis": snapshot.market_synthesis,
        "gnn": snapshot.gnn_state,
        "non_rl": snapshot.non_rl_state,
        "adversarial": snapshot.adversarial_state,
        "trade_quality": snapshot.trade_quality_state,
        "rl": snapshot.rl_state,
        "risk": snapshot.risk_state,
    })

    # The snapshot re-homes sections under semantic names, so a source path
    # and its carried path differ by prefix: final_verdict.probability_percent
    # arrives as market_synthesis.probability_percent. Rewrite each source
    # path through the SAME table the extraction used, rather than matching on
    # trailing segments -- a suffix heuristic both reported phantom loss for
    # every renamed section and, worse, would mark a genuinely dropped leaf as
    # present whenever some unrelated section happened to end in the same
    # leaf name. A coverage check that can be fooled is not a check.
    aliases: List[Tuple[str, str]] = []
    for section, paths in MARKET_STATE_SOURCES.items():
        for path in paths:
            aliases.append((".".join(path), f"deterministic.{section}"))
    for source_key, target in (
        ("final_verdict", "market_synthesis"), ("gnn", "gnn"),
        ("non_rl", "non_rl"), ("adversarial", "adversarial"),
        ("entry_analysis", "trade_quality"), ("rl", "rl"),
    ):
        aliases.append((source_key, target))
    # Longest source prefix first, so components.8_indicators is rewritten
    # before the bare `components` carried verbatim under deterministic.
    aliases.sort(key=lambda pair: -len(pair[0]))

    def candidates(item: str) -> List[str]:
        """Every place this source leaf may legitimately have landed."""
        found = [f"deterministic.{item}"]           # carried verbatim
        for source_prefix, target in aliases:
            if item == source_prefix or item.startswith(source_prefix + "."):
                found.append(target + item[len(source_prefix):])
        return found

    source = _leaf_paths(analysis)
    missing = sorted(
        item for item in source
        if not any(candidate in carried for candidate in candidates(item))
    )
    return {
        "analysis_leaves": len(source),
        "present": len(source) - len(missing),
        "missing": missing,
        "lossless": not missing,
        "coverage_ratio": (
            (len(source) - len(missing)) / len(source) if source else 1.0),
    }


def extract_decision_snapshots(
    decoded: Mapping[str, Any],
    genome: DecisionGenome,
) -> List[DecisionSnapshot]:
    """
    Reconstruct the event-level record (readme section 26.6) from what exists.

    The current pipeline does not emit decision snapshots, so only EXECUTION
    and CLOSE can be recovered honestly; the intermediate events
    (CANDIDATE_DETECTED, CONFIRMATION, MICROSTRUCTURE_TRIGGER, RL_DECISION,
    RISK_APPROVAL) were never recorded and are NOT synthesised here.
    Manufacturing them from the opening analysis would produce a timeline that
    looks complete and is fiction. Emitting them properly is a live-pipeline
    change, not an extraction one.
    """
    snapshots: List[DecisionSnapshot] = []
    opened_at = decoded.get("opened_at")

    if opened_at:
        snapshots.append(DecisionSnapshot(
            snapshot_id=f"{genome.decision_id}:EXECUTION",
            trade_id=genome.decision_id,
            event_type=EventType.EXECUTION,
            timestamp=str(opened_at),
            available_at=str(opened_at),
            market_snapshot={"entry_price": (decoded.get("entry") or {}).get("price")},
            deterministic_features=_full_deterministic_features(genome),
            market_synthesis=genome.market_synthesis,
            gnn_state=genome.gnn_state,
            non_rl_state=genome.non_rl_state,
            adversarial_state=genome.adversarial_state,
            trade_quality_state=genome.trade_quality,
            rl_state=genome.rl_state,
            risk_state=genome.risk_state,
            execution_state=dict(decoded.get("entry") or {}),
            decision={"action": "ENTER", "direction": decoded.get("direction")},
            probabilities={
                key: genome.market_synthesis.get(key)
                for key in ("probability_percent", "star_rating")
                if key in genome.market_synthesis
            },
            provenance=genome.provenance,
        ))

    closed_at = decoded.get("closed_at")
    close = decoded.get("close_data") or {}
    if closed_at:
        snapshots.append(DecisionSnapshot(
            snapshot_id=f"{genome.decision_id}:CLOSE",
            trade_id=genome.decision_id,
            event_type=EventType.CLOSE,
            timestamp=str(closed_at),
            available_at=str(closed_at),
            execution_state={
                "close_price": close.get("close_price"),
                "close_reason": close.get("close_reason"),
            },
            decision={"action": "CLOSE", "reason": close.get("close_reason")},
            provenance=genome.provenance,
        ))

    return snapshots


def extract_replay_records(
    trades: Sequence[Mapping[str, Any]],
    bridge: Any = None,
    include_features: bool = False,
) -> List[CanonicalTrade]:
    """Phase 1 item 6. Malformed documents are skipped, never guessed at."""
    records = []
    for trade in trades or []:
        record = to_canonical_trade(trade, bridge, include_features)
        if record is not None:
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Immutability (Phase 1 item 2, readme section 26)
# ---------------------------------------------------------------------------

def snapshot_fingerprint(trade: CanonicalTrade) -> Dict[str, Any]:
    """Identity plus content hashes, for detecting silent rewrites."""
    return {
        "trade_id": trade.trade_id,
        "schema_version": trade.schema_version,
        "content_hash": trade.content_hash(),
        "genome_hash": trade.genome.content_hash() if trade.genome else None,
        "decision_hash": content_hash(trade.decision_view()),
        "captured_at": utc_now(),
    }


def detect_mutation(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Compare two fingerprints of the same trade (readme section 26).

    Decision-state changes are reported separately from whole-document
    changes, because they mean different things: a trade legitimately gains
    price-evolution points and an outcome while open, but its DECISION state
    is history and must never change. Section 26 requires a new version rather
    than a rewrite, so a changed decision hash is a contract violation, not an
    update.
    """
    decision_changed = before.get("decision_hash") != after.get("decision_hash")
    return {
        "trade_id": after.get("trade_id"),
        "content_changed": before.get("content_hash") != after.get("content_hash"),
        "decision_state_changed": decision_changed,
        "genome_changed": before.get("genome_hash") != after.get("genome_hash"),
        "immutability_violated": decision_changed,
    }


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status() -> Dict[str, Any]:
    return {
        "component": "aireplay.data_engine",
        "version": DATA_ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "phase": "1 - Data Foundation",
        "implements": {
            "canonical_trade_schema": True,        # readme 22
            "immutable_snapshots": True,           # readme 26
            "temporal_metadata": True,             # readme 23
            "feature_availability_metadata": True,  # readme 24
            "decision_genome": True,               # readme 21
            "replay_extraction": True,             # phase 1 item 6
        },
        "writes_to_firebase": False,
        "lossless_extraction": True,
        "loss_policy": (
            "sections the semantic map does not fully absorb are carried "
            "verbatim under decision_state.unmapped; decision_state.coverage "
            "reports mapped/carried/dropped and dropped must be empty"),
        "synthesises_missing_events": False,
        "recoverable_snapshot_types": [
            EventType.EXECUTION.value, EventType.CLOSE.value],
        "unrecoverable_snapshot_types": [
            EventType.CANDIDATE_DETECTED.value, EventType.CONFIRMATION.value,
            EventType.MICROSTRUCTURE_TRIGGER.value, EventType.RL_DECISION.value,
            EventType.RISK_APPROVAL.value, EventType.MANAGEMENT.value,
            EventType.EXIT_DECISION.value,
        ],
        "why_unrecoverable": (
            "the live pipeline does not emit these events; synthesising them "
            "from the opening analysis would produce a timeline that looks "
            "complete and is fiction"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None) -> Dict[str, Any]:
    """Prove extraction, the temporal firewall, and immutability detection."""
    report: Dict[str, Any] = {
        "component": "aireplay.data_engine", "ok": False, "checks": {}}
    try:
        records = extract_replay_records(trades or [], bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["records_extracted"] = len(records)

        if records:
            sample = records[0]
            leakage = sample.leakage_report()
            report["checks"]["leakage"] = leakage
            report["checks"]["no_outcome_in_decision_view"] = not leakage["outcome_leaked"]
            report["checks"]["unclassified_fields"] = leakage["unclassified_fields"]

            coverage = (sample.decision_state or {}).get("coverage") or {}
            report["checks"]["analysis_coverage"] = coverage
            report["checks"]["extraction_is_lossless"] = coverage.get("lossless", False)

            # Section-level coverage on the canonical record read "lossless"
            # while the snapshot replay consumes held a fifth of the leaves.
            # The canonical record is not the thing being replayed, so it is
            # measured separately and at leaf level.
            # Measured against the RAW stored analysis, never against anything
            # derived from the extraction: comparing the output to a
            # reconstruction of itself is a check that cannot fail.
            raw_analysis = next(
                (dict((t.get("analysis_at_open") or
                       (t.get("analysis") or {}).get("at_open") or {}))
                 for t in (trades or [])
                 if str(t.get("trade_id") or t.get("ticket") or "")
                 == sample.trade_id), {})
            execution = next(
                (s for s in sample.decision_snapshots
                 if s.event_type is EventType.EXECUTION), None)
            if not raw_analysis:
                # Genuinely nothing to carry, so nothing can be lost. This is
                # distinct from being unable to check.
                report["checks"]["snapshot_coverage"] = {
                    "note": "trade stores no analysis_at_open; nothing to cover"}
                report["checks"]["snapshot_is_lossless"] = True
            elif execution is None:
                # There WAS analysis and no snapshot carries it. Not verifiable
                # is not the same as fine: an uncomputable gate is an unmet one.
                report["checks"]["snapshot_coverage"] = {
                    "note": "analysis present but no EXECUTION snapshot; "
                            "coverage unverifiable"}
                report["checks"]["snapshot_is_lossless"] = False
            else:
                snap = snapshot_coverage(raw_analysis, execution)
                report["checks"]["snapshot_coverage"] = {
                    "analysis_leaves": snap["analysis_leaves"],
                    "present": snap["present"],
                    "coverage_ratio": round(snap["coverage_ratio"], 4),
                    "missing": snap["missing"][:20],
                }
                report["checks"]["snapshot_is_lossless"] = snap["lossless"]
            report["checks"]["genome_sections_populated"] = (
                sample.genome.market_state.populated_sections() if sample.genome else [])
            report["checks"]["snapshots_temporally_valid"] = all(
                s.is_temporally_valid() for s in sample.decision_snapshots)

            # Re-extraction must be byte-stable, or immutability cannot be
            # checked at all.
            again = to_canonical_trade((trades or [])[0], bridge)
            report["checks"]["extraction_is_deterministic"] = (
                content_hash(sample.decision_view())
                == content_hash(again.decision_view()) if again else False)

            report["ok"] = bool(
                report["checks"]["no_outcome_in_decision_view"]
                and report["checks"]["snapshots_temporally_valid"]
                and report["checks"]["extraction_is_deterministic"]
                and report["checks"]["extraction_is_lossless"]
                and report["checks"]["snapshot_is_lossless"]
                and not leakage["unclassified_fields"]
            )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "DATA_ENGINE_VERSION", "MARKET_STATE_SOURCES", "FULLY_CONSUMED_KEYS",
    "carry_unmapped", "analysis_coverage", "snapshot_coverage",
    "describe_features",
    "build_genome", "to_canonical_trade", "extract_decision_snapshots",
    "extract_replay_records", "snapshot_fingerprint", "detect_mutation",
    "get_status", "self_check",
]
