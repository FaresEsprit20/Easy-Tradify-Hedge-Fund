# ============================================================
# BROKER FACTS -- WHAT THE SERVER SAYS, NOT WHAT WE INFER
# ============================================================
# FILE: core/broker_facts.py
#
# Two questions that must never be answered by guesswork, because a wrong
# answer becomes a trade's stored LABEL and nothing downstream can tell it
# apart from a measured one:
#
#   how did this position actually close?   -> closing_deal()
#   what is this symbol's contract size?    -> contract_size()
#
# WHY THIS MODULE EXISTS SEPARATELY
# ---------------------------------
# Both the monitor (monitor/monitor_core.py) and the copy-trade controller
# (api/execute_copy_trade.py) reconstruct a close when a position disappears
# from the open list. They had SEPARATE, IDENTICAL copies of that logic, and
# both copies carried the same two defects:
#
#   1. `price_close = sl` whenever the trade-history lookup missed -- which it
#      routinely does in the moment right after a close. That assumes every
#      trade closed at its stop, which is false for any manual or webhook
#      close.
#
#   2. `profit = move * volume * 100000`. 100000 is the FX contract size.
#      UKOIL and XAUUSD are not FX.
#
# Measured live: a UKOIL SELL recorded "profit" of $8,500.00 on a fraction of
# a lot, and a XAUUSD SELL worth +$4.77 was stored as -$3,960.00. Fixing one
# copy and leaving the other is how the second one survives, so the logic
# lives here once and both callers import it.
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BROKER_FACTS_VERSION = "1.0"


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def contract_size(mt5_symbol: str) -> Optional[float]:
    """
    The symbol's contract size, from the broker.

    Returns None rather than a default when it cannot be determined. A default
    of 100000 is what produced the errors above; a caller that cannot size the
    contract must decline to compute a profit, not scale by a guess.
    """
    try:
        info = _mt5().symbol_info(mt5_symbol)
        size = getattr(info, "trade_contract_size", None) if info else None
        return float(size) if size else None
    except Exception as exc:
        logger.debug("contract_size failed for %s: %s", mt5_symbol, exc)
        return None


def closing_deal(ticket: Any, retries: int = 4,
                 delay: float = 0.5) -> Optional[Dict[str, Any]]:
    """
    How the broker says the position closed: exit price, volume, realised P/L.

    `history_deals_get(position=...)` returns the deals belonging to one
    position; the DEAL_ENTRY_OUT rows are the closes. This is the authority on
    both exit and profit -- it already accounts for slippage, swap, commission
    and partial fills, none of which a reconstruction can know.

    Costs are summed over EVERY deal on the position, not just the closing
    ones: entry carries its own commission, and on a small position that is a
    large share of the result. Price and volume come from the closing deals
    only, volume-weighted so a position closed in parts yields one honest
    average exit rather than whichever fill happened to be last.

    Retried briefly because the deal is not always visible in the terminal's
    history the instant the position leaves the open list -- that race is
    exactly what sent the old code to its fallback.

    Returns None when the broker has no answer. Callers MUST NOT substitute a
    guess: a trade stored with a fabricated exit is worse than a trade not
    stored at all.
    """
    mt5 = None
    for attempt in range(retries):
        try:
            mt5 = mt5 or _mt5()
            deals = mt5.history_deals_get(position=int(ticket))
        except Exception as exc:
            logger.debug("history_deals_get failed for %s: %s", ticket, exc)
            deals = None

        if deals:
            out_entries = {getattr(mt5, "DEAL_ENTRY_OUT", 1),
                           getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)}
            closes = [d for d in deals if getattr(d, "entry", None) in out_entries]
            if closes:
                volume = sum(float(getattr(d, "volume", 0) or 0) for d in closes)
                profit = sum(float(getattr(d, "profit", 0) or 0)
                             + float(getattr(d, "swap", 0) or 0)
                             + float(getattr(d, "commission", 0) or 0)
                             for d in deals)
                if volume > 0:
                    price = sum(float(getattr(d, "price", 0) or 0)
                                * float(getattr(d, "volume", 0) or 0)
                                for d in closes) / volume
                    return {"price_close": price, "profit": profit,
                            "volume": volume}

        if attempt < retries - 1:
            time.sleep(delay)

    return None


def profit_from_prices(mt5_symbol: str, direction: Optional[str],
                       price_open: float, price_close: float,
                       volume: float) -> Optional[float]:
    """
    Profit implied by two prices -- the LAST resort, after closing_deal().

    Returns None, meaning "cannot say", unless every input is known. It needs
    the direction and the contract size, and it will not proceed without
    either.

    THE TWO WAYS THIS WAS WRITTEN WRONG, both of which corrupted the label
    every model trains on:

      if price_close > price_open:
          profit = (price_close - price_open) * volume * 100000
      else:
          profit = (price_open - price_close) * volume * 100000

    Both branches are POSITIVE. This is the absolute price move, so every
    trade came out a winner no matter which way it was placed or how it
    ended -- a 100% win rate manufactured in the profit field. And 100000 is
    the FX contract size; on UKOIL it produced $8,500.00 for a fraction of a
    lot, on XAUUSD -$3,960.00 for a +$4.77 trade.

    The sign must come from the DIRECTION, and the scale from the broker.
    """
    if not price_open or not price_close or not volume:
        return None

    side = str(direction or "").strip().upper()
    if side not in ("BUY", "SELL"):
        logger.warning("profit_from_prices: unknown direction %r for %s - "
                       "refusing to guess a sign", direction, mt5_symbol)
        return None

    size = contract_size(mt5_symbol)
    if not size:
        logger.warning("profit_from_prices: no contract size for %s - "
                       "refusing to scale by a guess", mt5_symbol)
        return None

    move = (price_close - price_open) if side == "BUY" else (price_open - price_close)
    return move * volume * size


# ============================================================
# SPREAD, REWARD:RISK AND SLIPPAGE
# ============================================================
# Three trade fields were never measured, and two of them were stored as a
# confident-looking constant instead of an absence:
#
#   spread_at_entry         None on 121/121 trades. The writer read
#                           `spread_pips` from the execute_trade response,
#                           which never contained that key (it lives in
#                           get_symbol_info, a different function).
#   risk_reward_ratio       None on 121/121. A TradeResult field that nothing
#                           anywhere ever assigned.
#   close_data.exit_spread  0.0 on every closed trade -- a hardcoded literal.
#   close_data.exit_slippage 0.0 on every closed trade -- same literal.
#   price_evolution[].spread 0 on every point: `position.get("spread", 0)`,
#                           and an MT5 position object has no spread attribute.
#
# A stored 0.0 spread is worse than a missing one: it reads as "the broker
# charged nothing", and any cost analysis built on it concludes the platform
# trades for free.


def pip_size(mt5_symbol: str) -> Optional[float]:
    """The pip size the rest of the platform uses for this symbol.

    Delegates to core.execution.get_pip_info so a spread stored here is in the
    same unit as the stop distances and the analysis snapshot's spread_pips --
    three different pip conventions in one document would make every
    comparison between them wrong by a factor of ten.
    """
    try:
        mt5 = _mt5()
        info = mt5.symbol_info(mt5_symbol)
        if info is None:
            return None
        from core.execution import get_pip_info  # lazy: avoids an import cycle
        size, _, _ = get_pip_info(info)
        return float(size) if size else None
    except Exception as exc:
        logger.debug(f"[broker_facts] pip_size({mt5_symbol}) failed: {exc}")
        return None


def spread_now_pips(mt5_symbol: str) -> Optional[float]:
    """The live spread, in pips. None if MT5 will not quote the symbol."""
    try:
        tick = _mt5().symbol_info_tick(mt5_symbol)
        pip = pip_size(mt5_symbol)
        if not tick or not pip or not tick.ask or not tick.bid or tick.ask < tick.bid:
            return None
        return round((tick.ask - tick.bid) / pip, 2)
    except Exception as exc:
        logger.debug(f"[broker_facts] spread_now_pips({mt5_symbol}) failed: {exc}")
        return None


# ------------------------------------------------------------
# BROKER CLOCK
# ------------------------------------------------------------
# MT5 stamps ticks and deals in the BROKER'S clock, encoded as if it were UTC,
# and copy_ticks_range() expects that same clock. This broker runs UTC+3 while
# US daylight saving is in force and UTC+2 otherwise (the usual "New York close
# = midnight" convention). Measured 2026-09-14: live tick time - UTC = 10,799.5 s,
# and every opening deal sits 10,799.9 s after the trade's stored UTC opened_at.
#
# Before this, spread_at_pips() queried ticks at the UTC instant, i.e. three
# hours BEFORE the moment it claimed to measure; the backfilled entry spreads
# and every "tick_at_detection" exit spread came from the wrong time.

_OFFSET_CACHE: Dict[str, Any] = {"at": 0.0, "seconds": None}


def _us_dst(moment) -> bool:
    """US daylight saving: second Sunday of March 07:00 UTC to first Sunday of November 06:00 UTC."""
    from datetime import datetime, timedelta, timezone

    year = moment.year
    march = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)
    november = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
    end = november + timedelta(days=(6 - november.weekday()) % 7)
    return start <= moment < end


def broker_offset_seconds(moment: Any = None) -> int:
    """Broker clock minus UTC, in seconds, at `moment` (a UTC datetime; default now).

    Measured from a fresh live tick when the market is open, then shifted by an
    hour if `moment` falls in the other daylight-saving regime than now. When no
    fresh tick exists (weekend) the convention above is used directly.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    moment = moment or now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    rule = lambda m: 3 * 3600 if _us_dst(m) else 2 * 3600  # noqa: E731

    measured = _OFFSET_CACHE["seconds"] if time.time() - _OFFSET_CACHE["at"] < 600 else None
    if measured is None:
        try:
            mt5 = _mt5()
            for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
                tick = mt5.symbol_info_tick(symbol)
                if not tick or not getattr(tick, "time_msc", 0):
                    continue
                raw = tick.time_msc / 1000.0 - time.time()
                rounded = round(raw / 3600.0) * 3600
                if abs(raw - rounded) < 120:        # fresh tick: clock reading is exact
                    measured = int(rounded)
                    break
        except Exception as exc:
            logger.debug(f"[broker_facts] broker offset measurement failed: {exc}")
        if measured is not None:
            _OFFSET_CACHE.update(at=time.time(), seconds=measured)

    if measured is None:
        return rule(moment)
    return measured + (rule(moment) - rule(now))


def to_broker_clock(moment: Any):
    """A UTC datetime expressed in the broker clock copy_ticks_range() expects."""
    from datetime import timedelta, timezone

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment + timedelta(seconds=broker_offset_seconds(moment))


def from_broker_clock(moment: Any):
    """A broker-clock datetime (tick/deal time) converted to true UTC."""
    from datetime import timedelta, timezone

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    guess = moment - timedelta(seconds=broker_offset_seconds(moment))
    return moment - timedelta(seconds=broker_offset_seconds(guess))


def price_at(mt5_symbol: str, moment: Any, side: str,
             window_seconds: float = 5.0) -> Optional[float]:
    """The bid or ask nearest a past UTC instant, from tick history.

    `side` is "bid" or "ask". None when no tick lies within the window.
    """
    try:
        from datetime import datetime, timedelta, timezone

        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        if not isinstance(moment, datetime) or side not in ("bid", "ask"):
            return None
        broker = to_broker_clock(moment)
        mt5 = _mt5()
        mt5.symbol_select(mt5_symbol, True)
        ticks = mt5.copy_ticks_range(mt5_symbol, broker - timedelta(seconds=window_seconds),
                                     broker + timedelta(seconds=window_seconds), mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            return None
        target_ms = broker.timestamp() * 1000.0
        valid = [t for t in ticks if t[side] > 0]
        if not valid:
            return None
        return float(min(valid, key=lambda t: abs(float(t["time_msc"]) - target_ms))[side])
    except Exception as exc:
        logger.debug(f"[broker_facts] price_at({mt5_symbol}) failed: {exc}")
        return None


def spread_at_pips(mt5_symbol: str, moment: Any,
                   window_seconds: float = 30.0) -> Optional[float]:
    """The spread at a PAST instant, from MT5's tick history.

    Tick history is market data, not account data, so this works for trades
    placed on any of the platform's MT5 accounts regardless of which one the
    terminal is logged into now -- unlike deal history, which only covers the
    current login. Measured back to the oldest stored trade.

    Takes the tick nearest `moment` within +/- window_seconds. Returns None when
    there is no tick in the window (history expired, market closed) rather than
    widening the search: a spread from ten minutes away can differ wildly
    around news or the daily rollover, and would be recorded as if exact.
    """
    try:
        from datetime import datetime, timedelta, timezone

        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        if not isinstance(moment, datetime):
            return None
        if moment.tzinfo is None:
            # Stored timestamps are naive UTC (opened_at) or UTC datetimes.
            moment = moment.replace(tzinfo=timezone.utc)

        mt5 = _mt5()
        mt5.symbol_select(mt5_symbol, True)
        pip = pip_size(mt5_symbol)
        if not pip:
            return None

        moment = to_broker_clock(moment)   # `moment` is UTC; ticks are broker clock
        ticks = mt5.copy_ticks_range(
            mt5_symbol,
            moment - timedelta(seconds=window_seconds),
            moment + timedelta(seconds=window_seconds),
            mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            return None

        target_ms = moment.timestamp() * 1000.0
        valid = [t for t in ticks if t["ask"] > 0 and t["bid"] > 0 and t["ask"] >= t["bid"]]
        if not valid:
            return None
        nearest = min(valid, key=lambda t: abs(float(t["time_msc"]) - target_ms))
        return round((float(nearest["ask"]) - float(nearest["bid"])) / pip, 2)

    except Exception as exc:
        logger.debug(f"[broker_facts] spread_at_pips({mt5_symbol}) failed: {exc}")
        return None


def close_moment(ticket: Any) -> Optional[Any]:
    """When the position's closing deal actually executed, as a UTC datetime.

    The close path runs when the monitor NOTICES a position has gone, which can
    be a whole scan interval after the broker closed it. A spread read at
    detection time is a spread from the wrong moment; around a news release or
    the daily rollover the two can differ by several pips.

    Only covers positions on the account the terminal is currently logged into
    -- deal history is per-account. Returns None otherwise, and the caller
    falls back to detection time with that fact recorded.
    """
    try:
        from datetime import datetime, timezone

        mt5 = _mt5()
        deals = mt5.history_deals_get(position=int(ticket))
        if not deals:
            return None
        out_entries = {getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)}
        closes = [d for d in deals if getattr(d, "entry", None) in out_entries]
        if not closes:
            return None
        last_ms = max(float(getattr(d, "time_msc", 0) or 0) for d in closes)
        if last_ms <= 0:
            return None
        # Deal time is broker clock; return true UTC like every stored timestamp.
        return from_broker_clock(datetime.fromtimestamp(last_ms / 1000.0, tz=timezone.utc))
    except Exception as exc:
        logger.debug(f"[broker_facts] close_moment({ticket}) failed: {exc}")
        return None


def risk_usd_at_stop(mt5_symbol: str, direction: Optional[str], volume: Any,
                     entry: Any, stop: Any) -> Optional[float]:
    """What the position loses, in account currency, if it fills exactly at its stop.

    Asked of the broker (order_calc_profit), so contract size and the quote ->
    USD conversion are the broker's, not a pip-value formula. Excludes
    commission, which is charged regardless of where the trade exits.
    The sizing field `actual_risk_usd` is NOT this: measured against the deals
    it understates the loss at the stop on a large share of trades.
    """
    side = (direction or "").upper()
    try:
        volume_f, entry_f, stop_f = float(volume), float(entry), float(stop)
    except (TypeError, ValueError):
        return None
    if side not in ("BUY", "SELL") or not volume_f or not entry_f or not stop_f:
        return None
    try:
        mt5 = _mt5()
        order = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(order, mt5_symbol, volume_f, entry_f, stop_f)
        return round(abs(float(loss)), 2) if loss is not None else None
    except Exception as exc:
        logger.debug(f"[broker_facts] risk_usd_at_stop({mt5_symbol}) failed: {exc}")
        return None


def risk_reward_ratio(entry: Any, stop: Any, target: Any) -> Optional[float]:
    """Reward divided by risk, from the prices the order was ACTUALLY placed at.

    Deliberately not the analysis snapshot's ratio. That one is computed before
    sizing, and the sizer moves the stop to hit the dollar-risk target -- so the
    analysis might say 7.27 for a trade that went out at 1.6. The executed
    prices are the only ones the market ever saw.

    None when a price is missing or the stop sits on the entry (a zero-risk
    trade has no ratio; returning infinity would be quoted as a real number).
    """
    try:
        entry_f, stop_f, target_f = float(entry), float(stop), float(target)
    except (TypeError, ValueError):
        return None
    if not entry_f or not stop_f or not target_f:
        return None

    risk = abs(entry_f - stop_f)
    reward = abs(target_f - entry_f)
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def exit_slippage_pips(mt5_symbol: str, direction: Optional[str],
                       close_reason: Optional[str], close_price: Any,
                       stop: Any, target: Any) -> Optional[float]:
    """How far the fill landed from the level that triggered the close, in pips.

    Positive = filled WORSE than the level; negative = price improvement.

    Only defined for a stop or target hit, where there IS a requested level.
    A manual, EA or unknown close had no target price, so there is nothing to
    slip against and the answer is None -- not 0.0, which would claim a perfect
    fill that was never measured.
    """
    reason = (close_reason or "").upper()
    if "STOP" in reason or reason in ("SL", "SL_HIT"):
        level = stop
    elif "TAKE" in reason or "PROFIT" in reason or reason in ("TP", "TP_HIT"):
        level = target
    else:
        return None

    side = (direction or "").upper()
    if side not in ("BUY", "SELL"):
        return None

    try:
        level_f, close_f = float(level), float(close_price)
    except (TypeError, ValueError):
        return None
    if not level_f or not close_f:
        return None

    pip = pip_size(mt5_symbol)
    if not pip:
        return None

    # For a BUY, filling BELOW the level is adverse on both a stop and a
    # target; for a SELL, filling above it is. One expression covers all four.
    adverse = (level_f - close_f) * (1 if side == "BUY" else -1)
    # `+ 0.0` folds -0.0 into 0.0; otherwise a perfect fill on a SELL
    # serialises as "-0.0" and reads like a tiny price improvement.
    return round(adverse / pip, 2) + 0.0


def get_status() -> Dict[str, Any]:
    return {"component": "broker_facts", "version": BROKER_FACTS_VERSION}


def self_check() -> Dict[str, Any]:
    """
    Plant a known answer and require recovery, including the negative case --
    a check that cannot fail is indistinguishable from a stub returning
    success.
    """
    import sys
    import types

    findings = []
    real = sys.modules.get("MetaTrader5")

    class _Deal:
        def __init__(self, entry, price, volume, profit, swap=0.0, commission=0.0):
            self.entry, self.price, self.volume = entry, price, volume
            self.profit, self.swap, self.commission = profit, swap, commission

    fake = types.SimpleNamespace(
        DEAL_ENTRY_OUT=1,
        DEAL_ENTRY_OUT_BY=3,
        # The real XAUUSD trade: entry and exit each charged 0.32 commission.
        history_deals_get=lambda **kw: [
            _Deal(0, 4396.21, 0.09, 0.0, commission=-0.32),
            _Deal(1, 4396.51, 0.09, -2.70, commission=-0.32),
        ],
        symbol_info=lambda s: types.SimpleNamespace(trade_contract_size=100.0),
    )
    sys.modules["MetaTrader5"] = fake
    try:
        deal = closing_deal(1, retries=1, delay=0)
        if not deal:
            findings.append("closing_deal found nothing in a planted history")
        else:
            if abs(deal["price_close"] - 4396.51) > 1e-6:
                findings.append(f"exit price {deal['price_close']} != 4396.51")
            # -2.70 plus BOTH commissions.
            if abs(deal["profit"] - (-3.34)) > 1e-6:
                findings.append(
                    f"profit {deal['profit']} != -3.34 (entry commission dropped?)")
        if contract_size("XAUUSD") != 100.0:
            findings.append("contract_size did not read trade_contract_size")

        # Negative case: no closing deal must yield None, never a guess.
        fake.history_deals_get = lambda **kw: [_Deal(0, 4396.21, 0.09, 0.0)]
        if closing_deal(1, retries=1, delay=0) is not None:
            findings.append("an entry-only history produced a close")

        fake.symbol_info = lambda s: None
        if contract_size("XAUUSD") is not None:
            findings.append("contract_size invented a size for an unknown symbol")
    finally:
        if real is not None:
            sys.modules["MetaTrader5"] = real
        else:
            sys.modules.pop("MetaTrader5", None)

    return {"component": "broker_facts", "ok": not findings, "findings": findings}
