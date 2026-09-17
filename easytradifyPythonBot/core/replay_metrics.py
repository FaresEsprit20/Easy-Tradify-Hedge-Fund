# ============================================================
# REPLAY METRICS & FAILURE CLASSIFICATION
# ============================================================
# FILE: core/replay_metrics.py
#
# Roadmap Phase 6: "Classify losses and rejected opportunities."
#
# The headline metric people ask for is win rate. It is close to useless
# on its own, and it is actively misleading in a 1:2 programme, because:
#
#   - At 1:2 R:R, breakeven is 33.3%. A 45% win rate is PROFITABLE
#     (+0.35R per trade). A 70% win rate at 1:0.5 is not (-0.05R).
#     Expectancy in R is the number that pays.
#   - Win rate rises trivially as you trade less. A filter that rejects
#     everything has an undefined win rate and zero profit.
#   - "Win" counted at the target ignores spread. A 2R target that nets
#     1.7R after spread is not a 2R win.
#
# So the primary output here is expectancy in R, with win rate reported
# alongside it and never alone.
#
# The second output is CALIBRATION, which is what the 7/10 programme is
# really for. The engine emits a probability. Calibration asks: when it
# said 80%, did 80% of those win? A system whose stated probability
# matches its realized hit rate is trustworthy at any win rate. A system
# claiming 90% and delivering 55% is dangerous precisely BECAUSE the
# number is high -- position sizing and gate thresholds both trust it.
# ============================================================

from typing import Dict, Any, List, Optional
from collections import Counter, defaultdict


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and float("-inf") < v < float("inf") else None


def summarize(records: List[Dict[str, Any]], *, net_of_spread: bool = True) -> Dict[str, Any]:
    """
    Headline performance. `records` is ReplayRunner.run() output.
    """
    entries = [r for r in records if r.get("entry_triggered")]
    resolved = [r for r in entries
                if (r.get("outcome") or {}).get("outcome") in ("WIN", "LOSS")]

    wins = [r for r in resolved if r["outcome"]["outcome"] == "WIN"]
    losses = [r for r in resolved if r["outcome"]["outcome"] == "LOSS"]
    unresolved = [r for r in entries if (r.get("outcome") or {}).get("outcome") == "UNRESOLVED"]
    ambiguous = [r for r in resolved if r["outcome"].get("ambiguous")]

    key = "r_multiple_net" if net_of_spread else "r_multiple"
    r_values = [_f(r["outcome"].get(key)) for r in resolved]
    r_values = [v for v in r_values if v is not None]

    n = len(resolved)
    win_rate = (len(wins) / n * 100.0) if n else None
    expectancy = (sum(r_values) / len(r_values)) if r_values else None

    # Break-even win rate implied by the AVERAGE planned R:R actually
    # taken -- the honest yardstick for "is this win rate good enough".
    planned = [_f(r.get("planned_rr")) for r in entries]
    planned = [p for p in planned if p and p > 0]
    avg_planned_rr = (sum(planned) / len(planned)) if planned else None
    breakeven_wr = (100.0 / (1.0 + avg_planned_rr)) if avg_planned_rr else None

    timing_bypassed_entries = len([r for r in entries if r.get("timing_bypassed_replay")])

    return {
        "decisions_evaluated": len(records),
        "entries_taken": len(entries),
        # Bar replay has no real tick stream, so entry_engine.py's
        # timing_ready gate is bypassed rather than enforced (see its
        # is_replay docstring) -- these entries were never tick-confirmed
        # the way a live trade would be. Surfaced here so a high entry
        # count can't be read as "the strategy trades a lot" when it may
        # really mean "the one gate that would have said no can't run on
        # bars."
        "timing_bypassed_entries": timing_bypassed_entries,
        "selectivity_pct": round(len(entries) / len(records) * 100.0, 2) if records else None,
        "resolved": n,
        "unresolved": len(unresolved),
        "ambiguous_bars": len(ambiguous),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "avg_planned_rr": round(avg_planned_rr, 3) if avg_planned_rr else None,
        "breakeven_win_rate_pct": round(breakeven_wr, 2) if breakeven_wr else None,
        "edge_over_breakeven_pct": (round(win_rate - breakeven_wr, 2)
                                    if win_rate is not None and breakeven_wr else None),
        # THE number. Positive means the strategy makes money.
        "expectancy_r": round(expectancy, 4) if expectancy is not None else None,
        "total_r": round(sum(r_values), 2) if r_values else None,
        "avg_win_r": round(sum(v for v in r_values if v > 0) / max(1, len(wins)), 3) if wins else None,
        "avg_loss_r": round(sum(v for v in r_values if v <= 0) / max(1, len(losses)), 3) if losses else None,
        "max_drawdown_r": _max_drawdown(r_values),
        "net_of_spread": net_of_spread,
        "caveats": _caveats(records, entries, resolved, unresolved, ambiguous),
    }


def _max_drawdown(r_values: List[float]) -> Optional[float]:
    if not r_values:
        return None
    peak = 0.0
    equity = 0.0
    dd = 0.0
    for v in r_values:
        equity += v
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return round(dd, 2)


def _caveats(records, entries, resolved, unresolved, ambiguous) -> List[str]:
    """
    Reasons not to trust the headline. Emitted with the result rather
    than buried, because a metric summary that does not state its own
    weaknesses invites exactly the overconfidence this programme exists
    to remove.
    """
    out = []
    if len(resolved) < 30:
        out.append(f"Only {len(resolved)} resolved trades -- far too few for a "
                   f"meaningful win rate. Treat as a smoke test, not evidence.")
    elif len(resolved) < 100:
        out.append(f"{len(resolved)} resolved trades -- a 95% confidence interval on "
                   f"win rate is roughly +/-10 points at this sample size.")
    if unresolved:
        pct = len(unresolved) / max(1, len(entries)) * 100
        out.append(f"{len(unresolved)} trades ({pct:.0f}%) never hit stop or target within "
                   f"the holding window and are EXCLUDED from win rate. If these are "
                   f"systematically bad trades, the win rate is overstated.")
    if ambiguous:
        out.append(f"{len(ambiguous)} trades had stop and target inside one bar's range; "
                   f"which came first is unknowable from OHLC and was resolved by policy.")
    if records and len(entries) / len(records) < 0.01:
        out.append("Selectivity below 1% -- a very small number of setups drives the "
                   "entire result, so it is highly sensitive to a few bars.")
    return out


def calibration(records: List[Dict[str, Any]], *, buckets: int = 10) -> Dict[str, Any]:
    """
    Does the stated probability match the realized hit rate?

    This is the single most important output of the whole replay for a
    7/10 programme. It is what turns "we want 90%" from an aspiration
    into a measurable claim: if the engine says 90% and 90% win, the
    number is real. If it says 90% and 55% win, the number is a fiction
    that every downstream gate is trusting.
    """
    rows = []
    for r in records:
        if not r.get("entry_triggered"):
            continue
        o = (r.get("outcome") or {}).get("outcome")
        if o not in ("WIN", "LOSS"):
            continue
        trace = r.get("trace") or {}
        p = _f(trace.get("probability_final"))
        if p is None:
            p = _f(trace.get("probability_at_decision"))
        if p is None:
            continue
        rows.append((p, 1 if o == "WIN" else 0))

    if not rows:
        return {"available": False, "reason": "no resolved trades carried a probability"}

    width = 100.0 / buckets
    grouped = defaultdict(list)
    for p, w in rows:
        idx = min(buckets - 1, int(p // width))
        grouped[idx].append(w)

    out = []
    total_err = 0.0
    total_n = 0
    for idx in sorted(grouped):
        ws = grouped[idx]
        stated_mid = (idx + 0.5) * width
        realized = sum(ws) / len(ws) * 100.0
        out.append({
            "bucket": f"{idx * width:.0f}-{(idx + 1) * width:.0f}%",
            "n": len(ws),
            "stated_midpoint_pct": round(stated_mid, 1),
            "realized_win_rate_pct": round(realized, 1),
            "gap_pct": round(realized - stated_mid, 1),
        })
        total_err += abs(realized - stated_mid) * len(ws)
        total_n += len(ws)

    return {
        "available": True,
        "n": total_n,
        "buckets": out,
        # Mean absolute calibration error, sample-weighted. Under ~5 is
        # good; over ~15 means the probability is decorative.
        "mean_abs_calibration_error": round(total_err / total_n, 2) if total_n else None,
        "interpretation": (
            "gap > 0 means the engine UNDER-states its edge; gap < 0 means it "
            "OVER-states it. Systematic negative gaps at the high buckets are the "
            "dangerous case: the gates and position sizing both trust that number."
        ),
    }


def classify_rejections(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Why were setups rejected, and at which gate?

    Phase 6 asks for rejected opportunities to be classified, because a
    gate that rejects 99% of everything is not a filter, it is an
    outage -- and it looks identical to a strict filter unless counted.
    """
    gate_counts = Counter()
    reason_counts = Counter()
    for r in records:
        if r.get("entry_triggered"):
            continue
        recon = (r.get("trace_verification") or {}).get("reconstruction") or {}
        gate = recon.get("blocked_at") or "unrecorded"
        gate_counts[gate] += 1
        reason = r.get("rejection_reason") or recon.get("reason") or "unrecorded"
        reason_counts[str(reason)[:120]] += 1

    total = sum(gate_counts.values())
    return {
        "total_rejections": total,
        "by_gate": [
            {"gate": g, "n": c, "pct": round(c / total * 100, 1) if total else None}
            for g, c in gate_counts.most_common()
        ],
        "top_reasons": [{"reason": r, "n": c} for r, c in reason_counts.most_common(15)],
    }


def integrity_report(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Did the trace actually reconstruct the engine's decisions, and did
    the probability ledger reconcile?

    A replay whose traces do not verify is not measuring the engine --
    it is measuring a model of the engine. This must be clean before any
    performance number is quoted.
    """
    verified = [r for r in records if r.get("trace_verification")]
    disagreements = [r for r in verified if not r["trace_verification"].get("agrees")]
    reconciled = [r for r in records if r.get("probability_reconciliation")]
    unreconciled = [r for r in reconciled
                    if not r["probability_reconciliation"].get("reconcilable")]

    violations = []
    for r in records:
        v = ((r.get("trace") or {}).get("data_integrity") or {}).get("violations") or []
        violations.extend(v)

    return {
        "traces_verified": len(verified),
        "reconstruction_disagreements": len(disagreements),
        "reconstruction_agreement_pct": (
            round((len(verified) - len(disagreements)) / len(verified) * 100, 2)
            if verified else None),
        "probability_unreconciled": len(unreconciled),
        "data_integrity_violations": len(violations),
        "violation_kinds": dict(Counter(v.get("kind") for v in violations)),
        "sample_disagreements": [
            {"index": r.get("decision_index"),
             "discrepancy": r["trace_verification"].get("discrepancy"),
             "engine": r["trace_verification"].get("engine_decision"),
             "reconstructed": r["trace_verification"]["reconstruction"].get("reason")}
            for r in disagreements[:5]
        ],
        # A PASS with zero traces verified is worse than useless: it reads
        # as confirmation when nothing was actually checked. The first real
        # replay reported PASS on 0 verified traces.
        "verdict": (
            "NOT VERIFIED -- no DecisionTrace objects were built, so "
            "reconstruction was never tested. Performance numbers are "
            "unconfirmed rather than confirmed."
            if not verified else
            "PASS -- traces reconstruct the engine and probability reconciles"
            if not disagreements and not unreconciled else
            "FAIL -- do not quote performance numbers until this is clean"
        ),
    }


def full_report(records: List[Dict[str, Any]], *, net_of_spread: bool = True) -> Dict[str, Any]:
    """Everything, in the order it should be read."""
    return {
        # Integrity FIRST. If this fails, the rest is noise.
        "integrity": integrity_report(records),
        "performance": summarize(records, net_of_spread=net_of_spread),
        "calibration": calibration(records),
        "rejections": classify_rejections(records),
    }


def format_report(report: Dict[str, Any]) -> str:
    """Human-readable rendering."""
    i = report["integrity"]
    p = report["performance"]
    c = report["calibration"]
    lines = [
        "=" * 62,
        "REPLAY INTEGRITY  (read this before any performance number)",
        "=" * 62,
        f"  verdict:                    {i['verdict']}",
        f"  traces verified:            {i['traces_verified']}",
        f"  reconstruction agreement:   {i['reconstruction_agreement_pct']}%",
        f"  probability unreconciled:   {i['probability_unreconciled']}",
        f"  data integrity violations:  {i['data_integrity_violations']}",
        "",
        "=" * 62,
        "PERFORMANCE",
        "=" * 62,
        f"  decisions evaluated:        {p['decisions_evaluated']}",
        f"  entries taken:              {p['entries_taken']}  ({p['selectivity_pct']}% selectivity)",
        f"  timing-bypassed entries:    {p['timing_bypassed_entries']}  (no real tick stream in replay -- see notes)",
        f"  resolved / unresolved:      {p['resolved']} / {p['unresolved']}",
        f"  win rate:                   {p['win_rate_pct']}%",
        f"  break-even win rate:        {p['breakeven_win_rate_pct']}%  (at avg planned {p['avg_planned_rr']}R)",
        f"  edge over break-even:       {p['edge_over_breakeven_pct']} points",
        f"  EXPECTANCY:                 {p['expectancy_r']} R per trade",
        f"  total R / max drawdown:     {p['total_r']} / {p['max_drawdown_r']}",
    ]
    for cav in p["caveats"]:
        lines.append(f"  ! {cav}")

    lines += ["", "=" * 62, "CALIBRATION  (does the stated probability mean anything?)", "=" * 62]
    if not c.get("available"):
        lines.append(f"  unavailable: {c.get('reason')}")
    else:
        lines.append(f"  mean absolute calibration error: {c['mean_abs_calibration_error']} points")
        lines.append(f"  {'bucket':>12} {'n':>6} {'stated':>8} {'realized':>10} {'gap':>8}")
        for b in c["buckets"]:
            lines.append(f"  {b['bucket']:>12} {b['n']:>6} {b['stated_midpoint_pct']:>7.1f}% "
                         f"{b['realized_win_rate_pct']:>9.1f}% {b['gap_pct']:>+7.1f}")

    r = report["rejections"]
    lines += ["", "=" * 62, "REJECTIONS BY GATE", "=" * 62]
    for g in r["by_gate"]:
        lines.append(f"  {g['gate']:<24} {g['n']:>6}  ({g['pct']}%)")
    return "\n".join(lines)