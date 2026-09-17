# ============================================================
# ITEM #8 — ADAPTIVE / VOLATILITY-NORMALIZED OSCILLATOR THRESHOLDS
# ============================================================
# FILE: core/adaptive_thresholds.py
#
# STOCH_OVERSOLD=20 / RSI_OVERSOLD=30 and their overbought mirrors are
# flat constants regardless of the instrument's current behavior --
# textbook numbers tuned for equities decades ago. This module derives
# oversold/overbought bands from the recent distribution of the
# oscillator itself, using ONLY the full historical value lists
# calculations.py's _calculate_rsi() / _calculate_stochastic() already
# return (not just the latest value) -- same "derive from the recent
# distribution" pattern swing_points.py already uses for pip tables and
# patterns.py uses for rectangle-range tables. No new data source.
# ============================================================

from typing import Dict, Any, List, Optional
import statistics


def _percentile(values: List[float], pct: float) -> float:
    """Linear-interpolation percentile, no numpy dependency required."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def compute_adaptive_band(
    history: List[float],
    lookback: int = 100,
    oversold_pct: float = 10.0,
    overbought_pct: float = 90.0,
    fallback_oversold: float = 20.0,
    fallback_overbought: float = 80.0,
) -> Dict[str, Any]:
    """
    Generic: given a value history (RSI, Stochastic-K, whatever bounded
    oscillator), returns distribution-derived oversold/overbought levels
    instead of flat textbook constants.

    Falls back to the flat constants if there isn't enough history yet --
    this makes it a safe drop-in that degrades gracefully rather than
    producing garbage bands from 3 data points.
    """
    recent = [v for v in history[-lookback:] if v is not None]
    min_required = max(20, lookback // 5)

    if len(recent) < min_required:
        return {
            "oversold": fallback_oversold,
            "overbought": fallback_overbought,
            "adaptive": False,
            "sample_size": len(recent),
            "reason": f"only {len(recent)} bars of history, need >= {min_required} — using textbook fallback",
        }

    oversold = _percentile(recent, oversold_pct)
    overbought = _percentile(recent, overbought_pct)

    # Sanity guard: if the distribution is degenerate (near-flat market,
    # oversold/overbought collapse toward each other), widen back toward
    # the textbook band rather than emitting a threshold pair that would
    # fire on every tick.
    if overbought - oversold < (fallback_overbought - fallback_oversold) * 0.25:
        return {
            "oversold": fallback_oversold,
            "overbought": fallback_overbought,
            "adaptive": False,
            "sample_size": len(recent),
            "reason": "distribution too narrow (degenerate/flat regime) — using textbook fallback to avoid over-firing",
        }

    return {
        "oversold": round(oversold, 2),
        "overbought": round(overbought, 2),
        "adaptive": True,
        "sample_size": len(recent),
        "reason": f"derived from {oversold_pct:.0f}th/{overbought_pct:.0f}th percentile of last {len(recent)} bars",
    }


def compute_volatility_percentile_band(
    atr_history_pips: List[float],
    lookback: int = 100,
    low_pct: float = 10.0,
    high_pct: float = 90.0,
    fallback_low: float = 5.0,
    fallback_high: float = 20.0,
    extreme_pct: float = 98.0,
    fallback_extreme: float = None,
) -> Dict[str, Any]:
    """
    Same percentile machinery as compute_adaptive_band(), reused for ATR
    instead of RSI/Stochastic. Kept as a separate function (rather than
    calling compute_adaptive_band() directly) because "oversold"/
    "overbought" field names don't make sense for a volatility band --
    this returns "low"/"high" instead, everything else is identical
    logic (same graceful degrade to the static fallback range when
    there isn't enough history yet, same degenerate-distribution guard).

    ADDED: a third level, "extreme". compute_adaptive_band() produces
    exactly TWO levels, but the consumer that actually matters --
    calculations.py's check_volatility_protection() -- needs THREE
    (min / max / extreme) to pick its penalty tier. Without an extreme
    drawn from the same distribution this band cannot replace the static
    table at all: pairing an adaptive high (e.g. 90.4 pips) with a static
    extreme (45.0) gives extreme < max, which would mark every reading
    above 45 as EXTREME while it simultaneously sits inside the normal
    band. The extreme is therefore taken from the same history at
    extreme_pct and forced strictly above `high`.

    fallback_extreme defaults to 2x fallback_high, so the degraded path
    preserves min < max < extreme ordering too.
    """
    if fallback_extreme is None:
        fallback_extreme = fallback_high * 2.0

    band = compute_adaptive_band(
        atr_history_pips, lookback=lookback,
        oversold_pct=low_pct, overbought_pct=high_pct,
        fallback_oversold=fallback_low, fallback_overbought=fallback_high,
    )

    if not band["adaptive"]:
        # Degraded: compute_adaptive_band already swapped in the static
        # fallbacks, so the extreme must come from the static side too --
        # mixing a real percentile extreme onto fallback low/high would be
        # the ordering bug described above, inverted.
        extreme = fallback_extreme
    else:
        recent = [v for v in atr_history_pips[-lookback:] if v is not None]
        extreme = _percentile(recent, extreme_pct)
        # A tight distribution can put the 98th percentile essentially on
        # top of the 90th. Keep a real gap so the EXTREME tier stays
        # meaningfully above the HIGH tier instead of collapsing onto it.
        min_gap = max(1.0, band["overbought"] * 0.10)
        extreme = max(extreme, band["overbought"] + min_gap)

    return {
        "low": band["oversold"],
        "high": band["overbought"],
        "extreme": round(extreme, 2),
        "adaptive": band["adaptive"],
        "sample_size": band["sample_size"],
        "reason": band["reason"],
    }


def score_stochastic_adaptive(
    k: float,
    d: float,
    k_history: List[float],
    trend: str,
    lookback: int = 100,
) -> Dict[str, Any]:
    """
    Drop-in replacement shape for a flat-threshold stochastic scorer --
    same output contract (recommendation/score/confidence/reason) as the
    rest of the indicator_scores breakdown, but the oversold/overbought
    line is now this instrument's own recent behavior, not 20/80.
    """
    band = compute_adaptive_band(k_history, lookback=lookback)
    oversold, overbought = band["oversold"], band["overbought"]

    # ✅ FIXED: `d` was accepted and never read, so this scorer was
    # level-only -- it could see that %K had entered a band but not
    # whether %K had actually crossed %D, which is the event a
    # stochastic signal is normally built on. Its non-adaptive sibling,
    # score_stochastic_indicator_with_divergence(), does use the cross
    # and scores it higher (+-18) than a bare level read (+-12), so
    # swapping in the adaptive band silently DOWNGRADED the indicator:
    # the same setup that produced a confirmed crossover signal before
    # produced a weaker level-only one after.
    #
    # The cross is now read on both sides, with the adaptive band kept.
    #
    # A tie (k == d) is deliberately NOT a cross in either direction.
    # That exact asymmetry -- testing `k > d` on one side and `not
    # (k > d)` on the other -- made every tie resolve bearish in the
    # sibling scorer and produced a measured 1:2.5 bearish lean over
    # 4240 decisions.
    k_above_d = (d is not None) and k > d
    k_below_d = (d is not None) and k < d

    if k <= oversold:
        if k_above_d:
            rec, score, conf = "BUY", 18, 85
            reason = (f"Oversold, K crossed above D ({k:.1f} > {d:.1f}, "
                      f"adaptive band <= {oversold:.1f})")
        else:
            rec, score, conf = "BUY", 12, 70
            reason = f"Oversold region ({k:.1f}, adaptive band <= {oversold:.1f})"
    elif k >= overbought:
        if k_below_d:
            rec, score, conf = "SELL", -18, 85
            reason = (f"Overbought, K crossed below D ({k:.1f} < {d:.1f}, "
                      f"adaptive band >= {overbought:.1f})")
        else:
            rec, score, conf = "SELL", -12, 70
            reason = f"Overbought region ({k:.1f}, adaptive band >= {overbought:.1f})"
    else:
        rec, score, conf = "NEUTRAL", 0, 40
        reason = f"Mid-range ({k:.1f}, adaptive band {oversold:.1f}-{overbought:.1f})"

    return {
        "recommendation": rec,
        "score": score,
        "confidence": conf,
        "reason": reason,
        "band": band,
    }


def score_rsi_adaptive(
    rsi: float,
    rsi_history: List[float],
    lookback: int = 100,
) -> Dict[str, Any]:
    band = compute_adaptive_band(
        rsi_history, lookback=lookback,
        fallback_oversold=30.0, fallback_overbought=70.0,
    )
    oversold, overbought = band["oversold"], band["overbought"]

    if rsi <= oversold:
        rec, score, conf = "BUY", 10, 65
        reason = f"Oversold ({rsi:.1f}, adaptive band <= {oversold:.1f})"
    elif rsi >= overbought:
        rec, score, conf = "SELL", -10, 65
        reason = f"Overbought ({rsi:.1f}, adaptive band >= {overbought:.1f})"
    else:
        rec, score, conf = "NEUTRAL", 0, 50
        reason = f"Neutral ({rsi:.1f}, adaptive band {oversold:.1f}-{overbought:.1f})"

    return {
        "recommendation": rec,
        "score": score,
        "confidence": conf,
        "reason": reason,
        "band": band,
    }