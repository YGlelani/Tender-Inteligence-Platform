"""
Walk a whole eTenders list once and refresh the tenders already stored.

The background loop only reads the newest pages (ETENDERS_MAX_PAGES_DEFAULT), so a
tender is never revisited once it moves further down the list. Tenders saved before
closing dates were scraped therefore have no closing date, and none are ever
marked as closed. This command fixes that backlog:

- `--status current` saves every tender on the open list, filling in missing
  closing dates (new tenders are added as well, as in the normal loop);
- `--status closed`, `cancelled` or `awarded` marks tenders already in the
  database with that status. Tenders that are not stored are skipped, so the
  database does not fill up with eTenders' history.

Each page takes about 16 seconds, so a long run is best started at a quiet time.

Usage (inside the scraper container):
    python -m app.backfill --status current --pages 250
    python -m app.backfill --status closed --pages 1000
"""
import argparse
import asyncio
from collections import Counter

from .config import get_settings
from .database import TenderDB
from .scraper import scrape_tenders

settings = get_settings()


async def save_found(db: TenderDB, tenders, status: str) -> Counter:
    """Save the scraped tenders with the list's status; other lists only update stored tenders."""
    counts = Counter()
    for tender in tenders:
        if status != "current" and not await db.tender_exists(tender.tender_number):
            counts["not_stored"] += 1
            continue
        counts[await db.save_tender(tender, source=f"backfill_{status}", status=settings.status_names[status])] += 1
    return counts


async def backfill(status: str, pages: int) -> Counter:
    db = await TenderDB.connect()
    log_id = await db.start_log(f"backfill_{status}")
    try:
        result = await scrape_tenders(status=status, max_pages=pages, fetch_details=True)
        counts = await save_found(db, result.tenders, status)
    except Exception as error:
        await db.complete_log(log_id, 0, 0, "Failed", str(error)[:500])
        raise
    await db.complete_log(log_id, len(result.tenders), counts["new"], "Completed")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh stored tenders from a whole eTenders list.")
    parser.add_argument("--status", choices=sorted(settings.status_ids), required=True)
    parser.add_argument("--pages", type=int, required=True, help=f"pages to read, at most {settings.max_pages_hard_cap}")
    args = parser.parse_args()
    counts = asyncio.run(backfill(args.status, min(args.pages, settings.max_pages_hard_cap)))
    print(f"[BACKFILL] {args.status}: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))


if __name__ == "__main__":
    main()
