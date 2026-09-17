# ============================================================
# PRICE EVOLUTION DECODER -- stored blob back to the asset-analysis snapshot
# ============================================================
# FILE: ai/price_evolution_decoder.py
#
# Two sources, most complete first:
#
#   full_analysis_z / full_analysis   the lossless snapshot. Every field, list
#                                      and detector block comes back exactly.
#   field codes (schema_version 3)    when a blob carries no payload, the
#                                      scalars the codes name, rebuilt at their
#                                      snapshot paths and labelled
#                                      `_decoded_from: "field_codes"` so no reader
#                                      mistakes the skeleton for the whole thing.
#
# What decode never does is invent. `timestamp`, `success` and `model_version`
# are returned only when the analysis asserted them; the encode time comes back
# as `encoded_at`, named for what it is.
#
# Rebuilt 2026-09-17. The previous decoder turned short codes back into the
# pre-grouping layout (components 1_trend_bias..8_indicators, lot_result, gnn,
# pattern_analysis ...): a snapshot that no longer exists, with defaults filled
# in wherever the old codes had nothing to say. Blobs written with those codes
# and no payload are not decoded -- MongoDB holds none, and returning the old
# layout would hand every reader a confident, wrong analysis.
# ============================================================

from __future__ import annotations

import base64
import json
import logging
import zlib
from typing import Any, Dict

from .price_evolution_encoder import PriceEvolutionEncoder
from .price_evolution_maps import SCHEMA_NAME, SCHEMA_VERSION, EvolutionMaps

logger = logging.getLogger(__name__)


class PriceEvolutionDecoder:
    """Decode an encoded blob back into the asset-analysis snapshot it came from."""

    def __init__(self):
        self.maps = EvolutionMaps()
        self.encoder = PriceEvolutionEncoder()

    def encode_price_evolution(self, payload: Any, timeframe: str = "M1", position: Dict = None) -> Dict[str, Any]:
        """Compatibility wrapper for encoding a full asset analysis or price-history payload."""
        return self.encoder.encode_price_evolution(payload, timeframe, position)

    def decode_price_evolution(self, encoded: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility wrapper for decoding a previously encoded payload."""
        return self.decode(encoded)

    def decode(self, compressed: Dict[str, Any]) -> Dict[str, Any]:
        """Decode one blob. Returns {} for anything that is not a decodable blob."""
        if not isinstance(compressed, dict) or not compressed:
            return {}

        # A price point's analysis block: {"m1": <blob>, ..., "_encoded": True}.
        if compressed.get("_encoded") is True:
            result = compressed.copy()
            if "analysis" in compressed:
                encoded_analysis = compressed.get("analysis", {}) or {}
                result["analysis"] = {
                    tf: self.decode(encoded_analysis.get(tf, {}))
                    for tf in ("m1", "m5", "h1")
                }
            return result

        if compressed.get("analysis_type") == "price_history":
            return dict(compressed)

        if compressed.get("analysis_schema") != SCHEMA_NAME:
            return {}

        if "full_analysis_z" in compressed or "full_analysis" in compressed:
            payload = self._payload(compressed)
            if isinstance(payload, dict):
                self._provenance(payload, compressed)
            return payload

        if int(compressed.get("schema_version") or 0) >= SCHEMA_VERSION:
            payload = self.maps.decode_fields(compressed)
            payload["_decoded_from"] = "field_codes"
            self._provenance(payload, compressed)
            return payload

        logger.debug("[DECODER] pre-v3 blob without a payload -- not decodable to the current snapshot")
        return {}

    # ------------------------------------------------------------------ helpers
    def _payload(self, compressed: Dict[str, Any]) -> Any:
        """The lossless snapshot: compressed form preferred, plain copy as fallback."""
        source = compressed.get("full_analysis")
        packed = compressed.get("full_analysis_z")
        if packed:
            try:
                source = json.loads(zlib.decompress(base64.b64decode(packed)).decode("utf-8"))
            except Exception:
                # A corrupt blob must not masquerade as an analysis: fall back to
                # the plain copy if the row has one, otherwise visibly empty.
                source = compressed.get("full_analysis")
        return self.maps.make_json_safe(source or {})

    @staticmethod
    def _provenance(payload: Dict[str, Any], compressed: Dict[str, Any]) -> None:
        """Surface only what the analysis itself recorded; label the encode time."""
        if compressed.get("ts") is not None:
            payload.setdefault("timestamp", compressed["ts"])
        elif compressed.get("t") is not None and "timestamp" not in payload:
            payload.setdefault("encoded_at", compressed["t"])
        if compressed.get("scs") is not None:
            payload.setdefault("success", bool(compressed["scs"]))
        if compressed.get("mv") is not None:
            payload.setdefault("model_version", compressed["mv"])
