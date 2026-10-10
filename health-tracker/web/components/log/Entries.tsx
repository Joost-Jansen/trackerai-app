"use client";

// Log or analyses: newest first, per month, with search and a form for a new entry.
// Who wrote it (the user or an agent) is shown with it.

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@/components/ds";
import Markdown from "@/components/log/Markdown";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";

export type Entry = { id: number; kind: "log" | "analysis"; day: string; title: string; body: string; author: string; created_at: string };

function NewEntry({ kind, onDone }: { kind: Entry["kind"]; onDone: () => void }) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [day, setDay] = useState(new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Amsterdam" }));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Card title={kind === "log" ? t.log.newLog : t.log.newAnalysis}>
      <form
        className="flex flex-col gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api.post("/api/entries", { kind, title, body, day });
            onDone();
          } catch (err) {
            setError(errorText(err, t, t.common.saveFailed));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="flex flex-wrap gap-2">
          <input type="date" className="ds-input w-[150px]" value={day} onChange={(e) => setDay(e.target.value)} aria-label={t.log.date} />
          <input className="ds-input min-w-0 flex-1" placeholder={t.log.subject} value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <textarea className="ds-input h-40 py-2 text-[13px]" placeholder={t.log.bodyPh} value={body} onChange={(e) => setBody(e.target.value)} required />
        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={busy || !title.trim() || !body.trim()}>{t.common.save}</Button>
          <Button size="sm" variant="ghost" onClick={onDone}>{t.common.cancel}</Button>
          {error && <span className="text-[12.5px] text-loss">{error}</span>}
        </div>
      </form>
    </Card>
  );
}

export default function Entries({ kind }: { kind: Entry["kind"] }) {
  const t = useT();
  const f = useFormat();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const q = useQuery({ queryKey: ["entries", kind], queryFn: () => api.get<Entry[]>(`/api/entries?kind=${kind}&limit=500`) });

  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const items = (q.data ?? []).filter((e) => !needle || e.title.toLowerCase().includes(needle) || e.body.toLowerCase().includes(needle) || e.day.includes(needle));
    const out: { month: string; items: Entry[] }[] = [];
    for (const e of items) {
      const m = e.day.slice(0, 7);
      if (out[out.length - 1]?.month !== m) out.push({ month: m, items: [] });
      out[out.length - 1].items.push(e);
    }
    return out;
  }, [q.data, search]);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.log.loadFailed(kind)}</p>;
  const first = q.data[0]?.id;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <input className="ds-input h-9 min-w-0 flex-1 text-[13px] sm:max-w-[280px]" placeholder={t.log.search} value={search} onChange={(e) => setSearch(e.target.value)} />
        <span className="text-[12px] text-ink-muted tabular-nums">{t.log.count(q.data.length, kind)}</span>
        <span className="flex-1" />
        {!adding && <Button size="sm" onClick={() => setAdding(true)}>{t.log.add(kind)}</Button>}
      </div>
      {adding && <NewEntry kind={kind} onDone={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["entries", kind] }); }} />}
      {q.data.length === 0 && (
        <p className="text-[13px] text-ink-muted">
          {t.log.empty(kind)}
        </p>
      )}
      {groups.map((g) => (
        <section key={g.month} className="flex flex-col gap-3">
          <h2 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-ink-muted">{f.month(g.month)}</h2>
          {g.items.map((e) => {
            const expanded = open[e.id] ?? (e.id === first || !!search);
            return (
              <Card key={e.id}>
                <button type="button" className="flex w-full flex-wrap items-baseline justify-between gap-x-3 text-left" onClick={() => setOpen({ ...open, [e.id]: !expanded })} aria-expanded={expanded}>
                  <span className="text-[14px] font-semibold">{e.title}</span>
                  <span className="text-[12px] text-ink-muted">{f.weekdayDayYear(e.day)} · {e.author}</span>
                </button>
                {expanded ? <Markdown text={e.body} className="mt-3" /> : <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-muted">{e.body.replace(/[#*|`>-]/g, " ").slice(0, 240)}</p>}
              </Card>
            );
          })}
        </section>
      ))}
    </div>
  );
}
