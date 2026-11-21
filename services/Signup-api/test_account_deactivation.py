"""POST /user/deactivate and the deletion of accounts left deactivated."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import main
from test_account_deletion import ME, OTHER, PASSWORD, client, headers, rows_for  # noqa: F401

NOW = datetime(2027, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def mail(client, monkeypatch):
    sent = {"deactivated": [], "warned": []}
    monkeypatch.setattr(
        main, "send_deactivation_confirmation", lambda to, when: sent["deactivated"].append((to, when))
    )
    monkeypatch.setattr(
        main, "send_deletion_warning", lambda to, when: sent["warned"].append((to, when))
    )
    return sent


def deactivate(client, password=PASSWORD):
    return client.post("/user/deactivate", json={"password": password}, headers=headers())


def account(email=ME):
    con = main.db()
    try:
        return con.execute(
            "SELECT is_active, deactivated_at, deletion_warning_sent_at FROM users WHERE email=?",
            (email,),
        ).fetchone()
    finally:
        con.close()


def deactivated_days_ago(days, email=ME):
    con = main.db()
    try:
        con.execute(
            "UPDATE users SET is_active=0, deactivated_at=? WHERE email=?",
            ((NOW - timedelta(days=days)).isoformat(), email),
        )
        con.commit()
    finally:
        con.close()


def test_deactivate_switches_the_account_off_and_keeps_everything(client, mail):
    response = deactivate(client)

    assert response.status_code == 200
    body = response.json()
    assert body["deactivated"] is True
    expected = (datetime.now(UTC) + timedelta(days=365)).date()
    assert abs((datetime.fromisoformat(body["delete_on"]).date() - expected).days) <= 1
    row = account()
    assert row["is_active"] == 0 and row["deactivated_at"]
    assert set(rows_for(ME).values()) == {1}
    assert client.agent_calls == []
    assert [to for to, _ in mail["deactivated"]] == [ME]


def test_token_stops_working_once_deactivated(client, mail):
    deactivate(client)

    assert client.get("/user/profile", headers=headers()).status_code == 401


def test_wrong_password_does_not_deactivate(client, mail):
    response = deactivate(client, password="Wrong123!")

    assert response.status_code == 403
    assert response.json()["detail"] == main.WRONG_PASSWORD_ERROR
    assert account()["is_active"] == 1
    assert mail["deactivated"] == []


def test_deactivate_needs_a_token(client, mail):
    assert client.post("/user/deactivate", json={"password": PASSWORD}).status_code == 401


def test_failed_email_does_not_undo_deactivation(client, monkeypatch, caplog):
    def smtp_down(to, when):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(main, "send_deactivation_confirmation", smtp_down)

    assert deactivate(client).status_code == 200
    assert account()["is_active"] == 0
    assert "Account deactivation email could not be sent" in caplog.text


def test_account_is_deleted_twelve_months_after_deactivation(client, mail):
    deactivated_days_ago(366)

    main.run_account_jobs(NOW)

    assert set(rows_for(ME).values()) == {0}
    assert set(rows_for(OTHER).values()) == {1}
    assert client.agent_calls == [ME]
    assert client.emails == [ME]


def test_account_is_kept_until_twelve_months_have_passed(client, mail):
    deactivated_days_ago(364)

    main.run_account_jobs(NOW)

    assert set(rows_for(ME).values()) == {1}
    assert client.agent_calls == []


def test_owner_is_warned_once_thirty_days_before(client, mail):
    deactivated_days_ago(336)

    main.run_account_jobs(NOW)
    main.run_account_jobs(NOW + timedelta(hours=1))

    assert len(mail["warned"]) == 1
    to, when = mail["warned"][0]
    assert to == ME
    assert when == NOW - timedelta(days=336) + timedelta(days=365)
    assert account()["deletion_warning_sent_at"]
    assert set(rows_for(ME).values()) == {1}


def test_no_warning_earlier_than_thirty_days_before(client, mail):
    deactivated_days_ago(300)

    main.run_account_jobs(NOW)

    assert mail["warned"] == []


def test_failed_warning_is_tried_again(client, mail, monkeypatch):
    deactivated_days_ago(340)
    monkeypatch.setattr(main, "send_deletion_warning", lambda to, when: 1 / 0)
    main.run_account_jobs(NOW)
    assert account()["deletion_warning_sent_at"] is None

    monkeypatch.setattr(main, "send_deletion_warning", lambda to, when: mail["warned"].append(to))
    main.run_account_jobs(NOW)
    assert mail["warned"] == [ME]


def test_account_reactivated_during_deletion_is_kept(client, mail, monkeypatch):
    deactivated_days_ago(400)

    def owner_signs_in_meanwhile(email):
        con = main.db()
        con.execute("UPDATE users SET is_active=1, deactivated_at=NULL WHERE email=?", (email,))
        con.commit()
        con.close()

    monkeypatch.setattr(main, "delete_agent_data", owner_signs_in_meanwhile)

    main.run_account_jobs(NOW)

    assert set(rows_for(ME).values()) == {1}
    assert account()["is_active"] == 1


def test_agent_failure_keeps_the_account_until_the_next_run(client, mail, monkeypatch):
    deactivated_days_ago(400)
    calls = []

    def agent_down_once(email):
        calls.append(email)
        if len(calls) == 1:
            raise OSError("connection refused")

    monkeypatch.setattr(main, "delete_agent_data", agent_down_once)

    main.run_account_jobs(NOW)
    assert set(rows_for(ME).values()) == {1}

    main.run_account_jobs(NOW + timedelta(hours=1))
    assert set(rows_for(ME).values()) == {0}


def test_accounts_switched_off_by_someone_else_are_left_alone(client, mail):
    con = main.db()
    con.execute("UPDATE users SET is_active=0 WHERE email=?", (ME,))
    con.commit()
    con.close()

    main.run_account_jobs(NOW + timedelta(days=5000))

    assert set(rows_for(ME).values()) == {1}
    assert mail["warned"] == []


def test_columns_are_added_to_an_existing_users_table(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "old.db"))
    con = sqlite3.connect(tmp_path / "old.db")
    con.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
        "email TEXT NOT NULL UNIQUE, hashed_password TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1)"
    )
    con.commit()
    con.close()

    main.initialize_database()

    con = main.db()
    columns = {row["name"] for row in con.execute("PRAGMA table_info(users)")}
    con.close()
    assert {"deactivated_at", "deletion_warning_sent_at"} <= columns
