"""Tab videos of any layout: one or more tab lines per frame, scrolling, line by line or page by page, with a
cursor line, a beat band, coloured notes or no cursor at all.

The unit is the bar. Every frame, each tab line on screen is split into bars at its bar lines. A run of frames in
which no bar changes is a view; between views, bars are matched by content (in reading order: line by line, left to
right), so a bar that scrolls along or moves up a line stays the same bar, and one that was not on screen before is
new. A bar that comes back later (a repeat played again) is new again, so the bars run in playing order.

The song is the bars in the order they are played: with a cursor, the order in which it reaches them; without one,
the order in which they appear. Timing comes from the cursor, or else from when each page of bars appears.
The bars are scaled to one staff size and put side by side into a tape for the usual parser.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from .cursor import find_box, find_cursor, tinted_mask
from .glyphs import find_barlines
from .layout import Staff, find_staffs

SP = 26.7  # staff space of the tape (as the parser was tuned on)
TAPE_TOP = 96.5  # y of the top line on the tape
ABOVE, BELOW = 3.6, 1.6  # staff spaces kept above the top line and below the bottom one
TAPE_H = int(round(TAPE_TOP + 5 * SP + BELOW * SP))
SIG = (32, 10)  # bar signature size (w, h)


@dataclass
class Slot:
    """Where a tab line sits on screen."""

    staff: Staff
    static: np.ndarray  # pixels coloured in nearly every frame (never the cursor)

    @property
    def sp(self) -> float:
        return self.staff.spacing

    def band(self) -> tuple[int, int]:
        """Rows of the staff with a little margin (for bar lines, signatures and the cursor)."""
        return int(self.staff.lines[0] - 1.2 * self.sp), int(self.staff.lines[-1] + 1.2 * self.sp)

    def lines_at(self, dy: int, scale: float) -> list[float]:
        """The staff lines in a frame where the line sits `dy` lower and is `scale` times as tall."""
        top = self.staff.lines[0] + dy
        return [top + (y - self.staff.lines[0]) * scale for y in self.staff.lines]


@dataclass
class Bar:
    slot: int
    x0: int  # in frame px
    x1: int
    sig: np.ndarray
    dy: int = 0  # the line sat this much lower than its slot in that frame (a strip can move a little per page)
    scale: float = 1.0  # and was this much taller (a lesson's pages are not all drawn at the same size)


@dataclass
class View:
    f0: int
    f1: int
    bars: list[Bar]  # reading order
    ids: list[int] = field(default_factory=list)  # bar instance per bar


def find_slots(cap: cv2.VideoCapture, samples: int = 60) -> list[Slot]:
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    found: list[tuple[Staff, np.ndarray]] = []
    for i in np.linspace(n * 0.05, n * 0.95, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            found += [(s, fr) for s in find_staffs(fr)]
    if not found:
        raise RuntimeError("no tab staff found in video")
    # tab lines at the same height in different frames are one slot
    found.sort(key=lambda t: t[0].lines[0])
    groups: list[list[tuple[Staff, np.ndarray]]] = []
    for s, fr in found:
        if groups and abs(groups[-1][-1][0].lines[0] - s.lines[0]) < s.spacing:
            groups[-1].append((s, fr))
        else:
            groups.append([(s, fr)])
    frames_with = max(len(g) for g in groups)
    slots = []
    for g in groups:
        if len(g) < 0.2 * frames_with:
            continue  # seen too rarely: a transition or something else that looked like a staff
        lines = np.median([s.lines for s, _ in g], axis=0).tolist()
        staff = Staff(lines=lines, x0=int(np.median([s.x0 for s, _ in g])), x1=int(np.median([s.x1 for s, _ in g])))
        slot = Slot(staff, np.zeros((1, 1), bool))
        y0, y1 = slot.band()
        y0, y1 = max(0, y0), min(g[0][1].shape[0], y1)
        tint = np.mean([tinted_mask(fr[y0:y1, staff.x0 : staff.x1 + 1]) for _, fr in g], axis=0)
        slot.static = tint > 0.9
        slots.append(slot)
    return slots


# other sizes a tab line may have relative to its slot, nearest first
SCALES = sorted((s for s in np.round(np.arange(0.9, 1.101, 0.01), 2) if s != 1), key=lambda s: abs(s - 1))


def _fit(frame: np.ndarray, slot: Slot) -> tuple[int, float] | None:
    """How far the tab line sits below its usual place in this frame, and how much taller it is (None: not on
    screen). Some videos place each page a few pixels higher or lower, or (lessons) draw some pages a little larger
    or smaller: other sizes are tried when the slot's own does not fit."""
    st, sp = slot.staff, slot.sp
    reach = int(0.7 * sp)
    height = st.lines[-1] - st.lines[0]
    y0, y1 = int(st.lines[0]) - reach - 2, int(st.lines[0] + height * max(SCALES)) + reach + 3
    y0c, y1c = max(0, y0), min(frame.shape[0], y1)
    g = cv2.cvtColor(frame[y0c:y1c, st.x0 : st.x1 + 1], cv2.COLOR_BGR2GRAY)
    prof = (g < 200).mean(axis=1)
    for scales in ([1.0], SCALES):
        best = None
        for scale in scales:
            rows = [int(round(y)) - y0c for y in slot.lines_at(0, scale)]
            for dy in range(-reach, reach + 1):
                idx = [r + dy for r in rows]
                if min(idx) < 1 or max(idx) >= len(prof) - 1:
                    continue
                score = min(max(prof[i - 1], prof[i], prof[i + 1]) for i in idx)  # every line must be there
                if best is None or score > best[0]:
                    best = (score, dy, float(scale))
        if best and best[0] > 0.5:
            return best[1], best[2]
    return None


def _bars(frame: np.ndarray, k: int, slot: Slot, faint: list[int] | None = None) -> tuple[list[Bar], tuple[int, float] | None]:
    """The whole bars of one tab line in a frame, and its fit (None: the line is not on screen). `faint`: the faint
    bar lines of this line in the frame before; this frame's go in it."""
    fit = _fit(frame, slot)
    if fit is None:
        if faint is not None:
            faint.clear()
        return [], None
    dy, scale = fit
    st, sp = slot.staff, slot.sp * scale
    on = slot.lines_at(dy, scale)
    y0c, y1c = max(0, int(on[0] - 1.2 * sp)), min(frame.shape[0], int(on[-1] + 1.2 * sp))
    band = frame[y0c:y1c, st.x0 : st.x1 + 1]
    crop = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    if (crop > 150).mean() < 0.6:
        if faint is not None:
            faint.clear()
        return [], None  # not on paper: a fade or the video over it
    ink = (crop < 150).astype(np.uint8)
    lines = [y - y0c for y in on]
    xs = find_barlines(ink, lines)
    w = ink.shape[1]
    # a thin grey bar line (half on one pixel column, half on the next, as in some lessons) is lighter than ink:
    # add the bar lines found on lighter ink that is not coloured (a cursor line is no bar line), away from the ends.
    # Only in a frame with dark bar lines too, and where the frame before had it: a page fading in or out is all
    # grey for a moment, the one fading out shows through the next
    if faint is not None:
        light = find_barlines(((crop < 200) & ~tinted_mask(band)).astype(np.uint8), lines)
        new = [x for x in light if 2 * sp < x < w - 2 * sp and all(abs(x - d) > 0.5 * sp for d in xs)] if xs else []
        kept = [x for x in new if any(abs(x - y) < 0.5 * sp for y in faint)]
        faint[:] = new
        xs = sorted(xs + kept)
    edges = [0, *xs, w - 1]
    spans = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 2 * sp]
    if not spans:
        return [], fit
    inner = [b - a for a, b in spans if a in xs and b in xs]
    typical = np.median(inner) if inner else w / max(len(spans), 1)
    out = []
    top, bot = int(lines[0] - 0.5 * sp), int(lines[-1] + 0.5 * sp) + 1
    for a, b in spans:
        whole = a in xs and b in xs
        # the first bar of a line may start without a bar line, the last may end at the edge: whole enough if wide
        if not whole and b - a < 0.6 * typical:
            continue
        sig = cv2.resize(ink[top:bot, a:b].astype(np.float32), SIG, interpolation=cv2.INTER_AREA)
        out.append(Bar(k, st.x0 + a, st.x0 + b, sig, dy, scale))
    return out, fit


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    """Correlation of two bar signatures: what is drawn must match, shared blank paper does not count."""
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


def _same(a: Bar, b: Bar) -> bool:
    """The same bar, possibly elsewhere on screen (it scrolled or moved up a line)."""
    w = max(a.x1 - a.x0, b.x1 - b.x0)
    return abs((a.x1 - a.x0) - (b.x1 - b.x0)) < 0.12 * w and _corr(a.sig, b.sig) > 0.85


def _same_layout(a: list[Bar], b: list[Bar], sp: float) -> bool:
    """Nothing changed between two frames (a cursor moving over the bars aside)."""
    return len(a) == len(b) and all(
        p.slot == q.slot and abs(p.x0 - q.x0) < 0.4 * sp and abs(p.x1 - q.x1) < 0.4 * sp and _corr(p.sig, q.sig) > 0.9 for p, q in zip(a, b)
    )


def scan_video(video: str, progress=None) -> dict:
    """One pass over the video: the views (runs of frames with the same bars) and the cursor in every frame."""
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    slots = find_slots(cap)
    sp = float(np.median([s.sp for s in slots]))
    # what is above each tab line: from below the line above it (a box there would be that line's), or the top
    above = [0.0] + [s.staff.lines[-1] + 1.5 * s.sp for s in slots[:-1]]
    faint: list[list[int]] = [[] for _ in slots]  # per tab line, its faint bar lines in the frame before
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    views: list[View] = []
    cursor: list[tuple[int, int, float]] = []  # (frame, slot, x in frame px)
    cur: list[Bar] | None = None
    start = 0
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        bars = []
        for k, slot in enumerate(slots):
            b, fit = _bars(fr, k, slot, faint[k])
            bars += b
            if fit is not None:
                dy, scale = fit
                on, sp_k = slot.lines_at(dy, scale), slot.sp * scale
                y0c, y1c = max(0, int(on[0] - 1.2 * sp_k)), min(fr.shape[0], int(on[-1] + 1.2 * sp_k))
                st = slot.staff
                same = dy == 0 and scale == 1 and slot.static.shape[0] >= y1c - y0c
                static = slot.static if same else None
                x = find_cursor(
                    fr[y0c:y1c, st.x0 : st.x1 + 1],
                    on[0] - y0c,
                    on[-1] - y0c,
                    sp_k,
                    static[: y1c - y0c] if static is not None else None,
                )
                if np.isnan(x):
                    # a box over the notation above (a lesson); up to the tab line above, if there is one, and
                    # only with room for a staff in between
                    a0 = int(max(on[0] - 10 * sp_k, above[k], 0))
                    a1 = int(on[0] - 0.3 * sp_k)
                    if a1 - a0 > 5 * sp_k:
                        x = find_box(fr[a0:a1, st.x0 : st.x1 + 1], sp_k)
                if not np.isnan(x):
                    cursor.append((i, k, st.x0 + x))
        if cur is not None and not (bars and _same_layout(cur, bars, sp)):
            if i - start >= 4:
                views.append(View(start, i - 1, cur))
            cur = None
        if cur is None and bars:
            cur, start = bars, i
        i += 1
        if progress and i % 1000 == 0:
            progress(f"  scanned {i} frames")
    if cur is not None and i - start >= 4:
        views.append(View(start, i - 1, cur))
    cap.release()
    return {"fps": fps, "frames": i, "frame_h": frame_h, "slots": slots, "views": views, "cursor": cursor}


def link_views(views: list[View]) -> int:
    """Give every bar of every view an instance id: the same id as the matching bar of the view before."""
    next_id = 0
    prev: View | None = None
    for v in views:
        v.ids = [-1] * len(v.bars)
        if prev is not None:
            # the shift (in bars, reading order) under which most bars of the two views match
            n, m = len(prev.bars), len(v.bars)
            best = (0, 0)
            for k in range(-m + 1, n):
                hits = sum(1 for j in range(m) if 0 <= j + k < n and _same(prev.bars[j + k], v.bars[j]))
                if hits > best[0] or (hits == best[0] and hits and abs(k) < abs(best[1])):
                    best = (hits, k)
            if best[0]:
                k = best[1]
                for j in range(m):
                    if 0 <= j + k < n and _same(prev.bars[j + k], v.bars[j]):
                        v.ids[j] = prev.ids[j + k]
        for j in range(len(v.ids)):
            if v.ids[j] < 0:
                v.ids[j] = next_id
                next_id += 1
        prev = v
    return next_id


def as_pages(views: list[View]) -> list[View]:
    """Without a cursor, in a video whose views hardly share bars (pages that flip, not a strip that scrolls): every
    page is played in full, also when it comes back with only its last bar changed (a repeat with a second ending).
    So every page gets bars of its own; a view much shorter than a page is a transition and is left out."""
    shared = sum(1 for a, b in zip(views, views[1:]) for i in b.ids if i in a.ids)
    total = sum(len(v.ids) for v in views[1:])
    if not views or shared > 0.3 * max(total, 1):
        return views
    typical = float(np.median([v.f1 - v.f0 for v in views]))
    pages = [v for v in views if v.f1 - v.f0 >= 0.35 * typical]
    n = 0
    for v in pages:
        v.ids = list(range(n, n + len(v.bars)))
        n += len(v.bars)
    return pages


def is_lesson(views: list[View], fps: float, gap: float = 10.0) -> bool:
    """The tab goes away for a while (`gap` seconds or more) and comes back: a lesson, in which the tutor talks or
    plays to the camera between the parts of the score. A play-along video keeps its tab on screen."""
    return any(b.f0 - a.f1 >= gap * fps for a, b in zip(views, views[1:]))


def steady_pages(views: list[View], sp: float) -> list[View]:
    """In a lesson, a thin grey bar line may be found in some frames and missed in others, so one page on screen
    becomes many short views, with two bars or one wide one. Back-to-back views of the same page, where one only
    lacks some of the other's bar lines and the bars both have match, are one view with all the bar lines."""

    def edges(v: View) -> set[tuple[int, int]]:
        return {(b.slot, x) for b in v.bars for x in (b.x0, b.x1)}

    def within(a: set, b: set) -> bool:
        return all(any(k == m and abs(x - y) < 0.4 * sp for m, y in b) for k, x in a)

    def same_page(a: View, b: View) -> bool:
        if b.f0 - a.f1 > 2 or {x.slot for x in a.bars} != {x.slot for x in b.bars}:
            return False
        ea, eb = edges(a), edges(b)
        if not (within(ea, eb) or within(eb, ea)):
            return False
        both = [(p, q) for p in a.bars for q in b.bars if p.slot == q.slot and abs(p.x0 - q.x0) < 0.4 * sp and abs(p.x1 - q.x1) < 0.4 * sp]
        return bool(both) and all(_corr(p.sig, q.sig) > 0.9 for p, q in both)

    out: list[View] = []
    for v in views:
        if out and same_page(out[-1], v):
            prev = out[-1]
            finer = v.bars if len(v.bars) > len(prev.bars) else prev.bars
            out[-1] = View(prev.f0, v.f1, finer)
        else:
            out.append(v)
    return out


def link_pages(views: list[View]) -> None:
    """In a lesson, a page shown again later (after the tutor talked) is the same page: its bars keep their ids, so
    going over a passage twice does not write it out twice. Only a whole page counts; single bars are often alike."""
    for i, v in enumerate(views):
        if i and set(v.ids) & set(views[i - 1].ids):
            continue  # it follows on from the view before
        for e in views[:i]:
            if len(e.bars) == len(v.bars) and all(_same(a, b) for a, b in zip(e.bars, v.bars)):
                v.ids = list(e.ids)
                break


def play_order(views: list[View], cursor: list[tuple[int, int, float]], fps: float, min_frames: int = 3, once: bool = False):
    """The bars in playing order, `seq` (instance ids; a bar played twice is in it twice), the cursor samples as
    (time, position in seq, x in frame px), and whether the cursor carried the order.

    With a cursor: follow it from bar to bar. Returning to a bar it already left is playing it again (a repeat), so
    that bar gets a new place in the order. Stays shorter than `min_frames` are detection jitter at a bar edge and
    are ignored. A bar the cursor never reached goes after the bar before it on screen. Without a cursor: the order
    in which bars appear.

    `once` (a lesson): every bar once, in the order of the score, where the tutor goes back and forth over it; its
    timing is when the cursor first reached it."""
    by_frame: dict[int, list[tuple[int, float]]] = {}
    for f, k, x in cursor:
        by_frame.setdefault(f, []).append((k, x))
    hits = []  # (frame, instance, x)
    for v in views:
        for f in range(v.f0, v.f1 + 1):
            for k, x in by_frame.get(f, []):
                for bid, b in zip(v.ids, v.bars):
                    if b.slot == k and b.x0 <= x < b.x1:
                        hits.append((f, bid, x))
                        break
    appear: dict[int, tuple[int, int]] = {}
    for vi, v in enumerate(views):
        for j, bid in enumerate(v.ids):
            appear.setdefault(bid, (vi, j))
    ids = sorted(appear, key=lambda b: appear[b])
    # runs of the same bar; short runs are jitter
    runs: list[list] = []
    for f, bid, x in hits:
        if runs and runs[-1][0] == bid:
            runs[-1][1].append((f, x))
        else:
            runs.append([bid, [(f, x)]])
    runs = [r for r in runs if len(r[1]) >= min_frames]
    merged: list[list] = []
    for r in runs:
        if merged and merged[-1][0] == r[0]:
            merged[-1][1] += r[1]
        else:
            merged.append(r)
    if len({r[0] for r in merged}) < 0.5 * len(ids):
        return ids, [], False
    if once:
        first: dict[int, list] = {}
        for bid, fx in merged:
            first.setdefault(bid, fx)
        return ids, [(f / fps, ids.index(bid), x) for bid, fx in first.items() for f, x in fx], True
    seq, samples = [], []
    for bid, fx in merged:
        seq.append(bid)
        samples += [(f / fps, len(seq) - 1, x) for f, x in fx]
    for b in ids:  # bars the cursor never reached
        if b not in seq:
            prev = [p for p in ids[: ids.index(b)] if p in seq]
            seq.insert(seq.index(prev[-1]) + 1 if prev else 0, b)
            samples = [(t, p + (p >= (seq.index(b))), x) for t, p, x in samples]
    return seq, samples, True


def _bar_image(cap: cv2.VideoCapture, view: View, bar: Bar, slot: Slot, n: int = 7) -> np.ndarray:
    """A clean image of one bar on the tape's scale: the median over frames of its view (the cursor moves, the
    tab does not)."""
    on = slot.lines_at(bar.dy, bar.scale)
    sp = slot.sp * bar.scale
    y0 = int(round(on[0] - ABOVE * sp))
    y1 = int(round(on[-1] + BELOW * sp))
    stack = []
    for f in np.unique(np.linspace(view.f0, view.f1, n).astype(int)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, fr = cap.read()
        if not ok:
            continue
        h = fr.shape[0]
        # just inside the bar's own bar lines: the tape gets one clean line per boundary instead
        m = max(2, int(round(0.12 * sp)))
        crop = fr[max(0, y0) : min(h, y1), bar.x0 + m : bar.x1 - m + 1]
        # a line at the very top or bottom of the frame: pad with paper
        crop = cv2.copyMakeBorder(crop, max(0, -y0), max(0, y1 - h), 0, 0, cv2.BORDER_REPLICATE)
        stack.append(crop)
    img = np.median(np.stack(stack), axis=0).astype(np.uint8)
    f = SP / sp
    img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    # put the top line at TAPE_TOP, the height at TAPE_H
    shift = int(round(TAPE_TOP - ABOVE * SP))
    out = np.full((TAPE_H, img.shape[1], 3), 255, np.uint8)
    ys, yd = max(0, -shift), max(0, shift)
    hcopy = min(img.shape[0] - ys, TAPE_H - yd)
    out[yd : yd + hcopy] = img[ys : ys + hcopy]
    return out


def build_tape(video: str, views: list[View], slots: list[Slot], seq: list[int]):
    """The bars side by side in playing order (`seq`, from play_order). Returns the tape, the x range of each place
    in `seq` on it, and where each bar was taken from."""
    where: dict[int, tuple[View, Bar]] = {}
    for v in views:  # each bar from its longest view: the cleanest median
        for bid, b in zip(v.ids, v.bars):
            if bid not in where or (v.f1 - v.f0) > (where[bid][0].f1 - where[bid][0].f0):
                where[bid] = (v, b)
    cap = cv2.VideoCapture(video)
    parts, spans, x = [], [], 0
    lines = [TAPE_TOP + i * SP for i in range(6)]
    images: dict[int, np.ndarray] = {}
    for bid in seq:
        v, b = where[bid]
        if bid not in images:
            images[bid] = _bar_image(cap, v, b, slots[b.slot])
        img = images[bid].copy()
        img[int(lines[0]) : int(lines[-1]) + 1, :2] = 0  # a bar line before every bar: the parser splits on it
        parts.append(img)
        spans.append((x, x + img.shape[1]))
        x += img.shape[1]
    cap.release()
    end = np.full((TAPE_H, 12, 3), 255, np.uint8)
    end[int(lines[0]) : int(lines[-1]) + 1, :2] = 0  # and one after the last
    for k in range(6):
        end[int(round(lines[k])), :2] = 0
    return np.hstack(parts + [end]), spans, where, lines


def track(
    seq: list[int], spans: list, where: dict, samples: list, views: list[View], fps: float, covered: bool
) -> tuple[np.ndarray, np.ndarray]:
    """(time, tape x) of the playback: from the cursor, or else from when each page of bars appeared."""
    ts, xs = [], []
    if covered:
        for t, pos, x in samples:
            b = where[seq[pos]][1]
            a, e = spans[pos]
            ts.append(t)
            xs.append(a + (x - b.x0) / max(b.x1 - b.x0, 1) * (e - a))
    else:
        # no cursor: a page's bars are played while it is on screen, one after the other
        pos = 0
        for vi, v in enumerate(views):
            new = [p for p in range(pos, len(seq)) if seq[p] in v.ids][: len(v.ids)]
            if not new:
                continue
            pos = new[-1] + 1
            t0 = v.f0 / fps
            t1 = (views[vi + 1].f0 if vi + 1 < len(views) else v.f1 + 1) / fps
            step = (t1 - t0) / len(new)
            for j, p in enumerate(new):
                ts.append(t0 + j * step)
                xs.append(spans[p][0])
            ts.append(t1 - 1e-3)
            xs.append(spans[new[-1]][1] - 1)
    if not ts:
        return np.array([]), np.array([])
    o = np.argsort(ts, kind="stable")
    ts, xs = np.array(ts)[o], np.maximum.accumulate(np.array(xs)[o])
    # a cursor that jumps from beat to beat stays put in between: keep the moment it arrives (the onset)
    keep = np.r_[True, np.diff(xs) > 0]
    return ts[keep], xs[keep]
