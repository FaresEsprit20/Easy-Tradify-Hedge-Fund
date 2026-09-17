"""Gate 1e (strategic_plan_v4.md): tick-triggered entries at the moment of a sub-minute burst.

Gate 1d samples the market at M5 closes; information in ticks decays within seconds, so this gate enters when it
appears. Pre-registered 2026-09-17, before any result:
  data       MT5 raw ticks (quote changes only), 30 markets, 2026-05-26 -> 2026-09-16, read-only
  unit U     RMS of one-minute mid changes over the previous 60 minutes (minutes with quotes, >= 10 of them)
  trigger    |mid move over the last W seconds| >= k * U, W in {5, 15, 60}, k in {1.5, 2.5, 4};
             first tick where it holds; then no new trigger in that market (for that W, k) for 300 s
  direction  CONT (with the burst) or REV (against it)
  entry      first quote at or after trigger + 250 ms (retail latency); buy on ask, sell on bid
  exits      stop = target = b * U from the fill, b in {0.5, 1, 2}; time exit after H in {60, 300, 900} s;
             walked tick by tick on the exit side; a stop fills at the price of the crossing quote (gaps fill
             worse than the level), a target (limit) fills at its level; commission from symbol facts; R = b * U
  control    the same rule at random quote times (same count per market and day, same W for the sign)
  split      choose the best configuration on DISCOVERY (fills before 2026-07-20) among those with >= 300
             trades; score it once on HOLDOUT (from 2026-07-20)
  PASS       holdout >= 300 trades, win >= 65%, net >= +0.20R, t >= 2, and the random-time control fails

    python -m engine_v2.run.gate1e collect
    python -m engine_v2.run.gate1e analyse
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import warnings
import zlib
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "v4" / "gate1e"
START = int(datetime(2026, 5, 26, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp())
T_SPLIT_MS = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp()) * 1000
SYMBOLS = ("EURUSD GBPUSD USDJPY AUDUSD NZDUSD USDCAD USDCHF EURGBP EURJPY GBPJPY EURCAD AUDNZD AUDCAD AUDCHF GBPAUD "
           "XAUUSD XAGUSD US500 USTEC US30 US2000 DE40 STOXX50 F40 UK100 JP225 HK50 AUS200 XTIUSD XBRUSD").split()
WS, KS, BS, HS = (5, 15, 60), (1.5, 2.5, 4.0), (0.5, 1.0, 2.0), (60, 300, 900)
LATENCY_MS = 250
REFRACTORY_MS = 300_000
WORKERS = 5
TIMEOUT = 5400


def _read(mt5, sym, lo_s, hi_s):
    a = mt5.copy_ticks_range(sym, datetime.fromtimestamp(lo_s, tz=timezone.utc),
                             datetime.fromtimestamp(hi_s, tz=timezone.utc), mt5.COPY_TICKS_ALL)
    if a is None or len(a) < 2:
        return None
    tm, bid, ask = a["time_msc"].astype(np.int64), a["bid"].astype(float), a["ask"].astype(float)
    ok = (bid > 0) & (ask > bid)
    tm, bid, ask = tm[ok], bid[ok], ask[ok]
    if len(tm) < 100:
        return None
    keep = np.r_[True, (np.diff(bid) != 0) | (np.diff(ask) != 0)]
    return tm[keep], bid[keep], ask[keep]


def _unit_per_tick(tm, mid):
    """U known at each tick: RMS of one-minute mid changes over the 60 minutes before the tick's minute."""
    minute = tm // 60_000 - tm[0] // 60_000
    nmin = int(minute[-1]) + 1
    last_idx = np.searchsorted(minute, np.arange(nmin), side="right") - 1   # last tick at or before each minute
    have = np.r_[True, np.diff(last_idx) > 0]                                 # a quote arrived in that minute
    close = mid[last_idx]                                                     # mid at each minute's end
    d = np.r_[np.nan, np.diff(close)]
    active = have & np.isfinite(d)
    d2 = np.where(active, d * d, 0.0)
    c_d2, c_n = np.r_[0.0, np.cumsum(d2)], np.r_[0, np.cumsum(active)]
    lo = np.clip(np.arange(nmin) - 60, 0, None)
    s, n = c_d2[np.arange(nmin)] - c_d2[lo], c_n[np.arange(nmin)] - c_n[lo]   # minutes [m-60, m) : strictly before
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        U_min = np.where(n >= 10, np.sqrt(s / np.maximum(n, 1)), np.nan)
    return U_min[minute]


EXITS = list(product(("CONT", "REV"), BS, HS))


def _simulate_all(tm, bid, ask, fi, burst, u, comm_px):
    """Net R of every (direction, b, H) exit variant for one fill at quote index fi."""
    out = np.empty(len(EXITS), np.float32)
    ends = [int(np.searchsorted(tm, tm[fi] + H * 1000, side="right")) for H in HS]
    k = 0
    for direction in ("CONT", "REV"):
        d = burst if direction == "CONT" else -burst
        fill = ask[fi] if d > 0 else bid[fi]
        rel = ((bid if d > 0 else ask)[fi + 1:ends[-1]] - fill) * d
        for b in BS:
            b_px = b * u
            hit = (rel <= -b_px) | (rel >= b_px)
            first = int(np.argmax(hit)) if hit.any() else len(rel)
            for eH in ends:
                n_h = eH - (fi + 1)
                if first < n_h:
                    g = b_px if rel[first] >= b_px else rel[first]
                elif n_h > 0:
                    g = rel[n_h - 1]
                else:
                    g = 0.0
                out[k] = (g - comm_px) / b_px
                k += 1
    return out


def symbol_events(sym: str):
    """All trades for every configuration (and its random-time control) in one market."""
    import MetaTrader5 as mt5
    from engine_v2.data.symbols import facts
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    fx = facts(sym)
    comm_px = fx.commission_usd_per_lot_round_trip / fx.usd_per_price_unit_per_lot
    rng = np.random.default_rng(zlib.crc32(sym.encode()))
    cid_of = {c: i for i, c in enumerate(product(WS, KS, ("CONT", "REV"), BS, HS))}
    chunks = []
    for day in range(START // 86400, END // 86400):
        rd = _read(mt5, sym, day * 86400 - 3700, (day + 1) * 86400 + 1000)
        if rd is None:
            continue
        tm, bid, ask = rd
        mid = (bid + ask) / 2
        U = _unit_per_tick(tm, mid)
        in_day = (tm >= day * 86400 * 1000) & (tm < (day + 1) * 86400 * 1000)
        for W in WS:
            j = np.searchsorted(tm, tm - W * 1000, side="left") - 1
            mv = np.where(j >= 0, mid - mid[np.clip(j, 0, None)], np.nan)
            ok = in_day & np.isfinite(U) & (U > 0) & np.isfinite(mv)
            rand_pool = np.flatnonzero(ok & (mv != 0))
            for kk in KS:
                cand = np.flatnonzero(ok & (np.abs(mv) >= kk * U))
                trig, last = [], -10 ** 15
                for i in cand:
                    if tm[i] - last >= REFRACTORY_MS:
                        trig.append(i)
                        last = tm[i]
                if not trig or len(rand_pool) == 0:
                    continue
                trig = np.array(trig)
                ctrl = np.sort(rng.choice(rand_pool, size=len(trig), replace=len(rand_pool) < len(trig)))
                cids = np.array([cid_of[(W, kk) + e] for e in EXITS], np.int16)
                for is_ctrl, idx in ((0, trig), (1, ctrl)):
                    fills = np.searchsorted(tm, tm[idx] + LATENCY_MS, side="left")
                    for i, fi in zip(idx, fills):
                        if fi >= len(tm) or tm[fi] - tm[i] > 60_000:
                            continue
                        nets = _simulate_all(tm, bid, ask, int(fi), 1 if mv[i] > 0 else -1, float(U[i]), comm_px)
                        ch = np.empty(len(EXITS), dtype=[("cid", np.int16), ("ctrl", np.int8), ("t", np.int64), ("net", np.float32)])
                        ch["cid"], ch["ctrl"], ch["t"], ch["net"] = cids, is_ctrl, tm[fi], nets
                        chunks.append(ch)
    mt5.shutdown()
    if not chunks:
        return np.empty(0, dtype=[("cid", np.int16), ("ctrl", np.int8), ("t", np.int64), ("net", np.float32)])
    return np.concatenate(chunks)


def one(sym: str):
    t0 = time.time()
    ev = symbol_events(sym)
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    np.save(OUT / "parts" / f"{sym}.npy", ev)
    print(sym, "trades", len(ev), f"{time.time() - t0:.0f}s", flush=True)


def collect():
    parts = OUT / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [s for s in SYMBOLS if not (parts / f"{s}.npy").exists()]
    running = {}
    while todo or running:
        while todo and len(running) < WORKERS:
            s = todo.pop(0)
            running[s] = (subprocess.Popen([sys.executable, "-W", "ignore", "-m", "engine_v2.run.gate1e", "one", s],
                                           cwd=ROOT), time.time())
        for s, (p, t0) in list(running.items()):
            if p.poll() is not None:
                print(s, "exit", p.returncode, f"{time.time() - t0:.0f}s", flush=True)
                del running[s]
            elif time.time() - t0 > TIMEOUT:
                p.kill()
                print(s, "TIMEOUT", flush=True)
                del running[s]
        time.sleep(2)


def _stats(net):
    if len(net) < 2:
        return {"n": int(len(net))}
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if net.std() > 0 else 0.0
    return {"n": int(len(net)), "win": round(float((net > 0).mean()), 3), "net": round(float(net.mean()), 3),
            "t": round(t, 1)}


def analyse():
    from engine_v2.run.gate1b import _cls
    configs = list(product(WS, KS, ("CONT", "REV"), BS, HS))
    evs = []
    for s in SYMBOLS:
        f = OUT / "parts" / f"{s}.npy"
        if f.exists():
            e = np.load(f)
            evs.append((s, e))
    table = []
    for cid, cfg in enumerate(configs):
        disc, hold, dctl, hctl = [], [], [], []
        by_cls = {c: [] for c in range(4)}
        for s, e in evs:
            m = e["cid"] == cid
            for ctrl, dst_d, dst_h in ((0, disc, hold), (1, dctl, hctl)):
                mm = m & (e["ctrl"] == ctrl)
                dst_d.append(e["net"][mm & (e["t"] < T_SPLIT_MS)])
                dst_h.append(e["net"][mm & (e["t"] >= T_SPLIT_MS)])
            by_cls[_cls(s)].append(e["net"][m & (e["ctrl"] == 0) & (e["t"] >= T_SPLIT_MS)])
        cat = lambda v: np.concatenate(v).astype(float) if v else np.array([])
        row = {"cfg": dict(zip(("W", "k", "dir", "b", "H"), cfg)), "discovery": _stats(cat(disc)),
               "discovery_control": _stats(cat(dctl)), "holdout": _stats(cat(hold)),
               "holdout_control": _stats(cat(hctl)),
               "holdout_by_class": {nm: _stats(cat(by_cls[c])) for c, nm in {0: "FX", 1: "metals", 2: "oil", 3: "indices"}.items()}}
        table.append(row)
    eligible = [r for r in table if r["discovery"].get("n", 0) >= 300]
    best = max(eligible, key=lambda r: (r["discovery"]["net"], r["discovery"]["win"]))
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    verdict = {"chosen_on_discovery": best, "PASS": bool(okf(best["holdout"]) and not okf(best["holdout_control"]))}
    top = sorted(eligible, key=lambda r: -r["discovery"]["net"])[:10]
    both = [r for r in table if r["discovery"].get("n", 0) >= 300 and r["discovery"]["net"] > 0 and r["holdout"].get("n", 0) >= 300 and r["holdout"]["net"] > 0]
    hi_win = sorted(eligible, key=lambda r: -r["discovery"]["win"])[:5]
    (OUT / "analysis.json").write_text(json.dumps({"verdict": verdict, "top10_discovery": top,
                                                   "positive_in_both": both, "highest_win_discovery": hi_win,
                                                   "all": table}, indent=1))
    print("CHOSEN", json.dumps(best["cfg"]), "disc", best["discovery"], "hold", best["holdout"], "hold_ctrl",
          best["holdout_control"], "PASS", verdict["PASS"])
    for r in top:
        print(" top", r["cfg"], "disc", r["discovery"], "ctrl", r["discovery_control"], "hold", r["holdout"])
    print("configs positive in discovery AND holdout:", len(both))
    for r in hi_win:
        print(" hi-win", r["cfg"], "disc", r["discovery"], "hold", r["holdout"])


if __name__ == "__main__":
    if sys.argv[1] == "one":
        one(sys.argv[2])
    else:
        {"collect": collect, "analyse": analyse}[sys.argv[1]]()
