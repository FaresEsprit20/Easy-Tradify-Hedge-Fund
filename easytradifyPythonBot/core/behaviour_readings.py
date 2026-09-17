# core/behaviour_readings.py
"""
What price is DOING, as opposed to where it is.

Every reading the system had was a position reading: price above/below EMA200,
inside/outside the value area, premium or discount, which pivot is nearer.
core/state_readings.py measured thirteen of them and they came back nearly
identical -- 44.2% to 45.4% right, -0.121R to -0.165R, against a 44.6%
baseline. They were not thirteen components. They were one component read
thirteen ways, which is why combining them returns the baseline and the final
probability's AUC sits at 0.50.

The coverage column says why. supply_demand_side fired on 100% of bars,
ema200_side 99.3%, poc_side 98.7%. A reading that is available on every bar is
not a signal about this bar; it is a restatement of where price currently is,
and price is always somewhere.

Nothing in the system read the other axis: whether a move is still moving.
That gap is not cosmetic -- it is the reason mean reversion cannot work here.
The strategy asserts "price is overextended" and never checks whether it is
still extending, and the tick study is unambiguous about which half matters:

    fading a fast move          -0.408R   (32.5% right)
    following a fast move       +0.036R   (54.8% right)
    fading a STALLED stretch    -0.116R   (holdout -0.023R)

Velocity continues; it does not revert. Only a stretch that has stopped
extending reverts at all. `reversion_ready` below is that condition, and it is
the gate the mean-reversion group never had.

These readings are deliberately selective. A behaviour reading that fires on
every bar would have reproduced the defect it exists to correct.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

MEAN_MINUTES = 240          # the 4h mean the stretch is measured from
STALL_MINUTES = 30          # no new extreme for this long
VELOCITY_MINUTES = 15       # window the move's speed is measured over
EXTENDED_ATR = 1.0          # how far from the mean counts as stretched
VELOCITY_MAX_ATR = 0.3      # above this the move is still running
COMPRESSION_LOOKBACK = 50   # bars of range history for the volatility slope
EXPANSION_RATIO = 1.3       # current range vs its recent base to count as expanding


TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def minutes_per_bar(timeframe: Any, default: int = 1) -> int:
    """Bar length in minutes, tolerating a name or an MT5 timeframe constant."""
    return TIMEFRAME_MINUTES.get(str(timeframe or "").upper().strip(), default)


def _bars(minutes: int, minutes_per_bar: int) -> int:
    return max(1, int(round(minutes / max(1, minutes_per_bar))))


def read(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
         atr: Optional[float], minutes_per_bar: int = 1) -> Dict[str, Any]:
    """Behaviour of the last closed bar, or `available: False` when unknowable.

    `atr` is the same H1 ATR the stop is sized from, so "0.3 ATR in fifteen
    minutes" means the same thing here as it does in the risk geometry.
    """
    out: Dict[str, Any] = {"available": False}
    n = min(len(highs), len(lows), len(closes))
    mean_bars = _bars(MEAN_MINUTES, minutes_per_bar)
    stall_bars = _bars(STALL_MINUTES, minutes_per_bar)
    vel_bars = _bars(VELOCITY_MINUTES, minutes_per_bar)
    need = mean_bars + 2 * stall_bars
    if not atr or atr <= 0 or n < need:
        out["reason"] = f"needs {need} bars and an ATR (have {n})"
        return out

    h = list(highs[-need:])
    l = list(lows[-need:])
    c = list(closes[-need:])
    price = float(c[-1])
    # the mean of the PRECEDING window, excluding the bar being measured --
    # including it puts the price inside its own reference and shrinks the
    # extension. Every study measures it this way; ai/strategy_selector_lab.py
    # self_check() holds the two conventions against each other.
    mean = sum(c[-mean_bars - 1:-1]) / float(mean_bars)
    extension = (price - mean) / atr
    velocity = abs(price - float(c[-1 - vel_bars])) / atr if n > vel_bars else None

    # Stalled is asked on the side price is stretched to: a stretch UP has
    # stalled when it stops making highs. Asking the other side would answer a
    # different question -- lows can rise while highs keep extending.
    recent_h, prior_h = max(h[-stall_bars:]), max(h[-2 * stall_bars:-stall_bars])
    recent_l, prior_l = min(l[-stall_bars:]), min(l[-2 * stall_bars:-stall_bars])
    stalled = (recent_h <= prior_h) if extension > 0 else (recent_l >= prior_l)

    # Bars since the extreme in the direction of the stretch -- how long the
    # move has been failing to go anywhere.
    window = h[-mean_bars:] if extension > 0 else l[-mean_bars:]
    peak = max(window) if extension > 0 else min(window)
    bars_since_extreme = len(window) - 1 - max(i for i, v in enumerate(window) if v == peak)

    ranges = [float(h[i]) - float(l[i]) for i in range(len(h))]
    if len(ranges) >= COMPRESSION_LOOKBACK + stall_bars:
        base = sorted(ranges[-COMPRESSION_LOOKBACK:])[COMPRESSION_LOOKBACK // 2]
        now = sum(ranges[-stall_bars:]) / float(stall_bars)
        ratio = (now / base) if base > 0 else 1.0
        transition = ("EXPANDING" if ratio >= EXPANSION_RATIO
                      else "CONTRACTING" if ratio <= 1.0 / EXPANSION_RATIO else "STEADY")
    else:
        ratio, transition = None, "UNKNOWN"

    extended = abs(extension) >= EXTENDED_ATR
    slow = velocity is not None and velocity <= VELOCITY_MAX_ATR
    out.update({
        "available": True,
        "extension_atr": round(float(extension), 3),
        "extended": bool(extended),
        "velocity_atr": None if velocity is None else round(float(velocity), 3),
        "slow": bool(slow),
        "stalled": bool(stalled),
        "bars_since_extreme": int(bars_since_extreme),
        "minutes_since_extreme": int(bars_since_extreme * minutes_per_bar),
        "range_vs_base": None if ratio is None else round(float(ratio), 3),
        "volatility_transition": transition,
        # the measured reversion condition: stretched, no longer making new
        # extremes, and no longer moving fast
        "reversion_ready": bool(extended and stalled and slow),
        # its mirror: a move still running is a continuation reading, not a
        # fade -- following one measured +0.036R where fading it lost 0.408R
        "momentum_running": bool(velocity is not None and velocity > VELOCITY_MAX_ATR),
        "side_if_reverting": (-1 if extension > 0 else 1) if extended else 0,
    })
    return out


def from_rates(rates: Any, atr: Optional[float], minutes_per_bar: int = 1) -> Dict[str, Any]:
    """`read()` off an MT5 rates array or a list of OHLC mappings."""
    try:
        if rates is None or len(rates) == 0:
            return {"available": False, "reason": "no rates"}
        if hasattr(rates, "dtype") and getattr(rates.dtype, "names", None):
            return read(rates["high"], rates["low"], rates["close"], atr, minutes_per_bar)
        highs: List[float] = []
        lows: List[float] = []
        closes: List[float] = []
        for bar in rates:
            if isinstance(bar, Mapping):
                highs.append(float(bar["high"]))
                lows.append(float(bar["low"]))
                closes.append(float(bar["close"]))
            else:
                highs.append(float(bar[2]))
                lows.append(float(bar[3]))
                closes.append(float(bar[4]))
        return read(highs, lows, closes, atr, minutes_per_bar)
    except Exception as e:  # a reading must never take the analysis down
        return {"available": False, "reason": f"error: {e}"}


def get_status() -> Dict[str, Any]:
    return {"component": "behaviour_readings", "extended_atr": EXTENDED_ATR,
            "stall_minutes": STALL_MINUTES, "velocity_max_atr": VELOCITY_MAX_ATR,
            "reads": "behaviour (is the move still moving), not position"}


def self_check() -> Dict[str, Any]:
    atr, n = 1.0, 400
    # a stretch that is still making new highs: extended but NOT ready to fade
    running_h = [100.0 + i * 0.05 for i in range(n)]
    running = read(running_h, [v - 0.1 for v in running_h], running_h, atr, 1)
    # the same stretch, then flat for an hour: extended, stalled, slow
    flat = running_h[:-60] + [running_h[-60]] * 60
    stalled = read(flat, [v - 0.1 for v in flat], flat, atr, 1)
    checks = {
        "running_move_is_extended": running["extended"] is True,
        "running_move_is_not_reversion_ready": running["reversion_ready"] is False,
        "running_move_reads_as_momentum": running["momentum_running"] is True,
        "stalled_move_is_reversion_ready": stalled["reversion_ready"] is True,
        "stalled_move_fades_down": stalled["side_if_reverting"] == -1,
        "short_history_is_unavailable": read([1.0], [1.0], [1.0], atr, 1)["available"] is False,
        "no_atr_is_unavailable": read(running_h, running_h, running_h, None, 1)["available"] is False,
    }
    return {"component": "behaviour_readings", "ok": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    import json
    print(json.dumps(self_check(), indent=1))
