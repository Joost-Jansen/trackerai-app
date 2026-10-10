"use client";

// A page's shared time window: a period (4W … All) or a custom from-to. Lives
// in the address bar (?periode=3M, or ?van=…&tot=…) so a link or a reload shows
// the same, and in localStorage so the page remembers the last choice when you
// come back via the menu.

import { useCallback, useEffect, useMemo, useState } from "react";
import { CUSTOM, DEFAULT_PERIOD, PERIODS, clampRange, dayNumber, periodWindow, toRange, toWindow, type DateWindow } from "@/lib/timeline";

type State = { period: string; custom: DateWindow | null; preset: string };
const ISO = /^\d{4}-\d{2}-\d{2}$/;

function readStored(key: string): State | null {
  try {
    const raw = localStorage.getItem(`timerange:${key}`);
    if (!raw) return null;
    const s = JSON.parse(raw) as State;
    if (s.custom && ISO.test(s.custom.from) && ISO.test(s.custom.to)) return { period: CUSTOM, custom: s.custom, preset: PERIODS.includes(s.preset) ? s.preset : DEFAULT_PERIOD };
    if (PERIODS.includes(s.period)) return { period: s.period, custom: null, preset: s.period };
  } catch {
    /* no storage: default */
  }
  return null;
}

export function useTimeRange(first: string, last: string, key = "trends", initial = DEFAULT_PERIOD) {
  const [state, setState] = useState<State>({ period: initial, custom: null, preset: initial });
  const [ready, setReady] = useState(false);

  // Read only after loading: the page is prebuilt as static html, without an address bar.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const van = q.get("van");
    const tot = q.get("tot");
    const periode = q.get("periode");
    const stored = readStored(key);
    if (van && tot && ISO.test(van) && ISO.test(tot)) {
      setState({ period: CUSTOM, custom: { from: van, to: tot }, preset: stored?.preset ?? initial });
    } else if (periode && PERIODS.includes(periode)) {
      setState({ period: periode, custom: null, preset: periode });
    } else if (stored) {
      setState(stored);
    }
    setReady(true);
  }, [key, initial]);

  useEffect(() => {
    if (!ready) return;
    try {
      localStorage.setItem(`timerange:${key}`, JSON.stringify(state));
    } catch {
      /* private window */
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("periode");
    url.searchParams.delete("van");
    url.searchParams.delete("tot");
    if (state.custom) {
      url.searchParams.set("van", state.custom.from);
      url.searchParams.set("tot", state.custom.to);
    } else if (state.period !== initial) {
      url.searchParams.set("periode", state.period);
    }
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url.href);
  }, [state, ready, key, initial]);

  const window_ = useMemo<DateWindow>(() => {
    // As long as the data is not there, there is no window (and no date to calculate with).
    if (!first || !last) return { from: "", to: "" };
    if (!state.custom) return periodWindow(state.period === CUSTOM ? state.preset : state.period, first, last);
    const r = clampRange(toRange(state.custom), dayNumber(first), dayNumber(last));
    return toWindow({ a: Math.round(r.a), b: Math.round(r.b) });
  }, [state, first, last]);

  const choose = useCallback((period: string) => setState({ period, custom: null, preset: period }), []);
  const change = useCallback(
    (w: DateWindow) => {
      if (!first || !last) return;
      setState((s) => {
        const preset = s.custom ? s.preset : s.period;
        const p = periodWindow(preset, first, last);
        // Back on exactly the period's window: then it is that period again, not "custom".
        if (p.from === w.from && p.to === w.to) return { period: preset, custom: null, preset };
        return { period: CUSTOM, custom: w, preset };
      });
    },
    [first, last],
  );
  const reset = useCallback(() => setState((s) => ({ period: s.preset, custom: null, preset: s.preset })), []);

  return { period: state.period, preset: state.preset, custom: state.custom !== null, window: window_, choose, change, reset };
}

export type TimeRange = ReturnType<typeof useTimeRange>;
