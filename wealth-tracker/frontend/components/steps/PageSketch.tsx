// A small drawing of a page of the app, for the tour: a browser frame with a
// sidebar and a stylised version of what the page shows. Bars stand in for
// text. Only the app's own colour tokens, so light and dark both work.

export type Kind =
  | "cards" | "table" | "line" | "calendar" | "donut" | "bars" | "budget"
  | "news" | "form" | "help" | "sidebar" | "upload" | "chat";

/** Which drawing fits which page (nav ids from lib/nav.ts). */
export const SKETCH_OF: Record<string, Kind> = {
  today: "cards",
  positions: "table",
  returns: "line",
  calendar: "calendar",
  allocation: "donut",
  dividend: "bars",
  news: "news",
  // wealth-tracker's portfolio items (one per question, the views as tabs).
  holdings: "table",
  performance: "line",
  agenda: "calendar",
  net_worth: "line",
  spending: "bars",
  budget: "budget",
  transactions: "table",
  labelling: "table",
  categories: "table",
  accounts: "table",
  settings: "form",
  help: "help",
};

const INK = "var(--text-faint)";
const RULE = "var(--rule)";
const CARD = "var(--surface-card)";
const A = "var(--chart-1)";
const B = "var(--chart-2)";
const C = "var(--chart-3)";

// The content area: x 78..308, y 30..170.
function Content({ kind }: { kind: Kind }) {
  switch (kind) {
    case "cards":
      return (
        <>
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={78 + i * 78} y={34} width={70} height={38} rx={6} fill={CARD} />
              <rect x={86 + i * 78} y={42} width={28} height={4} rx={2} fill={INK} />
              <rect x={86 + i * 78} y={54} width={44} height={8} rx={3} fill={i === 1 ? A : INK} opacity={i === 1 ? 1 : 0.7} />
            </g>
          ))}
          <rect x={78} y={80} width={226} height={86} rx={6} fill={CARD} />
          <path d="M88 150 L120 138 L150 142 L182 120 L214 126 L246 104 L292 96" fill="none" stroke={A} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    case "table":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <g key={i}>
              {i > 0 && <line x1={86} x2={296} y1={40 + i * 20} y2={40 + i * 20} stroke={RULE} />}
              <rect x={88} y={46 + i * 20} width={i === 0 ? 30 : 60 - (i % 3) * 10} height={5} rx={2.5} fill={INK} opacity={i === 0 ? 0.5 : 0.8} />
              <rect x={190} y={46 + i * 20} width={36} height={5} rx={2.5} fill={i === 0 ? INK : i % 2 ? A : B} opacity={i === 0 ? 0.5 : 0.9} />
              <rect x={258} y={46 + i * 20} width={30} height={5} rx={2.5} fill={INK} opacity={i === 0 ? 0.5 : 0.8} />
            </g>
          ))}
        </>
      );
    case "line":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          <rect x={88} y={44} width={60} height={8} rx={3} fill={INK} />
          {[80, 110, 140].map((y) => <line key={y} x1={88} x2={296} y1={y} y2={y} stroke={RULE} strokeDasharray="2 4" />)}
          <path d="M88 150 L118 142 L148 146 L178 128 L208 122 L238 106 L268 100 L296 84" fill="none" stroke={A} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
          <path d="M88 152 L118 148 L148 146 L178 140 L208 136 L238 128 L268 124 L296 116" fill="none" stroke={B} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" opacity={0.8} />
        </>
      );
    case "calendar":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          {Array.from({ length: 28 }, (_, i) => {
            const col = i % 7, row = Math.floor(i / 7);
            const on = [3, 10, 18, 23].includes(i);
            return <rect key={i} x={88 + col * 30} y={44 + row * 30} width={24} height={24} rx={5} fill={on ? A : RULE} opacity={on ? 1 : 0.6} />;
          })}
        </>
      );
    case "donut":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          <circle cx={140} cy={100} r={40} fill="none" stroke={A} strokeWidth={18} strokeDasharray="120 252" />
          <circle cx={140} cy={100} r={40} fill="none" stroke={B} strokeWidth={18} strokeDasharray="70 252" strokeDashoffset={-120} />
          <circle cx={140} cy={100} r={40} fill="none" stroke={C} strokeWidth={18} strokeDasharray="62 252" strokeDashoffset={-190} />
          {[A, B, C].map((c, i) => (
            <g key={i}>
              <rect x={206} y={74 + i * 20} width={10} height={10} rx={3} fill={c} />
              <rect x={222} y={77 + i * 20} width={56 - i * 8} height={5} rx={2.5} fill={INK} />
            </g>
          ))}
        </>
      );
    case "bars":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          {[40, 62, 50, 78, 58, 90, 70, 84].map((h, i) => (
            <rect key={i} x={92 + i * 26} y={156 - h} width={16} height={h} rx={4} fill={i === 7 ? A : B} opacity={i === 7 ? 1 : 0.55} />
          ))}
        </>
      );
    case "budget":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          {[0.8, 0.45, 1, 0.6].map((f, i) => (
            <g key={i}>
              <rect x={88} y={46 + i * 30} width={50} height={5} rx={2.5} fill={INK} />
              <rect x={88} y={56 + i * 30} width={206} height={8} rx={4} fill={RULE} />
              <rect x={88} y={56 + i * 30} width={206 * f} height={8} rx={4} fill={f >= 1 ? "var(--text-loss)" : A} />
            </g>
          ))}
        </>
      );
    case "news":
      return (
        <>
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={78} y={34 + i * 45} width={226} height={38} rx={6} fill={CARD} />
              <rect x={86} y={41 + i * 45} width={36} height={24} rx={4} fill={i === 0 ? A : B} opacity={0.6} />
              <rect x={132} y={45 + i * 45} width={120 - i * 20} height={5} rx={2.5} fill={INK} />
              <rect x={132} y={56 + i * 45} width={80} height={4} rx={2} fill={INK} opacity={0.5} />
            </g>
          ))}
        </>
      );
    case "form":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={90} y={46 + i * 36} width={44} height={5} rx={2.5} fill={INK} />
              <rect x={90} y={56 + i * 36} width={150} height={16} rx={5} fill="none" stroke={RULE} strokeWidth={1.5} />
            </g>
          ))}
          <rect x={250} y={146} width={44} height={14} rx={5} fill={A} />
        </>
      );
    case "help":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          <circle cx={120} cy={82} r={24} fill="none" stroke={A} strokeWidth={4} />
          <text x={120} y={92} textAnchor="middle" fontSize={28} fontWeight={600} fill={A}>?</text>
          {[0, 1, 2, 3].map((i) => <rect key={i} x={160} y={64 + i * 12} width={120 - (i % 2) * 30} height={5} rx={2.5} fill={INK} />)}
          {[0, 1].map((i) => <rect key={i} x={90} y={128 + i * 14} width={190 - i * 50} height={5} rx={2.5} fill={INK} opacity={0.6} />)}
        </>
      );
    case "upload":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          <rect x={120} y={56} width={142} height={84} rx={10} fill="none" stroke={A} strokeWidth={2} strokeDasharray="6 5" />
          <path d="M191 112 V80 M179 92 L191 80 L203 92" fill="none" stroke={A} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
          <rect x={160} y={122} width={62} height={5} rx={2.5} fill={INK} />
        </>
      );
    case "chat":
      return (
        <>
          <rect x={78} y={34} width={226} height={132} rx={6} fill={CARD} />
          <rect x={150} y={44} width={144} height={22} rx={11} fill={RULE} />
          <rect x={160} y={52} width={96} height={5} rx={2.5} fill={INK} />
          <rect x={88} y={76} width={170} height={44} rx={11} fill={A} opacity={0.18} />
          <rect x={98} y={86} width={130} height={5} rx={2.5} fill={A} />
          <rect x={98} y={98} width={100} height={5} rx={2.5} fill={A} opacity={0.7} />
          {[0, 1, 2, 3].map((i) => <rect key={i} x={98 + i * 14} y={108} width={8} height={4 + i * 3} rx={1.5} fill={A} opacity={0.6} transform={`translate(0 ${-i * 3})`} />)}
          <rect x={88} y={136} width={206} height={20} rx={10} fill="none" stroke={RULE} strokeWidth={1.5} />
        </>
      );
    case "sidebar":
    default:
      return (
        <>
          {[0, 1].map((i) => (
            <rect key={i} x={78 + i * 116} y={34} width={110} height={60} rx={6} fill={CARD} />
          ))}
          <rect x={78} y={102} width={226} height={64} rx={6} fill={CARD} />
        </>
      );
  }
}

export default function PageSketch({ kind, label }: { kind: Kind; label?: string }) {
  const nav = kind === "sidebar";
  return (
    <svg viewBox="0 0 320 180" className="block h-auto w-full rounded-lg" role="img" aria-label={label}
      style={{ background: "var(--surface-inset)" }}>
      {/* Browser frame */}
      <rect x={6} y={6} width={308} height={168} rx={10} fill="var(--surface-page)" stroke={RULE} />
      {[0, 1, 2].map((i) => <circle key={i} cx={18 + i * 9} cy={17} r={2.6} fill={INK} opacity={0.6} />)}
      <line x1={6} x2={314} y1={26} y2={26} stroke={RULE} />
      {/* Sidebar: a few menu bars, the active one highlighted */}
      <rect x={6} y={26} width={62} height={148} fill="var(--surface-sunken)" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect key={i} x={14} y={38 + i * 18} width={nav ? 46 : 40 - (i % 3) * 6} height={nav && i < 6 ? 7 : 5} rx={3}
          fill={i === 1 ? A : INK} opacity={i === 1 ? 1 : nav ? 0.8 : 0.5} />
      ))}
      <Content kind={kind} />
    </svg>
  );
}
