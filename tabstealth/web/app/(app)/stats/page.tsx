"use client";

// Practice: how much you played (per day, per song), your streak, the speed you reached per song, and where the
// library stands. From the practice log the song page writes while something plays (GET /api/practice).

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import Bars from "@trackerai/ui/charts/Bars";
import LineChart from "@trackerai/ui/charts/LineChart";
import { EmptyState } from "@trackerai/ui/ds/Feedback";
import { api, STATUSES, type PracticeSummary, type Song } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { localDay } from "@/lib/library";
import { duration, lastDays, weekMinutes } from "@/lib/stats";

const COLOURS = ["var(--chart-1)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded border border-border bg-surface p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">{label}</div>
      <div className="mt-1 font-display text-[26px] font-light leading-tight">{value}</div>
      {note && <div className="mt-0.5 text-xs text-ink-muted">{note}</div>}
    </div>
  );
}

export default function StatsPage() {
  const t = useT();
  const practice = useQuery({
    queryKey: ["practice"],
    queryFn: () => api.get<PracticeSummary>(`/api/practice?today=${localDay()}`),
  });
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const p = practice.data;
  const byVideo = new Map((songs.data ?? []).map((s) => [s.video, s]));

  if (practice.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!p || p.total_seconds === 0) {
    return (
      <div className="mx-auto max-w-content">
        <EmptyState title={t.stats.title} body={t.stats.empty} />
      </div>
    );
  }

  const days = lastDays(p.days, 30);
  const week = weekMinutes(p.days);
  const top = p.songs.slice(0, 8);
  const most = Math.max(...top.map((s) => s.seconds), 1);
  const speedSongs = top.filter((s) => (p.speed[s.video]?.length ?? 0) > 1).slice(0, 5);
  const statusCount = STATUSES.map((st) => ({ st, n: (songs.data ?? []).filter((s) => s.status === st).length }));
  const total = Math.max(
    1,
    statusCount.reduce((a, b) => a + b.n, 0),
  );

  return (
    <div className="mx-auto flex max-w-content flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t.stats.thisWeek} value={`${week.thisWeek} min`} note={t.stats.lastWeek(week.lastWeek)} />
        <Stat label={t.stats.streak} value={t.stats.days(p.streak)} />
        <Stat label={t.stats.total} value={duration(p.total_seconds)} />
        <Stat label={t.stats.songs} value={String(p.songs.length)} />
      </div>

      <Card title={t.stats.perDay}>
        <Bars
          bars={days.map((d) => ({
            key: d.day,
            label: d.day.slice(8),
            title: d.day,
            segments: [{ key: "min", value: d.minutes, colour: "var(--chart-1)" }],
          }))}
          format={(v) => `${Math.round(v)} min`}
          summary={t.stats.perDaySummary(Math.round(days.reduce((a, b) => a + b.minutes, 0)))}
          labelEvery={5}
          ariaLabel={t.stats.perDay}
        />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t.stats.perSong}>
          <ul className="flex flex-col gap-2">
            {top.map((s) => {
              const song = byVideo.get(s.video);
              return (
                <li key={s.video} className="text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <Link href={`/song/?v=${encodeURIComponent(s.video)}`} className="min-w-0 truncate hover:text-brand">
                      {song?.title ?? s.video}
                    </Link>
                    <span className="flex-none text-xs text-ink-muted">{duration(s.seconds)}</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-2">
                    <div className="h-1.5 rounded-full bg-brand" style={{ width: `${(s.seconds / most) * 100}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card title={t.stats.library}>
          <div className="flex h-3 overflow-hidden rounded-full">
            {statusCount.map(({ st, n }, i) => (
              <div key={st} style={{ width: `${(n / total) * 100}%`, background: COLOURS[i] }} title={`${t.library.statuses[st]}: ${n}`} />
            ))}
          </div>
          <ul className="mt-3 grid grid-cols-2 gap-2 text-sm">
            {statusCount.map(({ st, n }, i) => (
              <li key={st} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLOURS[i] }} />
                <span className="text-ink-muted">{t.library.statuses[st]}</span>
                <span className="ml-auto font-medium">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {speedSongs.length > 0 && (
        <Card title={t.stats.speed}>
          <LineChart
            series={speedSongs.map((s, i) => ({
              label: byVideo.get(s.video)?.title ?? s.video,
              colour: COLOURS[i],
              points: p.speed[s.video].map((x) => ({ d: x.day, v: Math.round(x.speed * 100) })),
            }))}
            baseline={100}
            format={(v) => `${Math.round(v)}%`}
            ariaLabel={t.stats.speed}
          />
        </Card>
      )}
    </div>
  );
}
