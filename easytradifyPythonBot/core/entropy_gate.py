"""
CONTEXT-TREE WEIGHTING  (Stage 3 of the decoupled AI pipeline)
==============================================================
FILE: core/entropy_gate.py

Is this order flow compressible, or is it noise?

THE IDEA

A tradable move leaves structure in the tape: runs of same-side ticks,
asymmetric pauses, a direction that persists longer than chance. Chop
does not -- it is a sequence with no exploitable regularity. Shannon
made that measurable: a compressible sequence has LOW entropy, a random
one has entropy at its theoretical maximum. Context-Tree Weighting
estimates that compressibility online, over all tree depths at once,
without needing to know the model order in advance.

So the test is not "is the market trending?" -- an indicator's guess --
but "does the recent tape contain any structure at all?", which has an
information-theoretic answer.

WHY THIS PROJECT NEEDS IT

The choppy-market veto is currently `ADX < 25`. On the measured EURUSD
replay it rejected 31 of 46 qualifying setups, and it was RIGHT to --
those setups won 22.9% against a 33.3% break-even. But ADX on M1 is a
smoothed directional-movement average over 14 bars: a slow, indirect
proxy for "is there structure here", computed from bars while the
structure it is proxying for lives in the tape.

Now that tick history exists (core/market_data.TickFeed), the question
can be asked of the tape directly, in the unit the question is actually
about.

WHAT THIS IS NOT

It is not a direction signal and cannot be traded on. Entropy is
sign-blind: it says whether the sequence is structured, never which way
it will resolve. It is an ABORT condition -- exactly the role the
pipeline spec gives it -- and it can only ever decline a trade.

It is also not yet wired into the pipeline. It is measured against
recorded outcomes first, through the Stage 4 invariance harness, and
only earns a place if it discriminates where ADX does not. That is the
same bar every other stage in this project has been held to, and three
of them have failed it.

RAM: one dict of counts bounded by 2^(depth+1). Nothing else.
"""

from typing import Any, Dict, List, Optional, Sequence
import logging
import math

logger = logging.getLogger(__name__)

# Suffix-tree depth. Each level doubles the context count, and at depth
# 6 a 200-tick window still gives ~3 observations per deepest context --
# past that the estimates are counting noise.
DEFAULT_DEPTH = 6

# Krichevsky-Trofimov smoothing. The standard 1/2 prior: an unseen
# symbol is never assigned probability zero, which would make one
# surprising tick dominate the whole estimate.
KT_ALPHA = 0.5

# Entropy above this fraction of maximum is treated as noise. 0.82 is
# the pipeline spec's figure. Deliberately NOT tuned against outcomes
# here -- a threshold fitted to this sample is a threshold that only
# works on this sample.
DEFAULT_ENTROPY_ABORT = 0.82

# Below this many usable ticks the estimate is not a measurement.
MIN_TICKS = 40


def _kt_probability(count_symbol: int, count_total: int) -> float:
    """Krichevsky-Trofimov estimator for the next symbol."""
    return (count_symbol + KT_ALPHA) / (count_total + 2 * KT_ALPHA)


def symbolize(ticks) -> List[int]:
    """
    Turn a tick sequence into binary symbols: 1 if the mid rose, 0 if it
    fell. Unchanged ticks are DROPPED rather than assigned a symbol.

    Dropping matters. A quiet tape is mostly unchanged ticks, and coding
    them as 0 would make silence look like sustained selling -- a
    perfectly compressible sequence that means nothing happened. The
    question is about the direction of moves, so only moves are symbols.
    """
    syms: List[int] = []
    prev: Optional[float] = None
    for t in ticks:
        try:
            bid = float(t["bid"])
            ask = float(t["ask"])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2.0
        if prev is not None:
            if mid > prev:
                syms.append(1)
            elif mid < prev:
                syms.append(0)
        prev = mid
    return syms


def ctw_entropy(symbols: Sequence[int], depth: int = DEFAULT_DEPTH) -> Optional[float]:
    """
    Normalised entropy rate in [0, 1] over a binary sequence.

    Codes each symbol against the KT estimate for its own context, and
    averages the resulting code length. 1.0 means incompressible (one
    bit per symbol -- a fair coin); lower means the past predicts the
    next symbol.

    This is the context-mixing simplification of full CTW: rather than
    weighting every tree depth, it uses the deepest context with enough
    observations and backs off when there are not. On a 200-tick window
    the two agree closely and this one is a fraction of the cost, which
    matters when it runs on every decision.
    """
    n = len(symbols)
    if n < MIN_TICKS:
        return None

    # counts[context][symbol]
    counts: Dict[tuple, List[int]] = {}
    total_bits = 0.0
    coded = 0

    for i in range(n):
        # Deepest available context with prior observations, backing off.
        ctx: tuple = ()
        for d in range(min(depth, i), 0, -1):
            candidate = tuple(symbols[i - d:i])
            if candidate in counts and sum(counts[candidate]) >= 2:
                ctx = candidate
                break

        c = counts.setdefault(ctx, [0, 0])
        s = symbols[i]
        p = _kt_probability(c[s], c[0] + c[1])
        p = min(max(p, 1e-12), 1 - 1e-12)
        total_bits += -math.log2(p)
        coded += 1

        # Update every context this symbol belongs to, so shallower
        # contexts stay usable when a deep one has not been seen before.
        for d in range(0, min(depth, i) + 1):
            key = tuple(symbols[i - d:i]) if d else ()
            slot = counts.setdefault(key, [0, 0])
            slot[s] += 1

    if not coded:
        return None
    return max(0.0, min(1.0, total_bits / coded))


def evaluate_entropy(ticks, *, abort_above: float = DEFAULT_ENTROPY_ABORT,
                     depth: int = DEFAULT_DEPTH) -> Dict[str, Any]:
    """
    Stage 3 verdict for one decision's tape.

    Returns:
        available   did the estimate run
        entropy     normalised, [0, 1], or None
        decision    "TRADE" | "ABORT" | None when inactive
        reason      always populated

    Inactive (available False, decision None) when there is no tape --
    NOT an abort. A missing tick cache is the absence of evidence, and
    this project's governing rule is that absent data never becomes
    positive evidence in either direction. The caller decides whether to
    require this stage.
    """
    if ticks is None or len(ticks) == 0:
        return {"available": False, "entropy": None, "decision": None,
                "reason": "no tick data -- entropy not measurable"}

    syms = symbolize(ticks)
    if len(syms) < MIN_TICKS:
        return {"available": False, "entropy": None, "decision": None,
                "reason": (f"only {len(syms)} directional ticks "
                           f"(need {MIN_TICKS}) -- tape too quiet to measure")}

    h = ctw_entropy(syms, depth=depth)
    if h is None:
        return {"available": False, "entropy": None, "decision": None,
                "reason": "entropy estimate did not converge"}

    noisy = h > abort_above
    return {
        "available": True,
        "entropy": round(h, 4),
        "abort_above": abort_above,
        "symbols": len(syms),
        "decision": "ABORT" if noisy else "TRADE",
        "reason": (f"tape entropy {h:.3f} "
                   f"{'>' if noisy else '<='} {abort_above:.2f} -- "
                   f"{'incompressible, no structure to trade' if noisy else 'structured'}"),
    }
