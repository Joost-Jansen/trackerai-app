"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import TabStudio from "@/components/TabStudio";
import { useT } from "@/lib/i18n";

// /song/?v=<YouTube id>: a query parameter, so every song is the same static page.
function Song() {
  const vid = useSearchParams().get("v");
  const t = useT();
  if (!vid) return <p className="text-sm text-ink-muted">{t.common.error}</p>;
  return <TabStudio key={vid} vid={vid} />;
}

export default function SongPage() {
  return (
    <Suspense>
      <Song />
    </Suspense>
  );
}
