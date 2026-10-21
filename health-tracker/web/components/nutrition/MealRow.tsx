// One meal in a list: its moment icon (a photo thumbnail once meals have photos), time, moment and what was in it,
// kcal and protein. Opens to its items with their amounts; Edit hands it to the editor.

import { useState } from "react";
import { UtensilsIcon } from "@trackerai/ui/icons";
import { useFormat, useT } from "@/lib/i18n";
import { photoUrl, type Meal } from "@/lib/nutrition";

export default function MealRow({
  meal,
  onEdit,
  compact = false,
  showMoment = true,
}: {
  meal: Meal;
  onEdit?: (m: Meal) => void;
  compact?: boolean;
  showMoment?: boolean;
}) {
  const t = useT().nutrition;
  const f = useFormat();
  const [open, setOpen] = useState(false);
  const names = meal.items.map((i) => i.name).join(", ");
  return (
    <li className="border-t border-border py-2.5 first:border-t-0">
      <div className="grid grid-cols-[40px_1fr_auto] items-center gap-x-3">
        {meal.photo_id ? (
          // eslint-disable-next-line @next/next/no-img-element -- the user's own photo, from the API
          <img src={photoUrl(meal.photo_id)} alt="" loading="lazy" className="h-10 w-10 rounded-md object-cover" />
        ) : (
          <span aria-hidden className="grid h-10 w-10 place-items-center rounded-md bg-[var(--surface-sunken)] text-[var(--text-faint)]">
            <UtensilsIcon width={18} height={18} />
          </span>
        )}
        <button
          type="button"
          className="min-w-0 text-left"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          title={open ? t.meal.close : t.meal.open}
        >
          <span className="block text-[12px] tabular-nums text-ink-muted">
            {showMoment ? `${meal.eaten_at} · ${t.moments[meal.moment]}` : meal.eaten_at}
          </span>
          <span className={`block text-[13px] ${compact ? "truncate" : ""}`}>{names}</span>
        </button>
        <span className="text-right text-[12.5px] tabular-nums">
          <span className="block">{t.kcal(f.num(meal.totals.energy_kcal))}</span>
          <span className="block text-[11.5px] text-ink-muted">
            {t.nutrients.protein_g} {f.num(meal.totals.protein_g)} g
          </span>
        </span>
      </div>
      {open && (
        <div className="mt-2 pl-[52px]">
          <ul className="flex flex-col gap-0.5 text-[12.5px] tabular-nums">
            {meal.items.map((i) => (
              <li key={i.id} className="flex justify-between gap-3">
                <span className="min-w-0 truncate">{i.name}</span>
                <span className="shrink-0 text-ink-muted">
                  {f.num(i.grams)} {i.unit} · {t.kcal(f.num(i.nutrients.energy_kcal ?? 0))}
                </span>
              </li>
            ))}
          </ul>
          {onEdit && (
            <button type="button" className="mt-1.5 text-[12px] font-medium underline underline-offset-4" onClick={() => onEdit(meal)}>
              {t.meal.edit}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
