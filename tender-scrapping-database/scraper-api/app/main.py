import logging
import os
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .scraper import scrape_tenders, ScrapeError
from .database import TenderDB
from .auth import require_api_key
from .routers import tenders as tenders_router
from .routers import stats as stats_router
from .routers import scraping as scraping_router

settings = get_settings()
db: TenderDB | None = None


# Background scraper loop — scrapes AND saves, forever
async def _background_scraper_loop():
    await asyncio.sleep(settings.scraper_loop_start_delay_seconds)
    print("[LOOP] Background scraper loop started")

    while True:
        started = asyncio.get_event_loop().time()
        print("\n[LOOP] === Starting scheduled scrape ===")

        log_id = None
        found = 0
        added = 0
        updated = 0
        skipped = 0

        try:
            if db is None:
                print("[LOOP] DB not initialized, skipping this cycle")
                await asyncio.sleep(settings.scraper_loop_interval_seconds)
                continue

            log_id = await db.start_log("background_loop")

            # SCRAPE 
            result = await scrape_tenders(
                status="current",
                max_pages=settings.max_pages_default,
                fetch_details=True,
            )
            found = len(result.tenders)
            print(f"[LOOP] Scraped {found} tenders — saving...")

            # SAVE 
            for tender in result.tenders:
                outcome = await db.save_tender(tender, source="background_loop", status=settings.status_names["current"])
                if outcome == "new":
                    added += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1

            await db.complete_log(log_id, found, added, "Completed")

            elapsed = asyncio.get_event_loop().time() - started
            print(
                f"[LOOP] === Cycle done in {elapsed:.1f}s: "
                f"found={found} added={added} updated={updated} skipped={skipped} ==="
            )

        except asyncio.CancelledError:
            print("[LOOP] Cancelled — shutting down cleanly")
            raise
        except Exception as exc:
            print(f"[LOOP] Cycle failed: {type(exc).__name__}: {exc}")
            try:
                if log_id is not None and db is not None:
                    await db.complete_log(log_id, found, added, "Failed", str(exc))
            except Exception as log_exc:
                print(f"[LOOP] Could not update log: {log_exc}")

        print(f"[LOOP] Sleeping {settings.scraper_loop_interval_seconds}s before next cycle...")
        await asyncio.sleep(settings.scraper_loop_interval_seconds)


# Lifespan — starts the loop, cleans up on shutdown

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = await TenderDB.connect()

    loop_task = None
    if settings.scraper_loop_enabled:
        loop_task = asyncio.create_task(_background_scraper_loop())
    else:
        print("[LOOP] Background scraper loop disabled (SCRAPER_LOOP_ENABLED=false)")

    yield

    if loop_task:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    await db.close()


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

# Web pages allowed to call this API from a browser, comma-separated
# (for example http://129.151.181.87:8009). Set in compose.yaml.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logging.getLogger(__name__).warning("CORS_ORIGINS is not set: browsers on other sites cannot call this API.")

app = FastAPI(
    **API_DOCS,
    title="eTenders API",
    description="Scraper + read API for South Africa's National Treasury eTenders portal.",
    version="1.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
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


#  Routers 
app.include_router(tenders_router.router)
app.include_router(stats_router.router)
app.include_router(scraping_router.router)


# Manual scrape-and-save 
@app.get(
    "/scrape-and-save",
    tags=["scraping"],
    dependencies=[Depends(require_api_key)],
)
async def scrape_and_save(
    status: str = Query("current"),
    max_pages: int = Query(settings.max_pages_default, ge=1, le=settings.max_pages_hard_cap),
):
    if db is None:
        raise HTTPException(500, "DB not initialized")

    log_id = await db.start_log("etenders_portal")
    found = 0
    added = 0
    updated = 0
    skipped = 0

    try:
        result = await scrape_tenders(
            status=status, max_pages=max_pages, fetch_details=True
        )
        found = len(result.tenders)

        for tender in result.tenders:
            outcome = await db.save_tender(tender, source="etenders_portal", status=settings.status_names[status])
            if outcome == "new":
                added += 1
            elif outcome == "updated":
                updated += 1
            else:
                skipped += 1

        await db.complete_log(log_id, found, added, "Completed")
        return {
            "log_id": log_id,
            "found": found,
            "added": added,
            "updated": updated,
            "skipped": skipped,
        }

    except Exception as exc:
        try:
            await db.complete_log(log_id, found, added, "Failed", str(exc))
        except Exception as log_exc:
            print(f"[LOG ERROR] {log_exc}")
        raise


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/", tags=["root"])
async def root():
    return {
        "message": "eTenders API",
        "docs": "/docs",
        "loop": {
            "enabled": settings.scraper_loop_enabled,
            "interval_seconds": settings.scraper_loop_interval_seconds,
        },
        "endpoints": {
            "list_tenders":    "GET /tenders",
            "search_tenders":  "GET /tenders/search?q=internet",
            "tender_detail":   "GET /tenders/{tender_number}",
            "stats":           "GET /stats",
            "deep_health":     "GET /health/deep",
            "scrape_only":     "POST /scrape (X-API-Key required)",
            "scrape_and_save": "GET /scrape-and-save (X-API-Key required)",
            "scraping_logs":   "GET /scraping-logs",
            "log_detail":      "GET /scraping-logs/{id}",
        },
    }