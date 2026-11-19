import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .dependencies import Pool

bearer_scheme = HTTPBearer()
ALGORITHM = "HS256"
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def _claims_from_token(token, secret):
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid authentication token", headers=BEARER_CHALLENGE) from None
    if not payload.get("sub"):
        raise HTTPException(401, "Invalid authentication token", headers=BEARER_CHALLENGE)
    return payload


# Sign-ins end when the password is changed or reset: the Login API stores
# sessions_valid_after (Unix seconds) on the user, and tokens issued before it
# are refused. Databases the Login API has not touched yet have no column.
async def _session_cutoff_column(conn):
    columns = {row["name"] for row in await conn.fetch("PRAGMA table_info(users)")}
    return "sessions_valid_after" if "sessions_valid_after" in columns else "NULL"


def _issued_before_cutoff(claims, cutoff):
    if cutoff is None:
        return False
    issued_at = claims.get("iat")
    return not isinstance(issued_at, (int, float)) or issued_at < cutoff


# Signing out ends that one sign-in: the Login API lists the token's id ("jti")
# in revoked_tokens. Tokens without an id, or databases without the table, pass.
async def _token_signed_out(conn, claims):
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        return False
    if not await conn.fetchrow("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revoked_tokens'"):
        return False
    return await conn.fetchrow("SELECT 1 FROM revoked_tokens WHERE jti = ?", jti) is not None


async def require_user(
    pool: Pool,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
):
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(503, "JWT_SECRET is not configured")

    claims = _claims_from_token(credentials.credentials, secret)
    username = claims["sub"]
    async with pool.acquire() as conn:
        cutoff = await _session_cutoff_column(conn)
        user = await conn.fetchrow(
            f"""SELECT id, username, is_active, {cutoff} AS sessions_valid_after FROM users
            WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
            LIMIT 1""",
            username, username,
        )
        signed_out = await _token_signed_out(conn, claims)
    if not user or not user["is_active"]:
        raise HTTPException(401, "User account is inactive or unavailable", headers=BEARER_CHALLENGE)
    if _issued_before_cutoff(claims, user["sessions_valid_after"]) or signed_out:
        raise HTTPException(401, "Your session has ended. Please sign in again.", headers=BEARER_CHALLENGE)
    return {"id": int(user["id"]), "username": user["username"], "token": credentials.credentials}
