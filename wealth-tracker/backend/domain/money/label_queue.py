"""
label_queue.py — everything that needs a decision from you, in one queue.

To label had grown into separate blocks: what the rules did not recognise,
what was suspicious, what Claude labelled, where it disagreed, and rule
suggestions, each with its own buttons. Here that becomes one list of items
with the same shape: who (title), how much (count, total), what is there now
(now), what is suggested (suggestion, confidence, reason) and which
transactions they are (ids). That way the page chooses the same everywhere —
agree, reject or something else — and the largest amounts are on top, wherever
they come from.

Kinds:
  own       probably between your own accounts (categorization.suspicious)
  doubt     Claude suggested something, but was not certain enough to label
  disagree  Claude disagrees with what a rule did ("Check everything")
  unknown   no category and no suggestion yet, per counterparty
  rule      a rule Claude suggests
  ai        what Claude labelled: reviewing is allowed, not required

What Claude brings in only appears if it may help (ai_labelling).
"""

import re
import sqlite3
from collections import defaultdict

from domain.money import ai_labelling
from domain.money import bank_transactions
from domain.money import categorization
from domain.i18n import tr

KINDS = ("own", "doubt", "disagree", "unknown", "rule", "ai")
CHOICES = ("agreed", "reject", "otherwise")
# Reviewing is a choice, not a task: does not count in "waiting for you".
OPTIONAL = ("ai",)

UNKNOWN = categorization.UNKNOWN
FRIENDS = categorization.FRIENDS


_LABELS = re.compile(r"\b(reference|other party|value date|date|time|iban|bic|name|description|naam|"
                     r"omschrijving|kenmerk|referentie)\s*:\s*", re.IGNORECASE)
_NUMBERS = re.compile(r"(?<!\w)[\d/:.\-]+(?!\w)")


def readable(description: str | None, name: str | None) -> str:
    """The description without bank noise: no IBANs, references, dates, card and
    terminal numbers, and without the name that is already above it. Empty if
    nothing meaningful is left after that.
    """
    # Leaving out the same as for Claude, but not cut off: this is for reading.
    text = description or ""
    for pattern in ai_labelling._AWAY:
        text = pattern.sub(" ", text)
    text = _LABELS.sub(" ", text)
    text = _NUMBERS.sub(" ", text)
    if name and name.strip():
        text = re.sub(re.escape(name.strip()), " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ·,-")
    return text if re.search(r"[A-Za-zÀ-ÿ]{3}", text) else ""


def _item(kind: str, key: str, title: str, rows: list[dict], *, now: str | None,
          suggestion: str | None = None, confidence: float | None = None, reason: str | None = None,
          rule_possible: bool = False, **extra) -> dict:
    description = next((r["description"] for r in rows if r["description"]), "")
    return {
        "key": f"{kind}:{key}", "kind": kind, "title": title,
        "ids": [r["id"] for r in rows], "count": len(rows),
        "total": round(sum(r["amount"] for r in rows), 2),
        "last": max((r["date"] for r in rows), default=None),
        "description": description, "remark": readable(description, title),
        "now": now, "suggestion": suggestion, "confidence": confidence, "reason": reason,
        "rule_possible": rule_possible, **extra,
    }


def _name_is_counterparty(name: str | None) -> bool:
    """A rule on the name is only possible when the name is the counterparty (not a Tikkie or processor)."""
    return bool(categorization.learn_keys(name, None))


def _own(conn: sqlite3.Connection) -> list[dict]:
    return [_item("own", str(r["id"]), r["name"], [r], now=r["category_effective"],
                  suggestion=r["suggestion"], reason=r["reason"])
            for r in categorization.suspicious(conn, limit=500)]


def _doubt(conn: sqlite3.Connection, already: set[int]) -> list[dict]:
    """Open transactions where Claude suggested something below the threshold. What
    is certain enough has already been labelled (see _restore).
    """
    types = {c["name"]: c["type"] for c in categorization.load_categories(conn)}
    groups: dict = defaultdict(list)
    for r in conn.execute(
        """
        SELECT t.id, t.date, t.amount, t.name, t.description,
               COALESCE(t.category_effective, ?) AS now, v.category AS suggestion, v.confidence, v.reason
          FROM ai_suggestions v
          JOIN bank_transactions_typed t ON t.id = v.transaction_id
          JOIN categories c ON c.name = v.category AND c.type != 'INTERNAL'
         WHERE t.category_manual IS NULL
           AND v.confidence > 0 AND v.confidence < ? AND v.category != ?
           AND COALESCE(t.category_source, 'rule') != 'ai'
           AND COALESCE(t.category_effective, ?) IN (?, ?, ?)
        """,
        (UNKNOWN, categorization.AI_THRESHOLD, UNKNOWN, UNKNOWN, UNKNOWN, *FRIENDS),
    ):
        r = dict(r)
        # Also what was stored before the direction check: received money is never
        # "paid to friends", an expense never income.
        r["suggestion"] = ai_labelling.fit_direction(r["suggestion"], r["amount"], types)
        if r["id"] in already or not r["suggestion"] or r["suggestion"] == r["now"]:
            continue
        # For a friend only when the description says what for; see ai_labelling.
        if r["now"] in FRIENDS and not categorization.has_target_text(r["name"], r["description"]):
            continue
        groups[(r["name"], r["now"], r["suggestion"])].append(r)
    return [_item("doubt", f"{name}|{now}|{suggestion}", name, rs, now=now, suggestion=suggestion,
                  confidence=max(r["confidence"] for r in rs),
                  reason=next((r["reason"] for r in rs if r["reason"]), None),
                  rule_possible=_name_is_counterparty(name))
            for (name, now, suggestion), rs in groups.items()]


def _unknown(conn: sqlite3.Connection, already: set[int]) -> list[dict]:
    groups: dict = defaultdict(list)
    for r in conn.execute(
        """
        SELECT id, date, amount, name, description FROM bank_transactions_typed
         WHERE category_manual IS NULL
           AND COALESCE(category_effective, ?) = ?
           AND TRIM(COALESCE(name, '')) != ''
        """,
        (UNKNOWN, UNKNOWN),
    ):
        if r["id"] not in already:
            groups[r["name"]].append(dict(r))
    return [_item("unknown", name, name, rs, now=UNKNOWN,
                  processor=bool(categorization._PROCESSOR.search(name.upper())),
                  rule_possible=_name_is_counterparty(name))
            for name, rs in groups.items()]


def _disagree(conn: sqlite3.Connection) -> list[dict]:
    return [{
        "key": f"oneens:{a['name']}|{a['now']}|{a['suggestion']}", "kind": "disagree", "title": a["name"],
        "ids": a["ids"], "count": a["count"], "total": a["total"], "last": a["last"],
        "description": a["description"], "remark": readable(a["description"], a["name"]),
        "now": a["now"], "suggestion": a["suggestion"],
        "confidence": a["confidence"], "reason": a.get("reason"), "rule_possible": a["rule_possible"],
    } for a in ai_labelling.deviations(conn, limit=1000)]


def _rules(conn: sqlite3.Connection) -> list[dict]:
    off = []
    for v in ai_labelling.rule_suggestions(conn):
        reason = f"raakt {v['touches']}"
        if v["changes"]:
            reason += tr(", {0} get another category", v['changes'])
        if v["clashes"]:
            reason += tr(", {0} different by hand (stays)", v['clashes'])
        off.append({
            "key": f"regel:{v['id']}", "kind": "rule", "title": v["pattern"], "rule_id": v["id"],
            "ids": [], "count": v["touches"], "total": 0.0, "last": None,
            "description": " · ".join(v["examples"]), "remark": " · ".join(v["examples"]),
            "now": None, "suggestion": v["category"],
            "confidence": None, "reason": reason, "rule_possible": False,
        })
    return off


def _by_ai(conn: sqlite3.Connection) -> list[dict]:
    groups: dict = defaultdict(list)
    for r in ai_labelling.by_ai(conn, limit=2000):
        groups[(r["name"], r["category"])].append(r)
    return [_item("ai", f"{name}|{category}", name, rs, now=category, suggestion=category,
                  confidence=min(r["confidence"] for r in rs),
                  reason=next((r.get("reason") for r in rs if r.get("reason")), None),
                  rule_possible=_name_is_counterparty(name))
            for (name, category), rs in groups.items()]


def _restore(conn: sqlite3.Connection) -> None:
    """Suggestions that are certain enough but not applied yet — for instance after
    turning Claude on again — are applied after all. Otherwise they sat at 90%
    under "Claude is in doubt".
    """
    applicable = categorization.ai_suggestions(conn)
    if not applicable:
        return
    ids = list(applicable)
    places = ",".join("?" * len(ids))
    for r in conn.execute(
        f"""
        SELECT name, description, category_auto FROM bank_transactions
         WHERE category_manual IS NULL AND COALESCE(category_source, 'rule') != 'ai'
           AND id IN ({places})
        """, ids,
    ):
        open_ = r["category_auto"] in (None, UNKNOWN)
        if open_ or (r["category_auto"] in FRIENDS and categorization.has_target_text(r["name"], r["description"])):
            categorization.relabel(conn)
            return


def queue(conn: sqlite3.Connection) -> dict:
    """The whole queue, largest amounts first; rule suggestions and what Claude
    already labelled at the end.
    """
    categorization.seed(conn)
    claude = ai_labelling.available() and ai_labelling.on(conn)
    if claude:
        _restore(conn)

    own = _own(conn)
    already = {i for item in own for i in item["ids"]}
    doubt = _doubt(conn, already) if claude else []
    already |= {i for item in doubt for i in item["ids"]}
    decisions = own + doubt + (_disagree(conn) if claude else []) + _unknown(conn, already)
    items = (sorted(decisions, key=lambda i: -abs(i["total"]))
             + (_rules(conn) if claude else [])
             + (sorted(_by_ai(conn), key=lambda i: -abs(i["total"])) if claude else []))

    total, open_ = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(COALESCE(category_effective, ?) = ?), 0) FROM bank_transactions_typed",
        (UNKNOWN, UNKNOWN),
    ).fetchone()
    most_recent = conn.execute(
        "SELECT MAX(t) FROM (SELECT MAX(created_at) AS t FROM ai_suggestions "
        "UNION ALL SELECT MAX(created_at) FROM ai_checks UNION ALL SELECT MAX(created_at) FROM rule_suggestions)"
    ).fetchone()[0]
    return {
        "items": items,
        "tellers": {s: sum(1 for i in items if i["kind"] == s) for s in KINDS},
        "waiting": sum(1 for i in items if i["kind"] not in OPTIONAL),
        "coverage": round((total - open_) / total * 100, 1) if total else 0.0,
        "unknown": open_,
        "most_recent_checked": most_recent,
        "claude": claude,
    }


def _rule_on_name(conn: sqlite3.Connection, ids: list[int], category: str) -> bool:
    """Makes a rule on the name of these transactions, if possible: one name, and
    that name is the counterparty.
    """
    if not ids:
        return False
    places = ",".join("?" * len(ids))
    names = {r["name"] for r in conn.execute(f"SELECT name FROM bank_transactions WHERE id IN ({places})", ids)}
    if len(names) != 1:
        return False
    name = names.pop()
    if not _name_is_counterparty(name):
        return False
    categorization.make_rule(conn, priority=ai_labelling.RULE_PRIORITY, field="N",
                             pattern=re.escape(name.strip().upper()), direction="", category=category)
    return True


def decision(conn: sqlite3.Connection, decisions: list[dict]) -> dict:
    """Processes a series of decisions from the queue, then relabels once.

    Each decision: {kind, choice (agreed | reject | otherwise), ids, category?,
    rule?, rule_id?}. Agreed and otherwise set the category — as a rule on the
    name if `rule` is on and that is possible, otherwise as your own label.
    Reject means per kind: Claude's label comes off (doubt, ai), the original is
    right (disagree), it stays as it is (own: your choice for the current
    category), or later (unknown: nothing).
    """
    if not decisions:
        raise ValueError(tr("Nothing was chosen."))
    categorization.seed(conn)
    valid = {c["name"] for c in categorization.load_categories(conn)}
    manual: dict[str, list[int]] = defaultdict(list)
    new_rule = False
    for b in decisions:
        kind, choice = b.get("kind"), b.get("choice")
        if kind not in KINDS or choice not in CHOICES:
            raise ValueError(tr("Unknown decision."))
        ids = sorted({int(i) for i in b.get("ids") or []})
        category = b.get("category")
        if category is not None and category not in valid:
            raise ValueError(tr("'{0}' is not an existing category.", category))

        if kind == "rule":
            ai_labelling.rule_suggestion_decision(conn, ids=[int(b["rule_id"])], accept=choice == "agreed")
            continue
        if kind == "disagree":
            ai_labelling.decision(conn, ids=ids, category=category, rule=bool(b.get("rule")),
                               choice={"agreed": "suggestion", "reject": "original", "otherwise": "otherwise"}[choice])
            continue
        if choice == "reject":
            if kind in ("doubt", "ai"):
                ai_labelling.reject(conn, ids)
            elif kind == "own" and category:
                manual[category] += ids
            continue
        if not category:
            raise ValueError(tr("Choose a category."))
        if b.get("rule") and _rule_on_name(conn, ids, category):
            new_rule = True
        else:
            manual[category] += ids

    for category, ids in manual.items():
        bank_transactions.set_category_manual_for(conn, ids, category)
    if manual or new_rule:
        categorization.relabel(conn, everything=new_rule)
    return {"processed": len(decisions)}
