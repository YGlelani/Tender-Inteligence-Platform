"""
Semantic tender search.

Keyword search misses tenders that describe the same work in different
words ("road resurfacing" vs "rehabilitation of municipal streets"). This
module embeds every open tender and searches by meaning, with optional
province / category filters and a "still open" date filter applied inside
the vector query (hybrid search).

Sync (`sync_open_tenders`):
  * pages through client-api /tenders?status=Open
  * builds one text per tender (title + organisation + category + province + description)
  * re-embeds only tenders whose text changed (sha1 stored on the hash), and
    unchanged text is an embedding-cache hit anyway
  * removes tenders that are no longer open
  * a Redis lock (SET NX EX) stops two replicas syncing at the same time

Runs at startup, every TENDER_SYNC_INTERVAL seconds, and on POST /agent/reindex-tenders.
"""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone

from .config import get_settings
from .embeddings import embed, embed_many
from .redis_bin import get_redis_bin, to_str
from .upstream import get_json
from .vector_store import Filter, VectorIndex, backend_info

logger = logging.getLogger(__name__)
settings = get_settings()

INDEX = VectorIndex(
    "tenders", "tender:vec:",
    tags=("tender_key", "province", "category", "status"),
    texts=("title",),
    numerics=("closing_ts",),
)
LOCK_KEY = "tenderidx:sync:lock"
LAST_SYNC_KEY = "tenderidx:last_sync"
UNKNOWN_CLOSING = -1  # tenders without a parseable closing date are treated as open

RETURN_FIELDS = ("tender_number", "title", "organisation", "province_name", "category_name",
                 "closing_date", "status")

_SA_PROVINCES = ["eastern cape", "free state", "gauteng", "kwazulu-natal", "kwazulu natal", "kzn",
                 "limpopo", "mpumalanga", "north west", "northern cape", "western cape", "national"]
_PROVINCE_CANON = {"kwazulu natal": "kwazulu-natal", "kzn": "kwazulu-natal"}


def tender_key(tender_number: str) -> str:
    return hashlib.sha1(" ".join(tender_number.split()).lower().encode()).hexdigest()[:16]


def _category(t: dict) -> str:
    # client-api returns the joined category as `category_name`.
    return t.get("category_name") or t.get("category") or ""


def tender_text(t: dict) -> str:
    parts = [
        t.get("title"),
        t.get("organisation_name") or t.get("organisation"),
        _category(t),
        t.get("province"),
        (t.get("description") or "")[:2500],
    ]
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


def parse_closing(value) -> float:
    if not value:
        return UNKNOWN_CLOSING
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y", "%d/%m/%Y %H:%M", "%d %B %Y", "%d %b %Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return UNKNOWN_CLOSING
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def detect_province(text: str) -> str | None:
    low = text.lower()
    for p in _SA_PROVINCES:
        if p in low:
            return _PROVINCE_CANON.get(p, p)
    return None


def strip_province(text: str) -> str:
    """Remove province names, e.g. 'fixing potholes gauteng' -> 'fixing potholes'."""
    low = text.lower()
    for p in sorted(_SA_PROVINCES, key=len, reverse=True):
        low = low.replace(p, " ")
    return " ".join(low.split())


# ---------------------------------------------------------------- sync
async def sync_open_tenders(max_tenders: int | None = None, page_size: int = 500) -> dict:
    r = get_redis_bin()
    if r is None:
        return {"status": "skipped", "reason": "redis unavailable"}
    if not await r.set(LOCK_KEY, b"1", nx=True, ex=900):
        return {"status": "skipped", "reason": "another sync is running"}

    started = time.time()
    max_tenders = max_tenders or settings.tender_sync_max
    try:
        tenders, complete, offset = [], True, 0
        while len(tenders) < max_tenders:
            try:
                # ttl=0: always fresh data for the sync, don't fill the read cache
                _, data = await get_json("/tenders", params={"status": "Open", "limit": page_size,
                                                             "offset": offset}, ttl=0, timeout=60)
            except Exception as e:
                logger.warning("Tender sync: page at offset %s failed: %s", offset, e)
                complete = False
                break
            page = (data or {}).get("tenders", [])
            tenders.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        tenders = [t for t in tenders[:max_tenders] if t.get("tender_number")]

        # Which ones changed since the last sync?
        prepared = []
        for t in tenders:
            text = tender_text(t)
            prepared.append((t, tender_key(t["tender_number"]), text,
                             hashlib.sha1(text.encode()).hexdigest()))
        pipe = r.pipeline(transaction=False)
        for _, tkey, _, _ in prepared:
            pipe.hget(INDEX.prefix + tkey, "text_hash")
        old_hashes = await pipe.execute() if prepared else []
        changed = [p for p, old in zip(prepared, old_hashes) if to_str(old) != p[3]]

        embedded = 0
        if changed:
            vectors = await embed_many([p[2] for p in changed])
            records = []
            for (t, tkey, _text, h), vec in zip(changed, vectors):
                records.append((tkey, vec, {
                    "tender_key": tkey,
                    "tender_number": t["tender_number"],
                    "title": (t.get("title") or "")[:500],
                    "organisation": t.get("organisation_name") or t.get("organisation") or "",
                    "province": t.get("province") or "",
                    "category": _category(t),
                    # tag fields are lower-cased for filtering; keep a display copy
                    "province_name": t.get("province") or "",
                    "category_name": _category(t),
                    "status": t.get("status") or "Open",
                    "closing_date": str(t.get("closing_date") or ""),
                    "closing_ts": parse_closing(t.get("closing_date")),
                    "text_hash": h,
                }))
            for i in range(0, len(records), 200):
                embedded += await INDEX.upsert(records[i:i + 200])

        # Remove tenders that are no longer open (only if we saw the full list).
        removed = 0
        if complete:
            seen = {INDEX.prefix + p[1] for p in prepared}
            stale = [k for k in await INDEX.keys() if k not in seen]
            for i in range(0, len(stale), 500):
                removed += await r.delete(*stale[i:i + 500])

        result = {
            "status": "ok" if complete else "partial",
            "open_tenders": len(prepared),
            "embedded": embedded,
            "unchanged": len(prepared) - len(changed),
            "removed": removed,
            "seconds": round(time.time() - started, 2),
            **(await backend_info()),
        }
        await r.set(LAST_SYNC_KEY, str(int(time.time())).encode())
        logger.info("Tender sync: %s", result)
        return result
    finally:
        await r.delete(LOCK_KEY)


async def periodic_sync() -> None:
    """Background loop started from the app lifespan."""
    await asyncio.sleep(5)  # let the other services come up first
    while True:
        try:
            await sync_open_tenders()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Tender sync failed")
        if settings.tender_sync_interval <= 0:
            return
        await asyncio.sleep(settings.tender_sync_interval)


# ---------------------------------------------------------------- search
async def semantic_search(query: str, province: str | None = None, category: str | None = None,
                          limit: int = 5, open_only: bool = True, min_score: float = 0.0,
                          provinces: list[str] | None = None) -> list[dict]:
    """Tenders closest in meaning to `query`, filtered inside the vector query.

    `provinces` keeps tenders in any of several provinces (a user's profile provinces).
    """
    vec = await embed(query)
    flt = Filter().tag("province", province, *(provinces or [])).tag("category", category)
    if open_only:
        flt.range("closing_ts", (time.time(), float("inf")), (UNKNOWN_CLOSING, UNKNOWN_CLOSING))
    hits = await INDEX.knn(vec, k=max(1, min(int(limit), 20)), flt=flt, return_fields=RETURN_FIELDS)
    return [{
        "tender_number": h.fields.get("tender_number"),
        "title": h.fields.get("title"),
        "organisation": h.fields.get("organisation"),
        "province": h.fields.get("province_name"),
        "category": h.fields.get("category_name"),
        "closing_date": h.fields.get("closing_date"),
        "score": round(h.score, 4),
    } for h in hits if h.score >= min_score]


async def index_size() -> int:
    try:
        return len(await INDEX.keys())
    except Exception:
        return 0


async def last_sync() -> int | None:
    r = get_redis_bin()
    if r is None:
        return None
    raw = to_str(await r.get(LAST_SYNC_KEY))
    return int(raw) if raw else None
