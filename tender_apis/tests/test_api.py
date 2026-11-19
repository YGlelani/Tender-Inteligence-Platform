import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
import main

SECRET = "test-secret-that-is-at-least-32-bytes-long"
INTERNAL_KEY = "internal-test-key"
client = TestClient(main.app)

SHARED_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE, hashed_password TEXT NOT NULL DEFAULT 'x', is_active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE tenders (id INTEGER PRIMARY KEY AUTOINCREMENT, tender_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL, closing_date TEXT, status TEXT DEFAULT 'Open');
CREATE TABLE saved_tenders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    tender_id INTEGER NOT NULL, UNIQUE(user_id, tender_id));
CREATE TABLE profile_alert_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL DEFAULT 1, tender_id INTEGER NOT NULL, score INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]', matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, read_at TEXT,
    UNIQUE(user_id, tender_id));
"""


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    db_path = tmp_path / "tenders.db"
    con = sqlite3.connect(db_path)
    con.executescript(SHARED_SCHEMA)
    con.execute("INSERT INTO users(username, email) VALUES ('alice@acme.co.za', 'alice@acme.co.za')")
    con.execute("INSERT INTO users(username, email) VALUES ('bob@acme.co.za', 'bob@acme.co.za')")
    con.commit()
    con.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(main, "JWT_SECRET", SECRET)
    monkeypatch.setattr(main, "INTERNAL_API_KEY", INTERNAL_KEY)
    monkeypatch.setattr(main, "PUBLIC_API_URL", "http://api.test:9007")
    sent = []
    monkeypatch.setattr(main, "send_email", lambda to, subject, text, html: sent.append((to, subject, text)))
    main.initialize_database()
    yield sent


def sql(query, params=()):
    con = sqlite3.connect(main.DATABASE_PATH)
    try:
        cur = con.execute(query, params)
        con.commit()
        return cur.fetchall()
    finally:
        con.close()


def auth(username="alice@acme.co.za"):
    token = jwt.encode({"sub": username, "exp": 4102444800}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def internal(payload, key=INTERNAL_KEY):
    return client.post("/internal/notifications", json=payload, headers={"X-Internal-Key": key})


def add_saved_tender(user_id, number, closing_date, status="Open"):
    con = sqlite3.connect(main.DATABASE_PATH)
    try:
        tender_id = con.execute(
            "INSERT INTO tenders(tender_number, title, closing_date, status) VALUES (?, ?, ?, ?)",
            (number, f"Tender {number}", closing_date, status),
        ).lastrowid
        con.execute("INSERT INTO saved_tenders(user_id, tender_id) VALUES (?, ?)", (user_id, tender_id))
        con.commit()
        return tender_id
    finally:
        con.close()


def test_health_reports_service_and_database():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "notifications-api", "database": "connected"}


def test_authentication_is_required():
    assert client.get("/notifications").status_code == 401
    assert client.get("/notifications", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_internal_endpoint_requires_key():
    assert internal({"username": "alice@acme.co.za", "type": "profile_updated"}, key="wrong").status_code == 401


def test_internal_rejects_non_internal_types():
    assert internal({"username": "alice@acme.co.za", "type": "new_matches"}).status_code == 400


def test_profile_updated_shows_in_bell_without_email(setup):
    assert internal({"username": "alice@acme.co.za", "type": "profile_updated"}).status_code == 201
    items = client.get("/notifications", headers=auth()).json()
    assert [i["type"] for i in items] == ["profile_updated"]
    assert items[0]["is_read"] is False
    assert client.get("/notifications/unread-count", headers=auth()).json() == {"unread": 1}
    assert client.get("/notifications", headers=auth("bob@acme.co.za")).json() == []
    main.run_job_once()
    assert setup == []


def test_password_changed_cannot_be_hidden_by_stored_preference(setup):
    sql("INSERT INTO notification_preferences(user_id, type, in_app, email) VALUES (1, 'password_changed', 0, 0)")
    internal({"user_id": 1, "type": "password_changed"})
    assert len(client.get("/notifications", headers=auth()).json()) == 1
    assert len(setup) == 1


def test_password_changed_is_emailed_immediately(setup):
    assert internal({"user_id": 1, "type": "password_changed"}).status_code == 201
    assert len(setup) == 1
    to, subject, text = setup[0]
    assert to == "alice@acme.co.za"
    assert "unsubscribe" not in text.lower()


def test_mark_read_and_read_all():
    internal({"user_id": 1, "type": "profile_updated"})
    internal({"user_id": 1, "type": "password_changed"})
    first = client.get("/notifications", headers=auth()).json()[0]
    assert client.post(f"/notifications/{first['id']}/read", headers=auth("bob@acme.co.za")).status_code == 404
    assert client.post(f"/notifications/{first['id']}/read", headers=auth()).status_code == 204
    assert client.get("/notifications/unread-count", headers=auth()).json() == {"unread": 1}
    assert client.post("/notifications/read-all", headers=auth()).json() == {"updated": 1}
    assert client.get("/notifications?unread_only=true", headers=auth()).json() == []


def test_preferences_defaults_and_update():
    prefs = {p["type"]: p for p in client.get("/notification-preferences", headers=auth()).json()["preferences"]}
    assert prefs["password_changed"]["locked"] is True
    assert prefs["tender_closing_soon"]["email"] is True
    assert prefs["new_matches"]["email"] is False
    response = client.put("/notification-preferences", headers=auth(),
                          json={"preferences": [{"type": "profile_updated", "in_app": False, "email": False}]})
    assert response.status_code == 200
    internal({"user_id": 1, "type": "profile_updated"})
    assert client.get("/notifications", headers=auth()).json() == []


def test_locked_type_cannot_be_disabled():
    response = client.put("/notification-preferences", headers=auth(),
                          json={"preferences": [{"type": "password_changed", "in_app": False, "email": True}]})
    assert response.status_code == 400


def test_closing_soon_reminders_once_per_window(setup):
    soon = (datetime.now(timezone.utc) + timedelta(hours=60)).isoformat()
    add_saved_tender(1, "T-1", soon)
    main.run_job_once()
    main.run_job_once()
    items = client.get("/notifications", headers=auth()).json()
    assert [i["type"] for i in items] == ["tender_closing_soon"]
    assert "3 days" in items[0]["message"]
    assert len(setup) == 1
    assert "unsubscribe" in setup[0][2].lower()


def test_cancelled_tender_is_not_reminded():
    add_saved_tender(1, "T-2", (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat(), status="Cancelled")
    main.run_job_once()
    assert client.get("/notifications", headers=auth()).json() == []


def test_saved_tender_updated_and_cancelled():
    tender_id = add_saved_tender(1, "T-3", "2099-01-10")
    main.run_job_once()
    assert client.get("/notifications", headers=auth()).json() == []
    sql("UPDATE tenders SET closing_date='2099-01-20' WHERE id=?", (tender_id,))
    main.run_job_once()
    sql("UPDATE tenders SET status='Cancelled' WHERE id=?", (tender_id,))
    main.run_job_once()
    types = [i["type"] for i in client.get("/notifications", headers=auth()).json()]
    assert types == ["tender_cancelled", "tender_updated"]


def test_new_matches_summary_after_first_run():
    sql("INSERT INTO profile_alert_notifications(user_id, tender_id, score) VALUES (1, 100, 90)")
    main.run_job_once()
    assert client.get("/notifications", headers=auth()).json() == []
    sql("INSERT INTO profile_alert_notifications(user_id, tender_id, score) VALUES (1, 101, 80), (1, 102, 75), (1, 103, 40)")
    main.run_job_once()
    items = client.get("/notifications", headers=auth()).json()
    assert [i["type"] for i in items] == ["new_matches"]
    assert items[0]["message"].startswith("2 new tenders")
    main.run_job_once()
    assert len(client.get("/notifications", headers=auth()).json()) == 1


def test_failed_email_is_retried(monkeypatch, setup):
    calls = []

    def flaky(to, subject, text, html):
        calls.append(to)
        if len(calls) == 1:
            raise OSError("smtp down")

    monkeypatch.setattr(main, "send_email", flaky)
    add_saved_tender(1, "T-4", (datetime.now(timezone.utc) + timedelta(hours=60)).isoformat())
    main.run_job_once()
    main.run_job_once()
    assert len(calls) == 2
    assert sql("SELECT email_status FROM notifications") == [("sent",)]


def test_unsubscribe_turns_off_email_for_type():
    token = main.unsubscribe_token(1, "tender_closing_soon")
    response = client.get(f"/notifications/unsubscribe?token={token}")
    assert response.status_code == 200
    prefs = {p["type"]: p for p in client.get("/notification-preferences", headers=auth()).json()["preferences"]}
    assert prefs["tender_closing_soon"]["email"] is False
    assert prefs["tender_closing_soon"]["in_app"] is True
    assert client.get("/notifications/unsubscribe?token=not-a-real-token").status_code == 400


def add_notification(title, age_days):
    created = main.iso(main.now_utc() - timedelta(days=age_days))
    sql("INSERT INTO notifications (user_id, type, title, message, created_at) "
        "VALUES (1, 'profile_updated', ?, 'm', ?)", (title, created))


def test_old_notifications_are_deleted_by_the_job(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATION_RETENTION_DAYS", 90)
    add_notification("recent", 10)
    add_notification("just inside", 89)
    add_notification("too old", 91)

    main.run_job_once()

    titles = {row[0] for row in sql("SELECT title FROM notifications")}
    assert titles == {"recent", "just inside"}


def test_zero_retention_keeps_everything(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATION_RETENTION_DAYS", 0)
    add_notification("ancient", 1000)

    con = main.db()
    try:
        assert main.delete_old_notifications(con) == 0
    finally:
        con.close()
    assert sql("SELECT COUNT(*) FROM notifications")[0][0] == 1


def test_deactivated_user_gets_no_reminders(setup):
    sql("UPDATE users SET is_active=0 WHERE id=1")
    add_saved_tender(1, "T-5", (datetime.now(timezone.utc) + timedelta(hours=60)).isoformat())
    add_saved_tender(2, "T-6", (datetime.now(timezone.utc) + timedelta(hours=60)).isoformat())

    main.run_job_once()

    assert sql("SELECT user_id, type FROM notifications") == [(2, "tender_closing_soon")]
    assert [to for to, _subject, _text in setup] == ["bob@acme.co.za"]


def test_deactivated_user_still_gets_security_emails(setup):
    sql("UPDATE users SET is_active=0 WHERE id=1")

    assert internal({"username": "alice@acme.co.za", "type": "password_changed"}).status_code == 201
    assert internal({"username": "alice@acme.co.za", "type": "profile_updated"}).status_code == 201

    assert sql("SELECT type FROM notifications") == [("password_changed",)]
    assert [to for to, _subject, _text in setup] == ["alice@acme.co.za"]


def test_waiting_email_is_not_sent_after_deactivation(monkeypatch, setup):
    def smtp_down(to, subject, text, html):
        raise OSError("smtp down")

    monkeypatch.setattr(main, "send_email", smtp_down)
    add_saved_tender(1, "T-7", (datetime.now(timezone.utc) + timedelta(hours=60)).isoformat())
    main.run_job_once()
    assert sql("SELECT email_status FROM notifications") == [("pending",)]

    sql("UPDATE users SET is_active=0 WHERE id=1")
    monkeypatch.setattr(main, "send_email", lambda to, subject, text, html: setup.append((to, subject, text)))
    main.run_job_once()

    assert setup == []
    assert sql("SELECT email_status FROM notifications") == [("pending",)]


def test_tokens_from_before_a_password_change_are_refused():
    """The Login API sets sessions_valid_after on a password change or reset."""
    import sqlite3
    import time

    def get(**claims):
        claims = {"sub": 'alice@acme.co.za', "exp": int(time.time()) + 3600, **claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        token = jwt.encode(claims, SECRET, algorithm="HS256")
        return client.get('/notifications', headers={"Authorization": "Bearer " + token}).status_code

    now = int(time.time())
    assert get() != 401  # no column yet: old tokens keep working
    assert get(exp=None) == 401  # a token must expire
    db = sqlite3.connect(main.DATABASE_PATH)
    try:
        db.execute("ALTER TABLE users ADD COLUMN sessions_valid_after INTEGER")
        db.execute("UPDATE users SET sessions_valid_after = ?", (now - 10,))
        db.commit()
        assert get(iat=now - 60) == 401
        assert get() == 401  # no issue time
        assert get(iat=now) != 401
    finally:
        db.execute("UPDATE users SET sessions_valid_after = NULL")
        db.commit()
        db.close()


def test_unsubscribe_links_have_their_own_key_audience_and_expiry():
    import time

    def visit(token):
        return client.get(f"/notifications/unsubscribe?token={token}").status_code

    good = main.unsubscribe_token(1, "tender_closing_soon")
    claims = jwt.decode(good, main.unsubscribe_key(), algorithms=["HS256"], audience=main.UNSUBSCRIBE_AUDIENCE)
    assert 89 * 86400 < claims["exp"] - time.time() <= 90 * 86400

    # Old-style links (login secret, no expiry) and sign-in tokens are refused.
    old = jwt.encode({"sub": "1", "type": "tender_closing_soon", "purpose": "unsubscribe"}, SECRET, algorithm="HS256")
    assert visit(old) == 400
    login = jwt.encode({"sub": "1", "type": "tender_closing_soon", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    assert visit(login) == 400
    # An expired link is refused.
    expired = jwt.encode({"sub": "1", "type": "tender_closing_soon", "aud": main.UNSUBSCRIBE_AUDIENCE,
                          "exp": int(time.time()) - 1}, main.unsubscribe_key(), algorithm="HS256")
    assert visit(expired) == 400
    # An unsubscribe link is not a sign-in token.
    assert client.get("/notifications", headers={"Authorization": "Bearer " + good}).status_code == 401
    assert visit(good) == 200


def test_a_token_its_user_signed_out_with_is_refused():
    """The Login API lists signed-out token ids in revoked_tokens; other sign-ins keep working."""
    import sqlite3
    import time

    def get(jti):
        claims = {"sub": 'alice@acme.co.za', "exp": int(time.time()) + 3600, "iat": int(time.time()), "jti": jti}
        token = jwt.encode(claims, SECRET, algorithm="HS256")
        return client.get('/notifications', headers={"Authorization": "Bearer " + token}).status_code

    assert get("phone") != 401  # no table yet
    db = sqlite3.connect(main.DATABASE_PATH)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
        db.execute("INSERT INTO revoked_tokens VALUES ('phone', ?)", (int(time.time()) + 3600,))
        db.commit()
        assert get("phone") == 401
        assert get("laptop") != 401
    finally:
        db.execute("DELETE FROM revoked_tokens")
        db.commit()
        db.close()
