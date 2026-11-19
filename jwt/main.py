import os
import httpx
import jwt
import bcrypt
import psycopg2
from datetime import datetime, timedelta, UTC
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from dotenv import load_dotenv

# Loads variables from your .env file
load_dotenv()

app = FastAPI(title="JWT Authentication API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Make unexpected crashes readable.

    FastAPI's default 500 response is generated OUTSIDE the CORS middleware, so
    it has no Access-Control-Allow-Origin header. The browser then reports a
    misleading "blocked by CORS policy" error instead of the real crash. This
    handler returns the actual error WITH CORS headers so it is visible in the
    browser Network tab (handy when you have no shell access to the server).

    NOTE: it exposes the exception text for debugging — tighten this (log it
    server-side and return a generic message) once the login bug is fixed.
    """
    origin = request.headers.get("origin", "*")
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        },
    )

# Security settings
# Now securely pulls the JWT_SECRET from your .env file
SECRET_KEY = os.getenv("JWT_SECRET") or "your_super_secret_development_key"
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

# Pointing directly to the Oracle Database Server
# It will prioritize the DATABASE_URL from your .env file if it exists
# Use `or` (not getenv's default arg) so an empty DATABASE_URL also falls back.
# os.getenv("X", default) returns "" when X is set-but-empty, and psycopg2
# then silently connects to the local socket (localhost:5432) instead of the
# real DB. `or` catches both the missing AND the empty-string case.
def normalize_database_url(value: str) -> str:
    """
    Normalize database URLs for the Docker deployment.

    The PostgreSQL container is reachable by its Docker hostname on the
    shared tender-scrapping network and listens on 5432 internally, even
    though the host publishes PostgreSQL on port 5433.
    """
    value = (value or "").strip()

    if not value:
        return (
            "postgresql://tender_scrapping_agent:"
            "tender%40scrapping@129.151.181.87:5433/"
            "tender_scrapping_db"
        )

    for hostname in ("tender-postgres", "postgres"):
        value = value.replace(
            f"@{hostname}:5433/",
            f"@{hostname}:5432/",
        )

    return value


DB_URL = normalize_database_url(os.getenv("DATABASE_URL"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class TenderTextRequest(BaseModel):
    text: str

class GenerateAgentRequest(BaseModel):
    prompt: str

def get_db_connection():
    """Creates a new database connection for each request."""
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

def create_access_token(data: dict):
    """Generates a JWT token with an expiration time."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Verifies user credentials against the database and returns a JWT token."""
    conn = None
    cur = None

    # --- 1. Fetch the user (only DB errors are expected here) ---------------
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT username, hashed_password FROM users WHERE username = %s AND is_active = TRUE;",
            (form_data.username,),
        )
        user = cur.fetchone()
    except psycopg2.Error as e:
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    # --- 2. Unknown / inactive user, or missing hash -> generic 401 ----------
    if not user or user.get("hashed_password") is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- 3. Normalise the stored hash --------------------------------------
    # Depending on the column type, psycopg2 may return the hash as a str
    # (text/varchar) or as bytes/memoryview (bytea). bcrypt.checkpw needs bytes.
    stored = user["hashed_password"]
    if isinstance(stored, memoryview):
        stored = stored.tobytes()
    if isinstance(stored, str):
        stored = stored.encode("utf-8")

    # --- 4. Verify the password --------------------------------------------
    try:
        password_ok = bcrypt.checkpw(form_data.password.encode("utf-8"), stored)
    except ValueError as e:
        # The stored value is not a valid bcrypt hash (e.g. the signup service
        # saved it as plaintext or with a different algorithm). This is a data
        # problem, not a wrong password — surface it clearly.
        raise HTTPException(
            status_code=500,
            detail=f"Stored password for '{form_data.username}' is not a valid bcrypt hash: {e}",
        )

    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- 5. Issue the token -------------------------------------------------
    access_token = create_access_token(data={"sub": user["username"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "session_timeout_hours": ACCESS_TOKEN_EXPIRE_MINUTES / 60,
    }

@app.get("/")
async def root():
    return {"message": "JWT API is running. Go to /docs to test the login."}

@app.get("/health")
async def health_check():
    """Endpoint for Docker and GitHub Actions to verify the API is running."""
    return {"status": "healthy"}

def verify_access_token(token: str) -> dict:
    """Verify token signature and enforce its expiry claim."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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


@app.get("/protected-tenders")
async def get_protected_tenders(token: str = Depends(oauth2_scheme)):
    """Reject invalid or expired access tokens before returning protected data."""
    claims = verify_access_token(token)
    return {
        "message": "If you are seeing this, you successfully passed the token!",
        "username": claims.get("sub"),
    }

@app.post("/api/ai/generate-insight")
async def generate_tender_insight(request: GenerateAgentRequest):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    model = os.getenv("AI_MODEL", "llama3.2:3b")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"You are a helpful AI assistant analyzing tender documents. {request.prompt}",
                    "stream": False
                }
            )
            response.raise_for_status()
            result = response.json()
            return {"generated_text": result.get("response", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama AI Error: {str(e)}")
