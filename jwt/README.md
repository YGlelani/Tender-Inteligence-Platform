# TenderScraping — Frontend Dashboard

The web dashboard for the TenderScraping platform. It visualises scraped
public-tender data: headline KPIs, a volume pipeline chart, breakdowns by
province and category, the last scrape status, a searchable/paginated tender
feed, and a per-tender detail page.

This is a **static front end** (plain HTML, CSS and vanilla JavaScript ES
modules) served by **nginx** inside a **Docker** container. It has no build
step — the files you see are the files that ship.

> This repository is **only the dashboard** (served on port `8009`). Login
> (`8005`) and signup (`8008`) are deployed separately and are not part of this
> repo. The dashboard talks to five backend microservices over HTTP (see
> [Architecture](#architecture)).

---

## Table of contents

- [Live URLs](#live-urls)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Running locally](#running-locally)
- [Deploying on the server](#deploying-on-the-server)
- [CI/CD](#cicd)
- [Health checks & verification](#health-checks--verification)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Roadmap / nice-to-haves](#roadmap--nice-to-haves)

---

## Live URLs

| App         | URL                              | In this repo? |
|-------------|----------------------------------|---------------|
| Dashboard   | `http://129.151.181.87:8009/`    | ✅ yes        |
| Login       | `http://129.151.181.87:8005/`    | ❌ separate   |
| Signup      | `http://129.151.181.87:8008/`    | ❌ separate   |

---

## Architecture

The browser loads the static dashboard from nginx (`:8009`) and then calls the
backend services **directly** from JavaScript. All services live on the same
host (`129.151.181.87`) on different ports.

```
                         ┌─────────────────────────────┐
   Browser ──HTTP GET──▶ │  nginx (Docker)  :8009       │  static HTML/CSS/JS
                         └─────────────────────────────┘
        │
        │  fetch() calls (cross-origin, from the browser)
        ▼
   ┌───────────────────────── backend services (129.151.181.87) ─────────────────────────┐
   │  :8000  scraper   health / stats / scrape / scraping-logs                            │
   │  :8001  client    tenders list / search / detail / stats                             │
   │  :8002  ollama     AI generate / analyse / match / business-profiles                 │
   │  :8003  cache     cached tenders / search / stats / clear   (preferred, with fallback)│
   │  :8007  signup    signup / health                                                    │
   └──────────────────────────────────────────────────────────────────────────────────────┘
```

Key behaviours:

- **Cache-first with fallback.** The feed and overview try the cache service
  (`:8003`) first and fall back to the client service (`:8001`) if the cache is
  unavailable. See `scripts/overview.js` and `scripts/feed.js`.
- **Defensive field mapping.** The UI accepts multiple field-name shapes from
  the backend (e.g. `total_tenders` / `totalTenders` / `total`) so minor API
  differences don't break rendering.
- **Auto-refresh.** KPIs refresh every 30s and the scrape status every 15s
  (`scripts/config.js` → `refresh`).
- **Request timeout.** Every API call is aborted after 15s (`requestTimeout`).

### Pages

| Page          | File          | Script                | Purpose                                   |
|---------------|---------------|-----------------------|-------------------------------------------|
| Overview      | `index.html`  | `scripts/overview.js` | KPIs, volume chart, province/category, scrape status |
| Tender Feed   | `feed.html`   | `scripts/feed.js`     | Search + paginated list of tenders        |
| Tender Detail | `tender.html` | `scripts/tender.js`   | Full detail + documents for one tender    |

---

## Project structure

```
.
├── index.html              # Overview dashboard
├── feed.html               # Tender feed (search + pagination)
├── tender.html             # Tender detail page
├── css/
│   └── styles.css          # All styling
├── scripts/
│   ├── config.js           # Service URLs, endpoints, timeouts  ← edit to repoint backends
│   ├── api.js              # Thin fetch wrappers per service
│   ├── main.js             # Overview entry point
│   ├── overview.js         # Overview page logic
│   ├── feed.js             # Feed page logic
│   ├── tender.js           # Detail page logic
│   ├── chart.js            # SVG volume chart renderer
│   ├── state.js            # (unused) tiny store helper — safe to remove
│   └── script.js           # (unused) old demo chart data — safe to remove
├── nginx.conf              # Hardened nginx server block (gzip, cache, /healthz)
├── Dockerfile              # Builds the nginx image
├── compose.yaml            # Runs the container on :8009 with a healthcheck
├── .dockerignore           # Keeps git/docs/CI out of the image
└── .github/workflows/
    ├── ci.yml              # Validation: build + smoke test (no deploy)
    └── deploy.yml          # Deploy: compose up on the self-hosted runner
```

> `scripts/state.js` and `scripts/script.js` are **not imported anywhere** and
> can be deleted. They're left in place for now to avoid touching anything
> during deployment week.

---

## Configuration

All runtime configuration lives in **`scripts/config.js`**. There is no
environment-variable layer — the service URLs are baked into this file and
served as-is to the browser.

```js
export const CONFIG = {
  services: {
    scraper: 'http://129.151.181.87:8000',
    client:  'http://129.151.181.87:8001',
    ollama:  'http://129.151.181.87:8002',
    cache:   'http://129.151.181.87:8003',
    signup:  'http://129.151.181.87:8007',
  },
  // ...endpoints, refresh intervals, requestTimeout
};
```

**To point the dashboard at different backends** (new IP, new ports, or a
domain), edit the `services` block and redeploy. Because this is loaded by the
browser, the URLs must be reachable **from the user's machine**, not just from
the server.

---

## Running locally

The site uses ES modules and `fetch`, so you can't open `index.html` from the
file system (`file://`) — you need a local HTTP server.

**Option A — Docker (closest to production):**

```bash
docker compose up -d --build
# open http://localhost:8009
```

**Option B — any static server:**

```bash
# Python 3
python -m http.server 8080
# then open http://localhost:8080

# or Node
npx serve .
```

Note: the backends in `config.js` point at the live server IP. Running the UI
locally will still call those remote services, so the data you see is live
(assuming the services allow cross-origin requests from your origin).

---

## Deploying on the server

The target is a Docker host reachable at `129.151.181.87`, serving the
dashboard on port **8009**. The group requirement is to deploy on the server
(not GitHub Pages / Vercel) and share `public_ip:port`.

### One-time server setup

```bash
# Docker Engine + compose plugin (Ubuntu/Debian example)
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker

# allow the port through the firewall (if ufw is used)
sudo ufw allow 8009/tcp
```

> Cloud VMs (Oracle/AWS/etc.) usually have a **security list / security group**
> in addition to the OS firewall. Make sure port **8009** is open there too, or
> the page will be unreachable even though the container is healthy.

### Deploy / redeploy

```bash
git clone <repo-url> tender-frontend   # first time only
cd tender-frontend
git pull                               # on subsequent deploys

docker compose up -d --build
```

`up -d --build` rebuilds the image and recreates the container only if
something changed, so there's minimal downtime. Then visit
`http://129.151.181.87:8009/`.

### Automated deploy

If the self-hosted GitHub Actions runner is active on the server, **pushing to
`main` deploys automatically** — see [CI/CD](#cicd). The manual commands above
are the fallback if the runner is down.

---

## CI/CD

Two GitHub Actions workflows run on the **self-hosted runner** (the server
itself):

| Workflow        | Trigger                         | What it does                                              |
|-----------------|---------------------------------|-----------------------------------------------------------|
| `ci.yml`        | Pull request to `main`, manual  | Builds the image and smoke-tests it on a throwaway port (`18009`), then cleans up. **Never touches the live container.** |
| `deploy.yml`    | Push to `main`, manual          | `docker compose up -d --build`, then polls `/healthz` on `:8009` up to ~30s. Prints logs if it fails. |

Why two: previously `ci.yml` and `deploy.yml` were **identical** and both
deployed on push to `main` — two concurrent `docker compose` runs racing each
other. Now validation and deployment are separated, and `deploy.yml` uses a
`concurrency` group so overlapping pushes can't deploy simultaneously.

---

## Health checks & verification

The container exposes a lightweight `GET /healthz` that returns `200 ok`
(defined in `nginx.conf`). Both the Docker `HEALTHCHECK` and the compose
healthcheck use it.

```bash
# container state (look for "healthy")
docker compose ps

# from the server
curl -I http://localhost:8009/           # page loads
curl    http://localhost:8009/healthz    # -> ok

# from anywhere
curl -I http://129.151.181.87:8009/
```

---

## Troubleshooting

**Page loads but all tiles show `—` / "unavailable".**
The static site is fine but the backend calls are failing. Open the browser
dev-tools Network tab:

- **CORS error** — the backend must send
  `Access-Control-Allow-Origin` for the dashboard's origin
  (`http://129.151.181.87:8009`). This is a backend-side fix.
- **Mixed content (blocked)** — happens only if the page is served over
  **HTTPS** while the APIs are plain `http://`. Currently everything is HTTP, so
  this shouldn't occur; if you add TLS to the dashboard, you must also serve the
  APIs over HTTPS (or proxy them). See the roadmap.
- **Connection refused / timeout** — the backend service or its port is down.
  Check the service and that its port is open in the firewall / security group.

**Page unreachable from outside, but `curl localhost:8009` works on the server.**
The OS firewall and/or cloud security group is blocking `8009`. Open it in both.

**Container keeps restarting / unhealthy.**
`docker compose logs --tail=50`. A common cause is a typo in `nginx.conf`;
`docker exec <container> nginx -t` validates the config.

**I changed a file but don't see the update.**
HTML is served `no-cache`, but static assets (`.js`, `.css`) are cached for 7
days by the browser. Hard-refresh (Ctrl/Cmd+Shift+R), or redeploy — the content
hash changes aren't automatic here.

---

## Security notes

Current state (fine for a demo, **not** production):

- **No authentication** on the dashboard or the backend services. Anything at
  `public_ip:port` is open to the internet.
- **Plain HTTP** everywhere — traffic is unencrypted.
- Backend ports (`8000`–`8007`) are exposed directly to the browser, so each
  must be individually reachable and CORS-enabled.

See the roadmap for how to tighten this.

---

## Roadmap / nice-to-haves

These are **optional** improvements, deliberately not done during deploy week to
avoid breaking the live setup:

1. **Reverse-proxy the APIs through this nginx.** Serve the site and proxy
   `/api/scraper/*`, `/api/client/*`, etc. to the backend services. Benefits:
   one origin (no CORS), one open port, and no mixed-content problem if TLS is
   added. `config.js` would then use relative paths instead of a hard-coded IP.
2. **HTTPS.** Put [Caddy](https://caddyserver.com/) in front (automatic Let's
   Encrypt) or add nginx + certbot — needs a domain name.
3. **Runtime config.** Inject the backend base URL at container start instead of
   baking it into `config.js`, so the same image works across environments.
4. **Remove dead code.** Delete `scripts/state.js` and `scripts/script.js`.
5. **Add auth** in front of the dashboard and services.
