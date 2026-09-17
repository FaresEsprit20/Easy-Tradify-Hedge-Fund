"""
ORDER-FLOW PROXIES  (prerequisite for Stage 5, Inverse RL)
==========================================================
FILE: core/order_flow_proxy.py

Bar-derived stand-ins for the order-flow footprints Stage 5 wants, and
an honest test of whether they carry a stable signal BEFORE anything is
built on top of them.

WHY THIS IS NOT STAGE 5 ITSELF

Stage 5 reverse-engineers institutional intent "from raw order flow
footprints" -- tick prints, book deltas, the sequence of who lifted
whom. This environment has none of it. The replay cache is OHLCV bars;
core/mt5_shim.py deliberately serves None for copy_ticks_from and its
own counter recorded `missing: {ticks: 1856}` -- once per decision, on
every decision. analyze_micro_structure(), the only existing
order-flow reader, is structurally unavailable in replay for the same
reason.

An IRL trained on data that does not exist cannot be trained, cannot
be validated, and would reach production unmeasured. That is the exact
failure this project has spent its effort removing, so it is not worth
reproducing with a more impressive name.

WHAT BARS CAN ACTUALLY SAY

Wyckoff's effort-versus-result, which is order-flow reasoning that
predates order-flow data: volume is effort, price displacement is
result, and the RATIO between them is informative. High effort with no
result means someone absorbed the move -- a large resting participant
on the other side. Low effort with large result means no one defended
the level.

These proxies are honest about being proxies. They are computed here,
joined to the replay's recorded outcomes, and put through the Stage 4
invariance test (core/causal_invariance.py). If they do not survive
that, an IRL over them has nothing to learn and this module is the
cheapest possible way to find that out.

Nothing here touches the live pipeline. It is a research instrument.
"""

from typing import Any, Dict, List, Optional
import logging
import os

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_PROJECT_ROOT, "replay_bars")


def _fld(row, name):
    try:
        return float(row[name])
    except (KeyError, ValueError, IndexError, TypeError):
        return None


def close_location_value(row) -> Optional[float]:
    """
    Where in its own range the bar settled. +1 closed on the high
    (buyers held it), -1 on the low (sellers did).

    The oldest order-flow proxy there is: with no tape, the close's
    position in the range is the market's own summary of who won the
    bar.
    """
    hi, lo, close = _fld(row, "high"), _fld(row, "low"), _fld(row, "close")
    if hi is None or lo is None or close is None:
        return None
    rng = hi - lo
    if rng <= 0:
        return 0.0
    return ((close - lo) - (hi - close)) / rng


def effort_vs_result(row, avg_volume: float) -> Optional[float]:
    """
    Volume spent per unit of displacement, normalised.

    High effort with little result is absorption: someone large is
    filling against the move. This is the closest a bar can come to
    seeing a resting institutional order.
    """
    hi, lo = _fld(row, "high"), _fld(row, "low")
    vol = _fld(row, "tick_volume")
    op, close = _fld(row, "open"), _fld(row, "close")
    if None in (hi, lo, vol, op, close) or avg_volume <= 0:
        return None
    body = abs(close - op)
    rng = hi - lo
    if rng <= 0:
        return None
    # displacement as a fraction of range; volume relative to its own
    # recent norm. Effort/result is high when volume is big and the
    # body is small.
    displacement = body / rng
    effort = vol / avg_volume
    return effort * (1.0 - displacement)


def displacement_strength(row, avg_volume: float) -> Optional[float]:
    """
    Conviction: a large body on heavy volume, signed by direction.

    The mirror of absorption -- price moved AND was paid for. Signed so
    that its relationship with a trade's outcome is directional rather
    than absolute.
    """
    hi, lo = _fld(row, "high"), _fld(row, "low")
    vol = _fld(row, "tick_volume")
    op, close = _fld(row, "open"), _fld(row, "close")
    if None in (hi, lo, vol, op, close) or avg_volume <= 0:
        return None
    rng = hi - lo
    if rng <= 0:
        return None
    body_frac = (close - op) / rng          # signed
    return body_frac * (vol / avg_volume)


def wick_rejection(row) -> Optional[float]:
    """
    Net wick imbalance: how hard each side was rejected.

    Positive when the lower wick dominates (buyers defended), negative
    when the upper does. A rejection wick is the bar-level trace of a
    level being defended by someone with size.
    """
    hi, lo = _fld(row, "high"), _fld(row, "low")
    op, close = _fld(row, "open"), _fld(row, "close")
    if None in (hi, lo, op, close):
        return None
    rng = hi - lo
    if rng <= 0:
        return None
    upper = hi - max(op, close)
    lower = min(op, close) - lo
    return (lower - upper) / rng


PROXY_FUNCTIONS = {
    "of_close_location": lambda row, av: close_location_value(row),
    "of_effort_vs_result": effort_vs_result,
    "of_displacement": displacement_strength,
    "of_wick_rejection": lambda row, av: wick_rejection(row),
}


def compute_proxies(bars, index: int, lookback: int = 20) -> Dict[str, Optional[float]]:
    """
    Order-flow proxies for the bar at `index`, plus short aggregates.

    Aggregates matter more than any single bar: one absorption bar is
    noise, three in a row at the same level is a participant. Strictly
    backward-looking -- index is the decision bar and nothing after it
    is read, so this cannot leak the future into a replayed decision.
    """
    if index < lookback or index >= len(bars):
        return {}

    window = bars[index - lookback:index + 1]
    vols = [_fld(r, "tick_volume") for r in window]
    vols = [v for v in vols if v is not None and v > 0]
    avg_volume = (sum(vols) / len(vols)) if vols else 0.0

    out: Dict[str, Optional[float]] = {}
    row = bars[index]
    for name, fn in PROXY_FUNCTIONS.items():
        try:
            out[name] = fn(row, avg_volume)
        except Exception:
            out[name] = None

    # Three-bar persistence of the same reads. A single bar is noise.
    for name, fn in PROXY_FUNCTIONS.items():
        vals = []
        for j in range(max(0, index - 2), index + 1):
            try:
                v = fn(bars[j], avg_volume)
            except Exception:
                v = None
            if v is not None:
                vals.append(v)
        out[f"{name}_3bar"] = (sum(vals) / len(vals)) if vals else None

    return out


def load_bars(symbol: str = "XAGUSD", timeframe: str = "M1"):
    import numpy as np
    path = os.path.join(CACHE_DIR, f"{symbol}_{timeframe}.npy")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"no cached bars at {path} -- run core/run_replay.py first")
    return np.load(path)


def attach_proxies(records: List[Dict[str, Any]], symbol: str = "XAGUSD",
                   timeframe: str = "M1") -> int:
    """
    Compute proxies for each record's decision bar and merge them into
    its `capture` dict, so the Stage 4 invariance machinery -- which
    reads capture -- can test them with no changes of its own.

    Returns how many records were enriched.
    """
    bars = load_bars(symbol, timeframe)
    n = 0
    for rec in records:
        idx = rec.get("decision_index")
        if idx is None:
            continue
        proxies = compute_proxies(bars, int(idx))
        if not proxies:
            continue
        cap = rec.setdefault("capture", {})
        cap.update(proxies)
        n += 1
    return n
