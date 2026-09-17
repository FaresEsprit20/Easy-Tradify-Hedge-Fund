# ============================================================
# ROOT CAUSE ADAPTER -- STORED TRADE -> EVIDENCE INPUT
# ============================================================
#
# WHY THIS EXISTS
# ---------------
# RootCauseAnalyzer.analyze() consumes an already-canonical evidence bundle:
# decision_snapshots, market_synthesis, gnn, non_rl, rl, trade_quality,
# execution, outcome, replay, counterfactuals. Nothing built that bundle.
#
# Fed a stored Firebase trade directly it produced, measured on a real-shaped
# fixture: 0 component evidence, no diagnosis, 0 recommendations, and the
# report "No Replay artifact was supplied." The analyzer was behaving
# correctly -- it refuses to invent a cause it cannot evidence -- but nothing
# was ever going to supply that evidence, so the whole subsystem was inert.
#
# ai/aireplay/ already produces every artifact it wants. This connects them
# rather than reimplementing either side (standard 10).
#
# SHAPE TRANSLATION IS THE WHOLE JOB
# ----------------------------------
# The two sides disagree about container types, and silently:
#   * aireplay returns `divergences` as a DICT keyed by kind
#     (first_anomaly, first_prediction_error, ...); root cause reads it with
#     _list(), which yields the KEY STRINGS for a dict, and _to_divergence
#     then rejects every one of them because a str is not a Mapping.
#   * aireplay returns `attribution` as a DICT holding failure_class and
#     responsible_component_candidates; root cause expects a LIST of
#     attribution records and reads failure_class from the replay top level.
# Both mismatches fail silently and produce an empty, confident-looking
# analysis. They are translated here, explicitly.
#
# WHAT THIS DOES NOT DO
# ---------------------
# It does not compute a cause, score a component, or fill a gap with a
# plausible default. Every field it emits is copied from an artifact another
# module produced. If replay could not reconstruct a path, the bundle says so
# and the analyzer reports UNPROVEN rather than guessing.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

ADAPTER_VERSION = "1.0"


def _snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    """
    An aireplay DecisionSnapshot as the analyzer's DecisionSnapshot mapping.

    The two classes share a name and disagree on nearly every field name.
    aireplay emits `deterministic_features`, `event_type`, `gnn_state`,
    `non_rl_state`, `rl_state`, `trade_quality_state`, `execution_state`; the
    analyzer reads `deterministic`, `phase`, `gnn`, `non_rl`, `rl`,
    `trade_quality`, `execution`. Passing one to the other therefore yields a
    snapshot whose every subsystem field is empty -- which is exactly what
    happened: component evidence came back 0 for every trade, and the analysis
    still rendered a full report.

    Renaming a field on either side would break its own callers, so the
    translation lives here. That is what an adapter is for.
    """
    payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
    event_type = payload.get("event_type")
    event_type = getattr(event_type, "value", event_type)

    return {
        "snapshot_id": payload.get("snapshot_id"),
        "trade_id": payload.get("trade_id"),
        "timestamp": payload.get("timestamp"),
        # The analyzer calls this `phase`; aireplay calls it `event_type`.
        "phase": event_type,
        "event_type": event_type,
        "decision": (payload.get("decision") or {}).get("action"),
        "decision_reason": dict(payload.get("decision") or {}),
        "market_synthesis": dict(payload.get("market_synthesis") or {}),
        "deterministic": dict(payload.get("deterministic_features") or {}),
        "gnn": dict(payload.get("gnn_state") or {}),
        "non_rl": dict(payload.get("non_rl_state") or {}),
        "adversarial": dict(payload.get("adversarial_state") or {}),
        "trade_quality": dict(payload.get("trade_quality_state") or {}),
        "rl": dict(payload.get("rl_state") or {}),
        "risk_gate": dict(payload.get("risk_state") or {}),
        "execution": dict(payload.get("execution_state") or {}),
        "probabilities": dict(payload.get("probabilities") or {}),
        "provenance": dict(payload.get("provenance") or {}),
    }


def _divergences_to_list(divergences: Any) -> List[Dict[str, Any]]:
    """
    aireplay's dict-of-kinds -> the analyzer's list of divergence records.

    Reading the dict directly gives its keys, which are strings, which the
    analyzer discards one by one without a word. The kind is preserved as
    `category` so the translation loses nothing.
    """
    if isinstance(divergences, Sequence) and not isinstance(divergences, (str, bytes)):
        return [dict(item) for item in divergences if isinstance(item, Mapping)]
    if not isinstance(divergences, Mapping):
        return []

    # `earliest` is a POINTER to whichever of the four fired first, not a
    # fifth divergence. Emitting it as a record double-counts the same event
    # and inflates "5 divergences were recorded" when four occurred -- a
    # narrative built on that count would be quietly wrong about how much
    # went wrong.
    alias_keys = {"earliest", "first", "first_divergence"}

    records: List[Dict[str, Any]] = []
    for kind, value in divergences.items():
        if not isinstance(value, Mapping) or str(kind) in alias_keys:
            continue
        record = dict(value)
        record.setdefault("divergence_id", str(kind))
        record.setdefault("category", str(record.get("kind") or kind))
        record.setdefault("source", "aireplay.replay_engine")
        records.append(record)

    # Ordered by when they happened, so "the first divergence" means the
    # earliest one rather than whichever the dict happened to yield first.
    records.sort(key=lambda item: (
        item.get("index") if isinstance(item.get("index"), int) else 10 ** 9))
    return records


def _attribution_to_list(attribution: Any) -> List[Dict[str, Any]]:
    """
    aireplay's attribution block -> the analyzer's list of attributions.

    `responsible_component_candidates` is deliberately the field name on the
    replay side: replay reports CANDIDATES, not causes. That wording survives
    the translation -- causal_status stays UNPROVEN unless a counterfactual
    established otherwise, because a component being present at a failure is
    not evidence that it caused one.
    """
    if isinstance(attribution, Sequence) and not isinstance(attribution, (str, bytes)):
        return [dict(item) for item in attribution if isinstance(item, Mapping)]
    if not isinstance(attribution, Mapping):
        return []

    records: List[Dict[str, Any]] = []
    for candidate in attribution.get("responsible_component_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        records.append({
            "target": candidate.get("component") or candidate.get("target") or "",
            # CONTRIBUTING, never PRIMARY. Replay reports components that
            # were PRESENT at a failure; presence is not causation, and
            # PRIMARY would assert a finding no counterfactual has
            # established. "COMPONENT" is not a member of AttributionType, so
            # it silently degraded to UNKNOWN and threw the distinction away.
            "attribution_type": candidate.get(
                "attribution_type", "CONTRIBUTING"),
            "role": candidate.get("role", "CANDIDATE"),
            "explanation": candidate.get("reason") or candidate.get("explanation") or "",
            "confidence": candidate.get("confidence"),
            "causal_status": candidate.get("causal_status", "UNPROVEN"),
            "evidence": candidate.get("evidence") or [],
        })
    return records


def to_analysis_input(trade: Mapping[str, Any], bridge: Any = None,
                      include_counterfactuals: bool = True) -> Dict[str, Any]:
    """
    A stored Firebase trade -> the evidence bundle RootCauseAnalyzer reads.

    Everything is sourced from aireplay artifacts. A trade that cannot be
    canonicalised returns a bundle that says exactly that, rather than an
    empty one that reads like "we looked and found nothing wrong".
    """
    from .aireplay import counterfactual as counterfactual_module
    from .aireplay import replay_trade
    from .aireplay.data_engine import to_canonical_trade

    canonical = to_canonical_trade(trade, bridge)
    if canonical is None:
        return {
            "trade_id": trade.get("trade_id") or trade.get("ticket"),
            "symbol": trade.get("symbol"),
            "adapter_version": ADAPTER_VERSION,
            "unusable": "trade could not be canonicalised; no evidence extracted",
        }

    genome = canonical.genome
    bundle: Dict[str, Any] = {
        "trade_id": canonical.trade_id,
        "symbol": canonical.symbol,
        "adapter_version": ADAPTER_VERSION,
        "decision_snapshots": [
            _snapshot_payload(s) for s in canonical.decision_snapshots],
        "market_synthesis": dict(genome.market_synthesis) if genome else {},
        "gnn": dict(genome.gnn_state) if genome else {},
        "non_rl": dict(genome.non_rl_state) if genome else {},
        "adversarial": dict(genome.adversarial_state) if genome else {},
        "rl": dict(genome.rl_state) if genome else {},
        "trade_quality": dict(genome.trade_quality) if genome else {},
        "risk_gate": dict(genome.risk_state) if genome else {},
        # The full decision-time snapshot, so a diagnosis can cite SMC,
        # volume profile, S/R, patterns, indicators, session or leverage
        # rather than only the subsystem summaries.
        "deterministic": dict(genome.unmapped) if genome else {},
        "execution": dict(canonical.execution or {}),
        "outcome": dict(canonical.outcome or {}),
        "close_data": dict(canonical.outcome or {}),
        "provenance": (genome.provenance.__dict__.copy()
                       if genome and genome.provenance else {}),
    }

    try:
        replay = replay_trade(canonical)
    except Exception as exc:
        bundle["replay"] = {
            "replay_version": None,
            "unavailable": type(exc).__name__ + ": " + str(exc),
        }
        return bundle

    divergences = _divergences_to_list(replay.get("divergences"))
    attribution_block = replay.get("attribution") or {}
    bundle["replay"] = {
        "replay_version": replay.get("replay_version"),
        "divergences": divergences,
        "first_divergence": divergences[0] if divergences else None,
        "attribution": _attribution_to_list(attribution_block),
        "failure_class": (attribution_block.get("failure_class")
                          if isinstance(attribution_block, Mapping) else None),
        "provenance": {
            "event_stream_hash": replay.get("event_stream_hash"),
            "events": replay.get("events"),
            "replayed_at": replay.get("replayed_at"),
        },
    }
    bundle["reality"] = replay.get("reality")

    if include_counterfactuals:
        branches = counterfactual_module.branch_trade(canonical)
        bundle["replay"]["counterfactuals"] = [
            {
                "scenario_id": branch.get("name"),
                "action": branch.get("action"),
                "parameters": branch.get("params") or {},
                "return": branch.get("realized_r"),
                "result": branch.get("exit_reason"),
                # Every branch is walked over the SAME recorded prices, so it
                # is historical truth rather than a simulation of a market
                # that never happened.
                "is_historical_truth": bool(
                    branches.get("uses_only_historical_prices")),
                "simulator_version": branches.get("version"),
                "implementable": branch.get("implementable"),
            }
            for branch in branches.get("branches") or []
        ]
        bundle["replay"]["counterfactual_comparison"] = branches.get("comparison")

    return bundle


def analyze_trade(trade: Mapping[str, Any], bridge: Any = None,
                  analyzer: Any = None, include_counterfactuals: bool = True):
    """A stored trade straight to a RootCauseAnalysisResult."""
    from .root_cause_analyzers import RootCauseAnalyzer

    bundle = to_analysis_input(trade, bridge, include_counterfactuals)
    return (analyzer or RootCauseAnalyzer()).analyze(bundle)


def analyze_trades(trades: Sequence[Mapping[str, Any]], bridge: Any = None,
                   analyzer: Any = None) -> List[Any]:
    """Batch form; malformed trades are skipped, never guessed at."""
    from .root_cause_analyzers import RootCauseAnalyzer

    shared = analyzer or RootCauseAnalyzer()
    results = []
    for trade in trades or []:
        try:
            results.append(analyze_trade(trade, bridge, shared))
        except Exception:
            continue
    return results


def coverage(trade: Mapping[str, Any], bridge: Any = None) -> Dict[str, Any]:
    """
    Which evidence sections the bundle actually carries for one trade.

    Exists so "full data coverage" is a measurement rather than a claim: an
    empty section here means the stored trade had nothing in it, and that is
    visible instead of being indistinguishable from a section this adapter
    forgot to map.
    """
    bundle = to_analysis_input(trade, bridge)
    sections = ("decision_snapshots", "market_synthesis", "gnn", "non_rl",
                "adversarial", "rl", "trade_quality", "risk_gate",
                "deterministic", "execution", "outcome")
    populated = {name: bool(bundle.get(name)) for name in sections}
    replay = bundle.get("replay") or {}
    return {
        "adapter_version": ADAPTER_VERSION,
        "sections": populated,
        "sections_populated": sum(1 for value in populated.values() if value),
        "sections_total": len(sections),
        "replay_available": bool(replay.get("replay_version")),
        "divergences": len(replay.get("divergences") or []),
        "attributions": len(replay.get("attribution") or []),
        "counterfactuals": len(replay.get("counterfactuals") or []),
        "deterministic_sections": sorted(
            (bundle.get("deterministic") or {}).keys()),
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "root_cause_adapter",
        "adapter_version": ADAPTER_VERSION,
        "source": "ai.aireplay (canonical trade, replay, counterfactuals)",
        "invents_evidence": False,
        "translates": [
            "divergences: dict-of-kinds -> list of records",
            "attribution: candidates block -> list of attributions",
        ],
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the bundle is populated, and that the shape translation happened.

    The load-bearing check is `divergences_are_records`: read straight from
    aireplay, a dict of divergences iterates as its KEY STRINGS and the
    analyzer silently discards every one. That failure produces an analysis
    that looks complete and contains nothing.
    """
    report: Dict[str, Any] = {
        "component": "root_cause_adapter", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; nothing to adapt"
            return report

        bundle = to_analysis_input(trades[0])
        if bundle.get("unusable"):
            report["ok"] = False
            report["reason"] = bundle["unusable"]
            return report

        replay = bundle.get("replay") or {}
        checks["has_decision_snapshots"] = bool(bundle.get("decision_snapshots"))
        checks["has_deterministic_sections"] = bool(bundle.get("deterministic"))
        checks["replay_available"] = bool(replay.get("replay_version"))
        checks["divergences_are_records"] = all(
            isinstance(item, Mapping) for item in replay.get("divergences") or [])
        checks["attributions_are_records"] = all(
            isinstance(item, Mapping) for item in replay.get("attribution") or [])
        checks["counterfactuals_historical"] = all(
            item.get("is_historical_truth")
            for item in replay.get("counterfactuals") or [])

        result = analyze_trade(trades[0])
        checks["analysis_has_evidence"] = len(result.evidence) > 0
        checks["analysis_produces_report"] = bool(result.report)

        required = ("has_decision_snapshots", "divergences_are_records",
                    "attributions_are_records", "counterfactuals_historical",
                    "analysis_produces_report")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "ADAPTER_VERSION", "to_analysis_input", "analyze_trade", "analyze_trades",
    "coverage", "get_status", "self_check",
]
