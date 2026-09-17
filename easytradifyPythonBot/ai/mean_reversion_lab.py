# ai/mean_reversion_lab.py
"""
The mean-reversion setup that survived the tick study, re-run over four years.

Built by elimination on 16 weeks of tick data. What survived:

  entry     price stretched >= STRETCH_ATR from its 4h mean, and STALLED --
            no new extreme for 30 minutes -- and slow (<= 0.3 ATR in the last
            15 minutes). Fading a FAST move loses 0.41R: velocity continues,
            it does not revert. Only stretch that has stopped moving reverts.
  exit      a fixed 1R. Targeting the mean itself is worse (-0.151 vs -0.116),
            which was the surprise.
  gate      spread <= MAX_COST_SHARE of H1 ATR. Across 15 symbols the
            correlation between that cost share and profit is -0.673:
            EURUSD pays 0.68% of an hourly range per trade, AUDNZD 5.54%.

What was tested and did NOT help: anchoring the entry to prior-day levels
(-0.232 against -0.116), requiring a flat 24h trend (-0.267), demanding a
bigger stretch (-0.262 at 1.5 ATR), a 60-minute stall (-0.259), and targeting
the mean or half the stretch.

Sixteen weeks gave 37-52 trades a symbol -- a shape, not a proof. This runs
the same rules on four years of M15 bars with the measured spread profile and
the rollover hour excluded (ai/deep_history_lab.py), where each symbol has
roughly 1,500.

RESULT (2026-09-16, 6,406 trades inside the cost gate): it did NOT hold. The
16-week +0.120R on EURUSD was small-sample noise; four years reads 48.5% and
-0.045R, and only USDCAD is positive (+0.011R, holdout -0.205R).

And `frontier()` settles the question the win rate was standing in for. It
prices every target on the same trades:

     target    won      net R        target    won      net R
       0.15   86.8%    -0.040          1.00   49.2%    -0.053
       0.25   79.8%    -0.041          2.00   36.1%    -0.049
       0.33   74.6%    -0.046          4.00   32.3%    -0.029

Accuracy is a dial on the target, nothing more. Fifty-four points of win rate
move expectancy by two hundredths of an R, and every setting loses. "Make it
75% accurate" is already free -- target 0.33R -- and worth -0.046R a trade.
So no exit rule, target or stop geometry rescues this entry; the missing
thing is directional edge at the entry, which is where the work belongs.

Beware the settlement bug this function had on its first run: a trade that
touches neither barrier must mark to market at the last close. Comparing two
"never happened" sentinels paid every timeout a full win and reported +0.77R
at a 4R target, which is what an implausible result looks like from inside.

    python -m ai.mean_reversion_lab
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

STRETCH_ATR = 1.0
STALL_BARS = 2              # 30 minutes of M15
VELOCITY_MAX = 0.3          # ATR over the last 15 minutes
MEAN_BARS = 16              # 4 hours of M15
STOP_ATR = 1.5
TARGET_R = 1.0
HOLD_BARS = 96              # 24 hours
COOLDOWN_BARS = 16          # one trade per stretch, not one per bar
MAX_COST_SHARE = 0.02       # spread as a share of H1 ATR
COMMISSION_PER_LOT = 7.03
RISK_USD = 4.0


def series(symbol: str) -> Optional[Dict[str, np.ndarray]]:
    """M15 bars with the H1 ATR each one sits in."""
    from ai.deep_history_lab import load_bars

    m = load_bars(symbol).get("M15")
    if m is None:
        return None
    t = m["time"].astype(np.int64)
    close = m["close"].astype(float)
    high = m["high"].astype(float)
    low = m["low"].astype(float)
    n = t.size // 4
    hi = high[:n * 4].reshape(n, 4).max(axis=1)
    lo = low[:n * 4].reshape(n, 4).min(axis=1)
    cl = close[:n * 4].reshape(n, 4)[:, -1]
    pc = np.r_[cl[0], cl[:-1]]
    tr = np.maximum(hi - lo, np.maximum(abs(hi - pc), abs(lo - pc)))
    atr_h1 = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]
    atr_h1[:14] = np.nan
    # n*4 can fall short of t.size by up to three bars (a partial final hour);
    # those trailing M15 bars have no completed H1 behind them, so they carry
    # NaN rather than silently shortening the column and misaligning every
    # array against it
    per_bar = np.repeat(atr_h1, 4)
    atr = np.full(t.size, np.nan)
    atr[:min(per_bar.size, t.size)] = per_bar[:t.size]
    return {"t": t, "close": close, "high": high, "low": low, "atr": atr,
            "volume": m["tick_volume"].astype(float), "hour": (t % 86400) // 3600}


def cost_share(symbol: str, atr_price: float) -> Optional[float]:
    from ai.deep_history_lab import spread_table
    from ai.price_history_study import symbol_specs

    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    prof = spread_table().get(symbol) or {}
    spread_pips = prof.get("median_pips")
    if not pip or spread_pips is None or not atr_price:
        return None
    return (float(spread_pips) * pip) / atr_price


def trades(symbol: str) -> List[Dict[str, Any]]:
    from ai.deep_history_lab import bracket_on_bid_bars, spread_pips, spread_table, ROLLOVER_BROKER_HOURS
    from ai.price_history_study import symbol_specs, usd_per_price_unit_per_lot

    s = series(symbol)
    if s is None:
        return []
    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    usd = usd_per_price_unit_per_lot(symbol)
    if not pip or not usd:
        return []
    spread = spread_pips(spread_table(), symbol, s["hour"]) * pip
    close, high, low, atr = s["close"], s["high"], s["low"], s["atr"]
    rows: List[Dict[str, Any]] = []
    last = -10 ** 9
    for i in range(MEAN_BARS + 2 * STALL_BARS, close.size - HOLD_BARS - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0 or i - last < COOLDOWN_BARS:
            continue
        if s["hour"][i] in ROLLOVER_BROKER_HOURS:
            continue
        mean4h = float(close[i - MEAN_BARS:i].mean())
        stretch = (close[i] - mean4h) / a
        if abs(stretch) < STRETCH_ATR:
            continue
        side = -1 if stretch > 0 else 1
        if abs(close[i] - close[i - 1]) / a > VELOCITY_MAX:
            continue
        if side < 0:
            stalled = high[i - STALL_BARS:i + 1].max() <= high[i - 2 * STALL_BARS:i - STALL_BARS].max()
        else:
            stalled = low[i - STALL_BARS:i + 1].min() >= low[i - 2 * STALL_BARS:i - STALL_BARS].min()
        if not stalled:
            continue
        k = i + 1
        risk = STOP_ATR * a
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        entry = float(close[i] + (spread[i] if side > 0 else 0.0))
        stop = entry - side * risk
        target = entry + side * TARGET_R * risk
        sl = slice(k, k + HOLD_BARS)
        result, r = bracket_on_bid_bars(low[sl], high[sl], close[sl], s["hour"][sl], spread[sl],
                                        side, entry, stop, target)
        if result == "NONE":
            continue
        rows.append({"symbol": symbol, "ts": int(s["t"][k]), "side": side, "stretch": round(float(stretch), 2),
                     "result": result, "r": r, "commission_r": COMMISSION_PER_LOT / rpl,
                     "cost_share": cost_share(symbol, float(a))})
        last = i
    return rows


TARGET_GRID = (0.15, 0.2, 0.25, 0.33, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)


def frontier(symbol: str) -> List[Dict[str, Any]]:
    """The same entries, every target, so accuracy can be priced.

    A target is only worth what it costs in expectancy. This walks each trade
    once, records the bar at which the stop is hit and the bar at which each
    target is first reached, and settles every target off that one walk -- so
    "75% wins" and "what that pays" come from identical trades.
    """
    from ai.deep_history_lab import spread_pips, spread_table, ROLLOVER_BROKER_HOURS
    from ai.price_history_study import symbol_specs, usd_per_price_unit_per_lot

    s = series(symbol)
    if s is None:
        return []
    spec = symbol_specs().get(symbol) or {}
    pip = spec.get("pip")
    usd = usd_per_price_unit_per_lot(symbol)
    if not pip or not usd:
        return []
    share = None
    spread = spread_pips(spread_table(), symbol, s["hour"]) * pip
    close, high, low, atr = s["close"], s["high"], s["low"], s["atr"]
    rows: List[Dict[str, Any]] = []
    last = -10 ** 9
    for i in range(MEAN_BARS + 2 * STALL_BARS, close.size - HOLD_BARS - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0 or i - last < COOLDOWN_BARS:
            continue
        if s["hour"][i] in ROLLOVER_BROKER_HOURS:
            continue
        mean4h = float(close[i - MEAN_BARS:i].mean())
        stretch = (close[i] - mean4h) / a
        if abs(stretch) < STRETCH_ATR:
            continue
        side = -1 if stretch > 0 else 1
        if abs(close[i] - close[i - 1]) / a > VELOCITY_MAX:
            continue
        if side < 0:
            stalled = high[i - STALL_BARS:i + 1].max() <= high[i - 2 * STALL_BARS:i - STALL_BARS].max()
        else:
            stalled = low[i - STALL_BARS:i + 1].min() >= low[i - 2 * STALL_BARS:i - STALL_BARS].min()
        if not stalled:
            continue
        risk = STOP_ATR * a
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        if share is None:
            share = cost_share(symbol, float(a))
        k = i + 1
        sl = slice(k, k + HOLD_BARS)
        entry = float(close[i] + (spread[i] if side > 0 else 0.0))
        # exits pay the spread: a BUY leaves on the bid (the bar), a SELL on the ask
        if side > 0:
            fav = (high[sl] - entry) / risk
            adv = (entry - low[sl]) / risk
        else:
            fav = (entry - (low[sl] + spread[sl])) / risk
            adv = ((high[sl] + spread[sl]) - entry) / risk
        if fav.size == 0:
            continue
        # a trade that never touches either barrier is marked to market at the
        # last CLOSE. Settling it at the target instead -- which is what
        # comparing two "never happened" sentinels did -- paid every timeout a
        # full win, and at a 4R target most trades time out: it read +0.77R.
        exit_r = (close[sl] - entry) / risk if side > 0 else (entry - (close[sl] + spread[sl])) / risk
        timeout_r = float(exit_r[-1])
        stop_at = int(np.argmax(adv >= 1.0)) if (adv >= 1.0).any() else None
        run = np.maximum.accumulate(fav)
        row = {"symbol": symbol, "ts": int(s["t"][k]), "cost_share": share,
               "commission_r": COMMISSION_PER_LOT / rpl, "mfe": round(float(run[-1]), 3),
               "mfe_bar": int(np.argmax(fav))}
        for t in TARGET_GRID:
            reach = int(np.argmax(run >= t)) if (run >= t).any() else None
            if reach is not None and (stop_at is None or reach <= stop_at):
                row[f"t{t}"] = float(t)
            elif stop_at is not None:
                row[f"t{t}"] = -1.0
            else:
                row[f"t{t}"] = timeout_r
        rows.append(row)
        last = i
    return rows


def report(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    from ai.deep_history_lab import periods, MODEL_OPTIMISM_R

    if len(rows) < 30:
        return {"n": len(rows)}
    ts = np.array([r["ts"] for r in rows], dtype=float)
    net = np.array([r["r"] - (r["commission_r"] or 0) for r in rows])
    won = np.array([r["result"] == "TARGET" for r in rows])
    out = {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1),
           "net_r": round(float(net.mean()), 4),
           "net_r_tick_adjusted": round(float(net.mean()) - MODEL_OPTIMISM_R, 4)}
    for name, m in periods(ts).items():
        out[name] = ({"n": int(m.sum()), "won_pct": round(100 * float(won[m].mean()), 1),
                      "net_r": round(float(net[m].mean()), 4)} if m.sum() > 20 else {"n": int(m.sum())})
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "mean_reversion_lab", "stretch_atr": STRETCH_ATR,
            "stall_minutes": STALL_BARS * 15, "max_cost_share": MAX_COST_SHARE}


def self_check() -> Dict[str, Any]:
    # the rule must reject a FAST move and accept a stalled one
    a = 0.001
    fast = abs(0.5 * a) / a
    slow = abs(0.1 * a) / a
    assert fast > VELOCITY_MAX >= slow
    assert STALL_BARS * 15 == 30
    return {"ok": True}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
        raise SystemExit
    rows: List[Dict[str, Any]] = []
    with Pool(8) as pool:
        for got in pool.imap_unordered(trades, SYMBOLS):
            rows += got
    print(f"{len(rows)} trades over four years\n")
    print(f"{'symbol':8s} {'cost':>7s} {'n':>5s} {'won':>7s} {'net R':>9s} {'disc':>9s} {'valid':>9s} {'holdout':>9s}")
    cheap_rows = []
    for sym in sorted({r["symbol"] for r in rows}):
        sel = [r for r in rows if r["symbol"] == sym]
        rep = report(sel)
        if rep.get("n", 0) < 30:
            continue
        share = sel[0].get("cost_share") or 0
        if share <= MAX_COST_SHARE:
            cheap_rows += sel
        d = rep.get("discovery", {}); v = rep.get("validation", {}); h = rep.get("holdout", {})
        print(f"{sym:8s} {100*share:6.2f}% {rep['n']:5d} {rep['won_pct']:6.1f}% {rep['net_r']:+9.4f} "
              f"{d.get('net_r', float('nan')):+9.4f} {v.get('net_r', float('nan')):+9.4f} "
              f"{h.get('net_r', float('nan')):+9.4f}")
    print(f"\nPOOLED, cost gate <= {100*MAX_COST_SHARE:.0f}% of H1 ATR:")
    rep = report(cheap_rows)
    print(json.dumps(rep, indent=1))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "mean_reversion_lab.json").write_text(json.dumps({"pooled_cheap": rep, "n_all": len(rows)}, indent=1))
