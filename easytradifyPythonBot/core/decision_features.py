"""
CANONICAL DECISION FLATTENER
============================
FILE: core/decision_features.py

One definition of "what a decision looks like as a flat dict", shared
by the replay recorder and the live pipeline.

WHY THIS IS ITS OWN MODULE

The Stage 7 meta-label model is TRAINED on replay records and SERVED on
live analyses. If the two paths flatten the same decision differently
-- one reading `entry_analysis.timing_confidence`, the other reading
`entry.timing_conf`, or the two disagreeing about whether a missing
field is None or 0 -- the model learns one thing and is asked another.
That failure is silent by construction: the features still have the
right names and the right shapes, every log line looks healthy, and
the predictions are just wrong.

Train/serve skew has no error message, so the only real defence is
having one function. This is that function. core/engine_replay.py's
_capture() delegates here, and the live pipeline calls it directly.

It is a pure projection of an analysis result: no market access, no
clock, no side effects.
"""

from typing import Any, Dict


def _g(d: Dict[str, Any], *path, default=None):
    """Nested lookup that never raises on a missing branch."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


# Probability-chain contributions, as (feature key, block field). Each
# lives in result["final_verdict"][f"{key}_final_score"].
_CONTRIBUTION_FIELDS = (
    ("pattern", "pattern_contribution"),
    ("gnn", "gnn_contribution"),
    ("smc", "smc_contribution"),
    ("fvg_ifvg", "fvg_ifvg_contribution"),
    ("order_flow", "order_flow_contribution"),
    ("trend_cascade", "adjustment"),
    ("adr_exhaustion", "adjustment"),
    ("rvam", "adjustment"),
    ("nested_zone", "adjustment"),
    ("dxy_confluence", "adjustment"),
)


def _component_verdicts(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Every component's own verdict, flat, for outcome attribution.

    Two sources, because the pipeline has two shapes:

      result["components"]   the top-level analysis blocks (trend,
                             supply_demand, support_resistance,
                             ict_concepts, candlestick, wyckoff), each a
                             single verdict.

      result["indicators"]   NOT a verdict -- a CONTAINER of individual
                             indicators (rsi, macd, bollinger,
                             stochastic, volume, round_numbers, ...),
                             each carrying its own recommendation and
                             score.

    Reading the container as though it were a verdict is why
    "indicators" scored on zero decisions in the first attribution run:
    `result["indicators"].get("recommendation")` is None, so every
    decision was skipped and the single largest group of signals in the
    system went unmeasured. Each sub-indicator is lifted out under an
    `ind:` prefix so it is attributed on its own.
    """
    out: Dict[str, Any] = {}

    for name, blk in (result.get("components") or {}).items():
        if isinstance(blk, dict):
            out[name] = {"recommendation": blk.get("recommendation"),
                         "score": blk.get("score")}

    from core.analysis_groups import block as _group_block
    for name, blk in (_group_block(result, "indicators") or {}).items():
        # Only sub-blocks that actually state a view. Others in this
        # container (ema levels, debug payloads) have no verdict to score.
        if isinstance(blk, dict) and blk.get("recommendation") is not None:
            out[f"ind:{name}"] = {"recommendation": blk.get("recommendation"),
                                  "score": blk.get("score")}

    return out


def flatten_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten one analyze_institutional_signal() result.

    Deliberately wide. A field that is never read costs a few bytes; a
    field that was not captured cannot be investigated after the run,
    and re-running a multi-hour replay to recover one number is how
    analysis stalls.
    """
    fv = result.get("final_verdict") or {}
    entry = result.get("entry_analysis") or {}
    vet = result.get("vetos") or {}
    anti = result.get("global_anticheat") or {}
    ledger = fv.get("probability_ledger") or []

    contributions: Dict[str, Any] = {}
    for key, field in _CONTRIBUTION_FIELDS:
        block = fv.get(f"{key}_final_score") or {}
        if block:
            contributions[key] = block.get(field)
            contributions[f"{key}_aligned"] = block.get("aligned")

    return {
        # decision
        "probability": fv.get("probability_percent"),
        "direction": _g(result, "final_verdict", "best_direction"),
        "buy_probability": _g(result, "final_verdict", "probability_buy"),
        "sell_probability": _g(result, "final_verdict", "probability_sell"),
        "simple_action": entry.get("simple_action"),
        "execution": entry.get("execution"),
        "entry_status": entry.get("entry_status"),
        "should_enter": entry.get("should_enter"),
        # The entry engine's own verdict before the veto or R:R floor
        # could overturn it -- see asset_analysis where it is set.
        "engine_qualified": entry.get("engine_qualified"),
        "star_rating": entry.get("star_rating"),
        # gates
        "veto_triggered": vet.get("triggered"),
        "veto_reason": vet.get("reason"),
        "veto_checks": vet.get("checks") or {},
        "signal_count": _g(entry, "golden_signals", "signal_count"),
        "timing_confidence": entry.get("timing_confidence"),
        "timing_ready": entry.get("timing_ready"),
        # No default. Defaulting a missing diagnostic to False is what
        # made the XAGUSD audit report "timing bypassed on 11 decisions"
        # when the real figure was 942 -- the engine's early returns
        # omitted the key and this invented a reassuring answer. None
        # means "not reported", which is a question, not an all-clear.
        "timing_bypassed_replay": entry.get("timing_bypassed_replay"),
        "micro_structure_available": entry.get("micro_structure_available"),
        # Which confirmation tier fired, and how strong it claimed to be.
        # Captured because the tiers are wildly unequal in practice and
        # nothing recorded which one actually decided a trade: on a
        # 4240-decision EURUSD replay, 49 of 52 confirmed entries came
        # from the weakest tier (score 60, "the candle closed in my
        # direction" -- roughly a coin flip on M1), while the three
        # structural tiers fired 3 times between them. Without this
        # field that had to be reconstructed from the bars afterwards.
        "confirmation_type": _g(entry, "confirmation", "type"),
        "confirmation_score": _g(entry, "confirmation", "score"),
        "confirmation_is_confirmed": _g(entry, "confirmation", "is_confirmed"),
        "discount_quality": _g(entry, "discount", "discount_quality"),
        "discount_at_zone": _g(entry, "discount", "is_already_at_discount"),
        "zone_type": _g(entry, "discount", "zone_type"),
        "zone_expected_direction": _g(entry, "discount", "expected_direction"),
        "zone_grade": _g(entry, "discount", "zone_grade"),
        # risk
        "rr_ratio": _g(result, "entry_details", "risk_reward_detail", "ratio"),
        "rr_valid": _g(result, "entry_details", "risk_reward_detail", "valid"),
        "sl_pips": _g(result, "entry_details", "stop_loss_pips"),
        "tp_pips": _g(result, "entry_details", "take_profit_pips"),
        "lot_size": _g(result, "entry_details", "lot_size"),
        # probability mechanics
        "absorbed_total": _g(fv, "probability_absorbed_by_bounds", "total_absorbed"),
        "clamped_steps": _g(fv, "probability_absorbed_by_bounds", "clamped_step_count"),
        "ledger_reconciles": fv.get("probability_ledger_reconciles"),
        "ledger_len": len(ledger),
        "ledger": ledger,
        "contributions": contributions,
        # Each analysis component's own verdict (trend, supply_demand,
        # support_resistance, ict_concepts, candlestick, wyckoff,
        # indicators). Captured so component_attribution() can score
        # every one of them against outcomes -- previously these were
        # local variables in asset_analysis and no report could see them.
        "components": _component_verdicts(result),
        # cross-checks
        "conviction_score": _g(result, "conviction", "conviction_score"),
        "conviction_passed": _g(result, "conviction", "passed"),
        "conviction_hard_fails": _g(result, "conviction", "hard_fails") or [],
        "coherence_ok": _g(result, "coherence", "coherent"),
        "coherence_violations": len(_g(result, "coherence", "violations") or []),
        "gnn_conflict": bool(_g(result, "gnn", "conflict", "conflict")),
        "liquidity_aligned": _g(result, "liquidity_events", "aligned_with_direction"),
        "smc_recommendation": _g(result, "smc", "analysis", "recommendation"),
        "premium_position_pct": _g(result, "smc", "analysis",
                                   "premium_discount", "position_pct"),
        # defensive core (stages 9/7/8), present once those have run
        "symbolic_passed": _g(result, "symbolic_gate", "passed"),
        "symbolic_blocked_by": _g(result, "symbolic_gate", "blocked_by"),
        "meta_label_probability": _g(result, "meta_label", "win_probability"),
        "meta_label_passed": _g(result, "meta_label", "passed"),
        "conformal_decision": _g(result, "conformal", "decision"),
        "conformal_error_rate": _g(result, "conformal", "error_rate"),
        # context
        "atr_pips": anti.get("atr_pips"),
        "spread_pips": anti.get("spread_pips"),
        "volume_ratio": anti.get("volume_ratio"),
        "candle_progress": anti.get("candle_progress_percent"),
        "adx": _g(result, "indicators", "trend", "adx", "adx_14"),
        "regime": _g(result, "volatility_protection", "trading_regime", "state"),
        "market_regime": fv.get("market_regime"),
        "h1_trend": _g(result, "higher_timeframe", "trend"),
        "session_open": _g(result, "session_analysis", "is_market_open"),
        # Inputs to the three vetoes commented out in veto_engine.py
        # (V3 against_trend, V4 against_ema, V5 h1_conflict). They were
        # disabled by hand with no measurement attached, and without
        # these fields captured there is no way to ask the shadow
        # universe whether re-enabling any of them would help or hurt.
        # V5's factor (h1_opposition) has already been measured and
        # FAILED the invariance splits -- it stays off on evidence.
        # V3 and V4 remain unmeasurable until these land in a run.
        # Captured from vetos.checks, where they are ALREADY computed,
        # rather than rebuilt here from trend/ema_200/price. A second
        # implementation of a condition is a second thing to drift.
        "veto_against_trend": _g(result, "vetos", "checks", "against_trend"),
        "veto_against_ema": _g(result, "vetos", "checks", "against_ema"),
        "veto_h1_conflict": _g(result, "vetos", "checks", "h1_conflict"),
        "trend": _g(result, "indicators", "trend", "trend"),
        # Accepted by calculate_real_probability() and never read there.
        # Captured so the invariance splits can decide whether wiring it
        # in is justified, rather than taste deciding.
        "ema_gap_pips": _g(result, "indicators", "trend", "ema_gap_pips"),
    }
