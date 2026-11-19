import asyncio
import logging

from . import db
from .documents import cached_details, with_documents
from .matching import score_profile
from .ml_categories import shared_categories

logger = logging.getLogger("alerts-api")

# Only surface strong Smart Alerts notifications to users.
MIN_ALERT_MATCH_SCORE = 70


async def get_profile_matches(pool, profile):
    """Canonical live matches shared by the matches and notifications endpoints."""
    tenders = await db.fetch_profile_matching_tenders(pool)
    ml_matches = await shared_categories(profile, tenders) or {}
    matches = []
    for tender in tenders:
        score, reasons = score_profile(profile, tender, ml_category=ml_matches.get(str(tender["id"])))
        if score <= 0:
            continue
        matches.append({"tender": tender, "score": score, "reasons": reasons})

    matches.sort(key=lambda item: (
        -item["score"],
        item["tender"].get("closing_date") is None,
        item["tender"].get("closing_date") or "",
    ))
    return matches


async def get_alert_matches(pool, profile):
    """Live matches strong enough to notify the user about."""
    return [
        match for match in await get_profile_matches(pool, profile)
        if match["score"] >= MIN_ALERT_MATCH_SCORE
    ]


async def current_notifications(pool, profile, limit=100):
    """The user's alerts for their current strong matches, best first.

    A strong match the background scanner hasn't stored yet gets its
    notification row created here, so the user sees it straight away and
    can mark it as read. Scores and reasons are always the live values.
    """
    alert_matches = (await get_alert_matches(pool, profile))[:limit]
    alert_ids = {int(match["tender"]["id"]) for match in alert_matches}
    stored = {
        int(row["tender_id"]): dict(row)
        for row in await db.fetch_notifications(pool, profile["user_id"], 1000)
        if row.get("tender_id") is not None and int(row["tender_id"]) in alert_ids
    }

    notifications = []
    for match in alert_matches:
        tender = match["tender"]
        item = stored.get(int(tender["id"]))
        if not item:
            created = await db.create_notification(pool, profile, tender, match["score"], match["reasons"])
            if not created or created.get("id") is None:
                continue
            item = {
                "id": int(created["id"]),
                "tender_id": int(tender["id"]),
                "matched_at": tender.get("published_date") or "1970-01-01T00:00:00",
                "read_at": None,
            }
        item.update(
            score=match["score"],
            reasons=match["reasons"],
            tender_number=tender["tender_number"],
            title=tender["title"],
        )
        notifications.append(item)
    return notifications


async def scan_alerts(pool):
    profiles = await db.list_business_profiles(pool)
    created = 0

    for profile in profiles:
        profile = with_documents(profile, cached_details(profile["user_id"]))

        for match in await get_alert_matches(pool, profile):
            result = await db.create_notification(
                pool,
                profile,
                match["tender"],
                match["score"],
                match["reasons"],
            )

            if result:
                created += 1

    if created:
        logger.info("Created %s profile-based tender notification(s)", created)

    return created

async def background_scanner(pool, stop_event: asyncio.Event, interval: int):
    while not stop_event.is_set():
        try:
            await scan_alerts(pool)
        except Exception:
            logger.exception("Profile-based alert scan failed")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval,
            )
        except asyncio.TimeoutError:
            pass
