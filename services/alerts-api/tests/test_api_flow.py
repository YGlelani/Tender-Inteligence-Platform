import json
import sqlite3

import jwt
from app import documents

# The `client` fixture and its test database live in tests/conftest.py.


def test_matches_use_business_profile_and_skip_expired_tenders(client):
    response = client.get("/matches")
    assert response.status_code == 200
    numbers = {item["tender_number"] for item in response.json()}
    assert "OPEN-1" in numbers
    assert "OLD-1" not in numbers


def test_profile_comes_from_business_profile_table(client):
    response = client.get("/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["business_name"] == "Baloyi Civils"
    assert body["provinces"] == ["Limpopo"]


def test_unread_count_drops_after_marking_read(client):
    notifications = client.get("/notifications").json()
    assert notifications
    before = client.get("/notifications/unread-count").json()["unread"]
    assert before == len(notifications)

    assert client.post(f"/notifications/{notifications[0]['id']}/read").status_code == 204

    after = client.get("/notifications/unread-count").json()["unread"]
    assert after == before - 1
    unread = client.get("/notifications", params={"unread_only": True}).json()
    assert notifications[0]["id"] not in {item["id"] for item in unread}


def test_reading_notifications_does_not_rewrite_rows(client):
    client.get("/notifications")
    con = sqlite3.connect(client.db_path)
    first = con.execute("SELECT id, matched_at FROM profile_alert_notifications ORDER BY id").fetchall()
    con.execute("UPDATE profile_alert_notifications SET matched_at = '2000-01-01 00:00:00'")
    con.commit()
    client.get("/notifications")
    client.get("/notifications/unread-count")
    second = con.execute("SELECT matched_at FROM profile_alert_notifications").fetchall()
    con.close()
    assert first
    assert all(row[0] == "2000-01-01 00:00:00" for row in second)


def test_missing_business_profile_returns_404(client):
    con = sqlite3.connect(client.db_path)
    con.execute("DELETE FROM business_profiles")
    con.commit()
    con.close()
    assert client.get("/profile").status_code == 404
    assert client.get("/notifications").json() == []


def test_business_documents_add_matches_and_show_on_profile(client):
    con = sqlite3.connect(client.db_path)
    con.execute("UPDATE business_profiles SET keywords = '[]', industry = 'Other'")
    con.execute("UPDATE tenders SET title = 'Stormwater drainage upgrade', description = 'Stormwater drainage upgrade' WHERE id = 2")
    con.commit()
    con.close()
    client.documents["details"] = {
        "industries": ["Civil engineering"],
        "keywords": ["stormwater drainage"],
        "services": "Stormwater drainage",
        "description": "",
        "provinces": ["Limpopo"],
    }

    matches = client.get("/matches").json()
    open_2 = next(item for item in matches if item["tender_number"] == "OPEN-2")
    assert "Matches your business documents: stormwater drainage" in open_2["reasons"]

    profile = client.get("/profile").json()
    assert profile["document_keywords"] == ["stormwater drainage"]
    assert profile["document_provinces"] == ["Limpopo"]


def test_details_from_overview_reads_documents_profile():
    details = documents.details_from_overview({
        "profile": {
            "business_name": "Thuto Solutions",
            "status": "ready",
            "industries": ["Information Technology"],
            "services": ["IT support", "Website design"],
            "service_areas": ["gauteng", "Limpopo", "Botswana"],
            "description": "IT company",
        }
    })
    assert details["keywords"] == ["IT support", "Website design"]
    assert details["industries"] == ["Information Technology"]
    assert details["provinces"] == ["Gauteng", "Limpopo"]
    assert documents.details_from_overview({"profile": {"status": "failed"}})["keywords"] == []


def test_documents_service_down_does_not_break_alerts(monkeypatch):
    import asyncio

    monkeypatch.setattr(documents, "AGENT_URL", "http://127.0.0.1:9")
    documents._cache.clear()
    details = asyncio.run(documents.fetch_details(99, "token"))
    assert details == documents.EMPTY


def test_matches_include_near_matches_but_alerts_only_strong(client):
    con = sqlite3.connect(client.db_path)
    con.execute("UPDATE tenders SET title = 'Helpdesk services', description = 'Helpdesk services' WHERE id = 2")
    con.execute("UPDATE business_profiles SET keywords = ?, industry = 'Other', categories = '[]', provinces = '[]'", (json.dumps(["IT support"]),))
    con.commit()
    con.close()

    matches = {item["tender_number"]: item for item in client.get("/matches").json()}
    assert matches["OPEN-2"]["level"] == "near"

    alerted = {item["tender_number"] for item in client.get("/notifications").json()}
    assert "OPEN-2" not in alerted


def test_tokens_from_before_a_password_change_are_refused(client):
    """The Login API sets sessions_valid_after on a password change or reset."""
    import sqlite3
    import time

    def get(**claims):
        claims = {"sub": 'owner@example.com', "exp": int(time.time()) + 3600, **claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        token = jwt.encode(claims, "ci-test-secret", algorithm="HS256")
        return client.get('/profile', headers={"Authorization": "Bearer " + token}).status_code

    now = int(time.time())
    assert get() != 401  # no column yet: old tokens keep working
    assert get(exp=None) == 401  # a token must expire
    db = sqlite3.connect(client.db_path)
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


def test_a_token_its_user_signed_out_with_is_refused(client):
    """The Login API lists signed-out token ids in revoked_tokens; other sign-ins keep working."""
    import sqlite3
    import time

    def get(jti):
        claims = {"sub": 'owner@example.com', "exp": int(time.time()) + 3600, "iat": int(time.time()), "jti": jti}
        token = jwt.encode(claims, "ci-test-secret", algorithm="HS256")
        return client.get('/profile', headers={"Authorization": "Bearer " + token}).status_code

    assert get("phone") != 401  # no table yet
    db = sqlite3.connect(client.db_path)
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


def test_undated_tenders_close_36_days_after_publishing_and_awarded_ones_are_hidden(client):
    from datetime import date, timedelta

    recent = (date.today() - timedelta(days=10)).isoformat()
    old = (date.today() - timedelta(days=60)).isoformat()
    con = sqlite3.connect(client.db_path)
    con.executemany(
        "INSERT INTO tenders VALUES (?, ?, 'Road maintenance and paving', 'Road maintenance and paving',"
        " 'Limpopo', NULL, ?, ?, 1, 1)",
        [(4, "UNDATED-NEW", recent, "Open"), (5, "UNDATED-OLD", old, "Open"), (6, "AWARDED-1", recent, "Awarded")],
    )
    con.commit()
    con.close()

    numbers = {item["tender_number"] for item in client.get("/matches").json()}

    assert "UNDATED-NEW" in numbers
    assert "UNDATED-OLD" not in numbers
    assert "AWARDED-1" not in numbers
