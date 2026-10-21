# Branches, checks and deploys

`main` is what runs in production: Railway builds every service from it. `dev` is where work comes together before
it goes there. Neither takes a direct push; both take pull requests whose checks are green.

```
feature branch ──PR──▶ dev ──PR──▶ main ──Railway──▶ production
```

## Branches

- **Feature branches** (`nutrition-photo`, `fix-login`, ...): one change each, a pull request into `dev`. They are
  deleted when the pull request merges.
- **`dev`**: the next release. CI runs on every push to it, so what is on `dev` is tested together.
- **`main`**: production. A pull request from `dev` (or, for an urgent fix, from a fix branch) once `dev` is green.

An admin can still push or merge past the rules in an emergency (`gh pr merge --admin`); it is meant to stay rare.

## Checks

One workflow per part of the repository, in `.github/workflows/`:

| Workflow | Tests | Required check |
|---|---|---|
| `health-tracker` | backend (pytest), frontend (tsc, i18n, build), both images | `health-tracker ok` |
| `wealth-tracker` | backend on SQLite and Postgres, frontend, the image | `wealth-tracker ok` |
| `trackerai` | the front door's API and image | `trackerai ok` |
| `trackerai-web` | the front door's site and image | `trackerai-web ok` |
| `accounts`, `websec`, `ai` | the shared Python packages in `packages/` | `accounts ok`, `websec ok`, `ai ok` |

Every Python suite runs on Postgres, as production does: its job has a Postgres service (`TEST_DATABASE_URL`) and
`packages/testing` gives each test a database of its own. Locally the same server comes from `compose.dev.yml`.

A push to `main` or `dev` runs a workflow only when its paths changed. A pull request runs every workflow: a first job,
`changes`, compares the pull request with its base and the jobs only run when the same paths changed; otherwise they
are skipped. The last job, `<workflow> ok`, always runs and is green when every job passed or was skipped. Those
`ok` jobs are the required checks on `main` and `dev`: a skipped workflow still reports, so a pull request is never
left waiting for a check that does not run.

Adding a job to a workflow: give it `needs: changes` and `if: needs.changes.outputs.run == 'true'`, and add it to the
`needs` of `ok`. Adding a workflow: copy that pattern, and add its `ok` check to the branch protection of `main` and
`dev` (Settings, Branches).

## Deploys

Railway (project `trackerai`, environment `production`) builds each service from `main` when a file in its watch
patterns changes:

| Service | Dockerfile | Watches |
|---|---|---|
| `health-api` | `health-tracker/api/Dockerfile` | `health-tracker/api`, `tools`, `scripts`, the shared Python packages |
| `health-web` | `health-tracker/web/Dockerfile` | `health-tracker/web`, `packages/ui`, `packages/marketing`, the npm lockfiles |
| `health-sync` | `health-tracker/Dockerfile.sync` (cron 04:00) | `health-tracker/tools`, its requirements |
| `api` (wealth) | `wealth-tracker/backend/Dockerfile` | `wealth-tracker` (not its frontend or docs), the shared Python packages |
| `wealth-web` | `wealth-tracker/frontend/Dockerfile` | `wealth-tracker/frontend`, `packages`, the npm lockfiles |
| `trackerai-api`, `trackerai-web` | `trackerai/api`, `trackerai/web` | their folder and the packages they use |

A new shared package needs adding to the watch patterns of every service whose image installs it (for example
`packages/ai` for `health-api` and `api`).
