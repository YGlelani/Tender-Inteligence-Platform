# Tender-Inteligence-Platform

All Tender-Intelligence (Tender Scrapper) services in one repository, with a shared
build-and-test pipeline, a fully isolated staging environment and an approval-gated
production release.

## Services

| Folder | What it is | Tech | Production port |
|---|---|---|---|
| [frontend](frontend) | Main site (dashboard, search, alerts, profile, tracker) | static HTML/JS on nginx | 8009 (`USER_SERVER_PORT`) |
| [tender-ai-frontend](tender-ai-frontend) | AI workspace (chat, matches, bid strategy) | static HTML/JS on nginx | 9001 |
| [tender-scrapping-database](tender-scrapping-database) | Scraper API, Client API, AI service, Ollama, Redis, cache | FastAPI, Playwright, SQLite | 8000, 8001, 8003 (8002 internal) |
| [cache-api](cache-api) | Redis read-through cache in front of the Client API | FastAPI, Redis | 8003 |
| [jwt](jwt) | Login API (sign-in tokens) | FastAPI | 8006 |
| [Signup-api](Signup-api) | Sign-up, e-mail verification, account settings | FastAPI, SQLite | 8007 |
| [tender_apis](tender_apis) | Notifications API (bell + e-mail) | FastAPI, SQLite | 9007 |
| [alerts-api](alerts-api) | Smart alerts / profile-based tender matching | FastAPI, SQLite | 9005 |
| [tender-ml](tender-ml) | Tender category model | scikit-learn, FastAPI | 9004 |
| [tender-ai-agent](tender-ai-agent) | AI agent (chat, documents, semantic search) | FastAPI, LangGraph, Azure AI, Redis | 9000 |

Most APIs share one SQLite database (`/data/tenders.db`) on a shared Docker volume and reach
each other by container name on one Docker network. Browsers call the APIs directly on
their ports.

## Environments

| Branch | Runs | Environment |
|---|---|---|
| `dev` | build + basic tests | - |
| `testing` | build + full tests + integration test | - |
| `staging` | build + full tests, then deploy | staging (`compose.staging.yaml`) |
| `prod` | staging check + full tests + **manual approval**, then deploy | production |
| `main` | build + full tests | stable source |

- [STAGING_SETUP.md](STAGING_SETUP.md): run staging locally or on a server, and how it is kept apart from production
- [DEPLOYMENT.md](DEPLOYMENT.md): branch flow, workflows, GitHub setup, promoting a release, known issues
- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md): every setting and GitHub secret

## Quick start (staging on your machine)

```bash
cp .env.staging.example .env.staging          # then fill in USER_SERVER_IP=localhost and the five secrets
python scripts/staging/check_staging.py --env-file .env.staging
docker compose --env-file .env.staging -f compose.staging.yaml up -d --build --wait
bash scripts/staging/smoke_test.sh .env.staging
```

Main site: http://localhost:18009 - AI workspace: http://localhost:19001
