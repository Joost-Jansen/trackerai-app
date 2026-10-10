"use client";

// Sync now, from every page: the round arrows next to the theme switch in the top bar. Starts the same sync as
// Settings, Connections (POST /api/connections/sync), turns while it runs (also when the daily sync or another tab
// started it), and when it is done reloads all data on the page, so today's sleep and day up to now show straight
// away. Without a connection it opens Settings, Connections. `text`: a button with a label, for inside a page (an
// empty today on Sleep & body).

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, IconButton } from "@/components/ds";
import { SyncIcon } from "@trackerai/ui/icons";
import { ApiError, api } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";

type Status = { garmin: { syncing: boolean; last_sync: string | null } };

export default function SyncButton({ text = false }: { text?: boolean }) {
  const t = useT();
  const f = useFormat();
  const qc = useQueryClient();
  const router = useRouter();
  const [started, setStarted] = useState(false);
  const q = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Status>("/api/connections"),
    refetchInterval: (query) => (started || query.state.data?.garmin.syncing ? 3000 : false),
  });
  const syncing = started || !!q.data?.garmin.syncing;

  // a sync that was running and is now done: everything on the page may have changed
  const was = useRef(false);
  useEffect(() => {
    const running = !!q.data?.garmin.syncing;
    if (was.current && !running) {
      setStarted(false);
      qc.invalidateQueries();
    }
    was.current = running;
  }, [q.data, qc]);

  async function sync() {
    if (syncing) return;
    try {
      setStarted(true);
      await api.post("/api/connections/sync");
      was.current = true; // the next status without "syncing" means done, even if the first poll missed the run
      q.refetch();
    } catch (err) {
      setStarted(false);
      if (err instanceof ApiError && err.code === "garmin_not_connected") router.push("/settings/connections/");
    }
  }

  const last = q.data?.garmin.last_sync;
  const lastText = last && /^\d{4}-\d{2}-\d{2}/.test(last) ? `${f.weekdayDay(last.slice(0, 10))}${last.length > 10 ? `, ${last.slice(11, 16)}` : ""}` : null;
  const icon = <SyncIcon className={`h-4 w-4 ${syncing ? "animate-spin motion-reduce:animate-none" : ""}`} />;
  if (text)
    return (
      <Button size="sm" onClick={sync} disabled={syncing} icon={icon}>
        {syncing ? t.nav.syncing : t.nav.sync}
      </Button>
    );
  return (
    <IconButton
      onClick={sync}
      disabled={syncing}
      label={syncing ? t.nav.syncing : lastText ? t.nav.syncLast(lastText) : t.nav.sync}
      icon={icon}
    />
  );
}
