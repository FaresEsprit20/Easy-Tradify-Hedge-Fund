"""
TTM SQUEEZE
===========
FILE: core/ttm_squeeze.py

The real Bollinger-inside-Keltner squeeze, with duration, release
detection and confirmation.

WHAT EXISTS TODAY AND WHY IT ISN'T THIS

get_bb_squeeze_threshold() compares Bollinger BANDWIDTH against a fixed
per-instrument number. That answers "is volatility low right now" and
nothing more. It has no notion of duration, no release event, and no
direction -- so a squeeze can only ever tilt indicator weights. It cannot
be traded.

A TTM squeeze is a RELATIONSHIP between two volatility measures:

    Bollinger  mean +/- k * standard deviation   -> reacts to price
    Keltner    EMA    +/- k * ATR                -> reacts to true range

When the Bollinger bands contract INSIDE the Keltner channel, price
dispersion has fallen below the instrument's own true range. Something is
compressing. That is a coiled spring, and the tradeable event is not the
squeeze -- it is the RELEASE.

WHY DURATION MATTERS

A 3-bar squeeze is noise. A 30-bar squeeze that releases is a setup. The
existing bandwidth check cannot tell them apart because it has no memory,
so it reports the same "SQUEEZE" state for both. Duration is most of the
signal.

WHY THE RELEASE NEEDS CONFIRMATION

A squeeze release tells you compression ended, not which way it resolves.
Direction has to come from somewhere else -- momentum, and participation.
Releasing on thin volume is the classic failed breakout, which is exactly
what RVAM was built to catch, so this hands the direction question to
evidence rather than guessing from the release bar alone.
"""

from typing import Dict, Any, List, Optional
import math
import logging

logger = logging.getLogger(__name__)

# Standard TTM parameters. Keltner uses a WIDER multiplier than Bollinger
# by convention -- the squeeze is defined by BB fitting inside KC, so
# equal multipliers would make it fire constantly.
SQUEEZE_BB_PERIOD = 20
SQUEEZE_BB_STD = 2.0
SQUEEZE_KC_PERIOD = 20
SQUEEZE_KC_ATR_MULT = 1.5

# Below this many consecutive bars, a squeeze is noise rather than
# compression. The single most important parameter here: without it every
# quiet patch reads as a setup.
SQUEEZE_MIN_BARS = 6

# How recently a release must have happened to still be actionable.
SQUEEZE_RELEASE_MAX_BARS_AGO = 3

# Momentum lookback for the direction read on release.
SQUEEZE_MOMENTUM_BARS = 12


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(bars, period: int) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(len(bars) - period, len(bars)):
        try:
            h, l = float(bars[i][2]), float(bars[i][3])
            pc = float(bars[i - 1][4])
        except (IndexError, TypeError, ValueError):
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else None


def _squeeze_at(bars, end: int) -> Optional[bool]:
    """Is Bollinger inside Keltner at bar index `end`?"""
    window = bars[: end + 1]
    if len(window) < max(SQUEEZE_BB_PERIOD, SQUEEZE_KC_PERIOD) + 2:
        return None
    try:
        closes = [float(b[4]) for b in window]
    except (IndexError, TypeError, ValueError):
        return None

    recent = closes[-SQUEEZE_BB_PERIOD:]
    mean = sum(recent) / len(recent)
    var = sum((c - mean) ** 2 for c in recent) / len(recent)
    sd = math.sqrt(var)
    bb_upper, bb_lower = mean + SQUEEZE_BB_STD * sd, mean - SQUEEZE_BB_STD * sd

    ema = _ema(closes[-(SQUEEZE_KC_PERIOD * 3):], SQUEEZE_KC_PERIOD)
    atr = _atr(window, SQUEEZE_KC_PERIOD)
    if ema is None or atr is None or atr <= 0:
        return None
    kc_upper, kc_lower = ema + SQUEEZE_KC_ATR_MULT * atr, ema - SQUEEZE_KC_ATR_MULT * atr

    # The definition: both Bollinger bands inside the Keltner channel.
    return bb_upper < kc_upper and bb_lower > kc_lower


def _momentum(bars, period: int) -> Optional[float]:
    """
    Linear-regression slope of close over `period`, normalised by ATR.

    Slope rather than a simple close-to-close difference so one spike
    cannot define the direction of a release, and ATR-normalised so the
    value is comparable across instruments -- the recurring lesson of
    every absolute threshold in this codebase.
    """
    if len(bars) < period + 1:
        return None
    try:
        ys = [float(b[4]) for b in bars[-period:]]
    except (IndexError, TypeError, ValueError):
        return None
    n = len(ys)
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return None
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    atr = _atr(bars, min(14, len(bars) - 1))
    if not atr or atr <= 0:
        return None
    return (slope * n) / atr


def detect_ttm_squeeze(rates, scan_bars: int = 60) -> Dict[str, Any]:
    """
    Current squeeze state, its duration, and whether it just released.

    Returns available=False rather than a neutral state when there is not
    enough history -- "no squeeze" is a claim about the market and should
    not be manufactured from missing data.
    """
    need = max(SQUEEZE_BB_PERIOD, SQUEEZE_KC_PERIOD) + SQUEEZE_MOMENTUM_BARS + 5
    if rates is None or len(rates) < need:
        return {"available": False, "reason": f"needs {need}+ bars", "state": "UNKNOWN"}

    n = len(rates)
    start = max(need - 1, n - scan_bars)
    states = []
    for i in range(start, n):
        s = _squeeze_at(rates, i)
        if s is None:
            return {"available": False, "reason": "insufficient window", "state": "UNKNOWN"}
        states.append(s)

    in_squeeze_now = states[-1]

    # Length of the squeeze run ending at the last bar (if active), or the
    # run that ended most recently (if it just released).
    duration = 0
    for s in reversed(states):
        if s:
            duration += 1
        else:
            break

    released = False
    bars_since_release = None
    prior_duration = 0
    if not in_squeeze_now:
        for k in range(len(states) - 1, -1, -1):
            if states[k]:
                bars_since_release = len(states) - 1 - k
                for j in range(k, -1, -1):
                    if states[j]:
                        prior_duration += 1
                    else:
                        break
                break
        released = (bars_since_release is not None
                    and bars_since_release <= SQUEEZE_RELEASE_MAX_BARS_AGO
                    and prior_duration >= SQUEEZE_MIN_BARS)

    mom = _momentum(rates, SQUEEZE_MOMENTUM_BARS)

    if in_squeeze_now:
        state = "SQUEEZE_ACTIVE" if duration >= SQUEEZE_MIN_BARS else "SQUEEZE_FORMING"
    elif released:
        state = "SQUEEZE_RELEASED"
    else:
        state = "NO_SQUEEZE"

    return {
        "available": True,
        "state": state,
        "in_squeeze": in_squeeze_now,
        "duration_bars": duration if in_squeeze_now else prior_duration,
        "bars_since_release": bars_since_release,
        "released": released,
        "momentum": round(mom, 3) if mom is not None else None,
        "momentum_direction": (None if mom is None else ("UP" if mom > 0 else "DOWN")),
        # The TTM signal is the momentum AT RELEASE. momentum_direction is set
        # on every bar and was read as a vote on 100% of study bars
        # (2026-09-15); this is set only when a squeeze has just fired.
        "release_direction": (("UP" if mom > 0 else "DOWN") if released and mom else None),
        # A long squeeze is a bigger spring. Capped at 30 bars, past which
        # more compression stops meaning more energy and starts meaning a
        # dead instrument.
        "compression_score": round(min(1.0, (duration if in_squeeze_now else prior_duration) / 30.0), 3),
        "reason": {
            "SQUEEZE_ACTIVE": f"compressed {duration} bars -- coiled, direction unknown until release",
            "SQUEEZE_FORMING": f"compressing ({duration} bars, needs {SQUEEZE_MIN_BARS})",
            "SQUEEZE_RELEASED": f"released {bars_since_release} bars ago after {prior_duration} bars of compression",
            "NO_SQUEEZE": "bands outside Keltner -- normal or expanding volatility",
        }[state],
    }


def score_squeeze_setup(squeeze: Dict[str, Any],
                        direction: str,
                        rvam_result: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Turn a squeeze state into a trade verdict.

    The release is the setup, not the squeeze. An ACTIVE squeeze is a
    reason to WAIT, and saying so is more useful than a neutral zero --
    the current bandwidth check reports low volatility and leaves the
    caller to decide what that means, which is how "quiet" ended up
    tilting indicator weights instead of producing a setup.

    Participation is required on the release. A squeeze releasing on thin
    volume is the textbook failed breakout, and RVAM already answers that
    question, so it is consulted rather than re-derived.
    """
    if not squeeze.get("available"):
        return {"score": 0, "setup": None, "reason": squeeze.get("reason", "unavailable")}

    state = squeeze["state"]

    if state == "SQUEEZE_ACTIVE":
        return {"score": 0, "setup": "WAIT_FOR_RELEASE",
                "reason": f"squeeze active for {squeeze['duration_bars']} bars -- "
                          f"entering before release is trading a coin flip"}

    if state == "SQUEEZE_FORMING":
        return {"score": 0, "setup": None,
                "reason": "compression forming but not yet a squeeze"}

    if state != "SQUEEZE_RELEASED":
        return {"score": 0, "setup": None, "reason": squeeze["reason"]}

    mom_dir = squeeze.get("momentum_direction")
    trade_up = str(direction).upper() == "BUY"
    aligned = (mom_dir == "UP") == trade_up if mom_dir else None

    # A release with no readable momentum direction is a release with no
    # direction to trade. Returning a positive score here would reward
    # "something happened" without knowing which way -- which is the
    # failure the old bandwidth-only squeeze had.
    if aligned is None:
        return {"score": 0, "setup": "RELEASE_NO_DIRECTION",
                "reason": f"squeeze released after {squeeze['duration_bars']} bars "
                          f"but momentum is unreadable -- no direction to trade"}

    if aligned is False:
        return {"score": -10, "setup": "RELEASE_AGAINST",
                "reason": f"squeeze released {mom_dir} after "
                          f"{squeeze['duration_bars']} bars -- against this {direction}"}

    # Compression length scales the reward: a 25-bar coil releasing is
    # worth more than a 7-bar one.
    base = 6 + int(squeeze["compression_score"] * 8)

    cls = (rvam_result or {}).get("classification")
    if cls == "UNPARTICIPATED":
        return {"score": -8, "setup": "RELEASE_UNCONFIRMED",
                "reason": f"squeeze released {mom_dir} on thin participation -- "
                          f"textbook failed breakout"}
    if cls == "CONVICTION_MOVE":
        return {"score": base + 6, "setup": "RELEASE_CONFIRMED",
                "reason": f"squeeze released {mom_dir} after {squeeze['duration_bars']} bars "
                          f"with heavy participation"}

    return {"score": base, "setup": "RELEASE",
            "reason": f"squeeze released {mom_dir} after {squeeze['duration_bars']} bars "
                      f"(participation unconfirmed)"}