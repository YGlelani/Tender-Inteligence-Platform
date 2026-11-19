"""
Login-token verification shared by every authenticated route.

Tokens are issued by the Login API (musiwalo-jwt-api, container `jwt-api`,
port 8006). Instead of keeping its own copy of the signing secret, the agent
asks the Login API whether a token is valid: the Login API is the only service
that needs JWT_SECRET, so separate repos never have to keep secrets in sync.

Valid answers are cached briefly (never past the token's own expiry) so the
dashboard isn't slowed down by an extra call per request.
"""
import hashlib
import logging
import os
import time

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)

# Both services sit on the shared `tender-scrapping-net` Docker network.
LOGIN_API_URL = os.getenv("LOGIN_API_URL", "http://jwt-api:8006").rstrip("/")
# Login API endpoint that verifies a bearer token and returns {"username": <sub>}.
LOGIN_API_VERIFY_PATH = os.getenv("LOGIN_API_VERIFY_PATH", "/protected-tenders")
CACHE_SECONDS = int(os.getenv("AUTH_CACHE_SECONDS", "60"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

_verified: dict[str, tuple[float, dict]] = {}  # sha256(token) -> (valid until, claims)


def _cache_until(token: str) -> float:
    # The Login API has already checked the signature; we only read `exp` to
    # make sure a cached answer never outlives the token itself.
    now = time.time()
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp")
    except jwt.InvalidTokenError:
        exp = None
    limit = now + CACHE_SECONDS
    return min(limit, float(exp)) if exp else limit


async def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _verified.get(key)
    if cached and cached[0] > time.time():
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(LOGIN_API_URL + LOGIN_API_VERIFY_PATH,
                                    headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        # 503, not 401: the user's session may be fine; the sign-in service is unreachable.
        logger.error("Login API unreachable at %s: %s", LOGIN_API_URL, e)
        raise HTTPException(status_code=503, detail="Sign-in service is unreachable. Please try again shortly.")

    if resp.status_code in (401, 403):
        try:
            detail = resp.json().get("detail") or "Invalid token"
        except ValueError:
            detail = "Invalid token"
        raise HTTPException(status_code=401, detail=detail)
    if resp.status_code != 200:
        logger.error("Login API verify returned %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(status_code=503, detail="Sign-in service could not verify your session.")

    username = (resp.json().get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Token has no user identity")

    claims = {"sub": username}
    if len(_verified) > 5000:
        _verified.clear()
    _verified[key] = (_cache_until(token), claims)
    return claims


def user_email(user: dict) -> str:
    email = (user.get("sub") or user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token has no user identity")
    return email
