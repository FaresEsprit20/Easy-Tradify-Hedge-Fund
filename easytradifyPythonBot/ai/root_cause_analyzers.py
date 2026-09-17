"""
EasyTradify - Root Cause Analyzer
=================================

Final evidence-only Root Cause layer.

ARCHITECTURAL RULE:
    Root Cause MUST NOT recalculate anything that another component already
    calculated.

The analyzer consumes:
    1. Decision Snapshots
    2. Market Synthesis snapshots
    3. Existing deterministic component outputs
    4. Existing GNN / Non-RL / RL / Trade Quality outputs
    5. Replay divergences and attributions
    6. Simulator/counterfactual results
    7. Final execution/outcome data

It diagnoses decisions; it is NOT another market-intelligence engine.

It never:
    - reads raw candles to calculate indicators
    - decodes price evolution
    - calculates price statistics
    - detects patterns
    - detects liquidity/FVG/SMC structures
    - calculates volume statistics
    - calculates regime
    - recalculates confidence
    - creates fake prediction accuracy
    - creates majority votes
    - changes thresholds/weights/models
    - issues autonomous trading instructions
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .root_cause_models import (
    Attribution,
    AttributionType,
    CounterfactualResult,
    DecisionSnapshot,
    Divergence,
    EvidenceRef,
    FailureDiagnosis,
    RootCauseAnalysisResult,
    ReplaySummary,
    Severity,
    OutcomeSnapshot,
)
from .root_cause_trackers import RootCauseEvidenceTracker


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


class RootCauseAnalyzer:
    """Consumes canonical evidence and produces a diagnostic explanation."""

    VERSION = "2.0-evidence-only"

    def __init__(self, tracker: Optional[RootCauseEvidenceTracker] = None):
        self.tracker = tracker or RootCauseEvidenceTracker()
        self.analysis_count = 0

    def analyze(self, trade_data: Mapping[str, Any]) -> RootCauseAnalysisResult:
        """
        Analyze a trade exclusively from already-produced evidence.

        Supported canonical inputs:
            decision_snapshots
            market_synthesis
            deterministic
            gnn
            non_rl
            trade_quality
            rl
            risk_gate
            execution
            outcome / close_data
            replay
            provenance

        Legacy analysis_at_open is accepted as evidence when no canonical
        decision snapshots are supplied. It is copied, never reinterpreted.
        """

        data = _mapping(trade_data)
        ticket = data.get("trade_id", data.get("ticket"))
        symbol = str(data.get("symbol", ""))

        outcome = self._read_outcome(data)
        snapshots = self._read_decision_snapshots(data)
        replay_data = _mapping(data.get("replay"))

        result = RootCauseAnalysisResult(
            schema_version="2.0",
            trade_id=ticket,
            symbol=symbol,
            profit=outcome.pnl,
            is_loss=(outcome.pnl < 0 if outcome.pnl is not None else None),
            timestamp=datetime.now(timezone.utc).isoformat(),
            outcome=outcome,
            decision_snapshots=snapshots,
            replay=self._read_replay(replay_data),
            market_synthesis=_mapping(data.get("market_synthesis")),
            gnn_evidence=_mapping(data.get("gnn")),
            non_rl_evidence=_mapping(data.get("non_rl")),
            execution_evidence=_mapping(data.get("execution")),
            management_evidence=_mapping(data.get("management")),
            provenance=_mapping(data.get("provenance")),
        )

        # Canonical evidence comes from snapshots. No indicator is recalculated.
        result.component_evidence = self.tracker.index_component_evidence(
            [self._snapshot_to_dict(s) for s in snapshots]
        )

        result.evidence = self._collect_top_level_evidence(data, snapshots)
        result.diagnosis = self._build_diagnosis(result)
        result.recommendations = self._build_experiment_proposals(result)
        result.validation_requirements = self._build_validation_requirements(result)
        result.win_analysis = self._read_win_analysis(data, result)

        result.report = self._build_report(result)

        self.analysis_count += 1
        return result

    # ------------------------------------------------------------------
    # Input adapters: copy existing evidence only.
    # ------------------------------------------------------------------

    def _read_outcome(self, data: Mapping[str, Any]) -> OutcomeSnapshot:
        raw = _mapping(data.get("outcome"))
        if not raw:
            raw = _mapping(data.get("close_data"))

        pnl = raw.get("pnl", raw.get("profit_usd"))
        return OutcomeSnapshot(
            result=raw.get("result", raw.get("status")),
            pnl=pnl,
            return_value=raw.get("return", raw.get("return_value")),
            mfe=raw.get("mfe"),
            mae=raw.get("mae"),
            duration=raw.get("duration"),
            exit_reason=raw.get("exit_reason", raw.get("close_reason")),
            execution=_mapping(raw.get("execution")),
            provenance=_mapping(raw.get("provenance")),
        )

    def _read_decision_snapshots(
        self, data: Mapping[str, Any]
    ) -> List[DecisionSnapshot]:
        raw_snapshots = _list(data.get("decision_snapshots"))

        # Backward-compatible read of analysis_at_open. This is a single
        # already-created snapshot, not a trigger to run legacy analyzers.
        # Flatten the stored envelope before reading any field from it --
        # the live writer nests the analysis under m1_analysis_raw, so the
        # legacy path below would otherwise find an empty snapshot on every
        # real trade and report the reasoning as missing.
        try:
            from .price_evolution_bridge import canonical_analysis
            if isinstance(data.get("analysis_at_open"), Mapping):
                data = dict(data)
                data["analysis_at_open"] = canonical_analysis(
                    data["analysis_at_open"])
        except Exception:
            pass

        if not raw_snapshots and isinstance(data.get("analysis_at_open"), Mapping):
            raw_snapshots = [{
                "snapshot_id": "legacy_analysis_at_open",
                "timestamp": data.get("entry_at", data.get("timestamp", "")),
                "phase": "entry",
                "decision": data.get("decision"),
                "decision_reason": _mapping(
                    data.get("analysis_at_open")
                ),
                "market_synthesis": _mapping(
                    data.get("analysis_at_open", {}).get("market_synthesis")
                ),
                "deterministic": _mapping(
                    data.get("analysis_at_open", {}).get("deterministic")
                ),
                "gnn": _mapping(data.get("analysis_at_open", {}).get("gnn")),
                "non_rl": _mapping(
                    data.get("analysis_at_open", {}).get("non_rl")
                ),
                "trade_quality": _mapping(
                    data.get("analysis_at_open", {}).get("trade_quality")
                ),
                "rl": _mapping(data.get("analysis_at_open", {}).get("rl")),
                "risk_gate": _mapping(
                    data.get("analysis_at_open", {}).get("risk_gate")
                ),
                "execution": _mapping(
                    data.get("analysis_at_open", {}).get("execution")
                ),
                "provenance": _mapping(
                    data.get("analysis_at_open", {}).get("provenance")
                ),
            }]

        snapshots: List[DecisionSnapshot] = []
        for raw in raw_snapshots:
            item = _mapping(raw)
            snapshots.append(
                DecisionSnapshot(
                    snapshot_id=str(item.get("snapshot_id", "")),
                    trade_id=item.get("trade_id", data.get("trade_id", data.get("ticket"))),
                    timestamp=str(item.get("timestamp", "")),
                    phase=str(item.get("phase", "")),
                    decision=item.get("decision"),
                    decision_reason=dict(_mapping(item.get("decision_reason"))),
                    market_synthesis=dict(_mapping(item.get("market_synthesis"))),
                    deterministic=dict(_mapping(item.get("deterministic"))),
                    gnn=dict(_mapping(item.get("gnn"))),
                    non_rl=dict(_mapping(item.get("non_rl"))),
                    trade_quality=dict(_mapping(item.get("trade_quality"))),
                    rl=dict(_mapping(item.get("rl"))),
                    risk_gate=dict(_mapping(item.get("risk_gate"))),
                    execution=dict(_mapping(item.get("execution"))),
                    provenance=dict(_mapping(item.get("provenance"))),
                )
            )
        return snapshots

    def _read_replay(self, replay: Mapping[str, Any]) -> ReplaySummary:
        return ReplaySummary(
            replay_version=replay.get("replay_version"),
            first_divergence=replay.get("first_divergence"),
            divergences=_list(replay.get("divergences")),
            attribution=_list(replay.get("attribution")),
            failure_class=replay.get("failure_class"),
            replay_score=replay.get("replay_score"),
            counterfactuals=_list(replay.get("counterfactuals")),
            provenance=dict(_mapping(replay.get("provenance"))),
        )

    def _read_win_analysis(
        self, data: Mapping[str, Any], result: RootCauseAnalysisResult
    ) -> Dict[str, Any]:
        supplied = data.get("win_analysis")
        if isinstance(supplied, Mapping):
            return dict(supplied)
        return {}

    def _snapshot_to_dict(self, snapshot: DecisionSnapshot) -> Dict[str, Any]:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "timestamp": snapshot.timestamp,
            "phase": snapshot.phase,
            "deterministic": snapshot.deterministic,
            "provenance": snapshot.provenance,
        }

    def _collect_top_level_evidence(
        self,
        data: Mapping[str, Any],
        snapshots: Iterable[DecisionSnapshot],
    ) -> List[EvidenceRef]:
        refs: List[EvidenceRef] = []

        provenance = _mapping(data.get("provenance"))
        refs.append(
            EvidenceRef(
                source="trade_record",
                path="provenance",
                value=dict(provenance),
                version=provenance.get("analysis_version"),
            )
        )

        replay = _mapping(data.get("replay"))
        if replay:
            refs.append(
                EvidenceRef(
                    source="ai_market_replay",
                    path="replay",
                    value=replay,
                    version=replay.get("replay_version"),
                )
            )

        for snapshot in snapshots:
            refs.append(
                EvidenceRef(
                    source="decision_genome",
                    path=f"decision_snapshots[{snapshot.snapshot_id}]",
                    timestamp=snapshot.timestamp,
                    value={
                        "decision": snapshot.decision,
                        "phase": snapshot.phase,
                        "market_synthesis": snapshot.market_synthesis,
                        "deterministic": snapshot.deterministic,
                        "gnn": snapshot.gnn,
                        "non_rl": snapshot.non_rl,
                        "trade_quality": snapshot.trade_quality,
                        "rl": snapshot.rl,
                        "risk_gate": snapshot.risk_gate,
                    },
                    version=snapshot.provenance.get("feature_version"),
                )
            )

        return refs

    # ------------------------------------------------------------------
    # Diagnosis: consumes Replay attribution. It does not rediscover causes.
    # ------------------------------------------------------------------

    def _build_diagnosis(
        self, result: RootCauseAnalysisResult
    ) -> FailureDiagnosis:
        replay = result.replay

        first = self._to_divergence(replay.first_divergence)
        attributions = [
            self._to_attribution(item) for item in replay.attribution
        ]
        counterfactuals = [
            self._to_counterfactual(item) for item in replay.counterfactuals
        ]

        primary = next(
            (
                item for item in attributions
                if item.attribution_type == AttributionType.PRIMARY
            ),
            None,
        )

        if primary is None and attributions:
            primary = attributions[0]

        contributors = [
            item for item in attributions
            if item is not primary
            and item.attribution_type == AttributionType.CONTRIBUTING
        ]

        failure_class = replay.failure_class or "UNKNOWN"
        severity = self._severity_from_evidence(
            failure_class=failure_class,
            first_divergence=first,
            outcome=result.outcome,
        )

        causal_status = "UNPROVEN"
        if primary and primary.causal_status:
            causal_status = primary.causal_status

        explanation = self._compose_explanation(
            result=result,
            first=first,
            primary=primary,
            contributors=contributors,
            causal_status=causal_status,
        )

        return FailureDiagnosis(
            failure_class=failure_class,
            severity=severity,
            primary_cause=primary,
            contributing_causes=contributors,
            first_divergence=first,
            counterfactuals=counterfactuals,
            confidence=replay.replay_score,
            causal_status=causal_status,
            explanation=explanation,
        )

    def _to_divergence(self, raw: Any) -> Optional[Divergence]:
        if not isinstance(raw, Mapping):
            return None
        evidence = [
            self._to_evidence_ref(x)
            for x in _list(raw.get("evidence"))
            if isinstance(x, Mapping)
        ]
        return Divergence(
            divergence_id=str(raw.get("divergence_id", raw.get("id", ""))),
            timestamp=raw.get("timestamp"),
            phase=raw.get("phase"),
            category=str(raw.get("category", "")),
            expected=raw.get("expected"),
            observed=raw.get("observed"),
            magnitude=raw.get("magnitude"),
            source=str(raw.get("source", "replay")),
            evidence=evidence,
            confidence=raw.get("confidence"),
            metadata=dict(_mapping(raw.get("metadata"))),
        )

    def _to_attribution(self, raw: Any) -> Attribution:
        item = _mapping(raw)
        raw_type = str(item.get("attribution_type", "UNKNOWN")).upper()
        try:
            attribution_type = AttributionType(raw_type)
        except ValueError:
            attribution_type = AttributionType.UNKNOWN

        return Attribution(
            target=str(item.get("target", item.get("component", ""))),
            attribution_type=attribution_type,
            role=str(item.get("role", "")),
            explanation=str(item.get("explanation", item.get("reason", ""))),
            evidence=[
                self._to_evidence_ref(x)
                for x in _list(item.get("evidence"))
                if isinstance(x, Mapping)
            ],
            confidence=item.get("confidence"),
            causal_status=str(item.get("causal_status", "UNPROVEN")),
            counterfactual_reference=item.get("counterfactual_reference"),
        )

    def _to_counterfactual(self, raw: Any) -> CounterfactualResult:
        item = _mapping(raw)
        return CounterfactualResult(
            scenario_id=str(item.get("scenario_id", item.get("id", ""))),
            action=str(item.get("action", "")),
            parameters=dict(_mapping(item.get("parameters"))),
            result=item.get("result"),
            pnl=item.get("pnl"),
            return_value=item.get("return"),
            improvement=item.get("improvement"),
            simulator_version=item.get("simulator_version"),
            historical_path_reference=item.get("historical_path_reference"),
            is_historical_truth=bool(item.get("is_historical_truth", True)),
            confidence=item.get("confidence"),
            evidence=[
                self._to_evidence_ref(x)
                for x in _list(item.get("evidence"))
                if isinstance(x, Mapping)
            ],
        )

    def _to_evidence_ref(self, raw: Mapping[str, Any]) -> EvidenceRef:
        return EvidenceRef(
            source=str(raw.get("source", "")),
            path=str(raw.get("path", "")),
            timestamp=raw.get("timestamp"),
            available_at=raw.get("available_at"),
            version=raw.get("version"),
            value=raw.get("value"),
            quality=raw.get("quality"),
            metadata=dict(_mapping(raw.get("metadata"))),
        )

    def _severity_from_evidence(
        self,
        *,
        failure_class: str,
        first_divergence: Optional[Divergence],
        outcome: OutcomeSnapshot,
    ) -> Severity:
        # This is classification of supplied replay evidence, not a market
        # calculation. If Replay supplied severity, use it.
        if first_divergence and first_divergence.metadata.get("severity"):
            raw = str(first_divergence.metadata["severity"]).upper()
            try:
                return Severity(raw)
            except ValueError:
                pass

        if failure_class in {
            "RISK_GATE_BYPASS",
            "EXECUTION_FAILURE",
            "DECISION_LEAKAGE",
            "DATA_CORRUPTION",
        }:
            return Severity.CRITICAL

        if failure_class in {
            "ENTRY_TIMING",
            "MANAGEMENT_FAILURE",
            "MODEL_MISSED_DIVERGENCE",
        }:
            return Severity.HIGH

        if outcome.result in {"LOSS", "STOPPED_OUT"}:
            return Severity.MEDIUM

        return Severity.LOW

    def _compose_explanation(
        self,
        *,
        result: RootCauseAnalysisResult,
        first: Optional[Divergence],
        primary: Optional[Attribution],
        contributors: List[Attribution],
        causal_status: str,
    ) -> str:
        if not result.replay.replay_version:
            return (
                "No Replay artifact was supplied. Root Cause will not "
                "reconstruct market behavior or invent a cause. "
                "Run AI Market Replay first."
            )

        parts: List[str] = []

        if first:
            parts.append(
                f"First replay divergence: {first.category or 'UNSPECIFIED'}"
                + (f" at {first.timestamp}" if first.timestamp else "")
                + "."
            )

        if primary:
            parts.append(
                f"Primary evidence-backed attribution: "
                f"{primary.target or 'UNSPECIFIED'}."
            )

        if contributors:
            names = ", ".join(
                item.target for item in contributors if item.target
            )
            if names:
                parts.append(f"Contributing evidence: {names}.")

        parts.append(f"Causal status: {causal_status}.")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Learning output: proposals only. No live mutation.
    # ------------------------------------------------------------------

    def _build_experiment_proposals(
        self, result: RootCauseAnalysisResult
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []

        primary = result.diagnosis.primary_cause
        if primary:
            proposals.append({
                "type": "POLICY_EXPERIMENT",
                "target": primary.target,
                "reason": primary.explanation,
                "causal_status": primary.causal_status,
                "requires": [
                    "walk_forward",
                    "out_of_sample",
                    "regime_breakdown",
                    "rollback_plan",
                ],
            })

        if result.diagnosis.counterfactuals:
            proposals.append({
                "type": "COUNTERFACTUAL_REVIEW",
                "scenario_ids": [
                    x.scenario_id for x in result.diagnosis.counterfactuals
                ],
                "requires": [
                    "historical_path_consistency",
                    "execution_cost_consistency",
                    "out_of_sample_validation",
                ],
            })

        return proposals

    def _build_validation_requirements(
        self, result: RootCauseAnalysisResult
    ) -> List[Dict[str, Any]]:
        if not result.diagnosis.primary_cause:
            return [{
                "requirement": "replay_artifact",
                "status": "REQUIRED",
                "reason": "No primary replay attribution exists.",
            }]

        return [
            {
                "requirement": "causal_validation",
                "status": "REQUIRED",
                "reason": "Association is not sufficient to promote a rule.",
            },
            {
                "requirement": "walk_forward",
                "status": "REQUIRED",
            },
            {
                "requirement": "out_of_sample",
                "status": "REQUIRED",
            },
            {
                "requirement": "regime_breakdown",
                "status": "REQUIRED",
            },
        ]

    def _build_report(self, result: RootCauseAnalysisResult) -> str:
        d = result.diagnosis
        lines = [
            f"Root Cause Analysis v{self.VERSION}",
            f"Trade: {result.trade_id}",
            f"Symbol: {result.symbol}",
            f"Outcome: {result.outcome.result or 'UNKNOWN'}",
            f"PnL: {result.outcome.pnl}",
            f"Failure class: {d.failure_class}",
            f"Severity: {d.severity.value}",
            f"Causal status: {d.causal_status}",
            f"Replay version: {result.replay.replay_version or 'NOT_AVAILABLE'}",
            "",
            d.explanation,
        ]

        if d.primary_cause:
            lines.append(
                f"Primary cause: {d.primary_cause.target} — "
                f"{d.primary_cause.explanation}"
            )

        if d.contributing_causes:
            lines.append(
                "Contributors: "
                + ", ".join(
                    x.target for x in d.contributing_causes if x.target
                )
            )

        if d.counterfactuals:
            lines.append(
                "Counterfactual scenarios supplied: "
                + str(len(d.counterfactuals))
            )

        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.__class__.__name__,
            "version": self.VERSION,
            "analyses": self.analysis_count,
            "mode": "evidence_only",
            "recalculates_components": False,
            "recalculates_price": False,
            "recalculates_patterns": False,
            "recalculates_regime": False,
            "recalculates_confidence": False,
            "mutates_models": False,
            "mutates_thresholds": False,
            "issues_autonomous_trade_actions": False,
            "requires_replay_for_root_cause": True,
        }


__all__ = ["RootCauseAnalyzer"]


# ============================================================
# MODULE-LEVEL VERIFICATION ENDPOINTS
# ============================================================
#
# Standard 12. Neither this module nor root_cause_trackers exposed a
# self_check, so /verify could not reach them at all -- 1,082 lines of
# diagnostic machinery with no test file and no way to ask whether it worked.
# It did not work: fed a stored trade it produced 0 component evidence and no
# diagnosis, because nothing built the evidence bundle it reads. See
# root_cause_adapter.

def get_status(analyzer: Optional["RootCauseAnalyzer"] = None) -> Dict[str, Any]:
    """Capability and policy of the root cause layer."""
    status = (analyzer or RootCauseAnalyzer()).get_status()
    status.update({
        "component": "root_cause_analyzers",
        "invents_causes": False,
        "requires_replay_artifact": True,
        "input_adapter": "ai.root_cause_adapter.to_analysis_input",
    })
    return status


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the analyzer reads a real evidence bundle, and refuses without one.

    The refusal check is load-bearing. This module's entire value rests on
    declining to name a cause it cannot evidence; an analyzer that produces a
    confident diagnosis from an empty record is worse than none, because its
    output is indistinguishable from a real finding.
    """
    report: Dict[str, Any] = {
        "component": "root_cause_analyzers", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        analyzer = RootCauseAnalyzer()

        # Refusal is not a missing diagnosis -- it is a PRESENT diagnosis that
        # names no cause. The analyzer still reports failure_class UNKNOWN,
        # primary_cause None and an explanation saying why, which is a far
        # more useful answer than a null: it distinguishes "we looked and the
        # record cannot support a cause" from "nothing ran".
        empty = analyzer.analyze({"trade_id": "none"})
        checks["refuses_without_replay"] = bool(
            empty.diagnosis is not None
            and empty.diagnosis.primary_cause is None
            and empty.diagnosis.failure_class == "UNKNOWN"
            and "Replay" in (empty.diagnosis.explanation or ""))

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; analysis not exercised"
            return report

        from .root_cause_adapter import to_analysis_input

        bundle = to_analysis_input(trades[0])
        result = analyzer.analyze(bundle)
        checks["evidence_refs"] = len(result.evidence)
        checks["component_evidence"] = len(result.component_evidence)
        checks["has_component_evidence"] = bool(result.component_evidence)
        checks["produces_report"] = bool(result.report)
        checks["diagnosis_present"] = result.diagnosis is not None

        # Nothing may be asserted as PROVEN without a counterfactual behind it.
        attributions = list(result.diagnosis.contributing_causes or []) if (
            result.diagnosis) else []
        if result.diagnosis and result.diagnosis.primary_cause:
            attributions.append(result.diagnosis.primary_cause)
        checks["no_unproven_causal_claims"] = all(
            item.causal_status != "PROVEN" or item.counterfactual_reference
            for item in attributions)

        required = ("refuses_without_replay", "has_component_evidence",
                    "produces_report", "no_unproven_causal_claims")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report
