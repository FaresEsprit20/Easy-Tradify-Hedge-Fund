# core/firebase/__init__.py
# ============================================================
# FIREBASE PACKAGE INITIALIZATION
# ============================================================

from .firebase_service import FirebaseService, get_firebase_service
from .firebase_config import FirebaseConfig

__all__ = [
    'FirebaseService',
    'get_firebase_service',
    'FirebaseConfig',
    'TradeData',
    'TradeEntry',
    'StopLoss',
    'TakeProfit',
    'CloseDetails',
    'PriceUpdate',
    'Modification'
]