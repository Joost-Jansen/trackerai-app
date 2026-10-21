// From what the user starts with (a saved meal, a food from search or a barcode, a photo's draft, a favourite,
// yesterday's meal) to the items the meal editor holds.

import { foodName, type DraftItem, type EditorStart, type Food, type Meal, type PhotoDraft, type Template } from "@/lib/nutrition";

let seq = 0;
export const draftKey = () => `n${++seq}`;

/** A saved item: its snapshot scales when the amount changes (the food may have changed or gone since). */
export function fromMeal(meal: Meal, keepIds = true): DraftItem[] {
  return meal.items.map((i) => ({
    key: draftKey(),
    id: keepIds ? i.id : undefined,
    food_ref: i.food_ref,
    name: i.name,
    unit: i.unit,
    grams: i.grams,
    per_100: null,
    snapshot: i.nutrients,
    snapshotGrams: i.grams,
    grams_source: keepIds ? i.grams_source : "user",
    grams_ai: i.grams_ai,
    grams_low: i.grams_low,
    grams_high: i.grams_high,
    confidence: i.confidence,
  }));
}

export function fromFood(food: Food, locale: string, grams?: number): DraftItem {
  return {
    key: draftKey(),
    food_ref: food.ref,
    name: foodName(food, locale),
    unit: food.unit,
    per_100: food.per_100,
    grams: Math.round(grams ?? food.portion_g ?? food.default_portion_g ?? 100),
    portion_g: food.portion_g ?? null,
    grams_source: "user",
  };
}

export function fromPhoto(draft: PhotoDraft, locale: string): DraftItem[] {
  return draft.items
    .filter((i) => i.food)
    .map((i) => ({
      ...fromFood(i.food!, locale, i.grams),
      grams: i.grams,
      grams_source: i.grams_source,
      grams_ai: i.grams_ai,
      grams_low: i.grams_low,
      grams_high: i.grams_high,
      confidence: i.confidence,
      label: locale === "en" && i.label_en ? i.label_en : i.label_nl,
      alternatives: i.alternatives,
    }));
}

/** A favourite: its items with the food's values per 100 (the API adds them). */
export function fromTemplate(t: Template): DraftItem[] {
  return t.items.map((i) => ({
    key: draftKey(),
    food_ref: i.food_ref,
    name: i.name,
    unit: i.unit,
    grams: i.grams,
    per_100: i.per_100 ?? null,
    grams_source: "user",
  }));
}

export const photoStart = (draft: PhotoDraft, preview: string | null, locale: string, eatenAt?: string): EditorStart => ({
  input: "photo",
  items: fromPhoto(draft, locale),
  moment: draft.moment_guess,
  eaten_at: eatenAt,
  photo: { id: draft.photo_id, preview },
  ai_run_id: draft.ai_run_id,
  extras: draft.hidden_extras,
  failed: draft.failed,
  unmatched: draft.items.filter((i) => !i.food).map((i) => (locale === "en" && i.label_en ? i.label_en : i.label_nl)),
});
