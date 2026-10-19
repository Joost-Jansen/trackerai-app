"use client";

// Voeding, Dag: one day at a time (today by default, another through ?day= like Slaap & lichaam): the day's training,
// totals against its targets, the energy split and the meals by moment. Behind the nutrition beta (lib/nav.ts).

import { Suspense, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { CameraIcon, ChevronLeftIcon, ChevronRightIcon, PlusIcon } from "@trackerai/ui/icons";
import { Button, Columns, IconButton } from "@/components/ds";
import EnergySplit from "@/components/nutrition/EnergySplit";
import AddMealSheet from "@/components/nutrition/AddMealSheet";
import MealEditor from "@/components/nutrition/MealEditor";
import MealRow from "@/components/nutrition/MealRow";
import { ContextLine, TargetBars } from "@/components/nutrition/parts";
import { addDays } from "@/components/plan/plan";
import { api } from "@/lib/api";
import { useFormat, useLocale, useT } from "@/lib/i18n";
import { MOMENTS, type Meal, type NutrientKey, type NutritionDay } from "@/lib/nutrition";

function Figure({ label, value, unit, detail }: { label: string; value: string; unit?: string; detail?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[12px] text-ink-muted">{label}</span>
      <span className="font-display text-[27px] font-light leading-none tabular-nums">
        {value}{unit && <span className="ml-1 text-[13px] text-ink-muted">{unit}</span>}
      </span>
      {detail && <span className="text-[11.5px] tabular-nums text-ink-muted">{detail}</span>}
    </div>
  );
}

function Totals({ d }: { d: NutritionDay }) {
  const tt = useT();
  const t = tt.nutrition;
  const f = useFormat();
  const v = d.totals;
  const g = (k: NutrientKey, digits = 0) => f.num(v[k], digits);
  const missing = Object.entries(v.missing).filter(([k]) => ["energy_kcal", "carbs_g", "protein_g", "fat_g", "fiber_g", "salt_g"].includes(k));
  return (
    <Card title={t.day.totals}>
      <div className="flex flex-col gap-4">
        <TargetBars totals={v} perKg={d.per_kg} targets={d.targets} />
        <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-3">
          <Figure label={t.nutrients.energy_kcal} value={g("energy_kcal")} unit="kcal" detail={d.burn_kcal != null ? t.burn(f.num(d.burn_kcal)) : undefined} />
          <Figure label={t.nutrients.carbs_g} value={g("carbs_g")} unit="g" detail={`${t.short.sugars} ${g("sugars_g")} g`} />
          <Figure label={t.nutrients.protein_g} value={g("protein_g")} unit="g" />
          <Figure label={t.nutrients.fat_g} value={g("fat_g")} unit="g"
            detail={`${t.short.saturated} ${g("sat_fat_g")} · ${t.short.mono} ${g("mufa_g")} · ${t.short.poly} ${g("pufa_g")}`} />
          <Figure label={t.nutrients.fiber_g} value={g("fiber_g")} unit="g" />
          <Figure label={t.nutrients.alcohol_g} value={g("alcohol_g")} unit="g" />
          <Figure label={t.nutrients.salt_g} value={g("salt_g", 1)} unit="g" />
        </div>
        <EnergySplit split={d.energy_split} />
        {missing.length > 0 && (
          <p className="text-[11.5px] text-ink-muted">{missing.map(([k, n]) => t.day.missing(n!, t.nutrients[k as NutrientKey])).join(" · ")}</p>
        )}
      </div>
    </Card>
  );
}

function DayView() {
  const param = useSearchParams().get("day");
  const day = param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? param : null;
  const tt = useT();
  const t = tt.nutrition;
  const f = useFormat();
  const { locale } = useLocale();
  const router = useRouter();
  const [editing, setEditing] = useState<Meal | null>(null);
  const [adding, setAdding] = useState<false | "choose" | File>(false);
  const camera = useRef<HTMLInputElement>(null);
  const q = useQuery({
    queryKey: ["nutrition-day", day],
    queryFn: () => api.get<NutritionDay>(`/api/nutrition/day${day ? `?day=${day}` : ""}`),
    placeholderData: keepPreviousData,
  });
  if (q.isLoading) return <p className="text-sm text-ink-muted">{tt.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.day.loadFailed}</p>;
  const d = q.data;
  const go = (iso: string) => router.replace(iso === d.today ? "/nutrition/" : `/nutrition/?day=${iso}`, { scroll: false });
  const training = d.targets.sessions.filter((s) => s.done || d.day >= d.today);
  const byMoment = MOMENTS.map((m) => ({ moment: m, meals: d.meals.filter((x) => x.moment === m) })).filter((g) => g.meals.length);
  const source = locale === "en" ? d.source.en : d.source.nl;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 aria-live="polite" className={`font-display text-[21px] font-light transition-opacity ${q.isPlaceholderData ? "opacity-60" : ""}`}>
            {f.weekdayDayYear(d.day)}
          </h2>
          <p className="text-[12.5px] text-ink-muted">
            {[
              ...training.map((s) => [s.kind || s.name || tt.sport(s.sport), s.distance_km ? f.km(s.distance_km) : null, s.minutes ? f.duration(s.minutes * 60) : null]
                .filter(Boolean).join(" ")),
              t.dayTypes[d.targets.day_type],
            ].join(" · ")}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <IconButton label={tt.texts.trends.timeFilter.previous} size="sm" icon={<ChevronLeftIcon width={15} height={15} />} onClick={() => go(addDays(d.day, -1))} />
          <input type="date" aria-label={t.day.pickDay} value={d.day} max={d.today}
            onChange={(e) => /^\d{4}-\d{2}-\d{2}$/.test(e.target.value) && go(e.target.value)}
            className="h-8 rounded border border-border bg-surface px-2 text-[13px] tabular-nums text-[var(--text-primary)]" />
          <IconButton label={tt.texts.trends.timeFilter.next} size="sm" icon={<ChevronRightIcon width={15} height={15} />} disabled={d.day >= d.today}
            onClick={() => go(addDays(d.day, 1))} />
          <Button variant="primary" size="sm" className="ml-2" disabled={!d.foods_ready} onClick={() => setAdding("choose")} icon={<PlusIcon width={14} height={14} />}>
            {t.today.add}
          </Button>
        </div>
      </div>

      {!d.foods_ready && <Card><p className="text-[13px] text-ink-muted">{t.day.noFoods}</p></Card>}
      <ContextLine context={d.context} />

      <Columns
        left={[<Totals key="totals" d={d} />]}
        right={[
          <Card key="meals" title={t.day.meals}>
            {byMoment.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{t.day.empty}</p>
            ) : (
              <div className="flex flex-col gap-3">
                {byMoment.map((g) => (
                  <section key={g.moment}>
                    <h3 className="text-[12px] font-medium text-ink-muted">{t.moments[g.moment]}</h3>
                    <ul className="flex flex-col">{g.meals.map((m) => <MealRow key={m.id} meal={m} onEdit={setEditing} showMoment={false} />)}</ul>
                  </section>
                ))}
              </div>
            )}
          </Card>,
        ]}
      />
      {source && <p className="text-[11.5px] text-ink-muted">{source}</p>}
      {editing && <MealEditor day={d.day} meal={editing} onClose={() => setEditing(null)} />}
      {adding && <AddMealSheet day={d.day} ai={d.ai} file={adding instanceof File ? adding : null} onClose={() => setAdding(false)} />}
      {d.ai && d.foods_ready && (
        // On a phone, logging is one tap from the page: the camera, bottom right above the safe area. The file input is
        // clicked inside the tap itself; iOS opens no camera for a click that comes later.
        <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setAdding(f); }} />
      )}
      {d.ai && d.foods_ready && (
        <button type="button" aria-label={t.add.photo} onClick={() => camera.current?.click()}
          className="fixed right-4 z-30 grid h-14 w-14 place-items-center rounded-full bg-[var(--surface-brand)] text-[var(--text-inverse)] shadow-lg sm:hidden"
          style={{ bottom: "calc(1rem + env(safe-area-inset-bottom))" }}>
          <CameraIcon width={22} height={22} />
        </button>
      )}
    </div>
  );
}

export default function Page() {
  const t = useT();
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">{t.common.loading}</p>}>
      <DayView />
    </Suspense>
  );
}
