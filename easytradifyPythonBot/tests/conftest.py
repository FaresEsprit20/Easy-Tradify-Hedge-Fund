"""
Shared fixtures for the AI layer test suite.

Run from easytradifyPythonBot/:   python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tests must never write into the live decision log: an analysis run on
# simulated market data would otherwise land in MongoDB `decisions` beside the
# real ones. tests/test_live_data_pipeline.py turns it back on, with a fake
# collection.
os.environ.setdefault("DECISION_LOG", "0")

# Analysis payloads are full of emoji keys; on a cp1252 console any test that
# prints one raises UnicodeEncodeError and the failure looks unrelated to the
# assertion that actually failed.
import core.console_safe  # noqa: E402,F401

from ai.price_evolution_encoder import PriceEvolutionEncoder  # noqa: E402


CONFIDENCE = "⭐ CONFIDENCE"
FINAL_DECISION = "\U0001f3af FINAL_DECISION"
TAKE_PROFIT_1 = "\U0001f3af TAKE_PROFIT_1"


def build_analysis(seed: int = 0) -> dict:
    """
    An analyze_institutional_signal()-shaped payload covering every subsystem
    a trade decision actually consults, so coverage tests fail loudly if any
    of them stops surviving extraction.
    """
    return {
        CONFIDENCE: f"{60 + seed}%",
        FINAL_DECISION: "BUY NOW",
        TAKE_PROFIT_1: 1.0890,
        "account_info": {
            "leverage": 200, "balance": 5000.0, "equity": 5012.5,
            "margin_free": 4800.0, "currency": "USD",
        },
        "components": {
            "1_trend_bias": {"trend": "BULLISH", "adx_value": 31.2,
                             "ema_20": 1.0845, "ema_200": 1.0810, "score": 75},
            "4_supply_demand": {"zone_grade": "B", "zone_type": "DEMAND", "touch_count": 2,
                                "quality_breakdown": {"freshness": 0.8, "displacement": 0.7,
                                                      "touch": 0.9, "volume": 0.5}},
            "6_support_resistance": {"r1": 1.0900, "s1": 1.0800, "pivot": 1.0850,
                                     "distance_to_resistance_pips": 40},
            "8_indicators": {
                "rsi": {"value": 58.2, "rsi_21": 55.1},
                "macd": {"line": 0.0004, "signal": 0.0002, "histogram": 0.0002},
                "bollinger": {"upper": 1.0890, "middle": 1.0850, "lower": 1.0810,
                              "percent_b": 0.62, "width": 0.007},
                "stochastic": {"k": 64.1, "d": 59.8},
            },
        },
        "smc": {"recommendation": "BULLISH", "confluence_count": 4,
                "reasons": ["BULLISH BOS", "Price at bullish order block", "discount zone"],
                "market_structure": {"structure": "BULLISH", "last_event": "BULLISH_BOS"}},
        "volume_profile": {"poc": 1.0849, "vah": 1.0862, "val": 1.0836, "inside_va": True},
        "wave_lattice": {"fully_nested": True, "degree": "M15", "contradicts": False},
        "pattern_analysis": {"strongest_pattern": "DOUBLE_BOTTOM",
                             "patterns": [{"name": "DOUBLE_BOTTOM", "confidence": 0.71},
                                          {"name": "RECTANGLE", "confidence": 0.44}]},
        "vwap": {"vwap": 1.0848, "slope": 0.4},
        "rvam": {"state": "CONVICTION_MOVE", "z_score": 2.1},
        "liquidity_events": {"sweep_count": 2},
        "order_flow_forensics": {"stop_hunt_detected": True, "ob_freshness": "VIRGIN"},
        "family_vote": {"aligned": True, "score": 0.72},
        "ttm_squeeze": {"released": True},
        "trend_cascade": {"agreement": 0.85},
        "nested_zone": {"confluent": True},
        "session_analysis": {"session": "LONDON", "phase": "OPEN"},
        "news_analysis": {"event_risk": "LOW"},
        "volatility_protection": {"atr_pips": 12.4, "penalty": 0.0},
        "final_verdict": {
            "probability_percent": 72.5, "star_rating": 4,
            # 14 steps: deliberately more than a small head-of-list cap, so a
            # regression that truncates the ledger is caught.
            "probability_ledger": [{"step": f"s{i}", "delta": float(i)} for i in range(14)],
        },
        "vetos": {"triggered": False, "checks": {"choppy": False, "spread": False}},
        "higher_timeframe": {"h1_trend": "BULLISH"},
        "config": {"min_entry_confidence": 75},
        # The sections the live decision is made from (core/strategy_groups.py,
        # asset_analysis direction_decision), in their live shape. The flat
        # sections above are kept for the modules whose tests still read them;
        # tests/test_price_evolution_alignment.py covers the full live snapshot.
        "direction_decision": {"analysis_direction": "BUY", "traded_direction": "BUY",
                               "flipped_by_trend_cascade": False, "cascade_direction": "BULLISH",
                               "cascade_score": 0.6, "chosen_direction_was_vetoed": False,
                               "veto_overruled_by_trend_cascade": None},
        "strategy_groups": {
            "enabled": True, "version": "1.5", "direction": "BUY", "winner": "TREND",
            "best_score": 75.0, "groups_agreeing": 1, "groups_scored": 2,
            "final_probability": 72.5,
            "groups": {
                "TREND": {"title": "Trend following", "scored": True, "score": 75.0,
                          "agreement": 0.5, "with_count": 3, "against_count": 1,
                          "members": [{"name": "H1 trend", "vote": "WITH", "strength": 0.8}]},
                "MOMENTUM": {"title": "Momentum", "scored": True, "score": 41.9,
                             "agreement": -0.162, "with_count": 1, "against_count": 2,
                             "members": [{"name": "VWAP side (trend-confirmed)",
                                          "vote": "AGAINST", "strength": 0.4}]},
                "WAVE": {"title": "Waves, patterns and candles", "scored": False, "members": [],
                         "reason": "only 0 member(s) with a reading"},
            },
        },
    }


def build_trade(ticket: int = 555, points: int = 3, winning: bool = True,
                encoded: bool = True) -> dict:
    """
    A stored Firebase trade document.

    `encoded` picks which of the two real storage shapes to emit: True is the
    post-fix encoder path, False the legacy raw fallback that firebase_helpers
    writes whenever the encoder import is unavailable.
    """
    analysis = build_analysis(ticket % 5)
    encoder = PriceEvolutionEncoder()

    evolution = []
    for i in range(points):
        point = {
            "timestamp": f"2026-09-01T10:{i:02d}:00Z",
            "price": 1.0850 + i * 0.0004,
            "profit_percent": round(i * 0.3, 3),
            "distance_from_entry_pips": i * 4,
            "spread": 0.7,
            "volume": {"tick_volume": 90 + i, "avg_volume": 61,
                       "volume_ratio": 1.54, "volume_spike": True, "volume_trend": "RISING"},
        }
        if encoded:
            point["analysis"] = {
                "m1": encoder.encode(analysis),
                "m5": encoder.encode(analysis),
                "h1": encoder.encode(analysis),
                "_encoded": True,
            }
        else:
            point["m1_analysis_raw"] = analysis
            point["m5_analysis_raw"] = {"partial": True}
            point["h1_analysis_raw"] = {}
            point["_encoded"] = False
        evolution.append(point)

    return {
        "trade_id": str(ticket), "ticket": ticket, "symbol": "EURUSD",
        "direction": "BUY", "status": "CLOSED", "opened_at": "2026-09-01T10:00:00Z",
        "closed_at": "2026-09-01T10:07:00Z",
        "entry": {"price": 1.0850, "volume": 0.12, "stop_loss": 1.0830,
                  "take_profit": 1.0890, "actual_risk_usd": 20.0,
                  "risk_percent_used": 0.4, "spread_at_entry": 0.6,
                  "magic": 777, "actual_margin": 65.2},
        "analysis_at_open": analysis,
        "price_evolution": evolution,
        "metrics": {"price_updates_count": points},
        "close_data": {
            "close_reason": "TAKE_PROFIT_1" if winning else "STOP_LOSS",
            "close_price": 1.0890 if winning else 1.0830,
            "profit_percent": 1.8 if winning else -0.9,
            "profit_usd": 36.0 if winning else -18.0,
            "is_winning": winning, "duration_seconds": 420,
        },
        "analysis_at_close": {"result": "WIN" if winning else "LOSS", "confidence": "80%"},
    }


@pytest.fixture
def analysis():
    return build_analysis()


@pytest.fixture
def trade():
    return build_trade()


@pytest.fixture
def trades():
    return [build_trade(ticket=t, points=3 + t % 3, winning=(t % 2 == 0))
            for t in range(1, 9)]


@pytest.fixture
def bridge():
    from ai.price_evolution_bridge import PriceEvolutionBridge
    return PriceEvolutionBridge()
