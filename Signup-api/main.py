import asyncio
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
import urllib.request
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlsplit

import bcrypt
import jwt
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EMAIL_CONFIRMATION_URL = os.getenv("EMAIL_CONFIRMATION_URL", "").strip()
LOGIN_URL = os.getenv("LOGIN_URL", "").strip() or "http://127.0.0.1:8005"
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
TOKEN_MINUTES = int(os.getenv("VERIFICATION_TOKEN_EXPIRE_MINUTES", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))
RATE_LIMIT_PER_IP = int(os.getenv("RATE_LIMIT_PER_IP", "10"))
RATE_LIMIT_PER_EMAIL = int(os.getenv("RATE_LIMIT_PER_EMAIL", "3"))
NOTIFICATIONS_API_URL = os.getenv("NOTIFICATIONS_API_URL", "").strip().rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "").strip()

MAX_PASSWORD_BYTES = 72
EMAIL_SEND_ERROR = "We could not send the verification email. Please try again later."

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
logger = logging.getLogger("signup-api")


class SignupRequest(BaseModel):
    company_name: str = Field(..., max_length=255)
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class ResendRequest(BaseModel):
    email: str = Field(..., max_length=254)


class ProfileUpdate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)


FREE_EMAILS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.za",
    "ymail.com",
    "outlook.com",
    "hotmail.com",
    "hotmail.co.za",
    "live.com",
    "live.co.za",
    "msn.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "zoho.com",
    "zohomail.com",
    "gmx.com",
    "mail.com",
    "yandex.com",
    "tuta.com",
    "tutanota.com",
}


def valid_email(email):
    """Accept name@domain.tld: one "@", no whitespace, and a dot in the domain
    with at least one character before it and two after it."""
    if len(email) > 254 or re.search(r"\s", email):
        return False
    local, _, domain = email.partition("@")
    return bool(local) and "@" not in domain and "." in domain[1:-2]


def business_email(email):
    return valid_email(email) and email.rsplit("@", 1)[1].lower() not in FREE_EMAILS


def password_error(password):
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password must be 72 characters or fewer."
    if not re.search(r"\d", password):
        return "Password must include a number."
    if not re.search(r"[A-Z]", password):
        return "Password must include an uppercase letter."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must include a special character."
    return None


_attempts = defaultdict(deque)
_attempts_lock = threading.Lock()


def rate_limited(key, limit):
    now = time.monotonic()
    with _attempts_lock:
        hits = _attempts[key]
        while hits and now - hits[0] > RATE_LIMIT_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False


def enforce_rate_limit(action, http_request, email):
    ip = http_request.client.host if http_request.client else "unknown"
    ip_limited = rate_limited(f"{action}:ip:{ip}", RATE_LIMIT_PER_IP)
    if ip_limited or rate_limited(f"{action}:email:{email}", RATE_LIMIT_PER_EMAIL):
        raise HTTPException(
            429, detail="Too many attempts. Please wait a while and try again."
        )


def parse_expiry(value):
    try:
        expiry = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry


def is_expired(value):
    return parse_expiry(value) <= datetime.now(UTC)


def db():
    path = Path(DB_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Raise it as a database error so callers' sqlite3.Error handlers cover it.
        raise sqlite3.OperationalError("Could not create database directory") from exc
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=20000")
    return con


def initialize_database():
    con = db()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_email_verified INTEGER NOT NULL DEFAULT 1,
                company_name TEXT,
                full_name TEXT
            )
            """
        )
        # The users table is shared with other services, so older databases
        # may be missing columns this API relies on.
        added_columns = {
            "is_email_verified": "INTEGER NOT NULL DEFAULT 1",
            "company_name": "TEXT",
            "full_name": "TEXT",
            "verification_token_hash": "TEXT",
            "verification_token_expires_at": "TEXT",
            # Set when the user deactivates their own account (see below).
            "deactivated_at": "TEXT",
            "deletion_warning_sent_at": "TEXT",
            # Set by the Login API when the password is changed or reset:
            # tokens issued before it (Unix seconds) no longer work anywhere.
            "sessions_valid_after": "INTEGER",
        }
        existing = {row["name"] for row in con.execute("PRAGMA table_info(users)")}
        for name, definition in added_columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                hashed_password TEXT NOT NULL,
                verification_token_hash TEXT NOT NULL,
                verification_token_expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        con.execute(
            "UPDATE users SET is_email_verified=1 "
            "WHERE is_email_verified=0 AND verification_token_hash IS NULL"
        )
        con.commit()
    finally:
        con.close()


@asynccontextmanager
async def lifespan(app):
    initialize_database()
    # Warns about and deletes accounts that stayed deactivated too long
    # (run_account_jobs_regularly is defined with the deactivation code below).
    account_jobs = asyncio.create_task(run_account_jobs_regularly())
    try:
        yield
    finally:
        account_jobs.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await account_jobs


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

# Web pages allowed to call this API from a browser, comma-separated
# (for example http://129.151.181.87:8009). Set in compose.yaml.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logging.getLogger(__name__).warning("CORS_ORIGINS is not set: browsers on other sites cannot call this API.")

app = FastAPI(**API_DOCS, title="Signup and Email Confirmation API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Signup and Email Confirmation API is running",
        "database": "SQLite",
    }


@app.get("/health")
def health():
    con = None
    try:
        con = db()
        con.execute("SELECT 1").fetchone()
        return {"status": "healthy", "database": "connected"}
    except sqlite3.Error:
        logger.exception("Health check could not reach the database")
        raise HTTPException(status_code=503, detail="Database connection failed")
    finally:
        if con:
            con.close()


def create_verification_token():
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_MINUTES)
    return raw_token, token_hash, expires_at.isoformat()


def verification_url(raw_token):
    if not EMAIL_CONFIRMATION_URL:
        raise RuntimeError("EMAIL_CONFIRMATION_URL is not configured")
    base = EMAIL_CONFIRMATION_URL.rstrip("/")
    parts = urlsplit(base)
    if parts.path.endswith("/verify.html"):
        page = base
    else:
        # Not a verify page URL: use the signup frontend's verify page on the
        # same host.
        host = parts.hostname
        if host and ":" in host:
            host = "[" + host + "]"
        page = parts.scheme + "://" + host + ":8008/verify.html"
    return page + "?token=" + quote(raw_token)


def send_email(to, subject, heading, body, button, url, footer):
    settings = {
        "SMTP_HOST": SMTP_HOST,
        "SMTP_USERNAME": SMTP_USERNAME,
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "EMAIL_FROM": EMAIL_FROM,
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise RuntimeError("Email settings missing: " + ", ".join(missing))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = to
    message.set_content(f"{heading}\n\n{body}\n\n{footer}")
    message.add_alternative(
        "<html><body>"
        f"<h2>{html.escape(heading)}</h2>"
        f"<p>{html.escape(body)}</p>"
        f'<p><a href="{html.escape(url, quote=True)}">{html.escape(button)}</a></p>'
        f"<small>{html.escape(footer)}</small>"
        "</body></html>",
        subtype="html",
    )

    context = ssl.create_default_context()
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, timeout=15, context=context
        ) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)


def send_verification(to, raw_token):
    send_email(
        to,
        subject="Verify your Tender Scrapper account",
        heading="Verify your email address",
        body=(
            "Please verify your email address to finish creating your account. "
            f"This link expires in {TOKEN_MINUTES} minutes."
        ),
        button="Verify My Email",
        url=verification_url(raw_token),
        footer="If you did not register, ignore this email.",
    )


def result_page(title, message, ok=True):
    color = "#16a34a" if ok else "#dc2626"
    return HTMLResponse(
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title></head>"
        '<body style="font-family:Arial;background:#f1f5f9;display:grid;'
        'place-items:center;min-height:100vh">'
        '<main style="background:white;padding:40px;border-radius:16px;'
        'max-width:520px;text-align:center">'
        f'<h2 style="color:{color}">Tender Scrapper</h2>'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>"
        "</main></body></html>"
    )


@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, http_request: Request):
    company = payload.company_name.strip()
    email = payload.email.strip().lower()
    password = payload.password
    if not company:
        raise HTTPException(400, detail="Enter a valid company name.")
    if not business_email(email):
        raise HTTPException(400, detail="Please use a business email address.")
    error = password_error(password)
    if error:
        raise HTTPException(400, detail=error)
    enforce_rate_limit("signup", http_request, email)

    con = None
    try:
        con = db()
        if con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(
                409, detail="An account with this email already exists."
            )
        pending = con.execute(
            "SELECT verification_token_expires_at FROM pending_registrations "
            "WHERE email=?",
            (email,),
        ).fetchone()
        if pending and not is_expired(pending["verification_token_expires_at"]):
            raise HTTPException(
                409,
                detail=(
                    "A verification email was already sent to this address. "
                    "Check your inbox or request a new link."
                ),
            )

        hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        raw_token, token_hash, expires_at = create_verification_token()
        con.execute(
            """
            INSERT INTO pending_registrations (
                email, company_name, hashed_password,
                verification_token_hash, verification_token_expires_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                company_name = excluded.company_name,
                hashed_password = excluded.hashed_password,
                verification_token_hash = excluded.verification_token_hash,
                verification_token_expires_at = excluded.verification_token_expires_at
            """,
            (email, company, hashed_password, token_hash, expires_at),
        )
        con.commit()

        try:
            send_verification(email, raw_token)
        except Exception as exc:
            logger.exception("Verification email failed for signup")
            con.execute("DELETE FROM pending_registrations WHERE email=?", (email,))
            con.commit()
            raise HTTPException(503, detail=EMAIL_SEND_ERROR) from exc

        return {
            "message": (
                "Verification email sent. "
                "Please check your email to complete registration."
            ),
            "email": email,
            "account_created": False,
            "email_verification_required": True,
        }
    except HTTPException:
        if con:
            con.rollback()
        raise
    except sqlite3.Error:
        logger.exception("Database error during signup")
        if con:
            con.rollback()
        raise HTTPException(500, detail="Database error while creating account")
    finally:
        if con:
            con.close()


@app.get("/email/verify", response_class=HTMLResponse)
def verify_email(token: str = Query(..., min_length=20)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    con = None
    try:
        con = db()
        con.execute("BEGIN IMMEDIATE")
        pending = con.execute(
            "SELECT * FROM pending_registrations WHERE verification_token_hash=?",
            (token_hash,),
        ).fetchone()
        if not pending:
            con.rollback()
            return result_page(
                "Verification failed",
                "This link is invalid or has already been used.",
                ok=False,
            )
        if is_expired(pending["verification_token_expires_at"]):
            con.rollback()
            return result_page(
                "Verification link expired",
                "This verification link has expired. Request a new one below.",
                ok=False,
            )

        con.execute(
            "INSERT INTO users (username, company_name, email, hashed_password, "
            "is_active, is_email_verified) VALUES (?, ?, ?, ?, 1, 1)",
            (
                pending["email"],
                pending["company_name"],
                pending["email"],
                pending["hashed_password"],
            ),
        )
        con.execute("DELETE FROM pending_registrations WHERE id=?", (pending["id"],))
        con.commit()

        try:
            send_email(
                pending["email"],
                subject="Your Tender Scrapper account is ready",
                heading="Your account is ready",
                body="Your email has been verified and your account has been created.",
                button="Open Tender Scrapper",
                url=LOGIN_URL,
                footer="Thank you for joining Tender Scrapper.",
            )
        except Exception:
            # The account already exists, so a failed welcome email must not
            # turn a successful verification into an error page.
            logger.warning("Welcome email could not be sent", exc_info=True)
        return result_page(
            "Email verified successfully",
            "Your Tender Scrapper account has been created.",
        )
    except sqlite3.IntegrityError:
        if con:
            con.rollback()
        return result_page(
            "Account already exists",
            "An account with this email already exists. You can log in.",
        )
    except sqlite3.Error:
        logger.exception("Database error during email verification")
        if con:
            con.rollback()
        raise HTTPException(503, detail="Verification could not be completed.")
    finally:
        if con:
            con.close()


@app.post("/email/resend-verification")
def resend_verification(payload: ResendRequest, http_request: Request):
    email = payload.email.strip().lower()
    if not valid_email(email):
        raise HTTPException(400, detail="Invalid email address.")
    enforce_rate_limit("resend", http_request, email)

    con = None
    try:
        con = db()
        user = con.execute(
            "SELECT is_email_verified FROM users WHERE email=?", (email,)
        ).fetchone()
        if user:
            return {
                "message": "An account with this email already exists.",
                "email_verified": bool(user["is_email_verified"]),
            }
        pending = con.execute(
            "SELECT id FROM pending_registrations WHERE email=?", (email,)
        ).fetchone()
        if not pending:
            raise HTTPException(
                404, detail="No pending registration was found for this email address."
            )

        raw_token, token_hash, expires_at = create_verification_token()
        con.execute(
            "UPDATE pending_registrations "
            "SET verification_token_hash=?, verification_token_expires_at=? "
            "WHERE id=?",
            (token_hash, expires_at, pending["id"]),
        )
        con.commit()

        try:
            send_verification(email, raw_token)
        except Exception as exc:
            logger.exception("Verification email failed for resend")
            raise HTTPException(503, detail=EMAIL_SEND_ERROR) from exc

        return {
            "message": "A new verification email has been sent.",
            "email": email,
            "email_verification_required": True,
        }
    except sqlite3.Error:
        logger.exception("Database error while resending verification")
        if con:
            con.rollback()
        raise HTTPException(503, detail="Could not resend the verification email.")
    finally:
        if con:
            con.close()


def issued_before_cutoff(claims: dict, cutoff) -> bool:
    """True for a token issued before the user's last password change or reset.
    Tokens without an issue time predate this check and only fail once there is a cut-off."""
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


def current_user(token: str = Depends(oauth2_scheme)):
    if not JWT_SECRET:
        raise HTTPException(503, detail="JWT_SECRET is not configured")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.InvalidTokenError:
        claims = {}
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(401, detail="Invalid or expired access token")

    con = None
    try:
        con = db()
        user = con.execute(
            "SELECT id, username, company_name, email, full_name, is_active, "
            "is_email_verified, created_at, sessions_valid_after FROM users WHERE username=?",
            (subject,),
        ).fetchone()
        signed_out = token_signed_out(con, claims)
    except sqlite3.Error:
        logger.exception("Database error while loading the signed-in user")
        raise HTTPException(503, detail="Could not load user account")
    finally:
        if con:
            con.close()
    if not user or not user["is_active"]:
        raise HTTPException(401, detail="Invalid or inactive user")
    if issued_before_cutoff(claims, user["sessions_valid_after"]) or signed_out:
        raise HTTPException(401, detail="Your session has ended. Please sign in again.")
    if not user["is_email_verified"]:
        raise HTTPException(403, detail="Please verify your email before continuing")
    return dict(user)


@app.get("/user/profile")
def get_user_profile(user=Depends(current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"] or user["company_name"] or user["username"],
        "email": user["email"],
    }


def notify(username, event_type):
    """Tell the notifications API about an account event.

    Failures are logged and never affect the caller.
    """
    if not NOTIFICATIONS_API_URL or not INTERNAL_API_KEY:
        return
    request = urllib.request.Request(
        NOTIFICATIONS_API_URL + "/internal/notifications",
        data=json.dumps({"username": username, "type": event_type}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Key": INTERNAL_API_KEY,
        },
    )
    try:
        urllib.request.urlopen(request, timeout=3).close()
    except Exception:
        logger.warning("Could not send %s notification", event_type, exc_info=True)


@app.put("/user/profile")
def update_user_profile(
    payload: ProfileUpdate,
    background_tasks: BackgroundTasks,
    user=Depends(current_user),
):
    name = payload.full_name.strip()
    if len(name) < 2:
        raise HTTPException(422, detail="Full name must contain at least 2 characters")

    con = None
    try:
        con = db()
        con.execute("UPDATE users SET full_name=? WHERE id=?", (name, user["id"]))
        row = con.execute(
            "SELECT id, username, full_name, email FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
        con.commit()
        background_tasks.add_task(notify, user["username"], "profile_updated")
        return dict(row)
    except sqlite3.Error:
        logger.exception("Database error while saving user profile")
        if con:
            con.rollback()
        raise HTTPException(503, detail="Could not save user profile")
    finally:
        if con:
            con.close()


# ---------------------------------------------------------------------------
# Account deletion
#
# DELETE /user/account removes everything that belongs to the signed-in user:
# first the documents, AI profile and chat history held by the AI agent (which
# also clears the AI service), then every row in the shared database, in one
# transaction. If the agent cannot confirm its part, nothing in the shared
# database is touched and the user can simply try again.
# ---------------------------------------------------------------------------
AGENT_API_URL = (
    os.getenv("AGENT_API_URL", "").strip().rstrip("/") or "http://tender-agent-api:9000"
)
# Shared with the AI agent (tender-ai-agent); sent as X-Internal-Key.
ACCOUNT_DELETION_KEY = os.getenv("ACCOUNT_DELETION_KEY", "").strip()
ACCOUNT_DELETION_UNAVAILABLE = (
    "Your account could not be deleted right now and nothing was removed. "
    "Please try again later."
)
WRONG_PASSWORD_ERROR = "That password is not correct."


class PasswordConfirmation(BaseModel):
    password: str = Field(..., max_length=256)


def password_matches(password, hashed_password):
    try:
        # Same 72-byte limit as the login API.
        return bcrypt.checkpw(
            password.encode("utf-8")[:MAX_PASSWORD_BYTES], hashed_password.encode()
        )
    except (ValueError, TypeError):
        return False


def require_password(user, password, unavailable_message):
    """Answer 403 unless password is the user's current password."""
    con = None
    try:
        con = db()
        row = con.execute(
            "SELECT hashed_password FROM users WHERE id=?", (user["id"],)
        ).fetchone()
    except sqlite3.Error:
        logger.exception("Database error while checking the password")
        raise HTTPException(503, detail=unavailable_message)
    finally:
        if con:
            con.close()
    if not row or not password_matches(password, row["hashed_password"]):
        raise HTTPException(403, detail=WRONG_PASSWORD_ERROR)


def delete_agent_data(email):
    """Ask the AI agent to delete this user's documents, AI profile and chat
    history. Raises if the agent does not confirm."""
    if not ACCOUNT_DELETION_KEY:
        raise RuntimeError("ACCOUNT_DELETION_KEY is not configured")
    request = urllib.request.Request(
        AGENT_API_URL + "/internal/accounts/delete",
        data=json.dumps({"email": email}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Key": ACCOUNT_DELETION_KEY,
        },
    )
    # urlopen raises for any non-2xx answer.
    urllib.request.urlopen(request, timeout=30).close()


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def delete_user_rows(con, user):
    """Delete every row in the shared database that belongs to the user.
    Runs inside the caller's transaction. Returns {table: rows deleted}."""
    tables = {
        row["name"]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    deleted = {}

    def run(table, sql, params):
        count = con.execute(sql, params).rowcount
        if count > 0:
            deleted[table] = deleted.get(table, 0) + count

    # Application history is linked through the application, not the user.
    if {"tender_application_history", "tender_applications"} <= tables:
        run(
            "tender_application_history",
            "DELETE FROM tender_application_history WHERE application_id IN "
            "(SELECT id FROM tender_applications WHERE user_id=?)",
            (user["id"],),
        )
    # Every other service keys its rows by users.id in a user_id column
    # (profiles, documents, alerts, saved tenders, applications, notifications).
    for table in sorted(tables - {"users"}):
        columns = {row["name"] for row in con.execute(f"PRAGMA table_info({quoted(table)})")}
        if "user_id" in columns:
            run(table, f"DELETE FROM {quoted(table)} WHERE user_id=?", (user["id"],))
    # The Login API keys its emailed codes by username.
    for table in ("password_reset_codes", "reactivation_codes"):
        if table in tables:
            run(table, f"DELETE FROM {table} WHERE username=?", (user["username"],))
    if "pending_registrations" in tables:
        run(
            "pending_registrations",
            "DELETE FROM pending_registrations WHERE email=?",
            (user["email"],),
        )
    run("users", "DELETE FROM users WHERE id=?", (user["id"],))
    return deleted


def send_deletion_confirmation(to):
    send_email(
        to,
        subject="Your Tender Scrapper account has been deleted",
        heading="Your account has been deleted",
        body=(
            "Your Tender Scrapper account and the information linked to it, "
            "including your business documents, have been deleted."
        ),
        button="Visit Tender Scrapper",
        url=LOGIN_URL,
        footer=(
            "If you did not ask for this, reply to this email or contact us "
            "straight away."
        ),
    )


def erase_account(user, still_deactivated_since=None):
    """Delete the user's data at the AI agent, then every row in the shared
    database in one transaction. Raises if either part fails; when the agent
    fails, the shared database is not touched.

    With still_deactivated_since, the shared-database part only goes ahead if
    the account is still deactivated since that moment (the owner may have
    signed back in meanwhile); returns None if it was not."""
    try:
        delete_agent_data(user["email"])
    except Exception:
        logger.exception("The AI agent did not confirm deleting account data")
        raise

    con = None
    try:
        con = db()
        con.execute("BEGIN IMMEDIATE")
        if still_deactivated_since is not None:
            still = con.execute(
                "SELECT 1 FROM users WHERE id=? AND is_active=0 AND deactivated_at=?",
                (user["id"], still_deactivated_since),
            ).fetchone()
            if still is None:
                con.rollback()
                return None
        deleted = delete_user_rows(con, user)
        con.commit()
    except sqlite3.Error:
        logger.exception("Database error while deleting an account")
        if con:
            con.rollback()
        raise
    finally:
        if con:
            con.close()
    # Log the account number and row counts only, never the email address.
    logger.info("Deleted account %s: %s", user["id"], deleted)
    return deleted


@app.delete("/user/account")
def delete_account(
    payload: PasswordConfirmation, http_request: Request, user=Depends(current_user)
):
    enforce_rate_limit("delete-account", http_request, user["email"])
    require_password(user, payload.password, ACCOUNT_DELETION_UNAVAILABLE)

    try:
        erase_account(user)
    except Exception as exc:
        raise HTTPException(503, detail=ACCOUNT_DELETION_UNAVAILABLE) from exc

    try:
        send_deletion_confirmation(user["email"])
    except Exception:
        logger.warning("Account deletion email could not be sent", exc_info=True)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Account deactivation
#
# POST /user/deactivate switches the account off without deleting anything.
# is_active = 0 makes every service refuse it straight away, and
# deactivated_at records that the owner chose this. Signing in again on the
# login page and entering a code emailed to the user reactivates it (the
# Login API's /reactivate/send-code and /reactivate clear both).
#
# An account that stays deactivated for DEACTIVATED_ACCOUNT_RETENTION_DAYS is
# deleted exactly like DELETE /user/account. Its owner is emailed
# DELETION_WARNING_DAYS before. Both checks run at startup and then every
# ACCOUNT_JOBS_INTERVAL_SECONDS.
# ---------------------------------------------------------------------------
DEACTIVATED_ACCOUNT_RETENTION_DAYS = int(
    os.getenv("DEACTIVATED_ACCOUNT_RETENTION_DAYS") or "365"
)
DELETION_WARNING_DAYS = int(os.getenv("DELETION_WARNING_DAYS") or "30")
ACCOUNT_JOBS_INTERVAL_SECONDS = int(os.getenv("ACCOUNT_JOBS_INTERVAL_SECONDS") or "3600")
ACCOUNT_DEACTIVATION_UNAVAILABLE = (
    "Your account could not be deactivated right now. Please try again later."
)


def deletion_due(deactivated_at):
    """When a deactivated account is deleted, or None if the time is unreadable."""
    try:
        moment = datetime.fromisoformat(deactivated_at)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment + timedelta(days=DEACTIVATED_ACCOUNT_RETENTION_DAYS)


def long_date(moment):
    return f"{moment.day} {moment:%B %Y}"


def send_deactivation_confirmation(to, delete_on):
    send_email(
        to,
        subject="Your Tender Scrapper account has been deactivated",
        heading="Your account is deactivated",
        body=(
            "You have been signed out and we won't send you tender emails. "
            "Everything you saved is kept. To reactivate your account, sign in again "
            f"before {long_date(delete_on)} and enter the code we email you. If you "
            "don't, your account and the "
            "information linked to it, including your business documents, will be "
            "deleted on that date."
        ),
        button="Sign in to reactivate",
        url=LOGIN_URL,
        footer=(
            "If you did not deactivate your account, sign in to reactivate it and "
            "change your password straight away."
        ),
    )


def send_deletion_warning(to, delete_on):
    send_email(
        to,
        subject=f"Your Tender Scrapper account will be deleted on {long_date(delete_on)}",
        heading="Your account will be deleted soon",
        body=(
            f"Your Tender Scrapper account is deactivated. On {long_date(delete_on)} "
            "we will delete it and the information linked to it, including your "
            "business documents. To keep your account, sign in again before then."
        ),
        button="Sign in to keep my account",
        url=LOGIN_URL,
        footer="If you are happy for your account to be deleted, you don't need to do anything.",
    )


@app.post("/user/deactivate")
def deactivate_account(
    payload: PasswordConfirmation, http_request: Request, user=Depends(current_user)
):
    enforce_rate_limit("deactivate-account", http_request, user["email"])
    require_password(user, payload.password, ACCOUNT_DEACTIVATION_UNAVAILABLE)

    deactivated_at = datetime.now(UTC).isoformat()
    con = None
    try:
        con = db()
        con.execute(
            "UPDATE users SET is_active=0, deactivated_at=?, deletion_warning_sent_at=NULL "
            "WHERE id=?",
            (deactivated_at, user["id"]),
        )
        con.commit()
    except sqlite3.Error as exc:
        logger.exception("Database error while deactivating an account")
        if con:
            con.rollback()
        raise HTTPException(503, detail=ACCOUNT_DEACTIVATION_UNAVAILABLE) from exc
    finally:
        if con:
            con.close()
    logger.info("Deactivated account %s", user["id"])

    delete_on = deletion_due(deactivated_at)
    try:
        send_deactivation_confirmation(user["email"], delete_on)
    except Exception:
        logger.warning("Account deactivation email could not be sent", exc_info=True)
    return {"deactivated": True, "delete_on": delete_on.date().isoformat()}


def deactivated_accounts():
    con = db()
    try:
        return con.execute(
            "SELECT id, username, email, deactivated_at, deletion_warning_sent_at "
            "FROM users WHERE is_active=0 AND deactivated_at IS NOT NULL"
        ).fetchall()
    finally:
        con.close()


def delete_expired_deactivated_accounts(now):
    """Delete accounts deactivated for DEACTIVATED_ACCOUNT_RETENTION_DAYS.
    One that fails is tried again next time. Returns how many were deleted."""
    deleted = 0
    for row in deactivated_accounts():
        due = deletion_due(row["deactivated_at"])
        if due is None or due > now:
            continue
        try:
            if erase_account(dict(row), still_deactivated_since=row["deactivated_at"]) is None:
                continue
        except Exception:
            logger.warning("Deactivated account %s could not be deleted yet", row["id"])
            continue
        deleted += 1
        try:
            send_deletion_confirmation(row["email"])
        except Exception:
            logger.warning("Account deletion email could not be sent", exc_info=True)
    return deleted


def warn_before_deletion(now):
    """Email owners whose deactivated account is deleted within
    DELETION_WARNING_DAYS. Returns how many were warned."""
    warned = 0
    for row in deactivated_accounts():
        due = deletion_due(row["deactivated_at"])
        if row["deletion_warning_sent_at"] or due is None:
            continue
        if not now < due <= now + timedelta(days=DELETION_WARNING_DAYS):
            continue
        try:
            send_deletion_warning(row["email"], due)
        except Exception:
            logger.warning("Deletion warning for account %s could not be sent", row["id"], exc_info=True)
            continue
        con = db()
        try:
            con.execute(
                "UPDATE users SET deletion_warning_sent_at=? WHERE id=? AND deactivated_at=?",
                (now.isoformat(), row["id"], row["deactivated_at"]),
            )
            con.commit()
        finally:
            con.close()
        warned += 1
    return warned


def run_account_jobs(now=None):
    now = now or datetime.now(UTC)
    # Delete first, so nobody is warned about a deletion happening this minute.
    delete_expired_deactivated_accounts(now)
    warn_before_deletion(now)


def run_account_jobs_safely():
    try:
        run_account_jobs()
    except Exception:
        logger.exception("Deactivated-account checks failed")


async def run_account_jobs_regularly():
    while True:
        await asyncio.to_thread(run_account_jobs_safely)
        await asyncio.sleep(ACCOUNT_JOBS_INTERVAL_SECONDS)
