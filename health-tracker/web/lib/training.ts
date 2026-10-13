// Types and formatting for training data. Times as 1:05 (h:mm), pace as 5:20/km.

import type { ActivityGear } from "@/lib/gear";
import { SPORTS, effortKind } from "@/lib/sports";

export const ZONES = ["Z1", "Z2", "Z3", "Z4", "Z5"] as const;
export type Zone = (typeof ZONES)[number];
export type ZoneSeconds = Record<Zone, number>;

export const ZONE_COLOUR: Record<Zone, string> = {
  Z1: "var(--zone-1)",
  Z2: "var(--zone-2)",
  Z3: "var(--zone-3)",
  Z4: "var(--zone-4)",
  Z5: "var(--zone-5)",
};

/** Endurance rule of thumb (80/20): about 80% of the time easy, in Z1-Z2. Below EASY_LOW it deserves a look
 *  (the same line as the Trends insight easy_share, api/trends.py). */
export const EASY_TARGET = 80;
export const EASY_LOW = 75;
export const easyPct = (pct: Record<Zone, number>) => pct.Z1 + pct.Z2;

/** Dutch sport names (lib/sports.ts); the site takes its names from lib/i18n (t.sport) in the user's language. */
export const SPORT_LABEL: Record<string, string> = Object.fromEntries(Object.entries(SPORTS).map(([k, v]) => [k, v.nl]));

export const sportLabel = (s: string) => SPORT_LABEL[s] ?? s.replace(/_/g, " ");

export type ActivitySummary = {
  id: string;
  start_local: string;
  sport: string;
  name?: string;
  distance_km?: number;
  moving_time_s?: number;
  avg_hr?: number;
  max_hr?: number;
  elevation_gain_m?: number;
  hr_zones_s?: ZoneSeconds;
  /** Open water (tools/distance.py): a doubtful GPS distance is left out (`distance_km` empty, the GPS value in
   *  `gps_distance_km`); `distance_manual` when you corrected it. */
  open_water?: boolean;
  distance_doubtful?: boolean;
  gps_distance_km?: number;
  distance_manual?: boolean;
};

export type ZoneShare = { seconds: ZoneSeconds; total_s: number; pct: Record<Zone, number> };
export type Volume = { count: number; km: number; seconds: number };
/** form_pct: form as % of yesterday's fitness (null in the first weeks), see tools/analytics.py. */
export type FormRow = { date: string; load: number; ctl: number; atl: number; tsb: number; form_pct?: number | null };

/** Acute (ATL) against chronic (CTL) load, see api/dashboard.py load_indicator. */
export type LoadIndicator = {
  band: "low" | "build" | "high" | "unknown";
  acwr: number | null;
  ramp: number | null;
  reason: "ratio" | "ramp" | null;
  thresholds: { low: number; high: number; ramp_high: number };
};

export type Dashboard = {
  today: string;
  last_sync: string;
  zone_bounds: Record<string, number[]>;
  zone_estimates?: string[];
  zones_set?: string[];
  zones: { week: Record<string, ZoneShare>; month: Record<string, ZoneShare> };
  volume: { week: Record<string, Volume>; avg4w: Record<string, Volume> };
  form: null | {
    ctl: number;
    atl: number;
    tsb: number;
    /** form as % of fitness; the status follows from it (api/dashboard.py FORM_BANDS) */
    pct?: number | null;
    status: string;
    ctl_peak: number;
    ctl_peak_date: string;
    /** Last day of the series: today, or the last synced day when the sync is older than yesterday. */
    until: string;
    stopped_at_sync: boolean;
    load: LoadIndicator;
    series: FormRow[];
  };
  recent: RecentItem[];
  recovery: {
    days: ({ date: string } & Record<string, number | string>)[];
    baseline_rhr: number | null;
    /** Where the normal comes from (api/readiness.py normal_resting_hr). */
    baseline_rhr_source?: RhrSource | null;
  };
  upcoming: PlanSession[];
  plan_title?: string;
  /** Only with an active plan. */
  plan_week?: PlanWeekSummary;
  race?: NextRace | null;
  readiness?: Readiness | null;
};

/** Codes and numbers; the text comes from T.today.readiness (api/readiness.py). */
export type ReadinessNote = {
  code: "vs_baseline" | "sleep" | "highest" | "form_yesterday";
  params: { delta?: number; baseline?: number; score?: number; date?: string; days_ago?: number };
};

export type Readiness = {
  verdict: "ready" | "easy" | "recover" | "unknown";
  date: string | null;
  /** No sleep or resting heart rate from last night. */
  no_night: boolean;
  signals: { key: "resting_hr" | "respiration" | "sleep_h" | "body_battery" | "tsb"; value: number; note: ReadinessNote; level: "ok" | "attention" | "warn" }[];
  /** Resting HR, heart rate while asleep and night breathing all above normal together: a cold may be coming on. */
  illness_hint?: boolean;
};

export type SleepStage = "deep" | "light" | "rem" | "awake";
export type SleepNight = { date: string } & Record<SleepStage, number>;
export type DaySeriesKey = "hr" | "stress" | "bb" | "resp" | "spo2";

/** GET /api/wellness/day (api/daily.py): one day of health data from the watch. Times are minutes after midnight of
 *  `day`; the evening before is negative. `summary` is the day's wellness row (tools/store.py wellness_from_garmin),
 *  `normals` the 60-day medians before the day. */
export type HealthDay = {
  day: string;
  prev: string | null;
  next: string | null;
  latest: string | null;
  /** Today where the user lives: the date picker goes up to it, also before it has data. */
  today: string | null;
  from: number;
  to: number;
  series: Partial<Record<DaySeriesKey, [number, number][]>>;
  sleep: { start: number; end: number; stages: { start: number; end: number; stage: SleepStage }[] } | null;
  next_sleep_start: number | null;
  summary: Partial<Record<string, number | string>>;
  normals: Partial<Record<"resting_hr" | "sleep_hr" | "sleep_h" | "sleep_resp" | "sleep_stress" | "bb_charged_sleep" | "spo2_avg" | "stress_avg", number | null>>;
  hr_min: number | null;
  hr_max: number | null;
  night: { lowest: number; lowest_at: number; avg: number; last_avg: number | null; before_avg: number | null; rise: number | null; minutes: number } | null;
};

export function fmtDuration(seconds?: number): string {
  if (!seconds) return "0:00";
  const m = Math.round(seconds / 60);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

export function fmtPace(seconds?: number, km?: number): string {
  if (!seconds || !km) return "–";
  const s = Math.round(seconds / km);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}/km`;
}

export function fmtSpeed(seconds?: number, km?: number): string {
  if (!seconds || !km) return "–";
  return `${((km / seconds) * 3600).toFixed(1).replace(".", ",")} km/u`;
}

/** Pace on foot, speed for cycling and most other sports, per 100 m for swimming (lib/sports.ts effortKind). */
export function fmtIntensity(a: { sport: string; moving_time_s?: number; distance_km?: number }): string {
  const kind = effortKind(a.sport);
  if (kind === "speed") return fmtSpeed(a.moving_time_s, a.distance_km);
  if (kind === "swim" || kind === "row") {
    if (!a.moving_time_s || !a.distance_km) return "–";
    const s = Math.round(a.moving_time_s / (a.distance_km * (kind === "swim" ? 10 : 2)));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}/${kind === "swim" ? "100m" : "500m"}`;
  }
  return fmtPace(a.moving_time_s, a.distance_km);
}

export const fmtKm = (km?: number) => (km == null ? "–" : `${km.toFixed(1).replace(".", ",")} km`);

export function fmtDate(iso: string): string {
  return new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("nl-NL", { weekday: "short", day: "numeric", month: "short" });
}

export function zoneRanges(bounds: number[]): Record<Zone, string> {
  const [b2, b3, b4, b5] = bounds;
  return { Z1: `< ${b2}`, Z2: `${b2}-${b3 - 1}`, Z3: `${b3}-${b4 - 1}`, Z4: `${b4}-${b5 - 1}`, Z5: `≥ ${b5}` };
}

// ── History (T4) ─────────────────────────────────────────────────────────────

export type ActivityListItem = ActivitySummary & { has_gps?: boolean };

export type Lap = { distance_km?: number; time_s?: number; avg_hr?: number; pace?: string; elevation_gain_m?: number };
export type KmSplit = { km: number; seconds: number; avg_hr: number | null; elevation_m?: number };
export type RouteRun = { id: string; date: string; moving_time_s?: number; distance_km?: number; avg_hr?: number; pace_s_per_km: number | null };

export type ActivityDetail = ActivitySummary & {
  elapsed_time_s?: number;
  avg_cadence_spm?: number;
  calories?: number;
  vo2max?: number;
  laps: Lap[];
  zone_bounds: number[] | null;
  zone_estimate: boolean;
  track: { latlng: [number, number][]; zone: (Zone | null)[] } | null;
  series: { time: number[]; heartrate?: (number | null)[]; velocity?: (number | null)[]; altitude?: (number | null)[]; cadence?: (number | null)[]; distance?: (number | null)[] } | null;
  splits: KmSplit[];
  decoupling_pct: number | null;
  same_day: { id: string; start_local: string; sport: string; name?: string; distance_km?: number; moving_time_s?: number }[];
  route: null | { id: string; name?: string; distance_km?: number; history: RouteRun[] };
  prev_id: string | null;
  next_id: string | null;
  gear: ActivityGear[];
  /** The user chose the gear here (or "none"): the default and Garmin no longer decide. */
  gear_chosen: boolean;
};

export type Heatmap = { tracks: [number, number][][] };

export function zoneShare(seconds?: Partial<ZoneSeconds> | null): ZoneShare | null {
  if (!seconds) return null;
  const secs = Object.fromEntries(ZONES.map((z) => [z, seconds[z] ?? 0])) as ZoneSeconds;
  const total = ZONES.reduce((s, z) => s + secs[z], 0);
  if (!total) return null;
  const pct = Object.fromEntries(ZONES.map((z) => [z, (secs[z] / total) * 100])) as Record<Zone, number>;
  return { seconds: secs, total_s: total, pct };
}

export function fmtClock(seconds?: number | null): string {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

export const fmtPaceS = (s?: number | null) => (s ? `${fmtClock(s)}/km` : "–");

// ── Trends (T5) ──────────────────────────────────────────────────────────────

export type RecordRow = { date: string; seconds: number; activity_id: string };
export type Race = { date: string; name: string; sport: string; seconds: number; distance_km: number; activity_ids: string[]; detected?: "name" | "heart_rate" };
export type Prediction = { seconds: number; pace_s_per_km: number; from: { date: string; km: number; seconds: number; activity_id: string; source: "split" | "race" } };
export type Insight = { level: "good" | "watch" | "info"; title: string; text: string };

export type Trends = {
  today: string;
  form: FormRow[];
  /** One row per day with any recovery value, oldest first (T17). */
  /** Per night with sleep stages, in hours (api/trends.py sleep_stages). */
  sleep_stages?: SleepNight[];
  recovery_daily?: { date: string; resting_hr?: number | null; sleep_h?: number | null; body_battery_high?: number | null; stress_avg?: number | null; hrv?: number | null }[];
  weekly: { week: string; sports: Record<string, Volume> }[];
  z2_pace: { week: string; pace_s_per_km: number; runs: number; z2_seconds: number }[];
  vo2max: { date: string; value: number }[];
  recovery_weekly: ({ week: string } & Partial<Record<"resting_hr" | "sleep_h" | "body_battery_high" | "stress_avg" | "hrv" | "sleep_resp" | "sleep_stress" | "bb_charged_sleep" | "spo2_avg", number | null>>)[];
  records: Record<"1k" | "5k" | "10k" | "21k", RecordRow[]>;
  races: Race[];
  rules?: { race_min_km: number; race_hard_pct: number; predict_days: number; riegel: number };
  predictions: Partial<Record<"5k" | "10k" | "21k" | "42k", Prediction>>;
  insights: Insight[];
};

// ── Plan (T6) ────────────────────────────────────────────────────────────────

export type SessionStatus = "done" | "missed" | "today" | "planned" | "rest";

export type PlanSession = {
  id?: number;
  date: string;
  sport: string;
  kind?: string | null;
  distance_km?: number | null;
  duration_min?: number | null;
  target_zone?: string | null;
  description?: string | null;
  route_id?: string | null;
  status?: SessionStatus;
  activity_ids?: string[];
  /** How the activity was matched (api/plans.py match_sessions): that day, a day or two early or late, or by the user. */
  match?: "day" | "near" | "manual";
  /** `date`: the day the activity was done. */
  done?: { date: string; distance_km: number; moving_time_s: number; avg_hr?: number; zone_pct: number | null };
  /** Open sessions: unused activities of the same sport within a week, to link by hand. */
  candidates?: { id: string; date: string; distance_km?: number | null; moving_time_s?: number | null }[];
  route_suggestion?: { parts: string[]; names: string[]; total_km: number; deviation_km: number; within_tolerance: boolean; days_since: number };
  /** The loop chosen in the plan (`route_id`), when it is one of the user's loops (T24). */
  route?: { id: string; name: string; distance_km?: number | null };
};

/** `done_km` (also per sport) counts every activity of a sport in the plan that week, in a session or not. */
export type PlanWeek = {
  week: string;
  planned_km: number;
  done_km: number;
  planned: number;
  done: number;
  missed: number;
  sports: Record<string, { planned_km: number; done_km: number }>;
};

export type Plan = {
  id: number;
  title: string;
  goal?: string | null;
  race?: string | null;
  notes?: string | null;
  status: "active" | "finished" | "stopped";
  author: string;
  created_at: string;
  sessions: PlanSession[];
  weeks: PlanWeek[];
  /** What the user decided: activity id -> the date of its session, or null for "not part of the plan". */
  links?: Record<string, string | null>;
};

export type PlanListItem = Omit<Plan, "sessions" | "weeks" | "links">;

// ── Routes (T7) ──────────────────────────────────────────────────────────────

/** Sports with recurring routes: id prefix r (running) and f (cycling). */
export type RouteSport = "run" | "ride";

export type RouteSummary = {
  id: string;
  name?: string;
  sport: string;
  distance_km: number;
  is_loop?: boolean;
  elevation_gain_m?: number;
  runs: number;
  first_run?: string;
  last_run?: string;
  /** Running: median pace "5:08"; null for cycling routes. */
  median_pace?: string | null;
  /** Cycling: median speed in km/h; null for running routes. */
  median_speed_kmh?: number | null;
  median_hr?: number;
  start?: [number, number];
  best: null | { activity_id: string; date: string; pace_s_per_km: number; moving_time_s?: number };
  recent_pace_s_per_km: number | null;
  earlier_pace_s_per_km: number | null;
  recent_efficiency: number | null;
  earlier_efficiency: number | null;
  medoid_id?: string | null;
  track: [number, number][];
  variants?: { id: string; date: string; track: [number, number][] }[];
};

export type RouteDetail = RouteSummary & {
  history: { id: string; date: string; distance_km?: number; moving_time_s?: number; avg_hr?: number; pace_s_per_km: number | null; m_per_beat: number | null; hr_zones_s?: ZoneSeconds }[];
};

export type RouteOption = {
  parts: string[];
  names: string[];
  total_km: number;
  deviation_km: number;
  within_tolerance: boolean;
  days_since: number;
  tracks: Record<string, [number, number][]>;
};

// ── Zones over time (T16) ────────────────────────────────────────────────────

export type ZonePeriod = "week" | "month";

/** GET /api/zones?period=&offset= : one week or month, offset 0 = the current one (up to now). */
export type ZonesForPeriod = {
  period: ZonePeriod;
  offset: number;
  start: string;
  end: string;
  label: string;
  is_current: boolean;
  /** Per sport plus "all" (sum, every sport with its own zones); empty without heart-rate data. */
  zones: Record<string, ZoneShare>;
  bounds: Record<string, number[]>;
};

export type ZoneHistoryItem = ZoneShare & { start: string; end: string; label: string };

/** GET /api/zones/history?period=&count=&sport= : oldest first, the last is the current period. */
export type ZoneHistory = {
  period: ZonePeriod;
  sport: string;
  /** Sports with heart-rate zones in the whole window, regardless of the sport filter. */
  sports: string[];
  items: ZoneHistoryItem[];
};


// ── Accounts (T19) ───────────────────────────────────────────────────────────

export type Me = {
  id: number; // null (only) while the account still has to set up two-step login, consent, or join health-tracker
  username: string;
  display_name: string | null;
  is_admin: boolean; // health-tracker's admin
  via: "cookie" | "agent";
  totp_enabled?: boolean; // the authenticator app
  email_codes?: boolean; // codes by email
  two_step?: boolean; // either: deleting or leaving asks for a code
  email?: string | null;
  email_verify_required?: boolean; // signed up, the address not confirmed yet: the gate asks for the welcome code
  locale?: "nl" | "en" | null;
  // the shared trackerai account (packages/accounts)
  account_admin?: boolean;
  apps?: string[];
  totp_required?: boolean;
  totp_setup_required?: boolean;
  in_app?: boolean;
  consent_needed?: boolean;
  betas?: string[]; // beta features an admin switched on for this user (api/betas.py)
};
export type RegistrationMode = "closed" | "invite" | "open";

// ── Routes: length variants and "is this the same route?" (T20) ─────────────

/** A length variant within a route (the same route with an extra loop, detour or run-up). */
export type RouteLengthVariant = { distance_km: number; runs: number; activity_ids: string[]; last_run: string };

/** GET /api/routes and /api/routes/{id} also return `distance_variants`, shortest first. */
export type RouteWithVariants = RouteSummary & { distance_variants?: RouteLengthVariant[] };

export type RouteCandidateSide = {
  id: string;
  kind: "route" | "activity";
  name?: string | null;
  distance_km?: number;
  runs?: number;
  last_run?: string;
  /** Only for a single activity. */
  date?: string;
  track: [number, number][];
};

export type RouteReasonCode = "same" | "other_start" | "extra_loop" | "partly_other_way";

/** An open question: a is always a route, b a route or a single activity. */
export type RouteCandidate = {
  sport: RouteSport;
  outcome: "same" | "candidate";
  confidence: number;
  reason_code?: RouteReasonCode | null;
  reason: string;
  a: RouteCandidateSide;
  b: RouteCandidateSide;
};

/** GET /api/routes/candidates?sport= */
export type RouteCandidates = { candidates: RouteCandidate[]; last_sync: string | null };

/** POST /api/routes/candidates {a, b, same} */
export type RouteCandidateResult = { applied: boolean; applied_on_next_sync: boolean; route: RouteWithVariants | null; remaining: number };

// ── Today: plan this week, race, latest activities ───────────────────────────

/** The plan's sessions per sport this week; planned time only from sessions with a duration. */
export type PlanWeekSport = { planned_km: number; done_km: number; planned_s: number; done_s: number; sessions: number; done: number };

/** GET /api/dashboard `plan_week`: Monday to Sunday of the active plan (api/dashboard.py plan_week). */
export type PlanWeekSummary = {
  start: string;
  end: string;
  sports: Record<string, PlanWeekSport>;
  /** `unsynced`: past, but after the last sync; not yet known whether it was done. */
  sessions: { total: number; done: number; missed: number; upcoming: number; unsynced: number };
};

/** GET /api/dashboard `race`: the next race from the plan; `name` only for the plan's own race. */
export type NextRace = { date: string; days: number; name: string | null; distance_km: number | null; sport: string | null };

/** An item under latest activities: runs with less than 30 minutes break are one item with `parts`. */
export type RecentItem = ActivitySummary & { parts?: number; activity_ids?: string[]; race?: boolean };

// ── Trends, extension (insights as codes, records from races, goal, longest run, wrist heart rate) ──────────

export type RecordKey = "1k" | "5k" | "10k" | "21k";
/** A record row: from a split or from a race the watch measured slightly short (then with distance_km). */
export type RecordRowPlus = RecordRow & { source?: "split" | "race"; distance_km?: number };
export type RecentRecord = { key: RecordKey; date: string; seconds: number; previous_seconds: number; activity_id: string; source: "split" | "race" };
/** The goal from the active plan (api/trends.py goal_from_plan). */
export type TrendsGoal = { km: number; seconds: number | null; date: string | null; text: string };
export type LongestRun = { week: string; date: string; km: number; seconds: number; parts: number; activity_id: string };
export type HrFlagReason = "low_start" | "flat" | "dropout";
export type HrFlag = { id: string; date: string; name: string; reasons: HrFlagReason[] };

/** Insight as a code with numbers; the text comes from lib/texts.ts (T.trends.insight). */
export type InsightCode =
  | { level: Insight["level"]; code: "record_set"; params: { key: RecordKey; seconds: number; previous_seconds: number; date: string; activity_id: string } }
  | { level: Insight["level"]; code: "acwr_high"; params: { atl: number; ctl: number; ratio: number } }
  | { level: Insight["level"]; code: "ramp_fast"; params: { ramp: number } }
  | { level: Insight["level"]; code: "fresh"; params: { tsb: number; pct: number } }
  | { level: Insight["level"]; code: "easy_share"; params: { easy_pct: number; grey_pct: number; hard_pct: number } }
  | { level: Insight["level"]; code: "longest_run"; params: { km: number } }
  | { level: Insight["level"]; code: "long_run_goal"; params: { km: number; target_km: number; goal_km: number } }
  | { level: Insight["level"]; code: "goal_prediction"; params: { goal_km: number; goal_seconds: number; predicted_seconds: number; from_km: number; from_date: string } }
  | { level: Insight["level"]; code: "run_volume"; params: { avg_km: number; week_km: number; week_start: string } };

export type RecoveryDay = {
  date: string;
  resting_hr: number | null;
  sleep_h: number | null;
  body_battery_high: number | null;
  stress_avg: number | null;
  hrv: number | null;
  sleep_resp?: number | null;
  sleep_stress?: number | null;
  bb_charged_sleep?: number | null;
  spo2_avg?: number | null;
};

/** GET /api/trends as the API returns it now. */
export type SportBest = { key: string; value: number; date: string; km: number; seconds: number; activity_id: string };
export type SportPerformance = {
  bests: SportBest[];
  longest: { week: string; km: number; date: string; activity_id: string }[];
  speed: { week: string; value: number }[];
};

/** Where the normal resting HR comes from: the last 60 days, the last 7 measured nights, or the value in Settings. */
export type RhrSource = "60d" | "recent" | "profile";

export type TrendsPlus = Omit<Trends, "insights" | "records" | "rules" | "recovery_daily"> & {
  insights: InsightCode[];
  records: Record<RecordKey, RecordRowPlus[]>;
  recovery_daily?: RecoveryDay[];
  /** The user's normal per recovery value: median of the last 60 days (api/trends.py recovery_normals). */
  recovery_normals?: Partial<Record<Exclude<keyof RecoveryDay, "date">, number | null>>;
  recent_records?: RecentRecord[];
  goal?: TrendsGoal | null;
  /** Last day of the form series; after a sync from the day before yesterday or older, the last synced day (`stopped_at_sync`). */
  form_until?: string | null;
  stopped_at_sync?: boolean;
  longest_runs?: LongestRun[];
  /** Swimming and cycling: bests, longest per week, pace (swim, s/100m) or speed (ride, km/h) per week (api/trends.py). */
  sport_performance?: Record<string, SportPerformance>;
  hr_flags?: HrFlag[];
  rules?: { race_min_km: number; race_hard_pct: number; predict_days: number; riegel: number; race_short_pct?: number; recent_record_days?: number };
};

/** ActivitySummary with the flag for unreliable wrist heart rate (GET /api/activities, when the API includes it). */
export type ActivitySummaryFlags = { hr_flags?: HrFlagReason[] };

export type FeedbackStatus = "new" | "planned" | "fixed" | "wontfix";
export type FeedbackItem = {
  id: number;
  app: "health";
  account_id: number | null; // the sender's trackerai account (null once it is gone)
  username: string | null;
  kind: "bug" | "idea";
  message: string;
  page: string | null;
  context: { site?: string; browser?: string; screen?: string; language?: string; theme?: string; version?: string | null; errors?: { message: string; where?: string; status?: number; at?: string }[] } | null;
  status: FeedbackStatus;
  reply: string | null;
  has_screenshot: boolean;
  created_at: string;
  updated_at: string | null;
};
