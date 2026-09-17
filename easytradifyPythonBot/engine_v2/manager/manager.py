"""Trade manager: the live mirror of engine_v2/sim/outcome.py. Pure decision function.

Given a setup record, its live state and the current closed-bar Context, returns the actions to take.
The same thesis rules as replay (engine_v2/thesis.py); the same target/breakeven/time-stop rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine_v2.data.clock import TF_SECONDS
from engine_v2.thesis import NEVER, earliest_break


@dataclass
class LiveState:
    status: str                      # PENDING | FILLED
    fill_time: int | None = None
    fill_price: float | None = None
    targets_hit: int = 0
    remaining_share: float = 1.0
    current_stop: float | None = None
    extra: dict = field(default_factory=dict)


def decide(setup, state: LiveState, ctx, now: int, bid: float, ask: float) -> list[dict]:
    """Actions: CANCEL_PENDING, CLOSE_ALL, CLOSE_PARTIAL(share), MOVE_STOP(price)."""
    actions: list[dict] = []
    d = setup.direction
    if state.status == "PENDING":
        if now >= setup.valid_until:
            return [{"action": "CANCEL_PENDING", "reason": "valid_until reached"}]
        t = earliest_break(setup.thesis, ctx, "pending", 0, setup.created_at, now)
        if t != NEVER and t <= now:
            return [{"action": "CANCEL_PENDING", "reason": "thesis broken before fill"}]
        return actions

    if state.status != "FILLED":
        return actions
    exit_px = bid if d > 0 else ask
    mg = setup.management or {}
    ts = mg.get("time_stop_bars")
    if ts and now >= state.fill_time + ts * TF_SECONDS[setup.timeframe]:
        return [{"action": "CLOSE_ALL", "reason": "time stop"}]
    t = earliest_break(setup.thesis, ctx, "open", state.targets_hit, state.fill_time, now)
    if t != NEVER and t <= now:
        return [{"action": "CLOSE_ALL", "reason": "thesis broken"}]
    k = state.targets_hit
    if k < len(setup.targets) - 1:           # the last target is the broker TP
        tp = float(setup.targets[k]["price"])
        if (exit_px - tp) * d >= 0:
            share = float(setup.targets[k]["share"])
            actions.append({"action": "CLOSE_PARTIAL", "share": share, "reason": f"target{k + 1}"})
            if mg.get("breakeven_after_target") == k + 1:
                actions.append({"action": "MOVE_STOP", "price": state.fill_price, "reason": "breakeven"})
    return actions


def apply_actions(state: LiveState, actions: list[dict]) -> LiveState:
    for a in actions:
        if a["action"] == "CLOSE_PARTIAL":
            state.remaining_share = max(0.0, state.remaining_share - a["share"])
            state.targets_hit += 1
        elif a["action"] == "MOVE_STOP":
            state.current_stop = a["price"]
        elif a["action"] in ("CLOSE_ALL", "CANCEL_PENDING"):
            state.remaining_share = 0.0
            state.status = "CLOSED"
    return state
