# ============================================================
# COMPONENT VALIDATION -- EARN THE RIGHT TO VOTE
# ============================================================
#
# THE MEASUREMENT THAT MOTIVATED THIS
# -----------------------------------
# Every component publishes a score that contributes points to the final
# probability. Measured on 215 real trades with the analysis recomputed at
# each entry, direction chosen on a chronological training split and scored on
# the held-out remainder:
#
#     14 components tested
#      7 held their training direction out of sample
#      7 REVERSED it
#      0 survived Benjamini-Hochberg at q=0.10
#
# Seven of fourteen is a coin flip. And the component with the LARGEST
# training edge (nested_zone, +0.4271R) had the WORST test edge (-0.4567R) --
# the strongest in-sample signal reversed hardest, which is the defining
# signature of fitting noise.
#
# This is also why the composite fails. The stated confidence was measured
# non-monotonic across its own deciles (best band 37-58%, p=0.62 high versus
# low). A weighted sum of scores that do not individually discriminate cannot
# discriminate, and no amount of reweighting fixes inputs that carry nothing.
#
# WHAT THIS MODULE IS FOR
# -----------------------
# Making a component earn its vote. `validate()` measures each one the same
# way -- chronological split, direction fixed on train, scored out of sample,
# corrected across the family -- and `recommended_weights()` returns 0.0 for
# any component that has not demonstrated it discriminates.
#
# A component at weight 0 is not deleted. It is still computed, still
# recorded, and still available to be re-validated when there are enough
# trades to settle it. It simply stops adding points to a probability on the
# strength of an assumption.
#
# WHY THIS IS NOT ANOTHER SCAN
# ----------------------------
# A previous pass scanned 1,756 buckets over every analysis feature and found
# nothing, because the correction over that many comparisons makes 215 trades
# meaningless. This tests a FIXED, pre-declared family -- the components that
# already vote -- which is a question that was going to be asked anyway. The
# family is small, named in advance, and the same every run.
#
# WHAT IT CANNOT DO
# -----------------
# It cannot manufacture a component that works. With 215 trades, detecting a
# 0.3R effect needs roughly 470 and a 0.1R effect roughly 4,200; most
# components will report NOT PROVEN for a long time, and that is the honest
# state rather than a failure of the method.
# ============================================================

from __future__ import annotations

import os
import statistics
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

COMPONENT_VALIDATION_VERSION = "1.0"

# Minimum trades on each side of a split before a component is scored at all.
MIN_TRAIN = 40
MIN_TEST = 20
MIN_BUCKET = 8

TRAIN_FRACTION = 0.7
FALSE_DISCOVERY_RATE = 0.10


from .price_evolution_bridge import canonical_analysis

def extract_scores(analysis: Mapping[str, Any]) -> Dict[str, float]:
    """
    Every numeric component score in one analysis payload.

    Covers both places a component publishes: `components.<name>.score` and
    the `final_verdict.*_final_score` blocks, which are separate voters that
    happen to live in a different section.
    """
    scores: Dict[str, float] = {}
    if not isinstance(analysis, Mapping):
        return scores

    for name, block in (analysis.get("components") or {}).items():
        if isinstance(block, Mapping) and isinstance(
                block.get("score"), (int, float)):
            scores["comp." + str(name)] = float(block["score"])

    for name, value in (analysis.get("final_verdict") or {}).items():
        if not str(name).endswith("_final_score"):
            continue
        if isinstance(value, (int, float)):
            scores["fv." + str(name)] = float(value)
        elif isinstance(value, Mapping):
            for key in ("score", "adjustment", "final_score"):
                if isinstance(value.get(key), (int, float)):
                    scores["fv.%s.%s" % (name, key)] = float(value[key])
                    break
    return scores


def _samples(trades: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One row per trade: realised R, opening timestamp, component scores."""
    rows = []
    for trade in trades or []:
        entry = trade.get("entry") or {}
        close = trade.get("close_data") or {}
        price, stop = entry.get("price"), entry.get("stop_loss")
        exit_price = close.get("close_price")
        if not price or not stop or not exit_price:
            continue
        risk = abs(price - stop)
        if not risk:
            continue
        sign = -1 if str(trade.get("direction", "")).upper().startswith("S") else 1
        rows.append({
            "r": sign * (exit_price - price) / risk,
            "at": str(trade.get("opened_at") or ""),
            # canonical_analysis(): analysis_at_open is an envelope in the
            # live shape, so extract_scores() on the raw block finds nothing.
            "scores": extract_scores(
                canonical_analysis(trade.get("analysis_at_open") or {})),
        })
    rows.sort(key=lambda row: row["at"])
    return rows


def validate(trades: Sequence[Mapping[str, Any]],
             train_fraction: float = TRAIN_FRACTION,
             fdr: float = FALSE_DISCOVERY_RATE) -> Dict[str, Any]:
    """
    Measure every component's out-of-sample discrimination.

    Chronological, never random: a random split lets a component see its own
    test set's regime, and market data is the case where that matters most.
    The favoured direction is fixed on TRAIN -- deciding "high is good" after
    seeing the test result turns a coin into a signal.
    """
    from .abstention_model import benjamini_hochberg, welch_t_test

    report: Dict[str, Any] = {
        "version": COMPONENT_VALIDATION_VERSION, "measurable": False}

    rows = _samples(trades)
    report["trades"] = len(rows)
    cut = int(len(rows) * train_fraction)
    train, test = rows[:cut], rows[cut:]
    report["train"], report["test"] = len(train), len(test)

    if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
        report["reason"] = (
            "need >=%d train and >=%d test trades, have %d and %d"
            % (MIN_TRAIN, MIN_TEST, len(train), len(test)))
        return report

    report["measurable"] = True
    names = sorted({name for row in rows for name in row["scores"]})
    results: List[Dict[str, Any]] = []

    for name in names:
        train_pairs = [(r["scores"][name], r["r"]) for r in train
                       if name in r["scores"]]
        test_pairs = [(r["scores"][name], r["r"]) for r in test
                      if name in r["scores"]]
        if len(train_pairs) < MIN_TRAIN or len(test_pairs) < MIN_TEST:
            continue
        if len({v for v, _ in train_pairs}) < 3:
            # A constant score cannot separate anything.
            continue

        median = statistics.median(v for v, _ in train_pairs)
        high_train = [r for v, r in train_pairs if v > median]
        low_train = [r for v, r in train_pairs if v <= median]
        if len(high_train) < MIN_BUCKET or len(low_train) < MIN_BUCKET:
            continue

        favour_high = statistics.mean(high_train) > statistics.mean(low_train)
        high_test = [r for v, r in test_pairs if v > median]
        low_test = [r for v, r in test_pairs if v <= median]
        if len(high_test) < MIN_BUCKET or len(low_test) < MIN_BUCKET:
            continue

        kept = high_test if favour_high else low_test
        dropped = low_test if favour_high else high_test
        edge = statistics.mean(kept) - statistics.mean(dropped)

        results.append({
            "component": name,
            "favour": "high" if favour_high else "low",
            "train_edge_r": round(
                (statistics.mean(high_train) - statistics.mean(low_train))
                * (1 if favour_high else -1), 4),
            "test_edge_r": round(edge, 4),
            "kept_mean_r": round(statistics.mean(kept), 4),
            "kept_win_rate": round(
                sum(1 for r in kept if r > 0) / len(kept), 4),
            "kept_n": len(kept),
            "p_value": welch_t_test(kept, dropped),
            # The single most informative field: did the direction chosen on
            # train survive contact with unseen trades?
            "holds_out_of_sample": edge > 0,
        })

    survivors = benjamini_hochberg([r["p_value"] for r in results], fdr)
    for result, survived in zip(results, survivors):
        result["survives_fdr"] = bool(survived)
        result["verdict"] = (
            "VALIDATED" if survived and result["holds_out_of_sample"]
            else "NOT PROVEN" if result["holds_out_of_sample"]
            else "REVERSED")

    results.sort(key=lambda r: -r["test_edge_r"])
    holding = [r for r in results if r["holds_out_of_sample"]]

    report["components"] = results
    report["tested"] = len(results)
    report["held_direction"] = len(holding)
    report["reversed"] = len(results) - len(holding)
    report["validated"] = sum(1 for r in results if r["verdict"] == "VALIDATED")
    # A 50/50 split of held versus reversed is what no signal looks like.
    report["hold_rate"] = (round(len(holding) / len(results), 4)
                           if results else None)
    report["reading"] = (
        "a hold rate near 0.5 is what no discrimination looks like; a "
        "component that REVERSED contributed points in the wrong direction "
        "on unseen trades")
    return report


def recommended_weights(trades: Sequence[Mapping[str, Any]],
                        **kwargs: Any) -> Dict[str, Any]:
    """
    The weight each component has earned: 1.0 if validated, else 0.0.

    Weight 0 is not deletion. The component still computes, still records and
    can be re-validated once there are enough trades; it simply stops adding
    points to a probability on the strength of an assumption.

    Deliberately binary. A graded weight fitted to these same trades would be
    another parameter fitted on 215 samples, and the whole finding here is
    that 215 samples cannot support that.
    """
    report = validate(trades, **kwargs)
    if not report.get("measurable"):
        return {"measurable": False, "reason": report.get("reason"),
                "weights": {}}

    weights = {}
    for result in report["components"]:
        weights[result["component"]] = (
            1.0 if result["verdict"] == "VALIDATED" else 0.0)

    return {
        "measurable": True,
        "weights": weights,
        "validated": [c for c, w in weights.items() if w > 0],
        "silenced": [c for c, w in weights.items() if w == 0],
        "reversed": [r["component"] for r in report["components"]
                     if r["verdict"] == "REVERSED"],
        "note": ("weight 0 means the component has not demonstrated "
                 "discrimination on held-out trades, not that it is wrong"),
        "sample_size_caveat": (
            "with %d trades, detecting a 0.3R effect needs ~470 and a 0.1R "
            "effect ~4,200; most components will read NOT PROVEN for a long "
            "time" % report.get("trades", 0)),
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "component_validation",
        "version": COMPONENT_VALIDATION_VERSION,
        "question": "has this component earned the right to vote?",
        "method": ("chronological split, direction fixed on train, scored "
                   "out of sample, Benjamini-Hochberg across the family"),
        "family": "the components that already vote -- fixed and pre-declared",
        "why_not_a_scan": (
            "a 1,756-bucket scan over every analysis feature found nothing, "
            "because the correction over that many comparisons makes 215 "
            "trades meaningless; this asks one question of a small named set"),
        "weights_are_binary": True,
        "weight_zero_means": "not proven, not deleted",
        "prior_measurement": {
            "trades": 215, "tested": 14, "held": 7, "reversed": 7,
            "validated": 0,
            "largest_train_edge": "nested_zone +0.4271R",
            "its_test_edge": "-0.4567R",
            "reading": ("7 of 14 is a coin flip; the strongest in-sample "
                        "signal reversed hardest, which is what fitting "
                        "noise looks like"),
        },
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the method refuses noise and cannot see its own test set.

    `noise_is_not_validated` is load-bearing: run on random scores this must
    validate nothing, or the whole exercise is a machine for promoting noise
    into weights.
    """
    report: Dict[str, Any] = {
        "component": "component_validation", "ok": False, "checks": {}}
    try:
        import random

        checks = report["checks"]

        # Pure noise: random component scores, random outcomes.
        rng = random.Random(11)
        noise = []
        for index in range(220):
            noise.append({
                "direction": "BUY",
                "opened_at": "2026-01-%02dT%02d:00:00Z" % (
                    1 + index // 24, index % 24),
                "entry": {"price": 1.1, "stop_loss": 1.09},
                "close_data": {"close_price": 1.1 + rng.gauss(0, 0.01)},
                "analysis_at_open": {
                    "components": {
                        "a": {"score": rng.uniform(0, 100)},
                        "b": {"score": rng.uniform(0, 100)},
                        "c": {"score": rng.uniform(0, 100)},
                    }},
            })
        noise_report = validate(noise)
        checks["noise_is_measurable"] = bool(noise_report.get("measurable"))
        checks["noise_is_not_validated"] = noise_report.get("validated", 0) == 0

        # A planted signal must be found: a control that rejects everything is
        # as useless as one that accepts everything.
        planted = []
        for index in range(220):
            score = rng.uniform(0, 100)
            move = 0.02 if score > 50 else -0.02
            planted.append({
                "direction": "BUY",
                "opened_at": "2026-01-%02dT%02d:00:00Z" % (
                    1 + index // 24, index % 24),
                "entry": {"price": 1.1, "stop_loss": 1.09},
                "close_data": {"close_price": 1.1 + move},
                "analysis_at_open": {
                    "components": {"real": {"score": score}}},
            })
        planted_report = validate(planted)
        checks["planted_signal_holds"] = any(
            r["holds_out_of_sample"] for r in planted_report.get("components", []))

        # Thin data must refuse rather than produce a confident empty result.
        checks["thin_data_refuses"] = validate(noise[:20]).get(
            "measurable") is False

        weights = recommended_weights(noise)
        checks["weights_are_binary"] = all(
            w in (0.0, 1.0) for w in weights.get("weights", {}).values())
        checks["noise_components_silenced"] = all(
            w == 0.0 for w in weights.get("weights", {}).values())

        if trades:
            real = validate(trades)
            checks["real_trades_measurable"] = bool(real.get("measurable"))
            checks["real_hold_rate"] = real.get("hold_rate")

        required = ("noise_is_measurable", "noise_is_not_validated",
                    "planted_signal_holds", "thin_data_refuses",
                    "weights_are_binary", "noise_components_silenced")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "COMPONENT_VALIDATION_VERSION", "extract_scores", "validate",
    "recommended_weights", "get_status", "self_check",
]
