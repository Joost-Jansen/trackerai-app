# Running the app

Three ways to host it: on a mini PC behind a shared Caddy and Cloudflare
Tunnel (the self-hosting plan), on the Raspberry Pi (the original
installation, with its own tunnel) or on Railway. All run the same two
Dockerfiles; the differences are environment variables and which compose
services run.

## Mini PC (shared Caddy + Cloudflare Tunnel)

The full guide is [SELF_HOSTING.md](SELF_HOSTING.md). In short: the compose
file's default services `api` (container `stock-api`) and `web` (`stock-web`)
build on the box itself (`docker compose up -d --build`) and join the external
docker network `edge`. There the shared Caddy of health-tracker's `deploy/edge`
(container `edge-caddy`) routes `/api/*` to `stock-api:8000` and the rest to
`stock-web:3000` (block: [`deploy/edge/Caddyfile.stocks`](../deploy/edge/Caddyfile.stocks)),
and the shared `cloudflared` reaches that Caddy. No `beta-proxy` and no
`cloudflared` of its own: those stay behind the compose profile `pi`.

Set in `.env`: `APP_ENCRYPTION_KEY` (required), `PUBLIC_ORIGINS`,
`TRUSTED_PROXIES` (the `edge` subnet), `PRIVACY_CONTROLLER`, `PRIVACY_CONTACT`.

## On the Raspberry Pi

stock-tracker runs permanently on the Pi and is publicly reachable at
**https://stock-tracker.nl** (through a Cloudflare Tunnel). It runs **in
Docker** (`~/stock-tracker` of the user on the Pi), like the other homelab
apps. The containers are the isolation: they only see their own files and
publish only on `127.0.0.1:8502`, so they cannot reach other services on the Pi
(such as Immich or Vaultwarden).

There are three containers: `stock-tracker-api` (FastAPI), `stock-tracker-web`
(Next.js) and `stock-tracker-beta-proxy` (Caddy, the only one that publishes a
host port). Only that proxy is reachable from outside; api and web talk to each
other over the compose network.

The app has a **login** (self-hosted, username + password). Every user gets
their **own, separate database** under `data/users/<user>/`, so nobody sees
anyone else's portfolio. The accounts are stored (only as bcrypt hashes) in
`auth_config.yaml`, which is NOT in git.

Reachability:
- **Public** (for friends, outside the tailnet): **Cloudflare Tunnel** at
  `https://stock-tracker.nl` (and `www.stock-tracker.nl`). The login protects
  the data. See "Public through Cloudflare Tunnel" below.
- **Private** (within the tailnet): Tailscale Serve on `:8445`.

> On the same Pi: Vaultwarden on `:443`, Immich on `:8443` — both tailnet-only.
> stock-tracker is public through Cloudflare; Tailscale `:8445` stays the
> private entrance. One machine, several apps, kept neatly apart.

### Running in Docker

The persistent state (per-user databases + `auth_config.yaml`) sits next to
the compose file and is mounted as a volume, so it survives a rebuild.

```bash
cd ~/stock-tracker
docker compose ps                 # is it running?
docker compose logs -f            # live logs
docker compose restart            # restart
docker compose down               # stop
```

The proxy publishes on `127.0.0.1:8502` (for Tailscale Serve `:8445`); the
Cloudflare Tunnel reaches the app through the compose network
(`http://beta-proxy:80`). Both stay unchanged across a rebuild.

> Since the mini-PC changes, the Pi's own proxy and tunnel are the compose
> profile `pi`, and the compose file needs a few things the Pi did not have
> before (once, on the Pi):
>
> - `.env`: `APP_ENCRYPTION_KEY=$(cat data/.encryption_key)` (take over the key
>   the app made itself; the api refuses to start without one), plus
>   `API_MEM_LIMIT=512m` for the Pi's small memory, and `TRUSTED_PROXIES` set to
>   the compose network's subnet (`docker network inspect stock-tracker_default`)
>   so the per-IP limits see the visitor behind `beta-proxy`.
> - `mv auth_config.yaml data/`: the account file now lives in the data folder
>   (written atomically); the single-file mount is gone.
> - `docker network create edge`: the compose file names that network for the
>   mini PC; on the Pi it only has to exist.
>
> The container names of api and web are now `stock-api` and `stock-web`.

> **NEVER build images on the Pi** (no bare `docker compose up -d --build`).
> The Pi has ~1.3Gi RAM and runs Immich and the live app next to it; a Next.js
> build there risks the OOM killer taking down running services. A bare `up`
> also starts a second `cloudflared` (a duplicate of the production tunnel).
> Build the images on the Mac and ship them — see "Day to day" below. On the
> Pi always use `--no-build` with the services named explicitly.

### Day to day

**Open the app** — public: `https://stock-tracker.nl` (private within the
tailnet: Tailscale Serve on `:8445`).

**Change code** — edit on the laptop, then one command on the laptop:

```bash
./deploy/deploy.sh
```

That script (1) pushes the code, (2) builds the `api` and `web` images on the
Mac (native arm64, fits the Pi), (3) ships them with
`docker save --platform linux/arm64 … | gzip | ssh 'docker load'`, and (4) runs
`deploy/update.sh` on the Pi — which does a `git pull` and recreates the
containers **without building** (`docker compose --profile pi up -d --no-build api web beta-proxy`).
`DEPLOY_HOST`, `SITE_URL` and `IMAGE_TAG` override the target, the address it
prints and the image tag (default `local`).

**Check / restart** (on the Pi, in `~/stock-tracker`):

```bash
docker compose ps
docker compose restart
docker compose logs -f
```

### Public through Cloudflare Tunnel (stock-tracker.nl)

The Pi opens an outgoing tunnel to Cloudflare itself (the `cloudflared`
container, see `docker-compose.yml`), so **no ports need to be opened on the
router**. Cloudflare handles the HTTPS certificate.

The chain: visitor → Cloudflare → tunnel → `beta-proxy` container (`:80`) →
`web` (pages) or `api` (`/api/*`).

**One-time setup (Cloudflare dashboard + registrar):**

1. Add the domain `stock-tracker.nl` as a zone in Cloudflare.
2. At the registrar, switch the **nameservers** to the two Cloudflare
   nameservers (ending in `.ns.cloudflare.com`).
3. **Zero Trust → Networks → Tunnels**: create the tunnel `stock-tracker-pi`,
   put the connector token in `.env` on the Pi (`TUNNEL_TOKEN=…`) and start
   `docker compose up -d`.
4. In the tunnel under **Routes → Public Hostname** add two routes:
   `stock-tracker.nl` and `www.stock-tracker.nl` → `http://beta-proxy:80`.
   Cloudflare creates the matching (proxied, orange cloud) DNS records itself —
   add nothing to DNS by hand.
5. **SSL/TLS → Edge Certificates → "Always Use HTTPS"** on, so `http` redirects
   to `https` automatically.

The `TUNNEL_TOKEN` lives in `.env` (in `.gitignore`, never commit it). Check the
tunnel with `docker compose logs cloudflared`.

### Your database

`data/` and `*.db` are in `.gitignore`, so the database does NOT travel through
GitHub. The data lives in `~/stock-tracker/data/` on the Pi and is mounted into
the container. To bring a database over from the laptop:

```bash
scp data/portfolio.db <user>@<pi>:~/stock-tracker/data/
ssh <user>@<pi> "cd ~/stock-tracker && docker compose restart"
```

### Access and security

- Logging in to the Pi uses an **SSH key** (the private part is only on the
  admin laptop), not a password. The Pi itself is only on the Tailscale network,
  not on the open internet.
- **Laptop lost?** The app keeps running. To lock out the lost key: remove its
  line from `~/.ssh/authorized_keys` on the Pi.

### Problems?

- **The phone cannot reach it**: is Tailscale on (for the private address)?
- **The app does not start**: `cd ~/stock-tracker && docker compose logs`.

## On Railway

An alternative to the Pi: no machine of your own, no Caddy and no tunnel.
Railway runs the same two Dockerfiles as services, with one volume for all data.

**Services** (both from this repo, branch `main`):

| Service | Root directory | Dockerfile | Healthcheck | Volume |
|---|---|---|---|---|
| `api` | `/` (the trackerai repository) | `wealth-tracker/backend/Dockerfile` | `/api/health` | `/data` |
| `web` | `/frontend` | `Dockerfile` | `/login` | — |

These settings live on the services themselves, not in a `railway.toml`:
Railway has phased those config files out. Both restart on failure.

Only `web` gets a public domain. `api` is only reachable through the private
network: the browser talks to `web`, and `web` forwards `/api/*`.

**Variables on `api`:**

| Variable | Value | Why |
|---|---|---|
| `DATA_DIR` | `/data` | databases and uploads on the volume |
| `AUTH_CONFIG_PATH` | `/data/auth_config.yaml` | accounts on the volume |
| `PORT` | `8000` | fixed, so `web` knows where to go |
| `HOST` | `0.0.0.0` (or leave out) | not `::`: then the healthcheck (IPv4) does not get through and the deploy hangs. The private network has IPv4 in environments created after 16 October 2025; only an older, IPv6-only environment needs `::` |
| `RAILWAY_RUN_UID` | `0` | a volume belongs to root; the image otherwise runs as `appuser` |
| `TZ` | `Europe/Amsterdam` | times as on the Pi |
| `PRICE_REFRESH` | `on` | keep prices current during market hours |
| `APP_ENCRYPTION_KEY` | **required**, a Fernet key | encrypts bank-connection keys and sessions and two-step login secrets; the api refuses to start without it. On an existing volume take over `/data/.encryption_key` (`railway ssh --service api -- cat /data/.encryption_key`); a new key also works while that file stays, values are re-encrypted on use |
| `PUBLIC_ORIGINS` | `https://<your domain>` (comma-separated for stock- and wealth-tracker) | CSRF origin check and the bank's return address: Next's proxy changes the Host header, so the API must be told its public origin |
| `PRIVACY_CONTROLLER`, `PRIVACY_CONTACT` | your name and an e-mail address | shown on `/privacy` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | your choice | only for the first start, see below |
| `ANTHROPIC_API_KEY` | optional | Claude in labelling |
| `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `NTFY_TOPIC_URL` | optional | as in `.env` on the Pi |

**Variables on `web`:**

| Variable | Value |
|---|---|
| `API_INTERNAL_URL` | `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` |
| `PORT` | `3000` |

`PORT` is needed: otherwise Railway gives every service a port of its own
(8080), Next listens on that, and the public domain points to 3000 — then you
get a 502 "Application failed to respond" while the service says "Online".

`API_INTERNAL_URL` is baked into the image at build time (Next fixes rewrites
then). If you change it, `web` has to be rebuilt, not just restarted.

**One site.** The frontend is wealth-tracker: your wealth first (net worth,
spending, accounts) with the portfolio below it (`frontend/lib/app.ts`). The
former stock-tracker build mode is gone; whoever signs up gets the money beta
flag straight away (its code stays `money`). On Railway the frontend service is
still called `money`.

**The first account.** An empty server has no `auth_config.yaml`, and without
that file nobody can log in. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` on
`api`: the first start then creates the file, with that account as admin and
self sign-up closed. After that it does nothing any more, even if the
variables stay. Remove `ADMIN_PASSWORD` after the first successful login: only
the hash is in the file. Add new users afterwards through the admin page
(invite links, or open sign-up), or with `railway ssh` and
`python ../scripts/manage_users.py add <name>`.

**Backups.** Everything is on that one volume. Turn on the volume's automatic
backups in Railway. A separate copy:

```bash
railway ssh --service api -- tar czf - -C /data . > stock-tracker-data-$(date +%F).tgz
```

The databases run in WAL mode; `tar` on a running app can catch a write
halfway. For a guaranteed copy: stop the service first, or per database
`sqlite3 portfolio.db ".backup copy.db"`.

**One instance.** SQLite on one volume does not tolerate a second writing
machine, so `api` stays at one replica (the default; do not raise it).

**Known difference from the Pi.** On Railway the per-IP login limit sees the
address of `web`, not that of the visitor: everyone shares that one counter
(`TRUSTED_PROXIES` could name Railway's private network, but `web` is then
trusted to pass on the visitor's address, which Next does not guarantee). The
per-username limit, which stops the real guessing, works as usual.

## Security settings at a glance

Shared with health-tracker, documented in [SELF_HOSTING.md](SELF_HOSTING.md):
`APP_ENCRYPTION_KEY` (required), `PUBLIC_ORIGINS`, `TRUSTED_PROXIES`,
`PRIVACY_CONTROLLER`, `PRIVACY_CONTACT`, `SESSION_DAYS` (30, sliding),
`MAX_UPLOAD_MB` (10), `UPLOAD_RETENTION_DAYS` (0: delete after import) and
`ALLOW_INSECURE_DEFAULTS=true` as the only opt-out, for development.

## Managing users

The **Admin page in the app** (visible to admins only) covers almost all of it:

- **Registration mode** — open (anyone can create an account), invite only
  (with a personal invite link or the shared code), or closed. Stored as
  `registration_mode` in `auth_config.yaml`.
- **Invite links** — one per person, usable once, with an end date, and
  revocable.
- **Accounts** — reset a password (a temporary one if you leave it empty),
  grant or revoke admin, suspend, set beta features, and delete (including that
  user's data folder). Guardrails: you cannot delete or suspend yourself and the
  last admin always stays. A suspended account cannot log in and a running
  session becomes invalid at once.
- **Overview and log** — the number of accounts, admins, suspended accounts,
  disk use and open feedback, plus a log of recent admin actions
  (`data/admin_audit.log`).

On the server itself, `scripts/manage_users.py` still works, run **inside the
container**:

```bash
docker compose -f ~/stock-tracker/docker-compose.yml exec api python ../scripts/manage_users.py add <name>
# other commands: passwd <name> | remove <name> | list | set-code <code>
```

The password is entered hidden and only stored as a hash.

### Beta features per user

Some tabs are **beta** and hidden for normal users by default (returns,
dividends, calendar, rebalancing, and the money part). Admins always see them.
You give a non-admin user access on the Admin page, per account. Underneath
this writes a `beta:` block in `auth_config.yaml`:

```yaml
beta:
  rebalancing:
    - friend1
```

A new beta feature is added in code to `BETA_FEATURES` in
`backend/app/core/auth_store.py`; it then appears on the Admin page by itself.

### Rate limiting on sign-up (with open registration)

With **open** registration anyone on the internet can create accounts, and
every account gets its own database and folder. The first defence is a
**Cloudflare rule at the edge**, which stops bots before they reach the Pi:

**Cloudflare dashboard → your zone → Security → WAF → Rate limiting rules →
Create rule:**
- **Field** `URI Path` — **operator** `equals` — **value** `/api/auth/register`
- **When rate exceeds:** `5` requests per `1 minute` per client IP (plenty for
  real friends, tight for a spam bot)
- **Then:** `Block` for e.g. `10 minutes`

Cloudflare passes the visitor IP in `CF-Connecting-IP`; the app reads that
header for its own **backstop** throttle (5 sign-ups per hour per IP,
`backend/app/core/throttle.py`) in case something gets past the edge anyway —
but only when the request comes from one of `TRUSTED_PROXIES` (the Caddy in
front of it). From anyone else the header could be forged, and the socket
address counts.

**With more than one rule available** (paid plans, or once sign-up is closed
and the register rule is free again), add the durable layer for the other
in-memory limits, which reset on every restart:

- `URI Path starts with /api/auth/` — 20 requests per minute per IP → block 10 minutes.
- `URI Path starts with /api/mcp` — 120 requests per minute per IP → block 10 minutes
  (an MCP client makes one request per tool call; the app also refuses an IP
  after 20 failed tokens in 15 minutes).

### Rate limiting on login

Unlike sign-up, the main protection here is **in the app**, not at the edge —
on purpose. `backend/app/routers/auth.py` allows **10 attempts per 15 min per
account** and **30 per 15 min per IP**, checked before the password, so a
blocked attempt no longer costs a bcrypt check (~1.5 ms instead of ~240 ms).

The limit *per account* is the point. Cloudflare does not look into the request
body and so only counts per IP; an attack from a hundred IPs on one account is
exactly what an edge rule does not see and the app does. On the free plan that
cannot be built at the edge, however you write the rule.

**A separate Cloudflare rule for `/api/auth/login` was deliberately *not*
created.** At ~1.5 ms per blocked attempt someone has to send well over 40,000
attempts per minute to fill the 1.5 CPU the `api` container may use (see
`docker-compose.yml`) — and above that Cloudflare's standard DDoS protection,
which is on for every plan, steps in itself.

⚠️ **In particular, do not do this:** stretch the existing register rule from 5
to 20 per minute so `/api/auth/login` fits in with an `or`. The free plan allows
only one rate limiting rule, so that feels like the obvious trick — but you
give up working protection on sign-up in exchange for something marginal.

> **A note on the per-account limit:** someone who knows a username can keep it
> locked on purpose with 10 attempts per quarter of an hour. That is the known
> downside of counting per account, and still better than unlimited guessing.
> Increasing delays instead of blocking would take that away.
