"""Positive control for the Gate 1b/1d protocol: would the test find an edge if one existed?

A known pocket is planted in the real Gate 1b events (real features, real market groups, real times); outcomes are
drawn at random with a fixed win rate. The planted rule lives in the features, so a working protocol must recover it
on held-out markets and weeks.
  planted   events with rsi_m15 < 35 and r15 < -0.8 (about 3% of events): long wins with probability 0.72;
            everything else: 0.47. Win = +1R - 0.05R cost, loss = -1R - 0.05R
  null      same, but the pocket's win rate is 0.47 too
  protocol  identical to Gate 1b/1d step B: HistGradientBoosting, 3 market groups (seed 11), train on other markets
            before 2026-07-20, score the held-out group from 2026-07-20, top 10/5/2% slices, shuffled-label control,
            PASS = >= 300 trades, >= 65% won, >= +0.20R, t >= 2 while the control fails

    python -m engine_v2.run.positive_control
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def run(pocket_win: float, seed: int = 3):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from engine_v2.run.gate1b import FEATURES, T_SPLIT, _stats
    z = np.load(ROOT / "reports" / "v4" / "gate1b" / "events.npz")
    sym_arr, t_arr, X = z["symbol"], z["t"], z["X"].astype(float)
    rs = np.random.default_rng(seed)
    pocket = (X[:, FEATURES.index("rsi_m15")] < 35) & (X[:, FEATURES.index("r15")] < -0.8)
    p_win = np.where(pocket, pocket_win, 0.47)
    y_all = (rs.random(len(p_win)) < p_win).astype(int)
    net_all = np.where(y_all == 1, 1.0, -1.0) - 0.05
    syms = sorted(set(sym_arr.tolist()))
    rng = np.random.default_rng(11)
    order = list(rng.permutation(syms))
    groups = [set(order[k::3]) for k in range(3)]
    params = dict(max_depth=4, learning_rate=0.05, max_iter=400, min_samples_leaf=100, l2_regularization=1.0)
    ranks, ranks_c, idxs, aucs = [], [], [], []
    for grp in groups:
        in_g = np.isin(sym_arr, list(grp))
        tr, te = (~in_g) & (t_arr < T_SPLIT), in_g & (t_arr >= T_SPLIT)
        p = HistGradientBoostingClassifier(**params, random_state=0).fit(X[tr], y_all[tr]).predict_proba(X[te])[:, 1]
        pc = HistGradientBoostingClassifier(**params, random_state=0).fit(X[tr], rng.permutation(y_all[tr])).predict_proba(X[te])[:, 1]
        aucs.append(roc_auc_score(y_all[te], p))
        ranks.append(np.argsort(np.argsort(-p)) / len(p))
        ranks_c.append(np.argsort(np.argsort(-pc)) / len(pc))
        idxs.append(np.flatnonzero(te))
    rk, rkc, ix = np.concatenate(ranks), np.concatenate(ranks_c), np.concatenate(idxs)
    okf = lambda s: s.get("n", 0) >= 300 and s["win"] >= 0.65 and s["net"] >= 0.20 and s["t"] >= 2
    out = {"pocket_share": round(float(pocket.mean()), 4), "auc": round(float(np.mean(aucs)), 3)}
    passed = False
    for q in (0.10, 0.05, 0.02):
        sel, selc = ix[rk < q], ix[rkc < q]
        st, sc = _stats(net_all[sel], y_all[sel]), _stats(net_all[selc], y_all[selc])
        out[f"top{q:.0%}"], out[f"control_top{q:.0%}"] = st, sc
        passed = passed or (okf(st) and not okf(sc))
    out["PASS"] = passed
    return out


if __name__ == "__main__":
    for name, w in (("planted 72% pocket", 0.72), ("null (no pocket)", 0.47)):
        r = run(w)
        print(name, r, flush=True)
