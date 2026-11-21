from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/tenders", tags=["tenders"])


def _db():
    from ..main import db
    if db is None:
        raise HTTPException(500, "DB not initialized")
    return db


@router.get("")
async def list_tenders(
    status: Optional[str] = Query(None, description="Open, Closed, Awarded"),
    province: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    organisation: Optional[str] = Query(None),
    closing_before: Optional[str] = Query(None, description="ISO date"),
    closing_after: Optional[str] = Query(None, description="ISO date"),
    keyword: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    db = _db()
    rows = await db.list_tenders(
        status=status, province=province, category=category,
        organisation=organisation,
        closing_before=closing_before, closing_after=closing_after,
        keyword=keyword, limit=limit, offset=offset,
    )
    total = await db.count_tenders(
        status=status, province=province, category=category,
        organisation=organisation,
        closing_before=closing_before, closing_after=closing_after,
        keyword=keyword,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(rows),
        "tenders": rows,
    }


@router.get("/search")
async def search_tenders(
    q: Optional[str] = Query(None, max_length=200),
    province: Optional[str] = Query(None, max_length=100),
    category: Optional[str] = Query(None, max_length=100),
    organisation: Optional[str] = Query(None, max_length=200),
    status: Optional[str] = Query(None, max_length=30),
    include_closed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = _db()
    selected_status = status or (None if include_closed else "Open")
    filters = {
        "status": selected_status,
        "province": province,
        "category": category,
        "organisation": organisation,
        "keyword": q,
    }
    rows = await db.list_tenders(**filters, limit=limit, offset=offset)
    total = await db.count_tenders(**filters)
    return {"query": q, "count": len(rows), "total": total, "tenders": rows}


# NOTE: {tender_number:path} — the ":path" converter lets the route capture
# slashes, so tender numbers like "2027/003", "01-2026/27", and
# "019/2026/EWSS/LAPTOPS/RFB" all work. Without it, only the segment before
# the first slash would be passed to the handler.
@router.get("/{tender_number:path}")
async def get_tender(tender_number: str):
    db = _db()
    detail = await db.get_tender_detail(tender_number)
    if detail is None:
        raise HTTPException(404, f"Tender {tender_number} not found")
    return detail
