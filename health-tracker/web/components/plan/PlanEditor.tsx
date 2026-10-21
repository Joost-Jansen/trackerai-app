"use client";

// Plan editor (T24): create a new plan or change the active one with a form instead of pasting a table.
// Sessions grouped per week and always by date; per session date, sport, kind, km or minutes,
// target zone, one of your own routes and a description. Saved via POST /api/plans or PATCH + PUT .../sessions.

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Markdown from "@/components/log/Markdown";
import { Button, IconButton } from "@/components/ds";
import { CloseIcon } from "@trackerai/ui/icons";
import { api } from "@/lib/api";
import { errorText, routeName, useFormat, useT, type Messages } from "@/lib/i18n";
import type { Plan, PlanSession, RouteSummary } from "@/lib/training";
import { PLAN_SPORTS, ZONE_OPTIONS, addDays, fmtWeekRange, isValidIso, joinRace, sportColour, splitRace, todayIso, weekOf } from "./plan";
import { SportGlyph } from "./SportIcon";

type Row = {
  key: number;
  date: string;
  sport: string;
  kind: string;
  km: string;
  min: string;
  zone: string;
  route_id: string;
  description: string;
};
type Meta = { title: string; goal: string; raceName: string; raceDate: string; notes: string };
type Errors = { meta: Partial<Record<keyof Meta, string>>; rows: Record<number, Partial<Record<"date" | "km" | "min", string>>> };

const parseNum = (v: string) => (v.trim() === "" ? null : Number(v.trim().replace(",", ".")));
const hasAmount = (sport: string) => sport !== "rest";
const hasRoute = (sport: string) => sport === "run" || sport === "ride";

function validate(meta: Meta, rows: Row[], t: Messages): Errors {
  const m = t.plan.editor;
  const e: Errors = { meta: {}, rows: {} };
  if (!meta.title.trim()) e.meta.title = m.titleRequired;
  if (meta.raceDate && !isValidIso(meta.raceDate)) e.meta.raceDate = m.invalidDate;
  for (const r of rows) {
    const re: Errors["rows"][number] = {};
    if (!isValidIso(r.date)) re.date = m.pickDate;
    if (hasAmount(r.sport)) {
      const km = parseNum(r.km);
      const min = parseNum(r.min);
      if (km != null && (Number.isNaN(km) || km < 0 || km > 400)) re.km = m.kmRange;
      if (min != null && (Number.isNaN(min) || min < 0 || min > 1440 || !Number.isInteger(min))) re.min = m.wholeMinutes;
    }
    if (Object.keys(re).length) e.rows[r.key] = re;
  }
  return e;
}

const errorCount = (e: Errors) => Object.keys(e.meta).length + Object.keys(e.rows).length;

function toPayload(r: Row): Omit<PlanSession, "status"> {
  const rest = r.sport === "rest";
  return {
    date: r.date,
    sport: r.sport,
    kind: r.kind.trim() || null,
    distance_km: rest ? null : parseNum(r.km),
    duration_min: rest ? null : parseNum(r.min),
    target_zone: rest ? null : r.zone || null,
    description: r.description.trim() || null,
    route_id: hasRoute(r.sport) ? r.route_id || null : null,
  };
}

const byDate = (a: Row, b: Row) => a.date.localeCompare(b.date) || a.key - b.key;

function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-[11.5px] font-medium text-[var(--text-secondary)] sm:sr-only">
      {children}
    </label>
  );
}

function RowEditor({
  row,
  errors,
  routes,
  onChange,
  onDuplicate,
  onDelete,
}: {
  row: Row;
  errors?: Errors["rows"][number];
  routes: RouteSummary[];
  onChange: (patch: Partial<Row>) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  const fmt = useFormat();
  const m = t.plan.editor;
  const id = (f: string) => `r${row.key}-${f}`;
  const cell = "ds-input h-9 px-2.5 text-[13px]";
  const sel = "ds-select h-9 pl-2.5 text-[13px]";
  const rest = row.sport === "rest";
  const own = routes.filter((r) => r.sport === row.sport);
  return (
    <li
      className="grid grid-cols-6 gap-x-2 gap-y-2.5 rounded-md border border-border bg-surface p-3 pl-3.5 sm:grid-cols-[138px_132px_minmax(100px,1fr)_72px_72px_96px_minmax(130px,1.2fr)_64px] sm:gap-y-1.5 sm:border-0 sm:border-t sm:bg-transparent sm:p-0 sm:py-2.5 sm:pl-3"
      style={{ boxShadow: `inset 3px 0 0 ${sportColour(row.sport)}` }}
    >
      <div className="col-span-3 sm:col-span-1">
        <Label htmlFor={id("date")}>{m.date}</Label>
        <input
          id={id("date")}
          type="date"
          className={cell}
          value={row.date}
          aria-invalid={!!errors?.date || undefined}
          onChange={(e) => onChange({ date: e.target.value })}
        />
        {errors?.date && <span className="mt-0.5 block text-[11px] text-loss">{errors.date}</span>}
      </div>
      <div className="col-span-3 sm:col-span-1">
        <Label htmlFor={id("sport")}>{m.sport}</Label>
        <select
          id={id("sport")}
          className={sel}
          value={row.sport}
          onChange={(e) => onChange({ sport: e.target.value, ...(e.target.value === "rest" ? { kind: row.kind || t.plan.restKind } : {}) })}
        >
          {PLAN_SPORTS.map((s) => (
            <option key={s} value={s}>
              {t.sport(s)}
            </option>
          ))}
          {!PLAN_SPORTS.includes(row.sport as (typeof PLAN_SPORTS)[number]) && <option value={row.sport}>{t.sport(row.sport)}</option>}
        </select>
      </div>
      <div className="col-span-2 sm:col-span-1">
        <Label htmlFor={id("kind")}>{m.kind}</Label>
        <input
          id={id("kind")}
          className={cell}
          list={`kinds-${row.sport}`}
          placeholder={rest ? t.plan.restKind : m.kindPh}
          value={row.kind}
          onChange={(e) => onChange({ kind: e.target.value })}
        />
      </div>
      <div className="col-span-2 sm:col-span-1">
        <Label htmlFor={id("km")}>{m.km}</Label>
        <input
          id={id("km")}
          inputMode="decimal"
          className={`${cell} tabular-nums`}
          placeholder="km"
          disabled={rest}
          value={rest ? "" : row.km}
          aria-invalid={!!errors?.km || undefined}
          onChange={(e) => onChange({ km: e.target.value })}
        />
        {errors?.km && <span className="mt-0.5 block text-[11px] text-loss">{errors.km}</span>}
      </div>
      <div className="col-span-2 sm:col-span-1">
        <Label htmlFor={id("min")}>{m.minutes}</Label>
        <input
          id={id("min")}
          inputMode="numeric"
          className={`${cell} tabular-nums`}
          placeholder="min"
          disabled={rest}
          value={rest ? "" : row.min}
          aria-invalid={!!errors?.min || undefined}
          onChange={(e) => onChange({ min: e.target.value })}
        />
        {errors?.min && <span className="mt-0.5 block text-[11px] text-loss">{errors.min}</span>}
      </div>
      <div className={`${rest ? "hidden sm:block" : hasRoute(row.sport) ? "col-span-2" : "col-span-6"} sm:col-span-1`}>
        <Label htmlFor={id("zone")}>{m.zone}</Label>
        <select
          id={id("zone")}
          className={sel}
          disabled={rest}
          value={rest ? "" : row.zone}
          onChange={(e) => onChange({ zone: e.target.value })}
        >
          <option value="">{m.zone}</option>
          {ZONE_OPTIONS.map((z) => (
            <option key={z} value={z}>
              {z.replace("-Z", "–")}
            </option>
          ))}
          {row.zone && !ZONE_OPTIONS.includes(row.zone) && <option value={row.zone}>{row.zone}</option>}
        </select>
      </div>
      <div className={`${hasRoute(row.sport) ? "col-span-4" : "hidden sm:block"} sm:col-span-1`}>
        <Label htmlFor={id("route")}>{m.route}</Label>
        <select
          id={id("route")}
          className={sel}
          disabled={!hasRoute(row.sport) || own.length === 0}
          value={hasRoute(row.sport) ? row.route_id : ""}
          onChange={(e) => onChange({ route_id: e.target.value })}
        >
          <option value="">{hasRoute(row.sport) ? (own.length ? m.autoRoute : m.noRoutes) : m.noRoute}</option>
          {own.map((r) => (
            <option key={r.id} value={r.id}>
              {routeName(r.name, r.id, t, fmt)} · {fmt.trim(r.distance_km)} km
            </option>
          ))}
          {row.route_id && hasRoute(row.sport) && !own.some((r) => r.id === row.route_id) && (
            <option value={row.route_id}>{row.route_id}</option>
          )}
        </select>
      </div>
      <div className="order-last col-span-6 flex items-center justify-end gap-0.5 sm:order-none sm:col-span-1 sm:row-span-2 sm:flex-col sm:items-end sm:justify-start">
        <IconButton
          size="sm"
          label={m.duplicate}
          onClick={onDuplicate}
          icon={
            <svg
              viewBox="0 0 24 24"
              width="15"
              height="15"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <rect x="8" y="8" width="12" height="12" rx="2" />
              <path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2" />
            </svg>
          }
        />
        <IconButton size="sm" label={m.remove} onClick={onDelete} icon={<CloseIcon width={15} height={15} />} />
      </div>
      <div className="col-span-6 sm:col-span-7">
        <Label htmlFor={id("desc")}>{m.description}</Label>
        <input
          id={id("desc")}
          className={`${cell} w-full bg-[var(--surface-sunken)]`}
          placeholder={m.descriptionPh}
          value={row.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>
    </li>
  );
}

export default function PlanEditor({
  plan,
  onSaved,
  onCancel,
  onPaste,
}: {
  /** Empty = new plan. */
  plan?: Plan | null;
  onSaved: () => void;
  onCancel?: () => void;
  /** To "paste from table" (only for a new plan). */
  onPaste?: () => void;
}) {
  const t = useT();
  const f = useFormat();
  const m = t.plan.editor;
  const showNum = f.input;
  const next = useRef(1);
  const mk = (s: Partial<PlanSession>): Row => ({
    key: next.current++,
    date: s.date ?? todayIso(),
    sport: s.sport ?? "run",
    kind: s.kind ?? "",
    km: showNum(s.distance_km),
    min: showNum(s.duration_min),
    zone: s.target_zone ?? "",
    route_id: s.route_id ?? "",
    description: s.description ?? "",
  });
  const race = splitRace(plan?.race);
  const [meta, setMeta] = useState<Meta>(() => ({
    title: plan?.title ?? "",
    goal: plan?.goal ?? "",
    raceName: race.name,
    raceDate: race.date ?? "",
    notes: plan?.notes ?? "",
  }));
  const [rows, setRows] = useState<Row[]>(() => (plan?.sessions ?? []).map(mk));
  const initial = useRef(JSON.stringify({ meta, rows: rows.map(({ key, ...r }) => r) }));
  const [preview, setPreview] = useState(false);
  const [tried, setTried] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useQuery({ queryKey: ["routes", "run"], queryFn: () => api.get<RouteSummary[]>("/api/routes?sport=run") });
  const ride = useQuery({ queryKey: ["routes", "ride"], queryFn: () => api.get<RouteSummary[]>("/api/routes?sport=ride") });
  const routes = useMemo(() => [...(run.data ?? []), ...(ride.data ?? [])], [run.data, ride.data]);

  const dirty = JSON.stringify({ meta, rows: rows.map(({ key, ...r }) => r) }) !== initial.current;
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const errors = validate(meta, rows, t);
  // Check numbers right away, a missing title or date only after the first save attempt.
  const shown: Errors = tried
    ? errors
    : { meta: {}, rows: Object.fromEntries(Object.entries(errors.rows).map(([k, v]) => [k, { km: v.km, min: v.min }])) };

  const sorted = [...rows].sort(byDate);
  const weeks = useMemo(() => {
    const m = new Map<string, Row[]>();
    for (const r of sorted) {
      const w = isValidIso(r.date) ? weekOf(r.date) : "";
      m.set(w, [...(m.get(w) ?? []), r]);
    }
    return [...m.entries()];
  }, [sorted]);

  const patch = (key: number, p: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  const remove = (key: number) => setRows((rs) => rs.filter((r) => r.key !== key));
  const duplicate = (key: number) =>
    setRows((rs) => {
      const i = rs.findIndex((r) => r.key === key);
      return [...rs.slice(0, i + 1), { ...rs[i], key: next.current++ }, ...rs.slice(i + 1)];
    });
  const addInWeek = (monday: string) => {
    const taken = new Set(rows.map((r) => r.date));
    const free = Array.from({ length: 7 }, (_, i) => addDays(monday, i)).find(
      (d) => !taken.has(d) && d >= (monday <= todayIso() ? todayIso() : monday),
    );
    setRows((rs) => [...rs, mk({ date: free ?? monday, sport: "run" })]);
  };
  const lastDate = sorted.filter((r) => isValidIso(r.date)).at(-1)?.date;
  const addSession = () => setRows((rs) => [...rs, mk({ date: lastDate ? addDays(lastDate, 1) : todayIso(), sport: "run" })]);
  const addWeek = () => {
    if (!lastDate) {
      const monday = addDays(weekOf(todayIso()), 7);
      setRows((rs) => [...rs, mk({ date: monday, sport: "run" })]);
      return;
    }
    const lastWeek = weekOf(lastDate);
    const copy = sorted.filter((r) => isValidIso(r.date) && weekOf(r.date) === lastWeek);
    setRows((rs) => [...rs, ...copy.map((r) => ({ ...r, key: next.current++, date: addDays(r.date, 7) }))]);
  };

  async function save() {
    setTried(true);
    setError(null);
    if (errorCount(errors)) return;
    const body = {
      title: meta.title.trim(),
      goal: meta.goal.trim(),
      race: joinRace(meta.raceName, meta.raceDate),
      notes: meta.notes.trim(),
    };
    const sessions = sorted.map(toPayload);
    setSaving(true);
    try {
      if (plan) {
        await api.patch(`/api/plans/${plan.id}`, body);
        await api.put(`/api/plans/${plan.id}/sessions`, sessions);
      } else {
        await api.post("/api/plans", { ...body, goal: body.goal || null, race: body.race || null, notes: body.notes || null, sessions });
      }
      initial.current = JSON.stringify({ meta, rows: rows.map(({ key, ...r }) => r) });
      onSaved();
    } catch (e) {
      setError(errorText(e, t, t.common.saveFailed));
    } finally {
      setSaving(false);
    }
  }

  const cancel = () => {
    if (!dirty || confirm(m.discard)) onCancel?.();
  };

  const totals = useMemo(() => {
    const km: Record<string, number> = {};
    for (const r of rows) if (r.sport !== "rest") km[r.sport] = (km[r.sport] ?? 0) + (parseNum(r.km) || 0);
    return Object.entries(km).filter(([, v]) => v > 0);
  }, [rows]);
  const nErrors = errorCount(errors);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-muted">{plan ? m.editing : m.newPlan}</span>
          <h1 className="mt-1 font-display text-[28px] font-light leading-tight">{meta.title.trim() || (plan ? plan.title : m.newPlan)}</h1>
          {!plan && <p className="mt-1 text-[12.5px] text-ink-muted">{m.becomesActive}</p>}
        </div>
        {onPaste && (
          <Button size="sm" variant="ghost" onClick={onPaste}>
            {t.plan.paste}
          </Button>
        )}
      </div>

      <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
        <h2 className="mb-3.5 text-[13.5px] font-semibold">{m.about}</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2">
            <label htmlFor="pe-title" className="ds-field__label mb-1.5 block">
              {m.title}
            </label>
            <input
              id="pe-title"
              className="ds-input"
              placeholder={m.titlePh}
              value={meta.title}
              aria-invalid={!!shown.meta.title || undefined}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })}
            />
            {shown.meta.title && <span className="mt-1 block text-[12px] text-loss">{shown.meta.title}</span>}
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="pe-goal" className="ds-field__label mb-1.5 block">
              {m.goal}
            </label>
            <input
              id="pe-goal"
              className="ds-input"
              placeholder={m.goalPh}
              value={meta.goal}
              onChange={(e) => setMeta({ ...meta, goal: e.target.value })}
            />
          </div>
          <div className="sm:col-span-1 lg:col-span-2">
            <label htmlFor="pe-race" className="ds-field__label mb-1.5 block">
              {m.race}
            </label>
            <input
              id="pe-race"
              className="ds-input"
              placeholder={m.racePh}
              value={meta.raceName}
              onChange={(e) => setMeta({ ...meta, raceName: e.target.value })}
            />
          </div>
          <div className="sm:col-span-1 lg:col-span-2">
            <label htmlFor="pe-race-date" className="ds-field__label mb-1.5 block">
              {m.raceDate}
            </label>
            <input
              id="pe-race-date"
              type="date"
              className="ds-input"
              value={meta.raceDate}
              aria-invalid={!!shown.meta.raceDate || undefined}
              onChange={(e) => setMeta({ ...meta, raceDate: e.target.value })}
            />
            {shown.meta.raceDate && <span className="mt-1 block text-[12px] text-loss">{shown.meta.raceDate}</span>}
          </div>
          <div className="sm:col-span-2 lg:col-span-4">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label htmlFor="pe-notes" className="ds-field__label">
                {m.notes}
              </label>
              <span className="flex gap-1" role="group" aria-label={m.notes}>
                {[false, true].map((p) => (
                  <button
                    key={String(p)}
                    type="button"
                    aria-pressed={preview === p}
                    onClick={() => setPreview(p)}
                    className={`h-7 rounded-md px-2.5 text-[12px] ${preview === p ? "bg-[var(--surface-active)] font-semibold" : "text-ink-muted hover:bg-[var(--surface-hover)]"}`}
                  >
                    {p ? m.preview : m.write}
                  </button>
                ))}
              </span>
            </div>
            {preview ? (
              <div className="min-h-[120px] rounded-md bg-[var(--surface-sunken)] p-3">
                {meta.notes.trim() ? (
                  <Markdown text={meta.notes} className="text-[13px]" />
                ) : (
                  <p className="text-[13px] text-ink-muted">{m.noNotes}</p>
                )}
              </div>
            ) : (
              <textarea
                id="pe-notes"
                className="ds-input h-32 py-2 leading-relaxed"
                placeholder={m.notesPh}
                value={meta.notes}
                onChange={(e) => setMeta({ ...meta, notes: e.target.value })}
              />
            )}
          </div>
        </div>
      </section>

      <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[13.5px] font-semibold">{m.sessions}</h2>
          <span className="text-[12px] tabular-nums text-ink-muted">
            {m.sessionCount(rows.length)}
            {totals.map(([s, km]) => ` · ${t.sport(s).toLowerCase()} ${f.trim(km)} km`).join("")}
          </span>
        </div>

        {rows.length === 0 && (
          <div className="rounded-md border border-dashed border-[var(--border-strong)] px-4 py-8 text-center">
            <p className="text-[13.5px] font-medium">{m.noSessions}</p>
            <p className="mt-1 text-[12.5px] text-ink-muted">{m.noSessionsBody}</p>
          </div>
        )}

        {rows.length > 0 && (
          <div className="hidden grid-cols-[138px_132px_minmax(100px,1fr)_72px_72px_96px_minmax(130px,1.2fr)_64px] gap-x-2 pb-1.5 pl-3 text-[11.5px] text-ink-muted sm:grid">
            <span>{m.date}</span>
            <span>{m.sport}</span>
            <span>{m.kind}</span>
            <span>{m.km}</span>
            <span>{m.minutes}</span>
            <span>{m.zone}</span>
            <span>{m.route}</span>
            <span />
          </div>
        )}

        <div className="flex flex-col gap-5">
          {weeks.map(([monday, list]) => (
            <div key={monday || "zonder-datum"}>
              <div className="mb-2 flex items-center justify-between gap-2 rounded-md bg-[var(--surface-sunken)] px-3 py-1.5">
                <span className="text-[12.5px] font-semibold">
                  {monday ? m.weekOf(fmtWeekRange(monday, f)) : m.noDate}
                  <span className="ml-2 font-normal tabular-nums text-ink-muted">
                    {f.trim(list.reduce((s, r) => s + (r.sport === "rest" ? 0 : parseNum(r.km) || 0), 0))} km
                  </span>
                </span>
                {monday && (
                  <Button size="sm" variant="ghost" onClick={() => addInWeek(monday)}>
                    {m.addInWeek}
                  </Button>
                )}
              </div>
              <ul className="flex flex-col gap-2 sm:gap-0">
                {list.map((r) => (
                  <RowEditor
                    key={r.key}
                    row={r}
                    errors={shown.rows[r.key]}
                    routes={routes}
                    onChange={(p) => patch(r.key, p)}
                    onDuplicate={() => duplicate(r.key)}
                    onDelete={() => remove(r.key)}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={addSession} icon={<SportGlyph sport="run" width={15} height={15} />}>
            {m.addSession}
          </Button>
          <Button size="sm" variant="ghost" onClick={addWeek}>
            {lastDate ? m.addWeekCopy : m.addWeek}
          </Button>
        </div>
        {Object.entries(t.plan.kinds).map(([sport, kinds]) => (
          <datalist key={sport} id={`kinds-${sport}`}>
            {kinds.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        ))}
      </section>

      <div className="sticky bottom-0 z-20 -mx-4 flex flex-wrap items-center gap-2 border-t border-border bg-[var(--surface-page)] px-4 py-3 sm:mx-0 sm:rounded sm:border sm:bg-surface">
        <span className="min-w-0 flex-1 text-[12.5px]">
          {error ? (
            <span className="text-loss">{error}</span>
          ) : tried && nErrors ? (
            <span className="text-loss">{m.errors(nErrors)}</span>
          ) : (
            <span className="text-ink-muted">{dirty ? m.unsaved : m.noChanges}</span>
          )}
        </span>
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={cancel}>
            {t.common.cancel}
          </Button>
        )}
        <Button size="sm" variant="primary" onClick={save} disabled={saving || (!!plan && !dirty)}>
          {saving ? t.common.saving : plan ? t.common.save : m.savePlan}
        </Button>
      </div>
    </div>
  );
}
