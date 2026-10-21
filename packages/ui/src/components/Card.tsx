// The card: title on the left, optionally an action or a
// "more →" link on the right, content below.
//
// Used to be a local copy in both app/(app)/dashboard/page.tsx and
// app/(app)/news/page.tsx. With the third page (Rebalancing) that is one copy
// too many: then the padding or the title size shifts in one place and not in
// the other.

import Link from "next/link";

export default function Card({
  title,
  more,
  moreHref,
  action,
  children,
  className = "",
}: {
  title?: string;
  more?: string;
  moreHref?: string;
  /** Gets the spot to the right of the title; goes before `more`/`moreHref`. */
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded border border-border bg-surface p-4 sm:p-[18px] ${className}`}>
      {(title || action || (more && moreHref)) && (
        // flex-wrap so an action that is too wide next to the title drops below it
        // instead of squeezing it — the period bar of the Value development card is
        // seven buttons and never fits next to the title on a phone.
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-x-2.5 gap-y-2.5">
          {title && <h2 className="text-[13.5px] font-semibold tracking-[0.01em]">{title}</h2>}
          {action ??
            (more && moreHref && (
              <Link
                href={moreHref}
                // py-1 with a compensating -my-1: a line of 12px text is a touch target 15px
                // high, and that is not one. The negative margin keeps the header height
                // exactly as the design has it.
                className="-my-1 inline-block whitespace-nowrap py-1 text-xs font-semibold text-brand hover:underline"
              >
                {more} →
              </Link>
            ))}
        </div>
      )}
      {children}
    </section>
  );
}

/** The small small-caps label above a large number. */
export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-muted">{children}</span>;
}
