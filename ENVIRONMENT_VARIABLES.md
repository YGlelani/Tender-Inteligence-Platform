# Environment variables

Three places hold settings:

1. **Staging**: `.env.staging` (from [.env.staging.example](.env.staging.example)), read by
   [compose.staging.yaml](compose.staging.yaml). Locally you write it; on the staging runner
   the workflow writes it from the `staging` GitHub environment.
2. **Production**: the `.env` files and GitHub secrets each service's own deploy workflow
   uses today, or the `production` GitHub environment once this repository deploys production.
3. **Inside the containers**: what each service reads (last section).

Never put a real value in a committed file. `.env`, `.env.*` and `.env.staging` are
git-ignored; only `*.example` files are committed.

## Staging settings (`.env.staging`)

Staging reads only `USER_SERVER_IP` and names starting with `STAGING_`. A missing required
value stops `docker compose` with a message naming it; `scripts/staging/check_staging.py`
also rejects `change-me`, values shorter than 32 characters and (with `--production-env`)
any value equal to a production value.

### Required

| Name | Used by | Notes |
|---|---|---|
| `USER_SERVER_IP` | both sites, links in e-mails, CORS | IP or host name browsers use for staging; `localhost` locally |
| `STAGING_JWT_SECRET` | Login, Signup, Alerts, Notifications APIs | signs sign-in tokens |
| `STAGING_INTERNAL_API_KEY` | Signup, Login -> Notifications | `X-Internal-Key` |
| `STAGING_ACCOUNT_DELETION_KEY` | Signup -> AI agent | account deletion |
| `STAGING_AI_SERVICE_API_KEY` | AI agent -> AI service | `X-Internal-Key` |
| `STAGING_SCRAPER_API_KEY` | Scraper API | protects write endpoints |

Generate each with `openssl rand -hex 32`. Every value must be new and different from production.

### Optional

| Name | Default | Used by | Notes |
|---|---|---|---|
| `STAGING_AZURE_AI_ENDPOINT`, `STAGING_AZURE_AI_API_KEY` | empty | AI agent | empty = chat reports `degraded`; use a staging key |
| `STAGING_AZURE_AI_DEPLOYMENT` | `mistral-small-2503` | AI agent | |
| `STAGING_AZURE_AI_VISION_DEPLOYMENT` | same as above | AI agent | scanned documents |
| `STAGING_EMBED_MODEL` | `text-embedding-3-small` | AI agent | |
| `STAGING_AZURE_EMBED_ENDPOINT`, `STAGING_AZURE_EMBED_API_KEY` | empty | AI agent | only if embeddings live on another Azure resource |
| `STAGING_AGENT_ADMIN_KEY` | empty (off) | AI agent | `X-Admin-Key` for a full re-index |
| `STAGING_TENDER_SYNC_INTERVAL` | `21600` | AI agent | seconds; `0` start-up only, `-1` off |
| `STAGING_AI_MODEL` | `llama3.1:8b` | AI service | Ollama model; pull it once |
| `STAGING_AI_REQUEST_TIMEOUT_SECONDS` | `600` | AI service | |
| `STAGING_OLLAMA_KEEP_ALIVE` | `5m` | Ollama | production keeps the model loaded (`-1`) |
| `STAGING_EMAIL_FROM`, `STAGING_SMTP_HOST`, `STAGING_SMTP_USERNAME`, `STAGING_SMTP_PASSWORD` | empty | Signup, Login, Notifications | empty = e-mails fail with a clear error; use a sandbox account |
| `STAGING_SMTP_PORT` | `587` | same | |
| `STAGING_SMTP_USE_TLS` | `true` | same | `true` = STARTTLS, `false` = SMTPS |
| `STAGING_EMAIL_CONFIRMATION_URL` | `http://USER_SERVER_IP:18008/verify.html` | Signup | must end in `/verify.html` |
| `STAGING_LOGIN_PAGE_URL` | `http://USER_SERVER_IP:18009/login.html` | Signup | link in account e-mails |
| `STAGING_CORS_ORIGINS` | staging main site + AI workspace | all APIs | comma-separated |
| `STAGING_SESSION_TIMEOUT_HOURS` | `2` | Login API | |
| `STAGING_ALERT_SCAN_INTERVAL_SECONDS` | `300` | Alerts API | |
| `STAGING_SCRAPER_LOOP_ENABLED` | `true` | Scraper API | fills the staging database from eTenders |
| `STAGING_ETENDERS_BASE_URL` | `https://www.etenders.gov.za` | Scraper API | public site |
| `STAGING_IMAGE_TAG` | `staging` | all built images | `tender-staging/<service>:<tag>` |

### Ports

| Name | Default | Production equivalent |
|---|---|---|
| `STAGING_SCRAPER_PORT` | 18000 | 8000 |
| `STAGING_CLIENT_PORT` | 18001 | 8001 |
| `STAGING_CACHE_PORT` | 18003 | 8003 |
| `STAGING_LOGIN_PORT` | 18006 | 8006 |
| `STAGING_SIGNUP_PORT` | 18007 | 8007 |
| `STAGING_FRONTEND_PORT` | 18009 | 8009 (`USER_SERVER_PORT`) |
| `STAGING_AGENT_PORT` | 19000 | 9000 |
| `STAGING_AI_FRONTEND_PORT` | 19001 | 9001 |
| `STAGING_ML_PORT` | 19004 (127.0.0.1 only) | 9004 |
| `STAGING_ALERTS_PORT` | 19005 | 9005 |
| `STAGING_NOTIFICATIONS_PORT` | 19007 | 9007 |
| `STAGING_OVERVIEW_PORT`, `STAGING_SIGNUP_FRONTEND_PORT`, `STAGING_BUSINESS_PROFILE_PORT`, `STAGING_TRACKER_PORT`, `STAGING_SAVED_TENDERS_PORT`, `STAGING_TENDER_SEARCH_PORT` | 18005, 18008, 19002, 19006, 19008, 19009 | services not in this repository yet; used only by the main site's links |

### Fixed in `compose.staging.yaml` (deliberately not configurable)

So that no setting can point staging at production, these are hard-wired to staging services:
`REDIS_URL=redis://redis:6379/0`, `CLIENT_API_URL=http://client-api:8001`, `AI_SERVICE_URL=http://ai:8002`,
`ALERTS_API_URL=http://alerts-api:9005`, `TENDER_ML_URL=http://tender-ml:9004`,
`LOGIN_API_URL=http://jwt-api:8006`, `NOTIFICATIONS_API_URL=http://tender-notifications-api:8000`,
`AGENT_API_URL` / `AGENT_URL` (internal) `=http://tender-agent-api:9000`, `OLLAMA_BASE_URL=http://ollama:11434`,
every `DATABASE_PATH` (inside a staging volume) and `CACHE_KEY_PREFIX=staging`.

## Browser sites: start-up variables

Read by `docker-entrypoint.d/40-runtime-config.sh` in each nginx image. Production sets none.

| Site | Variable | Example | Effect |
|---|---|---|---|
| `frontend` | `USER_SERVER_IP` | `203.0.113.10` | host the pages call |
| `frontend` | `FRONTEND_SERVICE_PORTS` | `client=18001,login=18006,...` | port per service name in `scripts/config.js` |
| `tender-ai-frontend` | `AGENT_URL` | `http://203.0.113.10:19000` | AI agent address; also allowed in the CSP |
| `tender-ai-frontend` | `LOGIN_URL` | `http://203.0.113.10:18009/login.html` | where signed-out users go |
| `tender-ai-frontend` | `MAIN_SITE_PORT` | `18009` | links back to the main site |

## GitHub secrets and variables

Create them in **Settings -> Environments -> (environment) -> secrets / variables**, not as
repository secrets.

### `staging` environment

| Kind | Name | Required |
|---|---|---|
| variable | `USER_SERVER_IP` | yes |
| secret | `STAGING_JWT_SECRET`, `STAGING_INTERNAL_API_KEY`, `STAGING_ACCOUNT_DELETION_KEY`, `STAGING_AI_SERVICE_API_KEY`, `STAGING_SCRAPER_API_KEY` | yes |
| secret | `STAGING_AZURE_AI_ENDPOINT`, `STAGING_AZURE_AI_API_KEY`, `STAGING_AZURE_EMBED_ENDPOINT`, `STAGING_AZURE_EMBED_API_KEY`, `STAGING_AGENT_ADMIN_KEY` | for AI features |
| secret | `STAGING_EMAIL_FROM`, `STAGING_SMTP_HOST`, `STAGING_SMTP_USERNAME`, `STAGING_SMTP_PASSWORD` | for e-mails |
| variable | `STAGING_EXTRA_SETTINGS` | no: other non-secret `STAGING_*` settings, one `NAME=value` per line (ports, `STAGING_AI_MODEL`, `STAGING_SMTP_PORT`, ...) |
| variable | `STAGING_SITE_URL` | no: link shown on the deployment, e.g. `http://<server>:18009` |
| variable | `STAGING_COMPARE_PRODUCTION_ENV_FILES` | no: space-separated paths of production `.env` files on the staging runner's machine; the deploy then fails if a staging secret equals a production value |

### `production` environment

Needed only once `PRODUCTION_DEPLOY_ENABLED=true` (see [DEPLOYMENT.md](DEPLOYMENT.md)).
Use the same values the service repositories hold today. Names that changed because one
repository cannot have two secrets with the same name:

| Secret in this repository | Was, in the service repository |
|---|---|
| `SCRAPER_API_KEY` | `API_KEY` (tender-scrapping-database) |
| `AZURE_AI_API_KEY` | `API_KEY` (tender-ai-agent) |
| `AZURE_AI_ENDPOINT` | `endpoint` (tender-ai-agent) |
| `AZURE_AI_DEPLOYMENT` | `deployment_name` (tender-ai-agent) |

Other secrets, unchanged names: `JWT_SECRET`, `JWT_ALGORITHM`, `INTERNAL_API_KEY`,
`ACCOUNT_DELETION_KEY`, `AI_SERVICE_API_KEY`, `AGENT_ADMIN_KEY`, `ETENDERS_BASE_URL`, `AI_MODEL`,
`AI_REQUEST_TIMEOUT_SECONDS`, `CLIENT_API_URL`, `REDIS_URL`, `EMAIL_CONFIRMATION_URL`,
`LOGIN_URL` (main-site login page; used by Signup-api and tender-ai-frontend), `AGENT_URL`
(public AI agent address for tender-ai-frontend), `AGENT_API_URL`, `APP_URL`,
`NOTIFICATIONS_PUBLIC_URL`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_USE_TLS`, `VERIFICATION_TOKEN_EXPIRE_MINUTES`, `SESSION_TIMEOUT_HOURS`.
Not needed: `POSTGRES_*` (only the finished one-time PostgreSQL-to-SQLite migration used them),
`GHCR_TOKEN` (images are built on the server).

Production variables: `USER_SERVER_PORT` (main site port, today 8009), `PRODUCTION_SITE_URL` (optional).

### Repository variables

| Name | Purpose |
|---|---|
| `PRODUCTION_DEPLOY_ENABLED` | `true` lets deploy-production.yml deploy; anything else stops after the tests |
| `PRODUCTION_SERVICES` | space-separated services to deploy, e.g. `frontend tender-ai-frontend` |
| `PROJECT_LOGIN_API`, `PROJECT_SIGNUP_API`, `PROJECT_NOTIFICATIONS_API`, `PROJECT_ALERTS_API`, `PROJECT_TENDER_ML` | Compose project names of today's production containers, if they differ from the defaults |

## What each service reads

| Service | Variables (from the code) |
|---|---|
| alerts-api | `DATABASE_PATH`, `JWT_SECRET`, `CORS_ORIGINS`, `ALERT_SCAN_INTERVAL_SECONDS`, `AGENT_URL`, `TENDER_ML_URL`, `TENDER_ML_TIMEOUT`, `ENABLE_API_DOCS` |
| cache-api | `REDIS_URL`, `CLIENT_API_URL`, `UPSTREAM_TIMEOUT`, `CACHE_TTL_LIST/SEARCH/DETAIL/STATS`, `CACHE_KEY_PREFIX`, `CORS_ORIGINS` |
| jwt (Login API) | `JWT_SECRET`, `DATABASE_PATH`, `SESSION_TIMEOUT_HOURS`, `CORS_ORIGINS`, `NOTIFICATIONS_API_URL`, `INTERNAL_API_KEY`, `EMAIL_FROM`, `SMTP_*`, `LOGIN_WINDOW_SECONDS`, `LOGIN_MAX_FAILURES_PER_ACCOUNT`, `LOGIN_MAX_FAILURES_PER_IP`, `RESET_CODE_MINUTES`, `RESET_CODE_CLEANUP_INTERVAL_SECONDS`, `ENABLE_API_DOCS` |
| Signup-api | `DATABASE_PATH`, `JWT_SECRET`, `JWT_ALGORITHM`, `CORS_ORIGINS`, `EMAIL_CONFIRMATION_URL`, `LOGIN_URL`, `EMAIL_FROM`, `SMTP_*`, `VERIFICATION_TOKEN_EXPIRE_MINUTES`, `NOTIFICATIONS_API_URL`, `INTERNAL_API_KEY`, `AGENT_API_URL`, `ACCOUNT_DELETION_KEY`, `RATE_LIMIT_*`, `ACCOUNT_JOBS_INTERVAL_SECONDS`, `DEACTIVATED_ACCOUNT_RETENTION_DAYS`, `DELETION_WARNING_DAYS`, `ENABLE_API_DOCS` |
| tender_apis (Notifications) | `DATABASE_PATH`, `JWT_SECRET`, `JWT_ALGORITHM`, `INTERNAL_API_KEY`, `APP_URL`, `PUBLIC_API_URL`, `EMAIL_FROM`, `SMTP_*`, `CORS_ORIGINS`, `ENABLE_SCHEDULER`, `NOTIFY_INTERVAL_MINUTES`, `MATCH_MIN_SCORE`, `NOTIFICATION_RETENTION_DAYS`, `UNSUBSCRIBE_LINK_DAYS`, `ENABLE_API_DOCS` |
| tender-ai-agent | see [tender-ai-agent/.env.example](tender-ai-agent/.env.example) (Azure AI, embeddings, upstream URLs, Redis, caches, sync, data dir, CORS, keys) |
| tender-ml | `DATABASE_PATH`, `MODEL_PATH`, `REPORTS_DIR` |
| tender-scrapping-database scraper-api | `DATABASE_PATH`, `API_KEY`, `CORS_ORIGINS`, `ETENDERS_*`, `SCRAPER_LOOP_*` |
| tender-scrapping-database client-api | `DATABASE_PATH`, `CORS_ORIGINS` |
| tender-scrapping-database ai | `DATABASE_PATH`, `OLLAMA_BASE_URL`, `AI_MODEL`, `AI_REQUEST_TIMEOUT_SECONDS`, `AI_SERVICE_API_KEY`, `CLIENT_API_URL`, `TENDER_ML_URL`, `TENDER_ML_TIMEOUT`, `EMBED_MODEL`, `EMBED_TIMEOUT_SECONDS`, `CORS_ORIGINS`, `ENABLE_API_DOCS` |
| frontend, tender-ai-frontend | start-up variables above |
