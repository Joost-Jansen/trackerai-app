"""Text in the video via Tesseract: section labels, chord names, tuning and capo."""

import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from .glyphs import gray

# A chord name: root, quality and number, then extensions that each start with a letter, # or b, or "(" (so a run of
# digits belongs to one of them only: no ambiguous repetition that can backtrack), then a bass note.
CHORD_RE = re.compile(
    r"^[A-G][#b]?(?:maj|min|dim|aug|sus|add|m|M)?[0-9]*"
    r"(?:sus[24]?|add[0-9]+|maj[0-9]*|[b#][0-9]+|\([^)]*\))*(?:/[A-G][#b]?)?$"
)
NOTE_PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
STANDARD = [64, 59, 55, 50, 45, 40]


def available() -> bool:
    return shutil.which("tesseract") is not None


def tesseract(img: np.ndarray, psm: int = 7, extra: tuple[str, ...] = ()) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        cv2.imwrite(f.name, img)
        r = subprocess.run(["tesseract", f.name, "stdout", "--psm", str(psm), *extra], capture_output=True, text=True)
    return r.stdout.strip()


def _prep(img: np.ndarray, invert: bool = False, scale: float = 2.0) -> np.ndarray:
    g = gray(img)
    if invert:
        g = 255 - g
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def section_name(crop: np.ndarray) -> str | None:
    """Section label: light text at the left of the dark bar."""
    g = gray(crop)
    if g.mean() > 150:  # bar not dark: no label here
        return None
    light = (g > 170).astype(np.uint8)
    cols = np.where(light.sum(axis=0) > 0)[0]
    if len(cols) == 0:
        return None
    # the label is the first cluster of text from the left
    gaps = np.where(np.diff(cols) > crop.shape[0])[0]
    end = cols[gaps[0]] if len(gaps) else cols[-1]
    txt = tesseract(_prep(crop[:, : end + 10], invert=True))
    txt = re.sub(r"[^A-Za-z0-9 '\-]", "", txt).strip()
    return section_label(txt)


SECTIONS = [
    "Intro",
    "Verse",
    "Pre-Chorus",
    "Chorus",
    "Post-Chorus",
    "Bridge",
    "Solo",
    "Break",
    "Interlude",
    "Instrumental",
    "Riff",
    "Theme",
    "Hook",
    "Refrain",
    "Coda",
    "Ending",
    "Outro",
]


def _near(a: str, b: str) -> bool:
    """Equal, or one letter off (Sols, Solb -> Solo) for words of four letters or more."""
    if a == b:
        return True
    if len(b) < 4 or abs(len(a) - len(b)) > 1:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def section_label(txt: str) -> str | None:
    """The section a label names, as a known name plus its number: "Verse 2 For forty" (lyrics leaking in) ->
    "Verse 2", "Chorus a 7" -> "Chorus", "Sols" -> "Solo"; noise such as "tll is" -> None."""
    tokens = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?|\d+", txt)
    if not tokens:
        return None
    name = next((n for n in SECTIONS if _near(tokens[0].lower(), n.lower())), None)
    if name is None:
        return None
    nxt = tokens[1] if len(tokens) > 1 else ""
    num = "1" if nxt in ("I", "l") else nxt if nxt.isdigit() and 1 <= int(nxt) <= 6 else ""
    return f"{name} {num}" if num else name


def chord_names(tape_img: np.ndarray, lines: list[float]) -> list[tuple[float, str]]:
    """(x centre, chord) for chord names written above the staff."""
    sp = (lines[-1] - lines[0]) / 5
    y1 = int(lines[0] - 1.3 * sp)
    band = tape_img[:y1]
    ink = (gray(band) < 130).astype(np.uint8)
    blobs = cv2.dilate(ink, np.ones((3, int(0.5 * sp)), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(blobs)
    out = []
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if h < 0.5 * sp or h > 1.6 * sp or w < 0.4 * sp:
            continue
        crop = band[max(0, y - 4) : y + h + 4, max(0, x - 4) : x + w + 4]
        txt = tesseract(_prep(crop, scale=3.0), psm=7)
        txt = txt.replace("♯", "#").replace("♭", "b").replace(" ", "")
        txt = re.sub(r"(?<=[A-G])[♯]", "#", txt)
        if CHORD_RE.match(txt):
            out.append((x + w / 2, txt))
    return out


def tuning_capo(corner: np.ndarray) -> tuple[list[int], int, str]:
    """Parse 'Tuning: ...' and 'Capo: ...' text. Returns (tuning, capo fret, raw text)."""
    txt = tesseract(_prep(corner), psm=6)
    tuning, capo = STANDARD, 0
    m = re.search(r"Capo\s*[:.]?\s*(?:fret\s*)?(\w+)", txt, re.I)
    if m:
        v = m.group(1)
        roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}
        capo = int(v) if v.isdigit() else roman.get(v.upper(), 0)
    m = re.search(r"Tuning\s*:?\s*([^\n]+)", txt, re.I)
    if m:
        tuning = parse_tuning(m.group(1).strip()) or STANDARD
    return tuning, capo, txt


def parse_tuning(name: str) -> list[int] | None:
    n = name.lower().replace(" ", "")
    if n.startswith("standard") or n == "eadgbe":
        return STANDARD
    if n.startswith("dropd"):
        return [64, 59, 55, 50, 45, 38]
    if n.startswith("halfstep") or n.startswith("eb") or n.startswith("e♭"):
        return [p - 1 for p in STANDARD]
    # explicit six note names low->high, e.g. DADGAD, DGDGBD, CGDGBD
    notes = re.findall(r"[A-G][#b]?", name)
    if len(notes) == 6:
        base = [40, 45, 50, 55, 59, 64]  # nearest to standard pitch, low -> high
        out = []
        for ref, nm in zip(base, notes):
            pc = (NOTE_PITCH[nm[0]] + (1 if "#" in nm else -1 if nm.endswith("b") else 0)) % 12
            cands = [p for p in range(ref - 6, ref + 6) if p % 12 == pc]
            out.append(min(cands, key=lambda p: abs(p - ref)))
        return out[::-1]
    return None


def words_above_staff(img: np.ndarray, lines: list[float], window: int = 3000) -> list[tuple[int, int, int, int, str]]:
    """(x, y, w, h, text) of every word between the chord names and the top string (tape coordinates):
    where Guitar Pro writes P.M., bend amounts and harmonic marks."""
    sp = (lines[-1] - lines[0]) / 5
    y0, y1 = max(0, int(lines[0] - 2.6 * sp)), int(lines[0] - 0.1 * sp)
    out, seen = [], set()
    for x0 in range(0, img.shape[1], window):
        crop = gray(img[y0:y1, x0 : x0 + window + 200])
        big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            cv2.imwrite(f.name, big)
            tsv = subprocess.run(["tesseract", f.name, "stdout", "--psm", "11", "tsv"], capture_output=True, text=True).stdout
        for row in tsv.splitlines()[1:]:
            c = row.split("\t")
            if len(c) < 12 or not c[11].strip():
                continue
            x, y, w, h = (int(v) // 2 for v in c[6:10])
            key = (x + x0) // 10
            if key in seen:
                continue  # the overlap between windows
            seen.add(key)
            out.append((x + x0, y + y0, w, h, c[11].strip()))
    return out
