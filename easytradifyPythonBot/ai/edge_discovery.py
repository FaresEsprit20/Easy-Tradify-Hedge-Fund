# ============================================================
# EDGE DISCOVERY -- SEARCH THE RULE SPACE ON REAL OUTCOMES
# ============================================================
# FILE: ai/edge_discovery.py
#
# The mission is a DIFFERENT edge, not a better-tuned version of the current
# one. This is the component that searches for it.
#
# THE IDEA
# --------
# `final_verdict.probability_ledger` records what every component contributed
# to a trade's probability, step by step:
#
#     {"step": "pattern", "before": 50.0, "after": 64.4, "delta": 14.4}
#
# So a RULE CONFIGURATION is just a weight vector over those steps:
#
#     probability(w) = base + SUM_i  w_i * delta_i
#
# w = 1 everywhere reproduces the live system exactly. w = 0 for a step turns
# that component off. w = -1 inverts it. Every combination in between is a
# different trading system -- and all of them can be scored against the SAME
# real price outcomes, because the outcome of a trade does not depend on how
# we weighted the reasoning that led to it.
#
# WHY THIS BEATS GENERATING SYNTHETIC MARKETS
# -------------------------------------------
# A diffusion model or GAN trained on this history reproduces its statistical
# properties, so a strategy optimised against it exploits the GENERATOR's
# artifacts. You find an edge against your own model. Synthetic markets are
# for stress-testing an edge you already have, never for discovering one.
# Here every outcome is a real price that really happened.
#
# WHY IT IS STATISTICALLY EFFICIENT
# ---------------------------------
# Every configuration is evaluated on the IDENTICAL set of trades, so
# comparisons are PAIRED. Market-regime variance -- which dominates
# unpaired comparisons and is why 215 unpaired trades could not separate
# anything -- cancels out. A paired test on the same 215 trades has far more
# power than two independent samples of 215.
#
# THE DANGER, AND WHAT IS DONE ABOUT IT
# -------------------------------------
# The search space is enormous, so SOMETHING will always look good. Four
# controls, because this project has produced four false positives already by
# skipping them:
#
#   1. chronological split -- configurations are chosen on train, scored on test
#   2. a permutation null -- outcomes shuffled, the identical search re-run, so
#      the report states what the BEST configuration looks like when there is
#      no signal at all
#   3. the number of configurations tested is always reported
#   4. sparsity is preferred -- a configuration touching two components is
#      likelier to be real than one touching fifteen
# ============================================================

from __future__ import annotations

import logging
import random
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

EDGE_DISCOVERY_VERSION = "1.0"

PROB_FLOOR, PROB_CEIL = 5.0, 95.0


# ============================================================
# EXTRACTION
# ============================================================

def extract_samples(trades: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    One row per trade: the ledger deltas, the base, and the REAL outcome in R.

    Deltas are re-expressed relative to the TRADED direction. Every chained
    scorer signs its contribution against `best_direction`, which differs from
    the direction actually filled on ~19% of trades -- and reading them in the
    wrong frame turned a measured +0.49R component edge into an apparent sign
    error. Getting this wrong invalidates everything downstream, so it is done
    once, here.
    """
    from ai import trade_repository as repo

    rows: List[Dict[str, Any]] = []
    for trade in trades:
        entry = trade.get("entry") or {}
        close = trade.get("close_data") or {}
        ep, sl, cp = entry.get("price"), entry.get("stop_loss"), close.get("close_price")
        if not all(isinstance(v, (int, float)) for v in (ep, sl, cp)) or ep == sl:
            continue

        traded = trade.get("direction")
        sign = 1 if traded == "BUY" else -1
        r = sign * (cp - ep) / abs(ep - sl)

        ledger = repo.ledger_of(trade)
        if not ledger:
            continue
        best = repo.best_direction_of(trade)
        frame = 1 if best == traded else -1

        base = ledger[0].get("before")
        deltas = {}
        for step in ledger:
            name, delta = step.get("step"), step.get("delta")
            if name and isinstance(delta, (int, float)):
                deltas[name] = float(delta) * frame

        # The realised price path, in R from entry, signed for the traded
        # direction. This is what lets a configuration change the EXIT as well
        # as the entry -- and exits carry more measurable edge in this data
        # than entry filters do, so a search that cannot touch them is
        # searching the smaller half of the space.
        risk = abs(ep - sl)
        path_r: List[float] = []
        for point in (trade.get("price_evolution") or []):
            price = point.get("price") if isinstance(point, Mapping) else None
            if isinstance(price, (int, float)):
                path_r.append(sign * (price - ep) / risk)

        rows.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "opened_at": str(trade.get("opened_at") or ""),
            "r": r,
            "win": 1 if r > 0 else 0,
            "base": float(base) if isinstance(base, (int, float)) else 50.0,
            "deltas": deltas,
            "path_r": path_r,
            # Measurements, NOT probability contributions -- see features_of().
            "features": features_of(trade),
        })

    rows.sort(key=lambda x: x["opened_at"])
    return rows


FEATURE_CHANNELS = (
    "microstructure_at_entry",
    "microstructure_bias",
    "strategy_family_scores",
    "component_reads",
)


def features_of(trade: Mapping[str, Any]) -> Dict[str, float]:
    """
    The measurement channels a trade carries, flattened to numbers.

    WHY THESE ARE NOT `deltas`
    --------------------------
    `deltas` are probability-chain contributions, and the reweighting search
    multiplies them into the probability. These are not contributions -- they
    are observations recorded ALONGSIDE the decision, deliberately carrying
    `contribution: 0.0` so they cannot move the probability until validated.
    Feeding them into `deltas` would wire an unvalidated component straight
    into the chain, which is precisely the mistake that had `pattern` pushing
    12 probability points the wrong way on 26% of trades.

    So they get their own namespace and their own search (search_features),
    which CONDITIONS on them -- "would skipping trades where flow opposes the
    fill have helped?" -- without touching the probability.

    WHY THIS EXISTS AT ALL
    ----------------------
    Every trade has been recording microstructure_at_entry,
    strategy_family_scores and component_reads, and nothing in ai/ read any of
    them: extract_samples built rows from the ledger and the price path only.
    The one edge this project confirmed from NEW information -- microstructure
    order flow, +0.2646R, 4/4 folds, p=0.0180 -- was therefore invisible to
    the search that is supposed to find it.

    Booleans become 1.0/0.0 so a filter threshold works uniformly. Keys are
    prefixed by channel so two channels cannot collide on a short name.
    """
    analysis = trade.get("analysis_at_open") or {}
    out: Dict[str, float] = {}

    def _add(prefix: str, blob: Any) -> None:
        if not isinstance(blob, Mapping):
            return
        for key, value in blob.items():
            if key in ("available", "reason", "version", "symbol", "note",
                       "as_of_epoch"):
                continue
            if isinstance(value, bool):
                out[f"{prefix}.{key}"] = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                out[f"{prefix}.{key}"] = float(value)
            elif isinstance(value, Mapping):
                # component_reads nests one level (gnn, wyckoff, ...).
                for sub, sval in value.items():
                    if isinstance(sval, bool):
                        out[f"{prefix}.{key}.{sub}"] = 1.0 if sval else 0.0
                    elif isinstance(sval, (int, float)):
                        out[f"{prefix}.{key}.{sub}"] = float(sval)

    for channel in FEATURE_CHANNELS:
        _add(channel.replace("_at_entry", "").replace("strategy_", ""),
             analysis.get(channel))

    return out


def feature_names(samples: Sequence[Mapping[str, Any]],
                  min_present: int = 10) -> List[str]:
    """
    Features present on enough trades to test, most-populated first.

    `min_present` is a floor, not a nicety: a feature on three trades will
    produce a spectacular subset and mean nothing, and every such feature
    also costs an FDR correction against the ones that might be real.
    """
    tally: Dict[str, int] = {}
    for row in samples:
        for name in (row.get("features") or {}):
            tally[name] = tally.get(name, 0) + 1
    return sorted((n for n, c in tally.items() if c >= min_present),
                  key=lambda n: -tally[n])


def component_names(samples: Sequence[Mapping[str, Any]]) -> List[str]:
    """Components that actually move the probability on some trade."""
    active: Dict[str, int] = {}
    for row in samples:
        for name, delta in row["deltas"].items():
            if abs(delta) > 1e-9:
                active[name] = active.get(name, 0) + 1
    return sorted(active, key=lambda n: -active[n])


# ============================================================
# SCORING A CONFIGURATION
# ============================================================

def probability_under(row: Mapping[str, Any],
                      weights: Mapping[str, float]) -> float:
    """
    What the probability WOULD have been under this weighting.

    Clamped once at the end rather than after every step. The live chain
    clamps per step, which makes a component's influence depend on its
    position in the chain and on whether earlier steps happened to saturate --
    both arbitrary. Clamping once is order-independent, which is what makes
    the weights mean something.
    """
    total = row["base"]
    for name, delta in row["deltas"].items():
        total += weights.get(name, 1.0) * delta
    return max(PROB_FLOOR, min(PROB_CEIL, total))


def r_under_exit(row: Mapping[str, Any], take_profit: Optional[float],
                 stop_loss: Optional[float], flip: bool = False) -> float:
    """
    The R this trade would have returned under a different exit geometry.

    Walks the realised path. `flip` reverses the direction, which negates the
    whole path -- the same market move, traded the other way.

    When neither level is reached the trade is scored at its final price, not
    discarded. Dropping unresolved trades is precisely the error that made an
    earlier exit study report 77.6% win rate: it silently measured only the
    fifth of trades that resolved.

    With no path recorded, falls back to the realised R. That is honest --
    the trade happened, we just cannot re-cut it.
    """
    path = row.get("path_r") or []
    realised = -row["r"] if flip else row["r"]
    if not path:
        return realised
    if take_profit is None and stop_loss is None:
        return realised

    for value in path:
        r = -value if flip else value
        if stop_loss is not None and r <= -abs(stop_loss):
            return -abs(stop_loss)
        if take_profit is not None and r >= abs(take_profit):
            return abs(take_profit)
    last = path[-1]
    return -last if flip else last


def evaluate(samples: Sequence[Mapping[str, Any]],
             weights: Mapping[str, float],
             threshold: float,
             *, flip: bool = False,
             take_profit: Optional[float] = None,
             stop_loss: Optional[float] = None) -> Dict[str, Any]:
    """
    Score one configuration: which trades it takes, which way, and how it exits.

    `flip` is the axis a take/skip search cannot reach. Direction entropy on
    this account measures 1.0000 -- entries are directionally random -- so if
    an edge exists in the components it may well be an INVERSE one, and a
    search that can only skip trades can never find it.
    """
    kept = [row for row in samples
            if probability_under(row, weights) >= threshold]
    if not kept:
        return {"trades": 0, "win_rate": None, "expectancy": None,
                "total_r": 0.0, "coverage": 0.0, "returns": []}

    rs = [r_under_exit(row, take_profit, stop_loss, flip) for row in kept]
    wins = sum(1 for r in rs if r > 0)
    return {
        "trades": len(kept),
        "win_rate": round(100.0 * wins / len(rs), 2),
        "expectancy": round(statistics.mean(rs), 4),
        "total_r": round(sum(rs), 3),
        "coverage": round(100.0 * len(kept) / len(samples), 1),
        "returns": rs,
    }


# ============================================================
# STATISTICS
# ============================================================

def walk_forward_folds(rows: Sequence[Mapping[str, Any]], folds: int = 4
                       ) -> List[Tuple[List, List]]:
    """
    Expanding-window folds: train on everything before, test on the next block.

    A single 70/30 split validates on 30% of the data ONCE. Four expanding
    folds test on most of the series while never letting a fold see its own
    future -- several times the validation evidence from the same trades,
    which is the cheapest power available when trades are the scarce resource.
    """
    n = len(rows)
    if n < folds * 20:
        cut = int(n * 0.7)
        return [(list(rows[:cut]), list(rows[cut:]))]
    block = n // (folds + 1)
    out = []
    for i in range(1, folds + 1):
        train_end = block * i
        test_end = block * (i + 1) if i < folds else n
        out.append((list(rows[:train_end]), list(rows[train_end:test_end])))
    return out


def benjamini_hochberg(pvalues: Sequence[float], alpha: float = 0.10
                       ) -> List[bool]:
    """
    Which p-values survive FDR control at `alpha`.

    Applied to EVERY configuration tested, not only those that already looked
    good. Correcting after an effect-size filter inflates the false-positive
    rate badly -- measured in this project at 67% versus 16.7% when done
    correctly -- because the filter has already used the data.
    """
    indexed = sorted(enumerate(pvalues), key=lambda kv: kv[1])
    m = len(pvalues)
    keep = [False] * m
    largest = -1
    for rank, (index, p) in enumerate(indexed, start=1):
        if p <= alpha * rank / m:
            largest = rank
    for rank, (index, _) in enumerate(indexed, start=1):
        if rank <= largest:
            keep[index] = True
    return keep


def paired_pvalue(returns: Sequence[float], baseline: Sequence[float],
                  trials: int = 2000, seed: int = 11) -> float:
    """
    Probability this configuration beats the baseline by chance.

    A PAIRED sign-flip test: both are measured on the same trades, so the
    market-regime variance that dominates unpaired comparisons cancels. That
    pairing is what makes a few hundred trades informative at all.
    """
    if not returns or not baseline:
        return 1.0
    n = min(len(returns), len(baseline))
    diffs = [returns[i] - baseline[i] for i in range(n)]
    observed = statistics.mean(diffs)
    if observed <= 0:
        return 1.0
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        flipped = statistics.mean(d if rng.random() < 0.5 else -d for d in diffs)
        if flipped >= observed:
            hits += 1
    return (hits + 1) / (trials + 1)


# ============================================================
# THE SEARCH
# ============================================================

class Config(dict):
    """One candidate trading system: which trades, which way, which exit."""

    @property
    def label(self) -> str:
        return self["label"]

    def score(self, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        return evaluate(rows, self["weights"], self["threshold"],
                        flip=self["flip"], take_profit=self["take_profit"],
                        stop_loss=self["stop_loss"])


def _configs(names: Sequence[str], thresholds: Sequence[float],
             max_components: int = 2,
             exits: Sequence[Tuple[Optional[float], Optional[float]]] = ((None, None),),
             allow_flip: bool = True) -> List[Config]:
    """
    Candidate configurations, deliberately SPARSE in the components.

    Only `max_components` are altered at a time. A configuration touching two
    components and holding out of sample is far likelier to be real than one
    touching fifteen, which has enough freedom to fit noise exactly.

    Three axes are searched together, because an edge can live in their
    COMBINATION and none of them finds it alone:

      weights   which components vote, inverted or amplified
      flip      trade the opposite direction -- reachable only because
                direction entropy is 1.0, so the current entries carry no
                directional information to preserve
      exit      where the target and stop sit, in R

    The product is large, which is exactly why the permutation null below is
    computed over the SAME product rather than over a single hypothesis.
    """
    import itertools

    settings = (0.0, -1.0, 2.0)
    names_for = {0.0: "off", -1.0: "inverted", 2.0: "doubled"}
    flips = (False, True) if allow_flip else (False,)

    def make(label, weights, threshold, flip, tp, sl):
        parts = [label]
        if flip:
            parts.append("DIRECTION FLIPPED")
        if tp is not None or sl is not None:
            parts.append("exit TP%s/SL%s" % (tp if tp is not None else "-",
                                             sl if sl is not None else "-"))
        if threshold:
            parts.append("prob>=%g" % threshold)
        return Config(label=" | ".join(parts), weights=weights,
                      threshold=threshold, flip=flip,
                      take_profit=tp, stop_loss=sl)

    out: List[Config] = []
    for threshold in thresholds:
        for flip in flips:
            for tp, sl in exits:
                out.append(make("baseline", {}, threshold, flip, tp, sl))

    for size in range(1, max_components + 1):
        for combo in itertools.combinations(names, size):
            for values in itertools.product(settings, repeat=size):
                weights = dict(zip(combo, values))
                label = ", ".join("%s %s" % (n, names_for[v])
                                  for n, v in weights.items())
                for threshold in thresholds:
                    for flip in flips:
                        for tp, sl in exits:
                            out.append(make(label, weights, threshold, flip,
                                            tp, sl))
    return out


DEFAULT_EXITS: Tuple[Tuple[Optional[float], Optional[float]], ...] = (
    (None, None),            # as traded
    (0.5, 1.0), (0.5, 1.5),  # high win rate geometries
    (1.0, 1.0), (1.5, 1.0),
    (2.0, 1.0), (2.0, 1.5),  # let winners run
    (3.0, 1.0),
)


def search_all(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
               samples: Optional[Sequence[Mapping[str, Any]]] = None,
               thresholds: Sequence[float] = (0.0, 55.0, 65.0, 75.0),
               max_components: int = 2,
               exits: Sequence[Tuple[Optional[float], Optional[float]]] = DEFAULT_EXITS,
               allow_flip: bool = True,
               folds: int = 4,
               min_train: int = 25,
               min_test: int = 12,
               target_win_rate: float = 60.0,
               target_expectancy: float = 0.0,
               alpha: float = 0.10,
               permutations: int = 60,
               seed: int = 20260909) -> Dict[str, Any]:
    """
    The full search: components x direction x exits x thresholds.

    Scored on WALK-FORWARD folds -- each fold trains on everything before it
    and tests on the block after, so a configuration must work repeatedly
    rather than once. A single split can be survived by luck; four
    consecutive out-of-sample blocks is a much harder bar, and it uses the
    same scarce trades several times over.

    Reported per configuration:
      folds_positive   how many out-of-sample blocks it made money in
      test_*           pooled out-of-sample performance
      p_value          PAIRED sign-flip test against the baseline on the same
                       trades, so regime variance cancels
      fdr_significant  survives Benjamini-Hochberg across EVERY configuration
                       tested, not just the ones that already looked good

    A configuration is only called an edge if it clears all of it AND beats
    the permutation null, which says what this identical search finds in data
    with no signal at all.
    """
    rows = list(samples) if samples is not None else extract_samples(trades or [])
    report: Dict[str, Any] = {
        "component": "edge_discovery",
        "version": EDGE_DISCOVERY_VERSION,
        "samples": len(rows),
        "target": {"win_rate": target_win_rate, "expectancy": target_expectancy},
    }
    if len(rows) < min_train + min_test:
        report["ok"] = None
        report["reason"] = "only %d trades; too few to search" % len(rows)
        return report

    names = component_names(rows)
    configs = _configs(names, thresholds, max_components, exits, allow_flip)
    blocks = walk_forward_folds(rows, folds)

    report.update({
        "components": names,
        "configurations_tested": len(configs),
        "folds": len(blocks),
        "path_coverage": round(100.0 * sum(
            1 for r in rows if r.get("path_r")) / len(rows), 1),
    })

    baseline = Config(label="baseline", weights={}, threshold=0.0, flip=False,
                      take_profit=None, stop_loss=None)
    base_test: List[float] = []
    for _, test_rows in blocks:
        base_test.extend(baseline.score(test_rows).get("returns") or [])
    report["baseline"] = {
        "trades": len(base_test),
        "win_rate": (round(100.0 * sum(1 for r in base_test if r > 0)
                           / len(base_test), 2) if base_test else None),
        "expectancy": round(statistics.mean(base_test), 4) if base_test else None,
    }

    scored: List[Dict[str, Any]] = []
    for config in configs:
        pooled: List[float] = []
        folds_positive = 0
        usable = 0
        for train_rows, test_rows in blocks:
            tr = config.score(train_rows)
            if not tr["trades"] or tr["trades"] < min_train:
                continue
            te = config.score(test_rows)
            if not te["trades"] or te["trades"] < min_test:
                continue
            usable += 1
            pooled.extend(te["returns"])
            if te["expectancy"] and te["expectancy"] > 0:
                folds_positive += 1
        if usable < max(2, len(blocks) - 1) or not pooled:
            continue
        wins = sum(1 for r in pooled if r > 0)
        scored.append({
            "label": config.label,
            "config": {k: v for k, v in config.items() if k != "label"},
            "folds_usable": usable,
            "folds_positive": folds_positive,
            "test_trades": len(pooled),
            "test_win_rate": round(100.0 * wins / len(pooled), 2),
            "test_expectancy": round(statistics.mean(pooled), 4),
            "test_total_r": round(sum(pooled), 2),
            "returns": pooled,
        })

    report["configurations_scored"] = len(scored)
    if not scored:
        report["ok"] = False
        report["conclusion"] = "no configuration retained enough trades to score"
        return report

    # Paired significance against the baseline, then FDR across ALL of them.
    for entry in scored:
        entry["p_value"] = round(
            paired_pvalue(entry["returns"], base_test, seed=seed), 4)
    flags = benjamini_hochberg([e["p_value"] for e in scored], alpha=alpha)
    for entry, keep in zip(scored, flags):
        entry["fdr_significant"] = bool(keep)

    # The null: the identical search on shuffled outcomes.
    rng = random.Random(seed)
    outcomes = [(r["r"], r["win"], list(r.get("path_r") or [])) for r in rows]
    null_e, null_w = [], []
    for _ in range(max(0, int(permutations))):
        rng.shuffle(outcomes)
        shuffled = []
        for row, (r, w, path) in zip(rows, outcomes):
            copy = dict(row)
            copy["r"], copy["win"], copy["path_r"] = r, w, path
            shuffled.append(copy)
        s_blocks = walk_forward_folds(shuffled, folds)
        best_e, best_w = -9.0, 0.0
        for config in configs:
            pooled = []
            for _, test_rows in s_blocks:
                res = config.score(test_rows)
                if res["trades"] and res["trades"] >= min_test:
                    pooled.extend(res["returns"])
            if len(pooled) >= min_test:
                best_e = max(best_e, statistics.mean(pooled))
                best_w = max(best_w, 100.0 * sum(1 for r in pooled if r > 0)
                             / len(pooled))
        if best_e > -9:
            null_e.append(best_e)
            null_w.append(best_w)

    if null_e:
        null_e.sort()
        null_w.sort()
        p95_e = null_e[int(0.95 * len(null_e))]
        p95_w = null_w[int(0.95 * len(null_w))]
        report["null"] = {
            "permutations": len(null_e),
            "expectancy_95th": round(p95_e, 4),
            "win_rate_95th": round(p95_w, 2),
            "note": "what this identical search finds with NO signal present",
        }
    else:
        p95_e, p95_w = 0.0, 100.0

    for entry in scored:
        entry["beats_null"] = (entry["test_expectancy"] > p95_e
                               and entry["test_win_rate"] > p95_w)
        entry.pop("returns", None)

    genuine = [e for e in scored
               if e["beats_null"] and e["fdr_significant"]
               and e["folds_positive"] >= max(2, e["folds_usable"] - 1)]
    hits_target = [e for e in genuine
                   if e["test_win_rate"] >= target_win_rate
                   and e["test_expectancy"] > target_expectancy]

    report["best_by_expectancy"] = sorted(
        scored, key=lambda e: -e["test_expectancy"])[:10]
    report["best_by_win_rate"] = sorted(
        scored, key=lambda e: -e["test_win_rate"])[:10]
    report["genuine"] = sorted(genuine, key=lambda e: -e["test_expectancy"])[:10]
    report["hits_target"] = sorted(hits_target,
                                   key=lambda e: -e["test_expectancy"])[:10]
    report["ok"] = bool(genuine)
    if not genuine:
        report["conclusion"] = (
            "%d configurations searched; none beats the noise floor across "
            "walk-forward folds. With %d trades the null band is wide enough "
            "to swallow any edge this size -- more trades, not more search."
            % (len(configs), len(rows)))
    return report


def search(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
           samples: Optional[Sequence[Mapping[str, Any]]] = None,
           thresholds: Sequence[float] = (0.0, 50.0, 60.0, 70.0),
           max_components: int = 2,
           min_trades: int = 25,
           min_test_trades: int = 12,
           target_win_rate: float = 60.0,
           permutations: int = 100,
           seed: int = 20260909) -> Dict[str, Any]:
    """
    Search rule configurations for one that holds out of sample.

    Returns the survivors AND the permutation null, because the null is what
    makes the survivors interpretable. A configuration that beats the 95th
    percentile of shuffled outcomes is worth forward-testing; one that does
    not is a coincidence with a label.
    """
    rows = list(samples) if samples is not None else extract_samples(trades or [])
    report: Dict[str, Any] = {
        "component": "edge_discovery",
        "version": EDGE_DISCOVERY_VERSION,
        "samples": len(rows),
    }
    if len(rows) < min_trades * 2:
        report["ok"] = None
        report["reason"] = (
            "only %d trades; a rule search needs far more before its result "
            "means anything" % len(rows))
        return report

    names = component_names(rows)
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    configs = _configs(names, thresholds, max_components)

    report.update({
        "components": names,
        "configurations_tested": len(configs),
        "train": len(train), "test": len(test),
        "baseline": {"train": evaluate(train, {}, 0.0),
                     "test": evaluate(test, {}, 0.0)},
    })

    scored = []
    for config in configs:
        label, weights, threshold = (config["label"], config["weights"],
                                     config["threshold"])
        tr = evaluate(train, weights, threshold)
        if not tr["trades"] or tr["trades"] < min_trades:
            continue
        te = evaluate(test, weights, threshold)
        if not te["trades"] or te["trades"] < min_test_trades:
            continue
        scored.append({"label": label, "weights": weights,
                       "threshold": threshold, "train": tr, "test": te})

    report["configurations_scored"] = len(scored)

    # Survivors: positive expectancy on BOTH splits, and the win-rate target
    # met on both. Requiring both splits is the whole discipline -- picking on
    # train alone is how this project produced four false positives.
    survivors = [c for c in scored
                 if c["train"]["expectancy"] > 0 and c["test"]["expectancy"] > 0
                 and c["train"]["win_rate"] >= target_win_rate
                 and c["test"]["win_rate"] >= target_win_rate]
    report["survivors"] = sorted(
        survivors, key=lambda c: -c["test"]["expectancy"])[:10]
    report["survivor_count"] = len(survivors)

    report["best_by_test_expectancy"] = sorted(
        scored, key=lambda c: -(c["test"]["expectancy"] or -9))[:10]

    # ---- the null: what does the best configuration look like with NO signal?
    rng = random.Random(seed)
    outcomes = [(row["r"], row["win"]) for row in rows]
    null_expectancy, null_win = [], []
    for _ in range(max(0, int(permutations))):
        rng.shuffle(outcomes)
        shuffled = []
        for row, (r, w) in zip(rows, outcomes):
            copy = dict(row)
            copy["r"], copy["win"] = r, w
            shuffled.append(copy)
        s_test = shuffled[cut:]
        best_e, best_w = -9.0, 0.0
        for config in configs:
            res = evaluate(s_test, config["weights"], config["threshold"])
            if res["trades"] and res["trades"] >= min_test_trades:
                best_e = max(best_e, res["expectancy"])
                best_w = max(best_w, res["win_rate"])
        if best_e > -9:
            null_expectancy.append(best_e)
            null_win.append(best_w)

    if null_expectancy:
        null_expectancy.sort()
        null_win.sort()
        p95_e = null_expectancy[int(0.95 * len(null_expectancy))]
        p95_w = null_win[int(0.95 * len(null_win))]
        report["null"] = {
            "permutations": len(null_expectancy),
            "expectancy_95th": round(p95_e, 4),
            "expectancy_max": round(null_expectancy[-1], 4),
            "win_rate_95th": round(p95_w, 2),
            "win_rate_max": round(null_win[-1], 2),
            "note": ("a configuration must beat these to be distinguishable "
                     "from luck, because this is what the SAME search finds "
                     "in data with no signal at all"),
        }
        report["genuine"] = [
            c for c in report["best_by_test_expectancy"]
            if c["test"]["expectancy"] > p95_e
            and (c["test"]["win_rate"] or 0) > p95_w
        ]

    report["ok"] = bool(report.get("genuine"))
    if not report["ok"]:
        report["conclusion"] = (
            "no configuration beats the noise floor on held-out trades. This "
            "is a statement about sample size as much as about the rules: "
            "with %d trades and %d configurations, the search cannot resolve "
            "an edge smaller than the null band." %
            (len(rows), len(configs)))
    return report


# ============================================================
# STATUS / SELF CHECK
# ============================================================

def search_features(trades: Optional[Sequence[Mapping[str, Any]]] = None, *,
                    samples: Optional[Sequence[Mapping[str, Any]]] = None,
                    folds: int = 4,
                    min_train: int = 25,
                    min_test: int = 12,
                    alpha: float = 0.10,
                    permutations: int = 60,
                    seed: int = 20260910) -> Dict[str, Any]:
    """
    Does conditioning on a MEASUREMENT channel beat taking every trade?

    One hypothesis per (feature, direction, threshold): keep only trades where
    the feature is above (or below) a quantile of its own training-fold
    distribution, and compare the kept trades' mean R against taking
    everything. Thresholds come from the TRAIN fold only -- deriving them from
    the full series is look-ahead, and it is the easiest way to manufacture an
    edge here.

    Every survivor must clear the same bar the rest of this module applies:
      * an expanding walk-forward, scored only on held-out blocks,
      * a permutation null on shuffled outcomes, and
      * Benjamini-Hochberg across EVERY hypothesis tested, not just the
        promising ones.

    On 215 trades, searching 82 hypotheses against shuffled outcomes still
    produced a best subset at 61.5% -- so an uncorrected number here means
    nothing at all.
    """
    if samples is None:
        if trades is None:
            from ai import trade_repository as repo
            trades = repo.load_trades(status="CLOSED")
        samples = extract_samples(trades)

    rows = sorted(samples, key=lambda r: r.get("opened_at") or "")
    names = feature_names(rows)
    if not rows or not names:
        return {"tested": 0, "survivors": [], "features": names,
                "reason": "no features present on enough trades"}

    folds_list = walk_forward_folds(rows, folds)
    results: List[Dict[str, Any]] = []

    for name in names:
        for side in ("above", "below"):
            for q in (0.25, 0.5, 0.75):
                kept_r: List[float] = []
                base_r: List[float] = []
                for train, test in folds_list:
                    tr = [r["features"][name] for r in train
                          if name in (r.get("features") or {})]
                    if len(tr) < min_train or len(test) < min_test:
                        continue
                    tr.sort()
                    cut = tr[min(len(tr) - 1, int(len(tr) * q))]
                    for r in test:
                        val = (r.get("features") or {}).get(name)
                        base_r.append(r["r"])
                        if val is None:
                            continue
                        if (side == "above" and val >= cut) or \
                           (side == "below" and val <= cut):
                            kept_r.append(r["r"])
                if len(kept_r) < min_test or not base_r:
                    continue
                results.append({
                    "feature": name, "side": side, "quantile": q,
                    "trades": len(kept_r),
                    "coverage": round(100.0 * len(kept_r) / len(base_r), 1),
                    "expectancy": round(statistics.mean(kept_r), 4),
                    "baseline": round(statistics.mean(base_r), 4),
                    "lift": round(statistics.mean(kept_r)
                                  - statistics.mean(base_r), 4),
                    "win_rate": round(
                        100.0 * sum(1 for r in kept_r if r > 0) / len(kept_r), 2),
                    "p": paired_pvalue(kept_r, base_r,
                                       trials=max(200, permutations * 20),
                                       seed=seed),
                })

    if not results:
        return {"tested": 0, "survivors": [], "features": names,
                "reason": "no hypothesis had enough held-out trades"}

    passed, _ = benjamini_hochberg([r["p"] for r in results], alpha=alpha)
    for r, ok in zip(results, passed):
        r["survives_fdr"] = bool(ok)

    survivors = sorted((r for r in results if r["survives_fdr"] and r["lift"] > 0),
                       key=lambda r: -r["lift"])
    return {
        "tested": len(results),
        "features": names,
        "survivors": survivors,
        "all": sorted(results, key=lambda r: r["p"]),
        "alpha": alpha,
        # Stated so a reader cannot mistake a raw p for a corrected one.
        "note": (f"{len(results)} hypotheses tested; "
                 f"{len(survivors)} survive BH-FDR at alpha={alpha} "
                 f"with positive lift"),
    }


def get_status() -> Dict[str, Any]:
    return {"component": "edge_discovery", "version": EDGE_DISCOVERY_VERSION,
            "method": "ledger reweighting on real outcomes",
            "synthetic_prices": False}


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None
               ) -> Dict[str, Any]:
    """
    Prove the search can find a PLANTED edge, and does not invent one.

    A search that cannot recover a signal it was handed is useless; a search
    that reports one in pure noise is worse. Both are checked.
    """
    rng = random.Random(7)
    planted, noise = [], []
    for i in range(300):
        d = rng.choice([-10.0, 10.0])
        # Planted: outcome follows the component exactly.
        planted.append({"trade_id": f"p{i}", "opened_at": f"{i:04d}",
                        "r": 1.0 if d > 0 else -1.0, "win": 1 if d > 0 else 0,
                        "base": 50.0, "deltas": {"good": d, "junk": rng.choice([-5.0, 5.0])}})
        r = rng.choice([-1.0, 1.0])
        noise.append({"trade_id": f"n{i}", "opened_at": f"{i:04d}",
                      "r": r, "win": 1 if r > 0 else 0, "base": 50.0,
                      "deltas": {"good": d, "junk": rng.choice([-5.0, 5.0])}})

    found = search(samples=planted, permutations=25, min_trades=20,
                   min_test_trades=10, target_win_rate=60.0)
    empty = search(samples=noise, permutations=25, min_trades=20,
                   min_test_trades=10, target_win_rate=60.0)

    checks = {
        "recovers_planted_edge": bool(found.get("survivor_count")),
        "planted_survivors": found.get("survivor_count", 0),
        "rejects_pure_noise": not empty.get("ok"),
        "noise_survivors_passing_null": len(empty.get("genuine") or []),
    }
    return {"component": "edge_discovery", "version": EDGE_DISCOVERY_VERSION,
            "checks": checks,
            "ok": checks["recovers_planted_edge"] and checks["rejects_pure_noise"]}
