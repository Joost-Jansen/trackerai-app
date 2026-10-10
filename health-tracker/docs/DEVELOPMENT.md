# Development

How the code is organised, how to run it, and the rules the code follows. Deployment and environment variables are in
the README ("Deploy your own"). The UI speaks Dutch and English (see "Languages" below); code, comments, file and folder
names and commits are English (Dutch only inside UI texts and the Dutch messages the API returns).

## Architecture

```
web (web/Dockerfile)            Next.js standalone server: the pages, a CSP with a nonce per page (web/proxy.ts),
                                 /api/* passed on to the API
api (api/Dockerfile)            FastAPI: auth by session cookie (browser) or Bearer agent token (scripts, MCP clients)
                                 in-process daily Garmin sync for every connected user (api/sync_runner.py)
Postgres                         single source of truth (tools/db.py schema); SQLite works for local runs and tests
sync (optional cron)             Dockerfile.sync: tools/sync.py run_all_users, same work as the in-process sync
```

Garmin and Wahoo sessions and two-step login secrets are stored per user, encrypted with `APP_ENCRYPTION_KEY`
(`TOKEN_ENCRYPTION_KEY` is the older name; without either the key is derived from `TRAINING_JWT_SECRET`, which production
refuses unless `ALLOW_INSECURE_DEFAULTS=true`); give `web` and `sync` the same key. If Garmin invalidates a session, the user reconnects under Settings, Connections.

## Repo layout

| Path | What |
|---|---|
| `api/` | FastAPI app (`create_app` factory), auth, dashboard aggregation |
| `web/` | Next.js 16 + Tailwind, a standalone server. Own design system, sage theme. One folder per page in `web/app/(app)/`; `web/app/(redirects)/` only holds the old Dutch paths (see "Old paths") |
| `tools/db.py` | Database schema and all reads/writes (SQLAlchemy Core; Postgres in prod, SQLite in tests) |
| `tools/sync.py`, `tools/fit.py`, `tools/store.py`, `tools/intraday.py` | Garmin sync, FIT stream parsing, record normalisation and merge rules, Garmin's series through the day (heart rate, stress, Body Battery, breathing, SpO2, sleep stages) |
| `tools/apple_health.py`, `tools/apple_import.py`, `api/apple.py` | Apple Health import: read the export of the Health app as a stream, store it like Garmin's data (source `apple`), the upload endpoint with background progress |
| `tools/zones.py`, `tools/analytics.py`, `tools/summarize.py`, `tools/routes.py`, `tools/recommend.py` | Zones, training load (CTL/ATL/TSB), sessions, route recognition, route suggestions |
| `scripts/seed_demo.py` | Demo user with six months of synthetic data (also seeds the example account, `api/example.py`) |
| `scripts/make_apple_export.py` | A synthetic Apple Health `export.zip` (iPhone + Watch, old and new export shapes) to test the Apple import |
| `scripts/screenshots.mjs` | Retakes the README screenshots (`docs/screenshots/`) from a local instance with the demo user, in English (Playwright) |
| `packages/websec` | Shared with wealth-tracker (stdlib + Starlette only): client IP behind trusted proxies, rate limiter, security headers, CSRF origin check, log redaction, upload guards; tested in `packages/websec/tests` |
| `api/account.py` | Export and deletion of your own account |
| `docker-compose.yml`, `deploy/` | Self-hosting: the API and the site with Postgres, the shared edge (Caddy + cloudflared), backups (`docs/SELF_HOSTING.md`) |
| `tests/` | pytest, one file per module |

## Working on it

```bash
uv venv .venv && uv pip install -p .venv -r requirements-dev.txt
.venv/bin/pytest -q                      # must stay green, no warnings
(cd .. && npm ci) && cd web && npm run build   # npm install at the repo root; the Next server in web/.next
```

Local run: `DATABASE_URL=sqlite:///dev.db .venv/bin/python scripts/seed_demo.py` (demo data; `dev.db` is git-ignored), create
`.env.dev` (git-ignored) with `DATABASE_URL=sqlite:///<absolute path>/dev.db`, a random `TRAINING_JWT_SECRET`,
`COOKIE_SECURE=false` and `ALLOW_INSECURE_DEFAULTS=true` (or an `APP_ENCRYPTION_KEY`), then `set -a; . ./.env.dev; set +a; .venv/bin/uvicorn api.main:create_app --factory --port 8765` and open
http://localhost:8765/api/health.
For the site: run the API on port 8000 and `cd web && npm run dev` (hot reload; `/api/*` goes to :8000).

Docker check before touching a Dockerfile: `docker build -f health-tracker/api/Dockerfile -t health-api:test .` from the repo root, then `docker run --rm -p 18000:8000 health-api:test`, then `curl localhost:18000/api/health`; the same for `web/Dockerfile` (port 3000, `curl localhost:13000/login/`).

### Rules

1. **Tests first** for backend logic (pytest). Run the full suite before every push.
2. **Secrets never in files or commits.** `.env.dev` and `.dev-credentials` are git-ignored and local only.
3. **Health data is private.** Every API route except `/api/health`, `/api/auth/config`, `/api/login` and `/api/register`
   requires auth and returns only the caller's data. Never add a public route that returns activities, GPS or wellness.
4. **Zones** always come from the user's zones setting (`settings` key `zones`), never from Garmin's `hrTimeInZone_*`.
   Each activity carries `hr_zones_s` computed with its own sport's zones.
5. **Split runs**: runs with <= 30 min gap are one session (`run_sessions` in `tools/summarize.py`). A run after swim/bike
   (triathlon/brick) is not comparable to a standalone run.
6. **Sports**: `tools/sports.py` turns Garmin's type key (with its parent type) or Strava's type into one code: every
   running, cycling or swimming variant is `run`, `ride` or `swim`; e-bikes (`e_bike`) and hand cycling stay apart;
   other sports keep Garmin's key without `_v2`/`_ws`. `web/lib/sports.ts` has a name in both languages and an icon
   group for each code; `tests/test_sports.py` checks all of Garmin's types (`tests/garmin_activity_types.json`) are
   there. A multisport activity (triathlon, brick, swimrun) is stored as its legs, without the transitions; the legs
   share the parent's FIT file, each with its own time window (`tools/sync.py` `multisport_legs`).
7. **Open water**: an open-water swim takes the timer time (Garmin's moving time is broken there) and a pace outside
   1:00-4:00/100m means its GPS distance is wrong: `tools/distance.py` `counted` (applied in `api/data.py`) then gives it
   no distance, so totals, paces and plans leave it out; the GPS value stays as `gps_distance_km`. The user's
   correction is source `manual`, first for `distance_km`, so a later sync keeps it.
8. **No personal text in the UI**: explanations about health and performance live in `web/lib/texts.ts` and take the
   user's own numbers as parameters.
9. **Two languages**: every text in the UI comes from `useT()` (`web/lib/i18n`), never a string in a component; numbers
   and dates go through `useFormat()`. `npm run check:i18n` (also run by pytest) must stay green.
10. **Frontend**: reuse `web/components/ds`, `Card`, `charts/*` and the CSS tokens in `web/app/globals.css` (`--sage-*`,
   `--zone-1..5`, `--chart-*`). Light and dark mode must both work, and phone width without horizontal scroll.
11. **No empty space in cards**: content length varies (one sport or three, a short or a long text), so never pair cards
   in grid rows, where the tallest card stretches its neighbour. Cards side by side go in `Columns`
   (`web/components/ds/Columns.tsx`: two independent stacks, one interleaved column on a phone); a plain two-column grid
   gets `items-start`. Both columns end level: give `Columns` a `filler`, a list that shows as many rows as fit
   (`ds/useFitRows.ts`, e.g. recent activities), and put a list card last in a column with `fill` (upcoming sessions).
   Charts with a time axis (Trends, Form on Today) take the full width.
12. **Commits**: small and descriptive.
13. **Security**: a new state-changing route is covered by the CSRF origin check and the body limit automatically;
    a new upload streams with a limit (`packages/websec/trackerai_websec/uploads.py`) and checks a zip before unpacking it; markdown is only
    rendered through `components/log/Markdown.tsx`; never `dangerouslySetInnerHTML` with user or agent text; no inline
    `<script>` beyond the one in `app/layout.tsx` (the CSP allows each page's inline scripts by hash, computed from the
    built HTML); no external scripts, styles or images (the CSP allows only this site and the OSM tiles).

## Languages

The site is in Dutch (`nl`, the source) and English (`en`, en-GB formatting: 5.3 km, 4 Oct 2026, 24-hour clock).

| File | What |
|---|---|
| `web/lib/i18n/nl.ts`, `en.ts` | the texts, same keys; `en` is typed as `Messages` (= `typeof nl`), so a missing or extra key or other parameters is a type error. Texts with numbers or names are functions; plurals with `f.plural(n, {one, other})` |
| `web/lib/texts.ts`, `web/lib/i18n/texts.en.ts` | the health and performance explanations (`T`): Dutch source and English; reached as `useT().texts`. A Dutch key without English falls back to Dutch and fails `check:i18n` |
| `web/lib/i18n/format.ts` | `useFormat()`: numbers, km, km/u or km/h, pace, durations, dates, lists |
| `web/lib/i18n/index.tsx` | provider, `useT`, `useFormat`, `useLocale`, `errorText` (API error code in the user's language), `routeName` (generated loop names) |
| `web/lib/i18n/rich.tsx` | `rich(text, {link, b})` for a link or bold word inside a translated sentence (`<link>…</link>`) |
| `web/scripts/check-i18n.mjs` | key parity of both catalogs and of T, and a grep for Dutch strings in converted files (`// i18n-ignore` to allow one) |

Adding a string: add the key to `nl.ts` and `en.ts`, use `const t = useT()` and `t.area.key` (or `t.area.key(params)`), run
`npm run check:i18n`. An API text the site shows is a code with params (`ApiError`, see Errors), never a sentence.

Which language: the account's `locale` (`GET /api/me`, set with `PATCH /api/account {locale}` from Settings, Account,
or at registration); without one the last choice on this device (localStorage `locale`, also the switch on the login
page), else the browser language (Dutch browsers Dutch, everything else English). `<html lang>` follows, set before
the first paint by an inline script in `web/app/layout.tsx`.

## Old paths

The pages moved from Dutch to English paths. The old paths still work: each has a tiny client page in
`web/app/(redirects)/` that replaces the URL with the new path and keeps the query string and anchor
(`web/components/Redirect.tsx`). `tests/test_web_routes.py` checks the list below and that every internal link points to
an existing page. Remove a redirect (and its line in that test) once nobody uses the old URL any more.

| Old | New |
|---|---|
| `/historie/`, `/historie/activiteit/?id=` | `/history/`, `/history/activity/?id=` |
| `/rondjes/`, `/rondjes/rondje/?id=` | `/routes/`, `/routes/route/?id=` |
| `/instellingen/` (`koppelingen`, `beheer`, `zones`, `agents`) | `/settings/` (`connections`, `admin`, `zones`, `agents`) |
| `/analyses/doelen/`, `/analyses/profiel/` | `/analyses/goals/`, `/analyses/profile/` |
| `/help/handleiding/` | `/help/guide/` |
| `/health/?day=` | `/dashboard/body/?day=` (Today, Sleep & body) |
| `/health/over-time/` | `/trends/recovery/` |

The ids followed in schema 3: onboarding page ids (`visited`: `routes`, `history`), plan statuses (`active`, `finished`,
`stopped`), nav and catalog keys (`nav.items.routes`, `nav.tabs.connections`, ...) and the guide's anchors (`#data`) are
English. `tools/db.py` `_migrate_v3` converts the Dutch values a schema 2 database holds; the API also still accepts the
old onboarding page ids and plan statuses in Dutch from MCP agents. Generated route names are English too ("6.0 km loop
(r1)"); the site shows them in the user's language and still recognises the Dutch ones.

## API contract

Every route except `/api/health`, `/api/auth/config`, `/api/login`,
`/api/register` needs the session cookie or `Authorization: Bearer <agent token>`, and sees only the caller's data.
`current_user` (api/users.py) returns a `User` (id, username, is_admin, via cookie|agent, `store` = that user's `DataStore`,
`scope` = `db.Scope`); routers read from it, never from a global store. Every `tools/db.py` function for user data takes a
`Scope(engine, user_id)`.

| Method | Path | What |
|---|---|---|
| GET | `/api/auth/config` | `{registration: closed\|invite\|open, first_user, privacy: {controller, contact, version}}` (public) |
| POST | `/api/register` | `{username, password, display_name?, invite?, locale?: nl\|en, consent: true}` (422 `consent_required` without consent; time and privacy version stored); first user on an empty install becomes admin; `example` is reserved (409 `username_reserved`); 5 per hour per IP |
| POST | `/api/login` | `{username, password, totp?}`; 401 `bad_credentials`, `totp_required` (password right, two-step login on), `totp_invalid`; 429 `too_many_attempts` after 10 failures per username or 30 per IP in 15 min |
| GET | `/api/me` | `{id, username, display_name, is_admin, via, totp_enabled, locale: nl\|en\|null, betas[]}`; `null` = never chosen, the site follows the browser; `betas`: the beta features switched on for you (api/betas.py) |
| POST | `/api/account/totp/setup`, `/api/account/totp/enable` `{code}`, `/api/account/totp/disable` `{password, code}` | two-step login: `{secret, otpauth_uri}`, then `{backup_codes}` (shown once); enable and disable end every other session |
| GET | `/api/account/export` | a zip: JSON per table of your data and the FIT files (site login only) |
| DELETE | `/api/account` | `{password, totp?}`: the account and all its data; 409 `last_admin`, `account_busy` |
| PATCH | `/api/account` | `{display_name?, locale?: nl\|en}` (site login only); returns the user with `locale` |
| POST | `/api/account/password` | `{current, new}`; new passwords: ≥ 10 characters, not common (`password_too_common`), not the username; ends every other session |
| GET/PATCH/POST/DELETE | `/api/trackerai/admin/accounts…`, `/registration`, `/invites` | the shared account tools (packages/accounts), for the shared admin page; account admins only |
| POST/GET | `/api/feedback` | send `{kind: bug\|idea, message, page?, context?, screenshot?: data URL}` (site login; 20 a day) / your own, with status and reply |
| GET | `/api/feedback/{id}/screenshot` | its sender or an admin |
| GET/PATCH | `/api/admin/feedback`, `/api/admin/feedback/{id}` | everyone's (`?status=`) / `{status?: new\|planned\|fixed\|wontfix, reply?}`; admins only. MCP: `list_feedback`, `update_feedback` for an admin's token. Every feedback item: `{id, app: "health", kind, message, page, context, status, reply, created_at, updated_at, account_id, username, has_screenshot}` (`account_id`/`username`: the sender's trackerai account) |
| GET | `/api/admin/tracker` | for the admin hub at trackerai.nl/admin: `{app: "health", betas: [{id, name: {en, nl}}], measure, weekly: [{week, value}] (12 ISO weeks, workouts by start date), accounts: [{account_id, betas, count, last_at}]}`; admins only (cookie) |
| PATCH | `/api/admin/tracker/betas/{account_id}` | `{feature, enabled}` -> that account's entry; 404 `account_not_found`, 422 `unknown_beta`; in `admin_audit` |
| GET | `/api/connections` | `{garmin: {connected, readable, connected_at, last_sync, last_failed, syncing}}` |
| POST | `/api/connections/garmin` | `{email, password}` -> `{status: connected\|mfa}`; password only goes to Garmin, the session is stored encrypted |
| POST | `/api/connections/garmin/mfa` | `{code}` (within 10 min) |
| DELETE | `/api/connections/garmin` | disconnect (data stays) |
| GET | `/api/connections/wahoo/start` | `{url}`: Wahoo's login page with a one-time state (15 min); 503 `wahoo_not_configured` without WAHOO_CLIENT_ID/SECRET |
| GET | `/api/connections/wahoo/callback` | where Wahoo sends the browser back (`code`, `state`): tokens stored encrypted, first sync started; redirects to `/settings/connections/?wahoo=connected\|denied\|expired\|failed` |
| DELETE | `/api/connections/wahoo` | revoke the access at Wahoo and remove what came in through it (source `wahoo_api`; uploaded files stay) -> `{ok, removed, changed}` |
| POST | `/api/connections/sync` | sync now in the background |
| GET/PUT | `/api/settings/zones` | `{percent[4], sports: {run\|ride\|swim: {max_hr, estimate}}}`; bounds computed, derive re-runs; GET adds `suggested_max` from the user's data |
| GET/PUT | `/api/settings/profile` | `{birth_year?, weight_kg?, height_cm?, resting_hr?}` |
| GET/PUT | `/api/onboarding` | `{choice: site\|claude\|null, done, step, hidden[], visited[], status, steps: {garmin, sync, zones, profile, explore, agent, goals, plan}, required_done}`; PUT takes only what changes: `{choice?, done?, step?, hide?: checklist\|data, visit?: dashboard\|trends\|routes\|history}` |

Sync: `web` runs a daily sync for every connected user after 06:00 Europe/Amsterdam (`api/sync_runner.py`, off with `SYNC_IN_WEB=false`); the optional cron `sync` (`tools/sync.py run_all_users`) does the same.

Existing:

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{"status":"ok"}` |
| POST | `/api/login` | body `{username,password}`; sets httpOnly cookie `training_session` |
| POST | `/api/logout` | clears cookie |
| GET | `/api/me` | `{username}` |
| GET | `/api/dashboard` | see `web/lib/training.ts` type `Dashboard` Also: `form.until`, `form.stopped_at_sync` (series ends at the last synced day when the sync is older than yesterday), `form.load {band: low\|build\|high\|unknown, acwr, ramp, reason, thresholds}`; `recent[]` may carry `parts`, `activity_ids`, `race`; with an active plan `plan_week {start, end, sports, sessions}` and `race {date, days, name, distance_km, sport}`; `readiness {verdict, date, no_night, signals: [{key: resting_hr\|respiration\|sleep_h\|body_battery\|tsb, value, level, note: {code, params}}], illness_hint}` (codes, no sentences). |
| GET | `/api/activities?sport=&from=&to=` | `ActivitySummary[]`, newest first; runs with implausible wrist HR carry `hr_flags: [low_start\|flat\|dropout]` |
| POST | `/api/activities/upload?name=&recompute=true` | one FIT file (or a zip with one) as the raw body: a ride or run from a Wahoo or any other device. Merged into an activity that starts within 2 min (Garmin stays leading), else added; `{status: added\|merged, id, sport, start_local, distance_km, source: wahoo\|fit, merged_with[]}`. Errors: `upload_empty`, `upload_too_large`, `fit_unreadable` |
| POST | `/api/apple/upload` `{name, size}` | start a chunked upload (what the site uses) -> 201 `{upload_id, chunk_size, max_bytes}` |
| PUT | `/api/apple/upload/{id}/{index}` | part `index` as the raw body, exactly `chunk_size` bytes (the last one the rest), in order; the last part again is fine -> `{received, size}`. Errors: `upload_not_found` (404, also someone else's id), `upload_out_of_order` (409), `upload_size_mismatch` (422) |
| POST/DELETE | `/api/apple/upload/{id}/finish`, `/api/apple/upload/{id}` | all parts in: checked and imported in the background -> 202 as below (`upload_incomplete` 409) / give up |
| POST | `/api/apple/import?name=export.zip` | the whole export (`export.zip`, or `export.xml` alone) as one raw body (scripts; Cloudflare refuses bodies over 100 MB), streamed to a temporary file (max `APPLE_IMPORT_MAX_MB`, 2 GB); a zip is checked before it is read; read in the background -> 202 `{running, progress, last}`. Errors: `upload_empty`, `upload_too_large`, `not_an_export` (not a zip or XML, or a zip that unpacks to too much), `apple_import_running` (409) |
| GET | `/api/apple/import` | `{running, progress: {step: read\|workouts\|days\|derive, done, total} \| null, last: {status: done\|failed, file, workouts, added, merged, days, nights, staged_nights, kept_garmin_days, intraday_days, first, last, sports, exported, imported_at, error} \| null}` |
| DELETE | `/api/apple/import` | remove what the import brought in (activities with source `apple`, wellness days and intraday rows with `source: apple`) -> `{removed, changed, days, intraday_days}` |
| POST | `/api/activities/recompute` | zones and routes again, after a batch uploaded with `recompute=false` |
| GET | `/api/activities/{id}` | summary + `laps` + `track {latlng, zone}` + `series {time, heartrate, velocity, altitude}` (≤ 1500 points) |
| PATCH | `/api/activities/{id}` | `{distance_km: number\|null}`: the real distance (0.01-1000 km) when GPS got it wrong; null removes the correction; returns the detail |
| GET | `/api/wellness/day?day=YYYY-MM-DD` | one day of health data (the Health page; without `day` the latest): `{day, prev, next, latest, from, to, series {hr, stress, bb, resp, spo2: [minute, value][]}, sleep {start, end, stages [{start, end, stage: deep\|light\|rem\|awake}]}, next_sleep_start, summary (the day's wellness row), normals {resting_hr, sleep_hr, sleep_h, sleep_resp, sleep_stress, bb_charged_sleep, spo2_avg, stress_avg} (60-day medians), hr_min, hr_max, night {lowest, lowest_at, avg, last_avg, before_avg, rise, minutes}}`; minutes after local midnight, the evening before negative. The series come from table `intraday` (tools/intraday.py), fetched with wellness: the first time the last 14 days, at most 90 days back |
| GET | `/api/heatmap?sport=run` | `{tracks: [lat,lon][][]}` (≤ 300 points per track) |
| GET/PUT | `/api/docs/{profile,goals}` | `{key, body, updated_at, updated_by}` |
| GET/POST | `/api/entries?kind=log,analysis` | list / create `{kind, title, body, day?}` |
| GET/POST/PATCH/PUT | `/api/plans`, `/api/plans/active` (`{persistent, plan}`), `/api/plans/{id}`, `/api/plans/{id}/sessions`, POST `/api/plans/import` | plans with matched sessions, see `api/plans.py` and `web/lib/training.ts` `Plan`; a session whose `route_id` is one of the user's loops gets `route: {id, name, distance_km}` instead of `route_suggestion`; import returns `warnings` (Dutch text) and `warning_codes: [{code, params}]` |
| GET | `/api/zones?period=week\|month&offset=0` | `{period, offset, start, end, label, is_current, zones: {all?, <sport>: {seconds, total_s, pct}}, bounds}`; offset 0 = current period |
| GET | `/api/zones/history?period=week\|month&count=12&sport=all` | `{period, sport, sports, items: [{start, end, label, seconds, total_s, pct}]}` oldest to newest, last = current; count ≤ 104 weeks / 36 months |
| GET | `/api/context` | bundle for AI assistants (profile, goals, zones, active plan, dashboard, routes, recent log/analyses) |

More (types in `web/lib/training.ts`):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/trends` (also `recovery_daily: {date, resting_hr, sleep_h, body_battery_high, stress_avg, hrv, sleep_resp, sleep_stress, bb_charged_sleep, spo2_avg}[]`, one row per day, oldest first; `recovery_normals` the 60-day median of each) | `{form: FormRow[], weekly: {week, sports: Record<sport,{km,seconds,count}>}[], z2_pace: {week, pace_s_per_km, runs}[], vo2max: {date, value}[], recovery_weekly: {week, resting_hr, sleep_h, body_battery_high, stress_avg}[], records: Record<"1k"|"5k"|"10k"|"21k", {date, seconds, activity_id}[]>, races: {date, name, sport, seconds, distance_km}[]}` Also: `recent_records`, `goal {km, seconds, date, text}` (from the active plan; null without one), `longest_runs`, `hr_flags [{id, date, name, reasons}]`, `form_until`, `stopped_at_sync`; `records[*].source: split\|race`; `insights [{level, code, params}]` (codes, no sentences). |
| GET | `/api/routes?sport=run\|ride`, `/api/routes/suggest?km=&sport=&tolerance=&start=`, GET/PATCH `/api/routes/{id}` | routes (`r<n>` runs, `f<n>` rides; `median_pace` for runs, `median_speed_kmh` for rides) and suggestions of one sport (`km` ≤ 300); summaries include `distance_variants` |
| GET | `/api/routes/candidates?sport=run\|ride` | `{candidates: [{sport, outcome: same\|candidate, confidence, reason_code, reason, a, b}], last_sync}`; each side `{id, kind: route\|activity, name, distance_km, runs, last_run?\|date?, track (≤ 150 points)}`; answered pairs are left out |
| POST | `/api/routes/candidates` | body `{a, b, same}`; records the decision (setting `route_decisions`), applies a merge right away; returns `{applied, applied_on_next_sync, route, remaining}`; 404 if the pair is not open |

### Example data (first-run walk)

`api/example.py`. While the tour's walk past the pages is on a page step, the site sends `X-Example-Data: 1`
(`web/lib/api.ts`, switched by `web/lib/exampleData.ts` from the coach mark) so a new account does not walk past empty
pages. For a site login, GET requests to the data routes (`/api/dashboard`, `activities`, `heatmap`, `trends`, `plans`,
`docs`, `entries`, `context`, `routes`, `zones`, `wellness`, `settings/zones|profile|resting-hr`) are then answered from
a shared example account: `scripts/seed_demo.py` with fixed seeds, made-up loops around its own invented start point,
in a separate SQLite database (`EXAMPLE_DATA_DIR`, default the temp dir) that is seeded on first use (at startup in
production), made again when the date changes, and opened read-only (`mode=ro`). Every POST/PUT/PATCH/DELETE carrying
the header gets 403 `example_read_only`. Who you are, account, connections, agent tokens, feedback and onboarding stay
your own (the site does not send the header there). Admin, MCP and `/api/agent-tokens` routes and Bearer-token
requests ignore the header. The site resets its data queries when the walk enters or leaves the page steps, so example
and real data never share the cache.

### MCP

`api/mcp.py`: Model Context Protocol over streamable HTTP (stateless, JSON responses, no SSE). `POST /api/mcp` with
`Authorization: Bearer <agent token>`, or `POST /api/mcp/<agent token>` for clients that cannot send headers. Tokens
only (no session cookie); 20 failed tokens per IP in 15 minutes; the path token is masked in the logs.
Tools: `get_context`, `list_activities`, `get_activity`, `get_day`, `get_trends`, `get_plan`, `create_plan` and `replace_plan_sessions`
(markdown/CSV table, `preview`), `set_plan_status`, `add_log`, `list_log`, `get_doc`, `update_doc`, `suggest_route`.
Results are markdown text (trends as JSON). Writes are authored `agent`.

Connect: see "Connect an AI assistant" in the README. The token can sit in the connector URL; treat that URL as a
password and delete the token under Settings, Agents if it leaks.

Tested with the official `mcp` Python SDK client (initialize, tools/list, tools/call) and in `tests/test_mcp.py`.

If a contract changes, update this table in the same commit.

### Errors

Errors raised with `api.errors.ApiError` answer `{detail, code, params}`: `detail` is the Dutch text (agents, scripts,
MCP), `code` + `params` is what the site translates (`errors` in `web/lib/i18n/nl.ts` and `en.ts`). New user-facing
errors use a code: add it to `MESSAGES` in `api/errors.py` and to both web catalogs. FastAPI's own validation errors
(422 with a list) have no code.
