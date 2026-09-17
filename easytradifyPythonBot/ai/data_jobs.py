# ai/data_jobs.py
"""
The background jobs of strategic_plan_v5_live_data.md. Places no orders.

Every CYCLE_SECONDS:
  * results for due decisions        ai/decision_outcomes.fill()

Skipped setups are not labelled separately: every one of them is also in the
decision log with its whole snapshot, and ai/skipped_setup_outcomes caches 8
hours of ticks to disk PER setup, which at one setup per symbol per minute
fills a disk within days. decision_outcomes reads ticks once per symbol window.

Once per UTC day (first cycle after DAILY_AT_UTC):
  * MT5 vs MongoDB reconciliation    ai/data_reconciliation.reconcile()
  * MT5 history import               ai/data_reconciliation.import_history()

Each job is isolated: one failing never stops the others or the loop. A
heartbeat with the last result of every job is written to
logs/data_jobs_heartbeat.json.

    python -m ai.data_jobs            # loop (scripts/start_services.bat starts it)
    python -m ai.data_jobs --once     # one cycle, daily jobs included
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

CYCLE_SECONDS = 900
DAILY_AT_UTC = 0          # hour
HEARTBEAT = Path(__file__).resolve().parents[1] / "logs" / "data_jobs_heartbeat.json"


def _run(name: str, job: Callable[[], Any], report: Dict[str, Any]) -> None:
    started = time.time()
    try:
        result = job()
        report[name] = {"ok": True, "seconds": round(time.time() - started, 1), "result": result}
    except Exception as exc:
        report[name] = {"ok": False, "seconds": round(time.time() - started, 1),
                        "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-800:]}
        logger.warning(f"[DATA JOBS] {name} failed: {exc}")


def cycle(daily: bool) -> Dict[str, Any]:
    from ai import data_reconciliation, decision_outcomes

    report: Dict[str, Any] = {"at": datetime.now(timezone.utc).isoformat(), "daily": daily}
    _run("decision_outcomes", lambda: decision_outcomes.fill(), report)
    if daily:
        _run("reconciliation", lambda: {k: v for k, v in data_reconciliation.reconcile(days=7).items()
                                        if k != "tickets"}, report)
        _run("history_import", lambda: data_reconciliation.import_history(days=90), report)
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    import core.console_safe  # noqa: F401  UTF-8 output; a click in the window cannot freeze the loop
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

    last_daily = None
    while True:
        now = datetime.now(timezone.utc)
        daily = args.once or (last_daily != now.date() and now.hour >= DAILY_AT_UTC)
        report = cycle(daily)
        if daily:
            last_daily = now.date()
        summary = {k: (v.get("result") if v.get("ok") else v.get("error"))
                   for k, v in report.items() if isinstance(v, dict)}
        print(json.dumps({"at": report["at"], **summary}, default=str), flush=True)
        if args.once:
            break
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
