# ============================================================
# ENGINE VERSION -- which engine produced a stored record
# ============================================================
# FILE: core/engine_version.py
#
# strategic_plan_v5_live_data.md, rule 2: never pool records produced by
# different engines. The sizing change of 2026-09-17 (USE_MARKET_STOP off) is
# exactly such a change -- a trade sized by the market stop and one sized by the
# original margin-first rule are not samples of the same thing.
#
# engine_stamp() describes the process that is running:
#   git_commit    the checked-out commit when the process started
#   code_hash     hash of the decision-making source files AS LOADED, so work
#                 that was never committed still separates one era from another
#   config        the switches that change what gets traded
#   fingerprint   hash of code_hash + config: equal fingerprints may be pooled
#
# Computed once per process, because a running process keeps the code and the
# config it started with until it is restarted.
# ============================================================

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ENGINE_STAMP_VERSION = 1
_ROOT = Path(__file__).resolve().parents[1]

# The modules whose code decides direction, entry, stop, target and size.
DECISION_SOURCES = (
    "core/asset_analysis.py",
    "core/asset_analysis_config.py",
    "core/strategy_groups.py",
    "core/state_readings.py",
    "core/analysis_groups.py",
    "core/calibrated_model.py",
    "core/calibrated_model.json",
    "core/execution.py",
    "core/market_stop.py",
    "core/discount_engine.py",
)

_STAMP: Optional[Dict[str, Any]] = None


def _git_commit() -> Optional[str]:
    """The checked-out commit, read from .git without running git."""
    for base in (_ROOT, *_ROOT.parents):
        head = base / ".git" / "HEAD"
        if not head.exists():
            continue
        try:
            ref = head.read_text(encoding="utf-8").strip()
            if not ref.startswith("ref:"):
                return ref[:12]
            ref_path = ref.split(" ", 1)[1].strip()
            loose = base / ".git" / ref_path
            if loose.exists():
                return loose.read_text(encoding="utf-8").strip()[:12]
            packed = base / ".git" / "packed-refs"
            if packed.exists():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(ref_path):
                        return line.split(" ", 1)[0][:12]
        except Exception as exc:  # recording only, never fatal
            logger.debug("git commit unreadable: %s", exc)
        return None
    return None


def _code_hash() -> str:
    digest = hashlib.sha1()
    for rel in DECISION_SOURCES:
        path = _ROOT / rel
        digest.update(rel.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()[:12]


def _config() -> Dict[str, Any]:
    from core import asset_analysis_config as cfg
    from core import strategy_groups as sg

    config: Dict[str, Any] = {
        "use_market_stop": cfg.USE_MARKET_STOP,
        "use_calibrated_probability": cfg.USE_CALIBRATED_PROBABILITY,
        "use_strategy_group_probability": getattr(cfg, "USE_STRATEGY_GROUP_PROBABILITY", None),
        "strategy_group_min_probability": getattr(cfg, "STRATEGY_GROUP_MIN_PROBABILITY", None),
        "trade_probability_minimum": getattr(cfg, "TRADE_PROBABILITY_MINIMUM", None),
        "max_risk_per_trade": cfg.MAX_RISK_PER_TRADE,
        "strategy_groups_version": sg.STRATEGY_GROUPS_VERSION,
        "opposition_weight": sg.OPPOSITION_WEIGHT,
        "measured_empty_groups": list(sg.MEASURED_EMPTY_GROUPS),
    }
    try:
        model = json.loads((_ROOT / "core" / "calibrated_model.json").read_text(encoding="utf-8"))
        config["calibrated_model"] = {k: model.get(k) for k in
                                      ("version", "decision_mode", "entry_floor",
                                       "model_decides_direction", "max_cost_r")}
    except Exception:
        config["calibrated_model"] = None
    try:
        from ai.price_evolution_maps import SCHEMA_VERSION
        config["codec_schema"] = SCHEMA_VERSION
    except Exception:
        config["codec_schema"] = None
    return config


def engine_stamp() -> Dict[str, Any]:
    """The stamp for this process (computed once)."""
    global _STAMP
    if _STAMP is None:
        try:
            config = _config()
        except Exception as exc:
            logger.warning("engine config unreadable for the stamp: %s", exc)
            config = {"error": str(exc)}
        code = _code_hash()
        fingerprint = hashlib.sha1(
            json.dumps({"code": code, "config": config}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        _STAMP = {"stamp_version": ENGINE_STAMP_VERSION, "git_commit": _git_commit(),
                  "code_hash": code, "config": config, "fingerprint": fingerprint}
    return _STAMP


def short_stamp() -> Dict[str, Any]:
    """What goes on every record: enough to join to the full stamp."""
    stamp = engine_stamp()
    return {"fingerprint": stamp["fingerprint"], "git_commit": stamp["git_commit"]}


def register(collection=None) -> bool:
    """Store the full stamp once per fingerprint in `engine_versions`. Never raises."""
    try:
        stamp = engine_stamp()
        if collection is None:
            from core.mongo import get_trades_service
            service = get_trades_service()
            collection = service.client[service.config.database]["engine_versions"]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        collection.update_one({"fingerprint": stamp["fingerprint"]},
                              {"$setOnInsert": {**stamp, "first_seen": now},
                               "$set": {"last_seen": now}}, upsert=True)
        return True
    except Exception as exc:
        logger.debug("engine stamp not registered: %s", exc)
        return False


def reset_for_tests() -> None:
    global _STAMP
    _STAMP = None


def get_status() -> Dict[str, Any]:
    return {"component": "engine_version", **short_stamp()}
