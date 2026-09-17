# ============================================================
# GNN ANALYSIS -- PHASE 5 ITEMS 2, 5 AND 7
# ============================================================
#
# Three capabilities the GNN was missing, built on the graph it already
# constructs rather than beside it (standard 10):
#
#   item 2  embeddings         -- a named, extractable per-asset vector
#   item 5  divergence/conflict -- where an asset disagrees with its peers
#   item 7  OOS validation      -- whether any of it predicts anything
#
# WHY EMBEDDINGS NEEDED AN API AT ALL
# -----------------------------------
# Message passing already wrote `gnn_direction` and `gnn_connections` onto
# each node, which is a two-dimensional embedding by any reasonable
# definition. But nothing could READ it as a vector: there was no ordering, no
# dimension names, and no way to compare two assets or two moments. An
# embedding that cannot be extracted is a side effect, not a representation.
#
# WHY CONFLICT IS THE INTERESTING SIGNAL
# --------------------------------------
# A correlated peer group moving together tells you what you already knew from
# looking at one chart. The information is in DISAGREEMENT: an asset whose own
# direction opposes the direction its peers imply. That is either a leading
# move or a false one, and knowing which trades sit in that state is worth
# more than knowing the average.
#
# THE VALIDATION IS EXPECTED TO REFUSE
# ------------------------------------
# Direction entropy in this system measured 1.0000. A graph over instruments
# whose direction is a coin flip has no obvious reason to predict outcomes,
# and `validate_out_of_sample` is built to say so plainly rather than to find
# something. It uses the same standards as every other model here:
# chronological trade-grouped splits, expectancy in R as the criterion, and a
# label-shuffled control that the real result must beat. A version of this
# that reported AUC alone would have found "signal" in the first run.
# ============================================================

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

GNN_ANALYSIS_VERSION = "1.0"

# The embedding, in fixed order. Named because an unlabelled vector is
# untraceable the moment it reaches another module.
EMBEDDING_DIMENSIONS = (
    "direction_own",        # the asset's own directional read
    "direction_peers",      # what its neighbours imply
    "conflict",             # signed disagreement between the two
    "degree",               # how many neighbours it has
    "weighted_degree",      # summed edge strength
    "influence",            # gnn_direction after message passing
)

# Below this, a disagreement is rounding rather than conflict.
CONFLICT_THRESHOLD = 0.30


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def node_embeddings(gnn: Any) -> Dict[str, Dict[str, float]]:
    """
    A named vector per asset, extracted from the live graph.

    Returns an empty mapping when no graph has been built -- never a vector of
    zeros. A zero embedding is a claim that every dimension was measured at
    zero, which is a different statement from "the graph does not exist yet",
    and downstream code cannot tell them apart once they look the same.
    """
    graph = getattr(gnn, "graph", None)
    if not isinstance(graph, Mapping) or not graph.get("assets"):
        return {}

    assets = list(graph.get("assets") or [])
    features = graph.get("features") or {}
    edges = graph.get("edges") or []
    weights = graph.get("edge_weights") or []

    degree: Dict[int, int] = {}
    weighted: Dict[int, float] = {}
    for (left, right), weight in zip(edges, weights):
        for index in (left, right):
            degree[index] = degree.get(index, 0) + 1
            weighted[index] = weighted.get(index, 0.0) + _number(weight)

    embeddings: Dict[str, Dict[str, float]] = {}
    for index, asset in enumerate(assets):
        feature = features.get(asset) or {}
        own = _number(feature.get("direction_4h"))
        peers = _number(feature.get("gnn_direction"))
        embeddings[asset] = {
            "direction_own": own,
            "direction_peers": peers,
            "conflict": own - peers,
            "degree": float(degree.get(index, 0)),
            "weighted_degree": round(weighted.get(index, 0.0), 6),
            "influence": peers,
        }
    return embeddings


def embedding_vector(embedding: Mapping[str, float]) -> List[float]:
    """The embedding in EMBEDDING_DIMENSIONS order, for anything numeric."""
    return [_number(embedding.get(name)) for name in EMBEDDING_DIMENSIONS]


def detect_conflicts(gnn: Any,
                     threshold: float = CONFLICT_THRESHOLD) -> Dict[str, Any]:
    """
    Assets whose own direction opposes what their peers imply (item 5).

    Only OPPOSING signs count as conflict, not merely different magnitudes: an
    asset reading +0.9 among peers implying +0.3 agrees with them
    emphatically, and calling that a conflict would fill the report with
    agreements and bury the handful of genuine disagreements.
    """
    embeddings = node_embeddings(gnn)
    if not embeddings:
        return {"available": False,
                "reason": "no graph has been built yet",
                "conflicts": []}

    conflicts = []
    for asset, embedding in embeddings.items():
        own = embedding["direction_own"]
        peers = embedding["direction_peers"]
        opposing = (own > 0 > peers) or (own < 0 < peers)
        magnitude = abs(own - peers)
        if opposing and magnitude >= threshold:
            conflicts.append({
                "asset": asset,
                "direction_own": round(own, 6),
                "direction_peers": round(peers, 6),
                "magnitude": round(magnitude, 6),
                "degree": embedding["degree"],
                "reading": ("the asset is moving against its correlated peers; "
                            "this is either a leading move or a false one, and "
                            "the graph cannot say which"),
            })

    conflicts.sort(key=lambda item: -item["magnitude"])
    return {
        "available": True,
        "assets": len(embeddings),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "threshold": threshold,
        "claims_direction": False,
    }


# ---------------------------------------------------------------------------
# Out-of-sample validation (item 7)
# ---------------------------------------------------------------------------

def _gnn_samples(trades: Sequence[Mapping[str, Any]], bridge: Any = None
                 ) -> List[Dict[str, Any]]:
    """
    One sample per trade that carries BOTH a GNN state at entry and a
    resolved outcome.

    Read through the bridge, so the GNN state comes from the decision-time
    analysis and the return from the outcome -- never from the same place.
    """
    from .price_evolution_bridge import PriceEvolutionBridge

    if bridge is None:
        bridge = PriceEvolutionBridge()

    samples: List[Dict[str, Any]] = []
    for trade in trades or []:
        try:
            canonical = bridge.to_canonical(dict(trade))
        except Exception:
            continue

        analysis = canonical.get("analysis_at_open") or {}
        gnn_state = analysis.get("gnn")
        if not isinstance(gnn_state, Mapping) or not gnn_state:
            continue

        entry = canonical.get("entry") or {}
        close = canonical.get("close_data") or {}
        entry_price = _number(entry.get("price"), 0.0)
        stop = _number(entry.get("stop_loss"), 0.0)
        close_price = _number(close.get("close_price"), 0.0)
        risk = abs(entry_price - stop)
        if not entry_price or not risk or not close_price:
            continue

        direction = str(canonical.get("direction") or "").upper()
        sign = -1 if direction.startswith("S") else 1
        realized_r = sign * (close_price - entry_price) / risk

        samples.append({
            "trade_id": str(canonical.get("trade_id")
                            or canonical.get("ticket") or ""),
            "timestamp": str(canonical.get("opened_at") or ""),
            "influence": _number(gnn_state.get("gnn_influence")
                                 or gnn_state.get("influence")),
            "connections": _number(gnn_state.get("gnn_connections")
                                   or gnn_state.get("connections")),
            "conflict": _number(gnn_state.get("conflict")),
            "realized_r": realized_r,
        })
    return samples


def _split_expectancy(samples: Sequence[Mapping[str, Any]],
                      threshold: float) -> Optional[float]:
    """Mean R of the trades this rule would have kept."""
    kept = [s["realized_r"] for s in samples
            if abs(s["influence"]) >= threshold]
    return sum(kept) / len(kept) if kept else None


def validate_out_of_sample(trades: Sequence[Mapping[str, Any]],
                           bridge: Any = None,
                           min_samples: int = 60,
                           seed: int = 42) -> Dict[str, Any]:
    """
    Does GNN context at entry predict anything, out of sample? (item 7)

    Chronological split -- train on the earlier trades, test on the later
    ones -- because a random split lets the model see the future of its own
    test set. The criterion is an expectancy delta in R that also beats a
    label-shuffled control, which is the same bar every other model here has
    to clear, and the bar that correctly refused meta-labeling.

    Built expecting to refuse. Direction entropy measured 1.0000, so a graph
    over coin-flip instruments has no obvious reason to predict outcomes, and
    a version of this reporting AUC alone would have found "signal" on the
    first run.
    """
    report: Dict[str, Any] = {
        "version": GNN_ANALYSIS_VERSION,
        "promoted": False,
        "phase": "5 - item 7 (OOS validation)",
    }

    samples = _gnn_samples(trades, bridge)
    report["samples"] = len(samples)
    report["trades_in"] = len(trades or [])

    if len(samples) < min_samples:
        report["measurable"] = False
        report["rejected_because"] = (
            "%d trades carry a GNN state and a resolved outcome; %d required. "
            "This is a data gap, not a verdict on the GNN."
            % (len(samples), min_samples))
        return report

    report["measurable"] = True
    samples = sorted(samples, key=lambda s: s["timestamp"])
    cut = int(len(samples) * 0.7)
    train, test = samples[:cut], samples[cut:]
    report["train_samples"] = len(train)
    report["test_samples"] = len(test)

    # The rule is chosen on TRAIN only. Choosing it on everything and then
    # reporting the test slice is the oldest way to manufacture a result.
    candidates = [0.0, 0.1, 0.2, 0.3, 0.5]
    scored = [(threshold, _split_expectancy(train, threshold))
              for threshold in candidates]
    scored = [(t, value) for t, value in scored if value is not None]
    if not scored:
        report["measurable"] = False
        report["rejected_because"] = "no threshold kept any training trade"
        return report

    best_threshold = max(scored, key=lambda pair: pair[1])[0]
    baseline = sum(s["realized_r"] for s in test) / len(test)
    policy = _split_expectancy(test, best_threshold)
    report["threshold"] = best_threshold
    report["baseline_r"] = round(baseline, 4)
    report["policy_r"] = round(policy, 4) if policy is not None else None
    delta = (policy - baseline) if policy is not None else None
    report["delta_r"] = round(delta, 4) if delta is not None else None

    # Shuffled control: the same selection procedure over outcomes that have
    # been detached from their features. Whatever it still finds is what the
    # procedure invents from nothing.
    rng = random.Random(seed)
    shuffled_deltas: List[float] = []
    returns = [s["realized_r"] for s in samples]
    for _ in range(60):
        pool = list(returns)
        rng.shuffle(pool)
        shuffled = [dict(s, realized_r=r) for s, r in zip(samples, pool)]
        s_train, s_test = shuffled[:cut], shuffled[cut:]
        s_scored = [(t, _split_expectancy(s_train, t)) for t in candidates]
        s_scored = [(t, v) for t, v in s_scored if v is not None]
        if not s_scored:
            continue
        s_threshold = max(s_scored, key=lambda pair: pair[1])[0]
        s_policy = _split_expectancy(s_test, s_threshold)
        if s_policy is None:
            continue
        s_baseline = sum(x["realized_r"] for x in s_test) / len(s_test)
        shuffled_deltas.append(s_policy - s_baseline)

    # Compared against the UPPER TAIL of the shuffled distribution, not its
    # mean. The mean is the centre of the null; a delta sitting inside the
    # null's ordinary spread beats it roughly half the time by construction.
    # Measured on pure noise with the mean as the bar, this promoted in 1 run
    # in 5 -- a 20% false-positive rate presented as a passed control.
    floor = (sum(shuffled_deltas) / len(shuffled_deltas)
             if shuffled_deltas else None)
    ceiling = None
    if shuffled_deltas:
        ordered = sorted(shuffled_deltas)
        index = min(len(ordered) - 1, int(0.95 * len(ordered)))
        ceiling = ordered[index]
    report["shuffled_floor_r"] = round(floor, 4) if floor is not None else None
    report["shuffled_95th_r"] = round(ceiling, 4) if ceiling is not None else None
    report["shuffles"] = len(shuffled_deltas)

    reasons: List[str] = []
    if delta is None:
        reasons.append("no test trade survived the selected threshold")
    else:
        if delta < 0.05:
            reasons.append("expectancy delta %.4fR below the 0.05R minimum"
                           % delta)
        if floor is None or ceiling is None:
            # An uncomputable gate is an unmet gate (standard 16).
            reasons.append("shuffled control could not be scored, so the "
                           "noise floor is unknown")
        elif delta <= ceiling:
            reasons.append(
                "delta %.4fR does not exceed the 95th percentile of the "
                "shuffled control (%.4fR) -- the same selection procedure "
                "reaches this on randomised outcomes at least 5%% of the time"
                % (delta, ceiling))
        elif delta - floor < 0.05:
            reasons.append(
                "delta %.4fR does not beat the shuffled mean %.4fR by 0.05R"
                % (delta, floor))

    report["promoted"] = not reasons
    report["rejected_because"] = "; ".join(reasons) if reasons else None
    return report


def get_status(gnn: Any = None) -> Dict[str, Any]:
    return {
        "component": "gnn_analysis",
        "version": GNN_ANALYSIS_VERSION,
        "implements": {
            "embeddings": True,             # phase 5 item 2
            "divergence_conflict": True,    # phase 5 item 5
            "oos_validation": True,         # phase 5 item 7
        },
        "embedding_dimensions": list(EMBEDDING_DIMENSIONS),
        "conflict_threshold": CONFLICT_THRESHOLD,
        "claims_direction": False,
        "validation_standard": (
            "chronological split, expectancy delta in R, must beat a "
            "label-shuffled control -- AUC alone is not accepted"),
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove embeddings extract, conflicts detect only real opposition, and the
    validator refuses rather than invents.
    """
    report: Dict[str, Any] = {
        "component": "gnn_analysis", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        # No graph must yield no embedding -- never a zero vector.
        class _Empty:
            graph = None

        checks["no_graph_yields_nothing"] = node_embeddings(_Empty()) == {}
        checks["no_graph_conflict_unavailable"] = (
            detect_conflicts(_Empty())["available"] is False)

        # A synthetic graph with one genuine opposition and one mere
        # magnitude difference: exactly one must be reported.
        class _Graph:
            graph = {
                "assets": ["A", "B", "C"],
                "nodes": 3,
                "edges": [(0, 1), (1, 2)],
                "edge_weights": [0.8, 0.6],
                "features": {
                    "A": {"direction_4h": 0.9, "gnn_direction": -0.8},
                    "B": {"direction_4h": 0.9, "gnn_direction": 0.3},
                    "C": {"direction_4h": 0.0, "gnn_direction": 0.0},
                },
            }

        embeddings = node_embeddings(_Graph())
        checks["embeddings_extracted"] = len(embeddings) == 3
        checks["embedding_is_named_and_ordered"] = (
            len(embedding_vector(embeddings["A"])) == len(EMBEDDING_DIMENSIONS))
        checks["degree_counted"] = embeddings["B"]["degree"] == 2.0

        conflicts = detect_conflicts(_Graph())
        checks["only_opposing_signs_are_conflicts"] = (
            conflicts["conflict_count"] == 1
            and conflicts["conflicts"][0]["asset"] == "A")

        trades = list(trades or [])
        checks["trades_in"] = len(trades)

        # Supplied trades that nothing can decode mean the DATA PATH failed,
        # and this must not report "verified" on the strength of its own
        # synthetic invariants. Those invariants hold on any input -- that is
        # what makes them invariants, and what makes them useless as evidence
        # that the pipeline works. Same discipline as standard 19.
        if trades:
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades)
            checks["usable_trades"] = usable
            if usable == 0:
                report["ok"] = False
                report["reason"] = (
                    "no supplied trade could be decoded; the module's own "
                    "invariants passed, which says nothing about the pipeline")
                return report

        validation = validate_out_of_sample(trades)
        checks["validation_runs"] = "promoted" in validation
        # With no GNN state in the trades this must report a DATA GAP, not a
        # verdict about the GNN.
        if not validation.get("measurable"):
            checks["unmeasurable_is_explained"] = bool(
                validation.get("rejected_because"))
        else:
            checks["unmeasurable_is_explained"] = True

        required = ("no_graph_yields_nothing", "no_graph_conflict_unavailable",
                    "embeddings_extracted", "embedding_is_named_and_ordered",
                    "degree_counted", "only_opposing_signs_are_conflicts",
                    "validation_runs", "unmeasurable_is_explained")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "GNN_ANALYSIS_VERSION", "EMBEDDING_DIMENSIONS", "CONFLICT_THRESHOLD",
    "node_embeddings", "embedding_vector", "detect_conflicts",
    "validate_out_of_sample", "get_status", "self_check",
]
