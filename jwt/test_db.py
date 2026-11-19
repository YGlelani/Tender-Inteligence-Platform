"""SQLite database smoke test for the JWT API.

The CI workflow creates an isolated SQLite database at DATABASE_PATH.
This test intentionally does not connect to a production database.
"""
import os
import sqlite3


def test_sqlite_database_has_users_table():
    database_path = os.getenv("DATABASE_PATH", "/data/tenders.db")
    if not os.path.isfile(database_path):
        # In a local environment without the production volume, skip safely.
        import pytest
        pytest.skip(f"SQLite database not available at {database_path}")

    connection = sqlite3.connect(database_path)
    try:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        assert result is not None, "SQLite database is missing the users table"
    finally:
        connection.close()
