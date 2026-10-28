"use client";

// The library: every converted song (search, filters, sorting, favourites), adding a YouTube link (a video or a whole
// playlist), and the conversions running.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@trackerai/ui/ds/Button";
import { Input, Select } from "@trackerai/ui/ds/Field";
import Tabs from "@trackerai/ui/ds/Tabs";
import { HeartIcon, SearchIcon } from "@trackerai/ui/icons";
import { EmptyState, Tag } from "@trackerai/ui/ds/Feedback";
import { api, ApiError, STATUSES, type Job, type Song } from "@/lib/api";
import { allTags, daysAgo, matches, SORTS, sortSongs, type Filter, type Sort } from "@/lib/library";
import { useT } from "@/lib/i18n";

const YT = /^(https?:\/\/(www\.|m\.|music\.)?(youtube\.com|youtu\.be)\/\S+|[\w-]{11})$/;

export default function LibraryPage() {
  const t = useT();
  const qc = useQueryClient();
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<Job[]>("/api/jobs"),
    // poll only while something is converting
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 3000 : false),
  });
  // A finished job adds songs: reload the library once per job that finishes.
  const finished = useRef(new Set<number>());
  useEffect(() => {
    let changed = false;
    for (const j of jobs.data ?? []) {
      if ((j.status === "done" || j.status === "failed") && !finished.current.has(j.id)) {
        finished.current.add(j.id);
        changed = true;
      }
    }
    if (changed) void qc.invalidateQueries({ queryKey: ["songs"] });
  }, [jobs.data, qc]);

  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: (u: string) => api.post<Job>("/api/convert", { url: u }),
    onSuccess: () => {
      setUrl("");
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t.common.error),
  });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const u = url.trim();
    if (!YT.test(u)) return setError(t.library.invalid);
    setError(null);
    add.mutate(u);
  };

  // search, filter and sort; the choice is kept for this visit in the URL-less state
  const [filter, setFilter] = useState<Filter>({ query: "", status: "all", tag: null });
  const [sort, setSort] = useState<Sort>("artist");
  const all = songs.data ?? [];
  const list = sortSongs(all.filter((s) => matches(s, filter)), sort);
  const tags = allTags(all);
  const star = useMutation({
    mutationFn: (s: Song) => api.patch(`/api/songs/${s.video}`, { favourite: !s.favourite }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["songs"] }),
  });
  const active = (jobs.data ?? []).filter((j) => j.status !== "done").slice(0, 6);

  return (
    <div className="mx-auto flex max-w-content flex-col gap-4">
      <p className="max-w-[62ch] text-sm text-ink-muted">{t.library.lead}</p>

      <Card title={t.library.addTitle}>
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <Input
              label={t.library.addLabel}
              hint={t.library.addHint}
              error={error ?? undefined}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=…"
              inputMode="url"
              autoComplete="off"
            />
          </div>
          <Button type="submit" variant="primary" className="sm:mt-[22px]" disabled={add.isPending}>
            {t.library.addButton}
          </Button>
        </form>
        {active.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">{t.library.jobs}</h3>
            <ul className="flex flex-col gap-2">
              {active.map((j) => (
                <li key={j.id} className="flex flex-col gap-0.5 text-sm">
                  <div className="flex items-center gap-2">
                    <Tag tone={j.status === "failed" ? "loss" : j.status === "running" ? "brand" : "neutral"}>
                      {t.library.status[j.status]}
                    </Tag>
                    <span className="min-w-0 truncate font-mono text-xs">{j.url}</span>
                  </div>
                  {j.log.length > 0 && <span className="truncate font-mono text-[11px] text-ink-muted">{j.log[j.log.length - 1]}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {all.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[200px] flex-1">
              <Input
                icon={<SearchIcon className="h-4 w-4" />}
                value={filter.query}
                onChange={(e) => setFilter({ ...filter, query: e.target.value })}
                placeholder={t.library.search}
                aria-label={t.library.search}
              />
            </div>
            <Select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label={t.library.sort}>
              {SORTS.map((k) => (
                <option key={k} value={k}>
                  {t.library.sortBy[k]}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Tabs
              variant="quiet"
              items={(["all", ...STATUSES, "favourite", "review"] as const).map((k) => ({
                id: k,
                label: k === "all" ? t.library.all : k === "favourite" ? t.library.favourites : k === "review" ? t.library.toReviewFilter : t.library.statuses[k],
              }))}
              value={filter.status}
              onChange={(id) => setFilter({ ...filter, status: id as Filter["status"] })}
              ariaLabel={t.library.statusLabel}
            />
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    aria-pressed={filter.tag === tag}
                    onClick={() => setFilter({ ...filter, tag: filter.tag === tag ? null : tag })}
                    className={`rounded-full border px-2 py-0.5 text-[11px] ${filter.tag === tag ? "border-brand bg-brand-tint text-brand" : "border-border text-ink-muted hover:border-border-strong"}`}
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {songs.isLoading ? (
        <p className="text-sm text-ink-muted">{t.common.loading}</p>
      ) : all.length === 0 ? (
        <EmptyState title={t.library.title} body={t.library.empty} />
      ) : list.length === 0 ? (
        <p className="text-sm text-ink-muted">{t.library.noMatch}</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((s) => (
            <div key={s.video} className="group relative flex gap-3 rounded border border-border bg-surface p-3 transition-colors hover:border-border-strong">
              <Link href={`/song/?v=${encodeURIComponent(s.video)}`} className="absolute inset-0 rounded" aria-label={`${s.title} – ${s.artist}`} />
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`https://i.ytimg.com/vi/${s.video}/mqdefault.jpg`} alt="" className="h-[54px] w-24 flex-none rounded-sm object-cover" loading="lazy" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold group-hover:text-brand">{s.title}</div>
                    <div className="truncate text-xs text-ink-muted">{s.artist}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => star.mutate(s)}
                    aria-pressed={s.favourite}
                    aria-label={t.library.favourite}
                    title={t.library.favourite}
                    className={`relative z-10 -mr-1 -mt-1 rounded-sm p-1 ${s.favourite ? "text-brand" : "text-ink-muted opacity-50 hover:opacity-100"}`}
                  >
                    <HeartIcon className="h-4 w-4" fill={s.favourite ? "currentColor" : "none"} />
                  </button>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-muted">
                  <Tag tone={s.status === "mastered" ? "gain" : s.status === "learning" ? "brand" : "neutral"}>{t.library.statuses[s.status]}</Tag>
                  {s.to_review ? <Tag tone="loss">{t.library.toReview(s.to_review)}</Tag> : null}
                  {s.tempo != null && <span>♩ {s.tempo}</span>}
                  {!!s.capo && <span>{t.library.capo(s.capo)}</span>}
                  {s.edited && <span>{t.library.edited}</span>}
                  <span>{s.last_practised ? t.library.practised(daysAgo(s.last_practised), Math.round(s.practised_seconds / 60)) : t.library.never}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
