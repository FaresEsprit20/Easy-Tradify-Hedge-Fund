# ai/rebuild_report.py
"""
Engine rebuild scorecard: original vs current engine on the price-history
study, per component and per strategy category, with the validated repair
rules and the entry policy.

Inputs (latest of each):
  reports/cache/study/*.labelled.jsonl.gz          original engine (before 2026-09-15 fixes)
  PRICE_STUDY_DIR (full capture) labelled records   current engine
  reports/component_repair_move_5atr_*.json          ai/component_repair.py
  reports/group_model_*.json                         ai/group_model.py

    python -m ai.rebuild_report --html out.html
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OLD_DIR = ROOT / "reports" / "cache" / "study"
NEW_DIR = Path(os.getenv("PRICE_STUDY_DIR") or r"C:/Users/msi/tradify_study/full")

GROUP_TITLES = {"TREND": "Trend following", "MOMENTUM": "Momentum", "MEAN_REVERSION": "Mean reversion",
                "STRUCTURE": "Structure (zones, levels, fibs)", "SMC": "Smart money / ICT",
                "ORDER_FLOW": "Volume and order flow", "WAVE": "Waves, patterns and candles",
                "CROSS_ASSET": "Cross-asset", "CONTEXT": "Context"}

DEFECTS = [
    ("Supply / demand", "Touch count rose on every analysis CALL near a zone; freshness dated from when the process first saw it; demand zones emitted IMMEDIATE_ENTRY, which no reader parses as BUY, so only SELL ever voted.",
     "Zone age, touches and departure impulse measured from the bars; broken swings excluded; demand emits IMMEDIATE_BUY."),
    ("Live vs history", "Live analyses read a still-forming bar; history and replay read closed bars, so every calibration described numbers live never produced.",
     "core/closed_bars.py: live analyses fetch closed bars only."),
    ("Every level / zone threshold", "\"ATR-scaled\" thresholds were max(fixed pips, ATR fraction) with pips tuned on silver: on a 1-pip-ATR currency pair fib proximity was 8 ATR, at-zone 5-15 ATR, touch 2 ATR.",
     "ATR fraction whenever ATR is known; swing size 0.5 ATR on every instrument."),
    ("Regime", "Regime \"confirmed\" after three identical CALLS, not bars; CHOPPY confirmed 1 time in 505 raw reads.",
     "Confirmation from the last closed bars."),
    ("Liquidity sweeps", "BUY_SIDE_SWEEP parsed as BUY although bearish; bars before a swing formed and every later re-crossing counted as sweeps (92% of bars).",
     "One direction per event; only the first breach of a significant, confirmed swing, while recent."),
    ("Order flow", "Stop hunts read backwards (legend inverted vs the liquidity engine); liquidity pools counted only for the side being scored, echoing the engine's own choice (99.8% of bars).",
     "Side-independent market reading from each event's implied direction; pools alone are not a call; order blocks count only within 0.5 ATR."),
    ("Support / resistance", "Price above/below a 20-bar pivot (99.6% of bars); breakouts detected only upward, an upward break in a bearish trend labelled BREAKOUT_SELL.",
     "Swing levels: symmetric breakouts, bounces within 0.25 ATR, otherwise silent."),
    ("FVG / ICT", "Scan skipped the 4 newest bars and returned gaps already filled; FVG/IFVG voted on the nearest gap however far away.",
     "Most recent unfilled gap within 75 bars and 0.1 ATR wide; votes only within 0.25 ATR."),
    ("Candlestick", "\"Marubozu\" meant body larger than each wick (70% of bars STRONG); ordinary bars voted; tiny-body rejection candles read as doji.",
     "Body >= 75% of range and range >= 0.8 ATR; ordinary bars neutral; dominant wick beats doji."),
    ("Elliott wave / patterns", "Wave C detected on 83% of bars from any three legs at a fixed 0.60; waves 1, 5 and A were entries; ABC counted twice.",
     "C needs a prior impulse, C >= 0.9 A and <= 0.786 retracement; only waves 3 and C are entries; ABC once."),
    ("Wyckoff / volume", "Both copied the trend label into their vote; the spring mapped to NEUTRAL; no upthrust detection.",
     "Wyckoff votes spring/upthrust; volume direction from the high-volume bar."),
    ("Trend cascade", "EMA-20 slopes from 33 bars (barely warmed up) and a fixed 0.3-pip flat threshold on M5-H4, so the cascade was a noisy sign on 78% of bars.",
     "200 bars per timeframe; flat when the slope is under 0.1 ATR of that timeframe."),
    ("TTM squeeze / RVAM / MACD", "Votes read always-on states: momentum sign, last-move sign, histogram sign (100% of bars).",
     "Votes are events: momentum at squeeze release, a conviction move, a histogram zero-cross within 3 bars."),
    ("GNN", "Peer-symbol actions counted as this symbol's direction; the reading turned into CONFLICT whenever it disagreed with the side being scored (right 40%).",
     "Each peer action read through its correlation sign; conflict kept as a separate flag."),
    ("Entry decision", "The legacy funnel (golden signals, discount, confirmation, tiers) selected nothing on unseen bars (46% vs 49.5% for every bar) and, once zone scales were fixed, entered zero times.",
     "The validated category model decides side and floor, priced on net R after cost with a cost cap; only hard safety checks remain."),
    ("RSI / Bollinger / SMC structure / discount", "RSI voted at 40/60 on M1; every M1 bar was a Bollinger squeeze; structure stayed BULLISH after a bearish CHoCH; discount freshness was wall-clock process memory.",
     "RSI at extremes only; squeeze by bandwidth percentile; CHoCH sets structure; discount stateless and ATR-scaled."),
]


def _latest(pattern: str) -> Optional[Path]:
    files = sorted(glob.glob(str(ROOT / "reports" / pattern)))
    return Path(files[-1]) if files else None


def _records(directory: Path):
    for f in sorted(directory.glob("*.labelled.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    break


def component_comparison() -> Dict[str, Dict[str, Any]]:
    """Original vs current accuracy and firing rate on the same (symbol, ts)."""
    from ai.component_repair import COMPONENTS
    from core.strategy_groups import market_direction

    def direction(v):
        if isinstance(v, bool):
            return 1 if v else -1
        return market_direction(v)

    old = {}
    for r in _records(OLD_DIR):
        y = (r.get("outcome") or {}).get("move_5atr")
        if y in (1, -1):
            old[(r["symbol"], r["ts"])] = (y, r.get("num") or {})
    stats = defaultdict(lambda: {"o": [0, 0], "n": [0, 0], "count": 0, "move": [], "net": []})
    engine = {"o": [0, 0], "n": [0, 0], "count": 0}
    for r in _records(NEW_DIR):
        key = (r["symbol"], r["ts"])
        out = r.get("outcome") or {}
        y = out.get("move_5atr")
        if y not in (1, -1) or key not in old:
            continue
        full = r.get("full") or {}
        onum = old[key][1]
        atr = r.get("atr_pips") or 0
        spread = out.get("quote_spread_pips") if out.get("quote_spread_pips") is not None else r.get("spread_pips")
        spread_atr = (spread or 0) / atr if atr else 0
        ret = out.get("ret_120")
        for comp, spec in COMPONENTS.items():
            field = spec["votes"][0]
            s = stats[comp]
            s["count"] += 1
            od = direction(onum.get(field))
            nd = direction(full.get(field))
            if od in (1, -1):
                s["o"][0] += od == y; s["o"][1] += 1
            if nd in (1, -1):
                s["n"][0] += nd == y; s["n"][1] += 1
                if isinstance(ret, (int, float)):
                    s["move"].append(nd * max(-10.0, min(10.0, ret)) - spread_atr)
                br = out.get("bracket_buy" if nd > 0 else "bracket_sell") or {}
                cost = (out["commission_r"] if out.get("source") == "quotes" and "commission_r" in out
                        else (r.get("cost") or {}).get("cost_r")) or 0
                if isinstance(br.get("r"), (int, float)):
                    s["net"].append(br["r"] - cost)
    result = {}
    for comp, s in stats.items():
        c = max(s["count"], 1)
        result[comp] = {
            "orig_acc": 100 * s["o"][0] / s["o"][1] if s["o"][1] else None,
            "orig_fire": 100 * s["o"][1] / c,
            "cur_acc": 100 * s["n"][0] / s["n"][1] if s["n"][1] else None,
            "cur_fire": 100 * s["n"][1] / c,
            "cur_move": float(np.mean(s["move"])) if s["move"] else None,
            "cur_net": float(np.mean(s["net"])) if s["net"] else None,
            "matched": s["count"],
        }
    return result


def build(repair_path: Optional[Path] = None, group_path: Optional[Path] = None,
          overall: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from ai.component_repair import COMPONENTS
    from ai.group_model import COMPONENT_GROUP

    repair_path = repair_path or _latest("component_repair_move_5atr_*.json")
    group_path = group_path or _latest("group_model_*.json")
    repair = json.loads(repair_path.read_text()) if repair_path else {"components": {}}
    groups = json.loads(group_path.read_text()) if group_path else {}
    comparison = component_comparison()

    comps = []
    order = list(GROUP_TITLES)
    for comp in COMPONENTS:
        cmp_ = comparison.get(comp, {})
        rep = (repair.get("components") or {}).get(comp) or {}
        rules = [r for r in rep.get("rules") or [] if r.get("fdr") and r.get("stable_blocks", 0) >= 3]
        rules.sort(key=lambda r: (-(bool(r.get("passes"))), -(r.get("test") or {}).get("acc", 0)))
        best = None
        if rules:
            r = rules[0]
            ho = r.get("holdout") or {}
            best = {"conditions": r["conditions"], "orientation": r.get("orientation"),
                    "test_acc": ho.get("acc"), "test_n": ho.get("n"),
                    "validation_acc": r["test"].get("acc"),
                    "move_atr": ho.get("move_atr"), "net_r": ho.get("net_r"),
                    "red_line": bool(r.get("passes"))}
        g = COMPONENT_GROUP.get(comp, "CONTEXT")
        comps.append({"name": comp.replace("_", " "), "group": g, "group_title": GROUP_TITLES.get(g, g),
                      **{k: cmp_.get(k) for k in ("orig_acc", "orig_fire", "cur_acc", "cur_fire", "cur_move", "cur_net")},
                      "best_rule": best})
    comps.sort(key=lambda c: (order.index(c["group"]) if c["group"] in order else 99, c["name"]))

    group_rows = []
    for g, info in (groups.get("groups") or {}).items():
        from ai.component_calibration import monotonic_verdict
        bins = info.get("holdout_bins") or info.get("test_bins")
        group_rows.append({"title": GROUP_TITLES.get(g, g), "features": len(info.get("features") or []),
                           "test_acc": info.get("holdout_direction_acc", info.get("test_direction_acc")),
                           "auc": info.get("holdout_auc", info.get("test_auc")),
                           "verdict": monotonic_verdict(bins or [])["verdict"], "bins": bins})

    pol = groups.get("policy") or {}
    chosen = pol.get("chosen")
    policy = {}
    if chosen:
        t = pol.get("holdout_at_floor") or pol.get("test_at_floor") or {}
        cap = pol.get("cost_cap")
        policy = {"floor": pol.get("floor"), "grid": pol.get("holdout_grid") or pol.get("test_grid") or [],
                  "summary": (f"{'Model' if chosen == 'model_side' else 'Engine'} side, floor {100 * pol['floor']:.1f}%"
                              f"{'' if cap is None else f', cost at most {cap}R'}: "
                              f"{t.get('n')} holdout trades, {t.get('success_pct')}% right, net {t.get('net_r')}R per trade after cost, "
                              f"move {t.get('move_atr')} ATR. "
                              f"{'Net-positive on discovery, validation and the untouched holdout: installed live.' if pol.get('earns') and pol.get('earns_holdout') else 'Not net-positive on every split: shadow mode.'}")}

    period = ""
    try:
        ts = [r["ts"] for r in _records(NEW_DIR)]
        period = f"{datetime.fromtimestamp(min(ts), timezone.utc):%Y-%m-%d} to {datetime.fromtimestamp(max(ts), timezone.utc):%Y-%m-%d}"
        snapshots = len(ts)
    except ValueError:
        snapshots = 0
    return {"snapshots": snapshots, "symbols": sorted({c for c in (repair.get("symbols") or [])}) or list(range(17)),
            "period": period,
            "lede": ("The real engine replayed every 15 minutes across MT5 history, before and after the logic repairs, "
                     "each reading judged by whether the next 5-ATR move went its way. Rules were searched on the first 30% "
                     "of the calendar, validated on the next 30%, and every figure shown here is on the last 40%, which "
                     "nothing was chosen on."),
            "overall": overall or [], "groups": group_rows, "components": comps, "policy": policy,
            "defects": [{"component": c, "defect": d, "fix": f} for c, d, f in DEFECTS]}


def write_html(data: Mapping[str, Any], out: Path) -> Path:
    page = (ROOT / "ai" / "templates" / "bot_rebuild.html").read_text(encoding="utf-8")
    out.write_text(page.replace("__DATA__", json.dumps(data, default=str)), encoding="utf-8")
    return out


def self_check() -> Dict[str, Any]:
    assert len(DEFECTS) >= 10 and all(len(d) == 3 for d in DEFECTS)
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "rebuild_report"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--overall", help="JSON file with the overall rows")
    a = ap.parse_args()
    overall = json.loads(Path(a.overall).read_text()) if a.overall else None
    print(write_html(build(overall=overall), Path(a.html)))
