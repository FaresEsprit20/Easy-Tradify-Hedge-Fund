"""Rule forensics: what was true at entry for winners vs losers, per category (16-year H4/D1 replay).

For every setup it records the market state at the trigger close, replays it with the category's standard
exits, then for each feature finds the best tertile on DISCOVERY (2010-2020) only and reports how that
same rule does on HOLDOUT (2021-2026). A rule is 'confirmed' when the holdout agrees in direction.

    python -m engine_v2.run.forensics            # collect + analyse
    python -m engine_v2.run.forensics --analyse  # analyse existing rows
"""
from __future__ import annotations

import argparse
import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from engine_v2.run.replay import MODULES
from engine_v2.run.replay_history import HOLDOUT, SCALE, standard_exits

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "forensics"
MIN_BIN = 40
NUMERIC = ["d1_er", "vol_pct", "d1_range_pos", "ext_ema50", "mom20", "room_r", "risk_atr", "hour", "d1_trend_age"]
CATEGORICAL = ["d1_align", "htf_align", "session", "side", "variant", "weekday", "pool", "others_agree"]


def features(ctx, s) -> dict:
    t = s.created_at
    d = s.direction
    tf = s.timeframe
    b = ctx.bars(tf)
    i = ctx.last_closed_index(tf, t)
    atr = ctx.atr(tf)
    a = float(atr[i]) if i >= 0 else np.nan
    entry = float(s.entry["price"])
    risk = abs(entry - float(s.stop["price"]))
    out = {"side": s.side, "variant": s.variant, "hour": int((t % 86400) // 3600),
           "weekday": int((t // 86400 + 3) % 7), "risk_atr": risk / a if a > 0 else None,
           "session": s.context.get("session"), "pool": s.context.get("pool")}
    h = s.context.get("htf_trend", s.context.get("h4_trend"))
    out["htf_align"] = "aligned" if h == d else ("against" if h == -d else "neutral")
    j = ctx.last_closed_index("D1", t)
    d1 = ctx.bars("D1")
    if j >= 20:
        tr = ctx.trend("D1")
        out["d1_align"] = "aligned" if tr[j] == d else ("against" if tr[j] == -d else "neutral")
        k = j
        while k > 0 and tr[k - 1] == tr[j]:
            k -= 1
        out["d1_trend_age"] = j - k
        er = ctx.efficiency_ratio("D1")[j]
        out["d1_er"] = float(er) if np.isfinite(er) else None
        hi, lo = float(d1.high[j - 19:j + 1].max()), float(d1.low[j - 19:j + 1].min())
        pos = (entry - lo) / (hi - lo) if hi > lo else 0.5
        out["d1_range_pos"] = pos if d > 0 else 1 - pos          # 0 = best price for the side (discount)
        sw = ctx.swings("D1")
        known = sw.available_idx <= j
        lv = sw.price[known & (sw.kind == (1 if d > 0 else -1))]
        beyond = lv[(lv - entry) * d > 0]
        room = (beyond.min() - entry if d > 0 else entry - beyond.max()) if len(beyond) else np.nan
        out["room_r"] = float(min(room / risk, 10.0)) if risk > 0 and np.isfinite(room) else 10.0
    if i >= 250 and a > 0:
        out["vol_pct"] = float((atr[i - 250:i + 1] < a).mean())
        ema50 = ctx.ema(tf, 50)
        out["ext_ema50"] = float((b.close[i] - ema50[i]) * d / a) if np.isfinite(ema50[i]) else None
        out["mom20"] = float((b.close[i] - b.close[i - 20]) * d / a)
    return out


def run_symbol_v3(category: str, symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.run.replay_history import HOLDOUT as H
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    rows = []
    for s in mod.propose(ctx):
        o = simulate(s, ctx)
        if not o.traded:
            continue
        rows.append({"category": category, "symbol": symbol, "created_at": s.created_at,
                     "period": "holdout" if s.created_at >= H else "discovery",
                     "net_r": o.net_r, "win": o.win, "mfe_r": o.mfe_r, "mae_r": o.mae_r,
                     "targets_hit": o.targets_hit, "exit": o.exit_reason, **features(ctx, s)})
    return rows


def run_symbol(category: str, symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.sim.outcome import simulate
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_h1(symbol))
    tfs = SCALE[category]
    rows = []
    for s in mod.propose(ctx, tfs):
        try:
            o = simulate(standard_exits(category, s, ctx, tfs).validate(), ctx)
        except ValueError:
            continue
        if not o.traded:
            continue
        rows.append({"category": category, "symbol": symbol, "created_at": s.created_at,
                     "period": "holdout" if s.created_at >= HOLDOUT else "discovery",
                     "net_r": o.net_r, "win": o.win, "mfe_r": o.mfe_r, "mae_r": o.mae_r,
                     "targets_hit": o.targets_hit, "exit": o.exit_reason, **features(ctx, s)})
    return rows


def collect():
    from engine_v2.data.history import LONG_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    allrows = []
    with ProcessPoolExecutor(11) as ex:
        for cat in SCALE:
            rows = [r for part in ex.map(run_symbol, [cat] * len(LONG_SYMBOLS), LONG_SYMBOLS) for r in part]
            allrows.extend(rows)
            print(cat, len(rows), flush=True)
    # cross-category agreement: another category, same symbol and side, created within the previous 3 days
    by = {}
    for r in allrows:
        by.setdefault((r["symbol"], r["side"]), []).append(r)
    for r in allrows:
        others = {o["category"] for o in by[(r["symbol"], r["side"])]
                  if o["category"] != r["category"] and 0 <= r["created_at"] - o["created_at"] <= 3 * 86400}
        r["others_agree"] = "yes" if others else "no"
    with open(OUT / "rows.jsonl", "w") as f:
        for r in allrows:
            f.write(json.dumps(r) + "\n")


def _cell(g):
    if not g:
        return {"n": 0, "win": None, "net": None}
    return {"n": len(g), "win": round(float(np.mean([x["win"] for x in g])), 3),
            "net": round(float(np.mean([x["net_r"] for x in g])), 3)}


def analyse():
    rows = [json.loads(l) for l in open(OUT / "rows.jsonl")]
    report = {}
    for cat in SCALE:
        R = [r for r in rows if r["category"] == cat]
        disc = [r for r in R if r["period"] == "discovery"]
        hold = [r for r in R if r["period"] == "holdout"]
        base = {"discovery": _cell(disc), "holdout": _cell(hold)}
        rules = []
        for f in NUMERIC:
            vals = np.array([r.get(f) for r in disc if r.get(f) is not None], dtype=float)
            if len(vals) < 3 * MIN_BIN:
                continue
            q1, q2 = np.quantile(vals, [1 / 3, 2 / 3])
            bins = {"low": lambda v: v <= q1, "mid": lambda v: q1 < v <= q2, "high": lambda v: v > q2}
            for name, fn in bins.items():
                gd = [r for r in disc if r.get(f) is not None and fn(r[f])]
                gh = [r for r in hold if r.get(f) is not None and fn(r[f])]
                if len(gd) >= MIN_BIN and len(gh) >= MIN_BIN // 2:
                    rules.append({"rule": f"{f} {name} ({'<=' + format(q1, '.3g') if name == 'low' else format(q1, '.3g') + '..' + format(q2, '.3g') if name == 'mid' else '>' + format(q2, '.3g')})",
                                  "discovery": _cell(gd), "holdout": _cell(gh)})
        for f in CATEGORICAL:
            for v in sorted({r.get(f) for r in disc if r.get(f) is not None}, key=str):
                gd = [r for r in disc if r.get(f) == v]
                gh = [r for r in hold if r.get(f) == v]
                if len(gd) >= MIN_BIN and len(gh) >= MIN_BIN // 2:
                    rules.append({"rule": f"{f} = {v}", "discovery": _cell(gd), "holdout": _cell(gh)})
        for r in rules:
            r["disc_lift"] = round(r["discovery"]["net"] - base["discovery"]["net"], 3)
            r["hold_lift"] = round(r["holdout"]["net"] - base["holdout"]["net"], 3)
            r["confirmed"] = r["disc_lift"] > 0.05 and r["hold_lift"] > 0.0
        rules.sort(key=lambda r: -r["disc_lift"])
        # combine the 3 best DISCOVERY rules on different features, judge on holdout
        chosen, feats = [], set()
        for r in rules:
            feat = r["rule"].split(" ")[0]
            if r["disc_lift"] > 0.05 and feat not in feats:
                chosen.append(r["rule"]); feats.add(feat)
            if len(chosen) == 3:
                break
        report[cat] = {"base": base, "top_rules": rules[:12], "worst_rules": rules[-5:], "combined_rules": chosen}
    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))
    for cat, rep in report.items():
        print(f"\n=== {cat}  base discovery {rep['base']['discovery']}  holdout {rep['base']['holdout']}")
        for r in rep["top_rules"]:
            flag = "CONFIRMED" if r["confirmed"] else ""
            print(f"  + {r['rule']:38s} disc n={r['discovery']['n']:4d} win={r['discovery']['win']} net={r['discovery']['net']:+.3f} | hold n={r['holdout']['n']:4d} win={r['holdout']['win']} net={r['holdout']['net']:+.3f} {flag}")
        for r in rep["worst_rules"]:
            print(f"  - {r['rule']:38s} disc n={r['discovery']['n']:4d} win={r['discovery']['win']} net={r['discovery']['net']:+.3f} | hold n={r['holdout']['n']:4d} win={r['holdout']['win']} net={r['holdout']['net']:+.3f}")


def collect_v3(symbols=None, out_name="rows_v3.jsonl"):
    from engine_v2.data.history import LONG_SYMBOLS
    symbols = symbols or LONG_SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    allrows = []
    with ProcessPoolExecutor(11) as ex:
        for cat in ("SMC", "STRUCTURE", "TREND", "MOMENTUM", "MEAN_REVERSION", "WAVE"):
            rows = [r for part in ex.map(run_symbol_v3, [cat] * len(symbols), symbols) for r in part]
            allrows.extend(rows)
            print(cat, len(rows), flush=True)
    with open(OUT / out_name, "w") as f:
        for r in allrows:
            f.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--v3", action="store_true")
    args = ap.parse_args()
    if args.v3:
        collect_v3()
        return
    if not args.analyse:
        collect()
    analyse()


if __name__ == "__main__":
    main()
