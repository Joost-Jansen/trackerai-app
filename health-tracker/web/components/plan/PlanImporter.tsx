"use client";

// "Paste from table": a plan from a markdown table or CSV (as an agent or a spreadsheet makes it). The
// second route next to the editor; check first, then save as the active plan.

import { useState } from "react";
import { Button, Tag } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useFormat, useT, type Messages } from "@/lib/i18n";
import type { Plan, PlanSession } from "@/lib/training";
import { capitalise } from "./plan";
import { SportBadge } from "./SportIcon";
import ZoneChip from "./ZoneChip";

type Warning = { code: string; params: Record<string, unknown> };
type ImportResponse = { sessions: PlanSession[]; warnings: string[]; warning_codes?: Warning[]; saved: boolean; plan?: Plan };

/** A coded warning (api/plans.py WARNINGS) in the user's language; the Dutch text when the code is unknown. */
function warningText(t: Messages, w: Warning | undefined, fallback: string): string {
  const m = w && (t.plan.importer.warnings as Record<string, string | ((p: never) => string)>)[w.code];
  if (typeof m === "string") return m;
  if (typeof m === "function") return (m as (p: Record<string, unknown>) => string)(w!.params);
  return fallback;
}

export default function PlanImporter({ onDone, onCancel, onEditor }: { onDone: () => void; onCancel?: () => void; onEditor?: () => void }) {
  const t = useT();
  const f = useFormat();
  const m = t.plan.importer;
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [race, setRace] = useState("");
  const [preview, setPreview] = useState<ImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(save: boolean) {
    setError(null);
    try {
      // Without a title the API names the plan in Dutch; name it here in the user's language.
      const first = preview?.sessions[0]?.date;
      const name = title || (save && first ? m.defaultTitle(f.day(first)) : undefined);
      const res = await api.post<ImportResponse>("/api/plans/import", { text, title: name, goal: goal || undefined, race: race || undefined, preview: !save });
      setPreview(res);
      if (save && res.saved) onDone();
    } catch (e) {
      setError(errorText(e, t, m.failed));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-muted">{m.eyebrow}</span>
          <h1 className="mt-1 font-display text-[28px] font-light leading-tight">{m.title}</h1>
          <p className="mt-1 max-w-prose text-[12.5px] text-ink-muted">
            {m.intro}
          </p>
        </div>
        <div className="flex gap-2">
          {onEditor && <Button size="sm" onClick={onEditor}>{m.manual}</Button>}
          {onCancel && <Button size="sm" variant="ghost" onClick={onCancel}>{t.common.cancel}</Button>}
        </div>
      </div>
      <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
        <div className="grid gap-3 sm:grid-cols-3">
          <input className="ds-input" placeholder={m.titlePh} aria-label={m.titleLabel} value={title} onChange={(e) => setTitle(e.target.value)} />
          <input className="ds-input" placeholder={m.goalPh} aria-label={m.goalLabel} value={goal} onChange={(e) => setGoal(e.target.value)} />
          <input className="ds-input" placeholder={m.racePh} aria-label={m.raceLabel} value={race} onChange={(e) => setRace(e.target.value)} />
        </div>
        <textarea className="ds-input mt-3 h-44 w-full py-2 font-mono text-[12px]" aria-label={m.table} placeholder={m.example} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="ds-btn ds-btn--secondary ds-btn--sm cursor-pointer">
            {m.file}
            <input type="file" accept=".csv,.md,.txt,.tsv" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setText(await f.text()); setPreview(null); } }} />
          </label>
          <Button size="sm" variant="ghost" onClick={() => { setText(m.example); setPreview(null); }}>{m.fillExample}</Button>
          <span className="flex-1" />
          <Button size="sm" onClick={() => run(false)} disabled={!text.trim()}>{m.check}</Button>
          <Button size="sm" variant="primary" onClick={() => run(true)} disabled={!preview || preview.sessions.length === 0}>{m.saveActive}</Button>
        </div>
        {error && <p className="mt-3 text-[12.5px] text-loss">{error}</p>}
        {preview && (
          <div className="mt-4 border-t border-border pt-3">
            {preview.warnings.map((w, i) => <p key={w} className="text-[12.5px] text-loss">{warningText(t, preview.warning_codes?.[i], w)}</p>)}
            <p className="mb-2 text-[12.5px] text-ink-muted">{m.found(preview.sessions.length)}</p>
            <ul className="flex flex-col">
              {preview.sessions.map((s, i) => (
                <li key={i} className="flex items-center gap-3 border-t border-[var(--border-subtle)] py-2 text-[13px] first:border-t-0">
                  <span className="w-[72px] flex-none text-[12px] text-ink-muted">{f.weekdayDay(s.date)}</span>
                  <SportBadge sport={s.sport} size={24} />
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{s.kind ? capitalise(s.kind) : t.sport(s.sport)}</span>
                    {s.distance_km ? <span className="tabular-nums"> · {f.trim(s.distance_km)} km</span> : s.duration_min ? <span className="tabular-nums"> · {s.duration_min} min</span> : null}
                    {s.description && <span className="block truncate text-[12px] text-ink-muted">{s.description}</span>}
                  </span>
                  <ZoneChip zone={s.target_zone} />
                  {s.route_id && <Tag>{s.route_id}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
