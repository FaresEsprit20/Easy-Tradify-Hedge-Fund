#!/usr/bin/env python3
"""
============================================================
RUN A REPLAY
============================================================
Pulls historical bars from MT5, replays the real engine over them, and
writes two files:

    replay_report.txt    <- human-readable, this is what you share
    replay_records.json  <- full per-decision detail

USAGE
    python -m core.run_replay                          # defaults below
    python -m core.run_replay --symbol XAUUSD --days 30
    python -m core.run_replay --step 10                # samples 1 bar in 10
    python -m core.run_replay --bars-only              # download and cache

    python core/run_replay.py --symbol XAGUSD          # also works

This file lives in core/. Either invocation works: it locates the
project root from its own path and puts it on sys.path, so `core.*`
imports resolve whether you run it as a module or as a script, and from
whatever working directory you happen to be in.

WHY THE BARS ARE CACHED
    The download is the slow part and the terminal only has to be open
    once. After the first run the bars sit in ./replay_bars/ and every
    later run reads from disk -- so you can re-run a replay after a code
    change without MT5 running at all, and against IDENTICAL data, which
    is the only way to compare two builds honestly.
============================================================
"""

import argparse
import json
import os
import sys
from datetime import datetime

# This module lives inside core/, so the PROJECT ROOT is its parent's
# parent. Putting that on sys.path is what lets `from core.market_data
# import ...` work when the file is executed directly as
# `python core/run_replay.py` -- without it Python only has core/ itself
# on the path and the package is invisible to its own contents.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Cache and outputs go in the project root, not in core/. Downloaded
# bars are data, not source, and burying a few hundred MB of .npy files
# inside a package directory is a good way to commit them by accident.
CACHE_DIR = os.path.join(_PROJECT_ROOT, "replay_bars")
REPORT_PATH = os.path.join(_PROJECT_ROOT, "replay_report.txt")
RECORDS_PATH = os.path.join(_PROJECT_ROOT, "replay_records.json")

# Higher timeframes need history BEFORE the M1 walk starts, or they get
# dropped for having too few closed bars and the engine silently loses
# its H1/H4 context. These counts are deliberately generous.
TF_BARS = {
    "M1": None,      # derived from --days
    "M5": 5000,
    "M15": 3000,
    "M30": 2000,
    "H1": 2000,
    "H4": 1000,
    "D1": 400,
}


def download(symbol, days):
    """Pull bars from MT5 and cache them."""
    import MetaTrader5 as mt5
    import numpy as np

    if not mt5.initialize():
        print(f"ERROR: could not connect to MT5: {mt5.last_error()}")
        print("Open the MetaTrader 5 terminal and log in, then re-run.")
        sys.exit(1)

    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"ERROR: symbol {symbol!r} not found. Check the exact name "
              f"in Market Watch (it may have a suffix like {symbol}.raw).")
        mt5.shutdown()
        sys.exit(1)
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)

    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
              "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
              "D1": mt5.TIMEFRAME_D1}

    counts = dict(TF_BARS)
    counts["M1"] = min(days * 1440, 200_000)

    os.makedirs(CACHE_DIR, exist_ok=True)
    meta = {
        "symbol": symbol,
        "downloaded": datetime.utcnow().isoformat(),
        "days": days,
        "digits": info.digits,
        "point": info.point,
        "trade_contract_size": info.trade_contract_size,
        "trade_tick_value": info.trade_tick_value,
        "trade_tick_size": info.trade_tick_size,
        "volume_min": info.volume_min,
        "volume_step": info.volume_step,
        "spread_current": info.spread,
        "bars": {},
    }

    for tf, n in counts.items():
        rates = mt5.copy_rates_from_pos(symbol, tf_map[tf], 0, n)
        if rates is None or len(rates) == 0:
            print(f"  {tf:>4}: NO DATA (skipped)")
            continue
        filename = f"{symbol}_{tf}.npy"
        np.save(os.path.join(CACHE_DIR, filename), rates)
        first = datetime.utcfromtimestamp(int(rates[0]["time"]))
        last = datetime.utcfromtimestamp(int(rates[-1]["time"]))
        # Filename only, not a full path: an absolute path baked into the
        # cache breaks the moment the project is moved or shared, and the
        # failure looks like missing data rather than a stale path.
        meta["bars"][tf] = {"count": len(rates), "file": filename,
                            "first": first.isoformat(), "last": last.isoformat()}
        print(f"  {tf:>4}: {len(rates):>7} bars   {first:%Y-%m-%d} -> {last:%Y-%m-%d}")

    account = mt5.account_info()
    if account:
        meta["balance"] = float(account.balance)
        meta["leverage"] = int(account.leverage)

    with open(os.path.join(CACHE_DIR, f"{symbol}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    mt5.shutdown()
    return meta


def load(symbol):
    import numpy as np
    meta_path = os.path.join(CACHE_DIR, f"{symbol}_meta.json")
    if not os.path.exists(meta_path):
        return None, None
    with open(meta_path) as f:
        meta = json.load(f)
    rates = {}
    for tf, d in meta["bars"].items():
        # "file" is current; "path" is tolerated so a cache written by an
        # earlier version still loads instead of silently coming back empty.
        name = d.get("file") or os.path.basename(d.get("path", ""))
        full = os.path.join(CACHE_DIR, name)
        if name and os.path.exists(full):
            rates[tf] = np.load(full)
    return rates, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAGUSD")
    ap.add_argument("--days", type=int, default=30,
                    help="days of M1 history to pull (default 30)")
    ap.add_argument("--step", type=int, default=5,
                    help="analyse every Nth bar; 1 is every bar (slow)")
    ap.add_argument("--warmup", type=int, default=800,
                    help="M1 bars to skip before the first decision")
    ap.add_argument("--spread", type=float, default=None,
                    help="fixed spread in pips; default uses each bar's own")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N decisions (for a quick smoke test)")
    ap.add_argument("--pip-size", type=float, default=None,
                    help="override pip size; use the value your live payload reports")
    ap.add_argument("--max-holding", type=int, default=500,
                    help="bars to wait for stop or target before UNRESOLVED")
    ap.add_argument("--refresh", action="store_true", help="re-download bars")
    ap.add_argument("--bars-only", action="store_true", help="download and exit")
    args = ap.parse_args()

    rates, meta = load(args.symbol)
    if rates is None or args.refresh:
        print(f"Downloading {args.symbol} ({args.days} days)...")
        meta = download(args.symbol, args.days)
        rates, meta = load(args.symbol)
    else:
        print(f"Using cached bars from {meta['downloaded']} "
              f"(--refresh to re-download)")

    if args.bars_only:
        return
    if "M1" not in rates:
        print("ERROR: no M1 bars. Run with --refresh.")
        sys.exit(1)

    import logging
    logging.disable(logging.WARNING)   # the engine is chatty per decision

    from core.market_data import HistoricalFeed
    from core.engine_replay import replay_engine
    from core.replay_metrics import full_report, format_report
    from core.replay_forensics import forensic_report, format_forensics

    # Auto-derivation is a guess and it was WRONG for the first real run:
    # a broker quoting XAGUSD at digits=3 / point=0.001 got pip_size 0.01,
    # ten times the 0.001 the live engine uses. Every pip figure -- stop
    # distance, spread, R:R -- came out by a factor of ten, and the report
    # looked plausible rather than broken.
    #
    # So --pip-size now overrides, and a mismatch against the live value is
    # loud rather than silent.
    if args.pip_size:
        pip_size = args.pip_size
    else:
        pip_size = float(meta.get("point", 0.001))
        if meta.get("digits", 3) in (3, 5):
            pip_size = pip_size * 10
        print(f"  NOTE: pip_size auto-derived as {pip_size} from digits="
              f"{meta.get('digits')} point={meta.get('point')}.")
        print(f"        If your live payload reports a different pip_size, "
              f"re-run with --pip-size <value>. Every pip figure depends on it.")

    feed = HistoricalFeed(
        rates, symbol=args.symbol, base_timeframe="M1",
        pip_size=pip_size, spread_pips=args.spread,
        balance=meta.get("balance", 10000.0),
        leverage=meta.get("leverage", 200),
        info_kwargs={
            "digits": meta.get("digits", 3),
            "point": meta.get("point", 0.001),
            "trade_contract_size": meta.get("trade_contract_size", 5000.0),
            "trade_tick_value": meta.get("trade_tick_value", 5.0),
            "trade_tick_size": meta.get("trade_tick_size", 0.001),
            "volume_min": meta.get("volume_min", 0.01),
            "volume_step": meta.get("volume_step", 0.01),
        },
    )

    total = len(feed.timestamps(warmup_bars=args.warmup, step=args.step))
    print(f"\n{args.symbol}: {total} decisions to analyse "
          f"(every {args.step} bars, pip_size={pip_size})")
    print("Roughly 30 decisions/sec. Ctrl-C is safe -- partial results still save.\n")

    done = [0]

    def progress(_rec):
        done[0] += 1
        if done[0] % 100 == 0:
            pct = done[0] / max(1, min(total, args.limit or total)) * 100
            print(f"  {done[0]} analysed ({pct:.0f}%)", end="\r", flush=True)

    records = []
    try:
        records = replay_engine(
            feed, symbol=args.symbol, warmup_bars=args.warmup,
            step=args.step, stop_after=args.limit, on_decision=progress,
            max_holding_bars=args.max_holding,
        )
    except KeyboardInterrupt:
        print("\nInterrupted -- saving what was analysed.")
    except RuntimeError as e:
        print(f"\nSTOPPED: {e}")
        sys.exit(1)

    if not records:
        print("No decisions produced. Try a larger --days or a smaller --warmup.")
        sys.exit(1)

    report = full_report(records)
    forensics = forensic_report(records, feed)
    text = format_report(report) + "\n" + format_forensics(forensics)

    stats = records[0].get("_stats", {})
    header = [
        "=" * 62,
        f"REPLAY  {args.symbol}",
        "=" * 62,
        f"  bars from:     {meta['bars']['M1']['first']}",
        f"  bars to:       {meta['bars']['M1']['last']}",
        f"  timeframes:    {', '.join(sorted(rates))}",
        f"  pip_size:      {pip_size}",
        f"  spread:        {args.spread if args.spread else 'per-bar from data'}",
        f"  max holding:   {args.max_holding} bars",
        f"  step:          every {args.step} bars",
        f"  analysed:      {stats.get('analysed')}",
        f"  errors:        {stats.get('errors')}",
        f"  lookahead:     {stats.get('lookahead_violations')}",
        "",
    ]
    text = "\n".join(header) + text

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    slim = []
    for r in records:
        slim.append({k: v for k, v in r.items() if k != "_stats"})
    with open(RECORDS_PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stats": stats,
                   "report": report, "forensics": forensics,
                   "records": slim}, f, indent=2, default=str)

    print("\n" + text)
    print(f"\nWrote {REPORT_PATH}")
    print(f"      {RECORDS_PATH}")


if __name__ == "__main__":
    main()