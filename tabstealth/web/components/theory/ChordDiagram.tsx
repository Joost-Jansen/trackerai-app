"use client";

// A chord box: strings upright (low E left), five frets, x for a muted string and o for an open one.

import type { Shape } from "@/lib/theory";

export default function ChordDiagram({ name, shape, caption, active, onClick }: { name: string; shape: Shape | null; caption?: string; active?: boolean; onClick?: () => void }) {
  const played = shape?.filter((f) => f > 0) ?? [];
  const lowest = played.length ? Math.min(...played) : 1;
  const base = played.length && Math.max(...played) > 5 ? lowest : 1; // the first fret drawn
  const x = (i: number) => 12 + i * 14;
  const y = (f: number) => 26 + (f - base + 0.5) * 16;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex flex-col items-center rounded-md border px-1.5 pb-1 pt-1.5 transition-colors ${active ? "border-brand bg-brand-tint" : "border-transparent hover:border-border"}`}
    >
      <span className="text-sm font-semibold">{name}</span>
      <svg viewBox="0 0 94 112" width={78} height={93} aria-hidden>
        {base > 1 && (
          <text x={2} y={y(base) + 4} fontSize={10} fill="var(--ink-muted)">
            {base}
          </text>
        )}
        <line x1={x(0)} x2={x(5)} y1={26} y2={26} stroke="currentColor" strokeWidth={base === 1 ? 3.5 : 1} />
        {[1, 2, 3, 4, 5].map((r) => (
          <line key={r} x1={x(0)} x2={x(5)} y1={26 + r * 16} y2={26 + r * 16} stroke="var(--ink-muted)" strokeWidth={0.8} />
        ))}
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <line key={i} x1={x(i)} x2={x(i)} y1={26} y2={106} stroke="var(--ink-muted)" strokeWidth={0.8} />
        ))}
        {shape?.map((f, i) =>
          f < 0 ? (
            <text key={i} x={x(i)} y={20} textAnchor="middle" fontSize={11} fill="var(--ink-muted)">
              ×
            </text>
          ) : f === 0 ? (
            <circle key={i} cx={x(i)} cy={16} r={3.5} fill="none" stroke="var(--ink-muted)" strokeWidth={1.2} />
          ) : (
            <circle key={i} cx={x(i)} cy={y(f)} r={5.5} fill="var(--brand-500)" />
          ),
        )}
      </svg>
      {caption && <span className="font-mono text-[11px] text-ink-muted">{caption}</span>}
    </button>
  );
}
