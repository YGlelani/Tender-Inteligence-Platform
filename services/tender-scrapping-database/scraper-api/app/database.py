
from contextlib import asynccontextmanager
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import Tender
from .config import get_settings

settings = get_settings()

# A tender is open until its closing date, stored in South African time (UTC+2, no daylight
# saving). Tenders saved before closing dates were scraped have none: they count as open for
# 36 days after publishing, the time within which 95% of tenders with a date close.
# Keep in step with client-api/app/database.py.
UNDATED_OPEN_DAYS = 36
OPEN_BY_DATE = """(
    datetime(t.closing_date) >= datetime('now', '+2 hours')
    OR (datetime(t.closing_date) IS NULL
        AND (datetime(t.published_date) IS NULL
             OR datetime(t.published_date) >= datetime('now', '+2 hours', ?)))
)"""
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")



from datetime import datetime



import re
from datetime import datetime, timedelta


def _parse_ts(value):
    """Parse absolute and relative closing dates from eTenders."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    value = str(value).strip()
    if not value or value.upper() in {"N/A", "NA", "NONE", "-"}:
        return None

    # Handle values such as "in 35 days" or "35 days".
    match = re.fullmatch(
        r"(?:in\s+)?(\d+)\s+days?",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=int(match.group(1)))

    # Handle ISO timestamps and dates.
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00") if value.endswith("Z") else value
        )
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%A, %d %B %Y - %H:%M",
        "%A, %d %B %Y",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    print(f"[DB WARN] Unrecognised date format: {value!r}")
    return None




def _db_value(value):
    """Convert Python dates to values SQLite can store consistently."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, bool):
        return int(value)
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



async def _fetchone(conn, sql, params=()):
    """Execute a query and return one row using supported aiosqlite APIs."""
    cursor = await conn.execute(sql, params)
    try:
        return await cursor.fetchone()
    finally:
        await cursor.close()


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
        # Do not await the connection before entering its context manager:
        # aiosqlite starts its worker thread on first await/entry, and starting
        # it twice raises "threads can only be started once".
        async with aiosqlite.connect(self.database_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    async def close(self):
        # Connections are opened and closed per operation.
        return None

    # --------------------------------------------------------------
    # Logging
    # --------------------------------------------------------------
    async def start_log(self, source: str) -> int:
        async with self._connect() as conn:
            cursor = await conn.execute(
                "INSERT INTO scraping_logs (source, status) VALUES (?, 'Running')",
                (source,),
            )
            await conn.commit()
            return cursor.lastrowid

    async def complete_log(
        self,
        log_id: int,
        found: int,
        added: int,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                UPDATE scraping_logs
                SET tenders_found = ?,
                    tenders_added = ?,
                    status = ?,
                    error_message = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (found, added, status, error, log_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def tender_exists(self, tender_number: str | None) -> bool:
        if not tender_number:
            return False
        async with self._connect() as conn:
            row = await _fetchone(conn, "SELECT 1 FROM tenders WHERE tender_number = ?", (tender_number,))
            return row is not None

    # --------------------------------------------------------------
    # Save or update a tender
    # `status` is the status of the eTenders list the tender was found on.
    # Returns "new", "updated", or "skipped"
    # --------------------------------------------------------------
    async def save_tender(self, tender: Tender, source: str, status: str = "Open") -> str:
        if not tender.tender_number:
            return "skipped"

        async with self._connect() as conn:
            try:
                await conn.execute("BEGIN")

                existing = await _fetchone(conn,
                    "SELECT id FROM tenders WHERE tender_number = ?",
                    (tender.tender_number,),
                )
                is_new = existing is None

                organisation_name = tender.organ_of_state or "Unknown"
                category_name = tender.category or "Uncategorised"

                await conn.execute(
                    """
                    INSERT INTO organisations (name)
                    VALUES (?)
                    ON CONFLICT(name) DO NOTHING
                    """,
                    (organisation_name,),
                )
                await conn.execute(
                    """
                    INSERT INTO categories (name)
                    VALUES (?)
                    ON CONFLICT(name) DO NOTHING
                    """,
                    (category_name,),
                )

                org_row = await _fetchone(conn,
                    "SELECT id FROM organisations WHERE name = ?",
                    (organisation_name,),
                )
                category_row = await _fetchone(conn,
                    "SELECT id FROM categories WHERE name = ?",
                    (category_name,),
                )

                await conn.execute(
                    """
                    INSERT INTO tenders (
                        tender_number, title, description,
                        organisation_id, category_id, tender_type,
                        province, location, published_date, closing_date,
                        special_conditions, tender_url, source, status,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            CURRENT_TIMESTAMP)
                    ON CONFLICT(tender_number) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        organisation_id = excluded.organisation_id,
                        category_id = excluded.category_id,
                        tender_type = excluded.tender_type,
                        province = excluded.province,
                        location = excluded.location,
                        published_date = COALESCE(excluded.published_date, tenders.published_date),
                        closing_date = COALESCE(excluded.closing_date, tenders.closing_date),
                        special_conditions = excluded.special_conditions,
                        tender_url = excluded.tender_url,
                        source = excluded.source,
                        status = excluded.status,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        tender.tender_number,
                        (tender.description or "")[:200],
                        tender.description,
                        org_row["id"],
                        category_row["id"],
                        tender.tender_type,
                        tender.province,
                        tender.location,
                        _db_value(_parse_ts(tender.published_date)),
                        _db_value(_parse_ts(tender.closing_date)),
                        tender.special_conditions,
                        tender.detail_url,
                        source,
                        status,
                    ),
                )

                tender_row = await _fetchone(conn,
                    "SELECT id FROM tenders WHERE tender_number = ?",
                    (tender.tender_number,),
                )
                tender_id = tender_row["id"]

                # Match the existing PostgreSQL procedure behaviour:
                # replace contact details when a person or email is provided.
                if tender.contact_person or tender.contact_email:
                    await conn.execute(
                        "DELETE FROM tender_contacts WHERE tender_id = ?",
                        (tender_id,),
                    )
                    await conn.execute(
                        """
                        INSERT INTO tender_contacts (
                            tender_id, contact_person, email, telephone, fax_number
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            tender_id,
                            tender.contact_person,
                            tender.contact_email,
                            tender.contact_telephone,
                            tender.contact_fax,
                        ),
                    )

                if tender.has_briefing:
                    await conn.execute(
                        "DELETE FROM briefing_sessions WHERE tender_id = ?",
                        (tender_id,),
                    )
                    await conn.execute(
                        """
                        INSERT INTO briefing_sessions (
                            tender_id, is_there_a_briefing, is_compulsory,
                            briefing_date_time, briefing_venue
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            tender_id,
                            1,
                            int(bool(tender.is_compulsory)),
                            _db_value(_parse_ts(tender.briefing_datetime)),
                            tender.briefing_venue,
                        ),
                    )

                for doc in tender.documents:
                    try:
                        await conn.execute(
                            """
                            INSERT INTO tender_documents (
                                tender_id, document_name, document_type, document_url
                            ) VALUES (?, ?, ?, ?)
                            ON CONFLICT(document_url) DO NOTHING
                            """,
                            (
                                tender_id,
                                (doc.get("name") or "Document")[:255],
                                doc.get("type"),
                                doc.get("url"),
                            ),
                        )
                    except Exception as exc:
                        print(
                            f"[DB WARN] Document insert failed for "
                            f"{doc.get('url')}: {exc}"
                        )

                await conn.commit()
                return "new" if is_new else "updated"

            except Exception:
                await conn.rollback()
                raise

    # --------------------------------------------------------------
    # Shared filters for list/count operations
    # --------------------------------------------------------------
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

    # --------------------------------------------------------------
    # Read methods
    # --------------------------------------------------------------
    async def list_tenders(
        self,
        status: str | None = None,
        province: str | None = None,
        category: str | None = None,
        organisation: str | None = None,
        closing_before=None,
        closing_after=None,
        keyword: str | None = None,
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
                item["document_urls"] = json.loads(item["document_urls"] or "[]")
            except (TypeError, json.JSONDecodeError):
                item["document_urls"] = []
            item["has_briefing"] = bool(item["has_briefing"])
            results.append(item)
        return results

    async def count_tenders(
        self,
        status: str | None = None,
        province: str | None = None,
        category: str | None = None,
        organisation: str | None = None,
        closing_before=None,
        closing_after=None,
        keyword: str | None = None,
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
                SELECT document_name AS name, document_type AS type,
                       document_url AS url, date_uploaded
                FROM tender_documents
                WHERE tender_id = ?
                ORDER BY id
                """,
                (tender["id"],),
            )
            tender["documents"] = [dict(d) for d in await docs_cursor.fetchall()]

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

    async def list_scraping_logs(self, limit: int = 50, offset: int = 0):
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, source, started_at, completed_at,
                       tenders_found, tenders_added, status, error_message
                FROM scraping_logs
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get_scraping_log(self, log_id: int):
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, source, started_at, completed_at,
                       tenders_found, tenders_added, status, error_message
                FROM scraping_logs
                WHERE id = ?
                """,
                (log_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
