"use client";

// Filtering on one or more categories, switchable per group. "Still to
// categorise" is listed separately: that is not a category but the absence of
// one, and exactly the filter you use to start labelling.

import { useState } from "react";
import { Checkbox, Input } from "@/components/ds";
import type { Category } from "@/lib/money";
import { tr } from "@/lib/i18n";

export const UNKNOWN = "Onbekend";

export default function CategoryFilter({ categories, value, onChange }: {
  categories: Category[]; value: string[]; onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const chosen = new Set(value);
  const put = (names: string[], on: boolean) => {
    const next = new Set(chosen);
    for (const n of names) (on ? next.add(n) : next.delete(n));
    onChange([...next]);
  };

  const filter = search.trim().toLocaleLowerCase("nl");
  const onGroup = categories
    .filter((c) => c.name !== UNKNOWN)
    .filter((c) => !filter || `${c.group_name} ${c.name}`.toLocaleLowerCase("nl").includes(filter))
    .reduce<Record<string, Category[]>>((acc, c) => {
      (acc[c.group_name] ??= []).push(c);
      return acc;
    }, {});

  const pill = (key: string, label: string, active: boolean, onClick: () => void) => (
    <button key={key} type="button" aria-pressed={active} onClick={onClick}
      className="rounded-full border px-3 py-1.5 text-xs transition-colors"
      style={{ borderColor: active ? "var(--text-primary)" : "var(--rule)", background: active ? "var(--surface-inset)" : "transparent", fontWeight: active ? 600 : 400 }}>
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-2 pb-5" role="group" aria-label={tr("Filter categories")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs text-ink-muted">{tr("Categories")}</span>
        {pill("all", tr("Any"), value.length === 0, () => onChange([]))}
        {pill(UNKNOWN, tr("Still to categorise"), chosen.has(UNKNOWN), () => put([UNKNOWN], !chosen.has(UNKNOWN)))}
        {value.filter((n) => n !== UNKNOWN).map((n) => pill(n, `${n} ×`, true, () => put([n], false)))}
        {pill("choose", open ? tr("Close") : tr("+ Choose"), open, () => setOpen((o) => !o))}
      </div>
      {open && (
        <div className="rounded-md p-3" style={{ border: "1px solid var(--rule)" }}>
          <Input label={tr("Search")} placeholder={tr("e.g. groceries")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="grid max-h-80 gap-4 overflow-y-auto pt-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(onGroup).map(([group_name, items]) => {
              const names = items.map((c) => c.name);
              const everything = names.every((n) => chosen.has(n));
              return (
                <div key={group_name} className="flex flex-col gap-1">
                  <Checkbox label={<b>{group_name}</b>} checked={everything} onChange={(on) => put(names, on)} />
                  <div className="flex flex-col gap-1 pl-5">
                    {items.map((c) => (
                      <Checkbox key={c.id} label={c.name} checked={chosen.has(c.name)} onChange={(on) => put([c.name], on)} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** Applies the filter: empty is everything, "Onbekend" also matches no category. */
export function inCategories(category: string | null, value: string[]): boolean {
  if (value.length === 0) return true;
  return value.includes(!category || category === UNKNOWN ? UNKNOWN : category);
}
