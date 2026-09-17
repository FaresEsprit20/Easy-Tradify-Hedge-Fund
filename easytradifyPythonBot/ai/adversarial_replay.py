# ============================================================
# ADVERSARIAL REPLAY INTEGRATION -- PHASE 6 ITEM 6
# ============================================================
#
# THE QUESTION
# ------------
# Adversarial testing perturbs a trade's analysis and checks that the MODEL
# survives. This asks the harder question: does the DIAGNOSIS survive?
#
# Replay produces a failure class, a first divergence and a list of
# responsible-component candidates. If those flip when an unrelated field is
# nudged, the diagnosis was reading noise, and every recommendation built on
# it inherits that. An attribution that changes under a perturbation it should
# not care about is not a finding -- and until now nothing in this package
# could tell the two apart.
#
# WHY THIS IS THE RIGHT PAIRING
# -----------------------------
# The adversarial module already knows how to perturb a trade realistically:
# it has 28 attack families covering final decision, indicators, patterns,
# SMC, account state and more. Replay already knows how to reconstruct and
# attribute. Neither knew about the other. This runs replay on the original
# and on each attacked variant, and reports how much of the diagnosis is
# stable.
#
# WHAT STABILITY DOES AND DOES NOT MEAN
# -------------------------------------
# A stable diagnosis is not necessarily a CORRECT one -- a consistently wrong
# attribution is perfectly stable. Stability is a necessary condition, not a
# sufficient one, and the report says so rather than letting a high score read
# as validation.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

ADVERSARIAL_REPLAY_VERSION = "1.0"

# Fields a diagnosis must not be sensitive to in order to be worth trusting.
TRACKED_CONCLUSIONS = ("failure_class", "first_divergence_kind",
                       "top_candidate")


def _conclusions(trade: Mapping[str, Any], bridge: Any = None
                 ) -> Optional[Dict[str, Any]]:
    """The three conclusions replay reaches about one trade."""
    from .aireplay import replay_trade
    from .aireplay.data_engine import to_canonical_trade

    canonical = to_canonical_trade(trade, bridge)
    if canonical is None:
        return None
    try:
        replay = replay_trade(canonical)
    except Exception:
        return None

    divergences = replay.get("divergences") or {}
    earliest = None
    if isinstance(divergences, Mapping):
        earliest = divergences.get("earliest") or next(
            (v for v in divergences.values() if isinstance(v, Mapping)), None)

    attribution = replay.get("attribution") or {}
    candidates = attribution.get("responsible_component_candidates") or []
    top = candidates[0].get("component") if candidates else None

    return {
        "failure_class": attribution.get("failure_class"),
        "first_divergence_kind": (earliest or {}).get("kind"),
        "first_divergence_index": (earliest or {}).get("index"),
        "top_candidate": top,
        "candidate_count": len(candidates),
    }


def probe_trade(trade: Mapping[str, Any], adversarial: Any = None,
                variations: int = 8, bridge: Any = None) -> Dict[str, Any]:
    """
    How stable is the diagnosis of this trade under adversarial perturbation?

    The attacked variants come from the real attack families, not from noise
    injected here -- a bespoke perturbation would test robustness to something
    the system will never encounter.
    """
    from .ai_adversarial import AIAdversarial

    baseline = _conclusions(trade, bridge)
    if baseline is None:
        return {
            "version": ADVERSARIAL_REPLAY_VERSION,
            "trade_id": trade.get("trade_id") or trade.get("ticket"),
            "skipped": "trade could not be replayed",
        }

    if adversarial is None:
        adversarial = AIAdversarial()

    config = adversarial.adversarial_config
    saved = {key: config.get(key) for key in
             ("enabled", "attack_probability", "attack_both_wins_and_losses",
              "variations_per_trade")}
    saved_rollout = adversarial.ab_test.get("rollout")
    try:
        # Gates forced open: with defaults, attack generation is governed by
        # a probability and the A/B rollout, so a stability measurement would
        # be decided partly by a coin flip.
        config["enabled"] = True
        config["attack_probability"] = 1.0
        config["attack_both_wins_and_losses"] = True
        config["variations_per_trade"] = variations
        adversarial.set_ab_test_rollout(1.0)
        attacked = adversarial.generate_attacked_trades(dict(trade), 1, {})
    finally:
        config.update({k: v for k, v in saved.items() if v is not None})
        if saved_rollout is not None:
            adversarial.set_ab_test_rollout(saved_rollout)

    results: List[Dict[str, Any]] = []
    for variant in attacked[:variations]:
        conclusions = _conclusions(variant, bridge)
        if conclusions is None:
            continue
        changed = [name for name in TRACKED_CONCLUSIONS
                   if conclusions.get(name) != baseline.get(name)]
        results.append({
            "attack": variant.get("_adversarial_attack_type")
                      or variant.get("attack_type") or "unknown",
            "conclusions": conclusions,
            "changed": changed,
            "stable": not changed,
        })

    stable = [r for r in results if r["stable"]]
    per_conclusion = {
        name: sum(1 for r in results if name in r["changed"])
        for name in TRACKED_CONCLUSIONS
    }

    return {
        "version": ADVERSARIAL_REPLAY_VERSION,
        "trade_id": trade.get("trade_id") or trade.get("ticket"),
        "baseline": baseline,
        "variants_replayed": len(results),
        "stable_variants": len(stable),
        "stability": (round(len(stable) / len(results), 4) if results else None),
        "flips_by_conclusion": per_conclusion,
        "most_fragile_conclusion": (max(per_conclusion, key=per_conclusion.get)
                                    if results and any(per_conclusion.values())
                                    else None),
        "variants": results[:20],
        "caveat": ("stability is necessary, not sufficient: a consistently "
                   "wrong attribution is perfectly stable"),
    }


def probe_trades(trades: Sequence[Mapping[str, Any]], variations: int = 6,
                 bridge: Any = None) -> Dict[str, Any]:
    """
    Diagnosis stability across a cohort.

    The cohort number is the actionable one. A single unstable diagnosis is an
    anecdote; a layer where 40% of failure classes flip under perturbation is
    a diagnostic system reporting noise with a straight face.
    """
    from .ai_adversarial import AIAdversarial

    shared = AIAdversarial()
    results = [probe_trade(trade, shared, variations, bridge)
               for trade in trades or []]
    usable = [r for r in results if r.get("stability") is not None]
    if not usable:
        return {"trades": 0, "mean_stability": None,
                "reason": "no trade produced a replayable variant"}

    mean = sum(r["stability"] for r in usable) / len(usable)
    fragile = [r for r in usable if r["stability"] < 0.5]
    totals: Dict[str, int] = {name: 0 for name in TRACKED_CONCLUSIONS}
    for result in usable:
        for name, count in (result.get("flips_by_conclusion") or {}).items():
            totals[name] = totals.get(name, 0) + count

    return {
        "version": ADVERSARIAL_REPLAY_VERSION,
        "trades": len(usable),
        "skipped": len(results) - len(usable),
        "mean_stability": round(mean, 4),
        "fragile_trades": len(fragile),
        "fragile_fraction": round(len(fragile) / len(usable), 4),
        "flips_by_conclusion": totals,
        "most_fragile_conclusion": (max(totals, key=totals.get)
                                    if any(totals.values()) else None),
        "caveat": ("stability is necessary, not sufficient: a consistently "
                   "wrong attribution is perfectly stable"),
    }


def get_status() -> Dict[str, Any]:
    return {
        "component": "adversarial_replay",
        "version": ADVERSARIAL_REPLAY_VERSION,
        "phase": "6 - item 6 (replay integration)",
        "question": "does the DIAGNOSIS survive perturbation, not just the model",
        "tracked_conclusions": list(TRACKED_CONCLUSIONS),
        "uses_real_attack_families": True,
        "stability_implies_correctness": False,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the probe replays variants and measures a real stability number.

    `baseline_is_not_a_variant` guards the obvious way to fake a perfect
    score: replaying the original trade N times and reporting 100% stability.
    """
    report: Dict[str, Any] = {
        "component": "adversarial_replay", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        checks["stability_is_not_correctness"] = (
            get_status()["stability_implies_correctness"] is False)

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; probe not exercised"
            return report

        result = probe_trade(trades[0], variations=6)
        if result.get("skipped"):
            report["ok"] = False
            report["reason"] = result["skipped"]
            return report

        checks["baseline_conclusions"] = bool(result.get("baseline"))
        checks["variants_replayed"] = result.get("variants_replayed", 0)
        checks["produced_variants"] = result.get("variants_replayed", 0) > 0
        checks["stability_measured"] = result.get("stability") is not None

        # The attacked variants must genuinely differ from the original,
        # otherwise "stability" is measuring nothing at all.
        from .ai_adversarial import AIAdversarial

        adversarial = AIAdversarial()
        adversarial.adversarial_config["enabled"] = True
        adversarial.adversarial_config["attack_probability"] = 1.0
        adversarial.set_ab_test_rollout(1.0)
        variants = adversarial.generate_attacked_trades(dict(trades[0]), 1, {})
        checks["baseline_is_not_a_variant"] = bool(
            variants and any(v != trades[0] for v in variants))

        cohort = probe_trades(trades[:5], variations=4)
        checks["cohort_reports_mean"] = cohort.get("mean_stability") is not None

        required = ("stability_is_not_correctness", "baseline_conclusions",
                    "produced_variants", "stability_measured",
                    "baseline_is_not_a_variant", "cohort_reports_mean")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report


__all__ = [
    "ADVERSARIAL_REPLAY_VERSION", "TRACKED_CONCLUSIONS",
    "probe_trade", "probe_trades", "get_status", "self_check",
]
