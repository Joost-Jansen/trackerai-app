"""log_meal for an agent (api/mcp.py; here, not in tools/, because it reads tables with api/plans.py): meals from a table of foods and grams, matched against the food table.

    | Voedingsmiddel | Gram | Moment | Tijd | Dag |
    | havermout      | 60   | ontbijt | 07:30 |    |
    | nevo:1234      | 120  | ontbijt | 07:30 |    |

Markdown or CSV with a header row, Dutch or English headers. A food is a reference (nevo:1234, off:<ean>, user:12)
or a name, which takes the best match from search (the user's history counts, as on the site). Rows with the same day,
moment and time are one meal. Moment and day default to the clock's moment and today; nothing is saved with preview.
"""

from __future__ import annotations

import re
from datetime import date

from api.plans import _rows
from tools import db
from tools.nutrition import foods, meals

HEADERS = {
    "food": ("voedingsmiddel", "food", "product", "wat", "item", "naam", "name"),
    "grams": ("gram", "grams", "g", "gr", "hoeveelheid", "amount", "ml"),
    "moment": ("moment", "maaltijd", "meal"),
    "time": ("tijd", "time", "om"),
    "day": ("dag", "datum", "day", "date"),
}
MOMENT_WORDS = {
    "ontbijt": "breakfast", "breakfast": "breakfast", "lunch": "lunch", "diner": "dinner", "avondeten": "dinner", "dinner": "dinner",
    "tussendoor": "snack", "snack": "snack", "training": "training", "tijdens training": "training", "drinken": "drinks", "drinks": "drinks",
}


def _column(header: list[str], key: str) -> int | None:
    names = [re.sub(r"[^a-z ]", "", h.lower()).strip() for h in header]
    return next((i for i, h in enumerate(names) if h in HEADERS[key]), None)


def parse(text: str, today: date, now_hhmm: str) -> tuple[list[dict], list[str]]:
    """Rows as {food, grams, moment, eaten_at, day}, and warnings for rows that were skipped."""
    rows = _rows(text or "")
    if len(rows) < 2:
        return [], ["geen tabel met een kopregel en minstens één regel"]
    header, body = rows[0], rows[1:]
    col = {k: _column(header, k) for k in HEADERS}
    if col["food"] is None or col["grams"] is None:
        return [], ["kolommen Voedingsmiddel en Gram zijn verplicht"]
    out, warnings = [], []
    for n, row in enumerate(body, 2):
        cell = lambda k: row[col[k]].strip() if col[k] is not None and col[k] < len(row) else ""  # noqa: E731
        food = cell("food")
        try:
            grams = float(cell("grams").replace(",", ".").rstrip("gml ").strip())
        except ValueError:
            warnings.append(f"regel {n}: geen hoeveelheid in gram")
            continue
        if not food:
            continue
        time = cell("time") or now_hhmm
        if re.fullmatch(r"\d{1,2}[:.]\d{2}", time):
            h, m = re.split(r"[:.]", time)
            time = f"{int(h):02d}:{m}"
        else:
            warnings.append(f"regel {n}: tijd {time!r} niet als 07:30")
            continue
        moment = MOMENT_WORDS.get(cell("moment").lower(), None) if cell("moment") else meals_moment(time)
        if moment is None:
            warnings.append(f"regel {n}: onbekend moment {cell('moment')!r}")
            continue
        day = cell("day") or today.isoformat()
        out.append({"food": food, "grams": grams, "moment": moment, "eaten_at": time, "day": day, "row": n})
    return out, warnings


def meals_moment(hhmm: str) -> str:
    """The moment the clock suggests (as the site does, web/lib/nutrition.ts momentAt)."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    t = h * 60 + m
    if 5 * 60 <= t < 10 * 60 + 30:
        return "breakfast"
    if 11 * 60 + 30 <= t < 14 * 60 + 30:
        return "lunch"
    if 17 * 60 <= t < 21 * 60:
        return "dinner"
    return "snack"


def resolve(s: db.Scope, rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Each row with its food (or a warning when nothing matches)."""
    history = meals.history(s)
    out, warnings = [], []
    for r in rows:
        food = foods.get(s, r["food"]) if ":" in r["food"] else None
        if food is None:
            found = foods.search(s, r["food"], 1, history)
            food = found[0] if found else None
        if food is None:
            warnings.append(f"regel {r['row']}: {r['food']!r} niet gevonden; gebruik search_foods")
            continue
        out.append({**r, "food": food})
    return out, warnings


def group(rows: list[dict]) -> list[dict]:
    """Rows with the same day, moment and time as one meal, in time order."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r["day"], r["eaten_at"], r["moment"]), []).append(r)
    return [{"day": d, "eaten_at": t, "moment": m, "items": items} for (d, t, m), items in sorted(by.items())]
