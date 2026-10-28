"""Pass 3: parse a clean page image into measures, beats and notes."""
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .glyphs import Glyph, find_barlines, gray, note_glyphs, number_glyphs, remove_lines

PROTOS = Path(__file__).parent / "assets" / "glyph_protos.npz"


class Classifier:
    """Nearest-prototype glyph classifier (normalised correlation)."""

    def __init__(self, path: Path = PROTOS):
        d = np.load(path)
        b = d["bitmaps"].reshape(len(d["bitmaps"]), -1).astype(np.float32)
        b = (b - b.mean(1, keepdims=True)) / (b.std(1, keepdims=True) + 1e-6)
        self.protos = b
        self.labels = d["labels"]

    def __call__(self, g: Glyph) -> tuple[str, float]:
        v = g.bitmap.ravel()
        v = (v - v.mean()) / (v.std() + 1e-6)
        s = self.protos @ v / len(v)
        i = int(np.argmax(s))
        return str(self.labels[i]), float(s[i])


@dataclass
class Note:
    string: int  # 1 = high e
    fret: int | None  # None for a dead note (X)
    grace: bool = False
    x: float = 0.0
    score: float = 1.0
    hammer: bool = False  # hammer-on / pull-off to the next note on this string
    slide: bool = False  # slide to the next note on this string
    tied: bool = False  # continues the previous note on this string
    harmonic: bool = False  # natural harmonic, drawn as <12>
    ghost: bool = False  # ghost note, drawn as (3)
    palm_mute: bool = False
    vibrato: bool = False
    bend: int = 0  # 0, 50 (half) or 100 (full)

    @property
    def dead(self) -> bool:
        return self.fret is None


@dataclass
class Column:
    x: float
    notes: list[Note]
    grace: list[Note] = field(default_factory=list)  # grace notes played just before
    stroke: tuple[str, int] | None = None  # ("down"|"up", GP stroke duration value)
    chord: str | None = None


@dataclass
class PageMeasure:
    number: int | None
    x0: int
    x1: int
    complete: bool
    columns: list[Column]


@dataclass
class ParsedPage:
    bars: list[int]
    measures: list[PageMeasure]
    numbers: dict[int, int]  # bar x -> measure number read above it


DIGITS = set("0123456789")


def read_number(img, lines, bar_x, clf: Classifier) -> int | None:
    gl = number_glyphs(img, lines, bar_x)
    s = ""
    for g in gl:
        lab, sc = clf(g)
        if lab in DIGITS and sc > 0.55:
            s += lab
    return int(s) if s else None


def merge_multidigit(notes: list[tuple[Glyph, str, float]], sp: float):
    """Join digit glyphs that sit side by side on the same string into one number.

    Over seven videos the digits of one number sit 0.15-0.30 staff spaces apart and separate notes 0.55 or more, so
    0.42 splits the two cleanly (0.25 split "12" into the notes 1 and 2 in some videos)."""
    notes.sort(key=lambda t: (round(t[0].cy / sp), t[0].x0))
    out: list[list] = []
    for g, lab, sc in notes:
        if (out and lab in DIGITS and out[-1][1][-1] in DIGITS
                and abs(out[-1][0].cy - g.cy) < 0.2 * sp
                and 0 <= g.x0 - out[-1][3] < 0.42 * sp):
            out[-1][1] += lab
            out[-1][3] = g.x1
            out[-1][2] = min(out[-1][2], sc)
            out[-1][4] = (out[-1][0].x0 + g.x1) / 2
        else:
            out.append([g, lab, sc, g.x1, g.cx])
    return out


def bracketed(clean: np.ndarray, x0: int, x1: int, y0: int, y1: int, sp: float) -> bool:
    """True when a curved stroke as tall as the digit stands right beside it: "(3)".

    The parentheses often touch the tie arc that leads into them, so they are not glyphs of their own; this looks at
    the ink beside the digit instead. Per row it takes the ink nearest the digit, which leaves out the arc: a "("
    is farther away in the middle than at its ends, a ")" mirrors that, a slide's slash or a 1 is not curved."""
    w = int(0.4 * sp)

    def side(a: int, b: int, sign: int) -> bool:
        win = clean[y0:y1, max(0, a):max(0, b)]
        if win.shape[1] < 3 or win.any(axis=1).mean() < 0.8:
            return False
        near = np.array([(np.nonzero(r)[0].max() if sign < 0 else np.nonzero(r)[0].min()) if r.any() else np.nan
                         for r in win], float)
        h = len(near)
        band = lambda p, q: np.nanmedian(near[int(p * h):max(int(q * h), int(p * h) + 1)])
        bulge = (band(0, 0.2) + band(0.8, 1)) / 2 - band(0.4, 0.6)  # > 0: the middle lies left of the ends
        return -sign * bulge > 0.15 * win.shape[1]

    return side(x0 - w, x0 - 1, -1) or side(x1 + 1, x1 + w, 1)


def find_rests(clean: np.ndarray, lines: list[float]) -> list[float]:
    """x of rest symbols: compact glyphs centred on the staff, between the strings."""
    sp = (lines[-1] - lines[0]) / 5
    mid = (lines[2] + lines[3]) / 2
    n, _, st, _ = cv2.connectedComponentsWithStats(clean)
    xs = []
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if (abs(y + h / 2 - mid) < 0.6 * sp and 1.2 * sp <= h <= 3.0 * sp
                and 0.45 * sp <= w <= 1.0 * sp):
            xs.append(x + w / 2)
    return xs


def parse_page(img: np.ndarray, lines: list[float], clf: Classifier) -> ParsedPage:
    sp = (lines[-1] - lines[0]) / 5
    ink = (gray(img) < 150).astype(np.uint8)
    bars = find_barlines(ink, lines)
    clean = remove_lines(ink, lines, bars)
    numbers = {b: n for b in bars if (n := read_number(img, lines, b, clf)) is not None}
    found, slide_marks, brackets = [], [], []
    for g in note_glyphs(img, lines, bars):
        d_line = min(abs(g.cy - ly) for ly in lines)
        if g.w < 3 or d_line > 0.4 * sp:
            continue
        lab, sc = clf(g)
        if lab == "/":
            slide_marks.append(g)
        elif lab in "<>" and g.h >= 0.4 * sp and d_line <= 0.3 * sp:
            brackets.append((g, lab))
        elif (lab in DIGITS or lab == "X") and g.h >= 0.55 * sp and d_line <= 0.15 * sp:
            found.append((g, lab, sc))
    raw = []
    for g, lab, sc, x1, cx in merge_multidigit(found, sp):
        h = g.y1 - g.y0
        string = int(np.argmin([abs(g.cy - ly) for ly in lines])) + 1
        ghost = False
        # "(3)": a parenthesis reads like a 1, so 1-3-1 comes in as fret 131; off the neck, it is a ghost note
        if lab not in ("X",) and len(lab) >= 3 and lab[0] == "1" and lab[-1] == "1" and int(lab) > 24:
            lab, ghost = lab[1:-1], True
        if lab != "X" and int(lab) > 24:
            continue  # not a fret: a misread mark, better no note than a wrong one
        if not ghost and bracketed(clean, g.x0, x1, g.y0, g.y1, sp):
            ghost = True  # "(3)": a tie or a ghost note, effects.parentheses decides which
        fret = None if lab == "X" else int(lab)
        note = Note(string, fret, grace=h < 0.8 * sp, x=cx, score=sc, ghost=ghost)
        # "<12>": angle brackets on both sides of the fret, on its string, make a natural harmonic
        near = [(b, k) for b, k in brackets if abs(b.cy - g.cy) < 0.3 * sp and abs(b.cx - cx) < 1.4 * sp]
        left = [b for b, k in near if k == "<" and b.cx < cx]
        right = [b for b, k in near if k == ">" and b.cx > cx]
        if left and right:
            note.harmonic = True
            # the small "1" inside <12> looks like a stroke fragment and can drop out: if the brackets hold room
            # for two digits but one was read, it was 12, 17 or 19 (the two-digit natural harmonics)
            room = min(b.x0 for b in right) - max(b.x1 for b in left)
            if fret is not None and fret < 10 and room > 1.5 * (x1 - g.x0) and 10 + fret in (12, 17, 19):
                note.fret = 10 + fret
        raw.append(note)
    rests = find_rests(clean, lines)
    # group notes into measures and columns
    measures = []
    edges = [0] + bars + [img.shape[1]]
    for a, b in zip(edges, edges[1:]):
        if b - a < sp:
            continue
        ns = sorted([n for n in raw if a < n.x < b], key=lambda n: n.x)
        cols: list[Column] = []
        pending_grace: list[Note] = []
        for n in ns:
            if n.grace:
                pending_grace.append(n)
                continue
            # same column when it lines up, unless that string already has a note there (then it is the next beat)
            if (cols and abs(cols[-1].x - n.x) < 0.45 * sp and not pending_grace
                    and n.string not in {m.string for m in cols[-1].notes}):
                cols[-1].notes.append(n)
                cols[-1].x = float(np.mean([m.x for m in cols[-1].notes]))
            else:
                cols.append(Column(x=n.x, notes=[n], grace=pending_grace))
                pending_grace = []
        cols += [Column(x=x, notes=[]) for x in rests if a < x < b]  # rests: no notes
        cols.sort(key=lambda c: c.x)
        complete = a in bars and b in bars
        num = numbers.get(a)
        measures.append(PageMeasure(num, a, b, complete, cols))
    # Guitar Pro numbers measures consecutively, so number = position + a constant offset.
    # Taking the most common offset fixes misread or unreadable numbers (e.g. measure 1,
    # whose number sits after the clef, or measures on a faded first view).
    offs = [m.number - i for i, m in enumerate(measures) if m.number is not None]
    if offs:
        k = max(set(offs), key=offs.count)
        for i, m in enumerate(measures):
            m.number = i + k if i + k >= 1 else None
    from .effects import annotate  # effects builds on the dataclasses defined here
    annotate(img, clean, lines, bars, measures, slide_marks)
    return ParsedPage(bars, measures, numbers)


def signature(m: PageMeasure) -> str:
    """Compact text form of a measure's notes (for debugging and comparisons)."""
    parts = []
    for c in m.columns:
        g = ",".join(f"g{n.string}:{'x' if n.dead else n.fret}" for n in c.grace)
        parts.append(g + "|" + ",".join(f"{n.string}:{'x' if n.dead else n.fret}"
                                         for n in sorted(c.notes, key=lambda n: n.string)))
    return " ".join(parts)
