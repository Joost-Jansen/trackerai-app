"use client";

// Latest activities: a run in pieces (less than 30 minutes break) is one row with "N parts", races
// get a label (same detection as Trends). With `fill` (the filler under the shorter column on Today) it shows as many
// as fit, so both columns end level.

import Card from "@trackerai/ui/components/Card";
import { useFitRows } from "@/components/ds/useFitRows";
import { SportBadge } from "@/components/plan/SportIcon";
import { useFormat, useT } from "@/lib/i18n";
import type { RecentItem } from "@/lib/training";

export default function RecentActivities({ items, fill = false }: { items: RecentItem[]; fill?: boolean }) {
  const tt = useT();
  const t = tt.texts.today.recent;
  const f = useFormat();
  // without fill the six newest, as before; the API sends more for filling
  const { box, rows } = useFitRows<HTMLDivElement>(fill ? items.length : Math.min(6, items.length), fill);
  return (
    <Card title={t.title} more={t.more} moreHref="/history/" className={fill ? "flex flex-col" : ""}>
      {items.length === 0 && <p className="text-[13px] text-ink-muted">{t.empty}</p>}
      <div ref={box} className={fill ? "relative lg:flex-1 lg:overflow-hidden" : ""}>
        <ul className={`flex flex-col ${fill ? "lg:absolute lg:inset-x-0 lg:top-0" : ""}`}>
          {items.slice(0, rows).map((a) => (
            <li
              key={a.id}
              className={`grid grid-cols-[72px_1fr] items-baseline gap-x-3 gap-y-0.5 border-t border-border py-2 text-[13px] first:border-t-0 ${fill ? "sm:grid-cols-[92px_1fr]" : "sm:grid-cols-[92px_1fr_auto]"}`}
            >
              <span className="text-ink-muted">{f.weekdayDay(a.start_local.slice(0, 10))}</span>
              <span className="flex min-w-0 items-center gap-2">
                <SportBadge sport={a.sport} size={22} />
                <span className="truncate">
                  <span className="font-medium">{tt.sport(a.sport)}</span>
                  {a.name && <span className="text-ink-muted"> · {a.name}</span>}
                </span>
                {a.race && (
                  <span className="flex-none rounded-full bg-[var(--surface-brand-soft)] px-2 py-px text-[11px] font-semibold text-brand">
                    {t.race}
                  </span>
                )}
              </span>
              {/* filling a column, which may be narrow: the numbers on a line of their own */}
              <span className={`col-start-2 tabular-nums text-ink-muted ${fill ? "" : "sm:col-start-auto"}`}>
                {a.distance_km ? `${f.km(a.distance_km)} · ${f.intensity(a)}` : f.duration(a.moving_time_s)}
                {a.avg_hr ? ` · ${a.avg_hr} bpm` : ""}
                {a.parts && a.parts > 1 && <span title={t.partsHelp}> · {t.parts(a.parts)}</span>}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
