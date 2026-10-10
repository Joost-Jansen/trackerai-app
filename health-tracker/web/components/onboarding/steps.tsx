"use client";

// The explanation per step, written once: the tour, the checklist on the dashboard and Help show the same text.
// What is about the user (number of workouts, max heart rate, when connected) comes from the onboarding status; the
// texts from lib/i18n (onboarding) and the explanations about health and performance from lib/texts.ts (t.texts).

import Link from "next/link";
import type { Format, Messages } from "@/lib/i18n";
import { useT } from "@/lib/i18n";
import { PAGES, type Onboarding, type StepId } from "@/lib/onboarding";

const FIRST_SYNC_DAYS = 365;

export function A({ href, children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) {
  return <Link href={href} onClick={onClick} className="underline underline-offset-4">{children}</Link>;
}

/** A check mark: green when done, a dot when still to do. */
export function Check({ done, size = 20 }: { done: boolean; size?: number }) {
  return (
    <span aria-hidden className="grid flex-none place-items-center rounded-full text-[11px] font-semibold"
      style={{
        width: size, height: size,
        background: done ? "var(--pos)" : "var(--surface-inset)",
        color: done ? "var(--surface-card)" : "var(--text-faint)",
      }}>
      {done ? "✓" : "·"}
    </span>
  );
}

/** One row of a checklist. */
export function CheckRow({ done, title, optional, children, action }: {
  done: boolean; title: string; optional?: boolean; children?: React.ReactNode; action?: React.ReactNode;
}) {
  const t = useT();
  return (
    <li className="flex gap-3 border-t border-border py-2.5 first:border-t-0">
      <Check done={done} />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-[13px]">
        <span className={done ? "" : "font-semibold"}>
          {title}
          {optional && <span className="ml-1.5 text-[11px] font-normal text-ink-muted">{t.common.optional}</span>}
          <span className="sr-only">{done ? t.onboarding.doneSr : t.onboarding.todoSr}</span>
        </span>
        {children && <span className="text-xs leading-relaxed text-ink-muted">{children}</span>}
      </div>
      {action && <div className="flex-none self-center">{action}</div>}
    </li>
  );
}

/** A step's title: the first step is "Connect Garmin", or "Import Apple Health" for an Apple Watch. */
export function stepTitle(id: StepId, o: Pick<Onboarding, "device"> | null, t: Messages): string {
  return id === "garmin" && o?.device === "apple" ? t.onboarding.steps.apple.title : t.onboarding.steps[id].title;
}

/** What a step says now: what is already there, or what you need to do. Short, for a checklist. */
export function stepSummary(id: StepId, o: Onboarding, t: Messages, f: Format): React.ReactNode {
  const st = o.status;
  const s = t.onboarding.summary;
  switch (id) {
    case "garmin":
      if (o.device === "apple") {
        if (st.apple.running) return s.appleRunning;
        if (st.apple.imported) return s.appleDone(st.apple.workouts ?? 0, st.apple.days ?? 0, st.apple.imported_at ? f.day(st.apple.imported_at) : null);
        return st.apple.failed ? s.appleFailed : s.appleTodo;
      }
      return st.garmin.connected ? s.garminConnected(st.garmin.connected_at ? f.day(st.garmin.connected_at) : null) : s.garminTodo;
    case "sync":
      if (st.sync.running && !o.steps.sync) return s.syncRunning;
      if (o.steps.sync) {
        const a = st.activities;
        const last = st.sync.last_sync ? f.dateTime(st.sync.last_sync) : t.common.unknown;
        return a.count > 0 ? s.syncDone(a.count, f.day(a.first), f.day(a.last), last, st.sync.last_failed) : s.syncEmpty(last);
      }
      return st.garmin.connected ? s.syncWaiting : s.syncAfterGarmin;
    case "zones": {
      if (o.steps.zones) return t.texts.onboarding.zonesSet(st.zones.set, st.zones.estimated);
      const sport = (["run", "ride", "swim"] as const).find((x) => st.zones.suggested_max[x]);
      return sport ? t.texts.onboarding.maxSuggestion(sport, st.zones.suggested_max[sport] as number) : s.zonesTodo;
    }
    case "profile":
      return o.steps.profile ? s.profileDone(st.profile.filled.map((k) => s.facts[k] ?? k)) : s.profileTodo;
    case "explore": {
      const left = PAGES.filter((p) => p.id !== "dashboard" && !o.visited.includes(p.id));
      return left.length === 0
        ? s.exploreDone
        : <>{s.exploreLeft}{left.map((p, i) => <span key={p.id}>{i > 0 && ", "}<A href={p.href}>{t.onboarding.pages[p.id].label}</A></span>)}.</>;
    }
    case "agent":
      return o.steps.agent ? s.agentDone(st.agents.tokens) : s.agentTodo;
    case "goals":
      return o.steps.goals ? s.goalsDone : s.goalsTodo;
    case "plan":
      return o.steps.plan ? s.planDone(st.plan.active, st.plan.count) : s.planTodo;
  }
}

/** The longer explanation per step, for the tour and the guide: an introduction and points of attention. */
export function stepExplain(id: StepId, o: Onboarding | null, t: Messages): { intro: React.ReactNode; bullets: React.ReactNode[] } {
  const ex = t.onboarding.explain;
  const T = t.texts.onboarding;
  switch (id) {
    case "garmin":
      return o?.device === "apple" ? ex.apple : ex.garmin;
    case "sync":
      return { intro: T.firstSync(FIRST_SYNC_DAYS), bullets: ex.sync };
    case "zones": {
      const sug = o ? (["run", "ride", "swim"] as const).filter((s) => o.status.zones.suggested_max[s]) : [];
      return {
        intro: T.zonesWhy,
        bullets: [...sug.map((s) => T.maxSuggestion(s, o!.status.zones.suggested_max[s] as number)), T.zonesHow, ex.zones],
      };
    }
    case "profile":
      return { intro: T.profileWhy, bullets: ex.profile };
    case "explore":
      return {
        intro: ex.explore,
        bullets: PAGES.map((p) => <><b>{t.onboarding.pages[p.id].label}</b>: {t.onboarding.pages[p.id].text}</>),
      };
    case "agent":
      return ex.agent;
    case "goals":
      return ex.goals;
    case "plan":
      return ex.plan;
  }
}
