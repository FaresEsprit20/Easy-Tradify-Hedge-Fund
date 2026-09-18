# ============================================================
# PRICE EVOLUTION MAPS -- the current asset-analysis snapshot, field by field
# ============================================================
# FILE: ai/price_evolution_maps.py
#
# What the encoder, decoder and bridge agree a snapshot looks like. Rebuilt on
# 2026-09-17 against live analyze_institutional_signal() payloads (EURUSD,
# XAUUSD, US500, GBPJPY; AUTO/BUY/SELL): the decision at the top level, the
# strategy groups, the state readings, and every detector filed under its
# group by core/analysis_groups.reshape().
#
# WHY IT WAS REBUILT
# ------------------
# The previous maps described a payload that no longer exists: components
# 1_trend_bias..8_indicators, indicator_scores, gnn/ohlc_gnn, pattern_analysis,
# lot_result, symbolic_gate, decision_snapshot, directional_analysis. Every
# short code read an absent section and silently wrote its default, so a stored
# price point said "trend NEUTRAL, zone grade E, GNN 0" whatever the market was
# doing -- while strategy_groups, state_readings, direction_decision, the market
# stop and the OU reversion fit (the sections the decision is actually made
# from) had no code at all.
#
# THREE KINDS OF PATH -- every path in a snapshot is exactly one of them
# ----------------------------------------------------------------------
#   field  a scalar with a short code (FIELDS). Stored VERBATIM: no rounding and
#          no integer enums, so a code decodes to the exact value and a label
#          the maps have never seen is kept rather than coerced to a default.
#   list   a list-valued path (LIST_TEMPLATES). Kept whole in the lossless
#          payload; the bridge expands it into features.
#   data   analysis.<GROUP>.data.<block>: a detector's raw output, filed by
#          core/analysis_groups.GROUPS. Kept whole in the lossless payload.
#
# coverage() classifies a live payload and names anything that is none of the
# three; tests/test_price_evolution_alignment.py fails on it, and on any code
# whose path no snapshot can produce.
#
# The group, member and reading registries come from core rather than being
# copied, so a group or reading added there is known here at once. Its short
# code still has to be named below -- the alignment test says which.
# ============================================================

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

from core.analysis_groups import GROUPS as _ANALYSIS_LAYOUT
from core.analysis_groups import TRASH as _TRASH
from core.state_readings import MEASURED as _STATE_READING_SPECS
from core.strategy_groups import GROUP_TITLES as _GROUP_TITLES
from core.strategy_groups import MEMBERS as _GROUP_MEMBERS

SCHEMA_NAME = "asset_analysis"
SCHEMA_VERSION = 3
LAYOUT_GROUPED = "grouped"      # core/analysis_groups.reshape() ran
LAYOUT_FLAT = "flat"            # reshape failed: detectors still at the top level


class _Missing:
    """Absent, as distinct from present-and-None."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


# ============================================================
# REGISTRIES (from core)
# ============================================================

STRATEGY_GROUPS: Tuple[str, ...] = tuple(_GROUP_TITLES)
ANALYSIS_GROUPS: Tuple[str, ...] = tuple(_ANALYSIS_LAYOUT)
GROUP_DATA_BLOCKS: Dict[str, Tuple[str, ...]] = {
    group: tuple(key for key, _legacy in items) for group, items in _ANALYSIS_LAYOUT.items()}
GROUP_MEMBERS: Dict[str, Tuple[str, ...]] = {
    group: tuple(name for owner, name, _reader in _GROUP_MEMBERS if owner == group)
    for group in STRATEGY_GROUPS}
STATE_READINGS: Dict[str, str] = {
    name: spec.get("group", "CONTEXT") for name, spec in _STATE_READING_SPECS.items()}

# Sections that existed before the grouping and the 2026-09-15 deletions. A
# payload carrying one of these at the top level is either flat (reshape did
# not run) or old, and a reader asking for one is reading a dead section.
REMOVED_SECTIONS: Tuple[str, ...] = tuple(sorted(set(
    [t for t in _TRASH if "." not in t]
    + [legacy.split(".")[0] for items in _ANALYSIS_LAYOUT.values() for _k, legacy in items]
    + ["decision_snapshot", "directional_analysis", "lot_result", "indicator_scores",
       "coherence", "conviction", "model_version"])))


# ============================================================
# SHORT NAMES
# ============================================================

GROUP_CODES: Dict[str, str] = {
    "TREND": "tr", "MOMENTUM": "mo", "MEAN_REVERSION": "mr", "STRUCTURE": "st",
    "SMC": "sm", "ORDER_FLOW": "of", "WAVE": "wv", "CROSS_ASSET": "ca", "CONTEXT": "cx",
}

READING_CODES: Dict[str, str] = {
    "supply_demand_side": "sds", "nearer_pivot_level": "npl", "value_area_side": "vas",
    "poc_side": "poc", "liquidity_pool_side": "lps", "premium_discount": "pd",
    "fvg_side": "fvg", "ema200_side": "e200", "ema_gap": "egap", "macd_histogram": "mch",
    "rsi_from_50": "rsi", "bollinger_percent_b": "bpb", "correction_direction": "cor",
}

SUMMARY_KEYS: Dict[str, str] = {
    "🎯 FINAL_DECISION": "fd",
    "💰 ENTRY": "en",
    "🛑 STOP_LOSS": "sl",
    "🎯 TAKE_PROFIT_1": "tp1",
    "🎯 TAKE_PROFIT_2": "tp2",
    "🎯 TAKE_PROFIT_3": "tp3",
    "📊 LOT_SIZE": "lot",
    "💵 RISK_USD": "rsk",
    "📈 REWARD_USD": "rwd",
    "💰 MARGIN_REQUIRED_USD": "mrg",
    "⭐ CONFIDENCE": "cf",
    "⭐ CONFIDENCE_POST_CHAIN": "cfp",
    "🚀 SIMPLE_ACTION": "sa",
    "🚀 REASON": "rs",
}

# Always present on a successful analysis, in the order the engine writes them.
TOP_LEVEL_KEYS: Tuple[str, ...] = (
    ("success", "timestamp") + tuple(SUMMARY_KEYS)
    + ("direction_decision", "strategy_groups", "entry_analysis", "position_management",
       "vetos", "final_verdict", "entry_details", "account_info", "config",
       "state_readings", "analysis"))

# Present only on some branches:
#   calibrated_decision  core/calibrated_model when decision_mode == "calibrated"
#   FINAL_DECISION       the plain key calibrated_model.apply_entry writes on an entry
#   error                every early `return {"success": False, "error": ...}`
OPTIONAL_TOP_LEVEL_KEYS: Tuple[str, ...] = ("calibrated_decision", "FINAL_DECISION", "error")

VETO_CHECKS: Dict[str, str] = {
    "session_veto": "ses", "news_veto": "nws", "choppy_market": "chp",
    "extreme_volatility": "exv", "against_trend": "atr", "against_ema": "aem",
    "h1_conflict": "h1c", "rsi_divergence_opposing": "rdo", "wick_reversal": "wrv",
    "low_volume": "lvo", "high_spread": "hsp", "candle_too_young": "cty",
}

# final_verdict.<block>: (short name, (field, code) ...). Each block reports how
# one confluence check moved (or wanted to move) the probability.
FINAL_SCORE_BLOCKS: Dict[str, Tuple[str, Tuple[Tuple[str, str], ...]]] = {
    "gnn_final_score": ("gn", (("aligned", "al"), ("data_quality", "dq"), ("final_score", "fs"),
                               ("gnn_contribution", "ct"), ("gnn_recommendation", "rc"),
                               ("gnn_score", "sc"), ("gnn_weight_used", "wu"))),
    "smc_final_score": ("sm", (("aligned", "al"), ("final_score", "fs"), ("smc_contribution", "ct"),
                               ("smc_recommendation", "rc"), ("smc_score", "sc"),
                               ("smc_weight_used", "wu"))),
    "pattern_final_score": ("pt", (("aligned", "al"), ("directions.BEARISH", "dbe"),
                                   ("directions.BULLISH", "dbu"), ("directions.NEUTRAL", "dne"),
                                   ("final_score", "fs"), ("pattern_contribution", "ct"),
                                   ("pattern_recommendation", "rc"), ("pattern_score", "sc"),
                                   ("pattern_weight_used", "wu"), ("patterns_detected", "pd"))),
    "fvg_ifvg_final_score": ("fg", (("aligned", "al"), ("final_score", "fs"),
                                    ("fvg_ifvg_contribution", "ct"), ("fvg_ifvg_recommendation", "rc"),
                                    ("fvg_ifvg_score", "sc"), ("fvg_ifvg_weight_used", "wu"))),
    "order_flow_final_score": ("of", (("aligned", "al"), ("final_score", "fs"),
                                      ("order_flow_contribution", "ct"),
                                      ("order_flow_recommendation", "rc"), ("order_flow_score", "sc"),
                                      ("order_flow_weight_used", "wu"))),
    "gap_slippage_final_score": ("gp", (("final_score", "fs"), ("gap_slippage_penalty", "pen"),
                                        ("gap_slippage_weight_used", "wu"))),
    "trend_cascade_final_score": ("tc", (("adjustment", "adj"), ("aligned", "al"),
                                         ("final_score", "fs"), ("reason", "rs"))),
    "adr_exhaustion_final_score": ("ad", (("adjustment", "adj"), ("final_score", "fs"),
                                          ("reason", "rs"), ("signal", "sig"))),
    "rvam_final_score": ("rv", (("adjustment", "adj"), ("aligned", "al"), ("final_score", "fs"),
                                ("reason", "rs"), ("rvam.confirms", "rvc"), ("rvam.reason", "rvr"),
                                ("rvam.score", "rvs"))),
}

# Keys the encoder writes beside the field codes. No field may use one.
RESERVED_KEYS: Tuple[str, ...] = (
    "t", "p", "pf", "pp", "ohlc", "mv", "layout", "unmapped_paths", "unmapped_count", "full_analysis_keys",
    "analysis_schema", "schema_version", "full_analysis_z", "full_analysis_bytes",
    "full_analysis", "_encoded", "_decoded_from")


# ============================================================
# THE FIELD TABLE
# ============================================================

class Field(NamedTuple):
    code: str
    path: Tuple[str, ...]
    template: str       # the path with {G}/{R} placeholders, for "can any snapshot produce this?"
    compact: bool       # carried on every price_evolution point, not only on full encodes


class _TableBuilder:
    def __init__(self) -> None:
        self.fields: List[Field] = []

    def add(self, code: str, path: Iterable[str], compact: bool = False,
            template: Optional[str] = None) -> None:
        path = tuple(path)
        self.fields.append(Field(code, path, template or ".".join(path), compact))

    def section(self, prefix: str, base: Tuple[str, ...], entries: Iterable[Tuple[str, str]],
                compact: Iterable[str] = (), template_base: Optional[str] = None) -> None:
        compact = set(compact)
        for key, code in entries:
            path = base + tuple(key.split("."))
            template = ".".join((template_base or ".".join(base), key)) if base else key
            self.add(f"{prefix}{code}", path, compact=code in compact, template=template)


# entry_analysis.rules.<rule> (core/entry_engine.RULE_ORDER)
ENTRY_RULE_CODES: Dict[str, str] = {
    "zone": "zn", "signals": "sg", "probability": "pr", "setup": "su", "discount": "ds",
    "discount_quality": "dq", "confirmation": "cf", "timing": "tm", "momentum": "mm",
}


def _build_fields() -> Tuple[Field, ...]:
    b = _TableBuilder()

    # --- the decision headline ------------------------------------------------
    b.add("scs", ("success",), compact=True)
    b.add("ts", ("timestamp",), compact=True)
    for key, code in SUMMARY_KEYS.items():
        b.add(code, (key,), compact=True)
    b.add("fdp", ("FINAL_DECISION",), compact=True)
    b.add("err", ("error",), compact=True)

    # --- direction_decision -----------------------------------------------------
    b.section("dd_", ("direction_decision",), (
        ("analysis_direction", "ad"), ("traded_direction", "td"),
        ("flipped_by_trend_cascade", "fl"), ("cascade_direction", "cd"),
        ("cascade_score", "cs"), ("chosen_direction_was_vetoed", "cv"),
        ("veto_overruled_by_trend_cascade", "vo")),
        compact=("ad", "td", "fl", "cd", "cs", "cv", "vo"))

    # --- strategy_groups ----------------------------------------------------------
    b.section("sg_", ("strategy_groups",), (
        ("enabled", "en"), ("version", "ver"), ("direction", "dir"), ("winner", "win"),
        ("selected", "sel"), ("cost_priced_on", "cpo"),
        ("best_score", "bs"), ("groups_agreeing", "ga"), ("groups_scored", "gs"),
        ("other_side_best", "osb"), ("contested", "con"), ("most_opposed", "mo"),
        ("opposition", "op"), ("context_total", "ct"), ("final_probability", "fp"),
        ("reason", "rs"), ("error", "err"),
        ("other_side.direction", "osd"), ("other_side.final_probability", "osp"),
        ("cost.cost_r", "ccr"), ("cost.penalty_points", "cpp"), ("cost.target_r", "ctr"),
        ("calibrated.version", "kv"), ("calibrated.p_up", "kp"),
        ("calibrated.probability", "kpr"), ("calibrated.preferred_direction", "kpd"),
        ("calibrated.preferred_probability", "kpp"),
        ("edges.version", "ev"), ("edges.error", "eerr"),
        ("edges.ccy_strength_60", "ecs60"), ("edges.ccy_strength_240", "ecs240"),
        ("edges.compression", "ecmp"), ("edges.day_open_side", "edos"),
        ("edges.day_range_pos", "edrp"), ("edges.hour_utc", "ehr"),
        ("edges.mean_dist_60", "emd60"), ("edges.mom_15", "em15"), ("edges.mom_60", "em60"),
        ("edges.mom_240", "em240"), ("edges.mom_1440", "em1440"),
        ("edges.mom_agreement", "ema"), ("edges.prev_day_break", "epdb"),
        ("edges.asia_break", "eab"), ("edges.asia_range_atr", "eara"),
        ("edges.prev_day_pos", "epdp"), ("edges.sweep_reclaim", "eswr"),
        ("edges.weekday", "ewd")),
        compact=("dir", "win", "bs", "ga", "gs", "osb", "con", "mo", "op", "ct", "fp", "err",
                 "osd", "osp", "ccr", "cpp", "ctr", "kp", "kpr", "kpd", "kpp"))
    for group in STRATEGY_GROUPS:
        g = GROUP_CODES[group]
        b.section(f"sg_{g}_", ("strategy_groups", "groups", group), (
            ("title", "ti"), ("scored", "ok"), ("reason", "rs"), ("agreement", "ag"),
            ("score", "sc"), ("with_count", "wc"), ("against_count", "ac"),
            ("counts_in_decision", "cid"), ("excluded_reason", "xr")),
            compact=("ok", "ag", "sc"), template_base="strategy_groups.groups.{G}")
    for group in ANALYSIS_GROUPS:
        g = GROUP_CODES[group]
        b.section(f"sk_{g}_", ("strategy_groups", "calibrated", "groups", group), (
            ("p_up", "p"), ("readings", "n"), ("score", "s")),
            template_base="strategy_groups.calibrated.groups.{G}")

    # --- entry_analysis -------------------------------------------------------------
    b.section("ea_", ("entry_analysis",), (
        ("pre_entry_passed", "pep"), ("pre_entry_skip_reason", "psr"), ("should_enter", "se"),
        ("engine_qualified", "eq"), ("entry_status", "es"), ("final_decision", "fd"),
        ("simple_action", "sa"), ("execution", "ex"), ("reason", "rs"), ("star_rating", "sr"),
        ("stars_display", "sd"), ("entry_quality", "qu"), ("timing_confidence", "tc"),
        ("timing_ready", "tr"), ("timing_bypassed_replay", "tbr"),
        ("micro_structure_available", "msa"), ("required_confirmation", "rc"),
        ("veto_reason", "vr"),
        ("discount.action", "d_ac"), ("discount.discount_level", "d_lv"),
        ("discount.discount_quality", "d_q"), ("discount.discount_score", "d_sc"),
        ("discount.distance_pips", "d_dp"), ("discount.expected_direction", "d_ed"),
        ("discount.freshness_score", "d_fs"), ("discount.grade_multiplier", "d_gm"),
        ("discount.is_already_at_discount", "d_at"), ("discount.zone_grade", "d_zg"),
        ("discount.zone_type", "d_zt"), ("discount.debug.atr_pips", "d_atr"),
        ("discount.debug.buffer_pips_used", "d_buf"), ("discount.debug.distance_pips", "d_ddp"),
        ("discount.debug.instrument", "d_ins"), ("discount.debug.need_to_drop", "d_ntd"),
        ("discount.debug.need_to_rise", "d_ntr"),
        ("discount.debug.zone_level", "d_zl"), ("discount.debug.current_price", "d_cp"),
        ("discount.debug.grade_multiplier", "d_dgm"),
        ("discount.debug.premium_threshold_pips", "d_ptp"),
        ("discount.debug.adjusted_premium_threshold", "d_apt"),
        ("discount.debug.adjusted_good_threshold", "d_agt"),
        ("discount.debug.freshness_score", "d_dfs"), ("discount.debug.zone_touch_count", "d_ztc"),
        ("confirmation.is_confirmed", "c_ic"), ("confirmation.score", "c_sc"),
        ("confirmation.type", "c_ty"),
        ("golden_signals.absorption", "g_ab"), ("golden_signals.at_poi", "g_ap"),
        ("golden_signals.at_poi_fvg_proximity", "g_apf"),
        ("golden_signals.at_poi_zone_proximity", "g_apz"),
        ("golden_signals.momentum_burst", "g_mb"), ("golden_signals.signal_count", "g_sc"),
        ("golden_signals.signal_type", "g_st"), ("golden_signals.volume_spike", "g_vs"),
        ("golden_signals.at_poi_displacement.available", "g_da"),
        ("golden_signals.at_poi_displacement.body_pips", "g_dbp"),
        ("golden_signals.at_poi_displacement.body_range_ratio", "g_dbr"),
        ("golden_signals.at_poi_displacement.confirmed", "g_dc"),
        ("golden_signals.at_poi_displacement.reason", "g_dr"),
        ("h1_alignment.adjusted_probability", "h_ap"), ("h1_alignment.aligned", "h_al"),
        ("h1_alignment.confidence_bonus", "h_cb"), ("h1_alignment.h1_trend", "h_tr"),
        ("micro_structure.absorption_detected", "m_ad"), ("micro_structure.available", "m_av"),
        ("micro_structure.entry_confidence", "m_ec"),
        ("micro_structure.iceberg_available", "m_ia"),
        ("micro_structure.iceberg_detected", "m_id"),
        ("micro_structure.momentum_acceleration", "m_ma"),
        ("micro_structure.momentum_burst", "m_mb"), ("micro_structure.spread_collapse", "m_sc"),
        ("micro_structure.timing_confidence", "m_tc"), ("micro_structure.timing_ready", "m_tr"),
        ("micro_structure.volume_imbalance_confirms", "m_vic"),
        ("micro_structure.volume_imbalance_direction", "m_vid"),
        ("micro_structure.debug.ask_volume", "m_dav"),
        ("micro_structure.debug.avg_tick_volume", "m_datv"),
        ("micro_structure.debug.bid_volume", "m_dbv"),
        ("micro_structure.debug.spreads.avg_spread_pips", "m_dsa"),
        ("micro_structure.debug.spreads.current_spread_pips", "m_dsc"),
        ("micro_structure.debug.spreads.spread_collapse_triggered", "m_dst"),
        ("micro_structure.debug.tick_frequency", "m_dtf"),
        ("micro_structure.debug.ticks_per_second", "m_dtps"),
        ("micro_structure.debug.total_volume", "m_dtv"),
        ("micro_structure.debug.volume_imbalance", "m_dvi"),
        ("strategy.available", "s_av"), ("strategy.final_probability", "s_fp"),
        ("strategy.most_opposed", "s_mo"), ("strategy.name", "s_nm"),
        ("strategy.score", "s_sc"), ("strategy.title", "s_ti"), ("strategy.why", "s_why"),
        ("strategy.runner_up.group", "s_rug"), ("strategy.runner_up.score", "s_rus")) + tuple(
        # the entry rule table (core/entry_engine.py, entry foundation v2)
        (f"rules.{rule}.{key}", f"r_{rc}_{kc}")
        for rule, rc in ENTRY_RULE_CODES.items()
        for key, kc in (("passed", "p"), ("mode", "m"), ("value", "v"), ("threshold", "t"), ("why", "w"), ("polarity", "pl"))),
        compact=("se", "eq", "es", "sa", "ex", "sr", "qu", "tc", "tr", "pep", "g_sc",
                 "s_nm", "s_sc", "s_fp", "m_av", "m_tr")
                + tuple(f"r_{rc}_p" for rc in ENTRY_RULE_CODES.values()))

    # --- final_verdict ------------------------------------------------------------------
    b.section("fv_", ("final_verdict",), (
        ("verdict", "vd"), ("probability_percent", "pp"), ("probability_buy", "pb"),
        ("probability_sell", "ps"), ("best_direction", "bd"),
        ("probability_percent_post_chain", "ppc"), ("probability_ledger_reconciles", "plr"),
        ("probability_note", "pn"), ("action", "ac"), ("simple_action", "sa"),
        ("entry_price", "ep"), ("stop_loss", "sl"), ("stop_loss_pips", "slp"),
        ("take_profit_1", "tp1"), ("take_profit_2", "tp2"), ("take_profit_3", "tp3"),
        ("take_profit_pips", "tpp"), ("lot_size", "ls"), ("margin_required_usd", "mr"),
        ("risk_reward_ratio", "rr"), ("star_rating", "sr"), ("stars_display", "sd"),
        ("execution", "ex"), ("market_regime", "mrg"), ("timing_confidence", "tc"),
        ("timing_ready", "tr"), ("symbolic_blocked", "syb"), ("symbolic_reason", "syr"),
        ("should_enter", "se"), ("stop_source", "ssrc"),
        # the strategy the decision came from and the setup it trades
        ("strategy.name", "sn_n"), ("strategy.title", "sn_ti"), ("strategy.score", "sn_sc"),
        ("strategy.final_probability", "sn_fp"), ("strategy.why", "sn_why"),
        ("strategy.momentum", "sn_mom"),
        ("strategy_setup.version", "st_ver"), ("strategy_setup.group", "st_g"),
        ("strategy_setup.has_setups", "st_hs"), ("strategy_setup.name", "st_n"),
        ("strategy_setup.valid", "st_v"), ("strategy_setup.why", "st_why"),
        ("strategy_setup.title", "st_ti"), ("strategy_setup.direction", "st_d"),
        ("strategy_setup.entry_price", "st_ep"), ("strategy_setup.stop_loss", "st_sl"),
        ("strategy_setup.take_profit", "st_tp"), ("strategy_setup.risk_pips", "st_rp"),
        ("strategy_setup.reward_pips", "st_wp"), ("strategy_setup.risk_reward_ratio", "st_rr"),
        ("strategy_setup.net_risk_reward", "st_nrr"),
        ("strategy_setup.lot_size", "st_ls"), ("strategy_setup.projected_risk_usd", "st_pru"),
        ("strategy_setup.exit_type", "st_et"), ("strategy_setup.stop_loss_basis", "st_slb"),
        ("strategy_setup.take_profit_basis", "st_tpb"),
        ("directional_vetoes.both_directions_vetoed", "dv_b"),
        ("directional_vetoes.buy_veto", "dv_bv"),
        ("directional_vetoes.chosen_direction_was_vetoed", "dv_c"),
        ("directional_vetoes.sell_veto", "dv_sv"),
        ("probability_absorbed_by_bounds.clamped_step_count", "ab_n"),
        ("probability_absorbed_by_bounds.note", "ab_note"),
        ("probability_absorbed_by_bounds.total_absorbed", "ab_t")),
        compact=("vd", "pp", "pb", "ps", "bd", "ppc", "plr", "ac", "sa", "ep", "sl", "slp",
                 "tp1", "tpp", "ls", "rr", "sr", "ex", "mrg", "tc", "tr", "syb", "se", "ssrc",
                 "sn_n", "sn_sc", "sn_mom", "st_n", "st_v", "st_rp", "st_wp", "st_nrr", "st_ls",
                 "dv_b", "dv_bv", "dv_c", "dv_sv", "ab_t"))
    for block, (short, entries) in FINAL_SCORE_BLOCKS.items():
        b.section(f"fv_{short}_", ("final_verdict", block), entries, compact=("fs", "al", "adj"))

    # --- entry_details ------------------------------------------------------------------------
    b.section("ed_", ("entry_details",), (
        ("entry_price", "ep"), ("stop_loss", "sl"), ("stop_loss_pips", "slp"),
        ("take_profit_1", "tp1"), ("take_profit_2", "tp2"), ("take_profit_3", "tp3"),
        ("take_profit_pips", "tpp"), ("risk_reward", "rr"), ("lot_size", "ls"),
        ("spread_pips", "sp"), ("risk_usd", "ru"), ("reward_usd", "rw"),
        ("margin_required_usd", "mr"),
        ("risk_reward_detail.direction", "rd_d"), ("risk_reward_detail.ratio", "rd_r"),
        ("risk_reward_detail.reason", "rd_rs"), ("risk_reward_detail.reward_pips", "rd_wp"),
        ("risk_reward_detail.risk_pips", "rd_kp"), ("risk_reward_detail.valid", "rd_v"),
        ("behaviour.available", "b_av"), ("behaviour.reason", "b_rs"),
        ("behaviour.bars_since_extreme", "b_bse"), ("behaviour.extended", "b_ext"),
        ("behaviour.extension_atr", "b_ea"), ("behaviour.minutes_since_extreme", "b_mse"),
        ("behaviour.momentum_running", "b_mr"), ("behaviour.range_vs_base", "b_rvb"),
        ("behaviour.reversion_ready", "b_rr"), ("behaviour.side_if_reverting", "b_sir"),
        ("behaviour.slow", "b_slow"), ("behaviour.stalled", "b_st"),
        ("behaviour.velocity_atr", "b_va"), ("behaviour.volatility_transition", "b_vt"),
        ("market_stop.affordable", "ms_af"), ("market_stop.entry", "ms_en"),
        ("market_stop.h1_atr", "ms_atr"), ("market_stop.lot", "ms_lot"),
        ("market_stop.margin_usd", "ms_mu"), ("market_stop.risk_usd", "ms_ru"),
        ("market_stop.side", "ms_sd"), ("market_stop.stop_h1_atr_multiple", "ms_sm"),
        ("market_stop.stop_pips", "ms_sp"), ("market_stop.stop_price", "ms_spr"),
        ("market_stop.target_pips", "ms_tp"), ("market_stop.target_price", "ms_tpr"),
        ("market_stop.target_r", "ms_tr"), ("market_stop.target_risk_usd", "ms_tru"),
        ("ou_reversion.available", "ou_av"), ("ou_reversion.reason", "ou_rs"),
        ("ou_reversion.cost_sigma", "ou_cs"), ("ou_reversion.exit_z", "ou_ez"),
        ("ou_reversion.expected_gain_sigma", "ou_egs"), ("ou_reversion.forward_beta", "ou_fb"),
        ("ou_reversion.forward_t", "ou_ft"), ("ou_reversion.forward_windows", "ou_fw"),
        ("ou_reversion.half_life_bars", "ou_hl"), ("ou_reversion.net_edge_sigma", "ou_nes"),
        ("ou_reversion.phi", "ou_phi"), ("ou_reversion.price_share", "ou_psh"),
        ("ou_reversion.side", "ou_sd"), ("ou_reversion.sigma_eq", "ou_seq"),
        ("ou_reversion.size_multiple", "ou_szm"), ("ou_reversion.theta", "ou_th"),
        ("ou_reversion.time_stop_bars", "ou_tsb"), ("ou_reversion.tradeable", "ou_tr"),
        ("ou_reversion.z", "ou_z")),
        compact=("ep", "sl", "slp", "tp1", "tpp", "ls", "sp", "ru", "rw", "rd_r", "rd_v",
                 "b_ext", "b_ea", "b_mr", "b_rr", "b_st", "b_va", "b_vt",
                 "ms_af", "ms_sp", "ms_tr", "ou_tr", "ou_z", "ou_nes"))

    # --- vetos --------------------------------------------------------------------------------------
    b.section("vt_", ("vetos",), (("triggered", "tr"), ("reason", "rs")), compact=("tr", "rs"))
    b.section("vt_c_", ("vetos", "checks"), tuple(VETO_CHECKS.items()),
              compact=tuple(VETO_CHECKS.values()))
    b.section("vt_et_", ("vetos", "effective_thresholds"), (
        ("adx_threshold", "adx"), ("adx_threshold_source", "adxs"),
        ("choppy_market_mode", "chm"), ("symbol", "sym"),
        ("volatility_threshold_band", "vb"), ("volatility_threshold_pips", "vp"),
        ("volatility_threshold_source", "vs")))

    # --- account, position, config -------------------------------------------------------------------
    b.section("ai_", ("account_info",), (
        ("balance", "ba"), ("leverage", "lv"), ("free_margin_before", "fmb"),
        ("margin_required_usd", "mr"), ("free_margin_after", "fma")))
    b.section("pm_", ("position_management",), (
        ("should_close", "sc"), ("close_reason", "cr"), ("is_already_in_trade", "it"),
        ("current_pnl_percent", "pnl")), compact=("sc", "cr", "pnl"))
    b.section("cfg_", ("config",), (
        ("symbol", "sym"), ("strategy_selection", "ssel"),
        ("user_requested_direction", "urd"), ("executed_direction", "exd"),
        ("timeframe", "tf"), ("leverage", "lv"), ("fixed_trade_size_usd", "fts"),
        ("risk_per_trade_percent", "rpt"), ("max_risk_usd", "mru"), ("breakout_period", "bp"),
        ("breakout_volume_threshold", "bvt"), ("min_timing_confidence", "mtc"),
        ("min_probability_for_entry", "mpe"), ("strong_entry_threshold", "set"),
        ("decision_wait_threshold", "dwt"), ("decision_monitor_threshold", "dmt"),
        ("min_wick_ratio", "mwr"), ("extreme_volatility_veto_threshold", "evt"),
        ("ranging_market_adx_threshold", "rat"), ("trade_probability_minimum", "tpm"),
        ("gnn_enabled", "gne"), ("gnn_available", "gna"), ("gnn_ab_test_enabled", "gab"),
        ("gnn_weight", "gw"), ("gnn_confidence_threshold", "gct"), ("pattern_weight", "pw")),
        compact=("exd", "mpe", "ssel"))

    # --- state_readings -----------------------------------------------------------------------------------
    b.section("sr_", ("state_readings",), (
        ("groups_with_a_reading", "gwr"), ("readings", "n"), ("scored", "sc"), ("note", "note")),
        compact=("gwr", "n"))
    for reading, group in STATE_READINGS.items():
        r = READING_CODES.get(reading)
        if r is None:           # named in core, not here: the alignment test reports it
            continue
        b.section(f"sr_{r}_", ("state_readings", "groups", group, reading), (
            ("side", "sd"), ("value", "v"), ("holdout_won_pct", "w"), ("holdout_net_r", "r"),
            ("scored", "sc")), compact=("sd",), template_base=f"state_readings.groups.{{G}}.{{R}}")

    # --- analysis: each group's own verdict beside its data ---------------------------------------------------
    for group in STRATEGY_GROUPS:
        g = GROUP_CODES[group]
        b.section(f"an_{g}_", ("analysis", group), (
            ("score", "sc"), ("direction", "dir"), ("scored", "ok"), ("reason", "rs")),
            template_base="analysis.{G}")

    # --- calibrated_decision (only when the calibrated model decides) -------------------------------------------
    b.section("cd_", ("calibrated_decision",), (
        ("side", "sd"), ("probability", "pr"), ("floor", "fl"), ("flipped", "fp"),
        ("enter", "en"), ("reason", "rs")),
        compact=("sd", "pr", "fl", "fp", "en", "rs"))

    return tuple(b.fields)


FIELDS: Tuple[Field, ...] = _build_fields()
FIELDS_BY_CODE: Dict[str, Field] = {f.code: f for f in FIELDS}
FIELDS_BY_PATH: Dict[Tuple[str, ...], Field] = {f.path: f for f in FIELDS}
COMPACT_CODES: Tuple[str, ...] = tuple(f.code for f in FIELDS if f.compact)

# Fields a normal live bar does not produce, each with the branch that writes it.
# The alignment test accepts a code whose path no captured snapshot contains
# only if it is listed here -- anything else is a stale code.
OPTIONAL_TEMPLATES: Dict[str, str] = {
    "error": "core/asset_analysis.py early returns {'success': False, 'error': ...}",
    "FINAL_DECISION": "core/calibrated_model.apply_entry (calibrated entry)",
    "calibrated_decision.side": "asset_analysis: decision_mode == 'calibrated'",
    "calibrated_decision.probability": "asset_analysis: decision_mode == 'calibrated'",
    "calibrated_decision.floor": "asset_analysis: decision_mode == 'calibrated'",
    "calibrated_decision.flipped": "asset_analysis: decision_mode == 'calibrated'",
    "calibrated_decision.enter": "asset_analysis: decision_mode == 'calibrated'",
    "calibrated_decision.reason": "asset_analysis: decision_mode == 'calibrated'",
    "final_verdict.should_enter": "core/calibrated_model.apply_entry",
    "final_verdict.symbolic_blocked": "asset_analysis: symbolic gate enforced and failed",
    "final_verdict.symbolic_reason": "asset_analysis: symbolic gate enforced and failed",
    "entry_details.behaviour.reason": "core/behaviour_readings: unavailable",
    "entry_details.ou_reversion.reason": "core/ou_mean_reversion: unavailable",
    "strategy_groups.error": "asset_analysis: score_groups raised",
    "strategy_groups.edges.error": "core/edge_features: no M1 bars",
    "strategy_groups.cost_priced_on": "core/asset_analysis: a valid strategy setup re-prices the cost",
    # core/discount_engine.py: only when price is already at the zone
    # (action READY_FOR_CONFIRMATION); first seen live on XAUUSD 2026-09-17
    "entry_analysis.discount.debug.zone_level": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.current_price": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.grade_multiplier": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.premium_threshold_pips": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.adjusted_premium_threshold": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.adjusted_good_threshold": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.freshness_score": "core/discount_engine: price at the zone",
    "entry_analysis.discount.debug.zone_touch_count": "core/discount_engine: price at the zone",
}
# core/strategy_setups.pick: present only when the winning group's setup is valid
OPTIONAL_TEMPLATES.update({
    f"final_verdict.strategy_setup.{key}": "core/strategy_setups.pick: a valid setup"
    for key in ("title", "direction", "entry_price", "stop_loss", "take_profit", "risk_pips",
                "reward_pips", "risk_reward_ratio", "net_risk_reward", "lot_size", "projected_risk_usd", "exit_type",
                "stop_loss_basis", "take_profit_basis")})
# core/market_stop.plan: published only while USE_MARKET_STOP is on (off since
# 2026-09-17, operator decision -- original sizing); entry_details.market_stop is
# then null, which has its own code (ed_ms).
OPTIONAL_TEMPLATES.update({
    f"entry_details.market_stop.{key}": "core/market_stop (USE_MARKET_STOP = True)"
    for key in ("affordable", "entry", "h1_atr", "lot", "margin_usd", "risk_usd", "side",
                "stop_h1_atr_multiple", "stop_pips", "stop_price", "target_pips", "target_price",
                "target_r", "target_risk_usd")})

# Containers that may be null instead of a dict. The null itself is a fact
# ("no runner-up", "no affordable market stop"), so it gets a code of its own.
NULLABLE_CONTAINERS: Dict[str, Tuple[str, ...]] = {
    "ea_s_ru": ("entry_analysis", "strategy", "runner_up"),
    "ed_ms": ("entry_details", "market_stop"),
    "sg_cost": ("strategy_groups", "cost"),
    "sg_edges": ("strategy_groups", "edges"),
    "sg_cal": ("strategy_groups", "calibrated"),
    "sg_os": ("strategy_groups", "other_side"),
    "fv_rv_rvam": ("final_verdict", "rvam_final_score", "rvam"),
}
NULLABLE_CODES: Dict[Tuple[str, ...], str] = {path: code for code, path in NULLABLE_CONTAINERS.items()}

LIST_TEMPLATES: Tuple[str, ...] = (
    "strategy_groups.groups.{G}.members", "strategy_groups.ranked", "strategy_groups.context",
    "entry_analysis.strategy.agreeing", "entry_analysis.strategy.opposing", "entry_analysis.blocked_by",
    "entry_analysis.micro_structure.triggers", "entry_details.ou_reversion.why_not",
    "final_verdict.probability_ledger", "final_verdict.probability_absorbed_by_bounds.steps",
    "final_verdict.order_flow_final_score.reasons", "final_verdict.gap_slippage_final_score.reasons",
    "vetos.advisory_only", "config.valid_zone_grades", "config.pattern_timeframes",
    "final_verdict.strategy_setup.candidates",
    "analysis.{G}.members",
)


def _expand(template: str) -> List[str]:
    if "{G}" not in template:
        return [template]
    groups = STRATEGY_GROUPS
    return [template.replace("{G}", group) for group in groups]


LIST_PATHS: Tuple[str, ...] = tuple(p for t in LIST_TEMPLATES for p in _expand(t))


# ============================================================
# THE MAPS OBJECT
# ============================================================

class EvolutionMaps:
    """The current snapshot schema, and the path helpers every codec step uses."""

    SCHEMA_NAME = SCHEMA_NAME
    SCHEMA_VERSION = SCHEMA_VERSION
    FIELDS = FIELDS
    FIELDS_BY_CODE = FIELDS_BY_CODE
    FIELDS_BY_PATH = FIELDS_BY_PATH
    COMPACT_CODES = COMPACT_CODES
    OPTIONAL_TEMPLATES = OPTIONAL_TEMPLATES
    NULLABLE_CONTAINERS = NULLABLE_CONTAINERS
    LIST_PATHS = LIST_PATHS
    TOP_LEVEL_KEYS = TOP_LEVEL_KEYS
    OPTIONAL_TOP_LEVEL_KEYS = OPTIONAL_TOP_LEVEL_KEYS
    SUMMARY_KEYS = SUMMARY_KEYS
    STRATEGY_GROUPS = STRATEGY_GROUPS
    ANALYSIS_GROUPS = ANALYSIS_GROUPS
    GROUP_DATA_BLOCKS = GROUP_DATA_BLOCKS
    GROUP_MEMBERS = GROUP_MEMBERS
    STATE_READINGS = STATE_READINGS
    FINAL_SCORE_BLOCKS = FINAL_SCORE_BLOCKS
    VETO_CHECKS = VETO_CHECKS
    REMOVED_SECTIONS = REMOVED_SECTIONS
    RESERVED_KEYS = RESERVED_KEYS

    # ---------------------------------------------------------------- JSON safety
    def make_json_safe(self, value: Any) -> Any:
        """Recursively convert analysis payloads into JSON-safe values."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): self.make_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self.make_json_safe(v) for v in value]
        if hasattr(value, "tolist"):
            return self.make_json_safe(value.tolist())
        if hasattr(value, "item"):
            return self.make_json_safe(value.item())
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    # ---------------------------------------------------------------- paths
    @staticmethod
    def get_path(payload: Any, path: Tuple[str, ...]) -> Any:
        """Value at `path`, MISSING when any step is absent or not a dict."""
        node = payload
        for key in path:
            if not isinstance(node, Mapping) or key not in node:
                return MISSING
            node = node[key]
        return node

    @staticmethod
    def set_path(target: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
        node = target
        for key in path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[path[-1]] = value

    # ---------------------------------------------------------------- codes
    def encode_fields(self, payload: Mapping[str, Any], compact: bool = False) -> Dict[str, Any]:
        """code -> value for every mapped field present in `payload` (verbatim)."""
        out: Dict[str, Any] = {}
        for f in FIELDS:
            if compact and not f.compact:
                continue
            value = self.get_path(payload, f.path)
            if value is MISSING or isinstance(value, (dict, list)):
                continue
            out[f.code] = value
        for code, path in NULLABLE_CONTAINERS.items():
            if self.get_path(payload, path) is None:
                out[code] = None
        return out

    def decode_fields(self, encoded: Mapping[str, Any]) -> Dict[str, Any]:
        """The snapshot skeleton the codes describe (scalars only, no lists or data)."""
        out: Dict[str, Any] = {}
        for code, value in encoded.items():
            f = FIELDS_BY_CODE.get(code)
            if f is not None:
                self.set_path(out, f.path, value)
        for code, path in NULLABLE_CONTAINERS.items():
            if code in encoded and encoded[code] is None and self.get_path(out, path) is MISSING:
                self.set_path(out, path, None)
        return out

    # ---------------------------------------------------------------- coverage
    @staticmethod
    def layout(payload: Mapping[str, Any]) -> str:
        return LAYOUT_GROUPED if isinstance(payload.get("analysis"), Mapping) else LAYOUT_FLAT

    def classify(self, path: Tuple[str, ...], value: Any) -> Optional[str]:
        """"field", "list", "data", "nullable" -- or None when the maps do not know the path."""
        if len(path) >= 3 and path[0] == "analysis" and path[2] == "data":
            group = path[1]
            if len(path) == 3:
                return "data"
            return "data" if path[3] in GROUP_DATA_BLOCKS.get(group, ()) else None
        dotted = ".".join(path)
        if isinstance(value, list):
            return "list" if dotted in LIST_PATHS else None
        if value is None and path in NULLABLE_CODES:
            return "nullable"
        if isinstance(value, dict):
            return "container"
        return "field" if path in FIELDS_BY_PATH else None

    def coverage(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Classify every path of a payload against the maps.

        `unmapped` lists paths the maps cannot place -- a field the engine
        started publishing, or a detector reshape() did not file. `removed`
        lists top-level sections that no longer belong in a grouped snapshot.
        Both empty is what "the maps match this snapshot 100%" means.
        """
        counts = {"field": 0, "list": 0, "data": 0, "nullable": 0}
        unmapped: List[str] = []
        data_blocks: List[str] = []

        def walk(node: Any, path: Tuple[str, ...]) -> None:
            kind = self.classify(path, node) if path else "container"
            if kind is None:
                unmapped.append(".".join(path))
                return
            if kind == "data":
                if len(path) == 4:
                    data_blocks.append(".".join(path))
                    counts["data"] += 1
                elif len(path) == 3 and isinstance(node, Mapping):
                    for key, child in node.items():
                        walk(child, path + (str(key),))
                return
            if kind == "container":
                for key, child in node.items():
                    walk(child, path + (str(key),))
                return
            counts[kind] += 1

        if isinstance(payload, Mapping):
            walk(payload, ())
        top = list(payload.keys()) if isinstance(payload, Mapping) else []
        return {
            "schema_version": SCHEMA_VERSION,
            "layout": self.layout(payload) if isinstance(payload, Mapping) else None,
            "fields": counts["field"], "lists": counts["list"], "data_blocks": counts["data"],
            "nullable": counts["nullable"],
            "unmapped": sorted(unmapped),
            "missing_top_level": [k for k in TOP_LEVEL_KEYS if k not in top]
                                 if payload.get("success") is not False else [],
            "removed_sections_present": [k for k in top if k in REMOVED_SECTIONS],
            "matches": not unmapped and not [k for k in top if k in REMOVED_SECTIONS],
        }

    # ---------------------------------------------------------------- introspection
    @classmethod
    def get_all_maps(cls) -> Dict[str, Any]:
        return {
            "schema": {"name": SCHEMA_NAME, "version": SCHEMA_VERSION},
            "fields": {f.code: ".".join(f.path) for f in FIELDS},
            "compact_codes": list(COMPACT_CODES),
            "nullable_containers": {c: ".".join(p) for c, p in NULLABLE_CONTAINERS.items()},
            "lists": list(LIST_PATHS),
            "data_blocks": {g: list(b) for g, b in GROUP_DATA_BLOCKS.items()},
            "strategy_groups": list(STRATEGY_GROUPS),
            "state_readings": dict(STATE_READINGS),
            "veto_checks": list(VETO_CHECKS),
            "final_score_blocks": list(FINAL_SCORE_BLOCKS),
            "removed_sections": list(REMOVED_SECTIONS),
        }
