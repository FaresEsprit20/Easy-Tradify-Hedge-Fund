"""High-expectancy lab (pre-registered 2026-09-17, before any result).

Strategies
  A. TREND D1 trend following (engine_v2/categories/trend_d1.py): donchian_55_20, donchian_55_chand.
     One position per symbol and variant: a signal is skipped while the previous trade of that variant is open.
  B. Runner exits on the existing categories (base setups, every v2.1/v3 rule off): no fixed target,
     breakeven at +1R, then exit on a chandelier(22, 3) close of the setup timeframe; 120-day time stop.
Costs: bid/ask fills, commission, overnight swap (triple Wednesday).
Symbols: pairs with >= 7 years of H1 history (11 original + CHFJPY EURAUD EURCHF EURNZD EURCAD).
PASS: net R per trade >= +0.20 with t >= 2, net R > 0 both before 2021 and from 2021, and positive on >= 60% of the
symbols that traded.

    python -m engine_v2.run.expectancy_lab
"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from engine_v2.data.clock import TF_SECONDS
from engine_v2.run.replay import MODULES
from engine_v2.run.replay_history import SCALE

OUT = Path(__file__).resolve().parents[2] / "reports" / "v2" / "expectancy"
SPLIT_2021 = 1609459200
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY", "XAUUSD", "XAGUSD",
           "CHFJPY", "EURAUD", "EURCHF", "EURNZD", "EURCAD"]
RUNNER_CATEGORIES = ("SMC", "STRUCTURE", "TREND", "MOMENTUM", "WAVE")


def _runner(s):
    d = s.direction
    e = float(s.entry["price"])
    risk = (e - float(s.stop["price"])) * d
    tf = s.timeframe
    return replace(s, targets=[{"price": e + d * 100.0 * risk, "share": 1.0, "reason": "runner"}],
                   management={"breakeven_after_target": None, "breakeven_at_r": 1.0,
                               "time_stop_bars": int(120 * 86400 // TF_SECONDS[tf])},
                   thesis=[t for t in s.thesis if t.get("applies_to") == "pending"] +
                          [{"type": "close_beyond_series", "tf": tf,
                            "series": "chandelier_long_22_3" if d > 0 else "chandelier_short_22_3",
                            "beyond": "below" if d > 0 else "above", "applies_to": "open"}])


def _row(name, symbol, s, o):
    return {"strategy": name, "symbol": symbol, "side": s.side, "created_at": s.created_at, "exit_time": o.exit_time,
            "net_r": o.net_r, "gross_r": o.gross_r, "commission_r": o.commission_r, "swap_r": o.swap_r,
            "win": o.win, "mfe_r": o.mfe_r, "hold_days": (o.exit_time - o.fill_time) / 86400, "exit": o.exit_reason}


def run_symbol(symbol: str):
    from engine_v2.data.history import load_h1
    from engine_v2.market_model.context import Context
    from engine_v2.run.crosspair import _rules_off
    from engine_v2.sim.outcome import simulate
    ctx = Context(symbol, load_h1(symbol))
    rows = []
    trend_d1 = importlib.import_module("engine_v2.categories.trend_d1")
    busy_until: dict[str, int] = {}
    for s in sorted(trend_d1.propose(ctx), key=lambda x: x.created_at):
        name = f"D1_TREND:{s.variant}"
        if s.created_at < busy_until.get(name, 0):
            continue
        o = simulate(s, ctx)
        if o.traded:
            busy_until[name] = o.exit_time
            rows.append(_row(name, symbol, s, o))
    _rules_off()
    for cat in RUNNER_CATEGORIES:
        mod = importlib.import_module(f"engine_v2.categories.{MODULES[cat]}")
        for s in mod.propose(ctx, SCALE[cat]):
            try:
                o = simulate(_runner(s).validate(), ctx)
            except ValueError:
                continue
            if o.traded:
                rows.append(_row(f"RUNNER:{cat}", symbol, s, o))
    return rows


def _summary(g):
    net = np.array([r["net_r"] for r in g])
    by_sym = {}
    for r in g:
        by_sym.setdefault(r["symbol"], []).append(r["net_r"])
    pre = [r["net_r"] for r in g if r["created_at"] < SPLIT_2021]
    post = [r["net_r"] for r in g if r["created_at"] >= SPLIT_2021]
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 1 and net.std() > 0 else 0.0
    res = {"trades": len(g), "win_rate": round(float(np.mean([r["win"] for r in g])), 3), "net_r": round(float(net.mean()), 3),
           "t": round(t, 2), "gross_r": round(float(np.mean([r["gross_r"] for r in g])), 3),
           "commission_r": round(float(np.mean([r["commission_r"] for r in g])), 3),
           "swap_r": round(float(np.mean([r["swap_r"] for r in g])), 3),
           "avg_win_r": round(float(np.mean([r["net_r"] for r in g if r["win"]])), 2) if any(r["win"] for r in g) else None,
           "avg_loss_r": round(float(np.mean([r["net_r"] for r in g if not r["win"]])), 2) if not all(r["win"] for r in g) else None,
           "hold_days_median": round(float(np.median([r["hold_days"] for r in g])), 1),
           "pre2021_net": round(float(np.mean(pre)), 3) if pre else None, "pre2021_n": len(pre),
           "from2021_net": round(float(np.mean(post)), 3) if post else None, "from2021_n": len(post),
           "symbols_positive": f"{sum(1 for v in by_sym.values() if np.mean(v) > 0)}/{len(by_sym)}",
           "total_r": round(float(net.sum()), 1)}
    pos_share = sum(1 for v in by_sym.values() if np.mean(v) > 0) / max(len(by_sym), 1)
    res["PASS"] = bool(res["net_r"] >= 0.20 and t >= 2 and (res["pre2021_net"] or 0) > 0 and (res["from2021_net"] or 0) > 0
                       and pos_share >= 0.6)
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(12) as ex:
        rows = [r for part in ex.map(run_symbol, SYMBOLS) for r in part]
    with open(OUT / "rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    report = {}
    for name in sorted({r["strategy"] for r in rows}):
        report[name] = _summary([r for r in rows if r["strategy"] == name])
        print(f"{name:28s} {report[name]}", flush=True)
    (OUT / "summary.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
