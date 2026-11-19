"""Brute-force limits, generic errors, CORS allowlist and token checks."""
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
USERNAME = "tenders@company.co.za"
PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)")
    db.execute("INSERT INTO users VALUES (?, ?, 1)", (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.execute("INSERT INTO users VALUES (?, ?, 0)", ("inactive@company.co.za", bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    return path


def login(password, username=USERNAME, ip_client=client):
    return ip_client.post("/login", data={"username": username, "password": password})


# --- brute-force limits ------------------------------------------------------

def test_account_is_locked_after_repeated_failures():
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT):
        assert login("Wrong-password1!").status_code == 401
    blocked = login(PASSWORD)  # even the right password waits out the window
    assert blocked.status_code == 429
    assert "Too many failed sign-in attempts" in blocked.json()["detail"]
    assert blocked.headers["Retry-After"] == str(main.LOGIN_WINDOW_SECONDS)


def test_lock_ignores_username_case_and_spaces():
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT):
        login("Wrong-password1!", username=f"  {USERNAME.upper()} ")
    assert login(PASSWORD).status_code == 429


def test_successful_login_clears_the_account_count():
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT - 1):
        login("Wrong-password1!")
    assert login(PASSWORD).status_code == 200
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT - 1):
        assert login("Wrong-password1!").status_code == 401
    assert login(PASSWORD).status_code == 200


def test_unknown_accounts_count_towards_the_ip_limit():
    for i in range(main.LOGIN_MAX_FAILURES_PER_IP):
        assert login("Wrong-password1!", username=f"nobody{i}@company.co.za").status_code == 401
    assert login(PASSWORD).status_code == 429


def test_lock_expires_after_the_window(monkeypatch):
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT):
        login("Wrong-password1!")
    assert login(PASSWORD).status_code == 429
    later = main.time.monotonic() + main.LOGIN_WINDOW_SECONDS + 1
    monkeypatch.setattr(main.time, "monotonic", lambda: later)
    assert login(PASSWORD).status_code == 200


def test_password_longer_than_bcrypt_limit_is_a_normal_failure():
    response = login("A1!" + "x" * 200)
    assert response.status_code == 401


# --- generic errors ----------------------------------------------------------

def test_unexpected_errors_do_not_reveal_details(monkeypatch):
    def boom():
        raise ZeroDivisionError("secret internal detail /data/tenders.db")

    monkeypatch.setattr(main, "get_db_connection", boom)
    quiet_client = TestClient(main.app, raise_server_exceptions=False)
    response = login(PASSWORD, ip_client=quiet_client)
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert "ZeroDivisionError" not in response.text


def test_database_errors_do_not_reveal_the_path(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATABASE_PATH", str(tmp_path / "missing" / "tenders.db"))
    response = login(PASSWORD)
    assert response.status_code == 503
    assert "missing" not in response.text
    health = client.get("/health")
    assert health.status_code == 503
    assert "missing" not in health.text


def test_invalid_stored_hash_does_not_reveal_the_account(database):
    db = sqlite3.connect(database)
    db.execute("UPDATE users SET hashed_password = 'not-a-bcrypt-hash' WHERE username = ?", (USERNAME,))
    db.commit()
    db.close()
    response = login(PASSWORD)
    assert response.status_code == 500
    assert USERNAME not in response.text


# --- CORS --------------------------------------------------------------------

def test_cors_allows_only_configured_origins():
    allowed = client.options("/login", headers={
        "Origin": "http://allowed.example", "Access-Control-Request-Method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "http://allowed.example"
    assert "access-control-allow-credentials" not in allowed.headers

    foreign = client.options("/login", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in foreign.headers


# --- tokens ------------------------------------------------------------------

def token_for(claims):
    return jwt.encode(claims, main.SECRET_KEY, algorithm=main.ALGORITHM)


def test_protected_route_rejects_inactive_user():
    token = main.create_access_token({"sub": "inactive@company.co.za"})
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_protected_route_rejects_deleted_user():
    token = main.create_access_token({"sub": "deleted@company.co.za"})
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_protected_route_accepts_active_user():
    token = main.create_access_token({"sub": USERNAME})
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == USERNAME


def test_tokens_without_expiry_are_rejected():
    # e.g. the never-expiring unsubscribe links signed with the same secret
    token = token_for({"sub": USERNAME, "purpose": "unsubscribe"})
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_tokens_without_subject_are_rejected():
    token = token_for({"exp": datetime.now(UTC) + timedelta(minutes=5)})
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- removed and required pieces ---------------------------------------------

def test_unauthenticated_llm_endpoint_is_gone():
    response = client.post("/api/ai/generate-insight", json={"prompt": "hello"})
    assert response.status_code in (404, 405)


def test_app_refuses_to_start_without_jwt_secret():
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    env["JWT_SECRET"] = "   "
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=Path(main.__file__).parent, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "JWT_SECRET is not set" in result.stderr
