"""Where the playback is, in one frame of a tab line, whatever the video uses to show it.

Tab ink is black or grey on light paper; what shows the playback is coloured. Seen so far: a thin blue line over
the staff (with the whole bar tinted yellow), a pale green band in a red box around the beat, and the notes being
played turning blue. So: look at the coloured pixels per hue. A narrow coloured column as tall as the staff is the
cursor (a line or a band up to 2.5 staff spaces; a whole tinted bar is far wider); without one, a cluster of
coloured notes is.
"""
import cv2
import numpy as np

HUES = 12  # hue bins around the paper colour
TINT = 4  # colour difference from the paper that counts as coloured (JPEG noise on paper stays below ~2)


def _chroma(band: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(a, b) colour of every pixel relative to the paper's, and lightness. The paper may be white or beige."""
    lab = cv2.cvtColor(band, cv2.COLOR_BGR2LAB).astype(np.float32)
    light = lab[..., 0] > 180
    ref = np.median(lab[light][:, 1:], axis=0) if light.any() else np.array([128, 128], np.float32)
    return lab[..., 1] - ref[0], lab[..., 2] - ref[1], lab[..., 0]


def tinted_mask(band: np.ndarray) -> np.ndarray:
    """Pixels with a colour of their own, however pale (a pale green band counts, white or beige paper does not)."""
    a, b, light = _chroma(band)
    return (np.hypot(a, b) > TINT) & (light > 90)


def find_cursor(band: np.ndarray, top: float, bottom: float, sp: float, static: np.ndarray | None = None) -> float:
    """x of the playback in `band` (a crop of one tab line), or NaN. `top`/`bottom`: y of the outer staff lines.
    `static`: pixels that are coloured in most frames (a logo, a coloured frame): never the cursor, which moves."""
    a, b, light = _chroma(band)
    rows = slice(max(0, int(top - 0.3 * sp)), int(bottom + 0.3 * sp) + 1)
    tinted = (np.hypot(a, b) > TINT) & (light > 90)
    if static is not None:
        tinted &= ~static
    h = (np.degrees(np.arctan2(b, a)) % 360 * HUES / 360).astype(int)
    hue = h[rows]
    tinted = tinted[rows]
    # digits and lines inside a band are dark, not tinted: count coverage over the rest of each column
    height = np.maximum((light[rows] > 90).sum(axis=0), 1)
    best = None  # (area, x) of the best narrow column
    for k in range(HUES):
        # a colour family (this bin and two either side), so a tint that straddles bins is judged as one: a whole
        # tinted bar is then too wide, and the slightly different fringe at its edges can't pass for a cursor
        family = np.isin(hue, [(k + d) % HUES for d in (-2, -1, 0, 1, 2)])
        prof = (tinted & family).sum(axis=0) / height
        cols = prof > 0.5
        if not cols.any():
            continue
        # runs of tall coloured columns
        edges = np.flatnonzero(np.diff(np.r_[0, cols.astype(np.int8), 0]))
        for lo, hi in zip(edges[::2], edges[1::2]):
            if 2 <= hi - lo <= 2.5 * sp:  # a line or a beat band; a tinted bar is far wider
                area = float(prof[lo:hi].sum())
                if best is None or area > best[0]:
                    best = (area, (lo + hi - 1) / 2)
    if best is not None:
        return float(best[1])
    # coloured notes: digits that are coloured as a whole (black digits only have coloured fringes from compression)
    # ink by Lab lightness (pure blue is dark there, though bright in HSV), its colour absolute: black is neutral
    # whatever the paper's colour, and HSV saturation is high on any dark grey pixel, so it can't tell
    lab_img = cv2.cvtColor(band, cv2.COLOR_BGR2LAB).astype(np.float32)[rows]
    ink = (lab_img[..., 0] < 170).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(ink)
    chroma = np.hypot(lab_img[..., 1] - 128, lab_img[..., 2] - 128)
    if static is not None:
        chroma = np.where(static[rows], 0, chroma)
    blobs = []
    for i in range(1, n):
        if not (0.3 * sp <= st[i, cv2.CC_STAT_HEIGHT] <= 1.2 * sp and st[i, cv2.CC_STAT_AREA] >= 0.05 * sp * sp):
            continue
        if np.median(chroma[lab == i]) > 50:  # vivid: dark purple or brown digits are not a cursor
            blobs.append((st[i, cv2.CC_STAT_AREA], cen[i][0]))
    if not blobs:
        return float("nan")
    # the notes of one beat stand in one column: take the column with the most coloured ink
    xs = np.array([x for _, x in blobs])
    ws = np.array([a for a, _ in blobs], float)
    score = [(ws[np.abs(xs - x) < 0.6 * sp].sum(), x) for x in xs]
    x = max(score)[1]
    near = np.abs(xs - x) < 0.6 * sp
    return float(np.average(xs[near], weights=ws[near]))
