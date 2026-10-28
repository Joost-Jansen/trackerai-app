// One beat as the editor sees it, read from alphaTab's model and written back to the API (tabstealth/api/app.py
// BeatEdit). Everything the converter writes has a field here, so editing a beat never loses a technique.
//
// The editor opens with alphaTab's reading of the beat (instant), then takes the .gp5's own (fromApi), since the
// renderer can drop a detail, such as a slide whose target note is bars away.
//
// alphaTab turns a Guitar Pro grace note into a beat of its own before the main beat; the API counts beats the
// Guitar Pro way, without them. gpBeatIndex() and mainBeat() translate.

import { gpString } from "./sync.ts";

export type Strum = "" | "down" | "up" | "arpeggio";

export type NoteState = {
  fret: string; // "" no note, "x" dead, else 0-24
  tie: boolean;
  hammer: boolean;
  slide: boolean;
  letRing: boolean;
  palmMute: boolean;
  ghost: boolean;
  harmonic: boolean;
  vibrato: boolean;
  grace: string; // "" none, "x" dead, else 0-24
  graceSlide: boolean;
  graceHammer: boolean;
};

export type BeatState = { notes: NoteState[]; strum: Strum; chord: string; section: string }; // notes[0] = high e

export const TECHNIQUES = ["hammer", "slide", "tie", "letRing", "palmMute", "ghost", "harmonic", "vibrato"] as const;
export type Technique = (typeof TECHNIQUES)[number];

export const emptyNote = (): NoteState => ({
  fret: "", tie: false, hammer: false, slide: false, letRing: false, palmMute: false, ghost: false, harmonic: false,
  vibrato: false, grace: "", graceSlide: false, graceHammer: false,
});

// alphaTab enums (BrushType): 1 brush up, 2 brush down, 3 arpeggio up, 4 arpeggio down. A Guitar Pro 5 stroke has
// only a direction and a speed; a slow one (the converter writes 1/16) comes in as a long brush: an arpeggio.
const ARPEGGIO_MS = 60;

/** The beat the editor works on: a click on a grace note means the beat it belongs to. */
export function mainBeat(beat: any): any {
  const beats = beat.voice.beats;
  let i = beat.index;
  while (i < beats.length - 1 && beats[i].graceType !== 0) i++;
  return beats[i];
}

/** The beat's index in the Guitar Pro file: grace beats not counted. */
export const gpBeatIndex = (beat: any): number =>
  beat.voice.beats.filter((b: any) => b.graceType === 0 && b.index < beat.index).length;

/** The beat with this Guitar Pro index in a bar of alphaTab's model. */
export const beatAtGpIndex = (bar: any, index: number): any =>
  bar?.voices[0].beats.filter((b: any) => b.graceType === 0)[index];

const fretText = (n: any) => (n.isDead ? "x" : String(n.fret));

export function fromAlphaTab(beat: any): BeatState {
  const notes = Array.from({ length: 6 }, emptyNote);
  for (const n of beat.notes) {
    const s = notes[gpString(n.string) - 1];
    Object.assign(s, {
      fret: fretText(n),
      tie: !!n.isTieDestination,
      hammer: !!n.isHammerPullOrigin,
      slide: !!n.slideOutType,
      letRing: !!n.isLetRing,
      palmMute: !!n.isPalmMute,
      ghost: !!n.isGhost,
      harmonic: !!n.harmonicType,
      vibrato: !!n.vibrato,
    });
  }
  // grace beats right before this one
  const beats = beat.voice.beats;
  for (let i = beat.index - 1; i >= 0 && beats[i].graceType !== 0; i--) {
    for (const g of beats[i].notes) {
      const s = notes[gpString(g.string) - 1];
      s.grace = fretText(g);
      s.graceSlide = !!g.slideOutType;
      s.graceHammer = !!g.isHammerPullOrigin;
    }
  }
  const b = beat.brushType ?? 0;
  const strum: Strum = b === 0 ? "" : beat.brushDuration >= ARPEGGIO_MS || b >= 3 ? "arpeggio" : b === 1 ? "up" : "down";
  return { notes, strum, chord: beat.text ?? "", section: beat.voice.bar.masterBar.section?.text ?? "" };
}

const validFret = (f: string) => f.toLowerCase() === "x" || (/^\d{1,2}$/.test(f) && Number(f) <= 24);

/** First problem with the form, or null. */
export function invalid(state: BeatState): "fret" | null {
  for (const n of state.notes) {
    if (n.fret !== "" && !validFret(n.fret)) return "fret";
    if (n.fret !== "" && n.grace !== "" && !validFret(n.grace)) return "fret";
  }
  return null;
}

const apiFret = (f: string): number | "x" => (f.toLowerCase() === "x" ? "x" : Number(f));

/** The body of POST /api/songs/{id}/beats. */
export function toRequest(bar: number, beat: number, state: BeatState) {
  const notes: Record<string, unknown> = {};
  state.notes.forEach((n, i) => {
    if (n.fret === "") return;
    notes[String(i + 1)] = {
      fret: apiFret(n.fret),
      tie: n.tie,
      hammer: n.hammer,
      slide: n.slide,
      let_ring: n.letRing,
      palm_mute: n.palmMute,
      ghost: n.ghost,
      harmonic: n.harmonic,
      vibrato: n.vibrato,
      grace: n.grace === "" ? null : { fret: apiFret(n.grace), slide: n.graceSlide, hammer: n.graceHammer },
    };
  });
  return { bar, beat, notes, stroke: state.strum || null, chord: state.chord.trim() || null };
}

/** What GET /api/songs/{id}/beats/{bar}/{beat} returns: the beat exactly as it is in the .gp5. */
export type ApiBeat = {
  notes: Record<string, {
    fret: number | "x"; tie: boolean; hammer: boolean; slide: boolean; let_ring: boolean; palm_mute: boolean;
    ghost: boolean; harmonic: boolean; vibrato: boolean; grace: { fret: number | "x"; slide: boolean; hammer: boolean } | null;
  }>;
  stroke: Exclude<Strum, ""> | null;
  chord: string | null;
  section: string | null;
};

export function fromApi(b: ApiBeat): BeatState {
  const notes = Array.from({ length: 6 }, emptyNote);
  for (const [s, n] of Object.entries(b.notes)) {
    notes[Number(s) - 1] = {
      fret: String(n.fret), tie: n.tie, hammer: n.hammer, slide: n.slide, letRing: n.let_ring, palmMute: n.palm_mute,
      ghost: n.ghost, harmonic: n.harmonic, vibrato: n.vibrato,
      grace: n.grace ? String(n.grace.fret) : "", graceSlide: !!n.grace?.slide, graceHammer: !!n.grace?.hammer,
    };
  }
  return { notes, strum: b.stroke ?? "", chord: b.chord ?? "", section: b.section ?? "" };
}
