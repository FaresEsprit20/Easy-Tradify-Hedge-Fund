"""Helpers shared by category strategies (geometry only; no category imports another)."""
from __future__ import annotations

import numpy as np

from engine_v2.data.clock import in_rollover, session_of

STOP_BUFFER_ATR = 0.10
STOP_BUFFER_SPREAD = 1.5


def stop_buffer(atr_value: float, spread: float, atr_mult: float = STOP_BUFFER_ATR) -> float:
    return max(atr_mult * atr_value, STOP_BUFFER_SPREAD * max(spread, 0.0))


def at_least_r(entry: float, target: float, risk: float, d: int, min_r: float) -> float:
    """Target moved out to `min_r` R when the structural one is closer than that."""
    if (target - entry) * d < min_r * risk:
        return entry + d * min_r * risk
    return target


def two_targets(entry: float, t1: float, t2: float, risk: float, d: int, t1_min_r: float = 1.0,
                t2_min_gap_r: float = 0.5, reason1: str = "", reason2: str = "") -> list[dict]:
    t1 = at_least_r(entry, t1, risk, d, t1_min_r)
    if (t2 - t1) * d < t2_min_gap_r * risk:
        t2 = t1 + d * t2_min_gap_r * risk
    return [{"price": float(t1), "share": 0.5, "reason": reason1},
            {"price": float(t2), "share": 0.5, "reason": reason2}]


def base_context(ctx, t: int, htf: str = "H4") -> dict:
    tr = ctx.trend(htf)
    i = ctx.last_closed_index(htf, t)
    v = int(tr[i]) if i >= 0 else 0
    out = {"htf": htf, "htf_trend": v, "session": session_of(t)}
    if htf == "H4":
        out["h4_trend"] = v
    return out


def rollover(t: int, tf: str = "M15") -> bool:
    """Entries are not created inside the rollover window on intraday timeframes. From H4 up a bar close
    at 00:00 is the normal daily boundary and the fill happens later, so the rule does not apply."""
    from engine_v2.data.clock import TF_SECONDS
    if TF_SECONDS[tf] >= 14400:
        return False
    return bool(in_rollover(np.int64(t)))


def secure_half(entry: float, risk: float, d: int, last_target: dict, at_r: float) -> list[dict]:
    """v3 management: half off at +at_r R (then breakeven), the runner to the category's structure target."""
    return [{"price": float(entry + d * at_r * risk), "share": 0.5, "reason": f"secure half at +{at_r}R"},
            {"price": float(last_target["price"]), "share": 0.5, "reason": last_target.get("reason", "structure target")}]
