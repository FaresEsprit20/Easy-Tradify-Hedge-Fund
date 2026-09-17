"""Gate 1f (strategic_plan_v4.md): cross-market lag, traded at the moment it opens.

Pre-registered 2026-09-17, before any result:
  data       MT5 raw ticks (quote changes only), 2026-05-26 -> 2026-09-16, read-only
  pairs      correlated: the follower trades in the leader's direction (US indices among themselves, European
             indices among themselves, US500/HK50 for JP225, US500/JP225 for AUS200, gold/silver, WTI/Brent,
             EURUSD/GBPUSD, AUDUSD/NZDUSD, EURUSD inverted for USDCHF);
             triangles: a cross against the move implied by its two legs (EURJPY, GBPJPY, EURGBP, EURCAD, AUDNZD,
             AUDCAD, AUDCHF, GBPAUD; USDJPY against EURJPY/EURUSD)
  unit U     per market: RMS of one-minute mid changes over the previous 60 minutes (>= 10 minutes with quotes)
  signal     on every quote time of the markets involved, moves over the last W seconds in each market's U:
               correlated  leader burst |L| >= k and unfollowed part |L| - s*sign(L)*F >= k/2; side s*sign(L)
               triangle    implied cross move from its legs (log moves) minus the cross's own move: |gap| >= k;
                           side sign(gap)
             W in {5, 15, 60} s, k in {1.5, 2.5, 4}; every market involved must have quoted within 60 s;
             then no new signal for that follower, pair, W and k for 300 s
  entry      follower's first quote at or after signal + 250 ms; buy on ask, sell on bid
  exits      stop = target = b * U(follower), b in {0.5, 1, 2}; time exit after H in {30, 60, 300} s; a stop fills
             at the crossing quote, a target at its level; commission from symbol facts
  control    random quote times (same count per follower, pair and day); side = sign of the same gap there
  split/PASS as Gate 1e: best configuration on DISCOVERY (fills before 2026-07-20, >= 300 trades) scored once
             on HOLDOUT; PASS = holdout >= 300 trades, win >= 65%, net >= +0.20R, t >= 2, control fails.
             Also reported: the best configuration chosen on discovery within each kind (correlated, triangle).

    python -m engine_v2.run.gate1f collect
    python -m engine_v2.run.gate1f analyse
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
OUT = ROOT / "reports" / "v4" / "gate1f"
START = int(datetime(2026, 5, 26, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp())
T_SPLIT_MS = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp()) * 1000
SPECS = {
    "US500": [("corr", "USTEC", 1), ("corr", "US30", 1), ("corr", "US2000", 1)],
    "USTEC": [("corr", "US500", 1), ("corr", "US30", 1)],
    "US30": [("corr", "US500", 1), ("corr", "USTEC", 1)],
    "US2000": [("corr", "US500", 1), ("corr", "USTEC", 1)],
    "DE40": [("corr", "STOXX50", 1), ("corr", "F40", 1), ("corr", "UK100", 1)],
    "STOXX50": [("corr", "DE40", 1), ("corr", "F40", 1)],
    "F40": [("corr", "DE40", 1), ("corr", "STOXX50", 1)],
    "UK100": [("corr", "DE40", 1), ("corr", "STOXX50", 1)],
    "JP225": [("corr", "US500", 1), ("corr", "HK50", 1)],
    "HK50": [("corr", "JP225", 1)],
    "AUS200": [("corr", "US500", 1), ("corr", "JP225", 1)],
    "XAUUSD": [("corr", "XAGUSD", 1)], "XAGUSD": [("corr", "XAUUSD", 1)],
    "XTIUSD": [("corr", "XBRUSD", 1)], "XBRUSD": [("corr", "XTIUSD", 1)],
    "EURUSD": [("corr", "GBPUSD", 1)], "GBPUSD": [("corr", "EURUSD", 1)],
    "AUDUSD": [("corr", "NZDUSD", 1)], "NZDUSD": [("corr", "AUDUSD", 1)],
    "USDCHF": [("corr", "EURUSD", -1)],
    "EURJPY": [("tri", "EURUSD", 1, "USDJPY", 1)], "GBPJPY": [("tri", "GBPUSD", 1, "USDJPY", 1)],
    "EURGBP": [("tri", "EURUSD", 1, "GBPUSD", -1)], "EURCAD": [("tri", "EURUSD", 1, "USDCAD", 1)],
    "AUDNZD": [("tri", "AUDUSD", 1, "NZDUSD", -1)], "AUDCAD": [("tri", "AUDUSD", 1, "USDCAD", 1)],
    "AUDCHF": [("tri", "AUDUSD", 1, "USDCHF", 1)], "GBPAUD": [("tri", "GBPUSD", 1, "AUDUSD", -1)],
    "USDJPY": [("tri", "EURJPY", 1, "EURUSD", -1)],
}
WS, KS, BS, HS = (5, 15, 60), (1.5, 2.5, 4.0), (0.5, 1.0, 2.0), (30, 60, 300)
CONFIGS = list(product(WS, KS, BS, HS))
LATENCY_MS = 250
REFRACTORY_MS = 300_000
FRESH_MS = 60_000
WORKERS = 5
TIMEOUT = 5400
ROW = [("cid", np.int16), ("ctrl", np.int8), ("kind", np.int8), ("t", np.int64), ("net", np.float32)]


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


class _Market:
    def __init__(self, tm, bid, ask):
        self.tm, self.bid, self.ask = tm, bid, ask
        self.mid = (bid + ask) / 2
        self.m0 = tm[0] // 60_000
        minute = tm // 60_000 - self.m0
        nmin = int(minute[-1]) + 1
        last_idx = np.searchsorted(minute, np.arange(nmin), side="right") - 1
        have = np.r_[True, np.diff(last_idx) > 0]
        d = np.r_[np.nan, np.diff(self.mid[last_idx])]
        active = have & np.isfinite(d)
        c_d2 = np.r_[0.0, np.cumsum(np.where(active, d * d, 0.0))]
        c_n = np.r_[0, np.cumsum(active)]
        m = np.arange(nmin)
        lo = np.clip(m - 60, 0, None)
        s, n = c_d2[m] - c_d2[lo], c_n[m] - c_n[lo]                         # minutes [m-60, m)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.U_min = np.where(n >= 10, np.sqrt(s / np.maximum(n, 1)), np.nan)

    def mid_at(self, t):
        """Mid of the last quote at or before t, and whether that quote is fresh (within FRESH_MS)."""
        i = np.searchsorted(self.tm, t, side="right") - 1
        ok = i >= 0
        ic = np.clip(i, 0, None)
        return np.where(ok, self.mid[ic], np.nan), ok & (t - self.tm[ic] <= FRESH_MS)

    def unit_at(self, t):
        k = t // 60_000 - self.m0
        inside = (k >= 0) & (k < len(self.U_min))
        return np.where(inside, self.U_min[np.clip(k, 0, len(self.U_min) - 1)], np.nan)


def _trades(f: _Market, t_sig, side, u, comm_px):
    """Net R for every (b, H) exit of each signal. Returns (fill times, nets[n, len(BS)*len(HS)])."""
    fills = np.searchsorted(f.tm, t_sig + LATENCY_MS, side="left")
    keep_t, keep_n = [], []
    for ts, fi, d, uu in zip(t_sig, fills, side, u):
        if fi >= len(f.tm) or f.tm[fi] - ts > FRESH_MS or d == 0 or not (uu > 0):
            continue
        ends = [int(np.searchsorted(f.tm, f.tm[fi] + H * 1000, side="right")) for H in HS]
        fill = f.ask[fi] if d > 0 else f.bid[fi]
        rel = ((f.bid if d > 0 else f.ask)[fi + 1:ends[-1]] - fill) * d
        out = []
        for b in BS:
            b_px = b * uu
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
                out.append((g - comm_px) / b_px)
        keep_t.append(f.tm[fi])
        keep_n.append(out)
    return np.array(keep_t, np.int64), np.array(keep_n, np.float32).reshape(-1, len(BS) * len(HS))


def _refractory(times):
    picked, pos = [], 0
    while pos < len(times):
        picked.append(pos)
        pos = int(np.searchsorted(times, times[pos] + REFRACTORY_MS, side="left"))
    return np.array(picked, int)


def follower_events(fol: str):
    import MetaTrader5 as mt5
    from engine_v2.data.symbols import facts
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    fx = facts(fol)
    comm_px = fx.commission_usd_per_lot_round_trip / fx.usd_per_price_unit_per_lot
    rng = np.random.default_rng(zlib.crc32(fol.encode()))
    specs = SPECS[fol]
    names = sorted({fol} | {x for sp in specs for x in sp[1:] if isinstance(x, str)})
    chunks = []
    for day in range(START // 86400, END // 86400):
        mk = {}
        for m in names:
            rd = _read(mt5, m, day * 86400 - 3700, (day + 1) * 86400 + 400)
            if rd is not None:
                mk[m] = _Market(*rd)
        if fol not in mk:
            continue
        f = mk[fol]
        day_lo, day_hi = day * 86_400_000, (day + 1) * 86_400_000
        for sp in specs:
            legs = [x for x in sp[1:] if isinstance(x, str)]
            if any(l not in mk for l in legs):
                continue
            grid = np.unique(np.concatenate([f.tm] + [mk[l].tm for l in legs]))
            grid = grid[(grid >= day_lo) & (grid < day_hi)]
            if len(grid) < 100:
                continue
            fm_now, f_fresh = f.mid_at(grid)
            uf = f.unit_at(grid)
            fresh = f_fresh & (uf > 0)
            now = {}
            for l in legs:
                now[l], fr = mk[l].mid_at(grid)
                fresh &= fr
            kind = 0 if sp[0] == "corr" else 1
            for W in WS:
                fm_then, _ = f.mid_at(grid - W * 1000)
                F = (fm_now - fm_then) / uf
                if sp[0] == "corr":
                    _, leader, s = sp
                    ul = mk[leader].unit_at(grid)
                    lm_then, _ = mk[leader].mid_at(grid - W * 1000)
                    L = (now[leader] - lm_then) / ul
                    valid = fresh & np.isfinite(F) & np.isfinite(L) & (ul > 0)
                    unfollowed = np.abs(L) - s * np.sign(L) * F
                    side_sig = (s * np.sign(L)).astype(int)
                    side_ctrl = np.sign(s * L - F).astype(int)
                    cond = lambda k: valid & (np.abs(L) >= k) & (unfollowed >= k / 2)
                else:
                    _, l1, s1, l2, s2 = sp
                    t1, _ = mk[l1].mid_at(grid - W * 1000)
                    t2, _ = mk[l2].mid_at(grid - W * 1000)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        implied = (s1 * np.log(now[l1] / t1) + s2 * np.log(now[l2] / t2)) * fm_now / uf
                    gap = implied - F
                    valid = fresh & np.isfinite(gap)
                    side_sig = np.sign(gap).astype(int)
                    side_ctrl = side_sig
                    cond = lambda k: valid & (np.abs(gap) >= k)
                pool = np.flatnonzero(valid & (side_ctrl != 0))
                for kk in KS:
                    cand = np.flatnonzero(cond(kk))
                    if len(cand) == 0 or len(pool) == 0:
                        continue
                    sig = cand[_refractory(grid[cand])]
                    ctrl = np.sort(rng.choice(pool, size=len(sig), replace=len(pool) < len(sig)))
                    base = CONFIGS.index((W, kk, BS[0], HS[0]))
                    for is_ctrl, idx, sides in ((0, sig, side_sig), (1, ctrl, side_ctrl)):
                        tf, nets = _trades(f, grid[idx], sides[idx], uf[idx], comm_px)
                        if len(tf) == 0:
                            continue
                        n_ex = nets.shape[1]
                        ch = np.empty(len(tf) * n_ex, dtype=ROW)
                        ch["cid"] = np.tile(np.arange(base, base + n_ex), len(tf))
                        ch["ctrl"], ch["kind"] = is_ctrl, kind
                        ch["t"] = np.repeat(tf, n_ex)
                        ch["net"] = nets.reshape(-1)
                        chunks.append(ch)
    mt5.shutdown()
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=ROW)


def one(sym: str):
    t0 = time.time()
    ev = follower_events(sym)
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    np.save(OUT / "parts" / f"{sym}.npy", ev)
    print(sym, "rows", len(ev), f"{time.time() - t0:.0f}s", flush=True)


def collect():
    parts = OUT / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [s for s in SPECS if not (parts / f"{s}.npy").exists()]
    running = {}
    while todo or running:
        while todo and len(running) < WORKERS:
            s = todo.pop(0)
            running[s] = (subprocess.Popen([sys.executable, "-W", "ignore", "-m", "engine_v2.run.gate1f", "one", s],
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
    ev = {s: np.load(OUT / "parts" / f"{s}.npy") for s in SPECS if (OUT / "parts" / f"{s}.npy").exists()}
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    report = {}
    for scope, kinds in (("all", (0, 1)), ("correlated", (0,)), ("triangle", (1,))):
        table = []
        for cid, cfg in enumerate(CONFIGS):
            acc = {k: [] for k in ("d", "h", "dc", "hc")}
            by_cls = {c: [] for c in range(4)}
            for s, e in ev.items():
                m = (e["cid"] == cid) & np.isin(e["kind"], kinds)
                early = e["t"] < T_SPLIT_MS
                acc["d"].append(e["net"][m & (e["ctrl"] == 0) & early])
                acc["h"].append(e["net"][m & (e["ctrl"] == 0) & ~early])
                acc["dc"].append(e["net"][m & (e["ctrl"] == 1) & early])
                acc["hc"].append(e["net"][m & (e["ctrl"] == 1) & ~early])
                by_cls[_cls(s)].append(e["net"][m & (e["ctrl"] == 0) & ~early])
            cat = lambda v: np.concatenate(v).astype(float) if v else np.array([])
            table.append({"cfg": dict(zip(("W", "k", "b", "H"), cfg)), "discovery": _stats(cat(acc["d"])),
                          "discovery_control": _stats(cat(acc["dc"])), "holdout": _stats(cat(acc["h"])),
                          "holdout_control": _stats(cat(acc["hc"])),
                          "holdout_by_class": {nm: _stats(cat(by_cls[c])) for c, nm in
                                               {0: "FX", 1: "metals", 2: "oil", 3: "indices"}.items()}})
        eligible = [r for r in table if r["discovery"].get("n", 0) >= 300]
        if not eligible:
            report[scope] = {"note": "no configuration with >= 300 discovery trades"}
            continue
        best = max(eligible, key=lambda r: (r["discovery"]["net"], r["discovery"]["win"]))
        passed = bool(okf(best["holdout"]) and not okf(best["holdout_control"]))
        both = [r for r in eligible if r["discovery"]["net"] > 0 and r["holdout"].get("n", 0) >= 300 and r["holdout"]["net"] > 0]
        report[scope] = {"chosen_on_discovery": best, "PASS": passed, "positive_in_both": both,
                         "top10_discovery": sorted(eligible, key=lambda r: -r["discovery"]["net"])[:10], "all": table}
        print(f"[{scope}] CHOSEN {best['cfg']} disc {best['discovery']} disc_ctrl {best['discovery_control']} "
              f"hold {best['holdout']} hold_ctrl {best['holdout_control']} PASS {passed}", flush=True)
        print(f"[{scope}]   by class (holdout): {best['holdout_by_class']}", flush=True)
        for r in report[scope]["top10_discovery"][:5]:
            print(f"[{scope}]   top {r['cfg']} disc {r['discovery']} ctrl {r['discovery_control']} hold {r['holdout']}")
        print(f"[{scope}]   configurations positive in discovery and holdout: {len(both)}", flush=True)
    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "one":
        one(sys.argv[2])
    else:
        {"collect": collect, "analyse": analyse}[sys.argv[1]]()
