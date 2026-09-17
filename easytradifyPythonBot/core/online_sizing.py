"""
ONLINE CONVEX OPTIMIZATION  (Stage 10 of the decoupled AI pipeline)
===================================================================
FILE: core/online_sizing.py

Position size as a regret-minimising decision, not a fixed fraction.

THE PROBLEM

Everything upstream decides WHETHER to trade. Nothing decides HOW MUCH,
beyond a constant risk fraction that is identical on the strategy's
best day and its worst. A system whose edge decays -- because the
regime turned, the spread widened, or the edge was never there --
keeps betting the same amount while it happens, and the account finds
out before the operator does.

THE ALGORITHM

Follow-the-Regularised-Leader over two experts: TRADE and CASH. Each
resolved outcome scores both (the trade expert earns the realised R,
cash earns 0), and the weight on TRADE becomes the size multiplier.
Regularisation keeps it from lurching on a single result.

This is the multiplicative-weights form, which for two experts is:

    w_trade  =  exp(eta * cumulative_R)  /  (exp(eta * cumulative_R) + 1)

with cumulative_R discounted so old evidence fades. A strategy earning
positive R drifts toward full size; one bleeding R drifts toward zero,
smoothly, with no threshold to tune and no forecast required.

WHAT IT IS NOT

It does not predict anything and it cannot create edge. On a strategy
with negative expectancy it converges toward zero size, which IS the
correct answer -- and the replay measured exactly that: -0.092R on
XAGUSD, -0.107R on EURUSD. Sizing down a losing system is not a
consolation prize, it is the only lever that works without a forecast.

Nor does it replace the risk budget. It scales the size that
calculate_lot_proper() already computed from the stop distance, so
every existing floor and broker limit still applies. It can only ever
make a position SMALLER.

DECAY, NOT A WINDOW

Evidence is discounted geometrically rather than truncated at N trades.
A hard window makes the multiplier jump when a good or bad trade falls
off the end, and that discontinuity is visible as a step change in
position size for no reason a trader could explain from the market.
"""

from typing import Any, Dict, List, Optional
import json
import logging
import math
import os
import threading

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STATE_PATH = os.path.join(_PROJECT_ROOT, "online_sizing_state.json")

# Learning rate. At 0.35 a single -1R trade moves the multiplier a few
# points rather than a third of the way to zero: fast enough to react
# within a losing streak, slow enough that one stop-out is not a verdict.
DEFAULT_ETA = 0.35

# Geometric discount per resolved trade. 0.98 gives evidence a half-life
# of ~34 trades -- long enough to average through normal variance,
# short enough to notice a regime that has stopped paying.
DEFAULT_DECAY = 0.98

# Never scale below this while the stage is enabled. A multiplier of
# exactly zero stops producing outcomes, which stops producing the
# evidence needed to ever size back up -- the algorithm would latch off
# permanently. A floor keeps a small probe running.
MIN_MULTIPLIER = 0.10

# Nor above 1.0: this stage exists to reduce exposure, never to lever
# up on a hot streak. Position sizing that grows after wins is how a
# variance run becomes a margin call.
MAX_MULTIPLIER = 1.00


class OnlineSizer:
    """
    Regret-minimising size multiplier over resolved trade outcomes.

    State is a single discounted sum, so it is O(1) in memory and
    survives a restart as one small JSON file.
    """

    __slots__ = ("cumulative_r", "n_updates", "eta", "decay", "_lock")

    def __init__(self, cumulative_r: float = 0.0, n_updates: int = 0,
                 eta: float = DEFAULT_ETA, decay: float = DEFAULT_DECAY):
        self.cumulative_r = float(cumulative_r)
        self.n_updates = int(n_updates)
        self.eta = float(eta)
        self.decay = float(decay)
        self._lock = threading.Lock()

    def multiplier(self) -> float:
        """
        Weight on the TRADE expert, in [MIN_MULTIPLIER, MAX_MULTIPLIER].

        With no evidence the discounted sum is 0, giving exp(0)/(exp(0)+1)
        = 0.5 -- half size until the strategy has said something about
        itself. That is deliberately not 1.0: an untested configuration
        has not earned full exposure.
        """
        z = self.eta * self.cumulative_r
        # Guard the exponential rather than letting a long winning or
        # losing run raise OverflowError inside position sizing.
        if z > 500:
            w = 1.0
        elif z < -500:
            w = 0.0
        else:
            e = math.exp(z)
            w = e / (e + 1.0)
        return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, w))

    def update(self, r_multiple: float) -> float:
        """
        Fold in one resolved outcome and return the new multiplier.

        `r_multiple` is the realised R, net of costs. Only resolved
        trades belong here: an unresolved position has not scored either
        expert yet, and counting it as 0 would quietly teach the sizer
        that trading and holding cash are equivalent.
        """
        try:
            r = float(r_multiple)
        except (TypeError, ValueError):
            return self.multiplier()
        if r != r or abs(r) == float("inf"):
            return self.multiplier()

        with self._lock:
            self.cumulative_r = self.cumulative_r * self.decay + r
            self.n_updates += 1
            return self.multiplier()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cumulative_r": round(self.cumulative_r, 6),
            "n_updates": self.n_updates,
            "eta": self.eta,
            "decay": self.decay,
            "multiplier": round(self.multiplier(), 4),
        }

    def save(self, path: str = DEFAULT_STATE_PATH) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.as_dict(), fh, indent=2)
        except Exception as e:
            logger.warning(f"[SIZING] could not persist state to {path}: {e}")

    @classmethod
    def load(cls, path: str = DEFAULT_STATE_PATH) -> "OnlineSizer":
        """
        Restore, or start fresh. A missing file is normal on first run;
        an unreadable one starts fresh too, because a sizer that refuses
        to start is worse than one that begins at half size.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            return cls(
                cumulative_r=blob.get("cumulative_r", 0.0),
                n_updates=blob.get("n_updates", 0),
                eta=blob.get("eta", DEFAULT_ETA),
                decay=blob.get("decay", DEFAULT_DECAY),
            )
        except FileNotFoundError:
            logger.debug(f"[SIZING] no state at {path} -- starting at half size")
        except Exception as e:
            logger.warning(f"[SIZING] state at {path} unusable ({e}) -- starting fresh")
        return cls()


def simulate(outcomes: List[float], *, eta: float = DEFAULT_ETA,
             decay: float = DEFAULT_DECAY) -> Dict[str, Any]:
    """
    Replay a sequence of realised R multiples through the sizer.

    Answers the only question that matters about this stage: applied to
    the trades this strategy ACTUALLY took, would it have reduced the
    loss? It compares total R at full size against total R with each
    trade scaled by the multiplier standing BEFORE that trade -- no
    lookahead, since the multiplier only ever reflects outcomes already
    resolved.
    """
    sizer = OnlineSizer(eta=eta, decay=decay)
    flat_total = 0.0
    sized_total = 0.0
    multipliers = []
    flat_curve, sized_curve = [], []
    flat_peak = sized_peak = 0.0
    flat_dd = sized_dd = 0.0

    for r in outcomes:
        m = sizer.multiplier()          # decided before the outcome is known
        multipliers.append(m)
        flat_total += r
        sized_total += r * m

        flat_peak = max(flat_peak, flat_total)
        sized_peak = max(sized_peak, sized_total)
        flat_dd = max(flat_dd, flat_peak - flat_total)
        sized_dd = max(sized_dd, sized_peak - sized_total)
        flat_curve.append(flat_total)
        sized_curve.append(sized_total)

        sizer.update(r)

    n = len(outcomes)
    return {
        "n": n,
        "flat_total_r": round(flat_total, 3),
        "sized_total_r": round(sized_total, 3),
        "r_saved": round(sized_total - flat_total, 3),
        "flat_max_drawdown_r": round(flat_dd, 3),
        "sized_max_drawdown_r": round(sized_dd, 3),
        "drawdown_reduction_pct": (round((1 - sized_dd / flat_dd) * 100, 1)
                                   if flat_dd > 0 else None),
        "final_multiplier": round(sizer.multiplier(), 4),
        "mean_multiplier": round(sum(multipliers) / n, 4) if n else None,
        "min_multiplier": round(min(multipliers), 4) if n else None,
    }
