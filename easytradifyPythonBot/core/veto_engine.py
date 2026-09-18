# core/veto_engine.py
"""
VETO ENGINE - All Trade Prevention Rules

Centralized veto checking for:
- Session (market closed, weekend, holiday)
- News (high impact events)
- Market conditions (ADX, volatility)
- Trend alignment
- Technical filters (EMA, divergence, wicks, volume, spread, candle)

FIXES APPLIED:
- Fixed modify_sl logic in session veto
- Added proper news veto function handling with fallback
- Fixed candle_too_young logic (reversed condition)
- Added instrument-aware thresholds
- Made trend checking more flexible (BULLISH allows BUY)
- Added holiday and weekend veto checks
- Added cooldown mechanism for repeated vetoes
- Added health check method
- Made thresholds configurable via __init__
- FIXED CANDLE VETO: Now only vetoes when signals are weak
  - Strong signals (≥2, volume spike, absorption, prob≥75) override the veto
  - Only veto at < 10% even with strong signals
  - No veto if entry already triggered
- FIXED UNKNOWN VETO REASON: All vetoes now return descriptive reasons
- FIXED CHECK_ALL_VETOS: Added try/except to prevent crashes, fails open
- Added default reason for empty veto reason
- FIXED VOLUME VETO: Now trend-aware (strong trends allow lower volume)
- FIXED WICK REVERSAL: Lenient ratio for small candles (< 1 pip body)
"""

from typing import Dict, Any, Tuple, Optional, Callable
import logging
import time
from threading import Lock

from core.asset_analysis_config import TRADE_PROBABILITY_MINIMUM
from collections import deque

# Import config functions for trend-aware thresholds
# ✅ FIXED: this module was the ONLY one in core/ importing from
# core.config. The other nine all import core.asset_analysis_config.
# Those two files are parallel copies of the same settings -- 145 shared
# constants, 13 of which have drifted apart, and 19 shared functions, 6
# with differing bodies.
#
# Most of that split was inert here: of the nine names imported below,
# the seven constants are byte-identical in both files and
# get_wick_reversal_ratio's body matches. ONE did not:
#
#   get_volume_threshold() differs. asset_analysis_config's version
#   strips the "STRONG_" prefix before its membership check; this file's
#   copy matches "BULLISH"/"BEARISH" exactly. A trend labelled
#   STRONG_BULLISH by divergence confirmation rather than by a high ADX
#   therefore missed BOTH branches and fell through to WEAK_TREND (0.5)
#   instead of MODERATE (0.4) -- which asset_analysis_config's own
#   docstring documents as a bug it fixed. veto_engine was running the
#   unfixed copy, and veto_engine is what decides the low-volume veto.
#
#   Concretely: STRONG_-labelled trend with ADX < 50 needed volume >= 0.5
#   rather than >= 0.4 to clear the veto.
#
# Repointed at asset_analysis_config so this module reads the same
# settings as the rest of the system. After this change core.config has
# zero importers in core/.
from core.asset_analysis_config import (
    get_volume_threshold,
    get_wick_reversal_ratio,
    ADX_STRONG_TREND_THRESHOLD,
    VOLUME_THRESHOLD_STRONG_TREND,
    VOLUME_THRESHOLD_MODERATE_TREND,
    VOLUME_THRESHOLD_WEAK_TREND,
    WICK_REVERSAL_RATIO_NORMAL,
    WICK_REVERSAL_RATIO_SMALL,
    WICK_SMALL_CANDLE_BODY_THRESHOLD,
    DISABLED_VETOS,
)

logger = logging.getLogger(__name__)


class VetoEngine:
    """
    Centralized veto checking for trade entries.
    
    Each veto check returns:
    - veto_triggered: bool
    - veto_reason: str
    - can_modify: bool (whether SL/TP can be adjusted)
    - modified_sl_pips: Optional[float]
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize veto engine with optional custom configuration.
        
        Args:
            config: Optional configuration dictionary with keys:
                - min_adx_for_trend: Minimum ADX for trend (default 25)
                - extreme_volatility_threshold: Extreme ATR threshold (default 70)
                - min_volume_ratio: Minimum volume ratio (default 0.5) - DEPRECATED
                - min_candle_progress: Minimum candle progress % (default 75) - DEPRECATED
                - candle_young_threshold_weak: Threshold for weak signals (default 50)
                - candle_young_threshold_strong: Threshold for strong signals (default 10)
                - wick_rejection_ratio: Wick to body ratio for rejection (default 3)
                - rsi_oversold_for_buy: RSI oversold threshold (default 30)
                - rsi_overbought_for_sell: RSI overbought threshold (default 70)
                - divergence_extreme_score: Extreme divergence score (default 80)
                - cooldown_seconds: Cooldown after veto (default 60)
        """
        # Veto thresholds with config overrides
        # ✅ ADDED (Phase 2, defect D-05): canonical veto record.
        #
        # There were three veto truths in the system: breakdown_*['veto']
        # used for direction tie-breaking, this engine's check_all_vetos()
        # which actually decides, and asset_analysis._veto_check_safe()
        # which RE-INVOKED the engine at reporting time to fill the output
        # block. The reported flags were therefore a second evaluation, not
        # a record of the first.
        #
        # The divergence is structural, not incidental: check_all_vetos()
        # SHORT-CIRCUITS on the first veto that fires, so later checks never
        # run. Re-invoking them afterwards evaluates checks the decision
        # never made, against state that may have moved. That is exactly how
        # choppy_market/extreme_volatility/wick_reversal/low_volume ended up
        # disagreeing with vetos.triggered on live bars.
        #
        # Each check now records itself as it runs. A check that never ran
        # is recorded as not-evaluated, which is a DIFFERENT fact from a
        # check that ran and declined to veto -- the old reporting path
        # could not distinguish them.
        self._veto_ledger: Dict[str, Dict[str, Any]] = {}
        self._veto_ledger_lock = Lock()

        # ✅ A CHRONOLOGICAL STREAM, alongside the per-symbol ledger above.
        #
        # The ledger answers "what did the last decision on EURUSD look like?"
        # -- it is keyed by symbol and each new decision overwrites the prior
        # one. That is the right shape for reporting a single analysis, and the
        # wrong shape for the question actually being asked most often here,
        # which is "why is nothing trading?".
        #
        # Answering that needs the decisions ACROSS symbols and over time: the
        # same check firing on twelve symbols in a row is the signal, and the
        # ledger cannot show it because symbol twelve has overwritten nothing
        # relevant -- each entry is a separate key. So every recorded check is
        # also appended here, in order, with a timestamp.
        #
        # Bounded: a monitor left running for hours evaluates a check per
        # symbol per scan cycle, which is unbounded growth in a process that is
        # meant to stay up for days. 400 is a few minutes of history, which is
        # the window anyone actually looks at.
        self._veto_stream: deque = deque(maxlen=400)
        cfg = config or {}

        # ============================================================
        # SELECTIVELY DISABLING A VETO  (measured, not guessed)
        # ============================================================
        # `disabled_vetos` names checks that still RUN and still RECORD
        # themselves, but no longer block the trade. Running them anyway
        # is the point: the ledger keeps saying what each check would
        # have done, so a disabled veto stays measurable and the decision
        # to re-enable it is made on evidence rather than on memory.
        #
        # This exists because V3/V4/V5 above were disabled by commenting
        # them out -- which also deleted their measurement, so nobody
        # could tell afterwards whether that had helped or hurt. A flag
        # that keeps the instrumentation is strictly better than a
        # comment that removes it.
        #
        # DEFAULT is core/asset_analysis_config.DISABLED_VETOS (candle_too_young
        # since 2026-09-17: every reading is taken on closed bars, so the age
        # of the forming bar judges nothing -- see the note there). Pass
        # disabled_vetos=() to make every check block.
        #
        # WHAT THE REPLAY SAYS (30 days, M15, 4 symbols, measured on the
        # trades the calibrated family filter selects -- see
        # core/phase_report.py):
        #
        #   low_volume   blocks 62 trades that won 45.2% at +0.563R,
        #                costing +12.0R on the tune window and +22.9R on
        #                the confirm window. Positive on BOTH windows,
        #                which is the bar everything else here failed.
        #                This is the one check with a clear case to drop.
        #
        #   extreme_volatility and rsi_divergence_opposing HELP on both
        #                windows (they block net losers). Keep them.
        #
        #   choppy_market, against_trend, h1_conflict flip sign between
        #                windows -- no stable evidence either way, so no
        #                change is justified on this data.
        #
        # news_veto, session/weekend/holiday, high_spread and
        # extreme_volatility are TAIL PROTECTION. A bar replay cannot
        # price a news gap, a requote or a weekend hole, so their value
        # is structurally invisible here and a weak backtest showing is
        # not evidence against them. Do not disable them on this data.
        self.disabled_vetos = set(cfg.get('disabled_vetos', DISABLED_VETOS) or ())
        # "invert" by default -- the only configuration of the ADX rule that
        # is positive on the recorded history. See check_choppy_market for the
        # measurement and the caveat; set "block" to restore the original.
        # ⚠️ REVERTED TO "block" -- the original behaviour.
        #
        # This defaulted to "invert" on a measurement taken over ALL 215
        # trades: choppy-vetoed setups returned +0.019R at 48.3% win against
        # -0.089R at 37.1% for the ones the veto allowed, and the combined
        # rule change read +0.2623R per trade, 37.1% -> 50.7% win rate.
        #
        # Split chronologically -- fit on the earlier 70%, scored on the
        # later 30% -- it inverts completely:
        #
        #   rule set                     TRAIN        TEST     test win
        #   original rules             +0.0455R    -0.0348R      43.6%
        #   invert choppy              -0.0708R    -0.1388R      30.8%
        #   + enable against_ema       -0.0579R    -0.3580R      28.6%
        #   + enable h1_conflict       -0.0356R    -0.3789R      35.7%
        #
        # The original rules are the BEST on held-out data and the "fix" is
        # the worst. The +0.2623R was selection: three rules chosen on the
        # same 215 trades they were then measured on, with n falling 97 -> 71
        # while the number improved. That is the exact failure this codebase
        # has documented three times (rvam train +0.318R -> test -0.861R),
        # and it was reproduced here by the person writing the warning.
        #
        # Both flags stay, so the hypothesis can be run forward under
        # ai/rule_experiments.py where a control decides it. Neither is a
        # default until it has survived data it was not fitted on.
        # DATA-COLLECTION MODE (2026-09-10): default 'block' -> 'off'.
        #
        # Measured over a full session: the choppy veto is the single largest
        # blocker, still firing 95 times in the most recent window even after
        # the ADX floor was cut 25 -> 15 -> 10. Trade count is the binding
        # constraint on this research, and this rule spends most of its budget
        # rejecting the RANGING regime the edge study found performs better
        # (48.3% / +0.0245R vs TRENDING 36.8% / -0.0983R).
        #
        # HONEST COUNTER-EVIDENCE, because it exists: the held-out comparison
        # in tests/test_rule_experiments.py found the ORIGINAL rules (this veto
        # blocking) beat the loosened set out of sample -- +0.0455R train /
        # -0.0348R test against -0.0356R / -0.3789R. That is a real argument
        # for 'block', and it is why this is a deliberate data-collection
        # setting rather than a correction. Restore 'block' before drawing any
        # conclusion about expectancy from trades gathered under it.
        self.choppy_market_mode = str(
            cfg.get('choppy_market_mode') or 'off').lower()
        self.enable_trend_vetoes = bool(
            cfg.get('enable_trend_vetoes', False))
        
        # DATA-COLLECTION MODE (2026-09-10): 25 -> 15.
        # Largest single veto (1299 hits); ADX when vetoed had median 18.8,
        # p75 22.0, max 24.9 -- i.e. it was rejecting the whole 15-25 band.
        # Note the edge research found RANGING outperforms TRENDING
        # (48.3% / +0.0245R vs 36.8% / -0.0983R), so an ADX floor was
        # vetoing the regime that measured better.
        # NOTE: the choppy-market veto does NOT read this -- it uses
        # instrument_adx_thresholds above. Kept in step so the two cannot
        # disagree, but changing this alone changes nothing.
        self.min_adx_for_trend = cfg.get('min_adx_for_trend', 15)
        self.extreme_volatility_threshold = cfg.get('extreme_volatility_threshold', 70.0)
        
        # Volume threshold - kept for backward compatibility, but now overridden by trend-aware logic
        self.min_volume_ratio = cfg.get('min_volume_ratio', 0.5)
        
        # Candle veto thresholds - FIXED: more lenient
        # DATA-COLLECTION MODE (2026-09-10): 50/10 -> 15/5.
        # "Candle too young" was still firing after the other gates opened.
        # It rejects a setup for arriving early in the candle's formation --
        # a timing preference, not a claim about the setup itself -- and on M1
        # a 50% floor discards the first thirty seconds of every minute.
        self.candle_young_threshold_weak = cfg.get('candle_young_threshold_weak', 15)
        self.candle_young_threshold_strong = cfg.get('candle_young_threshold_strong', 5)
        self.min_candle_progress = cfg.get('min_candle_progress', 75)  # Legacy, kept for compatibility
        
        # Wick reversal ratio - can be overridden by config
        # 3 -> 5: a HIGHER ratio is a LOOSER veto (the wick must be a larger
        # multiple of the body before the bar counts as a rejection), so this
        # fires less often. Only 1 hit in the last window, so this is a small
        # lever included for completeness.
        self.wick_rejection_ratio = cfg.get('wick_rejection_ratio', 5)
        
        # RSI divergence thresholds
        self.rsi_oversold_for_buy = cfg.get('rsi_oversold_for_buy', 30)
        self.rsi_overbought_for_sell = cfg.get('rsi_overbought_for_sell', 70)
        self.divergence_extreme_score = cfg.get('divergence_extreme_score', 80)
        
        # Cooldown mechanism
        self.cooldown_seconds = cfg.get('cooldown_seconds', 60)
        self._last_veto_time = 0
        self._last_veto_symbol = None
        self._veto_count = 0
        self._lock = Lock()
        
        # Instrument-specific ADX thresholds (can be overridden)
        # DATA-COLLECTION MODE (2026-09-10): lowered from 20/22/25.
        #
        # THIS is the table the choppy-market veto actually reads --
        # _get_instrument_adx_threshold(), not self.min_adx_for_trend below.
        # Lowering min_adx_for_trend alone was a no-op: the veto kept firing
        # at "ADX=20.1 < 25" for eight hours after that change, because these
        # two settings look interchangeable and are not.
        #
        # The edge research found RANGING outperforms TRENDING (48.3% /
        # +0.0245R vs 36.8% / -0.0983R), so an ADX floor rejects the regime
        # that measured better. Measured ADX on vetoed setups: median 18.8,
        # p75 22.0 -- i.e. the whole 15-25 band was being discarded.
        # Lowered again 2026-09-10: 314 vetoes still fired at ADX < 15 over a
        # full session with zero trades taken. The edge research finds RANGING
        # outperforms TRENDING (48.3% / +0.0245R vs 36.8% / -0.0983R), so an
        # ADX floor is rejecting the regime that measured better -- there is no
        # evidence here that a trend filter helps, and it is currently the
        # single largest veto.
        self.instrument_adx_thresholds = {
            "XAUUSD": 8,
            "XAGUSD": 9,
            "DEFAULT": 10
        }
        
        # Instrument-specific volatility thresholds
        self.instrument_volatility_thresholds = {
            "XAUUSD": 100.0,  # Gold can handle higher volatility
            "XAGUSD": 80.0,
            "DEFAULT": 70.0
        }
        
        logger.info(f"VetoEngine initialized with cooldown={self.cooldown_seconds}s")
        logger.info(f"  Candle veto: weak_threshold={self.candle_young_threshold_weak}%, strong_threshold={self.candle_young_threshold_strong}%")
        logger.info(f"  Volume veto: strong_trend={VOLUME_THRESHOLD_STRONG_TREND}, moderate={VOLUME_THRESHOLD_MODERATE_TREND}, weak={VOLUME_THRESHOLD_WEAK_TREND}")
    
    def _get_instrument_adx_threshold(self, symbol: str) -> int:
        """Get instrument-appropriate ADX threshold."""
        symbol_upper = symbol.upper()
        for key in self.instrument_adx_thresholds:
            if key in symbol_upper:
                return self.instrument_adx_thresholds[key]
        return self.instrument_adx_thresholds["DEFAULT"]
    
    def _get_instrument_volatility_threshold(self, symbol: str) -> float:
        """Get instrument-appropriate volatility threshold."""
        symbol_upper = symbol.upper()
        for key in self.instrument_volatility_thresholds:
            if key in symbol_upper:
                return self.instrument_volatility_thresholds[key]
        return self.instrument_volatility_thresholds["DEFAULT"]
    
    def _is_in_cooldown(self, symbol: str) -> Tuple[bool, int]:
        """Check if we're in cooldown period after a veto."""
        with self._lock:
            if self._last_veto_symbol == symbol:
                elapsed = time.time() - self._last_veto_time
                if elapsed < self.cooldown_seconds:
                    return True, int(self.cooldown_seconds - elapsed)
        return False, 0
    
    def _record_veto(self, symbol: str):
        """Record a veto for cooldown tracking."""
        with self._lock:
            self._last_veto_time = time.time()
            self._last_veto_symbol = symbol
            self._veto_count += 1
    
    def check_session_veto(
        self,
        is_already_in_trade: bool,
        session_result: Dict
    ) -> Tuple[bool, str, bool, Optional[float]]:
        """
        Check session veto (market closed, off hours).
        
        FIXED: Properly handles modify_sl from session_result.
        """
        if not is_already_in_trade:
            if session_result.get("veto_triggered", False):
                veto_reason = session_result.get("veto_reason", "Session veto")
                modify_sl = session_result.get("modify_sl", False)
                new_sl_pips = session_result.get("new_sl_pips")
                
                # Record veto for cooldown
                symbol = session_result.get("symbol", "UNKNOWN")
                self._record_veto(symbol)
                
                return True, veto_reason, modify_sl, new_sl_pips
        
        return False, "", False, None
    
    def check_news_veto(
        self,
        symbol: str,
        best_direction: str,
        news_veto_func: Optional[Callable],
        is_already_in_trade: bool = False
    ) -> Tuple[bool, str]:
        """
        Check news veto for new entries.
        
        FIXED: Handles None news_veto_func gracefully.
        """
        if not is_already_in_trade and news_veto_func is not None:
            try:
                news_veto, news_reason = news_veto_func(symbol, best_direction, "NORMAL")
                if news_veto:
                    # the cooldown starts in check_all_vetos, and only when
                    # this veto is active (it is record-only by default)
                    return True, news_reason
            except Exception as e:
                logger.warning(f"[VETO] News veto function failed: {e}")
                # Fail open - allow trade if news check fails
                return False, ""
        return False, ""
    
    def check_weekend_veto(
        self,
        symbol: str,
        session_manager,
        is_already_in_trade: bool = False
    ) -> Tuple[bool, str, bool, Optional[float]]:
        """
        Check weekend veto for new entries.
        
        Returns:
            (veto_triggered, reason, modify_sl, new_sl_pips)
        """
        if not is_already_in_trade and session_manager:
            try:
                veto, reason, modifications = session_manager.should_veto_weekend(
                    symbol, 0, 0  # No expected gain/SL for veto check
                )
                if veto:
                    self._record_veto(symbol)
                    modify_sl = modifications.get("modify_sl", False) if modifications else False
                    new_sl_pips = modifications.get("new_sl_pips") if modifications else None
                    return True, reason, modify_sl, new_sl_pips
            except Exception as e:
                logger.warning(f"[VETO] Weekend check failed: {e}")
        return False, "", False, None
    
    def check_holiday_veto(
        self,
        symbol: str,
        session_manager,
        is_already_in_trade: bool = False
    ) -> Tuple[bool, str, bool, Optional[float]]:
        """
        Check holiday veto for new entries.
        
        Returns:
            (veto_triggered, reason, modify_sl, new_sl_pips)
        """
        if not is_already_in_trade and session_manager:
            try:
                veto, reason, modifications = session_manager.should_veto_holiday(
                    symbol, 0, 0
                )
                if veto:
                    self._record_veto(symbol)
                    modify_sl = modifications.get("modify_sl", False) if modifications else False
                    new_sl_pips = modifications.get("new_sl_pips") if modifications else None
                    return True, reason, modify_sl, new_sl_pips
            except Exception as e:
                logger.warning(f"[VETO] Holiday check failed: {e}")
        return False, "", False, None
    
    # How the ADX rule behaves. Set via config `choppy_market_mode`.
    #
    #   "block"   veto when ADX is LOW  -- the original rule
    #   "off"     never veto on ADX
    #   "invert"  veto when ADX is HIGH -- take the low-ADX setups instead
    #
    # MEASURED on 215 real trades, analysis recomputed from bars at each
    # entry (ai/history_enrichment.py), R denominated by the submitted stop:
    #
    #   block   n= 97  mean -0.0890R  win 37.1%  total  -8.6R   <- original
    #   off     n=215  mean -0.0298R  win 43.3%  total  -6.4R
    #   invert  n=118  mean +0.0189R  win 48.3%  total  +2.2R
    #
    # The rule was backwards: the setups it blocked were the only profitable
    # group in the account, and the ones it approved lost money on both
    # measures. Inverting is the only configuration of this rule that is
    # positive on the recorded history.
    #
    # THE EVIDENCE IS NOT CONCLUSIVE. The split is post-hoc on a single
    # sample, p=0.49, and 215 trades cannot resolve a 0.1R effect -- roughly
    # 470 would be needed. It is adopted because the original rule has no
    # demonstrated value in either direction and this configuration is the
    # only one that is not losing, not because the finding is proven.
    # `ai/rule_experiments.py` runs it forward under governance; reverting is
    # `choppy_market_mode: "block"`.
    CHOPPY_MODES = ("block", "off", "invert")

    def check_choppy_market(self, adx_val: float, symbol: str = "DEFAULT") -> Tuple[bool, str]:
        """ADX regime veto. See CHOPPY_MODES for why the default is 'invert'."""
        mode = getattr(self, "choppy_market_mode", "invert")
        if mode not in self.CHOPPY_MODES:
            mode = "invert"

        if mode == "off":
            return False, ""

        min_adx = self._get_instrument_adx_threshold(symbol)
        if mode == "invert":
            # Veto the TRENDING setups, which is where the losses were.
            if adx_val >= min_adx:
                return True, (f"Trending market vetoed by inverted ADX rule "
                              f"(ADX={adx_val:.1f} >= {min_adx})")
            return False, ""

        if adx_val < min_adx:
            return True, f"Choppy market (ADX={adx_val:.1f} < {min_adx})"
        return False, ""
    
    def check_extreme_volatility(self, atr_pips: float, symbol: str = "DEFAULT",
                                 atr_band: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """Veto if volatility is extreme FOR THIS INSTRUMENT.

        ✅ FIXED 2026-09-15. The limit used to be a fixed pip count (XAUUSD 100,
        XAGUSD 80, everything else 70). Gold's ordinary M1 ATR is ~210 pips at a
        0.01 pip, so the veto fired on 104 of 110 recent gold bars -- and on
        110/110 for US30 and BTCUSD. None of the 111 stored trades were gold:
        the instrument was blocked, not volatile.

        When the analysis supplies the instrument's own ATR percentile band
        (volatility_protection.atr_percentile_band, built from its last 100
        bars) and that band is adaptive, "extreme" is the band's own extreme
        level (98th percentile). On the same 110 bars that fired 0 times on
        gold, silver, US30 and BTCUSD. When no usable band exists (FX majors,
        whose distribution is too narrow), the static table still applies --
        it never fired on FX, so FX is unchanged.
        """
        band_extreme = None
        if isinstance(atr_band, dict) and atr_band.get("adaptive"):
            try:
                band_extreme = float(atr_band.get("extreme"))
            except (TypeError, ValueError):
                band_extreme = None
        if band_extreme and band_extreme > 0:
            if atr_pips > band_extreme:
                return True, (f"Extreme volatility (ATR={atr_pips:.1f}p > {band_extreme:.1f}p, "
                              f"this instrument's own 98th percentile)")
            return False, ""
        max_atr = self._get_instrument_volatility_threshold(symbol)
        if atr_pips > max_atr:
            return True, f"Extreme volatility (ATR={atr_pips:.1f}p > {max_atr}p)"
        return False, ""
    
    # def check_against_trend(self, best_direction: str, trend: str) -> Tuple[bool, str]:
    #     """
    #     Veto if trading against trend.
        
    #     FIXED: More flexible - allows BUY in BULLISH (not just STRONG_BULLISH)
    #     """
    #     if best_direction == "BUY":
    #         if trend not in ["STRONG_BULLISH", "BULLISH"]:
    #             return True, f"Buying in {trend} trend"
    #     elif best_direction == "SELL":
    #         if trend not in ["STRONG_BEARISH", "BEARISH"]:
    #             return True, f"Selling in {trend} trend"
    #     return False, ""
    
    # RE-ENABLED on measured evidence. Both of these were computed, reported
    # as PASS/FAIL gates, and unable to stop a trade -- and both of them work.
    #
    # Measured on 215 real trades with the analysis recomputed at each entry
    # (ai/history_enrichment.py):
    #
    #            fires on          allows            what it blocks
    #   ema      37 @ -0.2148R     178 @ +0.0087R    losers
    #   h1       39 @ -0.1636R     176 @ -0.0001R    losers
    #
    # So the two vetoes that correctly identified losing setups were inert,
    # while `choppy_market` -- which blocked the only profitable group -- was
    # the one actually stopping trades. The rule base was doing the opposite
    # of its job in both directions at once.
    #
    # Gated by `enable_trend_vetoes`, which defaults to FALSE -- so
    # against_ema and h1_conflict are inert: check_against_ema() and
    # check_h1_conflict() still return a verdict when called directly, but
    # the veto chain at _run_vetoes() only consults them when the flag is on,
    # so neither has ever stopped a live trade. (This comment previously said
    # "default True", which read as though they were active.)
    def check_against_ema(
        self,
        best_direction: str,
        current_price: float,
        ema_200: float
    ) -> Tuple[bool, str]:
        """Veto if trading against the 200 EMA."""
        if not ema_200 or not current_price:
            return False, ""
        if best_direction == "BUY" and current_price < ema_200:
            return True, f"Buying below 200 EMA ({current_price:.5f} < {ema_200:.5f})"
        elif best_direction == "SELL" and current_price > ema_200:
            return True, f"Selling above 200 EMA ({current_price:.5f} > {ema_200:.5f})"
        return False, ""

    def check_h1_conflict(self, best_direction: str, h1_trend: str) -> Tuple[bool, str]:
        """Veto if the H1 timeframe opposes the M1 direction."""
        if not h1_trend or h1_trend == "NEUTRAL":
            return False, ""
        if best_direction == "BUY" and h1_trend in ["STRONG_BEARISH", "BEARISH"]:
            return True, f"H1 {h1_trend} opposes M1 BUY"
        elif best_direction == "SELL" and h1_trend in ["STRONG_BULLISH", "BULLISH"]:
            return True, f"H1 {h1_trend} opposes M1 SELL"
        return False, ""
    
    def check_rsi_divergence_opposing(
        self,
        best_direction: str,
        rsi_div_score: float,
        rsi_div_rsi: float
    ) -> Tuple[bool, str]:
        """Veto if the M1 RSI divergence (core/rsi_divergence_setup.py) opposes the trade."""
        if best_direction == "BUY" and rsi_div_score < 0:
            if rsi_div_rsi < self.rsi_oversold_for_buy or abs(rsi_div_score) > self.divergence_extreme_score:
                return True, f"M1 RSI divergence opposing BUY (score={rsi_div_score}, RSI={rsi_div_rsi:.1f})"
        elif best_direction == "SELL" and rsi_div_score > 0:
            if rsi_div_rsi > self.rsi_overbought_for_sell or rsi_div_score > self.divergence_extreme_score:
                return True, f"M1 RSI divergence opposing SELL (score={rsi_div_score}, RSI={rsi_div_rsi:.1f})"
        return False, ""
    
    def check_wick_reversal(
        self,
        best_direction: str,
        upper_wick_pips: float,
        lower_wick_pips: float,
        body_pips: float
    ) -> Tuple[bool, str]:
        """
        Veto if extreme wick reversal at the level.
        
        FIXED: Uses lenient ratio for small candles (< 1 pip body).
        Uses config function get_wick_reversal_ratio() for dynamic threshold.
        """
        if body_pips <= 0:
            return False, ""
        
        # Get size-appropriate wick reversal ratio from config
        effective_ratio = get_wick_reversal_ratio(body_pips)
        
        if best_direction == "BUY" and upper_wick_pips > body_pips * effective_ratio:
            return True, f"Wick reversal (upper wick {upper_wick_pips:.1f}p > {body_pips * effective_ratio:.1f}p)"
        elif best_direction == "SELL" and lower_wick_pips > body_pips * effective_ratio:
            return True, f"Wick reversal (lower wick {lower_wick_pips:.1f}p > {body_pips * effective_ratio:.1f}p)"
        return False, ""
    
    def _veto_active(self, name: str, unit_id: Any = None) -> bool:
        """
        Is this veto allowed to BLOCK, as opposed to merely report?

        A disabled veto has already run and already recorded its verdict
        by the time this is consulted -- only the block is suppressed.

        That separation is also what makes a rule experiment possible here:
        both arms compute and record the identical verdict, and differ in
        exactly one respect. When an experiment is running and this candidate
        is in its test arm, the block is suppressed and everything else is
        unchanged.

        Fails safe in every direction: no experiment, no unit id, an
        unrecognised veto, or any error at all leaves the veto ACTIVE, which
        is today's behaviour. The failure that matters is suppressing a veto
        by accident, never keeping one.
        """
        if name in self.disabled_vetos:
            return False
        try:
            from ai.rule_experiments import should_suppress

            if unit_id is not None and should_suppress(name, unit_id):
                return False
        except Exception:
            pass
        return True

    def check_low_volume(
        self,
        volume_ratio: float,
        trend: str = "NEUTRAL",
        adx: float = 0
    ) -> Tuple[bool, str]:
        """
        Veto if volume is too low - trend-aware.
        
        FIXED: Uses trend-aware threshold from config.
        - Strong trends (ADX > 50): threshold = 0.3
        - Moderate trends (BULLISH/BEARISH): threshold = 0.4
        - Weak trends (NEUTRAL): threshold = 0.5
        """
        # Get trend-aware threshold from config
        threshold = get_volume_threshold(trend, adx)
        
        if volume_ratio < threshold:
            return True, f"Low volume (ratio={volume_ratio:.2f} < {threshold})"
        return False, ""
    
    def check_high_spread(
        self,
        spread_valid: bool,
        spread_pips: float,
        max_allowed_spread: int
    ) -> Tuple[bool, str]:
        """Veto if spread is too high."""
        if not spread_valid:
            return True, f"High spread ({spread_pips:.1f}p > {max_allowed_spread})"
        return False, ""
    
    def check_candle_too_young(
        self,
        entry_triggered: bool,
        candle_progress_pct: float,
        signal_count: int = 0,
        probability: float = 0,
        volume_spike: bool = False,
        absorption: bool = False
    ) -> Tuple[bool, str]:
        """
        Check if candle is too young for entry.
        
        FIXED: Only veto if:
        1. Entry is NOT already triggered
        2. Candle is very young
        3. AND we don't have strong signals to override
        
        This prevents the veto from killing good early entries.
        
        Thresholds:
        - Strong signals (≥2, volume spike, absorption, prob≥75): can enter at 10%
        - Weak signals: need 50% candle progress
        """
        # If entry is already triggered, never veto
        if entry_triggered:
            return False, ""
        
        # If candle is old enough (>= 50%), no veto
        if candle_progress_pct >= self.candle_young_threshold_weak:
            return False, ""
        
        # ============================================================
        # SITUATIONAL VETO - Only veto young candles when conditions are weak
        # ============================================================
        
        # Check for strong signals that can override the veto
        strong_signals = (
            signal_count >= 2 or
            volume_spike or
            absorption or
            probability >= TRADE_PROBABILITY_MINIMUM   # re-centred scale (was a literal 75)
        )
        
        # If we have strong signals, allow early entry
        if strong_signals:
            # Even with strong signals, veto if candle is EXTREMELY young
            if candle_progress_pct < self.candle_young_threshold_strong:
                return True, f"Candle extremely young ({candle_progress_pct:.0f}% < {self.candle_young_threshold_strong}%)"
            return False, ""  # Allow entry with strong signals
        
        # For weak signals, veto if candle is young
        if candle_progress_pct < self.candle_young_threshold_weak:
            return True, f"Candle too young ({candle_progress_pct:.0f}% < {self.candle_young_threshold_weak}%) with weak signals"
        
        return False, ""
    
    def check_cooldown(self, symbol: str) -> Tuple[bool, str]:
        """Check if we're in cooldown period after a veto."""
        in_cooldown, seconds_left = self._is_in_cooldown(symbol)
        if in_cooldown:
            return True, f"Cooldown active: {seconds_left}s remaining"
        return False, ""
    

    def _begin_veto_record(self, symbol: str) -> None:
        """Start a fresh canonical record for this symbol's decision."""
        with self._veto_ledger_lock:
            self._veto_ledger[symbol] = {"__order__": []}

    def _rec(self, symbol: str, name: str, vetoed: bool, reason: str = "") -> None:
        """Record one check exactly as the decision path evaluated it."""
        with self._veto_ledger_lock:
            entry = self._veto_ledger.setdefault(symbol, {"__order__": []})
            if name not in entry:
                entry["__order__"].append(name)
            entry[name] = {"evaluated": True, "vetoed": bool(vetoed), "reason": reason or ""}

            # Same fact, chronological. Written under the same lock so the two
            # views cannot disagree about what was decided.
            self._veto_stream.append({
                "timestamp": time.time(),
                "symbol": symbol,
                "gate": name,
                "vetoed": bool(vetoed),
                "reason": reason or "",
            })

    def get_recent_gate_events(self, limit: int = 100,
                               symbol: Optional[str] = None,
                               vetoed_only: bool = False) -> list:
        """The most recent gate decisions, newest first.

        This is the feed behind the UI's gate ticker, and the fastest answer to
        "why did nothing trade in the last ten minutes?" -- one check dominating
        the list is the whole diagnosis.

        `vetoed_only` filters to the checks that actually blocked. Off by
        default, because a stream of passes is what makes a single veto
        legible; filtered to vetoes alone, every entry looks equally damning.
        """
        with self._veto_ledger_lock:
            events = list(self._veto_stream)

        if symbol:
            events = [e for e in events if e["symbol"] == symbol]
        if vetoed_only:
            events = [e for e in events if e["vetoed"]]

        events.reverse()  # newest first
        return events[:max(1, int(limit))]

    def get_gate_summary(self, window_seconds: float = 600.0) -> Dict[str, Any]:
        """Which checks are blocking, and how often, over a recent window.

        Counts per gate rather than a list, because the actionable question is
        which ONE check to look at -- and that is invisible in a flat feed once
        it is more than a screen long.
        """
        cutoff = time.time() - max(1.0, float(window_seconds))

        with self._veto_ledger_lock:
            events = [e for e in self._veto_stream if e["timestamp"] >= cutoff]

        by_gate: Dict[str, Dict[str, int]] = {}
        for e in events:
            bucket = by_gate.setdefault(e["gate"], {"evaluated": 0, "vetoed": 0})
            bucket["evaluated"] += 1
            if e["vetoed"]:
                bucket["vetoed"] += 1

        blocked = sum(1 for e in events if e["vetoed"])

        return {
            "window_seconds": window_seconds,
            "evaluated": len(events),
            "vetoed": blocked,
            "symbols_seen": len({e["symbol"] for e in events}),
            # Sorted by what blocks most -- the first row is where to look.
            "by_gate": dict(sorted(
                by_gate.items(), key=lambda kv: kv[1]["vetoed"], reverse=True)),
        }

    def get_veto_record(self, symbol: str) -> Dict[str, Any]:
        """
        The canonical veto truth for the last decision on this symbol.

        Reporting MUST read from here rather than re-invoking the checks.
        Checks absent from the record did not run (short-circuit) and must
        be reported as not-evaluated rather than as False.
        """
        with self._veto_ledger_lock:
            return dict(self._veto_ledger.get(symbol, {}))

    def check_all_vetos(
        self,
        symbol: str,
        best_direction: str,
        adx_val: float,
        atr_pips: float,
        trend: str,
        current_price: float,
        ema_200: float,
        h1_trend: str,
        rsi_div_score: float,
        rsi_div_rsi: float,
        upper_wick_pips: float,
        lower_wick_pips: float,
        body_pips: float,
        volume_ratio: float,
        spread_valid: bool,
        spread_pips: float,
        max_allowed_spread: int,
        entry_triggered: bool,
        candle_progress_pct: float,
        is_already_in_trade: bool,
        session_result: Dict,
        news_veto_func: Optional[Callable] = None,
        session_manager: Optional[Any] = None,
        signal_count: int = 0,
        probability: float = 0,
        volume_spike: bool = False,
        absorption: bool = False,
        atr_band: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Check all veto conditions in priority order.
        
        FIXED: Added try/except to prevent crashes, fails open.
        FIXED: All vetoes now return descriptive reasons.
        FIXED: Empty veto reasons replaced with default descriptions.
        FIXED: Volume veto now trend-aware.
        
        Args:
            signal_count: Number of golden signals detected (for candle veto)
            probability: Current best probability (for candle veto)
            volume_spike: Whether volume spike is detected (for candle veto)
            absorption: Whether absorption is detected (for candle veto)
        
        Returns:
            (veto_triggered, veto_reason, modified_sl_pips)
        """
        modified_sl_pips = None
        veto_reason = ""
        veto = False
        
        try:
            self._begin_veto_record(symbol)
            # Check cooldown first
            cooldown_veto, cooldown_reason = self.check_cooldown(symbol)
            self._rec(symbol, "cooldown", cooldown_veto, cooldown_reason)
            if cooldown_veto:
                print(f"🛑 [VETO] {cooldown_reason}")
                return True, cooldown_reason, modified_sl_pips
            
            # V0: Session veto (HIGHEST PRIORITY)
            session_veto, session_reason, modify_sl, new_sl = self.check_session_veto(
                is_already_in_trade, session_result
            )
            if session_veto:
                print(f"🛑 [VETO] {session_reason}")
                if modify_sl and new_sl:
                    modified_sl_pips = new_sl
                return True, session_reason, modified_sl_pips
            
            # V0.5: Weekend veto (for new entries)
            if not is_already_in_trade and session_manager:
                weekend_veto, weekend_reason, modify_sl, new_sl = self.check_weekend_veto(
                    symbol, session_manager, is_already_in_trade
                )
                if weekend_veto:
                    print(f"🛑 [VETO] {weekend_reason}")
                    if modify_sl and new_sl:
                        modified_sl_pips = new_sl
                    return True, weekend_reason, modified_sl_pips
            
            # V0.6: Holiday veto (for new entries)
            if not is_already_in_trade and session_manager:
                holiday_veto, holiday_reason, modify_sl, new_sl = self.check_holiday_veto(
                    symbol, session_manager, is_already_in_trade
                )
                if holiday_veto:
                    print(f"🛑 [VETO] {holiday_reason}")
                    if modify_sl and new_sl:
                        modified_sl_pips = new_sl
                    return True, holiday_reason, modified_sl_pips
            
            # V0.7: News veto
            news_veto, news_reason = self.check_news_veto(
                symbol, best_direction, news_veto_func, is_already_in_trade
            )
            self._rec(symbol, "news_veto", news_veto, news_reason)
            if news_veto and self._veto_active("news_veto"):
                self._record_veto(symbol)
                print(f"🛑 [VETO] {news_reason}")
                return True, news_reason, modified_sl_pips
            
            # V1: Choppy market (instrument-aware)
            veto, reason = self.check_choppy_market(adx_val, symbol)
            self._rec(symbol, "choppy_market", veto, reason)
            if veto and self._veto_active("choppy_market", unit_id=symbol):
                print(f"🛑 [VETO] {reason}")
                return True, reason, modified_sl_pips
            
            # V2: Extreme volatility (instrument-aware)
            veto, reason = self.check_extreme_volatility(atr_pips, symbol, atr_band=atr_band)
            self._rec(symbol, "extreme_volatility", veto, reason)
            if veto and self._veto_active("extreme_volatility"):
                print(f"🛑 [VETO] {reason}")
                return True, reason, modified_sl_pips
            
            # V3: Against trend
            # veto, reason = self.check_against_trend(best_direction, trend)
            # if veto:
            #     return True, reason, modified_sl_pips
            
            # V4: Against 200 EMA -- re-enabled, blocks -0.215R setups.
            if self.enable_trend_vetoes:
                veto, reason = self.check_against_ema(
                    best_direction, current_price, ema_200)
                self._rec(symbol, "against_ema", veto, reason)
                if veto and self._veto_active("against_ema", unit_id=symbol):
                    print(f"🛑 [VETO] {reason}")
                    return True, reason, modified_sl_pips

            # V5: H1 conflict -- re-enabled, blocks -0.164R setups.
            if self.enable_trend_vetoes:
                veto, reason = self.check_h1_conflict(best_direction, h1_trend)
                self._rec(symbol, "h1_conflict", veto, reason)
                if veto and self._veto_active("h1_conflict", unit_id=symbol):
                    return True, reason, modified_sl_pips

            # V3 (against_trend) stays OFF: measured at +0.0036R when it
            # fires against -0.0542R when it does not -- inverted like
            # choppy_market was, and enabling it cut the sample to 31 trades
            # for no gain. Left inert deliberately, not by oversight.
            
            # V6: RSI divergence opposing
            veto, reason = self.check_rsi_divergence_opposing(best_direction, rsi_div_score, rsi_div_rsi)
            self._rec(symbol, "rsi_divergence_opposing", veto, reason)
            if veto and self._veto_active("rsi_divergence_opposing"):
                return True, reason, modified_sl_pips
            
            # V7: Wick reversal (FIXED: size-aware)
            veto, reason = self.check_wick_reversal(best_direction, upper_wick_pips, lower_wick_pips, body_pips)
            self._rec(symbol, "wick_reversal", veto, reason)
            if veto and self._veto_active("wick_reversal"):
                return True, reason, modified_sl_pips
            
            # V8: Low volume (FIXED: trend-aware)
            veto, reason = self.check_low_volume(volume_ratio, trend, adx_val)
            self._rec(symbol, "low_volume", veto, reason)
            if veto and self._veto_active("low_volume"):
                return True, reason, modified_sl_pips
            
            # V9: High spread
            veto, reason = self.check_high_spread(spread_valid, spread_pips, max_allowed_spread)
            self._rec(symbol, "high_spread", veto, reason)
            if veto and self._veto_active("high_spread"):
                return True, reason, modified_sl_pips
            
            # V10: Candle too young (FIXED - signal-aware)
            veto, reason = self.check_candle_too_young(
                entry_triggered,
                candle_progress_pct,
                signal_count,
                probability,
                volume_spike,
                absorption
            )
            self._rec(symbol, "candle_too_young", veto, reason)
            if veto and self._veto_active("candle_too_young"):
                # Ensure reason is not empty
                if not reason:
                    reason = f"Candle too young ({candle_progress_pct:.0f}% < {self.candle_young_threshold_weak}%) with weak signals"
                return True, reason, modified_sl_pips
            
            return False, "", modified_sl_pips
            
        except Exception as e:
            logger.error(f"[VETO] Error in check_all_vetos for {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Fail open - allow trade if veto check fails
            return False, "", modified_sl_pips
    
    def get_stats(self) -> Dict[str, Any]:
        """Get veto engine statistics."""
        with self._lock:
            return {
                "last_veto_time": self._last_veto_time,
                "last_veto_symbol": self._last_veto_symbol,
                "veto_count": self._veto_count,
                "cooldown_seconds": self.cooldown_seconds,
                "cooldown_active": self._last_veto_time and (time.time() - self._last_veto_time < self.cooldown_seconds)
            }
    
    def reset_stats(self):
        """Reset veto engine statistics."""
        with self._lock:
            self._veto_count = 0
            self._last_veto_time = 0
            self._last_veto_symbol = None
            logger.info("[VETO] Statistics reset")
    
    def update_thresholds(self, **kwargs):
        """Update veto thresholds at runtime."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.info(f"[VETO] Updated {key} to {value}")
            else:
                logger.warning(f"[VETO] Unknown threshold: {key}")
    
    def get_effective_thresholds(self, symbol: str, atr_band: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        ✅ NEW: the thresholds ACTUALLY used for this symbol, after the
        per-instrument overrides above are applied.

        get_thresholds() below returns the raw tables, including the full
        instrument dicts -- useful for inspection, useless for answering
        "what number decided this bar." Nothing outside this class could
        answer that, so the reporting layer quoted the flat, system-wide
        constants instead and disagreed with the veto that actually ran:

            choppy_market      gate quoted RANGING_MARKET_ADX_THRESHOLD 25,
                               XAGUSD actually vetoes below 22
            extreme_volatility gate quoted EXTREME_VOLATILITY_VETO_THRESHOLD
                               70.0, XAGUSD actually vetoes above 80.0

        Both agree at most ATR/ADX values, so it stayed invisible. The
        contradiction bands are ADX in [22, 25) and ATR in (70, 80] --
        there the gate reports FAIL with a negative margin while the veto
        does not fire, which is the same "passing gate, negative margin"
        signature already seen and fixed once on the volatility side.
        """
        # The volatility limit the veto ACTUALLY applies: the instrument's own
        # band extreme when an adaptive band exists (check_extreme_volatility),
        # the static table otherwise. Reporting the static number while the
        # veto used the band made coherence flag "check true, no veto" on gold.
        band_extreme = None
        if isinstance(atr_band, dict) and atr_band.get("adaptive"):
            try:
                band_extreme = float(atr_band.get("extreme")) or None
            except (TypeError, ValueError):
                band_extreme = None
        return {
            "symbol": symbol,
            "adx_threshold": self._get_instrument_adx_threshold(symbol),
            # off / block / invert -- a gate that is off cannot disagree with its veto
            "choppy_market_mode": getattr(self, "choppy_market_mode", "invert"),
            "volatility_threshold_pips": band_extreme or self._get_instrument_volatility_threshold(symbol),
            "volatility_threshold_band": band_extreme is not None,
            "adx_threshold_source": (
                "instrument_override"
                if self._get_instrument_adx_threshold(symbol) != self.instrument_adx_thresholds["DEFAULT"]
                else "default"
            ),
            "volatility_threshold_source": (
                "instrument_override"
                if self._get_instrument_volatility_threshold(symbol) != self.instrument_volatility_thresholds["DEFAULT"]
                else "default"
            ),
        }

    def get_thresholds(self) -> Dict[str, Any]:
        """Get current veto thresholds (raw tables -- see
        get_effective_thresholds() for what actually applies to a symbol)."""
        return {
            "min_adx_for_trend": self.min_adx_for_trend,
            "extreme_volatility_threshold": self.extreme_volatility_threshold,
            "min_volume_ratio": self.min_volume_ratio,
            "candle_young_threshold_weak": self.candle_young_threshold_weak,
            "candle_young_threshold_strong": self.candle_young_threshold_strong,
            "wick_rejection_ratio": self.wick_rejection_ratio,
            "rsi_oversold_for_buy": self.rsi_oversold_for_buy,
            "rsi_overbought_for_sell": self.rsi_overbought_for_sell,
            "divergence_extreme_score": self.divergence_extreme_score,
            "cooldown_seconds": self.cooldown_seconds,
            "instrument_adx_thresholds": self.instrument_adx_thresholds,
            "instrument_volatility_thresholds": self.instrument_volatility_thresholds,
            # New config values from config.py
            "volume_threshold_strong_trend": VOLUME_THRESHOLD_STRONG_TREND,
            "volume_threshold_moderate_trend": VOLUME_THRESHOLD_MODERATE_TREND,
            "volume_threshold_weak_trend": VOLUME_THRESHOLD_WEAK_TREND,
            "wick_reversal_ratio_normal": WICK_REVERSAL_RATIO_NORMAL,
            "wick_reversal_ratio_small": WICK_REVERSAL_RATIO_SMALL,
            "wick_small_candle_body_threshold": WICK_SMALL_CANDLE_BODY_THRESHOLD
        }


# Global instance
_veto_engine = None
_veto_engine_lock = Lock()


def get_veto_engine(config: Dict[str, Any] = None) -> VetoEngine:
    """Get or create the global veto engine instance."""
    global _veto_engine
    with _veto_engine_lock:
        if _veto_engine is None:
            _veto_engine = VetoEngine(config)
        return _veto_engine


def reset_veto_engine(config: Dict[str, Any] = None):
    """Reset the global veto engine instance."""
    global _veto_engine
    with _veto_engine_lock:
        _veto_engine = VetoEngine(config)
        logger.info("[VETO] Engine reset")


def check_all_vetos(
    symbol: str,
    best_direction: str,
    adx_val: float,
    atr_pips: float,
    trend: str,
    current_price: float,
    ema_200: float,
    h1_trend: str,
    rsi_div_score: float,
    rsi_div_rsi: float,
    upper_wick_pips: float,
    lower_wick_pips: float,
    body_pips: float,
    volume_ratio: float,
    spread_valid: bool,
    spread_pips: float,
    max_allowed_spread: int,
    entry_triggered: bool,
    candle_progress_pct: float,
    is_already_in_trade: bool,
    session_result: Dict,
    news_veto_func: Optional[Callable] = None,
    session_manager: Optional[Any] = None,
    signal_count: int = 0,
    probability: float = 0,
    volume_spike: bool = False,
    absorption: bool = False,
    atr_band: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[float]]:
    """
    Convenience function to check all vetos.
    """
    engine = get_veto_engine()
    return engine.check_all_vetos(
        symbol=symbol,
        best_direction=best_direction,
        adx_val=adx_val,
        atr_pips=atr_pips,
        trend=trend,
        current_price=current_price,
        ema_200=ema_200,
        h1_trend=h1_trend,
        rsi_div_score=rsi_div_score,
        rsi_div_rsi=rsi_div_rsi,
        upper_wick_pips=upper_wick_pips,
        lower_wick_pips=lower_wick_pips,
        body_pips=body_pips,
        volume_ratio=volume_ratio,
        spread_valid=spread_valid,
        spread_pips=spread_pips,
        max_allowed_spread=max_allowed_spread,
        entry_triggered=entry_triggered,
        candle_progress_pct=candle_progress_pct,
        is_already_in_trade=is_already_in_trade,
        session_result=session_result,
        news_veto_func=news_veto_func,
        session_manager=session_manager,
        signal_count=signal_count,
        probability=probability,
        volume_spike=volume_spike,
        absorption=absorption,
        atr_band=atr_band
    )


def get_veto_stats() -> Dict[str, Any]:
    """Get veto engine statistics."""
    engine = get_veto_engine()
    return engine.get_stats()


def reset_veto_stats():
    """Reset veto engine statistics."""
    engine = get_veto_engine()
    engine.reset_stats()


def update_veto_thresholds(**kwargs):
    """Update veto thresholds at runtime."""
    engine = get_veto_engine()
    engine.update_thresholds(**kwargs)


def get_effective_veto_thresholds(symbol: str, atr_band: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Module-level accessor for the thresholds that actually apply to
    `symbol` after per-instrument overrides."""
    return get_veto_engine().get_effective_thresholds(symbol, atr_band=atr_band)


def get_veto_thresholds() -> Dict[str, Any]:
    """Get current veto thresholds."""
    engine = get_veto_engine()
    return engine.get_thresholds()