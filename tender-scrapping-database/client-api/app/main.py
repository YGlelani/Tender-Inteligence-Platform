import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .database import TenderDB
from .routers import tenders as tenders_router
from .routers import stats as stats_router

settings = get_settings()
db: TenderDB | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = await TenderDB.connect()
    yield
    await db.close()


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    **API_DOCS,
    title="eTenders Client API",
    description="Read-only API that serves tender data to the front-end client.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    print(f"\n[UNHANDLED] {request.method} {request.url.path}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
            "path": request.url.path,
        },
    )


app.include_router(tenders_router.router)
app.include_router(stats_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "client-api"}


@app.get("/")
async def root():
    return {
        "message": "eTenders Client API",
        "docs": "/docs",
        "endpoints": {
            "list_tenders":   "GET /tenders?province=Western Cape&limit=20",
            "search_tenders": "GET /tenders/search?q=internet",
            "tender_detail":  "GET /tenders/{tender_number}",
            "stats":          "GET /stats",
            "health":         "GET /health",
        },
    }