"use client";

// Today, Sleep & body: the night's sleep and the day from the watch, last night by default, another day through ?day=
// (components/dashboard/DaySection.tsx; the tabs are in lib/nav.ts).

import { Suspense } from "react";
import DaySection from "@/components/dashboard/DaySection";
import { useT } from "@/lib/i18n";

export default function Page() {
  const t = useT();
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">{t.common.loading}</p>}>
      <DaySection />
    </Suspense>
  );
}
