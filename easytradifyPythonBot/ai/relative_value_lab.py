# ai/relative_value_lab.py
"""
A different kind of information: what the OTHER pairs say this one is worth.

Every component in this engine reads one symbol's own candles, which is why
they all agree with each other and with noise. A cross rate is not free to be
anything, though: EURGBP must equal EURUSD / GBPUSD, EURJPY must equal
EURUSD x USDJPY. When the quoted cross drifts from what its legs imply,
something has to converge -- and that is a statement about direction that no
indicator in the engine can make.

For each cross this measures:

  deviation   (quoted - implied) / H1 ATR, on mid prices, minute by minute
  trade       when the deviation exceeds a threshold, take the convergence
              side (quoted rich -> sell the cross) on the live geometry:
              stop 1.5 x H1 ATR, target 1R and 2R, 24 hours
  fills       BUY at the ask, SELL at the bid, exits on the other side, with
              commission at a lot sized to the $4 risk -- tick quote bars

Judged on discovery / validation / holdout like everything else.

RESULT (2026-09-16, 16 weeks of tick quotes): dead. Requiring a dislocation to
persist five minutes leaves 8-11 events per cross, and fading them loses 0.70
to 1.09R -- near the maximum. The triangle is enforced by faster participants;
what survives to a minute bar is asynchronous quoting, and fading that means
selling a genuine move at its worst moment. Not a signal.

    python -m ai.relative_value_lab
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
QUOTE_DIR = Path(os.getenv("PRICE_QUOTE_DIR") or ROOT / "reports" / "cache" / "quotes")
REPORT_DIR = ROOT / "reports"

# cross -> (leg A, leg B, how the legs combine)
TRIANGLES: Dict[str, Tuple[str, str, str]] = {
    "EURGBP": ("EURUSD", "GBPUSD", "divide"),
    "EURJPY": ("EURUSD", "USDJPY", "multiply"),
    "GBPJPY": ("GBPUSD", "USDJPY", "multiply"),
    "EURCAD": ("EURUSD", "USDCAD", "multiply"),
    "AUDCAD": ("AUDUSD", "USDCAD", "multiply"),
    "AUDCHF": ("AUDUSD", "USDCHF", "multiply"),
    "AUDNZD": ("AUDUSD", "NZDUSD", "divide"),
    "GBPAUD": ("GBPUSD", "AUDUSD", "divide"),
}
THRESHOLDS = (0.25, 0.5, 1.0)          # in H1 ATR
HOLD_MINUTES = 1440
STOP_H1_ATR = 1.5
TARGETS_R = (1.0, 2.0)
COOLDOWN_MINUTES = 240                 # one trade per dislocation, not per minute
PERSIST_MINUTES = 5                    # one minute of it is asynchronous quoting, not a dislocation
COMMISSION_PER_LOT = 7.03
RISK_USD = 4.0
MIN_TRADES = 60


def load(symbol: str) -> Optional[Dict[str, np.ndarray]]:
    path = QUOTE_DIR / f"{symbol}.npz"
    if not path.exists():
        return None
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def align(*series: Mapping[str, np.ndarray]) -> Optional[Tuple[np.ndarray, List[np.ndarray]]]:
    """Common minutes across the given quote sets."""
    times = [s["time"] for s in series]
    common = times[0]
    for t in times[1:]:
        common = np.intersect1d(common, t, assume_unique=False)
    if common.size < 1000:
        return None
    mids = []
    for s in series:
        idx = np.searchsorted(s["time"], common)
        mids.append(s["mid_close"][idx])
    return common, mids


def h1_atr_series(mid: np.ndarray) -> np.ndarray:
    """A rolling hourly range, as the scale the deviation is measured in."""
    hours = mid.size // 60
    if hours < 20:
        return np.full(mid.size, np.nan)
    block = mid[:hours * 60].reshape(hours, 60)
    rng = block.max(axis=1) - block.min(axis=1)
    atr = np.convolve(rng, np.ones(14) / 14, mode="full")[:hours]
    atr[:14] = np.nan
    out = np.repeat(atr, 60)
    return np.r_[out, np.full(mid.size - out.size, out[-1] if out.size else np.nan)]


def deviations(cross: str) -> Optional[Dict[str, np.ndarray]]:
    legs = TRIANGLES.get(cross)
    if not legs:
        return None
    a, b, how = legs
    qs = [load(cross), load(a), load(b)]
    if any(q is None for q in qs):
        return None
    got = align(*qs)
    if got is None:
        return None
    times, (m_cross, m_a, m_b) = got
    implied = (m_a / m_b) if how == "divide" else (m_a * m_b)
    atr = h1_atr_series(m_cross)
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = (m_cross - implied) / atr
    return {"time": times, "dev": dev, "atr": atr, "cross": m_cross, "implied": implied}


def trade_deviation(cross: str, threshold: float) -> List[Dict[str, Any]]:
    """Fade the dislocation: a rich cross is sold, a cheap one bought."""
    from ai.price_history_study import quote_bracket, usd_per_price_unit_per_lot

    d = deviations(cross)
    q = load(cross)
    if d is None or q is None:
        return []
    usd = usd_per_price_unit_per_lot(cross) or 0.0
    qt = q["time"]
    rows: List[Dict[str, Any]] = []
    last_ts = -10 ** 9
    over = np.abs(d["dev"]) >= threshold
    # require the dislocation to survive PERSIST_MINUTES consecutive minutes
    if PERSIST_MINUTES > 1:
        run = np.ones(over.size, bool)
        for lag in range(PERSIST_MINUTES):
            run[PERSIST_MINUTES - 1:] &= over[PERSIST_MINUTES - 1 - lag: over.size - lag]
        run[:PERSIST_MINUTES - 1] = False
        over = run
    for i in np.flatnonzero(over):
        ts = int(d["time"][i])
        if ts - last_ts < COOLDOWN_MINUTES * 60:
            continue
        atr = float(d["atr"][i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        k = int(np.searchsorted(qt, ts))
        if k >= qt.size - HOLD_MINUTES // 2:
            continue
        side = -1 if d["dev"][i] > 0 else 1        # rich -> sell, cheap -> buy
        risk = STOP_H1_ATR * atr
        rpl = risk * usd
        if rpl <= 0 or 0.01 * rpl > RISK_USD * 1.1:
            continue
        commission = COMMISSION_PER_LOT / rpl
        for tr in TARGETS_R:
            br = quote_bracket(q, k, HOLD_MINUTES, risk, tr * risk, side)
            if not br:
                continue
            rows.append({"symbol": cross, "threshold": threshold, "target_r": tr, "dir": side,
                         "ts": ts, "dev_atr": round(float(d["dev"][i]), 3), "result": br["result"],
                         "r": br["r"], "commission_r": round(commission, 4)})
        last_ts = ts
    return rows


def report(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    from ai.component_repair import study_split

    if len(rows) < 8:
        return {"n": len(rows)}
    ts = np.array([r["ts"] for r in rows], dtype=float)
    net = np.array([r["r"] - (r["commission_r"] or 0) for r in rows])
    won = np.array([r["result"] == "TARGET" for r in rows])
    train, test, hold, _, _ = study_split(ts)
    out = {"n": len(rows), "won_pct": round(100 * float(won.mean()), 1), "net_r": round(float(net.mean()), 4)}
    for name, m in (("discovery", train), ("validation", test), ("holdout", hold)):
        out[name] = ({"n": int(m.sum()), "won_pct": round(100 * float(won[m].mean()), 1),
                      "net_r": round(float(net[m].mean()), 4)} if m.any() else {"n": 0})
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "relative_value_lab", "crosses": list(TRIANGLES), "thresholds": list(THRESHOLDS)}


def self_check() -> Dict[str, Any]:
    # a cross quoted above what its legs imply is rich, so the trade is a sell
    mid = np.linspace(1.0, 1.01, 3000)          # 50 hours: the scale needs 14 to warm up
    atr = h1_atr_series(mid)
    assert np.isfinite(atr[-1]) and atr[-1] > 0, atr[-5:]
    assert not np.isfinite(atr[0])              # and says so before it has them
    a, b = np.full(600, 1.2), np.full(600, 1.5)
    implied = a / b                                   # 0.8
    dev = (np.full(600, 0.81) - implied) / 0.01       # quoted rich by 1 ATR
    assert dev[0] > 0
    assert (-1 if dev[0] > 0 else 1) == -1
    return {"ok": True}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "check"))
    a = ap.parse_args()
    if a.cmd == "check":
        print(self_check())
        raise SystemExit
    all_rows: List[Dict[str, Any]] = []
    for cross in TRIANGLES:
        for th in THRESHOLDS:
            got = trade_deviation(cross, th)
            all_rows += got
            if got:
                r = report([g for g in got if g["target_r"] == 1.0])
                if r.get("won_pct") is None:
                    print(f"{cross} dev>={th} ATR: {r['n']:4d} trades -- too few to score", flush=True)
                else:
                    print(f"{cross} dev>={th} ATR: {r['n']:4d} trades  won {r['won_pct']}%  net {r['net_r']:+.4f}", flush=True)
    print("\npooled across crosses:")
    for th in THRESHOLDS:
        for tr in TARGETS_R:
            sel = [r for r in all_rows if r["threshold"] == th and r["target_r"] == tr]
            rep = report(sel)
            if rep.get("n", 0) >= MIN_TRADES:
                print(f"  dev>={th} ATR target {tr}R: n{rep['n']:5d} won {rep['won_pct']:5.1f}% net {rep['net_r']:+.4f} "
                      f"| disc {rep['discovery'].get('net_r')} valid {rep['validation'].get('net_r')} "
                      f"hold {rep['holdout'].get('net_r')} ({rep['holdout'].get('won_pct')}% won)")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "relative_value_lab.json").write_text(json.dumps(all_rows[:20000], default=str))
