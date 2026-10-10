# @trackerai/marketing

The public front door at trackerai.nl. It explains health-tracker and wealth-tracker, each in its own colours and with its own logo. The trackers' own subdomains stay plain login pages.

You can also log in on it, with the trackerai account every tracker shares (packages/accounts). The session cookie is on the parent domain, so after that both trackers open without asking again. Once logged in, the page names you and shows a button per tracker: "Open" for the trackers you use, "Start with" for the others (that tracker's own page then asks to join, and for consent where needed). Signing up happens here too: one trackerai account, an email address (confirmed with the code from the welcome
mail, which then is the two-step login) and the trackers to use, health, wealth or both. The other can be added
later ("Start with"). Each tracker's own `/register` still makes an account with just that tracker.

The page is a server component; the account (`Account.tsx`) is its one client part. Next puts the request's nonce on its scripts, so it works under the strict Content-Security-Policy. All motion is CSS, and it stops under `prefers-reduced-motion`.

## Use

```tsx
// app/layout.tsx
import "@trackerai/marketing/marketing.css";

// app/page.tsx
import { headers } from "next/headers";
import { FrontDoor, localeFrom } from "@trackerai/marketing";

export default async function Page() {
  const locale = localeFrom((await headers()).get("accept-language"));
  return (
    <FrontDoor
      locale={locale}
      urls={{ health: process.env.LANDING_HEALTH_URL, wealth: process.env.LANDING_WEALTH_URL }}
    />
  );
}
```

Add the package to `transpilePackages` in `next.config.js`. The buttons link to `${url}/`; "Create an account" opens the sign-up here (`#signup`). The addresses come from the environment, so any installation works. A tracker without an address is still described, just without buttons.

trackerai-web ([trackerai/web](../../trackerai/web)) serves the front door, with `LANDING_HEALTH_URL` and `LANDING_WEALTH_URL`. The account calls `/api/auth/*` on the page's own origin; trackerai-web forwards them to trackerai-api ([trackerai/api](../../trackerai/api)), which accepts posts from `PUBLIC_ORIGINS`, `https://<SESSION_COOKIE_DOMAIN>` and `https://www.<SESSION_COOKIE_DOMAIN>`.

## The admin page

`trackerai.nl/admin` (`Admin.tsx`, served by trackerai-web)
is one admin page for every tracker, for account admins, in tabs (kept in the URL hash):

- **Overview:** accounts, users per tracker, who logged in this week, two-step login (app or email), what needs
  attention (suspended, email not confirmed), and the settings that matter: sign-up mode, the two-step policy,
  whether mail can be sent, how long "stay logged in" lasts. A few charts over the last 12 weeks (`AdminChart.tsx`):
  accounts, each tracker's own weekly measure, feedback per week. Disk use, when the trackers report it.
- **Accounts:** search, and per account its email, trackers (with each tracker's count and disk use), two-step method
  and last login. Make or remove admin, suspend, beta features per tracker, give or take a tracker, reset the password,
  turn off two-step login, delete. Tick several accounts (or all shown) for the same action on each, one by one,
  with one confirmation for the destructive ones and one summary; never on your own account for admin, suspend and
  delete. Resetting a password stays per account.
- **Feedback:** the trackers' feedback in one list, with status and reply. Users keep their own list in each app.
- **Sign-up:** open, invitation only or closed; invitation links that choose the trackers.
- **Activity:** what admins did, the audit log.

It calls `/api/trackerai/admin/*` (packages/accounts), the shared admin routes under a path no tracker overrides, and
`/api/hub/{health|wealth}/...`, which trackerai-api (`app/hub.py`) forwards to that tracker's own
`/api/admin/tracker`, `/api/admin/tracker/betas/{account_id}`, `/api/admin/feedback[/{id}]` and
`/api/feedback/{id}/screenshot` (health at `HEALTH_API_URL`, wealth at `WEALTH_API_URL`).
A tracker that is not connected or does not answer gets a quiet note; the rest keeps working.

The same page is each tracker's own admin page (health-tracker `/settings/admin/`, wealth-tracker `/admin`), so a single
self-hosted tracker has one too: `trackers` names the trackers it manages and the base of their API
(`{ health: "/api/hub/health", wealth: "/api/hub/wealth" }` on the front door, `{ wealth: "/api" }` inside wealth-tracker),
and everything that lists trackers shows only those. With `inApp` it sits in the app's layout and colours, invitation
links go to the app's register page, and when the API reports `front_door_url` (`/api/auth/registration-status`) it
links quietly to the front door's page; the apps' admin links then go there too.

## Files

| File | What |
| --- | --- |
| `brands.ts` | the two brands, their class names, and `localeFrom` |
| `copy.ts` | all text, in English and Dutch |
| `marks.tsx` | logos: `HealthMark`, `WealthMark`, `TrackerAIMark` |
| `visuals.tsx` | illustrations of each app (made-up numbers, never real data) |
| `icons.tsx` | line icons for the feature tiles |
| `FrontDoor.tsx` | the page |
| `Account.tsx` | logging in and signing up, and the way into each tracker once logged in |
| `Admin.tsx`, `AdminChart.tsx`, `adminCopy.ts` | the admin page, its charts and its text |
| `marketing.css` | self-contained styles, prefixed `mk-` |

The page uses `--font-sans` and `--font-display` when the app defines them, and falls back to system fonts otherwise.
