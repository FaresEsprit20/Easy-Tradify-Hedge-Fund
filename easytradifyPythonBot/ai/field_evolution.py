# ai/field_evolution.py
"""
Field evolution: how every field of a strategy group changes from one update
to the next, whether each change was TRUE, whether it REVERSES, and what the
other fields looked like when it succeeded or failed.

The study captures the real engine every 15 minutes (ai/price_history_study.py,
full leaves) and labels each snapshot with the live trade on tick quotes: the
market stop (core/market_stop.py) for BUY and for SELL, which side reached its
target (y_ms) and the net R of each side. For one group (SMC, WAVE, TREND,
MEAN_REVERSION, ...) this walks consecutive snapshots of each symbol and, for
every field of the group's components:

  transition     the value it had -> the value it has now (text states, counts
                 and flags as they are; continuous numbers as quintile bins);
                 "(none)" when the field is absent
  truth          after the change, how often the BUY trade won and how often
                 the SELL trade won, and the net R of each. The side a change
                 means is learned on discovery data, not assumed from its name
                 (BUY_SIDE_SWEEP is bearish; a new equal-lows pool has no name)
  reversal       how often the field returns to its old value within 1 hour,
                 and how the change's side did when it did / did not
  confirmation   entering 15, 30 or 60 minutes later, only if the new value is
                 still there -- a tradable way to use "it did not reverse"
  why            beam-searched conditions on every group field and the edge
                 features AT the change (ai/component_repair.search_rules) that
                 separate the changes that won from those that failed

Every number is given for discovery / validation / holdout
(ai/component_repair.study_split); choices are made on discovery only, the
holdout is reported, never used.

    python -m ai.field_evolution --group SMC
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

STEP_SECONDS = 900
REVERSAL_STEPS = 4            # 1 hour of 15-minute updates
CONFIRM_STEPS = (1, 2, 4)
MAX_STATES = 30               # a text field with more distinct values is an id/level, not a state
NUMERIC_BINS = 5
MIN_EVENTS_TRAIN = 150
MIN_EVENTS_TEST = 60
MAX_RULE_SEARCHES = 60
TARGET_WIN = 65.0
TARGET_NET_R = 0.2
NONE = "(none)"


# ============================================================
# DATA
# ============================================================

class Evolution:
    """Column store view with, per row, the previous and the next rows of the
    same symbol, and the live market-stop trade outcome."""

    def __init__(self):
        from ai.component_repair import Columns, study_split

        c = self.cols = Columns()
        self.n = c.n
        self.ts = c.num("ts").astype(np.float64)
        codes, vocab = c.text("ctx.symbol")
        self.symbol = np.array([vocab[k] if k >= 0 else "" for k in codes], dtype=object)
        step = np.round(self.ts / STEP_SECONDS).astype(np.int64)
        index = {(s, t): i for i, (s, t) in enumerate(zip(self.symbol, step))}

        def shifted(k):
            return np.array([index.get((s, t + k), -1) for s, t in zip(self.symbol, step)], dtype=np.int64)

        self.prev = shifted(-1)
        self.ahead = {k: shifted(k) for k in range(1, REVERSAL_STEPS + 1)}
        self.train, self.test, self.holdout, self.blocks, self.holdout_start = study_split(self.ts)
        self.y = c.num("y_ms").astype(np.float64)
        cost = np.nan_to_num(c.num("ms_cost_r").astype(np.float64), nan=0.0)
        self.net = {1: c.num("br_ms_buy").astype(np.float64) - cost, -1: c.num("br_ms_sell").astype(np.float64) - cost}
        self.labelled = ~np.isnan(self.y) & ~np.isnan(self.net[1]) & ~np.isnan(self.net[-1])
        self.clusters = np.array([f"{s}|{int(t // 86400)}" for s, t in zip(self.symbol, self.ts)], dtype=object)
        self.close = c.num("close").astype(np.float64)
        atr = c.num("atr_pips").astype(np.float64) * c.num("pip").astype(np.float64)
        self.atr_price = np.where(atr > 0, atr, np.nan)

    def states(self, field: str) -> Optional[np.ndarray]:
        """Integer state per row (-1 = absent) and the state names."""
        c = self.cols
        if c.kind(field) == "text":
            codes, vocab = c.text(field)
            if len(vocab) > MAX_STATES:
                return None
            return codes.astype(np.int64), list(vocab)
        from ai.component_repair import _price_like

        v = c.num(field).astype(np.float64)
        unit = ""
        if _price_like(v, self.close):
            # an absolute price means nothing across symbols and days: its
            # distance from price, in ATR, is the state
            v = (v - self.close) / self.atr_price
            unit = " ATR from price"
        present = ~np.isnan(v)
        if present.sum() < MIN_EVENTS_TRAIN:
            return None
        uniq = np.unique(v[present])
        if uniq.size <= MAX_STATES and not unit:
            lut = {u: i for i, u in enumerate(uniq)}
            out = np.full(self.n, -1, dtype=np.int64)
            out[present] = [lut[x] for x in v[present]]
            return out, [f"{u:g}" for u in uniq]
        edges = np.unique(np.quantile(v[present & self.train], np.linspace(0, 1, NUMERIC_BINS + 1)[1:-1]))
        out = np.full(self.n, -1, dtype=np.int64)
        out[present] = np.searchsorted(edges, v[present], side="right")
        if edges.size == 0:
            return None
        names = [f"<= {edges[0]:.4g}"] + [f"{a:.4g}..{b:.4g}" for a, b in zip(edges[:-1], edges[1:])] + [f"> {edges[-1]:.4g}"]
        return out, [n + unit for n in names]


def group_fields(cols, group: str) -> List[str]:
    from ai.component_repair import COMPONENTS
    from ai.group_model import COMPONENT_GROUP

    prefixes = [p for comp, g in COMPONENT_GROUP.items() if g == group for p in COMPONENTS[comp]["fields"]]
    skip = ("note", "reason", "description", "timestamp", "time", "_ts", "bar_index", "sweep_bar_index")
    return [f for f in cols.names() if f.startswith(tuple(prefixes)) and not any(s in f.lower() for s in skip)]


# ============================================================
# MEASURES
# ============================================================

def _stats(ev: Evolution, rows: np.ndarray, side: int) -> Dict[str, Any]:
    """Win % and net R of `side`'s trade at `rows`, day-clustered z."""
    from ai.component_calibration import cluster_mean_z

    rows = rows[ev.labelled[rows]]
    if rows.size == 0:
        return {"n": 0}
    mask = np.zeros(ev.n, bool)
    mask[rows] = True
    win = np.where(mask, (ev.y == side).astype(float), np.nan)
    net = np.where(mask, ev.net[side], np.nan)
    w, wz, days = cluster_mean_z(win, ev.clusters, null=float(np.mean(ev.y[ev.labelled & ev.train] == side)))
    r, rz, _ = cluster_mean_z(net, ev.clusters, null=0.0)
    return {"n": int(rows.size), "days": int(days), "win": round(100 * w, 1), "win_z": round(wz, 2),
            "net_r": round(r, 3), "net_z": round(rz, 2)}


def _periods(ev: Evolution, rows: np.ndarray, side: int) -> Dict[str, Any]:
    return {name: _stats(ev, rows[period[rows]], side)
            for name, period in (("discovery", ev.train), ("validation", ev.test), ("holdout", ev.holdout))}


def transitions(ev: Evolution, field: str) -> List[Dict[str, Any]]:
    got = ev.states(field)
    if got is None:
        return []
    state, names = got
    has_prev = ev.prev >= 0
    before = np.where(has_prev, state[np.maximum(ev.prev, 0)], -2)
    changed = has_prev & (before != state)
    label = lambda k: NONE if k == -1 else names[k]
    pairs = defaultdict(list)
    for i in np.flatnonzero(changed):
        pairs[(int(before[i]), int(state[i]))].append(i)
    out = []
    for (a, b), rows in pairs.items():
        rows = np.asarray(rows, dtype=np.int64)
        if (ev.train[rows] & ev.labelled[rows]).sum() < MIN_EVENTS_TRAIN:
            continue
        # the side this change means, learned on discovery only
        disc = rows[ev.train[rows] & ev.labelled[rows]]
        side = 1 if ev.net[1][disc].mean() >= ev.net[-1][disc].mean() else -1
        item = {"field": field, "from": label(a), "to": label(b), "side": "BUY" if side > 0 else "SELL",
                "at_change": _periods(ev, rows, side)}
        # reversal: back to the old value within the hour. Only between two
        # real states -- a field returning to "(none)" is usually an event
        # ageing out of its lookback, not the market reversing it.
        if a >= 0 and b >= 0:
            back = np.zeros(rows.size, bool)
            for k in range(1, REVERSAL_STEPS + 1):
                j = ev.ahead[k][rows]
                back |= (j >= 0) & (state[np.maximum(j, 0)] == a)
            item["reversal_1h_pct"] = round(100 * back.mean(), 1)
            item["when_reversed"] = _periods(ev, rows[back], side)
            item["when_held"] = _periods(ev, rows[~back], side)
        else:
            item["reversal_1h_pct"] = None
        # confirmation entries: still the new value k updates later, enter there
        conf = {}
        for k in CONFIRM_STEPS:
            held = np.ones(rows.size, bool)
            for s in range(1, k + 1):
                j = ev.ahead[s][rows]
                held &= (j >= 0) & (state[np.maximum(j, 0)] == b)
            entry = ev.ahead[k][rows][held]
            conf[f"{15 * k}m"] = _periods(ev, entry, side)
        item["confirmed_entry"] = conf
        item["_rows"] = rows
        item["_side"] = side
        out.append(item)
    return out


def why(ev: Evolution, item: Mapping[str, Any], fields: Sequence[str]) -> List[Dict[str, Any]]:
    """Conditions at the change that separate the wins from the failures."""
    from ai.component_repair import CONTEXT_PREFIXES, evaluate, literals_for, search_rules

    rows, side = item["_rows"], item["_side"]
    at = np.zeros(ev.n, bool)
    at[rows] = True
    votes = np.where(at, float(side), np.nan)
    y = np.where(ev.labelled, ev.y, np.nan)
    net = np.where(at, ev.net[side], np.nan)
    c = ev.cols
    close = c.num("close").astype(np.float64)
    atr_price = c.num("atr_pips").astype(np.float64) * c.num("pip").astype(np.float64)
    atr_price = np.where(atr_price > 0, atr_price, np.nan)
    context = [f for f in c.names() if f.startswith(CONTEXT_PREFIXES) and f != "ctx.symbol"]
    literals = literals_for(c, list(fields) + context, at, ev.train & at, close, atr_price)
    out = []
    for rule in search_rules(votes, y, net, ev.train, literals)[:5]:
        mask = rule.pop("_mask")
        rule["validation"] = evaluate(mask, votes, y, net, ev.test, ev.clusters)
        rule["holdout"] = evaluate(mask, votes, y, net, ev.holdout, ev.clusters)
        rule["blocks"] = [evaluate(mask, votes, y, net, b, ev.clusters).get("acc") for b in ev.blocks]
        out.append(rule)
    return out


def five_star(p: Mapping[str, Any]) -> bool:
    """The user's line, on BOTH unseen periods: >= 65% win and >= +0.2R."""
    return all((p.get(k) or {}).get("n", 0) >= MIN_EVENTS_TEST
               and ((p.get(k) or {}).get("win") or 0) >= TARGET_WIN
               and ((p.get(k) or {}).get("net_r") or -9) >= TARGET_NET_R for k in ("validation", "holdout"))


# ============================================================
# RUN
# ============================================================

def run(group: str) -> Dict[str, Any]:
    ev = Evolution()
    fields = group_fields(ev.cols, group)
    items: List[Dict[str, Any]] = []
    for f in fields:
        items.extend(transitions(ev, f))
    print(group, "fields", len(fields), "transitions", len(items), flush=True)

    def disc_score(it):
        d = it["at_change"]["discovery"]
        return d.get("win_z") or 0.0

    items.sort(key=lambda it: -disc_score(it))
    for it in items[:MAX_RULE_SEARCHES]:
        it["why"] = why(ev, it, fields)
    found = []
    for it in items:
        candidates = [("at_change", it["at_change"])] + [(f"confirmed_{k}", v) for k, v in it["confirmed_entry"].items()]
        candidates += [("when " + " & ".join(r["conditions"]), {"validation": _as_period(r["validation"]),
                                                              "holdout": _as_period(r["holdout"])})
                       for r in it.get("why", [])]
        for how, p in candidates:
            if five_star(p):
                found.append({"field": it["field"], "from": it["from"], "to": it["to"], "side": it["side"], "how": how,
                              "validation": p["validation"], "holdout": p["holdout"]})
        it.pop("_rows", None)
        it.pop("_side", None)
    return {"group": group, "rows": ev.n, "holdout_start": ev.holdout_start, "fields": len(fields),
            "transitions": items, "five_star": found}


def _as_period(e: Mapping[str, Any]) -> Dict[str, Any]:
    return {"n": e.get("n", 0), "win": e.get("acc"), "net_r": e.get("net_r")}


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def self_check() -> Dict[str, Any]:
    good = {"n": 100, "win": 70.0, "net_r": 0.3}
    assert five_star({"validation": good, "holdout": good})
    assert not five_star({"validation": good, "holdout": {**good, "win": 60.0}})     # both unseen periods
    assert not five_star({"validation": good, "holdout": {**good, "net_r": 0.1}})    # expectancy too
    assert not five_star({"validation": good, "holdout": {**good, "n": 10}})         # support
    assert not five_star({"validation": good})
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "field_evolution", "reversal_steps": REVERSAL_STEPS, "confirm_steps": list(CONFIRM_STEPS),
            "target_win": TARGET_WIN, "target_net_r": TARGET_NET_R}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", nargs="+", default=["SMC"])
    a = ap.parse_args()
    for group in a.group:
        res = run(group)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        out = REPORT_DIR / f"field_evolution_{group}_{stamp}.json"
        out.write_text(json.dumps(_jsonable(res), indent=1, default=str))
        print("written", out, "five-star findings", len(res["five_star"]), flush=True)
