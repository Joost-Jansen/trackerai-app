// Nutrition (Voeding): the shapes api/nutrition.py returns and small helpers around them. Nutrient keys are those of
// tools/nutrition/nutrients.py; values per 100 g or 100 ml (a food's `unit`), None where the source has none.

export const NUTRIENT_KEYS = [
  "energy_kcal", "carbs_g", "sugars_g", "fiber_g", "protein_g", "fat_g", "sat_fat_g", "mufa_g", "pufa_g", "omega3_g",
  "trans_fat_g", "alcohol_g", "salt_g", "sodium_mg", "iron_mg", "calcium_mg", "magnesium_mg", "potassium_mg", "zinc_mg",
  "vit_c_mg", "vit_d_ug", "vit_b12_ug", "folate_ug",
] as const;
export type NutrientKey = (typeof NUTRIENT_KEYS)[number];
export type Nutrients = Partial<Record<NutrientKey, number | null>>;
export type Totals = Record<NutrientKey, number> & { missing: Partial<Record<NutrientKey, number>> };

export const MOMENTS = ["breakfast", "lunch", "dinner", "snack", "training", "drinks"] as const;
export type Moment = (typeof MOMENTS)[number];
export type Unit = "g" | "ml";
export type GramsSource = "ai" | "user" | "memory" | "agent";

export type MealItem = {
  id: number;
  position: number;
  food_ref: string;
  name: string;
  unit: Unit;
  grams: number;
  grams_ai: number | null;
  grams_low: number | null;
  grams_high: number | null;
  grams_source: GramsSource;
  confidence: number | null;
  nutrients: Nutrients;
};

export type Meal = {
  id: number;
  day: string;
  eaten_at: string;
  moment: Moment;
  input: "photo" | "search" | "barcode" | "repeat" | "agent";
  photo_id: number | null;
  note: string | null;
  items: MealItem[];
  totals: Totals;
};

export type DayType = "rest" | "easy" | "moderate" | "long" | "race";

export type TargetSession = { minutes: number; hard: boolean; race: boolean; sport: string; distance_km: number | null; kind?: string | null; name?: string | null; done: boolean };

export type Targets = {
  day: string;
  day_type: DayType;
  own_type: DayType;
  sessions: TargetSession[];
  weight_kg: number | null;
  carbs_per_kg: [number, number];
  protein_per_kg: [number, number];
  carbs_g: [number, number] | null;
  protein_g: [number, number] | null;
  tomorrow: { day_type: DayType; sport: string; kind: string | null; distance_km: number | null; minutes: number } | null;
};

export type NutritionContext =
  | { line: "tomorrow"; day_type: DayType; sport: string; kind: string | null; distance_km: number | null; minutes: number; carbs_per_kg: [number, number] }
  | { line: "after_training" };

export type NutritionDay = {
  day: string;
  today: string;
  meals: Meal[];
  totals: Totals;
  energy_split: Record<"carbs_g" | "protein_g" | "fat_g" | "alcohol_g" | "fiber_g", number>;
  per_kg: { carbs: number | null; protein: number | null };
  targets: Targets;
  context: NutritionContext | null;
  last_meal: string | null;
  /** Garmin's estimated burn for the day (resting + active), when the day is synced. */
  burn_kcal: number | null;
  source: { version: string | null; nl: string | null; en: string | null };
  foods_ready: boolean;
  /** Photo analysis is on for this user and the server can do it. */
  ai: boolean;
  kcal_target: number | null;
};

/** The Voeding vandaag card on /api/dashboard (`nutrition`): null without the beta. */
export type NutritionBlock =
  | ({ empty: false } & Pick<NutritionDay, "today" | "meals" | "totals" | "per_kg" | "targets" | "context" | "last_meal" | "burn_kcal" | "ai">)
  | { empty: true; today: string; targets: Targets; context: NutritionContext | null; ai: boolean };

export type Food = {
  ref: string;
  source: "nevo" | "off" | "usda" | "user";
  name: string;
  name_en: string | null;
  brand: string | null;
  group: string | null;
  unit: Unit;
  per_100: Nutrients;
  default_portion_g: number | null;
  version: string | null;
  uses?: number;
  /** Your usual amount (portion memory), else the food's default portion. */
  portion_g?: number | null;
};

/** A food's name in the reader's language: NEVO has an English name for most foods; your own foods have one name. */
export function foodName(food: Pick<Food, "name" | "name_en">, locale: string): string {
  return locale === "en" && food.name_en ? food.name_en : food.name;
}

/** One item while you compose a meal: what the editor holds before it is saved. */
export type DraftItem = {
  key: string;
  id?: number;
  food_ref: string;
  name: string;
  unit: Unit;
  grams: number;
  per_100: Nutrients | null; // null for a saved item whose food is no longer loaded: scale its snapshot
  snapshot?: Nutrients;
  snapshotGrams?: number;
  portion_g?: number | null;
  /** Where the amount came from: Claude's estimate, your usual portion, or you (touching it makes it yours). */
  grams_source?: GramsSource;
  grams_ai?: number | null;
  grams_low?: number | null;
  grams_high?: number | null;
  confidence?: number | null;
  /** From a photo: what Claude saw ("havermout") and the other foods it could be. */
  label?: string;
  alternatives?: Food[];
};

/** An item Claude saw on a photo, matched to a food (api/nutrition.py POST /photo, tools/nutrition/match.py). */
export type PhotoItem = {
  label_nl: string;
  label_en: string | null;
  kind: "food" | "drink" | "sauce" | "fat";
  grams: number;
  grams_ai: number;
  grams_low: number;
  grams_high: number;
  grams_source: GramsSource;
  confidence: number;
  food: Food | null;
  alternatives: Food[];
};

export type PhotoDraft = {
  photo_id: number | null;
  ai_run_id: number | null;
  /** Why the analysis gave nothing (unreachable, refused, ...); the photo is kept and search takes over. */
  failed: string | null;
  items: PhotoItem[];
  hidden_extras: { label_nl: string; label_en: string | null; grams: number; food: Food | null }[];
  moment_guess: Moment | null;
};

export type Template = {
  id: number;
  name: string;
  moment: Moment | null;
  items: { food_ref: string; name: string; unit: Unit; grams: number; per_100?: Nutrients | null }[];
  position: number;
};

export type NutritionSettings = {
  ai: boolean;
  photos: "30d" | "keep" | "never";
  kcal_target: number | null;
  ai_available: boolean;
  weight_kg: number | null;
  day_types: Record<DayType, { carbs_per_kg: [number, number]; protein_per_kg: [number, number] }>;
};

/** How the editor starts: from scratch, a photo's draft, a barcode, a favourite or yesterday's meal. */
export type EditorStart = {
  input: Meal["input"];
  items: DraftItem[];
  moment?: Moment | null;
  eaten_at?: string;
  photo?: { id: number | null; preview: string | null };
  ai_run_id?: number | null;
  extras?: PhotoDraft["hidden_extras"];
  /** What Claude saw but no food matched: offered as a search. */
  unmatched?: string[];
  failed?: string | null;
};

export const photoUrl = (id: number) => `/api/nutrition/photos/${id}`;

/** What `grams` of an item hold, as the server will compute it (tools/nutrition/nutrients.py scale). */
export function itemNutrients(item: DraftItem): Nutrients {
  const out: Nutrients = {};
  const base = item.per_100 ?? item.snapshot ?? {};
  const factor = item.per_100 ? item.grams / 100 : item.snapshotGrams ? item.grams / item.snapshotGrams : 0;
  for (const k of NUTRIENT_KEYS) {
    const v = base[k];
    out[k] = v == null ? null : v * factor;
  }
  return out;
}

export function sumNutrients(items: Nutrients[]): Record<NutrientKey, number> {
  const out = Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, 0])) as Record<NutrientKey, number>;
  for (const it of items) for (const k of NUTRIENT_KEYS) out[k] += it[k] ?? 0;
  return out;
}

/** The meal moment the clock suggests: what most people call a meal at that hour. */
export function momentAt(hhmm: string): Moment {
  const [h, m] = hhmm.split(":").map(Number);
  const t = h * 60 + m;
  if (t >= 5 * 60 && t < 10 * 60 + 30) return "breakfast";
  if (t >= 11 * 60 + 30 && t < 14 * 60 + 30) return "lunch";
  if (t >= 17 * 60 && t < 21 * 60) return "dinner";
  return "snack";
}

export function nowHHMM(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** The colour token of a macro (app/globals.css). */
export const MACRO_COLOUR: Partial<Record<NutrientKey, string>> = {
  carbs_g: "var(--macro-carb)",
  protein_g: "var(--macro-protein)",
  fat_g: "var(--macro-fat)",
  alcohol_g: "var(--macro-alcohol)",
  fiber_g: "var(--macro-fiber)",
};

