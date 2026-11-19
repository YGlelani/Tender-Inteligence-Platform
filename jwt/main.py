import asyncio
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import httpx
import jwt
import bcrypt
import sqlite3
from datetime import datetime, timedelta, UTC
from fastapi import BackgroundTasks, FastAPI, Depends, Form, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Loads variables from your .env file
load_dotenv()

logger = logging.getLogger("jwt-api")

# Web pages allowed to call this API from the browser, comma-separated
# (for example http://129.151.181.87:8009). Set in compose.yml.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logger.warning("CORS_ORIGINS is not set: browsers on other origins cannot call the Login API.")

@asynccontextmanager
async def lifespan(app):
    # Expired password-reset codes are deleted at startup and then every hour
    # (purge_reset_codes_* are defined with the reset-code code further down).
    purge_reset_codes_safely()
    cleanup = asyncio.create_task(purge_reset_codes_regularly())
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup


# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(**API_DOCS, title="JWT Authentication API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # sign-in uses a bearer token, not cookies
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log unexpected errors and return a generic message.

    FastAPI's default 500 response is generated outside the CORS middleware, so
    the browser would report a misleading CORS error. Allowed origins therefore
    get the CORS header here too. The error details stay in the server log.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    headers = {}
    origin = request.headers.get("origin")
    if origin and origin in CORS_ORIGINS:
        headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again later."},
        headers=headers,
    )

# Security settings: the signing secret must come from the environment.
# Never fall back to a built-in value; anyone could forge tokens with it.
SECRET_KEY = (os.getenv("JWT_SECRET") or "").strip()
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET is not set; the Login API will not start without it.")
ALGORITHM = "HS256"
def get_token_expiry_minutes() -> int:
    """Read the configurable JWT lifetime, expressed in hours."""
    raw_hours = os.getenv("SESSION_TIMEOUT_HOURS", "2").strip()
    try:
        hours = float(raw_hours)
    except ValueError as exc:
        raise RuntimeError("SESSION_TIMEOUT_HOURS must be a positive number of hours") from exc
    if hours <= 0:
        raise RuntimeError("SESSION_TIMEOUT_HOURS must be greater than zero")
    return max(1, int(hours * 60))


ACCESS_TOKEN_EXPIRE_MINUTES = get_token_expiry_minutes()

# Shared SQLite database used by the tender APIs.
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")


def get_db_connection():
    if not os.path.isfile(DATABASE_PATH):
        raise RuntimeError(f"SQLite database does not exist at {DATABASE_PATH}")
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

MAX_PASSWORD_BYTES = 72  # bcrypt only uses the first 72 bytes


# --- Sign-in attempt limits ---------------------------------------------------
# Failed sign-ins are counted per account and per IP address over a sliding
# window. Once either limit is reached, /login answers 429 until the window
# has passed. A successful sign-in clears the account's count.
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS") or "900")
LOGIN_MAX_FAILURES_PER_ACCOUNT = int(os.getenv("LOGIN_MAX_FAILURES_PER_ACCOUNT") or "5")
LOGIN_MAX_FAILURES_PER_IP = int(os.getenv("LOGIN_MAX_FAILURES_PER_IP") or "20")
_login_failures: dict[str, deque] = defaultdict(deque)
_login_lock = threading.Lock()


def _prune_login_failures(key: str, now: float) -> int:
    hits = _login_failures.get(key)
    if not hits:
        _login_failures.pop(key, None)
        return 0
    while hits and now - hits[0] > LOGIN_WINDOW_SECONDS:
        hits.popleft()
    if not hits:
        del _login_failures[key]
        return 0
    return len(hits)


def login_blocked(account: str, ip: str) -> bool:
    now = time.monotonic()
    with _login_lock:
        return (_prune_login_failures("account:" + account, now) >= LOGIN_MAX_FAILURES_PER_ACCOUNT
                or _prune_login_failures("ip:" + ip, now) >= LOGIN_MAX_FAILURES_PER_IP)


def record_login_failure(account: str, ip: str) -> None:
    now = time.monotonic()
    with _login_lock:
        if len(_login_failures) > 10_000:  # bound memory under a flood of random names
            for key in list(_login_failures):
                _prune_login_failures(key, now)
        _login_failures["account:" + account].append(now)
        _login_failures["ip:" + ip].append(now)


def clear_login_failures(account: str) -> None:
    with _login_lock:
        _login_failures.pop("account:" + account, None)


def create_access_token(data: dict):
    """Generates a JWT token with an expiration time."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": int(time.time()), "jti": secrets.token_urlsafe(16)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def incorrect_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


# --- Deactivated accounts -----------------------------------------------------
# Users can deactivate their own account in the Signup API, which sets
# is_active = 0 and deactivated_at. They come back by signing in again: after
# the correct password, /login answers 403, the sign-in page asks
# /reactivate/send-code to email a 6-digit code, and /reactivate checks it
# (see "Reactivation codes" below). An account switched off any other way
# (is_active = 0 without deactivated_at) is still treated as unknown.
ACCOUNT_DEACTIVATED_MESSAGE = (
    "This account is deactivated. You can reactivate it on the Tender Scrapper sign-in page."
)


def user_columns(conn) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(users)")}


def usable_account_condition(conn, alias: str = "") -> str:
    """SQL condition for accounts that may sign in or reset their password:
    active ones, and ones their owner deactivated (they come back by signing in)."""
    prefix = alias + "." if alias else ""
    if "deactivated_at" in user_columns(conn):
        return f"({prefix}is_active = 1 OR {prefix}deactivated_at IS NOT NULL)"
    return f"{prefix}is_active = 1"


def token_response(username: str) -> dict:
    return {
        "access_token": create_access_token(data={"sub": username}),
        "token_type": "bearer",
        "session_timeout_hours": ACCESS_TOKEN_EXPIRE_MINUTES / 60,
    }


@app.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """Verifies user credentials against the database and returns a JWT token."""
    user = check_credentials(request, form_data)
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ACCOUNT_DEACTIVATED_MESSAGE)
    return token_response(user["username"])


def check_credentials(request: Request, form_data: OAuth2PasswordRequestForm):
    """Check a username and password for /login and /reactivate.

    Returns the user's row (username, is_active, deactivated_at). Raises 429
    after too many failures, and the same generic 401 for an unknown account,
    an account switched off by someone else, or a wrong password.
    """
    conn = None
    cur = None
    account = form_data.username.strip().lower()
    ip = request.client.host if request.client else "unknown"

    # --- 0. Too many recent failures for this account or IP -> 429 ----------
    if login_blocked(account, ip):
        minutes = max(1, LOGIN_WINDOW_SECONDS // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Please wait {minutes} minutes and try again.",
            headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
        )

    # --- 1. Fetch the user (only DB errors are expected here) ---------------
    try:
        conn = get_db_connection()
        deactivated_at = "deactivated_at" if "deactivated_at" in user_columns(conn) else "NULL"
        cur = conn.cursor()
        cur.execute(
            f"SELECT username, hashed_password, is_active, {deactivated_at} AS deactivated_at "
            "FROM users WHERE username = ?;",
            (form_data.username,),
        )
        user = cur.fetchone()
    except (sqlite3.Error, RuntimeError):
        logger.exception("Database error during sign-in")
        raise HTTPException(status_code=503, detail="Sign-in is unavailable right now. Please try again later.")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    # --- 2. Unknown user, account switched off by someone else, or missing
    #        hash -> generic 401 ------------------------------------------------
    usable = user is not None and (user["is_active"] or user["deactivated_at"] is not None)
    if not usable or user["hashed_password"] is None:
        record_login_failure(account, ip)
        raise incorrect_login()

    # --- 3. Normalise the stored hash --------------------------------------
    # SQLite stores the bcrypt hash as text; bcrypt.checkpw needs bytes.
    stored = user["hashed_password"]
    if isinstance(stored, memoryview):
        stored = stored.tobytes()
    if isinstance(stored, str):
        stored = stored.encode("utf-8")

    # --- 4. Verify the password --------------------------------------------
    # bcrypt only uses the first 72 bytes; newer bcrypt versions raise instead
    # of truncating, so trim first (signup never accepts longer passwords).
    try:
        password_ok = bcrypt.checkpw(form_data.password.encode("utf-8")[:MAX_PASSWORD_BYTES], stored)
    except ValueError:
        # The stored value is not a valid bcrypt hash: a data problem, not a
        # wrong password. Details go to the log, never to the caller.
        logger.error("Stored password hash for an account is not a valid bcrypt hash")
        raise HTTPException(status_code=500, detail="Sign-in failed because of a problem on our side. Please try again later.")

    if not password_ok:
        record_login_failure(account, ip)
        raise incorrect_login()

    clear_login_failures(account)
    return user

@app.get("/")
async def root():
    return {"message": "JWT API is running. Go to /docs to test the login."}

@app.get("/health")
async def health_check():
    """Endpoint for Docker and GitHub Actions to verify the API is running."""
    try:
        conn = get_db_connection()
        conn.execute("SELECT username FROM users LIMIT 1")
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception:
        if "conn" in locals() and conn:
            conn.close()
        logger.exception("Health check could not reach the database")
        raise HTTPException(status_code=503, detail="Database connection failed")

def verify_access_token(token: str) -> dict:
    """Verify the token signature; it must name a user and carry an expiry."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Ending sign-ins ----------------------------------------------------------
# Changing or resetting a password ends every existing sign-in. The user's row
# gets sessions_valid_after (Unix seconds); a token issued before that time is
# refused here and by every other service that reads the shared database.
# Tokens from before this change carry no issue time ("iat"): they keep working
# until they expire, unless the user has a cut-off, which they then fail.
SESSION_CUTOFF_COLUMN = "sessions_valid_after"


def issued_before_cutoff(claims: dict, cutoff) -> bool:
    if cutoff is None:
        return False
    issued_at = claims.get("iat")
    return not isinstance(issued_at, (int, float)) or issued_at < cutoff


def end_sessions(conn, username: str) -> None:
    """Every token issued before now stops working (the caller commits)."""
    if SESSION_CUTOFF_COLUMN not in user_columns(conn):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {SESSION_CUTOFF_COLUMN} INTEGER")
        except sqlite3.OperationalError:
            if SESSION_CUTOFF_COLUMN not in user_columns(conn):  # not just another service adding it first
                raise
    conn.execute(
        f"UPDATE users SET {SESSION_CUTOFF_COLUMN} = ? WHERE username = ?;", (int(time.time()), username)
    )


# --- Signing out -------------------------------------------------------------
# Signing out ends that one sign-in: the token's id ("jti") goes into
# revoked_tokens until the token would have expired anyway, and every service
# refuses it. Other devices stay signed in. Tokens from before ids were added
# cannot be listed; they simply expire.
def ensure_revoked_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL
        );"""
    )


def token_revoked(conn, claims: dict) -> bool:
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        return False
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revoked_tokens';").fetchone():
        return False
    return conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?;", (jti,)).fetchone() is not None


def session_is_current(claims: dict) -> bool:
    """The token's user still exists, is active, has not changed their password
    since, and has not signed out with this token."""
    username = claims.get("sub")
    if not isinstance(username, str):
        return False
    conn = None
    try:
        conn = get_db_connection()
        cutoff = SESSION_CUTOFF_COLUMN if SESSION_CUTOFF_COLUMN in user_columns(conn) else "NULL"
        row = conn.execute(
            f"SELECT {cutoff} AS cutoff FROM users WHERE username = ? AND is_active = 1;", (username,)
        ).fetchone()
        return (
            row is not None
            and not issued_before_cutoff(claims, row["cutoff"])
            and not token_revoked(conn, claims)
        )
    except (sqlite3.Error, RuntimeError):
        logger.exception("Database error while checking a token's user")
        raise HTTPException(status_code=503, detail="Sign-in is unavailable right now. Please try again later.")
    finally:
        if conn:
            conn.close()


def require_current_session(token: str) -> str:
    """Username of a valid token whose sign-in has not been ended."""
    claims = verify_access_token(token)
    if not session_is_current(claims):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has ended. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims["sub"]


@app.get("/protected-tenders")
async def get_protected_tenders(token: str = Depends(oauth2_scheme)):
    """Verify a token for other services (the AI agent uses this).

    Besides the signature and expiry, the user must still exist and be active,
    so a deactivated account stops working everywhere straight away, and the
    token must be newer than the user's last password change or reset.
    """
    username = require_current_session(token)
    return {
        "message": "If you are seeing this, you successfully passed the token!",
        "username": username,
    }


@app.post("/logout")
def logout(token: str = Depends(oauth2_scheme)):
    """End this sign-in. The browser also forgets the token; other devices stay signed in."""
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        return {"message": "You have signed out."}  # nothing left to end
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    jti = claims.get("jti")
    if isinstance(jti, str) and jti:
        conn = None
        try:
            conn = get_db_connection()
            ensure_revoked_table(conn)
            conn.execute(
                "INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?);", (jti, int(claims["exp"]))
            )
            conn.commit()
        except (sqlite3.Error, RuntimeError):
            logger.exception("Could not record a sign-out")
            raise HTTPException(status_code=503, detail="Could not sign out on the server. Please try again.")
        finally:
            if conn:
                conn.close()
    return {"message": "You have signed out."}


# --- Change password ---------------------------------------------------------

NOTIFICATIONS_API_URL = os.getenv("NOTIFICATIONS_API_URL", "").strip().rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "").strip()


class PasswordChange(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)


def password_error(password: str):
    """Same rules as signup."""
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


def notify_password_changed(username: str):
    """Tell the notifications API. Failures never affect the password change."""
    if not NOTIFICATIONS_API_URL or not INTERNAL_API_KEY:
        return
    try:
        httpx.post(
            f"{NOTIFICATIONS_API_URL}/internal/notifications",
            json={"username": username, "type": "password_changed"},
            headers={"X-Internal-Key": INTERNAL_API_KEY},
            timeout=3,
        ).raise_for_status()
    except Exception:
        logger.warning("Could not send password_changed notification", exc_info=True)


@app.post("/change-password")
def change_password(
    payload: PasswordChange,
    background_tasks: BackgroundTasks,
    token: str = Depends(oauth2_scheme),
):
    """Change the logged-in user's password after checking the current one.

    Every other sign-in ends; this browser gets a new token in the response.
    """
    username = require_current_session(token)

    conn = None
    try:
        conn = get_db_connection()
        user = conn.execute(
            "SELECT hashed_password FROM users WHERE username = ? AND is_active = 1;",
            (username,),
        ).fetchone()
        if not user or not user["hashed_password"]:
            raise HTTPException(status_code=401, detail="User is not active or no longer exists.")

        stored = user["hashed_password"]
        if isinstance(stored, str):
            stored = stored.encode("utf-8")
        try:
            current_ok = bcrypt.checkpw(payload.current_password.encode("utf-8")[:MAX_PASSWORD_BYTES], stored)
        except ValueError:
            current_ok = False
        if not current_ok:
            raise HTTPException(status_code=400, detail="Your current password is incorrect.")

        error = password_error(payload.new_password)
        if error:
            raise HTTPException(status_code=400, detail=error)
        if payload.new_password == payload.current_password:
            raise HTTPException(
                status_code=400,
                detail="Your new password must be different from your current password.",
            )

        hashed = bcrypt.hashpw(payload.new_password.encode("utf-8"), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET hashed_password = ? WHERE username = ?;", (hashed, username))
        end_sessions(conn, username)
        conn.commit()
    except (sqlite3.Error, RuntimeError):
        raise HTTPException(status_code=503, detail="Could not change password. Please try again.")
    finally:
        if conn:
            conn.close()

    background_tasks.add_task(notify_password_changed, username)
    return {
        "message": "Your password has been changed. You have been signed out on your other devices.",
        **token_response(username),
    }

# --- Forgot password (6-digit code by email) --------------------------------

import hashlib
import hmac
import secrets
import smtplib
import ssl
from email.message import EmailMessage

RESET_CODE_MINUTES = int(os.getenv("RESET_CODE_MINUTES") or "10")
RESET_MAX_ATTEMPTS = 5
RESET_RATE_WINDOW_SECONDS = 3600
RESET_RATE_PER_EMAIL = 3
RESET_RATE_PER_IP = 10
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = (os.getenv("SMTP_USE_TLS") or "true").lower() == "true"
FORGOT_MESSAGE = (
    "If an account exists for this email, we've sent a 6-digit code to it. "
    f"The code expires in {RESET_CODE_MINUTES} minutes."
)
INVALID_CODE_MESSAGE = "This code is invalid or has expired. Please request a new one."

_reset_attempts = defaultdict(deque)
_reset_lock = threading.Lock()


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., max_length=256)


def reset_rate_limited(key: str, limit: int) -> bool:
    now = time.monotonic()
    with _reset_lock:
        hits = _reset_attempts[key]
        while hits and now - hits[0] > RESET_RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False


def hash_reset_code(username: str, code: str) -> str:
    """Keyed hash, so a stored value is useless without the server secret."""
    return hmac.new(SECRET_KEY.encode(), f"{username}:{code}".encode(), hashlib.sha256).hexdigest()


def ensure_reset_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS password_reset_codes (
               username TEXT PRIMARY KEY,
               code_hash TEXT NOT NULL,
               expires_at TEXT NOT NULL,
               attempts INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL
           )"""
    )


# Codes nobody used would otherwise stay in the table for good.
RESET_CODE_CLEANUP_INTERVAL_SECONDS = int(os.getenv("RESET_CODE_CLEANUP_INTERVAL_SECONDS") or "3600")


def _is_past(value: str, now: datetime) -> bool:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return True  # unreadable: treat as expired
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment <= now


def _purge_expired_codes(table: str, ensure_table) -> int:
    now = datetime.now(UTC)
    conn = get_db_connection()
    try:
        ensure_table(conn)
        stale = [
            (row["username"],)
            for row in conn.execute(f"SELECT username, expires_at FROM {table}")
            if _is_past(row["expires_at"], now)
        ]
        if stale:
            conn.executemany(f"DELETE FROM {table} WHERE username = ?", stale)
            conn.commit()
            logger.info("Deleted %d expired codes from %s", len(stale), table)
        return len(stale)
    finally:
        conn.close()


def purge_expired_reset_codes() -> int:
    """Delete password-reset codes that have expired. Returns how many were deleted."""
    return _purge_expired_codes("password_reset_codes", ensure_reset_table)


def purge_expired_reactivation_codes() -> int:
    """Delete account reactivation codes that have expired. Returns how many were deleted."""
    return _purge_expired_codes("reactivation_codes", ensure_reactivation_table)


def purge_expired_revoked_tokens() -> int:
    """Forget signed-out tokens once they have expired. Also creates the table at startup."""
    conn = get_db_connection()
    try:
        ensure_revoked_table(conn)
        deleted = conn.execute("DELETE FROM revoked_tokens WHERE expires_at <= ?;", (int(time.time()),)).rowcount
        conn.commit()
        if deleted:
            logger.info("Forgot %d expired signed-out tokens", deleted)
        return deleted
    finally:
        conn.close()


def purge_reset_codes_safely() -> None:
    """Runs at startup and then every RESET_CODE_CLEANUP_INTERVAL_SECONDS."""
    for purge, what in (
        (purge_expired_reset_codes, "password-reset codes"),
        (purge_expired_reactivation_codes, "reactivation codes"),
        (purge_expired_revoked_tokens, "signed-out tokens"),
    ):
        try:
            purge()
        except Exception:
            logger.exception("Could not delete expired %s", what)


async def purge_reset_codes_regularly() -> None:
    while True:
        await asyncio.sleep(RESET_CODE_CLEANUP_INTERVAL_SECONDS)
        await asyncio.to_thread(purge_reset_codes_safely)


def send_email(to: str, subject: str, text: str, html_body: str):
    missing = [k for k, v in {"SMTP_HOST": SMTP_HOST, "SMTP_USERNAME": SMTP_USERNAME,
                              "SMTP_PASSWORD": SMTP_PASSWORD, "EMAIL_FROM": EMAIL_FROM}.items() if not v]
    if missing:
        raise RuntimeError("Email settings missing: " + ", ".join(missing))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, EMAIL_FROM, to
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15, context=context) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)


def send_reset_code(email: str, code: str):
    text = (
        f"Your Tender Scrapper password reset code is {code}.\n\n"
        f"It expires in {RESET_CODE_MINUTES} minutes. If you didn't ask to reset your password, "
        "you can ignore this email; your password stays the same."
    )
    html_body = (
        "<html><body><h2>Reset your password</h2><p>Your password reset code is:</p>"
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:6px">{code}</p>'
        f"<p>It expires in {RESET_CODE_MINUTES} minutes.</p>"
        "<small>If you didn't ask to reset your password, you can ignore this email; "
        "your password stays the same.</small></body></html>"
    )
    try:
        send_email(email, "Your Tender Scrapper password reset code", text, html_body)
    except Exception:
        logger.exception("Password reset email failed")


@app.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, background_tasks: BackgroundTasks):
    """Email a 6-digit reset code. Always answers the same way, so it can't reveal who has an account."""
    email = payload.email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    if reset_rate_limited("forgot:ip:" + ip, RESET_RATE_PER_IP) or reset_rate_limited(
        "forgot:email:" + email, RESET_RATE_PER_EMAIL
    ):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a while and try again.")

    conn = None
    try:
        conn = get_db_connection()
        # A deactivated account can reset its password too, so its owner can
        # sign in again to reactivate it.
        user = conn.execute(
            f"SELECT username FROM users WHERE lower(username) = ? AND {usable_account_condition(conn)};",
            (email,),
        ).fetchone()
        if user:
            code = f"{secrets.randbelow(1_000_000):06d}"
            now = datetime.now(UTC)
            ensure_reset_table(conn)
            conn.execute(
                """INSERT INTO password_reset_codes (username, code_hash, expires_at, attempts, created_at)
                   VALUES (?, ?, ?, 0, ?)
                   ON CONFLICT(username) DO UPDATE SET code_hash = excluded.code_hash,
                       expires_at = excluded.expires_at, attempts = 0, created_at = excluded.created_at""",
                (
                    user["username"],
                    hash_reset_code(user["username"], code),
                    (now + timedelta(minutes=RESET_CODE_MINUTES)).isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()
            background_tasks.add_task(send_reset_code, user["username"], code)
    except (sqlite3.Error, RuntimeError):
        raise HTTPException(status_code=503, detail="Password reset is unavailable right now. Please try again later.")
    finally:
        if conn:
            conn.close()
    return {"message": FORGOT_MESSAGE}


@app.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, background_tasks: BackgroundTasks):
    """Check the emailed code and set a new password."""
    email = payload.email.strip().lower()
    code = payload.code.strip()
    ip = request.client.host if request.client else "unknown"
    if reset_rate_limited("reset:ip:" + ip, RESET_RATE_PER_IP * 3):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a while and try again.")
    if not code.isdigit():
        raise HTTPException(status_code=400, detail=INVALID_CODE_MESSAGE)
    error = password_error(payload.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)

    conn = None
    try:
        conn = get_db_connection()
        ensure_reset_table(conn)
        row = conn.execute(
            f"""SELECT r.username, r.code_hash, r.expires_at, r.attempts
                FROM password_reset_codes r JOIN users u ON u.username = r.username
                WHERE lower(r.username) = ? AND {usable_account_condition(conn, "u")};""",
            (email,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail=INVALID_CODE_MESSAGE)
        username = row["username"]
        expired = datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC)
        if expired or row["attempts"] >= RESET_MAX_ATTEMPTS:
            conn.execute("DELETE FROM password_reset_codes WHERE username = ?;", (username,))
            conn.commit()
            raise HTTPException(status_code=400, detail=INVALID_CODE_MESSAGE)
        if not hmac.compare_digest(row["code_hash"], hash_reset_code(username, code)):
            conn.execute("UPDATE password_reset_codes SET attempts = attempts + 1 WHERE username = ?;", (username,))
            conn.commit()
            left = RESET_MAX_ATTEMPTS - row["attempts"] - 1
            if left <= 0:
                raise HTTPException(status_code=400, detail=INVALID_CODE_MESSAGE)
            raise HTTPException(status_code=400, detail=f"That code is incorrect. {left} attempt(s) left.")

        hashed = bcrypt.hashpw(payload.new_password.encode("utf-8"), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET hashed_password = ? WHERE username = ?;", (hashed, username))
        conn.execute("DELETE FROM password_reset_codes WHERE username = ?;", (username,))
        end_sessions(conn, username)
        conn.commit()
    except (sqlite3.Error, RuntimeError):
        raise HTTPException(status_code=503, detail="Password reset is unavailable right now. Please try again later.")
    finally:
        if conn:
            conn.close()

    background_tasks.add_task(notify_password_changed, username)
    return {
        "message": "Your password has been reset and you have been signed out everywhere. "
                   "You can now sign in with your new password."
    }


# --- Reactivation codes -------------------------------------------------------
# Reactivating a deactivated account needs the password and a 6-digit code
# emailed to the account's address. The codes work like password-reset codes:
# stored as a keyed hash, valid for RESET_CODE_MINUTES, five tries, one use.

REACTIVATION_MAX_ATTEMPTS = 5
REACTIVATION_CODE_SENT_MESSAGE = (
    "We've emailed a 6-digit code to {email}. It expires in {minutes} minutes."
)
INVALID_REACTIVATION_CODE_MESSAGE = (
    "This code is invalid or has expired. Please request a new one."
)
REACTIVATION_UNAVAILABLE_MESSAGE = (
    "Your account could not be reactivated right now. Please try again later."
)


def ensure_reactivation_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reactivation_codes (
               username TEXT PRIMARY KEY,
               code_hash TEXT NOT NULL,
               expires_at TEXT NOT NULL,
               attempts INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL
           )"""
    )


def hash_reactivation_code(username: str, code: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"reactivate:{username}:{code}".encode(), hashlib.sha256).hexdigest()


def send_reactivation_code(email: str, code: str):
    text = (
        f"Your Tender Scrapper code to reactivate your account is {code}.\n\n"
        f"It expires in {RESET_CODE_MINUTES} minutes. If you didn't try to sign in, "
        "someone may know your password: reset it on the sign-in page straight away."
    )
    html_body = (
        "<html><body><h2>Reactivate your account</h2><p>Your code is:</p>"
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:6px">{code}</p>'
        f"<p>It expires in {RESET_CODE_MINUTES} minutes.</p>"
        "<small>If you didn't try to sign in, someone may know your password: "
        "reset it on the sign-in page straight away.</small></body></html>"
    )
    try:
        send_email(email, "Your Tender Scrapper reactivation code", text, html_body)
    except Exception:
        logger.exception("Reactivation code email failed")


@app.post("/reactivate/send-code")
def send_reactivation(
    request: Request,
    background_tasks: BackgroundTasks,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Email a 6-digit code for reactivating a deactivated account.

    Takes the same form as /login. A wrong password gets the same 401 as /login.
    """
    user = check_credentials(request, form_data)
    if user["is_active"]:
        raise HTTPException(status_code=400, detail="This account is already active. You can sign in.")
    username = user["username"]
    ip = request.client.host if request.client else "unknown"
    if reset_rate_limited("reactivate:ip:" + ip, RESET_RATE_PER_IP) or reset_rate_limited(
        "reactivate:account:" + username.lower(), RESET_RATE_PER_EMAIL
    ):
        raise HTTPException(status_code=429, detail="Too many codes requested. Please wait a while and try again.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(UTC)
    conn = None
    try:
        conn = get_db_connection()
        ensure_reactivation_table(conn)
        conn.execute(
            """INSERT INTO reactivation_codes (username, code_hash, expires_at, attempts, created_at)
               VALUES (?, ?, ?, 0, ?)
               ON CONFLICT(username) DO UPDATE SET code_hash = excluded.code_hash,
                   expires_at = excluded.expires_at, attempts = 0, created_at = excluded.created_at""",
            (username, hash_reactivation_code(username, code),
             (now + timedelta(minutes=RESET_CODE_MINUTES)).isoformat(), now.isoformat()),
        )
        conn.commit()
    except (sqlite3.Error, RuntimeError):
        logger.exception("Database error while creating a reactivation code")
        raise HTTPException(status_code=503, detail=REACTIVATION_UNAVAILABLE_MESSAGE)
    finally:
        if conn:
            conn.close()
    # The username is the account's email address.
    background_tasks.add_task(send_reactivation_code, username, code)
    return {"message": REACTIVATION_CODE_SENT_MESSAGE.format(email=username, minutes=RESET_CODE_MINUTES)}


@app.post("/reactivate")
def reactivate(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    code: str = Form("", max_length=12),
):
    """Switch a deactivated account back on and sign in.

    Takes the /login form plus the emailed code. An account that is already
    active simply signs in.
    """
    user = check_credentials(request, form_data)
    username = user["username"]
    if user["is_active"]:
        return token_response(username)

    ip = request.client.host if request.client else "unknown"
    if reset_rate_limited("reactivate-check:ip:" + ip, RESET_RATE_PER_IP * 3):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a while and try again.")
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code we emailed you.")

    conn = None
    try:
        conn = get_db_connection()
        ensure_reactivation_table(conn)
        row = conn.execute(
            "SELECT code_hash, expires_at, attempts FROM reactivation_codes WHERE username = ?;",
            (username,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail=INVALID_REACTIVATION_CODE_MESSAGE)
        if _is_past(row["expires_at"], datetime.now(UTC)) or row["attempts"] >= REACTIVATION_MAX_ATTEMPTS:
            conn.execute("DELETE FROM reactivation_codes WHERE username = ?;", (username,))
            conn.commit()
            raise HTTPException(status_code=400, detail=INVALID_REACTIVATION_CODE_MESSAGE)
        if not hmac.compare_digest(row["code_hash"], hash_reactivation_code(username, code)):
            conn.execute("UPDATE reactivation_codes SET attempts = attempts + 1 WHERE username = ?;", (username,))
            conn.commit()
            left = REACTIVATION_MAX_ATTEMPTS - row["attempts"] - 1
            if left <= 0:
                raise HTTPException(status_code=400, detail=INVALID_REACTIVATION_CODE_MESSAGE)
            raise HTTPException(status_code=400, detail=f"That code is incorrect. {left} attempt(s) left.")

        clear = "".join(
            f", {column} = NULL"
            for column in ("deactivated_at", "deletion_warning_sent_at")
            if column in user_columns(conn)
        )
        conn.execute(
            f"UPDATE users SET is_active = 1{clear} "
            "WHERE username = ? AND is_active = 0 AND deactivated_at IS NOT NULL;",
            (username,),
        )
        conn.execute("DELETE FROM reactivation_codes WHERE username = ?;", (username,))
        conn.commit()
    except (sqlite3.Error, RuntimeError):
        logger.exception("Database error while reactivating an account")
        raise HTTPException(status_code=503, detail=REACTIVATION_UNAVAILABLE_MESSAGE)
    finally:
        if conn:
            conn.close()
    logger.info("A deactivated account was reactivated")
    return token_response(username)
