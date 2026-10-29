"""Pass 1: scan every frame of the video for tab-strip state.

Per frame we record whether the staff is visible, the playback cursor x, the yellow
highlight span (current measure) and a coarse ink signature used to split the video
into "pages" (distinct tab images).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from .layout import Staff, find_staff, ink_mask

SIG_DOWN = 4  # signature downsampling factor


@dataclass
class Region:
    y0: int
    y1: int
    x0: int
    x1: int


def strip_region(staff: Staff, frame_h: int) -> Region:
    sp = staff.spacing
    return Region(
        y0=max(0, int(staff.lines[0] - 3.6 * sp)),
        y1=min(frame_h, int(staff.lines[-1] + 1.6 * sp)),
        x0=0,
        x1=staff.x1,
    )


def detect_staff(video: str, samples: int = 40) -> Staff:
    """Robust staff geometry: median over frames sampled across the video."""
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    found = []
    for i in np.linspace(n * 0.05, n * 0.95, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok and (s := find_staff(fr)):
            found.append(s)
    cap.release()
    if not found:
        raise RuntimeError("no tab staff found in video")
    lines = np.median([s.lines for s in found], axis=0).tolist()
    x1 = int(np.median([s.x1 for s in found]))
    return Staff(lines=lines, x0=0, x1=x1)


def cursor_x(crop: np.ndarray) -> float:
    """x of the blue playback cursor in the crop, or NaN."""
    b, g, r = (crop[..., i].astype(int) for i in range(3))
    blue = (b - r > 25) & (b > 150)
    col = blue.sum(axis=0)
    if col.max() < crop.shape[0] * 0.4:
        return np.nan
    xs = np.where(col >= col.max() * 0.6)[0]
    return float(xs.mean())


def highlight_span(crop: np.ndarray) -> tuple[float, float]:
    b, g, r = (crop[..., i].astype(int) for i in range(3))
    yellow = (r - b > 20) & (g - b > 20) & (r > 200)
    col = yellow.mean(axis=0)
    xs = np.where(col > 0.3)[0]
    if len(xs) < 10:
        return (np.nan, np.nan)
    return (float(xs.min()), float(xs.max()))


def scan(video: str, staff: Staff | None = None, progress: bool = True) -> dict:
    staff = staff or detect_staff(video)
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reg = strip_region(staff, h)
    line_rows = [int(round(y)) - reg.y0 for y in staff.lines]
    sp = staff.spacing
    # dark bar above the strip with the section name (left) and lyrics (right)
    lab_y0, lab_y1 = max(0, int(staff.lines[0] - 7.2 * sp)), int(staff.lines[0] - 4.4 * sp)
    lab_x1 = int(staff.x1 * 0.35)
    labels, last_lab = [], None  # (frame, crop) whenever the section label changes
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    corner = None
    present, cur, hl0, hl1, sigs = [], [], [], [], []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        crop = fr[reg.y0 : reg.y1, reg.x0 : reg.x1]
        ink = ink_mask(crop, 185)
        # staff present if most of the 6 line rows are mostly inked
        cov = [ink[max(0, y - 1) : y + 2].max(axis=0).mean() for y in line_rows]
        gaps = [ink[(a + b) // 2].mean() for a, b in zip(line_rows, line_rows[1:])]
        present.append(min(cov) > 0.5 and max(gaps) < 0.35)
        cur.append(cursor_x(crop))
        a, b = highlight_span(crop)
        hl0.append(a)
        hl1.append(b)
        sig = cv2.resize(ink_mask(crop, 140), None, fx=1 / SIG_DOWN, fy=1 / SIG_DOWN, interpolation=cv2.INTER_AREA)
        sigs.append(np.packbits(sig > 0))
        if present[-1]:
            lab = fr[lab_y0:lab_y1, :lab_x1]
            lab_sig = cv2.resize(cv2.cvtColor(lab, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25) > 160  # light text on the dark bar
            if last_lab is None or (lab_sig != last_lab).mean() > 0.01:
                labels.append((i, lab.copy()))
                last_lab = lab_sig
            if corner is None and i > n_frames // 3:
                corner = fr[: int(staff.lines[0] - 7.2 * sp), int(fr.shape[1] * 0.7) :].copy()
        i += 1
        if progress and i % 1000 == 0:
            print(f"  scanned {i} frames", flush=True)
    cap.release()
    return dict(
        fps=fps,
        frame_h=h,
        staff_lines=np.array(staff.lines),
        staff_x1=staff.x1,
        region=np.array([reg.y0, reg.y1, reg.x0, reg.x1]),
        present=np.array(present),
        cursor=np.array(cur),
        hl0=np.array(hl0),
        hl1=np.array(hl1),
        sigs=np.array(sigs),
        label_frames=np.array([f for f, _ in labels]),
        label_crops=[c for _, c in labels],
        corner=corner if corner is not None else np.zeros((1, 1, 3), np.uint8),
    )
