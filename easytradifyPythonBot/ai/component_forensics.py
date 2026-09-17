# ai/component_forensics.py
"""
Component forensics: for every component of the analysis, WHY its trades won
or lost, measured on the real price path -- and what would fix it.

It joins three things per trade:
  * the component's reading at entry (ai/component_scorecard catalogue),
  * the market path from ai/trade_forensics (ticks, 8 h),
  * the component's reading at every in-trade price_evolution point.

PER COMPONENT, PER STATE
------------------------
  direction accuracy   Was the component right about the MARKET, whatever the
                       trade did? Its direction (ALIGNED = the trade's, OPPOSED
                       = the other) against which 5-ATR barrier price touched
                       first. 50% is a coin. This separates "bad signal" from
                       "good signal, bad trade".
  failure anatomy      How its trades ended: target, spread stop (mid never
                       reached the stop), noise stop (stopped, then went on to
                       the target), gave back (+1R first), wrong direction.
  drift                Mean favourable move at 15 / 60 / 240 min, in R.
  exits                Net R under fixed alternative exits, so a component
                       whose direction is right but whose trades lose is visible.
  flips                While the trade was open, did the component turn against
                       it? Loss rate after a flip, and what exiting at the flip
                       would have booked versus holding.

Every rate is split into the chronologically first and second half. A reading
that reverses between halves is not a fix; it is noise.

VERDICTS
--------
Rule-based, stated with the numbers that triggered them, and conservative: a
component is only called INVERTED or PREDICTIVE when the Wilson interval of its
direction accuracy excludes 50%.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from ai import component_scorecard as cs
from ai import trade_evaluation as te
from ai import trade_forensics as tf

COMPONENT_FORENSICS_VERSION = "1.0"
EXITS = ("1.0x|5.0", "2.0x|3.0", "3.0x|2.0", "5.0x|2.0", "5.0x|1.0")
ATR_EXITS = ("2.0atr|2.0", "3.0atr|2.0", "5.0atr|1.0", "5.0atr|2.0", "8.0atr|1.0")
CLASSES = ("WIN_TARGET", "LOSS_SPREAD_STOP", "LOSS_NOISE_STOP", "LOSS_GAVE_BACK",
           "LOSS_WRONG_DIRECTION", "LOSS_UNRESOLVED", "OPEN_AT_HORIZON")
MIN_N = 12


def wilson(k, n):
    lo, hi = te.wilson(k, n)
    return [lo, hi]


def _mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return round(statistics.mean(xs), 3) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


# ============================================================
# JOIN
# ============================================================

def build(trades=None) -> List[Dict[str, Any]]:
    from ai import trade_repository as repo
    if trades is None:
        trades = repo.load_trades()
    paths = {m["trade_id"]: m for m in tf.collect(trades)}
    rows = []
    for trade in trades:
        m = paths.get(trade.get("trade_id"))
        if not m:
            continue
        sign = 1 if trade["direction"] == "BUY" else -1
        rows.append({"trade": trade, "path": m, "sign": sign,
                     "analysis": trade.get("analysis_at_open") or {},
                     "opened_at": m["opened_at"]})
    rows.sort(key=lambda r: r["opened_at"])
    half = len(rows) // 2
    for i, r in enumerate(rows):
        r["half"] = 1 if i < half else 2
    return rows


def _fav_at(row, when_iso: str) -> Optional[float]:
    """Exit-side favourable R at a moment, from the cached ticks."""
    trade, path = row["trade"], row["path"]
    ticks = tf.load_ticks(trade["trade_id"], trade["symbol"], tf._utc(trade["opened_at"]))
    if ticks is None:
        return None
    t, bid, ask = ticks
    moment = tf._utc(when_iso)
    if moment is None:
        return None
    idx = int(np.searchsorted(t, moment.timestamp()))
    if idx >= t.size:
        return None
    price = trade["entry"]["price"]
    risk = abs(price - trade["entry"]["stop_loss"])
    px = bid[idx] if row["sign"] > 0 else ask[idx]
    return float(row["sign"] * (px - price) / risk)


# ============================================================
# ONE COMPONENT
# ============================================================

def _state_block(members: List[Dict[str, Any]], state: str, kind: str) -> Dict[str, Any]:
    n = len(members)
    paths = [m["path"] for m in members]
    block: Dict[str, Any] = {"state": state, "n": n, "small": n < MIN_N}

    # ---- direction accuracy
    if kind == "vote" and state in ("ALIGNED", "OPPOSED"):
        comp_dir = [(m["sign"] if state == "ALIGNED" else -m["sign"]) for m in members]
        label = "component"
    else:
        comp_dir = [m["sign"] for m in members]
        label = "trade"
    for barrier in (5, 2):
        right = wrong = 0
        by_half = {1: [0, 0], 2: [0, 0]}
        for m, d in zip(members, comp_dir):
            move = m["path"].get(f"market_{barrier}atr")
            if not move:
                continue
            ok = move == d
            right += ok
            wrong += not ok
            by_half[m["half"]][0 if ok else 1] += 1
        total = right + wrong
        block[f"accuracy_{barrier}atr"] = {
            "who": label, "right": right, "n": total,
            "rate": round(100 * right / total, 1) if total else None,
            "ci95": wilson(right, total) if total else None,
            "half1": round(100 * by_half[1][0] / sum(by_half[1]), 1) if sum(by_half[1]) else None,
            "half2": round(100 * by_half[2][0] / sum(by_half[2]), 1) if sum(by_half[2]) else None,
        }

    # ---- anatomy
    classes = Counter(p["class"] for p in paths)
    block["classes"] = {c: classes.get(c, 0) for c in CLASSES if classes.get(c)}
    wins = classes.get("WIN_TARGET", 0)
    block["win_rate"] = round(100 * wins / n, 1) if n else None
    stops = [p for p in paths if p["replay_result"] == "STOP"]
    block["stopped_then_reached_target"] = (round(100 * sum(1 for p in stops if p.get("after_stop") == "REACHED_TARGET")
                                                  / len(stops), 1) if stops else None)
    block["median_seconds_to_stop"] = _median([p["replay_seconds"] for p in stops])
    block["median_mfe_r"] = _median([p["mfe_r"] for p in paths])
    block["reached_1r_share"] = round(100 * sum(1 for p in paths if p["mfe_r"] >= 1) / n, 1) if n else None
    block["mae_first_30s"] = _median([p.get("mae_first_30s") for p in paths])
    block["risk_pips_median"] = _median([p["risk_pips"] for p in paths])

    # ---- drift in the component's direction (for votes) or the trade's
    for minutes in (15, 60, 240):
        vals = []
        for m, d in zip(members, comp_dir):
            v = m["path"].get(f"fav_{minutes}m")
            if v is not None:
                vals.append(v * (d * m["sign"]))
        block[f"drift_{minutes}m_r"] = _mean(vals)

    # ---- exits (trade direction, net of commission)
    exits = {}
    for key in EXITS:
        vals = [m["path"]["grid_net_r"].get(key) for m in members]
        h1 = [m["path"]["grid_net_r"].get(key) for m in members if m["half"] == 1]
        h2 = [m["path"]["grid_net_r"].get(key) for m in members if m["half"] == 2]
        exits[key] = {"all": _mean(vals), "half1": _mean(h1), "half2": _mean(h2)}
    for key in ATR_EXITS:
        vals = [(m["path"].get("grid_atr_net_r") or {}).get(key) for m in members]
        h1 = [(m["path"].get("grid_atr_net_r") or {}).get(key) for m in members if m["half"] == 1]
        h2 = [(m["path"].get("grid_atr_net_r") or {}).get(key) for m in members if m["half"] == 2]
        exits[key] = {"all": _mean(vals), "half1": _mean(h1), "half2": _mean(h2)}
    block["exits"] = exits
    best = max(((k, v) for k, v in exits.items() if v["all"] is not None), key=lambda kv: kv[1]["all"],
               default=(None, None))
    block["best_exit"] = {"exit": best[0], **(best[1] or {})}
    return block


def _flips(rows, reader) -> Dict[str, Any]:
    """Readings during the trade: how often the component turned, and what it meant."""
    flipped, steady = [], []
    exit_gain = []
    by_half = {1: [], 2: []}
    for row in rows:
        start = reader(row["analysis"], row["sign"])
        if start not in ("ALIGNED", "OPPOSED"):
            continue
        against = "OPPOSED" if start == "ALIGNED" else "ALIGNED"
        points = row["trade"].get("price_evolution") or []
        replay = row["path"]["grid_net_r"].get("1.0x|5.0")
        flip_at = None
        for point in points:
            m1 = ((point.get("analysis") or {}).get("m1")) or {}
            if not m1:
                continue
            try:
                state = reader(m1, row["sign"])
            except Exception:
                state = None
            if start == "ALIGNED" and state == "OPPOSED":
                flip_at = point.get("timestamp")
                break
        if start != "ALIGNED":
            continue
        if flip_at is None:
            steady.append(row)
            continue
        fav = _fav_at(row, flip_at)
        # Only a flip that happened BEFORE the trade was already over counts.
        opened = tf._utc(row["trade"]["opened_at"])
        seconds = (tf._utc(flip_at) - opened).total_seconds() if opened else None
        if seconds is None or seconds > row["path"]["replay_seconds"]:
            steady.append(row)
            continue
        flipped.append(row)
        if fav is not None and replay is not None:
            c = row["path"].get("commission_r") or 0
            gain = (fav - c) - replay
            exit_gain.append(gain)
            by_half[row["half"]].append(gain)

    def loss_rate(group):
        return round(100 * sum(1 for r in group if r["path"]["class"] != "WIN_TARGET") / len(group), 1) \
            if group else None

    return {"aligned_at_entry": len(flipped) + len(steady), "flipped": len(flipped),
            "loss_rate_flipped": loss_rate(flipped), "loss_rate_steady": loss_rate(steady),
            "exit_on_flip_gain_r": _mean(exit_gain),
            "exit_on_flip_gain_half1": _mean(by_half[1]), "exit_on_flip_gain_half2": _mean(by_half[2])}


def verdict(component: Dict[str, Any]) -> Dict[str, Any]:
    """What is wrong with the component, what the numbers say, what to change."""
    states = {s["state"]: s for s in component["states"]}
    findings, fixes = [], []
    status = "INCONCLUSIVE"

    if component["kind"] == "vote":
        voted = [s for k, s in states.items() if k in ("ALIGNED", "OPPOSED")]
        right = sum((s.get("accuracy_5atr") or {}).get("right", 0) for s in voted)
        total = sum((s.get("accuracy_5atr") or {}).get("n", 0) for s in voted)
        halves = {}
        for h in (1, 2):
            rr = nn = 0
            for s in voted:
                a = s.get("accuracy_5atr") or {}
                rate, n = a.get(f"half{h}"), a.get("n") or 0
                if rate is not None:
                    rr += rate * n / 100
                    nn += n
            halves[h] = round(100 * rr / nn, 1) if nn else None
        acc = round(100 * right / total, 1) if total else None
        lo, hi = te.wilson(right, total) if total else (None, None)
        component["direction_accuracy"] = {"rate": acc, "n": total, "ci95": [lo, hi],
                                           "half1_approx": halves[1], "half2_approx": halves[2]}
        al, op = states.get("ALIGNED"), states.get("OPPOSED")

        # LIFT: does agreeing with this component make the TRADE right more
        # often? A component that almost always agrees just inherits the
        # trades' own accuracy (59%), so absolute accuracy alone flatters it.
        a_acc = (al or {}).get("accuracy_5atr") or {}
        o_acc = (op or {}).get("accuracy_5atr") or {}
        if a_acc.get("n") and o_acc.get("n"):
            ka, na = a_acc["right"], a_acc["n"]
            ko, no = o_acc["n"] - o_acc["right"], o_acc["n"]          # trade right when opposed
            pa, po = ka / na, ko / no
            pooled = (ka + ko) / (na + no)
            se = math.sqrt(pooled * (1 - pooled) * (1 / na + 1 / no)) if 0 < pooled < 1 else None
            z = (pa - po) / se if se else 0.0
            p = math.erfc(abs(z) / math.sqrt(2))
            component["lift"] = {"trade_right_when_aligned": round(100 * pa, 1), "n_aligned": na,
                                 "trade_right_when_opposed": round(100 * po, 1), "n_opposed": no,
                                 "lift_pts": round(100 * (pa - po), 1), "p": round(p, 4)}

        if total < MIN_N:
            status = "TOO_RARE"
            findings.append(f"only {total} directional votes -- it almost never takes a side")
            fixes.append("Either widen its trigger so it votes, or stop spending probability weight on it.")
        elif hi is not None and hi < 50:
            status = "INVERTED"
            findings.append(f"called the market right {acc}% of the time (95% CI {lo}-{hi}%), n={total}")
            fixes.append("Its direction is backwards on this sample: invert the sign of its vote, "
                         "or remove it from the probability chain until re-tested on new trades.")
        elif lo is not None and lo > 50:
            status = "PREDICTIVE"
            findings.append(f"called the market right {acc}% of the time (95% CI {lo}-{hi}%), n={total}")
        else:
            status = "NO_DIRECTIONAL_EDGE"
            findings.append(f"direction accuracy {acc}% (95% CI {lo}-{hi}%) -- indistinguishable from a coin")
            fixes.append("Down-weight toward zero in the probability chain; it adds confidence without information.")

        lift = component.get("lift")
        if lift and min(lift["n_aligned"], lift["n_opposed"]) >= MIN_N:
            findings.append(f"trade direction right {lift['trade_right_when_aligned']}% when it agreed (n={lift['n_aligned']}) "
                            f"vs {lift['trade_right_when_opposed']}% when it disagreed (n={lift['n_opposed']}), "
                            f"lift {lift['lift_pts']:+.1f} pts, p={lift['p']}")
            if lift["p"] < 0.05 and lift["lift_pts"] > 0:
                status = "ADDS_EDGE" if status != "INVERTED" else status
                fixes.append("It separates good from bad entries: make agreement a REQUIRED condition "
                             "(or give it a large weight) rather than one vote among many.")
            elif lift["p"] < 0.05 and lift["lift_pts"] < 0:
                status = "INVERTED"
                fixes.append("Trades it agreed with went wrong more often than trades it opposed: "
                             "treat its agreement as a warning, or invert it.")
        elif status == "PREDICTIVE" and (not lift or (op or {}).get("n", 0) < MIN_N):
            status = "PREDICTIVE_BUT_ALWAYS_AGREES"
            findings.append("it nearly always agrees with the trade, so its accuracy is the trades' own; "
                            "it cannot filter anything")
            fixes.append("No weight change can help: it never disagrees. Remove it from the chain or "
                         "redefine it so it can say no.")

        if halves[1] is not None and halves[2] is not None and (halves[1] - 50) * (halves[2] - 50) < 0 \
                and abs(halves[1] - halves[2]) > 15:
            findings.append(f"accuracy reversed between halves ({halves[1]}% then {halves[2]}%)")
            if status in ("PREDICTIVE", "INVERTED"):
                status += "_UNSTABLE"

        if al and not al["small"]:
            stops_to_target = al.get("stopped_then_reached_target")
            spread = al["classes"].get("LOSS_SPREAD_STOP", 0)
            if spread >= 0.5 * al["n"]:
                findings.append(f"{spread}/{al['n']} trades it supported were stopped on the spread "
                                f"(mid never reached the stop); median stop {al['risk_pips_median']} pips, "
                                f"stopped after {al['median_seconds_to_stop']} s")
            if stops_to_target and stops_to_target >= 30:
                findings.append(f"{stops_to_target}% of its stopped trades later reached the target")
            be = al.get("best_exit") or {}
            base = (al["exits"].get("1.0x|5.0") or {}).get("all")
            if be.get("exit") and be.get("all") is not None and base is not None and be["all"] > base + 0.2:
                consistent = (be.get("half1") or -9) > (base or -9) and (be.get("half2") or -9) > (base or -9)
                findings.append(f"with it ALIGNED, exit {be['exit']} books {be['all']:+.2f}R vs {base:+.2f}R "
                                f"for the current bracket (halves {be.get('half1')}, {be.get('half2')})")
                if status == "PREDICTIVE" or consistent:
                    fixes.append(f"When this component drives the entry, place the stop at {be['exit'].split('|')[0]} "
                                 f"and the target at {be['exit'].split('|')[1]}R of the new stop.")
        if al and op and not al["small"] and not op["small"]:
            if (op.get("win_rate") or 0) > (al.get("win_rate") or 0) + 8:
                findings.append(f"trades it OPPOSED won {op['win_rate']}% vs {al['win_rate']}% when it agreed")

        fl = component.get("flips") or {}
        if (fl.get("flipped") or 0) >= MIN_N:
            g, g1, g2 = fl.get("exit_on_flip_gain_r"), fl.get("exit_on_flip_gain_half1"), \
                fl.get("exit_on_flip_gain_half2")
            findings.append(f"turned against {fl['flipped']}/{fl['aligned_at_entry']} trades mid-way; "
                            f"loss rate {fl['loss_rate_flipped']}% after a flip vs {fl['loss_rate_steady']}% without")
            if g is not None and g > 0.1 and (g1 or 0) > 0 and (g2 or 0) > 0:
                fixes.append(f"Exit when it turns against the trade: +{g:.2f}R per flipped trade versus holding, "
                             f"positive in both halves.")
    else:
        best_state = max(component["states"], key=lambda s: (s["exits"]["1.0x|5.0"]["all"] or -9) if not s["small"] else -9,
                         default=None)
        worst_state = min(component["states"], key=lambda s: (s["exits"]["1.0x|5.0"]["all"] or 9) if not s["small"] else 9,
                          default=None)
        status = "DESCRIPTIVE"
        for s in component["states"]:
            if s["small"]:
                continue
            a = s.get("accuracy_5atr") or {}
            if a.get("ci95") and a["ci95"][1] is not None and a["ci95"][1] < 50:
                findings.append(f"in state {s['state']} the TRADE direction was right only {a['rate']}% "
                                f"(CI {a['ci95'][0]}-{a['ci95'][1]}%), n={a['n']}")
                fixes.append(f"Do not take trades while {component['name']} is {s['state']}, "
                             f"pending confirmation on new trades.")
                status = "HAS_BAD_STATE"
            elif a.get("ci95") and a["ci95"][0] is not None and a["ci95"][0] > 50:
                findings.append(f"in state {s['state']} the trade direction was right {a['rate']}% "
                                f"(CI {a['ci95'][0]}-{a['ci95'][1]}%), n={a['n']}")
                status = "HAS_GOOD_STATE" if status == "DESCRIPTIVE" else status
        if best_state and worst_state and best_state is not worst_state:
            findings.append(f"best state {best_state['state']} ({best_state['exits']['1.0x|5.0']['all']:+.2f}R), "
                            f"worst {worst_state['state']} ({worst_state['exits']['1.0x|5.0']['all']:+.2f}R) "
                            f"under the current bracket")
    component["status"] = status
    component["findings"] = findings
    component["fixes"] = fixes
    return component


# ============================================================
# PLAYBOOK: exits, pre-registered rules, code diagnoses
# ============================================================

# Rules fixed BEFORE looking at their results (chosen from the per-component
# lift ranking, not from a search over combinations). Each is scored on the
# chronologically first and second half separately.
RULES = [
    ("All trades (current)", ()),
    ("Trend cascade aligned", ("Trend cascade M5-H4",)),
    ("H4 slope aligned", ("H4 slope",)),
    ("Family TREND aligned", ("Family score TREND",)),
    ("Liquidity sweeps aligned", ("Liquidity sweeps bias",)),
    ("Cascade + liquidity", ("Trend cascade M5-H4", "Liquidity sweeps bias")),
    ("H4 + liquidity", ("H4 slope", "Liquidity sweeps bias")),
    ("Cascade + MACD histogram", ("Trend cascade M5-H4", "MACD histogram")),
    ("Cascade + H4 + liquidity", ("Trend cascade M5-H4", "H4 slope", "Liquidity sweeps bias")),
]
PLAYBOOK_EXITS = ("1.0x|5.0", "2.0x|3.0", "5.0x|2.0", "3.0atr|2.0", "5.0atr|1.0", "8.0atr|1.0")

# What the code does, read from the source, next to what the paths measured.
CODE_DIAGNOSES = [
    {"id": "stop", "title": "Stops sized by the account, not the market",
     "components": ["Stop distance (pips)"],
     "files": ["core/calculations.py:341 calculate_lot_proper", "core/asset_analysis_config.py:85 SL_MIN_ATR_MULTIPLE",
               "core/asset_analysis.py:2485 _atr_stop_floor"],
     "cause": "The stop is $risk divided by the pip value of the largest lot the margin allows. More leverage "
              "allows a bigger lot, so the stop shrinks. The only market floors are 3x spread and 1.0x ATR, "
              "so on M1 majors the stop lands at ~1.1 ATR (1.3 pips median).",
     "change": "Raise SL_MIN_ATR_MULTIPLE from 1.0 to 3.0; the lot already scales down to keep dollar risk "
               "constant. Set the take-profit at 2R of the new stop instead of the hybrid target (median 6R)."},
    {"id": "cascade", "title": "Higher-timeframe trend is the strongest signal and is only a nudge",
     "components": ["Trend cascade M5-H4", "H4 slope", "Family score TREND"],
     "files": ["core/trend_cascade.py:70-71 TREND_CASCADE_MAX_BONUS/PENALTY", "core/trend_cascade.py:37 weights"],
     "cause": "A counter-cascade trade loses at most 18 probability points, applied after earlier steps "
              "that often push probability to the 95 clamp, so trades against the H1/H4 trend still clear "
              "the 75 entry threshold (27 of 88 cascade-decisive trades were against it).",
     "change": "Make cascade agreement decide direction: either take the trade only in the cascade's "
               "direction, or (no-veto option) flip to the cascade's side when they disagree. Raise the "
               "penalty so an opposed cascade cannot be outvoted."},
    {"id": "liquidity", "title": "Liquidity sweeps carry edge and have zero weight",
     "components": ["Liquidity sweeps bias"],
     "files": ["core/asset_analysis.py:5007 summarize_liquidity (display only)", "core/liquidity_events.py"],
     "cause": "Sweep bias is written into the output but never enters the probability chain; it only leaks in "
              "through order flow, where the order-block penalty overwhelms it.",
     "change": "Add a liquidity_events step to the confluence chain with a bonus when the sweep bias agrees "
               "and a penalty when it opposes, sized like the trend cascade."},
    {"id": "orderflow", "title": "Order flow is inverted by its exhausted-zone penalty",
     "components": ["Order flow", "Family score ORDER_FLOW", "Order block mitigation"],
     "files": ["core/order_flow_forensics.py:385 LIKELY_EXHAUSTED -> sign -1, magnitude 45"],
     "cause": "101 of 111 zones are classed LIKELY_EXHAUSTED, which adds a 45-point vote AGAINST the zone. "
              "On a trade taken at its own zone that flips order flow to OPPOSED; those trades were right "
              "63.8% of the time. The mitigation count over-counts touches across old history.",
     "change": "Drop the LIKELY_EXHAUSTED counter-vote (magnitude 0) until the mitigation count is re-based on "
               "touches after the zone formed; keep the stop-hunt term, which is the part that carries sign."},
    {"id": "weights", "title": "Indicator weights are the reverse of their measured value",
     "components": ["MACD", "MACD histogram", "RSI", "Trend indicator (EMA/ADX)"],
     "files": ["core/asset_analysis_config.py:537 regime favor/fade", "volatility_protection.trading_regime_weights_used"],
     "cause": "MACD adds +27 points of direction lift and has the smallest weight (0.039); RSI has the largest "
              "(0.126) and no measurable edge; in RANGING_CALM the trend-following group is faded to 0.6.",
     "change": "Move weight from RSI, stochastic, Bollinger and M1 trend to MACD; stop fading higher-timeframe "
               "trend evidence in ranging M1 regimes (the M1 regime label does not describe H1/H4)."},
    {"id": "rsi_adaptive", "title": "RSI adaptive fades moves that continue",
     "components": ["RSI adaptive", "Round numbers", "Wave C reversal", "Tick volume imbalance at entry"],
     "files": ["core/indicators.py adaptive RSI band", "indicators.round_numbers", "indicators.wave_c"],
     "cause": "These are reversal calls. When RSI adaptive opposed the trade the trade was right 65-73% in both "
              "regimes; round numbers and wave C were right about the market only 33-38%.",
     "change": "Remove their votes from the probability (or invert RSI adaptive into a momentum read). They are "
               "reversal logic on M1, where the measured behaviour is continuation."},
    {"id": "fvg", "title": "FVG and SMC structure scores push without predicting",
     "components": ["FVG / IFVG", "Family score FVG", "Family score SMC_STRUCTURE", "SMC premium / discount"],
     "files": ["core/asset_analysis_config.py:2279 FVG_IFVG_WEIGHT = 0.15", "final_verdict.pattern_final_score weight 20"],
     "cause": "FVG contributes up to 15 points and is aligned on 74 of 97 voting trades, yet trades it opposed were "
              "right more often (69.6% vs 55.4%). It raises probability on exactly the entries that stop out.",
     "change": "Cut FVG_IFVG_WEIGHT toward 0.05 and use the FVG as an entry LOCATION (where to wait for price), "
               "not as directional evidence."},
    {"id": "flips", "title": "Do not exit when a component turns",
     "components": [],
     "files": ["monitor/monitor_core.py close logic"],
     "cause": "Exiting when a component flipped against an open trade booked less than holding for almost every "
              "component; flips happen near the stop, after most of the loss is taken.",
     "change": "No flip-based exits. Manage the trade with the wider bracket instead."},
]


def opposite_side_exits(row, keys) -> Dict[str, Optional[float]]:
    """Net R had the trade been placed the OTHER way at the same moment.

    Entry at the opposite side of the book (bid for a sell, ask for a buy) at
    the first tick, same stop distance, same ATR, commission unchanged. This is
    what "flip to the cascade's direction instead of skipping" would have booked.
    """
    trade, path = row["trade"], row["path"]
    ticks = tf.load_ticks(trade["trade_id"], trade["symbol"], tf._utc(trade["opened_at"]))
    if ticks is None:
        return {}
    t, bid, ask = ticks
    keep = t >= tf._utc(trade["opened_at"]).timestamp()
    t, bid, ask = t[keep], bid[keep], ask[keep]
    if t.size < 3:
        return {}
    sign = -row["sign"]
    entry = ask[0] if sign > 0 else bid[0]
    risk = abs(trade["entry"]["price"] - trade["entry"]["stop_loss"])
    exit_px = bid if sign > 0 else ask
    fav = sign * (exit_px - entry) / risk
    c0 = path.get("commission_r") or 0.0
    atr_r = path.get("atr_r")
    out = {}
    for key in keys:
        stop_part, target = key.split("|")
        target = float(target)
        if stop_part.endswith("atr"):
            if not atr_r:
                continue
            k = float(stop_part[:-3]) * atr_r
        else:
            k = float(stop_part[:-1])
        r, _, _ = tf.barrier(fav, t, k, target * k, 0.0)
        out[key] = round(r / k - c0 / k, 4)
    return out


def _exit_value(row, key):
    grid = row["path"].get("grid_atr_net_r") if "atr" in key else row["path"]["grid_net_r"]
    return (grid or {}).get(key)


def playbook(rows) -> Dict[str, Any]:
    readers = {name: reader for name, _, _, reader, _ in cs.CATALOGUE}

    def state(row, name):
        try:
            return readers[name](row["analysis"], row["sign"])
        except Exception:
            return None

    rules = []
    for title, required in RULES:
        sel = [r for r in rows if all(state(r, n) == "ALIGNED" for n in required)]
        entry = {"rule": title, "requires": list(required), "n": len(sel),
                 "n_half1": sum(1 for r in sel if r["half"] == 1), "n_half2": sum(1 for r in sel if r["half"] == 2)}
        voted = [r for r in sel if r["path"].get("market_5atr")]
        entry["direction_right"] = round(100 * sum(1 for r in voted if r["path"]["market_5atr"] == r["sign"])
                                         / len(voted), 1) if voted else None
        entry["exits"] = {}
        for key in PLAYBOOK_EXITS:
            vals = {h: [v for r in sel if r["half"] == h and (v := _exit_value(r, key)) is not None] for h in (1, 2)}
            allv = vals[1] + vals[2]
            entry["exits"][key] = {
                "all": _mean(allv), "half1": _mean(vals[1]), "half2": _mean(vals[2]),
                "win_rate": round(100 * sum(1 for v in allv if v > 0) / len(allv), 1) if allv else None,
                "total_r": round(sum(allv), 1) if allv else None}
        rules.append(entry)

    # ---- the no-veto alternative: keep every trade, but when the cascade
    # disagrees, trade the cascade's side instead of the analysis's.
    flip = {"rule": "Every trade, flipped to the cascade's side when it disagrees",
            "requires": ["cascade decides direction"], "n": len(rows),
            "n_half1": sum(1 for r in rows if r["half"] == 1),
            "n_half2": sum(1 for r in rows if r["half"] == 2), "exits": {}}
    flipped_vals = {}
    for r in rows:
        if state(r, "Trend cascade M5-H4") == "OPPOSED":
            flipped_vals[r["trade"]["trade_id"]] = opposite_side_exits(r, PLAYBOOK_EXITS)
    flip["flipped_trades"] = len(flipped_vals)
    right = total = 0
    for r in rows:
        move = r["path"].get("market_5atr")
        if not move:
            continue
        side = -r["sign"] if r["trade"]["trade_id"] in flipped_vals else r["sign"]
        right += move == side
        total += 1
    flip["direction_right"] = round(100 * right / total, 1) if total else None
    for key in PLAYBOOK_EXITS:
        vals = {1: [], 2: []}
        for r in rows:
            v = (flipped_vals.get(r["trade"]["trade_id"]) or {}).get(key) \
                if r["trade"]["trade_id"] in flipped_vals else _exit_value(r, key)
            if v is not None:
                vals[r["half"]].append(v)
        allv = vals[1] + vals[2]
        flip["exits"][key] = {"all": _mean(allv), "half1": _mean(vals[1]), "half2": _mean(vals[2]),
                              "win_rate": round(100 * sum(1 for v in allv if v > 0) / len(allv), 1) if allv else None,
                              "total_r": round(sum(allv), 1) if allv else None}
    rules.append(flip)

    grid = []
    keys = list(rows[0]["path"]["grid_net_r"].keys()) + list((rows[0]["path"].get("grid_atr_net_r") or {}).keys())
    for key in keys:
        vals = {h: [v for r in rows if r["half"] == h and (v := _exit_value(r, key)) is not None] for h in (1, 2)}
        allv = vals[1] + vals[2]
        if len(allv) < len(rows) * 0.8:
            continue
        grid.append({"exit": key, "all": _mean(allv), "half1": _mean(vals[1]), "half2": _mean(vals[2]),
                     "win_rate": round(100 * sum(1 for v in allv if v > 0) / len(allv), 1)})
    grid.sort(key=lambda g_: -(g_["all"] or -9))

    paths = [r["path"] for r in rows]
    stops = [p for p in paths if p["replay_result"] == "STOP"]
    # The stored bracket re-run on the ticks must reproduce the booked result
    # on stop and target closes (manual/EA closes had no bracket exit).
    bracket = [r for r in rows if str((r["trade"].get("close_data") or {}).get("close_reason")) in
               ("STOP_LOSS", "TAKE_PROFIT")]
    agree = sum(1 for r in bracket
                if (r["path"]["replay_result"] == "TARGET")
                == (((r["trade"].get("close_data") or {}).get("profit_usd") or 0) > 0)
                and r["path"]["replay_result"] != "TIMEOUT")
    by_lev = defaultdict(list)
    for r in rows:
        by_lev[r["trade"].get("leverage")].append(r)
    return {
        "replay_agreement": {"agree": agree, "n": len(bracket)},
        "anatomy": dict(Counter(p["class"] for p in paths)),
        "after_stop": dict(Counter(p.get("after_stop") for p in stops)),
        "median_stop_pips": _median([p["risk_pips"] for p in paths]),
        "median_stop_atr": _median([p["risk_pips"] / (cs.g(r["analysis"], "volatility_protection.atr_pips") or 1)
                                    for r, p in zip(rows, paths)]),
        "median_seconds_to_stop": _median([p["replay_seconds"] for p in stops]),
        "median_commission_r": _median([p["commission_r"] for p in paths]),
        "median_entry_spread_r": _median([p["entry_spread_r"] for p in paths]),
        "median_mae_first_30s": _median([p.get("mae_first_30s") for p in paths]),
        "drift_mean_r": {m: _mean([p.get(f"fav_{m}m") for p in paths]) for m in (5, 15, 60, 240)},
        "leverage": [{"leverage": lev, "n": len(rs), "median_stop_pips": _median([r["path"]["risk_pips"] for r in rs]),
                      "spread_stops": sum(1 for r in rs if r["path"]["class"] == "LOSS_SPREAD_STOP")}
                     for lev, rs in sorted(by_lev.items(), key=lambda kv: str(kv[0]))],
        "rules": rules, "exit_grid": grid[:20],
        "exit_grid_current": [g_ for g_ in grid if g_["exit"].startswith("1.0x")],
        "diagnoses": CODE_DIAGNOSES,
    }


# ============================================================
# ENTRY POINT
# ============================================================

def evaluate(trades=None) -> Dict[str, Any]:
    rows = build(trades)
    report: Dict[str, Any] = {"component": "component_forensics", "version": COMPONENT_FORENSICS_VERSION,
                              "trades_with_paths": len(rows)}
    report["overall"] = _state_block(rows, "ALL", "state")

    components = []
    for name, cat, kind, reader, description in cs.CATALOGUE:
        groups = defaultdict(list)
        for row in rows:
            if name == "Session (UTC)":
                label = te._session(tf._utc(row["opened_at"]))
            else:
                try:
                    label = reader(row["analysis"], row["sign"])
                except Exception:
                    label = None
            if label is not None:
                groups[str(label)].append(row)
        if not groups:
            continue
        order = {"ALIGNED": 0, "NEUTRAL": 1, "OPPOSED": 2}
        states = [_state_block(members, state, kind)
                  for state, members in sorted(groups.items(), key=lambda kv: (order.get(kv[0], 3), -len(kv[1])))]
        comp = {"name": name, "category": cat, "kind": kind, "description": description,
                "coverage": sum(len(v) for v in groups.values()), "states": states}
        if kind == "vote" and name != "Session (UTC)":
            comp["flips"] = _flips(rows, reader)
        components.append(verdict(comp))
    report["components"] = components

    # ---- categories: roll-up of verdicts
    cats = []
    for cat, title in cs.CATEGORIES:
        members = [c for c in components if c["category"] == cat]
        cats.append({"category": cat, "title": title,
                     "statuses": dict(Counter(c["status"] for c in members)),
                     "predictive": [c["name"] for c in members if c["status"].startswith("PREDICTIVE")],
                     "inverted": [c["name"] for c in members if c["status"].startswith("INVERTED")],
                     "no_edge": [c["name"] for c in members if c["status"] == "NO_DIRECTIONAL_EDGE"]})
    report["categories"] = cats
    report["playbook"] = playbook(rows)
    return report


def get_status() -> Dict[str, Any]:
    return {"component": "component_forensics", "version": COMPONENT_FORENSICS_VERSION}


def self_check(trades=None) -> Dict[str, Any]:
    report: Dict[str, Any] = {"component": "component_forensics", "ok": None}
    fake = {"name": "x", "kind": "vote", "states": [
        {"state": "ALIGNED", "n": 40, "small": False, "classes": {}, "exits": {"1.0x|5.0": {"all": -0.5}},
         "accuracy_5atr": {"right": 10, "n": 40, "half1": 25.0, "half2": 25.0}},
        {"state": "OPPOSED", "n": 40, "small": False, "classes": {}, "exits": {"1.0x|5.0": {"all": 0.2}},
         "accuracy_5atr": {"right": 10, "n": 40, "half1": 25.0, "half2": 25.0}}], "flips": {}}
    checks = {"planted_inversion_found": verdict(fake)["status"] == "INVERTED"}
    report["checks"] = checks
    if not trades:
        report["reason"] = "no trades supplied; verdict logic checked only"
        return report
    usable = [t for t in trades if isinstance(t, Mapping) and (t.get("entry") or {}).get("stop_loss")
              and t.get("direction") in ("BUY", "SELL")]
    if not usable:
        report["ok"] = False
        report["reason"] = "no trade with direction, entry and stop -- nothing to join to a path"
        return report
    report["ok"] = all(checks.values())
    return report


if __name__ == "__main__":
    import logging
    import sys
    logging.disable(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = evaluate()
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    with open(os.path.join(folder, "component_forensics.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, default=str)
    print("saved reports/component_forensics.json")

    if "--html" in sys.argv:
        template = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates",
                                "component_forensics.html")
        with open(template, encoding="utf-8") as handle:
            page = handle.read()
        # Per-state 2-ATR accuracy is not shown on the page; drop it to keep the page light.
        for comp in result["components"]:
            for st in comp["states"]:
                st.pop("accuracy_2atr", None)
        data = json.dumps(result, separators=(",", ":"), default=str).replace("</", "<" + chr(92) + "/")
        with open(os.path.join(folder, "component_forensics.html"), "w", encoding="utf-8") as handle:
            handle.write(page.replace("__DATA__", data))
        print("saved reports/component_forensics.html")
