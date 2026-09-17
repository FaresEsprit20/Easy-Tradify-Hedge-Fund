"""Gate 1h (strategic_plan_v4.md): relative strength across markets and currencies, on the Gate 1b events.

Every earlier gate read each market on its own. Pre-registered 2026-09-17, before any result:
  events/labels  the Gate 1b events and bracket labels (reports/v4/gate1b/events.npz): M5 closes, true bid/ask,
                 G1 = stop 1x ATR(M15), G2 = stop 2x ATR(M15), target 1R, time exit 240 min, commission
  XS             cross-section of all markets quoting at the same M5 close (>= 10): z of the Gate 1b return r_L
                 (ATR units, L in {15, 60} min) across markets; take the highest and the lowest with |z| >= z_min;
                 CONT = long the highest / short the lowest, REV = the opposite
  CS             currency strength from 17 instruments (15 FX pairs, XAUUSD, XAGUSD; 10 currencies): log mid
                 returns over L are solved for strengths (minimum-norm least squares, strengths sum to zero);
                 implied pair move = strength(base) - strength(quote), residual = actual - implied; both z-scored
                 by their own standard deviation over the previous 5 days of M5 closes.
                 STRENGTH_CONT / STRENGTH_REV: instrument with the largest |implied z|, with / against it;
                 RESID_REV / RESID_CONT: instrument with the largest |residual z|, against / with it
  thresholds     z_min in {1.5, 2.5}; one trade per market per configuration per 60 minutes
  control        for every trade: a random other market quoting at the same close, random side, same geometry
  split/PASS     best configuration on DISCOVERY (before 2026-07-20, >= 300 trades) scored once on HOLDOUT;
                 PASS = holdout >= 300 trades, win >= 65%, net >= +0.20R, t >= 2, while the control fails

    python -m engine_v2.run.gate1h
"""
from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "v4" / "gate1h"
SRC = ROOT / "reports" / "v4" / "gate1b" / "events.npz"
INSTR = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY",
         "EURCAD", "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "XAUUSD", "XAGUSD"]
CURR = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "XAU", "XAG"]
COOLDOWN = 3600
Z_WINDOW = 5 * 288


def _rolling_past_std(x: np.ndarray, window: int) -> np.ndarray:
    """Std of the previous `window` finite values (strictly before each row), per column; NaN until 200 exist."""
    out = np.full_like(x, np.nan)
    for c in range(x.shape[1]):
        col = x[:, c]
        fin = np.isfinite(col)
        v = np.where(fin, col, 0.0)
        c1, c2, cn = np.r_[0, np.cumsum(v)], np.r_[0, np.cumsum(v * v)], np.r_[0, np.cumsum(fin)]
        i = np.arange(len(col))
        lo = np.clip(i - window, 0, None)
        n = cn[i] - cn[lo]
        s1, s2 = c1[i] - c1[lo], c2[i] - c2[lo]
        with np.errstate(invalid="ignore", divide="ignore"):
            var = (s2 - s1 * s1 / n) / (n - 1)
        out[:, c] = np.where(n >= 200, np.sqrt(np.maximum(var, 0)), np.nan)
    return out


def _stats(net):
    net = np.asarray(net, float)
    if len(net) < 2:
        return {"n": int(len(net))}
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if net.std() > 0 else 0.0
    return {"n": int(len(net)), "win": round(float((net > 0).mean()), 3), "net": round(float(net.mean()), 3),
            "t": round(t, 1)}


def main():
    from engine_v2.data.replay import load_m1
    from engine_v2.run.gate1b import FEATURES, T_SPLIT, _cls
    z = np.load(SRC)
    sym_arr, t_arr, X, NET = z["symbol"], z["t"].astype(np.int64), z["X"].astype(float), z["net"].astype(float)
    labels = [str(x) for x in z["labels"]]
    row_of = {(str(s), int(t)): i for i, (s, t) in enumerate(zip(sym_arr, t_arr))}
    rng = np.random.default_rng(7)
    times = np.unique(t_arr)
    by_time = {}
    order = np.argsort(t_arr, kind="stable")
    bounds = np.searchsorted(t_arr[order], times)
    bounds = np.r_[bounds, len(order)]
    for k, tt in enumerate(times):
        by_time[int(tt)] = order[bounds[k]:bounds[k + 1]]

    def label_net(i, side, geom):
        return NET[i, labels.index(f"{geom}{'L' if side > 0 else 'S'}")]

    trades = {}      # config -> list of (t, net, control net, class)

    def take(cfg, i, side, geom, t, last):
        s = str(sym_arr[i])
        if t - last.get((cfg, s), -10 ** 12) < COOLDOWN:
            return
        last[(cfg, s)] = t
        pool = by_time[t]
        others = pool[pool != i]
        if len(others) == 0:
            return
        j = int(rng.choice(others))
        trades.setdefault(cfg, []).append((t, label_net(i, side, geom), label_net(j, rng.choice((-1, 1)), geom),
                                           _cls(s)))

    # --- XS: cross-section of all markets
    last = {}
    for L, geom, zmin, mode in product((15, 60), ("G1", "G2"), (1.5, 2.5), ("CONT", "REV")):
        col = FEATURES.index(f"r{L}")
        cfg = ("XS", L, mode, zmin, geom)
        for tt, idx in by_time.items():
            if len(idx) < 10:
                continue
            r = X[idx, col]
            ok = np.isfinite(r)
            if ok.sum() < 10:
                continue
            zz = np.full(len(r), np.nan)
            zz[ok] = (r[ok] - r[ok].mean()) / (r[ok].std() + 1e-12)
            hi, lo = int(np.nanargmax(zz)), int(np.nanargmin(zz))
            sgn = 1 if mode == "CONT" else -1
            if zz[hi] >= zmin:
                take(cfg, int(idx[hi]), sgn, geom, tt, last)
            if -zz[lo] >= zmin:
                take(cfg, int(idx[lo]), -sgn, geom, tt, last)

    # --- CS: currency strength
    bars = {s: load_m1(s) for s in INSTR}
    grid = np.array(sorted(tt for tt in by_time if all((s, tt) in row_of for s in INSTR[:15])), np.int64)
    A = np.zeros((len(INSTR), len(CURR)))
    for p, s in enumerate(INSTR):
        A[p, CURR.index(s[:3])], A[p, CURR.index(s[3:])] = 1.0, -1.0
    P = np.linalg.pinv(A)

    def mid_at(b, t):
        k = np.searchsorted(b.time, t - 60, side="right") - 1
        ok = (k >= 0) & (t - 60 - b.time[np.clip(k, 0, None)] <= 120)
        return np.where(ok, b.close[np.clip(k, 0, None)], np.nan)

    for L in (15, 60):
        R = np.column_stack([np.log(mid_at(bars[s], grid)) - np.log(mid_at(bars[s], grid - L * 60)) for s in INSTR])
        good = np.isfinite(R).all(axis=1)
        S = np.full((len(grid), len(CURR)), np.nan)
        S[good] = R[good] @ P.T
        IMP = S @ A.T
        RES = R - IMP
        zi = IMP / _rolling_past_std(IMP, Z_WINDOW)
        zr = RES / _rolling_past_std(RES, Z_WINDOW)
        for geom, zmin, mode in product(("G1", "G2"), (1.5, 2.5), ("STRENGTH_CONT", "STRENGTH_REV", "RESID_REV", "RESID_CONT")):
            cfg = ("CS", L, mode, zmin, geom)
            Z = zi if mode.startswith("STRENGTH") else zr
            for g, tt in enumerate(grid):
                row = Z[g]
                if not np.isfinite(row).any():
                    continue
                p = int(np.nanargmax(np.abs(row)))
                if abs(row[p]) < zmin:
                    continue
                i = row_of.get((INSTR[p], int(tt)))
                if i is None:
                    continue
                sgn = int(np.sign(row[p])) * (1 if mode in ("STRENGTH_CONT", "RESID_CONT") else -1)
                take(cfg, i, sgn, geom, int(tt), last)

    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    table = []
    for cfg, rows in trades.items():
        a = np.array([(r[0], r[1], r[2], r[3]) for r in rows], dtype=float)
        early = a[:, 0] < T_SPLIT
        table.append({"cfg": list(cfg), "discovery": _stats(a[early, 1]), "discovery_control": _stats(a[early, 2]),
                      "holdout": _stats(a[~early, 1]), "holdout_control": _stats(a[~early, 2]),
                      "holdout_by_class": {nm: _stats(a[(~early) & (a[:, 3] == c), 1])
                                           for c, nm in {0: "FX", 1: "metals", 2: "oil", 3: "indices"}.items()}})
    eligible = [r for r in table if r["discovery"].get("n", 0) >= 300]
    best = max(eligible, key=lambda r: (r["discovery"]["net"], r["discovery"]["win"]))
    passed = bool(okf(best["holdout"]) and not okf(best["holdout_control"]))
    both = [r for r in eligible if r["discovery"]["net"] > 0 and r["holdout"].get("n", 0) >= 300 and r["holdout"]["net"] > 0]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").write_text(json.dumps({"chosen_on_discovery": best, "PASS": passed,
                                                   "positive_in_both": both, "all": table}, indent=1))
    print("CHOSEN", best["cfg"], "disc", best["discovery"], "disc_ctrl", best["discovery_control"], "hold",
          best["holdout"], "hold_ctrl", best["holdout_control"], "PASS", passed)
    print("  by class (holdout):", best["holdout_by_class"])
    for r in sorted(eligible, key=lambda r: -r["discovery"]["net"])[:8]:
        print("  top", r["cfg"], "disc", r["discovery"], "ctrl", r["discovery_control"], "hold", r["holdout"],
              "hold_ctrl", r["holdout_control"])
    print("  configurations positive in discovery and holdout:", len(both), [r["cfg"] for r in both])
    hi = sorted(eligible, key=lambda r: -r["discovery"]["win"])[:3]
    for r in hi:
        print("  hi-win", r["cfg"], "disc", r["discovery"], "hold", r["holdout"])


if __name__ == "__main__":
    main()
