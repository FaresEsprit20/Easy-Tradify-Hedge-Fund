"""Cross-pair rule discovery (pre-registered 2026-09-17, before any result).

Universe: 30 pairs (11 original + 19 unseen). Base setups: every category at H4/D1 with its standard exits and
ALL v2.1 rules switched off. Each setup is replayed with two exit families: 'std' (standard exits) and 'half'
(50% at +0.5R, breakeven, runner to the last target).

Procedure, per category and exit family:
  - pairs shuffled with seed 17 and split into 5 folds of 6
  - on the 24 training pairs: thresholds = training tertiles; candidate rules = keep low/mid/high tertile of a
    numeric feature, keep/drop one categorical value; a rule must keep >= 100 training trades and >= 25% of them
  - greedy: best training net-R rule, then a second rule on the survivors if it lifts training net R by >= 0.03R
  - the chosen rule(s) are applied to the 6 held-back pairs; only held-back trades are scored
PASS (per category and exit family): held-back net R > 0 with t >= 2, win rate >= 50%, and held-back net R > 0
both before 2021 and from 2021.

    python -m engine_v2.run.crosspair            # collect + validate
    python -m engine_v2.run.crosspair --analyse  # validate existing rows
"""
from __future__ import annotations

import argparse
import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from engine_v2.run.exit_lab import make_variant
from engine_v2.run.forensics import features
from engine_v2.run.replay import MODULES
from engine_v2.run.replay_history import SCALE

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "crosspair"
SPLIT_2021 = 1609459200
SEED = 17
FOLDS = 5
MIN_TRAIN_TRADES = 100
MIN_KEEP_SHARE = 0.25
SECOND_RULE_MIN_LIFT = 0.03
NUMERIC = ["room_r", "d1_range_pos", "vol_pct", "d1_trend_age", "ext_ema50", "mom20", "risk_atr", "d1_er"]
CATEGORICAL = ["session", "weekday", "htf_align", "d1_align", "side", "variant", "pool"]


def _rules_off():
    """Switch every v2.1/v3 rule off so the base setups are the textbook categories with standard exits."""
    smc = importlib.import_module("engine_v2.categories.smc")
    smc.ROOM_MIN_R, smc.SMC_POOLS, smc.PARTIAL_AT_R = -1e9, ("prior_day", "prior_week", "asia", "equal"), None
    st = importlib.import_module("engine_v2.categories.structure")
    st.VOL_PCT_LOW, st.VOL_PCT_HIGH, st.PARTIAL_AT_R = -1.0, 2.0, None
    tr = importlib.import_module("engine_v2.categories.trend")
    tr.VOL_PCT_MAX, tr.PARTIAL_AT_R = 1e9, None
    mo = importlib.import_module("engine_v2.categories.momentum")
    mo.ROOM_MIN_R, mo.EXCLUDED_SESSIONS, mo.PARTIAL_AT_R = -1e9, (), None
    wa = importlib.import_module("engine_v2.categories.wave")
    wa.WY_ENABLED, wa.NO_FRIDAY = True, False


def run_symbol(category: str, symbol: str):
    _rules_off()
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    rows = []
    for s in mod.propose(ctx, SCALE[category]):
        try:
            a = simulate(s, ctx)
            b = simulate(make_variant(s, "V3").validate(), ctx)
        except ValueError:
            continue
        if not (a.traded and b.traded):
            continue
        rows.append({"category": category, "symbol": symbol, "created_at": s.created_at,
                     "std_net": a.net_r, "std_win": a.win, "half_net": b.net_r, "half_win": b.win, **features(ctx, s)})
    return rows


def collect():
    from engine_v2.data.history import LONG_SYMBOLS, UNSEEN_SYMBOLS
    syms = LONG_SYMBOLS + UNSEEN_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    allrows = []
    with ProcessPoolExecutor(12) as ex:
        for cat in SCALE:
            rows = [r for part in ex.map(run_symbol, [cat] * len(syms), syms) for r in part]
            allrows.extend(rows)
            print(cat, len(rows), flush=True)
    with open(OUT / "rows.jsonl", "w") as f:
        for r in allrows:
            f.write(json.dumps(r) + "\n")


def _candidates(train):
    out = []
    for f in NUMERIC:
        vals = np.array([r[f] for r in train if r.get(f) is not None], float)
        if len(vals) < 3 * MIN_TRAIN_TRADES:
            continue
        q1, q2 = np.quantile(vals, [1 / 3, 2 / 3])
        out.append((f"{f} <= {q1:.3g}", lambda r, f=f, q=q1: r.get(f) is not None and r[f] <= q))
        out.append((f"{f} in ({q1:.3g}, {q2:.3g}]", lambda r, f=f, a=q1, b=q2: r.get(f) is not None and a < r[f] <= b))
        out.append((f"{f} > {q2:.3g}", lambda r, f=f, q=q2: r.get(f) is not None and r[f] > q))
        out.append((f"{f} > {q1:.3g}", lambda r, f=f, q=q1: r.get(f) is not None and r[f] > q))
        out.append((f"{f} <= {q2:.3g}", lambda r, f=f, q=q2: r.get(f) is not None and r[f] <= q))
    for f in CATEGORICAL:
        for v in sorted({r.get(f) for r in train if r.get(f) is not None}, key=str):
            out.append((f"{f} == {v}", lambda r, f=f, v=v: r.get(f) == v))
            out.append((f"{f} != {v}", lambda r, f=f, v=v: r.get(f) != v))
    return out


def _best_rule(train, key, base_n):
    base = np.mean([r[key] for r in train]) if train else -9
    best = (None, None, base)
    for name, fn in _candidates(train):
        kept = [r for r in train if fn(r)]
        if len(kept) < MIN_TRAIN_TRADES or len(kept) < MIN_KEEP_SHARE * base_n:
            continue
        m = float(np.mean([r[key] for r in kept]))
        if m > best[2]:
            best = (name, fn, m)
    return best


def _cell(g, key, win):
    if not g:
        return {"n": 0}
    net = np.array([r[key] for r in g])
    return {"n": len(g), "win": round(float(np.mean([r[win] for r in g])), 3), "net": round(float(net.mean()), 4),
            "t": round(float(net.mean() / (net.std(ddof=1) / np.sqrt(len(g)))), 2) if len(g) > 1 and net.std() > 0 else None,
            "total_r": round(float(net.sum()), 1)}


def analyse():
    rows = [json.loads(l) for l in open(OUT / "rows.jsonl")]
    report = {}
    for cat in SCALE:
        R = [r for r in rows if r["category"] == cat]
        pairs = sorted({r["symbol"] for r in R})
        rng = np.random.default_rng(SEED)
        order = list(rng.permutation(pairs))
        folds = [order[k::FOLDS] for k in range(FOLDS)]
        report[cat] = {}
        for fam in ("std", "half"):
            key, win = f"{fam}_net", f"{fam}_win"
            held, base_held, chosen = [], [], []
            for test_pairs in folds:
                train = [r for r in R if r["symbol"] not in test_pairs]
                test = [r for r in R if r["symbol"] in test_pairs]
                base_held.extend(test)
                n1, f1, m1 = _best_rule(train, key, len(train))
                rules = []
                if f1 is not None:
                    rules.append((n1, f1))
                    sub = [r for r in train if f1(r)]
                    n2, f2, m2 = _best_rule(sub, key, len(train))
                    if f2 is not None and m2 - m1 >= SECOND_RULE_MIN_LIFT:
                        rules.append((n2, f2))
                chosen.append([n for n, _ in rules])
                held.extend([r for r in test if all(fn(r) for _, fn in rules)])
            res = {"base_held_out": _cell(base_held, key, win), "rules_held_out": _cell(held, key, win),
                   "rules_held_out_pre2021": _cell([r for r in held if r["created_at"] < SPLIT_2021], key, win),
                   "rules_held_out_2021on": _cell([r for r in held if r["created_at"] >= SPLIT_2021], key, win),
                   "rules_by_fold": chosen}
            c, a, b = res["rules_held_out"], res["rules_held_out_pre2021"], res["rules_held_out_2021on"]
            res["PASS"] = bool(c.get("n") and c["net"] > 0 and (c["t"] or 0) >= 2 and c["win"] >= 0.5
                               and a.get("n") and a["net"] > 0 and b.get("n") and b["net"] > 0)
            report[cat][fam] = res
            print(f"{cat:15s} {fam:4s} base held-out {res['base_held_out']} | rules held-out {c} | pre2021 {a.get('net')} n={a.get('n')} | 2021+ {b.get('net')} n={b.get('n')} | PASS={res['PASS']}")
            print(f"      rules chosen per fold: {chosen}")
    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyse", action="store_true")
    args = ap.parse_args()
    if not args.analyse:
        collect()
    analyse()


if __name__ == "__main__":
    main()
