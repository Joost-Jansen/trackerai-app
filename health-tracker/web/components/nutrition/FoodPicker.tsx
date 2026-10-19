"use client";

// Search a food: NEVO, cached Open Food Facts and your own foods (GET /api/nutrition/foods/search), with what you ate
// lately while the box is empty. A tap picks it; the editor then sets the amount.

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SearchIcon } from "@trackerai/ui/icons";
import { api } from "@/lib/api";
import { useFormat, useLocale, useT } from "@/lib/i18n";
import { foodName, type Food } from "@/lib/nutrition";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export default function FoodPicker({ onPick, autoFocus = false }: { onPick: (food: Food) => void; autoFocus?: boolean }) {
  const t = useT().nutrition;
  const f = useFormat();
  const { locale } = useLocale();
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), 200);
  const search = useQuery({
    queryKey: ["nutrition-search", q],
    queryFn: () => api.get<Food[]>(`/api/nutrition/foods/search?q=${encodeURIComponent(q)}`),
    enabled: q.length > 0,
    staleTime: 60_000,
  });
  const recent = useQuery({ queryKey: ["nutrition-recent"], queryFn: () => api.get<Food[]>("/api/nutrition/foods/recent") });
  // Search mode as soon as there is text, also in the moment before the debounced query runs.
  const searching = text.trim().length > 0;
  const pending = searching && (q !== text.trim() || search.isFetching);
  const list = searching ? (q ? search.data ?? [] : []) : recent.data ?? [];

  return (
    <div className="flex flex-col gap-2">
      <label className="ds-field">
        <span className="ds-field__label">{t.editor.search}</span>
        <span className="relative">
          <SearchIcon width={15} height={15} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-faint)]" />
          <input
            className="ds-input w-full pl-8"
            type="search"
            value={text}
            placeholder={t.editor.searchPlaceholder}
            onChange={(e) => setText(e.target.value)}
            autoFocus={autoFocus}
            maxLength={100}
          />
        </span>
      </label>
      {!searching && list.length > 0 && <span className="text-[11.5px] text-ink-muted">{t.editor.recent}</span>}
      {pending && list.length === 0 && <p className="text-[12.5px] text-ink-muted">{t.editor.searching}</p>}
      {searching && !pending && search.data && list.length === 0 && <p className="text-[12.5px] text-ink-muted">{t.editor.noResults}</p>}
      {list.length > 0 && (
        <ul className="flex max-h-56 flex-col overflow-y-auto rounded border border-border">
          {list.map((food) => (
            <li key={food.ref} className="border-t border-border first:border-t-0">
              <button type="button" onClick={() => onPick(food)} className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-[var(--surface-sunken)]">
                <span className="min-w-0">
                  <span className="block truncate text-[13px]">{foodName(food, locale)}</span>
                  <span className="block text-[11px] text-ink-muted">
                    {[food.source === "user" ? t.editor.own : food.source.toUpperCase(), locale === "en" && food.name_en ? food.name : null, food.brand].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span className="shrink-0 text-[11.5px] tabular-nums text-ink-muted">
                  {t.kcal(f.num(food.per_100.energy_kcal ?? 0))}/100 {food.unit}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
