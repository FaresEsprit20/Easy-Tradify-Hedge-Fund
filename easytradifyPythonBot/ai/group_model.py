# ai/group_model.py
"""
Strategy-group (category) models on the fixed engine's full capture.

Reads the column store built by `python -m ai.component_repair columns` and
the passing repair rules (core/component_rules.json), and fits one calibrated
model per strategy category -- trend, momentum, mean reversion, structure,
smart money, order flow, waves/patterns, cross-asset -- then a stacked final
model. Everything is chosen on the first calendar half and judged on the
second:

  candidate readings  each component's own direction field, each validated
                      repair rule, each edge feature, and each of those
                      restricted to a session / regime / volatility state
  kept when           significant on train (cluster z >= 2), same sign on
                      test, holds its side of 50% in >= 3 of 4 calendar
                      blocks, and survives Benjamini-Hochberg
  group model         L2 logistic over the group's kept readings -> P(up)
  final model         logistic over the group logits -> P(up)
  policy              side (engine's or model's) and entry floor chosen on
                      training-half net R after cost, reported on the test half

Exports core/calibrated_model.json (version 2: features are specs the live
engine evaluates on core/result_leaves.model_row) with decision_mode
"calibrated" only if the chosen policy is net-positive on BOTH halves.

    python -m ai.group_model            # fit, report, export when it earns it
    python -m ai.group_model --no-export
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "core" / "calibrated_model.json"
REPORT_DIR = ROOT / "reports"

# component (ai/component_repair.COMPONENTS key) -> strategy category
COMPONENT_GROUP = {
    "trend_indicator": "TREND", "trend_cascade": "TREND", "h1_trend": "TREND",
    "macd": "MOMENTUM", "ttm_squeeze": "MOMENTUM", "rvam": "MOMENTUM", "vwap": "MOMENTUM",
    "rsi": "MEAN_REVERSION", "stochastic": "MEAN_REVERSION", "bollinger": "MEAN_REVERSION",
    "premium_discount": "MEAN_REVERSION",
    "supply_demand": "STRUCTURE", "support_resistance": "STRUCTURE", "fibonacci": "STRUCTURE",
    "round_numbers": "STRUCTURE",
    "smc_overall": "SMC", "smc_structure": "SMC", "order_blocks": "SMC", "liquidity_sweep": "SMC",
    "ict_fvg": "SMC", "fvg_ifvg": "SMC",
    "volume": "ORDER_FLOW", "volume_profile": "ORDER_FLOW", "order_flow": "ORDER_FLOW",
    "liquidity_events": "ORDER_FLOW",
    "chart_patterns": "WAVE", "elliott_wave": "WAVE", "wave_lattice": "WAVE", "wyckoff": "WAVE",
    "candlestick": "WAVE", "wave_c": "WAVE",
    "gnn": "CROSS_ASSET",
    "adr_exhaustion": "CONTEXT", "session": "CONTEXT",
    "expected_value": "CONTEXT",
}
EDGE_GROUP = {
    "mom_1440": "TREND", "mom_agreement": "TREND",
    "mom_15": "MOMENTUM", "mom_60": "MOMENTUM", "mom_240": "MOMENTUM",
    "mean_dist_60": "MEAN_REVERSION",
    "day_range_pos": "STRUCTURE", "day_open_side": "STRUCTURE", "asia_break": "STRUCTURE",
    "prev_day_break": "STRUCTURE", "prev_day_pos": "STRUCTURE",
    "sweep_reclaim": "SMC",
    "ccy_strength_60": "CROSS_ASSET", "ccy_strength_240": "CROSS_ASSET",
}
DISCRETE_EDGES = ("asia_break", "prev_day_break", "sweep_reclaim", "mom_agreement")
MIN_VOTES = 400
Z_TRAIN = 2.0


# ============================================================
# DATA
# ============================================================

class Data:
    def __init__(self, market: bool = False):
        from ai.component_repair import Columns

        self.cols = Columns()
        c = self.cols
        self.n = c.n
        self.ts = c.num("ts").astype(np.float64)
        from ai.component_repair import study_split
        # discovery (train) / validation (test) inside the first 60%; the
        # holdout is only reported on (see ai.component_repair.study_split)
        self.train, self.test, self.holdout, self.blocks, self.holdout_start = study_split(self.ts)
        # market=True: the live market-stop trade (ai.component_repair.MARKET_LABEL)
        # -- direction = the side whose trade won (rows where neither won are
        # left out of the direction fit), R and commission of that trade
        self.market = market
        y = c.num("y_ms" if market else "y").astype(np.float64)
        self.y = np.where(np.isin(y, (1, -1)), y, np.nan)
        codes, vocab = c.text("ctx.symbol")
        self.symbol = np.array([vocab[k] if k >= 0 else "" for k in codes], dtype=object)
        self.clusters = np.array([f"{s}|{int(t // 86400)}" for s, t in zip(self.symbol, np.nan_to_num(self.ts))], dtype=object)
        self.br_buy = c.num("br_ms_buy" if market else "br_buy").astype(np.float64)
        self.br_sell = c.num("br_ms_sell" if market else "br_sell").astype(np.float64)
        self.cost = np.nan_to_num(c.num("ms_cost_r" if market else "cost_r").astype(np.float64), nan=0.0)          # cap
        self.net_cost = np.nan_to_num(c.num("ms_cost_r" if market else "net_cost_r").astype(np.float64), nan=0.0)  # off the bracket R
        atr = c.num("atr_pips").astype(np.float64)
        self.ret_120 = np.clip(c.num("ret_120").astype(np.float64), -10.0, 10.0)   # quiet-hour ATR tails
        from ai.component_repair import entry_spread_pips
        self.spread_atr = np.nan_to_num(entry_spread_pips(c) / np.where(atr > 0, atr, np.nan), nan=0.0)
        rcodes, rvocab = c.text("ctx.regime")
        regime = np.array([rvocab[k] if k >= 0 else "" for k in rcodes], dtype=object).astype(str)
        hour = c.num("edges.hour_utc").astype(np.float64)
        comp = c.num("edges.compression").astype(np.float64)
        from core.calibrated_model import SESSIONS_UTC, COMPRESSED_BELOW, EXPANDED_ABOVE
        self.conditions = {"trending": np.char.startswith(regime, "TREND"),
                           "ranging": np.char.startswith(regime, "RANGING"),
                           "compressed": comp < COMPRESSED_BELOW, "expanded": comp > EXPANDED_ABOVE}
        for name, (a, b) in SESSIONS_UTC.items():
            self.conditions[name] = (hour >= a) & (hour < b)
        self.rows_for_rules = None


def cluster_mean_z(values, clusters, null=0.5):
    from ai.component_calibration import cluster_mean_z as f
    return f(values, clusters, null)


def rule_vector(data: Data, rule: Mapping[str, Any]) -> np.ndarray:
    """Vectorised core/component_rules.rule_reading over the column store."""
    c = data.cols
    d = c.direction(rule["vote"]).astype(np.float64) if c.kind(rule["vote"]) else np.full(data.n, np.nan)
    mask = np.ones(data.n, bool)
    close = c.num("close").astype(np.float64)
    atr_price = c.num("atr_pips").astype(np.float64) * c.num("pip").astype(np.float64)
    for cond in rule.get("conditions") or []:
        for op in (" <= ", " >= ", " == "):
            if op in cond:
                left, right = cond.split(op, 1)
                break
        else:
            mask &= False
            continue
        if left.startswith("(") and left.endswith(" - price)/ATR"):
            field = left[1:-len(" - price)/ATR")]
            v = (c.num(field).astype(np.float64) - close) / atr_price
            kind = "num"
        else:
            kind = c.kind(left)
            v = c.num(left).astype(np.float64) if kind == "num" else None
        if op == " == " and kind == "text":
            codes, vocab = c.text(left)
            target = vocab.index(right) if right in vocab else -2
            mask &= codes == target
        elif v is not None:
            r = float(right)
            with np.errstate(invalid="ignore"):
                mask &= (v <= r) if op == " <= " else (v >= r) if op == " >= " else (v == r)
        else:
            mask &= False
    out = np.where(mask & ~np.isnan(d) & (d != 0), d, np.nan)
    return -out if rule.get("orientation") == "inverted" else out


def candidates(data: Data, rules: Optional[Mapping[str, Any]]) -> Dict[str, Tuple[str, np.ndarray, Dict[str, Any]]]:
    """name -> (group, vector, spec). Vectors: +1/-1 readings (nan silent) or
    continuous edges."""
    from ai.component_repair import COMPONENTS

    c = data.cols
    out: Dict[str, Tuple[str, np.ndarray, Dict[str, Any]]] = {}
    for comp, spec in COMPONENTS.items():
        group = COMPONENT_GROUP.get(comp)
        if not group:
            continue
        for field in spec["votes"]:
            if not c.kind(field):
                continue
            v = c.direction(field).astype(np.float64)
            if (~np.isnan(v) & (v != 0)).sum() < MIN_VOTES:
                continue
            out[f"f:{field}"] = (group, np.where(v == 0, np.nan, v), {"kind": "field", "field": field})
    for comp, items in ((rules or {}).get("components") or {}).items():
        group = COMPONENT_GROUP.get(comp)
        for i, rule in enumerate(items):
            v = rule_vector(data, rule)
            if group and (~np.isnan(v)).sum() >= MIN_VOTES // 2:
                out[f"r:{comp}:{i}"] = (group, v, {"kind": "rule", "component": comp, "index": i})
    for edge, group in EDGE_GROUP.items():
        name = f"edges.{edge}"
        if c.kind(name) != "num":
            continue
        v = c.num(name).astype(np.float64)
        if edge in DISCRETE_EDGES:
            v = np.where(v == 0, np.nan, v)
            scale = 1.0
        else:
            typical = np.nanmedian(np.abs(v[data.train])) or 1.0
            scale = float(typical)
            v = np.tanh(v / (2 * scale))
        out[f"e:{edge}"] = (group, v, {"kind": "edge", "edge": edge, "scale": scale,
                                       "discrete": edge in DISCRETE_EDGES})
    # conditional variants
    base = list(out.items())
    for name, (group, v, spec) in base:
        for cond, cmask in data.conditions.items():
            cv = np.where(cmask, v, np.nan)
            if (~np.isnan(cv) & (cv != 0)).sum() >= MIN_VOTES:
                out[f"{name}@{cond}"] = (group, cv, {**spec, "condition": cond})
    return out


def _direction_stats(v, y, clusters, mask):
    voted = mask & ~np.isnan(v) & (v != 0) & ~np.isnan(y)
    agree = np.where(voted, (np.sign(v) == y).astype(float), np.nan)
    acc, z, g = cluster_mean_z(agree, clusters)
    return acc, z, int(voted.sum())


def select(data: Data, cands) -> List[Dict[str, Any]]:
    from ai.component_calibration import benjamini_hochberg

    rows = []
    for name, (group, v, spec) in cands.items():
        tr_acc, tr_z, tr_n = _direction_stats(v, data.y, data.clusters, data.train)
        te_acc, te_z, te_n = _direction_stats(v, data.y, data.clusters, data.test)
        if tr_n < MIN_VOTES // 2 or te_n < MIN_VOTES // 4 or abs(tr_z) < Z_TRAIN:
            continue
        sign = 1 if tr_z > 0 else -1
        blocks = [_direction_stats(v, data.y, data.clusters, b)[0] for b in data.blocks]
        stable = sum(1 for a in blocks if a == a and sign * (a - 0.5) > 0)
        rows.append({"name": name, "group": group, "spec": spec, "sign": sign,
                     "train_acc": round(100 * tr_acc, 1), "test_acc": round(100 * te_acc, 1),
                     "train_n": tr_n, "test_n": te_n, "test_z": round(te_z, 2), "stable_blocks": stable,
                     "p": 0.5 * math.erfc(sign * te_z / math.sqrt(2))})
    passed = benjamini_hochberg([r["p"] for r in rows])
    kept = [r for r, ok in zip(rows, passed) if ok and r["stable_blocks"] >= 3]
    # a kept rule brings its mirror twin (and vice versa): symmetry is by
    # construction, not by what the drifting sample happened to validate
    kept_names = {r["name"] for r in kept}
    by_name = {r["name"]: r for r in rows}
    for r in list(kept):
        twin = mirror_name(r["name"], cands)
        if twin and twin not in kept_names:
            group, _v, spec = cands[twin]
            kept.append(by_name.get(twin) or {"name": twin, "group": group, "spec": spec, "sign": r["sign"],
                                               "test_z": 0.0, "stable_blocks": None, "mirror_added": True})
            kept_names.add(twin)
    return sorted(kept, key=lambda r: -abs(r["test_z"]))


def mirror_name(name: str, cands) -> Optional[str]:
    """The candidate that is `name` seen in the mirrored market (itself for
    field and edge readings, the twin for a rule)."""
    base, _, cond = name.partition("@")
    if not base.startswith("r:"):
        return name
    _, comp, idx = base.split(":")
    from core.component_rules import load_rules
    items = ((load_rules() or {}).get("components") or {}).get(comp) or []
    i = int(idx)
    if i >= len(items):
        return None
    j = items[i].get("mirror_index", items[i].get("mirror_of"))
    if j is None:
        return None
    twin = f"r:{comp}:{j}" + (f"@{cond}" if cond else "")
    return twin if twin in cands else None


# ============================================================
# MODELS
# ============================================================

def fit(data: Data, cands, kept: List[Dict[str, Any]], C: float = 0.5) -> Dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from ai.component_calibration import auc, binned, monotonic_verdict

    up = (data.y == 1).astype(int)
    decided = ~np.isnan(data.y)
    tr = data.train & decided
    by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in kept:
        by_group[r["group"]].append(r)
    groups, logits, order = {}, [], []
    for g, feats in sorted(by_group.items()):
        X = np.column_stack([np.nan_to_num(cands[f["name"]][1], nan=0.0) for f in feats])
        # ✅ SYMMETRIC (2026-09-15): every training bar is also added mirrored
        # (readings negated, outcome flipped) and no intercept is fitted, so
        # P(up | x) = 1 - P(up | -x). The study period drifted down (46% of
        # moves up) and the unconstrained models learned "sell" as a bias:
        # confident setups were SELL 25:1 and the edge would not survive an
        # up market. Every reading here is signed, so mirroring is exact.
        names = [f["name"] for f in feats]
        perm = [names.index(mirror_name(nm, cands)) if mirror_name(nm, cands) in names else k
                for k, nm in enumerate(names)]
        Xtr = np.vstack([X[tr], -X[tr][:, perm]]); ytr = np.concatenate([up[tr], 1 - up[tr]])
        m = LogisticRegression(C=C, max_iter=1000, fit_intercept=False).fit(Xtr, ytr)
        p = m.predict_proba(X)[:, 1]
        side_right = np.where(decided, ((p >= 0.5) == (data.y == 1)).astype(float), np.nan)
        acc_te, z_te, _ = cluster_mean_z(np.where(data.test, side_right, np.nan), data.clusters)
        conf = np.maximum(p, 1 - p)
        rows = binned(np.where(data.test, 100 * conf, np.nan), side_right, data.clusters, (50, 52.5, 55, 57.5, 60, 65, 70, 101))
        acc_ho, _, _ = cluster_mean_z(np.where(data.holdout, side_right, np.nan), data.clusters)
        rows_ho = binned(np.where(data.holdout, 100 * conf, np.nan), side_right, data.clusters, (50, 52.5, 55, 57.5, 60, 65, 70, 101))
        groups[g] = {"features": [{"name": f["name"], **f["spec"]} for f in feats],
                     "holdout_direction_acc": round(100 * acc_ho, 1),
                     "holdout_auc": round(auc(np.where(data.holdout & decided, p, np.nan), up), 3),
                     "holdout_bins": rows_ho,
                     "coef": [round(float(x), 5) for x in m.coef_[0]], "intercept": round(float(np.atleast_1d(m.intercept_)[0]) if m.fit_intercept else 0.0, 5),
                     "test_auc": round(auc(np.where(data.test & decided, p, np.nan), up), 3),
                     "test_direction_acc": round(100 * acc_te, 1), "test_bins": rows, **monotonic_verdict(rows)}
        logits.append(np.log(np.clip(p, 1e-4, 1 - 1e-4) / np.clip(1 - p, 1e-4, 1)))
        order.append(g)
    if not order:
        return {"groups": {}, "group_order": []}
    L = np.column_stack(logits)
    stack = LogisticRegression(C=C, max_iter=1000, fit_intercept=False).fit(
        np.vstack([L[tr], -L[tr]]), np.concatenate([up[tr], 1 - up[tr]]))
    p_up = stack.predict_proba(L)[:, 1]
    return {"groups": groups, "group_order": order,
            "stack": {"coef": [round(float(x), 5) for x in stack.coef_[0]], "intercept": 0.0},
            "_p_up": p_up}


FLOORS = (0.5, 0.525, 0.55, 0.575, 0.6, 0.625, 0.65, 0.675, 0.7, 0.75, 0.8)
COST_CAPS = (None, 0.5, 0.35, 0.2)      # max spread+commission in R a trade may pay


def price(data: Data, side: np.ndarray, conf: np.ndarray, mask: np.ndarray,
          cost_cap: Optional[float] = None) -> List[Dict[str, Any]]:
    br = np.where(side == 1, data.br_buy, data.br_sell)
    net = br - data.net_cost
    move = side * data.ret_120 - data.spread_atr
    right = np.where(np.isnan(data.y), np.nan, (side == data.y).astype(float))
    cheap = np.ones(data.n, bool) if cost_cap is None else (data.cost <= cost_cap)
    rows = []
    for f in FLOORS:
        m = mask & cheap & (conf >= f) & ~np.isnan(net)
        if m.sum() < 30:
            continue
        acc, _, _ = cluster_mean_z(np.where(m, right, np.nan), data.clusters)
        nr, nz, g = cluster_mean_z(np.where(m, net, np.nan), data.clusters, null=0.0)
        mv, _, _ = cluster_mean_z(np.where(m, move, np.nan), data.clusters, null=0.0)
        buys, sells = m & (side > 0), m & (side < 0)
        rows.append({"floor": f, "cost_cap": cost_cap, "n": int(m.sum()), "days": g,
                     "buys": int(buys.sum()), "sells": int(sells.sum()),
                     "buy_success_pct": round(100 * float(np.nanmean(right[buys])), 1) if buys.any() else None,
                     "sell_success_pct": round(100 * float(np.nanmean(right[sells])), 1) if sells.any() else None,
                     "success_pct": round(100 * acc, 1), "net_r": round(nr, 3), "net_z": round(nz, 2),
                     "move_atr": round(mv, 3)})
    return rows


def policy(data: Data, model: Mapping[str, Any]) -> Dict[str, Any]:
    """Side rule x floor x cost cap chosen on the TRAINING half by net R
    (at least 150 trades), reported on the test half."""
    p = model["_p_up"]
    engine_side = np.sign(np.nan_to_num(data.cols.direction("ctx.direction").astype(np.float64)))
    rules = {
        "model_side": (np.where(p >= 0.5, 1.0, -1.0), np.maximum(p, 1 - p)),
        "engine_side": (engine_side, np.where(engine_side == 1, p, np.where(engine_side == -1, 1 - p, 0.0))),
    }
    out: Dict[str, Any] = {}
    best_key, best_train = None, None
    for name, (side, conf) in rules.items():
        entry = {"options": []}
        for cap in COST_CAPS:
            tr = {r["floor"]: r for r in price(data, side, conf, data.train, cap)}
            te = {r["floor"]: r for r in price(data, side, conf, data.test, cap)}
            for f, row in tr.items():
                if row["n"] >= 150 and f in te:
                    entry["options"].append({"floor": f, "cost_cap": cap, "train": row, "test": te[f]})
                    if best_train is None or row["net_r"] > best_train:
                        best_train, best_key = row["net_r"], (name, f, cap)
            entry.setdefault("test_by_cap", {})[str(cap)] = list(te.values())
        out[name] = entry
    if best_key:
        name, f, cap = best_key
        opt = next(o for o in out[name]["options"] if o["floor"] == f and o["cost_cap"] == cap)
        side, conf = rules[name]
        ho = {r["floor"]: r for r in price(data, side, conf, data.holdout, cap)}
        out.update(chosen=name, floor=f, cost_cap=cap, train_at_floor=opt["train"], test_at_floor=opt["test"],
                   holdout_at_floor=ho.get(f),
                   earns=bool(opt["train"]["net_r"] > 0 and opt["test"]["net_r"] > 0),
                   earns_holdout=bool(ho.get(f) and ho[f]["net_r"] > 0),
                   test_grid=out[name]["test_by_cap"][str(cap)],
                   holdout_grid=list(ho.values()))
    else:
        out.update(chosen=None, earns=False)
    return out


_HOLDOUT_START = {"ts": None}


def data_holdout_start():
    return _HOLDOUT_START["ts"]


def export(model: Mapping[str, Any], pol: Mapping[str, Any], path: Path = MODEL_PATH) -> Dict[str, Any]:
    chosen = pol.get("chosen")
    doc = {
        "version": 2,
        "fitted": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        # live only when it earned on discovery, validation AND the untouched holdout
        "decision_mode": "calibrated" if (pol.get("earns") and pol.get("earns_holdout")) else "shadow",
        "test_start_ts": data_holdout_start(),
        "model_decides_direction": chosen == "model_side",
        "entry_floor": round(100 * pol["floor"], 1) if chosen else 100.0,
        "max_cost_r": pol.get("cost_cap"),
        "group_order": model["group_order"],
        "groups": {g: {k: v for k, v in info.items() if k in ("features", "coef", "intercept")}
                   for g, info in model["groups"].items()},
        "stack": model["stack"],
        "policy_train": pol.get("train_at_floor"),
        "policy_test": pol.get("test_at_floor"),
        "policy_holdout": pol.get("holdout_at_floor"),
    }
    path.write_text(json.dumps(doc, indent=1))
    return doc


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating,)) or (isinstance(o, float) and math.isnan(o)):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def self_check() -> Dict[str, Any]:
    assert set(COMPONENT_GROUP.values()) >= {"TREND", "MOMENTUM", "MEAN_REVERSION", "STRUCTURE", "SMC", "ORDER_FLOW", "WAVE"}
    from ai.component_repair import COMPONENTS
    missing = [c for c in COMPONENTS if c not in COMPONENT_GROUP]
    assert not missing, missing
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "group_model", "model_installed": MODEL_PATH.exists()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--market", action="store_true", help="judge on the live market-stop trade")
    ap.add_argument("--rules", default=None, help="component rules JSON (default core/component_rules.json)")
    a = ap.parse_args()
    from core.component_rules import load_rules
    data = Data(market=a.market)
    _HOLDOUT_START["ts"] = int(data.holdout_start)
    cands = candidates(data, json.loads(Path(a.rules).read_text()) if a.rules else load_rules())
    kept = select(data, cands)
    print("candidates", len(cands), "kept", len(kept), flush=True)
    model = fit(data, cands, kept)
    pol = policy(data, model) if model["group_order"] else {"chosen": None, "earns": False}
    report = {"rows": data.n, "kept": kept, "groups": model.get("groups"), "policy": pol}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = REPORT_DIR / f"group_model_{stamp}.json"
    out.write_text(json.dumps(_jsonable(report), indent=1, default=str))
    print("written", out)
    for g, info in (model.get("groups") or {}).items():
        print(g, "features", len(info["features"]), "test acc", info["test_direction_acc"], "auc", info["test_auc"], info["verdict"],
              "| HOLDOUT acc", info["holdout_direction_acc"], "auc", info["holdout_auc"])
    if pol.get("chosen"):
        print("policy", pol["chosen"], "floor", pol["floor"], "cost cap", pol["cost_cap"],
              "train", pol["train_at_floor"], "test", pol["test_at_floor"], "HOLDOUT", pol.get("holdout_at_floor"),
              "earns", pol["earns"], "earns_holdout", pol.get("earns_holdout"))
    if not a.no_export and model["group_order"]:
        print("exported", export(model, pol)["decision_mode"])
