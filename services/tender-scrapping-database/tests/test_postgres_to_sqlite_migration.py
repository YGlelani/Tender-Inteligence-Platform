"""Regression tests for the PostgreSQL → SQLite migration utility."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_postgres_to_sqlite.py"
SPEC = importlib.util.spec_from_file_location("migration", SCRIPT)
migration = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def test_normalises_postgres_values(self):
        self.assertEqual(migration._normalise(True), 1)
        self.assertEqual(migration._normalise(False), 0)
        value = datetime(2026, 10, 28, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(migration._normalise(value), value.isoformat(sep=" "))
        self.assertEqual(migration._normalise(date(2026, 10, 29)), "2026-10-29")
        self.assertEqual(migration._normalise(UUID("12345678-1234-5678-1234-567812345678")),
                         "12345678-1234-5678-1234-567812345678")
        self.assertEqual(migration._normalise(Decimal("12.30")), "12.30")
        self.assertEqual(json.loads(migration._normalise(["Gauteng", "Limpopo"])),
                         ["Gauteng", "Limpopo"])
        self.assertEqual(json.loads(migration._normalise({"score": 90})), {"score": 90})
        self.assertEqual(migration._normalise(memoryview(b"data")), b"data")

    def test_refuses_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "existing.db"
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO organisations (name) VALUES (?)", ("Existing organisation",))
            with self.assertRaisesRegex(RuntimeError, "already contains data"):
                migration.migrate("postgresql://not-used", str(db), str(ROOT / "db" / "schema.sql"))
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM organisations").fetchone()[0], 1)

    def test_schema_contains_all_source_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "schema.db"
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(set(migration.TABLES), {
                "organisations", "categories", "users", "pending_registrations", "tenders",
                "tender_contacts", "briefing_sessions", "tender_documents", "scraping_logs",
                "business_documents", "business_profiles", "company_documents",
                "alert_preferences", "saved_tenders", "tender_applications",
                "tender_application_history", "tender_requirements",
                "alert_notifications", "profile_alert_notifications",
            })
            self.assertTrue(set(migration.TABLES).issubset(tables))

    def test_schema_enforces_key_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "schema.db"
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.execute("PRAGMA foreign_keys = ON")
                    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute("INSERT INTO business_profiles (user_id,business_name,industry) VALUES (999,'x','x')")
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute("INSERT INTO tender_application_history (id,application_id,new_status) VALUES ('a','missing','Submitted')")


if __name__ == "__main__":
    unittest.main()
