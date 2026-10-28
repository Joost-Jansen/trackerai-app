// Video time <-> tab position. The converter measured when every bar starts in the video (timing.json); inside a
// bar we interpolate linearly, which holds because the tempo is constant within a bar. Ticks are alphaTab's MIDI
// ticks (960 per quarter); a bar is { start, duration } in those ticks.

export type Timing = {
  video: string;
  measure_starts: number[];
  measure_seconds: number;
  /** Top of the video's own tab overlay, as a fraction of the frame height (to crop the video to the hands). */
  overlay_top?: number;
};

export type BarTicks = { start: number; duration: number };

export type Clock = { tickToTime: (tick: number) => number; timeToTick: (seconds: number) => number };

export function makeClock(timing: Timing, bars: BarTicks[]): Clock {
  const starts = timing.measure_starts;
  const step = timing.measure_seconds || (starts.length > 1 ? starts[1] - starts[0] : 2);
  // bar i starts at at(i) seconds, also past the measured bars
  const at = (i: number) => (i < starts.length ? starts[i] : starts[starts.length - 1] + (i - starts.length + 1) * step);

  function tickToTime(tick: number): number {
    if (!bars.length) return 0;
    let i = bars.length - 1;
    for (let lo = 0, hi = bars.length - 1; lo <= hi; ) {
      const mid = (lo + hi) >> 1;
      if (bars[mid].start <= tick) {
        i = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    if (tick < bars[0].start) i = 0;
    const frac = Math.min(Math.max((tick - bars[i].start) / bars[i].duration, 0), 1);
    return at(i) + frac * (at(i + 1) - at(i));
  }

  function timeToTick(seconds: number): number {
    if (!bars.length || seconds <= at(0)) return bars.length ? bars[0].start : 0;
    let i = 0;
    while (i < bars.length - 1 && at(i + 1) <= seconds) i++;
    const frac = Math.min((seconds - at(i)) / (at(i + 1) - at(i)), 1);
    return Math.round(bars[i].start + frac * bars[i].duration);
  }

  return { tickToTime, timeToTick };
}

/** YouTube plays only these speeds; the nearest one to the tab's speed. */
export function nearestRate(speed: number, rates: number[] = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]): number {
  return rates.reduce((best, r) => (Math.abs(r - speed) < Math.abs(best - speed) ? r : best), rates[0]);
}

/** alphaTab counts strings from the lowest (thickest) up; Guitar Pro and the API count from the high e down. */
export const gpString = (alphaString: number, strings = 6) => strings - alphaString + 1;
