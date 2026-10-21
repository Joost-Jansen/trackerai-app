## What

<!-- The change, in a few lines. -->

## Why

<!-- The problem it solves, or the issue it closes. -->

## How tested

- [ ] `health-tracker/`: `python -m pytest -q tests`; `web/`: `npx tsc --noEmit -p .`, `npm run check:i18n`
- [ ] `wealth-tracker/`: `TZ=Europe/Amsterdam python -m pytest backend/tests -q`; `frontend/`: `npx tsc --noEmit -p .`, `npm run check:i18n`, `npm test`
- [ ] `trackerai/api`: `python -m pytest -q`
- [ ] `packages/`: the tests of the package, and both apps
- [ ] Tried it in the browser

## Screenshots

<!-- For a UI change: before and after. -->
