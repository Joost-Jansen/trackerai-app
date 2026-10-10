"use client";

// The step-by-step plan: one step at a time, with an image, a short explanation
// and what to watch out for, and Previous/Next. The same shape everywhere the app
// explains how to do something — in Help, in the first-time tour and behind "How
// do I export this?" in Update — so explanations look the same everywhere and
// are written once.
//
// A plan can have several routes: computer or phone (DeGiro), ING or bunq. Which
// one you see is a visible choice above the step, because the image and half the
// text depend on it.
//
// The images are redrawings with fixed light colours, not screenshots: they do
// not go out of date pixel by pixel and show no real data.

import { useEffect, useState } from "react";
import { Button, IconButton, Tabs } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "@trackerai/ui/icons";
import { tr, trx } from "@/lib/i18n";

export type Step = {
  title: string;
  intro: React.ReactNode;
  bullets: React.ReactNode[];
  visual?: React.ReactNode;
};

export type Route = { id: string; label: string; steps: Step[] };

/** One step: title, explanation, image and points of attention. */
export function StepContent({ step }: { step: Step }) {
  return (
    <>
      <h3 className="mb-1.5 mt-4 font-display text-[21px] font-normal tracking-[-0.014em]">{step.title}</h3>
      <p className="mb-3 text-[13px] leading-relaxed text-ink-muted">{step.intro}</p>
      {step.visual && <div className="mb-3">{step.visual}</div>}
      {step.bullets.length > 0 && (
        <ul className="mb-4 space-y-1.5">
          {step.bullets.map((b, i) => (
            <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed">
              <span className="mt-[7px] h-1 w-1 flex-none rounded-full" style={{ background: "var(--text-faint)" }} />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** The progress: a dash per step, filled up to and including where you are. */
export function Progress({ count, current }: { count: number; current: number }) {
  return (
    <div className="mb-1 flex gap-1">
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="h-1 flex-1 rounded-full"
          style={{ background: i <= current ? "var(--n-800)" : "var(--surface-inset)" }} />
      ))}
    </div>
  );
}

export function StepPlan({ routes, begin, chooseLabel = tr("I'm doing this on:"), phone, done }: {
  routes: Route[];
  /** The route the plan opens with. */
  begin?: string;
  chooseLabel?: string;
  /** This route opens on a device with a touch screen. */
  phone?: string;
  /** A button after the last step, such as "Go to Update". */
  done?: { label: string; onClick: () => void };
}) {
  const [routeId, setRouteId] = useState(begin ?? routes[0].id);
  const [step, setStep] = useState(0);
  // Guessed, not decided: a coarse pointer is usually a phone. The switch makes a
  // wrong guess free. After loading, so the server and the first render show the
  // same.
  useEffect(() => {
    if (!begin && phone && window.matchMedia("(pointer: coarse)").matches) setRouteId(phone);
  }, [begin, phone]);

  const route = routes.find((r) => r.id === routeId) ?? routes[0];
  const current = Math.min(step, route.steps.length - 1);
  const last = current === route.steps.length - 1;

  return (
    <div className="flex flex-col">
      <Progress count={route.steps.length} current={current} />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="ds-eyebrow">{trx("Step {0} of {1}", current + 1, route.steps.length)}</span>
        {routes.length > 1 && (
          <span className="flex items-center gap-2">
            <span className="text-[11.5px] text-ink-muted">{chooseLabel}</span>
            <Tabs variant="segmented" ariaLabel={chooseLabel} items={routes.map((r) => ({ id: r.id, label: r.label }))}
              value={route.id} onChange={(v) => {
                setRouteId(v);
                // The routes are not equally long; stay within range.
                setStep((s) => Math.min(s, (routes.find((r) => r.id === v)?.steps.length ?? 1) - 1));
              }} />
          </span>
        )}
      </div>
      <StepContent step={route.steps[current]} />
      {/* Knoppen van ruim formaat: iemand tikt ze vier keer achter elkaar aan op een telefoon. */}
      <div className="flex items-center justify-end gap-2 pt-1">
        {current > 0 && (
          <Button onClick={() => setStep(current - 1)} icon={<ChevronLeftIcon className="h-3.5 w-3.5" />}>{tr("Previous")}</Button>
        )}
        {!last ? (
          <Button variant="primary" onClick={() => setStep(current + 1)} iconAfter={<ChevronRightIcon className="h-3.5 w-3.5" />}>{tr("Next")}</Button>
        ) : done && (
          <Button variant="primary" onClick={done.onClick}>{done.label}</Button>
        )}
      </div>
    </div>
  );
}

/** A step-by-step plan as a dialog, for example behind "How do I export this?". */
export function StepPlanDialog({ open, onClose, title, ...plan }: {
  open: boolean; onClose: () => void; title: string;
} & React.ComponentProps<typeof StepPlan>) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0" style={{ background: "rgba(20,18,14,0.36)" }} onClick={onClose} />
      {/* dvh, not vh: on a phone the buttons otherwise fell under the address bar. */}
      <div className="relative flex max-h-[90dvh] w-full max-w-[440px] flex-col overflow-y-auto overscroll-contain rounded-xl p-6"
        style={{ background: "var(--surface-card)", boxShadow: "var(--shadow-4)" }}>
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[13px] font-semibold">{title}</span>
          <IconButton label={tr("Close")} onClick={onClose} icon={<CloseIcon className="h-4 w-4" />} className="-mr-2 flex-none" />
        </div>
        <StepPlan {...plan} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Building blocks for the images
// ---------------------------------------------------------------------------

/** A browser window, with the address of the site you see redrawn. */
export function MockBrowser({ url, children }: { url: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-black/10 bg-white text-[#1a1a1a] shadow-sm">
      <div className="flex items-center gap-1.5 border-b border-black/10 bg-[#f5f6f8] px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-[#ff5f57]" />
        <span className="h-2 w-2 rounded-full bg-[#febc2e]" />
        <span className="h-2 w-2 rounded-full bg-[#28c840]" />
        <span className="ml-2 truncate text-[10px] text-black/40">{url}</span>
      </div>
      <div className="p-3 text-[11px]">{children}</div>
    </div>
  );
}

/** A phone screen. */
export function MockPhone({ title, colour = "#1a1a1a", children }: { title: string; colour?: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto w-[210px] overflow-hidden rounded-[22px] border-[5px] border-[#1a1a1a] bg-white text-[#1a1a1a] shadow-sm">
      <div className="px-3 py-2 text-[11px] font-semibold text-white" style={{ background: colour }}>{title}</div>
      <div className="flex flex-col gap-1.5 p-3 text-[10.5px]">{children}</div>
    </div>
  );
}

/** Where you need to look or click. */
export function Mark({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[4px] bg-[#fce97a]/70 px-1.5 py-0.5 ring-1 ring-[#e0b400]">{children}</span>;
}

/** An input field in a redrawn form. */
export function MockField({ label, value, mark = false }: { label: string; value: React.ReactNode; mark?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9.5px] uppercase tracking-wide text-black/45">{label}</span>
      <span className={`truncate rounded border px-2 py-1 ${mark ? "border-[#e0b400] bg-[#fce97a]/40" : "border-black/15"}`}>{value}</span>
    </div>
  );
}

/** A button in a redrawn screen. */
export function MockButton({ children, mark = false, colour = "#1a1a1a" }: { children: React.ReactNode; mark?: boolean; colour?: string }) {
  return (
    <span className={`inline-block rounded px-2.5 py-1 text-[10.5px] font-semibold text-white ${mark ? "ring-2 ring-[#e0b400] ring-offset-1" : ""}`}
      style={{ background: colour }}>
      {children}
    </span>
  );
}
