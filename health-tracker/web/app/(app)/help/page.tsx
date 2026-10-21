"use client";

// Help, getting started: the checklist from your own data, how you use the site (the site
// only or also with Claude), and restarting the tour. The guide and the explanation about Claude are in the tabs next to it.

import Card from "@trackerai/ui/components/Card";
import { Button, ButtonLink, Tabs } from "@/components/ds";
import { countSteps, Progress, StepList } from "@/components/onboarding/Checklist";
import { useT } from "@/lib/i18n";
import { CHOICES, DEVICES, PAUSED_KEY, useOnboarding, useSetOnboarding, type Choice, type Device } from "@/lib/onboarding";

export default function HelpStart() {
  const t = useT();
  const h = t.help.start;
  const q = useOnboarding();
  const set = useSetOnboarding();
  const o = q.data;
  if (!o) return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  const { done, total } = countSteps(o);

  return (
    <div className="flex flex-col gap-4">
      <Card title={h.title}>
        <p className="mb-3 max-w-prose text-[13px] leading-relaxed text-ink-muted">{h.intro}</p>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-ink-muted">{h.watch}</span>
          <Tabs
            variant="segmented"
            ariaLabel={t.onboarding.devices.question}
            items={DEVICES.map((d) => ({ id: d, label: t.onboarding.devices[d].title }))}
            value={o.device}
            onChange={(v) => set.mutate({ device: v as Device })}
          />
          <span className="text-xs text-ink-muted">{h.using}</span>
          <Tabs
            variant="segmented"
            ariaLabel={h.usingAria}
            items={CHOICES.map((c) => ({ id: c, label: t.onboarding.choices[c].title }))}
            value={o.choice ?? "site"}
            onChange={(v) => set.mutate({ choice: v as Choice })}
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={set.isPending}
            onClick={() => {
              try {
                sessionStorage.removeItem(PAUSED_KEY);
              } catch {
                /* no storage */
              }
              set.mutate({ done: false, step: 0 });
            }}
          >
            {h.restart}
          </Button>
          <ButtonLink href="/two-step/" size="sm" variant="ghost">
            {t.auth.twoStepHelp}
          </ButtonLink>
        </div>
      </Card>

      <Card
        title={h.progress}
        action={
          <span className="w-40">
            <Progress done={done} total={total} />
          </span>
        }
      >
        <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-muted">{h.basics}</h3>
              <ButtonLink href="/help/guide/" size="sm" variant="ghost">
                {h.manual}
              </ButtonLink>
            </div>
            <StepList o={o} only="required" />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-muted">{h.further}</h3>
              {o.choice === "claude" && (
                <ButtonLink href="/help/claude/" size="sm" variant="ghost">
                  {h.claude}
                </ButtonLink>
              )}
            </div>
            <StepList o={o} only="optional" />
          </div>
        </div>
      </Card>
    </div>
  );
}
