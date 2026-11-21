"""Tokens issued before the user's last password change or reset are refused."""
import time

import jwt

import main
from test_account_deletion import ME, SECRET, client  # noqa: F401


def profile(client, **claims):
    claims = {"sub": ME, "exp": int(time.time()) + 3600, **claims}
    claims = {k: v for k, v in claims.items() if v is not None}
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    return client.get("/user/profile", headers={"Authorization": "Bearer " + token})


def set_cutoff(seconds_ago):
    con = main.db()
    con.execute("UPDATE users SET sessions_valid_after = ? WHERE username = ?", (int(time.time()) - seconds_ago, ME))
    con.commit()
    con.close()


def test_without_a_cut_off_old_and_new_tokens_work(client):
    assert profile(client).status_code == 200
    assert profile(client, iat=int(time.time())).status_code == 200


def test_tokens_from_before_the_cut_off_are_refused(client):
    set_cutoff(10)
    old = profile(client, iat=int(time.time()) - 60)
    assert old.status_code == 401
    assert old.json()["detail"] == "Your session has ended. Please sign in again."
    assert profile(client).status_code == 401  # no issue time at all
    assert profile(client, iat=int(time.time())).status_code == 200


def test_tokens_without_an_expiry_are_refused(client):
    assert profile(client, exp=None).status_code == 401


def test_the_column_is_created(client):
    con = main.db()
    columns = {row["name"] for row in con.execute("PRAGMA table_info(users)")}
    con.close()
    assert "sessions_valid_after" in columns


def test_a_token_its_user_signed_out_with_is_refused(client):
    """The Login API lists signed-out token ids in revoked_tokens; other sign-ins keep working."""
    import sqlite3
    import time

    def get(jti):
        claims = {"sub": 'tenders@company.co.za', "exp": int(time.time()) + 3600, "iat": int(time.time()), "jti": jti}
        token = jwt.encode(claims, SECRET, algorithm="HS256")
        return client.get('/user/profile', headers={"Authorization": "Bearer " + token}).status_code

    assert get("phone") != 401  # no table yet
    db = sqlite3.connect(main.DB_PATH)
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
