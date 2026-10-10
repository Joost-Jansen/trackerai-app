// Counts page visits for the admin page's usage figures: one POST /api/account/visit per page shown (packages/accounts
// keeps a count per day, never which page). Fire and forget: a failed count never bothers anyone.

import { useEffect } from "react";

export function useCountVisits(pathname: string, enabled: boolean, post: (path: string) => Promise<unknown>): void {
  useEffect(() => {
    if (enabled) post("/api/account/visit").catch(() => undefined);
  }, [pathname, enabled, post]);
}
