"use client";

// One line above a page that is still empty: where to start. Only while there
// are no workouts yet, with a text that fits where you are (not connected, first sync running, waiting for sync; with
// an Apple Watch: not imported yet, import running).
// Not on the dashboard: the checklist is there. Can be dismissed; that is stored with your account.
// Not while the walk shows example data either (lib/exampleData.ts): then the page is not empty.
//
// Also here: which pages of the "Rondkijken" (look around) step you have already seen (useRecordVisit).

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useExampleDataOn } from "@/lib/exampleData";
import { PAGES, useOnboarding, useSetOnboarding, type Onboarding, type Page } from "@/lib/onboarding";
import { useT, type Messages } from "@/lib/i18n";

const SCREENS = ["/trends/", "/routes/", "/history/", "/plan/"];

function text(o: Onboarding, t: Messages): { text: string; href: string; link: string } {
  const st = o.status;
  const b = t.onboarding.banner;
  if (o.device === "apple" && !st.garmin.connected) {
    if (st.apple.running) return { text: b.importing, href: "/settings/connections/#apple", link: b.toConnections };
    return { text: b.notImported, href: "/settings/connections/#apple", link: b.importApple };
  }
  if (!st.garmin.connected) return { text: b.notConnected, href: "/settings/connections/", link: b.connect };
  if (st.sync.running) return { text: b.syncing, href: "/help/guide/#data", link: b.how };
  return { text: b.waiting, href: "/settings/connections/", link: b.toConnections };
}

export default function StartBanner({ enabled }: { enabled: boolean }) {
  const t = useT();
  const pathname = usePathname();
  const q = useOnboarding(enabled);
  const set = useSetOnboarding();
  const example = useExampleDataOn();
  const o = q.data;
  if (!o || example) return null;
  const path = pathname.endsWith("/") ? pathname : `${pathname}/`;
  if (!SCREENS.some((s) => path.startsWith(s))) return null;
  if (o.status.activities.count > 0 || o.hidden.includes("data")) return null;
  const msg = text(o, t);

  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-2 rounded-md px-4 py-3 text-sm" style={{ background: "var(--surface-inset)" }}>
      <span>
        {msg.text}{" "}
        <Link href={msg.href} className="font-semibold underline underline-offset-4">{msg.link}</Link>
      </span>
      <button type="button" className="text-xs text-ink-muted underline underline-offset-4" onClick={() => set.mutate({ hide: "data" })}>
        {t.common.hide}
      </button>
    </div>
  );
}

/** Remembers which pages of the Rondkijken step you have opened (at most once per page). */
export function useRecordVisit(pathname: string, enabled: boolean) {
  const q = useOnboarding(enabled);
  const set = useSetOnboarding();
  const sent = useRef<Set<Page>>(new Set());
  const visited = q.data?.visited;
  useEffect(() => {
    if (!visited) return;
    const path = pathname.endsWith("/") ? pathname : `${pathname}/`;
    const page = PAGES.find((p) => path.startsWith(p.href))?.id;
    if (!page || visited.includes(page) || sent.current.has(page)) return;
    sent.current.add(page);
    set.mutate({ visit: page });
  }, [pathname, visited, set]);
}
