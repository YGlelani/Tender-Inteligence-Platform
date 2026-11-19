import json
import sqlite3
import time

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient

import main

SECRET = "s" * 40
PASSWORD = "Password123!"
ME = "tenders@company.co.za"
OTHER = "other@company.co.za"

# Tables other services create in the shared database, cut down to the columns
# that matter for deletion.
OTHER_SERVICE_TABLES = """
CREATE TABLE tenders (id INTEGER PRIMARY KEY);
CREATE TABLE business_profiles (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE
    REFERENCES users(id) ON DELETE CASCADE, business_name TEXT);
CREATE TABLE company_documents (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL
    REFERENCES users(id) ON DELETE CASCADE, document_name TEXT);
CREATE TABLE alert_preferences (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL
    REFERENCES users(id) ON DELETE CASCADE, name TEXT);
CREATE TABLE alert_notifications (id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL
    REFERENCES alert_preferences(id) ON DELETE CASCADE, user_id INTEGER NOT NULL
    REFERENCES users(id) ON DELETE CASCADE, tender_id INTEGER);
CREATE TABLE profile_alert_notifications (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL
    REFERENCES users(id) ON DELETE CASCADE, tender_id INTEGER);
CREATE TABLE saved_tenders (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL
    REFERENCES users(id) ON DELETE CASCADE, tender_id INTEGER NOT NULL);
CREATE TABLE tender_applications (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL
    REFERENCES users(id), tender_id INTEGER NOT NULL);
CREATE TABLE tender_application_history (id TEXT PRIMARY KEY, application_id TEXT NOT NULL
    REFERENCES tender_applications(id) ON DELETE CASCADE, new_status TEXT);
CREATE TABLE notifications (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT);
CREATE TABLE notification_preferences (user_id INTEGER NOT NULL, type TEXT);
CREATE TABLE notification_tender_snapshots (user_id INTEGER NOT NULL, tender_id INTEGER);
CREATE TABLE password_reset_codes (username TEXT PRIMARY KEY, code_hash TEXT);
CREATE TABLE reactivation_codes (username TEXT PRIMARY KEY, code_hash TEXT);
"""
USER_TABLES = [
    "business_profiles", "company_documents", "alert_preferences", "alert_notifications",
    "profile_alert_notifications", "saved_tenders", "tender_applications",
    "tender_application_history", "notifications", "notification_preferences",
    "notification_tender_snapshots", "password_reset_codes", "reactivation_codes",
]


def add_user_with_data(con, email):
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    user_id = con.execute(
        "INSERT INTO users (username, email, hashed_password, is_active, is_email_verified) "
        "VALUES (?, ?, ?, 1, 1)",
        (email, email, hashed),
    ).lastrowid
    con.execute("INSERT INTO business_profiles (user_id, business_name) VALUES (?, 'Co')", (user_id,))
    con.execute("INSERT INTO company_documents (user_id, document_name) VALUES (?, 'Tax')", (user_id,))
    alert_id = con.execute(
        "INSERT INTO alert_preferences (user_id, name) VALUES (?, 'A')", (user_id,)
    ).lastrowid
    con.execute(
        "INSERT INTO alert_notifications (alert_id, user_id, tender_id) VALUES (?, ?, 1)",
        (alert_id, user_id),
    )
    con.execute("INSERT INTO profile_alert_notifications (user_id, tender_id) VALUES (?, 1)", (user_id,))
    con.execute("INSERT INTO saved_tenders (user_id, tender_id) VALUES (?, 1)", (user_id,))
    con.execute(
        "INSERT INTO tender_applications (id, user_id, tender_id) VALUES (?, ?, 1)",
        ("app-" + email, user_id),
    )
    con.execute(
        "INSERT INTO tender_application_history (id, application_id, new_status) "
        "VALUES (?, ?, 'Submitted')",
        ("hist-" + email, "app-" + email),
    )
    con.execute("INSERT INTO notifications (user_id, title) VALUES (?, 'Hi')", (user_id,))
    con.execute("INSERT INTO notification_preferences (user_id, type) VALUES (?, 'x')", (user_id,))
    con.execute("INSERT INTO notification_tender_snapshots (user_id, tender_id) VALUES (?, 1)", (user_id,))
    con.execute("INSERT INTO password_reset_codes (username, code_hash) VALUES (?, 'h')", (email,))
    con.execute("INSERT INTO reactivation_codes (username, code_hash) VALUES (?, 'h')", (email,))
    return user_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "JWT_SECRET", SECRET)
    monkeypatch.setattr(main, "ACCOUNT_DELETION_KEY", "deletion-key")
    main._attempts.clear()
    main.initialize_database()
    con = main.db()
    con.executescript(OTHER_SERVICE_TABLES)
    con.execute("INSERT INTO tenders (id) VALUES (1)")
    add_user_with_data(con, ME)
    add_user_with_data(con, OTHER)
    con.commit()
    con.close()

    test_client = TestClient(main.app)
    test_client.agent_calls = []
    test_client.emails = []
    monkeypatch.setattr(main, "delete_agent_data", test_client.agent_calls.append)
    monkeypatch.setattr(main, "send_deletion_confirmation", test_client.emails.append)
    return test_client


def headers(username=ME):
    token = jwt.encode({"sub": username, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def delete(client, password=PASSWORD, username=ME):
    return client.request(
        "DELETE", "/user/account", json={"password": password}, headers=headers(username)
    )


def rows_for(email):
    """Rows each table holds for this user (0 everywhere once deleted)."""
    con = main.db()
    try:
        user = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        user_id = user["id"] if user else -1
        counts = {"users": 1 if user else 0}
        for table in USER_TABLES:
            if table == "tender_application_history":
                sql, arg = "SELECT COUNT(*) FROM tender_application_history WHERE application_id=?", "app-" + email
            elif table in ("password_reset_codes", "reactivation_codes"):
                sql, arg = f"SELECT COUNT(*) FROM {table} WHERE username=?", email
            else:
                sql, arg = f"SELECT COUNT(*) FROM {table} WHERE user_id=?", user_id
            counts[table] = con.execute(sql, (arg,)).fetchone()[0]
        return counts
    finally:
        con.close()


def test_delete_account_removes_all_of_the_users_data(client):
    response = delete(client)

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert set(rows_for(ME).values()) == {0}


def test_delete_account_leaves_other_users_alone(client):
    delete(client)

    assert set(rows_for(OTHER).values()) == {1}


def test_delete_account_asks_the_agent_first_and_sends_confirmation(client):
    delete(client)

    assert client.agent_calls == [ME]
    assert client.emails == [ME]


def test_token_stops_working_after_deletion(client):
    delete(client)

    response = client.get("/user/profile", headers=headers())

    assert response.status_code == 401


def test_wrong_password_deletes_nothing(client):
    response = delete(client, password="Wrong123!")

    assert response.status_code == 403
    assert response.json()["detail"] == main.WRONG_PASSWORD_ERROR
    assert client.agent_calls == []
    assert set(rows_for(ME).values()) == {1}


def test_agent_failure_deletes_nothing(client, monkeypatch):
    def agent_down(email):
        raise OSError("connection refused")

    monkeypatch.setattr(main, "delete_agent_data", agent_down)

    response = delete(client)

    assert response.status_code == 503
    assert response.json()["detail"] == main.ACCOUNT_DELETION_UNAVAILABLE
    assert set(rows_for(ME).values()) == {1}
    assert client.emails == []


def test_database_failure_rolls_back_everything(client, monkeypatch):
    real = main.delete_user_rows

    def fail_half_way(con, user):
        con.execute("DELETE FROM saved_tenders WHERE user_id=?", (user["id"],))
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main, "delete_user_rows", fail_half_way)

    response = delete(client)

    assert response.status_code == 503
    assert set(rows_for(ME).values()) == {1}
    monkeypatch.setattr(main, "delete_user_rows", real)


def test_failed_confirmation_email_does_not_undo_deletion(client, monkeypatch, caplog):
    def smtp_down(to):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(main, "send_deletion_confirmation", smtp_down)

    response = delete(client)

    assert response.status_code == 200
    assert "Account deletion email could not be sent" in caplog.text


def test_delete_account_needs_a_token(client):
    response = client.request("DELETE", "/user/account", json={"password": PASSWORD})

    assert response.status_code == 401
    assert client.agent_calls == []


def test_delete_account_is_rate_limited(client):
    statuses = [
        delete(client, password="Wrong123!").status_code
        for _ in range(main.RATE_LIMIT_PER_EMAIL + 1)
    ]

    assert statuses[:-1] == [403] * main.RATE_LIMIT_PER_EMAIL
    assert statuses[-1] == 429


def test_delete_works_when_other_services_tables_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "bare.db"))
    main.initialize_database()
    con = main.db()
    con.execute(
        "INSERT INTO users (username, email, hashed_password) VALUES (?, ?, 'x')", (ME, ME)
    )
    user = dict(con.execute("SELECT id, username, email FROM users").fetchone())
    deleted = main.delete_user_rows(con, user)
    con.commit()
    con.close()

    assert deleted == {"users": 1}


class FakeResponse:
    def close(self):
        pass


def test_agent_request_carries_the_key_and_email(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "ACCOUNT_DELETION_KEY", "deletion-key")
    monkeypatch.setattr(main, "AGENT_API_URL", "http://agent:9000")
    monkeypatch.setattr(
        main.urllib.request,
        "urlopen",
        lambda request, timeout: sent.append(request) or FakeResponse(),
    )

    main.delete_agent_data(ME)

    request = sent[0]
    assert request.full_url == "http://agent:9000/internal/accounts/delete"
    assert request.get_method() == "POST"
    assert request.get_header("X-internal-key") == "deletion-key"
    assert json.loads(request.data) == {"email": ME}


def test_agent_request_refuses_without_a_key(monkeypatch):
    monkeypatch.setattr(main, "ACCOUNT_DELETION_KEY", "")

    with pytest.raises(RuntimeError):
        main.delete_agent_data(ME)
