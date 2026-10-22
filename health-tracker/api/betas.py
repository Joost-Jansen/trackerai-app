"""Beta features: switched on per user by an admin, from the admin hub at trackerai.nl/admin (api/tracker_admin.py).

To add one, put it in BETA_FEATURES (display order) with its name in both languages:

    {"id": "new_trends", "name": {"en": "New trends page", "nl": "Nieuwe trendspagina"}},

then gate the feature on it: `enabled(engine, user.id, "new_trends")` in a route, or `betas` from /api/me on the site.
Removing a feature from the list switches it off for everyone; what users had stored is ignored, not an error.

Private features are a second kind: not in the admin hub and not switchable there, only on for the accounts listed in
an environment variable (usernames or health-tracker user ids, comma-separated). Empty or unset: off for everyone. For
the rest of the site they behave like a beta (`enabled`, `betas` from /api/me); for everyone else they do not exist.
"""

from __future__ import annotations

import os

from tools import db

BETA_FEATURES: list[dict] = [
    {"id": "nutrition", "name": {"en": "Nutrition", "nl": "Voeding"}},  # meals, food search, training-aware targets
]


# feature id -> the environment variable with the accounts that have it
PRIVATE_FEATURES: dict[str, str] = {
    "skin": "SKIN_DIARY_USERS",  # the skin diary (api/skin.py)
}


def _allowed(engine, user_id: int, variable: str) -> bool:
    names = {n.strip().lower() for n in os.environ.get(variable, "").split(",") if n.strip()}
    if not names:
        return False
    if str(user_id) in names:
        return True
    user = db.get_user(engine, user_id)
    return bool(user) and user["username"].lower() in names


def ids() -> list[str]:
    return [f["id"] for f in BETA_FEATURES]


def of_user(engine, user_id: int) -> list[str]:
    """The user's beta features that still exist, in display order, then the private features listed for them."""
    mine = set(db.user_betas(engine, user_id))
    private = [f for f, variable in PRIVATE_FEATURES.items() if _allowed(engine, user_id, variable)]
    return [f for f in ids() if f in mine] + private


def enabled(engine, user_id: int, feature: str) -> bool:
    return feature in of_user(engine, user_id)
