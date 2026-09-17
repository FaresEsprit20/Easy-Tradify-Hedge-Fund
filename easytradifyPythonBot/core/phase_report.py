#!/usr/bin/env python3
# ============================================================
# PHASED VALIDATION REPORT  (Phase 0)
# ============================================================
# FILE: core/phase_report.py
#
# Implements replay_backtest_strategy.md, Phase 0, over the
# records core/run_replay.py writes.
#
#     python -m core.phase_report rec_EURUSD_M15.json
#     python -m core.phase_report rec_*.json --out phase0_report.txt
#
# ---- SECTION 1: EXPECTANCY IS THE METRIC, NOT WIN RATE ----
#
#     expectancy_R = win_rate x avg_win_R - loss_rate x avg_loss_R
#
# Win rate alone is meaningless without its paired R:R, and it can be
# gamed by loosening R:R until a coin flip looks like a system. Every
# number below is reported with its breakeven win rate beside it, which
# is 1 / (1 + reward multiple): 33.3% at 1:2, 25% at 1:3. A 60% win rate
# at 1:0.5 is worse than a 35% win rate at 1:3.
#
# ---- SECTION 2: THE WIN-RATE DEFINITION, LOCKED ----
#
#     win rate = wins / (wins + losses)
#
# Scratches are tracked and reported as their OWN rate. They are not
# folded into wins, into losses, or into the denominator. This keeps two
# separate questions separate -- "did the direction call hold up" and
# "did risk management avoid a loss" -- and lets them recombine only in
# expectancy, where both belong.
#
# A trade is a SCRATCH if it exits via the breakeven stop with realized
# R between -0.1 and +0.1. Phase 0 predates the breakeven
# rule, so its scratch count is structurally 0; the machinery is here
# because the definition must be locked BEFORE Phase 4 moves the number,
# not after, or the change in measured win rate cannot be told apart
# from a change in the system.
#
# ---- WHICH TRADES ARE COUNTED (and why the shadow universe) ----
#
# Two universes, both reported:
#
#   TAKEN   the trades the live engine actually entered. This is what
#           "the current system as it runs today" literally means, and
#           it is the honest headline -- but on this build it produces a
#           handful of trades per symbol, far under Phase 0's 100-trade
#           exit criterion, so it cannot carry a win rate.
#
#   SHADOW  the trade the engine COMPUTED at every decision, taken or
#           not, walked forward against real bars. Thousands per symbol.
#
# A universe of 2 trades answers nothing. So SHADOW is the Phase 0
# baseline, and TAKEN is reported beside it so the gap between "what the
# engine can see" and "what the engine takes" stays visible rather than
# being quietly replaced by the larger, more flattering number.
# ============================================================

import argparse
import glob
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Section 2: the scratch band, in R. Wide enough to absorb spread and
# slippage noise around exact breakeven, narrow enough that a real win
# or loss never lands inside it.
SCRATCH_BAND = 0.1

# Section 8's interim milestone.
TARGET_WIN_RATE = 0.60
TARGET_RR = 2.0


def _f(x) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _g(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


# ============================================================
# RECORDS -> TRADES
# ============================================================
def extract_trades(records: List[Dict[str, Any]], *, universe: str = "shadow",
                   net_of_spread: bool = True) -> List[Dict[str, Any]]:
    """
    One replay record -> at most one trade row, with everything section 4
    asks to be logged.

    UNRESOLVED and INVALID rows are dropped from the trade list but
    counted in the returned rows' absence -- a trade that never reached
    either level is not a win, a loss, or a scratch, and folding it into
    any of the three would put a number where an unknown belongs.
    """
    out: List[Dict[str, Any]] = []
    for rec in records:
        if universe == "taken":
            if not rec.get("entry_triggered"):
                continue
            outcome = rec.get("outcome") or {}
            plan = {"direction": rec.get("direction"),
                    "entry_price": rec.get("entry_price"),
                    "stop_loss": rec.get("stop_loss"),
                    "take_profit": rec.get("take_profit"),
                    "planned_rr": rec.get("planned_rr")}
        else:
            outcome = rec.get("shadow") or {}
            plan = rec.get("shadow_plan") or {}
        if not outcome or not plan:
            continue

        kind = outcome.get("outcome")
        if kind not in ("WIN", "LOSS"):
            continue

        r = _f(outcome.get("r_multiple_net") if net_of_spread
               else outcome.get("r_multiple"))
        if r is None:
            continue

        cap = rec.get("capture") or {}

        # Section 2's classification. Until Phase 4 arms a breakeven stop
        # nothing exits at breakeven, so `scratch` is False on every row
        # here by construction -- computed anyway so the definition is
        # already in force when the exits that can trigger it appear.
        exited_at_be = bool(outcome.get("exited_at_breakeven"))
        scratch = exited_at_be and abs(r) <= SCRATCH_BAND

        out.append({
            "symbol": rec.get("symbol"),
            "timestamp": _f(rec.get("decision_timestamp")),
            "decision_index": rec.get("decision_index"),
            # plan
            "direction": plan.get("direction"),
            "entry_price": _f(plan.get("entry_price")),
            "stop_loss": _f(plan.get("stop_loss")),
            "take_profit": _f(plan.get("take_profit")),
            "planned_rr": _f(plan.get("planned_rr")),
            # outcome
            "outcome": kind,
            "scratch": scratch,
            "r": r,
            "r_gross": _f(outcome.get("r_multiple")),
            "bars_held": outcome.get("bars_held"),
            # Needed to express spread as a fraction of the trade's own
            # risk. Without it a pip cost cannot be compared across
            # symbols or across stop distances.
            "risk_pips": _f(outcome.get("risk_pips")),
            # section 4 instrumentation
            "mfe_r": _f(outcome.get("mfe_r")),
            "mae_r": _f(outcome.get("mae_r")),
            "reached_1r": outcome.get("reached_1r"),
            "bars_to_1r": outcome.get("bars_to_1r"),
            "session": _g(rec, "session", "session", default="UNKNOWN"),
            "utc_hour": _g(rec, "session", "utc_hour"),
            "regime": cap.get("regime"),
            "probability": _f(cap.get("probability")),
            "atr_pips": _f(cap.get("atr_pips")),
            "spread_pips": _f(cap.get("spread_pips")),
            # Live-gate inputs. Carried so the cost of each gate can be
            # measured against the trades the calibrated filter WANTS,
            # rather than against the undifferentiated universe.
            "signal_count": _f(cap.get("signal_count")),
            "discount_at_zone": cap.get("discount_at_zone"),
            "discount_quality": cap.get("discount_quality"),
            "timing_ready": cap.get("timing_ready"),
            "veto_triggered": cap.get("veto_triggered"),
            "rr_ratio": _f(cap.get("rr_ratio")),
            "conviction_passed": cap.get("conviction_passed"),
            "gnn_conflict": cap.get("gnn_conflict"),
            "liquidity_aligned": cap.get("liquidity_aligned"),
            "zone_expected_direction": cap.get("zone_expected_direction"),
            "premium_position_pct": _f(cap.get("premium_position_pct")),
        })
    return out


# ============================================================
# SECTION 1 + 2: THE METRIC BLOCK
# ============================================================
def metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Every number the roadmap reports, computed one way, in one place.

    Note what the win-rate denominator is and is not: scratches are
    excluded from it entirely (section 2), so `n` and
    `wins + losses` are deliberately allowed to differ.
    """
    n = len(trades)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "scratches": 0,
                "win_rate": None, "scratch_rate": None, "expectancy": None,
                "avg_win": None, "avg_loss": None, "total_r": 0.0,
                "avg_planned_rr": None, "breakeven_win_rate": None,
                "edge_points": None, "max_drawdown": None,
                "profit_factor": None, "mfe_r_median": None,
                "mae_r_median": None, "reached_1r_rate": None}

    scratches = [t for t in trades if t["scratch"]]
    decisive = [t for t in trades if not t["scratch"]]
    wins = [t for t in decisive if t["r"] > 0]
    losses = [t for t in decisive if t["r"] <= 0]

    wl = len(wins) + len(losses)
    win_rate = (len(wins) / wl) if wl else None
    avg_win = (sum(t["r"] for t in wins) / len(wins)) if wins else None
    avg_loss = (abs(sum(t["r"] for t in losses)) / len(losses)) if losses else None

    # Section 1's formula, over the decisive trades. Scratches carry
    # their own (near-zero) R into total_r and into the per-trade
    # expectancy below, but never into the win rate.
    if win_rate is not None:
        expectancy = (win_rate * (avg_win or 0.0)
                      - (1.0 - win_rate) * (avg_loss or 0.0))
    else:
        expectancy = None

    rrs = [t["planned_rr"] for t in trades if t["planned_rr"]]
    avg_rr = (sum(rrs) / len(rrs)) if rrs else None
    be = (1.0 / (1.0 + avg_rr)) if avg_rr else None

    gross_win = sum(t["r"] for t in wins)
    gross_loss = abs(sum(t["r"] for t in losses))

    def _median(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        m = len(vals) // 2
        return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0

    reached = [t["reached_1r"] for t in trades if t["reached_1r"] is not None]

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        "win_rate": win_rate,
        "scratch_rate": len(scratches) / n,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_r": sum(t["r"] for t in trades),
        "avg_planned_rr": avg_rr,
        "breakeven_win_rate": be,
        "edge_points": ((win_rate - be) * 100.0
                        if (win_rate is not None and be is not None) else None),
        "max_drawdown": _max_drawdown([t["r"] for t in
                                       sorted(trades, key=lambda x: x["timestamp"] or 0)]),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "mfe_r_median": _median([t["mfe_r"] for t in trades]),
        "mae_r_median": _median([t["mae_r"] for t in trades]),
        "mfe_r_median_losses": _median([t["mfe_r"] for t in losses]),
        "mae_r_median_wins": _median([t["mae_r"] for t in wins]),
        "reached_1r_rate": (sum(1 for r in reached if r) / len(reached)) if reached else None,
        "reached_1r_then_lost": _reached_1r_then_lost(trades),
    }


def _max_drawdown(r_sequence: List[float]) -> Optional[float]:
    if not r_sequence:
        return None
    peak = equity = 0.0
    worst = 0.0
    for r in r_sequence:
        equity += r
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 2)


def _reached_1r_then_lost(trades: List[Dict[str, Any]]) -> Optional[float]:
    """
    Of the trades that ever reached 1R in unrealized profit, what
    fraction still finished as losses.

    This is Phase 4's headline number computed three phases early,
    because it is free once MFE is logged and it is the ONLY thing that
    decides whether a breakeven stop can help: if this fraction is small,
    breakeven mostly cuts winners short for nothing.
    """
    got = [t for t in trades if t.get("reached_1r")]
    if not got:
        return None
    return sum(1 for t in got if t["r"] <= 0) / len(got)


# ============================================================
# SEQUENTIAL EXECUTION -- THE ONLY TRADEABLE MEASURE
# ============================================================
# The shadow universe evaluates a trade at EVERY decision. On an M15
# replay that is one every 15 M1 bars, while the median trade holds ~79
# bars -- so roughly five positions are open at once, all of them riding
# the same move.
#
# That inflates results twice over, and the second way is the dangerous
# one:
#
#   1. TOTAL R is multiplied, because one favourable move is banked by
#      every overlapping trade that was open across it. Obvious once
#      stated, and easy to discount for.
#
#   2. PER-TRADE EXPECTANCY is also inflated, which is not obvious at
#      all. Winning moves are long enough to accumulate many overlapping
#      entries; losses resolve at the stop and accumulate fewer. So the
#      overlapping sample is quietly weighted toward winners, and the
#      average looks better than any tradeable sequence of the same
#      signals. On USDCHF this was the difference between +0.228R and
#      +0.007R -- the entire apparent edge.
#
# A real account cannot hold 100 correlated positions, so neither can an
# honest measurement. This walks the signals in time order and takes one
# only when the previous has closed. It is pessimistic in one respect --
# a real system might hold two or three uncorrelated positions -- but it
# is the floor, and the floor is what a decision to risk money needs.
# ============================================================

def sequential_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    One position at a time: take a signal only once the previous trade
    has closed. Order is by decision index, so the walk matches how the
    signals would actually have arrived.
    """
    ordered = sorted(trades, key=lambda t: (t.get("decision_index") or 0))
    out: List[Dict[str, Any]] = []
    busy_until = -1
    for t in ordered:
        start = t.get("decision_index")
        if start is None or start <= busy_until:
            continue
        out.append(t)
        busy_until = start + (t.get("bars_held") or 0)
    return out


def concentration(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    How much of the result rests on a handful of trades.

    A total that depends on its best three trades is not an edge, it is
    three lucky draws with a lot of noise around them -- and it will not
    repeat. Reported beside every sequential number for that reason.
    """
    rs = sorted((t["r"] for t in trades), reverse=True)
    total = sum(rs)
    out = {"n": len(rs), "total_r": total}
    for k in (1, 3, 5):
        out[f"top{k}_r"] = sum(rs[:k]) if len(rs) >= k else None
        out[f"top{k}_share"] = ((sum(rs[:k]) / total) if (total > 0 and len(rs) >= k)
                                else None)
    return out


# ============================================================
# SECTION 6: WALK-FORWARD DISCIPLINE
# ============================================================
def split_walk_forward(trades: List[Dict[str, Any]], frac: float = 0.5
                       ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Chronological split: tune on the earlier window, confirm on the later
    one. Never random -- a random split leaks the future into the tuning
    set through overlapping market conditions, and the whole point of
    section 6 is that a result found on one window has to survive a
    window it was not found on.
    """
    ordered = sorted(trades, key=lambda t: t["timestamp"] or 0)
    cut = int(len(ordered) * frac)
    return ordered[:cut], ordered[cut:]


# ============================================================
# PHASE 0
# ============================================================
def phase0(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Baseline. The current system, replayed unchanged, fully instrumented.

    Produces the "before" numbers every later phase is compared against.
    Nothing after this means anything without it.
    """
    shadow = extract_trades(records, universe="shadow")
    taken = extract_trades(records, universe="taken")

    unresolved = sum(1 for r in records
                     if (r.get("shadow") or {}).get("outcome") == "UNRESOLVED")
    invalid = sum(1 for r in records
                  if (r.get("shadow") or {}).get("outcome") == "INVALID")

    by_session: Dict[str, Any] = {}
    for t in shadow:
        by_session.setdefault(t["session"], []).append(t)
    by_regime: Dict[str, Any] = {}
    for t in shadow:
        by_regime.setdefault(str(t["regime"]), []).append(t)

    exit_ok = len(shadow) >= 100
    return {
        "phase": 0,
        "decisions": len(records),
        "shadow": metrics(shadow),
        "taken": metrics(taken),
        "unresolved": unresolved,
        "invalid": invalid,
        "by_session": {k: metrics(v) for k, v in sorted(by_session.items())},
        "by_regime": {k: metrics(v) for k, v in sorted(by_regime.items())},
        "instrumentation": _instrumentation_audit(records, shadow),
        "exit_criteria_met": exit_ok,
        "exit_criteria_note": (
            f"{len(shadow)} shadow trades logged "
            f"({'>= 100, criterion met' if exit_ok else '< 100, criterion NOT met'}"
            f"{'; 300+ target ' + ('met' if len(shadow) >= 300 else 'not met')})"
            f"; {len(taken)} actually taken by the live gates"),
    }


def _instrumentation_audit(records: List[Dict[str, Any]],
                           trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Did section 4 actually get logged? A phase that silently lost half
    its instrumentation still prints a clean-looking report, and the
    absence is only discovered when Phase 2 tries to slice on a field
    that is None everywhere.
    """
    n = max(1, len(trades))
    return {
        "mfe_logged_pct": 100.0 * sum(1 for t in trades if t["mfe_r"] is not None) / n,
        "mae_logged_pct": 100.0 * sum(1 for t in trades if t["mae_r"] is not None) / n,
        "session_logged_pct": 100.0 * sum(1 for t in trades
                                          if t["session"] != "UNKNOWN") / n,
        "bars_to_1r_logged_pct": 100.0 * sum(1 for t in trades
                                             if t["reached_1r"] is not None) / n,
    }


# ============================================================
# DISTRIBUTION HELPERS
# ============================================================


def _count(values) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _distribution(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    s = sorted(values)

    def pct(p):
        return round(s[min(len(s) - 1, int(len(s) * p))], 3)
    return {"n": len(s), "min": round(s[0], 3), "p25": pct(0.25),
            "median": pct(0.5), "p75": pct(0.75), "p90": pct(0.90),
            "p99": pct(0.99), "max": round(s[-1], 3)}


# ============================================================
# TARGET CURVE -- BUYING WIN RATE WITH R:R, HONESTLY
# ============================================================
# Section 4 of the roadmap says MFE exists to answer "whether a tighter
# target would have caught more wins before reversal -- the empirical
# way to check an R:R change, rather than guessing". This is that check.
#
# HOW A TIGHTER TARGET IS RE-SCORED, AND WHY IT IS EXACT
#
# MFE is recorded from entry up to and including the bar that resolved
# the trade, so for any target T no wider than the one actually used:
#
#   original WIN            -> still a win at T. It reached the original
#                              target without being stopped, so it passed
#                              through T first.
#   original LOSS, MFE >= T -> becomes a WIN at T. The excursion happened
#                              at or before the stop bar, because the
#                              trade ended there.
#   original LOSS, MFE <  T -> still a loss.
#
# No assumption is smuggled in and nothing is extrapolated. The one
# residual is same-bar ambiguity, where T and the stop sit inside one
# bar's range; the harness already resolves that pessimistically for the
# original target and the same pessimism carries through here.
#
# WIDER targets cannot be evaluated this way and are not offered. That
# would need price data past the exit, which was never recorded, and
# guessing it is exactly what this function exists to avoid.
#
# WHAT THE CURVE IS FOR
#
# Win rate and expectancy move in OPPOSITE directions along it. A
# shorter target converts near-misses into wins and raises the win rate;
# each win is worth less. There is no single right answer -- a higher
# win rate is worth paying for if it is what makes a system possible to
# hold through a drawdown, and a system abandoned mid-drawdown returns
# nothing regardless of its expectancy. The curve makes that a priced
# choice instead of an argument.
# ============================================================

def target_curve(trades: List[Dict[str, Any]],
                 targets: Tuple[float, ...] = (0.75, 1.0, 1.25, 1.5, 1.75,
                                               2.0, 2.25, 2.5),
                 charge_spread: bool = True
                 ) -> List[Dict[str, Any]]:
    """
    Win rate and expectancy at each target, with the stop fixed at 1R.

    SPREAD IS CHARGED, and at short targets it is the difference between
    a real result and a flattering one. MFE is recorded from raw prices,
    so a trade whose gross excursion reaches 0.75R did NOT net 0.75R --
    it netted 0.75R minus the spread it paid to get in and out. On a
    20-pip stop with a 1.5-pip spread that is 0.075R, which against a
    +0.2R expectancy is a third of the edge.

    The distortion is worst exactly where the win rate looks best, so a
    curve without this correction argues hardest for the target that
    survives contact with a broker least well.
    """
    usable = [t for t in trades if t.get("mfe_r") is not None]
    if not usable:
        return []

    rows = []
    for T in targets:
        wins = losses = 0
        gross = 0.0
        cost = 0.0
        # A trade can only speak about targets no wider than the one it
        # actually ran to. It EXITED at its own target, so MFE stops
        # there and says nothing about whether price would have carried
        # further -- crediting such an exit as a win at a wider target
        # invents a move that was never observed.
        #
        # This is not hypothetical: GBPUSD's average planned target is
        # ~2.06R, and 29.3% of trades reach 2.0R while only 1.8% reach
        # 2.5R. That cliff is the truncation, not the market, and
        # scoring T=2.5 against it produced a large fake edge.
        priced = [t for t in usable
                  if t.get("planned_rr") is None or T <= t["planned_rr"] + 1e-9]
        if len(priced) < max(20, 0.5 * len(usable)):
            continue
        for t in priced:
            # Spread as a fraction of the trade's own risk, which is what
            # makes it comparable across symbols and stop distances.
            # The replay evaluates outcomes with spread_pips=0 unless
            # --spread is passed, so r_gross and r_net are IDENTICAL on
            # these records and their difference is not a spread charge.
            # Relying on it silently priced every trade at zero cost.
            # The real per-bar spread is captured separately, so charge
            # from that and fall back to the harness difference only if
            # it is actually non-zero.
            sc = 0.0
            if charge_spread:
                r_gross, r_net = t.get("r_gross"), t.get("r")
                if r_gross is not None and r_net is not None and r_gross != r_net:
                    sc = max(0.0, r_gross - r_net)
                else:
                    sp, risk = t.get("spread_pips"), t.get("risk_pips")
                    if sp and risk:
                        sc = max(0.0, sp / risk)
            cost += sc

            if t["outcome"] == "WIN" or t["mfe_r"] >= T:
                wins += 1
                gross += T
            else:
                losses += 1
                gross -= 1.0
        n = wins + losses
        if n == 0:
            continue
        wr = wins / n
        exp = (gross - cost) / n
        coverage = len(priced) / len(usable)
        avg_cost = cost / n
        # Breakeven rises once the spread has to be paid out of each win.
        be = (1.0 + avg_cost) / (1.0 + T) if T > -1 else None
        rows.append({
            "target_r": T, "n": n, "wins": wins, "losses": losses,
            "win_rate": wr,
            "breakeven_win_rate": be,
            "edge_points": ((wr - be) * 100.0) if be is not None else None,
            "expectancy": exp,
            "avg_spread_r": avg_cost,
            "coverage": coverage,
            "total_r": exp * n,
        })
    return rows


def format_target_curve(rows: List[Dict[str, Any]], label: str) -> str:
    out = [
        "",
        "=" * 78,
        f"TARGET CURVE -- what each R:R buys, from MFE   {label}",
        "=" * 78,
        "  Stop fixed at 1R; only the target moves. Re-scored from recorded",
        "  MFE, so these are measured outcomes, not projections.",
        "",
        f"  {'target':>7} {'win rate':>9} {'breakeven':>10} {'edge pts':>9} "
        f"{'exp R':>9} {'total R':>9}",
    ]
    for r in rows:
        out.append(
            f"  {'1:' + format(r['target_r'], '.2f'):>7} {_pct(r['win_rate']):>9} "
            f"{_pct(r['breakeven_win_rate']):>10} {r['edge_points']:>+9.1f} "
            f"{_r(r['expectancy']):>9} {r['total_r']:>+9.1f}")
    if rows:
        best = max(rows, key=lambda r: r["expectancy"])
        out += ["",
                f"  Most profitable target: 1:{best['target_r']:.2f} "
                f"({_pct(best['win_rate'])} win, {_r(best['expectancy'])} per trade)"]
    return "\n".join(out)


# ============================================================
# FORMATTING
# ============================================================
def _pct(x, nd=1):
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def _r(x, nd=4):
    return "n/a" if x is None else f"{x:+.{nd}f}"


def _num_or_na(x, fmt: str = "{:.3f}") -> str:
    return "n/a" if x is None else fmt.format(x)


def _metric_lines(m: Dict[str, Any], indent: str = "  ") -> List[str]:
    if m["n"] == 0:
        return [indent + "no trades"]

    avg_loss = _num_or_na(None if m["avg_loss"] is None else -m["avg_loss"])
    rr = ("n/a" if m["avg_planned_rr"] is None
          else f"1:{m['avg_planned_rr']:.2f}")
    edge = _num_or_na(m["edge_points"], "{:+.2f}")
    pf = _num_or_na(m["profit_factor"])
    return [
        f"{indent}trades:              {m['n']}  "
        f"(wins {m['wins']} / losses {m['losses']} / scratches {m['scratches']})",
        f"{indent}WIN RATE:            {_pct(m['win_rate'])}"
        f"   [wins / (wins + losses); scratches excluded from the denominator]",
        f"{indent}scratch rate:        {_pct(m['scratch_rate'])}",
        f"{indent}EXPECTANCY:          {_r(m['expectancy'])} R per trade",
        f"{indent}avg win / avg loss:  {_r(m['avg_win'], 3)}R / {avg_loss}R",
        f"{indent}avg planned R:R:     {rr}"
        f"   breakeven win rate {_pct(m['breakeven_win_rate'])}",
        f"{indent}edge over breakeven: {edge} points",
        f"{indent}total R / max DD:    {m['total_r']:+.2f} / {m['max_drawdown']}",
        f"{indent}profit factor:       {pf}",
        f"{indent}MFE median  all/losers:  "
        f"{m['mfe_r_median']} / {m['mfe_r_median_losses']} R",
        f"{indent}MAE median  all/winners: "
        f"{m['mae_r_median']} / {m['mae_r_median_wins']} R",
        f"{indent}reached 1R:          {_pct(m['reached_1r_rate'])}"
        f"   of those, finished as losses: {_pct(m['reached_1r_then_lost'])}",
    ]


def _slice_table(by: Dict[str, Any], label: str, min_n: int = 20) -> List[str]:
    """
    Section 4/Phase 2 groundwork: the same metric block per slice, with
    thin slices shown but marked, never silently dropped. A 6-trade slice
    with a 67% win rate is noise, and it looks exactly like an edge until
    its `n` is printed beside it.
    """
    lines = [f"  {label:<22} {'n':>6} {'win%':>7} {'exp R':>9} {'avgRR':>7}"]
    for k, m in sorted(by.items(), key=lambda kv: -(kv[1]["n"])):
        if m["n"] == 0:
            continue
        flag = "" if m["n"] >= min_n else "   (too few to judge)"
        rr = "n/a" if m["avg_planned_rr"] is None else f"{m['avg_planned_rr']:.2f}"
        lines.append(f"  {k:<22} {m['n']:>6} {_pct(m['win_rate']):>7} "
                     f"{_r(m['expectancy']):>9} {rr:>7}{flag}")
    return lines


def format_phase0(p0: Dict[str, Any], symbol: str) -> str:
    ins = p0["instrumentation"]
    out = [
        "=" * 74,
        f"PHASE 0 -- BASELINE & INSTRUMENTATION    {symbol}",
        "=" * 74,
        "  The current system, replayed unchanged. No logic was modified.",
        "",
        f"  decisions replayed:  {p0['decisions']}",
        f"  unresolved / invalid: {p0['unresolved']} / {p0['invalid']}"
        f"   (excluded from every rate -- not wins, not losses)",
        "",
        "  -- INSTRUMENTATION AUDIT (section 4) --",
        f"     MFE logged:        {ins['mfe_logged_pct']:.1f}%",
        f"     MAE logged:        {ins['mae_logged_pct']:.1f}%",
        f"     session tagged:    {ins['session_logged_pct']:.1f}%",
        f"     1R-touch logged:   {ins['bars_to_1r_logged_pct']:.1f}%",
        "",
        "  -- UNIVERSE A: TRADES THE LIVE ENGINE ACTUALLY TOOK --",
    ]
    out += _metric_lines(p0["taken"], "     ")
    out += [
        "",
        "  -- UNIVERSE B: SHADOW (every computed setup, walked forward) --",
        "     This is the Phase 0 BASELINE.",
    ]
    out += _metric_lines(p0["shadow"], "     ")
    out += [
        "",
        "  -- BY SESSION (Phase 2 groundwork) --",
    ]
    out += _slice_table(p0["by_session"], "session")
    out += ["", "  -- BY TRADING REGIME (Phase 2 groundwork) --"]
    out += _slice_table(p0["by_regime"], "regime")
    out += [
        "",
        f"  EXIT CRITERIA: {p0['exit_criteria_note']}",
        f"  -> {'MET' if p0['exit_criteria_met'] else 'NOT MET'}",
    ]
    return "\n".join(out)


def run(paths: List[str]) -> str:
    """Phase 0 per symbol (section 7: results do not automatically transfer
    between instruments). Phase 1 measured the family-voting filter, which
    was removed on 2026-09-15."""
    chunks: List[str] = []
    summary: List[Tuple[str, Any, Any]] = []

    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        records = blob.get("records") or []
        symbol = (records[0].get("symbol") if records else None) or os.path.basename(path)

        p0 = phase0(records)
        chunks.append(format_phase0(p0, symbol))
        chunks.append("")
        summary.append((symbol, p0["shadow"], p0["exit_criteria_met"]))

    head = [
        "=" * 74,
        "PHASE 0 REPORT",
        "replay_backtest_strategy.md -- expectancy is the metric;",
        "win rate = wins / (wins + losses), scratches reported separately.",
        "=" * 74,
        "",
        f"  {'symbol':<12} {'base n':>7} {'base win':>9} {'base exp':>10}  P0",
    ]
    for sym, b, ok0 in summary:
        head.append(
            f"  {sym:<12} {b['n']:>7} {_pct(b['win_rate']):>9} "
            f"{_r(b['expectancy']):>10}  {'ok' if ok0 else 'NO'}")
    head.append("")
    return "\n".join(head) + "\n" + "\n".join(chunks)


def main():
    ap = argparse.ArgumentParser(
        description="Phase 0 of replay_backtest_strategy.md")
    ap.add_argument("records", nargs="+",
                    help="replay records JSON file(s), e.g. rec_EURUSD_M15.json")
    ap.add_argument("--out", default=None, help="also write the report here")
    args = ap.parse_args()

    paths: List[str] = []
    for pattern in args.records:
        hits = sorted(glob.glob(pattern))
        paths.extend(hits or [pattern])

    text = run(paths)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
