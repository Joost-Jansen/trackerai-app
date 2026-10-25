"use client";

// Achieved: what you achieved over time, by year. Your own achievements (a challenge, a race, a record; recorded here
// or by Claude with add_achievement) and every finished plan with what it asked against what was done.

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, EmptyState, Input, Select, Tag } from "@/components/ds";
import { CalendarIcon } from "@trackerai/ui/icons";
import Markdown from "@/components/log/Markdown";
import { todayIso } from "@/components/plan/plan";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";
import type { Achievement, AchievementKind } from "@/lib/training";

const KINDS: AchievementKind[] = ["challenge", "race", "record", "milestone"];

function AddForm({ onDone }: { onDone: () => void }) {
  const t = useT();
  const a = t.achievements;
  const [title, setTitle] = useState("");
  const [day, setDay] = useState(todayIso());
  const [kind, setKind] = useState<AchievementKind>("challenge");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.post("/api/achievements", { title: title.trim(), day, kind, body: body.trim() || null }),
    onSuccess: onDone,
    onError: (e) => setError(errorText(e, t, t.common.saveFailed)),
  });
  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_160px_160px]"
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) return setError(a.titleRequired);
        setError(null);
        save.mutate();
      }}
    >
      <Input label={a.titleLabel} placeholder={a.titlePh} value={title} onChange={(e) => setTitle(e.target.value)} />
      <Input label={a.dayLabel} type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      <Select label={a.kindLabel} value={kind} onChange={(e) => setKind(e.target.value as AchievementKind)}>
        {KINDS.map((k) => (
          <option key={k} value={k}>
            {a.kinds[k]}
          </option>
        ))}
      </Select>
      <div className="sm:col-span-3">
        <label htmlFor="ach-body" className="ds-field__label mb-1.5 block">
          {a.bodyLabel}
        </label>
        <textarea
          id="ach-body"
          className="ds-input min-h-[72px]"
          placeholder={a.bodyPh}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:col-span-3">
        <Button size="sm" variant="primary" type="submit" disabled={save.isPending}>
          {a.save}
        </Button>
        <Button size="sm" variant="ghost" type="button" onClick={onDone}>
          {t.common.cancel}
        </Button>
        {error && <span className="text-[12.5px] text-loss">{error}</span>}
      </div>
    </form>
  );
}

function Item({ item, onRemove }: { item: Achievement; onRemove: () => void }) {
  const t = useT();
  const f = useFormat();
  const a = t.achievements;
  const m = item.summary;
  return (
    <li className="grid gap-x-4 border-t border-border py-3 first:border-t-0 sm:grid-cols-[110px_minmax(0,1fr)]">
      <span className="text-[12.5px] tabular-nums text-ink-muted">{f.day(item.day)}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[15px] font-semibold">{item.title}</span>
          <Tag tone={item.kind === "plan" ? "neutral" : "brand"}>{a.kinds[item.kind]}</Tag>
          {m?.complete && <Tag tone="gain">{t.plans.complete}</Tag>}
        </div>
        {m && (
          <p className="mt-0.5 text-[12.5px] tabular-nums text-ink-muted">
            {t.plans.sessions(m.done, m.done + m.missed)}
            {m.planned_km > 0 ? ` · ${t.plans.km(f.trim(m.done_km), f.trim(m.planned_km))}` : ""}
          </p>
        )}
        {item.body && <Markdown text={item.body} className="mt-1 max-w-[72ch] text-[13px]" />}
        <div className="mt-1 flex flex-wrap items-center gap-3 text-[12px] text-ink-muted">
          {item.source === "manual" && <span>{a.by(item.author)}</span>}
          {item.plan_id != null && (
            <Link href={`/plan/all/?id=${item.plan_id}`} className="font-semibold text-brand hover:underline">
              {a.openPlan}
            </Link>
          )}
          {item.source === "manual" && (
            <button type="button" className="hover:text-loss hover:underline" onClick={() => confirm(a.removeConfirm) && onRemove()}>
              {a.remove}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

export default function AchievementsPage() {
  const t = useT();
  const a = t.achievements;
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const q = useQuery({ queryKey: ["achievements"], queryFn: () => api.get<{ items: Achievement[] }>("/api/achievements") });
  const remove = useMutation({
    mutationFn: (id: number | string) => api.del(`/api/achievements/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["achievements"] }),
  });

  const add = adding ? (
    <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
      <h2 className="mb-3 text-[13.5px] font-semibold">{a.add}</h2>
      <AddForm
        onDone={() => {
          setAdding(false);
          qc.invalidateQueries({ queryKey: ["achievements"] });
        }}
      />
    </section>
  ) : (
    <div>
      <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
        {a.add}
      </Button>
    </div>
  );

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{errorText(q.error, t, a.loadFailed)}</p>;

  const items = q.data.items;
  const years = [...new Set(items.map((x) => x.day.slice(0, 4)))];
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-display text-[28px] font-light leading-tight">{a.title}</h1>
        <p className="mt-1 max-w-prose text-[13px] text-ink-muted">{a.intro}</p>
      </div>
      {add}
      {remove.isError && <p className="text-[12.5px] text-loss">{errorText(remove.error, t, t.common.saveFailed)}</p>}
      {!items.length ? (
        <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
          <EmptyState icon={<CalendarIcon width={22} height={22} />} title={a.emptyTitle} body={a.emptyBody} />
        </section>
      ) : (
        years.map((year) => (
          <section key={year} className="rounded border border-border bg-surface p-4 sm:p-[18px]">
            <h2 className="text-[13.5px] font-semibold tabular-nums">{year}</h2>
            <ul className="mt-2">
              {items
                .filter((x) => x.day.startsWith(year))
                .map((x) => (
                  <Item key={`${x.source}-${x.id}`} item={x} onRemove={() => remove.mutate(x.id)} />
                ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
