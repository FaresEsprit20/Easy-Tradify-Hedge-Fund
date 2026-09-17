import numpy as np

from engine_v2.data.clock import broker_offset_seconds, utc_to_broker
from engine_v2.market_model import indicators as ind
from engine_v2.market_model.structure import DOWN, UP, bos_events, trend_series, zigzag
from engine_v2.market_model.zones import displacement, fvg, supply_demand_zones


def test_broker_clock_follows_us_dst():
    summer = 1781481600   # 2026-06-15 00:00 UTC
    winter = 1768435200   # 2026-01-15 00:00 UTC
    assert broker_offset_seconds(summer) == 3 * 3600
    assert broker_offset_seconds(winter) == 2 * 3600
    assert list(utc_to_broker(np.array([winter, summer]))) == [winter + 7200, summer + 10800]


def _zig_path():
    # up 10, down 5, up 10, down 5, up 10 (HH/HL), ATR ~1
    seg = [np.linspace(0, 10, 11), np.linspace(10, 5, 6)[1:], np.linspace(5, 15, 11)[1:],
           np.linspace(15, 10, 6)[1:], np.linspace(10, 20, 11)[1:]]
    return np.concatenate(seg)


def test_zigzag_confirms_swings_only_after_reversal():
    c = _zig_path()
    atr = np.ones_like(c)
    sw = zigzag(c, c, c, atr, 1.0)
    # the start bar is a swing low confirmed one bar later; then the alternating legs
    assert list(sw.kind) == [-1, 1, -1, 1, -1]
    assert list(sw.price) == [0, 10, 5, 15, 10]
    assert all(sw.available_idx > sw.idx)          # never known on the extreme bar itself


def test_structure_trend_up_after_higher_highs_and_lows():
    c = _zig_path()
    sw = zigzag(c, c, c, np.ones_like(c), 1.0)
    tr = trend_series(sw, len(c))
    assert tr[-1] == UP


def test_bos_up_when_close_breaks_last_swing_high():
    c = _zig_path()
    sw = zigzag(c, c, c, np.ones_like(c), 1.0)
    tr = trend_series(sw, len(c))
    bos_up, bos_dn, *_ = bos_events(c, sw, tr)
    i = int(np.flatnonzero(bos_up)[0])
    assert c[i] > 10 and c[i - 1] <= 10


def test_bullish_fvg_and_displacement():
    high = np.array([1.0, 1.1, 1.5, 1.6])
    low = np.array([0.9, 1.0, 1.2, 1.4])
    atr = np.full(4, 0.5)
    flag, top, bot = fvg(high, low, atr, 1)
    assert flag[2] and top[2] == 1.2 and bot[2] == 1.0    # low[2]=1.2 > high[0]=1.0, gap 0.2 >= 0.05
    o = np.array([1.0, 1.0, 1.0]); h = np.array([1.1, 1.1, 2.0]); l = np.array([0.9, 0.9, 1.0]); cl = np.array([1.0, 1.0, 1.9])
    assert displacement(o, h, l, cl, np.full(3, 0.5))[2] == 1


def test_demand_zone_from_base_and_departure():
    # 3 flat base bars then a strong up close
    o = np.array([1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.01])
    h = np.array([1.02, 1.02, 1.01, 1.012, 1.011, 1.30, 1.40])
    l = np.array([0.98, 0.98, 0.99, 0.995, 0.996, 1.00, 1.28])
    c = np.array([1.00, 1.00, 1.001, 1.002, 1.001, 1.25, 1.35])
    atr = np.full(7, 0.05)
    zones = supply_demand_zones(o, h, l, c, atr)
    assert any(z.side == 1 and z.departure_idx == 5 for z in zones)
    z = [z for z in zones if z.side == 1][0]
    assert z.distal < z.proximal


def test_rsi_bounds_and_efficiency_ratio():
    x = np.cumsum(np.ones(50))
    assert np.nanmax(ind.rsi(x)) == 100.0
    er = ind.efficiency_ratio(x, 20)
    assert np.isclose(er[-1], 1.0)
