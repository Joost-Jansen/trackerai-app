"""Render a Song as plain ASCII tab (readable anywhere, also handy for checking)."""
from .assemble import TICKS_PER_QUARTER, Song

STRINGS = "eBGDAE"


def to_ascii(song: Song, per_line: int = 4, cell: int = 2) -> str:
    """One character cell per 16th note; triplet positions are rounded to the nearest 16th."""
    step = TICKS_PER_QUARTER // 4
    out = [f"Tempo {song.tempo}  Time {song.numerator}/{song.denominator}", ""]
    for i in range(0, len(song.measures), per_line):
        chunk = song.measures[i:i + per_line]
        rows = [f"{s}|" for s in STRINGS]
        head = "  "
        for m in chunk:
            ticks = sum(b.duration for b in m.beats)
            width = ticks // step * (cell + 1)
            cols = [["-"] * width for _ in STRINGS]
            for b in m.beats:
                if b.column is None or not b.column.notes:
                    continue
                pos = round(b.start / step) * (cell + 1)
                for n in b.column.notes:
                    txt = "x" if n.dead else str(n.fret)
                    for k, ch in enumerate(txt):
                        if pos + k < width:
                            cols[n.string - 1][pos + k] = ch
                for n in b.column.grace:  # grace note: lower case g marker one cell earlier
                    p = max(pos - 2, 0)
                    cols[n.string - 1][p] = "x" if n.dead else str(n.fret)[-1]
            for r in range(6):
                rows[r] += "".join(cols[r]) + "|"
            head += str(m.number).ljust(width + 1)
        out += [head] + rows + [""]
    return "\n".join(out)
