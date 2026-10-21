"""Finding foods: one search over the global table (NEVO, cached Open Food Facts) and the user's own foods.

A food is addressed by a reference that says where it lives, so a meal item can point at any source:
`nevo:1234` (NEVO-code), `off:8710000000000` (EAN), `usda:123`, `user:12` (user_foods.id).

The global table is small (NEVO has about 2,300 foods), so search runs in Python over an in-process index instead of a
database feature, accent- and case-blind. Every query word must match a word of the
food's name, synonyms or English name: as its start ("volk brood"), or from four letters on inside a Dutch compound
("brood" in "volkorenbrood"), which counts for less. NEVO writes compounds as "Vlokken haver-" and "Olie olijf-"; the
index adds "havervlokken" and "olijfolie" for them. A synonym that is the whole query counts like the name ("havermout"
finds "Vlokken haver-", whose synonym it is). The index reloads after an import here and at most every RELOAD_S
elsewhere (another worker process).
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import weakref
from dataclasses import dataclass

from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update

from tools import db
from tools.nutrition.nutrients import KEYS, with_salt

RELOAD_S = 600
SOURCES = ("nevo", "off", "usda", "user")


INSIDE_MIN = 4  # a query word this long also matches inside a compound word
COMPOUND = re.compile(r"(\w+)\s+(\w+)-(?=\s|$)")  # NEVO's "Vlokken haver-": havervlokken


@dataclass(frozen=True)
class Indexed:
    ref: str
    words: tuple[str, ...]  # of the name, then of synonyms and the English name
    name_words: int  # how many of `words` are the Dutch name's
    phrases: tuple[str, ...]  # the name and each synonym, normalised, for a whole-query match
    food: dict


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def ref_of(source: str, code) -> str:
    return f"{source}:{code}"


def split_ref(ref: str) -> tuple[str, str]:
    source, _, code = (ref or "").partition(":")
    if source not in SOURCES or not code:
        raise ValueError(f"not a food reference: {ref!r}")
    return source, code


def _public(row: dict, source: str, code) -> dict:
    return {
        "ref": ref_of(source, code),
        "source": source,
        "name": row["name_nl"],
        "name_en": row.get("name_en"),
        "brand": row.get("brand"),
        "group": row.get("food_group"),
        "unit": row.get("unit") or "g",
        "per_100": row["per_100"],
        "default_portion_g": row.get("default_portion_g"),
        "version": row.get("source_version"),
    }


def _compounds(text: str) -> list[str]:
    return [norm(m[2] + m[1]) for m in COMPOUND.finditer(text or "")]


def _entry(food: dict, synonyms: str | None) -> Indexed:
    name = norm(food["name"]).split() + _compounds(food["name"])
    rest = norm(" ".join(x for x in (synonyms, food.get("name_en"), food.get("brand")) if x)).split()
    # NEVO separates synonyms with "/" but also uses it inside one ("groente/kaas/ei"): a synonym starts with a capital
    phrases = (norm(food["name"]), *(norm(x) for x in (synonyms or "").split("/") if x.strip()[:1].isupper()))
    return Indexed(food["ref"], tuple(name + rest), len(name), phrases, food)


class _Index:
    def __init__(self):
        self.lock = threading.Lock()
        # by the engine itself, held weakly: an id() could be reused by a later engine with other foods
        self.by_engine: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def entries(self, engine) -> list[Indexed]:
        with self.lock:
            hit = self.by_engine.get(engine)
            if hit and time.monotonic() - hit[0] < RELOAD_S:
                return hit[1]
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(select(db.foods)).mappings()]
        entries = [_entry(_public(r, r["source"], r["source_code"]), r.get("synonyms")) for r in rows]
        with self.lock:
            self.by_engine[engine] = (time.monotonic(), entries)
        return entries

    def add(self, engine, food: dict) -> None:
        with self.lock:
            hit = self.by_engine.get(engine)
            if hit is not None and not any(e.ref == food["ref"] for e in hit[1]):
                self.by_engine[engine] = (hit[0], [*hit[1], _entry(food, None)])

    def clear(self):
        with self.lock:
            self.by_engine.clear()


_index = _Index()


def invalidate() -> None:
    _index.clear()


def add(engine, food: dict) -> None:
    """One new global food (an Open Food Facts product) into the loaded index."""
    _index.add(engine, food)


def user_foods(s: db.Scope) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(select(db.user_foods).where(db.user_foods.c.user_id == s.user_id).order_by(db.user_foods.c.id)).mappings().all()
    return [_public(dict(r), "user", r["id"]) for r in rows]


def get(s: db.Scope, ref: str) -> dict | None:
    """One food by reference; a user food only when it is this user's."""
    try:
        source, code = split_ref(ref)
    except ValueError:
        return None
    if source == "user":
        if not code.isdigit():
            return None
        with s.engine.connect() as conn:
            row = conn.execute(select(db.user_foods).where(db.user_foods.c.user_id == s.user_id, db.user_foods.c.id == int(code))).mappings().first()
        return _public(dict(row), "user", row["id"]) if row else None
    with s.engine.connect() as conn:
        row = conn.execute(select(db.foods).where(db.foods.c.source == source, db.foods.c.source_code == code)).mappings().first()
    return _public(dict(row), source, code) if row else None


def _score(entry: Indexed, terms: list[str], phrase: str) -> float | None:
    """None when a query word matches no word of the food; higher is better."""
    score = 0.0
    for t in terms:
        hits, weight = [i for i, w in enumerate(entry.words) if w.startswith(t)], 1.0
        if not hits and len(t) >= INSIDE_MIN:
            hits, weight = [i for i, w in enumerate(entry.words) if t in w], 0.5  # inside a compound counts for less
        if not hits:
            return None
        first = hits[0]
        exact = entry.words[first] == t
        score += weight * ((3.0 if first < entry.name_words else 1.0) + (1.0 if exact else 0.0) + (0.5 if first == 0 else 0.0))
    name, synonyms = entry.phrases[0], entry.phrases[1:]
    if name == phrase:
        score += 5
    elif any(x == phrase for x in synonyms):
        score += 4.5
    elif name.startswith(phrase):
        score += 2
    elif any(x.startswith(phrase) for x in synonyms):
        score += 1
    return score - 0.05 * entry.name_words  # "Banaan" before "Banaan gedroogd met suiker"


def search(s: db.Scope, query: str, limit: int = 20, history: dict[str, int] | None = None) -> list[dict]:
    """Foods matching `query`, best first: the user's own foods and those they ate before (`history`: ref -> times)
    rank higher at an equal text match."""
    phrase = norm(query)
    terms = phrase.split()
    if not terms:
        return []
    history = history or {}
    mine = [_entry(f, None) for f in user_foods(s)]
    scored = []
    for e in (*mine, *_index.entries(s.engine)):
        sc = _score(e, terms, phrase)
        if sc is None:
            continue
        sc += min(history.get(e.ref, 0), 10) * 0.4 + (1.0 if e.ref.startswith("user:") else 0.0)
        scored.append((sc, e))
    scored.sort(key=lambda x: (-x[0], x[1].food["name"]))
    return [{**e.food, "uses": history.get(e.ref, 0)} for _, e in scored[:limit]]


# --- your own foods (Mijn voeding) ---------------------------------------------------------------------------

MAX_USER_FOODS = 500
LIMITS = {"energy_kcal": 900.0}  # per 100: no food holds more than pure fat; everything else at most 100 g (or its mg/µg)


class FoodError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _per_100(values: dict) -> dict:
    out = {}
    for k in KEYS:
        v = values.get(k)
        if v is None:
            out[k] = None
            continue
        v = float(v)
        top = LIMITS.get(k, 100.0 if k.endswith("_g") else 100000.0)
        if not 0 <= v <= top:
            raise FoodError("food_value_range", field=k, max=top)
        out[k] = round(v, 3)
    if out.get("energy_kcal") is None:
        raise FoodError("food_energy_required")
    return with_salt(out)


def create_user_food(s: db.Scope, *, name: str | None = None, brand: str | None = None, unit: str | None = None,
                     default_portion_g: float | None = None, per_100: dict | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise FoodError("food_name_required")
    if (unit or "g") not in ("g", "ml"):
        raise FoodError("invalid_choice", options="g, ml")
    if len(user_foods(s)) >= MAX_USER_FOODS:
        raise FoodError("too_many_foods", max=MAX_USER_FOODS)
    with s.engine.begin() as conn:
        fid = conn.execute(insert(db.user_foods).values(user_id=s.user_id, name_nl=name[:200], brand=(brand or "").strip()[:100] or None,
                                                        unit=unit or "g", per_100=_per_100(per_100 or {}), default_portion_g=default_portion_g,
                                                        created_at=datetime.now(timezone.utc))).inserted_primary_key[0]
    return get(s, ref_of("user", fid))


def change_user_food(s: db.Scope, fid: int, **fields) -> dict | None:
    if get(s, ref_of("user", fid)) is None:
        return None
    values: dict = {}
    if "name" in fields:
        if not (fields["name"] or "").strip():
            raise FoodError("food_name_required")
        values["name_nl"] = fields["name"].strip()[:200]
    if "brand" in fields:
        values["brand"] = (fields["brand"] or "").strip()[:100] or None
    if "unit" in fields:
        if fields["unit"] not in ("g", "ml"):
            raise FoodError("invalid_choice", options="g, ml")
        values["unit"] = fields["unit"]
    if "default_portion_g" in fields:
        values["default_portion_g"] = fields["default_portion_g"]
    if fields.get("per_100") is not None:
        values["per_100"] = _per_100(fields["per_100"])
    if values:
        with s.engine.begin() as conn:
            conn.execute(update(db.user_foods).where(db.user_foods.c.user_id == s.user_id, db.user_foods.c.id == fid).values(**values))
    return get(s, ref_of("user", fid))


def delete_user_food(s: db.Scope, fid: int) -> bool:
    """The product, its usual portion and its place in favourites (a favourite left empty goes too). Logged meals keep
    their snapshot."""
    ref = ref_of("user", fid)
    with s.engine.begin() as conn:
        if not conn.execute(delete(db.user_foods).where(db.user_foods.c.user_id == s.user_id, db.user_foods.c.id == fid)).rowcount:
            return False
        conn.execute(delete(db.portion_memory).where(db.portion_memory.c.user_id == s.user_id, db.portion_memory.c.food_ref == ref))
        for tid, items in conn.execute(select(db.meal_templates.c.id, db.meal_templates.c["items"]).where(db.meal_templates.c.user_id == s.user_id)).all():
            kept = [it for it in items or [] if it.get("food_ref") != ref]
            if len(kept) == len(items or []):
                continue
            q = db.meal_templates.c
            if kept:
                conn.execute(update(db.meal_templates).where(q.user_id == s.user_id, q.id == tid).values(items=kept))
            else:
                conn.execute(delete(db.meal_templates).where(q.user_id == s.user_id, q.id == tid))
    return True

