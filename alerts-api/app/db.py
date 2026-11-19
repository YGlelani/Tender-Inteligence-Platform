import json
from pathlib import Path

from .config import DATABASE_PATH
from .sqlite_pool import SQLitePool

# A tender is open until its closing date, stored in South African time (UTC+2, no daylight
# saving). Tenders saved before closing dates were scraped have none: they count as open for
# 36 days after publishing, the time within which 95% of tenders with a date close.
# The client API uses the same rule.
UNDATED_OPEN_DAYS = 36

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profile_alert_notifications(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    reasons TEXT NOT NULL DEFAULT '[]',
    matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    UNIQUE(user_id, tender_id)
);
CREATE INDEX IF NOT EXISTS idx_profile_alert_notifications_user
    ON profile_alert_notifications(user_id, matched_at DESC);
CREATE INDEX IF NOT EXISTS idx_profile_alert_notifications_unread
    ON profile_alert_notifications(user_id) WHERE read_at IS NULL;
"""



def create_pool():
    path = Path(DATABASE_PATH)
    if not path.is_file():
        raise RuntimeError(f"Shared SQLite database does not exist at {path}")
    return SQLitePool(str(path))


async def ensure_schema(pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


def _decode_json_list(row, key):
    if isinstance(row.get(key), str):
        try:
            row[key] = json.loads(row[key])
        except ValueError:
            row[key] = []


async def _active_profiles(pool, user_id=None):
    """Profiles of active users; all of them, or only `user_id`'s when given."""
    async with pool.acquire() as conn:
        # The Business Profile API creates this table, so it may not exist yet.
        if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'business_profiles')"
        ):
            return []
        rows = await conn.fetch(
            """SELECT bp.id, bp.user_id, u.username, bp.business_name, bp.industry,
                bp.categories, bp.provinces, bp.keywords,
                bp.min_tender_value, bp.max_tender_value,
                bp.services_offered, bp.company_description, bp.province,
                bp.cidb_grade, bp.bbbee_level, bp.created_at, bp.updated_at
            FROM business_profiles bp JOIN users u ON u.id = bp.user_id
            WHERE u.is_active = 1 AND (? IS NULL OR bp.user_id = ?)
            ORDER BY bp.id""",
            user_id, user_id,
        )
    for row in rows:
        for key in ("categories", "provinces", "keywords"):
            _decode_json_list(row, key)
    return rows


async def fetch_business_profile(pool, user_id):
    profiles = await _active_profiles(pool, user_id)
    return profiles[0] if profiles else None


async def list_business_profiles(pool):
    return await _active_profiles(pool)


async def fetch_profile_matching_tenders(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT t.id, t.tender_number, t.title, t.description, t.province,
                t.closing_date, t.published_date, t.status,
                c.name AS category, o.name AS organisation
            FROM tenders t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN organisations o ON o.id = t.organisation_id
            WHERE LOWER(COALESCE(t.status, 'open')) NOT IN ('closed', 'cancelled', 'expired', 'awarded')
              AND (datetime(t.closing_date) >= datetime('now', '+2 hours')
                   OR (datetime(t.closing_date) IS NULL
                       AND (datetime(t.published_date) IS NULL
                            OR datetime(t.published_date) >= datetime('now', '+2 hours', ?))))
            ORDER BY CASE WHEN t.closing_date IS NULL THEN 1 ELSE 0 END,
                t.closing_date ASC, t.published_date DESC""",
            f"-{UNDATED_OPEN_DAYS} days",
        )


async def fetch_notifications(pool, user_id, limit):
    # Do not filter by the stored score here: the service recalculates the
    # score against the user's current profile and applies the 70-point
    # threshold. Stored scores may be stale after profile/tender changes.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT n.id, n.tender_id, t.tender_number, t.title, t.description, t.province,
                c.name AS category, o.name AS organisation, t.status,
                n.score, n.reasons, n.matched_at, n.read_at
            FROM profile_alert_notifications n
            JOIN tenders t ON t.id = n.tender_id
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN organisations o ON o.id = t.organisation_id
            WHERE n.user_id = ?
            ORDER BY n.matched_at DESC
            LIMIT ?""",
            user_id, limit,
        )
    for row in rows:
        _decode_json_list(row, "reasons")
    return rows


async def mark_notification_read(pool, user_id, notification_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """UPDATE profile_alert_notifications SET read_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            RETURNING id""",
            notification_id, user_id,
        )


async def create_notification(pool, profile, tender, score, reasons):
    # Insert, or refresh an existing row; matched_at only moves when something changed.
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """INSERT INTO profile_alert_notifications(user_id, profile_id, tender_id, score, reasons)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, tender_id) DO UPDATE SET
                profile_id = excluded.profile_id,
                score = excluded.score,
                reasons = excluded.reasons,
                matched_at = CASE
                    WHEN profile_alert_notifications.profile_id IS NOT excluded.profile_id
                      OR profile_alert_notifications.score IS NOT excluded.score
                      OR profile_alert_notifications.reasons IS NOT excluded.reasons
                    THEN CURRENT_TIMESTAMP
                    ELSE profile_alert_notifications.matched_at
                END
            RETURNING id""",
            profile["user_id"], profile["id"], tender["id"], score, json.dumps(reasons),
        )
