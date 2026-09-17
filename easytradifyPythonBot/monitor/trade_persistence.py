# ============================================================
# TRADE PERSISTENCE -- MONGODB ONLY
# ============================================================
# FILE: monitor/trade_persistence.py
#
# Every write the monitor makes about a trade -- open, price evolution,
# trailing-stop moves, close, analysis at close -- and every read it uses to
# decide something ("is this trade already closed?") goes to MongoDB, through
# monitor/trade_sink.py. Nothing in this module touches Firebase.
#
# WHY THIS FILE REPLACED firebase_helpers.py
# ------------------------------------------
# The old module's writes to Firestore had long been switched off, but it
# still DEPENDED on Firebase in two ways that mattered:
#
#   1. Every write function opened with `if not firebase_service: return`,
#      placed BEFORE the Mongo write. If Firebase was unreachable, the trade
#      was not saved to Mongo either -- the log said "Firebase not available -
#      trade NOT saved" and the record was lost.
#   2. The monitor's "is this trade already closed?" checks read Firebase,
#      which holds no trades. They never found one, so the duplicate-close
#      guard could not fire and closed trades kept receiving price updates.
#
# And trailing-stop moves were written to Firestore ONLY, so no trade in Mongo
# records how its stop moved.
#
# monitor/firebase_helpers.py remains as a thin shim for callers not yet
# migrated (it forwards to the functions here and ignores the Firebase handle).
# ============================================================

# Console encoding, before anything logs. This module's log lines carry
# emoji; on a Windows cp1252 console writing one raises UnicodeEncodeError
# rather than printing a replacement character. That is not cosmetic -- the
# identical failure silently disabled the GNN for this entire project (the
# ai.ai_gnn import logs a brain emoji, the import raised, and a broad
# `except Exception` reported it as 'GNN initialization failed'), and it
# ended every replay run with a traceback after the work was finished.
# In a live monitor the same line would take the process down mid-session.
try:
    import core.console_safe  # noqa: F401
except Exception:
    pass

import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Mapping

# Shared with monitor/monitor_core.py and api/execute_copy_trade.py --
# see core/broker_facts.py for why this is not reimplemented per caller.
from core.broker_facts import profit_from_prices
import numpy as np
import math
import MetaTrader5 as mt5
from core.broker_facts import (risk_reward_ratio, spread_now_pips,
                               spread_at_pips, exit_slippage_pips,
                               close_moment, closing_deal, risk_usd_at_stop)

from core.asset_analysis import analyze_institutional_signal
from core.execution import get_trade_history
# ============================================================
# ✅ NEW: PRICE EVOLUTION ENCODER IMPORTS
# ============================================================
try:
    from ai.price_evolution_encoder import PriceEvolutionEncoder
    from ai.price_evolution_decoder import PriceEvolutionDecoder
    from ai.price_evolution_bridge import PriceEvolutionBridge
except ImportError:
    PriceEvolutionEncoder = None
    PriceEvolutionDecoder = None
    PriceEvolutionBridge = None
    print("⚠️ Price evolution encoder not available")

logger = logging.getLogger(__name__)


# ============================================================
# HELPER: PRINT WITH TIMESTAMP
# ============================================================

def _print(*args):
    """Print with timestamp directly to console"""
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}]", *args)


def _bump(stats: Optional[Dict[str, Any]], key: str) -> None:
    """Increment a caller-owned counter, if the caller passed a stats dict."""
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def _normalise_direction(value) -> Optional[str]:
    """"BUY"/"SELL" from whatever a caller stored, or None if it is neither."""
    text = str(value or "").strip().upper()
    return text if text in ("BUY", "SELL") else None


def _direction_of_record(ticket, existing_trade=None) -> Optional[str]:
    """
    Which way the trade was actually placed, from the record written at open.

    Checked in order of authority:
      1. the document already in hand (saves a round trip),
      2. MongoDB, which is where trades actually live now
         (the only trade store),
      3. None.

    Returns None rather than guessing. Callers must not substitute a default:
    a wrong direction silently inverts the sign of the trade's return, and
    that is exactly the defect this function exists to prevent.
    """
    for source in (existing_trade,):
        if isinstance(source, Mapping):
            found = _normalise_direction(
                source.get("order_type") or source.get("direction"))
            if found:
                return found

    try:
        from monitor.trade_sink import is_enabled
        if not is_enabled():
            return None
        from core.mongo import get_trades_service
        doc = get_trades_service().get_trade(
            ticket, fields=("order_type", "direction"))
        return _normalise_direction(doc.get("order_type") or doc.get("direction"))
    except Exception as exc:
        logger.debug("direction lookup failed for %s: %s", ticket, exc)
        return None


# ============================================================
# ✅ ENCODER INSTANCE (Singleton)
# ============================================================

_PRICE_ENCODER = None
_PRICE_DECODER = None
_PRICE_BRIDGE = None

def _get_encoder():
    global _PRICE_ENCODER
    if _PRICE_ENCODER is None and PriceEvolutionEncoder is not None:
        _PRICE_ENCODER = PriceEvolutionEncoder()
    return _PRICE_ENCODER

def _get_decoder():
    global _PRICE_DECODER
    if _PRICE_DECODER is None and PriceEvolutionDecoder is not None:
        _PRICE_DECODER = PriceEvolutionDecoder()
    return _PRICE_DECODER

def _get_bridge():
    global _PRICE_BRIDGE
    if _PRICE_BRIDGE is None and PriceEvolutionBridge is not None:
        _PRICE_BRIDGE = PriceEvolutionBridge()
    return _PRICE_BRIDGE


# ============================================================
# ✅ GET FULL RAW ANALYSIS FOR ALL TIMEFRAMES (FOR OPEN/CLOSE)
# ============================================================

def get_all_timeframe_analysis_raw(
    symbol: str,
    order_type: str,
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    symbol_mt5_map: Dict[str, str]
) -> Dict[str, Any]:
    """
    Get FULL RAW analyze_institutional_signal results for M1, M5, and H1 timeframes.
    Returns COMPLETE objects WITHOUT ANY EXTRACTION.
    Used for OPEN and CLOSE analysis (stored once each).
    """
    mt5_symbol = symbol_mt5_map.get(symbol, symbol)

    # ✅ M1 ONLY -- and that means NOT COMPUTING the others either.
    #
    # This used to run analyze_institutional_signal THREE times (M1, M5, H1)
    # on every call. Under STORE_M1_ONLY the M5 and H1 results were then
    # discarded, so two thirds of the most expensive call in the system was
    # pure waste -- paid once per minute per open position, on the same
    # thread that has to keep up with the market.
    #
    # The m5/h1 keys are still returned, empty, so callers that index them do
    # not need changing and an absent analysis reads as absent rather than
    # stale.
    result = {"m1": {}, "m5": {}, "h1": {}}

    try:
        m1_result = analyze_institutional_signal(
            symbol=mt5_symbol,
            order_type=order_type,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            timeframe="M1",
            debug=False
        )
        result["m1"] = m1_result if m1_result.get("success", False) else {}
    except Exception as e:
        _print(f"⚠️ M1 analysis error: {e}")

    return result


# ============================================================
# ✅ GET ENCODED ANALYSIS FOR PRICE EVOLUTION
# ============================================================

def get_all_timeframe_analysis_encoded(
    symbol: str,
    order_type: str,
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    symbol_mt5_map: Dict[str, str]
) -> Dict[str, Any]:
    """
    Get FULL RAW analyze_institutional_signal results for M1, M5, and H1 timeframes.
    Returns ENCODED objects for price evolution (400B instead of 18KB).
    """
    mt5_symbol = symbol_mt5_map.get(symbol, symbol)
    encoder = _get_encoder()

    result = {
        "m1": {},
        "m5": {},
        "h1": {}
    }

    if encoder is None:
        # Fallback: store raw data
        _print("⚠️ Encoder not available - using raw data for price evolution")
        return get_all_timeframe_analysis_raw(
            symbol, order_type, fixed_trade_size_usd, risk_per_trade, symbol_mt5_map
        )

    # M1 Analysis - FULL RAW then ENCODE
    try:
        m1_result = analyze_institutional_signal(
            symbol=mt5_symbol,
            order_type=order_type,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            timeframe="M1",
            debug=False
        )
        if m1_result.get("success", False):
            result["m1"] = encoder.encode(m1_result)
    except Exception as e:
        _print(f"⚠️ M1 analysis error: {e}")

    # ✅ M1 ONLY -- see STORE_M1_ONLY. The M5 and H1 passes were removed:
    # they ran the most expensive call in the system twice more per
    # point and the results were then discarded unstored.


    return result


# ============================================================
# ✅ HELPER: GET DOC_ID
# ============================================================

# ============================================================
# ✅ AUDIT SLICE — 360° COVERAGE, QUERYABLE
# ============================================================
# What gets stored in MongoDB for every analysis, at open (m1_audit) and on
# the raw-fallback price points.
#
# WHY NOT THE ENCODED BLOB
#   An encoded blob cannot be queried, grouped or compared without decoding.
#
# WHY NOT THE FULL RAW RESULT
#   ~40KB per analysis, most of it intermediate values no audit groups by.
#   The raw result is stored once, beside this, in m1_analysis_raw.
#
# WHAT THIS COVERS
#   Every subsystem capable of blocking or shaping a trade:
#
#     decision      direction, probability + the ledger that built it
#     strategy      the strategy groups the probability is now made from
#     direction     analysed vs traded side, trend-cascade flip
#     vetos         triggered, reason, per-check, enforced vs advisory
#     zone          grade, level, quality breakdown, touches, distance
#     discount      quality, score, buffer used, distance
#     entry         status, quality, stars, timing
#     confluence    every *_final_score block in the chain
#     indicators    each family's recommendation (+ confidence when published)
#     vwap / squeeze / liquidity / rvam   value, compression, sweeps, participation
#     regime        ATR, volatility verdicts, range source, trend, session
#
# SCHEMA 2 (2026-09-17). The detectors now live under analysis.<GROUP>.data
# (core/analysis_groups.reshape), and schema 1 read vwap, ttm_squeeze,
# liquidity_events, rvam, trend_analysis and session_analysis at the top level
# -- every one of those fields was null on every trade, while the values sat
# one level down. Readers go through core.analysis_groups.block() now, which
# finds a block in the grouped or the flat layout. Removed because their source
# no longer exists anywhere in the payload: `gates` (decision_snapshot, deleted
# 2026-09-15), `coherence` (validator deleted 2026-09-15), zone.quality_grade /
# position_cost_grades / position_pct and liquidity.aligned. A key that can
# never be filled reads as "measured, nothing there", which is worse than no key.
#
# Roughly 9KB, most of it the probability ledger; stored once per trade at open
# (and on price points only when the encoder is unavailable). The rule for inclusion: could this field ever be the answer to
# "why did that trade lose"? If yes it is here, because a gap in the audit is
# indistinguishable from a component that works.
AUDIT_SCHEMA_VERSION = 2


def _audit_slice(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a full analysis result to its audit-relevant fields."""
    if not isinstance(analysis, dict) or not analysis:
        return {}

    from core.analysis_groups import block as _group_block

    def pick(node, *path):
        for k in path:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        return node

    fv = analysis.get("final_verdict") or {}
    entry = analysis.get("entry_analysis") or {}
    vetos = analysis.get("vetos") or {}
    groups = analysis.get("strategy_groups") or {}
    direction = analysis.get("direction_decision") or {}
    ind = _group_block(analysis, "indicators")
    sd = ind.get("supply_demand") or {}
    sd_debug = sd.get("debug") or {}
    trend = ind.get("trend") or {}
    vol = _group_block(analysis, "volatility_protection")
    session = _group_block(analysis, "session_analysis")
    vwap = _group_block(analysis, "vwap")
    vwap_context = _group_block(analysis, "vwap_context")
    squeeze = _group_block(analysis, "ttm_squeeze")
    squeeze_setup = _group_block(analysis, "ttm_squeeze_setup")
    liquidity = _group_block(analysis, "liquidity_events")
    rvam = _group_block(analysis, "rvam")

    # Every confluence block, whole but flat: the blocks do not share field
    # names (gnn publishes gnn_contribution, trend_cascade publishes
    # adjustment, gap_slippage a penalty), so a fixed trio of keys was null
    # for most of them.
    chain = {}
    for k, v in fv.items():
        if k.endswith("_final_score") and isinstance(v, dict):
            chain[k.replace("_final_score", "")] = {
                field: value for field, value in v.items()
                if not isinstance(value, (dict, list))}

    # Each indicator's verdict. Recommendation, never the raw score -- score
    # sign conventions differ between scorers. Confidence only where the
    # indicator publishes one.
    indicators = {}
    for name, blk in ind.items():
        if isinstance(blk, dict) and blk.get("recommendation") is not None:
            indicators[name] = {"recommendation": blk.get("recommendation")}
            if "confidence" in blk:
                indicators[name]["confidence"] = blk.get("confidence")

    is_demand = sd_debug.get("is_demand_zone")
    if isinstance(is_demand, bool):
        zone_type = "DEMAND" if is_demand else "SUPPLY"
    else:
        zone_type = (entry.get("discount") or {}).get("zone_type")

    return {
        "schema": AUDIT_SCHEMA_VERSION,
        "timeframe": pick(analysis, "config", "timeframe"),

        "decision": {
            "direction": fv.get("best_direction"),
            "probability": fv.get("probability_percent"),
            "probability_post_chain": fv.get("probability_percent_post_chain"),
            "probability_ledger": fv.get("probability_ledger"),
            "buy_probability": fv.get("probability_buy"),
            "sell_probability": fv.get("probability_sell"),
            "directional_vetoes": fv.get("directional_vetoes"),
        },

        "strategy": {
            "winner": groups.get("winner"),
            "best_score": groups.get("best_score"),
            "final_probability": groups.get("final_probability"),
            "contested": groups.get("contested"),
            "most_opposed": groups.get("most_opposed"),
            "opposition": groups.get("opposition"),
            "groups_scored": groups.get("groups_scored"),
            "cost_r": pick(groups, "cost", "cost_r"),
            "calibrated_probability": pick(groups, "calibrated", "probability"),
            "groups": {
                name: {"score": g.get("score"), "scored": g.get("scored")}
                for name, g in (groups.get("groups") or {}).items() if isinstance(g, dict)
            },
        },

        "direction": {
            "analysed": direction.get("analysis_direction"),
            "traded": direction.get("traded_direction"),
            "flipped_by_trend_cascade": direction.get("flipped_by_trend_cascade"),
            "cascade_direction": direction.get("cascade_direction"),
            "cascade_score": direction.get("cascade_score"),
        },

        "vetos": {
            "triggered": vetos.get("triggered"),
            "reason": vetos.get("reason"),
            "checks": vetos.get("checks"),
            "advisory_only": vetos.get("advisory_only"),
            "effective_thresholds": vetos.get("effective_thresholds"),
        },

        "zone": {
            "type": zone_type,
            "grade": sd.get("zone_grade"),
            "level": sd.get("zone_level"),
            "is_at_zone": sd.get("is_at_zone"),
            "quality_breakdown": sd_debug.get("quality_breakdown"),
            "touch_count": sd_debug.get("touch_count"),
            "distance_pips": sd_debug.get("distance_to_zone_pips"),
        },

        "discount": {
            "quality": (entry.get("discount") or {}).get("discount_quality"),
            "score": (entry.get("discount") or {}).get("discount_score"),
            "distance_pips": (entry.get("discount") or {}).get("distance_pips"),
            "buffer_pips_used": pick(entry, "discount", "debug", "buffer_pips_used"),
        },

        "entry": {
            "status": entry.get("entry_status"),
            "quality": entry.get("entry_quality"),
            "star_rating": entry.get("star_rating"),
            "timing_confidence": entry.get("timing_confidence"),
            "timing_ready": entry.get("timing_ready"),
            "should_enter": entry.get("should_enter"),
            # the entry rule table: which rules held, and which blocked
            "rules_passed": {name: (r or {}).get("passed")
                             for name, r in (entry.get("rules") or {}).items()},
            "blocked_by": entry.get("blocked_by"),
        },

        "confluence_chain": chain,

        # Value context and the liquidity picture: "do trades taken 2+ sigma
        # from VWAP lose more" and "do sweep-aligned entries win more".
        "vwap": {
            "deviation_sigma": vwap.get("deviation_sigma"),
            "zone": vwap.get("zone"),
            "sigma_pips": vwap.get("sigma_pips"),
            "stance": vwap_context.get("stance"),
            "score": vwap_context.get("score"),
        },
        "squeeze": {
            "state": squeeze.get("state"),
            "duration_bars": squeeze.get("duration_bars"),
            "momentum_direction": squeeze.get("momentum_direction"),
            "setup": squeeze_setup.get("setup"),
            "score": squeeze_setup.get("score"),
        },
        "liquidity": {
            "available": liquidity.get("available"),
            "event_count": liquidity.get("event_count"),
            "bias": liquidity.get("bias"),
        },

        # Effort vs result: "do UNPARTICIPATED entries lose more often".
        "rvam": {
            "classification": rvam.get("classification"),
            "return_z": rvam.get("return_z"),
            "volume_ratio": rvam.get("volume_ratio"),
            "direction": rvam.get("direction"),
        },
        "indicators": indicators,

        "regime": {
            "atr_pips": vol.get("atr_pips"),
            "range_source": vol.get("range_source"),
            "volatility_level": vol.get("volatility_level"),
            "volatility_verdicts": vol.get("volatility_verdicts"),
            "confidence_penalty": vol.get("confidence_penalty"),
            "trend": trend.get("trend"),
            "adx": pick(trend, "adx", "adx_14"),
            "session_state": session.get("session_close_state"),
            "calendar_degraded": session.get("calendar_degraded"),
        },
    }


def _engine_stamp() -> Dict[str, Any]:
    """Which engine produced this record (strategic_plan_v5_live_data.md rule 2:
    records from different engines are compared, never pooled). Never raises."""
    try:
        from core.engine_version import register, short_stamp
        register()
        return short_stamp()
    except Exception as exc:
        return {"error": str(exc)}


def _get_doc_id(ticket: int) -> str:
    """The canonical trade_id, "trade_{ticket}", used for every stored trade."""
    return f"trade_{ticket}"


# ============================================================
# IS THIS TRADE ALREADY CLOSED?  (MongoDB)
# ============================================================

def is_trade_closed(ticket: int) -> bool:
    """Whether the stored record says this trade is closed.

    Used to stop recording price evolution on a closed trade and to avoid
    re-processing a close. It used to ask Firebase, which holds no trades, so it
    always answered False.

    Reads as closed on status CLOSED, or on a recorded non-zero close price for
    records written before `status` was reliable. An unreachable store reads as
    "not closed", which fails open: the monitor keeps recording rather than
    dropping data it cannot confirm is redundant.
    """
    from monitor.trade_sink import get_trade_record

    record = get_trade_record(ticket)
    if not record:
        return False
    if str(record.get("status") or "").upper() == "CLOSED":
        return True
    close = record.get("close_data") or {}
    try:
        return float(close.get("close_price") or 0) != 0
    except (TypeError, ValueError):
        return False

# ============================================================
# JSON SAFE CONVERSION
# ============================================================

def make_json_safe(obj: Any) -> Any:
    """Convert numpy types and other non-JSON objects to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
        return obj
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {make_json_safe(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_safe(item) for item in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

# ============================================================
# TRADE OPEN - SAVE TO MONGODB
# ============================================================






def _micro_snapshot(symbol, pip_size, direction):
    """
    A compact order-flow reading for one price point.

    Deliberately SMALL. The full microstructure payload is ~1.9KB and a trade
    writes ~180 points, which would add 340KB per trade for data that is
    mostly redundant minute to minute. Only the cross-window summaries are
    kept -- imbalance, acceleration, spread stress -- which are the fields
    that actually moved the outcome in testing.

    Never raises: a telemetry failure must not stop a price point being
    recorded, and a missing reading is reported as unavailable rather than as
    a zero that would read like a real measurement of "no flow".
    """
    try:
        from core.microstructure_features import analyse, directional_bias
        feats = analyse(symbol, pip_size, lookback_seconds=300,
                        windows=(30, 300))
        if not feats.get("available"):
            return {"available": False, "reason": feats.get("reason")}
        bias = directional_bias(feats, direction)
        return {
            "available": True,
            "ticks": feats.get("tick_count"),
            "flow_with_trade_short": bias.get("flow_with_trade_short"),
            "flow_with_trade_long": bias.get("flow_with_trade_long"),
            "flow_supports_trade": bias.get("flow_supports_trade"),
            "flow_opposes_trade": bias.get("flow_opposes_trade"),
            "intensity_acceleration": feats.get("intensity_acceleration"),
            "spread_stress": feats.get("spread_stress"),
        }
    except Exception as exc:
        return {"available": False, "reason": "snapshot failed: %s" % exc}


# ============================================================
# RISK STATE ON EVERY PRICE POINT
# ============================================================
#
# A price point recorded price, profit and the analysis -- and nothing about
# where the STOP was at that moment. Break-even and trailing both MOVE the
# stop while a trade is open, so without this the forward walk cannot answer
# the first question any losing trade raises: was the stop where it started,
# or had it been pulled to entry and then clipped by noise?
#
# The live sl/tp on the MT5 position are ground truth -- they already reflect
# every break-even and trailing modification, whoever made it -- so they are
# recorded directly rather than inferred from the management config. The
# derived flags say what MOVED, which is what a reader actually wants.
def _risk_state(ticket, position, entry_price, pip_size, initial_sl=None):
    """Stop/target state at this instant, plus break-even and trailing flags."""
    state = {
        "sl": position.get("sl"),
        "tp": position.get("tp"),
        "initial_sl": initial_sl,
    }

    try:
        from core.execution import get_break_even_status, _active_trails
        be = get_break_even_status(ticket) or {}
        state["break_even_enabled"] = bool(be.get("has_break_even"))
        state["break_even_applied"] = bool(be.get("break_even_applied"))
        state["break_even_price"] = be.get("break_even_price")
        state["break_even_trigger"] = be.get("break_even_trigger")
        state["break_even_trigger_type"] = be.get("break_even_trigger_type")
        state["trailing_active"] = ticket in _active_trails
    except Exception:
        # Telemetry must never break the write it is attached to.
        state.setdefault("break_even_enabled", None)
        state.setdefault("trailing_active", None)

    sl = state.get("sl")
    try:
        if sl and entry_price and pip_size:
            # Positive = the stop sits on the profitable side of entry, which
            # is what "at break-even or better" means for either direction.
            is_buy = position.get("type") == 0
            state["sl_distance_from_entry_pips"] = round(
                ((sl - entry_price) if is_buy else (entry_price - sl)) / pip_size, 1)
            state["sl_at_or_beyond_breakeven"] = bool(
                sl >= entry_price if is_buy else sl <= entry_price)
        if sl and initial_sl and pip_size:
            state["sl_moved_pips"] = round(abs(sl - initial_sl) / pip_size, 1)
    except Exception:
        pass

    return state



# ============================================================
# TRADES LIVE IN MONGODB. FIRESTORE NO LONGER STORES THEM.
# ============================================================
# Trades are written ONLY to MongoDB. Firestore keeps everything else it
# owns (portfolio_config, ai_models) and stops receiving trade documents.
#
# Why the switch: a Firestore document is capped at 1 MiB and a trade with a
# full forward walk is several megabytes, so price_evolution had to become a
# subcollection there, appends were read-modify-write (quadratic), and every
# analytical query needed its own composite index. Mongo's 16 MB limit holds
# a whole trade as one document with price_evolution as a plain array, which
# is the shape every model already expects.
#
# THE TRADE-OFF, STATED PLAINLY: this removes the fallback. With the dual
# write, a Mongo outage still left a complete record in Firestore. Now, if
# Mongo is unavailable when a trade opens, that trade has NO record anywhere.
# monitor/trade_sink.py counts failures and get_status() reports `degraded`,
# so the loss is visible rather than silent -- but it is a real loss, and the
# counters are worth checking after any database interruption.
# Firestore writes have been removed from this module entirely; there is no
# longer a flag to turn them back on.


# ============================================================
# STORE_M1_ONLY -- ONE TIMEFRAME, EVERYWHERE
# ============================================================
#
# analysis_at_open, analysis_at_close and every price_evolution point store
# the M1 analysis and nothing else. No M5, no H1, in any field.
#
# This costs far less context than it appears to. `analyze_institutional_
# signal` is not a single-timeframe function: its M1 payload already carries
# `higher_timeframe`, the `h1_alignment` chain step, and `trend_cascade`,
# which itself reads M5/M15/H1/H4. The separate m5/h1 payloads were the SAME
# analysis re-run at another resolution, not the only source of higher-
# timeframe information.
#
# What it buys is decisive. Measured on live data, a 3-timeframe point was
# ~58KB against ~20KB for M1 alone, and analysis_at_open was 356KB. A trade
# holding ~180 points went from ~10.8MB to ~3.6MB, and the trade document
# itself drops well clear of Firestore's 1 MiB ceiling.
#
# Readers that ask for analysis["m5"] / ["h1"] get nothing, deliberately --
# an absent key is honest, where a stale copy would not be.
# ============================================================

def _resolve_close_reason(ticket):
    """DEAL_REASON-backed close reason; UNKNOWN if MT5 cannot be reached."""
    try:
        from core.execution import resolve_close_reason
        return resolve_close_reason(ticket)
    except Exception:
        return "UNKNOWN"


def _account_at_open(analysis_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The MT5 account this trade was actually placed on.

    WHY THIS IS RECORDED
    --------------------
    Trades are placed from three different MT5 accounts at 1:200, 1:300 and
    1:500 leverage, and leverage changes the result: sizing is margin-first, so
    at a fixed $200 margin a higher leverage buys a larger lot, and holding the
    dollar risk then forces a TIGHTER stop -- which noise reaches more often.
    Pooling the accounts without this field averages three different trading
    conditions into one number.

    Before this, leverage survived only deep inside the analysis snapshot
    (`analysis_at_open.m1_analysis_raw.account_info.leverage`), which list
    queries exclude as a heavy field and which nothing could index or sort on.

    Read live from MT5 at open, so it is the account in use, not a config
    default. Falls back to the analysis snapshot, and returns None rather than
    guessing -- a wrong leverage would misfile the trade into the wrong bucket.
    """
    account: Dict[str, Any] = {"login": None, "server": None, "leverage": None,
                               "currency": None, "company": None}
    try:
        info = mt5.account_info()
        if info is not None:
            account.update({
                "login": getattr(info, "login", None),
                "server": getattr(info, "server", None),
                "leverage": getattr(info, "leverage", None),
                "currency": getattr(info, "currency", None),
                "company": getattr(info, "company", None),
            })
    except Exception as exc:  # recording, never worth failing the save
        logger.warning(f"[account] mt5.account_info() failed: {exc}")

    if account["leverage"] is None and analysis_data:
        fallback = (((analysis_data.get("m1_analysis_raw") or {})
                     .get("account_info") or {}).get("leverage"))
        if fallback is not None:
            account["leverage"] = fallback

    try:
        account["leverage"] = int(account["leverage"]) if account["leverage"] is not None else None
    except (TypeError, ValueError):
        account["leverage"] = None

    return account


def save_trade_open(
    trade_result,
    analysis_result: Dict[str, Any],
    symbol_mt5_map: Dict[str, str],
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    stats: Dict[str, Any]
) -> bool:
    """
    Save trade open data to MongoDB with the M1 analysis snapshot.
    ✅ Uses consistent doc_id format: "trade_{ticket}"
    """
    if not trade_result.success:
        return False

    try:
        ticket = trade_result.ticket
        if not ticket:
            return False

        doc_id = _get_doc_id(ticket)  # ✅ "trade_{ticket}"

        _print(f"💾 Saving trade to MongoDB: {doc_id} ({trade_result.symbol})")

        # DIRECTION: what was actually sent to the broker wins.
        #
        # This used to read ONLY `analysis_result["config"]["executed_direction"]`
        # with a hardcoded "BUY" default. `executed_direction` is produced by
        # core/asset_analysis.py, so it exists on the monitor's path and NOT on
        # the copy-trade path, which calls this with analysis_result={} on
        # purpose to keep the open-save fast. Every copy-trade SELL was
        # therefore recorded as a BUY.
        #
        # And it was not merely a wrong label: `order_type` is passed straight
        # into get_all_timeframe_analysis_raw() below, so analysis_at_open --
        # the feature set every model reads -- was computed for the OPPOSITE
        # side of the trade that was actually open.
        #
        # trade_result.order_type is the direction the order was placed with,
        # which is the only fact of record here; the analysis config is a
        # fallback for callers that do not set it.
        config_data = analysis_result.get("config", {})
        order_type = str(
            getattr(trade_result, "order_type", None)
            or config_data.get("executed_direction")
            or "BUY"
        ).upper()
        if order_type not in ("BUY", "SELL"):
            _print(f"⚠️ Unrecognised order_type {order_type!r} for ticket {ticket} "
                   f"- refusing to guess a direction")
            return False

        # Get FULL RAW analysis for all timeframes
        timeframe_analysis = get_all_timeframe_analysis_raw(
            symbol=trade_result.symbol,
            order_type=order_type,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            symbol_mt5_map=symbol_mt5_map
        )

        # Read once: it is a round trip to the MT5 terminal.
        _account = _account_at_open(trade_result.analysis_data)

        # Entry spread, most exact source first:
        #   order_tick -- the quote execute_trade priced the order with
        #   live_tick  -- a quote read now, moments after the fill
        #   analysis   -- the snapshot taken seconds before the order
        # The source is stored beside the value, because a cost study should
        # be able to exclude the approximate ones.
        _exec = trade_result.full_execution_response or {}
        _mt5_sym = (symbol_mt5_map or {}).get(trade_result.symbol, trade_result.symbol)
        _entry_spread, _entry_spread_source = _exec.get("spread_pips"), "order_tick"
        if _entry_spread is None:
            _entry_spread, _entry_spread_source = spread_now_pips(_mt5_sym), "live_tick"
        if _entry_spread is None:
            _entry_spread = ((((trade_result.analysis_data or {}).get("m1_analysis_raw") or {})
                              .get("entry_details") or {}).get("spread_pips"))
            _entry_spread_source = "analysis"
        if _entry_spread is None:
            _entry_spread_source = None

        # Build trade_data
        trade_data = {
            "ticket": ticket,
            "symbol": trade_result.symbol,
            "order_type": order_type,
            # Same value under the name the storage schema and the AI layer
            # use (core/mongo/trades_service.py lists "direction"; the models
            # read trade["direction"]). Written at open so the close path has
            # an authoritative direction to look up instead of inferring one.
            "direction": order_type,

            # ------------------------------------------------------------
            # THE SHAPE THE MODELS ACTUALLY READ
            # ------------------------------------------------------------
            # ai/trade_repository.py:_r_multiple, ai/edge_discovery.py,
            # ai/strategy_families.py and ai/component_audit_360.py all do:
            #
            #     entry = trade.get("entry") or {}
            #     ep, sl = entry.get("price"), entry.get("stop_loss")
            #     if not all(isinstance(v, (int, float)) ...): skip this trade
            #
            # This writer only ever emitted the flat `price`/`stop_loss`
            # below, so `entry` was absent, every live trade returned R=None,
            # and every model silently skipped it -- a trade recorded and
            # invisible, which is the most expensive kind of missing data
            # because the collection looks like it is working. Measured:
            # R computable on 220/250 history trades, 0/2 live ones.
            #
            # ai/mt5_history.to_trade() is the canonical shape and this
            # mirrors it. The flat keys stay for the API controllers and the
            # close path, which already read them.
            "entry": {
                "price": trade_result.entry_price,
                "volume": trade_result.volume,
                "stop_loss": trade_result.stop_loss,
                "take_profit": trade_result.take_profit,
            },
            # The chronological key. It is the default sort in
            # core/mongo/trades_service.py and carries its own index, and
            # every walk-forward split orders on it -- but nothing wrote it,
            # so a chronological split over live trades had nothing to sort
            # by. `closed_at` is already set by the close path.
            "opened_at": trade_result.timestamp,

            # Top-level so it can be indexed, filtered and sorted, and shows in
            # list responses (which exclude the analysis block). See
            # _account_at_open for why leverage matters to the result.
            "leverage": _account["leverage"],
            "account": _account,

            "price": trade_result.entry_price,
            "volume": trade_result.volume,
            "stop_loss": trade_result.stop_loss,
            "take_profit": trade_result.take_profit,
            "take_profit_2": trade_result.take_profit_2,
            "take_profit_3": trade_result.take_profit_3,
            "actual_margin": trade_result.actual_margin,
            "actual_risk_usd": trade_result.actual_risk_usd,
            # The broker's own figure for the loss at the stop (ex commission).
            # Net R is booked profit over this; actual_risk_usd understates it.
            "risk_usd_at_stop": risk_usd_at_stop(
                (symbol_mt5_map or {}).get(trade_result.symbol, trade_result.symbol),
                trade_result.order_type, trade_result.volume,
                trade_result.entry_price, trade_result.stop_loss),
            "risk_percent_used": trade_result.risk_percent_used,
            "magic": trade_result.magic,
            "comment": trade_result.comment,
            "probability_of_hit_percent": trade_result.probability_of_hit_percent,
            # Computed from the EXECUTED entry/stop/target. TradeResult has a
            # risk_reward_ratio field, but nothing ever assigned it, so this
            # was None on every stored trade. See broker_facts.risk_reward_ratio
            # for why the analysis snapshot's own ratio is not used.
            "risk_reward_ratio": (
                trade_result.risk_reward_ratio
                if trade_result.risk_reward_ratio is not None
                else risk_reward_ratio(trade_result.entry_price,
                                       trade_result.stop_loss,
                                       trade_result.take_profit)),
            "confidence": trade_result.analysis_data.get("confidence", 0) if trade_result.analysis_data else 0,
            "spread_at_entry": _entry_spread,
            "spread_at_entry_source": _entry_spread_source,
            "engine": _engine_stamp(),
        }

        # Trailing stop config
        trailing_config = trade_result.full_execution_response.get("trailing_stop", {}) if trade_result.full_execution_response else {}
        trailing_stop_data = {
            "enabled": trailing_config.get("enabled", False),
            "step_pips": trailing_config.get("step_pips", 5),
            "activated": False,
            "status": "INACTIVE"
        }

        # ============================================================
        # ✅ FIXED: analysis_at_open is stored as THREE SEPARATE, FULL
        # timeframe analyses -- never encoded, never trimmed.
        #
        # What it used to do: when the encoder was importable (which is the
        # normal case) it took the ENCODED branch and produced
        #     {"analysis": {"m1": <400B blob>, "m5": ..., "h1": ...}}
        # with no `m1_analysis_raw` key at all. firebase_service.
        # _extract_analysis_data() only hoists the per-timeframe fields when
        # `m1_analysis_raw` is present, so it hoisted nothing and wrapped the
        # whole object one level deeper as `full_raw_analysis`. The result in
        # Firestore was
        #     analysis_at_open.full_raw_analysis.analysis.{m1,m5,h1}  (encoded)
        # -- three levels down, compressed, with no final_verdict,
        # probability_ledger or best_direction reachable anywhere. Every model
        # that reads analysis_at_open saw an empty snapshot.
        #
        # Why RAW here and ENCODED for price_evolution: the encoder exists
        # because a trade has ~200 evolution points at ~18KB each, which does
        # not fit a 1 MiB Firestore document. analysis_at_open happens ONCE
        # per trade. Three full timeframes cost ~54KB, well inside the limit,
        # and this is the single most-read object in the whole system -- the
        # decision snapshot. Compressing it saved nothing that mattered and
        # cost the fields the analysis exists to record.
        #
        # m5/h1 are stored IN FULL rather than through _audit_slice(): the
        # slice exists to keep repeated evolution points small, and there is
        # exactly one analysis_at_open per trade.
        # ============================================================
        m1_full = timeframe_analysis.get("m1", {}) or {}

        full_analysis = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # ✅ M1 ONLY -- see STORE_M1_ONLY at the top of this module.
            "m1_analysis_raw": m1_full,
            "m1_audit": _audit_slice(m1_full),
            "_encoded": False,
            "_audit_schema": AUDIT_SCHEMA_VERSION,
            "trailing_stop": trailing_stop_data,
            # Top-level summary fields for quick access / dashboards.
            "⭐ CONFIDENCE": m1_full.get("⭐ CONFIDENCE", "0%"),
            "🎯 FINAL_DECISION": m1_full.get("🎯 FINAL_DECISION", "HOLD"),
            "💰 ENTRY": m1_full.get("💰 ENTRY", 0),
            "🛑 STOP_LOSS": m1_full.get("🛑 STOP_LOSS", 0),
            "🚀 SIMPLE_ACTION": m1_full.get("🚀 SIMPLE_ACTION", "HOLD"),
            "🚀 REASON": m1_full.get("🚀 REASON", ""),
        }

        # ============================================================
        # RESEARCH CHANNELS -- captured at entry, used by nothing yet
        # ============================================================
        # Two measurements the 215-trade history could not settle, recorded
        # now so the forward data can. Neither touches the decision: they are
        # written beside the analysis, never into the probability.
        #
        # microstructure  the only edge candidate that survived every control
        #                 (+0.2646R, positive in 4/4 walk-forward folds, beats
        #                 a 500-shuffle null at p=0.0180). It had to be
        #                 RECONSTRUCTED from tick history for that test;
        #                 recording it natively removes the reconstruction and
        #                 lets the forward test run on clean data.
        #
        # strategy_families  the probability chain SUMS trend-following and
        #                 mean-reversion contributions, and they conflict on
        #                 91.2% of trades -- a buy signal added to a sell
        #                 signal nine times in ten. Per-family scores stored
        #                 separately make the regime question answerable
        #                 (it currently sits at p=0.0775, just short).
        #
        # Both are wrapped so a failure here can never block a trade write.
        try:
            from core.microstructure_features import analyse as _micro, directional_bias
            # `mt5_symbol` was referenced here but never defined in this
            # function -- a NameError on EVERY trade, swallowed by the except
            # below and written as {"available": False, "reason": "capture
            # failed: name 'mt5_symbol' is not defined"}. Because the failure
            # was recorded rather than raised it looked like "no tick data was
            # available", so it went unnoticed while it silently discarded the
            # ONE edge this project confirmed from new information
            # (microstructure order flow, +0.2646R, 4/4 folds, p=0.0180).
            # The broker symbol comes from the map this function is passed.
            _mt5_symbol = (symbol_mt5_map or {}).get(
                trade_result.symbol, trade_result.symbol)
            _info = mt5.symbol_info(_mt5_symbol)
            if _info is not None:
                _pip = _info.point * (10 if _info.digits in (3, 5) else 1)
                _feats = _micro(_mt5_symbol, _pip, lookback_seconds=900)
                full_analysis["microstructure_at_entry"] = _feats
                full_analysis["microstructure_bias"] = directional_bias(
                    _feats, order_type)
            else:
                full_analysis["microstructure_at_entry"] = {
                    "available": False,
                    "reason": f"no symbol_info for {_mt5_symbol}"}
        except Exception as _exc:
            full_analysis["microstructure_at_entry"] = {
                "available": False, "reason": "capture failed: %s" % _exc}

        try:
            from ai.strategy_families import family_scores
            full_analysis["strategy_family_scores"] = family_scores(
                {"analysis_at_open": m1_full, "direction": order_type})
        except Exception as _exc:
            full_analysis["strategy_family_scores"] = {"error": str(_exc)}

        # Subsystems that produce a real directional read and contribute
        # NOTHING to the probability chain, so they have no ledger step and
        # have never been scored against an outcome: volume profile, wyckoff,
        # Elliott waves, the wave lattice, GNN, and the SMC confluence count.
        # Signed against the trade and recorded; contribution is fixed at 0.
        try:
            from core.component_reads import extract as _reads
            full_analysis["component_reads"] = _reads(m1_full, order_type)
        except Exception as _exc:
            full_analysis["component_reads"] = {"error": str(_exc)}


        # Make JSON-safe before saving
        trade_data_safe = make_json_safe(trade_data)
        full_analysis_safe = make_json_safe(full_analysis)

        # MongoDB is the only store. record_open never raises into the loop;
        # its return value says whether the write actually landed, and the
        # log line below reports THAT rather than assuming success.
        from monitor.trade_sink import record_open
        saved = record_open(trade_data_safe, full_analysis_safe)

        _bump(stats, "mongo_saves" if saved else "mongo_errors")

        if saved:
            _print(f"✅ Trade {ticket} saved to MongoDB (trade_id: {doc_id})")
        else:
            _print(f"❌ Trade {ticket} NOT saved to MongoDB -- see trade_sink status")
        return saved

    except Exception as e:
        _bump(stats, "mongo_errors")
        _print(f"❌ Failed to save trade to MongoDB: {e}")
        if stats is not None:
            _bump(stats, "mongo_errors")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TRADE PRICE UPDATE - MONGODB (ENCODED) - UPDATED EVERY 60 SECONDS
# ✅ STORES ENCODED ANALYSIS - 18KB → 400B
# ✅ FIXED: Consistent doc_id "trade_{ticket}"
# ✅ FIXED: Checks if trade is already closed before updating
# ============================================================

def update_trade_price(
    ticket: int,
    position: Dict[str, Any],
    symbol_mt5_map: Dict[str, str],
    fixed_trade_size_usd: float,
    risk_per_trade: float
) -> bool:
    """
    ✅ FIXED: Update trade price with ENCODED M1, M5, H1 analysis.
    Stores COMPLETE analysis using ENCODER.
    Size: 18KB → 400B per point (97.8% reduction)
    Data: 100% preserved (lossless)
    Updates every 60 seconds (1 minute).
    ✅ FIXED: Uses consistent doc_id "trade_{ticket}"
    ✅ FIXED: Checks if trade is already closed before updating
    """
    try:
        # ✅ FIXED: Use consistent doc_id format
        doc_id = _get_doc_id(ticket)

        # Stop recording price evolution once the stored trade is closed.
        if is_trade_closed(ticket):
            _print(f"⏭️ Trade {ticket} already closed - skipping price evolution update")
            return True

        entry_price = position.get("price_open")
        current_price = position.get("price_current")
        profit_usd = position.get("total_profit_usd", 0)
        symbol = position.get("symbol", "")

        if not entry_price or not current_price:
            return False

        if entry_price > 0:
            if position.get("type") == 0:
                profit_percent = (current_price - entry_price) / entry_price * 100
            else:
                profit_percent = (entry_price - current_price) / entry_price * 100
        else:
            profit_percent = 0

        mt5_symbol = symbol_mt5_map.get(symbol, symbol)
        info = mt5.symbol_info(mt5_symbol)
        if info:
            if "XAU" in mt5_symbol.upper() or "GOLD" in mt5_symbol.upper():
                pip_size = 0.01 if info.digits == 2 else 0.1
            elif "XAG" in mt5_symbol.upper() or "SILVER" in mt5_symbol.upper():
                pip_size = 0.001 if info.digits == 3 else 0.01
            elif "JPY" in mt5_symbol.upper():
                pip_size = 0.01
            else:
                pip_to_points = 10 if info.digits in [3, 5] else 1
                pip_size = info.point * pip_to_points
        else:
            pip_size = 0.0001

        distance_pips = abs(current_price - entry_price) / pip_size if pip_size > 0 else 0

        order_type = "BUY" if position.get("type") == 0 else "SELL"

        # ✅ CHANGED: was get_all_timeframe_analysis_encoded().
        #
        # The encoder compressed each timeframe's analysis from ~18KB to
        # ~400B for price_evolution. That was the right trade when this
        # data was write-only. It is the wrong one now that the data is
        # the audit trail: an encoded blob cannot be queried, grouped or
        # compared, so every stored point was unreadable for the purpose
        # it now has to serve.
        #
        # An audit that cannot see its own inputs cannot tell you what is
        # blocking the win rate -- which is the whole reason this data is
        # being kept. Storing raw and filtering to the fields that matter
        # (below) costs a fraction of the 18KB while staying queryable.
        encoded_analysis = get_all_timeframe_analysis_raw(
            symbol=symbol,
            order_type=order_type,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            symbol_mt5_map=symbol_mt5_map
        )

        # ✅ BUILD PRICE POINT WITH ENCODED ANALYSIS
        # Using PriceEvolutionEncoder for 100% encoding
        encoder = _get_encoder()
        if encoder:
            # Prepare payload for encoder
            # The encoder expects a full analysis payload.
            # encoded_analysis is a dict of {m1, m5, h1} results from analyze_institutional_signal

            # Since the encoder expects a single payload, we might need to
            # structure this appropriately, or encode each timeframe.
            # The current structure has m1, m5, h1 analyses separately.

            price_point = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "price": current_price,
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "distance_from_entry_pips": distance_pips,
                # Live tick. An MT5 position has no `spread` attribute, so the
                # old position.get("spread", 0) was 0 on every point ever stored.
                "spread": spread_now_pips(mt5_symbol),
                "volume": position.get("volume", 0),
                # Where the stop/target actually were at this instant,
                # so a break-even or trailing move is visible in the walk.
                "risk_state": _risk_state(ticket, position, entry_price, pip_size),
                # Order flow AS THE TRADE RUNS, not only at entry. This is
                # what makes a dynamic exit possible: entry microstructure
                # says whether to take the trade, but flow TURNING against an
                # open position is the signal to leave it, and no bar-derived
                # field can see that. Measured only -- it changes no decision.
                "microstructure": _micro_snapshot(mt5_symbol, pip_size, order_type),
                # compact=True: scalars + the zlib-compressed full payload.
                # Lossless (decode reconstructs every field) but ~6x smaller
                # per point, because the uncompressed section dicts it used to
                # carry were verbatim duplicates of the compressed payload.
                # A trade writes ~200 of these; the duplication was paid every
                # time and is what put the document over Firestore's limit.
                # ✅ M1 ONLY, everywhere -- see STORE_M1_ONLY.
                "analysis": {
                    "m1": encoder.encode(encoded_analysis.get("m1", {}) or {},
                                         compact=True),
                },
                "_encoded": True,
                "_audit_schema": AUDIT_SCHEMA_VERSION,
                "_tf_included": ["m1"],
                "_engine": _engine_stamp().get("fingerprint"),
            }
        else:
            # Fallback if encoder is not available
            price_point = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "price": current_price,
                "profit_usd": profit_usd,
                "profit_percent": profit_percent,
                "distance_from_entry_pips": distance_pips,
                # Live tick. An MT5 position has no `spread` attribute, so the
                # old position.get("spread", 0) was 0 on every point ever stored.
                "spread": spread_now_pips(mt5_symbol),
                "volume": position.get("volume", 0),
                # Where the stop/target actually were at this instant,
                # so a break-even or trailing move is visible in the walk.
                "risk_state": _risk_state(ticket, position, entry_price, pip_size),
                # Order flow AS THE TRADE RUNS, not only at entry. This is
                # what makes a dynamic exit possible: entry microstructure
                # says whether to take the trade, but flow TURNING against an
                # open position is the signal to leave it, and no bar-derived
                # field can see that. Measured only -- it changes no decision.
                "microstructure": _micro_snapshot(mt5_symbol, pip_size, order_type),
                "m1_analysis": _audit_slice(encoded_analysis.get("m1", {})),
                "_encoded": False,
                "_audit_schema": AUDIT_SCHEMA_VERSION,
                "_engine": _engine_stamp().get("fingerprint"),
            }

        # Make JSON-safe before saving
        price_point_safe = make_json_safe(price_point)

        # ✅ FIXED: was append_to_array(field="price_evolution"), which
        # read-modify-wrote the entire array on every point. With three full
        # timeframe snapshots a point measures ~370KB, so the trade document
        # hit Firestore's 1 MiB ceiling after TWO points and every later
        # append was rejected -- which is why live trades held 1-2 points
        # instead of the ~200 their holding time implies.
        #
        # Each point is now its own document in a subcollection: no array
        # limit, O(1) writes, unbounded points, full snapshots retained.
        from monitor.trade_sink import record_price_point
        ok = record_price_point(ticket, price_point_safe)
        if not ok:
            _print(f"⚠️ price point NOT stored for ticket {ticket}")
            return False

        _print(f"📊 Price evolution updated for {symbol} (ticket: {ticket}) - 60s update")
        _print(f"   ✅ ENCODED: ~400B (was ~18KB) - 97.8% reduction")
        _print(f"   ✅ Document ID: {doc_id}")
        _print(f"   Price: {current_price} | Profit: ${profit_usd:.2f}")

        return True

    except Exception as e:
        _print(f"❌ Price evolution update error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# SAVE ANALYSIS AT CLOSE TO MONGODB
# ✅ FIXED: Consistent doc_id "trade_{ticket}"
# ============================================================

def save_analysis_at_close(
    ticket: int,
    symbol: str,
    order_type: str,
    close_analysis: Dict[str, Any]
) -> bool:
    """
    Save analysis_at_close to MongoDB.
    Stores FULL RAW analysis at the moment of trade close.
    ✅ FIXED: Uses consistent doc_id "trade_{ticket}"
    """
    try:
        # ✅ FIXED: Use consistent doc_id format
        doc_id = _get_doc_id(ticket)

        # Extract profit from close_analysis
        profit_usd = close_analysis.get("profit_usd", 0.0)
        profit_percent = close_analysis.get("profit_percent", 0.0)
        result = close_analysis.get("result", "UNKNOWN")

        # Build analysis_at_close data WITH PROFIT
        analysis_at_close = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "order_type": order_type,
            "profit_usd": profit_usd,
            "profit_percent": profit_percent,
            "result": result,
            "_engine": _engine_stamp().get("fingerprint"),
            # ✅ M1 ONLY -- see STORE_M1_ONLY.
            "m1_analysis_raw": close_analysis.get("m1", {}),
            "⭐ CONFIDENCE": close_analysis.get("m1", {}).get("⭐ CONFIDENCE", "0%"),
            "🎯 FINAL_DECISION": close_analysis.get("m1", {}).get("🎯 FINAL_DECISION", "HOLD"),
            "💰 ENTRY": close_analysis.get("m1", {}).get("💰 ENTRY", 0),
            "🛑 STOP_LOSS": close_analysis.get("m1", {}).get("🛑 STOP_LOSS", 0),
            "🎯 TAKE_PROFIT_1": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_1", 0),
            "🎯 TAKE_PROFIT_2": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_2", 0),
            "🎯 TAKE_PROFIT_3": close_analysis.get("m1", {}).get("🎯 TAKE_PROFIT_3", 0),
            "📊 LOT_SIZE": close_analysis.get("m1", {}).get("📊 LOT_SIZE", 0),
            "💵 RISK_USD": close_analysis.get("m1", {}).get("💵 RISK_USD", 0),
            "📈 REWARD_USD": close_analysis.get("m1", {}).get("📈 REWARD_USD", 0),
            "💰 MARGIN_REQUIRED_USD": close_analysis.get("m1", {}).get("💰 MARGIN_REQUIRED_USD", 0),
            "🚀 SIMPLE_ACTION": close_analysis.get("m1", {}).get("🚀 SIMPLE_ACTION", "HOLD"),
            "🚀 REASON": close_analysis.get("m1", {}).get("🚀 REASON", ""),
            # The analysis publishes no "📈 RISK_REWARD" key, so this was the
            # "1:0" default on every close. The ratio lives in final_verdict
            # (entry_details carries the same display); absent stays None.
            "📈 RISK_REWARD": ((close_analysis.get("m1", {}).get("final_verdict") or {}).get("risk_reward_ratio")
                              or (close_analysis.get("m1", {}).get("entry_details") or {}).get("risk_reward")),
        }

        # Make JSON-safe
        analysis_at_close_safe = make_json_safe(analysis_at_close)

        # record_analysis_at_close ONLY attaches the analysis. The previous
        # code called record_close() with a placeholder close record
        # ({"analysis_at_close_written": True}), which marked the trade CLOSED
        # before the real close data existed.
        from monitor.trade_sink import record_analysis_at_close
        if not record_analysis_at_close(ticket, analysis_at_close_safe):
            _print(f"⚠️ analysis_at_close NOT stored for ticket {ticket}")
            return False

        _print(f"✅ analysis_at_close saved for {symbol} (Ticket: {ticket}) - Profit: ${profit_usd:.2f}")
        _print(f"   ✅ Document ID: {doc_id}")
        return True

    except Exception as e:
        _print(f"❌ Failed to save analysis_at_close: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TRADE CLOSE - SAVE TO MONGODB (WITH analysis_at_close)
# ✅ FIXED: Consistent doc_id "trade_{ticket}"
# ============================================================

def save_trade_close(
    symbol: str,
    ticket: int,
    close_reason: str,
    profit: float,
    price_open: float,
    price_close: float,
    volume: float,
    sl: float,
    tp: float,
    symbol_mt5_map: Dict[str, str],
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    is_webhook: bool = False,
    trailing_stop_history: List[Dict] = None,
    close_analysis: Dict[str, Any] = None
) -> bool:
    """
    ✅ FIXED: Save trade close with ALL data properly populated.
    ✅ NEW: Saves analysis_at_close with profit.
    ✅ FIXED: Uses consistent doc_id "trade_{ticket}"
    """
    try:
        # ✅ FIXED: Use consistent doc_id format
        doc_id = _get_doc_id(ticket)

        # ============================================================
        # LOG THE PROFIT WE RECEIVED
        # ============================================================
        print("=" * 80)
        print(f"💰 SAVE_TRADE_CLOSE CALLED")
        print(f"   Ticket: {ticket}")
        print(f"   Symbol: {symbol}")
        print(f"   Profit received: ${profit:.2f}")
        print(f"   is_webhook: {is_webhook}")
        print(f"   Document ID: {doc_id}")
        print("=" * 80)

        # ============================================================
        # CHECK IF ALREADY CLOSED (MONGODB)
        # ============================================================
        from monitor.trade_sink import get_trade_record
        existing_trade = get_trade_record(ticket)
        if existing_trade:
            existing_close = existing_trade.get("close_data", {})
            existing_close_price = existing_close.get("close_price", 0)
            existing_profit = existing_close.get("profit_usd", 0)

            if existing_close_price != 0:
                print("=" * 80)
                print(f"⚠️ TRADE {ticket} ALREADY CLOSED IN MONGODB - SKIPPING OVERWRITE")
                print(f"   Existing close_price: {existing_close_price}")
                print(f"   Existing profit: ${existing_profit:.2f}")
                print(f"   New close_price: {price_close}")
                print(f"   New profit: ${profit:.2f}")
                print(f"   Source: {'WEBHOOK' if is_webhook else 'FALLBACK'}")
                print("=" * 80)
                return True

        # ============================================================
        # CONVERT TO FLOAT - HANDLE STRINGS FROM WEBHOOK
        # ============================================================
        try:
            profit = float(profit) if profit is not None else 0.0
        except (ValueError, TypeError):
            profit = 0.0
            print(f"⚠️ Invalid profit value, defaulting to 0")

        try:
            price_open = float(price_open) if price_open is not None else 0.0
        except (ValueError, TypeError):
            price_open = 0.0

        try:
            price_close = float(price_close) if price_close is not None else 0.0
        except (ValueError, TypeError):
            price_close = 0.0

        # The broker's closing deal is the authority on the exit price. The EA
        # webhook formatted price_close with `_Digits` -- the digits of the
        # CHART it runs on, not of the traded symbol -- so from a 2-digit chart
        # every FX close arrived as 1.16 / 0.0. 24 of 117 stored closes were
        # rounded that way, which turned their R into +-30 and one into +583.
        #
        # Same for profit: the EA sent its LAST FLOATING P/L snapshot from before
        # the position vanished -- stale and without commission. Against the
        # broker's deals, 3 of 36 stored profits had the wrong SIGN (losses
        # stored as wins) and 11 more the wrong amount. The deal's net
        # (profit + commission + swap) is the result the account actually booked.
        _deal = closing_deal(ticket, retries=2, delay=0.25)
        _profit_source = "reported"
        if _deal and _deal.get("price_close"):
            if price_close and abs(_deal["price_close"] - price_close) > 1e-9:
                print(f"   ⚠️ close price {price_close} replaced by broker deal price "
                      f"{_deal['price_close']}")
            price_close = float(_deal["price_close"])
            if _deal.get("profit") is not None:
                if abs(float(_deal["profit"]) - profit) > 0.005:
                    print(f"   ⚠️ profit {profit:.2f} replaced by broker net {_deal['profit']:.2f}")
                profit = round(float(_deal["profit"]), 2)
                _profit_source = "deal"

        try:
            volume = float(volume) if volume is not None else 0.0
        except (ValueError, TypeError):
            volume = 0.0

        try:
            sl = float(sl) if sl is not None else 0.0
        except (ValueError, TypeError):
            sl = 0.0

        try:
            tp = float(tp) if tp is not None else 0.0
        except (ValueError, TypeError):
            tp = 0.0

        # ============================================================
        # CALCULATE PROFIT IF MISSING
        # ============================================================
        if profit == 0 and price_open > 0 and price_close > 0 and volume > 0:
            # Both branches of the old version were POSITIVE -- it took the
            # absolute price move, so every trade was recorded as a winner
            # whichever way it was placed. And 100000 is the FX contract size.
            # Sign now comes from the recorded direction, scale from the broker.
            mt5_symbol = symbol_mt5_map.get(symbol, symbol) if symbol_mt5_map else symbol
            implied = profit_from_prices(mt5_symbol,
                                         _direction_of_record(ticket, existing_trade),
                                         price_open, price_close, volume)
            if implied is None:
                print(f"⚠️ Cannot compute profit for {symbol} without a known "
                      f"direction and contract size - leaving it unset")
            else:
                profit = implied
                print(f"💰 Calculated profit from prices: ${profit:.2f}")

        # ============================================================
        # VALIDATE DATA
        # ============================================================
        if price_open == 0:
            print(f"   ❌ CRITICAL: price_open is 0!")
        if price_close == 0:
            print(f"   ❌ CRITICAL: price_close is 0!")
        if volume == 0:
            print(f"   ❌ CRITICAL: volume is 0!")

        # ============================================================
        # CALCULATE DERIVED FIELDS
        # ============================================================
        if price_open > 0 and price_close > 0:
            profit_percent = ((price_close - price_open) / price_open) * 100
        else:
            profit_percent = 0.0

        # DIRECTION: looked up, never inferred.
        #
        # This used to be:
        #     order_type = "BUY"
        #     if price_close < price_open: order_type = "SELL"
        #
        # That derives direction from the OUTCOME. It does not record which way
        # the trade was placed -- it records which way the price moved, and then
        # calls it the direction. Two consequences, both silent:
        #   * a BUY that lost was stored as a SELL (observed on ticket
        #     1921284905: a confirmed BUY, stored "SELL"),
        #   * and because direction was chosen to agree with the price move,
        #     every closed trade reads back as a WINNER. Any win rate or R
        #     computed from this field is measuring the inference, not the
        #     trades.
        #
        # The direction of record is the one written at open. If it cannot be
        # found, store None: a missing value is visible to the next reader,
        # a fabricated one is not.
        order_type = _direction_of_record(ticket, existing_trade)
        if order_type is None:
            _print(f"⚠️ No recorded direction for ticket {ticket} - storing null "
                   f"rather than inferring one from the price move")

        is_winning = profit > 0

        # ============================================================
        # SAVE analysis_at_close (if provided or create it)
        # ============================================================
        if close_analysis is None:
            # Create basic close_analysis
            close_analysis = {
                "profit_usd": profit,
                "profit_percent": profit_percent,
                "result": "WIN" if is_winning else "LOSS",
                "order_type": order_type,
                "m1": {},
                "m5": {},
                "h1": {},
            }
        else:
            # Ensure profit is in close_analysis
            close_analysis["profit_usd"] = profit
            close_analysis["profit_percent"] = profit_percent
            close_analysis["result"] = "WIN" if is_winning else "LOSS"
            close_analysis["order_type"] = order_type

        # Save analysis_at_close to MongoDB
        save_analysis_at_close(
            ticket=ticket,
            symbol=symbol,
            order_type=order_type,
            close_analysis=close_analysis
        )

        # ============================================================
        # BUILD CLOSE_DATA - ✅ CRITICAL: profit_usd is explicitly set
        # ============================================================
        # ------------------------------------------------------------
        # EXIT COSTS -- measured, no longer two hardcoded zeros
        # ------------------------------------------------------------
        # Both used to be the literal 0.0 on every trade: a stored claim that
        # every exit happened at zero spread with a perfect fill. A cost study
        # over that data concludes the broker charges nothing on the way out.
        _close_sym = symbol_mt5_map.get(symbol, symbol) if symbol_mt5_map else symbol
        _exit_at = close_moment(ticket)
        _exit_spread = spread_at_pips(_close_sym, _exit_at) if _exit_at else None
        _exit_spread_source = "tick_at_deal" if _exit_spread is not None else None
        if _exit_spread is None:
            _exit_spread = spread_now_pips(_close_sym)
            _exit_spread_source = "tick_at_detection" if _exit_spread is not None else None

        close_data = {
            # An absent reason is UNKNOWN, never a guess. "SL_TP_HIT" as a
            # default asserted that a stop or target was hit on trades that
            # may have been closed manually or by the EA.
            "close_reason": close_reason or "UNKNOWN",
            "close_price": price_close,
            "profit_usd": profit,  # ✅ CRITICAL: This MUST be set
            "profit_source": _profit_source,
            "profit_percent": profit_percent,
            "is_winning": is_winning,
            "exit_spread": _exit_spread,
            "exit_spread_source": _exit_spread_source,
            # Against the stop or target that triggered the close; None for a
            # manual/EA close, which had no requested level to slip from.
            "exit_slippage": exit_slippage_pips(_close_sym, order_type, close_reason,
                                                price_close, sl, tp),
            "order_type": order_type,
            "duration_seconds": 0,
            "price_open": price_open,
            "volume": volume,
            "sl": sl,
            "tp": tp,
        }

        if trailing_stop_history:
            close_data["trailing_stop_history"] = trailing_stop_history
            close_data["trailing_stop_activated"] = len(trailing_stop_history) > 0

        # ============================================================
        # LOG WHAT WE'RE SAVING
        # ============================================================
        print(f"📊 CLOSE_DATA being saved:")
        print(f"   profit_usd: ${close_data['profit_usd']:.2f}")
        print(f"   close_price: {price_close}")
        print(f"   price_open: {price_open}")
        print(f"   Source: {'WEBHOOK' if is_webhook else 'FALLBACK'}")

        # ============================================================
        # BUILD ANALYSIS DATA
        # ============================================================
        analysis_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": "WIN" if is_winning else "LOSS",
            "profit_usd": profit,  # ✅ Also set here
            "profit_percent": profit_percent,
            "duration_seconds": 0,
            "close_reason": close_reason,
            "is_webhook": is_webhook,
        }

        # ============================================================
        # SAVE TO MONGODB
        # ============================================================
        close_data_safe = make_json_safe(close_data)
        analysis_data_safe = make_json_safe(analysis_data)

        # ✅ Verify profit is in the data before saving
        print(f"💾 Saving to MongoDB: profit_usd={close_data_safe.get('profit_usd', 0):.2f}")

        # ✅ FIXED: Use CORRECT doc_id
        # The close record becomes the trade's LABEL -- the one row the AI
        # layer cannot do without -- so the result reported is the write's.
        from monitor.trade_sink import record_close
        success = record_close(ticket, close_data_safe, analysis_data_safe)

        if success:
            print(f"✅✅✅ Trade {ticket} CLOSED in MongoDB")
            print(f"   Profit: ${profit:.2f} | Open: {price_open} | Close: {price_close}")
            print(f"   ✅ profit_usd saved: ${profit:.2f}")
            print(f"   ✅ analysis_at_close saved with profit: ${profit:.2f}")
            print(f"   ✅ Document ID: {doc_id}")
        else:
            print(f"❌ MongoDB close write FAILED for {ticket} -- see trade_sink status")

        return success

    except Exception as e:
        print(f"❌ Failed to save closed trade to MongoDB: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# WEBHOOK HANDLER - PROCESS ORDER CLOSURE
# ============================================================

def process_webhook_close(
    monitor,
    symbol: str,
    ticket: int,
    close_reason: str,
    profit: float,
    price_open: float,
    price_close: float,
    volume: float,
    sl: float,
    tp: float,
    close_time: str,
    symbol_mt5_map: Dict[str, str],
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    close_analysis: Dict[str, Any] = None
) -> bool:
    """
    Process webhook close with ALL data properly handled.
    ✅ NEW: Accepts close_analysis from monitor.
    ✅ FIXED: Uses consistent doc_id "trade_{ticket}"
    """
    try:
        doc_id = _get_doc_id(ticket)  # ✅ CORRECT doc_id

        print("=" * 80)
        print("📨 WEBHOOK CLOSE RECEIVED:")
        print(f"   Symbol: {symbol}")
        print(f"   Ticket: {ticket}")
        print(f"   Reason: {close_reason}")
        print(f"   Profit: ${profit:.2f}")
        print(f"   Document ID: {doc_id}")
        print("=" * 80)

        # Validate required data
        missing_fields = []
        if price_open == 0:
            missing_fields.append("price_open")
        if price_close == 0:
            missing_fields.append("price_close")
        if volume == 0:
            missing_fields.append("volume")

        if missing_fields:
            print(f"❌ CRITICAL: Missing/Zero fields in webhook for {symbol} (Ticket: {ticket})")
            print(f"   Missing: {missing_fields}")

        # Calculate profit if not provided
        if profit == 0 and price_open > 0 and price_close > 0 and volume > 0:
            # Same defect as above: absolute move, FX multiplier. See
            # core/broker_facts.profit_from_prices.
            mt5_symbol = symbol_mt5_map.get(symbol, symbol) if symbol_mt5_map else symbol
            implied = profit_from_prices(mt5_symbol,
                                         _direction_of_record(ticket),
                                         price_open, price_close, volume)
            if implied is None:
                print(f"   ⚠️ Cannot compute profit for {symbol} without a known "
                      f"direction and contract size - leaving it unset")
            else:
                profit = implied
                print(f"   Calculated profit: ${profit:.2f}")

        # Save to MongoDB with close_analysis
        success = save_trade_close(
            symbol=symbol,
            ticket=ticket,
            close_reason=close_reason,
            profit=profit,
            price_open=price_open,
            price_close=price_close,
            volume=volume,
            sl=sl,
            tp=tp,
            symbol_mt5_map=symbol_mt5_map,
            fixed_trade_size_usd=fixed_trade_size_usd,
            risk_per_trade=risk_per_trade,
            is_webhook=True,
            close_analysis=close_analysis
        )

        if not success:
            print(f"❌ Failed to save close to MongoDB for {symbol} (Ticket: {ticket})")
            return False

        # Update local state
        if monitor:
            with monitor._state_lock:
                for sym, tick in list(monitor.open_positions.items()):
                    if tick == ticket:
                        del monitor.open_positions[sym]
                        monitor.stats["trades_closed"] = monitor.stats.get("trades_closed", 0) + 1
                        break

                if symbol in monitor.symbol_status_map:
                    monitor.symbol_status_map[symbol].in_position = False
                    monitor.symbol_status_map[symbol].ticket = None

            monitor._update_positions_log()

            monitor._log_closed_trade(
                symbol=symbol,
                ticket=ticket,
                close_reason=close_reason,
                profit=profit,
                price_open=price_open,
                price_close=price_close,
                volume=volume,
                sl=sl,
                tp=tp
            )

            print(f"✅ Webhook processed: {symbol} closed at ${price_close:.5f}")

        return True

    except Exception as e:
        print(f"❌ Webhook close processing error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TRAILING STOP - SAVE TO MONGODB
# ✅ FIXED: Consistent doc_id "trade_{ticket}"
# ============================================================

def save_trailing_stop(
    ticket: int,
    symbol: str,
    action: str,
    sl_price: float,
    profit_pips: float,
    step_pips: float,
    price: float = None,
    entry_price: float = None,
    timestamp: str = None
) -> bool:
    """Record a trailing-stop move in MongoDB: current state plus history."""
    try:
        # ✅ FIXED: Use consistent doc_id format
        doc_id = _get_doc_id(ticket)

        print(f"📊 Saving trailing stop to MongoDB: {symbol} ticket={ticket} action={action}")
        print(f"   ✅ Document ID: {doc_id}")

        trailing_data = {
            "activated": True,
            "action": action,
            "new_sl": sl_price,
            "profit_pips": round(profit_pips, 1),
            "step_pips": step_pips,
            "last_update": timestamp or datetime.now(timezone.utc).isoformat(),
            "symbol": symbol
        }

        if price is not None:
            trailing_data["price"] = price
        if entry_price is not None:
            trailing_data["entry_price"] = entry_price

        # Previously written to Firestore ONLY -- no trade in Mongo recorded
        # how its stop moved.
        from monitor.trade_sink import record_trailing_stop
        saved = record_trailing_stop(ticket, trailing_data)
        if saved:
            print(f"✅ Trailing stop saved: {symbol} ticket={ticket} action={action}")
        else:
            print(f"❌ Trailing stop NOT saved: {symbol} ticket={ticket} action={action}")
        return saved

    except Exception as e:
        print(f"❌ Failed to save trailing stop: {e}")
        return False


# ============================================================
# WEBHOOK HANDLER - PROCESS TRAILING STOP UPDATE
# ============================================================

def process_trailing_webhook(
    monitor,
    data: Dict[str, Any]
) -> bool:
    """Process a trailing stop webhook update."""
    try:
        event = data.get('event')
        if event != 'TRAILING_STOP':
            print(f"⚠️ Unknown event: {event}")
            return False

        ticket = data.get('ticket')
        symbol = data.get('symbol')
        action = data.get('action')
        sl_price = data.get('sl_price')
        profit_pips = data.get('profit_pips')
        step_pips = data.get('step_pips')
        price = data.get('price')
        entry_price = data.get('entry_price')
        timestamp = data.get('timestamp')

        if not ticket or not symbol:
            print("❌ Missing ticket or symbol in trailing webhook")
            return False

        doc_id = _get_doc_id(ticket)

        print(f"📨 TRAILING STOP WEBHOOK: {symbol} ticket={ticket} action={action}")
        print(f"   SL: {sl_price} | Profit: {profit_pips:.1f}p | Step: {step_pips}p")
        print(f"   Document ID: {doc_id}")

        save_trailing_stop(
            ticket=ticket,
            symbol=symbol,
            action=action,
            sl_price=sl_price,
            profit_pips=profit_pips,
            step_pips=step_pips,
            price=price,
            entry_price=entry_price,
            timestamp=timestamp
        )

        if monitor and action == "CLOSED":
            with monitor._state_lock:
                for sym, tick in list(monitor.open_positions.items()):
                    if tick == ticket:
                        del monitor.open_positions[sym]
                        monitor.stats["trades_closed"] = monitor.stats.get("trades_closed", 0) + 1
                        break

                if symbol in monitor.symbol_status_map:
                    monitor.symbol_status_map[symbol].in_position = False
                    monitor.symbol_status_map[symbol].ticket = None

            monitor._update_positions_log()

        print(f"✅ Trailing webhook processed: {symbol} ticket={ticket} action={action}")
        return True

    except Exception as e:
        print(f"❌ Trailing webhook processing error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# POSITION MONITOR - MONGODB UPDATES (FALLBACK)
# ✅ FIXED: Consistent doc_id "trade_{ticket}"
# ✅ FIXED: Stops price evolution updates when trade is closed
# ============================================================

def monitor_position_updates(
    open_positions: Dict[str, int],
    symbol_mt5_map: Dict[str, str],
    fixed_trade_size_usd: float,
    risk_per_trade: float,
    stats: Dict[str, Any],
    stop_event,
    on_position_closed: Optional[callable] = None
):
    """
    Monitor open positions and record price and close data in MongoDB.
    Uses ENCODER for price evolution updates every 60 seconds.
    ✅ FIXED: Stops price evolution updates when trade is closed.
    ✅ FIXED: Uses consistent doc_id "trade_{ticket}"
    """
    from core.execution import get_position_details, get_trade_history

    last_cleanup = time.time()
    last_price_update = 0

    # ✅ Price evolution update interval - 60 seconds (1 minute)
    PRICE_UPDATE_INTERVAL = 60

    while not stop_event.is_set():
        try:
            current_time = time.time()

            if current_time - last_cleanup >= 60:
                last_cleanup = current_time

            positions_to_check = list(open_positions.keys())

            for symbol in positions_to_check:
                try:
                    ticket = open_positions.get(symbol)
                    if not ticket:
                        continue

                    # ✅ FIXED: Use consistent doc_id
                    doc_id = _get_doc_id(ticket)

                    # Already closed in the store: tidy local state and move on.
                    if is_trade_closed(ticket):
                        # Clean up local state if needed
                        if symbol in open_positions:
                            del open_positions[symbol]
                            if stats is not None:
                                stats["trades_closed"] = stats.get("trades_closed", 0) + 1
                        if on_position_closed:
                            on_position_closed(symbol, ticket)
                        continue

                    position = get_position_details(ticket)

                    if not position:
                        print(f"📉 {symbol} closed (ticket: {ticket}) - FALLBACK DETECTION")

                        # Check whether the store already has this close
                        from monitor.trade_sink import get_trade_record
                        existing_trade = get_trade_record(ticket)
                        if existing_trade:
                            existing_close = existing_trade.get("close_data", {})
                            existing_close_price = existing_close.get("close_price", 0)
                            existing_profit = existing_close.get("profit_usd", 0)

                            if existing_close_price != 0:
                                print(f"   ✅ Already closed in MongoDB - profit: ${existing_profit:.2f}")
                                if symbol in open_positions:
                                    del open_positions[symbol]
                                    if stats is not None:
                                        stats["trades_closed"] = stats.get("trades_closed", 0) + 1
                                if on_position_closed:
                                    on_position_closed(symbol, ticket)
                                continue

                        # No existing close data - proceed with fallback
                        profit = 0
                        price_open = 0
                        price_close = 0
                        volume = 0
                        sl = 0
                        tp = 0

                        try:
                            history = get_trade_history(last_n_days=1)
                            if history.get("success", False):
                                for trade in history.get("trades", []):
                                    if trade.get("entry_ticket") == ticket:
                                        profit = trade.get("net_profit", 0)
                                        price_open = trade.get("entry_price", 0)
                                        price_close = trade.get("exit_price", 0)
                                        volume = trade.get("volume", 0)
                                        sl = trade.get("entry_sl", 0)
                                        tp = trade.get("entry_tp", 0)
                                        break
                        except Exception as e:
                            print(f"⚠️ Could not get trade history: {e}")

                        if price_open == 0 or price_close == 0:
                            print(f"⚠️ Incomplete close data for {symbol}, skipping")
                            if symbol in open_positions:
                                del open_positions[symbol]
                                if stats is not None:
                                    stats["trades_closed"] = stats.get("trades_closed", 0) + 1
                            if on_position_closed:
                                on_position_closed(symbol, ticket)
                            continue

                        save_trade_close(
            symbol=symbol,
                            ticket=ticket,
                            close_reason=_resolve_close_reason(ticket),
                            profit=profit,
                            price_open=price_open,
                            price_close=price_close,
                            volume=volume,
                            sl=sl,
                            tp=tp,
                            symbol_mt5_map=symbol_mt5_map,
                            fixed_trade_size_usd=fixed_trade_size_usd,
                            risk_per_trade=risk_per_trade,
                            is_webhook=False
                        )

                        if stats is not None:
                            stats["trades_closed"] = stats.get("trades_closed", 0) + 1

                        if symbol in open_positions:
                            del open_positions[symbol]

                        if on_position_closed:
                            on_position_closed(symbol, ticket)

                    else:
                        # ✅ Position still open - update price evolution with ENCODER (every 60 seconds)
                        if current_time - last_price_update >= PRICE_UPDATE_INTERVAL:
                            # ✅ Check again if trade is closed before updating
                            if not is_trade_closed(ticket):
                                update_trade_price(
            ticket=ticket,
                                    position=position,
                                    symbol_mt5_map=symbol_mt5_map,
                                    fixed_trade_size_usd=fixed_trade_size_usd,
                                    risk_per_trade=risk_per_trade
                                )
                                last_price_update = current_time
                            else:
                                # Trade was closed during this iteration
                                if symbol in open_positions:
                                    del open_positions[symbol]
                                    if stats is not None:
                                        stats["trades_closed"] = stats.get("trades_closed", 0) + 1
                                if on_position_closed:
                                    on_position_closed(symbol, ticket)

                except Exception as e:
                    pass

            time.sleep(2)

        except Exception as e:
            time.sleep(5)