// The library list: search, filters and sorting (the page in app/(app)/library).

import type { Kind, Song, Status } from "./api.ts";

export type Sort = "artist" | "title" | "added" | "practised" | "most";
export type Filter = { query: string; status: Status | "all" | "favourite" | "review"; tag: string | null; kind?: Kind | "all" };

export const SORTS: Sort[] = ["artist", "title", "added", "practised", "most"];

export function matches(s: Song, f: Filter): boolean {
  const q = f.query.trim().toLowerCase();
  if (q && ![s.title, s.artist, ...(s.tags ?? [])].some((x) => x.toLowerCase().includes(q))) return false;
  if (f.status === "favourite" && !s.favourite) return false;
  if (f.status === "review" && !s.to_review) return false;
  if (f.status !== "all" && f.status !== "favourite" && f.status !== "review" && s.status !== f.status) return false;
  if (f.tag && !(s.tags ?? []).includes(f.tag)) return false;
  if (f.kind && f.kind !== "all" && (s.kind ?? "tab") !== f.kind) return false;
  return true;
}

const text = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base" });

export function sortSongs(list: Song[], sort: Sort): Song[] {
  const out = [...list];
  const by: Record<Sort, (a: Song, b: Song) => number> = {
    artist: (a, b) => text(a.artist, b.artist) || text(a.title, b.title),
    title: (a, b) => text(a.title, b.title),
    added: (a, b) => (b.converted ?? "").localeCompare(a.converted ?? "") || text(a.title, b.title),
    practised: (a, b) => (b.last_practised ?? "").localeCompare(a.last_practised ?? "") || text(a.title, b.title),
    most: (a, b) => b.practised_seconds - a.practised_seconds || text(a.title, b.title),
  };
  return out.sort(by[sort]);
}

export const allTags = (list: Song[]) => [...new Set(list.flatMap((s) => s.tags ?? []))].sort();

/** Days between two ISO dates (today - day). */
export function daysAgo(day: string, today: Date = new Date()): number {
  const [y, m, d] = day.split("-").map(Number);
  const then = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((now - then) / 86_400_000);
}

/** The player's own date as YYYY-MM-DD (practice counts on your calendar, not the server's). */
export function localDay(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Where an item opens: a tab in the player, a video on its own, a PDF in the viewer. */
export const itemHref = (s: Pick<Song, "video" | "kind">) =>
  s.kind === "pdf" ? `/pdf/?id=${encodeURIComponent(s.video)}` : s.kind === "video" ? `/watch/?v=${encodeURIComponent(s.video)}` : `/song/?v=${encodeURIComponent(s.video)}`;
