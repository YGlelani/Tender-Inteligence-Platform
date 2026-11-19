"""
Binary-safe Redis connection.

`cache.py` and `memory.py` use `decode_responses=True`, which turns every reply
into `str`. Vector embeddings are raw float32 bytes, so they need a client that
leaves bytes alone. This module owns that second connection.

Every caller must treat `get_redis_bin()` returning None as "Redis is down" and
degrade gracefully — the agent keeps working without caching or vector search.
"""
import logging

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client = None


async def init_redis_bin():
    global _client
    if _client is not None:
        return _client
    import redis.asyncio as redis  # imported lazily so unit tests can inject a fake

    try:
        # Inside the try: a blank/invalid REDIS_URL must degrade gracefully, not crash startup.
        client = redis.from_url(settings.redis_url, decode_responses=False)
        await client.ping()
        _client = client
        logger.info("Binary Redis connected (vectors + embedding cache)")
    except Exception as e:
        logger.warning("Binary Redis unavailable: %s", e)
        _client = None
    return _client


def get_redis_bin():
    return _client


def set_redis_bin(client) -> None:
    """Swap the connection (used by tests)."""
    global _client
    _client = client


async def close_redis_bin() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


def to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
