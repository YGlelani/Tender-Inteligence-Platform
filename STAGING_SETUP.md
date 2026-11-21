# Staging setup

Staging runs the whole Tender-Intelligence platform from this repository as one Docker
Compose project, `tender-staging`, defined in [compose.staging.yaml](compose.staging.yaml).
It can run on your own machine or on the production server next to production, because it
shares nothing with production.

## What keeps staging away from production

| Concern | Production (per-service compose files, unchanged) | Staging (`compose.staging.yaml`) |
|---|---|---|
| Container names | fixed: `tender-client-api`, `jwt-api`, `tender-agent-api`, ... | none fixed: `tender-staging-<service>-1` |
| Network | `tender-scrapping-net` (external) | `tender-staging_net`, created by Compose |
| SQLite (`tenders.db`) | volume `tender-scrapping_tender-sqlite-data` | volume `tender-staging_sqlite-data`, starts empty |
| AI service database (`ai.db`) | `tender-scrapping_ai-data` | `tender-staging_ai-data` |
| Agent documents | `tender-ai-agent_agent-data` | `tender-staging_agent-data` |
| ML models | `tender-ml-models` volume | `tender-staging_ml-models` |
| Redis | `tender-redis`, host port 6379 | own `redis` service, no host port, key prefix `staging` |
| Ollama | `tender-ollama`, host port 11434 | own `ollama` service, no host port, own model volume |
| Image tags | `tender-frontend:latest`, `ghcr.io/yglelani/...:latest` | `tender-staging/<service>:staging` |
| Host ports | 8000-8009, 9000-9009 | 18000-18009, 19000-19007 |
| Settings | `.env` files per service folder, GitHub secrets | `.env.staging` with `STAGING_*` names only; no `env_file` |
| Addresses between services | container names on `tender-scrapping-net` | pinned to staging service names; not configurable |

`scripts/staging/check_staging.py` checks every row of this table and fails if anything
could reach production. It runs in CI on every branch and before every staging deploy.

Staging never copies production data. The scraper fills the empty staging database from
the public eTenders site; accounts are created by signing up on the staging site.

## Services and ports

| Service (folder) | Staging host port | In-network address | Notes |
|---|---|---|---|
| Main site (`frontend`) | 18009 | `frontend:80` | Production: `USER_SERVER_PORT` (8009) |
| AI workspace (`tender-ai-frontend`) | 19001 | `tender-ai-frontend:80` | |
| Scraper API (`services/tender-scrapping-database/scraper-api`) | 18000 | `scraper-api:8000` | |
| Client API (`services/tender-scrapping-database/client-api`) | 18001 | `client-api:8001` | Creates the schema (`db/schema.sql`) on first start |
| AI service (`services/tender-scrapping-database/ai`) | none | `ai:8002` | Not published, as in production |
| Cache API (`services/cache-api`) | 18003 | `cache-api:8003` (alias `lelani-cache-api`) | |
| Login API (`jwt`) | 18006 | `jwt-api:8006` | Signs in against the staging `tenders.db` |
| Signup API (`services/Signup-api`) | 18007 | `signup-api:8000` | |
| Notifications API (`services/tender_apis`) | 19007 | `tender-notifications-api:8000` | |
| Alerts API (`services/alerts-api`) | 19005 | `alerts-api:9005` | |
| Tender ML (`services/tender-ml`) | 127.0.0.1:19004 | `tender-ml:9004` | This machine only |
| AI agent (`services/tender-ai-agent`) | 19000 | `tender-agent-api:9000` (alias `agent-api`) | |
| Redis, Ollama | none | `redis:6379`, `ollama:11434` | |

Every port can be changed with its `STAGING_*_PORT` setting ([ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)).
The browser sites learn the staging ports at container start (see "How the sites find the staging APIs").

## Run staging on your own machine

Needs Docker with Compose v2 and about 10 GB of free disk (the scraper image includes
Playwright browsers; the Ollama model is several GB).

1. Create the settings file and fill it in. (In this workspace `.env.staging` already
   exists with `USER_SERVER_IP=localhost` and newly generated staging secrets; only the
   optional Azure and SMTP values are empty.)

   ```bash
   cp .env.staging.example .env.staging
   ```

   - `USER_SERVER_IP=localhost`
   - each of `STAGING_JWT_SECRET`, `STAGING_INTERNAL_API_KEY`, `STAGING_ACCOUNT_DELETION_KEY`,
     `STAGING_AI_SERVICE_API_KEY`, `STAGING_SCRAPER_API_KEY`: a new value from `openssl rand -hex 32`
     (PowerShell: `-join ((1..32) | % { '{0:x2}' -f (Get-Random -Max 256) })`)
   - optional: the `STAGING_AZURE_*` keys (AI chat) and `STAGING_SMTP_*` (e-mails), from
     staging/test accounts, never the production ones

2. Check the settings and the isolation (needs `pip install pyyaml`):

   ```bash
   python scripts/staging/check_staging.py --env-file .env.staging
   docker compose --env-file .env.staging -f compose.staging.yaml config --quiet
   ```

3. Build and start:

   ```bash
   docker compose --env-file .env.staging -f compose.staging.yaml up -d --build --wait
   ```

4. First run only - download the AI model into the staging Ollama volume, and train the
   category model once the scraper has collected tenders (a few minutes after start):

   ```bash
   docker compose --env-file .env.staging -f compose.staging.yaml exec ollama ollama pull llama3.1:8b
   docker compose --env-file .env.staging -f compose.staging.yaml run --rm tender-ml python train.py
   docker compose --env-file .env.staging -f compose.staging.yaml restart tender-ml
   ```

5. Smoke test, then open the sites:

   ```bash
   bash scripts/staging/smoke_test.sh .env.staging
   ```

   - Main site: http://localhost:18009
   - AI workspace: http://localhost:19001

Tip: `export COMPOSE_FILE=compose.staging.yaml` (PowerShell: `$env:COMPOSE_FILE='compose.staging.yaml'`)
saves typing `-f compose.staging.yaml`. Keep `--env-file .env.staging` on every command:
Compose needs the required values even for `ps` and `logs`.

### Everyday commands

```bash
docker compose --env-file .env.staging -f compose.staging.yaml ps
docker compose --env-file .env.staging -f compose.staging.yaml logs -f signup-api
docker compose --env-file .env.staging -f compose.staging.yaml up -d --build alerts-api   # rebuild one service
docker compose --env-file .env.staging -f compose.staging.yaml down                       # stop, keep staging data
docker compose --env-file .env.staging -f compose.staging.yaml down -v                    # stop AND delete staging data
```

`down -v` only removes volumes of the `tender-staging` project. Never run `down -v` with a
production compose file.

## Deploy staging from GitHub

Pushing to the `staging` branch runs [.github/workflows/deploy-staging.yml](.github/workflows/deploy-staging.yml):
full build and test suite, then on the staging runner it writes `.env.staging` from the
`staging` environment's secrets, runs `check_staging.py`, starts the stack, pulls the
Ollama model, trains the ML model and runs the smoke test. Setup: [DEPLOYMENT.md](DEPLOYMENT.md).

## How the sites find the staging APIs

The browser pages call the APIs on `USER_SERVER_IP` (or the host name in the address bar)
plus a port. Production ports are built into the code; staging overrides them at start-up:

- `frontend`: `docker-entrypoint.d/40-runtime-config.sh` turns `USER_SERVER_IP` and
  `FRONTEND_SERVICE_PORTS` into `scripts/runtime-config.js` (`window.APP_CONFIG`), which
  `scripts/config.js`, `script.js`, `scripts/forgot-password.js` and `scripts/navigation.js` read.
- `tender-ai-frontend`: the same script turns `AGENT_URL`, `LOGIN_URL` and `MAIN_SITE_PORT`
  into `scripts/runtime-config.js` and allows the staging agent address in the
  Content-Security-Policy.

Production sets none of these variables, so its containers write an empty configuration and
the pages behave exactly as before. `check_staging.py` fails if any service in `scripts/config.js`
is missing from `FRONTEND_SERVICE_PORTS` (it would otherwise call a production port).

## Deployment notes

1. **Signup verification page**: the signup API links to `STAGING_SIGNUP_FRONTEND_PORT` (18008
   by default). This site must be deployed separately and configured to use this staging API.
2. **Cache API source**: production runs the image `ghcr.io/yglelani/lelani-cache-api:latest`,
   built from another repository. Staging builds `services/cache-api/` from this repository; confirm
   the two are the same code.
3. **E-mail**: the Signup, Login and Notifications APIs need STARTTLS or SMTPS with a valid
   certificate and a username/password, so a local catcher such as Mailpit does not work
   without code changes. Use a sandbox SMTP account for staging.
4. **Memory**: on a shared server, staging's Ollama adds roughly 5 GB while a model is loaded
   (`llama3.1:8b`). `STAGING_OLLAMA_KEEP_ALIVE=5m` unloads it when idle; `STAGING_AI_MODEL=llama3.2:3b`
   is lighter.

## Troubleshooting

- `required variable STAGING_... is missing a value`: add it to `.env.staging`.
- `port is already allocated`: another program uses that port; change the `STAGING_*_PORT` setting.
- `40-runtime-config: ...` and the site container restarts: `USER_SERVER_IP` or a port setting
  has an invalid value; the message names it.
- Agent `/health` says `degraded`: Azure AI settings are empty or wrong (staging still runs).
- Tender ML `/health` fails: no model trained yet (step 4).
