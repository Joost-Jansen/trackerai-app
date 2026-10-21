// Gear (api/gear.py): shoes, a bike, anything an activity wears out. The shapes the API sends and the one query.

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const GEAR_KINDS = ["shoes", "bike", "other"] as const;
export type GearKind = (typeof GEAR_KINDS)[number];
export type GearState = "ok" | "soon" | "replace" | "retired";

export type Gear = {
  id: number;
  kind: GearKind;
  name: string;
  brand: string | null;
  model: string | null;
  start_km: number | null;
  max_km: number | null;
  since: string | null;
  retired_on: string | null;
  notes: string | null;
  source: "garmin" | "manual";
  total_km: number;
  linked_km: number;
  before_km: number;
  limit_km: number | null;
  limit_from: "own" | "garmin" | "default" | null;
  left_km: number | null;
  share: number | null;
  state: GearState;
  uses: number;
  first_used: string | null;
  last_used: string | null;
  km_30d: number;
  default_for: string[];
};

export type GearOverview = { gear: Gear[]; defaults: Record<string, number>; sports: string[] };

/** What an activity used; source says why: chosen on the activity, linked in Garmin, or the default of its sport. */
export type ActivityGear = { id: number; name: string; kind: GearKind; source: "manual" | "garmin" | "default" };

export type GearActivity = {
  id: string;
  start_local: string;
  sport: string;
  name: string | null;
  distance_km: number | null;
  moving_time_s: number | null;
  source: ActivityGear["source"];
};

export const useGear = () => useQuery({ queryKey: ["gear"], queryFn: () => api.get<GearOverview>("/api/gear") });
