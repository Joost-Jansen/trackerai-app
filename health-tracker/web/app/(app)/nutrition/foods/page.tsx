"use client";

// Voeding, Mijn voeding: what the app keeps about your food. Favourites (rename, reorder, delete), your usual portions
// (learnt from what you set; change or forget one), your own products from a label, the packaged products you scanned,
// and one search over all of it with the source of every result.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { ChevronDownIcon, CloseIcon, PlusIcon } from "@trackerai/ui/icons";
import { Button, Columns, Dialog, Input, Select } from "@/components/ds";
import FoodPicker from "@/components/nutrition/FoodPicker";
import { api } from "@/lib/api";
import { errorText, useFormat, useLocale, useT } from "@/lib/i18n";
import { foodName, type Food, type NutrientKey, type Template, type Unit } from "@/lib/nutrition";

type Portion = {
  ref: string;
  name: string;
  name_en: string | null;
  source: string;
  unit: Unit;
  grams: number;
  uses: number;
  last_used: string | null;
};
type UserFoods = { own: Food[]; scanned: Food[] };

// What a label lists, in the order it lists it (per 100 g or ml).
const LABEL: NutrientKey[] = ["energy_kcal", "fat_g", "sat_fat_g", "carbs_g", "sugars_g", "fiber_g", "protein_g", "salt_g"];
const KEYS = ["nutrition-templates", "nutrition-portions", "nutrition-user-foods", "nutrition-search", "nutrition-recent", "nutrition-day"];

function useRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ predicate: (q) => KEYS.includes(String(q.queryKey[0])) });
}

function ProductDialog({ food, onClose }: { food: Food | null; onClose: () => void }) {
  const tt = useT();
  const t = tt.nutrition.foods;
  const f = useFormat();
  const refresh = useRefresh();
  const [name, setName] = useState(food?.name ?? "");
  const [brand, setBrand] = useState(food?.brand ?? "");
  const [unit, setUnit] = useState<Unit>(food?.unit ?? "g");
  const [portion, setPortion] = useState(f.input(food?.default_portion_g));
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(LABEL.map((k) => [k, f.input(food?.per_100[k] ?? null)])),
  );
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const per_100 = Object.fromEntries(LABEL.map((k) => [k, f.parse(values[k] ?? "")]));
    if (Object.values(per_100).some((v) => v != null && !Number.isFinite(v))) return setError(t.failed);
    const body = { name: name.trim(), brand: brand.trim() || null, unit, default_portion_g: f.parse(portion), per_100 };
    try {
      if (food) await api.patch(`/api/nutrition/user-foods/${food.ref.split(":")[1]}`, body);
      else await api.post("/api/nutrition/user-foods", body);
      await refresh();
      onClose();
    } catch (err) {
      setError(errorText(err, tt, t.failed));
    }
  }

  async function remove() {
    if (!food) return;
    await api.del(`/api/nutrition/user-foods/${food.ref.split(":")[1]}`);
    await refresh();
    onClose();
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={food ? t.editProduct : t.addProduct}
      actions={
        <>
          {food && (
            <Button variant="ghost" className="mr-auto" onClick={remove}>
              {t.delete}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {tt.nutrition.editor.cancel}
          </Button>
          <Button variant="primary" type="submit" form="product-form">
            {tt.nutrition.editor.save}
          </Button>
        </>
      }
    >
      <form id="product-form" onSubmit={save} className="-mx-1 flex max-h-[65vh] flex-col gap-3 overflow-y-auto px-1">
        <Input label={t.name} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoFocus />
        <div className="grid grid-cols-[1fr_88px] gap-3">
          <Input label={t.brand} value={brand} onChange={(e) => setBrand(e.target.value)} maxLength={100} />
          <Select label={t.per} value={unit} onChange={(e) => setUnit(e.target.value as Unit)}>
            <option value="g">100 g</option>
            <option value="ml">100 ml</option>
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          {LABEL.map((k) => (
            <Input
              key={k}
              label={`${tt.nutrition.nutrients[k]} (${k === "energy_kcal" ? "kcal" : "g"})`}
              inputMode="decimal"
              value={values[k] ?? ""}
              onChange={(e) => setValues({ ...values, [k]: e.target.value })}
            />
          ))}
        </div>
        <Input
          label={t.portion(unit)}
          inputMode="decimal"
          value={portion}
          onChange={(e) => setPortion(e.target.value)}
          hint={t.portionHint}
        />
        {error && (
          <p className="text-[12.5px] text-loss" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

function Favourites() {
  const tt = useT();
  const t = tt.nutrition.foods;
  const refresh = useRefresh();
  const q = useQuery({ queryKey: ["nutrition-templates"], queryFn: () => api.get<Template[]>("/api/nutrition/templates") });
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);
  const list = q.data ?? [];
  const move = async (tpl: Template, by: number) => {
    await api.patch(`/api/nutrition/templates/${tpl.id}`, { position: Math.max(0, list.indexOf(tpl) + by) });
    refresh();
  };
  return (
    <Card title={t.favourites}>
      {list.length === 0 ? (
        <p className="text-[13px] text-ink-muted">{t.noFavourites}</p>
      ) : (
        <ul className="flex flex-col">
          {list.map((tpl, i) => (
            <li key={tpl.id} className="flex items-center gap-2 border-t border-border py-2 first:border-t-0">
              <div className="min-w-0 flex-1">
                {renaming?.id === tpl.id ? (
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      await api.patch(`/api/nutrition/templates/${tpl.id}`, { name: renaming.name });
                      setRenaming(null);
                      refresh();
                    }}
                  >
                    <Input
                      aria-label={t.name}
                      value={renaming.name}
                      onChange={(e) => setRenaming({ id: tpl.id, name: e.target.value })}
                      maxLength={100}
                      autoFocus
                      onBlur={() => setRenaming(null)}
                    />
                  </form>
                ) : (
                  <button
                    type="button"
                    className="block text-left text-[13px] font-medium"
                    onClick={() => setRenaming({ id: tpl.id, name: tpl.name })}
                    title={t.rename}
                  >
                    {tpl.name}
                  </button>
                )}
                <span className="block truncate text-[11.5px] text-ink-muted">
                  {tpl.items.map((x) => `${x.name} ${Math.round(x.grams)} ${x.unit}`).join(", ")}
                </span>
              </div>
              <button
                type="button"
                aria-label={t.up(tpl.name)}
                disabled={i === 0}
                onClick={() => move(tpl, -1)}
                className="grid h-7 w-7 rotate-180 place-items-center text-[var(--text-faint)] disabled:opacity-30"
              >
                <ChevronDownIcon width={14} height={14} />
              </button>
              <button
                type="button"
                aria-label={t.down(tpl.name)}
                disabled={i === list.length - 1}
                onClick={() => move(tpl, 1)}
                className="grid h-7 w-7 place-items-center text-[var(--text-faint)] disabled:opacity-30"
              >
                <ChevronDownIcon width={14} height={14} />
              </button>
              <button
                type="button"
                aria-label={t.remove(tpl.name)}
                onClick={async () => {
                  await api.del(`/api/nutrition/templates/${tpl.id}`);
                  refresh();
                }}
                className="grid h-7 w-7 place-items-center text-[var(--text-faint)] hover:text-[var(--text-primary)]"
              >
                <CloseIcon width={13} height={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Portions() {
  const tt = useT();
  const t = tt.nutrition.foods;
  const f = useFormat();
  const { locale } = useLocale();
  const refresh = useRefresh();
  const q = useQuery({ queryKey: ["nutrition-portions"], queryFn: () => api.get<Portion[]>("/api/nutrition/portions") });
  const [edit, setEdit] = useState<{ ref: string; text: string } | null>(null);
  const list = q.data ?? [];
  return (
    <Card title={t.portions}>
      <p className="mb-2 text-[12px] text-ink-muted">{t.portionsIntro}</p>
      {list.length === 0 ? (
        <p className="text-[13px] text-ink-muted">{t.noPortions}</p>
      ) : (
        <ul className="flex flex-col">
          {list.map((p) => (
            <li key={p.ref} className="flex items-center gap-2 border-t border-border py-2 first:border-t-0 text-[13px]">
              <span className="min-w-0 flex-1 truncate">{foodName(p, locale)}</span>
              {edit?.ref === p.ref ? (
                <form
                  className="flex items-center gap-1"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const g = f.parse(edit.text);
                    if (g && g > 0) await api.put(`/api/nutrition/portions/${encodeURIComponent(p.ref)}`, { grams: g });
                    setEdit(null);
                    refresh();
                  }}
                >
                  <Input
                    aria-label={t.portion(p.unit)}
                    inputMode="decimal"
                    value={edit.text}
                    onChange={(e) => setEdit({ ref: p.ref, text: e.target.value })}
                    className="w-20"
                    autoFocus
                  />
                  <span className="text-[12px] text-ink-muted">{p.unit}</span>
                  <Button size="sm" variant="secondary" type="submit">
                    {tt.common.save}
                  </Button>
                </form>
              ) : (
                <button
                  type="button"
                  className="tabular-nums underline decoration-dotted underline-offset-4"
                  onClick={() => setEdit({ ref: p.ref, text: f.input(p.grams) })}
                >
                  {f.num(p.grams)} {p.unit}
                </button>
              )}
              <span className="w-16 text-right text-[11.5px] tabular-nums text-ink-muted">{t.uses(p.uses)}</span>
              <button
                type="button"
                aria-label={t.forget(foodName(p, locale))}
                onClick={async () => {
                  await api.del(`/api/nutrition/portions/${encodeURIComponent(p.ref)}`);
                  refresh();
                }}
                className="grid h-7 w-7 place-items-center text-[var(--text-faint)] hover:text-[var(--text-primary)]"
              >
                <CloseIcon width={13} height={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Products() {
  const tt = useT();
  const t = tt.nutrition.foods;
  const f = useFormat();
  const { locale } = useLocale();
  const q = useQuery({ queryKey: ["nutrition-user-foods"], queryFn: () => api.get<UserFoods>("/api/nutrition/user-foods") });
  const [open, setOpen] = useState<Food | null | "new">(null);
  const row = (food: Food, onClick?: () => void) => (
    <li key={food.ref} className="border-t border-border first:border-t-0">
      <button
        type="button"
        disabled={!onClick}
        onClick={onClick}
        className="flex w-full items-baseline justify-between gap-3 py-2 text-left disabled:cursor-default"
      >
        <span className="min-w-0">
          <span className="block truncate text-[13px]">{foodName(food, locale)}</span>
          {food.brand && <span className="block text-[11px] text-ink-muted">{food.brand}</span>}
        </span>
        <span className="shrink-0 text-[11.5px] tabular-nums text-ink-muted">
          {tt.nutrition.kcal(f.num(food.per_100.energy_kcal ?? 0))}/100 {food.unit}
        </span>
      </button>
    </li>
  );
  return (
    <>
      <Card
        title={t.own}
        action={
          <Button size="sm" variant="secondary" icon={<PlusIcon width={14} height={14} />} onClick={() => setOpen("new")}>
            {t.addProduct}
          </Button>
        }
      >
        {(q.data?.own ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t.noOwn}</p>
        ) : (
          <ul className="flex flex-col">{q.data!.own.map((food) => row(food, () => setOpen(food)))}</ul>
        )}
      </Card>
      <Card title={t.scanned}>
        {(q.data?.scanned ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t.noScanned}</p>
        ) : (
          <ul className="flex flex-col">{q.data!.scanned.map((food) => row(food))}</ul>
        )}
        <p className="mt-2 text-[11.5px] text-ink-muted">{t.offCredit}</p>
      </Card>
      {open && <ProductDialog food={open === "new" ? null : open} onClose={() => setOpen(null)} />}
    </>
  );
}

function Search() {
  const tt = useT();
  const t = tt.nutrition.foods;
  const f = useFormat();
  const { locale } = useLocale();
  const [food, setFood] = useState<Food | null>(null);
  return (
    <Card title={t.search}>
      <FoodPicker onPick={setFood} />
      {food && (
        <div className="mt-3 rounded-md bg-[var(--surface-sunken)] px-3 py-2 text-[12.5px]">
          <p className="font-medium">
            {foodName(food, locale)} <span className="font-normal text-ink-muted">· {t.sources[food.source]}</span>
          </p>
          <p className="mt-1 flex flex-wrap gap-x-3 tabular-nums text-ink-muted">
            {LABEL.map((k) => (
              <span key={k}>
                {tt.nutrition.nutrients[k]} {food.per_100[k] == null ? "–" : f.trim(food.per_100[k]!, 1)}
                {k === "energy_kcal" ? " kcal" : " g"}
              </span>
            ))}
          </p>
          <p className="mt-1 text-[11.5px] text-ink-muted">
            {t.per100(food.unit)}
            {food.portion_g ? ` · ${t.yourPortion(f.num(food.portion_g), food.unit)}` : ""}
          </p>
        </div>
      )}
    </Card>
  );
}

export default function Page() {
  return (
    <div className="flex flex-col gap-4">
      <Search />
      <Columns left={[<Favourites key="fav" />, <Portions key="portions" />]} right={[<Products key="products" />]} />
    </div>
  );
}
