# ============================================================
# 360-DEGREE COMPONENT AUDIT
# ============================================================
# FILE: ai/component_audit_360.py
#
# Every scoreable field in the analysis payload, tested individually against
# real outcomes, with the same controls applied to all of them.
#
# WHY A DISCOVERY-BASED AUDIT RATHER THAN A HAND-WRITTEN LIST
# -----------------------------------------------------------
# The probability ledger exposes ~13 aggregate steps. Underneath those sit
# hundreds of individual readings -- RSI, stochastic, MACD, Bollinger,
# candlestick, wyckoff phase, order blocks, CHoCH, FVG/IFVG, supply and demand
# zones separately, support/resistance, volume confirmation, Elliott waves,
# the wave lattice -- and most have NEVER been scored against an outcome.
#
# A hand-written list would test what someone remembered to include. This
# walks the payload and finds every numeric and boolean field wherever it
# lives, so a component nobody thought about gets audited exactly like a
# component everybody argues about. Fields that turn out to be dead, constant,
# or absent are reported as such rather than silently skipped -- "this was
# never exercised" is a finding, not a gap.
#
# THE FOUR VERDICTS
# -----------------
#   DEAD      no variance, or present on too few trades. It cannot be
#             carrying information because it never changes. Several
#             components in this codebase have been in exactly this state
#             while appearing to work.
#   NOISE     varies, but does not separate outcomes beyond chance.
#   EDGE      separates outcomes, survives walk-forward AND a permutation
#             null AND FDR across every field tested.
#   INVERTED  separates outcomes BACKWARDS -- the reading is real but its
#             sign is wrong. This is not hypothetical: `pattern` was
#             sign-inverted on every SELL, worth +0.4880R once corrected.
#
# WHY THE CONTROLS ARE NOT OPTIONAL
# ---------------------------------
# Testing hundreds of fields guarantees that some will look excellent. On 215
# trades, a search of 82 hypotheses produced a 62% subset that collapsed to
# 25% out of sample, and a shuffled-outcome control showed the best subset of
# PURE NOISE still reaches 61.5%. So a field is only called an EDGE if it
# survives walk-forward folds, beats a permutation null, and clears
# Benjamini-Hochberg across the whole audit.
#
# DIRECTION FRAME
# ---------------
# A market reading ("RSI is high") means the opposite thing for a long and a
# short. Every numeric field is therefore tested twice: raw, and multiplied by
# the trade's direction. Testing only the raw form is how a genuinely
# predictive component measures as noise -- the two directions cancel.
# ============================================================

from __future__ import annotations

import logging
import random
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

AUDIT_VERSION = "1.0"

MAX_DEPTH = 6
MIN_COVERAGE = 0.30      # a field must be present on 30% of trades
# 2, not 3. A field needs at least two values to carry any information --
# one value is constant and therefore dead. Setting this to 3 silently
# discarded EVERY boolean flag in the payload (`nested`, `available`,
# `confirmed`, `supports`, `detected`...), which are among the most
# interesting readings the system produces and are explicitly converted to
# 1/0 by flatten() so they can be tested. Caught by self_check, which plants
# a binary signal and requires the audit to find it.
MIN_DISTINCT = 2
MIN_SIDE = 12            # each side of a split needs this many trades


def flatten(payload: Any, prefix: str = "", depth: int = 0
            ) -> Dict[str, float]:
    """
    Every numeric leaf in the payload, keyed by its path.

    Booleans become 1/0 -- a flag is a perfectly good feature and several of
    the most interesting readings here are flags (`nested`, `available`,
    `confirmed`). Strings are skipped: they are handled as categoricals
    elsewhere, and silently coercing them would invent an ordering.
    """
    out: Dict[str, float] = {}
    if depth > MAX_DEPTH:
        return out
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            name = str(key)
            if name.startswith("_") or name in ("timestamp", "probability_ledger"):
                continue
            path = f"{prefix}.{name}" if prefix else name
            out.update(flatten(value, path, depth + 1))
    elif isinstance(payload, (list, tuple)):
        # Lists are summarised by LENGTH. "How many order blocks / liquidity
        # events / waves were present" is a real feature; indexing into a
        # variable-length list is not -- element 3 is a different thing on
        # every trade.
        out[f"{prefix}.count"] = float(len(payload))
    elif isinstance(payload, bool):
        out[prefix] = 1.0 if payload else 0.0
    elif isinstance(payload, (int, float)):
        try:
            value = float(payload)
            if value == value and abs(value) != float("inf"):
                out[prefix] = value
        except Exception:
            pass
    return out


def build_rows(trades: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One row per trade: every flattened feature plus the realised R."""
    rows: List[Dict[str, Any]] = []
    for trade in trades:
        entry = trade.get("entry") or {}
        close = trade.get("close_data") or {}
        ep, sl, cp = entry.get("price"), entry.get("stop_loss"), close.get("close_price")
        if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)) or ep == sl:
            continue
        sign = 1 if trade.get("direction") == "BUY" else -1
        analysis = trade.get("analysis_at_open") or {}
        if not analysis:
            continue
        rows.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "opened_at": str(trade.get("opened_at") or ""),
            "r": sign * (cp - ep) / abs(ep - sl),
            "sign": sign,
            "features": flatten(analysis),
            # String readings, gathered here so the categorical layer has
            # something to work with. Without this the layer covering wyckoff
            # phase, market regime, session, zone grade, SMC structure and
            # Elliott wave labels silently audits nothing -- and those are
            # precisely the fields never scored before.
            "categoricals": flatten_categorical(analysis),
        })
    rows.sort(key=lambda r: r["opened_at"])
    return rows


def _coverage(rows: Sequence[Mapping[str, Any]], name: str
              ) -> Tuple[List[float], List[float]]:
    values, outcomes = [], []
    for row in rows:
        value = row["features"].get(name)
        if value is None:
            continue
        values.append(value)
        outcomes.append(row["r"])
    return values, outcomes


def _split_edge(rows: Sequence[Mapping[str, Any]], name: str,
                signed: bool) -> Optional[Tuple[float, int, int, float, float]]:
    """Edge from splitting this field at its median. None if unusable."""
    pairs = []
    for row in rows:
        value = row["features"].get(name)
        if value is None:
            continue
        pairs.append(((value * row["sign"]) if signed else value, row["r"]))
    if len(pairs) < MIN_SIDE * 2:
        return None
    threshold = _split_point([p[0] for p in pairs])
    if threshold is None:
        return None
    high = [r for v, r in pairs if v > threshold]
    low = [r for v, r in pairs if v <= threshold]
    if len(high) < MIN_SIDE or len(low) < MIN_SIDE:
        return None
    return (statistics.mean(high) - statistics.mean(low), len(high), len(low),
            statistics.mean(high), statistics.mean(low))


def _split_point(values: Sequence[float]) -> Optional[float]:
    """
    A threshold that actually divides the data.

    The median is the obvious choice and it FAILS on binary features: with
    uneven counts `statistics.median` returns one of the two values, so
    `v > median` selects an empty side and the field is silently discarded.
    Every boolean flag in the payload -- `nested`, `available`, `confirmed`,
    `detected` -- would have been dropped that way, which is precisely the
    kind of silent, flattering omission this audit exists to catch. Found by
    self_check, which plants a binary signal and requires it to be recovered.

    Falls back to the most balanced split over the distinct values, so binary,
    small-cardinality and continuous fields all divide correctly.
    """
    if not values:
        return None
    median = statistics.median(values)
    if any(v > median for v in values) and any(v <= median for v in values):
        return median

    distinct = sorted(set(values))
    if len(distinct) < 2:
        return None
    total = len(values)
    best, best_balance = None, None
    for candidate in distinct[:-1]:
        upper = sum(1 for v in values if v > candidate)
        balance = abs(upper - (total - upper))
        if best_balance is None or balance < best_balance:
            best, best_balance = candidate, balance
    return best


def audit(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
          rows: Optional[Sequence[Mapping[str, Any]]] = None,
          folds: int = 3,
          permutations: int = 200,
          alpha: float = 0.10,
          seed: int = 20260909) -> Dict[str, Any]:
    """
    Audit every discovered field.

    Returns a verdict per field and a summary. The DEAD list is as valuable as
    the EDGE list: a component that never varies is doing nothing, and this
    codebase has repeatedly shipped components in that state -- a dead DXY
    basket, an unreachable VIRGIN order-block status, an adaptive weight loop
    iterating an empty set.
    """
    from ai import edge_discovery as ed

    data = list(rows) if rows is not None else build_rows(trades or [])
    report: Dict[str, Any] = {"component": "component_audit_360",
                              "version": AUDIT_VERSION, "trades": len(data)}
    if len(data) < MIN_SIDE * 4:
        report["ok"] = None
        report["reason"] = "only %d trades; nothing can be resolved" % len(data)
        return report

    names = sorted({n for row in data for n in row["features"]})
    report["fields_discovered"] = len(names)

    dead, testable = [], []
    for name in names:
        values, _ = _coverage(data, name)
        coverage = len(values) / len(data)
        distinct = len(set(values))
        if coverage < MIN_COVERAGE:
            dead.append({"field": name, "why": "coverage %.0f%%" % (100 * coverage)})
        elif distinct < MIN_DISTINCT:
            dead.append({"field": name,
                         "why": "only %d distinct value(s)" % distinct,
                         "constant_value": values[0] if values else None})
        else:
            testable.append(name)

    report["dead_fields"] = len(dead)
    report["dead_sample"] = dead[:40]
    report["testable_fields"] = len(testable)

    blocks = ed.walk_forward_folds(data, folds)
    findings = []
    for name in testable:
        for signed in (False, True):
            pooled_hi, pooled_lo, positive, used = [], [], 0, 0
            for train, test in blocks:
                tr = _split_edge(train, name, signed)
                if tr is None:
                    continue
                # threshold fixed from TRAIN, applied to TEST
                # The threshold comes from _split_point, NOT statistics.median.
                # This logic used to be duplicated here with a raw median, so
                # the fix applied to _split_edge did not reach it and every
                # binary field was still being dropped -- the same defect,
                # surviving in a second copy of the code.
                pairs = [((row["features"][name] * row["sign"]) if signed
                          else row["features"][name], row["r"])
                         for row in train if row["features"].get(name) is not None]
                threshold = _split_point([p[0] for p in pairs])
                if threshold is None:
                    continue

                def _value(row):
                    raw = row["features"].get(name)
                    if raw is None:
                        return None
                    return (raw * row["sign"]) if signed else raw

                hi = [row["r"] for row in test
                      if _value(row) is not None and _value(row) > threshold]
                lo = [row["r"] for row in test
                      if _value(row) is not None and _value(row) <= threshold]
                if len(hi) < 5 or len(lo) < 5:
                    continue
                used += 1
                pooled_hi += hi
                pooled_lo += lo
                if statistics.mean(hi) - statistics.mean(lo) > 0:
                    positive += 1
            if used < 2 or len(pooled_hi) < MIN_SIDE or len(pooled_lo) < MIN_SIDE:
                continue
            edge = statistics.mean(pooled_hi) - statistics.mean(pooled_lo)
            n = min(len(pooled_hi), len(pooled_lo))
            p = ed.paired_pvalue(pooled_hi[:n], pooled_lo[:n], trials=1500) \
                if edge > 0 else ed.paired_pvalue(pooled_lo[:n], pooled_hi[:n],
                                                  trials=1500)
            findings.append({
                "field": name, "signed": signed, "edge": round(edge, 4),
                "high_r": round(statistics.mean(pooled_hi), 4),
                "low_r": round(statistics.mean(pooled_lo), 4),
                "n_high": len(pooled_hi), "n_low": len(pooled_lo),
                "folds_positive": positive, "folds_used": used,
                "p_value": round(p, 4),
                "hi": pooled_hi, "lo": pooled_lo,
            })

    report["hypotheses_tested"] = len(findings)
    if not findings:
        report["ok"] = False
        report["conclusion"] = "no field had enough coverage to test"
        return report

    flags = ed.benjamini_hochberg([f["p_value"] for f in findings], alpha=alpha)
    for finding, keep in zip(findings, flags):
        finding["fdr_significant"] = bool(keep)

    # Permutation null over the WHOLE audit: the largest |edge| any field
    # reaches when outcomes are shuffled. This is the honest bar, because the
    # audit reports the best of hundreds of fields.
    rng = random.Random(seed)
    outcomes = [row["r"] for row in data]
    null = []
    sample_fields = testable[:120]
    for _ in range(max(0, permutations)):
        rng.shuffle(outcomes)
        shuffled = [dict(row, r=o) for row, o in zip(data, outcomes)]
        best = 0.0
        for name in sample_fields:
            got = _split_edge(shuffled, name, False)
            if got:
                best = max(best, abs(got[0]))
        null.append(best)
    null.sort()
    p95 = null[int(0.95 * len(null))] if null else 0.0
    report["null"] = {"permutations": len(null),
                      "largest_edge_95th": round(p95, 4),
                      "largest_edge_max": round(null[-1], 4) if null else None,
                      "note": ("the biggest |edge| ANY field reaches when the "
                               "outcomes are shuffled -- the bar the audit "
                               "must clear because it reports the best of "
                               "hundreds")}

    for finding in findings:
        finding["beats_null"] = abs(finding["edge"]) > p95
        finding["verdict"] = (
            "EDGE" if (finding["edge"] > 0 and finding["beats_null"]
                       and finding["fdr_significant"]
                       and finding["folds_positive"] >= finding["folds_used"] - 0)
            else "INVERTED" if (finding["edge"] < 0 and finding["beats_null"]
                                and finding["fdr_significant"])
            else "NOISE")
        finding.pop("hi", None)
        finding.pop("lo", None)

    report["edges"] = sorted([f for f in findings if f["verdict"] == "EDGE"],
                             key=lambda f: -f["edge"])
    report["inverted"] = sorted([f for f in findings if f["verdict"] == "INVERTED"],
                                key=lambda f: f["edge"])
    report["strongest_untested"] = sorted(
        [f for f in findings if f["verdict"] == "NOISE"],
        key=lambda f: -abs(f["edge"]))[:15]
    report["counts"] = {
        "EDGE": len(report["edges"]),
        "INVERTED": len(report["inverted"]),
        "NOISE": len(findings) - len(report["edges"]) - len(report["inverted"]),
        "DEAD": len(dead),
    }
    report["ok"] = bool(report["edges"] or report["inverted"])
    return report


# ============================================================
# DEEPER LAYERS
# ============================================================
# A median split answers one narrow question: "is high better than low?" Most
# of the ways a component can carry -- or destroy -- information are invisible
# to it. These are the layers that see them.
# ============================================================

CATEGORICAL_KEYS = (
    "phase", "regime", "session", "grade", "trend", "state", "status",
    "recommendation", "direction", "classification", "signal", "bias",
    "wave", "structure", "verdict", "action", "type",
)


def flatten_categorical(payload: Any, prefix: str = "", depth: int = 0
                        ) -> Dict[str, str]:
    """
    String-valued readings, which the numeric pass deliberately skips.

    These are some of the most important fields in the system and NONE of them
    has ever been scored: wyckoff phase, market regime, session, zone grade,
    SMC structure state, Elliott wave label, order-block status. Coercing them
    to numbers would invent an ordering that does not exist, so they are
    tested per-category instead -- each value against every other.
    """
    out: Dict[str, str] = {}
    if depth > MAX_DEPTH:
        return out
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            name = str(key)
            if name.startswith("_"):
                continue
            path = f"{prefix}.{name}" if prefix else name
            if isinstance(value, str):
                if 0 < len(value) <= 40 and any(
                        token in name.lower() for token in CATEGORICAL_KEYS):
                    out[path] = value
            else:
                out.update(flatten_categorical(value, path, depth + 1))
    return out


def categorical_audit(rows: Sequence[Mapping[str, Any]],
                      min_group: int = 12) -> List[Dict[str, Any]]:
    """
    Every category value against every other, on the same outcome scale.

    This is where "wyckoff phase ACCUMULATION" or "session ASIA" or "order
    block VIRGIN" finally gets a number attached. A category that never
    appears is reported too -- an unreachable state is a bug, and this
    codebase had exactly that with an order-block status that was
    unreachable by construction.
    """
    findings = []
    fields: Dict[str, Dict[str, List[float]]] = {}
    for row in rows:
        for field, value in (row.get("categoricals") or {}).items():
            fields.setdefault(field, {}).setdefault(value, []).append(row["r"])

    for field, groups in fields.items():
        total = sum(len(v) for v in groups.values())
        if total < min_group * 2:
            continue
        overall = statistics.mean(r for v in groups.values() for r in v)
        for value, outcomes in groups.items():
            if len(outcomes) < min_group:
                continue
            others = [r for k, v in groups.items() if k != value for r in v]
            if len(others) < min_group:
                continue
            findings.append({
                "field": field, "value": value, "n": len(outcomes),
                "share": round(100.0 * len(outcomes) / total, 1),
                "r": round(statistics.mean(outcomes), 4),
                "r_others": round(statistics.mean(others), 4),
                "edge": round(statistics.mean(outcomes) - statistics.mean(others), 4),
                "win_rate": round(100.0 * sum(1 for r in outcomes if r > 0)
                                  / len(outcomes), 1),
                "overall": round(overall, 4),
            })
    return sorted(findings, key=lambda f: -abs(f["edge"]))


def quantile_profile(rows: Sequence[Mapping[str, Any]], name: str,
                     signed: bool = False, buckets: int = 5
                     ) -> Optional[Dict[str, Any]]:
    """
    The shape of the relationship, not just its slope.

    A median split cannot see a U -- a feature that predicts at BOTH extremes
    and not in the middle splits to zero and reports as noise. It also cannot
    tell an ordered relationship from a lumpy one.

    `monotonic` is the useful discriminator: a real signal usually walks in
    one direction across quantiles, while noise zig-zags. A feature with a big
    edge and a non-monotonic profile is far more likely to be an artefact of
    where the median happened to fall.
    """
    pairs = []
    for row in rows:
        value = row["features"].get(name)
        if value is None:
            continue
        pairs.append(((value * row["sign"]) if signed else value, row["r"]))
    if len(pairs) < buckets * MIN_SIDE:
        return None
    if len(set(v for v, _ in pairs)) < buckets:
        # Fewer distinct values than buckets: the quantiles would be
        # arbitrary slices of identical readings, and the "profile" would
        # describe the sort order rather than the feature.
        return None
    pairs.sort(key=lambda p: p[0])
    size = len(pairs) // buckets
    means, counts = [], []
    for i in range(buckets):
        chunk = pairs[i * size:(i + 1) * size] if i < buckets - 1 else pairs[i * size:]
        if not chunk:
            return None
        means.append(statistics.mean(r for _, r in chunk))
        counts.append(len(chunk))

    ups = sum(1 for i in range(1, buckets) if means[i] > means[i - 1])
    downs = buckets - 1 - ups
    return {
        "field": name, "signed": signed,
        "quantile_r": [round(m, 4) for m in means],
        "counts": counts,
        "spread": round(max(means) - min(means), 4),
        "monotonic": ups == buckets - 1 or downs == buckets - 1,
        "direction": "rising" if ups > downs else "falling",
        # U or inverted-U: extremes agree with each other and differ from
        # the middle. Invisible to any median split.
        "u_shaped": (means[0] > means[buckets // 2] and means[-1] > means[buckets // 2])
                    or (means[0] < means[buckets // 2] and means[-1] < means[buckets // 2]),
    }


def mutual_information(rows: Sequence[Mapping[str, Any]], name: str,
                       bins: int = 5) -> Optional[float]:
    """
    Non-linear dependence between a feature and the WIN/LOSS outcome.

    Correlation and median splits only see monotone relationships. Mutual
    information sees any dependence at all, so a feature that matters only in
    a narrow band still registers. Reported in bits; 0 means independent.
    """
    pairs = [(row["features"][name], 1 if row["r"] > 0 else 0)
             for row in rows if row["features"].get(name) is not None]
    if len(pairs) < bins * MIN_SIDE:
        return None
    pairs.sort(key=lambda p: p[0])
    size = len(pairs) // bins
    total = len(pairs)
    p_win = sum(1 for _, w in pairs if w) / total
    if p_win in (0.0, 1.0):
        return 0.0

    import math
    mi = 0.0
    for i in range(bins):
        chunk = pairs[i * size:(i + 1) * size] if i < bins - 1 else pairs[i * size:]
        if not chunk:
            continue
        p_bin = len(chunk) / total
        wins = sum(1 for _, w in chunk if w)
        for outcome, count in ((1, wins), (0, len(chunk) - wins)):
            if not count:
                continue
            p_joint = count / total
            p_out = p_win if outcome else (1 - p_win)
            mi += p_joint * math.log2(p_joint / (p_bin * p_out))
    return round(max(0.0, mi), 5)


def regime_conditional(rows: Sequence[Mapping[str, Any]], name: str,
                       regime_field: str, min_group: int = 15
                       ) -> List[Dict[str, Any]]:
    """
    Does this feature behave DIFFERENTLY in different market states?

    The most important hypothesis this audit can test. A component that works
    in a trend and inverts in a range averages to EXACTLY zero -- which is
    what direction entropy of 1.0000 looks like in aggregate, and it would
    explain why seven separate searches over these features found nothing.

    If a feature's edge flips sign between regimes and both sides are
    substantial, the component is not useless. It is being asked the wrong
    question.
    """
    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        regime = (row.get("categoricals") or {}).get(regime_field)
        if regime and row["features"].get(name) is not None:
            groups.setdefault(regime, []).append(row)

    out = []
    for regime, subset in groups.items():
        if len(subset) < min_group:
            continue
        got = _split_edge(subset, name, False)
        if got:
            out.append({"regime": regime, "n": len(subset),
                        "edge": round(got[0], 4),
                        "high_r": round(got[3], 4), "low_r": round(got[4], 4)})
    return sorted(out, key=lambda g: -abs(g["edge"]))


def redundancy_clusters(rows: Sequence[Mapping[str, Any]],
                        names: Sequence[str], threshold: float = 0.95
                        ) -> List[List[str]]:
    """
    Groups of fields that are effectively the same measurement.

    This matters for more than tidiness. The probability chain adds each
    component's contribution independently, so two fields carrying the same
    information are DOUBLE-COUNTED -- the same evidence moves the probability
    twice. Finding these clusters says where the chain is over-weighting one
    underlying signal while believing it has two.
    """
    columns: Dict[str, List[float]] = {}
    for name in names:
        values = [row["features"].get(name) for row in rows]
        if all(v is not None for v in values) and len(set(values)) > 2:
            columns[name] = [float(v) for v in values]

    keys = list(columns)
    seen, clusters = set(), []
    for i, a in enumerate(keys):
        if a in seen:
            continue
        group = [a]
        for b in keys[i + 1:]:
            if b in seen:
                continue
            try:
                c = abs(_pearson(columns[a], columns[b]))
            except Exception:
                continue
            if c >= threshold:
                group.append(b)
                seen.add(b)
        if len(group) > 1:
            seen.add(a)
            clusters.append(group)
    return clusters


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    ma, mb = statistics.mean(a[:n]), statistics.mean(b[:n])
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math_sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math_sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    return num / (da * db) if da and db else 0.0


def math_sqrt(x: float) -> float:
    import math
    return math.sqrt(x)


def interactions(rows: Sequence[Mapping[str, Any]], names: Sequence[str],
                 top: int = 12, min_group: int = 15) -> List[Dict[str, Any]]:
    """
    Pairs of fields that only work TOGETHER.

    A component can be worthless alone and decisive in combination -- "RSI
    oversold" means one thing at a demand zone and another mid-range. Every
    single-field test in this audit is blind to that, and so is the
    probability chain, which adds contributions independently and can never
    express a conditional.

    Restricted to the strongest single fields and reported with the
    interaction GAIN over the better of the two alone, so a pair only counts
    if it beats what its members already do.
    """
    import itertools

    out = []
    for a, b in itertools.combinations(names[:14], 2):
        both, either = [], []
        for row in rows:
            va, vb = row["features"].get(a), row["features"].get(b)
            if va is None or vb is None:
                continue
            (both if (va > 0 and vb > 0) else either).append(row["r"])
        if len(both) < min_group or len(either) < min_group:
            continue
        solo_a = [row["r"] for row in rows
                  if (row["features"].get(a) or 0) > 0]
        solo_b = [row["r"] for row in rows
                  if (row["features"].get(b) or 0) > 0]
        if len(solo_a) < min_group or len(solo_b) < min_group:
            continue
        best_solo = max(statistics.mean(solo_a), statistics.mean(solo_b))
        out.append({
            "pair": [a, b], "n_both": len(both),
            "r_both": round(statistics.mean(both), 4),
            "r_either": round(statistics.mean(either), 4),
            "best_solo": round(best_solo, 4),
            "interaction_gain": round(statistics.mean(both) - best_solo, 4),
        })
    return sorted(out, key=lambda x: -x["interaction_gain"])[:top]


def per_symbol_robustness(rows: Sequence[Mapping[str, Any]], name: str,
                          min_group: int = 10) -> Dict[str, Any]:
    """
    Is the edge present across instruments, or carried by one?

    A finding driven by a single symbol is a property of that symbol -- or of
    a handful of lucky trades in it -- not of the component. The
    microstructure result earlier fired on 21 symbols but GBPAUD supplied 18
    of 64 trades, and that concentration is the main reason it is called a
    candidate rather than a conclusion.
    """
    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        if row["features"].get(name) is not None:
            groups.setdefault(row.get("symbol") or "?", []).append(row)

    per = []
    for symbol, subset in groups.items():
        if len(subset) < min_group:
            continue
        got = _split_edge(subset, name, False)
        if got:
            per.append({"symbol": symbol, "n": len(subset),
                        "edge": round(got[0], 4)})
    positive = sum(1 for p in per if p["edge"] > 0)
    return {"symbols_tested": len(per), "positive": positive,
            "consistent": bool(per) and positive >= max(2, int(0.7 * len(per))),
            "per_symbol": sorted(per, key=lambda p: -p["edge"])}


def deep_audit(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
               rows: Optional[Sequence[Mapping[str, Any]]] = None,
               **kwargs) -> Dict[str, Any]:
    """
    The full 360: the base audit plus every deeper layer.

    Ordered so the cheap, high-yield layers run first. The categorical audit
    in particular covers fields that have NEVER been scored in this system --
    wyckoff phase, market regime, session, zone grade, SMC structure, Elliott
    wave labels -- because they are strings and every previous analysis
    silently skipped them.
    """
    data = list(rows) if rows is not None else build_rows(trades or [])
    for row in data:
        if "categoricals" not in row:
            row["categoricals"] = {}

    report = audit(rows=data, **kwargs)
    if not data or report.get("ok") is None:
        return report

    names = [f["field"] for f in
             sorted(report.get("strongest_untested", [])
                    + report.get("edges", [])
                    + report.get("inverted", []),
                    key=lambda f: -abs(f["edge"]))]
    names = list(dict.fromkeys(names))

    report["categorical"] = categorical_audit(data)[:25]
    report["quantile_profiles"] = [
        q for q in (quantile_profile(data, n) for n in names[:20]) if q]
    report["mutual_information"] = sorted(
        [{"field": n, "bits": mi}
         for n in names[:40]
         for mi in [mutual_information(data, n)] if mi],
        key=lambda x: -x["bits"])[:15]
    report["interactions"] = interactions(data, names)
    report["redundancy_clusters"] = redundancy_clusters(data, names[:60])[:12]

    regime_fields = sorted({f for row in data
                            for f in (row.get("categoricals") or {})
                            if "regime" in f.lower() or "session" in f.lower()})
    report["regime_conditional"] = {}
    for regime_field in regime_fields[:2]:
        for name in names[:6]:
            got = regime_conditional(data, name, regime_field)
            if len(got) >= 2 and got[0]["edge"] * got[-1]["edge"] < 0:
                # sign FLIPS between regimes -- the interesting case
                report["regime_conditional"].setdefault(regime_field, []).append(
                    {"field": name, "groups": got})

    report["robustness"] = {n: per_symbol_robustness(data, n)
                            for n in names[:6]}
    report["layers"] = ["numeric", "categorical", "quantile", "mutual_information",
                        "interaction", "redundancy", "regime", "robustness"]
    return report


def get_status() -> Dict[str, Any]:
    return {"component": "component_audit_360", "version": AUDIT_VERSION,
            "min_coverage": MIN_COVERAGE, "min_distinct": MIN_DISTINCT,
            "layers": ["numeric", "categorical", "quantile",
                       "mutual_information", "interaction", "redundancy",
                       "regime", "robustness"]}


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the audit finds a planted field, flags a dead one, and does not
    invent an edge in noise.
    """
    rng = random.Random(5)
    rows = []
    for i in range(240):
        good = rng.choice([-1.0, 1.0])
        rows.append({
            "trade_id": "t%d" % i, "symbol": "X", "opened_at": "%04d" % i,
            "r": good, "sign": 1,
            "features": {"real.signal": good,
                         "junk.random": rng.gauss(0, 1),
                         "dead.constant": 1.0},
        })
    report = audit(rows=rows, permutations=40, folds=3)
    edges = {f["field"] for f in report.get("edges", [])}
    dead = {d["field"] for d in report.get("dead_sample", [])}
    checks = {
        "finds_planted_signal": "real.signal" in edges,
        "flags_constant_as_dead": "dead.constant" in dead,
        "does_not_promote_noise": "junk.random" not in edges,
        "fields_discovered": report.get("fields_discovered"),
    }
    return {"component": "component_audit_360", "version": AUDIT_VERSION,
            "checks": checks,
            "ok": (checks["finds_planted_signal"]
                   and checks["flags_constant_as_dead"]
                   and checks["does_not_promote_noise"])}
