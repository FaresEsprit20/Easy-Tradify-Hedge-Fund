# ============================================================
# COPY-TRADE CLOSE PATH -- REGRESSION TESTS
# ============================================================
# A live XAUUSD trade (ticket 1921232120) opened, hit its stop, and then span
# in the position monitor at roughly one error every two seconds:
#
#   📉 XAUUSD closed (ticket: 1921232120) - SL/TP HIT detected
#   ⚠️ Position monitor error: '>' not supported between 'NoneType' and 'int'
#
# ...forever. The trade was never saved. Two independent defects had to line
# up, and both are pinned below.
#
#   1. The cache stores execution_result.get("take_profit") with NO default,
#      so the key is always present and holds None on a trade opened without
#      a TP -- the documented normal case. Reading it back with
#      .get("tp", 0) returns None, because a dict default applies only to a
#      MISSING key, never to a present-but-None one. `tp > 0` then raised.
#
#   2. The cache delete and _cleanup_closed_position() sat on the happy path
#      after that comparison, so the exception skipped them. The ticket stayed
#      in the cache, the next pass re-detected the same close, and it looped.
#
# Defect 1 alone loses one trade record. Defect 2 turns it into a permanent
# spin that also blocks every later close. The fix addresses both, so both are
# tested -- fixing only the None would leave the monitor one exception away
# from the same wedge.
# ============================================================

import ast
import inspect
import io
import os

import pytest


# --------------------------------------------------------------------------
# 1. The None hazard
# --------------------------------------------------------------------------

def test_dict_get_default_does_not_protect_against_none():
    """
    The trap itself, stated as a test so nobody 'simplifies' _num back into a
    .get(key, 0). This is standard dict behaviour, and it is exactly why the
    original code looked correct while being wrong.
    """
    cache = {"tp": None}
    assert cache.get("tp", 0) is None, "a default does NOT replace a None value"

    with pytest.raises(TypeError):
        cache.get("tp", 0) > 0


def test_num_coerces_every_shape_a_price_field_arrives_in():
    from api.execute_copy_trade import _num

    # The failure that was actually observed live.
    assert _num(None) == 0.0
    # Ordinary values must pass through unchanged.
    assert _num(0) == 0.0
    assert _num(5) == 5.0
    assert _num(4401.85) == pytest.approx(4401.85)
    # MT5 and Firebase both hand back numeric strings in places.
    assert _num("3.5") == pytest.approx(3.5)
    # Junk must degrade to the default rather than raise: this runs inside the
    # position monitor, where an exception costs the whole close.
    assert _num("") == 0.0
    assert _num("abc") == 0.0
    assert _num({}) == 0.0
    assert _num(None, default=-1.0) == -1.0


def test_num_makes_the_original_comparison_safe():
    """The exact expression that raised, on the exact cached shape."""
    from api.execute_copy_trade import _num

    cached = {"sl": 4380.0, "tp": None}          # stop set, no take profit
    sl, tp = _num(cached.get("sl")), _num(cached.get("tp"))

    assert (sl > 0 and tp > 0) is False           # no raise, and correctly False
    assert sl > 0                                 # the SL-only branch still fires


# --------------------------------------------------------------------------
# 2. The wedge
# --------------------------------------------------------------------------

def _close_branch_nodes():
    """The `if not position:` body inside the position monitor loop."""
    from api import execute_copy_trade

    src = io.open(execute_copy_trade.__file__, encoding="utf-8").read()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # The close path is the Try that owns the cleanup calls in its finally.
        finally_src = "".join(ast.dump(n) for n in node.finalbody)
        if "_cleanup_closed_position" in finally_src:
            return node
    return None


def test_cleanup_runs_even_when_reconstructing_the_close_fails():
    """
    The cache delete and _cleanup_closed_position() must be in a `finally`.

    On the happy path they are unreachable whenever anything above them
    raises, and the ticket is then never evicted -- which is what produced the
    endless loop rather than a single lost trade.
    """
    node = _close_branch_nodes()
    assert node is not None, (
        "no try/finally owns _cleanup_closed_position -- the close path can "
        "again leave a ticket in _position_data_cache and spin forever")

    finally_src = "".join(ast.dump(n) for n in node.finalbody)
    assert "_position_data_cache" in finally_src, (
        "the cache eviction must be in the finally, not the happy path")
    assert "checked_tickets" in finally_src, (
        "checked_tickets.add must be in the finally, or a failed close is "
        "retried on every pass")


def test_close_path_reads_cached_prices_through_num():
    """
    Guards the specific regression: a raw .get("tp", 0) reappearing in the
    close block would restore the crash verbatim.
    """
    from api import execute_copy_trade

    src = io.open(execute_copy_trade.__file__, encoding="utf-8").read()

    for field in ("sl", "tp", "price_open", "volume"):
        assert f'cached.get("{field}", 0)' not in src, (
            f'cached.get("{field}", 0) is back -- it returns None when the key '
            f"is present and null, which is the normal shape for an optional "
            f"TP. Use _num(cached.get(...)).")
