"""
RVAM — RELATIVE VOLUME-ADJUSTED MOVEMENT
========================================
FILE: core/rvam.py

Asks the one question nothing in this pipeline currently asks: did the
participation match the movement?

Every existing check measures either price OR volume. Trend, structure,
patterns, Bollinger, Elliott all read price. get_volume_ratio() reads
volume. Nothing compares them, so a 40-pip break on a dead tape and a
40-pip break on triple volume are scored identically — and the first one
is where fake breakouts come from.

WHY LOG RETURNS

A raw pip move means nothing across instruments: 40 pips is enormous on
EURUSD and a rounding error on XAUUSD. This codebase has repeatedly been
burned by absolute-pip thresholds for exactly that reason. A log return
is scale-free by construction, and standardising it against its own
recent distribution makes it comparable across every symbol and session
without a per-instrument table to maintain and drift.

THE 2x2 IS THE POINT

RVAM is not one number. It is the interaction of two, and the
interesting cells are the diagonals:

                    volume HIGH          volume LOW
    move LARGE      CONVICTION_MOVE      UNPARTICIPATED
                    real participation   the fake breakout
    move SMALL      ABSORPTION           QUIET
                    effort, no result    nothing happening

  UNPARTICIPATED is a breakout nobody funded. It is the single most
  useful thing here as a filter.

  ABSORPTION is heavy volume that moved nothing — someone is filling
  size against the move. Classic exhaustion / reversal territory, and
  it is invisible to every current check because price barely moved.

Both diagonals are ignored by the present system, which would see the
first as "strong momentum" and the second as "quiet".
"""

from typing import Dict, Any, List, Optional
import math
import os
import logging

logger = logging.getLogger(__name__)

# Standardisation window for log returns. Long enough for a stable
# distribution, short enough to reflect the current session rather than
# last week's regime.
RVAM_RETURN_LOOKBACK = 100

# Bars the move is measured over. 1 = this bar alone; 3 catches an
# impulse that spans a few candles, which is what displacement looks
# like on M1.
RVAM_MOVE_BARS = 3

# z-score above which a move counts as LARGE. 1.5 sigma is roughly the
# top ~13% of bars — infrequent enough to mean something, common enough
# to fire.
RVAM_LARGE_MOVE_Z = 1.5

# Relative volume above which participation counts as HIGH. Deliberately
# not 2.0: at 2.0 the classifier almost never fires, which is the same
# failure as MICRO_STRUCTURE_ICEBERG_MIN_VOLUME being set past its own
# maximum.
RVAM_HIGH_VOLUME_RATIO = 1.4
RVAM_LOW_VOLUME_RATIO = 0.8


def _safe_log_return(a: float, b: float) -> Optional[float]:
    """ln(b/a), or None on any input that would make it meaningless."""
    try:
        a, b = float(a), float(b)
        if a <= 0 or b <= 0:
            return None
        return math.log(b / a)
    except (TypeError, ValueError):
        return None


def _stdev(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def calculate_rvam(rates,
                   volume_ratio: float,
                   move_bars: int = RVAM_MOVE_BARS,
                   lookback: int = RVAM_RETURN_LOOKBACK) -> Dict[str, Any]:
    """
    Compare the size of the recent move against its own history, and
    against the participation behind it.

    volume_ratio comes from the caller — get_volume_ratio() already
    resolves the per-timeframe baseline, and duplicating that here is how
    this codebase ends up with two definitions of the same quantity.

    Returns available=False rather than a neutral-looking score when
    there is not enough history: a fabricated 0.0 would read as "no
    move", which is a claim, not an absence.
    """
    if rates is None or len(rates) < lookback + move_bars + 1:
        return {"available": False, "reason": f"needs {lookback + move_bars + 1} bars",
                "classification": "UNKNOWN"}

    try:
        closes = [float(r[4]) for r in rates]
    except (IndexError, TypeError, ValueError) as e:
        return {"available": False, "reason": f"bad rates: {e}", "classification": "UNKNOWN"}

    # The move being judged.
    move_ret = _safe_log_return(closes[-1 - move_bars], closes[-1])
    if move_ret is None:
        return {"available": False, "reason": "non-positive price", "classification": "UNKNOWN"}

    # Its own recent distribution, measured over the SAME horizon so the
    # comparison is like-for-like. Comparing a 3-bar move against 1-bar
    # returns would inflate every z-score by roughly sqrt(3).
    history = []
    window = closes[-(lookback + move_bars):]
    for i in range(len(window) - move_bars):
        r = _safe_log_return(window[i], window[i + move_bars])
        if r is not None:
            history.append(r)

    sigma = _stdev(history)
    if sigma <= 0:
        return {"available": False, "reason": "degenerate return distribution",
                "classification": "UNKNOWN"}

    z = move_ret / sigma
    rvol = float(volume_ratio or 1.0)

    large = abs(z) >= RVAM_LARGE_MOVE_Z
    high_vol = rvol >= RVAM_HIGH_VOLUME_RATIO
    low_vol = rvol <= RVAM_LOW_VOLUME_RATIO

    if large and high_vol:
        classification = "CONVICTION_MOVE"
        detail = "large move on heavy participation"
    elif large and low_vol:
        classification = "UNPARTICIPATED"
        detail = "large move on thin volume — nobody funded this"
    elif (not large) and high_vol:
        classification = "ABSORPTION"
        detail = "heavy volume, little movement — size being filled against the move"
    elif (not large) and rvol < RVAM_HIGH_VOLUME_RATIO and abs(z) < 0.5:
        classification = "QUIET"
        detail = "no meaningful move, no meaningful volume"
    else:
        classification = "NORMAL"
        detail = "move and participation both unremarkable"

    # Signed so a caller can compare it against a trade direction without
    # re-deriving which way price went.
    rvam = z * rvol

    return {
        "available": True,
        "rvam": round(rvam, 3),
        "return_z": round(z, 3),
        "volume_ratio": round(rvol, 3),
        "move_bars": move_bars,
        "direction": "UP" if move_ret > 0 else "DOWN",
        # The signal: a large move with heavy participation, in its direction.
        # `direction` is the sign of any move and was a vote on every bar.
        "signal_direction": ("UP" if move_ret > 0 else "DOWN") if classification == "CONVICTION_MOVE" else None,
        "classification": classification,
        "detail": detail,
        "sigma": round(sigma, 8),
    }


def score_rvam_confirmation(rvam_result: Dict[str, Any],
                            direction: str,
                            is_breakout: bool = False) -> Dict[str, Any]:
    """
    Turn an RVAM reading into a confirmation verdict for a proposed trade.

    Deliberately asymmetric. UNPARTICIPATED is a hard warning because an
    unfunded breakout is the specific failure this module exists to
    catch; CONVICTION_MOVE is only a mild endorsement, because heavy
    participation confirms that a move is real without saying it will
    continue.

    ABSORPTION is direction-dependent and the subtlest case: volume
    absorbing a move is evidence AGAINST that move continuing, so it
    supports a trade taken against it.
    """
    if not rvam_result.get("available"):
        return {"confirms": None, "score": 0, "reason": rvam_result.get("reason", "unavailable")}

    cls = rvam_result["classification"]
    move_dir = rvam_result["direction"]
    trade_up = str(direction).upper() == "BUY"
    move_up = move_dir == "UP"
    aligned = trade_up == move_up

    if cls == "UNPARTICIPATED":
        if is_breakout and aligned:
            return {"confirms": False, "score": -15,
                    "reason": "breakout on thin volume — unfunded move, high fake-break risk"}
        return {"confirms": False, "score": -8,
                "reason": "move not backed by participation"}

    if cls == "CONVICTION_MOVE":
        # ------------------------------------------------------------------
        # MEASURED, 215 real trades with the analysis recomputed at entry:
        #
        #   aligned  (was scored +10)  n=10  mean -0.5389R  win 10.0%
        #   opposing (was scored -12)  n=11  mean +0.1765R  win 45.5%
        #   difference -0.7154R, p=0.15
        #
        # The branch was rewarding the condition with a 10% win rate and
        # penalising the one that performed at the base rate. Three things
        # make that a defect rather than an unlucky sample:
        #
        #  1. The docstring above already says CONVICTION_MOVE "is only a
        #     mild endorsement, because heavy participation confirms that a
        #     move is real WITHOUT SAYING IT WILL CONTINUE" -- and then the
        #     code awarded +10, larger than ABSORPTION's +8. The stated
        #     intent and the implementation disagreed.
        #  2. The ABSORPTION branch below applies the opposite (exhaustion)
        #     prior and measures CORRECT: +8 for opposing returned +0.294R at
        #     57.9% win.
        #  3. adr_exhaustion, which uses the same exhaustion prior, was the
        #     strongest positive contributor in the whole ledger (+0.213R).
        #
        # So this branch was the only place in the system applying a
        # continuation prior, and it is the one the data contradicts.
        #
        # DEFAULT IS "neutral", NOT "exhaustion". The evidence that +10 is
        # wrong is good; the evidence that -10 is RIGHT is 21 trades at
        # p=0.15. Asserting the opposite sign on that would be the same
        # mistake in the other direction -- and this codebase has measured
        # what that costs: rvam's own train edge of +0.318R became -0.861R
        # out of sample. Neutral removes a contribution the data
        # contradicts without claiming to know its replacement.
        #
        # Set RVAM_CONVICTION_MODE=continuation to restore the original, or
        # =exhaustion to run the inverted hypothesis under an experiment.
        mode = os.environ.get("RVAM_CONVICTION_MODE", "neutral").strip().lower()
        if mode not in ("continuation", "neutral", "exhaustion"):
            mode = "neutral"

        if mode == "continuation":
            if aligned:
                return {"confirms": True, "score": 10,
                        "reason": "move backed by heavy participation, aligned with trade"}
            return {"confirms": False, "score": -12,
                    "reason": "heavy participation driving price AGAINST this trade"}

        if mode == "exhaustion":
            if aligned:
                return {"confirms": False, "score": -10,
                        "reason": ("heavy aligned participation -- late to the move "
                                   "(exhaustion prior)")}
            return {"confirms": True, "score": 12,
                    "reason": ("heavy participation against this trade -- fading an "
                               "extended move (exhaustion prior)")}

        # neutral
        if aligned:
            return {"confirms": None, "score": 0,
                    "reason": ("move backed by heavy participation, aligned with trade "
                               "-- no adjustment: continuation prior contradicted by "
                               "measurement (10% win rate on 10 trades)")}
        return {"confirms": None, "score": 0,
                "reason": ("heavy participation driving price against this trade "
                           "-- no adjustment: prior unvalidated")}

    if cls == "ABSORPTION":
        # Volume absorbed the move, so the move is being resisted. That
        # favours the side opposing the recent direction.
        if not aligned:
            return {"confirms": True, "score": 8,
                    "reason": "volume absorbing the opposing move — supports this direction"}
        return {"confirms": False, "score": -6,
                "reason": "volume absorbing the move this trade is following"}

    if cls == "QUIET":
        return {"confirms": False, "score": -4,
                "reason": "no participation and no movement — nothing to trade"}

    return {"confirms": None, "score": 0, "reason": "unremarkable move and volume"}


RVAM_WEIGHT = 0.10


def calculate_rvam_final_score(rvam_confirmation: Dict[str, Any],
                               base_probability: float) -> Dict[str, Any]:
    """
    Apply RVAM as a probability adjustment, in the same shape as every
    other confluence step (trend_cascade, nested_zone, liquidity_sweeps...),
    so it slots into the existing chain and appears in the ledger without
    special-casing.

    The scores in score_rvam_confirmation are already the intended
    magnitudes, so this clamps rather than rescaling — a second scaling
    layer would make the published number disagree with the reason string.
    """
    score = rvam_confirmation.get("score", 0) or 0
    if not score:
        return {"final_score": base_probability, "adjustment": 0.0,
                "aligned": rvam_confirmation.get("confirms"),
                "reason": rvam_confirmation.get("reason", "no RVAM signal")}

    adjustment = float(score)
    final = max(5.0, min(95.0, float(base_probability) + adjustment))
    return {
        "final_score": round(final, 1),
        "adjustment": round(adjustment, 1),
        "aligned": rvam_confirmation.get("confirms"),
        "reason": rvam_confirmation.get("reason"),
        "rvam": rvam_confirmation,
    }