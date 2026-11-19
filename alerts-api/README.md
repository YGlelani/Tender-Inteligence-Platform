# Smart Tender Alerts API

A FastAPI service that matches public tenders to a company's **Business Profile** and notifies the user about the best opportunities, without any manual alert setup.

Part of the **Tender Scrapper** platform. It shares the platform's database and login (JWT) with the other services.

The service runs on port **9005**. Once it is running:

| | |
|---|---|
| **API docs (Swagger)** | `/docs` |
| **Health check** | `/health` |

---

## Contents

- [How it works](#how-it-works)
- [Matching and scoring](#matching-and-scoring)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Running locally](#running-locally)
- [Running with Docker](#running-with-docker)
- [Testing](#testing)
- [Project structure](#project-structure)
- [CI/CD](#cicd)
- [Recent changes](#recent-changes)

---

## How it works

Users never create alert rules. Their Business Profile *is* the alert.

1. The user signs in through the Login API and receives a JWT.
2. The Business Profile API stores the user's company profile: industry, categories, provinces, keywords and services.
3. The Tender Agent API can add extra details taken from the user's uploaded business documents (keywords, industries, service areas). A user who has uploaded documents but not filled in a Business Profile is matched on the documents alone in `/matches` (their service areas filter provinces the same way profile provinces do). Notifications still need a Business Profile.
4. This service compares each open tender against the profile and gives it a **score from 0 to 100**, with plain-language reasons.
5. Strong matches are saved as **notifications**. A background scanner repeats this every 5 minutes for every active profile.
6. The dashboard shows the user's matches, notifications and unread count.

```
Login API ──JWT──► Dashboard ──JWT──► Smart Alerts API ──► shared SQLite database
                                             │               (users, tenders,
                                             │                business_profiles)
                                             └──► Tender Agent API (document details)
```

## Matching and scoring

Each tender is scored against the profile in these areas:

| Area | Weight | How it matches |
|---|---|---|
| Province | 20 | Tender is in one of the profile's provinces (or in the head-office province) |
| Category | 25 | Tender category matches one of the profile's categories, or the tender-ml model finds a category the company and the tender share |
| Industry | 20 | Tender text mentions the profile's industry or a related term |
| Keywords | 25 | Profile or document keywords appear in the tender; related synonyms earn partial credit |
| Services | 10 | Wording in the tender overlaps with the services and company description |

The score is the points earned out of the points that applied to that tender, so areas the profile leaves empty don't count against it.

**ML category matching.** For each profile, the open tenders are sent to the tender-ml service (`POST /match-categories`, in batches of 2,000) with the company's industry, services, keywords and description. tender-ml predicts the categories the company most likely works in and compares them with each tender's saved and predicted categories. A shared category earns the category points with the reason *"Category matches your business (ML: …)"*. The ML answer can only turn a category mismatch into a match; it never lowers a score. If tender-ml cannot be reached, scoring is exactly as before.

**Rules that exclude a tender:**
- It is closed, cancelled, expired or awarded, or past its closing date (South African time).
- It has no closing date and was published more than 36 days ago. 95% of tenders with a closing date close within 36 days; older tenders saved before closing dates were scraped have none.
- The profile lists specific provinces and the tender is in another one. National tenders are always allowed.
- The tender needs a CIDB grade, and the profile has a grade that is too low.

**Thresholds:**

| Score | Result |
|---|---|
| 70 or more | **Strong** match: shown in `/matches` and creates a notification |
| 50 to 69 | **Near** match: shown in `/matches` only |
| Below 50 | Not shown |

## API reference

All endpoints except `/` and `/health` need the user's JWT:

```
Authorization: Bearer <JWT>
```

The token is checked with the same `JWT_SECRET` (HS256) as the Login API, and its subject must belong to an active user.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/profile` | The signed-in user's Business Profile, including details from their documents |
| `GET` | `/matches` | Current matching tenders (score ≥ 50, up to 150), best first. Also used by the AI dashboard and chat, so all three show the same matches |
| `GET` | `/notifications` | Strong-match notifications. Query: `limit` (1–200, default 50), `unread_only` (default `false`) |
| `GET` | `/notifications/unread-count` | Number of unread notifications |
| `POST` | `/notifications/{notification_id}/read` | Mark one notification as read (returns `204`) |
| `GET` | `/health` | Service health check |

**Error responses**

| Status | Meaning |
|---|---|
| `401` | Missing, invalid or expired token, or the user is inactive |
| `404` | No Business Profile exists yet, or the notification was not found |
| `503` | The database or `JWT_SECRET` is not configured |

Full request and response schemas are available at `/docs`.

## Configuration

Settings come from environment variables. For local development, put them in a `.env` file in the project root. Git ignores `.env`, so it is never committed.

| Variable | Description |
|---|---|
| `JWT_SECRET` | Required. Must match the secret used by the Login API |
| `DATABASE_PATH` | Path to the shared SQLite database file (the file must already exist) |
| `ALERT_SCAN_INTERVAL_SECONDS` | How often the background scanner runs, in seconds (minimum 60) |
| `AGENT_URL` | Base URL of the Tender Agent API, used for business-document details |
| `TENDER_ML_URL` | Base URL of the tender-ml category model (default `http://tender-ml:9004`) |
| `TENDER_ML_TIMEOUT` | Seconds to wait for tender-ml before scoring without it (default `10`) |

**Database tables**

- **Read:** `users`, `business_profiles`, `tenders`, `categories`, `organisations`. Other platform services own these tables.
- **Owned:** `profile_alert_notifications`. Created automatically when the service starts.

## Running locally

Requires **Python 3.11+** and a copy of the shared `tenders.db` database.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # app + test dependencies

# create .env with at least JWT_SECRET and DATABASE_PATH (see Configuration)
uvicorn app.main:app --reload --port 9005
```

Then open http://localhost:9005/docs.

## Running with Docker

The container joins the platform's existing Docker network and database volume (defined in `compose.yaml`). Both must exist first.

```bash
docker compose up -d --build
```

The API is published on port **9005**.

## Testing

```bash
pytest -q
```

The tests build their own temporary SQLite database. They need no external services or real secrets.

## Project structure

```
app/
├── main.py          App startup, background scanner, /health
├── routers.py       API endpoints
├── dependencies.py  Shared FastAPI dependencies (database pool)
├── auth.py          JWT validation
├── service.py       Live matching, notifications and background scanning
├── matching.py      Scoring a profile against a tender
├── keywords.py      Keyword and synonym scoring
├── rules.py         Text, category and CIDB-grade rules
├── synonyms.py      Related keyword and industry terms
├── documents.py     Business-document details from the Tender Agent API
├── db.py            Database queries
├── sqlite_pool.py   Async wrapper around SQLite
├── schemas.py       Response models
└── config.py        Environment settings
tests/               Pytest suite (conftest.py builds the test database)
requirements.txt     Runtime dependencies (installed in the Docker image)
requirements-dev.txt Runtime + test dependencies (used locally and in CI)
```

## CI/CD

- **CI** (`.github/workflows/ci.yml`): runs on every push and pull request to `main`. It installs dependencies, checks that the code compiles, runs the tests and builds the Docker image.
- **Deploy** (`.github/workflows/deploy.yml`): runs after CI succeeds on `main`, or manually. On the self-hosted server it writes `.env` from the `JWT_SECRET` repository secret, rebuilds and restarts the container with Docker Compose, and checks `/health`.

## Recent changes

### ML category matching

Category points can now come from the tender-ml model (see [Matching and scoring](#matching-and-scoring)). Old and new scores were compared for every business profile in a copy of the database against all 6,786 open tenders:

- No score went down.
- Per profile, between 0 and 70 tenders scored higher. A profile with too little text gets no ML categories and is unchanged.
- Every level change was from *not shown* to *near match*. No new strong matches, and so no new notifications, were created.
- In a spot check of the tenders that moved up for an IT company, all were IT tenders (software licences, network and cybersecurity services, VoIP, hosting).

Code: `app/ml_categories.py` (client), `app/matching.py` (`_score_category`), `app/service.py` (one tender-ml call per profile). Tests: `tests/test_ml_categories.py` and the new cases in `tests/test_matching.py`.
### Code-quality and documentation update

**Matching results and API responses are unchanged**, apart from the `/health` change below. The new scoring code was compared with the previous version on 60,000 random profile/tender cases and gave identical scores and reasons. The same sequence of API calls also returned identical responses from the old and new versions.

**API**
- Swagger now documents the `404` and `503` errors each endpoint can return.
- Endpoint parameters use FastAPI's recommended `Annotated` style.
- `/health` and `/` no longer return a hardcoded `"port": 9005`. The real port is set by Docker, so the field could be wrong.

**Structure**
- Routes only handle HTTP. Creating notifications moved from `routers.py` to `service.py`, and the scanner and the endpoints now share the same alert rule and 70-point threshold.
- The database pool is shared through `app.state` and a FastAPI dependency (`dependencies.py`) instead of module globals and an import from `main.py`.

**Matching**
- The large `score_profile` function is split into one small step per scoring area.
- Text, category and CIDB rules moved to `rules.py`; keyword scoring moved to `keywords.py`.
- Repeated synonym phrases in `synonyms.py` are now named constants.

**Database**
- SQLite queries now run in a worker thread, so slow queries no longer block other requests.
- The notifications query no longer builds SQL from strings (fixes the Bandit B608 warning).
- The SQLite connection wrapper moved to `sqlite_pool.py`.
- Queries are plain SQLite. The old PostgreSQL-to-SQLite rewriting layer is gone.
- Removed unused code: `count_unread`, `notification_exists`, `normalise_reasons`, and an unused `unread_only` option.

**Reliability**
- Agent-service errors are now caught by specific type (network, HTTP status, bad URL, bad JSON) instead of catching every exception.

**Project**
- Shared test setup moved to `tests/conftest.py`.
- `bcrypt` (unused) removed. `pytest` moved to `requirements-dev.txt`, so it is no longer installed in the production image.
- All app files follow standard Python style (PEP 8).
- `.gitignore` now also excludes local databases, tool caches, editor settings and scanner reports.
- This README now describes the current SQLite setup.
- `.env.example` removed. All `.env*` files are ignored by Git.
