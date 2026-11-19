import sqlite3

import bcrypt
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
REAL_NOTIFY = main.notify_password_changed
USERNAME = "tenders@company.co.za"
PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)")
    db.execute("INSERT INTO users VALUES (?, ?, 1)", (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    events = []
    monkeypatch.setattr(main, "notify_password_changed", lambda username: events.append(username))
    return events


def auth():
    token = main.create_access_token({"sub": USERNAME})
    return {"Authorization": f"Bearer {token}"}


def change(current, new, headers=None):
    return client.post("/change-password", json={"current_password": current, "new_password": new},
                       headers=auth() if headers is None else headers)


def login(password):
    return client.post("/login", data={"username": USERNAME, "password": password})


def test_change_password_then_login_with_new_password(database):
    response = change(PASSWORD, "NewPassword456!")
    assert response.status_code == 200
    assert login("NewPassword456!").status_code == 200
    assert login(PASSWORD).status_code == 401
    assert database == [USERNAME]


def test_wrong_current_password_is_rejected(database):
    response = change("Wrong123!", "NewPassword456!")
    assert response.status_code == 400
    assert response.json()["detail"] == "Your current password is incorrect."
    assert database == []


@pytest.mark.parametrize("new_password", ["weak", "nouppercase1!", "NoNumber!!", "NoSpecial123", PASSWORD])
def test_password_rules_are_enforced(database, new_password):
    assert change(PASSWORD, new_password).status_code == 400
    assert database == []


def test_login_is_required():
    assert change(PASSWORD, "NewPassword456!", headers={}).status_code == 401
    bad = {"Authorization": "Bearer invalid.token.value"}
    assert change(PASSWORD, "NewPassword456!", headers=bad).status_code == 401


def test_notify_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATIONS_API_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main, "INTERNAL_API_KEY", "key")

    def fail(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(main.httpx, "post", fail)
    REAL_NOTIFY(USERNAME)  # must not raise


def test_notify_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(main, "NOTIFICATIONS_API_URL", "")

    def boom(*args, **kwargs):
        raise AssertionError("should not call the network")

    monkeypatch.setattr(main.httpx, "post", boom)
    REAL_NOTIFY(USERNAME)
