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
};

export type Job = { id: number; url: string; status: "queued" | "running" | "done" | "failed"; log: string[] };
