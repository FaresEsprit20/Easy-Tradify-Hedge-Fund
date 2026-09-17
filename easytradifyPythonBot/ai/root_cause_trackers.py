"""
EasyTradify - Root Cause Trackers
=================================

Evidence trackers only.

These trackers DO NOT:
    - calculate indicators
    - decode price evolution
    - detect FVGs
    - detect patterns
    - calculate ADX/RSI/VWAP/ATR
    - infer market regime
    - calculate component scores
    - invent confidence accuracy
    - vote between indicators
    - mutate model weights
    - mutate thresholds
    - generate trading actions

They index and organize facts already produced by upstream systems.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .root_cause_models import EvidenceRef


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


class RootCauseEvidenceTracker:
    """Builds diagnostic indexes from immutable upstream evidence."""

    def index_decision_snapshots(
        self, snapshots: Iterable[Mapping[str, Any]]
    ) -> Dict[str, Any]:
        items = [dict(item) for item in snapshots]
        by_id: Dict[str, Dict[str, Any]] = {}
        by_timestamp: Dict[str, Dict[str, Any]] = {}

        for item in items:
            snapshot_id = str(item.get("snapshot_id", ""))
            timestamp = str(item.get("timestamp", ""))
            if snapshot_id:
                by_id[snapshot_id] = item
            if timestamp:
                by_timestamp[timestamp] = item

        return {
            "count": len(items),
            "by_id": by_id,
            "by_timestamp": by_timestamp,
        }

    def index_replay_evidence(
        self, replay: Mapping[str, Any]
    ) -> Dict[str, Any]:
        divergences = _as_list(replay.get("divergences"))
        attribution = _as_list(replay.get("attribution"))
        counterfactuals = _as_list(replay.get("counterfactuals"))

        return {
            "first_divergence": replay.get("first_divergence"),
            "failure_class": replay.get("failure_class"),
            "divergences": divergences,
            "attribution": attribution,
            "counterfactuals": counterfactuals,
            "replay_score": replay.get("replay_score"),
            "replay_version": replay.get("replay_version"),
        }

    def index_component_evidence(
        self, snapshots: Iterable[Mapping[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Indexes existing component outputs without recalculating them."""

        result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for snapshot in snapshots:
            # Both spellings are accepted. DecisionSnapshot.to_dict() emits
            # `deterministic_features`; this read only `deterministic`, so
            # every canonical snapshot produced ZERO component evidence and
            # said nothing about it -- the analysis came back complete-looking
            # and componentless. A key mismatch between a producer and a
            # consumer is invisible unless one of them insists.
            deterministic = snapshot.get("deterministic")
            if not isinstance(deterministic, Mapping):
                deterministic = snapshot.get("deterministic_features")
            if not isinstance(deterministic, Mapping):
                continue

            for component, evidence in deterministic.items():
                result[str(component)].append({
                    "timestamp": snapshot.get("timestamp"),
                    "phase": snapshot.get("phase"),
                    "evidence": evidence,
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "provenance": snapshot.get("provenance", {}),
                })

        return dict(result)

    def collect_evidence_refs(
        self,
        evidence: Iterable[Mapping[str, Any]],
        *,
        source: str,
        path: str,
    ) -> List[EvidenceRef]:
        """Wraps existing records as references; it never derives new values."""

        refs: List[EvidenceRef] = []
        for item in evidence:
            refs.append(
                EvidenceRef(
                    source=source,
                    path=path,
                    timestamp=item.get("timestamp"),
                    available_at=item.get("available_at"),
                    version=item.get("version"),
                    value=item.get("evidence", item.get("value")),
                    quality=item.get("quality"),
                    metadata={
                        "snapshot_id": item.get("snapshot_id"),
                        "phase": item.get("phase"),
                    },
                )
            )
        return refs

    def build_component_timeline(
        self, snapshots: Iterable[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Returns supplied component states in supplied chronological order.

        Ordering is intentionally NOT reconstructed here. Replay must provide
        snapshots in deterministic order.
        """

        timeline: List[Dict[str, Any]] = []
        for snapshot in snapshots:
            timeline.append({
                "snapshot_id": snapshot.get("snapshot_id"),
                "timestamp": snapshot.get("timestamp"),
                "phase": snapshot.get("phase"),
                "deterministic": snapshot.get("deterministic", {}),
            })
        return timeline

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.__class__.__name__,
            "mode": "evidence_only",
            "recalculates_market_intelligence": False,
            "mutates_models": False,
            "mutates_thresholds": False,
            "requires_replay_for_temporal_attribution": True,
        }


# Compatibility name. The old tracker class is intentionally reduced to an
# evidence-only facade; legacy calculation methods are not retained.
RootCauseAnalyzer = RootCauseEvidenceTracker

__all__ = ["RootCauseEvidenceTracker", "RootCauseAnalyzer"]


# ============================================================
# MODULE-LEVEL VERIFICATION ENDPOINTS
# ============================================================
#
# Standard 12. The indexer here silently produced zero component evidence for
# every canonical snapshot, because it read `deterministic` while
# DecisionSnapshot.to_dict() emits `deterministic_features`. A key mismatch
# between a producer and a consumer is invisible unless something insists on
# checking, which is what this does.

def get_status(tracker: Optional["RootCauseEvidenceTracker"] = None
               ) -> Dict[str, Any]:
    status = (tracker or RootCauseEvidenceTracker()).get_status()
    status.update({
        "component": "root_cause_trackers",
        "recalculates_indicators": False,
        "accepted_deterministic_keys": ["deterministic", "deterministic_features"],
    })
    return status


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """Prove the indexer finds component evidence under BOTH key spellings."""
    report: Dict[str, Any] = {
        "component": "root_cause_trackers", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        tracker = RootCauseEvidenceTracker()

        legacy = tracker.index_component_evidence([
            {"snapshot_id": "a", "deterministic": {"smc": {"x": 1}}}])
        canonical = tracker.index_component_evidence([
            {"snapshot_id": "b", "deterministic_features": {"smc": {"x": 1}}}])
        checks["indexes_legacy_key"] = "smc" in legacy
        checks["indexes_canonical_key"] = "smc" in canonical

        # A snapshot with neither key must yield nothing, not a fabricated row.
        empty = tracker.index_component_evidence([{"snapshot_id": "c"}])
        checks["empty_snapshot_yields_nothing"] = empty == {}

        report["ok"] = all(bool(value) for value in checks.values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report
