# ============================================================
# TRADE DATA MONITOR -- AUTOMATED, CONTINUOUS, UNATTENDED
# ============================================================
# FILE: core/mongo/trade_data_monitor.py
#
# Watches what the live system is actually WRITING and reports every way the
# record can be wrong, without anyone having to look at a document and notice.
#
# WHY THIS EXISTS
# ---------------
# Every serious data defect in this project was silent, and several made the
# system look healthier than it was. All of these were live, all were found by
# hand, and every one of them is checked here now:
#
#   * price_evolution held 1-2 points on trades running 3.3 hours (~180
#     expected). Three independent causes -- an encoder crash on a None field,
#     a throttle shared across all positions, and the 1 MiB document limit --
#     and the monitor logged healthy throughout.
#   * analysis_at_open was stored triple-nested and compressed, so no model
#     could reach final_verdict. The field was present and looked fine.
#   * analysis_at_close stored EMPTY timeframes because the writer looked for
#     three key spellings and the producer used a fourth.
#   * close_reason was the literal "SL_TP_HIT" on every close, merging "hit
#     target" with "hit stop".
#   * a trade whose top-level direction was BUY carried close_data.order_type
#     SELL.
#   * duration_seconds was 0 on trades that ran for hours.
#
# The rule this module is built on: a check that cannot fail is worthless, so
# every check here is written against a REAL defect that actually occurred and
# would have caught it.
#
# Severity is meaningful, not decorative:
#   CRITICAL  data is being lost right now, or is wrong in a way that would
#             corrupt training. Act immediately.
#   WARNING   degraded or trending toward failure.
#   INFO      worth knowing, not urgent.
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

MONITOR_VERSION = "1.0"

CRITICAL, WARNING, INFO = "CRITICAL", "WARNING", "INFO"

# One price point per minute is the configured cadence
# (MultiSymbolMonitor.PRICE_UPDATE_INTERVAL). A trade producing far fewer than
# its age implies is losing its forward walk.
EXPECTED_SECONDS_PER_POINT = 60
POINT_SHORTFALL_RATIO = 0.5      # under half of expected -> CRITICAL
DOCUMENT_WARN_RATIO = 0.75       # of MongoDB's 16 MB ceiling


def _finding(severity: str, code: str, message: str,
             trade_id: Optional[str] = None,
             evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"severity": severity, "code": code, "message": message,
            "trade_id": trade_id, "evidence": evidence or {}}


def _age_seconds(trade: Mapping[str, Any]) -> Optional[float]:
    opened = trade.get("opened_at")
    if not opened:
        return None
    try:
        if isinstance(opened, datetime):
            start = opened
        else:
            start = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = trade.get("closed_at")
        if end:
            stop = (end if isinstance(end, datetime)
                    else datetime.fromisoformat(str(end).replace("Z", "+00:00")))
            if stop.tzinfo is None:
                stop = stop.replace(tzinfo=timezone.utc)
        else:
            stop = datetime.now(timezone.utc)
        return max(0.0, (stop - start).total_seconds())
    except Exception:
        return None


# ============================================================
# PER-TRADE CHECKS
# ============================================================

def inspect_trade(trade: Mapping[str, Any],
                  document_bytes: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every defect detectable in one stored trade."""
    findings: List[Dict[str, Any]] = []
    trade_id = trade.get("trade_id")
    status = trade.get("status")
    points = trade.get("price_evolution") or []
    age = _age_seconds(trade)

    # ---- the forward walk ------------------------------------------------
    if age and age > 3 * EXPECTED_SECONDS_PER_POINT:
        expected = int(age // EXPECTED_SECONDS_PER_POINT)
        if expected and len(points) < expected * POINT_SHORTFALL_RATIO:
            findings.append(_finding(
                CRITICAL, "price_evolution_starved",
                f"{len(points)} price points over {int(age)}s, expected "
                f"~{expected}. The forward walk is being lost as it happens.",
                trade_id, {"points": len(points), "expected": expected,
                           "age_seconds": int(age)}))

    if status == "CLOSED" and not points:
        findings.append(_finding(
            CRITICAL, "price_evolution_empty",
            "closed trade has NO price evolution -- the forward walk this "
            "trade produced is gone and cannot be recovered", trade_id))

    # ---- the analysis the models actually read ---------------------------
    analysis = trade.get("analysis_at_open") or {}
    if not analysis:
        findings.append(_finding(
            CRITICAL, "analysis_at_open_missing",
            "no analysis_at_open -- the decision snapshot was never stored, "
            "so nothing can explain why this trade was taken", trade_id))
    else:
        reachable = _verdict_reachable(analysis)
        if not reachable:
            findings.append(_finding(
                CRITICAL, "analysis_at_open_unreachable",
                "analysis_at_open exists but final_verdict cannot be reached "
                "from it -- the envelope is not being flattened, so every "
                "model reads an empty snapshot",
                trade_id, {"keys": sorted(analysis.keys())[:12]}))
        elif not _ledger_reachable(analysis):
            findings.append(_finding(
                WARNING, "probability_ledger_missing",
                "final_verdict has no probability_ledger -- component "
                "attribution is impossible for this trade", trade_id))

    if status == "CLOSED":
        at_close = trade.get("analysis_at_close") or {}
        if not at_close:
            findings.append(_finding(
                WARNING, "analysis_at_close_missing",
                "closed trade has no analysis_at_close", trade_id))
        elif not any(at_close.get(k) for k in
                     ("m1_analysis_raw", "final_verdict", "full_analysis_raw")):
            findings.append(_finding(
                CRITICAL, "analysis_at_close_empty",
                "analysis_at_close is present but carries no analysis -- the "
                "exact defect a key-spelling mismatch produced before",
                trade_id, {"keys": sorted(at_close.keys())[:12]}))

    # ---- the outcome label ----------------------------------------------
    close = trade.get("close_data") or {}
    if status == "CLOSED":
        reason = close.get("close_reason")
        if reason in (None, "", "UNKNOWN"):
            findings.append(_finding(
                WARNING, "close_reason_unknown",
                "close reason unresolved -- cannot tell target from stop",
                trade_id, {"close_reason": reason}))
        elif reason == "SL_TP_HIT":
            findings.append(_finding(
                CRITICAL, "close_reason_ambiguous",
                "close_reason is the ambiguous literal 'SL_TP_HIT', which "
                "merges a winner that hit target with a loser that hit stop",
                trade_id))

        if close.get("duration_seconds") in (0, None) and age and age > 60:
            findings.append(_finding(
                WARNING, "duration_zero",
                f"duration_seconds is {close.get('duration_seconds')!r} on a "
                f"trade that ran {int(age)}s", trade_id))

        order_type = close.get("order_type")
        direction = trade.get("direction")
        if order_type and direction and str(order_type).upper() != str(direction).upper():
            findings.append(_finding(
                CRITICAL, "direction_mismatch",
                f"trade direction is {direction} but close_data.order_type is "
                f"{order_type} -- one of them is wrong and both are used",
                trade_id, {"direction": direction, "order_type": order_type}))

    # ---- risk state ------------------------------------------------------
    if points:
        with_risk = sum(1 for p in points
                        if isinstance(p, dict) and p.get("risk_state"))
        if with_risk == 0:
            findings.append(_finding(
                WARNING, "risk_state_absent",
                "no price point records where the stop was, so a break-even "
                "or trailing move cannot be reconstructed", trade_id))

    # ---- size ------------------------------------------------------------
    if document_bytes:
        from .mongo_config import MONGO_MAX_DOCUMENT_BYTES
        ratio = document_bytes / MONGO_MAX_DOCUMENT_BYTES
        if ratio >= 1.0:
            findings.append(_finding(
                CRITICAL, "document_over_limit",
                f"document is {document_bytes} bytes, past the "
                f"{MONGO_MAX_DOCUMENT_BYTES}-byte ceiling -- further appends "
                f"will be rejected", trade_id, {"bytes": document_bytes}))
        elif ratio >= DOCUMENT_WARN_RATIO:
            findings.append(_finding(
                WARNING, "document_size_high",
                f"document is at {ratio:.0%} of the size limit",
                trade_id, {"bytes": document_bytes}))

    return findings


def _verdict_reachable(analysis: Mapping[str, Any]) -> bool:
    if analysis.get("final_verdict"):
        return True
    for value in analysis.values():
        if isinstance(value, Mapping) and value.get("final_verdict"):
            return True
    return False


def _ledger_reachable(analysis: Mapping[str, Any]) -> bool:
    verdict = analysis.get("final_verdict")
    if isinstance(verdict, Mapping) and verdict.get("probability_ledger"):
        return True
    for value in analysis.values():
        if isinstance(value, Mapping):
            inner = value.get("final_verdict")
            if isinstance(inner, Mapping) and inner.get("probability_ledger"):
                return True
    return False


# ============================================================
# COLLECTION-WIDE SCAN
# ============================================================

def scan(limit: int = 100, *, only_open: bool = False,
         since_hours: Optional[int] = None) -> Dict[str, Any]:
    """
    Inspect recent trades and report everything wrong with them.

    Designed to run unattended on a timer. The report is structured so a
    caller can act on it without a human reading prose: findings carry a
    machine-readable `code`, a severity, and the evidence behind the claim.
    """
    from core.mongo import get_trades_service

    service = get_trades_service()
    report: Dict[str, Any] = {
        "component": "trade_data_monitor",
        "version": MONITOR_VERSION,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "healthy": None,
        "trades_scanned": 0,
        "findings": [],
        "by_severity": {CRITICAL: 0, WARNING: 0, INFO: 0},
        "by_code": {},
    }

    if not service.is_healthy():
        report["healthy"] = False
        report["error"] = "trades database is unreachable"
        return report

    filters: Dict[str, Any] = {}
    if only_open:
        filters["status"] = "OPEN"
    opened_from = None
    if since_hours:
        opened_from = (datetime.now(timezone.utc)
                       - timedelta(hours=int(since_hours))).isoformat()

    try:
        trades = service.list_trades(
            page=1, page_size=min(int(limit or 100), 200),
            sort_by="opened_at", sort_dir="desc",
            filters=filters, opened_from=opened_from,
            include_heavy=True)["items"]
    except Exception as exc:
        report["healthy"] = False
        report["error"] = f"scan query failed: {exc}"
        return report

    for trade in trades:
        size = None
        try:
            size = service._document_size(trade)
        except Exception:
            pass
        for finding in inspect_trade(trade, document_bytes=size):
            report["findings"].append(finding)
            report["by_severity"][finding["severity"]] += 1
            report["by_code"][finding["code"]] = (
                report["by_code"].get(finding["code"], 0) + 1)

    report["trades_scanned"] = len(trades)
    # None, not True, when nothing was examined: an empty collection cannot
    # demonstrate that the pipeline works.
    report["healthy"] = (None if not trades
                         else report["by_severity"][CRITICAL] == 0)
    report["summary"] = _summarise(report)
    return report


def _summarise(report: Mapping[str, Any]) -> str:
    scanned = report.get("trades_scanned", 0)
    if not scanned:
        return "no trades examined; nothing was verified"
    counts = report.get("by_severity", {})
    if not report.get("findings"):
        return f"{scanned} trades scanned, no defects found"
    parts = [f"{counts.get(sev, 0)} {sev.lower()}"
             for sev in (CRITICAL, WARNING, INFO) if counts.get(sev)]
    worst = sorted(report["by_code"].items(), key=lambda kv: -kv[1])[:3]
    return (f"{scanned} trades scanned: {', '.join(parts)}. "
            f"Most common: {', '.join(f'{c} x{n}' for c, n in worst)}")


def get_status() -> Dict[str, Any]:
    """Cheap status without a full scan."""
    from core.mongo import get_trades_service
    service = get_trades_service()
    status: Dict[str, Any] = {"component": "trade_data_monitor",
                              "version": MONITOR_VERSION}
    try:
        status["healthy"] = service.is_healthy()
        if status["healthy"]:
            status["trades_open"] = service.count_trades(
                filters={"status": "OPEN"})
            status["trades_total"] = service.count_trades()
    except Exception as exc:
        status["healthy"] = False
        status["error"] = str(exc)
    return status


def self_check(trades: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """
    Prove the checks can FAIL.

    A monitor that returns "healthy" on garbage is indistinguishable from a
    stub. This feeds it a deliberately broken trade and requires that the
    known defects are detected, then feeds a clean one and requires silence.
    """
    broken = {
        "trade_id": "trade_selfcheck_bad",
        "status": "CLOSED",
        "direction": "BUY",
        "opened_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "price_evolution": [],
        "analysis_at_open": {},
        "close_data": {"close_reason": "SL_TP_HIT", "order_type": "SELL",
                       "duration_seconds": 0},
    }
    clean = {
        "trade_id": "trade_selfcheck_good",
        "status": "CLOSED",
        "direction": "BUY",
        "opened_at": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "price_evolution": [
            {"price": 1.1, "risk_state": {"sl": 1.09},
             "analysis": {"m1": {"final_verdict": {"probability_percent": 60}}}},
            {"price": 1.2, "risk_state": {"sl": 1.09},
             "analysis": {"m1": {"final_verdict": {"probability_percent": 61}}}},
            {"price": 1.3, "risk_state": {"sl": 1.09},
             "analysis": {"m1": {"final_verdict": {"probability_percent": 62}}}},
        ],
        "analysis_at_open": {"final_verdict": {"probability_percent": 60,
                                               "probability_ledger": [{"step": "pattern"}]}},
        "analysis_at_close": {"m1_analysis_raw": {"final_verdict": {}}},
        "close_data": {"close_reason": "TAKE_PROFIT", "order_type": "BUY",
                       "duration_seconds": 180},
    }

    detected = {f["code"] for f in inspect_trade(broken)}
    missed = {"price_evolution_empty", "analysis_at_open_missing",
              "close_reason_ambiguous", "direction_mismatch",
              "duration_zero"} - detected
    false_alarms = [f["code"] for f in inspect_trade(clean)]

    report = {
        "component": "trade_data_monitor",
        "version": MONITOR_VERSION,
        "checks": {
            "detected_on_broken_trade": sorted(detected),
            "expected_but_missed": sorted(missed),
            "false_alarms_on_clean_trade": false_alarms,
        },
        "ok": (not missed) and (not false_alarms),
    }
    if missed:
        report["reason"] = ("the monitor failed to detect known defects; it "
                            "cannot be trusted to report healthy")
    elif false_alarms:
        report["reason"] = "the monitor flags a clean trade"
    return report
