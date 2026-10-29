"""Locate the tab strip (6 staff lines) in a video frame."""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Staff:
    lines: list[float]  # y of string 1 (high e) .. string 6 (low E), in full-frame px
    x0: int  # left end of the staff lines
    x1: int  # right end of the staff lines (chord box starts after this)

    @property
    def spacing(self) -> float:
        return (self.lines[-1] - self.lines[0]) / 5

    def string_of(self, y: float) -> int:
        """1-based string number nearest to y."""
        return int(np.argmin([abs(y - ly) for ly in self.lines])) + 1


def ink_mask(bgr: np.ndarray, thresh: int = 140) -> np.ndarray:
    """Dark ink as 1. Yellow highlight, blue cursor and white paper all map to 0."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return (gray < thresh).astype(np.uint8)


def find_staff(frame: np.ndarray, search_from: float = 0.5) -> Staff | None:
    """Find six equally spaced long horizontal lines in the lower part of the frame."""
    h, w = frame.shape[:2]
    y_off = int(h * search_from)
    ink = ink_mask(frame[y_off:], thresh=185)
    # A staff line is a long run of ink; use a horizontal opening to keep only long runs.
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
    long_runs = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
    prof = long_runs.sum(axis=1)
    rows = np.where(prof > w * 0.35)[0]
    if len(rows) < 6:
        return None
    # group adjacent rows into lines
    groups, cur = [], [rows[0]]
    for r in rows[1:]:
        if r - cur[-1] <= 2:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    groups = [g for g in groups if len(g) <= 3]  # staff lines are thin
    if len(groups) < 6:
        return None
    ys = [float(np.average(g, weights=prof[g])) for g in groups]
    # pick the 6 consecutive lines with the most uniform spacing
    best = None
    for i in range(len(ys) - 5):
        cand = ys[i : i + 6]
        d = np.diff(cand)
        if d.min() < 12 or d.max() > 60:
            continue
        score = d.std() / d.mean()
        if score < 0.08 and (best is None or score < best[0]):
            best = (score, cand)
    if best is None:
        return None
    lines = [y + y_off for y in best[1]]
    # horizontal extent: where the middle line row has long ink
    mid = int(round(lines[2])) - y_off
    cols = np.where(long_runs[mid - 1 : mid + 2].max(axis=0) > 0)[0]
    return Staff(lines=lines, x0=int(cols.min()), x1=int(cols.max()))


def find_staffs(frame: np.ndarray, min_width: float = 0.2) -> list[Staff]:
    """Every tab staff in the frame, top to bottom: groups of six evenly spaced long lines with light paper between
    them (guitar strings in the video are long lines too, but over a dark neck)."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    ink = (gray < 215).astype(np.uint8)  # thin light-grey staff lines on white paper count too
    # a line is thin: paper a few pixels above and below (a filled area such as a fretboard picture is not)
    ink[4:-4] &= (1 - ink[:-8]) & (1 - ink[8:])
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
    long_runs = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
    prof = long_runs.sum(axis=1)
    rows = np.where(prof > w * min_width)[0]
    if len(rows) < 6:
        return []
    groups, cur = [], [rows[0]]
    for r in rows[1:]:
        if r - cur[-1] <= 2:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    groups = [g for g in groups if len(g) <= 6]  # thin lines; anti-aliasing makes thick ones a few rows more
    ys = [float(np.average(g, weights=prof[g])) for g in groups]
    staffs, i = [], 0
    while i + 6 <= len(ys):
        cand = ys[i : i + 6]
        d = np.diff(cand)
        if d.min() >= 8 and d.max() <= 60 and d.std() / d.mean() < 0.08:
            # the staff runs where (nearly) all six lines do; one line alone may be a fret of a fretboard picture
            on = np.sum([long_runs[int(round(y)) - 1 : int(round(y)) + 2].max(axis=0) > 0 for y in cand], axis=0) >= 5
            on = cv2.morphologyEx(on.astype(np.uint8)[None], cv2.MORPH_CLOSE, np.ones((1, 15), np.uint8))[0] > 0
            cols = np.flatnonzero(on)
            if len(cols) < w * min_width:
                i += 1
                continue
            x0, x1 = int(cols.min()), int(cols.max())
            # paper between the lines: mostly light where the lines run
            band = gray[int(cand[0]) + 2 : int(cand[-1]) - 1, x0 : x1 + 1]
            gaps = [gray[int((a + b) / 2), x0 : x1 + 1] for a, b in zip(cand, cand[1:])]
            if np.mean([np.mean(g > 150) for g in gaps]) > 0.75 and band.size:
                staffs.append(Staff(lines=cand, x0=x0, x1=x1))
                i += 6
                continue
        i += 1
    return staffs
