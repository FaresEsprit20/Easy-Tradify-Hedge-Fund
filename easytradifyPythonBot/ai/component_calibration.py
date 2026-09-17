# ai/component_calibration.py
"""
Calibrate every component on the price-history study, and search for new edges.

Input: reports/cache/study/*.labelled.jsonl.gz (ai/price_history_study.py) --
the real engine's readings every 15 minutes on 17 symbols, with the move that
followed (which 5-ATR barrier price touched first) and edge features computed
from bars.

Three questions, each answered out of sample (first half of the calendar
trains, second half tests; standard errors cluster by symbol-day because
snapshots of one symbol on one day share most of their future):

1. MONOTONICITY AUDIT of the current construction. When a score is higher,
   is the measured hit rate higher? For the final probability, every group
   score, every member (by strength) and every numeric payload field.

2. EDGE SEARCH. Every candidate directional reading -- each member raw and
   repaired, each bar-computed edge feature, each categorical payload field --
   is tested for direction accuracy. A candidate is kept only if it is
   significant in the training half, holds the same sign in the test half and
   survives Benjamini-Hochberg across everything tested.

3. CALIBRATED MODEL. Per strategy group, a regularised logistic model over the
   group's validated readings gives P(up) -- monotone by construction, checked
   bin by bin on the test half. Group probabilities are then combined (the
   max rule versus a stacked logistic), and the result is priced with the
   engine's own brackets net of cost.

    python -m ai.component_calibration            # full report -> reports/component_calibration_*.json
    python -m ai.component_calibration --export   # also write core/calibrated_model.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
MODEL_PATH = ROOT / "core" / "calibrated_model.json"

MIN_N = 300                 # fewest decided snapshots for a reading to be judged
MIN_CLUSTERS = 30
Z_TRAIN = 2.0
FDR_Q = 0.05
COMMISSION_R_FALLBACK = 0.0

# Which strategy group each bar-computed edge feature belongs to.
EDGE_GROUPS = {
    "mom_15": "MOMENTUM", "mom_60": "MOMENTUM", "mom_240": "MOMENTUM", "mom_1440": "TREND",
    "mom_agreement": "TREND",
    "day_range_pos": "STRUCTURE", "day_open_side": "STRUCTURE", "asia_break": "STRUCTURE",
    "prev_day_break": "STRUCTURE", "prev_day_pos": "STRUCTURE",
    "sweep_reclaim": "SMC",
    "mean_dist_60": "MEAN_REVERSION",
    "ccy_strength_60": "CROSS_ASSET", "ccy_strength_240": "CROSS_ASSET",
}
CONTEXT_EDGES = ("compression", "asia_range_atr", "hour_utc", "weekday")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ============================================================
# LOADING
# ============================================================

LABEL = "move_5atr"


def load(symbols: Optional[Iterable[str]] = None, label: Optional[str] = None) -> Dict[str, Any]:
    """Columnar arrays of every decided snapshot (outcome `label` = +/-1)."""
    label = label or LABEL
    from ai.price_history_study import SYMBOLS, iter_records

    cols: Dict[str, list] = defaultdict(list)
    n = 0
    member_groups: Dict[str, str] = {}
    for rec in iter_records(symbols or SYMBOLS, labelled=True):
        out = rec.get("outcome") or {}
        y = out.get(label)
        if y not in (1, -1):
            continue
        d = str(rec.get("direction") or "").upper()
        side = 1 if d == "BUY" else -1 if d == "SELL" else 0
        row: Dict[str, Any] = {
            "symbol": rec["symbol"], "ts": rec["ts"], "cluster": f"{rec['symbol']}|{rec['ts'] // 86400}",
            "y": y, "y2": out.get("move_2atr") or 0, "ret_120": out.get("ret_120"),
            "side": side, "sg_final": rec.get("sg_final"), "sg_other": rec.get("sg_other"),
            "should_enter": int(bool(rec.get("should_enter"))),
            "cost_r": (rec.get("cost") or {}).get("cost_r"),
            "target_r": (rec.get("cost") or {}).get("target_r"),
            "br_r": (out.get("bracket") or {}).get("r"),
            "br_buy": (out.get("bracket_buy") or {}).get("r"),
            "br_sell": (out.get("bracket_sell") or {}).get("r"),
            "regime": rec.get("regime") or "",
            "sg_winner": rec.get("sg_winner") or "",
        }
        for g, s in (rec.get("sg_scores") or {}).items():
            row[f"g_{g}"] = s
        for name, m in (rec.get("members") or {}).items():
            member_groups[slug(name)] = m.get("group")
            for kind in ("raw", "used"):
                r = m.get(kind)
                row[f"m_{kind}_{slug(name)}"] = None if r is None else r[0] * max(0.0, min(1.0, r[1]))
        for k, v in (rec.get("edges") or {}).items():
            if isinstance(v, (int, float)) and k != "version":
                row[f"e_{k}"] = v
        for k, v in (rec.get("num") or {}).items():
            if isinstance(v, (int, float)):
                row[f"n_{k}"] = v
            elif isinstance(v, str):
                row[f"c_{k}"] = v
        for k, v in row.items():
            cols[k].append((n, v))       # sparse: (row index, value)
        n += 1
    frame = {}
    for k, pairs in cols.items():
        numeric = all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for _, v in pairs)
        if numeric:
            dense = np.full(n, np.nan)
            for i, v in pairs:
                if v is not None:
                    dense[i] = v
        else:
            dense = np.empty(n, dtype=object)
            for i, v in pairs:
                dense[i] = v
        frame[k] = dense
    frame["_n"] = n
    frame["_member_groups"] = member_groups
    return frame


def num(frame, key) -> np.ndarray:
    col = frame.get(key)
    if col is None:
        return np.full(frame["_n"], np.nan)
    if isinstance(col, np.ndarray) and col.dtype == float:
        return col
    return np.array([float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else np.nan
                     for v in col], dtype=float)


def halves(frame) -> Tuple[np.ndarray, np.ndarray]:
    """Train = calendar first half, test = second half, one day embargoed."""
    ts = num(frame, "ts")
    cut = np.nanmedian(ts)
    return ts < cut - 43200, ts >= cut + 43200


# ============================================================
# STATISTICS
# ============================================================

def cluster_mean_z(values: np.ndarray, clusters: np.ndarray, null: float = 0.5) -> Tuple[float, float, int]:
    """Mean of `values`, and its z against `null` with cluster-robust SE."""
    ok = ~np.isnan(values)
    v, c = values[ok], clusters[ok]
    if v.size == 0:
        return float("nan"), 0.0, 0
    mean = float(v.mean())
    uniq, inv = np.unique(c, return_inverse=True)
    g = len(uniq)
    if g < 2:
        return mean, 0.0, g
    resid = np.bincount(inv, weights=v - mean)
    se = math.sqrt((resid ** 2).sum() * g / (g - 1)) / v.size
    return mean, (mean - null) / se if se > 0 else 0.0, g


def p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def benjamini_hochberg(pvalues: Sequence[float], q: float = FDR_Q) -> List[bool]:
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    passed = np.zeros(m, dtype=bool)
    k_max = -1
    for rank, idx in enumerate(order, start=1):
        if p[idx] <= q * rank / m:
            k_max = rank
    if k_max > 0:
        passed[order[:k_max]] = True
    return passed.tolist()


def auc(score: np.ndarray, label: np.ndarray) -> float:
    ok = ~np.isnan(score)
    s, l = score[ok], label[ok]
    pos, neg = s[l == 1], s[l != 1]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]), kind="mergesort"), kind="mergesort") + 1.0
    # average ties
    allv = np.concatenate([pos, neg])
    _, inv, counts = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / counts)[inv]
    return float((ranks[:pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def binned(score: np.ndarray, good: np.ndarray, clusters: np.ndarray, edges: Sequence[float]) -> List[Dict[str, Any]]:
    """Hit rate per score bin, with the cluster z of each step versus the previous bin."""
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (score >= lo) & (score < hi) & ~np.isnan(good)
        if mask.sum() == 0:
            continue
        m, z, g = cluster_mean_z(good[mask], clusters[mask])
        rows.append({"bin": f"{lo:g}-{hi:g}", "n": int(mask.sum()), "hit": round(100 * m, 1), "z_vs_50": round(z, 2)})
    return rows


def monotonic_verdict(rows: List[Dict[str, Any]], min_n: int = 100) -> Dict[str, Any]:
    """Spearman of bin order vs hit rate, and material inversions (a later bin
    at least 3 points below an earlier one, both with min_n)."""
    usable = [r for r in rows if r["n"] >= min_n]
    if len(usable) < 3:
        return {"verdict": "TOO_FEW_BINS", "spearman": None, "inversions": []}
    hits = np.array([r["hit"] for r in usable])
    order = np.arange(len(hits))
    rank_h = np.argsort(np.argsort(hits))
    rho = float(np.corrcoef(order, rank_h)[0, 1])
    inversions = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            if usable[j]["hit"] + 3 <= usable[i]["hit"]:
                inversions.append(f"{usable[i]['bin']} {usable[i]['hit']}% > {usable[j]['bin']} {usable[j]['hit']}%")
    verdict = ("MONOTONE" if rho >= 0.8 and not inversions else
               "INVERTED" if rho <= -0.8 else "NON_MONOTONE")
    return {"verdict": verdict, "spearman": round(rho, 2), "inversions": inversions[:6]}


# ============================================================
# 1. MONOTONICITY AUDIT
# ============================================================

SCORE_EDGES = (0, 30, 45, 55, 65, 75, 85, 101)


def audit(frame) -> Dict[str, Any]:
    y, side, clusters = num(frame, "y"), num(frame, "side"), frame["cluster"]
    right = np.where(side != 0, (y == side).astype(float), np.nan)
    train, test = halves(frame)
    out: Dict[str, Any] = {}

    sg = num(frame, "sg_final")
    block = {}
    for label, mask in (("all", np.ones_like(train)), ("train", train), ("test", test)):
        rows = binned(np.where(mask, sg, np.nan), right, clusters, SCORE_EDGES)
        block[label] = {"bins": rows, **monotonic_verdict(rows)}
    block["auc_all"] = round(auc(np.where(side != 0, sg, np.nan), right), 3)
    out["final_probability"] = block

    groups = {}
    for key in frame:
        if not key.startswith("g_"):
            continue
        s = num(frame, key)
        up_score = np.where(side == 1, s, np.where(side == -1, 100 - s, np.nan))
        up = (y == 1).astype(float)
        rows = binned(up_score, up, clusters, SCORE_EDGES)
        groups[key[2:]] = {"bins": rows, **monotonic_verdict(rows),
                           "auc": round(auc(up_score, up), 3), "n": int((~np.isnan(up_score)).sum())}
    out["group_scores"] = groups

    members = {}
    for key in frame:
        if not key.startswith("m_"):
            continue
        v = num(frame, key)
        voted = ~np.isnan(v) & (v != 0)
        if voted.sum() < MIN_N:
            members[key] = {"n": int(voted.sum()), "verdict": "TOO_FEW"}
            continue
        agree = np.where(voted, (np.sign(v) == y).astype(float), np.nan)
        strength = np.abs(v)
        rows = binned(np.where(voted, strength, np.nan), agree, clusters, (0, 0.35, 0.55, 0.75, 0.95, 1.01))
        acc, z, g = cluster_mean_z(agree, clusters)
        acc_tr, z_tr, _ = cluster_mean_z(np.where(train, agree, np.nan), clusters)
        acc_te, z_te, _ = cluster_mean_z(np.where(test, agree, np.nan), clusters)
        members[key] = {"n": int(voted.sum()), "coverage": round(float(voted.mean()), 3),
                        "accuracy": round(100 * acc, 1), "z": round(z, 2),
                        "train": round(100 * acc_tr, 1), "test": round(100 * acc_te, 1),
                        "by_strength": rows, **monotonic_verdict(rows)}
    out["members"] = members

    numeric = {}
    up = (y == 1).astype(float)
    for key in frame:
        if not key.startswith("n_"):
            continue
        v = num(frame, key)
        ok = ~np.isnan(v)
        if ok.sum() < MIN_N * 3 or len(np.unique(v[ok])) < 5:
            continue
        qs = np.unique(np.nanquantile(v[ok], np.linspace(0, 1, 6)))
        if len(qs) < 4:
            continue
        qs[-1] = qs[-1] + 1e-9
        rows = binned(v, up, clusters, qs.tolist())
        mv = monotonic_verdict(rows)
        numeric[key[2:]] = {"n": int(ok.sum()), "bins": rows, **mv, "auc_up": round(auc(v, up), 3)}
    out["numeric_fields"] = numeric
    return out


# ============================================================
# 2. EDGE SEARCH
# ============================================================

def _direction_of_text(value: Any) -> Optional[int]:
    from core.strategy_groups import market_direction
    return market_direction(value)


def candidates(frame) -> Dict[str, np.ndarray]:
    """Every directional reading as a +/- vector (nan = no reading, 0 = silent)."""
    n = frame["_n"]
    out: Dict[str, np.ndarray] = {}
    for key in frame:
        if key.startswith("m_"):
            out[key] = num(frame, key)
        elif key.startswith("e_") and key[2:] in EDGE_GROUPS:
            out[key] = num(frame, key)
        elif key.startswith("c_"):
            col = frame[key]
            vals = np.array([np.nan if v is None else (_direction_of_text(v) if _direction_of_text(v) is not None else np.nan)
                             for v in col], dtype=float)
            if (~np.isnan(vals) & (vals != 0)).sum() >= MIN_N:
                out[key] = vals
    return out


# ------------------------------------------------------------
# Conditional and adaptive readings (added after the plain search found no
# reading that held its sign from one half of the calendar to the other:
# trend-following members were right 53-57% in the first weeks and 44-46%
# after). A reading may carry edge only in a regime, a session or a
# volatility state -- or only while it has recently been working.
# ------------------------------------------------------------

LABEL_HORIZON_SECONDS = {"move_5atr": 8 * 3600, "move_2atr": 8 * 3600}
ADAPTIVE_DAYS = 5
ADAPTIVE_MIN_HISTORY = 30
ADAPTIVE_MIN_EDGE = 0.02


def label_horizon(label: str) -> int:
    return LABEL_HORIZON_SECONDS.get(label, 24 * 3600)


def conditions(frame) -> Dict[str, np.ndarray]:
    n = frame["_n"]
    from core.calibrated_model import SESSIONS_UTC, COMPRESSED_BELOW, EXPANDED_ABOVE

    regime = np.array([str(v or "") for v in frame.get("regime", np.full(n, ""))])
    hour = num(frame, "e_hour_utc")
    comp = num(frame, "e_compression")
    out = {"trending": np.char.startswith(regime, "TREND"),
           "ranging": np.char.startswith(regime, "RANGING")}
    for name, (a, b) in SESSIONS_UTC.items():
        out[name] = (hour >= a) & (hour < b)
    out["compressed"] = comp < COMPRESSED_BELOW
    out["expanded"] = comp > EXPANDED_ABOVE
    return out


def adaptive_reading(frame, v: np.ndarray, label: str, days: int = ADAPTIVE_DAYS) -> np.ndarray:
    """The reading, oriented by how it has done on the same symbol over the
    previous `days` -- using only outcomes already settled at decision time
    (a snapshot's outcome counts once its whole horizon has passed)."""
    y = num(frame, "y")
    ts = num(frame, "ts")
    symbols = frame["symbol"]
    horizon = label_horizon(label)
    out = np.full(frame["_n"], np.nan)
    voted = ~np.isnan(v) & (v != 0)
    agree = np.where(voted, (np.sign(v) == y).astype(float), 0.0)
    for sym in np.unique(symbols):
        idx = np.where(symbols == sym)[0]
        idx = idx[np.argsort(ts[idx], kind="mergesort")]
        t = ts[idx]
        csum_agree = np.concatenate([[0.0], np.cumsum(agree[idx])])
        csum_vote = np.concatenate([[0.0], np.cumsum(voted[idx].astype(float))])
        hi = np.searchsorted(t, t - horizon, side="right")
        lo = np.searchsorted(t, t - days * 86400, side="left")
        hi = np.maximum(hi, lo)
        count = csum_vote[hi] - csum_vote[lo]
        acc = np.where(count > 0, (csum_agree[hi] - csum_agree[lo]) / np.maximum(count, 1), 0.5)
        orient = np.where((count >= ADAPTIVE_MIN_HISTORY) & (np.abs(acc - 0.5) >= ADAPTIVE_MIN_EDGE),
                          np.sign(acc - 0.5), 0.0)
        out[idx] = np.where(np.isnan(v[idx]), np.nan, v[idx] * orient)
    return out


def extended_candidates(frame, label: str) -> Dict[str, np.ndarray]:
    base = {k: v for k, v in candidates(frame).items() if not k.startswith("c_") and not k.startswith("m_used_")}
    out = dict(candidates(frame))
    conds = conditions(frame)
    for name, v in base.items():
        for cname, mask in conds.items():
            cv = np.where(mask, v, np.nan)
            if (~np.isnan(cv) & (cv != 0)).sum() >= MIN_N:
                out[f"{name}@{cname}"] = cv
        out[f"{name}~adaptive"] = adaptive_reading(frame, v, label)
    return out


def blocks(frame, k: int = 4) -> List[np.ndarray]:
    ts = num(frame, "ts")
    edges = np.nanquantile(ts, np.linspace(0, 1, k + 1))
    edges[-1] += 1
    return [(ts >= a) & (ts < b) for a, b in zip(edges[:-1], edges[1:])]


def _edge_stats(v: np.ndarray, y: np.ndarray, clusters, mask) -> Dict[str, Any]:
    voted = mask & ~np.isnan(v) & (v != 0)
    agree = np.where(voted, (np.sign(v) == y).astype(float), np.nan)
    acc, z, g = cluster_mean_z(agree, clusters)
    return {"n": int(voted.sum()), "clusters": g, "acc": acc, "z": z}


def edge_search(frame, label: Optional[str] = None, extended: bool = True) -> Dict[str, Any]:
    y, clusters = num(frame, "y"), frame["cluster"]
    train, test = halves(frame)
    cands = extended_candidates(frame, label or LABEL) if extended else candidates(frame)
    four = blocks(frame)
    rows = []
    for name, v in cands.items():
        tr, te = _edge_stats(v, y, clusters, train), _edge_stats(v, y, clusters, test)
        block_acc = [_edge_stats(v, y, clusters, b)["acc"] for b in four]
        rows.append({"name": name, "train_n": tr["n"], "train_acc": tr["acc"], "train_z": tr["z"],
                     "test_n": te["n"], "test_acc": te["acc"], "test_z": te["z"], "clusters": te["clusters"],
                     "block_acc": [None if a is None or math.isnan(a) else round(100 * a, 1) for a in block_acc]})
    # selected on train: significant either way (an inverted reading is an edge too)
    selected = [r for r in rows if r["train_n"] >= MIN_N and abs(r["train_z"]) >= Z_TRAIN
                and r["test_n"] >= MIN_N // 2]
    pvals = []
    for r in selected:
        sign = 1 if r["train_z"] > 0 else -1
        # one-sided test in the train direction
        z = sign * r["test_z"]
        pvals.append(0.5 * math.erfc(z / math.sqrt(2)))
    passed = benjamini_hochberg(pvals)
    for r, p, ok in zip(selected, pvals, passed):
        sign = 1 if r["train_z"] > 0 else -1
        r["test_p_one_sided"] = p
        r["orientation"] = "as-is" if sign > 0 else "inverted"
        # held its side of 50% in at least 3 of the 4 calendar blocks
        r["stable_blocks"] = sum(1 for a in r["block_acc"] if a is not None and sign * (a - 50) > 0)
        r["validated"] = bool(ok) and r["stable_blocks"] >= 3
    for r in rows:
        for k in ("train_acc", "test_acc"):
            r[k] = None if r[k] is None or (isinstance(r[k], float) and math.isnan(r[k])) else round(100 * r[k], 1)
        for k in ("train_z", "test_z"):
            r[k] = round(r[k], 2)
        r.setdefault("validated", False)
    rows.sort(key=lambda r: (not r["validated"], -abs(r["test_z"])))
    return {"tested": len(rows), "selected_on_train": len(selected),
            "validated": sum(1 for r in rows if r["validated"]), "rows": rows}


# ============================================================
# 3. CALIBRATED MODEL
# ============================================================

DISCRETE_EDGES = ("asia_break", "prev_day_break", "sweep_reclaim")


def _base_name(name: str) -> str:
    return name.split("@", 1)[0].split("~", 1)[0]


def feature_scale(frame, name: str, mask: np.ndarray) -> float:
    """Typical size of a continuous edge reading on the training rows."""
    base = _base_name(name)
    if not base.startswith("e_") or base[2:] in DISCRETE_EDGES:
        return 1.0
    v = np.abs(num(frame, base)[mask])
    v = v[~np.isnan(v)]
    s = float(np.median(v)) if v.size else 1.0
    return s if s > 0 else 1.0


def transform(value: np.ndarray, name: str, scale: float) -> np.ndarray:
    """Bounded, sign-preserving feature: tanh(v / 2 x typical size) for
    continuous edges; member readings (direction x strength) as they are."""
    base = _base_name(name)
    if base.startswith("e_") and base[2:] not in DISCRETE_EDGES:
        return np.tanh(value / (2.0 * scale))
    return value


def feature_values(frame, name: str) -> np.ndarray:
    """A candidate's column: plain, or restricted to a condition (x@cond)."""
    if "@" in name:
        base, cond = name.split("@", 1)
        return np.where(conditions(frame)[cond], num(frame, base), np.nan)
    return num(frame, name)


def _feature_matrix(frame, names: Sequence[str], scales: Mapping[str, float]) -> np.ndarray:
    cols = [np.nan_to_num(transform(feature_values(frame, n), n, scales[n]), nan=0.0) for n in names]
    return np.column_stack(cols) if cols else np.zeros((frame["_n"], 0))


def group_of(name: str, member_groups: Mapping[str, str]) -> Optional[str]:
    name = _base_name(name)
    if name.startswith("m_raw_") or name.startswith("m_used_"):
        return member_groups.get(name.split("_", 2)[2])
    if name.startswith("e_"):
        return EDGE_GROUPS.get(name[2:])
    return None


def fit_models(frame, validated: Sequence[str], C: float = 0.5) -> Dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.isotonic import IsotonicRegression

    y = num(frame, "y")
    up = (y == 1).astype(int)
    clusters = frame["cluster"]
    train, test = halves(frame)
    member_groups = frame["_member_groups"]

    by_group: Dict[str, List[str]] = defaultdict(list)
    for name in validated:
        g = group_of(name, member_groups)
        if g:
            by_group[g].append(name)

    groups: Dict[str, Any] = {}
    p_train_cols, p_test_cols, p_all_cols, order = [], [], [], []
    scales = {n: feature_scale(frame, n, train) for n in validated}
    for g, names in sorted(by_group.items()):
        X = _feature_matrix(frame, names, scales)
        model = LogisticRegression(C=C, max_iter=500)
        model.fit(X[train], up[train])
        p = model.predict_proba(X)[:, 1]
        rows = binned(np.where(test, 100 * p, np.nan), up.astype(float), clusters, (0, 30, 40, 45, 50, 55, 60, 70, 101))
        groups[g] = {"features": names, "scales": [round(scales[n], 6) for n in names],
                     "coef": [round(float(c), 4) for c in model.coef_[0]],
                     "intercept": round(float(model.intercept_[0]), 4),
                     "test_auc": round(auc(np.where(test, p, np.nan), up), 3),
                     "test_bins": rows, **monotonic_verdict(rows)}
        order.append(g)
        p_all_cols.append(p)
    if not order:
        return {"groups": {}, "note": "no validated readings"}
    P = np.column_stack(p_all_cols)
    logit = np.log(np.clip(P, 1e-4, 1 - 1e-4) / (1 - np.clip(P, 1e-4, 1 - 1e-4)))

    stack = LogisticRegression(C=C, max_iter=500)
    stack.fit(logit[train], up[train])
    p_stack = stack.predict_proba(logit)[:, 1]

    # max rule on calibrated groups: side = sign of the most confident group
    dev = P - 0.5
    idx = np.argmax(np.abs(dev), axis=1)
    p_max_raw = P[np.arange(len(idx)), idx]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p_max_raw[train], up[train])
    p_max = iso.predict(p_max_raw)

    result = {"groups": groups, "group_order": order,
              "stack": {"coef": [round(float(c), 4) for c in stack.coef_[0]],
                        "intercept": round(float(stack.intercept_[0]), 4)}}
    engine_side = num(frame, "side")
    for label, p in (("stacked", p_stack), ("max_rule", p_max)):
        side = np.where(p >= 0.5, 1, -1)
        conf = np.where(side == 1, p, 1 - p)
        right = (side == y).astype(float)
        rows = binned(np.where(test, 100 * conf, np.nan), right, clusters, (50, 52.5, 55, 57.5, 60, 65, 70, 101))
        acc, z, _ = cluster_mean_z(np.where(test, right, np.nan), clusters)
        result[label] = {"test_auc_up": round(auc(np.where(test, p, np.nan), up), 3),
                         "test_direction_acc": round(100 * acc, 1), "z": round(z, 2),
                         "test_confidence_bins": rows, **monotonic_verdict(rows),
                         "pricing": price_rule(frame, side, conf, test)}
    eng_right = np.where(engine_side != 0, (engine_side == y).astype(float), np.nan)
    acc, z, _ = cluster_mean_z(np.where(test, eng_right, np.nan), clusters)
    result["engine_direction_test_acc"] = round(100 * acc, 1)
    result["_p_stack"] = p_stack
    result["_P"] = P
    return result


def price_rule(frame, side: np.ndarray, conf: np.ndarray, mask: np.ndarray,
               floors: Sequence[float] = (0.5, 0.55, 0.6, 0.65, 0.7)) -> List[Dict[str, Any]]:
    """Net R of taking `side` at each confidence floor, with the engine's own
    stop/target distances (mirrored bracket) minus its cost."""
    br = np.where(side == 1, num(frame, "br_buy"), num(frame, "br_sell"))
    cost = np.nan_to_num(num(frame, "cost_r"), nan=COMMISSION_R_FALLBACK)
    net = br - cost
    clusters = frame["cluster"]
    rows = []
    for f in floors:
        m = mask & (conf >= f) & ~np.isnan(net)
        if m.sum() == 0:
            continue
        mean, z, g = cluster_mean_z(np.where(m, net, np.nan), clusters, null=0.0)
        gross, _, _ = cluster_mean_z(np.where(m, br, np.nan), clusters, null=0.0)
        rows.append({"floor": f, "n": int(m.sum()), "clusters": g, "gross_r": round(gross, 3),
                     "net_r": round(mean, 3), "z": round(z, 2)})
    return rows


COST_BUCKETS = (0.0, 0.2, 0.35, 0.5, 0.75, 1.0, 2.0, 99.0)


def cost_breakdown(frame) -> List[Dict[str, Any]]:
    """The engine's own bracket on its own side, by cost in R: where the
    stop is so close that spread and commission eat the trade."""
    br, cost, clusters = num(frame, "br_r"), num(frame, "cost_r"), frame["cluster"]
    rows = []
    for lo, hi in zip(COST_BUCKETS[:-1], COST_BUCKETS[1:]):
        m = (cost >= lo) & (cost < hi) & ~np.isnan(br)
        if m.sum() == 0:
            continue
        gross, _, _ = cluster_mean_z(np.where(m, br, np.nan), clusters, null=0.0)
        net, z, g = cluster_mean_z(np.where(m, br - cost, np.nan), clusters, null=0.0)
        rows.append({"cost_r": f"{lo:g}-{hi:g}", "n": int(m.sum()), "gross_r": round(gross, 3),
                     "net_r": round(net, 3), "z": round(z, 2),
                     "target_hit_pct": round(100 * float(np.mean(br[m] > 0)), 1)})
    return rows


FLOOR_GRID = (0.5, 0.525, 0.55, 0.575, 0.6, 0.625, 0.65, 0.675, 0.7, 0.75)
MIN_FLOOR_N = 200


def choose_policy(frame, model: Mapping[str, Any]) -> Dict[str, Any]:
    """Which side to trade and from what calibrated probability, chosen on the
    TRAINING half by net R after cost, then reported on the test half.

    Two side rules are priced: the engine's own side (probability = calibrated
    P(that side)) and the model's preferred side. The model decides the side
    only if that is better on net R in the training half AND the test half."""
    train, test = halves(frame)
    p_up = model["_p_stack"]
    engine_side = num(frame, "side")
    rules = {
        "engine_side": (engine_side, np.where(engine_side == 1, p_up, np.where(engine_side == -1, 1 - p_up, np.nan))),
        "model_side": (np.where(p_up >= 0.5, 1, -1), np.maximum(p_up, 1 - p_up)),
    }
    out: Dict[str, Any] = {}
    for name, (side, conf) in rules.items():
        tr = {r["floor"]: r for r in price_rule(frame, side, conf, train, FLOOR_GRID)}
        te = {r["floor"]: r for r in price_rule(frame, side, conf, test, FLOOR_GRID)}
        usable = [f for f in FLOOR_GRID if f in tr and tr[f]["n"] >= MIN_FLOOR_N]
        best = max(usable, key=lambda f: tr[f]["net_r"]) if usable else None
        out[name] = {"train": list(tr.values()), "test": list(te.values()), "chosen_floor": best,
                     "train_net_r": tr[best]["net_r"] if best else None,
                     "test_net_r": te[best]["net_r"] if best in te else None,
                     "test_n": te[best]["n"] if best in te else 0}
    e, m = out["engine_side"], out["model_side"]
    decides = (m["chosen_floor"] is not None and e["chosen_floor"] is not None
               and m["train_net_r"] > e["train_net_r"] and (m["test_net_r"] or -9) > (e["test_net_r"] or -9))
    chosen = m if decides else e
    out["model_decides_direction"] = bool(decides)
    out["entry_floor"] = None if chosen["chosen_floor"] is None else round(100 * chosen["chosen_floor"], 1)
    return out


def export(model: Mapping[str, Any], policy: Mapping[str, Any], label: str, path: Path = MODEL_PATH) -> None:
    doc = {"version": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "label": label,
           "entry_floor": policy.get("entry_floor") or 50.0,
           "model_decides_direction": policy.get("model_decides_direction", False),
           "groups": {g: {k: v for k, v in info.items() if k in ("features", "scales", "coef", "intercept")}
                      for g, info in model["groups"].items()},
           "group_order": model["group_order"], "stack": model["stack"]}
    path.write_text(json.dumps(doc, indent=1))


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if math.isnan(float(obj)) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def self_check() -> Dict[str, Any]:
    v = np.array([1, 1, 1, 0, 0, 1.0]); c = np.array(list("aabbcc"))
    m, z, g = cluster_mean_z(v, c)
    assert abs(m - 4 / 6) < 1e-9 and g == 3
    assert benjamini_hochberg([0.001, 0.2, 0.03]) == [True, False, True]
    assert abs(auc(np.array([0.1, 0.9, 0.8, 0.2]), np.array([0, 1, 1, 0])) - 1.0) < 1e-9
    rows = [{"bin": str(i), "n": 500, "hit": h} for i, h in enumerate([40, 45, 52, 60])]
    assert monotonic_verdict(rows)["verdict"] == "MONOTONE"
    rows[3]["hit"] = 41
    assert monotonic_verdict(rows)["verdict"] != "MONOTONE"
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "component_calibration", "fdr_q": FDR_Q}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--label", default=LABEL)
    a = parser.parse_args()
    if a.check:
        print(self_check())
        raise SystemExit
    frame = load(label=a.label)
    print("snapshots", frame["_n"])
    report = {"snapshots": frame["_n"], "label": a.label, "audit": audit(frame),
              "edges": edge_search(frame, a.label), "costs": cost_breakdown(frame),
              "period": [int(np.nanmin(num(frame, "ts"))), int(np.nanmax(num(frame, "ts")))],
              "symbols": sorted(set(frame["symbol"].tolist()))}
    # adaptive readings need a live outcome history the engine does not keep;
    # they are reported, not deployed
    validated = [r["name"] for r in report["edges"]["rows"] if r["validated"] and "~" not in r["name"]]
    model = fit_models(frame, validated)
    report["model"] = model
    policy = choose_policy(frame, model) if model.get("groups") else {}
    report["policy"] = policy
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = REPORT_DIR / f"component_calibration_{stamp}.json"
    out.write_text(json.dumps(_jsonable(report), indent=1, default=str))
    print("written", out)
    print(json.dumps(_jsonable({k: v for k, v in policy.items() if k in ("entry_floor", "model_decides_direction")})))
    if a.export and model.get("groups"):
        export(model, policy, a.label)
        print("exported", MODEL_PATH)
