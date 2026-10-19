"""Photo to draft meal (tools/nutrition/photos.py, recognize.py, match.py), Open Food Facts (off.py) and favourites.

Claude is never called: RECORDED is an answer in the shape the structured output returns. One live test runs only with
NUTRITION_LIVE_TEST=1 and ANTHROPIC_API_KEY (it costs a call).
"""

import json
import os
import struct
from pathlib import Path

import pytest

from tools import db
from tools.nutrition import foods, match, meals, nevo, off, photos, recognize

SAMPLE = (Path(__file__).parent / "nevo_sample.csv").read_bytes()
RECORDED = {
    "items": [
        {"label_nl": "havermout", "label_en": "oat flakes", "kind": "food", "grams": 65, "grams_low": 50, "grams_high": 80,
         "confidence": 0.9, "cooking": "", "search_terms": ["havermout"]},
        {"label_nl": "banaan", "label_en": "banana", "kind": "food", "grams": 110, "grams_low": 90, "grams_high": 130,
         "confidence": 0.55, "cooking": "raw", "search_terms": ["banaan"]},
        {"label_nl": "halfvolle melk", "label_en": "semi-skimmed milk", "kind": "drink", "grams": 200, "grams_low": 150,
         "grams_high": 250, "confidence": 0.8, "cooking": "", "search_terms": ["melk halfvolle", "melk"]},
    ],
    "hidden_extras": [{"label_nl": "olijfolie", "label_en": "olive oil", "grams": 5, "search_terms": ["olie olijf"]}],
    "reference_object": "bowl",
    "moment_guess": "breakfast",
}


@pytest.fixture
def s(tmp_path):
    e = db.connect(f"sqlite:///{tmp_path / 'm.db'}")
    db.create_schema(e)
    foods.invalidate()
    nevo.import_foods(e, nevo.csv_text(SAMPLE))
    return db.Scope(e, 1)


def jpeg(with_exif=True) -> bytes:
    seg = lambda marker, body: b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body  # noqa: E731
    parts = [b"\xff\xd8", seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")]
    if with_exif:
        parts += [seg(0xE1, b"Exif\x00\x00GPS 52.09N 5.12E"), seg(0xFE, b"a comment")]
    parts += [seg(0xDB, b"\x00" + bytes(64)), seg(0xDA, b"\x01\x01\x00\x00\x3f\x00"), b"\x12\x34\xff\x00\x56", b"\xff\xd9"]
    return b"".join(parts)


def test_photos_lose_their_metadata_and_only_images_pass():
    mime, clean = photos.clean(jpeg())
    assert mime == "image/jpeg" and b"Exif" not in clean and b"GPS" not in clean and b"comment" not in clean
    assert clean == jpeg(with_exif=False)  # everything else, the scan data too, unchanged
    png = b"\x89PNG\r\n\x1a\n" + b"".join(struct.pack(">I", len(d)) + n + d + b"\x00\x00\x00\x00"
                                       for n, d in ((b"IHDR", bytes(13)), (b"tEXt", b"GPS\x0052N"), (b"IDAT", b"xx"), (b"IEND", b"")))
    assert photos.clean(png)[0] == "image/png" and b"GPS" not in photos.clean(png)[1]
    for bad in (b"", b"GIF89a....", b"\xff\xd8\xff\xe1\x00\x02"):
        with pytest.raises(photos.PhotoError):
            photos.clean(bad)


def test_photo_keeping_follows_the_setting(s):
    from datetime import datetime, timedelta, timezone

    mime, data = photos.clean(jpeg())
    assert photos.save(s, mime, data, "never") is None
    kept, month, orphan = (photos.save(s, mime, data, k) for k in ("keep", "30d", "keep"))
    assert photos.load(s, kept)[1] == data and photos.load(db.Scope(s.engine, 2), kept) is None
    for pid, keep in ((kept, "keep"), (month, "30d")):  # claimed by a saved meal
        meals.create(s, day="2026-10-19", eaten_at="08:00", moment="breakfast", input="photo", photo_id=pid,
                     items=[{"food_ref": "nevo:9001", "grams": 60}])
        photos.attach(s, pid, keep)
    now = datetime.now(timezone.utc)
    assert photos.purge_expired(s.engine, now + timedelta(days=2)) == 1  # the photo of a cancelled review: a day
    assert photos.load(s, orphan) is None and photos.load(s, month) and photos.load(s, kept)
    assert photos.purge_expired(s.engine, now + timedelta(days=31)) == 1
    assert photos.load(s, month) is None and photos.load(s, kept)
    assert meals.between(s, "2026-10-19", "2026-10-19")[1]["photo_id"] is None  # the meal stays, without its photo
    photos.retention_changed(s, "never")
    assert photos.load(s, kept) is None


def test_the_answer_is_kept_within_bounds():
    answer = recognize.tidy({"items": [
        {"label_nl": "pasta", "kind": "x", "grams": 99999, "grams_low": 10, "grams_high": 5, "confidence": 7, "search_terms": []},
        {"label_nl": " ", "grams": 10},
    ], "hidden_extras": [], "reference_object": "spoon", "moment_guess": "brunch"})
    (item,) = answer["items"]
    assert item["kind"] == "food" and item["grams"] == 3000 and item["grams_low"] == 5 and item["grams_high"] == 3000
    assert item["confidence"] == 1 and item["search_terms"] == ["pasta"]
    assert answer["reference_object"] == "none" and answer["moment_guess"] is None


def test_the_request_asks_for_structured_output_with_the_image(monkeypatch):
    monkeypatch.delenv("NUTRITION_MODEL", raising=False)
    body = recognize.request("image/jpeg", b"img")
    assert body["model"] == recognize.DEFAULT_MODEL and body["output_config"]["format"]["schema"] is recognize.SCHEMA
    assert body["messages"][0]["content"][0]["source"]["data"] == "aW1n" and "tool_choice" not in body
    monkeypatch.setenv("NUTRITION_MODEL", "claude-haiku-5-5")
    assert recognize.request("image/jpeg", b"img")["model"] == "claude-haiku-5-5"


class Stub:
    def __init__(self, answer):
        text = json.dumps(answer)
        msg = {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
               "usage": {"input_tokens": 1500, "output_tokens": 300}}
        create = lambda **kw: type("R", (), {"to_dict": lambda self: msg})()  # noqa: E731
        self.messages = type("M", (), {"create": staticmethod(create)})()
        self.beta = type("B", (), {"messages": self.messages})()


def test_recognise_logs_the_run_and_the_draft_matches_foods(s):
    run_id, answer = recognize.recognise(s, "image/jpeg", b"img", client=Stub(RECORDED))
    with s.engine.connect() as c:
        run = c.execute(db.nutrition_ai_runs.select()).mappings().one()
    assert run["id"] == run_id and (run["tokens_in"], run["tokens_out"], run["prompt_version"]) == (1500, 300, "1")
    assert run["response"]["answer"]["items"][0]["label_nl"] == "havermout"
    d = match.draft(s, answer)
    oats, banana, milk = d["items"]
    assert oats["food"]["ref"] == "nevo:9001" and oats["grams"] == 65 and oats["grams_source"] == "ai"
    assert milk["food"]["unit"] == "ml"  # a drink prefers a food measured in ml
    assert [a["ref"] for a in banana["alternatives"]][:2] == ["nevo:9002", "nevo:9006"]
    assert d["hidden_extras"][0]["food"]["ref"] == "nevo:9007" and d["moment_guess"] == "breakfast"


def test_an_unsure_estimate_takes_your_usual_portion(s):
    meals.create(s, day="2026-10-18", eaten_at="08:00", moment="breakfast", input="search", items=[{"food_ref": "nevo:9002", "grams": 120}])
    d = match.draft(s, recognize.tidy(RECORDED))
    oats, banana, _ = d["items"]
    assert (banana["grams"], banana["grams_ai"], banana["grams_source"]) == (120, 110, "memory")  # confidence 0.55
    assert banana["grams_low"] == 90 and banana["alternatives"][0]["portion_g"] == 120
    assert oats["grams_source"] == "ai"  # sure enough, no memory either


def test_failures_are_logged_too(s):
    stub = Stub(RECORDED)
    stub.messages.create = lambda **kw: type("R", (), {"to_dict": lambda self: {"content": [], "stop_reason": "refusal", "usage": {}}})()
    stub.beta.messages = stub.messages
    with pytest.raises(recognize.trackerai_ai.AiError):
        recognize.recognise(s, "image/jpeg", b"img", client=stub)
    with s.engine.connect() as c:
        assert c.execute(db.nutrition_ai_runs.select()).mappings().one()["response"]["error"] == "refused"


def test_open_food_facts_mapping_and_cache(s):
    product = {"product_name": "Skyr naturel", "brands": "Arla, X", "product_quantity_unit": "g", "nutrition_data_per": "100g",
               "serving_quantity": "150", "nutriments": {"energy-kcal_100g": 63, "proteins_100g": 11, "carbohydrates_100g": 4,
                                                         "fat_100g": 0.2, "sodium_100g": 0.04, "calcium_100g": 0.12, "vitamin-d_100g": 0.0000002}}
    calls = []
    fetcher = lambda ean: calls.append(ean) or product  # noqa: E731
    assert off.valid_ean("8710400011234") is False and off.valid_ean("4006381333931") is True
    food = off.lookup(s, "4006381333931", fetcher)
    p = food["per_100"]
    assert (food["ref"], food["brand"], food["default_portion_g"], food["source"]) == ("off:4006381333931", "Arla", 150, "off")
    assert (p["sodium_mg"], p["salt_g"], p["calcium_mg"], p["vit_d_ug"], p["fiber_g"]) == (40, 0.1, 120, 0.2, None)
    assert off.lookup(s, "4006381333931", fetcher)["name"] == "Skyr naturel" and calls == ["4006381333931"]  # cached
    assert foods.search(s, "skyr")[0]["ref"] == "off:4006381333931"
    with pytest.raises(off.NoNutrients):
        off.lookup(s, "5000112637922", lambda ean: {"product_name": "Water", "nutriments": {}})
    beer = off.to_food("1", {"product_name": "Pils", "product_quantity_unit": "ml", "nutriments": {"energy-kcal_100g": 42, "alcohol_100g": 5}})
    assert beer["unit"] == "ml" and beer["per_100"]["alcohol_g"] == 3.945  # 5 % vol x 0.789 g/ml
    assert off.to_food("1", {"product_name": "No energy", "nutriments": {}}) is None


def test_favourites_and_again(s):
    t = meals.create_template(s, name="Ontbijt", moment="breakfast", items=[{"food_ref": "nevo:9001", "grams": 60}])
    meals.create_template(s, name="Lunch", moment="lunch", items=[{"food_ref": "nevo:9004", "grams": 70}])
    assert t["items"] == [{"food_ref": "nevo:9001", "name": "Havermout", "unit": "g", "grams": 60}]
    assert [x["name"] for x in meals.change_template(s, t["id"], position=1) and meals.templates(s)] == ["Lunch", "Ontbijt"]
    meals.create(s, day="2026-10-18", eaten_at="08:00", moment="breakfast", input="search", items=[{"food_ref": "nevo:9002", "grams": 120}])
    out = meals.again(s, "2026-10-19", "breakfast")
    assert [f["name"] for f in out["favourites"]] == ["Ontbijt", "Lunch"] and len(out["yesterday"]) == 1
    assert meals.templates(db.Scope(s.engine, 2)) == [] and not meals.delete_template(db.Scope(s.engine, 2), t["id"])
    with pytest.raises(meals.MealError):
        meals.create_template(s, name=" ", items=[{"food_ref": "nevo:9001", "grams": 60}])


@pytest.mark.skipif(os.environ.get("NUTRITION_LIVE_TEST") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="live call to Claude: NUTRITION_LIVE_TEST=1 and ANTHROPIC_API_KEY")
def test_live_photo(s):  # pragma: no cover - by hand, with a meal photo in NUTRITION_LIVE_PHOTO
    data = Path(os.environ["NUTRITION_LIVE_PHOTO"]).read_bytes()
    mime, image = photos.clean(data)
    _, answer = recognize.recognise(s, mime, image)
    assert answer["items"]
