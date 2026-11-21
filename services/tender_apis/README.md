# Notifications API (branch `Feature/notifications-api`)

Top-bar bell notifications for Tender Scrapper: account events, saved tender
reminders/changes and a "new matches" summary, with per-type bell/email
preferences. Runs on port **9007** and shares `/data/tenders.db` with the other
APIs. Design: [docs/notifications-api-design.md](docs/notifications-api-design.md).

## Endpoints
| Method | Path | Auth |
|---|---|---|
| GET | `/health` | none |
| GET | `/notifications?unread_only=false&limit=20` | Bearer JWT |
| GET | `/notifications/unread-count` | Bearer JWT |
| POST | `/notifications/{id}/read` | Bearer JWT |
| POST | `/notifications/read-all` | Bearer JWT |
| GET / PUT | `/notification-preferences` | Bearer JWT |
| GET | `/notifications/unsubscribe?token=` | signed link in emails |
| POST | `/internal/notifications` | `X-Internal-Key` header |

`PUT /notification-preferences` body:
```json
{"preferences": [{"type": "new_matches", "in_app": true, "email": true}]}
```

`POST /internal/notifications` body (types `password_changed`, `profile_updated`):
```json
{"username": "user@company.co.za", "type": "profile_updated"}
```

## Retention
The background job deletes notifications 90 days after they were created
(`NOTIFICATION_RETENTION_DAYS` in `main.py`; `0` keeps them all).

## Deactivated accounts
Users whose account is switched off (`users.is_active = 0`, for example after
they deactivate it in Signup-api) get no new notifications and no emails, except
`password_changed`. Emails still waiting when they deactivated are not sent.

## GitHub secrets
Required: `JWT_SECRET` (same as the other APIs), `INTERNAL_API_KEY` (a long
random string, also given to Signup-api).
Email: `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_USE_TLS` (same values as Signup-api).
Optional: `JWT_ALGORITHM`, `APP_URL` (frontend base URL for email buttons),
`NOTIFICATIONS_PUBLIC_URL` (public base URL of this API, for unsubscribe links).

## Run tests
```
pip install -r requirements.txt pytest
pytest -q
```
