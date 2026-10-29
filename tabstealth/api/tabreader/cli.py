"""tabreader: convert scrolling-tab guitar videos (e.g. Kenneth Acoustic) into Guitar Pro 5 files.

  python -m tabreader VIDEO_URL_OR_ID [...]          one or more videos
  python -m tabreader --playlist URL [--cookies-from-browser chrome]
"""
import argparse
import filecmp
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import effects, ocr
from .ascii import gp5_to_ascii
from .assemble import build_song
from .export import Meta, write_gp5
from .meter import read_tempo_mark
from .pages import build_pages, stable_runs
from .glyphs import find_barlines, gray
from .parse import Classifier, parse_page, read_number
from .scan import detect_staff, scan
from .stitch import cursor_shift, stitch

# Everything the converter downloads, caches and writes lives under TABSTEALTH_DATA:
#   videos/<id>/   download, frame scan cache, stitched tape image, report.json
#   library/       the converted songs (.gp5, .txt, .timing.json) and index.json
DATA = Path(os.environ.get("TABSTEALTH_DATA", Path(__file__).resolve().parent.parent / "data"))
LIBRARY = DATA / "library"
VIDEO_FORMAT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/b[height<=1080]"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def video_id(s: str) -> str:
    """The 11-character id from a YouTube link, or the id itself. Anything else is refused: an id becomes a folder
    and a library key ("a b c" from an unsplit shell variable once made a second entry for an existing song)."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", s)
    vid = m.group(1) if m else s.strip()
    if not re.fullmatch(r"[\w-]{11}", vid):
        raise ValueError(f"not a YouTube link or video id: {s!r}")
    return vid


def yt(args: list[str], cookies: str | None) -> subprocess.CompletedProcess:
    cmd = ["yt-dlp", *(["--cookies-from-browser", cookies] if cookies else []), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def playlist_ids(url: str, cookies: str | None) -> list[tuple[str, str]]:
    r = yt(["--flat-playlist", "--print", "%(id)s\t%(title)s", url], cookies)
    if r.returncode != 0:
        raise SystemExit(f"could not read playlist: {r.stderr.strip().splitlines()[-1]}\n"
                         "If the playlist is private, add --cookies-from-browser chrome "
                         "(or make it unlisted).")
    return [tuple(line.split("\t", 1)) for line in r.stdout.splitlines() if "\t" in line]


def split_title(title: str) -> tuple[str, str]:
    """'Song - Artist | Fingerstyle Guitar | TAB ...' -> (song, artist)."""
    main = title.split("|")[0].strip()
    if " - " in main:
        a, b = main.split(" - ", 1)
        return a.strip(), b.strip()
    return main, ""


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "", name).strip()


def view_numbers(img, lines, clf) -> dict[int, int]:
    """{measure number: bar x} for the bar lines of one view."""
    bars = find_barlines((gray(img) < 150).astype(np.uint8), lines)
    return {n: x for x in bars if (n := read_number(img, lines, x, clf)) is not None}


REVIEW_TIMING = 0.08  # quarter notes: an onset this far from its grid slot was a guess


def review_list(song, parsed) -> list[dict]:
    """Per bar (0-based, as in the .gp5) the reasons to check it by ear: what the converter was unsure about."""
    by_number = {m.number: m for m in parsed.measures if m.number is not None}
    out = []
    for i, m in enumerate(song.measures):
        reasons = []
        if "missing" in m.flags:
            reasons.append("missing")
        if "rhythm from note spacing" in m.flags:
            reasons.append("spacing")
        if "collision" in m.flags:
            reasons.append("collision")
        if m.timing_error > REVIEW_TIMING:
            reasons.append("timing")
        pm = by_number.get(m.number)
        if pm is not None:
            if any(n.score < 0.7 for c in pm.columns for n in c.notes + c.grace):
                reasons.append("low_confidence")
            read = parsed.numbers.get(pm.x0)
            if read is not None and read != m.number:
                reasons.append("number")
        if reasons:
            out.append({"bar": i, "reasons": reasons})
    return out


def video_timing(song, sc: dict, vid: str) -> dict:
    """Video time of every measure's downbeat, for syncing the player with the video."""
    starts = [m.t_start for m in song.measures]
    good = [i for i, m in enumerate(song.measures)
            if not np.isnan(m.t_start) and "rhythm from note spacing" not in m.flags]
    med = float(np.median(np.diff([starts[i] for i in good]))) if len(good) > 1 else 2.0
    for i in range(len(starts)):  # measures without cursor data: extend from neighbours
        if i not in good:
            prev = max((g for g in good if g < i), default=None)
            nxt = min((g for g in good if g > i), default=None)
            starts[i] = (starts[prev] + (i - prev) * med if prev is not None
                         else starts[nxt] - (nxt - i) * med)
    lines = sc["staff_lines"]
    sp = (lines[-1] - lines[0]) / 5
    frame_h = sc.get("frame_h", 1080)
    return {
        "video": vid,
        "measure_starts": [round(float(t), 3) for t in starts],
        "measure_seconds": round(med, 4),
        # top of the overlay (section bar) as a fraction of frame height: lets the
        # player crop the video to the hands while the tab is shown next to it
        "overlay_top": round(float(lines[0] - 7.2 * sp) / frame_h, 4),
    }


def convert(vid: str, out_dir: Path, cookies: str | None, keep_video: bool,
            force: bool = False, overwrite_edits: bool = False) -> dict:
    work = DATA / "videos" / vid
    work.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={vid}"
    info_p = work / "info.json"
    if not info_p.exists():
        r = yt(["--print", "%(title)s\t%(channel)s\t%(duration)s", url], cookies)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().splitlines()[-1])
        t, ch, dur = r.stdout.strip().split("\t")
        info_p.write_text(json.dumps({"title": t, "channel": ch, "duration": dur}))
    info = json.loads(info_p.read_text())
    song_name, artist = split_title(info["title"])
    log(f"{vid}: {info['title']}")

    video = work / "video.mp4"
    scan_p = work / "scan.pkl"
    if force or not scan_p.exists():
        if not video.exists():
            log("  downloading video")
            r = yt(["-q", "-f", VIDEO_FORMAT, "-o", str(video), url], cookies)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip().splitlines()[-1])
        log("  scanning frames")
        staff = detect_staff(str(video))
        sc = scan(str(video), staff, progress=False)
        runs = stable_runs(sc)
        log(f"  {len(runs)} stable views, building page images")
        pages = build_pages(str(video), sc)
        sc["page_images"] = [cv2.imencode(".png", p.image)[1] for p in pages]  # compact
        pickle.dump(sc, open(scan_p, "wb"))
    sc = pickle.load(open(scan_p, "rb"))
    if not keep_video and video.exists():
        video.unlink()

    lines = list(sc["staff_lines"] - sc["region"][0])
    runs = stable_runs(sc)
    clf = Classifier()
    log("  stitching views into one tab line")
    views = [cv2.imdecode(b, cv2.IMREAD_COLOR) for b in sc["page_images"]]
    numbers = [view_numbers(v, lines, clf) for v in views]
    shifts = [cursor_shift(sc["cursor"], ra, rb) for ra, rb in zip(runs, runs[1:])]
    tape = stitch(views, lines, numbers, shifts)
    cv2.imwrite(str(work / "tape.png"), tape.image)
    parsed = parse_page(tape.image, lines, clf)
    marks = {}
    if ocr.available():  # P.M., bend amounts and harmonic marks are words above the staff
        words = ocr.words_above_staff(tape.image, lines)
        cols = [c for m in parsed.measures for c in m.columns]
        marks = effects.text_marks(words, (gray(tape.image) < 150).astype(np.uint8), lines, cols)
    notes_all = [n for m in parsed.measures for c in m.columns for n in c.notes]
    marks.update(ghost=sum(n.ghost for n in notes_all), harmonic_brackets=sum(n.harmonic for n in notes_all),
                 vibrato=sum(n.vibrato for n in notes_all))
    misreads = sum(1 for m in parsed.measures if m.x0 in parsed.numbers
                   and parsed.numbers[m.x0] != m.number)
    tempo_mark = read_tempo_mark(tape.image, lines, parsed.bars[2] if len(parsed.bars) > 2
                                 else tape.image.shape[1], clf)
    song = build_song(parsed, tape.offsets, runs, sc, tempo_mark)
    log(f"  {len(song.measures)} measures, {song.numerator}/{song.denominator} at {song.tempo} bpm"
        f" (tempo mark: {tempo_mark}, swing: {song.triplet_feel or 'none'})")

    meta = Meta(title=song_name, artist=artist,
                source=f"Transcribed by tabreader from {url} ({info['channel']})")
    extras = {}
    if ocr.available():
        tuning, capo, raw = ocr.tuning_capo(sc["corner"])
        meta.tuning, meta.capo = tuning, capo
        extras["tuning_capo_text"] = raw
        # chord names above the staff -> attach to the nearest note column
        cols = [c for m in parsed.measures for c in m.columns]
        sp = (lines[-1] - lines[0]) / 5
        for x, name in ocr.chord_names(tape.image, lines):
            near = min(cols, key=lambda c: abs(c.x - x), default=None)
            if near is not None and abs(near.x - x) < 1.2 * sp:
                near.chord = name
        # section labels -> markers on the measure playing when the label changed
        fps = float(sc["fps"])
        starts = [(m.t_start, m) for m in song.measures if not np.isnan(m.t_start)]
        prev = None
        marked = []
        for f, crop in zip(sc["label_frames"], sc["label_crops"]):
            name = ocr.section_name(crop)
            if not name or name == prev:
                continue
            t = f / fps
            _, m = min(starts, key=lambda s: abs(s[0] - t))
            m.marker = name
            marked.append(m)
            prev = name
        # OCR often drops the "I" of "Verse I": number it when "Verse 2" exists
        names = {m.marker for m in marked}
        for m in marked:
            if f"{m.marker} 2" in names:
                m.marker = f"{m.marker} 1"
        # "Verse" and "Verse 1" alternating were two labels; after numbering they are one section
        last = None
        for m in sorted({id(m): m for m in marked}.values(), key=lambda m: m.t_start):
            if m.marker == last:
                m.marker = None
            else:
                last = m.marker
    else:
        log("  tesseract not found: skipping chord names, sections, tuning/capo")

    out_dir.mkdir(parents=True, exist_ok=True)
    name = safe(f"{artist} - {song_name}" if artist else song_name)
    gp5, txt = out_dir / f"{name}.gp5", out_dir / f"{name}.txt"
    timing = out_dir / f"{name}.timing.json"
    timing.write_text(json.dumps(video_timing(song, sc, vid)))
    orig = out_dir / f"{name}.orig.gp5"
    if orig.exists() and gp5.exists() and not filecmp.cmp(orig, gp5, shallow=False) and not overwrite_edits:
        log(f"  {gp5.name} has your edits: not overwritten (use --overwrite-edits)")
    else:
        write_gp5(song, str(gp5), meta)
        # a fresh conversion is the new original: no old backup or undo history to compare it with
        orig.unlink(missing_ok=True)
        shutil.rmtree(out_dir / ".history" / gp5.stem, ignore_errors=True)
    txt.write_text(gp5_to_ascii(str(gp5)))  # from the file itself, so an edited tab keeps its edits
    flagged = {m.number: m.flags for m in song.measures if m.flags}
    review = review_list(song, parsed)
    review_p = out_dir / f"{name}.review.json"
    review_p.write_text(json.dumps(review, indent=1))
    report = {
        "video": url, "title": info["title"], "measures": len(song.measures),
        "tempo": song.tempo, "time_signature": f"{song.numerator}/{song.denominator}",
        "swing": song.triplet_feel,
        "tempo_mark": tempo_mark, "capo": meta.capo, "tuning": meta.tuning,
        "measure_number_misreads": misreads, "views": len(runs),
        "stitch_min_score": round(float(min(tape.scores)), 3),
        "notes": sum(len(b.column.notes) for m in song.measures for b in m.beats if b.column),
        "low_confidence_notes": sum(1 for m in parsed.measures for c in m.columns
                                    for n in c.notes if n.score < 0.7),
        "flagged_measures": flagged, "techniques_read": marks, **extras,
    }
    (work / "report.json").write_text(json.dumps(report, indent=2, default=str))
    index_p = out_dir / "index.json"
    index = json.loads(index_p.read_text()) if index_p.exists() else {}
    index[vid] = {"file": gp5.name, "timing": timing.name, "text": txt.name, "review": review_p.name, "title": song_name,
                  "artist": artist, "measures": len(song.measures), "tempo": song.tempo,
                  "time_signature": f"{song.numerator}/{song.denominator}", "capo": meta.capo,
                  "swing": song.triplet_feel, "flagged": len(flagged),
                  "converted": time.strftime("%Y-%m-%d")}
    index_p.write_text(json.dumps(index, indent=2))
    log(f"  wrote {gp5}")
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="*", help="YouTube URLs or video ids")
    ap.add_argument("--playlist", help="YouTube playlist URL")
    ap.add_argument("--out", default=str(LIBRARY), help="output folder")
    ap.add_argument("--cookies-from-browser", dest="cookies",
                    help="browser to read YouTube cookies from (needed for private playlists)")
    ap.add_argument("--keep-video", action="store_true", help="keep downloaded videos")
    ap.add_argument("--force", action="store_true", help="re-scan even if cached")
    ap.add_argument("--overwrite-edits", action="store_true",
                    help="replace .gp5 files you edited in the player")
    a = ap.parse_args(argv)
    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp not found (brew install yt-dlp)")
    try:
        ids = [video_id(v) for v in a.videos]
    except ValueError as e:
        ap.error(str(e))
    if a.playlist:
        ids += [i for i, _ in playlist_ids(a.playlist, a.cookies)]
    if not ids:
        ap.error("give at least one video or --playlist")
    results, failed = [], []
    for vid in dict.fromkeys(ids):
        try:
            results.append(convert(vid, Path(a.out), a.cookies, a.keep_video, a.force,
                                   a.overwrite_edits))
        except Exception as e:  # keep going with the rest of the playlist
            log(f"  FAILED {vid}: {e}")
            failed.append((vid, str(e)))
    log(f"done: {len(results)} converted, {len(failed)} failed")
    for vid, err in failed:
        print(f"  {vid}: {err}")


if __name__ == "__main__":
    main()
