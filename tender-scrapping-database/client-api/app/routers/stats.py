from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def get_stats():
    from ..main import db
    if db is None:
        raise HTTPException(500, "DB not initialized")
    return await db.get_dashboard_stats()