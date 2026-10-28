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


def test_edit_beat_keeps_backup_and_restores(library):
    c = TestClient(create_app(library, FakeJobs()))
    r = c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "frets": {"1": 3, "2": "x", "5": 0}})
    assert r.status_code == 200
    beat = gp.parse(str(library / "A - B.gp5")).tracks[0].measures[0].voices[0].beats[0]
    assert sorted((n.string, n.value, n.type.name) for n in beat.notes) == [
        (1, 3, "normal"), (2, 0, "dead"), (5, 0, "normal")]
    assert (library / "A - B.orig.gp5").exists()
    assert c.get("/api/songs").json()[0]["edited"] is True
    # clearing every string turns the beat into a rest
    c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "frets": {}})
    beat = gp.parse(str(library / "A - B.gp5")).tracks[0].measures[0].voices[0].beats[0]
    assert beat.status.name == "rest"
    c.post("/api/songs/abcdefghijk/restore")
    beat = gp.parse(str(library / "A - B.gp5")).tracks[0].measures[0].voices[0].beats[0]
    assert sorted(n.string for n in beat.notes) == [2, 3, 5]


def test_edit_rejects_bad_input(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.post("/api/songs/abcdefghijk/beats", json={"bar": 5, "beat": 0, "frets": {}}).status_code == 404
    assert c.post("/api/songs/abcdefghijk/beats", json={"bar": 0, "beat": 0, "frets": {"1": 30}}).status_code == 400


def test_convert_queues_only_youtube_links(library):
    c = TestClient(create_app(library, FakeJobs()))
    assert c.post("/api/convert", json={"url": "https://evil.example/x"}).status_code == 400
    job = c.post("/api/convert", json={"url": "https://www.youtube.com/watch?v=gHRmuLWp-z4"}).json()
    for _ in range(50):
        if c.get("/api/jobs").json()[0]["status"] == "done":
            break
        time.sleep(0.02)
    assert c.get("/api/jobs").json()[0] == {**job, "status": "done"}
