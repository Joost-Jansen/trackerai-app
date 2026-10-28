"""Pass 2: split the scan into stable pages and build a clean image of each page."""
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Page:
    idx: int
    f0: int  # first frame (inclusive)
    f1: int  # last frame (inclusive)
    image: np.ndarray | None = None  # clean BGR crop of the strip (median of frames)
    measures: list = field(default_factory=list)  # filled by parse


def stable_runs(scan: dict, max_diff: int = 40, min_len: int = 6) -> list[tuple[int, int]]:
    """Runs of consecutive frames whose ink signature barely changes."""
    sig = np.unpackbits(scan["sigs"], axis=1).astype(np.int16)
    diff = np.abs(np.diff(sig, axis=0)).sum(axis=1)
    present = scan["present"]
    runs, start = [], None
    for i in range(len(sig)):
        same = i > 0 and diff[i - 1] <= max_diff and present[i]
        if start is not None and not same:
            if i - start >= min_len:
                runs.append((start, i - 1))
            start = None
        if start is None and present[i]:
            start = i
    if start is not None and len(sig) - start >= min_len:
        runs.append((start, len(sig) - 1))
    return runs


def build_pages(video: str, scan: dict, n_samples: int = 9) -> list[Page]:
    y0, y1, x0, x1 = scan["region"]
    runs = stable_runs(scan)
    wanted: dict[int, list[int]] = {}
    for pi, (a, b) in enumerate(runs):
        for f in np.unique(np.linspace(a, b, min(n_samples, b - a + 1)).astype(int)):
            wanted.setdefault(int(f), []).append(pi)
    stacks: list[list[np.ndarray]] = [[] for _ in runs]
    cap = cv2.VideoCapture(video)
    f = 0
    last = max(wanted) if wanted else -1
    while f <= last:
        ok = cap.grab()
        if not ok:
            break
        if f in wanted:
            _, fr = cap.retrieve()
            crop = fr[y0:y1, x0:x1]
            for pi in wanted[f]:
                stacks[pi].append(crop)
        f += 1
    cap.release()
    pages = []
    for pi, (a, b) in enumerate(runs):
        # median removes the moving cursor; highlight is light and binarises away later
        img = np.median(np.stack(stacks[pi]), axis=0).astype(np.uint8)
        pages.append(Page(idx=pi, f0=a, f1=b, image=img))
    return pages
