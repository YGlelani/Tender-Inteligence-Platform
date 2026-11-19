import hashlib
import hmac
import html
import logging
import os
import secrets
import smtplib
import sqlite3
import ssl
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "").strip()
APP_URL = os.getenv("APP_URL", "").strip().rstrip("/")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").strip().rstrip("/")
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = (os.getenv("SMTP_USE_TLS") or "true").lower() == "true"
NOTIFY_INTERVAL_MINUTES = int(os.getenv("NOTIFY_INTERVAL_MINUTES") or "10")
MATCH_MIN_SCORE = int(os.getenv("MATCH_MIN_SCORE") or "71")
ENABLE_SCHEDULER = (os.getenv("ENABLE_SCHEDULER") or "true").lower() == "true"
EMAIL_RETRY_HOURS = 24
# Notifications are deleted this many days after they were created (0 keeps them all).
NOTIFICATION_RETENTION_DAYS = int(os.getenv("NOTIFICATION_RETENTION_DAYS") or "90")
SA_TZ = timezone(timedelta(hours=2))
logger = logging.getLogger("notifications-api")

# type: (label, bell default, email default, locked)
TYPES = {
    "password_changed": ("Password changed", True, True, True),
    "profile_updated": ("Profile updated", True, False, False),
    "tender_closing_soon": ("Saved tender closing soon", True, True, False),
    "tender_updated": ("Saved tender updated", True, True, False),
    "tender_cancelled": ("Saved tender cancelled", True, True, False),
    "new_matches": ("New tender matches", True, False, False),
}
INTERNAL_TYPES = {
    "password_changed": ("Your password was changed",
                         "Your Tender Scrapper password was changed. If this wasn't you, reset your password now.",
                         "profile.html"),
    "profile_updated": ("Profile updated", "Your profile details were updated.", "profile.html"),
}


@asynccontextmanager
async def lifespan(_app):
    initialize_database()
    stop = threading.Event()
    if ENABLE_SCHEDULER:
        threading.Thread(target=scheduler_loop, args=(stop,), daemon=True, name="notification-job").start()
    yield
    stop.set()


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

# Web pages allowed to call this API from a browser, comma-separated
# (for example https://app.example.com). Set per environment in Compose.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logging.getLogger(__name__).warning("CORS_ORIGINS is not set: browsers on other sites cannot call this API.")

app = FastAPI(**API_DOCS, title="Notifications API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)


# ---------- database ----------

def now_utc():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat(timespec="seconds")


def db():
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 20000")
    return con


def initialize_database():
    con = db()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            tender_id INTEGER,
            in_app INTEGER NOT NULL DEFAULT 1,
            email_status TEXT NOT NULL DEFAULT 'skipped',
            email_attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            read_at TEXT,
            emailed_at TEXT,
            dedupe_key TEXT UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id) WHERE read_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_notifications_email ON notifications(email_status);
        CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            in_app INTEGER NOT NULL,
            email INTEGER NOT NULL,
            updated_at TEXT,
            UNIQUE(user_id, type)
        );
        CREATE TABLE IF NOT EXISTS notification_tender_snapshots (
            user_id INTEGER NOT NULL,
            tender_id INTEGER NOT NULL,
            closing_date TEXT,
            status TEXT,
            UNIQUE(user_id, tender_id)
        );
        CREATE TABLE IF NOT EXISTS notification_job_state (key TEXT PRIMARY KEY, value TEXT);
        """)
        con.commit()
    finally:
        con.close()


def table_exists(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


# ---------- preferences ----------

def user_preferences(con, user_id):
    stored = {r["type"]: r for r in con.execute(
        "SELECT type, in_app, email FROM notification_preferences WHERE user_id=?", (user_id,))}
    prefs = {}
    for type_, (label, bell, email, locked) in TYPES.items():
        row = stored.get(type_)
        if row is not None and not locked:
            bell, email = bool(row["in_app"]), bool(row["email"])
        prefs[type_] = {"type": type_, "label": label, "in_app": bell, "email": email, "locked": locked}
    return prefs


def locked_types():
    return [type_ for type_, (_label, _bell, _email, locked) in TYPES.items() if locked]


def is_deactivated(con, user_id):
    """True if the user exists and is switched off (for example, they deactivated
    their account). Their saved data is kept, but they get no reminders."""
    if not table_exists(con, "users"):
        return False
    row = con.execute("SELECT COALESCE(is_active, 1) AS active FROM users WHERE id=?", (user_id,)).fetchone()
    return row is not None and not row["active"]


def create_notification(con, user_id, type_, title, message, link=None, tender_id=None, dedupe_key=None):
    """Store a notification according to the user's preferences. Returns its id, or None.
    Deactivated users only get security notices (the locked types)."""
    if type_ not in locked_types() and is_deactivated(con, user_id):
        return None
    pref = user_preferences(con, user_id)[type_]
    if not pref["in_app"] and not pref["email"]:
        return None
    cur = con.execute(
        """INSERT OR IGNORE INTO notifications
           (user_id, type, title, message, link, tender_id, in_app, email_status, created_at, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, type_, title, message, link, tender_id, int(pref["in_app"]),
         "pending" if pref["email"] else "skipped", iso(now_utc()), dedupe_key))
    return cur.lastrowid if cur.rowcount else None


# ---------- email ----------

# Unsubscribe links are signed with their own key, derived from JWT_SECRET, so a
# link can never pass as a sign-in token or the other way round. They name their
# audience and stop working after UNSUBSCRIBE_LINK_DAYS.
UNSUBSCRIBE_AUDIENCE = "tender-scrapper:unsubscribe"
UNSUBSCRIBE_LINK_DAYS = int(os.getenv("UNSUBSCRIBE_LINK_DAYS") or "90")


def unsubscribe_key():
    return hmac.new((JWT_SECRET or "").encode(), b"tender-scrapper unsubscribe links v1", hashlib.sha256).hexdigest()


def unsubscribe_token(user_id, type_):
    now = now_utc()
    claims = {"sub": str(user_id), "type": type_, "aud": UNSUBSCRIBE_AUDIENCE,
              "iat": now, "exp": now + timedelta(days=UNSUBSCRIBE_LINK_DAYS)}
    return jwt.encode(claims, unsubscribe_key(), algorithm="HS256")


def send_email(to, subject, text, html_body):
    missing = [k for k, v in {"SMTP_HOST": SMTP_HOST, "SMTP_USERNAME": SMTP_USERNAME,
                              "SMTP_PASSWORD": SMTP_PASSWORD, "EMAIL_FROM": EMAIL_FROM}.items() if not v]
    if missing:
        raise RuntimeError("Email settings missing: " + ", ".join(missing))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, EMAIL_FROM, to
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    ctx = ssl.create_default_context()
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo(); server.starttls(context=ctx); server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD); server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15, context=ctx) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD); server.send_message(msg)


def render_email(row):
    link = (APP_URL + "/" + row["link"]) if APP_URL and row["link"] else ""
    unsubscribe = ""
    if PUBLIC_API_URL and not TYPES[row["type"]][3] and JWT_SECRET:
        unsubscribe = PUBLIC_API_URL + "/notifications/unsubscribe?token=" + quote(unsubscribe_token(row["user_id"], row["type"]))
    text = row["title"] + "\n\n" + row["message"]
    body = "<h2>" + html.escape(row["title"]) + "</h2><p>" + html.escape(row["message"]) + "</p>"
    if link:
        text += "\n\nOpen Tender Scrapper: " + link
        body += '<p><a href="' + html.escape(link, quote=True) + '">Open Tender Scrapper</a></p>'
    if unsubscribe:
        text += "\n\nStop these emails: " + unsubscribe
        body += '<p><small><a href="' + html.escape(unsubscribe, quote=True) + '">Unsubscribe from these emails</a></small></p>'
    return text, "<html><body>" + body + "</body></html>"


def send_pending_emails(con, notification_id=None):
    cutoff = iso(now_utc() - timedelta(hours=EMAIL_RETRY_HOURS))
    con.execute("UPDATE notifications SET email_status='failed' WHERE email_status='pending' AND created_at < ?", (cutoff,))
    con.commit()
    # Emails still waiting when a user deactivated their account are not sent,
    # except security notices.
    locked = locked_types()
    placeholders = ", ".join("?" for _ in locked)
    query = f"""SELECT n.*, u.email AS user_email FROM notifications n JOIN users u ON u.id = n.user_id
                WHERE n.email_status='pending'
                  AND (COALESCE(u.is_active, 1) = 1 OR n.type IN ({placeholders}))"""
    params = tuple(locked)
    if notification_id is not None:
        query += " AND n.id=?"
        params += (notification_id,)
    for row in con.execute(query + " ORDER BY n.id LIMIT 50", params).fetchall():
        text, html_body = render_email(row)
        try:
            send_email(row["user_email"], row["title"], text, html_body)
            con.execute("UPDATE notifications SET email_status='sent', emailed_at=?, email_attempts=email_attempts+1 WHERE id=?",
                        (iso(now_utc()), row["id"]))
        except Exception:
            logger.exception("Notification email %s failed", row["id"])
            con.execute("UPDATE notifications SET email_attempts=email_attempts+1 WHERE id=?", (row["id"],))
        con.commit()


# ---------- background job ----------

def parse_closing(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if len(text) == 10:  # date only: end of that day
        parsed = datetime.combine(parsed.date(), dtime(23, 59))
    return parsed.replace(tzinfo=SA_TZ) if parsed.tzinfo is None else parsed


def is_cancelled(status_value):
    return "cancel" in (status_value or "").lower()


def is_closed(status_value):
    s = (status_value or "").lower()
    return "cancel" in s or "closed" in s or "award" in s


def tender_label(row):
    return f"'{row['title']}' ({row['tender_number']})"


def check_new_matches(con):
    if not table_exists(con, "profile_alert_notifications"):
        return
    state = con.execute("SELECT value FROM notification_job_state WHERE key='last_match_id'").fetchone()
    newest = con.execute("SELECT COALESCE(MAX(id), 0) FROM profile_alert_notifications").fetchone()[0]
    if state is not None:
        last = int(state["value"])
        rows = con.execute(
            """SELECT user_id, COUNT(*) AS n, MAX(id) AS max_id FROM profile_alert_notifications
               WHERE id > ? AND id <= ? AND score >= ? GROUP BY user_id""", (last, newest, MATCH_MIN_SCORE)).fetchall()
        for r in rows:
            word = "tender matches" if r["n"] == 1 else "tenders match"
            create_notification(con, r["user_id"], "new_matches", "New tender matches",
                                f"{r['n']} new {word} your business profile.", "alerts.html",
                                dedupe_key=f"matches:{r['user_id']}:{r['max_id']}")
    con.execute("INSERT INTO notification_job_state(key, value) VALUES ('last_match_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(newest),))
    con.commit()


def saved_tenders(con):
    if not (table_exists(con, "saved_tenders") and table_exists(con, "tenders")):
        return []
    return con.execute(
        """SELECT s.user_id, t.id AS tender_id, t.title, t.tender_number, t.closing_date, t.status,
                  snap.user_id AS snap_user, snap.closing_date AS snap_closing, snap.status AS snap_status
           FROM saved_tenders s JOIN tenders t ON t.id = s.tender_id
           LEFT JOIN notification_tender_snapshots snap ON snap.user_id = s.user_id AND snap.tender_id = t.id""").fetchall()


def check_tender_changes(con, rows):
    for r in rows:
        if r["snap_user"] is not None:
            if is_cancelled(r["status"]) and not is_cancelled(r["snap_status"]):
                create_notification(con, r["user_id"], "tender_cancelled", "Saved tender cancelled",
                                    f"{tender_label(r)} has been cancelled.", "saved-tenders.html", r["tender_id"],
                                    f"cancelled:{r['user_id']}:{r['tender_id']}")
            elif (r["closing_date"] or "") != (r["snap_closing"] or ""):
                create_notification(con, r["user_id"], "tender_updated", "Saved tender updated",
                                    f"The closing date of {tender_label(r)} changed to {r['closing_date'] or 'not set'}.",
                                    "saved-tenders.html", r["tender_id"],
                                    f"updated:{r['user_id']}:{r['tender_id']}:{r['closing_date']}")
        con.execute(
            """INSERT INTO notification_tender_snapshots(user_id, tender_id, closing_date, status) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, tender_id) DO UPDATE SET closing_date=excluded.closing_date, status=excluded.status""",
            (r["user_id"], r["tender_id"], r["closing_date"], r["status"]))
    con.commit()


def check_closing_soon(con, rows):
    current = now_utc()
    for r in rows:
        closing = parse_closing(r["closing_date"])
        if closing is None or is_closed(r["status"]):
            continue
        left = closing - current
        if timedelta(0) < left <= timedelta(days=1):
            window, words = "1d", "1 day"
        elif timedelta(days=1) < left <= timedelta(days=3):
            window, words = "3d", "3 days"
        else:
            continue
        create_notification(con, r["user_id"], "tender_closing_soon", "Saved tender closing soon",
                            f"{tender_label(r)} closes in less than {words} ({closing.strftime('%d %b %Y %H:%M')}).",
                            "saved-tenders.html", r["tender_id"], f"closing:{window}:{r['user_id']}:{r['tender_id']}")
    con.commit()


def delete_old_notifications(con):
    """Delete notifications older than NOTIFICATION_RETENTION_DAYS (0 keeps them all)."""
    if NOTIFICATION_RETENTION_DAYS <= 0:
        return 0
    # created_at is always written by iso(now_utc()), so the strings compare in time order.
    cutoff = iso(now_utc() - timedelta(days=NOTIFICATION_RETENTION_DAYS))
    deleted = con.execute("DELETE FROM notifications WHERE created_at < ?", (cutoff,)).rowcount
    con.commit()
    if deleted:
        logger.info("Deleted %d notifications older than %d days", deleted, NOTIFICATION_RETENTION_DAYS)
    return deleted


def run_job_once():
    con = db()
    try:
        delete_old_notifications(con)
        check_new_matches(con)
        rows = saved_tenders(con)
        check_tender_changes(con, rows)
        check_closing_soon(con, rows)
        if table_exists(con, "users"):
            send_pending_emails(con)
    finally:
        con.close()


def scheduler_loop(stop):
    while not stop.is_set():
        try:
            run_job_once()
        except Exception:
            logger.exception("Notification job failed")
        stop.wait(NOTIFY_INTERVAL_MINUTES * 60)


# ---------- auth ----------

# Sign-ins end when the password is changed or reset: the Login API stores
# sessions_valid_after (Unix seconds) on the user, and tokens issued before it
# are refused. Databases the Login API has not touched yet have no column.
def session_cutoff_column(con) -> str:
    columns = {row[1] for row in con.execute("PRAGMA table_info(users)")}
    return "sessions_valid_after" if "sessions_valid_after" in columns else "NULL"


def issued_before_cutoff(claims: dict, cutoff) -> bool:
    if cutoff is None:
        return False
    issued_at = claims.get("iat")
    return not isinstance(issued_at, (int, float)) or issued_at < cutoff


# Signing out ends that one sign-in: the Login API lists the token's id ("jti")
# in revoked_tokens. Tokens without an id, or databases without the table, pass.
def token_signed_out(con, claims: dict) -> bool:
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        return False
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revoked_tokens'").fetchone():
        return False
    return con.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone() is not None


def current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> int:
    if credentials is None:
        raise HTTPException(401, detail="Authentication required")
    if not JWT_SECRET:
        raise HTTPException(503, detail="Authentication is not configured")
    try:
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM],
                            options={"require": ["exp", "sub"]})
        username = claims.get("sub")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Missing subject")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(401, detail="Invalid or expired access token")
    con = db()
    try:
        row = con.execute(
            f"SELECT id, {session_cutoff_column(con)} AS sessions_valid_after FROM users WHERE username=? AND is_active=1",
            (username,),
        ).fetchone()
        signed_out = token_signed_out(con, claims)
    except sqlite3.Error:
        raise HTTPException(503, detail="Unable to resolve authenticated user")
    finally:
        con.close()
    if row is None:
        raise HTTPException(401, detail="Token user is not active or no longer exists")
    if issued_before_cutoff(claims, row["sessions_valid_after"]) or signed_out:
        raise HTTPException(401, detail="Your session has ended. Please sign in again.")
    return int(row["id"])


def require_internal_key(x_internal_key: str | None = Header(default=None)):
    if not INTERNAL_API_KEY:
        raise HTTPException(503, detail="INTERNAL_API_KEY is not configured")
    if not x_internal_key or not secrets.compare_digest(x_internal_key, INTERNAL_API_KEY):
        raise HTTPException(401, detail="Invalid internal key")


# ---------- schemas ----------

class PreferenceIn(BaseModel):
    type: str
    in_app: bool
    email: bool


class PreferencesUpdate(BaseModel):
    preferences: list[PreferenceIn] = Field(..., max_length=len(TYPES))


class InternalNotification(BaseModel):
    type: str
    user_id: int | None = None
    username: str | None = Field(default=None, max_length=254)
    title: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=500)
    dedupe_key: str | None = Field(default=None, max_length=200)


APPLICATION_STATUSES = ("Interested", "Preparing", "Submitted", "Won", "Lost")


class SavedTenderIn(BaseModel):
    tender_id: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class SavedTenderNotes(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class ApplicationIn(BaseModel):
    tender_id: int | None = Field(default=None, gt=0)
    tender_number: str | None = Field(default=None, min_length=1, max_length=200)
    status: str = Field(default="Interested", pattern="^(Interested|Preparing|Submitted|Won|Lost)$")
    application_deadline: str | None = Field(default=None, max_length=30)
    submission_date: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=10000)


class ApplicationUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(Interested|Preparing|Submitted|Won|Lost)$")
    application_deadline: str | None = Field(default=None, max_length=30)
    submission_date: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=10000)


def serialize(row):
    return {"id": row["id"], "type": row["type"], "title": row["title"], "message": row["message"],
            "link": row["link"], "tender_id": row["tender_id"], "created_at": row["created_at"],
            "read_at": row["read_at"], "is_read": row["read_at"] is not None}


# ---------- routes ----------

@app.get("/")
def root():
    return {"message": "Notifications API is running", "database": "SQLite"}


@app.get("/health")
def health():
    con = None
    try:
        con = db()
        con.execute("SELECT 1").fetchone()
        return {"status": "healthy", "service": "notifications-api", "database": "connected"}
    except sqlite3.Error:
        raise HTTPException(503, detail="Database connection failed")
    finally:
        if con:
            con.close()


def _saved_tenders_for_user(con, user_id):
    rows = con.execute(
        """SELECT s.tender_id, s.notes, s.saved_at, t.tender_number, t.title, t.status,
                  t.province, t.closing_date, t.published_date, t.tender_url,
                  o.name AS organisation_name, c.name AS category_name
           FROM saved_tenders s JOIN tenders t ON t.id=s.tender_id
           LEFT JOIN organisations o ON o.id=t.organisation_id
           LEFT JOIN categories c ON c.id=t.category_id
           WHERE s.user_id=? ORDER BY s.saved_at DESC, s.tender_id DESC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/saved-tenders")
def list_saved_tenders(user_id: int = Depends(current_user_id)):
    con = db()
    try:
        items = _saved_tenders_for_user(con, user_id)
        return {"saved_tenders": items, "total": len(items)}
    except sqlite3.Error:
        raise HTTPException(503, detail="Saved tenders are not available")
    finally:
        con.close()


@app.post("/api/saved-tenders", status_code=201)
def save_tender(payload: SavedTenderIn, user_id: int = Depends(current_user_id)):
    con = db()
    try:
        if con.execute("SELECT 1 FROM tenders WHERE id=?", (payload.tender_id,)).fetchone() is None:
            raise HTTPException(404, detail="Tender not found")
        con.execute(
            """INSERT INTO saved_tenders(user_id, tender_id, notes) VALUES (?, ?, ?)
               ON CONFLICT(user_id, tender_id) DO UPDATE SET
                 notes=COALESCE(excluded.notes, saved_tenders.notes), updated_at=CURRENT_TIMESTAMP""",
            (user_id, payload.tender_id, payload.notes),
        )
        con.commit()
        return next(item for item in _saved_tenders_for_user(con, user_id)
                    if item["tender_id"] == payload.tender_id)
    except sqlite3.Error:
        raise HTTPException(503, detail="Saved tenders are not available")
    finally:
        con.close()


@app.patch("/api/saved-tenders/{tender_id}")
def update_saved_tender(tender_id: int, payload: SavedTenderNotes,
                        user_id: int = Depends(current_user_id)):
    con = db()
    try:
        cur = con.execute(
            "UPDATE saved_tenders SET notes=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND tender_id=?",
            (payload.notes, user_id, tender_id),
        )
        if not cur.rowcount:
            raise HTTPException(404, detail="Saved tender not found")
        con.commit()
        return next(item for item in _saved_tenders_for_user(con, user_id)
                    if item["tender_id"] == tender_id)
    except sqlite3.Error:
        raise HTTPException(503, detail="Saved tenders are not available")
    finally:
        con.close()


@app.delete("/api/saved-tenders/{tender_id}", status_code=204)
def delete_saved_tender(tender_id: int, user_id: int = Depends(current_user_id)):
    con = db()
    try:
        cur = con.execute("DELETE FROM saved_tenders WHERE user_id=? AND tender_id=?", (user_id, tender_id))
        if not cur.rowcount:
            raise HTTPException(404, detail="Saved tender not found")
        con.commit()
        return Response(status_code=204)
    except sqlite3.Error:
        raise HTTPException(503, detail="Saved tenders are not available")
    finally:
        con.close()


def _application_by_id(con, user_id, application_id):
    row = con.execute(
        """SELECT a.*, t.tender_number AS tender_reference, t.title AS tender_title,
                  t.closing_date, o.name AS organisation_name
           FROM tender_applications a JOIN tenders t ON t.id=a.tender_id
           LEFT JOIN organisations o ON o.id=t.organisation_id
           WHERE a.user_id=? AND a.id=?""",
        (user_id, application_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail="Application not found")
    item = dict(row)
    deadline = item.get("application_deadline")
    item["is_overdue"] = bool(deadline and deadline[:10] < now_utc().date().isoformat()
                               and item["status"] not in ("Won", "Lost", "Submitted"))
    return item


@app.get("/api/applications")
def list_applications(status_filter: str | None = Query(None, alias="status"),
                      limit: int = Query(100, ge=1, le=500),
                      sort_by: str = Query("deadline", pattern="^(deadline|created_at|status)$"),
                      sort_order: str = Query("asc", pattern="^(asc|desc)$"),
                      user_id: int = Depends(current_user_id)):
    con = db()
    try:
        where = "a.user_id=?"
        params = [user_id]
        sort_column = {"deadline": "application_deadline", "created_at": "created_at", "status": "status"}[sort_by]
        if status_filter:
            if status_filter not in APPLICATION_STATUSES:
                raise HTTPException(422, detail="Invalid application status")
            where += " AND a.status=?"
            params.append(status_filter)
        total = con.execute(f"SELECT COUNT(*) FROM tender_applications a WHERE {where}", params).fetchone()[0]
        rows = con.execute(
            f"""SELECT a.id FROM tender_applications a WHERE {where}
                ORDER BY a.{sort_column} {sort_order.upper()}, a.id LIMIT ?""",
            [*params, limit],
        ).fetchall()
        items = [_application_by_id(con, user_id, row["id"]) for row in rows]
        counts = {status: con.execute(
            "SELECT COUNT(*) FROM tender_applications WHERE user_id=? AND status=?", (user_id, status)
        ).fetchone()[0] for status in APPLICATION_STATUSES}
        return {"applications": items, "total": total, "counts": counts}
    except sqlite3.Error:
        raise HTTPException(503, detail="Applications are not available")
    finally:
        con.close()


@app.get("/api/applications/stats")
def application_stats(user_id: int = Depends(current_user_id)):
    con = db()
    try:
        counts = {status: con.execute(
            "SELECT COUNT(*) FROM tender_applications WHERE user_id=? AND status=?", (user_id, status)
        ).fetchone()[0] for status in APPLICATION_STATUSES}
        return {"total": sum(counts.values()), "counts": counts}
    except sqlite3.Error:
        raise HTTPException(503, detail="Applications are not available")
    finally:
        con.close()


@app.post("/api/applications", status_code=201)
def create_application(payload: ApplicationIn, user_id: int = Depends(current_user_id)):
    if not payload.tender_id and not payload.tender_number:
        raise HTTPException(422, detail="tender_id or tender_number is required")
    con = db()
    try:
        if payload.tender_id:
            tender = con.execute("SELECT id FROM tenders WHERE id=?", (payload.tender_id,)).fetchone()
        else:
            tender = con.execute("SELECT id FROM tenders WHERE tender_number=?", (payload.tender_number.strip(),)).fetchone()
        if tender is None:
            raise HTTPException(404, detail="Tender not found")
        application_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO tender_applications
               (id, user_id, tender_id, status, application_deadline, submission_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (application_id, user_id, tender["id"], payload.status,
             payload.application_deadline, payload.submission_date, payload.notes),
        )
        con.execute(
            "INSERT INTO tender_application_history(id, application_id, previous_status, new_status) VALUES (?, ?, NULL, ?)",
            (str(uuid.uuid4()), application_id, payload.status),
        )
        con.commit()
        return _application_by_id(con, user_id, application_id)
    except sqlite3.IntegrityError:
        con.rollback()
        raise HTTPException(409, detail="Application already exists for this tender")
    except sqlite3.Error:
        con.rollback()
        raise HTTPException(503, detail="Applications are not available")
    finally:
        con.close()


@app.patch("/api/applications/{application_id}")
def update_application(application_id: str, payload: ApplicationUpdate,
                       user_id: int = Depends(current_user_id)):
    con = db()
    try:
        current = con.execute(
            "SELECT status FROM tender_applications WHERE id=? AND user_id=?", (application_id, user_id)
        ).fetchone()
        if current is None:
            raise HTTPException(404, detail="Application not found")
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return _application_by_id(con, user_id, application_id)
        new_status = changes.get("status")
        assignments = [f"{field}=?" for field in changes]
        assignments.append("updated_at=CURRENT_TIMESTAMP")
        con.execute(f"UPDATE tender_applications SET {', '.join(assignments)} WHERE id=? AND user_id=?",
                    [*changes.values(), application_id, user_id])
        if new_status and new_status != current["status"]:
            con.execute(
                "INSERT INTO tender_application_history(id, application_id, previous_status, new_status) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), application_id, current["status"], new_status),
            )
        con.commit()
        return _application_by_id(con, user_id, application_id)
    except sqlite3.Error:
        con.rollback()
        raise HTTPException(503, detail="Applications are not available")
    finally:
        con.close()


@app.delete("/api/applications/{application_id}", status_code=204)
def delete_application(application_id: str, user_id: int = Depends(current_user_id)):
    con = db()
    try:
        cur = con.execute("DELETE FROM tender_applications WHERE id=? AND user_id=?", (application_id, user_id))
        if not cur.rowcount:
            raise HTTPException(404, detail="Application not found")
        con.execute("DELETE FROM tender_application_history WHERE application_id=?", (application_id,))
        con.commit()
        return Response(status_code=204)
    except sqlite3.Error:
        con.rollback()
        raise HTTPException(503, detail="Applications are not available")
    finally:
        con.close()


@app.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = Query(20, ge=1, le=100),
                       user_id: int = Depends(current_user_id)):
    con = db()
    try:
        query = "SELECT * FROM notifications WHERE user_id=? AND in_app=1"
        if unread_only:
            query += " AND read_at IS NULL"
        rows = con.execute(query + " ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
        return [serialize(r) for r in rows]
    finally:
        con.close()


@app.get("/notifications/unread-count")
def unread_count(user_id: int = Depends(current_user_id)):
    con = db()
    try:
        n = con.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND in_app=1 AND read_at IS NULL",
                        (user_id,)).fetchone()[0]
        return {"unread": n}
    finally:
        con.close()


@app.post("/notifications/read-all")
def read_all(user_id: int = Depends(current_user_id)):
    con = db()
    try:
        cur = con.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND in_app=1 AND read_at IS NULL",
                          (iso(now_utc()), user_id))
        con.commit()
        return {"updated": cur.rowcount}
    finally:
        con.close()


@app.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: int, user_id: int = Depends(current_user_id)):
    con = db()
    try:
        row = con.execute("SELECT read_at FROM notifications WHERE id=? AND user_id=? AND in_app=1",
                          (notification_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, detail="Notification not found")
        if row["read_at"] is None:
            con.execute("UPDATE notifications SET read_at=? WHERE id=?", (iso(now_utc()), notification_id))
            con.commit()
        return Response(status_code=204)
    finally:
        con.close()


@app.get("/notification-preferences")
def get_preferences(user_id: int = Depends(current_user_id)):
    con = db()
    try:
        return {"preferences": list(user_preferences(con, user_id).values())}
    finally:
        con.close()


def save_preference(con, user_id, type_, in_app, email):
    con.execute(
        """INSERT INTO notification_preferences(user_id, type, in_app, email, updated_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, type) DO UPDATE SET in_app=excluded.in_app, email=excluded.email,
           updated_at=excluded.updated_at""", (user_id, type_, int(in_app), int(email), iso(now_utc())))


@app.put("/notification-preferences")
def update_preferences(payload: PreferencesUpdate, user_id: int = Depends(current_user_id)):
    for p in payload.preferences:
        if p.type not in TYPES:
            raise HTTPException(400, detail=f"Unknown notification type: {p.type}")
        if TYPES[p.type][3] and not (p.in_app and p.email):
            raise HTTPException(400, detail=f"{TYPES[p.type][0]} notifications cannot be turned off")
    con = db()
    try:
        for p in payload.preferences:
            if not TYPES[p.type][3]:
                save_preference(con, user_id, p.type, p.in_app, p.email)
        con.commit()
        return {"preferences": list(user_preferences(con, user_id).values())}
    finally:
        con.close()


def result_page(title, message, ok=True):
    color = "#16a34a" if ok else "#dc2626"
    return HTMLResponse(
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + html.escape(title) + '</title></head><body style="font-family:Arial;background:#f1f5f9;display:grid;'
        'place-items:center;min-height:100vh"><main style="background:white;padding:40px;border-radius:16px;max-width:520px;'
        'text-align:center"><h2 style="color:' + color + '">Tender Scrapper</h2><h1>' + html.escape(title) + "</h1><p>"
        + html.escape(message) + "</p></main></body></html>", status_code=200 if ok else 400)


@app.get("/notifications/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = Query(..., min_length=10)):
    try:
        if not JWT_SECRET:
            raise ValueError("no secret")
        claims = jwt.decode(token, unsubscribe_key(), algorithms=["HS256"], audience=UNSUBSCRIBE_AUDIENCE,
                            options={"require": ["exp", "sub", "aud"]})
        user_id, type_ = int(claims["sub"]), claims["type"]
        if type_ not in TYPES or TYPES[type_][3]:
            raise ValueError("bad claims")
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return result_page("Link not valid", "This unsubscribe link is invalid or has expired. "
                                             "You can turn emails off in your notification settings.", ok=False)
    con = db()
    try:
        current = user_preferences(con, user_id)[type_]
        save_preference(con, user_id, type_, current["in_app"], False)
        con.commit()
    finally:
        con.close()
    return result_page("Unsubscribed", f"You will no longer receive '{TYPES[type_][0]}' emails. "
                                       "You can turn them back on in your notification settings.")


@app.post("/internal/notifications", status_code=201, dependencies=[Depends(require_internal_key)])
def internal_notification(payload: InternalNotification):
    if payload.type not in INTERNAL_TYPES:
        raise HTTPException(400, detail="Unsupported notification type for internal use")
    if payload.user_id is None and not payload.username:
        raise HTTPException(400, detail="user_id or username is required")
    title, message, link = INTERNAL_TYPES[payload.type]
    con = db()
    try:
        if payload.user_id is not None:
            user = con.execute("SELECT id FROM users WHERE id=?", (payload.user_id,)).fetchone()
        else:
            user = con.execute("SELECT id FROM users WHERE username=? OR email=?",
                               (payload.username, payload.username.lower())).fetchone()
        if user is None:
            raise HTTPException(404, detail="User not found")
        notification_id = create_notification(con, user["id"], payload.type, payload.title or title,
                                               payload.message or message, payload.link or link,
                                               dedupe_key=payload.dedupe_key)
        con.commit()
        if notification_id and payload.type == "password_changed":
            send_pending_emails(con, notification_id)
        return {"id": notification_id, "created": notification_id is not None}
    finally:
        con.close()
