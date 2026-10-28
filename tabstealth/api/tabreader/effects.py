"""Detect playing techniques around the parsed notes: strums, arpeggios, slurs, slides."""
import cv2
import numpy as np

from .glyphs import Glyph, gray
from .parse import Column, Note, PageMeasure

BRUSH = 64  # GP stroke duration value for a quick strum
ARPEGGIO = 16  # slower roll for the wavy arpeggio sign


def _columns(measures: list[PageMeasure]) -> list[Column]:
    return [c for m in measures for c in m.columns]


def _column_right_of(cols: list[Column], x: float, sp: float) -> Column | None:
    cands = [c for c in cols if 0.2 * sp < c.x - x < 1.4 * sp]
    return min(cands, key=lambda c: c.x - x) if cands else None


def strums(ink: np.ndarray, lines: list[float], bars: list[int], cols: list[Column]) -> None:
    """Straight vertical arrows left of a chord. Head at the top (up arrow) = downstroke."""
    sp = (lines[-1] - lines[0]) / 5
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(1.3 * sp)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(vert)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        cx = x + w / 2
        if w > 4 or any(abs(cx - b) < 4 for b in bars):
            continue
        col = _column_right_of(cols, cx, sp)
        if col is None:
            continue
        # arrowhead: the end of the shaft where the ink is widest
        x0, x1 = int(cx - 0.35 * sp), int(cx + 0.35 * sp) + 1
        top = ink[max(0, y - 3):y + int(0.4 * sp), x0:x1].sum(axis=1).max()
        bot = ink[y + h - int(0.4 * sp):y + h + 3, x0:x1].sum(axis=1).max()
        if max(top, bot) < 5:
            continue  # plain line without a head
        mid = ink[y + int(0.4 * sp):y + h - int(0.4 * sp), x0:x1].sum(axis=1)
        if len(mid) and np.median(mid) > 4.5:
            col.stroke = ("down", ARPEGGIO)  # thick wavy line, not an arrow shaft
            continue
        col.stroke = ("down", BRUSH) if top > bot else ("up", BRUSH)


def arpeggios(ink_clean: np.ndarray, lines: list[float], cols: list[Column]) -> None:
    """Wavy vertical line left of a chord: a rolled chord (low to high)."""
    sp = (lines[-1] - lines[0]) / 5
    joined = cv2.dilate(ink_clean, np.ones((7, 1), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if h < 1.5 * sp or w > 0.6 * sp or w < 3:
            continue
        col = _column_right_of(cols, x + w / 2, sp)
        if col is not None and len(col.notes) >= 2 and col.stroke is None:
            col.stroke = ("down", ARPEGGIO)


def _note_near(notes: list[Note], string: int, x: float, sp: float) -> Note | None:
    c = [n for n in notes if n.string == string and abs(n.x - x) < 0.8 * sp]
    return min(c, key=lambda n: abs(n.x - x)) if c else None


def slurs(ink_clean: np.ndarray, lines: list[float], notes: list[Note]) -> None:
    """Arcs joining two notes on one string: tie (same fret) or hammer-on/pull-off.

    Guitar Pro draws the arc above the highest note of the column, not necessarily right
    above its own string, so we take the highest string below the arc whose notes sit
    under both ends of the arc.
    """
    sp = (lines[-1] - lines[0]) / 5
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink_clean)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if not (0.7 * sp < w < 4 * sp and 2 <= h < 0.7 * sp):
            continue
        if y + h < lines[0] - 1.3 * sp or y > lines[-1]:
            continue  # chord names / lyrics area
        for s in range(1, 7):
            if lines[s - 1] < y + h - 2:
                continue  # string above the arc
            a = _note_near(notes, s, x + 0.15 * w, sp)
            b = _note_near(notes, s, x + w - 0.15 * w, sp)
            if a is None or b is None or a is b or b.x <= a.x:
                continue
            if a.fret is not None and a.fret == b.fret and not a.grace:
                b.tied = True
            else:
                a.hammer = True
            break


def slides(slide_glyphs: list[Glyph], lines: list[float], notes: list[Note]) -> None:
    sp = (lines[-1] - lines[0]) / 5
    for g in slide_glyphs:
        s = int(np.argmin([abs(g.cy - ly) for ly in lines])) + 1
        left = [n for n in notes if n.string == s and n.x < g.cx and g.cx - n.x < 1.5 * sp]
        if left:
            max(left, key=lambda n: n.x).slide = True


def annotate(img: np.ndarray, ink_clean: np.ndarray, lines: list[float], bars: list[int],
             measures: list[PageMeasure], slide_glyphs: list[Glyph]) -> None:
    ink = (gray(img) < 150).astype(np.uint8)
    cols = _columns(measures)
    notes = [n for c in cols for n in c.notes + c.grace]
    strums(ink, lines, bars, cols)
    arpeggios(ink_clean, lines, cols)
    slurs(ink_clean, lines, notes)
    slides(slide_glyphs, lines, notes)
