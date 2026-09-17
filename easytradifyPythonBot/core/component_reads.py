# ============================================================
# COMPONENT READS -- SCORING THE SUBSYSTEMS THAT NEVER ENTER THE LEDGER
# ============================================================
# FILE: core/component_reads.py
#
# WHY THIS EXISTS
# ---------------
# The probability ledger has ~13 steps, and every measurement in this project
# has been built on them. But several whole subsystems produce a real,
# directional read and contribute NOTHING to the chain, so they have no ledger
# entry and cannot be scored at all:
#
#   volume_profile   emits poc / vah / val / score / recommendation
#   wyckoff          emits phase / score / recommendation
#   elliott_waves    emits wave type / current wave / confidence
#   wave_lattice     emits a multi-timeframe wave read
#   gnn              emits a recommendation and a score
#   smc.trade_setup  emits confluence_count / is_perfect_setup
#
# Each of these is computed on every decision, published in the payload,
# surfaced in dashboards -- and has never once been tested against an outcome.
# "We do not know whether this works" is the honest description, and it
# applies to a substantial fraction of the analysis.
#
# WHAT THIS DOES, AND DELIBERATELY DOES NOT DO
# --------------------------------------------
# It extracts a SIGNED read per subsystem -- positive when the subsystem
# supports the trade being taken, negative when it opposes -- and records it
# beside the analysis.
#
# It does NOT contribute to the probability. Not one of these has been
# validated on this account, and wiring an unvalidated component into the
# chain is exactly how `pattern` came to push 12 probability points the WRONG
# way on 26% of trades. Measure first; the forward data decides whether any of
# them earns a vote.
#
# SIGNING
# -------
# Every read is signed against the trade direction, because a market read
# means the opposite thing for a long and a short. Components that reported a
# market read and left the caller to sign it are the source of the single
# largest defect found in this codebase.
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

COMPONENT_READS_VERSION = "1.0"

# Recommendation vocabularies, mapped to a market direction in [-1, 1].
# STRONG variants score higher because the subsystems emit them to mean
# exactly that, and flattening them would discard information the component
# went to the trouble of producing.
BULLISH_WORDS = {
    "STRONG_BUY": 1.0, "STRONG_BULLISH": 1.0, "BUY": 0.6, "BULLISH": 0.6,
    "ACCUMULATION": 0.6, "MARKUP": 0.6, "LONG": 0.6, "SUPPORT": 0.5,
}
BEARISH_WORDS = {
    "STRONG_SELL": -1.0, "STRONG_BEARISH": -1.0, "SELL": -0.6,
    "BEARISH": -0.6, "DISTRIBUTION": -0.6, "MARKDOWN": -0.6, "SHORT": -0.6,
    "RESISTANCE": -0.5,
}
NEUTRAL_WORDS = {"NEUTRAL", "WAIT", "HOLD", "NONE", "CONSOLIDATION",
                 "UNAVAILABLE", "UNKNOWN", "RANGING"}


def _block(analysis, name):
    """The named block whether the payload is grouped (analysis.<GROUP>.data.*)
    or flat -- see core/analysis_groups.py."""
    from core.analysis_groups import block
    return block(analysis or {}, name) or {}


def _market_direction(text: Any) -> Optional[float]:
    """
    A recommendation string as a market direction in [-1, 1].

    Returns None for an unrecognised value rather than 0.0. Zero would mean
    "this component says neutral", and an unmapped string means "we do not
    know what this component said" -- collapsing the two would silently
    convert a parsing gap into a measurement.
    """
    if not isinstance(text, str):
        return None
    token = text.strip().upper().replace(" ", "_")
    if not token:
        return None
    if token in NEUTRAL_WORDS:
        return 0.0
    if token in BULLISH_WORDS:
        return BULLISH_WORDS[token]
    if token in BEARISH_WORDS:
        return BEARISH_WORDS[token]
    # Substring fallback, longest match first so STRONG_BUY is not read as BUY.
    for table in (BULLISH_WORDS, BEARISH_WORDS):
        for word in sorted(table, key=len, reverse=True):
            if word in token:
                return table[word]
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _read(name: str, direction: str, market: Optional[float],
          confidence: Optional[float] = None,
          detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One subsystem's read, signed against the trade."""
    entry: Dict[str, Any] = {"component": name}
    if market is None:
        entry["available"] = False
        entry["reason"] = "no recognisable directional read"
        if detail:
            entry.update(detail)
        return entry

    sign = 1 if str(direction).upper() == "BUY" else -1
    entry.update({
        "available": True,
        "market_direction": round(market, 4),
        # THE field a downstream test uses: positive = supports this trade.
        "supports_trade": round(sign * market, 4),
        "confidence": round(confidence, 4) if confidence is not None else None,
        # Never a probability contribution. See the module docstring.
        "contribution": 0.0,
    })
    if detail:
        entry.update(detail)
    return entry


# ============================================================
# EXTRACTORS -- one per unscored subsystem
# ============================================================

def volume_profile_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """
    Volume profile: where price sits relative to POC and the value area.

    Position within the value area is a genuine directional read -- below POC
    inside the area is a different setup from above it -- and the subsystem
    already computes it. It has never been scored.
    """
    node = (_block(analysis, "indicators").get("volume_profile")
            or analysis.get("volume_profile") or {})
    if not isinstance(node, Mapping) or not node:
        return _read("volume_profile", direction, None)

    market = _market_direction(node.get("recommendation"))
    detail = {k: node.get(k) for k in ("poc", "vah", "val", "score", "reason")
              if node.get(k) is not None}

    # Derive a position read when the recommendation is neutral: inside the
    # value area, below POC is a different location from above it.
    poc, vah, val = (_number(node.get("poc")), _number(node.get("vah")),
                     _number(node.get("val")))
    price = _number(analysis.get("💰 ENTRY")) or _number(
        (analysis.get("entry_analysis") or {}).get("entry_price"))
    if price and poc and vah and val and vah > val:
        detail["position_in_value_area"] = round((price - val) / (vah - val), 4)
        detail["distance_from_poc_pct"] = round((price - poc) / poc * 100.0, 4)

    return _read("volume_profile", direction, market,
                 _number(node.get("confidence")), detail)


def wyckoff_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """Wyckoff phase and recommendation -- computed everywhere, scored nowhere."""
    node = (_block(analysis, "indicators").get("wyckoff")
            or (analysis.get("components") or {}).get("wyckoff") or {})
    if not isinstance(node, Mapping) or not node:
        return _read("wyckoff", direction, None)

    # The PHASE carries more meaning than the recommendation: ACCUMULATION and
    # DISTRIBUTION are directional claims, CONSOLIDATION is not.
    market = _market_direction(node.get("recommendation"))
    if market in (None, 0.0):
        market = _market_direction(node.get("phase")) or market
    return _read("wyckoff", direction, market, _number(node.get("score")),
                 {"phase": node.get("phase"),
                  "recommendation": node.get("recommendation")})


def elliott_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """
    Elliott waves: the highest-confidence actionable wave.

    Waves live in `pattern_analysis.elliott_waves` as a LIST, and only entries
    whose recommendation is an actual trade call count -- the detector also
    emits WATCH/WAIT reads that carry a direction but are explicitly not
    tradeable. Treating those as signals is a bug this codebase has already
    had once, worth +13.7 probability points in the wrong direction.
    """
    waves = (_block(analysis, "pattern_analysis").get("elliott_waves")
             or analysis.get("elliott_waves") or [])
    if not isinstance(waves, Sequence) or isinstance(waves, (str, bytes)):
        return _read("elliott_wave", direction, None)

    best, best_conf = None, -1.0
    for wave in waves:
        if not isinstance(wave, Mapping):
            continue
        recommendation = str(wave.get("recommendation") or "").upper()
        if recommendation not in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL"):
            continue
        confidence = _number(wave.get("confidence")) or 0.0
        if confidence > best_conf:
            best, best_conf = wave, confidence

    if best is None:
        return _read("elliott_wave", direction, None,
                     detail={"waves_present": len(waves),
                             "reason": "no actionable wave recommendation"})
    return _read("elliott_wave", direction,
                 _market_direction(best.get("recommendation")), best_conf,
                 {"wave_type": best.get("type"),
                  "current_wave": best.get("current_wave"),
                  "next_wave": best.get("next_wave"),
                  "waves_present": len(waves)})


def gnn_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """Cross-asset GNN read. Often unavailable, which is itself worth recording."""
    node = _block(analysis, "gnn")
    final = node.get("final_score") if isinstance(node, Mapping) else None
    if not isinstance(node, Mapping) or not node.get("available"):
        return _read("gnn", direction, None,
                     detail={"reason": "gnn unavailable on this decision"})
    market = _market_direction(
        (final or {}).get("gnn_recommendation") if isinstance(final, Mapping) else None)
    return _read("gnn", direction, market,
                 _number((final or {}).get("gnn_score")),
                 {"data_quality": node.get("data_quality")})


def smc_setup_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """
    SMC confluence COUNT, separate from the smc probability step.

    The chain scores an SMC recommendation; the confluence count is a
    different measurement (how much structure agreed) and is not scored
    anywhere. Recorded unsigned -- it is a magnitude, not a direction.
    """
    setup = _block(analysis, "smc").get("trade_setup") or {}
    if not isinstance(setup, Mapping) or not setup:
        return {"component": "smc_setup", "available": False}
    return {
        "component": "smc_setup", "available": True,
        "confluence_count": _number(setup.get("confluence_count")),
        "is_perfect_setup": bool(setup.get("is_perfect_setup")),
        "contribution": 0.0,
    }


def wave_lattice_read(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """Multi-timeframe wave lattice summary -- published, never scored."""
    node = _block(analysis, "wave_lattice")
    summary = node.get("lattice_summary") if isinstance(node, Mapping) else None
    if not isinstance(summary, Mapping) or not summary:
        return {"component": "wave_lattice", "available": False}
    market = _market_direction(summary.get("bias") or summary.get("direction"))
    return _read("wave_lattice", direction, market,
                 _number(summary.get("confidence")),
                 {"root_timeframe": summary.get("root_timeframe"),
                  "nodes": len(node.get("nodes") or {})})


EXTRACTORS = (volume_profile_read, wyckoff_read, elliott_read, gnn_read,
              smc_setup_read, wave_lattice_read)


def extract(analysis: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """
    Every unscored subsystem's read, signed against the trade.

    One failing extractor must not lose the others, so each is isolated: a
    payload shape change in one subsystem should cost that subsystem's
    reading, not the whole block.
    """
    out: Dict[str, Any] = {"version": COMPONENT_READS_VERSION}
    if not isinstance(analysis, Mapping):
        return out
    for extractor in EXTRACTORS:
        try:
            read = extractor(analysis, direction)
            out[read.get("component") or extractor.__name__] = read
        except Exception as exc:
            out[extractor.__name__] = {"available": False,
                                       "reason": "extractor failed: %s" % exc}
    out["available_count"] = sum(
        1 for v in out.values()
        if isinstance(v, Mapping) and v.get("available"))
    return out


def get_status() -> Dict[str, Any]:
    return {"component": "component_reads",
            "version": COMPONENT_READS_VERSION,
            "subsystems": [f.__name__.replace("_read", "") for f in EXTRACTORS],
            "wired_into_probability": False}


def self_check() -> Dict[str, Any]:
    """
    Prove reads are signed against the trade and that unknown values are not
    silently turned into neutral.
    """
    analysis = {
        "indicators": {
            "volume_profile": {"recommendation": "BULLISH", "confidence": 40,
                               "poc": 100.0, "vah": 110.0, "val": 90.0},
            "wyckoff": {"phase": "ACCUMULATION", "recommendation": "NEUTRAL",
                        "score": 3},
        },
        "pattern_analysis": {"elliott_waves": [
            {"recommendation": "WATCH", "confidence": 0.9, "type": "diagonal"},
            {"recommendation": "SELL", "confidence": 0.6, "type": "corrective",
             "current_wave": "C"},
        ]},
        "smc": {"trade_setup": {"confluence_count": 3, "is_perfect_setup": False}},
        "gnn": {"available": False},
        "💰 ENTRY": 105.0,
    }
    buy = extract(analysis, "BUY")
    sell = extract(analysis, "SELL")

    checks = {
        # a bullish volume profile supports a BUY and opposes a SELL
        "signed_against_trade": (buy["volume_profile"]["supports_trade"] > 0
                                 and sell["volume_profile"]["supports_trade"] < 0),
        # phase used when the recommendation is neutral
        "wyckoff_uses_phase": buy["wyckoff"]["supports_trade"] > 0,
        # WATCH is not tradeable even at higher confidence than the SELL
        "elliott_ignores_watch": buy["elliott_wave"]["market_direction"] < 0,
        "gnn_unavailable_reported": buy["gnn"]["available"] is False,
        "smc_confluence_captured": buy["smc_setup"]["confluence_count"] == 3,
        "value_area_position": abs(
            buy["volume_profile"]["position_in_value_area"] - 0.75) < 1e-6,
        # never a probability contribution
        "no_probability_contribution": all(
            v.get("contribution", 0.0) == 0.0
            for v in buy.values() if isinstance(v, Mapping)),
        # an unknown recommendation must be None, not 0.0
        "unknown_is_not_neutral": _market_direction("WHATEVER") is None,
        "neutral_is_zero": _market_direction("NEUTRAL") == 0.0,
    }
    return {"component": "component_reads", "version": COMPONENT_READS_VERSION,
            "checks": checks, "ok": all(checks.values())}
