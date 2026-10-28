# tabstealth

**Tabs from guitar videos, playable and in sync with the video.**

Many guitar channels (Kenneth Acoustic, for one) show the tab of the song in a strip under the video: a Guitar Pro
rendering that scrolls along, with a playback cursor. tabstealth reads that strip and turns it into a real Guitar Pro 5
file, then plays it next to the original video.

- **Converter** (`api/tabreader`): stitches the scrolling views into one tab line (anchored on the measure numbers and
  the cursor, so a repeating riff cannot fool it), reads the frets per string with a glyph classifier trained on the
  Guitar Pro font, and takes the rhythm from the video's own playback cursor: every note's onset is the moment the
  cursor passes it. On top: rests, 16th and triplet grids, swing (Guitar Pro's triplet feel), grace notes, dead notes,
  hammer-ons and pull-offs, slides, ties, strums and arpeggios, chord names, sections, tempo, tuning and capo.
- **Player** (`web`): the video and the tab side by side. Choose what you hear: the video (the tab cursor follows) or
  the tab, at any speed and in a loop (the video follows, muted). Click a beat to jump there and to correct its frets;
  edits go straight into the `.gp5`, and the converter's version is kept for a restore.
- **Library**: paste a YouTube link (a video or a playlist) and it converts in the background.

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
