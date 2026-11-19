
from contextlib import asynccontextmanager
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")

# A tender is open until its closing date, stored in South African time (UTC+2, no daylight
# saving). Tenders saved before closing dates were scraped have none: they count as open for
# 36 days after publishing, the time within which 95% of tenders with a date close.
# Keep in step with scraper-api/app/database.py.
UNDATED_OPEN_DAYS = 36
OPEN_BY_DATE = """(
    datetime(t.closing_date) >= datetime('now', '+2 hours')
    OR (datetime(t.closing_date) IS NULL
        AND (datetime(t.published_date) IS NULL
             OR datetime(t.published_date) >= datetime('now', '+2 hours', ?)))
)"""


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    value = str(value)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%A, %d %B %Y - %H:%M",
        "%A, %d %B %Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _db_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def _load_schema() -> str:
    """Load the canonical SQLite schema from the repository's db/ folder."""
    candidates = [
        Path(__file__).resolve().parents[2] / "db" / "schema.sql",
        Path("/app/db/schema.sql"),
    ]
    for schema_path in candidates:
        if schema_path.is_file():
            return schema_path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        "db/schema.sql not found; build the API image from the repository root"
    )



class TenderDB:
    def __init__(self, database_path: str = DATABASE_PATH):
        self.database_path = database_path

    @classmethod
    async def connect(cls) -> "TenderDB":
        path = Path(DATABASE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        db = cls(str(path))
        async with aiosqlite.connect(db.database_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.executescript(_load_schema())
            await conn.commit()
        return db

    @asynccontextmanager
    async def _connect(self):
        # Enter aiosqlite's context before its worker thread is started.
        async with aiosqlite.connect(self.database_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    async def close(self):
        # Connections are opened and closed per operation.
        return None

    def _filter_sql(
        self,
        status=None,
        province=None,
        category=None,
        organisation=None,
        closing_before=None,
        closing_after=None,
        keyword=None,
    ):
        conditions = []
        params = []

        if status:
            conditions.append("t.status = ?")
            params.append(status)
        if status and status.lower() == "open":
            # The stored status can stay "Open" after a tender closes, so the dates decide.
            conditions.append(OPEN_BY_DATE)
            params.append(f"-{UNDATED_OPEN_DAYS} days")
        if province:
            conditions.append("t.province LIKE ?")
            params.append(f"%{province}%")
        if category:
            conditions.append("cat.name LIKE ?")
            params.append(f"%{category}%")
        if organisation:
            conditions.append("o.name LIKE ?")
            params.append(f"%{organisation}%")
        if closing_before:
            conditions.append("t.closing_date <= ?")
            params.append(_db_value(_parse_ts(closing_before)))
        if closing_after:
            conditions.append("t.closing_date >= ?")
            params.append(_db_value(_parse_ts(closing_after)))
        if keyword:
            conditions.append(
                """
                (
                    t.title LIKE ? OR t.description LIKE ?
                    OR t.tender_number LIKE ? OR o.name LIKE ?
                    OR cat.name LIKE ?
                )
                """
            )
            wildcard = f"%{keyword}%"
            params.extend([wildcard] * 5)

        where = " AND ".join(conditions) if conditions else "1 = 1"
        return where, params

    async def list_tenders(
        self,
        status: Optional[str] = None,
        province: Optional[str] = None,
        category: Optional[str] = None,
        organisation: Optional[str] = None,
        closing_before=None,
        closing_after=None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        where, params = self._filter_sql(
            status, province, category, organisation,
            closing_before, closing_after, keyword,
        )

        sql = f"""
            SELECT
                t.tender_number, t.title, t.description, t.status,
                t.province, t.closing_date, t.published_date,
                c.telephone AS contact_telephone,
                c.email AS contact_email,
                o.name AS organisation_name,
                cat.name AS category_name,
                COALESCE(b.is_there_a_briefing, 0) AS has_briefing,
                b.briefing_venue,
                (
                    SELECT json_group_array(d.document_url)
                    FROM tender_documents d
                    WHERE d.tender_id = t.id
                ) AS document_urls
            FROM tenders t
            LEFT JOIN organisations o ON o.id = t.organisation_id
            LEFT JOIN categories cat ON cat.id = t.category_id
            LEFT JOIN tender_contacts c ON c.tender_id = t.id
            LEFT JOIN briefing_sessions b ON b.tender_id = t.id
            WHERE {where}
            ORDER BY
                CASE WHEN t.closing_date IS NULL THEN 1 ELSE 0 END,
                t.closing_date ASC,
                t.tender_number
            LIMIT ? OFFSET ?
        """

        async with self._connect() as conn:
            cursor = await conn.execute(sql, [*params, limit, offset])
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            item = dict(row)
            try:
                item["document_urls"] = json.loads(
                    item["document_urls"] or "[]"
                )
            except (TypeError, json.JSONDecodeError):
                item["document_urls"] = []
            item["has_briefing"] = bool(item["has_briefing"])
            results.append(item)
        return results

    async def count_tenders(
        self,
        status: Optional[str] = None,
        province: Optional[str] = None,
        category: Optional[str] = None,
        organisation: Optional[str] = None,
        closing_before=None,
        closing_after=None,
        keyword: Optional[str] = None,
    ) -> int:
        where, params = self._filter_sql(
            status, province, category, organisation,
            closing_before, closing_after, keyword,
        )

        sql = f"""
            SELECT COUNT(DISTINCT t.id)
            FROM tenders t
            LEFT JOIN organisations o ON o.id = t.organisation_id
            LEFT JOIN categories cat ON cat.id = t.category_id
            WHERE {where}
        """

        async with self._connect() as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            return int(row[0])

    async def get_tender_detail(self, tender_number: str):
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT
                    t.*, o.name AS organisation_name,
                    cat.name AS category_name,
                    c.contact_person, c.email AS contact_email,
                    c.telephone AS contact_telephone,
                    c.fax_number AS contact_fax,
                    b.is_there_a_briefing AS has_briefing,
                    b.is_compulsory, b.briefing_date_time,
                    b.briefing_venue
                FROM tenders t
                LEFT JOIN organisations o ON o.id = t.organisation_id
                LEFT JOIN categories cat ON cat.id = t.category_id
                LEFT JOIN tender_contacts c ON c.tender_id = t.id
                LEFT JOIN briefing_sessions b ON b.tender_id = t.id
                WHERE t.tender_number = ?
                """,
                (tender_number,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            tender = dict(row)
            docs_cursor = await conn.execute(
                """
                SELECT document_name AS name,
                       document_type AS type,
                       document_url AS url,
                       date_uploaded
                FROM tender_documents
                WHERE tender_id = ?
                ORDER BY id
                """,
                (tender["id"],),
            )
            tender["documents"] = [
                dict(doc) for doc in await docs_cursor.fetchall()
            ]

        return {
            "tender_number": tender["tender_number"],
            "title": tender["title"],
            "description": tender["description"],
            "status": tender["status"],
            "tender_type": tender["tender_type"],
            "province": tender["province"],
            "location": tender["location"],
            "published_date": tender["published_date"],
            "closing_date": tender["closing_date"],
            "special_conditions": tender["special_conditions"],
            "tender_url": tender["tender_url"],
            "source": tender["source"],
            "organisation": tender["organisation_name"],
            "category": tender["category_name"],
            "contact": {
                "person": tender["contact_person"],
                "email": tender["contact_email"],
                "telephone": tender["contact_telephone"],
                "fax": tender["contact_fax"],
            },
            "briefing": {
                "has_briefing": bool(tender["has_briefing"]),
                "is_compulsory": bool(tender["is_compulsory"]),
                "datetime": tender["briefing_date_time"],
                "venue": tender["briefing_venue"],
            },
            "documents": tender["documents"],
        }

    async def get_dashboard_stats(self):
        async with self._connect() as conn:
            async def scalar(sql, params=()):
                cursor = await conn.execute(sql, params)
                row = await cursor.fetchone()
                return row[0] if row else 0

            total = await scalar("SELECT COUNT(*) FROM tenders")
            opened = await scalar(
                "SELECT COUNT(*) FROM tenders WHERE status = 'Open'"
            )
            closing_week = await scalar(
                """
                SELECT COUNT(*) FROM tenders
                WHERE closing_date >= datetime('now')
                  AND closing_date <= datetime('now', '+7 days')
                """
            )
            closing_month = await scalar(
                """
                SELECT COUNT(*) FROM tenders
                WHERE closing_date >= datetime('now')
                  AND closing_date <= datetime('now', '+30 days')
                """
            )
            organisations = await scalar("SELECT COUNT(*) FROM organisations")
            categories = await scalar("SELECT COUNT(*) FROM categories")
            documents = await scalar("SELECT COUNT(*) FROM tender_documents")

            cursor = await conn.execute(
                """
                SELECT province, COUNT(*) AS count
                FROM tenders
                WHERE province IS NOT NULL
                GROUP BY province
                ORDER BY count DESC
                """
            )
            by_province = [
                {"province": row["province"], "count": row["count"]}
                for row in await cursor.fetchall()
            ]

            cursor = await conn.execute(
                """
                SELECT c.name AS category, COUNT(t.id) AS count
                FROM categories c
                LEFT JOIN tenders t ON t.category_id = c.id
                GROUP BY c.name
                ORDER BY count DESC
                LIMIT 10
                """
            )
            by_category = [
                {"category": row["category"], "count": row["count"]}
                for row in await cursor.fetchall()
            ]

            cursor = await conn.execute(
                """
                SELECT started_at, completed_at, status,
                       tenders_found, tenders_added
                FROM scraping_logs
                ORDER BY id DESC LIMIT 1
                """
            )
            row = await cursor.fetchone()
            last_scrape = dict(row) if row else None

        return {
            "total_tenders": total,
            "open_tenders": opened,
            "closing_this_week": closing_week,
            "closing_this_month": closing_month,
            "total_organisations": organisations,
            "total_categories": categories,
            "total_documents": documents,
            "by_province": by_province,
            "by_category": by_category,
            "last_scrape": last_scrape,
        }
