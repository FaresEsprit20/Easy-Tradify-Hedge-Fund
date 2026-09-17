# ai/structure_lab.py
"""
Structure lab: supply/demand, order blocks and market structure rebuilt with
full definitions and traded the way the concept trades them, on tick quotes.

Why a lab and not the engine's fields: the engine's supply/demand component
publishes ONE price (`zone_level`) -- no proximal/distal edge, no departure
leg, no invalidation -- so a zone trade (limit at the proximal edge, stop
beyond the distal edge, valid until first touch) cannot be measured from it.
Every concept here is built from mid-price bars (tick bid/ask average, so a
rollover spread spike is not a "wick"), each variant is simulated on bid/ask
quote bars, and only variants that hold on validation AND holdout become the
upgraded components.

Definitions (timeframe TF in M15 / H1, ATR = ATR(14) of TF):
  swing            fractal high/low with SWING_N bars each side, known SWING_N
                   bars after it forms
  BOS              a TF close beyond the last confirmed swing high (up) or low
                   (down); CHoCH when it is against the previous BOS
  zone             for a BOS up: the leg's origin is the lowest low between
                   the swing low before the broken high and the BOS bar; the
                   zone is the last down-close candle at/just before the origin
                   (its full range). Mirrored for a BOS down.
  departure        (leg extreme - zone proximal edge) / ATR
  sweep origin     the origin took out the previous swing low (high) and closed
                   back inside -- liquidity grabbed before the move
  HTF aligned      H4 structure (last BOS on H4) points the zone's way

Trade (first touch only): limit at the proximal edge (BUY fills when the ask
reaches it, SELL when the bid does), stop BUFFER x ATR beyond the distal edge,
target R x risk; stop checked from the fill minute (stop first when a minute
holds both), exits on the correct side of the book, 48h max, zone order
cancelled after EXPIRY_MINUTES or if price closes beyond the distal edge first.
Commission = $7.03 per lot at a lot sized to the dollar risk.

    python -m ai.structure_lab run
    python -m ai.structure_lab report
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
OUT_DIR = Path(os.getenv("STRUCTURE_LAB_DIR") or ROOT / "reports" / "cache" / "structure_lab")
REPORT_DIR = ROOT / "reports"

TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
SWING_N = 2
ATR_N = 14
OB_LOOKBACK = 3
EXPIRY_MINUTES = 3 * 1440
HOLD_MINUTES = 2 * 1440
BUFFERS = (0.1, 0.5)
TARGETS_R = (1.0, 2.0)
COMMISSION_PER_LOT = 7.03
RISK_USD = 4.0


# ============================================================
# BARS
# ============================================================

def load_quotes(symbol: str) -> Optional[Dict[str, np.ndarray]]:
    path = QUOTE_DIR / f"{symbol}.npz"
    if not path.exists():
        return None
    with np.load(path) as z:
        q = {k: z[k] for k in z.files}
    q["mid_open"] = np.r_[q["mid_close"][0], q["mid_close"][:-1]]
    return q


def resample(q: Mapping[str, np.ndarray], tf: str) -> Dict[str, np.ndarray]:
    """Mid OHLC bars of `tf`; `end` is the index of the first M1 bar after the TF bar."""
    sec = TF_SECONDS[tf]
    key = q["time"] // sec
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], key.size]
    return {"time": key[starts] * sec, "open": q["mid_open"][starts],
            "high": np.maximum.reduceat(q["mid_high"], starts), "low": np.minimum.reduceat(q["mid_low"], starts),
            "close": q["mid_close"][ends - 1], "end": ends, "sec": sec}


def atr(b: Mapping[str, np.ndarray], n: int = ATR_N) -> np.ndarray:
    h, l, c = b["high"], b["low"], b["close"]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.full(tr.size, np.nan)
    if tr.size > n:
        cs = np.cumsum(tr)
        out[n:] = (cs[n:] - cs[:-n]) / n
    return out


def swings(b: Mapping[str, np.ndarray], n: int = SWING_N):
    h, l = b["high"], b["low"]
    size = h.size
    sh = np.zeros(size, bool)
    sl = np.zeros(size, bool)
    for i in range(n, size - n):
        wh = h[i - n:i + n + 1]
        wl = l[i - n:i + n + 1]
        sh[i] = h[i] == wh.max() and (wh == h[i]).sum() == 1
        sl[i] = l[i] == wl.min() and (wl == l[i]).sum() == 1
    return sh, sl


def structure(b: Mapping[str, np.ndarray], n: int = SWING_N) -> List[Dict[str, Any]]:
    """BOS / CHoCH events in bar order, each with the swings it came from."""
    sh, sl = swings(b, n)
    h, l, c = b["high"], b["low"], b["close"]
    events = []
    last_high = last_low = None          # (index, price) of the latest CONFIRMED swing
    prev_low_before_high = None
    broken_high = broken_low = -1
    trend = 0
    for i in range(c.size):
        j = i - n                         # a swing at j is confirmed at bar i
        if j >= 0 and sh[j]:
            prev_low_before_high = last_low
            last_high = (j, h[j])
        if j >= 0 and sl[j]:
            last_low = (j, l[j])
        if last_high and last_high[0] != broken_high and c[i] > last_high[1]:
            origin_from = last_low[0] if last_low and last_low[0] < i else max(0, last_high[0] - 10)
            events.append({"i": i, "dir": 1, "choch": trend == -1, "broken": last_high[1],
                           "origin_from": origin_from, "sweep_ref": prev_low_before_high})
            broken_high = last_high[0]
            trend = 1
        if last_low and last_low[0] != broken_low and c[i] < last_low[1]:
            origin_from = last_high[0] if last_high and last_high[0] < i else max(0, last_low[0] - 10)
            events.append({"i": i, "dir": -1, "choch": trend == 1, "broken": last_low[1],
                           "origin_from": origin_from, "sweep_ref": None})
            broken_low = last_low[0]
            trend = -1
    return events


def trend_at(events: List[Dict[str, Any]], bars: Mapping[str, np.ndarray], t: int) -> int:
    """Direction of the last BOS whose bar CLOSED at or before broker time t."""
    d = 0
    for e in events:
        if bars["time"][e["i"]] + bars["sec"] <= t:
            d = e["dir"]
        else:
            break
    return d


# ============================================================
# ZONES
# ============================================================

def zones(b: Mapping[str, np.ndarray], events: List[Dict[str, Any]], a: np.ndarray) -> List[Dict[str, Any]]:
    o, h, l, c = b["open"], b["high"], b["low"], b["close"]
    out = []
    for e in events:
        i, d = e["i"], e["dir"]
        lo, hi = e["origin_from"], i
        if hi - lo < 1 or not np.isfinite(a[i]) or a[i] <= 0:
            continue
        seg = slice(lo, hi + 1)
        origin = lo + int(np.argmin(l[seg]) if d > 0 else np.argmax(h[seg]))
        ob = origin
        for k in range(origin, max(lo, origin - OB_LOOKBACK) - 1, -1):
            if (c[k] < o[k]) if d > 0 else (c[k] > o[k]):
                ob = k
                break
        z_lo, z_hi = l[ob], h[ob]
        proximal, distal = (z_hi, z_lo) if d > 0 else (z_lo, z_hi)
        leg_extreme = h[origin:i + 1].max() if d > 0 else l[origin:i + 1].min()
        departure = d * (leg_extreme - proximal) / a[i]
        # liquidity taken at the origin: it broke the swing before it and closed back
        prior = l[max(0, origin - 30):origin] if d > 0 else h[max(0, origin - 30):origin]
        swept = bool(prior.size and ((l[origin] < prior.min() and c[origin] > prior.min()) if d > 0
                                     else (h[origin] > prior.max() and c[origin] < prior.max())))
        out.append({"bos_i": i, "dir": d, "choch": bool(e["choch"]), "proximal": float(proximal),
                    "distal": float(distal), "width_atr": float((z_hi - z_lo) / a[i]), "departure_atr": float(departure),
                    "swept_origin": swept, "legs_bars": int(i - origin), "atr": float(a[i]),
                    "created": int(b["time"][i] + b["sec"]), "start_m1": int(b["end"][i])})
    return out


def simulate(q: Mapping[str, np.ndarray], z: Mapping[str, Any], buffer: float, target_r: float,
             usd_per_price_per_lot: float) -> Dict[str, Any]:
    """First-touch limit order on the zone, filled and exited on quotes."""
    d, s = z["dir"], z["start_m1"]
    end = min(q["time"].size, s + EXPIRY_MINUTES)
    if s >= end:
        return {"filled": False}
    limit, distal = z["proximal"], z["distal"]
    if d > 0:
        touch = q["ask_low"][s:end] <= limit
        broke = q["mid_close"][s:end] < distal
    else:
        touch = q["bid_high"][s:end] >= limit
        broke = q["mid_close"][s:end] > distal
    ti = int(np.argmax(touch)) if touch.any() else None
    bi = int(np.argmax(broke)) if broke.any() else None
    if ti is None or (bi is not None and bi < ti):
        return {"filled": False}
    f = s + ti
    # a gap through the limit fills at the better open
    entry = min(limit, float(q["ask_open"][f])) if d > 0 else max(limit, float(q["bid_open"][f]))
    stop = distal - d * buffer * z["atr"]
    risk = d * (entry - stop)
    if risk <= 0:
        return {"filled": False}
    target = entry + d * target_r * risk
    e2 = min(q["time"].size, f + HOLD_MINUTES)
    if d > 0:
        hit_s = q["bid_low"][f:e2] <= stop
        hit_t = q["bid_high"][f:e2] >= target
        last = float(q["bid_close"][e2 - 1])
    else:
        hit_s = q["ask_high"][f:e2] >= stop
        hit_t = q["ask_low"][f:e2] <= target
        last = float(q["ask_close"][e2 - 1])
    hit_t[0] = False                      # order inside the fill minute is unknowable: stop only
    i_s = int(np.argmax(hit_s)) if hit_s.any() else None
    i_t = int(np.argmax(hit_t)) if hit_t.any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        result, r = "STOP", -1.0
    elif i_t is not None:
        result, r = "TARGET", target_r
    else:
        result, r = "TIMEOUT", d * (last - entry) / risk
    risk_per_lot = risk * usd_per_price_per_lot
    return {"filled": True, "fill_ts": int(q["time"][f]), "result": result, "r": round(r, 4),
            "commission_r": round(COMMISSION_PER_LOT / risk_per_lot, 4) if risk_per_lot > 0 else None,
            "affordable": bool(0.01 * risk_per_lot <= RISK_USD * 1.1), "risk_atr": round(risk / z["atr"], 3),
            "wait_minutes": int(ti)}


# ============================================================
# RUN
# ============================================================

def run_symbol(symbol: str) -> Dict[str, Any]:
    from ai.price_history_study import usd_per_price_unit_per_lot

    q = load_quotes(symbol)
    usd = usd_per_price_unit_per_lot(symbol)
    if q is None or not usd:
        return {"symbol": symbol, "error": "no quotes or specs"}
    h4 = resample(q, "H4")
    h4_events = structure(h4)
    rows = []
    for tf in ("M15", "H1"):
        b = resample(q, tf)
        a = atr(b)
        ev = structure(b)
        for z in zones(b, ev, a):
            z["htf_trend"] = trend_at(h4_events, h4, z["created"])
            base = {"symbol": symbol, "tf": tf, **{k: v for k, v in z.items() if k not in ("start_m1",)}}
            for buf in BUFFERS:
                for tr in TARGETS_R:
                    sim = simulate(q, z, buf, tr, usd)
                    if sim.get("filled"):
                        rows.append({**base, "buffer": buf, "target_r": tr, **sim})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{symbol}.json").write_text(json.dumps(rows))
    return {"symbol": symbol, "trades": len(rows)}


# ============================================================
# HIGHER-TIMEFRAME ZONE, LOWER-TIMEFRAME ENTRY
# ============================================================
# The first-touch limit trade loses on every period (42-46% at 1R), and no SMC
# confirmation rescued it. This is the other way traders actually take a zone:
# the HIGHER timeframe says WHERE (an H4 or D1 zone is a location, not a
# signal), and the LOWER timeframe says WHEN -- price must return to the zone
# AND print a structure break in the zone's direction before anything is
# risked. Nothing is traded on the touch itself.
#
#   location    zone from an H4 / D1 break of structure (zones())
#   trigger     price trades into the zone (mid, so a spread spike is not a touch)
#   entry       the first M15 / M5 break of structure in the zone's direction
#               within CONFIRM_BARS bars of that touch -- market, next minute
#   stop        "structure": under the swing the confirmation came from
#               "zone": beyond the zone's far edge
#   target      R multiples of whichever stop is used
# ============================================================

CONFIRM_BARS = 12


def htf_trades(symbol: str, htf: str = "H4", ltf: str = "M15", stop_kinds=("structure", "zone"),
               targets=TARGETS_R, buffer_atr: float = 0.25) -> List[Dict[str, Any]]:
    from ai.price_history_study import quote_bracket, usd_per_price_unit_per_lot

    q = load_quotes(symbol)
    usd = usd_per_price_unit_per_lot(symbol)
    if q is None or not usd:
        return []
    hb = resample(q, htf)
    ha = atr(hb)
    hev = structure(hb)
    zs = zones(hb, hev, ha)
    lb = resample(q, ltf)
    la = atr(lb)
    lev = structure(lb)
    lsec = TF_SECONDS[ltf]
    # LTF breaks of structure, as (minute index the bar closed, direction)
    breaks = [(int(lb["end"][e["i"]]), e["dir"], e["i"]) for e in lev]
    b_idx = np.array([b[0] for b in breaks], dtype=np.int64)
    d1 = resample(q, "D1")
    d1_ev = structure(d1)
    rows: List[Dict[str, Any]] = []
    for z in zs:
        d, s = z["dir"], z["start_m1"]
        end = min(q["time"].size, s + EXPIRY_MINUTES)
        if s >= end:
            continue
        # price must trade INTO the zone -- measured on the mid
        into = (q["mid_low"][s:end] <= z["proximal"]) if d > 0 else (q["mid_high"][s:end] >= z["proximal"])
        gone = (q["mid_close"][s:end] < z["distal"]) if d > 0 else (q["mid_close"][s:end] > z["distal"])
        ti = int(np.argmax(into)) if into.any() else None
        gi = int(np.argmax(gone)) if gone.any() else None
        if ti is None or (gi is not None and gi < ti):
            continue
        touch = s + ti
        # the first LTF structure break the zone's way, within CONFIRM_BARS
        window = (b_idx > touch) & (b_idx <= touch + CONFIRM_BARS * lsec // 60)
        confirmed = [breaks[i] for i in np.flatnonzero(window) if breaks[i][1] == d]
        if not confirmed:
            continue
        k, _, li = confirmed[0]
        if k >= q["time"].size - 30:
            continue
        entry = float(q["ask_open"][k] if d > 0 else q["bid_open"][k])
        latr = la[li] if li < la.size and np.isfinite(la[li]) else z["atr"]
        for kind in stop_kinds:
            if kind == "zone":
                stop = z["distal"] - d * buffer_atr * z["atr"]
            else:
                seg = slice(max(0, touch - 1), k)
                extreme = float(q["mid_low"][seg].min()) if d > 0 else float(q["mid_high"][seg].max())
                stop = extreme - d * buffer_atr * latr
            risk = d * (entry - stop)
            if risk <= 0:
                continue
            rpl = risk * usd
            for tr in targets:
                br = quote_bracket(q, k, HOLD_MINUTES, risk, tr * risk, d)
                if not br:
                    continue
                rows.append({"symbol": symbol, "htf": htf, "ltf": ltf, "stop_kind": kind, "target_r": tr,
                             "dir": d, "choch": z["choch"], "departure_atr": z["departure_atr"],
                             "swept_origin": z["swept_origin"], "width_atr": z["width_atr"],
                             "htf_trend": trend_at(hev, hb, int(q["time"][k])), "d1_trend": trend_at(d1_ev, d1, int(q["time"][k])),
                             "fill_ts": int(q["time"][k]), "wait_minutes": int(touch - s),
                             "confirm_minutes": int(k - touch), "risk_atr": round(risk / z["atr"], 3),
                             "result": br["result"], "r": br["r"],
                             "commission_r": round(COMMISSION_PER_LOT / rpl, 4) if rpl > 0 else None,
                             "affordable": bool(0.01 * rpl <= RISK_USD * 1.1)})
    return rows


def _htf_worker(args) -> Dict[str, Any]:
    symbol, htf, ltf = args
    rows = htf_trades(symbol, htf, ltf)
    out = OUT_DIR / f"htf_{htf}_{ltf}"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{symbol}.json").write_text(json.dumps(rows))
    return {"symbol": symbol, "htf": htf, "ltf": ltf, "trades": len(rows)}


def boundaries() -> Dict[str, float]:
    """The study's discovery / validation / holdout calendar."""
    from ai.component_repair import Columns, HOLDOUT_FRACTION

    ts = Columns().num("ts").astype(np.float64)
    start = float(np.nanquantile(ts, 1 - HOLDOUT_FRACTION))
    cut = float(np.nanmedian(ts[ts < start - 86400]))
    return {"validation_start": cut + 43200, "discovery_end": cut - 43200, "holdout_start": start}


def load_rows() -> List[Dict[str, Any]]:
    rows = []
    for f in sorted(OUT_DIR.glob("*.json")):
        rows.extend(json.loads(f.read_text()))
    return rows


def period_of(ts: float, bnd: Mapping[str, float]) -> Optional[str]:
    if ts >= bnd["holdout_start"]:
        return "holdout"
    if ts >= bnd["validation_start"] and ts < bnd["holdout_start"] - 86400:
        return "validation"
    if ts < bnd["discovery_end"]:
        return "discovery"
    return None


def summarize(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"n": 0}
    net = np.array([r["r"] - (r["commission_r"] or 0) for r in rows])
    win = np.array([r["result"] == "TARGET" for r in rows])
    return {"n": len(rows), "win": round(100 * win.mean(), 1), "net_r": round(float(net.mean()), 3),
            "total_r": round(float(net.sum()), 1)}


def self_check() -> Dict[str, Any]:
    # a rising series with one pullback: a BOS up and a demand zone at the pullback
    closes = np.array([10, 11, 12, 11, 10, 9, 10, 11, 12, 13, 14, 15, 16], float)
    b = {"time": np.arange(closes.size) * 900, "open": np.r_[closes[0], closes[:-1]], "close": closes,
         "high": closes + 0.2, "low": closes - 0.2, "end": np.arange(1, closes.size + 1), "sec": 900}
    ev = structure(b, n=2)
    assert any(e["dir"] == 1 for e in ev), ev
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "structure_lab", "timeframes": ["M15", "H1"], "buffers": list(BUFFERS),
            "targets_r": list(TARGETS_R)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "htf", "check"))
    ap.add_argument("--htf", default="H4")
    ap.add_argument("--ltf", default="M15")
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
    elif a.cmd == "htf":
        from ai.price_history_study import SYMBOLS
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            for res in pool.imap_unordered(_htf_worker, [(s, a.htf, a.ltf) for s in SYMBOLS]):
                print(res, flush=True)
    else:
        from ai.price_history_study import SYMBOLS
        with Pool(min(len(SYMBOLS), os.cpu_count() or 4)) as pool:
            for res in pool.imap_unordered(run_symbol, SYMBOLS):
                print(res, flush=True)
