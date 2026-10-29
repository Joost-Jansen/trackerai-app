"""Stitch the scrolled page views into one continuous tab "tape".

Consecutive pages show overlapping parts of the same horizontal tab line. We find the
horizontal scroll between them by matching ink, place every page on a shared tape
coordinate, and compose a panorama that is then parsed in one go.
"""

from dataclasses import dataclass

import numpy as np

from .glyphs import gray


@dataclass
class Tape:
    image: np.ndarray
    offsets: list[int]  # tape_x = page_x + offsets[page]
    scores: list[float]  # registration quality per page transition (1.0 = identical overlap)


def _ink(img: np.ndarray, rows: slice) -> np.ndarray:
    return (gray(img)[rows] < 150).astype(np.float32)


def _score(a: np.ndarray, b: np.ndarray, s: int) -> float:
    w = a.shape[1]
    ov_a, ov_b = a[:, s:], b[:, : w - s]
    return float((ov_a * ov_b).sum() / max(np.maximum(ov_a, ov_b).sum(), 1))


def register(
    a: np.ndarray, b: np.ndarray, candidates: list[int] | None = None, min_overlap: int = 200, window: int = 15
) -> tuple[int, float]:
    """Shift s >= 0 such that a[:, x + s] ~ b[:, x] (b is a scrolled left by s).

    Repetitive music (the same riff bar after bar) makes the ink match at several
    shifts, so when measure numbers give candidate shifts we only search near those.
    """
    w = a.shape[1]
    if candidates:
        windows = [range(max(0, c - window), min(w - min_overlap, c + window + 1)) for c in candidates]
        return max(((s, _score(a, b, s)) for win in windows for s in win), key=lambda t: t[1], default=(0, -1.0))
    # coarse search on 2x downsampled ink, then refine at full resolution
    a2, b2 = a[:, ::2], b[:, ::2]
    s0 = max(range(0, (w - min_overlap) // 2), key=lambda s: _score(a2, b2, s)) * 2
    return max(((s, _score(a, b, s)) for s in range(max(0, s0 - 2), min(w - min_overlap, s0 + 3))), key=lambda t: t[1])


def cursor_shift(cursor: np.ndarray, run_a: tuple[int, int], run_b: tuple[int, int]) -> int | None:
    """Predict the scroll between two views from the playback cursor.

    Music time runs on through a scroll, so the cursor's position just before it,
    carried forward at its current speed, lands where the cursor appears in the next view.
    """
    fa = [f for f in range(run_a[0], run_a[1] + 1) if not np.isnan(cursor[f])][-8:]
    fb = [f for f in range(run_b[0], run_b[1] + 1) if not np.isnan(cursor[f])][:1]
    if len(fa) < 3 or not fb:
        return None
    v = np.polyfit(fa, cursor[fa], 1)[0]  # px per frame
    pred = cursor[fa[-1]] + v * (fb[0] - fa[-1])
    return int(round(pred - cursor[fb[0]]))


def stitch(
    images: list[np.ndarray], lines: list[float], numbers: list[dict[int, int]] | None = None, cursor_shifts: list[int | None] | None = None
) -> Tape:
    """numbers: per view, {measure number: bar x}; cursor_shifts: predicted scroll per
    transition (see cursor_shift). Both are optional anchors against riff aliasing."""
    sp = (lines[-1] - lines[0]) / 5
    # compare only the staff band (chord names and lyrics change between views)
    rows = slice(int(lines[0] - 1.2 * sp), int(lines[-1] + 0.6 * sp))
    inks = [_ink(im, rows) for im in images]
    offsets, scores = [0], [1.0]
    for i, (a, b) in enumerate(zip(inks, inks[1:])):
        # anchors, most precise first: shared measure numbers, then the cursor prediction
        cands, window = [], 15
        if numbers:
            na, nb = numbers[i], numbers[i + 1]
            cands = sorted({na[n] - nb[n] for n in na.keys() & nb.keys() if na[n] - nb[n] >= 0})
        pred = cursor_shifts[i] if cursor_shifts else None
        if not cands and pred is not None:
            cands, window = [max(0, pred)], 80
        s, sc = register(a, b, cands or None, window=window)
        offsets.append(offsets[-1] + s)
        scores.append(sc)
    h, w = images[0].shape[:2]
    total = offsets[-1] + w
    tape = np.full((h, total, 3), 255, np.uint8)
    best_margin = np.full(total, -np.inf)
    paper = [float(np.median(gray(im))) for im in images]
    brightest = max(paper)
    for img, off, pb in zip(images, offsets, paper):
        # use each tape column from the view where it is farthest from the view's edges,
        # avoiding views that are dimmed (fade-in/out transitions)
        x = np.arange(w)
        margin = np.minimum(x, w - 1 - x).astype(float) - (10_000 if pb < brightest - 12 else 0)
        cols = off + x
        better = margin > best_margin[cols]
        tape[:, cols[better]] = img[:, x[better]]
        best_margin[cols[better]] = margin[better]
    return Tape(tape, offsets, scores)
