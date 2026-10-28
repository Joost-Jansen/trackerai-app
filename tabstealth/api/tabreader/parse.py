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
    """Join digit glyphs that sit side by side on the same string into one number."""
    notes.sort(key=lambda t: (round(t[0].cy / sp), t[0].x0))
    out: list[list] = []
    for g, lab, sc in notes:
        if (out and lab in DIGITS and out[-1][1][-1] in DIGITS
                and abs(out[-1][0].cy - g.cy) < 0.2 * sp
                and 0 <= g.x0 - out[-1][3] < 0.25 * sp):
            out[-1][1] += lab
            out[-1][3] = g.x1
            out[-1][2] = min(out[-1][2], sc)
            out[-1][4] = (out[-1][0].x0 + g.x1) / 2
        else:
            out.append([g, lab, sc, g.x1, g.cx])
    return out


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
    numbers = {b: n for b in bars if (n := read_number(img, lines, b, clf)) is not None}
    found, slide_marks = [], []
    for g in note_glyphs(img, lines, bars):
        d_line = min(abs(g.cy - ly) for ly in lines)
        if g.w < 3 or d_line > 0.4 * sp:
            continue
        lab, sc = clf(g)
        if lab == "/":
            slide_marks.append(g)
        elif (lab in DIGITS or lab == "X") and g.h >= 0.55 * sp and d_line <= 0.15 * sp:
            found.append((g, lab, sc))
    raw = []
    for g, lab, sc, x1, cx in merge_multidigit(found, sp):
        h = g.y1 - g.y0
        string = int(np.argmin([abs(g.cy - ly) for ly in lines])) + 1
        fret = None if lab == "X" else int(lab)
        raw.append(Note(string, fret, grace=h < 0.8 * sp, x=cx, score=sc))
    rests = find_rests(remove_lines(ink, lines, bars), lines)
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
            if cols and abs(cols[-1].x - n.x) < 0.45 * sp and not pending_grace:
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
    annotate(img, remove_lines(ink, lines, bars), lines, bars, measures, slide_marks)
    return ParsedPage(bars, measures, numbers)


def signature(m: PageMeasure) -> str:
    """Compact text form of a measure's notes (for debugging and comparisons)."""
    parts = []
    for c in m.columns:
        g = ",".join(f"g{n.string}:{'x' if n.dead else n.fret}" for n in c.grace)
        parts.append(g + "|" + ",".join(f"{n.string}:{'x' if n.dead else n.fret}"
                                         for n in sorted(c.notes, key=lambda n: n.string)))
    return " ".join(parts)
