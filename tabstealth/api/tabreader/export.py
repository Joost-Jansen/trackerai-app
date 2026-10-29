"""Write a Song as a Guitar Pro 5 file (opens in TuxGuitar, MuseScore, Guitar Pro, alphaTab)."""
from dataclasses import dataclass

import guitarpro as gp

from .assemble import TICKS_PER_QUARTER, Song

# ticks (24 per quarter) -> (duration value, dotted, triplet), longest first
DURATIONS = [
    (96, 1, False, False), (72, 2, True, False), (48, 2, False, False),
    (36, 4, True, False), (32, 2, False, True), (24, 4, False, False),
    (18, 8, True, False), (16, 4, False, True), (12, 8, False, False),
    (9, 16, True, False), (8, 8, False, True), (6, 16, False, False),
    (4, 16, False, True), (3, 32, False, False), (2, 32, False, True),
    (1, 64, False, True),
]
STANDARD = [64, 59, 55, 50, 45, 40]


@dataclass
class Meta:
    title: str = ""
    artist: str = ""
    source: str = ""
    capo: int = 0
    tuning: list[int] | None = None  # MIDI pitch of string 1..6
    let_ring: bool = True


def split_ticks(ticks: int) -> list[tuple[int, int, bool, bool]]:
    parts = []
    while ticks > 0:
        d = next(d for d in DURATIONS if d[0] <= ticks)
        parts.append(d)
        ticks -= d[0]
    return parts


def gp_duration(value: int, dotted: bool, triplet: bool) -> gp.Duration:
    return gp.Duration(value=value, isDotted=dotted,
                       tuplet=gp.Tuplet(3, 2) if triplet else gp.Tuplet(1, 1))


def write_gp5(song: Song, path: str, meta: Meta) -> None:
    # GP5 keeps text in an 8-bit code page: leave out what it can't hold (emoji in a video title)
    fit = lambda t: t.encode("cp1252", "ignore").decode("cp1252")
    g = gp.Song(title=fit(meta.title), artist=fit(meta.artist), tempo=song.tempo)
    g.tab = fit(meta.source)
    g.comments = [g.tab] if meta.source else []
    track = g.tracks[0]
    track.name = "Acoustic Guitar"
    track.channel.instrument = 25  # Acoustic Guitar (steel)
    track.offset = meta.capo  # capo fret
    tuning = meta.tuning or STANDARD
    track.strings = [gp.GuitarString(i + 1, v) for i, v in enumerate(tuning)]
    ts = gp.TimeSignature(numerator=song.numerator,
                          denominator=gp.Duration(value=song.denominator))
    g.measureHeaders = []
    track.measures = []
    start = gp.Duration.quarterTime
    for i, m in enumerate(song.measures):
        header = gp.MeasureHeader(number=i + 1, start=start, timeSignature=ts)
        if song.triplet_feel:
            header.tripletFeel = (gp.TripletFeel.sixteenth if song.triplet_feel == "16th"
                                  else gp.TripletFeel.eighth)
        if getattr(m, "marker", None):
            header.marker = gp.Marker(title=m.marker)
        g.measureHeaders.append(header)
        measure = gp.Measure(track, header)
        track.measures.append(measure)
        voice = measure.voices[0]
        for b in m.beats:
            parts = split_ticks(b.duration)
            for k, (_, val, dot, trip) in enumerate(parts):
                beat = gp.Beat(voice, duration=gp_duration(val, dot, trip),
                               status=gp.BeatStatus.normal)
                voice.beats.append(beat)
                if b.column is None or not b.column.notes:
                    beat.status = gp.BeatStatus.rest
                    continue
                col = b.column
                if k == 0:
                    if getattr(col, "stroke", None):
                        beat.effect.stroke = gp.BeatStroke(
                            direction=gp.BeatStrokeDirection.down if col.stroke[0] == "down"
                            else gp.BeatStrokeDirection.up,
                            value=col.stroke[1])
                    if getattr(col, "chord", None):
                        beat.text = col.chord
                # one note per string: Guitar Pro cannot store two (the file would not read back)
                notes = list({n.string: n for n in sorted(col.notes, key=lambda n: -n.score)}.values())
                for n in sorted(notes, key=lambda n: n.string):
                    note = gp.Note(beat, string=n.string,
                                   value=0 if n.dead else n.fret)
                    if k > 0:  # continuation of a long note: tie
                        if n.dead:
                            continue
                        note.type = gp.NoteType.tie
                    else:
                        note.type = gp.NoteType.dead if n.dead else (
                            gp.NoteType.tie if getattr(n, "tied", False) else gp.NoteType.normal)
                        note.effect.letRing = meta.let_ring and not n.dead
                        note.effect.hammer = getattr(n, "hammer", False)
                        if getattr(n, "slide", False):
                            note.effect.slides = [gp.SlideType.legatoSlideTo]
                        note.effect.palmMute = getattr(n, "palm_mute", False)
                        note.effect.ghostNote = getattr(n, "ghost", False)
                        note.effect.vibrato = getattr(n, "vibrato", False)
                        if getattr(n, "harmonic", False):
                            note.effect.harmonic = gp.NaturalHarmonic()
                        if getattr(n, "bend", 0):
                            st = n.bend // 50  # semitones: 1 half, 2 full
                            note.effect.bend = gp.BendEffect(
                                type=gp.BendType.bend, value=n.bend,
                                points=[gp.BendPoint(0, 0), gp.BendPoint(6, st), gp.BendPoint(12, st)])
                        gr = next((x for x in col.grace if x.string == n.string), None)
                        if gr is not None:
                            note.effect.grace = gp.GraceEffect(
                                fret=0 if gr.dead else gr.fret, duration=32, isDead=gr.dead,
                                transition=gp.GraceEffectTransition.slide if getattr(gr, "slide", False)
                                else gp.GraceEffectTransition.hammer if getattr(gr, "hammer", False)
                                else gp.GraceEffectTransition.none)
                    beat.notes.append(note)
                if k == 0:
                    # grace notes on strings without a main note: sound them with the beat
                    main = {n.string for n in col.notes}
                    for gr in col.grace:
                        if gr.string not in main:
                            note = gp.Note(beat, string=gr.string, value=0 if gr.dead else gr.fret,
                                           type=gp.NoteType.dead if gr.dead else gp.NoteType.normal)
                            note.effect.letRing = meta.let_ring and not gr.dead
                            beat.notes.append(note)
                            main.add(gr.string)
        start += sum(b.duration for b in m.beats) * gp.Duration.quarterTime // TICKS_PER_QUARTER
    gp.write(g, path, version=(5, 1, 0))
