"use client";

// The review queue: the bars the converter was unsure about (GET /api/songs/{id}/review), each with why. "Go"
// selects the bar, moves the video there and loops it; ticking it off marks it checked.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, ChevronDownIcon } from "@trackerai/ui/icons";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type ReviewItem = { bar: number; reasons: string[]; checked: boolean };

export default function ReviewPanel({ vid, open, onToggle, onGo }: { vid: string; open: boolean; onToggle: () => void; onGo: (bar: number) => void }) {
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
      <button type="button" className="flex items-center gap-2 text-left" aria-expanded={open} onClick={onToggle}>
        <CheckIcon className={`h-4 w-4 flex-none ${left ? "text-warn" : "text-pos"}`} />
        <span className="text-[13.5px] font-semibold tracking-[0.01em]">{t.review.title}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">{left ? t.review.left(left) : t.review.allChecked}</span>
        <ChevronDownIcon className={`h-4 w-4 flex-none text-ink-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <>
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
        </>
      )}
    </section>
  );
}
