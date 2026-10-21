"use client";

// On the dashboard: gear that is due for replacement or nearly so (api/gear.py state), one line each.

import Link from "next/link";
import { useGear } from "@/lib/gear";
import { useFormat, useT } from "@/lib/i18n";

export default function GearNotice() {
  const t = useT();
  const m = t.dashboard.gear;
  const f = useFormat();
  const worn = (useGear().data?.gear ?? []).filter((g) => g.state === "replace" || g.state === "soon");
  if (!worn.length) return null;
  return (
    <p role="status" className="flex items-start gap-2 rounded border border-border bg-surface px-3 py-2 text-[12.5px] leading-relaxed">
      <span
        aria-hidden="true"
        className={`mt-[6px] inline-block h-2 w-2 flex-none rounded-full ${worn[0].state === "replace" ? "bg-[var(--data-loss)]" : "bg-warn"}`}
      />
      <span>
        {worn.map((g) => (
          <span key={g.id}>
            {g.state === "replace" ? m.replace(g.name, f.km(g.total_km, 0)) : m.soon(g.name, f.km(g.left_km ?? 0, 0))}{" "}
          </span>
        ))}
        <Link href="/history/#gear" className="font-medium underline underline-offset-4">
          {m.open}
        </Link>
      </span>
    </p>
  );
}
