"""Gate 1b (strategic_plan_v4.md): open M1 edge search with cross-market lead/lag and microstructure.

Pre-registered 2026-09-17, before any result:
  data      true bid/ask M1 from MT5 ticks, 2026-05-25 -> 2026-09-17, 30 markets (FX, metals, indices, oil)
  events    every M5 close in every market, both directions; skipped when the spread is > 3x its median
  geometry  G1: stop = 1.0 x ATR(M15), target = 1R;  G2: stop = 2.0 x ATR(M15), target = 1R
            (stop never below 8 x the current spread). Entry next M1 open on the ask (long) / bid (short),
            exits on the other side, time exit after 240 M1 bars. Commission per symbol facts.
  features  own returns 1/5/15/60m, related-market returns 1/5/15m and their gap to own (lead/lag),
            tick-flow imbalance 1/5/15m, tick-rate ratio, spread/ATR, spread shock, M1 bar anatomy,
            volatility state (ATR M1/M15, ATR M15/H1), range position M15/H1, room to M15/H1 swings,
            trend M15/H1, EMA extension M5/M15, RSI M5/M15, market class. Never time of day.
  split     3 market groups (seed 11); train on other markets before T = 2026-07-20, score the group from T.
  model     HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=400, min_samples_leaf=100,
            l2_regularization=1.0) on win, per geometry and direction; shuffled-label control
  PASS      a top slice (10/5/2% ranked within scoring group) with >= 300 trades, win >= 65%,
            net R >= +0.20 with t >= 2, while the control's same slice fails

    python -m engine_v2.run.gate1b collect
    python -m engine_v2.run.gate1b analyse
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[2] / "reports" / "v4" / "gate1b"
START = int(datetime(2026, 5, 25, tzinfo=timezone.utc).timestamp())
T_SPLIT = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp())
HOLD = 240
GEOMETRIES = {"G1": 1.0, "G2": 2.0}
RELATED = {
    "US500": ["USTEC", "US30", "US2000"], "USTEC": ["US500", "US30", "US2000"], "US30": ["US500", "USTEC", "US2000"],
    "US2000": ["US500", "USTEC", "US30"], "DE40": ["STOXX50", "F40", "UK100"], "STOXX50": ["DE40", "F40", "UK100"],
    "F40": ["DE40", "STOXX50", "UK100"], "UK100": ["DE40", "STOXX50", "F40"], "JP225": ["HK50", "AUS200", "US500"],
    "HK50": ["JP225", "AUS200"], "AUS200": ["JP225", "HK50", "US500"], "XAUUSD": ["XAGUSD", "EURUSD"],
    "XAGUSD": ["XAUUSD", "EURUSD"], "XTIUSD": ["XBRUSD"], "XBRUSD": ["XTIUSD"],
    "EURUSD": ["GBPUSD", "AUDUSD", "NZDUSD", "USDCHF"], "GBPUSD": ["EURUSD", "AUDUSD", "EURGBP"],
    "AUDUSD": ["NZDUSD", "EURUSD", "AUDCAD"], "NZDUSD": ["AUDUSD", "EURUSD", "AUDNZD"],
    "USDCAD": ["EURUSD", "XTIUSD", "AUDCAD"], "USDCHF": ["EURUSD", "AUDCHF"], "USDJPY": ["EURJPY", "GBPJPY", "US500"],
    "EURGBP": ["EURUSD", "GBPUSD"], "EURJPY": ["EURUSD", "USDJPY"], "GBPJPY": ["GBPUSD", "USDJPY"],
    "EURCAD": ["EURUSD", "USDCAD"], "AUDNZD": ["AUDUSD", "NZDUSD"], "AUDCAD": ["AUDUSD", "USDCAD"],
    "AUDCHF": ["AUDUSD", "USDCHF"], "GBPAUD": ["GBPUSD", "AUDUSD"],
}
FEATURES = ["r1", "r5", "r15", "r60", "rel1", "rel5", "rel15", "gap1", "gap5", "gap15", "imb1", "imb5", "imb15",
            "tickrate5", "spread_atr", "spread_shock", "body1", "upwick1", "lowwick1", "vol_m1_m15", "vol_m15_h1",
            "pos_m15", "pos_h1", "room_up_m15", "room_dn_m15", "room_up_h1", "room_dn_h1", "tr_m15", "tr_h1",
            "ext_m5", "ext_m15", "rsi_m5", "rsi_m15", "cls"]


def _cls(sym):
    if sym.startswith(("XAU", "XAG")):
        return 1
    if sym.startswith(("XTI", "XBR")):
        return 2
    return 0 if (len(sym) == 6 and sym.isalpha()) else 3


def _load(sym):
    from engine_v2.data.replay import load_m1
    b = load_m1(sym)
    return b.slice(int(np.searchsorted(b.time, START)), len(b))


def _aligned_close(ref_time, bars):
    """Last closed mid close of `bars` at each ref minute (NaN before its first bar)."""
    idx = np.searchsorted(bars.time, ref_time, side="right") - 1
    out = np.where(idx >= 0, bars.close[np.clip(idx, 0, None)], np.nan)
    return out


def run_symbol(sym):
    from engine_v2.data.symbols import facts
    from engine_v2.market_model.context import Context
    fx = facts(sym)
    b = _load(sym)
    ctx = Context(sym, b)
    t, c, n = b.time, b.close, len(b)
    a15 = ctx.atr("M15")
    ah = ctx.atr("H1")
    a1 = ctx.atr("M1")
    ema5, ema15 = ctx.ema("M5", 20), ctx.ema("M15", 20)
    rsi5, rsi15 = ctx.rsi("M5"), ctx.rsi("M15")
    tr15, trh = ctx.trend("M15"), ctx.trend("H1")
    m5, m15, h1 = ctx.bars("M5"), ctx.bars("M15"), ctx.bars("H1")
    sw15, swh = ctx.swings("M15"), ctx.swings("H1")
    spread = b.ask_close - b.bid_close
    med_spread = np.median(spread)
    rel = {}
    for r in RELATED.get(sym, []):
        try:
            rb = _load(r)
        except FileNotFoundError:
            continue
        rc = _aligned_close(t, rb)
        ra = Context(r, rb).atr("M15")
        ridx = np.searchsorted(rb.close_time if False else rb.time, t, side="right") - 1
        r_m15 = Context(r, rb).bars("M15")
        rel[r] = (rc, r_m15, ra)
    up, dn, vol = b.up_ticks, b.down_ticks, b.volume

    def lastidx(bars, tt):
        return int(np.searchsorted(bars.close_time, tt, side="right")) - 1

    rows = []
    for i in range(120, n - HOLD - 1):
        tt = int(t[i]) + 60
        if tt % 300 != 0:
            continue
        if spread[i] > 3 * med_spread:
            continue
        j15, jh, j5 = lastidx(m15, tt), lastidx(h1, tt), lastidx(m5, tt)
        if min(j15, jh, j5) < 30:
            continue
        A15, AH, A1 = a15[j15], ah[jh], a1[i]
        if not (A15 > 0 and AH > 0 and A1 > 0):
            continue
        ret = lambda k: (c[i] - c[i - k]) / A15
        rel_r = {k: [] for k in (1, 5, 15)}
        for r, (rc, r_m15, ra) in rel.items():
            jr = lastidx(r_m15, tt)
            if jr < 0 or not (ra[jr] > 0) or not np.isfinite(rc[i - 15]):
                continue
            for k in (1, 5, 15):
                rel_r[k].append((rc[i] - rc[i - k]) / ra[jr])
        relm = {k: (float(np.mean(v)) if v else np.nan) for k, v in rel_r.items()}

        def imb(k):
            u, d_ = np.nansum(up[i - k + 1:i + 1]), np.nansum(dn[i - k + 1:i + 1])
            return float((u - d_) / (u + d_)) if u + d_ > 0 else np.nan

        rng1 = b.high[i] - b.low[i]
        hi15, lo15 = m15.high[j15 - 19:j15 + 1].max(), m15.low[j15 - 19:j15 + 1].min()
        hih, loh = h1.high[jh - 23:jh + 1].max(), h1.low[jh - 23:jh + 1].min()

        def room(sw, j, kind):
            known = sw.available_idx <= j
            lv = sw.price[known & (sw.kind == kind)]
            lv = lv[(lv - c[i]) * kind > 0]
            return float(np.min(np.abs(lv - c[i])) / A15) if len(lv) else 10.0

        f = {
            "r1": ret(1), "r5": ret(5), "r15": ret(15), "r60": ret(60),
            "rel1": relm[1], "rel5": relm[5], "rel15": relm[15],
            "gap1": relm[1] - ret(1) if np.isfinite(relm[1]) else np.nan,
            "gap5": relm[5] - ret(5) if np.isfinite(relm[5]) else np.nan,
            "gap15": relm[15] - ret(15) if np.isfinite(relm[15]) else np.nan,
            "imb1": imb(1), "imb5": imb(5), "imb15": imb(15),
            "tickrate5": float(np.mean(vol[i - 4:i + 1]) / max(np.mean(vol[i - 59:i + 1]), 1e-9)),
            "spread_atr": float(spread[i] / A1), "spread_shock": float(spread[i] / max(np.median(spread[i - 59:i + 1]), 1e-12)),
            "body1": float((c[i] - b.open[i]) / rng1) if rng1 > 0 else 0.0,
            "upwick1": float((b.high[i] - max(c[i], b.open[i])) / rng1) if rng1 > 0 else 0.0,
            "lowwick1": float((min(c[i], b.open[i]) - b.low[i]) / rng1) if rng1 > 0 else 0.0,
            "vol_m1_m15": float(A1 / A15), "vol_m15_h1": float(A15 / AH),
            "pos_m15": float((c[i] - lo15) / (hi15 - lo15)) if hi15 > lo15 else 0.5,
            "pos_h1": float((c[i] - loh) / (hih - loh)) if hih > loh else 0.5,
            "room_up_m15": room(sw15, j15, 1), "room_dn_m15": room(sw15, j15, -1),
            "room_up_h1": room(swh, jh, 1), "room_dn_h1": room(swh, jh, -1),
            "tr_m15": float(tr15[j15]), "tr_h1": float(trh[jh]),
            "ext_m5": float((m5.close[j5] - ema5[j5]) / A15) if np.isfinite(ema5[j5]) else np.nan,
            "ext_m15": float((m15.close[j15] - ema15[j15]) / A15) if np.isfinite(ema15[j15]) else np.nan,
            "rsi_m5": float(rsi5[j5]), "rsi_m15": float(rsi15[j15]), "cls": float(_cls(sym)),
        }
        # labels: both directions, both geometries, on bid/ask from the next minute's open
        lab = {}
        for g, k in GEOMETRIES.items():
            dist = max(k * A15, 8 * spread[i])
            for d, name in ((1, "L"), (-1, "S")):
                if d > 0:
                    fill = b.ask_open[i + 1]
                    stop, tgt = fill - dist, fill + dist
                    xs_lo, xs_hi = b.bid_low[i + 1:i + 1 + HOLD], b.bid_high[i + 1:i + 1 + HOLD]
                    ks, kt = np.argmax(xs_lo <= stop), np.argmax(xs_hi >= tgt)
                    hit_s, hit_t = xs_lo[ks] <= stop, xs_hi[kt] >= tgt
                    end_px = b.bid_close[i + HOLD]
                else:
                    fill = b.bid_open[i + 1]
                    stop, tgt = fill + dist, fill - dist
                    xs_hi, xs_lo = b.ask_high[i + 1:i + 1 + HOLD], b.ask_low[i + 1:i + 1 + HOLD]
                    ks, kt = np.argmax(xs_hi >= stop), np.argmax(xs_lo <= tgt)
                    hit_s, hit_t = xs_hi[ks] >= stop, xs_lo[kt] <= tgt
                    end_px = b.ask_close[i + HOLD]
                if hit_s and (not hit_t or ks <= kt):
                    gross = -1.0
                elif hit_t:
                    gross = 1.0
                else:
                    gross = float((end_px - fill) * d / dist)
                net = gross - fx.commission_r(dist)
                lab[f"{g}{name}_net"] = round(net, 4)
                lab[f"{g}{name}_win"] = bool(net > 0)
        rows.append({"symbol": sym, "t": tt, **{k: (None if not np.isfinite(v) else round(float(v), 5)) for k, v in f.items()}, **lab})
    return rows


def collect():
    from engine_v2.data.replay import available_symbols
    syms = [s for s in available_symbols() if s in RELATED]
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(OUT / "events.jsonl", "w") as fh, ProcessPoolExecutor(12) as ex:
        for part in ex.map(run_symbol, syms):
            for r in part:
                fh.write(json.dumps(r) + "\n")
            n += len(part)
            print("rows so far", n, flush=True)
    print("events", n, "markets", len(syms))


def _stats(nets, wins):
    if len(nets) == 0:
        return {"n": 0}
    nets = np.asarray(nets)
    t = float(nets.mean() / (nets.std(ddof=1) / np.sqrt(len(nets)))) if len(nets) > 1 and nets.std() > 0 else 0.0
    return {"n": int(len(nets)), "win": round(float(np.mean(wins)), 3), "net": round(float(nets.mean()), 3), "t": round(t, 1)}


def analyse():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    z = np.load(OUT / "events.npz")
    sym_arr, t_arr, X_all, NET = z["symbol"], z["t"], z["X"].astype(float), z["net"].astype(float)
    labels = [str(x) for x in z["labels"]]
    syms = sorted(set(sym_arr.tolist()))
    rng = np.random.default_rng(11)
    order = list(rng.permutation(syms))
    groups = [set(order[k::3]) for k in range(3)]
    cls_arr = X_all[:, FEATURES.index("cls")]
    report = {}
    params = dict(max_depth=4, learning_rate=0.05, max_iter=400, min_samples_leaf=100, l2_regularization=1.0)
    for g in GEOMETRIES:
        for dname in ("L", "S"):
            key = f"{g}{dname}"
            net_all = NET[:, labels.index(key)]
            y_all = (net_all > 0).astype(int)
            ranks, ranks_c, idxs, aucs = [], [], [], []
            for grp in groups:
                in_g = np.isin(sym_arr, list(grp))
                tr = (~in_g) & (t_arr < T_SPLIT)
                te = in_g & (t_arr >= T_SPLIT)
                if tr.sum() < 1000 or te.sum() < 200:
                    continue
                m = HistGradientBoostingClassifier(**params, random_state=0).fit(X_all[tr], y_all[tr])
                p = m.predict_proba(X_all[te])[:, 1]
                mc = HistGradientBoostingClassifier(**params, random_state=0).fit(X_all[tr], rng.permutation(y_all[tr]))
                pc = mc.predict_proba(X_all[te])[:, 1]
                aucs.append(roc_auc_score(y_all[te], p))
                ranks.append(np.argsort(np.argsort(-p)) / len(p))
                ranks_c.append(np.argsort(np.argsort(-pc)) / len(pc))
                idxs.append(np.flatnonzero(te))
            rk, rkc, ix = np.concatenate(ranks), np.concatenate(ranks_c), np.concatenate(idxs)
            res = {"oos": int(len(ix)), "auc": round(float(np.mean(aucs)), 3), "all": _stats(net_all[ix], y_all[ix])}
            passed = False
            for q in (0.10, 0.05, 0.02):
                sel, selc = ix[rk < q], ix[rkc < q]
                st, sc = _stats(net_all[sel], y_all[sel]), _stats(net_all[selc], y_all[selc])
                res[f"top{q:.0%}"], res[f"control_top{q:.0%}"] = st, sc
                ok = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
                if ok(st) and not ok(sc):
                    passed = True
                for k, name in {0: "FX", 1: "metals", 2: "oil", 3: "indices"}.items():
                    selk = sel[cls_arr[sel] == k]
                    res.setdefault(f"top{q:.0%}_by_class", {})[name] = _stats(net_all[selk], y_all[selk])
            res["PASS"] = passed
            report[key] = res
            print(f"{key}: auc={res['auc']} all={res['all']} top10={res['top10%']} top5={res['top5%']} top2={res['top2%']} "
                  f"ctrl_top5={res['control_top5%']} PASS={passed}", flush=True)
            print(f"    top5 by class: {res['top5%_by_class']}", flush=True)
    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    {"collect": collect, "analyse": analyse}[sys.argv[1]]()
