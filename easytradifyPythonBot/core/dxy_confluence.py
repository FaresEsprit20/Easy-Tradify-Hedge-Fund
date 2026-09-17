# ============================================================
# DOLLAR INDEX (DXY) CROSS-CHECK
# ============================================================
# FILE: core/dxy_confluence.py
#
# For a USD pair, DXY's own trend is a real, mostly-independent second
# opinion on the USD side of the trade -- mostly independent, because
# DXY is a fixed weighted basket (EUR ~57.6%, JPY ~13.6%, GBP ~11.9%,
# CAD ~9.1%, SEK ~4.2%, CHF ~3.6%), and a pair whose non-USD currency
# carries a large weight in that basket is checking DXY against a
# number DXY itself is largely built from. EURUSD is the extreme case
# (EUR alone is over half the basket) -- close to circular. AUDUSD and
# NZDUSD are the clean case: AUD/NZD aren't in the DXY basket at all,
# so DXY's trend there is genuinely independent evidence. This module
# is basket-weight-aware rather than a blunt "skip EURUSD" rule: the
# probability-chain effect size scales down by how much basket overlap
# a given pair actually has (see DXY_BASKET_WEIGHTS / circularity_pct
# below), so GBPUSD/USDCAD/USDJPY get a real but partially-damped
# effect, matching how circular they actually are rather than treating
# every USD pair (or only EURUSD) as a special case.
#
# ai_gnn.py's get_context()/'dxy_strength' field was found hardcoded to
# a flat 0.5 (neutral) placeholder in both of its return paths -- never
# actually computed from anything. That field is now wired to
# get_dxy_direction() below, one real source of truth instead of a
# working module here and a dead stub sitting next to it.
# ============================================================

import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Common broker naming conventions for the Dollar Index CFD/symbol --
# tried in order, first one that resolves on this broker wins. Brokers
# are not standardized on this, unlike the FX majors.
DXY_SYMBOL_CANDIDATES = [
    "USDX", "DXY", "DX", "DXY.cash", "USDX.cash", "USDIDX",
    "DX-Y.NYB", "USDOLLAR", "DOLLAR", "USD_IDX",
]

# Approximate ICE Dollar Index basket weights -- used only to scale how
# much a cross-check actually adds for a given pair, not for anything
# price-sensitive.
DXY_BASKET_WEIGHTS = {
    "EUR": 0.576,
    "JPY": 0.136,
    "GBP": 0.119,
    "CAD": 0.091,
    "SEK": 0.042,
    "CHF": 0.036,
}

EMA_PERIOD = 20
SLOPE_LOOKBACK_BARS = 3
BARS_NEEDED = EMA_PERIOD + SLOPE_LOOKBACK_BARS + 10
FLAT_SLOPE_THRESHOLD_PCT = 0.02  # % move over the lookback window below which DXY counts as flat

# Probability-chain effect size at ZERO basket overlap (AUDUSD/NZDUSD).
# Scaled down per-pair by (1 - circularity_pct) -- see
# calculate_dxy_confluence_final_score().
DXY_MAX_BONUS = 10.0
DXY_MAX_PENALTY = -10.0

_resolved_dxy_symbol: Optional[str] = None  # cached across calls within a process


# ✅ Non-FX instruments that happen to be quoted in USD. They end in
# "USD" and so were being classified as ordinary QUOTE-side FX pairs.
# Their "other currency" (XAG/XAU/BTC/...) isn't in the DXY basket, so
# _get_circularity_pct returned 0.0 -- and 0.0 is the code for "no
# overlap, fully independent evidence", earning the FULL +-10 effect,
# the same treatment AUDUSD gets.
#
# That reads the zero backwards. 0.0 here means "not a basket currency",
# not "an independent read on the dollar". Silver, gold and crypto move
# on their own supply/demand and risk sentiment; DXY's slope is a much
# weaker second opinion on them than it is on a genuine FX major, and
# basket weight is simply the wrong instrument for measuring that.
#
# Damped rather than excluded -- the dollar leg is real, it just isn't
# the whole story the way it is for EURUSD.
NON_FX_USD_QUOTED_PREFIXES = ("XAU", "XAG", "XPT", "XPD", "BTC", "ETH", "WTI", "BRENT", "USOIL", "UKOIL")
NON_FX_USD_EFFECT_SCALE = 0.4


def _is_non_fx_usd_quoted(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith("USD") and any(s.startswith(p) for p in NON_FX_USD_QUOTED_PREFIXES)


def _get_pair_usd_role(symbol: str) -> Optional[str]:
    """'BASE' if USD is the base currency (USDJPY, USDCAD, USDCHF...),
    'QUOTE' if USD is the quote currency (EURUSD, GBPUSD, AUDUSD...),
    None if the symbol has no USD leg at all (cross pairs, non-FX)."""
    s = symbol.upper()
    if s.startswith("USD"):
        return "BASE"
    if s.endswith("USD"):
        return "QUOTE"
    return None


def _get_circularity_pct(symbol: str) -> float:
    """How much of DXY's own basket is made up of this pair's non-USD
    currency -- 0.0 for currencies not in the basket at all (AUD, NZD),
    up to ~0.576 for EUR."""
    s = symbol.upper()
    other_currency = s.replace("USD", "", 1)
    return DXY_BASKET_WEIGHTS.get(other_currency, 0.0)


def _resolve_dxy_symbol(mt5) -> Optional[str]:
    global _resolved_dxy_symbol
    if _resolved_dxy_symbol is not None:
        return _resolved_dxy_symbol
    for candidate in DXY_SYMBOL_CANDIDATES:
        try:
            info = mt5.symbol_info(candidate)
            if info is not None:
                _resolved_dxy_symbol = candidate
                return candidate
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Synthetic fallback
# ---------------------------------------------------------------------------
#
# MEASURED: this component returned "no DXY-equivalent symbol found on this
# broker" on 215 of 215 real trades. Every candidate name in
# DXY_SYMBOL_CANDIDATES is absent here -- the broker carries 7,403 symbols and
# not one of them is a dollar index. So the component ran, published
# available=False, contributed exactly 0.0 on every trade, and looked from the
# outside like a check that had simply declined to act.
#
# It does not need the index symbol. The ICE basket is six pairs, and all six
# are on this broker. The published formula reconstructs the index from them:
#
#   DXY = 50.14348112
#         * EURUSD^-0.576 * USDJPY^+0.136 * GBPUSD^-0.119
#         * USDCAD^+0.091 * USDSEK^+0.042 * USDCHF^+0.036
#
# Only the SLOPE is used downstream, so the leading constant is irrelevant to
# every decision -- it is kept so the number is recognisable to a human
# reading a log next to a real quote.
#
# The exponent signs are the part that matters and the part that is easy to
# get backwards: a pair quoted USD-base (USDJPY, USDCAD, USDSEK, USDCHF) rises
# when the dollar strengthens, so it takes a POSITIVE exponent; a pair quoted
# USD-quote (EURUSD, GBPUSD) falls when the dollar strengthens and takes a
# NEGATIVE one. Inverting those would produce a confidently wrong dollar
# direction on every trade, which is worse than the unavailable it replaces.

DXY_SYNTHETIC_LEGS = (
    ("EURUSD", -0.576),
    ("USDJPY", +0.136),
    ("GBPUSD", -0.119),
    ("USDCAD", +0.091),
    ("USDSEK", +0.042),
    ("USDCHF", +0.036),
)
DXY_SYNTHETIC_CONSTANT = 50.14348112


def synthetic_dxy_closes(mt5, timeframe_const, bars: int):
    """
    Reconstruct the dollar index from its basket.

    Returns None when any leg is missing or short -- a partial basket is not a
    dollar index, and silently dropping a leg would reweight the whole thing
    without saying so.
    """
    series = {}
    for symbol, _ in DXY_SYNTHETIC_LEGS:
        try:
            rates = mt5.copy_rates_from_pos(symbol, timeframe_const, 0, bars)
        except Exception:
            return None
        if rates is None or len(rates) < bars:
            return None
        series[symbol] = [float(r["close"]) for r in rates]

    length = min(len(v) for v in series.values())
    closes = []
    for index in range(length):
        value = DXY_SYNTHETIC_CONSTANT
        for symbol, exponent in DXY_SYNTHETIC_LEGS:
            price = series[symbol][index]
            if price <= 0:
                return None
            value *= price ** exponent
        closes.append(value)
    return closes


def _ema_series(values, period: int):
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    series = [ema]
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
        series.append(ema)
    return series


def get_dxy_direction(timeframe_const=None) -> Dict[str, Any]:
    """
    Fetches DXY (whichever broker-symbol name resolves) and computes an
    EMA-slope direction read, same lightweight approach as
    core/trend_cascade.py's per-timeframe slope sign -- this doesn't
    need a full pattern-analysis pass, just "is the dollar index
    trending up, down, or flat right now."
    """
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        return {"available": False, "direction": "NEUTRAL", "reason": f"MT5 unavailable: {e}"}

    # DISABLED by default.
    #
    # The synthetic basket below is correct -- it reconstructs the index at
    # 98.76-98.99 against a real DXY that trades in the same range, which is
    # what proves the exponent signs. But correct is not the same as useful:
    # switching it on would start feeding a NEW, unvalidated signal into a
    # probability chain that was measured to carry no ranking information
    # (AUC 0.5254, 0.64 sigma). Adding an unvalidated input to a broken
    # aggregate is how the aggregate got here.
    #
    # Set DXY_CONFLUENCE_ENABLED=1 to turn it on for a governed experiment.
    if os.environ.get("DXY_CONFLUENCE_ENABLED", "").strip().lower() not in (
            "1", "true", "yes", "on"):
        return {
            "available": False,
            "direction": "NEUTRAL",
            "reason": ("dxy_confluence disabled (synthetic basket available; "
                       "set DXY_CONFLUENCE_ENABLED=1 to enable)"),
        }

    tf = timeframe_const if timeframe_const is not None else mt5.TIMEFRAME_H1
    dxy_symbol = _resolve_dxy_symbol(mt5)
    closes = None
    source = dxy_symbol

    if dxy_symbol is not None:
        try:
            rates = mt5.copy_rates_from_pos(dxy_symbol, tf, 0, BARS_NEEDED)
        except Exception as e:
            return {"available": False, "direction": "NEUTRAL",
                    "reason": f"fetch error on {dxy_symbol}: {e}"}
        if rates is not None and len(rates) >= EMA_PERIOD + SLOPE_LOOKBACK_BARS:
            closes = [float(r["close"]) for r in rates]

    if closes is None:
        # No index symbol on this broker -- rebuild it from the basket rather
        # than reporting unavailable on every trade, which is what this
        # component did on all 215 trades of the recorded history.
        closes = synthetic_dxy_closes(mt5, tf, BARS_NEEDED)
        source = "synthetic(basket)"

    if closes is None or len(closes) < EMA_PERIOD + SLOPE_LOOKBACK_BARS:
        got = 0 if closes is None else len(closes)
        return {
            "available": False,
            "direction": "NEUTRAL",
            "reason": (f"no DXY symbol (tried: {', '.join(DXY_SYMBOL_CANDIDATES)}) "
                       f"and the synthetic basket could not be built ({got} bars)"),
        }

    class _Row:
        """
        Stands in for an MT5 rate record.

        Downstream reads the close positionally as r[4] -- the MT5 tuple
        layout (time, open, high, low, close, ...) -- so a plain dict is not
        a drop-in. Both spellings are supported rather than picking one and
        hoping every caller agrees.
        """

        __slots__ = ("close",)

        def __init__(self, close):
            self.close = close

        def __getitem__(self, key):
            if key in (4, "close"):
                return self.close
            if key in (1, 2, 3, "open", "high", "low"):
                return self.close     # synthetic index has no OHLC spread
            raise KeyError(key)

    rates = [_Row(c) for c in closes]
    dxy_symbol = source

    closes = [float(r[4]) for r in rates]
    ema = _ema_series(closes, EMA_PERIOD)
    if len(ema) < SLOPE_LOOKBACK_BARS + 1:
        return {"available": False, "direction": "NEUTRAL", "reason": "insufficient EMA warm-up"}

    slope = ema[-1] - ema[-1 - SLOPE_LOOKBACK_BARS]
    slope_pct = (slope / ema[-1 - SLOPE_LOOKBACK_BARS]) * 100 if ema[-1 - SLOPE_LOOKBACK_BARS] else 0.0

    if abs(slope_pct) < FLAT_SLOPE_THRESHOLD_PCT:
        direction = "NEUTRAL"
    elif slope_pct > 0:
        direction = "STRONG_USD"
    else:
        direction = "WEAK_USD"

    return {
        "available": True,
        "dxy_symbol": dxy_symbol,
        "direction": direction,
        "slope_pct": round(slope_pct, 4),
        "current_value": round(closes[-1], 3),
        "reason": f"{dxy_symbol} EMA-slope {slope_pct:+.3f}% over {SLOPE_LOOKBACK_BARS} bars -> {direction}",
    }


def calculate_dxy_confluence_final_score(
    dxy_result: Dict[str, Any],
    base_probability: float,
    best_direction: str,
    symbol: str,
) -> Dict[str, Any]:
    """
    Turns DXY's direction into a signed probability adjustment, scaled
    by how much basket overlap this specific pair has with DXY (see
    module docstring) -- the same {"final_score": ...} shape used
    throughout asset_analysis.py's probability chain.
    """
    if not dxy_result.get("available") or dxy_result.get("direction") == "NEUTRAL":
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "aligned": None,
            "circularity_pct": None,
            "reason": dxy_result.get("reason", "DXY unavailable/flat"),
        }

    usd_role = _get_pair_usd_role(symbol)
    if usd_role is None:
        return {
            "final_score": base_probability,
            "adjustment": 0.0,
            "aligned": None,
            "circularity_pct": None,
            "reason": f"{symbol} has no USD leg -- DXY cross-check not applicable",
        }

    circularity_pct = _get_circularity_pct(symbol)
    effective_scale = 1.0 - circularity_pct  # EURUSD -> ~0.42x; AUDUSD/NZDUSD -> 1.0x

    # ✅ See NON_FX_USD_QUOTED_PREFIXES: a metal/commodity/crypto quoted
    # in USD scores 0.0 basket circularity and would otherwise take the
    # full effect as though it were as clean a read as AUDUSD.
    non_fx_usd = _is_non_fx_usd_quoted(symbol)
    if non_fx_usd:
        effective_scale = min(effective_scale, NON_FX_USD_EFFECT_SCALE)

    dxy_direction = dxy_result["direction"]  # STRONG_USD or WEAK_USD
    # USD is QUOTE (e.g. EURUSD): BUY = long other ccy / short USD, so a
    # WEAK_USD read aligns with BUY. USD is BASE (e.g. USDJPY): BUY =
    # long USD, so STRONG_USD aligns with BUY.
    if usd_role == "QUOTE":
        aligned = (best_direction == "BUY" and dxy_direction == "WEAK_USD") or \
                  (best_direction == "SELL" and dxy_direction == "STRONG_USD")
    else:  # BASE
        aligned = (best_direction == "BUY" and dxy_direction == "STRONG_USD") or \
                  (best_direction == "SELL" and dxy_direction == "WEAK_USD")

    adjustment = round((DXY_MAX_BONUS if aligned else DXY_MAX_PENALTY) * effective_scale, 1)
    final_score = max(5.0, min(95.0, base_probability + adjustment))

    if non_fx_usd:
        circularity_note = (
            f" (damped to {effective_scale:.0%} strength -- {symbol} is a non-FX instrument "
            f"quoted in USD, so DXY's slope is a weaker second opinion on it than on an FX major)"
        )
    elif circularity_pct > 0:
        circularity_note = (
            f" (damped to {effective_scale:.0%} strength -- {symbol}'s own currency is "
            f"~{circularity_pct:.0%} of the DXY basket, so this isn't fully independent evidence)"
        )
    else:
        circularity_note = ""

    return {
        "final_score": round(final_score, 1),
        "adjustment": adjustment,
        "aligned": aligned,
        "circularity_pct": round(circularity_pct, 3),
        "non_fx_usd_quoted": non_fx_usd,
        "effective_scale": round(effective_scale, 3),
        "reason": (
            f"{best_direction} {symbol} {'aligns with' if aligned else 'against'} "
            f"{dxy_result.get('dxy_symbol', 'DXY')}'s {dxy_direction} read{circularity_note}"
        ),
        "dxy": dxy_result,
    }