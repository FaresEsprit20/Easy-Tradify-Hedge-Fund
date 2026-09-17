"""
COHERENCE VALIDATOR
===================
FILE: core/coherence.py

Every contradiction found in this system so far was found the same way: a
person read a payload and noticed two numbers that could not both be
true. Grade A beside a touch count of 1. A gate reporting PASS with a
negative margin. position BELOW_MIDDLE beside reason "Above middle band".
checks.choppy_market true beside triggered false. Four instruments whose
ATRs differ 245-fold all reporting probability 13.0.

That method does not scale and does not run at 3am. This module turns it
into machine-checked invariants that execute on every analysis.

DESIGN

An invariant is a statement that must hold between two or more published
fields. Each one names the fields, the rule, and what it means when
violated. They are pure functions of the result dict -- no market data,
no clock, no side effects -- so they are cheap, deterministic, and safe
to run in the hot path.

Violations are reported, never raised. A trading system that crashes on a
reporting inconsistency is worse than one that trades with a mislabelled
field. Severity separates the two cases:

    CRITICAL  two fields that GATE the trade disagree. The decision
              itself is unsound.
    ERROR     a published field contradicts the value that decided.
              Anyone reading the output is misled.
    WARNING   a value is outside its own declared domain, or a signal is
              structurally unable to fire.

WHAT THIS IS NOT

It does not judge whether a threshold is well chosen, whether a trade is
good, or whether the strategy has an edge. It only checks that the system
agrees with itself. A perfectly coherent system can still be wrong about
the market -- but an incoherent one cannot be reasoned about at all.
"""

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

CRITICAL = "CRITICAL"
ERROR = "ERROR"
WARNING = "WARNING"


def _get(d: Dict[str, Any], *path, default=None):
    """Nested lookup that never raises on a missing branch."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _violation(severity, invariant, detail, fields):
    return {
        "severity": severity,
        "invariant": invariant,
        "detail": detail,
        "fields": fields,
    }


# ============================================================
# INVARIANTS
# ============================================================

def _check_zone_grade_matches_touches(result, cfg) -> List[Dict]:
    """
    Zone grade is derived ENTIRELY from touch_count via
    ZONE_GRADE_THRESHOLDS, then optionally demoted by penalties. So the
    published grade can be LOWER than the touch count implies (a penalty
    fired) but never HIGHER -- nothing in the pipeline promotes a zone.

    Live violation that motivated this: zone_grade "A" published beside
    zone_touch_count 1, where A requires 8. A grade-A zone gets the
    largest position size and the tightest discount thresholds, so this
    is not cosmetic.
    """
    out = []
    order = ["A", "B", "C", "D", "E"]

    grade = _get(result, "indicators", "supply_demand", "zone_grade") \
        or _get(result, "entry_analysis", "discount", "zone_grade")
    if grade is None:
        return out

    # ✅ CORRECTED. This invariant originally assumed grade was a pure
    # function of touch_count -- true when it was written, and false as
    # soon as grading became composite (freshness + displacement + touch +
    # volume). The validator then flagged every correctly-graded fresh
    # zone as CRITICAL: "grade B is better than touch_count 2 allows".
    #
    # That was the validator working exactly as intended and being wrong
    # for exactly the right reason: it enforces the model it was told
    # about, so when the model changed it objected loudly instead of
    # silently passing. An invariant that cannot be wrong is not checking
    # anything.
    #
    # It now validates against whichever model actually produced the
    # grade: the composite score when a quality_breakdown is present,
    # touch_count when the legacy path ran.
    breakdown = _get(result, "indicators", "supply_demand", "debug", "quality_breakdown")
    composite = _num((breakdown or {}).get("composite"))

    if composite is not None:
        q_thresholds = cfg.get("zone_quality_grade_thresholds") \
            or {"A": 80, "B": 65, "C": 50, "D": 35}
        implied = "E"
        for g in ("A", "B", "C", "D"):
            if composite >= q_thresholds.get(g, 999):
                implied = g
                break
        if str(grade).upper() not in order:
            return out
        if order.index(str(grade).upper()) < order.index(implied):
            out.append(_violation(
                CRITICAL, "zone_grade_above_composite",
                f"zone_grade {grade} is better than composite quality "
                f"{composite:.1f} allows (implies {implied}). Penalties demote; "
                f"nothing promotes.",
                {"zone_grade": grade, "composite": composite,
                 "implied_grade": implied, "breakdown": breakdown},
            ))
        return out

    thresholds = cfg.get("zone_grade_thresholds") or {"A": 8, "B": 5, "C": 3, "D": 2}
    touches = _get(result, "indicators", "supply_demand", "debug", "touch_count")
    if touches is None:
        touches = _get(result, "entry_analysis", "discount", "debug", "zone_touch_count")
    touches = _num(touches)
    if touches is None:
        return out

    grade = str(grade).upper()
    if grade not in order:
        return out

    implied = "E"
    for g in ("A", "B", "C", "D"):
        if touches >= thresholds.get(g, 99):
            implied = g
            break

    if order.index(grade) < order.index(implied):
        out.append(_violation(
            CRITICAL, "zone_grade_not_promotable",
            f"zone_grade {grade} is BETTER than touch_count {touches:.0f} allows "
            f"(implies {implied}, needs >= {thresholds.get(grade)}). Penalties can "
            f"only demote a grade; nothing promotes one, so these two cannot both "
            f"be right. Grade drives position size and discount thresholds.",
            {"zone_grade": grade, "touch_count": touches, "implied_grade": implied},
        ))
    return out


def _check_gate_margins(result) -> List[Dict]:
    """
    A gate publishes `passed` (from the veto that decided) and `margin`
    (recomputed from value vs the quoted threshold). If the quoted
    threshold is not the one the veto used, the two disagree in sign.

    This has now happened three times: classification vs veto threshold
    (45 vs 70), default vs instrument override (70 vs 80), and flat ADX
    25 vs XAGUSD's 22.
    """
    out = []
    for gate in _get(result, "decision_snapshot", "gates_with_margin", default=[]) or []:
        if not isinstance(gate, dict):
            continue
        if gate.get("threshold_mismatch"):
            out.append(_violation(
                CRITICAL, "gate_threshold_mismatch",
                f"gate '{gate.get('gate')}' reports passed={gate.get('passed')} with "
                f"margin {gate.get('margin')} against threshold {gate.get('threshold')}. "
                f"A passing gate cannot have a negative margin -- the quoted threshold "
                f"is not the one the veto applied.",
                {k: gate.get(k) for k in ("gate", "passed", "value", "threshold", "margin")},
            ))
    return out


def _check_checks_agree_with_veto(result) -> List[Dict]:
    """
    vetos.checks is meant to explain vetos.triggered. If no check is true
    but a veto fired -- or every check is false while triggered is true --
    the explanation does not describe the decision.

    Advisory checks are excluded: they are reported but have no live veto
    behind them, so a true value there correctly does not trigger.
    """
    out = []
    vetos = _get(result, "vetos", default={}) or {}
    checks = vetos.get("checks") or {}
    advisory = set(vetos.get("advisory_only") or [])
    triggered = vetos.get("triggered")
    if not checks or triggered is None:
        return out

    enforced_true = [k for k, v in checks.items() if v and k not in advisory]

    if triggered and not enforced_true:
        out.append(_violation(
            ERROR, "veto_without_cause",
            f"vetos.triggered is true but no ENFORCED check is true "
            f"(reason: {vetos.get('reason')!r}). The checks block does not explain "
            f"the decision it is supposed to explain.",
            {"triggered": triggered, "reason": vetos.get("reason"),
             "advisory_true": [k for k, v in checks.items() if v and k in advisory]},
        ))
    if (not triggered) and enforced_true:
        out.append(_violation(
            ERROR, "cause_without_veto",
            f"enforced checks {enforced_true} are true but vetos.triggered is false. "
            f"Either the check uses a different threshold from the veto, or the veto "
            f"for it is disabled and should be listed in advisory_only.",
            {"triggered": triggered, "enforced_true": enforced_true},
        ))
    return out


def _check_probability_provenance(result, cfg) -> List[Dict]:
    """
    probability_percent must be the value the entry gate tested. If it
    equals the post-chain figure instead, the headline is a number no
    gate ever saw.

    Also flags the floor fingerprint: a probability sitting exactly on
    the 5.0 clamp plus a fixed chain constant is not a measurement. Four
    instruments whose ATRs spanned 0.7 to 171.6 pips all published
    exactly 13.0 -- 5.0 clamp + 8.0 ADR constant.
    """
    out = []
    fv = _get(result, "final_verdict", default={}) or {}
    prob = _num(fv.get("probability_percent"))
    post = _num(fv.get("probability_percent_post_chain"))
    if prob is None:
        return out

    direction = _get(result, "directional_analysis", "best_direction")
    raw = _num(_get(result, "directional_analysis",
                    "buy_probability" if direction == "BUY" else "sell_probability"))

    if raw is not None and raw <= 5.0 + 1e-9:
        out.append(_violation(
            WARNING, "probability_pinned_at_floor",
            f"{direction} probability is at the 5.0 clamp before the chain runs "
            f"(published {prob}). Every downstream adjustment is operating on a "
            f"clamped value, so the reported figure reflects chain constants rather "
            f"than this instrument's setup. Check volatility_protection.range_source.",
            {"raw_probability": raw, "published": prob,
             "range_source": _get(result, "volatility_protection", "range_source"),
             "confidence_penalty": _get(result, "volatility_protection", "confidence_penalty")},
        ))

    if post is not None and prob is not None and abs(prob - post) < 1e-9 and post != prob:
        out.append(_violation(
            ERROR, "probability_provenance_lost",
            "probability_percent equals the post-chain value; the decision-time "
            "figure has been overwritten.",
            {"probability_percent": prob, "post_chain": post},
        ))
    return out


def _check_volatility_verdicts(result) -> List[Dict]:
    """
    The static table, the regime classifier and the ATR percentile band
    all answer 'how volatile is this'. They may legitimately differ at
    the margins, but when the static table says EXTREME and the
    instrument's OWN distribution says NORMAL, the static table is
    describing a different instrument.
    """
    out = []
    v = _get(result, "volatility_protection", "volatility_verdicts", default={}) or {}
    if not v:
        return out
    static = str(v.get("static_table") or "").upper()
    band = str(v.get("percentile_band") or "").upper()
    if static in ("EXTREME", "HIGH") and band == "NORMAL":
        out.append(_violation(
            WARNING, "static_table_contradicts_own_distribution",
            f"static table says {static} while this instrument's own ATR percentile "
            f"band says NORMAL. The penalty derived from the static table is being "
            f"applied against a reading the instrument's own history calls ordinary.",
            {"verdicts": v,
             "atr_pips": _get(result, "volatility_protection", "atr_pips"),
             "band": _get(result, "volatility_protection", "atr_percentile_band")},
        ))
    return out


def _check_field_domains(result) -> List[Dict]:
    """
    Values outside their own declared range. Confidences are 0-100,
    probabilities 0-100, ratios non-negative. A negative confidence is
    how the GNN sign bug surfaced.
    """
    out = []
    probes = [
        ("ohlc_gnn.combined_signal.gnn_confidence",
         _get(result, "ohlc_gnn", "combined_signal", "gnn_confidence"), 0, 100),
        ("final_verdict.probability_percent",
         _get(result, "final_verdict", "probability_percent"), 0, 100),
        ("entry_analysis.timing_confidence",
         _get(result, "entry_analysis", "timing_confidence"), 0, 100),
    ]
    for name, val, lo, hi in probes:
        n = _num(val)
        if n is not None and not (lo <= n <= hi):
            out.append(_violation(
                ERROR, "value_outside_domain",
                f"{name} = {n}, outside its declared range [{lo}, {hi}].",
                {name: n},
            ))
    return out


def _check_direction_consistency(result) -> List[Dict]:
    """
    A direction that was explicitly vetoed should not be the chosen one
    unless the opposing side was vetoed too.
    """
    out = []
    dv = _get(result, "directional_analysis", "directional_vetoes", default={}) or {}
    if dv.get("chosen_direction_was_vetoed") and not dv.get("both_directions_vetoed"):
        out.append(_violation(
            CRITICAL, "vetoed_direction_chosen",
            f"best_direction was chosen despite carrying its own veto "
            f"({dv.get('buy_veto') or dv.get('sell_veto')}) while the opposing "
            f"direction was not vetoed.",
            dv,
        ))
    return out


def _check_probability_ledger(result) -> List[Dict]:
    """
    The ledger must account for the whole movement of best_probability.

    Before it existed, the payload published a chain of *_final_score
    blocks that did NOT reconcile: XAUUSD went 45.0 -> 5.0 while
    publishing a single -18.0 adjustment, leaving 22 points unexplained.
    expected_value, the H1 bonus and the hard-disagreement penalty all
    move probability without emitting an "adjustment".

    Two things are checked. First, that consecutive steps chain --
    step[i].after must equal step[i+1].before, or a mutation happened
    between recorded steps and the ledger has a hole. Second, that the
    last step lands on the published decision probability.

    A ledger that silently stops accounting is worse than no ledger,
    because it looks authoritative.
    """
    out = []
    fv = _get(result, "final_verdict", default={}) or {}
    ledger = fv.get("probability_ledger")
    if not ledger or not isinstance(ledger, list):
        return out

    for i in range(len(ledger) - 1):
        a, b = ledger[i], ledger[i + 1]
        after, before = _num(a.get("after")), _num(b.get("before"))
        if after is None or before is None:
            continue
        if abs(after - before) > 0.15:
            out.append(_violation(
                ERROR, "probability_ledger_gap",
                f"ledger discontinuity between '{a.get('step')}' (after {after}) "
                f"and '{b.get('step')}' (before {before}) -- probability moved "
                f"{before - after:+.2f} outside any recorded step.",
                {"prev_step": a.get("step"), "next_step": b.get("step"),
                 "after": after, "before": before},
            ))

    # ✅ CORRECTED. This originally compared the ledger's LAST step against
    # probability_percent and flagged a CRITICAL when they differed. They
    # are supposed to differ: probability_percent is the DECISION-time
    # value, captured before analyze_entry, while the ledger continues
    # through the post-entry chain (pattern, GNN, SMC, FVG, order flow,
    # gap) which affects reporting and sizing but never entry.
    #
    # Live proof: ledger ended 63.17, probability_percent 60.80, and
    # probability_percent_post_chain was 63.2 -- an exact match to the
    # ledger. The system was right and the invariant was comparing the
    # wrong pair, which is the second time an invariant here has flagged
    # correct behaviour after the model beneath it changed.
    #
    # The ledger now carries an ENTRY_DECISION marker, so each half can be
    # checked against the figure it actually corresponds to.
    published = _num(fv.get("probability_percent"))
    post = _num(fv.get("probability_percent_post_chain"))
    final = _num(ledger[-1].get("after"))

    marker = next((e for e in ledger if e.get("step") == "ENTRY_DECISION"), None)
    if marker is not None:
        at_decision = _num(marker.get("after"))
        if published is not None and at_decision is not None and abs(published - at_decision) > 0.15:
            out.append(_violation(
                CRITICAL, "probability_ledger_decision_mismatch",
                f"ledger marks the entry decision at {at_decision} but "
                f"probability_percent is {published}. The gate was evaluated "
                f"on a different number from the one published.",
                {"ledger_at_decision": at_decision, "published": published},
            ))
        target, label = post, "probability_percent_post_chain"
    else:
        # No marker: an older payload, or the chain ended at the decision.
        target, label = (post if post is not None else published), "post-chain value"

    if target is not None and final is not None and abs(target - final) > 0.15:
        out.append(_violation(
            CRITICAL, "probability_ledger_does_not_reconcile",
            f"ledger ends at {final} but {label} is {target}. "
            f"The published figure is not the one the recorded chain produces.",
            {"ledger_final": final, label: target, "steps": len(ledger)},
        ))
    return out


def _check_discount_buffer_scale(result) -> List[Dict]:
    """
    The "price is at the zone" buffer must be meaningful against the
    instrument's own range.

    discount_buffer_pips defaults to 1, giving a 0.9-pip window at grade
    B. That is 75% of a bar on EURUSD and 0.4% on XAUUSD, where price
    would have to land inside a 0.9-pip window on an instrument moving
    227 pips a minute -- sampled once per analysis, not continuously.
    discount_quality was NO_DISCOUNT with score 0 on every payload once
    the zone gate opened.

    Flags a buffer under 2% of ATR: at that point the gate is not
    selective, it is unreachable, and a permanently-unreachable gate is
    indistinguishable from a broken one.
    """
    out = []
    dbg = _get(result, "entry_analysis", "discount", "debug", default={}) or {}
    buf = _num(dbg.get("buffer_pips_used"))
    atr = _num(dbg.get("atr_pips")) or _num(_get(result, "volatility_protection", "atr_pips"))
    if buf is None or not atr or atr <= 0:
        return out
    pct = buf / atr * 100.0
    if pct < 2.0:
        out.append(_violation(
            WARNING, "discount_buffer_unreachable",
            f"the at-zone buffer is {buf:.2f} pips against an ATR of {atr:.1f} "
            f"({pct:.2f}% of one bar). Price would have to land inside that "
            f"window on a single sampled analysis -- the gate is effectively "
            f"unreachable rather than selective.",
            {"buffer_pips": buf, "atr_pips": atr, "pct_of_atr": round(pct, 2)},
        ))
    return out


INVARIANTS = [
    ("zone_grade_vs_touches", lambda r, c: _check_zone_grade_matches_touches(r, c)),
    ("gate_margins", lambda r, c: _check_gate_margins(r)),
    ("checks_vs_veto", lambda r, c: _check_checks_agree_with_veto(r)),
    ("probability_provenance", lambda r, c: _check_probability_provenance(r, c)),
    ("volatility_verdicts", lambda r, c: _check_volatility_verdicts(r)),
    ("field_domains", lambda r, c: _check_field_domains(r)),
    ("direction_consistency", lambda r, c: _check_direction_consistency(r)),
    ("probability_ledger", lambda r, c: _check_probability_ledger(r)),
    ("discount_buffer_scale", lambda r, c: _check_discount_buffer_scale(r)),
]


def validate_coherence(result: Dict[str, Any],
                       cfg: Dict[str, Any] = None,
                       symbol: str = "") -> Dict[str, Any]:
    """
    Run every invariant over a completed analysis result.

    Never raises. A malformed result, a missing section, or a bug in an
    invariant itself must not take down an analysis -- the validator is
    an observer, not a gate.
    """
    cfg = cfg or {}
    violations: List[Dict] = []

    for name, fn in INVARIANTS:
        try:
            violations.extend(fn(result, cfg) or [])
        except Exception as e:  # an invariant must never break the caller
            logger.debug(f"[COHERENCE] invariant {name} failed on {symbol}: {e}")

    counts = {CRITICAL: 0, ERROR: 0, WARNING: 0}
    for v in violations:
        counts[v["severity"]] = counts.get(v["severity"], 0) + 1

    for v in violations:
        line = f"[COHERENCE] {symbol}: {v['invariant']} -- {v['detail']}"
        if v["severity"] == CRITICAL:
            logger.error(line)
        elif v["severity"] == ERROR:
            logger.warning(line)
        else:
            logger.info(line)

    return {
        "coherent": not violations,
        "counts": counts,
        "violations": violations,
        "invariants_run": len(INVARIANTS),
    }