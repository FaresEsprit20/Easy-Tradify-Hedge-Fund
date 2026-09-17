# ============================================================
# REPLAY FORENSICS
# ============================================================
# FILE: core/replay_forensics.py
#
# A win rate tells you WHETHER something is wrong. This tells you WHERE.
#
# Every analysis here exists because a specific class of failure is
# invisible without it:
#
#   gate_funnel          which gate kills decisions -- a gate that rejects
#                        99% is an outage, and looks identical to a strict
#                        filter unless counted
#   gate_counterfactual  what each gate rejected. A gate that only rejects
#                        winners is worse than no gate, and NOTHING in a
#                        normal backtest reveals it
#   evidence_attribution which families actually predict. A family whose
#                        contribution has zero correlation with outcome is
#                        noise being counted as confluence
#   frozen_fields        values identical on every decision -- dead code,
#                        a broken feed, or a default that never updates
#   degenerate_fields    always-null, always-zero, always-bounded
#   clamp_forensics      evidence computed and discarded at a bound
#   contradiction        how often modules disagreed, and whether
#                        disagreement predicted failure
#   data_integrity       gaps, NaN, stale bars, impossible values
#   regime_breakdown     an edge that exists only in one regime is not an
#                        edge, it is a sample artifact
#   threshold_sensitivity how close gates ran to their thresholds -- a gate
#                        always clearing by 0.0 is not really a gate
#   direction_bias       a system that only ever goes one way
#   temporal             edge concentrated in a few hours or a few days
#
# Everything degrades gracefully: a missing field produces "unavailable",
# never an exception. A forensics module that crashes on the run you most
# need it for is worthless.
# ============================================================

from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import math

# A field seen on fewer than this many decisions is not worth judging.
MIN_SAMPLE = 20
# Correlations below this are treated as noise regardless of sign.
WEAK_CORRELATION = 0.05


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and float("-inf") < v < float("inf") else None


def _cap(rec, *path, default=None):
    cur = rec.get("capture") or {}
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _outcome_of(rec) -> Optional[str]:
    """WIN/LOSS from the shadow, which exists for taken and rejected alike."""
    o = (rec.get("shadow") or rec.get("outcome") or {}).get("outcome")
    return o if o in ("WIN", "LOSS") else None


def _r_of(rec) -> Optional[float]:
    o = rec.get("shadow") or rec.get("outcome") or {}
    return _f(o.get("r_multiple_net"))


def _rate(records) -> Optional[float]:
    res = [r for r in records if _outcome_of(r)]
    if not res:
        return None
    return sum(1 for r in res if _outcome_of(r) == "WIN") / len(res) * 100.0


def _expectancy(records) -> Optional[float]:
    vals = [_r_of(r) for r in records if _outcome_of(r)]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _corr(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson r. Returns None rather than 0 when it is undefined."""
    n = len(xs)
    if n < MIN_SAMPLE:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _outcome_variance(records) -> Tuple[int, Optional[str]]:
    """
    (resolved count, blocking reason) for any analysis that needs both
    wins and losses.

    Correlation and discrimination are undefined when every resolved
    decision had the same outcome. Reporting that once, clearly, is far
    more useful than printing "undefined" against twenty rows -- it
    points at the sample rather than implying twenty separate problems.
    """
    res = [r for r in records if _outcome_of(r)]
    n = len(res)
    if n < MIN_SAMPLE:
        return n, (f"only {n} resolved decisions (need {MIN_SAMPLE}). Most setups "
                   f"never reached stop or target inside the holding window -- "
                   f"try a longer history or a larger --max-holding.")
    wins = sum(1 for r in res if _outcome_of(r) == "WIN")
    if wins == n:
        return n, (f"all {n} resolved decisions WON. Nothing can be discriminated "
                   f"from a single-outcome sample -- this usually means the data "
                   f"trends one way and the system only traded with it. Check "
                   f"direction bias and the per-bucket breakdowns.")
    if wins == 0:
        return n, (f"all {n} resolved decisions LOST. Nothing can be discriminated "
                   f"from a single-outcome sample.")
    return n, None


def _summary_block(records, label) -> Dict[str, Any]:
    res = [r for r in records if _outcome_of(r)]
    wins = sum(1 for r in res if _outcome_of(r) == "WIN")
    return {
        "label": label,
        "n": len(records),
        "resolved": len(res),
        "wins": wins,
        "win_rate_pct": round(wins / len(res) * 100, 1) if res else None,
        "expectancy_r": round(_expectancy(records), 3) if res else None,
    }


# ------------------------------------------------------------
# COMPONENT ATTRIBUTION
# ------------------------------------------------------------

def component_attribution(records) -> Dict[str, Any]:
    """
    Win rate for every analysis component, split by its own verdict.

    Section 5 scores the eleven probability-chain contributions. This
    scores the components a trader actually reasons about -- trend,
    supply/demand, support/resistance, ICT, candlestick, Wyckoff,
    indicators, GNN -- and it asks the sharper question: when THIS
    component said BUY, did price go up?

    The measure is the spread between a component's bullish calls and
    its bearish ones, in win-rate points, restricted to decisions where
    the trade direction matched the call. A component with real skill
    wins more when it agrees with the trade than when it opposes it.
    Zero spread means the component is decorative: it is consuming
    weight in the probability chain and returning noise.

    This is the section that answers "why can we not reach a high win
    rate" component by component, instead of as one aggregate number
    nobody can act on.
    """
    n_res, blocker = _outcome_variance(records)
    if blocker:
        return {"available": False, "reason": blocker}

    def verdict_side(rec: str) -> Optional[str]:
        """
        Map a component's recommendation onto BUY/SELL/neutral.

        Each component speaks its own vocabulary, and a substring match
        on BUY/SELL alone silently drops half of some of them. The
        supply/demand engine emits IMMEDIATE_ENTRY / IMMEDIATE_SELL --
        the first is a BUY and contains none of the usual keywords, so
        matching only on "BUY" scored that component on its SELL calls
        exclusively and reported an edge computed from half its
        decisions. Anything not recognised must return None (excluded)
        rather than being guessed into a side.
        """
        if not rec:
            return None
        r = str(rec).strip().upper()

        # Exact vocabulary first -- substring rules cannot express
        # "IMMEDIATE_ENTRY means buy" and would mis-handle it silently.
        exact = {
            "IMMEDIATE_ENTRY": "BUY",
            "IMMEDIATE_BUY": "BUY",
            "IMMEDIATE_BUY": "BUY",
            "IMMEDIATE_SELL": "SELL",
            "STRONG_BUY": "BUY",
            "STRONG_SELL": "SELL",
            "BUY": "BUY",
            "SELL": "SELL",
            "BULLISH": "BUY",
            "BEARISH": "SELL",
            "STRONG_BULLISH": "BUY",
            "STRONG_BEARISH": "SELL",
        }
        if r in exact:
            return exact[r]

        # Explicitly neutral / non-directional verdicts.
        if r in ("MONITOR", "AVOID", "WAIT_FOR_RETEST", "HOLD", "NEUTRAL",
                 "WAIT", "NONE", "EXCLUDED", "NO_SIGNAL"):
            return None

        # Fall back to substring, longest keywords first so STRONG_SELL
        # cannot be read as a BUY by matching some other fragment.
        if "SELL" in r or "BEARISH" in r or "SHORT" in r:
            return "SELL"
        if "BUY" in r or "BULLISH" in r or "LONG" in r:
            return "BUY"
        return None

    # Component verdicts live under capture["components"]; the GNN's
    # signed contribution lives with the chain contributions.
    names = set()
    for r in records:
        names.update((_cap(r, "components") or {}).keys())

    # Several components are published twice -- once as a top-level
    # analysis block and once inside the indicators container (trend,
    # supply_demand, support_resistance, candlestick, wyckoff). They are
    # the same verdict from the same computation, so the "ind:" copy is
    # dropped rather than listed twice with identical numbers, which
    # reads as independent corroboration when it is one measurement.
    duplicated = {n for n in names if n.startswith("ind:") and n[4:] in names}
    names -= duplicated

    rows = []
    for name in sorted(names):
        agree, oppose = [], []
        for r in records:
            if not _outcome_of(r):
                continue
            blk = (_cap(r, "components") or {}).get(name) or {}
            side = verdict_side(blk.get("recommendation"))
            direction = _cap(r, "direction")
            if side is None or direction not in ("BUY", "SELL"):
                continue
            (agree if side == direction else oppose).append(r)

        # BOTH sides need a real sample. An `and` here let a component
        # with 1099 agreements and ONE disagreement report an edge of
        # +29.8 points and the verdict PREDICTIVE -- the entire spread
        # came from a single losing decision on the opposing side.
        # An edge is a comparison, and a comparison needs two samples.
        if len(agree) < MIN_SAMPLE or len(oppose) < MIN_SAMPLE:
            # A component that never opposes is not necessarily broken --
            # it may not be a DIRECTIONAL signal at all. core/expected_value.py
            # is the clear case: it judges whether this trade's risk/reward
            # is worth taking, and its docstring is explicit that a bad EV
            # on a BUY is not evidence for a SELL, so it votes the trade's
            # own direction or NEUTRAL and registers dissent through its
            # SCORE (-15) instead. Scoring that by directional agreement
            # measures the wrong thing and calls a correctly-built
            # component one-sided.
            #
            # So these are labelled as needing the other lens rather than
            # judged by this one. score_attribution() below is that lens.
            one_sided = (len(agree) >= MIN_SAMPLE) != (len(oppose) >= MIN_SAMPLE)
            rows.append({
                "component": name, "n_agree": len(agree),
                "n_oppose": len(oppose),
                "verdict": ("NON-DIRECTIONAL -- judge by score, not by side"
                            if one_sided else "INSUFFICIENT SAMPLE"),
                "win_agree_pct": round(_rate(agree), 1) if len(agree) >= MIN_SAMPLE else None,
                "win_oppose_pct": round(_rate(oppose), 1) if len(oppose) >= MIN_SAMPLE else None,
                "edge_pts": None})
            continue

        wa, wo = _rate(agree), _rate(oppose)
        edge = (wa - wo) if (wa is not None and wo is not None) else None
        if edge is None:
            verdict = "ONE-SIDED -- never took the other view"
        elif edge >= 5.0:
            verdict = "PREDICTIVE"
        elif edge <= -5.0:
            verdict = "INVERTED -- agreeing with it costs money"
        else:
            verdict = "NO SKILL -- decorative weight in the chain"

        rows.append({
            "component": name,
            "n_agree": len(agree), "n_oppose": len(oppose),
            "win_agree_pct": round(wa, 1) if wa is not None else None,
            "win_oppose_pct": round(wo, 1) if wo is not None else None,
            "edge_pts": round(edge, 1) if edge is not None else None,
            "verdict": verdict,
        })

    rows.sort(key=lambda r: -(r["edge_pts"] if r["edge_pts"] is not None else -999))
    predictive = [r["component"] for r in rows if r["verdict"] == "PREDICTIVE"]
    inverted = [r["component"] for r in rows if r["verdict"].startswith("INVERTED")]
    useless = [r["component"] for r in rows if r["verdict"].startswith("NO SKILL")]

    return {
        "available": True,
        "resolved": n_res,
        "components": rows,
        "predictive": predictive,
        "inverted": inverted,
        "no_skill": useless,
    }


def score_attribution(records) -> Dict[str, Any]:
    """
    Does a component's SCORE predict the outcome, regardless of side?

    component_attribution() asks whether trading WITH a component beats
    trading against it. That is the right question for a directional
    signal and the wrong one for a quality assessor: core/expected_value.py
    rates whether this particular trade is worth taking and deliberately
    never votes for the opposite direction, so a directional lens reports
    it as "one-sided" and learns nothing.

    This is the other lens. For every component that publishes a numeric
    score, it correlates that score with the realised outcome across all
    decisions. A component whose high scores win more often is carrying
    information even if it never picks a side; one whose correlation is
    zero is contributing weight and nothing else.
    """
    n_res, blocker = _outcome_variance(records)
    if blocker:
        return {"available": False, "reason": blocker}

    names = set()
    for r in records:
        names.update((_cap(r, "components") or {}).keys())

    rows = []
    for name in sorted(names):
        xs, ys = [], []
        for r in records:
            o = _outcome_of(r)
            if not o:
                continue
            blk = (_cap(r, "components") or {}).get(name) or {}
            s = _f(blk.get("score"))
            if s is None:
                continue
            xs.append(s)
            ys.append(1.0 if o == "WIN" else 0.0)

        if len(xs) < MIN_SAMPLE:
            continue
        c = _corr(xs, ys)
        if c is None:
            rows.append({"component": name, "n": len(xs), "corr": None,
                         "verdict": "CONSTANT -- score never varies"})
            continue
        rows.append({
            "component": name, "n": len(xs), "corr": round(c, 4),
            "verdict": ("PREDICTIVE" if c >= WEAK_CORRELATION else
                        "INVERTED" if c <= -WEAK_CORRELATION else
                        "NO INFORMATION"),
        })

    rows.sort(key=lambda r: -(abs(r["corr"]) if r["corr"] is not None else -1))
    return {
        "available": True,
        "resolved": n_res,
        "components": rows,
        "informative": [r["component"] for r in rows
                        if r["verdict"] in ("PREDICTIVE", "INVERTED")],
    }


# ------------------------------------------------------------
# CONFIRMATION QUALITY
# ------------------------------------------------------------

def confirmation_quality(records) -> Dict[str, Any]:
    """
    Which confirmation tier actually decides trades, and is it worth
    anything?

    entry_engine.check_discount_confirmation() has four tiers scored
    95/85/80/60. The bottom one is `close > open` for a BUY -- the
    candle closed green -- which on M1 is close to a coin flip. The
    three above it require real structure.

    Measured on a 4240-decision EURUSD replay: 49 of 52 confirmed
    entries came from the score-60 tier. So "confirmed" almost always
    meant "this candle happened to close in our direction", and the
    entry engine's approved setups went on to win 23.1% while the ones
    it REJECTED for lacking confirmation won 35.3%.

    A tier that fires on 94% of confirmations and carries no
    information is not a filter, and it is invisible in any aggregate
    that does not split by tier -- which is why this is its own section.
    """
    conf = [r for r in records if _cap(r, "confirmation_is_confirmed")]
    if not conf:
        return {"available": False,
                "reason": "no decision recorded a confirmation tier "
                          "(pre-dates confirmation_type capture)"}

    by_tier: Dict[str, List[Any]] = {}
    for r in conf:
        tier = str(_cap(r, "confirmation_type") or "UNKNOWN")
        by_tier.setdefault(tier, []).append(r)

    rows = []
    for tier, group in sorted(by_tier.items(), key=lambda kv: -len(kv[1])):
        blk = _summary_block(group, "")
        score = _f(_cap(group[0], "confirmation_score"))
        rows.append({
            "tier": tier,
            "score": score,
            "n": len(group),
            "pct_of_confirmations": round(len(group) / len(conf) * 100, 1),
            "win_rate_pct": blk["win_rate_pct"],
            "expectancy_r": blk["expectancy_r"],
        })

    weakest = [r for r in rows if (r["score"] or 0) <= 60]
    weak_share = sum(r["pct_of_confirmations"] for r in weakest)

    return {
        "available": True,
        "confirmed": len(conf),
        "tiers": rows,
        "weak_tier_share_pct": round(weak_share, 1),
        "verdict": ("DOMINATED BY THE WEAKEST TIER -- 'confirmation' mostly "
                    "means the candle closed the right way"
                    if weak_share >= 60 else
                    "mixed -- structural tiers carry a real share"
                    if weak_share >= 25 else
                    "structural tiers dominate"),
    }


# ------------------------------------------------------------
# COST STRUCTURE
# ------------------------------------------------------------

def cost_structure(records) -> Dict[str, Any]:
    """
    Can these trades survive their own cost of entry?

    A position crosses the spread on the way in, so the spread is a
    fixed head start given to the losing side: the stop sits
    (stop - spread) away while the target sits (target + spread) away.
    When the spread is a large fraction of the stop, that asymmetry
    decides outcomes on its own and no amount of signal quality
    survives it.

    This is here as a permanent check because the first XAGUSD replay
    found spread/stop >= 0.56 on ALL 1856 decisions, median 0.70, with
    22.8% of them carrying a spread wider than the entire stop -- and
    nothing anywhere in the funnel, the counterfactuals or the family
    attribution surfaced it. It presented as "the strategy has no
    edge", which was true and completely misleading: the stop was
    being derived from the account's risk budget rather than from the
    market, so it landed near the spread by construction.

    A one-off discovery that is not wired into the report is a
    discovery that has to be made again.
    """
    rows = []
    for r in records:
        spread = _f(_cap(r, "spread_pips"))
        stop = _f(_cap(r, "sl_pips"))
        if spread is None or stop is None or stop <= 0:
            continue
        rows.append((spread / stop, r))

    if not rows:
        return {"available": False,
                "reason": "no decision carried both a spread and a stop distance"}

    ratios = sorted(x for x, _ in rows)
    n = len(ratios)
    median = ratios[n // 2]
    over_1 = sum(1 for x in ratios if x > 1.0)

    buckets = [(0.0, 0.20), (0.20, 0.34), (0.34, 0.50),
               (0.50, 0.80), (0.80, float("inf"))]
    table = []
    for lo, hi in buckets:
        sel = [rec for x, rec in rows if lo <= x < hi]
        if not sel:
            continue
        blk = _summary_block(sel, "")
        table.append({
            "bucket": f"{lo:.2f}-{hi:.2f}" if hi != float("inf") else f"{lo:.2f}+",
            "n": len(sel),
            "win_rate_pct": blk["win_rate_pct"],
            "expectancy_r": blk["expectancy_r"],
        })

    return {
        "available": True,
        "n": n,
        "median_spread_to_stop": round(median, 3),
        "min_spread_to_stop": round(ratios[0], 3),
        "max_spread_to_stop": round(ratios[-1], 3),
        "spread_exceeds_stop_count": over_1,
        "spread_exceeds_stop_pct": round(over_1 / n * 100, 1),
        "buckets": table,
        # A median above a third means the cost of entry is a first-order
        # term in the outcome rather than a friction on it.
        "verdict": ("SEVERE -- the spread, not the setup, decides these trades"
                    if median > 0.50 else
                    "ELEVATED -- entry cost is a material drag"
                    if median > 0.34 else
                    "acceptable -- stops are wide relative to entry cost"),
    }


# ------------------------------------------------------------
# 1. GATE FUNNEL
# ------------------------------------------------------------

def gate_funnel(records) -> Dict[str, Any]:
    """
    Where decisions die, in pipeline order.

    Each stage counts decisions that reached it AND passed. The biggest
    single drop is the binding constraint on the whole system, and it is
    usually not the one people assume.
    """
    total = len(records)
    stages = [
        ("analysed successfully", lambda r: r.get("success")),
        ("direction selected", lambda r: _cap(r, "direction") in ("BUY", "SELL")),
        ("probability >= floor", lambda r: (_f(_cap(r, "probability")) or 0) >= 75),
        ("had entry signals", lambda r: (_f(_cap(r, "signal_count")) or 0) > 0),
        ("at discount zone", lambda r: bool(_cap(r, "discount_at_zone"))),
        ("discount quality ok", lambda r: _cap(r, "discount_quality")
            not in (None, "NO_DISCOUNT", "UNKNOWN")),
        ("timing ready", lambda r: bool(_cap(r, "timing_ready"))),
        # engine_qualified, not should_enter: the veto and the R:R floor
        # both clear should_enter, so using it here would fold three
        # different rejections into one stage and hide which one fired.
        ("entry engine qualified",
         lambda r: bool(_cap(r, "engine_qualified")
                        if _cap(r, "engine_qualified") is not None
                        else _cap(r, "should_enter"))),
        ("no hard veto", lambda r: not _cap(r, "veto_triggered")),
        ("R:R valid", lambda r: bool(_cap(r, "rr_valid"))),
        ("R:R >= 2.0", lambda r: (_f(_cap(r, "rr_ratio")) or 0) >= 2.0),
        ("ENTERED", lambda r: bool(r.get("entry_triggered"))),
    ]
    # Genuinely cumulative: each stage is applied only to what survived
    # the previous ones. An independent per-stage count produces negative
    # "lost" figures and hides the real bottleneck, because a decision
    # that already died upstream still passes a later test.
    rows = []
    surviving = list(records)
    for name, test in stages:
        before = len(surviving)
        surviving = [r for r in surviving if _safe(test, r)]
        after = len(surviving)
        # Independent pass rate too: "of everything, how many would clear
        # this stage on its own". A stage with a high independent rate but
        # a big cumulative loss is being starved by an upstream gate, not
        # rejecting on its own merits.
        independent = sum(1 for r in records if _safe(test, r))
        rows.append({
            "stage": name,
            "reached": before,
            "passed": after,
            "lost_here": before - after,
            "pct_of_total": round(after / total * 100, 2) if total else None,
            "independent_pass_pct": round(independent / total * 100, 2) if total else None,
        })

    biggest = max(rows, key=lambda x: x["lost_here"]) if rows else None
    starved = [r["stage"] for r in rows
               if r["reached"] == 0 and r["independent_pass_pct"]
               and r["independent_pass_pct"] > 20]
    return {
        "total_decisions": total,
        "stages": rows,
        "biggest_bottleneck": biggest["stage"] if biggest else None,
        "biggest_bottleneck_lost": biggest["lost_here"] if biggest else None,
        "starved_stages": starved,
        "note": ("Cumulative: each stage sees only survivors of the previous. "
                 "independent_pass_pct is how many of ALL decisions would clear "
                 "that stage alone -- a high independent rate with zero reached "
                 "means an upstream gate is starving it, so tuning it changes "
                 "nothing."),
    }


def _safe(fn, r):
    try:
        return bool(fn(r))
    except Exception:
        return False


# ------------------------------------------------------------
# 2. GATE COUNTERFACTUAL  -- the important one
# ------------------------------------------------------------

def gate_counterfactual(records) -> Dict[str, Any]:
    """
    For each gate: how did the setups it REJECTED actually perform?

    A gate earns its place by rejecting setups that would have lost. If
    the setups a gate blocks win MORE often than the ones it passes, the
    gate is inverted and is actively costing money. Nothing in a
    conventional backtest surfaces this, because rejected setups never
    get an outcome.
    """
    gates = {
        "probability_floor": lambda r: (_f(_cap(r, "probability")) or 0) < 75,
        "no_entry_signals": lambda r: (_f(_cap(r, "signal_count")) or 0) == 0,
        "not_at_discount": lambda r: not _cap(r, "discount_at_zone"),
        "discount_quality": lambda r: _cap(r, "discount_quality") in ("NO_DISCOUNT", "UNKNOWN"),
        "timing_not_ready": lambda r: not _cap(r, "timing_ready"),
        "hard_veto": lambda r: bool(_cap(r, "veto_triggered")),
        "rr_below_floor": lambda r: (_f(_cap(r, "rr_ratio")) or 0) < 2.0,
        "conviction_failed": lambda r: _cap(r, "conviction_passed") is False,
        "gnn_conflict": lambda r: bool(_cap(r, "gnn_conflict")),
        "liquidity_opposed": lambda r: _cap(r, "liquidity_aligned") is False,
        "zone_opposes_direction": lambda r: (
            _cap(r, "zone_expected_direction") is not None
            and _cap(r, "direction") is not None
            and _cap(r, "zone_expected_direction") != _cap(r, "direction")),
        "premium_entry_on_buy": lambda r: (
            _cap(r, "direction") == "BUY"
            and (_f(_cap(r, "premium_position_pct")) or 0) > 75),
    }

    # NOTE: named blocked_reason, not `blocked` -- the per-gate loop below
    # binds `blocked` to a list of records, and the earlier collision made
    # the report emit raw record dumps in place of the reason string.
    n_res, blocked_reason = _outcome_variance(records)
    out = []
    for name, fires in gates.items():
        blocked = [r for r in records if _safe(fires, r)]
        allowed = [r for r in records if not _safe(fires, r)]
        b = _summary_block(blocked, "blocked")
        a = _summary_block(allowed, "allowed")
        if b["resolved"] < MIN_SAMPLE or a["resolved"] < MIN_SAMPLE:
            verdict = "insufficient sample"
            edge = None
        else:
            edge = round(a["win_rate_pct"] - b["win_rate_pct"], 1)
            if edge > 5:
                verdict = "HELPING -- blocks losers"
            elif edge < -5:
                verdict = "INVERTED -- blocks winners, costing money"
            else:
                verdict = "NEUTRAL -- no measurable discrimination"
        out.append({
            "gate": name,
            "fired_on": len(blocked),
            "fired_pct": round(len(blocked) / len(records) * 100, 1) if records else None,
            "blocked_win_rate": b["win_rate_pct"],
            "allowed_win_rate": a["win_rate_pct"],
            "blocked_expectancy_r": b["expectancy_r"],
            "allowed_expectancy_r": a["expectancy_r"],
            "discrimination_pts": edge,
            "verdict": verdict,
        })

    out.sort(key=lambda x: (x["discrimination_pts"] is None, x["discrimination_pts"] or 0))
    inverted = [g["gate"] for g in out if g["verdict"].startswith("INVERTED")]
    useless = [g["gate"] for g in out if g["verdict"].startswith("NEUTRAL")]
    return {
        "measurable": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "n_resolved": n_res,
        "gates": out,
        "inverted_gates": inverted,
        "non_discriminating_gates": useless,
        "note": ("discrimination_pts = allowed win rate minus blocked win rate. "
                 "Positive means the gate blocks losers (good). Negative means "
                 "it blocks winners. Near zero means it is filtering at random."),
    }


# ------------------------------------------------------------
# 3. EVIDENCE ATTRIBUTION
# ------------------------------------------------------------

def evidence_attribution(records) -> Dict[str, Any]:
    """
    Does each evidence family's contribution correlate with the outcome?

    A family whose contribution has no relationship to what happens next
    is noise being counted as confluence -- and because contributions
    compound through the chain, noise with a positive mean inflates every
    probability the system publishes.
    """
    n_res, blocked = _outcome_variance(records)
    if blocked:
        return {"available": False, "reason": blocked, "n_resolved": n_res}
    resolved = [r for r in records if _outcome_of(r)]

    names = set()
    for r in resolved:
        names.update(k for k in (_cap(r, "contributions") or {})
                     if not k.endswith("_aligned"))

    rows = []
    for name in sorted(names):
        xs, ys, present = [], [], 0
        for r in resolved:
            v = _f((_cap(r, "contributions") or {}).get(name))
            if v is None:
                continue
            present += 1
            xs.append(v)
            ys.append(1.0 if _outcome_of(r) == "WIN" else 0.0)
        if present < MIN_SAMPLE:
            continue
        c = _corr(xs, ys)
        nonzero = sum(1 for v in xs if abs(v) > 0.001)
        mean = sum(xs) / len(xs)
        if c is None:
            verdict = "undefined (no variance)"
        elif abs(c) < WEAK_CORRELATION:
            verdict = "NO PREDICTIVE VALUE"
        elif c < 0:
            verdict = "INVERTED -- pushes the wrong way"
        else:
            verdict = "predictive"
        rows.append({
            "family": name,
            "n": present,
            "active_pct": round(nonzero / present * 100, 1),
            "mean_contribution": round(mean, 3),
            "correlation_with_win": round(c, 3) if c is not None else None,
            "verdict": verdict,
        })

    rows.sort(key=lambda x: (x["correlation_with_win"] is None,
                             x["correlation_with_win"] or 0))
    return {
        "available": True,
        "n_resolved": len(resolved),
        "families": rows,
        "inverted": [r["family"] for r in rows if r["verdict"].startswith("INVERTED")],
        "worthless": [r["family"] for r in rows if r["verdict"] == "NO PREDICTIVE VALUE"],
        "note": ("Correlation between a family's contribution and the "
                 "eventual win. A family with a positive mean contribution "
                 "and zero correlation is systematically inflating "
                 "probability while predicting nothing."),
    }


# ------------------------------------------------------------
# 4. FROZEN AND DEGENERATE FIELDS
# ------------------------------------------------------------

SCALAR_FIELDS = [
    "probability", "buy_probability", "sell_probability", "signal_count",
    "timing_confidence", "star_rating", "rr_ratio", "sl_pips", "tp_pips",
    "lot_size", "absorbed_total", "clamped_steps", "conviction_score",
    "atr_pips", "spread_pips", "volume_ratio",
    "candle_progress", "adx", "premium_position_pct", "coherence_violations",
]

CATEGORICAL_FIELDS = [
    "direction", "simple_action", "execution", "entry_status",
    "discount_quality", "zone_type", "zone_grade", "regime",
    "market_regime", "h1_trend", "family_direction", "smc_recommendation",
    "veto_reason",
]


# Fields the HARNESS cannot vary, whatever the code under test does.
# Reporting these as "dead code" sends you hunting a bug that isn't
# there while hiding the real problem, which is that the replay never
# exercises the gate at all.
#
# candle_progress: get_candle_progress_fixed() measures now-minus-bar-open
# against the bar duration. Live, MT5 returns the FORMING bar newest, so
# progress lands in [0,1). The replay serves only CLOSED bars and steps on
# bar boundaries, so elapsed always equals the full duration and the value
# clamps to 100%. The function is correct; the harness cannot move it.
# Consequence: entry_engine's min_candle_progress thresholds (40-75%) are
# never tested here, so LIVE will take FEWER trades than replay shows.
_HARNESS_INVARIANT_FIELDS = {
    "candle_progress": (
        "replay serves closed bars only, so progress always reads 100%; "
        "the live gate (min_candle_progress 40-75%) is NOT exercised -- "
        "expect live to trade less than this report suggests"
    ),
}


def frozen_fields(records) -> Dict[str, Any]:
    """
    Fields that never change, are always null, or are pinned at a bound.

    This is the hidden-issue detector. A field frozen across thousands of
    decisions means dead code, a broken feed, or a default nobody noticed
    -- and none of those announce themselves. A field pinned at a bound
    means the value is saturated and carries no information.

    Fields in _HARNESS_INVARIANT_FIELDS are reported separately: they are
    frozen by the test rig, not by the code, and chasing them as bugs
    wastes the audit's credibility.
    """
    n = len(records)
    frozen, always_null, mostly_null, pinned, low_variety = [], [], [], [], []
    not_exercised = []

    for field in SCALAR_FIELDS:
        vals = [_f(_cap(r, field)) for r in records]
        present = [v for v in vals if v is not None]
        if not present:
            always_null.append(field)
            continue
        if len(present) < n * 0.5:
            mostly_null.append({"field": field, "present_pct":
                                round(len(present) / n * 100, 1)})
        uniq = set(round(v, 6) for v in present)
        if len(uniq) == 1 and len(present) >= MIN_SAMPLE:
            entry = {"field": field, "value": present[0], "n": len(present)}
            if field in _HARNESS_INVARIANT_FIELDS:
                entry["why"] = _HARNESS_INVARIANT_FIELDS[field]
                not_exercised.append(entry)
            else:
                frozen.append(entry)
            continue
        top, count = Counter(round(v, 3) for v in present).most_common(1)[0]
        share = count / len(present)
        if share > 0.8 and len(present) >= MIN_SAMPLE:
            pinned.append({"field": field, "value": top,
                           "share_pct": round(share * 100, 1), "n": len(present)})

    for field in CATEGORICAL_FIELDS:
        vals = [_cap(r, field) for r in records]
        present = [v for v in vals if v is not None]
        if not present:
            always_null.append(field)
            continue
        counts = Counter(str(v) for v in present)
        if len(counts) == 1 and len(present) >= MIN_SAMPLE:
            entry = {"field": field, "value": present[0], "n": len(present)}
            if field in _HARNESS_INVARIANT_FIELDS:
                entry["why"] = _HARNESS_INVARIANT_FIELDS[field]
                not_exercised.append(entry)
            else:
                frozen.append(entry)
        elif len(counts) == 2 and len(present) >= MIN_SAMPLE * 5:
            low_variety.append({"field": field, "values": dict(counts)})

    return {
        "frozen": frozen,
        "not_exercised": not_exercised,
        "always_null": always_null,
        "mostly_null": mostly_null,
        "pinned_at_one_value": pinned,
        "low_variety": low_variety,
        "verdict": ("CLEAN" if not (frozen or always_null or pinned)
                    else "SUSPECT -- see entries above"),
        "note": ("A frozen field across many decisions is dead code, a "
                 "broken feed, or an unnoticed default. A pinned field is "
                 "saturated and carries no information."),
    }


# ------------------------------------------------------------
# 5. CLAMP FORENSICS
# ------------------------------------------------------------

def clamp_forensics(records) -> Dict[str, Any]:
    """
    Evidence computed and then discarded at the 5/95 bounds.

    If the probability regularly arrives at the ceiling before the chain
    finishes, later families contribute nothing and the chain is not
    doing confluence -- it is starting at the cap and subtracting
    penalties.
    """
    absorbed_by_step = defaultdict(float)
    hits_by_step = Counter()
    totals, clamped_counts, ledger_lens = [], [], []
    reconcile_failures = 0

    for r in records:
        t = _f(_cap(r, "absorbed_total"))
        if t is not None:
            totals.append(t)
        c = _f(_cap(r, "clamped_steps"))
        if c is not None:
            clamped_counts.append(c)
        if _cap(r, "ledger_reconciles") is False:
            reconcile_failures += 1
        ledger = _cap(r, "ledger") or []
        ledger_lens.append(len(ledger))
        for step in ledger:
            a = _f(step.get("absorbed"))
            if a and abs(a) > 0.05:
                absorbed_by_step[step.get("step")] += a
                hits_by_step[step.get("step")] += 1

    n = len(records)
    steps = [{"step": k, "total_absorbed": round(v, 1),
              "decisions_affected": hits_by_step[k],
              "pct_of_decisions": round(hits_by_step[k] / n * 100, 1) if n else None}
             for k, v in sorted(absorbed_by_step.items(),
                                key=lambda x: -abs(x[1]))]

    mean_clamped = (sum(clamped_counts) / len(clamped_counts)) if clamped_counts else None
    mean_len = (sum(ledger_lens) / len(ledger_lens)) if ledger_lens else None
    severity = "CLEAN"
    if mean_clamped and mean_len and mean_len > 0:
        share = mean_clamped / mean_len
        if share > 0.5:
            severity = ("SEVERE -- over half the chain runs at a bound; "
                        "confluence is not being applied")
        elif share > 0.25:
            severity = "SIGNIFICANT -- a quarter of the chain runs at a bound"
        elif share > 0.05:
            severity = "MINOR"

    return {
        "decisions": n,
        "mean_absorbed_per_decision": round(sum(totals) / len(totals), 2) if totals else None,
        "max_absorbed": round(max(totals), 2) if totals else None,
        "decisions_with_absorption": sum(1 for t in totals if abs(t) > 0.05),
        "mean_clamped_steps": round(mean_clamped, 1) if mean_clamped else None,
        "mean_chain_length": round(mean_len, 1) if mean_len else None,
        "by_step": steps,
        "ledger_reconcile_failures": reconcile_failures,
        "severity": severity,
    }


# ------------------------------------------------------------
# 6. CONTRADICTIONS
# ------------------------------------------------------------

def contradictions(records) -> Dict[str, Any]:
    """
    How often modules disagreed, and whether disagreement predicted failure.

    Disagreement that predicts nothing is noise. Disagreement that
    predicts losses is a signal the system is currently ignoring.
    """
    checks = {
        "gnn_opposes_direction": lambda r: bool(_cap(r, "gnn_conflict")),
        "liquidity_opposes_direction": lambda r: _cap(r, "liquidity_aligned") is False,
        "zone_type_opposes_direction": lambda r: (
            _cap(r, "zone_expected_direction") is not None
            and _cap(r, "zone_expected_direction") != _cap(r, "direction")),
        "smc_opposes_direction": lambda r: (
            (_cap(r, "smc_recommendation") == "BEARISH" and _cap(r, "direction") == "BUY")
            or (_cap(r, "smc_recommendation") == "BULLISH" and _cap(r, "direction") == "SELL")),
        "buying_in_premium": lambda r: (
            _cap(r, "direction") == "BUY"
            and (_f(_cap(r, "premium_position_pct")) or 0) > 75),
        "selling_in_discount": lambda r: (
            _cap(r, "direction") == "SELL"
            and (_f(_cap(r, "premium_position_pct")) or 100) < 25),
        "coherence_violation": lambda r: (_f(_cap(r, "coherence_violations")) or 0) > 0,
        "conviction_hard_fail": lambda r: len(_cap(r, "conviction_hard_fails") or []) > 0,
        "candle_not_ready": lambda r: (_f(_cap(r, "candle_progress")) or 100) < 50,
    }

    n_res, blocked = _outcome_variance(records)
    rows = []
    for name, fires in checks.items():
        hit = [r for r in records if _safe(fires, r)]
        miss = [r for r in records if not _safe(fires, r)]
        h, m = _summary_block(hit, "with"), _summary_block(miss, "without")
        if h["resolved"] < MIN_SAMPLE or m["resolved"] < MIN_SAMPLE:
            impact, verdict = None, "insufficient sample"
        else:
            impact = round(h["win_rate_pct"] - m["win_rate_pct"], 1)
            if impact < -5:
                verdict = "PREDICTS LOSSES -- worth acting on"
            elif impact > 5:
                verdict = "predicts wins -- contradiction may be misread"
            else:
                verdict = "no measurable effect"
        rows.append({
            "contradiction": name,
            "occurred": len(hit),
            "occurred_pct": round(len(hit) / len(records) * 100, 1) if records else None,
            "win_rate_when_present": h["win_rate_pct"],
            "win_rate_when_absent": m["win_rate_pct"],
            "impact_pts": impact,
            "verdict": verdict,
        })

    rows.sort(key=lambda x: (x["impact_pts"] is None, x["impact_pts"] or 0))
    return {
        "measurable": blocked is None,
        "blocked_reason": blocked,
        "n_resolved": n_res,
        "checks": rows,
        "actionable": [r["contradiction"] for r in rows
                       if r["verdict"].startswith("PREDICTS LOSSES")],
    }


# ------------------------------------------------------------
# 7. DATA INTEGRITY
# ------------------------------------------------------------

def data_integrity(records, feed=None) -> Dict[str, Any]:
    """
    Problems in the inputs rather than the logic.

    Impossible values, decisions on incomplete bars, timestamp gaps and
    failed analyses. Any of these makes the rest of the report suspect.
    """
    n = len(records)
    failed = [r for r in records if not r.get("success")]
    issues = []

    def _flag(name, test, why):
        hits = [r for r in records if _safe(test, r)]
        if hits:
            issues.append({"issue": name, "count": len(hits),
                           "pct": round(len(hits) / n * 100, 1) if n else None,
                           "why_it_matters": why})

    _flag("decision on incomplete candle",
          lambda r: (_f(_cap(r, "candle_progress")) or 100) < 50,
          "bar values still moving; replay and live will disagree")
    _flag("spread at or above max",
          lambda r: (_f(_cap(r, "spread_pips")) or 0) >= 40,
          "fills will be materially worse than modelled")
    _flag("spread exceeds stop distance",
          lambda r: ((_f(_cap(r, "spread_pips")) or 0)
                     > (_f(_cap(r, "sl_pips")) or 1e9)),
          "trade is underwater beyond its own stop at entry")
    _flag("volume ratio below 0.2",
          lambda r: (_f(_cap(r, "volume_ratio")) or 1) < 0.2,
          "thin liquidity; indicator readings unreliable")
    _flag("R:R marked invalid",
          lambda r: _cap(r, "rr_valid") is False,
          "risk/reward could not be measured")
    _flag("stop distance pinned at the MAX_SL_PIPS cap",
          lambda r: (_f(_cap(r, "sl_pips")) or 0) >= 1000,
          "position sizing failed and the stop fell back to the cap -- "
          "R:R and every performance number below are meaningless")
    _flag("stop distance more than 10x the ATR",
          lambda r: ((_f(_cap(r, "sl_pips")) or 0)
                     > (_f(_cap(r, "atr_pips")) or 1e9) * 10),
          "stop is implausibly wide for the instrument's volatility, "
          "which inflates the win rate while destroying R:R")
    _flag("zero or negative stop distance",
          lambda r: (_f(_cap(r, "sl_pips")) or 1) <= 0,
          "position sizing and R:R are both undefined")
    _flag("probability at a bound",
          lambda r: _f(_cap(r, "probability")) in (5.0, 95.0),
          "saturated; the number carries no gradient")
    _flag("ledger did not reconcile",
          lambda r: _cap(r, "ledger_reconciles") is False,
          "probability moved without being recorded")
    _flag("market reported closed",
          lambda r: _cap(r, "session_open") is False,
          "decision taken outside trading hours")

    gaps = []
    ts = [r.get("decision_timestamp") for r in records]
    ts = [t for t in ts if t is not None]
    if len(ts) > 2:
        deltas = [b - a for a, b in zip(ts, ts[1:])]
        median = sorted(deltas)[len(deltas) // 2]
        for i, d in enumerate(deltas):
            if median > 0 and d > median * 10:
                gaps.append({"after_index": i, "gap_seconds": d,
                             "gap_hours": round(d / 3600, 1)})
    return {
        "decisions": n,
        "failed_analyses": len(failed),
        "failed_pct": round(len(failed) / n * 100, 1) if n else None,
        "sample_failures": [str(r.get("rejection_reason"))[:120] for r in failed[:5]],
        "issues": sorted(issues, key=lambda x: -x["count"]),
        "timestamp_gaps": gaps[:10],
        "gap_count": len(gaps),
        "feed_stats": getattr(feed, "stats", None),
    }


# ------------------------------------------------------------
# 8. REGIME / TEMPORAL / DIRECTION BREAKDOWNS
# ------------------------------------------------------------

def _bucketed(records, key_fn, label) -> Dict[str, Any]:
    groups = defaultdict(list)
    for r in records:
        try:
            k = key_fn(r)
        except Exception:
            k = None
        if k is not None:
            groups[str(k)].append(r)
    rows = []
    for k, group in sorted(groups.items()):
        b = _summary_block(group, k)
        if b["resolved"] >= 5:
            rows.append({"bucket": k, **{x: b[x] for x in
                        ("n", "resolved", "win_rate_pct", "expectancy_r")}})
    concentrated = None
    if len(rows) > 1:
        best = max(rows, key=lambda x: x["expectancy_r"] or -99)
        share = best["resolved"] / max(1, sum(r["resolved"] for r in rows))
        if (best["expectancy_r"] or 0) > 0 and share < 0.3:
            concentrated = (f"positive expectancy concentrated in {best['bucket']} "
                            f"({share:.0%} of resolved trades) -- likely a sample "
                            f"artifact rather than a regime edge")
    return {"dimension": label, "buckets": rows, "warning": concentrated}


def breakdowns(records) -> Dict[str, Any]:
    def adx_bucket(r):
        v = _f(_cap(r, "adx"))
        if v is None:
            return None
        return "ADX<20" if v < 20 else "ADX 20-30" if v < 30 else "ADX 30-45" if v < 45 else "ADX>45"

    def atr_bucket(r):
        v = _f(_cap(r, "atr_pips"))
        if v is None:
            return None
        return "ATR<30" if v < 30 else "ATR 30-60" if v < 60 else "ATR>60"

    def spread_bucket(r):
        v = _f(_cap(r, "spread_pips"))
        if v is None:
            return None
        return "spread<15" if v < 15 else "spread 15-30" if v < 30 else "spread>30"

    def hour(r):
        t = r.get("decision_timestamp")
        return f"{int((t // 3600) % 24):02d}:00 UTC" if t else None

    def prob_bucket(r):
        v = _f(_cap(r, "probability"))
        if v is None:
            return None
        return f"{int(v // 10) * 10}-{int(v // 10) * 10 + 10}%"

    return {
        "by_direction": _bucketed(records, lambda r: _cap(r, "direction"), "direction"),
        "by_adx": _bucketed(records, adx_bucket, "trend strength"),
        "by_atr": _bucketed(records, atr_bucket, "volatility"),
        "by_spread": _bucketed(records, spread_bucket, "spread"),
        "by_regime": _bucketed(records, lambda r: _cap(r, "regime"), "trading regime"),
        "by_h1_trend": _bucketed(records, lambda r: _cap(r, "h1_trend"), "H1 trend"),
        "by_hour": _bucketed(records, hour, "hour of day"),
        "by_probability": _bucketed(records, prob_bucket, "stated probability"),
    }


def direction_bias(records) -> Dict[str, Any]:
    """A system that only ever goes one way is fitting a trend, not trading."""
    dirs = Counter(_cap(r, "direction") for r in records
                   if _cap(r, "direction") in ("BUY", "SELL"))
    total = sum(dirs.values())
    if not total:
        return {"available": False}
    buy_pct = dirs.get("BUY", 0) / total * 100
    verdict = "balanced"
    if buy_pct > 80 or buy_pct < 20:
        verdict = ("SEVERE BIAS -- the system barely trades one side; results "
                   "reflect the sample's drift, not an edge")
    elif buy_pct > 70 or buy_pct < 30:
        verdict = "notable bias"
    return {"available": True, "buy": dirs.get("BUY", 0), "sell": dirs.get("SELL", 0),
            "buy_pct": round(buy_pct, 1), "verdict": verdict}


def threshold_proximity(records) -> Dict[str, Any]:
    """
    How close gates ran to their thresholds.

    A gate always clearing by a hair is fragile; a gate always clearing
    by a mile is not a gate.
    """
    checks = [
        ("probability vs 75", "probability", 75.0),
        ("R:R vs 2.0", "rr_ratio", 2.0),
        ("ADX vs 22", "adx", 22.0),
        ("spread vs 40", "spread_pips", 40.0),
        ("timing vs 75", "timing_confidence", 75.0),
    ]
    rows = []
    for label, field, threshold in checks:
        vals = [_f(_cap(r, field)) for r in records]
        vals = [v for v in vals if v is not None]
        if len(vals) < MIN_SAMPLE:
            continue
        margins = [v - threshold for v in vals]
        near = sum(1 for m in margins if abs(m) <= threshold * 0.02)
        rows.append({
            "check": label, "n": len(vals), "threshold": threshold,
            "mean_margin": round(sum(margins) / len(margins), 2),
            "min_margin": round(min(margins), 2),
            "max_margin": round(max(margins), 2),
            "near_miss_pct": round(near / len(vals) * 100, 1),
        })
    return {"checks": rows,
            "note": ("near_miss_pct is the share of decisions landing within "
                     "2% of the threshold. High values mean the gate is "
                     "deciding on noise.")}


# ------------------------------------------------------------
# 9. REJECTION CLUSTERING
# ------------------------------------------------------------

def rejection_clusters(records) -> Dict[str, Any]:
    rejected = [r for r in records if not r.get("entry_triggered")]
    raw = Counter(str(r.get("rejection_reason"))[:70] for r in rejected)

    def family(reason: str) -> str:
        low = reason.lower()
        for key, name in (("veto", "hard veto"), ("no entry signals", "no signals"),
                          ("invalid zone", "zone invalid"),
                          ("discount", "not at discount"),
                          ("risk:reward", "R:R floor"),
                          ("probability", "probability floor"),
                          ("expected value", "EV gate"),
                          ("do nothing", "no action"), ("timing", "timing")):
            if key in low:
                return name
        return "other"

    fam = Counter(family(str(r.get("rejection_reason"))) for r in rejected)
    with_outcome = defaultdict(list)
    for r in rejected:
        with_outcome[family(str(r.get("rejection_reason")))].append(r)

    rows = []
    for name, count in fam.most_common():
        b = _summary_block(with_outcome[name], name)
        rows.append({"family": name, "count": count,
                     "pct": round(count / len(rejected) * 100, 1) if rejected else None,
                     "would_have_won_pct": b["win_rate_pct"],
                     "would_have_expectancy_r": b["expectancy_r"]})
    return {
        "total_rejected": len(rejected),
        "by_family": rows,
        "top_verbatim": [{"reason": k, "n": v} for k, v in raw.most_common(15)],
        "note": ("would_have_won_pct is the shadow outcome of setups this "
                 "family of rejection blocked. High values with positive "
                 "expectancy mean the rejection is costing money."),
    }


# ------------------------------------------------------------
# TOP LEVEL
# ------------------------------------------------------------

def triage(rep: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read the whole report and rank what is actually wrong.

    A twelve-section forensic dump is only useful if you know which
    section to read first. This applies the same reasoning a reviewer
    would, in severity order, and states plainly when the run cannot
    support conclusions at all -- which is itself the most important
    finding when it is true.
    """
    findings = []

    def add(severity, title, detail, action):
        text = str(detail)
        if len(text) > 400:
            text = text[:400] + " ... (truncated)"
        findings.append({"severity": severity, "finding": title,
                         "detail": text, "action": action})

    # Cost structure first: when the spread is a large fraction of the
    # stop, every gate verdict, family correlation and win rate below is
    # being measured on trades that were already losing at entry. That
    # makes it the thing to fix before trusting any other number here.
    cs = rep.get("cost_structure") or {}
    if cs.get("available"):
        median = cs["median_spread_to_stop"]
        if median > 0.50:
            add("BLOCKING", "the spread, not the strategy, is deciding outcomes",
                f"median spread/stop {median:.2f}; "
                f"{cs['spread_exceeds_stop_pct']}% of decisions carry a spread wider "
                f"than the entire stop",
                "widen stops relative to entry cost (or size positions from the stop "
                "instead of from margin) -- gate tuning cannot fix this")
        elif median > 0.34:
            add("HIGH", "entry cost is a material drag on every trade",
                f"median spread/stop {median:.2f}",
                "widen stops or trade a cheaper instrument/session")

    ci = rep.get("causal_invariance") or {}
    if ci.get("available"):
        if ci.get("regime_contingent"):
            add("HIGH", "factors that reverse between environments",
                ", ".join(ci["regime_contingent"]),
                "they carry information but pooling it across regimes cancels it "
                "out -- condition on regime or stop using them")
        if not ci.get("causal_candidates"):
            add("HIGH", "no factor is invariant across environments",
                f"every candidate tested under {len(ci.get('splits', []))} splits "
                f"is either inert or regime-contingent",
                "the evidence stack has no stable mechanism to build on -- new "
                "features are needed, not new weights on these")

    di = rep["data_integrity"]
    if di["failed_analyses"] and di["failed_pct"] > 5:
        add("BLOCKING", "analyses are failing",
            f"{di['failed_analyses']} of {di['decisions']} decisions errored "
            f"({di['failed_pct']}%)",
            "send the sample failures; the rest of this report is unreliable")

    su = rep["shadow_universe"]
    # A win rate this high is almost never a strategy result. It means the
    # stop is far away and the target is close, so price reaches the target
    # first nearly every time -- for a tiny R each. Real proof: a replay
    # whose stop had fallen back to the 1000-pip cap reported 97% wins at
    # +0.022R against a 0.36 planned R:R.
    if su["win_rate_pct"] is not None and su["win_rate_pct"] > 90:
        add("BLOCKING", "win rate above 90% -- check the stop distance",
            f"{su['win_rate_pct']}% wins at {su['expectancy_r']}R expectancy",
            "a far stop and a near target produce this; confirm sl_pips "
            "and R:R match your live payload before reading anything else")
    if su["resolved"] < MIN_SAMPLE:
        add("BLOCKING", "too few resolved outcomes",
            f"{su['resolved']} of {su['n']} decisions reached stop or target",
            "run a longer history, or raise max holding bars")

    gc = rep["gate_counterfactual"]
    if not gc.get("measurable", True):
        add("BLOCKING", "gate performance not measurable",
            gc.get("blocked_reason", ""),
            "fix the sample before drawing conclusions about any gate")
    else:
        for g in gc["gates"]:
            if g["verdict"].startswith("INVERTED"):
                add("CRITICAL", f"gate '{g['gate']}' blocks winners",
                    f"setups it blocked won {g['blocked_win_rate']}% vs "
                    f"{g['allowed_win_rate']}% for those it allowed "
                    f"({g['discrimination_pts']} pts)",
                    "this gate is costing money -- loosen or remove it")
        for g in gc["gates"]:
            if g["verdict"].startswith("NEUTRAL") and (g["fired_pct"] or 0) > 20:
                add("HIGH", f"gate '{g['gate']}' filters at random",
                    f"fires on {g['fired_pct']}% of decisions with no measurable "
                    f"discrimination",
                    "it is reducing trade count without improving quality")

    gf = rep["gate_funnel"]
    top = gf.get("biggest_bottleneck")
    if top and gf.get("biggest_bottleneck_lost", 0) > gf["total_decisions"] * 0.5:
        add("HIGH", f"'{top}' is the binding constraint",
            f"{gf['biggest_bottleneck_lost']} of {gf['total_decisions']} decisions "
            f"die there",
            "nothing downstream of it can matter until it is loosened")
    if gf.get("starved_stages"):
        add("MEDIUM", "stages never reached",
            f"{', '.join(gf['starved_stages'])} are starved by upstream gates",
            "tuning them will change nothing")

    ea = rep["evidence_attribution"]
    if ea.get("available"):
        for f in ea["families"]:
            if f["verdict"].startswith("INVERTED"):
                add("CRITICAL", f"evidence family '{f['family']}' is inverted",
                    f"correlation with winning is {f['correlation_with_win']}",
                    "it is pushing probability the wrong way")
        if ea.get("worthless"):
            add("HIGH", "families with no predictive value",
                ", ".join(ea["worthless"]),
                "they inflate confluence while predicting nothing")

    cf = rep["clamp_forensics"]
    if cf["severity"].startswith("SEVERE"):
        add("CRITICAL", "the probability chain is saturated", cf["severity"],
            "raise the cap or rescale contributions -- most evidence is discarded")
    elif cf["severity"].startswith("SIGNIFICANT"):
        add("HIGH", "significant clamping", cf["severity"],
            "a quarter of the chain contributes nothing")
    if cf["ledger_reconcile_failures"]:
        add("HIGH", "probability moved unrecorded",
            f"{cf['ledger_reconcile_failures']} decisions failed ledger reconciliation",
            "there is a mutation path outside the ledger")

    ff = rep["frozen_fields"]
    for f in ff["frozen"]:
        add("HIGH", f"'{f['field']}' never changes",
            f"always {f['value']!r} across {f['n']} decisions",
            "dead code, a broken feed, or an unnoticed default")
    for f in ff.get("not_exercised", []):
        add("MEDIUM", f"'{f['field']}' is not exercised by the replay",
            f"pinned at {f['value']!r} across {f['n']} decisions by the harness, "
            f"not by the code",
            f"{f['why']} -- this is a BACKTEST FIDELITY gap, not a bug to hunt")
    if ff["always_null"]:
        add("MEDIUM", "fields always null", ", ".join(ff["always_null"]),
            "the producing module may not be running")

    co = rep["contradictions"]
    for c in co.get("actionable", []):
        add("HIGH", f"'{c}' predicts losses",
            "setups with this contradiction lose materially more often",
            "consider making it a veto")

    db = rep["direction_bias"]
    if db.get("available") and db["verdict"].startswith("SEVERE"):
        add("HIGH", "severe direction bias",
            f"{db['buy_pct']}% of decisions were BUY",
            "results reflect the sample's drift, not an edge")

    for key, block in rep["breakdowns"].items():
        if block.get("warning"):
            add("MEDIUM", f"edge concentrated by {block['dimension']}",
                block["warning"], "treat the headline expectancy with suspicion")

    order = {"BLOCKING": 0, "CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    return {
        "findings": findings,
        "counts": dict(Counter(f["severity"] for f in findings)),
        "headline": (findings[0]["finding"] if findings
                     else "no structural problems detected"),
    }


def forensic_report(records, feed=None) -> Dict[str, Any]:
    rep = {
        "data_integrity": data_integrity(records, feed),
        "gate_funnel": gate_funnel(records),
        "gate_counterfactual": gate_counterfactual(records),
        "evidence_attribution": evidence_attribution(records),
        "clamp_forensics": clamp_forensics(records),
        "contradictions": contradictions(records),
        "frozen_fields": frozen_fields(records),
        "threshold_proximity": threshold_proximity(records),
        "direction_bias": direction_bias(records),
        "breakdowns": breakdowns(records),
        "rejections": rejection_clusters(records),
        "shadow_universe": _summary_block(records, "all decisions, shadow outcome"),
        "cost_structure": cost_structure(records),
        "confirmation_quality": confirmation_quality(records),
        "component_attribution": component_attribution(records),
        "score_attribution": score_attribution(records),
        "causal_invariance": _causal_consensus(records),
    }
    rep["triage"] = triage(rep)
    return rep


def _causal_consensus(records):
    """
    Stage 4 (invariant causal prediction), run as a standing diagnostic.

    Section 5's evidence attribution already asks "does this family
    correlate with winning?". This asks the sharper question: "does it
    correlate the SAME WAY in every environment?" -- which is what
    separates a factor with a mechanism behind it from one that is
    really a bet on the current regime.

    Imported lazily so a failure in the causal module degrades this one
    section rather than taking down the whole report.
    """
    try:
        from core.causal_invariance import causal_consensus_report
        return causal_consensus_report(records)
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}


def _hdr(title):
    return ["", "=" * 74, title, "=" * 74]


def format_forensics(rep: Dict[str, Any]) -> str:
    L: List[str] = []

    tri = rep.get("triage", {})
    L += _hdr("0. TRIAGE  (read this first)")
    counts = tri.get("counts", {})
    L.append(f"  {counts or 'nothing flagged'}")
    L.append(f"  headline: {tri.get('headline')}")
    L.append("")
    for i, f in enumerate(tri.get("findings", [])[:15], 1):
        L.append(f"  {i:>2}. [{f['severity']}] {f['finding']}")
        L.append(f"      {f['detail']}")
        L.append(f"      -> {f['action']}")

    di = rep["data_integrity"]
    L += _hdr("1. DATA INTEGRITY")
    L.append(f"  decisions {di['decisions']} | failed analyses {di['failed_analyses']} "
             f"({di['failed_pct']}%) | timestamp gaps {di['gap_count']}")
    for f in di["sample_failures"]:
        L.append(f"    failure: {f}")
    if not di["issues"]:
        L.append("  no input-quality issues detected")
    for i in di["issues"]:
        L.append(f"  [{i['count']:>6}] {i['pct']:>5}%  {i['issue']}")
        L.append(f"           -> {i['why_it_matters']}")

    cs = rep.get("cost_structure") or {}
    if cs.get("available"):
        L += _hdr("1b. COST STRUCTURE  (can a trade survive its own spread?)")
        L.append(f"  spread/stop: median {cs['median_spread_to_stop']} "
                 f"(min {cs['min_spread_to_stop']}, max {cs['max_spread_to_stop']})")
        L.append(f"  spread wider than the WHOLE stop: {cs['spread_exceeds_stop_count']} "
                 f"({cs['spread_exceeds_stop_pct']}%) -- these lose at entry, before price moves")
        L.append(f"  verdict: {cs['verdict']}")
        L.append(f"  {'spread/stop':<14} {'n':>6} {'win%':>7} {'exp R':>8}")
        for b in cs["buckets"]:
            L.append(f"  {b['bucket']:<14} {b['n']:>6} "
                     f"{(b['win_rate_pct'] if b['win_rate_pct'] is not None else '-'):>7} "
                     f"{(b['expectancy_r'] if b['expectancy_r'] is not None else '-'):>8}")

    cq = rep.get("confirmation_quality") or {}
    if cq.get("available"):
        L += _hdr("1c. CONFIRMATION QUALITY  (which tier actually decides?)")
        L.append(f"  confirmed entries: {cq['confirmed']}   "
                 f"weakest-tier share: {cq['weak_tier_share_pct']}%")
        L.append(f"  verdict: {cq['verdict']}")
        L.append(f"  {'tier':<28} {'score':>6} {'n':>6} {'share':>7} {'win%':>7} {'exp R':>8}")
        for t in cq["tiers"]:
            L.append(f"  {t['tier']:<28} {str(t['score']):>6} {t['n']:>6} "
                     f"{t['pct_of_confirmations']:>6}% "
                     f"{(t['win_rate_pct'] if t['win_rate_pct'] is not None else '-'):>7} "
                     f"{(t['expectancy_r'] if t['expectancy_r'] is not None else '-'):>8}")

    su = rep["shadow_universe"]
    L += _hdr("2. SHADOW UNIVERSE  (what EVERY setup would have done)")
    L.append(f"  decisions {su['n']} | resolved {su['resolved']} | "
             f"win rate {su['win_rate_pct']}% | expectancy {su['expectancy_r']}R")
    L.append("  This is the raw material: if the engine had taken every setup it")
    L.append("  computed, this is what it would have got. Gates are judged against it.")

    gf = rep["gate_funnel"]
    L += _hdr("3. GATE FUNNEL  (where decisions die)")
    L.append(f"  {'stage':<28}{'reached':>9}{'passed':>9}{'lost':>8}{'indep%':>9}")
    for s in gf["stages"]:
        L.append(f"  {s['stage']:<28}{s['reached']:>9}{s['passed']:>9}"
                 f"{s['lost_here']:>8}{str(s['independent_pass_pct']):>9}")
    L.append(f"  BIGGEST BOTTLENECK: {gf['biggest_bottleneck']} "
             f"({gf['biggest_bottleneck_lost']} decisions lost)")
    if gf.get("starved_stages"):
        L.append(f"  ! starved by upstream gates (tuning them changes nothing): "
                 f"{', '.join(gf['starved_stages'])}")

    gc = rep["gate_counterfactual"]
    L += _hdr("4. GATE COUNTERFACTUAL  (is each gate earning its place?)")
    if not gc.get("measurable", True):
        L.append(f"  NOT MEASURABLE: {gc.get('blocked_reason')}")
        L.append("  Fire counts below are still valid -- they show what each gate DID.")
    L.append(f"  {'gate':<26}{'fired':>7}{'blocked':>9}{'allowed':>9}{'disc':>7}  verdict")
    for g in gc["gates"]:
        L.append(f"  {g['gate']:<26}{g['fired_on']:>7}"
                 f"{str(g['blocked_win_rate']):>9}{str(g['allowed_win_rate']):>9}"
                 f"{str(g['discrimination_pts']):>7}  {g['verdict']}")
    if gc["inverted_gates"]:
        L.append(f"  !! INVERTED (blocking winners): {', '.join(gc['inverted_gates'])}")
    if gc["non_discriminating_gates"]:
        L.append(f"  !  no discrimination: {', '.join(gc['non_discriminating_gates'])}")

    ea = rep["evidence_attribution"]
    L += _hdr("5. EVIDENCE ATTRIBUTION  (which families actually predict?)")
    if not ea.get("available"):
        L.append(f"  unavailable: {ea.get('reason')}")
    else:
        L.append(f"  {'family':<22}{'n':>7}{'active%':>9}{'mean':>8}{'corr':>8}  verdict")
        for f in ea["families"]:
            L.append(f"  {f['family']:<22}{f['n']:>7}{f['active_pct']:>9}"
                     f"{f['mean_contribution']:>8}{str(f['correlation_with_win']):>8}"
                     f"  {f['verdict']}")
        if ea["inverted"]:
            L.append(f"  !! INVERTED: {', '.join(ea['inverted'])}")
        if ea["worthless"]:
            L.append(f"  !  no predictive value: {', '.join(ea['worthless'])}")

    ca = rep.get("component_attribution") or {}
    L += _hdr("5a. COMPONENT ATTRIBUTION  (does each module actually predict?)")
    if not ca.get("available"):
        L.append(f"  unavailable: {ca.get('reason')}")
    else:
        L.append("  Win rate when the component AGREED with the trade direction")
        L.append("  versus when it OPPOSED it. A component with skill wins more")
        L.append("  when trading with it. Zero spread = decorative weight.")
        L.append("")
        L.append(f"  {'component':<20}{'n agree':>9}{'n opp':>7}{'win agree':>11}"
                 f"{'win opp':>9}{'edge':>7}  verdict")
        for c in ca["components"]:
            L.append(f"  {c['component']:<20}{c['n_agree']:>9}{c['n_oppose']:>7}"
                     f"{(f'{c["win_agree_pct"]}%' if c['win_agree_pct'] is not None else '-'):>11}"
                     f"{(f'{c["win_oppose_pct"]}%' if c['win_oppose_pct'] is not None else '-'):>9}"
                     f"{(f'{c["edge_pts"]:+.1f}' if c['edge_pts'] is not None else '-'):>7}"
                     f"  {c['verdict']}")
        if ca["predictive"]:
            L.append(f"  !! PREDICTIVE: {', '.join(ca['predictive'])}")
        if ca["inverted"]:
            L.append(f"  !! INVERTED (trading with them costs money): {', '.join(ca['inverted'])}")
        if ca["no_skill"]:
            L.append(f"  !  NO SKILL: {', '.join(ca['no_skill'])}")

    sa = rep.get("score_attribution") or {}
    if sa.get("available"):
        L.append("")
        L.append("  -- by SCORE (the lens for components that never pick a side) --")
        L.append(f"  {'component':<24}{'n':>7}{'corr':>9}  verdict")
        for c in sa["components"][:14]:
            cc = f"{c['corr']:+.4f}" if c.get("corr") is not None else "-"
            L.append(f"  {c['component']:<24}{c['n']:>7}{cc:>9}  {c['verdict']}")
        if sa["informative"]:
            L.append(f"  !! carries information: {', '.join(sa['informative'])}")

    ci = rep.get("causal_invariance") or {}
    L += _hdr("5b. CAUSAL INVARIANCE  (does it predict the SAME WAY everywhere?)")
    L.append("  Section 5 asks whether a factor correlates with winning. This asks")
    L.append("  whether it does so identically across regimes, sessions, volatility")
    L.append("  bands and H1 trends. A factor that reverses between environments is")
    L.append("  a bet on the environment, and pooling it averages the effect away.")
    L.append("")
    try:
        from core.causal_invariance import format_causal_consensus
        L.append(format_causal_consensus(ci))
    except Exception as e:
        L.append(f"  unavailable: {type(e).__name__}: {e}")

    cf = rep["clamp_forensics"]
    L += _hdr("6. CLAMP FORENSICS  (evidence computed then discarded)")
    L.append(f"  severity: {cf['severity']}")
    L.append(f"  mean absorbed {cf['mean_absorbed_per_decision']} pts | max {cf['max_absorbed']} | "
             f"affected {cf['decisions_with_absorption']}/{cf['decisions']}")
    L.append(f"  mean clamped steps {cf['mean_clamped_steps']} of {cf['mean_chain_length']}")
    L.append(f"  ledger reconcile failures: {cf['ledger_reconcile_failures']}")
    for s in cf["by_step"][:10]:
        L.append(f"    {s['step']:<20} absorbed {s['total_absorbed']:>8}  "
                 f"on {s['pct_of_decisions']}% of decisions")

    co = rep["contradictions"]
    L += _hdr("7. CONTRADICTIONS  (does internal disagreement predict failure?)")
    if not co.get("measurable", True):
        L.append(f"  NOT MEASURABLE: {co.get('blocked_reason')}")
    L.append(f"  {'contradiction':<30}{'occurred':>10}{'with':>8}{'without':>9}{'impact':>8}")
    for c in co["checks"]:
        L.append(f"  {c['contradiction']:<30}{c['occurred']:>10}"
                 f"{str(c['win_rate_when_present']):>8}"
                 f"{str(c['win_rate_when_absent']):>9}{str(c['impact_pts']):>8}")
    if co["actionable"]:
        L.append(f"  !! PREDICTS LOSSES: {', '.join(co['actionable'])}")

    ff = rep["frozen_fields"]
    L += _hdr("8. FROZEN / DEGENERATE FIELDS  (hidden breakage)")
    L.append(f"  verdict: {ff['verdict']}")
    for f in ff["frozen"]:
        L.append(f"  FROZEN      {f['field']:<24} always {f['value']!r} ({f['n']} decisions)")
    for f in ff.get("not_exercised", []):
        L.append(f"  NOT EXERCISED {f['field']:<22} always {f['value']!r} "
                 f"({f['n']} decisions) -- harness limit, not a code defect")
        L.append(f"                {f['why']}")
    if ff["always_null"]:
        L.append(f"  ALWAYS NULL {', '.join(ff['always_null'])}")
    for f in ff["mostly_null"]:
        L.append(f"  MOSTLY NULL {f['field']:<24} present on only {f['present_pct']}%")
    for f in ff["pinned_at_one_value"]:
        L.append(f"  PINNED      {f['field']:<24} = {f['value']} on {f['share_pct']}%")
    for f in ff["low_variety"]:
        L.append(f"  LOW VARIETY {f['field']:<24} {f['values']}")

    tp = rep["threshold_proximity"]
    L += _hdr("9. THRESHOLD PROXIMITY  (are gates deciding on noise?)")
    L.append(f"  {'check':<22}{'n':>7}{'mean':>9}{'min':>9}{'max':>9}{'near%':>8}")
    for c in tp["checks"]:
        L.append(f"  {c['check']:<22}{c['n']:>7}{c['mean_margin']:>9}"
                 f"{c['min_margin']:>9}{c['max_margin']:>9}{c['near_miss_pct']:>8}")

    db = rep["direction_bias"]
    L += _hdr("10. DIRECTION BIAS")
    if db.get("available"):
        L.append(f"  BUY {db['buy']} / SELL {db['sell']} ({db['buy_pct']}% buy) -- {db['verdict']}")

    L += _hdr("11. BREAKDOWNS  (is the edge real or concentrated?)")
    for key, block in rep["breakdowns"].items():
        if not block["buckets"]:
            continue
        L.append(f"  -- by {block['dimension']} --")
        for b in block["buckets"]:
            L.append(f"     {b['bucket']:<18} n={b['n']:<6} resolved={b['resolved']:<6} "
                     f"win={str(b['win_rate_pct']):<7} exp={b['expectancy_r']}R")
        if block["warning"]:
            L.append(f"     ! {block['warning']}")

    rj = rep["rejections"]
    L += _hdr("12. REJECTIONS  (what did we refuse, and would it have won?)")
    L.append(f"  total rejected: {rj['total_rejected']}")
    L.append(f"  {'family':<22}{'count':>8}{'%':>7}{'would-win%':>13}{'exp R':>9}")
    for f in rj["by_family"]:
        L.append(f"  {f['family']:<22}{f['count']:>8}{str(f['pct']):>7}"
                 f"{str(f['would_have_won_pct']):>13}{str(f['would_have_expectancy_r']):>9}")
    L.append("  top verbatim reasons:")
    for t in rj["top_verbatim"][:8]:
        L.append(f"    {t['n']:>6}  {t['reason']}")

    return "\n".join(L)