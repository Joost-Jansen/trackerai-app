# Money — how the second part of the app works

Next to the portfolio the app has a second subject, **Money**: bank accounts (CSV
import and optionally a PSD2 connection), automatic categorisation of bank
transactions, a spending overview with charts, a budget per group, net worth
(investments + bank balances + cash − debts) and a queue for labelling.
Optionally Claude helps with the labelling. wealth-tracker shows this part first
and the portfolio below it (see `frontend/lib/app.ts` and `frontend/lib/nav.ts`).

Read this before changing anything in it.

## Architecture

The same layers as the rest of the app: FastAPI routers → services → domain
modules, one SQLite database per user, Next.js (app router, React Query, the
`components/ds` design system).

### Domain modules (`backend/domain/money/`)

| Module | What |
|---|---|
| `accounts.py` | Accounts (bank, cash, manual, broker, debt), balances, IBAN normalisation, balances derived from transactions, explaining balance deviations |
| `bank_transactions.py` | Storing bank transactions (with dedup), loading, adding by hand, setting the category |
| `bank_providers/` | Parsers: `ing.py`, `ing_savings.py`, `ing_balances.py`, `bunq.py` → one normalised row (`base.py`); `enablebanking.py` for PSD2 |
| `bank_link.py` | The Enable Banking connection per user: consent, fetching, dedup with CSV |
| `categorization.py` | The labelling engine: taxonomy, rules, relabelling, own accounts, reversals, learning from your own labels |
| `label_queue.py` | "To label" as one queue (everything that needs a decision) and processing the decisions |
| `ai_labelling.py` | Optional: Claude suggests categories, checks the rules' labels, proposes rules |
| `fixed_costs.py` | Recognising fixed costs by their pattern (monthly, similar amount); the user's choice (`fixed_cost_choices`) wins both ways |
| `budget.py` | Monthly budget per group next to the actual |
| `month_periods.py` | Calendar month or salary month (salary on the 21st, with weekends and holidays) |
| `debt_schedule.py` | Interest and repayment of a debt (student debt) per month |
| `net_worth.py` | The net worth series: investments + bank balances + cash − debts |

And next to them in `backend/domain/`: `preferences.py` (small per-user
preferences: chart layout, Claude on/off), `onboarding.py` (what someone tracks
and the first steps), `secret_box.py` (Fernet encryption of a bank connection's
private key), `legacy_names.py` (migrates databases from before the English
rename) and `imports/degiro_cash.py` (the money at DeGiro, which counts in net
worth).

**Brokers.** The portfolio can be spread over several brokers
(`domain/portfolio/brokers.py`: `degiro`, `trade_republic`). Every row in
`transactions` and `dividends` carries its `broker`, its broker cash account
(`account_id`) and its `source` (`import`/`manual`); rows from before this were
all DeGiro's and are marked so by `init_db`. A broker's cash is an account of
kind `broker` whose provider is the broker code. For Trade Republic its balance
is the running sum of its movements in `account_entries` (with a `kind`: buy,
sell, deposit, …), kept by `portfolio/broker_ledger.py`, which also records
movements entered by hand (`/api/brokers`, the MCP tool `add_broker_transaction`).
`imports/trade_republic.py` reads Trade Republic's transaction export (CSV).
Positions add up per ISIN across brokers; only the Portfolio tab lists each
broker's line apart, with its own average cost.

### Routers (`backend/app/routers/`)

`accounts`, `bank_transactions`, `categories`, `labelling`, `spending`,
`budget`, `month_periods`, `net_worth`, `connections`, `onboarding`,
`preferences` — all under `/api/…`, registered in `backend/app/main.py`.

### The beta flag `money`

- Registered in `auth_store.BETA_FEATURES`, so it can be granted on the Admin page.
- **Backend:** `app.deps.require_money` is a router dependency on every money
  router (including `/api/uploads/bank`) → 403 without the flag. `onboarding`
  and `preferences` stay open.
- **Onboarding:** without the flag `/api/onboarding` always returns
  `choice: "investments"` and `money: false`. That way Money drops out of Help,
  the tour and the start banner by itself; the user's own choice comes back as
  soon as the flag is turned on.
- **Frontend:** `beta: "money"` on the items in `lib/nav.ts`; the layout only
  fetches the bank with the flag, and an address from the navigation the account
  has no access to shows a notice instead of a page full of 403s.
- Tests: `backend/tests/test_money_beta.py`. The fixture in `conftest.py` gives
  alice and bob the flag, because most tests are about Money.

### Frontend

- Pages: `/net-worth`, `/spending` (Overview, Budget, Transactions, To label),
  `/categories`, `/accounts` (including `/accounts/connect`), `/help/money`.
- Components under `components/money/` (charts in `charts/`, the labelling queue
  in `labelling/`), the step-by-step plans in `components/steps/`.
- Old Dutch addresses (`/vermogen`, `/uitgaven/…`, `/rekeningen/…`) redirect to
  the English ones (`frontend/next.config.js`).

### Agreements that apply everywhere

- **Explicit `conn`** as the first argument, as in `database.py`.
- **Sign convention in the bank tables:** spending **positive**, income
  **negative**. Only `net_worth.py` flips it when adding up.
- **`category_manual` always wins** over `category_auto`; a rule round never
  writes the manual field.
- **Nothing hardcoded per person or bank:** everything works for every user and
  every bank.

## Data model

Tables per user, in `portfolio.db`:

| Table | What |
|---|---|
| `accounts`, `account_balances`, `account_entries` | Accounts and their balance over time |
| `bank_transactions` | Bank transactions; `category_auto` (rules), `category_manual` (you), `category_source` (`rule`/`learned`/`ai`), `source` (`import`/`manual`) |
| `bank_transactions_typed` (view) | With `category_effective`, `group_name`, `type_effective` — the only place the type is derived |
| `categories` | Taxonomy: `group_name`, `name`, `type` (`EXPENSE`/`INCOME`/`INTERNAL`), `sort_order` |
| `rules` | `(priority, field N/T/A/P, pattern, direction ''/D/C, category)`; the lowest priority wins |
| `budgets` | Budget per **group name** |
| `debt_schedules` | Interest and repayment per debt |
| `bank_connections`, `bank_consents`, `bank_consent_accounts` | PSD2 connection (encrypted key, consent, linked accounts) |
| `ai_suggestions`, `ai_checks`, `rule_suggestions` | What Claude suggested, checked and proposed as a rule (with `reason` and a version label) |
| `fixed_cost_choices` | Whether a counterparty is a fixed cost, when the user says so |

Settings in `settings`: `default_rules_version`, `preference:*`,
`category_renamed`, `month_periods`, `salary_day`, `salary_category`. SQLite runs
with `journal_mode = WAL` and `busy_timeout = 5000` (in `database.connect`).

Category names (`Boodschappen`, `Onbekend`, …) are data, not code: they stay as
the user has them. The names the app relies on itself are in
`categorization.FIXED_CATEGORIES` and cannot be renamed.

## The labelling engine (`categorization.py`)

The order of certainty, and it stays that way:

1. **What you set by hand** (`category_manual`).
2. **Own accounts:** a counterparty IBAN or an account number of another own
   account in the description → "Eigen rekeningen"; a proven reversal between
   own accounts (same amount, within a few days).
3. **Rules**, by priority: the default rules (shop chains, words in the
   description, "what for" words on Tikkies) plus your own rules. Fields: `N`
   name, `T` description, `A` both, `P` "looks like a person".
4. **Learned:** what you labelled yourself before for the same counterparty.
5. **Claude** (optional), only when it is at least 80% sure.

**Versions of the default rules.** `DEFAULT_RULES_VERSION` with `RULES_SINCE`,
`CATEGORIES_SINCE`, `GROUPS_SINCE` and `TYPES_SINCE`: an existing user gets only what was added
on the first `seed()` after an update, once, and then everything is relabelled
once. What a user threw away, moved or renamed stays as they did it
(`category_renamed` remembers renames).

## Claude (optional)

- **Off by default.** Only available with `ANTHROPIC_API_KEY` on the server, and
  turned on per user (preference `ai_labelling`). Without a key nothing of it
  shows in the frontend and earlier AI labels fall back.
- **What goes to Anthropic:** name, description, amount and date, with IBANs,
  card and reference numbers removed (`ai_labelling.mask`). With "look
  thoroughly" also several descriptions per counterparty and the names of
  counterparties the user often labels (no friends, nothing internal).
- **Models:** `ai_labelling.MODEL` for labelling, checking and rule
  suggestions; `ai_labelling.MODEL_THOROUGH` for looking thoroughly.
- **Rounds of ~40:** one request to Claude per API call; the page runs the rounds
  and shows the progress. Next's `proxyTimeout` is 120 s. Behind Caddy that Next
  proxy plays no part.
- **Never silently:** what a rule or the user already knew does not go to Claude;
  certain suggestions are marked `ai`; rejecting is remembered.

## Bank connection (optional, Enable Banking / PSD2)

- Every user brings their own Enable Banking app: an app ID and a `.pem` private
  key, uploaded in the app (Accounts → Bank connection).
- The key and the Enable Banking session id are stored encrypted
  (`secret_box.py`) with `APP_ENCRYPTION_KEY`, required in production. A key
  file the server made itself on older installs (`.encryption_key`) is still
  read and its values re-encrypted with the new key. If the key is lost, the app
  asks for the `.pem` again.
- The return address at the start of a consent must be this site
  (`PUBLIC_ORIGINS` or the request's own host).
- Redirect URL at Enable Banking: `https://<your-domain>/api/connections/enablebanking/callback`.
  The old address `/api/koppelingen/enablebanking/terug` is still served, so a
  connection registered before the English rename keeps working.
- Without a connection everything works with CSV import (ING, ING savings, bunq).

## Configuration

The Pi needs nothing new; Railway sets a few paths. See [DEPLOY.md](DEPLOY.md).

| Variable | Pi (default) | Railway | Why |
|---|---|---|---|
| `DATA_DIR` | empty → `<repo>/data` | `/data` | Where the databases and uploads are |
| `AUTH_CONFIG_PATH` | empty → `<repo>/auth_config.yaml` | `/data/auth_config.yaml` | Accounts on the volume |
| `ANTHROPIC_API_KEY` | optional | optional | Claude features |
| `APP_ENCRYPTION_KEY` | required | required | Key for encrypted bank connections (key and session) and two-step secrets |
| `ENABLEBANKING_API_URL` | optional | optional | Another Enable Banking address (sandbox) |

## Testing

```bash
python -m pytest backend/tests -q
cd frontend && npx tsc --noEmit -p .
node scripts/test-money.cjs
node scripts/test-spending-query.mjs
node scripts/test-variable-spending.mjs
```

Test data is made up: names, IBANs and references in the tests are not real.
Tests that need a local copy of the old bookkeeping (`FINANCIEN_CLASSIFIED`,
`FINANCIEN_RULES`) skip themselves. Claude is never really called in the tests.

## Where to start reading

The docstring of `categorization.py` → `bank_transactions.py` → the money part
of `database.init_db` → `label_queue.py` → `ai_labelling.py` → `net_worth.py`.
The tests (`backend/tests/domain/test_categorization.py`,
`test_smarter_labelling.py`, `test_label_queue.py`, `test_learn_and_ai.py`,
`test_net_worth.py`) show what each piece promises.
