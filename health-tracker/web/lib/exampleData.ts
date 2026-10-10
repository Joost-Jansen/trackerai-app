// Example data during the first-run walk past the pages (components/onboarding/CoachMark.tsx).
//
// A brand-new account has no data yet, so the walk would pass empty pages. While a page step is on screen, the data
// requests ask for the shared, read-only example account instead (lib/api.ts `exampleHeader`, api/example.py). The
// cache must never mix the two: on switching on and off, every data query is cancelled and reset, so a page refetches
// in the new mode. Personal queries (who you are, onboarding, connections, tokens, feedback, admin) always hold the
// user's own data and are left alone.

import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";
import { exampleDataOn, setExampleData, subscribeExampleData } from "@/lib/api";

const PERSONAL = new Set(["me", "onboarding", "connections", "agent-tokens", "feedback", "auth-config", "admin-overview", "admin-users", "admin-settings"]);

const isData = (q: Query) => !PERSONAL.has(String(q.queryKey[0]));

async function switchTo(qc: QueryClient, on: boolean) {
  setExampleData(on);
  await qc.cancelQueries({ predicate: isData });
  await qc.resetQueries({ predicate: isData });
}

/** Show example data while the calling component is mounted; the user's own data comes back when it unmounts. */
export function useExampleData() {
  const qc = useQueryClient();
  useEffect(() => {
    void switchTo(qc, true);
    return () => {
      void switchTo(qc, false);
    };
  }, [qc]);
}

/** Are the pages showing example data right now? (To leave out what speaks about your own, empty, data.) */
export function useExampleDataOn(): boolean {
  return useSyncExternalStore(subscribeExampleData, exampleDataOn, () => false);
}
