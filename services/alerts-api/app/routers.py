from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from . import db
from .auth import require_user
from .dependencies import Pool
from .documents import fetch_details, invalidate_details, profile_from_documents, with_documents
from .schemas import (
    BusinessProfileAlertOut,
    MatchedTender,
    NotificationOut,
    UnreadCount,
)
from .service import MIN_ALERT_MATCH_SCORE, current_notifications, get_profile_matches

router = APIRouter()

CurrentUser = Annotated[dict, Depends(require_user)]

MIN_NEAR_MATCH_SCORE = 50
MAX_MATCHES = 150

PROFILE_NOT_FOUND = "Company profile not found."
DB_UNAVAILABLE = {"description": "Database is not initialized"}
NO_PROFILE = {"description": PROFILE_NOT_FOUND}


def serialise_profile(row):
    item = dict(row)
    for key in ("min_tender_value", "max_tender_value"):
        if item.get(key) is not None:
            item[key] = float(item[key])
    return item


async def matching_profile(pool, user):
    """The user's Business Profile merged with details from their documents."""
    profile = await db.fetch_business_profile(pool, user["id"])
    if not profile:
        return None
    return with_documents(profile, await fetch_details(user["id"], user["token"]))


async def profile_for_matches(pool, user):
    """The matching profile, or one built from the user's business documents when they have no Business Profile.

    Only /matches uses it: notifications are stored against a Business Profile.
    """
    profile = await matching_profile(pool, user)
    if profile:
        return profile
    return profile_from_documents(await fetch_details(user["id"], user["token"]))


async def user_notifications(pool, user):
    profile = await matching_profile(pool, user)
    if not profile:
        return []
    return await current_notifications(pool, profile)


@router.get(
    "/profile",
    response_model=BusinessProfileAlertOut,
    tags=["profile"],
    responses={404: NO_PROFILE, 503: DB_UNAVAILABLE},
)
async def get_profile(pool: Pool, user: CurrentUser):
    profile = await db.fetch_business_profile(pool, user["id"])
    if not profile:
        raise HTTPException(404, PROFILE_NOT_FOUND)
    details = await fetch_details(user["id"], user["token"])
    item = serialise_profile(with_documents(profile, details))
    item["document_provinces"] = details.get("provinces", [])
    return item


@router.post(
    "/profile/refresh",
    tags=["profile"],
    responses={404: NO_PROFILE, 503: DB_UNAVAILABLE},
)
async def refresh_profile(pool: Pool, user: CurrentUser):
    invalidate_details(user["id"])
    details = await fetch_details(user["id"], user["token"])
    profile = await db.fetch_business_profile(pool, user["id"])
    if profile:
        item = serialise_profile(with_documents(profile, details))
    else:
        item = profile_from_documents(details)
    if not item:
        raise HTTPException(409, "Upload a business profile or company documents before refreshing your profile.")
    item["document_provinces"] = details.get("provinces", [])
    return item


@router.get(
    "/matches",
    response_model=list[MatchedTender],
    tags=["profile"],
    responses={404: NO_PROFILE, 503: DB_UNAVAILABLE},
)
async def profile_matches(pool: Pool, user: CurrentUser):
    profile = await profile_for_matches(pool, user)
    if not profile:
        raise HTTPException(404, PROFILE_NOT_FOUND)

    matches = []
    for match in await get_profile_matches(pool, profile):
        if match["score"] < MIN_NEAR_MATCH_SCORE:
            continue
        tender = match["tender"]
        matches.append({
            "id": tender["id"],
            "tender_number": tender["tender_number"],
            "title": tender["title"],
            "province": tender["province"],
            "category": tender["category"],
            "organisation": tender["organisation"],
            "closing_date": tender["closing_date"],
            "status": tender["status"],
            "score": match["score"],
            "level": "strong" if match["score"] >= MIN_ALERT_MATCH_SCORE else "near",
            "reasons": match["reasons"],
        })
    return matches[:MAX_MATCHES]


@router.get(
    "/notifications",
    response_model=list[NotificationOut],
    tags=["notifications"],
    responses={503: DB_UNAVAILABLE},
)
async def list_notifications(
    pool: Pool,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    unread_only: Annotated[bool, Query()] = False,
):
    items = await user_notifications(pool, user)
    if unread_only:
        items = [item for item in items if not item.get("read_at")]
    return items[:limit]


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCount,
    tags=["notifications"],
    responses={503: DB_UNAVAILABLE},
)
async def unread_count(pool: Pool, user: CurrentUser):
    items = await user_notifications(pool, user)
    return {"unread": sum(1 for item in items if not item.get("read_at"))}


@router.post(
    "/notifications/{notification_id}/read",
    status_code=204,
    tags=["notifications"],
    responses={404: {"description": "Notification not found"}, 503: DB_UNAVAILABLE},
)
async def mark_read(notification_id: int, pool: Pool, user: CurrentUser):
    if not await db.mark_notification_read(pool, user["id"], notification_id):
        raise HTTPException(404, "Notification not found")
