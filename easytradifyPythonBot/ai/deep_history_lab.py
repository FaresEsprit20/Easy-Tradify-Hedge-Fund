# ai/deep_history_lab.py
"""
The same concepts, over years instead of weeks.

Every lab so far ran on 16 weeks of tick data -- the only window MT5 serves
minute data for -- and an H4 zone setup fires nine times per symbol in that
window. Nothing rare can be proved on it. The terminal does serve M15 back
about four years and H1 about sixteen, so the concepts are re-run there.

Those bars are BID only, which is exactly what produced the first false edge
(rollover spread spikes read as wicks), so this module never pretends
otherwise:

  fills     a BUY pays the ask = bid + the spread measured for that symbol at
            that broker hour (tradify_study/spread_profile.json, taken from
            real ticks); a SELL fills on the bid and exits on the ask
  rollover  broker hour 0 is excluded from triggering anything -- EURUSD's
            spread there is 3.68 pips against 0.06 normally, GBPAUD's 25.6,
            so a stop "hit" in that hour is the broker, not the market
  costs     commission $7.03 per lot at a lot sized to the $4 risk
  periods   split by calendar: first half discovery, third quarter validation,
            last quarter holdout -- chosen once, never re-cut

Anything that survives here is then re-checked on the 16 weeks of true bid/ask
ticks, where nothing is modelled.

CALIBRATION (2026-09-16, 361 matched H1-zone trades in the tick window, same
plans re-simulated with real limit fills): this lab reads about 0.05R per
trade TOO GOOD -- modelled +0.002R against tick-verified -0.050R, win rates
46/58/46% against 41/56/45%. Subtract MODEL_OPTIMISM_R before believing any
expectancy here, and verify survivors on ticks.

    python -m ai.deep_history_lab zones --htf H1 --ltf M15
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BARS_DIR = Path(os.getenv("DEEP_BARS_DIR") or ROOT / "reports" / "cache" / "mt5_bars")
SPREAD_PROFILE = Path(os.getenv("SPREAD_PROFILE") or ROOT / "reports" / "cache" / "spread_profile.json")
REPORT_DIR = ROOT / "reports"

TF_SECONDS = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
ROLLOVER_BROKER_HOURS = (0,)
COMMISSION_PER_LOT = 7.03
# measured bias of this lab against true tick fills (see the docstring)
MODEL_OPTIMISM_R = 0.05
RISK_USD = 4.0
HOLD_BARS = {"M15": 96, "H1": 24}          # 24 hours either way
EXPIRY_BARS = {"M15": 288, "H1": 72}       # 3 days to be touched


def load_bars(symbol: str) -> Dict[str, np.ndarray]:
    path = BARS_DIR / f"{symbol}.npz"
    if not path.exists():
        return {}
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def spread_table() -> Dict[str, Any]:
    if SPREAD_PROFILE.exists():
        return json.loads(SPREAD_PROFILE.read_text())
    return {}


def spread_pips(profile: Mapping[str, Any], symbol: str, hour: np.ndarray) -> np.ndarray:
    """The measured spread for this symbol at each broker hour, in pips."""
    entry = profile.get(symbol) or {}
    by_hour = entry.get("median_by_broker_hour_pips") or {}
    fallback = float(entry.get("median_pips") or 1.0)
    lut = np.array([float(by_hour.get(str(h), fallback)) for h in range(24)])
    return lut[np.asarray(hour, dtype=int) % 24]


def as_bars(rates: np.ndarray, tf: str, ltf_times: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    """The bar shape ai/structure_lab.py's structure()/zones() expect."""
    out = {"time": rates["time"].astype(np.int64), "open": rates["open"].astype(float),
           "high": rates["high"].astype(float), "low": rates["low"].astype(float),
           "close": rates["close"].astype(float), "sec": TF_SECONDS[tf]}
    if ltf_times is not None:
        out["end"] = np.searchsorted(ltf_times, out["time"] + out["sec"], side="left")
    else:
        out["end"] = np.arange(1, out["time"].size + 1)
    return out


def bracket_on_bid_bars(low: np.ndarray, high: np.ndarray, close: np.ndarray, hour: np.ndarray,
                        spread: np.ndarray, side: int, entry: float, stop: float, target: float) -> Tuple[str, float]:
    """Stop/target on bid bars, with the ask reconstructed for the side that
    needs it and the rollover hour unable to trigger anything."""
    tradable = ~np.isin(hour, ROLLOVER_BROKER_HOURS)
    if side > 0:                                   # long: exits read the bid directly
        hit_stop = (low <= stop) & tradable
        hit_target = (high >= target) & tradable
        last = close[-1]
    else:                                          # short: exits read the ask
        hit_stop = ((high + spread) >= stop) & tradable
        hit_target = ((low + spread) <= target) & tradable
        last = close[-1] + spread[-1]
    i_s = int(np.argmax(hit_stop)) if hit_stop.any() else None
    i_t = int(np.argmax(hit_target)) if hit_target.any() else None
    risk = abs(entry - stop)
    if risk <= 0:
        return "NONE", 0.0
    if i_s is not None and (i_t is None or i_s <= i_t):
        return "STOP", -1.0
    if i_t is not None:
        return "TARGET", round(abs(target - entry) / risk, 3)
    return "TIMEOUT", round(side * (last - entry) / risk, 3)


def periods(ts: np.ndarray) -> Dict[str, np.ndarray]:
    """Calendar split, cut once: half / quarter / quarter."""
    lo, hi = float(np.min(ts)), float(np.max(ts))
    a, b = lo + 0.5 * (hi - lo), lo + 0.75 * (hi - lo)
    return {"discovery": ts < a, "validation": (ts >= a) & (ts < b), "holdout": ts >= b}


def zone_trades(symbol: str, htf: str = "H1", ltf: str = "M15", buffer_atr: float = 0.25,
                targets=(1.0, 2.0)) -> List[Dict[str, Any]]:
    """First-touch limit at a zone's proximal edge, the way structure_lab
    measured it on ticks -- now over years."""
    from ai.structure_lab import structure, zones, atr
    from ai.price_history_study import usd_per_price_unit_per_lot, symbol_specs

    bars = load_bars(symbol)
    if htf not in bars or ltf not in bars:
        return []
    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    usd = usd_per_price_unit_per_lot(symbol)
    if not pip or not usd:
        return []
    profile = spread_table()
    lo = as_bars(bars[ltf], ltf)
    # H1 reaches back to 2010 but M15 only ~4 years: a zone older than the
    # entry timeframe has no bars to be traded on, and mapping it to index 0
    # trades a 2010 level at 2022 prices. Keep only the overlap.
    htf_rates = bars[htf]
    overlap = (htf_rates["time"].astype(np.int64) >= int(lo["time"][0])) &               (htf_rates["time"].astype(np.int64) <= int(lo["time"][-1]))
    if overlap.sum() < 100:
        return []
    hb = as_bars(htf_rates[overlap], htf, ltf_times=lo["time"])
    ha = atr(hb)
    lo_hour = (lo["time"] % 86400) // 3600
    lo_spread = spread_pips(profile, symbol, lo_hour) * pip
    rows: List[Dict[str, Any]] = []
    for z in zones(hb, structure(hb), ha):
        s = int(hb["end"][z["bos_i"]]) if z["bos_i"] < hb["end"].size else None
        if s is None or s <= 0 or s >= lo["time"].size - 10:
            continue
        end = min(lo["time"].size, s + EXPIRY_BARS[ltf])
        d = z["dir"]
        # price trades into the zone (bid bars; for a short the ask matters)
        if d > 0:
            touch = lo["low"][s:end] <= z["proximal"]
        else:
            touch = (lo["high"][s:end] + lo_spread[s:end]) >= z["proximal"]
        gone = (lo["close"][s:end] < z["distal"]) if d > 0 else (lo["close"][s:end] > z["distal"])
        ti = int(np.argmax(touch)) if touch.any() else None
        gi = int(np.argmax(gone)) if gone.any() else None
        if ti is None or (gi is not None and gi < ti):
            continue
        k = s + ti
        if (lo_hour[k] in ROLLOVER_BROKER_HOURS) or k >= lo["time"].size - 5:
            continue                                    # never enter in the rollover hour
        entry = z["proximal"] + (lo_spread[k] if d > 0 else 0.0)
        stop = z["distal"] - d * buffer_atr * z["atr"]
        risk = d * (entry - stop)
        if risk <= 0:
            continue
        e2 = min(lo["time"].size, k + HOLD_BARS[ltf])
        sl = slice(k, e2)
        rpl = risk * usd
        for tr in targets:
            result, r = bracket_on_bid_bars(lo["low"][sl], lo["high"][sl], lo["close"][sl], lo_hour[sl],
                                            lo_spread[sl], d, entry, stop, entry + d * tr * risk)
            if result == "NONE":
                continue
            rows.append({"symbol": symbol, "htf": htf, "ltf": ltf, "target_r": tr, "dir": d,
                         "ts": int(lo["time"][k]), "result": result, "r": r,
                         # the actual plan, so any trade can be re-simulated on
                         # true bid/ask ticks where those exist
                         "entry": round(float(entry), 6), "stop": round(float(stop), 6),
                         "target": round(float(entry + d * tr * risk), 6), "risk_price": round(float(risk), 6),
                         "commission_r": round(COMMISSION_PER_LOT / rpl, 4) if rpl > 0 else None,
                         "affordable": bool(0.01 * rpl <= RISK_USD * 1.1),
                         "choch": z["choch"], "swept_origin": z["swept_origin"],
                         "departure_atr": round(z["departure_atr"], 2), "width_atr": round(z["width_atr"], 2),
                         "risk_atr": round(risk / z["atr"], 2), "hour": int(lo_hour[k]),
                         "wait_bars": int(ti)})
    return rows


def sweep_trades(symbol: str, ltf: str = "M15", reclaim_bars: int = 4, buffer_atr: float = 0.25,
                 targets=(1.0, 2.0)) -> List[Dict[str, Any]]:
    """Previous-day high/low swept and reclaimed, over years.

    On 16 weeks of ticks this lost on every period; the question here is
    whether that holds across four years and several regimes, or whether the
    window was simply too short to tell.
    """
    from ai.structure_lab import atr
    from ai.price_history_study import usd_per_price_unit_per_lot, symbol_specs

    bars = load_bars(symbol)
    if ltf not in bars:
        return []
    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    usd = usd_per_price_unit_per_lot(symbol)
    if not pip or not usd:
        return []
    lo = as_bars(bars[ltf], ltf)
    a = atr(lo)
    hour = (lo["time"] % 86400) // 3600
    spread = spread_pips(spread_table(), symbol, hour) * pip
    day = lo["time"] // 86400                       # broker day: the FX day starts at 00:00 broker
    rows: List[Dict[str, Any]] = []
    days = np.unique(day)
    prev = {}
    for d in days:
        m = day == d
        prev[int(d)] = (float(lo["high"][m].max()), float(lo["low"][m].min()))
    for d in days[1:]:
        ref = prev.get(int(d) - 1)
        if not ref:
            continue
        pdh, pdl = ref
        idx = np.flatnonzero((day == d) & ~np.isin(hour, ROLLOVER_BROKER_HOURS))
        if idx.size < reclaim_bars + 2:
            continue
        for level, side in ((pdh, -1), (pdl, 1)):   # sweeping the high sells, the low buys
            swept_at = None
            for n, i in enumerate(idx):
                if not np.isfinite(a[i]) or a[i] <= 0:
                    continue
                beyond = (lo["high"][i] + spread[i]) > level if side < 0 else lo["low"][i] < level
                closed_beyond = lo["close"][i] > level if side < 0 else lo["close"][i] < level
                if swept_at is None and beyond:
                    swept_at = n
                    continue
                if swept_at is not None and n - swept_at <= reclaim_bars and not closed_beyond:
                    seg = idx[swept_at:n + 1]
                    extreme = float(lo["high"][seg].max()) if side < 0 else float(lo["low"][seg].min())
                    k = int(i) + 1
                    if k >= lo["time"].size - 5:
                        break
                    entry = float(lo["close"][i] + (spread[i] if side > 0 else 0.0))
                    stop = extreme - side * buffer_atr * float(a[i])
                    risk = side * (entry - stop)
                    if risk <= 0:
                        break
                    e2 = min(lo["time"].size, k + HOLD_BARS[ltf])
                    sl = slice(k, e2)
                    rpl = risk * usd
                    for tr in targets:
                        result, r = bracket_on_bid_bars(lo["low"][sl], lo["high"][sl], lo["close"][sl],
                                                        hour[sl], spread[sl], side, entry, stop,
                                                        entry + side * tr * risk)
                        if result == "NONE":
                            continue
                        rows.append({"symbol": symbol, "setup": "pd_sweep", "ltf": ltf, "target_r": tr,
                                     "dir": side, "ts": int(lo["time"][k]), "result": result, "r": r,
                                     "entry": round(entry, 6), "stop": round(stop, 6),
                                     "target": round(entry + side * tr * risk, 6), "risk_price": round(risk, 6),
                                     "commission_r": round(COMMISSION_PER_LOT / rpl, 4) if rpl > 0 else None,
                                     "affordable": bool(0.01 * rpl <= RISK_USD * 1.1),
                                     "depth_atr": round(abs(extreme - level) / float(a[i]), 2),
                                     "bars_to_reclaim": int(n - swept_at), "hour": int(hour[i])})
                    break
    return rows


def summarize(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"n": 0}
    net = np.array([r["r"] - (r["commission_r"] or 0) for r in rows])
    won = np.array([r["result"] == "TARGET" for r in rows])
    return {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1),
            "net_r": round(float(net.mean()), 3),
            "net_r_tick_adjusted": round(float(net.mean()) - MODEL_OPTIMISM_R, 3),
            "total_r": round(float(net.sum()), 1)}


def report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ts = np.array([r["ts"] for r in rows], dtype=float)
    masks = periods(ts)
    out: Dict[str, Any] = {"all": summarize(rows)}
    for name, m in masks.items():
        out[name] = summarize([r for r, keep in zip(rows, m) if keep])
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "deep_history_lab", "bars_dir": str(BARS_DIR),
            "rollover_hours_excluded": list(ROLLOVER_BROKER_HOURS)}


def self_check() -> Dict[str, Any]:
    hour = np.array([5, 5, 0, 5])
    spread = np.array([0.0001] * 4)
    low = np.array([1.0990, 1.0985, 1.0900, 1.0995])     # the 1.0900 dip is in the rollover hour
    high = np.array([1.1010, 1.1005, 1.1100, 1.1002])
    close = np.array([1.1000, 1.1000, 1.1000, 1.1000])
    # a long stopped at 1.0950 must NOT be stopped by the rollover bar
    result, r = bracket_on_bid_bars(low, high, close, hour, spread, 1, 1.1000, 1.0950, 1.1100)
    assert result == "TIMEOUT", result
    # with the same dip in a normal hour it stops
    result2, _ = bracket_on_bid_bars(low, high, close, np.array([5, 5, 5, 5]), spread, 1, 1.1000, 1.0950, 1.1100)
    assert result2 == "STOP", result2
    p = periods(np.array([0.0, 1.0, 2.0, 3.0]))
    assert p["discovery"].sum() == 2 and p["validation"].sum() == 1 and p["holdout"].sum() == 1
    return {"ok": True}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("zones", "sweeps", "check"))
    ap.add_argument("--htf", default="H1")
    ap.add_argument("--ltf", default="M15")
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
    else:
        rows: List[Dict[str, Any]] = []
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            jobs = [(s, a.htf, a.ltf) for s in SYMBOLS] if a.cmd == "zones" else [(s, a.ltf) for s in SYMBOLS]
            for got in pool.starmap(zone_trades if a.cmd == "zones" else sweep_trades, jobs):
                rows += got
        rows = [r for r in rows if r["affordable"]]
        print(f"{a.htf} zones, {a.ltf} entries: {len(rows)} trades over "
              f"{len({r['symbol'] for r in rows})} symbols\n")
        for tr in (1.0, 2.0):
            sel = [r for r in rows if r["target_r"] == tr]
            rep = report(sel)
            print(f"  target {tr}R  " + " | ".join(
                f"{k}: n{v.get('n', 0)} won {v.get('won_pct')}% net {v.get('net_r')}" for k, v in rep.items()))
        path = REPORT_DIR / f"deep_history_{a.htf}_{a.ltf}.json"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows[:50000], default=str))
        print("\nwritten", path)
