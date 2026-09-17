"""
CONFORMAL PREDICTION  (Stage 8 of the decoupled AI pipeline)
============================================================
FILE: core/conformal.py

Turns the meta-label's score into a statement with a coverage
guarantee, and abstains when it cannot make one.

THE PROBLEM THIS SOLVES

A classifier's output looks like a probability and usually is not one.
The Stage 7 model is fitted with balanced class weights (the base rate
is ~27% wins, so without balancing the model can score well by calling
everything a loss and never rank anything), and balancing shifts the
outputs toward a 50/50 world. Measured on the replay: decisions the
model scored >= 0.65 went on to win 28.2% of the time. The number 0.65
was not 65% of anything. Acting on it as though it were is how a
system becomes confidently wrong.

Split (inductive) conformal fixes this without touching the model. It
asks a purely empirical question of a held-out calibration set:

    among past decisions the model scored at least this high, how
    often was it actually right?

That frequency is distribution-free -- it assumes only that today's
decisions are exchangeable with the calibration ones, not that the
model is calibrated, well-specified, or even good. If the model is
worthless the guarantee still holds; it just cannot be met at any
useful threshold, and the correct output becomes ABSTAIN.

WHAT IT RETURNS

Not a point prediction. A decision from {TRADE, ABSTAIN} plus the
empirical error rate backing it. The pipeline spec's rule is
"stay in 100% cash if the calibrated error rate exceeds 10%", and on
this data that is expected to abstain nearly always -- which is the
honest answer for a 27%-base-rate problem, not a bug. A stage that
abstains is doing its job; a stage that manufactures a 90% confidence
out of a 28% win rate is not.

RAM: the calibration set is a sorted list of floats. Nothing else.
"""

from typing import Any, Dict, List, Optional
import bisect
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CALIBRATION_PATH = os.path.join(_PROJECT_ROOT, "conformal_calibration.json")

# Maximum tolerated error rate among trades this stage lets through.
# 0.10 is the pipeline spec's figure: at most one loser in ten among
# the decisions it approves.
DEFAULT_MAX_ERROR_RATE = 0.10

# Below this many calibration points at or above a score, the observed
# error rate is not a measurement. With 30 samples a single flip moves
# the rate by 3.3 points, which is the resolution the guarantee is
# being asked to provide -- so anything thinner abstains.
MIN_CALIBRATION_SUPPORT = 30


class ConformalCalibrator:
    """
    Split-conformal calibration over meta-label scores.

    Holds (score, was_win) pairs from a held-out set, sorted by score,
    with a suffix-sum of wins so the empirical win rate at or above any
    threshold is O(log n).
    """

    __slots__ = ("scores", "_suffix_wins", "n", "base_rate", "trained_at",
                 "source", "metrics")

    def __init__(self, blob: Dict[str, Any], source: str = ""):
        pairs = [(float(s), int(w)) for s, w in blob["calibration"]]
        pairs.sort(key=lambda sw: sw[0])

        self.scores = [s for s, _ in pairs]
        self.n = len(pairs)

        # suffix_wins[i] = wins among pairs[i:]
        suffix = [0] * (self.n + 1)
        for i in range(self.n - 1, -1, -1):
            suffix[i] = suffix[i + 1] + pairs[i][1]
        self._suffix_wins = suffix

        self.base_rate = (suffix[0] / self.n) if self.n else None
        self.trained_at = blob.get("trained_at")
        self.metrics = dict(blob.get("metrics") or {})
        self.source = source

    def empirical_win_rate(self, score: float):
        """
        (win_rate, support) among calibration points scoring >= `score`.

        This is the conformal quantity: a frequency actually observed
        out of sample, not a transformation of the model's own output.
        """
        i = bisect.bisect_left(self.scores, score)
        support = self.n - i
        if support <= 0:
            return None, 0
        return self._suffix_wins[i] / support, support

    def as_blob(self) -> Dict[str, Any]:
        raise NotImplementedError("built by core/train_meta_label.py")


_cache: Dict[str, Optional[ConformalCalibrator]] = {}
_lock = threading.Lock()


def load_calibrator(path: str = DEFAULT_CALIBRATION_PATH, *,
                    force: bool = False) -> Optional[ConformalCalibrator]:
    with _lock:
        if not force and path in _cache:
            return _cache[path]
        cal: Optional[ConformalCalibrator] = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cal = ConformalCalibrator(json.load(fh), source=path)
            logger.info(f"[CONFORMAL] loaded {path} (n={cal.n}, "
                        f"base_rate={cal.base_rate})")
        except FileNotFoundError:
            logger.debug(f"[CONFORMAL] no calibration at {path} -- stage inactive")
        except Exception as e:
            logger.warning(f"[CONFORMAL] calibration at {path} is unusable: {e}")
        _cache[path] = cal
        return cal


def reset_cache():
    with _lock:
        _cache.clear()


def evaluate_conformal(win_probability: Optional[float], *,
                       max_error_rate: float = DEFAULT_MAX_ERROR_RATE,
                       calibration_path: str = DEFAULT_CALIBRATION_PATH) -> Dict[str, Any]:
    """
    Stage 8 verdict for one meta-label score.

    Returns:
        available        did the stage run
        decision         "TRADE" | "ABSTAIN" | None (inactive)
        error_rate       empirical P(loss | score >= this), or None
        support          calibration points behind that estimate
        reason           always populated
    """
    if win_probability is None:
        # Nothing upstream to calibrate. Not an opinion, so not a veto.
        return {"available": False, "decision": None, "error_rate": None,
                "support": 0, "reason": "no meta-label score to calibrate"}

    cal = load_calibrator(calibration_path)
    if cal is None:
        return {"available": False, "decision": None, "error_rate": None,
                "support": 0, "reason": "no conformal calibration set yet"}

    win_rate, support = cal.empirical_win_rate(float(win_probability))
    if win_rate is None or support < MIN_CALIBRATION_SUPPORT:
        # Too few comparable past decisions to make ANY guarantee. The
        # tail of the score distribution is exactly where a model looks
        # most confident and is least measured, so this abstains rather
        # than extrapolating into it.
        return {
            "available": True, "decision": "ABSTAIN", "error_rate": None,
            "support": support,
            "reason": (f"only {support} calibration decisions scored this high "
                       f"(need {MIN_CALIBRATION_SUPPORT}) -- no guarantee can be made"),
        }

    error_rate = 1.0 - win_rate
    ok = error_rate <= max_error_rate
    return {
        "available": True,
        "decision": "TRADE" if ok else "ABSTAIN",
        "error_rate": round(error_rate, 4),
        "max_error_rate": max_error_rate,
        "support": support,
        "empirical_win_rate": round(win_rate, 4),
        "base_rate": round(cal.base_rate, 4) if cal.base_rate is not None else None,
        "reason": (
            f"decisions scoring >= {win_probability:.3f} won {win_rate:.1%} of the "
            f"time across {support} calibration cases -> error {error_rate:.1%} "
            f"{'<=' if ok else '>'} {max_error_rate:.0%}"
        ),
    }
