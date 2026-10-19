"""Finding foods: one search over the global table (NEVO, cached Open Food Facts) and the user's own foods.

A food is addressed by a reference that says where it lives, so a meal item can point at any source:
`nevo:1234` (NEVO-code), `off:8710000000000` (EAN), `usda:123`, `user:12` (user_foods.id).

The global table is small (NEVO has about 2,300 foods), so search runs in Python over an in-process index instead of a
database feature: the same on Postgres and SQLite, accent- and case-blind. Every query word must match a word of the
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
from dataclasses import dataclass

from sqlalchemy import select

from tools import db

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
        self.by_engine: dict[int, tuple[float, list[Indexed]]] = {}

    def entries(self, engine) -> list[Indexed]:
        key = id(engine)
        with self.lock:
            hit = self.by_engine.get(key)
            if hit and time.monotonic() - hit[0] < RELOAD_S:
                return hit[1]
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(select(db.foods)).mappings()]
        entries = [_entry(_public(r, r["source"], r["source_code"]), r.get("synonyms")) for r in rows]
        with self.lock:
            self.by_engine[key] = (time.monotonic(), entries)
        return entries

    def clear(self):
        with self.lock:
            self.by_engine.clear()


_index = _Index()


def invalidate() -> None:
    _index.clear()


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
        hits = [i for i, w in enumerate(entry.words) if w.startswith(t)]
        inside = 0.5
        if not hits and len(t) >= INSIDE_MIN:
            hits = [i for i, w in enumerate(entry.words) if t in w]
        else:
            inside = 1.0
        if not hits:
            return None
        first = hits[0]
        exact = entry.words[first] == t
        score += inside * ((3.0 if first < entry.name_words else 1.0) + (1.0 if exact else 0.0) + (0.5 if first == 0 else 0.0))
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
