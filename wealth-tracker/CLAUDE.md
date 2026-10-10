# For agents

Besides the portfolio this repo has a second subject, **Money** (bank import,
categorisation, spending, budget, net worth, optionally Claude). Read
**[docs/MONEY.md](docs/MONEY.md)** first: architecture, data model, and how to
test. Hosting (Pi and Railway) is in **[docs/DEPLOY.md](docs/DEPLOY.md)**.

Money sits behind the beta flag `money` (Admin page): in `frontend/lib/nav.ts`
and through `require_money` on every money router. A new money router gets that
dependency too.

Agreements that apply everywhere:

- Every function in the domain layer takes an explicit `conn` as its first argument.
- Bank tables: spending **positive**, income **negative** — do not flip it.
- `category_manual` always wins; a rule round only writes `category_auto`.
- Nothing hardcoded per person or per bank.
- Code, comments and commits in English. The UI is bilingual (Dutch and
  English): user-facing text is written in English inside `tr("…")` /
  `trx("…", <b>…</b>)` (`frontend/lib/i18n`), with its Dutch in
  `frontend/lib/i18n/nl.ts`; backend messages likewise with `tr()` from
  `backend/domain/i18n.py` and Dutch in `backend/domain/i18n_nl.py` (the
  request's language comes from the `X-Locale` header). Codes stay codes
  (`"1Y"`, `"early"`, `"quarterly"`) and get their label where they are shown.
- Category names (`Boodschappen`, `Onbekend`, …) are user data, not code.
- A rename of a stored name (table, column, code value, settings key) needs a
  step in `backend/domain/legacy_names.py`, so existing databases keep working.
- Tests: `python -m pytest backend/tests -q` and, in `frontend/`, `npx tsc --noEmit -p .`
  and `npm run check:i18n` (every text has its Dutch, every Dutch entry is used).
