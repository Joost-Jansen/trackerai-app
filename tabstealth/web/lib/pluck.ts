// A plucked guitar string in the browser (Karplus-Strong: a burst of noise through a short, damped delay line),
// to hear a note, a scale or a chord on the Theory page. No samples to download.

import { hz } from "./theory.ts";

let ctx: AudioContext | null = null;
const cache = new Map<number, AudioBuffer>();

function buffer(midi: number): AudioBuffer {
  const c = ctx!;
  const hit = cache.get(midi);
  if (hit) return hit;
  const rate = c.sampleRate;
  const period = Math.round(rate / hz(midi));
  const length = Math.round(rate * 1.8);
  const buf = c.createBuffer(1, length, rate);
  const out = buf.getChannelData(0);
  const ring = new Float32Array(period).map(() => Math.random() * 2 - 1);
  const damping = 0.996 - Math.max(0, midi - 60) * 0.0004; // high notes die a little faster, as on a guitar
  for (let i = 0; i < length; i++) {
    const j = i % period;
    const next = ring[(j + 1) % period];
    out[i] = ring[j];
    ring[j] = damping * 0.5 * (ring[j] + next);
  }
  cache.set(midi, buf);
  return buf;
}

/** Play one note now, or `delay` seconds from now. */
export function pluck(midi: number, delay = 0, volume = 0.5): void {
  if (typeof window === "undefined") return;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  const src = ctx.createBufferSource();
  const gain = ctx.createGain();
  src.buffer = buffer(midi);
  gain.gain.value = volume;
  src.connect(gain).connect(ctx.destination);
  src.start(ctx.currentTime + delay);
}

/** A strum, low string first. */
export const strum = (pitches: number[], spread = 0.035) => pitches.forEach((p, i) => pluck(p, i * spread, 0.35));

/** One note after another (a scale run). */
export const run = (pitches: number[], gap = 0.22) => pitches.forEach((p, i) => pluck(p, i * gap, 0.45));
