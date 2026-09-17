"""Gate 1 of strategic_plan_v4.md: the M1 predictability limit per market and category.

Pre-registered 2026-09-17, before any result:
  events    base setups of every category (all H4/D1 rules off) at two M1 scales:
              scalp      M1 trigger, M1-M5 structure (engine_v2/run/m1_lab.py SCALE_M1)
              precision  M1 trigger with M15/H1 structure (single-timeframe categories use an M5 setup bar)
  labels    outcome on true bid/ask M1 (commission, swap) under exit families std and half
  features  causal at the trigger close, never time of day (see features())
  split     markets in 3 fixed groups (seed 4); for each group: train on the other markets before T,
            score this group from T on. T = 2026-07-20 broker time. Each market is scored once, out of sample.
  model     HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=50,
            l2_regularization=1.0) on win; shuffled-label control trained identically
  slices    top 10% / 20% / 30% by predicted win probability (ranked within each scoring group)
  PASS      a slice with >= 300 out-of-sample trades, win >= 65%, net R >= +0.20 with t >= 2,
            and the same slice of the shuffled control does NOT pass

    python -m engine_v2.run.gate1 collect
    python -m engine_v2.run.gate1 analyse
"""
from __future__ import annotations

import importlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine_v2.run.exit_lab import make_variant
from engine_v2.run.m1_lab import SCALE_M1
from engine_v2.run.replay import MODULES

OUT = Path(__file__).resolve().parents[2] / "reports" / "v4" / "gate1"
T_SPLIT = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp())
GROUPS = 3
SEED = 4
SCALE_PRECISION = {
    "SMC": {"setup": "M5", "context": "H1"},
    "STRUCTURE": {"zone": "M15", "trigger": "M1", "context": "H1"},
    "TREND": {"impulse": "M15", "context": "H1", "trigger": "M1"},
    "MOMENTUM": {"setup": "M5", "er": "H1", "context": "H1"},
    "MEAN_REVERSION": {"setup": "M5", "er": "H1", "context": "H1"},
    "WAVE": {"pattern": "M15", "trigger": "M1", "context": "H1"},
}
SCALES = {"scalp": SCALE_M1, "precision": SCALE_PRECISION}
FEATURES = ["risk_atr_m1", "risk_atr_h1", "atr_m1_h1", "atr_m5_h1", "spread_risk", "spread_atr",
            "ret5", "ret15", "ret60", "burst5", "burst15", "tickrate5", "imb5", "imb15",
            "pos_m15", "pos_h1", "tr_m5", "tr_m15", "tr_h1", "ext_m1", "ext_m5", "rsi_m1", "rsi_m5",
            "er_m15", "er_h1", "room_m15", "room_h1", "side", "cls", "variant_code"]


def instrument_class(sym: str) -> int:
    if sym.startswith(("XAU", "XAG")):
        return 1
    if sym.startswith(("XTI", "XBR")):
        return 2
    if len(sym) == 6 and sym.isalpha() and sym.isupper():
        return 0
    return 3


def _idx(ctx, tf, t):
    return ctx.last_closed_index(tf, t)


def features(ctx, s, variants: list[str]) -> dict:
    from engine_v2.market_model.location import room_to_opposing_level_r
    t, d = s.created_at, s.direction
    m = ctx.m1
    i = _idx(ctx, "M1", t)
    i5, i15, ih = _idx(ctx, "M5", t), _idx(ctx, "M15", t), _idx(ctx, "H1", t)
    if min(i, i5, i15, ih) < 60:
        return {}
    a1, a5, a15, ah = ctx.atr("M1")[i], ctx.atr("M5")[i5], ctx.atr("M15")[i15], ctx.atr("H1")[ih]
    if not (a1 > 0 and a5 > 0 and ah > 0):
        return {}
    entry = float(s.entry["price"])
    risk = abs(entry - float(s.stop["price"]))
    c = m.close
    spread = float(m.ask_close[i] - m.bid_close[i])
    w5, w15 = slice(i - 4, i + 1), slice(i - 14, i + 1)
    ticks = m.volume
    up, dn = m.up_ticks, m.down_ticks

    def imb(w):
        u, v = np.nansum(up[w]), np.nansum(dn[w])
        return float((u - v) / (u + v) * d) if (u + v) > 0 and np.isfinite(up[w]).all() else np.nan

    def pos(tf, n, idx):
        b = ctx.bars(tf)
        hi, lo = float(b.high[idx - n + 1:idx + 1].max()), float(b.low[idx - n + 1:idx + 1].min())
        p = (entry - lo) / (hi - lo) if hi > lo else 0.5
        return p if d > 0 else 1 - p

    m5, m15b = ctx.bars("M5"), ctx.bars("M15")
    return {
        "risk_atr_m1": risk / a1, "risk_atr_h1": risk / ah, "atr_m1_h1": a1 / ah, "atr_m5_h1": a5 / ah,
        "spread_risk": spread / risk if risk > 0 else np.nan, "spread_atr": spread / a1,
        "ret5": (c[i] - c[i - 5]) * d / a1, "ret15": (c[i] - c[i - 15]) * d / a1, "ret60": (c[i] - c[i - 60]) * d / a1,
        "burst5": (m.high[w5].max() - m.low[w5].min()) / a1, "burst15": (m.high[w15].max() - m.low[w15].min()) / a1,
        "tickrate5": float(np.mean(ticks[w5]) / max(np.mean(ticks[i - 59:i + 1]), 1e-9)),
        "imb5": imb(w5), "imb15": imb(w15),
        "pos_m15": pos("M15", 20, i15) if i15 >= 20 else np.nan, "pos_h1": pos("H1", 24, ih) if ih >= 24 else np.nan,
        "tr_m5": float(ctx.trend("M5")[i5] * d), "tr_m15": float(ctx.trend("M15")[i15] * d), "tr_h1": float(ctx.trend("H1")[ih] * d),
        "ext_m1": float((c[i] - ctx.ema("M1", 20)[i]) * d / a1),
        "ext_m5": float((m5.close[i5] - ctx.ema("M5", 50)[i5]) * d / a5),
        "rsi_m1": float((ctx.rsi("M1")[i] - 50) * d), "rsi_m5": float((ctx.rsi("M5")[i5] - 50) * d),
        "er_m15": float(ctx.efficiency_ratio("M15")[i15]), "er_h1": float(ctx.efficiency_ratio("H1")[ih]),
        "room_m15": room_to_opposing_level_r(ctx, t, entry, risk, d, "M15"),
        "room_h1": room_to_opposing_level_r(ctx, t, entry, risk, d, "H1"),
        "side": float(d), "cls": float(instrument_class(s.symbol)),
        "variant_code": float(variants.index(s.variant) if s.variant in variants else -1),
    }


VARIANTS = {"SMC": ["fvg_mid"], "STRUCTURE": ["first_touch", "confirmation"], "TREND": ["pullback"],
            "MOMENTUM": ["squeeze_release"], "MEAN_REVERSION": ["vwap_stretch"],
            "WAVE": ["wyckoff_spring", "wyckoff_upthrust", "double_bottom", "double_top", "elliott_w2"]}


def run_symbol(job):
    category, scale, symbol = job
    from engine_v2.data.replay import load_m1
    from engine_v2.market_model.context import Context
    from engine_v2.run.crosspair import _rules_off
    from engine_v2.sim.outcome import simulate
    _rules_off()
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_m1(symbol))
    rows = []
    for s in mod.propose(ctx, SCALES[scale][category]):
        try:
            a = simulate(s, ctx)
            b = simulate(make_variant(s, "V3").validate(), ctx)
        except ValueError:
            continue
        if not (a.traded and b.traded):
            continue
        f = features(ctx, s, VARIANTS[category])
        if not f:
            continue
        rows.append({"category": category, "scale": scale, "symbol": symbol, "created_at": s.created_at,
                     "std_net": a.net_r, "std_win": a.win, "half_net": b.net_r, "half_win": b.win,
                     **{k: (None if (isinstance(v, float) and not np.isfinite(v)) else v) for k, v in f.items()}})
    return rows


def collect():
    from engine_v2.data.replay import available_symbols
    syms = available_symbols()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(c, sc, s) for sc in SCALES for c in SCALES[sc] for s in syms]
    n = 0
    with open(OUT / "events.jsonl", "w") as f, ProcessPoolExecutor(12) as ex:
        for part in ex.map(run_symbol, jobs, chunksize=1):
            for r in part:
                f.write(json.dumps(r) + "\n")
                n += 1
    print("events", n, "symbols", len(syms))


def _slice_stats(rows, fam):
    if not rows:
        return {"n": 0}
    net = np.array([r[f"{fam}_net"] for r in rows])
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 1 and net.std() > 0 else 0.0
    return {"n": len(rows), "win": round(float(np.mean([r[f"{fam}_win"] for r in rows])), 3),
            "net": round(float(net.mean()), 3), "t": round(t, 1)}


def _passes(st):
    return st.get("n", 0) >= 300 and st["win"] >= 0.65 and st["net"] >= 0.20 and st["t"] >= 2


def analyse():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    rows = [json.loads(l) for l in open(OUT / "events.jsonl")]
    syms = sorted({r["symbol"] for r in rows})
    rng = np.random.default_rng(SEED)
    order = list(rng.permutation(syms))
    groups = [set(order[k::GROUPS]) for k in range(GROUPS)]
    report = {}
    for cat in SCALE_M1:
        for scale in SCALES:
            R = [r for r in rows if r["category"] == cat and r["scale"] == scale]
            for fam in ("std", "half"):
                key = f"{cat}|{scale}|{fam}"
                scored, scored_ctrl, aucs = [], [], []
                for g in groups:
                    train = [r for r in R if r["symbol"] not in g and r["created_at"] < T_SPLIT]
                    test = [r for r in R if r["symbol"] in g and r["created_at"] >= T_SPLIT]
                    if len(train) < 500 or len(test) < 100:
                        continue
                    X = lambda rs: np.array([[np.nan if r.get(f) is None else r[f] for f in FEATURES] for r in rs], float)
                    Xtr, Xte = X(train), X(test)
                    ytr = np.array([r[f"{fam}_win"] for r in train], int)
                    yte = np.array([r[f"{fam}_win"] for r in test], int)
                    params = dict(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=50, l2_regularization=1.0)
                    p = HistGradientBoostingClassifier(**params, random_state=0).fit(Xtr, ytr).predict_proba(Xte)[:, 1]
                    pc = HistGradientBoostingClassifier(**params, random_state=0).fit(Xtr, rng.permutation(ytr)).predict_proba(Xte)[:, 1]
                    if len(set(yte)) > 1:
                        aucs.append(roc_auc_score(yte, p))
                    rank = np.argsort(np.argsort(-p)) / len(p)
                    rank_c = np.argsort(np.argsort(-pc)) / len(pc)
                    scored += [(rk, r) for rk, r in zip(rank, test)]
                    scored_ctrl += [(rk, r) for rk, r in zip(rank_c, test)]
                if not scored:
                    report[key] = {"skipped": f"too few events ({len(R)})"}
                    print(f"{key:36s} skipped ({len(R)} events)", flush=True)
                    continue
                res = {"events": len(R), "oos_trades": len(scored), "auc": round(float(np.mean(aucs)), 3) if aucs else None,
                       "all": _slice_stats([r for _, r in scored], fam)}
                passed = False
                for q in (0.10, 0.20, 0.30):
                    st = _slice_stats([r for rk, r in scored if rk < q], fam)
                    sc = _slice_stats([r for rk, r in scored_ctrl if rk < q], fam)
                    res[f"top{int(q * 100)}"] = st
                    res[f"control_top{int(q * 100)}"] = sc
                    if _passes(st) and not _passes(sc):
                        passed = True
                res["PASS"] = passed
                classes = {0: "FX", 1: "metals", 2: "oil", 3: "indices"}
                for q in (0.10, 0.20):
                    res[f"top{int(q * 100)}_by_class"] = {
                        classes[k]: _slice_stats([r for rk, r in scored if rk < q and r["cls"] == k], fam) for k in classes}
                    for k in classes:
                        st = res[f"top{int(q * 100)}_by_class"][classes[k]]
                        if st.get("n", 0) >= 100 and st["win"] >= 0.65 and st["net"] >= 0.20 and st["t"] >= 2:
                            res.setdefault("class_candidates", []).append(f"{classes[k]} top{int(q * 100)}")
                report[key] = res
                print(f"      top20 by class: {res['top20_by_class']}", flush=True)
                print(f"{key:36s} events={len(R):6d} oos={len(scored):5d} auc={res['auc']} all={res['all']} "
                      f"top10={res['top10']} top20={res['top20']} ctrl_top10={res['control_top10']} PASS={passed}", flush=True)
    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    {"collect": collect, "analyse": analyse}[sys.argv[1]]()
