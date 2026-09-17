"""
INVARIANT CAUSAL PREDICTION  (Stage 4 of the decoupled AI pipeline)
==================================================================
FILE: core/causal_invariance.py

Separates factors that predict because of a stable mechanism from
factors that predicted once, in one regime, by coincidence.

THE IDEA

Peters/Buhlmann/Meinshausen's invariance principle: if X genuinely
causes Y, then P(Y | X) is the SAME in every environment where you
measure it. Change the regime, the session, the volatility band -- a
causal relationship survives; a spurious one does not, because what
actually produced it was the environment.

So the test is not "does this feature correlate with winning?" -- the
replay already answers that and the answer moves every time the sample
does. The test is "does it correlate the same way in every regime?" A
factor that predicts wins in RANGING_CALM and losses in TRENDING_CALM
has no stable mechanism behind it; pooling those two environments
averages them into a small correlation that looks like weak signal and
is really two contradictory effects cancelling out.

WHY THIS PROJECT NEEDS IT SPECIFICALLY

A 1856-decision XAGUSD replay measured all eleven evidence families at
|corr with winning| <= 0.042 and reported every one as NO PREDICTIVE
VALUE. That verdict is correct but not diagnostic: it cannot tell
apart

    (a) this factor carries no information at all, and
    (b) this factor carries real information that reverses sign
        between regimes, so pooling destroys it.

Those two call for opposite responses -- delete the factor, or
condition it on regime. Correlation cannot distinguish them. Testing
the effect per environment can, and that is the whole of what this
module does.

WHAT IT DELIBERATELY DOES NOT DO

It does not fit a model, rank features by importance, or output a
score to trade on. It is a diagnostic over recorded outcomes: it says
which factors are stable enough to be worth building on. Anything that
turns its findings into a trading decision belongs in Stage 7, behind
that stage's own out-of-sample validation.

Pure stdlib + numpy. No sklearn, no training, no artifact.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import logging
import math

logger = logging.getLogger(__name__)

# An environment with fewer decisions than this cannot support an
# effect estimate worth comparing -- its confidence interval is wide
# enough to be consistent with almost anything, which would make every
# feature look spuriously "invariant".
MIN_ENV_SAMPLES = 60

# Minimum environments a feature must be measurable in. Invariance
# across one environment is not invariance, it is a single measurement.
MIN_ENVIRONMENTS = 3

# |effect| below this is treated as no effect regardless of its
# p-value. On a few thousand samples a correlation of 0.02 can be
# "significant" and still be worth nothing to a trader.
NEGLIGIBLE_EFFECT = 0.05


def _f(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return float(v) if isinstance(v, bool) else None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and float("-inf") < x < float("inf") else None


def _point_biserial(values: Sequence[float], wins: Sequence[int]) -> Optional[Tuple[float, float]]:
    """
    (effect, standard error) between a continuous feature and a binary
    outcome, as a Pearson correlation.

    Returns None when the feature is constant -- a column with no
    variance has no measurable relationship with anything, and dividing
    by its zero standard deviation is how that becomes a NaN that
    propagates silently through every downstream comparison.
    """
    n = len(values)
    if n < 8:
        return None

    mean_x = sum(values) / n
    mean_y = sum(wins) / n
    sxx = sum((x - mean_x) ** 2 for x in values)
    syy = sum((y - mean_y) ** 2 for y in wins)
    if sxx <= 0 or syy <= 0:
        return None

    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(values, wins))
    r = sxy / math.sqrt(sxx * syy)
    r = max(-0.999999, min(0.999999, r))

    # Fisher-z standard error: stable near |r| -> 1, unlike the raw
    # correlation's, and what the cross-environment comparison below
    # needs to be done in.
    se_z = 1.0 / math.sqrt(n - 3) if n > 3 else float("inf")
    return r, se_z


def _fisher_z(r: float) -> float:
    return 0.5 * math.log((1 + r) / (1 - r))


def _normal_sf(z: float) -> float:
    """Two-sided tail probability of |z| under a standard normal."""
    return math.erfc(abs(z) / math.sqrt(2.0))


# ------------------------------------------------------------
# ENVIRONMENTS
# ------------------------------------------------------------
# An environment is any partition of the data the mechanism should be
# invariant to. Regime is the natural one for a trading system; session
# and volatility band are independent second opinions, because a factor
# that looks invariant under one partition and falls apart under
# another was never invariant, only untested.

def env_by_regime(rec) -> Optional[str]:
    v = (rec.get("capture") or {}).get("regime")
    return str(v) if v else None


def env_by_volatility(rec) -> Optional[str]:
    v = _f((rec.get("capture") or {}).get("atr_pips"))
    if v is None:
        return None
    return "atr_low" if v < 30 else "atr_mid" if v < 60 else "atr_high"


def env_by_session(rec) -> Optional[str]:
    t = rec.get("decision_timestamp")
    if not t:
        return None
    hour = int((t // 3600) % 24)
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 21:
        return "newyork"
    return "late"


def env_by_trend(rec) -> Optional[str]:
    v = (rec.get("capture") or {}).get("h1_trend")
    return str(v) if v else None


def env_by_period(rec) -> Optional[str]:
    """
    Which third of the replay window this decision falls in.

    THE SPLIT THAT WAS MISSING, AND WHY IT MATTERS

    The other four splits partition by market STATE. None of them
    partitions by TIME, so a factor that works for one stretch and
    reverses in the next passes all four and is reported as invariant.

    That is not hypothetical. `h1_opposition` -- trading against the H1
    trend -- measured r = 0.139 with ZERO failed splits and +0.187R
    expectancy on 950 decisions, and was reported as this project's
    first and only causal candidate. Splitting the same window in half
    by time:

        first half    opposes +0.560R   aligns -0.414R   swing +0.974R
        second half   opposes -0.172R   aligns -0.055R   swing -0.117R

    The entire effect lived in the first half and reversed in the
    second. An out-of-sample instrument (XAGUSD) also flipped its sign.
    It was a regime artifact that the invariance test, as it stood,
    could not see.

    Time is the one environment a live system is guaranteed to move
    through, so an effect that is not stable across it is not tradable
    no matter how stable it looks across everything else.

    Thirds rather than halves: two periods can agree by coincidence far
    more easily than three, and thirds still leave enough decisions per
    bucket to measure.
    """
    ts = rec.get("decision_timestamp")
    if not ts:
        return None
    # Bucketed against the run's own span, resolved lazily by the caller
    # via _PERIOD_BOUNDS -- set by causal_invariance_report() before use.
    lo, hi = _PERIOD_BOUNDS
    if lo is None or hi is None or hi <= lo:
        return None
    frac = (float(ts) - lo) / (hi - lo)
    if frac < 1 / 3:
        return "period_1"
    if frac < 2 / 3:
        return "period_2"
    return "period_3"


# Filled in by causal_invariance_report() from the records themselves,
# so env_by_period does not need the whole set threaded into it.
_PERIOD_BOUNDS = (None, None)


ENVIRONMENT_SPLITS: Dict[str, Callable[[Any], Optional[str]]] = {
    "regime": env_by_regime,
    "volatility": env_by_volatility,
    "session": env_by_session,
    "h1_trend": env_by_trend,
    # Time. See env_by_period: without it, a factor that reverses
    # between fortnights reads as perfectly invariant.
    "period": env_by_period,
}


# ------------------------------------------------------------
# CANDIDATE FACTORS
# ------------------------------------------------------------
# The eleven evidence families, plus the context measures that the
# cost-structure work showed can dominate outcomes. Contributions live
# one level down, under capture["contributions"].

def _cap_getter(key: str):
    return lambda rec: _f((rec.get("capture") or {}).get(key))


def _contrib_getter(key: str):
    return lambda rec: _f(((rec.get("capture") or {}).get("contributions") or {}).get(key))


def _bool_getter(key: str):
    """
    A captured boolean as 1.0/0.0, with absent stayed absent.

    _f() on a bool would work, but None must NOT collapse to 0.0: a
    field the run never captured would then read as "condition false on
    every decision" and could be scored as a perfectly inert factor
    instead of an unmeasured one.
    """
    def get(rec):
        v = (rec.get("capture") or {}).get(key)
        if v is None:
            return None
        return 1.0 if bool(v) else 0.0
    return get


CANDIDATE_FACTORS: Dict[str, Callable[[Any], Optional[float]]] = {
    # evidence families (the probability chain's own contributions)
    "pattern": _contrib_getter("pattern"),
    "smc": _contrib_getter("smc"),
    "fvg_ifvg": _contrib_getter("fvg_ifvg"),
    "order_flow": _contrib_getter("order_flow"),
    "trend_cascade": _contrib_getter("trend_cascade"),
    "adr_exhaustion": _contrib_getter("adr_exhaustion"),
    "rvam": _contrib_getter("rvam"),
    "nested_zone": _contrib_getter("nested_zone"),
    "dxy_confluence": _contrib_getter("dxy_confluence"),
    "gnn": _contrib_getter("gnn"),
    # the stack's own summary judgements
    "probability": _cap_getter("probability"),
    "conviction_score": _cap_getter("conviction_score"),
    "star_rating": _cap_getter("star_rating"),
    "signal_count": _cap_getter("signal_count"),
    "coherence_violations": _cap_getter("coherence_violations"),
    # context
    "atr_pips": _cap_getter("atr_pips"),
    "spread_pips": _cap_getter("spread_pips"),
    "adx": _cap_getter("adx"),
    "volume_ratio": _cap_getter("volume_ratio"),
    "premium_position_pct": _cap_getter("premium_position_pct"),
    "rr_ratio": _cap_getter("rr_ratio"),
    "sl_pips": _cap_getter("sl_pips"),
    # The three vetoes commented out in veto_engine.py (V3/V4/V5).
    # They were disabled by hand with no measurement attached, and
    # re-enabling them is a trading decision that should be settled by
    # the shadow universe rather than by taste. Routing them through
    # the same invariance splits as everything else means a factor that
    # only works in one regime cannot be promoted on a pooled average
    # -- which is precisely how h1_opposition (V5's factor) nearly got
    # re-enabled at +0.187R before the period split reversed its sign.
    # Real tape-derived timing. Only meaningful on decisions where ticks
    # actually existed; measured pooled at +0.246R for the >=85 bucket,
    # which survived the period and direction splits and then flipped on
    # h1_trend (BEARISH +0.578, BULLISH -0.034, n~32 a cell). Kept as a
    # standing candidate so a longer tick history can settle it rather
    # than having to rediscover it by hand.
    "timing_confidence": _cap_getter("timing_confidence"),
    # Computed, passed to the probability engine, discarded there.
    "ema_gap_pips": _cap_getter("ema_gap_pips"),
    "veto_against_trend": _bool_getter("veto_against_trend"),
    "veto_against_ema": _bool_getter("veto_against_ema"),
    "veto_h1_conflict": _bool_getter("veto_h1_conflict"),
}


def _outcome_win(rec) -> Optional[int]:
    """1 win, 0 loss, None unresolved -- read from the shadow outcome."""
    o = (rec.get("shadow") or {}).get("outcome")
    if o == "WIN":
        return 1
    if o == "LOSS":
        return 0
    return None


def test_factor(records, factor: Callable[[Any], Optional[float]],
                env_of: Callable[[Any], Optional[str]]) -> Dict[str, Any]:
    """
    Is this factor's relationship with winning the same everywhere?

    Per environment: the point-biserial correlation with the outcome.
    Across environments: a Cochran's-Q heterogeneity test on the
    Fisher-z transformed effects -- which asks whether the spread
    BETWEEN environments is larger than the noise WITHIN them.

    A low heterogeneity p-value means the effect genuinely differs by
    environment, i.e. the factor is not invariant, i.e. whatever it is
    measuring is a property of the regime rather than of the setup.
    """
    per_env: Dict[str, List[Tuple[float, int]]] = {}
    for rec in records:
        y = _outcome_win(rec)
        if y is None:
            continue
        x = factor(rec)
        if x is None:
            continue
        e = env_of(rec)
        if e is None:
            continue
        per_env.setdefault(e, []).append((x, y))

    effects = {}
    for env, rows in per_env.items():
        if len(rows) < MIN_ENV_SAMPLES:
            continue
        vals = [x for x, _ in rows]
        wins = [y for _, y in rows]
        got = _point_biserial(vals, wins)
        if got is None:
            continue
        r, se_z = got
        effects[env] = {"n": len(rows), "effect": r, "z": _fisher_z(r), "se_z": se_z}

    if len(effects) < MIN_ENVIRONMENTS:
        return {
            "testable": False,
            "environments": len(effects),
            "verdict": "NOT TESTABLE",
            "detail": (f"measurable in only {len(effects)} environment(s) with "
                       f">= {MIN_ENV_SAMPLES} samples -- invariance needs at least "
                       f"{MIN_ENVIRONMENTS}"),
        }

    # Inverse-variance pooled effect (fixed-effects meta-analysis).
    weights = {e: 1.0 / (v["se_z"] ** 2) for e, v in effects.items()}
    wsum = sum(weights.values())
    z_pooled = sum(weights[e] * effects[e]["z"] for e in effects) / wsum
    se_pooled = math.sqrt(1.0 / wsum)
    r_pooled = math.tanh(z_pooled)

    # Cochran's Q: dispersion of the per-environment effects relative to
    # their own precision. Under "one shared effect" it is chi-square
    # with (k-1) degrees of freedom.
    Q = sum(weights[e] * (effects[e]["z"] - z_pooled) ** 2 for e in effects)
    k = len(effects)
    df = k - 1
    # Wilson-Hilferty chi-square -> normal, adequate for the small df here
    # and keeps this module free of a scipy dependency.
    if df > 0 and Q > 0:
        wh = ((Q / df) ** (1.0 / 3.0) - (1 - 2.0 / (9 * df))) / math.sqrt(2.0 / (9 * df))
        het_p = _normal_sf(wh) / 2.0
    else:
        het_p = 1.0

    signs = {1 if v["effect"] > 0 else -1 for v in effects.values()
             if abs(v["effect"]) >= 0.02}
    sign_stable = len(signs) <= 1

    pooled_p = _normal_sf(z_pooled / se_pooled) if se_pooled > 0 else 1.0
    strong_enough = abs(r_pooled) >= NEGLIGIBLE_EFFECT

    if not strong_enough:
        verdict = "NO EFFECT"
        detail = (f"pooled |r| {abs(r_pooled):.3f} is below the {NEGLIGIBLE_EFFECT} "
                  f"floor -- nothing to be invariant about")
    elif het_p < 0.05 or not sign_stable:
        verdict = "NOT INVARIANT"
        detail = (f"effect differs by environment (heterogeneity p={het_p:.3f}"
                  + ("; sign flips across environments" if not sign_stable else "")
                  + ") -- this is a property of the regime, not of the setup")
    elif pooled_p < 0.05:
        verdict = "INVARIANT + PREDICTIVE"
        detail = (f"stable across {k} environments (heterogeneity p={het_p:.3f}) "
                  f"and non-zero (p={pooled_p:.4f}) -- a causal candidate")
    else:
        verdict = "INVARIANT, NOT SIGNIFICANT"
        detail = (f"consistent across {k} environments but the pooled effect is "
                  f"not distinguishable from zero (p={pooled_p:.3f})")

    return {
        "testable": True,
        "environments": k,
        "n_total": sum(v["n"] for v in effects.values()),
        "pooled_effect": round(r_pooled, 4),
        "pooled_p": round(pooled_p, 4),
        "heterogeneity_Q": round(Q, 3),
        "heterogeneity_p": round(het_p, 4),
        "sign_stable": sign_stable,
        "per_environment": {e: {"n": v["n"], "effect": round(v["effect"], 4)}
                            for e, v in sorted(effects.items())},
        "verdict": verdict,
        "detail": detail,
    }


def causal_invariance_report(records, *, split: str = "regime") -> Dict[str, Any]:
    """
    Run every candidate factor through the invariance test.

    `split` names the environment partition (see ENVIRONMENT_SPLITS).
    Regime is the default because it is the partition a trading system
    is most obviously expected to be invariant to: a factor that only
    works when the market is ranging is a regime bet wearing an
    indicator's clothes.
    """
    # Establish the time window before any split runs, so env_by_period
    # can bucket against this run's own span rather than an absolute date.
    global _PERIOD_BOUNDS
    _ts = [r.get("decision_timestamp") for r in records if r.get("decision_timestamp")]
    _PERIOD_BOUNDS = (min(_ts), max(_ts)) if _ts else (None, None)

    env_of = ENVIRONMENT_SPLITS.get(split)
    if env_of is None:
        return {"available": False,
                "reason": f"unknown environment split {split!r}; "
                          f"have {sorted(ENVIRONMENT_SPLITS)}"}

    resolved = [r for r in records if _outcome_win(r) is not None]
    if len(resolved) < MIN_ENV_SAMPLES * MIN_ENVIRONMENTS:
        return {"available": False,
                "reason": (f"only {len(resolved)} resolved decisions; need at least "
                           f"{MIN_ENV_SAMPLES * MIN_ENVIRONMENTS} to compare "
                           f"{MIN_ENVIRONMENTS} environments")}

    results = {}
    for name, getter in CANDIDATE_FACTORS.items():
        try:
            results[name] = test_factor(resolved, getter, env_of)
        except Exception as e:
            results[name] = {"testable": False, "verdict": "ERROR",
                             "detail": f"{type(e).__name__}: {e}"}

    def bucket(v):
        return [n for n, r in results.items() if r.get("verdict") == v]

    return {
        "available": True,
        "split": split,
        "resolved": len(resolved),
        "factors": results,
        # Deliberately NOT called "causal_candidates".
        #
        # This function tests ONE split. Surviving one split is a weak
        # claim that reads like a strong one: on a single XAGUSD M15
        # run, split="regime" alone returned five names -- order_flow,
        # trend_cascade, adr_exhaustion, family_score, veto_against_ema
        # -- and every one of them failed at least one of the other four
        # splits. veto_against_ema went further and reversed outright on
        # the same data analysed at M1 (+0.105 -> -0.018, sign unstable).
        #
        # The stricter all-splits verdict lives in
        # causal_consensus_report(). Naming this key the same
        # thing invited exactly the misreading it caused.
        "survivors_this_split": bucket("INVARIANT + PREDICTIVE"),
        "split_caveat": (
            f"survived the {split!r} split ONLY -- not a causal claim; "
            f"see causal_consensus_report() for the all-splits verdict"),
        "regime_dependent": bucket("NOT INVARIANT"),
        "no_effect": bucket("NO EFFECT"),
        "untestable": bucket("NOT TESTABLE"),
    }


def causal_consensus_report(records) -> Dict[str, Any]:
    """
    Run the invariance test under EVERY environment split and keep only
    factors that survive all of them.

    One partition is not a test of invariance, it is a single
    comparison that a factor can pass by accident -- because that
    particular split happens not to separate the environments where the
    factor reverses. Measured here: dxy_confluence reads
    "INVARIANT + PREDICTIVE" under an h1_trend split and
    "NOT INVARIANT" under regime, volatility AND session. Reporting the
    first result alone would have promoted a regime bet to a causal
    factor.

    So a candidate must be invariant everywhere it can be measured, and
    must fail nowhere. This is deliberately hard to pass: the cost of a
    false causal factor is a strategy built on it.
    """
    per_split = {}
    for split in ENVIRONMENT_SPLITS:
        rep = causal_invariance_report(records, split=split)
        if rep.get("available"):
            per_split[split] = rep

    if not per_split:
        return {"available": False,
                "reason": "no environment split had enough resolved decisions"}

    # Aggregate each factor's verdicts across splits.
    factors: Dict[str, Dict[str, Any]] = {}
    for split, rep in per_split.items():
        for name, res in rep["factors"].items():
            slot = factors.setdefault(name, {"verdicts": {}, "effects": {}})
            slot["verdicts"][split] = res.get("verdict")
            if res.get("testable"):
                slot["effects"][split] = res.get("pooled_effect")

    survivors, contingent, inert = [], [], []
    for name, slot in factors.items():
        verdicts = set(slot["verdicts"].values())
        tested = [v for v in slot["verdicts"].values() if v != "NOT TESTABLE"]
        if not tested:
            continue
        if "NOT INVARIANT" in verdicts:
            contingent.append(name)
        elif "INVARIANT + PREDICTIVE" in verdicts and verdicts <= {
                "INVARIANT + PREDICTIVE", "INVARIANT, NOT SIGNIFICANT", "NOT TESTABLE"}:
            survivors.append(name)
        else:
            inert.append(name)

    return {
        "available": True,
        "splits": sorted(per_split),
        "resolved": next(iter(per_split.values()))["resolved"],
        "factors": factors,
        "causal_candidates": sorted(survivors),
        "regime_contingent": sorted(contingent),
        "inert": sorted(inert),
    }


def format_causal_consensus(rep: Dict[str, Any]) -> str:
    if not rep.get("available"):
        return f"  unavailable: {rep.get('reason')}"

    L = [f"  splits tested: {', '.join(rep['splits'])}  |  "
         f"resolved decisions: {rep['resolved']}",
         "  a factor must be invariant under EVERY split to count as causal",
         ""]

    rows = []
    for name, slot in rep["factors"].items():
        eff = slot["effects"]
        mean_eff = (sum(eff.values()) / len(eff)) if eff else None
        fails = sum(1 for v in slot["verdicts"].values() if v == "NOT INVARIANT")
        rows.append((abs(mean_eff or 0), name, mean_eff, fails, slot["verdicts"]))
    rows.sort(reverse=True)

    L.append(f"  {'factor':<22} {'mean r':>8} {'splits failed':>14}")
    for _, name, mean_eff, fails, _v in rows[:12]:
        L.append(f"  {name:<22} "
                 f"{(f'{mean_eff:.4f}' if mean_eff is not None else '-'):>8} "
                 f"{fails:>14}")

    L.append("")
    if rep["causal_candidates"]:
        L.append(f"  !! CAUSAL CANDIDATES: {', '.join(rep['causal_candidates'])}")
        L.append("     stable everywhere tested -- these are what to build on")
    else:
        L.append("  !! NO CAUSAL CANDIDATES -- nothing in the evidence stack holds a")
        L.append("     stable relationship with winning across environments.")
    if rep["regime_contingent"]:
        L.append(f"  !  REGIME-CONTINGENT: {', '.join(rep['regime_contingent'])}")
        L.append("     these DO carry information, but it reverses between")
        L.append("     environments -- pooling them into one probability averages")
        L.append("     the effect away. Condition on regime or drop them.")
    return "\n".join(L)


def format_causal_invariance(rep: Dict[str, Any]) -> str:
    if not rep.get("available"):
        return f"  unavailable: {rep.get('reason')}"

    lines = [f"  environment split: {rep['split']}  |  resolved decisions: {rep['resolved']}",
             "",
             f"  {'factor':<22} {'envs':>5} {'pooled r':>9} {'het p':>7}  verdict"]

    order = {"INVARIANT + PREDICTIVE": 0, "NOT INVARIANT": 1,
             "INVARIANT, NOT SIGNIFICANT": 2, "NO EFFECT": 3,
             "NOT TESTABLE": 4, "ERROR": 5}
    for name, r in sorted(rep["factors"].items(),
                          key=lambda kv: (order.get(kv[1].get("verdict"), 9),
                                          -abs(kv[1].get("pooled_effect") or 0))):
        if not r.get("testable"):
            lines.append(f"  {name:<22} {'-':>5} {'-':>9} {'-':>7}  {r['verdict']}")
            continue
        lines.append(
            f"  {name:<22} {r['environments']:>5} {r['pooled_effect']:>9.4f} "
            f"{r['heterogeneity_p']:>7.3f}  {r['verdict']}")

    if rep["causal_candidates"]:
        lines.append("")
        lines.append(f"  !! CAUSAL CANDIDATES (stable across environments): "
                     f"{', '.join(rep['causal_candidates'])}")
    if rep["regime_dependent"]:
        lines.append(f"  !  REGIME-DEPENDENT (predict differently per environment, "
                     f"do not pool): {', '.join(rep['regime_dependent'])}")
    if not rep["causal_candidates"]:
        lines.append("")
        lines.append("  No factor survived the invariance test. That is a finding:")
        lines.append("  the stack's evidence is either inert or regime-contingent,")
        lines.append("  and pooling it into one probability is averaging away the")
        lines.append("  only structure present.")
    return "\n".join(lines)
