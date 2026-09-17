"""
APPEND-ONLY TICK ARCHIVE
========================
FILE: core/tick_archive.py

MT5 retains roughly a week of tick history. Everything that reads real
order flow -- analyze_micro_structure(), and through it the
timing_confidence gate -- is therefore limited to whatever that window
happens to hold on the day you run.

Measured cost of that limit: on a 1856-decision XAGUSD replay, 942
decisions had no tape at all because the bars reached back further than
the ticks did. The one candidate factor the tick-backed half produced
(timing_confidence >= 85, +0.246R pooled) had 78 observations, which is
not enough to survive splitting -- it held on the period and direction
splits and then flipped on h1_trend at n~32 a cell. That question cannot
be settled by re-running. It can only be settled by having more tape,
which means keeping it before MT5 drops it.

run_replay's downloader OVERWRITES {symbol}_ticks.npy on every refresh,
so it cannot accumulate: each run trades older tape for newer. This
merges instead. Run it on any cadence shorter than MT5's retention and
coverage grows without bound; miss a fortnight and you get a gap rather
than a corruption.

    python -m core.tick_archive EURUSD XAGUSD
    python -m core.tick_archive --status

The archive is the union of every download ever made, de-duplicated and
time-sorted. Re-running immediately is a no-op, so it is safe to
schedule as often as you like.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tick_archive")

# How far back to ASK. The server returns what it has, so over-asking
# costs a slower download and nothing else -- while under-asking
# silently truncates history that cannot be recovered later.
#
# This was 10 on the assumption MT5 retains about a week. It does not:
# a --days 30 request returned a full month of ticks on all four
# instruments (1.47M on EURUSD, 3.45M on XAGUSD), and the archiver's
# own 10-day default was throwing two thirds of that away on every run.
# Retention is broker- and instrument-dependent, so ask generously.
DEFAULT_LOOKBACK_DAYS = 45


def archive_path(symbol: str) -> str:
    return os.path.join(ARCHIVE_DIR, f"{symbol.upper()}_ticks.npy")


def load(symbol: str, *, mmap: bool = True) -> Optional[np.ndarray]:
    """
    The archive for `symbol`, or None if there isn't one yet.

    mmap=True keeps the file on disk and pages it in, which is what a
    replay wants: it touches a few hundred rows per decision out of
    millions, and materialising 80MB per run to do that is waste.

    mmap=False for anything that will REPLACE this file afterwards. A
    memory map holds an open handle, and on Windows os.replace() onto a
    mapped file fails outright with PermissionError -- which is exactly
    how update() broke the first time it was asked to merge into an
    archive it had already read.
    """
    p = archive_path(symbol)
    if not os.path.exists(p):
        return None
    try:
        return np.load(p, mmap_mode="r" if mmap else None)
    except Exception:
        return None


def _dedupe_key(arr: np.ndarray) -> np.ndarray:
    """
    Identity of a tick, for de-duplication.

    time_msc when present: millisecond stamps are effectively unique per
    tick and are what MT5 itself orders by. Plain `time` is only
    second-resolution, and a liquid symbol prints many ticks inside one
    second -- de-duplicating on it would silently discard real data,
    which is worse than the duplicates it removes.

    Without time_msc, fall back to the whole row: two rows identical in
    every field are genuinely indistinguishable, so collapsing them
    loses nothing.
    """
    names = arr.dtype.names or ()
    if "time_msc" in names:
        return arr["time_msc"]
    return np.array([repr(tuple(row)) for row in arr])


def merge(old: Optional[np.ndarray], new: np.ndarray) -> np.ndarray:
    """Union of two tick arrays, de-duplicated and time-sorted."""
    if old is None or len(old) == 0:
        combined = np.asarray(new)
    elif len(new) == 0:
        combined = np.asarray(old)
    else:
        if old.dtype != new.dtype:
            # A broker or terminal upgrade can change the tick dtype.
            # Refusing is right: silently coercing would make the two
            # halves of the archive mean different things, and nothing
            # downstream would be able to tell which half a row was from.
            raise ValueError(
                f"tick dtype changed:\n  archive {old.dtype}\n  new     {new.dtype}\n"
                f"Move the old archive aside rather than mixing them.")
        combined = np.concatenate([np.asarray(old), np.asarray(new)])

    if len(combined) == 0:
        return combined
    _, keep = np.unique(_dedupe_key(combined), return_index=True)
    combined = combined[np.sort(keep)]
    return combined[np.argsort(combined["time"], kind="stable")]


def _span(arr: np.ndarray) -> str:
    if arr is None or len(arr) == 0:
        return "empty"
    f = datetime.fromtimestamp(int(arr["time"][0]), timezone.utc)
    l = datetime.fromtimestamp(int(arr["time"][-1]), timezone.utc)
    return f"{f:%Y-%m-%d} -> {l:%Y-%m-%d}  ({(l - f).days + 1}d)"


def update(symbol: str, *, days: int = DEFAULT_LOOKBACK_DAYS,
           verbose: bool = True) -> Dict[str, Any]:
    """
    Pull whatever MT5 still holds for `symbol` and merge it in.

    Returns a summary rather than raising on a download failure: this is
    meant to run unattended across several symbols, and one unavailable
    instrument must not stop the rest from being archived.
    """
    import MetaTrader5 as mt5

    symbol = symbol.upper()
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    # mmap=False: this function replaces the archive file below, and a
    # live memory map would block the replace on Windows.
    before = load(symbol, mmap=False)
    n_before = 0 if before is None else len(before)

    try:
        to = datetime.now()
        ticks = mt5.copy_ticks_range(symbol, to - timedelta(days=days), to,
                                     mt5.COPY_TICKS_ALL)
    except Exception as e:
        if verbose:
            print(f"  {symbol:<10} download failed: {e}")
        return {"symbol": symbol, "ok": False, "error": str(e),
                "archived": n_before}

    if ticks is None or len(ticks) == 0:
        err = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
        if verbose:
            print(f"  {symbol:<10} no ticks returned ({err}); archive unchanged "
                  f"at {n_before}")
        return {"symbol": symbol, "ok": False, "error": str(err),
                "archived": n_before}

    try:
        merged = merge(before, ticks)
    except ValueError as e:
        if verbose:
            print(f"  {symbol:<10} REFUSED: {e}")
        return {"symbol": symbol, "ok": False, "error": str(e),
                "archived": n_before}

    # Write to a temp file and replace, so an interrupted run cannot
    # leave a truncated archive where a good one used to be.
    p = archive_path(symbol)
    tmp = p + ".tmp.npy"
    np.save(tmp, merged)
    try:
        os.replace(tmp, p)
    except PermissionError as e:
        # Something else holds the file open -- a concurrent replay
        # mmap'ing it, or an antivirus scan. Leave the existing archive
        # intact and say so; a half-written archive is worse than a
        # skipped update, because nothing downstream would notice.
        try:
            os.remove(tmp)
        except OSError:
            pass
        if verbose:
            print(f"  {symbol:<10} REFUSED: archive is open elsewhere ({e.strerror}); "
                  f"left unchanged at {n_before}")
        return {"symbol": symbol, "ok": False, "error": f"locked: {e}",
                "archived": n_before}

    added = len(merged) - n_before
    if verbose:
        print(f"  {symbol:<10} +{added:<8} now {len(merged):<10} {_span(merged)}")
    return {"symbol": symbol, "ok": True, "added": added,
            "archived": len(merged), "downloaded": len(ticks)}


def status(symbols: Optional[List[str]] = None) -> None:
    if not os.path.isdir(ARCHIVE_DIR):
        print(f"No archive yet at {ARCHIVE_DIR}")
        return
    names = symbols or sorted(
        f[:-10] for f in os.listdir(ARCHIVE_DIR) if f.endswith("_ticks.npy"))
    if not names:
        print(f"No archive yet at {ARCHIVE_DIR}")
        return
    print(f"{'symbol':<12}{'ticks':>12}   coverage")
    print("-" * 58)
    for s in names:
        a = load(s)
        if a is None:
            print(f"{s:<12}{'-':>12}   (unreadable)")
            continue
        mb = os.path.getsize(archive_path(s)) / 1e6
        print(f"{s:<12}{len(a):>12}   {_span(a)}   {mb:.0f}MB")


def main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    days = DEFAULT_LOOKBACK_DAYS
    for a in argv:
        if a.startswith("--days="):
            try:
                days = int(a.split("=", 1)[1])
            except ValueError:
                print(f"bad --days: {a}")
                return 2
    if "--status" in argv:
        status(args or None)
        return 0
    if not args:
        print(__doc__.strip().split("\n\n")[0])
        print("\nusage: python -m core.tick_archive SYMBOL [SYMBOL ...]")
        print("       python -m core.tick_archive --status")
        return 2

    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 initialize() failed: {mt5.last_error()}")
        return 1
    try:
        print(f"Archiving to {ARCHIVE_DIR}")
        results = [update(s, days=days) for s in args]
    finally:
        mt5.shutdown()

    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} archived")
    # Non-zero only if EVERY symbol failed. A partial success on a
    # scheduled run is worth keeping, and alerting on it would train
    # whoever reads the log to ignore it.
    return 1 if failed and len(failed) == len(results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
