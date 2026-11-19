#!/usr/bin/env python3
"""Validated, read-only-source migration from the legacy PostgreSQL schema to SQLite.

Install: python -m pip install -r scripts/migration-requirements.txt
Run: python scripts/migrate_postgres_to_sqlite.py --postgres-url "$SOURCE_DATABASE_URL" --sqlite-path ./tenders-migrated.db

The importer requires a NEW destination file and verifies all 19 application tables,
source columns, row counts, and foreign keys before committing. PostgreSQL is never modified.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

TABLES = (
    "organisations", "categories", "users", "pending_registrations", "tenders",
    "tender_contacts", "briefing_sessions", "tender_documents", "scraping_logs",
    "business_documents", "business_profiles", "company_documents",
    "alert_preferences", "saved_tenders", "tender_applications",
    "tender_application_history", "tender_requirements",
    "alert_notifications", "profile_alert_notifications",
)


def _normalise(value: Any) -> Any:
    """Convert psycopg values into SQLite-compatible values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return value


def migrate(postgres_url: str, sqlite_path: str, schema_path: str) -> dict[str, dict[str, int]]:
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError(
            "Missing migration dependency. Run: python -m pip install -r scripts/migration-requirements.txt"
        ) from exc

    destination = Path(sqlite_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    schema_file = Path(schema_path).expanduser().resolve()
    if not schema_file.is_file():
        raise FileNotFoundError(f"SQLite schema not found: {schema_file}")

    with sqlite3.connect(destination) as target:
        target.execute("PRAGMA foreign_keys = ON")
        target.executescript(schema_file.read_text(encoding="utf-8"))
        existing = {
            table: target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in TABLES
        }
        populated = {table: count for table, count in existing.items() if count}
        if populated:
            raise RuntimeError(
                "SQLite destination already contains data; use a new empty destination. "
                f"Existing row counts: {populated}"
            )

    report: dict[str, dict[str, int]] = {}
    with psycopg.connect(postgres_url, row_factory=psycopg.rows.dict_row) as source:
        with source.transaction():
            with sqlite3.connect(destination) as target:
                target.execute("PRAGMA foreign_keys = ON")
                target.execute("BEGIN")
                try:
                    for table in TABLES:
                        source_columns = source.execute(
                            """SELECT column_name FROM information_schema.columns
                               WHERE table_schema = 'public' AND table_name = %s
                               ORDER BY ordinal_position""",
                            (table,),
                        ).fetchall()
                        if not source_columns:
                            raise RuntimeError(
                                f"Required PostgreSQL table public.{table} was not found; "
                                "no migration was committed."
                            )
                        columns = [row["column_name"] for row in source_columns]
                        target_columns_set = {
                            row[1] for row in target.execute(f'PRAGMA table_info("{table}")')
                        }
                        missing = sorted(set(columns) - target_columns_set)
                        if missing:
                            raise RuntimeError(
                                f"PostgreSQL table {table} has columns absent from SQLite: {missing}. "
                                "No migration was committed."
                            )
                        quoted_columns = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
                        query = sql.SQL("SELECT {} FROM {}.{}").format(
                            quoted_columns, sql.Identifier("public"), sql.Identifier(table)
                        )
                        cursor = source.cursor()
                        cursor.execute(query)
                        source_count = 0
                        placeholders = ", ".join("?" for _ in columns)
                        target_columns = ", ".join(f'"{c}"' for c in columns)
                        insert = f'INSERT INTO "{table}" ({target_columns}) VALUES ({placeholders})'
                        while True:
                            rows = cursor.fetchmany(500)
                            if not rows:
                                break
                            target.executemany(
                                insert,
                                [tuple(_normalise(row[c]) for c in columns) for row in rows],
                            )
                            source_count += len(rows)
                        target_count = target.execute(
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0]
                        if source_count != target_count:
                            raise RuntimeError(
                                f"Row-count mismatch for {table}: PostgreSQL={source_count}, SQLite={target_count}"
                            )
                        report[table] = {"postgres_rows": source_count, "sqlite_rows": target_count}

                    violations = target.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        raise RuntimeError(
                            f"SQLite foreign-key validation failed ({len(violations)} violation(s)); "
                            "no migration was committed."
                        )
                    for table in TABLES:
                        columns = {r[1] for r in target.execute(f'PRAGMA table_info("{table}")')}
                        if "id" in columns:
                            target.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                            target.execute(
                                "INSERT INTO sqlite_sequence(name, seq) "
                                f'SELECT ?, COALESCE(MAX(id), 0) FROM "{table}"',
                                (table,),
                            )
                    target.commit()
                except Exception:
                    target.rollback()
                    raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", default=os.getenv("SOURCE_DATABASE_URL"),
                        help="PostgreSQL connection URL (or set SOURCE_DATABASE_URL)")
    parser.add_argument("--sqlite-path", default="./tenders-migrated.db",
                        help="Path to a NEW SQLite database file")
    parser.add_argument("--schema", default=str(Path(__file__).resolve().parents[1] / "db" / "schema.sql"),
                        help="Path to the canonical SQLite schema")
    args = parser.parse_args()
    if not args.postgres_url:
        parser.error("provide --postgres-url or set SOURCE_DATABASE_URL")
    try:
        report = migrate(args.postgres_url, args.sqlite_path, args.schema)
    except Exception as exc:
        print(f"MIGRATION FAILED: {exc}", file=sys.stderr)
        return 1
    print("Migration completed. PostgreSQL was read only.")
    for table, counts in report.items():
        print(f"{table}: PostgreSQL={counts['postgres_rows']} SQLite={counts['sqlite_rows']}")
    print(f"SQLite destination: {Path(args.sqlite_path).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
