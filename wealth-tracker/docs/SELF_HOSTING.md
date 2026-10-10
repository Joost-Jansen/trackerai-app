# Self-hosting stock-tracker

How to run wealth-tracker (formerly stock-tracker) on your own machine, safely enough to let other
people use it. The layout matches health-tracker, so both apps can share one
edge (Caddy + Cloudflare Tunnel) on one box. Railway and the original Raspberry
Pi setup are in [DEPLOY.md](DEPLOY.md).

## Requirements

- A Linux box with Docker Engine and the compose plugin (x86-64 or arm64). 2 GB
  of RAM is comfortable: the api may use up to 1 GB while importing, web 512 MB.
- The shared edge from health-tracker (`deploy/edge`): a Caddy container
  (`edge-caddy`) and `cloudflared` on the external docker network `edge`. Or any
  reverse proxy that routes `/api/*` to `stock-api:8000` and the rest to
  `stock-web:3000` and terminates TLS (directly or via Cloudflare).
- A domain in Cloudflare (for the tunnel) and, for bank connections, an Enable
  Banking application per user (each user brings their own).

## Environment variables

Everything lives in `.env` next to `docker-compose.yml`; `.env.example` lists
all of them with comments, in the same order and with the same names as in
health-tracker. The important ones:

| Variable | Required | What |
|---|---|---|
| `APP_ENCRYPTION_KEY` | yes | Fernet key for bank keys, bank sessions and two-step secrets. The api refuses to start without it. See "Upgrading" for taking over the key an older install made itself |
| `PUBLIC_ORIGINS` | yes behind a proxy that changes Host | The public origin(s), e.g. `https://stocks.example.org`; CSRF check and the bank's return address |
| `TRUSTED_PROXIES` | yes behind a proxy | IPs/CIDRs whose `CF-Connecting-IP` / `X-Forwarded-For` are believed (the `edge` subnet). Empty: none, every request counts as its socket peer |
| `PRIVACY_CONTROLLER`, `PRIVACY_CONTACT` | recommended | Who runs the installation and how to reach them; shown on `/privacy` |
| `SESSION_DAYS` | no (30) | "Stay logged in": session length, renewed while in use (at most 90 days after the password was typed) |
| `MAX_UPLOAD_MB` | no (10) | Largest uploaded file |
| `UPLOAD_RETENTION_DAYS` | no (0) | Days an imported file is kept; 0 deletes it after import |
| `ANTHROPIC_API_KEY` | no | Claude labelling; each user still has to opt in |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | first start | Create the first admin on an empty data folder |
| `ALLOW_INSECURE_DEFAULTS` | development only | The single opt-out: allows running without `APP_ENCRYPTION_KEY` |

`COOKIE_SECURE=false` only for plain-http development; it also turns HSTS off.

## Run with Docker Compose

```bash
git clone https://github.com/<you>/stock-tracker /srv/stock && cd /srv/stock
cp .env.example .env && chmod 600 .env        # fill in; never commit
mkdir -p data && chown 1000:1000 data          # the api runs as uid 1000
docker network create --subnet 172.30.0.0/24 edge   # once per box (shared with health-tracker)
docker compose up -d --build                   # builds api and web on this box
docker compose ps                              # both "healthy" after ~30 s
```

The first start with `ADMIN_USERNAME`/`ADMIN_PASSWORD` creates
`data/auth_config.yaml` with that admin and sign-up closed. Log in, then remove
`ADMIN_PASSWORD` from `.env`. Open sign-up only deliberately (Admin page:
closed / invite / open); invite links are single-use.

Containers: `stock-api` (FastAPI, port 8000) and `stock-web` (Next.js, port
3000), both `restart: unless-stopped`, json-file logs rotated at 10 MB × 3,
healthchecks on `/api/health` and `/login`. Nothing is published on the host.

## Behind the shared edge (Caddy + Cloudflare Tunnel)

The edge (health-tracker's `deploy/edge`) runs one `cloudflared` and one Caddy
(`edge-caddy`) for all apps on the box. Add the block from
[`deploy/edge/Caddyfile.stocks`](../deploy/edge/Caddyfile.stocks) to its
Caddyfile: `/api/*` → `stock-api:8000`, the rest → `stock-web:3000`, a request
body limit, and a Tailscale-only listener that drops a forged
`CF-Connecting-IP`.

In the Cloudflare tunnel, route the hostname to `http://edge-caddy:80`. While
the app is private (phase A of the plan), publish only the paths that must be
public:

```yaml
ingress:
  - hostname: stocks.example.org
    path: ^/api/(mcp|connections/enablebanking/callback)
    service: http://edge-caddy:80
  - service: http_status:404
```

and use the site itself over Tailscale. When opening it to others, drop the
`path` line.

Cloudflare settings for the zone (dashboard):

- SSL/TLS: Full; Always Use HTTPS on; minimum TLS 1.2; HSTS may be enabled at
  the edge as well (the app already sends it).
- Security → WAF → rate limiting rules (the durable layer; the app's own limits
  are in memory and reset on restart). With one rule (free plan) cover sign-up;
  with more, add the others:
  - `URI Path equals /api/auth/register`: 5 per minute per IP → block 10 min.
  - `URI Path starts with /api/auth/`: 20 per minute per IP → block 10 min.
  - `URI Path starts with /api/mcp`: 120 per minute per IP → block 10 min.
- Managed WAF rules and Bot Fight Mode on (Bot Fight Mode may challenge MCP
  clients: exclude `/api/mcp*` if they fail).
- Optional: Cloudflare Access (one-time e-mail code) in front of `/admin`.

App-side limits (in memory, per process): login 10 per 15 min per username and
30 per 15 min per IP; sign-up 5 per hour per IP; failed agent/MCP tokens 20 per
15 min per IP; password re-entry 10 per 15 min per account.

## Backups and restore

Everything is in `./data`: `users/*/portfolio.db`, `feedback.db`,
`admin_audit.log`, `auth_config.yaml` (and `.encryption_key` on an old
install). The databases run in WAL mode, so copy them with SQLite, not `cp`:

```bash
cd /srv/stock
for db in data/users/*/portfolio.db data/feedback.db; do
  sqlite3 "$db" ".backup '/srv/backup/stock/${db//\//_}'"
done
cp data/auth_config.yaml data/admin_audit.log /srv/backup/stock/
```

then `restic backup` the folder (see the plan's backup section). Keep
`APP_ENCRYPTION_KEY` in the password manager: without it the bank keys and
two-step secrets in a restored backup are unreadable (users can upload the key
again and set up two-step login again; everything else is unaffected).

Restore: stop the stack, put the files back in `data/` (owned by uid 1000),
`docker compose up -d`. Test a restore into a scratch folder twice a year.

## Upgrading

```bash
cd /srv/stock && git pull && docker compose up -d --build && docker image prune -f
```

Database changes migrate themselves on first use (`domain/legacy_names.py` and
idempotent steps), so there is no separate migration command.

From an install before this hardening:

1. **Encryption key.** Set `APP_ENCRYPTION_KEY` in `.env` to the content of
   `data/.encryption_key` (`echo "APP_ENCRYPTION_KEY=$(cat data/.encryption_key)" >> .env`).
   Nothing has to be re-entered. A *new* key also works as long as the old file
   stays: values are re-encrypted with the new key when used; remove the file
   only after that (keep a copy). Bank session ids stored in plain text are
   encrypted on first use.
2. **Account file.** `auth_config.yaml` now lives in `data/` (a directory
   mount, so it can be written atomically): `mv auth_config.yaml data/` before
   `docker compose up -d`.
3. Set `PUBLIC_ORIGINS`, `TRUSTED_PROXIES`, `PRIVACY_CONTROLLER`,
   `PRIVACY_CONTACT`.
4. Sessions now last 14 days: everyone logs in again once their cookie expires.
   Existing passwords keep working; the new rules apply when a password is set.
5. Agent tokens made before keep working without an end date; consider
   replacing them with tokens that have one.

## Security notes

- Every user has their own SQLite database under `data/users/<name>/`; every
  request opens only the database of the user its cookie or token names. Agent
  tokens never reach admin, token, account or bank-connection endpoints.
- Sessions: httpOnly, Secure, SameSite=Lax cookie; 30 days sliding with "stay logged in", a browser session without; retired by
  a password change. Cookie-authenticated writes must come from this site's
  origin (CSRF check). Optional two-step login (TOTP) for every user; strongly
  recommended for admins. Passwords: at least 10 characters, not common, not
  the username.
- Headers: a nonce-based Content Security Policy on every page, HSTS, frame
  denial, nosniff, Referrer-Policy, Permissions-Policy, COOP.
- Uploads: size-limited while streaming, xlsx checked against zip bombs, XML
  parsed with defusedxml, files deleted after import.
- Secrets at rest: bank keys, bank sessions and two-step secrets encrypted with
  `APP_ENCRYPTION_KEY`; passwords bcrypt; agent tokens and backup codes hashed.
- Claude labelling sends transaction descriptions to Anthropic, only for users
  who turn it on; the privacy page says so.
- Users export all their data and delete their account themselves (Settings →
  Your data); deletion revokes their bank consents.
- Check before opening up: `ss -tlnp` shows nothing public, the router forwards
  no ports, a restore test passed, old MCP tokens replaced.
