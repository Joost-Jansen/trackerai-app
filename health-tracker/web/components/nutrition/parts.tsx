// Pieces the Dag tab and the Voeding vandaag card share: the two macro bars against the day's targets and the one
// line of context from the plan.

import Link from "next/link";
import MacroBar from "@/components/nutrition/MacroBar";
import { useFormat, useT } from "@/lib/i18n";
import { MACRO_COLOUR, type NutritionContext, type Targets, type Totals } from "@/lib/nutrition";

export function TargetBars({
  totals,
  perKg,
  targets,
}: {
  totals: Pick<Totals, "carbs_g" | "protein_g">;
  perKg: { carbs: number | null; protein: number | null };
  targets: Targets;
}) {
  const t = useT().nutrition;
  return (
    <div className="flex flex-col gap-3">
      <MacroBar
        label={t.nutrients.carbs_g}
        grams={totals.carbs_g}
        range={targets.carbs_g}
        perKg={perKg.carbs}
        perKgRange={targets.carbs_per_kg}
        colour={MACRO_COLOUR.carbs_g!}
      />
      <MacroBar
        label={t.nutrients.protein_g}
        grams={totals.protein_g}
        range={targets.protein_g}
        perKg={perKg.protein}
        perKgRange={targets.protein_per_kg}
        colour={MACRO_COLOUR.protein_g!}
      />
      {targets.weight_kg == null && (
        <p className="text-[12px] text-ink-muted">
          {t.noWeight}{" "}
          <Link href="/settings/zones/" className="underline underline-offset-4">
            {t.toProfile}
          </Link>
        </p>
      )}
    </div>
  );
}

export function ContextLine({ context }: { context: NutritionContext | null }) {
  const tt = useT();
  const t = tt.nutrition;
  const f = useFormat();
  if (!context) return null;
  const text =
    context.line === "tomorrow"
      ? t.context.tomorrow(
          t.session(
            context.kind?.toLowerCase() ?? null,
            tt.sport(context.sport).toLowerCase(),
            context.distance_km ? f.km(context.distance_km, 0) : null,
          ),
          f.trim(context.carbs_per_kg[0], 1),
          f.trim(context.carbs_per_kg[1], 1),
        )
      : t.context.afterTraining;
  return <p className="rounded-md bg-[var(--surface-brand-soft)] px-3 py-2 text-[12.5px] text-[var(--text-secondary)]">{text}</p>;
}
