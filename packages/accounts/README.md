# trackerai-accounts

One account for every tracker. You register once and log in once. That one session holds on health.trackerai.nl
and wealth.trackerai.nl. Two-step login is part of the account, so you set it up once for all of them.

**What is shared and what is not:**
- **Shared:** who you are. That is your username, password, two-step login, language, whether you are an admin or
  suspended, and which apps you use.
- **Not shared:** your data. Health data stays in health-tracker's database, and money and portfolio data stay in
  wealth-tracker's. Each app links an account to its own user by the account's `local_key`: health-tracker's user id,
  and wealth-tracker's data folder.
- **Per app:** agent (MCP) tokens, so a token for one app cannot read the other.

## Two-step login

`REQUIRE_TOTP` decides who must use it:

| Policy | Who must use it |
|---|---|
| `shared` (default) | Admins, and anyone who uses more than one app. One password then opens both health and money data. |
| `all` | Everyone. |
| `admins` | Admins only. |
| `off` | Nobody. It stays available to anyone who wants it. |

**When it is required but not set up yet:**
- The login still works.
- Every route behind `sessions.ready` answers 403 `totp_setup_required`, so the site sends you to set it up.
- The account pages (`sessions.current`) stay reachable.
- It cannot be switched off while it is required.

## Signing up with an email address

Signing up needs an email address (`email`; one account per address). With a mail server, a welcome mail brings a
code that confirms it: until then every route behind `sessions.ready` answers 403 `email_verify_required`, and the
site asks for the code (`POST /api/account/email/confirm`). `POST /api/account/email/resend` sends it again, and with
`{email}` it corrects a typo first. Confirmed, the address is the account's two-step login: codes by email are on.
Accounts from before this have no address until they turn codes by email on themselves.

## Codes by email

Next to the authenticator app, or instead of it, two-step login can mail a code. Someone turns it on at Settings ›
Account: they enter an address and confirm it with the code mailed to it. From then on a right password mails a
six-digit code (`email_code_sent`, with the masked address). With the app on too, the login answers `totp_required`
with `email: true`, and `send_email` in the login asks for a mail instead.
- A code works once, for 10 minutes; five wrong tries spend it. At most five codes per account per quarter hour.
- Codes are stored as an HMAC (with `ACCOUNTS_SESSION_SECRET`), never as digits.
- It counts as two-step login, also where `REQUIRE_TOTP` requires it.
- A step that asks for a code (deleting, leaving an app, turning it off) can get one from `POST /api/account/email/code`.
- Without a configured mail provider it is not offered (`email_codes: false` in `/api/auth/registration-status`).

## Staying logged in

The login form sends `remember` ("stay logged in", on by default):
- **On:** the session lasts `SESSION_DAYS` (default 30) after its last use, never more than 90 days after the
  password was typed. A browser that gave the two-step code is also remembered for `SESSION_DAYS`: there, only the
  password is asked. A password change, turning two-step login on or off and an admin reset end both.
- **Off:** a browser session that ends when the browser closes, and after `SHORT_SESSION_HOURS` (default 24) at most.

`GET /api/auth/registration-status` also gives `session_days`, for the login form's text.

## Usage for the admin page

Each app's pages call `POST /api/account/visit` once per page they show (`useCountVisits` in packages/ui). The
accounts keep one number per day, app and account (`daily_use`): how many pages, never which ones. At most 5000 a day
are counted. `GET /api/admin/usage` gives the admin page the page visits and the number of active accounts per app and
ISO week (the last 12), the accounts active in the last 7 and 30 days, and each account's last day with a visit.
Deleting an account deletes its rows.

## Using it in an app

```python
from trackerai_accounts import install, make_router, open_accounts

accounts = open_accounts()                      # ACCOUNTS_* from the environment
install(app)                                    # AccountError -> {detail, code, params}
router, sessions = make_router(accounts, "health", client_ip=my_client_ip)
app.include_router(router)                      # before the app's own routes

def current_user(s = Depends(sessions.ready)):  # the app's own user for this account
    key = accounts.local_key(s.id, "health")
    if key is None:                             # first visit: create the app's user, remember its key
        key = create_local_user(s.account)
        accounts.set_local_key(s.id, "health", key)
    ...
```

**The app's duties:**
- **Its own user:** create it on the account's first visit, and keep its key with `set_local_key`.
- **Agent tokens:** resolve a token to its own user, then check that the account still exists and is not suspended:
  `accounts.account_for_local_key(app, key)`.
- **Deleting data:** sweep `accounts.pending_purges(app)` at startup and every few minutes. For each entry, delete the
  account's data, then call `accounts.purged(account_id, app)`. Data goes when someone leaves the app or deletes their
  account, and the account row goes with the last app.
- **Consent:** for health data, check `consent_at` on the account's app row before showing data. An admin can give
  someone the app; the person still consents on their first visit.

The routes are listed in [routes.py](trackerai_accounts/routes.py). They answer the same paths in every app.

## Settings

Every app must use the same values for these:

| Variable | What |
|---|---|
| `ACCOUNTS_DATABASE_URL` | The accounts database: Postgres in production, `sqlite:///…` on one machine. |
| `ACCOUNTS_SESSION_SECRET` | Signs the session cookie. At least 32 random characters. |
| `ACCOUNTS_ENCRYPTION_KEY` | A Fernet key that encrypts the two-step secrets. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `SESSION_COOKIE_DOMAIN` | The shared parent domain, e.g. `trackerai.nl`. Leave it empty for a single app or local development. |

These can differ per app:
- `COOKIE_SECURE`
- `SESSION_DAYS`
- `REQUIRE_TOTP`
- `FRONT_DOOR_URL`: the front door the apps link to (its admin page, for one), e.g. `https://www.trackerai.nl`.
  Optional: empty means `https://www.<SESSION_COOKIE_DOMAIN>`, and none at all without a shared domain (a tracker on
  its own). `GET /api/auth/registration-status` returns it as `front_door_url` (or `null`).

For codes by email, give every app the same mail provider. Resend over HTTPS works on Railway Hobby, where
outbound SMTP is blocked. Set `RESEND_API_KEY` and `MAIL_FROM`; use a sending-only key restricted to the verified
sender domain. HTTPS is preferred when both transports are configured. A failed request is not retried or sent
through SMTP. SMTP remains available on hosts that allow it.

| Variable | What |
|---|---|
| `RESEND_API_KEY` | Resend sending API key. Keep it in the deployment's secret variables. |
| `MAIL_FROM` | Sender for Resend, e.g. `trackerai <login@trackerai.nl>`. Falls back to `SMTP_FROM` when empty. |
| `SMTP_HOST`, `SMTP_PORT` | The mail server. Port 587 uses STARTTLS, 465 TLS from the start. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Its login. |
| `SMTP_FROM` | The sender, e.g. `trackerai <login@trackerai.nl>`. The provider must be allowed to send for that domain (SPF and DKIM in its DNS). |

**Security notes:**
- **Logout is everywhere.** The cookie is on the parent domain, so logging out of one app logs out of all of them.
- **CSRF.** The browser treats the subdomains as the same site, so `SameSite=Lax` alone does not stop one subdomain
  posting to another. Each app's origin check (`PUBLIC_ORIGINS`) does.
- **Rate limits.** The per-account login limit lives in the database and counts across apps. The per-IP limits are
  in memory, one set per process.

## Moving existing accounts in

`python -m trackerai_accounts.migrate` imports health-tracker's users and wealth-tracker's `auth_config.yaml`. It
prints a plan first. `--same` joins the accounts of someone who has both, and `--rename` settles a name that two
different people use. Its docstring has the details.

## Tests

```
pip install -e "packages/accounts[test]"
python -m pytest -q packages/accounts/tests
```
