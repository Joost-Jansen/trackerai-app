// The day's energy split by source (carbohydrate, protein, fat, alcohol, fibre): one thin stacked bar with a legend,
// so colour is never the only signal.

import { useFormat, useT } from "@/lib/i18n";
import { MACRO_COLOUR, type NutritionDay } from "@/lib/nutrition";

const ORDER = ["carbs_g", "protein_g", "fat_g", "alcohol_g", "fiber_g"] as const;

export default function EnergySplit({ split }: { split: NutritionDay["energy_split"] }) {
  const t = useT().nutrition;
  const f = useFormat();
  const parts = ORDER.filter((k) => split[k] > 0.005);
  if (parts.length === 0) return null;
  const label = (k: (typeof ORDER)[number]) => `${t.nutrients[k]} ${f.num(split[k] * 100)}%`;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] text-ink-muted">{t.day.split}</span>
      <div
        role="img"
        aria-label={t.day.splitAria(f.list(parts.map(label)))}
        className="flex h-2 overflow-hidden rounded-full bg-[var(--surface-inset)]"
      >
        {parts.map((k) => (
          <span key={k} style={{ width: `${split[k] * 100}%`, background: MACRO_COLOUR[k] }} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] tabular-nums text-ink-muted">
        {parts.map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: MACRO_COLOUR[k] }} />
            {label(k)}
          </li>
        ))}
      </ul>
    </div>
  );
}
