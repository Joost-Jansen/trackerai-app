"""
ai_labelling.py — Claude Haiku helps with what the rules do not recognise.

The order of certainty, and it stays that way:

  1. what you set by hand;
  2. the rules (default and your own);
  3. what you labelled yourself before for the same counterparty (categorization.learned);
  4. and only then a suggestion from Claude.

Claude only gets what is still open after that: without a category, or only
"paid to / received from friends" because the name looked like a person.
Asked once per transaction; the answer is stored in `ai_suggestions`. Certain
enough (categorization.AI_THRESHOLD) and relabel() takes it over, marked as
'ai'. What is doubtful stays for you to choose.

Privacy: off by default, turned on per user (preference `ai_labelling`), and
only if the server has an ANTHROPIC_API_KEY. IBANs, account and card numbers
and long references are removed before sending; name, description, amount and
date go along, because that is where the meaning is.
"""

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime

import trackerai_ai
from domain import preferences
from domain.i18n import tr
from domain.money import bank_transactions, categorization, safe_regex

MODEL = "claude-haiku-4-5-20251001"
# Which instruction a suggestion got: model and prompt version. A new version
# (a better instruction) makes asking again worthwhile; see _retry_ids.
PROMPT_VERSION = 2
VERSION = f"{MODEL}#{PROMPT_VERSION}"
# Version 2 (direction out/in and a reason) went live at this moment; its
# suggestions are still stored without a version label.
_DIRECTION_SINCE = "2026-09-15T15:10:00+00:00"
# For what Haiku could not place: a stronger model with more context. See thorough().
MODEL_THOROUGH = "claude-sonnet-5"
THOROUGH_VERSION = f"{MODEL_THOROUGH}#1"
THOROUGH_PER_RUN = 15
# One request to Claude per API call: the website does not wait forever, and 40
# transactions is plenty of time for Haiku. The page starts the next round itself
# and shows what is happening.
PER_RUN = 40
MAX_PER_ROUND = PER_RUN


class AiError(RuntimeError):
    """Something the user needs to know: no key, turned off, or Claude failed."""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def on(conn: sqlite3.Connection) -> bool:
    value = preferences.read(conn, "ai_labelling")
    return bool(value and value.get("on"))


# What is removed before sending. Order matters: the ING fields first, then
# whatever numbers remain.
_AWAY = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b[A-Z]{2}\d{2}\s?[A-Z]{4}(\s?\d){6,}\b",  # IBAN
        r"card (sequence )?no\.?:?\s*[\d*\s]+",  # card number / sequence number
        r"\b(term(inal)?|transaction|transactie):\s*\S+",
        r"\b(value date|date/time|date|time|datum|tijd):\s*[\d/:\-\s]+",
        r"\b(name|description|naam|omschrijving|iban|kenmerk|referentie)\s*:",
        r"\b(?=[A-Z]*\d)[A-Z0-9-]{10,}\b",  # references with digits
        r"\d{5,}",
    )
]


def mask(text: str | None) -> str:
    off = text or ""
    for pattern in _AWAY:
        off = pattern.sub(" ", off)
    return re.sub(r"\s+", " ", off).strip()[:140]


def to_ask(conn: sqlite3.Connection) -> list[dict]:
    """What Claude has not seen yet and the rules did not know (for sure); newest first.

    A payment to or from a friend only when the description says what for: there
    is nothing to guess from a name alone.
    """
    return [
        dict(r)
        for r in conn.execute(
            """
        SELECT id, date, amount, name, description, category_auto FROM bank_transactions
         WHERE category_manual IS NULL
           AND COALESCE(category_auto, ?) IN (?, ?, ?)
           AND id NOT IN (SELECT transaction_id FROM ai_suggestions)
         ORDER BY date DESC, id DESC
        """,
            (categorization.UNKNOWN, categorization.UNKNOWN, *categorization.FRIENDS),
        )
        if r["category_auto"] not in categorization.FRIENDS or categorization.has_target_text(r["name"], r["description"])
    ]


def _for_claude(conn: sqlite3.Connection) -> list[dict]:
    """The categories Claude may choose from: nothing internal. Saving, own accounts
    and "exclude" follow from your accounts or are your choice.
    """
    categorization.seed(conn)
    return [c for c in categorization.load_categories(conn) if c["type"] != "INTERNAL"]


_SYSTEM = """You categorise Dutch bank transactions for a household budget.

direction: "out" is money that went out (an expense), "in" is money that came in. For "in" never
"Betaald aan vrienden"; for "out" never "Ontvangen van vrienden" or a category of type INCOME.
Choose exactly one category per transaction from the list below, spelled literally.

Guidelines:
- A payment to or from a person (or a Tikkie/payment request) without a hint of what it was for:
  "Betaald aan vrienden" (expense) or "Ontvangen van vrienden" (in).
- If the description says what it was for (food, hotel, tickets, groceries…), choose that category,
  also when the money came in: then it is a refund of that expense.
- Card payments abroad or in a foreign currency usually belong to "Vakantie".
- If you recognise the kind of business from the name (café, restaurant, clothing shop, gym…), use that.
- Never guess from a person's name alone: without a hint of what it was for, it is friends.
- A refund belongs to the category of the original expense; if you don't know it, "Onbekend".
- If you are really unsure, choose "Onbekend".

confidence is a number from 0 to 1: how sure you are. Be honest. A business name whose kind of
business you don't know is at most 0.5; a well-known chain or a clear description may be 0.9 or higher.

reason is why, in at most eight words: "well-known clothing chain", "description mentions hotel", "payment in
Indonesian rupiah". Don't repeat the category.

Categories (group — name — type):"""


def _ask_claude(items: list[dict], categories: list[dict], *, extra: str = "", model: str = MODEL) -> list[dict]:
    """One request to the Messages API; returns [{id, category, confidence, reason}]."""
    names = [c["name"] for c in categories]
    item_list = "\n".join(f"- {c['group_name']} — {c['name']} — {c['type']}" for c in categories)
    body = {
        "model": model,
        "max_tokens": 4096,
        "system": _SYSTEM + item_list + extra,
        "tools": [
            {
                "name": "labels",
                "description": "The category per transaction.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "labels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "category": {"type": "string", "enum": names},
                                    "confidence": {"type": "number"},
                                    "reason": {"type": "string", "description": "Waarom, in hooguit acht woorden."},
                                },
                                "required": ["id", "category", "confidence"],
                            },
                        }
                    },
                    "required": ["labels"],
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "labels"},
        "messages": [{"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
    }
    return _api(body).get("labels", [])


def _api(body: dict) -> dict:
    """One request to the Messages API with a required tool (through the shared
    client, packages/ai); returns what Claude filled in for that tool.
    """
    try:
        result = trackerai_ai.ask(body, timeout=90, retries=0)  # as before: one try, the page starts the next round
    except trackerai_ai.AiError as e:
        if e.code in ("unreachable", "unavailable"):
            raise AiError(tr("Claude could not be reached. Try again later.")) from e
        raise AiError(tr("Claude returned an error ({0}). Check the API key and the credit.", e.status or e.code)) from e
    return result.tool_input(body["tool_choice"]["name"])


def _valid(answers: list, ids: set[int], valid: set[str]) -> dict[int, tuple[str, float, str | None]]:
    """Only answers about a transaction that was asked about, with an existing
    category; (category, confidence, reason).
    """
    off = {}
    for a in answers:
        if isinstance(a, dict) and a.get("category") in valid and a.get("id") in ids:
            try:
                confidence = min(max(float(a.get("confidence", 0)), 0.0), 1.0)
            except (TypeError, ValueError):
                confidence = 0.0
            reason = a.get("reason")
            off[a["id"]] = (a["category"], confidence, reason.strip()[:80] if isinstance(reason, str) and reason.strip() else None)
    return off


def fit_direction(category: str, amount: float, types: dict[str, str]) -> str | None:
    """The category if it fits the direction of the money; otherwise the right
    friends category, or None.

    Claude sometimes put received money on "Betaald aan vrienden". An income
    category on an expense is always wrong. A spending category on money coming
    in is fine: that is a refund of that expense.
    """
    within = amount < 0
    paid, received = categorization.FRIENDS
    if category in categorization.FRIENDS:
        return received if within else paid
    if types.get(category) == "INCOME" and not within:
        return None
    return category


def _in_direction(answered: dict, amount_of: dict[int, float], types: dict[str, str]) -> dict:
    off = {}
    for i, (category, confidence, reason) in answered.items():
        good = fit_direction(category, amount_of[i], types)
        off[i] = (good, confidence, reason) if good else (categorization.UNKNOWN, 0.0, reason)
    return off


def _direction(amount: float) -> str:
    return "in" if amount < 0 else "out"


def _allowed(conn: sqlite3.Connection) -> None:
    if not available():
        raise AiError(tr("No ANTHROPIC_API_KEY is set on this server."))
    if not on(conn):
        raise AiError(tr("First turn on ‘Let Claude help’."))


def analyse(conn: sqlite3.Connection, *, limit: int = MAX_PER_ROUND) -> dict:
    """Asks Claude for a suggestion for what is still open, and relabels.

    At most `limit` transactions at a time, so a request does not take minutes;
    `rest` says whether another round is needed.
    """
    _allowed(conn)
    categories = _for_claude(conn)
    valid = {c["name"] for c in categories}
    types = {c["name"]: c["type"] for c in categories}
    rows = to_ask(conn)[:limit]
    now = datetime.now(UTC).isoformat(timespec="seconds")

    suggestions, error = 0, None
    for begin in range(0, len(rows), PER_RUN):
        block = rows[begin : begin + PER_RUN]
        items = [
            {
                "id": r["id"],
                "date": r["date"],
                "amount": round(abs(r["amount"]), 2),
                "direction": _direction(r["amount"]),
                "name": mask(r["name"])[:60],
                "description": mask(r["description"]),
            }
            for r in block
        ]
        try:
            answers = _ask_claude(items, categories)
        except AiError as e:
            error = str(e)
            break
        answered = _in_direction(_valid(answers, {r["id"] for r in block}, valid), {r["id"]: r["amount"] for r in block}, types)
        # What it skipped counts as "does not know": do not ask again either.
        conn.executemany(
            "INSERT OR REPLACE INTO ai_suggestions (transaction_id, category, confidence, reason, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(r["id"], *answered.get(r["id"], (categorization.UNKNOWN, 0.0, None)), VERSION, now) for r in block],
        )
        conn.commit()
        suggestions += len(answered)

    if error and suggestions == 0:
        raise AiError(error)
    if suggestions:
        # Not everything: what was open (and was AI or learned before) runs again,
        # and that is what a suggestion is about.
        categorization.relabel(conn)
    items = _round_items(conn, [r["id"] for r in rows])
    return {
        "asked": len(rows),
        "suggestions": suggestions,
        "labelled": sum(1 for i in items if i["applied"]),
        "doubt": sum(1 for i in items if not i["applied"] and i["category"] != categorization.UNKNOWN),
        "items": items,
        "rest": len(to_ask(conn)),
        "error": error,
    }


def _round_items(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    """What Claude said this round, per transaction, and whether it was taken over:
    that is how the page sees what happened.
    """
    if not ids:
        return []
    places = ",".join("?" * len(ids))
    return [
        dict(r) | {"applied": bool(r["applied"])}
        for r in conn.execute(
            f"""
        SELECT t.name, t.amount, v.category, v.confidence,
               (t.category_source = 'ai' AND t.category_manual IS NULL) AS applied
          FROM ai_suggestions v JOIN bank_transactions t ON t.id = v.transaction_id
         WHERE v.transaction_id IN ({places})
         ORDER BY v.confidence DESC
        """,
            ids,
        )
    ]


def status(conn: sqlite3.Connection) -> dict:
    by_ai = conn.execute("SELECT COUNT(*) FROM bank_transactions WHERE category_source = 'ai' AND category_manual IS NULL").fetchone()[0]
    groups = _to_check(conn)
    return {
        "available": available(),
        "on": on(conn),
        "to_ask": len(to_ask(conn)),
        "by_ai": by_ai,
        "model": MODEL,
        "to_check": sum(len(g["ids"]) for g in groups),
        "to_check_groups": len(groups),
        "rule_candidates": len(_candidates(conn)),
        "again": len(_retry_ids(conn)),
        "thorough": len(_thorough_groups(conn)),
    }


def reject(conn: sqlite3.Connection, ids: list[int]) -> dict:
    """ "Not right": Claude's label comes off and it does not suggest it again. The
    transaction is then back among what is still to be labelled (or among
    friends, if the rules found that).
    """
    chosen = sorted({int(i) for i in ids})
    if not chosen:
        raise ValueError(tr("No transactions were chosen."))
    conn.executemany("UPDATE ai_suggestions SET confidence = 0 WHERE transaction_id = ?", [(i,) for i in chosen])
    conn.commit()
    categorization.relabel(conn)
    return {"updated": len(chosen)}


def _retry_ids(conn: sqlite3.Connection) -> list[int]:
    """Still without a category, and Claude did not know earlier or was in doubt —
    with an older instruction than now. Asking again with the same instruction
    gives the same answer, so the page does not offer that. Not what you rejected
    yourself ("Not right": a category with confidence 0).
    """
    return [
        r["transaction_id"]
        for r in conn.execute(
            """
        SELECT v.transaction_id FROM ai_suggestions v JOIN bank_transactions t ON t.id = v.transaction_id
         WHERE t.category_manual IS NULL AND COALESCE(t.category_source, 'rule') != 'ai'
           AND COALESCE(t.category_auto, ?) = ?
           AND (v.category = ? OR (v.confidence > 0 AND v.confidence < ?))
           AND COALESCE(v.model, '') != ?
           AND NOT (COALESCE(v.model, '') = ? AND v.created_at >= ?)
           AND COALESCE(v.model, '') NOT LIKE ?
        """,
            (
                categorization.UNKNOWN,
                categorization.UNKNOWN,
                categorization.UNKNOWN,
                categorization.AI_THRESHOLD,
                VERSION,
                MODEL,
                _DIRECTION_SINCE,
                f"{MODEL_THOROUGH}#%",
            ),
        )
    ]


def ask_again(conn: sqlite3.Connection) -> dict:
    """Put what has no category yet to Claude again: the next round (analyse) takes
    it along again. Worthwhile after a better instruction, or when more is known
    in the meantime.
    """
    _allowed(conn)
    ids = _retry_ids(conn)
    conn.executemany("DELETE FROM ai_suggestions WHERE transaction_id = ?", [(i,) for i in ids])
    conn.commit()
    return {"released": len(ids), "to_ask": len(to_ask(conn))}


def by_ai(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    """What Claude labelled and you have not reviewed yet, least certain first."""
    return [
        dict(r)
        for r in conn.execute(
            """
        SELECT t.id, t.date, t.account_id, t.amount, t.name, t.description,
               t.category_auto AS category, v.confidence, v.reason
          FROM bank_transactions t JOIN ai_suggestions v ON v.transaction_id = t.id
         WHERE t.category_source = 'ai' AND t.category_manual IS NULL
         ORDER BY v.confidence ASC, t.date DESC
         LIMIT ?
        """,
            (limit,),
        )
    ]


# ---------------------------------------------------------------------------
# Checking everything
# ---------------------------------------------------------------------------
#
# On request Claude also looks at what the rules already labelled, and says
# where it disagrees. Nothing is taken over by itself here: a rule is a
# deliberate choice, a model's different opinion is not. You choose per
# counterparty: the suggestion, the original, or something else.
#
# Equal counterparties go once: three hundred times the same supermarket is one
# question, and the answer applies to all three hundred.

CHECK_THRESHOLD = 0.7
MAX_GROUPS_PER_ROUND = PER_RUN
RULE_PRIORITY = 25  # like "Make rule" under To label
CHOICES = ("suggestion", "original", "otherwise")

_CHECK = """

Check: each transaction already has a category in "now", given by a rule; "count" says how often
this counterparty occurs like this. Give the category you think is right. If "now" is right, give exactly that.
Only deviate when you are reasonably sure."""


def _to_check(conn: sqlite3.Connection) -> list[dict]:
    """What the rules labelled and Claude has not seen yet, grouped per counterparty.

    Only spending and income: what is internal (own accounts, saving, investing)
    follows from your accounts, and Claude knows nothing about that. Not what you
    set by hand, not what is still open (analyse does that), and not what Claude
    already labelled itself.
    """
    rows = conn.execute(
        """
        SELECT t.id, t.date, t.amount, t.name, t.description, t.category_effective AS now
          FROM bank_transactions_typed t
          JOIN categories c ON c.name = t.category_effective
         WHERE t.category_manual IS NULL
           AND c.type IN ('EXPENSE', 'INCOME')
           AND t.category_effective NOT IN (?, ?, ?)
           AND COALESCE(t.category_source, 'rule') != 'ai'
           AND t.id NOT IN (SELECT transaction_id FROM ai_checks)
         ORDER BY t.date DESC, t.id DESC
        """,
        (categorization.UNKNOWN, *categorization.FRIENDS),
    ).fetchall()
    groups: dict = {}
    for r in rows:
        # Behind a Tikkie or payment processor there is something different every time:
        # those only together when the description is equal too.
        loose = not categorization.learn_keys(r["name"], None)
        key = (mask(r["name"]).upper(), r["amount"] < 0, r["now"], mask(r["description"]).upper() if loose else "")
        groups.setdefault(key, {"example": dict(r), "ids": []})["ids"].append(r["id"])
    return list(groups.values())


def verify(conn: sqlite3.Connection, *, limit: int = MAX_GROUPS_PER_ROUND) -> dict:
    """One round of checking: at most `limit` counterparties. `rest` says whether
    another round is needed.
    """
    _allowed(conn)
    categories = _for_claude(conn)
    valid = {c["name"] for c in categories}
    types = {c["name"]: c["type"] for c in categories}
    groups = _to_check(conn)[:limit]
    now = datetime.now(UTC).isoformat(timespec="seconds")

    completed, error, found = 0, None, []
    for begin in range(0, len(groups), PER_RUN):
        block = groups[begin : begin + PER_RUN]
        items = [
            {
                "id": g["ids"][0],
                "date": v["date"],
                "amount": round(abs(v["amount"]), 2),
                "direction": _direction(v["amount"]),
                "name": mask(v["name"])[:60],
                "description": mask(v["description"]),
                "now": v["now"],
                "count": len(g["ids"]),
            }
            for g in block
            for v in [g["example"]]
        ]
        try:
            answers = _ask_claude(items, categories, extra=_CHECK)
        except AiError as e:
            error = str(e)
            break
        answered = _in_direction(
            _valid(answers, {g["ids"][0] for g in block}, valid), {g["ids"][0]: g["example"]["amount"] for g in block}, types
        )
        rows = []
        for g in block:
            current = g["example"]["now"]
            # No answer is "no opinion": agrees with what is there.
            category, confidence, reason = answered.get(g["ids"][0], (current, 0.0, None))
            rows += [(tid, category, confidence, reason, current, VERSION, now) for tid in g["ids"]]
            if category != current and confidence >= CHECK_THRESHOLD:
                found.append(
                    {
                        "name": g["example"]["name"],
                        "now": current,
                        "suggestion": category,
                        "confidence": confidence,
                        "reason": reason,
                        "count": len(g["ids"]),
                    }
                )
        conn.executemany(
            "INSERT OR REPLACE INTO ai_checks (transaction_id, category, confidence, reason, current, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        completed += len(block)

    if error and completed == 0:
        raise AiError(error)
    return {"checked": completed, "rest": len(_to_check(conn)), "deviating": len(found), "items": found, "error": error}


def deviations(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    """Where Claude (certainly enough) disagrees with what is there now and you have
    not chosen yet, per counterparty; the largest amounts first.
    """
    types = {c["name"]: c["type"] for c in categorization.load_categories(conn)}
    groups: dict = {}
    for r in conn.execute(
        """
        SELECT t.id, t.date, t.amount, t.name, t.description, t.category_effective AS now,
               a.category AS suggestion, a.confidence, a.reason
          FROM ai_checks a JOIN bank_transactions_typed t ON t.id = a.transaction_id
         WHERE a.decision IS NULL AND t.category_manual IS NULL
           AND a.confidence >= ? AND a.category != t.category_effective
         ORDER BY t.date DESC, t.id DESC
        """,
        (CHECK_THRESHOLD,),
    ):
        # Also what was stored before the direction check.
        if fit_direction(r["suggestion"], r["amount"], types) != r["suggestion"]:
            continue
        g = groups.setdefault(
            (r["name"], r["now"], r["suggestion"]),
            {
                "name": r["name"],
                "now": r["now"],
                "suggestion": r["suggestion"],
                "confidence": 0.0,
                "ids": [],
                "total": 0.0,
                "last": r["date"],
                "description": r["description"],
                "reason": r["reason"],
                # A rule on the name is only possible when the name is the counterparty.
                "rule_possible": bool(categorization.learn_keys(r["name"], None)),
            },
        )
        g["ids"].append(r["id"])
        g["total"] += r["amount"]
        g["confidence"] = max(g["confidence"], r["confidence"])
    off = sorted(groups.values(), key=lambda g: -abs(g["total"]))[:limit]
    for g in off:
        g["count"] = len(g["ids"])
        g["total"] = round(g["total"], 2)
    return off


def decision(conn: sqlite3.Connection, *, ids: list[int], choice: str, category: str | None = None, rule: bool = False) -> dict:
    """What you make of it. `original` leaves everything; `suggestion` or `otherwise`
    sets the category — as a rule on the name (also for what is still to come),
    or as your own label on exactly these transactions.
    """
    if choice not in CHOICES:
        raise ValueError(tr("Choose from: {0}.", ", ".join(CHOICES)))
    ids = sorted({int(i) for i in ids})
    if not ids:
        raise ValueError(tr("No transactions were chosen."))
    if choice != "original":
        categorization.seed(conn)
        if category not in {c["name"] for c in categorization.load_categories(conn)}:
            raise ValueError(tr("Choose an existing category."))
        places = ",".join("?" * len(ids))
        names = {r["name"] for r in conn.execute(f"SELECT name FROM bank_transactions WHERE id IN ({places})", ids)}
        name = next(iter(names)) if len(names) == 1 else None
        if rule and name and categorization.learn_keys(name, None):
            categorization.make_rule(
                conn, priority=RULE_PRIORITY, field="N", pattern=re.escape(name.strip().upper()), direction="", category=category
            )
            categorization.relabel(conn, everything=True)
        else:
            bank_transactions.set_category_manual_for(conn, ids, category)
            categorization.relabel(conn)
    conn.executemany("UPDATE ai_checks SET decision = ? WHERE transaction_id = ?", [(choice, i) for i in ids])
    conn.commit()
    return {"updated": len(ids)}


# ---------------------------------------------------------------------------
# Rule suggestions
# ---------------------------------------------------------------------------
#
# What you or Claude recognised for a counterparty that occurs more often
# becomes a rule: then the next payment goes right by itself, for free and
# without asking. Claude comes up with the pattern ("BEDRIJFSREST" instead of
# "Bedrijfsrest. 7045 DELFT NLD"); the app tests it on your whole history and
# only shows what is not too broad and does not clash with your own choices.
# You accept it or not.

MIN_TIMES = 2
MAX_CANDIDATES = 30  # one request per call, as above

_PATTERNS = """You make labelling rules for a household budget. Per group you get the names of one counterparty as the
bank writes them, and the category. Give per group a short regex pattern (Python, case-insensitive; it searches
anywhere in the name) that finds all these names and as few other businesses or people as possible.
- Use the distinctive part of the name, not the place name, the branch number or the country code.
  Example: "Bedrijfsrest. 7045 DELFT NLD" and "Bedrijfsrest. 7047 DELFT NLD" → BEDRIJFSREST
- Write in capitals and escape characters with a special meaning (\\. \\* \\+ \\( etc.).
- No ^ or $, unless the pattern would otherwise also find something quite different."""


def _candidates(conn: sqlite3.Connection) -> list[dict]:
    """Counterparties that can become a rule: at least twice, each time (80%) the
    same category from you or Claude, and the rules do not know it now. What has
    been suggested before — accepted or not — does not come back.
    """
    groups: dict = defaultdict(list)
    for r in conn.execute("SELECT id, name, category_manual, category_auto, category_source FROM bank_transactions"):
        if r["category_manual"]:
            wish = None if r["category_manual"] in categorization._NOT_LEARN else r["category_manual"]
        else:
            wish = r["category_auto"] if r["category_source"] in ("ai", "learned") else None
        name = [s for s in categorization.learn_keys(r["name"], None) if s.startswith("naam:")]
        if wish and name:
            groups[name[0]].append((dict(r), wish))
    already = {r["key"] for r in conn.execute("SELECT key FROM rule_suggestions")}
    off = []
    for key, items in groups.items():
        if key in already or len(items) < MIN_TIMES:
            continue
        category, n = Counter(w for _, w in items).most_common(1)[0]
        if n / len(items) < 0.8:
            continue
        # If the rules already know it, there is nothing to gain.
        if all(r["category_source"] == "rule" and r["category_auto"] == category for r, _ in items):
            continue
        off.append(
            {"key": key, "category": category, "names": sorted({r["name"] for r, _ in items})[:8], "ids": [r["id"] for r, _ in items]}
        )
    return sorted(off, key=lambda k: -len(k["ids"]))


def _ask_patterns(groups: list[dict]) -> list[dict]:
    """Claude comes up with a pattern per group; returns [{id, pattern}]."""
    body = {
        "model": MODEL,
        "max_tokens": 2048,
        "system": _PATTERNS,
        "tools": [
            {
                "name": "patterns",
                "description": "The pattern per group.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "patterns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"id": {"type": "integer"}, "pattern": {"type": "string"}},
                                "required": ["id", "pattern"],
                            },
                        }
                    },
                    "required": ["patterns"],
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "patterns"},
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    [{"id": g["id"], "category": g["category"], "names": [mask(n)[:60] for n in g["names"]]} for g in groups],
                    ensure_ascii=False,
                ),
            }
        ],
    }
    return _api(body).get("patterns", [])


def _fallback(key: str) -> str:
    """When Claude's pattern does not pass the test: the name without digits and
    country code, word for word ("TIOFLI.*AMSTERDAM").
    """
    return ".*".join(re.escape(w) for w in key.removeprefix("naam:").split())


def _all_rows(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, category_manual, category_effective AS category, category_source FROM bank_transactions_typed"
        )
    ]


def _test(rows: list[dict], pattern: str | None, category: str, ids: list[int]) -> dict | None:
    """What a rule with this pattern would do, or None if it is unusable: broken,
    too short, misses its own counterparty, clashes with what you set by hand, or
    takes over too much of what another rule already knew.
    """
    if not pattern or len(pattern.strip()) < 3:
        return None
    try:
        safe_regex.check(pattern)  # Claude's patterns go through the same guard as anyone's
    except ValueError:
        return None
    touches = [r for r in rows if safe_regex.search(pattern, r["name"] or "")]
    if not touches or len({r["id"] for r in touches} & set(ids)) < 0.9 * len(ids):
        return None
    weak = (categorization.UNKNOWN, *categorization.FRIENDS)
    clashes = sum(
        1
        for r in touches
        if r["category_manual"] and r["category_manual"] != category and r["category_manual"] not in categorization._NOT_LEARN
    )
    changes = sum(1 for r in touches if not r["category_manual"] and r["category"] != category)
    overwrites = sum(
        1
        for r in touches
        if not r["category_manual"] and r["category_source"] == "rule" and r["category"] not in weak and r["category"] != category
    )
    if clashes > 0.1 * len(touches) or overwrites > max(1, len(touches) // 5):
        return None
    return {
        "touches": len(touches),
        "changes": changes,
        "overwrites": overwrites,
        "clashes": clashes,
        "examples": sorted({r["name"] for r in touches})[:5],
    }


def make_rule_suggestions(conn: sqlite3.Connection, *, limit: int = MAX_CANDIDATES) -> dict:
    """Lets Claude come up with patterns for the candidates, and stores what passes the test."""
    _allowed(conn)
    candidates = _candidates(conn)[:limit]
    rows = _all_rows(conn)
    existing = {(r["pattern"], r["category"]) for r in categorization.load_rules(conn, only_active=False)}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    suggested, items = 0, []
    for begin in range(0, len(candidates), 30):
        block = candidates[begin : begin + 30]
        for i, k in enumerate(block):
            k["id"] = i
        try:
            answers = {a.get("id"): a.get("pattern") for a in _ask_patterns(block) if isinstance(a, dict)}
        except AiError:
            if suggested == 0:
                raise
            break
        for k in block:
            pattern = next(
                (
                    p
                    for p in (answers.get(k["id"]), _fallback(k["key"]))
                    if isinstance(p, str) and (p, k["category"]) not in existing and _test(rows, p, k["category"], k["ids"])
                ),
                None,
            )
            # What did not work is remembered too: otherwise it costs the same again every time.
            conn.execute(
                "INSERT OR IGNORE INTO rule_suggestions (key, pattern, category, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (k["key"], pattern, k["category"], None if pattern else "onbruikbaar", now),
            )
            suggested += bool(pattern)
            if pattern:
                items.append({"pattern": pattern, "category": k["category"], "count": len(k["ids"])})
        conn.commit()
    return {"suggested": suggested, "viewed": len(candidates), "items": items, "rest": len(_candidates(conn))}


def rule_suggestions(conn: sqlite3.Connection) -> list[dict]:
    """The open suggestions, with what they would do *now*; what no longer passes the
    test in the meantime drops out. Most transactions first.
    """
    rows = _all_rows(conn)
    off = []
    for v in conn.execute("SELECT id, pattern, category FROM rule_suggestions WHERE status IS NULL ORDER BY id"):
        test = _test(rows, v["pattern"], v["category"], [])
        if test:
            off.append({"id": v["id"], "pattern": v["pattern"], "category": v["category"], **test})
    return sorted(off, key=lambda v: -v["touches"])


def rule_suggestion_decision(conn: sqlite3.Connection, *, ids: list[int], accept: bool) -> dict:
    """Accepting makes the rules and relabels everything; rejecting remembers that,
    so the same suggestion does not come back.
    """
    chosen = {int(i) for i in ids}
    if not chosen:
        raise ValueError(tr("No suggestions were chosen."))
    if accept:
        open_ = [v for v in rule_suggestions(conn) if v["id"] in chosen]
        for v in open_:
            categorization.make_rule(conn, priority=RULE_PRIORITY, field="N", pattern=v["pattern"], direction="", category=v["category"])
        if open_:
            categorization.relabel(conn, everything=True)
        chosen = {v["id"] for v in open_}
    conn.executemany(
        "UPDATE rule_suggestions SET status = ? WHERE id = ? AND status IS NULL",
        [("accepted" if accept else "rejected", i) for i in chosen],
    )
    conn.commit()
    return {"updated": len(chosen)}


# ---------------------------------------------------------------------------
# Looking thoroughly
# ---------------------------------------------------------------------------
#
# For what Haiku could not place, asking the same question again gives the same
# answer. A thorough round asks it differently: a stronger model, per
# counterparty several descriptions with date and amount (time, frequency and
# place often say more than one row), and examples of how you label similar
# counterparties. Once per counterparty; what you rejected yourself is left out.

_THOROUGH = """

Thorough round: a first round could not place these counterparties. Per counterparty you get "count",
"total" and up to five examples with date, amount and description. Look for clues: the kind of business behind
the name (also when it is abbreviated), the place, the time, how often it comes back and how large the amounts are.
Choose "Onbekend" only when there really is no clue.

This is how this user labels similar counterparties (name → category):"""


def _thorough_groups(conn: sqlite3.Connection) -> list[list[dict]]:
    """What has no category yet and has not been looked at thoroughly, per
    counterparty (behind a Tikkie or payment processor: per transaction); largest
    amount first.
    """
    groups: dict = {}
    for r in conn.execute(
        """
        SELECT id, date, amount, name, description FROM bank_transactions
         WHERE category_manual IS NULL AND COALESCE(category_auto, ?) = ?
           AND id NOT IN (SELECT transaction_id FROM ai_suggestions WHERE model LIKE ?)
           AND id NOT IN (SELECT transaction_id FROM ai_suggestions WHERE confidence = 0 AND category != ?)
         ORDER BY date DESC, id DESC
        """,
        (categorization.UNKNOWN, categorization.UNKNOWN, f"{MODEL_THOROUGH}#%", categorization.UNKNOWN),
    ):
        loose = not categorization.learn_keys(r["name"], None)
        groups.setdefault((r["name"], r["id"]) if loose else (r["name"],), []).append(dict(r))
    return sorted(groups.values(), key=lambda g: -abs(sum(r["amount"] for r in g)))


def _examples(conn: sqlite3.Connection, n: int = 80) -> list[str]:
    """How this user labels: the most frequent counterparties with their category.
    Without friends (those are names of people) and without internal.
    """
    return [
        f"{mask(r['name'])[:50]} → {r['category']}"
        for r in conn.execute(
            """
        SELECT t.name AS name, t.category_effective AS category, COUNT(*) AS count
          FROM bank_transactions_typed t JOIN categories c ON c.name = t.category_effective
         WHERE t.category_effective NOT IN (?, ?, ?) AND c.type != 'INTERNAL'
         GROUP BY t.name, t.category_effective
         ORDER BY count DESC
         LIMIT ?
        """,
            (categorization.UNKNOWN, *categorization.FRIENDS, n),
        )
        if mask(r["name"])
    ]


def thorough(conn: sqlite3.Connection, *, limit: int = THOROUGH_PER_RUN) -> dict:
    """One thorough round: at most `limit` counterparties, one request."""
    _allowed(conn)
    categories = _for_claude(conn)
    valid = {c["name"] for c in categories}
    types = {c["name"]: c["type"] for c in categories}
    groups = _thorough_groups(conn)[:limit]
    if not groups:
        return {"asked": 0, "labelled": 0, "doubt": 0, "items": [], "rest": 0, "error": None}
    items = [
        {
            "id": g[0]["id"],
            "name": mask(g[0]["name"])[:60],
            "direction": _direction(sum(r["amount"] for r in g)),
            "count": len(g),
            "total": round(abs(sum(r["amount"] for r in g)), 2),
            "examples": [{"date": r["date"], "amount": round(abs(r["amount"]), 2), "description": mask(r["description"])} for r in g[:5]],
        }
        for g in groups
    ]
    extra = _THOROUGH + "\n".join(f"- {v}" for v in _examples(conn))
    answers = _ask_claude(items, categories, extra=extra, model=MODEL_THOROUGH)
    answered = _in_direction(
        _valid(answers, {g[0]["id"] for g in groups}, valid), {g[0]["id"]: sum(r["amount"] for r in g) for g in groups}, types
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO ai_suggestions (transaction_id, category, confidence, reason, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(r["id"], *answered.get(g[0]["id"], (categorization.UNKNOWN, 0.0, None)), THOROUGH_VERSION, now) for g in groups for r in g],
    )
    conn.commit()
    categorization.relabel(conn)
    off = _round_items(conn, [g[0]["id"] for g in groups])
    return {
        "asked": len(groups),
        "labelled": sum(1 for i in off if i["applied"]),
        "doubt": sum(1 for i in off if not i["applied"] and i["category"] != categorization.UNKNOWN),
        "items": off,
        "rest": len(_thorough_groups(conn)),
        "error": None,
    }
