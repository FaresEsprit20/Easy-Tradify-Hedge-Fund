"""v2.1 asset analysis: every category proposes its own setups; risk from the caller; real probabilities.

    analyze_institutional_signal(symbol, order_type, fixed_trade_size_usd, risk_per_trade, ...)

Returns the setups that are live now (created on a closed bar and not yet past valid_until), the ones not
tradeable (unknown probability, negative measured net R, or unaffordable), each setup's measured probability,
the selected setup (highest real probability among tradeable ones) and the market model.
"""
from __future__ import annotations

import importlib

from engine_v2.probability.frequency import load_table, probability_for
from engine_v2.risk import size
from engine_v2.selection import select, tradeable

# v2.1 categories run at their H4/D1 defaults on long H1 context. ORDER_FLOW (intraday profiles) and
# CROSS_ASSET (multi-symbol) measured negative and have no v2.1 rules, so they are not proposed live.
CATEGORY_MODULES = ("smc", "structure", "trend", "momentum", "mean_reversion", "wave")
# v3.0: only categories that passed leave-pairs-out validation (engine_v2/run/crosspair.py) may be tradeable.
# The others still propose setups so the shadow run keeps collecting their live evidence.
VALIDATED: set[str] = set()
# STRUCTURE (medium volatility + secure-half) passed the fold test (553 held-out trades, 68.4%, +0.096R, t=2.19) but the
# fixed-band rebuild on all 30 pairs gave +0.056R (t=1.3), +0.001R from 2021 and -0.054R on the 19 new pairs.
# It is the leading candidate for the forward shadow run, not a validated rule.


def analyze_context(ctx, fixed_trade_size_usd: float, risk_per_trade: float, now: int | None = None,
                    table: dict | None = None, categories=CATEGORY_MODULES) -> dict:
    now = int(now if now is not None else ctx.m1.close_time[-1])
    table = table if table is not None else load_table()
    live, errors = [], {}
    for name in categories:
        try:
            mod = importlib.import_module(f"engine_v2.categories.{name}")
            for s in mod.propose(ctx):
                if s.created_at <= now < s.valid_until:
                    live.append(s)
        except Exception as e:  # one broken category must not take the others down
            errors[name] = repr(e)
    for s in live:
        s.probability = probability_for(s, table)
        s.risk = size(s, fixed_trade_size_usd, risk_per_trade)
        s.status = "PROPOSED" if (s.category in VALIDATED and tradeable(s)) else "NOT_TRADEABLE"
    chosen = select([s for s in live if s.status == "PROPOSED"])

    def why(s):
        if s.category not in VALIDATED:
            return "category failed cross-pair validation (shadow only)"
        p = s.probability
        if p.get("value") is None:
            return f"probability unknown (n={p.get('n', 0)})"
        if (p.get("net_r") or 0) <= 0:
            return f"measured net R {p.get('net_r')} is not positive"
        return s.risk.get("reason")

    i4 = ctx.last_closed_index("H4", now)
    d1 = ctx.last_closed_index("D1", now)
    return {
        "engine": "v3.0",
        "symbol": ctx.symbol,
        "as_of": now,
        "setups": [s.to_dict() for s in live if s.status == "PROPOSED"],
        "not_tradeable": [dict(s.to_dict(), why=why(s)) for s in live if s.status != "PROPOSED"],
        "selected": chosen.to_dict() if chosen else None,
        "market_model": {"d1_trend": int(ctx.trend("D1")[d1]) if d1 >= 0 else None,
                         "h4_trend": int(ctx.trend("H4")[i4]) if i4 >= 0 else None,
                         "atr_h4": float(ctx.atr("H4")[i4]) if i4 >= 0 else None},
        "category_errors": errors,
    }


def analyze_institutional_signal(symbol: str, order_type: str | None, fixed_trade_size_usd: float,
                                 risk_per_trade: float, h1_bars: int = 6000, **_ignored) -> dict:
    from engine_v2.data.live import load_live_h1
    from engine_v2.market_model.context import Context
    ctx = Context(symbol, load_live_h1(symbol, h1_bars))
    return analyze_context(ctx, fixed_trade_size_usd, risk_per_trade)
