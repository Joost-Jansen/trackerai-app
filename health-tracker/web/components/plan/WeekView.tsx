"use client";

// One week of the plan: seven days stacked, per day the sessions stacked (two workouts on one day
// sit under one date), empty days as a narrow rest row. Past weeks are collapsed to their head line.
// A done session can be unlinked from its activity, an open one linked by hand to an activity close by (`onLink`).

import Link from "next/link";
import { Tag } from "@/components/ds";
import { ChevronDownIcon, RouteIcon } from "@trackerai/ui/icons";
import { routeName, useFormat, useT, type Format } from "@/lib/i18n";
import type { PlanSession } from "@/lib/training";
import { type Week, STATUS_TONE, capitalise, fmtWeekRange, parseIso, sportColour } from "./plan";
import { SportBadge, SportGlyph } from "./SportIcon";
import ZoneChip from "./ZoneChip";

const activityHref = (id: string) => `/history/activity/?id=${encodeURIComponent(id)}`;
const routeHref = (id: string) => `/routes/route/?id=${encodeURIComponent(id)}`;
const RACE = /\b(wedstrijd|race)\b(?!\s*-?\s*(tempo|pace))/i; // not "race pace"

/** Link an activity to the session on `sessionDate`, or with null keep it out of the plan. */
type OnLink = (activityId: string, sessionDate: string | null) => void;
const linkBtn = "whitespace-nowrap font-medium text-ink-muted underline-offset-2 hover:text-[var(--text-link-hover)] hover:underline";

function amount(s: PlanSession, f: Format) {
  if (s.distance_km) return `${f.trim(s.distance_km)} km`;
  if (s.duration_min) return s.duration_min >= 90 ? `${Math.floor(s.duration_min / 60)}:${String(s.duration_min % 60).padStart(2, "0")} ${f.hourUnit}` : `${s.duration_min} min`;
  return null;
}

/** Only what differs from "planned" gets a label; today is already shown above the day. */
function StatusTag({ s }: { s: PlanSession }) {
  const t = useT();
  if (s.status !== "done" && s.status !== "missed") return null;
  const tone = STATUS_TONE[s.status];
  return (
    <Tag tone={tone} outline={tone === "neutral"} className="flex-none">
      {s.status === "done" && (
        <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M2.5 6.2 4.8 8.5 9.5 3.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      )}
      {t.plan.statuses[s.status]}
    </Tag>
  );
}

function Done({ s, onLink }: { s: PlanSession; onLink?: OnLink }) {
  const t = useT();
  const f = useFormat();
  const T = t.texts;
  const d = s.done!;
  const zone = d.zone_pct != null && s.target_zone ? T.plan.zoneFit(d.zone_pct, s.target_zone) : null;
  const zoneTone = d.zone_pct == null ? "" : d.zone_pct >= 80 ? "text-gain" : d.zone_pct >= 60 ? "" : "text-loss";
  const bits = [
    d.distance_km ? `${f.trim(d.distance_km, 2)} km` : null,
    d.moving_time_s ? f.clock(d.moving_time_s) : null,
    d.distance_km && d.moving_time_s && s.sport !== "strength_training" ? f.intensity({ sport: s.sport, moving_time_s: d.moving_time_s, distance_km: d.distance_km }) : null,
    d.avg_hr ? `${d.avg_hr} bpm` : null,
  ].filter(Boolean);
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-[var(--surface-gain-soft)] px-2.5 py-1.5 text-[12px] tabular-nums">
      <span className="font-semibold text-gain">{t.plan.week.done}</span>
      <span>{bits.join(" · ")}</span>
      {zone && <span className={zoneTone} title={T.plan.zoneFitMethod}>· {zone}</span>}
      {d.date && d.date !== s.date && (
        <span className="text-ink-muted" title={s.match === "near" ? t.plan.week.nearHint : undefined}>
          · {t.plan.week.doneOn(f.weekdayDay(d.date))}{s.match === "near" ? ` (${t.plan.week.auto})` : ""}
        </span>
      )}
      <span className="ml-auto flex items-center gap-3">
        {onLink && s.activity_ids?.length ? (
          <button type="button" className={linkBtn} title={t.plan.week.unlinkHint} onClick={() => s.activity_ids!.forEach((id) => onLink(id, null))}>
            {t.plan.week.unlink}
          </button>
        ) : null}
        {s.activity_ids?.[0] && (
          <Link className={linkBtn} href={activityHref(s.activity_ids[0])}>
            {t.plan.week.view}
          </Link>
        )}
      </span>
    </div>
  );
}

function Route({ s }: { s: PlanSession }) {
  const t = useT();
  const f = useFormat();
  const link = "underline decoration-[var(--border-strong)] underline-offset-2 hover:text-[var(--text-link-hover)] hover:decoration-current";
  if (s.route) {
    return (
      <p className="mt-1 flex items-center gap-1.5 text-[12px] text-ink-muted">
        <RouteIcon width={13} height={13} className="flex-none" />
        <span>
          {t.plan.week.routeLabel}<Link className={link} href={routeHref(s.route.id)}>{routeName(s.route.name, s.route.id, t, f)}</Link>
          {s.route.distance_km ? ` · ${f.trim(s.route.distance_km)} km` : ""}
        </span>
      </p>
    );
  }
  const r = s.route_suggestion;
  if (!r) return null;
  return (
    <p className="mt-1 flex items-center gap-1.5 text-[12px] text-ink-muted">
      <RouteIcon width={13} height={13} className="flex-none" />
      <span>
        {t.plan.week.suggestion}
        {r.parts.map((id, i) => (
          <span key={`${id}-${i}`}>
            {i > 0 && " + "}
            <Link className={link} href={routeHref(id)}>{routeName(r.names[i], id, t, f)}</Link>
          </span>
        ))}
        {r.parts.length > 1 || !r.within_tolerance ? ` · ${f.trim(r.total_km)} km${r.within_tolerance ? "" : t.plan.week.closest}` : ""}
      </span>
    </p>
  );
}

/** Open sessions: link an activity of the same sport from the days around it by hand. */
function LinkPicker({ s, onLink }: { s: PlanSession; onLink: OnLink }) {
  const t = useT();
  const f = useFormat();
  if (!s.candidates?.length) return null;
  return (
    <label className="mt-1.5 flex items-center gap-2 text-[12px] text-ink-muted">
      <span>{t.plan.week.linkLabel}</span>
      <select
        className="min-w-0 rounded border border-border bg-surface px-1.5 py-0.5 text-[12px] tabular-nums text-[var(--text-primary)]"
        value=""
        onChange={(e) => e.target.value && onLink(e.target.value, s.date)}
      >
        <option value="">{t.plan.week.linkPick}</option>
        {s.candidates.map((c) => (
          <option key={c.id} value={c.id}>
            {[f.weekdayDay(c.date), c.distance_km ? `${f.trim(c.distance_km, 2)} km` : null, c.moving_time_s ? f.clock(c.moving_time_s) : null].filter(Boolean).join(" · ")}
          </option>
        ))}
      </select>
    </label>
  );
}

function SessionItem({ s, onLink }: { s: PlanSession; onLink?: OnLink }) {
  const t = useT();
  const f = useFormat();
  const race = RACE.test(s.kind ?? "");
  const title = s.kind ? capitalise(s.kind) : t.sport(s.sport);
  const amt = amount(s, f);
  return (
    <div className={`flex gap-3 ${s.status === "missed" ? "opacity-75" : ""}`}>
      <SportBadge sport={s.sport} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 pt-[3px]">
            <span className={`text-[14px] font-semibold ${s.status === "missed" ? "line-through decoration-[var(--text-loss)] decoration-1" : ""}`}>{title}</span>
            {amt && <span className="text-[14px] tabular-nums">{amt}</span>}
            {s.kind && <span className="text-[12px] text-ink-muted">{t.sport(s.sport)}</span>}
            <ZoneChip zone={s.target_zone} />
            {race && <Tag tone="brand">{t.plan.week.race}</Tag>}
          </div>
          <StatusTag s={s} />
        </div>
        {s.description && <p className="mt-0.5 max-w-[72ch] text-[12.5px] leading-relaxed text-ink-muted">{s.description}</p>}
        {s.done && <Done s={s} onLink={onLink} />}
        {s.status !== "done" && s.status !== "missed" && <Route s={s} />}
        {s.status !== "done" && onLink && <LinkPicker s={s} onLink={onLink} />}
      </div>
    </div>
  );
}

function DateCell({ date, today, compact }: { date: string; today: boolean; compact?: boolean }) {
  const f = useFormat();
  const d = parseIso(date);
  const tone = today ? "text-brand" : "text-ink-muted";
  if (compact) {
    return (
      <span className={`flex items-baseline gap-1 text-[12px] ${tone}`}>
        <span className="min-w-[26px] whitespace-nowrap font-semibold uppercase tracking-[0.06em]">{f.weekday(date)}</span>
        <span className="tabular-nums">{d.getDate()}</span>
      </span>
    );
  }
  return (
    <span className={`flex flex-col leading-none ${tone}`}>
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em]">{f.weekday(date)}</span>
      <span className={`mt-1 font-display text-[24px] font-light tabular-nums ${today ? "" : "text-[var(--text-primary)]"}`}>{d.getDate()}</span>
      <span className="mt-0.5 text-[11px]">{f.monthShort(date)}</span>
    </span>
  );
}

function DayRow({ date, sessions, today, onLink }: { date: string; sessions: PlanSession[]; today: string; onLink?: OnLink }) {
  const t = useT();
  const isToday = date === today;
  const rest = sessions.length === 0 || sessions.every((s) => s.sport === "rest");
  const base = "grid grid-cols-[48px_1fr] gap-x-3 sm:grid-cols-[64px_1fr] sm:gap-x-4";
  const todayCls = isToday ? "relative -mx-3 rounded-md bg-[var(--surface-brand-soft)] px-3 sm:-mx-4 sm:px-4" : "";
  if (rest) {
    const note = sessions.map((s) => s.description).filter(Boolean).join(" ");
    return (
      <li className={`${base} items-center border-t border-[var(--border-subtle)] py-2 first:border-t-0 ${todayCls}`}>
        <DateCell date={date} today={isToday} compact />
        <span className="flex min-w-0 items-center gap-2 text-[12px] text-[var(--text-faint)]">
          <SportGlyph sport="rest" width={13} height={13} className="flex-none" />
          <span className="flex-none">{isToday ? t.plan.week.todayRest : t.plan.week.rest}</span>
          {note && <span className="truncate text-ink-muted">· {note}</span>}
        </span>
      </li>
    );
  }
  return (
    <li className={`${base} border-t border-[var(--border-subtle)] py-3.5 first:border-t-0 ${todayCls}`}>
      <DateCell date={date} today={isToday} />
      <div className="flex min-w-0 flex-col gap-3.5">
        {isToday && <span className="-mb-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-brand">{t.plan.week.today}</span>}
        {sessions.filter((s) => s.sport !== "rest").map((s, i) => <SessionItem key={s.id ?? i} s={s} onLink={onLink} />)}
      </div>
    </li>
  );
}

/** A strip with one block per session in the colour of its status: how the week is going at a glance. */
function Strip({ sessions }: { sessions: PlanSession[] }) {
  const items = sessions.filter((s) => s.sport !== "rest");
  const colour: Record<string, string> = {
    done: "var(--data-gain)",
    missed: "var(--data-loss)",
    today: "var(--surface-brand)",
    planned: "var(--surface-inset)",
  };
  return (
    <span className="flex h-[6px] w-full max-w-[220px] gap-[3px]" aria-hidden>
      {items.map((s, i) => <span key={i} className="flex-1 rounded-full" style={{ background: colour[s.status ?? "planned"] ?? "var(--surface-inset)" }} />)}
    </span>
  );
}

export default function WeekCard({
  week,
  index,
  count,
  today,
  raceDate,
  open,
  onToggle,
  onLink,
}: {
  week: Week;
  index: number;
  count: number;
  today: string;
  raceDate: string | null;
  open: boolean;
  onToggle: () => void;
  onLink?: OnLink;
}) {
  const t = useT();
  const f = useFormat();
  const w = t.plan.week;
  const current = today >= week.monday && today <= week.days[6].date;
  const past = week.days[6].date < today;
  const isRaceWeek = !!raceDate && raceDate >= week.monday && raceDate <= week.days[6].date;
  const train = week.sessions.filter((s) => s.sport !== "rest");
  const done = train.filter((s) => s.status === "done").length;
  const missed = train.filter((s) => s.status === "missed").length;
  const km = Object.entries(week.km).filter(([, v]) => v.planned > 0 || v.done > 0);
  const label = current ? w.thisWeek : isRaceWeek ? w.raceWeek : index === 0 && !past ? w.firstWeek : w.week(index + 1);

  return (
    <section className={`rounded border bg-surface ${current ? "border-[var(--border-strong)]" : "border-border"}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5 text-left sm:px-[18px]"
      >
        <span className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
          <span className="flex items-center gap-2">
            <span className="text-[13.5px] font-semibold">{label}</span>
            {current && isRaceWeek && <Tag tone="brand">{w.raceWeek}</Tag>}
          </span>
          <span className="text-[12px] text-ink-muted">
            {fmtWeekRange(week.monday, f)} · {w.weekOf(index + 1, count)}
          </span>
        </span>
        <span className="flex items-center gap-3 text-[12px] tabular-nums text-ink-muted">
          {train.length > 0 && (
            <span className="hidden items-center gap-2 sm:flex">
              <Strip sessions={week.sessions} />
            </span>
          )}
          <span>
            {past || current ? w.doneCount(done, train.length) : w.sessions(train.length)}
            {missed > 0 && <span className="text-loss"> · {w.missed(missed)}</span>}
          </span>
          <ChevronDownIcon width={16} height={16} className={`flex-none transition-transform ${open ? "rotate-180" : ""}`} />
        </span>
        {km.length > 0 && (
          <span className="flex w-full flex-wrap gap-x-4 gap-y-1 text-[12px] tabular-nums text-ink-muted">
            {km.map(([sport, v]) => (
              <span key={sport} className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: sportColour(sport) }} aria-hidden />
                {t.sport(sport)}{" "}
                <span className="text-[var(--text-primary)]">
                  {past || current ? `${f.trim(v.done)} / ` : ""}
                  {f.trim(v.planned)} km
                </span>
              </span>
            ))}
          </span>
        )}
      </button>
      {open && (
        <ul className="border-t border-border px-4 pb-1 sm:px-[18px]">
          {week.days.filter((d) => !d.outside).map((d) => <DayRow key={d.date} date={d.date} sessions={d.sessions} today={today} onLink={onLink} />)}
        </ul>
      )}
    </section>
  );
}
