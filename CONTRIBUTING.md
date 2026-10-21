# Contributing

Thanks for taking a look. This is a personal project, but issues and pull requests are welcome.

## Running the apps

The repository is one npm workspace with three apps and their shared packages. Run `npm ci` once at the root, then
follow the app's own README:

- [health-tracker](health-tracker/README.md): training, sleep and recovery.
- [wealth-tracker](wealth-tracker/README.md): money and portfolio. "Try it locally with demo data" starts it with an
  invented account.
- [trackerai](trackerai): the front door at trackerai.nl.

Shared code lives in [packages/](packages). [CLAUDE.md](CLAUDE.md) has the agreements that hold everywhere: shared code
first, nothing per person or per deployment in code, and every user-facing text in English and Dutch.

## Branches and pull requests

Work in a branch and open a pull request. Every pull request runs the checks in [docs/CI.md](docs/CI.md); they all need
to be green before it merges. Keep one change per pull request, and fill in the template.

## Tests

Run the tests for what you touched, and both apps when you touch `packages/`:

- `health-tracker/`: `python -m pytest -q tests`; in `web/`: `npx tsc --noEmit -p .` and `npm run check:i18n`.
- `wealth-tracker/`: `TZ=Europe/Amsterdam python -m pytest backend/tests -q`; in `frontend/`: `npx tsc --noEmit -p .`,
  `npm run check:i18n` and `npm test`.
- `trackerai/api`: `python -m pytest -q`.
- `packages/accounts`, `packages/websec`, `packages/ai`: `python -m pytest -q` in each; `packages/ui`:
  `npm test --workspace @trackerai/ui`.

## Formatting and lint

Python is formatted and linted with [ruff](https://docs.astral.sh/ruff/) (`ruff.toml`), TypeScript and the rest with
Prettier and ESLint (`.prettierrc.json`, `eslint.config.mjs`). The versions are pinned, because formatter output changes
between releases. The `lint` workflow checks all of it on every pull request.

The easiest way to stay green is pre-commit, which runs the same checks on every commit:

```bash
pipx install pre-commit && pre-commit install
```

Or by hand before pushing: `ruff check .`, `ruff format --check .`, `npm run lint` and `npm run format:check` at the
root (`ruff format .` and `npm run format` fix the formatting).

The commit that formatted the whole repository is listed in `.git-blame-ignore-revs`. GitHub's blame skips it; for
local blame run `git config blame.ignoreRevsFile .git-blame-ignore-revs` once.

## Security

Found a vulnerability? Please do not open an issue; see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
