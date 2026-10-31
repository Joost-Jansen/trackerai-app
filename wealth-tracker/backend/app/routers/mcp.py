"""
MCP: lets an AI assistant (any MCP client) work with your
portfolio and your money, as your account and with an agent token (see
routers/agent_tokens.py and auth_store).

Model Context Protocol over streamable HTTP, stateless, JSON responses without
SSE: `POST /api/mcp` with `Authorization: Bearer <token>`, or `POST /api/mcp/<token>`
for clients that only take a URL (a connector in claude.ai or ChatGPT).
Any MCP client works: Claude, ChatGPT, Codex, Copilot, Cursor, Gemini, … One server for
stock-tracker and wealth-tracker: they share this API.

Every tool calls an existing endpoint of this API, in the same process and with
the same token. That way exactly the same rules apply as in the browser: only
your own data, the beta flags, and in deps.py what a token with "read" or
"write" may do. The tools summarise the response to what an assistant needs,
and account numbers appear only as their last four characters.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core import auth_store, feedback_store
from domain.money import month_periods
from domain.money import net_worth as net_worth_domain
from trackerai_accounts.mcp_tools import describe
from trackerai_accounts.oauth import PREFIX, OAuth

router = APIRouter(tags=["mcp"])

PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]


def _obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    out = {"type": "object", "properties": props or {}}
    if required:
        out["required"] = required
    return out


PERIOD = {
    "start": {"type": "string", "description": "ISO date, inclusive (default: start of this month)"},
    "end": {"type": "string", "description": "ISO date, inclusive (default: today)"},
}

READ_TOOLS = [
    {
        "name": "get_overview",
        "description": "Everything at once: net worth (investments, bank, debt), the portfolio (value, result, today), spending and income this month, budget this month and how much is still to be labelled.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_portfolio",
        "description": "The portfolio: totals and per position name, ticker, broker, quantity, value, weight, unrealised and total result, and the day's price.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_returns",
        "description": "Return per period (1M, 3M, YTD, 1Y, 3Y, All): TWR, IRR, simple return, gain and deposits. Plus the comparison with the benchmarks this year.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_dividends",
        "description": "Dividend: totals, per year, per fund and what is expected in the coming period.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_net_worth",
        "description": "Net worth now, the change, and per month investments, bank, debt and net.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_spending",
        "description": "Spending and income in a period, per group and category, compared with the equally long period before. Internal transfers (saving, investing, own accounts) don't count.",
        "inputSchema": _obj(PERIOD),
    },
    {
        "name": "get_budget",
        "description": "Budget per group against actual, per month, with the median and what is still expected this month.",
        "inputSchema": _obj({"months": {"type": "integer", "default": 3, "description": "Number of months (1-24)"}}),
    },
    {
        "name": "list_transactions",
        "description": "Search bank transactions. A positive amount is an expense, a negative one income. Each transaction has an id, for label_transactions.",
        "inputSchema": _obj(
            {
                **PERIOD,
                "search": {"type": "string", "description": "Text in name or description (case-insensitive)"},
                "category": {"type": "string", "description": "Only this category (or 'Onbekend', the name for no category)"},
                "limit": {"type": "integer", "default": 50, "description": "Maximum (1-500), newest first"},
            }
        ),
    },
    {
        "name": "get_unlabelled",
        "description": "What is still to be labelled: per counterparty the transactions, the total, the current category and a suggestion if there is one.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_net_worth_split",
        "description": "Where the change in net worth came from, per month (calendar or salary month, as set in Settings) and optionally for a period from start to end (from the balance at the end of the day before start): change = saved + market + bank + debt. saved: income minus spending (including your own share of shared costs when a shared-costs category is set; that part is also in `shared`). market: what the holdings did (price change and dividend; money moved to or from the broker is not a gain). debt: the change in your own debts (a repayment is positive, interest negative; money held for friends is left out). bank: the rest, in `detail`: friends (money for or of friends not settled), unlabelled, corrections (balances that don't follow the transactions; per account in get_bank_corrections) and transfers (e.g. a repayment leaving the bank, money to accounts outside net worth). The same bank figure also reads as listed (the transactions in categories that land in Bank & cash, those without a category, and friends' money unless it counts as spending) + corrections + other_half (money whose other half isn't a bank transaction, e.g. to a savings account with only balances). All null when the bank data does not cover the period. Positive means more net worth.",
        "inputSchema": _obj(
            {
                "start": {
                    "type": "string",
                    "description": "ISO date: only months that end on or after it, and the start of the period split",
                },
                "end": {"type": "string", "description": "ISO date: months up to it, and the end of the period split"},
                "months": {"type": "integer", "default": 12, "description": "Without start: the last this many months (1-120)"},
            }
        ),
    },
    {
        "name": "get_settings",
        "description": "The settings behind Spending, Budget and Net worth: the month layout (calendar months, or salary months that start on the day your salary comes in, with the salary day and salary category) and the category where your own share of shared costs counts as spending (null: it counts nowhere and stays with friends' money).",
        "inputSchema": _obj(),
    },
    {
        "name": "list_categories",
        "description": "All categories with their group, type (EXPENSE, INCOME, INTERNAL), role on Net worth (spending, income, investments, debt, own, others, bank) whether the type is locked (type_locked: the app relies on it) and whether the name is fixed (is_fixed: it can't be renamed), and the rules that fill them, each with an id.",
        "inputSchema": _obj(),
    },
    {
        "name": "get_fixed_costs",
        "description": "Fixed costs: counterparties that come back every month (is_fixed, with the median amount per month), candidates that might be one, and what the user marked as not a fixed cost (excluded). `manual`: chosen by hand instead of detected.",
        "inputSchema": _obj(),
    },
    {
        "name": "list_accounts",
        "description": "Accounts with kind, balance and balance date (account number only the last four characters).",
        "inputSchema": _obj(),
    },
    {
        "name": "get_bank_corrections",
        "description": "Where the balance corrections in Bank & cash (detail.corrections in get_net_worth_split) come from, per account: from the balance at the end of `from` to the end of `to` (use the from and to of a month in get_net_worth_split), the change of each account minus its own transactions. Per account the events that make it up: start (the account's first data, before it it counts as zero), transfer (a savings account running on with transfers your other accounts made to or from it), measurement (a balance, entered by hand or synced, that the transactions don't reach), line (the straight line between two balances entered by hand) and derived (a step the transactions of that day don't explain). A correction is right when it reflects money that really moved without a transaction here; it is wrong when a balance was entered on the wrong date or with the wrong amount, or an export is missing. Check with list_balances and list_transactions before changing anything.",
        "inputSchema": _obj(
            {
                "from": {"type": "string", "description": "ISO date: from the balance at the end of this day"},
                "to": {"type": "string", "description": "ISO date: to the balance at the end of this day (default: today)"},
            },
            ["from"],
        ),
    },
    {
        "name": "list_balances",
        "description": "Every balance recorded for one account (date, balance, source: manual = entered by hand, sync = from the bank connection or an export), plus the balances that don't match its transactions, each with the calculated balance, the difference and the most likely explanation. For an account with its own transactions only the last balance sets the level; the earlier ones only show here when they don't match. For a debt with a schedule also the months the schedule calculated.",
        "inputSchema": _obj(
            {
                "account": {"type": ["string", "integer"], "description": "Account id or name (see list_accounts)"},
            },
            ["account"],
        ),
    },
]

WRITE_TOOLS = [
    {
        "name": "refresh_data",
        "description": "Fetch today's figures, as the Update button in the app does: refresh every price, and fetch new transactions and balances through the bank connection when the user has one. Takes up to a minute. Use it before an answer that depends on today's numbers when prices or bank data look old (get_overview shows prices_of).",
        "inputSchema": _obj(),
    },
    {
        "name": "label_transactions",
        "description": "Give transactions a category, by hand: it wins over the rules. Leaving it empty (category null) puts them back to what the rules find. Use list_categories for the valid names.",
        "inputSchema": _obj(
            {
                "ids": {"type": "array", "items": {"type": "integer"}, "description": "Transaction ids"},
                "category": {"type": ["string", "null"], "description": "Existing category, or null"},
            },
            ["ids"],
        ),
    },
    {
        "name": "set_budget",
        "description": "Set the monthly budget of a group (e.g. Boodschappen). 0 or null removes it.",
        "inputSchema": _obj(
            {
                "group_name": {"type": "string"},
                "amount": {"type": ["number", "null"], "description": "Euro per month"},
            },
            ["group_name", "amount"],
        ),
    },
    {
        "name": "add_category_rule",
        "description": "A rule that labels by itself from now on: transactions whose field matches the pattern get this category. Relabels everything afterwards.",
        "inputSchema": _obj(
            {
                "pattern": {"type": "string", "description": "Regular expression, case-insensitive, e.g. 'ALBERT HEIJN|JUMBO'"},
                "category": {"type": "string"},
                "field": {
                    "type": "string",
                    "enum": ["N", "T", "A", "P"],
                    "default": "N",
                    "description": "N counterparty name, T description, A counter account, P everything",
                },
                "direction": {
                    "type": "string",
                    "enum": ["", "D", "C"],
                    "default": "",
                    "description": "Empty: both; D: only out; C: only in",
                },
                "priority": {"type": "integer", "default": 50, "description": "Lower wins. Own rules: 30-60"},
            },
            ["pattern", "category"],
        ),
    },
    {
        "name": "delete_rule",
        "description": "Delete a labelling rule by its id (see list_categories). Relabels everything afterwards; labels set by hand stay.",
        "inputSchema": _obj(
            {
                "id": {"type": "integer", "description": "Rule id"},
            },
            ["id"],
        ),
    },
    {
        "name": "set_category_type",
        "description": "Whether a category counts as spending (EXPENSE), income (INCOME) or nowhere (INTERNAL: transfers, saving, investing). That also decides where it lands on Net worth: EXPENSE and INCOME in Saved, INTERNAL in Bank & cash. Categories with type_locked cannot be changed.",
        "inputSchema": _obj(
            {
                "category": {"type": "string", "description": "Existing category name"},
                "type": {"type": "string", "enum": ["EXPENSE", "INCOME", "INTERNAL"]},
            },
            ["category", "type"],
        ),
    },
    {
        "name": "rename_category",
        "description": "Rename a category; its transactions, rules and budgets move along.",
        "inputSchema": _obj(
            {
                "category": {"type": "string", "description": "Current name"},
                "new_name": {"type": "string"},
            },
            ["category", "new_name"],
        ),
    },
    {
        "name": "move_category",
        "description": "Move a category to another group (main category); a group that does not exist yet is created.",
        "inputSchema": _obj(
            {
                "category": {"type": "string"},
                "group_name": {"type": "string"},
            },
            ["category", "group_name"],
        ),
    },
    {
        "name": "set_month_layout",
        "description": "Where a month starts, for Spending, Budget and Net worth: 'calendar' (the 1st) or 'salary' (the day the salary comes in). Only the fields given change. day: the usual salary day (1-31), null to recognise it from the transactions. category: the category the salary is in.",
        "inputSchema": _obj(
            {
                "mode": {"type": "string", "enum": ["calendar", "salary"]},
                "day": {"type": ["integer", "null"], "description": "Salary day 1-31, or null: recognise"},
                "category": {"type": "string", "description": "Salary category (default Salaris)"},
            }
        ),
    },
    {
        "name": "set_shared_costs_category",
        "description": "The spending category where your own share of shared costs (money advanced for friends that does not come back) counts as spending. null: it counts nowhere and stays on Net worth as money for friends under Bank & cash.",
        "inputSchema": _obj(
            {
                "category": {"type": ["string", "null"], "description": "An EXPENSE category, or null"},
            },
            ["category"],
        ),
    },
    {
        "name": "set_fixed_cost",
        "description": "Whether a counterparty is a fixed cost: true, false (never), or null to leave it to the detection again. By counterparty name, as get_fixed_costs shows it.",
        "inputSchema": _obj(
            {
                "name": {"type": "string", "description": "Counterparty name"},
                "is_fixed": {"type": ["boolean", "null"]},
            },
            ["name", "is_fixed"],
        ),
    },
    {
        "name": "set_balance",
        "description": "Enter the balance of an account on a date; the same date again replaces it. A debt is always stored as negative, whatever sign is given.",
        "inputSchema": _obj(
            {
                "account": {"type": ["string", "integer"], "description": "Account id or name (see list_accounts)"},
                "balance": {"type": "number", "description": "Euro"},
                "date": {"type": "string", "description": "ISO date (default: today)"},
            },
            ["account", "balance"],
        ),
    },
    {
        "name": "delete_balance",
        "description": "Delete one recorded balance of an account (see list_balances), for a balance that should never have been there: a wrong date, a wrong amount or a double. A wrong amount on the right date is better fixed with set_balance on that date. Cannot be undone; only when the user asked for it.",
        "inputSchema": _obj(
            {
                "account": {"type": ["string", "integer"], "description": "Account id or name (see list_accounts)"},
                "date": {"type": "string", "description": "ISO date of the balance"},
            },
            ["account", "date"],
        ),
    },
    {
        "name": "add_transaction",
        "description": "Add a bank transaction by hand, for something that is in no export (cash, a forgotten payment). A positive amount is an expense, a negative amount income. Without a category the rules decide.",
        "inputSchema": _obj(
            {
                "account": {"type": ["string", "integer"], "description": "Account id or name (see list_accounts)"},
                "amount": {"type": "number", "description": "Euro; positive = expense, negative = income"},
                "name": {"type": "string", "description": "Counterparty"},
                "date": {"type": "string", "description": "ISO date (default: today)"},
                "description": {"type": "string"},
                "category": {"type": ["string", "null"], "description": "Existing category, or null: the rules decide"},
            },
            ["account", "amount", "name"],
        ),
    },
    {
        "name": "add_broker_transaction",
        "description": "Add a movement at a broker by hand (e.g. Trade Republic): a buy or sell (fractional quantities are fine, as in a savings plan), a deposit, withdrawal, interest, dividend, fee or tax. Amounts are positive euros; the kind gives the direction. The broker account must already exist (see get_portfolio / list_accounts); it updates positions, the broker's cash and net worth.",
        "inputSchema": _obj(
            {
                "broker": {
                    "type": ["string", "integer"],
                    "description": "Broker code (trade_republic, degiro), its display name, or the account id",
                },
                "kind": {"type": "string", "enum": ["buy", "sell", "deposit", "withdrawal", "interest", "dividend", "fee", "tax"]},
                "date": {"type": "string", "description": "ISO date (default: today)"},
                "isin": {"type": "string", "description": "For buy, sell and dividend"},
                "name": {"type": "string", "description": "Product name (optional; known ISINs keep their name)"},
                "quantity": {"type": "number", "description": "Units, for buy and sell"},
                "price": {"type": "number", "description": "Euro per unit, for buy and sell (or give amount)"},
                "amount": {
                    "type": "number",
                    "description": "Euro: the value of a buy/sell without the price, the gross dividend, or the cash amount",
                },
                "fee": {"type": "number", "description": "Euro, positive"},
                "tax": {"type": "number", "description": "Euro withheld, positive"},
                "description": {"type": "string"},
            },
            ["broker", "kind"],
        ),
    },
]

WRITE_NAMES = {t["name"] for t in WRITE_TOOLS}
# Writes that delete or overwrite what was there: an assistant should ask first.
DESTRUCTIVE_NAMES = {"delete_rule", "delete_balance", "rename_category", "move_category", "set_balance"}

# Only for an admin's token: feedback from all users (routers/feedback.py). A
# token otherwise never gets admin rights; this is the one exception, kept
# narrow: reading, and with "write" the status and reply. The tools talk to
# feedback_store directly, not through /api/admin (that stays closed to
# tokens, deps.AGENT_BLOCKED).
FEEDBACK_TOOLS = [
    {
        "name": "list_feedback",
        "description": "Feedback from users of stock-tracker and wealth-tracker: something broken (bug) or an idea, with app, page, browser, version and recent errors. Newest first. By default only open reports (new and planned).",
        "inputSchema": _obj(
            {
                "status": {"type": "string", "enum": ["open", "all", "new", "planned", "fixed", "wontfix"], "default": "open"},
                "limit": {"type": "integer", "default": 30},
            }
        ),
    },
    {
        "name": "update_feedback",
        "description": "Set the status (new, planned, fixed, wontfix) and/or a reply on a report. The user sees both in the app. Only with a token that may write.",
        "inputSchema": _obj(
            {
                "id": {"type": "integer"},
                "status": {"type": "string", "enum": list(feedback_store.STATUSES)},
                "reply": {"type": "string", "description": "Short reply for the user, in their language"},
            },
            ["id"],
        ),
    },
]
FEEDBACK_NAMES = {t["name"] for t in FEEDBACK_TOOLS}


def feedback_md(items: list[dict]) -> str:
    out = []
    for f in items:
        ctx = f.get("context") or {}
        lines = [
            f"## #{f['id']} {f['kind']} · {f['status']} · {f.get('app') or 'stock'}-tracker · {f['created_at'][:16].replace('T', ' ')} · {f['username']}",
            f["message"].strip(),
        ]
        meta = [
            f"pagina {f['page']}" if f.get("page") else None,
            f"versie {ctx['version']}" if ctx.get("version") else None,
            ctx.get("browser"),
            ctx.get("screen"),
        ]
        lines.append("_" + " · ".join(m for m in meta if m) + "_")
        for e in ctx.get("errors") or []:
            lines.append(f"- error: {e.get('message')}" + (f" ({e['where']})" if e.get("where") else ""))
        if f.get("has_screenshot"):
            lines.append(f"- screenshot: /api/feedback/{f['id']}/screenshot (only in the browser)")
        if f.get("reply"):
            lines.append(f"Reply: {f['reply']}")
        out.append("\n".join(lines))
    return "\n\n".join(out) or "No feedback."


def instructions(scope: str) -> str:
    rights = (
        "You may read and write: refresh prices and bank data (refresh_data), label transactions, set budgets, add and delete labelling rules, change categories (name, group, type), the month layout, the shared-costs category and fixed costs, enter and delete balances, add bank transactions and add trades or cash movements at a broker (add_broker_transaction). Only do that when the user asks for it, and say what you changed."
        if scope == "write"
        else "You may only read; this token cannot change anything."
    )
    return (
        "The user's portfolio and money (stock-tracker / wealth-tracker). Start with get_overview. Answer in the user's language, calculate with the data instead of estimating, and separate what the figures say from your interpretation. Amounts in euros. For bank transactions a positive amount is an expense and a negative amount income. "
        + rights
        + " No financial advice: give information and leave decisions about investing to the user."
    )


class ToolError(Exception):
    pass


def _mask(iban: str | None) -> str | None:
    return f"…{iban[-4:]}" if iban else None


def _dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def _r2(x):
    """Rounds every float in a result to cents."""
    if isinstance(x, float):
        return round(x, 2) + 0.0
    if isinstance(x, dict):
        return {k: _r2(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r2(v) for v in x]
    return x


FIXED_KEYS = ("name", "category", "group_name", "amount", "months", "first", "last", "is_new", "stopped", "manual")


def fixed_costs_out(d: dict) -> dict:
    trim = lambda items: [{k: v.get(k) for k in FIXED_KEYS if k in v} for v in items or []]
    running = [v for v in d.get("is_fixed") or [] if not v.get("stopped")]
    return {
        "per_month": round(sum(v.get("amount") or 0 for v in running), 2),
        "is_fixed": trim(d.get("is_fixed")),
        "candidates": trim(d.get("candidates")),
        "excluded": trim(d.get("excluded")),
    }


def settings_out(mp: dict, shared: dict | None) -> dict:
    return {
        "month_layout": {k: mp.get(k) for k in ("mode", "active", "day", "day_configured", "category", "recognised", "current")},
        "shared_costs_category": shared.get("category") if shared else None,
    }


class Server:
    def __init__(self, token: str, scope: str, username: str = ""):
        self.token = token
        self.scope = scope
        self.username = username

    def is_admin(self) -> bool:
        return not self.token.startswith(PREFIX) and bool(self.username) and auth_store.is_admin(self.username)

    def tools(self) -> list[dict]:
        tools = READ_TOOLS + (WRITE_TOOLS if self.scope == "write" else []) + (FEEDBACK_TOOLS if self.is_admin() else [])
        from app.core.accounts import accounts

        return describe(
            tools,
            "wealth",
            WRITE_NAMES | {"update_feedback"},
            destructive=DESTRUCTIVE_NAMES,
            open_world={"refresh_data"},
            oauth=OAuth(accounts).enabled,
        )

    def _feedback(self, name: str, args: dict) -> str:
        if not self.is_admin():
            raise ToolError("Admins only.")
        if name == "list_feedback":
            wanted = args.get("status") or "open"
            items = feedback_store.list_(status=None if wanted in ("open", "all") else wanted, limit=min(int(args.get("limit") or 30), 200))
            if wanted == "open":
                items = [f for f in items if f["status"] in ("new", "planned")]
            return feedback_md(items)
        if self.scope != "write":
            raise ToolError("This token only has read access.")
        new_status = args.get("status")
        if new_status is not None and new_status not in feedback_store.STATUSES:
            raise ToolError(f"Status is one of {', '.join(feedback_store.STATUSES)}.")
        if not feedback_store.update(int(args["id"]), status=new_status, reply=args.get("reply")):
            raise ToolError(f"Feedback {args['id']} does not exist.")
        return feedback_md([feedback_store.get(int(args["id"]))])

    async def _api(self, method: str, path: str, *, params: dict | None = None, body=None, optional: bool = False):
        """Calls an endpoint of this API, in the same process (ASGI), with the agent's token."""
        from app.main import app  # here, not at import: app.main imports this module

        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        payload = json.dumps(body).encode() if body is not None else b""
        headers = [(b"authorization", f"Bearer {self.token}".encode()), (b"host", b"mcp.local")]
        if body is not None:
            headers.append((b"content-type", b"application/json"))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": unquote(path),
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": query.encode(),
            "headers": headers,
            "client": ("127.0.0.1", 0),
            "server": ("mcp.local", 80),
        }
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}

        status_code, chunks = 500, []

        async def send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await app(scope, receive, send)
        raw = b"".join(chunks)
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        if status_code >= 400:
            if optional:
                return None
            detail = data.get("detail") if isinstance(data, dict) else raw.decode(errors="replace")[:200]
            raise ToolError(f"{detail or status_code}")
        return data

    # --- read --------------------------------------------------------------

    async def _spending(self, start: str, end: str) -> dict:
        data = await self._api("GET", "/api/bank-transactions", params={"start": start, "end": end})
        off, inn = defaultdict(float), defaultdict(float)
        per_cat: dict[tuple[str, str], float] = defaultdict(float)
        for t in data["transactions"]:
            if t.get("type") == "EXPENSE":
                off[t.get("group_name") or "?"] += t["amount"]
                per_cat[(t.get("group_name") or "?", t.get("category") or "Onbekend")] += t["amount"]
            elif t.get("type") == "INCOME":
                inn[t.get("category") or "?"] -= t["amount"]
        r2 = lambda d: {k: round(v, 2) for k, v in sorted(d.items(), key=lambda kv: -abs(kv[1]))}
        return {
            "start": start,
            "end": end,
            "spending": round(sum(off.values()), 2),
            "income": round(sum(inn.values()), 2),
            "per_group": r2(off),
            "per_category": [
                {"group_name": g, "category": c, "amount": round(v, 2)} for (g, c), v in sorted(per_cat.items(), key=lambda kv: -kv[1])
            ],
            "income_per_category": r2(inn),
            "transactions": data["count"],
        }

    async def _category(self, name) -> dict:
        name = str(name or "").strip()
        if not name:
            raise ToolError("Give the category.")
        c = await self._api("GET", "/api/categories")
        found = next((x for x in c["categories"] if x["name"] == name), None)
        if found is None:
            found = next((x for x in c["categories"] if x["name"].lower() == name.lower()), None)
        if found is None:
            raise ToolError(f"'{name}' is not an existing category; see list_categories.")
        return found

    async def _account(self, ref) -> dict:
        if ref is None or str(ref).strip() == "":
            raise ToolError("Give the account.")
        r = await self._api("GET", "/api/accounts")
        items = r["accounts"]
        text = str(ref).strip()
        if text.isdigit():
            found = next((x for x in items if x["id"] == int(text)), None)
            if found:
                return found
        named = [x for x in items if (x.get("name") or "").lower() == text.lower()]
        if len(named) > 1:
            raise ToolError(f"More than one account is called '{text}'; use the id from list_accounts.")
        if not named:
            raise ToolError(f"No account '{text}'; see list_accounts.")
        return named[0]

    @staticmethod
    def _category_out(categories: list[dict], name: str) -> dict | None:
        c = next((x for x in categories if x["name"] == name), None)
        return {k: c.get(k) for k in ("name", "group_name", "type", "role", "type_locked")} if c else None

    async def call(self, name: str, args: dict) -> str:
        if name in FEEDBACK_NAMES:
            return self._feedback(name, args)
        if name in WRITE_NAMES and self.scope != "write":
            raise ToolError("This token only has read access.")
        today = date.today()

        if name == "get_overview":
            out: dict = {}
            s = await self._api("GET", "/api/dashboard/summary", optional=True)
            if s:
                out["portfolio"] = {
                    **{
                        k: s["summary"].get(k)
                        for k in (
                            "total_value",
                            "total_gain",
                            "total_return_pct",
                            "unrealized_gain",
                            "net_investment",
                            "total_dividends",
                            "num_positions",
                        )
                    },
                    "today": s.get("day"),
                    "prices_of": s.get("latest_price_fetch"),
                }
            v = await self._api("GET", "/api/net-worth", optional=True)
            if v:
                out["net_worth"] = {"now": v.get("now"), "change": v.get("change")}
                start = today.replace(day=1).isoformat()
                sp = await self._spending(start, today.isoformat())
                out["this_month"] = {k: sp[k] for k in ("start", "end", "spending", "income", "per_group")}
                b = await self._api("GET", "/api/budget", params={"months": 1}, optional=True)
                if b:
                    m = b["months"][-1]
                    out["budget_this_month"] = [
                        {
                            "group_name": g["group_name"],
                            "budget": g["budget"],
                            "actual": g["actual"].get(m),
                            "expected_remaining": g.get("expected"),
                        }
                        for g in b["groups"]
                        if g.get("budget")
                    ]
                w = await self._api("GET", "/api/labelling/queue", optional=True)
                if w:
                    out["unlabelled"] = w.get("waiting")
            else:
                out["money"] = "is not turned on for this account"
            return _dump(out)

        if name == "get_portfolio":
            h = await self._api("GET", "/api/holdings/overview")
            total = sum(p.get("current_value") or 0 for p in h["positions"])
            keys = (
                "name",
                "ticker",
                "isin",
                "broker",
                "asset_type",
                "shares_held",
                "current_price",
                "current_value",
                "unrealized_eur",
                "unrealized_pct",
                "total_eur",
                "total_pct",
                "dividends_eur",
                "day_pct",
            )
            pos = [
                {**{k: p.get(k) for k in keys}, "weight_pct": round(100 * (p.get("current_value") or 0) / total, 2) if total else None}
                for p in h["positions"]
            ]
            s = await self._api("GET", "/api/dashboard/summary", optional=True)
            return _dump({"totals": s["summary"] if s else None, "positions": pos})

        if name == "get_returns":
            r = await self._api("GET", "/api/returns", optional=True)
            b = await self._api("GET", "/api/benchmarks/series", optional=True)
            ytd = None
            if b and b.get("ytd"):
                ytd = {s["label"]: (s["points"][-1]["v"] if s["points"] else None) for s in b["ytd"]["series"]}
            if r is None and ytd is None:
                raise ToolError("Returns is not turned on for this account.")
            return _dump({"per_period": (r or {}).get("ranges"), "this_year_pct_vs_benchmarks": ytd})

        if name == "get_dividends":
            d = await self._api("GET", "/api/dividend")
            return _dump(
                {
                    "totals": d.get("totals"),
                    "per_year": d.get("by_year"),
                    "per_fund": d.get("by_stock"),
                    "expected": (d.get("upcoming") or [])[:12],
                }
            )

        if name == "get_net_worth":
            v = await self._api("GET", "/api/net-worth")
            return _dump(
                {"now": v.get("now"), "change": v.get("change"), "per_month": v.get("months"), "prices_unknown": v.get("prices_unknown")}
            )

        if name == "get_spending":
            start = args.get("start") or today.replace(day=1).isoformat()
            end = args.get("end") or today.isoformat()
            d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
            if d1 < d0:
                raise ToolError("end is before start.")
            now = await self._spending(start, end)
            length = (d1 - d0).days + 1
            last_one = await self._spending((d0 - timedelta(days=length)).isoformat(), (d0 - timedelta(days=1)).isoformat())
            now["previous_period"] = {k: last_one[k] for k in ("start", "end", "spending", "income", "per_group")}
            return _dump(now)

        if name == "get_budget":
            months = max(1, min(24, int(args.get("months") or 3)))
            return _dump(await self._api("GET", "/api/budget", params={"months": months}))

        if name == "list_transactions":
            start = args.get("start") or (today - timedelta(days=90)).isoformat()
            end = args.get("end") or today.isoformat()
            data = await self._api("GET", "/api/bank-transactions", params={"start": start, "end": end})
            search = (args.get("search") or "").lower()
            cat = args.get("category")
            rows = [
                t
                for t in data["transactions"]
                if (not search or search in f"{t.get('name') or ''} {t.get('description') or ''}".lower())
                and (not cat or (t.get("category") or "Onbekend") == cat)
            ]
            rows.sort(key=lambda t: (t["date"], t["id"]), reverse=True)
            limit = max(1, min(500, int(args.get("limit") or 50)))
            keys = ("id", "date", "amount", "name", "description", "category", "group_name", "type", "category_source", "account_id")
            return _dump(
                {
                    "start": start,
                    "end": end,
                    "found": len(rows),
                    "shown": min(limit, len(rows)),
                    "transactions": [
                        {**{k: t.get(k) for k in keys}, "counter_account": _mask(t.get("counterparty_iban"))} for t in rows[:limit]
                    ],
                }
            )

        if name == "get_unlabelled":
            w = await self._api("GET", "/api/labelling/queue")
            keys = ("kind", "title", "ids", "count", "total", "last", "description", "now", "suggestion", "confidence", "reason")
            return _dump(
                {
                    "waiting": w.get("waiting"),
                    "coverage_pct": w.get("coverage"),
                    "items": [{k: i.get(k) for k in keys} for i in w.get("items", [])],
                }
            )

        if name == "list_categories":
            c = await self._api("GET", "/api/categories")
            return _dump(
                {
                    "categories": [
                        {k: x.get(k) for k in ("name", "group_name", "type", "role", "type_locked", "is_fixed")} for x in c["categories"]
                    ],
                    "rules": [
                        {k: x.get(k) for k in ("id", "priority", "field", "pattern", "direction", "category", "active")} for x in c["rules"]
                    ],
                }
            )

        if name == "get_net_worth_split":
            v = await self._api("GET", "/api/net-worth")
            mp = await self._api("GET", "/api/month-periods")
            points, flows = v.get("points") or [], v.get("flows") or []
            shared = v.get("shared_costs_category") is not None
            start, end = args.get("start"), args.get("end")
            for d in (start, end):
                if d:
                    date.fromisoformat(d)
            if start and end and end < start:
                raise ToolError("end is before start.")
            layout = month_periods.Layout(mp.get("active") or "calendar", mp.get("boundaries") or [])
            rows = net_worth_domain.split_per_month(points, flows, layout.key, shared, until=end)
            if start:
                rows = [r for r in rows if r["to"] >= start]
            else:
                rows = rows[-max(1, min(120, int(args.get("months") or 12))) :]
            out = {
                "month_layout": layout.mode,
                "shared_costs_category": v.get("shared_costs_category"),
                "months": [
                    {"month": r["month"], "from": r["from"], "to": r["to"], "partial": r["partial"], **(r["split"] or {"change": None})}
                    for r in rows
                ],
            }
            if start or end:
                # From the balance at the end of the day before start, so the start day itself counts.
                upto = [p for p in points if not end or p["d"] <= end]
                before = [p for p in upto if start and p["d"] < start]
                inside = [p for p in upto if not start or p["d"] >= start]
                base = before[-1] if before else (inside[0] if inside else None)
                out["period"] = (
                    {"from": base["d"], "to": inside[-1]["d"], **net_worth_domain.split(base, inside[-1], flows, shared)}
                    if base and inside and inside[-1]["d"] > base["d"]
                    else None
                )
            return _dump(_r2(out))

        if name == "get_settings":
            mp = await self._api("GET", "/api/month-periods")
            shared = await self._api("GET", "/api/spending/shared-costs", optional=True)
            return _dump(settings_out(mp, shared))

        if name == "get_fixed_costs":
            return _dump(fixed_costs_out(await self._api("GET", "/api/spending/fixed-costs/manage")))

        if name == "list_accounts":
            r = await self._api("GET", "/api/accounts")
            keys = ("id", "name", "kind", "provider", "currency", "balance", "balance_date", "active")
            return _dump([{**{k: x.get(k) for k in keys}, "account_number": _mask(x.get("iban"))} for x in r["accounts"]])

        if name == "get_bank_corrections":
            start, end = args.get("from"), args.get("to") or today.isoformat()
            for d in (start, end):
                date.fromisoformat(d or "")
            if end < start:
                raise ToolError("to is before from.")
            return _dump(await self._api("GET", "/api/net-worth/corrections", params={"start": start, "end": end}))

        if name == "list_balances":
            account = await self._account(args.get("account"))
            b = await self._api("GET", f"/api/accounts/{account['id']}/balances")
            v = await self._api("GET", "/api/net-worth")
            keys = ("date", "balance", "source")
            return _dump(
                {
                    "account": {k: account.get(k) for k in ("id", "name", "kind")},
                    "balances": [{k: m.get(k) for k in keys} for m in b["balances"]],
                    "not_matching": [
                        {k: x.get(k) for k in ("date", "measured", "calculated", "source", "anchor", "explanation")}
                        for x in v.get("deviating_balances") or []
                        if x.get("account_id") == account["id"]
                    ],
                    "pending_in_last": [x for x in v.get("pending_in_last") or [] if x.get("account_id") == account["id"]],
                    "calculated": [{k: m.get(k) for k in ("date", "balance", "interest", "repayment")} for m in b.get("calculated") or []],
                }
            )

        # --- write (scope bijhouden) ----------------------------------------

        if name == "refresh_data":
            out: dict = {}
            for part, path in (("prices", "/api/prices/refresh"), ("bank", "/api/connections/enablebanking/fetch")):
                try:
                    out[part] = await self._api("POST", path)
                except ToolError as e:  # no bank connection, Money off, a bank that refuses: say so, keep the rest
                    out[part] = {"error": str(e)}
            return _dump(out)

        if name == "label_transactions":
            ids = [int(i) for i in args.get("ids") or []]
            if not ids:
                raise ToolError("Give the ids of the transactions.")
            r = await self._api("PUT", "/api/bank-transactions/category", body={"ids": ids, "category": args.get("category")})
            return _dump({"updated": r.get("updated"), "category": args.get("category")})

        if name == "set_budget":
            group_name = str(args.get("group_name") or "").strip()
            if not group_name:
                raise ToolError("Give the group.")
            await self._api("PUT", f"/api/budget/{quote(group_name, safe='')}", params={"months": 1}, body={"amount": args.get("amount")})
            return _dump({"group_name": group_name, "budget": args.get("amount")})

        if name == "add_category_rule":
            body = {
                "pattern": args["pattern"],
                "category": args["category"],
                "field": args.get("field") or "N",
                "direction": args.get("direction") or "",
                "priority": int(args.get("priority") or 50),
            }
            r = await self._api("POST", "/api/categories/rules", body=body)
            await self._api("POST", "/api/categories/relabel", optional=True)
            return _dump({"rule": r.get("rule")})

        if name == "delete_rule":
            rule_id = int(args["id"])
            await self._api("DELETE", f"/api/categories/rules/{rule_id}")
            await self._api("POST", "/api/categories/relabel", optional=True)
            return _dump({"deleted_rule": rule_id})

        if name == "set_category_type":
            kind = str(args.get("type") or "").upper()
            if kind not in ("EXPENSE", "INCOME", "INTERNAL"):
                raise ToolError("type is EXPENSE, INCOME or INTERNAL.")
            c = await self._category(args.get("category"))
            if c.get("type_locked"):
                raise ToolError(f"The type of '{c['name']}' is locked: the app relies on how it counts ({c['type']}).")
            r = await self._api("PUT", f"/api/categories/{c['id']}/type", body={"type": kind})
            return _dump({"category": self._category_out(r["categories"], c["name"])})

        if name == "rename_category":
            c = await self._category(args.get("category"))
            new_name = str(args.get("new_name") or "").strip()
            if not new_name:
                raise ToolError("Give the new name.")
            r = await self._api("PUT", f"/api/categories/{c['id']}/name", body={"name": new_name})
            return _dump({"renamed_from": c["name"], "category": self._category_out(r["categories"], new_name)})

        if name == "move_category":
            c = await self._category(args.get("category"))
            group_name = str(args.get("group_name") or "").strip()
            if not group_name:
                raise ToolError("Give the group.")
            r = await self._api("PUT", f"/api/categories/{c['id']}/group", body={"group_name": group_name})
            return _dump({"category": self._category_out(r["categories"], c["name"])})

        if name == "set_month_layout":
            body = {k: args[k] for k in ("mode", "day", "category") if k in args}
            if not body:
                raise ToolError("Give mode, day and/or category.")
            mp = await self._api("PUT", "/api/month-periods", body=body)
            shared = await self._api("GET", "/api/spending/shared-costs", optional=True)
            return _dump(settings_out(mp, shared))

        if name == "set_shared_costs_category":
            if "category" not in args:
                raise ToolError("Give the category, or null.")
            category = args.get("category")
            if category is not None:
                category = (await self._category(category))["name"]
            r = await self._api("PUT", "/api/spending/shared-costs", body={"category": category})
            return _dump({"shared_costs_category": r.get("category")})

        if name == "set_fixed_cost":
            fixed_name = str(args.get("name") or "").strip()
            if not fixed_name:
                raise ToolError("Give the counterparty name.")
            if "is_fixed" not in args or args["is_fixed"] not in (True, False, None):
                raise ToolError("is_fixed is true, false or null.")
            r = await self._api("PUT", "/api/spending/fixed-costs/choice", body={"name": fixed_name, "is_fixed": args["is_fixed"]})
            return _dump({"name": fixed_name, "is_fixed": args["is_fixed"], "fixed_costs": fixed_costs_out(r)})

        if name == "set_balance":
            account = await self._account(args.get("account"))
            when = args.get("date") or today.isoformat()
            r = await self._api(
                "PUT", f"/api/accounts/{account['id']}/balance", body={"date": when, "balance": float(args["balance"]), "source": "manual"}
            )
            a = r["account"]
            return _dump(
                {
                    "account": {
                        **{k: a.get(k) for k in ("id", "name", "kind", "balance", "balance_date")},
                        "account_number": _mask(a.get("iban")),
                    },
                    "date": when,
                }
            )

        if name == "delete_balance":
            account = await self._account(args.get("account"))
            when = str(args.get("date") or "")
            date.fromisoformat(when)
            r = await self._api("DELETE", f"/api/accounts/{account['id']}/balance/{when}")
            a = r["account"]
            return _dump(
                {
                    "deleted": {"account": a.get("name"), "date": when},
                    "account": {
                        **{k: a.get(k) for k in ("id", "name", "kind", "balance", "balance_date")},
                        "account_number": _mask(a.get("iban")),
                    },
                }
            )

        if name == "add_transaction":
            account = await self._account(args.get("account"))
            amount = float(args["amount"])
            if amount == 0:
                raise ToolError("The amount is not zero: positive for an expense, negative for income.")
            tx_name = str(args.get("name") or "").strip()
            if not tx_name:
                raise ToolError("Give the counterparty name.")
            category = args.get("category")
            if category is not None:
                category = (await self._category(category))["name"]
            body = {
                "account_id": account["id"],
                "date": args.get("date") or today.isoformat(),
                "amount": abs(amount),
                "direction": "expense" if amount > 0 else "income",
                "name": tx_name,
                "description": args.get("description") or "",
                "category": category,
            }
            t = (await self._api("POST", "/api/bank-transactions", body=body))["transaction"]
            keys = ("id", "date", "amount", "name", "description", "category", "group_name", "type", "category_source", "account_id")
            return _dump({"transaction": {k: t.get(k) for k in keys}})

        if name == "add_broker_transaction":
            listing = await self._api("GET", "/api/brokers")
            ref = str(args.get("broker") or "").strip()
            wanted = ref.lower().replace(" ", "_")
            account = next(
                (
                    a
                    for a in listing["accounts"]
                    if (ref.isdigit() and a["id"] == int(ref)) or a["broker"] == wanted or a["broker_label"].lower() == ref.lower()
                ),
                None,
            )
            if account is None:
                raise ToolError(f"No broker account '{ref}'. The user adds it first (Details or Accounts in the app).")
            body = {
                k: args.get(k)
                for k in ("kind", "isin", "name", "quantity", "price", "amount", "fee", "tax", "description")
                if args.get(k) is not None
            }
            body.update({"account_id": account["id"], "date": args.get("date") or today.isoformat()})
            r = await self._api("POST", "/api/brokers/transactions", body=body)
            a = r["account"]
            return _dump(
                {
                    "stored": r["stored"],
                    "account": {
                        "name": a.get("name"),
                        "broker": a.get("broker"),
                        "cash": a.get("balance"),
                        "cash_date": a.get("balance_date"),
                    },
                }
            )

        raise ToolError(f"Unknown tool {name}")

    async def handle(self, msg: dict) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # notification (initialized, cancelled): nothing to answer
            return None

        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        if method == "initialize":
            asked = params.get("protocolVersion")
            return ok(
                {
                    "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "stock-tracker", "title": "stock-tracker and wealth-tracker", "version": "1.0"},
                    "instructions": instructions(self.scope),
                }
            )
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": self.tools()})
        if method == "tools/call":
            try:
                text = await self.call(params.get("name", ""), params.get("arguments") or {})
                return ok({"content": [{"type": "text", "text": text}], "isError": False})
            except (ToolError, KeyError, ValueError, TypeError) as e:
                return ok({"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


# Access logs print the request path; the token of /api/mcp/<token> is kept out
# of them by trackerai_websec.log_redact (installed in app/main.py).


def _server_for(request: Request, token: str) -> Server:
    from app.deps import resolve_agent_token

    cfg = auth_store.load_config()
    username, entry = resolve_agent_token(request, token, cfg)
    if (cfg.get("credentials", {}).get("usernames", {}).get(username) or {}).get("suspended"):
        raise HTTPException(status_code=401, detail="This account is suspended")
    return Server(token, entry.get("scope", "read"), username)


async def _serve(request: Request, server: Server) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
    if isinstance(body, list):
        out = [x for x in [await server.handle(m) for m in body] if x]
        return JSONResponse(out) if out else Response(status_code=202)
    res = await server.handle(body)
    return JSONResponse(res) if res else Response(status_code=202)


@router.post("/api/mcp")
async def mcp(request: Request):
    from app.core.accounts import accounts

    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer agent token required", headers=OAuth(accounts).challenge("wealth"))
    return await _serve(request, _server_for(request, header[7:].strip()))


@router.post("/api/mcp/{token}")
async def mcp_path(token: str, request: Request):
    if token.startswith(PREFIX):
        raise HTTPException(status_code=401, detail="OAuth tokens require the Authorization header")
    return await _serve(request, _server_for(request, token))


@router.get("/api/mcp")
@router.get("/api/mcp/{token}")
def no_stream():
    return Response(status_code=405, headers={"Allow": "POST"})
