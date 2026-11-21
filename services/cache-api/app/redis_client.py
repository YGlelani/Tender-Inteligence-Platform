"""
Async Redis client wrapper.

Used by the cache layer to store serialized JSON responses keyed by
the request's path + query string.
"""
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CacheClient:
    def __init__(self, url: str, key_prefix: str):
        self.url = url
        self.key_prefix = key_prefix
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Open the connection pool. Called once at app startup."""
        self._client = redis.from_url(
            self.url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        # Verify connection works before declaring success
        await self._client.ping()
        logger.info("Connected to Redis at %s", self.url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            logger.info("Redis connection closed")

    async def ping(self) -> bool:
        try:
            if self._client is None:
                return False
            return await self._client.ping()
        except Exception as e:
            logger.warning("Redis ping failed: %s", e)
            return False

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value (deserialized) or None on miss."""
        if self._client is None:
            return None
        try:
            raw = await self._client.get(self._full_key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Redis GET failed for %s: %s", key, e)
            return None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Store a value with a TTL (seconds). Returns True on success."""
        if self._client is None:
            return False
        try:
            serialized = json.dumps(value, default=str)
            await self._client.setex(self._full_key(key), ttl, serialized)
            return True
        except Exception as e:
            logger.warning("Redis SET failed for %s: %s", key, e)
            return False

    async def invalidate_prefix(self, prefix: str = "") -> int:
        """
        Delete all keys that start with the given prefix.
        Uses SCAN to avoid blocking Redis (KEYS is O(N) and blocks).

        Returns the number of keys deleted.
        """
        if self._client is None:
            return 0

        pattern = self._full_key(f"{prefix}*")
        deleted = 0

        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    deleted += await self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("Redis SCAN/DELETE failed for pattern %s: %s", pattern, e)

        return deleted

    async def stats(self) -> dict:
        """
        Return cache size + Redis info.
        Useful for /cache/stats and debugging.
        """
        if self._client is None:
            return {"connected": False}

        try:
            info = await self._client.info("memory")
            pattern = self._full_key("*")
            cursor = 0
            count = 0
            while True:
                cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=200)
                count += len(keys)
                if cursor == 0:
                    break
            return {
                "connected": True,
                "keys_with_prefix": count,
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_bytes": info.get("used_memory"),
            }
        except Exception as e:
            logger.warning("Redis INFO failed: %s", e)
            return {"connected": False, "error": str(e)}


# Singleton instance used across the app
cache: CacheClient | None = None


def init_cache() -> CacheClient:
    """Create the singleton. Called once in main.py lifespan."""
    global cache
    if cache is None:
        cache = CacheClient(settings.redis_url, settings.cache_key_prefix)
    return cache


def get_cache() -> CacheClient:
    """Return the singleton. Raises if init_cache() wasn't called yet."""
    if cache is None:
        raise RuntimeError("Cache not initialized — call init_cache() first")
    return cache