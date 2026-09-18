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
        while RSI there is HIGHER, and RSI at the new pivot is < 20.
  SELL: the mirror -- higher high, lower RSI high, RSI > 80.
  Confirmation: a break of structure -- within 60 M1 bars of the divergence, a bar
         closes above the previous 5 bars' high (below their low for a SELL);
         cancelled if the stop is reached first. (Added 2026-09-18, the operator's
         idea; measured best: 56% won, -0.15R / -0.11R vs -0.15R / -0.15R without.)
  Entry: at the tick after the confirming bar closes (BUY at the ask, SELL at the bid).
  Stop : the divergence swing -1 pip (+1 for a SELL); at least 2 pips from the
         fill; must fit $4 at the 0.01 lot.
  Exit : a BUY closes when RSI(14) closes at or above 80, a SELL at or below 20
         (80/20 for entry and exit: operator, 2026-09-18); stop first; 480-bar cap.
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

# The setup is defined ONCE, in core/rsi_divergence_setup.py, and the app's RSI
# score and RSI setup read the same module. v3 journal: since 2026-09-18 the entry
# waits for a break of structure (the operator's confirmation idea, the best
# measured variant) -- a different setup, so its trades do not mix with v1/v2.
from core.rsi_divergence_setup import (  # noqa: E402
    BOS_BARS, EXIT_BUY, EXTREME, HISTORY, HOLD_BARS, LOOK, PIV, RSI_N, WAIT,
    current_setup, detect, divergence_state, mid_arrays, pip_size, pivot_flags,
    rsi_exit_hit, rsi_wilder,
)

# v4: levels 80/20 for entry and exit (operator, 2026-09-18) -- a different setup
JOURNAL = Path(__file__).resolve().parents[2] / "reports" / "v2" / "shadow_rsi_div_m1_v4.jsonl"
HEARTBEAT = JOURNAL.with_name("shadow_rsi_div_m1_heartbeat.json")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
           "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY"]
RISK_USD = 4.0
MIN_STOP_PIPS = 2.0      # the study's floor: a stop closer than 2 pips is not a real order
MIN_TRADES_FOR_VERDICT = 300


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
            stop_low, stop_high = bid["low"], bid["high"] + sp     # what a stop is judged on
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
                             "exit_bar_time": int(tr["entry_bar_time"]) + 60 * (res[1] - 1),
                             "opp_net_r": opp[0] - c})
                    open_by_sym.pop(sym)
                report["symbols"][sym] = "open" if sym in open_by_sym else "resolved"
                if sym in open_by_sym:
                    continue

            # 2. a divergence confirmed by a break of structure on the bar that just closed
            pip = pip_size(sym)
            # one trade per market at a time, as in the study: divergences known
            # before the previous trade's exit do not count
            last_exit = max((t_["exit_bar_time"] for t_ in trades.values()
                             if t_.get("symbol") == sym and "exit_bar_time" in t_), default=None)
            not_before = None
            if last_exit is not None:
                idx = int(np.searchsorted(t, last_exit, side="right")) - 1
                not_before = idx if idx >= 0 else None
            hit = current_setup(mid_h, mid_l, mid_c, stop_low, stop_high, pip, not_before=not_before)
            if hit is None:
                report["symbols"].setdefault(sym, "watching")
                continue
            side, j, ref, rsi_at = hit["side"], hit["swing_index"], hit["swing_price"], hit["rsi_at_swing"]
            sid = f"{sym}-{int(t[j])}-{side}"
            if sid in trades:
                continue
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            fill_now = tick.ask if side == 1 else tick.bid
            stop = side * (fill_now - hit["stop_price"])           # distance from the fill to the swing stop
            if stop < MIN_STOP_PIPS * pip:
                _append({"event": "SKIPPED", "id": sid, "symbol": sym, "stop_pips": round(stop / pip, 2),
                         "reason": f"stop closer than {MIN_STOP_PIPS:g} pips to the fill"})
                continue
            if f.risk_usd_at_min_lot(stop) > RISK_USD * 1.12:
                _append({"event": "SKIPPED", "id": sid, "symbol": sym, "reason": "stop does not fit $4 at 0.01 lot",
                         "stop_pips": stop / pip})
                continue
            entry = {"event": "ENTRY", "id": sid, "symbol": sym, "side": side,
                     "detected_at": int(time.time()), "entry_bar_time": int(t[-1]) + 60,
                     "pivot_time": int(t[j]), "pivot_price": ref, "rsi_at_pivot": rsi_at,
                     "known_time": int(t[hit["known_index"]]), "bos_time": int(t[hit["bos_index"]]),
                     "stop_price": hit["stop_price"],
                     "fill": tick.ask if side == 1 else tick.bid,
                     "opp_fill": tick.bid if side == 1 else tick.ask,
                     "stop": stop, "target": None, "stop_pips": round(stop / pip, 2),
                     "frozen": {"piv": PIV, "look": LOOK, "rsi": RSI_N, "extreme": EXTREME,
                                "confirm": f"BOS {BOS_BARS} bars within {WAIT}",
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
