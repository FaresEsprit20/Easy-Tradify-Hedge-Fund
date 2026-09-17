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
from datetime import datetime, timedelta

# This module lives inside core/, so the PROJECT ROOT is its parent's
# parent. Putting that on sys.path is what lets `from core.market_data
# import ...` work when the file is executed directly as
# `python core/run_replay.py` -- without it Python only has core/ itself
# on the path and the package is invisible to its own contents.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Before anything prints. The report contains emoji, and on a cp1252
# console `print(report)` raised UnicodeEncodeError at the very last
# line of every run -- after the analysis was finished and both output
# files were already written. Every replay in this project ended in a
# traceback for a reason that had nothing to do with the replay.
import core.console_safe  # noqa: E402,F401

# Cache and outputs go in the project root, not in core/. Downloaded
# bars are data, not source, and burying a few hundred MB of .npy files
# inside a package directory is a good way to commit them by accident.
CACHE_DIR = os.path.join(_PROJECT_ROOT, "replay_bars")
REPORT_PATH = os.path.join(_PROJECT_ROOT, "replay_report.txt")
RECORDS_PATH = os.path.join(_PROJECT_ROOT, "replay_records.json")

# Higher timeframes need history BEFORE the M1 walk starts, or they get
# dropped for having too few closed bars and the engine silently loses
# its H1/H4 context. These counts are deliberately generous.
# Bars per timeframe. These used to be FIXED CONSTANTS while only M1
# scaled with --days, which made every long run a lie: a 62-day pull
# fetched 89,280 M1 bars reaching back to June, but only 3,000 M15 bars
# reaching back five weeks. The ANALYSIS reads M15, so every decision
# before the M15 window simply produced no usable trade -- silently, with
# no error, and with the M1 bars sitting there looking like coverage.
#
# The symptom was subtle enough to survive a whole session: a "62-day"
# replay whose resolved trades all fell inside the same 30 days that had
# already been searched, so a run bought to obtain fresh data returned
# none and looked fine doing it.
#
# Now every timeframe is derived from --days, with the old constants kept
# as FLOORS so short runs behave exactly as before, and a generous
# multiplier because higher timeframes also need warm-up history BEFORE
# the walk starts.
_BARS_PER_DAY = {"M1": 1440, "M5": 288, "M15": 96, "M30": 48,
                 "H1": 24, "H4": 6, "D1": 1}
_TF_FLOOR = {"M5": 5000, "M15": 3000, "M30": 2000,
             "H1": 2000, "H4": 1000, "D1": 400}
# The terminal refuses requests past roughly this size (probed on
# IC Markets: 90,000 M1 bars served, 129,600 returned None).
_MAX_BARS = 90000
_WARMUP_FACTOR = 1.4


def bars_for(days: int) -> dict:
    """Bars to request per timeframe for a `days`-long replay."""
    out = {"M1": min(int(days * 1440), _MAX_BARS)}
    for tf, per_day in _BARS_PER_DAY.items():
        if tf == "M1":
            continue
        want = int(days * per_day * _WARMUP_FACTOR)
        out[tf] = min(max(want, _TF_FLOOR[tf]), _MAX_BARS)
    return out


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

    counts = bars_for(days)

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

    # ---- ticks -------------------------------------------------
    # The only real order flow this system has. analyze_micro_structure()
    # -- and through it the timing_confidence gate, which decided 0 of 65
    # candidates before this existed -- reads nothing else. Without a
    # cache the shim serves None and that gate is unmeasurable; with one
    # it is evaluated on the same tape a live decision would have seen.
    #
    # Large but not unreasonable: ~70k ticks/day on EURUSD, ~150k on
    # XAGUSD. Stored as one time-sorted array and memory-mapped at read
    # time, since a replay touches a few hundred rows per decision.
    try:
        tick_from = datetime.now() - timedelta(days=days)
        ticks = mt5.copy_ticks_range(symbol, tick_from, datetime.now(),
                                     mt5.COPY_TICKS_ALL)
        if ticks is not None and len(ticks):
            tick_file = f"{symbol}_ticks.npy"
            np.save(os.path.join(CACHE_DIR, tick_file), ticks)
            t_first = datetime.utcfromtimestamp(int(ticks[0]["time"]))
            t_last = datetime.utcfromtimestamp(int(ticks[-1]["time"]))
            meta["ticks"] = {
                "count": int(len(ticks)), "file": tick_file,
                "first": t_first.isoformat(), "last": t_last.isoformat(),
            }
            print(f"  ticks: {len(ticks):>7}        {t_first:%Y-%m-%d} -> {t_last:%Y-%m-%d}")
        else:
            print(f"  ticks: NO DATA ({mt5.last_error()}) -- micro-structure "
                  f"will report unavailable, as before")
    except Exception as e:
        # Never fatal: bars alone reproduce every previous run exactly.
        print(f"  ticks: download failed ({e}) -- continuing with bars only")

    account = mt5.account_info()
    if account:
        meta["balance"] = float(account.balance)
        meta["leverage"] = int(account.leverage)

    # ---- REFUSE TO WRITE A CACHE WITH NO BASE TIMEFRAME ----------
    #
    # copy_rates_from_pos returns None -- not a short array -- when the
    # request is larger than the terminal will serve. On this broker
    # anything past ~90,000 M1 bars fails that way, so asking for 90 days
    # silently produced a meta.json with every timeframe EXCEPT M1.
    #
    # The old code wrote that file anyway. The .npy bars from the
    # previous good download were still on disk, but load() reads the
    # timeframe list from meta, so a perfectly intact 30-day cache became
    # unloadable -- and the failure surfaced much later as "ERROR: no M1
    # bars", pointing at the replay rather than at the download that
    # broke it.
    #
    # A refresh that cannot produce the base timeframe has failed. Leave
    # whatever was there alone and say so.
    if "M1" not in meta["bars"]:
        print(f"  ABORTED: no M1 bars returned for {days} days -- the terminal "
              f"refused the request (it serves ~90,000 M1 bars maximum).")
        print(f"  The existing cache has NOT been modified. Retry with fewer days.")
        mt5.shutdown()
        return None

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
    # Default None, not 5, so an explicitly-passed --step can be told
    # apart from the default. The timeframe auto-scaling below must
    # override the default and must NOT override a deliberate choice.
    ap.add_argument("--step", type=int, default=None,
                    help="analyse every Nth M1 bar (default: one analysis-"
                         "timeframe bar); 1 is every bar (slow)")
    ap.add_argument("--warmup", type=int, default=800,
                    help="M1 bars to skip before the first decision")
    ap.add_argument("--spread", type=float, default=None,
                    help="fixed spread in pips; default uses each bar's own")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N decisions (for a quick smoke test)")
    ap.add_argument("--trade-size", type=float, default=200.0,
                    help="fixed_trade_size_usd, as your live config sets it")
    ap.add_argument("--risk-per-trade", type=float, default=0.1,
                    help="RISK FRACTION, not percent. calculate_lot_proper() "
                         "computes target_risk = trade_size * risk_per_trade, "
                         "so 0.1 means 10%%. Passing 10 asks for 10x the "
                         "account per trade and drives the stop to MAX_SL_PIPS.")
    ap.add_argument("--verbose", action="store_true",
                    help="let the engine log to the console (very slow)")
    ap.add_argument("--diagnose", action="store_true",
                    help="analyse ONE decision and dump the sizing inputs, then exit")
    ap.add_argument("--pip-size", type=float, default=None,
                    help="override pip size; use the value your live payload reports")
    ap.add_argument("--max-holding", type=int, default=500,
                    help="bars to wait for stop or target before UNRESOLVED")
    ap.add_argument("--peers", default="",
                    help="comma-separated correlated symbols to serve alongside "
                         "the primary (e.g. GBPUSD,USDCHF,EURJPY). Needed for "
                         "the GNN: it requests ticks for correlated instruments "
                         "to build its graph, and without them every peer "
                         "request returns None.")
    # The analysis timeframe is NOT the same as the replay's stepping
    # timeframe. Decisions are still evaluated bar-by-bar on M1 so fills
    # stay precise; this only changes which timeframe the ANALYSIS reads
    # as its primary series.
    #
    # It matters more than it looks. Spread is a fixed cost per trade,
    # but the move you are trying to catch scales with the timeframe, so
    # cost-as-a-fraction-of-signal falls roughly 4-6x from M1 to M15:
    #
    #             M1      M5     M15     H1
    #   EURUSD   9.3%    4.3%    2.5%   1.2%
    #   GBPUSD  22.9%    5.7%    3.6%   1.9%
    #   XAGUSD  37.4%   17.6%    8.1%   4.1%
    #   USDCHF  52.6%   13.2%    8.7%   4.2%
    #
    # On M1, USDCHF needs price to travel 3.16 ATRs to reach a 1:2
    # target with the stop on its 3x-spread floor. That is a bet on an
    # unusual move on every single trade, independent of any signal.
    ap.add_argument("--timeframe", default="M1",
                    choices=["M1", "M5", "M15", "M30", "H1", "H4"],
                    help="timeframe the ANALYSIS reads (default M1); "
                         "outcomes are still evaluated on M1 bars")
    ap.add_argument("--refresh", action="store_true", help="re-download bars")
    ap.add_argument("--bars-only", action="store_true", help="download and exit")
    # Both outputs are fixed filenames in the project root, so two
    # replays running at once silently overwrite each other's records --
    # and the damage is invisible, because each run still writes a
    # complete, well-formed file. This makes the destination explicit so
    # a per-symbol sweep can run its symbols in PARALLEL (four symbols
    # serially is ~2 hours of wall clock; four at once is ~30 minutes)
    # instead of being serialized by a naming collision.
    # Which measurable vetoes to run-but-not-enforce. The replay is the
    # only place this can be answered honestly: the vetoes SHORT-CIRCUIT,
    # so estimating the effect of disabling one from a previous run's
    # ledger is an upper bound -- checks that never ran because an
    # earlier veto fired are absent from it, and one of them may block
    # the same trade anyway. Actually re-running is the only way to see
    # what a disabled veto really releases.
    ap.add_argument("--disable-vetos", default="",
                    help="comma-separated veto names to record but not enforce, "
                         "e.g. low_volume. Tail-protection vetoes (news, session, "
                         "weekend, holiday) are not disableable.")
    # Stops sit on the SL_MIN_ATR_MULTIPLE floor for essentially every
    # trade (median risk_pips equals median atr_pips to the decimal on
    # all four symbols), so this multiple IS the stop distance in
    # practice, not a rarely-touched floor.
    #
    # It is the one parameter that can move win rate and expectancy the
    # SAME way: a wider stop is hit less often (win rate up) and dilutes
    # the fixed spread cost across more risk (expectancy up). At 1.0 x
    # ATR a 1.5-pip spread is ~25% of total risk on these symbols, which
    # is a tax no edge can carry.
    #
    # It cannot be evaluated from existing records -- MFE/MAE are only
    # recorded up to the original exit, so a wider stop has no data past
    # the bar where the old one fired. It has to be re-run.
    ap.add_argument("--sl-atr", type=float, default=None,
                    help="override SL_MIN_ATR_MULTIPLE (default 1.0). Widens the "
                         "stop floor; the whole R scale moves with it.")
    ap.add_argument("--out-prefix", default=None,
                    help="write <prefix>_report.txt and <prefix>_records.json "
                         "instead of the shared replay_report.txt / "
                         "replay_records.json; required to run replays in parallel")
    args = ap.parse_args()

    if args.sl_atr:
        # Patch BOTH the config module and asset_analysis's own binding:
        # asset_analysis does `from ... import SL_MIN_ATR_MULTIPLE` at
        # import time, so rebinding the config alone leaves the engine
        # still holding the old value and the run silently does nothing.
        import core.asset_analysis_config as _cfg
        import core.asset_analysis as _aa
        _cfg.SL_MIN_ATR_MULTIPLE = args.sl_atr
        if hasattr(_aa, "SL_MIN_ATR_MULTIPLE"):
            _aa.SL_MIN_ATR_MULTIPLE = args.sl_atr
        print(f"  SL_MIN_ATR_MULTIPLE overridden: {args.sl_atr} x ATR")

    disabled = {v.strip() for v in (args.disable_vetos or "").split(",") if v.strip()}
    if disabled:
        from core.veto_engine import reset_veto_engine
        reset_veto_engine({"disabled_vetos": disabled})
        print(f"  vetoes recorded but NOT enforced: {', '.join(sorted(disabled))}")

    report_path, records_path = REPORT_PATH, RECORDS_PATH
    if args.out_prefix:
        report_path = os.path.join(_PROJECT_ROOT, f"{args.out_prefix}_report.txt")
        records_path = os.path.join(_PROJECT_ROOT, f"{args.out_prefix}_records.json")

    rates, meta = load(args.symbol)
    if rates is None or args.refresh:
        print(f"Downloading {args.symbol} ({args.days} days)...")
        fresh = download(args.symbol, args.days)
        if fresh is None and rates is None:
            print("ERROR: download failed and no usable cache exists.")
            sys.exit(1)
        rates, meta = load(args.symbol)
    else:
        print(f"Using cached bars from {meta['downloaded']} "
              f"(--refresh to re-download)")

    if args.bars_only:
        return
    if "M1" not in rates:
        print("ERROR: no M1 bars. Run with --refresh.")
        sys.exit(1)

    # ---- THE ANALYSIS TIMEFRAME MUST SPAN THE M1 WALK ------------
    #
    # Decisions are stepped on M1 but ANALYSED on --timeframe. If that
    # timeframe's history starts later than M1's, every decision before
    # it silently produces no usable trade: no error, no warning, just a
    # replay whose early half quietly evaporates.
    #
    # That is not hypothetical. With the old fixed TF_BARS a 62-day pull
    # fetched M1 back to June 10 and M15 only back to July 23, so a run
    # made specifically to obtain six weeks of fresh data returned none
    # of it -- and looked entirely healthy while doing so. The wasted
    # work was only noticed because a pre-registered holdout came back
    # with zero trades and had to be explained.
    #
    # Cheap to check, and the check is loud.
    _tf = args.timeframe.upper()
    if _tf != "M1" and _tf in meta.get("bars", {}):
        m1_first = meta["bars"]["M1"]["first"]
        tf_first = meta["bars"][_tf]["first"]
        if tf_first > m1_first:
            print(f"ERROR: {_tf} history starts {tf_first[:10]} but the M1 walk "
                  f"starts {m1_first[:10]}.")
            print(f"       Every decision before {tf_first[:10]} would be analysed "
                  f"with no {_tf} data and silently produce nothing.")
            print(f"       Re-download: python -m core.run_replay --symbol "
                  f"{args.symbol} --days {args.days} --refresh --bars-only")
            sys.exit(1)

    import logging
    # logging.disable(WARNING) suppresses WARNING and BELOW -- ERROR still
    # prints. The engine logs a coherence ERROR per violating decision, and
    # on a real run that is thousands of lines to the console. Console I/O
    # then dominates the runtime: a 1,856-decision replay that should take
    # a minute instead crawls.
    #
    # The violations still reach the report (section 7 counts them and
    # scores whether they predict losses) -- they are silenced on stdout,
    # not discarded.
    logging.disable(logging.CRITICAL)
    logging.getLogger().setLevel(logging.CRITICAL)
    for name in list(logging.root.manager.loggerDict):
        lg = logging.getLogger(name)
        lg.setLevel(logging.CRITICAL)
        lg.propagate = False
        for h in list(lg.handlers):
            lg.removeHandler(h)
    if not args.verbose:
        # Third-party imports install handlers at import time, after the
        # loop above. This catches anything that appears later.
        logging.basicConfig(level=logging.CRITICAL, force=True)

    from core.market_data import HistoricalFeed, TickFeed, MultiSymbolFeed
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

    # Tick history, when the cache has it. Absent, the shim serves None
    # for copy_ticks_from and micro-structure reports unavailable --
    # which is exactly how every run before tick caching behaved, so an
    # old cache still reproduces its original numbers.
    tick_feed = None

    # The append-only archive first (see core/tick_archive.py). The
    # per-symbol cache is OVERWRITTEN on every --refresh, so it only
    # ever holds MT5's ~1 week of retention; the archive is the union of
    # every download ever made. Whichever holds more tape wins, so this
    # is a strict improvement and never loses a run its existing data.
    try:
        from core.tick_archive import load as _load_archive, archive_path
        arch = _load_archive(args.symbol)
        if arch is not None and len(arch):
            tick_feed = TickFeed(arch, symbol=args.symbol)
            print(f"  ticks: {len(arch):,} from ARCHIVE "
                  f"({os.path.relpath(archive_path(args.symbol))})")
    except Exception as e:
        print(f"  ticks: archive unreadable ({e}) -- falling back to cache")
        tick_feed = None

    tick_meta = meta.get("ticks") or {}
    if tick_meta.get("file"):
        tick_path = os.path.join(CACHE_DIR, tick_meta["file"])
        cached = TickFeed.load(tick_path, symbol=args.symbol)
        if cached is not None and (tick_feed is None or len(cached) > len(tick_feed)):
            tick_feed = cached
        if tick_feed is not None:
            print(f"  ticks: {len(tick_feed):,} loaded -- micro-structure and the "
                  f"timing gate are LIVE (no replay bypass)")
    if tick_feed is None:
        print("  ticks: none cached -- micro-structure unavailable, timing gate "
              "bypassed in replay (--refresh to download ticks)")

    feed = HistoricalFeed(
        rates, symbol=args.symbol, base_timeframe="M1",
        tick_feed=tick_feed,
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

    # ---- correlated peers ----------------------------------------
    # The GNN asks MT5 about OTHER instruments to build its correlation
    # graph. Until the shim became symbol-aware those requests silently
    # returned the PRIMARY symbol's tick, making every correlation 1.0 by
    # construction; now they return None unless a peer feed is supplied.
    # This is what supplies them.
    peer_names = [p.strip().upper() for p in (args.peers or "").split(",") if p.strip()]
    if peer_names:
        peer_feeds = {}
        for pname in peer_names:
            p_rates, p_meta = load(pname)
            if not p_rates:
                print(f"  peer {pname}: NO CACHED BARS -- run with "
                      f"--symbol {pname} --bars-only first (skipped)")
                continue
            p_pip = float(p_meta.get("point", 0.001))
            if p_meta.get("digits", 3) in (3, 5):
                p_pip *= 10
            peer_feeds[pname] = HistoricalFeed(
                p_rates, symbol=pname, base_timeframe="M1", pip_size=p_pip,
                balance=p_meta.get("balance", 10000.0),
                leverage=p_meta.get("leverage", 200),
                info_kwargs={"digits": p_meta.get("digits", 3),
                             "point": p_meta.get("point", 0.001)},
            )
            print(f"  peer {pname}: {len(p_rates.get('M1', [])):,} M1 bars")
        if peer_feeds:
            feed = MultiSymbolFeed(feed, peer_feeds)
            print(f"  cross-asset: {len(peer_feeds)} peer(s) served -- GNN can "
                  f"build a real correlation graph")

    if args.diagnose:
        # One decision, everything printed. Position sizing depends on
        # symbol properties the shim has to synthesise, and when those are
        # wrong the failure is silent: the stop falls back to a cap and the
        # report shows an excellent win rate on an impossible trade. This
        # makes the inputs visible before any of that can happen.
        from core.mt5_shim import replay_context, ShimStats
        from core.engine_replay import _capture
        from core.asset_analysis import analyze_institutional_signal

        ts = feed.timestamps(warmup_bars=args.warmup, step=args.step)
        if not ts:
            print("No decision timestamps -- lower --warmup or pull more days.")
            sys.exit(1)
        md = feed.at(ts[0])
        if md is None:
            print("Feed returned no data for the first timestamp.")
            sys.exit(1)

        print("=" * 62)
        print("DIAGNOSE -- symbol properties the shim is serving")
        print("=" * 62)
        for k in ("digits", "point", "trade_contract_size", "trade_tick_value",
                  "trade_tick_size", "volume_min", "volume_step"):
            print(f"  {k:<24} {getattr(md.info, k, None)}")
        print(f"  {'balance':<24} {md.account.balance}")
        print(f"  {'leverage':<24} {md.account.leverage}")
        print(f"  {'pip_size (feed)':<24} {feed.pip_size}")
        print(f"  {'target risk (USD)':<24} "
              f"{args.trade_size * args.risk_per_trade:.2f}   "
              f"<- compare with risk_usd in your live payload")
        print(f"  {'bid / ask':<24} {md.tick.bid:.5f} / {md.tick.ask:.5f}")
        print(f"  {'bars per timeframe':<24} "
              f"{ {k: len(v) for k, v in md.multi_tf_rates.items()} }")
        thin = (feed.stats or {}).get("thin_timeframes")
        if thin:
            print(f"  DROPPED (too few closed bars): {thin}")

        shim = ShimStats()
        with replay_context(md, stats=shim):
            res = analyze_institutional_signal(
                symbol=args.symbol, order_type="AUTO",
                fixed_trade_size_usd=args.trade_size,
                risk_per_trade=args.risk_per_trade,
                leverage=md.account.leverage, timeframe=args.timeframe,
                market_data=md)
        cap = _capture(res)
        print()
        print("  sizing produced by the engine:")
        for k in ("lot_size", "sl_pips", "tp_pips", "rr_ratio", "rr_valid",
                  "atr_pips", "spread_pips", "probability", "h1_trend"):
            print(f"    {k:<20} {cap.get(k)}")
        print()
        print("  COMPARE sl_pips against your live payload. If it reads 1000.0")
        print("  it hit MAX_SL_PIPS and every downstream number is invalid.")
        print(f"  shim calls: {shim.as_dict()}")
        if not res.get("success"):
            print(f"  analysis error: {res.get('error')}")
        return

    # ---- step vs analysis timeframe -----------------------------
    # The step is counted in BASE (M1) bars, but the analysis reads
    # `--timeframe`. Stepping 5 M1 bars while analysing M15 means
    # consecutive decisions share two thirds of the same M15 bar: they
    # are near-duplicates, not independent observations.
    #
    # That is not a cosmetic concern. It inflates every correlation and
    # every significance test in the forensics, because the effective
    # sample is a fraction of the nominal one. On the first real M15
    # run it produced correlations 3-4x larger than the M1 run's
    # (order_flow -0.143, trend_cascade -0.140) -- and all of them
    # failed the invariance splits, which is what an overlap artifact
    # looks like.
    #
    # One analysis bar per decision is the honest default. It is only
    # raised, never lowered, so an explicit --step larger than the
    # timeframe is respected.
    _TF_BARS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}
    _need = _TF_BARS.get(args.timeframe.upper(), 1)
    if args.step is None:
        args.step = max(5, _need) if _need > 1 else 5
        if _need > 1:
            print(f"  step: {args.step} M1 bars = one {args.timeframe} bar "
                  f"(decisions do not overlap)")
    elif args.step < _need:
        # Explicit and overlapping: respected, but never silently. The
        # forensics that read these records cannot tell overlapping rows
        # from independent ones, so the warning has to travel with the run.
        _ov = 100.0 * (1.0 - args.step / _need)
        print(f"  step: WARNING -- --step {args.step} with --timeframe "
              f"{args.timeframe} ({_need} M1 bars per analysis bar)")
        print(f"        consecutive decisions overlap {_ov:.0f}%; correlations "
              f"and p-values in the forensics will be OVERSTATED because the")
        print(f"        effective sample is far below the nominal one. Use "
              f"--step {_need} for independent decisions.")

    # AFTER the step is resolved: computed before it, `total` used the
    # unresolved default (None -> every bar) and the progress readout
    # divided by a denominator 15x too large.
    total = len(feed.timestamps(warmup_bars=args.warmup, step=args.step))
    print(f"\n{args.symbol}: {total} decisions to analyse "
          f"(every {args.step} bars, pip_size={pip_size})")
    est = total if not args.limit else min(total, args.limit)
    print(f"Roughly 10 decisions/sec -- about {est / 10 / 60:.0f} min for this run.")
    print("Ctrl-C is safe: partial results are still written.\n")

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
            fixed_trade_size_usd=args.trade_size,
            risk_per_trade=args.risk_per_trade,
            step=args.step, stop_after=args.limit, on_decision=progress,
            max_holding_bars=args.max_holding, timeframe=args.timeframe,
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
        f"  trade size:    {args.trade_size} USD",
        f"  risk fraction: {args.risk_per_trade}  "
        f"(target risk {args.trade_size * args.risk_per_trade:.2f} USD)",
        f"  step:          every {args.step} bars",
        f"  analysed:      {stats.get('analysed')}",
        f"  errors:        {stats.get('errors')}",
        f"  lookahead:     {stats.get('lookahead_violations')}",
        "",
    ]
    text = "\n".join(header) + text

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)

    slim = []
    for r in records:
        slim.append({k: v for k, v in r.items() if k != "_stats"})
    with open(records_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stats": stats,
                   "report": report, "forensics": forensics,
                   "records": slim}, f, indent=2, default=str)

    print("\n" + text)
    print(f"\nWrote {report_path}")
    print(f"      {records_path}")


if __name__ == "__main__":
    main()