"""
RL entry-timing agent: trade -> snapshot conversion and leakage safety.
"""

from ai.ai_reinforcement import (
    CounterfactualSimulator,
    RLConfig,
    extract_price,
    sanitize_observation,
    smoke_test,
    snapshots_from_trades,
)

from conftest import build_trade


def test_one_sequence_per_trade(trades):
    sequences = snapshots_from_trades(trades)
    assert len(sequences) == len(trades)


def test_sequences_are_never_concatenated(trades):
    """
    CounterfactualSimulator walks forward from an entry index to the END of
    the list it is given. Concatenating trades would resolve one trade's entry
    against the next trade's price path -- a different symbol, days later --
    producing fabricated returns indistinguishable from real ones.
    """
    sequences = snapshots_from_trades(trades)
    for trade, sequence in zip(trades, sequences):
        # T0 plus one snapshot per evolution point, and nothing from any
        # other trade.
        assert len(sequence) == len(trade["price_evolution"]) + 1


def test_opening_snapshot_is_the_decision_moment(trades):
    opening = snapshots_from_trades(trades)[0][0]
    assert opening["price"] == trades[0]["entry"]["price"]
    assert opening["direction"] == "BUY"
    assert any(k.startswith("open.") for k in opening)
    assert any(k.startswith("entry.") for k in opening)


def test_evolution_snapshots_carry_every_timeframe(trades):
    snapshot = snapshots_from_trades(trades)[0][1]
    for prefix in ("m1.", "m5.", "h1.", "point."):
        assert any(k.startswith(prefix) for k in snapshot), prefix


def test_every_snapshot_exposes_a_usable_price(trades):
    """extract_price returning None would silently abort the simulation."""
    for sequence in snapshots_from_trades(trades):
        for snapshot in sequence:
            assert extract_price(snapshot) is not None


def test_trades_without_a_forward_path_are_skipped():
    """An entry with nothing after it cannot be walked forward."""
    assert snapshots_from_trades([build_trade(points=0)]) == []


def test_malformed_trades_do_not_abort_the_batch(trades):
    sequences = snapshots_from_trades([None, {"ticket": 1}] + trades)
    assert len(sequences) == len(trades)


def test_snapshots_survive_the_leakage_filter(trades):
    """
    RL strips known future keys before vectorizing. If that filter removed
    everything, training would run on empty state vectors and still "work".
    """
    snapshot = snapshots_from_trades(trades)[0][1]
    clean = sanitize_observation(snapshot, RLConfig().categorical_buckets)
    assert len(clean) > 10


def test_simulator_produces_a_finite_return(trades):
    sequence = snapshots_from_trades(trades)[0]
    outcome = CounterfactualSimulator(RLConfig()).simulate(sequence, 0)
    assert outcome.return_pct == outcome.return_pct   # not NaN


def test_smoke_test_still_passes():
    result = smoke_test()
    assert result["rl_version"]
    assert result["counterfactual_return_pct"] is not None
