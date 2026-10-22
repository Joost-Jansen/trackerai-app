// The skin diary (api/skin.py): its shapes, and the gate. The diary is a private feature: only for the accounts the
// API lists (SKIN_DIARY_USERS), visible as `skin` in /api/me's betas. Anyone else gets the site's 404 page here, as
// for a page that does not exist; the API answers them 404 too.

import { notFound } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Me } from "@/lib/training";

export const LOCATIONS = ["cheeks", "nose", "chin", "mouth", "hairline"] as const;
export type Location = (typeof LOCATIONS)[number];
export type SportMark = { activity_id?: string; name: string; red: boolean };

export type Entry = {
  id: number;
  day: string;
  itch: number | null;
  redness: number | null;
  bumps: number | null;
  burning: boolean | null;
  locations: Location[];
  flaking: boolean | null;
  products: string[];
  new_products: string[];
  food: string[];
  sport: SportMark[];
  sleep: number | null;
  stress: number | null;
  weather: string | null;
  heating: boolean | null;
  note: string | null;
  photo_id: number | null;
};
export type EntryFields = Partial<Omit<Entry, "id" | "day" | "photo_id">>;

export type DayContext = {
  activities: { activity_id: string; name: string; sport: string | null; start: string }[];
  sleep_h: number | null;
  sleep_score: number | null;
};
export type DayView = { day: string; today: string; entry: Entry | null; context: DayContext };

export type Week = {
  week: string;
  start: string;
  days: number;
  itch: number | null;
  redness: number | null;
  bumps: number | null;
  flaking_days: number;
  burning_days: number;
  sleep_h: number | null;
  sessions: number;
  training_min: number;
  load: number;
};
export type Side = { days: number; redness: number | null };
export type Comparison = { kind: "short_sleep" | "training" | "food"; label: string; with: Side; without: Side };
export type Overview = { from: string; to: string; entries: Entry[]; weeks: Week[]; comparisons: Comparison[] };

/** Renders the 404 page for anyone without the diary; true once it is theirs, false while /api/me loads. */
export function useSkinGate(): boolean {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me"), retry: false });
  if (!me.data) return false;
  if (!me.data.betas?.includes("skin")) notFound();
  return true;
}
