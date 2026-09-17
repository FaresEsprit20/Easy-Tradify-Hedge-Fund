"""
META-LABELING  (Stage 7 of the decoupled AI pipeline)
=====================================================
FILE: core/meta_labeling.py

Separates the SIDE of a trade from whether it should be taken at all.

The primary stack (probability chain, families, SMC, discount engine)
decides direction. This asks one narrower, purely empirical question
about the setup it produced:

    will THIS entry hit its take-profit before its stop-loss?

That is a binary label with a ground truth, which means -- unlike a
confluence score -- it can be measured instead of argued about. The
replay harness already produces exactly that label for every decision
it walks (`shadow.outcome`, WIN/LOSS from a forward walk to whichever
level price touched first), so the training set is a by-product of
work the audit already does.

WHY THIS EXISTS AT ALL

A 12-day, 1856-decision XAGUSD replay measured every one of the eleven
evidence families at |correlation with winning| <= 0.042 -- that is,
none of them predicted anything. The same run found real, sizeable
discrimination in the execution context the families ignore:

    spread 15-30 pips   32.0% win        spread > 30 pips   18.5% win
    ATR < 30            37.2% win        ATR > 60           25.3% win
    coherence violation 18.5% win        clean              28.4% win

So the fix is not another confluence indicator. It is a model over the
context that demonstrably separates winners from losers, trained on
outcomes rather than on opinion.

FAILURE SEMANTICS

The controlling rule of this codebase is that missing, invalid or stale
data must never silently become positive evidence. So:

  * no model artifact            -> available False, passed None.
                                   The pipeline ignores this stage. It
                                   does NOT invent a probability and it
                                   does NOT block trading, because a
                                   stage that was never trained has no
                                   standing to veto anything.
  * model present but a feature
    it needs is missing          -> available False, passed False.
                                   Asked to judge and unable to, the
                                   answer is no.
  * model present, features fine -> available True, passed = p >= floor.

That asymmetry is deliberate. "Not installed" and "installed but
broken right now" are different situations and collapsing them is how
a filter silently stops filtering.

MODEL FORMAT

A standardized logistic regression stored as plain JSON: feature order,
per-feature mean/scale, coefficients, intercept, plus the validation
metrics it earned. Inference is one dot product, so this module imports
nothing beyond the stdlib -- no sklearn, no pickle, no numpy at serve
time. Training (core/train_meta_label.py) is where sklearn lives.

Plain JSON over pickle on purpose: a pickle is executable, version-
brittle, and unreadable in a diff. A trader who wants to know what the
model actually weights can open this file and read it.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import math
import os
import threading

logger = logging.getLogger(__name__)

# Artifact location. Kept beside the other run outputs (project root)
# rather than inside core/, for the same reason replay_bars/ is: a
# trained model is data, not source.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "meta_label_model.json")

# Current feature-contract version. Bumped whenever FEATURES changes in
# a way that invalidates an existing artifact. A model whose
# feature_version does not match is refused rather than silently scored
# against mismatched columns -- the failure mode of a shifted feature
# vector is a confident wrong answer, which is worse than no answer.
FEATURE_VERSION = 1


# ============================================================
# FEATURES
# ============================================================
# One extractor per feature, sharing a single definition between
# training and inference. Train/serve skew -- the model learning column
# k as "spread" and being served column k as "ATR" -- produces a model
# that validates well and is wrong in production, with nothing in
# either log to show for it. One list, both paths.
#
# Every extractor returns Optional[float]; None means "this decision
# genuinely does not carry that fact", which is distinct from 0.0 and
# is handled by the caller rather than being coerced.

def _f(v) -> Optional[float]:
    """Float or None. Never raises, never guesses."""
    if v is None or isinstance(v, bool):
        return float(v) if isinstance(v, bool) else None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and float("-inf") < f < float("inf") else None


def _b(v) -> Optional[float]:
    """Boolean as 1.0/0.0. None stays None -- an unknown flag is not False."""
    if v is None:
        return None
    return 1.0 if bool(v) else 0.0


def _grade_rank(g) -> Optional[float]:
    """Zone grade as an ordinal. A is best; unknown grades are not scored."""
    if not isinstance(g, str):
        return None
    return {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}.get(g.strip().upper())


def _eq(value, target) -> Optional[float]:
    """One-hot for a categorical, None when the field is absent."""
    if value is None:
        return None
    return 1.0 if str(value).strip().upper() == target else 0.0


def _spread_to_stop(cap: Dict[str, Any]) -> Optional[float]:
    """
    Spread as a fraction of the stop distance.

    The single most discriminating context measure in the replay: the
    audit flags "spread exceeds stop distance" on 22.8% of decisions,
    and those are trades that begin already beyond their own stop. A
    raw spread in pips cannot express that, because 30 pips is cheap
    against a 300-pip stop and fatal against a 20-pip one. This ratio
    is what actually decides whether the setup can pay for itself.
    """
    spread = _f(cap.get("spread_pips"))
    sl = _f(cap.get("sl_pips"))
    if spread is None or sl is None or sl <= 0:
        return None
    return spread / sl


def _rr_times_prob(cap: Dict[str, Any]) -> Optional[float]:
    """
    Stated probability scaled by planned R:R -- a crude expected value.

    Included because the two inputs are individually uninformative in
    the measured sample (the probability buckets are flat: 26.5% win at
    90-100% stated, 30.1% at 20-30%) while their product at least has
    the right units for the decision being made. If it also carries no
    signal, the purged validation will say so and the coefficient will
    shrink toward zero.
    """
    p = _f(cap.get("probability"))
    rr = _f(cap.get("rr_ratio"))
    if p is None or rr is None:
        return None
    return (p / 100.0) * rr


def _contrib(name: str):
    def get(cap: Dict[str, Any]) -> Optional[float]:
        return _f((cap.get("contributions") or {}).get(name))
    return get


def _list_len(key: str):
    def get(cap: Dict[str, Any]) -> Optional[float]:
        v = cap.get(key)
        return float(len(v)) if isinstance(v, (list, tuple)) else None
    return get


# (name, extractor). Order IS the model's column order; append only.
FEATURES: List[Tuple[str, Any]] = [
    # --- execution context: where the measured discrimination was ---
    ("spread_pips",          lambda c: _f(c.get("spread_pips"))),
    ("spread_to_stop",       _spread_to_stop),
    ("atr_pips",             lambda c: _f(c.get("atr_pips"))),
    ("volume_ratio",         lambda c: _f(c.get("volume_ratio"))),
    ("adx",                  lambda c: _f(c.get("adx"))),

    # --- the trade's own geometry ---
    ("rr_ratio",             lambda c: _f(c.get("rr_ratio"))),
    ("sl_pips",              lambda c: _f(c.get("sl_pips"))),
    ("tp_pips",              lambda c: _f(c.get("tp_pips"))),
    ("rr_times_prob",        _rr_times_prob),

    # --- what the primary stack thought ---
    ("probability",          lambda c: _f(c.get("probability"))),
    ("signal_count",         lambda c: _f(c.get("signal_count"))),
    ("star_rating",          lambda c: _f(c.get("star_rating"))),
    ("conviction_score",     lambda c: _f(c.get("conviction_score"))),
    ("premium_position_pct", lambda c: _f(c.get("premium_position_pct"))),

    # --- self-consistency: measured at -9.9 points of win rate ---
    ("coherence_violations", lambda c: _f(c.get("coherence_violations"))),
    ("absorbed_total",       lambda c: _f(c.get("absorbed_total"))),
    ("clamped_steps",        lambda c: _f(c.get("clamped_steps"))),

    # --- booleans ---
    ("discount_at_zone",     lambda c: _b(c.get("discount_at_zone"))),
    ("gnn_conflict",         lambda c: _b(c.get("gnn_conflict"))),
    ("liquidity_aligned",    lambda c: _b(c.get("liquidity_aligned"))),
    ("rr_valid",             lambda c: _b(c.get("rr_valid"))),
    ("session_open",         lambda c: _b(c.get("session_open"))),

    # --- categoricals ---
    ("is_buy",               lambda c: _eq(c.get("direction"), "BUY")),
    ("zone_is_demand",       lambda c: _eq(c.get("zone_type"), "DEMAND")),
    ("zone_grade_rank",      lambda c: _grade_rank(c.get("zone_grade"))),
    ("h1_bullish",           lambda c: _eq(c.get("h1_trend"), "BULLISH")),
    ("h1_bearish",           lambda c: _eq(c.get("h1_trend"), "BEARISH")),
    ("regime_choppy",        lambda c: _eq(c.get("regime"), "CHOPPY")),
    ("regime_ranging_calm",  lambda c: _eq(c.get("regime"), "RANGING_CALM")),
    ("regime_trending_calm", lambda c: _eq(c.get("regime"), "TRENDING_CALM")),
    ("regime_squeeze",       lambda c: _eq(c.get("regime"), "SQUEEZE")),

    # --- per-family probability contributions ---
    ("contrib_pattern",      _contrib("pattern")),
    ("contrib_smc",          _contrib("smc")),
    ("contrib_fvg_ifvg",     _contrib("fvg_ifvg")),
    ("contrib_order_flow",   _contrib("order_flow")),
    ("contrib_trend_cascade", _contrib("trend_cascade")),
    ("contrib_adr_exhaustion", _contrib("adr_exhaustion")),
    ("contrib_rvam",         _contrib("rvam")),
    ("contrib_nested_zone",  _contrib("nested_zone")),
    ("contrib_dxy",          _contrib("dxy_confluence")),
]

FEATURE_NAMES: List[str] = [n for n, _ in FEATURES]

# A decision missing any of these cannot be scored at all -- they are
# the ones the model leans on hardest and the ones whose absence means
# the decision never really got far enough to be judged. Everything
# else may be imputed to its training mean, which for a standardized
# model is exactly "contributes nothing".
REQUIRED_FEATURES = {"spread_pips", "atr_pips", "probability"}


def build_features(capture: Dict[str, Any]) -> Tuple[Optional[List[Optional[float]]], Optional[str]]:
    """
    Feature vector for one decision's `capture` dict.

    Returns (values, None) or (None, reason). Values may contain None
    for non-required features; the model imputes those to its own
    training mean, which is the only imputation that leaves a
    standardized linear model's output unchanged.
    """
    if not isinstance(capture, dict):
        return None, "capture is not a dict"

    values: List[Optional[float]] = []
    missing_required: List[str] = []
    for name, extract in FEATURES:
        try:
            v = extract(capture)
        except Exception:                      # an extractor must never
            v = None                           # take the analysis down
        if v is None and name in REQUIRED_FEATURES:
            missing_required.append(name)
        values.append(v)

    if missing_required:
        return None, f"missing required feature(s): {', '.join(missing_required)}"
    return values, None


# ============================================================
# MODEL
# ============================================================

class MetaLabelModel:
    """A standardized logistic regression, scored with the stdlib."""

    __slots__ = ("features", "mean", "scale", "coef", "intercept",
                 "metrics", "feature_version", "trained_at", "source")

    def __init__(self, blob: Dict[str, Any], source: str = ""):
        self.features = list(blob["features"])
        self.mean = [float(x) for x in blob["mean"]]
        self.scale = [float(x) for x in blob["scale"]]
        self.coef = [float(x) for x in blob["coef"]]
        self.intercept = float(blob["intercept"])
        self.metrics = dict(blob.get("metrics") or {})
        self.feature_version = int(blob.get("feature_version", 0))
        self.trained_at = blob.get("trained_at")
        self.source = source

        n = len(self.features)
        if not (len(self.mean) == len(self.scale) == len(self.coef) == n):
            raise ValueError(
                f"model arrays disagree on length: features={n} "
                f"mean={len(self.mean)} scale={len(self.scale)} coef={len(self.coef)}"
            )

    def predict_proba(self, capture: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
        """P(win) for one decision, or (None, reason)."""
        if self.feature_version != FEATURE_VERSION:
            return None, (f"model feature_version {self.feature_version} != "
                          f"code FEATURE_VERSION {FEATURE_VERSION} -- retrain")
        if self.features != FEATURE_NAMES:
            return None, "model feature names do not match this build's FEATURES"

        values, reason = build_features(capture)
        if values is None:
            return None, reason

        z = self.intercept
        for i, v in enumerate(values):
            scale = self.scale[i] or 1.0
            # None -> the training mean -> standardized 0 -> no
            # contribution. An absent feature must not push the score.
            x = 0.0 if v is None else (v - self.mean[i]) / scale
            z += self.coef[i] * x

        # Guard the exponential rather than letting a large |z| raise.
        if z >= 0:
            p = 1.0 / (1.0 + math.exp(-z)) if z < 700 else 1.0
        else:
            e = math.exp(z) if z > -700 else 0.0
            p = e / (1.0 + e)
        return p, None


_model_cache: Dict[str, Optional[MetaLabelModel]] = {}
_model_lock = threading.Lock()


def load_model(path: str = DEFAULT_MODEL_PATH, *, force: bool = False) -> Optional[MetaLabelModel]:
    """
    Load and cache the artifact. Returns None when there isn't one.

    A missing file is normal (nothing trained yet) and logs at debug. A
    file that exists but cannot be parsed is a real problem and logs at
    warning -- that is a filter the operator believes is running.
    """
    with _model_lock:
        if not force and path in _model_cache:
            return _model_cache[path]
        model: Optional[MetaLabelModel] = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                model = MetaLabelModel(json.load(fh), source=path)
            logger.info(
                f"[META_LABEL] loaded {path} "
                f"(features={len(model.features)}, metrics={model.metrics})"
            )
        except FileNotFoundError:
            logger.debug(f"[META_LABEL] no model at {path} -- stage inactive")
        except Exception as e:
            logger.warning(f"[META_LABEL] model at {path} is unusable: {e}")
        _model_cache[path] = model
        return model


def reset_model_cache():
    with _model_lock:
        _model_cache.clear()


# ============================================================
# THE STAGE
# ============================================================

def evaluate_meta_label(capture: Dict[str, Any], *,
                        min_probability: float,
                        model_path: str = DEFAULT_MODEL_PATH) -> Dict[str, Any]:
    """
    Stage 7 verdict for one decision.

    `capture` is engine_replay._capture()'s flat dict, or anything with
    the same keys -- the live pipeline builds the same shape so one
    feature definition serves both paths.

    Returns:
        available          did the stage actually run
        win_probability    P(TP before SL), or None
        passed             True / False, or None when the stage is inactive
        reason             human-readable, always populated
    """
    model = load_model(model_path)
    if model is None:
        # Never trained. Not an opinion, so not a veto -- see the module
        # docstring on why this differs from "trained but broken".
        return {"available": False, "win_probability": None, "passed": None,
                "reason": "no meta-label model trained yet"}

    p, reason = model.predict_proba(capture)
    if p is None:
        return {"available": False, "win_probability": None, "passed": False,
                "reason": f"meta-label could not score this decision: {reason}"}

    passed = p >= min_probability
    return {
        "available": True,
        "win_probability": round(p, 4),
        "passed": passed,
        "min_required": min_probability,
        "reason": (f"meta-label P(win)={p:.3f} "
                   f"{'>=' if passed else '<'} {min_probability:.2f}"),
        "model_metrics": model.metrics,
    }
