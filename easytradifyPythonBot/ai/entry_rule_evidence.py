# ai/entry_rule_evidence.py
"""
Evidence for the entry rule table (core/entry_engine.py, entry foundation v2).

Every decision carries every entry rule's verdict (entry_analysis.rules), and
once its result is known, what a trade taken there would have made. This
measures each rule on that:

  split      decisions a rule passed against decisions it failed: won %, net R,
             t -- in the earlier and the later half of the data separately
  side       the same split on the OPPOSITE side of every decision. A rule that
             lifts both sides picks market conditions, not direction
  table      the entries the current modes take (no blocking rule failed), and
             the entries with each rule switched to "observe" (drop one)
  verdict    fixed before any result is read (2026-09-17): a rule blocks only
             when it has SHOWN that it helps -- its passed group beats its failed
             group at the primary geometry in BOTH halves, with at least
             MIN_GROUP decisions in each group of each half, among decisions
             inside the probability band. Anything else is "observe": a rule
             that does not help, and a rule too rare to be shown to help. An
             observed rule is still evaluated on every live decision, so it can
             earn "block" back on later data.
  pass line  strategic_plan_v5_live_data.md: >= 300 trades, >= 65% won,
             >= +0.20R net, t >= 2, on the later half.

Rows are plain dicts, so the history replay (ai/price_history_study.py records
labelled on quote bars) and the live decision log (decisions + decision_outcomes)
go through the same functions:

    {"symbol": str, "ts": float, "direction": "BUY"|"SELL",
     "rules": {rule: True|False|None},          # None = not measurable
     "results": {geometry: {"BUY": r_net, "SELL": r_net}}}

Independence: decisions of one symbol on one day share most of their price
path, so t uses a cluster-robust standard error over (symbol, day).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

BLOCK = "block"
OBSERVE = "observe"
MIN_GROUP = 100
PASS_LINE = {"min_trades": 300, "min_won": 0.65, "min_net_r": 0.20, "min_t": 2.0}
BAND_RULE = "probability"


# ------------------------------------------------------------------ statistics
def cluster_stats(values: Sequence[float], clusters: Sequence[Any]) -> Dict[str, Any]:
    """n, clusters, won share, mean net R and its cluster-robust t."""
    arr = np.asarray([v for v in values], dtype=float)
    n = int(arr.size)
    if n == 0:
        return {"n": 0, "clusters": 0, "won": None, "net_r": None, "t": None}
    mean = float(arr.mean())
    sums: Dict[Any, float] = defaultdict(float)
    for v, c in zip(arr, clusters):
        sums[c] += float(v) - mean
    k = len(sums)
    t = None
    if k > 1:
        var = sum(s * s for s in sums.values()) * k / (k - 1)
        se = math.sqrt(var) / n
        t = round(mean / se, 2) if se > 0 else None
    return {"n": n, "clusters": k, "won": round(float((arr > 0).mean()), 4),
            "net_r": round(mean, 4), "t": t}


def _cluster(row: Mapping[str, Any]) -> Tuple[str, str]:
    day = datetime.fromtimestamp(float(row["ts"]), tz=timezone.utc).strftime("%Y-%m-%d")
    return str(row.get("symbol")), day


def _opposite(side: str) -> str:
    return "SELL" if side == "BUY" else "BUY"


def results(rows: Iterable[Mapping[str, Any]], geometry: str, opposite: bool = False) -> Dict[str, Any]:
    """Stats of the decision's own side (or the opposite side) at one geometry."""
    values, clusters = [], []
    for row in rows:
        side = row.get("direction")
        if side not in ("BUY", "SELL"):
            continue
        r = ((row.get("results") or {}).get(geometry) or {}).get(_opposite(side) if opposite else side)
        if r is None or not math.isfinite(r):
            continue
        values.append(r)
        clusters.append(_cluster(row))
    return cluster_stats(values, clusters)


# ------------------------------------------------------------------ populations
def halves(rows: Sequence[Mapping[str, Any]]) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Earlier and later half by decision time."""
    ordered = sorted(rows, key=lambda r: float(r["ts"]))
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:]


def blocked_by(row: Mapping[str, Any], modes: Mapping[str, str]) -> List[str]:
    """Rules in block mode that failed (not measurable never blocks)."""
    return [name for name, passed in (row.get("rules") or {}).items()
            if modes.get(name, BLOCK) == BLOCK and passed is False]


def entries(rows: Iterable[Mapping[str, Any]], modes: Mapping[str, str]) -> List[Mapping[str, Any]]:
    return [row for row in rows if not blocked_by(row, modes)]


def rule_names(rows: Iterable[Mapping[str, Any]]) -> List[str]:
    seen: Dict[str, None] = {}
    for row in rows:
        for name in (row.get("rules") or {}):
            seen.setdefault(name, None)
    return list(seen)


# ------------------------------------------------------------------ the report
def split(rows: Sequence[Mapping[str, Any]], rule: str, geometry: str) -> Dict[str, Any]:
    passed = [r for r in rows if (r.get("rules") or {}).get(rule) is True]
    failed = [r for r in rows if (r.get("rules") or {}).get(rule) is False]
    out = {"pass": results(passed, geometry), "fail": results(failed, geometry),
           "pass_other_side": results(passed, geometry, opposite=True),
           "fail_other_side": results(failed, geometry, opposite=True)}
    p, f = out["pass"]["net_r"], out["fail"]["net_r"]
    out["lift"] = None if p is None or f is None else round(p - f, 4)
    po, fo = out["pass_other_side"]["net_r"], out["fail_other_side"]["net_r"]
    out["lift_other_side"] = None if po is None or fo is None else round(po - fo, 4)
    return out


def verdict(early: Sequence[Mapping[str, Any]], late: Sequence[Mapping[str, Any]], rule: str,
            geometry: str, current_mode: str) -> Dict[str, Any]:
    """The pre-registered mode decision for one rule (see the module docstring)."""
    def band(rows):
        if rule == BAND_RULE:
            return rows
        return [r for r in rows if (r.get("rules") or {}).get(BAND_RULE) is True]

    s1, s2 = split(band(early), rule, geometry), split(band(late), rule, geometry)
    sizes = [s1["pass"]["n"], s1["fail"]["n"], s2["pass"]["n"], s2["fail"]["n"]]
    both_lift = s1["lift"] is not None and s2["lift"] is not None and s1["lift"] > 0 and s2["lift"] > 0
    if min(sizes) < MIN_GROUP:
        keep, why = False, f"unproven: smallest group {min(sizes)} < {MIN_GROUP} decisions"
    elif both_lift:
        keep, why = True, "passed group beats failed group in both halves"
    else:
        keep, why = False, "passed group does not beat failed group in both halves"
    return {"mode": BLOCK if keep else OBSERVE, "was": current_mode, "why": why,
            "lift_early": s1["lift"], "lift_late": s2["lift"],
            "lift_other_side_early": s1["lift_other_side"], "lift_other_side_late": s2["lift_other_side"],
            "sizes": sizes}


def meets_pass_line(stats: Mapping[str, Any]) -> bool:
    return bool(stats.get("n", 0) >= PASS_LINE["min_trades"]
                and (stats.get("won") or 0) >= PASS_LINE["min_won"]
                and (stats.get("net_r") or -9) >= PASS_LINE["min_net_r"]
                and (stats.get("t") or 0) >= PASS_LINE["min_t"])


def report(rows: Sequence[Mapping[str, Any]], modes: Mapping[str, str], geometries: Sequence[str],
           primary: str) -> Dict[str, Any]:
    rows = [r for r in rows if r.get("direction") in ("BUY", "SELL")]
    early, late = halves(rows)
    names = rule_names(rows)
    out: Dict[str, Any] = {
        "decisions": len(rows), "primary_geometry": primary, "geometries": list(geometries),
        "period": [min((r["ts"] for r in rows), default=None), max((r["ts"] for r in rows), default=None)],
        "split_ts": float(late[0]["ts"]) if late else None,
        "modes": dict(modes), "rules": names,
    }
    out["baseline"] = {h: {g: results(part, g) for g in geometries}
                       for h, part in (("early", early), ("late", late))}
    out["rule_split"] = {name: {h: {g: split(part, name, g) for g in geometries}
                                for h, part in (("early", early), ("late", late))} for name in names}
    out["measurable"] = {name: {"measured": sum(1 for r in rows if (r.get("rules") or {}).get(name) is not None),
                                "passed": sum(1 for r in rows if (r.get("rules") or {}).get(name) is True)}
                         for name in names}
    out["table"] = {h: {g: results(entries(part, modes), g) for g in geometries}
                    for h, part in (("early", early), ("late", late))}
    out["drop_one"] = {name: {h: {g: results(entries(part, {**modes, name: OBSERVE}), g) for g in geometries}
                              for h, part in (("early", early), ("late", late))}
                       for name in names if modes.get(name, BLOCK) == BLOCK}
    out["verdict"] = {name: verdict(early, late, name, primary, modes.get(name, BLOCK)) for name in names}
    verdict_modes = {name: v["mode"] for name, v in out["verdict"].items()}
    out["verdict_modes"] = verdict_modes
    out["verdict_table"] = {h: {g: results(entries(part, verdict_modes), g) for g in geometries}
                            for h, part in (("early", early), ("late", late))}
    # the same entries traded the opposite way: does the engine's side beat a coin flip?
    out["verdict_table_other_side"] = {h: {g: results(entries(part, verdict_modes), g, opposite=True)
                                           for g in geometries}
                                       for h, part in (("early", early), ("late", late))}
    out["pass_line"] = {
        "rule": PASS_LINE,
        "current_modes_late": {g: meets_pass_line(out["table"]["late"][g]) for g in geometries},
        "verdict_modes_late": {g: meets_pass_line(out["verdict_table"]["late"][g]) for g in geometries},
    }
    return out


# ------------------------------------------------------------------ the live decision log
GEOMETRIES = ("engine", "scalp|M5x1|1R", "precision|M15x1|1R", "precision|M15x1|2R", "precision|H1x1|1R")
PRIMARY = "precision|M15x1|1R"


def _epoch(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def row_from_decision(decision: Mapping[str, Any], outcome: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """One evidence row from a `decisions` document and its `decision_outcomes`
    document (ai/decision_outcomes.py). None when the result is not usable or
    the decision predates the rule table."""
    from ai.price_evolution_maps import ENTRY_RULE_CODES

    if (outcome or {}).get("status") != "ok":
        return None
    side = str(decision.get("direction") or "").upper()
    ts = _epoch(decision.get("decided_at"))
    if side not in ("BUY", "SELL") or ts is None:
        return None
    snapshot = decision.get("snapshot") or {}
    rules = {name: snapshot[f"ea_r_{code}_p"] for name, code in ENTRY_RULE_CODES.items()
             if f"ea_r_{code}_p" in snapshot}
    if not rules:
        return None
    by_geometry: Dict[str, Dict[str, float]] = defaultdict(dict)
    for key, res in (outcome.get("grid") or {}).items():
        geometry, _, grid_side = str(key).rpartition("|")
        if isinstance(res, Mapping) and res.get("r_net") is not None:
            by_geometry[geometry][grid_side] = float(res["r_net"])
    engine = ((outcome.get("engine") or {}).get("result") or {})
    if engine.get("r_net") is not None:
        by_geometry["engine"][side] = float(engine["r_net"])     # the engine traded its own side only
    return {"symbol": decision.get("symbol"), "ts": ts, "direction": side, "rules": rules,
            "results": dict(by_geometry), "engine": (decision.get("engine") or {}).get("fingerprint")}


def live_rows(days: float = 7.0, decisions=None, outcomes=None,
              now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Rows for every decision of the last `days` whose result is in."""
    from datetime import timedelta

    if decisions is None or outcomes is None:
        from ai.decision_outcomes import _collections
        decisions, outcomes = _collections()
    now = now or datetime.now(timezone.utc)
    docs = list(decisions.find({"decided_at": {"$gte": now - timedelta(days=days)}, "outcome.status": "ok"},
                               {"order_flow": 0}))
    results = {o["decision_key"]: o for o in outcomes.find(
        {"decision_key": {"$in": [d.get("key") for d in docs]}})}
    rows = [row_from_decision(d, results.get(d.get("key"))) for d in docs]
    return [r for r in rows if r is not None]


def live_report(days: float = 7.0, fingerprint: Optional[str] = None, **collections) -> Tuple[Dict[str, Any], str]:
    """The rule-table report on the live decision log, one engine version only
    (strategic_plan_v5_live_data.md: never mix engine versions)."""
    from collections import Counter
    from core.asset_analysis_config import ENTRY_RULE_MODES

    rows = live_rows(days, **collections)
    versions = Counter(r.get("engine") for r in rows)
    fingerprint = fingerprint or (versions.most_common(1)[0][0] if versions else None)
    rows = [r for r in rows if r.get("engine") == fingerprint]
    rep = report(rows, ENTRY_RULE_MODES, GEOMETRIES, PRIMARY)
    rep["engine_fingerprint"] = fingerprint
    rep["engine_versions_seen"] = dict(versions)
    return rep, to_markdown(rep, f"Entry rule table on the live decision log (engine {fingerprint}, last {days:g} days)")


# ------------------------------------------------------------------ markdown
def _fmt(stats: Mapping[str, Any]) -> str:
    if not stats or not stats.get("n"):
        return "n=0"
    won = f"{100 * stats['won']:.1f}%" if stats.get("won") is not None else "-"
    t = f"{stats['t']:+.1f}" if stats.get("t") is not None else "-"
    return f"n={stats['n']} ({stats['clusters']}d) {won} {stats['net_r']:+.3f}R t={t}"


def to_markdown(rep: Mapping[str, Any], title: str) -> str:
    g0 = rep["primary_geometry"]
    lines = [f"# {title}", ""]
    period = rep.get("period") or [None, None]
    if period[0] is not None:
        fmt = lambda ts: datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(f"Decisions: {rep['decisions']} ({fmt(period[0])} to {fmt(period[1])}, "
                     f"halves split at {fmt(rep['split_ts'])}). Primary geometry: `{g0}`. "
                     f"Each cell: n (symbol-days) won% net R per decision, cluster-robust t.")
    lines += ["", "## Baseline: every decision, its own side", "",
              "| geometry | early half | later half |", "|---|---|---|"]
    for g in rep["geometries"]:
        lines.append(f"| `{g}` | {_fmt(rep['baseline']['early'][g])} | {_fmt(rep['baseline']['late'][g])} |")

    lines += ["", f"## Each rule: passed vs failed (`{g0}`)", "",
              "Lift = net R of passed minus failed. Other side = the same decisions traded the opposite way; "
              "a rule that lifts both sides is choosing conditions, not direction.", "",
              "| rule | measured / passed | half | passed | failed | lift | lift other side |",
              "|---|---|---|---|---|---|---|"]
    for name in rep["rules"]:
        m = rep["measurable"][name]
        for h in ("early", "late"):
            s = rep["rule_split"][name][h][g0]
            lines.append(f"| {name if h == 'early' else ''} | "
                         f"{str(m['measured']) + ' / ' + str(m['passed']) if h == 'early' else ''} | {h} | "
                         f"{_fmt(s['pass'])} | {_fmt(s['fail'])} | "
                         f"{'-' if s['lift'] is None else format(s['lift'], '+.3f')} | "
                         f"{'-' if s['lift_other_side'] is None else format(s['lift_other_side'], '+.3f')} |")

    lines += ["", "## Entries under the current modes, and with one rule switched to observe", "",
              "| modes | geometry | early half | later half |", "|---|---|---|---|"]
    for g in rep["geometries"]:
        lines.append(f"| current | `{g}` | {_fmt(rep['table']['early'][g])} | {_fmt(rep['table']['late'][g])} |")
    for name, by_half in rep["drop_one"].items():
        lines.append(f"| without {name} | `{g0}` | {_fmt(by_half['early'][g0])} | {_fmt(by_half['late'][g0])} |")

    lines += ["", "## Verdict (rule fixed before the results were read)", "",
              "| rule | current | verdict | lift early | lift later | why |", "|---|---|---|---|---|---|"]
    for name, v in rep["verdict"].items():
        fmt_l = lambda x: "-" if x is None else f"{x:+.3f}"
        lines.append(f"| {name} | {rep['modes'].get(name, BLOCK)} | **{v['mode']}** | {fmt_l(v['lift_early'])} | "
                     f"{fmt_l(v['lift_late'])} | {v['why']} |")
    lines += ["", "| entries under the verdict modes | early half | later half | pass line (later) | "
              "same entries, opposite side (later) |", "|---|---|---|---|---|"]
    for g in rep["geometries"]:
        lines.append(f"| `{g}` | {_fmt(rep['verdict_table']['early'][g])} | "
                     f"{_fmt(rep['verdict_table']['late'][g])} | "
                     f"{'PASS' if rep['pass_line']['verdict_modes_late'][g] else 'fail'} | "
                     f"{_fmt(rep['verdict_table_other_side']['late'][g])} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="entry rule table evidence from the live decision log")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--fingerprint", default=None)
    args = ap.parse_args(argv)
    rep, md = live_report(args.days, args.fingerprint)
    out = Path(__file__).resolve().parents[1] / "reports" / "entry_rules"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"LIVE_{datetime.now(timezone.utc):%Y-%m-%d}.md"
    path.write_text(md, encoding="utf-8")
    print(f"{rep['decisions']} decisions -> {path}")


if __name__ == "__main__":
    main()
