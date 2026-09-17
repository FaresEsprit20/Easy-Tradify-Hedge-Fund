# ============================================================
# MONGO CONFIGURATION -- CONNECTION, POOLING, TIMEOUTS
# ============================================================
# FILE: core/mongo/mongo_config.py
#
# One place that knows how to reach MongoDB, so no other module builds a
# client or hardcodes a URI.
#
# SECRETS
# -------
# The URI carries credentials when one is used. Nothing here logs, prints or
# returns it unredacted: `safe_uri` is what goes in a log line and what a
# status endpoint may publish. A connection string in a log file is a leaked
# password, and log files get pasted into issues.
#
# FAIL BEHAVIOUR
# --------------
# Connecting is LAZY and never raises at import: a trading process must start
# and report a degraded database rather than refuse to boot. `is_healthy()`
# says whether the server actually answered, and it is checked rather than
# assumed -- pymongo constructs a MongoClient without contacting the server,
# so a client object is not evidence of a working database.
# ============================================================

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_URI = "mongodb://localhost:27017"
DEFAULT_DB = "easytradify"
DEFAULT_COLLECTION = "trades"
DEFAULT_ARCHIVE_COLLECTION = "trades_archive"

# MongoDB's hard per-document ceiling. Trades are checked against it before
# writing rather than after, because the failure mode on the other side is an
# append that silently stops working -- which is exactly what happened on
# Firestore's 1 MiB limit and went unnoticed for the life of every trade.
MONGO_MAX_DOCUMENT_BYTES = 16 * 1024 * 1024

# Leave headroom so a document nearing the ceiling is reported as a problem
# while it is still writable, instead of at the moment it stops being one.
DOCUMENT_SIZE_WARN_RATIO = 0.80


def _redact(uri: str) -> str:
    """A URI safe to log: credentials replaced, host and database kept."""
    if not uri:
        return ""
    # mongodb://user:pass@host/db  ->  mongodb://***:***@host/db
    return re.sub(r"://[^/@]*@", "://***:***@", uri)


@dataclass
class MongoConfig:
    """Everything needed to open a connection, and nothing that isn't."""

    uri: str = field(default_factory=lambda: os.getenv("MONGO_URI", DEFAULT_URI))
    database: str = field(default_factory=lambda: os.getenv("MONGO_DB", DEFAULT_DB))
    collection: str = field(
        default_factory=lambda: os.getenv("MONGO_TRADES_COLLECTION", DEFAULT_COLLECTION))
    archive_collection: str = field(
        default_factory=lambda: os.getenv("MONGO_TRADES_ARCHIVE_COLLECTION",
                                          DEFAULT_ARCHIVE_COLLECTION))

    # Timeouts. Every one of these is deliberately SHORT: this client is used
    # from the position-monitor loop, and a database that has gone away must
    # surface as an error in seconds rather than blocking the thread that has
    # to keep up with the market.
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 5000
    socket_timeout_ms: int = 20000

    # Pooling. The monitor writes from several threads (position monitor,
    # fast-entry, main loop), so a pool is required; the ceiling keeps a
    # runaway loop from exhausting server connections.
    max_pool_size: int = 50
    min_pool_size: int = 0

    # w="majority" + journal: a trade record is money. Acknowledged-and-lost
    # is not an acceptable outcome for the one artefact that says what the
    # system did.
    write_concern: str = "majority"
    journal: bool = True

    # Reads may lag a primary failover; for analytics that is fine, and for
    # correctness-critical reads the service asks for primary explicitly.
    read_preference: str = "primaryPreferred"

    @property
    def safe_uri(self) -> str:
        """The URI with credentials removed -- the only form fit to log."""
        return _redact(self.uri)

    def to_dict(self) -> Dict[str, Any]:
        """Publishable configuration. Never includes the raw URI."""
        return {
            "uri": self.safe_uri,
            "database": self.database,
            "collection": self.collection,
            "archive_collection": self.archive_collection,
            "server_selection_timeout_ms": self.server_selection_timeout_ms,
            "connect_timeout_ms": self.connect_timeout_ms,
            "socket_timeout_ms": self.socket_timeout_ms,
            "max_pool_size": self.max_pool_size,
            "write_concern": self.write_concern,
            "journal": self.journal,
            "read_preference": self.read_preference,
            "max_document_bytes": MONGO_MAX_DOCUMENT_BYTES,
        }

    def client_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for pymongo.MongoClient."""
        return {
            "serverSelectionTimeoutMS": self.server_selection_timeout_ms,
            "connectTimeoutMS": self.connect_timeout_ms,
            "socketTimeoutMS": self.socket_timeout_ms,
            "maxPoolSize": self.max_pool_size,
            "minPoolSize": self.min_pool_size,
            "w": self.write_concern,
            "journal": self.journal,
            "appname": "easytradify",
            "retryWrites": True,
            "tz_aware": True,
        }


_CONFIG: Optional[MongoConfig] = None
_CONFIG_LOCK = threading.Lock()


def get_mongo_config(refresh: bool = False) -> MongoConfig:
    """
    The process-wide Mongo configuration.

    Cached because it reads the environment, and a value that changes
    underneath a running monitor would mean two threads writing to different
    databases with no indication that they had diverged.
    """
    global _CONFIG
    with _CONFIG_LOCK:
        if _CONFIG is None or refresh:
            _CONFIG = MongoConfig()
            logger.info("Mongo configured: %s db=%s collection=%s",
                        _CONFIG.safe_uri, _CONFIG.database, _CONFIG.collection)
        return _CONFIG
