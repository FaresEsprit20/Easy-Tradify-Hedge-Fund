"""
Every chained probability scorer must be signed against the trade direction.

`base_probability` in the scoring chain is the probability that the CHOSEN
direction is correct -- it is NOT an absolute bullish/bearish market read. So
a scorer that reads BULLISH must ADD probability to a BUY and SUBTRACT it from
a SELL. A scorer that decides the sign from its market read alone gets every
short trade backwards.

This exact bug has now been found three separate times in this codebase:

  * calculate_gnn_final_score  -- judged alignment with `base_probability > 50`
  * calculate_smc_final_score  -- same inversion, same fix
  * calculate_pattern_final_score -- never received best_direction at all; it
    was the last of the eight chained scorers still signing off the market
    read alone.

The pattern case was measurable on 215 real MT5 trades: splitting by the
ledger delta's sign gave +0.4063R on BUY trades and -0.4296R on SELL trades --
nearly equal magnitude, opposite sign, which is what a sign error looks like.
Pooled across both directions the two halves cancelled to +0.0260R (p=0.89),
so the component measured as pure noise while firing on 80.5% of trades. 26%
of trades were receiving a mean 12.3 probability points in the wrong
direction.

Three times is a class of defect, not an incident, so this file tests the
property directly rather than the three instances: for each scorer, feed the
same market read with best_direction BUY and then SELL, and require the
contribution to flip sign. A scorer added later that forgets best_direction
fails here without anyone remembering to write a test for it.
"""

import inspect

import pytest

from core.asset_analysis import calculate_pattern_final_score
from core.asset_analysis_gnn import calculate_gnn_final_score
from core.asset_analysis_smc import calculate_smc_final_score


def _bullish_pattern_result():
    """A pattern payload whose weighted direction is unambiguously BULLISH."""
    return {
        "timeframes": {
            "H1": {
                "patterns": {
                    "double_bottom": {
                        "detected": True,
                        "confidence": 0.9,
                        "relevance": 0.9,
                        "direction": "BULLISH",
                    }
                }
            }
        }
    }


def _bearish_pattern_result():
    return {
        "timeframes": {
            "H1": {
                "patterns": {
                    "double_top": {
                        "detected": True,
                        "confidence": 0.9,
                        "relevance": 0.9,
                        "direction": "BEARISH",
                    }
                }
            }
        }
    }


# --------------------------------------------------------------------------
# the property, stated once per scorer
# --------------------------------------------------------------------------

SCORERS = [
    pytest.param(
        calculate_pattern_final_score,
        _bullish_pattern_result(),
        "pattern_contribution",
        id="pattern",
    ),
    pytest.param(
        calculate_gnn_final_score,
        {
            "available": True,
            "recommendation": "BULLISH",
            "recommendation_score": 80,
            "data_quality": "REAL",
        },
        "gnn_contribution",
        id="gnn",
    ),
    pytest.param(
        calculate_smc_final_score,
        {"available": True, "recommendation": "BULLISH", "score": 80},
        "smc_contribution",
        id="smc",
    ),
]


@pytest.mark.parametrize("scorer, payload, key", SCORERS)
def test_a_bullish_read_helps_a_buy_and_hurts_a_sell(scorer, payload, key):
    """The same market read must not push both directions the same way."""
    on_buy = scorer(payload, 50.0, best_direction="BUY")[key]
    on_sell = scorer(payload, 50.0, best_direction="SELL")[key]

    assert on_buy > 0, (
        "%s: a BULLISH read must ADD probability to a BUY, got %+.2f"
        % (scorer.__name__, on_buy)
    )
    assert on_sell < 0, (
        "%s: a BULLISH read must SUBTRACT probability from a SELL -- this is "
        "the direction-blind sign bug; got %+.2f" % (scorer.__name__, on_sell)
    )


@pytest.mark.parametrize("scorer, payload, key", SCORERS)
def test_every_chained_scorer_accepts_best_direction(scorer, payload, key):
    """
    A scorer that cannot be told the trade direction cannot be signed
    correctly. `pattern` shipped for a long time without this parameter, so
    the omission is checked as its own failure rather than being inferred
    from a wrong number.
    """
    params = inspect.signature(scorer).parameters
    assert "best_direction" in params, (
        "%s does not accept best_direction, so its contribution is signed "
        "from the market read alone" % scorer.__name__
    )


@pytest.mark.parametrize("scorer, payload, key", SCORERS)
def test_the_final_score_moves_with_the_contribution(scorer, payload, key):
    """
    The sign fix is worthless if the caller reads `final_score` and that
    field was computed from an unsigned contribution -- which is how the
    GNN and SMC wiring bugs stayed invisible. Tie the two together.
    """
    for direction in ("BUY", "SELL"):
        out = scorer(payload, 50.0, best_direction=direction)
        assert out["final_score"] == pytest.approx(
            50.0 + out[key], abs=0.05
        ), (
            "%s (%s): final_score %.2f does not equal base + contribution "
            "(%.2f)" % (scorer.__name__, direction, out["final_score"], out[key])
        )


# --------------------------------------------------------------------------
# pattern-specific, because it is the one just fixed
# --------------------------------------------------------------------------

def test_a_bearish_pattern_is_the_mirror_image():
    """Both reads must respond to direction, not just the bullish one."""
    bear = _bearish_pattern_result()
    on_buy = calculate_pattern_final_score(bear, 50.0, best_direction="BUY")
    on_sell = calculate_pattern_final_score(bear, 50.0, best_direction="SELL")

    assert on_buy["pattern_contribution"] < 0
    assert on_sell["pattern_contribution"] > 0
    assert on_buy["aligned"] is False
    assert on_sell["aligned"] is True


def test_the_magnitude_is_unchanged_only_the_sign_moves():
    """
    The correction must be a pure sign flip. If the magnitude also changed,
    something was retuned alongside the fix -- which is how a validated
    change gets bundled with an unvalidated one.
    """
    bull = _bullish_pattern_result()
    on_buy = calculate_pattern_final_score(bull, 50.0, best_direction="BUY")
    on_sell = calculate_pattern_final_score(bull, 50.0, best_direction="SELL")

    assert on_buy["pattern_contribution"] == pytest.approx(
        -on_sell["pattern_contribution"], abs=1e-9
    )
    assert on_buy["pattern_score"] == on_sell["pattern_score"]
    assert on_buy["pattern_recommendation"] == on_sell["pattern_recommendation"] == "BULLISH"


def test_the_recommendation_stays_a_market_read():
    """
    `pattern_recommendation` is consumed elsewhere (the price-evolution
    encoder maps it through PATTERN_DIRECTION_MAP) as a bullish/bearish
    market read. The fix changes how that read is APPLIED, and must not
    redefine what it means -- otherwise every stored payload's meaning
    silently changes.
    """
    bull = _bullish_pattern_result()
    for direction in ("BUY", "SELL"):
        out = calculate_pattern_final_score(bull, 50.0, best_direction=direction)
        assert out["pattern_recommendation"] == "BULLISH"


def test_a_neutral_read_contributes_nothing_either_way():
    empty = {"timeframes": {}}
    for direction in ("BUY", "SELL"):
        out = calculate_pattern_final_score(empty, 61.0, best_direction=direction)
        assert out["pattern_contribution"] == 0
        assert out["final_score"] == 61.0
        assert out["aligned"] is True


def test_the_default_direction_preserves_the_old_long_behaviour():
    """
    The parameter defaults to BUY, matching the sibling scorers, so a caller
    that has not been updated behaves exactly as it did before rather than
    raising.
    """
    bull = _bullish_pattern_result()
    assert (
        calculate_pattern_final_score(bull, 50.0)["pattern_contribution"]
        == calculate_pattern_final_score(bull, 50.0, best_direction="BUY")[
            "pattern_contribution"
        ]
    )


# --------------------------------------------------------------------------
# the exhaustive guard: no scorer may be direction-blind by accident
# --------------------------------------------------------------------------

# Scorers that legitimately do not take a direction, each with the reason why.
# A scorer belongs here only if its adjustment is genuinely symmetric between
# a long and a short taken at the same instant -- NOT merely because it
# currently has no direction argument.
DIRECTION_SYMMETRIC = {
    "calculate_gap_slippage_final_score":
        "pure penalty: a gapped bar or thin liquidity degrades fill quality "
        "identically for a long and a short, and the function can only ever "
        "subtract. There is no sign to get wrong.",
    "calculate_nested_zone_final_score":
        "measures whether the zone being traded is backed by a higher "
        "timeframe zone. That is a quality property of the level itself, not "
        "a directional read -- an HTF-backed zone is better evidence for "
        "whichever side is being taken off it.",
    "calculate_rvam_final_score":
        "receives an already-signed score from score_rvam_confirmation(), "
        "which DOES take direction and resolves the direction-dependent "
        "ABSORPTION case there. This function only applies and clamps it.",
}


def _chain_scorers():
    """Every *_final_score entry point that feeds the probability chain."""
    import importlib

    modules = [
        "core.adr_exhaustion", "core.asset_analysis", "core.asset_analysis_gnn",
        "core.asset_analysis_smc", "core.dxy_confluence", "core.exhaustion_filter",
        "core.gap_slippage_detector",
        "core.nested_zone_confluence", "core.order_flow_forensics", "core.rvam",
        "core.trend_cascade",
    ]
    found = {}
    for name in modules:
        mod = importlib.import_module(name)
        for attr in dir(mod):
            if not attr.startswith("calculate_") or not attr.endswith("_final_score"):
                continue
            fn = getattr(mod, attr)
            if callable(fn) and getattr(fn, "__module__", "") == name:
                found[attr] = fn
    return found


def test_every_chain_scorer_is_direction_aware_or_explicitly_symmetric():
    """
    The guard that would have caught the pattern bug without anyone
    suspecting it.

    A scorer added to the chain later must either accept a direction, or be
    listed in DIRECTION_SYMMETRIC with a stated reason. Silence is not an
    option: an unclassified scorer fails this test, so the question "does
    this thing need to know which way we're trading?" has to be answered
    once, in writing, for every contributor to the probability.
    """
    scorers = _chain_scorers()
    assert len(scorers) >= 10, (
        "only found %d chain scorers -- the discovery list is stale and this "
        "guard is no longer exhaustive" % len(scorers)
    )

    unclassified = []
    for name, fn in sorted(scorers.items()):
        params = inspect.signature(fn).parameters
        if any("direction" in p for p in params):
            continue
        if name in DIRECTION_SYMMETRIC:
            continue
        unclassified.append(name)

    assert not unclassified, (
        "these scorers contribute to the probability but neither accept a "
        "direction nor are documented as direction-symmetric: %s\n"
        "base_probability is the probability the CHOSEN direction is correct, "
        "so a scorer signing its contribution from a bullish/bearish market "
        "read alone gets every short backwards. Either take best_direction, "
        "or add an entry to DIRECTION_SYMMETRIC saying why the adjustment is "
        "the same for a long and a short." % ", ".join(unclassified)
    )


def test_the_symmetric_allowlist_has_not_gone_stale():
    """
    An allowlist that names scorers which no longer exist, or which have
    since gained a direction parameter, is a comment pretending to be a
    check. Both cases fail here.
    """
    scorers = _chain_scorers()
    for name in DIRECTION_SYMMETRIC:
        assert name in scorers, (
            "%s is on the direction-symmetric allowlist but is not a chain "
            "scorer any more -- remove the entry" % name
        )
        params = inspect.signature(scorers[name]).parameters
        assert not any("direction" in p for p in params), (
            "%s now takes a direction, so it is no longer symmetric -- remove "
            "it from DIRECTION_SYMMETRIC" % name
        )


def test_the_ledger_note_records_which_way_the_read_pointed():
    """
    The `aligned` key exists so _final_score_note() can write "aligned" or
    "OPPOSED to trade direction" into the probability ledger. Without it the
    ledger records a delta on 80.5% of trades and says nothing about why.
    """
    from core.asset_analysis import _final_score_note

    opposed = calculate_pattern_final_score(
        _bullish_pattern_result(), 50.0, best_direction="SELL"
    )
    note = _final_score_note(opposed, "pattern")
    assert "OPPOSED" in note, note
