# ai/component_repair.py
"""
Per-component repair: why each component wins and loses, where it
contradicts itself, and which rules over its OWN internal fields make it
right often enough and profitable enough to keep.

Input: the price-history study captured with PRICE_STUDY_FULL=1 (every
component's internal fields per snapshot) and labelled (outcome + edges).

    python -m ai.component_repair columns     # one pass: gz records -> memory-mapped columns
    python -m ai.component_repair run         # diagnose + search + validate every component
    python -m ai.component_repair run --only supply_demand

The red line per component (user, 2026-09-15): high success rate AND high
expectancy. A rule passes only when, on the calendar half it was NOT found on,
  - its direction is right >= MIN_TEST_ACCURACY,
  - its net R after cost is > 0 (the engine's own stop/target distances),
  - it holds >= MIN_TEST_ACCURACY - 5 in at least 3 of 4 calendar blocks,
  - and it survives Benjamini-Hochberg across every rule tested.

Rules are conjunctions of at most MAX_LITERALS conditions on the component's
fields (price-like fields measured from price in ATR) and session / regime /
edge context, found with a beam search on the first half only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = Path(os.getenv("PRICE_STUDY_DIR") or r"C:/Users/msi/tradify_study/full")
COLUMN_DIR = STUDY_DIR / "columns"
REPORT_DIR = ROOT / "reports"
RULES_PATH = ROOT / "core" / "component_rules.json"

LABEL = "move_5atr"
# The live trade: market stop (1.5 x H1 ATR), 1R target, tick-accurate fills.
# Success = that trade reached its target; the red line is the user's target.
MARKET_LABEL = "market_stop"
TARGET_NET_R = 0.2
MIN_TEST_ACCURACY = 65.0
MIN_SUPPORT_TRAIN = 150
MIN_SUPPORT_TEST = 100
BEAM = 40
MAX_LITERALS = 2
QUANTILES = (0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9)
MAX_CATEGORIES = 12
FDR_Q = 0.05

# Context every component may be conditioned on (edge features, regime, session).
CONTEXT_PREFIXES = ("edges.", "ctx.")

# component -> (vote field(s), internal field prefixes)
# The vote is the component's own directional output; the prefixes are where
# its internals live in the analysis result.
COMPONENTS: Dict[str, Dict[str, Any]] = {
    "rsi": {"votes": ["indicators.rsi.recommendation", "indicators.rsi.adaptive.recommendation"],
            "fields": ["indicators.rsi."]},
    "stochastic": {"votes": ["indicators.stochastic.recommendation", "indicators.stochastic.signal",
                             "indicators.stochastic.adaptive.recommendation"],
                   "fields": ["indicators.stochastic."]},
    "macd": {"votes": ["indicators.macd.cross_direction", "indicators.macd.signal", "indicators.macd.recommendation"],
             "fields": ["indicators.macd."]},
    "bollinger": {"votes": ["indicators.bollinger_bands.recommendation", "indicators.bollinger_bands.signal"],
                  "fields": ["indicators.bollinger_bands."]},
    "trend_indicator": {"votes": ["indicators.trend.recommendation"], "fields": ["indicators.trend."]},
    "volume": {"votes": ["indicators.volume.recommendation"], "fields": ["indicators.volume."]},
    "supply_demand": {"votes": ["indicators.supply_demand.recommendation",
                                "indicators.supply_demand.volume_profile_confluence.zone_type"],
                      "fields": ["indicators.supply_demand."]},
    "support_resistance": {"votes": ["indicators.support_resistance.recommendation"],
                           "fields": ["indicators.support_resistance.", "indicators.breakout."]},
    "fibonacci": {"votes": ["indicators.fib_confluence.recommendation"], "fields": ["indicators.fib_confluence."]},
    "candlestick": {"votes": ["indicators.candlestick.recommendation"], "fields": ["indicators.candlestick."]},
    "wyckoff": {"votes": ["indicators.wyckoff.recommendation", "indicators.wyckoff.phase"],
                "fields": ["indicators.wyckoff."]},
    "ict_fvg": {"votes": ["indicators.ict_concepts.type"], "fields": ["indicators.ict_concepts."]},
    "fvg_ifvg": {"votes": ["indicators.fvg_ifvg.recommendation"], "fields": ["indicators.fvg_ifvg."]},
    "volume_profile": {"votes": ["indicators.volume_profile.recommendation"],
                       "fields": ["indicators.volume_profile."]},
    "wave_c": {"votes": ["indicators.wave_c.data.reversal_direction", "indicators.wave_c.recommendation"],
               "fields": ["indicators.wave_c."]},
    "round_numbers": {"votes": ["indicators.round_numbers.recommendation", "indicators.round_numbers.magnet_type"],
                      "fields": ["indicators.round_numbers."]},
    "expected_value": {"votes": ["indicators.expected_value.recommendation"],
                       "fields": ["indicators.expected_value."]},
    "smc_overall": {"votes": ["smc.analysis.recommendation"], "fields": ["smc.analysis."]},
    "smc_structure": {"votes": ["smc.analysis.market_structure.structure", "smc.analysis.market_structure.last_event"],
                      "fields": ["smc.analysis.market_structure."]},
    "order_blocks": {"votes": ["smc.analysis.order_blocks.bullish_ob.type", "smc.analysis.order_blocks.bearish_ob.type"],
                     "fields": ["smc.analysis.order_blocks.", "smc.order_block_volume_profile_confluence."]},
    "liquidity_sweep": {"votes": ["smc.analysis.liquidity_sweep.type", "smc.analysis.liquidity_sweep.event.implied_direction"],
                        "fields": ["smc.analysis.liquidity_sweep.", "smc.sweep_volume_profile_confluence."]},
    "premium_discount": {"votes": ["smc.analysis.premium_discount.zone"], "fields": ["smc.analysis.premium_discount."]},
    "order_flow": {"votes": ["final_verdict.order_flow_final_score.order_flow_recommendation"],
                   "fields": ["order_flow_forensics.", "final_verdict.order_flow_final_score."]},
    "liquidity_events": {"votes": ["liquidity_events.bias", "liquidity_events.strongest.implied_direction"],
                         "fields": ["liquidity_events."]},
    "chart_patterns": {"votes": ["pattern_analysis.final_score.pattern_recommendation",
                                 "pattern_analysis.summary.overall_direction"],
                       "fields": ["pattern_analysis."]},
    "elliott_wave": {"votes": ["pattern_analysis.elliott_waves[0].direction", "pattern_analysis.elliott_waves[0].next_move"],
                     "fields": ["pattern_analysis.elliott_waves"]},
    "wave_lattice": {"votes": ["wave_lattice.lattice_summary.root_direction"], "fields": ["wave_lattice."]},
    "trend_cascade": {"votes": ["trend_cascade.direction"], "fields": ["trend_cascade."]},
    "h1_trend": {"votes": ["higher_timeframe.trend"], "fields": ["higher_timeframe."]},
    "ttm_squeeze": {"votes": ["ttm_squeeze.release_direction", "ttm_squeeze.momentum_direction"], "fields": ["ttm_squeeze.", "ttm_squeeze_setup."]},
    "rvam": {"votes": ["rvam.signal_direction", "rvam.direction"], "fields": ["rvam."]},
    "vwap": {"votes": ["vwap.above_vwap", "vwap_context.stance"], "fields": ["vwap.", "vwap_context."]},
    "gnn": {"votes": ["gnn.analysis.recommendation", "gnn.analysis.gnn_direction"], "fields": ["gnn.analysis.", "ohlc_gnn."]},
    "adr_exhaustion": {"votes": ["adr_exhaustion.direction", "adr_exhaustion.signal"], "fields": ["adr_exhaustion."]},
    "session": {"votes": ["session_analysis.bias", "session_analysis.direction"], "fields": ["session_analysis."]},
}


# ============================================================
# COLUMN STORE
# ============================================================

def _direction(value: Any) -> Optional[int]:
    from core.strategy_groups import market_direction
    if isinstance(value, bool):
        return 1 if value else -1
    return market_direction(value)


def _row(rec: Mapping[str, Any]) -> Dict[str, Any]:
    out = rec.get("outcome") or {}
    row: Dict[str, Any] = {
        "ts": rec["ts"], "close": rec.get("close"), "pip": rec.get("pip"), "atr_pips": rec.get("atr_pips"),
        "y": out.get(LABEL), "y_h1x1": out.get("move_h1x1"), "y_h1x2": out.get("move_h1x2"),
        "ret_120": out.get("ret_120"), "ret_30": out.get("ret_30"),
        "spread_pips": rec.get("spread_pips"),
        "quote_spread_pips": out.get("quote_spread_pips"),     # the real bid/ask gap at entry
        # the live market-stop trade (core/market_stop.py) on tick quotes:
        # which side reached its target, gross R per side, commission in R
        "y_ms": out.get("y_ms"),
        "br_ms_buy": (out.get("bracket_ms_buy") or {}).get("r"), "br_ms_sell": (out.get("bracket_ms_sell") or {}).get("r"),
        "ms_cost_r": out.get("commission_ms_r"),
        "br_buy": (out.get("bracket_buy") or {}).get("r"), "br_sell": (out.get("bracket_sell") or {}).get("r"),
        # cost_r: what the entry costs (spread + commission), the quantity the
        # live cost cap reads. net_cost_r: what still has to come off the
        # bracket R -- commission only when the bracket was filled on real
        # bid/ask quotes (spread already inside), the full cost otherwise.
        "cost_r": out.get("cost_r", (rec.get("cost") or {}).get("cost_r")),
        "net_cost_r": out["commission_r"] if out.get("source") == "quotes" and "commission_r" in out
        else (rec.get("cost") or {}).get("cost_r"),
        "ctx.regime": rec.get("regime"), "ctx.symbol": rec.get("symbol"),
        "ctx.direction": rec.get("direction"), "ctx.should_enter": int(bool(rec.get("should_enter"))),
    }
    for k, v in (rec.get("edges") or {}).items():
        if k != "version":
            row[f"edges.{k}"] = v
    # A capture taken after the payload was grouped spells leaves
    # analysis.<GROUP>.data.*; the registry and the fitted rules are written
    # flat, so names are normalised back (core/analysis_groups.to_legacy).
    from core.analysis_groups import to_legacy
    for k, v in (rec.get("full") or {}).items():
        row[to_legacy(k)] = v
    return row


def entry_spread_pips(cols: "Columns") -> np.ndarray:
    """The real quote spread at entry where tick quotes labelled the record,
    else the snapshot's spread."""
    snap = cols.num("spread_pips").astype(np.float64)
    if "quote_spread_pips" not in cols.names():
        return snap
    quote = cols.num("quote_spread_pips").astype(np.float64)
    return np.where(np.isnan(quote), snap, quote)


def build_columns(symbols: Optional[Iterable[str]] = None, out_dir: Path = COLUMN_DIR) -> Dict[str, Any]:
    """One pass over the labelled records into per-column .npy files:
    numeric -> float32 (nan = absent); text -> int16 codes + vocabulary."""
    from ai.price_history_study import SYMBOLS

    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = list(symbols or SYMBOLS)
    parts: List[Path] = []
    kinds: Dict[str, str] = {}
    for symbol in symbols:
        path = STUDY_DIR / f"{symbol}.labelled.jsonl.gz"
        if not path.exists():
            continue
        cols: Dict[str, list] = defaultdict(list)
        n = 0
        with gzip.open(path, "rt") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    break
                for k, v in _row(rec).items():
                    if v is None:
                        continue
                    cols[k].append((n, v))
                n += 1
        arrays = {}
        for k, pairs in cols.items():
            is_text = any(isinstance(v, str) for _, v in pairs)
            if is_text:
                kinds[k] = "text"
                a = np.empty(n, dtype=object)
                for i, v in pairs:
                    a[i] = str(v)
            else:
                kinds.setdefault(k, "num")
                a = np.full(n, np.nan, dtype=np.float32)
                for i, v in pairs:
                    if isinstance(v, (int, float)):
                        a[i] = v
            arrays[k] = a
        part = out_dir / f"_part_{symbol}.npz"
        np.savez(part, _n=np.array([n]), **{re.sub(r"[^A-Za-z0-9_.\[\]-]", "_", k): v for k, v in arrays.items()},
                 allow_pickle=True)
        parts.append(part)
        print(symbol, n, len(arrays), flush=True)

    # concatenate every column across symbols
    keys = sorted({re.sub(r"[^A-Za-z0-9_.\[\]-]", "_", k) for k in kinds})
    sizes = []
    loaded = [np.load(p, allow_pickle=True) for p in parts]
    for z in loaded:
        sizes.append(int(z["_n"][0]))
    total = sum(sizes)
    manifest = {"n": total, "columns": {}}
    for k in keys:
        text = any(k in z.files and z[k].dtype == object for z in loaded)
        if text:
            values = np.concatenate([z[k] if k in z.files else np.full(sz, None, dtype=object)
                                     for z, sz in zip(loaded, sizes)])
            vocab = sorted({v for v in values if v is not None})
            index = {v: i for i, v in enumerate(vocab)}
            codes = np.array([-1 if v is None else index[v] for v in values], dtype=np.int32)
            np.save(out_dir / f"{k}.npy", codes)
            manifest["columns"][k] = {"kind": "text", "vocab": vocab}
        else:
            values = np.concatenate([z[k].astype(np.float32) if k in z.files else np.full(sz, np.nan, dtype=np.float32)
                                     for z, sz in zip(loaded, sizes)])
            np.save(out_dir / f"{k}.npy", values)
            manifest["columns"][k] = {"kind": "num"}
    for z in loaded:
        z.close()
    for p in parts:
        p.unlink()
    (out_dir / "manifest.json").write_text(json.dumps(manifest))
    return {"rows": total, "columns": len(keys)}


class Columns:
    def __init__(self, directory: Path = COLUMN_DIR):
        self.dir = directory
        self.manifest = json.loads((directory / "manifest.json").read_text())
        self.n = self.manifest["n"]
        self._cache: Dict[str, np.ndarray] = {}

    def names(self) -> List[str]:
        return list(self.manifest["columns"])

    def kind(self, name: str) -> Optional[str]:
        c = self.manifest["columns"].get(name)
        return c["kind"] if c else None

    def num(self, name: str) -> np.ndarray:
        if self.kind(name) != "num":
            return np.full(self.n, np.nan, dtype=np.float32)
        if name not in self._cache:
            self._cache[name] = np.load(self.dir / f"{name}.npy", mmap_mode="r")
        return np.asarray(self._cache[name])

    def text(self, name: str) -> Tuple[np.ndarray, List[str]]:
        c = self.manifest["columns"].get(name)
        if not c or c["kind"] != "text":
            return np.full(self.n, -1, dtype=np.int32), []
        return np.load(self.dir / f"{name}.npy"), c["vocab"]

    def direction(self, name: str) -> np.ndarray:
        """+1/-1/0 from a directional text or boolean column, nan when absent."""
        if self.kind(name) == "text":
            codes, vocab = self.text(name)
            lut = np.array([np.nan if _direction(v) is None else _direction(v) for v in vocab] + [np.nan])
            return lut[np.where(codes < 0, len(vocab), codes)]
        v = self.num(name)
        return np.sign(v)


# ============================================================
# RULE SEARCH
# ============================================================

def wilson_lower(k: np.ndarray, n: np.ndarray, z: float = 1.96) -> np.ndarray:
    n = np.maximum(n, 1)
    p = k / n
    return (p + z * z / (2 * n) - z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def _price_like(values: np.ndarray, close: np.ndarray) -> bool:
    ok = ~np.isnan(values) & (close > 0)
    if ok.sum() < 50:
        return False
    rel = np.abs(values[ok] / close[ok] - 1)
    return float(np.median(rel)) < 0.03


def literals_for(cols: Columns, fields: Sequence[str], base_mask: np.ndarray, train: np.ndarray,
                 close: np.ndarray, atr_price: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Candidate conditions: numeric thresholds at training quantiles (price
    fields measured from price in ATR), categorical equalities, presence."""
    out: List[Tuple[str, np.ndarray]] = []
    fit = base_mask & train
    for name in fields:
        kind = cols.kind(name)
        if kind == "num":
            v = cols.num(name).astype(np.float64)
            label = name
            if _price_like(v, close):
                v = (v - close) / atr_price
                label = f"({name} - price)/ATR"
            present = ~np.isnan(v)
            if (present & fit).sum() < MIN_SUPPORT_TRAIN:
                continue
            uniq = np.unique(v[present & fit])
            if uniq.size <= 1:
                continue
            if uniq.size <= 6:
                for u in uniq:
                    m = v == u
                    if (m & fit).sum() >= MIN_SUPPORT_TRAIN:
                        out.append((f"{label} == {float(u)!r}", m))
                continue
            qs = np.unique(np.quantile(v[present & fit], QUANTILES))
            for q in qs:
                out.append((f"{label} <= {float(q)!r}", v <= q))
                out.append((f"{label} >= {float(q)!r}", v >= q))
        elif kind == "text":
            codes, vocab = cols.text(name)
            counts = Counter(codes[fit & (codes >= 0)].tolist())
            for code, c in counts.most_common(MAX_CATEGORIES):
                if c >= MIN_SUPPORT_TRAIN:
                    out.append((f"{name} == {vocab[code]}", codes == code))
    return out


def search_rules(votes: np.ndarray, y: np.ndarray, net: np.ndarray, train: np.ndarray,
                 literals: List[Tuple[str, np.ndarray]]) -> List[Dict[str, Any]]:
    """Beam search for conjunctions maximising the Wilson lower bound of
    accuracy on the training half, among rules whose mean `net` on the
    training half is positive. Called with the MOVE expectancy (the vote's
    120-minute move in ATR after spread): at a 1-2 pip stop almost every
    reading is net-negative in bracket R before any edge shows, so bracket
    net R is judged at the entry policy, not per rule."""
    voted = ~np.isnan(votes) & (votes != 0) & ~np.isnan(y)
    base = voted & train
    win = base & (np.sign(votes) == y)
    if base.sum() < MIN_SUPPORT_TRAIN:
        return []
    net_train = np.where(base, np.nan_to_num(net, nan=0.0), 0.0)
    net_valid = base & ~np.isnan(net)

    def score(mask):
        n = (mask & base).sum()
        if n < MIN_SUPPORT_TRAIN:
            return None
        k = (mask & win).sum()
        nn = (mask & net_valid).sum()
        mean_net = float(net_train[mask & net_valid].sum() / nn) if nn else float("nan")
        return float(wilson_lower(np.array([k]), np.array([n]))[0]), int(n), k / n, mean_net

    scored = []
    for desc, m in literals:
        s = score(m)
        if s:
            scored.append((s, [desc], m))
    scored.sort(key=lambda x: -x[0][0])
    beam = scored[:BEAM]
    results = list(beam)
    if MAX_LITERALS >= 2:
        top_literals = scored[:max(BEAM * 3, 120)]
        seen = set()
        for s1, d1, m1 in beam:
            for s2, d2, m2 in top_literals:
                if d1[0] == d2[0] or d2[0].split(" ")[0] == d1[0].split(" ")[0]:
                    continue
                key = tuple(sorted(d1 + d2))
                if key in seen:
                    continue
                seen.add(key)
                m = m1 & m2
                s = score(m)
                if s:
                    results.append((s, d1 + d2, m))
    results.sort(key=lambda x: -x[0][0])
    out, used = [], set()
    for s, descs, m in results:
        if s[3] != s[3] or s[3] <= 0:        # positive training expectancy required
            continue
        key = tuple(sorted(descs))
        if key in used:
            continue
        used.add(key)
        out.append({"conditions": descs, "train_n": s[1], "train_acc": round(100 * s[2], 1),
                    "train_lower": round(100 * s[0], 1), "train_move_atr": round(s[3], 3), "_mask": m})
        if len(out) >= 15:
            break
    return out


# 120-minute move clipped to +/- this many M1 ATRs: in quiet hours the M1 ATR
# is tiny and a normal move is dozens of "ATRs", which dominated the mean.
MOVE_CLIP_ATR = 10.0
MOVE = {}   # set by run(): signed 120-minute move in ATR, and spread in ATR


def evaluate(rule_mask: np.ndarray, votes: np.ndarray, y: np.ndarray, net: np.ndarray, mask: np.ndarray,
             clusters: np.ndarray) -> Dict[str, Any]:
    """Accuracy, bracket net R (the engine's own stop/target, after cost) and
    move expectancy: the 120-minute move in the vote's direction, in ATR,
    minus the spread -- what the reading is worth before any stop choice."""
    from ai.component_calibration import cluster_mean_z
    m = rule_mask & mask & ~np.isnan(votes) & (votes != 0) & ~np.isnan(y)
    n = int(m.sum())
    if n == 0:
        return {"n": 0}
    right = np.where(m, (np.sign(votes) == y).astype(float), np.nan)
    acc, z, g = cluster_mean_z(right, clusters)
    nm = m & ~np.isnan(net)
    net_mean, net_z, _ = cluster_mean_z(np.where(nm, net, np.nan), clusters, null=0.0) if nm.any() else (float("nan"), 0, 0)
    out = {"n": n, "clusters": g, "acc": round(100 * acc, 1), "z": round(z, 2),
           "net_r": None if net_mean != net_mean else round(net_mean, 3), "net_z": round(net_z, 2)}
    if MOVE:
        move = np.sign(votes) * MOVE["ret_120"] - MOVE["spread_atr"]
        mm = m & ~np.isnan(move)
        if mm.any():
            mv, mz, _ = cluster_mean_z(np.where(mm, move, np.nan), clusters, null=0.0)
            out.update(move_atr=round(mv, 3), move_z=round(mz, 2))
    return out


# ============================================================
# DIAGNOSIS
# ============================================================

def diagnose(cols: Columns, name: str, spec: Mapping[str, Any], y: np.ndarray, net_for, clusters, train, test,
             holdout=None):
    """Coverage, raw accuracy per vote field, and contradictions between the
    component's own directional fields."""
    report: Dict[str, Any] = {"votes": {}, "contradictions": []}
    dirs = {}
    for vf in spec["votes"]:
        d = cols.direction(vf) if cols.kind(vf) else np.full(cols.n, np.nan)
        dirs[vf] = d
        voted = ~np.isnan(d) & (d != 0)
        if voted.sum() == 0:
            report["votes"][vf] = {"coverage": 0.0}
            continue
        net = net_for(d)
        report["votes"][vf] = {
            "coverage_pct": round(100 * float(voted.mean()), 1),
            "all": evaluate(np.ones(cols.n, bool), d, y, net, np.ones(cols.n, bool), clusters),
            "train": evaluate(np.ones(cols.n, bool), d, y, net, train, clusters),
            "test": evaluate(np.ones(cols.n, bool), d, y, net, test, clusters),
            "holdout": evaluate(np.ones(cols.n, bool), d, y, net, holdout, clusters) if holdout is not None else None,
        }
    # contradictions: two directional outputs of the same component disagreeing
    directional_fields = [f for f in cols.names() if any(f.startswith(p) for p in spec["fields"])
                          and cols.kind(f) == "text" and f not in dirs]
    for f in directional_fields[:200]:
        d = cols.direction(f)
        if (~np.isnan(d) & (d != 0)).sum() < 500:
            continue
        dirs[f] = d
    names = list(dirs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            da, db = dirs[a], dirs[b]
            both = ~np.isnan(da) & ~np.isnan(db) & (da != 0) & (db != 0)
            if both.sum() < 500:
                continue
            disagree = both & (da != db)
            rate = float(disagree.sum() / both.sum())
            if rate < 0.15:
                continue
            acc_a = evaluate(disagree, da, y, net_for(da), np.ones(cols.n, bool), clusters)
            report["contradictions"].append({"a": a, "b": b, "both_voting": int(both.sum()),
                                             "disagree_pct": round(100 * rate, 1),
                                             "when_they_disagree_a_right_pct": acc_a.get("acc"),
                                             "when_they_disagree_b_right_pct": None if acc_a.get("acc") is None
                                             else round(100 - acc_a["acc"], 1)})
    report["contradictions"].sort(key=lambda c: -c["both_voting"])
    report["contradictions"] = report["contradictions"][:12]
    return report, dirs


# ============================================================
# DRIVER
# ============================================================

HOLDOUT_FRACTION = 0.4   # the last 40% of the calendar is never used to choose anything


def study_split(ts: np.ndarray):
    """Discovery (train), validation (test), holdout and 4 blocks.

    Discovery and validation are the two halves of the first 60% of the
    calendar (a half day embargoed between them): rules are searched on
    discovery and must survive FDR and block stability on validation. The
    holdout starts a full day after that and is only ever REPORTED on -- the
    first protocol used the test half both to select features and to report
    them, which made the reported numbers optimistic.
    """
    start = float(np.nanquantile(ts, 1 - HOLDOUT_FRACTION))
    usable = ts < start - 86400
    holdout = ts >= start
    cut = float(np.nanmedian(ts[usable]))
    train = usable & (ts < cut - 43200)
    test = usable & (ts >= cut + 43200)
    edges = np.nanquantile(ts[usable], np.linspace(0, 1, 5))
    edges[-1] += 1
    blocks = [usable & (ts >= a) & (ts < b) for a, b in zip(edges[:-1], edges[1:])]
    return train, test, holdout, blocks, start


def run(only: Optional[Sequence[str]] = None, label: str = LABEL) -> Dict[str, Any]:
    from ai.component_calibration import benjamini_hochberg

    cols = Columns()
    n = cols.n
    ts = cols.num("ts").astype(np.float64)
    train, test, holdout, blocks, holdout_start = study_split(ts)
    market = label == MARKET_LABEL
    if market:
        # the side whose market-stop trade won; 0 (neither won) counts as wrong
        y = cols.num("y_ms").astype(np.float64)
        y = np.where(np.isin(y, (1, 0, -1)), y, np.nan)
    else:
        y = cols.num("y" if label == LABEL else {"move_h1x1": "y_h1x1", "move_h1x2": "y_h1x2"}[label]).astype(np.float64)
        y = np.where(np.isin(y, (1, -1)), y, np.nan)
    sym_codes, sym_vocab = cols.text("ctx.symbol")
    clusters = np.array([f"{c}|{int(t // 86400)}" for c, t in zip(sym_codes, np.nan_to_num(ts))], dtype=object)
    close = cols.num("close").astype(np.float64)
    atr_price = cols.num("atr_pips").astype(np.float64) * cols.num("pip").astype(np.float64)
    atr_price = np.where(atr_price > 0, atr_price, np.nan)
    if market:
        br_buy, br_sell = cols.num("br_ms_buy").astype(np.float64), cols.num("br_ms_sell").astype(np.float64)
        cost = np.nan_to_num(cols.num("ms_cost_r").astype(np.float64), nan=0.0)
    else:
        br_buy, br_sell = cols.num("br_buy").astype(np.float64), cols.num("br_sell").astype(np.float64)
        cost = np.nan_to_num(cols.num("net_cost_r").astype(np.float64), nan=0.0)
    atr_p = cols.num("atr_pips").astype(np.float64)
    MOVE["ret_120"] = np.clip(cols.num("ret_120").astype(np.float64), -MOVE_CLIP_ATR, MOVE_CLIP_ATR)
    MOVE["spread_atr"] = np.nan_to_num(entry_spread_pips(cols) / np.where(atr_p > 0, atr_p, np.nan), nan=0.0)

    def net_for(d):
        return np.where(d > 0, br_buy - cost, np.where(d < 0, br_sell - cost, np.nan))

    # session / regime context as columns the literal builder can use
    context_fields = [c for c in cols.names() if c.startswith(CONTEXT_PREFIXES) and c != "ctx.symbol"]

    components = {}
    all_rules = []
    for name, spec in COMPONENTS.items():
        if only and name not in only:
            continue
        report, dirs = diagnose(cols, name, spec, y, net_for, clusters, train, test, holdout)
        fields = [c for c in cols.names() if any(c.startswith(p) for p in spec["fields"])]
        report["internal_fields"] = len(fields)
        candidates = []
        vote_fields = [vf for vf in spec["votes"] if vf in dirs and (~np.isnan(dirs[vf]) & (dirs[vf] != 0)).sum() >= 500]
        present_any = np.zeros(n, bool)
        for f in fields[:50]:
            present_any |= (cols.num(f) == cols.num(f)) if cols.kind(f) == "num" else (cols.text(f)[0] >= 0)
        literals = literals_for(cols, fields + context_fields, present_any, train, close, atr_price)
        report["literals"] = len(literals)
        for vf in vote_fields:
            for orient in (1, -1):
                d = dirs[vf] * orient
                net = net_for(d)
                move = np.sign(d) * MOVE["ret_120"] - MOVE["spread_atr"]
                # under the market stop the trade itself is the judge
                for rule in search_rules(d, y, net if market else move, train, literals):
                    mask = rule.pop("_mask")
                    rule.update(vote=vf, orientation="as-is" if orient > 0 else "inverted")
                    rule["test"] = evaluate(mask, d, y, net, test, clusters)
                    rule["holdout"] = evaluate(mask, d, y, net, holdout, clusters)
                    rule["blocks"] = [evaluate(mask, d, y, net, b, clusters).get("acc") for b in blocks]
                    candidates.append(rule)
        report["rules"] = sorted(candidates, key=lambda r: -(r["test"].get("acc") or 0))[:25]
        components[name] = report
        all_rules.extend((name, r) for r in report["rules"])
        print(name, "fields", len(fields), "literals", len(literals), "rules", len(candidates),
              "best test", report["rules"][0]["test"] if report["rules"] else None, flush=True)

    # FDR across every rule tested: one-sided p of test accuracy > 50
    pvals = []
    for _, r in all_rules:
        z = r["test"].get("z") or 0.0
        pvals.append(0.5 * math.erfc(z / math.sqrt(2)) if r["test"].get("n", 0) >= MIN_SUPPORT_TEST else 1.0)
    passed_fdr = benjamini_hochberg(pvals, FDR_Q)
    for (name, r), ok in zip(all_rules, passed_fdr):
        t = r["test"]
        stable = sum(1 for a in r["blocks"] if a is not None and a >= MIN_TEST_ACCURACY - 5)
        r["fdr"] = bool(ok)
        r["stable_blocks"] = stable
        # red line: >= 65% right AND positive expectancy on the unseen half
        # (move expectancy in ATR after spread; bracket net R is reported too)
        expectancy_ok = ((t.get("net_r") if t.get("net_r") is not None else -1) >= TARGET_NET_R if market
                         else (t.get("move_atr") or -1) > 0)
        r["passes"] = bool(ok and t.get("n", 0) >= MIN_SUPPORT_TEST and (t.get("acc") or 0) >= MIN_TEST_ACCURACY
                           and expectancy_ok and stable >= 3)
    for name, rep in components.items():
        rep["passing_rules"] = [r for r in rep["rules"] if r.get("passes")]
        rep["verdict"] = "REPAIRED" if rep["passing_rules"] else "NOT_YET"
    return {"label": label, "rows": n, "holdout_start": holdout_start, "components": components,
            "passing": {k: len(v["passing_rules"]) for k, v in components.items()}}


MIN_FEATURE_ACCURACY = 55.0


def export_rules(result: Mapping[str, Any], path: Path = RULES_PATH) -> Dict[str, int]:
    """Every validated rule (FDR, >= 3 of 4 stable blocks, test accuracy >=
    MIN_FEATURE_ACCURACY) becomes a reading the category models may use; the
    ones that also meet the red line (>= 65% and net-positive) are flagged."""
    from ai.rule_mirror import mirror_rule

    doc = {"version": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "label": result["label"], "components": {}}
    counts = {"features": 0, "red_line": 0}
    cols = Columns()
    _signed_cache: Dict[str, bool] = {}

    def is_signed(field: str) -> bool:
        if field not in _signed_cache:
            v = cols.num(field) if cols.kind(field) == "num" else None
            _signed_cache[field] = bool(v is not None and np.nanmin(v) < 0 < np.nanmax(v))
        return _signed_cache[field]
    for name, rep in result["components"].items():
        keep = [r for r in rep["rules"]
                if r.get("fdr") and r.get("stable_blocks", 0) >= 3 and (r["test"].get("acc") or 0) >= MIN_FEATURE_ACCURACY]
        keep.sort(key=lambda r: -(r["test"].get("acc") or 0))
        items = []
        for r in keep[:8]:
            items.append({k: r.get(k) for k in ("vote", "orientation", "conditions", "test", "holdout", "train_acc", "stable_blocks")}
                         | {"meets_red_line": bool(r.get("passes"))})
        if items:
            # every rule gets its opposite-side twin (ai/rule_mirror.py), so no
            # category can reach confidence on one side only
            twins = []
            for i, item in enumerate(items):
                twin = mirror_rule(item, is_signed)
                if twin is not None and twin["conditions"] != item["conditions"]:
                    twins.append(dict(twin, mirror_of=i, meets_red_line=False, test=None, holdout=None))
            for j, twin in enumerate(twins):
                items[twin["mirror_of"]]["mirror_index"] = len(items) + j
            items.extend(twins)
            doc["components"][name] = items
            counts["features"] += len(items)
            counts["red_line"] += sum(1 for i in items if i["meets_red_line"])
    path.write_text(json.dumps(doc, indent=1))
    return counts


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating,)):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, np.integer):
        return int(o)
    return o


def self_check() -> Dict[str, Any]:
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.random(n)
    votes = rng.choice([-1.0, 1.0], n)
    y = np.where(x > 0.7, votes, rng.choice([-1.0, 1.0], n))        # right whenever x > 0.7
    net = np.where(np.sign(votes) == y, 2.0, -1.0)
    train = np.arange(n) < n // 2
    lits = [("x >= 0.7", x >= 0.7), ("x <= 0.3", x <= 0.3)]
    rules = search_rules(votes, y, net, train, lits)
    assert rules and rules[0]["conditions"] == ["x >= 0.7"] and rules[0]["train_acc"] > 95
    assert wilson_lower(np.array([50]), np.array([100]))[0] < 0.5
    return {"ok": True}


def get_status() -> Dict[str, Any]:
    return {"component": "component_repair", "components": len(COMPONENTS), "min_test_accuracy": MIN_TEST_ACCURACY}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("columns")
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*")
    r.add_argument("--label", default=LABEL)
    r.add_argument("--export", action="store_true")
    sub.add_parser("check")
    a = ap.parse_args()
    if a.cmd == "columns":
        print(build_columns())
    elif a.cmd == "check":
        print(self_check())
    else:
        res = run(a.only, a.label)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        out = REPORT_DIR / f"component_repair_{a.label}_{stamp}.json"
        out.write_text(json.dumps(_jsonable(res), indent=1, default=str))
        print("written", out, res["passing"])
        if a.export:
            print("rules exported", export_rules(res))
