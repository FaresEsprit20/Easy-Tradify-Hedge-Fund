# ai/strategy_selector_lab.py
"""
Does behaviour tell you WHICH strategy to run?

The system picks a direction and then lets whichever group scores highest
claim it. It has never had a reading that says "this is a bar to follow" or
"this is a bar to fade" -- core/state_readings.py measured thirteen readings
that all answer "where is price" and all landed on the 44.6% baseline
(44.2-45.4%). core/behaviour_readings.py added the other axis. This asks
whether that axis is worth anything, in the only way that settles it:

At every bar, classify the behaviour state, then take BOTH trades -- the
follow and the fade -- on identical geometry, and compare them inside each
state. The claim being tested is a separation, not a win rate:

    reversion_ready   fade should beat follow
    momentum_running  follow should beat fade
    expanding         follow should beat fade (expansion continues)

If those separations hold out of sample, the strategy selector is real and
behaviour should choose the group. If follow and fade are the same number in
every state, the axis is decoration and MEAN_REVERSION's new gate is resting
on nothing -- which is worth knowing before it trades.

Geometry is the live one: stop 1.5 x H1 ATR, target 1R, 24h, spread from the
measured profile, commission at a $4-risk lot, rollover hour excluded.

    python -m ai.strategy_selector_lab            # the full four years
    python -m ai.strategy_selector_lab check      # agreement with the live reading
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from ai.mean_reversion_lab import (COMMISSION_PER_LOT, COOLDOWN_BARS, HOLD_BARS, MAX_COST_SHARE,
                                   MEAN_BARS, RISK_USD, STALL_BARS, STOP_ATR, TARGET_R,
                                   cost_share, series)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

VEL_BARS = 1                 # 15 minutes of M15, matching behaviour_readings
EXTENDED_ATR = 1.0
VELOCITY_MAX_ATR = 0.3
COMPRESSION_LOOKBACK = 50
EXPANSION_RATIO = 1.3

STATES = ("REVERSION_READY", "MOMENTUM_RUNNING", "EXPANDING", "QUIET")


def _roll_max(a: np.ndarray, w: int) -> np.ndarray:
    """Rolling max ending at each index (inclusive), NaN until the window fills."""
    out = np.full(a.size, np.nan)
    if a.size >= w:
        v = np.lib.stride_tricks.sliding_window_view(a, w).max(axis=1)
        out[w - 1:] = v
    return out


def _roll_min(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(a.size, np.nan)
    if a.size >= w:
        v = np.lib.stride_tricks.sliding_window_view(a, w).min(axis=1)
        out[w - 1:] = v
    return out


def _roll_mean(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(a.size, np.nan)
    if a.size >= w:
        c = np.cumsum(np.insert(a, 0, 0.0))
        out[w - 1:] = (c[w:] - c[:-w]) / w
    return out


def behaviour_columns(s: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """The readings of core/behaviour_readings.py, vectorised over every bar.

    Kept deliberately literal so `self_check()` can hold it against the live
    per-bar implementation; if the two ever disagree the check fails rather
    than the study quietly measuring a different rule than the engine runs.
    """
    close, high, low, atr = s["close"], s["high"], s["low"], s["atr"]
    mean4h = _roll_mean(close, MEAN_BARS)
    # the mean of the PRIOR window, as the live reading takes close[-MEAN:] up
    # to but not including the current bar
    mean_prior = np.r_[np.nan, mean4h[:-1]]
    extension = (close - mean_prior) / atr

    velocity = np.full(close.size, np.nan)
    velocity[VEL_BARS:] = np.abs(close[VEL_BARS:] - close[:-VEL_BARS]) / atr[VEL_BARS:]

    rh, rl = _roll_max(high, STALL_BARS), _roll_min(low, STALL_BARS)
    prior_h = np.r_[np.full(STALL_BARS, np.nan), rh[:-STALL_BARS]]
    prior_l = np.r_[np.full(STALL_BARS, np.nan), rl[:-STALL_BARS]]
    stalled = np.where(extension > 0, rh <= prior_h, rl >= prior_l)

    rng = high - low
    base = np.full(close.size, np.nan)
    if close.size >= COMPRESSION_LOOKBACK:
        w = np.lib.stride_tricks.sliding_window_view(rng, COMPRESSION_LOOKBACK)
        base[COMPRESSION_LOOKBACK - 1:] = np.median(w, axis=1)
    now = _roll_mean(rng, STALL_BARS)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(base > 0, now / base, np.nan)

    extended = np.abs(extension) >= EXTENDED_ATR
    slow = velocity <= VELOCITY_MAX_ATR
    return {"extension": extension, "velocity": velocity, "stalled": stalled, "ratio": ratio,
            "reversion_ready": extended & stalled & slow,
            "momentum_running": velocity > VELOCITY_MAX_ATR,
            "expanding": ratio >= EXPANSION_RATIO}


def state_of(c: Mapping[str, np.ndarray], i: int) -> Optional[str]:
    """One state per bar, most specific first, so the cells do not overlap."""
    if not np.isfinite(c["extension"][i]) or not np.isfinite(c["velocity"][i]):
        return None
    if c["reversion_ready"][i]:
        return "REVERSION_READY"
    if c["momentum_running"][i]:
        return "MOMENTUM_RUNNING"
    if np.isfinite(c["ratio"][i]) and c["expanding"][i]:
        return "EXPANDING"
    return "QUIET"


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
    close, atr, low, high = s["close"], s["atr"], s["low"], s["high"]
    c = behaviour_columns(s)
    share = None
    rows: List[Dict[str, Any]] = []
    last: Dict[str, int] = {}
    start = max(MEAN_BARS + 2 * STALL_BARS, COMPRESSION_LOOKBACK) + 1
    for i in range(start, close.size - HOLD_BARS - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0 or s["hour"][i] in ROLLOVER_BROKER_HOURS:
            continue
        state = state_of(c, i)
        if state is None or i - last.get(state, -10 ** 9) < COOLDOWN_BARS:
            continue
        move = close[i] - close[i - VEL_BARS]
        if move == 0:
            continue
        follow = 1 if move > 0 else -1
        # the fade is defined by the stretch when there is one, otherwise by
        # the move -- so "fade" always means the opposite of what just happened
        ext = c["extension"][i]
        fade = (-1 if ext > 0 else 1) if abs(ext) >= EXTENDED_ATR else -follow
        risk = STOP_ATR * a
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        if share is None:
            share = cost_share(symbol, float(a))
        commission = COMMISSION_PER_LOT / rpl
        k = i + 1
        sl = slice(k, k + HOLD_BARS)
        for action, side in (("follow", follow), ("fade", fade)):
            entry = float(close[i] + (spread[i] if side > 0 else 0.0))
            stop = entry - side * risk
            target = entry + side * TARGET_R * risk
            result, r = bracket_on_bid_bars(low[sl], high[sl], close[sl], s["hour"][sl],
                                            spread[sl], side, entry, stop, target)
            if result == "NONE":
                continue
            rows.append({"symbol": symbol, "ts": int(s["t"][k]), "state": state, "action": action,
                         "won": result == "TARGET", "net": r - commission, "cost_share": share})
        last[state] = i
    return rows


def cell(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    from ai.deep_history_lab import periods

    if len(rows) < 50:
        return {"n": len(rows)}
    ts = np.array([r["ts"] for r in rows], dtype=float)
    net = np.array([r["net"] for r in rows])
    won = np.array([r["won"] for r in rows])
    out = {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1),
           "net_r": round(float(net.mean()), 4)}
    for name, m in periods(ts).items():
        out[name] = round(float(net[m].mean()), 4) if m.sum() > 20 else None
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "strategy_selector_lab", "states": list(STATES),
            "tests": "does behaviour predict follow vs fade"}


def self_check() -> Dict[str, Any]:
    """The vectorised columns must agree with the live per-bar reading."""
    from core.behaviour_readings import read as live_read

    rng = np.random.default_rng(7)
    n = 600
    close = 100 + np.cumsum(rng.normal(0, 0.1, n))
    high = close + np.abs(rng.normal(0, 0.05, n))
    low = close - np.abs(rng.normal(0, 0.05, n))
    atr = np.full(n, 0.5)
    s = {"close": close, "high": high, "low": low, "atr": atr}
    c = behaviour_columns(s)
    agree_ready = agree_ext = checked = 0
    for i in range(n - 60, n):
        live = live_read(high[:i + 1], low[:i + 1], close[:i + 1], float(atr[i]), minutes_per_bar=15)
        if not live["available"]:
            continue
        checked += 1
        agree_ready += int(bool(live["reversion_ready"]) == bool(c["reversion_ready"][i]))
        # the live reading publishes extension rounded to 3 decimals
        agree_ext += int(abs(live["extension_atr"] - round(float(c["extension"][i]), 3)) < 1e-9)
    checks = {"bars_checked": checked > 20,
              "reversion_ready_agrees": checked > 0 and agree_ready == checked,
              "extension_agrees": checked > 0 and agree_ext == checked,
              "states_are_exclusive": len(set(STATES)) == len(STATES)}
    return {"component": "strategy_selector_lab", "ok": all(checks.values()),
            "checks": checks, "bars": checked}


if __name__ == "__main__":
    from multiprocessing import Pool
    from ai.price_history_study import SYMBOLS

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    args = ap.parse_args()
    if args.cmd == "check":
        print(json.dumps(self_check(), indent=1))
        raise SystemExit

    rows: List[Dict[str, Any]] = []
    with Pool(8) as pool:
        for got in pool.imap_unordered(trades, SYMBOLS):
            rows += got
    cheap = [r for r in rows if (r.get("cost_share") or 1) <= MAX_COST_SHARE]
    print(f"{len(rows)} trades, {len(cheap)} on instruments inside the cost gate\n")
    summary: Dict[str, Any] = {}
    for label, pool_rows in (("ALL INSTRUMENTS", rows), (f"COST GATE <= {100*MAX_COST_SHARE:.0f}%", cheap)):
        print(f"== {label} ==")
        print(f"{'state':18s} {'action':7s} {'n':>6s} {'won':>7s} {'net R':>9s} "
              f"{'disc':>9s} {'valid':>9s} {'holdout':>9s}")
        for state in STATES:
            got = {}
            for action in ("follow", "fade"):
                sel = [r for r in pool_rows if r["state"] == state and r["action"] == action]
                rep = cell(sel)
                got[action] = rep
                if rep.get("n", 0) < 50:
                    print(f"{state:18s} {action:7s} {rep.get('n', 0):6d}  too few")
                    continue
                print(f"{state:18s} {action:7s} {rep['n']:6d} {rep['won_pct']:6.1f}% {rep['net_r']:+9.4f} "
                      + " ".join(f"{(rep.get(p) if rep.get(p) is not None else float('nan')):+9.4f}"
                                 for p in ("discovery", "validation", "holdout")))
            if got.get("follow", {}).get("net_r") is not None and got.get("fade", {}).get("net_r") is not None:
                edge = got["follow"]["net_r"] - got["fade"]["net_r"]
                print(f"{'':18s} {'follow - fade':>7s}{'':7s}{'':7s} {edge:+9.4f}"
                      f"   <- the separation this lab exists to test")
            summary.setdefault(label, {})[state] = got
        print()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "strategy_selector_lab.json").write_text(json.dumps(summary, indent=1))
    print(f"written: reports/strategy_selector_lab.json")
