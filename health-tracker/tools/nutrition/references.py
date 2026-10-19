"""Dutch reference intakes for adults, per day: the Voedingscentrum's table of the Gezondheidsraad's norms
("Aanbevelingen voor vitamines, mineralen en spoorelementen", Voedingscentrum 05/2025,
https://mobiel.voedingscentrum.nl/Assets/Uploads/voedingscentrum/Documents/Professionals/vitamines%20en%20mineralen/Vitamines%20mineralen%20en%20spoorelementen_2025_def.pdf).

ADH (aanbevolen dagelijkse hoeveelheid) is what nearly everyone needs; AI (adequate inname) is used where too little is
known for an ADH, and is a guide rather than a target. Several norms differ by sex and age: the user picks men's or
women's norms in the Nutrition settings (the profile has a birth year, not a sex); without a choice there is no
percentage. Values are for adults from 18, not for pregnancy or breastfeeding.
"""

from __future__ import annotations

from datetime import date

SOURCE = {
    "nl": "Aanbevelingen voor vitamines, mineralen en spoorelementen, Voedingscentrum 05/2025 (normen van de Gezondheidsraad)",
    "en": "Recommendations for vitamins, minerals and trace elements, Voedingscentrum 05/2025 (norms of the Health Council of the Netherlands)",
    "url": "https://mobiel.voedingscentrum.nl/Assets/Uploads/voedingscentrum/Documents/Professionals/vitamines%20en%20mineralen/Vitamines%20mineralen%20en%20spoorelementen_2025_def.pdf",
}
GROUPS = ("men", "women")
# key: (kind, {group: [(from_age, value), ...]}) with the age bands in ascending order; a band runs to the next one.
NORMS: dict[str, tuple[str, dict[str, list[tuple[int, float]]]]] = {
    "iron_mg": ("ADH", {"men": [(18, 11)], "women": [(18, 16), (50, 11)]}),
    "vit_d_ug": ("ADH", {"men": [(18, 10), (70, 20)], "women": [(18, 10), (70, 20)]}),
    "calcium_mg": ("ADH", {"men": [(18, 1000), (25, 950), (70, 1200)], "women": [(18, 1000), (25, 950), (50, 1100), (70, 1200)]}),
    "magnesium_mg": ("AI", {"men": [(18, 350)], "women": [(18, 300)]}),
    "potassium_mg": ("AI", {"men": [(18, 3500)], "women": [(18, 3500)]}),
    "zinc_mg": ("ADH", {"men": [(18, 9.0)], "women": [(18, 7.0)]}),
    "vit_c_mg": ("ADH", {"men": [(18, 75)], "women": [(18, 75)]}),
    "vit_b12_ug": ("ADH", {"men": [(18, 2.8)], "women": [(18, 2.8)]}),
    "folate_ug": ("ADH", {"men": [(18, 300)], "women": [(18, 300)]}),
}
# The order of the Vitamins and minerals table: what matters most for endurance athletes first (spec), then the rest.
ORDER = ("iron_mg", "vit_d_ug", "calcium_mg", "magnesium_mg", "potassium_mg", "zinc_mg", "vit_c_mg", "vit_b12_ug", "folate_ug", "sodium_mg")


def age(birth_year: int | None, today: date) -> int | None:
    return today.year - int(birth_year) if birth_year else None


def norm(key: str, group: str | None, years: int | None) -> tuple[str, float] | None:
    """(ADH|AI, amount per day) for a nutrient, or None without a group or for a nutrient without a norm here. An
    unknown age takes the band from 18 (the age bands only differ for calcium, iron for women and vitamin D)."""
    if group not in GROUPS or key not in NORMS:
        return None
    kind, by_group = NORMS[key]
    value = None
    for start, amount in by_group[group]:
        if years is None and value is not None:
            break
        if years is None or years >= start:
            value = amount
    return (kind, value) if value is not None else None


def table(totals: dict, group: str | None, years: int | None) -> list[dict]:
    """The Vitamins and minerals rows: amount eaten, the norm and the share of it (None without a norm)."""
    rows = []
    for key in ORDER:
        n = norm(key, group, years)
        amount = totals.get(key)
        rows.append({"key": key, "amount": amount, "kind": n[0] if n else None, "reference": n[1] if n else None,
                     "pct": round(amount / n[1] * 100) if n and amount is not None else None,
                     "missing": (totals.get("missing") or {}).get(key, 0)})
    return rows
