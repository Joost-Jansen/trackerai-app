"""Tempo mark ("♩ = 73") reading and meter inference."""
import cv2
import numpy as np

from .glyphs import Glyph, gray, normalise
from .parse import DIGITS, Classifier


def read_tempo_mark(img: np.ndarray, lines: list[float], x_end: int, clf: Classifier) -> int | None:
    """Digits of the tempo mark above the first measures (bold, ~1 string space tall)."""
    sp = (lines[-1] - lines[0]) / 5
    y0, y1 = max(0, int(lines[0] - 3.2 * sp)), int(lines[0] - 0.5 * sp)
    roi = (gray(img[y0:y1, :x_end]) < 150).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(roi)
    digits = []
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if 0.75 * sp < h < 1.3 * sp and 0.3 * sp < w < 0.9 * sp:
            g = Glyph(x, y, x + w, y + h, normalise((lab[y:y + h, x:x + w] == i).astype(np.float32)))
            lab_, sc = clf(g)
            if lab_ in DIGITS and sc > 0.7:
                digits.append((x, y + h / 2, lab_))
    if not digits:
        return None
    digits.sort()
    # keep the digits on one row and adjacent to each other
    row = [d for d in digits if abs(d[1] - digits[-1][1]) < 0.3 * sp]
    groups, cur = [], [row[0]]
    for d in row[1:]:
        if d[0] - cur[-1][0] < 1.2 * sp:
            cur.append(d)
        else:
            groups.append(cur)
            cur = [d]
    groups.append(cur)
    vals = [int("".join(d[2] for d in g)) for g in groups]
    vals = [v for v in vals if 30 <= v <= 300]
    return vals[0] if vals else None


def infer_meter(measure_seconds: float, tempo: int | None) -> tuple[int, int, int]:
    """(numerator, denominator, tempo). Without a tempo mark we assume 4/4."""
    if not tempo:
        return 4, 4, int(round(240 / measure_seconds))
    quarters = measure_seconds * tempo / 60
    q2 = round(quarters * 2) / 2
    if abs(quarters - q2) > 0.2:  # tempo mark does not fit the playback: trust playback, 4/4
        return 4, 4, int(round(240 / measure_seconds))
    if q2 == int(q2):
        return int(q2), 4, tempo
    return int(q2 * 2), 8, tempo  # e.g. 3.5 quarters = 7/8
