"""Beta features: switched on per user by an admin, from the admin hub at trackerai.nl/admin (api/tracker_admin.py).

To add one, put it in BETA_FEATURES (display order) with its name in both languages:

    {"id": "new_trends", "name": {"en": "New trends page", "nl": "Nieuwe trendspagina"}},

then gate the feature on it: `enabled(engine, user.id, "new_trends")` in a route, or `betas` from /api/me on the site.
Removing a feature from the list switches it off for everyone; what users had stored is ignored, not an error.
"""

from __future__ import annotations

from tools import db

BETA_FEATURES: list[dict] = [
    {"id": "nutrition", "name": {"en": "Nutrition", "nl": "Voeding"}},  # meals, food search, training-aware targets
]


def ids() -> list[str]:
    return [f["id"] for f in BETA_FEATURES]


def of_user(engine, user_id: int) -> list[str]:
    """The user's beta features that still exist, in display order."""
    mine = set(db.user_betas(engine, user_id))
    return [f for f in ids() if f in mine]


def enabled(engine, user_id: int, feature: str) -> bool:
    return feature in of_user(engine, user_id)
