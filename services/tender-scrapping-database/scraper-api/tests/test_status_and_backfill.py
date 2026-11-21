"""Tenders keep the status of the eTenders list they were found on, and the backfill refreshes old ones."""
import asyncio
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRAPER_API_DIR = Path(__file__).resolve().parents[1]
if str(SCRAPER_API_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_API_DIR))

from app import backfill, database  # noqa: E402
from app.models import Tender  # noqa: E402

SOUTH_AFRICA = timezone(timedelta(hours=2))


def _tender(number, closing=None):
    return Tender(tender_number=number, description=f"Tender {number}", published_date="Thursday, 1 October 2026",
                  closing_date=closing)


class StoredTenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = str(Path(self.tmp.name) / "tenders.db")
        database.DATABASE_PATH = self.path
        self.db = asyncio.run(database.TenderDB.connect())

    def tearDown(self):
        self.tmp.cleanup()

    def _row(self, number):
        with sqlite3.connect(self.path) as connection:
            return connection.execute(
                "SELECT status, closing_date FROM tenders WHERE tender_number = ?", (number,)
            ).fetchone()

    def test_saving_from_the_closed_list_marks_the_tender_closed_and_fills_its_date(self):
        asyncio.run(self.db.save_tender(_tender("T1"), source="test"))
        self.assertEqual(self._row("T1"), ("Open", None))

        closed = _tender("T1", closing="Friday, 13 November 2026 - 12:00")
        asyncio.run(self.db.save_tender(closed, source="test", status="Closed"))

        self.assertEqual(self._row("T1"), ("Closed", "2026-11-13 12:00:00"))

    def test_closed_list_backfill_only_updates_stored_tenders(self):
        asyncio.run(self.db.save_tender(_tender("T1"), source="test"))

        counts = asyncio.run(backfill.save_found(self.db, [_tender("T1"), _tender("T9")], "closed"))

        self.assertEqual(counts, {"updated": 1, "not_stored": 1})
        self.assertEqual(self._row("T1")[0], "Closed")
        self.assertIsNone(self._row("T9"))

    def test_current_list_backfill_adds_new_tenders(self):
        counts = asyncio.run(backfill.save_found(self.db, [_tender("T2", closing="Friday, 4 December 2026")], "current"))

        self.assertEqual(counts, {"new": 1})
        self.assertEqual(self._row("T2"), ("Open", "2026-12-04 00:00:00"))


class OpenFilterTest(unittest.TestCase):
    def test_open_uses_the_closing_date_or_36_days_after_publishing(self):
        def stamp(days):
            return (datetime.now(SOUTH_AFRICA) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        connection = sqlite3.connect(":memory:")
        connection.executescript("""
            CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE organisations (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE tenders (id INTEGER PRIMARY KEY, tender_number TEXT, title TEXT, description TEXT,
                status TEXT, province TEXT, closing_date TEXT, published_date TEXT,
                organisation_id INTEGER, category_id INTEGER);
        """)
        connection.executemany(
            "INSERT INTO tenders (id, status, closing_date, published_date) VALUES (?, 'Open', ?, ?)",
            [(1, stamp(1), stamp(-60)), (2, stamp(-1), stamp(-5)), (3, None, stamp(-10)), (4, None, stamp(-40))],
        )
        where, params = database.TenderDB(":memory:")._filter_sql(status="Open")
        query = ("SELECT t.id FROM tenders t LEFT JOIN categories cat ON cat.id = t.category_id "
                 "LEFT JOIN organisations o ON o.id = t.organisation_id WHERE " + where + " ORDER BY t.id")
        # The WHERE clause is built by _filter_sql with ? placeholders for every value.
        listed = [row[0] for row in connection.execute(query, params).fetchall()]  # nosec B608

        self.assertEqual(listed, [1, 3])


if __name__ == "__main__":
    unittest.main()
