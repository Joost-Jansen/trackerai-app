"use client";

// Add, check or edit a meal (POST / PATCH /api/nutrition/meals): when, which moment, and its foods with their amounts.
// After a photo this is the review screen ("Controleer je maaltijd"): the photo on top, each food as matched with the
// other foods it could be ("swap"), Claude's estimate marked "≈" until you touch it, a dot for how sure Claude was, and
// chips for what a photo cannot show. Totals update as you slide; nothing is saved until Save. The nutrients always
// come from the food table on the server; what this shows while you edit is the same sum, computed here.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { CloseIcon, PlusIcon } from "@trackerai/ui/icons";
import { Button, Checkbox, Dialog, Input, Select } from "@/components/ds";
import FoodPicker from "@/components/nutrition/FoodPicker";
import GramField from "@/components/nutrition/GramField";
import { fromFood, fromMeal } from "@/components/nutrition/drafts";
import { api } from "@/lib/api";
import { errorText, useFormat, useLocale, useT } from "@/lib/i18n";
import {
  MOMENTS, foodName, itemNutrients, momentAt, nowHHMM, photoUrl, sumNutrients,
  type DraftItem, type EditorStart, type Food, type Meal, type Moment,
} from "@/lib/nutrition";

const QUERIES = ["nutrition-day", "nutrition-recent", "nutrition-again", "nutrition-templates", "dashboard", "nutrition-search"];

/** How sure Claude was of what it is: green, amber or grey, with the words in a popover (never colour alone). */
function ConfidenceDot({ value }: { value: number }) {
  const t = useT().nutrition.editor;
  const level = value >= 0.8 ? "high" : value >= 0.5 ? "medium" : "low";
  const colour = { high: "var(--moss-500)", medium: "var(--amber-500)", low: "var(--text-faint)" }[level];
  return (
    <InfoPopover label={t.confidence[level]} trigger={<span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: colour }} />}>
      {t.confidenceHelp}
    </InfoPopover>
  );
}

export default function MealEditor({ day, meal, start, onClose }: { day: string; meal?: Meal | null; start?: EditorStart; onClose: () => void }) {
  const t = useT();
  const m = t.nutrition.editor;
  const f = useFormat();
  const { locale } = useLocale();
  const qc = useQueryClient();
  const startTime = meal?.eaten_at ?? start?.eaten_at ?? nowHHMM();
  const [when, setWhen] = useState(meal?.day ?? day);
  const [time, setTime] = useState(startTime);
  const [moment, setMoment] = useState<Moment>(meal?.moment ?? start?.moment ?? momentAt(startTime));
  const [items, setItems] = useState<DraftItem[]>(meal ? fromMeal(meal) : start?.items ?? []);
  const [extras, setExtras] = useState(start?.extras?.filter((x) => x.food) ?? []);
  const [unmatched, setUnmatched] = useState(start?.unmatched ?? []);
  const [picking, setPicking] = useState<string | null>(!meal && !start?.items.length ? "" : null);
  const [favourite, setFavourite] = useState(false);
  const [favName, setFavName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const photoId = meal?.photo_id ?? start?.photo?.id ?? null;
  const preview = start?.photo?.preview ?? (photoId ? photoUrl(photoId) : null);

  const totals = sumNutrients(items.map(itemNutrients));
  const update = (k: string, patch: Partial<DraftItem>) => setItems((xs) => xs.map((x) => (x.key === k ? { ...x, ...patch } : x)));

  function pick(food: Food) {
    setItems((xs) => [...xs, fromFood(food, locale)]);
    setPicking(null);
  }

  function swap(item: DraftItem, ref: string) {
    const food = item.alternatives?.find((a) => a.ref === ref);
    if (food) update(item.key, { food_ref: food.ref, name: foodName(food, locale), unit: food.unit, per_100: food.per_100, portion_g: food.portion_g ?? null });
  }

  function addExtra(i: number) {
    const x = extras[i];
    setItems((xs) => [...xs, fromFood(x.food!, locale, x.grams)]);
    setExtras((xs) => xs.filter((_, j) => j !== i));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (items.length === 0) return setError(t.errors.meal_empty);
    setBusy(true);
    setError(null);
    const item = (i: DraftItem) =>
      i.id
        ? { id: i.id, grams: i.grams, ...(i.food_ref !== meal?.items.find((x) => x.id === i.id)?.food_ref ? { food_ref: i.food_ref, name: i.name } : {}) }
        : { food_ref: i.food_ref, name: i.name, grams: i.grams, grams_source: i.grams_source ?? "user", grams_ai: i.grams_ai, grams_low: i.grams_low,
            grams_high: i.grams_high, confidence: i.confidence };
    const body = { day: when, eaten_at: time, moment, items: items.map(item) };
    try {
      if (meal) await api.patch(`/api/nutrition/meals/${meal.id}`, body);
      else await api.post("/api/nutrition/meals", { ...body, input: start?.input ?? "search", photo_id: photoId, ai_run_id: start?.ai_run_id ?? null });
      if (favourite) {
        await api.post("/api/nutrition/templates", {
          name: (favName.trim() || `${t.nutrition.moments[moment]} · ${items[0].name}`).slice(0, 100), moment,
          items: items.map((i) => ({ food_ref: i.food_ref, name: i.name, grams: i.grams })),
        });
      }
      await qc.invalidateQueries({ predicate: (q) => QUERIES.includes(String(q.queryKey[0])) });
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
      await qc.invalidateQueries({ predicate: (q) => QUERIES.includes(String(q.queryKey[0])) });
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
      title={meal ? m.editTitle : start?.input === "photo" ? m.reviewTitle : m.addTitle}
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
        {preview && (
          // eslint-disable-next-line @next/next/no-img-element -- the user's own photo, from the API
          <img src={preview} alt={m.photoAlt} className="max-h-40 w-full rounded-md object-cover" />
        )}
        {start?.failed && <p className="rounded-md bg-[var(--surface-sunken)] px-3 py-2 text-[12.5px] text-ink-muted" role="status">{m.photoFailed}</p>}
        <div className="grid grid-cols-[1fr_96px] gap-3">
          <Input label={m.day} type="date" value={when} onChange={(e) => e.target.value && setWhen(e.target.value)} />
          <Input label={m.time} type="time" value={time} onChange={(e) => e.target.value && setTime(e.target.value)} />
          <Select label={m.moment} value={moment} onChange={(e) => setMoment(e.target.value as Moment)} className="col-span-2">
            {MOMENTS.map((x) => <option key={x} value={x}>{t.nutrition.moments[x]}</option>)}
          </Select>
        </div>

        {items.length > 0 && (
          <ul className="flex flex-col">
            {items.map((i) => {
              const estimated = i.grams_source === "ai" || i.grams_source === "memory";
              return (
                <li key={i.key} className="flex flex-col gap-1.5 border-t border-border py-2.5 first:border-t-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5">
                      {i.confidence != null && <ConfidenceDot value={i.confidence} />}
                      <span className="truncate text-[13px] font-medium">{i.name}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 text-[12px] tabular-nums text-ink-muted">
                      {t.nutrition.kcal(f.num(itemNutrients(i).energy_kcal ?? 0))}
                      <button type="button" aria-label={m.remove(i.name)} onClick={() => setItems((xs) => xs.filter((x) => x.key !== i.key))}
                        className="grid h-6 w-6 place-items-center rounded text-[var(--text-faint)] hover:text-[var(--text-primary)]">
                        <CloseIcon width={13} height={13} />
                      </button>
                    </span>
                  </div>
                  {i.alternatives && i.alternatives.length > 1 && (
                    <label className="flex items-center gap-2 text-[11.5px] text-ink-muted">
                      {/* what Claude saw, when it is not simply the name of the food it matched */}
                      <span>{i.label && !i.name.toLowerCase().includes(i.label.toLowerCase()) ? m.sawAs(i.label) : `${m.swap}:`}</span>
                      <select className="ds-input h-7 min-w-0 flex-1 py-0 text-[12px]" value={i.food_ref} onChange={(e) => swap(i, e.target.value)} aria-label={m.swap}>
                        {i.alternatives.map((a) => <option key={a.ref} value={a.ref}>{foodName(a, locale)}</option>)}
                      </select>
                    </label>
                  )}
                  <GramField value={i.grams} unit={i.unit} portion={i.portion_g} estimated={estimated} label={`${i.name}: ${m.amount(i.unit)}`}
                    onChange={(grams) => update(i.key, { grams, grams_source: "user" })} />
                  {i.grams_source === "memory" && <span className="text-[11px] text-ink-muted">{m.fromMemory}</span>}
                </li>
              );
            })}
          </ul>
        )}

        {(extras.length > 0 || unmatched.length > 0) && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={m.extras}>
            {extras.map((x, idx) => (
              <button key={`x${idx}`} type="button" onClick={() => addExtra(idx)}
                className="flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[12px] text-ink-muted hover:text-[var(--text-primary)]">
                <PlusIcon width={11} height={11} />{m.extra(locale === "en" && x.label_en ? x.label_en : x.label_nl, f.num(x.grams))}
              </button>
            ))}
            {unmatched.map((label) => (
              <button key={`u${label}`} type="button" onClick={() => { setPicking(label); setUnmatched((xs) => xs.filter((y) => y !== label)); }}
                className="rounded-full border border-dashed border-border px-2.5 py-1 text-[12px] text-ink-muted hover:text-[var(--text-primary)]">
                {m.notFound(label)}
              </button>
            ))}
          </div>
        )}

        {picking != null ? (
          <div className="flex flex-col gap-2">
            {items.length === 0 && !start?.failed && <p className="text-[12.5px] text-ink-muted">{m.start}</p>}
            <FoodPicker key={picking} onPick={pick} autoFocus initial={picking} />
          </div>
        ) : (
          <button type="button" onClick={() => setPicking("")} className="self-start text-[12.5px] font-medium underline underline-offset-4">{m.addItem}</button>
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
        {!meal && items.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Checkbox checked={favourite} onChange={setFavourite} label={m.saveFavourite} />
            {favourite && <Input aria-label={m.favouriteName} placeholder={m.favouriteName} value={favName} onChange={(e) => setFavName(e.target.value)} maxLength={100} className="min-w-0 flex-1" />}
          </div>
        )}
        {error && <p className="text-[12.5px] text-loss" role="alert">{error}</p>}
      </form>
    </Dialog>
  );
}
