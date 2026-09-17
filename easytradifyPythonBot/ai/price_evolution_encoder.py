# ============================================================
# PRICE EVOLUTION ENCODER -- the current asset-analysis snapshot, for storage
# ============================================================
# FILE: ai/price_evolution_encoder.py
#
# One encoded blob per analysis:
#
#   <field codes>        every mapped scalar of the snapshot, VERBATIM, under
#                        the short codes in ai/price_evolution_maps.FIELDS.
#                        compact=True (what price_evolution points use) keeps
#                        the decision subset; a full encode keeps all of them.
#   full_analysis_z      the whole snapshot, zlib + base64. Lossless: decode()
#                        rebuilds every field, list and detector block from it.
#   layout               "grouped" (core/analysis_groups.reshape ran) or "flat".
#   unmapped_paths       paths the maps cannot place -- empty when the maps match
#                        the snapshot. Stored so schema drift shows up in the data
#                        itself instead of in a model that quietly reads nothing.
#
# Rebuilt 2026-09-17. The previous encoder mapped a payload that no longer exists
# (components 1_trend_bias..8_indicators, gnn/ohlc_gnn, pattern_analysis,
# indicator_scores, lot_result, directional_analysis, session/news/volatility at
# the top level): every short code read an absent section and wrote its default,
# and the strategy groups, state readings, direction decision, market stop and
# OU reversion -- what the decision is now made from -- had no code at all. Only
# the compressed payload was ever correct.
#
# Codes are stored verbatim on purpose. Rounding and integer enums are what made
# the old codes lossy, and an enum map meets a label it has never seen by
# writing a default -- the silent failure this module exists to prevent.
# ============================================================

from __future__ import annotations

import base64
import json
import logging
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .price_evolution_maps import SCHEMA_NAME, SCHEMA_VERSION, EvolutionMaps

logger = logging.getLogger(__name__)

# How many unmapped paths a blob names. The count is always stored; the list is
# a sample, because a payload that drifted by a whole section would otherwise
# repeat hundreds of paths on every price point.
MAX_UNMAPPED_REPORTED = 20


def _num(mapping, key, default):
    """
    A numeric field from a payload, tolerating an explicit None.

    dict.get() returns the default only when the key is ABSENT -- a key PRESENT
    with value None returns None, and None * 10 raises TypeError. That is not
    hypothetical: analyze_institutional_signal emits
    micro_structure.timing_confidence = None whenever tick data is unavailable,
    and an exception while encoding used to drop the whole price point.

    Returns `default` for None, non-numeric and unparseable values alike.
    """
    value = mapping.get(key, default) if hasattr(mapping, "get") else default
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class PriceEvolutionEncoder:
    """Encode an asset-analysis snapshot: verbatim field codes plus a lossless payload."""

    def __init__(self):
        self.maps = EvolutionMaps()
        self.last_validation: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ wrappers
    def encode_price_evolution(self, payload: Any, timeframe: str = "M1",
                               position: Dict = None) -> Dict[str, Any]:
        """Compatibility wrapper: a full analysis dict, or a raw price-history payload."""
        if isinstance(payload, dict):
            return self.encode(payload, position)
        return {
            "schema_version": SCHEMA_VERSION,
            "analysis_type": "price_history",
            "timeframe": timeframe,
            "history": self.maps.make_json_safe(payload),
        }

    def get_field_coverage(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """How the maps classify this payload, and whether every path is placed."""
        if not isinstance(analysis, dict):
            return {"all_fields_preserved": False, "matches": False,
                    "reason": "analysis is not a dictionary"}
        report = self.maps.coverage(self.maps.make_json_safe(analysis))
        report["top_level_fields"] = sorted(analysis.keys())
        # The compressed payload keeps every path whether or not it is mapped.
        report["full_analysis_preserved"] = True
        report["all_fields_preserved"] = True
        return report

    # ------------------------------------------------------------------ encode
    def encode(self, analysis: Dict[str, Any], position: Dict = None,
               compact: bool = False) -> Dict[str, Any]:
        """
        Encode one analysis snapshot.

        `compact=True` keeps only the decision subset of field codes (the ones a
        stored price point is queried by). Nothing is lost either way: decode()
        rebuilds the snapshot from full_analysis_z.
        """
        safe = self.maps.make_json_safe(analysis if isinstance(analysis, dict) else {})

        # Encode time, labelled as such. It is never written as `timestamp`:
        # a price point is stored minutes to hours after the decision it holds.
        result: Dict[str, Any] = {"t": datetime.now(timezone.utc).isoformat()}

        # Where the open position stood, only when the caller supplied one. The
        # old encoder wrote 0 for all of these when it had no position, which a
        # reader cannot tell apart from a price of 0.
        if position:
            for code, key in (("p", "price_current"), ("pf", "profit_usd"), ("pp", "profit_pips")):
                value = _num(position, key, None)
                if value is not None:
                    result[code] = value
            bar = {code: _num(position, key, None)
                   for code, key in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}
            if any(v is not None for v in bar.values()):
                result["ohlc"] = {k: v for k, v in bar.items() if v is not None}

        # Provenance is copied only when the analysis asserted it.
        if safe.get("model_version") is not None:
            result["mv"] = safe["model_version"]

        result.update(self.maps.encode_fields(safe, compact=compact))

        coverage = self.maps.coverage(safe)
        result["layout"] = coverage["layout"]
        if coverage["unmapped"]:
            result["unmapped_paths"] = coverage["unmapped"][:MAX_UNMAPPED_REPORTED]
            result["unmapped_count"] = len(coverage["unmapped"])
        if not compact:
            result["full_analysis_keys"] = sorted(safe.keys())
        result["analysis_schema"] = SCHEMA_NAME
        result["schema_version"] = SCHEMA_VERSION

        try:
            raw = json.dumps(safe, separators=(",", ":"), ensure_ascii=False,
                             default=str).encode("utf-8")
            result["full_analysis_z"] = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
            result["full_analysis_bytes"] = len(raw)
        except Exception as exc:
            # Never lose the analysis because compression failed.
            logger.warning(f"full_analysis compression failed, storing raw: {exc}")
            result["full_analysis"] = safe

        self._validate_encoding(result, safe)
        return result

    # ------------------------------------------------------------------ validation
    def _validate_encoding(self, encoded: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Check the blob decodes to what went in, and record the verdict.

        Never raises: a price point that fails validation is still stored (the
        compressed payload is the record), but last_validation says what failed
        and a warning is logged so it cannot go unnoticed.
        """
        problems = []
        payload = encoded.get("full_analysis")
        packed = encoded.get("full_analysis_z")
        if packed:
            try:
                payload = json.loads(zlib.decompress(base64.b64decode(packed)).decode("utf-8"))
            except Exception as exc:
                problems.append(f"payload does not decompress: {exc}")
                payload = None
        if payload is not None:
            expected = json.loads(json.dumps(source, ensure_ascii=False, default=str))
            if payload != expected:
                problems.append("payload does not reproduce the analysis")

        codes = 0
        for code, value in encoded.items():
            field = self.maps.FIELDS_BY_CODE.get(code)
            if field is None:
                continue
            codes += 1
            if self.maps.get_path(source, field.path) != value:
                problems.append(f"code {code} does not match {'.'.join(field.path)}")

        self.last_validation = {
            "ok": not problems,
            "codes": codes,
            "unmapped": encoded.get("unmapped_count", 0),
            "layout": encoded.get("layout"),
            "bytes": encoded.get("full_analysis_bytes"),
            "problems": problems[:10],
        }
        if problems:
            logger.warning(f"[ENCODER] validation failed: {problems[:3]}")
