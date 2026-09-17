# ============================================================
# RESULT LEAVES -- one flat view of an analysis result
# ============================================================
# FILE: core/result_leaves.py
#
# The price-history study stores every analysis as flat leaves
# ("indicators.support_resistance.recommendation" -> "SUPPORT_BUY"), and the
# calibrated model and the component rules are fitted on those leaves. The
# live engine must score exactly the same view, so both call this module:
#
#   full_leaves(result)          dict leaves, list lengths, first two list items
#   model_row(result, edges)     the leaves plus the context columns the study
#                                adds (edges.*, ctx.regime, close, atr, pip)
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

MAX_FULL_LEAVES = 4000
FULL_SKIP_KEYS = {"decision_snapshot", "probability_ledger", "ledger", "reasons", "reason", "description",
                  "explanation", "note", "legend", "stop_hunt_legend", "summary", "contributions",
                  "account_info", "position_management", "config", "calibrated_decision"}
_EMOJI_PREFIXES = ("🎯", "💰", "🛑", "⭐", "🚀", "📊", "📈", "💵")


def full_leaves(node: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None, depth: int = 0) -> Dict[str, Any]:
    out = {} if out is None else out
    if len(out) >= MAX_FULL_LEAVES or depth > 8:
        return out
    if isinstance(node, Mapping):
        for k, v in node.items():
            if str(k) in FULL_SKIP_KEYS or str(k).startswith(_EMOJI_PREFIXES):
                continue
            full_leaves(v, f"{prefix}.{k}" if prefix else str(k), out, depth + 1)
    elif isinstance(node, (list, tuple)):
        out[f"{prefix}.len"] = len(node)
        for i, item in enumerate(node[:2]):
            full_leaves(item, f"{prefix}[{i}]", out, depth + 1)
    elif isinstance(node, bool):
        out[prefix] = int(node)
    elif isinstance(node, (int, float)) or type(node).__name__ in ("float64", "float32", "int64", "int32"):
        try:
            v = float(node)
        except (TypeError, ValueError):
            return out
        if math.isfinite(v):
            out[prefix] = round(v, 7)
    elif isinstance(node, str) and len(node) <= 40:
        out[prefix] = node
    return out


def model_row(result: Mapping[str, Any], edges: Optional[Mapping[str, Any]] = None,
              close: Optional[float] = None, pip: Optional[float] = None) -> Dict[str, Any]:
    """The row shape ai/component_repair.py builds from a study record."""
    row: Dict[str, Any] = dict(full_leaves(result))
    # A grouped payload files readings under analysis.<GROUP>.data.*
    # (core/analysis_groups.py). The model and the component rules were fitted
    # on the flat names, so both spellings are in the row: the study stores the
    # new ones, the rules keep resolving.
    from core.analysis_groups import legacy_paths, resolve
    for legacy in legacy_paths():
        new = resolve(legacy)
        prefix = new + "."
        for key in [k for k in row if k.startswith(prefix)]:
            row.setdefault(legacy + key[len(new):], row[key])
    vp = result.get("volatility_protection") or {}
    row["atr_pips"] = vp.get("atr_pips")
    row["close"] = close
    row["pip"] = pip
    row["ctx.regime"] = (vp.get("trading_regime") or {}).get("state")
    row["ctx.symbol"] = (result.get("config") or {}).get("symbol")
    for k, v in (edges or {}).items():
        if k != "version":
            row[f"edges.{k}"] = v
    return row


def get_status() -> Dict[str, Any]:
    return {"component": "result_leaves", "max_leaves": MAX_FULL_LEAVES}
