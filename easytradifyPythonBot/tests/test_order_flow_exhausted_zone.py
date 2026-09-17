"""
An inflated "LIKELY_EXHAUSTED" zone no longer votes against the trade.

The counter-vote inverted order flow on the stored trades (right 40%); trades
at their own "exhausted" zone that order flow opposed were right 63.8%.
"""

from core import order_flow_forensics as off
from core.order_flow_forensics import calculate_order_flow_final_score


def data(status, zone_type="SUPPLY", hunts=None):
    return {"stop_hunts": hunts or [],
            "order_block_mitigation": {"available": True, "status": status, "zone_type": zone_type},
            "liquidity_pools": {"available": False}}


def test_exhausted_zone_alone_moves_nothing():
    result = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED"), 80.0, "SELL")
    assert result["order_flow_contribution"] == 0
    assert result["final_score"] == 80.0


def test_exhausted_zone_no_longer_flips_the_trade():
    """A sell at a supply zone must not read as BULLISH order flow."""
    result = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED", "SUPPLY"), 80.0, "SELL")
    assert result["order_flow_recommendation"] != "BULLISH"
    assert result["aligned"] is True


def test_fresh_zones_still_count():
    first = calculate_order_flow_final_score(data("FIRST_TOUCH", "DEMAND"), 70.0, "BUY")
    assert first["order_flow_contribution"] > 0
    partial = calculate_order_flow_final_score(data("PARTIALLY_MITIGATED", "SUPPLY"), 70.0, "SELL")
    assert partial["order_flow_contribution"] > 0


def test_stop_hunts_still_carry_sign():
    """A SELL_SIDE trap is the LOWS swept and reclaimed (core/liquidity_events),
    which implies up: it supports a BUY and opposes a SELL. This test used to
    assert the opposite, following the inverted legend fixed 2026-09-15."""
    hunt = [{"type": "STOP_HUNT_SELL_SIDE_TRAP", "sweep_size_pips": 1.5, "bars_to_reclaim": 2,
             "implied_direction": "BUY", "bars_ago": 3}]
    buy = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED", hunts=hunt), 70.0, "BUY")
    sell = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED", hunts=hunt), 70.0, "SELL")
    assert buy["order_flow_contribution"] > 0 > sell["order_flow_contribution"]
    assert buy["order_flow_recommendation"] == "BULLISH" == sell["order_flow_recommendation"]


def test_stale_stop_hunts_do_not_count():
    hunt = [{"type": "STOP_HUNT_SELL_SIDE_TRAP", "sweep_size_pips": 1.5, "bars_to_reclaim": 2,
             "implied_direction": "BUY", "bars_ago": 80}]
    result = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED", hunts=hunt), 70.0, "BUY")
    assert result["order_flow_contribution"] == 0


def test_counter_vote_is_switchable(monkeypatch):
    monkeypatch.setattr(off, "LIKELY_EXHAUSTED_COUNTER_VOTE", 45.0)
    result = calculate_order_flow_final_score(data("LIKELY_EXHAUSTED", "SUPPLY"), 80.0, "SELL")
    assert result["order_flow_contribution"] < 0


# ---------------------------------------------------------------------------
# Mitigation is counted from the zone's formation, not from the first bar
# fetched. Bars are (time, open, high, low, close, volume).
# ---------------------------------------------------------------------------
import numpy as np

from core.order_flow_forensics import calculate_order_block_mitigation

PIP = 0.0001
LEVEL = 1.1050


def _bar(high, low):
    return (0, (high + low) / 2, high, low, (high + low) / 2, 100)


def _supply_history(visits_before_formation, visits_after_formation):
    bars = []
    for _ in range(visits_before_formation):          # price trading through the level earlier
        bars += [_bar(LEVEL + 0.00003, LEVEL - 0.0005), _bar(LEVEL - 0.0010, LEVEL - 0.0020)]
    bars.append(_bar(LEVEL, LEVEL - 0.0008))           # the swing high that forms the zone
    bars.append(_bar(LEVEL - 0.0015, LEVEL - 0.0030))  # departure
    for _ in range(visits_after_formation):
        bars += [_bar(LEVEL - 0.00002, LEVEL - 0.0006), _bar(LEVEL - 0.0015, LEVEL - 0.0030)]
    bars.append(_bar(LEVEL - 0.00001, LEVEL - 0.0004))  # the current bar, at the zone
    return np.array(bars, dtype=float)


def test_visits_before_formation_are_not_counted():
    result = calculate_order_block_mitigation(_supply_history(6, 0), LEVEL, "SUPPLY", PIP)
    assert result["formation_found"] is True
    assert result["status"] == "VIRGIN"


def test_visits_after_formation_are_counted():
    result = calculate_order_block_mitigation(_supply_history(6, 1), LEVEL, "SUPPLY", PIP)
    assert result["mitigation_count"] == 1 and result["status"] == "FIRST_TOUCH"
    result = calculate_order_block_mitigation(_supply_history(0, 5), LEVEL, "SUPPLY", PIP)
    assert result["status"] == "LIKELY_EXHAUSTED"


def test_demand_formation_uses_the_low():
    bars = np.array([
        _bar(LEVEL + 0.0005, LEVEL - 0.00003),          # earlier pass below the level
        _bar(LEVEL + 0.0008, LEVEL),                    # swing low forming the demand zone
        _bar(LEVEL + 0.0030, LEVEL + 0.0015),
        _bar(LEVEL + 0.0006, LEVEL + 0.00002),          # first return
        _bar(LEVEL + 0.0030, LEVEL + 0.0015),
        _bar(LEVEL + 0.0004, LEVEL + 0.00001),          # current bar
    ], dtype=float)
    result = calculate_order_block_mitigation(bars, LEVEL, "DEMAND", PIP)
    assert result["formation_found"] is True
    assert result["mitigation_count"] == 1


def test_unknown_level_falls_back_to_full_scan():
    bars = _supply_history(3, 0)
    result = calculate_order_block_mitigation(bars, LEVEL + 0.00037, "SUPPLY", PIP)
    assert result["formation_found"] is False
    assert result["bars_since_formation"] is None
