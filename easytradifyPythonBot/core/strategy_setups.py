# ============================================================
# STRATEGY SETUPS -- each strategy group trades its own setup
# ============================================================
# FILE: core/strategy_setups.py
#
# The strategy-group auction (core/strategy_groups.py) picks the group whose
# reading is strongest. Until 2026-09-17 every group then went through ONE entry:
# a supply/demand discount, a confirmation candle and tick timing, traded with the
# account's margin-first stop (about 1 pip on EURUSD). The trade setups the
# strategies already compute (core/asset_analysis_smc.py) were published and
# never traded.
#
# Now the winning group trades its own setup when it has one:
#
#   group            setups, in order (the first valid one is traded)
#   SMC              SMC trade setup (elite confluence) -> FVG/IFVG retest
#   MEAN_REVERSION   Bollinger band extreme -> RSI divergence reversal ->
#                    stochastic divergence reversal (all three fade an extreme
#                    back toward value, which is what this group trades)
#   TREND            fresh EMA crossover. It exits on a signal the monitor does
#                    not manage, so its stop is kept and the target is the
#                    analysis's own take-profit, at least the minimum R:R.
#   WAVE             wave C reversal
#   MOMENTUM, STRUCTURE, ORDER_FLOW: no setup of their own -- the entry rule
#                    table and the account levels decide, as before. CROSS_ASSET
#                    is advisory and never decides a trade.
#
# A setup is traded only when it is valid (is_perfect_setup), on the side the
# analysis trades, its levels sit on the correct sides of the entry, and its OWN
# target pays at least the minimum risk:reward NET of the spread (1:1.2,
# asset_analysis_config.MIN_ABSOLUTE_RISK_REWARD). The target stays the
# strategy's -- SMC the next opposing structure swing, mean reversion the middle
# band / Fibonacci retracement, wave C the wave B pivot, FVG/IFVG the nearest
# swing -- and is never stretched to reach the minimum: a setup that cannot pay
# 1:1.2 is not traded. Its stop and target become the trade's. The lot is the
# $200 margin-first lot shrunk until the loss at that stop fits the $4 budget --
# never larger (the operator's sizing;
# the setups size it that way themselves, and core/execution.execute_trade keeps
# the stop and re-checks the lot when the order goes out).
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

STRATEGY_SETUPS_VERSION = "1.0"

# group -> setup names, in the order they are tried
GROUP_SETUPS: Dict[str, Tuple[str, ...]] = {
    "SMC": ("smc_trade", "fvg_ifvg"),
    "MEAN_REVERSION": ("bb_mean_reversion", "rsi_reversal", "stochastic_reversal"),
    "TREND": ("ema_crossover",),
    "WAVE": ("wave_c",),
    # MOMENTUM has no setup of its own. The stochastic reversal was filed here
    # (core/analysis_groups.py files the stochastic reading under MOMENTUM), but
    # it fades a divergence back to a Fibonacci retracement -- a mean-reversion
    # trade, not a continuation. Momentum trades the generic rules until it has
    # a continuation setup (the TTM squeeze release has no stop or target yet).
}

SETUP_TITLES: Dict[str, str] = {
    "smc_trade": "SMC trade setup",
    "fvg_ifvg": "FVG/IFVG retest",
    "bb_mean_reversion": "Bollinger mean reversion",
    "rsi_reversal": "RSI divergence reversal",
    "stochastic_reversal": "Stochastic divergence reversal",
    "ema_crossover": "EMA crossover",
    "wave_c": "Wave C reversal",
}


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _levels_ok(setup: Mapping[str, Any], direction: str) -> Tuple[bool, str]:
    entry, stop, target = (_num(setup.get(k)) for k in ("entry_price", "stop_loss", "take_profit"))
    if entry is None or stop is None:
        return False, "entry or stop missing"
    if (direction == "BUY" and not stop < entry) or (direction == "SELL" and not stop > entry):
        return False, f"stop {stop} is on the wrong side of entry {entry}"
    if target is not None and ((direction == "BUY" and not target > entry)
                               or (direction == "SELL" and not target < entry)):
        return False, f"target {target} is on the wrong side of entry {entry}"
    return True, ""


def pick(group: Optional[str], setups: Mapping[str, Mapping[str, Any]], direction: str,
         spread_pips: float = 0.0, min_rr: Optional[float] = None) -> Dict[str, Any]:
    """The setup the winning group trades, or why it has none.

    spread_pips / min_rr: the setup's own target must pay min_rr (default
    MIN_ABSOLUTE_RISK_REWARD) net of the spread, as the R:R gate judges it.

    valid: True  -> trade this setup's stop, target and lot
           False -> the group has setups and none is valid now (the entry rule
                    "setup" fails)
           None  -> the group has no setup of its own (the rule is not measurable)
    """
    group = str(group or "").upper() or None
    direction = str(direction or "").upper()
    if min_rr is None:
        from core.asset_analysis_config import MIN_ABSOLUTE_RISK_REWARD as min_rr
    spread = max(0.0, _num(spread_pips) or 0.0)
    names = GROUP_SETUPS.get(group or "", ())
    out: Dict[str, Any] = {"version": STRATEGY_SETUPS_VERSION, "group": group, "has_setups": bool(names),
                           "candidates": list(names), "name": None, "valid": None}
    if not names:
        out["why"] = f"{group or 'no winning group'} has no trade setup of its own"
        return out

    refusals = []
    for name in names:
        setup = setups.get(name) or {}
        if not setup.get("is_perfect_setup"):
            refusals.append(f"{name}: {setup.get('reason') or 'not evaluated'}")
            continue
        if str(setup.get("direction") or "").upper() != direction:
            refusals.append(f"{name}: setup side {setup.get('direction')} is not the traded side {direction}")
            continue
        ok, why = _levels_ok(setup, direction)
        if not ok:
            refusals.append(f"{name}: {why}")
            continue
        entry, stop, target = (_num(setup.get(k)) for k in ("entry_price", "stop_loss", "take_profit"))
        risk_pips, reward_pips = _num(setup.get("risk_pips")), _num(setup.get("reward_pips"))
        net_rr = None
        if target is not None and risk_pips and reward_pips is not None:
            net_rr = (reward_pips - spread) / risk_pips
            if net_rr < min_rr - 1e-9:
                refusals.append(f"{name}: its target pays 1:{net_rr:.2f} net of the {spread:.1f}p spread, "
                                f"below the 1:{min_rr:g} minimum")
                continue
        out.update({
            "valid": True,
            "name": name,
            "title": SETUP_TITLES.get(name, name),
            "why": f"{SETUP_TITLES.get(name, name)} valid for {group}",
            "direction": direction,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "risk_pips": risk_pips,
            "reward_pips": reward_pips,
            "risk_reward_ratio": setup.get("risk_reward_ratio"),
            "net_risk_reward": None if net_rr is None else round(net_rr, 2),
            "lot_size": _num(setup.get("lot_size")),
            "projected_risk_usd": _num(setup.get("projected_risk_usd")),
            "exit_type": setup.get("exit_type") or ("TARGET" if target is not None else "SIGNAL_EXIT"),
            "stop_loss_basis": setup.get("stop_loss_basis"),
            "take_profit_basis": setup.get("take_profit_basis"),
        })
        return out

    out.update(valid=False, why="; ".join(refusals))
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "strategy_setups", "version": STRATEGY_SETUPS_VERSION,
            "groups": {g: list(n) for g, n in GROUP_SETUPS.items()}}
