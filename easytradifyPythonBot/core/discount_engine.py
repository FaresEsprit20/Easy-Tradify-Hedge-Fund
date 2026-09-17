# core/discount_engine.py
"""
DISCOUNT ENGINE - Professional Discount Detection

Core Principle:
A discount is when price reaches a value area where institutions are likely to enter.
For BUY: Discount = price at or BELOW demand zone (buying low)
For SELL: Discount = price at or ABOVE supply zone (selling high)

The engine identifies:
1. If current price is at discount
2. The quality of the discount (Premium, Good, Deep)
3. The expected direction based on zone type
4. Zone grade impact on discount quality

FIXES APPLIED:
- Fixed threshold inconsistency between is_at_discount and calculate_discount_zone
- Added zone grade multiplier to calculate_discount_zone
- Added proper pip_size validation to prevent division by zero
- Added discount_buffer_pips usage for "at discount" detection
- Added thread-safe singleton with lock
- Fixed return type documentation
- Added grade-adjusted discount quality calculation
- Added comprehensive debug logging
- ADDED: Instrument-aware premium discount thresholds (tighter for Forex)
- ADDED: Distance quality grading with percentage-based scoring
- ADDED: Discount zone age tracking (freshness decay)
- ADDED: Volume confirmation for discount validity
- ADDED: Spread condition check for discount quality
"""

from typing import Dict, Any, Tuple, Optional
import logging

from core.asset_analysis_config import atr_relative_pips
import time
from threading import Lock

logger = logging.getLogger(__name__)


class DiscountEngine:
    """
    Analyzes if current price is at a discount zone.

    A discount is valid when price reaches the value area.
    Quality determines how good the discount is:
    - PREMIUM_DISCOUNT: Within instrument-specific threshold (best)
    - GOOD_DISCOUNT: Within 20 pips of zone
    - DEEP_DISCOUNT: Beyond 20 pips (higher risk)

    Zone grades affect discount quality:
    - Grade A/B zones: Premium discount is even better
    - Grade C/D zones: Discount requires closer proximity
    - Grade E zones: Discount is weak

    INSTRUMENT-AWARE THRESHOLDS:
    - EURUSD, GBPUSD: Premium = 2 pips (tighter for stable Forex)
    - XAUUSD, XAGUSD: Premium = 10 pips (wider for volatile metals)
    - Default: Premium = 3 pips
    """

    # Instrument-aware premium discount thresholds (pips)
    INSTRUMENT_PREMIUM_THRESHOLDS = {
        "EURUSD": 2,
        "GBPUSD": 2,
        "USDJPY": 2,
        "AUDUSD": 2,
        "USDCAD": 2,
        "NZDUSD": 2,
        "USDCHF": 2,
        "EURGBP": 2,
        "EURJPY": 2,
        "GBPJPY": 2,
        "XAUUSD": 10,
        "XAGUSD": 8,
        "DEFAULT": 3
    }

    # Instrument-aware good discount thresholds (pips)
    INSTRUMENT_GOOD_THRESHOLDS = {
        "XAUUSD": 25,
        "XAGUSD": 20,
        "DEFAULT": 20
    }

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize DiscountEngine with optional configuration.

        Args:
            config: Optional configuration dictionary with keys:
                - premium_discount_pips: Pips threshold for premium discount (default 3)
                - good_discount_pips: Pips threshold for good discount (default 20)
                - discount_buffer_pips: Buffer for "at discount" detection (default 1)
                - zone_grade_multipliers: Dict of grade -> multiplier
                - enable_freshness_decay: Enable zone age decay (default True)
                - freshness_decay_rate: Decay rate per minute (default 0.02 = 2%)
                - require_volume_confirmation: Require volume for discount (default False)
        """
        cfg = config or {}

        # Discount quality thresholds (pips) - with instrument awareness
        self.premium_discount_pips = cfg.get('premium_discount_pips', 3)
        self.good_discount_pips = cfg.get('good_discount_pips', 20)
        self.deep_discount_pips = cfg.get('deep_discount_pips', 50)

        # Discount buffer for "at discount" detection (tighter for M1)
        self.discount_buffer_pips = cfg.get('discount_buffer_pips', 1)

        # Zone grade multipliers (affects discount quality)
        self.zone_grade_multipliers = cfg.get('zone_grade_multipliers', {
            "A": 1.0,
            "B": 0.9,
            "C": 0.7,
            "D": 0.5,
            "E": 0.3
        })

        # Discount quality base scores
        self.discount_scores = cfg.get('discount_scores', {
            "PREMIUM_DISCOUNT": 100,
            "GOOD_DISCOUNT": 70,
            "DEEP_DISCOUNT": 40,
            "NO_DISCOUNT": 0,
            "UNKNOWN": 0
        })

        # Grade score multipliers
        self.grade_score_multipliers = cfg.get('grade_score_multipliers', {
            "A": 1.0,
            "B": 0.85,
            "C": 0.7,
            "D": 0.5,
            "E": 0.3
        })

        # Freshness decay settings
        self.enable_freshness_decay = cfg.get('enable_freshness_decay', True)
        self.freshness_decay_rate = cfg.get('freshness_decay_rate', 0.02)  # 2% per minute
        self.max_freshness_minutes = cfg.get('max_freshness_minutes', 60)

        # Volume confirmation settings
        self.require_volume_confirmation = cfg.get('require_volume_confirmation', False)
        self.min_volume_ratio_for_discount = cfg.get('min_volume_ratio_for_discount', 0.7)

        # Zone tracking for freshness
        self._zone_detection_time = {}  # zone_key -> detection_time
        self._zone_touch_count = {}     # zone_key -> touch_count
        self._lock = Lock()

        logger.info(f"[DISCOUNT] Engine initialized: premium={self.premium_discount_pips}p, good={self.good_discount_pips}p, buffer={self.discount_buffer_pips}p")

    def _get_instrument_premium_threshold(self, symbol: str) -> int:
        """Get instrument-specific premium discount threshold."""
        symbol_upper = symbol.upper()
        # ✅ FIXED: was `if key in symbol_upper` (substring match anywhere
        # in the symbol), which could in principle match a key that's
        # merely contained somewhere inside a broker-suffixed symbol name
        # rather than actually being the base instrument. startswith() is
        # the semantically correct check for "this symbol, possibly with
        # a broker suffix appended after it" (e.g. "EURUSD.a", "EURUSDm").
        for key in self.INSTRUMENT_PREMIUM_THRESHOLDS:
            if key != "DEFAULT" and symbol_upper.startswith(key):
                return self.INSTRUMENT_PREMIUM_THRESHOLDS[key]
        return self.INSTRUMENT_PREMIUM_THRESHOLDS["DEFAULT"]

    def _get_instrument_good_threshold(self, symbol: str) -> int:
        """Get instrument-specific good discount threshold."""
        symbol_upper = symbol.upper()
        for key in self.INSTRUMENT_GOOD_THRESHOLDS:
            if key != "DEFAULT" and symbol_upper.startswith(key):
                return self.INSTRUMENT_GOOD_THRESHOLDS[key]
        return self.INSTRUMENT_GOOD_THRESHOLDS["DEFAULT"]

    def _get_grade_multiplier(self, zone_grade: str) -> float:
        """Get zone grade multiplier with fallback."""
        if not zone_grade:
            return 0.5
        return self.zone_grade_multipliers.get(zone_grade.upper(), 0.5)

    # Discount distance bands as ATR fractions (2026-09-15). The pip tables
    # above were tuned on XAGUSD (ATR ~40 pips): premium 8p ~0.2 ATR, good 20p
    # ~0.5 ATR, deep 50p ~1.25 ATR. On a 1-pip-ATR currency pair the same pips
    # were 2 / 20 / 50 ATR, so almost any distance graded as a discount.
    DISCOUNT_ATR_FRACTIONS = {"premium": 0.20, "good": 0.50, "deep": 1.25}

    def _get_discount_quality(self, distance_pips: float, grade_multiplier: float, symbol: str = "DEFAULT",
                              atr_pips: float = None) -> str:
        """
        Get discount quality based on distance and grade multiplier.

        Args:
            distance_pips: Distance in pips from zone
            grade_multiplier: Zone grade multiplier (0.3 to 1.0)
            symbol: Symbol for instrument-specific thresholds

        Returns:
            Discount quality string
        """
        if atr_pips and atr_pips > 0:
            f = self.DISCOUNT_ATR_FRACTIONS
            premium_threshold, good_threshold, deep_threshold = (
                atr_pips * f["premium"], atr_pips * f["good"], atr_pips * f["deep"])
        else:
            premium_threshold = self._get_instrument_premium_threshold(symbol)
            good_threshold = self._get_instrument_good_threshold(symbol)
            deep_threshold = self.deep_discount_pips

        # Apply grade multiplier to thresholds
        adjusted_premium = premium_threshold * grade_multiplier
        adjusted_good = good_threshold * grade_multiplier
        adjusted_deep = deep_threshold * grade_multiplier

        if distance_pips <= adjusted_premium:
            return "PREMIUM_DISCOUNT"
        elif distance_pips <= adjusted_good:
            return "GOOD_DISCOUNT"
        elif distance_pips <= adjusted_deep:
            return "DEEP_DISCOUNT"
        else:
            return "NO_DISCOUNT"

    def _update_zone_tracking(self, zone_key: str, touch_detected: bool = False):
        """Update zone tracking for freshness calculation."""
        with self._lock:
            current_time = time.time()
            if zone_key not in self._zone_detection_time:
                self._zone_detection_time[zone_key] = current_time
                self._zone_touch_count[zone_key] = 1 if touch_detected else 0
            elif touch_detected:
                self._zone_touch_count[zone_key] = self._zone_touch_count.get(zone_key, 0) + 1

    def _get_zone_freshness(self, zone_key: str) -> float:
        """
        Calculate zone freshness score (1.0 = fresh, 0.0 = expired).

        Freshness decays over time: 100% at detection, decays to 0% after max_freshness_minutes.
        """
        if not self.enable_freshness_decay:
            return 1.0

        with self._lock:
            detection_time = self._zone_detection_time.get(zone_key)
            if detection_time is None:
                return 1.0

            age_minutes = (time.time() - detection_time) / 60
            if age_minutes >= self.max_freshness_minutes:
                return 0.0

            freshness = 1.0 - (age_minutes * self.freshness_decay_rate)
            return max(0.0, min(1.0, freshness))

    def _calculate_discount_score(
        self,
        discount_quality: str,
        zone_grade: str,
        distance_pips: float,
        symbol: str,
        volume_ratio: float = 1.0,
        spread_pips: float = 1.0,
        zone_key: Optional[str] = None,
        atr_pips: Optional[float] = None,
        freshness: Optional[float] = None,
        touch_count: Optional[int] = None,
    ) -> int:
        """
        Calculate enhanced discount score with multiple factors.

        Factors:
        - Base quality score (40-100)
        - Grade multiplier (0.3-1.0)
        - Distance penalty (closer is better)
        - Freshness penalty (older zones are weaker)
        - Mitigation penalty (heavily-revisited zones are weaker)
        - Volume confirmation bonus
        - Spread condition penalty

        ✅ FIXED: freshness previously used a locally-built zone_key of
        f"{zone_grade}_{distance_pips:.2f}", which changes almost every
        tick (distance_pips moves continuously) and was NEVER registered
        by _update_zone_tracking() (only calculate_discount_zone()'s
        stable f"{zone_level}_{zone_type}" key is). That meant
        _get_zone_freshness() always saw an untracked key and returned
        1.0 unconditionally. zone_key is now passed in from the caller
        so both use the SAME stable identity for the same zone.
        """
        # Base quality score
        base_score = self.discount_scores.get(discount_quality, 0)

        # Grade multiplier
        grade_mult = self.grade_score_multipliers.get(zone_grade.upper(), 0.5)

        # Distance penalty (closer to zone = better), in ATR when known
        d = distance_pips / atr_pips if atr_pips and atr_pips > 0 else distance_pips
        steps = (0.1, 0.25, 0.5, 1.0) if atr_pips and atr_pips > 0 else (1, 3, 5, 10)
        if d <= steps[0]:
            distance_factor = 1.0
        elif d <= steps[1]:
            distance_factor = 0.95
        elif d <= steps[2]:
            distance_factor = 0.9
        elif d <= steps[3]:
            distance_factor = 0.8
        else:
            distance_factor = 0.7

        # ✅ FIXED (2026-09-15): freshness was wall-clock minutes since this
        # PROCESS first saw the zone, and the touch count went up on every
        # analysis call made near it -- a restart made every zone fresh, a
        # fast poll exhausted it. Both now come from the zone itself, as
        # measured on the bars by the supply/demand detector.
        if freshness is None:
            freshness = 1.0
        if touch_count is None:
            touch_count = 0
        if touch_count <= 1:
            mitigation_factor = 1.0        # first touch (or untouched) — full strength
        elif touch_count <= 3:
            mitigation_factor = 0.9        # partially mitigated
        elif touch_count <= 6:
            mitigation_factor = 0.75
        else:
            mitigation_factor = 0.55       # likely exhausted, still tradable but flagged weaker

        # Volume confirmation
        # ✅ FIXED: require_volume_confirmation previously only ever added a
        # +5% bonus when volume happened to be sufficient -- it never did
        # anything when volume was insufficient, so setting it to True
        # "required" nothing; low-volume discounts scored identically to
        # high-volume ones. Now: True + sufficient volume still gives the
        # +5% bonus, but True + insufficient volume applies a real penalty
        # (0.5x) big enough to usually push the score below
        # min_discount_score, which is what actually blocks entry
        # downstream in entry_engine._is_discount_valid(). False preserves
        # the old neutral (1.0) behavior exactly, so nothing changes for
        # anyone not using this setting.
        volume_bonus = 1.0
        if self.require_volume_confirmation:
            if volume_ratio >= self.min_volume_ratio_for_discount:
                volume_bonus = 1.05
            else:
                volume_bonus = 0.5
                logger.debug(
                    f"[DISCOUNT_SCORE] volume confirmation required but "
                    f"volume_ratio={volume_ratio:.2f} < {self.min_volume_ratio_for_discount} "
                    f"-- applying 0.5x penalty"
                )

        # Spread penalty (high spread reduces discount quality)
        spread_penalty = 1.0
        if spread_pips > 5:
            spread_penalty = 0.95
        elif spread_pips > 10:
            spread_penalty = 0.9

        # Calculate final score
        final_score = base_score * grade_mult * distance_factor * freshness * mitigation_factor * volume_bonus * spread_penalty

        logger.debug(f"[DISCOUNT_SCORE] {discount_quality} + grade {zone_grade} = {final_score:.0f} (dist_factor={distance_factor:.2f}, freshness={freshness:.2f}, mitigation={mitigation_factor:.2f}, touch_count={touch_count})")

        return int(max(0, min(100, final_score)))

    def is_at_discount(
        self,
        current_price: float,
        zone_level: float,
        zone_type: str,
        zone_grade: str,
        pip_size: float,
        symbol: str = "DEFAULT"
    ) -> Tuple[bool, str, float, str]:
        """
        Determine if price is at a discount zone.

        FIXED: Now properly handles discount buffer and grade multipliers.
        FIXED: Added instrument-aware premium thresholds.

        Returns:
            (is_at_discount, quality_or_reason, distance_pips, expected_direction)
        """
        # Safety checks with validation
        if zone_level is None:
            logger.warning(f"[DISCOUNT] zone_level is None for {zone_type} zone")
            zone_level = current_price

        # ✅ FIXED: was `zone_type = "DEMAND"` -- a missing zone type was
        # silently coerced into a BUY zone. Sitting among genuinely
        # defensive fallbacks (zone_level -> current_price, zone_grade ->
        # "E", pip_size -> 0.0001) it reads like one, but it is not the
        # same kind of thing: those degrade toward NO signal, while this
        # invents a DIRECTION.
        #
        # zone_type is None on 39.1% of replayed decisions, so any of
        # those reaching here were treated as demand zones and biased
        # bullish, on a warning-free path, with an expected_direction of
        # "BUY" that looked entirely normal downstream.
        #
        # Unknown now falls through to this function's existing
        # "Unknown zone_type" branch, which returns NEUTRAL / UNKNOWN --
        # the correct answer for a zone whose side is not known.
        if zone_type is None:
            logger.warning(
                "[DISCOUNT] zone_type is None -- scoring as UNKNOWN. "
                "Previously this was silently treated as a DEMAND (buy) zone.")
        else:
            # Normalised once, here, so every `== "DEMAND"` / `== "SUPPLY"`
            # branch below agrees. Without this a zone_type differing only
            # in case falls through to the unknown branch and loses a
            # perfectly valid signal -- the mirror of the FVG polarity bug,
            # where a lowercase "bullish" became a full-strength SELL.
            zone_type = str(zone_type).strip().upper()

        if zone_grade is None:
            zone_grade = "E"

        # pip_size validation to prevent division by zero
        if pip_size is None or pip_size <= 0:
            logger.warning(f"[DISCOUNT] Invalid pip_size={pip_size}, using default 0.0001")
            pip_size = 0.0001

        distance = abs(current_price - zone_level)
        distance_pips = distance / pip_size

        # ✅ HARDENED: was `"BUY" if zone_type == "DEMAND" else "SELL"`, so
        # anything that was not exactly "DEMAND" -- None, "", a lowercase
        # "demand", an unexpected label -- became a SELL. The docstring
        # says zone_type is "DEMAND" or "SUPPLY"; nothing enforced it.
        #
        # Currently LATENT, not active: zone_type is None on 39.1% of
        # replayed decisions, but those never reach this line (their
        # expected_direction is also None), so no live decision is known
        # to have been flipped by it. It is hardened anyway because the
        # identical idiom WAS active in score_fvg_ifvg_indicator(), where
        # any unrecognised polarity produced a full-strength SELL, and
        # because expected_direction feeds _is_discount_valid()'s
        # "zone opposes trade" check -- a wrong default there silently
        # rejects every trade on one side.
        _zt = str(zone_type or "").strip().upper()
        if _zt == "DEMAND":
            expected_direction = "BUY"
        elif _zt == "SUPPLY":
            expected_direction = "SELL"
        else:
            logger.warning(
                f"[DISCOUNT] unrecognised zone_type {zone_type!r} -- cannot "
                f"infer a direction. Previously this defaulted to SELL.")
            expected_direction = None

        # Get grade-adjusted thresholds
        grade_multiplier = self._get_grade_multiplier(zone_grade)
        adjusted_buffer = self.discount_buffer_pips * grade_multiplier

        # Get instrument-specific premium threshold for logging
        premium_threshold = self._get_instrument_premium_threshold(symbol)

        logger.debug(f"[DISCOUNT] zone_type={zone_type}, zone_level={zone_level:.5f}, current={current_price:.5f}")
        logger.debug(f"[DISCOUNT] distance={distance_pips:.2f}p, grade_mult={grade_multiplier:.2f}, buffer={adjusted_buffer:.1f}p")

        if zone_type == "DEMAND":
            # For BUY: discount is when price is AT or BELOW demand zone
            if current_price <= zone_level + (adjusted_buffer * pip_size):
                quality = self._get_discount_quality(distance_pips, grade_multiplier, symbol)
                logger.info(f"[DISCOUNT] ✅ BUY DISCOUNT: {quality} ({distance_pips:.1f}p below/at zone {zone_level:.5f})")
                return True, quality, distance_pips, expected_direction
            else:
                logger.debug(f"[DISCOUNT] ❌ Not at discount: price {current_price:.5f} is above demand zone {zone_level:.5f}")
                return False, "PRICE_ABOVE_ZONE", distance_pips, expected_direction

        elif zone_type == "SUPPLY":
            # For SELL: discount is when price is AT or ABOVE supply zone
            if current_price >= zone_level - (adjusted_buffer * pip_size):
                quality = self._get_discount_quality(distance_pips, grade_multiplier, symbol)
                logger.info(f"[DISCOUNT] ✅ SELL DISCOUNT: {quality} ({distance_pips:.1f}p above/at zone {zone_level:.5f})")
                return True, quality, distance_pips, expected_direction
            else:
                logger.debug(f"[DISCOUNT] ❌ Not at discount: price {current_price:.5f} is below supply zone {zone_level:.5f}")
                return False, "PRICE_BELOW_ZONE", distance_pips, expected_direction

        logger.warning(f"[DISCOUNT] Unknown zone_type: {zone_type}")
        return False, "UNKNOWN_ZONE_TYPE", distance_pips, "NEUTRAL"

    def calculate_discount_zone(
        self,
        current_price: float,
        zone_level: float,
        zone_type: str,
        zone_grade: str,
        pip_size: float,
        symbol: str = "DEFAULT",
        volume_ratio: float = 1.0,
        spread_pips: float = 1.0,
        atr_pips: float = None
    ) -> Dict[str, Any]:
        """
        Calculate the discount zone information with enhanced scoring.

        FIXED: Now uses grade multipliers consistently with is_at_discount().
        FIXED: Added enhanced discount scoring with multiple factors.

        Args:
            current_price: Current market price
            zone_level: The zone level (demand or supply)
            zone_type: "DEMAND" or "SUPPLY"
            zone_grade: Zone grade (A, B, C, D, E)
            pip_size: Pip size for the symbol
            symbol: Symbol for instrument-specific thresholds
            volume_ratio: Volume ratio for confirmation (optional)
            spread_pips: Current spread for penalty (optional)

        Returns:
            Dictionary with discount information
        """
        # Safety checks for None values
        if zone_level is None:
            logger.warning(f"[DISCOUNT] zone_level is None, using current_price {current_price:.5f} as fallback")
            zone_level = current_price

        # ✅ FIXED: was `zone_type = "DEMAND"` -- a missing zone type was
        # silently coerced into a BUY zone. Sitting among genuinely
        # defensive fallbacks (zone_level -> current_price, zone_grade ->
        # "E", pip_size -> 0.0001) it reads like one, but it is not the
        # same kind of thing: those degrade toward NO signal, while this
        # invents a DIRECTION.
        #
        # zone_type is None on 39.1% of replayed decisions, so any of
        # those reaching here were treated as demand zones and biased
        # bullish, on a warning-free path, with an expected_direction of
        # "BUY" that looked entirely normal downstream.
        #
        # Unknown now falls through to this function's existing
        # "Unknown zone_type" branch, which returns NEUTRAL / UNKNOWN --
        # the correct answer for a zone whose side is not known.
        if zone_type is None:
            logger.warning(
                "[DISCOUNT] zone_type is None -- scoring as UNKNOWN. "
                "Previously this was silently treated as a DEMAND (buy) zone.")
        else:
            # Normalised once, here, so every `== "DEMAND"` / `== "SUPPLY"`
            # branch below agrees. Without this a zone_type differing only
            # in case falls through to the unknown branch and loses a
            # perfectly valid signal -- the mirror of the FVG polarity bug,
            # where a lowercase "bullish" became a full-strength SELL.
            zone_type = str(zone_type).strip().upper()

        if zone_grade is None:
            zone_grade = "E"

        # pip_size validation
        if pip_size is None or pip_size <= 0:
            logger.warning(f"[DISCOUNT] Invalid pip_size={pip_size}, using default 0.0001")
            pip_size = 0.0001

        distance = abs(current_price - zone_level)
        distance_pips = distance / pip_size

        # ✅ HARDENED: was `"BUY" if zone_type == "DEMAND" else "SELL"`, so
        # anything that was not exactly "DEMAND" -- None, "", a lowercase
        # "demand", an unexpected label -- became a SELL. The docstring
        # says zone_type is "DEMAND" or "SUPPLY"; nothing enforced it.
        #
        # Currently LATENT, not active: zone_type is None on 39.1% of
        # replayed decisions, but those never reach this line (their
        # expected_direction is also None), so no live decision is known
        # to have been flipped by it. It is hardened anyway because the
        # identical idiom WAS active in score_fvg_ifvg_indicator(), where
        # any unrecognised polarity produced a full-strength SELL, and
        # because expected_direction feeds _is_discount_valid()'s
        # "zone opposes trade" check -- a wrong default there silently
        # rejects every trade on one side.
        _zt = str(zone_type or "").strip().upper()
        if _zt == "DEMAND":
            expected_direction = "BUY"
        elif _zt == "SUPPLY":
            expected_direction = "SELL"
        else:
            logger.warning(
                f"[DISCOUNT] unrecognised zone_type {zone_type!r} -- cannot "
                f"infer a direction. Previously this defaulted to SELL.")
            expected_direction = None

        # Get grade multiplier and use it for quality calculation
        grade_multiplier = self._get_grade_multiplier(zone_grade)
        # ✅ SCALED. discount_buffer_pips defaults to 1, so the "is price at
        # the zone" window was 0.9 pips at grade B. That is 75% of a bar's
        # range on EURUSD -- sane, and clearly what it was written for --
        # but 1.5% on XAGUSD and 0.4% on XAUUSD. Price had to land inside a
        # 0.9-pip window on an instrument moving 227 pips a minute, sampled
        # once per analysis rather than continuously. discount_quality came
        # back NO_DISCOUNT with score 0 on every payload once the zone gate
        # opened, and this buffer is why.
        #
        # Floored at 0.10 ATR -- the same fraction ZONE_TOUCH_ATR_FRACTION
        # uses for "price touched this zone", so the two stay one idea
        # rather than drifting into separate definitions of the same event.
        adjusted_buffer = atr_relative_pips(
            self.discount_buffer_pips * grade_multiplier, atr_pips, 0.10
        )

        # Get instrument-specific thresholds
        premium_threshold = self._get_instrument_premium_threshold(symbol)
        good_threshold = self._get_instrument_good_threshold(symbol)
        adjusted_premium = premium_threshold * grade_multiplier
        adjusted_good = good_threshold * grade_multiplier

        logger.debug(f"[DISCOUNT_CALC] zone_type={zone_type}, zone_level={zone_level:.5f}, zone_grade={zone_grade}")
        logger.debug(f"[DISCOUNT_CALC] current={current_price:.5f}, distance={distance_pips:.2f}p, grade_mult={grade_multiplier:.2f}")

        # Update zone tracking
        # ✅ FIXED: zone_key used to embed the raw, unrounded zone_level
        # float directly. Since zone_level comes from upstream swing
        # detection re-run on a slightly different rates window every
        # call (a new bar arrives, the lookback window shifts), the same
        # conceptual zone could produce a key that differs by sub-pip
        # float noise between calls -- silently fragmenting freshness/
        # mitigation tracking back to "first touch" every time instead of
        # accumulating. Rounded to the same 5-decimal precision this
        # value is already displayed at everywhere else in this
        # codebase, so genuinely different zones still get distinct
        # keys, but float noise well below a tenth of a pip can't.
        zone_key = f"{round(zone_level, 5)}_{zone_type}"
        try:
            from core.indicators import get_zone_quality_breakdown
            _facts = get_zone_quality_breakdown(zone_level, zone_type, symbol) or {}
        except Exception:
            _facts = {}
        freshness = float(_facts.get("freshness", 1.0))
        zone_touch_count = int(_facts.get("touch_count", 0))

        if zone_type == "DEMAND":
            # For BUY: discount is when price is AT or BELOW demand zone
            if current_price <= zone_level + (adjusted_buffer * pip_size):
                discount_quality = self._get_discount_quality(distance_pips, grade_multiplier, symbol, atr_pips)

                # Calculate enhanced score
                discount_score = self._calculate_discount_score(
                    discount_quality, zone_grade, distance_pips, symbol, volume_ratio, spread_pips,
                    zone_key=zone_key, atr_pips=atr_pips, freshness=freshness, touch_count=zone_touch_count
                )

                logger.info(f"[DISCOUNT_CALC] ✅ At DISCOUNT: price {current_price:.5f} <= zone {zone_level:.5f} ({discount_quality})")

                # Build debug info
                debug_info = {
                    "zone_level": round(zone_level, 5),
                    "current_price": round(current_price, 5),
                    "distance_pips": round(distance_pips, 2),
                    "grade_multiplier": round(grade_multiplier, 2),
                    "premium_threshold_pips": premium_threshold,
                    "adjusted_premium_threshold": round(adjusted_premium, 1),
                    "adjusted_good_threshold": round(adjusted_good, 1),
                    "freshness_score": round(freshness, 2),
                    "zone_touch_count": zone_touch_count,
                    "instrument": symbol,
                    # ✅ the ATR-scaled "at the zone" window that
                    # decided this branch, so a NO_DISCOUNT can be
                    # read against the distance rather than guessed at
                    "buffer_pips_used": round(adjusted_buffer, 2),
                    "atr_pips": atr_pips
                }

                return {
                    "discount_level": zone_level,
                    "is_already_at_discount": True,
                    "distance_pips": round(distance_pips, 1),
                    "expected_direction": expected_direction,
                    "discount_quality": discount_quality,
                    "zone_grade": zone_grade,
                    "grade_multiplier": round(grade_multiplier, 2),
                    "discount_score": discount_score,
                    "freshness_score": round(freshness, 2),
                    "action": "READY_FOR_CONFIRMATION",
                    "debug": debug_info
                }
            else:
                logger.debug(f"[DISCOUNT_CALC] ❌ NOT at discount: price {current_price:.5f} > zone {zone_level:.5f} (need to drop {distance_pips:.1f}p)")
                return {
                    "discount_level": zone_level,
                    "is_already_at_discount": False,
                    "distance_pips": round(distance_pips, 1),
                    "expected_direction": expected_direction,
                    "discount_quality": "NO_DISCOUNT",
                    "zone_grade": zone_grade,
                    "grade_multiplier": round(grade_multiplier, 2),
                    "discount_score": 0,
                    "freshness_score": round(freshness, 2),
                    "action": f"WAIT_FOR_PRICE_TO_DROP_{distance_pips:.1f}PIPS",
                    "debug": {
                        "distance_pips": round(distance_pips, 2),
                        "need_to_drop": round(distance_pips, 1),
                        "instrument": symbol,
                    # ✅ the ATR-scaled "at the zone" window that
                    # decided this branch, so a NO_DISCOUNT can be
                    # read against the distance rather than guessed at
                    "buffer_pips_used": round(adjusted_buffer, 2),
                    "atr_pips": atr_pips
                    }
                }

        elif zone_type == "SUPPLY":
            # For SELL: discount is when price is AT or ABOVE supply zone
            if current_price >= zone_level - (adjusted_buffer * pip_size):
                discount_quality = self._get_discount_quality(distance_pips, grade_multiplier, symbol, atr_pips)

                # Calculate enhanced score
                discount_score = self._calculate_discount_score(
                    discount_quality, zone_grade, distance_pips, symbol, volume_ratio, spread_pips,
                    zone_key=zone_key, atr_pips=atr_pips, freshness=freshness, touch_count=zone_touch_count
                )

                logger.info(f"[DISCOUNT_CALC] ✅ At DISCOUNT: price {current_price:.5f} >= zone {zone_level:.5f} ({discount_quality})")

                debug_info = {
                    "zone_level": round(zone_level, 5),
                    "current_price": round(current_price, 5),
                    "distance_pips": round(distance_pips, 2),
                    "grade_multiplier": round(grade_multiplier, 2),
                    "premium_threshold_pips": premium_threshold,
                    "adjusted_premium_threshold": round(adjusted_premium, 1),
                    "adjusted_good_threshold": round(adjusted_good, 1),
                    "freshness_score": round(freshness, 2),
                    "zone_touch_count": zone_touch_count,
                    "instrument": symbol,
                    # ✅ the ATR-scaled "at the zone" window that
                    # decided this branch, so a NO_DISCOUNT can be
                    # read against the distance rather than guessed at
                    "buffer_pips_used": round(adjusted_buffer, 2),
                    "atr_pips": atr_pips
                }

                return {
                    "discount_level": zone_level,
                    "is_already_at_discount": True,
                    "distance_pips": round(distance_pips, 1),
                    "expected_direction": expected_direction,
                    "discount_quality": discount_quality,
                    "zone_grade": zone_grade,
                    "grade_multiplier": round(grade_multiplier, 2),
                    "discount_score": discount_score,
                    "freshness_score": round(freshness, 2),
                    "action": "READY_FOR_CONFIRMATION",
                    "debug": debug_info
                }
            else:
                logger.debug(f"[DISCOUNT_CALC] ❌ NOT at discount: price {current_price:.5f} < zone {zone_level:.5f} (need to rise {distance_pips:.1f}p)")
                return {
                    "discount_level": zone_level,
                    "is_already_at_discount": False,
                    "distance_pips": round(distance_pips, 1),
                    "expected_direction": expected_direction,
                    "discount_quality": "NO_DISCOUNT",
                    "zone_grade": zone_grade,
                    "grade_multiplier": round(grade_multiplier, 2),
                    "discount_score": 0,
                    "freshness_score": round(freshness, 2),
                    "action": f"WAIT_FOR_PRICE_TO_RISE_{distance_pips:.1f}PIPS",
                    "debug": {
                        "distance_pips": round(distance_pips, 2),
                        "need_to_rise": round(distance_pips, 1),
                        "instrument": symbol,
                    # ✅ the ATR-scaled "at the zone" window that
                    # decided this branch, so a NO_DISCOUNT can be
                    # read against the distance rather than guessed at
                    "buffer_pips_used": round(adjusted_buffer, 2),
                    "atr_pips": atr_pips
                    }
                }

        logger.warning(f"[DISCOUNT_CALC] Unknown zone_type: {zone_type}")
        return {
            "discount_level": current_price,
            "is_already_at_discount": False,
            "distance_pips": 0,
            "expected_direction": "NEUTRAL",
            "discount_quality": "UNKNOWN",
            "zone_grade": zone_grade,
            "grade_multiplier": 0.5,
            "discount_score": 0,
            "freshness_score": 0,
            "action": "UNKNOWN_ZONE"
        }

    def get_discount_score(self, discount_quality: str, zone_grade: str) -> int:
        """
        Calculate a numeric score for the discount quality.

        Args:
            discount_quality: Quality string from discount detection
            zone_grade: Zone grade (A, B, C, D, E)

        Returns:
            Numeric score (0-100)
        """
        base_score = self.discount_scores.get(discount_quality, 0)
        grade_mult = self.grade_score_multipliers.get(zone_grade.upper(), 0.5)

        final_score = int(base_score * grade_mult)
        logger.debug(f"[DISCOUNT_SCORE] {discount_quality} + grade {zone_grade} = {final_score}")

        return final_score

    def get_discount_summary(
        self,
        current_price: float,
        zone_level: float,
        zone_type: str,
        zone_grade: str,
        pip_size: float,
        symbol: str = "DEFAULT",
        volume_ratio: float = 1.0,
        spread_pips: float = 1.0
    ) -> Dict[str, Any]:
        """
        Get a comprehensive discount summary with enhanced scoring.

        Returns:
            Dictionary with all discount-related information
        """
        # First get the detailed discount calculation
        discount_result = self.calculate_discount_zone(
            current_price, zone_level, zone_type, zone_grade, pip_size, symbol, volume_ratio, spread_pips
        )

        # Build comprehensive summary
        summary = {
            "is_at_discount": discount_result.get("is_already_at_discount", False),
            "discount_quality": discount_result.get("discount_quality", "NO_DISCOUNT"),
            "distance_to_discount_pips": discount_result.get("distance_pips", 0),
            "expected_direction": discount_result.get("expected_direction", "NEUTRAL"),
            "zone_grade": zone_grade,
            "discount_score": discount_result.get("discount_score", 0),
            "freshness_score": discount_result.get("freshness_score", 1.0),
            "grade_multiplier": discount_result.get("grade_multiplier", 1.0),
            "action": discount_result.get("action", "UNKNOWN"),
            "discount_level": discount_result.get("discount_level", zone_level),
            "premium_threshold_pips": self._get_instrument_premium_threshold(symbol),
            "good_threshold_pips": self._get_instrument_good_threshold(symbol),
            "debug": discount_result.get("debug", {})
        }

        return summary

    def reset_zone_tracking(self):
        """Reset zone tracking data (useful for testing)."""
        with self._lock:
            self._zone_detection_time.clear()
            self._zone_touch_count.clear()
            logger.info("[DISCOUNT] Zone tracking reset")


# ============================================================
# GLOBAL INSTANCE (Thread-safe)
# ============================================================

_discount_engine = None
_discount_engine_lock = Lock()


def get_discount_engine(config: Dict[str, Any] = None) -> DiscountEngine:
    """Get or create the global discount engine instance (thread-safe)."""
    global _discount_engine
    with _discount_engine_lock:
        if _discount_engine is None:
            _discount_engine = DiscountEngine(config)
        return _discount_engine


def reset_discount_engine(config: Dict[str, Any] = None):
    """Reset the global discount engine instance (useful for testing)."""
    global _discount_engine
    with _discount_engine_lock:
        _discount_engine = DiscountEngine(config)
        logger.info("[DISCOUNT] Engine reset")


def get_discount_summary(
    current_price: float,
    zone_level: float,
    zone_type: str,
    zone_grade: str,
    pip_size: float,
    symbol: str = "DEFAULT",
    volume_ratio: float = 1.0,
    spread_pips: float = 1.0
) -> Dict[str, Any]:
    """
    Convenience function to get discount summary with enhanced scoring.
    """
    engine = get_discount_engine()
    return engine.get_discount_summary(current_price, zone_level, zone_type, zone_grade, pip_size, symbol, volume_ratio, spread_pips)


def is_at_discount(
    current_price: float,
    zone_level: float,
    zone_type: str,
    zone_grade: str,
    pip_size: float,
    symbol: str = "DEFAULT"
) -> Tuple[bool, str, float, str]:
    """
    Convenience function to check if price is at discount.

    Returns:
        (is_at_discount, quality, distance_pips, expected_direction)
    """
    engine = get_discount_engine()
    return engine.is_at_discount(current_price, zone_level, zone_type, zone_grade, pip_size, symbol)


def reset_zone_tracking():
    """Reset zone tracking data for all symbols."""
    engine = get_discount_engine()
    engine.reset_zone_tracking()