
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .redis_client import init_cache, get_cache
from .client import init_upstream, get_upstream
from .routers import cache as cache_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("lelani.cache")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup 
    logger.info("Starting Cache API")

    # Redis
    cache = init_cache()
    try:
        await cache.connect()
        logger.info("Redis connected at %s", settings.redis_url)
    except Exception as e:
        logger.error("Could not connect to Redis: %s", e)
        # We do NOT crash on startup — the app can still forward requests
        # to upstream without a cache .

    # Upstream client-api
    upstream = init_upstream()
    await upstream.connect()
    if await upstream.is_healthy():
        logger.info("Upstream client-api is healthy at %s", settings.client_api_url)
    else:
        logger.warning("Upstream client-api did NOT respond to /health")

    logger.info("Lelani Cache API startup complete")

    yield

    #  shutdown 
    logger.info("Shutting down  Cache API")
    try:
        await get_cache().close()
    except Exception:
        pass
    try:
        await get_upstream().close()
    except Exception:
        pass


app = FastAPI(
    title=" Cache API",
    description=(
        "Read-through cache in front of client-api. "
        "Reduces DB load by storing frequent responses in Redis."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error("Unhandled error on %s %s", request.method, request.url.path)
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
            "path": request.url.path,
        },
    )


#  Routers 
app.include_router(cache_router.router)


#Health & root 
@app.get("/health", tags=["health"])
async def health():
    cache_ok = False
    upstream_ok = False
    try:
        cache_ok = await get_cache().ping()
    except Exception:
        pass
    try:
        upstream_ok = await get_upstream().is_healthy()
    except Exception:
        pass

    overall = "ok" if (cache_ok and upstream_ok) else "degraded"
    return {
        "status": overall,
        "service": "lelani-cache-api",
        "redis": "ok" if cache_ok else "unavailable",
        "client_api": "ok" if upstream_ok else "unavailable",
    }


@app.get("/", tags=["root"])
async def root():
    return {
        "message": "Lelani Cache API",
        "docs": "/docs",
        "endpoints": {
            "list_tenders":     "GET /cache/tenders",
            "search_tenders":   "GET /cache/tenders/search?q=internet",
            "tender_detail":    "GET /cache/tenders/{tender_number}",
            "stats":            "GET /cache/stats",
            "cache_stats":      "GET /cache/stats-cache",
            "clear_cache":      "POST /cache/clear?prefix=/cache/tenders",
            "health":           "GET /health",
        },
    }