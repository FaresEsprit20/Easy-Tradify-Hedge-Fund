"""The extreme-volatility veto judges each instrument against its own ATR band."""

from core.veto_engine import VetoEngine


def test_gold_normal_volatility_is_not_extreme():
    veto, _ = VetoEngine().check_extreme_volatility(212.0, "XAUUSD", {"adaptive": True, "extreme": 371.2})
    assert veto is False


def test_above_own_98th_percentile_is_extreme():
    veto, reason = VetoEngine().check_extreme_volatility(400.0, "XAUUSD", {"adaptive": True, "extreme": 371.2})
    assert veto is True and "98th percentile" in reason


def test_without_a_usable_band_the_static_table_applies():
    engine = VetoEngine()
    assert engine.check_extreme_volatility(75.0, "EURUSD", {"adaptive": False, "extreme": 40})[0] is True
    assert engine.check_extreme_volatility(30.0, "EURUSD", None)[0] is False


def test_high_spread_gate_reads_the_spread_fact_not_a_short_circuited_check():
    """An earlier veto short-circuits check_all_vetos before high_spread runs;
    the unevaluated check read as 'passed' against a spread above the ceiling."""
    import inspect
    from core import decision_snapshot

    source = inspect.getsource(decision_snapshot)
    block = source[source.index('"high_spread",'):]
    block = block[:block.index("))")]
    assert "spread_valid" in block
