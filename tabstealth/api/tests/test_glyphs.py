"""Reading digits into frets: which glyphs form one number. Geometry as in a 1080p video (27 px between strings)."""

import numpy as np
from tabreader.glyphs import Glyph
from tabreader.parse import merge_multidigit

SP = 26.7


def digit(x0: int, w: int, label: str, y: int = 97):
    return Glyph(x0, y - 12, x0 + w, y + 12, np.zeros((24, 16), np.float32)), label, 0.99


def test_the_digits_of_12_are_one_fret_even_when_spaced_wider():
    # "<12>" from Locked Out of Heaven: the 1 ends 7 px before the 2 starts
    assert [n[1] for n in merge_multidigit([digit(6114, 9, "1"), digit(6130, 16, "2")], SP)] == ["12"]


def test_two_notes_on_one_string_stay_two_notes():
    # "0-1-0" with a short dash between: 15 px apart
    notes = merge_multidigit([digit(100, 16, "0"), digit(131, 9, "1"), digit(155, 16, "0")], SP)
    assert [n[1] for n in notes] == ["0", "1", "0"]


def test_tightly_spaced_notes_only_join_into_a_real_fret():
    # "12·11" on one string, 8 px between the 2 and the next 1: 1211 is no fret, so 12 and 11
    notes = merge_multidigit([digit(100, 9, "1"), digit(116, 16, "2"), digit(140, 9, "1"), digit(156, 9, "1")], SP)
    assert [n[1] for n in notes] == ["12", "11"]
