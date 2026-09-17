"""Execution: turn a Setup into broker requests. Pending orders (LIMIT/STOP) or a market deal.

Nothing is sent unless a broker object with `live=True` is used AND V2_LIVE_ORDERS is True.
The order carries the initial stop and the LAST target as broker SL/TP; partial exits and
breakeven are the trade manager's job (engine_v2/manager/manager.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

V2_LIVE_ORDERS = False
V2_MAGIC = 2002
DEVIATION_POINTS = 20


def _round(price: float, digits: int) -> float:
    return round(float(price), digits)


def build_request(setup, lot: float, digits: int, mt5_consts) -> dict:
    """MT5 order_send request for the setup's entry. mt5_consts: the MetaTrader5 module (or a stub)."""
    buy = setup.side == "BUY"
    ot = setup.entry["order_type"]
    if ot == "MARKET":
        action = mt5_consts.TRADE_ACTION_DEAL
        otype = mt5_consts.ORDER_TYPE_BUY if buy else mt5_consts.ORDER_TYPE_SELL
        filling = mt5_consts.ORDER_FILLING_IOC
    else:
        action = mt5_consts.TRADE_ACTION_PENDING
        if ot == "LIMIT":
            otype = mt5_consts.ORDER_TYPE_BUY_LIMIT if buy else mt5_consts.ORDER_TYPE_SELL_LIMIT
        else:
            otype = mt5_consts.ORDER_TYPE_BUY_STOP if buy else mt5_consts.ORDER_TYPE_SELL_STOP
        filling = mt5_consts.ORDER_FILLING_RETURN
    req = {
        "action": action, "symbol": setup.symbol, "volume": float(lot), "type": otype,
        "price": _round(setup.entry["price"], digits),
        "sl": _round(setup.stop["price"], digits),
        "tp": _round(setup.targets[-1]["price"], digits),
        "deviation": DEVIATION_POINTS, "magic": V2_MAGIC,
        "comment": f"v2 {setup.category[:6]} {setup.variant[:10]}"[:31],
        "type_time": mt5_consts.ORDER_TIME_GTC, "type_filling": filling,
    }
    return req


@dataclass
class DryRunBroker:
    """Records requests instead of sending them. Used in tests and in shadow mode."""
    live: bool = False
    sent: list = field(default_factory=list)

    def send(self, request: dict) -> dict:
        self.sent.append(request)
        return {"retcode": "DRY_RUN", "request": request}


class MT5Broker:
    live = True

    def __init__(self):
        import MetaTrader5 as mt5
        self.mt5 = mt5

    def send(self, request: dict) -> dict:
        if not V2_LIVE_ORDERS:
            return {"retcode": "BLOCKED", "reason": "V2_LIVE_ORDERS is False", "request": request}
        result = self.mt5.order_send(request)
        return {"retcode": getattr(result, "retcode", None), "order": getattr(result, "order", None),
                "comment": getattr(result, "comment", None), "request": request}

    def cancel(self, order_ticket: int) -> dict:
        return self.send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": int(order_ticket)})

    def modify_sl(self, position_ticket: int, symbol: str, sl: float, tp: float) -> dict:
        return self.send({"action": self.mt5.TRADE_ACTION_SLTP, "position": int(position_ticket),
                          "symbol": symbol, "sl": float(sl), "tp": float(tp)})


def place(setup, broker, digits: int, mt5_consts) -> dict:
    if not setup.risk.get("affordable") or setup.risk.get("lot", 0) <= 0:
        return {"retcode": "NOT_TRADEABLE", "reason": setup.risk.get("reason")}
    if setup.probability.get("value") is None and getattr(broker, "live", False):
        return {"retcode": "NOT_TRADEABLE", "reason": "probability unknown"}
    return broker.send(build_request(setup, setup.risk["lot"], digits, mt5_consts))
