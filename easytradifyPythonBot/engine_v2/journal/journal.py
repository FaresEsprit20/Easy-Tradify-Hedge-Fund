"""Setup journal: every setup (proposed, taken, skipped, expired) with its thesis and outcome.

JSONL always; MongoDB collection `v2_setups` when V2_JOURNAL_MONGO is True (uses core/mongo config).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

V2_JOURNAL_MONGO = False
LIVE_JOURNAL = Path(__file__).resolve().parents[2] / "reports" / "v2" / "live_journal.jsonl"


def record(setup, event: str, extra: dict | None = None, path: Path = LIVE_JOURNAL) -> dict:
    doc = {"logged_at": int(time.time()), "event": event, "setup": setup.to_dict(), **(extra or {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(doc, default=str) + "\n")
    if V2_JOURNAL_MONGO:
        try:
            from core.mongo.mongo_config import get_database  # type: ignore
            get_database()["v2_setups"].insert_one(dict(doc))
        except Exception:
            pass
    return doc
