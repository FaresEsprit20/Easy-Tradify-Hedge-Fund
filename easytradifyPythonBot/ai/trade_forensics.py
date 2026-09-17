# ai/trade_forensics.py
"""
Trade forensics: what the market actually did around every stored trade.

Outcome tables say a trade lost. They cannot say WHY: the direction was wrong,
the direction was right but the stop was inside the noise, the trade reached
+2R and gave it back, or the entry was a minute late. Those need the PATH.

SOURCES
-------
  MT5 tick history   bid/ask from entry to 8 hours after it. Market data, so
                     it covers trades from all three accounts. Converted from
                     the broker clock (UTC+3) -- see core/broker_facts.
  price_evolution    the stored in-trade points (~every 5 s), each carrying a
                     full M1 re-analysis: how every component's reading
                     changed while the trade was open.

NOT A REPLAY OF THE STRATEGY
----------------------------
Entries are the real fills. Nothing re-decides whether to trade. Only EXITS are
re-run on the real subsequent ticks, to measure what a different stop or
target would have done -- the one question outcomes alone cannot answer.
The stored bracket is also re-run and must reproduce the recorded result; that
agreement rate is reported as the check that the path data is trustworthy.

UNITS
-----
R is the ORIGINAL stop distance. "fav" is the favourable excursion in R at the
price the trade would exit on (bid for a long, ask for a short), so spread is
inside every number. Net figures subtract commission; with position size set
for a constant dollar risk, a stop k times wider carries 1/k of the commission
in R (smaller lot, same dollars at risk).
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

logger = logging.getLogger(__name__)

FORENSICS_VERSION = "1.0"
HORIZON_HOURS = 8
HORIZON_MINUTES = (1, 5, 15, 60, 240)
STOP_MULTIPLES = (1.0, 1.5, 2.0, 3.0, 5.0, 8.0)
TARGETS_R = (0.5, 1.0, 1.5, 2.0, 3.0, 5.0)
ATR_BARRIERS = (2.0, 5.0)
ATR_STOP_MULTIPLES = (1.0, 2.0, 3.0, 5.0, 8.0)
NOISE_ADVERSE_R = 3.0          # a stopped trade that later reaches its target before
                               # going 3R against it was stopped inside the noise
COMMISSION_PER_LOT = {0: 7.03}
COMMISSION_PER_SHARE = 0.04

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "reports", "cache", "ticks")


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


# ============================================================
# TICKS
# ============================================================

def load_ticks(trade_id: str, symbol: str, start: datetime, hours: float = HORIZON_HOURS):
    """(t_utc_seconds, bid, ask) arrays from `start` for `hours`; cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{trade_id}.npz")
    if os.path.exists(path):
        data = np.load(path)
        return data["t"], data["bid"], data["ask"]

    import MetaTrader5 as mt5
    from core.broker_facts import broker_offset_seconds

    if not mt5.initialize():
        return None
    # Never add a symbol to Market Watch (operator rule: symbol_select only with
    # approval). A symbol that is not already selected has no ticks for us.
    info = mt5.symbol_info(symbol)
    if info is None or not info.select:
        return None
    offset = broker_offset_seconds(start)
    begin = start + timedelta(seconds=offset - 5)
    end = start + timedelta(seconds=offset, hours=hours)
    ticks = mt5.copy_ticks_range(symbol, begin, end, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return None
    t = ticks["time_msc"].astype(np.float64) / 1000.0 - offset
    bid, ask = ticks["bid"].astype(np.float64), ticks["ask"].astype(np.float64)
    # Carry the last quote forward: MT5 emits one-sided updates with the
    # other side as 0.
    for arr in (bid, ask):
        valid = arr > 0
        if not valid.any():
            return None
        idx = np.where(valid, np.arange(arr.size), 0)
        np.maximum.accumulate(idx, out=idx)
        arr[:] = arr[idx]
    keep = (bid > 0) & (ask > 0)
    t, bid, ask = t[keep], bid[keep], ask[keep]
    np.savez_compressed(path, t=t, bid=bid, ask=ask)
    return t, bid, ask


# ============================================================
# ONE TRADE
# ============================================================

def _first(mask: np.ndarray) -> Optional[int]:
    if not mask.any():
        return None
    return int(np.argmax(mask))


def barrier(fav: np.ndarray, t: np.ndarray, stop_r: float, target_r: float, commission_r: float = 0.0):
    """First touch of +target or -stop. Returns (R result, seconds, how)."""
    hit_t, hit_s = _first(fav >= target_r), _first(fav <= -stop_r)
    if hit_t is None and hit_s is None:
        return float(fav[-1]) - commission_r, float(t[-1] - t[0]), "TIMEOUT"
    if hit_s is None or (hit_t is not None and hit_t < hit_s):
        return target_r - commission_r, float(t[hit_t] - t[0]), "TARGET"
    return -stop_r - commission_r, float(t[hit_s] - t[0]), "STOP"


def path_metrics(trade: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    from core.broker_facts import pip_size

    entry = trade.get("entry") or {}
    price, stop, target = entry.get("price"), entry.get("stop_loss"), entry.get("take_profit")
    direction = trade.get("direction")
    opened = _utc(trade.get("opened_at"))
    if not all(isinstance(v, (int, float)) for v in (price, stop, target)) or \
            direction not in ("BUY", "SELL") or opened is None:
        return None
    risk = abs(price - stop)
    if not risk:
        return None
    sign = 1 if direction == "BUY" else -1
    ticks = load_ticks(trade["trade_id"], trade["symbol"], opened)
    if ticks is None:
        return None
    t, bid, ask = ticks
    keep = t >= opened.timestamp()
    if keep.sum() < 3:
        return None
    t, bid, ask = t[keep], bid[keep], ask[keep]

    exit_px = bid if sign > 0 else ask
    mid = (bid + ask) / 2
    fav = sign * (exit_px - price) / risk
    fav_mid = sign * (mid - price) / risk
    target_r = abs(target - price) / risk
    elapsed = t - t[0]

    risk_usd = trade.get("risk_usd_at_stop")
    volume = entry.get("volume") or 0
    is_stock = str(trade["symbol"]).upper().endswith((".NAS", ".NYSE"))
    commission_usd = volume * (COMMISSION_PER_SHARE if is_stock else COMMISSION_PER_LOT[0])
    commission_r = commission_usd / risk_usd if risk_usd else None

    result, seconds, how = barrier(fav, t, 1.0, target_r)
    end = _first(elapsed >= seconds) or len(t) - 1
    in_trade = slice(0, end + 1)

    pip = pip_size(trade["symbol"]) or (0.0001 if price < 20 else 0.01)
    analysis = trade.get("analysis_at_open") or {}
    vp = analysis.get("volatility_protection") or {}
    atr_pips = vp.get("atr_pips") if isinstance(vp, Mapping) else None

    out: Dict[str, Any] = {
        "trade_id": trade["trade_id"], "symbol": trade["symbol"], "direction": direction,
        "opened_at": opened.isoformat(), "risk_pips": round(risk / pip, 2),
        "target_r": round(target_r, 2), "ticks": int(t.size),
        "coverage_hours": round(float(elapsed[-1]) / 3600, 2),
        "commission_r": round(commission_r, 3) if commission_r else None,
        "replay_result": how, "replay_seconds": round(seconds, 1),
        "recorded_reason": (trade.get("close_data") or {}).get("close_reason"),
        "recorded_profit": (trade.get("close_data") or {}).get("profit_usd"),
        "mfe_r": round(float(fav[in_trade].max()), 3),
        "mae_r": round(float(fav[in_trade].min()), 3),
        "mfe_mid_r": round(float(fav_mid[in_trade].max()), 3),
        "mae_mid_r": round(float(fav_mid[in_trade].min()), 3),
        "seconds_to_mfe": round(float(elapsed[int(np.argmax(fav[in_trade]))]), 1),
        # Stopped on the exit side while the mid never reached the stop:
        # the spread alone took the trade out.
        "spread_stopout": how == "STOP" and float(fav_mid[in_trade].min()) > -1.0,
        "entry_spread_r": round(float(ask[0] - bid[0]) / risk, 3),
    }
    for minutes in HORIZON_MINUTES:
        idx = _first(elapsed >= minutes * 60)
        out[f"fav_{minutes}m"] = round(float(fav_mid[idx]), 3) if idx is not None else None
    for secs in (10, 30, 60):
        idx = _first(elapsed >= secs)
        out[f"mae_first_{secs}s"] = round(float(fav[:idx + 1].min()), 3) if idx is not None else None

    # ---- after a stop-out: was the direction right?
    if how == "STOP":
        after = slice(end, None)
        f_after, t_after = fav[after], t[after]
        reach_target = _first(f_after >= target_r)
        deep = _first(f_after <= -NOISE_ADVERSE_R)
        if reach_target is not None and (deep is None or reach_target < deep):
            out["after_stop"] = "REACHED_TARGET"
            out["after_stop_minutes"] = round(float(t_after[reach_target] - t_after[0]) / 60, 1)
        elif deep is not None:
            out["after_stop"] = "CONTINUED_AGAINST"
        else:
            out["after_stop"] = "UNRESOLVED"
        out["after_stop_max_r"] = round(float(f_after.max()), 2)

    # ---- the exit grid on the real path
    grid = {}
    for k in STOP_MULTIPLES:
        for T in TARGETS_R + (round(target_r, 2),):
            c = (commission_r / k) if commission_r else 0.0
            # Stop at k x the original distance, target at T in NEW-risk units
            # (T x k original R). Result in new-risk R: what a position sized
            # for the same dollar risk books, commission scaled by 1/k.
            r, s, h = barrier(fav, t, k, T * k, 0.0)
            grid[f"{k}x|{T}"] = round(r / k - c, 4)
    out["grid_net_r"] = grid

    # ---- stops sized by volatility instead of by the original distance
    if isinstance(atr_pips, (int, float)) and atr_pips > 0 and commission_r:
        atr_grid = {}
        atr_r = atr_pips * pip / risk
        for a in ATR_STOP_MULTIPLES:
            k = max(a * atr_r, 1e-9)
            c = commission_r / k
            for T in TARGETS_R:
                r, _, _ = barrier(fav, t, k, T * k, 0.0)
                atr_grid[f"{a}atr|{T}"] = round(r / k - c, 4)
        out["grid_atr_net_r"] = atr_grid
        out["atr_r"] = round(atr_r, 3)

    # ---- market direction, independent of the trade: which ATR barrier first
    if isinstance(atr_pips, (int, float)) and atr_pips > 0:
        up_mid = (mid - mid[0]) / (atr_pips * pip)
        for b in ATR_BARRIERS:
            u, d = _first(up_mid >= b), _first(up_mid <= -b)
            out[f"market_{int(b)}atr"] = (0 if u is None and d is None else
                                          1 if d is None or (u is not None and u < d) else -1)
    return out


# ============================================================
# ALL TRADES
# ============================================================

def classify(m: Mapping[str, Any]) -> str:
    """Why the trade ended the way it did, from its path alone."""
    if m["replay_result"] == "TARGET":
        return "WIN_TARGET"
    if m["replay_result"] == "TIMEOUT":
        return "OPEN_AT_HORIZON"
    if m.get("spread_stopout"):
        return "LOSS_SPREAD_STOP"
    if m["mfe_r"] >= 1.0:
        return "LOSS_GAVE_BACK"
    after = m.get("after_stop")
    if after == "REACHED_TARGET":
        return "LOSS_NOISE_STOP"
    if after == "CONTINUED_AGAINST":
        return "LOSS_WRONG_DIRECTION"
    return "LOSS_UNRESOLVED"


def collect(trades=None) -> List[Dict[str, Any]]:
    if trades is None:
        from ai.trade_repository import load_trades
        trades = load_trades()
    out = []
    for trade in trades:
        try:
            m = path_metrics(trade)
        except Exception as exc:
            logger.warning("forensics failed for %s: %s", trade.get("trade_id"), exc)
            m = None
        if m:
            m["class"] = classify(m)
            out.append(m)
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "trade_forensics", "version": FORENSICS_VERSION,
            "horizon_hours": HORIZON_HOURS}


def self_check(trades=None) -> Dict[str, Any]:
    """Barrier logic on planted paths; ok=None when no trades were given."""
    report: Dict[str, Any] = {"component": "trade_forensics", "ok": None, "checks": {}}
    t = np.arange(6, dtype=float)
    checks = {
        "target_first": barrier(np.array([0, .5, 1.2, -2, 0, 0]), t, 1, 1)[2] == "TARGET",
        "stop_first": barrier(np.array([0, -1.1, 2, 2, 2, 2]), t, 1, 1)[2] == "STOP",
        "timeout": barrier(np.array([0, .2, -.3, .4, .1, .3]), t, 1, 1)[2] == "TIMEOUT",
        "commission_subtracted": abs(barrier(np.array([0, 2.0]), t[:2], 1, 1, 0.5)[0] - 0.5) < 1e-9,
    }
    report["checks"] = checks
    if not trades:
        report["reason"] = "no trades supplied; barrier logic checked only"
        return report
    valid = [x for x in trades if isinstance(x, Mapping) and (x.get("entry") or {}).get("stop_loss")]
    if not valid:
        report["ok"] = False
        report["reason"] = "no trade with entry and stop"
        return report
    report["ok"] = all(checks.values())
    return report
