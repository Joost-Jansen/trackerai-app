"""The API on a temporary library: listing, timing, beat edits with backup and restore, the convert queue."""
import json
import time

import guitarpro as gp
import pytest
from fastapi.testclient import TestClient

from app import Jobs, create_app
from tabreader.assemble import TICKS_PER_QUARTER as Q, Beat, Measure, Song
from tabreader.export import Meta, write_gp5
from tabreader.parse import Column, Note


@pytest.fixture
def library(tmp_path):
    chord = Column(x=0, notes=[Note(2, 2), Note(3, 2), Note(5, 0)])
    song = Song([Measure(1, [Beat(0, 2 * Q, chord), Beat(2 * Q, 2 * Q)])], 80, 4, 4)
    write_gp5(song, str(tmp_path / "A - B.gp5"), Meta(title="B", artist="A"))
    (tmp_path / "A - B.timing.json").write_text(json.dumps({"video": "abcdefghijk", "measure_starts": [1.5]}))
    (tmp_path / "A - B.txt").write_text("tab")
    (tmp_path / "index.json").write_text(json.dumps({"abcdefghijk": {
        "file": "A - B.gp5", "timing": "A - B.timing.json", "text": "A - B.txt", "title": "B", "artist": "A"}}))
    return tmp_path


class FakeJobs(Jobs):
    def __init__(self):
        super().__init__(runner=lambda job: True)


def test_songs_and_timing(library):
    c = TestClient(create_app(library, FakeJobs()))
    songs = c.get("/api/songs").json()
    assert songs[0]["video"] == "abcdefghijk" and songs[0]["edited"] is False
    assert c.get("/api/songs/abcdefghijk/timing").json()["measure_starts"] == [1.5]
    assert c.get("/api/songs/nope/timing").status_code == 404


def beat0(library):
    return gp.parse(str(library / "A - B.gp5")).tracks[0].measures[0].voices[0].beats[0]


def test_edit_beat_keeps_backup_and_restores(library):
    c = TestClient(create_app(library, FakeJobs()))
    r = c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"1": {"fret": 3}, "2": {"fret": "x"}, "5": {"fret": 0}}})
    assert r.status_code == 200
    assert sorted((n.string, n.value, n.type.name) for n in beat0(library).notes) == [
        (1, 3, "normal"), (2, 0, "dead"), (5, 0, "normal")]
    assert (library / "A - B.orig.gp5").exists()
    assert c.get("/api/songs").json()[0]["edited"] is True
    # no notes at all turns the beat into a rest
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {}})
    assert beat0(library).status.name == "rest"
    c.post("/api/songs/abcdefghijk/restore")
    assert sorted(n.string for n in beat0(library).notes) == [2, 3, 5]


def test_every_technique_round_trips(library):
    c = TestClient(create_app(library, FakeJobs()))
    body = {"bar": 0, "beat": 0, "stroke": "arpeggio", "chord": "Dsus2", "notes": {
        "1": {"fret": 2, "hammer": True, "let_ring": True, "grace": {"fret": 0, "hammer": True}},
        "2": {"fret": 3, "slide": True, "vibrato": True, "grace": {"fret": "x", "slide": True}},
        "3": {"fret": 2, "tie": True, "palm_mute": True},
        "4": {"fret": 12, "harmonic": True, "ghost": True},
    }}
    assert c.post("/api/songs/abcdefghijk/beats", json=body).status_code == 200
    b = beat0(library)
    n = {x.string: x for x in b.notes}
    assert n[1].effect.hammer and n[1].effect.letRing and n[1].effect.grace.fret == 0
    assert n[1].effect.grace.transition.name == "hammer"
    assert n[2].effect.slides and n[2].effect.vibrato and n[2].effect.grace.isDead
    assert n[2].effect.grace.transition.name == "slide"
    assert n[3].type.name == "tie" and n[3].effect.palmMute
    assert n[4].effect.harmonic is not None and n[4].effect.ghostNote and n[4].value == 12
    assert b.effect.stroke.value == 16 and b.text == "Dsus2"
    # reading the beat back gives the same form
    got = c.get("/api/songs/abcdefghijk/beats/0/0").json()
    assert got["stroke"] == "arpeggio" and got["chord"] == "Dsus2"
    assert got["notes"]["1"]["grace"] == {"fret": 0, "slide": False, "hammer": True}
    assert got["notes"]["2"]["grace"]["fret"] == "x" and got["notes"]["2"]["slide"] is True
    assert got["notes"]["3"]["tie"] and got["notes"]["4"]["harmonic"] and got["notes"]["4"]["fret"] == 12
    assert c.get("/api/songs/abcdefghijk/beats/0/9").status_code == 404
    # switching techniques off clears them
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "stroke": "up", "notes": {"1": {"fret": 2}}})
    b = beat0(library)
    e = b.notes[0].effect
    assert not (e.hammer or e.letRing or e.slides or e.grace) and b.text is None
    assert b.effect.stroke.direction.name == "up" and b.effect.stroke.value == 64


def test_effects_the_form_does_not_show_are_kept(library):
    song = gp.parse(str(library / "A - B.gp5"))
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    note.effect.staccato = True
    note.effect.trill = gp.TrillEffect(fret=5, duration=gp.Duration(value=16))
    gp.write(song, str(library / "A - B.gp5"), version=(5, 1, 0))
    c = TestClient(create_app(library, FakeJobs()))
    s = note.string
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {str(s): {"fret": 4}}})
    kept = [n for n in beat0(library).notes if n.string == s][0]
    assert kept.value == 4 and kept.effect.staccato and kept.effect.trill.fret == 5


def test_section_and_text_tab(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.post("/api/songs/abcdefghijk/bars", json={"bar": 0, "section": "Chorus"}).status_code == 200
    assert gp.parse(str(library / "A - B.gp5")).measureHeaders[0].marker.title == "Chorus"
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "chord": "Am", "stroke": "down",
                                                 "notes": {"2": {"fret": 1, "hammer": True}, "6": {"fret": "x"}}})
    text = c.get("/api/songs/abcdefghijk/text").text
    assert "1 Chorus" in text and "Am" in text and "^" in text
    assert "B|1" in text and "E|x" in text
    c.post("/api/songs/abcdefghijk/bars", json={"bar": 0, "section": ""})
    assert gp.parse(str(library / "A - B.gp5")).measureHeaders[0].marker is None


def test_edit_rejects_bad_input(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.post("/api/songs/abcdefghijk/beats", json={"bar": 5, "beat": 0, "notes": {}}).status_code == 404
    assert c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"1": {"fret": 30}}}).status_code == 400
    assert c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"7": {"fret": 1}}}).status_code == 422
    assert c.post("/api/songs/abcdefghijk/bars", json={"bar": 9, "section": "x"}).status_code == 404
    assert not (library / "A - B.orig.gp5").exists()  # nothing changed, so nothing counts as edited


def test_convert_queues_only_youtube_links(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.post("/api/convert", json={"url": "https://evil.example/x"}).status_code == 400
    job = c.post("/api/convert", json={"url": "https://www.youtube.com/watch?v=gHRmuLWp-z4"}).json()
    for _ in range(50):
        if c.get("/api/jobs").json()[0]["status"] == "done":
            break
        time.sleep(0.02)
    assert c.get("/api/jobs").json()[0] == {**job, "status": "done"}


def test_undo_redo_and_restore(library):
    c = TestClient(create_app(library, FakeJobs()))
    frets = lambda: sorted((n.string, n.value) for n in beat0(library).notes)
    original = frets()
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"1": {"fret": 5}}})
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"1": {"fret": 7}}})
    assert frets() == [(1, 7)]
    assert c.get("/api/songs/abcdefghijk/history").json() == {"undo": 2, "redo": 0}
    assert c.post("/api/songs/abcdefghijk/undo").json() == {"undo": 1, "redo": 1}
    assert frets() == [(1, 5)]
    c.post("/api/songs/abcdefghijk/undo")
    assert frets() == original
    assert c.get("/api/songs").json()[0]["edited"] is False  # back to the converter's version
    assert c.post("/api/songs/abcdefghijk/undo").status_code == 409
    c.post("/api/songs/abcdefghijk/redo")
    c.post("/api/songs/abcdefghijk/redo")
    assert frets() == [(1, 7)]
    # restoring the original is a change of its own: undo brings the edit back
    c.post("/api/songs/abcdefghijk/restore")
    assert frets() == original
    c.post("/api/songs/abcdefghijk/undo")
    assert frets() == [(1, 7)]
    # a new change empties redo
    c.post("/api/songs/abcdefghijk/undo")
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"2": {"fret": 1}}})
    assert c.get("/api/songs/abcdefghijk/history").json()["redo"] == 0


def test_bend(library):
    c = TestClient(create_app(library, FakeJobs()))
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"3": {"fret": 7, "bend": 100}, "2": {"fret": 8, "bend": 50}}})
    n = {x.string: x for x in beat0(library).notes}
    assert max(p.value for p in n[3].effect.bend.points) == 2 and max(p.value for p in n[2].effect.bend.points) == 1
    got = c.get("/api/songs/abcdefghijk/beats/0/0").json()["notes"]
    assert got["3"]["bend"] == 100 and got["2"]["bend"] == 50
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "notes": {"3": {"fret": 7}}})
    assert beat0(library).notes[0].effect.bend is None


def test_song_meta(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.get("/api/songs").json()[0]["status"] == "new"
    c.patch("/api/songs/abcdefghijk", json={"status": "learning", "tags": [" Fingerstyle", "capo", "capo", ""], "favourite": True})
    s = c.get("/api/songs").json()[0]
    assert (s["status"], s["tags"], s["favourite"]) == ("learning", ["capo", "fingerstyle"], True)
    assert c.patch("/api/songs/abcdefghijk", json={"status": "done"}).status_code == 422
    assert c.patch("/api/songs/nope", json={"favourite": True}).status_code == 404


def test_practice_log_and_summary(library):
    c = TestClient(create_app(library, FakeJobs()))
    log = lambda day, sec, speed, whole=False: c.post("/api/practice", json={
        "video": "abcdefghijk", "day": day, "seconds": sec, "speed": speed, "source": "tab", "whole_song": whole})
    assert log("2026-10-26", 120, 0.6).status_code == 200
    log("2026-10-27", 300, 0.8, True)
    log("2026-10-28", 60, 1.0)
    log("2026-10-28", 30, 0.9, True)
    assert c.post("/api/practice", json={"video": "nope", "day": "2026-10-28", "seconds": 5, "speed": 1, "source": "tab"}).status_code == 404
    assert c.post("/api/practice", json={"video": "abcdefghijk", "day": "28-10-2026", "seconds": 5, "speed": 1, "source": "tab"}).status_code == 422
    p = c.get("/api/practice", params={"today": "2026-10-28"}).json()
    assert p["total_seconds"] == 510 and p["streak"] == 3
    assert p["days"][-1] == {"day": "2026-10-28", "seconds": 90}
    assert p["songs"][0]["best_speed"] == 0.9 and p["songs"][0]["last"] == "2026-10-28"
    assert [x["speed"] for x in p["speed"]["abcdefghijk"]] == [0.6, 0.8, 1.0]
    # not practised today yet: the streak runs up to yesterday
    assert c.get("/api/practice", params={"today": "2026-10-29"}).json()["streak"] == 3
    assert c.get("/api/practice", params={"today": "2026-10-31"}).json()["streak"] == 0
    s = c.get("/api/songs").json()[0]
    assert s["practised_seconds"] == 510 and s["last_practised"] == "2026-10-28"


def test_review_queue(library):
    (library / "A - B.review.json").write_text(json.dumps([{"bar": 0, "reasons": ["timing", "low_confidence"]}]))
    idx = json.loads((library / "index.json").read_text())
    idx["abcdefghijk"]["review"] = "A - B.review.json"
    (library / "index.json").write_text(json.dumps(idx))
    c = TestClient(create_app(library, FakeJobs()))
    assert c.get("/api/songs").json()[0]["to_review"] == 1
    assert c.get("/api/songs/abcdefghijk/review").json() == [{"bar": 0, "reasons": ["timing", "low_confidence"], "checked": False}]
    assert c.post("/api/songs/abcdefghijk/review", json={"bar": 0, "checked": True}).json()[0]["checked"] is True
    assert c.get("/api/songs").json()[0]["to_review"] == 0
    c.post("/api/songs/abcdefghijk/review", json={"bar": 0, "checked": False})
    assert c.get("/api/songs").json()[0]["to_review"] == 1
