# ============================================================
# PRICE EVOLUTION BRIDGE -- the one decode boundary for the AI layer
# ============================================================
# FILE: ai/price_evolution_bridge.py
#
# How a stored trade becomes something a model can read, for the snapshot
# analyze_institutional_signal() produces today (see ai/price_evolution_maps.py):
#
#   to_canonical        stored document -> decoded trade: the analysis_at_open /
#                       analysis_at_close envelopes flattened, every
#                       price_evolution point's blob decoded.
#   to_snapshots        the T0..TC sequence (decision, then each point), outcome
#                       fields withheld.
#   to_outcome          labels from the close side only.
#   to_decision_record  kwargs for non_rl_intelligence.DecisionRecord; component
#                       scores are the strategy-group scores the decision used.
#   feature_coverage    which sections and strategy groups produced features, and
#                       whether the maps placed every path of the open snapshot.
#   extract_learning_data   the forward walk: how probability, groups, readings,
#                       vetoes, behaviour and the market stop moved during the trade.
#
# HOW THE MONITOR STORES A TRADE (monitor/trade_persistence.py -> trade_sink ->
# core/mongo/trades_service.py, collection `trades`, trade_id "trade_<ticket>"):
#   analysis_at_open    {"m1_analysis_raw": <snapshot, raw>, "m1_audit": ...,
#                        microstructure_at_entry, strategy_family_scores,
#                        component_reads, trailing_stop, emoji summary}
#   price_evolution[]   $push per update: price, profit_usd, profit_percent,
#                        spread, risk_state, microstructure, and
#                        "analysis": {"m1": encoder.encode(snapshot, compact=True)}
#   analysis_at_close   {"m1_analysis_raw": <snapshot, raw>, result, profit, summary}
# ============================================================

from typing import Dict, Any, List, Mapping, Optional, Sequence, Tuple
from collections import defaultdict
import math

from .price_evolution_decoder import PriceEvolutionDecoder
from .price_evolution_encoder import PriceEvolutionEncoder
from .price_evolution_maps import MISSING, EvolutionMaps


def _num(value: Any) -> Optional[float]:
    """Coerce to float, tolerating the '72.5%' strings the analysis layer emits."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


# Lists are expanded item-by-item up to this many. Raised from 8 because a
# probability_ledger routinely carries a dozen-plus adjustment steps and the
# tail steps are not noise -- they are the ones that pushed the decision over
# the threshold. Aggregates (count/sum/mean/min/max) always cover the whole
# list regardless, so nothing beyond the cap disappears without trace.
MAX_LIST_ITEMS = 32

# Strings longer than this are truncated rather than dropped, and always keep
# a companion `.len` feature. Dropping them outright lost the fact that the
# field existed at all.
MAX_STRING_LEN = 200


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """
    Flatten arbitrary nested analysis into dotted scalar keys.

    Lists are expanded, not counted. An earlier version collapsed every list
    to `<name>.count`, which silently discarded the highest-value evidence in
    the payload -- probability_ledger (every probability adjustment step),
    smc.reasons, the pattern list, liquidity_events -- since all of those are
    arrays. A list now yields its length, numeric aggregates, and the first
    MAX_LIST_ITEMS elements expanded individually.

    Deliberately schema-free: it walks whatever is present rather than
    enumerating known components, so a newly added analysis subsystem is
    picked up automatically instead of silently missing until someone
    remembers to update a hardcoded list.
    """
    flat: Dict[str, Any] = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(value, name))

    elif isinstance(obj, (list, tuple)):
        flat[f"{prefix}.count"] = len(obj)
        numbers = [v for v in obj if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numbers:
            flat[f"{prefix}.sum"] = float(sum(numbers))
            flat[f"{prefix}.mean"] = float(sum(numbers)) / len(numbers)
            flat[f"{prefix}.min"] = float(min(numbers))
            flat[f"{prefix}.max"] = float(max(numbers))
        for index, item in enumerate(obj[:MAX_LIST_ITEMS]):
            flat.update(_flatten(item, f"{prefix}.{index}"))

    elif prefix:
        flat[prefix] = obj

    return flat


class PriceEvolutionBridge:
    """
    COMPLETE bridge that extracts EVERY learning signal from compressed data.
    ALL fields extracted including GNN, patterns, indicators, and OHLC+GNN combined.
    """
    
    def __init__(self):
        self.decoder = PriceEvolutionDecoder()
        self.encoder = PriceEvolutionEncoder()
        self.maps = EvolutionMaps()

    def bridge_asset_to_system(self, symbol: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Round-trip a full asset-analysis payload through the price-evolution stack."""
        encoded = self.encoder.encode(analysis)
        decoded = self.decoder.decode(encoded)
        return {
            "symbol": symbol,
            "encoded": encoded,
            "decoded": decoded,
            "learning_data": self.extract_learning_data([encoded]),
            "coverage_report": self.encoder.get_field_coverage(analysis),
        }
    
    # ============================================================
    # CANONICAL FORM - the decode boundary for every AI consumer
    # ============================================================

    def to_canonical(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Firebase trade document -> fully decoded canonical form.

        Every AI consumer (adversarial, RL, non-RL, root-cause) must read
        trades THROUGH this method. Reasoning directly off the stored
        document is wrong, because price_evolution[].analysis is written in
        TWO different shapes and neither is the analysis shape those
        consumers expect:

          _encoded True   point["analysis"] = {"m1": <short-key blob>, "m5": ..., "h1": ...}
          _encoded False  point["m1_analysis_raw"] / ["m5_analysis_raw"] / ["h1_analysis_raw"]
                          at the TOP level of the point, with no "analysis" key at all

        Which shape a row has depends on whether `ai.price_evolution_encoder`
        was importable when it was written -- monitor/firebase_helpers.py
        falls back to the raw branch when _get_encoder() returns None. The
        ai package was unimportable for a period (empty ai_config.py broke
        ai/__init__.py), so older rows are raw and newer rows are encoded.
        Consumers must never assume one format.

        Note the raw branch stores only _audit_slice() of m5/h1, so those
        rows carry less analysis than encoded rows do. That asymmetry is
        historical and cannot be recovered here.

        ✅ FIXED: this used to say "analysis_at_open / analysis_at_close are
        NOT touched: firebase_service writes those raw already." That is true
        of the synchronous write and FALSE of the trade as it finally exists.

        api/execute_copy_trade.py opens a trade, writes analysis_at_open = {}
        on the fast path, and then a background thread calls
        _save_analysis_snapshot_to_firebase(stage="open"), which OVERWRITES
        the field with a snapshot ENVELOPE:

            analysis_at_open = {"timestamp": ..., "symbol": ..., "result": ...,
                                "m1_analysis_raw": <the real analysis>,
                                "m5_analysis_raw": ..., "h1_analysis_raw": ...}

        firebase_service.save_trade_open wraps differently again, under
        "full_raw_analysis". Neither is the flat analysis shape every consumer
        here reads, so on a live-recorded trade `analysis["final_verdict"]`,
        `analysis["best_direction"]` and the probability ledger are all
        absent -- not empty, absent -- and every component measurement built
        on them silently reads nothing.

        That mattered enormously the moment it was checked: the entire
        component analysis in this package depends on final_verdict.
        probability_ledger and best_direction, and a live capture run would
        have produced trades none of it could read, while looking fine.

        Unwrapped here, at the one boundary every consumer already goes
        through, rather than in each reader. The envelope's own keys are
        retained underneath so nothing is lost; the inner analysis wins on
        conflict, because those are the analysis's real values.
        """
        if not isinstance(trade, dict):
            return {}

        canonical = dict(trade)
        for field in ("analysis_at_open", "analysis_at_close"):
            if field in canonical:
                canonical[field] = self._canonical_analysis(canonical[field])

        points = trade.get("price_evolution")
        if not isinstance(points, list):
            return canonical

        canonical["price_evolution"] = [self._canonical_point(p) for p in points]
        return canonical

    # The wrappers a stored analysis can arrive inside, most specific first.
    # `m1_analysis_raw` is the live snapshot envelope; `full_raw_analysis` is
    # firebase_service._extract_analysis_data's wrapper.
    ANALYSIS_ENVELOPE_KEYS = ("m1_analysis_raw", "full_raw_analysis")

    def _canonical_analysis(self, block: Any) -> Dict[str, Any]:
        """
        Flatten a stored analysis envelope to the shape consumers read.

        Idempotent without needing a marker key: the flattened result still
        carries its envelope keys (m5/h1 raw are real data and are kept), so a
        second pass merges the SAME inner dict over the same result and
        changes nothing.

        A block that was never wrapped is returned byte-identical --
        deliberately not stamped with a marker. An analysis that arrives flat
        is already canonical, and adding a key to it would make this method
        edit payloads it has no business editing; three existing tests assert
        exactly that and they are right to.
        """
        if not isinstance(block, dict) or not block:
            return block if isinstance(block, dict) else {}

        for key in self.ANALYSIS_ENVELOPE_KEYS:
            inner = block.get(key)
            if isinstance(inner, dict) and inner:
                merged = dict(block)
                # Inner wins: "timestamp"/"symbol" on the envelope describe
                # when the snapshot was WRITTEN, the analysis's own fields
                # describe what it computed.
                merged.update(inner)
                merged["_analysis_envelope"] = key
                return merged

        return dict(block)

    def _canonical_point(self, point: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize one price_evolution point to {"analysis": {m1, m5, h1}} decoded."""
        if not isinstance(point, dict):
            return point

        # Idempotent: a canonical point has no _encoded flag, so re-running
        # would fall through to the raw branch, find no *_analysis_raw keys
        # and blank the analysis it already decoded.
        if point.get("_canonical"):
            return dict(point)

        result = dict(point)
        analysis = point.get("analysis")

        # ✅ FIXED: the encoded branch tested `analysis["_encoded"]`, but the
        # writer puts `_encoded` on the POINT, beside `analysis`, not inside
        # it -- monitor/firebase_helpers.py builds
        #     {"analysis": {"m1": <blob>}, "_encoded": True, "_tf_included": [...]}
        # so the test failed, control fell to the raw branch, that branch found
        # no `m1_analysis_raw` at the point level, and every point decoded to
        # {"m1": {}, "m5": {}, "h1": {}}.
        #
        # Silent and total: the AI layer received a well-formed price point
        # with an EMPTY analysis on every row, which reads as "this trade had
        # no analysis" rather than "the decoder looked in the wrong place".
        # Every model that walks price_evolution was training on nothing.
        #
        # Both placements are accepted now, and a blob is decoded whenever it
        # looks like one, so neither writer shape can be missed again.
        encoded = bool(point.get("_encoded")
                       or (isinstance(analysis, dict) and analysis.get("_encoded")))

        if isinstance(analysis, dict) and (encoded or self._looks_encoded(analysis)):
            result["analysis"] = {
                tf: self._decode_safe(analysis.get(tf))
                for tf in ("m1", "m5", "h1")
            }
        elif isinstance(analysis, dict) and analysis:
            # Already-decoded analyses pass through untouched.
            result["analysis"] = {tf: analysis.get(tf) or {}
                                  for tf in ("m1", "m5", "h1")}
        else:
            result["analysis"] = {
                tf: point.get(f"{tf}_analysis_raw") or {}
                for tf in ("m1", "m5", "h1")
            }

        result["_canonical"] = True
        return result

    @staticmethod
    def _looks_encoded(analysis: Dict[str, Any]) -> bool:
        """
        Whether a timeframe payload is an encoder blob rather than an analysis.

        Structural, not flag-based, so a writer that forgets to stamp
        `_encoded` still decodes correctly. An encoded blob carries the
        encoder's own markers (`analysis_schema`, the compressed payload, or
        the short-key scheme); a raw analysis carries `final_verdict`.
        """
        for value in analysis.values():
            if not isinstance(value, dict):
                continue
            if ("full_analysis_z" in value or "full_analysis" in value
                    or value.get("analysis_schema") == "asset_analysis"):
                return True
        return False

    def _decode_safe(self, blob: Any) -> Dict[str, Any]:
        """Decode one encoded timeframe blob; a bad row must not kill a whole run."""
        if not isinstance(blob, dict) or not blob:
            return {}
        try:
            return self.decoder.decode(blob)
        except Exception:
            return {}

    # ============================================================
    # WHOLE-TRADE LIFECYCLE VIEWS
    # ============================================================
    # A stored trade has three lifecycle sections and they are NOT
    # interchangeable as model input:
    #
    #   analysis_at_open + entry   what was known at T0  -> FEATURES
    #   price_evolution[]          the market's response -> forward walk
    #   close_data + analysis_at_close   how it ended    -> LABELS ONLY
    #
    # Feeding close-side data in as features is the leakage failure both
    # specs call non-negotiable, and non_rl_intelligence.sanitize_observation
    # already drops any key containing "analysis_at_close" for exactly that
    # reason. These accessors keep the split explicit so a consumer cannot
    # collapse it by accident.
    # ============================================================

    # Only genuinely future/outcome-derived fields. Deliberately precise
    # substrings, not broad ones: an earlier version skipped anything
    # containing "profit", which also threw away take_profit /
    # TAKE_PROFIT_1..3 -- target levels chosen at T0 and among the most
    # informative features available.
    _OUTCOME_TOKENS = (
        "profit_usd", "profit_percent", "max_profit", "max_drawdown",
        "is_winning", "realized_return", "close_data", "analysis_at_close",
        "closed_at", "close_price", "close_reason", "duration_seconds",
        "exit_spread", "exit_slippage", "pnl", "mfe", "mae",
        "future", "outcome",
    )

    def to_snapshots(self, trade: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Ordered T0..TC snapshot sequence for the RL entry-timing agent.

        Index 0 is the opening decision (analysis_at_open + entry), then one
        snapshot per price_evolution point. Outcome-derived fields are left
        out entirely: the RL CounterfactualSimulator derives return itself by
        walking extract_price() across the sequence, so carrying profit_usd
        here would hand it the answer instead of making it earn it.
        """
        trade = self.to_canonical(trade)
        entry = trade.get("entry") or {}
        direction = trade.get("direction") or "BUY"

        opening = {
            "timestamp": trade.get("opened_at"),
            "price": _num(entry.get("price")),
            "direction": direction,
            "entry_price": _num(entry.get("price")),
            "stop_loss": _num(entry.get("stop_loss")),
            "take_profit": _num(entry.get("take_profit")),
        }
        # Whole entry block, not selected keys: volume, margin, risk_usd,
        # risk_percent, spread_at_entry, probability_of_hit, R:R, magic.
        opening.update(self._features(entry, "entry"))
        opening.update(self._features(trade.get("analysis_at_open") or {}, "open"))
        snapshots = [opening]

        for point in trade.get("price_evolution") or []:
            if not isinstance(point, dict):
                continue
            snap = {
                "timestamp": point.get("timestamp"),
                "price": _num(point.get("price")),
                "direction": direction,
                "entry_price": _num(entry.get("price")),
                "stop_loss": _num(entry.get("stop_loss")),
                "take_profit": _num(entry.get("take_profit")),
                "distance_from_entry_pips": _num(point.get("distance_from_entry_pips")),
            }
            snap.update(self._features(entry, "entry"))

            # Everything else on the point except the analysis blobs handled
            # below: the volume block (tick_volume, avg_volume, volume_ratio,
            # volume_spike, volume_trend), live spread, trailing-stop state,
            # audit schema. Previously discarded -- that volume block is the
            # market-participation read at each step of the trade.
            rest = {k: v for k, v in point.items() if k != "analysis"}
            snap.update(self._features(rest, "point"))

            for tf, analysis in (point.get("analysis") or {}).items():
                snap.update(self._features(analysis, tf))
            snapshots.append(snap)

        return snapshots

    def to_outcome(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Label dict built from the close side, keyed to match OutcomeLabel.

        MFE/MAE are recomputed from the price_evolution profit_percent series
        rather than read from trade["metrics"], because metrics is maintained
        incrementally on every write and only ever moves in one direction --
        the series is the primary record.
        """
        trade = self.to_canonical(trade)
        close = trade.get("close_data") or {}
        reason = str(close.get("close_reason") or "").upper()

        returns = [
            _num(p.get("profit_percent"))
            for p in (trade.get("price_evolution") or [])
            if isinstance(p, dict) and p.get("profit_percent") is not None
        ]
        returns = [r for r in returns if r is not None]

        metrics = trade.get("metrics") or {}
        mfe = max(returns) if returns else _num(metrics.get("max_profit_percent"))
        mae = min(returns) if returns else _num(metrics.get("max_drawdown_percent"))

        realized = _num(close.get("profit_percent"))
        is_winning = close.get("is_winning")
        if is_winning is None and realized is not None:
            is_winning = realized > 0

        tp_hit = 1 if "TP" in reason or "TAKE_PROFIT" in reason else 0
        sl_hit = 1 if "SL" in reason or "STOP" in reason else 0
        duration = _num(close.get("duration_seconds"))

        return {
            "success": int(bool(is_winning)) if is_winning is not None else None,
            "realized_return": realized,
            "mfe": mfe,
            "mae": mae,
            "tp_hit": tp_hit,
            "sl_hit": sl_hit,
            "time_to_tp": duration if tp_hit else None,
            "time_to_sl": duration if sl_hit else None,
            "failure_class": reason or None,
            "source": "firebase_trade",
        }

    def to_decision_record(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trade document -> kwargs for non_rl_intelligence.DecisionRecord.

        Returned as a plain dict rather than a DecisionRecord so this module
        does not import non_rl_intelligence (the dependency runs the other
        way). Build with DecisionRecord(**bridge.to_decision_record(trade)).
        """
        trade = self.to_canonical(trade)
        analysis = trade.get("analysis_at_open") or {}

        observation = dict(self._features(analysis, "open"))
        observation.update(self._features(trade.get("entry") or {}, "entry"))
        observation.update(self._features(trade.get("metrics") or {}, "metrics"))
        for key in ("symbol", "direction", "timeframe", "magic"):
            if trade.get(key) is not None:
                observation[f"trade.{key}"] = trade[key]
        observation["timestamp"] = trade.get("opened_at")

        # The strategy-group scores the decision was made from. Only groups that
        # scored: an unscored group has no score, and inventing 50 for it would
        # claim a neutral reading nobody measured. (This read
        # analysis["components"], a section deleted on 2026-09-15, so every
        # live trade reached the models with no component scores at all.)
        component_scores = {}
        groups = (analysis.get("strategy_groups") or {}).get("groups") or {}
        for name, group in groups.items():
            if isinstance(group, dict) and group.get("scored"):
                score = _num(group.get("score"))
                if score is not None:
                    component_scores[str(name)] = score

        return {
            "decision_id": str(trade.get("trade_id") or trade.get("ticket") or ""),
            "timestamp": trade.get("opened_at") or "",
            "observation": observation,
            "outcome": self.to_outcome(trade),
            "component_scores": component_scores,
            "metadata": {
                "symbol": trade.get("symbol"),
                "direction": trade.get("direction"),
                "ticket": trade.get("ticket"),
                "evolution_points": len(trade.get("price_evolution") or []),
            },
        }

    def _features(self, analysis: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        """
        Flatten one analysis blob into scalar features.

        Exhaustive by design: every section of analyze_institutional_signal()
        output is walked -- indicators, SMC, supply/demand, support/resistance,
        volume profile, wave lattice, patterns, VWAP, RVAM, liquidity events,
        order flow, family vote, TTM squeeze, trend cascade, nested zone,
        GNN, vetoes, session/news, account_info (leverage, balance, equity),
        config, probability ledger. Nothing is enumerated by name, so a
        component added to the analysis payload later shows up here without
        this file changing.

        Only future/outcome-derived fields are withheld, because using those
        as features is leakage rather than information.
        """
        if not isinstance(analysis, dict):
            return {}

        flat = {}
        for key, value in _flatten(analysis).items():
            low = key.lower()
            if any(token in low for token in self._OUTCOME_TOKENS):
                continue

            if isinstance(value, str) and len(value) > MAX_STRING_LEN:
                # Truncate, never discard: a prose blob still carries the
                # signal that the field was populated and how long it was.
                flat[f"{prefix}.{key}"] = value[:MAX_STRING_LEN]
                flat[f"{prefix}.{key}.len"] = float(len(value))
                continue

            if value is None:
                flat[f"{prefix}.{key}.is_null"] = True
                continue

            if isinstance(value, (int, float, str, bool)):
                flat[f"{prefix}.{key}"] = value
        return flat

    def feature_coverage(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Which analysis sections actually produced features, and which did not.

        The point of this is falsifiability: "the AI sees everything" is a
        claim, and this is how you check it per trade rather than trusting it.
        Anything listed under `empty_sections` is present in the stored
        analysis but contributed nothing -- either genuinely blank upstream,
        or withheld as outcome data.
        """
        trade = self.to_canonical(trade)
        analysis = trade.get("analysis_at_open") or {}
        features = self._features(analysis, "open")

        produced, empty = {}, []
        for section in analysis.keys():
            # Match nested sections AND scalar top-level keys: a scalar emits
            # "open.<section>" with no trailing dot, so a prefix-only test
            # reported real features as missing.
            exact = f"open.{section}"
            count = sum(
                1 for k in features
                if k == exact or k.startswith(f"{exact}.")
            )
            if count:
                produced[str(section)] = count
            else:
                empty.append(str(section))

        # The grouped snapshot keeps every detector under `analysis`, so a
        # section-level count would call the whole engine one section. Each
        # group is reported on its own.
        groups_with, groups_empty = {}, []
        for group in (analysis.get("analysis") or {}):
            prefix = f"open.analysis.{group}."
            count = sum(1 for k in features if k.startswith(prefix))
            if count:
                groups_with[str(group)] = count
            else:
                groups_empty.append(str(group))

        snapshot = {k: v for k, v in analysis.items() if k not in self.ENVELOPE_EXTRAS}
        schema = self.maps.coverage(snapshot) if snapshot else {}

        return {
            "total_features": len(features),
            "sections_with_features": produced,
            "empty_sections": sorted(empty),
            "analysis_groups_with_features": groups_with,
            "empty_analysis_groups": sorted(groups_empty),
            "schema": {
                "version": self.maps.SCHEMA_VERSION,
                "layout": schema.get("layout"),
                "matches": schema.get("matches"),
                "unmapped_paths": (schema.get("unmapped") or [])[:50],
                "removed_sections_present": schema.get("removed_sections_present") or [],
            },
            "evolution_points": len(trade.get("price_evolution") or []),
        }

    # Keys the monitor writes AROUND the snapshot in analysis_at_open /
    # analysis_at_close (monitor/trade_persistence.py). They survive
    # canonicalisation beside the snapshot's own keys and are not part of it.
    ENVELOPE_EXTRAS = ("m1_analysis_raw", "m1_audit", "_encoded", "_audit_schema", "_engine",
                       "trailing_stop", "microstructure_at_entry", "microstructure_bias",
                       "strategy_family_scores", "component_reads", "_analysis_envelope",
                       "symbol", "order_type", "profit_usd", "profit_percent", "result",
                       "📈 RISK_REWARD", "full_raw_analysis")

    # ============================================================
    # LEARNING DATA -- how the snapshot evolved across a trade
    # ============================================================
    # The forward walk, not decision-time features: these summaries describe
    # what the analysis did WHILE the trade was open (the probability sliding,
    # the winning group changing, a veto starting to fire, the market stop
    # moving), which is exactly what an exit or "the setup reversed mid-trade"
    # study needs and exactly what must never be fed back as an entry feature.
    #
    # Rebuilt 2026-09-17 for the grouped snapshot. The previous 34 extractors
    # read short codes of sections that no longer exist (gnn/ohlc_gnn,
    # pattern_analysis, indicator_scores, components) and returned zeros and
    # empty lists on every live point.

    def extract_learning_data(self, points: Sequence[Any]) -> Dict[str, Any]:
        """
        Every learning signal the current snapshot carries, over a point sequence.

        Accepts stored price_evolution points ({"analysis": {"m1": <blob>}, price,
        profit_usd, ...}), canonical points, encoded blobs, or decoded snapshots.
        """
        views = [self._point_view(p) for p in points or []]
        views = [(a, m) for a, m in views if a or m]
        if not views:
            return {}
        snaps = [a for a, _ in views]
        markets = [m for _, m in views]
        stamps = [m.get("timestamp") or a.get("timestamp") or a.get("encoded_at") for a, m in views]

        return {
            "schema": self._schema_report(snaps),
            "probability": {
                name: self._series(snaps, path) for name, path in (
                    ("probability_percent", "final_verdict.probability_percent"),
                    ("probability_post_chain", "final_verdict.probability_percent_post_chain"),
                    ("probability_buy", "final_verdict.probability_buy"),
                    ("probability_sell", "final_verdict.probability_sell"),
                    ("strategy_final_probability", "strategy_groups.final_probability"),
                    ("other_side_probability", "strategy_groups.other_side.final_probability"),
                    ("calibrated_probability", "strategy_groups.calibrated.probability"),
                    ("calibrated_p_up", "strategy_groups.calibrated.p_up"))},
            "confidence": {
                "confidence": self._series(snaps, "⭐ CONFIDENCE"),
                "confidence_post_chain": self._series(snaps, "⭐ CONFIDENCE_POST_CHAIN"),
            },
            "decision_changes": {
                name: self._changes(snaps, path, stamps) for name, path in (
                    ("final_decision", "🎯 FINAL_DECISION"), ("simple_action", "🚀 SIMPLE_ACTION"),
                    ("action", "final_verdict.action"), ("execution", "final_verdict.execution"),
                    ("entry_status", "entry_analysis.entry_status"))},
            "direction": {
                "changes": {name: self._changes(snaps, path, stamps) for name, path in (
                    ("best_direction", "final_verdict.best_direction"),
                    ("analysis_direction", "direction_decision.analysis_direction"),
                    ("traded_direction", "direction_decision.traded_direction"),
                    ("cascade_direction", "direction_decision.cascade_direction"),
                    ("calibrated_preferred", "strategy_groups.calibrated.preferred_direction"))},
                "cascade_score": self._series(snaps, "direction_decision.cascade_score"),
                "flipped_by_trend_cascade": self._share(snaps, "direction_decision.flipped_by_trend_cascade"),
                "chosen_direction_vetoed": self._share(snaps, "final_verdict.directional_vetoes.chosen_direction_was_vetoed"),
                "both_directions_vetoed": self._share(snaps, "final_verdict.directional_vetoes.both_directions_vetoed"),
            },
            "strategy_groups": {
                "groups": {group: {
                    "score": self._series(snaps, f"strategy_groups.groups.{group}.score"),
                    "agreement": self._series(snaps, f"strategy_groups.groups.{group}.agreement"),
                    "scored": self._share(snaps, f"strategy_groups.groups.{group}.scored"),
                    "calibrated_p_up": self._series(snaps, f"strategy_groups.calibrated.groups.{group}.p_up"),
                } for group in self.maps.STRATEGY_GROUPS},
                "winner_changes": self._changes(snaps, "strategy_groups.winner", stamps),
                "most_opposed_changes": self._changes(snaps, "strategy_groups.most_opposed", stamps),
                "contested": self._share(snaps, "strategy_groups.contested"),
                "best_score": self._series(snaps, "strategy_groups.best_score"),
                "opposition": self._series(snaps, "strategy_groups.opposition"),
                "groups_agreeing": self._series(snaps, "strategy_groups.groups_agreeing"),
                "groups_scored": self._series(snaps, "strategy_groups.groups_scored"),
                "context_total": self._series(snaps, "strategy_groups.context_total"),
                "cost_r": self._series(snaps, "strategy_groups.cost.cost_r"),
            },
            "state_readings": {reading: {
                "side_changes": self._changes(snaps, f"state_readings.groups.{group}.{reading}.side", stamps),
                "value": self._series(snaps, f"state_readings.groups.{group}.{reading}.value"),
                "present": self._share_present(snaps, f"state_readings.groups.{group}.{reading}.side"),
            } for reading, group in self.maps.STATE_READINGS.items()},
            "vetos": {
                "triggered": self._share(snaps, "vetos.triggered"),
                "reasons": self._counts(snaps, "vetos.reason"),
                "checks": {check: self._share(snaps, f"vetos.checks.{check}")
                           for check in self.maps.VETO_CHECKS},
            },
            "entry": {
                "should_enter": self._share(snaps, "entry_analysis.should_enter"),
                "engine_qualified": self._share(snaps, "entry_analysis.engine_qualified"),
                "timing_ready": self._share(snaps, "entry_analysis.timing_ready"),
                "timing_confidence": self._series(snaps, "entry_analysis.timing_confidence"),
                "star_rating": self._series(snaps, "entry_analysis.star_rating"),
                "entry_quality_changes": self._changes(snaps, "entry_analysis.entry_quality", stamps),
                "strategy_changes": self._changes(snaps, "entry_analysis.strategy.name", stamps),
                "golden_signal_count": self._series(snaps, "entry_analysis.golden_signals.signal_count"),
            },
            "final_scores": {block: {
                "final_score": self._series(snaps, f"final_verdict.{block}.final_score"),
                "aligned": self._share(snaps, f"final_verdict.{block}.aligned"),
                "adjustment": self._series(snaps, f"final_verdict.{block}.adjustment"),
            } for block in self.maps.FINAL_SCORE_BLOCKS},
            "ledger": {
                "steps": self._series_values([self._len(s, "final_verdict.probability_ledger") for s in snaps]),
                "total_absorbed": self._series(snaps, "final_verdict.probability_absorbed_by_bounds.total_absorbed"),
                "reconciles": self._share(snaps, "final_verdict.probability_ledger_reconciles"),
            },
            "behaviour": {
                **{flag: self._share(snaps, f"entry_details.behaviour.{flag}") for flag in (
                    "extended", "stalled", "reversion_ready", "momentum_running", "slow")},
                "velocity_atr": self._series(snaps, "entry_details.behaviour.velocity_atr"),
                "extension_atr": self._series(snaps, "entry_details.behaviour.extension_atr"),
                "volatility_transition_changes": self._changes(
                    snaps, "entry_details.behaviour.volatility_transition", stamps),
            },
            "ou_reversion": {
                "tradeable": self._share(snaps, "entry_details.ou_reversion.tradeable"),
                "z": self._series(snaps, "entry_details.ou_reversion.z"),
                "net_edge_sigma": self._series(snaps, "entry_details.ou_reversion.net_edge_sigma"),
            },
            "market_stop": {
                "affordable": self._share(snaps, "entry_details.market_stop.affordable"),
                "stop_pips": self._series(snaps, "entry_details.market_stop.stop_pips"),
                "target_r": self._series(snaps, "entry_details.market_stop.target_r"),
            },
            "risk": {name: self._series(snaps, path) for name, path in (
                ("lot_size", "entry_details.lot_size"), ("risk_usd", "entry_details.risk_usd"),
                ("reward_usd", "entry_details.reward_usd"),
                ("risk_reward", "entry_details.risk_reward_detail.ratio"),
                ("stop_loss_pips", "entry_details.stop_loss_pips"),
                ("take_profit_pips", "entry_details.take_profit_pips"),
                ("spread_pips", "entry_details.spread_pips"))},
            "regime_changes": self._changes(snaps, "final_verdict.market_regime", stamps),
            "position_management": {
                "should_close": self._share(snaps, "position_management.should_close"),
                "close_reasons": self._counts(snaps, "position_management.close_reason"),
            },
            "analysis_groups": {group: {
                "scored": self._share(snaps, f"analysis.{group}.scored"),
                "direction_changes": self._changes(snaps, f"analysis.{group}.direction", stamps),
            } for group in self.maps.STRATEGY_GROUPS},
            "market": {name: self._series_values([_num(m.get(name)) for m in markets])
                       for name in ("price", "profit_usd", "profit_percent", "spread",
                                    "distance_from_entry_pips")},
        }

    # ------------------------------------------------------------------ point views
    def _point_view(self, point: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """(snapshot, point-level market fields) for one learning point."""
        if not isinstance(point, Mapping):
            return {}, {}
        analysis = point.get("analysis")
        if isinstance(analysis, Mapping) and any(tf in analysis for tf in ("m1", "m5", "h1")):
            canonical = self._canonical_point(dict(point))
            snapshot = (canonical.get("analysis") or {}).get("m1") or {}
            market = {k: v for k, v in point.items()
                      if k != "analysis" and not str(k).startswith("_")
                      and not str(k).endswith("_analysis_raw")}
            return (snapshot if isinstance(snapshot, dict) else {}), market
        if point.get("analysis_schema") == self.maps.SCHEMA_NAME:
            market = {"price": point.get("p"), "profit_usd": point.get("pf"),
                      "profit_pips": point.get("pp"), "timestamp": point.get("t")}
            return self._decode_safe(dict(point)), {k: v for k, v in market.items() if v is not None}
        return dict(point), {}

    def _schema_report(self, snaps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Whether the maps placed every path of every snapshot in the walk."""
        layouts: Dict[str, int] = defaultdict(int)
        unmapped: set = set()
        removed: set = set()
        for snap in snaps:
            if not snap:
                continue
            cov = self.maps.coverage(snap)
            layouts[str(cov["layout"])] += 1
            unmapped.update(cov["unmapped"])
            removed.update(cov["removed_sections_present"])
        return {"schema_version": self.maps.SCHEMA_VERSION, "points": len(snaps),
                "layouts": dict(layouts), "unmapped_paths": sorted(unmapped)[:50],
                "unmapped_count": len(unmapped), "removed_sections_present": sorted(removed),
                "matches": not unmapped and not removed}

    # ------------------------------------------------------------------ primitives
    def _value(self, snap: Mapping[str, Any], dotted: str) -> Any:
        """Value at a dotted snapshot path (no current key contains a dot), None when absent."""
        found = self.maps.get_path(snap, tuple(dotted.split(".")))
        return None if found is MISSING else found

    def _series(self, snaps: Sequence[Mapping[str, Any]], dotted: str) -> Dict[str, Any]:
        return self._series_values([_num(self._value(s, dotted)) for s in snaps])

    @staticmethod
    def _series_values(values: Sequence[Optional[float]]) -> Dict[str, Any]:
        """Trajectory summary of the numeric values; None entries are gaps, not zeros."""
        numbers = [v for v in values if v is not None and math.isfinite(v)]
        if not numbers:
            return {"count": 0}
        drop_from, drop_to, drop, drop_index = None, None, 0.0, None
        rise = 0.0
        for i in range(1, len(numbers)):
            delta = numbers[i] - numbers[i - 1]
            if -delta > drop:
                drop, drop_index, drop_from, drop_to = -delta, i, numbers[i - 1], numbers[i]
            rise = max(rise, delta)
        return {
            "count": len(numbers), "first": numbers[0], "last": numbers[-1],
            "min": min(numbers), "max": max(numbers),
            "mean": sum(numbers) / len(numbers), "change": numbers[-1] - numbers[0],
            "biggest_drop": {"drop": drop, "index": drop_index, "from": drop_from, "to": drop_to},
            "biggest_rise": rise,
        }

    def _changes(self, snaps: Sequence[Mapping[str, Any]], dotted: str,
                 stamps: Sequence[Any]) -> List[Dict[str, Any]]:
        """Every point where the value differs from the previous point that had one."""
        out: List[Dict[str, Any]] = []
        previous = MISSING
        for i, snap in enumerate(snaps):
            value = self._value(snap, dotted) if snap else None
            if value is None and not snap:
                continue
            if previous is not MISSING and value != previous:
                out.append({"index": i, "timestamp": stamps[i] if i < len(stamps) else None,
                            "from": previous, "to": value})
            previous = value
        return out

    def _share(self, snaps: Sequence[Mapping[str, Any]], dotted: str) -> Dict[str, Any]:
        values = [self._value(s, dotted) for s in snaps if s]
        flags = [v for v in values if isinstance(v, bool)]
        if not flags:
            return {"count": 0}
        return {"count": len(flags), "true": sum(flags), "share": sum(flags) / len(flags),
                "first": flags[0], "last": flags[-1]}

    def _share_present(self, snaps: Sequence[Mapping[str, Any]], dotted: str) -> float:
        present = [s for s in snaps if s]
        if not present:
            return 0.0
        return sum(1 for s in present if self._value(s, dotted) is not None) / len(present)

    def _counts(self, snaps: Sequence[Mapping[str, Any]], dotted: str) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for snap in snaps:
            value = self._value(snap, dotted) if snap else None
            if value is not None:
                counts[str(value)[:MAX_STRING_LEN]] += 1
        return dict(counts)

    def _len(self, snap: Mapping[str, Any], dotted: str) -> Optional[float]:
        value = self._value(snap, dotted) if snap else None
        return float(len(value)) if isinstance(value, list) else None


# ---------------------------------------------------------------------------
# Shared usability probe
# ---------------------------------------------------------------------------

def canonical_analysis(block: Any) -> Dict[str, Any]:
    """
    An `analysis_at_open` / `analysis_at_close` block in the shape readers expect.

    Module-level so that any consumer holding a RAW stored trade can flatten
    the envelope without constructing a bridge or knowing the storage layout.

    This exists because three modules read `trade["analysis_at_open"]`
    directly -- ai_asset_diagnostic, component_validation and
    root_cause_analyzers -- and the live writer stores an ENVELOPE there:

        {"timestamp": ..., "m1_analysis_raw": <the real analysis>, ...}

    Reading that raw yields a dict with no `final_verdict`, no
    `probability_ledger` and no `best_direction`. Nothing raises; the consumer
    simply extracts nothing and reports that the trade had no analysis. That
    is the failure mode this whole package keeps re-learning: the data is
    present, the reader looks one level too high, and the result is silence
    rather than an error.

    Idempotent -- an already-flat analysis is returned unchanged.
    """
    return PriceEvolutionBridge()._canonical_analysis(block)


def count_usable_trades(trades: Any, bridge: Any = None) -> int:
    """
    How many supplied trades the decode path can actually read.

    This exists to separate two states that every model's self_check was
    collapsing into one. "No samples were built" can mean the input was
    unusable -- a broken or empty data path, which SHOULD fail a verification
    gate -- or that the input was fine and simply contained nothing eligible
    (no trade reached the profit threshold an extension decision needs), which
    should not. Reporting both as failure pinned the whole-layer gate red on
    thin data; reporting both as "not exercised" would let a broken data path
    pass unnoticed. Neither is acceptable, so they are distinguished here once
    rather than reimplemented in each model (standard 10).

    A trade counts as usable when it canonicalises and carries an entry price.
    """
    if bridge is None:
        bridge = PriceEvolutionBridge()
    usable = 0
    for trade in trades or []:
        if not isinstance(trade, Mapping):
            continue
        try:
            canonical = bridge.to_canonical(dict(trade))
        except Exception:
            continue
        if not isinstance(canonical, dict):
            continue
        entry = canonical.get("entry") or {}
        if _num(entry.get("price")) is not None:
            usable += 1
    return usable


# ---------------------------------------------------------------------------
# Decision-time context features
# ---------------------------------------------------------------------------

# A categorical value becomes an indicator column. Cardinality is capped so a
# free-text field cannot silently produce thousands of columns and turn every
# model into a lookup table keyed by a string nobody meant as a feature.
MAX_CATEGORY_COLUMNS = 4


def context_features(trade: Mapping[str, Any], bridge: Any = None,
                     prefix: str = "ctx") -> Dict[str, float]:
    """
    Every decision-time analysis value, as numeric features.

    WHY: exit_model and target_model were deciding from 11 price-path features
    and nothing else -- no SMC, no volume profile, no indicators, no session,
    no leverage -- while the bridge was already extracting 125 features per
    trade that no model consumed. abstention_model looked at 10 hand-listed
    conditions out of the same payload. The evidence existed; the models were
    not reading it.

    LEAKAGE: sourced from analysis_at_open and entry ONLY. close_data,
    analysis_at_close and price_evolution are never touched, so nothing here
    can know the outcome. That boundary is the whole reason this reads through
    to_canonical() rather than the raw document.

    Booleans become 0/1, numbers pass through, and a categorical becomes
    `<key>=<value>` indicators. Non-finite values are dropped rather than
    coerced: a NaN that silently becomes 0.0 is a measurement claiming the
    value was zero.
    """
    if bridge is None:
        bridge = PriceEvolutionBridge()
    try:
        canonical = bridge.to_canonical(dict(trade))
    except Exception:
        return {}

    source = {
        "open": canonical.get("analysis_at_open") or {},
        "entry": canonical.get("entry") or {},
    }
    flat = _flatten(source)

    features: Dict[str, float] = {}
    categories: Dict[str, List[str]] = {}

    for key, value in flat.items():
        name = f"{prefix}.{key}"
        if isinstance(value, bool):
            features[name] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                features[name] = number
        elif isinstance(value, str) and value:
            categories.setdefault(name, []).append(value)

    # Indicator columns, ordered deterministically so the feature vector is
    # reproducible across runs and machines.
    for name, values in sorted(categories.items()):
        for value in sorted(set(values))[:MAX_CATEGORY_COLUMNS]:
            token = "".join(c if c.isalnum() else "_" for c in str(value))[:32]
            features[f"{name}={token}"] = 1.0

    return features


def context_feature_union(trades: Sequence[Mapping[str, Any]],
                          bridge: Any = None) -> List[str]:
    """
    The stable, sorted feature names across a set of trades.

    Models need one fixed column order. Building it from the union rather than
    from the first trade matters because indicator columns are sparse: a trade
    in the LONDON session produces no ASIA column at all, and a per-trade
    ordering would silently shift every column's meaning between rows.
    """
    if bridge is None:
        bridge = PriceEvolutionBridge()
    names: set = set()
    for trade in trades or []:
        names.update(context_features(trade, bridge).keys())
    return sorted(names)


def context_vector(trade: Mapping[str, Any], names: Sequence[str],
                   bridge: Any = None) -> List[float]:
    """One trade as a row in the fixed column order. Absent means 0.0."""
    values = context_features(trade, bridge)
    return [float(values.get(name, 0.0)) for name in names]


# ---------------------------------------------------------------------------
# Verification surface
# ---------------------------------------------------------------------------
#
# Standard 12, and overdue. This module is standard 1 -- "one decode boundary,
# never reason off stored form" -- so it is the single point every model's view
# of a trade passes through, and it was the one module in the AI layer with no
# get_status and no self_check. /verify has been printing "price_evolution: NO
# self_check" for as long as that endpoint has existed.
#
# The checks below are the failures this module has actually had: fabricated
# fields stamped onto payloads that claimed none of them, and two incompatible
# stored shapes where only one was handled.

def get_status(bridge: Optional["PriceEvolutionBridge"] = None) -> Dict[str, Any]:
    """What the decode boundary guarantees."""
    return {
        "component": "price_evolution_bridge",
        "role": "the single decode boundary (standard 1)",
        "snapshot_schema": {"name": EvolutionMaps.SCHEMA_NAME, "version": EvolutionMaps.SCHEMA_VERSION,
                            "fields": len(EvolutionMaps.FIELDS),
                            "compact_fields": len(EvolutionMaps.COMPACT_CODES),
                            "strategy_groups": list(EvolutionMaps.STRATEGY_GROUPS)},
        "storage_formats_handled": ["_encoded: True", "_encoded: False (*_analysis_raw)"],
        "idempotent": True,
        "fabricates_fields": False,
        "context_features_sources": ["analysis_at_open", "entry"],
        "never_reads": ["close_data", "analysis_at_close", "price_evolution"],
        "max_list_items": MAX_LIST_ITEMS,
        "max_category_columns": MAX_CATEGORY_COLUMNS,
    }


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               bridge: Optional["PriceEvolutionBridge"] = None) -> Dict[str, Any]:
    """
    Prove decoding is faithful, idempotent, and invents nothing.

    `invents_no_fields` is the load-bearing one. The encoder used to stamp
    success=False, model_version="v4.0.1" and an encode-time timestamp onto
    payloads that asserted none of them, and every consumer downstream
    believed all three. Nothing raised; the values were simply wrong, and they
    were wrong in a direction that looked like data.
    """
    report: Dict[str, Any] = {
        "component": "price_evolution_bridge", "ok": False, "checks": {}}
    try:
        checks = report["checks"]
        bridge = bridge or PriceEvolutionBridge()

        # A trade carrying neither shape must decode to something usable
        # rather than raising or inventing.
        bare = bridge.to_canonical({"trade_id": "bare", "entry": {"price": 1.0}})
        checks["bare_trade_decodes"] = isinstance(bare, dict)
        checks["invents_no_fields"] = not any(
            key in (bare.get("close_data") or {})
            for key in ("success", "model_version", "ts"))

        # Garbage in must not become a confident empty result.
        checks["garbage_is_not_usable"] = count_usable_trades([{"junk": 1}]) == 0

        trades = list(trades or [])
        checks["trades_in"] = len(trades)
        if not trades:
            report["ok"] = None
            report["reason"] = "no trades supplied; decoding not exercised"
            return report

        canonical = bridge.to_canonical(dict(trades[0]))
        checks["canonical_has_entry"] = bool(canonical.get("entry"))
        checks["canonical_has_open_analysis"] = bool(
            canonical.get("analysis_at_open"))

        # Idempotence: decoding an already-decoded trade must not change it.
        again = bridge.to_canonical(dict(canonical))
        checks["decode_is_idempotent"] = (
            (again.get("entry") or {}).get("price")
            == (canonical.get("entry") or {}).get("price")
            and len(again.get("price_evolution") or [])
            == len(canonical.get("price_evolution") or []))

        checks["usable_trades"] = count_usable_trades(trades)
        checks["all_supplied_trades_usable"] = (
            checks["usable_trades"] == len(trades))

        coverage = bridge.feature_coverage(dict(trades[0]))
        checks["feature_coverage_reports_sections"] = bool(
            coverage.get("sections_with_features"))
        checks["no_empty_sections_hidden"] = "empty_sections" in coverage
        # Reported, not required: a trade recorded before the grouping (or a
        # synthetic fixture) legitimately carries paths the current maps do
        # not place. On a live trade a non-zero count means the engine has
        # drifted from ai/price_evolution_maps.py.
        schema = coverage.get("schema") or {}
        checks["open_snapshot_layout"] = schema.get("layout")
        checks["open_snapshot_matches_maps"] = schema.get("matches")
        checks["open_snapshot_unmapped_paths"] = len(schema.get("unmapped_paths") or [])

        # The leakage boundary on context features, asserted rather than
        # assumed: every column must come from open analysis or entry.
        features = context_features(dict(trades[0]), bridge)
        checks["context_features"] = len(features)
        checks["context_features_are_decision_time"] = all(
            name.startswith("ctx.open.") or name.startswith("ctx.entry.")
            for name in features)

        required = ("bare_trade_decodes", "invents_no_fields",
                    "garbage_is_not_usable", "canonical_has_entry",
                    "decode_is_idempotent",
                    "context_features_are_decision_time")
        report["ok"] = all(bool(checks.get(key)) for key in required)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    return report
