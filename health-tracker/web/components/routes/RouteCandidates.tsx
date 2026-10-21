"use client";

// "Check your routes": pairs that are probably the same route (different start, extra loop, partly a
// different road) but not certain enough to merge them ourselves. Per pair both tracks on one map in two colours
// and two buttons. Collapsed with a count, so it does not push itself forward. Nothing to ask: nothing to see.

import { useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Badge, Button } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, routeName, useFormat, useT, type Format, type Messages } from "@/lib/i18n";
import type { RouteCandidate, RouteCandidateResult, RouteCandidateSide, RouteSport } from "@/lib/training";

const RoutesMap = dynamic(() => import("@/components/map/RoutesMap"), { ssr: false });

// same order as RoutesMap colours: first line --chart-1, second --chart-4
const COLOURS = ["var(--chart-1)", "var(--chart-4)"];
const SHOWN = 3;

function label(s: RouteCandidateSide, done: string, t: Messages, f: Format): { title: string; meta: string } {
  const c = t.routes.candidates;
  if (s.kind === "activity")
    return { title: s.name || c.single(f.day(s.date)), meta: c.metaSingle(f.km(s.distance_km), done, f.day(s.date)) };
  return {
    title: routeName(s.name, s.id, t, f),
    meta: c.meta(f.km(s.distance_km), s.runs ?? 0, done, s.last_run ? f.day(s.last_run) : null),
  };
}

function Pair({ c, done, onAnswer, busy }: { c: RouteCandidate; done: string; onAnswer: (same: boolean) => void; busy: boolean }) {
  const t = useT();
  const f = useFormat();
  const sides = [c.a, c.b];
  return (
    <li className="grid gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0 md:grid-cols-[1.1fr_1fr]">
      <RoutesMap height={220} lines={sides.map((s) => ({ id: `${s.kind}:${s.id}`, label: label(s, done, t, f).title, points: s.track }))} />
      <div className="flex min-w-0 flex-col gap-2 text-[12.5px]">
        {sides.map((s, i) => {
          const l = label(s, done, t, f);
          return (
            <div key={s.id} className="flex min-w-0 items-start gap-2">
              <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: COLOURS[i] }} aria-hidden />
              <div className="min-w-0">
                <div className="truncate font-medium">{l.title}</div>
                <div className="tabular-nums text-ink-muted">{l.meta}</div>
              </div>
            </div>
          );
        })}
        <p className="text-ink-muted">{(c.reason_code && t.texts.routes.reason[c.reason_code]) || c.reason}</p>
        <div className="mt-auto flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAnswer(true)}>
            {t.routes.candidates.yes}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAnswer(false)}>
            {t.routes.candidates.no}
          </Button>
        </div>
      </div>
    </li>
  );
}

export default function RouteCandidates({ sport, candidates, done }: { sport: RouteSport; candidates: RouteCandidate[]; done: string }) {
  const t = useT();
  const T = t.texts;
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const answer = useMutation({
    mutationFn: (v: { a: string; b: string; same: boolean }) => api.post<RouteCandidateResult>("/api/routes/candidates", v),
    onSuccess: (res) => {
      setNote(res.applied_on_next_sync ? T.routes.nextSync : null);
      qc.invalidateQueries({ queryKey: ["route-candidates"] });
      qc.invalidateQueries({ queryKey: ["routes"] });
      qc.invalidateQueries({ queryKey: ["route"] });
    },
    onError: (e) => setNote(errorText(e, t, t.common.saveFailed)),
  });
  if (candidates.length === 0 && !note) return null;
  const shown = all ? candidates : candidates.slice(0, SHOWN);

  return (
    <Card
      title={t.routes.candidates.title}
      action={
        candidates.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
            <Badge quiet>{candidates.length}</Badge>
            <span className="ml-1.5">{open ? t.routes.candidates.collapse : t.routes.candidates.show}</span>
          </Button>
        )
      }
    >
      {note && (
        <p className="mb-2 text-[12.5px] text-ink-muted" role="status">
          {note}
        </p>
      )}
      {candidates.length > 0 && !open && <p className="text-[12.5px] text-ink-muted">{T.routes.pending(candidates.length, sport)}</p>}
      {open && candidates.length > 0 && (
        <>
          <p className="mb-3 text-[12.5px] text-ink-muted">{T.routes.reviewIntro}</p>
          <ul className="flex flex-col gap-3">
            {shown.map((c) => (
              <Pair
                key={`${c.a.id}|${c.b.id}`}
                c={c}
                done={done}
                busy={answer.isPending}
                onAnswer={(same) => answer.mutate({ a: c.a.id, b: c.b.id, same })}
              />
            ))}
          </ul>
          {candidates.length > SHOWN && (
            <Button size="sm" variant="ghost" className="mt-3" onClick={() => setAll(!all)}>
              {all ? t.routes.candidates.fewer : t.routes.candidates.all(candidates.length)}
            </Button>
          )}
        </>
      )}
    </Card>
  );
}
