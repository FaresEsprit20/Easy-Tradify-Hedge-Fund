"""Gate 1d (strategic_plan_v4.md): sub-minute tick microstructure, own market and related markets, on the Gate 1b events.

Pre-registered 2026-09-17, before any outcome was computed (amended the same day, still before any outcome, to add
related-market seconds features and the premise step):
  events/labels  exactly the Gate 1b events and bracket labels (reports/v4/gate1b/events.npz): every M5 close,
                 30 markets, both sides, 1:1 brackets at 1x / 2x ATR(M15), true bid/ask, commission.
  unit U         RMS of one-minute mid changes over the 60 minutes before the event (minutes with quotes only).
  tick features  MT5 raw ticks strictly BEFORE the event time (read-only), quote changes only:
                 n10/n30/n60 updates, accel = 6*n10/n60, rate vs the last hour, up/down balance 10s/30s,
                 mid move over 5/10/30/60s in U, largest single jump 60s in U, 60s range in U and position in it,
                 spread now vs its 60s median, spread in U, seconds since the last mid change, bid share of updates
                 30s; related markets (Gate 1b RELATED map): mean mid move over 5/10/30s in their own U and the gap
                 to the own move.
  step A premise does the information exist at the horizon where it lives? Direction of the mid move from the
                 entry tick to 10/30/60/300s later; classifier on Gate 1b + tick features, same split and control.
                 Information beats cost iff, on held-out markets and weeks, long the top 10% and short the bottom
                 10% gives an average mid move in the predicted direction above the average round-trip cost
                 (max(entry spread, 60s median spread) + commission), t >= 2, while the control does not.
  step B gate    bracket labels G1L/G1S/G2L/G2S with (a) Gate 1b features (reference), (b) Gate 1b + tick features,
                 (c) tick features + market class; same split, model, control and PASS as Gate 1b.

    python -m engine_v2.run.gate1d collect      (one read-only MT5 subprocess per market)
    python -m engine_v2.run.gate1d analyse
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "v4" / "gate1d"
SRC = ROOT / "reports" / "v4" / "gate1b" / "events.npz"
WORKERS = 5
TIMEOUT = 3600
TICK_FEATURES = ["n10", "n30", "n60", "accel", "rate_hour", "bal10", "bal30", "move5", "move10", "move30", "move60",
                 "jump60", "rng60", "pos60", "spread_rel", "spread_u", "since_change", "bid_share30",
                 "rel_move5", "rel_move10", "rel_move30", "gap5", "gap10", "gap30"]
FORWARD = ["fwd10", "fwd30", "fwd60", "fwd300", "cost_u"]
HORIZONS = (10, 30, 60, 300)
STALE_MS = 300_000


def _read(mt5, sym, lo_s, hi_s):
    a = mt5.copy_ticks_range(sym, datetime.fromtimestamp(lo_s, tz=timezone.utc),
                             datetime.fromtimestamp(hi_s, tz=timezone.utc), mt5.COPY_TICKS_ALL)
    if a is None or len(a) < 2:
        return None
    tm, bid, ask = a["time_msc"].astype(np.int64), a["bid"].astype(float), a["ask"].astype(float)
    ok = (bid > 0) & (ask >= bid)
    tm, bid, ask = tm[ok], bid[ok], ask[ok]
    if len(tm) < 2:
        return None
    keep = np.r_[True, (np.diff(bid) != 0) | (np.diff(ask) != 0)]      # quote changes only
    return tm[keep], bid[keep], ask[keep]


def _unit(tm, mid, T):
    """RMS one-minute mid change over the hour before each T (minutes with at least one quote)."""
    grid = T[:, None] - 60_000 * np.arange(60, -1, -1)[None, :]
    idx = np.searchsorted(tm, grid, side="left") - 1
    m = np.where(idx >= 0, mid[np.clip(idx, 0, None)], np.nan)
    d = np.diff(m, axis=1)
    active = (np.diff(idx, axis=1) > 0) & np.isfinite(d)
    cnt = active.sum(axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        U = np.sqrt(np.nanmean(np.where(active, d * d, np.nan), axis=1))
    U[(cnt < 10) | ~(U > 0)] = np.nan
    return U


def _moves(tm, mid, T, U, ks):
    """Mid move over the last k seconds before T, in U; NaN when the market has no quote for STALE_MS."""
    e = np.searchsorted(tm, T, side="left")
    last = np.where(e >= 1, mid[np.clip(e - 1, 0, None)], np.nan)
    stale = (e < 1) | (T - tm[np.clip(e - 1, 0, None)] > STALE_MS)
    out = {}
    for k in ks:
        j = np.searchsorted(tm, T - k * 1000, side="left") - 1
        mv = np.where(j >= 0, (last - mid[np.clip(j, 0, None)]) / U, np.nan)
        mv[stale] = np.nan
        out[k] = mv
    return out


def features_for_symbol(sym: str, T_s: np.ndarray):
    import MetaTrader5 as mt5
    from engine_v2.data.symbols import facts
    from engine_v2.run.gate1b import RELATED
    if not mt5.initialize(timeout=20000):
        raise RuntimeError(mt5.last_error())
    fx = facts(sym)
    comm_px = fx.commission_usd_per_lot_round_trip / fx.usd_per_price_unit_per_lot
    X = np.full((len(T_s), len(TICK_FEATURES)), np.nan, np.float32)
    F = np.full((len(T_s), len(FORWARD)), np.nan, np.float32)
    days = T_s // 86400
    for day in np.unique(days):
        sel = np.flatnonzero(days == day)
        lo, hi = int(day) * 86400 - 3700, int(day + 1) * 86400 + 400
        own = _read(mt5, sym, lo, hi)
        if own is None:
            continue
        tm, bid, ask = own
        T = T_s[sel].astype(np.int64) * 1000
        mid, spr = (bid + ask) / 2, ask - bid
        n = len(tm)
        dmid = np.r_[0.0, np.diff(mid)]
        up, dn = np.r_[0, np.cumsum(dmid > 0)], np.r_[0, np.cumsum(dmid < 0)]
        db = np.r_[0, np.cumsum(np.r_[False, np.diff(bid) != 0])]
        da = np.r_[0, np.cumsum(np.r_[False, np.diff(ask) != 0])]
        lastchg = np.maximum.accumulate(np.where(dmid != 0, np.arange(n), 0))
        U = _unit(tm, mid, T)
        e = np.searchsorted(tm, T, side="left")
        s = {k: np.searchsorted(tm, T - k * 1000, side="left") for k in (10, 30, 60, 3600)}
        mv = _moves(tm, mid, T, U, (5, 10, 30, 60))
        rel = {k: [] for k in (5, 10, 30)}
        for r in RELATED.get(sym, []):
            rd = _read(mt5, r, lo, hi)
            if rd is None:
                continue
            rmid = (rd[1] + rd[2]) / 2
            rmv = _moves(rd[0], rmid, T, _unit(rd[0], rmid, T), (5, 10, 30))
            for k in rel:
                rel[k].append(rmv[k])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            relm = {k: (np.nanmean(np.vstack(v), axis=0) if v else np.full(len(T), np.nan)) for k, v in rel.items()}
        for q, k in enumerate(sel):
            eq = int(e[q])
            if eq < 2:
                continue
            a60 = int(s[60][q])
            n10, n30, n60 = eq - int(s[10][q]), eq - int(s[30][q]), eq - a60
            nh = eq - int(s[3600][q])
            seg = mid[max(a60 - 1, 0):eq]
            rng = (seg.max() - seg.min()) if len(seg) else 0.0
            u10, d10 = up[eq] - up[s[10][q]], dn[eq] - dn[s[10][q]]
            u30, d30 = up[eq] - up[s[30][q]], dn[eq] - dn[s[30][q]]
            nb, na = db[eq] - db[s[30][q]], da[eq] - da[s[30][q]]
            med_spr = float(np.median(spr[a60:eq])) if n60 else float(spr[eq - 1])
            Uq = U[q]
            X[k, :18] = [n10, n30, n60, 6.0 * n10 / max(n60, 1), n60 / max(nh / 60.0, 1e-9),
                         (u10 - d10) / (u10 + d10) if u10 + d10 else 0.0,
                         (u30 - d30) / (u30 + d30) if u30 + d30 else 0.0,
                         mv[5][q], mv[10][q], mv[30][q], mv[60][q],
                         float(np.abs(dmid[a60:eq]).max()) / Uq if n60 else 0.0,
                         rng / Uq, (mid[eq - 1] - seg.min()) / rng if rng > 0 else 0.5,
                         spr[eq - 1] / med_spr if med_spr > 0 else 1.0, spr[eq - 1] / Uq,
                         (T[q] - tm[lastchg[eq - 1]]) / 1000.0, nb / (nb + na) if nb + na else 0.5]
            X[k, 18:21] = [relm[5][q], relm[10][q], relm[30][q]]
            X[k, 21:24] = [relm[5][q] - mv[5][q], relm[10][q] - mv[10][q], relm[30][q] - mv[30][q]]
            if eq < n and tm[eq] - T[q] <= 60_000:                          # entry tick = first quote at/after T
                F[k, len(HORIZONS)] = (max(spr[eq], med_spr) + comm_px) / Uq          # conservative spread
                for hq, h in enumerate(HORIZONS):
                    j = max(int(np.searchsorted(tm, T[q] + h * 1000, side="left")) - 1, eq)
                    F[k, hq] = (mid[j] - mid[eq]) / Uq
    mt5.shutdown()
    return X, F


def one(sym: str):
    z = np.load(SRC)
    T_s = z["t"][z["symbol"] == sym].astype(np.int64)
    t0 = time.time()
    X, F = features_for_symbol(sym, T_s)
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "parts" / f"{sym}.npz", X=X, F=F, t=T_s)
    print(sym, "events", len(T_s), "with ticks", int(np.isfinite(X[:, 0]).sum()), "with forward",
          int(np.isfinite(F[:, 0]).sum()), f"{time.time() - t0:.0f}s", flush=True)


def collect():
    z = np.load(SRC)
    sym_arr, t_arr = z["symbol"], z["t"].astype(np.int64)
    syms = sorted(set(sym_arr.tolist()))
    parts = OUT / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [s for s in syms if not (parts / f"{s}.npz").exists()]
    running = {}
    while todo or running:
        while todo and len(running) < WORKERS:
            s = todo.pop(0)
            running[s] = (subprocess.Popen([sys.executable, "-W", "ignore", "-m", "engine_v2.run.gate1d", "one", s],
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
    X = np.full((len(t_arr), len(TICK_FEATURES)), np.nan, np.float32)
    F = np.full((len(t_arr), len(FORWARD)), np.nan, np.float32)
    for s in syms:
        f = parts / f"{s}.npz"
        if not f.exists():
            print("MISSING", s)
            continue
        p = np.load(f)
        mask = sym_arr == s
        assert np.array_equal(p["t"], t_arr[mask]), s
        X[mask], F[mask] = p["X"], p["F"]
    np.savez_compressed(OUT / "tick_features.npz", X=X, F=F, features=np.array(TICK_FEATURES),
                        forward=np.array(FORWARD))
    print("merged", len(t_arr), "events; with tick features", int(np.isfinite(X[:, 0]).sum()))


def _fit_predict(X_tr, y_tr, X_te, seed_rng):
    from sklearn.ensemble import HistGradientBoostingClassifier
    params = dict(max_depth=4, learning_rate=0.05, max_iter=400, min_samples_leaf=100, l2_regularization=1.0)
    p = HistGradientBoostingClassifier(**params, random_state=0).fit(X_tr, y_tr).predict_proba(X_te)[:, 1]
    pc = HistGradientBoostingClassifier(**params, random_state=0).fit(X_tr, seed_rng.permutation(y_tr)).predict_proba(X_te)[:, 1]
    return p, pc


def _edge_stats(move, cost):
    if len(move) < 2:
        return {"n": int(len(move))}
    edge = move - cost
    t = float(edge.mean() / (edge.std(ddof=1) / np.sqrt(len(edge)))) if edge.std() > 0 else 0.0
    return {"n": int(len(move)), "move_u": round(float(move.mean()), 4), "cost_u": round(float(cost.mean()), 4),
            "edge_u": round(float(edge.mean()), 4), "t": round(t, 1), "share_beating_cost": round(float((edge > 0).mean()), 3)}


def analyse():
    from sklearn.metrics import roc_auc_score
    from engine_v2.run.gate1b import FEATURES, T_SPLIT, _stats
    z = np.load(SRC)
    sym_arr, t_arr, X1b, NET = z["symbol"], z["t"], z["X"].astype(float), z["net"].astype(float)
    labels = [str(x) for x in z["labels"]]
    tf = np.load(OUT / "tick_features.npz")
    XT, FW = tf["X"].astype(float), tf["F"].astype(float)
    syms = sorted(set(sym_arr.tolist()))
    rng = np.random.default_rng(11)
    order = list(rng.permutation(syms))
    groups = [set(order[k::3]) for k in range(3)]
    cls_arr = X1b[:, FEATURES.index("cls")]
    classes = {0: "FX", 1: "metals", 2: "oil", 3: "indices"}
    X_full = np.hstack([X1b, XT])
    report = {"premise": {}, "gate": {}}
    cost = FW[:, len(HORIZONS)]

    # step A: premise
    for hq, h in enumerate(HORIZONS):
        fwd = FW[:, hq]
        known = np.isfinite(fwd) & np.isfinite(cost)
        parts, parts_c, aucs = [], [], []
        for grp in groups:
            in_g = np.isin(sym_arr, list(grp))
            tr = (~in_g) & (t_arr < T_SPLIT) & known & (fwd != 0)
            te = in_g & (t_arr >= T_SPLIT) & known
            p, pc = _fit_predict(X_full[tr], (fwd[tr] > 0).astype(int), X_full[te], rng)
            nz = fwd[te] != 0
            aucs.append(roc_auc_score((fwd[te][nz] > 0).astype(int), p[nz]))
            idx = np.flatnonzero(te)
            for store, prob in ((parts, p), (parts_c, pc)):
                store.append((idx, np.argsort(np.argsort(-prob)) / len(prob)))
        res = {"auc": round(float(np.mean(aucs)), 3)}
        for q in (0.10, 0.02):
            for name, store in (("model", parts), ("control", parts_c)):
                mv, cs, cl = [], [], []
                for idx, rk in store:
                    lo_, hi_ = idx[rk < q], idx[rk >= 1 - q]
                    mv += [fwd[lo_], -fwd[hi_]]
                    cs += [cost[lo_], cost[hi_]]
                    cl += [cls_arr[lo_], cls_arr[hi_]]
                mv, cs, cl = np.concatenate(mv), np.concatenate(cs), np.concatenate(cl)
                res[f"{name}_top{q:.0%}"] = _edge_stats(mv, cs)
                if name == "model":
                    res[f"model_top{q:.0%}_by_class"] = {nm: _edge_stats(mv[cl == c], cs[cl == c]) for c, nm in classes.items()}
            m_ok = res[f"model_top{q:.0%}"].get("edge_u", -1) > 0 and res[f"model_top{q:.0%}"].get("t", 0) >= 2
            c_ok = res[f"control_top{q:.0%}"].get("edge_u", -1) > 0 and res[f"control_top{q:.0%}"].get("t", 0) >= 2
            res[f"beats_cost_top{q:.0%}"] = bool(m_ok and not c_ok)
        report["premise"][f"{h}s"] = res
        print(f"premise {h:>3}s auc={res['auc']} top10={res['model_top10%']} top2={res['model_top2%']} "
              f"control_top10={res['control_top10%']}", flush=True)
        print("   by class top10:", res["model_top10%_by_class"], flush=True)
        (OUT / "analysis.json").write_text(json.dumps(report, indent=1))

    # step B: bracket gate
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    variants = (("1b_only", X1b), ("1b+ticks", X_full), ("ticks_only", np.hstack([XT, cls_arr[:, None]])))
    for variant, X_all in variants:
        for key in labels:
            net_all = NET[:, labels.index(key)]
            y_all = (net_all > 0).astype(int)
            ranks, ranks_c, idxs, aucs = [], [], [], []
            for grp in groups:
                in_g = np.isin(sym_arr, list(grp))
                tr, te = (~in_g) & (t_arr < T_SPLIT), in_g & (t_arr >= T_SPLIT)
                p, pc = _fit_predict(X_all[tr], y_all[tr], X_all[te], rng)
                aucs.append(roc_auc_score(y_all[te], p))
                ranks.append(np.argsort(np.argsort(-p)) / len(p))
                ranks_c.append(np.argsort(np.argsort(-pc)) / len(pc))
                idxs.append(np.flatnonzero(te))
            rk, rkc, ix = np.concatenate(ranks), np.concatenate(ranks_c), np.concatenate(idxs)
            res = {"auc": round(float(np.mean(aucs)), 3), "all": _stats(net_all[ix], y_all[ix])}
            passed = False
            for q in (0.10, 0.05, 0.02):
                sel, selc = ix[rk < q], ix[rkc < q]
                st, sc = _stats(net_all[sel], y_all[sel]), _stats(net_all[selc], y_all[selc])
                res[f"top{q:.0%}"], res[f"control_top{q:.0%}"] = st, sc
                passed = passed or (okf(st) and not okf(sc))
                res[f"top{q:.0%}_by_class"] = {nm: _stats(net_all[sel[cls_arr[sel] == c]], y_all[sel[cls_arr[sel] == c]])
                                               for c, nm in classes.items()}
            res["PASS"] = passed
            report["gate"][f"{variant}|{key}"] = res
            print(f"gate {variant:10s} {key}: auc={res['auc']} top10={res['top10%']} top5={res['top5%']} "
                  f"top2={res['top2%']} ctrl_top5={res['control_top5%']} PASS={passed}", flush=True)
            (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "one":
        one(sys.argv[2])
    else:
        {"collect": collect, "analyse": analyse}[sys.argv[1]]()
