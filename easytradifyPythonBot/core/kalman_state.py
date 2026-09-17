"""
UNSCENTED KALMAN FILTER  (Stage 1 of the decoupled AI pipeline)
===============================================================
FILE: core/kalman_state.py

Estimates the unobserved price level and velocity behind a noisy quote.

THE IDEA

Every moving average in this system is a lagging estimator: an EMA(20)
tells you where price was, smoothed, some bars ago. That lag is not a
tuning problem, it is what averaging does. A Kalman filter instead
maintains a MODEL of the state -- level and velocity -- and corrects it
with each observation in proportion to how much the observation should
be trusted. The result tracks a turn faster than an average of the same
smoothness, because it carries a velocity term rather than inferring
one from the past.

The "unscented" variant propagates sigma points through the model
instead of linearising it. For the near-linear constant-velocity model
used here that is close to a plain Kalman filter, and it is implemented
that way deliberately: a linear model solved exactly beats a non-linear
solver applied to a model that is not actually non-linear.

WHAT IT CAN AND CANNOT DO

It can produce a smoother, less-lagged level and an explicit velocity
estimate, and it can say how uncertain it currently is -- which no
moving average in this codebase reports at all.

It cannot create directional edge. This project measured price
direction at entropy 1.0000 -- a fair coin -- at every timeframe from
M1 to D1 on both instruments, and every one of nineteen components at
|correlation| < 0.05 against outcomes. A better estimate of a random
walk's current position is still an estimate of a random walk: the
filter reduces measurement noise, it does not make the next step
predictable. Anything claiming otherwise from this module is reading a
smoother line and mistaking smoothness for signal.

It is built and measured here because the pipeline specifies it and
because a calibrated uncertainty estimate is genuinely useful for
sizing and for stop placement -- not because it is expected to predict
direction.

Pure stdlib. Fixed process/measurement noise ratio, no fitting.
"""

from typing import Any, Dict, List, Optional, Sequence
import logging
import math

logger = logging.getLogger(__name__)

# Ratio of process noise to measurement noise. The single knob that
# matters: high values track fast and stay noisy, low values smooth
# hard and lag. 0.01 is a conventional starting point for a
# constant-velocity model on financial data and is NOT tuned against
# outcomes here -- a ratio fitted to this sample would be a parameter
# fitted to this sample, which is how the meta-label model earned its
# AUC of 0.5034.
DEFAULT_PROCESS_RATIO = 0.01

MIN_OBSERVATIONS = 30


class KalmanState:
    """
    Constant-velocity Kalman filter over a price series.

    State is [level, velocity]; the observation is the price. Covariance
    is carried explicitly so the filter can report how confident it
    currently is, which is the part no moving average provides.
    """

    __slots__ = ("level", "velocity", "p00", "p01", "p10", "p11",
                 "q_ratio", "r_var", "n")

    def __init__(self, initial_price: float, measurement_var: float,
                 q_ratio: float = DEFAULT_PROCESS_RATIO):
        self.level = float(initial_price)
        self.velocity = 0.0
        # Start uncertain in both states rather than pretending the
        # first observation is the truth.
        self.p00 = measurement_var
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = measurement_var
        self.q_ratio = q_ratio
        self.r_var = max(measurement_var, 1e-18)
        self.n = 0

    def step(self, price: float) -> None:
        """One predict/update cycle against a new observation."""
        q = self.r_var * self.q_ratio

        # --- predict: level advances by velocity, velocity persists ---
        level = self.level + self.velocity
        velocity = self.velocity

        # P = F P F' + Q, with F = [[1,1],[0,1]]
        p00 = self.p00 + self.p01 + self.p10 + self.p11 + q
        p01 = self.p01 + self.p11
        p10 = self.p10 + self.p11
        p11 = self.p11 + q

        # --- update: observe the level only, H = [1, 0] ---
        s = p00 + self.r_var
        if s <= 0:
            return
        k0 = p00 / s
        k1 = p10 / s
        residual = float(price) - level

        self.level = level + k0 * residual
        self.velocity = velocity + k1 * residual

        self.p00 = (1 - k0) * p00
        self.p01 = (1 - k0) * p01
        self.p10 = p10 - k1 * p00
        self.p11 = p11 - k1 * p01
        self.n += 1

    @property
    def uncertainty(self) -> float:
        """Standard deviation of the level estimate."""
        return math.sqrt(self.p00) if self.p00 > 0 else 0.0


def estimate_state(closes: Sequence[float], *, pip_size: float,
                   q_ratio: float = DEFAULT_PROCESS_RATIO) -> Dict[str, Any]:
    """
    Filtered level, velocity and uncertainty for the latest bar.

    Measurement variance is taken from the series' own recent squared
    returns, so the filter is scaled to the instrument rather than to a
    hardcoded constant that would be wrong on every symbol but one.

    Returns available False when there is too little history -- never a
    fabricated state.
    """
    vals = [float(c) for c in closes if c is not None and c > 0]
    if len(vals) < MIN_OBSERVATIONS:
        return {"available": False,
                "reason": f"need {MIN_OBSERVATIONS} closes, have {len(vals)}"}
    if not pip_size or pip_size <= 0:
        return {"available": False, "reason": "pip_size missing or invalid"}

    diffs = [vals[i] - vals[i - 1] for i in range(1, min(len(vals), 200))]
    meas_var = (sum(d * d for d in diffs) / len(diffs)) if diffs else 0.0
    if meas_var <= 0:
        return {"available": False, "reason": "series has no variation"}

    kf = KalmanState(vals[0], meas_var, q_ratio=q_ratio)
    for p in vals:
        kf.step(p)

    last = vals[-1]
    return {
        "available": True,
        "level": round(kf.level, 8),
        "velocity_pips": round(kf.velocity / pip_size, 4),
        "uncertainty_pips": round(kf.uncertainty / pip_size, 4),
        "residual_pips": round((last - kf.level) / pip_size, 4),
        "observations": kf.n,
        # Sign of velocity is a DESCRIPTION of the filtered state, not a
        # forecast. See the module docstring: direction on this data
        # measured at entropy 1.0.
        "direction_hint": ("UP" if kf.velocity > 0 else
                           "DOWN" if kf.velocity < 0 else "FLAT"),
        "reason": (f"level {kf.level:.5f} (price {last:.5f}, "
                   f"residual {(last - kf.level) / pip_size:+.1f}p), "
                   f"velocity {kf.velocity / pip_size:+.2f}p/bar, "
                   f"uncertainty {kf.uncertainty / pip_size:.2f}p"),
    }


def evaluate_lag(closes: Sequence[float], *, ema_period: int = 20,
                 q_ratio: float = DEFAULT_PROCESS_RATIO) -> Dict[str, Any]:
    """
    Does the filter actually track price with less lag than an EMA of
    comparable smoothness?

    Both estimators are run causally over the series and scored on mean
    absolute distance to the NEXT price -- the quantity a less-lagged
    estimator should be closer to. Smoothness is reported alongside,
    because an estimator can win on lag simply by being noisier, and
    that is not an improvement.
    """
    vals = [float(c) for c in closes if c is not None and c > 0]
    if len(vals) < MIN_OBSERVATIONS + ema_period + 20:
        return {"available": False, "reason": "not enough history to score"}

    diffs = [vals[i] - vals[i - 1] for i in range(1, min(len(vals), 200))]
    meas_var = sum(d * d for d in diffs) / len(diffs) if diffs else 0.0
    if meas_var <= 0:
        return {"available": False, "reason": "series has no variation"}

    kf = KalmanState(vals[0], meas_var, q_ratio=q_ratio)
    alpha = 2.0 / (ema_period + 1)
    ema = vals[0]

    kf_err, ema_err = [], []
    kf_jitter, ema_jitter = [], []
    prev_kf = prev_ema = None

    for i, p in enumerate(vals[:-1]):
        kf.step(p)
        ema = alpha * p + (1 - alpha) * ema
        if i < MIN_OBSERVATIONS + ema_period:
            prev_kf, prev_ema = kf.level, ema
            continue
        nxt = vals[i + 1]
        kf_err.append(abs(kf.level - nxt))
        ema_err.append(abs(ema - nxt))
        if prev_kf is not None:
            kf_jitter.append(abs(kf.level - prev_kf))
            ema_jitter.append(abs(ema - prev_ema))
        prev_kf, prev_ema = kf.level, ema

    if not kf_err:
        return {"available": False, "reason": "no scored bars"}

    mae_kf = sum(kf_err) / len(kf_err)
    mae_ema = sum(ema_err) / len(ema_err)
    j_kf = sum(kf_jitter) / len(kf_jitter) if kf_jitter else 0.0
    j_ema = sum(ema_jitter) / len(ema_jitter) if ema_jitter else 0.0

    return {
        "available": True,
        "n": len(kf_err),
        "mae_kalman": mae_kf,
        "mae_ema": mae_ema,
        "lag_improvement_pct": round((1 - mae_kf / mae_ema) * 100, 2) if mae_ema > 0 else None,
        "jitter_kalman": j_kf,
        "jitter_ema": j_ema,
        "smoothness_ratio": round(j_kf / j_ema, 3) if j_ema > 0 else None,
        "verdict": ("Kalman tracks closer than the EMA"
                    if mae_kf < mae_ema else
                    "EMA is as close or closer -- the filter is not buying anything"),
    }
