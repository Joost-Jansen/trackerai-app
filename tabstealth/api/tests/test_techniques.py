"""Techniques read from the marks Guitar Pro draws around the tab: palm mute, bends, harmonics, vibrato.

The test videos have no P.M., bends or vibrato, so these use drawn marks with the real geometry (27 px between
strings, as in a 1080p video)."""
import cv2
import numpy as np

from tabreader.effects import text_marks, vibrato
from tabreader.parse import Column, Note

LINES = [100.0 + 27 * i for i in range(6)]


def columns(xs, strings=(1, 3)):
    return [Column(x=x, notes=[Note(s, 2, x=x) for s in strings]) for x in xs]


def test_palm_mute_covers_the_label_and_its_dashes():
    ink = np.zeros((300, 900), np.uint8)
    for x in range(140, 460, 18):  # "P.M. - - - - -" ends at x 460
        ink[60:62, x:x + 9] = 1
    cols = columns([110, 250, 440, 700])
    found = text_marks([(100, 52, 36, 16, "P.M.")], ink, LINES, cols)
    assert [all(n.palm_mute for n in c.notes) for c in cols] == [True, True, True, False]
    assert found["palm_mute"] == 6


def test_bend_label_marks_the_note_it_rises_from():
    cols = columns([200, 400])
    text_marks([(415, 50, 30, 14, "full")], np.zeros((300, 900), np.uint8), LINES, cols)
    bent = {(c.x, n.string): n.bend for c in cols for n in c.notes if n.bend}
    assert bent == {(400, 1): 100}
    text_marks([(215, 50, 26, 14, "1/2")], np.zeros((300, 900), np.uint8), LINES, cols)
    assert cols[0].notes[0].bend == 50


def test_chord_names_and_other_words_change_nothing():
    cols = columns([200, 400])
    found = text_marks([(190, 30, 40, 18, "Am7"), (390, 30, 40, 18, "Capo")], np.zeros((300, 900), np.uint8), LINES, cols)
    assert found == {"palm_mute": 0, "harmonic": 0, "bend": 0}


def test_vibrato_is_a_wave_and_a_slur_arc_is_not():
    ink = np.zeros((300, 900), np.uint8)
    xs = np.arange(200, 290)
    ys = (88 + 3 * np.sin((xs - 200) / 5)).astype(int)  # a wavy line just above the top string
    for x, y in zip(xs, ys):
        cv2.circle(ink, (int(x), int(y)), 1, 1, -1)
    cv2.ellipse(ink, (500, 92), (30, 6), 0, 180, 360, 1, 2)  # one hump: a slur
    cols = columns([200, 480])
    assert vibrato(ink, LINES, cols) == 1
    assert cols[0].notes[0].vibrato and not cols[1].notes[0].vibrato
