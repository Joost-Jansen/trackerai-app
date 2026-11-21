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
    for (let lo = 0, hi = bars.length - 1; lo <= hi;) {
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

/** YouTube's smallest speed step: it plays 25% to 200% in steps of 5% and rounds anything finer down. */
export const VIDEO_STEP = 0.05;

/** The speed YouTube plays for `speed`: the nearest step of 5%, within 25% and 200%. */
export function videoRate(speed: number): number {
  // whole twentieths, divided last: 0.9 exactly, since YouTube rounds 0.8999… down to 0.85
  return Math.min(2, Math.max(0.25, Math.round(speed * 20) / 20));
}

/** alphaTab counts strings from the lowest (thickest) up; Guitar Pro and the API count from the high e down. */
export const gpString = (alphaString: number, strings = 6) => strings - alphaString + 1;
