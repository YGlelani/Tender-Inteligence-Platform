"""
Chat memory backed by Redis.

Stores the last N messages per session_id. Persists across container restarts.
"""
import json
import logging

import redis.asyncio as redis
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ChatMemory:
    def __init__(self, url: str, ttl_seconds: int = 86400, max_messages: int = 20):
        self.url = url
        self.ttl = ttl_seconds
        self.max_messages = max_messages
        self._client: redis.Redis | None = None

    async def connect(self):
        try:
            self._client = redis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            logger.info("Chat memory connected")
        except Exception as e:
            logger.warning("Chat memory unavailable: %s", e)
            self._client = None

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def get_history(self, session_id: str) -> list[dict]:
        if not self._client:
            return []
        try:
            raw = await self._client.get(f"chat:history:{session_id}")
            return json.loads(raw) if raw else []
        except Exception as e:
            logger.warning("Memory read failed: %s", e)
            return []

    async def append(self, session_id: str, role: str, content: str):
        if not self._client:
            return
        try:
            key = f"chat:history:{session_id}"
            history = await self.get_history(session_id)
            history.append({"role": role, "content": content})
            history = history[-self.max_messages:]
            await self._client.setex(key, self.ttl, json.dumps(history))
        except Exception as e:
            logger.warning("Memory append failed: %s", e)

    async def clear(self, session_id: str):
        if not self._client:
            return
        try:
            await self._client.delete(f"chat:history:{session_id}")
        except Exception:
            pass

    async def delete_matching(self, pattern: str) -> int:
        """Delete every key matching a glob pattern. Returns how many were deleted."""
        if not self._client:
            return 0
        deleted = 0
        async for key in self._client.scan_iter(match=pattern, count=500):
            deleted += await self._client.delete(key)
        return deleted


_memory: ChatMemory | None = None


async def init_memory() -> ChatMemory:
    global _memory
    if _memory is None:
        _memory = ChatMemory(settings.redis_url)
        await _memory.connect()
    return _memory


def get_memory() -> ChatMemory | None:
    return _memory