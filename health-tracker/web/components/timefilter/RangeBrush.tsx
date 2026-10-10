"use client";

// An overview bar of the whole history with the chosen window in it:
// drag the window to pan, drag an edge to zoom in or out,
// tap next to it to move the window there. The new window only goes to the page
// on release, so not every pixel redraws all charts.

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocale, useT } from "@/lib/i18n";
import { clampRange, dayNumber, fmtWindow, timeTicks, toRange, toWindow, type DateWindow, type DayPoint, type DayRange } from "@/lib/timeline";

const H = 46;
const AXIS = 14;
const HANDLE = 10;

export default function RangeBrush({
  first,
  last,
  window,
  onChange,
  points = [],
}: {
  first: string;
  last: string;
  window: DateWindow;
  onChange: (w: DateWindow) => void;
  /** A series as a silhouette under the bar, for example fitness. */
  points?: DayPoint[];
}) {
  const t = useT();
  const { locale } = useLocale();
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [drag, setDrag] = useState<DayRange | null>(null);
  const start = useRef<{ mode: "move" | "a" | "b"; x0: number; r0: DayRange } | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 600);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 600));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const lo = dayNumber(first);
  const hi = dayNumber(last);
  const span = Math.max(hi - lo, 1);
  const x = (d: number) => ((d - lo) / span) * w;
  const dayAt = (px: number) => lo + (px / w) * span;
  const r = drag ?? toRange(window);
  const plotH = H - AXIS;

  const silhouette = useMemo(() => {
    const pts = points.filter((p) => p.d >= first && p.d <= last);
    if (pts.length < 2) return "";
    const vals = pts.map((p) => p.v);
    const min = Math.min(...vals, 0);
    const max = Math.max(...vals) || 1;
    const yy = (v: number) => 3 + (1 - (v - min) / (max - min || 1)) * (plotH - 4);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(dayNumber(p.d)).toFixed(1)} ${yy(p.v).toFixed(1)}`).join("");
    return `${line}L${x(dayNumber(pts[pts.length - 1].d)).toFixed(1)} ${plotH}L${x(dayNumber(pts[0].d)).toFixed(1)} ${plotH}Z`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, first, last, w]);

  const local = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    return rect ? Math.min(Math.max(clientX - rect.left, 0), w) : 0;
  };

  function down(e: React.PointerEvent<HTMLDivElement>) {
    const px = local(e.clientX);
    const ax = x(r.a);
    const bx = x(r.b);
    let mode: "move" | "a" | "b" = "move";
    let r0 = r;
    if (Math.abs(px - ax) <= HANDLE) mode = "a";
    else if (Math.abs(px - bx) <= HANDLE) mode = "b";
    else if (px < ax || px > bx) {
      // Tapped next to it: put the window with the same width there and drag it right away.
      const half = (r.b - r.a) / 2;
      r0 = clampRange({ a: dayAt(px) - half, b: dayAt(px) + half }, lo, hi);
      setDrag(r0);
    }
    start.current = { mode, x0: px, r0 };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function move(e: React.PointerEvent<HTMLDivElement>) {
    const s = start.current;
    if (!s) return;
    const delta = ((local(e.clientX) - s.x0) / w) * span;
    if (s.mode === "move") {
      const len = s.r0.b - s.r0.a;
      const a = Math.max(lo, Math.min(hi - len, s.r0.a + delta));
      setDrag({ a, b: a + len });
    } else if (s.mode === "a") {
      setDrag(clampRange({ a: Math.min(s.r0.a + delta, s.r0.b - 7), b: s.r0.b }, lo, hi));
    } else {
      setDrag(clampRange({ a: s.r0.a, b: Math.max(s.r0.b + delta, s.r0.a + 7) }, lo, hi));
    }
  }

  function up() {
    if (!start.current) return;
    start.current = null;
    if (drag) onChange(toWindow({ a: Math.round(drag.a), b: Math.round(drag.b) }));
    setDrag(null);
  }

  const ticks = timeTicks(lo, hi, w, locale);
  const ax = x(r.a);
  const bx = x(r.b);

  return (
    <div>
      <div
        ref={box}
        className="relative cursor-pointer select-none"
        style={{ height: H, touchAction: "none" }}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        role="img"
        aria-label={t.trendsPage.brushAria(fmtWindow(toWindow({ a: Math.round(r.a), b: Math.round(r.b) }), locale))}
      >
        <svg width="100%" height={H} viewBox={`0 0 ${w} ${H}`} className="block overflow-visible">
          <rect x="0" y="0" width={w} height={plotH} rx="4" fill="var(--surface-inset)" />
          {silhouette && <path d={silhouette} fill="var(--chart-band)" stroke="var(--chart-1)" strokeOpacity="0.6" strokeWidth="1" />}
          {/* Dimmed outside the window, bright inside with a sage border. */}
          <rect x="0" y="0" width={Math.max(ax, 0)} height={plotH} fill="var(--surface-page)" fillOpacity="0.55" />
          <rect x={bx} y="0" width={Math.max(w - bx, 0)} height={plotH} fill="var(--surface-page)" fillOpacity="0.55" />
          <rect x={ax} y="0.5" width={Math.max(bx - ax, 1)} height={plotH - 1} rx="3" fill="none" stroke="var(--brand-500)" strokeWidth="1.5" />
          {[ax, bx].map((hx, i) => (
            <rect key={i} x={hx - 3} y={plotH / 2 - 9} width="6" height="18" rx="3" fill="var(--surface-card)" stroke="var(--brand-500)" strokeWidth="1.5" className="cursor-ew-resize" />
          ))}
          <g className="ds-chart__axis">
            {ticks.map((t) => (
              <text key={t.day} x={x(t.day)} y={H - 2} textAnchor={x(t.day) < 16 ? "start" : x(t.day) > w - 16 ? "end" : "middle"} style={t.major ? { fill: "var(--text-primary)" } : undefined}>
                {t.label}
              </text>
            ))}
          </g>
        </svg>
      </div>
    </div>
  );
}
