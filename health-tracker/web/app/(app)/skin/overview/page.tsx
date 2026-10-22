"use client";

// Huid, Overzicht: per week the averages of itch, redness and bumps, with the same weeks' measured sleep and training
// under them; redness with and without a short night, training or a food (associations, with how many days each side
// counts); and the CSV for the dermatologist (GET /api/skin/overview, /api/skin/export.csv). Private (lib/skin.ts).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import TimeChart from "@/components/charts/TimeChart";
import { ButtonLink, Columns } from "@/components/ds";
import { addDays } from "@/components/plan/plan";
import { api } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";
import { useSkinGate, type Comparison, type Overview } from "@/lib/skin";

const MONTHS = [3, 6, 12] as const;

function Overview() {
  const tt = useT();
  const t = tt.skin;
  const o = t.overview;
  const f = useFormat();
  const [months, setMonths] = useState<(typeof MONTHS)[number]>(3);
  const days = Math.round(months * 30.5);
  const q = useQuery({
    queryKey: ["skin-overview", months],
    queryFn: async () => {
      const today = (await api.get<{ today: string }>("/api/skin/day")).today;
      return api.get<Overview>(`/api/skin/overview?from=${addDays(today, -(days - 1))}&to=${today}`);
    },
  });

  const head = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="ds-segmented" role="tablist" aria-label={o.period}>
        {MONTHS.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={months === m}
            className={`ds-segmented__item ${months === m ? "ds-segmented__item--active" : ""}`}
            onClick={() => setMonths(m)}
          >
            {o.months(m)}
          </button>
        ))}
      </div>
      {q.data && (
        <ButtonLink size="sm" href={`/api/skin/export.csv?from=${q.data.from}&to=${q.data.to}`} download>
          {o.export}
        </ButtonLink>
      )}
    </div>
  );
  if (q.isLoading) return <p className="text-sm text-ink-muted">{tt.common.loading}</p>;
  if (!q.data) return head;
  const { weeks, comparisons } = q.data;
  const window = { from: q.data.from, to: q.data.to };
  const chart = { window, domain: window, barDays: 7, height: 200 };
  const weekly = (v: (w: (typeof weeks)[number]) => number | null) =>
    weeks.flatMap((w) => {
      const x = v(w);
      return x == null ? [] : [{ d: w.start, v: x }];
    });
  const side = (s: Comparison["with"]) => o.side(f.num(s.redness, 1), s.days);
  const label = (c: Comparison) => (c.kind === "short_sleep" ? o.shortSleep : c.kind === "training" ? o.training : o.foodTag(c.label));

  return (
    <div className="flex flex-col gap-4">
      {head}
      {q.data.entries.length === 0 ? (
        <Card>
          <p className="text-[13px] text-ink-muted">{o.empty}</p>
        </Card>
      ) : (
        <Columns
          left={[
            <Card key="trend" title={o.trend}>
              <TimeChart
                {...chart}
                ariaLabel={o.trend}
                format={(v) => f.num(v, 1)}
                legend
                series={[
                  { key: "itch", label: t.itch, colour: "var(--chart-1)", points: weekly((w) => w.itch) },
                  { key: "redness", label: t.redness, colour: "var(--chart-3)", points: weekly((w) => w.redness) },
                  { key: "bumps", label: t.bumps, colour: "var(--chart-2)", dash: "dashed", points: weekly((w) => w.bumps) },
                ]}
              />
              <div className="mt-3">
                <TimeChart
                  {...chart}
                  height={90}
                  ariaLabel={o.sleepH}
                  format={(v) => f.num(v, 1)}
                  unit="u"
                  legend
                  series={[{ key: "sleep", label: o.sleepH, colour: "var(--chart-4)", points: weekly((w) => w.sleep_h) }]}
                />
              </div>
              <div className="mt-3">
                <TimeChart
                  {...chart}
                  height={90}
                  ariaLabel={o.load}
                  format={(v) => f.num(v)}
                  legend
                  series={[{ key: "load", label: o.load, colour: "var(--chart-2)", kind: "bar", points: weekly((w) => w.load) }]}
                />
              </div>
              <p className="mt-2 text-[11.5px] text-ink-muted">{o.trendNote}</p>
            </Card>,
            <Card key="weeks" title={o.week}>
              <div className="overflow-x-auto">
                <table className="ds-table text-[12.5px]">
                  <thead>
                    <tr>
                      <th>{o.week}</th>
                      <th className="num">{o.days}</th>
                      <th className="num">{t.itch}</th>
                      <th className="num">{t.redness}</th>
                      <th className="num">{o.bumps}</th>
                      <th className="num">{o.flakingDays}</th>
                      <th className="num">{o.sleepH}</th>
                      <th className="num">{o.sessions}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...weeks].reverse().map((w) => (
                      <tr key={w.week}>
                        <td className="whitespace-nowrap">{f.date(w.start, { day: "numeric", month: "short" })}</td>
                        <td className="num">{w.days}</td>
                        <td className="num">{f.num(w.itch, 1)}</td>
                        <td className="num">{f.num(w.redness, 1)}</td>
                        <td className="num">{f.num(w.bumps, 1)}</td>
                        <td className="num">{w.flaking_days}</td>
                        <td className="num">{f.num(w.sleep_h, 1)}</td>
                        <td className="num">{w.sessions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>,
          ]}
          right={[
            <Card key="compare" title={o.compare}>
              {comparisons.length === 0 ? (
                <p className="text-[13px] text-ink-muted">{o.noCompare}</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {comparisons.map((c) => (
                    <li key={`${c.kind}-${c.label}`} className="text-[13px]">
                      <div className="font-medium">{label(c)}</div>
                      <div className="tabular-nums text-ink-muted">
                        {o.with}: {side(c.with)} · {o.without}: {side(c.without)}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-3 text-[11.5px] text-ink-muted">{o.compareNote}</p>
            </Card>,
            <Card key="export" title={o.export}>
              <p className="text-[12.5px] text-ink-muted">{o.exportNote}</p>
            </Card>,
          ]}
        />
      )}
    </div>
  );
}

export default function SkinOverviewPage() {
  const allowed = useSkinGate();
  const tt = useT();
  if (!allowed) return <p className="text-sm text-ink-muted">{tt.common.loading}</p>;
  return <Overview />;
}
