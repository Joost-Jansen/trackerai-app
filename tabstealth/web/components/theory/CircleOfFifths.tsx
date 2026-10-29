"use client";

// The circle of fifths: major keys outside, their relative minors inside, sharps and flats at the rim. Click a key to
// make it the page's key.

import { CIRCLE } from "@/lib/theory";

// server and browser can differ in the last digit of sin/cos: round, or React sees a different page
const round = (v: number) => Math.round(v * 100) / 100;

export default function CircleOfFifths({
  root,
  minor,
  onSelect,
  ariaLabel,
}: {
  root: number;
  minor: boolean;
  onSelect: (root: number, minor: boolean) => void;
  ariaLabel: string;
}) {
  const c = 150;
  const seg = (i: number, r0: number, r1: number) => {
    const a0 = ((i - 0.5) * 30 - 90) * (Math.PI / 180);
    const a1 = ((i + 0.5) * 30 - 90) * (Math.PI / 180);
    const p = (r: number, a: number) => `${round(c + r * Math.cos(a))},${round(c + r * Math.sin(a))}`;
    return `M${p(r0, a0)} L${p(r1, a0)} A${r1},${r1} 0 0 1 ${p(r1, a1)} L${p(r0, a1)} A${r0},${r0} 0 0 0 ${p(r0, a0)} Z`;
  };
  const at = (i: number, r: number) => {
    const a = (i * 30 - 90) * (Math.PI / 180);
    return { x: round(c + r * Math.cos(a)), y: round(c + r * Math.sin(a)) };
  };
  return (
    <svg viewBox="0 0 300 300" className="mx-auto w-full max-w-[320px]" role="img" aria-label={ariaLabel}>
      {CIRCLE.map((k, i) => {
        const minorRoot = (k.root + 9) % 12;
        const selMajor = !minor && k.root === root;
        const selMinor = minor && minorRoot === root;
        const o = at(i, 118);
        const n = at(i, 78);
        const acc = at(i, 143);
        return (
          <g key={k.name} className="cursor-pointer">
            <path
              d={seg(i, 98, 136)}
              fill={selMajor ? "var(--brand-500)" : "var(--surface-2)"}
              stroke="var(--surface)"
              strokeWidth={2}
              onClick={() => onSelect(k.root, false)}
            />
            <path
              d={seg(i, 58, 98)}
              fill={selMinor ? "var(--brand-500)" : "var(--brand-tint)"}
              stroke="var(--surface)"
              strokeWidth={2}
              onClick={() => onSelect(minorRoot, true)}
            />
            <text
              x={o.x}
              y={o.y + 5}
              textAnchor="middle"
              fontSize={15}
              fontWeight={600}
              fill={selMajor ? "#fff" : "currentColor"}
              pointerEvents="none"
            >
              {k.name}
            </text>
            <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={11} fill={selMinor ? "#fff" : "currentColor"} pointerEvents="none">
              {k.minor}
            </text>
            <text x={acc.x} y={acc.y + 3} textAnchor="middle" fontSize={8.5} fill="var(--ink-muted)" pointerEvents="none">
              {k.accidentals === 0 ? "" : k.accidentals > 0 ? `${k.accidentals}♯` : `${-k.accidentals}♭`}
            </text>
          </g>
        );
      })}
      <circle cx={c} cy={c} r={54} fill="var(--surface)" />
      <text x={c} y={c + 6} textAnchor="middle" fontSize={22} fill="var(--ink-muted)">
        ♪
      </text>
    </svg>
  );
}
