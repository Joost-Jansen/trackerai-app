"use client";

// A coach mark for the tour's walk past the pages: the real page is shown (the
// tour navigates there), its item in the sidebar gets a ring, and a small card
// sits next to that item, at its height. On a phone the sidebar is hidden, so
// the card docks at the bottom of the screen, still over the real page.

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient, type Query } from "@tanstack/react-query";
import { setExampleData } from "@/lib/api";
import { Button, IconButton, Tag } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from "@trackerai/ui/icons";
import { tr, trx } from "@/lib/i18n";

type Rect = { top: number; left: number; width: number; height: number; right: number };

/** The visible sidebar item for this page; the drawer's copy is hidden on a desktop. */
function anchorOf(id: string): Rect | null {
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(`[data-nav-id="${id}"]`))) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth) {
      return { top: r.top, left: r.left, width: r.width, height: r.height, right: r.right };
    }
  }
  return null;
}

export default function TourSpotlight({
  id,
  href,
  eyebrow,
  title,
  text,
  index,
  total,
  onBack,
  onNext,
  onPause,
  last,
}: {
  id: string;
  href: string;
  eyebrow: string;
  title: string;
  text: string;
  index: number;
  total: number;
  onBack: () => void;
  onNext: () => void;
  onPause: () => void;
  last: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [rect, setRect] = useState<Rect | null>(null);
  const qc = useQueryClient();

  // While the walk is on a page: the shared example account instead of an empty
  // new one. Everything cached is dropped on the way in and out, so example and
  // real figures never mix. The tour's own state and who you are stay real.
  useEffect(() => {
    const data = (q: Query) => !["onboarding", "me", "auth"].includes(String(q.queryKey[0]));
    const swap = (on: boolean) => {
      setExampleData(on);
      void qc.cancelQueries({ predicate: data }).then(() => qc.resetQueries({ predicate: data }));
    };
    swap(true);
    return () => swap(false);
  }, [qc]);

  // Show the page itself.
  useEffect(() => {
    if (pathname !== href) router.push(href);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [href]);

  // Follow the item: the page loads, the sidebar scrolls, the window resizes.
  useEffect(() => {
    const update = () => setRect(anchorOf(id));
    update();
    const t = window.setInterval(update, 250);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [id]);

  const card = (
    <>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span className="ds-eyebrow">{eyebrow}</span>
          <Tag>{tr("Example data")}</Tag>
        </span>
        <IconButton label={tr("Pause")} onClick={onPause} icon={<CloseIcon className="h-4 w-4" />} className="-mr-2 flex-none" />
      </div>
      <h3 className="mb-1 font-display text-[19px] font-normal tracking-[-0.014em]">{title}</h3>
      <p className="mb-3 text-[13px] leading-relaxed text-ink-muted">{text}</p>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-ink-muted">{trx("Step {0} of {1}", index + 1, total)}</span>
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={onBack} icon={<ChevronLeftIcon className="h-3.5 w-3.5" />}>
            {tr("Previous")}
          </Button>
          <Button size="sm" variant="primary" onClick={onNext} iconAfter={last ? undefined : <ChevronRightIcon className="h-3.5 w-3.5" />}>
            {tr("Next")}
          </Button>
        </span>
      </div>
    </>
  );

  const surface = { background: "var(--surface-card)", boxShadow: "var(--shadow-4)" } as const;

  if (!rect) {
    return (
      <div
        className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-[440px] rounded-xl p-4"
        style={surface}
        role="dialog"
        aria-label={tr("Tour")}
      >
        {card}
      </div>
    );
  }

  const width = 320;
  const top = Math.min(Math.max(rect.top + rect.height / 2 - 60, 12), window.innerHeight - 220);
  const arrowTop = rect.top + rect.height / 2 - top;
  return (
    <>
      {/* The ring around the item in the sidebar. */}
      <div
        aria-hidden
        className="pointer-events-none fixed z-50 rounded-lg transition-all duration-200"
        style={{
          top: rect.top - 3,
          left: rect.left - 3,
          width: rect.width + 6,
          height: rect.height + 6,
          boxShadow: "0 0 0 2px var(--chart-1), 0 0 0 6px color-mix(in srgb, var(--chart-1) 22%, transparent)",
        }}
      />
      <div
        className="fixed z-50 rounded-xl p-4 transition-all duration-200"
        role="dialog"
        aria-label={tr("Tour")}
        style={{ ...surface, top, left: rect.right + 16, width }}
      >
        <span
          aria-hidden
          className="absolute -left-1.5 h-3 w-3 rotate-45"
          style={{ top: Math.min(Math.max(arrowTop - 6, 14), 180), background: "var(--surface-card)" }}
        />
        {card}
      </div>
    </>
  );
}
