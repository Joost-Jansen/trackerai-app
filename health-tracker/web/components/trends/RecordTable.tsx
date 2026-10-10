"use client";

// Records per distance: the best ever (from a split or a race), with a PR label when it improved
// recently, and per distance a step line over the period chosen in the time bar.
//
// Why no plain line chart any more? Records rarely improve, so over a few months they were four flat
// lines. Here, per distance: where the record stood at the start of the period, every improvement as a dot
// on its date, and in words how often it improved in this period.

import { useState } from "react";
import Link from "next/link";
import { dayNumber, type DateWindow } from "@/lib/timeline";
import { useFormat, useT } from "@/lib/i18n";
import { fmtClock, type RecentRecord, type RecordKey, type RecordRowPlus } from "@/lib/training";

const KEYS: RecordKey[] = ["1k", "5k", "10k", "21k"];
const KM: Record<RecordKey, number> = { "1k": 1, "5k": 5, "10k": 10, "21k": 21.0975 };
const H = 30;
const PAD_Y = 6;

/** The record texts and date format in the user's language. */
function useRecordTexts() {
  const TR = useT().texts.trends.records;
  const f = useFormat();
  return { TR, LABEL: TR.label, fmtDay: (d: string) => f.day(d), fmtKm: (v: number) => f.km(v) };
}

function Steps({ rows, window: w, colour }: { rows: RecordRowPlus[]; window: DateWindow; colour: string }) {
  const { TR, fmtDay } = useRecordTexts();
  const [hover, setHover] = useState<number | null>(null); // index in `inside` of the record nearest the pointer
  const lo = dayNumber(w.from);
  const span = Math.max(dayNumber(w.to) - lo, 1);
  const before = [...rows].reverse().find((r) => r.date < w.from);
  const inside = rows.filter((r) => r.date >= w.from && r.date <= w.to);
  const levels = [before, ...inside].filter(Boolean) as RecordRowPlus[];
  if (levels.length === 0) return <div className="h-[30px] rounded" style={{ background: "var(--surface-inset)" }} aria-hidden />;
  const max = Math.max(...levels.map((r) => r.seconds));
  const min = Math.min(...levels.map((r) => r.seconds));
  // Faster is higher; without improvement a flat line in the middle.
  const y = (s: number) => (max === min ? H / 2 : PAD_Y + ((s - min) / (max - min)) * (H - 2 * PAD_Y));
  const x = (d: string) => Math.min(100, Math.max(0, ((dayNumber(d) - lo) / span) * 100));
  const segs: { x1: number; x2: number; y1: number; y2: number }[] = [];
  let curX = before ? 0 : x(inside[0].date);
  let curY = y((before ?? inside[0]).seconds);
  for (const r of before ? inside : inside.slice(1)) {
    const nx = x(r.date);
    segs.push({ x1: curX, x2: nx, y1: curY, y2: curY });
    segs.push({ x1: nx, x2: nx, y1: curY, y2: y(r.seconds) });
    curX = nx;
    curY = y(r.seconds);
  }
  segs.push({ x1: curX, x2: 100, y1: curY, y2: curY });
  // the record nearest the pointer (or tap) gets a box with its date and time, as on the other charts
  const pick = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!inside.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const at = ((e.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
    let best = 0;
    inside.forEach((r, i) => {
      if (Math.abs(x(r.date) - at) < Math.abs(x(inside[best].date) - at)) best = i;
    });
    setHover(best);
  };
  const hr = hover != null ? inside[hover] : null;
  return (
    <div className="relative" onPointerMove={pick} onPointerDown={pick} onPointerLeave={(e) => e.pointerType === "mouse" && setHover(null)}>
    <svg width="100%" height={H} className="block overflow-visible" role="img" aria-label={TR.improved(inside.length)}>
      <line x1="0%" x2="100%" y1={H - 0.5} y2={H - 0.5} stroke="var(--border-hairline)" strokeWidth="1" />
      {segs.map((s, i) => (
        <line key={i} x1={`${s.x1}%`} x2={`${s.x2}%`} y1={s.y1} y2={s.y2} stroke={colour} strokeWidth="1.75" strokeLinecap="round" opacity={inside.length ? 1 : 0.55} />
      ))}
      {inside.map((r) => (
        <circle key={r.date + r.activity_id} cx={`${x(r.date)}%`} cy={y(r.seconds)} r={r === hr ? 5 : 3.5} fill={colour} stroke="var(--surface-card)" strokeWidth="1.5" />
      ))}
    </svg>
    {hr && (
      <div
        className="ds-chart__tip"
        aria-live="polite"
        style={{ left: `calc(${x(hr.date)}% ${x(hr.date) > 50 ? "- 10px" : "+ 10px"})`, top: -6, transform: x(hr.date) > 50 ? "translate(-100%, -100%)" : "translateY(-100%)", zIndex: 20 }}
      >
        <span className="font-semibold">{fmtClock(hr.seconds)}</span> <span className="opacity-80">· {fmtDay(hr.date)}</span>
      </div>
    )}
    </div>
  );
}

export default function RecordTable({
  records,
  recent,
  window: w,
  recentDays,
  href,
  colours,
}: {
  records: Record<RecordKey, RecordRowPlus[]>;
  recent: RecentRecord[];
  window: DateWindow;
  recentDays: number;
  href: (id: string) => string;
  colours: Record<RecordKey, string>;
}) {
  const { TR, LABEL, fmtDay, fmtKm } = useRecordTexts();
  const fresh = new Set(recent.map((r) => r.key));
  return (
    <div className="flex flex-col">
      {recent.length > 0 && (
        <div className="mb-3 flex flex-col gap-1">
          {recent.map((r) => (
            <p key={r.key} className="flex items-center gap-2 text-[13px]">
              <span className="rounded-full px-1.5 py-px text-[10.5px] font-semibold" style={{ background: "var(--zone-2)", color: "var(--surface-card)" }}>{TR.pr}</span>
              <Link className="underline-offset-2 hover:underline" href={href(r.activity_id)}>{TR.prNotice(TR.name[r.key], fmtDay(r.date))}</Link>
            </p>
          ))}
        </div>
      )}
      <div className="hidden grid-cols-[7.5rem_5.5rem_4.5rem_7rem_1fr] gap-3 pb-2 text-[11.5px] text-ink-muted sm:grid">
        <span>{TR.colDistance}</span>
        <span>{TR.colTime}</span>
        <span>{TR.colPace}</span>
        <span>{TR.colDate}</span>
        <span>{TR.colProgress}</span>
      </div>
      {KEYS.map((k) => {
        const rows = records[k] ?? [];
        const best = rows[rows.length - 1];
        const inside = rows.filter((r) => r.date >= w.from && r.date <= w.to).length;
        const before = [...rows].reverse().find((r) => r.date < w.from);
        return (
          <div key={k} className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-3 gap-y-1.5 border-t border-border py-2.5 text-[13px] tabular-nums sm:grid-cols-[7.5rem_5.5rem_4.5rem_7rem_1fr] sm:items-center">
            <span>{LABEL[k]}</span>
            <span className="flex items-center gap-1.5 font-medium">
              {best ? fmtClock(best.seconds) : "–"}
              {fresh.has(k) && (
                <span title={TR.prTitle(recentDays)} className="rounded-full px-1.5 py-px text-[10.5px] font-semibold" style={{ background: "var(--zone-2)", color: "var(--surface-card)" }}>
                  {TR.pr}
                </span>
              )}
            </span>
            <span className="hidden text-ink-muted sm:inline">{best ? `${fmtClock(best.seconds / KM[k])}/km` : "–"}</span>
            <span className="text-right sm:text-left">
              {best ? <Link className="underline underline-offset-2" href={href(best.activity_id)}>{fmtDay(best.date)}</Link> : "–"}
            </span>
            <div className="col-span-3 sm:col-span-1">
              {rows.length > 0 && <Steps rows={rows} window={w} colour={colours[k]} />}
              {rows.length > 0 && (
                <p className="mt-0.5 text-[11px] text-ink-muted">
                  {TR.improved(inside)}
                  {inside > 0 && before ? ` · ${TR.before(fmtClock(before.seconds))}` : ""}
                  {best?.source === "race" && best.distance_km ? ` · ${TR.fromRace(fmtKm(best.distance_km))}` : ""}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
