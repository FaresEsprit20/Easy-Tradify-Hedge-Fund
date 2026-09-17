"""M1 lab (pre-registered 2026-09-17): every category rebuilt at M1 scale on true bid/ask M1 data.

Scale: SMC setup M1 / context M15; STRUCTURE zones M5 / trigger M1; TREND impulse M5 / context M15 / trigger M1;
MOMENTUM setup M1 / ER M15; MEAN_REVERSION setup M1 / ER M15; WAVE patterns M5 / trigger M1. All H4/D1 v2.1/v3 rules
off. Exit families per setup: std (standard exits), half (50% at +0.5R, breakeven), runner (breakeven at +1R,
chandelier(22,3) trail on the setup timeframe).
Data: engine_v2/data/replay.py (MT5 tick bars 2026-05-25 -> 2026-09-15 for 17 symbols, Dukascopy bid/ask M1 before).
Periods: discovery < 2026-06-15 <= holdout.
PASS (user target): win rate >= 65% AND net R per trade >= +0.20 with t >= 2, on discovery AND on holdout.

    python -m engine_v2.run.m1_lab
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.run.exit_lab import make_variant
from engine_v2.run.replay import HOLDOUT_START, MODULES

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "m1"
SCALE_M1 = {
    "SMC": {"setup": "M1", "context": "M15"},
    "STRUCTURE": {"zone": "M5", "trigger": "M1", "context": "M15"},
    "TREND": {"impulse": "M5", "context": "M15", "trigger": "M1"},
    "MOMENTUM": {"setup": "M1", "er": "M15", "context": "M15"},
    "MEAN_REVERSION": {"setup": "M1", "er": "M15", "context": "M15"},
    "WAVE": {"pattern": "M5", "trigger": "M1", "context": "M15"},
}
FAMILIES = ("std", "half", "runner")


def _runner(s):
    d = s.direction
    e = float(s.entry["price"])
    risk = (e - float(s.stop["price"])) * d
    return replace(s, targets=[{"price": e + d * 100.0 * risk, "share": 1.0, "reason": "runner"}],
                   management={"breakeven_after_target": None, "breakeven_at_r": 1.0, "time_stop_bars": 240},
                   thesis=[t for t in s.thesis if t.get("applies_to") == "pending"] +
                          [{"type": "close_beyond_series", "tf": s.timeframe,
                            "series": "chandelier_long_22_3" if d > 0 else "chandelier_short_22_3",
                            "beyond": "below" if d > 0 else "above", "applies_to": "open"}])


def run_symbol(category: str, symbol: str):
    from engine_v2.data.replay import load_m1
    from engine_v2.market_model.context import Context
    from engine_v2.run.crosspair import _rules_off
    from engine_v2.sim.outcome import simulate
    _rules_off()
    mod = importlib.import_module(f"engine_v2.categories.{MODULES[category]}")
    ctx = Context(symbol, load_m1(symbol))
    rows = []
    for s in mod.propose(ctx, SCALE_M1[category]):
        rec = {"category": category, "variant": s.variant, "symbol": symbol, "side": s.side,
               "created_at": s.created_at, "period": "holdout" if s.created_at >= HOLDOUT_START else "discovery",
               "risk_atr": s.context.get("risk_atr"), "session": s.context.get("session")}
        ok = True
        for fam, build in (("std", lambda x: x), ("half", lambda x: make_variant(x, "V3")), ("runner", _runner)):
            try:
                o = simulate(build(s).validate(), ctx)
            except ValueError:
                ok = False
                break
            if not o.traded:
                ok = False
                break
            rec[fam] = {"net": o.net_r, "gross": o.gross_r, "comm": o.commission_r, "win": o.win,
                        "hold_min": (o.exit_time - o.fill_time) / 60}
        if ok:
            rows.append(rec)
    return rows


def _cell(g, fam):
    if not g:
        return {"n": 0}
    net = np.array([r[fam]["net"] for r in g])
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 1 and net.std() > 0 else 0.0
    return {"n": len(g), "win": round(float(np.mean([r[fam]["win"] for r in g])), 3), "net": round(float(net.mean()), 3),
            "t": round(t, 1), "gross": round(float(np.mean([r[fam]["gross"] for r in g])), 3),
            "comm": round(float(np.mean([r[fam]["comm"] for r in g])), 3),
            "hold_min": round(float(np.median([r[fam]["hold_min"] for r in g])), 0)}


def main():
    from engine_v2.data.replay import available_symbols
    syms = available_symbols()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    with ProcessPoolExecutor(12) as ex:
        for cat in SCALE_M1:
            rows = [r for part in ex.map(run_symbol, [cat] * len(syms), syms) for r in part]
            with open(OUT / f"{cat.lower()}_rows.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            report[cat] = {}
            for fam in FAMILIES:
                d = _cell([r for r in rows if r["period"] == "discovery"], fam)
                h = _cell([r for r in rows if r["period"] == "holdout"], fam)
                passed = all(c.get("n", 0) > 0 and c["win"] >= 0.65 and c["net"] >= 0.20 and c["t"] >= 2 for c in (d, h))
                report[cat][fam] = {"discovery": d, "holdout": h, "PASS": passed}
                print(f"{cat:15s} {fam:6s} disc {d} | hold {h} | PASS={passed}", flush=True)
    (OUT / "summary.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
