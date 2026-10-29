// Practising: a bar range to loop, a speed trainer that speeds up every pass, and beat positions for the metronome.
// Bars are alphaTab master bars ({ start, duration } in MIDI ticks, 960 per quarter); bar numbers are 1-based.

import type { BarTicks } from "./sync.ts";
import { nearestRate } from "./sync.ts";

export type Practice = {
  loop: boolean;
  from: number; // first bar, 1-based
  to: number; // last bar, inclusive
  trainer: boolean;
  start: number; // trainer start speed, 0.25-1.5
  step: number; // added per pass
  target: number; // trainer stops here
  countIn: boolean;
  metronome: boolean;
};

export const DEFAULT_PRACTICE: Practice = {
  loop: false,
  from: 1,
  to: 4,
  trainer: false,
  start: 0.6,
  step: 0.05,
  target: 1,
  countIn: false,
  metronome: false,
};

/** The loop range in ticks, or null when the bars do not exist. */
export function rangeTicks(bars: BarTicks[], from: number, to: number): { startTick: number; endTick: number } | null {
  const a = Math.max(1, Math.min(from, to));
  const b = Math.min(bars.length, Math.max(from, to));
  if (!bars.length || a > bars.length) return null;
  return { startTick: bars[a - 1].start, endTick: bars[b - 1].start + bars[b - 1].duration };
}

/** The speed for the next pass. The video only plays YouTube's own speeds (quarter steps), the tab any speed. */
export function nextSpeed(current: number, p: Practice, source: "video" | "tab"): number {
  if (source === "video") {
    const rates = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    const now = nearestRate(current);
    const up = rates.find((r) => r > now + 1e-9) ?? now;
    return Math.min(up, Math.max(nearestRate(p.target), now));
  }
  return Math.round(Math.min(p.target, current + p.step) * 100) / 100;
}

/** Index of the bar that contains `tick` (the last bar for anything after the end). */
export function barAt(bars: BarTicks[], tick: number): number {
  let lo = 0;
  let hi = bars.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (bars[mid].start <= tick) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Which beat of which bar `tick` is in; `beatTicks` is the length of one beat (960 for a quarter). */
export function beatAt(bars: BarTicks[], tick: number, beatTicks: number): { bar: number; beat: number } {
  const bar = barAt(bars, tick);
  return { bar, beat: Math.max(0, Math.floor((tick - bars[bar].start) / beatTicks)) };
}
