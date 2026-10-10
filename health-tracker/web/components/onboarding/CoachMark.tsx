"use client";

// One step of the walk past the pages, as a coach mark on the real page instead of a step in the modal.
//
// It opens the page itself, rings that page's item in the sidebar (found by its `data-nav-id`), dims the rest of the
// sidebar a little and puts a small popover next to the item, at its height. The page stays visible and undimmed.
// It follows scrolling and resizing. On a phone the sidebar is hidden (and stays closed): the popover then docks at the
// bottom of the screen, on top of the real page.
//
// A new account has no data yet, so while a coach mark is on screen the pages show the shared, read-only example
// account (lib/exampleData.ts), and the coach mark says so. Your own data comes back as soon as it closes: at the end
// of the walk, on a pause or on skip.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Tag } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon } from "@trackerai/ui/icons";
import { useExampleData } from "@/lib/exampleData";
import { useT } from "@/lib/i18n";

type Box = { top: number; left: number; width: number; height: number };

/** The same dim as the tour's modal, lighter: only over the sidebar. */
const DIM = "rgba(20,24,20,0.42)";
/** Space between the item and its ring, and between the sidebar and the popover. */
const RING = 3;
const GAP = 14;
const EDGE = 12;
const WIDTH = 300;

function toBox(r: DOMRect): Box {
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

/** The nav item on screen: on a wide screen the one in the sidebar; the closed drawer on a phone sits off screen. */
function findAnchor(id: string): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(`[data-nav-id="${id}"]`)) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth) return el;
  }
  return null;
}

export default function CoachMark({
  navId,
  href,
  title,
  text,
  index,
  total,
  onBack,
  onNext,
  onSkip,
  onPause,
}: {
  navId: string;
  href: string;
  title: string;
  text: React.ReactNode;
  /** 0-based position in the whole tour. */
  index: number;
  total: number;
  onBack: () => void;
  onNext: () => void;
  onSkip: () => void;
  onPause: () => void;
}) {
  const t = useT();
  const tr = t.onboarding.tour;
  const router = useRouter();
  const pathname = usePathname();
  const pop = useRef<HTMLDivElement>(null);
  const [item, setItem] = useState<Box | null>(null);
  const [rail, setRail] = useState<Box | null>(null);
  const [height, setHeight] = useState(0);

  useExampleData();

  // Open the page of this step (also after a reload or a pause), unless you are already somewhere on it.
  useEffect(() => {
    if (!pathname.startsWith(href)) router.push(href);
    // Only when the step changes: after that you may look around freely.
  }, [href]);

  // Where the item and the sidebar are, again after every scroll and resize.
  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = findAnchor(navId);
      const nav = el?.closest("nav");
      setItem(el ? toBox(el.getBoundingClientRect()) : null);
      setRail(nav ? toBox(nav.getBoundingClientRect()) : null);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    const ro = new ResizeObserver(schedule);
    ro.observe(document.documentElement);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [navId, pathname]);

  useLayoutEffect(() => {
    setHeight(pop.current?.offsetHeight ?? 0);
  }, [item, rail, title, text]);

  // Focus on Next, so the keyboard can walk on; Escape pauses the tour, like the close button of the modal.
  useEffect(() => {
    pop.current?.querySelector<HTMLButtonElement>("[data-coach-next]")?.focus({ preventScroll: true });
  }, [navId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onPause();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onPause]);

  const docked = !item || !rail;
  let style: React.CSSProperties;
  let arrow = 0;
  if (docked) {
    style = { left: EDGE, right: EDGE, bottom: `calc(${EDGE}px + env(safe-area-inset-bottom))` };
  } else {
    const vh = window.innerHeight;
    const centre = item.top + item.height / 2;
    const h = height || 180;
    const top = Math.max(EDGE, Math.min(centre - 28, vh - h - EDGE));
    arrow = Math.max(14, Math.min(centre - top, h - 14));
    style = { top, left: rail.left + rail.width + GAP, width: WIDTH, maxWidth: `calc(100vw - ${rail.left + rail.width + GAP + EDGE}px)` };
  }

  return (
    <>
      {!docked && (
        <div aria-hidden className="pointer-events-none fixed inset-0 z-40">
          {/* The rest of the sidebar a little darker: above, below and beside the item. */}
          <div className="absolute" style={{ background: DIM, left: rail.left, width: rail.width, top: rail.top, height: Math.max(0, item.top - RING - rail.top) }} />
          <div className="absolute" style={{ background: DIM, left: rail.left, width: rail.width, top: item.top + item.height + RING, bottom: 0 }} />
          <div className="absolute" style={{ background: DIM, left: rail.left, width: Math.max(0, item.left - RING - rail.left), top: item.top - RING, height: item.height + 2 * RING }} />
          <div className="absolute" style={{ background: DIM, left: item.left + item.width + RING, width: Math.max(0, rail.left + rail.width - item.left - item.width - RING), top: item.top - RING, height: item.height + 2 * RING }} />
          {/* The ring around the item. */}
          <div className="absolute rounded-lg" style={{
            left: item.left - RING, top: item.top - RING, width: item.width + 2 * RING, height: item.height + 2 * RING,
            boxShadow: "0 0 0 2px var(--brand-300)",
          }} />
        </div>
      )}
      <div ref={pop} role="dialog" aria-modal="false" aria-label={tr.aria} aria-describedby="coachmark-text"
        className={`fixed z-50 rounded-xl p-4 ${docked ? "mx-auto max-w-[420px]" : ""}`}
        style={{ ...style, background: "var(--surface-card)", boxShadow: "inset 0 0 0 1px var(--border-hairline), var(--shadow-4)" }}>
        {!docked && (
          // A small arrow pointing at the item.
          <span aria-hidden className="absolute h-3 w-3 rotate-45" style={{
            left: -6, top: arrow - 6, background: "var(--surface-card)",
            boxShadow: "-1px 1px 0 0 var(--border-hairline)",
          }} />
        )}
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11.5px] text-ink-muted">{tr.step(index + 1, total)}</span>
          <Button size="sm" variant="ghost" className="-mr-2" onClick={onSkip}>{tr.skip}</Button>
        </div>
        <div className="mb-1 mt-1 flex items-center justify-between gap-2">
          <h3 className="font-display text-[19px] font-normal tracking-[-0.014em]">{title}</h3>
          <Tag tone="brand" className="flex-none">{tr.example}</Tag>
        </div>
        <p id="coachmark-text" className="text-[13px] leading-relaxed text-ink-muted">{text}</p>
        <p className="mt-2 rounded-lg px-3 py-2 text-[12px] leading-relaxed" style={{ background: "var(--surface-inset)" }}>{tr.exampleNote}</p>
        <div className="mt-3 flex items-center justify-between gap-2">
          <Button size="sm" variant="ghost" className="-ml-2" onClick={onBack} icon={<ChevronLeftIcon className="h-3.5 w-3.5" />}>{tr.back}</Button>
          <Button data-coach-next size="sm" variant="primary" onClick={onNext} iconAfter={<ChevronRightIcon className="h-3.5 w-3.5" />}>{t.common.next}</Button>
        </div>
      </div>
    </>
  );
}
