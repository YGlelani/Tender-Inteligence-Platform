"""Expired password-reset codes are deleted at startup and then every hour."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    con = sqlite3.connect(path)
    main.ensure_reset_table(con)
    now = datetime.now(UTC)
    rows = [
        ("valid@company.co.za", (now + timedelta(minutes=5)).isoformat()),
        ("expired@company.co.za", (now - timedelta(minutes=1)).isoformat()),
        ("old@company.co.za", (now - timedelta(days=40)).isoformat()),
        ("naive@company.co.za", (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()),
        ("garbled@company.co.za", "not a date"),
    ]
    con.executemany(
        "INSERT INTO password_reset_codes (username, code_hash, expires_at, attempts, created_at) "
        "VALUES (?, 'h', ?, 0, ?)",
        [(user, expires, now.isoformat()) for user, expires in rows],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    return path


def usernames(path):
    con = sqlite3.connect(path)
    try:
        return {row[0] for row in con.execute("SELECT username FROM password_reset_codes")}
    finally:
        con.close()


def test_purge_keeps_only_codes_that_are_still_valid(db):
    assert main.purge_expired_reset_codes() == 4
    assert usernames(db) == {"valid@company.co.za"}


def test_startup_runs_the_purge(db):
    with TestClient(main.app):
        pass

    assert usernames(db) == {"valid@company.co.za"}


def test_startup_survives_a_missing_database(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(main, "DATABASE_PATH", str(tmp_path / "missing.db"))

    with TestClient(main.app) as client:
        assert client.get("/docs").status_code in (200, 404)
    assert "Could not delete expired password-reset codes" in caplog.text
