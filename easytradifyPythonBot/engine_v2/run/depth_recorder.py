"""Order-book depth recorder (strategic plan v4, new input for the M1 edge search). Read-only: places no orders.

Every second, for every subscribed symbol, it reads the MT5 market book (market_book_get) and the last tick.
A snapshot is stored only when the book or the quote changed. Every FLUSH_SECONDS the buffered snapshots are
written to tradify_study/depth/<SYMBOL>/<YYYYMMDD_HHMMSS>.npz (short interval: an abrupt kill loses little):
    t_msc (int64), bid, ask (float64), bid_px/bid_vol/ask_px/ask_vol (float64, LEVELS columns, best first, NaN padded)
A heartbeat with per-symbol counts goes to tradify_study/depth/recorder.log once a minute.

    python -m engine_v2.run.depth_recorder
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np

SYMBOLS = ("EURUSD GBPUSD USDJPY AUDUSD NZDUSD USDCAD USDCHF EURGBP EURJPY GBPJPY EURCAD AUDNZD AUDCAD AUDCHF GBPAUD "
           "XAUUSD XAGUSD US500 USTEC US30 US2000 DE40 STOXX50 F40 UK100 JP225 HK50 AUS200 XTIUSD XBRUSD").split()
OUT = os.environ.get("TRADIFY_DEPTH_DIR", "C:/Users/msi/tradify_study/depth")
LEVELS = 10
POLL_SECONDS = 1.0
FLUSH_SECONDS = 120
HEARTBEAT_SECONDS = 60


def log(msg: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/recorder.log", "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}\n")


def connect(mt5) -> bool:
    if not mt5.initialize(timeout=20000):
        log(f"initialize failed {mt5.last_error()}")
        return False
    for s in SYMBOLS:
        mt5.market_book_add(s)
    log("connected; subscribed " + " ".join(SYMBOLS))
    return True


def snapshot(mt5, symbol: str):
    book = mt5.market_book_get(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not book or tick is None:
        return None
    buys = sorted((x for x in book if x.type in (mt5.BOOK_TYPE_BUY, mt5.BOOK_TYPE_BUY_MARKET)), key=lambda x: -x.price)
    sells = sorted((x for x in book if x.type in (mt5.BOOK_TYPE_SELL, mt5.BOOK_TYPE_SELL_MARKET)), key=lambda x: x.price)

    def side(levels):
        px = np.full(LEVELS, np.nan)
        vol = np.full(LEVELS, np.nan)
        for k, x in enumerate(levels[:LEVELS]):
            px[k], vol[k] = x.price, x.volume_dbl
        return px, vol

    bpx, bvol = side(buys)
    apx, avol = side(sells)
    return int(tick.time_msc), float(tick.bid), float(tick.ask), bpx, bvol, apx, avol


def flush(buffers: dict) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for sym, rows in buffers.items():
        if not rows:
            continue
        os.makedirs(f"{OUT}/{sym}", exist_ok=True)
        np.savez_compressed(f"{OUT}/{sym}/{stamp}.npz",
                            t_msc=np.array([r[0] for r in rows], np.int64),
                            bid=np.array([r[1] for r in rows]), ask=np.array([r[2] for r in rows]),
                            bid_px=np.array([r[3] for r in rows]), bid_vol=np.array([r[4] for r in rows]),
                            ask_px=np.array([r[5] for r in rows]), ask_vol=np.array([r[6] for r in rows]))
        rows.clear()


def main() -> None:
    import MetaTrader5 as mt5
    buffers = {s: [] for s in SYMBOLS}
    last_key: dict[str, tuple] = {}
    counts = {s: 0 for s in SYMBOLS}
    connected = connect(mt5)
    last_flush = last_beat = time.time()
    log("recorder started")
    try:
        while True:
            loop_start = time.time()
            if not connected:
                time.sleep(10)
                connected = connect(mt5)
                continue
            try:
                for s in SYMBOLS:
                    snap = snapshot(mt5, s)
                    if snap is None:
                        continue
                    key = (snap[1], snap[2], tuple(np.nan_to_num(snap[3])), tuple(np.nan_to_num(snap[4])),
                           tuple(np.nan_to_num(snap[5])), tuple(np.nan_to_num(snap[6])))
                    if last_key.get(s) == key:
                        continue
                    last_key[s] = key
                    buffers[s].append(snap)
                    counts[s] += 1
            except Exception as e:  # terminal restarted or connection lost
                log(f"read error {e!r}; reconnecting")
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                connected = False
                continue
            now = time.time()
            if now - last_flush >= FLUSH_SECONDS:
                flush(buffers)
                last_flush = now
            if now - last_beat >= HEARTBEAT_SECONDS:
                active = {s: c for s, c in counts.items() if c}
                log(f"heartbeat snapshots since start: {active}")
                last_beat = now
            time.sleep(max(0.0, POLL_SECONDS - (time.time() - loop_start)))
    finally:
        flush(buffers)
        log("recorder stopped")
        try:
            mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
