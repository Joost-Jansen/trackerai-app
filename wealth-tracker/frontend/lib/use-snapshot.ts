"use client";

// Which stored portfolio is drawn next to your own: one choice for the dashboard's
// value chart and the Returns chart, so picking "Before the switch" on one page
// shows it on the other. Remembered in this browser; when that storage is
// unavailable nothing is lost but the memory, and the line starts off.

import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Snapshot } from "@/lib/dashboard";

const KEY = "wealth:dashboard-snapshot";

export function useChosenSnapshot() {
  const [id, setId] = useState<number | null>(() => {
    try {
      const v = window.localStorage.getItem(KEY);
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  });
  const q = useQuery({
    queryKey: ["what-if-snapshots"],
    queryFn: () => api.get<{ snapshots: Snapshot[] }>("/api/what-if/snapshots"),
  });
  const snapshots = useMemo(() => q.data?.snapshots ?? [], [q.data]);
  const chosen = snapshots.find((x) => x.id === id) ?? null;
  const choose = useCallback((next: Snapshot | null) => {
    setId(next?.id ?? null);
    try {
      if (next) window.localStorage.setItem(KEY, String(next.id));
      else window.localStorage.removeItem(KEY);
    } catch {
      // private window or blocked storage: the choice just isn't remembered
    }
  }, []);
  return { snapshots, chosen, choose };
}
