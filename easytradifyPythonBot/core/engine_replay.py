# ============================================================
# ENGINE REPLAY
# ============================================================
# FILE: core/engine_replay.py
#
# Walks historical bars, calls the REAL analyze_institutional_signal()
# at each one with only past data, records what it decided, then looks
# forward at the bars that followed to see what actually happened.
#
# The point is not the win rate. The point is CALIBRATION: when the
# engine says 87%, do 87% of those win? A system whose stated
# probability matches its realised hit rate is trustworthy at any win
# rate. A system claiming 90% and delivering 45% is dangerous precisely
# BECAUSE the number is high -- position sizing trusts it, and so does
# TRADE_PROBABILITY_MINIMUM.
#
# Usage:
#     from core.market_data import HistoricalFeed
#     from core.engine_replay import replay_engine
#     from core.replay_metrics import full_report, format_report
#
#     feed = HistoricalFeed({"M1": m1, "M5": m5, "M15": m15, "H1": h1},
#                           symbol="XAGUSD", pip_size=0.001,
#                           spread_pips=20.0)
#     records = replay_engine(feed, symbol="XAGUSD")
#     print(format_report(full_report(records)))
#
# WHAT THIS CANNOT TELL YOU
# ------------------------------------------------------------
# Fills. It assumes you got the price you asked for. Snapshots from this
# system show 20-40 pip spreads on XAGUSD, so real fills will be worse
# than anything here. Slippage, requotes and partial fills are all
# invisible. Treat the output as an upper bound.
# ============================================================

from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
import logging

from core.mt5_shim import replay_context, ShimStats
from core.decision_features import flatten_decision

logger = logging.getLogger(__name__)

# Which bar's range decides an ambiguous outcome. When one bar spans
# both stop and target, which came first is unknowable from OHLC alone
# and assuming the target is a silent win-rate inflator.
AMBIGUOUS_POLICY = "stop"


def _field(row, name, index):
    try:
        return float(row[name])
    except (KeyError, ValueError, IndexError, TypeError):
        pass
    try:
        return float(row[index])
    except (IndexError, TypeError, ValueError, KeyError):
        return None


def _extract_plan(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pull the trade plan out of an analysis result.

    Returns None unless the engine actually intended to trade, so a HOLD
    never enters the outcome statistics.
    """
    entry = result.get("entry_analysis") or {}
    if not entry.get("should_enter"):
        return None
    if entry.get("execution") == "DO_NOTHING" or entry.get("simple_action") == "HOLD":
        return None

    details = result.get("entry_details") or {}
    # ✅ FIXED: this read the DIRECTION out of `simple_action`, which is
    # an ACTION label, not a direction. entry_engine.py sets it to
    # "ENTER NOW" on a confirmed entry (alongside "WAIT", "HOLD"), so
    # `direction` came out as "ENTER NOW", failed the BUY/SELL check
    # below, and returned None. The `or result.get("order_type")`
    # fallback could never rescue it either, because "ENTER NOW" is
    # truthy.
    #
    # Net effect: _extract_plan() returned None for EVERY qualifying
    # trade, so `entry_triggered` was never set, and the replay reported
    # "entries taken: 0" no matter what the engine decided. The gate
    # funnel's ENTERED row was structurally unreachable.
    #
    # It hid behind the genuine upstream blockers -- the timing gate,
    # the cost structure -- which independently produced 0 entries, so
    # the number always had an explanation that was also true.
    # _shadow_plan() directly below has always resolved direction
    # correctly, which is why the shadow universe scored thousands of
    # trades while this one scored none; the two disagreeing about where
    # direction lives IS the bug.
    direction = (result.get("order_type")
                 or _g(result, "directional_analysis", "best_direction"))
    if direction not in ("BUY", "SELL"):
        return None

    rr = details.get("risk_reward_detail") or {}
    plan = {
        "direction": direction,
        "entry_price": details.get("entry_price"),
        "stop_loss": details.get("stop_loss"),
        "take_profit": details.get("take_profit_1"),
        "planned_rr": rr.get("ratio"),
        "rr_valid": rr.get("valid"),
    }
    if any(plan[k] is None for k in ("entry_price", "stop_loss", "take_profit")):
        return None
    return plan


def _g(d, *path, default=None):
    """Nested get that never raises on a missing or non-dict level."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _shadow_plan(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    The trade the engine WOULD have taken, whether or not it took it.

    This is what makes gate forensics possible. entry_details carries a
    computed entry/SL/TP on every decision, including rejected ones, so
    every rejection can be scored against what actually happened next.
    Without it a gate that rejects nothing but winners looks identical
    to a gate that rejects nothing but losers.
    """
    details = result.get("entry_details") or {}
    direction = (result.get("order_type")
                 or _g(result, "directional_analysis", "best_direction"))
    if direction not in ("BUY", "SELL"):
        return None
    plan = {
        "direction": direction,
        "entry_price": details.get("entry_price"),
        "stop_loss": details.get("stop_loss"),
        "take_profit": details.get("take_profit_1"),
        "planned_rr": _g(details, "risk_reward_detail", "ratio"),
    }
    if any(plan[k] is None for k in ("entry_price", "stop_loss", "take_profit")):
        return None
    return plan


def _capture(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten the diagnostic surface of one decision.

    Delegates to core/decision_features.flatten_decision(), which the
    LIVE pipeline also calls. That shared definition is what keeps the
    Stage 7 meta-label model honest: it is trained on these records and
    served on live analyses, so the moment the two paths flatten a
    decision differently the model is being asked a different question
    than it was taught -- silently, with no error and no wrong-looking
    log line. One function, both paths.
    """
    return flatten_decision(result)


def session_tag(ts) -> Dict[str, Any]:
    """
    Which trading session a decision timestamp falls in (section 4 of
    replay_backtest_strategy.md).

    Derived from the timestamp, not from session_analysis: that block
    answers "is the market open", which on a round-the-clock FX symbol
    is True almost always and therefore cannot slice anything. Phase 2
    needs the slice, so the tag is computed from UTC hour boundaries
    that mean the same thing on every instrument.

    The overlap is called out as its own tag rather than folded into
    either side. It is the highest-liquidity window of the day and
    burying it inside LONDON would hide exactly the concentration Phase
    2 is looking for.
    """
    try:
        hour = datetime.utcfromtimestamp(float(ts)).hour
    except (TypeError, ValueError, OSError, OverflowError):
        return {"session": "UNKNOWN", "utc_hour": None}

    if 12 <= hour < 16:
        name = "LONDON_NY_OVERLAP"
    elif 7 <= hour < 12:
        name = "LONDON"
    elif 16 <= hour < 21:
        name = "NEWYORK"
    elif hour >= 22 or hour < 7:
        name = "ASIA"
    else:
        name = "OFF_HOURS"
    return {"session": name, "utc_hour": hour}


def _rejection_reason(result: Dict[str, Any]) -> str:
    fv = result.get("final_verdict") or {}
    entry = result.get("entry_analysis") or {}
    return (fv.get("verdict") or entry.get("final_decision")
            or entry.get("reason") or result.get("error") or "unrecorded")


def evaluate_outcome(rates, decision_index: int, plan: Dict[str, Any], *,
                     pip_size: float, spread_pips: float = 0.0,
                     max_holding_bars: int = 500,
                     ambiguous_policy: str = AMBIGUOUS_POLICY) -> Dict[str, Any]:
    """Walk forward from the bar AFTER the decision and see what happened."""
    d = plan["direction"]
    entry = float(plan["entry_price"])
    sl = float(plan["stop_loss"])
    tp = float(plan["take_profit"])

    risk = (entry - sl) if d == "BUY" else (sl - entry)
    if risk <= 0:
        return {"outcome": "INVALID", "reason": "stop is on the wrong side of entry"}
    risk_pips = risk / pip_size

    start = decision_index + 1
    end = min(len(rates), start + max_holding_bars)

    # ---- EXCURSION TRACKING (replay_backtest_strategy.md section 4) ----
    #
    # MFE and MAE, both in R, accumulated bar by bar up to the resolving
    # bar inclusive. They answer a question the win/loss column cannot:
    # whether a tighter target would have caught more wins before the
    # reversal, and how close the losers came to working. That is the
    # empirical way to test an R:R change -- the alternative is guessing
    # at a number and re-running the whole replay to find out.
    #
    # `bars_to_1r` is the same walk's answer to Phase 4's question: at
    # which bar did unrealized profit first reach 1R, i.e. when would a
    # breakeven stop have armed. Recorded here, NOT acted on -- Phase 0
    # changes no logic, and Phase 4 needs this number to exist before it
    # can test the rule that consumes it.
    mfe_pips = 0.0
    mae_pips = 0.0
    bars_to_1r = None

    def _excursion(i, hi, lo):
        """Update the running excursions from bar i's range."""
        nonlocal mfe_pips, mae_pips, bars_to_1r
        if d == "BUY":
            fav, adv = (hi - entry) / pip_size, (entry - lo) / pip_size
        else:
            fav, adv = (entry - lo) / pip_size, (hi - entry) / pip_size
        if fav > mfe_pips:
            mfe_pips = fav
        if adv > mae_pips:
            mae_pips = adv
        if bars_to_1r is None and risk_pips > 0 and fav >= risk_pips:
            bars_to_1r = i - decision_index

    def _excursions():
        return {
            "mfe_r": round(mfe_pips / risk_pips, 3) if risk_pips > 0 else None,
            "mae_r": round(mae_pips / risk_pips, 3) if risk_pips > 0 else None,
            "mfe_pips": round(mfe_pips, 2),
            "mae_pips": round(mae_pips, 2),
            "bars_to_1r": bars_to_1r,
            "reached_1r": bars_to_1r is not None,
        }

    for i in range(start, end):
        hi = _field(rates[i], "high", 2)
        lo = _field(rates[i], "low", 3)
        if hi is None or lo is None:
            continue
        _excursion(i, hi, lo)

        if d == "BUY":
            hit_stop, hit_target = lo <= sl, hi >= tp
        else:
            hit_stop, hit_target = hi >= sl, lo <= tp

        if hit_stop and hit_target:
            if ambiguous_policy == "target":
                return _close("WIN", i, tp, decision_index, entry, risk_pips,
                              d, pip_size, spread_pips, ambiguous=True,
                              extra=_excursions())
            if ambiguous_policy == "skip":
                out = {"outcome": "AMBIGUOUS", "bars_held": i - decision_index,
                       "reason": "stop and target inside one bar's range"}
                out.update(_excursions())
                return out
            return _close("LOSS", i, sl, decision_index, entry, risk_pips,
                          d, pip_size, spread_pips, ambiguous=True,
                          extra=_excursions())
        if hit_stop:
            return _close("LOSS", i, sl, decision_index, entry, risk_pips,
                          d, pip_size, spread_pips, extra=_excursions())
        if hit_target:
            return _close("WIN", i, tp, decision_index, entry, risk_pips,
                          d, pip_size, spread_pips, extra=_excursions())

    out = {"outcome": "UNRESOLVED", "bars_held": end - start,
           "reason": f"neither level reached within {max_holding_bars} bars"}
    out.update(_excursions())
    return out


def _close(kind, exit_index, exit_price, decision_index, entry, risk_pips,
           direction, pip_size, spread_pips, ambiguous=False, extra=None):
    moved = ((exit_price - entry) if direction == "BUY" else (entry - exit_price)) / pip_size
    out = {
        "outcome": kind,
        "exit_index": exit_index,
        "exit_price": exit_price,
        "bars_held": exit_index - decision_index,
        "pips_moved": round(moved, 2),
        "risk_pips": round(risk_pips, 2),
        "r_multiple": round(moved / risk_pips, 3) if risk_pips > 0 else None,
        # Net of spread. A "win" that only covers the spread is not a 2R
        # win, and reporting hit rate without this is how backtests lie.
        "r_multiple_net": (round((moved - spread_pips) / risk_pips, 3)
                           if risk_pips > 0 else None),
        "ambiguous": ambiguous,
    }
    if extra:
        out.update(extra)
    return out


def replay_engine(feed, *, symbol: str,
                  order_type: str = "AUTO",
                  fixed_trade_size_usd: float = 200.0,
                  risk_per_trade: float = 10.0,
                  leverage: int = 200,
                  timeframe: str = "M1",
                  warmup_bars: int = 300,
                  step: int = 1,
                  max_holding_bars: int = 500,
                  stop_after: Optional[int] = None,
                  verify_lookahead: bool = True,
                  on_decision: Optional[Callable[[Dict[str, Any]], None]] = None,
                  analyze_fn=None) -> List[Dict[str, Any]]:
    """
    Replay the real engine across a HistoricalFeed.

    verify_lookahead is on by default and checks EVERY served window
    rather than sampling. It costs almost nothing and a lookahead bug
    that only shows up in production is worse than a slow replay.
    """
    if analyze_fn is None:
        from core.asset_analysis import analyze_institutional_signal as analyze_fn
    base = feed.rates_by_tf[feed.base_timeframe]
    times = [_field(r, "time", 0) for r in base]
    index_of = {t: i for i, t in enumerate(times) if t is not None}

    records: List[Dict[str, Any]] = []
    shim_stats = ShimStats()
    stats = {"served": 0, "analysed": 0, "entries": 0, "errors": 0,
             "lookahead_violations": 0, "skipped_no_data": 0}

    for ts in feed.timestamps(warmup_bars=warmup_bars, step=step):
        md = feed.at(ts)
        if md is None:
            stats["skipped_no_data"] += 1
            continue
        stats["served"] += 1

        if verify_lookahead:
            problems = feed.verify_no_lookahead(ts, md)
            if problems:
                stats["lookahead_violations"] += 1
                raise RuntimeError(
                    f"LOOKAHEAD at ts={ts}: {problems}. "
                    f"Replay results would be meaningless; refusing to continue."
                )

        decision_index = len(md.rates) - 1
        # Map back onto the full array so outcome evaluation can walk forward.
        last_bar_time = _field(md.rates[-1], "time", 0)
        abs_index = index_of.get(last_bar_time, decision_index)

        try:
            # The market_data parameter covers the six acquisition points
            # in analyze_institutional_signal() itself. The shim covers
            # everything else -- calculate_lot_proper's symbol_info/tick/
            # account, the M15 divergence fetch, the D1 ADR fetch, the
            # SMC symbol_info, and any call site not yet found. Missing
            # ONE is enough to make the whole replay read the present.
            with replay_context(md, stats=shim_stats):
                result = analyze_fn(
                    symbol=symbol, order_type=order_type,
                    fixed_trade_size_usd=fixed_trade_size_usd,
                    risk_per_trade=risk_per_trade, leverage=leverage,
                    timeframe=timeframe, market_data=md,
                )
        except Exception as e:
            stats["errors"] += 1
            logger.debug(f"[REPLAY] analysis failed at ts={ts}: {e}")
            continue

        stats["analysed"] += 1
        fv = result.get("final_verdict") or {}
        captured = _capture(result)

        rec: Dict[str, Any] = {
            "symbol": symbol,
            "decision_index": abs_index,
            "decision_timestamp": ts,
            "success": result.get("success", False),
            "entry_triggered": False,
            "probability_percent": fv.get("probability_percent"),
            "rejection_reason": _rejection_reason(result),
            "capture": captured,
            "session": session_tag(ts),
            "trace": {
                "probability_final": fv.get("probability_percent"),
                "probability_at_decision": fv.get("probability_percent"),
                "absorbed": captured.get("absorbed_total"),
            },
        }

        plan = _extract_plan(result)

        # SHADOW OUTCOME -- computed for EVERY decision, taken or not.
        #
        # This is the difference between a backtest and an audit. Knowing
        # the win rate of trades you took tells you nothing about the
        # trades you refused. A gate that rejects 400 setups of which 380
        # would have won is not a filter, it is the problem -- and it is
        # indistinguishable from a good gate unless the rejected setups
        # are scored too.
        #
        # It costs one forward walk per decision and it is the single
        # most informative number this harness produces.
        shadow = _shadow_plan(result)
        if shadow:
            rec["shadow"] = evaluate_outcome(
                base, abs_index, shadow,
                pip_size=feed.pip_size,
                spread_pips=feed.spread_pips or 0.0,
                max_holding_bars=max_holding_bars,
            )
            rec["shadow_plan"] = shadow

        if plan:
            stats["entries"] += 1
            rec.update({
                "entry_triggered": True,
                "direction": plan["direction"],
                "entry_price": plan["entry_price"],
                "stop_loss": plan["stop_loss"],
                "take_profit": plan["take_profit"],
                "planned_rr": plan["planned_rr"],
                "outcome": rec.get("shadow") or evaluate_outcome(
                    base, abs_index, plan,
                    pip_size=feed.pip_size,
                    spread_pips=feed.spread_pips or 0.0,
                    max_holding_bars=max_holding_bars,
                ),
            })

        records.append(rec)
        if on_decision:
            on_decision(rec)
        if stop_after and len(records) >= stop_after:
            break

    stats["mt5_shim"] = shim_stats.as_dict()
    logger.info(f"[REPLAY] {symbol}: {stats}")
    if records:
        records[0].setdefault("_stats", stats)
    return records