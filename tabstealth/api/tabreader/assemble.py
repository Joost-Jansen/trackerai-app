"""Pass 4: turn the parsed tape into a song, deriving rhythm from the playback cursor.

The video's playback cursor sweeps smoothly and sits on a note at the moment it sounds.
Mapping the cursor into tape coordinates gives one monotone time track x(t); the onset
of any note column is the time the cursor passes it.
"""
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .meter import infer_meter
from .parse import Column, ParsedPage

TICKS_PER_QUARTER = 24  # divisible by 4, 3, 6 and 8: 16ths, triplets and 32nds
DOWNBEAT_MAX_U = 85  # first column closer than this to the bar line is on the downbeat


@dataclass
class Beat:
    start: int  # ticks from measure start
    duration: int = 0  # ticks, filled after quantisation
    column: Column | None = None  # None = rest


@dataclass
class Measure:
    number: int
    beats: list[Beat]
    tempo: int = 0
    t_start: float = np.nan
    duration_s: float = np.nan
    marker: str | None = None  # section name, e.g. "Verse 1"
    flags: list[str] = field(default_factory=list)
    timing_error: float = 0.0  # largest distance (in quarter notes) between a measured onset and its grid slot


@dataclass
class Song:
    measures: list[Measure]
    tempo: int
    numerator: int
    denominator: int
    triplet_feel: str | None = None  # "8th" / "16th" swing, as Guitar Pro's triplet feel


def cursor_track(offsets: list[int], runs: list[tuple[int, int]], scan: dict):
    """(t, tape_x) samples of the cursor over the whole video, made monotone."""
    fps = float(scan["fps"])
    ts, xs = [], []
    for off, (f0, f1) in zip(offsets, runs):
        for f in range(f0, f1 + 1):
            x = scan["cursor"][f]
            if not np.isnan(x):
                ts.append(f / fps)
                xs.append(x + off)
    ts, xs = np.array(ts), np.array(xs)
    backwards = int((np.diff(xs) < -3).sum())
    return ts, np.maximum.accumulate(xs), backwards


GRIDS = (4, 3, 6, 8)  # per quarter: 16ths, 8th triplets, 16th triplets, 32nds (simplest first)
GRID_TOL = 0.07  # max onset error in quarter notes (~50 ms at 80 bpm)


def quantise_positions(pos: list[float]) -> list[int]:
    """Map onsets (in quarter notes) to ticks, picking per beat the simplest grid that fits."""
    q = TICKS_PER_QUARTER
    out = [0] * len(pos)
    by_beat: dict[int, list[int]] = defaultdict(list)
    for i, p in enumerate(pos):
        by_beat[int(np.floor(p + 1 / 8))].append(i)
    for idx in by_beat.values():
        best = None
        for g in GRIDS:
            snapped = [round(pos[i] * g) / g for i in idx]
            err = max(abs(sv - pos[i]) for sv, i in zip(snapped, idx))
            distinct = len(set(snapped)) == len(snapped)
            if distinct and err <= GRID_TOL:
                best = snapped
                break
            if distinct and (best is None or err < best[0]):
                best = (err, snapped)
        snapped = best if isinstance(best, list) else (best[1] if best else
                                                       [round(pos[i] * 4) / 4 for i in idx])
        for i, sv in zip(idx, snapped):
            out[i] = int(round(sv * q))
    return out


def detect_swing(pos: list[float]) -> tuple[str | None, float]:
    """Swing ("triplet feel") from where off-beat notes land.

    Guitar Pro can play straight-written 8ths or 16ths swung. The cursor then reaches
    off-beat notes late: at ~0.62-0.67 of the pair instead of 0.5.
    """
    pos = np.asarray(pos)
    for feel, unit in (("16th", 0.5), ("8th", 1.0)):
        frac = (pos / unit) % 1
        # a swung off-beat sits at 0.6-0.67; 0.25 and 0.75 are straight 16ths, not swing
        off = frac[(frac > 0.4) & (frac < 0.71)]
        if len(off) >= 16 and 0.57 < np.median(off) < 0.72:
            return feel, float(np.median(off))
    return None, 0.5


def unswing(p: float, ratio: float, unit: float) -> float:
    """Map a swung onset back to the straight grid it is written on."""
    base, u = divmod(p / unit, 1.0)
    u = u * 0.5 / ratio if u < ratio else 0.5 + (u - ratio) * 0.5 / (1 - ratio)
    return (base + u) * unit


def spacing_positions(m, quarters: float) -> list[float]:
    """Fallback rhythm from note spacing (Guitar Pro spaces notes roughly by duration)."""
    xs = [c.x for c in m.columns] + [m.x1]
    w = np.diff(xs)
    return list(np.concatenate([[0], np.cumsum(w[:-1])]) / max(w.sum(), 1) * quarters)


def build_song(tape: ParsedPage, offsets: list[int], runs, scan: dict,
               tempo_mark: int | None = None, track: tuple[np.ndarray, np.ndarray] | None = None) -> Song:
    """`track`: (time, tape x) of the playback when the caller has it already (generic.track); otherwise it comes
    from the scrolling strip's cursor line."""
    if track is not None:
        (ts, xs), backwards = track, 0
    else:
        ts, xs, backwards = cursor_track(offsets, runs, scan)
    if len(xs) < 2:
        # the rhythm and the sync come from the moving cursor line; videos that flip whole pages and mark the beat
        # with a box or a coloured note have none (yet)
        raise RuntimeError("no playback cursor found: this tab layout (pages that flip, no cursor line) "
                           "is not supported yet")
    chosen = [m for m in tape.measures if m.number is not None and m.complete]
    first_u = [m.columns[0].x - m.x0 for m in chosen if m.columns]
    rest_u = float(np.median([u for u in first_u if u < DOWNBEAT_MAX_U] or [45]))

    def t_at(x: float) -> float:
        return float(np.interp(x, xs, ts))

    def downbeat_x(m) -> float:
        if m.columns and m.columns[0].x - m.x0 < DOWNBEAT_MAX_U:
            return m.columns[0].x
        return m.x0 + rest_u

    seen = (xs.min(), xs.max())
    starts = [t_at(downbeat_x(m)) for m in chosen]
    durs = np.diff(starts)
    med = float(np.median(durs))
    durs = list(durs) + [med]
    numerator, denominator, tempo = infer_meter(med, tempo_mark)
    quarters = numerator * 4 / denominator
    measure_ticks = int(quarters * TICKS_PER_QUARTER)
    raw = []  # (parsed measure, Measure, onsets in quarters, from cursor?)
    for m, t0, dur in zip(chosen, starts, durs):
        out = Measure(m.number, [], t_start=t0, duration_s=dur)
        covered = seen[0] <= downbeat_x(m) and m.x1 <= seen[1] + 60
        if not covered or not 0.6 * med < dur < 1.6 * med:
            out.flags.append("rhythm from note spacing")
            pos = spacing_positions(m, quarters) if m.columns else []
            dur = med
        else:
            pos = [(t_at(c.x) - t0) / dur * quarters for c in m.columns]
        out.tempo = int(round(60 * quarters / dur))
        raw.append((m, out, pos))
    feel, ratio = detect_swing([p for _, out, pos in raw for p in pos
                                if "rhythm from note spacing" not in out.flags])
    measures = []
    for m, out, pos in raw:
        if feel:
            pos = [unswing(p, ratio, 0.5 if feel == "16th" else 1.0) for p in pos]
        ticks = quantise_positions(pos)
        if pos and "rhythm from note spacing" not in out.flags:
            out.timing_error = max(abs(p - tk / TICKS_PER_QUARTER) for p, tk in zip(pos, ticks))
        beats: list[Beat] = []
        for c, tk in zip(m.columns, ticks):
            tk = min(max(tk, 0), measure_ticks - 1)
            if beats and beats[-1].start >= tk:  # two columns on one grid slot
                tk = beats[-1].start + 1
                out.flags.append("collision")
            beats.append(Beat(tk, column=c))
        if not beats or beats[0].start > 0:
            beats.insert(0, Beat(0))  # leading rest
        for a, b in zip(beats, beats[1:] + [Beat(measure_ticks)]):
            a.duration = b.start - a.start
        out.beats = [b for b in beats if b.duration > 0]
        measures.append(out)
    # Keep the video's bar numbers: a bar never seen whole (often bar 1 under a fade-in) becomes a rest bar in its
    # place, so bar N of the file is bar N of the video (sync, review and loops count on that).
    by_number = {m.number: m for m in measures}
    measures = [by_number.get(n) or Measure(n, [Beat(0, measure_ticks)], flags=["missing"])
                for n in range(1, max(by_number, default=0) + 1)]
    if backwards:
        measures[0].flags.append(f"cursor moved backwards {backwards}x (repeats?)")
    return Song(measures, tempo, numerator, denominator, feel)
