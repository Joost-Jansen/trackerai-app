# tabstealth

**Tabs from guitar videos, playable and in sync with the video.**

Many guitar channels (Kenneth Acoustic, for one) show the tab of the song in a strip under the video: a Guitar Pro
rendering that scrolls along, with a playback cursor. tabstealth reads that strip and turns it into a real Guitar Pro 5
file, then plays it next to the original video.

- **Converter** (`api/tabreader`): stitches the scrolling views into one tab line (anchored on the measure numbers and
  the cursor, so a repeating riff cannot fool it), reads the frets per string with a glyph classifier trained on the
  Guitar Pro font, and takes the rhythm from the video's own playback cursor: every note's onset is the moment the
  cursor passes it. On top: rests, 16th and triplet grids, swing (Guitar Pro's triplet feel), grace notes, dead notes,
  hammer-ons and pull-offs, slides, ties, strums and arpeggios, harmonics (`<12>`), ghost notes, palm mute, bends,
  vibrato, chord names, sections, tempo, tuning and capo. It also lists the bars it was unsure about (review queue).
- **Player** (`web`): the video and the tab side by side. Choose what you hear: the video (the tab cursor follows) or
  the tab, at any speed and in a loop (the video follows, muted). Click a beat to jump there and edit it: per string
  the fret (or `x`), a grace note and the techniques (hammer-on/pull-off, slide, tie, let ring, palm mute, ghost note,
  harmonic, vibrato); for the beat its strum (down, up, arpeggio) and chord name; for the bar its section. The editor
  reads the beat from the `.gp5` itself, so nothing the converter wrote is lost, and what it does not show (a bend)
  stays. Edits go straight into the file; the converter's version is kept for a restore.
  Undo and redo (also after a reload), and keyboard editing: arrows, digits, letters for the techniques.
- **Practising**: loop a bar range, a speed trainer that speeds up every pass, count-in and metronome, with either
  sound source. Playing time is logged; the **Practice** page shows minutes per day and per song, the streak and the
  speed reached per song.
- **Review queue**: the bars the converter was unsure about, with why; go there, loop it, fix it, tick it off.
- **Text tab**: rendered from the current `.gp5`, edits included, with sections, chords, strums and technique marks.
- **Library**: paste a YouTube link (a video or a playlist) and it converts in the background; or keep a video as it
  is (a lick or a lesson with no tab to read: speed and an A-B loop, convertible later), or upload a PDF (a tab, a
  chord sheet). Search, sort, filter by kind, status (new, checking, learning, mastered), tag, favourite or "to review".
- **Theory**: one interactive neck for a key and a scale (major, the minors, pentatonic and blues, the modes): every
  note by name or interval, the positions as guitarists learn them, or every note on the neck; the chords of the key
  as chord boxes, a clickable circle of fifths and common progressions in the key. Click to hear a note, play the
  scale, strum a chord.

The `.gp5` files open in [TuxGuitar](https://www.tuxguitar.app/) (the closest open-source match to Guitar Pro 8),
MuseScore and Guitar Pro itself; the player renders them with [alphaTab](https://alphatab.net/).

**Just for you.** The tabs are the work of the people who make the videos, who often sell them too. tabstealth is a
personal practice tool: it has no accounts yet, binds to localhost, and is not deployed. Do not host it publicly or
share the converted files; support the creators whose tabs you use.

## Run it

System tools: `ffmpeg`, `yt-dlp` and, for chord names, sections, tuning and capo, `tesseract`
(`brew install ffmpeg yt-dlp tesseract`).

```bash
cd tabstealth/api
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
TABSTEALTH_DATA=~/tabstealth-data .venv/bin/uvicorn app:create_app --factory --host 127.0.0.1 --port 8770
```

```bash
npm install            # at the repo root: one workspace, one lockfile
npm run dev --workspace tabstealth-web    # http://localhost:3070
```

`TABSTEALTH_DATA` holds everything the converter downloads and writes (`videos/<id>/` caches, `library/` the songs);
keep it outside the repository. Converting from the command line works too:

```bash
TABSTEALTH_DATA=~/tabstealth-data .venv/bin/python -m tabreader "https://www.youtube.com/watch?v=…"
TABSTEALTH_DATA=~/tabstealth-data .venv/bin/python -m tabreader --playlist "https://www.youtube.com/playlist?list=…" \
  --cookies-from-browser chrome   # only for a private playlist
```

Each conversion writes `report.json` next to its cache: measures, tempo, swing, capo, the number of misread measure
numbers and low-confidence notes, and the measures whose rhythm came from note spacing instead of the cursor (look at
those first).

## Tests

- `api/`: `python -m pytest -q` (rhythm, swing, durations, the API on a temporary library).
- `web/`: `npx tsc --noEmit -p .`, `npm run check:i18n`, `npm test` (the video/tab clock).
