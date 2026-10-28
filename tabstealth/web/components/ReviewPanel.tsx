"use client";

// The review queue: the bars the converter was unsure about (GET /api/songs/{id}/review), each with why. "Go"
// selects the bar, moves the video there and loops it; ticking it off marks it checked. Shown when its icon next to
// the speed is selected (TabStudio).

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type ReviewItem = { bar: number; reasons: string[]; checked: boolean };

export default function ReviewPanel({ vid, onGo }: { vid: string; onGo: (bar: number) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const items = useQuery({ queryKey: ["review", vid], queryFn: () => api.get<ReviewItem[]>(`/api/songs/${vid}/review`) });
  const list = items.data ?? [];
  if (!list.length) return null;
  const left = list.filter((r) => !r.checked).length;
  const mark = async (bar: number, checked: boolean) => {
    qc.setQueryData(["review", vid], await api.post<ReviewItem[]>(`/api/songs/${vid}/review`, { bar, checked }));
    void qc.invalidateQueries({ queryKey: ["songs"] });
  };
  const reason = (r: string) => (t.review.reasons as Record<string, string>)[r] ?? r;

  return (
    <section className="flex flex-col gap-2 rounded border border-border bg-surface p-3 text-sm">
      <div className="flex items-baseline gap-2">
        <h2 className="text-[13.5px] font-semibold tracking-[0.01em]">{t.review.title}</h2>
        <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">{left ? t.review.left(left) : t.review.allChecked}</span>
      </div>
      <p className="text-xs text-ink-muted">{t.review.lead}</p>
      <ul className="flex flex-col divide-y divide-border">
        {list.map((r) => (
          <li key={r.bar} className={`flex items-center gap-2 py-1.5 ${r.checked ? "opacity-60" : ""}`}>
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--brand-500)]"
              checked={r.checked}
              aria-label={t.review.checked}
              onChange={(e) => void mark(r.bar, e.target.checked)}
            />
            <span className="w-14 flex-none font-medium">{t.review.bar(r.bar + 1)}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">{r.reasons.map(reason).join(" · ")}</span>
            <button type="button" className="flex-none text-xs font-semibold text-brand hover:underline" onClick={() => onGo(r.bar)}>
              {t.review.go}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
