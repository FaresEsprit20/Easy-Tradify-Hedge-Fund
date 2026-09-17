"""
ENTRY ENGINE - the entry decision as one rule table (entry foundation v2, 2026-09-17)

Every decision evaluates EVERY rule below, records the whole table, and enters
only when no rule in "block" mode failed:

    rule              checks                                           status when it blocks first
    zone              a supply/demand zone with a tradable grade       INVALID_ZONE
    signals           golden signals >= ENTRY_MIN_SIGNALS              NO_POTENTIAL
    probability       floor <= probability <= ceiling                  INSUFFICIENT_PROBABILITY
    setup             the winning group's own trade setup is valid     NO_STRATEGY_SETUP
    discount          price back at the zone                           WAITING_DISCOUNT
    discount_quality  zone on the trade's side, quality and score      POOR_DISCOUNT
    confirmation      the last CLOSED bar confirms the direction       WAITING_CONFIRMATION
    timing            tick micro-structure timing confidence           POOR_TIMING
    momentum          the momentum group's strength for this side      WEAK_MOMENTUM

Modes ("block" / "observe") come from asset_analysis_config.ENTRY_RULE_MODES.
When the winning strategy group has trade setups of its own (SMC, mean
reversion, momentum, trend, wave -- core/strategy_setups.py), its setup decides
and the generic location/signal/candle rules are recorded but do not block.
The table is published as entry_analysis.rules with entry_analysis.blocked_by,
so each rule can be measured on the decisions the other rules stopped.

One rule, one place. Spread is judged by the veto engine (high_spread), the
candle's age by nobody (every reading is taken on closed bars, see
asset_analysis_config.DISABLED_VETOS), and the probability only here, with the
floor the caller passes for the scale its probability is on.
"""

from typing import Dict, Any, List, Mapping, Tuple, Optional
import logging
import time
from threading import Lock

# Import discount engine
from core.discount_engine import get_discount_engine

# [FIXED] ADDED: reuses the SAME small-candle widening shape already applied to
# the veto's wick-reversal check in asset_analysis.py -- hammer/shooting-
# star confirmation here was still using a flat 2.0x ratio regardless of
# candle body size. Importing the raw constants (rather than calling
# get_wick_reversal_ratio() itself) because that function's absolute
# values (3.0/5.0) calibrate a DIFFERENT decision -- the reversal veto,
# not hammer confirmation, which has always been calibrated at 2.0 here.
# Reusing only the WIDENING RATIO (5.0/3.0 ~ 1.67x for tiny bodies)
# preserves this engine's own existing calibration for normal-body
# candles while still fixing the "flat regardless of body size" bug.
from core.asset_analysis_config import (
    TIMING_CORROBORATION_BONUS,
    WICK_REVERSAL_RATIO_NORMAL,
    WICK_REVERSAL_RATIO_SMALL,
    WICK_SMALL_CANDLE_BODY_THRESHOLD,
    CONFIRMATION_MIN_CLOSE_LOCATION,
    CONFIRMATION_MIN_BODY_FRACTION,
    MAX_PROBABILITY_FOR_ENTRY,
    TRADE_PROBABILITY_MINIMUM,
    ENTRY_RULE_MODES,
    ENTRY_MIN_SIGNALS,
    MOMENTUM_STRENGTH_MIN,
)

BLOCK = "block"
OBSERVE = "observe"

# When the winning strategy group has trade setups of its own
# (core/strategy_setups.py), its setup decides where and when to enter. The
# generic location, signal and candle rules are then recorded for that decision
# but do not block: they were one entry applied to every strategy, and their
# measured value is on the average decision, not on a setup's.
SETUP_REPLACES = ("zone", "signals", "discount", "discount_quality", "confirmation", "timing")

# Evaluation and reporting order. When several rules block, the first one
# names the entry_status, so the statuses mean what they always meant.
RULE_ORDER = ("zone", "signals", "probability", "setup", "discount", "discount_quality",
              "confirmation", "timing", "momentum")
RULE_STATUS = {
    "zone": "INVALID_ZONE",
    "signals": "NO_POTENTIAL",
    "probability": "INSUFFICIENT_PROBABILITY",
    "setup": "NO_STRATEGY_SETUP",
    "discount": "WAITING_DISCOUNT",
    "discount_quality": "POOR_DISCOUNT",
    "confirmation": "WAITING_CONFIRMATION",
    "timing": "POOR_TIMING",
    "momentum": "WEAK_MOMENTUM",
}

# Tier 0 -- an entry with NO golden signal -- is disabled (2026-09-15).
# On the 111 stored trades with tick paths it produced 14 entries whose
# direction was right 17% of the time (-0.98R per trade, negative in both
# halves). They reached 80-95 probability, so no probability floor separates
# them; only the tier itself can. This one switch restores it.
ALLOW_UNCONFIRMED_ENTRIES = False

# [FIXED] FIXED: Import from indicators instead of helpers
try:
    from core.indicators import (
        analyze_micro_structure,
        get_volume_ratio,
        get_candle_progress_fixed,
        get_sr_recommendation,
        get_ict_recommendation,
        make_json_safe
    )
    MICRO_STRUCTURE_AVAILABLE = True
except ImportError:
    MICRO_STRUCTURE_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("[ENTRY] analyze_micro_structure not available, using fallback")

logger = logging.getLogger(__name__)


class EntryEngine:
    """
    Determines optimal entry based on discount, micro-structure, and confirmation.
    
    ✅ FIXED: A, B, and C zones are tradable (D, E rejected)
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize EntryEngine with optional configuration.
        """
        cfg = config or {}

        # Signal count -> quality label (drives the star rating of an entry).
        #
        # Until 2026-09-17 each tier also carried a probability bar (45) and a
        # candle-progress bar (20-40%), so this table was a second probability
        # check and one of four candle-age checks. Both are gone: the
        # probability is judged once by the "probability" rule, and candle age
        # judges nothing now that every reading is taken on closed bars.
        # Tier 0 (no golden signal) exists only when ALLOW_UNCONFIRMED_ENTRIES.
        self.signal_thresholds = cfg.get('signal_thresholds', {
            **({0: {"quality": "UNCONFIRMED"}} if ALLOW_UNCONFIRMED_ENTRIES else {}),
            5: {"quality": "PERFECT_PLUS"},
            4: {"quality": "PERFECT"},
            3: {"quality": "EXCELLENT"},
            2: {"quality": "GOOD"},
            1: {"quality": "MODERATE"},
        })
        self.min_signals = cfg.get(
            'min_signals', 0 if ALLOW_UNCONFIRMED_ENTRIES else max(1, int(ENTRY_MIN_SIGNALS)))

        # block / observe per rule; anything missing or unrecognised blocks.
        modes = dict(ENTRY_RULE_MODES)
        modes.update(cfg.get('rule_modes') or {})
        self.rule_modes = {name: (modes.get(name) if modes.get(name) in (BLOCK, OBSERVE) else BLOCK)
                           for name in RULE_ORDER}

        # Confirmation thresholds
        self.wick_rejection_ratio = cfg.get('wick_rejection_ratio', 2.0)
        self.min_timing_confidence = cfg.get('min_timing_confidence', 65)

        # Zone quality thresholds
        self.min_zone_grade = cfg.get('min_zone_grade', "D")  # data-collection: was "C"
        # DATA-COLLECTION MODE (2026-09-10): 50 -> 30. Once the earlier gates
        # were loosened this became the dominant blocker (172 POOR_DISCOUNT
        # in ~3 minutes), i.e. setups now reach it and stop here.
        self.min_discount_score = cfg.get('min_discount_score', 30)
        # The probability floor used when the caller does not pass one. The
        # live caller (core/asset_analysis.py) always passes the floor of the
        # scale its probability is on: 75 on the strategy-group scale, the
        # calibrated model's own floor, or this one on the additive chain.
        self.min_probability_for_entry = cfg.get('min_probability_for_entry', TRADE_PROBABILITY_MINIMUM)
        
        # Grade priority mapping - [FIXED] FIXED: A, B, C are tradable
        self.grade_priority = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        # DATA-COLLECTION MODE (2026-09-10): D admitted. 616 INVALID_ZONE
        # rejections, all grade D. This is the most aggressive of tonight's
        # loosenings and the first to revert: zone grade is a quality claim,
        # and admitting D means the collected sample no longer represents the
        # A/B/C strategy. It does give the models the contrast needed to test
        # whether grade predicts anything at all.
        self.tradable_grades = {"A": True, "B": True, "C": True, "D": True, "E": False}

        # ✅ FIXED: was `cfg.get('valid_zone_grades', ["A", "B", "C"])` -
        # independently configurable from self.tradable_grades (above),
        # which is what _is_zone_valid() actually gates on and is NOT
        # itself configurable. The two could silently disagree depending
        # on what the caller's config passed in - which is exactly what
        # happened: asset_analysis_config.VALID_ZONE_GRADES was ["A","B"],
        # fed in here as valid_zone_grades, while tradable_grades (the
        # real gate) still accepted C, and the rejection message
        # hardcoded "A, B, and C" as a third, independent claim. Three
        # sources of truth for one fact. Now derived directly from
        # tradable_grades so a real config change to what's tradable
        # can't silently desync from what's *displayed* as tradable.
        self.valid_zone_grades = [g for g, ok in self.tradable_grades.items() if ok]
        
        # Timing weights (from micro-structure)
        self.timing_weights = cfg.get('timing_weights', {
            "absorption": 85,
            "spread_collapse": 70,
            "momentum_burst": 65,
            "iceberg": 60,
            "volume_imbalance": 65,
            "neutral": 50
        })
        
        # Star ratings
        # ✅ FIXED: this dict's keys must match evaluate_potential_entry()'s
        # quality labels (self.signal_thresholds' "quality" values --
        # PERFECT_PLUS/PERFECT/EXCELLENT/GOOD/MODERATE) since get_entry_
        # decision() now looks a confirmed entry's star rating up by its
        # actual signal_type instead of hardcoding "PERFECT" for every
        # successful entry regardless of how many golden signals actually
        # confirmed it (see the fix note at that lookup). STRONG/WEAK/NO
        # are kept for any external config that references them, but are
        # never produced by evaluate_potential_entry() itself.
        self.star_ratings = cfg.get('star_ratings', {
            "PERFECT_PLUS": (5, "⭐⭐⭐⭐⭐"),
            "PERFECT": (5, "⭐⭐⭐⭐⭐"),
            "EXCELLENT": (5, "⭐⭐⭐⭐⭐"),
            "STRONG": (4, "⭐⭐⭐⭐"),
            "GOOD": (3, "⭐⭐⭐"),
            "MODERATE": (2, "⭐⭐"),
            "WEAK": (1, "⭐"),
            "NO": (1, "☆")
        })
        
        logger.info(f"[ENTRY] EntryEngine initialized: wick_ratio={self.wick_rejection_ratio}, min_timing={self.min_timing_confidence}")
        logger.info(f"[ENTRY] Zone quality: min_grade={self.min_zone_grade} (A/B/C), min_score={self.min_discount_score}")
        logger.info(f"[ENTRY] Min probability for entry: {self.min_probability_for_entry}%")
    
    def get_micro_structure_signals(
        self,
        symbol: str,
        zone_level: float,
        current_price: float,
        pip_size: float,
        order_type: str = "BUY"
    ) -> Tuple[Dict, bool, bool, bool, bool]:
        """
        Get micro-structure signals for entry confirmation.
        """
        # Handle None zone_level
        if zone_level is None:
            logger.debug(f"[ENTRY] No zone_level provided for {symbol}, using default micro-structure")
            zone_level = current_price
        
        # Fallback when micro-structure analysis not available
        if not MICRO_STRUCTURE_AVAILABLE:
            # [FIXED] FIXED: was logger.debug (invisible at normal log levels), so this
            # entire code path -- which hardcodes timing_confidence=50 for every
            # symbol, every call, forever -- could run silently the whole time
            # the bot was live if the core.indicators import failed at startup.
            logger.warning(
                f"[ENTRY] {symbol}: FALLBACK timing_confidence=50 — "
                f"MICRO_STRUCTURE_AVAILABLE=False (core.indicators import failed at startup, "
                f"see earlier '[ENTRY] analyze_micro_structure not available' log line)"
            )
            fallback_micro = {
                "available": False,
                "reason": "Micro-structure analysis not available",
                "entry_confidence": 50,
                "absorption_detected": False,
                "momentum_burst": False,
                "spread_collapse": False,
                "volume_imbalance_confirms": False,
                "timing_confidence": 50,
                "timing_ready": False,
                "triggers": []
            }
            return fallback_micro, False, False, False, False
        
        try:
            micro_structure = analyze_micro_structure(
                symbol, zone_level, current_price, order_type, 50.0, pip_size
            )
        except Exception as e:
            logger.warning(f"[ENTRY] {symbol}: FALLBACK timing_confidence=50 — analyze_micro_structure() raised: {e}")
            micro_structure = {
                "available": False,
                "reason": f"Error: {str(e)}",
                "entry_confidence": 50,
                "absorption_detected": False,
                "momentum_burst": False,
                "spread_collapse": False,
                "volume_imbalance_confirms": False,
                "timing_confidence": 50,
                "timing_ready": False,
                "triggers": []
            }
        
        absorption = micro_structure.get("absorption_detected", False)
        momentum_burst = micro_structure.get("momentum_burst", False)
        spread_collapse = micro_structure.get("spread_collapse", False)
        # ✅ NEW: real tape-level buy/sell-pressure confirmation (see
        # analyze_micro_structure() in core/indicators.py) -- appended
        # as a 5th return value rather than inserted among the first
        # four, so this stays backward compatible with the single
        # existing call site's 4-value unpack pattern if anything else
        # ever calls this with the old signature.
        volume_imbalance_confirms = micro_structure.get("volume_imbalance_confirms", False)

        return micro_structure, absorption, momentum_burst, spread_collapse, volume_imbalance_confirms
    
    def evaluate_signals(
        self,
        momentum_burst: bool,
        absorption: bool,
        volume_spike: bool,
        at_poi: bool,
        volume_imbalance_confirms: bool = False
    ) -> Tuple[bool, int, str]:
        """
        The "signals" rule: (passed, signal_count, quality label).

        Five golden signals: momentum burst, absorption and volume imbalance
        (live ticks, core/indicators.analyze_micro_structure), volume spike and
        at a point of interest (closed bars). Only the count is judged here;
        the probability has its own rule.
        """
        signal_count = sum(bool(s) for s in (momentum_burst, absorption, volume_spike, at_poi,
                                             volume_imbalance_confirms))
        quality = "NO_SIGNAL"
        for count in sorted(self.signal_thresholds.keys(), reverse=True):
            if signal_count >= count:
                quality = self.signal_thresholds[count]["quality"]
                break
        return signal_count >= self.min_signals, signal_count, quality
    
    def _is_zone_valid(self, zone_grade: str, zone_level: float) -> Tuple[bool, str]:
        """
        Validate zone quality before considering entry.
        
        ✅ FIXED: A, B, and C zones are valid. D, E are rejected.
        """
        if zone_level is None:
            return False, "No valid supply/demand zone detected"

        is_tradable = self.tradable_grades.get(str(zone_grade or "E").upper(), False)
        
        if not is_tradable:
            return False, (f"Zone grade {zone_grade} is not tradable. "
                           f"Tradable grades: {', '.join(self.valid_zone_grades)}.")
        
        return True, "Zone valid"
    
    def _is_discount_valid(self, discount_info: Dict,
                           best_direction: str = None) -> Tuple[bool, str]:
        """
        Validate discount quality before considering entry.

        ✅ FIXED (defect D-17): this checked proximity, quality and score
        but never that the zone TYPE matched the trade direction. A
        DEMAND zone is where you buy; a SUPPLY zone is where you sell.
        Nothing stopped a BUY from qualifying against a supply zone --
        that is, entering long at the exact location the structure says
        sellers are waiting.

        Live proof, XAGUSD 2026-09-01 15:39: direction BUY, discount
        zone_type SUPPLY at 65.019, expected_direction "SELL", price at
        85.6% of range (SMC zone PREMIUM), action
        "WAIT_FOR_PRICE_TO_RISE_15.0PIPS". The engine was waiting for
        price to rise INTO a supply zone in order to buy. SMC agreed it
        was a short setup -- "Price at bearish order block", "Price in
        premium zone", recommendation BEARISH.

        It did not fire that time only because is_already_at_discount was
        False, so it failed on proximity first. Had price risen those 15
        pips the location gate would have passed on a zone that means the
        opposite of the trade.

        best_direction is optional so existing callers keep working; the
        check is skipped rather than guessed when direction is unknown.
        """
        if not discount_info.get("is_already_at_discount", False):
            return False, "Price not at discount"

        # Direction/zone agreement, checked BEFORE quality: a high-grade
        # zone on the wrong side is worse than a low-grade one on the
        # right side, so quality must not be able to carry it.
        expected = discount_info.get("expected_direction")
        if best_direction and expected and expected != best_direction:
            zone_type = discount_info.get("zone_type") or (
                "DEMAND" if expected == "BUY" else "SUPPLY")
            return False, (
                f"Zone opposes trade: {zone_type} zone implies {expected}, "
                f"but direction is {best_direction}"
            )

        discount_quality = discount_info.get("discount_quality", "NO_DISCOUNT")
        if discount_quality in ["NO_DISCOUNT", "UNKNOWN"]:
            return False, f"Discount quality: {discount_quality}"
        
        discount_score = discount_info.get("discount_score", 0)
        if discount_score < self.min_discount_score:
            return False, f"Discount score {discount_score} < {self.min_discount_score}"
        
        return True, "Discount valid"
    
    def _get_confirmation_wick_ratio(self, body_pips: float) -> float:
        """
        Body-size-aware wick ratio for hammer/shooting-star confirmation.

        ✅ FIXED: was a flat self.wick_rejection_ratio (2.0) regardless of
        candle body size. On a tiny-body M1 candle (e.g. 0.3 pips), a
        "2x body" wick is just 0.6 pips -- noise-level, easy to false-
        trigger. Widens proportionally for small bodies using the SAME
        ratio (WICK_REVERSAL_RATIO_SMALL / WICK_REVERSAL_RATIO_NORMAL ≈
        1.67x) already applied to the veto's wick-reversal check, but
        anchored to this engine's own wick_rejection_ratio (2.0) rather
        than the veto's absolute values (3.0/5.0), since the two ratios
        calibrate different decisions and were never meant to be equal.
        """
        if body_pips < WICK_SMALL_CANDLE_BODY_THRESHOLD:
            widen_factor = WICK_REVERSAL_RATIO_SMALL / WICK_REVERSAL_RATIO_NORMAL
            return self.wick_rejection_ratio * widen_factor
        return self.wick_rejection_ratio

    def _close_is_decisive(self, candle_data: Dict, bullish: bool) -> Tuple[bool, str]:
        """
        Did this bar actually close in favour, or merely finish a tick
        the right way?

        The score-60 tier used to accept `close > open and body > 0`,
        which on M1 is close to a coin flip and produced 49 of 52
        confirmations on a 4240-decision replay -- so "confirmed" almost
        always meant nothing. Two conditions make the same idea mean
        something:

          * the close sat near the favourable end of the bar's own
            range (close-location value), i.e. that side held the level
            into the close rather than winning by one tick;
          * the body was a real share of the range, which rejects the
            doji whose "green" close is a tick between two large wicks.

        Returns (ok, why-not) so the rejection is explainable rather
        than a bare False.
        """
        o = candle_data.get("open", 0) or 0
        c = candle_data.get("close", 0) or 0
        hi = candle_data.get("high")
        lo = candle_data.get("low")

        if not (c > o if bullish else c < o):
            return False, "closed against the trade"

        # Without a range there is nothing to locate the close within.
        # Fall back to the old body-only rule rather than inventing a
        # reading: absent data must not become positive evidence, but it
        # must not silently become a rejection either when the caller
        # simply did not supply high/low.
        if hi is None or lo is None:
            return True, "no range available -- body-only check"

        rng = float(hi) - float(lo)
        if rng <= 0:
            return False, "bar has no range"

        body_fraction = abs(c - o) / rng
        if body_fraction < CONFIRMATION_MIN_BODY_FRACTION:
            return False, (f"body is {body_fraction:.0%} of range "
                           f"(<{CONFIRMATION_MIN_BODY_FRACTION:.0%}) -- indecision, "
                           f"not confirmation")

        # Close-location value in [-1, +1]; signed toward the trade.
        clv = ((float(c) - float(lo)) - (float(hi) - float(c))) / rng
        if not bullish:
            clv = -clv
        if clv < CONFIRMATION_MIN_CLOSE_LOCATION:
            return False, (f"close sat at {clv:+.2f} of range "
                           f"(<{CONFIRMATION_MIN_CLOSE_LOCATION:+.2f}) -- the level "
                           f"was not held into the close")

        return True, f"decisive close (clv {clv:+.2f}, body {body_fraction:.0%} of range)"

    def check_discount_confirmation(
        self,
        candle_data: Dict,
        zone_type: str,
        expected_direction: str
    ) -> Tuple[bool, str, int]:
        """
        Check if discount is CONFIRMED by price action.
        """
        body = candle_data.get("body_pips", 0)
        lower_wick = candle_data.get("lower_wick_pips", 0)
        upper_wick = candle_data.get("upper_wick_pips", 0)
        close = candle_data.get("close", 0)
        open_price = candle_data.get("open", 0)
        candle_type = candle_data.get("candle_type", "normal")
        candle_rec = candle_data.get("recommendation", "NEUTRAL")
        
        if body <= 0:
            body = 0.001
        
        if zone_type == "DEMAND" and expected_direction == "BUY":
            # Marubozu: strong bullish candle (BEST confirmation - score 95)
            if candle_type == "marubozu" and close > open_price:
                logger.debug(f"[CONFIRMATION] ✅ MARUBOZU_CONFIRMATION (score 95) - Strongest bullish signal")
                return True, "MARUBOZU_CONFIRMATION", 95
            
            # Hammer: long lower wick (body-size-aware ratio)
            confirmation_wick_ratio = self._get_confirmation_wick_ratio(body)
            if lower_wick > body * confirmation_wick_ratio:
                logger.debug(f"[CONFIRMATION] ✅ HAMMER_CONFIRMATION (score 85) - Lower wick {lower_wick:.1f}p > {body * confirmation_wick_ratio:.1f}p (ratio={confirmation_wick_ratio:.2f})")
                return True, "HAMMER_CONFIRMATION", 85
            
            # Bullish engulfing at discount
            if candle_type in ["marubozu_bullish", "pin_bar_bullish"] or "STRONG_BULLISH" in str(candle_rec):
                logger.debug(f"[CONFIRMATION] ✅ BULLISH_ENGULFING (score 80) - Strong bullish candle")
                return True, "BULLISH_ENGULFING", 80
            
            # Decisive bullish close -- see _close_is_decisive() for why
            # "closed above open" alone is not confirmation.
            ok, why = self._close_is_decisive(candle_data, bullish=True)
            if ok:
                logger.debug(f"[CONFIRMATION] ✅ BULLISH_CLOSE (score 60) - {why}")
                return True, "BULLISH_CLOSE", 60
            logger.debug(f"[CONFIRMATION] bullish close rejected: {why}")

            return False, "NO_CONFIRMATION", 0
        
        elif zone_type == "SUPPLY" and expected_direction == "SELL":
            # Marubozu: strong bearish candle (BEST confirmation - score 95)
            if candle_type == "marubozu" and close < open_price:
                logger.debug(f"[CONFIRMATION] ✅ MARUBOZU_CONFIRMATION (score 95) - Strongest bearish signal")
                return True, "MARUBOZU_CONFIRMATION", 95
            
            # Shooting star: long upper wick (body-size-aware ratio)
            confirmation_wick_ratio = self._get_confirmation_wick_ratio(body)
            if upper_wick > body * confirmation_wick_ratio:
                logger.debug(f"[CONFIRMATION] ✅ SHOOTING_STAR_CONFIRMATION (score 85) - Upper wick {upper_wick:.1f}p > {body * confirmation_wick_ratio:.1f}p (ratio={confirmation_wick_ratio:.2f})")
                return True, "SHOOTING_STAR_CONFIRMATION", 85
            
            # Bearish engulfing at discount
            if candle_type in ["marubozu_bearish", "pin_bar_bearish"] or "STRONG_BEARISH" in str(candle_rec):
                logger.debug(f"[CONFIRMATION] ✅ BEARISH_ENGULFING (score 80) - Strong bearish candle")
                return True, "BEARISH_ENGULFING", 80
            
            # Decisive bearish close -- mirror of the BUY branch above.
            ok, why = self._close_is_decisive(candle_data, bullish=False)
            if ok:
                logger.debug(f"[CONFIRMATION] ✅ BEARISH_CLOSE (score 60) - {why}")
                return True, "BEARISH_CLOSE", 60
            logger.debug(f"[CONFIRMATION] bearish close rejected: {why}")

            return False, "NO_CONFIRMATION", 0
        
        return False, "UNKNOWN_ZONE", 0
    
    def _get_required_confirmation(self, best_direction: str, candle_type: str, is_confirmed: bool) -> Optional[str]:
        """Get the confirmation requirement based on current state."""
        if is_confirmed:
            return None
        
        if candle_type in ["marubozu", "marubozu_bullish", "marubozu_bearish"]:
            return "MARUBOZU_CONFIRMATION"
        
        if best_direction == "BUY":
            return "HAMMER_OR_BULLISH_CLOSE"
        else:
            return "SHOOTING_STAR_OR_BEARISH_CLOSE"
    
    def calculate_timing_confidence(
        self,
        absorption: bool,
        momentum_burst: bool,
        spread_collapse: bool,
        volume_imbalance_confirms: bool = False
    ) -> int:
        """
        Timing confidence from the live tick micro-structure.

        It used to be halved when the spread was too wide and cut by 30% before
        the candle was 75% formed. Both penalties are gone: the spread is the
        veto engine's high_spread check, and the candle's age judges nothing
        now that every reading is taken on closed bars. At 50 x 0.7 = 35 (or 65
        x 0.7 = 45) against a 65 bar, the candle penalty alone had made timing
        impossible in the first 45 seconds of every minute.
        """
        base_confidence = self.timing_weights["neutral"]
        
        if absorption:
            base_confidence = max(base_confidence, self.timing_weights["absorption"])
        if spread_collapse:
            base_confidence = max(base_confidence, self.timing_weights["spread_collapse"])
        if momentum_burst:
            base_confidence = max(base_confidence, self.timing_weights["momentum_burst"])
        # ✅ NEW: real tape-level buy/sell-pressure confirmation now
        # contributes here too, not just to the golden-signal count in
        # evaluate_potential_entry() -- see analyze_micro_structure()
        # in core/indicators.py for where this is actually computed.
        if volume_imbalance_confirms:
            base_confidence = max(base_confidence, self.timing_weights.get("volume_imbalance", 65))

        # ✅ NEW: corroboration bonus.
        #
        # Every branch above is max(), so CONFIRMING signals were discarded:
        # spread_collapse + momentum_burst + volume_imbalance all firing at
        # once scored 70 -- identical to spread_collapse alone. Three
        # independent tape-level reads agreeing counted for exactly as much
        # as one.
        #
        # That interacts badly with min_timing_confidence (75): absorption
        # is worth 85 and everything else caps at 70, so ONLY absorption
        # could ever make timing_ready true, no matter how many other
        # signals agreed. The other three were decorative at this gate.
        #
        # Deliberately small and capped. These signals are correlated --
        # a spread collapse and a volume-imbalance spike often describe the
        # same moment on the tape -- so this is worth a nudge, not a sum.
        # Agreement is partly already priced in.
        confirming = sum([
            bool(absorption), bool(spread_collapse),
            bool(momentum_burst), bool(volume_imbalance_confirms),
        ])
        if confirming > 1:
            base_confidence = min(
                100,
                base_confidence + TIMING_CORROBORATION_BONUS * (confirming - 1),
            )

        return max(30, min(100, base_confidence))
    
    def get_entry_decision(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Entry decision, with per-decision diagnostics stamped on the result.

        The implementation records diagnostics into `_diag` once and this
        wrapper merges them into whatever comes back (setdefault, not
        assignment: a value the decision reports itself is kept).
        """
        diag: Dict[str, Any] = {}
        result = self._get_entry_decision_impl(diag, *args, **kwargs)
        if isinstance(result, dict):
            for k, v in diag.items():
                result.setdefault(k, v)

        # AI_MarketReplay pre-trade timeline. OFF unless AIREPLAY_RECORD_LIVE
        # is set, and structurally unable to affect this decision: the result
        # is passed by reference but only ever read, the call returns None so
        # nothing can branch on it, and both the callee and this line swallow
        # everything. A trade must never fail to open because its telemetry
        # raised.
        try:
            from ai.aireplay.live_recording import record_entry_decision

            record_entry_decision(
                args[0] if args else kwargs.get("symbol"), result)
        except Exception:
            pass

        return result

    def _get_entry_decision_impl(
        self,
        _diag: Dict[str, Any],
        symbol: str,
        best_direction: str,
        current_price: float,
        zone_level: float,
        zone_type: str,
        zone_grade: str,
        candle_data: Dict,
        volume_spike: bool,
        at_poi: bool,
        best_probability: float,
        pip_size: float,
        h1_trend: str = "NEUTRAL",
        h1_aligned: Optional[bool] = None,
        h1_bonus: Optional[int] = None,
        atr_pips: float = None,
        is_replay: bool = False,
        probability_floor: Optional[float] = None,
        strategy_setup: Optional[Mapping[str, Any]] = None,
        momentum_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate every entry rule, then decide.

        probability_floor: the floor for the scale best_probability is on. The
        live caller passes it; without it min_probability_for_entry applies.

        strategy_setup: core/strategy_setups.pick() for the winning group. When
        that group has setups of its own, the "setup" rule decides and the
        SETUP_REPLACES rules are recorded without blocking for this decision.

        h1_aligned / h1_bonus: pass these in if the caller has already computed
        them from h1_trend (asset_analysis.py does, and best_probability arrives
        already adjusted, so this function must not apply the bonus again).
        Leave both None to fall back to the self-contained calculation.

        is_replay: True only when the caller injected historical MarketData.
        Bar replay has no tick stream, so analyze_micro_structure() is always
        unavailable there; the timing rule is then recorded as not measurable
        (passed None) instead of failed. Live, an unavailable tick feed still
        fails the rule.
        """
        discount_engine = get_discount_engine()
        rules: Dict[str, Dict[str, Any]] = {}
        setup = strategy_setup if isinstance(strategy_setup, Mapping) else {}
        modes = dict(self.rule_modes)
        if setup.get("has_setups"):
            for name in SETUP_REPLACES:
                modes[name] = OBSERVE

        def rule(name: str, passed: Optional[bool], value: Any = None, threshold: Any = None,
                 why: str = "") -> None:
            rules[name] = {"passed": passed, "mode": modes.get(name, BLOCK),
                           "value": value, "threshold": threshold, "why": why}

        direction = str(best_direction or "").upper()

        # ---- inputs: all of them, on every decision -----------------------------
        micro_structure, absorption, momentum_burst, spread_collapse, volume_imbalance_confirms = \
            self.get_micro_structure_signals(symbol, zone_level, current_price, pip_size, best_direction)

        signals_ok, signal_count, signal_type = self.evaluate_signals(
            momentum_burst, absorption, volume_spike, at_poi, volume_imbalance_confirms)

        timing_confidence = self.calculate_timing_confidence(
            absorption, momentum_burst, spread_collapse, volume_imbalance_confirms)
        timing_ready = timing_confidence >= self.min_timing_confidence
        # Replay has no real tick stream, so micro_structure["available"] is
        # False on every decision -- a property of bar data, not an outage.
        timing_bypassed_replay = False
        if is_replay and not micro_structure.get("available", True):
            timing_ready = True
            timing_bypassed_replay = True
        micro_structure["timing_confidence"] = timing_confidence
        micro_structure["timing_ready"] = timing_ready

        zone_valid, zone_reason = self._is_zone_valid(zone_grade, zone_level)

        if zone_level is None:
            discount_info = {"is_already_at_discount": False, "discount_quality": "INVALID_ZONE",
                             "zone_grade": zone_grade}
        else:
            # symbol and atr_pips select the instrument's own thresholds and
            # scale the "at the zone" buffer (DEFAULT is an FX-major table).
            discount_info = discount_engine.calculate_discount_zone(
                current_price=current_price,
                zone_level=zone_level,
                zone_type=zone_type,
                zone_grade=zone_grade,
                pip_size=pip_size,
                symbol=symbol,
                atr_pips=atr_pips,
            )
            discount_info.setdefault("zone_type", zone_type)
            if "expected_direction" not in discount_info:
                discount_info["expected_direction"] = (
                    "BUY" if zone_type == "DEMAND" else "SELL" if zone_type == "SUPPLY" else best_direction)
        is_at_discount = bool(discount_info.get("is_already_at_discount", False))
        discount_valid, discount_reason = self._is_discount_valid(discount_info, best_direction)

        # The candle, read for the trade's own direction on the last closed bar.
        if direction in ("BUY", "SELL"):
            is_confirmed, confirmation_type, confirmation_score = self.check_discount_confirmation(
                candle_data or {}, "DEMAND" if direction == "BUY" else "SUPPLY", direction)
        else:
            is_confirmed, confirmation_type, confirmation_score = False, "UNKNOWN_DIRECTION", 0
        required_confirmation = self._get_required_confirmation(
            best_direction, (candle_data or {}).get("candle_type", "normal"), is_confirmed)

        floor = self.min_probability_for_entry if probability_floor is None else float(probability_floor)
        ceiling = float(MAX_PROBABILITY_FOR_ENTRY)
        probability = None if best_probability is None else float(best_probability)

        # ---- the rules ------------------------------------------------------------
        rule("zone", zone_valid, value=zone_grade, threshold="/".join(self.valid_zone_grades),
             why=zone_reason)

        fired = [name for name, on in (("momentum_burst", momentum_burst), ("absorption", absorption),
                                       ("volume_spike", volume_spike), ("at_poi", at_poi),
                                       ("volume_imbalance", volume_imbalance_confirms)) if on]
        rule("signals", signals_ok, value=signal_count, threshold=self.min_signals,
             why=", ".join(fired) if fired else "no golden signal")

        if probability is None:
            probability_ok, probability_why = False, "no probability"
        elif probability < floor:
            probability_ok, probability_why = False, f"{probability:.1f}% below the {floor:g}% floor"
        elif probability > ceiling:
            probability_ok, probability_why = False, f"{probability:.1f}% above the {ceiling:g}% ceiling"
            logger.info(f"[BAND] probability {probability:.1f} above the measured ceiling {ceiling:g}")
        else:
            probability_ok, probability_why = True, f"{probability:.1f}% inside {floor:g}-{ceiling:g}%"
        rule("probability", probability_ok,
             value=None if probability is None else round(probability, 1),
             threshold=f"{floor:g}-{ceiling:g}", why=probability_why)

        rule("setup", setup.get("valid"), value=setup.get("name"), threshold=setup.get("group"),
             why=str(setup.get("why") or "no strategy setup evaluated"))

        if zone_level is None:
            rule("discount", None, why="no zone to measure the distance to")
        else:
            rule("discount", is_at_discount, value=discount_info.get("distance_pips"),
                 threshold=(discount_info.get("debug") or {}).get("buffer_pips_used"),
                 why=str(discount_info.get("action") or discount_info.get("discount_quality") or ""))

        expected = discount_info.get("expected_direction")
        if zone_level is None:
            rule("discount_quality", None, why="no zone")
        elif is_at_discount:
            rule("discount_quality", discount_valid, value=discount_info.get("discount_score"),
                 threshold=self.min_discount_score, why=discount_reason)
        elif expected and direction in ("BUY", "SELL"):
            # Away from the zone only its side can be judged; quality and score
            # are scored at the zone.
            side_ok = expected == direction
            rule("discount_quality", side_ok, value=discount_info.get("discount_score"),
                 threshold=self.min_discount_score,
                 why=("zone is on the trade's side" if side_ok else
                      f"{discount_info.get('zone_type')} zone implies {expected}, trade is {direction}"))
        else:
            rule("discount_quality", None, why="zone direction unknown")

        rule("confirmation", is_confirmed, value=confirmation_type, threshold=confirmation_score,
             why=f"required: {required_confirmation}" if required_confirmation else "closed bar confirms")

        # momentum is a strength reading on whatever the decision trades, not a
        # strategy of its own (asset_analysis_config.MOMENTUM_STRENGTH_MIN)
        rule("momentum", None if momentum_score is None else momentum_score >= MOMENTUM_STRENGTH_MIN,
             value=None if momentum_score is None else round(float(momentum_score), 1),
             threshold=MOMENTUM_STRENGTH_MIN,
             why=("momentum group not scored for this side" if momentum_score is None
                  else f"momentum {momentum_score:.1f} for this side"))

        rule("timing", None if timing_bypassed_replay else timing_ready, value=timing_confidence,
             threshold=self.min_timing_confidence,
             why=("replay: no tick stream" if timing_bypassed_replay
                  else "micro-structure available" if micro_structure.get("available")
                  else str(micro_structure.get("reason") or "micro-structure unavailable")))

        rules = {name: rules[name] for name in RULE_ORDER}
        blocked_by: List[str] = [name for name in RULE_ORDER
                                 if rules[name]["mode"] == BLOCK and rules[name]["passed"] is False]
        should_enter = not blocked_by

        _diag["timing_bypassed_replay"] = timing_bypassed_replay
        _diag["timing_confidence"] = timing_confidence
        _diag["timing_ready"] = timing_ready
        _diag["micro_structure_available"] = bool(micro_structure.get("available", False))
        _diag["signal_count"] = signal_count

        # ---- H1 alignment (reporting and the star nudge only) ------------------
        if h1_aligned is not None and h1_bonus is not None:
            adjusted_probability = best_probability
        else:
            h1_aligned = False
            h1_bonus = 0
            adjusted_probability = best_probability
            if best_direction == "BUY" and h1_trend == "BULLISH":
                h1_aligned, h1_bonus = True, 10
                adjusted_probability = min(95, best_probability + 10)
            elif best_direction == "SELL" and h1_trend == "BEARISH":
                h1_aligned, h1_bonus = True, 10
                adjusted_probability = min(95, best_probability + 10)
            elif h1_trend == "NEUTRAL":
                h1_aligned, h1_bonus = True, 0
            else:
                h1_aligned, h1_bonus = False, -15
                adjusted_probability = max(5, best_probability - 15)

        result: Dict[str, Any] = {
            "should_enter": should_enter,
            "rules": rules,
            "blocked_by": blocked_by,
            "micro_structure": micro_structure,
            "timing_confidence": timing_confidence,
            "timing_ready": timing_ready,
            "timing_bypassed_replay": timing_bypassed_replay,
            "discount_info": discount_info,
            "confirmation": {"is_confirmed": is_confirmed, "type": confirmation_type,
                             "score": confirmation_score},
            "required_confirmation": required_confirmation,
            "strategy_setup": dict(setup) if setup else None,
            "h1_aligned": h1_aligned,
            "h1_bonus": h1_bonus,
            "adjusted_probability": adjusted_probability,
            "signals": {
                "momentum_burst": momentum_burst,
                "absorption": absorption,
                "volume_spike": volume_spike,
                "at_poi": at_poi,
                "signal_count": signal_count,
                "signal_type": signal_type,
            },
        }

        level = discount_info.get("discount_level", current_price) or current_price
        if should_enter:
            # Star rating from the real signal count; an unknown label gets the
            # LOWEST rating (the tables drifted apart), never the highest.
            if signal_type in self.star_ratings:
                entry_quality = signal_type
            else:
                entry_quality = "WEAK"
                logger.warning(
                    f"[ENTRY] {symbol}: signal_type '{signal_type}' has no entry in star_ratings -- "
                    f"defaulting to WEAK (1 star); add the missing tier.")
            star_rating, _ = self.star_ratings[entry_quality]
            if h1_bonus > 0 and star_rating < 5:
                star_rating = min(5, star_rating + 1)
            elif h1_bonus < 0 and star_rating > 1:
                star_rating = max(1, star_rating - 1)
            if setup.get("valid"):
                held = "STRATEGY_SETUP"
            elif rules["discount"]["passed"] and rules["confirmation"]["passed"]:
                held = "CONFIRMED_DISCOUNT"
            else:
                held = "RULES_PASSED"
            observed = [n for n in RULE_ORDER if rules[n]["mode"] == OBSERVE and rules[n]["passed"] is False]
            prob_txt = "n/a" if probability is None else f"{probability:.1f}%"
            trigger = (f"{setup.get('group')} {setup.get('title') or setup.get('name')}" if setup.get("valid")
                       else f"{confirmation_type} | {signal_type}")
            reason = f"✅ {direction} at {current_price:.5f} | {trigger} | Prob: {prob_txt}"
            if observed:
                reason += f" | observed, not blocking: {', '.join(observed)}"
            logger.info(f"[ENTRY] ✅ ENTRY SIGNAL: {symbol} {reason}")
            result.update({
                "entry_status": held,
                "final_decision": f"{direction} NOW",
                "simple_action": "ENTER NOW",
                "execution": "EXECUTE_MARKET_ORDER",
                "reason": reason,
                "star_rating": star_rating,
                "stars": "⭐" * star_rating if star_rating > 0 else "☆",
                "entry_quality": entry_quality,
            })
            return result

        first = blocked_by[0]
        also = f" | also blocked by: {', '.join(blocked_by[1:])}" if len(blocked_by) > 1 else ""
        if first == "zone":
            text = ("SKIP - INVALID ZONE", "HOLD", "DO_NOTHING", zone_reason, 1, "NO")
        elif first == "signals":
            text = ("DO NOTHING", "HOLD", "DO_NOTHING",
                    f"No entry signals (signal_count={signal_count}, need {self.min_signals})", 1, "NO")
        elif first == "probability":
            above = probability is not None and probability > ceiling
            text = ("SKIP - PROBABILITY ABOVE CEILING" if above else "SKIP - PROBABILITY TOO LOW",
                    "HOLD", "DO_NOTHING", f"Probability {probability_why}", 1, "NO")
        elif first == "setup":
            text = ("WAIT - NO STRATEGY SETUP", "WAIT", "SET_PRICE_ALERT",
                    f"{setup.get('group')} has no valid trade setup now: {setup.get('why')}", 2, "NO_SETUP")
        elif first == "discount":
            result["target_price"] = level
            result["distance_to_target_pips"] = discount_info.get("distance_pips", 0)
            text = ("WAIT - PRICE TO REACH DISCOUNT", "WAIT", "SET_PRICE_ALERT",
                    f"📊 {signal_type} detected | Wait for price to reach {level:.5f} "
                    f"({discount_info.get('distance_pips', 0):.1f} pips away)", 2, "POTENTIAL")
        elif first == "discount_quality":
            text = ("SKIP - POOR DISCOUNT", "HOLD", "DO_NOTHING",
                    f"Discount quality poor: {rules['discount_quality']['why']} "
                    f"(score={discount_info.get('discount_score', 0)})", 2, "POOR_DISCOUNT")
        elif first == "confirmation":
            where = f"At discount ({level:.5f}) | " if is_at_discount else ""
            text = ("WAIT - NEED CONFIRMATION", "WAIT", "SET_PRICE_ALERT",
                    f"🎯 {where}Waiting for confirmation: {required_confirmation or 'BULLISH_CLOSE'}",
                    3, "AWAITING_CONFIRMATION")
        elif first == "momentum":
            text = ("WAIT - WEAK MOMENTUM", "WAIT", "SET_PRICE_ALERT",
                    f"Momentum {rules['momentum']['value']} below {MOMENTUM_STRENGTH_MIN:g}", 2, "WEAK_MOMENTUM")
        else:  # timing
            text = ("WAIT - POOR TIMING", "WAIT", "SET_PRICE_ALERT",
                    f"🎯 {confirmation_type} but timing confidence low "
                    f"({timing_confidence}% < {self.min_timing_confidence}%)", 3, "TIMING_ISSUE")
        final_decision, simple_action, execution, reason, star_rating, entry_quality = text
        result.update({
            "entry_status": RULE_STATUS[first],
            "final_decision": final_decision,
            "simple_action": simple_action,
            "execution": execution,
            "reason": reason + also,
            "star_rating": star_rating,
            "stars": "⭐" * star_rating if star_rating > 1 else "☆",
            "entry_quality": entry_quality,
        })
        return result


# ============================================================
# GLOBAL INSTANCE (Thread-safe)
# ============================================================

_entry_engine = None
_entry_engine_lock = Lock()


def get_entry_engine(config: Dict[str, Any] = None) -> EntryEngine:
    """Get or create the global entry engine instance (thread-safe)."""
    global _entry_engine
    with _entry_engine_lock:
        if _entry_engine is None:
            _entry_engine = EntryEngine(config)
        return _entry_engine


def reset_entry_engine(config: Dict[str, Any] = None):
    """Reset the global entry engine instance (useful for testing)."""
    global _entry_engine
    with _entry_engine_lock:
        _entry_engine = EntryEngine(config)
        logger.info("[ENTRY] Engine reset")


def analyze_entry(
    symbol: str,
    best_direction: str,
    current_price: float,
    zone_level: float,
    zone_type: str,
    zone_grade: str,
    candle_data: Dict,
    volume_spike: bool,
    at_poi: bool,
    best_probability: float,
    pip_size: float,
    h1_trend: str = "NEUTRAL",
    h1_aligned: Optional[bool] = None,
    h1_bonus: Optional[int] = None,
    atr_pips: float = None,
    is_replay: bool = False,
    probability_floor: Optional[float] = None,
    strategy_setup: Optional[Mapping[str, Any]] = None,
    momentum_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    The entry decision from the shared engine (EntryEngine.get_entry_decision).

    probability_floor: the entry floor for the scale best_probability is on.
    is_replay: True only when the caller replays historical bars and has no
    real tick stream to confirm timing against.
    """
    engine = get_entry_engine()
    return engine.get_entry_decision(
        symbol=symbol,
        best_direction=best_direction,
        current_price=current_price,
        zone_level=zone_level,
        zone_type=zone_type,
        zone_grade=zone_grade,
        candle_data=candle_data,
        volume_spike=volume_spike,
        at_poi=at_poi,
        best_probability=best_probability,
        pip_size=pip_size,
        h1_trend=h1_trend,
        h1_aligned=h1_aligned,
        h1_bonus=h1_bonus,
        atr_pips=atr_pips,
        is_replay=is_replay,
        probability_floor=probability_floor,
        strategy_setup=strategy_setup,
        momentum_score=momentum_score,
    )


def get_entry_stats() -> Dict[str, Any]:
    """Get entry engine statistics (for debugging)."""
    engine = get_entry_engine()
    return {
        "rule_order": list(RULE_ORDER),
        "rule_modes": dict(engine.rule_modes),
        "min_signals": engine.min_signals,
        "wick_rejection_ratio": engine.wick_rejection_ratio,
        "min_timing_confidence": engine.min_timing_confidence,
        "min_zone_grade": engine.min_zone_grade,
        "min_discount_score": engine.min_discount_score,
        "min_probability_for_entry": engine.min_probability_for_entry,
        "max_probability_for_entry": MAX_PROBABILITY_FOR_ENTRY,
        "valid_zone_grades": engine.valid_zone_grades,
        "grade_priority": engine.grade_priority,
        "tradable_grades": engine.tradable_grades,
        "timing_weights": engine.timing_weights,
        "signal_thresholds": engine.signal_thresholds
    }
