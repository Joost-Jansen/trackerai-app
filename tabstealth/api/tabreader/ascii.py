"""Plain-text tab from a Guitar Pro file: readable anywhere, and always the file's current state (edits included).

One cell (three characters) per 16th note; a triplet lands on its nearest 16th. Above the strings: the section and the
measure number, the chord names, and the strum of each beat. In the strings:

  7   fret          x   dead note        h / p   hammer-on / pull-off to the next note on the string
  /   slide up      \\   slide down       a tied note keeps ringing: no number   a grace note sits two characters
  ^   downstroke    v   upstroke         ~       arpeggio (rolled chord)            before its beat
  <12> harmonic     (3) ghost note       7b      bend                7~  vibrato
"""

import guitarpro as gp

STRINGS = "eBGDAE"
CELL = 3
SIXTEENTH = gp.Duration.quarterTime // 4
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _next_on_string(beats: list, i: int, string: int):
    for b in beats[i + 1 :]:
        for n in b.notes:
            if n.string == string:
                return n
    return None


def _tuning_name(track) -> str:
    pitches = [s.value for s in track.strings]
    if pitches == [64, 59, 55, 50, 45, 40]:
        return "Standard"
    return "".join(NOTE_NAMES[p % 12] for p in reversed(pitches))


def gp5_to_ascii(path: str, per_line: int = 4) -> str:
    song = gp.parse(path)
    track = song.tracks[0]
    flat = [b for m in track.measures for b in m.voices[0].beats]
    index = {id(b): i for i, b in enumerate(flat)}  # by identity: the models compare by value, which is slow
    head = [
        f"{song.title} - {song.artist}".strip(" -"),
        f"Tempo {song.tempo}   Tuning {_tuning_name(track)}   Capo {track.offset or 'none'}",
    ]
    if song.tab:
        head.append(song.tab)
    out = head + ["", __doc__.split("\n\n", 1)[1].rstrip(), ""]
    for start in range(0, len(track.measures), per_line):
        rows = [f"{s}|" for s in STRINGS]
        nums, chords, strums = "  ", "  ", "  "
        for m in track.measures[start : start + per_line]:
            header = m.header
            ticks = header.timeSignature.numerator * gp.Duration.quarterTime * 4 // header.timeSignature.denominator.value
            width = max(1, round(ticks / SIXTEENTH)) * CELL
            cols = [[*("-" * width)] for _ in STRINGS]
            top = [*(" " * (width + 1))]
            strum = [*(" " * (width + 1))]
            pos = 0
            for b in m.voices[0].beats:
                x = min(round(pos / SIXTEENTH) * CELL, width - 1)
                pos += b.duration.time
                if b.text:
                    for k, ch in enumerate(str(b.text)[: width - x]):
                        top[x + k] = ch
                stroke = b.effect.stroke
                if stroke and stroke.direction != gp.BeatStrokeDirection.none:
                    strum[x] = (
                        "~" if stroke.value and stroke.value <= 16 else ("^" if stroke.direction == gp.BeatStrokeDirection.down else "v")
                    )
                i = index[id(b)]
                for n in b.notes:
                    row = cols[n.string - 1]
                    if n.type == gp.NoteType.dead:
                        txt = "x"
                    elif n.type == gp.NoteType.tie:
                        continue  # a tied note keeps ringing: nothing new to play
                    else:
                        txt = str(n.value)
                    e = n.effect
                    if e.harmonic is not None:
                        txt = f"<{txt}>"
                    if e.ghostNote:
                        txt = f"({txt})"
                    if e.bend is not None:
                        txt += "b"
                    if e.vibrato:
                        txt += "~"
                    nxt = _next_on_string(flat, i, n.string)
                    if n.effect.hammer and nxt is not None:
                        txt += "h" if nxt.value > n.value else "p"
                    elif n.effect.slides and nxt is not None:
                        txt += "/" if nxt.value >= n.value else "\\"
                    for k, ch in enumerate(txt):
                        if x + k < width:
                            row[x + k] = ch
                    g = n.effect.grace
                    if g is not None and x >= 2:
                        row[x - 2] = "x" if g.isDead else str(g.fret)[-1]
            for r in range(6):
                rows[r] += "".join(cols[r]) + "|"
            label = str(header.number) + (f" {header.marker.title}" if header.marker else "")
            nums += label[:width].ljust(width + 1)
            chords += "".join(top)
            strums += "".join(strum)
        block = [nums.rstrip()]
        if chords.strip():
            block.append(chords.rstrip())
        if strums.strip():
            block.append(strums.rstrip())
        out += block + rows + [""]
    return "\n".join(out)
