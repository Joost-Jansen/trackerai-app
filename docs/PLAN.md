# Plan: from two apps side by side to one codebase with shared packages

Both frontends are forks of one codebase on the "Meridian" design system. Both run Next 16, React 19, Tailwind 3.4
and TypeScript 5.7, and their Tailwind configs are identical. The fonts, the layout skeleton and most primitives are
the same, and so is the token structure. The two backends share one `websec` package (packages/websec), the
same environment variables, error codes and `/api/account/*` endpoints.

The apps differ in four ways:

1. **Brand:**
   - health-tracker: a cool green-grey neutral ladder with a sage accent;
   - wealth-tracker: warm paper with a terracotta accent.
2. **i18n:**
   - health-tracker: typed catalogs with `useT()`, and live switching between languages;
   - wealth-tracker: `tr("English")` with a flat Dutch map, and a reload when the language changes.
3. **Backend contracts:**
   - auth paths;
   - the error shape;
   - who decides about example data.
4. **Build:**
   - both: a Next standalone server plus a FastAPI api (health-tracker since 11.5).

Done: steps 1, 2, 4 (apart from archiving the old repositories), 5, 8, 10 and most of 6. Every step below is its own PR; each leaves both apps deployable.

Current work: step 11 (trackerai as a service of its own, one server setup for every app). Its table says who is on
which part; update your row there before you start.

## 1. Import (done)

- Both repositories were imported with their full history: `health-tracker/` and `wealth-tracker/`.
- CI runs at the root, one workflow per app with path filters.
- `scripts/import-old-repos.sh` brings in new commits from the old repositories until Railway deploys from here.

## 2. Workspaces and build contexts (done)

The apps must be able to import from `packages/` before anything moves there.

Done:
- the npm workspace and the one root lockfile; `transpilePackages`; Tailwind scans `packages/ui`;
- both frontend images build from the repo root;
- CI builds both images;
- `packages/ui` exists, with its first module, `screenshot` (it was identical in both apps).

- the backend half: every image builds from the repo root and installs the Python packages (`packages/accounts`,
  `packages/websec`); CI installs them next to each app's requirements.

The steps:

- **Frontend:**
  - add a root `package.json` with npm workspaces: `health-tracker/web`, `wealth-tracker/frontend`, `packages/*`;
  - use one lockfile;
  - add `transpilePackages` in both `next.config` files, so packages ship as TSX and CSS without a build step.
- **Backend:**
  - Python packages under `packages/` get a `pyproject.toml`;
  - the apps install them as a path dependency (`-e ../packages/websec`).
- **Docker:**
  - build from the repo root, so `packages/` is inside the build context;
  - each Dockerfile copies only its app and the packages it uses;
  - check that both images still build and pass their healthchecks.

## 3. Shared deploy (M)

- **Edge:** move `health-tracker/deploy/edge` and `health-tracker/deploy/backup` to a top-level `deploy/`.
- **Compose:** one compose file runs every container on the mini PC:
  - health-web;
  - stock-api;
  - stock-web;
  - **wealth-web**, the money build, which also serves the front door (`LANDING_HOSTS`);
  - Caddy and cloudflared.
- **Caddy and tunnel hostnames:**
  - health.
  - stock.
  - wealth.
  - the bare domain;
  - www.
- Merge the two `SELF_HOSTING.md` files into `docs/SELF_HOSTING.md`.

## 4. Railway deploys from here; archive the old repositories (S), deploys done

- Point each Railway service at this repository:
  - set its root directory or Dockerfile path;
  - set watch paths `health-tracker/**` or `wealth-tracker/**`, plus `packages/**`.
- Run `scripts/import-old-repos.sh` a last time.
- Archive `health-tracker` and `stock-tracker` on GitHub (read-only; their links keep working).
- From here on, all work happens in this repository.

## 5. `packages/websec` (done)

- The two copies are one package ([packages/websec](../packages/websec)), installed by both images like
  `packages/accounts`, with one test suite of its own.
- One name each: `RedactFilter`, `save_upload` (next to the async `stream_to_file`), `ZipRejected`.
- CSRF: a cookie write with neither Origin nor Referer is refused in both apps (wealth-tracker's rule); a request
  without the session cookie is not checked.

## 6. `packages/ui` (mostly done)

Shared now (packages/ui/README.md lists them):
- the stylesheet: `ds.css`, the tokens and element rules (`base.css`), one palette per app (`brand-sage.css`,
  `brand-terracotta.css`), the Tailwind preset and the fonts; checked pixel-identical in light and dark;
- the DS primitives (Button, Field, Dialog/EmptyState/Tag/Badge, Tabs, SubNav, RowMenu, Section, Card, InfoPopover,
  ThemeToggle), the icon set and the SidebarNav;
- the charts: Bars, LineChart (with both apps' features), ChartHeadline, the axis and date helpers;
- the FeedbackDialog, the API client, the screenshot and error helpers, the language rules;
- the components' own texts, with their own Dutch (`useTr`, checked like wealth-tracker's).

Still per app, to share next:
- the app layout around the sidebar (top bar, page title, tabs, account menu, mobile drawer): 22% alike today;
- the login, register and privacy pages, after their backend paths match (step 9);
- the onboarding mechanics (coach marks, start banner, example-data toggle);
- Logomark stays per app (each has its own mark), passed into the sidebar.

## 7. `packages/i18n` (M, then L)

**One model:** English source strings as keys (wealth-tracker's model), with live switching (health-tracker's
behaviour).

**The package:**
- `createI18n({ catalogs: { nl } })` gives `tr`/`trx` plus a `useTr()` hook that re-renders when the language changes;
- the TypeScript-AST checker becomes the shared `check:i18n`;
- the package ships its own small Dutch catalog for its UI strings, merged into each app's.

**Moving the apps:**
- wealth-tracker switches first; its module-level `tr()` constants (nav, app name) become functions.
- health-tracker converts folder by folder:
  - generate `{english: dutch}` from its `en.ts` and `nl.ts`;
  - function entries become `{0}` placeholders;
  - plurals and rich text need hand work;
  - `useT()` and `tr()` can coexist meanwhile.

## 8. `packages/marketing` (done)

- The public pages for trackerai.nl, and the product pages of health.trackerai.nl and wealth.trackerai.nl. Its start
  is `wealth-tracker/frontend/app/landing`, together with the `LANDING_*` routing in `frontend/proxy.ts`.
- They use `packages/ui` with a neutral brand.
- The links into each app come from the environment, so anyone's own installation works.

## 9. Layout shell and contracts (M each)

- **Layout shell:**
  - `AppShell` and `SidebarNav`, with slots for badges, the avatar menu and help;
  - the nav helpers;
  - a `Brand` object (name, tagline, home, logo, paper colours).
- **Backend contracts:**
  - the same auth paths `/api/auth/login|logout|me|registration-status` (health-tracker keeps its old paths as
    aliases for a while);
  - one error shape `{detail, code, params}`;
  - one `Me` shape;
  - the server decides about example data.
- **On those contracts:**
  - `createApi()` and `ApiError`;
  - FeedbackDialog;
  - the feedback and agents settings pages;
  - the charts (Bars, ChartHeadline, LineChart);
  - the auth pages (login, register, privacy, terms);
  - the onboarding mechanics (coach marks, start banner, example-data toggle).

## 10. One account (`packages/accounts`) (done)

One trackerai account for both apps, with two-step login as part of it ([packages/accounts](../packages/accounts)).

- **The package:** done first, on its own. It has the accounts database, the session cookie on the shared domain,
  login, registration, two-step login (required for admins and for anyone using both apps), joining and leaving an
  app, the admin's account tools, and the import of the existing accounts.
- **health-tracker:** `current_user` comes from the shared session. Its `users` row becomes the app's own user, made
  on the first visit. Its own login, registration, password and two-step routes go.
- **wealth-tracker:** `get_current_user` comes from the shared session. `auth_config.yaml` keeps only what is the
  app's own: beta flags and agent tokens, under the data folder's name.
- **Frontends:** the login pages call `/api/auth/login`. They send someone to two-step setup on
  `totp_setup_required`. The account settings show which apps someone uses, with a way to join or leave one.
- **Deploy:** one accounts database that both backends reach, the same `ACCOUNTS_*` and `SESSION_COOKIE_DOMAIN` on
  every backend, then the import (`python -m trackerai_accounts.migrate`).
- **Needs:** step 2's backend part, so both images can install `packages/accounts`.

## 11. trackerai as a service of its own, and one server setup for every app (L)

**Why:**
- trackerai.nl is hosted by wealth-tracker today. wealth-web serves the front door and the admin page
  (`LANDING_HOSTS`, `app/landing`, `app/api/hub`), and a login on trackerai.nl goes to wealth-tracker's API. A
  broken wealth deploy takes trackerai.nl down with it.
- The apps are built two ways (the Build difference at the top): health-tracker is one image with a static export,
  wealth-tracker a Next server plus an API. Every change to deploys, security or packages has to be done twice.

**The one setup** that trackerai, health-tracker and wealth-tracker all follow:
- **Services:** two per app on Railway, each deployed on its own: `<app>-web` and `<app>-api`.
- **Web:** Next 16 standalone server (`output: "standalone"`), React 19, the `packages/ui` Tailwind preset,
  TypeScript; built from the repo root; `/api/*` rewritten to `API_INTERNAL_URL` (a build argument); the
  Content-Security-Policy with a nonce from `proxy.ts`; port 3000.
- **API:** FastAPI on Python 3.13 with uvicorn; the account from `packages/accounts`, security from
  `packages/websec`; SQLAlchemy on Postgres, one database per app in the one Postgres service; `GET /api/health`
  for the healthcheck; port 8000.
- **Folders:** `<app>/web` and `<app>/api`.
- **Images:** one Dockerfile shape (multi-stage, a non-root user, a healthcheck) and the same environment variable
  names everywhere.

**trackerai** (new, `trackerai/`):
- **trackerai-web** serves trackerai.nl and www: the front door (`FrontDoor` from `packages/marketing`) with login,
  sign-up and two-step login, and `/admin` (`Admin` from `packages/marketing`) for every tracker.
- **trackerai-api** has the account routes from `packages/accounts` (`/api/auth/*`, `/api/account/*`, the admin's
  account tools) on the accounts database, and `/api/hub/{app}/...` to each tracker's own admin API (the allowlist of
  `wealth-tracker/frontend/lib/hub-proxy.ts`, moved to Python). It has no data of its own.
- The session cookie stays on `SESSION_COOKIE_DOMAIN`, so a login on trackerai.nl still opens both trackers.
- Hosts and URLs come from the environment (`HEALTH_API_URL`, `WEALTH_API_URL`, `LANDING_HEALTH_URL`, …), so a
  self-hosted installation works the same.

**Steps and who is on them** (one PR each; every step leaves all apps deployable; put your name in the row and the
date before you start, and set it to done in the PR that finishes it):

| Step | What | Size | Status | Who |
|---|---|---|---|---|
| 11.1 | `trackerai/api`: FastAPI with the account routes and the hub proxy, its tests, image and CI, on `packages/websec`; `make_router` without a default app | M | done (#23) | Claude (trackerai-service session), 2026-10-09 |
| 11.2 | `trackerai/web`: Next app with the front door and `/admin` from `packages/marketing`, its `proxy.ts` and rewrites | M | done (#24) | Claude (admin-hub session), 2026-10-09 |
| 11.3 | Deploy trackerai: Railway services trackerai-api and trackerai-web, tested on their Railway domains, then www.trackerai.nl and trackerai.nl moved to trackerai-web (the DNS change at GoDaddy is Joost's) | S | done: www.trackerai.nl on trackerai-web since 2026-10-09; the CNAMEs at GoDaddy can move to the targets Railway now names | Claude (trackerai-service session), 2026-10-09 |
| 11.4 | wealth-tracker without the front door: `app/landing`, `app/api/hub`, `lib/hub-proxy.ts` and the `LANDING_HOSTS` routing go; the `LANDING_*` variables go from wealth-web. Only after 11.3 is live | S | done (#25) | Claude (trackerai-service session), 2026-10-09 |
| 11.5 | health-tracker in the one setup: `health-tracker/web` becomes a Next standalone server (no static export), `health-tracker/api` its own image; Railway health-web and health-api | M | done (#26) | Claude (admin-hub session), 2026-10-09 |
| 11.6 | `packages/websec` in both apps (step 5): one package from both copies, both apps and their images on it | S | done (#22) | Claude (admin-hub session), 2026-10-09 |
| 11.7 | wealth-tracker on Postgres: from one SQLite file per user to SQLAlchemy on a `wealth` database, with a data migration checked per user and per table | L | in progress: 11.7a done (#28), 11.7b in review | Claude (trackerai-service session), 2026-10-09 |
| 11.8 | Folder names: `wealth-tracker/backend` and `frontend` become `api` and `web` (with the Railway watch paths). Last, when nothing else is in flight | S | open | |

**11.7 in parts** (wealth-tracker keeps working on SQLite until the switch; each part is its own PR):
- **11.7a, the seam:** one connection layer in `wealth-tracker/backend/domain` that every query goes through, on SQLite
  as today or on Postgres when `WEALTH_DATABASE_URL` is set. It speaks the sqlite3 shape the code uses (`?`
  placeholders, rows by name and index, `lastrowid`), so the queries change only where the dialect differs. CI runs
  the backend suite on both.
- **11.7b, the dialect:** the SQLite-only SQL gets a form both accept, or one per dialect where none exists:
  `INSERT OR REPLACE/IGNORE` (16), `strftime`/`datetime` (17), `AUTOINCREMENT` (15), `PRAGMA` (11), `lastrowid` (5).
- **11.7c, the layout:** one `wealth` database in the shared Postgres service, one schema per user (`u_<folder>`), so
  each user's tables stay apart as their files are today and no query needs a user column.
- **11.7d, the move:** a migration command copies each user's SQLite file into its schema and checks it per table
  (row counts and a checksum per table), run on Railway next to the volume; then the API switches to
  `WEALTH_DATABASE_URL`. The SQLite files stay on the volume as a fallback until Joost lets them go.
- **11.7d, how the switch goes:** create the `wealth` database in the Postgres service; set `WEALTH_DATABASE_URL` and
  `WEALTH_MIGRATE_FROM_SQLITE=on` on the api; deploy. The new deployment copies and checks everyone before its
  healthcheck answers (a failure keeps the old one, on SQLite, serving); then `WEALTH_MIGRATE_FROM_SQLITE` goes off.
  Writes in the minute between the copy and the switch-over land in the SQLite files only.
- **After 11.7d, still on the volume:** the installation's `feedback.db`, `auth_config.yaml` (beta flags, agent
  tokens) and the uploads folders. The volume can go only once those have a place too.

**Decided in a step, not up front:**
- **Registering without an app (11.1, done):** `make_router(accounts, None)` is the front door's: a sign-up must name
  its trackers (`apps`), and it mounts no OAuth issuer.
- **The agents' OAuth issuer** (`ACCOUNTS_OAUTH_ISSUER`) stays per app for now; each app's agent tokens are its own.
- **The mini PC compose file** (step 3) gets the trackerai containers in the step that changes it.

## Stays per app

- **Domain components:**
  - health-tracker: zones, maps (Leaflet), the day timeline;
  - wealth-tracker: holdings, allocation, the world map, bank categorisation.
- Long explanatory texts and each app's own nav tree.
- `fmtEu`, which a parity test pins to the backend.
- Domain units (km, pace).

## Risks

- **Trailing slashes:** health-tracker's hrefs end in `/` and wealth-tracker's don't, so shared link helpers normalise.
- **Concurrent work:** land the token PRs quickly and in small pieces, because `globals.css` and `ds.css` conflict
  easily.
- **Keep app-only dependencies out of shared packages:**
  - health-tracker: Leaflet and marked;
  - wealth-tracker: the geo data.
