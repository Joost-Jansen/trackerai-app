// The shared fetch wrapper (@trackerai/ui/lib/api) and what tabstealth-api returns.

import { ApiError, createApi } from "@trackerai/ui/lib/api";

export { ApiError };
export const api = createApi();

export type Song = {
  video: string;
  file: string;
  title: string;
  artist: string;
  measures?: number;
  tempo?: number;
  time_signature?: string;
  capo?: number;
  swing?: string | null;
  flagged?: number;
  converted?: string;
  edited: boolean;
  status: Status;
  tags: string[];
  favourite: boolean;
  practised_seconds: number;
  last_practised: string | null;
  /** bars the converter flagged and you have not checked yet (review queue) */
  to_review?: number;
};

export const STATUSES = ["new", "checking", "learning", "mastered"] as const;
export type Status = (typeof STATUSES)[number];

export type Job = { id: number; url: string; status: "queued" | "running" | "done" | "failed"; log: string[] };

export type PracticeSummary = {
  days: { day: string; seconds: number }[];
  songs: { video: string; seconds: number; last: string; best_speed: number }[];
  speed: Record<string, { day: string; speed: number }[]>;
  streak: number;
  total_seconds: number;
};
