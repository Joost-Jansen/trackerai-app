// Music theory for the guitar: notes and their spelling, scales and where they lie on the neck, the chords of a key,
// chord shapes, the circle of fifths and common progressions. Pure functions, no React (tests: theory.test.ts).

export const PITCHES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"] as const; // how the keys are named
const SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const LETTERS = ["C", "D", "E", "F", "G", "A", "B"];
const LETTER_PC: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/** Standard tuning, string 6 (low E) to string 1 (high e), as MIDI pitches. */
export const STANDARD = [40, 45, 50, 55, 59, 64];

export type ScaleId =
  | "major" | "minor" | "harmonicMinor" | "melodicMinor" | "majorPentatonic" | "minorPentatonic" | "blues"
  | "dorian" | "phrygian" | "lydian" | "mixolydian" | "locrian";

/** Semitones above the root. */
export const SCALES: Record<ScaleId, number[]> = {
  major: [0, 2, 4, 5, 7, 9, 11],
  minor: [0, 2, 3, 5, 7, 8, 10],
  harmonicMinor: [0, 2, 3, 5, 7, 8, 11],
  melodicMinor: [0, 2, 3, 5, 7, 9, 11],
  majorPentatonic: [0, 2, 4, 7, 9],
  minorPentatonic: [0, 3, 5, 7, 10],
  blues: [0, 3, 5, 6, 7, 10],
  dorian: [0, 2, 3, 5, 7, 9, 10],
  phrygian: [0, 1, 3, 5, 7, 8, 10],
  lydian: [0, 2, 4, 6, 7, 9, 11],
  mixolydian: [0, 2, 4, 5, 7, 9, 10],
  locrian: [0, 1, 3, 5, 6, 8, 10],
};

export const SCALE_GROUPS: { id: "basics" | "pentatonic" | "modes"; scales: ScaleId[] }[] = [
  { id: "basics", scales: ["major", "minor", "harmonicMinor", "melodicMinor"] },
  { id: "pentatonic", scales: ["majorPentatonic", "minorPentatonic", "blues"] },
  { id: "modes", scales: ["dorian", "phrygian", "lydian", "mixolydian", "locrian"] },
];

/** Minor-flavoured scales: the circle of fifths reads their root on the inner (minor) ring. */
export const isMinorScale = (s: ScaleId) => SCALES[s][2] === 3 || SCALES[s][1] === 3;

export const pc = (n: number) => ((n % 12) + 12) % 12;
export const pitchOf = (name: string): number => {
  const base = LETTER_PC[name[0]];
  const acc = name.slice(1).split("").reduce((a, c) => a + (c === "#" ? 1 : c === "b" ? -1 : 0), 0);
  return pc(base + acc);
};

/** Keys written with flats: F and everything flatwards, and their relative minors. */
const FLAT_ROOTS = new Set([5, 10, 3, 8, 1, 6]); // F Bb Eb Ab Db Gb (major)
export function usesFlats(root: number, minor: boolean): boolean {
  return FLAT_ROOTS.has(minor ? pc(root + 3) : root) || (minor && root === 2) /* D minor = F major */;
}

/** The name of a pitch class in a key that uses sharps or flats. */
export const noteName = (p: number, flats: boolean) => (flats ? FLATS : SHARPS)[pc(p)];

/**
 * The notes of a scale, each spelled once: a seven-note scale uses every letter (F# major has E#, not F), the
 * others take the key's sharps or flats.
 */
export function spellScale(root: number, scale: ScaleId, rootName: string = PITCHES[pc(root)]): string[] {
  const steps = SCALES[scale];
  const flats = rootName.includes("b") || (!rootName.includes("#") && usesFlats(root, isMinorScale(scale)));
  if (steps.length !== 7) return steps.map((s) => noteName(root + s, flats));
  const start = LETTERS.indexOf(rootName[0]);
  return steps.map((s, i) => {
    const letter = LETTERS[(start + i) % 7];
    let diff = pc(root + s - LETTER_PC[letter]);
    if (diff > 6) diff -= 12;
    return letter + (diff > 0 ? "#".repeat(diff) : "b".repeat(-diff));
  });
}

const INTERVALS = ["1", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7"];
/** The interval name of a step in a scale (#4 in lydian, b5 in the blues scale). */
export const intervalName = (semitones: number, scale?: ScaleId) => (semitones === 6 && scale === "lydian" ? "#4" : INTERVALS[pc(semitones)]);

export type Dot = { string: number; fret: number; pitch: number; degree: number; interval: string; name: string; root: boolean };

/** Every scale note on the neck (string 1 = high e), up to `frets`. */
export function scaleOnNeck(root: number, scale: ScaleId, frets = 15, tuning = STANDARD): Dot[] {
  const steps = SCALES[scale];
  const names = spellScale(root, scale);
  const dots: Dot[] = [];
  tuning.forEach((open, i) => {
    const string = 6 - i;
    for (let fret = 0; fret <= frets; fret++) {
      const p = open + fret;
      const degree = steps.indexOf(pc(p - root));
      if (degree >= 0) dots.push({ string, fret, pitch: p, degree, interval: intervalName(steps[degree], scale), name: names[degree], root: degree === 0 });
    }
  });
  return dots;
}

/**
 * The positions (boxes) of a scale, as guitarists learn them: start on a scale note on the low E string and climb
 * the scale, two notes per string for a pentatonic (the five boxes), three per string for a seven-note scale. The
 * blues scale is its pentatonic box plus the blue note where it falls inside the box. One position per scale note on
 * the low E string, from the lowest; each is the set of its notes as "string-fret".
 */
export function positions(root: number, scale: ScaleId, tuning = STANDARD): { from: number; to: number; notes: Set<string> }[] {
  const steps = SCALES[scale];
  const blues = scale === "blues";
  const core = blues ? SCALES.minorPentatonic : steps;
  const perString = core.length === 5 ? 2 : 3;
  const inScale = (p: number) => core.includes(pc(p - root));
  const starts = core.map((s) => pc(root + s - tuning[0])).sort((a, b) => a - b);
  return starts.map((startFret) => {
    const notes = new Set<string>();
    let p = tuning[0] + startFret;
    const frets: number[] = [];
    tuning.forEach((open, i) => {
      for (let n = 0; n < perString; n++) {
        while (!inScale(p)) p++;
        frets.push(p - open);
        notes.add(`${6 - i}-${p - open}`);
        p++;
      }
    });
    if (blues) {
      // the b5 on each string, when it lies inside the box
      const lo = Math.min(...frets);
      const hi = Math.max(...frets);
      tuning.forEach((open, i) => {
        for (let f = lo; f <= hi; f++) if (pc(open + f - root) === 6) notes.add(`${6 - i}-${f}`);
      });
    }
    return { from: Math.min(...frets), to: Math.max(...frets), notes };
  });
}

// ── chords ───────────────────────────────────────────────────────────────────

export type Quality = "maj" | "m" | "dim" | "aug" | "maj7" | "7" | "m7" | "m7b5" | "dim7" | "mMaj7" | "maj7#5";
export const CHORD_STEPS: Record<Quality, number[]> = {
  maj: [0, 4, 7], m: [0, 3, 7], dim: [0, 3, 6], aug: [0, 4, 8],
  maj7: [0, 4, 7, 11], "7": [0, 4, 7, 10], m7: [0, 3, 7, 10], m7b5: [0, 3, 6, 10], dim7: [0, 3, 6, 9],
  mMaj7: [0, 3, 7, 11], "maj7#5": [0, 4, 8, 11],
};
const SUFFIX: Record<Quality, string> = {
  maj: "", m: "m", dim: "°", aug: "+", maj7: "maj7", "7": "7", m7: "m7", m7b5: "m7b5", dim7: "°7", mMaj7: "m(maj7)", "maj7#5": "maj7#5",
};
const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"];

export type Chord = { root: number; rootName: string; quality: Quality; name: string; roman: string; tones: number[] };

export function qualityOf(steps: number[]): Quality {
  const key = steps.join(",");
  return (Object.entries(CHORD_STEPS).find(([, s]) => s.join(",") === key)?.[0] as Quality) ?? "maj";
}

export function chord(root: number, quality: Quality, rootName: string = PITCHES[pc(root)], roman = ""): Chord {
  return { root: pc(root), rootName, quality, name: rootName + SUFFIX[quality], roman, tones: CHORD_STEPS[quality].map((s) => pc(root + s)) };
}

/** The chords of a seven-note scale, built on every degree by stacking thirds (triads, or with the seventh). */
export function chordsInKey(root: number, scale: ScaleId, sevenths = false): Chord[] {
  const steps = SCALES[scale];
  if (steps.length !== 7) return [];
  const names = spellScale(root, scale);
  return steps.map((_, i) => {
    const take = (k: number) => pc(steps[(i + k) % 7] - steps[i]);
    const q = qualityOf(sevenths ? [0, take(2), take(4), take(6)] : [0, take(2), take(4)]);
    const minorish = q === "m" || q === "m7" || q === "dim" || q === "m7b5" || q === "dim7" || q === "mMaj7";
    let roman = minorish ? ROMAN[i].toLowerCase() : ROMAN[i];
    if (q === "dim" || q === "dim7") roman += "°";
    else if (q === "m7b5") roman += "ø";
    else if (q === "aug" || q === "maj7#5") roman += "+";
    return chord(root + steps[i], q, names[i], roman);
  });
}

/** A chord by roman numeral in a major or minor key ("vi", "V7", "bVII"), for the progressions. */
export function chordFromRoman(key: number, minor: boolean, numeral: string): Chord {
  const m = /^(b?)([ivIV]+)(°|7|maj7|m7)?$/.exec(numeral);
  if (!m) throw new Error(`bad numeral ${numeral}`);
  const [, flat, rn, ext] = m;
  const degree = ROMAN.indexOf(rn.toUpperCase());
  // a flat numeral (bVII) is counted from the major scale, as is the custom; the others from the key's own scale
  const root = flat ? pc(key + SCALES.major[degree] - 1) : pc(key + SCALES[minor ? "minor" : "major"][degree]);
  const lower = rn === rn.toLowerCase();
  const q: Quality = ext === "°" ? "dim" : ext === "7" ? (lower ? "m7" : "7") : ext === "maj7" ? "maj7" : ext === "m7" ? "m7" : lower ? "m" : "maj";
  const name = flat ? noteName(root, true) : spellScale(key, minor ? "minor" : "major")[degree];
  return chord(root, q, name, numeral);
}

export const PROGRESSIONS: { id: string; minor: boolean; numerals: string[] }[] = [
  { id: "pop", minor: false, numerals: ["I", "V", "vi", "IV"] },
  { id: "fifties", minor: false, numerals: ["I", "vi", "IV", "V"] },
  { id: "classic", minor: false, numerals: ["I", "IV", "V", "I"] },
  { id: "jazz", minor: false, numerals: ["ii7", "V7", "Imaj7"] },
  { id: "sad", minor: false, numerals: ["vi", "IV", "I", "V"] },
  { id: "blues", minor: false, numerals: ["I7", "I7", "I7", "I7", "IV7", "IV7", "I7", "I7", "V7", "IV7", "I7", "V7"] },
  { id: "minorPop", minor: true, numerals: ["i", "bVI", "bIII", "bVII"] },
  { id: "andalusian", minor: true, numerals: ["i", "bVII", "bVI", "V"] },
  { id: "minorClassic", minor: true, numerals: ["i", "iv", "v", "i"] },
];

// ── chord shapes ─────────────────────────────────────────────────────────────

/** Frets from string 6 (low E) to string 1, -1 = not played. */
export type Shape = number[];

const OPEN: Record<string, string> = {
  C: "x32010", D: "xx0232", E: "022100", F: "133211", G: "320003", A: "x02220", B: "x24442",
  Cm: "x35543", Dm: "xx0231", Em: "022000", Fm: "133111", Gm: "355333", Am: "x02210", Bm: "x24432",
  C7: "x32310", D7: "xx0212", E7: "020100", G7: "320001", A7: "x02020", B7: "x21202",
  Dm7: "xx0211", Em7: "020000", Am7: "x02010", Cmaj7: "x32000", Dmaj7: "xx0222", Fmaj7: "xx3210", Gmaj7: "320002", Amaj7: "x02120",
};
// Movable shapes as offsets from the root fret, null = string not played: on the low E string (E-shape) and on the A
// string (A-shape). Some reach a fret below the root (the b5 of an E-shape m7b5).
const E_SHAPE: Partial<Record<Quality, (number | null)[]>> = {
  maj: [0, 2, 2, 1, 0, 0], m: [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0], m7: [0, 2, 0, 0, 0, 0], maj7: [0, null, 1, 1, 0, null],
  m7b5: [0, null, 0, 0, -1, null], dim7: [0, null, -1, 0, -1, null], dim: [0, 1, 2, 0, null, null], aug: [0, 3, 2, 1, 1, 0],
};
const A_SHAPE: Partial<Record<Quality, (number | null)[]>> = {
  maj: [null, 0, 2, 2, 2, 0], m: [null, 0, 2, 2, 1, 0], "7": [null, 0, 2, 0, 2, 0], m7: [null, 0, 2, 0, 1, 0], maj7: [null, 0, 2, 1, 2, 0],
  m7b5: [null, 0, 1, 0, 1, null], dim: [null, 0, 1, 2, 1, null], dim7: [null, 0, 1, 2, 1, 2], aug: [null, 0, 3, 2, 2, null],
  mMaj7: [null, 0, 2, 1, 1, 0],
};

const parse = (s: string): Shape => s.split("").map((c) => (c === "x" ? -1 : Number(c)));

/** A playable shape: the open chord when there is a common one, else a barre shape (E- or A-shape, the lower). */
export function shapeFor(c: Chord): Shape | null {
  const key = noteName(c.root, false) + (c.quality === "maj" ? "" : c.quality);
  const flatKey = noteName(c.root, true) + (c.quality === "maj" ? "" : c.quality);
  const open = OPEN[key] ?? OPEN[flatKey];
  if (open) return parse(open);
  const options: Shape[] = [];
  for (const [shape, string] of [[E_SHAPE, 0], [A_SHAPE, 1]] as const) {
    const offs = shape[c.quality];
    if (!offs) continue;
    let base = pc(c.root - STANDARD[string]);
    if (offs.some((o) => o !== null && base + o < 0)) base += 12; // reaches below the nut: play it an octave up
    options.push(offs.map((o) => (o === null ? -1 : base + o)));
  }
  if (!options.length) return null;
  const low = (sh: Shape) => Math.min(...sh.filter((f) => f >= 0));
  return options.sort((a, b) => low(a) - low(b))[0];
}

/** Notes of a shape as MIDI pitches (to strum it). */
export const shapePitches = (shape: Shape, tuning = STANDARD) => shape.flatMap((f, i) => (f < 0 ? [] : [tuning[i] + f]));

// ── circle of fifths ─────────────────────────────────────────────────────────

/** Major keys round the circle, from C clockwise; each with its relative minor and its sharps (+) or flats (-). */
export const CIRCLE = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5].map((root, i) => ({
  root,
  name: ["C", "G", "D", "A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F"][i],
  minor: ["Am", "Em", "Bm", "F#m", "C#m", "G#m", "D#m", "Bbm", "Fm", "Cm", "Gm", "Dm"][i],
  accidentals: [0, 1, 2, 3, 4, 5, 6, -5, -4, -3, -2, -1][i],
}));

/** The frequency of a MIDI pitch. */
export const hz = (midi: number) => 440 * 2 ** ((midi - 69) / 12);
