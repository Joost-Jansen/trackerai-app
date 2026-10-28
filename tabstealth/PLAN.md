# tabstealth: plan for the next features

Built in this order; each step ends with its tests green and is usable on its own. **Status: steps 1 to 7 are
built** (2026-10-28). Harmonics are checked on real videos; ghost notes, palm mute, bends and vibrato are read with
tested rules, but none of the five test videos has them, so they are not yet checked on real footage.

## 1. The song in the top bar

On a song page the top bar shows the song instead of "Library": a back chevron, the title with artist, tempo, capo
and swing below it, the download / text / restore icons, and the transport (play, stop, sound switch). The layout
offers two slots (`topbar-title`, `topbar-actions`) that the song page fills; other pages keep their title. On a phone
the meta line and the download icons fold into a small menu so the transport keeps its room.

## 2. Undo, redo and keyboard editing

- **Undo/redo on the server**, so it survives a reload: every change (beat, section, restore) first saves the current
  `.gp5` to `library/.history/<id>/undo/`; undo moves it back and the current file to `redo/`; a new change clears
  `redo/`. Endpoints `POST /api/songs/{id}/undo|redo`, `GET /api/songs/{id}/history` (can undo, can redo). Up to 100
  steps. Buttons in the editor, and Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z.
- **Keyboard editing** while a beat is selected and the focus is not in a field: ←/→ previous/next beat (across bars),
  ↑/↓ the active string, digits type the fret (two digits within a moment), `x` dead, Backspace clears the string,
  `h` hammer-on, `/` slide, `t` tie, `r` let ring, `m` palm mute, `g` ghost, `n` harmonic, `v` vibrato, `b` bend
  (none, ½, full), Enter saves, Esc closes. Moving to another beat saves a changed beat first. A `?` shows the keys.

## 3. Library basics

Per song a status (new, checking, learning, mastered), tags and a favourite star, kept in `library/meta.json`
(`PATCH /api/songs/{id}`). The library page gets a search field (title, artist, tags), sorting (artist, title, recently
added, recently practised, most practised) and filters by status, tag and "to review".

## 4. Practising

- **Loop a bar range**: "from bar … to bar …" (or shift-click two beats). Tab sound: alphaTab's playback range and loop.
  Video sound: the video jumps back to the range's start at its end (times from the timing map).
- **Speed trainer**: start at e.g. 60% and add 5% per pass up to a target, for both sound sources.
- **Count-in** (one bar of clicks before playing) and a **metronome** (a click on every beat): alphaTab's own for tab
  sound; for video sound a small Web Audio click scheduled from the bar times of the timing map.

## 5. Practice log and statistics

While something plays, the page reports practice to `POST /api/practice` (every 30 s and on pause): song, seconds,
speed, sound source, bar range. Stored in `library/practice.jsonl`. A new **Practice** page: minutes per day (last 30
days, bar chart), streak, minutes per song, the speed reached per song over time (line chart), and the status mix of
the library. The library sorts on it, and each song shows its last practice.

## 6. Review queue

The converter writes `<song>.review.json`: per bar the reasons to look at it: rhythm from note spacing, two notes on
one grid slot, a large timing error before rounding, a note read with low confidence, a misread measure number. The
song page gets a **Review** list: click a bar to select it, loop it in the video, fix it in the editor, and mark it
checked (`POST /api/songs/{id}/review`). The library shows "N to review" and filters on it.

## 7. More techniques read from the video

The converter learns: **harmonics** (`<12>`), **ghost notes** (`(3)`), **palm mute** (the "P.M." text and its dashes),
**bends** (the "full" / "½" label over the bend arrow) and **vibrato** (the wavy line above a note), written to the
`.gp5` like the others. The editor gets the bend (none, ½, full). The glyph classifier gets the `<`, `>`, `(`, `)`
shapes; text labels come from Tesseract.

## Out of scope for now

Rhythm editing (durations, splitting and merging beats), deleting songs, and accounts / hosting.
