import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chordFromRoman, chordsInKey, CIRCLE, PROGRESSIONS, positions, scaleOnNeck, shapeFor, shapePitches, spellScale,
} from "./theory.ts";

test("scales are spelled with one letter each", () => {
  assert.deepEqual(spellScale(0, "major"), ["C", "D", "E", "F", "G", "A", "B"]);
  assert.deepEqual(spellScale(6, "major"), ["F#", "G#", "A#", "B", "C#", "D#", "E#"]);
  assert.deepEqual(spellScale(5, "major"), ["F", "G", "A", "Bb", "C", "D", "E"]);
  assert.deepEqual(spellScale(9, "minor"), ["A", "B", "C", "D", "E", "F", "G"]);
  assert.deepEqual(spellScale(9, "harmonicMinor"), ["A", "B", "C", "D", "E", "F", "G#"]);
  assert.deepEqual(spellScale(9, "minorPentatonic"), ["A", "C", "D", "E", "G"]);
  assert.deepEqual(spellScale(2, "minor", "D"), ["D", "E", "F", "G", "A", "Bb", "C"]);
});

test("a scale on the neck: A minor pentatonic box 1 at the 5th fret", () => {
  const dots = scaleOnNeck(9, "minorPentatonic", 12);
  const lowE = dots.filter((d) => d.string === 6).map((d) => d.fret);
  assert.deepEqual(lowE, [0, 3, 5, 8, 10, 12]);
  assert.ok(dots.find((d) => d.string === 6 && d.fret === 5)?.root);
  assert.equal(dots.find((d) => d.string === 3 && d.fret === 9)?.interval, "5");
  assert.equal(dots.find((d) => d.string === 3 && d.fret === 7)?.interval, "4");
  const boxes = positions(9, "minorPentatonic");
  assert.equal(boxes.length, 5);
  // box 1 of A minor pentatonic: 5-8 on the E strings, 5-7 in the middle
  const box1 = boxes.find((b) => b.from === 5)!;
  assert.equal(box1.to, 8);
  assert.deepEqual([...box1.notes].sort(), ["1-5", "1-8", "2-5", "2-8", "3-5", "3-7", "4-5", "4-7", "5-5", "5-7", "6-5", "6-8"]);
  // the box that starts on G (fret 3 of the low E) reaches back to fret 2 on the D and G strings
  const fromG = boxes.find((b) => b.from === 2)!;
  assert.ok(fromG.notes.has("4-2") && fromG.notes.has("3-2"));
  // three notes per string for a seven-note scale; the blues box adds the blue note
  assert.equal(positions(0, "major")[0].notes.size, 18);
  const bluesBox = positions(9, "blues").find((b) => b.from === 5)!;
  assert.ok(bluesBox.notes.has("5-6")); // Eb on the A string, the blue note of A blues
});

test("chords in a key, by stacking thirds", () => {
  assert.deepEqual(chordsInKey(0, "major").map((c) => c.name), ["C", "Dm", "Em", "F", "G", "Am", "B°"]);
  assert.deepEqual(chordsInKey(0, "major").map((c) => c.roman), ["I", "ii", "iii", "IV", "V", "vi", "vii°"]);
  assert.deepEqual(chordsInKey(0, "major", true).map((c) => c.name), ["Cmaj7", "Dm7", "Em7", "Fmaj7", "G7", "Am7", "Bm7b5"]);
  assert.deepEqual(chordsInKey(9, "minor").map((c) => c.name), ["Am", "B°", "C", "Dm", "Em", "F", "G"]);
  assert.deepEqual(chordsInKey(9, "harmonicMinor").map((c) => c.name)[4], "E");
  assert.deepEqual(chordsInKey(9, "minorPentatonic"), []);
});

test("progressions in a key", () => {
  const pop = PROGRESSIONS.find((p) => p.id === "pop")!;
  assert.deepEqual(pop.numerals.map((n) => chordFromRoman(7, false, n).name), ["G", "D", "Em", "C"]);
  assert.deepEqual(["ii7", "V7", "Imaj7"].map((n) => chordFromRoman(0, false, n).name), ["Dm7", "G7", "Cmaj7"]);
  assert.deepEqual(["i", "bVII", "bVI", "V"].map((n) => chordFromRoman(9, true, n).name), ["Am", "G", "F", "E"]);
});

test("chord shapes: open chords first, barre shapes for the rest", () => {
  const c = (root: number, q: any) => ({ root, rootName: "", quality: q, name: "", roman: "", tones: [] });
  assert.deepEqual(shapeFor(chordFromRoman(0, false, "I")), [-1, 3, 2, 0, 1, 0]); // C open
  assert.deepEqual(shapeFor(chordFromRoman(9, false, "ii")), [-1, 2, 4, 4, 3, 2]); // Bm: the barre at fret 2 on the A string
  const fsharp = shapeFor(c(6, "m7b5") as any)!;
  assert.deepEqual(fsharp, [2, -1, 2, 2, 1, -1]); // F#m7b5, the b5 one fret below the root
  assert.deepEqual(shapePitches([-1, 3, 2, 0, 1, 0]), [48, 52, 55, 60, 64]);
});

test("circle of fifths", () => {
  assert.equal(CIRCLE.length, 12);
  assert.deepEqual(CIRCLE.slice(0, 4).map((k) => `${k.name}/${k.minor}/${k.accidentals}`), ["C/Am/0", "G/Em/1", "D/Bm/2", "A/F#m/3"]);
  assert.equal(CIRCLE.at(-1)!.name, "F");
});
