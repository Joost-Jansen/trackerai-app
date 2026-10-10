"use client";

// Rounds: every piece of Claude's work is a series of short requests. One request
// per round, so no request lasts long enough to be cut off by the proxy. Between
// the rounds you see what happened, and the queue fills while it works.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { tr, trx } from "@/lib/i18n";

/** What Claude said about one transaction in one round, and whether it was taken over. */
export type AiItem = { name: string; amount: number; category: string; confidence: number; applied: boolean; reason?: string | null };
export type CheckItem = { name: string; now: string; suggestion: string; confidence: number; count: number; reason?: string | null };
export type RuleItem = { pattern: string; category: string; count: number };

export type Round<T> = { count: number; done: boolean; items: T[]; error?: string | null; tally?: Record<string, number> };

export type RoundState<T> = {
  busy: boolean;
  /** Finished by itself: nothing left to do (not stopped, no error). */
  finished: boolean;
  completed: number;
  total: number;
  rounds: number;
  feed: T[];
  error: string | null;
  tally: Record<string, number>;
  start: (total: number) => void;
  stop: () => void;
  close: () => void;
};

export function useRounds<V, T>(url: string, read: (v: V) => Round<T>, onDone: () => void): RoundState<T> {
  const qc = useQueryClient();
  const empty = {
    busy: false, finished: false, completed: 0, total: 0, rounds: 0,
    feed: [] as T[], error: null as string | null, tally: {} as Record<string, number>,
  };
  const [s, setS] = useState(empty);
  const round = useMutation({
    mutationFn: () => api.post<V>(url),
    onSuccess: (v) => {
      const r = read(v);
      setS((o) => {
        const automatically = r.done || r.count === 0;
        const final = !o.busy || automatically || !!r.error;
        const tally = { ...o.tally };
        for (const [k, n] of Object.entries(r.tally ?? {})) tally[k] = (tally[k] ?? 0) + n;
        return {
          ...o, completed: o.completed + r.count, rounds: o.rounds + 1, feed: [...r.items, ...o.feed].slice(0, 12),
          error: r.error ?? null, tally, busy: !final, finished: automatically && !r.error,
        };
      });
      // In between the counters and the queue; the rest only when everything is done.
      qc.invalidateQueries({ queryKey: ["categories", "ai"] });
      qc.invalidateQueries({ queryKey: ["labelling"] });
    },
    onError: (e) => setS((o) => ({ ...o, busy: false, error: (e as ApiError).message || tr("Something went wrong.") })),
  });
  useEffect(() => {
    if (s.busy && !round.isPending) round.mutate();
  }, [s.busy, s.rounds, round.isPending]); // eslint-disable-line react-hooks/exhaustive-deps
  const previous = useRef(false);
  useEffect(() => {
    if (previous.current && !s.busy) onDone();
    previous.current = s.busy;
  }, [s.busy]); // eslint-disable-line react-hooks/exhaustive-deps
  return {
    ...s,
    start: (total) => setS({ ...empty, busy: true, total: Math.max(total, 1) }),
    stop: () => setS((o) => ({ ...o, busy: false })),
    close: () => setS(empty),
  };
}

/** What a series of rounds does: a bar, what just happened, and a summary when it is done. */
export function Progress<T>({ r, step, title, unit, rule, summary }: {
  r: RoundState<T>; step?: string; title: string; unit: string; rule: (item: T) => ReactNode; summary: ReactNode;
}) {
  if (!r.busy && !r.finished && !r.error && r.rounds === 0) return null;
  const pct = r.finished ? 100 : Math.min(100, Math.round((r.completed / Math.max(r.total, 1)) * 100));
  const header = r.busy ? title : r.error ? tr("Stopped by an error") : r.finished ? tr("Done") : tr("Stopped");
  return (
    <div className="flex flex-col gap-2 text-xs" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[12.5px] font-medium">
          {r.busy && <span aria-hidden className="inline-block h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--brand)" }} />}
          {step && <span className="text-ink-muted">{step} ·</span>} {header}
        </span>
        <span className="num text-ink-muted">{trx("{0} of {1} {2}", Math.min(r.completed, r.total), r.total, unit)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--rule)" }}>
        <div className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%`, background: r.error ? "var(--text-loss)" : "var(--brand)" }} />
      </div>
      {r.busy && r.feed.length === 0 && (
        <p className="text-ink-muted">{tr("The first round is running; in a few seconds you'll see here what Claude is doing.")}</p>
      )}
      {r.feed.length > 0 && (
        <ul className="flex max-h-40 flex-col gap-0.5 overflow-y-auto">
          {r.feed.map((item, i) => <li key={`${r.rounds}-${i}`} className="truncate">{rule(item)}</li>)}
        </ul>
      )}
      {!r.busy && !r.error && <p>{summary}</p>}
      {r.error && <p style={{ color: "var(--text-loss)" }}>{r.error}</p>}
    </div>
  );
}

const pct = (z: number) => `${Math.round(z * 100)}%`;

export function aiRule(i: AiItem): ReactNode {
  if (i.category === "Onbekend") return <span className="text-ink-muted">{trx("– {0}: doesn't know", i.name)}</span>;
  return (
    <span>
      <span aria-hidden style={{ color: i.applied ? "var(--text-gain)" : undefined }}>{i.applied ? "✓" : "?"}</span>{" "}
      {i.name} → <b>{i.category}</b>{" "}
      <span className="num text-ink-muted">· {pct(i.confidence)}{i.reason ? ` · ${i.reason}` : ""}{i.applied ? "" : tr(" · unsure, in the queue")}</span>
    </span>
  );
}

export function checkRule(i: CheckItem): ReactNode {
  return (
    <span>
      <span aria-hidden>≠</span> {i.name} <span className="num text-ink-muted">({i.count}×)</span>: {i.now} → <b>{i.suggestion}</b>{" "}
      <span className="num text-ink-muted">· {pct(i.confidence)}{i.reason ? ` · ${i.reason}` : ""}</span>
    </span>
  );
}

export function ruleRule(i: RuleItem): ReactNode {
  return (
    <span>
      <span aria-hidden>+</span> <code>{i.pattern}</code> → <b>{i.category}</b> <span className="num text-ink-muted">· {i.count}×</span>
    </span>
  );
}
