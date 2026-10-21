"""Packaged products by barcode from Open Food Facts (ODbL: attribution required, shown with the product), cached in
the global `foods` table (source `off`) on first use so a product is fetched once.

Only the barcode leaves the server: GET https://world.openfoodfacts.org/api/v2/product/<ean>.json with a User-Agent
that names this app, as Open Food Facts asks. Its `*_100g` values are in grams (also sodium and vitamins), energy in
kcal under `energy-kcal_100g`, and alcohol in % vol; FACTOR turns them into the keys of tools/nutrition/nutrients.py.
"""

from __future__ import annotations

import os
import re

import requests
from sqlalchemy import insert, select

from tools import db
from tools.nutrition import foods
from tools.nutrition.nutrients import with_salt

URL = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
FIELDS = "product_name,product_name_nl,product_name_en,brands,nutriments,serving_quantity,quantity,product_quantity_unit,nutrition_data_per"
TIMEOUT_S = 8
ETHANOL_G_PER_ML = 0.789
# our key: (Open Food Facts nutriment, factor from its unit)
FACTOR: dict[str, tuple[str, float]] = {
    "energy_kcal": ("energy-kcal_100g", 1),
    "carbs_g": ("carbohydrates_100g", 1),
    "sugars_g": ("sugars_100g", 1),
    "fiber_g": ("fiber_100g", 1),
    "protein_g": ("proteins_100g", 1),
    "fat_g": ("fat_100g", 1),
    "sat_fat_g": ("saturated-fat_100g", 1),
    "mufa_g": ("monounsaturated-fat_100g", 1),
    "pufa_g": ("polyunsaturated-fat_100g", 1),
    "omega3_g": ("omega-3-fat_100g", 1),
    "trans_fat_g": ("trans-fat_100g", 1),
    "alcohol_g": ("alcohol_100g", ETHANOL_G_PER_ML),
    "salt_g": ("salt_100g", 1),
    "sodium_mg": ("sodium_100g", 1000),
    "iron_mg": ("iron_100g", 1000),
    "calcium_mg": ("calcium_100g", 1000),
    "magnesium_mg": ("magnesium_100g", 1000),
    "potassium_mg": ("potassium_100g", 1000),
    "zinc_mg": ("zinc_100g", 1000),
    "vit_c_mg": ("vitamin-c_100g", 1000),
    "vit_d_ug": ("vitamin-d_100g", 1e6),
    "vit_b12_ug": ("vitamin-b12_100g", 1e6),
    "folate_ug": ("folates_100g", 1e6),
}


class LookupFailed(Exception):
    pass


class NoNutrients(Exception):
    """Open Food Facts knows the product, without energy per 100 g (nothing to count with)."""


def valid_ean(ean: str) -> bool:
    """8, 12, 13 or 14 digits with a correct GS1 check digit."""
    if not re.fullmatch(r"\d{8}|\d{12,14}", ean or ""):
        return False
    digits = [int(c) for c in ean]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def user_agent() -> str:
    contact = os.environ.get("OFF_CONTACT", "").strip()  # an e-mail address of whoever runs this installation, optional
    return f"trackerai-health/1.0 ({contact})" if contact else "trackerai-health/1.0"


def fetch(ean: str) -> dict | None:
    """The product as Open Food Facts has it; None when it does not know the barcode."""
    try:
        r = requests.get(URL.format(ean=ean), params={"fields": FIELDS}, headers={"User-Agent": user_agent()}, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise LookupFailed(type(e).__name__) from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise LookupFailed(f"HTTP {r.status_code}")
    data = r.json()
    return data.get("product") if data.get("status") == 1 else None


def to_food(ean: str, product: dict) -> dict | None:
    """A foods row for a product, None without a name or without energy per 100 (nothing to count with). Open Food
    Facts gives `*_100g` also for a product labelled per serving, when it knows the serving size."""
    n = product.get("nutriments") or {}
    per_100 = {}
    for key, (field, factor) in FACTOR.items():
        value = n.get(field)
        try:
            per_100[key] = round(float(value) * factor, 4) if value not in (None, "") else None
        except (TypeError, ValueError):
            per_100[key] = None
    name = (product.get("product_name_nl") or product.get("product_name") or "").strip()
    if not name or per_100.get("energy_kcal") is None:
        return None
    unit = "ml" if (product.get("product_quantity_unit") or "").lower() == "ml" else "g"
    serving = product.get("serving_quantity")
    try:
        portion = float(serving) if serving not in (None, "") else None
    except (TypeError, ValueError):
        portion = None
    return {
        "source": "off",
        "source_code": ean,
        "name_nl": name[:200],
        "name_en": (product.get("product_name_en") or product.get("product_name") or "").strip()[:200] or None,
        "brand": (product.get("brands") or "").split(",")[0].strip()[:100] or None,
        "food_group": None,
        "unit": unit,
        "per_100": with_salt(per_100),
        "default_portion_g": portion,
        "source_version": "Open Food Facts",
    }


def lookup(s: db.Scope, ean: str, fetcher=None) -> dict | None:
    """The product as a food (public shape, tools/nutrition/foods.py), from the cache or else from Open Food Facts."""
    cached = foods.get(s, foods.ref_of("off", ean))
    if cached:
        return cached
    product = (fetcher or fetch)(ean)
    if not product:
        return None
    row = to_food(ean, product)
    if row is None:
        raise NoNutrients(ean)
    with s.engine.begin() as conn:
        if conn.execute(select(db.foods.c.id).where(db.foods.c.source == "off", db.foods.c.source_code == ean)).first() is None:
            conn.execute(insert(db.foods).values(**row))
    food = foods.get(s, foods.ref_of("off", ean))
    foods.add(s.engine, food)  # into the loaded index, instead of reading the whole table again
    return food
