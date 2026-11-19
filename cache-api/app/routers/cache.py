"""
Cache proxy endpoints.

Every GET request is handled like:
  1. Build a cache key from the path + query string.
  2. Look in Redis. If found → return immediately.
  3. If miss → call the upstream client-api.
  4. Store the response in Redis with a TTL.
  5. Return to the caller.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import get_settings
from ..redis_client import get_cache
from ..client import get_upstream

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/cache", tags=["cache"])


# --------------------------------------------------------------
# Helpers
# --------------------------------------------------------------
def _cache_key(request: Request) -> str:
    """
    Build a deterministic cache key from the request.
    Includes path + sorted query params so `/cache/tenders?a=1&b=2`
    and `/cache/tenders?b=2&a=1` map to the same key.
    """
    path = request.url.path
    query = request.url.query
    return f"{path}?{query}" if query else path


async def _proxy(
    request: Request,
    upstream_path: str,
    ttl: int,
    params: Optional[dict] = None,
) -> dict:
    """
    Generic proxy: check cache → call upstream → cache → return.
    """
    cache = get_cache()
    upstream = get_upstream()

    key = _cache_key(request)

    # 1. Cache lookup
    cached = await cache.get(key)
    if cached is not None:
        logger.debug("[HIT] %s", key)
        # Mark so callers can see whether the response was cached
        if isinstance(cached, dict):
            cached["_cached"] = True
        return cached

    logger.debug("[MISS] %s", key)

    # 2. Upstream call
    try:
        data = await upstream.get(upstream_path, params=params)
    except Exception as e:
        logger.warning("Upstream call failed for %s: %s", upstream_path, e)
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    # 3. Store in cache (best effort — failure doesn't break the response)
    stored = await cache.set(key, data, ttl=ttl)
    if isinstance(data, dict):
        data["_cached"] = False
    return data


# --------------------------------------------------------------
# Routes
# --------------------------------------------------------------
@router.get("/tenders")
async def cached_list_tenders(
    request: Request,
    status: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    organisation: Optional[str] = Query(None),
    closing_before: Optional[str] = Query(None),
    closing_after: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    params = {
        "status": status,
        "province": province,
        "category": category,
        "organisation": organisation,
        "closing_before": closing_before,
        "closing_after": closing_after,
        "keyword": keyword,
        "limit": limit,
        "offset": offset,
    }
    # Drop None values so the query string is clean
    params = {k: v for k, v in params.items() if v is not None}

    return await _proxy(
        request,
        upstream_path="/tenders",
        ttl=settings.cache_ttl_list,
        params=params,
    )


@router.get("/tenders/search")
async def cached_search_tenders(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
):
    return await _proxy(
        request,
        upstream_path="/tenders/search",
        ttl=settings.cache_ttl_search,
        params={"q": q, "limit": limit},
    )


@router.get("/tenders/{tender_number}")
async def cached_tender_detail(request: Request, tender_number: str):
    return await _proxy(
        request,
        upstream_path=f"/tenders/{tender_number}",
        ttl=settings.cache_ttl_detail,
    )


@router.get("/stats")
async def cached_stats(request: Request):
    return await _proxy(
        request,
        upstream_path="/stats",
        ttl=settings.cache_ttl_stats,
    )


# --------------------------------------------------------------
# Cache management
# --------------------------------------------------------------
@router.get("/stats-cache")
async def cache_stats():
    """Return Redis memory + key count. Not to be confused with /cache/stats
    above (which caches the client-api's /stats). This one is about Redis."""
    cache = get_cache()
    return await cache.stats()


@router.post("/clear")
async def cache_clear(prefix: str = ""):
    """
    Invalidate cache entries.
    - POST /cache/clear             → wipes ALL keys with our prefix
    - POST /cache/clear?prefix=/cache/tenders → wipes only tender keys
    """
    cache = get_cache()
    removed = await cache.invalidate_prefix(prefix)
    return {"removed": removed, "prefix": prefix or "(all)"}