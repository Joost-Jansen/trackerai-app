// Small cartoon sketches of the site for the setup steps of the tour: a browser window with a stylised version of a
// page. Inline SVG with the theme's own tokens, so light and dark mode both work; placeholder bars instead of text, so
// there is nothing to translate. Decorative only (aria-hidden): the step's own title and text say what the page is for.

import type { StepId } from "@/lib/onboarding";

export type SketchId = Exclude<StepId, "explore" | "goals" | "plan"> | "goals-plan";

const LINE = "var(--border-strong)";
const SOFT = "var(--surface-inset)";
const CARD = "var(--surface-card)";
const BRAND = "var(--brand)";
const POS = "var(--pos)";

/** A rounded placeholder bar for a line of text. */
function Bar({ x, y, w, h = 5, fill = LINE }: { x: number; y: number; w: number; h?: number; fill?: string }) {
  return <rect x={x} y={y} width={w} height={h} rx={h / 2} fill={fill} />;
}

/** A small card inside the page. */
function Box({ x, y, w, h, fill = CARD }: { x: number; y: number; w: number; h: number; fill?: string }) {
  return <rect x={x} y={y} width={w} height={h} rx={6} fill={fill} stroke="var(--border)" />;
}

function Tick({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <circle cx={x} cy={y} r={5} fill={POS} />
      <path d={`M${x - 2.4} ${y} l1.7 1.8 l3.2 -3.4`} fill="none" stroke={CARD} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
    </g>
  );
}

function Field({ x, y, w }: { x: number; y: number; w: number }) {
  return (
    <g>
      <Bar x={x} y={y} w={w * 0.35} h={4} />
      <rect x={x} y={y + 7} width={w} height={12} rx={4} fill={CARD} stroke="var(--border)" />
    </g>
  );
}

// The page content, drawn in a 288 x 100 area (x 16..304, y 30..130).
const PAGES: Record<SketchId, React.ReactNode> = {
  garmin: (
    <g>
      {/* a watch, an arrow, a login card */}
      <rect x={58} y={52} width={14} height={56} rx={5} fill={SOFT} stroke="var(--border)" />
      <circle cx={65} cy={80} r={16} fill={CARD} stroke={LINE} strokeWidth={2} />
      <path d="M65 71 v9 l6 4" fill="none" stroke={BRAND} strokeWidth={2} strokeLinecap="round" />
      <path d="M100 80 h40 m-7 -6 l7 6 l-7 6" fill="none" stroke={LINE} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <Box x={160} y={42} w={110} h={78} />
      <Field x={172} y={50} w={86} />
      <Field x={172} y={74} w={86} />
      <rect x={172} y={100} width={42} height={12} rx={6} fill={BRAND} />
    </g>
  ),
  sync: (
    <g>
      <circle cx={52} cy={62} r={16} fill={CARD} stroke="var(--border)" />
      <path d="M44 60 a8 8 0 0 1 14 -4 m0 -5 v5 h-5 M60 64 a8 8 0 0 1 -14 4 m0 5 v-5 h5" fill="none" stroke={BRAND} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
      <rect x={30} y={96} width={46} height={7} rx={3.5} fill={SOFT} />
      <rect x={30} y={96} width={30} height={7} rx={3.5} fill={BRAND} />
      {[0, 1, 2, 3].map((r) => (
        <g key={r} opacity={r === 3 ? 0.4 : 1}>
          <Box x={100} y={38 + r * 23} w={184} h={18} />
          <circle cx={112} cy={47 + r * 23} r={4} fill={`var(--chart-${r + 1})`} />
          <Bar x={122} y={44.5 + r * 23} w={70 - r * 8} />
          <Bar x={240} y={44.5 + r * 23} w={32} fill={SOFT} />
        </g>
      ))}
    </g>
  ),
  zones: (
    <g>
      {[1, 2, 3, 4, 5].map((z) => (
        <g key={z}>
          <Bar x={40} y={38 + (z - 1) * 18} w={30} h={6} />
          <rect x={82} y={35 + (z - 1) * 18} width={60 + z * 30} height={12} rx={4} fill={`var(--zone-${z})`} />
        </g>
      ))}
    </g>
  ),
  profile: (
    <g>
      <circle cx={70} cy={66} r={20} fill={SOFT} stroke="var(--border)" />
      <circle cx={70} cy={60} r={7} fill={LINE} />
      <path d="M57 78 a13 10 0 0 1 26 0" fill={LINE} />
      <Bar x={50} y={96} w={40} />
      <Field x={120} y={38} w={74} />
      <Field x={206} y={38} w={74} />
      <Field x={120} y={72} w={74} />
      <Field x={206} y={72} w={74} />
    </g>
  ),
  agent: (
    <g>
      {/* a token key and a short chat */}
      <circle cx={52} cy={62} r={11} fill="none" stroke={BRAND} strokeWidth={3} />
      <path d="M63 62 h28 m-8 0 v8 m-8 -8 v6" fill="none" stroke={BRAND} strokeWidth={3} strokeLinecap="round" />
      <rect x={30} y={92} width={78} height={14} rx={5} fill={SOFT} stroke="var(--border)" />
      <Bar x={38} y={97} w={50} h={4} />
      <rect x={136} y={38} width={110} height={24} rx={10} fill={SOFT} />
      <Bar x={146} y={47} w={80} />
      <rect x={170} y={70} width={114} height={34} rx={10} fill="var(--brand-tint)" stroke="var(--border)" />
      <Bar x={180} y={78} w={90} />
      <Bar x={180} y={89} w={64} />
    </g>
  ),
  "goals-plan": (
    <g>
      <Box x={24} y={36} w={100} h={88} />
      <Bar x={34} y={46} w={50} h={6} fill={BRAND} />
      {[0, 1, 2, 3].map((r) => <Bar key={r} x={34} y={62 + r * 13} w={[76, 60, 70, 44][r]} />)}
      <PlanGrid x={140} y={36} w={144} rows={3} />
    </g>
  ),
};

/** A plan as a little table: a week per row, sessions done, missed or still to come. */
function PlanGrid({ x, y, w, rows }: { x: number; y: number; w: number; rows: number }) {
  const cw = w / 7;
  const state = ["d", "", "d", "m", "d", "", "d", "d", "", "d", "d", "", "d", "", "p", "", "p", "p", "", "p", ""];
  return (
    <g>
      <rect x={x} y={y} width={w} height={rows * 28 + 4} rx={6} fill={CARD} stroke="var(--border)" />
      {Array.from({ length: rows * 7 }, (_, n) => {
        const s = state[n % state.length];
        const cx = x + (n % 7) * cw + 3;
        const cy = y + 4 + Math.floor(n / 7) * 28;
        const fill = s === "d" ? "var(--pos-tint)" : s === "m" ? "var(--neg-tint)" : s === "p" ? SOFT : "none";
        return (
          <g key={n}>
            <rect x={cx} y={cy} width={cw - 6} height={24} rx={4} fill={fill} />
            {s === "d" && <Tick x={cx + (cw - 6) / 2} y={cy + 12} />}
            {s === "p" && <Bar x={cx + 4} y={cy + 10} w={Math.max(4, cw - 14)} h={4} />}
          </g>
        );
      })}
    </g>
  );
}

/** A browser window with a sketch of the page. Scales with its container. */
export function Sketch({ id }: { id: SketchId }) {
  return (
    <div className="rounded-lg p-3" style={{ background: "var(--surface-inset)" }}>
      <svg viewBox="0 0 320 140" className="block h-auto w-full" aria-hidden focusable="false">
        <rect x={4} y={4} width={312} height={132} rx={10} fill={CARD} stroke="var(--border)" />
        <path d="M4 22 h312" stroke="var(--border)" />
        {[0, 1, 2].map((n) => <circle key={n} cx={16 + n * 10} cy={13} r={3} fill={LINE} />)}
        <rect x={60} y={8.5} width={140} height={9} rx={4.5} fill={SOFT} />
        {PAGES[id]}
      </svg>
    </div>
  );
}
