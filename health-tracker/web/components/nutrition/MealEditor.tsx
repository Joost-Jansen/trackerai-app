"use client";

// Add or edit a meal (POST / PATCH /api/nutrition/meals): when, which moment, and its foods with their amounts. Totals
// update as you slide; nothing is saved until Save. The nutrients themselves always come from the food table on the
// server; what this shows while you edit is the same sum, computed here for speed.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CloseIcon } from "@trackerai/ui/icons";
import { Button, Dialog, Input, Select } from "@/components/ds";
import FoodPicker from "@/components/nutrition/FoodPicker";
import GramField from "@/components/nutrition/GramField";
import { api } from "@/lib/api";
import { errorText, useFormat, useLocale, useT } from "@/lib/i18n";
import { MOMENTS, foodName, itemNutrients, momentAt, nowHHMM, sumNutrients, type DraftItem, type Food, type Meal, type Moment } from "@/lib/nutrition";

let seq = 0;
const key = () => `n${++seq}`;

function fromMeal(meal: Meal): DraftItem[] {
  return meal.items.map((i) => ({
    key: key(), id: i.id, food_ref: i.food_ref, name: i.name, unit: i.unit, grams: i.grams, per_100: null,
    snapshot: i.nutrients, snapshotGrams: i.grams, estimated: i.grams_source === "ai",
  }));
}

function fromFood(food: Food, locale: string): DraftItem {
  return {
    key: key(), food_ref: food.ref, name: foodName(food, locale), unit: food.unit, per_100: food.per_100,
    grams: Math.round(food.portion_g ?? food.default_portion_g ?? 100), portion_g: food.portion_g ?? null,
  };
}

export default function MealEditor({ day, meal, onClose }: { day: string; meal?: Meal | null; onClose: () => void }) {
  const t = useT();
  const m = t.nutrition.editor;
  const f = useFormat();
  const { locale } = useLocale();
  const qc = useQueryClient();
  const startTime = meal?.eaten_at ?? nowHHMM();
  const [when, setWhen] = useState(meal?.day ?? day);
  const [time, setTime] = useState(startTime);
  const [moment, setMoment] = useState<Moment>(meal?.moment ?? momentAt(startTime));
  const [items, setItems] = useState<DraftItem[]>(meal ? fromMeal(meal) : []);
  const [picking, setPicking] = useState(!meal);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const totals = sumNutrients(items.map(itemNutrients));
  const update = (k: string, patch: Partial<DraftItem>) => setItems((xs) => xs.map((x) => (x.key === k ? { ...x, ...patch } : x)));

  function pick(food: Food) {
    setItems((xs) => [...xs, fromFood(food, locale)]);
    setPicking(false);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (items.length === 0) return setError(t.errors.meal_empty);
    setBusy(true);
    setError(null);
    const body = {
      day: when, eaten_at: time, moment,
      items: items.map((i) => (i.id ? { id: i.id, grams: i.grams } : { food_ref: i.food_ref, name: i.name, grams: i.grams })),
    };
    try {
      if (meal) await api.patch(`/api/nutrition/meals/${meal.id}`, body);
      else await api.post("/api/nutrition/meals", { ...body, input: "search" });
      await qc.invalidateQueries({ predicate: (q) => ["nutrition-day", "nutrition-recent", "dashboard", "nutrition-search"].includes(String(q.queryKey[0])) });
      onClose();
    } catch (err) {
      setError(errorText(err, t, m.failed));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!meal) return;
    setBusy(true);
    try {
      await api.del(`/api/nutrition/meals/${meal.id}`);
      await qc.invalidateQueries({ predicate: (q) => ["nutrition-day", "dashboard"].includes(String(q.queryKey[0])) });
      onClose();
    } catch (err) {
      setError(errorText(err, t, m.failed));
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={meal ? m.editTitle : m.addTitle}
      actions={
        <>
          {meal && (confirming
            ? <Button variant="danger" className="mr-auto" onClick={remove} disabled={busy}>{m.confirmDelete}</Button>
            : <Button variant="ghost" className="mr-auto" onClick={() => setConfirming(true)}>{m.deleteMeal}</Button>)}
          <Button variant="ghost" onClick={onClose}>{m.cancel}</Button>
          <Button variant="primary" type="submit" form="meal-form" disabled={busy || items.length === 0}>{m.save}</Button>
        </>
      }
    >
      <form id="meal-form" onSubmit={save} className="-mx-1 flex max-h-[65vh] flex-col gap-4 overflow-y-auto px-1">
        <div className="grid grid-cols-[1fr_96px] gap-3 sm:grid-cols-[1fr_96px_1fr]">
          <Input label={m.day} type="date" value={when} onChange={(e) => e.target.value && setWhen(e.target.value)} />
          <Input label={m.time} type="time" value={time} onChange={(e) => e.target.value && setTime(e.target.value)} />
          <Select label={m.moment} value={moment} onChange={(e) => setMoment(e.target.value as Moment)} className="col-span-2 sm:col-span-1">
            {MOMENTS.map((x) => <option key={x} value={x}>{t.nutrition.moments[x]}</option>)}
          </Select>
        </div>

        {items.length > 0 && (
          <ul className="flex flex-col">
            {items.map((i) => (
              <li key={i.key} className="flex flex-col gap-1.5 border-t border-border py-2.5 first:border-t-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-[13px] font-medium">{i.name}</span>
                  <span className="flex shrink-0 items-center gap-2 text-[12px] tabular-nums text-ink-muted">
                    {t.nutrition.kcal(f.num(itemNutrients(i).energy_kcal ?? 0))}
                    <button type="button" aria-label={m.remove(i.name)} onClick={() => setItems((xs) => xs.filter((x) => x.key !== i.key))}
                      className="grid h-6 w-6 place-items-center rounded text-[var(--text-faint)] hover:text-[var(--text-primary)]">
                      <CloseIcon width={13} height={13} />
                    </button>
                  </span>
                </div>
                <GramField value={i.grams} unit={i.unit} portion={i.portion_g} estimated={i.estimated} label={`${i.name}: ${m.amount(i.unit)}`}
                  onChange={(grams) => update(i.key, { grams, estimated: false })} />
              </li>
            ))}
          </ul>
        )}

        {picking ? (
          <div className="flex flex-col gap-2">
            {items.length === 0 && <p className="text-[12.5px] text-ink-muted">{m.start}</p>}
            <FoodPicker onPick={pick} autoFocus />
          </div>
        ) : (
          <button type="button" onClick={() => setPicking(true)} className="self-start text-[12.5px] font-medium underline underline-offset-4">{m.addItem}</button>
        )}

        {items.length > 0 && (
          <p className="flex flex-wrap gap-x-4 gap-y-1 rounded-md bg-[var(--surface-sunken)] px-3 py-2 text-[12.5px] tabular-nums" aria-live="polite">
            <span className="font-medium">{m.total}</span>
            <span>{t.nutrition.kcal(f.num(totals.energy_kcal))}</span>
            <span>{t.nutrition.nutrients.carbs_g} {f.num(totals.carbs_g)} g</span>
            <span>{t.nutrition.nutrients.protein_g} {f.num(totals.protein_g)} g</span>
            <span>{t.nutrition.nutrients.fat_g} {f.num(totals.fat_g)} g</span>
          </p>
        )}
        {error && <p className="text-[12.5px] text-loss" role="alert">{error}</p>}
      </form>
    </Dialog>
  );
}
