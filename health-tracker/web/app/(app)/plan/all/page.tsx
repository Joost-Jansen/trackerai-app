"use client";

// All plans: drafts and upcoming plans, the active one and every earlier plan, each with what it asked against what
// was done. `?id=` opens one plan (components/plan/PlanScreen.tsx); a draft can be activated there.

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, EmptyState, Tag } from "@/components/ds";
import { CalendarIcon } from "@trackerai/ui/icons";
import PlanEditor from "@/components/plan/PlanEditor";
import PlanScreen from "@/components/plan/PlanScreen";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";
import type { PlanListItem, PlanStatus } from "@/lib/training";

const TONE: Record<PlanStatus, "neutral" | "gain" | "brand"> = { draft: "neutral", active: "brand", finished: "gain", stopped: "neutral" };

function PlanRow({ plan }: { plan: PlanListItem }) {
  const t = useT();
  const f = useFormat();
  const p = t.plans;
  const m = plan.summary;
  const due = m.done + m.missed;
  const pct = due ? Math.round((m.done / due) * 100) : null;
  const href = plan.status === "active" ? "/plan/" : `/plan/all/?id=${plan.id}`;
  return (
    <li className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Link href={href} className="truncate text-[15px] font-semibold hover:underline">
            {plan.title}
          </Link>
          <Tag tone={TONE[plan.status]}>{p.statuses[plan.status]}</Tag>
          {m.complete && plan.status !== "draft" && <Tag tone="gain">{p.complete}</Tag>}
        </div>
        <p className="mt-0.5 text-[12.5px] text-ink-muted">
          {m.start && m.end ? p.period(f.day(m.start), f.day(m.end)) : p.noSessions}
          {plan.goal ? ` · ${plan.goal}` : ""}
        </p>
      </div>
      <div className="flex flex-none flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-muted sm:justify-end">
        {pct != null && (
          <span className="inline-flex items-center gap-2 tabular-nums">
            <span className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-[var(--surface-inset)]">
              <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: "var(--data-gain)" }} />
            </span>
            {p.sessions(m.done, due)}
          </span>
        )}
        {m.open > 0 && <span className="tabular-nums">{p.toGo(m.open)}</span>}
        {m.planned_km > 0 && <span className="tabular-nums">{p.km(f.trim(m.done_km), f.trim(m.planned_km))}</span>}
        <Link href={href} className="font-semibold text-brand hover:underline">
          {p.open}
        </Link>
      </div>
    </li>
  );
}

function Group({ title, hint, plans }: { title: string; hint?: string; plans: PlanListItem[] }) {
  if (!plans.length) return null;
  return (
    <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
      <h2 className="text-[13.5px] font-semibold">{title}</h2>
      {hint && <p className="mt-0.5 max-w-prose text-[12.5px] text-ink-muted">{hint}</p>}
      <ul className="mt-2">
        {plans.map((plan) => (
          <PlanRow key={plan.id} plan={plan} />
        ))}
      </ul>
    </section>
  );
}

function PlansList() {
  const t = useT();
  const p = t.plans;
  const qc = useQueryClient();
  const [drafting, setDrafting] = useState(false);
  const q = useQuery({ queryKey: ["plans"], queryFn: () => api.get<{ persistent: boolean; plans: PlanListItem[] }>("/api/plans") });

  if (drafting) {
    return (
      <PlanEditor
        draft
        onSaved={() => {
          setDrafting(false);
          qc.invalidateQueries({ queryKey: ["plans"] });
        }}
        onCancel={() => setDrafting(false)}
      />
    );
  }
  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{errorText(q.error, t, p.loadFailed)}</p>;

  const plans = q.data.plans;
  // Drafts by their first session, the soonest first; earlier plans newest first (as the API sends them).
  const drafts = plans.filter((x) => x.status === "draft").sort((a, b) => (a.summary.start ?? "~").localeCompare(b.summary.start ?? "~"));
  const newDraft = (
    <Button size="sm" variant={drafts.length ? "ghost" : "secondary"} onClick={() => setDrafting(true)}>
      {p.newDraft}
    </Button>
  );

  if (!plans.length) {
    return (
      <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
        <EmptyState icon={<CalendarIcon width={22} height={22} />} title={p.emptyTitle} body={p.emptyBody} action={newDraft} />
      </section>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <Group title={p.upcoming} hint={p.upcomingHint} plans={drafts} />
      <Group title={p.current} plans={plans.filter((x) => x.status === "active")} />
      <Group title={p.past} plans={plans.filter((x) => x.status === "finished" || x.status === "stopped")} />
      <div>{newDraft}</div>
    </div>
  );
}

function AllPlans() {
  const t = useT();
  const id = Number(useSearchParams().get("id"));
  if (!id) return <PlansList />;
  const back = (
    <Link href="/plan/all/" className="text-[12.5px] font-semibold text-brand hover:underline">
      ← {t.plans.backToList}
    </Link>
  );
  return <PlanScreen key={id} planId={id} backLink={back} />;
}

export default function AllPlansPage() {
  return (
    <Suspense>
      <AllPlans />
    </Suspense>
  );
}
