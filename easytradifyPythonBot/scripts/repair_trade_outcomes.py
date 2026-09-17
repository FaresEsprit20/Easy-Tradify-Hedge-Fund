# scripts/repair_trade_outcomes.py
"""
Repair the OUTCOME fields of stored closed trades: exit price, profit, and the
costs measured from them.

WHY -- THREE DEFECTS, ALL MEASURED
----------------------------------
1. Rounded exit prices. The EA formatted price_close with `_Digits`, the digits
   of the CHART it runs on. From a 2-digit chart every FX close arrived as
   1.16 / 0.58 / 0.0: 24 of 117 closed trades. Their R came out as +-30, one
   as +583.
2. Stale profit. The EA sent the last FLOATING P/L it saw before the position
   vanished, without commission. On the 36 trades whose deals the terminal
   still holds, 3 had the wrong SIGN (losses stored as wins) and 11 the wrong
   amount.
3. Broker clock. MT5 ticks and deals are stamped in broker time (UTC+3 here);
   spreads looked up "at opened_at" were read three hours early.

SOURCES, BEST FIRST (recorded per trade in close_data.*_source)
---------------------------------------------------------------
exit price
  deal           the broker's closing deal (only the logged-in account's trades)
  reported       the EA's price, kept when it is not rounded -- it IS the deal
                 price, just transported
  stop_level /   the order's stop or target, for a SL/TP close, accepted only if
  target_level   tick history shows price actually reached that level in the two
                 minutes before the close was recorded (validated on the 36
                 known trades: 0.0 pip median error)
  tick_estimate  exit-side tick 12 s before closed_at (median measured lag),
                 accepted only if it rounds to the reported value (0.2 pip
                 median error on the known trades)
  unresolved     none of the above -- the trade keeps its fields and is flagged
profit
  deal           net of commission and swap, from the deals
  reported       kept when within $0.50 of the price-implied net
  reconstructed  order_calc_profit(entry, exit) minus the commission schedule
                 measured on the deals (FX $7.03/lot, stocks $0.04/share round
                 trip); reproduces 30 of 39 checkable stored nets to $0.15

Originals are preserved once under close_data.reported, so the script is
idempotent and every change is reversible.

Usage:
    python scripts/repair_trade_outcomes.py            # dry run
    python scripts/repair_trade_outcomes.py --apply    # write
"""

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MetaTrader5 as mt5  # noqa: E402

from core.broker_facts import (exit_slippage_pips, from_broker_clock,  # noqa: E402
                               pip_size, price_at, risk_reward_ratio, risk_usd_at_stop,
                               spread_at_pips)
from core.mongo.trades_service import get_trades_service  # noqa: E402

COMMISSION_PER_LOT = {0: 7.03}      # trade_calc_mode 0 = FOREX
COMMISSION_PER_SHARE = 0.04         # exchange-traded (calc modes 2+)
DETECTION_LAG_S = 12                # median closed_at - deal time, measured
PROFIT_TOLERANCE = 0.50


def decimals(value):
    text = repr(float(value)).rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def is_rounded(price, digits, calc_mode=0):
    """An FX price (3-5 digits) that carries two decimals or fewer.

    Stocks quote in cents, so 252.87 is a complete price; only FX is checked.
    """
    return price is not None and calc_mode == 0 and digits >= 3 and decimals(price) <= 2


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def deal_facts(ticket):
    deals = mt5.history_deals_get(position=int(ticket)) or []
    closes = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
    if not closes:
        return None
    volume = sum(d.volume for d in closes)
    return {
        "price": sum(d.price * d.volume for d in closes) / volume,
        "net": round(sum(d.profit + d.commission + d.swap for d in deals), 2),
        "at": from_broker_clock(datetime.fromtimestamp(max(d.time_msc for d in closes) / 1000,
                                                       timezone.utc)),
    }


def level_reached(symbol, direction, level, closed_at, is_stop):
    """Did the exit-side price touch `level` in the 2 minutes before closed_at?"""
    side = "bid" if direction == "BUY" else "ask"
    pip = pip_size(symbol) or 0.0001
    from core.broker_facts import to_broker_clock
    end = to_broker_clock(closed_at)
    ticks = mt5.copy_ticks_range(symbol, end - timedelta(seconds=120), end, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return False
    prices = [float(t[side]) for t in ticks if t[side] > 0]
    if not prices:
        return False
    tolerance = 0.5 * pip
    # A BUY exits on the bid: its stop is hit from above, its target from below.
    falling = (direction == "BUY") == is_stop
    return (min(prices) <= level + tolerance) if falling else (max(prices) >= level - tolerance)


def recover_exit(doc, info, deal):
    close = doc["close_data"]
    reported = (close.get("reported") or {}).get("close_price", close.get("close_price"))
    if deal:
        return deal["price"], "deal"
    if not is_rounded(reported, info.digits, info.trade_calc_mode):
        return reported, "reported"

    entry, direction = doc["entry"], doc["direction"]
    closed_at = utc(doc.get("closed_at"))
    half = 0.5 * 10 ** -decimals(reported) + 1e-9
    reason = str(close.get("close_reason") or "").upper()

    if closed_at and reason in ("STOP_LOSS", "TAKE_PROFIT"):
        is_stop = reason == "STOP_LOSS"
        level = entry.get("stop_loss" if is_stop else "take_profit")
        if level and abs(level - reported) <= half and \
                level_reached(doc["symbol"], direction, level, closed_at, is_stop):
            return level, "stop_level" if is_stop else "target_level"

    if closed_at:
        side = "bid" if direction == "BUY" else "ask"
        tick = price_at(doc["symbol"], closed_at - timedelta(seconds=DETECTION_LAG_S), side,
                        window_seconds=10)
        if tick and abs(tick - reported) <= half:
            return round(tick, info.digits), "tick_estimate"
    return None, "unresolved"


def implied_net(doc, info, exit_price):
    volume = (doc.get("entry") or {}).get("volume") or doc["close_data"].get("volume")
    if not volume or not exit_price:
        return None
    order = mt5.ORDER_TYPE_BUY if doc["direction"] == "BUY" else mt5.ORDER_TYPE_SELL
    gross = mt5.order_calc_profit(order, doc["symbol"], volume, doc["entry"]["price"], exit_price)
    if gross is None:
        return None
    rate = COMMISSION_PER_LOT.get(info.trade_calc_mode)
    commission = volume * (rate if rate is not None else COMMISSION_PER_SHARE)
    return round(gross - commission, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return 1

    col = get_trades_service().collection
    stats, updates, flagged = Counter(), [], []

    for doc in col.find({"status": "CLOSED", "deleted_at": None},
                        {"trade_id": 1, "ticket": 1, "symbol": 1, "direction": 1, "entry": 1,
                         "close_data": 1, "opened_at": 1, "closed_at": 1,
                         "spread_at_entry": 1, "spread_at_entry_source": 1}):
        close = doc.get("close_data") or {}
        entry = doc.get("entry") or {}
        symbol = doc.get("symbol")
        if not entry.get("price") or close.get("close_price") is None \
                or doc.get("direction") not in ("BUY", "SELL"):
            stats["skipped_incomplete"] += 1
            continue
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        if info is None:
            # Delisted from this terminal. A deal still answers exactly;
            # without one there is nothing to check the reported values against.
            deal = deal_facts(doc["ticket"]) if doc.get("ticket") else None
            stats["unknown_symbol_" + ("deal" if deal else "left_as_reported")] += 1
            if deal:
                sets = {"close_data.close_price": deal["price"], "close_data.close_price_source": "deal",
                        "close_data.profit_usd": deal["net"], "close_data.profit_source": "deal",
                        "close_data.is_winning": deal["net"] > 0}
                if "reported" not in close:
                    sets["close_data.reported"] = {k: close.get(k) for k in ("close_price", "profit_usd")}
                updates.append((doc["_id"], doc["trade_id"], sets))
            else:
                flagged.append((doc["trade_id"], symbol, "symbol unknown to MT5, no deal: left as reported"))
            continue

        sets = {}
        if "reported" not in close:
            sets["close_data.reported"] = {k: close.get(k) for k in
                                           ("close_price", "profit_usd", "sl", "tp",
                                            "exit_spread", "exit_spread_source", "exit_slippage")}
        reported = close.get("reported") or sets["close_data.reported"]

        deal = deal_facts(doc["ticket"]) if doc.get("ticket") else None
        exit_price, exit_source = recover_exit(doc, info, deal)
        stats[f"exit_{exit_source}"] += 1
        if exit_price is None:
            flagged.append((doc["trade_id"], symbol, "exit price unresolved"))
            sets["close_data.close_price_source"] = "unresolved"
            updates.append((doc["_id"], doc["trade_id"], sets))
            continue
        sets["close_data.close_price"] = exit_price
        sets["close_data.close_price_source"] = exit_source

        # ---- profit ----
        if deal:
            profit, profit_source = deal["net"], "deal"
        else:
            net = implied_net(doc, info, exit_price)
            stored = reported.get("profit_usd")
            if net is None:
                profit, profit_source = stored, "reported_unverified"
            elif stored is not None and abs(stored - net) <= PROFIT_TOLERANCE:
                profit, profit_source = stored, "reported"
            else:
                profit, profit_source = net, "reconstructed"
        stats[f"profit_{profit_source}"] += 1
        if profit is not None and reported.get("profit_usd") is not None \
                and (profit > 0) != (reported["profit_usd"] > 0):
            stats["outcome_flipped"] += 1
        sets["close_data.profit_usd"] = profit
        sets["close_data.profit_source"] = profit_source
        sets["close_data.is_winning"] = bool(profit is not None and profit > 0)
        sets["close_data.profit_percent"] = (exit_price - entry["price"]) / entry["price"] * 100

        # ---- exit levels, slippage, exit spread ----
        stop = reported.get("sl") if not is_rounded(reported.get("sl"), info.digits, info.trade_calc_mode) and reported.get("sl") \
            else entry.get("stop_loss")
        target = reported.get("tp") if not is_rounded(reported.get("tp"), info.digits, info.trade_calc_mode) and reported.get("tp") \
            else entry.get("take_profit")
        sets["close_data.sl"], sets["close_data.tp"] = stop, target
        sets["close_data.exit_slippage"] = exit_slippage_pips(
            symbol, doc["direction"], close.get("close_reason"), exit_price, stop, target)

        exit_at = deal["at"] if deal else utc(doc.get("closed_at"))
        if exit_at:
            spread = spread_at_pips(symbol, exit_at)
            sets["close_data.exit_spread"] = spread
            sets["close_data.exit_spread_source"] = ("tick_at_deal" if deal else "tick_at_closed_at") \
                if spread is not None else None
            stats["exit_spread_measured" if spread is not None else "exit_spread_none"] += 1
        if deal and doc.get("opened_at"):
            sets["close_data.duration_seconds"] = int((deal["at"] - utc(doc["opened_at"])).total_seconds())

        # ---- entry spread: re-read with the broker clock ----
        if doc.get("spread_at_entry_source") in ("tick_history", None) and doc.get("opened_at"):
            spread = spread_at_pips(symbol, utc(doc["opened_at"]))
            if spread is not None:
                sets["spread_at_entry"] = spread
                sets["spread_at_entry_source"] = "tick_history"
                stats["entry_spread_remeasured"] += 1

        rr = risk_reward_ratio(entry.get("price"), entry.get("stop_loss"), entry.get("take_profit"))
        if rr is not None:
            sets["risk_reward_ratio"] = rr
        risk = risk_usd_at_stop(symbol, doc["direction"], entry.get("volume"),
                                entry.get("price"), entry.get("stop_loss"))
        if risk:
            sets["risk_usd_at_stop"] = risk
            stats["risk_usd_at_stop"] += 1
        updates.append((doc["_id"], doc["trade_id"], sets))

    for key in sorted(stats):
        print(f"   {key:<28} {stats[key]}")
    if flagged:
        print(f"\nflagged ({len(flagged)}):")
        for row in flagged:
            print("   ", *row)
    print("\nsample of repaired exits:")
    for _, trade_id, sets in [u for u in updates if u[2].get("close_data.close_price_source")
                              not in ("reported", "deal")][:30]:
        print(f"   {trade_id:<18} {sets.get('close_data.close_price_source'):<14} "
              f"exit {sets.get('close_data.close_price')}  profit {sets.get('close_data.profit_usd')} "
              f"({sets.get('close_data.profit_source')})")

    if not args.apply:
        print("\ndry run -- re-run with --apply to write")
        return 0
    written = sum(col.update_one({"_id": _id}, {"$set": sets}).modified_count
                  for _id, _, sets in updates)
    print(f"\nwrote {written} trade(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
