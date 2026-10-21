"use client";

// Dividend — the money that comes in without you selling anything.
//
// The dashboard has a dividend card, and it stays: it answers "is something
// coming" in four lines. This tab answers the questions a card has no room for —
// when it comes in, spread over a year, which funds bring it in, what tax takes
// off, and what it has all been together.
//
// Two rules stand above everything here, both taken over from the estimate on
// the dashboard, because here they ring twice as loud:
//
//   * An estimate sits on the month, never on the day. The schedule arithmetic
//     produces an exact date because it has to count days; that date is not
//     knowledge. Only an official ex-dividend date gets a day.
//   * A fund without a recognisable rhythm gets *no* expectation. Left out, not
//     guessed.
//
// What is missing here and must be missing: a dividend yield that points to the
// future like a promise. Every percentage on this page is measured over the past
// twelve months or explicitly an estimate, and says so.

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDayMonth, fmtDayMonthYear, fmtEuro, fmtMonth, fmtPercent, monthAbbr, monthName } from "@/lib/format";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { Eyebrow, Hero, Section, Tag } from "@/components/ds";
import { trueMinus } from "@trackerai/ui/lib/typography";
import Disclosure from "@/components/etf/Disclosure";
import DownloadCsv from "@/components/etf/DownloadCsv";
import Bars, { type BarDatum } from "@trackerai/ui/charts/Bars";
import HBars from "@/components/charts/HBars";
import LineChart from "@trackerai/ui/charts/LineChart";
import { cadenceLabel, partLabel, type Part } from "@/lib/dashboard";
import { tr, trx } from "@/lib/i18n";

type Totals = {
  net: number;
  gross: number;
  tax: number;
  tax_pct: number | null;
  payments: number;
  first_payment: string | null;
  last_payment: string | null;
  ttm_net: number;
  prev_ttm_net: number;
  ttm_growth_pct: number | null;
  this_year_net: number;
  last_year_ytd_net: number;
  last_year_net: number;
  expected_rest_of_year: number;
  expected_year_total: number;
  forward_12m_net: number;
  forward_monthly_avg: number;
  yield_on_cost_pct: number | null;
  yield_on_value_pct: number | null;
  forward_yield_on_cost_pct: number | null;
  share_of_profit_pct: number | null;
  best_month: { month: string; net: number } | null;
  years: number;
  payers: number;
  positions: number;
};

type YearRow = {
  year: string;
  gross: number;
  tax: number;
  net: number;
  payments: number;
  expected: number;
  partial: boolean;
};

type MonthRow = { month: string; net: number; expected: number; future: boolean };
type SeasonRow = {
  month: number;
  label: string;
  total: number;
  years: number;
  share_pct: number | null;
};

type StockRow = {
  isin: string;
  name: string;
  held: boolean;
  gross: number;
  tax: number;
  net: number;
  ttm_net: number;
  payments: number;
  first: string;
  last: string;
  share_pct: number | null;
  cadence: string | null;
  yield_on_cost_pct: number | null;
  invested: number | null;
  next: {
    date: string;
    month: string;
    part: string;
    expected_eur: number | null;
    source: string;
    cadence: string | null;
  } | null;
};

type Upcoming = {
  isin: string;
  name: string | null;
  date: string;
  month: string;
  part: Part;
  expected_eur: number | null;
  cadence: string | null;
  confidence: "high" | "medium" | "low";
  source: "estimate" | "official";
};

type Payment = {
  date: string;
  isin: string;
  name: string;
  gross_eur: number;
  tax_eur: number;
  net_eur: number;
  currency: string;
};

type Dividend = {
  totals: Totals;
  by_year: YearRow[];
  by_month: MonthRow[];
  seasonality: SeasonRow[];
  cumulative: { d: string; v: number }[];
  by_stock: StockRow[];
  upcoming: Upcoming[];
  payments: Payment[];
};

// Meridian's chart palette, in order of importance: what you actually received
// is your own data (series 1, terracotta), what is still expected is the
// comparison next to it (series 4, ochre — a warning colour, because it is an
// estimate). The seasonal pattern is a third subject and gets olive.
const RECEIVED = "var(--chart-1)";
const EXPECTED = "var(--chart-4)";
const SEASON = "var(--chart-3)";

/** "Aug 2026" — the month label the dashboard card also uses. */
function monthLabel(iso: string): string {
  return `${fmtMonth(iso)} ${iso.slice(0, 4)}`;
}

/**
 * How an expected payment is marked in time: an official one gets a day, an
 *  estimate no further than "end of Aug".
 */
function whenLabel(item: { source: string; date: string; part: string; month: string }): string {
  return item.source === "official" ? fmtDayMonth(item.date) : `${partLabel(item.part)} ${fmtMonth(item.month)}`;
}

/**
 * A supporting number with its explanation button. No tile with a border around
 *  it — a card per statistic is exactly what this design does not want; scale
 *  and space do the work.
 */
function Tile({ label, value, sub, info }: { label: string; value: string; sub?: React.ReactNode; info?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-[5px]">
      <span className="flex items-center gap-1">
        <Eyebrow>{label}</Eyebrow>
        {info && <InfoPopover label={tr("Explanation {0}", label)}>{info}</InfoPopover>}
      </span>
      <span className="num font-display text-[21px] leading-tight tracking-[-0.02em]">{value}</span>
      {/* Always a line, even when empty: otherwise four figures stand side by side at four
          different heights. */}
      <span className="num min-h-[16px] text-xs leading-[16px] text-ink-muted">{sub}</span>
    </div>
  );
}

export default function DividendPage() {
  const q = useQuery({
    queryKey: ["dividend"],
    queryFn: () => api.get<Dividend>("/api/dividend"),
  });

  if (q.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (q.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("Dividend could not load. Try again.")}
      </p>
    );
  }

  const data = q.data!;
  const t = data.totals;

  if (t.payments === 0 && data.upcoming.length === 0) {
    return (
      <Section label="Dividend">
        <p className="max-w-measure text-sm leading-relaxed text-ink-muted">
          {trx(
            "No dividend received yet. As soon as a payout is in your {0} and you upload that file, your calendar, yearly totals and the yield you get from it appear here.",
            <b className="text-text">{tr("Account statement")}</b>,
          )}
        </p>
      </Section>
    );
  }

  return (
    <div className="flex flex-col gap-11">
      <Summary totals={t} />
      <Agenda upcoming={data.upcoming} totals={t} />
      <PerYear rows={data.by_year} totals={t} />
      <PerMonth rows={data.by_month} />
      <Seasons rows={data.seasonality} totals={t} />
      <Cumulative points={data.cumulative} totals={t} />
      <PerStock rows={data.by_stock} totals={t} />
      <PaymentLog payments={data.payments} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The header: four numbers and the two sentences that belong below them
// ---------------------------------------------------------------------------

function Summary({ totals: t }: { totals: Totals }) {
  const growth = t.ttm_growth_pct;
  return (
    <div>
      {/* The hero number of this screen: what was actually credited over the last twelve months.
          The three figures below put it in perspective — this design's framing rule in miniature. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <span className="flex items-center gap-1">
          <Eyebrow>{tr("Last 12 months")}</Eyebrow>
          <InfoPopover label={tr("Explanation last 12 months")}>
            {trx(
              'Everything that was actually credited over the past 365 days, after dividend tax.{0}{1}A {2} year and not the calendar year, because in January a calendar year is three days long. Every percentage on this page about "a year" is measured over this window.',
              <br />,
              <br />,
              <b>{tr("rolling")}</b>,
            )}
          </InfoPopover>
        </span>
        <span className="text-xs text-ink-muted">
          {trx(
            "{0} of your {1} {2}",
            <span className="num">{t.payers}</span>,
            <span className="num">{t.positions}</span>,
            t.positions === 1 ? tr("position pays out") : tr("positions pay out"),
          )}
        </span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-end gap-x-7 gap-y-2">
        <Hero>{fmtEuro(t.ttm_net)}</Hero>
        <span className="pb-2 text-[13px] text-ink-muted">
          {growth !== null ? (
            <>
              {trx(
                "{0} compared with the 12 months before",
                <span className="num" style={{ color: growth >= 0 ? "var(--text-gain)" : "var(--text-loss)" }}>
                  {trueMinus(fmtPercent(growth, { decimals: 0, plus: true }))}
                </span>,
              )}
            </>
          ) : (
            tr("first year with payouts")
          )}
        </span>
      </div>

      <div
        className="mt-7 grid grid-cols-2 gap-x-10 gap-y-6 pt-3.5 sm:grid-cols-3 sm:gap-x-12"
        style={{ borderTop: "1px solid var(--border-hairline)" }}
      >
        <Tile
          label={tr("This year ({0})", new Date().getFullYear())}
          value={fmtEuro(t.this_year_net)}
          sub={t.last_year_ytd_net > 0 ? <>{trx("last year at this date {0}", fmtEuro(t.last_year_ytd_net))}</> : null}
        />
        <Tile
          label={tr("Expected this year")}
          // Without an estimate this is not an expectation but simply what is already
          // there; the ± sign would suggest a look ahead that is not there.
          value={t.expected_rest_of_year > 0 ? `± ${fmtEuro(t.expected_year_total)}` : fmtEuro(t.expected_year_total)}
          info={
            <>
              {trx(
                "What came in this calendar year plus what the schedule of your own funds still expects before 31 December.{0}{1}The second part is an {2}: the rhythm and the usual amount of your own payout history, extended. Not an official announcement. Funds without a recognisable rhythm aren't included; they are left out, not guessed.",
                <br />,
                <br />,
                <b>{tr("estimate")}</b>,
              )}
            </>
          }
          sub={
            t.expected_rest_of_year > 0 ? (
              <>{trx("± {0} still to come", fmtEuro(t.expected_rest_of_year))}</>
            ) : (
              <>{tr("nothing more expected this year")}</>
            )
          }
        />
        <Tile
          label={tr("Per month")}
          // "± €0.00" is exactly the guess this tab refuses to make: it reads as "you get
          // nothing more", while it means that no fund has enough history to derive a
          // rhythm from.
          value={t.forward_12m_net > 0 ? `± ${fmtEuro(t.forward_monthly_avg)}` : "–"}
          info={
            <>
              {trx(
                'The expected payouts of the coming twelve months, divided by twelve.{0}{1}A whole year ahead and not half, otherwise this number would change with the month you happen to look in: a quarterly payer falls twice in one half-year and three times in the other.{2}{3}It is an average over months that differ hugely: see "In which months does it come in" below. There is no month in which this amount is really in your account.',
                <br />,
                <br />,
                <br />,
                <br />,
              )}
            </>
          }
          sub={
            t.forward_12m_net > 0 ? (
              <>{trx("± {0} over 12 months", fmtEuro(t.forward_12m_net))}</>
            ) : (
              <>{tr("no rhythm to calculate with yet")}</>
            )
          }
        />
      </div>

      <div className="mt-7 flex max-w-measure flex-col gap-2 text-[13px] leading-relaxed text-ink-muted">
        {t.yield_on_cost_pct !== null && (
          <p>
            <span className="flex items-center gap-1">
              <span>
                {trx(
                  "That is {0} per year on what you put in{1}.",
                  <b className="num text-text">{fmtPercent(t.yield_on_cost_pct, { decimals: 2 })}</b>,
                  t.yield_on_value_pct !== null && (
                    <>
                      {trx(
                        ", and {0} on what your portfolio is worth now",
                        <b className="num text-text">{fmtPercent(t.yield_on_value_pct, { decimals: 2 })}</b>,
                      )}
                    </>
                  ),
                )}
              </span>
              <InfoPopover label={tr("Explanation dividend yield")}>
                {trx(
                  "{0}{1}{2}{3}: what your purchases yield you each year. This number rises by itself as your positions are held longer and companies raise their payout: the numerator grows, the denominator is what you once paid.{4}{5}{6}: what you would get now if you invested the same amount today. This is the number you can compare with a savings rate or another fund.{7}{8}Both measured over the last twelve months and over your whole portfolio, so also over funds that pay nothing. An accumulating ETF pushes them down without you missing anything: that gain is in the price.",
                  <b>{tr("Two denominators, two questions.")}</b>,
                  <br />,
                  <br />,
                  <b>{tr("On your deposits")}</b>,
                  <br />,
                  <br />,
                  <b>{tr("On the current value")}</b>,
                  <br />,
                  <br />,
                )}
              </InfoPopover>
            </span>
          </p>
        )}
        <p>
          {trx(
            "Since {0} received {1} in total over {2} {3}{4}.",
            <span className="num">{t.first_payment ? fmtDayMonthYear(t.first_payment) : "–"}</span>,
            <b className="num text-text">{fmtEuro(t.net)}</b>,
            <span className="num">{t.payments}</span>,
            t.payments === 1 ? tr("payout") : tr("payouts"),
            t.share_of_profit_pct !== null && (
              <> {trx("({0} of your total gain)", <span className="num">{fmtPercent(t.share_of_profit_pct, { decimals: 0 })}</span>)}</>
            ),
          )}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The agenda
// ---------------------------------------------------------------------------

function Agenda({ upcoming, totals }: { upcoming: Upcoming[]; totals: Totals }) {
  if (upcoming.length === 0) {
    return (
      <Section
        label={tr("When does dividend come in")}
        infoLabel={tr("Explanation the dividend calendar")}
        info={
          <>
            {trx(
              "An expectation is only shown for a fund whose own history shows a recognisable rhythm: at least two payouts with an even interval.{0}{1}One payment, or an erratic pattern, gives no estimate. Those funds are left out, not guessed.",
              <br />,
              <br />,
            )}
          </>
        }
      >
        <p className="max-w-measure text-sm leading-relaxed text-ink-muted">
          {tr('No expected payments. Here that doesn\'t mean "nothing is coming" but "there is nothing to say".')}
        </p>
      </Section>
    );
  }

  // Grouped by month and not printed flat: an estimate sits on the month anyway,
  // so the month is the unit in which this list has meaning.
  const months: { month: string; items: Upcoming[]; total: number }[] = [];
  for (const item of upcoming) {
    const last = months[months.length - 1];
    if (last && last.month === item.month) {
      last.items.push(item);
      last.total += item.expected_eur ?? 0;
    } else {
      months.push({ month: item.month, items: [item], total: item.expected_eur ?? 0 });
    }
  }

  const anyEstimate = upcoming.some((u) => u.source === "estimate");

  return (
    <Section
      label={tr("When does dividend come in")}
      infoLabel={tr("Explanation the dividend calendar")}
      info={
        anyEstimate ? (
          <>
            {trx(
              "Amounts and months with {0} are an estimate from your own payout history, not an official announcement. That's why there is a month and a part of the month and no date: the rhythm is known, the day isn't.{1}{2}A row with {3} does come from an announced ex-dividend date.",
              <b>±</b>,
              <br />,
              <br />,
              <b>{tr("official")}</b>,
            )}
          </>
        ) : (
          <>
            {trx(
              "The coming months, added up per month. A row with {0} comes from an announced ex-dividend date.",
              <b>{tr("official")}</b>,
            )}
          </>
        )
      }
    >
      {/* An outcome, not an explanation: what is still to come this year. */}
      <p className="mb-3 text-[13px] leading-relaxed text-ink-muted">
        {trx("Together ± {0} before the end of this year.", fmtEuro(totals.expected_rest_of_year))}
      </p>
      <div className="flex flex-col gap-3">
        {months.map((m) => (
          <div key={m.month}>
            <div className="flex items-baseline justify-between gap-3 pb-1" style={{ borderBottom: "1px solid var(--border-hairline)" }}>
              <span className="ds-eyebrow" style={{ color: "var(--text-primary)" }}>
                {monthLabel(m.month)}
              </span>
              <span className="num text-[12.5px] font-semibold">± {fmtEuro(m.total)}</span>
            </div>
            {m.items.map((item) => (
              <div key={`${item.isin}-${item.date}`} className="row-rule flex items-center gap-2.5 py-[7px] text-[12.5px]">
                <span className="num w-[62px] flex-none text-ink-muted sm:w-[72px]">{whenLabel(item)}</span>
                <span className="min-w-0 flex-1 truncate">{item.name ?? item.isin}</span>
                {item.source === "official" ? (
                  <Tag className="flex-none">{tr("official")}</Tag>
                ) : (
                  item.confidence === "low" && (
                    <Tag className="flex-none" outline>
                      {tr("uncertain")}
                    </Tag>
                  )
                )}
                <span className="num flex-none font-semibold">± {fmtEuro(item.expected_eur)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Per year
// ---------------------------------------------------------------------------

function PerYear({ rows, totals }: { rows: YearRow[]; totals: Totals }) {
  const bars: BarDatum[] = rows.map((r) => ({
    key: r.year,
    label: r.year,
    title: r.year,
    segments: [
      { key: "net", value: r.net, colour: RECEIVED },
      { key: "expected", value: r.expected, colour: EXPECTED, estimate: true },
    ],
    note: r.expected > 0 ? tr("of which ± {0} expected", fmtEuro(r.expected)) : `${r.payments}×`,
  }));

  const finished = rows.filter((r) => !r.partial);
  const best = finished.reduce<YearRow | null>((top, r) => (top === null || r.net > top.net ? r : top), null);

  return (
    <Section
      label={tr("Per year")}
      action={
        <DownloadCsv
          stem="dividend-per-year"
          headers={[tr("year"), "gross", tr("dividend tax"), "net", tr("payouts"), "expected"]}
          rows={() => rows.map((r) => [r.year, r.gross, r.tax, r.net, r.payments, r.expected])}
        />
      }
    >
      <Bars
        bars={bars}
        legend={[
          { key: "net", label: "received", colour: RECEIVED },
          { key: "expected", label: tr("still expected"), colour: EXPECTED, estimate: true },
        ]}
        format={(v) => fmtEuro(v)}
        ariaLabel={tr("Dividend received per year")}
        summary={
          best ? (
            <>
              {trx(
                "Best completed year: {0} with {1}",
                <b className="num text-text">{best.year}</b>,
                <b className="num text-text">{fmtEuro(best.net)}</b>,
              )}
            </>
          ) : (
            <>{tr("The first year isn't complete yet")}</>
          )
        }
      />
      <Disclosure label={tr("Show the figures and the withheld tax per year")}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[380px] text-[12.5px]">
            <thead>
              <tr className="text-left text-ink-muted" style={{ borderBottom: "1px solid var(--border-hairline)" }}>
                <th className="py-1.5 pr-2 font-semibold">{tr("Year")}</th>
                <th className="py-1.5 pr-2 text-right font-semibold">{tr("Gross")}</th>
                <th className="py-1.5 pr-2 text-right font-semibold">{tr("Tax")}</th>
                <th className="py-1.5 pr-2 text-right font-semibold">{tr("Net")}</th>
                <th className="py-1.5 text-right font-semibold">{tr("Payouts")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.year} className="last:border-0" style={{ borderBottom: "1px solid var(--border-hairline)" }}>
                  <td className="num py-1.5 pr-2">
                    {r.year}
                    {r.partial && <span className="ml-1 text-ink-muted">{tr("(still running)")}</span>}
                  </td>
                  <td className="num py-1.5 pr-2 text-right">{fmtEuro(r.gross)}</td>
                  <td className="num py-1.5 pr-2 text-right text-ink-muted">{r.tax === 0 ? "–" : fmtEuro(r.tax)}</td>
                  <td className="num py-1.5 pr-2 text-right font-semibold">{fmtEuro(r.net)}</td>
                  <td className="num py-1.5 text-right text-ink-muted">{r.payments}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totals.tax_pct !== null && (
          <p className="mt-3 text-[12px] leading-relaxed text-ink-muted">
            {trx(
              "In total {0} dividend tax withheld, {1} of the gross amount. {2}",
              <b className="num text-text">{fmtEuro(-totals.tax)}</b>,
              fmtPercent(totals.tax_pct, { decimals: 1 }),
              <InfoPopover label={tr("Explanation withheld dividend tax")}>
                {trx(
                  "Dutch dividend tax is a prepayment: you can offset it in your income tax return.{0}{1}Foreign withholding tax works differently and can often only be partly reclaimed. This overview doesn't make that distinction: it shows what DeGiro withheld.",
                  <br />,
                  <br />,
                )}
              </InfoPopover>,
            )}
          </p>
        )}
      </Disclosure>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Per month
// ---------------------------------------------------------------------------

const MONTHS_BACK = 18;
const MONTHS_AHEAD = 6;

function PerMonth({ rows }: { rows: MonthRow[] }) {
  // The window around "now". The series runs twelve months ahead because the year
  // estimate needs it; twelve months of estimate bars next to eighteen months of
  // fact makes the chart about the expectation instead of about what happened.
  const current = rows.findIndex((r) => r.future);
  const now = current === -1 ? rows.length - 1 : current - 1;
  const window = rows.slice(Math.max(0, now - MONTHS_BACK + 1), now + 1 + MONTHS_AHEAD);

  const bars: BarDatum[] = window.map((r) => ({
    key: r.month,
    label: fmtMonth(r.month),
    title: monthLabel(r.month),
    segments: [
      { key: "net", value: r.net, colour: RECEIVED },
      { key: "expected", value: r.expected, colour: EXPECTED, estimate: true },
    ],
    // A month can come out below zero: DeGiro books a corrected payout back as a
    // negative row, and that correction can be larger than what else came in that
    // month. There is then no bar to show — so the readout says what is there.
    note:
      r.net < 0
        ? tr("reversed: more corrected than received")
        : r.net === 0 && r.expected === 0
          ? tr("nothing")
          : r.future
            ? tr("expected")
            : undefined,
  }));

  const received = window.filter((r) => !r.future);
  const paid = received.filter((r) => r.net > 0).length;

  return (
    <Section
      label={tr("Per month")}
      info={
        <>
          {trx(
            "The empty months belong to it: a quarterly payer pays four times a year, so eight months are quiet by definition.{0}{1}That's why there is no average per month here, because it hides exactly that pattern.",
            <br />,
            <br />,
          )}
        </>
      }
    >
      <Bars
        bars={bars}
        legend={[
          { key: "net", label: "received", colour: RECEIVED },
          { key: "expected", label: "expected", colour: EXPECTED, estimate: true },
        ]}
        format={(v) => fmtEuro(v)}
        labelEvery={3}
        ariaLabel={tr("Dividend per month")}
        summary={
          // With the year: below the bars there is only the month — across two years
          // "Mar" appears twice, and there is no room to put "Mar ’25" under a bar of
          // twenty pixels.
          <>
            {trx(
              "In {0} of the last {1} months something came in · {2} to {3}",
              <b className="num text-text">{paid}</b>,
              <b className="num text-text">{received.length}</b>,
              <span className="num">{monthLabel(window[0].month)}</span>,
              <span className="num">{monthLabel(window[window.length - 1].month)}</span>,
            )}
          </>
        }
      />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Season
// ---------------------------------------------------------------------------

function Seasons({ rows, totals }: { rows: SeasonRow[]; totals: Totals }) {
  const bars: BarDatum[] = rows.map((r) => ({
    key: String(r.month),
    label: monthAbbr(r.month),
    title: monthName(r.month),
    segments: [{ key: "total", value: r.total, colour: SEASON }],
    note:
      r.years === 0
        ? tr("never received anything")
        : tr(
            "in {0} {1}{2}",
            r.years,
            r.years === 1 ? tr("year") : tr("years"),
            r.share_pct !== null ? tr(" · {0} of everything", fmtPercent(r.share_pct, { decimals: 0 })) : "",
          ),
  }));

  const peak = rows.reduce<SeasonRow | null>((top, r) => (top === null || r.total > top.total ? r : top), null);

  return (
    <Section
      label={tr("In which months does it come in")}
      infoLabel={tr("Explanation the seasonal pattern")}
      info={
        <>
          {trx(
            "Everything added up over {0} years, not averaged per year.{1}{2}An average needs a denominator, and here it is misleading: dividing by the number of years with a payment would make a month that paid once look as large as a month that pays every year.",
            <span className="num">{totals.years}</span>,
            <br />,
            <br />,
          )}
        </>
      }
      action={
        <DownloadCsv
          stem="dividend-per-calendar-month"
          headers={[tr("month"), "total", tr("years")]}
          rows={() => rows.map((r) => [monthAbbr(r.month), r.total, r.years])}
        />
      }
    >
      <Bars
        bars={bars}
        format={(v) => fmtEuro(v)}
        ariaLabel={tr("Dividend received per calendar month, added up over all years")}
        summary={
          peak && peak.total > 0 ? (
            <>
              {trx(
                "Your busiest month is {0}, when {1} came in",
                <b className="text-text">{monthName(peak.month)}</b>,
                <b className="num text-text">{fmtEuro(peak.total)}</b>,
              )}
            </>
          ) : (
            <>{tr("Too little history for a pattern yet")}</>
          )
        }
      />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Cumulative
// ---------------------------------------------------------------------------

function Cumulative({ points, totals }: { points: { d: string; v: number }[]; totals: Totals }) {
  if (points.length < 2) return null;
  return (
    <Section
      label={tr("Added up since the start")}
      info={
        <>
          {trx(
            "A staircase, not a slope: the line only moves on a payout day, because that's the only moment money came in.{0}{1}The steeper the staircase gets, the faster your funds pay out, through higher dividends and because you own more units.",
            <br />,
            <br />,
          )}
        </>
      }
    >
      <LineChart
        series={[
          {
            label: tr("Dividend received"),
            colour: RECEIVED,
            fill: true,
            points,
          },
        ]}
        format={(v) => fmtEuro(v)}
        ariaLabel={tr("Cumulative dividend received")}
      />
      <p className="mt-3 text-[12px] text-ink-muted">{trx("Total {0}.", <b className="num text-text">{fmtEuro(totals.net)}</b>)}</p>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Per fund
// ---------------------------------------------------------------------------

function PerStock({ rows, totals }: { rows: StockRow[]; totals: Totals }) {
  const bars = rows.map((r) => ({
    label: r.name,
    value: r.net,
    display: fmtEuro(r.net),
    secondary: r.share_pct !== null ? fmtPercent(r.share_pct, { decimals: 0 }) : undefined,
    meta: [
      r.held ? (r.cadence ? cadenceLabel(r.cadence) : tr("no fixed rhythm")) : tr("no longer held"),
      tr("{0}× · last {1}", r.payments, fmtDayMonthYear(r.last)),
      r.next ? tr("next ± {0} {1}", fmtEuro(r.next.expected_eur), whenLabel(r.next)) : null,
      r.yield_on_cost_pct !== null ? tr("{0} per year on your deposits", fmtPercent(r.yield_on_cost_pct, { decimals: 2 })) : null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));

  const sold = rows.filter((r) => !r.held);

  return (
    <Section
      label={tr("Which funds pay")}
      info={
        <>
          {trx(
            "Everything you ever received, per fund. Tap a name for the rhythm, the last payment and the yield on your deposits.{0}{1}A fund you no longer own stays on the list: you received that money, so it counts in the total. There is no yield with it, because there are no deposits left to calculate it on.",
            <br />,
            <br />,
          )}
        </>
      }
      action={
        <DownloadCsv
          stem="dividend-per-fund"
          headers={[
            "isin",
            "name",
            tr("held"),
            "gross",
            "tax",
            "net",
            tr("last 12 mo"),
            tr("payouts"),
            "first",
            "last",
            tr("yield on cost %"),
          ]}
          rows={() =>
            rows.map((r) => [
              r.isin,
              r.name,
              r.held ? "ja" : "nee",
              r.gross,
              r.tax,
              r.net,
              r.ttm_net,
              r.payments,
              r.first,
              r.last,
              r.yield_on_cost_pct ?? "",
            ])
          }
        />
      }
    >
      <HBars rows={bars} colour={RECEIVED} emptyLabel={tr("No payouts received yet.")} />
      {/* An outcome about your list, not an explanation: how many rows below are about a fund you
          no longer have. Why they stay is behind the "i" on the heading. */}
      {sold.length > 0 && (
        <p className="mt-3 text-[12px] text-ink-muted">
          {trx(
            "{0} {1}, but {2} in the total of {3}.",
            <span className="num">{sold.length}</span>,
            sold.length === 1 ? tr("fund you no longer own") : tr("funds you no longer own"),
            sold.length === 1 ? tr("it still counts") : tr("they still count"),
            fmtEuro(totals.net),
          )}
        </p>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// The log
// ---------------------------------------------------------------------------

function PaymentLog({ payments }: { payments: Payment[] }) {
  if (payments.length === 0) return null;
  const foreign = payments.filter((p) => p.currency !== "EUR").length;

  return (
    <Section
      label={tr("All payments")}
      action={
        <DownloadCsv
          stem="dividend-payments"
          headers={[tr("date"), "isin", "name", "currency", tr("gross eur"), tr("tax eur"), tr("net eur")]}
          rows={() => payments.map((p) => [p.date, p.isin, p.name, p.currency, p.gross_eur, p.tax_eur, p.net_eur])}
        />
      }
    >
      <p className="text-[13px] leading-relaxed text-ink-muted">
        {trx(
          "{0} {1}, newest first.{2}",
          <span className="num">{payments.length}</span>,
          payments.length === 1 ? tr("payout") : tr("payouts"),
          foreign > 0 && (
            <>
              {" "}
              {trx(
                "{0} of them came in in another currency. {1}",
                <span className="num">{foreign}</span>,
                <InfoPopover label={tr("Explanation payouts in another currency")}>
                  {tr(
                    "Converted at the exchange rate DeGiro used on the payout day, not at today's rate. That way it shows what was really credited.",
                  )}
                </InfoPopover>,
              )}
            </>
          ),
        )}
      </p>
      <Disclosure label={payments.length === 1 ? tr("Show the payment") : tr("Show all {0} payments", payments.length)}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-[12.5px]">
            <thead>
              <tr className="text-left text-ink-muted" style={{ borderBottom: "1px solid var(--border-hairline)" }}>
                <th className="py-1.5 pr-2 font-semibold">{tr("Date")}</th>
                <th className="py-1.5 pr-2 font-semibold">{tr("Fund")}</th>
                <th className="py-1.5 pr-2 text-right font-semibold">{tr("Gross")}</th>
                <th className="py-1.5 pr-2 text-right font-semibold">{tr("Tax")}</th>
                <th className="py-1.5 text-right font-semibold">{tr("Net")}</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p, i) => (
                <tr key={`${p.date}-${p.isin}-${i}`} className="last:border-0" style={{ borderBottom: "1px solid var(--border-hairline)" }}>
                  <td className="num whitespace-nowrap py-1.5 pr-2">{fmtDayMonthYear(p.date)}</td>
                  <td className="max-w-[180px] truncate py-1.5 pr-2">{p.name || p.isin}</td>
                  <td className="num py-1.5 pr-2 text-right">{fmtEuro(p.gross_eur)}</td>
                  <td className="num py-1.5 pr-2 text-right text-ink-muted">{p.tax_eur === 0 ? "–" : fmtEuro(p.tax_eur)}</td>
                  <td className="num py-1.5 text-right font-semibold">{fmtEuro(p.net_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </Section>
  );
}
