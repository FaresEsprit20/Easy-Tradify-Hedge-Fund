# core/news_veto.py
"""
News Impact Veto System - Multi-API with Batch Processing & Efficient Caching
"""

import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from threading import Lock, Thread
import logging
import random
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================================
# MULTI-API CONFIGURATION - FREE TIERS
# ============================================================
APIS = {
    "forexfactory": {
        "url": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "backup": "https://nfs.faireconomy.media/ff_calendar_today.json",
        "timeout": 10,
        "weight": 1.0
    },
    "fmp": {
        "url": "https://financialmodelingprep.com/api/v3/economic_calendar",
        "params": {"apikey": "demo"},  # Limited but works
        "timeout": 10,
        "weight": 0.8
    },
    "alphavantage": {
        "url": "https://www.alphavantage.co/query",
        "params": {"function": "NEWS_SENTIMENT", "apikey": "demo"},
        "timeout": 10,
        "weight": 0.6
    },
    "marketaux": {
        "url": "https://api.marketaux.com/v1/news/all",
        "params": {"api_token": "demo", "limit": 50},
        "timeout": 10,
        "weight": 0.5
    }
}

# ============================================================
# AGGRESSIVE RATE LIMITING & CACHING
# ============================================================
MIN_REQUEST_INTERVAL = 60  # 1 minute minimum between requests
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 5.0

# Cache TTL
CACHE_TTL_SECONDS = 1800  # 30 minutes (reduced from 1 hour for freshness)

# Batch update interval
BATCH_UPDATE_INTERVAL = 900  # 15 minutes


class NewsEvent:
    """Structured news event object."""
    def __init__(self, data: Dict):
        self.name = data.get("name", data.get("title", "Unknown Event"))
        self.currency = data.get("currency", "USD")
        self.impact = data.get("impact", "LOW").upper()
        self.datetime = data.get("datetime")
        self.minutes_until = data.get("minutes_until", 999)
        self.actual = data.get("actual")
        self.forecast = data.get("forecast")
        self.previous = data.get("previous")
        self.country = data.get("country", "")
        self.event_type = data.get("event_type", data.get("type", ""))
        self.source = data.get("source", "unknown")
        self.confidence = data.get("confidence", 0.5)
        self.importance = self._calculate_importance()
    
    def _calculate_importance(self) -> float:
        """Calculate importance score (0-1)."""
        base = 0.5
        if self.impact == "HIGH":
            base += 0.4
        elif self.impact == "MEDIUM":
            base += 0.2
        
        # Boost based on confidence
        base *= (0.8 + 0.4 * self.confidence)
        
        # Boost for certain event types
        high_impact_types = ["FOMC", "NFP", "CPI", "PPI", "GDP", "Unemployment", "Retail Sales", "PMI"]
        for ht in high_impact_types:
            if ht in self.name or ht in self.event_type:
                base = min(1.0, base + 0.2)
                break
        
        return min(1.0, base)


class NewsCache:
    """
    Thread-safe multi-API news cache with batch processing.
    """
    
    def __init__(self, cache_ttl_seconds: int = CACHE_TTL_SECONDS):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, List[NewsEvent]] = {}
        self._cache_timestamp: Dict[str, float] = {}
        self._last_fetch_time = 0
        self._lock = Lock()
        self._is_refreshing = False
        self._refresh_thread = None
        self._consecutive_failures = 0
        self._is_startup = True
        self._batched_symbols: List[str] = []
        self._last_batch_update = 0
        
        # Expanded currency mapping
        self.watched_currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNY", "HKD", "SGD", "INR"]
        
        # Symbol to currency mapping (expanded)
        self.symbol_currency_map = {
            # Metals
            "XAUUSD": "USD", "XAGUSD": "USD", "XAUEUR": "EUR", "XAGEUR": "EUR", "XAUJPY": "JPY", "XAGJPY": "JPY",
            # Forex majors
            "EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "USD", "USDCAD": "USD",
            "AUDUSD": "AUD", "NZDUSD": "NZD", "USDCHF": "USD",
            # Forex crosses
            "EURGBP": "EUR", "EURJPY": "EUR", "GBPJPY": "GBP", "AUDJPY": "AUD",
            "EURCAD": "EUR", "GBPAUD": "GBP", "GBPCAD": "GBP", "AUDCAD": "AUD",
            # Indices
            "SPX500": "USD", "NAS100": "USD", "US30": "USD", "DAX40": "EUR",
            "FTSE100": "GBP", "CAC40": "EUR", "ASX200": "AUD", "NIKKEI225": "JPY",
            "HK50": "HKD", "STOXX50": "EUR",
            # Commodities
            "USOIL": "USD", "UKOIL": "USD", "BRENT": "USD", "WTI": "USD",
            # Stocks - NASDAQ
            "AAPL": "USD", "MSFT": "USD", "GOOGL": "USD", "AMZN": "USD",
            "NVDA": "USD", "META": "USD", "TSLA": "USD", "AMD": "USD",
            "INTC": "USD", "CSCO": "USD", "ORCL": "USD", "IBM": "USD",
            "QCOM": "USD", "MU": "USD", "PLTR": "USD", "SNOW": "USD",
            "UBER": "USD", "PYPL": "USD",
            # Stocks - NYSE
            "JNJ": "USD", "PFE": "USD", "MRK": "USD", "ABBV": "USD",
            "GILD": "USD", "MRNA": "USD", "WMT": "USD", "MCD": "USD",
            "SBUX": "USD", "DIS": "USD", "KO": "USD", "XOM": "USD",
            "CVX": "USD", "GE": "USD", "JPM": "USD", "MA": "USD",
            "AXP": "USD", "V": "USD", "BAC": "USD", "WFC": "USD",
            # ETFs
            "SPY": "USD", "QQQ": "USD", "SMH": "USD", "GLD": "USD",
            "SLV": "USD", "USO": "USD", "VTI": "USD"
        }
        
        # Country to currency mapping
        self.country_currency_map = {
            "UNITED STATES": "USD", "US": "USD", "USA": "USD", "AMERICA": "USD",
            "UNITED KINGDOM": "GBP", "UK": "GBP", "ENGLAND": "GBP", "BRITAIN": "GBP",
            "EUROPEAN UNION": "EUR", "EUROPE": "EUR", "GERMANY": "EUR", "FRANCE": "EUR", "ITALY": "EUR", "SPAIN": "EUR",
            "JAPAN": "JPY", "AUSTRALIA": "AUD", "CANADA": "CAD", "SWITZERLAND": "CHF",
            "NEW ZEALAND": "NZD", "CHINA": "CNY", "HONG KONG": "HKD", "SINGAPORE": "SGD",
            "INDIA": "INR", "SOUTH KOREA": "KRW", "BRAZIL": "BRL", "RUSSIA": "RUB"
        }
        
        # Impact mapping
        self.impact_mapping = {
            "high": "HIGH", "medium": "MEDIUM", "low": "LOW",
            "High": "HIGH", "Medium": "MEDIUM", "Low": "LOW",
            "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW",
            "1": "HIGH", "2": "MEDIUM", "3": "LOW",
            "red": "HIGH", "orange": "MEDIUM", "yellow": "LOW"
        }
        
        logger.info("✅ NewsCache initialized with multi-API support")
        logger.info(f"   {len(self.symbol_currency_map)} symbols mapped")
        logger.info(f"   {len(self.watched_currencies)} currencies watched")
        logger.info(f"   Cache TTL: {cache_ttl_seconds/60:.0f} minutes")
    
    def _get_symbol_currency(self, symbol: str) -> str:
        """Get currency for a symbol with fallback."""
        symbol_upper = symbol.upper()
        
        # Direct match
        if symbol_upper in self.symbol_currency_map:
            return self.symbol_currency_map[symbol_upper]
        
        # Check for partial matches
        for key, currency in self.symbol_currency_map.items():
            if key in symbol_upper or symbol_upper in key:
                return currency
        
        # Default to USD for unknown symbols
        logger.debug(f"[NEWS] No currency mapping for {symbol}, using USD")
        return "USD"
    
    def _parse_event_datetime(self, event: Dict) -> Optional[datetime]:
        """Parse datetime from various formats."""
        date_str = event.get("date", event.get("datetime", event.get("time", "")))
        time_str = event.get("time", event.get("event_time", ""))
        
        if not date_str:
            return None
        
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%Y%m%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        
        combined = f"{date_str} {time_str}".strip()
        
        for fmt in formats:
            try:
                return datetime.strptime(combined, fmt)
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(date_str, fmt)
                except (ValueError, TypeError):
                    continue
        
        logger.debug(f"[NEWS] Could not parse datetime: {combined}")
        return None
    
    def _parse_events_from_api(self, data: Any, source: str) -> List[NewsEvent]:
        """Parse events from various API response formats."""
        events = []
        
        # If data is a single event dict, wrap it
        if isinstance(data, dict) and not any(isinstance(v, list) for v in data.values()):
            data = [data]
        
        # If data is a list of events
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                events.append(self._parse_single_event(item, source))
        # If data is a dict with event list
        elif isinstance(data, dict):
            # Try common keys
            for key in ["events", "data", "calendar", "items", "event_list", "news", "articles", "results"]:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        if isinstance(item, dict):
                            events.append(self._parse_single_event(item, source))
                    break
            else:
                # Try any list in the dict
                for key, value in data.items():
                    if isinstance(value, list) and len(value) > 0:
                        if isinstance(value[0], dict):
                            if any(k in value[0] for k in ["date", "currency", "impact", "title", "name", "headline"]):
                                for item in value:
                                    events.append(self._parse_single_event(item, source))
                                break
        
        return events
    
    def _parse_single_event(self, item: Dict, source: str) -> NewsEvent:
        """Parse a single event from any API format."""
        # Extract name
        name = item.get("name", item.get("title", item.get("headline", item.get("description", "Unknown Event"))))
        
        # Extract currency
        currency = item.get("currency", "")
        if not currency:
            currency = item.get("ccy", "")
        if not currency:
            currency = item.get("country", "")
            currency = self.country_currency_map.get(currency.upper(), "USD")
        if not currency:
            currency = "USD"
        currency = currency.upper()
        
        # Extract impact
        impact = item.get("impact", item.get("importance", item.get("severity", "LOW")))
        impact = self.impact_mapping.get(str(impact).lower(), "LOW")
        
        # Extract datetime
        dt = self._parse_event_datetime(item)
        
        # Calculate minutes until
        minutes_until = 999
        if dt:
            delta = dt - datetime.now()
            minutes_until = max(0, delta.total_seconds() / 60)
        
        # Build event data
        event_data = {
            "name": name,
            "currency": currency,
            "impact": impact,
            "datetime": dt.isoformat() if dt else None,
            "minutes_until": minutes_until,
            "actual": item.get("actual"),
            "forecast": item.get("forecast", item.get("estimate", item.get("expected"))),
            "previous": item.get("previous", item.get("prior")),
            "country": item.get("country", ""),
            "event_type": item.get("type", item.get("category", "")),
            "source": source,
            "confidence": self._calculate_event_confidence(item, source)
        }
        
        return NewsEvent(event_data)
    
    def _calculate_event_confidence(self, item: Dict, source: str) -> float:
        """Calculate confidence in an event."""
        confidence = 0.5
        
        # Boost based on source
        source_confidence = {
            "forexfactory": 0.9,
            "fmp": 0.7,
            "alphavantage": 0.6,
            "marketaux": 0.5
        }
        confidence += source_confidence.get(source, 0.4)
        
        # Boost if multiple fields are filled
        fields = ["date", "time", "currency", "impact", "actual", "forecast", "previous"]
        filled = sum(1 for f in fields if item.get(f))
        confidence += (filled / len(fields)) * 0.3
        
        return min(1.0, confidence)
    
    def _fetch_from_api(self, api_name: str) -> List[NewsEvent]:
        """Fetch events from a specific API."""
        api_config = APIS.get(api_name)
        if not api_config:
            return []
        
        try:
            url = api_config["url"]
            params = api_config.get("params", {})
            timeout = api_config.get("timeout", 10)
            
            response = requests.get(url, params=params, timeout=timeout, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache'
            })
            
            if response.status_code == 429:
                logger.warning(f"[NEWS] Rate limited on {api_name}")
                return []
            
            if response.status_code != 200:
                logger.debug(f"[NEWS] {api_name} returned {response.status_code}")
                return []
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.debug(f"[NEWS] Invalid JSON from {api_name}")
                return []
            
            events = self._parse_events_from_api(data, api_name)
            
            if events:
                logger.info(f"[NEWS] {api_name}: found {len(events)} events")
            else:
                logger.debug(f"[NEWS] {api_name}: no events found")
            
            return events
            
        except requests.exceptions.Timeout:
            logger.debug(f"[NEWS] {api_name} timeout")
        except requests.exceptions.RequestException as e:
            logger.debug(f"[NEWS] {api_name} request error: {e}")
        except Exception as e:
            logger.debug(f"[NEWS] {api_name} error: {e}")
        
        return []
    
    def _batch_fetch_all_events(self) -> Dict[str, List[NewsEvent]]:
        """Fetch events from ALL APIs in batch."""
        all_events_by_currency = {c: [] for c in self.watched_currencies}
        all_events = []
        
        # Try each API
        for api_name in APIS.keys():
            try:
                events = self._fetch_from_api(api_name)
                all_events.extend(events)
                
                # Add to currency buckets
                for event in events:
                    if event.currency in all_events_by_currency:
                        all_events_by_currency[event.currency].append(event)
            except Exception as e:
                logger.debug(f"[NEWS] API {api_name} failed: {e}")
        
        # Log results
        total_events = sum(len(events) for events in all_events_by_currency.values())
        
        if total_events == 0:
            logger.warning("[NEWS] No events found from any API")
            # Use fallback mock data
            return self._get_fallback_events()
        
        # Sort events by time
        for currency in all_events_by_currency:
            all_events_by_currency[currency] = sorted(
                all_events_by_currency[currency],
                key=lambda x: x.minutes_until
            )
        
        # Log high impact events
        high_impact_count = 0
        for currency, events in all_events_by_currency.items():
            for e in events:
                if e.impact == "HIGH" and e.minutes_until < 120:
                    high_impact_count += 1
                    logger.info(f"  🔴 {e.name} ({e.currency}) in {e.minutes_until:.0f} min [source: {e.source}]")
        
        if high_impact_count > 0:
            logger.info(f"[NEWS] Found {high_impact_count} HIGH impact events upcoming")
        
        return all_events_by_currency
    
    def _get_fallback_events(self) -> Dict[str, List[NewsEvent]]:
        """Return fallback mock events when APIs fail."""
        logger.info("[NEWS] Using fallback mock data")
        
        now = datetime.now()
        fallback_events = {
            "USD": [
                NewsEvent({
                    "name": "FOMC Meeting Minutes",
                    "currency": "USD",
                    "impact": "HIGH",
                    "datetime": (now + timedelta(hours=2)).isoformat(),
                    "minutes_until": 120,
                    "source": "fallback"
                }),
                NewsEvent({
                    "name": "Initial Jobless Claims",
                    "currency": "USD",
                    "impact": "MEDIUM",
                    "datetime": (now + timedelta(hours=3)).isoformat(),
                    "minutes_until": 180,
                    "source": "fallback"
                }),
                NewsEvent({
                    "name": "Fed Rate Decision",
                    "currency": "USD",
                    "impact": "HIGH",
                    "datetime": (now + timedelta(hours=24)).isoformat(),
                    "minutes_until": 1440,
                    "source": "fallback"
                })
            ],
            "EUR": [
                NewsEvent({
                    "name": "ECB Interest Rate Decision",
                    "currency": "EUR",
                    "impact": "HIGH",
                    "datetime": (now + timedelta(hours=4)).isoformat(),
                    "minutes_until": 240,
                    "source": "fallback"
                }),
                NewsEvent({
                    "name": "German GDP",
                    "currency": "EUR",
                    "impact": "MEDIUM",
                    "datetime": (now + timedelta(hours=5)).isoformat(),
                    "minutes_until": 300,
                    "source": "fallback"
                })
            ],
            "GBP": [
                NewsEvent({
                    "name": "BOE Interest Rate Decision",
                    "currency": "GBP",
                    "impact": "HIGH",
                    "datetime": (now + timedelta(hours=6)).isoformat(),
                    "minutes_until": 360,
                    "source": "fallback"
                })
            ],
            "JPY": [
                NewsEvent({
                    "name": "BOJ Interest Rate Decision",
                    "currency": "JPY",
                    "impact": "HIGH",
                    "datetime": (now + timedelta(hours=8)).isoformat(),
                    "minutes_until": 480,
                    "source": "fallback"
                })
            ]
        }
        
        result = {c: [] for c in self.watched_currencies}
        for currency, events in fallback_events.items():
            if currency in result:
                result[currency] = events
        
        return result
    
    def _background_refresh(self):
        """Background thread to refresh cache."""
        with self._lock:
            if self._is_refreshing:
                return
            self._is_refreshing = True
        
        try:
            logger.info("[NEWS] Background refresh started...")
            start_time = time.time()
            new_cache = self._batch_fetch_all_events()
            elapsed = time.time() - start_time
            
            with self._lock:
                if new_cache:
                    self._cache = new_cache
                    self._last_fetch_time = time.time()
                    self._consecutive_failures = 0
                    logger.info(f"[NEWS] Background refresh completed in {elapsed:.2f}s")
                else:
                    logger.warning("[NEWS] Background refresh failed, keeping old cache")
                    self._consecutive_failures += 1
        except Exception as e:
            logger.error(f"[NEWS] Background refresh error: {e}")
            self._consecutive_failures += 1
        finally:
            with self._lock:
                self._is_refreshing = False
    
    def _ensure_cache_fresh(self):
        """Ensure cache is fresh, trigger refresh if needed."""
        with self._lock:
            current_time = time.time()
            cache_expired = not self._cache or (current_time - self._last_fetch_time > self.cache_ttl)
            
            if cache_expired and not self._is_refreshing:
                time_since_request = current_time - self._last_fetch_time
                if time_since_request >= MIN_REQUEST_INTERVAL:
                    logger.debug("[NEWS] Cache expired, starting background refresh...")
                    self._refresh_thread = Thread(target=self._background_refresh, daemon=True)
                    self._refresh_thread.start()
                else:
                    logger.debug(f"[NEWS] Cache expired but rate limited, using stale data")
    
    def get_upcoming_events(self, symbol: str, minutes_ahead: int = 90) -> List[NewsEvent]:
        """Get upcoming events for a symbol."""
        currency = self._get_symbol_currency(symbol)
        
        # Ensure cache is fresh
        self._ensure_cache_fresh()
        
        with self._lock:
            events = self._cache.get(currency, [])
            filtered = [e for e in events if e.minutes_until <= minutes_ahead]
            return filtered
    
    def get_highest_impact_soon(self, symbol: str, minutes_ahead: int = 90) -> Optional[NewsEvent]:
        """Get the highest impact event coming up."""
        events = self.get_upcoming_events(symbol, minutes_ahead)
        
        # Sort by impact importance
        impact_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        events_sorted = sorted(events, key=lambda x: (impact_rank.get(x.impact, 0), -x.importance), reverse=True)
        
        return events_sorted[0] if events_sorted else None
    
    def get_news_summary(self, symbol: str) -> Dict:
        """Get comprehensive news summary for a symbol."""
        events = self.get_upcoming_events(symbol, minutes_ahead=120)
        
        high_impact = [e for e in events if e.impact == "HIGH"]
        medium_impact = [e for e in events if e.impact == "MEDIUM"]
        low_impact = [e for e in events if e.impact == "LOW"]
        
        next_event = events[0] if events else None
        
        # Get events for all currencies (for context)
        all_events = []
        with self._lock:
            for currency_events in self._cache.values():
                all_events.extend(currency_events)
        all_events = sorted(all_events, key=lambda x: x.minutes_until)
        
        return {
            "symbol": symbol,
            "currency": self._get_symbol_currency(symbol),
            "has_news": len(events) > 0,
            "high_impact_count": len(high_impact),
            "medium_impact_count": len(medium_impact),
            "low_impact_count": len(low_impact),
            "next_event": {
                "name": next_event.name if next_event else None,
                "impact": next_event.impact if next_event else None,
                "minutes_until": next_event.minutes_until if next_event else None,
                "currency": next_event.currency if next_event else None,
                "source": next_event.source if next_event else None
            } if next_event else None,
            "all_events": [
                {
                    "name": e.name,
                    "impact": e.impact,
                    "currency": e.currency,
                    "minutes_until": e.minutes_until,
                    "source": e.source
                }
                for e in events
            ],
            "global_events": [
                {
                    "name": e.name,
                    "impact": e.impact,
                    "currency": e.currency,
                    "minutes_until": e.minutes_until
                }
                for e in all_events[:10]
            ]
        }
    
    def get_cache_status(self) -> Dict:
        """Get cache status."""
        with self._lock:
            age_seconds = time.time() - self._last_fetch_time if self._last_fetch_time > 0 else 0
            total_events = sum(len(events) for events in self._cache.values())
            return {
                "initialized": bool(self._cache),
                "cached": total_events > 0,
                "age_seconds": round(age_seconds, 1),
                "ttl_seconds": self.cache_ttl,
                "is_refreshing": self._is_refreshing,
                "consecutive_failures": self._consecutive_failures,
                "total_events": total_events,
                "events_by_currency": {k: len(v) for k, v in self._cache.items()}
            }
    
    def force_refresh(self):
        """Force immediate refresh."""
        with self._lock:
            logger.info("[NEWS] Force refreshing cache...")
            self._cache = self._batch_fetch_all_events()
            self._last_fetch_time = time.time()
            self._consecutive_failures = 0


# ============================================================
# NEWS VETO DECISION ENGINE
# ============================================================

class NewsVetoEngine:
    """Decision engine for news-based vetoes."""
    
    def __init__(self):
        self.cache = None
        self._veto_history = {}
        self._cooldown_seconds = 900  # 15 minutes
        self._cooldown_cleanup_interval = 3600
        self._last_cleanup = time.time()
    
    def _get_cache(self) -> NewsCache:
        if self.cache is None:
            self.cache = NewsCache()
        return self.cache
    
    def warmup(self):
        """Warm up cache on startup."""
        logger.info("[NEWS] Warming up cache...")
        cache = self._get_cache()
        cache._background_refresh()
    
    def _cleanup_old_cooldowns(self):
        """Clean up expired cooldowns."""
        current_time = time.time()
        if current_time - self._last_cleanup > self._cooldown_cleanup_interval:
            to_remove = []
            for symbol, veto_time in self._veto_history.items():
                if current_time - veto_time > self._cooldown_seconds:
                    to_remove.append(symbol)
            for symbol in to_remove:
                del self._veto_history[symbol]
            self._last_cleanup = current_time
    
    def _is_in_cooldown(self, symbol: str) -> Tuple[bool, int]:
        """Check if symbol is in cooldown."""
        self._cleanup_old_cooldowns()
        if symbol in self._veto_history:
            elapsed = time.time() - self._veto_history[symbol]
            if elapsed < self._cooldown_seconds:
                return True, int(self._cooldown_seconds - elapsed)
        return False, 0
    
    def _record_veto(self, symbol: str):
        """Record a veto for cooldown."""
        self._veto_history[symbol] = time.time()
    
    def should_veto_new_entry(self, symbol: str, best_direction: str = "BUY", risk_tolerance: str = "NORMAL") -> Tuple[bool, str]:
        """Check if news should veto a new entry."""
        cache = self._get_cache()
        
        # Check if cache is initialized
        status = cache.get_cache_status()
        if not status["initialized"]:
            logger.debug(f"[NEWS] Cache not initialized for {symbol}, allowing trade")
            return False, None
        
        # Check cooldown
        in_cooldown, seconds_left = self._is_in_cooldown(symbol)
        if in_cooldown:
            return True, f"Post-news cooldown: {seconds_left}s remaining"
        
        # Get events for this symbol
        events = cache.get_upcoming_events(symbol, minutes_ahead=90)
        
        if not events:
            return False, None
        
        # Veto windows by risk tolerance
        veto_windows = {
            "LOW": {"HIGH": 90, "MEDIUM": 60, "LOW": 30},
            "NORMAL": {"HIGH": 60, "MEDIUM": 30, "LOW": 0},
            "HIGH": {"HIGH": 30, "MEDIUM": 15, "LOW": 0}
        }
        windows = veto_windows.get(risk_tolerance.upper(), veto_windows["NORMAL"])
        
        # Check each event
        for event in events:
            veto_minutes = windows.get(event.impact, 0)
            if veto_minutes > 0 and event.minutes_until <= veto_minutes:
                reason = f"{event.impact} impact news in {event.minutes_until:.0f} min: {event.name} ({event.source})"
                self._record_veto(symbol)
                return True, reason
        
        return False, None
    
    def should_hold_existing_position(self, symbol: str, current_pnl_percent: float = 0, position_direction: str = "BUY") -> Tuple[bool, str]:
        """Check if news should close an existing position."""
        cache = self._get_cache()
        
        status = cache.get_cache_status()
        if not status["initialized"]:
            return False, None
        
        event = cache.get_highest_impact_soon(symbol, minutes_ahead=60)
        if not event:
            return False, None
        
        # High impact news within 30 minutes
        if event.impact == "HIGH" and event.minutes_until <= 30:
            if current_pnl_percent < -5:
                return True, f"HIGH impact news in {event.minutes_until:.0f} min: {event.name} - Consider exiting losing position"
            else:
                return False, f"HIGH impact news in {event.minutes_until:.0f} min: {event.name} - Hold position"
        
        # Medium impact news within 15 minutes with large loss
        if event.impact == "MEDIUM" and event.minutes_until <= 15:
            if current_pnl_percent < -10:
                return True, f"MEDIUM impact news in {event.minutes_until:.0f} min: {event.name} - Consider exiting large loss"
            else:
                return False, None
        
        return False, None
    
    def get_news_summary(self, symbol: str) -> Dict:
        """Get news summary for a symbol."""
        cache = self._get_cache()
        return cache.get_news_summary(symbol)
    
    def get_cooldown_status(self, symbol: str) -> Dict:
        """Get cooldown status for a symbol."""
        in_cooldown, seconds_left = self._is_in_cooldown(symbol)
        return {
            "symbol": symbol,
            "in_cooldown": in_cooldown,
            "cooldown_seconds_remaining": seconds_left if in_cooldown else 0,
            "last_veto_time": self._veto_history.get(symbol)
        }
    
    def clear_cooldown(self, symbol: str = None):
        """Clear cooldown for a symbol or all."""
        if symbol:
            self._veto_history.pop(symbol, None)
            logger.info(f"[NEWS] Cleared cooldown for {symbol}")
        else:
            self._veto_history.clear()
            logger.info("[NEWS] Cleared all cooldowns")


# ============================================================
# GLOBAL INSTANCE AND CONVENIENCE FUNCTIONS
# ============================================================

_veto_engine = None


def get_veto_engine() -> NewsVetoEngine:
    """Get or create the global veto engine."""
    global _veto_engine
    if _veto_engine is None:
        _veto_engine = NewsVetoEngine()
    return _veto_engine


def warmup_news_cache():
    """Warm up the news cache on startup."""
    engine = get_veto_engine()
    engine.warmup()
    logger.info("[NEWS] Cache warmup initiated")


def check_news_veto_for_new_entry(symbol: str, best_direction: str = "BUY", risk_tolerance: str = "NORMAL") -> Tuple[bool, str]:
    """Check if news should veto a new entry."""
    engine = get_veto_engine()
    return engine.should_veto_new_entry(symbol, best_direction, risk_tolerance)


def check_news_risk_for_existing_position(symbol: str, current_pnl_percent: float = 0, position_direction: str = "BUY") -> Tuple[bool, str]:
    """Check if news should close an existing position."""
    engine = get_veto_engine()
    return engine.should_hold_existing_position(symbol, current_pnl_percent, position_direction)


def get_news_summary(symbol: str) -> Dict:
    """Get news summary for a symbol."""
    engine = get_veto_engine()
    return engine.get_news_summary(symbol)


def get_cache_status() -> Dict:
    """Get cache status."""
    engine = get_veto_engine()
    cache = engine._get_cache()
    return cache.get_cache_status()


def force_refresh_cache():
    """Force refresh the news cache."""
    engine = get_veto_engine()
    cache = engine._get_cache()
    cache.force_refresh()


def get_news_health() -> Dict:
    """Get news system health."""
    engine = get_veto_engine()
    cache = engine._get_cache()
    return {
        "cache": cache.get_cache_status(),
        "cache_initialized": cache._cache is not None,
        "total_currencies": len(cache.watched_currencies),
        "total_symbols": len(cache.symbol_currency_map),
        "last_fetch_time": datetime.fromtimestamp(cache._last_fetch_time).isoformat() if cache._last_fetch_time > 0 else None
    }


def clear_cooldown(symbol: str = None):
    """Clear cooldown for a symbol or all."""
    engine = get_veto_engine()
    engine.clear_cooldown(symbol)


def get_cooldown_status(symbol: str) -> Dict:
    """Get cooldown status for a symbol."""
    engine = get_veto_engine()
    return engine.get_cooldown_status(symbol)


def check_news_veto(symbol: str) -> Tuple[bool, str]:
    """Convenience function for news veto."""
    return check_news_veto_for_new_entry(symbol, "BUY", "NORMAL")


# ============================================================
# ON STARTUP - WARM UP CACHE
# ============================================================

# Warm up the cache when imported
try:
    warmup_news_cache()
except Exception as e:
    logger.warning(f"[NEWS] Initial warmup failed: {e}")