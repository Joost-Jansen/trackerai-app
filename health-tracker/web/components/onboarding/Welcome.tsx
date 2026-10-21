"use client";

// The first-time tour:
//
//   1. Which watch: Garmin (connect the account) or an Apple Watch (import the Health app's export; then the first
//      step explains how to export on the iPhone, and there is no separate sync step). And how do you want to use
//      health-tracker? The site only, or also with Claude as coach (then the step "connect Claude" is added). Both can
//      be changed later under Help.
//   2. The steps: connect Garmin (or import Apple Health), first sync, zones, profile, (Claude), goals and plan. Every step
//      says from your own data whether it is done, and ticks itself off (also during the first sync).
//   3. A walk past the pages in the navigation, one step per page. These steps are not in the modal but a coach mark
//      on the page itself (CoachMark.tsx): it opens the page, rings its item in the sidebar and says what it is for.
//      This replaces the "look around" step of the checklist (opening the pages ticks it off).
//      A new account has no data yet, so during these steps the pages show a shared, read-only example account
//      (lib/exampleData.ts, api/example.py). The tour's own state always stays the user's.
//   4. Back is always possible, forward with Next; a step unlocks once you have been to the previous one.
//
// If a step sends you somewhere (Connections, Zones), the tour pauses and you continue with the button
// bottom right. Where you are is stored with your account (api/onboarding.py), so also on another device.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, IconButton } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "@trackerai/ui/icons";
import {
  CHOICES,
  DEVICES,
  PAGES,
  PAUSED_KEY,
  STEPS,
  stepHref,
  stepShown,
  useOnboarding,
  useSetOnboarding,
  type Choice,
  type Device,
} from "@/lib/onboarding";
import { localizeNav, NAV } from "@/lib/nav";
import { useT } from "@/lib/i18n";
import CoachMark from "./CoachMark";
import { Sketch } from "./Sketches";
import { Check, stepExplain, stepTitle } from "./steps";

type Action = { label: string; href: string };
type TourStep = {
  key: string;
  title: string;
  done?: boolean;
  intro: React.ReactNode;
  bullets: React.ReactNode[];
  visual?: React.ReactNode;
  actions: Action[];
  /** A step of the walk past the pages: shown as a coach mark next to this nav item, on its page. */
  page?: { id: string; href: string };
};

function Phases({ lines }: { lines: string[] }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg p-4" style={{ background: "var(--surface-inset)" }}>
      {lines.map((r, i) => (
        <span key={r} className="flex items-center gap-2 text-[12.5px]">
          <span
            className="grid h-5 w-5 flex-none place-items-center rounded-full text-[11px] font-semibold tabular-nums"
            style={{ background: "var(--surface-card)" }}
          >
            {i + 1}
          </span>
          {r}
        </span>
      ))}
    </div>
  );
}

function readPaused(): boolean {
  try {
    return sessionStorage.getItem(PAUSED_KEY) === "1";
  } catch {
    return false;
  }
}
function writePaused(v: boolean) {
  try {
    if (v) sessionStorage.setItem(PAUSED_KEY, "1");
    else sessionStorage.removeItem(PAUSED_KEY);
  } catch {
    /* no storage */
  }
}

export default function Welcome({ enabled }: { enabled: boolean }) {
  const t = useT();
  const tr = t.onboarding.tour;
  const router = useRouter();
  const q = useOnboarding(enabled);
  const set = useSetOnboarding();
  const [choice, setChoice] = useState<Choice | null>(null);
  const [device, setDevice] = useState<Device | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [step, setStep] = useState<number | null>(null); // 0 = first step after the choice
  const [reached, setReached] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => setPaused(readPaused()), []);

  // "Rondleiding opnieuw" (restart tour) in Help sets the step back to 0: then start at the beginning.
  const serverStep = q.data?.step ?? 0;
  const done = q.data?.done ?? true;
  useEffect(() => {
    if (!done && serverStep === 0) {
      setPaused(false);
      setStep(null);
      setReached(0);
      setChoice(null);
      setChoosing(true);
    }
  }, [done, serverStep]);

  const o = q.data;
  if (!o || o.done) return null;
  const chosen = choice ?? o.choice;
  const chosenDevice = device ?? o.device;
  const current = step ?? Math.max(0, serverStep - 1);
  const onChoice = choosing || !chosen || (step === null && serverStep === 0);

  const save = (i: number) => set.mutate({ step: i + 1 });
  const finish = () => {
    writePaused(false);
    set.mutate({ done: true, step: 0 });
  };
  const pause = (href?: string) => {
    setPaused(true);
    writePaused(true);
    save(current);
    if (href) router.push(href);
  };

  const view = { ...o, choice: chosen, device: chosenDevice };
  const apple = chosenDevice === "apple";
  const tour: TourStep[] = [
    {
      key: "intro",
      title: tr.introTitle,
      intro: apple ? tr.introApple : tr.intro,
      bullets: tr.introBullets,
      visual: <Phases lines={apple ? tr.phasesApple : tr.phases} />,
      actions: [],
    },
  ];
  for (const s of STEPS) {
    // "Look around" is covered by the walk past the pages below.
    if (!stepShown(s, view) || s.id === "plan" || s.id === "explore") continue;
    const ex = stepExplain(s.id, view, t);
    if (s.id === "goals") {
      const plan = stepExplain("plan", o, t);
      tour.push({
        key: "goals-plan",
        title: tr.goalsPlan,
        done: o.steps.goals && o.steps.plan,
        intro: (
          <>
            {ex.intro} {plan.intro}
          </>
        ),
        bullets: [...ex.bullets, ...plan.bullets],
        visual: <Sketch id="goals-plan" />,
        actions: [
          { label: t.onboarding.goTo(t.onboarding.steps.goals.link), href: "/analyses/goals/" },
          { label: t.onboarding.goTo(t.onboarding.steps.plan.link), href: "/plan/" },
        ],
      });
      continue;
    }
    tour.push({
      key: s.id,
      title: s.optional ? tr.optional(stepTitle(s.id, view, t)) : stepTitle(s.id, view, t),
      done: o.steps[s.id],
      intro: ex.intro,
      bullets: ex.bullets,
      visual: <Sketch id={s.id} />,
      actions:
        s.id === "sync" && !o.status.garmin.connected
          ? []
          : [{ label: t.onboarding.goTo(t.onboarding.steps[s.id].link), href: stepHref(s, view) }],
    });
  }
  // The walk past the pages: every page in the navigation, in its order. Today, Trends, Loops and History reuse the
  // texts of the look-around step (onboarding.pages); the others have their own (onboarding.walk).
  for (const item of localizeNav(NAV, t).flatMap((g) => g.items)) {
    const page = PAGES.find((p) => p.id === item.id);
    const w = t.onboarding.walk;
    const intro = page
      ? w.shows(item.label, t.onboarding.pages[page.id].text)
      : item.id === "plan" || item.id === "log" || item.id === "settings" || item.id === "help"
        ? w[item.id]
        : null;
    if (!intro) continue;
    tour.push({ key: `page-${item.id}`, title: item.label, intro, bullets: [], actions: [], page: { id: item.id, href: item.href } });
  }
  tour.push({
    key: "done",
    title: tr.doneTitle,
    intro: tr.doneIntro,
    bullets: tr.doneBullets,
    actions: [],
  });

  const i = Math.min(current, tour.length - 1);
  const here = tour[i];

  if (paused && !onChoice) {
    return (
      <div
        className="fixed bottom-4 right-4 z-40 flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full py-1.5 pl-4 pr-1.5 text-[12.5px]"
        style={{ background: "var(--surface-card)", boxShadow: "inset 0 0 0 1px var(--border-hairline), var(--shadow-4)" }}
        role="status"
      >
        <span className="truncate">{tr.paused(i + 1, tour.length)}</span>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setPaused(false);
            writePaused(false);
            q.refetch();
          }}
        >
          {tr.resume}
        </Button>
        <Button size="sm" variant="ghost" onClick={finish}>
          {tr.stop}
        </Button>
      </div>
    );
  }

  const go = (n: number) => {
    setStep(n);
    setReached((b) => Math.max(b, n));
    save(n);
  };

  if (here.page && !onChoice) {
    return (
      <CoachMark
        navId={here.page.id}
        href={here.page.href}
        title={here.title}
        text={here.intro}
        index={i}
        total={tour.length}
        onBack={() => go(i - 1)}
        onNext={() => go(i + 1)}
        onSkip={finish}
        onPause={() => pause()}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={tr.aria}>
      <div className="absolute inset-0" style={{ background: "rgba(20,24,20,0.42)" }} onClick={() => (onChoice ? undefined : pause())} />
      <div
        className="relative flex max-h-[90dvh] w-full max-w-[500px] flex-col overflow-y-auto overscroll-contain rounded-xl p-6"
        style={{ background: "var(--surface-card)", boxShadow: "inset 0 0 0 1px var(--border-hairline), var(--shadow-4)" }}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="ds-eyebrow">{onChoice ? tr.welcome : tr.tour}</span>
          <IconButton
            label={onChoice ? t.common.close : tr.pause}
            onClick={() => (onChoice ? finish() : pause())}
            icon={<CloseIcon className="h-4 w-4" />}
            className="-mr-2 flex-none"
          />
        </div>

        {onChoice ? (
          <>
            <h3 className="mb-1.5 font-display text-[21px] font-normal tracking-[-0.014em]">{tr.welcomeTitle}</h3>
            <p className="mb-4 text-[13px] leading-relaxed text-ink-muted">{tr.welcomeText}</p>
            {/* Which watch: decides how your data comes in (connect Garmin, or import Apple Health) */}
            <p className="mb-2 text-[12.5px] font-semibold">{t.onboarding.devices.question}</p>
            <div className="mb-4 grid grid-cols-2 gap-2" role="radiogroup" aria-label={t.onboarding.devices.question}>
              {DEVICES.map((d) => (
                <button
                  key={d}
                  type="button"
                  role="radio"
                  aria-checked={chosenDevice === d}
                  onClick={() => {
                    setDevice(d);
                    set.mutate({ device: d });
                  }}
                  className="rounded-lg p-3 text-left transition-colors hover:bg-surface-2"
                  style={{
                    border: `1px solid ${chosenDevice === d ? "var(--text-primary)" : "var(--border)"}`,
                    boxShadow: chosenDevice === d ? "inset 0 0 0 1px var(--text-primary)" : undefined,
                  }}
                >
                  <span className="block text-[14px] font-semibold">{t.onboarding.devices[d].title}</span>
                  <span className="block text-xs leading-snug text-ink-muted">{t.onboarding.devices[d].text}</span>
                </button>
              ))}
            </div>
            <p className="mb-2 text-[12.5px] font-semibold">{tr.useQuestion}</p>
            <div className="flex flex-col gap-2">
              {CHOICES.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => {
                    setChoice(c);
                    setChoosing(false);
                    setStep(0);
                    setReached(0);
                    set.mutate({ choice: c, step: 1 });
                  }}
                  className="rounded-lg p-3 text-left transition-colors hover:bg-surface-2"
                  style={{ border: `1px solid ${chosen === c ? "var(--text-primary)" : "var(--border)"}` }}
                >
                  <span className="block text-[14px] font-semibold">{t.onboarding.choices[c].title}</span>
                  <span className="block text-xs text-ink-muted">{t.onboarding.choices[c].text}</span>
                </button>
              ))}
            </div>
            <div className="mt-4">
              <Button variant="ghost" className="-ml-3" onClick={finish}>
                {tr.skip}
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="flex gap-1">
              {tour.map((step, n) => (
                <button
                  key={step.key}
                  type="button"
                  disabled={n > Math.max(reached, i)}
                  onClick={() => go(n)}
                  aria-label={tr.stepAria(n + 1, step.title, n > Math.max(reached, i))}
                  className="h-1.5 flex-1 rounded-full disabled:cursor-not-allowed"
                  style={{ background: n <= i ? "var(--n-800)" : n <= reached ? "var(--border-strong)" : "var(--surface-inset)" }}
                />
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <span className="text-[11.5px] text-ink-muted">{tr.step(i + 1, tour.length)}</span>
              {here.done !== undefined && (
                <span
                  className="flex items-center gap-1.5 text-[11.5px]"
                  style={{ color: here.done ? "var(--text-gain)" : "var(--text-muted)" }}
                >
                  <Check done={here.done} size={16} /> {here.done ? tr.done : tr.todo}
                </span>
              )}
            </div>

            <h3 className="mb-1.5 mt-4 font-display text-[21px] font-normal tracking-[-0.014em]">{here.title}</h3>
            <p className="mb-3 text-[13px] leading-relaxed text-ink-muted">{here.intro}</p>
            {here.visual && <div className="mb-3">{here.visual}</div>}
            {here.bullets.length > 0 && (
              <ul className="mb-4 space-y-1.5">
                {here.bullets.map((b, n) => (
                  <li key={n} className="flex gap-2 text-[12.5px] leading-relaxed">
                    <span className="mt-[7px] h-1 w-1 flex-none rounded-full" style={{ background: "var(--text-faint)" }} />
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            )}
            {here.actions.length > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {here.actions.map((a) => (
                  <Button key={a.href} size="sm" variant="secondary" onClick={() => pause(a.href)}>
                    {a.label}
                  </Button>
                ))}
                <span className="text-xs text-ink-muted">{tr.waits}</span>
              </div>
            )}

            <div className="mt-auto flex items-center justify-between gap-2 pt-1">
              <Button
                variant="ghost"
                className="-ml-3"
                onClick={() => (i === 0 ? setChoosing(true) : go(i - 1))}
                icon={<ChevronLeftIcon className="h-3.5 w-3.5" />}
              >
                {i === 0 ? tr.otherChoice : t.common.previous}
              </Button>
              {i < tour.length - 1 ? (
                <Button variant="primary" onClick={() => go(i + 1)} iconAfter={<ChevronRightIcon className="h-3.5 w-3.5" />}>
                  {t.common.next}
                </Button>
              ) : (
                <Button variant="primary" onClick={finish}>
                  {t.common.done}
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
