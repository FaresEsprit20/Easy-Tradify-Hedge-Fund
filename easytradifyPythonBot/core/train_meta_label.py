#!/usr/bin/env python3
"""
TRAIN THE META-LABEL MODEL  (Stage 7)
=====================================
FILE: core/train_meta_label.py

Fits core/meta_labeling.py's artifact from a replay run and -- the part
that actually matters -- refuses to ship it unless it validates.

USAGE
    python -m core.train_meta_label
    python -m core.train_meta_label --records replay_records.json
    python -m core.train_meta_label --min-auc 0.55 --force

WHY PURGED CROSS-VALIDATION AND NOT A PLAIN SPLIT

The replay steps every 5 M1 bars and holds a position for up to 1000
bars. A single trade's outcome window therefore overlaps the windows of
roughly the next 200 decisions: they are resolved by the SAME future
price path. Under an ordinary shuffled K-fold, a training row and a
test row can be two views of one event, so the model is scored partly
on data it trained on. That does not produce a small optimistic bias,
it produces a large one -- the classic way a backtested classifier
reports 0.75 AUC and delivers nothing live.

So folds are contiguous blocks in time, and any training sample whose
[decision_index, exit_index] interval overlaps a test sample's interval
is PURGED from that fold's training set, with an additional embargo
after the test block. This is Lopez de Prado's purging/embargo, and on
this data it removes a large fraction of the nominal training rows.
That is the point: what remains is the part that was genuinely
independent of what it is being tested on.

WHAT "VALIDATES" MEANS HERE

A model ships only if, out of fold:

  1. mean AUC >= --min-auc (default 0.55). At 0.50 the model is a coin
     flip and adding it to the pipeline is pure complexity.
  2. AUC beats the shuffled-label control by a clear margin. The
     control retrains on randomised labels; anything a real model can
     do that noise can also do is not a finding.
  3. Precision at the operating threshold exceeds the base rate. A
     filter that keeps a set of trades no better than the population
     it filtered from is not filtering.

If it fails, nothing is written and the run says why. A stage that was
never trained stays inactive (see meta_labeling.py's failure
semantics), which is strictly better than one that is confidently
wrong.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.meta_labeling import (          # noqa: E402
    FEATURE_NAMES, FEATURE_VERSION, DEFAULT_MODEL_PATH, build_features,
)
from core.conformal import DEFAULT_CALIBRATION_PATH   # noqa: E402

RECORDS_PATH = os.path.join(_PROJECT_ROOT, "replay_records.json")


# ============================================================
# DATA
# ============================================================

def load_dataset(records_path):
    """
    (X, y, spans, meta) from a replay run.

    spans[i] = (start_bar, end_bar) -- the window over which sample i's
    label was determined. Purging needs it; nothing else does.

    Only WIN/LOSS rows are used. UNRESOLVED means price touched neither
    level inside the holding cap, which is a real event but not a
    binary label, and folding it in as a loss would teach the model
    that "nothing happened" looks like "stopped out".
    """
    with open(records_path, "r", encoding="utf-8") as fh:
        blob = json.load(fh)
    records = blob["records"] if isinstance(blob, dict) else blob

    X, y, spans, skipped = [], [], [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for rec in records:
        shadow = rec.get("shadow") or {}
        outcome = shadow.get("outcome")
        if outcome not in ("WIN", "LOSS"):
            skip(f"outcome={outcome}")
            continue

        capture = rec.get("capture") or {}
        values, reason = build_features(capture)
        if values is None:
            skip(f"features: {reason}")
            continue

        start = rec.get("decision_index")
        if start is None:
            skip("no decision_index")
            continue
        held = shadow.get("bars_held")
        end = start + int(held) if held is not None else start

        X.append(values)
        y.append(1 if outcome == "WIN" else 0)
        spans.append((int(start), int(end)))

    meta = {
        "records_total": len(records),
        "usable": len(X),
        "skipped": skipped,
        "positives": int(sum(y)),
        "base_rate": (sum(y) / len(y)) if y else None,
    }
    return X, y, spans, meta


def impute_and_standardize(X, means=None, scales=None):
    """
    None -> column mean, then z-score.

    Imputing to the mean is what makes a missing feature contribute
    exactly zero to a standardized linear model, which is the only
    honest thing an absent fact can contribute.
    """
    import numpy as np

    n_cols = len(X[0])
    A = np.array([[np.nan if v is None else float(v) for v in row] for row in X],
                 dtype=float)

    if means is None:
        means = np.nanmean(A, axis=0)
        means = np.where(np.isnan(means), 0.0, means)     # all-empty column
    inds = np.where(np.isnan(A))
    A[inds] = np.take(means, inds[1])

    if scales is None:
        scales = A.std(axis=0)
        scales = np.where(scales < 1e-12, 1.0, scales)    # constant column

    return (A - means) / scales, means, scales


# ============================================================
# PURGED CV
# ============================================================

def purged_folds(spans, n_splits=5, embargo_bars=0):
    """
    Contiguous test blocks; training rows overlapping them are purged.

    Yields (train_idx, test_idx). Samples are assumed ordered in time,
    which replay records are.
    """
    n = len(spans)
    fold_size = n // n_splits
    for k in range(n_splits):
        lo = k * fold_size
        hi = n if k == n_splits - 1 else (k + 1) * fold_size
        test_idx = list(range(lo, hi))
        if not test_idx:
            continue

        t_start = min(spans[i][0] for i in test_idx)
        t_end = max(spans[i][1] for i in test_idx) + embargo_bars

        train_idx = [
            i for i in range(n)
            if i < lo or i >= hi
            # keep only rows whose OWN label window is entirely clear of
            # the test block's window
            if not (spans[i][0] <= t_end and spans[i][1] >= t_start)
        ]
        yield train_idx, test_idx


def fit_logistic(Xs, y, C=1.0):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(
        C=C, max_iter=2000, solver="lbfgs",
        # The base rate is ~27% wins. Without this the model can reach
        # good accuracy by predicting "loss" for everything, which is
        # true, useless, and gives a flat score with no ranking.
        class_weight="balanced",
    )
    clf.fit(Xs, y)
    return clf


def cross_validate(X, y, spans, *, n_splits, embargo, C, shuffle_labels=False, seed=0):
    """Mean out-of-fold AUC. Returns (auc, n_evaluated, fold_details)."""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    y_arr = np.array(y)
    if shuffle_labels:
        y_arr = rng.permutation(y_arr)

    aucs, details, oof = [], [], {}
    for train_idx, test_idx in purged_folds(spans, n_splits, embargo):
        ytr, yte = y_arr[train_idx], y_arr[test_idx]
        if len(train_idx) < 40 or len(set(ytr)) < 2 or len(set(yte)) < 2:
            details.append({"train": len(train_idx), "test": len(test_idx),
                            "auc": None, "reason": "degenerate fold"})
            continue

        Xtr = [X[i] for i in train_idx]
        Xte = [X[i] for i in test_idx]
        Xtr_s, means, scales = impute_and_standardize(Xtr)
        Xte_s, _, _ = impute_and_standardize(Xte, means, scales)

        clf = fit_logistic(Xtr_s, ytr, C=C)
        p = clf.predict_proba(Xte_s)[:, 1]
        auc = roc_auc_score(yte, p)
        aucs.append(auc)
        details.append({"train": len(train_idx), "test": len(test_idx),
                        "auc": round(float(auc), 4)})
        for j, i in enumerate(test_idx):
            oof[i] = float(p[j])

    mean_auc = float(sum(aucs) / len(aucs)) if aucs else None
    return mean_auc, len(aucs), details, oof


def precision_at(oof, y, threshold):
    """Win rate among decisions the model would have kept."""
    kept = [i for i, p in oof.items() if p >= threshold]
    if not kept:
        return None, 0
    wins = sum(1 for i in kept if y[i] == 1)
    return wins / len(kept), len(kept)


# ============================================================
# MAIN
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=RECORDS_PATH)
    ap.add_argument("--out", default=DEFAULT_MODEL_PATH)
    ap.add_argument("--calibration-out", default=DEFAULT_CALIBRATION_PATH,
                    help="Stage 8 conformal calibration set, built from the "
                         "purged out-of-fold predictions")
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--embargo", type=int, default=0,
                    help="extra bars of embargo after each test block "
                         "(label-window overlap is already purged)")
    ap.add_argument("--C", type=float, default=0.3,
                    help="inverse regularisation; small on purpose for a "
                         "wide feature set on a short sample")
    ap.add_argument("--threshold", type=float, default=0.65,
                    help="operating threshold, per the pipeline spec")
    ap.add_argument("--min-auc", type=float, default=0.55)
    ap.add_argument("--min-auc-margin", type=float, default=0.03,
                    help="required margin over the shuffled-label control")
    ap.add_argument("--force", action="store_true",
                    help="write the artifact even if validation fails "
                         "(it is written INACTIVE and must be enabled by hand)")
    args = ap.parse_args()

    print(f"Loading {args.records} ...")
    X, y, spans, meta = load_dataset(args.records)
    print(f"  records:   {meta['records_total']}")
    print(f"  usable:    {meta['usable']}  (WIN={meta['positives']}, "
          f"base rate={meta['base_rate']:.3f})" if meta["usable"] else "  usable: 0")
    for reason, count in sorted(meta["skipped"].items(), key=lambda kv: -kv[1])[:6]:
        print(f"    skipped {count:>5}  {reason}")

    if meta["usable"] < 200:
        print("\nREFUSING: fewer than 200 labelled decisions. Nothing "
              "trained on this little generalises; run a longer replay.")
        return 2

    span_len = sorted(e - s for s, e in spans)
    print(f"  label windows: median {span_len[len(span_len)//2]} bars, "
          f"max {span_len[-1]} bars -- these overlap, hence purging")

    print(f"\nPurged {args.splits}-fold CV (embargo={args.embargo} bars, C={args.C}) ...")
    auc, n_folds, details, oof = cross_validate(
        X, y, spans, n_splits=args.splits, embargo=args.embargo, C=args.C)
    for i, d in enumerate(details):
        print(f"  fold {i}: train={d['train']:>5} test={d['test']:>5} "
              f"auc={d.get('auc')}" + (f"  ({d['reason']})" if d.get("reason") else ""))

    if auc is None:
        print("\nREFUSING: every fold was degenerate after purging. The "
              "label windows overlap so heavily that no independent "
              "training set remains. Use a longer replay or a smaller "
              "--max-holding when generating it.")
        return 2

    print(f"\n  mean out-of-fold AUC: {auc:.4f}  ({n_folds} usable folds)")

    ctrl, _, _, _ = cross_validate(X, y, spans, n_splits=args.splits,
                                   embargo=args.embargo, C=args.C,
                                   shuffle_labels=True, seed=17)
    print(f"  shuffled-label control: {ctrl:.4f}" if ctrl else
          "  shuffled-label control: n/a")

    prec, kept = precision_at(oof, y, args.threshold)
    base = meta["base_rate"]
    if prec is None:
        print(f"  precision @ {args.threshold}: no decision scored that high")
    else:
        print(f"  precision @ {args.threshold}: {prec:.3f} on {kept} kept "
              f"({kept/len(y)*100:.1f}% of sample) vs base rate {base:.3f} "
              f"-> {(prec-base)*100:+.1f} pts")

    # ---- the gate --------------------------------------------------
    failures = []
    if auc < args.min_auc:
        failures.append(f"AUC {auc:.4f} < required {args.min_auc}")
    if ctrl is not None and auc - ctrl < args.min_auc_margin:
        failures.append(f"AUC {auc:.4f} is within {args.min_auc_margin} of the "
                        f"shuffled-label control {ctrl:.4f} -- indistinguishable from noise")
    if prec is not None and base is not None and prec <= base:
        failures.append(f"precision @ {args.threshold} ({prec:.3f}) does not beat "
                        f"the base rate ({base:.3f})")

    if failures:
        print("\n" + "=" * 62)
        print("VALIDATION FAILED -- model NOT written")
        print("=" * 62)
        for f in failures:
            print(f"  - {f}")
        print("\nThis is a result, not an error. On this sample the features"
              "\ncarry no out-of-sample signal, so a meta-label filter would"
              "\nbe complexity without discrimination. Options: replay a"
              "\nlonger window, add symbols, or accept that the edge is not"
              "\nin these features.")
        if not args.force:
            return 1
        print("\n--force given: writing anyway, marked inactive.")

    # ---- final fit on everything ----------------------------------
    Xs, means, scales = impute_and_standardize(X)
    clf = fit_logistic(Xs, y, C=args.C)

    artifact = {
        "feature_version": FEATURE_VERSION,
        "features": FEATURE_NAMES,
        "mean": [float(v) for v in means],
        "scale": [float(v) for v in scales],
        "coef": [float(v) for v in clf.coef_[0]],
        "intercept": float(clf.intercept_[0]),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "validated": not failures,
        "metrics": {
            "cv_auc": round(auc, 4),
            "shuffled_control_auc": round(ctrl, 4) if ctrl is not None else None,
            "precision_at_threshold": round(prec, 4) if prec is not None else None,
            "threshold": args.threshold,
            "base_rate": round(base, 4) if base is not None else None,
            "n_samples": meta["usable"],
            "n_folds": n_folds,
            "splits": args.splits,
            "embargo_bars": args.embargo,
            "C": args.C,
        },
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    print(f"\nWrote {args.out}")

    # ---- Stage 8 calibration set ----------------------------------
    # The out-of-fold predictions are exactly what split-conformal
    # needs: every one was scored by a model that never saw it. Reusing
    # them costs nothing and avoids carving a third split out of an
    # already short sample.
    #
    # Written even when validation failed, because the calibration set
    # is a measurement rather than a claim -- and a calibrator built on
    # a weak model is precisely what causes Stage 8 to abstain, which
    # is the behaviour that protects the account.
    calibration = sorted((round(float(p), 6), int(y[i])) for i, p in oof.items())
    cal_blob = {
        "trained_at": artifact["trained_at"],
        "source_model": os.path.basename(args.out),
        "calibration": calibration,
        "metrics": {
            "n": len(calibration),
            "base_rate": round(base, 4) if base is not None else None,
            "cv_auc": round(auc, 4),
            "from": "purged out-of-fold predictions",
        },
    }
    with open(args.calibration_out, "w", encoding="utf-8") as fh:
        json.dump(cal_blob, fh, indent=2)
    print(f"Wrote {args.calibration_out}  ({len(calibration)} calibration points)")

    # Show what Stage 8 will actually do with it, so the operator sees
    # the abstain/trade boundary rather than having to infer it.
    try:
        from core.conformal import evaluate_conformal, reset_cache
        reset_cache()
        print("\nStage 8 (conformal) behaviour across the score range:")
        print(f"  {'score':>7} {'support':>8} {'win rate':>9} {'error':>7}  decision")
        for s in (0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80):
            v = evaluate_conformal(s, calibration_path=args.calibration_out)
            wr = v.get("empirical_win_rate")
            er = v.get("error_rate")
            print(f"  {s:>7.2f} {v.get('support', 0):>8} "
                  f"{(f'{wr:.1%}' if wr is not None else '-'):>9} "
                  f"{(f'{er:.1%}' if er is not None else '-'):>7}  {v.get('decision')}")
    except Exception as e:
        print(f"  (could not preview conformal behaviour: {e})")

    top = sorted(zip(FEATURE_NAMES, artifact["coef"]),
                 key=lambda kv: -abs(kv[1]))[:12]
    print("\nLargest standardized coefficients (sign = direction of P(win)):")
    for name, c in top:
        print(f"  {c:+.4f}  {name}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
