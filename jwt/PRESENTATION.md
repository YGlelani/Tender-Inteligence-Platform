# Historical deployment note

This presentation includes the former single-host deployment model. Use the repository-root `docs/` deployment guides for current development, staging, and production configuration.

# TenderScraping Dashboard — Presentation Prep

A speaker's guide for presenting the frontend dashboard. Read this once before
you present, then keep the [Demo script](#4-live-demo-script-5-7-min) and
[Q&A prep](#7-qa-prep-anticipated-questions) open on a second screen.

**Timing suggestion (12–15 min):** pitch 1 · problem 1 · architecture 3 ·
demo 6 · deployment 2 · challenges 1 · Q&A.

---

## 1. Elevator pitch (30 seconds)

> "Public tenders are scattered across government sites, published daily, and
> painful to track. We built a platform that **scrapes** those tenders,
> **stores and caches** them, and surfaces them through a **live dashboard** —
> KPIs, trends, a searchable feed, and full tender detail with downloadable
> documents. There's also an AI service that can analyse a tender and match it
> to a business profile."

What you're demoing today is the **dashboard** — the window into all of that.

---

## 2. The problem & our solution (1 min)

- **Problem:** tender information is high-volume, time-sensitive (closing
  dates!), and fragmented. Businesses miss opportunities because tracking is
  manual.
- **Solution:** an automated pipeline (scraper → store → cache) with a clean
  dashboard on top. Users see what's open, what's closing this week/month,
  where tenders are concentrated (province/category), and can drill into any
  single tender.

---

## 3. Architecture walkthrough (talking points)

Draw/show this and talk to it:

```
Browser ──▶ nginx (:8009, this app)  ── static HTML/CSS/JS
   │
   └── fetch() ──▶ scraper :8000   (scrape + logs + stats)
                  client  :8001   (tenders list / search / detail)
                  ollama  :8002   (AI analyse / match)
                  cache   :8003   (fast reads, preferred)
                  signup  :8007   (account creation)

Separate apps:   login :8005      signup UI :8008
```

Points worth making (shows you understand it, not just that it runs):

- **It's a static front end** — no framework, no build step. Plain ES modules.
  That keeps it tiny, fast, and trivial to deploy as an nginx container.
- **Cache-first strategy.** The UI hits the cache service first and falls back
  to the main client service automatically, so the dashboard stays responsive
  and survives a cache outage.
- **Resilient rendering.** We map several possible field names from the API, so
  small backend changes don't blank out the UI. Failed calls degrade to "—"
  instead of crashing (`Promise.allSettled`, per-call try/catch).
- **Separation of concerns:** `config.js` (what to call) → `api.js` (how to
  call) → page scripts (what to show). One place to change a URL.

---

## 4. Live demo script (5–7 min)

Have `http://your-deployment-host:8009/` open and the backends running first.
**Pre-flight:** load the page once before presenting so assets are warm.

1. **Overview page.**
   - Point out the four KPIs (Total / Open / Closing this week / Closing this
     month). "These update automatically every 30 seconds."
   - Volume chart — switch **7D / 30D / 90D** to show the range toggle.
   - Province and Category breakdowns — "top three plus an 'Other' rollup."
   - Last Scrape Status — "this reflects the most recent scraper run; it polls
     every 15 seconds."

2. **Tender Feed** (click *Tender Feed*).
   - Type a keyword in the search box — "search is debounced, and it queries the
     cache service with a fallback to the client service."
   - Change **Per page**, use **Prev/Next** to show pagination.
   - "The count shows exactly which records we're viewing out of the total."

3. **Tender Detail** (click **Open →** on any card).
   - Walk through organisation, province, category, published/closing dates,
     contact (note the live `mailto:` link).
   - Show the **Documents** list — "these open the original tender attachments
     in a new tab."
   - Use **← Back to feed** to return.

4. **Resilience moment (optional, impressive).** Open dev-tools → Network, show
   a successful call, and mention: "if a service is down, that tile shows a dash
   instead of taking the whole page down."

**Fallback if the live demo fails:** have screenshots ready, and show
`docker compose ps` with the container `healthy` + `curl .../healthz` returning
`ok` to prove the deployment is sound even if a backend is flaky.

---

## 5. Deployment story (2 min) — this is what the group asked for

> "We deployed on the server itself, not GitHub Pages or Vercel."

- The dashboard is a **Docker container** running **nginx**, published on port
  **8009**, with `restart: unless-stopped` so it comes back after a reboot.
- Reachable at **`your-deployment-host:8009`** — the `public_ip:port` format the brief
  asked for.
- **Automated:** a **self-hosted GitHub Actions runner** on the server deploys
  on every push to `main` (`docker compose up -d --build`), then **health-checks
  `/healthz`** before calling it done.
- **Safe CI:** a separate validation workflow builds and smoke-tests the image
  on a throwaway port **without touching the live container**.
- **Health endpoint:** `GET /healthz` → `ok`, used by Docker, compose, and the
  deploy workflow to confirm the container is actually serving.

One-liner to memorise: *"Push to main → runner rebuilds the container → health
check on 8009 → live."*

---

## 6. Key technical decisions (why, not just what)

| Decision                      | Why                                                        |
|-------------------------------|------------------------------------------------------------|
| Static site, no framework     | Tiny, fast, no build step, dead-simple to containerise     |
| nginx in Docker               | Reproducible, portable, restarts on failure/reboot         |
| Deploy on the server          | Requirement; full control; backends are on the same host   |
| Cache-first with fallback     | Fast reads, resilient to a cache outage                    |
| Health endpoint + healthcheck | Deploys fail loudly instead of silently serving a dead page|
| Config in one file            | Repointing backends is a one-line change                   |

---

## 7. Q&A prep (anticipated questions)

**Why not GitHub Pages or Vercel?**
The brief required deploying on our own server, and the dashboard sits next to
its backend services on the same host — keeping it all together is simpler and
gives us full control over ports and networking.

**Isn't it insecure? No login, plain HTTP?**
Correct, and we're upfront about it: it's a demo deployment. For production we'd
add HTTPS (Caddy or nginx + Let's Encrypt), put the services behind
authentication, and stop exposing backend ports directly. It's on our roadmap.

**What happens if a backend service goes down?**
The page still loads. Each section fails independently — it shows a dash or an
"unavailable" message rather than crashing. The feed and overview also fall back
from the cache service to the main client service automatically.

**How does the frontend talk to five services on different ports?**
The browser calls each service directly using URLs defined in `config.js`. The
services send CORS headers so cross-origin calls are allowed. The cleaner next
step is to reverse-proxy them all through this nginx so there's a single origin.

**How would you scale this?**
The front end is static, so it scales trivially (any number of nginx replicas /
a CDN). Scaling is really a backend concern — the cache service already absorbs
most read traffic.

**Why vanilla JavaScript instead of React/Vue?**
The UI is read-mostly dashboards and lists. Vanilla ES modules keep it
lightweight with zero build tooling, which also made deployment simpler. If the
app grows more interactive, a framework becomes worth the overhead.

**How do you know a deploy actually worked?**
The deploy workflow polls `/healthz` after bringing the container up and fails
the job (with logs) if it doesn't go healthy. We also check `docker compose ps`.

**How do you update the backend URLs / move to a domain?**
Edit `scripts/config.js` and redeploy. Longer term we'd inject the base URL at
container start so one image works everywhere.

**What would you improve with more time?**
Reverse-proxy the APIs (one origin, no CORS), add HTTPS and auth, remove the two
unused scripts, and add runtime config. (These are listed in the README
roadmap.)

---

## 8. One-slide summary (if you need a closing slide)

- **What:** live dashboard for scraped public tenders — KPIs, trends, search,
  detail.
- **How:** static front end (vanilla JS) + nginx + Docker, calling 5 backend
  services, cache-first.
- **Where:** deployed on our server at `your-deployment-host:8009`, auto-deployed via
  a self-hosted CI runner with a health check.
- **Next:** HTTPS, auth, single-origin API proxy.
