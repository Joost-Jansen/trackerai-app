"use client";

// Practice settings next to the video: loop a bar range, the speed trainer, count-in and metronome (lib/practice.ts).
// Shown when its icon next to the speed is selected (TabStudio).

import { Switch } from "@trackerai/ui/ds/Field";
import type { Practice } from "@/lib/practice";
import { useT } from "@/lib/i18n";

const pct = (v: number) => `${Math.round(v * 100)}%`;
const PERCENTS = Array.from({ length: 26 }, (_, i) => Math.round((0.25 + i * 0.05) * 100) / 100); // 25% to 150%

export default function PracticePanel({
  value,
  onChange,
  bars,
  selectedBar,
  source,
  passes,
}: {
  value: Practice;
  onChange: (update: (p: Practice) => Practice) => void;
  bars: number;
  /** The bar of the selected beat (1-based), to start a loop there. */
  selectedBar: number | null;
  source: "video" | "tab";
  /** Passes through the loop so far. */
  passes: number;
}) {
  const t = useT();
  const set = (patch: Partial<Practice>) => onChange((p) => ({ ...p, ...patch }));
  const bar = (v: string) => Math.min(Math.max(1, Number(v) || 1), Math.max(1, bars));
  const num = "ds-input !h-8 w-14 text-center text-xs";
  const sel = "ds-input !h-8 !px-1 text-xs";
  return (
    <section className="flex flex-col gap-2.5 rounded border border-border bg-surface p-3 text-sm">
      <h2 className="text-[13.5px] font-semibold tracking-[0.01em]">{t.practice.title}</h2>
      <div className="flex flex-wrap items-center gap-2">
        <Switch checked={value.loop} onChange={(on) => set({ loop: on })} label={t.practice.loop} />
        <span className="text-xs text-ink-muted">{t.practice.bars}</span>
        <input
          className={num}
          inputMode="numeric"
          value={value.from}
          aria-label={t.practice.from}
          onChange={(e) => set({ from: bar(e.target.value) })}
        />
        <span className="text-xs text-ink-muted">–</span>
        <input
          className={num}
          inputMode="numeric"
          value={value.to}
          aria-label={t.practice.to}
          onChange={(e) => set({ to: bar(e.target.value) })}
        />
        {selectedBar && (
          <button
            type="button"
            className="text-xs font-semibold text-brand hover:underline"
            onClick={() => set({ from: selectedBar, to: Math.max(selectedBar, value.to), loop: true })}
          >
            {t.practice.fromSelected(selectedBar)}
          </button>
        )}
        {value.loop && passes > 0 && <span className="ml-auto text-xs text-ink-muted">{t.practice.passes(passes)}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Switch checked={value.trainer} onChange={(on) => set({ trainer: on })} label={t.practice.trainer} />
        <select className={sel} value={value.start} aria-label={t.practice.start} onChange={(e) => set({ start: Number(e.target.value) })}>
          {PERCENTS.map((v) => (
            <option key={v} value={v}>
              {t.practice.startAt(pct(v))}
            </option>
          ))}
        </select>
        <select className={sel} value={value.step} aria-label={t.practice.step} onChange={(e) => set({ step: Number(e.target.value) })}>
          {[0.02, 0.05, 0.1].map((v) => (
            <option key={v} value={v}>
              {t.practice.stepBy(pct(v))}
            </option>
          ))}
        </select>
        <select
          className={sel}
          value={value.target}
          aria-label={t.practice.target}
          onChange={(e) => set({ target: Number(e.target.value) })}
        >
          {PERCENTS.map((v) => (
            <option key={v} value={v}>
              {t.practice.upTo(pct(v))}
            </option>
          ))}
        </select>
      </div>
      {value.trainer && source === "video" && <p className="text-xs text-ink-muted">{t.practice.videoSteps}</p>}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Switch checked={value.countIn} onChange={(on) => set({ countIn: on })} label={t.practice.countIn} />
        <Switch checked={value.metronome} onChange={(on) => set({ metronome: on })} label={t.practice.metronome} />
      </div>
    </section>
  );
}

export { PERCENTS };
