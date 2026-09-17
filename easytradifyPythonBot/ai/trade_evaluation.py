# ai/trade_evaluation.py
"""
Evaluate the stored trades: how the system has actually performed, and which
readings at entry are associated with the outcome.

NOT A REPLAY
------------
Everything here is computed from trades that were really placed and closed.
Nothing is re-simulated. Trades come from three MT5 accounts (1:200, 1:300,
1:500), which is why replay is ruled out and why leverage is a first-class
split below.

WHAT IT REPORTS
---------------
  headline      win rate (Wilson 95% CI), expectancy in R and $, payoff,
                break-even win rate, profit factor, net result
  equity        cumulative R, max drawdown, losing streaks
  segments      leverage, asset class, symbol, direction, close reason,
                session, weekday, planned R:R, entry spread
  execution     planned vs realised R:R, target reach rate, exit spread and
                slippage, holding time
  ledger        each probability-chain component: did trades do better when it
                pushed FOR the trade than when it did not?
  fields        EVERY reading in analysis_at_open, discovered automatically --
                numeric fields by tercile, flags and labels by value
  oos           the walk-forward verdicts from component_audit_360

HOW TO READ IT -- THE CONTROLS ARE THE POINT
--------------------------------------------
With ~120 trades and a few hundred fields, some splits WILL look excellent by
chance alone. This package has measured that directly: on 215 trades a search
of 82 hypotheses produced a 62% subset that collapsed to 25% out of sample, and
the best subset of shuffled noise still reached 61.5%.

So every family of splits carries:
  * a permutation p-value for its BEST bucket, where the null re-runs the same
    "pick the best bucket" search on shuffled outcomes -- so choosing the most
    flattering bucket is paid for, not free;
  * a Benjamini-Hochberg q-value across the family;
  * a small-sample flag on any bucket under MIN_BUCKET trades.

A split is only worth acting on if q is small AND the walk-forward audit
agrees. A low in-sample p on its own is a hypothesis, not a finding.

DIRECTION FRAME
---------------
"Trend says SELL" means opposite things for a long and a short. Directional
labels are therefore re-expressed as ALIGNED / OPPOSED / NEUTRAL relative to
the traded direction, and signed numeric fields are also tested multiplied by
the trade's direction. Testing only the raw form lets a genuinely predictive
reading measure as noise, because the two directions cancel.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

EVALUATION_VERSION = "1.0"

MIN_BUCKET = 10          # a bucket under this is shown but flagged, and not tested
MAX_CATEGORIES = 15      # a string field with more distinct values is free text
DEFAULT_PERMUTATIONS = 2000
DEFAULT_SEED = 20260914

# Paths skipped by field discovery, and why.
#   absolute prices     a price level means nothing across symbols; splitting
#                       EURUSD at 1.15 against gold at 3,600 finds the symbol,
#                       not an edge
#   account state       balance/margin drift with time and with the account
#   config              settings, not market readings -- and they changed over
#                       the sample, so they proxy for "when", not "what"
#   A/B bookkeeping     counters about the test, not about the trade
_PRICE_LEAF = re.compile(
    r"(^|_)(price|prices|level|open|close|high|low|poc|vah|val|sl|tp|"
    r"stop_loss|take_profit(_\d)?|entry|today_open|range_high|range_low|"
    r"last_swing_high|last_swing_low|discount_level|zone_level|"
    r"balance|equity|margin|free_margin_before|free_margin_after|"
    r"margin_required_usd|bar_index|lot_size|reward_usd|risk_usd)$")
_KEEP_UNIT = re.compile(r"(pips|pct|percent|ratio|score|confidence|count|"
                        r"strength|atr|adx|sigma|bars_ago|weight|vote)$")
_SKIP_PREFIX = ("config.", "account_info.", "gnn.ab_test", "coherence.counts",
                "decision_snapshot.input_state_reference", "input_state_reference")
_TEXT_KEY = re.compile(r"(reason|note|explained|explanation|trigger|detail|"
                       r"message|scenario|thesis_text|generated_at|timestamp|"
                       r"snapshot_version|symbol|instrument|timeframe|"
                       r"invalidation|recommendation_text|summary)", re.I)

_DIRECTIONAL = {
    "BUY": 1, "LONG": 1, "BULLISH": 1, "STRONG_BULLISH": 1, "STRONG_BUY": 1, "UP": 1,
    "SELL": -1, "SHORT": -1, "BEARISH": -1, "STRONG_BEARISH": -1, "STRONG_SELL": -1, "DOWN": -1,
    "NEUTRAL": 0, "HOLD": 0, "NONE": 0, "FLAT": 0, "RANGING": 0,
}


# ============================================================
# ROWS
# ============================================================

def build_rows(trades: Iterable[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Scored rows, oldest first, plus counts of what was excluded and why.

    A row needs a measured profit AND a computable R. Win/loss is decided by the
    profit the broker reported; expectancy is measured in R, because $4 on gold
    and $4 on EURUSD are different amounts of risk and averaging dollars across
    them describes neither.
    """
    from ai import trade_repository as repo

    rows: List[Dict[str, Any]] = []
    excluded: Counter = Counter()

    for raw in trades:
        if not isinstance(raw, Mapping):
            excluded["not_a_trade"] += 1
            continue
        stored_envelope = "m1_analysis_raw" in (raw.get("analysis_at_open") or {})
        trade = repo.canonicalise(raw) if stored_envelope else dict(raw)
        close = trade.get("close_data") or {}

        if str(trade.get("status") or "CLOSED").upper() != "CLOSED":
            excluded["not_closed"] += 1
            continue

        profit = _num(close.get("profit_usd"))
        if profit is None:
            excluded["no_profit_recorded"] += 1
            continue

        # scripts/repair_trade_outcomes.py marks exits it could not recover;
        # their stored price is the EA's rounded 0.0 and would read as +583R.
        if close.get("close_price_source") == "unresolved":
            excluded["exit_price_unresolved"] += 1
            continue

        r = repo._r_multiple(trade)
        if r is None:
            excluded["r_not_computable"] += 1
            continue

        # Price R ignores commission. On this broker a round trip costs
        # $7.03/lot, which on a ~1 pip stop is most of the planned risk -- so
        # net R (booked $ over planned $ risk) is the figure the account feels.
        # The broker's loss-at-stop, not the sizer's `actual_risk_usd`, which
        # understates it (see core/broker_facts.risk_usd_at_stop).
        risk_usd = _num(trade.get("risk_usd_at_stop"))
        r_net = profit / risk_usd if risk_usd and risk_usd > 0 else None
        planned_risk = _num(trade.get("actual_risk_usd"))

        direction = str(trade.get("direction") or "").upper()
        sign = 1 if direction == "BUY" else -1
        analysis = trade.get("analysis_at_open") or {}
        opened = _parse_time(trade.get("opened_at"))
        closed = _parse_time(trade.get("closed_at"))

        rows.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol") or "?",
            "direction": direction or "?",
            "sign": sign,
            "profit": profit,
            "r": float(r),
            "r_net": r_net,
            "risk_usd": risk_usd,
            "planned_risk_usd": planned_risk,
            "win": profit > 0,
            "opened_at": opened,
            "closed_at": closed,
            "leverage": _leverage(trade),
            "close_reason": _close_reason(close.get("close_reason")),
            "planned_rr": _num(trade.get("risk_reward_ratio")),
            "spread_at_entry": _num(trade.get("spread_at_entry")),
            "exit_spread": _num(close.get("exit_spread")),
            "exit_slippage": _num(close.get("exit_slippage")),
            "duration_min": ((closed - opened).total_seconds() / 60.0
                             if opened and closed and closed >= opened else None),
            "ledger": _ledger_pushes(trade, direction),
            "numeric": _numeric_fields(analysis),
            "categorical": _categorical_fields(analysis, sign),
        })

    rows.sort(key=lambda row: row["opened_at"] or datetime.min.replace(tzinfo=timezone.utc))
    return rows, dict(excluded)


def _ledger_pushes(trade: Mapping[str, Any], direction: str) -> Dict[str, float]:
    """Each chain step's INTENDED push, in the traded direction's frame.

    `delta` alone is wrong here: when the probability is pinned at a bound the
    applied delta is 0 even though the component pushed. pattern, smc, fvg_ifvg
    and order_flow are clamped on 40-50% of trades, so reading `delta` would
    file half their contributions as "neutral". The intended push is
    `intended_after - before`.

    Ledger deltas are signed against the ANALYSIS direction, which differs from
    the traded one on a few trades; those are flipped into the traded frame.
    """
    from ai import trade_repository as repo

    best = str(repo.best_direction_of(trade) or direction).upper()
    frame = 1 if best in ("", direction) else -1
    pushes: Dict[str, float] = {}
    for step in repo.ledger_of(trade):
        before, after = _num(step.get("before")), _num(step.get("intended_after"))
        delta = (after - before) if (before is not None and after is not None) \
            else _num(step.get("delta"))
        if delta is None:
            continue
        pushes[str(step["step"])] = frame * delta
    return pushes


def _numeric_fields(analysis: Mapping[str, Any]) -> Dict[str, float]:
    from ai.component_audit_360 import flatten

    out = {}
    for path, value in flatten(analysis).items():
        if _skip_path(path):
            continue
        leaf = path.rsplit(".", 1)[-1]
        if _PRICE_LEAF.search(leaf) and not _KEEP_UNIT.search(leaf):
            continue
        out[path] = value
    return out


def _categorical_fields(analysis: Mapping[str, Any], sign: int, prefix: str = "",
                        depth: int = 0) -> Dict[str, str]:
    """Every short string reading, with directional labels put in the trade's frame."""
    out: Dict[str, str] = {}
    if depth > 6 or not isinstance(analysis, Mapping):
        return out
    for key, value in analysis.items():
        name = str(key)
        if name.startswith("_"):
            continue
        path = f"{prefix}.{name}" if prefix else name
        if _skip_path(path):
            continue
        if isinstance(value, Mapping):
            out.update(_categorical_fields(value, sign, path, depth + 1))
        elif isinstance(value, str) and 0 < len(value) <= 40 and not _TEXT_KEY.search(name):
            label = value.strip().upper()
            if label in _DIRECTIONAL:
                vote = _DIRECTIONAL[label] * sign
                out[f"{path}@vs_trade"] = ("ALIGNED" if vote > 0 else
                                           "OPPOSED" if vote < 0 else "NEUTRAL")
            else:
                out[path] = value.strip()
    return out


def _skip_path(path: str) -> bool:
    return any(path.startswith(p) or f".{p}" in path for p in _SKIP_PREFIX)


# ============================================================
# STATISTICS
# ============================================================

def wilson(k: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    """95% Wilson interval for a win rate, in percent. Honest at small n, unlike +/-2SE."""
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)


def bootstrap_mean_ci(values: Sequence[float], iterations: int = 2000,
                      seed: int = DEFAULT_SEED) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < 2:
        return None, None
    import numpy as np
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=float)
    means = rng.choice(data, size=(iterations, data.size), replace=True).mean(axis=1)
    return round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3)


def summarise(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The performance numbers for any set of rows."""
    n = len(rows)
    if not n:
        return {"n": 0}
    rs = [row["r"] for row in rows]
    wins = [row for row in rows if row["win"]]
    losses = [row for row in rows if row["profit"] < 0]
    win_r = [row["r"] for row in wins]
    loss_r = [row["r"] for row in losses]
    gross_win = sum(row["profit"] for row in wins)
    gross_loss = sum(row["profit"] for row in losses)
    lo, hi = wilson(len(wins), n)

    avg_win_r = statistics.mean(win_r) if win_r else None
    avg_loss_r = statistics.mean(loss_r) if loss_r else None
    payoff = (avg_win_r / abs(avg_loss_r)) if (avg_win_r is not None and avg_loss_r) else None

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "win_rate": round(100 * len(wins) / n, 1),
        "win_rate_ci95": [lo, hi],
        "expectancy_r": round(statistics.mean(rs), 3),
        "expectancy_r_ci95": list(bootstrap_mean_ci(rs)),
        "expectancy_usd": round(sum(row["profit"] for row in rows) / n, 2),
        "net_usd": round(sum(row["profit"] for row in rows), 2),
        "net_r": round(sum(rs), 2),
        "avg_win_r": round(avg_win_r, 3) if avg_win_r is not None else None,
        "avg_loss_r": round(avg_loss_r, 3) if avg_loss_r is not None else None,
        "payoff": round(payoff, 2) if payoff is not None else None,
        # The win rate this payoff needs just to break even. The gap between
        # this and the actual win rate is the whole story in one number.
        # (A "win" by profit can carry a negative price R when swap or
        # commission decided it, so payoff is not guaranteed positive.)
        "breakeven_win_rate": round(100 / (1 + payoff), 1) if payoff and payoff > 0 else None,
        "profit_factor": round(gross_win / abs(gross_loss), 2) if gross_loss else None,
        "median_r": round(statistics.median(rs), 3),
        "expectancy_net_r": (round(statistics.mean(net), 3)
                             if (net := [row["r_net"] for row in rows if row.get("r_net") is not None])
                             else None),
        "small_sample": n < MIN_BUCKET,
    }


def permutation_best_bucket(labels: Sequence[Any], rs: Sequence[float],
                            permutations: int, seed: int) -> Optional[Dict[str, Any]]:
    """p-value for the MOST extreme bucket of one field, search included.

    Statistic: max over eligible buckets of |mean R in bucket - mean R of the
    rest|. The null shuffles outcomes and re-runs the same search, so picking
    the most flattering bucket is accounted for. Returns None if fewer than two
    buckets have MIN_BUCKET trades.
    """
    import numpy as np

    counts = Counter(labels)
    eligible = [label for label, c in counts.items() if c >= MIN_BUCKET]
    if len(eligible) < 2 and not (len(eligible) == 1 and len(labels) - counts[eligible[0]] >= MIN_BUCKET):
        return None

    r = np.asarray(rs, dtype=float)
    n = r.size
    onehot = np.stack([np.asarray([lab == e for lab in labels], dtype=float) for e in eligible], axis=1)
    sizes = onehot.sum(axis=0)
    rest = n - sizes
    usable = (sizes >= MIN_BUCKET) & (rest >= MIN_BUCKET)
    if not usable.any():
        return None

    def contrast(values):
        sums = values @ onehot                      # (..., buckets)
        total = values.sum(axis=-1, keepdims=True)
        inside = sums / sizes
        outside = (total - sums) / rest
        diff = np.where(usable, inside - outside, 0.0)
        return diff

    observed = contrast(r)
    best = int(np.argmax(np.abs(observed)))
    stat = abs(float(observed[best]))

    rng = np.random.default_rng(seed)
    shuffled = rng.permuted(np.tile(r, (permutations, 1)), axis=1)
    null = np.abs(contrast(shuffled)).max(axis=1)
    p = (1 + int((null >= stat - 1e-12).sum())) / (permutations + 1)

    return {"best_bucket": eligible[best], "contrast_r": round(float(observed[best]), 3),
            "p": round(p, 4)}


def benjamini_hochberg(items: List[Dict[str, Any]], key: str = "p") -> None:
    """Attach `q` to every item that has a p-value. Controls the false discovery rate."""
    tested = [item for item in items if item.get(key) is not None]
    m = len(tested)
    if not m:
        return
    ordered = sorted(tested, key=lambda item: item[key])
    running = 1.0
    for rank in range(m, 0, -1):
        item = ordered[rank - 1]
        running = min(running, item[key] * m / rank)
        item["q"] = round(min(running, 1.0), 4)


# ============================================================
# SECTIONS
# ============================================================

def equity(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    peak = cumulative = drawdown = 0.0
    streak = longest_loss = longest_win = win_streak = 0
    for row in rows:
        cumulative += row["r"]
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        if row["win"]:
            win_streak += 1
            streak = 0
        else:
            streak += 1
            win_streak = 0
        longest_loss = max(longest_loss, streak)
        longest_win = max(longest_win, win_streak)
    return {"final_r": round(cumulative, 2), "peak_r": round(peak, 2),
            "max_drawdown_r": round(drawdown, 2),
            "longest_losing_streak": longest_loss, "longest_winning_streak": longest_win}


def segment(rows: Sequence[Mapping[str, Any]], key, name: str,
            permutations: int, seed: int) -> Dict[str, Any]:
    """Split rows by `key(row)` and summarise every bucket."""
    groups: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
    labels, rs = [], []
    for row in rows:
        label = key(row)
        if label is None:
            continue
        groups[label].append(row)
        labels.append(label)
        rs.append(row["r"])

    buckets = []
    for label, members in groups.items():
        info = summarise(members)
        info["value"] = label
        dates = [m["opened_at"] for m in members if m["opened_at"]]
        if dates:
            info["first_trade"] = min(dates).strftime("%Y-%m-%d")
            info["last_trade"] = max(dates).strftime("%Y-%m-%d")
        buckets.append(info)
    buckets.sort(key=lambda b: (-b["n"], str(b["value"])))

    result = {"segment": name, "buckets": buckets}
    test = permutation_best_bucket(labels, rs, permutations, seed) if labels else None
    if test:
        result.update(test)
    return result


def execution(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    wins = [row for row in rows if row["win"]]
    losses = [row for row in rows if not row["win"]]

    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.mean(values), 3) if values else None

    def median(values):
        values = [v for v in values if v is not None]
        return round(statistics.median(values), 3) if values else None

    tp = [row for row in rows if row["close_reason"] == "TAKE_PROFIT"]
    planned = [row["planned_rr"] for row in rows if row["planned_rr"] is not None]
    return {
        # The gap between these two is how much of the planned reward is ever
        # collected. A high planned R:R that is rarely reached is the
        # signature of targets set by the analysis rather than by the market.
        "planned_rr_median": median(planned),
        "realised_win_r_mean": mean([row["r"] for row in wins]),
        "target_reach_rate": round(100 * len(tp) / len(rows), 1) if rows else None,
        "wins_closed_at_target": sum(1 for row in wins if row["close_reason"] == "TAKE_PROFIT"),
        "wins_closed_other": sum(1 for row in wins if row["close_reason"] != "TAKE_PROFIT"),
        "entry_spread_pips_median": median([row["spread_at_entry"] for row in rows]),
        "exit_spread_pips_median": median([row["exit_spread"] for row in rows]),
        "exit_slippage_pips_mean": mean([row["exit_slippage"] for row in rows]),
        "exit_slippage_adverse_share": _share([row["exit_slippage"] for row in rows], lambda v: v > 0),
        "sizer_risk_usd_median": median([row["planned_risk_usd"] for row in rows]),
        "broker_risk_at_stop_usd_median": median([row["risk_usd"] for row in rows]),
        "loss_usd_median": median([row["profit"] for row in rows if row["profit"] < 0]),
        # Price R minus net R: what commission and swap take per trade, in
        # units of the risk at the stop.
        "cost_drag_r_median": median([row["r"] - row["r_net"] for row in rows
                                      if row.get("r_net") is not None]),
        # Price moved in the trade's favour, yet the account booked a loss.
        "price_winners_booked_as_losses": sum(1 for row in rows if row["r"] > 0 and row["profit"] <= 0),
        "holding_minutes_median_win": median([row["duration_min"] for row in wins]),
        "holding_minutes_median_loss": median([row["duration_min"] for row in losses]),
    }


def ledger_components(rows: Sequence[Mapping[str, Any]], permutations: int,
                      seed: int) -> Dict[str, Any]:
    steps = sorted({step for row in rows for step in row["ledger"]})
    components, dead = [], []
    for step in steps:
        pushes = [row["ledger"].get(step) for row in rows]
        if all(not p for p in pushes if p is not None):
            dead.append(step)
            continue

        def state(row, step=step):
            value = row["ledger"].get(step)
            if value is None:
                return None
            return "FOR" if value > 0 else "AGAINST" if value < 0 else "NEUTRAL"

        report = segment(rows, state, step, permutations, seed)
        by = {b["value"]: b for b in report["buckets"]}
        f, a = by.get("FOR"), by.get("AGAINST")
        report["win_rate_for_minus_against"] = (
            round(f["win_rate"] - a["win_rate"], 1) if f and a else None)
        report["expectancy_for_minus_against"] = (
            round(f["expectancy_r"] - a["expectancy_r"], 3) if f and a else None)
        components.append(report)

    benjamini_hochberg(components)
    return {"components": components, "never_moved_probability": dead}


def discovered_fields(rows: Sequence[Mapping[str, Any]], permutations: int,
                      seed: int) -> Dict[str, Any]:
    """Every numeric and categorical reading, split and tested."""
    results: List[Dict[str, Any]] = []
    constant: List[str] = []
    n = len(rows)

    # ---- numeric: terciles (or by value when there are few distinct values)
    names = sorted({name for row in rows for name in row["numeric"]})
    for name in names:
        values = [row["numeric"].get(name) for row in rows]
        present = [v for v in values if v is not None]
        if len(present) < 2 * MIN_BUCKET:
            continue
        variants = [("", 1)]
        if min(present) < 0 < max(present):
            variants.append(("@signed", None))
        for suffix, _ in variants:
            if suffix:
                vals = [None if v is None else v * row["sign"] for v, row in zip(values, rows)]
            else:
                vals = values
            labels = _numeric_buckets(vals)
            if labels is None:
                constant.append(name + suffix)
                continue
            results.append(_field_result(name + suffix, "numeric", rows, labels,
                                         permutations, seed))

    # ---- categorical
    cat_names = sorted({name for row in rows for name in row["categorical"]})
    for name in cat_names:
        pairs = [(row["categorical"][name], row) for row in rows if name in row["categorical"]]
        if len(pairs) < 2 * MIN_BUCKET:
            continue
        distinct = {label for label, _ in pairs}
        if len(distinct) < 2:
            constant.append(name)
            continue
        if len(distinct) > MAX_CATEGORIES:
            continue
        labels = [label for label, _ in pairs]
        keep = [row for _, row in pairs]
        results.append(_field_result(name, "categorical", keep, labels, permutations, seed))

    # The stored analysis carries most readings twice (top level and under
    # m1_analysis_raw, or final_verdict and m1_audit). Identical splits are
    # one hypothesis: counting each copy would double the family and make the
    # FDR correction harsher than the evidence warrants. Kept: the shortest path.
    unique: Dict[Tuple, Dict[str, Any]] = {}
    for result in filter(None, results):
        key = (tuple(sorted((str(b["value"]), b["n"], b["wins"], b["net_r"])
                            for b in result["buckets"])),)
        kept = unique.get(key)
        if kept is None or len(result["field"]) < len(kept["field"]):
            if kept is not None:
                result.setdefault("aliases", []).extend([kept["field"], *kept.get("aliases", [])])
            unique[key] = result
        else:
            kept.setdefault("aliases", []).append(result["field"])
    duplicates = len([r for r in results if r]) - len(unique)
    results = list(unique.values())
    benjamini_hochberg(results)
    results.sort(key=lambda r: (r.get("q") if r.get("q") is not None else 2.0,
                                r.get("p") if r.get("p") is not None else 2.0))
    return {"tested": sum(1 for r in results if r.get("p") is not None),
            "described": len(results), "constant_fields": len(constant),
            "duplicate_paths_merged": duplicates,
            "fields": results, "rows": n}


def _numeric_buckets(values: Sequence[Optional[float]]):
    present = sorted(v for v in values if v is not None)
    distinct = sorted(set(present))
    if len(distinct) < 2:
        return None
    if len(distinct) <= 6:
        return [None if v is None else _fmt(v) for v in values]
    lo = present[len(present) // 3]
    hi = present[(2 * len(present)) // 3]
    if lo == hi:
        cut = statistics.median(present)
        return [None if v is None else (f"<= {_fmt(cut)}" if v <= cut else f"> {_fmt(cut)}")
                for v in values]
    return [None if v is None else
            (f"LOW <= {_fmt(lo)}" if v <= lo else f"HIGH > {_fmt(hi)}" if v > hi else "MID")
            for v in values]


def _field_result(name: str, kind: str, rows: Sequence[Mapping[str, Any]],
                       labels: Sequence[Any], permutations: int, seed: int) -> Optional[Dict[str, Any]]:
    pairs = [(label, row) for label, row in zip(labels, rows) if label is not None]
    if len(pairs) < 2 * MIN_BUCKET:
        return None
    groups: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
    for label, row in pairs:
        groups[label].append(row)
    if len(groups) < 2:
        return None
    buckets = []
    for label, members in groups.items():
        s = summarise(members)
        s["value"] = label
        buckets.append(s)
    buckets.sort(key=lambda b: -b["n"])
    result = {"field": name, "kind": kind, "coverage": len(pairs), "buckets": buckets}
    test = permutation_best_bucket([l for l, _ in pairs], [r["r"] for _, r in pairs],
                                   permutations, seed)
    if test:
        result.update(test)
        # SELLs outperformed BUYs over this sample, so any reading that mostly
        # separates longs from shorts "predicts" the outcome by restating the
        # direction. Flag it: such a split is not independent evidence.
        members = groups[test["best_bucket"]]
        overall = sum(1 for _, r in pairs if r["direction"] == "SELL") / len(pairs)
        inside = sum(1 for r in members if r["direction"] == "SELL") / len(members)
        result["sell_share_best_vs_all"] = [round(inside, 2), round(overall, 2)]
        result["direction_proxy"] = abs(inside - overall) >= 0.25
    return result


# ============================================================
# ENTRY POINT
# ============================================================

def evaluate(trades: Optional[Iterable[Mapping[str, Any]]] = None, *,
             permutations: int = DEFAULT_PERMUTATIONS, seed: int = DEFAULT_SEED,
             include_fields: bool = True, include_oos: bool = True) -> Dict[str, Any]:
    """The full evaluation. Loads closed trades from MongoDB when none are given."""
    if trades is None:
        from ai.trade_repository import load_trades
        trades = load_trades()
    trades = list(trades)

    rows, excluded = build_rows(trades)
    report: Dict[str, Any] = {"component": "trade_evaluation", "version": EVALUATION_VERSION,
                              "generated_at": datetime.now(timezone.utc).isoformat(),
                              "trades_supplied": len(trades), "scored": len(rows),
                              "excluded": excluded, "permutations": permutations}
    if not rows:
        report["error"] = "no scorable trades"
        return report

    dated = [row["opened_at"] for row in rows if row["opened_at"]]
    if dated:
        report["period"] = [min(dated).isoformat(), max(dated).isoformat()]

    report["headline"] = summarise(rows)
    report["equity"] = equity(rows)

    segments = [
        segment(rows, lambda r: r["leverage"], "leverage", permutations, seed),
        segment(rows, lambda r: _asset_class(r["symbol"]), "asset_class", permutations, seed),
        segment(rows, lambda r: r["direction"], "direction", permutations, seed),
        segment(rows, lambda r: r["close_reason"], "close_reason", permutations, seed),
        segment(rows, lambda r: _session(r["opened_at"]), "session_utc", permutations, seed),
        segment(rows, lambda r: r["opened_at"].strftime("%a") if r["opened_at"] else None,
                "weekday", permutations, seed),
        segment(rows, lambda r: _rr_band(r["planned_rr"]), "planned_rr", permutations, seed),
        segment(rows, lambda r: r["symbol"], "symbol", permutations, seed),
    ]
    # Close reason is an OUTCOME, not a pre-trade reading: its "significance"
    # is trivially true (take-profits win). It is shown for the breakdown and
    # excluded from the multiple-testing family.
    benjamini_hochberg([s for s in segments if s["segment"] != "close_reason"])
    report["segments"] = segments

    report["execution"] = execution(rows)
    report["ledger"] = ledger_components(rows, permutations, seed)

    if include_fields:
        report["fields"] = discovered_fields(rows, permutations, seed)

    if include_oos:
        report["oos"] = _out_of_sample(trades)

    return report


def _out_of_sample(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Walk-forward verdicts from component_audit_360, summarised."""
    try:
        from ai import component_audit_360 as audit
        result = audit.audit(trades=[t for t in trades if isinstance(t, Mapping)])
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    out = {"available": True, "trades": result.get("trades"),
           "ok": result.get("ok"), "reason": result.get("reason"),
           "fields_discovered": result.get("fields_discovered")}
    for key in ("counts", "null", "edges", "inverted", "strongest_untested"):
        if key in result:
            out[key] = result[key]
    return out


# ============================================================
# HELPERS
# ============================================================

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: float) -> str:
    return f"{value + 0.0:.4g}"     # + 0.0 folds -0.0, which printed as its own bucket


def _share(values, predicate) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(100 * sum(1 for v in values if predicate(v)) / len(values), 1) if values else None


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _leverage(trade: Mapping[str, Any]) -> Optional[int]:
    from core.mongo.trade_query import leverage_of
    lev = leverage_of(trade)
    if lev is None:
        lev = _num((((trade.get("analysis_at_open") or {}).get("account_info") or {}).get("leverage")))
    return int(lev) if lev is not None else None


def _close_reason(value: Any) -> str:
    text = str(value or "UNKNOWN").upper()
    if text.startswith("TAKE_PROFIT") or text in ("TP", "TP_HIT"):
        return "TAKE_PROFIT"
    if text.startswith("STOP") or text in ("SL", "SL_HIT"):
        return "STOP_LOSS"
    return text


def _asset_class(symbol: str) -> str:
    s = (symbol or "").upper()
    if s.startswith(("XAU", "XAG")) or "GOLD" in s or "SILVER" in s:
        return "METALS"
    if s.endswith((".NAS", ".NYSE")):
        return "STOCKS"
    if "OIL" in s or s in ("XBRUSD", "XTIUSD", "XNGUSD"):
        return "ENERGY"
    if any(k in s for k in ("US30", "NAS100", "SPX", "US500", "GER", "UK100", "JP225", "QQQ")):
        return "INDICES"
    return "FX"


def _session(opened: Optional[datetime]) -> Optional[str]:
    if not opened:
        return None
    hour = opened.astimezone(timezone.utc).hour
    if hour < 1:
        return "00-01 ROLLOVER"
    if hour < 7:
        return "01-07 ASIA"
    if hour < 12:
        return "07-12 LONDON"
    if hour < 16:
        return "12-16 LONDON/NY"
    if hour < 21:
        return "16-21 NEW YORK"
    return "21-24 LATE"


def _rr_band(rr: Optional[float]) -> Optional[str]:
    if rr is None:
        return None
    if rr < 2:
        return "< 2"
    if rr < 4:
        return "2-4"
    if rr < 7:
        return "4-7"
    return ">= 7"


# ============================================================
# REPORT
# ============================================================

def _line(b: Mapping[str, Any]) -> str:
    lo, hi = b.get("win_rate_ci95") or (None, None)
    flag = "  (small)" if b.get("small_sample") else ""
    net_r = b.get("expectancy_net_r")
    net_text = f"{net_r:+.2f}" if net_r is not None else "  n/a"
    return (f"{str(b.get('value', '')):<28} n={b['n']:>3}  win {b['win_rate']:>5.1f}% "
            f"[{lo}-{hi}]  E={b['expectancy_r']:+.3f}R net={net_text}R  ${b['net_usd']:>8.2f}  "
            f"PF={b.get('profit_factor')}{flag}")


def format_report(report: Mapping[str, Any], top_fields: int = 25) -> str:
    out: List[str] = []
    add = out.append
    add(f"TRADE EVALUATION v{report.get('version')}  -- {report.get('scored')} scored of "
        f"{report.get('trades_supplied')}  excluded={report.get('excluded')}")
    if report.get("error"):
        add(report["error"])
        return "\n".join(out)
    add(f"period {report.get('period')}")

    h = report["headline"]
    add("\n== HEADLINE ==")
    for key in ("n", "wins", "losses", "breakeven", "win_rate", "win_rate_ci95", "expectancy_r",
                "expectancy_r_ci95", "expectancy_net_r", "expectancy_usd", "net_usd", "net_r", "avg_win_r",
                "avg_loss_r", "payoff", "breakeven_win_rate", "profit_factor", "median_r"):
        add(f"  {key:<20} {h.get(key)}")
    add("\n== EQUITY (R) ==")
    for key, value in report["equity"].items():
        add(f"  {key:<24} {value}")

    add("\n== SEGMENTS ==")
    for seg in report["segments"]:
        test = (f"best={seg.get('best_bucket')} contrast={seg.get('contrast_r')}R "
                f"p={seg.get('p')} q={seg.get('q')}" if seg.get("p") is not None else "not testable")
        add(f"\n-- {seg['segment']}   [{test}]")
        for b in seg["buckets"]:
            window = f"  {b.get('first_trade')}..{b.get('last_trade')}" if seg["segment"] == "leverage" else ""
            add("  " + _line(b) + window)

    add("\n== EXECUTION ==")
    for key, value in report["execution"].items():
        add(f"  {key:<32} {value}")

    add("\n== LEDGER COMPONENTS (push FOR / AGAINST the traded direction) ==")
    ledger = report["ledger"]
    for comp in sorted(ledger["components"], key=lambda c: c.get("p") if c.get("p") is not None else 2):
        add(f"\n-- {comp['segment']}   dWin(FOR-AGAINST)={comp.get('win_rate_for_minus_against')}  "
            f"dE={comp.get('expectancy_for_minus_against')}  p={comp.get('p')} q={comp.get('q')}")
        for b in comp["buckets"]:
            add("  " + _line(b))
    add(f"\n  never moved the probability: {ledger['never_moved_probability']}")

    fields = report.get("fields")
    if fields:
        add(f"\n== ANALYSIS FIELDS: {fields['tested']} tested, {fields['described']} described, "
            f"{fields['constant_fields']} constant, {fields.get('duplicate_paths_merged')} "
            f"duplicate paths merged ==")
        add(f"  top {top_fields} by q (a q above ~0.10 is indistinguishable from chance)")
        for f in fields["fields"][:top_fields]:
            proxy = (f"  DIRECTION PROXY (SELL share {f['sell_share_best_vs_all'][0]} vs "
                     f"{f['sell_share_best_vs_all'][1]})" if f.get("direction_proxy") else "")
            add(f"\n-- {f['field']}  best={f.get('best_bucket')} contrast={f.get('contrast_r')}R "
                f"p={f.get('p')} q={f.get('q')}{proxy}")
            for b in f["buckets"]:
                add("  " + _line(b))

    oos = report.get("oos")
    if oos:
        add("\n== OUT OF SAMPLE (component_audit_360 walk-forward) ==")
        add(f"  counts={oos.get('counts')}  reason={oos.get('reason')}")
        for f in (oos.get("edges") or []) + (oos.get("inverted") or []):
            add(f"  {f.get('verdict'):<9} {f.get('field')}  edge={f.get('edge')}")
    return "\n".join(out)


# ============================================================
# STATUS / SELF CHECK
# ============================================================

def get_status() -> Dict[str, Any]:
    return {"component": "trade_evaluation", "version": EVALUATION_VERSION,
            "min_bucket": MIN_BUCKET, "permutations_default": DEFAULT_PERMUTATIONS}


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Prove the evaluation scores real trades and refuses garbage.

    ok=None with no trades (nothing exercised); ok=False when trades were given
    but none could be scored; ok=True when rows were scored and the numbers
    reconcile -- wins + losses + breakeven == n, and the win rate lies inside
    its own confidence interval.
    """
    report: Dict[str, Any] = {"component": "trade_evaluation", "ok": None, "checks": {}}
    if not trades:
        report["reason"] = "no trades supplied"
        return report
    try:
        rows, excluded = build_rows(trades)
        report["checks"]["scored"] = len(rows)
        report["checks"]["excluded"] = excluded
        if not rows:
            report["ok"] = False
            report["reason"] = "no scorable trades (need close profit, entry, stop, close price)"
            return report
        head = summarise(rows)
        lo, hi = head["win_rate_ci95"]
        reconciles = head["wins"] + head["losses"] + head["breakeven"] == head["n"]
        inside = lo is not None and lo <= head["win_rate"] <= hi
        report["checks"].update({"counts_reconcile": reconciles, "win_rate_inside_ci": inside})
        report["ok"] = bool(reconciles and inside)
        return report
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        return report


if __name__ == "__main__":
    import json
    import os
    import sys

    logging.basicConfig(level=logging.WARNING)
    result = evaluate()
    text = format_report(result)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(text)

    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"trade_evaluation_{stamp}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, default=str)
    print(f"\nsaved {path}")
