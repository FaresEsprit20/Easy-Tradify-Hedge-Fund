"""
RSI divergence on H4 -- DEMO orders (operator decision, 2026-09-18).

Why: tradify_study/trend_m1_v1/rsi_div_higher_tf.py. Of 72 pre-registered H1/H4
cells this was the only one to pass the development halves AND the untouched
holdout (last third, 2026-03..09): development +0.04R / +0.42R, holdout +0.17R
(38 trades), opposite side -0.47R; re-scored on real bid/ask H4 bars built from
the M1 bid/ask data: +0.21R over 31 trades. Thin: 85 trades in 18 months.
The operator chose to trade it on the demo account now (not shadow first).

Setup (frozen = the study's cell "H4, +-3, any, BOS, 1:3")
  RSI      logarithmic RSI(14) of the H4 bid closes (core/rsi_divergence_setup)
  swing    an H4 bar whose low (high) is the lowest (highest) of the 3 bars on
           each side; known 3 bars later
  signal   classic divergence against the immediately preceding swing of the
           same kind, 3 < gap <= 60 bars: lower low + higher RSI -> BUY,
           higher high + lower RSI -> SELL; no RSI level
  confirm  within the next 10 H4 bars a bar CLOSES above the highest high of the
           previous 5 bars (below the lowest low for a SELL); cancelled if the
           stop is reached first
  entry    at market right after the confirming bar closes
  stop     the swing -1 pip (SELL: the swing high + spread +1 pip); >= 2 pips;
           must fit $4 at 0.01 lot (else skipped, as in the study)
  target   1:3 (broker take-profit); cap 120 H4 bars (20 days), then closed
  one position per market; a divergence known before the previous trade in that
  market closed does not count (the study's rule)

Pre-registered live verdict (written before the first live trade)
  after 40 closed trades: KEEP if mean net R > 0 AND beats the opposite side
  (same stop, same holding time, simulated on the H4 bars); otherwise STOP.
  Brake: new orders stop automatically on a STOP verdict, or if the cumulative
  net result reaches -10R (about -$40 of demo money) at any time.
Safety: RSI_DIV_H4_LIVE off -> nothing is sent; not a DEMO account -> refused.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from core.rsi_divergence_setup import pip_size, rsi_wilder

PIV = 3
MAX_GAP = 20 * PIV
BOS_BARS = 5
WAIT = 10
TARGET_R = 3.0
HOLD_BARS = 120
BAR_S = 14400
HISTORY = 400                      # closed H4 bars read each cycle
RISK_USD = 4.0
MIN_STOP_PIPS = 2.0
MIN_TRADES_FOR_VERDICT = 40
BRAKE_R = -10.0
MAGIC = 20260919
COMMENT = "RSIdiv H4"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCAD",
           "AUDNZD", "AUDCAD", "AUDCHF", "GBPAUD", "GBPJPY", "EURJPY"]
JOURNAL = Path(__file__).resolve().parents[2] / "reports" / "v2" / "rsi_div_h4_v1.jsonl"
HEARTBEAT = JOURNAL.with_name("rsi_div_h4_heartbeat.json")


# ---------------------------------------------------------------------------
# the setup (pure functions -- parity-tested against the study)
# ---------------------------------------------------------------------------

def pivot_flags(x: np.ndarray, low: bool) -> np.ndarray:
    out = np.zeros(x.size, bool)
    if x.size < 2 * PIV + 1:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, 2 * PIV + 1)
    ext = w.min(axis=1) if low else w.max(axis=1)
    out[PIV:x.size - PIV] = x[PIV:x.size - PIV] == ext
    return out


def divergences(h, l, r):
    """(known bar i, side, swing bar b) -- the study's consecutive-swing pairing."""
    out = []
    for low in (True, False):
        px = l if low else h
        pv = np.flatnonzero(pivot_flags(px, low))
        for a, b in zip(pv[:-1], pv[1:]):
            if b - a > MAX_GAP or b - a <= PIV:
                continue
            if low and px[b] < px[a] and r[b] > r[a]:
                out.append((b + PIV, 1, b))
            if not low and px[b] > px[a] and r[b] < r[a]:
                out.append((b + PIV, -1, b))
    return sorted(out)


def stop_price(side: int, h, l, sp, b: int, pip: float) -> float:
    return (l[b] if side == 1 else h[b] + sp[b]) - side * pip


def confirmation_bar(side, i, b, h, l, c, sp, pip):
    """The bar that confirms divergence (i, side, b), or None (stopped / expired / not yet)."""
    stop_px = stop_price(side, h, l, sp, b, pip)
    for k in range(i + 1, min(i + 1 + WAIT, c.size)):
        if (side == 1 and l[k] <= stop_px) or (side == -1 and h[k] + sp[k] >= stop_px):
            return None
        if (c[k] > h[k - BOS_BARS:k].max()) if side == 1 else (c[k] < l[k - BOS_BARS:k].min()):
            return k
    return None


def triggers_on_last_bar(h, l, c, sp, pip, not_before_bar: int = -1):
    """Setups whose confirmation is the LAST closed bar: [(side, i, b, stop_price)].
    Divergences known at or before not_before_bar (the previous trade's exit) are ignored."""
    last = c.size - 1
    r = rsi_wilder(c)
    out = []
    for i, side, b in divergences(h, l, r):
        if i <= not_before_bar or not (last - WAIT <= i < last):
            continue
        if confirmation_bar(side, i, b, h, l, c, sp, pip) == last:
            out.append((side, i, b, stop_price(side, h, l, sp, b, pip)))
    return out


def nights(t0: int, t1: int) -> int:
    from engine_v2.run.shadow_rsi_div_huge import nights as _n
    return _n(t0, t1)


def opposite_r(side, fill_opp, stop, bars_after, sp_after):
    """The control: the other side, same stop distance, closed on the taken trade's last bar."""
    s = -side
    stop_px = fill_opp - s * stop
    last_close = None
    for (o, h, l, c), spk in zip(bars_after, sp_after):
        lo, hi = (l, h) if s == 1 else (l + spk, h + spk)
        if (lo <= stop_px) if s == 1 else (hi >= stop_px):
            return -1.0
        last_close = c if s == 1 else c + spk
    return s * (last_close - fill_opp) / stop if last_close is not None else 0.0


# ---------------------------------------------------------------------------
# journal / verdict
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
            elif e["event"] == "SKIPPED":
                trades.setdefault(e["id"], {"id": e["id"], "symbol": e["symbol"], "skipped": True})
            elif e["event"] == "RESOLVED" and e["id"] in trades:
                trades[e["id"]].update(e)
    return trades


def _append(event: dict):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def verdict(trades: dict | None = None) -> tuple[str, int, float]:
    """(PENDING | KEEP | STOP | BRAKE, closed trades, cumulative net R)."""
    done = [t for t in (trades if trades is not None else _load()).values() if "net_r" in t]
    n = len(done)
    cum = float(sum(t["net_r"] for t in done))
    if cum <= BRAKE_R:
        return "BRAKE", n, cum
    if n < MIN_TRADES_FOR_VERDICT:
        return "PENDING", n, cum
    net = float(np.mean([t["net_r"] for t in done]))
    opp = float(np.mean([t["opp_net_r"] for t in done]))
    return ("KEEP" if net > 0 and net > opp else "STOP"), n, cum


def orders_allowed(v: str) -> bool:
    return v in ("PENDING", "KEEP")


# ---------------------------------------------------------------------------
# live
# ---------------------------------------------------------------------------

def live_enabled() -> bool:
    from core.asset_analysis_config import RSI_DIV_H4_LIVE
    return bool(RSI_DIV_H4_LIVE)


def is_demo(mt5) -> bool:
    info = mt5.account_info()
    return info is not None and info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


def _bars(mt5, sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, HISTORY + 1)
    if rates is None or len(rates) < 100:
        return None
    rates = rates[:-1]                                      # the last H4 bar is still forming
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    sp = rates["spread"].astype(float) * info.point
    if tick is not None:                                    # bar spreads are minimums; never below the live one
        sp = np.maximum(sp, tick.ask - tick.bid)
    return rates, sp


def _resolve(mt5, tr, f):
    """A closed position: its real result from the deals, and the opposite-side control."""
    ticket = tr.get("ticket")
    if not ticket or mt5.positions_get(ticket=ticket):
        return None
    deals = [d for d in (mt5.history_deals_get(position=ticket) or ())]
    if not deals:
        return None
    usd = float(sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals))
    exit_time = int(max(d.time for d in deals))
    risk_usd = float(tr["stop"]) * f.usd_per_price_unit_per_lot * float(tr.get("volume") or 0.01)
    rates = mt5.copy_rates_range(tr["symbol"], mt5.TIMEFRAME_H4, int(tr["entry_time"]) - BAR_S, exit_time + BAR_S)
    opp = 0.0
    if rates is not None and len(rates):
        info = mt5.symbol_info(tr["symbol"])
        sel = [k for k in range(len(rates)) if int(tr["entry_time"]) - BAR_S < rates["time"][k] <= exit_time]
        bars = [(rates["open"][k], rates["high"][k], rates["low"][k], rates["close"][k]) for k in sel]
        sps = [max(rates["spread"][k] * info.point, tr.get("spread_at_entry", 0.0)) for k in sel]
        opp = opposite_r(tr["side"], tr["opp_fill"], tr["stop"], bars, sps)
        opp += -f.commission_r(tr["stop"]) + nights(int(tr["entry_time"]), exit_time) * f.swap_r_per_night(-tr["side"], tr["stop"])
    return {"event": "RESOLVED", "id": tr["id"], "resolved_at": int(time.time()), "exit_time": exit_time,
            "usd": round(usd, 2), "risk_usd": round(risk_usd, 2),
            "net_r": usd / risk_usd if risk_usd > 0 else 0.0, "opp_net_r": opp}


def _close_expired(mt5):
    out = []
    for pos in mt5.positions_get() or ():
        if pos.magic != MAGIC:
            continue
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None or tick.time - pos.time < HOLD_BARS * BAR_S:
            continue
        from core.execution import close_position
        try:
            res = close_position(pos.ticket, deviation=20)
            out.append({"ticket": pos.ticket, "symbol": pos.symbol, "closed": bool(res.get("success"))})
        except Exception as e:
            out.append({"ticket": pos.ticket, "symbol": pos.symbol, "closed": False, "reason": repr(e)[:200]})
    return out


def _place(mt5, sym, side, sl, tp):
    from core.execution import execute_trade
    try:
        res = execute_trade(symbol=sym, order_type="BUY" if side == 1 else "SELL", strategy_magic=MAGIC,
                            fixed_trade_size_usd=200.0, risk_per_trade=RISK_USD / 200.0, max_spread=30,
                            trade_deviation=20, max_trades_per_symbol=1, comment=COMMENT,
                            stop_loss_price=sl, take_profit_price=tp, keep_stop=True)
    except Exception as e:
        return {"placed": False, "reason": f"execute_trade raised: {e!r}"[:300]}
    return {"placed": bool(res.get("success")), "ticket": res.get("ticket"), "price": res.get("price"),
            "volume": res.get("volume") or res.get("lot"), "stop_loss": res.get("stop_loss"),
            "take_profit": res.get("take_profit"), "reason": res.get("error") or res.get("message")}


def cycle(mt5) -> dict:
    from engine_v2.data.symbols import facts
    trades = _load()
    v, n, cum = verdict(trades)
    report = {"at": int(time.time()), "verdict": f"{v} ({n}/{MIN_TRADES_FOR_VERDICT} closed, {cum:+.2f}R)",
              "orders": "on" if (orders_allowed(v) and live_enabled()) else "off", "symbols": {}}
    for ex in _close_expired(mt5):
        _append({"event": "TIME_EXIT", "at": int(time.time()), **ex})
    for sym in SYMBOLS:
        try:
            f = facts(sym)
            # 1. record closed trades
            for tr in [t for t in trades.values() if t["symbol"] == sym and "net_r" not in t and t.get("ticket")]:
                res = _resolve(mt5, tr, f)
                if res:
                    _append(res)
                    tr.update(res)
            if any(p.magic == MAGIC for p in (mt5.positions_get(symbol=sym) or ())):
                report["symbols"][sym] = "position open"
                continue
            got = _bars(mt5, sym)
            if got is None:
                report["symbols"][sym] = "no bars"
                continue
            rates, sp = got
            t = rates["time"].astype(np.int64)
            h, l, c = (rates[k].astype(float) for k in ("high", "low", "close"))
            pip = pip_size(sym)
            last_exit = max((tr.get("exit_time", 0) for tr in trades.values() if tr["symbol"] == sym), default=0)
            not_before = int(np.searchsorted(t, last_exit, side="right")) - 1 if last_exit else -1
            hits = triggers_on_last_bar(h, l, c, sp, pip, not_before)
            if not hits:
                report["symbols"][sym] = "watching"
                continue
            side, i, b, stop_px = hits[0]
            sid = f"{sym}-{int(t[b])}-{side}"
            if sid in trades:
                report["symbols"][sym] = "already taken"
                continue
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            fill = tick.ask if side == 1 else tick.bid
            stop = side * (fill - stop_px)
            if stop < MIN_STOP_PIPS * pip or f.risk_usd_at_min_lot(stop) > RISK_USD * 1.12:
                _append({"event": "SKIPPED", "id": sid, "symbol": sym, "side": side, "at": int(time.time()),
                         "stop_pips": round(stop / pip, 1),
                         "reason": "stop under 2 pips" if stop < MIN_STOP_PIPS * pip else "stop does not fit $4 at 0.01 lot"})
                trades[sid] = {"id": sid, "symbol": sym, "skipped": True}
                report["symbols"][sym] = "skipped (stop)"
                continue
            tp = fill + side * TARGET_R * stop
            entry = {"event": "ENTRY", "id": sid, "symbol": sym, "side": side, "at": int(time.time()),
                     "entry_time": int(t[-1]) + BAR_S, "swing_time": int(t[b]), "known_time": int(t[i]),
                     "confirm_time": int(t[-1]), "stop_price": stop_px, "target_price": tp,
                     "fill": fill, "opp_fill": tick.bid if side == 1 else tick.ask, "stop": stop,
                     "stop_pips": round(stop / pip, 1), "spread_at_entry": tick.ask - tick.bid,
                     "frozen": {"tf": "H4", "piv": PIV, "gap": MAX_GAP, "rsi": "log RSI14", "level": "any",
                                "confirm": f"BOS {BOS_BARS} within {WAIT}", "target": "1:3", "hold": HOLD_BARS}}
            if not (orders_allowed(v) and live_enabled()):
                entry["order"] = {"placed": False, "reason": f"orders off ({v}, live={live_enabled()})"}
            elif not is_demo(mt5):
                entry["order"] = {"placed": False, "reason": "refused: not a demo account"}
            else:
                entry["order"] = _place(mt5, sym, side, stop_px, tp)
                entry["ticket"] = entry["order"].get("ticket")
                entry["volume"] = entry["order"].get("volume")
            _append(entry)
            trades[sid] = entry
            report["symbols"][sym] = (f"DEMO ORDER {entry.get('ticket')}" if entry["order"].get("placed")
                                      else f"signal, no order: {entry['order'].get('reason')}"[:120])
        except Exception as e:                                    # one market must not stop the rest
            report["symbols"][sym] = f"error: {e!r}"[:200]
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(report, indent=1))
    return report


def summary() -> str:
    done = [t for t in _load().values() if "net_r" in t]
    v, n, cum = verdict()
    lines = [f"RSI divergence H4 (demo) -- {n} closed trades, verdict at {MIN_TRADES_FOR_VERDICT}: {v}, "
             f"cumulative {cum:+.2f}R"]
    if done:
        net = np.array([t["net_r"] for t in done])
        opp = np.array([t["opp_net_r"] for t in done])
        lines.append(f"  won {np.mean(net > 0) * 100:.1f}%  mean {net.mean():+.3f}R  opposite {opp.mean():+.3f}R  "
                     f"USD {sum(t['usd'] for t in done):+.2f}")
    lines.append(f"  new orders: {'ON' if orders_allowed(v) and live_enabled() else 'OFF'}")
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
            print(time.strftime("%H:%M:%S"), rep["verdict"], json.dumps(flagged), flush=True)
            if args.once:
                break
            time.sleep(60 - time.time() % 60 + 10)       # every minute; acts only on a new H4 close
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
