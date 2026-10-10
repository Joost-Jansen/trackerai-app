// Small sport glyphs in the same line style as components/icons.tsx (stroke 1.5, currentColor), and a round
// badge in the sport colour for the week cards.

import type { SVGProps } from "react";
import { useT } from "@/lib/i18n";
import { sportGroup, type SportGroup } from "@/lib/sports";
import { sportColour } from "./plan";

type P = SVGProps<SVGSVGElement>;

function Svg({ children, ...props }: P) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

/** One glyph per group of sports (lib/sports.ts); a sport without a group of its own gets "other". */
const GLYPH: Record<SportGroup, React.ReactNode> = {
  run: (
    <>
      <circle cx="14.5" cy="4.5" r="1.8" />
      <path d="M8 21l3.2-5.2 3 2.2v3.5" />
      <path d="M6.5 11.5l3-3.2h4l2.2 3.4 2.8 1" />
      <path d="M13.5 8.3l-2.3 7.5" />
    </>
  ),
  ride: (
    <>
      <circle cx="6" cy="16.5" r="3.6" />
      <circle cx="18" cy="16.5" r="3.6" />
      <path d="M6 16.5l3.6-7h5.2L18 16.5" />
      <path d="M9.6 9.5L12.5 16.5h-6.5" />
      <path d="M13.5 6.5h2.5" />
    </>
  ),
  swim: (
    <>
      <path d="M3 17c1.5 1.2 3 1.2 4.5 0s3-1.2 4.5 0 3 1.2 4.5 0 3-1.2 4.5 0" />
      <path d="M3 20.5c1.5 1.2 3 1.2 4.5 0s3-1.2 4.5 0 3 1.2 4.5 0 3-1.2 4.5 0" />
      <circle cx="16.5" cy="7" r="1.8" />
      <path d="M5 13.5l5-4.5 3 3 3-2" />
    </>
  ),
  walk: (
    <>
      <circle cx="12.5" cy="4.5" r="1.8" />
      <path d="M12 8.5l-1.5 6 2.5 2.5V21" />
      <path d="M10.5 14.5L8.5 21" />
      <path d="M8.5 12l3.5-3.5 2.5 3.5" />
    </>
  ),
  hike: (
    <>
      <circle cx="11" cy="4.5" r="1.8" />
      <path d="M10.5 8.5L9 14.5l2.5 2.5V21" />
      <path d="M9 14.5L7 21" />
      <path d="M7 12l3.5-3.5 3 3" />
      <path d="M17 9v12M15.5 9h2" />
    </>
  ),
  strength: <path d="M7 8v8M17 8v8M4 10v4M20 10v4M7 12h10" />,
  cardio: (
    <>
      <path d="M12 20s-7.5-4.5-7.5-10A4 4 0 0112 7.6 4 4 0 0119.5 10c0 5.5-7.5 10-7.5 10z" />
      <path d="M7 12.5h2.5l1.2-2.2 1.8 4.4 1.2-2.2H17" />
    </>
  ),
  mind: (
    <>
      <circle cx="12" cy="5" r="1.8" />
      <path d="M12 8v6" />
      <path d="M6.5 12.5L12 14l5.5-1.5" />
      <path d="M5 18.5c2.2-1.3 4.6-2 7-2s4.8.7 7 2" />
    </>
  ),
  row: (
    <>
      <path d="M5 19L16 8" />
      <path d="M15 5.5l3.5 3.5 2-2-3.5-3.5z" />
      <path d="M19 19L8 8" />
      <path d="M9 5.5L5.5 9l-2-2L7 3.5z" />
    </>
  ),
  climb: (
    <>
      <path d="M3 20l6.5-11 4 6.5 2.5-4 5 8.5z" />
      <path d="M9.5 9V4l3.5 1.5L9.5 7" />
    </>
  ),
  snow: (
    <>
      <path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9" />
      <path d="M9.5 4.5L12 6l2.5-1.5M9.5 19.5L12 18l2.5 1.5" />
    </>
  ),
  skate: (
    <>
      <path d="M6 5h4.5v6.5H17a3 3 0 013 3V16H6z" />
      <path d="M4 19.5h16" />
      <path d="M8 16v3.5M17 16v3.5" />
    </>
  ),
  paddle: (
    <>
      <path d="M3 15.5c3.5 2.5 14.5 2.5 18 0" />
      <path d="M6.5 20.5L17.5 5" />
      <path d="M16 3.5l3 2-1.5 2.3-3-2z" />
      <path d="M8 22l-3-2 1.5-2.3 3 2z" />
    </>
  ),
  water: (
    <>
      <path d="M12 3v12M12 3l6.5 11H12" />
      <path d="M3 18.5c1.5 1.2 3 1.2 4.5 0s3-1.2 4.5 0 3 1.2 4.5 0 3-1.2 4.5 0" />
    </>
  ),
  dive: (
    <>
      <path d="M3.5 9h17v4.5a2.5 2.5 0 01-2.5 2.5h-3l-3-2-3 2H6a2.5 2.5 0 01-2.5-2.5z" />
      <circle cx="17" cy="4.5" r="1.2" />
      <circle cx="20" cy="3" r="0.8" />
    </>
  ),
  racket: (
    <>
      <circle cx="10" cy="9.5" r="5.5" />
      <path d="M7.5 5v9M12.5 5v9M5 7.5h10M5 11.5h10" />
      <path d="M14 13.5l6 6.5" />
      <circle cx="18.5" cy="5" r="1.6" />
    </>
  ),
  team: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8l3.2 2.3-1.2 3.7h-4l-1.2-3.7z" />
      <path d="M12 8V3.5M15.2 10.3l4.3-1.4M14 14l2.7 3.6M10 14l-2.7 3.6M8.8 10.3L4.5 8.9" />
    </>
  ),
  golf: (
    <>
      <path d="M8 21V3.5l9 3.5-9 3.5" />
      <path d="M4.5 21h9" />
    </>
  ),
  combat: (
    <>
      <path d="M7 10a5 5 0 0110 0v3.5a3.5 3.5 0 01-3.5 3.5h-3A3.5 3.5 0 017 13.5z" />
      <path d="M9 17v3.5h6V17" />
      <path d="M7 12h3.5" />
    </>
  ),
  multisport: (
    <>
      <circle cx="5" cy="12" r="2.5" />
      <circle cx="12" cy="12" r="2.5" />
      <circle cx="19" cy="12" r="2.5" />
      <path d="M7.5 12h2M14.5 12h2" />
    </>
  ),
  motor: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="2" />
      <path d="M12 14v6.5M10 12H3.5M14 12h6.5" />
    </>
  ),
  air: <path d="M21 15.5l-8-4V5.5a1.5 1.5 0 00-3 0v6l-8 4v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-4.5l8 2.5z" />,
  outdoor: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.5" />
    </>
  ),
  wheelchair: (
    <>
      <circle cx="10" cy="4" r="1.8" />
      <path d="M10 7.5v5h5l2 6h2.5" />
      <path d="M14 15a5 5 0 11-6.5-4.8" />
    </>
  ),
  rest: <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" />,
  other: <circle cx="12" cy="12" r="5" />,
};

export function SportGlyph({ sport, ...props }: { sport: string } & P) {
  return <Svg {...props}>{GLYPH[sportGroup(sport)]}</Svg>;
}

/** Round badge: soft sport colour as the surface, the glyph in the full colour. */
export function SportBadge({ sport, size = 30 }: { sport: string; size?: number }) {
  const t = useT();
  const c = sportColour(sport);
  return (
    <span
      title={t.sport(sport)}
      className="inline-flex flex-none items-center justify-center rounded-full"
      style={{ width: size, height: size, background: `color-mix(in srgb, ${c} 18%, transparent)`, color: c }}
    >
      <SportGlyph sport={sport} width={size * 0.56} height={size * 0.56} />
    </span>
  );
}
