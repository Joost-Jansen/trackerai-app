"""One-time move of the repo's files (data/, zones.json, profile.md, goals.md, log/, routes/) into the database.

    DATABASE_URL=... .venv/bin/python tools/migrate_files_to_db.py

Safe to run twice: activities merge by start time, log entries are skipped when the database already has log entries.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import db

ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}): (.+)$", re.M)


def split_log(text: str) -> list[dict]:
    parts = HEADING.split(text)
    # parts = [preamble, day, title, body, day, title, body, ...]
    return [{"day": parts[i], "title": parts[i + 1].strip(), "body": parts[i + 2].strip() + "\n"} for i in range(1, len(parts), 3)]


def migrate(root: Path, engine: db.Scope) -> dict:
    """`engine` is the Scope of the user that receives the files."""
    root = Path(root)
    db.create_schema(engine.engine)
    counts = {"activities": 0, "fit": 0, "wellness": 0, "log": 0}

    for path in sorted((root / "data" / "activities").glob("*/*.json")):
        a = json.loads(path.read_text())
        a.pop("hr_zones_s", None)  # derived; the build step recomputes it from zones
        sources = a.get("sources", {})
        # Re-insert per source so the merge rules stay the same as in the sync.
        for i, (src, info) in enumerate(sources.items()):
            record = {k: v for k, v in a.items() if k not in ("sources", "streams")}
            record.update(info.get("fields", {}))
            record["sources"] = {src: {k: v for k, v in info.items() if k != "fields"}}
            if i == 0 and a.get("streams"):
                record["streams"] = a["streams"]
            aid = db.upsert_activity(engine, record)
        counts["activities"] += 1
        fit = a.get("fit_file")
        if fit and (root / fit).exists() and not db.has_fit(engine, aid):
            db.put_fit(engine, aid, (root / fit).read_bytes())
            counts["fit"] += 1

    for path in sorted((root / "data" / "wellness").glob("*/*.json")):
        db.write_wellness(engine, path.stem, json.loads(path.read_text()))
        counts["wellness"] += 1

    zones = root / "zones.json"
    if zones.exists():
        db.set_setting(engine, "zones", {k: v for k, v in json.loads(zones.read_text()).items() if not k.startswith("_")})
    state = root / "data" / "sync_state.json"
    if state.exists():
        db.set_setting(engine, "sync_state", json.loads(state.read_text()))
    for key in ("profile", "goals"):
        doc = root / f"{key}.md"
        if doc.exists():
            db.put_document(engine, key, doc.read_text(), author="migratie")

    if not db.list_entries(engine, kind="log", limit=1):
        for log in sorted((root / "log").glob("*.md")):
            for item in split_log(log.read_text()):
                db.add_entry(engine, kind="log", author="agent", **item)
                counts["log"] += 1

    routes_file = root / "routes" / "routes.json"
    if routes_file.exists():
        db.save_routes(engine, [dict(r, sport=r.get("sport", "run")) for r in json.loads(routes_file.read_text())])
    return counts


if __name__ == "__main__":
    print(migrate(ROOT, db.Scope(db.connect(os.environ["DATABASE_URL"]), int(os.environ.get("TRAINING_USER_ID", "1")))))
