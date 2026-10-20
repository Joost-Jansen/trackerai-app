"""USDA FoodData Central as a fallback for foods NEVO lacks (public domain, CC0; credited as the source).

Only with FDC_API_KEY on the server (https://fdc.nal.usda.gov/api-key-signup). A search asks it only when NEVO, your
own foods and the cache together found fewer than FEW, from MIN_QUERY letters; only the search words go to USDA. A
food that comes back is cached in the global `foods` table (source `usda`, the fdcId as code), so it is searched like
any other afterwards. A failed lookup is never an error for the user: search shows what it has.

Nutrient numbers (FDC nutrientId, checked against a live response): energy 1008 (kcal), protein 1003, fat 1004,
carbohydrate by difference 1005 (includes fibre: available carbohydrate is 1005 - 1079, as NEVO counts it), fibre 1079,
sugars 2000, saturated 1258, mono- 1292 and polyunsaturated 1293, trans 1257, alcohol 1018, sodium 1093, iron 1089,
calcium 1087, magnesium 1090, potassium 1092, zinc 1095, vitamin C 1162, vitamin D 1114 (µg), B12 1178, folate DFE 1190.
"""

from __future__ import annotations

import os
import threading
import time

import requests
from sqlalchemy import insert, select

from tools import db
from tools.nutrition import foods
from tools.nutrition.nutrients import KEYS, with_salt

URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
FEW = 3
MIN_QUERY = 4  # a word, not the first letters of one
TIMEOUT_S = 4
PAGE = 8
CACHE_S = 3600
IDS = {
    "energy_kcal": 1008, "protein_g": 1003, "fat_g": 1004, "fiber_g": 1079, "sugars_g": 2000, "sat_fat_g": 1258, "mufa_g": 1292,
    "pufa_g": 1293, "trans_fat_g": 1257, "alcohol_g": 1018, "sodium_mg": 1093, "iron_mg": 1089, "calcium_mg": 1087,
    "magnesium_mg": 1090, "potassium_mg": 1092, "zinc_mg": 1095, "vit_c_mg": 1162, "vit_d_ug": 1114, "vit_b12_ug": 1178, "folate_ug": 1190,
}
CARBS_BY_DIFFERENCE = 1005

_lock = threading.Lock()
_asked: dict[str, float] = {}  # query -> when it was asked, so a typed word is not sent again for an hour


def enabled() -> bool:
    return bool(os.environ.get("FDC_API_KEY"))


def to_food(item: dict) -> dict | None:
    """A foods row from one search result, None without energy."""
    by_id = {n.get("nutrientId"): n.get("value") for n in item.get("foodNutrients") or []}
    per_100 = {k: (float(by_id[i]) if by_id.get(i) is not None else None) for k, i in IDS.items()}
    if per_100["energy_kcal"] is None:
        return None
    total = by_id.get(CARBS_BY_DIFFERENCE)
    per_100["carbs_g"] = round(max(0.0, float(total) - (per_100["fiber_g"] or 0)), 3) if total is not None else None
    name = (item.get("description") or "").strip()
    if not name:
        return None
    return {
        "source": "usda", "source_code": str(item["fdcId"]), "name_nl": name[:200], "name_en": name[:200], "brand": (item.get("brandOwner") or None),
        "food_group": item.get("foodCategory") if isinstance(item.get("foodCategory"), str) else None, "unit": "g",
        "per_100": with_salt({k: per_100.get(k) for k in KEYS}), "default_portion_g": None, "source_version": "USDA FoodData Central",
    }


def fetch(query: str) -> list[dict]:
    r = requests.get(URL, params={"api_key": os.environ["FDC_API_KEY"], "query": query, "pageSize": PAGE,
                                  "dataType": "Foundation,SR Legacy"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("foods") or []


def fill_later(s: db.Scope, query: str) -> bool:
    """fill() in the background, so a search never waits for USDA; True when a lookup was started. The picker asks
    again a moment later and then finds what came in."""
    q = foods.norm(query)
    if not enabled() or len(q) < MIN_QUERY:
        return False
    with _lock:
        if time.monotonic() - _asked.get(q, -CACHE_S) < CACHE_S:
            return False
    threading.Thread(target=fill, args=(s, query), name="usda", daemon=True).start()
    return True


def fill(s: db.Scope, query: str, fetcher=None) -> int:
    """Ask USDA for `query` once an hour at most, cache what it knows; returns how many foods were added."""
    q = foods.norm(query)
    if not enabled() or len(q) < MIN_QUERY:
        return 0
    with _lock:
        if time.monotonic() - _asked.get(q, -CACHE_S) < CACHE_S:
            return 0
        _asked[q] = time.monotonic()
        if len(_asked) > 2000:
            _asked.clear()
    try:
        items = (fetcher or fetch)(query)
    except (requests.RequestException, ValueError, KeyError):
        return 0
    added = 0
    with s.engine.begin() as conn:
        have = {c for (c,) in conn.execute(select(db.foods.c.source_code).where(db.foods.c.source == "usda"))}
        for item in items:
            row = to_food(item) if item.get("fdcId") is not None else None
            if row and row["source_code"] not in have:
                conn.execute(insert(db.foods).values(**row))
                have.add(row["source_code"])
                added += 1
    if added:
        foods.invalidate()
    return added
