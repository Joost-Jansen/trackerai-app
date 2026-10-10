"use client";

// Cards side by side without empty space inside them and with both columns ending level. A grid row is as tall as its
// tallest card, so a card with little to say (one sport, a short text) used to be stretched and stand half empty next
// to a long one. Here each side is a column of its own: on a wide screen two independent stacks, every card as tall as
// its content. Below lg one column, in reading order: left 1, right 1, left 2, right 2 ... (`display: contents` lets
// the cards of both sides share one flex column, where `order` interleaves them).
//
// Level bottoms: an optional `filler`, a card that can show more or less (a list), goes under the shorter column and
// takes the height that is left, so both columns end at the same line; the last card of each column stretches the
// last few pixels. On a phone the filler comes last.
//
//   <Columns left={[<Readiness />, <Plan />]} right={[<Load />, <Upcoming />]} filler={<Recent fill />} />
//
// Leave out a card with null or false; with one side empty the other takes the full width.

import { useLayoutEffect, useRef, useState } from "react";

type Node = React.ReactNode;
const WIDE = "(min-width: 1024px)"; // Tailwind's lg
const GAP = 16; // gap-4

/** A column's height as its cards' content needs it: up to where each card's last child ends, so stretching the last
 *  card (or the filler) never feeds back into the choice of column. */
function natural(block: HTMLElement): number {
  let total = 0;
  Array.from(block.children).forEach((wrapper, i) => {
    const card = wrapper.firstElementChild as HTMLElement | null;
    if (!card) return;
    const last = card.lastElementChild as HTMLElement | null;
    const cs = getComputedStyle(card);
    const h = last
      ? last.getBoundingClientRect().bottom - card.getBoundingClientRect().top + parseFloat(cs.paddingBottom) + parseFloat(cs.borderBottomWidth)
      : card.offsetHeight;
    total += h + (i ? GAP : 0);
  });
  return total;
}

export default function Columns({
  left,
  right,
  filler,
  template = "lg:grid-cols-[1.25fr_1fr]",
  className = "",
}: {
  left: Node[];
  right: Node[];
  /** Goes under the shorter column and fills it (e.g. a list that shows as many rows as fit). */
  filler?: Node;
  template?: string;
  className?: string;
}) {
  const l = left.filter((n) => n != null && n !== false);
  const r = right.filter((n) => n != null && n !== false);
  const both = l.length > 0 && r.length > 0;
  const refs = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const [short, setShort] = useState<0 | 1>(0);

  // Which column is shorter without the filler; measured again whenever a card changes height.
  useLayoutEffect(() => {
    if (!filler || !both) return;
    const measure = () => {
      if (!window.matchMedia(WIDE).matches || !refs[0].current || !refs[1].current) return;
      const [a, b] = [natural(refs[0].current), natural(refs[1].current)];
      if (Math.abs(a - b) > 8) setShort(a < b ? 0 : 1); // a few pixels either way: keep the current side
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    refs.forEach((x) => x.current && ro.observe(x.current));
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filler, both]);

  const side = (items: Node[], offset: 0 | 1) => {
    const withFiller = !!filler && both && short === offset;
    return (
      <div className="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-4">
        {/* The fixed cards; without the filler the block (and its last card) stretches to the column's end. */}
        <div ref={refs[offset]} className={`contents lg:flex lg:flex-col lg:gap-4 ${withFiller ? "" : "lg:flex-1"}`}>
          {items.map((n, i) => (
            <div
              key={i}
              className={`min-w-0 ${i === items.length - 1 && !withFiller ? "lg:flex lg:flex-1 lg:flex-col lg:[&>*]:flex-1" : ""}`}
              style={{ order: both ? i * 2 + offset : i }}
            >
              {n}
            </div>
          ))}
        </div>
        {withFiller && (
          // Takes the height that is left; its content is laid over it (absolute) so it never makes the column taller.
          <div className="relative min-w-0 lg:min-h-[8.5rem] lg:flex-1" style={{ order: 9999 }}>
            <div className="lg:absolute lg:inset-0 lg:flex lg:flex-col lg:[&>*]:flex-1">{filler}</div>
          </div>
        )}
      </div>
    );
  };
  return (
    <div className={`flex flex-col gap-4 ${both ? `lg:grid ${template}` : ""} ${className}`}>
      {side(l, 0)}
      {side(r, 1)}
      {filler && !both && <div style={{ order: 9999 }}>{filler}</div>}
    </div>
  );
}
