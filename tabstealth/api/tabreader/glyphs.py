"""Glyph extraction from a clean page image: bar lines, measure numbers, note glyphs."""
from dataclasses import dataclass

import cv2
import numpy as np

GLYPH_W, GLYPH_H = 16, 24  # normalised glyph bitmap size


@dataclass
class Glyph:
    x0: int
    y0: int
    x1: int  # exclusive
    y1: int  # exclusive
    bitmap: np.ndarray  # GLYPH_H x GLYPH_W float32 in [0,1]
    label: str = "?"
    score: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    @property
    def w(self) -> int:
        return self.x1 - self.x0


def normalise(patch: np.ndarray) -> np.ndarray:
    """Pad to the target aspect ratio, then resize: keeps '1' thin and '0' round."""
    h, w = patch.shape
    target_w = int(round(h * GLYPH_W / GLYPH_H))
    if w < target_w:
        pad = target_w - w
        patch = np.pad(patch, ((0, 0), (pad // 2, pad - pad // 2)))
    elif w > target_w:
        th = int(round(w * GLYPH_H / GLYPH_W))
        pad = th - h
        patch = np.pad(patch, ((pad // 2, pad - pad // 2), (0, 0)))
    return cv2.resize(patch.astype(np.float32), (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA)


def gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def find_barlines(ink: np.ndarray, lines: list[float]) -> list[int]:
    """x of bar lines: thin vertical strokes spanning exactly line 1 .. line 6."""
    top, bot = int(round(lines[0])), int(round(lines[-1]))
    sp = (lines[-1] - lines[0]) / 5
    span = ink[top:bot + 1]
    cover = span.mean(axis=0)
    above = ink[int(top - 0.45 * sp):top - 2].mean(axis=0)
    below = ink[bot + 3:int(bot + 0.45 * sp)].mean(axis=0) if bot + 3 < ink.shape[0] else 0 * cover
    cand = np.where((cover > 0.95) & (above < 0.2) & (below < 0.2))[0]
    xs, cur = [], []
    for x in cand:
        if cur and x - cur[-1] > 2:
            xs.append(cur)
            cur = []
        cur.append(x)
    if cur:
        xs.append(cur)
    bars = [float(np.mean(c)) for c in xs if len(c) <= 4]
    # merge double bar lines / repeat bars that sit close together
    merged: list[float] = []
    for x in bars:
        if merged and x - merged[-1] < 0.5 * sp:
            merged[-1] = x
        else:
            merged.append(x)
    return [int(round(x)) for x in merged]


def remove_lines(ink: np.ndarray, lines: list[float], bars: list[int]) -> np.ndarray:
    """Erase staff lines (where nothing is drawn just above/below) and long vertical strokes."""
    out = ink.copy()
    sp = (lines[-1] - lines[0]) / 5
    for ly in lines:
        y = int(round(ly))
        for yy in range(y - 1, y + 2):
            if yy - 3 < 0 or yy + 3 >= out.shape[0]:
                continue
            thin = (ink[yy - 3] == 0) & (ink[yy + 3] == 0)
            out[yy, thin] = 0
    # long vertical strokes: bar lines, arrow shafts
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(1.3 * sp)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, k)
    vert = cv2.dilate(vert, np.ones((1, 3), np.uint8))
    out[vert > 0] = 0
    return out


def components(ink: np.ndarray, y_lo: int, y_hi: int, min_h: int, max_h: int,
               max_w: int) -> list[Glyph]:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    gl = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (min_h <= h <= max_h and w <= max_w and area >= 4):
            continue
        if y + h / 2 < y_lo or y + h / 2 > y_hi:
            continue
        patch = (lab[y:y + h, x:x + w] == i).astype(np.float32)
        gl.append(Glyph(x, y, x + w, y + h, normalise(patch)))
    return gl


def note_glyphs(img: np.ndarray, lines: list[float], bars: list[int],
                thresh: int = 150) -> list[Glyph]:
    sp = (lines[-1] - lines[0]) / 5
    ink = (gray(img) < thresh).astype(np.uint8)
    clean = remove_lines(ink, lines, bars)
    return components(clean, int(lines[0] - 0.5 * sp), int(lines[-1] + 0.5 * sp),
                      min_h=int(0.3 * sp), max_h=int(1.0 * sp), max_w=int(0.9 * sp))


def number_glyphs(img: np.ndarray, lines: list[float], bar_x: int,
                  thresh: int = 200) -> list[Glyph]:
    """Small gray measure-number digits above a bar line."""
    sp = (lines[-1] - lines[0]) / 5
    y0, y1 = int(lines[0] - 1.1 * sp), int(lines[0] - 0.15 * sp)
    x0, x1 = max(0, int(bar_x - 1.0 * sp)), int(bar_x + 1.0 * sp)
    roi = (gray(img)[y0:y1, x0:x1] < thresh).astype(np.uint8)
    gl = components(roi, 0, roi.shape[0], min_h=int(0.3 * sp), max_h=int(0.75 * sp),
                    max_w=int(0.6 * sp))
    for g in gl:
        g.x0 += x0
        g.x1 += x0
        g.y0 += y0
        g.y1 += y0
    return sorted(gl, key=lambda g: g.x0)
