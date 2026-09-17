# ============================================================
# ELITE DECISION SNAPSHOT LAYER
# ============================================================
# FILE: core/decision_snapshot.py
#
# Wraps the existing asset_analysis.py output (the full JSON you already
# generate per signal) into ONE self-contained, replayable object, per the
# "elite rule-based system" spec: gates-with-margin, 3D regime, bull/bear
# duality, scenario tree, sensitivity/counterfactual, and a natural-language
# explain() that reconstructs the whole decision from the snapshot alone.
#
# ------------------------------------------------------------------------
# READ THIS FIRST — why `outcome` exists and why it's not optional
# ------------------------------------------------------------------------
# Everything below makes a decision more LEGIBLE. None of it makes a
# decision more CORRECT. A richer description of one hand of poker teaches
# you to narrate poker, not to play it -- narration only becomes learning
# once you can compare it against how hundreds of similar hands resolved.
# There is no amount of forensic detail on a SINGLE decision that manufactures
# information about whether it worked. That information only exists once
# price has moved forward and you check.
#
# So this schema carries one field, `outcome`, that starts as None. It is
# NOT a logging pipeline, a database, or a background service — it's one
# key on the same dict you already return. Call attach_outcome() once,
# later, when you know what happened. Skipping it doesn't remove the
# requirement to eventually validate these rules against reality; it just
# means the snapshot can explain what the rules SAID forever, but never
# learn what actually WORKS. Keep the field even if you never fill it yet.
# ============================================================

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import copy


# ============================================================
# 1. GATES WITH MARGIN
# ============================================================
# vetos.checks in the existing output is booleans only ("choppy_market":
# true). Elite means: how close, not just pass/fail. "ADX 19.1, needed 25,
# missed by 5.9" is a different piece of information than "choppy: true" --
# near-miss distance tells you whether the regime is borderline or nowhere
# close, which the raw boolean throws away.

def _gate(name: str, passed: bool, value: float, threshold: float,
          direction: str, unit: str = "", enforced: bool = True) -> Dict[str, Any]:
    """
    direction: 'above' means the gate wants value >= threshold to pass,
               'below' means the gate wants value <= threshold to pass.
    margin is always signed distance-to-pass: positive means comfortably
    passed by that much, negative means failed by that much.
    """
    if direction == "above":
        margin = value - threshold
    else:
        margin = threshold - value
    # ✅ NEW: self-consistency guard.
    #
    # `passed` comes from the veto system; `margin` is recomputed here from
    # value vs threshold. If the threshold quoted here isn't the one the
    # veto actually used, the two disagree -- a PASSING gate with a
    # NEGATIVE margin, or a failing gate with a positive one. That is
    # exactly what a mismatched threshold looks like from the outside, and
    # this codebase has now produced it three separate times:
    #
    #   extreme_volatility  classification 45.0 quoted against a veto at 70.0
    #   extreme_volatility  default 70.0 quoted against XAGUSD's actual 80.0
    #   choppy_market       flat 25 quoted against XAGUSD's actual 22
    #
    # Each was found by reading a payload and noticing the sign by eye.
    # This makes the condition self-reporting: any future threshold that
    # drifts away from the check it describes shows up as
    # threshold_mismatch=True on the gate itself, without anyone having to
    # spot it. It never changes pass/fail -- it only flags that the two
    # numbers can't both be right.
    # A gate whose veto is switched off decides nothing, so its quoted
    # threshold cannot disagree with it.
    threshold_mismatch = enforced and ((passed and margin < 0) or ((not passed) and margin > 0))

    return {
        "gate": name,
        "passed": passed,
        "value": round(value, 4),
        "threshold": round(threshold, 4),
        "margin": round(margin, 4),
        "unit": unit,
        "near_miss": (not passed) and abs(margin) <= (threshold * 0.15 if threshold else 0),
        "threshold_mismatch": threshold_mismatch,
        # ✅ False for checks that are reported but whose veto-engine
        # implementation is disabled -- a FAIL on one of these did not and
        # could not stop the trade. See vetos.advisory_only.
        "enforced": enforced,
    }


def build_gates_with_margin(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Reconstructs margin for every gate the veto system checks, using fields
    already present in the existing output (vetos.checks, config, and the
    raw values that fed them). Where the raw value isn't in the output
    (e.g. exact H1-conflict angle), the gate is still included as
    pass/fail-only with margin=None rather than guessed.
    """
    cfg = result.get("config", {})
    checks = result.get("vetos", {}).get("checks", {})
    trend = result.get("trend_confirmation", {})
    global_ac = result.get("global_anticheat", {})
    vol_prot = result.get("volatility_protection", {})
    directional = result.get("directional_analysis", {})

    # ✅ FIXED: this was referenced by BOTH the choppy_market gate and the
    # extreme_volatility gate below, but the definition never made it into
    # the file -- an edit that added the two usages landed while the edit
    # adding the definition did not. Every call raised NameError and the
    # entire snapshot came back {"available": false, "reason": "error:
    # name '_eff' is not defined"}. Caught on the first payload after
    # deploy. Defined here with the other top-of-function lookups so it
    # precedes every use.
    #
    # The veto engine applies PER-INSTRUMENT threshold overrides (XAGUSD:
    # ADX 22 not 25, ATR 80.0 not 70.0); prefer what it actually used over
    # the flat system-wide constants, falling back to those for payloads
    # that predate the effective_thresholds block.
    _eff = (result.get("vetos", {}) or {}).get("effective_thresholds", {}) or {}

    gates = []

    adx = trend.get("m1_adx", 0)
    # ✅ FIXED: quoted the flat RANGING_MARKET_ADX_THRESHOLD (25) while the
    # veto that sets checks["choppy_market"] is instrument-aware -- XAGUSD
    # vetoes below 22, XAUUSD below 20. For ADX in [22, 25) this gate
    # reported FAIL with a negative margin while no veto had fired.
    adx_threshold = _eff.get("adx_threshold") or cfg.get("ranging_market_adx_threshold", 25)
    # The veto's mode decides what the ADX gate means: "block" wants ADX above
    # the threshold, "invert" wants it below, "off" enforces nothing.
    choppy_mode = str(_eff.get("choppy_market_mode") or "block").lower()
    gates.append(_gate(
        "choppy_market (ADX trend strength)",
        not checks.get("choppy_market", True),
        adx, adx_threshold, direction="below" if choppy_mode == "invert" else "above", unit="ADX",
        enforced=choppy_mode != "off",
    ))

    atr = vol_prot.get("atr_pips", 0)
    # ✅ FIXED: `extreme_threshold_pips` used to carry the per-symbol
    # CLASSIFICATION threshold while `checks["extreme_volatility"]` is
    # decided by the VETO threshold. Quoting one against the other's
    # pass/fail produced passing gates with negative margins. Prefer the
    # veto threshold explicitly; the old key now holds it too, and the 40
    # default is kept only for payloads that predate this.
    # ✅ FIXED AGAIN: EXTREME_VOLATILITY_VETO_THRESHOLD (70.0) was closer
    # than the old classification threshold (45.0) but still not the number
    # that decides this gate -- VetoEngine overrides it per instrument, and
    # XAGUSD vetoes above 80.0. ATR in (70, 80] would still render FAIL with
    # a negative margin while the veto stayed silent. Prefer the engine's
    # own effective value.
    extreme_thr = _eff.get("volatility_threshold_pips") or vol_prot.get(
        "veto_threshold_pips", vol_prot.get("extreme_threshold_pips", 40)
    )
    gates.append(_gate(
        "extreme_volatility",
        not checks.get("extreme_volatility", False),
        atr, extreme_thr, direction="below", unit="pips ATR"
    ))

    vol_ratio = global_ac.get("volume_ratio", 0)
    gates.append({
        "gate": "low_volume",
        "passed": not checks.get("low_volume", False),
        "value": vol_ratio,
        "threshold": None,  # VOLUME_LOW_THRESHOLD_M1 not in output payload
        "margin": None,
        "unit": "ratio",
        "near_miss": None,
        "note": "threshold constant lives in config module, not in this payload",
    })

    spread = global_ac.get("spread_pips", 0)
    max_spread = global_ac.get("max_allowed_spread", 0)
    # passed is the spread fact the veto evaluates (spread_valid), not
    # checks.high_spread: that flag reads False whenever an earlier veto
    # short-circuited check_all_vetos before V9 ran, which reported a 2.7-pip
    # spread against a 2.5 ceiling as "passed" and fired gate_threshold_mismatch
    # on ~1.5% of study bars.
    spread_valid = global_ac.get("spread_valid")
    gates.append(_gate(
        "high_spread",
        bool(spread_valid) if isinstance(spread_valid, bool) else not checks.get("high_spread", False),
        spread, max_spread, direction="below", unit="pips"
    ))

    # Booleans with no numeric distance available in the payload as-is —
    # still surfaced, honestly marked as pass/fail-only.
    #
    # Some of these are advisory: reported, but with no live veto behind
    # them. The producing side names them so this doesn't have to guess.
    _advisory = set((result.get("vetos", {}) or {}).get("advisory_only", []) or [])
    for key, label in [
        ("against_trend", "against_trend"),
        ("against_ema", "against_ema"),
        ("h1_conflict", "h1_conflict"),
        ("rsi_divergence_opposing", "rsi_divergence_opposing"),
        ("wick_reversal", "wick_reversal"),
        ("candle_too_young", "candle_too_young"),
        ("session_veto", "session_veto"),
        ("news_veto", "news_veto"),
    ]:
        gates.append({
            "gate": label,
            "passed": not checks.get(key, False),
            "value": None, "threshold": None, "margin": None,
            "unit": None, "near_miss": None,
            "threshold_mismatch": False,
            # ✅ NEW: against_trend / against_ema / h1_conflict are computed
            # and rendered here as gates, but their VetoEngine
            # implementations are commented out -- a FAIL on one of them did
            # not stop the trade and could not have. Without this flag the
            # gate list reads as though every entry is load-bearing.
            "enforced": key not in _advisory,
        })

    # FIXED (defect D-20): this read the RAW directional probability, not
    # the value the entry gate actually tested. The gate is applied to
    # best_probability after the whole confluence chain; buy/sell_
    # probability is what calculate_probability_* produced before any of it.
    #
    # Live proof, XAGUSD 2026-09-01 15:49: this gate reported
    # "value=95.0 threshold=75 (margin +20.00 %)" while the ledger showed
    # ENTRY_DECISION at 87.0. Same payload, two numbers, and the reported
    # margin was 8 points too generous.
    prob = _scenario_probability(result)
    prob_threshold = cfg.get("min_probability_for_entry", _DEFAULT_ENTRY_THRESHOLD)
    gates.append(_gate(
        "probability_threshold",
        prob >= prob_threshold,
        prob, prob_threshold, direction="above", unit="%"
    ))

    return gates


# ============================================================
# 2. 3D REGIME CLASSIFICATION
# ============================================================
# trend-strength (ADX) x volatility (ATR position within its own normal
# band) x liquidity/session (spread + session state), fused into ONE label
# instead of three independently-gated flags.

def classify_regime_3d(result: Dict[str, Any]) -> Dict[str, Any]:
    trend = result.get("trend_confirmation", {})
    vol_prot = result.get("volatility_protection", {})
    session = result.get("session_analysis", {})
    global_ac = result.get("global_anticheat", {})
    cfg = result.get("config", {})

    # --- trend strength axis ---
    adx = trend.get("m1_adx", 0)
    adx_threshold = cfg.get("ranging_market_adx_threshold", 25)
    trend_axis = "TRENDING" if adx >= adx_threshold else "RANGING"

    # --- volatility axis, expressed as position in its own normal band ---
    # ✅ FIXED: this used to be the only option -- approximating "percentile
    # of self" from the static per-symbol min/max/extreme table, since no
    # real rolling ATR history was available at snapshot-build time. Now
    # that asset_analysis.py wires calculate_atr_long()'s previously-
    # discarded true-range history into volatility_protection.
    # atr_percentile_band, this uses the REAL percentile when present.
    # Falls back to the old static-table approximation for any snapshot
    # built before this fix (e.g. re-processing an older saved JSON) --
    # shape of the output is unchanged either way, exactly as promised.
    atr = vol_prot.get("atr_pips", 0)
    percentile_band = vol_prot.get("atr_percentile_band")
    if percentile_band and percentile_band.get("adaptive"):
        vmin = percentile_band.get("low", 0)
        vmax = percentile_band.get("high", 1)
        vol_band_source = f"real {percentile_band.get('reason', 'percentile')}"
    else:
        vmin = vol_prot.get("normal_range_min_pips", 0)
        vmax = vol_prot.get("normal_range_max_pips", 1)
        vol_band_source = "static per-symbol table (no ATR history available yet)"
    vextreme = vol_prot.get("extreme_threshold_pips", vmax * 2 if vmax else 1)
    if vmax > vmin:
        vol_position = (atr - vmin) / (vmax - vmin)
    else:
        vol_position = 0.5
    if atr >= vextreme:
        vol_axis = "EXTREME"
    elif vol_position > 1.0:
        vol_axis = "HIGH"
    elif vol_position < 0.0:
        vol_axis = "LOW"
    else:
        vol_axis = "NORMAL"

    # --- liquidity / session axis ---
    spread = global_ac.get("spread_pips", 0)
    max_spread = global_ac.get("max_allowed_spread", 1)
    spread_headroom = 1 - (spread / max_spread) if max_spread else 0
    is_open = session.get("is_market_open", True)
    if not is_open:
        liquidity_axis = "CLOSED"
    elif spread_headroom < 0.2:
        liquidity_axis = "THIN"
    else:
        liquidity_axis = "NORMAL"

    return {
        "trend_strength": trend_axis,
        "trend_strength_adx": adx,
        "volatility": vol_axis,
        "volatility_position_in_band": round(vol_position, 2),
        "volatility_band_source": vol_band_source,
        "liquidity": liquidity_axis,
        "spread_headroom_pct": round(spread_headroom * 100, 1),
        "combined_label": f"{trend_axis}+{vol_axis}_VOL+{liquidity_axis}_LIQ",
        "note": (
            "volatility axis now uses a real rolling ATR percentile "
            "(atr_percentile_band) when the payload includes it; falls "
            "back to the static per-symbol normal-range table only for "
            "older snapshots that predate this fix. See "
            "volatility_band_source above for which one this snapshot used."
        ),
    }


# ============================================================
# 3. BULL CASE / BEAR CASE (forced dual reasoning)
# ============================================================
# Not just "here's the dissent buried in breakdown" -- both sides get their
# own confidence, their own supporting indicators, and their own explicit
# invalidation trigger.

# Indicators do not all report confidence the same way. Most carry an
# explicit `confidence` (0-100), but support_resistance, wyckoff,
# ict_concepts and volume carry only an unsigned `score` and no confidence
# key at all. Reading .get("confidence", 0) on those yields 0, which is not
# "no conviction" -- it is "this field doesn't exist here".
#
# 95 matches get_sr_recommendation's 0-85 and wyckoff's 0-95 ranges, and is
# so indicators on different native scales report comparable strengths.
_UNSIGNED_SCORE_SCALE = 95.0

from core.asset_analysis_config import TRADE_PROBABILITY_MINIMUM as _DEFAULT_ENTRY_THRESHOLD  # noqa: E402


def _indicator_confidence(ind: Dict[str, Any]) -> float:
    """
    Confidence for an indicator, 0-100, falling back to |score| for the
    indicators that don't publish a confidence key.
    """
    confidence = ind.get("confidence")
    if confidence is not None:
        try:
            return max(0.0, min(100.0, float(confidence)))
        except (TypeError, ValueError):
            return 0.0

    score = ind.get("score")
    if score is not None:
        try:
            return max(0.0, min(100.0, abs(float(score)) / _UNSIGNED_SCORE_SCALE * 100.0))
        except (TypeError, ValueError):
            return 0.0

    return 0.0


def build_bull_bear_case(result: Dict[str, Any]) -> Dict[str, Any]:
    # ✅ FIXED (again): was result["indicators"]["unified_score"]["breakdown"].
    # unified_score itself was later removed entirely from asset_analysis.py's
    # output (it never actually drove best_probability/the real trade
    # decision -- that comes from probability_buy/probability_sell and the
    # additive chain -- so it was a parallel, display-only computation and
    # was deleted), which silently broke this function the exact same way
    # the paragraph below already describes fixing once before: bull_case/
    # bear_case quietly went back to 0 confidence and no supporting
    # indicators. Now reads each indicator's own {recommendation,
    # confidence, reason} directly from its top-level entry in
    # result["indicators"] -- every indicator already exposes these on
    # itself; the only thing that changed is there's no longer a single
    # combined dict to read them all from in one place, so this iterates
    # result["indicators"] directly instead.
    #
    # (Historical note, previous fix: was result["entry_analysis"]
    # ["indicator_scores"]["breakdown"] and result["components"]
    # ["5_support_resistance"] -- both paths were removed when every
    # indicator got merged into a single coherent result["indicators"]
    # section. Same underlying lesson both times: a consumer reading a
    # path one layer removed from the actual computation silently breaks
    # whenever that layer gets refactored, with no error, just empty data.)
    indicators = result.get("indicators", {})
    sr = indicators.get("support_resistance", {})
    entry = result.get("entry_details", {})

    # Every dict-valued entry in result["indicators"] that reports a plain
    # BUY/SELL/NEUTRAL recommendation counts as a vote here -- a few
    # sub-sections (e.g. "breakout", "wave_c") carry richer nested data
    # instead of a flat recommendation and are simply skipped rather than
    # guessed at.
    bull_support, bear_support = [], []
    bull_conf_sum, bear_conf_sum = 0, 0
    for name, ind in indicators.items():
        if not isinstance(ind, dict):
            continue
        # "volume" used to publish its key as "rec" rather than
        # "recommendation" -- that was itself a bug in asset_analysis.py
        # (it read a "rec" key score_volume_indicator never emitted, so the
        # field was pinned to its default) and has since been fixed at
        # source. The "rec" fallback is kept for older payloads.
        rec = ind.get("recommendation", ind.get("rec"))
        # ✅ FIXED: was ind.get("confidence", 0). support_resistance /
        # wyckoff / ict_concepts / volume publish no `confidence` key, so
        # each of them entered its case at 0 and dragged the case's MEAN
        # confidence down by simply being present. Confirmed live: a bull
        # case of trend(65) + macd(80) + support_resistance(0) reported
        # 48.3, when support_resistance's own score was 71.4 -- the
        # strongest structural read in the payload was scored as the
        # weakest thing supporting the trade. With the fallback it reports
        # 73.0 instead.
        conf = round(_indicator_confidence(ind), 1)
        # Same story for `reason`: these indicators don't all carry one,
        # and an empty string in the explain_decision() output reads as a
        # missing thought rather than a missing field.
        reason = ind.get("reason") or f"{name} reads {rec} (score {ind.get('score')})"
        entry_line = {"indicator": name, "confidence": conf, "reason": reason}
        if rec == "BUY":
            bull_support.append(entry_line)
            bull_conf_sum += conf
        elif rec == "SELL":
            bear_support.append(entry_line)
            bear_conf_sum += conf

    bull_case = {
        "thesis": "BUY",
        "confidence": round(bull_conf_sum / max(len(bull_support), 1), 1),
        "supporting_indicators": bull_support,
        "invalidation_trigger": (
            f"Price closes below stop_loss {entry.get('stop_loss')} "
            f"({entry.get('stop_loss_pips')} pips) or a bearish indicator "
            f"flip pushes weighted score negative."
        ),
    }
    bear_case = {
        "thesis": "SELL",
        "confidence": round(bear_conf_sum / max(len(bear_support), 1), 1) if bear_support else 0,
        "supporting_indicators": bear_support,
        "invalidation_trigger": (
            f"Price reclaims above resistance r1 {sr.get('r1')} on volume, "
            f"or the currently-live bearish indicators (e.g. stochastic) "
            f"cross back into neutral/bullish territory."
        ),
    }
    return {"bull_case": bull_case, "bear_case": bear_case}


# ============================================================
# 4. SCENARIO TREE (primary / invalidation / alternate)
# ============================================================


def _scenario_probability(result: Dict[str, Any]) -> float:
    """
    The probability the entry gate tested, for the direction taken.

    Defined once so the scenario tree and the gate list cannot drift
    apart -- they published different numbers for the same decision
    before this existed.
    """
    fv = result.get("final_verdict") or {}
    value = fv.get("probability_percent")
    if value is None:
        directional = result.get("directional_analysis") or {}
        key = ("buy_probability" if directional.get("best_direction") == "BUY"
               else "sell_probability")
        value = directional.get(key, 0)
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0

def build_scenario_tree(result: Dict[str, Any]) -> Dict[str, Any]:
    entry = result.get("entry_details", {})
    entry_a = result.get("entry_analysis", {})
    discount = entry_a.get("discount", {})
    directional = result.get("directional_analysis", {})

    # ✅ FIXED: discount_level/distance_pips are only present when
    # entry_engine.py actually reached the discount calculation (i.e.
    # the zone was valid to begin with) - on INVALID_ZONE and similar
    # early-exit paths it deliberately omits them since there's no real
    # discount level to report. This used to silently render as
    # "Price reaches discount level None (None pips away)".
    discount_level = discount.get('discount_level')
    distance_pips = discount.get('distance_pips')
    if discount_level is not None:
        primary_trigger = f"Price reaches discount level {discount_level} ({distance_pips} pips away)"
    else:
        primary_trigger = f"No discount level available ({discount.get('discount_quality', 'unknown')}) - zone was not valid enough to compute one"

    primary = {
        "scenario": "Primary — discount entry fills, trade proceeds toward TP1/TP2/TP3",
        # FIXED (defect D-20): was directional.get("buy_probability")
        # UNCONDITIONALLY -- so on a SELL the primary scenario carried the
        # BUY probability and invalidation carried 100 minus it. XAGUSD
        # 2026-09-01 10:58 was a SELL at 71.7% and this block published
        # primary 19.0% / invalidation 81.0%: the buy side, exactly
        # inverted, on the payload a human reads to sanity-check the call.
        "probability_pct": _scenario_probability(result),
        "trigger": primary_trigger,
        "targets": [entry.get("take_profit_1"), entry.get("take_profit_2"), entry.get("take_profit_3")],
    }
    invalidation = {
        "scenario": "Invalidation — stop loss hit before any target",
        "probability_pct": round(100 - _scenario_probability(result), 1),
        "trigger": f"Price trades through stop_loss {entry.get('stop_loss')} "
                   f"({entry.get('stop_loss_pips')} pips)",
    }
    alternate = {
        "scenario": "Alternate — price never reaches discount, setup expires unfilled",
        "probability_pct": None,  # not currently modeled anywhere upstream
        "trigger": "Price trends away from discount level without retracing "
                   "(e.g. breaks and holds above current range highs)",
        "note": "no upstream field currently estimates this probability; "
                "flagged rather than guessed.",
    }
    return {"primary": primary, "invalidation": invalidation, "alternate": alternate}


# ============================================================
# 5. SENSITIVITY / COUNTERFACTUAL
# ============================================================
# "If indicator X had scored the opposite, would the unified recommendation
# flip?" -- tells you whether the decision hinges on one fragile vote or is
# robustly overdetermined.

def build_sensitivity_report(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    ✅ REDESIGNED (not just a path fix): the old version read
    result["indicators"]["unified_score"]["breakdown"], asking "if this
    indicator's score were negated, would the unified weighted-vote sign
    flip?" That whole mechanism is gone -- unified_score itself was
    removed from asset_analysis.py's output because it never actually
    drove best_probability/the real trade decision (see the removal note
    at its former location in asset_analysis.py). Even a path fix
    wouldn't have been enough: no indicator carries a "weight" field
    outside that now-deleted computation, so there'd be nothing left to
    build a counterfactual weighted-sum from.

    Rebuilt against what's ACTUALLY load-bearing now: final_verdict's
    *_final_score entries (gnn/smc/pattern/fvg_ifvg/order_flow/
    gap_slippage/trend_cascade/exhaustion/adr_exhaustion/dxy_confluence/
    nested_zone), each of which reports a real, signed "adjustment" it
    applied to best_probability. For each one, this asks the question
    that actually matters for THIS pipeline: "if this specific
    confluence check's adjustment had been zero instead, would the
    trade have ended up on the other side of the entry probability
    threshold?" That's a real, accurate sensitivity/counterfactual
    against the real decision mechanism, rather than an always-empty
    report against a mechanism that no longer exists.
    """
    final_verdict = result.get("final_verdict", {})
    cfg = result.get("config", {})

    final_probability = final_verdict.get("probability_percent", 0)
    threshold = cfg.get("min_probability_for_entry", _DEFAULT_ENTRY_THRESHOLD)
    passed_now = final_probability >= threshold

    # Every *_final_score entry that reports a numeric "adjustment" --
    # new confluence checks automatically show up here with no further
    # wiring needed, since they all already follow this same shape.
    chain_keys = [k for k in final_verdict if k.endswith("_final_score")]

    flips = []
    for key in chain_keys:
        entry = final_verdict.get(key)
        if not isinstance(entry, dict) or "adjustment" not in entry:
            continue
        adjustment = entry.get("adjustment", 0) or 0
        if adjustment == 0:
            continue  # no-op checks aren't a sensitivity point by definition
        # ✅ FIXED: the subtraction was unclamped, so a check whose
        # adjustment exceeds the (already floored) final probability
        # produced an impossible negative. Live: probability 5.0 with an
        # adr_exhaustion adjustment of +8.0 reported a counterfactual of
        # -3.0%. Every stage of the real chain clamps to [5, 95]; the
        # counterfactual has to use the same bounds or it isn't describing
        # a state the system could ever have been in.
        #
        # Note this is inherently approximate once the chain clamps: if
        # the floor was already binding, removing a check may not actually
        # have moved the result at all. clamped_at_bound flags exactly
        # that case rather than presenting a clean number that isn't one.
        raw_counterfactual = final_probability - adjustment
        counterfactual_probability = max(5.0, min(95.0, raw_counterfactual))
        clamped = counterfactual_probability != raw_counterfactual
        would_pass_without = counterfactual_probability >= threshold
        flips.append({
            "check": key.replace("_final_score", ""),
            "adjustment_applied": adjustment,
            "counterfactual_probability_without_it": round(counterfactual_probability, 1),
            "clamped_at_bound": clamped,
            "would_flip_pass_fail": passed_now != would_pass_without,
        })

    fragile_votes = [f["check"] for f in flips if f["would_flip_pass_fail"]]
    return {
        "final_probability": final_probability,
        "entry_threshold": threshold,
        "passed_threshold": passed_now,
        "per_check_counterfactual": flips,
        "fragile_single_point_dependencies": fragile_votes,
        "robustness": (
            "FRAGILE (single confluence check decided pass/fail)" if fragile_votes
            else "OVERDETERMINED (no single check's removal changes pass/fail)"
        ),
    }


# ============================================================
# 6. OUTCOME SLOT — see module docstring
# ============================================================

def attach_outcome(snapshot: Dict[str, Any], hit: str, pips_moved: float,
                    bars_to_outcome: int, exit_price: float) -> Dict[str, Any]:
    """
    hit: one of 'TP1', 'TP2', 'TP3', 'SL', 'EXPIRED_UNFILLED', 'MANUAL_CLOSE'
    Call this once, later, when you know what happened. This is the entire
    "logging system" -- one function call appending one dict to a snapshot
    you already saved. Nothing else required.
    """
    snap = copy.deepcopy(snapshot)
    snap["outcome"] = {
        "hit": hit,
        "pips_moved": pips_moved,
        "bars_to_outcome": bars_to_outcome,
        "exit_price": exit_price,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    return snap


# ============================================================
# 7. TOP-LEVEL SNAPSHOT BUILDER
# ============================================================

def build_decision_snapshot(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wraps the full existing asset_analysis.py output dict into one
    self-contained Decision Snapshot. Does not modify `result` — pure
    function of the existing payload, so it can be called on already-saved
    JSON as easily as on a live signal.
    """
    return {
        "snapshot_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": result.get("config", {}).get("symbol"),
        "input_state_reference": {
            "timestamp": result.get("timestamp"),
            "entry_price": result.get("entry_details", {}).get("entry_price"),
            "timeframe": result.get("config", {}).get("timeframe"),
            "note": (
                "raw OHLC/tick arrays are not part of this JSON payload -- "
                "this reference lets you re-fetch the exact bar this "
                "decision was made on, it does not embed the arrays "
                "themselves. Embed them here directly if true offline "
                "replay without a data connection is required."
            ),
        },
        "gates_with_margin": build_gates_with_margin(result),
        **build_bull_bear_case(result),
        "scenario_tree": build_scenario_tree(result),
        "sensitivity": build_sensitivity_report(result),
        "final_verdict": result.get("final_verdict", {}),
        "outcome": None,  # see module docstring — fill via attach_outcome()
    }


# ============================================================
# 8. EXPLAIN / REPLAY — reconstruct the decision in plain language
# ============================================================

def explain_decision(snapshot: Dict[str, Any]) -> str:
    """
    Deterministically reconstructs a natural-language walkthrough from the
    snapshot alone: what fired, what almost fired, bull vs bear case, the
    scenario tree, and (if present) what actually happened.
    """
    lines = []
    sym = snapshot.get("symbol", "UNKNOWN")
    lines.append(f"=== Decision Snapshot — {sym} @ {snapshot.get('input_state_reference', {}).get('timestamp')} ===\n")

    lines.append("Gates checked:")
    for g in snapshot["gates_with_margin"]:
        status = "PASS" if g["passed"] else "FAIL"
        if g.get("margin") is not None:
            margin_txt = f" (margin {g['margin']:+.2f} {g.get('unit') or ''})".rstrip()
            near = "  <-- NEAR MISS" if g.get("near_miss") else ""
            lines.append(f"  [{status}] {g['gate']}: value={g['value']} threshold={g['threshold']}{margin_txt}{near}")
        else:
            lines.append(f"  [{status}] {g['gate']}")
    lines.append("")

    bull, bear = snapshot["bull_case"], snapshot["bear_case"]
    lines.append(f"Bull case (confidence {bull['confidence']}): "
                 f"{len(bull['supporting_indicators'])} indicator(s) support BUY.")
    for ind in bull["supporting_indicators"]:
        lines.append(f"    - {ind['indicator']} (conf {ind['confidence']}): {ind['reason']}")
    lines.append(f"  Invalidated if: {bull['invalidation_trigger']}\n")

    lines.append(f"Bear case (confidence {bear['confidence']}): "
                 f"{len(bear['supporting_indicators'])} indicator(s) support SELL.")
    for ind in bear["supporting_indicators"]:
        lines.append(f"    - {ind['indicator']} (conf {ind['confidence']}): {ind['reason']}")
    lines.append(f"  Invalidated if: {bear['invalidation_trigger']}\n")

    sens = snapshot["sensitivity"]
    lines.append(f"Robustness: {sens['robustness']}")
    if sens["fragile_single_point_dependencies"]:
        lines.append(f"  Single points of failure: {', '.join(sens['fragile_single_point_dependencies'])}")
    lines.append("")

    tree = snapshot["scenario_tree"]
    lines.append(f"Primary scenario ({tree['primary']['probability_pct']}%): {tree['primary']['scenario']}")
    lines.append(f"  Trigger: {tree['primary']['trigger']}")
    lines.append(f"Invalidation scenario ({tree['invalidation']['probability_pct']}%): {tree['invalidation']['scenario']}")
    lines.append(f"  Trigger: {tree['invalidation']['trigger']}")
    lines.append(f"Alternate scenario: {tree['alternate']['scenario']}")
    lines.append(f"  Trigger: {tree['alternate']['trigger']}\n")

    fv = snapshot.get("final_verdict", {})
    lines.append(f"Final verdict at decision time: {fv.get('verdict')}\n")

    outcome = snapshot.get("outcome")
    if outcome:
        lines.append(
            f"=== OUTCOME (recorded {outcome['recorded_at']}) ===\n"
            f"Result: {outcome['hit']} | {outcome['pips_moved']} pips | "
            f"{outcome['bars_to_outcome']} bars to resolve | exit {outcome['exit_price']}\n"
        )
        if outcome["hit"] == "SL" and bull["supporting_indicators"]:
            lines.append(
                "Post-mortem: the bull case's supporting indicators were live "
                "and did not prevent the loss -- worth checking whether the "
                "bear case's invalidation trigger fired earlier than the "
                "primary scenario's own trigger did."
            )
    else:
        lines.append(
            "=== OUTCOME: not yet recorded ===\n"
            "This snapshot explains what the rules said. It cannot yet tell "
            "you whether they were right -- call attach_outcome() once price "
            "has moved forward to close that loop."
        )

    return "\n".join(lines)


# ============================================================
# 9. DEMO — run against a real saved output
# ============================================================
if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python decision_snapshot.py <path_to_analysis_json>")
        sys.exit(1)

    with open(path) as f:
        result = json.load(f)

    snap = build_decision_snapshot(result)
    print(json.dumps(snap, indent=2, default=str))
    print("\n\n" + "=" * 70 + "\n")
    print(explain_decision(snap))