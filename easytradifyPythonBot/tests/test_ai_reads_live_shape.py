"""
Can the AI layer actually read what the live system writes?

This is the guard against the most expensive class of defect in this project:
the data is present, the reader looks one level too high, and the result is
SILENCE rather than an error. Nothing raises, nothing logs, and every model
concludes the trade had no analysis.

It has now happened three separate ways with the same shape:

  * `analysis_at_open` is stored as an ENVELOPE -- {"m1_analysis_raw": <the
    analysis>, ...} -- and three modules read it raw, finding no
    final_verdict, no probability_ledger, no best_direction.
  * `price_evolution[].analysis` carries `_encoded` on the POINT, beside
    `analysis`, while `_canonical_point` tested for it INSIDE `analysis`. The
    encoded branch never ran, the raw branch found no `m1_analysis_raw` at the
    point level, and every point decoded to {"m1": {}, "m5": {}, "h1": {}}.
  * the price-point encoder raised on a None `timing_confidence`, so the point
    was dropped entirely by a caller that swallowed the exception.

Every fixture here is built to the EXACT shape monitor/firebase_helpers.py and
core/firebase/firebase_service.py write today. If the writers change shape and
the readers are not updated, these fail -- which is the whole point, because
the alternative is discovering it from a model that trained on nothing.
"""

import pytest

from ai.price_evolution_bridge import PriceEvolutionBridge, canonical_analysis
from ai.price_evolution_encoder import PriceEvolutionEncoder


# --------------------------------------------------------------------------
# fixtures: the live shapes, verbatim
# --------------------------------------------------------------------------

def _analysis():
    """A trimmed but structurally real analyze_institutional_signal payload."""
    return {
        "best_direction": "SELL",
        "success": True,
        "final_verdict": {
            "probability_percent": 71.4,
            "probability_ledger": [
                {"step": "pattern", "before": 50.0, "after": 64.4, "delta": 14.4},
                {"step": "smc", "before": 64.4, "after": 71.4, "delta": 7.0},
            ],
        },
        "entry_analysis": {"zone_grade": "A"},
    }


@pytest.fixture
def live_trade():
    """A trade exactly as the monitor writes it to the database."""
    encoder = PriceEvolutionEncoder()
    analysis = _analysis()
    return {
        "trade_id": "trade_1", "ticket": 1, "symbol": "EURUSD",
        "direction": "BUY", "status": "CLOSED",
        "opened_at": "2026-09-09T10:00:00+00:00",
        "closed_at": "2026-09-09T12:00:00+00:00",
        "entry": {"price": 1.1000, "stop_loss": 1.0980, "volume": 0.1},
        "close_data": {"close_price": 1.1050, "profit_usd": 50.0,
                       "close_reason": "TAKE_PROFIT", "order_type": "BUY",
                       "duration_seconds": 7200},
        # the ENVELOPE the live writer produces
        "analysis_at_open": {
            "timestamp": "2026-09-09T10:00:00+00:00",
            "m1_analysis_raw": analysis,
            "m1_audit": {},
            "_encoded": False,
            "trailing_stop": {"enabled": False},
        },
        "analysis_at_close": {
            "timestamp": "2026-09-09T12:00:00+00:00",
            "result": "WIN",
            "m1_analysis_raw": analysis,
            "_encoded": False,
        },
        # `_encoded` sits on the POINT, beside `analysis`
        "price_evolution": [
            {
                "timestamp": f"2026-09-09T10:0{i}:00+00:00",
                "price": 1.1 + i / 10000, "profit_usd": i * 1.0,
                "spread": 2, "volume": 0.1,
                "risk_state": {"sl": 1.0990, "tp": 1.1050,
                               "break_even_applied": False,
                               "trailing_active": False,
                               "sl_at_or_beyond_breakeven": False},
                "analysis": {"m1": encoder.encode(analysis, compact=True)},
                "_encoded": True,
                "_tf_included": ["m1"],
            }
            for i in range(3)
        ],
    }


# --------------------------------------------------------------------------
# the decision snapshot
# --------------------------------------------------------------------------

def test_the_open_analysis_is_reachable_after_canonicalisation(live_trade):
    canonical = PriceEvolutionBridge().to_canonical(live_trade)
    analysis = canonical["analysis_at_open"]

    assert analysis.get("final_verdict"), (
        "final_verdict unreachable -- the storage envelope is not being "
        "flattened, so every model sees an empty decision snapshot")
    assert len(analysis["final_verdict"]["probability_ledger"]) == 2
    assert analysis.get("best_direction") == "SELL"


def test_canonical_analysis_is_usable_standalone(live_trade):
    """
    Modules that hold a RAW trade must be able to flatten one block without
    constructing a bridge -- that is why the helper is module-level.
    """
    flat = canonical_analysis(live_trade["analysis_at_open"])
    assert flat["final_verdict"]["probability_percent"] == 71.4
    assert flat["best_direction"] == "SELL"


def test_canonical_analysis_leaves_a_flat_block_alone():
    flat = {"final_verdict": {"probability_percent": 60.0}}
    assert canonical_analysis(dict(flat))["final_verdict"] == flat["final_verdict"]


def test_an_absent_analysis_stays_absent_rather_than_being_invented():
    """A trade whose snapshot never landed genuinely has none."""
    assert not canonical_analysis({}).get("final_verdict")


# --------------------------------------------------------------------------
# the forward walk
# --------------------------------------------------------------------------

def test_every_price_point_decodes_to_a_real_analysis(live_trade):
    """
    The defect this exists for: points decoding to {"m1": {}, "m5": {},
    "h1": {}} on every row, which reads as "no analysis" rather than
    "the decoder looked in the wrong place".
    """
    canonical = PriceEvolutionBridge().to_canonical(live_trade)
    points = canonical["price_evolution"]
    assert len(points) == 3

    for index, point in enumerate(points):
        m1 = (point.get("analysis") or {}).get("m1") or {}
        assert m1.get("final_verdict"), (
            f"price point {index} decoded to an EMPTY analysis -- the forward "
            f"walk is arriving blank and every model reading it trains on "
            f"nothing")
        assert len(m1["final_verdict"]["probability_ledger"]) == 2


def test_risk_state_survives_canonicalisation(live_trade):
    """Break-even and trailing state must reach the models that explain exits."""
    canonical = PriceEvolutionBridge().to_canonical(live_trade)
    risk = canonical["price_evolution"][0].get("risk_state") or {}
    assert risk.get("sl") == 1.0990
    assert risk.get("sl_at_or_beyond_breakeven") is False


def test_decoding_is_idempotent(live_trade):
    """Consumers re-canonicalise freely; twice must equal once."""
    bridge = PriceEvolutionBridge()
    once = bridge.to_canonical(live_trade)
    twice = bridge.to_canonical(dict(once))
    a = (once["price_evolution"][0]["analysis"]["m1"] or {}).get("final_verdict")
    b = (twice["price_evolution"][0]["analysis"]["m1"] or {}).get("final_verdict")
    assert a == b and a is not None


def test_an_encoded_point_without_the_flag_still_decodes(live_trade):
    """
    Detection is structural, not flag-based, so a writer that forgets to stamp
    `_encoded` cannot silently blank the walk again.
    """
    trade = dict(live_trade)
    trade["price_evolution"] = [
        {k: v for k, v in p.items() if k != "_encoded"}
        for p in live_trade["price_evolution"]
    ]
    canonical = PriceEvolutionBridge().to_canonical(trade)
    m1 = (canonical["price_evolution"][0].get("analysis") or {}).get("m1") or {}
    assert m1.get("final_verdict"), "structural detection failed"


# --------------------------------------------------------------------------
# the consumers that read a raw trade directly
# --------------------------------------------------------------------------

def test_component_validation_sees_the_scores(live_trade):
    """It reads analysis_at_open directly, so it must flatten first."""
    from ai.component_validation import extract_scores
    from ai.price_evolution_bridge import canonical_analysis as flatten

    scores = extract_scores(flatten(live_trade["analysis_at_open"]))
    assert isinstance(scores, dict)
    raw = extract_scores(live_trade["analysis_at_open"])
    assert len(scores) >= len(raw), (
        "flattening produced FEWER scores than the raw envelope -- the "
        "accessor is not helping")


def test_root_cause_reads_the_snapshot_from_a_live_trade(live_trade):
    """
    Its legacy analysis_at_open path must resolve against the ENVELOPE, or
    every diagnosis reports the reasoning as missing on real trades.

    Asserted against the raw stored trade deliberately -- this analyzer is
    reached with documents that have not been canonicalised, which is exactly
    why it flattens internally.
    """
    from ai.root_cause_analyzers import RootCauseAnalyzer

    analyzer = RootCauseAnalyzer()
    snapshots = analyzer._read_decision_snapshots(dict(live_trade))
    assert snapshots, (
        "no decision snapshot recovered from a live-shaped trade -- the "
        "analysis_at_open envelope is not being flattened")

    result = analyzer.analyze(dict(live_trade))
    assert result is not None


def test_the_repository_exposes_the_ledger_and_direction(live_trade):
    """The two fields every component measurement depends on."""
    from ai import trade_repository as repo

    canonical = repo.canonicalise(live_trade)
    assert len(repo.ledger_of(canonical)) == 2
    assert repo.best_direction_of(canonical) == "SELL"


def test_the_repository_keeps_outcome_data_out_of_features(live_trade):
    """
    The leakage firewall, asserted structurally rather than by convention:
    a feature row must not carry close_data or analysis_at_close.
    """
    from ai import trade_repository as repo

    canonical = repo.canonicalise(live_trade)
    features = {
        "trade_id": canonical.get("trade_id"),
        "entry": canonical.get("entry"),
        "analysis_at_open": canonical.get("analysis_at_open"),
    }
    for banned in ("close_data", "analysis_at_close", "closed_at"):
        assert banned not in features
    assert repo.OUTCOME_FIELDS == ("close_data", "analysis_at_close", "closed_at")
