"""Signing in to an account its owner deactivated (in the Signup API), and
reactivating it with a code sent by email."""
import sqlite3
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
USERNAME = "tenders@company.co.za"
PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def mail(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE users (username TEXT PRIMARY KEY, hashed_password TEXT NOT NULL, "
        "is_active INTEGER NOT NULL DEFAULT 1, deactivated_at TEXT, deletion_warning_sent_at TEXT)"
    )
    db.execute(
        "INSERT INTO users (username, hashed_password, is_active) VALUES (?, ?, 1)",
        (USERNAME, bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()),
    )
    db.commit()
    db.close()
    monkeypatch.setattr(main, "DATABASE_PATH", str(path))
    main._login_failures.clear()
    main._reset_attempts.clear()
    sent = {"reset": [], "reactivate": [], "db": path}
    monkeypatch.setattr(main, "send_reset_code", lambda email, code: sent["reset"].append(code))
    monkeypatch.setattr(main, "send_reactivation_code", lambda email, code: sent["reactivate"].append((email, code)))
    monkeypatch.setattr(main, "notify_password_changed", lambda username: None)
    return sent


def sql(path, query, params=()):
    db = sqlite3.connect(path)
    try:
        rows = db.execute(query, params).fetchall()
        db.commit()
        return rows
    finally:
        db.close()


def deactivate(path):
    sql(path, "UPDATE users SET is_active = 0, deactivated_at = '2026-01-01T00:00:00+00:00', "
              "deletion_warning_sent_at = '2026-12-01T00:00:00+00:00'")


def post(path, password=PASSWORD, **extra):
    return client.post(path, data={"username": USERNAME, "password": password, **extra})


def emailed_code(mail):
    assert post("/reactivate/send-code").status_code == 200
    return mail["reactivate"][-1][1]


def is_active(path):
    return sql(path, "SELECT is_active FROM users")[0][0] == 1


# --- signing in -------------------------------------------------------------

def test_login_tells_a_deactivated_owner_after_the_right_password(mail):
    deactivate(mail["db"])
    response = post("/login")
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"]
    assert "access_token" not in response.json()


def test_wrong_password_on_a_deactivated_account_looks_like_any_other(mail):
    deactivate(mail["db"])
    response = post("/login", "WrongPassword1!")
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_deactivated_account_tokens_stop_working(mail):
    token = post("/login").json()["access_token"]
    deactivate(mail["db"])
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- the emailed code -------------------------------------------------------

def test_code_is_emailed_to_the_account_and_stored_hashed(mail):
    deactivate(mail["db"])
    response = post("/reactivate/send-code")
    assert response.status_code == 200
    assert USERNAME in response.json()["message"]
    email, code = mail["reactivate"][0]
    assert email == USERNAME and len(code) == 6 and code.isdigit()
    stored = sql(mail["db"], "SELECT code_hash FROM reactivation_codes")[0][0]
    assert code not in stored


def test_sending_a_code_needs_the_right_password(mail):
    deactivate(mail["db"])
    assert post("/reactivate/send-code", "WrongPassword1!").status_code == 401
    assert mail["reactivate"] == []


def test_no_code_for_an_active_account(mail):
    assert post("/reactivate/send-code").status_code == 400
    assert mail["reactivate"] == []


def test_sending_codes_is_rate_limited(mail):
    deactivate(mail["db"])
    statuses = [post("/reactivate/send-code").status_code for _ in range(main.RESET_RATE_PER_EMAIL + 1)]
    assert statuses == [200] * main.RESET_RATE_PER_EMAIL + [429]


# --- reactivating -----------------------------------------------------------

def test_reactivate_with_the_emailed_code(mail):
    deactivate(mail["db"])
    response = post("/reactivate", code=emailed_code(mail))
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert jwt.decode(token, main.SECRET_KEY, algorithms=["HS256"])["sub"] == USERNAME
    assert sql(mail["db"], "SELECT is_active, deactivated_at, deletion_warning_sent_at FROM users") == [(1, None, None)]
    assert sql(mail["db"], "SELECT COUNT(*) FROM reactivation_codes") == [(0,)]
    assert post("/login").status_code == 200
    assert client.get("/protected-tenders", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_reactivate_without_a_code_is_refused(mail):
    deactivate(mail["db"])
    response = post("/reactivate")
    assert response.status_code == 400
    assert "6-digit code" in response.json()["detail"]
    assert not is_active(mail["db"])


def test_reactivate_before_any_code_was_sent_is_refused(mail):
    deactivate(mail["db"])
    assert post("/reactivate", code="123456").status_code == 400
    assert not is_active(mail["db"])


def test_wrong_codes_count_down_and_then_stop_working(mail):
    deactivate(mail["db"])
    code = emailed_code(mail)
    wrong = "000000" if code != "000000" else "111111"
    details = [post("/reactivate", code=wrong).json()["detail"] for _ in range(main.REACTIVATION_MAX_ATTEMPTS)]
    assert details[0] == "That code is incorrect. 4 attempt(s) left."
    assert details[-1] == main.INVALID_REACTIVATION_CODE_MESSAGE
    # Even the right code no longer works after five wrong tries.
    assert post("/reactivate", code=code).status_code == 400
    assert not is_active(mail["db"])


def test_expired_code_is_refused(mail):
    deactivate(mail["db"])
    code = emailed_code(mail)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sql(mail["db"], "UPDATE reactivation_codes SET expires_at = ?", (past,))
    response = post("/reactivate", code=code)
    assert response.status_code == 400
    assert response.json()["detail"] == main.INVALID_REACTIVATION_CODE_MESSAGE
    assert not is_active(mail["db"])


def test_only_the_newest_code_works(mail):
    deactivate(mail["db"])
    first = emailed_code(mail)
    second = emailed_code(mail)
    if first != second:
        assert post("/reactivate", code=first).status_code == 400
    assert post("/reactivate", code=second).status_code == 200


def test_reactivate_needs_the_right_password_as_well(mail):
    deactivate(mail["db"])
    code = emailed_code(mail)
    assert post("/reactivate", "WrongPassword1!", code=code).status_code == 401
    assert not is_active(mail["db"])


def test_reactivate_on_an_active_account_just_signs_in(mail):
    response = post("/reactivate")
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_account_switched_off_by_someone_else_cannot_be_reactivated(mail):
    sql(mail["db"], "UPDATE users SET is_active = 0")  # no deactivated_at: not the owner's choice
    assert post("/login").status_code == 401
    assert post("/reactivate/send-code").status_code == 401
    assert post("/reactivate", code="123456").status_code == 401
    assert mail["reactivate"] == []
    assert not is_active(mail["db"])


def test_deactivated_owner_can_reset_a_forgotten_password(mail):
    deactivate(mail["db"])
    assert client.post("/forgot-password", json={"email": USERNAME}).status_code == 200
    assert len(mail["reset"]) == 1
    response = client.post(
        "/reset-password", json={"email": USERNAME, "code": mail["reset"][0], "new_password": "NewPassword456!"}
    )
    assert response.status_code == 200
    # Still deactivated until they confirm a reactivation code.
    assert post("/login", "NewPassword456!").status_code == 403
    assert post("/reactivate/send-code", "NewPassword456!").status_code == 200
    code = mail["reactivate"][-1][1]
    assert post("/reactivate", "NewPassword456!", code=code).status_code == 200


def test_reset_is_still_refused_for_accounts_switched_off_by_someone_else(mail):
    sql(mail["db"], "UPDATE users SET is_active = 0")
    assert client.post("/forgot-password", json={"email": USERNAME}).status_code == 200
    assert mail["reset"] == []


def test_failures_on_a_deactivated_account_still_count_towards_the_lock(mail):
    deactivate(mail["db"])
    for _ in range(main.LOGIN_MAX_FAILURES_PER_ACCOUNT):
        assert post("/reactivate", "WrongPassword1!").status_code == 401
    assert post("/reactivate").status_code == 429


def test_expired_reactivation_codes_are_purged(mail):
    deactivate(mail["db"])
    emailed_code(mail)
    assert main.purge_expired_reactivation_codes() == 0
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sql(mail["db"], "UPDATE reactivation_codes SET expires_at = ?", (past,))
    assert main.purge_expired_reactivation_codes() == 1
    assert sql(mail["db"], "SELECT COUNT(*) FROM reactivation_codes") == [(0,)]
