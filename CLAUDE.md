# For agents

Two apps and their shared code in one repository: `health-tracker/`, `wealth-tracker/` (the former stock-tracker,
portfolio plus money) and `packages/` (shared), plus `trackerai/`, the front door at trackerai.nl (login, sign-up,
the admin page of every tracker; step 11 of the plan). Start with [README.md](README.md) and
[docs/PLAN.md](docs/PLAN.md).
Each app has its own rules too: `wealth-tracker/CLAUDE.md` applies to everything in `wealth-tracker/`.

Agreements that apply everywhere:

- **Shared first.** Before adding a component, hook, token, backend helper or page that the other app has or will
  need, put it in `packages/` (or move the existing copy there) instead of writing it twice.
- **App-specific code stays in the app.** Domain logic (training zones, sleep, holdings, bank categorisation) is not
  shared; a shared package never imports from an app.
- **No per-person or per-deployment values in code.** Domains, hosts and names come from environment variables, so
  anyone can run their own installation (e.g. `LANDING_HEALTH_URL`, `PUBLIC_ORIGINS`).
- **Security conventions are shared.** Both backends use `packages/websec` (rate limits, security headers, CSRF origin
  check, log redaction, upload checks) and `packages/accounts` (password policy, two-step login), the same environment variable names
  (`APP_ENCRYPTION_KEY`, `PUBLIC_ORIGINS`, `TRUSTED_PROXIES`, `SESSION_DAYS`, …), the same error codes and the same
  `/api/account/*` endpoints. Keep them the same; change both together.
- **English** for code, comments and commits. The UI is bilingual (Dutch and English); every user-facing text needs
  its Dutch, checked by `npm run check:i18n` in each frontend.
- **Branches**: work in a branch and open a pull request into `main` (production); the required checks must be green
  ([docs/CI.md](docs/CI.md)). A pull request lands as one squash commit; a new job joins its workflow's `ok`.
- **Format and lint before pushing**: `ruff check .`, `ruff format --check .`, `npm run lint` and `npm run format:check`
  at the root, or `pre-commit install` once so they run on every commit.
- **Test the app you touched**, and both apps when you touch `packages/`. The Python suites run on Postgres, as
  production does: start it once with `docker compose -f compose.dev.yml up -d` at the repo root and install
  `packages/testing` in the app's environment (`pip install -e packages/testing`); every test gets a database of its own.
  - `health-tracker/`: `python -m pytest -q tests`; in `web/`: `npx tsc --noEmit -p .` and `npm run check:i18n`.
  - `wealth-tracker/`: `TZ=Europe/Amsterdam python -m pytest backend/tests -q`; in `frontend/`:
    `npx tsc --noEmit -p .`, `npm run check:i18n` and `npm test`.
  - `trackerai/api`: `python -m pytest -q`.
- Renaming a stored name (table, column, settings key) needs a migration step so existing databases keep working.
