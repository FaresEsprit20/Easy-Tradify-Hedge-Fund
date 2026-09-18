"""The frozen RSI-extreme divergence setup on live M1 data: journal + DEMO orders.

    python -m engine_v2.run.shadow_rsi_div_m1            # loops at every M1 close
    python -m engine_v2.run.shadow_rsi_div_m1 --once
    python -m engine_v2.run.shadow_rsi_div_m1 --report   # results so far

Why it exists
-------------
The M1 trend-component audit (tradify_study/trend_m1_v1/components_m1.py,
2026-09-18) tested ~170 setup x swing x target cells. One setup -- regular RSI
divergence with RSI at the correct extreme at the pivot (the operator's idea) --
beat its own opposite side in BOTH halves at every swing size from +-20 bars up.
Nothing else did. It was still net NEGATIVE (-0.22R per trade at +-50 bars).
This runner confirms or kills it on M1 data it has never seen.

Since 2026-09-18 (operator decision) it is also the ONLY thing that trades the
demo account: every journaled setup is sent as a DEMO order through
engine_v2/run/rsi_div_live.py (refused on a non-demo account, pivot stop kept,
lot sized to $4, RSI 70/30 exit, 480-bar cap). The journal keeps the theoretical
fill and the opposite side, so the verdict below is unaffected by execution;
ORDER / RSI_EXIT / TIME_EXIT events record what the demo account actually did.

FROZEN (changing any of these makes it a different, unconfirmed setup)
------
  M1 only. Mid = bid + half the bar's spread.
  RSI(14), Wilder smoothing.
  Pivot low/high = the extreme of +-50 M1 bars, known 50 bars after it.
  BUY : the new pivot low is LOWER than the previous pivot low (within 1000 bars)
        while RSI there is HIGHER, and RSI at the new pivot is < 30.
  SELL: mirror (higher high, lower RSI high, RSI > 70).
  Entry: at the tick when the pivot is confirmed (BUY at the ask, SELL at the bid).
  Stop : the pivot price +- 1 pip (2 pips if price is already through it);
         must fit $4 at the 0.01 lot.
  Exit : the conventional RSI exit -- a BUY closes when RSI(14) closes at or
         above 70, a SELL at or below 30; stop first; 480-bar cap.
         (Was a fixed 1:2 target until 2026-09-18. Operator: "stick to the
         conventional RSI divergence rules". Measured on the same history --
         tradify_study/trend_m1_v1/conventional_rsi_div.py, 50 textbook
         variants, none profitable -- the RSI-70 exit was the best: 51% won,
         -0.16R / -0.14R per trade in the two halves vs -0.21R / -0.16R for
         1:2, and it beat the opposite side in both halves.)
  One open shadow trade per market.

Control (recorded on every trade): the OPPOSITE side, same stop distance,
closed on the same bar as the taken trade (same holding time).

Pre-registered verdict, written before any live result exists
-------------
After at least 300 resolved trades:
  CONFIRMED  net R per trade > 0 AND taken beats the opposite side
  DIRECTION ONLY  taken beats the opposite by > 0.05R but net R <= 0
  DEAD       otherwise
Costs in R: commission from the broker's own facts. Outcomes resolve on M1
bars (bid OHLC, ask = bid + the bar's spread), a bar touching both levels
counts as the stop.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from engine_v2.run import rsi_div_live

# v2 journal: the exit changed from a fixed 1:2 to the conventional RSI exit, which
# makes it a different setup -- its trades must not mix with the 1:2 ones
JOURNAL = Path(__file__).resolve().parents[2] / "reports" / "v2" / "shadow_rsi_div_m1_v2.jsonl"
HEARTBEAT = JOURNAL.with_name("shadow_rsi_div_m1_heartbeat.json")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
           "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY"]
PIV = 50
LOOK = 1000
RSI_N = 14
EXTREME = 30.0
EXIT_BUY = 70.0          # a BUY closes when RSI closes >= 70 (SELL: <= 30)
HOLD_BARS = 480          # the study's cap: close at market if neither stop nor RSI exit
HISTORY = 1600          # closed M1 bars fetched per cycle (LOOK + 2*PIV + RSI warm-up)
RISK_USD = 4.0
MIN_TRADES_FOR_VERDICT = 300


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


# ---------------------------------------------------------------------------
# the frozen detector -- pure functions, no MT5
# ---------------------------------------------------------------------------

def rsi_wilder(c: np.ndarray, n: int = RSI_N) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = np.empty_like(c), np.empty_like(c)
    au[0], ad[0] = up[0], dn[0]
    for i in range(1, c.size):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def pivot_flags(x: np.ndarray, low: bool) -> np.ndarray:
    """x[i] is the extreme of x[i-PIV : i+PIV+1]; False where the window is incomplete."""
    out = np.zeros(x.size, bool)
    if x.size < 2 * PIV + 1:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, 2 * PIV + 1)
    ext = w.min(axis=1) if low else w.max(axis=1)
    out[PIV:x.size - PIV] = x[PIV:x.size - PIV] == ext
    return out


def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray):
    """On CLOSED bars (last element = the bar that just closed): the setup whose
    pivot is confirmed by that bar, or None. Returns (side, pivot_index, ref, rsi)."""
    n = close.size
    j = n - 1 - PIV
    if j - PIV <= 0:
        return None
    r = rsi_wilder(close)
    for is_low in (True, False):
        px = low if is_low else high
        piv = pivot_flags(px, is_low)
        if not piv[j]:
            continue
        start = max(0, j - LOOK)
        prev = np.flatnonzero(piv[start:j - PIV])
        if not prev.size:
            continue
        p = start + int(prev[-1])
        if is_low and px[j] < px[p] and r[j] > r[p] and r[j] < EXTREME:
            return 1, j, float(px[j]), float(r[j])
        if not is_low and px[j] > px[p] and r[j] < r[p] and r[j] > 100 - EXTREME:
            return -1, j, float(px[j]), float(r[j])
    return None


def plan(side: int, entry_mid: float, ref: float, pip: float) -> float:
    """Stop distance (price), exactly as in the study. There is no price target:
    the trade exits on RSI (EXIT_BUY / 100 - EXIT_BUY)."""
    stop = max(abs(entry_mid - ref) + pip, pip)
    if (side == 1 and ref >= entry_mid) or (side == -1 and ref <= entry_mid):
        stop = 2 * pip
    return stop


def rsi_exit_hit(side: int, rsi_value: float) -> bool:
    return rsi_value >= EXIT_BUY if side == 1 else rsi_value <= 100 - EXIT_BUY


def _stop_hit(side, b, stop_px):
    bo, bh, bl, bc, ao, ah, al, ac = b
    if side == 1:
        return bl <= stop_px, bo
    return ah >= stop_px, ao


def resolve(side: int, fill: float, stop: float, bars, rsis):
    """Walk M1 bars after entry: (R before costs, bars used) or None if still open.
    Stop first; then the RSI exit at the bar's close; 480-bar cap.
    bars: (bid_open, bid_high, bid_low, bid_close, ask_open, ask_high, ask_low, ask_close)
    rsis: RSI(14) on mid closes, one per bar."""
    stop_px = fill - side * stop
    for k, (b, r) in enumerate(zip(bars[:HOLD_BARS], rsis[:HOLD_BARS])):
        hit, op = _stop_hit(side, b, stop_px)
        if hit:
            px = op if k > 0 and ((side == 1 and op < stop_px) or (side == -1 and op > stop_px)) else stop_px
            return side * (px - fill) / stop, k + 1
        if rsi_exit_hit(side, r):
            close = b[3] if side == 1 else b[7]
            return side * (close - fill) / stop, k + 1
    if len(bars) >= HOLD_BARS:
        last = bars[HOLD_BARS - 1]
        return side * ((last[3] if side == 1 else last[7]) - fill) / stop, HOLD_BARS
    return None


def resolve_matched(side: int, fill: float, stop: float, bars, n_bars: int) -> float:
    """The control: same stop distance, closed on the same bar as the taken trade."""
    stop_px = fill - side * stop
    for k, b in enumerate(bars[:n_bars]):
        hit, op = _stop_hit(side, b, stop_px)
        if hit:
            px = op if k > 0 and ((side == 1 and op < stop_px) or (side == -1 and op > stop_px)) else stop_px
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


def _bars(mt5, symbol, count):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count + 1)
    if rates is None or len(rates) < 2:
        return None
    rates = rates[:-1]                                   # the last bar is still forming
    info = mt5.symbol_info(symbol)
    sp = rates["spread"].astype(float) * info.point
    return rates, sp


def cycle(mt5) -> dict:
    from engine_v2.data.symbols import facts
    trades = _load()
    open_by_sym = {t["symbol"]: t for t in trades.values() if "net_r" not in t}
    v, n_resolved = verdict(trades)
    status = f"{v} ({n_resolved}/{MIN_TRADES_FOR_VERDICT} resolved)"
    report = {"at": int(time.time()), "verdict": status, "symbols": {}}
    # the study's 480-bar cap, on real demo positions
    for ex in rsi_div_live.time_exits(mt5):
        _append({"event": "TIME_EXIT", "at": int(time.time()), **ex})
    for sym in SYMBOLS:
        try:
            got = _bars(mt5, sym, HISTORY)
            if got is None:
                report["symbols"][sym] = "no bars"
                continue
            rates, sp = got
            t = rates["time"].astype(np.int64)
            bid = {k: rates[k].astype(float) for k in ("open", "high", "low", "close")}
            f = facts(sym)
            mid_h = bid["high"] + sp / 2
            mid_l = bid["low"] + sp / 2
            mid_c = bid["close"] + sp / 2
            rsi_now = rsi_wilder(mid_c)
            # the RSI exit on real demo positions (nothing to do while none are open)
            for ex in rsi_div_live.rsi_exits(mt5, sym, float(rsi_now[-1])):
                _append({"event": "RSI_EXIT", "at": int(time.time()), **ex})

            # 1. resolve the open trade, if any
            tr = open_by_sym.get(sym)
            if tr is not None:
                after = np.flatnonzero(t >= tr["entry_bar_time"])
                bars = [(bid["open"][i], bid["high"][i], bid["low"][i], bid["close"][i],
                         bid["open"][i] + sp[i], bid["high"][i] + sp[i], bid["low"][i] + sp[i],
                         bid["close"][i] + sp[i]) for i in after]
                res = resolve(tr["side"], tr["fill"], tr["stop"], bars, list(rsi_now[after]))
                if res is not None:
                    opp = (resolve_matched(-tr["side"], tr["opp_fill"], tr["stop"], bars, res[1]),)
                    c = f.commission_r(tr["stop"])
                    _append({"event": "RESOLVED", "id": tr["id"], "resolved_at": int(time.time()),
                             "gross_r": res[0], "net_r": res[0] - c, "bars": res[1],
                             "opp_net_r": opp[0] - c})
                    open_by_sym.pop(sym)
                report["symbols"][sym] = "open" if sym in open_by_sym else "resolved"
                if sym in open_by_sym:
                    continue

            # 2. a new setup confirmed by the bar that just closed
            hit = detect(mid_h, mid_l, mid_c)
            if hit is None:
                report["symbols"].setdefault(sym, "watching")
                continue
            side, j, ref, rsi_at = hit
            sid = f"{sym}-{int(t[j])}-{side}"
            if sid in trades:
                continue
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            pip = pip_size(sym)
            entry_mid = (tick.bid + tick.ask) / 2
            stop = plan(side, entry_mid, ref, pip)
            if f.risk_usd_at_min_lot(stop) > RISK_USD * 1.12:
                _append({"event": "SKIPPED", "id": sid, "symbol": sym, "reason": "stop does not fit $4 at 0.01 lot",
                         "stop_pips": stop / pip})
                continue
            entry = {"event": "ENTRY", "id": sid, "symbol": sym, "side": side,
                     "detected_at": int(time.time()), "entry_bar_time": int(t[-1]) + 60,
                     "pivot_time": int(t[j]), "pivot_price": ref, "rsi_at_pivot": round(rsi_at, 2),
                     "fill": tick.ask if side == 1 else tick.bid,
                     "opp_fill": tick.bid if side == 1 else tick.ask,
                     "stop": stop, "target": None, "stop_pips": round(stop / pip, 2),
                     "frozen": {"piv": PIV, "look": LOOK, "rsi": RSI_N, "extreme": EXTREME,
                                "exit": f"RSI {EXIT_BUY:g}/{100 - EXIT_BUY:g}", "hold": HOLD_BARS}}
            _append(entry)
            trades[sid] = entry
            report["symbols"][sym] = "NEW SHADOW TRADE"
            # the demo order for the same setup (refused unless enabled and on a demo account)
            order = rsi_div_live.place(mt5, sym, side, entry["fill"], stop, None,
                                       confirmed=(v == "CONFIRMED"), status=status)
            _append({"event": "ORDER", "id": sid, "at": int(time.time()), **order})
            if order.get("placed"):
                report["symbols"][sym] = f"DEMO ORDER {order.get('ticket')}"
        except Exception as e:                           # one market must not stop the rest
            report["symbols"][sym] = f"error: {e!r}"[:200]
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(report, indent=1))
    return report


def verdict(trades: dict | None = None) -> tuple[str, int]:
    """The pre-registered verdict on the resolved shadow trades: PENDING below
    MIN_TRADES_FOR_VERDICT, then CONFIRMED / DIRECTION ONLY / DEAD."""
    done = [t for t in (trades if trades is not None else _load()).values() if "net_r" in t]
    n = len(done)
    if n < MIN_TRADES_FOR_VERDICT:
        return "PENDING", n
    net = float(np.mean([t["net_r"] for t in done]))
    opp = float(np.mean([t["opp_net_r"] for t in done]))
    if net > 0 and net > opp:
        return "CONFIRMED", n
    if net - opp > 0.05:
        return "DIRECTION ONLY", n
    return "DEAD", n


def summary() -> str:
    trades = [t for t in _load().values() if "net_r" in t]
    n = len(trades)
    lines = [f"RSI-extreme divergence, M1 -- {n} resolved shadow trades "
             f"(verdict needs {MIN_TRADES_FOR_VERDICT})"]
    if not n:
        return "\n".join(lines)
    net = np.array([t["net_r"] for t in trades])
    opp = np.array([t["opp_net_r"] for t in trades])
    se = net.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
    lines.append(f"  won {np.mean(net > 0) * 100:.1f}%  net {net.mean():+.3f}R (+-{1.96 * se:.3f})  "
                 f"opposite side {opp.mean():+.3f}R  difference {net.mean() - opp.mean():+.3f}R")
    by = {}
    for t in trades:
        by.setdefault(t["symbol"], []).append(t["net_r"])
    lines.append(f"  markets net-positive: {sum(np.mean(v) > 0 for v in by.values())}/{len(by)}")
    v, _ = verdict()
    lines.append(f"  VERDICT: {v}" + (f" ({n}/{MIN_TRADES_FOR_VERDICT} trades)" if v == "PENDING" else ""))
    lines.append(f"  demo trading: {'ON' if v == 'CONFIRMED' else 'OFF until CONFIRMED'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        print(summary())
        return
    import core.console_safe  # noqa: F401  UTF-8 output; a click in the window cannot freeze the loop
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        while True:
            rep = cycle(mt5)
            flagged = {s: v for s, v in rep["symbols"].items() if v not in ("watching",)}
            print(time.strftime("%H:%M:%S"), json.dumps(flagged), flush=True)
            if args.once:
                break
            now = time.time()
            time.sleep(60 - now % 60 + 3)                # just after each M1 close
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
