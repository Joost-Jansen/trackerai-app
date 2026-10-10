"""Pushes an operational warning to the owner's phone, over ntfy.

Only for things the *server* notices and no user can act on — a position that
cannot be priced is the first of them. Users see their own problems in the app;
this exists because nobody was watching when the app quietly stopped counting a
holding, and the one person who could fix it heard about it by WhatsApp.

Deliberately thin:

  * **Never raises, never blocks anything.** A failed push must not break a
    price refresh; the caller gets False and carries on.
  * **Off unless configured.** NTFY_TOPIC_URL comes from the gitignored .env
    (the same topic the holdings canary uses, so no second subscription). Unset
    — which is every developer machine and the whole test suite — means no
    network call at all.
"""

import os

import requests

_TIMEOUT_SECONDS = 8


def topic_url() -> str:
    return os.environ.get("NTFY_TOPIC_URL", "").strip()


def push(title: str, message: str, *, tags: str = "warning", priority: str = "default") -> bool:
    """Sends one notification. Returns whether it went out."""
    url = topic_url()
    if not url:
        return False
    try:
        response = requests.post(
            url,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": priority,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        return response.status_code < 400
    except Exception as e:
        print(f"[notify] push failed: {e}")
        return False
