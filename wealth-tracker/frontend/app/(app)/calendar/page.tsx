"use client";

// Calendar — when something happens with your positions.
//
// Three kinds of date land here, and the whole design revolves around the fact
// that they are not equally well known:
//
//   · a publication date   — when a company releases its figures
//   · an ex-dividend date  — the day on which you secure the right to the payout
//   · a payment            — what actually arrived on your account
//
// All three are a *fact*: something that happened, or a date the source names.
// They get a cell in the grid.
//
// An estimate does not. The app has one rule about that, and it applies on every
// screen where one shows up: **an estimate sits on the month, never on the
// day.** The arithmetic behind an expected payout does produce an exact day — it
// has to count days — but that day is not knowledge. Hence the strip *below* the
// grid: "somewhere mid May", with a part of the month and no date.
//
// That is also exactly why this grid does not look empty for a portfolio of
// eleven trackers and one share. The official calendar knows nothing of a UCITS
// fund — Yahoo has no forward data for it — so without that strip a month with
// four expected payouts would show as an empty month.
//
// Whoever adds a cell here: never put an estimate in it. Then the grid lies.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDayMonth, fmtEuro, fmtMonth, monthName, WEEKDAY_ABBR } from "@/lib/format";
import { Eyebrow, Section, Tag } from "@/components/ds";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { ChevronLeftIcon, ChevronRightIcon, DownloadIcon } from "@trackerai/ui/icons";
import { partLabel, type Part } from "@/lib/dashboard";
import { tr, trx } from "@/lib/i18n";

type EventType = "earnings" | "ex_dividend" | "dividend_paid";

type Report = {
  kind: "filing" | "site";
  url: string | null;
  label: string | null;
  source: string | null;
};

type CalEvent = {
  date: string;
  type: EventType;
  isin: string;
  name: string | null;
  ticker?: string | null;
  pay_date?: string | null;
  amount_eur?: number | null;
  report?: Report | null;
};

type Estimate = {
  isin: string;
  name: string | null;
  type: "ex_dividend" | "earnings";
  month: string;
  part?: Part | null;
  from?: string;
  to?: string;
  expected_eur?: number | null;
  confidence?: "high" | "medium" | "low";
  cadence?: string | null;
  source: string;
};

type Calendar = {
  today: string;
  range: { from: string; to: string };
  events: CalEvent[];
  estimates: Estimate[];
  share_count: number;
  rest_of_year_eur: number | null;
};

// The three kinds, with their colour from the chart palette. The assignment
// follows the meaning the Dividend tab already uses: terracotta is always your
// own data, ochre is always an expectation. Publication dates are a third
// subject — not money — and therefore get slate blue and not a shade of the two
// that are about euros.
const KIND: Record<EventType, { color: string; label: string; short: string }> = {
  dividend_paid: { color: "var(--chart-1)", label: tr("Dividend paid"), short: tr("paid") },
  ex_dividend: { color: "var(--chart-3)", label: "Ex-dividend", short: "ex-dividend" },
  earnings: { color: "var(--chart-5)", label: tr("Results"), short: tr("results") },
};

const ESTIMATE_COLOR = "var(--chart-4)";

const WEEKDAYS = WEEKDAY_ABBR;

/** "August 2026" — in full above the grid, where there is room. */

function monthTitle(key: string): string {
  const [year, month] = key.split("-");
  return `${monthName(Number(month))} ${year}`;
}

function addMonths(key: string, delta: number): string {
  const [year, month] = key.split("-").map(Number);
  const total = year * 12 + (month - 1) + delta;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}

/**
 * The days of the month, with empty slots for the days before it.
 *
 * The week starts on Monday: getDay() gives 0 for Sunday, so (day + 6) % 7
 * shifts the columns to the Monday-first order. Without that shift every date
 * sits one day next to its column header, which you only notice when you look up
 * a known date — the kind of mistake that stays for months.
 */
function monthGrid(key: string): (string | null)[] {
  const [year, month] = key.split("-").map(Number);
  const first = new Date(Date.UTC(year, month - 1, 1));
  const lead = (first.getUTCDay() + 6) % 7;
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();

  const cells: (string | null)[] = Array(lead).fill(null);
  for (let d = 1; d <= days; d += 1) {
    cells.push(`${key}-${String(d).padStart(2, "0")}`);
  }
  // Padded to whole weeks, so the grid gets no half last row and the height does
  // not jump between a month of five and of six weeks.
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export default function CalendarPage() {
  const q = useQuery({
    queryKey: ["calendar"],
    queryFn: () => api.get<Calendar>("/api/calendar"),
  });

  const today = q.data?.today ?? new Date().toISOString().slice(0, 10);
  const [month, setMonth] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const current = month ?? today.slice(0, 7);

  const byDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>();
    for (const e of q.data?.events ?? []) {
      const list = map.get(e.date);
      if (list) list.push(e);
      else map.set(e.date, [e]);
    }
    return map;
  }, [q.data]);

  if (q.isLoading) {
    return <div className="h-96 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (q.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>{tr("The calendar could not load. Try again.")}</p>
    );
  }

  const data = q.data!;
  const cells = monthGrid(current);
  const monthEvents = data.events.filter((e) => e.date.startsWith(current));
  const monthEstimates = data.estimates.filter((e) => e.month === current);
  const shown = selected ? monthEvents.filter((e) => e.date === selected) : monthEvents;

  const canGoBack = current > data.range.from.slice(0, 7);
  const canGoForward = current < data.range.to.slice(0, 7);

  function goto(key: string) {
    setMonth(key);
    setSelected(null);
  }

  return (
    <div className="flex flex-col gap-11">
      <Next events={data.events} today={today} shareCount={data.share_count} onJump={goto} />

      <Section
        label={monthTitle(current)}
        info={
          <>{trx("A box means the date is fixed: a payout that has happened, or a date the source itself gives.{0}{1}Expected payouts aren't in it but in the strip below. Those are derived from your own payout history and are known to the month, not the day.", <br />, <br />)}</>
        }
        action={
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="ds-iconbtn ds-iconbtn--sm"
              disabled={!canGoBack}
              aria-label={tr("Previous month")}
              onClick={() => goto(addMonths(current, -1))}
            >
              <ChevronLeftIcon className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="ds-btn ds-btn--ghost ds-btn--sm"
              onClick={() => goto(today.slice(0, 7))}
            >{tr("Today")}</button>
            <button
              type="button"
              className="ds-iconbtn ds-iconbtn--sm"
              disabled={!canGoForward}
              aria-label={tr("Next month")}
              onClick={() => goto(addMonths(current, 1))}
            >
              <ChevronRightIcon className="h-4 w-4" />
            </button>
          </div>
        }
      >
        <Grid
          cells={cells}
          byDay={byDay}
          today={today}
          selected={selected}
          onSelect={(day) => setSelected((prev) => (prev === day ? null : day))}
        />

        <Strip estimates={monthEstimates} month={current} />
      </Section>

      <DayList
        events={shown}
        selected={selected}
        total={monthEvents.length}
        onClear={() => setSelected(null)}
      />

      <Legend />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The header: what comes first
// ---------------------------------------------------------------------------

function Next({
  events,
  today,
  shareCount,
  onJump,
}: {
  events: CalEvent[];
  today: string;
  shareCount: number;
  onJump: (month: string) => void;
}) {
  const next = events.find((e) => e.date >= today && e.type !== "dividend_paid");

  return (
    <div className="flex flex-col gap-2.5">
      <Eyebrow>{tr("Next up")}</Eyebrow>
      {next ? (
        <>
          <button
            type="button"
            onClick={() => onJump(next.date.slice(0, 7))}
            className="max-w-measure text-left font-display text-[26px] leading-tight tracking-[-0.02em] hover:text-brand"
          >
            {next.name ?? next.isin}
            <span className="text-ink-muted"> – {KIND[next.type].short}</span>
          </button>
          <p className="num text-sm text-ink-muted">
            {fmtDayMonth(next.date)}
            {next.date === today ? tr(" (today)") : ""}
          </p>
        </>
      ) : (
        <p className="max-w-measure text-[15px] leading-relaxed text-ink-muted">
          {shareCount === 0
            ? tr("You only own funds, and a fund doesn't publish results of its own. So what follows is about dividend: what has been paid, and what is still coming according to your own rhythm.")
            : tr("There is no confirmed date in the calendar right now. As soon as a company fixes its publication date, it appears here.")}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The grid — certain dates only
// ---------------------------------------------------------------------------

function Grid({
  cells,
  byDay,
  today,
  selected,
  onSelect,
}: {
  cells: (string | null)[];
  byDay: Map<string, CalEvent[]>;
  today: string;
  selected: string | null;
  onSelect: (day: string) => void;
}) {
  return (
    <div>
      <div className="grid grid-cols-7 gap-px">
        {WEEKDAYS.map((d) => (
          <div key={d} className="pb-1.5 text-center">
            <Eyebrow>{d}</Eyebrow>
          </div>
        ))}
      </div>

      <div
        className="grid grid-cols-7 gap-px overflow-hidden rounded-md"
        style={{ background: "var(--border-hairline)" }}
      >
        {cells.map((day, i) => {
          if (!day) {
            return <div key={`pad-${i}`} style={{ background: "var(--surface)" }} />;
          }
          const events = byDay.get(day) ?? [];
          const isToday = day === today;
          const isSelected = day === selected;
          // Only a day with something in it responds to a click. An empty day that lights
          // up when you touch it promises content that is not there.
          const clickable = events.length > 0;

          return (
            <button
              key={day}
              type="button"
              disabled={!clickable}
              aria-pressed={isSelected}
              aria-label={`${Number(day.slice(-2))}: ${
                events.length ? events.map((e) => KIND[e.type].short).join(", ") : tr("nothing")
              }`}
              onClick={() => clickable && onSelect(day)}
              className={`flex min-h-[62px] flex-col items-start gap-1 p-1.5 text-left transition-colors ${
                clickable ? "cursor-pointer hover:brightness-[0.97]" : "cursor-default"
              }`}
              style={{
                background: isSelected ? "var(--surface-active)" : "var(--surface)",
                boxShadow: isToday ? "inset 0 0 0 1.5px var(--brand)" : undefined,
              }}
            >
              <span
                className={`num text-xs leading-none ${
                  isToday ? "font-medium text-brand" : events.length ? "text-text" : "text-ink-muted"
                }`}
              >
                {Number(day.slice(-2))}
              </span>

              {/* A dot per event, not the name: on a phone a box is ~44px wide and no fund name
                  fits in it. The names are below the grid, where the row does have the width. */}
              <span className="flex flex-wrap gap-[3px]">
                {events.map((e, n) => (
                  <span
                    key={`${e.isin}-${e.type}-${n}`}
                    className="block h-[5px] w-[5px] rounded-full"
                    style={{ background: KIND[e.type].color }}
                  />
                ))}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The strip — everything known to the month and not to the day
// ---------------------------------------------------------------------------

function Strip({ estimates, month }: { estimates: Estimate[]; month: string }) {
  if (estimates.length === 0) return null;

  return (
    <div className="mt-5 flex flex-col gap-2.5">
      <span className="flex items-center gap-1">
        <Eyebrow>{trx("Sometime in {0}", fmtMonth(`${month}-01`))}</Eyebrow>
        <InfoPopover label={tr("Explanation estimates")}>{trx("Expected, not announced. Derived from the rhythm and the usual amount of your own earlier payouts, extended to the next time.{0}{1}That's why there is a part of the month and no date: the rhythm is known, the day isn't. A fund without a recognisable rhythm isn't shown at all: left out, not guessed.", <br />, <br />)}</InfoPopover>
      </span>

      <ul className="flex flex-col">
        {estimates.map((e, i) => (
          <li
            key={`${e.isin}-${e.month}-${i}`}
            className="flex items-baseline justify-between gap-4 border-t py-2 first:border-t-0"
            style={{ borderColor: "var(--border-hairline)" }}
          >
            <span className="flex min-w-0 items-baseline gap-2">
              <span
                className="mt-[1px] h-[5px] w-[5px] flex-none translate-y-[-2px] rounded-full"
                style={{ background: ESTIMATE_COLOR }}
              />
              <span className="truncate text-sm">{e.name ?? e.isin}</span>
            </span>
            <span className="num flex flex-none items-baseline gap-2.5 text-sm text-ink-muted">
              {e.type === "earnings" ? (
                <span>{trx("results, {0} – {1}", fmtDayMonth(e.from!), fmtDayMonth(e.to!))}</span>
              ) : (
                <>
                  <span>{e.part ? partLabel(e.part) : null}</span>
                  {typeof e.expected_eur === "number" && (
                    <span className="text-text">± {fmtEuro(e.expected_eur)}</span>
                  )}
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// What is in the grid, written out — with the report alongside
// ---------------------------------------------------------------------------

function DayList({
  events,
  selected,
  total,
  onClear,
}: {
  events: CalEvent[];
  selected: string | null;
  total: number;
  onClear: () => void;
}) {
  if (total === 0) {
    return (
      <Section label={tr("This month")} tone="quiet">
        <p className="max-w-measure text-sm leading-relaxed text-ink-muted">{tr("No fixed dates this month.")}</p>
      </Section>
    );
  }

  return (
    <Section
      label={selected ? fmtDayMonth(selected) : tr("This month")}
      meta={selected ? undefined : `${total} ${total === 1 ? "date" : "dates"}`}
      action={
        selected ? (
          <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" onClick={onClear}>{tr("Whole month")}</button>
        ) : undefined
      }
    >
      <ul className="flex flex-col">
        {events.map((e, i) => (
          <li
            key={`${e.date}-${e.isin}-${e.type}-${i}`}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t py-3 first:border-t-0"
            style={{ borderColor: "var(--border-hairline)" }}
          >
            <span className="flex min-w-0 items-baseline gap-2.5">
              <span
                className="h-[6px] w-[6px] flex-none translate-y-[-2px] rounded-full"
                style={{ background: KIND[e.type].color }}
              />
              <span className="num w-[52px] flex-none text-sm text-ink-muted">
                {fmtDayMonth(e.date)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm">{e.name ?? e.isin}</span>
                <span className="block text-xs text-ink-muted">
                  {KIND[e.type].label}
                  {e.type === "ex_dividend" && e.pay_date
                    ? tr(" (payout {0})", fmtDayMonth(e.pay_date))
                    : ""}
                </span>
              </span>
            </span>

            <span className="flex flex-none items-baseline gap-3">
              {typeof e.amount_eur === "number" && (
                <span className="num text-sm">{fmtEuro(e.amount_eur)}</span>
              )}
              {e.type === "earnings" && <ReportLink report={e.report ?? null} />}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * The way to the report itself, and honest about which way that is.
 *
 * For a US share that is the filing at the SEC: a direct link to the document.
 * For everything else that source does not exist yet — Europe's counterpart
 * (ESAP) only opens to the public in July 2027 — and the best there is, is the
 * company's website.
 *
 * Those two therefore do not get the same label. A button that says "Report" and
 * ends up on a homepage is convincing for exactly one click.
 */
function ReportLink({ report }: { report: Report | null }) {
  if (!report?.url) return null;

  if (report.kind === "filing") {
    return (
      <a
        href={report.url}
        target="_blank"
        rel="noopener noreferrer"
        className="ds-btn ds-btn--secondary ds-btn--sm"
      >
        <DownloadIcon className="ds-btn__icon" />
        {report.label ?? tr("Report")}
      </a>
    );
  }

  return (
    <a
      href={report.url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-xs text-ink-muted underline decoration-dotted underline-offset-2 hover:text-brand"
    >{tr("company website")}</a>
  );
}

// ---------------------------------------------------------------------------

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {(Object.keys(KIND) as EventType[]).map((k) => (
        <span key={k} className="flex items-center gap-2">
          <span
            className="h-[6px] w-[6px] rounded-full"
            style={{ background: KIND[k].color }}
          />
          <span className="text-xs text-ink-muted">{KIND[k].label}</span>
        </span>
      ))}
      <span className="flex items-center gap-2">
        <span className="h-[6px] w-[6px] rounded-full" style={{ background: ESTIMATE_COLOR }} />
        <span className="text-xs text-ink-muted">{tr("Estimate: to the month, not the day")}</span>
      </span>
      <Tag>Yahoo Finance</Tag>
    </div>
  );
}
