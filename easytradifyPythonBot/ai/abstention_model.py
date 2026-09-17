# ============================================================
# SELECTIVE ABSTENTION
# ============================================================
#
# Finds the conditions under which this system reliably loses, and declines
# them. Raises expectancy by subtraction.
#
# WHY THIS IS NOT META-LABELING AGAIN
# -----------------------------------
# Meta-labeling was tested on this data and refused: AUC 0.5034 against a
# 0.5092 shuffled control. The package standard is not to re-litigate it
# without new features, and this module does not.
#
# The differences are structural, not cosmetic:
#
#   TARGET      expectancy in R, not win/loss classification. A rule that
#               removes trades with terrible payoff ratios helps even when it
#               cannot predict direction at all.
#
#   FEATURES    cost and structural conditions known before entry -- spread
#               against stop distance, risk fraction, session, zone grade,
#               volatility band. NOT direction predictors. Replay already
#               measured the effect: spread/stop >= 0.8 won 18.6% of the
#               time, and 22.8% of trades had a spread wider than the entire
#               stop. That is arithmetic, not forecasting.
#
#   FORM        univariate bucket rules, not a fitted per-trade classifier.
#               "Decline the top quintile of spread/stop" is auditable, holds
#               its meaning out of sample, and cannot silently become a
#               direction model.
#
# WHY UNIVARIATE
# --------------
# Multivariate buckets explode combinatorially and overfit long before they
# generalise: with a few hundred trades, any deep bucket containing five rows
# will show a spectacular expectancy by chance. One condition at a time keeps
# each rule interpretable and each estimate backed by enough rows to mean
# something.
#
# THE CONTROL
# -----------
# Selecting the worst-performing buckets in-sample is a multiple-comparison
# machine: scan enough conditions and some will look terrible by luck alone.
# The floor here shuffles OUTCOMES across trades and runs the identical
# selection procedure, measuring how much apparent expectancy the method
# invents from nothing. The real rules must beat that.
# ============================================================

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ABSTENTION_MODEL_VERSION = "1.0"

# Conditions known BEFORE entry. Deliberately cost- and structure-oriented:
# nothing here attempts to say which way price will go.
#
# Each entry is (name, dotted path, kind). Paths are tried in order against a
# merged view of analysis_at_open + entry, so a field moving does not silently
# empty the whole feature.
CANDIDATE_CONDITIONS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("spread_to_stop", ("__derived__", "spread_to_stop"), "numeric"),
    ("risk_percent", ("entry", "risk_percent_used"), "numeric"),
    ("stop_distance_r", ("__derived__", "stop_distance_pips"), "numeric"),
    ("atr_pips", ("volatility_protection", "atr_pips"), "numeric"),
    ("session", ("session_analysis", "session"), "categorical"),
    ("session_phase", ("session_analysis", "phase"), "categorical"),
    ("zone_grade", ("components", "4_supply_demand", "zone_grade"), "categorical"),
    ("regime", ("final_verdict", "market_regime"), "categorical"),
    ("symbol", ("__derived__", "symbol"), "categorical"),
    ("direction", ("__derived__", "direction"), "categorical"),
)


@dataclass
class AbstentionConfig:
    min_trades: int = 60
    test_fraction: float = 0.3
    quantile_bins: int = 5

    # A bucket needs this many trades before its expectancy is worth believing.
    # Small buckets are where multiple-comparison noise lives.
    min_bucket_trades: int = 15

    # Decline a bucket only when its mean R is at least this negative. A bucket
    # sitting near zero is not evidence of anything.
    decline_below_r: float = -0.15

    # ------------------------------------------------------------------
    # LEARNING FROM SUCCESS
    # ------------------------------------------------------------------
    # The scan was originally one-sided: it looked only for buckets to
    # decline. Measured on data where ASIA ran -1.03R and NY ran +1.16R, it
    # found the ASIA rule and was completely blind to NY -- the strongest
    # signal in the set. A system that only learns where it loses cannot say
    # where it should lean in, and the Monitor ranks competing candidates
    # with no idea which conditions have historically paid.
    #
    # Favour rules are discovered by the identical procedure with the sign
    # reversed, and carry the identical multiple-comparison hazard: scanning
    # for the BEST buckets finds spurious winners in noise exactly as readily
    # as scanning for the worst. They are validated out of sample and against
    # the same shuffled floor before being reported as real.
    favor_above_r: float = 0.15

    # ------------------------------------------------------------------
    # FULL-SNAPSHOT SCAN, AND THE CONTROL IT REQUIRES
    # ------------------------------------------------------------------
    # CANDIDATE_CONDITIONS lists ten conditions out of a payload carrying
    # ~125. Supply/demand appeared only as zone_grade; SMC structure, volume
    # profile, S/R, patterns, waves, indicators, vetos and leverage were not
    # scanned at all. Turning this on derives conditions from the whole
    # decision-time snapshot instead.
    #
    # That multiplies the hazard standard 15b describes: scanning ten
    # conditions for the worst bucket already finds losers in pure noise, and
    # scanning a hundred finds them roughly ten times as often. Width without
    # a correction does not produce more knowledge, it produces more false
    # rules that look exactly like real ones.
    #
    # So every candidate bucket now carries a Welch t-test against the rest
    # of the sample, and the surviving set is chosen by Benjamini-Hochberg at
    # `false_discovery_rate`. This applies to the ten hand-listed conditions
    # too: they were never exempt from the arithmetic, only from the check.
    auto_conditions: bool = False
    max_auto_conditions: int = 120
    false_discovery_rate: float = 0.10

    # Gates.
    min_expectancy_gain_r: float = 0.05
    min_gain_over_shuffle_r: float = 0.05
    max_declined_fraction: float = 0.5   # declining everything is not a strategy

    random_seed: int = 42


@dataclass
class AbstentionSample:
    trade_id: str
    timestamp: str
    conditions: Dict[str, Any]
    realized_r: float


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _dig(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().rstrip("%"))
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def build_abstention_samples(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[AbstentionConfig] = None,
    bridge: Any = None,
    conditions: Optional[Sequence[Tuple[str, Tuple[str, ...], str]]] = None,
) -> List[AbstentionSample]:
    """
    One sample per closed trade: the conditions at entry, and the realised R.

    R rather than win/loss on purpose. A condition that produces frequent small
    wins and rare catastrophic losses is invisible to a hit-rate target and
    obvious in expectancy -- and that asymmetry is exactly what abstention is
    meant to find.
    """
    cfg = config or AbstentionConfig()
    condition_list = list(conditions or CANDIDATE_CONDITIONS)
    if bridge is None:
        from .price_evolution_bridge import PriceEvolutionBridge
        bridge = PriceEvolutionBridge()

    samples: List[AbstentionSample] = []
    for trade in trades or []:
        try:
            canonical = bridge.to_canonical(trade)
        except Exception:
            continue

        entry = canonical.get("entry") or {}
        entry_price, stop_loss = entry.get("price"), entry.get("stop_loss")
        if not entry_price or not stop_loss:
            continue

        risk = abs(entry_price - stop_loss)
        if not risk:
            continue

        close = canonical.get("close_data") or {}
        close_price = close.get("close_price")
        if close_price is None:
            continue

        direction = str(canonical.get("direction") or "BUY").upper()
        sign = -1 if direction in {"SELL", "SHORT"} else 1
        realized_r = sign * (close_price - entry_price) / risk

        trade_id = str(canonical.get("trade_id") or canonical.get("ticket") or "")
        if not trade_id:
            continue

        analysis = canonical.get("analysis_at_open") or {}
        merged = {**analysis, "entry": entry}

        # Derived conditions: the ones replay actually implicated are ratios,
        # not raw fields, so they have to be computed rather than read.
        spread = _numeric(entry.get("spread_at_entry"))
        stop_pips = risk / 0.0001 if risk else None
        derived = {
            "spread_to_stop": (spread / stop_pips) if (spread and stop_pips) else None,
            "stop_distance_pips": stop_pips,
            "symbol": canonical.get("symbol"),
            "direction": direction,
        }

        context: Dict[str, float] = {}
        if any(path[0] == "__context__" for _, path, _ in condition_list):
            from .price_evolution_bridge import context_features
            context = context_features(trade, bridge)

        conditions: Dict[str, Any] = {}
        for name, path, kind in condition_list:
            if path[0] == "__derived__":
                raw = derived.get(path[1])
            elif path[0] == "__context__":
                raw = context.get(path[1])
            else:
                raw = _dig(merged, path)
            if kind == "numeric":
                conditions[name] = _numeric(raw)
            else:
                conditions[name] = str(raw) if raw is not None else None

        samples.append(AbstentionSample(
            trade_id=trade_id,
            timestamp=str(canonical.get("opened_at") or ""),
            conditions=conditions,
            realized_r=realized_r,
        ))

    return samples


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def _without(pool: Sequence[float], subset: Sequence[float]) -> List[float]:
    """`pool` minus one occurrence of each value in `subset`."""
    remaining = list(pool)
    for value in subset:
        try:
            remaining.remove(value)
        except ValueError:
            pass
    return remaining


def welch_t_test(sample_a: Sequence[float],
                 sample_b: Sequence[float]) -> Optional[float]:
    """
    Two-sided p-value for a difference in means, unequal variances.

    Returns None rather than a number when either side is too small or has no
    spread. An unmeasurable p-value must stay unmeasurable: defaulting it to
    1.0 would silently mark a bucket as "not significant" and defaulting it to
    0.0 would promote it, and both are claims the data does not support.
    """
    if len(sample_a) < 2 or len(sample_b) < 2:
        return None
    mean_a = sum(sample_a) / len(sample_a)
    mean_b = sum(sample_b) / len(sample_b)
    var_a = sum((v - mean_a) ** 2 for v in sample_a) / (len(sample_a) - 1)
    var_b = sum((v - mean_b) ** 2 for v in sample_b) / (len(sample_b) - 1)
    standard_error_squared = var_a / len(sample_a) + var_b / len(sample_b)
    if standard_error_squared <= 0:
        return None
    t_statistic = (mean_a - mean_b) / math.sqrt(standard_error_squared)

    # Welch-Satterthwaite degrees of freedom, then a normal approximation to
    # the tail. Exact enough at the bucket sizes this model gates on
    # (min_bucket_trades >= 15) and avoids a scipy dependency.
    numerator = standard_error_squared ** 2
    denominator = ((var_a / len(sample_a)) ** 2 / (len(sample_a) - 1)
                   + (var_b / len(sample_b)) ** 2 / (len(sample_b) - 1))
    if denominator <= 0:
        return None
    return round(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_statistic)
                                                    / math.sqrt(2.0)))), 6)


def benjamini_hochberg(p_values: Sequence[Optional[float]],
                       false_discovery_rate: float) -> List[bool]:
    """
    Which hypotheses survive at the given FDR.

    Bonferroni would be the simpler choice and the wrong one here: with ~600
    buckets it is so conservative that a real edge of the size this system
    trades on would never survive, and a control nobody can pass gets removed
    rather than respected. BH controls the expected PROPORTION of false
    discoveries instead, which is the quantity that actually matters when the
    output is a ranked list of rules.

    A candidate whose p-value could not be computed never survives.
    """
    indexed = [(index, p) for index, p in enumerate(p_values) if p is not None]
    survivors = [False] * len(p_values)
    if not indexed:
        return survivors
    indexed.sort(key=lambda pair: pair[1])
    total = len(indexed)
    cutoff_rank = 0
    for rank, (_, p_value) in enumerate(indexed, start=1):
        if p_value <= false_discovery_rate * rank / total:
            cutoff_rank = rank
    for rank, (index, _) in enumerate(indexed, start=1):
        if rank <= cutoff_rank:
            survivors[index] = True
    return survivors


def auto_conditions_from_trades(
    trades: Sequence[Mapping[str, Any]],
    limit: int,
    bridge: Any = None,
) -> Tuple[Tuple[str, Tuple[str, ...], str], ...]:
    """
    Candidate conditions derived from the whole decision-time snapshot.

    Ranked by how much they vary: a column that is constant across every trade
    cannot separate anything, and spending the scan budget on it only inflates
    the multiple-comparison denominator for no possible gain.
    """
    from .price_evolution_bridge import context_feature_union, context_vector

    # Built over the UNION of columns, with absence counted as 0.0.
    #
    # Collecting values per key as they appear makes every sparse indicator
    # look constant: a `session=ASIA` column exists only on ASIA trades, so
    # its observed values are [1.0, 1.0, ...] and a variance filter discards
    # it as useless. Measured on the fixtures, that silently rejected every
    # single categorical column -- the scan reported ten conditions when it
    # was asked for a hundred and twenty, and nothing said so.
    names = context_feature_union(trades, bridge)
    rows = [context_vector(trade, names, bridge) for trade in trades or []]
    if not rows:
        return ()
    values: Dict[str, List[float]] = {
        name: [row[index] for row in rows] for index, name in enumerate(names)
    }

    scored: List[Tuple[float, str]] = []
    for key, observations in values.items():
        if len(set(observations)) < 2:
            continue
        mean = sum(observations) / len(observations)
        variance = sum((v - mean) ** 2 for v in observations) / len(observations)
        spread = math.sqrt(variance)
        scale = abs(mean) if abs(mean) > 1e-9 else 1.0
        scored.append((spread / scale, key))

    scored.sort(key=lambda pair: -pair[0])
    return tuple((key, ("__context__", key), "numeric")
                 for _, key in scored[:limit])


def quantile_edges(values: Sequence[float], bins: int) -> List[float]:
    """Interior quantile boundaries; deduplicated so a spiky distribution
    collapses into fewer bins rather than producing empty ones."""
    usable = sorted(v for v in values if v is not None)
    if len(usable) < bins:
        return []
    edges = []
    for index in range(1, bins):
        position = int(len(usable) * index / bins)
        edges.append(usable[min(position, len(usable) - 1)])
    return sorted(set(edges))


def bucket_of(value: Any, edges: Sequence[float]) -> Optional[str]:
    if value is None:
        return None
    if not edges:
        return "all"
    for index, edge in enumerate(edges):
        if value <= edge:
            return f"q{index}"
    return f"q{len(edges)}"


class AbstentionRules:
    """
    A set of univariate decline rules, each backed by a bucket expectancy.

    Persisted as JSON: every rule is a condition name, a bucket label and the
    evidence behind it, so a human can read why a trade would be declined.
    """

    def __init__(self, config: Optional[AbstentionConfig] = None):
        self.config = config or AbstentionConfig()
        # The scanned conditions are instance state, not a module constant:
        # with auto_conditions they are derived from the training trades, and
        # a rule set that cannot say which conditions produced it cannot be
        # replayed or audited later.
        self.conditions: List[Tuple[str, Tuple[str, ...], str]] = list(
            CANDIDATE_CONDITIONS)
        self.edges: Dict[str, List[float]] = {}
        self.rules: List[Dict[str, Any]] = []
        self.favor_rules: List[Dict[str, Any]] = []
        # Kept rather than discarded: "we looked and it did not survive" is a
        # finding, and without it a later reader cannot tell an unscanned
        # condition from a rejected one.
        self.rejected_rules: List[Dict[str, Any]] = []
        self.fitted = False
        self.metadata: Dict[str, Any] = {}

    def _bucket_key(self, sample: AbstentionSample, name: str) -> Optional[str]:
        value = sample.conditions.get(name)
        if value is None:
            return None
        kind = next((k for n, _, k in self.conditions if n == name), "numeric")
        if kind == "numeric":
            return bucket_of(value, self.edges.get(name, []))
        return str(value)

    def fit(self, samples: Sequence[AbstentionSample]) -> Dict[str, Any]:
        if len(samples) < self.config.min_trades:
            raise ValueError(
                f"Need >= {self.config.min_trades} trades, got {len(samples)}.")

        # Quantile edges come from the training split only; deriving them over
        # all trades would leak the test distribution into the bucketing.
        self.edges = {}
        for name, _, kind in self.conditions:
            if kind == "numeric":
                values = [s.conditions.get(name) for s in samples]
                self.edges[name] = quantile_edges(
                    [v for v in values if v is not None], self.config.quantile_bins)

        overall = sum(s.realized_r for s in samples) / len(samples)
        self.rules = []
        self.favor_rules = []
        scanned = 0

        # Pass 1: every candidate that clears the effect-size threshold, each
        # with a p-value against the rest of the sample.
        candidates: List[Dict[str, Any]] = []
        all_r = [s.realized_r for s in samples]

        for name, _, _kind in self.conditions:
            buckets: Dict[str, List[float]] = {}
            for sample in samples:
                key = self._bucket_key(sample, name)
                if key is not None:
                    buckets.setdefault(key, []).append(sample.realized_r)

            for key, values in buckets.items():
                scanned += 1
                if len(values) < self.config.min_bucket_trades:
                    continue

                # EVERY eligible bucket is tested, not only the extreme ones.
                #
                # Filtering by effect size first and correcting afterwards
                # makes the BH denominator the count of ALREADY-EXTREME
                # buckets (~12) instead of the number of hypotheses actually
                # examined (~600), which is not a correction at all: measured
                # over 30 pure-noise runs it let a false rule through in 67%
                # of them against a 10% target. The selection IS the multiple
                # comparison; it has to be inside the denominator.
                mean_r = sum(values) / len(values)
                rest = _without(all_r, values)
                candidates.append({
                    "condition": name,
                    "bucket": key,
                    "trades": len(values),
                    "mean_r": round(mean_r, 4),
                    "vs_overall_r": round(mean_r - overall, 4),
                    "p_value": welch_t_test(values, rest),
                    "side": "decline" if mean_r <= self.config.decline_below_r
                            else "favor" if mean_r >= self.config.favor_above_r
                            else "neutral",
                })

        # Pass 2: Benjamini-Hochberg over the WHOLE candidate set.
        #
        # Both sides are corrected together because they were found by one
        # scan: separating them would let each side spend the full error
        # budget and quietly double the false-discovery rate. A candidate
        # whose p-value could not be computed does not survive -- an
        # unmeasurable rule is not a rule.
        survivors = benjamini_hochberg(
            [c["p_value"] for c in candidates], self.config.false_discovery_rate)
        for candidate, survived in zip(candidates, survivors):
            candidate["survives_fdr"] = bool(survived)

        # A rule must clear BOTH bars: statistically distinguishable from the
        # rest of the sample AND large enough to be worth acting on. Either
        # alone is insufficient -- significance without effect size is a
        # rule that changes nothing, and effect size without significance is
        # the noise this control exists to reject.
        self.rejected_rules = [
            c for c in candidates
            if c["side"] != "neutral" and not c["survives_fdr"]]
        for candidate in candidates:
            if not candidate["survives_fdr"] or candidate["side"] == "neutral":
                continue
            if candidate["side"] == "decline":
                self.rules.append(candidate)
            else:
                self.favor_rules.append(candidate)

        self.rules.sort(key=lambda r: r["mean_r"])
        self.favor_rules.sort(key=lambda r: -r["mean_r"])
        self.fitted = True
        self.metadata = {
            "version": ABSTENTION_MODEL_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "samples": len(samples),
            "overall_expectancy_r": round(overall, 4),
            "buckets_scanned": scanned,
            "rules_found": len(self.rules),
            "favor_rules_found": len(self.favor_rules),
            "conditions_scanned": len(self.conditions),
            "buckets_tested": len(candidates),
            "candidates_before_fdr": sum(
                1 for c in candidates if c["side"] != "neutral"),
            "rejected_by_fdr": len(self.rejected_rules),
            "false_discovery_rate": self.config.false_discovery_rate,
        }
        return dict(self.metadata)

    def should_decline(self, sample: AbstentionSample) -> Dict[str, Any]:
        """Decline if the trade falls in any rule's bucket, and say which."""
        if not self.fitted:
            return {"decline": False, "reason": "not_fitted"}

        for rule in self.rules:
            if self._bucket_key(sample, rule["condition"]) == rule["bucket"]:
                return {
                    "decline": True,
                    "condition": rule["condition"],
                    "bucket": rule["bucket"],
                    "bucket_mean_r": rule["mean_r"],
                    "bucket_trades": rule["trades"],
                }
        return {"decline": False}

    def matching_favor(self, sample: AbstentionSample) -> Optional[Dict[str, Any]]:
        """The strongest favourable condition this trade falls under, if any."""
        if not self.fitted:
            return None
        for rule in self.favor_rules:
            if self._bucket_key(sample, rule["condition"]) == rule["bucket"]:
                return rule
        return None

    def assess(self, sample: AbstentionSample) -> Dict[str, Any]:
        """
        Full symmetric verdict: decline, favour, or neutral.

        Decline is authoritative -- a condition measured to lose money outranks
        one measured to make it, because the downside is realised and the
        upside is an estimate. `favor` is advisory and intended for ranking
        competing candidates, not for sizing.
        """
        verdict = self.should_decline(sample)
        if verdict.get("decline"):
            verdict["stance"] = "DECLINE"
            return verdict

        favourable = self.matching_favor(sample)
        if favourable:
            return {
                "decline": False,
                "stance": "FAVOR",
                "condition": favourable["condition"],
                "bucket": favourable["bucket"],
                "bucket_mean_r": favourable["mean_r"],
                "bucket_trades": favourable["trades"],
            }
        return {"decline": False, "stance": "NEUTRAL"}

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "version": ABSTENTION_MODEL_VERSION,
                "edges": self.edges,
                "rules": self.rules,
                "favor_rules": self.favor_rules,
                "config": asdict(self.config),
                "metadata": self.metadata,
            }, handle, indent=2)
        return path

    def load(self, path: str) -> "AbstentionRules":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("version") != ABSTENTION_MODEL_VERSION:
            raise ValueError(
                f"Artifact version {payload.get('version')} != "
                f"{ABSTENTION_MODEL_VERSION}. Retrain rather than loading.")
        self.edges = {k: list(v) for k, v in payload["edges"].items()}
        self.rules = list(payload["rules"])
        self.favor_rules = list(payload.get("favor_rules", []))
        self.metadata = payload.get("metadata", {})
        self.fitted = True
        return self


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def abstention_expectancy(
    rules: AbstentionRules,
    samples: Sequence[AbstentionSample],
) -> Dict[str, Any]:
    """
    Mean R taking everything, versus mean R after declining.

    Declined trades contribute 0.0 rather than being dropped from the average.
    Dropping them would flatter the policy by comparing a filtered mean against
    an unfiltered one -- the money not made on a skipped trade is zero, not
    absent.
    """
    if not samples:
        return {"trades": 0, "baseline_r": None, "policy_r": None, "delta_r": None}

    taken, declined = [], 0
    for sample in samples:
        if rules.should_decline(sample).get("decline"):
            taken.append(0.0)
            declined += 1
        else:
            taken.append(sample.realized_r)

    baseline = sum(s.realized_r for s in samples) / len(samples)
    policy = sum(taken) / len(taken)
    return {
        "trades": len(samples),
        "baseline_r": round(baseline, 4),
        "policy_r": round(policy, 4),
        "delta_r": round(policy - baseline, 4),
        "declined": declined,
        "declined_fraction": round(declined / len(samples), 3),
    }


def _shuffled_floor(
    samples: Sequence[AbstentionSample],
    cfg: AbstentionConfig,
    train_size: int,
    conditions: Optional[Sequence[Tuple[str, Tuple[str, ...], str]]] = None,
) -> Dict[str, Any]:
    """
    The identical selection procedure with outcomes shuffled across trades.

    Scanning many buckets for the worst performers is a multiple-comparison
    machine: with enough conditions some will look terrible by luck. Shuffling
    R across trades destroys any real condition-outcome link while preserving
    the bucket structure and the R distribution exactly, so whatever gain the
    procedure still shows is the gain it invents from nothing.
    """
    import random as _random
    rng = _random.Random(cfg.random_seed)

    values = [s.realized_r for s in samples]
    rng.shuffle(values)
    shuffled = [
        AbstentionSample(s.trade_id, s.timestamp, s.conditions, r)
        for s, r in zip(samples, values)
    ]

    train, test = shuffled[:train_size], shuffled[train_size:]
    # The floor must scan the SAME conditions as the real fit. A control that
    # searches a smaller space than the claim it is testing sets the bar too
    # low, and a wider scan would then clear it automatically (standard 15).
    rules = _rules_with(cfg, conditions or CANDIDATE_CONDITIONS)
    try:
        rules.fit(train)
    except ValueError as exc:
        return {"delta_r": None, "error": str(exc)}
    return abstention_expectancy(rules, test)


# ---------------------------------------------------------------------------
# Training with promotion gates
# ---------------------------------------------------------------------------

def _rules_with(config: AbstentionConfig,
                conditions: Sequence[Tuple[str, Tuple[str, ...], str]]
                ) -> "AbstentionRules":
    """An AbstentionRules that scans exactly the conditions it was given."""
    rules = AbstentionRules(config)
    rules.conditions = list(conditions)
    return rules


def train_and_validate(
    trades: Sequence[Mapping[str, Any]],
    config: Optional[AbstentionConfig] = None,
    bridge: Any = None,
) -> Dict[str, Any]:
    """
    Discover decline rules, then decide whether they survive out of sample.

    Promotion requires an expectancy gain on held-out trades that also beats
    what the same procedure extracts from shuffled outcomes.
    """
    cfg = config or AbstentionConfig()
    report: Dict[str, Any] = {
        "version": ABSTENTION_MODEL_VERSION, "promoted": False}

    # Conditions are derived from the FULL decision-time snapshot when
    # auto_conditions is on, instead of the ten hand-listed ones. The BH
    # correction inside AbstentionRules.fit is what makes the wider scan
    # safe; without it, width alone would just manufacture more rules.
    conditions = list(CANDIDATE_CONDITIONS)
    if cfg.auto_conditions:
        derived = auto_conditions_from_trades(
            trades, cfg.max_auto_conditions, bridge)
        existing = {name for name, _, _ in conditions}
        conditions += [c for c in derived if c[0] not in existing]
    report["conditions_scanned"] = len(conditions)

    samples = build_abstention_samples(trades, cfg, bridge, conditions)
    report["samples"] = len(samples)
    if len(samples) < cfg.min_trades:
        report["rejected_because"] = (
            f"{len(samples)} resolved trades < required {cfg.min_trades}")
        return report

    ordered = sorted(samples, key=lambda s: (s.timestamp, s.trade_id))
    cut = max(1, int(len(ordered) * (1.0 - cfg.test_fraction)))
    train, test = ordered[:cut], ordered[cut:]
    report["train_samples"], report["test_samples"] = len(train), len(test)
    if not test:
        report["rejected_because"] = "no trades left to hold out"
        return report

    rules = _rules_with(cfg, conditions)
    try:
        report["fit"] = rules.fit(train)
    except ValueError as exc:
        report["rejected_because"] = str(exc)
        return report

    report["rules"] = rules.rules
    report["favor_rules"] = rules.favor_rules
    report["in_sample"] = abstention_expectancy(rules, train)
    report["expectancy"] = abstention_expectancy(rules, test)

    # Do the favourable conditions hold up out of sample? Reported rather than
    # gated: favour rules do not change what is traded, only how candidates are
    # ranked, so they must not be able to block an otherwise-sound decline set.
    favoured = [s for s in test if rules.matching_favor(s)]
    others = [s for s in test if not rules.matching_favor(s)]
    report["favor_validation"] = {
        "favored_trades": len(favoured),
        "favored_mean_r": round(
            sum(s.realized_r for s in favoured) / len(favoured), 4) if favoured else None,
        "other_trades": len(others),
        "other_mean_r": round(
            sum(s.realized_r for s in others) / len(others), 4) if others else None,
        "holds_out_of_sample": bool(
            favoured and others
            and (sum(s.realized_r for s in favoured) / len(favoured))
            > (sum(s.realized_r for s in others) / len(others))
        ),
    }

    floor = _shuffled_floor(ordered, cfg, cut, conditions)
    report["shuffle_floor"] = {
        "delta_r": floor.get("delta_r"),
        "declined_fraction": floor.get("declined_fraction"),
        "error": floor.get("error"),
    }

    delta = report["expectancy"].get("delta_r")
    declined_fraction = report["expectancy"].get("declined_fraction", 0.0)
    reasons = []

    if not rules.rules:
        reasons.append(
            "no condition showed expectancy below "
            f"{cfg.decline_below_r}R with at least {cfg.min_bucket_trades} trades")

    if delta is None or delta < cfg.min_expectancy_gain_r:
        reasons.append(
            f"out-of-sample expectancy gain {delta}R < required "
            f"{cfg.min_expectancy_gain_r}R")

    if declined_fraction > cfg.max_declined_fraction:
        reasons.append(
            f"declines {declined_fraction:.0%} of trades > "
            f"{cfg.max_declined_fraction:.0%} -- that is not selectivity, "
            "it is not trading")

    # Fail closed, as elsewhere: an uncomputable gate is an unmet gate.
    floor_delta = floor.get("delta_r")
    if floor_delta is None:
        reasons.append(
            "shuffled-outcome floor could not be computed "
            f"({floor.get('error', 'insufficient data')}) -- refusing to "
            "promote without it")
    elif delta is not None and delta - floor_delta < cfg.min_gain_over_shuffle_r:
        reasons.append(
            f"gain {delta}R does not beat the shuffled-outcome floor "
            f"{floor_delta}R by {cfg.min_gain_over_shuffle_r}R -- the same "
            "bucket scan finds this much in randomised outcomes")

    report["promoted"] = not reasons

    # Governance: record EVERY attempt, promote only what cleared the gates.
    #
    # Rejected candidates are registered too. "This configuration was tried on
    # this data and did not beat the noise floor" is the fact that stops it
    # being tried again in three months, and a registry of successes only
    # cannot answer it. Promotion is still decided above; this records.
    #
    # A governance failure must not fail training, but it must not be silent
    # either -- the error is reported in the same report rather than swallowed.
    try:
        from .model_governance import record_training
        report["governance"] = record_training(
            "abstention_model",
            payload={key: value for key, value in report.items()
                     if key not in ("model", "rules_model", "governance")},
            metrics={key: report.get(key) for key in ("gain_r", "rules_found", "samples")
                     if report.get(key) is not None},
            promoted=bool(report["promoted"]),
            notes=report.get("rejected_because") or "passed promotion gates",
        )
    except Exception as exc:
        report["governance"] = {"error": type(exc).__name__ + ": " + str(exc)}
    report["rejected_because"] = "; ".join(reasons) if reasons else None
    report["rules_model"] = rules if report["promoted"] else None
    return report


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------

def get_status(rules: Optional[AbstentionRules] = None) -> Dict[str, Any]:
    cfg = AbstentionConfig()
    return {
        "component": "abstention_model",
        "version": ABSTENTION_MODEL_VERSION,
        "model_loaded": bool(rules and rules.fitted),
        "rules": rules.rules if rules and rules.fitted else [],
        "favor_rules": rules.favor_rules if rules and rules.fitted else [],
        "learns_from_success": True,
        "symmetry": (
            "the bucket scan runs in both directions: conditions measured "
            "below decline_below_r are declined, conditions above "
            "favor_above_r are reported as favourable for candidate ranking"),
        "metadata": rules.metadata if rules else {},
        "form": "univariate bucket rules on pre-entry cost/structure conditions",
        "conditions": [name for name, _, _ in CANDIDATE_CONDITIONS],
        "target": "expectancy in R",
        "predicts_direction": False,
        "is_meta_labeling": False,
        "why_not_meta_labeling": (
            "meta-labeling was tested and refused (AUC 0.5034 vs 0.5092 shuffled "
            "control). This targets expectancy rather than win/loss, uses "
            "pre-entry cost and structure conditions rather than direction "
            "predictors, and produces auditable bucket rules rather than a "
            "fitted per-trade classifier"),
        "promotion_gates": {
            "min_expectancy_gain_r": cfg.min_expectancy_gain_r,
            "min_gain_over_shuffle_r": cfg.min_gain_over_shuffle_r,
            "max_declined_fraction": cfg.max_declined_fraction,
            "min_bucket_trades": cfg.min_bucket_trades,
            "decline_below_r": cfg.decline_below_r,
            "favor_above_r": cfg.favor_above_r,
        },
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Any = None) -> Dict[str, Any]:
    """Prove extraction and report which conditions are actually populated."""
    report: Dict[str, Any] = {
        "component": "abstention_model", "ok": False, "checks": {}}
    try:
        samples = build_abstention_samples(trades or [], AbstentionConfig(), bridge)
        report["checks"]["trades_in"] = len(trades or [])
        report["checks"]["samples_built"] = len(samples)

        if samples:
            coverage = {}
            for name, _, _kind in CANDIDATE_CONDITIONS:
                present = sum(
                    1 for s in samples if s.conditions.get(name) is not None)
                coverage[name] = round(present / len(samples), 3)
            report["checks"]["condition_coverage"] = coverage
            report["checks"]["conditions_populated"] = [
                name for name, share in coverage.items() if share > 0]
            report["checks"]["realized_r_finite"] = all(
                math.isfinite(s.realized_r) for s in samples)
            report["checks"]["mean_r"] = round(
                sum(s.realized_r for s in samples) / len(samples), 4)
            report["ok"] = bool(
                report["checks"]["realized_r_finite"]
                and report["checks"]["conditions_populated"]
            )
        else:
            # Two different states were being collapsed into one here. `ok`
            # was left at its initialised False, which reported a working
            # module as broken whenever the data was merely thin -- and,
            # aggregated into /verify, pinned the whole-layer gate red until
            # people learned to ignore it. Reporting both as "not exercised"
            # would be the opposite error, letting a broken decode path pass
            # unnoticed. So they are separated: input nothing can read is a
            # FAILURE, valid input with nothing eligible is NOT EXERCISED.
            from .price_evolution_bridge import count_usable_trades
            usable = count_usable_trades(trades or [])
            report["checks"]["usable_trades"] = usable
            if trades and usable == 0:
                report["ok"] = False
                report["reason"] = ("no supplied trade could be decoded; the "
                                    "data path, not the model, is the problem")
            else:
                report["ok"] = None
                report["reason"] = "no abstention samples could be built from the supplied trades"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


__all__ = [
    "ABSTENTION_MODEL_VERSION", "CANDIDATE_CONDITIONS", "AbstentionConfig",
    "AbstentionSample", "AbstentionRules", "build_abstention_samples",
    "quantile_edges", "bucket_of", "abstention_expectancy",
    "train_and_validate", "get_status", "self_check",
]
