"""
Non-RL intelligence layer: trade -> DecisionRecord conversion and RNG hygiene.
"""

import random

from ai.non_rl_intelligence import (
    DecisionRecord,
    NonRLIntelligenceController,
    decision_records_from_trades,
)

from conftest import build_trade


# ---------------------------------------------------------------------------
# Regression: constructor reseeded the global RNG
# ---------------------------------------------------------------------------

def test_constructing_the_controller_does_not_reseed_global_rng():
    """
    __init__ called random.seed(config.random_seed), resetting the
    PROCESS-WIDE stream as a side effect of construction -- so anything else
    drawing from `random` (adversarial's attack selection among them) got a
    fixed sequence from that point on, identically on every run.
    """
    random.seed(1234)
    expected = [random.random() for _ in range(5)]

    random.seed(1234)
    NonRLIntelligenceController()
    actual = [random.random() for _ in range(5)]

    assert actual == expected


def test_controller_still_has_a_deterministic_stream():
    """Reproducibility must survive the fix, just scoped to the instance."""
    first = NonRLIntelligenceController().random.random()
    second = NonRLIntelligenceController().random.random()
    assert first == second


# ---------------------------------------------------------------------------
# Trade -> DecisionRecord
# ---------------------------------------------------------------------------

def test_builds_one_record_per_trade(trades):
    records = decision_records_from_trades(trades)
    assert len(records) == len(trades)
    assert all(isinstance(r, DecisionRecord) for r in records)


def test_records_carry_identity_features_and_labels(trades):
    record = decision_records_from_trades(trades)[0]
    assert record.decision_id
    assert record.timestamp
    assert len(record.observation) > 10
    assert record.outcome["success"] in (0, 1)
    assert record.component_scores


def test_unidentifiable_trades_are_skipped():
    """A record that cannot be joined back to anything is not worth keeping."""
    anonymous = build_trade()
    anonymous.pop("trade_id")
    anonymous.pop("ticket")
    assert decision_records_from_trades([anonymous]) == []


def test_malformed_trades_do_not_abort_the_batch(trades):
    assert len(decision_records_from_trades([None, "junk"] + trades)) == len(trades)


def test_labels_follow_the_close_reason():
    won = decision_records_from_trades([build_trade(ticket=1, winning=True)])[0]
    lost = decision_records_from_trades([build_trade(ticket=2, winning=False)])[0]
    assert won.outcome["success"] == 1 and won.outcome["tp_hit"] == 1
    assert lost.outcome["success"] == 0 and lost.outcome["sl_hit"] == 1


def test_observations_contain_no_outcome_information(trades):
    banned = ("close_data", "analysis_at_close", "is_winning",
              "profit_percent", "close_reason", "realized_return")
    for record in decision_records_from_trades(trades):
        leaked = [k for k in record.observation if any(b in k.lower() for b in banned)]
        assert not leaked, f"leakage into observation: {leaked}"


# ---------------------------------------------------------------------------
# prepare_from_trades
# ---------------------------------------------------------------------------

def test_prepare_from_trades_matches_manual_path(trades):
    """The trade shortcut must not diverge from the DecisionRecord path."""
    via_trades = NonRLIntelligenceController().prepare_from_trades(trades)
    via_records = NonRLIntelligenceController().prepare(
        decision_records_from_trades(trades)
    )
    assert len(via_trades[0]) == len(via_records[0])
    assert [l.success for l in via_trades[1]] == [l.success for l in via_records[1]]


def test_prepare_orders_records_chronologically(trades):
    rows, labels = NonRLIntelligenceController().prepare_from_trades(trades)
    assert len(rows) == len(labels) == len(trades)
