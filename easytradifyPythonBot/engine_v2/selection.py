"""Selection: the tradeable setup with the highest REAL probability (known and affordable)."""
from __future__ import annotations


def tradeable(setup) -> bool:
    """Known probability, measured positive net R for its cell, and affordable at the user's risk."""
    p = setup.probability
    return (p.get("value") is not None and (p.get("net_r") or 0) > 0 and bool(setup.risk.get("affordable")))


def select(setups: list) -> object | None:
    candidates = [s for s in setups if tradeable(s)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.probability["value"], s.probability.get("n", 0)))
