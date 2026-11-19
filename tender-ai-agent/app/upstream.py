"""
Read-through (cache-aside) cache for calls to client-api.

The agent asks client-api for the same tender over and over: once to show it,
again for its documents, again for a strategy, again for a proposal. Each of
those now goes through `get_json()`:

    Redis GET up:<hash(url+params)>
      hit  -> return cached JSON
      miss -> single-flight lock -> HTTP GET -> cache with TTL -> return

* TTLs: detail pages 10 min, lists/search 2 min (UPSTREAM_CACHE_TTL_*).
* 404s are cached briefly ("negative caching") so a mistyped tender number
  doesn't hammer client-api.
* Single-flight: if 10 requests miss the same key at once, only one goes
  upstream; the rest wait for it and read the cache (stops a cache stampede).
* Errors (5xx, timeouts) are never cached.
"""
import asyncio
import hashlib
import json
import logging
import urllib.parse
from collections import Counter
from typing import Any

import httpx

from .cache import get_cache
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

stats: Counter = Counter()
_locks: dict[str, asyncio.Lock] = {}


class UpstreamError(RuntimeError):
    pass


# One pooled HTTP client for every upstream call: reuses TCP connections instead
# of opening a new one (and a new connection pool) per request.
_http = None


def http_client():
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=30)
    return _http


async def close_http_client() -> None:
    global _http
    if _http is not None:
        try:
            await _http.aclose()
        except Exception:
            pass
        _http = None


async def post_json(url: str, json_body: dict | None = None, timeout: float = 60,
                    headers: dict[str, str] | None = None) -> Any:
    """POST to another service (not cached) and return the decoded JSON. Raises on HTTP errors."""
    resp = await http_client().post(url, json=json_body, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.json()


def tender_path(tender_number: str) -> str:
    return "/tenders/" + urllib.parse.quote(tender_number.strip(), safe="")


def _key(url: str, params: dict | None) -> str:
    blob = url + "?" + json.dumps(sorted((params or {}).items()), default=str)
    return "up:" + hashlib.sha1(blob.encode()).hexdigest()


async def get_json(path: str, params: dict | None = None, ttl: int | None = None,
                   timeout: float = 30, base_url: str | None = None) -> tuple[int, Any]:
    """GET base_url+path. Returns (status, data); data is None for 404. Raises UpstreamError otherwise."""
    url = (base_url or settings.client_api_url).rstrip("/") + path
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    ttl = ttl if ttl is not None else settings.upstream_ttl_detail
    key = _key(url, params)
    cache = get_cache()

    if cache and (hit := await cache.get(key)) is not None:
        stats["hits"] += 1
        return hit["status"], hit["data"]

    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            if cache and (hit := await cache.get(key)) is not None:  # filled while we waited
                stats["hits"] += 1
                return hit["status"], hit["data"]
            stats["misses"] += 1
            try:
                resp = await http_client().get(url, params=params or None, timeout=timeout)
            except httpx.HTTPError as e:
                stats["errors"] += 1
                raise UpstreamError(f"{type(e).__name__}: {e}") from e

            if resp.status_code == 404:
                if cache:
                    await cache.set(key, {"status": 404, "data": None}, ttl=settings.upstream_ttl_not_found)
                return 404, None
            if resp.status_code >= 400:
                stats["errors"] += 1
                raise UpstreamError(f"{url} returned {resp.status_code}")
            data = resp.json()
            if cache and ttl > 0:
                await cache.set(key, {"status": resp.status_code, "data": data}, ttl=ttl)
            return resp.status_code, data
    finally:
        if not lock.locked():
            _locks.pop(key, None)


async def get_tender(tender_number: str) -> dict | None:
    """Tender detail (cached). None if it doesn't exist."""
    status, data = await get_json(tender_path(tender_number), ttl=settings.upstream_ttl_detail)
    return data if status != 404 else None


async def list_tenders(**params) -> dict:
    """Tender list/search (cached briefly)."""
    _, data = await get_json("/tenders", params=params, ttl=settings.upstream_ttl_list)
    return data or {}


def get_stats() -> dict:
    total = stats["hits"] + stats["misses"]
    return {
        "hits": stats["hits"], "misses": stats["misses"], "errors": stats["errors"],
        "hit_rate": round(stats["hits"] / total, 3) if total else None,
        "ttl_detail": settings.upstream_ttl_detail, "ttl_list": settings.upstream_ttl_list,
    }
