"use client";

// The "Aan de slag" (getting started) checklist: every step with a check mark from your own data. On the dashboard as a
// card (replaces the old welcome card) while the tour is not done, or while there are no workouts yet and you have
// not hidden it; in Help always, as a list.

import Link from "next/link";
import Card from "@trackerai/ui/components/Card";
import { Button, ButtonLink } from "@/components/ds";
import { STEPS, stepHref, stepShown, useOnboarding, useSetOnboarding, type Onboarding } from "@/lib/onboarding";
import { useFormat, useT } from "@/lib/i18n";
import { rich } from "@/lib/i18n/rich";
import { CheckRow, stepSummary, stepTitle } from "./steps";

export function Progress({ done, total }: { done: number; total: number }) {
  const t = useT();
  return (
    <div className="flex items-center gap-2.5" aria-label={t.onboarding.progress(done, total)}>
      <div className="flex flex-1 gap-1">
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className="h-1.5 flex-1 rounded-full" style={{ background: i < done ? "var(--pos)" : "var(--surface-inset)" }} />
        ))}
      </div>
      <span className="text-[11.5px] tabular-nums text-ink-muted">{t.onboarding.progressShort(done, total)}</span>
    </div>
  );
}

/** The steps as a list. `only`: only the required or only the optional ones. */
export function StepList({ o, only, links = true }: { o: Onboarding; only?: "required" | "optional"; links?: boolean }) {
  const t = useT();
  const f = useFormat();
  const steps = STEPS.filter((s) => stepShown(s, o) && (!only || (only === "optional") === s.optional));
  return (
    <ul className="flex flex-col">
      {steps.map((s) => (
        <CheckRow
          key={s.id}
          done={o.steps[s.id]}
          title={stepTitle(s.id, o, t)}
          optional={s.optional}
          action={
            links && !o.steps[s.id] && s.id !== "explore" && !(s.id === "sync" && !o.status.garmin.connected) ? (
              <ButtonLink href={stepHref(s, o)} size="sm" variant="secondary">
                {t.onboarding.steps[s.id].link}
              </ButtonLink>
            ) : undefined
          }
        >
          {stepSummary(s.id, o, t, f)}
        </CheckRow>
      ))}
    </ul>
  );
}

export function countSteps(o: Onboarding) {
  const steps = STEPS.filter((s) => stepShown(s, o));
  return { done: steps.filter((s) => o.steps[s.id]).length, total: steps.length };
}

/** The card on the dashboard. Shows itself only when it is needed. */
export default function OnboardingCard() {
  const t = useT();
  const q = useOnboarding();
  const set = useSetOnboarding();
  const o = q.data;
  if (!o) return null;
  const c = t.onboarding.card;
  const show = !o.done || (o.status.activities.count === 0 && !o.hidden.includes("checklist"));
  if (!show) return null;
  const { done, total } = countSteps(o);

  return (
    <Card
      title={c.title}
      action={
        <div className="flex items-center gap-1">
          <ButtonLink href="/help/" size="sm" variant="ghost">
            {t.nav.items.help}
          </ButtonLink>
          <Button
            size="sm"
            variant="ghost"
            disabled={set.isPending}
            onClick={() => set.mutate(o.done ? { hide: "checklist" } : { done: true, hide: "checklist" })}
          >
            {t.common.hide}
          </Button>
        </div>
      }
    >
      <p className="mb-3 max-w-prose text-[13px] leading-relaxed text-ink-muted">
        {o.required_done ? c.requiredDone : o.device === "apple" ? c.requiredTodoApple : c.requiredTodo}
      </p>
      <div className="mb-2">
        <Progress done={done} total={total} />
      </div>
      <StepList o={o} only={o.required_done ? "optional" : "required"} />
      {!o.required_done && (
        <p className="mt-2 border-t border-border pt-2.5 text-xs text-ink-muted">
          {c.laterPrefix}
          {STEPS.filter((s) => s.optional && stepShown(s, o))
            .map((s) => t.onboarding.steps[s.id].title)
            .map((x) => (x.includes("Claude") ? x : x.toLowerCase()))
            .join(", ")}
          .{" "}
          {rich(c.laterSuffix, {
            link: (x) => (
              <Link href="/help/" className="underline underline-offset-4">
                {x}
              </Link>
            ),
          })}
        </p>
      )}
    </Card>
  );
}
