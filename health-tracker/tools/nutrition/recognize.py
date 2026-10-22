"""Recognise a meal on a photo with Claude: which foods, how many grams, and what a photo cannot show.

Claude names foods and estimates edible weight; it never gives nutrient values (those come from the food table,
tools/nutrition/match.py and nutrients.py). One Messages API call through the shared client (packages/ai) with the
image and a JSON schema for the answer (structured output). Every call is logged in nutrition_ai_runs: model, prompt
version, time, tokens and the answer (never the image), so cost and accuracy can be measured.

    NUTRITION_MODEL   the model (default DEFAULT_MODEL)
    NUTRITION_EFFORT  low | medium | high (default medium: a meal photo is perception, not a long reasoning task)
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select

import trackerai_ai
from tools import db

DEFAULT_MODEL = "claude-sonnet-5-5"
# Models that take server-side refusal fallbacks in their "default" form (Claude API).
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")
PROMPT_VERSION = "1"
TIMEOUT_S = 30
RETRIES = 1
MAX_ITEMS = 15
MAX_EXTRAS = 5
MAX_GRAMS = 3000.0
KINDS = ("food", "drink", "sauce", "fat")
MOMENTS = ("breakfast", "lunch", "dinner", "snack", "training", "drinks")
REFERENCES = ("plate", "bowl", "cutlery", "hand", "glass", "packaging", "none")

SYSTEM = """You look at a photo of a meal or a drink and list what is on it, for a food diary in the Netherlands.

For every separate food or drink you can see:
- label_nl: its usual Dutch name, as plain as a Dutch food table would list it (for example "havermout", "banaan",
  "volkorenbrood", "kipfilet gebakken", "rijst witte gekookt"); label_en: the same in English.
- kind: food, drink, sauce (dressings, gravy, ketchup) or fat (butter, oil, margarine you can see).
- grams: your best estimate of the edible weight in grams (for a drink: millilitres), without peel, bones or packaging;
  grams_low and grams_high: a range you are fairly sure the true weight lies in.
- confidence: 0 to 1, how sure you are of what it is (not of the weight).
- cooking: how it was prepared if you can tell (raw, boiled, fried, baked, grilled), else "".
- search_terms: two to four Dutch words to find it in a food table, most specific first.

Use the plate, bowl, cutlery, a hand or a glass to judge size; say which one you used in reference_object (or "none").
In hidden_extras list up to three things a photo usually hides but this meal probably has, such as oil or butter used
for frying, sugar in coffee or tea, or a sauce (label_nl, label_en, a typical amount in grams, search_terms); leave it
empty when nothing is likely. moment_guess: breakfast, lunch, dinner, snack, training (sports food or drink) or drinks.
Do not give calories or nutrients. If the photo shows no food or drink, return an empty items list."""

_TERMS = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label_nl": {"type": "string"},
                    "label_en": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "grams": {"type": "number"},
                    "grams_low": {"type": "number"},
                    "grams_high": {"type": "number"},
                    "confidence": {"type": "number"},
                    "cooking": {"type": "string"},
                    "search_terms": _TERMS,
                },
                "required": ["label_nl", "label_en", "kind", "grams", "grams_low", "grams_high", "confidence", "cooking", "search_terms"],
                "additionalProperties": False,
            },
        },
        "hidden_extras": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label_nl": {"type": "string"},
                    "label_en": {"type": "string"},
                    "grams": {"type": "number"},
                    "search_terms": _TERMS,
                },
                "required": ["label_nl", "label_en", "grams", "search_terms"],
                "additionalProperties": False,
            },
        },
        "reference_object": {"type": "string", "enum": list(REFERENCES)},
        "moment_guess": {"type": "string", "enum": list(MOMENTS)},
    },
    "required": ["items", "hidden_extras", "reference_object", "moment_guess"],
    "additionalProperties": False,
}


def model() -> str:
    return os.environ.get("NUTRITION_MODEL", "").strip() or DEFAULT_MODEL


def request(mime: str, image: bytes) -> dict:
    """The Messages API request for one photo."""
    effort = os.environ.get("NUTRITION_EFFORT", "").strip() or "medium"
    return {
        "model": model(),
        "max_tokens": 4000,
        "system": SYSTEM,
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.standard_b64encode(image).decode()}},
                    {"type": "text", "text": "What is on this photo?"},
                ],
            }
        ],
    }


def _grams(value, low=0.5, high=MAX_GRAMS) -> float:
    try:
        return round(min(max(float(value), low), high), 1)
    except (TypeError, ValueError):
        return low


def tidy(answer: dict) -> dict:
    """Claude's answer within bounds: grams between 0.5 and 3 kg with low <= grams <= high, confidence 0-1, short
    lists; anything unusable left out."""
    items = []
    for it in (answer.get("items") or [])[:MAX_ITEMS]:
        label = str(it.get("label_nl") or "").strip()
        if not label:
            continue
        grams = _grams(it.get("grams"))
        low, high = sorted((_grams(it.get("grams_low", grams)), _grams(it.get("grams_high", grams))))
        items.append(
            {
                "label_nl": label[:120],
                "label_en": str(it.get("label_en") or "").strip()[:120] or None,
                "kind": it.get("kind") if it.get("kind") in KINDS else "food",
                "grams": grams,
                "grams_low": min(low, grams),
                "grams_high": max(high, grams),
                "confidence": round(min(max(float(it.get("confidence") or 0), 0.0), 1.0), 2),
                "cooking": str(it.get("cooking") or "")[:40],
                "search_terms": [str(t)[:40] for t in (it.get("search_terms") or []) if str(t).strip()][:4] or [label],
            }
        )
    extras = []
    for ex in (answer.get("hidden_extras") or [])[:MAX_EXTRAS]:
        label = str(ex.get("label_nl") or "").strip()
        if label:
            extras.append(
                {
                    "label_nl": label[:120],
                    "label_en": str(ex.get("label_en") or "").strip()[:120] or None,
                    "grams": _grams(ex.get("grams"), 0.5, 200),
                    "search_terms": [str(t)[:40] for t in (ex.get("search_terms") or []) if str(t).strip()][:4] or [label],
                }
            )
    return {
        "items": items,
        "hidden_extras": extras,
        "reference_object": answer.get("reference_object") if answer.get("reference_object") in REFERENCES else "none",
        "moment_guess": answer.get("moment_guess") if answer.get("moment_guess") in MOMENTS else None,
    }


def daily_limit() -> int:
    """How many photos one user may have analysed in 24 hours (each is a paid call): NUTRITION_DAILY_PHOTOS, default 40."""
    try:
        return max(1, int(os.environ.get("NUTRITION_DAILY_PHOTOS") or 40))
    except ValueError:
        return 40


def runs_last_day(s: db.Scope) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    with s.engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(db.nutrition_ai_runs)
            .where(db.nutrition_ai_runs.c.user_id == s.user_id, db.nutrition_ai_runs.c.created_at >= since)
        ).scalar_one()


def owns_run(s: db.Scope, run_id: int) -> bool:
    with s.engine.connect() as conn:
        return (
            conn.execute(
                select(db.nutrition_ai_runs.c.id).where(db.nutrition_ai_runs.c.user_id == s.user_id, db.nutrition_ai_runs.c.id == run_id)
            ).first()
            is not None
        )


def log_run(s: db.Scope, result, answer: dict | None, error: str | None = None) -> int:
    with s.engine.begin() as conn:
        return conn.execute(
            insert(db.nutrition_ai_runs).values(
                user_id=s.user_id,
                model=(result.model if result else model())[:60],
                prompt_version=PROMPT_VERSION,
                request_ms=result.request_ms if result else None,
                tokens_in=result.tokens_in if result else None,
                tokens_out=result.tokens_out if result else None,
                response={"answer": answer, "error": error, "fallback": bool(result and result.fallback)},
                created_at=datetime.now(UTC),
            )
        ).inserted_primary_key[0]


def recognise(s: db.Scope, mime: str, image: bytes, client=None) -> tuple[int, dict]:
    """(run id, the tidied answer). Raises trackerai_ai.AiError (also logged as a run without an answer)."""
    body = request(mime, image)
    try:
        result = trackerai_ai.ask(body, timeout=TIMEOUT_S, retries=RETRIES, fallbacks=body["model"] in FALLBACK_MODELS, client=client)
    except trackerai_ai.AiError as e:
        log_run(s, None, None, e.code)
        raise
    try:
        answer = tidy(result.json())
    except trackerai_ai.AiError as e:
        log_run(s, result, None, e.code)  # paid for, so with its tokens
        raise
    return log_run(s, result, answer), answer
