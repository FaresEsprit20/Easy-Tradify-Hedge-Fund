"""
SHADOW ONLY -- RSI divergence on huge M1 swings (+-1600 bars). Never places orders.

Why (2026-09-18): tradify_study/trend_m1_v1/rsi_div_huge_swings.py. Of 36
pre-registered configurations this was the only one to pass on IC Markets bid/ask
M1 (15 pairs, 2026-05..09): 63% won, +0.010R / +0.015R per trade in the two
halves, 10/15 markets positive, 100 trades. It then LOST on the earlier,
unseen Dukascopy period (-0.05R, 41 trades), so it is NOT confirmed. The
operator asked to keep watching it live: this runner records what it would do.

Setup (frozen, exactly the study's cell "1600 any none RSI70")
  swing   a bar whose M1 mid low (high) is the lowest (highest) of the 1600 bars
          on each side; known 1600 bars later
  signal  classic divergence against the IMMEDIATELY preceding swing of the same
          kind, 1600 < gap <= 32000 bars: lower low with higher RSI(14) -> BUY,
          higher high with lower RSI(14) -> SELL. No RSI level, no confirmation.
  entry   the tick after the swing is known (BUY at the ask, SELL at the bid)
  stop    the swing -1 pip (+1 for a SELL); 2 pips minimum; must fit $4 at 0.01 lot
  exit    stop first; RSI(14) >= 70 for a BUY (<= 30 for a SELL) at a bar close;
          cap 4320 bars
  costs   commission and overnight swap (21:00 UTC, triple Wednesday) from the
          broker's facts
  control the opposite side, same stop, same holding time

Pre-registered verdict: after 300 resolved trades, CONFIRMED if net R > 0 and
beats the opposite side, else DEAD. At ~100 trades per 3.5 months this takes
about ten months. Even CONFIRMED does not trade by itself -- that is the
operator's decision.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from core.rsi_divergence_setup import pip_size, rsi_wilder

PIV = 1600
MAX_GAP = 20 * PIV
HOLD_BARS = 4320
EXIT_BUY = 70.0
HISTORY = 22 * PIV + 200          # closed M1 bars: the swing window plus the look-back
RISK_USD = 4.0
MIN_STOP_PIPS = 2.0
MIN_TRADES_FOR_VERDICT = 300
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
           "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY"]
JOURNAL = Path(__file__).resolve().parents[2] / "reports" / "v2" / "shadow_rsi_div_huge_v1.jsonl"
HEARTBEAT = JOURNAL.with_name("shadow_rsi_div_huge_heartbeat.json")


# ---------------------------------------------------------------------------
# the setup
# ---------------------------------------------------------------------------

def _is_pivot(x: np.ndarray, j: int, low: bool) -> bool:
    if j - PIV < 0 or j + PIV >= x.size:
        return False
    w = x[j - PIV:j + PIV + 1]
    return bool(x[j] == (w.min() if low else w.max()))


def _last_pivot_before(x: np.ndarray, b: int, low: bool) -> int | None:
    """The latest pivot a < b (searched back MAX_GAP bars), as the study's
    consecutive-pivot pairing sees it."""
    lo = max(b - MAX_GAP, PIV)
    if lo >= b:
        return None
    seg = x[lo - PIV:b + PIV]                       # every window a candidate in [lo, b) needs
    w = np.lib.stride_tricks.sliding_window_view(seg, 2 * PIV + 1)
    ext = w.min(axis=1) if low else w.max(axis=1)
    cand = np.flatnonzero(seg[PIV:PIV + ext.size] == ext) + lo
    cand = cand[cand < b]
    return int(cand[-1]) if cand.size else None


def signal_on_last_bar(h: np.ndarray, l: np.ndarray, r: np.ndarray):
    """A divergence whose second swing became known on the LAST closed bar:
    (side, swing index, first swing index) or None."""
    b = h.size - 1 - PIV
    for low, side in ((True, 1), (False, -1)):
        x = l if low else h
        if not _is_pivot(x, b, low):
            continue
        a = _last_pivot_before(x, b, low)
        if a is None or not (PIV < b - a <= MAX_GAP):
            continue
        if low and x[b] < x[a] and r[b] > r[a]:
            return side, b, a
        if not low and x[b] > x[a] and r[b] < r[a]:
            return side, b, a
    return None


def nights(t0: int, t1: int) -> int:
    """Rollovers (21:00 UTC) between two unix times; Wednesday counts 3."""
    n = 0
    day = (t0 - 21 * 3600) // 86400 + 1
    while day * 86400 + 21 * 3600 <= t1:
        wd = (day + 3) % 7                          # 1970-01-01 was a Thursday; 0 = Monday
        n += 3 if wd == 2 else (0 if wd in (5, 6) else 1)
        day += 1
    return n


def resolve(side: int, fill: float, stop: float, bars, rsis):
    """(R before costs, bars used) or None while open. Stop first, then the RSI
    exit at the bar close, then the cap. bars: (bo, bh, bl, bc, ao, ah, al, ac)."""
    stop_px = fill - side * stop
    for k, (b, r) in enumerate(zip(bars[:HOLD_BARS], rsis[:HOLD_BARS])):
        op = b[0] if side == 1 else b[4]
        if (side == 1 and b[2] <= stop_px) or (side == -1 and b[5] >= stop_px):
            px = op if k > 0 and side * (op - stop_px) < 0 else stop_px
            return side * (px - fill) / stop, k + 1
        if (r >= EXIT_BUY) if side == 1 else (r <= 100 - EXIT_BUY):
            return side * ((b[3] if side == 1 else b[7]) - fill) / stop, k + 1
    if len(bars) >= HOLD_BARS:
        last = bars[HOLD_BARS - 1]
        return side * ((last[3] if side == 1 else last[7]) - fill) / stop, HOLD_BARS
    return None


def resolve_matched(side: int, fill: float, stop: float, bars, n_bars: int) -> float:
    stop_px = fill - side * stop
    for k, b in enumerate(bars[:n_bars]):
        op = b[0] if side == 1 else b[4]
        if (side == 1 and b[2] <= stop_px) or (side == -1 and b[5] >= stop_px):
            px = op if k > 0 and side * (op - stop_px) < 0 else stop_px
            return side * (px - fill) / stop
    last = bars[n_bars - 1]
    return side * ((last[3] if side == 1 else last[7]) - fill) / stop


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------

def _load():
    trades = {}
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e["event"] == "ENTRY":
                trades[e["id"]] = e
            elif e["event"] == "RESOLVED" and e["id"] in trades:
                trades[e["id"]].update(e)
    return trades


def _append(event: dict):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def verdict(trades: dict | None = None) -> tuple[str, int]:
    done = [t for t in (trades if trades is not None else _load()).values() if "net_r" in t]
    if len(done) < MIN_TRADES_FOR_VERDICT:
        return "PENDING", len(done)
    net = float(np.mean([t["net_r"] for t in done]))
    opp = float(np.mean([t["opp_net_r"] for t in done]))
    return ("CONFIRMED" if net > 0 and net > opp else "DEAD"), len(done)


def cycle(mt5) -> dict:
    from engine_v2.data.symbols import facts
    trades = _load()
    open_by_sym = {t["symbol"]: t for t in trades.values() if "net_r" not in t}
    v, n = verdict(trades)
    report = {"at": int(time.time()), "verdict": f"{v} ({n}/{MIN_TRADES_FOR_VERDICT} resolved)",
              "orders": "never (shadow only)", "symbols": {}}
    for sym in SYMBOLS:
        try:
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, HISTORY + 1)
            if rates is None or len(rates) < HISTORY:
                report["symbols"][sym] = f"not enough bars ({0 if rates is None else len(rates)})"
                continue
            rates = rates[:-1]                                   # the last bar is still forming
            info = mt5.symbol_info(sym)
            sp = rates["spread"].astype(float) * info.point
            t = rates["time"].astype(np.int64)
            bo, bh, bl, bc = (rates[k].astype(float) for k in ("open", "high", "low", "close"))
            mid_h, mid_l, mid_c = bh + sp / 2, bl + sp / 2, bc + sp / 2
            r = rsi_wilder(mid_c)
            f = facts(sym)

            tr = open_by_sym.get(sym)
            if tr is not None:
                after = np.flatnonzero(t >= tr["entry_bar_time"])
                bars = [(bo[i], bh[i], bl[i], bc[i], bo[i] + sp[i], bh[i] + sp[i], bl[i] + sp[i], bc[i] + sp[i])
                        for i in after]
                res = resolve(tr["side"], tr["fill"], tr["stop"], bars, list(r[after]))
                if res is not None:
                    exit_time = int(tr["entry_bar_time"]) + 60 * (res[1] - 1)
                    nts = nights(int(tr["entry_bar_time"]), exit_time)
                    c = f.commission_r(tr["stop"])
                    opp = resolve_matched(-tr["side"], tr["opp_fill"], tr["stop"], bars, res[1])
                    _append({"event": "RESOLVED", "id": tr["id"], "resolved_at": int(time.time()),
                             "gross_r": res[0], "bars": res[1], "exit_bar_time": exit_time, "nights": nts,
                             "net_r": res[0] - c + nts * f.swap_r_per_night(tr["side"], tr["stop"]),
                             "opp_net_r": opp - c + nts * f.swap_r_per_night(-tr["side"], tr["stop"])})
                    open_by_sym.pop(sym)
                    report["symbols"][sym] = "resolved"
                else:
                    report["symbols"][sym] = "open"
                    continue

            hit = signal_on_last_bar(mid_h, mid_l, r)
            if hit is None:
                report["symbols"].setdefault(sym, "watching")
                continue
            side, b, a = hit
            sid = f"{sym}-{int(t[b])}-{side}"
            if sid in trades:
                continue
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            pip = pip_size(sym)
            stop_px = (mid_l[b] if side == 1 else mid_h[b]) - side * pip
            fill = tick.ask if side == 1 else tick.bid
            stop = side * (fill - stop_px)
            if stop < MIN_STOP_PIPS * pip or f.risk_usd_at_min_lot(stop) > RISK_USD * 1.12:
                _append({"event": "SKIPPED", "id": sid, "symbol": sym, "stop_pips": round(stop / pip, 2),
                         "reason": "stop under 2 pips" if stop < MIN_STOP_PIPS * pip else "stop does not fit $4 at 0.01 lot"})
                continue
            entry = {"event": "ENTRY", "id": sid, "symbol": sym, "side": side,
                     "detected_at": int(time.time()), "entry_bar_time": int(t[-1]) + 60,
                     "swing_time": int(t[b]), "first_swing_time": int(t[a]),
                     "rsi_at_swing": float(r[b]), "rsi_at_first_swing": float(r[a]),
                     "stop_price": float(stop_px), "fill": fill,
                     "opp_fill": tick.bid if side == 1 else tick.ask,
                     "stop": stop, "stop_pips": round(stop / pip, 2),
                     "frozen": {"piv": PIV, "max_gap": MAX_GAP, "rsi": 14, "level": "none", "confirm": "none",
                                "exit": f"RSI {EXIT_BUY:g}/{100 - EXIT_BUY:g}", "hold": HOLD_BARS}}
            _append(entry)
            trades[sid] = entry
            report["symbols"][sym] = "NEW SHADOW TRADE"
        except Exception as e:                                   # one market must not stop the rest
            report["symbols"][sym] = f"error: {e!r}"[:200]
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(report, indent=1))
    return report


def summary() -> str:
    done = [t for t in _load().values() if "net_r" in t]
    lines = [f"RSI divergence, +-{PIV} M1 swings (shadow only) -- {len(done)} resolved "
             f"(verdict needs {MIN_TRADES_FOR_VERDICT})"]
    if done:
        net = np.array([t["net_r"] for t in done])
        opp = np.array([t["opp_net_r"] for t in done])
        lines.append(f"  won {np.mean(net > 0) * 100:.1f}%  net {net.mean():+.3f}R  opposite {opp.mean():+.3f}R")
    lines.append(f"  VERDICT: {verdict()[0]}   orders: never (shadow only)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        print(summary())
        return
    import core.console_safe  # noqa: F401
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        while True:
            rep = cycle(mt5)
            flagged = {s: v for s, v in rep["symbols"].items() if v != "watching"}
            print(time.strftime("%H:%M:%S"), json.dumps(flagged), flush=True)
            if args.once:
                break
            time.sleep(60 - time.time() % 60 + 5)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
