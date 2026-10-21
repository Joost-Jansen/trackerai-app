# health-tracker

**A training platform on top of your Garmin data, built so that both you and your own AI agent (Claude, ChatGPT or any other MCP client) work from the same numbers.**

Part of [trackerai](../README.md): it runs at health.trackerai.nl with a trackerai account, next to
[wealth-tracker](../wealth-tracker/README.md).

![The Today page with readiness, training load, this week of the plan, upcoming sessions and form](docs/screenshots/dashboard.jpg)

<sub>All screenshots show the synthetic demo account from [`scripts/seed_demo.py`](scripts/seed_demo.py); no real person's data. The UI is in English and Dutch; these screenshots show the English version. Regenerate them with [`scripts/screenshots.mjs`](scripts/screenshots.mjs). The map screenshots (activity, loops) are from 5 October: map tiles need network access to OpenStreetMap.</sub>

health-tracker syncs runs, rides, swims, sleep and recovery from Garmin Connect into Postgres (rides from Wahoo too, and
an Apple Health export by upload), computes what the watch app does not (your own heart-rate zones per sport, training load, recurring routes, race predictions) and shows it in a
fast web app. The same data is exposed as an API, a small CLI and a **Model Context Protocol server**, so a coaching agent
can read your training, write a plan or an analysis, and you see it on the site straight away. Your dashboards stay on
the site, not in a chat app, so you can switch agents or use none. It is multi-user, each account only ever sees its own
data, and anyone can run their own instance.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Notable engineering decisions](#notable-engineering-decisions)
- [Accounts and sign-up](#accounts-and-sign-up)
- [Deploy your own](#deploy-your-own)
- [Self-hosting (Docker Compose)](#self-hosting-docker-compose)
- [Try it locally with demo data](#try-it-locally-with-demo-data)
- [Development](#development)
- [Connect your own agent (MCP)](#connect-your-own-agent-mcp)
- [Project structure](#project-structure)
- [Disclaimer](#disclaimer)
- [License](#license)

## Features

**Today.** A readiness check that compares last night's resting heart rate, sleep and Body Battery with *your own*
baseline and your current form, the next sessions from the active plan (with a suggested route), form (fitness, fatigue,
freshness), time per heart-rate zone per week or month for all sports and per sport, and this week's volume next to the
four-week average.

**Activity detail with map and streams.** Every activity has its GPS track coloured by heart-rate zone, a linked
heart-rate / pace / altitude chart (hover the chart, see the spot on the map), km splits, laps, aerobic decoupling and how
this run compares with earlier runs on the same route. A heatmap tab draws every route you ever ran.

**Gear.** How far your shoes and bike have gone and when they are due for replacement (History, Gear). Gear from Garmin
Connect comes along with the sync, with its kilometres and the activities it was used on; you can also add your own,
with the kilometres it had before, a replacement limit (700 km for running shoes unless you or Garmin set one) and a
default per sport. On an activity you see what it used and why (chosen, from Garmin, or the default) and can change it;
Today warns when something is nearly worn or past its limit.

![Gear: running shoes and a bike with their kilometres, the replacement limit and the default sport](docs/screenshots/gear.jpg)

**Nutrition** (beta, switched on per account in the admin hub). Log a meal by searching the Dutch food table NEVO-online
(RIVM) and setting the amounts; the app adds up energy, carbohydrate, protein, fat, fibre, alcohol and salt and shows
carbohydrate and protein per kilo body weight against a range that follows your training: what you did that day, what
the plan says for it, and the day before a race or a session over three hours. Today gets a Nutrition card with the
same bars and a line such as "Tomorrow long run 20 km: aim for 5-7 g/kg carbohydrate today". Your usual portion of a
food is learnt from what you enter. With photo analysis switched on (your choice, per account), a photo of your plate
is enough: Claude names the foods and estimates the grams, you check and correct them, and the amounts you set teach
your usual portion. Packaged products come from Open Food Facts by barcode, and a favourite or "same as yesterday" logs
a meal in one tap. A Trends tab shows carbohydrate and protein per kilo against the targets with the training load,
energy eaten against Garmin's estimated burn, iron, alcohol per week, salt and saturated fat against the guidelines, and
how many days are logged well. Sleep & body marks the last meal and any alcohol of the evening before the night. The Day
tab has a Vitamins and minerals table against the Dutch norms (Voedingscentrum, for men or women as you choose), and My
foods keeps your favourites, your usual portions, your own products from a label and what you scanned. Foods NEVO lacks
can come from USDA FoodData Central when the server has a key. An
agent reads and logs it all through MCP. No calorie target unless you set one, and no red numbers: it is bookkeeping,
not a diet. The nutrient
values always come from the food table, never from guesses; NEVO's data is not in this repository (RIVM allows linking
to it, not handing it out): an admin imports it once per release (`docs/DEVELOPMENT.md`, Nutrition).

![Activity detail: route coloured by zone, time in zones, insights and the heart-rate, pace and altitude chart](docs/screenshots/activity.jpg)

**Trends.** Your sport and body over time, in three tabs. Training: fitness/fatigue/form (CTL/ATL/TSB) with race markers, VO2max,
weekly volume per sport, time per heart-rate zone and Z2 pace. Performance: predicted race times (Riegel), longest run,
record progression and detected races. Every chart has a time filter (4W to all time, custom range), pan and zoom,
moving averages, trend lines and peak markers.

**Today** has a second tab, **Sleep & body**: the night's sleep and stages, heart rate, breathing, stress
and SpO2 while asleep, Body Battery and activity, each against your own normal, and the night and day as aligned
panels; last night by default, any other day through the date field. Trends has a third tab, **Recovery**: the body
per day or week against your normal. "Training and body" (Trends, Training) puts sport and body values on one date
axis, so you see your pace drop in the weeks your resting heart rate goes up.

![Trends: insights, predicted race times and the form chart](docs/screenshots/trends.jpg)

**Loops.** Recurring routes are recognised automatically, independent of where you started the watch, for runs
and rides. Each route shows its most typical track, every other run drawn lightly underneath, and pace and efficiency
(metres per heartbeat) over time. "A loop of X km" combines known routes into a suggestion for a given distance.

| | |
|---|---|
| ![Loop overview with a map per recurring route](docs/screenshots/routes.jpg) | ![One loop with its pace and efficiency trend](docs/screenshots/route.jpg) |

**Training plan.** Create a plan in the editor, paste a markdown/CSV table, or let an agent write it. Planned
sessions are matched to what you actually did (done, missed, today, planned), with zone compliance per session, weekly
planned-versus-done kilometres, a race countdown and a suggested route for every run or ride.

| | |
|---|---|
| ![The active plan with kilometres per week: done, planned and the race](docs/screenshots/plan.jpg) | ![One week of the plan, with each session matched to the activity that was done](docs/screenshots/plan-week.jpg) |

**History, log and analyses.** A filterable activity list per month, a log and an analyses section (markdown), goals and
profile documents. Agents write here too; every entry records who wrote it.

![History: activities per month with distance, pace, heart rate and time per zone](docs/screenshots/history.jpg)

**Settings.** Heart-rate zones per sport as a percentage of max HR (with a suggestion from your own data), profile facts,
the connections (Garmin including MFA, Wahoo, Apple Health upload), agent tokens with copy-ready MCP instructions, your
trackerai account (password, two-step login by app or email, export or delete), and for admins the feedback inbox and
workouts per account. Accounts, sign-up and invitations for both trackers are managed at trackerai.nl/admin.

**Example data.** A first-run tour walks through every page with a shared, read-only example account
([`api/example.py`](api/example.py)), so a new user can look around before their own data is in.

**Feedback.** Users report something broken or an idea from the sidebar. A screenshot of the page is taken in the
browser when the dialog opens (the user sees it and can remove it); the page, browser, screen size and the last errors the browser hit go along. Admins answer in an inbox under Settings (status and a reply the
user sees), or let their agent do it over MCP (`list_feedback`, `update_feedback`). An optional ntfy ping says a report
came in, without its content.

| | |
|---|---|
| ![Heart-rate zones per sport and profile](docs/screenshots/zones.jpg) | ![Agent tokens with the MCP connector URL and the claude mcp add command](docs/screenshots/agents.jpg) |

Light and dark mode both work:

![The dashboard in dark mode](docs/screenshots/dashboard-dark.jpg)

## Architecture

| Layer | Stack |
|---|---|
| Web | Next.js 16 (App Router, standalone server), React 19, TypeScript, Tailwind, TanStack Query, Leaflet with OpenStreetMap tiles, hand-written SVG charts |
| API | Python 3.12, FastAPI, Pydantic, SQLAlchemy Core, bcrypt, PyJWT |
| Data | PostgreSQL everywhere: production, local runs and every test |
| Sync | [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) (unofficial) for activities and wellness, `fitdecode` for per-second streams from the original FIT files |
| Agents | MCP over streamable HTTP (`api/mcp.py`), a REST API and a dependency-free CLI (`tools/tr.py`) |
| Accounts | The shared trackerai account ([packages/accounts](../packages/accounts)), in its own accounts database |
| Hosting | One Docker image (web + API), built from the monorepo root, on Railway with a Postgres service; an optional cron service for the sync |

```mermaid
flowchart LR
    G[Garmin Connect] -->|garminconnect + FIT files| S[sync<br/>tools/sync.py]
    S -->|activities, streams, wellness| DB[(PostgreSQL)]
    S --> D[derive<br/>zones per activity, routes]
    D --> DB
    DB --> API[FastAPI<br/>api/]
    API -->|/api/* JSON| WEB[Next.js static site<br/>served by FastAPI]
    API -->|/api/mcp| MCP[Your agent<br/>any MCP client]
    API -->|login, session| ACC[(trackerai accounts)]
    API -->|Bearer token| CLI[tools/tr.py]
    B[Browser] -->|session cookie| WEB
```

**Data flow.** Once a day (and on demand with "Nu synchroniseren") the sync logs in to Garmin with the user's stored
session, fetches new activities, downloads the original FIT file, parses per-second GPS, heart rate, speed, altitude and
cadence, and merges everything into one record per activity (activities from different sources that start within two
minutes of each other are the same activity). Sleep, resting HR, Body Battery, stress and steps are stored per day. Then
`tools/derive.py` recomputes the derived data: time per heart-rate zone with the user's own zones, and the recurring routes.
The API computes everything else (form, trends, plan matching, readiness) from that data on request, with a small per-user
cache that is invalidated after a sync.

**Other devices.** Rides or runs that never reached Garmin (a Wahoo bike computer, Zwift, a borrowed watch) can be
uploaded as FIT files under History. They go through the same merge: a file whose start matches an activity that is
already there is folded into it instead of counted twice, with Garmin's values leading.

**Apple Watch.** Apple has no server API: the data lives in the Health app on the iPhone. Users export it there (profile
picture, "Export All Health Data") and upload the `export.zip` under Settings, Connections, Apple Health
(`api/apple.py`). The server streams the upload to a temporary file, reads `export.xml` and the GPX routes as a stream
in the background (`tools/apple_health.py`, entity declarations refused) and stores workouts, sleep with stages,
recovery and 90 days of day series in the same tables as Garmin's (`tools/apple_import.py`, source `apple`); a newer
export later only adds what is new. Days and workouts Garmin also has keep Garmin's values. Without an Apple Watch:
`python scripts/make_apple_export.py out/export.zip --days 120` makes a realistic synthetic export to test with.

The web app is a Next.js server (`web/`, its own image) that passes `/api/*` on to the API (`api/`, another image), so the
browser sees one origin and there is no CORS. Each page gets a Content-Security-Policy with a fresh nonce (`web/proxy.ts`).
In development `next dev` proxies `/api/*` to the API the same way.

**Auth and multi-user.** Logins are the shared trackerai account ([packages/accounts](../packages/accounts)): one account,
password and two-step login for every tracker, in an accounts database both trackers reach. The browser gets an httpOnly,
`SameSite` session cookie on the shared parent domain carrying a signed JWT (HS256, `ACCOUNTS_SESSION_SECRET`); logins are
throttled per account (across trackers) and per IP (behind trusted proxies only), with "stay logged in" sessions last 30 days from their last
use and end on a password change, and two-step login (an authenticator app or a code by email) is required for admins
and for anyone using more than one tracker (`REQUIRE_TOTP`). health-tracker keeps its own `users` row per account, made on the account's first visit. Agents use personal access tokens created on the site; only their SHA-256 hash is stored. Every data table has a
`user_id` column (with composite primary keys where ids are natural, like activity ids), and every function in
`tools/db.py` that touches user data takes a `Scope(engine, user_id)` instead of an engine, so a query cannot forget the
user. The single auth dependency `current_user` returns the caller with their own data store; routers never see another
user's data. Sign-up is in the account too; see [Accounts and sign-up](#accounts-and-sign-up).

**Secrets.** The Garmin password is only used once, to log in; it is never stored. What is stored is Garmin's session
token, encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using `APP_ENCRYPTION_KEY` (`tools/secretbox.py`). Encrypted
values carry a short key id, so a process with a different key reports "reconnect Garmin" instead of failing with a
decryption error. Garmin rotates the session; the rotated copy is re-encrypted after every sync. The web service
refuses to start without the key (older installs used one derived from `TRAINING_JWT_SECRET`; see the variables).

## Notable engineering decisions

- **Own zones, not the watch's.** Time in zone is computed from the raw heart-rate stream with the user's zones per sport
  (percent of max HR, with an "estimated" flag for cycling and swimming), never from Garmin's precomputed zone times, which
  use whatever the watch was set to at the time.
- **Route recognition without a start point.** Tracks are rasterised into grid cells and compared on cell overlap and
  distance, so the same loop matches even when the watch was started somewhere else; each cluster keeps its medoid as the
  "typical" track.
- **Context-aware comparisons.** Runs with 30 minutes or less between them are one session, and a run after a swim or a
  ride (a triathlon or brick) is excluded from pace trends and race predictions instead of being compared with a fresh run.
- **Tests on the database production runs.** Every test gets a Postgres database of its own (`packages/testing`, about
  20 ms each from an empty template), so the 600+ tests check the same SQL, types and constraints as production and
  can't share state.
- **Schema migration in one transaction.** The move from a single-user to a multi-user schema happens at startup, in one
  transaction, and is idempotent; it was tested on a full copy of production data before it shipped.
- **Agents are first-class users of the API.** The MCP tools return compact markdown designed for a language model
  (a plan as a table with done/missed per session, trends trimmed to what matters), and writes are attributed to `agent`
  so the site shows what the coach changed.
- **Personal values are never hardcoded.** Everything about a person (max HR, PRs, estimated zones, races, readiness
  thresholds) comes from their own data and settings; explanatory copy lives in one text catalog.

## Accounts and sign-up

Logins are the shared trackerai account, so one account opens health-tracker and wealth-tracker:

- **Sign-up** happens on trackerai.nl (or this site's `/register`). You choose health, wealth or both, and give an email
  address; a welcome mail brings a code that confirms it before you continue. You can add the other tracker later.
- **Two-step login** by an authenticator app, by a code sent to your email, or both. A confirmed sign-up address turns
  email codes on from the start.
- **Stay logged in** for 30 days on your own devices (`SESSION_DAYS`); untick it on a shared computer.
- **Admins** manage accounts, sign-up (`open`, `invite` with a link per person, or `closed`), invitations and two-step
  login for both trackers at trackerai.nl/admin. On an empty accounts database the first account to sign up becomes the
  admin.

Without a mail provider (`RESEND_API_KEY` and `MAIL_FROM`, or `SMTP_*`), sign-up can't confirm an address and email codes
are not offered. Details: [packages/accounts](../packages/accounts/README.md).

## Deploy your own

You need a Garmin Connect account with a watch that records heart rate. Everything else is free-tier friendly.

### Railway

1. **Fork [trackerai-app](https://github.com/Joost-Jansen/trackerai-app)** on GitHub.
2. In [Railway](https://railway.com), create a new project and add a **PostgreSQL** database (New, Database, PostgreSQL).
   The accounts need a database too; with wealth-tracker in another project, use one Postgres both reach through its
   public URL.
3. Add a service from your fork (New, GitHub Repo) and name it `api`. Leave the root directory empty (the repo root is
   the build context), set the Dockerfile path to `health-tracker/api/Dockerfile`, the healthcheck path to `/api/health`,
   and the watch paths to `health-tracker/api/**`, `health-tracker/tools/**`, `health-tracker/scripts/**` and
   `packages/accounts/**`, `packages/websec/**`.
4. On `api`, set the variables from the table below. At minimum:
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `APP_ENCRYPTION_KEY`, `ACCOUNTS_DATABASE_URL`, `ACCOUNTS_SESSION_SECRET`,
   `ACCOUNTS_ENCRYPTION_KEY`, `PORT=8000`, `HOST=0.0.0.0`, `PUBLIC_ORIGINS=https://<web's domain>` (the site passes
   requests on under its own host, so the API needs to be told which origin may post), and a mail provider for sign-up.
5. Add a second service from the same fork and name it `web`: Dockerfile path `health-tracker/web/Dockerfile`, watch paths
   `health-tracker/web/**`, `packages/ui/**`, `packages/marketing/**`, `package.json` and `package-lock.json`,
   healthcheck path `/login/`, and one variable, `API_INTERNAL_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` (where
   `/api/*` goes). Under Networking, generate a public domain for `web`.
6. Deploy. Open the domain and sign up: on an empty accounts database the first account becomes the admin. Sign-up then
   switches to `closed`; open it or make invitation links in the admin page.
7. Connect Garmin under Settings, Connections (email, password and the MFA code if Garmin asks). The first sync starts
   right away; after that `api` syncs every connected user daily after 06:00 Europe/Amsterdam.
8. Set your heart-rate zones under Settings, Zones and profile (the page suggests a max HR from your own data).

Optional: a separate **cron service** for the sync, if you prefer it outside the web process. Add a second service from the
same repo with `health-tracker/Dockerfile.sync` (root directory `health-tracker`), cron schedule `0 4 * * *`, and the same `DATABASE_URL` and `APP_ENCRYPTION_KEY`; then
set `SYNC_IN_WEB=false` on `api`.

Every push to your fork's `main` redeploys the service whose watch paths it touches.

### Environment variables

| Variable | Service | Required | What it does | How to get a value |
|---|---|---|---|---|
| `DATABASE_URL` | api, sync | yes | SQLAlchemy URL of the database. `postgresql://...` (Railway: `${{Postgres.DATABASE_URL}}`) | from your database |
| `ACCOUNTS_DATABASE_URL`, `ACCOUNTS_SESSION_SECRET`, `ACCOUNTS_ENCRYPTION_KEY`, `SESSION_COOKIE_DOMAIN`, `REQUIRE_TOTP` | api | yes (the first three) | The shared trackerai account: the same values on every tracker. See [packages/accounts](../packages/accounts/README.md) | see there |
| `RESEND_API_KEY`, `MAIL_FROM` (or `SMTP_*`) | web | for sign-up | Sends the welcome mail and login codes; the same on every tracker | a sending-only key from resend.com |
| `FRONT_DOOR_URL` | api | no | The front door the site links to (the trackerai.nl admin page). Default: `https://www.<SESSION_COOKIE_DOMAIN>`; without a shared domain, no link. See [packages/accounts](../packages/accounts/README.md) | `https://www.trackerai.nl` |
| `TRAINING_JWT_SECRET` | api | no | Only for the key of an install from before `APP_ENCRYPTION_KEY` (see below); it no longer signs sessions | |
| `APP_ENCRYPTION_KEY` | api, sync | yes | Fernet key that encrypts stored Garmin and Wahoo sessions and two-step login secrets. Use the same value on every service. Changing it means every user reconnects and sets up two-step login again. The API refuses to start without it. `TOKEN_ENCRYPTION_KEY` is the older name and still read. An install that ran without either used a key derived from `TRAINING_JWT_SECRET`: `python -m tools.secretbox --print-derived-key` prints it, set that | `python -m tools.secretbox --new-key` |
| `ALLOW_INSECURE_DEFAULTS` | api | no | `true` skips the start-up checks above (missing encryption key, short JWT secret). Local development only | `true` locally |
| `PUBLIC_ORIGINS` | api | on Railway, and behind a proxy with another name | Comma-separated origins (`https://host[:port]`) besides the request's own host that may send state-changing requests (the CSRF origin check); the front door at `SESSION_COOKIE_DOMAIN` (`https://<domain>`, `https://www.<domain>`) is always allowed | `https://health.example.org,https://box.tailnet.ts.net` |
| `TRUSTED_PROXIES` | api | behind a proxy | Comma-separated IPs/CIDRs of your reverse proxies. Only requests from them have their `CF-Connecting-IP` (else the rightmost untrusted `X-Forwarded-For` hop) used as the client IP for the per-IP limits. Empty: the socket peer. The proxy must overwrite `CF-Connecting-IP` on any listener Cloudflare does not front (see `deploy/edge/Caddyfile`) | `172.30.0.10` |
| `SESSION_DAYS` | api | no | "Stay logged in": days a login stays valid after its last use (renewed while in use), and how long a device that gave the two-step code is not asked for it again. Default 30 | `30` |
| `PRIVACY_CONTROLLER`, `PRIVACY_CONTACT` | api | when others use it | Name and contact of whoever runs the installation (the GDPR controller), shown on /privacy | `Jane Doe`, `privacy@example.org` |
| `MAX_UPLOAD_MB` | api | no | Largest FIT upload (default 25) | `25` |
| `APPLE_IMPORT_MAX_MB`, `APPLE_CHUNK_MB`, `APPLE_UPLOAD_TTL_MIN` | api | no | Largest Apple Health export (default 2048), the parts the site uploads it in (default 32; below Cloudflare's 100 MB), minutes before an unfinished upload is removed (default 60) | `2048`, `32`, `60` |
| `APPLE_UPLOAD_DIR`, `TMPDIR` | api | no | Where uploads in progress and temporary files (exports) go; the image sets them under `/data` | `/data/uploads` |
| `PUBLIC_URL` | api | no | The site's address for links in the feedback ping | `https://health.example.org` |
| `PORT` | api | Railway: yes | Port uvicorn listens on (default 8000) | `8000` |
| `HOST` | api | no | Bind address (default `0.0.0.0`). Keep it IPv4; `::` breaks Railway's healthcheck in new environments | `0.0.0.0` |
| `TZ` | api, sync | no | Container time zone (the image defaults to `Europe/Amsterdam`) | e.g. `Europe/Amsterdam` |
| `COOKIE_SECURE` | api | no | `false` allows the session cookie over plain http (local development only). Default `true` | `false` locally |
| `SYNC_IN_WEB` | api | no | `false` turns off the daily sync inside `web` (when you run the cron service instead) | `false` |
| `TRAINING_USER`, `TRAINING_PASSWORD_HASH` | api | no | Alternative bootstrap: creates this admin on an empty database at startup, instead of registering in the browser. Ignored once any user exists | a bcrypt hash: `python -c "import bcrypt, getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"` |
| `TRAINING_AGENT_TOKEN_HASH` | api | no | Legacy: SHA-256 of one agent token for the first admin. Prefer tokens created on the site | `tools/set_agent_token.py` |
| `FEEDBACK_NTFY_URL` | api | no | An [ntfy](https://ntfy.sh) topic URL: a ping to your phone when someone sends feedback. Only the kind and a link go out, never the text | `https://ntfy.sh/<a long random topic>` |
| `ANTHROPIC_API_KEY` | api | for photo analysis | The Claude API key for Nutrition's photo analysis. Without it the option is not offered; each user switches it on themselves | `sk-ant-...` |
| `NUTRITION_MODEL`, `NUTRITION_EFFORT` | api | no | The model and effort for meal photos | `claude-sonnet-5-5`, `medium` (defaults) |
| `NUTRITION_DAILY_PHOTOS` | api | no | Photos one user may have analysed per 24 hours (each is a paid call) | `40` (default) |
| `FDC_API_KEY` | api | no | USDA FoodData Central, searched (only the search words go out) when NEVO, your own foods and the cache find fewer than three foods | developer key from fdc.nal.usda.gov |
| `OFF_CONTACT` | api | no | An e-mail address in the User-Agent of Open Food Facts barcode lookups, as Open Food Facts asks | `you@example.org` |
| `WAHOO_CLIENT_ID`, `WAHOO_CLIENT_SECRET` | api, sync | for Wahoo | The app from Wahoo's developer portal (scopes `workouts_read offline_data user_read`). Without them the Wahoo card says it is not set up | developers.wahooligan.com |
| `WAHOO_REDIRECT_URI` | api | no | The callback registered at Wahoo; default: this server's `/api/connections/wahoo/callback` | `https://<your-app>/api/connections/wahoo/callback` |
| `GARMINTOKENS` | sync | no | Legacy: an initial Garmin session for the first admin, used by the cron service if the stored one is missing or stale. Prefer connecting on the site | `tools/setup_garmin.py` |

Never commit any of these; set them in Railway (or `.env` for Docker Compose, a git-ignored `.env.dev` locally).

### Docker (any host)

```bash
docker build -f health-tracker/api/Dockerfile -t health-tracker-api .   # from the repo root
docker run -d -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:password@db-host:5432/health \
  -e APP_ENCRYPTION_KEY=<fernet key> \
  -e ACCOUNTS_DATABASE_URL=postgresql://user:password@db-host:5432/accounts \
  -e ACCOUNTS_SESSION_SECRET=<random hex> -e ACCOUNTS_ENCRYPTION_KEY=<fernet key> \
  health-tracker
curl localhost:8000/api/health   # {"status":"ok"}
```

Put a TLS-terminating proxy in front for anything public; the cookie is `Secure` by default.

## Self-hosting (Docker Compose)

For a server of your own (a mini PC at home, a VPS): [`docker-compose.yml`](docker-compose.yml) runs `health-web` (this
image) and Postgres 16 on an internal network, with healthchecks, log rotation and `restart: unless-stopped`; every
setting is in [`.env.example`](.env.example). It joins the shared external network `edge`, where
[`deploy/edge/`](deploy/edge) puts Caddy and a Cloudflare Tunnel in front of this app and wealth-tracker (hostnames,
body limits per path, the Tailscale listener, no MCP tokens in logs), and [`deploy/backup/`](deploy/backup) has the
nightly `pg_dump` + restic backup and the restore procedure.

```bash
cp .env.example .env && $EDITOR .env          # secrets: see the comments in the file
docker network create --subnet 172.30.0.0/24 edge
docker compose up -d --build
```

The whole procedure (edge, Tailscale, Cloudflare phases, moving from Railway, backups, upgrading, security notes):
[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md).

## Try it locally with demo data

```bash
git clone https://github.com/Joost-Jansen/trackerai-app && cd trackerai-app/health-tracker
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
(cd .. && npm ci)                                # one npm install at the repo root

# Postgres for every app, with an `accounts`, `health` and `wealth` database (from the repo root)
(cd .. && docker compose -f compose.dev.yml up -d)
export DATABASE_URL=postgresql://postgres:dev@127.0.0.1:55432/health
export ACCOUNTS_DATABASE_URL=postgresql://postgres:dev@127.0.0.1:55432/accounts
export REQUIRE_TOTP=off                      # no two-step login for the local demo
export ACCOUNTS_SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export ACCOUNTS_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# the synthetic "demo" user (about six months of training)
.venv/bin/python scripts/seed_demo.py         # prints the demo password

ALLOW_INSECURE_DEFAULTS=true COOKIE_SECURE=false SYNC_IN_WEB=false \
.venv/bin/uvicorn api.main:create_app --factory --port 8000 &
(cd web && npm run dev)                      # the site on :3000, /api/* to the API on :8000
```

Open http://localhost:3000 and log in as `demo`. The seed script creates runs, rides and pool swims with per-second
streams along a few invented loops east of Utrecht, daily sleep and recovery values, zones, a 16-week marathon plan, log
entries and an analysis, and then runs the same derive step as a real sync. Options: `--days`, `--end`, `--password`
(or `DEMO_PASSWORD`), `--reset`. Every value is generated from a fixed random seed; nothing comes from a real person.

## Development

```bash
.venv/bin/pip install -e ../packages/testing   # once: a Postgres database per test (compose.dev.yml must be up)
.venv/bin/python -m pytest -q          # backend: API, database, sync, zones, routes, plans, MCP (no network)
cd web && npx tsc --noEmit             # frontend type check
cd web && npm run build                # the Next server (standalone), also run by the Docker build
cd web && npm run dev                  # hot reload on :3000, proxies /api/* to the API on :8000
```

Garmin is never called in tests: the sync takes an injectable client and FIT reader. Developer notes are in
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md); design documents are in [`docs/`](docs).

## Connect your own agent (MCP)

The site is an MCP server at `/api/mcp` (streamable HTTP, stateless, JSON responses). Create a token under
Settings, Agents; it is shown once. Tools: `get_context`, `list_activities`, `get_activity`, `get_day`, `get_trends`, `get_plan`,
`create_plan`, `replace_plan_sessions`, `set_plan_status`, `add_log`, `list_log`, `get_doc`, `update_doc`, `suggest_route`, `list_gear`,
with Nutrition on also `get_nutrition`, `log_meal` and `search_foods` (and a Nutrition section in `get_context` and `get_day`), and
`sync_now` (fetches new data from Garmin and Wahoo, as the button on the site does, so your agent works with today's data).

Any MCP client works: the token goes in `Authorization: Bearer <token>`, or in the URL (`https://<your-domain>/api/mcp/<token>`) for a client
that only takes a URL. The token is then part of that URL, so treat the URL as a password; revoke the token on the site
if it leaks. Settings, Agents shows the steps for the assistant you pick, with the token filled in. Open the one you
need:

<details><summary><b>Claude</b> (app, claude.ai, Claude Code)</summary>

At claude.ai/customize/connectors, Add custom connector, URL `https://<your-domain>/api/mcp/<token>`. Once per account: it then works in the
Claude app, on claude.ai and in Claude Code logged in with that account (also in the cloud). Only Claude Code with an
API key instead of a claude.ai login needs its own entry:

```bash
claude mcp add --transport http --scope user health-tracker https://<your-domain>/api/mcp \
  --header "Authorization: Bearer <token>"
```
</details>

<details><summary><b>ChatGPT</b></summary>

On the web, switch on Developer mode under Settings (Apps or Connectors, Advanced), create a connector with URL
`https://<your-domain>/api/mcp/<token>` and authentication "No authentication".
</details>

<details><summary><b>Codex</b> (CLI and IDE extension)</summary>

In `~/.codex/config.toml`:

```toml
[mcp_servers.health-tracker]
url = "https://<your-domain>/api/mcp"
http_headers = { "Authorization" = "Bearer <token>" }
```
</details>

<details><summary><b>GitHub Copilot</b> (VS Code, CLI)</summary>

Each keeps its own list. In VS Code: Command Palette, "MCP: Open User Configuration", and add under `servers`:

```json
"health-tracker": { "type": "http", "url": "https://<your-domain>/api/mcp", "headers": { "Authorization": "Bearer <token>" } }
```

Copilot CLI, once:

```bash
copilot mcp add --transport http health-tracker https://<your-domain>/api/mcp/<token>
```
</details>

<details><summary><b>Another MCP client</b> (Cursor, Gemini CLI, …)</summary>

URL `https://<your-domain>/api/mcp` with header `Authorization: Bearer <token>`, or, if it only takes a URL, `https://<your-domain>/api/mcp/<token>`.
</details>

- **CLI / scripts:** `TRAINING_API_URL=https://<your-domain> TRAINING_API_TOKEN=<token> python tools/tr.py context`
  (standard library only). See `python tools/tr.py --help` for plans, log entries, analyses and documents.

The MCP server sends its own instructions to the assistant (see `instructions()` in `api/mcp.py`): start a session with
`get_context`, separate observation, interpretation and advice, compute instead of estimate, and end with a log entry.

## Project structure

```
api/                 FastAPI app (create_app factory): auth and users, dashboard, history, trends, plans, routes,
                     zones, onboarding, Garmin connection and in-process sync scheduler, MCP server
tools/               database schema and queries (db.py), Garmin sync (sync.py, fit.py, store.py), derived data
                     (derive.py, zones.py, routes.py, recommend.py, analytics.py), encryption (secretbox.py), CLI (tr.py)
web/                 Next.js app: app/(app)/<page> per screen (app/(redirects) for old Dutch paths), components
                     (design system, charts, maps, plan, zones)
scripts/             seed_demo.py (synthetic demo account), screenshots.mjs (retakes the README screenshots)
tests/               pytest, one file per module
docs/                developer notes, design documents, screenshots
Dockerfile           web + API image (Node build stage, Python runtime)
Dockerfile.sync      optional cron image for the sync
```

## Disclaimer

health-tracker is a personal project, **not a medical device and not medical advice**. Readiness, form, zones and race
predictions are estimates from wrist-based sensor data and simple models. If you are ill, injured or notice an unusual
heart rate, see a doctor or physiotherapist.

The Garmin sync uses [`garminconnect`](https://github.com/cyberjunky/python-garminconnect), an **unofficial** library
that logs in like the Garmin Connect app. It is not affiliated with or endorsed by Garmin, can break when Garmin changes
its service, and you use it with your own account at your own risk. Garmin, Garmin Connect and Body Battery are
trademarks of Garmin Ltd.

## License

[MIT](LICENSE) (c) 2026 Joost Jansen.
