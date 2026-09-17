# ai/state_readings.py
"""
State readings: can a component's MEASURED state call a side, where its label
cannot?

Most components publish a label that is neutral almost always -- supply/demand
says MONITOR on 96% of bars, support/resistance NEUTRAL on 70%, patterns
NEUTRAL on 87% -- so their groups have nothing to score (STRUCTURE 2.1% of
bars, ORDER_FLOW 5.9%, WAVE 12.9%). The state behind the label exists on every
bar: price IS somewhere relative to the zone, the level, the value area, the
wave.

Each candidate below turns that state into a side, on as many bars as the
state exists. Nothing is wired into the engine here -- this measures first:

  orientation   chosen on DISCOVERY only (does the state read with the move or
                against it?), never on the data it is then judged on
  judged        on the live market-stop trade (stop 1.5 x H1 ATR, target 1R,
                filled and exited on tick quotes): how often that side's trade
                finished positive, and its net R after real costs
  reported      discovery / validation / holdout separately, with the number of
                trades, against the 43.5% a random entry wins

A reading earns its place in the engine only if it beats the baseline on BOTH
unseen periods with at least MIN_TRADES trades. Everything else is recorded as
tested and left out, so it is not tried again by accident.

    python -m ai.state_readings
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
MIN_TRADES = 60
BASELINE_WIN = None      # measured from the data, not assumed


# ============================================================
# CANDIDATES
# ============================================================
# Each returns a side per bar: +1 buy, -1 sell, 0/nan = no reading.
# They are written in the component's own language; the orientation (whether
# the state reads with the move or against it) is decided on discovery.

def _atr_price(c) -> np.ndarray:
    a = c.num("atr_pips").astype(np.float64) * c.num("pip").astype(np.float64)
    return np.where(a > 0, a, np.nan)


def _num(c, name: str) -> np.ndarray:
    return c.num(name).astype(np.float64) if name in c.names() else np.full(c.n, np.nan)


def _text_is(c, name: str, value: str) -> np.ndarray:
    if name not in c.names():
        return np.zeros(c.n, bool)
    codes, vocab = c.text(name)
    match = {i for i, v in enumerate(vocab) if str(v).upper() == value.upper()}
    return np.isin(codes, list(match)) if match else np.zeros(c.n, bool)


def _side_where(condition: np.ndarray, side: np.ndarray) -> np.ndarray:
    out = np.where(condition, side, np.nan)
    return out


def sd_zone(c, max_atr: float) -> np.ndarray:
    """Supply/demand: demand below calls buy, supply above calls sell, while
    price is within `max_atr` of the zone. The component itself says MONITOR on
    96% of these bars."""
    dist = _num(c, "indicators.supply_demand.debug.distance_to_zone_pips") / np.maximum(c.num("atr_pips").astype(np.float64), 1e-9)
    demand = _num(c, "indicators.supply_demand.debug.is_demand_zone")
    side = np.where(demand > 0, 1.0, np.where(demand == 0, -1.0, np.nan))
    return _side_where((dist <= max_atr) & ~np.isnan(side), side)


def sr_level(c) -> np.ndarray:
    """Support/resistance: whichever pivot level price sits closer to calls the
    side -- nearer support buys, nearer resistance sells."""
    price = c.num("close").astype(np.float64)
    r1, s1 = _num(c, "indicators.support_resistance.r1"), _num(c, "indicators.support_resistance.s1")
    to_r, to_s = np.abs(r1 - price), np.abs(price - s1)
    side = np.where(to_s < to_r, 1.0, np.where(to_r < to_s, -1.0, np.nan))
    return _side_where(~np.isnan(to_r) & ~np.isnan(to_s), side)


def sr_pivot(c) -> np.ndarray:
    """Support/resistance: price above the pivot calls buy (continuation)."""
    above = _text_is(c, "indicators.support_resistance.debug.price_vs_pivot", "above")
    below = _text_is(c, "indicators.support_resistance.debug.price_vs_pivot", "below")
    return _side_where(above | below, np.where(above, 1.0, -1.0))


def value_area(c) -> np.ndarray:
    """Volume profile: above the value area calls sell, below calls buy --
    price returning to where volume actually transacted."""
    price = c.num("close").astype(np.float64)
    vah, val = _num(c, "indicators.volume_profile.vah"), _num(c, "indicators.volume_profile.val")
    side = np.where(price > vah, -1.0, np.where(price < val, 1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def poc_distance(c) -> np.ndarray:
    """Volume profile: which side of the point of control price sits on."""
    price = c.num("close").astype(np.float64)
    poc = _num(c, "indicators.volume_profile.poc")
    side = np.where(price > poc, -1.0, np.where(price < poc, 1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def premium_discount(c, edge_pct: float) -> np.ndarray:
    """SMC premium/discount: deep in discount buys, deep in premium sells."""
    pos = _num(c, "final_verdict.smc_analysis.premium_discount.position_pct")
    if np.all(np.isnan(pos)):
        pos = _num(c, "smc.analysis.premium_discount.position_pct")
    side = np.where(pos <= edge_pct, 1.0, np.where(pos >= 100 - edge_pct, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def fib_leg(c) -> np.ndarray:
    """Fib confluence: the direction of the leg being retraced."""
    up = _text_is(c, "indicators.fib_confluence.leg_direction", "UP")
    down = _text_is(c, "indicators.fib_confluence.leg_direction", "DOWN")
    return _side_where(up | down, np.where(up, 1.0, -1.0))


def round_magnet(c) -> np.ndarray:
    """Round numbers: the nearer round level is the magnet price drifts to."""
    to_r = _num(c, "indicators.round_numbers.distance_to_resistance_pips")
    to_s = _num(c, "indicators.round_numbers.distance_to_support_pips")
    side = np.where(to_r < to_s, 1.0, np.where(to_s < to_r, -1.0, np.nan))
    return _side_where(~np.isnan(to_r) & ~np.isnan(to_s), side)


def ema_stack(c) -> np.ndarray:
    """Trend: price above its own 200 EMA calls buy."""
    price = c.num("close").astype(np.float64)
    ema = _num(c, "indicators.trend.ema.ema_200")
    side = np.where(price > ema, 1.0, np.where(price < ema, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def ema_spread(c, min_atr: float) -> np.ndarray:
    """Trend: the 20/200 EMA gap, once it is wider than `min_atr` of ATR."""
    fast, slow = _num(c, "indicators.trend.ema.ema_20"), _num(c, "indicators.trend.ema.ema_200")
    gap = (fast - slow) / _atr_price(c)
    side = np.where(gap >= min_atr, 1.0, np.where(gap <= -min_atr, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def rsi_level(c, edge: float) -> np.ndarray:
    """RSI as a continuous state rather than a label: above 50+edge calls sell
    (mean reversion), below 50-edge calls buy."""
    rsi = _num(c, "indicators.rsi.rsi_14")
    side = np.where(rsi >= 50 + edge, -1.0, np.where(rsi <= 50 - edge, 1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def percent_b(c, edge: float) -> np.ndarray:
    """Bollinger %B: outside the band calls the reversion side."""
    pb = _num(c, "indicators.bollinger_bands.debug.percent_b")
    side = np.where(pb >= 1 - edge, -1.0, np.where(pb <= edge, 1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def macd_hist(c) -> np.ndarray:
    """MACD histogram sign, on every bar rather than at a cross."""
    h = _num(c, "indicators.macd.histogram")
    side = np.where(h > 0, 1.0, np.where(h < 0, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def fvg_side(c) -> np.ndarray:
    """ICT: price above the gap calls buy (the gap supports), below calls sell."""
    above = _num(c, "indicators.ict_concepts.price_above_fvg_pips")
    below = _num(c, "indicators.ict_concepts.price_below_fvg_pips")
    side = np.where(above > 0, 1.0, np.where(below > 0, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def pool_magnet(c) -> np.ndarray:
    """Order flow: the side holding more resting liquidity is the magnet."""
    hi = _num(c, "order_flow_forensics.liquidity_pool_volume_profile_confluence.equal_highs_pools.len")
    lo = _num(c, "order_flow_forensics.liquidity_pool_volume_profile_confluence.equal_lows_pools.len")
    side = np.where(hi > lo, 1.0, np.where(lo > hi, -1.0, np.nan))
    return _side_where(~np.isnan(side), side)


def wave_b_progress(c) -> np.ndarray:
    """Wave C: how far the correction has retraced, as a state."""
    pct = _num(c, "indicators.wave_c.data.wave_b_retracement_pct")
    up = _text_is(c, "indicators.wave_c.data.correction_direction", "UP")
    down = _text_is(c, "indicators.wave_c.data.correction_direction", "DOWN")
    side = np.where(up, -1.0, np.where(down, 1.0, np.nan))          # a correction ends against itself
    return _side_where(~np.isnan(pct) & ~np.isnan(side), side)


CANDIDATES: List[Tuple[str, str, Callable]] = [
    ("STRUCTURE", "supply/demand zone within 0.25 ATR", lambda c: sd_zone(c, 0.25)),
    ("STRUCTURE", "supply/demand zone within 1 ATR", lambda c: sd_zone(c, 1.0)),
    ("STRUCTURE", "supply/demand zone, any distance", lambda c: sd_zone(c, 1e9)),
    ("STRUCTURE", "nearer pivot level (support vs resistance)", sr_level),
    ("STRUCTURE", "price above/below pivot", sr_pivot),
    ("STRUCTURE", "nearer round number", round_magnet),
    ("STRUCTURE", "fib leg direction", fib_leg),
    ("ORDER_FLOW", "outside the value area", value_area),
    ("ORDER_FLOW", "side of the POC", poc_distance),
    ("ORDER_FLOW", "bigger resting liquidity pool", pool_magnet),
    ("SMC", "premium / discount, outer 25%", lambda c: premium_discount(c, 25.0)),
    ("SMC", "premium / discount, outer 10%", lambda c: premium_discount(c, 10.0)),
    ("SMC", "price above / below the FVG", fvg_side),
    ("TREND", "price vs EMA200", ema_stack),
    ("TREND", "EMA 20/200 gap over 0.25 ATR", lambda c: ema_spread(c, 0.25)),
    ("TREND", "EMA 20/200 gap over 1 ATR", lambda c: ema_spread(c, 1.0)),
    ("MOMENTUM", "MACD histogram sign", macd_hist),
    ("MEAN_REVERSION", "RSI 10 points from 50", lambda c: rsi_level(c, 10.0)),
    ("MEAN_REVERSION", "RSI 20 points from 50", lambda c: rsi_level(c, 20.0)),
    ("MEAN_REVERSION", "Bollinger %B outside 0.1", lambda c: percent_b(c, 0.1)),
    ("WAVE", "correction direction (wave C)", wave_b_progress),
]


# ============================================================
# MEASUREMENT
# ============================================================

class Trades:
    """The live market-stop trade for each side, from the study columns."""

    def __init__(self):
        from ai.component_repair import Columns, study_split

        self.c = Columns()
        cost = np.nan_to_num(self.c.num("ms_cost_r").astype(np.float64), nan=0.0)
        self.net = {1: self.c.num("br_ms_buy").astype(np.float64) - cost,
                    -1: self.c.num("br_ms_sell").astype(np.float64) - cost}
        self.have = ~np.isnan(self.net[1]) & ~np.isnan(self.net[-1])
        ts = self.c.num("ts").astype(np.float64)
        self.train, self.test, self.holdout, _, self.holdout_start = study_split(ts)
        codes, vocab = self.c.text("ctx.symbol")
        symbol = np.array([vocab[k] if k >= 0 else "" for k in codes], dtype=object)
        self.clusters = np.array([f"{s}|{int(t // 86400)}" for s, t in zip(symbol, np.nan_to_num(ts))], dtype=object)
        won_buy = self.net[1] > 0
        won_sell = self.net[-1] > 0
        self.baseline = float(np.mean(np.r_[won_buy[self.have], won_sell[self.have]]))

    def score(self, side: np.ndarray, mask: np.ndarray) -> Dict[str, Any]:
        from ai.component_calibration import cluster_mean_z

        m = mask & self.have & np.isin(side, (1.0, -1.0))
        n = int(m.sum())
        if n == 0:
            return {"n": 0}
        net = np.where(m, np.where(side == 1, self.net[1], self.net[-1]), np.nan)
        won = np.where(m, (net > 0).astype(float), np.nan)
        w, wz, days = cluster_mean_z(won, self.clusters, null=self.baseline)
        r, rz, _ = cluster_mean_z(net, self.clusters, null=0.0)
        return {"n": n, "days": int(days), "won": round(100 * w, 1), "won_z": round(wz, 2),
                "net_r": round(r, 3), "net_z": round(rz, 2)}


def evaluate(t: Trades, side: np.ndarray) -> Dict[str, Any]:
    """Orientation picked on discovery, then reported on each period."""
    as_is = t.score(side, t.train)
    flipped = t.score(-side, t.train)
    orient = 1 if (as_is.get("won") or 0) >= (flipped.get("won") or 0) else -1
    s = side * orient
    return {"orientation": "as-is" if orient > 0 else "inverted",
            "coverage_pct": round(100 * float(np.mean(np.isin(side, (1.0, -1.0)))), 1),
            "discovery": t.score(s, t.train), "validation": t.score(s, t.test), "holdout": t.score(s, t.holdout)}


def passes(result: Dict[str, Any], baseline: float) -> bool:
    """Beats a random entry on BOTH unseen periods, on enough trades."""
    for period in ("validation", "holdout"):
        p = result.get(period) or {}
        if p.get("n", 0) < MIN_TRADES or (p.get("won") or 0) <= 100 * baseline:
            return False
    return True


def run() -> Dict[str, Any]:
    t = Trades()
    out = []
    for group, name, fn in CANDIDATES:
        try:
            side = fn(t.c)
        except Exception as exc:                     # a missing column is a result, not a crash
            out.append({"group": group, "reading": name, "error": repr(exc)[:120]})
            continue
        res = evaluate(t, side)
        res.update(group=group, reading=name, passes=passes(res, t.baseline))
        out.append(res)
    out.sort(key=lambda r: -((r.get("holdout") or {}).get("won") or 0))
    return {"baseline_win_pct": round(100 * t.baseline, 1), "min_trades": MIN_TRADES,
            "holdout_start": t.holdout_start, "readings": out}


def get_status() -> Dict[str, Any]:
    return {"component": "state_readings", "candidates": len(CANDIDATES), "min_trades": MIN_TRADES}


def self_check() -> Dict[str, Any]:
    base = 0.435
    good = {"n": 100, "won": 50.0}
    assert passes({"validation": good, "holdout": good}, base)
    assert not passes({"validation": good, "holdout": {"n": 100, "won": 43.0}}, base)
    assert not passes({"validation": good, "holdout": {"n": 10, "won": 80.0}}, base)
    return {"ok": True}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = run()
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    else:
        print(f"a random entry wins {res['baseline_win_pct']}% of these trades\n")
        print(f"{'group':15s} {'reading':42s} {'orient':9s} {'covers':>7s} "
              f"{'disc':>6s} {'valid':>6s} {'hold':>6s} {'net hold':>9s} {'n hold':>7s}")
        for r in res["readings"]:
            if "error" in r:
                print(f"{r['group']:15s} {r['reading']:42s} ERROR {r['error']}")
                continue
            d, v, h = r["discovery"], r["validation"], r["holdout"]
            mark = "  <= keeps" if r["passes"] else ""
            print(f"{r['group']:15s} {r['reading']:42s} {r['orientation']:9s} {r['coverage_pct']:6.1f}% "
                  f"{d.get('won', 0):6.1f} {v.get('won', 0):6.1f} {h.get('won', 0):6.1f} "
                  f"{h.get('net_r', 0):+9.3f} {h.get('n', 0):7d}{mark}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"state_readings_{stamp}.json"
        path.write_text(json.dumps(res, indent=1, default=str))
        print(f"\nkept: {sum(1 for r in res['readings'] if r.get('passes'))} of {len(res['readings'])}   written {path}")
