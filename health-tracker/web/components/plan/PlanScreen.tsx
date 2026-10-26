"use client";

// One training plan: the active one (the Plan page) or any other (All plans, `planId`). Head with goal and
// countdown to the race, kilometres per week (planned against done), and per week the days with their sessions next
// to what you actually did. Create and edit with the plan editor; pasting from a table remains as a second route.
// Coaching agents write via the same API.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, EmptyState } from "@/components/ds";
import { CalendarIcon } from "@trackerai/ui/icons";
import PlanEditor from "@/components/plan/PlanEditor";
import PlanHeader from "@/components/plan/PlanHeader";
import PlanImporter from "@/components/plan/PlanImporter";
import VolumeChart from "@/components/plan/VolumeChart";
import WeekCard from "@/components/plan/WeekView";
import { buildWeeks, planRace, todayIso } from "@/components/plan/plan";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import type { Plan } from "@/lib/training";

type ActiveResponse = { persistent: boolean; plan: Plan | null };
type Mode = "view" | "edit" | "new" | "import";

/** `planId` null: the active plan. A given plan is shown as is, with "Activate" when it is not the active one. */
export default function PlanScreen({ planId = null, backLink }: { planId?: number | null; backLink?: React.ReactNode }) {
  const t = useT();
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("view");
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const key = planId == null ? ["plan-active"] : ["plan", planId];
  const q = useQuery({
    queryKey: key,
    queryFn: async (): Promise<ActiveResponse> =>
      planId == null
        ? api.get<ActiveResponse>("/api/plans/active")
        : { persistent: true, plan: await api.get<Plan>(`/api/plans/${planId}`) },
  });
  const refresh = () => {
    for (const k of [["plan-active"], ["plan"], ["plans"], ["achievements"], ["dashboard"]]) qc.invalidateQueries({ queryKey: k });
  };
  const link = useMutation({
    mutationFn: ({ planId, activityId, sessionDate }: { planId: number; activityId: string; sessionDate: string | null }) =>
      api.put<Plan>(`/api/plans/${planId}/links/${encodeURIComponent(activityId)}`, { session_date: sessionDate }),
    onSuccess: (p) => {
      qc.setQueryData<ActiveResponse>(key, (old) => ({ persistent: old?.persistent ?? true, plan: p }));
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "finished" | "active" }) => api.patch(`/api/plans/${id}`, { status }),
    onSuccess: refresh,
  });
  const go = (m: Mode) => {
    setMode(m);
    window.scrollTo({ top: 0 });
  };
  const saved = () => {
    go("view");
    refresh();
  };

  const plan = q.data?.plan ?? null;
  const today = todayIso();
  const weeks = useMemo(() => buildWeeks(plan?.sessions ?? [], plan?.weeks), [plan]);
  const race = useMemo(() => planRace(plan?.race, plan?.sessions ?? []), [plan]);
  useEffect(() => setToggled({}), [plan?.id]);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data)
    return (
      <div className="flex flex-col gap-3">
        {backLink}
        <p className="text-sm text-ink-muted">{q.error ? errorText(q.error, t, t.plan.loadFailed) : t.plan.loadFailed}</p>
      </div>
    );

  const warn = !q.data.persistent && (
    <p className="rounded border border-border bg-[var(--surface-sunken)] px-3 py-2 text-[12.5px] text-ink-muted">{t.plan.noDatabase}</p>
  );

  if (mode === "import") {
    return (
      <div className="flex flex-col gap-4">
        {warn}
        <PlanImporter onDone={saved} onCancel={() => go("view")} onEditor={() => go("new")} />
      </div>
    );
  }
  if (mode === "new" || (mode === "edit" && plan)) {
    return (
      <div className="flex flex-col gap-4">
        {warn}
        <PlanEditor
          key={mode === "edit" ? `edit-${plan?.id}` : "new"}
          plan={mode === "edit" ? plan : null}
          onSaved={saved}
          onCancel={() => go("view")}
          onPaste={mode === "new" ? () => go("import") : undefined}
        />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="flex flex-col gap-4">
        {warn}
        <section className="rounded border border-border bg-surface p-4 sm:p-[18px]">
          <EmptyState
            icon={<CalendarIcon width={22} height={22} />}
            title={t.plan.emptyTitle}
            body={t.plan.emptyBody}
            action={
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                <Button size="sm" variant="primary" onClick={() => go("new")}>
                  {t.plan.create}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => go("import")}>
                  {t.plan.paste}
                </Button>
              </div>
            }
          />
        </section>
      </div>
    );
  }

  const currentIndex = weeks.findIndex((w) => today >= w.monday && today <= w.days[6].date);
  const isOpen = (i: number) => toggled[weeks[i].monday] ?? weeks[i].days[6].date >= today;
  const pastCount = weeks.filter((w) => w.days[6].date < today).length;

  return (
    <div className="flex flex-col gap-4">
      {warn}
      {backLink}
      {/* Stretched on purpose: the km chart grows to the header's height (its bars are a share of it), so the pair ends
          level without empty space (docs/DEVELOPMENT.md rule 11, an elastic card). */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <PlanHeader
          plan={plan}
          race={race}
          today={today}
          weekIndex={currentIndex >= 0 ? currentIndex : null}
          weekCount={weeks.length}
          onEdit={() => go("edit")}
          onNew={plan.status === "active" ? () => go("new") : undefined}
          onFinish={
            plan.status === "active"
              ? () => confirm(t.plan.finishConfirm) && setStatus.mutate({ id: plan.id, status: "finished" })
              : undefined
          }
          onActivate={
            plan.status === "draft"
              ? () => confirm(t.plans.activateConfirm) && setStatus.mutate({ id: plan.id, status: "active" })
              : undefined
          }
        />
        <VolumeChart weeks={weeks} today={today} raceDate={race.date} />
      </div>

      {pastCount > 0 && pastCount === weeks.length && <p className="text-[13px] text-ink-muted">{t.plan.allPast}</p>}
      {link.isError && <p className="text-[12.5px] text-loss">{errorText(link.error, t, t.common.saveFailed)}</p>}
      <div className="flex flex-col gap-3">
        {weeks.map((w, i) => (
          <WeekCard
            key={w.monday}
            week={w}
            index={i}
            count={weeks.length}
            today={today}
            raceDate={race.date}
            open={isOpen(i)}
            onToggle={() => setToggled((t) => ({ ...t, [w.monday]: !isOpen(i) }))}
            onLink={(activityId, sessionDate) => link.mutate({ planId: plan.id, activityId, sessionDate })}
          />
        ))}
      </div>
      <p className="max-w-prose text-[12px] text-ink-muted">{t.texts.plan.matching}</p>
    </div>
  );
}
