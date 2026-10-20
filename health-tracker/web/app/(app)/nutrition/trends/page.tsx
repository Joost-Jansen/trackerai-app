"use client";

// Voeding, Trends: the last 14, 30 or 90 days. Carbohydrate per kg against the day's target (which follows the training,
// shown below it as load), protein per kg against 1.6-2.0, energy eaten against Garmin's estimated burn, iron, alcohol
// per week, salt against the 6 g guideline, saturated fat as a share of energy against 10%, and how many days are
// logged well enough to read anything from (GET /api/nutrition/trends).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import TimeChart, { type ChartSeries } from "@/components/charts/TimeChart";
import { Columns } from "@/components/ds";
import { weekOf } from "@/components/plan/plan";
import { api } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";
import { MACRO_COLOUR } from "@/lib/nutrition";
import type { DayPoint } from "@/lib/timeline";

type Row = {
  day: string; meals: number; covered: boolean; kcal: number | null; burn_kcal: number | null;
  carbs_per_kg: number | null; protein_per_kg: number | null; carbs_target: [number, number]; protein_target: [number, number];
  load: number; alcohol_g: number | null; salt_g: number | null; sat_fat_share: number | null; unsat_fat_share: number | null; iron_mg: number | null;
};
type Trends = { days: Row[]; weight_kg: number | null; covered: number; iron_reference: number | null };

const DAYS = [14, 30, 90] as const;
const SALT_GUIDE = 6; // g a day, Gezondheidsraad
const SAT_FAT_GUIDE = 10; // % of energy, Gezondheidsraad
const ALCOHOL_UNIT_G = 10;

const pts = (rows: Row[], v: (r: Row) => number | null | undefined): DayPoint[] =>
  rows.flatMap((r) => { const x = v(r); return x == null ? [] : [{ d: r.day, v: x }]; });

export default function Page() {
  const tt = useT();
  const t = tt.nutrition.trends;
  const n = tt.nutrition.nutrients;
  const f = useFormat();
  const [days, setDays] = useState<(typeof DAYS)[number]>(30);
  const q = useQuery({ queryKey: ["nutrition-trends", days], queryFn: () => api.get<Trends>(`/api/nutrition/trends?days=${days}`) });

  const head = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="ds-segmented" role="tablist" aria-label={t.period}>
        {DAYS.map((d) => (
          <button key={d} type="button" role="tab" aria-selected={days === d} onClick={() => setDays(d)}
            className={`ds-segmented__item ${days === d ? "ds-segmented__item--active" : ""}`}>{t.days(d)}</button>
        ))}
      </div>
      {q.data && <p className="text-[12.5px] text-ink-muted">{t.coverage(q.data.covered, q.data.days.length)}</p>}
    </div>
  );
  if (!q.data) return <div className="flex flex-col gap-4">{head}<p className="text-sm text-ink-muted">{q.isError ? t.loadFailed : tt.common.loading}</p></div>;
  const rows = q.data.days;
  const window = { from: rows[0].day, to: rows[rows.length - 1].day };
  const chart = { window, domain: window, barDays: 1, height: 190 };
  const target = (key: "carbs_target" | "protein_target", i: 0 | 1, label: string): ChartSeries =>
    ({ key: `${key}${i}`, label, colour: "var(--text-faint)", dash: "dashed", width: 1, kind: "step", points: rows.map((r) => ({ d: r.day, v: r[key][i] })) });

  // alcohol: units per ISO week, the bar on its Monday; only weeks that start in the window (a half week is no week)
  const weeks = new Map<string, number>();
  for (const r of rows) {
    const wk = weekOf(r.day);
    if (r.alcohol_g != null && wk >= rows[0].day) weeks.set(wk, (weeks.get(wk) ?? 0) + r.alcohol_g / ALCOHOL_UNIT_G);
  }
  const alcohol = [...weeks.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([d, v]) => ({ d, v: Math.round(v * 10) / 10 }));
  const flat = (v: number, key: string, label: string): ChartSeries =>
    ({ key, label, colour: "var(--text-faint)", dash: "dashed", width: 1, points: [{ d: window.from, v }, { d: window.to, v }] });

  return (
    <div className="flex flex-col gap-4">
      {head}
      {q.data.weight_kg == null && <p className="text-[12.5px] text-ink-muted">{tt.nutrition.noWeight}</p>}
      <Card title={t.carbs}>
        <TimeChart {...chart} ariaLabel={t.carbs} format={(v) => f.num(v, 1)} unit="g/kg" empty={t.empty} legend
          series={[{ key: "carbs", label: n.carbs_g, colour: MACRO_COLOUR.carbs_g!, kind: "bar", points: pts(rows, (r) => r.carbs_per_kg) },
                   target("carbs_target", 0, t.targetLow), target("carbs_target", 1, t.targetHigh)]} />
        <div className="mt-2">
          <TimeChart {...chart} height={90} ariaLabel={t.load} format={(v) => f.num(v)} legend
            series={[{ key: "load", label: t.load, colour: "var(--chart-2)", kind: "bar", points: rows.map((r) => ({ d: r.day, v: r.load })) }]} />
        </div>
        <p className="mt-2 text-[11.5px] text-ink-muted">{t.carbsNote}</p>
      </Card>
      <Columns
        left={[
          <Card key="protein" title={t.protein}>
            <TimeChart {...chart} ariaLabel={t.protein} format={(v) => f.num(v, 1)} unit="g/kg" empty={t.empty} legend
              series={[{ key: "protein", label: n.protein_g, colour: MACRO_COLOUR.protein_g!, kind: "bar", points: pts(rows, (r) => r.protein_per_kg) },
                       target("protein_target", 0, t.targetLow), target("protein_target", 1, t.targetHigh)]} />
          </Card>,
          <Card key="iron" title={t.iron}>
            <TimeChart {...chart} ariaLabel={t.iron} format={(v) => f.num(v, 1)} unit="mg" empty={t.empty} maOptions={[{ days: 7 }, { days: 0 }]} maDefault={7}
              legend={q.data.iron_reference != null}
              series={[{ key: "iron", label: n.iron_mg, colour: "var(--chart-5)", ma: true, points: pts(rows, (r) => r.iron_mg) },
                       ...(q.data.iron_reference != null ? [flat(q.data.iron_reference, "ironRef", t.reference)] : [])]} />
          </Card>,
          <Card key="salt" title={t.salt}>
            <TimeChart {...chart} ariaLabel={t.salt} format={(v) => f.num(v, 1)} unit="g" empty={t.empty} legend
              series={[{ key: "salt", label: n.salt_g, colour: "var(--chart-4)", kind: "bar", points: pts(rows, (r) => r.salt_g) }, flat(SALT_GUIDE, "saltGuide", t.guideline)]} />
            <p className="mt-2 text-[11.5px] text-ink-muted">{t.saltNote}</p>
          </Card>,
        ]}
        right={[
          <Card key="energy" title={t.energy}>
            <TimeChart {...chart} ariaLabel={t.energy} format={(v) => f.num(v)} unit="kcal" empty={t.empty} legend
              series={[{ key: "in", label: t.eaten, colour: "var(--chart-1)", points: pts(rows, (r) => r.kcal) },
                       { key: "out", label: t.burned, colour: "var(--chart-3)", dash: "dashed", points: pts(rows, (r) => r.burn_kcal) }]} />
          </Card>,
          <Card key="alcohol" title={t.alcohol}>
            <TimeChart {...chart} barDays={7} ariaLabel={t.alcohol} format={(v) => f.num(v, 1)} unit={t.units} empty={t.empty}
              series={[{ key: "alcohol", label: n.alcohol_g, colour: MACRO_COLOUR.alcohol_g!, kind: "bar", points: alcohol }]} />
          </Card>,
          <Card key="fat" title={t.fat}>
            <TimeChart {...chart} ariaLabel={t.fat} format={(v) => f.num(v)} unit="%" empty={t.empty} legend
              series={[{ key: "sat", label: t.saturated, colour: MACRO_COLOUR.fat_g!, points: pts(rows, (r) => r.sat_fat_share != null ? r.sat_fat_share * 100 : null) },
                       { key: "unsat", label: t.unsaturated, colour: "var(--chart-1)", dash: "dotted", points: pts(rows, (r) => r.unsat_fat_share != null ? r.unsat_fat_share * 100 : null) },
                       flat(SAT_FAT_GUIDE, "satGuide", t.guideline)]} />
          </Card>,
        ]}
      />
      <p className="text-[11.5px] text-ink-muted">{t.note}</p>
    </div>
  );
}
