"use client";

// Theory: a key and a scale, and where they lie on the neck. One neck that every part of the page drives: the scale
// (all of it, or one position at a time), a chord of the key, or every note. Below it the chords of the key, the circle
// of fifths and common progressions in the key. Click a note to hear it, play the scale, strum a chord.

import { useEffect, useMemo, useState } from "react";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@trackerai/ui/ds/Button";
import { Select, Switch } from "@trackerai/ui/ds/Field";
import Tabs from "@trackerai/ui/ds/Tabs";
import { PlayIcon } from "@trackerai/ui/icons";
import ChordDiagram from "@/components/theory/ChordDiagram";
import CircleOfFifths from "@/components/theory/CircleOfFifths";
import Fretboard, { type NeckDot, type Role } from "@/components/theory/Fretboard";
import { useT } from "@/lib/i18n";
import { run, strum, pluck } from "@/lib/pluck";
import {
  chordFromRoman, chordsInKey, intervalName, isMinorScale, noteName, pc, PITCHES, positions, PROGRESSIONS, SCALE_GROUPS,
  scaleOnNeck, SCALES, shapeFor, shapePitches, spellScale, STANDARD, usesFlats, type Chord, type ScaleId,
} from "@/lib/theory";

const FRETS = 15;

function role(semitones: number): Role {
  const s = pc(semitones);
  if (s === 0) return "root";
  if (s === 3 || s === 4) return "third";
  if (s === 6 || s === 7 || s === 8) return "fifth";
  if (s === 10 || s === 11 || s === 9) return "seventh";
  return "other";
}

export default function TheoryPage() {
  const t = useT();
  const [root, setRoot] = useState(9); // A
  const [scale, setScale] = useState<ScaleId>("minorPentatonic");
  const [labels, setLabels] = useState<"names" | "intervals">("names");
  const [position, setPosition] = useState(-1); // -1: the whole neck
  const [allNotes, setAllNotes] = useState(false);
  const [sevenths, setSevenths] = useState(false);
  const [chord, setChord] = useState<Chord | null>(null);

  // A new key or scale starts from the whole scale again.
  useEffect(() => {
    setPosition(-1);
    setChord(null);
  }, [root, scale]);

  const minor = isMinorScale(scale);
  const names = spellScale(root, scale);
  const steps = SCALES[scale];
  const boxes = positions(root, scale);
  const box = position >= 0 && !chord && !allNotes ? boxes[position] : null;
  // the chords of the key: for a pentatonic or blues scale, those of its major or minor parent
  const parent: ScaleId = steps.length === 7 ? scale : minor ? "minor" : "major";
  const chords = chordsInKey(root, parent, sevenths);
  const flats = usesFlats(root, minor);
  const keyName = `${names[0]}${minor ? "m" : ""}`;

  const dots: NeckDot[] = useMemo(() => {
    if (allNotes) {
      // every note on the neck, as on a wall chart; the key's notes stand out
      return STANDARD.flatMap((open, i) =>
        Array.from({ length: FRETS + 1 }, (_, fret) => {
          const p = open + fret;
          const inScale = steps.includes(pc(p - root));
          return { string: 6 - i, fret, pitch: p, label: noteName(p, flats), role: (inScale ? (pc(p - root) === 0 ? "root" : "third") : "other") as Role };
        }),
      );
    }
    if (chord) {
      return STANDARD.flatMap((open, i) =>
        Array.from({ length: FRETS + 1 }, (_, fret) => fret).flatMap((fret) => {
          const p = open + fret;
          const iv = pc(p - chord.root);
          if (!chord.tones.includes(pc(p))) return [];
          return [{ string: 6 - i, fret, pitch: p, label: labels === "names" ? noteName(p, flats) : intervalName(iv), role: role(iv) }];
        }),
      );
    }
    return scaleOnNeck(root, scale, FRETS).map((d) => ({
      string: d.string, fret: d.fret, pitch: d.pitch, label: labels === "names" ? d.name : d.interval, role: role(steps[d.degree]),
    }));
  }, [allNotes, chord, root, scale, labels, steps, flats]);

  /** One octave of the scale up from the root, in the chosen position (or the lowest root on the low strings). */
  const playScale = () => {
    const shown = dots.filter((d) => !box || box.notes.has(`${d.string}-${d.fret}`));
    const roots = shown.filter((d) => d.role === "root").map((d) => d.pitch).sort((a, b) => a - b);
    const from = roots[0] ?? STANDARD[0] + pc(root - STANDARD[0]);
    const pitches = [...new Set(shown.map((d) => d.pitch))].filter((p) => p >= from && p <= from + 12).sort((a, b) => a - b);
    run(pitches.length > 2 ? pitches : steps.concat(12).map((s) => from + s));
  };

  const pickChord = (c: Chord) => {
    setChord((cur) => (cur?.name === c.name ? null : c));
    const shape = shapeFor(c);
    if (shape) strum(shapePitches(shape));
  };

  return (
    <div className="mx-auto flex max-w-content flex-col gap-4">
      {/* the key and the scale: they drive the whole page */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-ink-muted">
          {t.theory.key}
          <Select value={String(root)} onChange={(e) => setRoot(Number(e.target.value))} aria-label={t.theory.key}>
            {PITCHES.map((p, i) => (
              <option key={p} value={i}>
                {p}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-muted">
          {t.theory.scale}
          <Select value={scale} onChange={(e) => setScale(e.target.value as ScaleId)} aria-label={t.theory.scale}>
            {SCALE_GROUPS.map((g) => (
              <optgroup key={g.id} label={t.theory.groups[g.id]}>
                {g.scales.map((s) => (
                  <option key={s} value={s}>
                    {t.theory.scales[s]}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-muted">
          {t.theory.position}
          <Select value={String(position)} onChange={(e) => setPosition(Number(e.target.value))} aria-label={t.theory.position} disabled={!!chord || allNotes}>
            <option value={-1}>{t.theory.wholeNeck}</option>
            {boxes.map((b, i) => (
              <option key={i} value={i}>
                {t.theory.positionN(i + 1, b.from, b.to)}
              </option>
            ))}
          </Select>
        </label>
        <Tabs
          variant="segmented"
          items={[
            { id: "names", label: t.theory.names },
            { id: "intervals", label: t.theory.intervals },
          ]}
          value={labels}
          onChange={(v) => setLabels(v as "names" | "intervals")}
          ariaLabel={t.theory.labels}
        />
        <Switch checked={allNotes} onChange={setAllNotes} label={t.theory.allNotes} />
        <Button variant="primary" icon={<PlayIcon className="h-[15px] w-[15px]" />} onClick={playScale} className="ml-auto">
          {t.theory.playScale}
        </Button>
      </div>

      <Card
        title={chord ? t.theory.chordOnNeck(chord.name) : allNotes ? t.theory.allNotesTitle : `${names[0]} ${t.theory.scales[scale].toLowerCase()}`}
        action={
          chord ? (
            <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => setChord(null)}>
              {t.theory.backToScale}
            </button>
          ) : undefined
        }
      >
        {!allNotes && !chord && (
          <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span>
              <span className="text-ink-muted">{t.theory.notes}: </span>
              <span className="font-medium">{names.join("  ")}</span>
            </span>
            <span>
              <span className="text-ink-muted">{t.theory.formula}: </span>
              <span className="font-mono">{steps.map((s) => intervalName(s, scale)).join(" ")}</span>
            </span>
          </div>
        )}
        <Fretboard dots={dots} frets={FRETS} window={box} highlight={box?.notes} onNote={(d) => pluck(d.pitch)} ariaLabel={t.theory.neck} />
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
          {(allNotes
            ? [["root", t.theory.legend.root], ["third", t.theory.legend.inKey], ["other", t.theory.legend.outside]]
            : [["root", t.theory.legend.root], ["third", t.theory.legend.third], ["fifth", t.theory.legend.fifth], ["seventh", t.theory.legend.seventh], ["other", t.theory.legend.other]]
          ).map(([k, label]) => (
            <span key={k} className="flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full border border-border" style={{ background: { root: "var(--brand-500)", third: "var(--chart-3)", fifth: "var(--chart-4)", seventh: "var(--chart-5)", other: "var(--surface)" }[k] }} />
              {label}
            </span>
          ))}
          <span className="ml-auto">{t.theory.clickToHear}</span>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_minmax(300px,36%)]">
        <Card
          title={t.theory.chordsIn(keyName)}
          action={
            <Tabs
              variant="quiet"
              items={[
                { id: "triads", label: t.theory.triads },
                { id: "sevenths", label: t.theory.sevenths },
              ]}
              value={sevenths ? "sevenths" : "triads"}
              onChange={(v) => setSevenths(v === "sevenths")}
            />
          }
        >
          {steps.length !== 7 && <p className="mb-2 text-xs text-ink-muted">{t.theory.parentChords(t.theory.scales[parent].toLowerCase())}</p>}
          <div className="flex flex-wrap gap-1">
            {chords.map((c) => (
              <ChordDiagram key={c.roman} name={c.name} shape={shapeFor(c)} caption={c.roman} active={chord?.name === c.name} onClick={() => pickChord(c)} />
            ))}
          </div>
        </Card>
        <Card title={t.theory.circle}>
          <CircleOfFifths
            root={root}
            minor={minor}
            ariaLabel={t.theory.circle}
            onSelect={(r, m) => {
              setRoot(r);
              // keep the kind of scale where it fits: a minor key gets the minor version of what was chosen
              if (m !== isMinorScale(scale)) setScale(m ? (scale === "majorPentatonic" ? "minorPentatonic" : "minor") : scale === "minorPentatonic" || scale === "blues" ? "majorPentatonic" : "major");
            }}
          />
          <p className="mt-2 text-center text-xs text-ink-muted">{t.theory.circleHint}</p>
        </Card>
      </div>

      <Card title={t.theory.progressions(keyName)}>
        <ul className="flex flex-col gap-2">
          {PROGRESSIONS.filter((p) => p.minor === minor).map((p) => {
            const cs = p.numerals.map((n) => chordFromRoman(root, minor, n));
            return (
              <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span className="w-40 flex-none text-sm text-ink-muted">{t.theory.progressionNames[p.id as keyof typeof t.theory.progressionNames]}</span>
                <span className="flex flex-wrap gap-1">
                  {cs.map((c, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => pickChord(c)}
                      className={`rounded-sm border px-2 py-0.5 text-sm ${chord?.name === c.name ? "border-brand bg-brand-tint text-brand" : "border-border hover:border-border-strong"}`}
                      title={c.roman}
                    >
                      {c.name}
                    </button>
                  ))}
                </span>
                <span className="font-mono text-[11px] text-ink-muted">{p.numerals.join(" ")}</span>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
