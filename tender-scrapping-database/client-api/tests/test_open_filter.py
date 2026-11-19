"""An "Open" tender past its closing date, or undated and published over 36 days ago, is not listed."""
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLIENT_API_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_API_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_API_DIR))

from app.database import TenderDB  # noqa: E402

SOUTH_AFRICA = timezone(timedelta(hours=2))
SCHEMA = """
    CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE organisations (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE tenders (
        id INTEGER PRIMARY KEY, tender_number TEXT, title TEXT, description TEXT, status TEXT,
        province TEXT, closing_date TEXT, published_date TEXT, organisation_id INTEGER, category_id INTEGER
    );
"""
QUERY = """
    SELECT t.id FROM tenders t
    LEFT JOIN categories cat ON cat.id = t.category_id
    LEFT JOIN organisations o ON o.id = t.organisation_id
    WHERE {where} ORDER BY t.id
"""


def _in_hours(hours):
    return (datetime.now(SOUTH_AFRICA) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _listed(status):
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    connection.executemany(
        "INSERT INTO tenders (id, status, closing_date, published_date) VALUES (?, ?, ?, ?)",
        [
            (1, "Open", _in_hours(2), _in_hours(-24 * 20)),          # closes later today: still open
            (2, "Open", _in_hours(-2), _in_hours(-24 * 20)),         # closed two hours ago
            (3, "Open", None, _in_hours(-24 * 10)),                  # no closing date, published 10 days ago
            (4, "Open", "not a date", _in_hours(-24 * 10)),          # unreadable closing date, recent
            (5, "Closed", _in_hours(48), _in_hours(-24 * 10)),
            (6, "Open", None, _in_hours(-24 * 40)),                  # no closing date, published 40 days ago
            (7, "Open", None, None),                                 # nothing to judge by: kept
        ],
    )
    where, params = TenderDB(":memory:")._filter_sql(status=status)
    # The WHERE clause is built by _filter_sql with ? placeholders for every value.
    rows = connection.execute(QUERY.format(where=where), params).fetchall()  # nosec B608
    return [row[0] for row in rows]


class OpenFilterTest(unittest.TestCase):
    def test_open_uses_the_closing_date_or_36_days_after_publishing(self):
        self.assertEqual(_listed("Open"), [1, 3, 4, 7])

    def test_other_statuses_are_not_affected(self):
        self.assertEqual(_listed("Closed"), [5])


if __name__ == "__main__":
    unittest.main()
