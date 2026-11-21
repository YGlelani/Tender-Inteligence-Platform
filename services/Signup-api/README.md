# Signup API

Registration and email-verification service for the Tender Scrapper platform. Businesses sign up with a company email address, confirm it through a single-use link, and then manage their profile using an access token issued by the platform's authentication service.

Built with **FastAPI** and **SQLite**, packaged with **Docker**, and tested and deployed with **GitHub Actions**.

## Contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [How registration works](#how-registration-works)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Getting started](#getting-started)
- [Testing](#testing)
- [CI/CD](#cicd)
- [Security](#security)
- [Project structure](#project-structure)

## Features

- **Business-only registration**: free mail providers such as Gmail, Outlook and Yahoo are rejected.
- **Password policy**: at least 8 characters with an uppercase letter, a number and a special character, and no more than 72 bytes (the bcrypt limit).
- **Verified accounts only**: a signup is held as a pending registration. The user account is created only after the email link is opened.
- **Secure verification links**: tokens are random, single-use and expire after 30 minutes by default. Only a SHA-256 hash of each token is stored.
- **Abuse protection**: signup and resend requests are rate-limited per client IP and per email address.
- **Profile management**: authenticated users can read and update their profile.
- **Event notifications**: profile updates are sent to the notifications service in the background. If that call fails, the request still succeeds.
- **Account deletion**: a signed-in user can delete their account after entering their password again. See [Account deletion](#account-deletion).
- **Account deactivation**: a signed-in user can switch their account off without deleting it, and sign in again to come back. Accounts left deactivated for 12 months are deleted. See [Account deactivation](#account-deactivation).

## Tech stack

| Area | Technology |
| --- | --- |
| Language | Python 3.11 |
| Web framework | FastAPI, Uvicorn |
| Storage | SQLite, shared with the other platform services |
| Security | bcrypt (password hashing), PyJWT (access tokens) |
| Delivery | Docker Compose, GitHub Actions |

## How registration works

```text
POST /signup ──► pending_registrations ──► verification email
                                                  │
         user opens the link (frontend verify page)
                                                  │
GET /email/verify?token=… ──► users ──► welcome email
```

1. `POST /signup` validates the request, hashes the password with bcrypt, stores a pending registration and emails a verification link.
2. The link opens the frontend's verify page, which calls `GET /email/verify` with the token.
3. The API creates the user, deletes the pending registration and sends a welcome email. An expired or already-used link returns a page that explains what happened.
4. `POST /email/resend-verification` sends a new link. The previous link stops working.

## API reference

When the service is running, interactive documentation is available at `/docs` (Swagger UI) and `/redoc`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/` | None | Service status |
| `GET` | `/health` | None | Database connectivity check. Returns `503` if the database is unavailable. |
| `POST` | `/signup` | None | Start a registration and send the verification email |
| `GET` | `/email/verify?token=…` | None | Complete a registration. Returns an HTML result page. |
| `POST` | `/email/resend-verification` | None | Send a new verification link |
| `GET` | `/user/profile` | Bearer token | Get the signed-in user's profile |
| `PUT` | `/user/profile` | Bearer token | Update the signed-in user's full name |
| `DELETE` | `/user/account` | Bearer token | Delete the signed-in user's account and data. Body: `{"password": "…"}` |
| `POST` | `/user/deactivate` | Bearer token | Deactivate the signed-in user's account. Body: `{"password": "…"}`. Returns the date it will be deleted if they don't come back. |

### Example: sign up

```http
POST /signup
Content-Type: application/json

{
  "company_name": "Example Trading",
  "email": "tenders@example.com",
  "password": "Str0ng!Passw0rd"
}
```

```json
{
  "message": "Verification email sent. Please check your email to complete registration.",
  "email": "tenders@example.com",
  "account_created": false,
  "email_verification_required": true
}
```

### Example: update profile

```http
PUT /user/profile
Authorization: Bearer <access-token>
Content-Type: application/json

{ "full_name": "Jane Doe" }
```

### Errors

Errors are returned as JSON in the form `{"detail": "<message>"}`. Each message is written so that it can be shown to the user.

| Status | Meaning |
| --- | --- |
| `400` | Invalid company name, invalid or non-business email, or weak password |
| `401` | Missing, invalid or expired access token, or inactive user |
| `403` | Email address not verified, or wrong password when deleting or deactivating an account |
| `404` | Resend requested for an email address with no pending registration |
| `409` | Account already exists, or a valid verification link has already been sent |
| `422` | Request body failed validation |
| `429` | Too many attempts; try again later |
| `500` | Unexpected database error during signup |
| `503` | Email could not be sent, the database is unavailable, or the service is not fully configured |

## Account deletion

`DELETE /user/account` asks for the user's password again, then:

1. Calls the AI agent's `POST /internal/accounts/delete` with `X-Internal-Key: <ACCOUNT_DELETION_KEY>`. The agent deletes the user's uploaded documents, AI profile, insights and chat history, and the AI service's copy of the profile.
2. If the agent confirms, deletes everything that belongs to the user in the shared database in one transaction: application history, every table with a `user_id` column (profiles, documents, alerts, saved tenders, applications, notifications), password-reset codes, any pending registration and the user.
3. Sends a confirmation email.

If the agent cannot confirm, nothing in the shared database is deleted and the API answers `503`, so the user can try again. A wrong password answers `403`. Attempts are rate-limited in the same way as signup.

The tests are in `test_account_deletion.py`.

## Account deactivation

`POST /user/deactivate` asks for the user's password again, then sets `is_active = 0` and `deactivated_at` on the user and emails a confirmation. Nothing is deleted. Every service already refuses inactive accounts, so the user's tokens stop working straight away, and the notifications service stops emailing them.

To come back, the user signs in again on the login page. The Login API (`musiwalo-jwt-api`) answers `403` after the correct password, emails a 6-digit code (`POST /reactivate/send-code`), and its `POST /reactivate` switches the account back on once the code is entered. Account deletion also removes any of these codes (`reactivation_codes`). Accounts switched off any other way (no `deactivated_at`) cannot be reactivated by their user.

Every hour (and at startup) the API also:

1. Deletes accounts that have been deactivated for `DEACTIVATED_ACCOUNT_RETENTION_DAYS` (365), in the same way as `DELETE /user/account`, and emails a confirmation. If the AI agent is unavailable, it tries again next time.
2. Emails a warning `DELETION_WARNING_DAYS` (30) before that date, once.

The tests are in `test_account_deactivation.py`.

## Configuration

The service reads all of its settings from environment variables. Keep real values in a local **`.env`** file in the project root. The file is listed in `.gitignore` and `.dockerignore` and must never be committed. In production, the deploy workflow creates this file from GitHub Actions secrets.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `JWT_SECRET` | Yes | | Secret used to verify access tokens. It must match the authentication service. |
| `JWT_ALGORITHM` | No | `HS256` | Algorithm used to sign access tokens |
| `EMAIL_CONFIRMATION_URL` | Yes | | Address of the frontend verify page, ending in `/verify.html`. The token is added as `?token=…`. |
| `LOGIN_URL` | Recommended | `http://127.0.0.1:8005` | Login page linked from the welcome, deactivation and deletion-warning emails |
| `EMAIL_FROM` | Yes | | Sender address for outgoing email |
| `SMTP_HOST` | Yes | | SMTP server host name |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USERNAME` | Yes | | SMTP login |
| `SMTP_PASSWORD` | Yes | | SMTP password or app password |
| `SMTP_USE_TLS` | No | `true` | `true` uses STARTTLS (usually port 587). `false` uses implicit TLS (usually port 465). |
| `DATABASE_PATH` | No | `/data/tenders.db` | Location of the SQLite database file |
| `VERIFICATION_TOKEN_EXPIRE_MINUTES` | No | `30` | Number of minutes a verification link stays valid |
| `NOTIFICATIONS_API_URL` | No | | Base URL of the notifications service. `compose.yaml` points it at the notifications container. |
| `INTERNAL_API_KEY` | No | | Shared key for the notifications service. If it is not set, notifications are skipped. |
| `ACCOUNT_DELETION_KEY` | For account deletion | | Shared with the AI agent (`tender-ai-agent`), which must have the same value. If it is not set, `DELETE /user/account` answers `503`. |
| `AGENT_API_URL` | No | `http://tender-agent-api:9000` | Address of the AI agent on the shared Docker network |
| `DEACTIVATED_ACCOUNT_RETENTION_DAYS` | No | `365` | Days a deactivated account is kept before it is deleted |
| `DELETION_WARNING_DAYS` | No | `30` | How many days before that deletion the warning email is sent |
| `ACCOUNT_JOBS_INTERVAL_SECONDS` | No | `3600` | How often deactivated accounts are checked |
| `RATE_LIMIT_WINDOW_SECONDS` | No | `3600` | Length of the rate-limit window |
| `RATE_LIMIT_PER_IP` | No | `10` | Requests allowed from one IP address per window, for each action |
| `RATE_LIMIT_PER_EMAIL` | No | `3` | Requests allowed for one email address per window, for each action |

> **Notes**
> - If `EMAIL_CONFIRMATION_URL` does not end in `/verify.html`, the API links to `/verify.html` on port `8008` of the same host.
> - `compose.yaml` does not pass the rate-limit or deactivation variables to the container, so the defaults apply when the service runs in Docker.

## Getting started

### Prerequisites

- Python 3.11 or later
- An SMTP account for sending email. An SMTP sandbox service is enough for local testing.
- Docker with Compose, for container deployment

### Run locally

```bash
git clone <repository-url>
cd Signup-api

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root and add the variables from [Configuration](#configuration). For local runs, set `DATABASE_PATH=./data/tenders.db`, because the default path points to the container volume.

```bash
uvicorn main:app --reload --port 8000 --env-file .env
```

The API is now running at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`. The database tables are created on startup if they do not already exist.

### Run with Docker

`compose.yaml` attaches the service to an external Docker network and a named volume that it shares with the other Tender Scrapper services. Create those first, or start the main platform stack. Compose reads `.env` from the project root to fill in the environment variables.

```bash
docker compose up -d --build
curl http://localhost:8007/health
```

The container listens on port `8000` and is published on host port `8007`.

## Testing

```bash
pip install pytest httpx2
python -m pytest -q
```

The tests use a temporary SQLite database and replace outgoing email and notification calls with stubs, so they do not need an SMTP server, network access or any secrets.

| File | Coverage |
| --- | --- |
| `test_main.py` | Unit tests for email and password validation and for token generation |
| `test_signup_flow.py` | API tests for signup, verification, resending, rate limiting, profile updates and startup |

## CI/CD

| Workflow | Trigger | What it does |
| --- | --- | --- |
| **Build and Test** (`ci.yml`) | Pushes to `main` and pull requests into `main` | Installs dependencies and runs the test suite on Python 3.11 |
| **Deploy Signup API** (`deploy.yml`) | A successful **Build and Test** run on `main`, or a manual run | Checks that the required secrets exist, writes `.env` from them with owner-only file permissions, rebuilds the container and waits for `/health` to respond |

The deploy workflow needs these repository secrets:

- **Required:** `JWT_SECRET`, `EMAIL_CONFIRMATION_URL`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`
- **Optional:** `LOGIN_URL`, `SMTP_PORT`, `SMTP_USE_TLS`, `VERIFICATION_TOKEN_EXPIRE_MINUTES`, `INTERNAL_API_KEY`, `AGENT_API_URL`
- **Needed for account deletion:** `ACCOUNT_DELETION_KEY` (the deploy warns if it is missing)

## Security

- Passwords are hashed with bcrypt. They are never stored or logged in plain text.
- Verification tokens are 256-bit random values. Only their SHA-256 hashes are stored, and each link works once and expires.
- Secrets are supplied only through environment variables. `.env` is excluded from both git and the Docker build context.
- Database and email failures are logged on the server. Clients receive only a short, user-facing message.

**Known limitations**

- Rate limits are kept in memory. They reset when the service restarts and are not shared between instances. Behind a reverse proxy, every request appears to come from the proxy's IP address.
- CORS allows all origins. The API authenticates with bearer tokens, not cookies, so it does not rely on CORS for protection.

## Project structure

```text
.
├── main.py                  # FastAPI application
├── test_main.py             # Unit tests
├── test_signup_flow.py      # API tests
├── requirements.txt         # Runtime dependencies
├── Dockerfile               # Container image
├── compose.yaml             # Container, network and volume settings
└── .github/workflows/
    ├── ci.yml               # Build and test
    └── deploy.yml           # Deploy after a successful build on main
```
