"use client";

// The sport filter of Trends: "all" or one sport. Lives in the address bar (?sport=run), so a link or a
// reload shows the same, and in sessionStorage, so it stays when you switch between the Trends tabs (their links
// carry no parameters). Touches only its own parameter, so the time window (?periode, ?van, ?tot) stays.

import { useCallback, useEffect, useState } from "react";

export const ALL_SPORTS = "all";
const PARAM = "sport";
const VALID = /^[a-z_]{1,40}$/;
const STORE = "trends:sport";

function stored(): string | null {
  try {
    return sessionStorage.getItem(STORE);
  } catch {
    return null; // no storage: only the address bar
  }
}

export function useSportFilter() {
  const [sport, setSport] = useState(ALL_SPORTS);

  // Read only after loading: the page is prebuilt as static html, without an address bar.
  const choose = useCallback((value: string) => {
    const next = VALID.test(value) ? value : ALL_SPORTS;
    setSport(next);
    try {
      sessionStorage.setItem(STORE, next);
    } catch {
      /* private window */
    }
    const url = new URL(window.location.href);
    if (next === ALL_SPORTS) url.searchParams.delete(PARAM);
    else url.searchParams.set(PARAM, next);
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url.href);
  }, []);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get(PARAM) ?? stored();
    if (value && VALID.test(value)) choose(value);
  }, [choose]);

  return { sport, choose, all: sport === ALL_SPORTS };
}
