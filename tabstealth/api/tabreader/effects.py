"""Detect playing techniques around the parsed notes: strums, arpeggios, slurs, slides."""

import re

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
        top = ink[max(0, y - 3) : y + int(0.4 * sp), x0:x1].sum(axis=1).max()
        bot = ink[y + h - int(0.4 * sp) : y + h + 3, x0:x1].sum(axis=1).max()
        if max(top, bot) < 5:
            continue  # plain line without a head
        mid = ink[y + int(0.4 * sp) : y + h - int(0.4 * sp), x0:x1].sum(axis=1)
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
    """Arcs joining notes on one string: a tie (same fret, nothing between) or hammer-ons/pull-offs.

    Guitar Pro draws the arc above the highest note of the column, not necessarily right
    above its own string, so we take the highest string below the arc whose notes sit
    under both ends of the arc. One arc can span several notes (0-1-0: hammer, then pull);
    a wider arc is also taller.
    """
    sp = (lines[-1] - lines[0]) / 5
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink_clean)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if not (0.7 * sp < w < 4 * sp and 2 <= h < max(0.7 * sp, 0.35 * w)):
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
            between = sorted((m for m in notes if m.string == s and a.x < m.x < b.x), key=lambda m: m.x)
            if a.fret is not None and a.fret == b.fret and not a.grace and not between:
                b.tied = True
            else:
                for m in [a, *between]:
                    m.hammer = True
            break


def grace_slurs(ink_clean: np.ndarray, lines: list[float], cols: list[Column]) -> int:
    """A grace note slurred into its main note ("2⌒4" with a small 2). The arc is short and crosses the staff line
    above, which line removal cuts it at, so it is no single component: look at the ink between the two notes for an
    arch instead (the farther from the middle, the lower the ink)."""
    sp = (lines[-1] - lines[0]) / 5
    found = 0
    for c in cols:
        for g in c.grace:
            m = next((n for n in c.notes if n.string == g.string), None)
            if m is None or g.slide or g.hammer or not 0.6 * sp < m.x - g.x < 2.5 * sp:
                continue
            if any(n.string == g.string - 1 and g.x - 0.3 * sp < n.x < m.x + 0.3 * sp for n in c.notes + c.grace):
                continue  # a note on the string above would look like a leg
            y = lines[g.string - 1]
            band = ink_clean[int(y - 1.1 * sp) : int(y - 0.55 * sp), int(g.x) : int(m.x)]
            if band.size == 0 or band.sum() > 0.6 * sp * sp:
                continue
            ys, xs = np.nonzero(band)
            wd = band.shape[1]
            if len(xs) < 8 or not (xs < 0.35 * wd).any() or not (xs > 0.65 * wd).any() or ys.min() == ys.max():
                continue
            if np.corrcoef(np.abs(xs - (wd - 1) / 2), ys)[0, 1] > 0.5:
                g.hammer = True
                found += 1
    return found


def slides(slide_glyphs: list[Glyph], lines: list[float], notes: list[Note]) -> None:
    sp = (lines[-1] - lines[0]) / 5
    for g in slide_glyphs:
        s = int(np.argmin([abs(g.cy - ly) for ly in lines])) + 1
        left = [n for n in notes if n.string == s and n.x < g.cx and g.cx - n.x < 1.5 * sp]
        if left:
            max(left, key=lambda n: n.x).slide = True


def annotate(
    img: np.ndarray, ink_clean: np.ndarray, lines: list[float], bars: list[int], measures: list[PageMeasure], slide_glyphs: list[Glyph]
) -> None:
    ink = (gray(img) < 150).astype(np.uint8)
    cols = _columns(measures)
    notes = [n for c in cols for n in c.notes + c.grace]
    strums(ink, lines, bars, cols)
    arpeggios(ink_clean, lines, cols)
    slurs(ink_clean, lines, notes)
    slides(slide_glyphs, lines, notes)
    grace_slurs(ink_clean, lines, cols)
    vibrato(ink_clean, lines, cols)
    parentheses(cols)


def parentheses(cols: list[Column]) -> None:
    """A fret in parentheses is usually a tied note in these tabs ("3 ⌒ (3)": still ringing), not a ghost note: it
    is a tie when the note before it on that string has the same fret (or a tie arc already said so)."""
    last: dict[int, Note] = {}
    for c in cols:
        for n in c.notes:
            if n.ghost:
                prev = last.get(n.string)
                if n.tied or (prev is not None and prev.fret == n.fret):
                    n.ghost, n.tied = False, True
            last[n.string] = n


PALM_MUTE = re.compile(r"^P\.?M\.?$", re.I)
HARMONIC = re.compile(r"^(N\.?H\.?|Harm\.?)$", re.I)
BENDS = {"full": 100, "1/2": 50, "½": 50, "1/4": 50, "¼": 50}


def _dashes_end(ink: np.ndarray, y: int, x: int, sp: float) -> int:
    """Where the dashed line after a label (P.M. - - - -|) ends: follow ink on that row across small gaps."""
    row = ink[max(0, y - 2) : y + 3].max(axis=0)
    end, gap = x, 0
    for xx in range(x, min(len(row), x + int(40 * sp))):
        if row[xx]:
            end, gap = xx, 0
        else:
            gap += 1
            if gap > 1.2 * sp:
                break
    return end


def text_marks(words: list[tuple[int, int, int, int, str]], ink: np.ndarray, lines: list[float], cols: list[Column]) -> dict[str, int]:
    """Palm mute, harmonics and bends from the words Guitar Pro writes above the staff. Returns counts."""
    sp = (lines[-1] - lines[0]) / 5
    found = {"palm_mute": 0, "harmonic": 0, "bend": 0}
    for x, y, w, h, text in words:
        word = text.strip(" .:-").replace(" ", "")
        if PALM_MUTE.match(text.strip()) or HARMONIC.match(text.strip()):
            kind = "palm_mute" if PALM_MUTE.match(text.strip()) else "harmonic"
            end = max(x + w + sp, _dashes_end(ink, y + h // 2, x + w, sp))
            for c in cols:
                if x - 0.3 * sp <= c.x <= end + 0.3 * sp:
                    for n in c.notes:
                        setattr(n, kind, True)
                        found[kind] += 1
        elif word.lower() in BENDS:
            # the bend arrow rises from the note to its label: the column just left of (or under) the word
            cands = [c for c in cols if x + w / 2 - 2.0 * sp <= c.x <= x + w / 2 + 0.3 * sp and c.notes]
            if cands:
                col = max(cands, key=lambda c: c.x)
                note = min(col.notes, key=lambda n: n.string)  # the highest string: where the arrow starts
                note.bend = BENDS[word.lower()]
                found["bend"] += 1
    return found


def vibrato(ink_clean: np.ndarray, lines: list[float], cols: list[Column]) -> int:
    """A wavy line just above the staff: vibrato on the highest note of the column it starts at."""
    sp = (lines[-1] - lines[0]) / 5
    y0, y1 = max(0, int(lines[0] - 1.6 * sp)), int(lines[0] - 0.15 * sp)
    band = ink_clean[y0:y1]
    n, lab, st, _ = cv2.connectedComponentsWithStats(band)
    count = 0
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if w < 0.9 * sp or h > 0.45 * sp or h < 3:
            continue
        mask = lab[y : y + h, x : x + w] == i
        top = np.array([np.argmax(col) if col.any() else -1 for col in mask.T], dtype=float)
        top = top[top >= 0]
        if len(top) < 6:
            continue
        d = np.sign(np.diff(np.convolve(top, np.ones(3) / 3, mode="valid")))
        d = d[d != 0]
        turns = int((np.diff(d) != 0).sum())
        if turns < 4:  # one hump is a slur arc, not a wave
            continue
        near = [c for c in cols if abs(c.x - x) < 0.8 * sp and c.notes]
        if near:
            col = min(near, key=lambda c: abs(c.x - x))
            min(col.notes, key=lambda nn: nn.string).vibrato = True
            count += 1
    return count
