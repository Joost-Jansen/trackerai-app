# @trackerai/ui

Shared frontend code for both apps, shipped as TypeScript and CSS source: no build step. Each app lists it as a
dependency (`"@trackerai/ui": "*"`, an npm workspace), transpiles it (`transpilePackages` in `next.config.js`), scans
it for Tailwind classes (`content` in `tailwind.config.ts`) and imports the styles in `app/globals.css`.

| Import | What |
|---|---|
| `@trackerai/ui/styles/ds.css`, `styles/base.css` | The Meridian component layer, the tokens and element rules |
| `@trackerai/ui/styles/brand-sage.css`, `styles/brand-terracotta.css`, `styles/brand-dusk.css` | One palette per app (health, wealth, tabstealth): neutral and brand ladders, ink panel, focus ring, chart colours, light and dark |
| `@trackerai/ui/tailwind-preset` | The Tailwind theme (`presets: [preset]`) |
| `@trackerai/ui/ds/*` | Button, Field, Feedback (Dialog, EmptyState, Tag, Badge), Tabs, SubNav, RowMenu, Section, SidebarNav |
| `@trackerai/ui/components/*` | Card, CollapsibleCard (icon and status with expandable content), InfoPopover, ThemeToggle, FeedbackDialog |
| `@trackerai/ui/charts/*` | Bars, LineChart, ChartHeadline |
| `@trackerai/ui/icons` | The line icon set |
| `@trackerai/ui/lib/*` | api (createApi, ApiError, example data), fonts, chartScale, dateTicks, dates, typography, recentErrors, screenshot |
| `@trackerai/ui/i18n`, `i18n/locale` | `UiLocale` and `useTr` for the components' own texts; the language rules |
| `@trackerai/ui/account/TwoStepHelp` | The help page about two-step login of the shared account, in Dutch and English |

## Rules

- A dependency is a `peerDependency`: the apps install it, so there is one copy of React.
- Colours come from tokens: `--brand-*` and the semantic names in `base.css`, never a brand's own ladder.
- A text is English in the code, `tr("…")` from `useTr()`, with its Dutch in `src/i18n/nl.ts`;
  `npm run check:i18n --workspace @trackerai/ui` checks both ways. The app passes its language with `<UiLocale>`.
- `lib/*` modules import each other by package name (`@trackerai/ui/lib/dates`), so node-run tests resolve them.
- After a change here, test both apps (see the root CLAUDE.md).
