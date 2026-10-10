"use client";

// The first-time tour: a step-by-step plan you go through step by step, as the
// DeGiro tour was at first — but for both parts.
//
//   0. A welcome: what the app is, start or skip.
//   1. Money: first an intermediate step that says what it is about, then the
//      steps themselves, with the same images as in Help.
//   2. You go back whenever you want, forward only with Next: a step unlocks
//      when you have been at the previous one.
//
//   3. A walk past every page you have (lib/nav.ts, so beta pages only when on),
//      each with a button that opens it. The progress bar is split per part.
//
// If a step sends you somewhere (Update, Bank connection), the tour pauses and
// you carry on with the button at the bottom right. Where you are is stored with
// your account (lib/onboarding.ts), so also on another device.

import { APP } from "@/lib/app";
import type { NavGroup } from "@/lib/nav";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, IconButton } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "@trackerai/ui/icons";
import { StepContent, type Step } from "@/components/steps/StepPlan";
import PageSketch from "@/components/steps/PageSketch";
import TourSpotlight from "@/components/TourSpotlight";
import { CONNECT_BANK, EXPORT_ROUTES, LABELLING, ENTER_BALANCE } from "@/components/steps/money";
import { useOnboarding, useSaveOnboarding, type BankChoice } from "@/lib/onboarding";
import { tr, trx } from "@/lib/i18n";

type Part = "money" | "around";
type TourStep = {
  part: Part; step: Step; action?: { label: string; run: () => void };
  /** Next stays off until the bank choice is made. */
  needsBank?: boolean;
  /** A page in the walk: shown on the real page as a coach mark (TourSpotlight), not in the modal. */
  page?: { id: string; href: string };
};

const PAUSED = "tour-paused";
const NAME: Record<Part, string> = { money: tr("Money"), around: tr("Take a look around") };

// One line per page for the walk past them, by nav id (lib/nav.ts). A page
// without a line here is left out of the walk.
const ABOUT: Record<string, string> = {
  // The portfolio items (one per question, the views as tabs).
  holdings: tr("What you own: every holding, the details, and how it's spread across sectors and regions."),
  performance: tr("What your portfolio has earned: returns compared with the market, and dividends."),
  agenda: tr("What's coming up and what's happening: results and ex-dividend dates, and news about what you own."),
  net_worth: tr("Everything you own minus everything you owe, and what moved it each month."),
  spending: tr("See where your money goes, by category and by month."),
  budget: tr("Set a monthly limit per category and keep track of how you're doing."),
  transactions: tr("Search all your transactions and fix any category."),
  labelling: tr("Transactions the app couldn't categorise yet, ready to label in one go."),
  categories: tr("Your categories, the rules behind them, and how each one counts."),
  accounts: tr("Your accounts and balances, plus your bank connection."),
  settings: tr("Your account, language, Claude access and feedback."),
  help: tr("Guides for everything, and this tour if you want it again. Look for the ? next to any page title."),
};

/** The two ways bank data comes in, with what each costs and gives. */
function BankOptions({ value, onPick }: { value: BankChoice | null; onPick: (b: BankChoice) => void }) {
  const options: { id: BankChoice; title: string; text: string; pros: string[]; cons: string[] }[] = [
    {
      id: "upload",
      title: tr("Upload exports"),
      text: tr("Download a CSV from your bank now and then, and upload it under Update."),
      pros: [tr("Years of history in one go, savings accounts included"), tr("Nothing to set up")],
      cons: [tr("Up to date only when you upload again")],
    },
    {
      id: "connect",
      title: tr("Exports plus an automatic connection"),
      text: tr("Upload your history once, then connect your bank through Enable Banking so new transactions and balances come in by themselves."),
      pros: [tr("New transactions and balances arrive automatically"), tr("Read-only: the connection can never make payments")],
      cons: [
        tr("About 15 minutes to set up: a free Enable Banking account and your own app key"),
        tr("Banks share limited history and not always savings accounts, so you still upload once"),
        tr("Approve it again in your bank app every 180 days"),
      ],
    },
  ];
  return (
    <div className="flex flex-col gap-2">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onPick(o.id)}
          className="rounded-lg p-3 text-left transition-colors hover:bg-surface-2"
          style={{ border: `1px solid ${value === o.id ? "var(--text-primary)" : "var(--rule)"}` }}>
          <span className="block text-[14px] font-semibold">{o.title}</span>
          <span className="mb-1.5 block text-xs text-ink-muted">{o.text}</span>
          {o.pros.map((p) => <span key={p} className="block text-xs"><span aria-hidden style={{ color: "var(--text-gain)" }}>+ </span>{p}</span>)}
          {o.cons.map((c) => <span key={c} className="block text-xs text-ink-muted"><span aria-hidden style={{ color: "var(--text-loss)" }}>− </span>{c}</span>)}
        </button>
      ))}
      <p className="text-[11.5px] text-ink-muted">{tr("Not sure? Start with exports. You can add the connection any time under Accounts → Bank connection.")}</p>
    </div>
  );
}

export default function Welcome({ enabled, onUpdate, nav }: { enabled: boolean; onUpdate: () => void; nav: NavGroup[] }) {
  const router = useRouter();
  const q = useOnboarding(enabled);
  const put = useSaveOnboarding();
  const [bankChoice, setBankChoice] = useState<BankChoice | null>(null);
  // Where you are in the tour (0 is the first step after the welcome), and how far you had come.
  const [step, setStep] = useState<number | null>(null);
  const [reaches, setReaches] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    try { setPaused(sessionStorage.getItem(PAUSED) === "1"); } catch { /* geen opslag */ }
  }, []);

  // "Restart tour" in Help sets the step back to 0: then start at the front.
  const serverStep = q.data?.step ?? 0;
  const done = q.data?.done ?? true;
  useEffect(() => {
    if (!done && serverStep === 0) {
      setPaused(false);
      setStep(null);
      setReaches(0);
    }
  }, [done, serverStep]);

  if (!q.data || q.data.done) return null;
  // The tour starts from your wealth, straight into Money; the walk past the
  // pages that follows also shows the portfolio below it.
  const bank = bankChoice ?? q.data.bank;
  // Server: 0 is the welcome, 1 the first step of the tour.
  const current = step ?? Math.max(0, serverStep - 1);
  const onWelcome = step === null && serverStep === 0;

  const save = (i: number) => put.mutate({ step: i + 1 });
  const close = () => {
    try { sessionStorage.removeItem(PAUSED); } catch { /* geen opslag */ }
    put.mutate({ done: true, step: 0 });
  };
  const pause = (after_that: () => void) => {
    setPaused(true);
    try { sessionStorage.setItem(PAUSED, "1"); } catch { /* geen opslag */ }
    save(current);
    after_that();
  };

  const tour: TourStep[] = [];
  // Money, in the order the data needs: first how bank data comes in, then the
  // export (it brings the history, savings accounts included; a connection
  // carries on from its last day), then the connection if chosen, then a
  // balance per account, and last what is left to label.
  {
    tour.push({
      part: "money",
      step: {
        title: tr("Money"),
        intro: tr("Add the rest of your money: bank and savings accounts, spending and debts. Together with your investments, that gives you your full net worth."),
        bullets: [tr("Choose how your bank data comes in"), tr("Set a balance for each account"), tr("Label anything the app doesn't recognise")],
        visual: <PageSketch kind="line" label={tr("Net worth")} />,
      },
    });
    const i_choice = tour.length;
    tour.push({
      part: "money",
      needsBank: true,
      step: {
        title: tr("How should your bank data come in?"),
        intro: tr("Both use the same accounts, and you can add or drop the connection later under Accounts."),
        bullets: [],
        visual: <BankOptions value={bank} onPick={(b) => { setBankChoice(b); put.mutate({ bank: b, step: i_choice + 2 }); setStep(i_choice + 1); setReaches((r) => Math.max(r, i_choice + 1)); }} />,
      },
    });
    tour.push({
      part: "money",
      step: {
        title: tr("Upload your bank export"),
        intro: tr("Download a CSV from your bank and upload it under Update. It brings in your history, savings accounts included."),
        bullets: [
          tr("ING: your transactions as a semicolon-separated CSV, plus the balance overview of your savings accounts"),
          tr("bunq: the account statement as a CSV, one per account"),
          ...(bank === "connect" ? [tr("Do this once even with a connection: banks often share only part of your history. Transactions in both are recognised and counted once.")] : []),
          tr("Step-by-step instructions for each bank are under “How do I export this?” in Update"),
        ],
        visual: EXPORT_ROUTES[0].steps[0].visual,
      },
      action: { label: tr("Open Update"), run: () => pause(onUpdate) },
    });
    if (bank === "connect") {
      CONNECT_BANK.forEach((s, i) => tour.push({
        part: "money", step: s,
        action: i === 2 ? { label: tr("Go to Bank connection"), run: () => pause(() => router.push("/accounts/connect")) } : undefined,
      }));
    }
    tour.push({ part: "money", step: ENTER_BALANCE, action: { label: tr("Go to Accounts"), run: () => pause(() => router.push("/accounts")) } });
    tour.push({ part: "money", step: LABELLING, action: { label: tr("Go to To label"), run: () => pause(() => router.push("/spending/labelling")) } });
  }
  // Optional: Claude reading along through MCP, with a token under Agents.
  {
    tour.push({
      part: "money",
      step: {
        title: tr("Optional: use Claude as your assistant"),
        intro: tr("Connect Claude to your data and just ask: how did my portfolio do, where did my money go, what still needs a label? Claude only sees what your token allows."),
        bullets: [
          tr("Create a token under Settings → Agents, read-only or with write access"),
          tr("Add it as a connector in the Claude app or in Claude Code"),
          tr("Not using Claude? Skip this step; you can set it up any time"),
        ],
        visual: <PageSketch kind="chat" label="Claude" />,
      },
      action: { label: tr("Go to Agents"), run: () => pause(() => router.push("/account/agents")) },
    });
  }
  // A walk past the pages.
  const pages = nav.flatMap((g) => g.items).filter((it) => ABOUT[it.id]);
  if (pages.length > 0) {
    tour.push({
      part: "around",
      step: {
        title: NAME.around,
        intro: tr("Next, a quick look at each page. The tour opens the page itself and points to it in the menu."),
        bullets: [tr("New exports go in through Update, at the top right")],
        visual: <PageSketch kind="sidebar" label={NAME.around} />,
      },
    });
    pages.forEach((it) => tour.push({
      part: "around",
      step: { title: it.label, intro: ABOUT[it.id], bullets: [] },
      page: { id: it.id, href: it.href },
    }));
  }
  {
    tour.push({
      part: tour[tour.length - 1].part,
      step: {
        title: tr("You're all set"),
        intro: tr("That's the tour. You'll find these steps, and more on how the numbers work, under Help. Every page also has a ? next to its title."),
        bullets: [tr("Want to see this again? Go to Help → Getting started → Tour again")],
      },
    });
  }

  const i = Math.min(current, Math.max(0, tour.length - 1));
  const here = tour[i];
  const share_out = Array.from(new Set(tour.map((t) => t.part)));

  if (paused && !onWelcome && here) {
    return (
      <div className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full py-1.5 pl-4 pr-1.5 text-[12.5px]"
        style={{ background: "var(--surface-card)", boxShadow: "var(--shadow-4)" }}>
        <span>{trx("Tour · step {0} of {1}", i + 1, tour.length)}</span>
        <Button size="sm" variant="primary" onClick={() => {
          setPaused(false);
          try { sessionStorage.removeItem(PAUSED); } catch { /* geen opslag */ }
        }}>{tr("Continue")}</Button>
        <Button size="sm" variant="ghost" onClick={close}>{tr("Stop")}</Button>
      </div>
    );
  }

  const ga = (n: number) => {
    setStep(n);
    setReaches((b) => Math.max(b, n));
    save(n);
  };

  // A page in the walk: on the page itself, pointing at it in the menu.
  if (here?.page && !onWelcome) {
    return (
      <TourSpotlight
        id={here.page.id}
        href={here.page.href}
        eyebrow={NAME.around}
        title={here.step.title}
        text={String(here.step.intro)}
        index={i}
        total={tour.length}
        onBack={() => ga(i - 1)}
        onNext={() => ga(i + 1)}
        onPause={() => pause(() => undefined)}
        last={i === tour.length - 1}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={tr("Tour")}>
      <div className="absolute inset-0" style={{ background: "rgba(20,18,14,0.36)" }} onClick={() => pause(() => undefined)} />
      <div className="relative flex max-h-[90dvh] w-full max-w-[480px] flex-col overflow-y-auto overscroll-contain rounded-xl p-6"
        style={{ background: "var(--surface-card)", boxShadow: "var(--shadow-4)" }}>
        <div className="mb-3 flex items-center justify-between">
          <span className="ds-eyebrow">
            {onWelcome ? tr("Welcome") : `${share_out.length > 1 ? tr("Part {0} of {1} · ", share_out.indexOf(here.part) + 1, share_out.length) : ""}${NAME[here.part]}`}
          </span>
          <IconButton label={tr("Pause")} onClick={() => (onWelcome ? close() : pause(() => undefined))}
            icon={<CloseIcon className="h-4 w-4" />} className="-mr-2 flex-none" />
        </div>

        {onWelcome ? (
          <>
            <h3 className="mb-1.5 font-display text-[21px] font-normal tracking-[-0.014em]">{tr("Welcome to {0}", APP.name)}</h3>
            <p className="mb-4 text-[13px] leading-relaxed text-ink-muted">
              {tr("Your net worth first: your bank accounts, spending and portfolio, all in one place. This short tour helps you bring in your data and shows you around.")}
            </p>
            <PageSketch kind="line" label={APP.name} />
            <div className="mt-4 flex items-center justify-between gap-2">
              <Button variant="ghost" className="-ml-3" onClick={close}>{tr("Skip the tour")}</Button>
              <Button variant="primary" onClick={() => ga(0)} iconAfter={<ChevronRightIcon className="h-3.5 w-3.5" />}>{tr("Start the tour")}</Button>
            </div>
          </>
        ) : (
          <>
            {/* De voortgang, per deel: bij allebei zie je waar Beleggingen ophoudt en Geldzaken begint. */}
            <div className="flex gap-3">
              {share_out.map((d, di) => (
                <div key={d} className="flex min-w-0 flex-1 flex-col gap-1">
                  {share_out.length > 1 && (
                    <span className="text-[10.5px] font-semibold uppercase tracking-wide"
                      style={{ color: here.part === d ? "var(--text-primary)" : "var(--text-faint)" }}>
                      {di + 1}. {NAME[d]}
                    </span>
                  )}
                  <div className="flex gap-1">
                    {tour.map((t, n) => t.part !== d ? null : (
                      <button key={n} type="button" disabled={n > Math.max(reaches, i)} onClick={() => ga(n)}
                        aria-label={tr("Step {0}{1}", n + 1, n > Math.max(reaches, i) ? tr(" (not available yet)") : "")}
                        className="h-1.5 flex-1 rounded-full disabled:cursor-not-allowed"
                        style={{ background: n <= i ? "var(--n-800)" : n <= reaches ? "var(--border-strong)" : "var(--surface-inset)" }} />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11.5px] text-ink-muted">{trx("Step {0} of {1}", i + 1, tour.length)}</span>
            </div>

            <StepContent step={here.step} />
            {here.action && (
              <div className="mb-3">
                <Button variant="secondary" onClick={here.action.run}>{here.action.label}</Button>
                <span className="ml-2 text-xs text-ink-muted">{tr("The tour will wait for you in the bottom right.")}</span>
              </div>
            )}

            <div className="mt-auto flex items-center justify-between gap-2 pt-1">
              <Button variant="ghost" className="-ml-3" onClick={() => ga(i - 1)}
                disabled={i === 0}
                icon={<ChevronLeftIcon className="h-3.5 w-3.5" />}>
                {tr("Previous")}
              </Button>
              {i < tour.length - 1 ? (
                <Button variant="primary" onClick={() => ga(i + 1)} disabled={here.needsBank && !bank} iconAfter={<ChevronRightIcon className="h-3.5 w-3.5" />}>{tr("Next")}</Button>
              ) : (
                <Button variant="primary" onClick={close}>{tr("Done")}</Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
