"""Risk belongs to the user: risk = risk_per_trade x fixed_trade_size_usd, capped; the lot follows the stop."""
from __future__ import annotations

import math

from engine_v2.data.symbols import facts

MAX_RISK_PER_TRADE = 0.02   # same cap as v1's core/asset_analysis_config.py (2% of the budget)
MAX_RISK_OVERSHOOT = 1.10   # a minimum lot may risk at most 10% more than asked


def size(setup, fixed_trade_size_usd: float, risk_per_trade: float) -> dict:
    fx = facts(setup.symbol)
    rpt = min(float(risk_per_trade), MAX_RISK_PER_TRADE)
    risk_usd = float(fixed_trade_size_usd) * rpt
    stop_distance = abs(float(setup.entry["price"]) - float(setup.stop["price"]))
    if stop_distance <= 0 or risk_usd <= 0:
        return {"usd": risk_usd, "lot": 0.0, "affordable": False, "reason": "no risk or no stop distance"}
    usd_per_lot = stop_distance * fx.usd_per_price_unit_per_lot
    raw_lot = risk_usd / usd_per_lot
    lot = math.floor(raw_lot / fx.volume_step + 1e-9) * fx.volume_step
    if lot < fx.volume_min:
        at_min = usd_per_lot * fx.volume_min
        if at_min <= risk_usd * MAX_RISK_OVERSHOOT:
            return {"usd": round(at_min, 2), "lot": fx.volume_min, "affordable": True,
                    "reason": f"minimum lot risks ${at_min:.2f} (asked ${risk_usd:.2f})"}
        return {"usd": round(at_min, 2), "lot": 0.0, "affordable": False,
                "reason": f"stop needs ${at_min:.2f} at minimum lot {fx.volume_min}, above ${risk_usd:.2f}"}
    return {"usd": round(lot * usd_per_lot, 2), "lot": round(lot, 2), "affordable": True,
            "reason": f"lot {lot:.2f} = ${risk_usd:.2f} / ${usd_per_lot:.2f} per lot at the stop"}
