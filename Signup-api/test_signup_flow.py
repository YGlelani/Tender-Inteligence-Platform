import sqlite3
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import main

VALID_SIGNUP = {
    "company_name": "Baloyi Trading",
    "email": "tenders@company.co.za",
    "password": "Password123!",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(
        main, "EMAIL_CONFIRMATION_URL", "http://localhost:8008/verify.html"
    )
    monkeypatch.setattr(main, "send_email", lambda to, **_: sent.append(to))
    main._attempts.clear()
    main.initialize_database()
    test_client = TestClient(main.app)
    test_client.sent = sent
    return test_client


def stored_password_hash(email):
    con = main.db()
    try:
        return con.execute(
            "SELECT hashed_password FROM pending_registrations WHERE email=?", (email,)
        ).fetchone()["hashed_password"]
    finally:
        con.close()


def expire_pending(email):
    con = main.db()
    try:
        con.execute(
            "UPDATE pending_registrations SET verification_token_expires_at=? "
            "WHERE email=?",
            ("2000-01-01T00:00:00+00:00", email),
        )
        con.commit()
    finally:
        con.close()


def auth_headers(monkeypatch, username=VALID_SIGNUP["email"]):
    secret = "s" * 40
    monkeypatch.setattr(main, "JWT_SECRET", secret)
    token = jwt.encode({"sub": username, "exp": int(time.time()) + 3600}, secret, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


@pytest.fixture(params=["cannot_open_file", "cannot_create_directory"])
def broken_database(request, client, tmp_path, monkeypatch):
    """Make every new database connection fail, after the client is set up."""
    if request.param == "cannot_open_file":

        def unavailable_database():
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr(main, "db", unavailable_database)
    else:
        # A regular file where the database directory should be makes mkdir fail.
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("")
        monkeypatch.setattr(main, "DB_PATH", str(blocker / "tenders.db"))


def signup_and_capture_token(client, monkeypatch):
    tokens = []
    monkeypatch.setattr(
        main, "send_verification", lambda to, raw_token: tokens.append(raw_token)
    )
    client.post("/signup", json=VALID_SIGNUP)
    return tokens[0]


def test_startup_creates_database_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "startup.db"))

    with TestClient(main.app):
        pass

    con = main.db()
    try:
        tables = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        con.close()
    assert {"users", "pending_registrations"} <= tables


def test_root_does_not_expose_database_path(client):
    assert "database_path" not in client.get("/").json()


def test_signup_sends_verification_email(client):
    response = client.post("/signup", json=VALID_SIGNUP)
    assert response.status_code == 201
    assert client.sent == [VALID_SIGNUP["email"]]


@pytest.mark.parametrize(
    "password",
    ["password123!", "Password!!!", "Password123", "Pa1!", "A1!" + "a" * 70],
)
def test_signup_rejects_weak_or_too_long_passwords(client, password):
    response = client.post("/signup", json={**VALID_SIGNUP, "password": password})
    assert response.status_code == 400
    assert client.sent == []


@pytest.mark.parametrize("email", ["person@ymail.com", "person@tutanota.com", "a@b.c"])
def test_signup_rejects_free_and_invalid_emails(client, email):
    response = client.post("/signup", json={**VALID_SIGNUP, "email": email})
    assert response.status_code == 400


def test_second_signup_cannot_replace_pending_password(client):
    client.post("/signup", json=VALID_SIGNUP)
    original_hash = stored_password_hash(VALID_SIGNUP["email"])

    response = client.post("/signup", json={**VALID_SIGNUP, "password": "Attacker123!"})

    assert response.status_code == 409
    assert stored_password_hash(VALID_SIGNUP["email"]) == original_hash
    assert len(client.sent) == 1


def test_signup_can_restart_after_link_expires(client):
    client.post("/signup", json=VALID_SIGNUP)
    expire_pending(VALID_SIGNUP["email"])

    response = client.post(
        "/signup", json={**VALID_SIGNUP, "password": "NewPassword123!"}
    )

    assert response.status_code == 201
    assert len(client.sent) == 2


def test_resend_keeps_pending_password(client):
    client.post("/signup", json=VALID_SIGNUP)
    original_hash = stored_password_hash(VALID_SIGNUP["email"])

    response = client.post(
        "/email/resend-verification", json={"email": VALID_SIGNUP["email"]}
    )

    assert response.status_code == 200
    assert stored_password_hash(VALID_SIGNUP["email"]) == original_hash
    assert len(client.sent) == 2


def test_resend_database_error_returns_503(client, monkeypatch):
    client.post("/signup", json=VALID_SIGNUP)

    def locked_database():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main, "create_verification_token", locked_database)
    response = client.post(
        "/email/resend-verification", json={"email": VALID_SIGNUP["email"]}
    )

    assert response.status_code == 503


def test_verify_creates_account_and_sends_welcome_email(client, monkeypatch):
    token = signup_and_capture_token(client, monkeypatch)

    response = client.get("/email/verify", params={"token": token})

    assert "Email verified successfully" in response.text
    con = main.db()
    try:
        user = con.execute(
            "SELECT company_name FROM users WHERE email=?", (VALID_SIGNUP["email"],)
        ).fetchone()
        pending = con.execute("SELECT id FROM pending_registrations").fetchone()
    finally:
        con.close()
    assert user["company_name"] == VALID_SIGNUP["company_name"]
    assert pending is None
    assert client.sent == [VALID_SIGNUP["email"]]


def test_verify_link_cannot_be_reused(client, monkeypatch):
    token = signup_and_capture_token(client, monkeypatch)
    client.get("/email/verify", params={"token": token})

    response = client.get("/email/verify", params={"token": token})

    assert "This link is invalid or has already been used." in response.text


def test_verify_succeeds_and_logs_when_welcome_email_fails(client, monkeypatch, caplog):
    token = signup_and_capture_token(client, monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(main, "send_email", fail)
    response = client.get("/email/verify", params={"token": token})

    assert "Email verified successfully" in response.text
    assert "Welcome email could not be sent" in caplog.text


def test_resend_is_rate_limited_per_email(client):
    client.post("/signup", json=VALID_SIGNUP)
    statuses = [
        client.post(
            "/email/resend-verification", json={"email": VALID_SIGNUP["email"]}
        ).status_code
        for _ in range(main.RATE_LIMIT_PER_EMAIL + 1)
    ]
    assert statuses[:-1] == [200] * main.RATE_LIMIT_PER_EMAIL
    assert statuses[-1] == 429


def test_signup_is_rate_limited_per_ip(client):
    statuses = [
        client.post(
            "/signup", json={**VALID_SIGNUP, "email": f"user{i}@company.co.za"}
        ).status_code
        for i in range(main.RATE_LIMIT_PER_IP + 1)
    ]
    assert statuses[:-1] == [201] * main.RATE_LIMIT_PER_IP
    assert statuses[-1] == 429


def test_email_failure_returns_friendly_message(client, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(main, "send_email", fail)
    response = client.post("/signup", json=VALID_SIGNUP)

    assert response.status_code == 503
    assert response.json()["detail"] == main.EMAIL_SEND_ERROR


def test_profile_update_sends_notification_event(client, monkeypatch):
    con = main.db()
    con.execute(
        "INSERT INTO users(username,email,hashed_password) VALUES (?,?,?)",
        ("tenders@company.co.za", "tenders@company.co.za", "x"),
    )
    con.commit()
    con.close()
    events = []
    monkeypatch.setattr(
        main,
        "notify",
        lambda username, event_type: events.append((username, event_type)),
    )

    response = client.put(
        "/user/profile",
        json={"full_name": "Baloyi Trading"},
        headers=auth_headers(monkeypatch),
    )

    assert response.status_code == 200
    assert events == [("tenders@company.co.za", "profile_updated")]


@pytest.mark.parametrize(
    ("method", "path", "body", "expected_status"),
    [
        ("get", "/health", None, 503),
        ("post", "/signup", VALID_SIGNUP, 500),
        ("get", "/email/verify?token=" + "x" * 20, None, 503),
        ("post", "/email/resend-verification", {"email": "a@company.co.za"}, 503),
        ("get", "/user/profile", None, 503),
        ("put", "/user/profile", {"full_name": "Baloyi Trading"}, 503),
    ],
)
def test_unavailable_database_returns_json_error(
    client, broken_database, monkeypatch, method, path, body, expected_status
):
    headers = auth_headers(monkeypatch)

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == expected_status
    assert response.json()["detail"]


def test_profile_update_returns_503_when_database_is_unavailable(
    client, broken_database, monkeypatch
):
    user = {"id": 1, "username": VALID_SIGNUP["email"]}
    monkeypatch.setitem(main.app.dependency_overrides, main.current_user, lambda: user)

    response = client.put("/user/profile", json={"full_name": "Baloyi Trading"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not save user profile"


def test_notify_is_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATIONS_API_URL", "")

    def boom(*args, **kwargs):
        raise AssertionError("should not call the network")

    monkeypatch.setattr(main.urllib.request, "urlopen", boom)
    main.notify("someone@company.co.za", "profile_updated")


def test_notify_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATIONS_API_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main, "INTERNAL_API_KEY", "key")

    def fail(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(main.urllib.request, "urlopen", fail)
    main.notify("someone@company.co.za", "profile_updated")
