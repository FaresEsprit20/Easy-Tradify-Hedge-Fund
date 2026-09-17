# ============================================================
# ASSET ANALYSIS - GNN (GRAPH NEURAL NETWORK) INTEGRATION WRAPPERS
# ============================================================
# FILE: core/asset_analysis_gnn.py
#
# Split out of asset_analysis.py (which had grown past 7,400 lines) to
# reduce its length -- this is a pure code-motion, not a rewrite: every
# function/constant below is byte-for-byte identical to what was in
# asset_analysis.py, just relocated together. Contains:
#   - GNN import-with-fallback setup (GNN_AVAILABLE, AssetGraphNeural
#     Network, default_config) and the module-level singleton instance
#     state (_gnn_instance/_gnn_initialized), plus get_gnn_instance()/
#     is_gnn_available() which manage it
#   - GNN read wrappers: get_gnn_context, get_gnn_divergence,
#     get_gnn_suggestions, get_gnn_conflict, get_gnn_ab_test,
#     get_gnn_correlations_detailed, analyze_gnn_correlations
#   - calculate_gnn_final_score() -- the probability-chain adjustment
#   - build_ohlc_with_gnn() / _calculate_combined_signal() -- blending
#     OHLC-derived and GNN-derived signals
#
# This file has NO dependency on asset_analysis.py or any other
# split-out module -- only on core.asset_analysis_config and the
# externally-optional ai.ai_gnn/ai.ai_config packages (already wrapped
# in the same try/except ImportError graceful-degradation pattern used
# throughout this codebase for other not-always-present dependencies
# like core.veto_engine/core.patterns). asset_analysis.py imports FROM
# this file, never the other way around, so there is no circular
# import.
# ============================================================

from typing import Dict, Any
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
import logging
import time

from core.asset_analysis_config import GNN_WEIGHT, GNN_CONFIDENCE_THRESHOLD


# ============================================================
# GNN IMPORTS - WITH PYTHON 3.13 COMPATIBILITY FIX
# ============================================================
GNN_AVAILABLE = False
AssetGraphNeuralNetwork = None
default_config = None

try:
    # ✅ FIXED: this used to hard-gate GNN behind
    # `if sys.version_info >= (3, 13): GNN disabled` plus a torch import
    # check, unconditionally printing "PyTorch not compatible with
    # Python 3.13 - GNN disabled" and permanently leaving GNN_AVAILABLE
    # False on any Python 3.13 install — regardless of whether torch
    # actually works. Two things were wrong with this:
    #   1. Current PyTorch (2.6+) supports standard Python 3.13 fine —
    #      confirmed the actual installed torch (2.13.0) imports
    #      successfully on this exact Python 3.13 setup.
    #   2. More fundamentally: ai.ai_gnn.AssetGraphNeuralNetwork doesn't
    #      import torch anywhere at all — it's a pure numpy/MT5-data
    #      implementation. This whole check was gating an import that
    #      never needed torch in the first place, on every single Python
    #      3.13 install, whether or not torch was even relevant.
    # Just attempt the real import and let ImportError (the actual
    # failure mode) drive the disabled state, instead of a version guess.
    # Must precede the ai.* imports: those modules log at MODULE level
    # with emoji, and on a cp1252 console that raises UnicodeEncodeError
    # during the import itself -- which the `except Exception` below then
    # reports as "GNN initialization failed". The GNN was never broken;
    # its import was writing a brain emoji to a console that could not
    # encode one. See core/console_safe.py.
    import core.console_safe  # noqa: F401

    from ai.ai_gnn import AssetGraphNeuralNetwork
    from ai.ai_config import default_config
    GNN_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ GNN import failed: {e}")
except Exception as e:
    logging.warning(f"⚠️ GNN initialization failed: {e}")

logger = logging.getLogger(__name__)

# ============================================================
# GLOBAL GNN INSTANCE
# ============================================================

_gnn_instance = None
_gnn_initialized = False


def get_gnn_instance(monitor=None):
    """Get or create GNN instance with proper initialization."""
    global _gnn_instance, _gnn_initialized
    
    if _gnn_instance is not None:
        return _gnn_instance
    
    if not GNN_AVAILABLE:
        logger.warning("⚠️ GNN not available")
        return None
    
    try:
        from core.firebase import get_firebase_service
        firebase = get_firebase_service()
        
        _gnn_instance = AssetGraphNeuralNetwork(
            firebase_service=firebase,
            config=default_config,
            monitor=monitor
        )
        _gnn_initialized = True
        
        time.sleep(1)
        
        logger.info("✅ GNN instance created for asset_analysis")
        return _gnn_instance
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to create GNN instance: {e}")
        _gnn_instance = None
        return None


def is_gnn_available() -> bool:
    """Check if GNN is available and enabled."""
    if not GNN_AVAILABLE:
        return False
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return False
        return gnn.is_enabled and gnn.is_ready()
    except Exception as e:
        logger.debug(f"GNN availability check failed: {e}")
        return False


# ============================================================
# GNN ANALYSIS FUNCTIONS - COMPLETE
# ============================================================

def get_gnn_context(symbol: str, trade_id: int = None) -> Dict[str, Any]:
    """Get GNN context for a symbol."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available or not ready"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        context = gnn.get_context(symbol.upper(), trade_id)
        
        return {
            "available": True,
            "context": context,
            "dxy_strength": context.get("dxy_strength", 0.5),
            "risk_sentiment": context.get("risk_sentiment", 0.5),
            "commodity_impact": context.get("commodity_impact", 0.5),
            "sector_sentiment": context.get("sector_sentiment", 0.5),
            "global_confidence": context.get("global_confidence", 0.5),
            "trend_alignment": context.get("trend_alignment", 0.5),
            "market_regime": context.get("market_regime", "NORMAL"),
            "gnn_influence": context.get("gnn_influence", 0),
            "gnn_connections": context.get("gnn_connections", 0),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"GNN context error for {symbol}: {e}")
        return {"available": False, "error": str(e)}


def get_gnn_divergence(symbol: str) -> Dict[str, Any]:
    """Get GNN divergence detection for a symbol."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        insights = gnn.get_trading_insights(symbol.upper())
        divergence = insights.get("divergence", {})
        
        return {
            "available": True,
            "detected": divergence.get("detected", False),
            "type": divergence.get("type"),
            "reason": divergence.get("reason"),
            "gnn_direction": divergence.get("gnn_direction", 0),
            "price_direction": divergence.get("price_direction", 0)
        }
        
    except Exception as e:
        logger.error(f"GNN divergence error for {symbol}: {e}")
        return {"available": False, "error": str(e)}


def get_gnn_suggestions(symbol: str, max_suggestions: int = 5) -> Dict[str, Any]:
    """Get GNN trade suggestions for a symbol."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        insights = gnn.get_trading_insights(symbol.upper())
        all_suggestions = insights.get("suggestions", [])
        suggestions = all_suggestions[:max_suggestions]
        
        buy_count = sum(1 for s in suggestions if s.get("action") == "BUY")
        sell_count = sum(1 for s in suggestions if s.get("action") == "SELL")
        
        if buy_count > sell_count:
            recommendation = "BULLISH"
            avg_confidence = sum(s.get("confidence", 0) for s in suggestions) / len(suggestions) if suggestions else 0
        elif sell_count > buy_count:
            recommendation = "BEARISH"
            avg_confidence = sum(s.get("confidence", 0) for s in suggestions) / len(suggestions) if suggestions else 0
        else:
            recommendation = "NEUTRAL"
            avg_confidence = 0
        
        return {
            "available": True,
            "suggestions": suggestions,
            "count": len(suggestions),
            "recommendation": recommendation,
            "confidence": round(avg_confidence, 1)
        }
        
    except Exception as e:
        logger.error(f"GNN suggestions error for {symbol}: {e}")
        return {"available": False, "error": str(e)}


def get_gnn_conflict(symbol: str, analysis_direction: str) -> Dict[str, Any]:
    """Get GNN conflict detection with your analysis."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        insights = gnn.get_trading_insights(symbol.upper(), analysis_direction)
        conflict = insights.get("conflict", None)
        
        if conflict:
            return {
                "available": True,
                "conflict": conflict,
                "your_analysis": conflict.get("your_analysis"),
                "gnn_says": conflict.get("gnn_says"),
                "severity": conflict.get("severity"),
                "message": conflict.get("message"),
                "recommendation": conflict.get("recommendation")
            }
        else:
            return {
                "available": True,
                "conflict": None,
                "message": f"No conflict detected. GNN agrees with {analysis_direction}",
                "your_analysis": analysis_direction,
                "gnn_says": analysis_direction
            }
        
    except Exception as e:
        logger.error(f"GNN conflict error for {symbol}: {e}")
        return {"available": False, "error": str(e)}


def get_gnn_ab_test() -> Dict[str, Any]:
    """Get GNN A/B test results."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        results = gnn.get_ab_test_results()
        
        return {
            "available": True,
            "enabled": results.get("enabled", False),
            "rollout": results.get("rollout", 0),
            "control": results.get("control", {}),
            "test": results.get("test", {}),
            "improvement": results.get("improvement", 0),
            "status": results.get("status", "UNKNOWN"),
            "total_trades": results.get("total_trades", 0)
        }
        
    except Exception as e:
        logger.error(f"GNN AB test error: {e}")
        return {"available": False, "error": str(e)}


def get_gnn_correlations_detailed(symbol: str) -> Dict[str, Any]:
    """Get detailed GNN correlations for a symbol."""
    if not is_gnn_available():
        return {"available": False, "message": "GNN not available"}
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            return {"available": False, "message": "GNN instance not available"}
        
        insights = gnn.get_trading_insights(symbol.upper())
        correlations = insights.get("correlations", [])
        
        for corr in correlations:
            if "direction" not in corr or corr.get("direction") == 0:
                try:
                    other_context = gnn.get_context(corr.get("symbol", ""))
                    corr["direction"] = other_context.get("gnn_influence", 0)
                except Exception:
                    corr["direction"] = 0
        
        if correlations:
            sorted_corrs = sorted(correlations, key=lambda x: abs(x.get("correlation", 0)), reverse=True)
            strongest = sorted_corrs[0] if sorted_corrs else None
            weakest = sorted_corrs[-1] if sorted_corrs else None
        else:
            strongest = None
            weakest = None
        
        return {
            "available": True,
            "correlations": correlations,
            "count": len(correlations),
            "strongest": strongest,
            "weakest": weakest
        }
        
    except Exception as e:
        logger.error(f"GNN correlations error for {symbol}: {e}")
        return {"available": False, "error": str(e)}


# ============================================================
# GNN ANALYSIS WITH SUGGESTIONS FROM CORRELATIONS
# ============================================================

def analyze_gnn_correlations(symbol: str, analysis_direction: str = None, trade_id: int = None) -> Dict[str, Any]:
    """Get GNN correlation analysis with ALL data."""
    default_response = {
        "available": False,
        "message": "GNN not available or not ready",
        "correlations": [],
        "divergence": {"detected": False},
        "suggestions": [],
        "conflict": None,
        "recommendation": "NEUTRAL",
        "recommendation_score": 0,
        "gnn_direction": 0,
        "price_direction": 0,
        "data_quality": "UNAVAILABLE",
        "risk_warnings": [],
        "timestamp": datetime.now().isoformat()
    }
    
    if not is_gnn_available():
        logger.warning("⚠️ GNN not available for correlations analysis")
        return default_response
    
    try:
        gnn = get_gnn_instance()
        if gnn is None:
            logger.warning("⚠️ GNN instance not available")
            return default_response
        
        logger.info(f"🔍 Getting GNN insights for {symbol}")
        insights = gnn.get_trading_insights(symbol, analysis_direction)
        
        if not insights:
            logger.warning(f"⚠️ No insights returned for {symbol}")
            return default_response
        
        correlations = insights.get("correlations", [])
        divergence = insights.get("divergence", {})
        suggestions = insights.get("suggestions", [])
        conflict = insights.get("conflict", None)
        price_direction = insights.get("price_direction", 0)
        gnn_direction = insights.get("gnn_direction", 0)
        data_quality = insights.get("data_quality", "UNKNOWN")
        risk_warnings = insights.get("risk_warnings", [])
        
        logger.info(f"📊 GNN data for {symbol}: {len(correlations)} correlations, {len(suggestions)} suggestions")
        
        # Generate suggestions from correlations if empty
        if not suggestions and correlations:
            logger.info(f"🔄 GNN suggestions empty - generating from {len(correlations)} correlations")
            for corr in correlations[:3]:
                if abs(corr.get('correlation', 0)) > 0.5:
                    if price_direction > 0.1:
                        action = 'BUY' if corr.get('correlation', 0) > 0 else 'SELL'
                    elif price_direction < -0.1:
                        action = 'SELL' if corr.get('correlation', 0) > 0 else 'BUY'
                    else:
                        if corr.get('direction', 0) > 0.05:
                            action = 'BUY'
                        elif corr.get('direction', 0) < -0.05:
                            action = 'SELL'
                        else:
                            action = 'NEUTRAL'
                    
                    if action != 'NEUTRAL':
                        suggestions.append({
                            'symbol': corr.get('symbol', ''),
                            'action': action,
                            'confidence': corr.get('confidence', 60),
                            'correlation': corr.get('correlation', 0),
                            'source': corr.get('source', 'STATIC'),
                            'reason': f"Correlation: {corr.get('correlation', 0):.2f} with {symbol}"
                        })
        
        # ============================================================
        # ✅ FIXED: previously this block ignored insights['recommendation']
        # and insights['recommendation_score'] entirely (both already
        # computed by ai_gnn.py's get_trading_insights, including proper
        # mixed-BUY/SELL-signal handling) and recomputed a cruder version
        # from scratch here (simple buy_count > sell_count with a flat
        # `buy_count * 20 + 20` score formula). The two could silently
        # disagree. Now uses the upstream values directly; only falls
        # back to a local computation if they're missing for some reason.
        # ============================================================
        recommendation = insights.get("recommendation")
        recommendation_score = insights.get("recommendation_score")
        
        if recommendation is None or recommendation_score is None:
            # Fallback path (upstream didn't provide one) - keep the
            # previous local logic as a safety net only.
            recommendation = "NEUTRAL"
            recommendation_score = 0
            
            if divergence.get("detected", False):
                div_type = divergence.get("type", "")
                if "BEARISH" in div_type:
                    recommendation = "BEARISH"
                    recommendation_score = 60
                elif "BULLISH" in div_type:
                    recommendation = "BULLISH"
                    recommendation_score = 60
            elif suggestions:
                buy_count = sum(1 for s in suggestions if s.get("action") == "BUY")
                sell_count = sum(1 for s in suggestions if s.get("action") == "SELL")
                
                if buy_count > sell_count:
                    recommendation = "BULLISH"
                    recommendation_score = min(85, buy_count * 20 + 20)
                elif sell_count > buy_count:
                    recommendation = "BEARISH"
                    recommendation_score = min(85, sell_count * 20 + 20)
                
                if suggestions:
                    avg_confidence = sum(s.get("confidence", 0) for s in suggestions) / len(suggestions)
                    recommendation_score = max(recommendation_score, avg_confidence)
        
        # ✅ FIXED (2026-09-15): a conflict with the ENGINE'S side replaced
        # the recommendation, so the GNN's own market reading depended on the
        # side being evaluated (CONFLICT on 21% of study bars). The reading
        # stays market-relative; the conflict is its own flag and still
        # counts against the side in calculate_gnn_final_score.
        
        return {
            "available": True,
            "correlations": correlations,
            "divergence": divergence,
            "suggestions": suggestions,
            "conflict": conflict,
            "recommendation": recommendation,
            "recommendation_score": round(recommendation_score, 1),
            "gnn_direction": gnn_direction,
            "price_direction": price_direction,
            "data_quality": data_quality,
            "risk_warnings": risk_warnings,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ GNN analysis error for {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return default_response


def calculate_gnn_final_score(gnn_analysis: Dict[str, Any], base_probability: float, best_direction: str = "BUY") -> Dict[str, Any]:
    """
    Calculate GNN's contribution to final trade score.

    `best_direction` ("BUY" or "SELL") is required to correctly interpret
    alignment. `base_probability` is the probability that the CHOSEN trade
    direction is correct, not an absolute bullish/bearish market read — so
    for a SELL trade a high base_probability means strong conviction the
    market will fall (bearish), not bullish. Alignment and the sign of the
    contribution are judged against best_direction, never against whether
    base_probability crosses 50.
    """
    if not gnn_analysis.get("available", False):
        return {
            "gnn_recommendation": "UNAVAILABLE",
            "gnn_score": 0,
            "gnn_contribution": 0,
            "final_score": base_probability,
            "gnn_weight_used": 0,
            "aligned": True
        }
    
    gnn_recommendation = gnn_analysis.get("recommendation", "NEUTRAL")
    gnn_score = gnn_analysis.get("recommendation_score", 0)
    if gnn_analysis.get("conflict"):
        gnn_recommendation = "CONFLICT"      # conflict with the side being scored
    
    if gnn_recommendation == "CONFLICT":
        gnn_score = 50
        gnn_weight = GNN_WEIGHT * 0.3
    else:
        gnn_weight = GNN_WEIGHT
    
    # ============================================================
    # ✅ FIXED: this function previously had zero awareness of whether the
    # GNN signal came from real MT5 data or the fabricated STATIC fallback
    # (data_quality) — a simulated/random signal got the exact same weight
    # in the real probability score as a live one. Dampened the same way
    # CONFLICT already is (×0.3), since "fabricated data" deserves at
    # least as much distrust as "GNN disagrees with itself".
    # risk_warnings similarly gets a smaller dampening (×0.7) when present,
    # since it flags things like mixed-signal correlated assets or low
    # correlation-confidence data.
    # ============================================================
    data_quality = gnn_analysis.get("data_quality", "UNKNOWN")
    risk_warnings = gnn_analysis.get("risk_warnings", [])
    
    if data_quality == "SIMULATED":
        gnn_weight = gnn_weight * 0.3
    elif risk_warnings:
        gnn_weight = gnn_weight * 0.7
    
    if gnn_score < GNN_CONFIDENCE_THRESHOLD:
        gnn_score = 0
        gnn_weight = 0    
    
    # ✅ FIXED: alignment used to be judged with `base_probability > 50`,
    # silently assuming base_probability was an absolute bullish-market
    # probability. It isn't -- it's the probability THIS trade's direction
    # is correct, so for a SELL trade a high value is bearish, not bullish.
    # That inverted the check for every SELL trade: an opposing (bullish)
    # signal was treated as "aligned" and given full weight, while a
    # genuinely agreeing (bearish) signal was wrongly dampened. Alignment
    # is now judged directly against best_direction.
    agree_label = "BULLISH" if best_direction == "BUY" else "BEARISH"
    oppose_label = "BEARISH" if best_direction == "BUY" else "BULLISH"

    aligned = True

    if gnn_recommendation == oppose_label:
        aligned = False
        gnn_weight = gnn_weight * 0.2

    # ✅ FIXED: was `gnn_weight = gnn_weight * 0.3` here too -- CONFLICT
    # already got its 0.3x dampening at the top of this function (line
    # ~1569). Re-applying it here compounded to an effective 0.3*0.3=0.09x
    # instead of the intended single 0.3x, which only showed up as a
    # misleadingly small gnn_weight_used in the output (the contribution
    # itself was already 0 via the `else` branch below regardless of
    # weight, so this was a display bug, not a scoring bug -- fixed
    # before it could become one).
    if gnn_recommendation == "CONFLICT":
        aligned = False
    
    if gnn_recommendation == agree_label:
        gnn_contribution = (gnn_score / 100) * gnn_weight * 100
    elif gnn_recommendation == oppose_label:
        gnn_contribution = -(gnn_score / 100) * gnn_weight * 100
    elif gnn_recommendation == "NEUTRAL" and gnn_score >= 50:
        # NEUTRAL doesn't oppose either direction, so a firm-but-neutral
        # read is a small direction-agnostic confidence boost for
        # whichever trade was already chosen -- not affected by the
        # direction-relative fix above.
        gnn_contribution = (gnn_score / 100) * gnn_weight * 100 * 0.5
    elif gnn_recommendation == "CONFLICT":
        # ✅ FIXED: CONFLICT matched none of the branches above and fell
        # into the `else`, so its contribution was 0 -- the conflict was
        # detected, flagged as aligned=False, dampened to 0.3x weight,
        # and then discarded before it could affect anything.
        #
        # Measured on a 4240-decision cross-asset replay: the GNN raised
        # CONFLICT 484 times and contributed 0.00 on every one of them.
        # The whole cross-asset graph was running to produce a signal
        # nothing consumed. That is the same "computed then discarded"
        # shape as the clamped probability evidence and the unread
        # near-miss margins elsewhere in this codebase.
        #
        # A conflict is not neutral information. It means the
        # cross-asset picture disagrees with the trade, so it reduces
        # confidence -- signed AGAINST the chosen direction, at the
        # already-dampened conflict weight, never in favour of it.
        gnn_contribution = -(gnn_score / 100) * gnn_weight * 100
    else:
        gnn_contribution = 0
    
    max_contribution = gnn_weight * 100    
    gnn_contribution = max(-max_contribution, min(max_contribution, gnn_contribution))
    
    final_score = base_probability + gnn_contribution
    final_score = max(5.0, min(95.0, final_score))
    
    return {
        "gnn_recommendation": gnn_recommendation,
        "gnn_score": gnn_score,
        "gnn_contribution": round(gnn_contribution, 2),
        "final_score": round(final_score, 2),
        "gnn_weight_used": round(gnn_weight * 100, 1),
        "data_quality": data_quality,
        "aligned": aligned
    }


def build_ohlc_with_gnn(
    symbol: str,
    rates: np.ndarray,
    current_price: float,
    pip_size: float,
    gnn_analysis: Dict[str, Any],
    timeframe: str = None
) -> Dict[str, Any]:
    """Build OHLC + GNN output for AI training.

    timeframe: the timeframe `rates` actually came from. Defaults to None
    -> reported as "UNKNOWN" rather than guessed; see the note at the
    "timeframe" key below for why guessing was the bug.
    """
    if rates is None or len(rates) < 10:
        return {}
    
    latest = rates[-1]
    
    try:
        ohlc = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            # ✅ FIXED: this was hardcoded "H1". The function has no idea
            # what timeframe `rates` came from -- it just reads rates[-1] --
            # so it labelled every bar H1 regardless. Live M1 analysis was
            # publishing its M1 bar as H1 in four consecutive payloads;
            # provable because ohlc.tick_volume matched
            # indicators.volume.debug.current_volume exactly every time
            # (45 / 27 / 94 / 16), and that is the M1 bar's volume. Since
            # this block is labelled "output for AI training", every
            # sample it produced carried the wrong timeframe label.
            "timeframe": (timeframe or "UNKNOWN").upper(),
            "open": round(float(latest[1]), 5),
            "high": round(float(latest[2]), 5),
            "low": round(float(latest[3]), 5),
            "close": round(float(latest[4]), 5),
            "tick_volume": int(latest[5]),
            "spread": float(getattr(mt5.symbol_info_tick(symbol), 'ask', 0) - getattr(mt5.symbol_info_tick(symbol), 'bid', 0)) / pip_size if pip_size > 0 else 0,
            "pip_size": pip_size,
            "body": round(abs(float(latest[4]) - float(latest[1])), 5),
            "upper_wick": round(float(latest[2]) - max(float(latest[1]), float(latest[4])), 5),
            "lower_wick": round(min(float(latest[1]), float(latest[4])) - float(latest[3]), 5),
            "range": round(float(latest[2]) - float(latest[3]), 5),
            "range_pips": round((float(latest[2]) - float(latest[3])) / pip_size, 1) if pip_size > 0 else 0,
        }
    except (IndexError, TypeError) as e:
        logger.error(f"Failed to parse OHLC data: {e}")
        return {}
    
    if ohlc["close"] > 0 and ohlc["open"] > 0:
        ohlc["change"] = round(ohlc["close"] - ohlc["open"], 5)
        ohlc["change_percent"] = round((ohlc["change"] / ohlc["open"]) * 100, 2)
    else:
        ohlc["change"] = 0
        ohlc["change_percent"] = 0
    
    if ohlc["close"] > ohlc["open"]:
        ohlc["candle_type"] = "BULLISH"
    elif ohlc["close"] < ohlc["open"]:
        ohlc["candle_type"] = "BEARISH"
    else:
        ohlc["candle_type"] = "DOJI"
    
    gnn_section = {"available": gnn_analysis.get("available", False)}
    
    if gnn_analysis.get("available", False):
        correlations = gnn_analysis.get("correlations", [])
        gnn_section["correlations"] = [
            {
                "symbol": c.get("symbol"),
                "correlation": round(c.get("correlation", 0), 2),
                "confidence": round(c.get("confidence", 0), 1),
                "stability": round(c.get("stability", 0), 1),
                "direction": c.get("direction", 0),
                "source": c.get("source", "STATIC")
            }
            for c in correlations[:5]
        ]
        
        divergence = gnn_analysis.get("divergence", {})
        gnn_section["divergence"] = {
            "detected": divergence.get("detected", False),
            "type": divergence.get("type"),
            "reason": divergence.get("reason"),
            "gnn_direction": round(divergence.get("gnn_direction", 0), 2),
            "price_direction": round(divergence.get("price_direction", 0), 2)
        }
        
        suggestions = gnn_analysis.get("suggestions", [])
        gnn_section["suggestions"] = [
            {
                "symbol": s.get("symbol"),
                "action": s.get("action"),
                "confidence": round(s.get("confidence", 0), 1),
                "reason": s.get("reason")
            }
            for s in suggestions[:3]
        ]
        
        gnn_section["recommendation"] = gnn_analysis.get("recommendation", "NEUTRAL")
        gnn_section["recommendation_score"] = round(gnn_analysis.get("recommendation_score", 0), 1)
        
        conflict = gnn_analysis.get("conflict")
        if conflict:
            gnn_section["conflict"] = {
                "your_analysis": conflict.get("your_analysis"),
                "gnn_says": conflict.get("gnn_says"),
                "severity": conflict.get("severity"),
                "message": conflict.get("message"),
                "recommendation": conflict.get("recommendation")
            }
    
    return {
        "ohlc": ohlc,
        "gnn": gnn_section,
        "combined_signal": _calculate_combined_signal(ohlc, gnn_section)
    }


def _calculate_combined_signal(ohlc: Dict, gnn: Dict) -> Dict:
    """Calculate combined signal from OHLC + GNN."""
    candle_signal = 1 if ohlc.get("candle_type") == "BULLISH" else -1 if ohlc.get("candle_type") == "BEARISH" else 0
    candle_confidence = 70
    
    gnn_signal = 0
    gnn_confidence = 0
    
    if gnn.get("available", False):
        rec = gnn.get("recommendation", "NEUTRAL")
        # ✅ FIXED: recommendation_score is SIGNED (+75.0 for a bullish
        # read, -73.5 for a bearish one) and was being assigned straight
        # into gnn_confidence, which is treated as an unsigned strength
        # everywhere below. Two consequences, both live:
        #
        #   1. A negative "confidence" was published (gnn_confidence:
        #      -73.5), which is not a meaningful quantity.
        #   2. Worse, the gate below is `gnn_confidence > 50`. A bearish
        #      score is always negative, so it could NEVER pass -- the
        #      blend silently fell through to `combined = candle_signal`
        #      and threw the GNN away entirely. The blend was structurally
        #      incapable of ever incorporating a bearish GNN read, while
        #      bullish reads blended normally. Confirmed live: GNN said
        #      BEARISH at 73.5, and combined_signal returned "BUY".
        #
        # Direction already comes from `rec`; the score contributes
        # magnitude only.
        raw_score = gnn.get("recommendation_score", 50)
        try:
            score_strength = abs(float(raw_score))
        except (TypeError, ValueError):
            score_strength = 50.0
        if rec == "BULLISH":
            gnn_signal = 1
            gnn_confidence = score_strength
        elif rec == "BEARISH":
            gnn_signal = -1
            gnn_confidence = score_strength
        elif rec == "CONFLICT":
            gnn_signal = 0
            gnn_confidence = 30
    
    if gnn.get("available", False) and gnn_confidence > 50:
        combined = (candle_signal * candle_confidence + gnn_signal * gnn_confidence) / (candle_confidence + gnn_confidence)
    else:
        combined = candle_signal
    
    if combined > 0.3:
        final_rec = "BUY"
        final_confidence = min(95, candle_confidence * 0.6 + abs(combined) * 30)
    elif combined < -0.3:
        final_rec = "SELL"
        final_confidence = min(95, candle_confidence * 0.6 + abs(combined) * 30)
    else:
        final_rec = "HOLD"
        final_confidence = 50
    
    return {
        "candle_signal": candle_signal,
        "candle_confidence": candle_confidence,
        "gnn_signal": gnn_signal,
        "gnn_confidence": gnn_confidence,
        "combined_score": round(combined, 2),
        "recommendation": final_rec,
        "confidence": round(final_confidence, 1),
        "gnn_available": gnn.get("available", False)
    }