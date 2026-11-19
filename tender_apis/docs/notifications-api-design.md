# Notifications API – design

Top-bar bell notifications for Tender Scrapper. Alerts (tender matches in the left
sidebar) stay in alerts-api; this service is for important app/account messages.

## Scope
- In: password changed, profile updated, saved tender closing soon / updated /
  cancelled, "new matches" summary, per-type preferences (bell + email), email
  unsubscribe links.
- Out (later): announcements (needs an admin mechanism), billing (no billing
  system yet), frontend bell UI.

## Deploy
- Branch `Feature/notifications-api`; workflows run only on pushes to this branch.
- Container `tender-notifications-api`, port `9007:8000`, shared volume
  `tender-sqlite-data` (`/data/tenders.db`), network `tender-scrapping-net`.
- Secrets: `JWT_SECRET`, `JWT_ALGORITHM`, `INTERNAL_API_KEY`, `EMAIL_FROM`,
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`,
  optional `APP_URL`, `PUBLIC_API_URL`.

## Tables (created on startup)
- `notifications(id, user_id, type, title, message, link, tender_id, in_app,
  email_status, email_attempts, created_at, read_at, emailed_at, dedupe_key UNIQUE)`
- `notification_preferences(user_id, type, in_app, email)` unique `(user_id, type)`
- `notification_tender_snapshots(user_id, tender_id, closing_date, status)`
- `notification_job_state(key, value)`

## Types and defaults
| Type | Bell | Email | Locked |
|---|---|---|---|
| password_changed | on | on | yes |
| profile_updated | on | off | no |
| tender_closing_soon | on | on | no |
| tender_updated | on | on | no |
| tender_cancelled | on | on | no |
| new_matches | on | off | no |

A notification is only stored if the user has the bell or email on for its type.
`in_app` is recorded on the row, so turning the bell off hides that type.

## Endpoints
- `GET /health`
- `GET /notifications?unread_only=&limit=` (limit ≤ 100)
- `GET /notifications/unread-count`
- `POST /notifications/{id}/read` (204, 404 if not the user's)
- `POST /notifications/read-all`
- `GET|PUT /notification-preferences`
- `GET /notifications/unsubscribe?token=` (signed token, turns email off for one type)
- `POST /internal/notifications` (header `X-Internal-Key`; types
  `password_changed`, `profile_updated`)

## Background job (every `NOTIFY_INTERVAL_MINUTES`, default 10)
1. New matches: `profile_alert_notifications` rows with id above the stored cursor
   and score ≥ `MATCH_MIN_SCORE` (71) → one summary per user. First run only sets
   the cursor.
2. Saved tender changes: compare with snapshot per (user, tender). Status became
   cancelled → `tender_cancelled`; closing date changed → `tender_updated`. First
   sighting only stores the snapshot.
3. Closing soon: saved tenders not cancelled/closed, closing within 3 days and
   within 1 day → one reminder per window (dedupe key).
4. Emails: pending emails are sent over SMTP; failures retry next run; after 24 h
   they are marked failed. `password_changed` is emailed immediately.

Naive closing dates are treated as South African time (UTC+2); date-only values
as end of that day.

## Signup-api change
After a successful `PUT /user/profile`, call `POST /internal/notifications`
(`profile_updated`) with a 3 s timeout; failures are logged and ignored.
`password_changed` is wired once a change-password endpoint exists.
