import { test } from "node:test";
import assert from "node:assert/strict";
import { beatAtGpIndex, fromAlphaTab, fromApi, gpBeatIndex, invalid, mainBeat, toRequest } from "./beat.ts";

// A bar shaped like alphaTab's model: a chord, a grace note (its own beat), the main beat it belongs to.
function bar() {
  const voice: any = { beats: [] };
  const masterBar = { section: { text: "Verse 1" } };
  voice.bar = { masterBar };
  const note = (string: number, fret: number, extra: object = {}) => ({ string, fret, isDead: false, ...extra });
  const mk = (i: number, graceType: number, notes: any[], extra: object = {}) => ({ index: i, graceType, notes, voice, brushType: 0, brushDuration: 0, text: null, ...extra });
  voice.beats = [
    mk(0, 0, [note(5, 2), note(4, 2), note(2, 0, { isLetRing: true })], { brushType: 2, brushDuration: 30, text: "A" }),
    mk(1, 2, [note(6, 0, { isHammerPullOrigin: true })]),
    mk(2, 0, [note(6, 2), note(1, 0, { isDead: true }), note(3, 7, { slideOutType: 2, isPalmMute: true })], { brushType: 2, brushDuration: 120 }),
  ];
  return { voices: [voice] };
}

test("grace beats are not counted in the Guitar Pro index", () => {
  const b = bar();
  const [chord, grace, main] = b.voices[0].beats;
  assert.equal(gpBeatIndex(chord), 0);
  assert.equal(mainBeat(grace), main);
  assert.equal(gpBeatIndex(main), 1);
  assert.equal(beatAtGpIndex(b, 1), main);
});

test("reading a beat: frets, techniques, grace, strum, chord and section", () => {
  const [chord, , main] = bar().voices[0].beats;
  const c = fromAlphaTab(chord);
  assert.deepEqual(c.notes.map((n) => n.fret), ["", "2", "2", "", "0", ""]);
  assert.equal(c.notes[4].letRing, true);
  assert.equal(c.strum, "down");
  assert.equal(c.chord, "A");
  assert.equal(c.section, "Verse 1");
  const m = fromAlphaTab(main);
  assert.equal(m.notes[0].fret, "2");
  assert.equal(m.notes[0].grace, "0");
  assert.equal(m.notes[0].graceHammer, true);
  assert.equal(m.notes[5].fret, "x");
  assert.equal(m.notes[3].slide && m.notes[3].palmMute, true);
  assert.equal(m.strum, "arpeggio");
});

test("writing a beat back: only strings with a fret, all fields named as the API wants", () => {
  const s = fromAlphaTab(bar().voices[0].beats[2]);
  const body: any = toRequest(4, 1, s);
  assert.deepEqual(Object.keys(body.notes).sort(), ["1", "4", "6"]);
  assert.deepEqual(body.notes["1"].grace, { fret: 0, slide: false, hammer: true });
  assert.equal(body.notes["6"].fret, "x");
  assert.equal(body.notes["4"].palm_mute, true);
  assert.equal(body.stroke, "arpeggio");
  assert.equal(body.chord, null);
});

test("frets are checked", () => {
  const s = fromAlphaTab(bar().voices[0].beats[0]);
  assert.equal(invalid(s), null);
  s.notes[0].fret = "25";
  assert.equal(invalid(s), "fret");
  s.notes[0].fret = "x";
  s.notes[0].grace = "q";
  assert.equal(invalid(s), "fret");
});

test("the API's beat maps onto the form and back without loss", () => {
  const api = {
    notes: {
      "3": { fret: 2, tie: false, hammer: false, slide: true, let_ring: true, palm_mute: false, ghost: false, harmonic: false, vibrato: false, grace: null },
      "1": { fret: "x" as const, tie: false, hammer: false, slide: false, let_ring: false, palm_mute: true, ghost: false, harmonic: false, vibrato: false, grace: { fret: 0, slide: true, hammer: false } },
    },
    stroke: "up" as const,
    chord: "Em",
    section: "Riff",
  };
  const s = fromApi(api);
  assert.equal(s.notes[2].slide, true);
  assert.equal(s.notes[0].fret, "x");
  assert.equal(s.section, "Riff");
  const body: any = toRequest(0, 0, s);
  assert.deepEqual(body.notes["3"], { fret: 2, tie: false, hammer: false, slide: true, let_ring: true, palm_mute: false, ghost: false, harmonic: false, vibrato: false, grace: null });
  assert.deepEqual(body.notes["1"].grace, { fret: 0, slide: true, hammer: false });
  assert.equal(body.stroke, "up");
});
