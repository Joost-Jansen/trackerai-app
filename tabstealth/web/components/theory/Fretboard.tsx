"use client";

// The neck, drawn as a tab reads it: high e on top, low E at the bottom, the nut on the left. Dots are coloured by
// their role (root, third, fifth, seventh, other); a position window dims what lies outside it. Click a dot to hear it.

export type Role = "root" | "third" | "fifth" | "seventh" | "other";
export type NeckDot = { string: number; fret: number; label: string; role: Role; pitch: number };

const FILL: Record<Role, string> = {
  root: "var(--brand-500)",
  third: "var(--chart-3)",
  fifth: "var(--chart-4)",
  seventh: "var(--chart-5)",
  other: "var(--surface)",
};
const INLAYS = [3, 5, 7, 9, 15, 17, 19, 21];

export default function Fretboard({
  dots,
  frets = 15,
  window: win,
  highlight,
  onNote,
  ariaLabel,
}: {
  dots: NeckDot[];
  frets?: number;
  window?: { from: number; to: number } | null;
  /** The notes of a position ("string-fret"); the rest is dimmed. */
  highlight?: Set<string>;
  onNote?: (d: NeckDot) => void;
  ariaLabel: string;
}) {
  const left = 34; // room for the open strings, left of the nut
  const w = 52;
  const gap = 26;
  const top = 18;
  const width = left + frets * w + 10;
  const height = top + gap * 5 + 34;
  const x = (fret: number) => (fret === 0 ? left - 17 : left + (fret - 0.5) * w);
  const y = (string: number) => top + (string - 1) * gap;
  const shown = (d: NeckDot) => (highlight ? highlight.has(`${d.string}-${d.fret}`) : !win || (d.fret >= win.from && d.fret <= win.to));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[720px]" role="img" aria-label={ariaLabel}>
        {/* the window of the chosen position */}
        {win && (
          <rect
            x={win.from === 0 ? 0 : left + (win.from - 1) * w}
            y={top - 13}
            width={(win.to - Math.max(win.from, 1) + 1) * w + (win.from === 0 ? left : 0)}
            height={gap * 5 + 26}
            rx={8}
            fill="var(--brand-tint)"
          />
        )}
        {/* inlays */}
        {INLAYS.filter((f) => f <= frets).map((f) => (
          <circle key={f} cx={left + (f - 0.5) * w} cy={top + gap * 2.5} r={5} fill="var(--border-strong)" />
        ))}
        {[12, 24]
          .filter((f) => f <= frets)
          .map((f) => (
            <g key={f} fill="var(--border-strong)">
              <circle cx={left + (f - 0.5) * w} cy={top + gap * 1.5} r={5} />
              <circle cx={left + (f - 0.5) * w} cy={top + gap * 3.5} r={5} />
            </g>
          ))}
        {/* frets and the nut */}
        {Array.from({ length: frets + 1 }, (_, f) => (
          <line
            key={f}
            x1={left + f * w}
            x2={left + f * w}
            y1={top}
            y2={top + gap * 5}
            stroke="var(--ink-muted)"
            strokeWidth={f === 0 ? 4 : 1.2}
            opacity={f === 0 ? 0.9 : 0.5}
          />
        ))}
        {/* strings: thicker towards the low E */}
        {[1, 2, 3, 4, 5, 6].map((s) => (
          <line key={s} x1={left} x2={left + frets * w} y1={y(s)} y2={y(s)} stroke="var(--ink-muted)" strokeWidth={0.7 + (s - 1) * 0.3} />
        ))}
        {/* fret numbers */}
        {Array.from({ length: frets }, (_, i) => i + 1).map((f) => (
          <text key={f} x={left + (f - 0.5) * w} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--ink-muted)">
            {f}
          </text>
        ))}
        {dots.map((d) => {
          const faded = !shown(d);
          const light = d.role === "other";
          return (
            <g
              key={`${d.string}-${d.fret}`}
              opacity={faded ? 0.18 : 1}
              onClick={() => onNote?.(d)}
              style={{ cursor: onNote ? "pointer" : undefined }}
            >
              <circle
                cx={x(d.fret)}
                cy={y(d.string)}
                r={11.5}
                fill={FILL[d.role]}
                stroke={light ? "var(--ink-muted)" : "none"}
                strokeWidth={1}
              />
              <text
                x={x(d.fret)}
                y={y(d.string) + 4}
                textAnchor="middle"
                fontSize={d.label.length > 2 ? 9 : 11}
                fontWeight={600}
                fill={light ? "var(--text-primary, currentColor)" : "#fff"}
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
