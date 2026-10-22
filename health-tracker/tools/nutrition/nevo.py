"""Import NEVO-online (RIVM's Dutch food composition table) into the global `foods` table.

    python -m tools.nutrition.nevo NEVO2025_v9.0.csv        # DATABASE_URL from the environment

or as an admin from the site: POST /api/nutrition/admin/nevo with the CSV (or the zip RIVM hands out) as the body.

The file comes from https://www.rivm.nl/nederlands-voedingsstoffenbestand (free, after accepting RIVM's conditions).
It is not in this repository: RIVM allows linking to it, not handing it out. Conditions that shape the app:
values are used unchanged (additions such as Open Food Facts or your own foods stay marked as such, never edits of
NEVO rows), and output that is calculated from them names the source and version (ATTRIBUTION).

The CSV: UTF-8, `|` between fields, values in double quotes with a decimal comma, an empty field for "not measured".
Idempotent: a row is matched on its NEVO-code, so importing the same release twice changes nothing and a new release
updates the foods in place (past meals keep the snapshot they were logged with).
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile

from sqlalchemy import insert, select, update

from tools import db
from tools.nutrition.nutrients import NEVO_CODES, with_salt

SOURCE = "nevo"
# What RIVM's conditions ask calculated output to say, nl and en (the en is our translation of the same reference).
ATTRIBUTION = {
    "nl": "Gebaseerd op gegevens van NEVO-online versie {version}, RIVM, Bilthoven",
    "en": "Based on data from NEVO-online version {version}, RIVM, Bilthoven",
}
MAX_CSV_BYTES = 20 * 1024 * 1024  # the 2025 table is 1.7 MB; a zip that unpacks to more is not RIVM's
REQUIRED = ("NEVO-code", "Voedingsmiddelnaam/Dutch food name", "Hoeveelheid/Quantity", "ENERCC (kcal)")


class NevoFormatError(ValueError):
    pass


def _number(text: str) -> float | None:
    text = (text or "").strip().strip('"').replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _code_of(header: str) -> str:
    """'ENERCC (kcal)' -> 'ENERCC'."""
    return header.split(" (", 1)[0].strip()


def csv_text(data: bytes) -> str:
    """The food table's text from the CSV itself or from RIVM's zip (the file named NEVO*.csv without a suffix)."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if re.fullmatch(r"(?:.*/)?NEVO\d{4}_v[\d.]+\.csv", n)]
            if not names:
                raise NevoFormatError("no NEVO<year>_v<version>.csv in the zip")
            if z.getinfo(names[0]).file_size > MAX_CSV_BYTES:
                raise NevoFormatError("the food table in the zip is larger than expected")
            data = z.read(names[0])
    return data.decode("utf-8-sig")


def parse(text: str) -> tuple[str | None, list[dict]]:
    """(release, foods) from the CSV text. Each food: source_code, names, synonyms, group, unit, per_100."""
    reader = csv.reader(io.StringIO(text), delimiter="|")
    try:
        header = next(reader)
    except StopIteration:
        raise NevoFormatError("empty file") from None
    missing = [h for h in REQUIRED if h not in header]
    if missing:
        raise NevoFormatError("not a NEVO-online table, missing columns: " + ", ".join(missing))
    col = {h: i for i, h in enumerate(header)}
    by_code = {_code_of(h): i for i, h in enumerate(header)}
    release = None
    out = []
    for row in reader:
        if not row or len(row) < len(REQUIRED):
            continue
        get = lambda h: row[col[h]].strip() if h in col and col[h] < len(row) else ""  # noqa: E731, B023  # used within this iteration only
        code = get("NEVO-code")
        if not code:
            continue
        release = release or get("NEVO-versie/NEVO-version") or None
        values = {key: _number(row[by_code[c]]) if by_code.get(c, len(row)) < len(row) else None for key, c in NEVO_CODES.items()}
        out.append(
            {
                "source_code": code,
                "name_nl": get("Voedingsmiddelnaam/Dutch food name"),
                "name_en": get("Engelse naam/Food name") or None,
                "synonyms": get("Synoniem") or None,
                "food_group": get("Food group") or get("Voedingsmiddelgroep") or None,
                "unit": "ml" if "ml" in get("Hoeveelheid/Quantity").lower() else "g",
                "per_100": with_salt(values),
            }
        )
    return release, out


def version_label(release: str | None) -> str:
    """'NEVO-Online 2025 9.0' -> '2025/9.0', the way RIVM writes the version in its reference."""
    m = re.search(r"(\d{4})\D+(\d+(?:\.\d+)*)", release or "")
    return f"{m[1]}/{m[2]}" if m else (release or "?")


def import_foods(engine, text: str) -> dict:
    """Insert new and update changed NEVO foods; returns counts and the release."""
    release, rows = parse(text)
    version = f"NEVO-online {version_label(release)}"
    added = updated = 0
    with engine.begin() as conn:
        have = {
            r.source_code: r
            for r in conn.execute(
                select(db.foods.c.id, db.foods.c.source_code, db.foods.c.per_100, db.foods.c.name_nl, db.foods.c.source_version).where(
                    db.foods.c.source == SOURCE
                )
            )
        }
        for f in rows:
            old = have.get(f["source_code"])
            if old is None:
                conn.execute(insert(db.foods).values(source=SOURCE, source_version=version, **f))
                added += 1
            elif old.per_100 != f["per_100"] or old.name_nl != f["name_nl"] or old.source_version != version:
                conn.execute(update(db.foods).where(db.foods.c.id == old.id).values(source_version=version, **f))
                updated += 1
    from tools.nutrition import foods as food_index  # the in-process search index reads the table again

    food_index.invalidate()
    return {"release": version, "foods": len(rows), "added": added, "updated": updated}


def current_version(engine) -> str | None:
    """The NEVO release in the table, e.g. 'NEVO-online 2025/9.0'; None before the first import."""
    with engine.connect() as conn:
        return conn.execute(select(db.foods.c.source_version).where(db.foods.c.source == SOURCE).limit(1)).scalar_one_or_none()


def attribution(version: str | None, lang: str = "nl", others: bool = False) -> str | None:
    """RIVM's reference for output calculated from NEVO; `others` when other sources are in it too."""
    if not version:
        return None
    text = ATTRIBUTION[lang].format(version=version.removeprefix("NEVO-online ").strip())
    return text + ({"nl": " en andere gegevens", "en": " and other data"}[lang] if others else "")


def main(argv: list[str]) -> int:
    import os

    if len(argv) != 1:
        print(__doc__)
        return 2
    engine = db.connect(os.environ["DATABASE_URL"])
    db.create_schema(engine)
    with open(argv[0], "rb") as fh:
        counts = import_foods(engine, csv_text(fh.read()))
    print(f"{counts['release']}: {counts['foods']} foods, {counts['added']} added, {counts['updated']} updated", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
