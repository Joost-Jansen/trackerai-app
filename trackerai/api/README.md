# trackerai-api

The API behind trackerai.nl (trackerai-web): the login, sign-up and account every tracker shares, and the admin page's
way to each tracker. It keeps no data of its own. Step 11 of [docs/PLAN.md](../../docs/PLAN.md).

| Path | What |
|---|---|
| `GET /api/health` | the healthcheck |
| `/api/auth/*`, `/api/account/*`, `/api/admin/*`, `/api/trackerai/admin/*` | the shared account ([packages/accounts](../../packages/accounts)), without a default app: a sign-up names its trackers (`apps`) |
| `/api/hub/{app}/<path>` | each tracker's own admin API (beta features, feedback), for the admin page; only the paths in `app/hub.py` pass |

There is no OAuth issuer for agents here: each tracker has its own.

## Environment

| Variable | What |
|---|---|
| `ACCOUNTS_DATABASE_URL`, `ACCOUNTS_SESSION_SECRET`, `ACCOUNTS_ENCRYPTION_KEY` | the shared accounts, the same values as every tracker's API |
| `SESSION_COOKIE_DOMAIN`, `REQUIRE_TOTP`, `SESSION_DAYS`, `RESEND_API_KEY`, `MAIL_FROM` | the same as every tracker's API |
| `PUBLIC_ORIGINS` | where the front door is served, e.g. `https://www.trackerai.nl,https://trackerai.nl` |
| `TRUSTED_PROXIES` | whose `X-Forwarded-For` is believed |
| `HEALTH_API_URL`, `WEALTH_API_URL` | each tracker's API for the hub (else `LANDING_HEALTH_URL`, `LANDING_WEALTH_URL`) |
| `COOKIE_SECURE` | `false` only on plain http (development) |

Without the shared accounts it refuses to start.

## Develop and test

```bash
pip install -r trackerai/api/requirements-dev.txt packages/accounts packages/websec
cd trackerai/api && python -m pytest -q
```

The image builds from the repo root: `docker build -f trackerai/api/Dockerfile .`
