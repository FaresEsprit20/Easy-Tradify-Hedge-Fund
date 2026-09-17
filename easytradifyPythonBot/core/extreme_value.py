"""
EXTREME VALUE THEORY  (Stage 6 of the decoupled AI pipeline)
============================================================
FILE: core/extreme_value.py

Is this move genuinely extreme, or just large?

THE IDEA

Ordinary statistics describe the middle of a distribution and are
actively misleading about its tail. "Three standard deviations" assumes
normality, and financial returns are not normal -- their tails are
fatter, so a 3-sigma move is far more common than the normal
distribution claims and carries much less information than it appears
to.

Extreme Value Theory models the tail directly. The
Pickands-Balkema-de Haan theorem says exceedances over a high threshold
converge to a Generalised Pareto Distribution regardless of the parent
distribution -- so the tail can be fitted without assuming anything
about the body. That gives an honest answer to "how unusual is this
move", which is the question a reversal signal actually depends on.

WHY IT MIGHT WORK HERE WHEN OTHER THINGS DID NOT

This project measured price DIRECTION at entropy 1.0000 -- a fair coin
at every timeframe on both instruments -- and every one of nineteen
components at |correlation| < 0.05 against outcomes. Direction carries
no information.

Magnitude is different and was measured separately: |returns| are
autocorrelated at 0.19-0.26 against a +-0.010 significance band, on
every instrument and timeframe tested. EVT operates entirely on
magnitude. It is the one part of this pipeline whose input is a
quantity the data has actually been shown to contain structure in.

That is a reason to TEST it, not a reason to believe it. Whether an
extreme reading predicts anything about outcomes is measured, not
assumed -- and this module is deliberately built as a diagnostic first
so that measurement can happen before it influences a trade.

WHAT IT IS NOT

Not a direction signal. An extreme move is equally consistent with
exhaustion (reversal) and with a breakout (continuation); EVT quantifies
how unusual the move is and says nothing about which follows. Anything
turning that into a trade decision needs its own evidence.

Pure stdlib. Method-of-moments fit, no optimiser, no training.
"""

from typing import Any, Dict, List, Optional, Sequence
import logging
import math

logger = logging.getLogger(__name__)

# Tail threshold: the quantile above which exceedances are modelled.
# 0.95 is the conventional choice -- high enough that GPD convergence
# holds, low enough to leave a usable number of exceedances.
DEFAULT_TAIL_QUANTILE = 0.95

# Exceedances needed before a fit means anything. Below this the shape
# parameter is dominated by whichever single observation is largest.
MIN_EXCEEDANCES = 30

# Minimum observations overall.
MIN_SAMPLE = 200

# Quantile beyond which a move is called extreme. 0.99 of the fitted
# tail -- roughly a 1-in-100 move for the series' OWN distribution,
# which is the point: fat tails make this far larger than 3 sigma.
DEFAULT_EXTREME_QUANTILE = 0.99


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if not sorted_vals:
        return 0.0
    if q <= 0:
        return sorted_vals[0]
    if q >= 1:
        return sorted_vals[-1]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def fit_gpd(exceedances: Sequence[float]) -> Optional[Dict[str, float]]:
    """
    Generalised Pareto shape and scale by method of moments.

    MoM rather than maximum likelihood on purpose: MLE for the GPD needs
    an iterative optimiser, can fail to converge on small samples, and
    would add a fitting step to a module that is meant to be a fixed
    rule. MoM is closed-form and adequate for the "how unusual is this"
    question being asked.

        xi    = 0.5 * (1 - mean^2 / var)
        sigma = 0.5 * mean * (mean^2 / var + 1)

    Returns None when the sample cannot support a fit -- never a
    fabricated one.
    """
    vals = [float(x) for x in exceedances if x is not None and x > 0]
    if len(vals) < MIN_EXCEEDANCES:
        return None

    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
    if mean <= 0 or var <= 0:
        return None

    ratio = (mean * mean) / var
    xi = 0.5 * (1.0 - ratio)
    sigma = 0.5 * mean * (ratio + 1.0)
    if sigma <= 0:
        return None

    return {"xi": xi, "sigma": sigma, "n_exceedances": n, "mean_excess": mean}


def gpd_quantile(fit: Dict[str, float], threshold: float, p_tail: float,
                 q: float) -> Optional[float]:
    """
    The q-quantile of the FULL distribution, read off the fitted tail.

    p_tail is the fraction of the sample above `threshold`. Inverting
    the GPD survival function:

        x(q) = u + (sigma/xi) * (((1-q)/p_tail)^(-xi) - 1)

    with the xi -> 0 limit handled separately (exponential tail).
    """
    if q <= 1 - p_tail:
        return None                     # inside the body, not the tail
    xi, sigma = fit["xi"], fit["sigma"]
    ratio = (1.0 - q) / p_tail
    if ratio <= 0:
        return None
    try:
        if abs(xi) < 1e-8:
            return threshold + sigma * (-math.log(ratio))
        return threshold + (sigma / xi) * (ratio ** (-xi) - 1.0)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def evaluate_extreme(moves: Sequence[float], current_move: float, *,
                     tail_quantile: float = DEFAULT_TAIL_QUANTILE,
                     extreme_quantile: float = DEFAULT_EXTREME_QUANTILE) -> Dict[str, Any]:
    """
    How unusual is `current_move` against the series' own fitted tail?

    `moves` are historical absolute moves; `current_move` the one being
    judged. Both in the same units.

    Returns available False -- never a verdict -- when the sample cannot
    support a fit. An unfittable tail is the absence of evidence, and in
    this codebase that never becomes evidence in either direction.
    """
    vals = sorted(abs(float(m)) for m in moves
                  if m is not None and abs(float(m)) > 0)
    if len(vals) < MIN_SAMPLE:
        return {"available": False,
                "reason": f"need {MIN_SAMPLE} moves to fit a tail, have {len(vals)}"}

    threshold = _quantile(vals, tail_quantile)
    exceedances = [v - threshold for v in vals if v > threshold]
    fit = fit_gpd(exceedances)
    if fit is None:
        return {"available": False,
                "reason": (f"only {len(exceedances)} exceedances over the "
                           f"{tail_quantile:.0%} threshold (need {MIN_EXCEEDANCES})")}

    p_tail = len(exceedances) / len(vals)
    cur = abs(float(current_move))
    extreme_level = gpd_quantile(fit, threshold, p_tail, extreme_quantile)

    # Where this move sits in the fitted tail, as a survival probability.
    if cur <= threshold:
        exceedance_p = None
        is_extreme = False
    else:
        xi, sigma = fit["xi"], fit["sigma"]
        y = cur - threshold
        try:
            if abs(xi) < 1e-8:
                surv = math.exp(-y / sigma)
            else:
                base = 1.0 + xi * y / sigma
                surv = base ** (-1.0 / xi) if base > 0 else 0.0
        except (ValueError, OverflowError, ZeroDivisionError):
            surv = None
        exceedance_p = (p_tail * surv) if surv is not None else None
        is_extreme = bool(extreme_level is not None and cur >= extreme_level)

    return {
        "available": True,
        "current_move": round(cur, 6),
        "tail_threshold": round(threshold, 6),
        "extreme_level": round(extreme_level, 6) if extreme_level is not None else None,
        "exceedance_probability": (round(exceedance_p, 6)
                                   if exceedance_p is not None else None),
        "is_extreme": is_extreme,
        "xi": round(fit["xi"], 4),
        "sigma": round(fit["sigma"], 6),
        "n_exceedances": fit["n_exceedances"],
        # xi > 0 is a heavy (power-law) tail: large moves are far more
        # likely than a normal distribution would say, which is exactly
        # why a sigma-based "extreme" test misleads on this data.
        "tail_type": ("heavy (power-law)" if fit["xi"] > 0.05 else
                      "light (exponential)" if fit["xi"] < -0.05 else
                      "exponential"),
        "reason": (f"move {cur:.5f} vs {extreme_quantile:.0%} tail level "
                   f"{extreme_level:.5f} -- "
                   f"{'EXTREME' if is_extreme else 'ordinary'}"
                   if extreme_level is not None else
                   f"move {cur:.5f}, tail level not computable"),
    }
