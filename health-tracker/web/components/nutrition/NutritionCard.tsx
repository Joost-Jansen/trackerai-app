"use client";

// Voeding vandaag on Today: carbohydrate and protein against the day's training-aware targets, one line from the plan,
// the meals so far and the energy eaten next to Garmin's estimate of what you burned. Only for users with the
// nutrition beta (the dashboard's `nutrition` is null without it); without a meal yet it is one line and a button.

import { useState } from "react";
import Link from "next/link";
import Card from "@trackerai/ui/components/Card";
import { PlusIcon } from "@trackerai/ui/icons";
import { Button } from "@/components/ds";
import MealEditor from "@/components/nutrition/MealEditor";
import MealRow from "@/components/nutrition/MealRow";
import { ContextLine, TargetBars } from "@/components/nutrition/parts";
import { useFormat, useT } from "@/lib/i18n";
import type { NutritionBlock } from "@/lib/nutrition";

const STRIP = 4;

export default function NutritionCard({ block }: { block: NutritionBlock }) {
  const t = useT().nutrition;
  const f = useFormat();
  const [adding, setAdding] = useState(false);
  const add = (
    <Button size="sm" variant="secondary" onClick={() => setAdding(true)} icon={<PlusIcon width={14} height={14} />}>{t.today.add}</Button>
  );
  return (
    <Card title={t.today.title} action={add}>
      {block.empty ? (
        <div className="flex flex-col gap-3">
          <ContextLine context={block.context} />
          <p className="text-[13px] text-ink-muted">{t.today.nothing}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3.5">
          <TargetBars totals={block.totals} perKg={block.per_kg} targets={block.targets} />
          <ContextLine context={block.context} />
          <ul className="flex flex-col">
            {block.meals.slice(-STRIP).map((m) => <MealRow key={m.id} meal={m} compact />)}
          </ul>
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-[12px] tabular-nums text-ink-muted">
            <span>
              <span className="text-[var(--text-primary)]">{t.kcal(f.num(block.totals.energy_kcal))}</span>
              {block.burn_kcal != null && <> · {t.burn(f.num(block.burn_kcal))}</>}
            </span>
            <Link href="/nutrition/" className="font-medium text-[var(--text-primary)] underline underline-offset-4">{t.today.all}</Link>
          </p>
        </div>
      )}
      {adding && <MealEditor day={block.today} onClose={() => setAdding(false)} />}
    </Card>
  );
}
