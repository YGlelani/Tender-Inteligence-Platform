"""Changing or resetting a password ends every sign-in made before it."""
import sqlite3
import time
from datetime import datetime, timedelta, UTC

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
USERNAME = "tenders@company.co.za"
PASSWORD = "Password123!"
NEW_PASSWORD = "NewPassword456!"


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    db = sqlite3.connect(path)
    # No sessions_valid_after column: the API adds it the first time it is needed.
    db.execute("CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)")
    db.execute("INSERT INTO users VALUES (?, ?, 1)", (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    main._reset_attempts.clear()
    main._login_failures.clear()
    sent = []
    monkeypatch.setattr(main, "send_reset_code", lambda email, code: sent.append((email, code)))
    monkeypatch.setattr(main, "notify_password_changed", lambda username: None)
    return {"sent": sent, "db": path}


def token(issued_seconds_ago=None):
    """A token like the ones signed in browsers hold; None = an old token without an issue time."""
    claims = {"sub": USERNAME, "exp": datetime.now(UTC) + timedelta(hours=1)}
    if issued_seconds_ago is not None:
        claims["iat"] = int(time.time()) - issued_seconds_ago
    return jwt.encode(claims, main.SECRET_KEY, algorithm=main.ALGORITHM)


def check(t):
    return client.get("/protected-tenders", headers={"Authorization": f"Bearer {t}"}).status_code


def change_password(t):
    return client.post("/change-password", headers={"Authorization": f"Bearer {t}"},
                       json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})


def test_new_tokens_carry_an_issue_time():
    claims = jwt.decode(main.create_access_token({"sub": USERNAME}), main.SECRET_KEY, algorithms=[main.ALGORITHM])
    assert abs(claims["iat"] - time.time()) < 5


def test_tokens_work_until_a_password_change():
    assert check(token(60)) == 200
    assert check(token()) == 200  # issued before this change: still fine until it expires


def test_change_password_ends_other_sign_ins_but_keeps_this_one(setup):
    phone, laptop = token(120), token(60)
    response = change_password(laptop)
    assert response.status_code == 200
    body = response.json()
    assert "signed out on your other devices" in body["message"]

    assert check(phone) == 401
    assert check(laptop) == 401
    assert check(token()) == 401  # old tokens without an issue time fail too
    assert check(body["access_token"]) == 200  # the browser that changed it stays signed in
    assert client.post("/login", data={"username": USERNAME, "password": NEW_PASSWORD}).status_code == 200


def test_an_ended_sign_in_cannot_change_the_password_again(setup):
    old = token(60)
    assert change_password(old).status_code == 200
    response = client.post("/change-password", headers={"Authorization": f"Bearer {old}"},
                           json={"current_password": NEW_PASSWORD, "new_password": "ThirdPass789!"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Your session has ended. Please sign in again."


def test_reset_password_ends_every_sign_in(setup):
    signed_in = token(60)
    client.post("/forgot-password", json={"email": USERNAME})
    code = setup["sent"][0][1]
    response = client.post("/reset-password", json={"email": USERNAME, "code": code, "new_password": NEW_PASSWORD})
    assert response.status_code == 200
    assert "signed out everywhere" in response.json()["message"]
    assert check(signed_in) == 401

    fresh = client.post("/login", data={"username": USERNAME, "password": NEW_PASSWORD}).json()["access_token"]
    assert check(fresh) == 200


def test_cut_off_is_stored_on_the_user(setup):
    change_password(token(60))
    db = sqlite3.connect(setup["db"])
    (cutoff,) = db.execute("SELECT sessions_valid_after FROM users WHERE username = ?", (USERNAME,)).fetchone()
    db.close()
    assert abs(cutoff - time.time()) < 5


def test_deactivated_user_is_refused(setup):
    t = token(60)
    db = sqlite3.connect(setup["db"])
    db.execute("UPDATE users SET is_active = 0")
    db.commit()
    db.close()
    assert check(t) == 401
