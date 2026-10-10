# Self-hosting plan: health-tracker and stock-tracker on a home mini PC

Moving both apps from Railway to a mini PC at home, with your own domain, a VPN for yourself and a Cloudflare Tunnel
for what has to be public, and getting both ready for other users. The same box also stores and streams films.

Prices are estimates (October 2026); check them before you buy. "Effort" is a rough size of the code work:
S = an hour or two, M = half a day to a day, L = more.

## 1. Summary

| | health-tracker | stock-tracker |
|---|---|---|
| Today | Railway: `web` (FastAPI + static site) + `Postgres` + an old `sync` cron service | Railway: `api` (FastAPI) + `web` (Next.js server) + a volume `/data` |
| Data | Postgres | SQLite per user (`data/users/<u>/portfolio.db`) + `auth_config.yaml` + `.encryption_key` |
| Already self-hostable | Dockerfile, no compose file | `docker-compose.yml` (api, web, Caddy, cloudflared), `docs/DEPLOY.md` for a Raspberry Pi |
| Public needs | MCP; the whole site once others use it; Wahoo OAuth callback | MCP; Enable Banking OAuth callback; the site if others use it |
| Biggest code gaps before others use it | chunked Apple upload (Cloudflare's 100 MB limit), per-IP login limit, security headers, self-service delete/export | upload size limits and zip-bomb guards, security headers, password policy, trusted proxy check, CSRF origin check, self-service delete/export |

**Order:** buy (2) → base server (3) → move health-tracker (5.1) → move stock-tracker (5.2) → backups and
monitoring (6) → code hardening (7, 8) → open to others (9). Phase A (only you) works after step 6; the code work is
only needed before other people get accounts.

## 2. What to buy

| Part | Choice | Approx. price |
|---|---|---|
| Mini PC | **Intel N150, 16 GB RAM, 1 TB NVMe**, e.g. Beelink EQ14 (alternatives: GMKtec NucBox G3 Plus, MinisForum UN150P) | €200-250 |
| Film storage | 2-bay USB-C enclosure (TerraMaster D2-320 or ORICO 2-bay) | €100-130 |
| Disks | 2× 8 TB NAS HDD (WD Red Plus or Seagate IronWolf, CMR, not SMR), as a mirror: 8 TB usable | €250-300 |
| UPS (recommended) | 500-700 VA, e.g. APC Back-UPS; a power cut is the most common cause of a corrupted database | €70-100 |
| Ethernet cable | to the router; no Wi-Fi for a server | €5 |
| Domain | one domain, subdomains per app (e.g. via Cloudflare Registrar) | €10-15/year |

**Why this mini PC:** 6-8 W idle; Intel Quick Sync for hardware video transcoding (Jellyfin, about three 4K→1080p
streams at once); 16 GB is plenty: health-tracker peaks at ~0.6 GB, stock-tracker runs in 512 MB today, Postgres and
Jellyfin 1-2 GB, together about 4-5 GB. 1 TB NVMe for the system, the apps, the databases and the Jellyfin cache;
films on the HDDs.

**Step up** (more services, virtual machines, 32-64 GB later): a refurbished Lenovo ThinkCentre M70q/M90q Tiny with a
12th-gen i5-T (€250-350, 10-15 W idle, two RAM slots).

**Costs:** one-off about €550-770 (mini PC, enclosure, disks, UPS); per year about €40-80 (power €30-55, domain,
backups). Railway today: roughly €60-240 a year for both apps (check the invoice).

## 3. Base server

- [ ] Debian 12 or Ubuntu Server 24.04 LTS on the NVMe, no desktop
- [ ] One sudo user; SSH with keys only (`PasswordAuthentication no`, `PermitRootLogin no`), only over Tailscale
- [ ] `unattended-upgrades` on; monthly reboot
- [ ] `ufw default deny incoming`; the router forwards **no** ports (Tailscale and cloudflared connect outwards)
- [ ] Docker Engine + Compose plugin; everything under `/srv`
- [ ] HDD mirror (mdadm RAID1 or a ZFS mirror) on `/srv/media`; `smartd` with e-mail alerts; spin-down after 20 min idle
- [ ] BIOS: power on after power loss
- [ ] Tailscale on the mini PC, phone and laptop; MagicDNS; ACLs: SSH only from your devices

## 4. Layout on the server

One Cloudflare Tunnel and one Caddy in front of both apps; each app keeps its own compose project.

```
/srv/edge/        docker-compose.yml: cloudflared (pinned version), caddy (hostnames → apps), shared network "edge"
/srv/health/      health-tracker: compose with web + postgres (postgres only on the internal network)
/srv/stock/       stock-tracker: its own compose (api, web) without its own cloudflared/proxy, on network "edge"
/srv/media/       films (HDD mirror), Jellyfin in /srv/jellyfin
/srv/backup/      restic scripts + the nightly cron
```

* **Caddy** routes by hostname: `health.<domain>` → `health-web:8000`; `stocks.<domain>` → `/api/*` to `stock-api:8000`,
  the rest to `stock-web:3000` (its current `Caddyfile.beta` logic). Caddy also sets the security headers for both
  (step 7) and a request body limit per path.
* **Tailscale** reaches the same Caddy on a separate port (Tailscale Serve), so you use the sites privately even when
  the tunnel only publishes the MCP paths.
* **cloudflared ingress, phase A** (only the MCP public):

  ```yaml
  ingress:
    - hostname: health.<domain>
      path: ^/api/mcp/
      service: http://caddy:80
    - hostname: stocks.<domain>
      path: ^/api/(mcp|connections/enablebanking/callback)
      service: http://caddy:80
    - service: http_status:404
  ```

  Phase B drops the `path` lines for the app that opens to others.

## 5. Moving off Railway

### 5.1 health-tracker

- [x] **Code (S):** add `docker-compose.yml` (web + postgres 16, healthchecks, `restart: unless-stopped`, log rotation)
      and `.env.example`; document it in the README next to Railway. Done: `docker-compose.yml`, `.env.example`,
      `docs/SELF_HOSTING.md`
- [ ] Copy from Railway: `TRAINING_JWT_SECRET` (or a new one: logs everyone out once), **`TOKEN_ENCRYPTION_KEY` (must
      be the same, otherwise every stored Garmin and Wahoo session is unreadable; set it as `APP_ENCRYPTION_KEY` now.
      Not set on Railway? Then `python -m tools.secretbox --print-derived-key` with the old JWT secret gives the key
      that was used)**, `WAHOO_*`, `FEEDBACK_NTFY_URL`
- [ ] **Delete the `sync` service on Railway**: it still runs older code next to the web service's own daily sync
- [ ] Stop the web service on Railway; `pg_dump --no-owner` via the public database URL; `pg_restore` at home
- [ ] Start; check over Tailscale: login, Today, a workout, Trends, an MCP call from Claude Code
- [ ] Wahoo developer portal: add the new callback `https://health.<domain>/api/connections/wahoo/callback`
- [ ] claude.ai: change the connector URL to the new domain (same token, or a new one)
- [ ] Keep Railway stopped for two weeks, then delete

### 5.2 stock-tracker

- [ ] **Code (S):** make the compose file host-independent:
  - a `build:` section for the api and web images, so they build on the x86 mini PC (today: built on a Mac for arm64 and
    shipped over ssh, `deploy/deploy.sh`)
  - drop its own `cloudflared` and `beta-proxy` services in favour of `/srv/edge` (or keep them behind a profile)
  - `mem_limit` 512m → 1g for the api (imports read whole files into memory); pin the image versions
  - `deploy/holdings-canary.sh`: no hard-coded home folder, read the path from the environment
  - remove the `beta.stock-tracker.nl` references or make them configurable
- [ ] Set `APP_ENCRYPTION_KEY` (from the Railway volume's `.encryption_key`, or Railway's variable) so the key no
      longer sits next to the data
- [ ] Copy the Railway volume `/data`: stop the api, then for every `users/*/portfolio.db` a `sqlite3 .backup` (WAL!),
      plus `auth_config.yaml`, `feedback.db`, `admin_audit.log`, `.encryption_key`, `users/*/uploads/`; via `railway ssh`
      and `tar`
- [ ] At home: `./data` and `./auth_config.yaml` (bind-mount the directory, not the single file, so in-place saves work)
- [ ] Enable Banking: register the redirect URL `https://stocks.<domain>/api/connections/enablebanking/callback`
- [ ] claude.ai: change the connector URL; check one read and one write tool
- [ ] Keep Railway stopped for two weeks, then delete (api, web and the volume)

## 6. Backups and monitoring

- [ ] Nightly at 03:00 (`/srv/backup/backup.sh`, cron; the script is in health-tracker `deploy/backup/`, restore in
      `deploy/backup/restore.md`):
  - health-tracker: `pg_dump -Fc`
  - stock-tracker: `sqlite3 <db> ".backup <copy>"` for every user database and `feedback.db`; copy `auth_config.yaml`,
    `admin_audit.log`, uploads
  - `restic backup` to Backblaze B2 (encrypted); keep 7 daily, 4 weekly, 12 monthly; then `restic check`
- [ ] Secrets in a password manager, **not only on the server**: restic password, `TOKEN_ENCRYPTION_KEY`,
      `APP_ENCRYPTION_KEY`, the JWT secret, the tunnel token
- [ ] **Restore test** into scratch containers now, then twice a year
- [ ] Films are not backed up (the mirror covers one dead disk)
- [ ] UptimeRobot (free) on both `/api/health` endpoints; `smartd` and a disk-space alert at 85%; Docker log rotation
- [ ] Phase A is done here: both sites over Tailscale, Claude connectors working

## 7. Code: health-tracker before others use it

Already in place: bcrypt, per-username login lock, httpOnly/secure/lax cookie, minimum password length, hashed MCP
tokens, encrypted Garmin/Wahoo sessions, per-user data, registration closed/invite/open, admin can delete users.

| # | Change | Why | Effort |
|---|---|---|---|
Status (October 2026): H1-H10 are implemented in health-tracker (see the commits and `docs/SELF_HOSTING.md`); the
shared building blocks are in `packages/websec` (used by both trackers).

| H1 | **Chunked Apple Health upload**: the browser sends ~50 MB parts, the server joins them, then imports | Cloudflare's free plan refuses request bodies over 100 MB; real exports are often bigger | M |
| H2 | **Login and registration limit per IP**, using `CF-Connecting-IP` only when the request comes from Caddy/cloudflared (a trusted-proxy list) | today only per username; behind the tunnel every visitor has the tunnel's address | S |
| H3 | **Security headers** (in Caddy or a FastAPI middleware): HSTS, CSP (`default-src 'self'`; map tiles and Leaflet), `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy` | none set today | S |
| H4 | **CSRF origin check**: refuse POST/PUT/PATCH/DELETE whose `Origin` is not the site's own (MCP/Bearer requests excepted) | today only SameSite=Lax protects | S |
| H5 | **Mask MCP tokens** in the uvicorn access log (as stock-tracker does) | the token is part of the URL; Railway's logs showed it | S |
| H6 | **Self-service account deletion and data export** (Settings › Account): a zip of all your data as JSON plus the stored FIT files | GDPR (art. 17, 20); today deletion only via an admin | M |
| H7 | **Consent at registration** for health data, privacy statement naming you as controller, retention | GDPR art. 9 (have it checked; not legal advice) | S |
| H8 | Upload limits: Apple 4 GB → 2 GB; FIT 25 MB stays; per-path body limits in Caddy | one user cannot fill the disk | S |
| H9 | **CI**: GitHub Actions running `pytest`, `tsc`, `check:i18n`, `npm run build` on every PR | nothing runs automatically today | S |
| H10 | Optional: TOTP two-step login for admins (or Cloudflare Access in front of `/settings/admin`) | admin accounts see everyone | M |

## 8. Code: stock-tracker before others use it

Already in place: bcrypt with constant-time unknown-user check, httpOnly/secure/lax cookie, sessions revoked on
password change, login limit per username and per IP, registration closed/invite/open, hashed scoped MCP tokens
(`read`/`write`, never admin), the MCP token masked in the app log, encrypted Enable Banking key, path-traversal guard
on uploads, admin audit log, privacy and terms pages.

| # | Change | Why | Effort |
|---|---|---|---|
| S1 | **Upload size limits and streaming** for DeGiro and bank uploads (e.g. 10 MB), checked before reading into memory; body limits in Caddy | no limit today; whole files are read into memory | S |
| S2 | **Zip/XML-bomb guard on xlsx**: `defusedxml` in the requirements, check the zip's uncompressed size and member count before `pandas.read_excel` | an uploaded xlsx is a zip with XML inside, parsed without guards | S |
| S3 | **Upload retention**: delete the stored upload once imported (or after 30 days), or make it an option | bank and broker files are kept forever | S |
| S4 | **Trusted proxy check**: only trust `CF-Connecting-IP` when the request comes from Caddy/cloudflared; run uvicorn with `--proxy-headers --forwarded-allow-ips` for those | anyone reaching Caddy directly (e.g. over Tailscale) can forge the header and dodge the per-IP limit | S |
| S5 | **Security headers**: HSTS, CSP (allow the inline theme script by hash), `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy` | none set today | S |
| S6 | **CSRF origin check** on state-changing requests (especially the multipart uploads) | today only SameSite=Lax | S |
| S7 | **Password policy**: at least 10 characters, refuse the most common passwords | only "not empty" today | S |
| S8 | **MCP tokens**: an optional expiry, "last used" shown, read-only as the default scope; a length/complexity limit and a timeout on `add_category_rule` regexes | a token without expiry gives full read access to someone's finances; user regex can hang the server (ReDoS) | M |
| S9 | **Require `APP_ENCRYPTION_KEY` in production** (refuse to start without it unless explicitly allowed); encrypt the Enable Banking `session_id` too | today the key file sits on the same disk as the data | S |
| S10 | **Self-service account deletion and data export** (all a user's tables as CSV/JSON in a zip) | GDPR; today admin-only, and the token blocklist already expects an `auth/delete` route | M |
| S11 | **Shorter sessions**: 30 → 14 days, refreshed while in use | a stolen cookie is valid a month | S |
| S12 | **CI and pinned dependencies**: GitHub Actions running pytest, `tsc`, the i18n check; pin `requirements.txt`, pin the cloudflared image | no CI; unpinned Python dependencies | S |
| S13 | **Rate-limit state**: keep the in-memory limits, add Cloudflare rate-limit rules for `/api/auth/*` and `/api/mcp*` as the durable layer | in-memory limits reset on every restart | S |
| S14 | Optional: TOTP two-step login (at least for admins) | financial data | M |
| S15 | Decide on the **Claude labelling** data flow: off by default, the privacy statement says that transactions go to Anthropic when on | other users' financial data to a third party needs their opt-in | S |

Because stock-tracker holds financial data and bank access, the simplest safe choice is to **keep it private**
(Tailscale for the site, only the MCP and the bank callback public) until S1-S10 are done.

## 9. Opening up to others (phase B)

- [ ] H1-H9 done (health-tracker), or S1-S13 done (stock-tracker), for the app that opens
- [ ] Registration on **invite** in each app's admin settings
- [ ] cloudflared: drop the `path` restriction for that hostname
- [ ] Cloudflare: Always Use HTTPS, minimum TLS 1.2, managed WAF rules, Bot Fight Mode, rate limits on login,
      registration and MCP
- [ ] Optional: Cloudflare Access (one-time code by e-mail) in front of `/settings/admin` and `/admin`
- [ ] Privacy statement and terms checked (GDPR: you are the controller of other people's health or financial data)
- [ ] Go-live checks: `ss -tlnp` shows nothing public; the router forwards no ports; a restore test passed;
      UptimeRobot alerts arrive; old MCP tokens replaced

## 10. Films

- [ ] Jellyfin in Docker with `/dev/dri` for Quick Sync; library on `/srv/media` (read-only)
- [ ] Only on the home network and Tailscale, **not** through the Cloudflare Tunnel (the free plan's terms do not allow
      video streaming)

## 11. Suggested pull requests

| Repo | PR | Contents | Effort |
|---|---|---|---|
| health-tracker | 1-5 | done on one branch, one commit per theme: security basics (H2-H5, H8), H1, H6, H7, H9, H10, compose and edge | — |
| stock-tracker | 1 | 5.2 compose changes, canary path, pinned images | S |
| stock-tracker | 2 | S1, S2, S3, S4, S5, S6, S7, S11 (uploads, proxy, headers, CSRF, passwords, sessions) | M |
| stock-tracker | 3 | S8, S9, S15 (MCP tokens, encryption key, labelling opt-in) | M |
| stock-tracker | 4 | S10 account deletion and export | M |
| stock-tracker | 5 | S12 CI and pinned dependencies | S |
| server | — | `/srv/edge` compose, Caddyfile, tunnel config, backup script: done in health-tracker `deploy/` | — |

## 12. Open questions

1. The domain name, and whether the stock-tracker keeps `stock-tracker.nl` (then it moves to the same Cloudflare account).
2. Will either app really get other users soon? If not, sections 7-9 can wait; phase A is enough.
3. Does anyone else (the original stock-tracker author) run their own copy that the compose changes in 5.2 must keep
   working for? Keep the Pi setup behind a compose profile if so.
