// Plan this week: per sport planned against done, how many sessions done, missed and to go, and at the top the
// countdown to the plan's next race. Only with an active plan.

import Card from "@trackerai/ui/components/Card";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { SportBadge } from "@/components/plan/SportIcon";
import { useFormat, useT } from "@/lib/i18n";
import type { NextRace, PlanWeekSport, PlanWeekSummary } from "@/lib/training";

const SPORT_ORDER = ["run", "ride", "swim"];
const bySportOrder = (a: string, b: string) => (SPORT_ORDER.indexOf(a) + 1 || 99) - (SPORT_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b);

function Countdown({ race }: { race: NextRace }) {
  const t = useT().texts.today.race;
  const f = useFormat();
  const today = race.days === 0;
  return (
    <div className="mb-3.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 rounded-md bg-[var(--surface-brand-soft)] px-3.5 py-2.5">
      <span className="font-display text-[30px] font-light leading-none tabular-nums text-brand">{today ? t.today : race.days}</span>
      <span className="text-[13px] text-[var(--text-secondary)]">
        {today ? t.todayIs(race.name) : `${t.days(race.days)} ${t.until(race.name)}`}
      </span>
      <span className="w-full text-[12px] text-ink-muted sm:ml-auto sm:w-auto">
        {[f.long(race.date), race.distance_km ? f.km(race.distance_km) : null].filter(Boolean).join(" · ")}
      </span>
    </div>
  );
}

/** Kilometres when the plan has distances, otherwise the time. A sport done without a session this week shows only
 *  what was done. */
function SportRow({ sport, row }: { sport: string; row: PlanWeekSport }) {
  const tt = useT();
  const t = tt.texts.today.planWeek;
  const f = useFormat();
  const byKm = row.planned_km > 0;
  const planned = byKm ? row.planned_km : row.planned_s;
  const done = byKm ? row.done_km : row.done_s;
  const unplanned = row.sessions === 0;
  const pct = unplanned ? 100 : planned ? Math.min(100, (done / planned) * 100) : (row.done / row.sessions) * 100;
  const amount = unplanned
    ? row.done_km > 0 ? f.km(row.done_km) : f.duration(row.done_s)
    : byKm ? t.ofPlanned(f.km(row.done_km), f.km(row.planned_km)) : planned ? t.ofPlanned(f.duration(row.done_s), f.duration(row.planned_s)) : t.ofPlanned(String(row.done), String(row.sessions));
  return (
    <li className="grid grid-cols-[22px_1fr_auto] items-baseline gap-x-2.5 gap-y-1 border-t border-border py-2 text-[13px] first:border-t-0">
      <span className="row-span-2 self-center"><SportBadge sport={sport} size={22} /></span>
      <span className="font-medium">{tt.sport(sport)}</span>
      <span className="text-right tabular-nums">
        {amount}
        {byKm && row.planned_s > 0 && <span className="ml-2 text-[11.5px] text-ink-muted">{t.ofPlanned(f.duration(row.done_s), f.duration(row.planned_s))}</span>}
      </span>
      <span className="col-span-2 block h-1.5 overflow-hidden rounded-full bg-[var(--surface-inset)]">
        <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: "var(--data-gain)" }} />
      </span>
    </li>
  );
}

export default function PlanWeekCard({ week, race, className = "" }: { week: PlanWeekSummary; race?: NextRace | null; className?: string }) {
  const t = useT().texts.today.planWeek;
  const sports = Object.keys(week.sports).sort(bySportOrder);
  const c = week.sessions;
  return (
    <Card title={t.title} className={className} action={<InfoPopover label={t.info}>{t.method}</InfoPopover>}>
      {race && <Countdown race={race} />}
      {sports.length === 0 ? (
        <p className="text-[13px] text-ink-muted">{t.empty}</p>
      ) : (
        <>
          <ul className="flex flex-col">
            {sports.map((s) => <SportRow key={s} sport={s} row={week.sports[s]} />)}
          </ul>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] tabular-nums text-ink-muted">
            <span className="font-medium text-[var(--text-primary)]">{t.done(c.done, c.total)}</span>
            {c.missed > 0 && <span className="text-loss">{t.missed(c.missed)}</span>}
            {c.upcoming > 0 && <span>{t.upcoming(c.upcoming)}</span>}
            {c.unsynced > 0 && <span>{t.unsynced(c.unsynced)}</span>}
          </p>
        </>
      )}
    </Card>
  );
}
