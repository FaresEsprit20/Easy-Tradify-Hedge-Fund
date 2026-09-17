# ============================================================
# AI_MarketReplay -- CLI
# ============================================================
#
# The specification's `cli.py`. One command that runs the whole stack against
# REAL stored trades and prints what it found.
#
# WHY THIS IS THE MISSING PIECE
# -----------------------------
# Everything built so far is verified against synthetic fixtures. That proves
# the code does what it was written to do; it proves nothing about whether the
# assumptions hold on this account's actual history. Several of those
# assumptions are load-bearing and untested against reality:
#
#   - that stored trades carry the fields extraction expects
#   - that price_evolution decodes on both storage formats in the wild
#   - that probability is informative enough to calibrate
#   - that any of the four models clears its promotion gates
#
# Every one of those is a question about data, and only real data answers it.
#
# READ-ONLY, WITH ONE HONEST CAVEAT
# ---------------------------------
# This module reads Firestore and writes nothing back: it calls only
# get_closed_trades, never save_*, append_to_array, or the recorder's
# persistence path. A diagnostic that can mutate the record it is diagnosing
# is not a diagnostic.
#
# But "runs without writing anything" would be a false claim, and it was made
# before checking. Initialising the shared service
# (core.firebase.get_firebase_service) performs a connection-test write to
# `test/test` and starts a background batch thread -- see
# firebase_service._init_firebase. That is pre-existing behaviour on every
# connection the bot makes, not something this CLI adds, and it touches no
# trade data. It is stated here because a caveat discovered later is worth
# less than one stated up front.
#
# Usage:
#     python -m ai.aireplay.cli --limit 200
#     python -m ai.aireplay.cli --limit 500 --symbol EURUSD --json report.json
#     python -m ai.aireplay.cli --synthetic          # no Firebase needed
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

# Must precede anything that may print. Firebase and the analysis layer log
# with emoji, and on a cp1252 console that raises UnicodeEncodeError from
# inside an exception handler -- so the failure that surfaces is an encoding
# error rather than the real one. Measured here: a missing-credentials message
# came back as "'charmap' codec can't encode '❌'", which says nothing
# about credentials. This is the same omission that once left GNN reported as
# an import failure when the real cause was an emoji in a log line.
import core.console_safe  # noqa: E402,F401

from .consistency import consistency_report
from .counterfactual import aggregate_branches, branch_trade
from .data_engine import (
    extract_replay_records,
    snapshot_coverage,
    self_check as extraction_check,
)
from .models import SCHEMA_VERSION, EventType
from .replay_engine import replay_trades

CLI_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

# The service resolves credentials relative to the CURRENT WORKING DIRECTORY
# ("firebase-credentials.json"), plus a few fixed fallbacks -- none of which is
# api/. The bot works because it runs from api/; anything run from the package
# root silently gets offline mode and an empty result that looks like "no
# trades" rather than "no credentials".
CREDENTIAL_CANDIDATES = (
    "firebase-credentials.json",
    os.path.join("api", "firebase-credentials.json"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "api", "firebase-credentials.json"),
)


def resolve_credentials(explicit: Optional[str] = None) -> Optional[str]:
    """Find the credentials file, so the CLI is not cwd-dependent."""
    for candidate in ([explicit] if explicit else []) + list(CREDENTIAL_CANDIDATES):
        if candidate and os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def load_trades(limit: int = 200, symbol: Optional[str] = None,
                credentials: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Closed trades from Firestore. Reads trade data only.

    Returns an empty list rather than raising when Firebase is unavailable, so
    the CLI can explain the situation instead of dying with a stack trace at
    someone who just wanted a report.
    """
    path = resolve_credentials(credentials)
    if path:
        os.environ["FIREBASE_CREDENTIALS_PATH"] = path
        print(f"  credentials: {path}")
    else:
        print("  credentials: NOT FOUND -- Firebase will run offline and "
              "return nothing")
        return []

    try:
        from core.firebase import get_firebase_service

        firebase = get_firebase_service()
        if not firebase or not firebase.is_healthy():
            print("  Firebase did not initialise (offline mode)")
            return []
        rows = firebase.get_closed_trades(limit=limit, symbol=symbol) or []
        if not rows:
            # "Empty result" and "could not connect" were reported the same
            # way, which cost real debugging time: a missing composite index
            # and an empty collection both surfaced as "Firebase may be
            # unavailable". Say which one it is.
            try:
                total = (firebase.db.collection(firebase.config.COLLECTION_TRADES)
                         .count().get()[0][0].value)
                print(f"  connected OK; collection "
                      f"'{firebase.config.COLLECTION_TRADES}' holds "
                      f"{int(total)} documents total")
            except Exception as count_error:
                print(f"  connected OK; could not count the collection: "
                      f"{type(count_error).__name__}: {count_error}")
        return rows
    except Exception as exc:
        print(f"  could not reach Firebase: {type(exc).__name__}: {exc}")
        return []


def synthetic_trades(count: int = 40) -> List[Dict[str, Any]]:
    """Fixture data, so the CLI is runnable without credentials."""
    sys.path.insert(0, "tests")
    from conftest import build_trade
    return [build_trade(ticket=i, points=3 + i % 4, winning=i % 2 == 0)
            for i in range(1, count + 1)]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def run_extraction(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    records = extract_replay_records(trades)
    check = extraction_check(trades)
    coverage = (records[0].decision_state or {}).get("coverage") if records else {}
    leakage = records[0].leakage_report() if records else {}

    # Section-level coverage is measured on the canonical record; the object
    # replay actually consumes is the snapshot, and the two disagreed. Measured
    # across EVERY record rather than the first, because a payload shape that
    # only some trades carry is exactly the kind of loss a single sample hides.
    by_id = {str(t.get("trade_id") or t.get("ticket") or ""): t for t in trades}
    worst_ratio, total_missing, checked = 1.0, set(), 0
    for record in records:
        raw = by_id.get(record.trade_id) or {}
        analysis = raw.get("analysis_at_open") or {}
        execution = next((snap for snap in record.decision_snapshots
                          if snap.event_type is EventType.EXECUTION), None)
        if not analysis or execution is None:
            continue
        result = snapshot_coverage(analysis, execution)
        checked += 1
        worst_ratio = min(worst_ratio, result["coverage_ratio"])
        total_missing.update(result["missing"])

    return {
        "snapshot_coverage_checked": checked,
        "snapshot_worst_coverage": round(worst_ratio, 4) if checked else None,
        "snapshot_lossless": (not total_missing) if checked else None,
        "snapshot_missing_leaves": sorted(total_missing)[:20],
        "trades_in": len(trades),
        "records_extracted": len(records),
        "extraction_rate": round(len(records) / len(trades), 3) if trades else None,
        "lossless": (coverage or {}).get("lossless"),
        "dropped_sections": (coverage or {}).get("dropped"),
        "sections_seen": (coverage or {}).get("total_sections"),
        "outcome_leaked": (leakage or {}).get("outcome_leaked"),
        "unclassified_fields": (leakage or {}).get("unclassified_fields"),
        "ok": check.get("ok"),
        "_records": records,
    }


def run_replay(records: Sequence[Any]) -> Dict[str, Any]:
    results = replay_trades(records)
    divergent = [r for r in results
                 if r["divergences"].get("first_material_divergence")]
    warned = [r for r in results if r["divergences"].get("anomaly_preceded_divergence")]

    classes: Dict[str, int] = {}
    for result in results:
        name = result["attribution"]["failure_class"]
        classes[name] = classes.get(name, 0) + 1

    return {
        "replayed": len(results),
        "with_material_divergence": len(divergent),
        "warning_preceded_damage": len(warned),
        "warning_share": (round(len(warned) / len(divergent), 3)
                          if divergent else None),
        "attribution_classes": dict(sorted(
            classes.items(), key=lambda kv: -kv[1])),
    }


def run_counterfactuals(records: Sequence[Any]) -> Dict[str, Any]:
    results = [branch_trade(r) for r in records]
    aggregate = aggregate_branches(results)
    improvable = [r for r in results
                  if (r.get("comparison") or {}).get("better_alternative_existed")]
    ratios = [(r["comparison"] or {}).get("capture_ratio") for r in results]
    ratios = [x for x in ratios if x is not None]

    return {
        "branched": sum(1 for r in results if r.get("branches")),
        "trades_with_a_better_alternative": len(improvable),
        "actual_mean_r": aggregate.get("actual_mean_r"),
        "best_policy": aggregate.get("best_policy"),
        "mean_capture_ratio": (round(sum(ratios) / len(ratios), 3)
                               if ratios else None),
    }


def run_models(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Every model's promotion verdict on this data.

    A refusal here is the system working. These gates exist because
    meta-labeling once looked promising and was correctly rejected; expecting
    them all to pass would misunderstand what they are for.
    """
    from .. import abstention_model, calibration_model, exit_model, target_model

    verdicts: Dict[str, Any] = {}
    for name, module in (("exit_model", exit_model),
                         ("target_model", target_model),
                         ("calibration_model", calibration_model),
                         ("abstention_model", abstention_model)):
        try:
            report = module.train_and_validate(trades)
            entry = {
                "promoted": report.get("promoted"),
                "rejected_because": report.get("rejected_because"),
                "samples": report.get("samples"),
            }
            if name == "calibration_model":
                diagnostics = report.get("diagnostics") or {}
                entry["input_is_informative"] = diagnostics.get("input_is_informative")
                entry["stated_probability_std"] = diagnostics.get("std")
                entry["auc"] = diagnostics.get("auc")
                entry["warning"] = report.get("warning")
            else:
                expectancy = report.get("expectancy") or {}
                entry["expectancy_delta_r"] = expectancy.get("delta_r")
            verdicts[name] = entry
        except Exception as exc:
            verdicts[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return verdicts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    extraction = run_extraction(trades)
    records = extraction.pop("_records")

    return {
        "cli_version": CLI_VERSION,
        "schema_version": SCHEMA_VERSION,
        "extraction": extraction,
        "replay": run_replay(records) if records else {},
        "counterfactuals": run_counterfactuals(records) if records else {},
        "simulator_consistency": consistency_report(records) if records else {},
        "models": run_models(trades) if trades else {},
    }


def print_report(report: Dict[str, Any]) -> None:
    def header(title: str) -> None:
        print(f"\n{title}\n{'-' * len(title)}")

    extraction = report["extraction"]
    header("EXTRACTION (Phase 1)")
    print(f"  trades in                 {extraction['trades_in']}")
    print(f"  records extracted         {extraction['records_extracted']}"
          f"  (rate {extraction['extraction_rate']})")
    print(f"  lossless (sections)       {extraction['lossless']}")
    print(f"  dropped sections          {extraction['dropped_sections']}")
    print(f"  lossless (snapshot leaves) {extraction['snapshot_lossless']}"
          f"  worst={extraction['snapshot_worst_coverage']}"
          f"  checked={extraction['snapshot_coverage_checked']}")
    if extraction.get("snapshot_missing_leaves"):
        print("  leaves missing from snapshots (replay input, not the record):")
        for leaf in extraction["snapshot_missing_leaves"]:
            print(f"      {leaf}")
    print(f"  outcome leaked            {extraction['outcome_leaked']}")
    print(f"  unclassified fields       {extraction['unclassified_fields']}")

    replay = report.get("replay") or {}
    if replay:
        header("REPLAY (Phase 3)")
        print(f"  replayed                  {replay['replayed']}")
        print(f"  material divergence       {replay['with_material_divergence']}")
        print(f"  warning preceded damage   {replay['warning_preceded_damage']}"
              f"  (share {replay['warning_share']})")
        print("  attribution candidates:")
        for name, count in (replay["attribution_classes"] or {}).items():
            print(f"      {name:22s} {count}")

    counterfactuals = report.get("counterfactuals") or {}
    if counterfactuals:
        header("COUNTERFACTUALS")
        print(f"  actual mean               {counterfactuals['actual_mean_r']}R")
        print(f"  better alternative        "
              f"{counterfactuals['trades_with_a_better_alternative']} trades")
        print(f"  mean capture ratio        {counterfactuals['mean_capture_ratio']}")
        best = counterfactuals.get("best_policy")
        if best:
            print(f"  best policy               {best['policy']} "
                  f"({best['mean_r']}R, delta {best['delta_vs_actual_r']}R)")

    consistency = report.get("simulator_consistency") or {}
    if consistency:
        header("SIMULATOR CONSISTENCY")
        print(f"  verdict                   {consistency.get('verdict')}")
        print(f"  disagreement rate         {consistency.get('disagreement_rate')}")
        if consistency.get("disagreements_by_field"):
            print(f"  by field                  "
                  f"{consistency['disagreements_by_field']}")

    models = report.get("models") or {}
    if models:
        header("MODEL PROMOTION VERDICTS")
        print("  (a refusal here is the gate working, not a failure)")
        for name, verdict in models.items():
            if "error" in verdict:
                print(f"  {name:20s} ERROR: {verdict['error']}")
                continue
            status = "PROMOTED" if verdict.get("promoted") else "refused"
            print(f"  {name:20s} {status:9s} samples={verdict.get('samples')}")
            if verdict.get("rejected_because"):
                print(f"      why: {verdict['rejected_because'][:110]}")
            if name == "calibration_model":
                print(f"      probability informative: "
                      f"{verdict.get('input_is_informative')} "
                      f"(std {verdict.get('stated_probability_std')}, "
                      f"auc {verdict.get('auc')})")

    header("WHAT THIS DOES NOT TELL YOU")
    print("  Promotion verdicts are measured on stored history only. A model")
    print("  that passes here has not been shown to work forward.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the AI_MarketReplay stack against stored trades "
                    "(read-only).")
    parser.add_argument("--limit", type=int, default=200,
                        help="maximum closed trades to load (default 200)")
    parser.add_argument("--symbol", default=None, help="restrict to one symbol")
    parser.add_argument("--synthetic", action="store_true",
                        help="use fixture data instead of Firebase")
    parser.add_argument("--credentials", default=None,
                        help="path to firebase-credentials.json")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write the full report as JSON")
    args = parser.parse_args(argv)

    print("=" * 62)
    print(f"AI_MarketReplay CLI v{CLI_VERSION}")
    print("reads trade data only; never writes to it")
    if not args.synthetic:
        print("note: connecting writes a test/test doc (firebase_service init)")
    print("=" * 62)

    if args.synthetic:
        print("\nloading synthetic fixture trades...")
        trades = synthetic_trades()
    else:
        print(f"\nloading up to {args.limit} closed trades from Firebase...")
        trades = load_trades(args.limit, args.symbol, args.credentials)

    if not trades:
        print("\n  No trades loaded.")
        print("  See the diagnosis above for which cause applies.")
        print("  Re-run with --synthetic to exercise the pipeline without data.")
        return 1

    print(f"  loaded {len(trades)} trades")
    report = build_report(trades)
    print_report(report)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        print(f"\n  full report written to {args.json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
