"""Thread-safe and async-compatible in-memory TTL caching.

Prevents redundant LLM calls and Tavily search requests, reducing cost,
conserving Tavily search credits, and minimizing latency.
Uses threading.Lock to avoid asyncio event loop binding issues across test runners.
"""

import threading
from typing import Any
from cachetools import TTLCache

from app.config import get_settings


class AsyncTTLCache:
    """Thread-safe TTL cache with async API."""

    def __init__(self, maxsize: int = 1000, ttl: int = 3600) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Any | None:
        """Retrieve value from cache if present and unexpired."""
        with self._lock:
            val = self._cache.get(key)
            if val is not None:
                self._hits += 1
            else:
                self._misses += 1
            return val

    async def set(self, key: str, value: Any) -> None:
        """Store value with default TTL."""
        with self._lock:
            self._cache[key] = value

    async def delete(self, key: str) -> None:
        """Remove a key from cache."""
        with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all entries from cache."""
        with self._lock:
            self._cache.clear()

    async def stats(self) -> dict[str, Any]:
        """Return cache health and hit/miss statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
            }


_settings = get_settings()

# Cache for parsed natural language query intents
query_intent_cache = AsyncTTLCache(
    maxsize=_settings.cache_maxsize,
    ttl=_settings.cache_ttl_seconds,
)

# Cache for raw Tavily search query responses
search_response_cache = AsyncTTLCache(
    maxsize=_settings.cache_maxsize,
    ttl=_settings.cache_ttl_seconds,
)
