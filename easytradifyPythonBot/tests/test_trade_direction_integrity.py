# ============================================================
# TRADE DIRECTION INTEGRITY -- REGRESSION TESTS
# ============================================================
# SELL orders sent through the copy-trade controller were stored as BUY.
# Two independent defects, in the open path and the close path, each of which
# silently inverts the sign of a trade's return.
#
# OPEN (monitor/firebase_helpers.save_trade_open_to_firebase)
#   order_type came ONLY from analysis_result["config"]["executed_direction"],
#   defaulting to "BUY". That key is produced by core/asset_analysis.py, so it
#   exists on the monitor's path and NOT on the copy-trade path, which passes
#   analysis_result={} deliberately to keep the open-save fast. Every
#   copy-trade trade was therefore recorded as a BUY.
#
#   Worse than a label: order_type is passed into
#   get_all_timeframe_analysis_raw(), so analysis_at_open -- the feature set
#   every model reads -- was computed for the OPPOSITE side of the open trade.
#
# CLOSE (monitor/firebase_helpers.save_trade_close_to_firebase)
#   order_type = "BUY"; if price_close < price_open: order_type = "SELL"
#
#   That is direction inferred from the OUTCOME. Observed live on ticket
#   1921284905: a confirmed BUY, stored as "SELL", because it lost. And since
#   direction was always chosen to agree with the price move, every closed
#   trade reads back as a winner -- any win rate computed from the stored
#   direction measures the inference, not the trades.
#
# Both now resolve direction from what was actually placed, and the close path
# stores None rather than guessing.
# ============================================================

import pytest

from monitor import trade_persistence as fh


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("BUY", "BUY"),
    ("SELL", "SELL"),
    ("buy", "BUY"),
    (" sell ", "SELL"),
    (None, None),
    ("", None),
    ("LONG", None),        # not a direction this system uses -- do not guess
    (0, None),
    ("BUY_LIMIT", None),
])
def test_normalise_direction(raw, expected):
    assert fh._normalise_direction(raw) == expected


# --------------------------------------------------------------------------
# the close path must never infer direction from price
# --------------------------------------------------------------------------

def test_direction_comes_from_the_record_not_the_price_move():
    """
    A losing BUY must stay a BUY. Under the old rule (`price fell -> SELL`)
    this exact case produced "SELL".
    """
    losing_buy = {"order_type": "BUY", "price": 1.16346}
    assert fh._direction_of_record(1921284905, losing_buy) == "BUY"

    losing_sell = {"order_type": "SELL", "price": 4401.85}
    assert fh._direction_of_record(1921232120, losing_sell) == "SELL"


def test_direction_field_is_accepted_as_well_as_order_type():
    """Records written by different paths use one name or the other."""
    assert fh._direction_of_record(1, {"direction": "SELL"}) == "SELL"
    assert fh._direction_of_record(2, {"order_type": "SELL"}) == "SELL"


def test_unknown_direction_is_none_not_a_default(monkeypatch):
    """
    The whole point: refuse to invent a direction.

    Returning "BUY" here is what made a SELL look like a BUY. A None is
    visible to the next reader; a wrong default is not.
    """
    monkeypatch.setattr(fh, "_normalise_direction", fh._normalise_direction)
    # No usable direction in the document, and the Mongo lookup unavailable.
    import monitor.trade_sink as sink
    monkeypatch.setattr(sink, "is_enabled", lambda: False)

    assert fh._direction_of_record(999, {}) is None
    assert fh._direction_of_record(999, {"order_type": "LONG"}) is None
    assert fh._direction_of_record(999, None) is None


def test_close_path_no_longer_derives_direction_from_price():
    """
    Source guard. The inference was three lines and easy to reintroduce while
    'simplifying', and it cannot be caught by reading the stored data -- the
    values look perfectly plausible.
    """
    import io
    src = io.open(fh.__file__, encoding="utf-8").read()

    # The exact shape of the old bug.
    assert 'order_type = "BUY"\n        if price_open > 0' not in src, (
        "direction is being inferred from the price move again")

    close_fn_start = src.index("def save_trade_close(")
    close_fn = src[close_fn_start:close_fn_start + 12000]
    assert "_direction_of_record" in close_fn, (
        "the close path must look the direction up, not derive it")


# --------------------------------------------------------------------------
# the open path must trust what was sent to the broker
# --------------------------------------------------------------------------

def test_open_path_prefers_the_executed_direction_over_the_default():
    """
    A SELL with an empty analysis_result -- the exact copy-trade shape -- must
    not fall through to the "BUY" default.
    """
    import io
    src = io.open(fh.__file__, encoding="utf-8").read()

    open_fn_start = src.index("def save_trade_open(")
    open_fn = src[open_fn_start:open_fn_start + 6000]

    assert 'config_data.get("executed_direction", "BUY")' not in open_fn, (
        'the open path is defaulting to "BUY" again: copy-trade passes '
        "analysis_result={} so executed_direction is absent and every SELL "
        "is recorded as a BUY")
    assert 'getattr(trade_result, "order_type", None)' in open_fn, (
        "the direction actually sent to the broker must win")


def test_open_record_carries_direction_for_the_close_path():
    """
    The close path looks up `direction`/`order_type` on the open record, and
    the AI layer reads trade["direction"]. Both must be written.
    """
    import io
    src = io.open(fh.__file__, encoding="utf-8").read()

    open_fn_start = src.index("def save_trade_open(")
    open_fn = src[open_fn_start:open_fn_start + 8000]

    assert '"direction": order_type' in open_fn, (
        "the open record must carry `direction`, or the close path has "
        "nothing authoritative to look up")
