"""The RSI divergence setup -- ONE definition, used by the app and the shadow runner.

Operator, 2026-09-18: "edit my current code in RSI so it applies exactly that last
config: no Fibonacci, BOS, etc." This module is that config; nothing else in the
app defines RSI-divergence entries or exits any more.

Where it comes from: the M1 RSI-divergence studies of 2026-09-18
(tradify_study/trend_m1_v1/), ~300 configurations on true bid/ask M1 bars. The
best measured -- and the only kind that beat its own opposite side in both halves
of history -- is below. At 30/70 it was still net NEGATIVE in the study (about -0.15R /
-0.11R per trade, 56% of trades won), which is why the demo account trades it
only once the live shadow verdict reads CONFIRMED (engine_v2/run/shadow_rsi_div_m1.py).

THE SETUP (M1 only; mid = bid + half the bar's spread; closed bars only)
  1. Divergence (classic / regular -- the reversal kind):
       BUY : a swing low that is the lowest of +-50 M1 bars, LOWER than the
             previous such swing low (within 1000 bars), while RSI(14) there is
             HIGHER than at the previous one, and RSI < 20 at the new swing.
       SELL: the mirror -- a HIGHER swing high, a LOWER RSI high, RSI > 80.
     It is known 50 bars after the swing (when the swing is confirmed).
  2. Confirmation -- break of structure (BOS): within the next 60 M1 bars, an M1
     bar CLOSES above the highest high of the previous 5 bars (below the lowest
     low for a SELL). Entry at the next price.
     Cancelled if price reaches the stop before the BOS; expires after 60 bars.
  3. Stop: the divergence swing -1 pip (+1 for a SELL). No Fibonacci, no price target.
  4. Exit: a BUY when RSI(14) closes at or above 80; a SELL at or below 20;
     stop first; 480-bar cap.

LEVELS 80/20 (operator decision, 2026-09-18, for entry AND exit). The study
measured the best version at 30/70. At 80/20 on +-50-bar swings the divergence
appeared only ~20 times in 3.5 months across 15 markets -- too few to measure --
so the shadow verdict (300 trades) will take a long time to arrive; on +-5-bar
swings 20/80 lost -0.35 to -0.65R per trade. Exiting at 80 instead of 70 measured
about the same (-0.16/-0.13R vs -0.15/-0.15R).
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import numpy as np

SETUP_NAME = "RSI divergence + BOS (M1)"
PIV = 50              # swing = extreme of +-50 M1 bars
LOOK = 1000           # the previous swing may be up to 1000 bars back
RSI_N = 14
EXTREME = 20.0        # BUY: RSI < 20 at the swing low; SELL: RSI > 80 at the swing high
BOS_BARS = 5          # break of the previous 5 bars' high / low
WAIT = 60             # bars allowed for the BOS after the divergence is known
EXIT_BUY = 80.0       # a BUY exits when RSI >= 80; a SELL when RSI <= 20
HOLD_BARS = 480       # cap
HISTORY = 1600        # closed M1 bars needed: LOOK + 2*PIV + WAIT + RSI warm-up


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def rsi_wilder(c: np.ndarray, n: int = RSI_N) -> np.ndarray:
    c = np.asarray(c, dtype=float)
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = np.empty_like(c), np.empty_like(c)
    au[0], ad[0] = up[0], dn[0]
    for i in range(1, c.size):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def pivot_flags(x: np.ndarray, low: bool) -> np.ndarray:
    """x[i] is the extreme of x[i-PIV : i+PIV+1]; False where the window is incomplete."""
    x = np.asarray(x, dtype=float)
    out = np.zeros(x.size, bool)
    if x.size < 2 * PIV + 1:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, 2 * PIV + 1)
    ext = w.min(axis=1) if low else w.max(axis=1)
    out[PIV:x.size - PIV] = x[PIV:x.size - PIV] == ext
    return out


def divergence_at(j: int, high, low, r, lo_piv, hi_piv):
    """The classic divergence whose swing is at bar j, or None: (side, swing price, rsi)."""
    for is_low in (True, False):
        piv = lo_piv if is_low else hi_piv
        if j < 0 or j >= piv.size or not piv[j]:
            continue
        # the IMMEDIATELY preceding swing, as in the study; a pair closer than
        # PIV bars or further than LOOK bars apart is not compared at all
        prev = np.flatnonzero(piv[:j])
        if not prev.size:
            continue
        p = int(prev[-1])
        if not PIV < j - p <= LOOK:
            continue
        px = low if is_low else high
        if is_low and px[j] < px[p] and r[j] > r[p] and r[j] < EXTREME:
            return 1, float(px[j]), float(r[j])
        if not is_low and px[j] > px[p] and r[j] < r[p] and r[j] > 100 - EXTREME:
            return -1, float(px[j]), float(r[j])
    return None


def detect(high, low, close):
    """A divergence whose swing is confirmed by the bar that just closed (the last
    element), or None: (side, swing index, swing price, rsi at the swing)."""
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    j = close.size - 1 - PIV
    if j - PIV <= 0:
        return None
    r = rsi_wilder(close)
    hit = divergence_at(j, high, low, r, pivot_flags(low, True), pivot_flags(high, False))
    return None if hit is None else (hit[0], j, hit[1], hit[2])


def bos(side: int, k: int, high, low, close) -> bool:
    """Bar k closes beyond the previous BOS_BARS bars' extreme in the trade's direction."""
    if k < BOS_BARS:
        return False
    if side == 1:
        return close[k] > np.max(high[k - BOS_BARS:k])
    return close[k] < np.min(low[k - BOS_BARS:k])


def divergence_state(high, low, close, stop_low, stop_high, pip: float,
                     not_before: Optional[int] = None) -> Dict[str, Any]:
    """Where the RSI divergence stands on the bar that just closed (the last element).

    status  CONFIRMED     a divergence's FIRST break of structure is this bar -> enter now
            AWAITING_BOS  a divergence is known (within the last WAIT bars), its stop has
                          not been reached, and no break of structure yet
            NONE          neither
    Oldest divergence first; an older one still waiting has priority over newer ones.
    Stateless: the same bars give the same answer.

    high/low/close: MID prices of closed M1 bars. stop_low/stop_high: the prices a
    stop is judged on (bid lows for a BUY, ask highs for a SELL).
    not_before: ignore divergences known at or before this bar index (the exit of
    the previous trade -- one trade per market at a time, as in the study).
    """
    none = {"status": "NONE"}
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    n = close.size
    if n < 2 * PIV + 2 * BOS_BARS:
        return none
    last = n - 1
    r = rsi_wilder(close)
    lo_piv, hi_piv = pivot_flags(low, True), pivot_flags(high, False)
    for known in range(max(2 * PIV, last - WAIT), last):
        if not_before is not None and known <= not_before:
            continue
        j = known - PIV
        hit = divergence_at(j, high, low, r, lo_piv, hi_piv)
        if hit is None:
            continue
        side, swing, rsi_at = hit
        stop_px = swing - side * pip
        info = {"side": side, "swing_index": j, "known_index": known, "swing_price": swing,
                "stop_price": stop_px, "rsi_at_swing": round(rsi_at, 2), "rsi_now": round(float(r[last]), 2)}
        still_waiting = True
        for k in range(known + 1, last + 1):
            if (side == 1 and stop_low[k] <= stop_px) or (side == -1 and stop_high[k] >= stop_px):
                still_waiting = False                          # stopped before confirming: cancelled
                break
            if bos(side, k, high, low, close):
                if k == last:
                    return {"status": "CONFIRMED", "bos_index": k, **info}
                still_waiting = False                          # confirmed earlier: not a new entry
                break
        if still_waiting:
            # an older divergence still waiting for its BOS has priority over newer ones
            return {"status": "AWAITING_BOS", "bars_waited": last - known, **info}
    return {"status": "NONE", "rsi_now": round(float(r[last]), 2)}


def current_setup(high, low, close, stop_low, stop_high, pip: float,
                  not_before: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The setup to enter NOW (a divergence confirmed by BOS on the last bar), or None."""
    st = divergence_state(high, low, close, stop_low, stop_high, pip, not_before)
    return st if st["status"] == "CONFIRMED" else None


def rsi_exit_hit(side: int, rsi_value: float) -> bool:
    return rsi_value >= EXIT_BUY if side == 1 else rsi_value <= 100 - EXIT_BUY


def mid_arrays(rates, point: float):
    """MT5 M1 rates (bid OHLC + spread in points) -> mid high/low/close and the
    bid-low / ask-high a stop is judged on."""
    sp = rates["spread"].astype(float) * point
    bh, bl, bc = (rates[k].astype(float) for k in ("high", "low", "close"))
    return bh + sp / 2, bl + sp / 2, bc + sp / 2, bl, bh + sp


def state_from_rates(rates, symbol: str, point: float) -> Dict[str, Any]:
    """divergence_state on MT5 M1 rates (CLOSED bars; the last is the bar that just closed)."""
    if rates is None or len(rates) < HISTORY // 2:
        have = 0 if rates is None else len(rates)
        return {"status": "NONE", "reason": f"needs ~{HISTORY} closed M1 bars, has {have}"}
    h, l, c, stop_low, stop_high = mid_arrays(rates, point)
    return divergence_state(h, l, c, stop_low, stop_high, pip_size(symbol))


def score_indicator(state: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The app's RSI reading from the divergence state, in the shape
    score_rsi_indicator_with_divergence returns. None when there is no divergence
    (the caller then scores RSI without one, as before).

      CONFIRMED     divergence + BOS on this bar: the setup's entry  -> confidence 95
      AWAITING_BOS  divergence known, not yet confirmed              -> confidence 75
    Score sign: + bullish, - bearish (the scorer's convention)."""
    status = state.get("status")
    if status not in ("CONFIRMED", "AWAITING_BOS"):
        return None
    side = state["side"]
    rec = "BUY" if side == 1 else "SELL"
    kind = "bullish" if side == 1 else "bearish"
    rsi_sw = state["rsi_at_swing"]
    if status == "CONFIRMED":
        return {"recommendation": rec, "score": 25 * side, "confidence": 95,
                "reason": (f"RSI: regular {kind} divergence (RSI {rsi_sw} at the swing) "
                           f"confirmed by a break of structure -- {SETUP_NAME}"),
                "divergence_status": status}
    waited = state["bars_waited"]
    return {"recommendation": rec, "score": 15 * side, "confidence": 75,
            "reason": (f"RSI: regular {kind} divergence (RSI {rsi_sw} at the swing), "
                       f"awaiting a break of structure ({waited}/{WAIT} bars)"),
            "divergence_status": status}


def setup_from_state(state: Mapping[str, Any], order_type: str, current_price: float,
                     symbol: str) -> Dict[str, Any]:
    """The app's RSI setup, in the shape core.strategy_setups.pick expects."""
    base = {"setup": SETUP_NAME, "is_perfect_setup": False}
    if state.get("status") != "CONFIRMED":
        return {**base, "reason": state.get("reason") or
                "no RSI divergence confirmed by a break of structure on the last closed bar"}
    pip = pip_size(symbol)
    direction = "BUY" if state["side"] == 1 else "SELL"
    if order_type and order_type.upper() not in (direction, "AUTO", "BOTH", ""):
        return {**base, "direction": direction,
                "reason": f"setup is {direction}, the analysis trades {order_type}"}
    stop = state["stop_price"]
    risk_pips = (current_price - stop) / pip if direction == "BUY" else (stop - current_price) / pip
    if risk_pips <= 0:
        return {**base, "direction": direction, "reason": "price is already through the divergence swing"}
    return {**base, "is_perfect_setup": True, "direction": direction,
            "entry_price": round(current_price, 5), "stop_loss": round(stop, 5), "take_profit": None,
            "risk_pips": round(risk_pips, 1), "reward_pips": None, "risk_reward_ratio": None,
            "exit_type": "RSI_80_20", "stop_loss_basis": "the divergence swing -1 pip",
            "take_profit_basis": "none: a BUY exits when RSI(14) reaches 80, a SELL at 20",
            "rsi_at_swing": state["rsi_at_swing"], "reason": f"{SETUP_NAME}: {direction} confirmed"}


def evaluate_setup(rates, symbol: str, order_type: str, current_price: float,
                   point: float) -> Dict[str, Any]:
    """setup_from_state on MT5 M1 rates."""
    return setup_from_state(state_from_rates(rates, symbol, point), order_type, current_price, symbol)
