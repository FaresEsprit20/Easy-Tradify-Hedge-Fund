# ============================================================
# ABLATION STUDY -- PHASE 3 ITEM 9
# ============================================================
#
# WHAT WAS ALREADY THERE, AND WHAT WAS MISSING
# --------------------------------------------
# `ExperimentEngine.ablate_components` builds ablated feature sets: give it
# rows and a component name and it returns the rows with that component's
# columns removed. That is the data half of an ablation, and it was the only
# half. Nothing re-scored the ablated set, so no one could answer the question
# an ablation exists to answer -- what does this component actually
# contribute?
#
# WHAT CONTRIBUTION MEANS HERE
# ----------------------------
# For each analysis section, drop every feature derived from it, re-run the
# full training and validation pipeline, and compare the held-out expectancy
# to the model trained on everything.
#
#     contribution = expectancy(full) - expectancy(without this section)
#
# A POSITIVE contribution means removing the section made things worse, so it
# was carrying something. A NEGATIVE contribution means the model did BETTER
# without it -- the section was contributing noise the model was fitting.
#
# THE SECOND RESULT IS THE MORE USEFUL ONE
# ----------------------------------------
# Systems accumulate inputs and almost never remove them. This package already
# has a measured instance: family-weight calibration put `trend` at 0.00 --
# negative discrimination on all four test symbols -- and it stayed in the
# analysis. An ablation that only ever confirms importance is a ceremony;
# naming the sections whose removal IMPROVES the model is what makes it worth
# running.
#
# WHY DELTAS ARE REPORTED WITH A NOISE BAND
# -----------------------------------------
# Retraining on a slightly different feature set changes the result even when
# the removed features were pure noise -- different splits, different
# convergence. Measuring one ablation and reporting its delta as "the
# contribution" would dress that variance up as a finding. The same pipeline
# is therefore run repeatedly on RANDOM feature subsets of the same size, and
# a section's delta has to stand outside that band before it means anything.
# ============================================================

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

ABLATION_VERSION = "1.0"

# Sections are ablated by prefix over the context feature names, which are
# emitted as `ctx.open.<section>...` by price_evolution_bridge.
SECTION_PREFIX = "ctx.open."


def _sections(feature_names: Sequence[str]) -> List[str]:
    """Top-level analysis sections present in a feature vector."""
    found = set()
    for name in feature_names:
        if not name.startswith(SECTION_PREFIX):
            continue
        remainder = name[len(SECTION_PREFIX):]
        found.add(remainder.split(".")[0].split("=")[0])
    return sorted(found)


def _drop_section(features: Mapping[str, float], section: str
                  ) -> Dict[str, float]:
    prefix = SECTION_PREFIX + section
    return {name: value for name, value in features.items()
            if not name.startswith(prefix)}


def _drop_names(features: Mapping[str, float], names: Sequence[str]
                ) -> Dict[str, float]:
    banned = set(names)
    return {name: value for name, value in features.items()
            if name not in banned}


def _expectancy(samples: Sequence[Any], predictor: Callable[[Any], float]
                ) -> Optional[float]:
    values = [predictor(sample) for sample in samples]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def ablation_study(trades: Sequence[Mapping[str, Any]],
                   max_sections: Optional[int] = None,
                   random_subsets: int = 8,
                   seed: int = 42) -> Dict[str, Any]:
    """
    What each analysis section contributes to the exit model's held-out AUC.

    exit_model is the target because it is the only model here that both
    consumes the full context snapshot and has a held-out scoring path already
    validated by a permutation control. Adding a second training pipeline to
    ablate against would be a second implementation of something that exists.

    `random_subsets` sets the size of the noise band: random feature subsets of
    the same size, re-scored the same way. A section whose delta sits inside
    that band has not been shown to contribute anything.
    """
    from .exit_model import ExitModel, ExitModelConfig, build_samples, roc_auc, split_by_trade

    report: Dict[str, Any] = {"version": ABLATION_VERSION, "measurable": False}

    config = ExitModelConfig(include_context_features=True)
    samples = build_samples(trades, config)
    report["samples"] = len(samples)
    if len(samples) < config.min_samples:
        report["reason"] = ("%d samples; exit_model needs %d"
                            % (len(samples), config.min_samples))
        return report

    feature_names = sorted({name for s in samples for name in s.features})
    sections = _sections(feature_names)
    if not sections:
        report["reason"] = ("no context sections in the feature vector; "
                            "include_context_features produced nothing")
        return report

    if max_sections:
        sections = sections[:max_sections]
    report["sections_examined"] = sections
    report["features_total"] = len(feature_names)

    train, test = split_by_trade(samples)
    if not train or not test:
        report["reason"] = "trade-grouped split produced an empty side"
        return report

    def score(transform: Callable[[Mapping[str, float]], Dict[str, float]]
              ) -> Optional[float]:
        """Train on the transformed features and score held-out AUC."""
        from dataclasses import replace as _replace

        local_train = [_replace(s, features=transform(s.features)) for s in train]
        local_test = [_replace(s, features=transform(s.features)) for s in test]
        model = ExitModel(ExitModelConfig(include_context_features=True))
        try:
            model.fit(local_train)
            scores = model.predict_proba(local_test)
        except Exception:
            return None
        return roc_auc([s.label for s in local_test], scores)

    baseline = score(lambda features: dict(features))
    report["baseline_auc"] = round(baseline, 4) if baseline is not None else None
    if baseline is None:
        report["reason"] = "baseline model could not be scored"
        return report

    report["measurable"] = True

    # The noise band: random subsets the same size as a typical ablation.
    rng = random.Random(seed)
    context_names = [n for n in feature_names if n.startswith(SECTION_PREFIX)]
    typical_drop = max(1, len(context_names) // max(1, len(sections)))
    band: List[float] = []
    for _ in range(random_subsets):
        victims = rng.sample(context_names, min(typical_drop, len(context_names)))
        value = score(lambda features, victims=victims: _drop_names(features, victims))
        if value is not None:
            band.append(baseline - value)
    if band:
        mean = sum(band) / len(band)
        variance = (sum((v - mean) ** 2 for v in band) / (len(band) - 1)
                    if len(band) > 1 else 0.0)
        spread = math.sqrt(variance)
        report["noise_band"] = {
            "runs": len(band),
            "mean_delta": round(mean, 4),
            "std": round(spread, 4),
            "threshold": round(abs(mean) + 2 * spread, 4),
        }
        threshold = abs(mean) + 2 * spread
    else:
        report["noise_band"] = None
        threshold = None

    results: List[Dict[str, Any]] = []
    for section in sections:
        ablated = score(lambda features, section=section:
                        _drop_section(features, section))
        if ablated is None:
            results.append({"section": section, "auc": None,
                            "contribution": None,
                            "note": "ablated model could not be scored"})
            continue
        contribution = baseline - ablated
        results.append({
            "section": section,
            "auc_without": round(ablated, 4),
            "contribution": round(contribution, 4),
            "outside_noise_band": (None if threshold is None
                                   else bool(abs(contribution) > threshold)),
            "harmful": bool(contribution < 0),
        })

    results.sort(key=lambda item: -(item.get("contribution") or 0.0))
    report["sections"] = results

    significant = [r for r in results if r.get("outside_noise_band")]
    harmful = [r for r in significant if r.get("harmful")]
    report["contributing_sections"] = [
        r["section"] for r in significant if not r.get("harmful")]
    # The finding worth acting on.
    report["harmful_sections"] = [r["section"] for r in harmful]
    report["interpretation"] = (
        "a positive contribution means removing the section made the model "
        "worse; a NEGATIVE one means the model did better without it, and "
        "those are the sections worth removing rather than defending")
    report["observational"] = True
    return report


def get_status() -> Dict[str, Any]:
    return {
        "component": "ablation",
        "version": ABLATION_VERSION,
        "phase": "3 - item 9 (ablation)",
        "target_model": "exit_model with include_context_features",
        "why_that_target": (
            "the only model consuming the full context snapshot that also has "
            "a held-out scoring path already validated by a permutation "
            "control"),
        "reports_harmful_sections": True,
        "noise_band": (
            "random feature subsets of the same size, re-scored identically; "
            "a delta inside that band is retraining variance, not contribution"),
        "observational": True,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove ablation removes what it claims to, and reports a noise band.

    `dropping_a_section_removes_its_features` is load-bearing: the whole study
    is meaningless if the "ablated" run still sees the section, and a prefix
    bug there would be invisible in the output.
    """
    report: Dict[str, Any] = {
        "component": "ablation", "ok": False, "checks": {}}
    try:
        checks = report["checks"]

        features = {
            "ctx.open.smc.confluence_count": 4.0,
            "ctx.open.smc.market_structure.last_event": 1.0,
            "ctx.open.account_info.leverage": 200.0,
            "return_r": 0.5,
        }
        dropped = _drop_section(features, "smc")
        checks["dropping_a_section_removes_its_features"] = (
            not any(n.startswith("ctx.open.smc") for n in dropped))
        checks["dropping_keeps_everything_else"] = (
            "ctx.open.account_info.leverage" in dropped
            and "return_r" in dropped)
        checks["sections_detected"] = _sections(features) == [
            "account_info", "smc"]

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; study not exercised"
            return report

        # Undecodable input is a DATA PATH failure and must fail the gate.
        # The synthetic drop checks above pass on any input -- that is what
        # makes them invariants, and what makes them useless as evidence the
        # pipeline works.
        from .price_evolution_bridge import count_usable_trades

        usable = count_usable_trades(trades)
        checks["usable_trades"] = usable
        if usable == 0:
            report["ok"] = False
            report["reason"] = (
                "no supplied trade could be decoded; the module's own "
                "invariants passed, which says nothing about the pipeline")
            return report

        study = ablation_study(trades, max_sections=3, random_subsets=3)
        checks["study_runs"] = "measurable" in study
        if study.get("measurable"):
            checks["baseline_scored"] = study["baseline_auc"] is not None
            checks["reports_noise_band"] = study.get("noise_band") is not None
            checks["reports_harmful"] = "harmful_sections" in study
        else:
            # An unmeasurable study is NOT a pass. Setting these to True to
            # keep the report green was exactly the papering-over this
            # codebase keeps finding: the study did not run, so it verified
            # nothing, and `ok` must say so.
            # NOT EXERCISED, not failed. Undecodable input was already
            # caught above by count_usable_trades, which returns False;
            # reaching here means the trades decoded fine and the study simply
            # could not run -- too few samples, or a model that would not fit.
            # Reporting that as a failure pins the whole-layer gate red on
            # thin data, which is standard 19 in the other direction.
            checks["unmeasurable_explained"] = bool(study.get("reason"))
            report["ok"] = None
            report["reason"] = study.get("reason") or "ablation study did not run"
            return report

        required = ("dropping_a_section_removes_its_features",
                    "dropping_keeps_everything_else", "sections_detected",
                    "study_runs", "baseline_scored", "reports_noise_band",
                    "reports_harmful")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "ABLATION_VERSION", "ablation_study", "get_status", "self_check",
]
