# ============================================================
# PORTFOLIO SERVICE -- MONGODB
# ============================================================
# FILE: core/mongo/portfolio_service.py
# ============================================================

import logging
from typing import Any, Dict, Optional
from .mongo_config import get_mongo_config, MongoConfig

logger = logging.getLogger(__name__)

class PortfolioMongoService:
    """CRUD for portfolio data in MongoDB."""

    def __init__(self, config: Optional[MongoConfig] = None):
        self.config = config or get_mongo_config()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from pymongo import MongoClient
            self._client = MongoClient(self.config.uri, **self.config.client_kwargs())
        return self._client

    def get_collection(self, collection_name: str):
        return self.client[self.config.database][collection_name]

    def save_config(self, config_data: Dict[str, Any]):
        self.get_collection("portfolio_config").replace_one(
            {"_id": "current"}, config_data, upsert=True
        )

    def load_config(self) -> Optional[Dict[str, Any]]:
        return self.get_collection("portfolio_config").find_one({"_id": "current"})

    def save_stats(self, collection_name: str, doc_id: str, stats_data: Dict[str, Any]):
        self.get_collection(collection_name).replace_one(
            {"_id": doc_id}, stats_data, upsert=True
        )

    def load_stats(self, collection_name: str, doc_id: str) -> Optional[Dict[str, Any]]:
        return self.get_collection(collection_name).find_one({"_id": doc_id})

_portfolio_service = None

def get_portfolio_service() -> PortfolioMongoService:
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = PortfolioMongoService()
    return _portfolio_service
