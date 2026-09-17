"""
VOLATILITY FORECAST
===================
FILE: core/volatility_forecast.py

Forecasts the SIZE of the next move. Says nothing about its direction,
because direction is not forecastable here and pretending otherwise is
what produced every dead end in this project.

THE MEASUREMENT THAT JUSTIFIES THIS MODULE

Autocorrelation on the project's own cached bars:

    series                       AC(1)      AC(5)     AC(20)
    returns (direction)         -0.024      ~0.00      ~0.00
    |returns| (volatility)       0.248      0.205      0.166

against a significance band of +-0.010 on M1. Direction is
indistinguishable from a coin flip at every timeframe from M1 to D1 on
both EURUSD and XAGUSD -- confirmed independently by a context-tree
entropy of 1.0000. Volatility is autocorrelated at roughly twenty-five
times the noise band, on every instrument and every timeframe tested.

So this is the one thing in the data that is measurably predictable,
and it is the only place a forecast can honestly be made.

WHY EWMA AND NOT SOMETHING FITTED

RiskMetrics' exponentially-weighted variance with lambda = 0.94:

    sigma^2_t = lambda * sigma^2_{t-1} + (1 - lambda) * r^2_{t-1}

It is a fixed recursion with an industry-standard constant, not a
trained model -- nothing here is fitted to outcomes, so nothing here
can overfit to them. That matters: this project has already had one
model score AUC 0.5034 against a shuffled-label control of 0.5092, and
the reason a rule survives where that failed is that it was never
fitted to the sample in the first place.

WHAT IT IS FOR

  * Stop placement. Stops currently use ATR, which is a trailing
    AVERAGE of the last 14 bars -- it describes the past. A forecast
    describes the bar the trade will actually live through. Fewer
    noise stop-outs at identical R:R is a win-rate gain that needs no
    directional edge.

  * Regime filtering. The project's own XAGUSD replay measured 37.2%
    wins at ATR < 30 against 25.3% at ATR > 60 -- a twelve-point spread
    on setups already being taken, sorted by exactly the quantity this
    module predicts.

  * Position sizing, via the same forecast.

RAM: two floats of state. No history retained.
"""

from typing import Any, Dict, List, Optional, Sequence
import logging
import math

logger = logging.getLogger(__name__)

# RiskMetrics decay. 0.94 is the published daily constant and is used
# here unchanged rather than tuned: a lambda fitted to this sample would
# be a parameter fitted to this sample.
DEFAULT_LAMBDA = 0.94

# EWMA of squared returns estimates the STANDARD DEVIATION. Almost
# everything downstream -- ATR, stop distances, "how far will price
# move" -- is expressed as a MEAN ABSOLUTE move, and for a zero-mean
# normal variable those differ by a constant:
#
#     E|X| = sigma * sqrt(2/pi)  ~  0.7979 * sigma
#
# Skipping the conversion makes every forecast ~25% too large. Measured:
# the raw sigma scored 16-23% WORSE than trailing ATR on mean absolute
# error while tracking it almost identically (corr 0.369 vs 0.377) --
# the signal was right and the units were wrong, which is exactly the
# failure that looks like "the model does not work".
SIGMA_TO_MEAN_ABS = math.sqrt(2.0 / math.pi)

# Bars needed before a forecast means anything. At lambda 0.94 the
# effective window is ~1/(1-lambda) ~ 17 observations, so 30 gives the
# recursion time to forget its seed.
MIN_BARS = 30

# Forecast/ATR ratios defining the regime bands. Chosen as round
# fractions either side of 1.0 -- deliberately NOT optimised against
# win rate, which would fit them to this sample.
QUIET_RATIO = 0.80
VOLATILE_RATIO = 1.25


def _returns(closes: Sequence[float]) -> List[float]:
    out = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a and b and a > 0 and b > 0:
            out.append(b - a)
    return out


def ewma_volatility(closes: Sequence[float], *,
                    lam: float = DEFAULT_LAMBDA) -> Optional[float]:
    """
    One-step-ahead volatility forecast, in price units.

    Seeded with the sample standard deviation of the first few returns
    so the recursion starts from the instrument's own scale rather than
    from zero -- a zero seed takes ~17 bars to decay away and makes
    early forecasts meaninglessly small.
    """
    rets = _returns(closes)
    if len(rets) < MIN_BARS:
        return None

    seed = rets[:10]
    mean = sum(seed) / len(seed)
    var = sum((r - mean) ** 2 for r in seed) / max(1, len(seed) - 1)
    if var <= 0:
        var = (sum(r * r for r in seed) / len(seed)) or 1e-12

    for r in rets[10:]:
        var = lam * var + (1.0 - lam) * (r * r)

    # Converted to a mean-absolute scale so it is comparable with ATR
    # and with the stop distances it feeds. See SIGMA_TO_MEAN_ABS.
    return math.sqrt(var) * SIGMA_TO_MEAN_ABS if var > 0 else None


def forecast_volatility(closes: Sequence[float], *, pip_size: float,
                        atr_pips: Optional[float] = None,
                        lam: float = DEFAULT_LAMBDA) -> Dict[str, Any]:
    """
    Volatility forecast for the next bar, plus the regime it implies.

    `atr_pips` is optional and only used for comparison -- the ratio of
    forecast to trailing ATR is what separates "the next bar is quieter
    than the recent average" from "noisier", which is the regime signal.

    Returns available False when there is not enough history. Absent
    data must not become a fabricated forecast; the caller keeps its
    existing ATR behaviour in that case.
    """
    if not pip_size or pip_size <= 0:
        return {"available": False, "reason": "pip_size missing or invalid"}

    sigma = ewma_volatility(closes, lam=lam)
    if sigma is None:
        return {"available": False,
                "reason": f"need {MIN_BARS} returns to seed the recursion"}

    forecast_pips = sigma / pip_size
    out: Dict[str, Any] = {
        "available": True,
        "forecast_pips": round(forecast_pips, 3),
        "lambda": lam,
    }

    if atr_pips and atr_pips > 0:
        ratio = forecast_pips / atr_pips
        out["atr_pips"] = round(atr_pips, 3)
        out["forecast_to_atr"] = round(ratio, 3)
        if ratio <= QUIET_RATIO:
            regime, note = "QUIET", "next bar forecast calmer than recent average"
        elif ratio >= VOLATILE_RATIO:
            regime, note = "VOLATILE", "next bar forecast noisier than recent average"
        else:
            regime, note = "NORMAL", "next bar forecast in line with recent average"
        out["regime"] = regime
        out["reason"] = (f"forecast {forecast_pips:.1f}p vs ATR {atr_pips:.1f}p "
                         f"(x{ratio:.2f}) -- {note}")
    else:
        out["regime"] = "UNKNOWN"
        out["reason"] = f"forecast {forecast_pips:.1f}p (no ATR to compare)"

    return out


def evaluate_forecast_skill(closes: Sequence[float], *,
                            atr_period: int = 14,
                            lam: float = DEFAULT_LAMBDA) -> Dict[str, Any]:
    """
    Does the forecast actually beat trailing ATR at predicting the NEXT
    bar's absolute move?

    Walk-forward and strictly causal: at each bar both predictors see
    only prior data, and both are scored against the move that follows.
    Reported as mean absolute error, plus the correlation between each
    predictor and the realised magnitude.

    This exists because "volatility is autocorrelated" justifies trying
    a forecast; it does not by itself prove THIS forecast is better than
    the ATR already in use. If it is not, the module should not be wired
    in, and this function is how that gets decided.
    """
    rets = _returns(closes)
    if len(rets) < MIN_BARS + atr_period + 20:
        return {"available": False, "reason": "not enough history to score"}

    ewma_err, atr_err = [], []
    ewma_pred, atr_pred, actual = [], [], []

    var = None
    for i in range(len(rets) - 1):
        r = rets[i]
        if var is None:
            if i < 10:
                continue
            seed = rets[:10]
            m = sum(seed) / len(seed)
            var = sum((x - m) ** 2 for x in seed) / max(1, len(seed) - 1) or 1e-12
        var = lam * var + (1.0 - lam) * (r * r)

        if i < MIN_BARS + atr_period:
            continue

        nxt = abs(rets[i + 1])
        f_ewma = math.sqrt(var) * SIGMA_TO_MEAN_ABS
        window = rets[i - atr_period + 1:i + 1]
        f_atr = sum(abs(x) for x in window) / len(window)

        ewma_err.append(abs(f_ewma - nxt))
        atr_err.append(abs(f_atr - nxt))
        ewma_pred.append(f_ewma)
        atr_pred.append(f_atr)
        actual.append(nxt)

    if not ewma_err:
        return {"available": False, "reason": "no scored bars"}

    def corr(a, b):
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        saa = sum((x - ma) ** 2 for x in a)
        sbb = sum((y - mb) ** 2 for y in b)
        return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None

    mae_e = sum(ewma_err) / len(ewma_err)
    mae_a = sum(atr_err) / len(atr_err)
    return {
        "available": True,
        "n": len(ewma_err),
        "mae_ewma": mae_e,
        "mae_atr": mae_a,
        "mae_improvement_pct": round((1 - mae_e / mae_a) * 100, 2) if mae_a > 0 else None,
        "corr_ewma": round(corr(ewma_pred, actual) or 0, 4),
        "corr_atr": round(corr(atr_pred, actual) or 0, 4),
        "verdict": ("EWMA forecast beats trailing ATR"
                    if mae_e < mae_a else
                    "trailing ATR is as good or better -- do not wire this in"),
    }
