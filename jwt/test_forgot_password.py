import sqlite3
from datetime import datetime, timedelta, UTC

import bcrypt
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
    db.execute("CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)")
    db.execute("INSERT INTO users VALUES (?, ?, 1)", (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()))
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    main._reset_attempts.clear()
    sent = []
    monkeypatch.setattr(main, "send_reset_code", lambda email, code: sent.append((email, code)))
    notified = []
    monkeypatch.setattr(main, "notify_password_changed", lambda username: notified.append(username))
    return {"sent": sent, "notified": notified, "db": path}


def forgot(email=USERNAME):
    return client.post("/forgot-password", json={"email": email})


def reset(code, new_password=NEW_PASSWORD, email=USERNAME):
    return client.post("/reset-password", json={"email": email, "code": code, "new_password": new_password})


def login(password):
    return client.post("/login", data={"username": USERNAME, "password": password})


def test_full_reset_flow(setup):
    response = forgot("  Tenders@Company.co.za ")
    assert response.status_code == 200
    assert setup["sent"][0][0] == USERNAME
    code = setup["sent"][0][1]
    assert len(code) == 6 and code.isdigit()

    assert reset(code).status_code == 200
    assert login(NEW_PASSWORD).status_code == 200
    assert login(PASSWORD).status_code == 401
    assert setup["notified"] == [USERNAME]
    # The code works only once.
    assert reset(code, "AnotherPass789!").status_code == 400


def test_unknown_email_gets_same_answer_and_no_email(setup):
    known = forgot().json()
    unknown = forgot("nobody@company.co.za")
    assert unknown.status_code == 200
    assert unknown.json() == known
    assert len(setup["sent"]) == 1


def test_code_is_stored_hashed(setup):
    forgot()
    code = setup["sent"][0][1]
    stored = sqlite3.connect(setup["db"]).execute("SELECT code_hash FROM password_reset_codes").fetchone()[0]
    assert code not in stored


def test_wrong_code_counts_attempts_then_locks(setup):
    forgot()
    code = setup["sent"][0][1]
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1):
        response = reset(wrong)
        assert response.status_code == 400
        assert f"{left} attempt" in response.json()["detail"]
    assert reset(wrong).json()["detail"] == main.INVALID_CODE_MESSAGE
    # Even the right code no longer works after 5 wrong tries.
    assert reset(code).status_code == 400
    assert login(PASSWORD).status_code == 200


def test_expired_code_is_rejected(setup):
    forgot()
    code = setup["sent"][0][1]
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    db = sqlite3.connect(setup["db"])
    db.execute("UPDATE password_reset_codes SET expires_at = ?", (past,))
    db.commit()
    db.close()
    assert reset(code).json()["detail"] == main.INVALID_CODE_MESSAGE


def test_new_code_replaces_old_one(setup):
    forgot()
    forgot()
    first, second = setup["sent"][0][1], setup["sent"][1][1]
    if first != second:
        assert reset(first).status_code == 400
    assert reset(second).status_code == 200


def test_weak_new_password_is_rejected_without_using_the_code(setup):
    forgot()
    code = setup["sent"][0][1]
    assert reset(code, "weak").status_code == 400
    assert reset(code).status_code == 200


def test_forgot_password_is_rate_limited_per_email(setup):
    statuses = [forgot().status_code for _ in range(main.RESET_RATE_PER_EMAIL + 1)]
    assert statuses[:-1] == [200] * main.RESET_RATE_PER_EMAIL
    assert statuses[-1] == 429


def test_reset_without_requesting_code_fails():
    assert reset("123456").json()["detail"] == main.INVALID_CODE_MESSAGE


def test_inactive_user_gets_no_code(setup):
    db = sqlite3.connect(setup["db"])
    db.execute("UPDATE users SET is_active = 0")
    db.commit()
    db.close()
    assert forgot().status_code == 200
    assert setup["sent"] == []
