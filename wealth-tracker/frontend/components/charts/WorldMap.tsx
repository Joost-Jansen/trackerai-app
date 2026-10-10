"use client";

// The world map next to the country bars on Allocation.
//
// What it is there for, and what not: a map is no tool for reading ratios — that
// is why the donut went and why there are bars here. Countries simply have an
// area that has nothing to do with your position: the Netherlands can be 16% of
// a portfolio and a pinprick on the map, Russia 0.0000015% and an eighth of the
// picture. The map therefore shows *where* something is, the bar next to it says
// how *much* — and they are tied together so you can point from one to the
// other.
//
// One colour, like every distribution in this design (slate blue, the same as
// the country bars), but in five steps darker. Stepped and not continuous
// because the distribution is extremely skewed: with the US at ~47% and the rest
// below 7% a linear scale would put everything except America on the same
// almost empty shade. The shades come from color-mix on --chart-5, so light and
// dark both work by themselves and no second colour definition arises that can
// drift.
//
// The geometry is in lib/worldGeo.ts and is made by scripts/build-world-map.mjs —
// projected ahead of time, so no map library ends up in the bundle.

import { useMemo, useRef, useState } from "react";
import { COUNTRIES, POINT_COUNTRIES, TINY, VIEWBOX } from "@/lib/worldGeo";
import { fmtEu, fmtEuro } from "@/lib/format";
import { localName } from "@/lib/slices";
import { tr, trx } from "@/lib/i18n";

/**
 * The steps, with their lower bound in percent. From large to small, because
 *  that is how it is walked. The bounds are round numbers you can say out loud
 *  ("more than a third", "between 1 and 5 percent") instead of quantiles of this
 *  one portfolio: for another user the same shade must mean the same.
 */
const TIERS = [
  { min: 35, mix: 100, label: "> 35%" },
  { min: 15, mix: 80, label: "15 – 35%" },
  { min: 5, mix: 62, label: "5 – 15%" },
  { min: 1, mix: 44, label: "1 – 5%" },
  // Not lower: in the dark theme the lightest step otherwise sinks into the
  // surface of the countries you hold *nothing* in, and then the map says nothing
  // there any more.
  { min: 0, mix: 27, label: "< 1%" },
];

/**
 * A step as a colour. Mixed into the paper the map lies on and not into white:
 *  on a ground lighter than the page the lightest step looks more like a light
 *  spot than a shade, and in the dark theme the series runs the other way by
 *  itself without a second colour definition.
 */
const tint = (mix: number) =>
  mix >= 100
    ? "var(--chart-5)"
    : `color-mix(in oklab, var(--chart-5) ${mix}%, var(--surface-page))`;

const tierOf = (pct: number) => TIERS.find((t) => pct >= t.min) ?? TIERS[TIERS.length - 1];

export type WorldMapProps = {
  /**
   * Every country you hold something in, with its share in percent. The full list,
   *  so including the tail that disappears into "Other" in the bar: that is
   *  exactly what the map adds. Names as the backend spells them (English).
   */
  slices: { name: string; pct: number }[];
  /**
   * The analysed equity value, to put an amount next to the percentage. 0 leaves
   *  the amount out.
   */
  analysedValue: number;
  /**
   * Which countries are lit up now. Comes from outside because the bars next to it
   *  drive and show the same selection.
   */
  active: Set<string>;
  /** Pointing. `null` = nothing pointed at any more. */
  onActive: (name: string | null) => void;
};

export default function WorldMap({ slices, analysedValue, active, onActive }: WorldMapProps) {
  const wrap = useRef<HTMLDivElement>(null);
  // Where the tooltip is, in pixels within the map area.
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  // What the tooltip says. Separate from `active`, because the bars also drive
  // `active` and then there is no mouse position: then no tooltip should appear.
  const [hovered, setHovered] = useState<string | null>(null);

  const owned = useMemo(
    () => new Map(slices.map((s) => [s.name, s.pct])),
    [slices],
  );

  // Countries too small to see or point at get a dot. Only if you hold something
  // there: a map strewn with dots on Andorra and Brunei says nothing, while the
  // Netherlands, Switzerland and Taiwan in particular must be findable.
  // POINT_COUNTRIES are the countries without a shape of their own at this scale
  // (Hong Kong, Singapore); those always need a dot.
  //
  // Sorted by ascending share, which on the map means: the largest position on
  // top. In the European cluster the Netherlands, Belgium and Luxembourg are
  // within five units of each other, so their pointing areas overlap anyway; then
  // a tap in that knot belongs to the country with the most money in it and not
  // to whoever happened to be last in the alphabet.
  const dots = useMemo(() => {
    const small = COUNTRIES.filter((c) => c.area < TINY && owned.has(c.name));
    const only = POINT_COUNTRIES.filter((p) => owned.has(p.name));
    return [...small, ...only]
      .map((c) => ({ name: c.name, c: c.c, pct: owned.get(c.name) ?? 0 }))
      .sort((a, b) => a.pct - b.pct);
  }, [owned]);

  const tip = hovered
    ? {
        name: localName(hovered),
        pct: owned.get(hovered),
      }
    : null;

  // Point, do not toggle. A toggle is broken on a phone: there an element first
  // gets focus and only then the click, and the click then sees "was already on"
  // and turns it off again — so nothing happens.
  const point = (name: string | null, e?: React.PointerEvent) => {
    setHovered(name);
    onActive(name);
    if (e && wrap.current) {
      const box = wrap.current.getBoundingClientRect();
      setAt({ x: e.clientX - box.left, y: e.clientY - box.top });
    }
  };

  const clear = () => {
    setHovered(null);
    setAt(null);
    onActive(null);
  };

  const fillOf = (name: string) => {
    const pct = owned.get(name);
    if (pct === undefined) return "var(--surface-inset)";
    return tint(tierOf(pct).mix);
  };

  return (
    <div className="flex flex-col gap-2.5">
      {/* Only the mouse lets go by moving away. A finger doesn't: when it lifts, the browser
          removes the pointer and fires pointerleave, so with a bare onPointerLeave every tap was
          undone at once and the map did exactly nothing on a phone. Letting go there happens by
          tapping next to a country (the ocean below) or by pointing at something else.
          pointercancel is the third case: then the tap has become a swipe and the page scrolls —
          then nothing should stay selected. */}
      <div
        ref={wrap}
        className="relative"
        onPointerLeave={(e) => e.pointerType === "mouse" && clear()}
        onPointerCancel={clear}
      >
        <svg
          viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
          className="block w-full"
          role="img"
          // The map repeats what the bars next to it already list. For a screen reader
          // that list is the usable form, so that is what it gets: here only what the map
          // *adds*, and otherwise no 175 paths to tab through.
          aria-label={tr("World map: the {0} countries where you have positions, darker as the share is larger. The same figures are in the list next to it.", slices.length)}
        >
          {/* The ocean. Also catches dismissing on a phone: tap next to a country and the map lets
              go. */}
          <rect
            x={0}
            y={0}
            width={VIEWBOX.width}
            height={VIEWBOX.height}
            fill="transparent"
            onPointerDown={clear}
          />
          {COUNTRIES.map((c) => (
            <path
              key={c.name}
              d={c.d}
              fill={fillOf(c.name)}
              stroke="var(--surface-card)"
              strokeWidth={0.5}
              fillRule="evenodd"
              onPointerEnter={(e) => point(c.name, e)}
              onPointerDown={(e) => point(c.name, e)}
              onPointerMove={(e) => point(c.name, e)}
            />
          ))}

          {/* The dots for the small countries. Above the areas, because they often sit on their own
              country. The invisible circle around them is the touch area: on a phone the visible
              dot of 4 units is about two pixels, and you never hit that. */}
          {dots.map((d) => (
            <g
              key={`dot-${d.name}`}
              onPointerEnter={(e) => point(d.name, e)}
              onPointerDown={(e) => point(d.name, e)}
              onPointerMove={(e) => point(d.name, e)}
            >
              <circle cx={d.c[0]} cy={d.c[1]} r={10} fill="transparent" />
              {/* Border in the paper colour and not in the text colour: a dark ring around each dot
                  turned the European cluster into eight black circles that spoke louder than the
                  countries themselves. The paper border only does what it is there for — separating
                  the dot from the country below — and the dark border is reserved for what you
                  point at. */}
              <circle
                cx={d.c[0]}
                cy={d.c[1]}
                r={4.5}
                fill={fillOf(d.name)}
                stroke={active.has(d.name) ? "var(--text-primary)" : "var(--surface-page)"}
                strokeWidth={active.has(d.name) ? 1.8 : 1}
              />
            </g>
          ))}

          {/* The outline of what you point at, separate and drawn last: as an outline on the
              country itself it would half disappear under the neighbouring countries (the
              Netherlands lies under Germany in the drawing order). Takes no part in pointing,
              otherwise the border would shield its own country. */}
          <g fill="none" stroke="var(--text-primary)" strokeWidth={1.6} pointerEvents="none">
            {COUNTRIES.filter((c) => active.has(c.name)).map((c) => (
              <path key={`on-${c.name}`} d={c.d} fillRule="evenodd" />
            ))}
          </g>
        </svg>

        {tip && at && (
          // Moving with the mouse, but clamped within the map: at phone width it otherwise
          // shot out on the right and the page became sideways scrollable.
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded border px-2 py-1 text-[11px] leading-tight shadow-sm"
            style={{
              left: `clamp(64px, ${at.x}px, calc(100% - 64px))`,
              top: Math.max(at.y - 8, 26),
              background: "var(--surface-card)",
              borderColor: "var(--border-hairline)",
            }}
          >
            <span className="font-semibold text-text">{tip.name}</span>
            {tip.pct === undefined ? (
              <span className="text-ink-muted">{" "}{tr("(no position)")}</span>
            ) : (
              <>
                <span className="num ml-1.5">
                  {/* The backend rounds to two decimals, so a position of a few cents arrives here
                      as 0. "0,00%" reads as an error; it is in the list, so it really is there. */}
                  {tip.pct < 0.005
                    ? "< 0,01%"
                    : fmtEu(tip.pct, { decimals: tip.pct < 1 ? 2 : 1, suffix: "%" })}
                </span>
                {/* The amount only when there is an amount to name: for a position of a few cents
                    it said "€ 0,00" next to "< 0,01%", and two zeros side by side read as broken
                    instead of small. */}
                {analysedValue > 0 && (tip.pct / 100) * analysedValue >= 0.5 && (
                  <span className="num ml-1.5 text-ink-muted">
                    {fmtEuro((tip.pct / 100) * analysedValue)}
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* The scale. No legend to link categories to colours — there are none, it is one colour —
          but the translation from shade to percentage, and a map can't do without that. */}
      {/* 11px is the lower limit in this design; anything below it can no longer be read on a
          phone. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-muted">
        {[...TIERS].reverse().map((t) => (
          <span key={t.label} className="flex items-center gap-1">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 flex-none rounded-[2px]"
              style={{ background: tint(t.mix) }}
            />
            <span className="num">{t.label}</span>
          </span>
        ))}
        <span className="flex items-center gap-1">{trx("{0}no position", <span
            aria-hidden="true"
            className="h-2.5 w-2.5 flex-none rounded-[2px]"
            style={{ background: "var(--surface-inset)" }}
          />)}</span>
      </div>
    </div>
  );
}
