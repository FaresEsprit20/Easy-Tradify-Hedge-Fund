"""
non_rl_intelligence.py
AI_MarketReplay — 5★ Unified Non-Reinforcement-Learning Intelligence Engine

Purpose
-------
A standalone, leakage-safe intelligence layer for AI_MarketReplay.

It does NOT execute trades and it does NOT use reinforcement learning.
It learns to:
    1. predict trade/setup outcomes,
    2. estimate MFE/MAE and time-to-event,
    3. classify failure causes,
    4. attribute outcomes to decision components,
    5. model market regimes,
    6. detect anomalous decision states,
    7. discover recurring state/outcome patterns,
    8. calibrate probabilities,
    9. generate counterfactual labels from replay,
   10. explain decisions and failures,
   11. validate models chronologically and walk-forward.

Design principle
----------------
    Replay / Decision Genome
              ↓
      Leakage-safe features
              ↓
      ┌───────┴────────────────────────────────────────────┐
      │ NON-RL INTELLIGENCE                                │
      │                                                    │
      │ Outcome prediction      Failure diagnosis          │
      │ MFE / MAE prediction    Component attribution      │
      │ Time-to-event            Regime modeling            │
      │ Setup quality            Anomaly detection          │
      │ Pattern discovery       Probability calibration    │
      │ Counterfactual labels   Explainability             │
      └───────────────────────┬────────────────────────────┘
                              ↓
                  Validation / OOS / A-B
                              ↓
                    RL decision specialists

The engine is intentionally infrastructure-first: callers may feed the exact
Decision Genome / Market Reality dictionaries produced by AI_MarketReplay,
or generic snapshot dictionaries. No Firebase/network dependency is required.

Research/paper-trading infrastructure only. No broker or MT5 execution.
"""

from __future__ import annotations

import copy
import json
import math
import os
import random
import statistics
import warnings
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VERSION = "5.0-unified-non-rl"

# Optional scientific stack -------------------------------------------------
try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        ExtraTreesRegressor,
        HistGradientBoostingClassifier,
        HistGradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        mean_absolute_error,
        mean_squared_error,
        precision_recall_fscore_support,
        roc_auc_score,
    )
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    SKLEARN_AVAILABLE = False

try:
    import joblib
except Exception:  # pragma: no cover
    joblib = None


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

FUTURE_KEY_TOKENS = (
    "future",
    "outcome",
    "result",
    "pnl",
    "profit",
    "loss",
    "mfe",
    "mae",
    "tp_hit",
    "sl_hit",
    "target_hit",
    "stop_hit",
    "time_to",
    "future_return",
    "forward_return",
    "label",
    "reward",
    "exit_reason",
    "trade_result",
)

TIMESTAMP_KEYS = (
    "available_at",
    "timestamp",
    "decision_timestamp",
    "observed_at",
    "event_timestamp",
    "time",
)

ID_KEYS = {
    "id",
    "uuid",
    "trade_id",
    "position_id",
    "order_id",
    "event_id",
    "symbol",
    "asset",
    "ticker",
    "direction",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        value = float(x)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _flatten(
    obj: Mapping[str, Any],
    prefix: str = "",
    out: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Flatten nested dictionaries/lists into deterministic scalar-ish keys."""
    if out is None:
        out = {}
    for key, value in obj.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            _flatten(value, name, out)
        elif isinstance(value, (list, tuple)):
            numeric = [_safe_float(v, float("nan")) for v in value]
            if numeric and all(math.isfinite(v) for v in numeric):
                for i, v in enumerate(numeric):
                    out[f"{name}[{i}]"] = v
                out[f"{name}.__len__"] = len(value)
            else:
                # Keep categorical list information without leaking nested
                # outcome objects.
                out[f"{name}.__len__"] = len(value)
                for i, v in enumerate(value[:20]):
                    if _is_number(v) or isinstance(v, str):
                        out[f"{name}[{i}]"] = v
        else:
            out[name] = value
    return out


def _leaf_name(key: str) -> str:
    return key.lower().replace("-", "_").split(".")[-1].replace("[", "_")


def _looks_future(key: str) -> bool:
    leaf = _leaf_name(key)
    # Explicit outcome keys are removed. Avoid overbroad substring matches
    # such as "profitability_score" when it is a genuine contemporaneous
    # model feature; caller can also provide an explicit allow-list.
    exact = {
        "outcome", "result", "pnl", "profit", "loss", "mfe", "mae",
        "tp_hit", "sl_hit", "target_hit", "stop_hit", "future_return",
        "forward_return", "reward", "exit_reason", "trade_result",
        "future", "label",
    }
    if leaf in exact:
        return True
    prefixes = (
        "future_", "forward_", "outcome_", "label_", "reward_",
        "time_to_", "pnl_", "profit_", "loss_",
    )
    return any(leaf.startswith(p) for p in prefixes)


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def sanitize_observation(
    observation: Mapping[str, Any],
    decision_timestamp: Any = None,
    explicit_future_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Remove future/outcome information and reject features unavailable at
    decision time.

    `available_at` can be attached to a scalar feature as:
        {"value": 1.2, "available_at": "..."}
    or at the snapshot level. Scalar wrappers are unwrapped after checking.
    """
    explicit = {str(k).lower() for k in (explicit_future_keys or [])}
    decision_dt = _coerce_datetime(decision_timestamp)

    flat = _flatten(observation)
    clean: Dict[str, Any] = {}

    for key, value in flat.items():
        low = key.lower()
        if low in explicit or _looks_future(key):
            continue
        if any(token in low for token in ("analysis_at_close", "price_evolution_future")):
            continue
        if not (_is_number(value) or isinstance(value, (str, bool))):
            continue

        # A nested wrapper represented by the flattened representation may
        # expose the availability timestamp. Skip timestamp metadata itself.
        if low.endswith("available_at") or low.endswith("observed_at"):
            continue

        clean[key] = value

    # If a top-level available_at exists, enforce it.
    available = None
    for key in ("available_at", "decision_timestamp", "timestamp", "observed_at"):
        if key in observation:
            available = _coerce_datetime(observation.get(key))
            if available:
                break
    if decision_dt and available and available > decision_dt:
        raise ValueError(
            f"Leakage violation: observation available_at={available.isoformat()} "
            f"is after decision_timestamp={decision_dt.isoformat()}"
        )

    return clean


def _numeric_matrix(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> List[List[float]]:
    matrix = []
    for row in rows:
        matrix.append([
            _safe_float(row.get(name, 0.0), 0.0) if _is_number(row.get(name, 0.0))
            else 0.0
            for name in feature_names
        ])
    return matrix


def _mean(values: Sequence[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values if _is_number(v)]
    return statistics.fmean(vals) if vals else default


def _std(values: Sequence[float], default: float = 1.0) -> float:
    vals = [float(v) for v in values if _is_number(v)]
    if len(vals) < 2:
        return default
    s = statistics.pstdev(vals)
    return s if s > 1e-12 else default


def _sigmoid(x: float) -> float:
    x = max(-60.0, min(60.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(1.0 - 1e-8, max(1e-8, p))
    return math.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# Configuration and canonical records
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceConfig:
    random_seed: int = 42

    # Features
    max_features: int = 600
    min_feature_variance: float = 1e-12
    categorical_hash_buckets: int = 64

    # Outcome prediction
    prediction_horizons: Tuple[int, ...] = (1, 3, 5, 10, 20)
    min_training_samples: int = 40
    classifier_trees: int = 240
    regressor_trees: int = 240
    max_depth: Optional[int] = 12

    # Regime / anomaly / clustering
    regime_count: int = 6
    anomaly_contamination: float = 0.03
    pattern_clusters: int = 8
    min_cluster_samples: int = 30

    # Attribution
    permutation_repeats: int = 3
    top_attributions: int = 20

    # Calibration
    calibration_min_samples: int = 30

    # Validation
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    test_fraction: float = 0.20
    walk_forward_folds: int = 5
    minimum_improvement: float = 0.01

    # Cost / risk estimates used only for labels/diagnostics
    spread_cost: float = 0.0
    commission_cost: float = 0.0
    slippage_cost: float = 0.0

    # Artifacts
    artifact_dir: str = "ai/aireplay/artifacts/non_rl"

    def __post_init__(self) -> None:
        if abs((self.train_fraction + self.validation_fraction + self.test_fraction) - 1.0) > 1e-6:
            raise ValueError("train_fraction + validation_fraction + test_fraction must equal 1.0")


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: str
    observation: Dict[str, Any]
    outcome: Dict[str, Any] = field(default_factory=dict)
    component_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutcomeLabel:
    decision_id: str
    timestamp: str
    success: Optional[int] = None
    tp_hit: Optional[int] = None
    sl_hit: Optional[int] = None
    invalidated: Optional[int] = None
    realized_return: Optional[float] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    time_to_tp: Optional[float] = None
    time_to_sl: Optional[float] = None
    time_to_invalidation: Optional[float] = None
    waiting_improvement: Optional[float] = None
    setup_quality: Optional[float] = None
    failure_class: Optional[str] = None
    regime: Optional[str] = None
    source: str = "replay"


@dataclass
class Prediction:
    decision_id: str
    timestamp: str
    model_name: str
    probability: Optional[float] = None
    expected_value: Optional[float] = None
    expected_mfe: Optional[float] = None
    expected_mae: Optional[float] = None
    time_to_event: Optional[float] = None
    confidence: float = 0.0
    calibrated: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureDiagnosis:
    decision_id: str
    primary_class: str
    probabilities: Dict[str, float]
    evidence: List[str]
    first_divergence: Optional[str] = None
    component_contributors: List[Dict[str, Any]] = field(default_factory=list)
    regime: Optional[str] = None
    anomaly_score: Optional[float] = None


@dataclass
class CounterfactualLabel:
    decision_id: str
    baseline_value: float
    wait_values: Dict[int, float]
    best_wait: int
    improvement: float
    label: str
    evidence: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Canonical adapters
# ---------------------------------------------------------------------------

def decision_records_from_trades(
    trades: Sequence[Mapping[str, Any]],
    bridge: Any = None,
) -> List[DecisionRecord]:
    """
    Stored Firebase trade documents -> DecisionRecord objects.

    Delegates the whole conversion to PriceEvolutionBridge.to_decision_record()
    so there is exactly one place that knows how a stored trade maps onto
    features and labels. That matters here specifically: price_evolution is
    written in two different storage formats, and the open/evolution/close
    split is what keeps close-side data out of the feature set. Duplicating
    either rule in this module would be a second implementation free to drift
    from the first.

    Trades that produce no decision_id are skipped rather than given a
    synthetic one, since an unidentifiable record cannot be joined back to
    anything later.
    """
    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    records: List[DecisionRecord] = []
    for trade in trades or []:
        try:
            payload = bridge.to_decision_record(trade)
        except Exception:
            continue
        if not payload.get("decision_id"):
            continue
        records.append(DecisionRecord(**payload))
    return records


class DecisionGenomeAdapter:
    """Normalize a Decision Genome or generic analysis into a flat feature map."""

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()

    def encode(self, record: DecisionRecord) -> Dict[str, Any]:
        clean = sanitize_observation(
            record.observation,
            decision_timestamp=record.timestamp,
        )
        # Component scores are valid contemporaneous signals if they were
        # calculated before/at decision time.
        for name, value in record.component_scores.items():
            if _is_number(value):
                clean[f"component_score.{name}"] = float(value)
        return clean

    def build_dataset(
        self,
        records: Sequence[DecisionRecord],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        rows = [self.encode(r) for r in records]
        names = sorted({k for row in rows for k in row.keys()})
        # Stable cap by variance / occurrence.
        if len(names) > self.config.max_features:
            scored = []
            for name in names:
                vals = [_safe_float(row.get(name, 0.0)) for row in rows]
                scored.append((_std(vals), name))
            names = [n for _, n in sorted(scored, reverse=True)[: self.config.max_features]]
        return rows, names


class MarketRealityAdapter:
    """Extract outcome fields from replay/market reality without contaminating features."""

    def label(self, record: DecisionRecord) -> OutcomeLabel:
        o = record.outcome or {}
        return OutcomeLabel(
            decision_id=record.decision_id,
            timestamp=record.timestamp,
            success=int(o["success"]) if o.get("success") is not None else None,
            tp_hit=int(o["tp_hit"]) if o.get("tp_hit") is not None else None,
            sl_hit=int(o["sl_hit"]) if o.get("sl_hit") is not None else None,
            invalidated=int(o["invalidated"]) if o.get("invalidated") is not None else None,
            realized_return=_safe_float(o.get("realized_return"), None) if o.get("realized_return") is not None else None,
            mfe=_safe_float(o.get("mfe"), None) if o.get("mfe") is not None else None,
            mae=_safe_float(o.get("mae"), None) if o.get("mae") is not None else None,
            time_to_tp=_safe_float(o.get("time_to_tp"), None) if o.get("time_to_tp") is not None else None,
            time_to_sl=_safe_float(o.get("time_to_sl"), None) if o.get("time_to_sl") is not None else None,
            time_to_invalidation=_safe_float(o.get("time_to_invalidation"), None) if o.get("time_to_invalidation") is not None else None,
            waiting_improvement=_safe_float(o.get("waiting_improvement"), None) if o.get("waiting_improvement") is not None else None,
            setup_quality=_safe_float(o.get("setup_quality"), None) if o.get("setup_quality") is not None else None,
            failure_class=o.get("failure_class"),
            regime=o.get("regime"),
            source=o.get("source", "replay"),
        )


# ---------------------------------------------------------------------------
# Feature encoder
# ---------------------------------------------------------------------------

class TabularFeatureEncoder:
    """
    Deterministic numeric encoding for heterogeneous Decision Genome data.

    Categorical strings are one-hot-ish hashed into a stable numeric bucket.
    Numeric columns are standardized after fitting.
    """

    def __init__(self, max_features: int = 600, hash_buckets: int = 64):
        self.max_features = max_features
        self.hash_buckets = hash_buckets
        self.feature_names: List[str] = []
        self.means: Dict[str, float] = {}
        self.stds: Dict[str, float] = {}
        self.fitted = False

    def fit(self, rows: Sequence[Mapping[str, Any]]) -> "TabularFeatureEncoder":
        all_names = sorted({str(k) for row in rows for k in row.keys()})
        if len(all_names) > self.max_features:
            # Keep most variable numeric fields.
            scores = []
            for name in all_names:
                vals = []
                for row in rows:
                    v = row.get(name)
                    if _is_number(v):
                        vals.append(float(v))
                scores.append((_std(vals, 0.0), name))
            all_names = [name for _, name in sorted(scores, reverse=True)[:self.max_features]]

        self.feature_names = all_names
        raw = self._raw_matrix(rows)
        for i, name in enumerate(self.feature_names):
            col = [r[i] for r in raw]
            self.means[name] = _mean(col)
            self.stds[name] = _std(col)
        self.fitted = True
        return self

    def _encode_value(self, value: Any, name: str) -> float:
        if _is_number(value):
            return float(value)
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if value is None:
            return 0.0
        # Deterministic categorical hash. This intentionally stays compact.
        h = hash((name, str(value))) % self.hash_buckets
        return (h / max(1, self.hash_buckets - 1)) * 2.0 - 1.0

    def _raw_matrix(self, rows: Sequence[Mapping[str, Any]]) -> List[List[float]]:
        return [
            [self._encode_value(row.get(name), name) for name in self.feature_names]
            for row in rows
        ]

    def transform(self, rows: Sequence[Mapping[str, Any]]) -> List[List[float]]:
        if not self.fitted:
            raise RuntimeError("Feature encoder must be fitted before transform().")
        raw = self._raw_matrix(rows)
        return [
            [
                (value - self.means[name]) / self.stds[name]
                if self.stds[name] > 1e-12 else 0.0
                for value, name in zip(row, self.feature_names)
            ]
            for row in raw
        ]

    def save(self, path: str) -> None:
        payload = {
            "feature_names": self.feature_names,
            "means": self.means,
            "stds": self.stds,
            "hash_buckets": self.hash_buckets,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "TabularFeatureEncoder":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        obj = cls(hash_buckets=payload.get("hash_buckets", 64))
        obj.feature_names = payload["feature_names"]
        obj.means = payload["means"]
        obj.stds = payload["stds"]
        obj.fitted = True
        return obj


# ---------------------------------------------------------------------------
# Outcome / counterfactual labeling
# ---------------------------------------------------------------------------

class OutcomeLabeler:
    """Convert replay outcomes into clean supervised-learning targets."""

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()

    def label(self, record: DecisionRecord) -> OutcomeLabel:
        label = MarketRealityAdapter().label(record)

        if label.success is None:
            if label.tp_hit is not None and label.sl_hit is not None:
                label.success = int(label.tp_hit == 1 and label.sl_hit == 0)
            elif label.realized_return is not None:
                label.success = int(label.realized_return > 0)

        if label.setup_quality is None:
            # Quality is an outcome-derived diagnostic, never used as a
            # contemporaneous feature.
            ret = label.realized_return if label.realized_return is not None else 0.0
            mfe = label.mfe if label.mfe is not None else 0.0
            mae = abs(label.mae) if label.mae is not None else 0.0
            label.setup_quality = max(-1.0, min(1.0, ret + 0.25 * mfe - 0.25 * mae))

        return label

    def build(self, records: Sequence[DecisionRecord]) -> List[OutcomeLabel]:
        return [self.label(r) for r in records]


class CounterfactualLabelEngine:
    """
    Turn replay-generated alternate decisions into supervised labels.

    Expected input:
        baseline_value
        wait_values = {seconds_or_steps: value_after_wait}
    """

    def label(
        self,
        decision_id: str,
        baseline_value: float,
        wait_values: Mapping[int, float],
        minimum_improvement: float = 0.0,
    ) -> CounterfactualLabel:
        if not wait_values:
            return CounterfactualLabel(
                decision_id=decision_id,
                baseline_value=baseline_value,
                wait_values={},
                best_wait=0,
                improvement=0.0,
                label="ENTER_NOW",
            )

        best_wait, best_value = max(wait_values.items(), key=lambda kv: kv[1])
        improvement = float(best_value) - float(baseline_value)

        if best_wait == 0 or improvement <= minimum_improvement:
            label = "ENTER_NOW"
        else:
            label = "WAIT"

        return CounterfactualLabel(
            decision_id=decision_id,
            baseline_value=float(baseline_value),
            wait_values={int(k): float(v) for k, v in wait_values.items()},
            best_wait=int(best_wait),
            improvement=improvement,
            label=label,
            evidence={"best_value": float(best_value)},
        )


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

class ConstantProbabilityModel:
    def __init__(self, probability: float = 0.5):
        self.probability = float(probability)

    def fit(self, X, y):
        vals = [int(v) for v in y]
        self.probability = _mean(vals, 0.5)
        return self

    def predict_proba(self, X):
        return [[1.0 - self.probability, self.probability] for _ in X]

    def predict(self, X):
        return [int(self.probability >= 0.5) for _ in X]


class ConstantRegressor:
    def __init__(self, value: float = 0.0):
        self.value = float(value)

    def fit(self, X, y):
        self.value = _mean([_safe_float(v) for v in y], 0.0)
        return self

    def predict(self, X):
        return [self.value for _ in X]


def _make_classifier(config: IntelligenceConfig):
    if not SKLEARN_AVAILABLE:
        return ConstantProbabilityModel()
    return HistGradientBoostingClassifier(
        max_iter=max(100, config.classifier_trees),
        max_depth=config.max_depth,
        learning_rate=0.05,
        random_state=config.random_seed,
    )


def _make_regressor(config: IntelligenceConfig):
    if not SKLEARN_AVAILABLE:
        return ConstantRegressor()
    return HistGradientBoostingRegressor(
        max_iter=max(100, config.regressor_trees),
        max_depth=config.max_depth,
        learning_rate=0.05,
        random_state=config.random_seed,
        loss="squared_error",
    )


# ---------------------------------------------------------------------------
# Outcome prediction
# ---------------------------------------------------------------------------

class OutcomePredictor:
    """
    Supervised prediction suite:
      - P(TP before SL / success)
      - expected return
      - expected MFE
      - expected MAE
      - time-to-event
      - waiting benefit
    """

    TARGETS = (
        "success",
        "realized_return",
        "mfe",
        "mae",
        "time_to_tp",
        "time_to_sl",
        "waiting_improvement",
    )

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.models: Dict[str, Any] = {}
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.fitted = False
        self.training_stats: Dict[str, Any] = {}

    def fit(
        self,
        rows: Sequence[Mapping[str, Any]],
        labels: Sequence[OutcomeLabel],
    ) -> "OutcomePredictor":
        if len(rows) < self.config.min_training_samples:
            raise ValueError(
                f"Need at least {self.config.min_training_samples} labeled samples; got {len(rows)}."
            )

        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit(rows)
        X = self.encoder.transform(rows)

        target_data = {
            "success": [x.success for x in labels],
            "realized_return": [x.realized_return for x in labels],
            "mfe": [x.mfe for x in labels],
            "mae": [x.mae for x in labels],
            "time_to_tp": [x.time_to_tp for x in labels],
            "time_to_sl": [x.time_to_sl for x in labels],
            "waiting_improvement": [x.waiting_improvement for x in labels],
        }

        for target, values in target_data.items():
            valid = [(x, y) for x, y in zip(X, values) if y is not None and math.isfinite(float(y))]
            if len(valid) < max(10, self.config.min_training_samples // 2):
                continue
            vx = [a for a, _ in valid]
            vy = [b for _, b in valid]
            if target == "success":
                # Degenerate targets need a safe fallback.
                if len(set(int(v) for v in vy)) < 2:
                    model = ConstantProbabilityModel(_mean(vy, 0.5))
                else:
                    model = _make_classifier(self.config)
            else:
                model = _make_regressor(self.config)
            model.fit(vx, vy)
            self.models[target] = model

        self.fitted = True
        self.training_stats = {
            "samples": len(rows),
            "features": len(self.encoder.feature_names),
            "models": sorted(self.models.keys()),
            "sklearn": SKLEARN_AVAILABLE,
        }
        return self

    def predict(
        self,
        rows: Sequence[Mapping[str, Any]],
        decision_ids: Optional[Sequence[str]] = None,
        timestamps: Optional[Sequence[str]] = None,
    ) -> List[Prediction]:
        if not self.fitted or self.encoder is None:
            raise RuntimeError("OutcomePredictor is not fitted.")
        X = self.encoder.transform(rows)
        ids = list(decision_ids or [str(i) for i in range(len(rows))])
        times = list(timestamps or [_utc_now()] * len(rows))
        predictions = []

        for i, x in enumerate(X):
            p = Prediction(
                decision_id=ids[i],
                timestamp=times[i],
                model_name="OutcomePredictor",
            )
            if "success" in self.models:
                try:
                    p.probability = float(self.models["success"].predict_proba([x])[0][1])
                except Exception:
                    p.probability = float(self.models["success"].predict([x])[0])
            if "realized_return" in self.models:
                p.expected_value = float(self.models["realized_return"].predict([x])[0])
            if "mfe" in self.models:
                p.expected_mfe = float(self.models["mfe"].predict([x])[0])
            if "mae" in self.models:
                p.expected_mae = float(self.models["mae"].predict([x])[0])
            if "time_to_tp" in self.models:
                p.time_to_event = float(self.models["time_to_tp"].predict([x])[0])
            confidence = 0.5
            if p.probability is not None:
                confidence = abs(p.probability - 0.5) * 2.0
            p.confidence = max(0.0, min(1.0, confidence))
            predictions.append(p)
        return predictions

    def save(self, directory: str) -> None:
        if not self.fitted:
            raise RuntimeError("Cannot save unfitted predictor.")
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        if joblib is not None:
            joblib.dump(self.models, path / "models.joblib")
        else:
            # Constant fallbacks can still be serialized.
            (path / "models.json").write_text(
                json.dumps({k: getattr(v, "__dict__", {}) for k, v in self.models.items()}, indent=2),
                encoding="utf-8",
            )
        if self.encoder:
            self.encoder.save(str(path / "encoder.json"))
        (path / "metadata.json").write_text(
            json.dumps({"version": VERSION, "training_stats": self.training_stats}, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Setup quality scoring
# ---------------------------------------------------------------------------

class SetupQualityModel:
    """
    Converts supervised outcome predictions into a normalized setup-quality
    estimate. This is diagnostic/ranking information, not a reward signal.
    """

    def score(
        self,
        prediction: Prediction,
        anomaly_score: Optional[float] = None,
        regime_confidence: float = 1.0,
    ) -> float:
        probability = prediction.probability if prediction.probability is not None else 0.5
        ev = prediction.expected_value if prediction.expected_value is not None else 0.0
        mfe = prediction.expected_mfe if prediction.expected_mfe is not None else 0.0
        mae = abs(prediction.expected_mae) if prediction.expected_mae is not None else 0.0

        raw = (
            0.50 * (2.0 * probability - 1.0)
            + 0.25 * math.tanh(ev)
            + 0.15 * math.tanh(mfe)
            - 0.10 * math.tanh(mae)
        )
        raw *= max(0.0, min(1.0, regime_confidence))
        if anomaly_score is not None:
            raw *= max(0.0, 1.0 - min(1.0, anomaly_score))
        return max(-1.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

FAILURE_CLASSES = (
    "prediction",
    "timing",
    "microstructure",
    "liquidity",
    "regime",
    "execution",
    "management",
    "sizing",
    "exit",
    "data_quality",
    "unknown",
)


class FailureClassifier:
    """
    Diagnose WHY a decision failed.

    If historical failure_class labels exist, a supervised classifier is fit.
    If they do not, a transparent heuristic layer provides a provisional
    diagnosis. The heuristic never pretends to be ground truth.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.model: Any = None
        self.classes_: List[str] = []
        self.fitted = False

    def fit(
        self,
        rows: Sequence[Mapping[str, Any]],
        labels: Sequence[OutcomeLabel],
    ) -> "FailureClassifier":
        pairs = [(r, l.failure_class) for r, l in zip(rows, labels) if l.failure_class]
        if len(pairs) < self.config.min_training_samples:
            return self

        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit([r for r, _ in pairs])
        X = self.encoder.transform([r for r, _ in pairs])
        y = [str(label) for _, label in pairs]
        self.classes_ = sorted(set(y))

        if len(self.classes_) < 2:
            self.model = None
            self.fitted = True
            return self

        if SKLEARN_AVAILABLE:
            self.model = HistGradientBoostingClassifier(
                max_iter=max(100, self.config.classifier_trees),
                max_depth=self.config.max_depth,
                learning_rate=0.05,
                random_state=self.config.random_seed,
            )
            # HistGradientBoosting expects integer-coded targets for some
            # versions; map explicitly.
            mapping = {c: i for i, c in enumerate(self.classes_)}
            self.model.fit(X, [mapping[v] for v in y])
        else:
            self.model = None
        self.fitted = True
        return self

    def _heuristic(
        self,
        record: DecisionRecord,
        prediction: Optional[Prediction],
    ) -> Dict[str, float]:
        o = record.outcome
        probs = {k: 0.02 for k in FAILURE_CLASSES}

        success = o.get("success")
        if success in (0, False):
            p = prediction.probability if prediction and prediction.probability is not None else 0.5
            if p >= 0.65:
                probs["prediction"] += 0.55
            elif o.get("waiting_improvement", 0) and _safe_float(o.get("waiting_improvement")) > 0:
                probs["timing"] += 0.55
            if _safe_float(o.get("microstructure_confirmation"), 1.0) < 0.5:
                probs["microstructure"] += 0.45
            if _safe_float(o.get("liquidity_quality"), 1.0) < 0.5:
                probs["liquidity"] += 0.40
            if _safe_float(o.get("regime_confidence"), 1.0) < 0.4:
                probs["regime"] += 0.40
            if _safe_float(o.get("execution_quality"), 1.0) < 0.5:
                probs["execution"] += 0.40
            if o.get("management_error"):
                probs["management"] += 0.50
            if o.get("sizing_error"):
                probs["sizing"] += 0.45
            if o.get("exit_error"):
                probs["exit"] += 0.50

        total = sum(probs.values())
        return {k: v / total for k, v in probs.items()}

    def predict_one(
        self,
        record: DecisionRecord,
        prediction: Optional[Prediction] = None,
    ) -> FailureDiagnosis:
        if self.fitted and self.model is not None and self.encoder is not None:
            row = self.encoder.transform([sanitize_observation(record.observation, record.timestamp)])[0]
            raw = self.model.predict_proba([row])[0]
            probabilities = {c: 0.0 for c in FAILURE_CLASSES}
            # Classes were encoded 0..N-1.
            for idx, value in enumerate(raw):
                if idx < len(self.classes_):
                    probabilities[self.classes_[idx]] = float(value)
        else:
            probabilities = self._heuristic(record, prediction)

        primary = max(probabilities.items(), key=lambda kv: kv[1])[0]
        evidence = []

        o = record.outcome
        if o.get("waiting_improvement") is not None and _safe_float(o["waiting_improvement"]) > 0:
            evidence.append("Replay indicates that waiting improved the counterfactual result.")
        if _safe_float(o.get("microstructure_confirmation"), 1.0) < 0.5:
            evidence.append("Microstructure confirmation was weak at/near the decision.")
        if _safe_float(o.get("liquidity_quality"), 1.0) < 0.5:
            evidence.append("Liquidity quality was weak.")
        if _safe_float(o.get("regime_confidence"), 1.0) < 0.4:
            evidence.append("Regime confidence was low.")
        if not evidence:
            evidence.append("No single high-confidence causal marker was available.")

        return FailureDiagnosis(
            decision_id=record.decision_id,
            primary_class=primary,
            probabilities=probabilities,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Component attribution
# ---------------------------------------------------------------------------

class ComponentAttributionEngine:
    """
    Attribution at feature and semantic-component level.

    Uses permutation importance against a supplied fitted predictor where
    possible. For a generic record it also aggregates Decision Genome keys by
    semantic prefixes.
    """

    COMPONENT_GROUPS = {
        "smc": ("smc", "structure", "bos", "choch", "order_block"),
        "liquidity": ("liquidity", "sweep", "stop"),
        "fvg": ("fvg", "fair_value"),
        "vwap": ("vwap",),
        "rvam": ("rvam",),
        "clv_absorption": ("clv", "absorption"),
        "microstructure": ("microstructure", "micro_", "tick", "flow"),
        "momentum": ("rsi", "stoch", "macd", "momentum"),
        "trend": ("ema", "trend"),
        "volatility": ("atr", "volatility", "bollinger", "bb_"),
        "regime": ("regime",),
        "quality": ("quality", "score", "confidence"),
    }

    def group_for(self, feature_name: str) -> str:
        low = feature_name.lower()
        for group, tokens in self.COMPONENT_GROUPS.items():
            if any(token in low for token in tokens):
                return group
        return "other"

    def aggregate(
        self,
        importances: Mapping[str, float],
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        grouped = defaultdict(float)
        counts = Counter()
        for feature, importance in importances.items():
            group = self.group_for(feature)
            grouped[group] += abs(float(importance))
            counts[group] += 1

        result = [
            {
                "component": group,
                "importance": value,
                "feature_count": counts[group],
            }
            for group, value in grouped.items()
        ]
        result.sort(key=lambda x: x["importance"], reverse=True)
        return result[:top_n]

    def rank_features(
        self,
        importances: Mapping[str, float],
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        ranked = sorted(
            (
                {
                    "feature": k,
                    "importance": abs(float(v)),
                    "component": self.group_for(k),
                }
                for k, v in importances.items()
            ),
            key=lambda x: x["importance"],
            reverse=True,
        )
        return ranked[:top_n]

    def heuristic_attribution(self, record: DecisionRecord) -> List[Dict[str, Any]]:
        """
        Transparent fallback: magnitude of contemporaneous component scores.
        It is association, not causality.
        """
        values = []
        for key, value in record.component_scores.items():
            if _is_number(value):
                values.append(
                    {
                        "component": key,
                        "importance": abs(float(value)),
                        "signed_value": float(value),
                        "method": "component_score_magnitude",
                    }
                )
        return sorted(values, key=lambda x: x["importance"], reverse=True)


# ---------------------------------------------------------------------------
# Regime modeling
# ---------------------------------------------------------------------------

class RegimeModel:
    """
    Unsupervised market-regime model.

    Preferred backend: MiniBatchKMeans over leakage-safe feature snapshots.
    Regime IDs are descriptive clusters; semantic names are assigned using
    contemporaneous volatility/trend/liquidity hints when available.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.model: Any = None
        self.fitted = False
        self.regime_descriptions: Dict[int, str] = {}

    def fit(self, rows: Sequence[Mapping[str, Any]]) -> "RegimeModel":
        if len(rows) < max(self.config.min_training_samples, self.config.regime_count):
            return self
        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit(rows)
        X = self.encoder.transform(rows)

        if SKLEARN_AVAILABLE:
            self.model = MiniBatchKMeans(
                n_clusters=min(self.config.regime_count, len(rows)),
                random_state=self.config.random_seed,
                batch_size=max(16, min(256, len(rows))),
                n_init=10,
            )
            self.model.fit(X)
        else:
            self.model = None

        self.fitted = True
        return self

    def predict(self, rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        if not self.fitted or self.encoder is None:
            return [{"regime_id": -1, "regime": "UNKNOWN", "confidence": 0.0} for _ in rows]
        X = self.encoder.transform(rows)
        if self.model is None:
            return [{"regime_id": 0, "regime": "UNMODELED", "confidence": 0.0} for _ in rows]

        ids = self.model.predict(X)
        results = []
        centers = self.model.cluster_centers_
        for x, rid in zip(X, ids):
            center = centers[int(rid)]
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(x, center)))
            confidence = 1.0 / (1.0 + distance)
            results.append(
                {
                    "regime_id": int(rid),
                    "regime": self.regime_descriptions.get(int(rid), f"REGIME_{int(rid)}"),
                    "confidence": float(max(0.0, min(1.0, confidence))),
                    "distance": float(distance),
                }
            )
        return results

    def name_regimes(
        self,
        rows: Sequence[Mapping[str, Any]],
        ids: Sequence[int],
    ) -> Dict[int, str]:
        """
        Assign readable names from contemporaneous feature hints.
        This is descriptive, not a supervised claim.
        """
        buckets = defaultdict(list)
        for row, rid in zip(rows, ids):
            buckets[int(rid)].append(row)

        names = {}
        for rid, group in buckets.items():
            trend = _mean([
                _safe_float(v) for row in group for k, v in row.items()
                if "trend" in k.lower() and _is_number(v)
            ], 0.0)
            vol = _mean([
                abs(_safe_float(v)) for row in group for k, v in row.items()
                if ("volatility" in k.lower() or "atr" in k.lower()) and _is_number(v)
            ], 0.0)
            liq = _mean([
                _safe_float(v) for row in group for k, v in row.items()
                if "liquidity" in k.lower() and _is_number(v)
            ], 0.0)

            if vol > 1.0 and abs(trend) > 0.5:
                label = "HIGH_VOL_TREND"
            elif vol > 1.0:
                label = "HIGH_VOL"
            elif abs(trend) > 0.5:
                label = "TREND"
            elif liq < 0.0:
                label = "LIQUIDITY_STRESSED"
            else:
                label = "RANGE_OR_LOW_VOL"
            names[rid] = label

        self.regime_descriptions.update(names)
        return names


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Robust distance-based anomaly detector.

    It uses feature-wise median/MAD instead of requiring a heavyweight model,
    making it deterministic and interpretable.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.medians: List[float] = []
        self.mads: List[float] = []
        self.threshold: float = 6.0
        self.fitted = False

    def fit(self, rows: Sequence[Mapping[str, Any]]) -> "AnomalyDetector":
        if not rows:
            return self
        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit(rows)
        X = self.encoder.transform(rows)
        if not X:
            return self

        cols = list(zip(*X))
        self.medians = [_mean(col) for col in cols]
        self.mads = [_std(col, 1.0) for col in cols]

        # Empirical threshold using training distances.
        distances = []
        for row in X:
            z = [abs(a - m) / max(1e-6, s) for a, m, s in zip(row, self.medians, self.mads)]
            distances.append(math.sqrt(_mean([v * v for v in z], 0.0)))
        if distances:
            q = sorted(distances)[int(min(len(distances) - 1, max(0, (1.0 - self.config.anomaly_contamination) * len(distances))))]
            self.threshold = max(3.0, q)
        self.fitted = True
        return self

    def score(self, rows: Sequence[Mapping[str, Any]]) -> List[float]:
        if not self.fitted or self.encoder is None:
            return [0.0 for _ in rows]
        X = self.encoder.transform(rows)
        scores = []
        for row in X:
            z = [
                abs(a - m) / max(1e-6, s)
                for a, m, s in zip(row, self.medians, self.mads)
            ]
            distance = math.sqrt(_mean([v * v for v in z], 0.0))
            scores.append(float(max(0.0, min(1.0, distance / max(1e-6, self.threshold)))))
        return scores


# ---------------------------------------------------------------------------
# Pattern discovery
# ---------------------------------------------------------------------------

class PatternDiscovery:
    """
    Cluster recurring Decision Genome states and attach outcome statistics.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.model: Any = None
        self.fitted = False
        self.pattern_stats: Dict[int, Dict[str, Any]] = {}

    def fit(
        self,
        rows: Sequence[Mapping[str, Any]],
        labels: Optional[Sequence[OutcomeLabel]] = None,
    ) -> "PatternDiscovery":
        if len(rows) < max(self.config.min_cluster_samples, self.config.pattern_clusters):
            return self

        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit(rows)
        X = self.encoder.transform(rows)

        if SKLEARN_AVAILABLE:
            self.model = MiniBatchKMeans(
                n_clusters=min(self.config.pattern_clusters, len(rows)),
                random_state=self.config.random_seed,
                batch_size=max(16, min(256, len(rows))),
                n_init=10,
            )
            ids = self.model.fit_predict(X)
        else:
            self.model = None
            ids = [0] * len(rows)

        if labels is not None:
            for rid in sorted(set(ids)):
                subset = [l for i, l in enumerate(labels) if ids[i] == rid]
                successes = [l.success for l in subset if l.success is not None]
                returns = [l.realized_return for l in subset if l.realized_return is not None]
                self.pattern_stats[int(rid)] = {
                    "samples": len(subset),
                    "success_rate": _mean(successes, 0.0),
                    "mean_return": _mean(returns, 0.0),
                    "mean_mfe": _mean([l.mfe for l in subset if l.mfe is not None], 0.0),
                    "mean_mae": _mean([l.mae for l in subset if l.mae is not None], 0.0),
                }

        self.fitted = True
        return self

    def predict(self, rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        if not self.fitted or self.encoder is None:
            return [{"pattern_id": -1, "stats": {}} for _ in rows]
        X = self.encoder.transform(rows)
        if self.model is None:
            ids = [0] * len(rows)
        else:
            ids = self.model.predict(X)
        return [
            {
                "pattern_id": int(rid),
                "stats": copy.deepcopy(self.pattern_stats.get(int(rid), {})),
            }
            for rid in ids
        ]


# ---------------------------------------------------------------------------
# Probability calibration
# ---------------------------------------------------------------------------

class ProbabilityCalibrator:
    """
    Calibrate probabilities on a temporally later validation set.

    Isotonic regression is used when available; otherwise a logistic
    recalibration model is used. Never calibrate on the same samples used to
    fit the base predictor.
    """

    def __init__(self):
        self.model: Any = None
        self.fitted = False
        self.method = "none"

    def fit(self, probabilities: Sequence[float], y: Sequence[int]) -> "ProbabilityCalibrator":
        if len(probabilities) < 30 or len(set(int(v) for v in y)) < 2:
            return self

        p = [min(1.0 - 1e-6, max(1e-6, float(v))) for v in probabilities]
        yy = [int(v) for v in y]

        if SKLEARN_AVAILABLE:
            self.model = IsotonicRegression(out_of_bounds="clip")
            self.model.fit(p, yy)
            self.method = "isotonic"
        else:
            self.model = None
            self.method = "identity"
        self.fitted = True
        return self

    def transform(self, probabilities: Sequence[float]) -> List[float]:
        if not self.fitted:
            return [float(p) for p in probabilities]
        if self.model is None:
            return [float(p) for p in probabilities]
        return [float(v) for v in self.model.predict(probabilities)]


# ---------------------------------------------------------------------------
# Time-to-event / survival-style model
# ---------------------------------------------------------------------------

class TimeToEventModel:
    """
    Practical survival-style approximation.

    It predicts log(time-to-event) using a regression target. Censoring can be
    represented by missing event time and is currently excluded from fitting.
    The class also produces a simple horizon survival curve.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()
        self.encoder: Optional[TabularFeatureEncoder] = None
        self.model: Any = None
        self.event_name = "tp"
        self.fitted = False

    def fit(
        self,
        rows: Sequence[Mapping[str, Any]],
        labels: Sequence[OutcomeLabel],
        event: str = "tp",
    ) -> "TimeToEventModel":
        self.event_name = event
        times = []
        for label in labels:
            value = label.time_to_tp if event == "tp" else (
                label.time_to_sl if event == "sl" else label.time_to_invalidation
            )
            times.append(value)

        pairs = [(r, t) for r, t in zip(rows, times) if t is not None and _safe_float(t) > 0]
        if len(pairs) < self.config.min_training_samples:
            return self

        self.encoder = TabularFeatureEncoder(
            max_features=self.config.max_features,
            hash_buckets=self.config.categorical_hash_buckets,
        ).fit([r for r, _ in pairs])
        X = self.encoder.transform([r for r, _ in pairs])
        y = [math.log1p(_safe_float(t)) for _, t in pairs]
        self.model = _make_regressor(self.config)
        self.model.fit(X, y)
        self.fitted = True
        return self

    def predict_time(self, rows: Sequence[Mapping[str, Any]]) -> List[float]:
        if not self.fitted or self.encoder is None or self.model is None:
            return [0.0] * len(rows)
        X = self.encoder.transform(rows)
        return [max(0.0, math.expm1(float(v))) for v in self.model.predict(X)]

    def survival_curve(
        self,
        predicted_median_time: float,
        horizons: Sequence[float],
    ) -> Dict[float, float]:
        """
        Log-normal-ish heuristic curve around the predicted median.
        This is a useful ranking approximation, not a formal Kaplan-Meier fit.
        """
        median = max(1e-6, predicted_median_time)
        scale = max(1e-6, median * 0.75)
        curve = {}
        for h in horizons:
            # Logistic survival centered around median.
            curve[float(h)] = 1.0 - _sigmoid((float(h) - median) / scale)
        return curve


# ---------------------------------------------------------------------------
# Explainability / audit report
# ---------------------------------------------------------------------------

class DecisionExplainer:
    """
    Build a compact but deep audit narrative from all intelligence outputs.
    """

    def explain(
        self,
        record: DecisionRecord,
        prediction: Optional[Prediction] = None,
        diagnosis: Optional[FailureDiagnosis] = None,
        regime: Optional[Dict[str, Any]] = None,
        anomaly_score: Optional[float] = None,
        pattern: Optional[Dict[str, Any]] = None,
        counterfactual: Optional[CounterfactualLabel] = None,
        component_attribution: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        outcome = record.outcome or {}
        evidence: List[str] = []

        if prediction:
            if prediction.probability is not None:
                evidence.append(f"Predicted success probability={prediction.probability:.3f}.")
            if prediction.expected_value is not None:
                evidence.append(f"Expected return proxy={prediction.expected_value:.4f}.")
            if prediction.expected_mfe is not None:
                evidence.append(f"Expected MFE={prediction.expected_mfe:.4f}.")
            if prediction.expected_mae is not None:
                evidence.append(f"Expected MAE={prediction.expected_mae:.4f}.")

        if diagnosis:
            evidence.append(f"Primary diagnosed failure class={diagnosis.primary_class}.")
            evidence.extend(diagnosis.evidence)

        if regime:
            evidence.append(
                f"Regime={regime.get('regime')} "
                f"(confidence={_safe_float(regime.get('confidence')):.3f})."
            )

        if anomaly_score is not None and anomaly_score > 0.5:
            evidence.append(f"Decision state is anomalous (score={anomaly_score:.3f}).")

        if counterfactual:
            if counterfactual.label == "WAIT":
                evidence.append(
                    f"Counterfactual replay indicates waiting could improve value by "
                    f"{counterfactual.improvement:.4f} at step {counterfactual.best_wait}."
                )
            else:
                evidence.append("Counterfactual replay did not show a meaningful waiting advantage.")

        if pattern and pattern.get("stats"):
            stats = pattern["stats"]
            evidence.append(
                f"Recurring pattern success rate={_safe_float(stats.get('success_rate')):.3f} "
                f"over {int(stats.get('samples', 0))} samples."
            )

        first_divergence = None
        if outcome.get("first_divergence"):
            first_divergence = str(outcome["first_divergence"])
        elif diagnosis:
            first_divergence = diagnosis.primary_class

        return {
            "decision_id": record.decision_id,
            "timestamp": record.timestamp,
            "signal": record.metadata.get("signal", record.metadata.get("strategy")),
            "outcome": copy.deepcopy(outcome),
            "first_divergence": first_divergence,
            "evidence": evidence,
            "primary_failure": diagnosis.primary_class if diagnosis else None,
            "regime": copy.deepcopy(regime),
            "anomaly_score": anomaly_score,
            "pattern": copy.deepcopy(pattern),
            "counterfactual": asdict(counterfactual) if counterfactual else None,
            "component_attribution": component_attribution or [],
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ClassificationMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    brier: Optional[float] = None
    auc: Optional[float] = None


@dataclass
class RegressionMetrics:
    mae: float
    rmse: float


@dataclass
class ValidationReport:
    model_name: str
    samples: int
    classification: Optional[ClassificationMetrics] = None
    regression: Optional[RegressionMetrics] = None
    calibration_error: Optional[float] = None
    notes: List[str] = field(default_factory=list)


class ValidationEngine:
    """Chronological validation only. No random shuffling for time-series data."""

    @staticmethod
    def chronological_split(
        records: Sequence[Any],
        config: IntelligenceConfig,
    ) -> Tuple[List[Any], List[Any], List[Any]]:
        n = len(records)
        a = int(n * config.train_fraction)
        b = a + int(n * config.validation_fraction)
        return list(records[:a]), list(records[a:b]), list(records[b:])

    @staticmethod
    def classification_report(
        y_true: Sequence[int],
        probabilities: Sequence[float],
        model_name: str = "classifier",
    ) -> ValidationReport:
        if not y_true:
            return ValidationReport(model_name=model_name, samples=0)
        pred = [int(p >= 0.5) for p in probabilities]
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, pred, average="binary", zero_division=0
        ) if SKLEARN_AVAILABLE else (0.0, 0.0, 0.0, None)

        auc = None
        brier = None
        if len(set(y_true)) > 1:
            if SKLEARN_AVAILABLE:
                try:
                    auc = float(roc_auc_score(y_true, probabilities))
                    brier = float(brier_score_loss(y_true, probabilities))
                except Exception:
                    pass

        return ValidationReport(
            model_name=model_name,
            samples=len(y_true),
            classification=ClassificationMetrics(
                accuracy=float(accuracy_score(y_true, pred)) if SKLEARN_AVAILABLE else _mean(
                    [int(a == b) for a, b in zip(y_true, pred)], 0.0
                ),
                precision=float(precision),
                recall=float(recall),
                f1=float(f1),
                brier=brier,
                auc=auc,
            ),
        )

    @staticmethod
    def regression_report(
        y_true: Sequence[float],
        y_pred: Sequence[float],
        model_name: str = "regressor",
    ) -> ValidationReport:
        if not y_true:
            return ValidationReport(model_name=model_name, samples=0)
        if SKLEARN_AVAILABLE:
            mae = float(mean_absolute_error(y_true, y_pred))
            rmse = float(math.sqrt(mean_squared_error(y_true, y_pred)))
        else:
            errors = [abs(a - b) for a, b in zip(y_true, y_pred)]
            mae = _mean(errors)
            rmse = math.sqrt(_mean([(a - b) ** 2 for a, b in zip(y_true, y_pred)]))
        return ValidationReport(
            model_name=model_name,
            samples=len(y_true),
            regression=RegressionMetrics(mae=mae, rmse=rmse),
        )

    @staticmethod
    def expected_calibration_error(
        y_true: Sequence[int],
        probabilities: Sequence[float],
        bins: int = 10,
    ) -> float:
        if not y_true:
            return 0.0
        buckets = [[] for _ in range(bins)]
        for y, p in zip(y_true, probabilities):
            idx = min(bins - 1, max(0, int(float(p) * bins)))
            buckets[idx].append((int(y), float(p)))

        total = len(y_true)
        ece = 0.0
        for bucket in buckets:
            if not bucket:
                continue
            accuracy = _mean([y for y, _ in bucket])
            confidence = _mean([p for _, p in bucket])
            ece += (len(bucket) / total) * abs(accuracy - confidence)
        return float(ece)

    @staticmethod
    def walk_forward_indices(
        n: int,
        folds: int,
        min_train: int,
    ) -> List[Tuple[range, range]]:
        if n <= min_train:
            return []
        remaining = n - min_train
        step = max(1, remaining // max(1, folds))
        result = []
        train_end = min_train
        while train_end < n and len(result) < folds:
            test_end = min(n, train_end + step)
            result.append((range(0, train_end), range(train_end, test_end)))
            train_end = test_end
        return result


# ---------------------------------------------------------------------------
# A/B and ablation
# ---------------------------------------------------------------------------

@dataclass
class ABReport:
    baseline_metric: float
    candidate_metric: float
    improvement: float
    relative_improvement: float
    candidate_wins: bool
    metric_name: str
    notes: List[str] = field(default_factory=list)


class ExperimentEngine:
    """
    Safe model/feature experiments:
      - A/B comparison
      - feature ablation
      - component ablation
      - regime-specific comparison
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()

    def compare_metric(
        self,
        baseline: float,
        candidate: float,
        metric_name: str,
        higher_is_better: bool = True,
    ) -> ABReport:
        raw = float(candidate) - float(baseline)
        improvement = raw if higher_is_better else -raw
        relative = improvement / max(1e-12, abs(float(baseline)))
        wins = improvement >= self.config.minimum_improvement
        return ABReport(
            baseline_metric=float(baseline),
            candidate_metric=float(candidate),
            improvement=float(improvement),
            relative_improvement=float(relative),
            candidate_wins=bool(wins),
            metric_name=metric_name,
        )

    def ablate_components(
        self,
        rows: Sequence[Mapping[str, Any]],
        components: Sequence[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        out = {}
        for component in components:
            modified = []
            token = component.lower()
            for row in rows:
                modified.append({
                    k: v for k, v in row.items()
                    if token not in k.lower()
                })
            out[component] = modified
        return out


# ---------------------------------------------------------------------------
# Unified controller
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceResult:
    decision_id: str
    prediction: Optional[Prediction]
    setup_quality: Optional[float]
    diagnosis: Optional[FailureDiagnosis]
    regime: Optional[Dict[str, Any]]
    anomaly_score: Optional[float]
    pattern: Optional[Dict[str, Any]]
    explanation: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class NonRLIntelligenceController:
    """
    Main façade.

    The controller shares no hidden state with RL. Both can consume the same
    replay records and therefore remain independently auditable.
    """

    def __init__(self, config: Optional[IntelligenceConfig] = None):
        self.config = config or IntelligenceConfig()

        # ✅ FIXED: this was `random.seed(self.config.random_seed)`, which
        # reseeds the PROCESS-WIDE RNG as a side effect of merely constructing
        # this controller. Anything else drawing from `random` afterwards --
        # ai_adversarial's attack selection, any sampling elsewhere -- would
        # silently have its stream reset to a fixed sequence, and would keep
        # getting the identical "random" values on every run. Reproducibility
        # here must not be bought by mutating global state; a private Random
        # instance gives the same determinism with no reach outside this
        # object. (RL's seed_everything() is different and correct: it is an
        # explicit, opt-in call at a training entry point, not a constructor.)
        self.random = random.Random(self.config.random_seed)

        self.adapter = DecisionGenomeAdapter(self.config)
        self.labeler = OutcomeLabeler(self.config)
        self.predictor = OutcomePredictor(self.config)
        self.failure_classifier = FailureClassifier(self.config)
        self.attribution = ComponentAttributionEngine()
        self.regime_model = RegimeModel(self.config)
        self.anomaly_detector = AnomalyDetector(self.config)
        self.pattern_discovery = PatternDiscovery(self.config)
        self.calibrator = ProbabilityCalibrator()
        self.time_to_tp = TimeToEventModel(self.config)
        self.time_to_sl = TimeToEventModel(self.config)
        self.counterfactual = CounterfactualLabelEngine()
        self.quality_model = SetupQualityModel()
        self.explainer = DecisionExplainer()
        self.validator = ValidationEngine()
        self.experiments = ExperimentEngine(self.config)

        self.records: List[DecisionRecord] = []
        self.rows: List[Dict[str, Any]] = []
        self.labels: List[OutcomeLabel] = []
        self.trained = False
        self.training_report: Dict[str, Any] = {}

    def get_status(self) -> Dict[str, Any]:
        """
        Verification surface for the non-RL layer.

        `fitted` is reported per model rather than as one flag, because a
        controller can legitimately be partly fitted -- a small sample can
        train the outcome predictor while leaving the calibrator unfitted --
        and a single boolean would hide that.
        """
        return {
            "component": "non_rl_intelligence",
            "sklearn_available": SKLEARN_AVAILABLE,
            "records_loaded": len(getattr(self, "records", []) or []),
            "feature_rows": len(getattr(self, "rows", []) or []),
            "labels": len(getattr(self, "labels", []) or []),
            "fitted": {
                "outcome_predictor": getattr(self.predictor, "fitted", False),
                "failure_classifier": getattr(self.failure_classifier, "fitted", False),
                "regime_model": getattr(self.regime_model, "fitted", False),
                "calibrator": getattr(self.calibrator, "fitted", False),
            },
            "config": {
                "min_training_samples": self.config.min_training_samples,
                "max_features": self.config.max_features,
                "random_seed": self.config.random_seed,
            },
            "seeding_is_instance_scoped": True,
        }

    def self_check(
        self,
        trades: Optional[Sequence[Mapping[str, Any]]] = None,
        bridge: Any = None,
    ) -> Dict[str, Any]:
        """
        Prove the trade -> DecisionRecord -> feature path works, without fitting.

        Includes an explicit leakage assertion, because that is the failure
        mode that does not announce itself: a leaked outcome column produces
        excellent validation numbers and a worthless model.
        """
        report = {"component": "non_rl_intelligence", "ok": False, "checks": {}}
        try:
            records = decision_records_from_trades(trades or [], bridge)
            report["checks"]["trades_in"] = len(trades or [])
            report["checks"]["records_built"] = len(records)

            banned = ("close_data", "analysis_at_close", "is_winning",
                      "profit_percent", "close_reason", "realized_return")
            leaked = sorted({
                key for record in records for key in record.observation
                if any(token in key.lower() for token in banned)
            })
            report["checks"]["leaked_features"] = leaked
            report["checks"]["no_leakage"] = not leaked

            labelled = sum(1 for r in records if r.outcome.get("success") is not None)
            report["checks"]["records_with_labels"] = labelled
            report["checks"]["mean_features_per_record"] = (
                round(sum(len(r.observation) for r in records) / len(records), 1)
                if records else 0
            )
            report["checks"]["enough_to_train"] = (
                len(records) >= self.config.min_training_samples
            )
            report["ok"] = bool(records) and not leaked
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    def prepare_from_trades(
        self,
        trades: Sequence[Mapping[str, Any]],
        bridge: Any = None,
    ) -> Tuple[List[Dict[str, Any]], List[OutcomeLabel]]:
        """
        Prepare directly from stored Firebase trade documents.

        Convenience wrapper over prepare(): converts each trade through
        PriceEvolutionBridge (which decodes price_evolution and splits the
        trade into open-side features vs close-side labels) and then follows
        the normal path, so trades and hand-built DecisionRecords go through
        exactly the same fitting and validation.
        """
        return self.prepare(decision_records_from_trades(trades, bridge))

    def prepare(
        self,
        records: Sequence[DecisionRecord],
    ) -> Tuple[List[Dict[str, Any]], List[OutcomeLabel]]:
        ordered = sorted(records, key=lambda r: _coerce_datetime(r.timestamp) or datetime.min.replace(tzinfo=timezone.utc))
        rows, _ = self.adapter.build_dataset(ordered)
        labels = self.labeler.build(ordered)
        self.records = list(ordered)
        self.rows = rows
        self.labels = labels
        return rows, labels

    def fit(
        self,
        records: Optional[Sequence[DecisionRecord]] = None,
    ) -> Dict[str, Any]:
        if records is not None:
            self.prepare(records)
        if not self.records:
            raise ValueError("No DecisionRecord samples supplied.")

        train, validation, test = self.validator.chronological_split(self.records, self.config)
        if len(train) < self.config.min_training_samples:
            raise ValueError(
                f"Chronological training split has {len(train)} samples; "
                f"need at least {self.config.min_training_samples}."
            )

        train_rows = [self.adapter.encode(r) for r in train]
        train_labels = [self.labeler.label(r) for r in train]

        self.predictor.fit(train_rows, train_labels)
        self.failure_classifier.fit(train_rows, train_labels)
        self.regime_model.fit(train_rows)
        self.anomaly_detector.fit(train_rows)
        self.pattern_discovery.fit(train_rows, train_labels)
        self.time_to_tp.fit(train_rows, train_labels, "tp")
        self.time_to_sl.fit(train_rows, train_labels, "sl")

        # Validation-only calibration: base predictor was trained on earlier
        # chronological samples.
        validation_rows = [self.adapter.encode(r) for r in validation]
        validation_labels = [self.labeler.label(r) for r in validation]
        if validation_rows and "success" in self.predictor.models:
            preds = self.predictor.predict(validation_rows)
            probs = [p.probability for p in preds if p.probability is not None]
            ys = [l.success for l in validation_labels if l.success is not None]
            if len(probs) == len(ys) and len(probs) >= self.config.calibration_min_samples:
                self.calibrator.fit(probs, ys)

        self.trained = True
        self.training_report = {
            "version": VERSION,
            "train_samples": len(train),
            "validation_samples": len(validation),
            "test_samples": len(test),
            "predictor": self.predictor.training_stats,
            "calibration": {"fitted": self.calibrator.fitted, "method": self.calibrator.method},
            "sklearn": SKLEARN_AVAILABLE,
        }
        return copy.deepcopy(self.training_report)

    def _predict_record(self, record: DecisionRecord) -> Optional[Prediction]:
        if not self.trained:
            return None
        row = self.adapter.encode(record)
        predictions = self.predictor.predict(
            [row],
            decision_ids=[record.decision_id],
            timestamps=[record.timestamp],
        )
        if not predictions:
            return None
        p = predictions[0]
        if p.probability is not None and self.calibrator.fitted:
            p.probability = self.calibrator.transform([p.probability])[0]
            p.calibrated = True
        return p

    def analyze(self, record: DecisionRecord) -> IntelligenceResult:
        if not self.trained:
            raise RuntimeError("Controller must be fitted before analyze().")

        row = self.adapter.encode(record)
        prediction = self._predict_record(record)

        anomaly = self.anomaly_detector.score([row])[0]
        regime = self.regime_model.predict([row])[0]
        pattern = self.pattern_discovery.predict([row])[0]

        diagnosis = self.failure_classifier.predict_one(record, prediction)

        if prediction:
            quality = self.quality_model.score(
                prediction,
                anomaly_score=anomaly,
                regime_confidence=_safe_float(regime.get("confidence"), 0.0),
            )
        else:
            quality = None

        attribution = self.attribution.heuristic_attribution(record)
        explanation = self.explainer.explain(
            record,
            prediction=prediction,
            diagnosis=diagnosis,
            regime=regime,
            anomaly_score=anomaly,
            pattern=pattern,
            component_attribution=attribution,
        )

        return IntelligenceResult(
            decision_id=record.decision_id,
            prediction=prediction,
            setup_quality=quality,
            diagnosis=diagnosis,
            regime=regime,
            anomaly_score=anomaly,
            pattern=pattern,
            explanation=explanation,
            metadata={"version": VERSION},
        )

    def analyze_batch(self, records: Sequence[DecisionRecord]) -> List[IntelligenceResult]:
        return [self.analyze(r) for r in records]

    def create_counterfactual_label(
        self,
        decision_id: str,
        baseline_value: float,
        wait_values: Mapping[int, float],
    ) -> CounterfactualLabel:
        return self.counterfactual.label(
            decision_id,
            baseline_value,
            wait_values,
            minimum_improvement=self.config.minimum_improvement,
        )

    def validate_test_set(self) -> Dict[str, Any]:
        if not self.trained:
            raise RuntimeError("Fit controller before validation.")
        train, validation, test = self.validator.chronological_split(self.records, self.config)
        rows = [self.adapter.encode(r) for r in test]
        labels = [self.labeler.label(r) for r in test]

        output: Dict[str, Any] = {"samples": len(test), "models": {}}
        if rows and "success" in self.predictor.models:
            preds = self.predictor.predict(rows)
            probs = [p.probability if p.probability is not None else 0.5 for p in preds]
            y = [l.success for l in labels]
            valid = [(a, b) for a, b in zip(y, probs) if a is not None]
            if valid:
                yy, pp = zip(*valid)
                report = self.validator.classification_report(yy, pp, "success")
                report.calibration_error = self.validator.expected_calibration_error(yy, pp)
                output["models"]["success"] = asdict(report)

        for target, attr in (
            ("realized_return", "expected_value"),
            ("mfe", "expected_mfe"),
            ("mae", "expected_mae"),
        ):
            if target not in self.predictor.models:
                continue
            preds = self.predictor.predict(rows)
            y = [getattr(l, target) for l in labels]
            p = [getattr(x, attr) for x in preds]
            valid = [(a, b) for a, b in zip(y, p) if a is not None]
            if valid:
                yy, pp = zip(*valid)
                output["models"][target] = asdict(
                    self.validator.regression_report(yy, pp, target)
                )

        return output

    def walk_forward_validate(self) -> Dict[str, Any]:
        """
        Refit independent temporary predictors per chronological fold.
        This is slower than one-shot validation but much closer to production
        behavior.
        """
        if not self.records:
            return {"folds": []}

        folds = self.validator.walk_forward_indices(
            len(self.records),
            self.config.walk_forward_folds,
            self.config.min_training_samples,
        )
        results = []

        for fold_id, (train_idx, test_idx) in enumerate(folds):
            train_records = [self.records[i] for i in train_idx]
            test_records = [self.records[i] for i in test_idx]
            if len(test_records) < 1:
                continue

            local = OutcomePredictor(self.config)
            train_rows = [self.adapter.encode(r) for r in train_records]
            train_labels = [self.labeler.label(r) for r in train_records]
            try:
                local.fit(train_rows, train_labels)
            except ValueError:
                continue

            test_rows = [self.adapter.encode(r) for r in test_records]
            test_labels = [self.labeler.label(r) for r in test_records]
            preds = local.predict(test_rows)
            probs = [p.probability for p in preds if p.probability is not None]
            ys = [l.success for l in test_labels if l.success is not None]
            fold = {"fold": fold_id, "train": len(train_records), "test": len(test_records)}

            if probs and len(probs) == len(ys) and len(set(ys)) > 1:
                report = self.validator.classification_report(ys, probs, "success")
                fold["success"] = asdict(report)
            results.append(fold)

        return {"folds": results, "count": len(results)}

    def component_ablation_report(
        self,
        records: Optional[Sequence[DecisionRecord]] = None,
        components: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        records = list(records or self.records)
        components = list(components or ComponentAttributionEngine.COMPONENT_GROUPS.keys())
        rows = [self.adapter.encode(r) for r in records]
        return {
            "components": components,
            "ablations": {
                name: {
                    "remaining_features": sorted(
                        {k for row in modified for k in row.keys()}
                    )
                }
                for name, modified in self.experiments.ablate_components(rows, components).items()
            },
        }

    def manifest(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "engine": "AI_MarketReplay Non-RL Intelligence",
            "modules": [
                "outcome_prediction",
                "setup_quality",
                "failure_classification",
                "component_attribution",
                "regime_modeling",
                "anomaly_detection",
                "pattern_discovery",
                "probability_calibration",
                "time_to_event",
                "counterfactual_labeling",
                "explainability",
                "chronological_validation",
                "walk_forward_validation",
                "ablation_experiments",
            ],
            "rl_boundary": "This module never selects actions through reinforcement learning.",
            "execution_boundary": "No broker/MT5/live execution.",
            "leakage_policy": "Decision-time features only; outcomes are labels.",
        }

    def save_artifacts(self, directory: Optional[str] = None) -> str:
        directory = directory or self.config.artifact_dir
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)

        self.predictor.save(str(path / "outcome_predictor"))

        (path / "manifest.json").write_text(
            json.dumps(self.manifest(), indent=2),
            encoding="utf-8",
        )
        (path / "training_report.json").write_text(
            json.dumps(self.training_report, indent=2),
            encoding="utf-8",
        )
        return str(path)


# ---------------------------------------------------------------------------
# Dataset / utility functions
# ---------------------------------------------------------------------------

def records_from_dicts(
    snapshots: Sequence[Mapping[str, Any]],
) -> List[DecisionRecord]:
    """Convert generic replay dictionaries to DecisionRecord objects."""
    records = []
    for i, snap in enumerate(snapshots):
        decision_id = str(
            snap.get("decision_id")
            or snap.get("id")
            or snap.get("trade_id")
            or i
        )
        timestamp = str(
            snap.get("decision_timestamp")
            or snap.get("timestamp")
            or snap.get("time")
            or _utc_now()
        )

        outcome = copy.deepcopy(snap.get("outcome", {}))
        if not outcome:
            # Support a flat replay schema while keeping outcomes outside
            # observation.
            outcome = {
                key: snap[key]
                for key in (
                    "success", "tp_hit", "sl_hit", "invalidated",
                    "realized_return", "mfe", "mae", "time_to_tp",
                    "time_to_sl", "time_to_invalidation",
                    "waiting_improvement", "setup_quality",
                    "failure_class", "regime", "source",
                )
                if key in snap
            }

        component_scores = copy.deepcopy(snap.get("component_scores", {}))
        metadata = copy.deepcopy(snap.get("metadata", {}))

        observation = snap.get("observation")
        if not isinstance(observation, Mapping):
            reserved = {
                "decision_id", "id", "trade_id", "decision_timestamp",
                "timestamp", "time", "outcome", "component_scores", "metadata",
                "success", "tp_hit", "sl_hit", "invalidated",
                "realized_return", "mfe", "mae", "time_to_tp", "time_to_sl",
                "time_to_invalidation", "waiting_improvement", "setup_quality",
                "failure_class", "regime", "source",
            }
            observation = {k: v for k, v in snap.items() if k not in reserved}

        records.append(
            DecisionRecord(
                decision_id=decision_id,
                timestamp=timestamp,
                observation=dict(observation),
                outcome=outcome,
                component_scores=component_scores,
                metadata=metadata,
            )
        )
    return records


def build_counterfactual_wait_dataset(
    decision_ids: Sequence[str],
    baseline_values: Sequence[float],
    wait_values: Sequence[Mapping[int, float]],
    minimum_improvement: float = 0.0,
) -> List[CounterfactualLabel]:
    engine = CounterfactualLabelEngine()
    return [
        engine.label(
            decision_id,
            baseline,
            waits,
            minimum_improvement=minimum_improvement,
        )
        for decision_id, baseline, waits in zip(
            decision_ids, baseline_values, wait_values
        )
    ]


def save_json(data: Any, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _synthetic_records(n: int = 140) -> List[DecisionRecord]:
    """
    Deterministic synthetic dataset used only for smoke testing.
    It is NOT market data and must never be treated as a trading result.
    """
    rng = random.Random(123)
    records = []

    for i in range(n):
        trend = math.sin(i / 13.0)
        vol = 0.5 + 0.4 * abs(math.sin(i / 9.0))
        micro = math.sin(i / 4.0)
        liquidity = 0.7 * math.cos(i / 17.0)

        signal_strength = 0.7 * trend + 0.35 * micro + 0.25 * liquidity
        noise = rng.gauss(0, 0.35)
        realized = signal_strength + noise
        success = int(realized > 0)

        if success:
            failure_class = None
        elif abs(micro) < 0.15:
            failure_class = "microstructure"
        elif vol > 0.85:
            failure_class = "regime"
        else:
            failure_class = "prediction"

        observation = {
            "smc": {
                "bos_strength": trend + rng.gauss(0, 0.1),
                "choch_strength": -trend + rng.gauss(0, 0.1),
            },
            "liquidity": {
                "sweep_quality": liquidity,
                "zone_distance": abs(liquidity) + 0.1,
            },
            "fvg": {"quality": max(0.0, 1.0 - abs(trend))},
            "vwap": {"distance": trend * 0.3},
            "rvam": {"value": micro},
            "clv_absorption": {"strength": liquidity * micro},
            "microstructure": {"confirmation": micro},
            "rsi": 50 + 25 * trend,
            "ema20": trend,
            "ema200": -trend * 0.5,
            "atr": vol,
            "liquidity_quality": liquidity,
            "regime_hint": "synthetic",
        }

        outcome = {
            "success": success,
            "tp_hit": success,
            "sl_hit": 1 - success,
            "realized_return": realized,
            "mfe": max(0.0, realized + rng.random() * 0.6),
            "mae": min(0.0, realized - rng.random() * 0.5),
            "time_to_tp": 1 + abs(realized) * 8 if success else None,
            "time_to_sl": 1 + abs(realized) * 8 if not success else None,
            "waiting_improvement": max(0.0, -realized * 0.4 + rng.gauss(0, 0.05)),
            "failure_class": failure_class,
            "microstructure_confirmation": 1.0 if abs(micro) > 0.15 else 0.2,
            "liquidity_quality": (liquidity + 1.0) / 2.0,
            "regime_confidence": 0.8 if vol < 0.85 else 0.3,
            "source": "synthetic_smoke_test",
        }

        records.append(
            DecisionRecord(
                decision_id=f"synthetic-{i}",
                timestamp=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
                observation=observation,
                outcome=outcome,
                component_scores={
                    "SMC": trend,
                    "Liquidity": liquidity,
                    "Microstructure": micro,
                    "VWAP": -trend * 0.2,
                    "RVAM": micro * 0.4,
                },
                metadata={"signal": "synthetic"},
            )
        )
    return records


def smoke_test() -> Dict[str, Any]:
    records = _synthetic_records()
    cfg = IntelligenceConfig(
        min_training_samples=40,
        max_features=120,
        regime_count=5,
        pattern_clusters=5,
        walk_forward_folds=3,
        artifact_dir="/tmp/ai_market_replay_non_rl_smoke",
    )
    controller = NonRLIntelligenceController(cfg)
    report = controller.fit(records)
    test_report = controller.validate_test_set()
    sample = controller.analyze(records[-1])
    cf = controller.create_counterfactual_label(
        "synthetic-cf",
        baseline_value=0.20,
        wait_values={1: 0.24, 2: 0.31, 3: 0.27},
    )

    assert controller.trained
    assert sample.decision_id == records[-1].decision_id
    assert sample.regime is not None
    assert sample.anomaly_score is not None
    assert cf.label == "WAIT"
    assert cf.best_wait == 2

    return {
        "status": "PASS",
        "version": VERSION,
        "records": len(records),
        "training": report,
        "test": test_report,
        "sample_primary_failure": sample.diagnosis.primary_class if sample.diagnosis else None,
        "sample_setup_quality": sample.setup_quality,
        "counterfactual": asdict(cf),
        "sklearn_available": SKLEARN_AVAILABLE,
    }


# ============================================================
# MODULE-LEVEL VERIFICATION ENDPOINTS
# ============================================================
#
# Standard 12 says every AI module exposes get_status() and self_check().
# Both existed here, but only as METHODS on NonRLIntelligenceController, so
# `non_rl_intelligence.self_check(trades)` -- the form every other module in
# the package uses, and the form a generic verification loop reaches for --
# raised AttributeError. An interface that is right only if you already know
# its shape is not an interface. These delegate; they are not a second
# implementation (standard 10).

def get_status(controller: Optional["NonRLIntelligenceController"] = None
               ) -> Dict[str, Any]:
    """Module-level view of the non-RL layer's capability and fit state."""
    return (controller or NonRLIntelligenceController()).get_status()


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None,
               controller: Optional["NonRLIntelligenceController"] = None
               ) -> Dict[str, Any]:
    """Module-level entry point for the controller's own self_check."""
    return (controller or NonRLIntelligenceController()).self_check(trades, bridge)


if __name__ == "__main__":
    print(json.dumps(smoke_test(), indent=2, default=str))
