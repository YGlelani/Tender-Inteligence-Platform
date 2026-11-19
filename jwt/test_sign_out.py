"""Signing out ends that device's sign-in; other devices stay signed in."""
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


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)")
    db.execute("INSERT INTO users VALUES (?, ?, 1)", (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    main._login_failures.clear()
    return path


def sign_in():
    return client.post("/login", data={"username": USERNAME, "password": PASSWORD}).json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def check(token):
    return client.get("/protected-tenders", headers=bearer(token)).status_code


def test_each_sign_in_has_its_own_id():
    first, second = (jwt.decode(sign_in(), main.SECRET_KEY, algorithms=[main.ALGORITHM]) for _ in range(2))
    assert first["jti"] and second["jti"] and first["jti"] != second["jti"]


def test_signing_out_ends_only_this_device():
    phone, laptop = sign_in(), sign_in()
    response = client.post("/logout", headers=bearer(phone))
    assert response.status_code == 200
    assert check(phone) == 401
    assert check(laptop) == 200
    # Signing out twice is fine.
    assert client.post("/logout", headers=bearer(phone)).status_code == 200


def test_a_signed_out_token_cannot_change_the_password():
    token = sign_in()
    client.post("/logout", headers=bearer(token))
    response = client.post("/change-password", headers=bearer(token),
                           json={"current_password": PASSWORD, "new_password": "NewPassword456!"})
    assert response.status_code == 401


def test_signing_out_with_an_expired_token_just_succeeds():
    expired = jwt.encode({"sub": USERNAME, "exp": datetime.now(UTC) - timedelta(minutes=1), "jti": "x"},
                         main.SECRET_KEY, algorithm=main.ALGORITHM)
    assert client.post("/logout", headers=bearer(expired)).status_code == 200


def test_signing_out_needs_a_real_token():
    assert client.post("/logout", headers=bearer("not-a-token")).status_code == 401
    assert client.post("/logout").status_code == 401


def test_expired_entries_are_forgotten(setup):
    token = sign_in()
    client.post("/logout", headers=bearer(token))
    db = sqlite3.connect(setup)
    db.execute("INSERT INTO revoked_tokens VALUES ('old', ?)", (int(time.time()) - 5,))
    db.commit()
    db.close()
    assert main.purge_expired_revoked_tokens() == 1
    assert check(token) == 401  # still signed out until it expires
