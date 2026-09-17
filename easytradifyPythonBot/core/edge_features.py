# ============================================================
# EDGE FEATURES -- directional readings computed straight from bars
# ============================================================
# FILE: core/edge_features.py
#
# Candidate NEW edges, none of which the engine had before 2026-09-15. Each
# feature is a market-relative reading: positive = expects price up. They
# are computed from closed bars only, so the same function serves a live
# analysis (bars from MT5) and the price-history study (bars sliced at the
# decision time).
#
#   Currency strength   each currency's average ATR-normalised move across
#                       every pair that contains it; a pair reads base minus
#                       quote. Needs the peer pairs' M1 closes.
#   Multi-horizon       return over 15 / 60 / 240 / 1440 minutes in ATR, and
#   momentum            how many of those horizons agree.
#   Session structure   position in today's range, side of the day open,
#                       break of the Asian range (00:00-07:00 UTC).
#   Previous day        above prior-day high / below prior-day low.
#   Sweep and reclaim   price traded beyond the last 60-minute high (low) in
#                       the last 15 minutes and is back inside: reads down
#                       (up).
#   Compression         15-bar ATR over 240-bar ATR (not directional; used
#                       as a context split).
#   Mean distance       distance from the 60-bar mean in ATR (reads toward
#                       the mean: negative when stretched above).
#
# Which of these carry edge, and how much, is decided by
# ai/component_calibration.py out of sample -- not here.
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

EDGE_FEATURES_VERSION = "1.0"
ATR_BARS = 60
MOMENTUM_HORIZONS = (15, 60, 240, 1440)
ASIA_END_HOUR_UTC = 7


def _col(rates, name):
    return np.asarray(rates[name], dtype=float)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, bars: int = ATR_BARS) -> Optional[float]:
    if close.size < bars + 1:
        return None
    prev = close[-bars - 1:-1]
    h, l = high[-bars:], low[-bars:]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    value = float(tr.mean())
    return value if value > 0 else None


def pair_move(rates, minutes: int) -> Optional[float]:
    """ATR-normalised close-to-close move over `minutes` M1 bars."""
    if rates is None or len(rates) < max(minutes, ATR_BARS) + 2:
        return None
    c = _col(rates, "close")
    a = atr(_col(rates, "high"), _col(rates, "low"), c)
    if not a:
        return None
    return float((c[-1] - c[-1 - minutes]) / a)


def currency_strength(m1_by_symbol: Mapping[str, Any], minutes: int) -> Dict[str, float]:
    """Average ATR move of each currency across the pairs it is in."""
    totals: Dict[str, list] = {}
    for symbol, rates in m1_by_symbol.items():
        s = symbol.upper()
        if len(s) != 6 or not s.isalpha():
            continue
        move = pair_move(rates, minutes)
        if move is None:
            continue
        base, quote = s[:3], s[3:]
        totals.setdefault(base, []).append(move)
        totals.setdefault(quote, []).append(-move)
    return {cur: float(np.mean(v)) for cur, v in totals.items() if len(v) >= 2}


def compute(symbol: str, m1, peers_m1: Optional[Mapping[str, Any]] = None,
            now_ts: Optional[float] = None, clock_offset_seconds: int = 0) -> Dict[str, Any]:
    """All edge features for `symbol` from its closed M1 bars (and peers').

    MT5 bar times are on the broker clock; `clock_offset_seconds` is that
    clock minus UTC (10800 for this broker under US DST). The trading day is
    the broker day (it starts at the New York close); session hours are UTC.
    """
    out: Dict[str, Any] = {"version": EDGE_FEATURES_VERSION}
    if m1 is None or len(m1) < ATR_BARS + 2:
        return out
    t = np.asarray(m1["time"], dtype=np.int64)
    h, l, c, o = _col(m1, "high"), _col(m1, "low"), _col(m1, "close"), _col(m1, "open")
    a = atr(h, l, c)
    if not a:
        return out
    price = c[-1]
    now_ts = int(now_ts if now_ts is not None else t[-1] + 60)

    agree = 0
    for m in MOMENTUM_HORIZONS:
        if c.size > m:
            r = float((price - c[-1 - m]) / a)
            out[f"mom_{m}"] = round(r, 3)
            agree += (r > 0) - (r < 0)
    out["mom_agreement"] = agree

    # Today's structure (broker day).
    day_start = now_ts - now_ts % 86400
    today = t >= day_start
    if today.sum() >= 5:
        th, tl = h[today].max(), l[today].min()
        if th > tl:
            out["day_range_pos"] = round(float((price - tl) / (th - tl)) * 2 - 1, 3)   # -1 low .. +1 high
        out["day_open_side"] = round(float((price - o[today][0]) / a), 3)
        asia_end = day_start + ASIA_END_HOUR_UTC * 3600 + clock_offset_seconds
        asia = today & (t < asia_end)
        if asia.sum() >= 60 and now_ts >= asia_end:
            ah, al = h[asia].max(), l[asia].min()
            out["asia_break"] = 1 if price > ah else -1 if price < al else 0
            out["asia_range_atr"] = round(float((ah - al) / a), 2)
    prev = (t >= day_start - 86400) & (t < day_start)
    if prev.sum() >= 60:
        ph, pl = h[prev].max(), l[prev].min()
        out["prev_day_break"] = 1 if price > ph else -1 if price < pl else 0
        out["prev_day_pos"] = round(float((price - pl) / (ph - pl)) * 2 - 1, 3) if ph > pl else None

    # Sweep and reclaim of the prior 60-minute extremes during the last 15 bars.
    if c.size >= 80:
        ref_h, ref_l = h[-75:-15].max(), l[-75:-15].min()
        recent_h, recent_l = h[-15:].max(), l[-15:].min()
        swept_up = recent_h > ref_h and price < ref_h
        swept_dn = recent_l < ref_l and price > ref_l
        out["sweep_reclaim"] = (-1 if swept_up else 0) + (1 if swept_dn else 0)

    if c.size >= 241:
        long_atr = atr(h, l, c, 240)
        short_atr = atr(h, l, c, 15)
        if long_atr and short_atr:
            out["compression"] = round(short_atr / long_atr, 3)
    if c.size >= 60:
        out["mean_dist_60"] = round(float(-(price - c[-60:].mean()) / a), 3)

    if peers_m1:
        s = symbol.upper()
        if len(s) == 6 and s.isalpha():
            for m in (60, 240):
                strength = currency_strength({**peers_m1, s: m1}, m)
                base, quote = strength.get(s[:3]), strength.get(s[3:])
                if base is not None and quote is not None:
                    out[f"ccy_strength_{m}"] = round(base - quote, 3)
    utc = now_ts - clock_offset_seconds
    out["hour_utc"] = int((utc % 86400) // 3600)
    out["weekday"] = int(((utc // 86400) + 3) % 7)   # 0 = Monday
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "edge_features", "version": EDGE_FEATURES_VERSION}


# The peer set the price-history study measured currency strength on. Live
# inputs must use the same set, or the strength reading is a different number.
PEER_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
                "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY", "XAUUSD", "XAGUSD")
LIVE_BARS = 1600
PEER_BARS = 300


def _closed(rates, drop_forming: bool):
    if rates is None or len(rates) < 2:
        return None
    return rates[:-1] if drop_forming else rates


def live_compute(symbol: str, replay: bool = False, extended_m1=None) -> Dict[str, Any]:
    """Edge features from MT5 bars (the replay shim serves the same calls).

    Live, copy_rates_from_pos(..., 0, n) ends with the bar still forming, so it
    is dropped; a replay serves closed bars only."""
    import MetaTrader5 as mt5
    from datetime import datetime, timezone
    from core.closed_bars import is_active as closed_bars_active

    # inside a live analysis the fetch already skips the forming bar
    replay = replay or closed_bars_active()
    m1 = (extended_m1 if extended_m1 is not None and len(extended_m1) > 1
          else _closed(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, LIVE_BARS), not replay))
    if m1 is None:
        return {"version": EDGE_FEATURES_VERSION, "error": "no M1 bars"}
    peers = {}
    for peer in PEER_SYMBOLS:
        if peer.upper() == symbol.upper():
            continue
        try:
            r = _closed(mt5.copy_rates_from_pos(peer, mt5.TIMEFRAME_M1, 0, PEER_BARS), not replay)
        except Exception:
            r = None
        if r is not None:
            peers[peer] = r
    now_ts = int(m1["time"][-1]) + 60
    try:
        from core.broker_facts import _us_dst
        offset = 10800 if _us_dst(datetime.fromtimestamp(now_ts - 10800, timezone.utc)) else 7200
    except Exception:
        offset = 10800
    return compute(symbol, m1, peers, now_ts=now_ts, clock_offset_seconds=offset)
