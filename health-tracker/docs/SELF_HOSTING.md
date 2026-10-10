# Self-hosting

Running health-tracker on your own server with Docker Compose, behind the shared edge (Caddy + a Cloudflare Tunnel)
that also serves stock-tracker. The plan behind it, with the hardware and the order of the steps, is in
[SELF_HOSTING_PLAN.md](SELF_HOSTING_PLAN.md). stock-tracker's `docs/SELF_HOSTING.md` has the same headings.

## Requirements

- A Linux host (x86-64 or arm64) with Docker Engine and the Compose plugin; 1 GB RAM for the app and Postgres.
- For access from outside: a domain on Cloudflare (the tunnel) and/or Tailscale on the host and your devices.
- For backups: `restic`, `sqlite3` (stock-tracker) and a restic repository (e.g. Backblaze B2).
- Nothing is published on the LAN: no router port forwarding, Postgres never leaves its internal network.

## Environment variables

All in `.env` next to `docker-compose.yml` (copy [`.env.example`](../.env.example); it explains each one and how to
make the secrets). The README's table lists every variable. In short:

| Section | Variables |
|---|---|
| Required secrets | `TRAINING_JWT_SECRET` (≥ 32 characters), `APP_ENCRYPTION_KEY` (Fernet; `TOKEN_ENCRYPTION_KEY` is the older name), `POSTGRES_PASSWORD` |
| Public URL and proxy | `PUBLIC_ORIGINS`, `TRUSTED_PROXIES`, `COOKIE_SECURE`, `SESSION_DAYS`, `PUBLIC_URL` |
| Privacy | `PRIVACY_CONTROLLER`, `PRIVACY_CONTACT` (shown on /privacy) |
| Limits | `MAX_UPLOAD_MB`, `APPLE_IMPORT_MAX_MB`, `APPLE_CHUNK_MB`, `APPLE_UPLOAD_TTL_MIN` |
| Integrations | `WAHOO_CLIENT_ID`, `WAHOO_CLIENT_SECRET`, `WAHOO_REDIRECT_URI`, `FEEDBACK_NTFY_URL`, `SYNC_IN_WEB`, `TZ` |
| Development only | `ALLOW_INSECURE_DEFAULTS`, `TRAINING_USER`, `TRAINING_PASSWORD_HASH` |

The web service refuses to start without `APP_ENCRYPTION_KEY` or with a short JWT secret (unless
`ALLOW_INSECURE_DEFAULTS=true`, for development only).

**Moving an install that ran without `APP_ENCRYPTION_KEY`** (Railway before this change): its Garmin and Wahoo sessions
are encrypted with a key derived from `TRAINING_JWT_SECRET`. Print that key and set it, so nobody has to reconnect:

```bash
TRAINING_JWT_SECRET=<the existing secret> python -m tools.secretbox --print-derived-key
```

An install that had `TOKEN_ENCRYPTION_KEY` keeps working as is; rename it to `APP_ENCRYPTION_KEY` when convenient.

## Run with Docker Compose

```bash
sudo mkdir -p /srv/health && cd /srv/health
git clone https://github.com/Joost-Jansen/health-tracker . && cp .env.example .env && chmod 600 .env
$EDITOR .env
docker network create --subnet 172.30.0.0/24 edge      # once per host, shared with the edge and stock-tracker
docker compose up -d --build
docker compose ps                                       # web and postgres "healthy"
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read())"
```

- `health-web` (the image from `Dockerfile`: the static site and the API, uvicorn as uid 1000, read-only root
  filesystem, temporary files on the `web-data` volume) and `health-postgres` (`postgres:16.15`, data on `pgdata`).
- Log rotation (json-file, 10 MB × 3), `restart: unless-stopped`, healthchecks on `/api/health` and `pg_isready`.
- The first account: register it right away over Tailscale (the first registration on an empty database becomes
  admin), or set `TRAINING_USER` and `TRAINING_PASSWORD_HASH` before the first start. Registration is then `closed`;
  open it or make invite codes under Settings, Admin.
- Moving from Railway: stop the Railway web service, `pg_dump -Fc --no-owner "$RAILWAY_DATABASE_URL" > railway.dump`,
  then `docker compose exec -T postgres pg_restore -U health -d health --no-owner < railway.dump` before starting `web`.

## Behind the shared edge (Caddy + Cloudflare Tunnel)

[`deploy/edge/`](../deploy/edge) is the compose project for `/srv/edge`: `cloudflared` (pinned) and Caddy (pinned,
fixed address 172.30.0.10 on `edge`), routing by hostname: `health.<domain>` → `health-web:8000`;
`stocks.<domain>` → `/api/*` to `stock-api:8000`, the rest to `stock-web:3000`.

1. `cd /srv/edge`, copy `deploy/edge/*` there, `cp .env.example .env` and set `DOMAIN`.
2. Tunnel: `cloudflared tunnel login && cloudflared tunnel create edge` (on any machine), put the credentials JSON in
   `cloudflared/`, copy `cloudflared/config.phase-a.yml` to `cloudflared/config.yml` and fill in the UUID and
   hostnames; `cloudflared tunnel route dns edge health.<domain>` (and `stocks.<domain>`).
3. `docker compose up -d`.
4. Tailscale on the host: `tailscale serve --bg --https=443 http://127.0.0.1:8081` (health) and
   `tailscale serve --bg --https=8443 http://127.0.0.1:8082` (stocks). Put that `https://<host>.<tailnet>.ts.net`
   origin in `PUBLIC_ORIGINS`.
5. In the app's `.env`: `TRUSTED_PROXIES=172.30.0.10` (only Caddy's forwarding headers are believed).

What the edge does:

- **Client IP.** Cloudflare sets `CF-Connecting-IP`; the Tailscale listeners **overwrite** it with the address Caddy
  sees and drop `X-Forwarded-For`, so nobody on the tailnet can forge it. The app believes the header only from Caddy.
- **Body limits per path** (above the app's own): `/api/apple/upload/*` 40 MB (one part), `/api/apple/import` 2.1 GB
  (Cloudflare caps a request at 100 MB anyway, which is why the site uploads in parts), `/api/activities/upload`
  30 MB, everything else 8 MB.
- **No MCP tokens in logs**: the access log skips `/api/mcp/*` (the app masks them in its own log too).
- **Phase A** (`config.phase-a.yml`): only `/api/mcp…` of health and stock-tracker's MCP and bank callback are public;
  you use the sites over Tailscale. For Wahoo in phase A, register the Tailscale URL as the callback and set
  `WAHOO_REDIRECT_URI` to it. **Phase B** (`config.phase-b.yml`): all of `health.<domain>`; then also turn on in
  Cloudflare: Always Use HTTPS, minimum TLS 1.2, the managed WAF rules, Bot Fight Mode and rate-limit rules for
  `/api/login`, `/api/register` and `/api/mcp*`.

## Backups and restore

[`deploy/backup/backup.sh`](../deploy/backup/backup.sh) (nightly from cron, configured by `backup.env`, see
`backup.env.example`): `pg_dump -Fc` of health-tracker (checked with `pg_restore --list`), a `sqlite3 .backup` of every
stock-tracker user database and `feedback.db` (integrity-checked), `auth_config.yaml`, `admin_audit.log` and the users'
uploads; then `restic backup`, `restic forget --prune` (7 daily, 4 weekly, 12 monthly) and `restic check`.

```cron
0 3 * * * /srv/backup/backup.sh >> /var/log/backup.log 2>&1
```

Restoring, and the restore test to do now and twice a year: [`deploy/backup/restore.md`](../deploy/backup/restore.md).
Keep the restic password, `APP_ENCRYPTION_KEY`, `TRAINING_JWT_SECRET` and the tunnel credentials in a password
manager too, not only on the server.

## Upgrading

```bash
cd /srv/health && git pull && docker compose up -d --build     # migrations run at start-up, in one transaction
docker compose logs -f web                                      # "Application startup complete"
```

Take a backup first (`/srv/backup/backup.sh`). Images of the edge and Postgres are pinned: bump the tags in the compose
files on purpose (Postgres: minor versions only; a major version needs a dump and restore).

## Security notes

- Secrets only in `.env` (chmod 600) and the password manager, never in the image or the repository.
- Containers: no published ports, Postgres on an internal network, the app as a non-root user on a read-only root
  filesystem with all capabilities dropped and `no-new-privileges`.
- The app itself (with or without the edge): security headers and a per-page Content-Security-Policy, a CSRF origin
  check, per-username and per-IP limits on login (10 / 30 per 15 min), registration (5 per hour per IP) and failed
  agent tokens (20 per 15 min per IP), sessions of `SESSION_DAYS` that end on a password change, optional two-step
  login (strongly recommended for admins), body limits, zip-bomb checks on uploads, self-service export and deletion.
- The rate limits live in memory and reset on a restart: Cloudflare's rate-limit rules are the durable layer.
- Exposing the whole site (phase B) means other people's health data: read the privacy statement (/privacy), fill in
  `PRIVACY_CONTROLLER` and `PRIVACY_CONTACT`, and have it checked (GDPR art. 9; this is not legal advice).
