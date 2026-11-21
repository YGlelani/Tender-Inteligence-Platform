import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import SCAN_INTERVAL_SECONDS
from .routers import router
from .service import background_scanner

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = db.create_pool()
    await db.ensure_schema(pool)
    app.state.pool = pool

    stop_scanner = asyncio.Event()
    scanner = asyncio.create_task(background_scanner(pool, stop_scanner, SCAN_INTERVAL_SECONDS))

    yield

    stop_scanner.set()
    await scanner
    await pool.close()
    app.state.pool = None


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

# Web pages allowed to call this API from a browser, comma-separated
# (for example https://app.example.com). Set per environment in Compose.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logging.getLogger(__name__).warning("CORS_ORIGINS is not set: browsers on other sites cannot call this API.")

app = FastAPI(
    **API_DOCS,
    title="TenderScrapping Smart Alerts API",
    description="Client-facing Smart Tender Alerts service.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "healthy", "service": "alerts-api"}


@app.get("/", tags=["root"])
async def root():
    return {"message": "TenderScrapping Smart Alerts API", "docs": "/docs"}
