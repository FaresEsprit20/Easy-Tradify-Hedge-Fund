# ============================================================
# TIMING FEATURES -- will a correct-direction entry survive its stop?
# ============================================================
# FILE: core/timing_features.py
#
# On the untouched holdout the calibrated model picks the right direction 78%
# of the time, yet ~55% of those trades touch the stop before reaching +2R:
# the stop sits inside the bar-to-bar noise. The stop is fixed (user
# decision), so the lever is WHEN to enter. These features describe the
# entry moment relative to the stop itself, for a given side:
#
#   stop_atr            stop distance in ATR -- how much noise room it has
#   ret_1/3/5_stop      the last 1/3/5 bars' move in the trade's direction, in stops
#   adverse_room_stop   distance to the lowest low (BUY) / highest high (SELL)
#                       of the last 10 bars, in stops -- where the noise has been
#   pullback_stop       distance back from the 30-bar extreme in the trade's
#                       direction, in stops (how far the move has retraced)
#   last_range_stop     the last bar's range in stops
#   spread_stop         spread in stops
#
# Computed from closed M1 bars only, so the price-history study and the live
# engine produce the same numbers.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

TIMING_VERSION = "1.1"
FEATURES = ("stop_atr", "ret_1_stop", "ret_3_stop", "ret_5_stop", "adverse_room_stop",
            "pullback_stop", "last_range_stop", "spread_stop",
            "close_pos_side", "volume_burst", "atr_ratio_15_60", "slope_15_stop", "range_pos_60_side",
            "minute_of_hour", "hour_utc", "weekday")


def compute(m1, side: int, stop_distance: float, atr_price: float, spread_price: float = 0.0,
            now_ts: Optional[int] = None, clock_offset_seconds: int = 10800) -> Optional[Dict[str, float]]:
    """Timing features for entering `side` (+1 BUY / -1 SELL) now, with a stop
    `stop_distance` (price units) away. None without enough bars."""
    if m1 is None or len(m1) < 61 or not stop_distance or stop_distance <= 0 or side not in (1, -1):
        return None
    h = np.asarray(m1["high"], dtype=float)
    l = np.asarray(m1["low"], dtype=float)
    c = np.asarray(m1["close"], dtype=float)
    price = c[-1]
    out = {
        "stop_atr": stop_distance / atr_price if atr_price and atr_price > 0 else 0.0,
        "ret_1_stop": side * (c[-1] - c[-2]) / stop_distance,
        "ret_3_stop": side * (c[-1] - c[-4]) / stop_distance,
        "ret_5_stop": side * (c[-1] - c[-6]) / stop_distance,
        "last_range_stop": (h[-1] - l[-1]) / stop_distance,
        "spread_stop": (spread_price or 0.0) / stop_distance,
    }
    if side > 0:
        out["adverse_room_stop"] = (price - l[-10:].min()) / stop_distance
        out["pullback_stop"] = (h[-30:].max() - price) / stop_distance
    else:
        out["adverse_room_stop"] = (h[-10:].max() - price) / stop_distance
        out["pullback_stop"] = (price - l[-30:].min()) / stop_distance
    # --- 1.1: bar shape, participation, volatility state, slope, session clock
    rng = h[-1] - l[-1]
    pos = (c[-1] - l[-1]) / rng if rng > 0 else 0.5
    out["close_pos_side"] = (pos if side > 0 else 1 - pos) * 2 - 1          # +1 closed at the trade's end
    try:
        v = np.asarray(m1["tick_volume"], dtype=float)
        out["volume_burst"] = float(v[-5:].mean() / v[-60:].mean()) if v[-60:].mean() > 0 else 1.0
    except (KeyError, ValueError, IndexError):
        out["volume_burst"] = 1.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    out["atr_ratio_15_60"] = float(tr[-15:].mean() / tr[-60:].mean()) if tr[-60:].mean() > 0 else 1.0
    x = np.arange(15)
    out["slope_15_stop"] = side * float(np.polyfit(x, c[-15:], 1)[0]) * 15 / stop_distance
    hi60, lo60 = h[-60:].max(), l[-60:].min()
    rp = (price - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5
    out["range_pos_60_side"] = (rp if side > 0 else 1 - rp) * 2 - 1
    ts = int(now_ts if now_ts is not None else int(m1["time"][-1]) + 60) - clock_offset_seconds
    out["minute_of_hour"] = (ts % 3600) // 60
    out["hour_utc"] = (ts % 86400) // 3600
    out["weekday"] = ((ts // 86400) + 3) % 7
    return {k: round(float(v), 4) for k, v in out.items()}


def get_status() -> Dict[str, Any]:
    return {"component": "timing_features", "version": TIMING_VERSION, "features": list(FEATURES)}
