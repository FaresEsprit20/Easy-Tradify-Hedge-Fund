# ============================================================
# MONGO PACKAGE -- TRADES STORAGE ONLY
# ============================================================
# FILE: core/mongo/__init__.py
#
# Scope is deliberately narrow: the `trades` collection, and nothing else.
# portfolio_config, ai_models and the rest stay in Firestore. A migration
# that moves everything at once has no safe rollback; moving one collection
# behind an unchanged service interface does.
#
# Why trades specifically -- these are the constraints that forced it, all
# measured on live documents rather than assumed:
#
#   * Firestore caps a document at 1 MiB. One price-evolution point carrying
#     the analysis snapshot measured ~370KB, so a trade document was full
#     after two points. A trade needs ~180 (one per minute over its life).
#     MongoDB's limit is 16 MB, which holds a whole trade -- ~180 points at
#     ~20KB is ~3.6 MB -- as ONE document.
#   * Firestore has no server-side array append, so adding point N meant
#     reading and rewriting all N. `$push` is atomic and O(1).
#   * Every analytical query this project runs (group by ledger step, bucket
#     by R multiple) is an aggregation. Firestore cannot express them and
#     needed a composite index per query shape; `get_closed_trades` was
#     already silently returning [] when one was missing.
# ============================================================

from .mongo_config import (
    MongoConfig,
    get_mongo_config,
)

from .portfolio_service import (
    PortfolioMongoService,
    get_portfolio_service,
)
from .trades_service import (
    TradesService,
    get_trades_service,
    DeleteMode,
    TradeNotFound,
    TradeValidationError,
    TradeStorageError,
)

__all__ = [
    "MongoConfig",
    "get_mongo_config",
    "TradesService",
    "get_trades_service",
    "DeleteMode",
    "TradeNotFound",
    "TradeValidationError",
    "TradeStorageError",
]
