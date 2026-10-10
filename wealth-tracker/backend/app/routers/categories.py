"""
Categories, labelling rules and relabelling.

The loop the user makes here: create a category, add a rule to it, relabel,
and the history moves along. A correction by hand stays in place —
`category_manual` is never written by a rule round here, only by the user
through `PUT /api/bank-transactions/{id}/category`.

The engine lives in domain/money/categorization.py; this only routes.

`seed()` sits at the start of every endpoint that needs the taxonomy: a new
user does not have to type in thirty-nine categories first, and seeding does
nothing once something is there — so a rule you threw away stays away.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from domain import db
from domain.money import ai_labelling
from domain.money import bank_transactions
from domain.money import categorization
from app.deps import CurrentUser, get_current_user, get_db, require_money
from domain.i18n import tr

router = APIRouter(tags=["categories"], dependencies=[Depends(require_money)])


@router.get("/api/categories")
def items(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    return {
        "categories": categorization.load_categories(conn),
        "rules": categorization.load_rules(conn, only_active=False),
    }


@router.post("/api/categories", status_code=status.HTTP_201_CREATED)
def make_category(
    group_name: str = Body(...),
    name: str = Body(...),
    type: str = Body(...),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    try:
        category_id = categorization.make_category(conn, group_name=group_name, name=name, type=type)
    except db.IntegrityError as e:
        # The only UNIQUE is the name.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            tr("There is already a category called '{0}'.", name)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    made = next(c for c in categorization.load_categories(conn) if c["id"] == category_id)
    return {"category": made}


@router.put("/api/categories/groups")
def rename_group(
    old: str = Body(..., description="The current name of the main category"),
    new_name: str = Body(..., description="The new name; if it already exists, they are merged"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    try:
        categorization.rename_group(conn, old, new_name)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This main category does not exist.")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"categories": categorization.load_categories(conn)}


@router.put("/api/categories/{category_id}/name")
def rename_category(
    category_id: int,
    name: str = Body(..., embed=True, description="The new name"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Renames a category; transactions, rules and suggestions move along."""
    categorization.seed(conn)
    try:
        categorization.rename_category(conn, category_id, name)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This category does not exist.")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"categories": categorization.load_categories(conn)}


@router.put("/api/categories/{category_id}/type")
def set_category_type(
    category_id: int,
    type: str = Body(..., embed=True, description="EXPENSE, INCOME or INTERNAL"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    try:
        categorization.set_type(conn, category_id, type)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This category does not exist.")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"categories": categorization.load_categories(conn)}


@router.put("/api/categories/{category_id}/group")
def move_category(
    category_id: int,
    group_name: str = Body(..., embed=True, description="The main category it moves to (may be new)"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    try:
        categorization.move_category(conn, category_id, group_name)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This category does not exist.")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"categories": categorization.load_categories(conn)}


@router.delete("/api/categories/{category_id}")
def delete_category(
    category_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    if not any(c["id"] == category_id for c in categorization.load_categories(conn)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This category does not exist."))
    categorization.delete_category(conn, category_id)
    return {"ok": True}


@router.post("/api/categories/rules", status_code=status.HTTP_201_CREATED)
def make_rule(
    priority: int = Body(...),
    field: str = Body(...),
    pattern: str = Body(...),
    category: str = Body(...),
    direction: str = Body(""),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    try:
        rule_id = categorization.make_rule(
            conn, priority=priority, field=field, pattern=pattern,
            direction=direction, category=category,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    rule = next(r for r in categorization.load_rules(conn, only_active=False)
                 if r["id"] == rule_id)
    return {"rule": rule}


@router.delete("/api/categories/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    if not any(r["id"] == rule_id for r in categorization.load_rules(conn, only_active=False)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This rule does not exist."))
    categorization.delete_rule(conn, rule_id)
    return {"ok": True}


@router.get("/api/categories/unknown")
def unknown(
    limit: int = Query(30, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Transactions without a category, grouped per counterparty — the place where
    one new rule gives the most coverage.
    """
    categorization.seed(conn)
    return {
        "counterparties": categorization.unknown_per_counterparty(conn, limit=limit),
        # All transactions without a category, also beyond the limit: the counter.
        "count": categorization.unknown_count(conn),
    }


@router.get("/api/categories/suspicious")
def suspicious(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Transactions the rules probably labelled wrong — usually money between your
    own accounts that counts as income or spending.
    """
    categorization.seed(conn)
    return {"transactions": categorization.suspicious(conn)}


@router.get("/api/categories/ai")
def ai_status(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Whether Claude can and may help, how much is still open, and what it
    labelled that you have not reviewed yet.
    """
    categorization.seed(conn)
    return {**ai_labelling.status(conn), "transactions": ai_labelling.by_ai(conn),
            "deviations": ai_labelling.deviations(conn),
            "rule_suggestions": ai_labelling.rule_suggestions(conn)}


@router.post("/api/categories/ai/rule-suggestions")
def ai_rule_suggestions(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Claude proposes rules for counterparties that occur more often; the open
    suggestions are then in GET /api/categories/ai.
    """
    try:
        return ai_labelling.make_rule_suggestions(conn)
    except ai_labelling.AiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/rule-suggestions/decision")
def ai_rule_suggestion_decision(
    ids: list[int] = Body(..., description="De voorstellen"),
    accept: bool = Body(..., description="Accepting makes the rules; rejecting remembers that"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        return ai_labelling.rule_suggestion_decision(conn, ids=ids, accept=accept)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/thorough")
def ai_thorough(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """A thorough round with a stronger model and more context, for what has no category yet."""
    try:
        return ai_labelling.thorough(conn)
    except ai_labelling.AiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/retry")
def ai_retry(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Put what has no category yet to Claude again (not what you rejected)."""
    try:
        return ai_labelling.ask_again(conn)
    except ai_labelling.AiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/reject")
def ai_reject(
    ids: list[int] = Body(..., embed=True, description="Transactions whose Claude label is wrong"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """"Not right": take Claude's label off, and do not suggest it again."""
    try:
        return ai_labelling.reject(conn, ids)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/verify")
def ai_verify(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """A "Check everything" round: Claude looks at what the rules already labelled.
    Nothing changes; the deviations are then in GET /api/categories/ai.
    """
    try:
        return ai_labelling.verify(conn)
    except ai_labelling.AiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/check/decision")
def ai_decision(
    ids: list[int] = Body(..., description="The transactions of one deviation"),
    choice: str = Body(..., description="voorstel, origineel of anders"),
    category: str | None = Body(None, description="With suggestion or otherwise: the category"),
    rule: bool = Body(False, description="As a rule on the name, also for what is still to come"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        return ai_labelling.decision(conn, ids=ids, choice=choice, category=category, rule=rule)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/ai/analyse")
def ai_analyse(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Let Claude do a round of suggestions for what is still open."""
    try:
        return ai_labelling.analyse(conn)
    except ai_labelling.AiError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/api/categories/relabel")
def relabel(
    everything: bool = Query(False, description="Also rules that already have an automatic category"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Relabels. Manual categories stay in place either way.

    Without `everything` only what has no automatic category yet; with it, the
    rest too — that is what you want after changing a rule.
    """
    categorization.seed(conn)
    return categorization.relabel(conn, everything=everything)


@router.put("/api/bank-transactions/{transaction_id}/category")
def set_category(
    transaction_id: int,
    category: str | None = Body(None, embed=True),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Your verdict on one transaction. `null` clears it, after which the automatic
    category takes over again.
    """
    rows = bank_transactions.load(conn)
    if not any(r["id"] == transaction_id for r in rows):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This transaction does not exist."))

    if category is not None:
        categorization.seed(conn)
        known = {c["name"] for c in categorization.load_categories(conn)}
        if category not in known:
            # A typo here makes a transaction impossible to find in any overview.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                tr("'{0}' is not an existing category.", category),
            )

    bank_transactions.set_category_manual(conn, transaction_id, category)
    return {"transaction": next(r for r in bank_transactions.load(conn) if r["id"] == transaction_id)}
