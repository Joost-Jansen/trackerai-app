"""Dutch and English for messages a person reads: errors, upload results, labels.

The code holds the English text; NL (domain/i18n_nl.py) maps it to Dutch. The
language is per request: middleware in app/main.py sets it from the X-Locale
header the frontend sends. Without that header it is Dutch, as the API always was.

    tr("Account {0} does not exist.", account_id)

Placeholders {0}, {1}… are the arguments in order; a translation may move them.
Names that are data (categories, accounts) are passed in, never translated.
"""

from __future__ import annotations

import re
from contextvars import ContextVar

from domain.i18n_nl import NL

LOCALES = ("nl", "en")
DEFAULT_LOCALE = "nl"

_locale: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)
_PLACEHOLDER = re.compile(r"\{(\d+)\}")


def set_locale(value: str | None):
    """Set the language of this request; returns the token to reset it with."""
    return _locale.set(value if value in LOCALES else DEFAULT_LOCALE)


def reset_locale(token) -> None:
    _locale.reset(token)


def current_locale() -> str:
    return _locale.get()


def tr(text: str, *args: object) -> str:
    """`text` in the current language, with {0}, {1}… filled in."""
    s = NL.get(text, text) if _locale.get() == "nl" else text
    if not args:
        return s
    return _PLACEHOLDER.sub(lambda m: str(args[int(m.group(1))]) if int(m.group(1)) < len(args) else m.group(0), s)
