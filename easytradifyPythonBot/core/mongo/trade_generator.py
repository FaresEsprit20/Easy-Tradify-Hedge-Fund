# ============================================================
# TRADE GENERATOR -- ENLARGE THE DATASET SAFELY AND FAST
# ============================================================
# FILE: core/mongo/trade_generator.py
#
# Produces trades in the EXACT shape the live monitor writes, by running the
# real analysis over historical bars and walking each decision forward to its
# stop or target. No broker, no orders, no waiting.
#
# WHY THIS IS NEEDED
# ------------------
# The live account produces ~3.3 trades/day. Every conclusion about signal
# quality this project has tried to draw has died on sample size: a search of
# 82 hypotheses over 215 trades found a 62% subset that collapsed to 25% out
# of sample, and a shuffled-outcome control showed the BEST subset of pure
# noise still reaches 61.5%. That is not a strategy problem, it is a power
# problem, and the only cure is more trades.
#
# WHAT MAKES THESE SAFE TO MIX WITH REAL ONES -- AND WHY THAT MATTERS
# -------------------------------------------------------------------
# They are NOT mixed. Every generated trade carries:
#
#     source            "simulated"
#     is_simulated      True
#     generator_version <version>
#
# and `TradesService` queries can exclude them. This package has refused
# fictional history before for exactly this reason: a reconstruction that is
# indistinguishable from a broker's record will eventually be treated as one,
# and then every measurement rests on data nobody can audit.
#
# WHAT IS REAL AND WHAT IS NOT
# ----------------------------
#   REAL        the bars, and therefore the price path, the stop/target hits
#               and the outcome
#   REAL        the analysis -- the same analyze_institutional_signal the
#               live bot runs, on the same bars, through the no-lookahead shim
#   SIMULATED   the fill: entry at the bar close with a fixed spread, no
#               slippage, no requote, no partial fill
#
# The third line is the honest limit. These trades answer "what would the
# rules have done", not "what would the broker have given us".
#
# CAUSALITY
# ---------
# Every analysis runs inside core.mt5_shim.replay_context, so a component that
# fetches its own bars is served from the same historical feed rather than
# reaching the live terminal. Without that, `nested_zone`, `trend_cascade`,
# `adr_exhaustion` and the H1/M15 paths silently read TODAY'S bars -- which is
# exactly what made them measure as noise before it was found.
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "1.0"

DEFAULT_SPREAD_PIPS = 1.0
DEFAULT_MAX_BARS = 480          # give a trade 8 hours to resolve
DEFAULT_POINT_INTERVAL = 60     # one price point per minute, as live


def _encoder():
    from ai.price_evolution_encoder import PriceEvolutionEncoder
    return PriceEvolutionEncoder()


def _bar(row) -> Dict[str, float]:
    """MT5 rate row -> plain dict. Column order: time, open, high, low, close."""
    def get(name, index):
        try:
            return float(row[name])
        except Exception:
            try:
                return float(row[index])
            except Exception:
                return None
    return {"time": get("time", 0), "open": get("open", 1),
            "high": get("high", 2), "low": get("low", 3),
            "close": get("close", 4)}


def generate(symbol: str, *, days: int = 30, step_bars: int = 15,
             risk_reward: float = 2.0, stop_pips: Optional[float] = None,
             max_trades: Optional[int] = None,
             spread_pips: float = DEFAULT_SPREAD_PIPS,
             max_bars_open: int = DEFAULT_MAX_BARS,
             point_interval_seconds: int = DEFAULT_POINT_INTERVAL,
             persist: bool = True,
             progress: bool = True) -> Dict[str, Any]:
    """
    Generate trades for one symbol over `days` of history.

    `step_bars` is how often a decision is evaluated. It is not a free
    parameter to maximise: sampling every bar produces heavily overlapping
    trades that share the same price move, and 500 such trades carry nowhere
    near 500 trades' worth of independent information. 15 minutes between
    decisions keeps them closer to independent.
    """
    from ai import history_enrichment as he
    from core.asset_analysis import analyze_institutional_signal
    from core.mt5_shim import replay_context
    from .trades_service import get_trades_service

    mt5 = he._mt5()
    if not mt5.initialize():
        raise RuntimeError("MetaTrader5 is not available")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(days))

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start, end)
    if rates is None or len(rates) < 500:
        raise RuntimeError(
            "not enough M1 history for %s (%s bars)"
            % (symbol, 0 if rates is None else len(rates)))
    bars = [_bar(r) for r in rates]

    info = mt5.symbol_info(symbol)
    point = getattr(info, "point", None) or 0.0001
    digits = getattr(info, "digits", 5)
    pip = point * (10 if digits in (3, 5) else 1)

    service = get_trades_service() if persist else None
    encoder = _encoder()

    warmup = 400
    made: List[Dict[str, Any]] = []
    skipped = {"no_entry": 0, "no_analysis": 0, "unresolved": 0}
    ticket = int(datetime.now(timezone.utc).timestamp())

    for index in range(warmup, len(bars) - 1, max(1, int(step_bars))):
        if max_trades and len(made) >= max_trades:
            break

        moment = bars[index]["time"]
        feed = he.build_feed(symbol, int(moment) - 86400 * 7, int(moment))
        if feed is None:
            skipped["no_analysis"] += 1
            continue
        market = feed.at(float(moment))
        if market is None or feed.verify_no_lookahead(float(moment), market):
            skipped["no_analysis"] += 1
            continue

        try:
            with replay_context(market, strict=True):
                analysis = analyze_institutional_signal(
                    symbol=symbol, order_type="BUY",
                    fixed_trade_size_usd=1000.0, risk_per_trade=1.0,
                    leverage=200, timeframe="M1", use_gnn=False,
                    market_data=market)
        except Exception as exc:
            logger.debug("analysis failed at %s: %s", moment, exc)
            skipped["no_analysis"] += 1
            continue

        if not analysis or not analysis.get("success"):
            skipped["no_analysis"] += 1
            continue

        verdict = analysis.get("final_verdict") or {}
        decision = str(analysis.get("🎯 FINAL_DECISION")
                       or verdict.get("decision") or "").upper()
        direction = analysis.get("best_direction") or (
            "BUY" if "BUY" in decision else "SELL" if "SELL" in decision else None)
        if not direction or "NO" in decision or "HOLD" in decision:
            skipped["no_entry"] += 1
            continue

        entry = bars[index]["close"]
        risk = (float(stop_pips) * pip) if stop_pips else (20.0 * pip)
        long = direction == "BUY"
        stop = entry - risk if long else entry + risk
        target = entry + risk * risk_reward if long else entry - risk * risk_reward

        outcome = _walk_forward(bars, index + 1, long, stop, target,
                                max_bars_open)
        if outcome is None:
            skipped["unresolved"] += 1
            continue
        exit_index, exit_price, reason = outcome

        ticket += 1
        opened = datetime.fromtimestamp(moment, tz=timezone.utc)
        closed = datetime.fromtimestamp(bars[exit_index]["time"], tz=timezone.utc)
        sign = 1 if long else -1
        profit_r = sign * (exit_price - entry) / risk
        spread_cost = (spread_pips * pip) / risk

        trade = {
            "ticket": ticket,
            "trade_id": "trade_%d" % ticket,
            "symbol": symbol,
            "direction": direction,
            "status": "CLOSED",
            "opened_at": opened,
            "closed_at": closed,
            # The provenance stamp. Never omitted -- a simulated trade that
            # cannot be told apart from a real fill will eventually be treated
            # as one.
            "source": "simulated",
            "is_simulated": True,
            "generator_version": GENERATOR_VERSION,
            "entry": {"price": entry, "stop_loss": stop, "take_profit": target,
                      "volume": 0.1, "spread_pips": spread_pips},
            "analysis_at_open": {
                "timestamp": opened.isoformat(),
                "m1_analysis_raw": analysis,
                "_encoded": False,
                "_audit_schema": 1,
            },
            "close_data": {
                "close_price": exit_price,
                "profit_usd": round((profit_r - spread_cost) * 100.0, 2),
                "profit_r": round(profit_r - spread_cost, 4),
                "close_reason": reason,
                "order_type": direction,
                "duration_seconds": int((closed - opened).total_seconds()),
                "closed_at": closed,
            },
            "price_evolution": _build_points(
                bars, index, exit_index, entry, stop, target, long, risk,
                analysis, encoder, point_interval_seconds),
        }

        if service:
            service.upsert_trade(trade)
        made.append(trade)

        if progress and len(made) % 25 == 0:
            print("  generated %d trades (%s)" % (len(made), symbol), flush=True)

    return {
        "symbol": symbol,
        "generated": len(made),
        "skipped": skipped,
        "days": days,
        "step_bars": step_bars,
        "persisted": bool(persist),
        "generator_version": GENERATOR_VERSION,
        "trades": [] if persist else made,
    }


def _walk_forward(bars, start_index, long, stop, target, max_bars):
    """
    Which level the price reached first, walking real bars.

    When one bar's range spans BOTH levels the order inside it is unknowable,
    and this resolves it as the STOP. That is the pessimistic reading, chosen
    deliberately: assuming the target came first would inflate every win rate
    this dataset ever produces, which is the flattering error that makes a
    backtest worthless.
    """
    for i in range(start_index, min(len(bars), start_index + max_bars)):
        high, low = bars[i]["high"], bars[i]["low"]
        if high is None or low is None:
            continue
        hit_stop = (low <= stop) if long else (high >= stop)
        hit_target = (high >= target) if long else (low <= target)
        if hit_stop:
            return i, stop, "STOP_LOSS"
        if hit_target:
            return i, target, "TAKE_PROFIT"
    return None


def _build_points(bars, entry_index, exit_index, entry, stop, target, long,
                  risk, analysis, encoder, interval_seconds):
    """
    The forward walk, one point per interval, in the live shape.

    The analysis is encoded ONCE and reused across points rather than being
    recomputed per minute: recomputing it would multiply generation cost by
    the length of every trade for a payload that barely changes, and the
    purpose here is volume. A point still carries its own price, profit and
    risk_state, which is what the path-based models read.
    """
    encoded = encoder.encode(analysis, compact=True)
    step = max(1, int(interval_seconds // 60))
    points = []
    for i in range(entry_index, exit_index + 1, step):
        price = bars[i]["close"]
        if price is None:
            continue
        sign = 1 if long else -1
        points.append({
            "timestamp": datetime.fromtimestamp(
                bars[i]["time"], tz=timezone.utc).isoformat(),
            "price": price,
            "profit_usd": round(sign * (price - entry) / risk * 100.0, 2),
            "profit_percent": round(sign * (price - entry) / entry * 100.0, 4),
            "distance_from_entry_pips": round(abs(price - entry) / risk, 3),
            "risk_state": {
                "sl": stop, "tp": target, "initial_sl": stop,
                "break_even_applied": False, "trailing_active": False,
                "sl_at_or_beyond_breakeven": False,
            },
            "analysis": {"m1": encoded},
            "_encoded": True,
            "_tf_included": ["m1"],
            "_simulated": True,
        })
    return points


def generate_many(symbols: Iterable[str], **kwargs) -> Dict[str, Any]:
    """Generate across several symbols and report the total."""
    reports, total = [], 0
    for symbol in symbols:
        try:
            report = generate(symbol, **kwargs)
            reports.append(report)
            total += report["generated"]
            print("  %-10s %d trades" % (symbol, report["generated"]), flush=True)
        except Exception as exc:
            logger.warning("generation failed for %s: %s", symbol, exc)
            reports.append({"symbol": symbol, "generated": 0, "error": str(exc)})
    return {"total_generated": total, "symbols": len(reports),
            "reports": reports}


def purge_simulated(confirm: bool = False) -> Dict[str, Any]:
    """
    Remove every generated trade.

    Dry run unless confirmed, and it matches ONLY documents carrying the
    simulated stamp -- a purge that could touch a real broker record would be
    a far worse bug than any it cleans up.
    """
    from .trades_service import get_trades_service

    service = get_trades_service()
    query = {"is_simulated": True}
    count = service.collection.count_documents(query)
    if not confirm:
        return {"dry_run": True, "would_delete": count,
                "hint": "pass confirm=True to delete"}
    deleted = service.collection.delete_many(query).deleted_count
    return {"dry_run": False, "deleted": deleted}
