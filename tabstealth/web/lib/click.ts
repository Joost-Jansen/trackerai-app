// A metronome click (Web Audio): a short tick, higher on the first beat of a bar. Used when the video is the
// sound source; with the tab as the source alphaTab clicks itself.

let ctx: AudioContext | null = null;

export function click(accent = false, volume = 0.6): void {
  if (typeof window === "undefined") return;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  const t = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.frequency.value = accent ? 1600 : 1100;
  gain.gain.setValueAtTime(volume, t);
  gain.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + 0.07);
}

/** `beats` clicks at `bpm`, then `done` (a count-in before the video starts). Returns a cancel function. */
export function countIn(beats: number, bpm: number, done: () => void): () => void {
  const gap = 60_000 / bpm;
  const timers = Array.from({ length: beats }, (_, i) => window.setTimeout(() => click(i === 0), i * gap));
  timers.push(window.setTimeout(done, beats * gap));
  return () => timers.forEach((id) => window.clearTimeout(id));
}
