import json
import logging
from functools import lru_cache

import redis.asyncio as redis
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ResponseCache:
    def __init__(self, url: str):
        self.url = url
        self._client: redis.Redis | None = None

    async def connect(self):
        try:
            # Inside the try: a blank/invalid REDIS_URL must degrade to "no cache", not crash startup.
            self._client = redis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            logger.info("Redis connected for cache")
        except Exception as e:
            logger.warning("Redis unavailable: %s", e)
            self._client = None

    async def get(self, key: str):
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def set(self, key: str, value, ttl: int = 600):
        if self._client is None:
            return
        try:
            await self._client.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass

    async def delete(self, key: str):
        if self._client is None:
            return
        try:
            await self._client.delete(key)
        except Exception:
            pass

    async def delete_matching(self, pattern: str) -> int:
        """Delete every key matching a glob pattern. Returns how many were deleted."""
        if self._client is None:
            return 0
        deleted = 0
        async for key in self._client.scan_iter(match=pattern, count=500):
            deleted += await self._client.delete(key)
        return deleted

    async def close(self):
        if self._client:
            await self._client.aclose()


_cache = None


async def init_cache() -> ResponseCache:
    global _cache
    if _cache is None:
        _cache = ResponseCache(settings.redis_url)
        await _cache.connect()
    return _cache


def get_cache() -> ResponseCache | None:
    return _cache