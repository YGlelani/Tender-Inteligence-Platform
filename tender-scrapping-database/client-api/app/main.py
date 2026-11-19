import os
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
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


@app.get("/overview/stats")
async def overview_stats():
    if db is None:
        raise HTTPException(503, "Database is not initialized")
    return await db.get_dashboard_stats()


@app.get("/overview/volume")
async def overview_volume(days: int = Query(30, ge=1, le=365)):
    if db is None:
        raise HTTPException(503, "Database is not initialized")
    start = date.today() - timedelta(days=days - 1)
    async with db._connect() as connection:
        cursor = await connection.execute(
            """SELECT date(published_date) AS day, COUNT(*) AS count
               FROM tenders
               WHERE published_date IS NOT NULL AND date(published_date) >= ?
               GROUP BY date(published_date) ORDER BY day""",
            (start.isoformat(),),
        )
        counts = {row["day"]: row["count"] for row in await cursor.fetchall() if row["day"]}
    daily = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        daily.append({"date": day, "count": counts.get(day, 0)})
    return {"days": days, "total": sum(item["count"] for item in daily), "daily": daily}


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
