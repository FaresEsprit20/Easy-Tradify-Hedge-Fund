# ============================================================
# STRATEGY FAMILIES -- THE SYSTEM IS FOUR STRATEGIES IN A TRENCH COAT
# ============================================================
# FILE: ai/strategy_families.py
#
# THE HYPOTHESIS THIS EXISTS TO TEST
# ---------------------------------
# The probability chain SUMS the contributions of components that belong to
# mutually contradictory strategies:
#
#   TREND FOLLOWING   buy strength, sell weakness  (trend, cascade, ADX,
#                     H1 alignment, EMA structure)
#   MEAN REVERSION    buy weakness, sell strength  (RSI, stochastic,
#                     Bollinger, exhaustion, ADR exhaustion, round numbers)
#   STRUCTURE / SMC   trade the level              (order blocks, FVG, nested
#                     zones, supply/demand, liquidity sweeps)
#   WAVE              trade the count              (Elliott, wave lattice,
#                     chart patterns)
#
# Trend and mean reversion are OPPOSITES. One says buy strength, the other
# says buy weakness. Adding them means that in a trend the trend components
# are right and the reversion components are wrong, in a range the reverse
# holds -- and averaged over a mixed sample the two cancel.
#
# That is not a metaphor. It is a mechanical explanation for the single most
# important measurement on this account: direction entropy 1.0000, meaning the
# entries carry NO directional information. Summing opposing strategies
# produces exactly that, and it explains why nine separate searches over these
# components -- inversion, 82 filters, 2,560 configs, a 1,251-field audit --
# all found nothing. They searched for better WEIGHTS. The defect is the
# SUMMATION.
#
# WHAT A FIX WOULD LOOK LIKE
# --------------------------
# Not reweighting. SELECTION: decide which strategy is valid for the current
# regime and let that family speak, instead of averaging it against its own
# opposite. This module measures whether that is true before anything is
# changed -- because "trend works in trends" is intuitive, widely believed,
# and still has to be demonstrated on this account's own trades.
#
# WHAT IS TESTED
# --------------
#   1. each family ALONE -- does trend following work here at all?
#   2. AGREEMENT -- when families point the same way, is there edge?
#   3. CONFLICT -- when trend and reversion disagree, is the aggregate noise?
#      (the cancellation, measured directly rather than assumed)
#   4. REGIME SELECTION -- does trend work in trending regimes and reversion
#      in ranging ones? This is the actual claim, and it is one hypothesis
#      per family, not a search over thousands.
# ============================================================

from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

STRATEGY_FAMILIES_VERSION = "1.0"

# Ledger steps and component paths, grouped by the strategy they implement.
# Matched as substrings against the field path, so a component is classified
# by what it IS rather than by where it happens to sit in the payload.
FAMILIES: Dict[str, Tuple[str, ...]] = {
    # --- directional strategies, and each other's opposites ---------------
    "TREND": ("trend_cascade", "h1_alignment", "trend_confirmation",
              "indicators.trend", "components.trend", "ema", "adx"),
    "MEAN_REVERSION": ("exhaustion", "rsi", "stochastic", "bollinger",
                       "round_numbers", "wave_c", "divergence"),

    # --- SMC, split apart. Lumping these together hid that they behave
    #     differently: order blocks, gaps, zones and sweeps are distinct
    #     ideas that happen to share a vocabulary.
    "SMC_STRUCTURE": ("smc", "choch", "bos", "market_structure"),
    "ORDER_FLOW": ("order_flow", "liquidity", "sweep", "absorption"),
    "FVG": ("fvg_ifvg", "fvg", "imbalance"),
    "ZONES": ("nested_zone", "supply_demand", "discount", "poi"),
    "SUPPORT_RESISTANCE": ("support_resistance", "pivot"),

    # --- volume and participation -----------------------------------------
    "VOLUME_PROFILE": ("volume_profile", "poc", "value_area"),
    "PARTICIPATION": ("rvam", "volume_confirmation"),
    "VWAP": ("vwap",),

    # --- pattern / wave, split: a chart pattern and an Elliott count are
    #     different claims and were never scored separately -----------------
    "PATTERN": ("pattern",),
    "ELLIOTT_WAVE": ("elliott", "wave_lattice", "wave_c_fibonacci"),

    # --- standalone subsystems, each its own family ------------------------
    "GNN": ("gnn", "ohlc_gnn"),
    "VOLATILITY": ("ttm_squeeze", "squeeze", "volatility_protection", "atr"),
    "EXHAUSTION_ADR": ("adr_exhaustion", "adr"),
    "MACRO": ("dxy_confluence", "dxy"),
    "EXPECTED_VALUE": ("expected_value",),
    "EXECUTION": ("gap_slippage", "spread"),
    "WYCKOFF": ("wyckoff",),
    "SESSION": ("session",),
    "NEWS": ("news",),
    "MICROSTRUCTURE": ("micro_structure", "microstructure"),
}

# Families that are DIRECT OPPOSITES. When these disagree the aggregate is
# adding a buy signal to a sell signal and calling the result a probability.
OPPOSING_PAIRS = (("TREND", "MEAN_REVERSION"),)


def classify(name: str) -> Optional[str]:
    """Which strategy family a component belongs to, or None if unmapped."""
    lowered = str(name).lower()
    # Longest token wins. First-match-wins made classification depend on dict
    # ORDER: "adr_exhaustion" matched MEAN_REVERSION's "exhaustion" before
    # EXHAUSTION_ADR's "adr_exhaustion" could be considered, so a whole family
    # was unreachable. Specificity is the right tie-break, and it does not
    # depend on how the table happens to be written.
    best_family, best_len = None, 0
    for family, tokens in FAMILIES.items():
        for token in tokens:
            if token in lowered and len(token) > best_len:
                best_family, best_len = family, len(token)
    return best_family


def family_scores(trade: Mapping[str, Any]) -> Dict[str, float]:
    """
    One score per family, from the probability ledger.

    Each family's score is the SUM of its members' deltas, expressed relative
    to the direction actually traded. A positive score means that family
    supported this trade; negative means it opposed it. Families with no
    contributing step are absent rather than zero -- "this family did not
    speak" and "this family was neutral" are different facts.
    """
    from ai import trade_repository as repo

    ledger = repo.ledger_of(trade)
    if not ledger:
        return {}
    best = repo.best_direction_of(trade)
    frame = 1 if best == trade.get("direction") else -1

    scores: Dict[str, float] = {}
    for step in ledger:
        family = classify(step.get("step") or "")
        delta = step.get("delta")
        if family and isinstance(delta, (int, float)) and abs(delta) > 1e-9:
            scores[family] = scores.get(family, 0.0) + float(delta) * frame
    return scores


def build_rows(trades: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Per trade: the family scores, the regime, and the realised R."""
    rows: List[Dict[str, Any]] = []
    for trade in trades:
        entry = trade.get("entry") or {}
        close = trade.get("close_data") or {}
        ep, sl, cp = entry.get("price"), entry.get("stop_loss"), close.get("close_price")
        if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)) or ep == sl:
            continue
        scores = family_scores(trade)
        if not scores:
            continue
        sign = 1 if trade.get("direction") == "BUY" else -1
        rows.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "opened_at": str(trade.get("opened_at") or ""),
            "r": sign * (cp - ep) / abs(ep - sl),
            "scores": scores,
            "regimes": _regime_of(trade) or {},
        })
    rows.sort(key=lambda r: r["opened_at"])
    field = _pick_regime_field(rows)
    for row in rows:
        row["regime_field"] = field
        row["regime"] = (row.get("regimes") or {}).get(field) if field else None
    return rows


def _regime_of(trade: Mapping[str, Any]) -> Optional[str]:
    """
    The market state the analysis recorded, from wherever it stored it.

    Several paths are tried because the payload spells this differently in
    different subsystems, and a regime test that silently found nothing would
    be indistinguishable from a regime test that found no effect.
    """
    analysis = trade.get("analysis_at_open") or {}
    values = {}
    for path in REGIME_PATHS:
        node: Any = analysis
        for key in path:
            node = node.get(key) if isinstance(node, Mapping) else None
            if node is None:
                break
        if isinstance(node, str) and node:
            values[".".join(path)] = node
    return values or None


# Candidate regime fields, in no priority order -- the CHOICE is made in
# build_rows by which one actually varies. Returning the first match here was
# a real bug: `final_verdict.market_regime` resolves on every trade with the
# constant value "NORMAL", so it always won and the regime test could never
# compare two states. A constant label is not a regime.
REGIME_PATHS = (
    ("final_verdict", "market_regime"),
    ("decision_snapshot", "regime_3d", "trend_strength"),
    ("decision_snapshot", "regime_3d", "volatility_state"),
    ("trading_regime", "state"),
    ("volatility_protection", "regime"),
    ("session_analysis", "session"),
)


def _pick_regime_field(rows: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """
    The regime label with the most distinct values.

    A field present on every trade but constant carries no information, and
    preferring it silently disables the whole regime analysis.
    """
    import collections

    tally: Dict[str, collections.Counter] = {}
    for row in rows:
        for field, value in (row.get("regimes") or {}).items():
            tally.setdefault(field, collections.Counter())[value] += 1

    # BALANCE, not distinct count. Picking the field with the most distinct
    # values chose `final_verdict.market_regime`, which is "NORMAL" on 213 of
    # 215 trades and has two singleton values -- three categories, and no
    # comparison possible. A regime label is only useful if its classes are
    # actually populated, so the field with the smallest dominant class wins.
    best, best_share = None, 1.01
    for field, counter in tally.items():
        total = sum(counter.values())
        populated = [c for c in counter.values() if c >= 15]
        if total < 30 or len(populated) < 2:
            continue
        share = max(counter.values()) / total
        if share < best_share:
            best, best_share = field, share
    return best


# ============================================================
# THE TESTS
# ============================================================

def _split(rows: Sequence[Mapping[str, Any]], family: str
           ) -> Tuple[List[float], List[float]]:
    supports = [r["r"] for r in rows if (r["scores"].get(family) or 0) > 0]
    opposes = [r["r"] for r in rows if (r["scores"].get(family) or 0) < 0]
    return supports, opposes


def analyse(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
            rows: Optional[Sequence[Mapping[str, Any]]] = None,
            min_group: int = 12, folds: int = 3,
            permutations: int = 300) -> Dict[str, Any]:
    """
    Test the family hypothesis. A handful of pre-registered questions, not a
    search -- which is why this has real power where the 1,251-field audit had
    none.
    """
    from ai import edge_discovery as ed

    data = list(rows) if rows is not None else build_rows(trades or [])
    report: Dict[str, Any] = {
        "component": "strategy_families",
        "version": STRATEGY_FAMILIES_VERSION,
        "trades": len(data),
    }
    if len(data) < min_group * 3:
        report["ok"] = None
        report["reason"] = "only %d trades" % len(data)
        return report

    families = sorted({f for row in data for f in row["scores"]})
    report["families_present"] = families
    report["baseline"] = round(statistics.mean(r["r"] for r in data), 4)

    # ---- 1. each family alone ------------------------------------------
    solo = []
    for family in families:
        supports, opposes = _split(data, family)
        if len(supports) < min_group or len(opposes) < min_group:
            continue
        edge = statistics.mean(supports) - statistics.mean(opposes)
        n = min(len(supports), len(opposes))
        p = (ed.paired_pvalue(supports[:n], opposes[:n], trials=2000) if edge > 0
             else ed.paired_pvalue(opposes[:n], supports[:n], trials=2000))
        solo.append({
            "family": family, "n_supports": len(supports), "n_opposes": len(opposes),
            "r_supports": round(statistics.mean(supports), 4),
            "r_opposes": round(statistics.mean(opposes), 4),
            "edge": round(edge, 4), "p_value": round(p, 4),
            "win_supports": round(100.0 * sum(1 for r in supports if r > 0)
                                  / len(supports), 1),
        })
    report["per_family"] = sorted(solo, key=lambda s: -s["edge"])

    # ---- 2 & 3. agreement and conflict ---------------------------------
    conflicts = []
    for a, b in OPPOSING_PAIRS:
        both = [r for r in data
                if r["scores"].get(a) is not None and r["scores"].get(b) is not None]
        if len(both) < min_group * 2:
            continue
        agree = [r["r"] for r in both
                 if r["scores"][a] * r["scores"][b] > 0]
        conflict = [r["r"] for r in both
                    if r["scores"][a] * r["scores"][b] < 0]
        if len(agree) < min_group or len(conflict) < min_group:
            continue
        conflicts.append({
            "pair": [a, b],
            "n_agree": len(agree), "n_conflict": len(conflict),
            "conflict_rate": round(100.0 * len(conflict) / len(both), 1),
            "r_agree": round(statistics.mean(agree), 4),
            "r_conflict": round(statistics.mean(conflict), 4),
            "edge": round(statistics.mean(agree) - statistics.mean(conflict), 4),
            "win_agree": round(100.0 * sum(1 for r in agree if r > 0) / len(agree), 1),
            "win_conflict": round(100.0 * sum(1 for r in conflict if r > 0)
                                  / len(conflict), 1),
            "note": ("if the conflict group is noise and the agree group is "
                     "not, the chain is averaging a buy signal against a sell "
                     "signal and reporting the mean as a probability"),
        })
    report["opposition"] = conflicts

    # ---- 4. regime selection -------------------------------------------
    regimes = sorted({r["regime"] for r in data if r["regime"]})
    report["regimes_present"] = regimes
    selection = []
    for family in families:
        per_regime = []
        for regime in regimes:
            subset = [r for r in data if r["regime"] == regime]
            supports, opposes = _split(subset, family)
            if len(supports) < 8 or len(opposes) < 8:
                continue
            per_regime.append({
                "regime": regime, "n": len(subset),
                "edge": round(statistics.mean(supports) - statistics.mean(opposes), 4),
            })
        if len(per_regime) >= 2:
            edges = [g["edge"] for g in per_regime]
            selection.append({
                "family": family, "per_regime": per_regime,
                "spread": round(max(edges) - min(edges), 4),
                # The interesting case: the family HELPS in one regime and
                # HURTS in another. That is a component being asked the wrong
                # question, not a useless component.
                "flips_sign": max(edges) > 0 > min(edges),
            })
    report["regime_selection"] = sorted(selection, key=lambda s: -s["spread"])

    # ---- walk-forward on the strongest single claim ---------------------
    if report["per_family"]:
        best = report["per_family"][0]["family"]
        pooled_s, pooled_o, positive, used = [], [], 0, 0
        for train, test in ed.walk_forward_folds(data, folds):
            s, o = _split(test, best)
            if len(s) < 5 or len(o) < 5:
                continue
            used += 1
            pooled_s += s
            pooled_o += o
            if statistics.mean(s) - statistics.mean(o) > 0:
                positive += 1
        if pooled_s and pooled_o:
            report["walk_forward"] = {
                "family": best, "folds_positive": positive, "folds_used": used,
                "r_supports": round(statistics.mean(pooled_s), 4),
                "r_opposes": round(statistics.mean(pooled_o), 4),
                "edge": round(statistics.mean(pooled_s)
                              - statistics.mean(pooled_o), 4),
            }

    report["ok"] = bool(report["per_family"])
    return report


def discover_opposition(rows: Sequence[Mapping[str, Any]],
                        min_both: int = 25) -> List[Dict[str, Any]]:
    """
    Which families actually contradict each other, measured rather than assumed.

    OPPOSING_PAIRS encodes one belief -- that trend and mean reversion are
    opposites. That belief turned out to be right (they conflict on 91% of
    trades), but hardcoding it means every OTHER opposition stays invisible.
    Structure and wave, flow and trend, or any other pair may disagree just as
    systematically, and each disagreement is another place the chain is
    averaging a buy signal against a sell signal.

    Reported per pair:
      conflict_rate   how often they point opposite ways
      r_agree         outcome when they agree
      r_conflict      outcome when they fight
      agreement_edge  what requiring agreement would be worth

    A pair with a high conflict rate AND a large agreement edge is a place
    where summation is destroying information.
    """
    import itertools

    families = sorted({f for row in rows for f in row["scores"]})
    out = []
    for a, b in itertools.combinations(families, 2):
        both = [r for r in rows
                if r["scores"].get(a) is not None and r["scores"].get(b) is not None]
        if len(both) < min_both:
            continue
        agree = [r["r"] for r in both if r["scores"][a] * r["scores"][b] > 0]
        conflict = [r["r"] for r in both if r["scores"][a] * r["scores"][b] < 0]
        if not agree or not conflict:
            # One-sided: they either never agree or never fight. Still worth
            # reporting -- "these two NEVER agree" is a strong statement about
            # the design, not a missing measurement.
            out.append({"pair": [a, b], "n_both": len(both),
                        "n_agree": len(agree), "n_conflict": len(conflict),
                        "conflict_rate": round(100.0 * len(conflict) / len(both), 1),
                        "r_agree": None, "r_conflict": None,
                        "agreement_edge": None,
                        "note": "one side is empty; cannot compare outcomes"})
            continue
        out.append({
            "pair": [a, b], "n_both": len(both),
            "n_agree": len(agree), "n_conflict": len(conflict),
            "conflict_rate": round(100.0 * len(conflict) / len(both), 1),
            "r_agree": round(statistics.mean(agree), 4),
            "r_conflict": round(statistics.mean(conflict), 4),
            "agreement_edge": round(statistics.mean(agree)
                                    - statistics.mean(conflict), 4),
            "win_agree": round(100.0 * sum(1 for r in agree if r > 0)
                               / len(agree), 1),
        })
    return sorted(out, key=lambda o: -o["conflict_rate"])


def component_opposition(trades: Sequence[Mapping[str, Any]],
                         min_both: int = 30, top: int = 20
                         ) -> List[Dict[str, Any]]:
    """
    The same question one level down: which individual COMPONENTS contradict
    each other?

    Families are a hypothesis about how components group. This makes no such
    assumption -- it takes every pair of ledger steps and measures how often
    their contributions point opposite ways. A pair that disagrees on most
    trades is two components cancelling inside the sum, whatever family
    anybody assigned them to.

    This is how an opposition nobody predicted gets found.
    """
    import itertools
    from ai import trade_repository as repo

    vectors: List[Dict[str, float]] = []
    for trade in trades:
        ledger = repo.ledger_of(trade)
        if not ledger:
            continue
        best = repo.best_direction_of(trade)
        frame = 1 if best == trade.get("direction") else -1
        row = {}
        for step in ledger:
            name, delta = step.get("step"), step.get("delta")
            if name and isinstance(delta, (int, float)) and abs(delta) > 1e-9:
                row[name] = float(delta) * frame
        if row:
            vectors.append(row)

    names = sorted({n for v in vectors for n in v})
    out = []
    for a, b in itertools.combinations(names, 2):
        both = [v for v in vectors if a in v and b in v]
        if len(both) < min_both:
            continue
        conflict = sum(1 for v in both if v[a] * v[b] < 0)
        out.append({
            "pair": [a, b], "n_both": len(both),
            "conflict_rate": round(100.0 * conflict / len(both), 1),
        })
    return sorted(out, key=lambda o: -o["conflict_rate"])[:top]


def get_status() -> Dict[str, Any]:
    return {"component": "strategy_families",
            "version": STRATEGY_FAMILIES_VERSION,
            "families": sorted(FAMILIES),
            "opposing_pairs": [list(p) for p in OPPOSING_PAIRS]}


def self_check() -> Dict[str, Any]:
    """
    Prove the classifier maps components correctly and that the opposition
    test can detect a planted cancellation.
    """
    mapping = {
        "trend_cascade": "TREND",
        "h1_alignment": "TREND",
        "exhaustion": "MEAN_REVERSION",
        # the specificity tie-break: "adr_exhaustion" must NOT be swallowed
        # by MEAN_REVERSION's shorter "exhaustion" token
        "adr_exhaustion": "EXHAUSTION_ADR",
        "smc": "SMC_STRUCTURE",
        "order_flow": "ORDER_FLOW",
        "fvg_ifvg": "FVG",
        "nested_zone": "ZONES",
        "gnn": "GNN",
        "pattern": "PATTERN",
        "elliott_waves": "ELLIOTT_WAVE",
        "rvam": "PARTICIPATION",
        "vwap_context": "VWAP",
        "ttm_squeeze": "VOLATILITY",
        "dxy_confluence": "MACRO",
        "expected_value": "EXPECTED_VALUE",
        "gap_slippage": "EXECUTION",
    }
    misclassified = {k: classify(k) for k, v in mapping.items()
                     if classify(k) != v}

    # Planted cancellation, constructed so BOTH tests have something to see.
    #
    # r follows TREND exactly, so TREND must show a strong POSITIVE edge.
    # MEAN_REVERSION opposes TREND on two thirds of trades and agrees on the
    # remaining third, so it must show a NEGATIVE edge -- and the opposition
    # test gets both an agree group and a conflict group, which it needs to
    # compare. A fixture where the families ALWAYS disagree has no agree
    # group at all, and the test correctly refuses to score it.
    rows = []
    for i in range(240):
        good = 1.0 if i % 2 == 0 else -1.0
        agreeing = (i % 3 == 0)
        rows.append({"trade_id": "t%d" % i, "symbol": "X",
                     "opened_at": "%04d" % i,
                     "r": good,
                     "scores": {"TREND": good * 10.0,
                                "MEAN_REVERSION": (good if agreeing else -good) * 10.0},
                     "regime": "TREND" if i % 4 < 2 else "RANGE"})

    report = analyse(rows=rows, min_group=10, folds=2, permutations=0)
    per = {f["family"]: f["edge"] for f in report.get("per_family", [])}
    opposition = report.get("opposition") or []

    checks = {
        "classifier_correct": not misclassified,
        "misclassified": misclassified,
        "trend_edge_detected": per.get("TREND", 0) > 1.0,
        # Inverted by construction: it opposes the outcome on 2 of every
        # 3 trades, which gives an edge near -0.67 rather than -2.
        "reversion_edge_inverted": per.get("MEAN_REVERSION", 0) < -0.3,
        "opposition_detected": bool(opposition),
        "conflict_rate_measured": (opposition[0]["conflict_rate"]
                                   if opposition else None),
    }
    return {"component": "strategy_families",
            "version": STRATEGY_FAMILIES_VERSION,
            "checks": checks,
            "ok": (checks["classifier_correct"] and checks["trend_edge_detected"]
                   and checks["reversion_edge_inverted"]
                   and checks["opposition_detected"])}
