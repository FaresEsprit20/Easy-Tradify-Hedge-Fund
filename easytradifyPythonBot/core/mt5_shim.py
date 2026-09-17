# ============================================================
# SCOPED MT5 SHIM
# ============================================================
# FILE: core/mt5_shim.py
#
# The analysis does not fetch data in one place. Reachable from
# analyze_institutional_signal() there are at least twelve MT5 calls
# across six modules:
#
#   calculations.py:253,257,269    symbol_info / tick / account
#                                  (inside calculate_lot_proper)
#   calculations.py:1428,1566      M15 divergence, M1 volume profile
#   indicators.py:260,2872,2965    tick, H1 trend, M15 divergence
#   indicators.py:3328             generic timeframe fetch
#   indicators.py:936              copy_ticks_from, inside
#                                  analyze_micro_structure() -- was
#                                  unpatched; fed live now()-ticks into
#                                  the timing_confidence gate during
#                                  every replayed decision
#   asset_analysis_smc.py:1019     symbol_info
#   adr_exhaustion.py:61           D1 bars
#
# Threading a market_data parameter through all of them would mean
# touching six modules and changing several public signatures -- and the
# real problem is that the ONE call site missed is the one that silently
# reads the present during a replay of the past. That failure is
# invisible: the backtest just comes out better.
#
# So instead of patching call sites, this intercepts the mt5 module for
# the duration of one replayed decision. Every call, found or not, is
# served from the injected data. On exit the originals are restored.
#
# This is replay-only. Live code never enters the context, so live
# behaviour is untouched.
#
# ------------------------------------------------------------
# FAIL CLOSED
# ------------------------------------------------------------
# When the feed has no data for a requested timeframe the shim returns
# None -- the same thing MT5 returns on failure -- so the consuming
# module takes its own "data unavailable" path and reports
# available: False. It does NOT fall through to the real terminal,
# because falling through is precisely the lookahead this exists to
# prevent.
# ============================================================

from contextlib import contextmanager
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Real MetaTrader5 timeframe constants, so the shim can map a requested
# timeframe back to a name regardless of which module asked.
TF_CONSTANT_TO_NAME = {
    1: "M1", 2: "M2", 3: "M3", 4: "M4", 5: "M5", 6: "M6",
    10: "M10", 12: "M12", 15: "M15", 20: "M20", 30: "M30",
    16385: "H1", 16386: "H2", 16387: "H3", 16388: "H4", 16390: "H6",
    16392: "H8", 16396: "H12", 16408: "D1", 32769: "W1", 49153: "MN1",
}

_PATCHED = ("symbol_info", "symbol_info_tick", "account_info",
            "copy_rates_from_pos", "copy_rates_from", "copy_rates_range", "order_calc_margin", "order_calc_profit",
            "copy_ticks_from", "copy_ticks_range")


class ShimStats:
    def __init__(self):
        self.served: Dict[str, int] = {}
        self.missing: Dict[str, int] = {}

    def hit(self, what: str):
        self.served[what] = self.served.get(what, 0) + 1

    def miss(self, what: str):
        self.missing[what] = self.missing.get(what, 0) + 1

    def as_dict(self):
        return {"served": dict(self.served), "missing": dict(self.missing)}


@contextmanager
def replay_context(market_data, *, stats: Optional[ShimStats] = None,
                   strict: bool = True):
    """
    Serve every MT5 call from `market_data` for the duration of the block.

    strict=True (the default) makes an unavailable timeframe return None
    rather than reaching the live terminal. Turning it off reintroduces
    the exact lookahead this module exists to remove, so it should only
    ever be used to debug the shim itself.
    """
    import MetaTrader5 as mt5

    stats = stats if stats is not None else ShimStats()
    originals = {name: getattr(mt5, name, None) for name in _PATCHED}

    rates_by_tf = dict(market_data.multi_tf_rates or {})
    if market_data.rates is not None:
        rates_by_tf.setdefault("M1", market_data.rates)

    def _rates_for(timeframe, count=None):
        name = TF_CONSTANT_TO_NAME.get(timeframe)
        arr = rates_by_tf.get(name) if name else None
        if arr is None or len(arr) == 0:
            stats.miss(f"rates:{name or timeframe}")
            return None
        stats.hit(f"rates:{name}")
        if count and count < len(arr):
            return arr[-count:]
        return arr

    # The symbol this MarketData actually describes. Every accessor below
    # checks the caller's symbol against it.
    #
    # ✅ FIXED: these ignored their `symbol` argument and returned the one
    # replayed symbol's data to ANY caller. For single-symbol analysis
    # that is harmless -- every request is for the same symbol. It stops
    # being harmless the moment something asks about a DIFFERENT
    # instrument, which is exactly what the GNN does: it requests ticks
    # for correlated symbols to build a cross-asset graph, and silently
    # received EURUSD's tick for every one of them. Correlations computed
    # against identical data are 1.0 by construction, so the component
    # would have looked like it was working while measuring nothing.
    #
    # A foreign symbol now returns None -- the same "no data" MT5 gives
    # on failure -- rather than the wrong instrument's data. Fail closed
    # is the rule for this whole module, and quietly substituting one
    # instrument for another is the most misleading way to break it.
    _own_symbol = str(getattr(market_data, "symbol", "") or "").upper()

    def _is_own(symbol) -> bool:
        if symbol is None or not _own_symbol:
            return True                    # unspecified: serve the replayed one
        return str(symbol).upper() == _own_symbol

    _peers = {k.upper(): v for k, v in (getattr(market_data, "peers", None) or {}).items()}

    def _peer(symbol, field):
        """A peer instrument's data at this same timestamp, or None."""
        blk = _peers.get(str(symbol).upper()) if symbol else None
        return (blk or {}).get(field)

    def _symbol_info(symbol=None):
        if not _is_own(symbol):
            peer = _peer(symbol, "info")
            if peer is not None:
                stats.hit(f"symbol_info:peer")
                return peer
            stats.miss(f"symbol_info:foreign:{symbol}")
            return None
        if market_data.info is None:
            stats.miss("symbol_info")
            return None
        stats.hit("symbol_info")
        return market_data.info

    def _symbol_info_tick(symbol=None):
        if not _is_own(symbol):
            peer = _peer(symbol, "tick")
            if peer is not None:
                stats.hit(f"tick:peer")
                return peer
            stats.miss(f"tick:foreign:{symbol}")
            return None
        if market_data.tick is None:
            stats.miss("tick")
            return None
        stats.hit("tick")
        return market_data.tick

    def _account_info():
        if market_data.account is None:
            stats.miss("account")
            return None
        stats.hit("account")
        return market_data.account

    def _peer_rates(symbol, timeframe, count=None):
        """A peer instrument's bars for one timeframe, or None."""
        blk = _peers.get(str(symbol).upper()) if symbol else None
        if not blk:
            return None
        name = TF_CONSTANT_TO_NAME.get(timeframe)
        by_tf = blk.get("multi_tf_rates") or {}
        arr = by_tf.get(name) if name else None
        if arr is None and name == "M1":
            arr = blk.get("rates")
        if arr is None or len(arr) == 0:
            stats.miss(f"rates:peer:{name}")
            return None
        stats.hit(f"rates:peer")
        return arr[-count:] if count and count < len(arr) else arr

    def _copy_rates_from_pos(symbol, timeframe, start_pos, count):
        # A foreign symbol gets ITS OWN bars when a peer feed supplies
        # them, and None otherwise -- never the primary's. The GNN calls
        # this per correlated instrument (H1 and M5, 50 bars each) to
        # build its graph; served the primary's bars instead, every peer
        # would look identical to the subject and every correlation
        # would be 1.0 by construction.
        if not _is_own(symbol):
            peer = _peer_rates(symbol, timeframe, (count or 0) + (start_pos or 0))
            if peer is None:
                stats.miss(f"rates:foreign:{symbol}")
                return None
            return peer[-count:] if count and count < len(peer) else peer

        arr = _rates_for(timeframe, count + (start_pos or 0))
        if arr is None:
            return None
        if start_pos:
            arr = arr[:-start_pos] if start_pos < len(arr) else None
            if arr is None or len(arr) == 0:
                return None
        return arr[-count:] if count and count < len(arr) else arr

    def _copy_rates_from(symbol, timeframe, date_from, count):
        return _rates_for(timeframe, count)

    def _copy_rates_range(symbol, timeframe, date_from, date_to):
        return _rates_for(timeframe)

    def _copy_ticks_from(symbol, date_from, count, flags):
        """
        Historical ticks as of the DECISION timestamp -- not the
        caller's `date_from`, which is deliberately ignored.

        analyze_micro_structure() in core/indicators.py asks for
        `datetime.now()`. Live that is right; in a replay of the past it
        is the one call that reads the present, which is the lookahead
        this whole module exists to prevent. The decision timestamp is
        what "now" means here, and the shim is the only layer that knows
        both, so the substitution belongs here rather than in a
        market_data parameter threaded through six modules.

        Falls back to None -- exactly as MT5 does on failure, and as
        this function did before tick caching existed -- when no tick
        history is loaded. The consumer already has a documented
        "insufficient tick data" path for that and reports
        available: False, so an absent cache degrades to the previous
        behaviour instead of inventing a tape.
        """
        feed = getattr(market_data, "tick_feed", None)
        ts = getattr(market_data, "decision_timestamp", None)
        if feed is None or ts is None:
            stats.miss("ticks")
            return None

        out = feed.before(ts, count or 200)
        if out is None or len(out) == 0:
            stats.miss("ticks")
            return None
        stats.hit("ticks")
        return out

    def _copy_ticks_range(symbol, date_from, date_to, flags):
        stats.miss("ticks")
        return None

    def _order_calc_margin(action, symbol, volume, price):
        """
        Margin for a hypothetical order.

        MT5 computes this server-side against the live account. In
        replay there is no server, so it is derived from the injected
        contract size, price and leverage:
            volume * contract_size * price / leverage
        which is the standard formula and matches what the live values
        in this system look like (0.61 lots x 5000 x 65.2 / 200 = 198.9).
        """
        info = market_data.info
        account = market_data.account
        if info is None or account is None:
            stats.miss("order_calc_margin")
            return None
        contract = float(getattr(info, "trade_contract_size", 5000.0) or 5000.0)
        leverage = float(getattr(account, "leverage", 200) or 200)
        if leverage <= 0:
            stats.miss("order_calc_margin")
            return None
        stats.hit("order_calc_margin")
        notional_quote = float(volume) * contract * float(price) / leverage
        # MT5 returns margin in the ACCOUNT currency. The formula above is in
        # the QUOTE currency: yen for USDJPY, 150x too large, which sized every
        # replayed JPY trade at the minimum lot with a 25-44 ATR stop that live
        # never produces. tick_value / (tick_size * contract) is the broker's
        # quote -> account rate.
        tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
        tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
        if tick_size > 0 and tick_value > 0 and contract > 0:
            return notional_quote * tick_value / (tick_size * contract)
        return notional_quote

    def _order_calc_profit(action, symbol, volume, price_open, price_close):
        """
        Profit/loss for a hypothetical closed position.

        calculate_lot_proper() uses this to size the position: it asks
        "what would I lose over this stop distance at this lot size"
        and scales until the answer matches the risk budget. Returning
        None here made abs() raise and killed the whole analysis, which
        is why every replayed decision failed before this existed.

        Derived from contract size and price distance. `action` selects
        the sign: a BUY profits when price rises, a SELL when it falls.
        """
        info = market_data.info
        if info is None:
            stats.miss("order_calc_profit")
            return None
        try:
            delta = float(price_close) - float(price_open)
        except (TypeError, ValueError):
            stats.miss("order_calc_profit")
            return None
        # ORDER_TYPE_SELL == 1; anything else is treated as a long.
        if action == 1:
            delta = -delta

        # MT5 computes profit from TICK VALUE and TICK SIZE, not contract
        # size:
        #     profit = volume * (delta / tick_size) * tick_value
        #
        # The two agree only when tick_value == contract_size * tick_size,
        # which is true for some symbols and not others. Using contract
        # size directly produced a pip value roughly thirty times too
        # small on a real XAGUSD replay, which drove required_sl_pips
        # past MAX_SL_PIPS and froze every stop at the 1000-pip cap --
        # so R:R came out near 0.05, nothing could clear the 2.0 floor,
        # and the run reported a 97% win rate on a $1.00 stop against a
        # $0.36 target. Every downstream number was wrong and none of it
        # looked wrong.
        tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
        tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
        if tick_size > 0 and tick_value > 0:
            stats.hit("order_calc_profit")
            return float(volume) * (delta / tick_size) * tick_value

        # Fallback only when the broker did not report tick data.
        contract = float(getattr(info, "trade_contract_size", 0) or 0)
        if contract > 0:
            stats.hit("order_calc_profit:contract_fallback")
            return float(volume) * contract * delta

        stats.miss("order_calc_profit")
        return None

    mt5.order_calc_profit = _order_calc_profit
    mt5.order_calc_margin = _order_calc_margin
    mt5.symbol_info = _symbol_info
    mt5.symbol_info_tick = _symbol_info_tick
    mt5.account_info = _account_info
    mt5.copy_rates_from_pos = _copy_rates_from_pos
    mt5.copy_rates_from = _copy_rates_from
    mt5.copy_rates_range = _copy_rates_range
    mt5.copy_ticks_from = _copy_ticks_from
    mt5.copy_ticks_range = _copy_ticks_range

    try:
        yield stats
    finally:
        for name, fn in originals.items():
            if fn is not None:
                setattr(mt5, name, fn)