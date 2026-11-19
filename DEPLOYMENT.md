# Deployment

How code moves from development to production in this repository, what each GitHub
Actions workflow does, and what has to be configured on GitHub and on the servers.

## Branch flow

```text
dev ──> testing ──> staging ──> prod ──> main
```

| Branch | Purpose | What runs on push | Deploys |
|---|---|---|---|
| `dev` | Active development | [ci.yml](.github/workflows/ci.yml), basic suite | nothing |
| `testing` | Automated and integration testing | [ci.yml](.github/workflows/ci.yml), full suite | nothing |
| `staging` | Pre-production | [deploy-staging.yml](.github/workflows/deploy-staging.yml): full suite, then deploy | staging stack |
| `prod` | Approved production release | [deploy-production.yml](.github/workflows/deploy-production.yml): staging check, full suite, approval, deploy | production (when switched on) |
| `main` | Stable source | [ci.yml](.github/workflows/ci.yml), full suite | nothing |

Pull requests into any of the five branches run the basic suite (into `dev`) or the full
suite (into the others). All suites are defined once, in
[build-and-test.yml](.github/workflows/build-and-test.yml):

- **basic**: staging isolation check, Compose validation (staging and all production files),
  shellcheck, every service's unit tests, frontend smoke tests and JavaScript syntax, and a
  Docker build of every image.
- **full**: basic plus `pip-audit` of the Python dependencies and an integration test: the
  whole staging stack is started on the GitHub runner with random throwaway secrets and
  probed by `scripts/staging/smoke_test.sh`.

A failed test stops the workflow; the deploy jobs `need` the test jobs.

### Promoting a release

1. Feature branches merge into `dev` (pull request, basic suite).
2. `dev` -> `testing` pull request. The full suite and integration test run.
3. `testing` -> `staging` pull request. On merge, staging is deployed automatically. Check it.
4. `staging` -> `prod` pull request. Use **Create a merge commit** (or fast-forward), not
   squash: the production workflow rejects any non-merge commit on `prod` that is not on
   `staging`, so only what was tested on staging can be released. After the tests, a
   required reviewer approves the `production` environment in the Actions run; only then
   does the deploy job start.
5. `prod` -> `main` pull request, so `main` holds the released source.

Hotfix: branch from `prod`, merge into `staging` first, verify, then promote `staging` -> `prod`
as usual, and merge back into `dev`.

Nothing deploys production from `staging`, and a manual run of a deploy workflow from any
other branch skips the deploy job.

## Branch audit (19 November 2026)

Read from local clones only (remote branches as of each clone's last fetch); nothing was
created, merged or pushed.

| Repository | Local branches | Remote branches of the five | Default | Production deploys from |
|---|---|---|---|---|
| **Tender-Inteligence-Platform** (this repo) | `main` | `main` only | `main` | nothing yet |
| tender-ai-agent | `main` + feature/fix branches | `dev`, `testing`, `staging`, `prod`, `main` | `main` | `main` |
| tender_scrapping (Ace-The-Academia) | `main` | `dev`, `testing`, `staging`, `prod`, `main` | `main` | no deploy workflow found |
| alerts-api | `main` + feature/fix | `main` | `main` | `main` |
| Signup-api | `main` + feature/fix (`test-environment` on remote) | `main` | `main` | `main` |
| frontend | `main` + feature/fix (`baloyi-dev` on remote) | `main` | `main` | `main` |
| tender_apis | `main` + `Feature/*` per API | `main` | `main` | `Feature/notifications-api` (notifications) |
| tender-ai-frontend | `main` + fix branches | `main` | `main` | `main` |
| tender-ml | `main` | `main` | `main` | `main` |
| tender-scrapping-database | `main` + feature/fix (`develop` on remote) | `main` | `main` | `main` |
| musiwalo-jwt-api (source of `jwt/`) | `main` + feature/fix | `main` | `main` | `main` |

**Action:** create `dev`, `testing`, `staging` and `prod` in this repository from `main`
(GitHub: Branches -> New branch). The workflows already reference them.

How this repository relates to the service repositories: each folder here is identical,
file by file, to its service repository's `main` as last fetched (commits of 16-18 November
2026), except `tender_apis/`, which matches the `Feature/notifications-api` branch.
`jwt/` was brought up to date with `musiwalo-jwt-api` `main` (commit `cabf759`) on
19 November 2026; it used to be the older PostgreSQL version. `cache-api/` has no local
clone of its source repository to compare with. The `.github/workflows` folders
inside the service folders are those repositories' own workflows; GitHub does not run
workflows from subfolders, so in this repository only the root `.github/workflows` run.

## GitHub configuration

### Environments (Settings -> Environments)

| Environment | Protection | Deployment branches |
|---|---|---|
| `staging` | none needed | `staging` only |
| `production` | **Required reviewers** (the manual approval); optionally "Prevent self-review" | `prod` only |

Required reviewers on a private repository need a paid GitHub plan (Team or Enterprise);
on GitHub Free they are available for public repositories only.

Store secrets **in the environments, not as repository secrets**, so a staging job can never
read a production secret. Staging uses `STAGING_*` names only.

Secrets and variables for each environment are listed in
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md#github-secrets-and-variables).

### Self-hosted runners (Settings -> Actions -> Runners)

| Label | Used by | Needs |
|---|---|---|
| `self-hosted`, `staging` | deploy-staging.yml | Docker Engine + Compose v2, `curl`, outbound HTTPS |
| `self-hosted`, `production` | deploy-production.yml | the production server's Docker, `curl`, `git`; same user that owns today's containers |

The staging runner may be the production server (staging is isolated by name, port,
network and volume) or a separate machine. Add the label when registering the runner
(`./config.sh --labels staging`) or later in the runner's settings.

### Branch protection (Settings -> Branches)

For `testing`, `staging`, `prod` and `main`: require a pull request and require the status
checks of the "Build and test" jobs to pass. For `prod`, also restrict who can push.

## Production deployment from this repository

Production is deployed today by the workflows in the individual service repositories.
[deploy-production.yml](.github/workflows/deploy-production.yml) can take over, one
service at a time, using the **existing production Compose files unchanged** and the same
`.env` contents those workflows write ([scripts/deploy/deploy_production.sh](scripts/deploy/deploy_production.sh)).

It is **switched off** until you set the repository variable `PRODUCTION_DEPLOY_ENABLED=true`.
While it is off, a push to `prod` still runs the staging check and full test suite and then
stops with a notice.

Before switching it on:

1. On the production server run `docker compose ls` and compare the project names with the
   defaults in `deploy_production.sh` (`musiwalo-jwt-api`, `signup-api`, `tender_apis`,
   `deploy-src` for both alerts-api and tender-ml; `tender-scrapping`, `tender-ai-agent`,
   `tender-ai-frontend` and `tender-frontend` come from the compose files). Set
   `PROJECT_LOGIN_API`, `PROJECT_SIGNUP_API`, `PROJECT_NOTIFICATIONS_API`, `PROJECT_ALERTS_API`,
   `PROJECT_TENDER_ML` variables if they differ; otherwise Docker refuses to create containers
   whose names another project owns.
2. Add the production secrets to the `production` environment (names in
   [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md#production-environment)).
3. Set `PRODUCTION_SERVICES` to the services to take over, for example `frontend tender-ai-frontend`,
   and disable the deploy workflow of the same service in its own repository, so two
   pipelines never deploy the same containers.
4. Push to `prod`, approve, and watch the health checks.

`cache-api` is refused by the script: production runs `ghcr.io/yglelani/lelani-cache-api`,
built from another repository.

Rollback: revert the commit on `staging`, promote to `prod` again (the deploy rebuilds from
the reverted source). Data volumes are never removed by these workflows.

## Known issues found during the audit

| # | Issue | Risk | What to do |
|---|---|---|---|
| 1 | The old `jwt/main.py` and `jwt/test_db.py` contained a hard-coded **production PostgreSQL address and password**; `test_db.py` connected to that server whenever `pytest` collected it. | The password is still in this repository's Git history (initial commit), which is on GitHub | **Fixed in the files** (jwt/ updated, see 2). Still to do: rotate that PostgreSQL password, or drop the PostgreSQL server if nothing uses it since the SQLite migration. Removing it from history needs a history rewrite and force-push. |
| 2 | `jwt/` was older than `musiwalo-jwt-api` `main` (PostgreSQL vs SQLite login). | Staging sign-in failed; deploying it would have broken production sign-in | **Fixed**: `jwt/` now matches `musiwalo-jwt-api` `main`; `deploy_production.sh` deploys it like its own workflow. |
| 3 | `jwt/__pycache__/*.pyc` were committed. | Stale bytecode in the image | **Fixed**: deleted (shows as deleted in `git status`); `.gitignore` keeps them out. |
| 4 | `jwt`, `alerts-api` and `tender-scrapping-database/ai` had no `.dockerignore`, and their Dockerfiles copy the whole folder, so a `.env` there was baked into the image. | Secrets inside image layers | **Fixed**: `.dockerignore` files exclude `.env`, caches and local databases. Containers still get the values from Compose. |
| 5 | `cache-api/.github/workflows/build.yml` built `ghcr.io/<owner>/ cache-api` (a space in the image name). Its deploy step also pulls a service named `cache-api`, while production's compose file calls it `lelani-cache-api`. | That workflow fails | Space **fixed** in this repository's copy. The service-name mismatch is left as is: production's cache image comes from another repository. |
| 6 | Production publishes Redis (6379) and Ollama (11434) on all interfaces; production compose defaults hard-code the server IP in `CORS_ORIGINS`. | Unauthenticated access from the internet if the firewall allows it | Remove those `ports:` or bind them to `127.0.0.1`; pass `CORS_ORIGINS` explicitly. Not changed here, to keep production untouched. |
| 7 | `tender_apis` holds each API on its own branch; only the Notifications API is in this repository. | Overview, Saved Tenders, Tracker and Search APIs cannot be tested in staging | Add them as folders here, then to `compose.staging.yaml`. |
