"""
Can a LIVE-recorded trade actually be analysed?

This is the question worth answering BEFORE running a capture session with
real money, not after. The component work in this package all rests on two
fields:

    analysis_at_open.final_verdict.probability_ledger   -- what each
        component contributed to the probability, per step
    analysis_at_open.best_direction                     -- the frame those
        contributions are signed against

A live trade does not store analysis_at_open flat. api/execute_copy_trade.py
writes `{}` on the fast path and a background thread then OVERWRITES the field
with a snapshot envelope whose real payload sits under `m1_analysis_raw`;
core/firebase/firebase_service.py wraps under `full_raw_analysis` instead.
Both shapes hide those two fields from every reader in ai/.

So a capture run would have produced hundreds of trades that look complete,
cost real money, and answer none of the questions they were collected for.
These tests assert the envelope is unwrapped, using payloads shaped exactly
like the two writers produce.
"""

import pytest

from ai.price_evolution_bridge import PriceEvolutionBridge


def _real_analysis():
    """The shape analyze_institutional_signal actually returns, trimmed."""
    return {
        "best_direction": "SELL",
        "final_verdict": {
            "probability_percent": 71.4,
            "probability_ledger": [
                {"step": "pattern", "before": 50.0, "after": 64.4,
                 "delta": 14.4, "clamped": False, "note": "pattern +14.40"},
                {"step": "smc", "before": 64.4, "after": 71.4,
                 "delta": 7.0, "clamped": False, "note": "smc +7.00"},
            ],
        },
        "pattern_final_score": {"pattern_recommendation": "BEARISH",
                                "pattern_contribution": 14.4, "aligned": True},
    }


def _live_snapshot_envelope():
    """What _save_analysis_snapshot_to_firebase(stage='open') writes."""
    return {
        "timestamp": "2026-09-09T10:00:00+00:00",
        "symbol": "EURUSD",
        "order_type": "SELL",
        "profit_usd": 0.0,
        "result": "UNKNOWN",
        "m1_analysis_raw": _real_analysis(),
        "m5_analysis_raw": {},
        "h1_analysis_raw": {},
        "⭐ CONFIDENCE": "71%",
    }


def _firebase_service_envelope():
    """What firebase_service._extract_analysis_data writes."""
    return {
        "timestamp": "2026-09-09T10:00:00+00:00",
        "full_raw_analysis": _real_analysis(),
        "\U0001f3af FINAL_DECISION": "SELL",
    }


def _trade_with(analysis):
    return {
        "trade_id": "trade_123",
        "direction": "SELL",
        "opened_at": "2026-09-09T10:00:00+00:00",
        "entry": {"price": 1.1000, "stop_loss": 1.1020},
        "close_data": {"close_price": 1.0950},
        "analysis_at_open": analysis,
        "price_evolution": [],
    }


ENVELOPES = [
    pytest.param(_live_snapshot_envelope, id="live_snapshot(m1_analysis_raw)"),
    pytest.param(_firebase_service_envelope, id="firebase(full_raw_analysis)"),
    pytest.param(_real_analysis, id="flat(enriched/legacy)"),
]


@pytest.mark.parametrize("build", ENVELOPES)
def test_the_probability_ledger_is_reachable(build):
    """Without this, no component can be attributed anything."""
    canonical = PriceEvolutionBridge().to_canonical(_trade_with(build()))
    analysis = canonical["analysis_at_open"]

    ledger = (analysis.get("final_verdict") or {}).get("probability_ledger")
    assert ledger, (
        "probability_ledger unreachable for this stored shape -- a capture "
        "run would yield trades no component analysis can read"
    )
    assert {s["step"] for s in ledger} == {"pattern", "smc"}


@pytest.mark.parametrize("build", ENVELOPES)
def test_best_direction_is_reachable(build):
    """
    Every chained scorer signs its contribution against best_direction, so a
    ledger delta cannot be interpreted without it -- measured this session:
    reading the same deltas in the wrong frame turned a +0.49R component
    edge into an apparent sign error.
    """
    canonical = PriceEvolutionBridge().to_canonical(_trade_with(build()))
    assert canonical["analysis_at_open"].get("best_direction") == "SELL"


@pytest.mark.parametrize("build", ENVELOPES)
def test_unwrapping_is_idempotent(build):
    """Consumers re-canonicalise freely; twice must equal once."""
    bridge = PriceEvolutionBridge()
    once = bridge.to_canonical(_trade_with(build()))
    twice = bridge.to_canonical(dict(once))

    a = (once["analysis_at_open"].get("final_verdict") or {}).get("probability_ledger")
    b = (twice["analysis_at_open"].get("final_verdict") or {}).get("probability_ledger")
    assert a == b
    assert twice["analysis_at_open"].get("best_direction") == "SELL"


def test_the_envelope_metadata_survives_unwrapping():
    """
    Unwrapping must not delete what the envelope carried -- m5/h1 raw
    analyses are real data, just less of it.
    """
    canonical = PriceEvolutionBridge().to_canonical(
        _trade_with(_live_snapshot_envelope()))
    analysis = canonical["analysis_at_open"]
    assert "m5_analysis_raw" in analysis
    assert analysis["_analysis_envelope"] == "m1_analysis_raw"


def test_an_empty_analysis_stays_empty_rather_than_inventing_structure():
    """
    A trade whose background snapshot never landed genuinely has no
    analysis. That must stay visible as empty, not be papered over -- the
    fast path really does write {} first.
    """
    canonical = PriceEvolutionBridge().to_canonical(_trade_with({}))
    assert not canonical["analysis_at_open"].get("final_verdict")


def test_a_flat_analysis_is_not_corrupted_by_the_unwrapper():
    """The enriched dataset and legacy trades must pass through untouched."""
    flat = _real_analysis()
    canonical = PriceEvolutionBridge().to_canonical(_trade_with(dict(flat)))
    analysis = canonical["analysis_at_open"]
    for key, value in flat.items():
        assert analysis[key] == value
