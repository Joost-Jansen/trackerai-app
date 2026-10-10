# Shared packages

Code used by both apps. A package here never imports from `health-tracker/` or `wealth-tracker/`; the apps import from
here. The packages planned, in the order of [docs/PLAN.md](../docs/PLAN.md):

| Package | What | From |
|---|---|---|
| `ui` | Design tokens (base plus one brand file per app: sage for health, terracotta for wealth), `ds.css`, the Tailwind preset, fonts, the DS primitives (Button, Field, Dialog, Tabs, Card, …), the layout shell | both frontends ("Meridian") |
| `i18n` | One runtime for both frontends: English source strings as keys, Dutch catalogs, live language switching, the `check:i18n` script | wealth-tracker's `tr()` model with health-tracker's live switching |
| `websec` | The web security building blocks of both backends: client IP, rate limits, security headers, CSRF origin check, log redaction, upload guards | once `health-tracker/api/websec` and `wealth-tracker/backend/app/websec`, two copies |
| `accounts` | One account for both apps: login, the session on the shared domain, two-step login, which apps someone uses, the admin's account tools, and the import of the existing accounts | new; replaces each app's own login and two-step login |
| `marketing` | The public pages: trackerai.nl and the product pages of both apps | new; hosted by trackerai-web (`trackerai/web`) |

Each package gets its own README with how an app uses it.
