"use client";

// Huid, Dag: the skin diary of one day (today by default, another through ?day=), filled in with a form. What the day
// already has comes from the API, so an entry an assistant made (MCP add_skin_entry) shows here and can be changed.
// The day's training comes from the existing data, to tick "red afterwards"; Garmin's night is shown next to the
// user's own sleep rating. Private: only for the accounts the API lists (lib/skin.ts useSkinGate).

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { CameraIcon, ChevronLeftIcon, ChevronRightIcon } from "@trackerai/ui/icons";
import { Button, Checkbox, Columns, IconButton, Input } from "@/components/ds";
import { addDays } from "@/components/plan/plan";
import { preparePhoto } from "@/components/nutrition/photo";
import { api, ApiError } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";
import { LOCATIONS, useSkinGate, type DayView, type Entry, type EntryFields, type SportMark } from "@/lib/skin";

const EMPTY: EntryFields = {
  itch: null,
  redness: null,
  oiliness: null,
  bumps: null,
  burning: null,
  locations: [],
  flaking: null,
  products: [],
  new_products: [],
  food: [],
  sport: [],
  sleep: null,
  stress: null,
  weather: null,
  heating: null,
  note: null,
};
const FOOD_SUGGESTIONS = ["witte chocolade", "alcohol"];

const fieldsOf = (e: Entry | null): EntryFields => {
  if (!e) return { ...EMPTY };
  const { id: _id, day: _day, photo_id: _photo, ...rest } = e;
  return rest;
};

/** 0 to 10 as a row of buttons; the chosen one again clears it (not filled in is not 0). */
function Scale({
  label,
  hint,
  value,
  onChange,
  min = 0,
  max = 10,
}: {
  label: string;
  hint?: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12.5px] font-medium">{label}</span>
      <div className="ds-segmented flex w-full" role="group" aria-label={label}>
        {Array.from({ length: max - min + 1 }, (_, i) => min + i).map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            className={`ds-segmented__item min-w-0 flex-1 px-0 tabular-nums ${value === n ? "ds-segmented__item--active" : ""}`}
            onClick={() => onChange(value === n ? null : n)}
          >
            {min < 0 && n > 0 ? `+${n}` : n}
          </button>
        ))}
      </div>
      {hint && <span className="text-[11.5px] text-ink-muted">{hint}</span>}
    </div>
  );
}

/** Yes, no or not filled in. */
function YesNo({ label, value, onChange }: { label: string; value: boolean | null | undefined; onChange: (v: boolean | null) => void }) {
  const tt = useT();
  const t = tt.skin;
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[13px]">{label}</span>
      <div className="ds-segmented" role="group" aria-label={label}>
        {([true, false] as const).map((v) => (
          <button
            key={String(v)}
            type="button"
            aria-pressed={value === v}
            className={`ds-segmented__item ${value === v ? "ds-segmented__item--active" : ""}`}
            onClick={() => onChange(value === v ? null : v)}
          >
            {v ? t.yes : t.no}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Free-text items as chips: type and press Enter (or Add); earlier items are offered as suggestions. */
function Items({
  label,
  hint,
  values,
  suggestions,
  onChange,
}: {
  label: string;
  hint?: string;
  values: string[];
  suggestions: string[];
  onChange: (v: string[]) => void;
}) {
  const t = useT().skin;
  const [text, setText] = useState("");
  const listId = `skin-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const add = () => {
    const v = text.trim().replace(/\s+/g, " ");
    if (v && !values.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...values, v]);
    setText("");
  };
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Input
            label={label}
            hint={hint ?? t.listHint}
            value={text}
            list={listId}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
        </div>
        <Button size="sm" onClick={add} disabled={!text.trim()} className="mb-[22px]">
          {t.add}
        </Button>
      </div>
      <datalist id={listId}>
        {suggestions
          .filter((s) => !values.some((v) => v.toLowerCase() === s.toLowerCase()))
          .map((s) => (
            <option key={s} value={s} />
          ))}
      </datalist>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <button
              key={v}
              type="button"
              aria-label={t.removeItem(v)}
              className="rounded-full border border-border px-2.5 py-0.5 text-[12.5px] hover:bg-surface-2"
              onClick={() => onChange(values.filter((x) => x !== v))}
            >
              {v} <span aria-hidden>×</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SkinDay() {
  const param = useSearchParams().get("day");
  const day = param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? param : null;
  const tt = useT();
  const t = tt.skin;
  const f = useFormat();
  const router = useRouter();
  const qc = useQueryClient();
  const camera = useRef<HTMLInputElement>(null);
  const q = useQuery({
    queryKey: ["skin-day", day],
    queryFn: () => api.get<DayView>(`/api/skin/day${day ? `?day=${day}` : ""}`),
    placeholderData: keepPreviousData,
  });
  // What was used before, as suggestions in the lists.
  const recent = useQuery({ queryKey: ["skin-overview", "recent"], queryFn: () => api.get<{ entries: Entry[] }>("/api/skin/overview") });
  const [draft, setDraft] = useState<EntryFields>(EMPTY);
  const [other, setOther] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  // The form starts from what the day has when another day loads, and never again on a refetch: a photo upload
  // refetching the day must not throw away what is typed but not saved yet.
  const [draftDay, setDraftDay] = useState<string | null>(null);
  const loaded = q.data && !q.isPlaceholderData ? q.data : null;
  useEffect(() => {
    if (loaded && loaded.day !== draftDay) {
      setDraft(fieldsOf(loaded.entry));
      setDraftDay(loaded.day);
    }
  }, [loaded, draftDay]);

  // Only the photo changes in the cached day; the form keeps what is typed.
  const photoChanged = (e: Entry | null) =>
    qc.setQueryData<DayView>(["skin-day", day], (old) =>
      old && e ? { ...old, entry: old.entry ? { ...old.entry, photo_id: e.photo_id } : e } : old,
    );
  const after = (v: DayView) => {
    qc.setQueryData(["skin-day", day], v);
    qc.invalidateQueries({ queryKey: ["skin-overview"] });
  };
  const save = useMutation({
    mutationFn: (fields: EntryFields) => api.put<DayView>(`/api/skin/day/${q.data!.day}`, fields),
    onSuccess: (v) => {
      after(v);
      setDraft(fieldsOf(v.entry));
      setSavedAt(v.day);
    },
  });
  const photo = useMutation({
    mutationFn: async (file: File) => api.upload<{ entry: Entry }>(`/api/skin/photo?day=${q.data!.day}`, await preparePhoto(file)),
    onSuccess: (r) => photoChanged(r.entry),
  });
  const dropPhoto = useMutation({
    mutationFn: () => api.del<{ entry: Entry | null }>(`/api/skin/photo?day=${q.data!.day}`),
    onSuccess: (r) => photoChanged(r.entry),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/skin/day/${q.data!.day}`),
    onSuccess: () => {
      setDraftDay(null); // start the form again from the (now empty) day
      qc.invalidateQueries({ queryKey: ["skin-day", day] });
      qc.invalidateQueries({ queryKey: ["skin-overview"] });
    },
  });

  if (q.isLoading) return <p className="text-sm text-ink-muted">{tt.common.loading}</p>;
  if (!q.data) return null;
  const d = q.data;
  const entry = d.entry;
  const set = (fields: EntryFields) => {
    setDraft((old) => ({ ...old, ...fields }));
    setSavedAt(null);
  };
  const go = (iso: string) => router.replace(iso === d.today ? "/skin/" : `/skin/?day=${iso}`, { scroll: false });
  const used = (key: "products" | "new_products" | "food") => {
    const seen = new Map<string, string>();
    for (const e of recent.data?.entries ?? []) for (const v of e[key]) seen.set(v.toLowerCase(), v);
    if (key === "food") for (const v of FOOD_SUGGESTIONS) if (!seen.has(v)) seen.set(v, v);
    return [...seen.values()];
  };
  const sport = draft.sport ?? [];
  const marked = (m: SportMark) => sport.find((s) => (m.activity_id ? s.activity_id === m.activity_id : s.name === m.name));
  const toggleSport = (m: SportMark, red: boolean) => set({ sport: [...sport.filter((s) => s !== marked(m)), { ...m, red }] });
  const error = save.error ?? photo.error ?? dropPhoto.error ?? remove.error;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2
            aria-live="polite"
            className={`font-display text-[21px] font-light transition-opacity ${q.isPlaceholderData ? "opacity-60" : ""}`}
          >
            {f.weekdayDayYear(d.day)}
          </h2>
          <p className="text-[12.5px] text-ink-muted">{t.intro}</p>
        </div>
        <div className="flex items-center gap-1">
          <IconButton
            label={t.prevDay}
            size="sm"
            icon={<ChevronLeftIcon width={15} height={15} />}
            onClick={() => go(addDays(d.day, -1))}
          />
          <input
            type="date"
            aria-label={t.title}
            value={d.day}
            max={d.today}
            onChange={(e) => /^\d{4}-\d{2}-\d{2}$/.test(e.target.value) && go(e.target.value)}
            className="h-8 rounded border border-border bg-surface px-2 text-[13px] tabular-nums text-[var(--text-primary)]"
          />
          <IconButton
            label={t.nextDay}
            size="sm"
            icon={<ChevronRightIcon width={15} height={15} />}
            disabled={d.day >= d.today}
            onClick={() => go(addDays(d.day, 1))}
          />
        </div>
      </div>

      <Columns
        left={[
          <Card key="skin" title={t.skin}>
            <div className="flex flex-col gap-4">
              <Scale label={t.itch} hint={t.scaleHint} value={draft.itch} onChange={(v) => set({ itch: v })} />
              <Scale label={t.redness} value={draft.redness} onChange={(v) => set({ redness: v })} />
              <Scale
                label={t.oiliness}
                hint={t.oilinessHint}
                min={-5}
                max={5}
                value={draft.oiliness}
                onChange={(v) => set({ oiliness: v })}
              />
              <Input
                label={t.bumps}
                type="number"
                inputMode="numeric"
                min={0}
                max={500}
                value={draft.bumps ?? ""}
                onChange={(e) => set({ bumps: e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))) })}
                className="max-w-[8rem]"
              />
              <YesNo label={t.burning} value={draft.burning} onChange={(v) => set({ burning: v })} />
              <YesNo label={t.flaking} value={draft.flaking} onChange={(v) => set({ flaking: v })} />
              <div className="flex flex-col gap-1.5">
                <span className="text-[12.5px] font-medium">{t.where}</span>
                <div className="flex flex-wrap gap-x-4 gap-y-2">
                  {LOCATIONS.map((l) => (
                    <Checkbox
                      key={l}
                      label={t.locations[l]}
                      checked={(draft.locations ?? []).includes(l)}
                      onChange={(on) => set({ locations: LOCATIONS.filter((x) => (x === l ? on : (draft.locations ?? []).includes(x))) })}
                    />
                  ))}
                </div>
              </div>
            </div>
          </Card>,
          <Card key="touched" title={t.whatTouched}>
            <div className="flex flex-col gap-4">
              <Items
                label={t.products}
                values={draft.products ?? []}
                suggestions={used("products")}
                onChange={(v) => set({ products: v })}
              />
              <Items
                label={t.newProducts}
                values={draft.new_products ?? []}
                suggestions={used("new_products")}
                onChange={(v) => set({ new_products: v })}
              />
              <Items
                label={t.food}
                hint={t.foodHint}
                values={draft.food ?? []}
                suggestions={used("food")}
                onChange={(v) => set({ food: v })}
              />
            </div>
          </Card>,
        ]}
        right={[
          <Card key="around" title={t.dayAround}>
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <span className="text-[12.5px] font-medium">{t.sport}</span>
                {d.context.activities.length === 0 && <p className="text-[12.5px] text-ink-muted">{t.noActivities}</p>}
                {[
                  ...d.context.activities.map((a) => ({
                    activity_id: a.activity_id,
                    name: a.name || tt.sport(a.sport ?? ""),
                    red: false,
                    at: a.start,
                  })),
                  ...sport.filter((s) => !s.activity_id).map((s) => ({ ...s, at: "" })),
                ].map((a) => (
                  <div key={a.activity_id ?? a.name} className="flex items-center justify-between gap-3 text-[13px]">
                    <span>
                      {a.at && <span className="mr-1.5 tabular-nums text-ink-muted">{a.at}</span>}
                      {a.name}
                    </span>
                    <Checkbox
                      label={t.redAfter}
                      checked={!!marked(a)?.red}
                      onChange={(on) => toggleSport({ activity_id: a.activity_id, name: a.name, red: false }, on)}
                    />
                  </div>
                ))}
                <div className="flex items-end gap-2">
                  <div className="min-w-0 flex-1">
                    <Input label={t.otherSport} value={other} onChange={(e) => setOther(e.target.value)} />
                  </div>
                  <Button
                    size="sm"
                    disabled={!other.trim()}
                    onClick={() => {
                      set({ sport: [...sport, { name: other.trim(), red: false }] });
                      setOther("");
                    }}
                  >
                    {t.add}
                  </Button>
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <Scale label={t.sleep} value={draft.sleep} onChange={(v) => set({ sleep: v })} />
                <span className="text-[11.5px] text-ink-muted">
                  {d.context.sleep_h != null ? t.sleepMeasured(f.num(d.context.sleep_h, 1), d.context.sleep_score) : t.noSleep}
                </span>
              </div>
              <Scale label={t.stress} value={draft.stress} onChange={(v) => set({ stress: v })} />
              <Input
                label={t.weather}
                hint={t.weatherHint}
                value={draft.weather ?? ""}
                onChange={(e) => set({ weather: e.target.value || null })}
              />
              <YesNo label={t.heating} value={draft.heating} onChange={(v) => set({ heating: v })} />
              <label className="flex flex-col gap-1.5">
                <span className="text-[12.5px] font-medium">{t.note}</span>
                <textarea
                  rows={3}
                  maxLength={4000}
                  value={draft.note ?? ""}
                  onChange={(e) => set({ note: e.target.value || null })}
                  className="ds-input min-h-[4.5rem] py-2"
                />
              </label>
            </div>
          </Card>,
          <Card key="photo" title={t.photo}>
            <div className="flex flex-col gap-3">
              {entry?.photo_id && (
                // eslint-disable-next-line @next/next/no-img-element -- a private photo from the API, not a static asset
                <img src={`/api/skin/photos/${entry.photo_id}`} alt={t.photo} className="max-h-72 w-full rounded object-contain" />
              )}
              <input
                ref={camera}
                type="file"
                accept="image/jpeg,image/png"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) photo.mutate(file);
                  e.target.value = "";
                }}
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  icon={<CameraIcon width={14} height={14} />}
                  disabled={photo.isPending}
                  onClick={() => camera.current?.click()}
                >
                  {entry?.photo_id ? t.replacePhoto : t.addPhoto}
                </Button>
                {entry?.photo_id && (
                  <Button size="sm" variant="ghost" disabled={dropPhoto.isPending} onClick={() => dropPhoto.mutate()}>
                    {t.removePhoto}
                  </Button>
                )}
              </div>
              <p className="text-[11.5px] text-ink-muted">{t.photoNote}</p>
            </div>
          </Card>,
        ]}
      />

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate(draft)}>
          {save.isPending ? t.saving : t.save}
        </Button>
        {savedAt === d.day && <span className="text-[12.5px] text-ink-muted">{t.saved}</span>}
        {error && (
          <span className="text-[12.5px] text-[var(--text-loss)]">{error instanceof ApiError ? error.message : String(error)}</span>
        )}
        {entry && (
          <Button
            variant="ghost"
            className="ml-auto"
            disabled={remove.isPending}
            onClick={() => window.confirm(t.removeConfirm) && remove.mutate()}
          >
            {t.removeDay}
          </Button>
        )}
      </div>
    </div>
  );
}

export default function SkinPage() {
  const allowed = useSkinGate();
  const tt = useT();
  if (!allowed) return <p className="text-sm text-ink-muted">{tt.common.loading}</p>;
  return (
    <Suspense>
      <SkinDay />
    </Suspense>
  );
}
