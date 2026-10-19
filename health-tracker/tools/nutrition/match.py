"""From Claude's answer to a draft meal: each recognised item matched to a food in the food table, with the top
alternatives for the "swap" list, and the user's usual portion where Claude was unsure.

Matching searches the food table (tools/nutrition/foods.py) with Claude's search terms, then its Dutch label; a food
found by an earlier term, higher up, eaten before by this user (search already ranks those first) or of the group that
fits the kind of item (a drink, a fat, a sauce) ranks higher. Nothing is saved here: the draft goes to the review
screen and the meal is stored only when the user confirms it (tools/nutrition/meals.py create).
"""

from __future__ import annotations

from tools import db
from tools.nutrition import foods, meals

ALTERNATIVES = 5
MEMORY_BELOW = 0.7  # Claude's confidence under which the user's usual portion is the better first guess
TERM_WEIGHT = (1.0, 0.8, 0.65, 0.5, 0.4)
# NEVO's food groups (English names) that fit a kind of item; Open Food Facts and own foods have none.
KIND_GROUPS = {
    "drink": ("beverages",),
    "fat": ("fats and oils",),
    "sauce": ("sauces", "dressings"),
}


def _fits(food: dict, kind: str) -> bool:
    if kind == "drink" and food.get("unit") == "ml":
        return True
    group = (food.get("group") or "").lower()
    return any(g in group for g in KIND_GROUPS.get(kind, ()))


def candidates(s: db.Scope, terms: list[str], kind: str, history: dict[str, int]) -> list[dict]:
    """The best foods for one recognised item, best first."""
    score: dict[str, float] = {}
    found: dict[str, dict] = {}
    for t_index, term in enumerate(dict.fromkeys(t for t in terms if t.strip())):
        weight = TERM_WEIGHT[min(t_index, len(TERM_WEIGHT) - 1)]
        for rank, food in enumerate(foods.search(s, term, 8, history)):
            found.setdefault(food["ref"], food)
            score[food["ref"]] = score.get(food["ref"], 0.0) + weight / (rank + 1)
    for ref, food in found.items():
        if _fits(food, kind):
            score[ref] += 0.3
    return [found[ref] for ref in sorted(score, key=lambda r: (-score[r], found[r]["name"]))][:ALTERNATIVES]


def draft(s: db.Scope, answer: dict) -> dict:
    """The review screen's draft for a tidied answer (tools/nutrition/recognize.py tidy)."""
    history = meals.history(s)
    items, refs = [], []
    for it in answer["items"]:
        options = candidates(s, [*it["search_terms"], it["label_nl"]], it["kind"], history)
        items.append({**it, "alternatives": options, "food": options[0] if options else None})
        refs += [o["ref"] for o in options]
    extras = []
    for ex in answer["hidden_extras"]:
        options = candidates(s, [*ex["search_terms"], ex["label_nl"]], "food", history)
        extras.append({**ex, "food": options[0] if options else None})
        refs += [o["ref"] for o in options[:1]]
    usual = meals.portions(s, refs)
    for it in items:
        food = it["food"]
        mine = usual.get(food["ref"]) if food else None
        for option in it["alternatives"]:
            option["portion_g"] = (usual.get(option["ref"]) or {}).get("grams") or option.get("default_portion_g")
        it.update({"grams_ai": it["grams"], "grams_source": "ai"})
        if mine and it["confidence"] < MEMORY_BELOW:
            it.update({"grams": mine["grams"], "grams_source": "memory"})  # the AI estimate stays as the range
    return {"items": items, "hidden_extras": extras, "moment_guess": answer.get("moment_guess"),
            "reference_object": answer.get("reference_object")}
