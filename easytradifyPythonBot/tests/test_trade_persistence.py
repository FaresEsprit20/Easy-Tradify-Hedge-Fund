"""
What actually reaches Firebase for a live trade.

Every failure guarded here was found in production data, not in review, and
every one of them was silent -- the monitor logged healthy while the record it
was writing was unusable:

  * price_evolution held 1-2 points on trades that ran 3.3 hours, where the
    60s interval implies ~200. Three independent causes, all invisible.
  * analysis_at_open stored the three timeframes compressed and buried at
    `full_raw_analysis.analysis.{m1,m5,h1}`, so no reader in ai/ could find
    final_verdict or the probability ledger.
  * analysis_at_close stored EMPTY timeframes because the writer looked for
    three key spellings and the producer used a fourth.
  * close_reason was the literal "SL_TP_HIT" on every close, merging "hit
    target" with "hit stop" -- the two outcomes the system exists to tell
    apart.
"""

import pytest

from ai.price_evolution_encoder import PriceEvolutionEncoder, _num
from core.execution import DEAL_REASON_LABELS


# --------------------------------------------------------------------------
# the encoder crash that emptied price_evolution
# --------------------------------------------------------------------------

def test_num_treats_an_explicit_none_as_missing():
    """
    dict.get(key, default) returns the default only when the key is ABSENT.
    A key present with value None returns None, and None * 10 raises. That
    one-line distinction is what emptied price_evolution.
    """
    assert _num({"x": None}, "x", 50) == 50      # present but None
    assert _num({}, "x", 50) == 50               # absent
    assert _num({"x": 7}, "x", 50) == 7          # real value survives
    assert _num({"x": "12.5"}, "x", 50) == 12.5  # numeric string
    assert _num({"x": "abc"}, "x", 50) == 50     # unparseable
    assert _num({"x": True}, "x", 50) == 50      # bool is not a measurement


def test_encoding_survives_a_none_timing_confidence():
    """
    analyze_institutional_signal emits micro_structure.timing_confidence =
    None whenever tick data is unavailable -- the documented FALLBACK path,
    which fires routinely outside liquid hours. That must not be able to
    destroy the point.
    """
    analysis = {
        "micro_structure": {"timing_confidence": None, "entry_confidence": None},
        "entry_analysis": {"timing_confidence": None},
        "final_verdict": {"probability_percent": None, "timing_confidence": None},
        "directional_analysis": {"buy_probability": None, "sell_probability": None},
    }
    encoded = PriceEvolutionEncoder().encode(analysis)
    assert isinstance(encoded, dict) and encoded


def test_a_price_point_keeps_the_probability_ledger():
    """
    The ledger is what every component measurement reads. If encoding drops
    it, the forward walk silently carries less than the decision snapshot.
    """
    from ai.price_evolution_decoder import PriceEvolutionDecoder

    ledger = [{"step": "pattern", "before": 50.0, "after": 64.4, "delta": 14.4},
              {"step": "smc", "before": 64.4, "after": 71.4, "delta": 7.0}]
    analysis = {"final_verdict": {"probability_percent": 71.4,
                                  "probability_ledger": ledger}}

    back = PriceEvolutionDecoder().decode(PriceEvolutionEncoder().encode(analysis))
    out = (back.get("final_verdict") or {}).get("probability_ledger")
    assert out, "probability_ledger did not survive the round trip"
    assert [s["step"] for s in out] == ["pattern", "smc"]


# --------------------------------------------------------------------------
# analysis_at_open / analysis_at_close shape
# --------------------------------------------------------------------------

class _FakeFirebase:
    """Just enough FirebaseService to exercise _extract_analysis_data."""

    def __init__(self):
        from core.firebase.firebase_service import FirebaseService
        self._extract = FirebaseService._extract_analysis_data.__get__(self)
        self._clean_dict = lambda d: d


def test_the_m1_analysis_is_stored_flat_and_not_rewrapped():
    """
    The caller supplies the M1 analysis. It must land at the TOP level of
    analysis_at_open, and the payload must NOT also be nested under
    `full_raw_analysis` -- that duplicate is what hid the analysis from every
    consumer and doubled the document size.

    Storage is M1-only by decision (see STORE_M1_ONLY in
    monitor/firebase_helpers.py): the M1 payload already carries
    higher_timeframe, h1_alignment and trend_cascade, so the separate m5/h1
    re-runs were near-duplicate bulk against a 1 MiB document limit.
    """
    fb = _FakeFirebase()
    payload = {
        "m1_analysis_raw": {"final_verdict": {"probability_percent": 71.4}},
        "_encoded": False,
    }
    out = fb._extract(payload)

    assert out["m1_analysis_raw"]["final_verdict"]["probability_percent"] == 71.4
    assert "full_raw_analysis" not in out, (
        "payload re-wrapped under full_raw_analysis -- this is the nesting "
        "that made analysis_at_open unreadable"
    )
    assert out["_encoded"] is False


def test_higher_timeframes_are_not_written_anywhere():
    """M1-only means M1-only: no m5/h1 field may be emitted."""
    fb = _FakeFirebase()
    out = fb._extract({
        "m1_analysis_raw": {"final_verdict": {"probability_percent": 71.4}},
        "m5_analysis_raw": {"trend": "BULLISH"},
        "h1_analysis_raw": {"trend": "BEARISH"},
    })
    assert "m5_analysis_raw" not in out
    assert "h1_analysis_raw" not in out


def test_full_raw_analysis_is_kept_when_it_is_the_only_copy():
    """
    Dropping the wrapper must not lose data for a caller that supplies no
    per-timeframe breakdown -- then it IS the analysis.
    """
    fb = _FakeFirebase()
    out = fb._extract({"final_verdict": {"probability_percent": 60.0}})
    assert "full_raw_analysis" in out


# --------------------------------------------------------------------------
# close reason
# --------------------------------------------------------------------------

def test_close_reason_distinguishes_target_from_stop():
    """
    "SL_TP_HIT" told us a stop OR a target was hit and never which. Any label
    that cannot separate a winner from a loser is worse than absent, because
    it looks like data.
    """
    assert DEAL_REASON_LABELS[4] == "STOP_LOSS"     # DEAL_REASON_SL
    assert DEAL_REASON_LABELS[5] == "TAKE_PROFIT"   # DEAL_REASON_TP
    assert DEAL_REASON_LABELS[6] == "STOP_OUT"      # DEAL_REASON_SO
    assert DEAL_REASON_LABELS[3] == "EXPERT"        # closed by the EA
    assert len(set(DEAL_REASON_LABELS.values())) >= 4


def test_an_unresolvable_close_reason_is_unknown_not_a_guess():
    """A missing label is recoverable later; a wrong one is not."""
    from core.execution import resolve_close_reason
    assert resolve_close_reason(-1) == "UNKNOWN"


def test_no_source_file_still_hardcodes_the_ambiguous_label():
    """
    The literal must not creep back in. It is allowed to appear in a comment
    explaining the fix, but never as a value being written.
    """
    import pathlib, re

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in list(root.glob("monitor/*.py")) + list(root.glob("core/**/*.py")):
        for num, line in enumerate(path.read_text(encoding="utf-8",
                                                  errors="replace").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'close_reason\s*=\s*["\']SL_TP_HIT["\']', line):
                offenders.append(f"{path.name}:{num}")
    assert not offenders, (
        "close_reason hardcoded to the ambiguous label at: %s" % ", ".join(offenders)
    )


# --------------------------------------------------------------------------
# risk state on every price point
# --------------------------------------------------------------------------

def test_every_price_point_records_where_the_stop_was():
    """
    Break-even and trailing MOVE the stop mid-trade. Without the stop level on
    each point, the forward walk cannot answer the first question a losing
    trade raises: was the stop where it started, or had it been pulled to
    entry and then clipped by noise?
    """
    from monitor.trade_persistence import _risk_state

    buy = {"sl": 1.1010, "tp": 1.1100, "type": 0}
    state = _risk_state(1, buy, entry_price=1.1000, pip_size=0.0001,
                        initial_sl=1.0980)
    assert state["sl"] == 1.1010
    assert state["tp"] == 1.1100
    assert state["sl_moved_pips"] == 30.0
    assert state["sl_at_or_beyond_breakeven"] is True


def test_breakeven_direction_is_not_inverted_for_a_sell():
    """
    "Stop on the profitable side of entry" is ABOVE entry for a long and
    BELOW it for a short. Getting that backwards would label every protected
    short as unprotected -- the same direction-blindness that broke `pattern`.
    """
    from monitor.trade_persistence import _risk_state

    # SELL with the stop pulled DOWN below entry: protected.
    protected = _risk_state(2, {"sl": 1.0990, "tp": 1.0900, "type": 1},
                            entry_price=1.1000, pip_size=0.0001)
    assert protected["sl_at_or_beyond_breakeven"] is True
    assert protected["sl_distance_from_entry_pips"] == 10.0

    # SELL with the stop still ABOVE entry: not yet protected.
    exposed = _risk_state(3, {"sl": 1.1020, "tp": 1.0900, "type": 1},
                          entry_price=1.1000, pip_size=0.0001)
    assert exposed["sl_at_or_beyond_breakeven"] is False
    assert exposed["sl_distance_from_entry_pips"] == -20.0


def test_risk_state_never_raises_on_a_degenerate_position():
    """Telemetry must not be able to break the write it is attached to."""
    from monitor.trade_persistence import _risk_state

    for pos in ({}, {"sl": None, "tp": None}, {"sl": 0, "type": None}):
        state = _risk_state(4, pos, entry_price=None, pip_size=0)
        assert isinstance(state, dict)
