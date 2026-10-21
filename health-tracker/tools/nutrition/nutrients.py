"""The nutrient keys every food, meal item and total uses, and how each source's codes map onto them.

Values are per 100 g (or per 100 ml for a food whose unit is ml), as the source gives them. A missing value is None:
"not measured", which is not the same as 0. Totals add what is known and count what was missing (`missing`).
"""

from __future__ import annotations

# The one key set, in display order. Units are in the key: _g, _mg, _ug (micrograms), energy in kcal.
KEYS: tuple[str, ...] = (
    "energy_kcal",
    "carbs_g",
    "sugars_g",
    "fiber_g",
    "protein_g",
    "fat_g",
    "sat_fat_g",
    "mufa_g",
    "pufa_g",
    "omega3_g",
    "trans_fat_g",
    "alcohol_g",
    "salt_g",
    "sodium_mg",
    "iron_mg",
    "calcium_mg",
    "magnesium_mg",
    "potassium_mg",
    "zinc_mg",
    "vit_c_mg",
    "vit_d_ug",
    "vit_b12_ug",
    "folate_ug",
)
MACROS = ("energy_kcal", "carbs_g", "protein_g", "fat_g", "fiber_g", "alcohol_g", "salt_g")

# NEVO-online 2025/9.0 column codes (NEVO2025_v9.0_Nutrienten_Nutrients.csv): CHO is available carbohydrate, FOL
# dietary folate equivalents, FAMSCIS monounsaturated cis. NEVO has no salt column: salt is sodium x 2.5 (SALT_PER_NA).
NEVO_CODES: dict[str, str] = {
    "energy_kcal": "ENERCC",
    "carbs_g": "CHO",
    "sugars_g": "SUGAR",
    "fiber_g": "FIBT",
    "protein_g": "PROT",
    "fat_g": "FAT",
    "sat_fat_g": "FASAT",
    "mufa_g": "FAMSCIS",
    "pufa_g": "FAPU",
    "omega3_g": "FAPUN3",
    "trans_fat_g": "FATRS",
    "alcohol_g": "ALC",
    "sodium_mg": "NA",
    "iron_mg": "FE",
    "calcium_mg": "CA",
    "magnesium_mg": "MG",
    "potassium_mg": "K",
    "zinc_mg": "ZN",
    "vit_c_mg": "VITC",
    "vit_d_ug": "VITD",
    "vit_b12_ug": "VITB12",
    "folate_ug": "FOL",
}
SALT_PER_NA = 2.5 / 1000  # g salt per mg sodium (NaCl is 39.3% sodium; the factor food labels use)

# Energy per gram, to split a day's energy by macro (EnergySplit): the factors NEVO and EU labels use.
KCAL_PER_G = {"carbs_g": 4.0, "protein_g": 4.0, "fat_g": 9.0, "alcohol_g": 7.0, "fiber_g": 2.0}

# A unit of alcohol in the Netherlands (standaardglas): 10 g.
ALCOHOL_UNIT_G = 10.0


def with_salt(values: dict) -> dict:
    """`values` with salt_g from sodium when the source gave sodium and no salt (None when it gave neither)."""
    if values.get("salt_g") is None and values.get("sodium_mg") is not None:
        return {**values, "salt_g": round(values["sodium_mg"] * SALT_PER_NA, 3)}
    return {**values, "salt_g": values.get("salt_g")}


def scale(per_100: dict, amount: float) -> dict:
    """What `amount` g (or ml) of a food holds: every known value times amount/100, None stays None."""
    f = amount / 100.0
    return {k: (round(per_100[k] * f, 3) if per_100.get(k) is not None else None) for k in KEYS}


def total(items: list[dict]) -> dict:
    """The sum of nutrient dicts. `missing`: per key, how many items did not know it (a 0 there would be a guess)."""
    out: dict = {k: 0.0 for k in KEYS}
    missing = {k: 0 for k in KEYS}
    for item in items:
        for k in KEYS:
            v = item.get(k)
            if v is None:
                missing[k] += 1
            else:
                out[k] += v
    rounded = {k: round(v, 1) for k, v in out.items()}
    rounded["missing"] = {k: n for k, n in missing.items() if n}
    return rounded


def energy_split(totals: dict) -> dict:
    """Share of energy per macro (carbs, protein, fat, alcohol, fibre), from grams and KCAL_PER_G, summing to 1."""
    kcal = {k: (totals.get(k) or 0) * f for k, f in KCAL_PER_G.items()}
    whole = sum(kcal.values())
    return {k: round(v / whole, 3) if whole else 0.0 for k, v in kcal.items()}
