"use client";

// Returns — the two numbers the dashboard deliberately does not use.
//
// The dashboard answers "what has my money done": an amount in euros with a
// percentage that goes with it. That question has one good answer and it is
// already there. This tab answers the two questions that amount cannot answer —
// how the investments did regardless of when you deposited (TWR), and what your
// money actually yielded per year including that timing (IRR).
//
// They can differ enormously and both be right. That is why every number has an
// explanation button with when to use it, in plain language: a page with three
// percentages of which you do not understand two is worse than a page with one
// percentage.
//
// Benchmarks live here too (they had a tab of their own): one period filter for
// the figures and the charts, so "1Y" means the same year everywhere on the page.
// The comparison chart puts your portfolio next to the indexes over that period,
// rebased to 100 on its first day; the rolling 3-month return is cut to it.
// TWR, IRR and the simple return need the "returns" beta; the charts do not.
//
// The little decision tree ("which number do I need?") used to be a section with
// four questions and four answers at the bottom of the page — half a page of text
// below the figures it was about. It now sits behind the "?" in the top bar,
// where the rest of the method is too.

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro, fmtPercent } from "@/lib/format";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import LineChart, { type LineSeries } from "@trackerai/ui/charts/LineChart";
import { Checkbox, Eyebrow, Section, Tabs } from "@/components/ds";
import { periodTabs } from "@/lib/timeline";
import ZoomChip, { type ZoomWindow } from "@/components/charts/ZoomChip";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { tr, trx } from "@/lib/i18n";
import { availableRanges, sliceByRange, type Range } from "@/lib/dashboard";
import { fmtEu } from "@/lib/format";

type RangeStat = {
  label: string;
  from: string;
  days: number;
  twr_pct: number | null;
  irr_pct: number | null;
  simple_pct: number | null;
  gain_eur: number;
  contrib_eur: number;
};

type Returns = {
  points: { d: string; twr: number }[];
  gaps: { from: string; to: string }[];
  ranges: RangeStat[];
  /** True when the closes could not be fetched. Without this the whole tab read
   *  0,00%: every holding fell back to its cost basis, so the day value equalled
   *  the amount invested and the TWR index never left 100. */
  unavailable?: boolean;
};

type Series = {
  label: string;
  kind: "portfolio" | "benchmark";
  points: { d: string; v: number }[];
};

type Chart = { series: Series[]; baseline: number | null };

type BenchmarkSeries = {
  indexed: Chart;
  rolling: Chart;
  ytd: Chart;
  rolling_window_days: number;
  year: number;
};

// Meridian's order of importance: series 1 (terracotta) is always your own data,
// series 2 (walnut black, dashed) is always the benchmark. With more than one
// index the next ones get the olive and ochre lines, in a fixed order and never
// cycled — two lines of the same colour in one chart is worse than one line less.
const BENCHMARK_COLOURS = ["var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

function toLineSeries(chart: Chart, { fillPortfolio = false } = {}): LineSeries[] {
  let benchmark = 0;
  return chart.series.map((s) => {
    if (s.kind === "portfolio") {
      return {
        label: s.label,
        points: s.points,
        colour: "var(--chart-1)",
        width: 2,
        fill: fillPortfolio,
      };
    }
    const i = benchmark++;
    return {
      label: s.label,
      points: s.points,
      colour: BENCHMARK_COLOURS[i % BENCHMARK_COLOURS.length],
      // Only the first index is *the* benchmark and gets the dashed line; a chart in
      // which everything is dashed reads as a chart without data.
      dash: i === 0 ? ("dashed" as const) : undefined,
      width: 1.5,
    };
  });
}

/**
 * A chart cut to a stretch dragged out on it. `rebase`: an index starts again at
 * 100 and a return again at 0% on the first day, so the lines compare over that
 * stretch only; a rolling return is left as it is.
 */
function zoomed(chart: Chart, zoom: ZoomWindow | null, rebase: "index" | "pct" | null): Chart {
  if (!zoom) return chart;
  return {
    ...chart,
    series: chart.series.map((s) => {
      const inside = s.points.filter((p) => p.d >= zoom.from && p.d <= zoom.to);
      const v0 = inside[0]?.v;
      if (!rebase || v0 === undefined) return { ...s, points: inside };
      return {
        ...s,
        points: inside.map((p) => ({
          d: p.d,
          v: rebase === "index" ? (v0 ? (p.v / v0) * 100 : p.v) : ((1 + p.v / 100) / (1 + v0 / 100) - 1) * 100,
        })),
      };
    }),
  };
}

const HIDDEN_KEY = "benchmarks-hidden";

const pct = (v: number) => fmtEu(v, { decimals: 1, suffix: "%" });
const index100 = (v: number) => fmtEu(v, { decimals: 0 });

/** Where each line stands now, as a row of figures above the chart. */
function Latest({ chart, format, hidden }: { chart: Chart; format: (v: number) => string; hidden: Set<string> }) {
  const rows = chart.series
    .filter((s) => !hidden.has(s.label))
    .map((s) => ({ label: s.label, last: s.points[s.points.length - 1] }))
    .filter((r) => r.last !== undefined);
  if (rows.length === 0) return null;
  const base = chart.baseline ?? 0;
  return (
    <div className="flex flex-wrap gap-x-7 gap-y-1.5">
      {rows.map((r) => (
        <span key={r.label} className="text-[12.5px]">
          <span className="text-ink-muted">{r.label} </span>
          <b className="num" style={{ color: r.last.v >= base ? "var(--text-gain)" : "var(--text-loss)" }}>
            {trueMinus(format(r.last.v))}
          </b>
        </span>
      ))}
    </div>
  );
}

function Pct({ value, big = false }: { value: number | null; big?: boolean }) {
  if (value === null) {
    return <span className={`num text-ink-muted ${big ? "font-display text-[34px] font-light" : ""}`}>–</span>;
  }
  return (
    <span
      className={`num ${big ? "font-display text-[34px] font-light leading-tight tracking-[-0.028em]" : "text-[15px]"}`}
      style={{ color: value >= 0 ? "var(--text-gain)" : "var(--text-loss)" }}
    >
      {trueMinus(fmtPercent(value, { decimals: 1, plus: true }))}
    </span>
  );
}

export default function ReturnPage() {
  // TWR, IRR and the simple return are behind the "returns" beta; the charts are for everyone.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ is_admin: boolean; beta_features: string[] }>("/api/auth/me") });
  const canSeeReturns = !!me.data && (me.data.is_admin || me.data.beta_features.includes("returns"));
  // One period for the whole page: a button, or a stretch dragged out on a chart.
  const [rangeLabel, setRangeLabel] = useState<string>("All");
  const [zoom, setZoom] = useState<ZoomWindow | null>(null);
  // Bonds in by default, so the portfolio line matches the TWR figure above it.
  const [excludeBonds, setExcludeBonds] = useState(false);
  // Indexes switched off, by name; your portfolio always stays. Remembered here.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  useEffect(() => {
    try {
      setHidden(new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]")));
    } catch {
      /* no storage */
    }
  }, []);
  const toggle = (label: string) =>
    setHidden((old) => {
      const next = new Set(old);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      try {
        localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next]));
      } catch {
        /* no storage */
      }
      return next;
    });

  // The API works out a dragged window's figures as "Custom".
  const q = useQuery({
    queryKey: ["returns", zoom?.from ?? null, zoom?.to ?? null],
    queryFn: () => api.get<Returns>(zoom ? `/api/returns?start=${zoom.from}&end=${zoom.to}` : "/api/returns"),
    placeholderData: (previous) => previous,
    enabled: canSeeReturns,
    retry: false,
  });
  const bq = useQuery({
    queryKey: ["benchmark-series", excludeBonds],
    queryFn: () => api.get<BenchmarkSeries>(`/api/benchmarks/series?exclude_bonds=${excludeBonds}`),
    retry: false,
  });

  if (me.isLoading || (canSeeReturns && q.isLoading) || bq.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  const data = canSeeReturns && q.data && !q.data.unavailable && q.data.ranges.length > 0 ? q.data : null;
  const bench = bq.data ?? null;
  if (!data && !bench) {
    return (
      <p className="max-w-measure py-6 text-sm leading-relaxed text-ink-muted">
        {q.data?.unavailable
          ? tr(
              "The price history could not be fetched from Yahoo Finance, so no return can be calculated right now. Your positions and amounts are fine. Try again in a few minutes.",
            )
          : bq.error && bq.error instanceof ApiError
            ? bq.error.message
            : tr(
                "Nothing to calculate yet. Upload your transactions and refresh the prices, then your time-weighted and money-weighted return appear here.",
              )}
      </p>
    );
  }

  // The period buttons: what the history can live up to. 1D and 1W say nothing
  // about a return over time.
  const days: { d: string }[] = bench?.indexed.series.find((x) => x.kind === "portfolio")?.points ?? data?.points ?? [];
  const labels = availableRanges(days).filter((r) => r !== "1D" && r !== "1W") as string[];
  const label = labels.includes(rangeLabel) ? rangeLabel : "All";
  const sliced = days.length >= 2 ? sliceByRange(days, label as Range) : days;
  const period: ZoomWindow = zoom ?? { from: sliced[0]?.d ?? "", to: days[days.length - 1]?.d ?? "" };
  const choose = (r: string) => {
    setZoom(null);
    setRangeLabel(r);
  };

  const custom = zoom ? data?.ranges.find((r) => r.label === "Custom") : undefined;
  const selected = data
    ? zoom
      ? custom
      : (data.ranges.find((r) => r.label === label) ?? data.ranges.find((r) => r.label === "All"))
    : undefined;
  // What the figures show: the period's, or while a dragged window's figures load,
  // the last ones (dimmed).
  const stat = selected ?? (data ? (data.ranges.find((r) => r.label === label) ?? data.ranges[data.ranges.length - 1]) : undefined);
  // While the figures of a dragged window load, the charts already show it.
  const pending = !!zoom && !!data && !custom;
  const gaps = data ? data.gaps.filter((g) => g.to >= period.from && g.from <= period.to) : [];

  const indexed = bench ? zoomed(bench.indexed, period, "index") : null;
  const rolling = bench ? zoomed(bench.rolling, period, null) : null;
  const shown = (series: LineSeries[]) => series.filter((s) => !hidden.has(s.label));
  const benchmarks = bench ? toLineSeries(bench.indexed).filter((_, i) => bench.indexed.series[i].kind === "benchmark") : [];

  return (
    <div className="flex flex-col gap-11">
      {/* One period for everything below: the figures and both charts. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <Eyebrow>{tr("Measured over")}</Eyebrow>
        <span className="flex flex-wrap items-center gap-3">
          <Tabs variant="quiet" items={periodTabs(labels)} value={zoom ? "" : label} onChange={choose} ariaLabel={tr("Period")} />
          {zoom && <ZoomChip zoom={zoom} onClear={() => setZoom(null)} />}
        </span>
      </div>

      {stat ? (
        <>
          {/* The two numbers as supporting figures under an ink line — no tiles with a border around
          them. Two denominators, two questions, so two figures. */}
          <div
            className="-mt-6 grid gap-x-12 gap-y-8 pt-3.5 transition-opacity sm:grid-cols-2"
            style={{ borderTop: "1px solid var(--border-hairline)", opacity: pending ? 0.35 : 1 }}
            aria-busy={pending}
          >
            <div className="flex flex-col gap-1.5">
              <span className="flex items-center gap-1">
                <Eyebrow>{tr("Time-weighted (TWR)")}</Eyebrow>
                <InfoPopover label={tr("Explanation time-weighted return")}>
                  {trx(
                    "{0}{1}{2}This number pretends you invested one amount at the start and never touched it again. Deposits and withdrawals are taken out, so only how the funds and shares did remains.{3}{4}{5} The MSCI World has no savings account money comes from every month; you do. Without that correction a good month in which you happened to deposit a lot would make you look better than you were, and the other way round.{6}{7}{8} the question how much you earned. TWR weighs every year equally, also the years in which you had hardly invested anything. That's why it can come out much higher than what's in your account in euros.",
                    <b>{tr("How good were the investments themselves?")}</b>,
                    <br />,
                    <br />,
                    <br />,
                    <br />,
                    <b>{tr("Use this when you compare yourself with an index.")}</b>,
                    <br />,
                    <br />,
                    <b>{tr("What not to use it for:")}</b>,
                  )}
                </InfoPopover>
              </span>
              <Pct value={stat.twr_pct} big />
              <span className="text-xs text-ink-muted">
                {trx("over this whole period, since {0}", <span className="num">{fmtDayMonthYear(zoom ? period.from : stat.from)}</span>)}
              </span>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="flex items-center gap-1">
                <Eyebrow>{tr("Money-weighted (IRR)")}</Eyebrow>
                <InfoPopover label={tr("Explanation money-weighted return")}>
                  {trx(
                    "{0}{1}{2}This does count when you put money in. If you deposited a lot just before a rise, this number goes up. If you deposited a lot just before a fall, it goes down. It's the return a savings account would have had to give you to end up at the same amount, with exactly your deposits.{3}{4}{5}: investing and timing together.{6}{7}It is {8}, not over the whole period. That's why short periods show a dash: converting two good weeks to a yearly rate gives numbers like \"+400% per year\", and those mean nothing.",
                    <b>{tr("What did your money really yield?")}</b>,
                    <br />,
                    <br />,
                    <br />,
                    <br />,
                    <b>{tr("Use this when you want to know how you did")}</b>,
                    <br />,
                    <br />,
                    <b>{tr("per year")}</b>,
                  )}
                </InfoPopover>
              </span>
              <Pct value={stat.irr_pct} big />
              <span className="text-xs text-ink-muted">
                {stat.irr_pct === null ? tr("period too short to express per year") : tr("per year, with your deposits")}
              </span>
            </div>
          </div>

          <Section
            tone="quiet"
            label={tr("What your money did")}
            info={
              <>
                {trx(
                  "The number that is also on Today: the gain in euros, and that gain divided by the money that was in it during this period (the starting value plus what you deposited along the way).{0}{1}The simplest of the three and the only one that fits the amount in euros neatly. Rougher than IRR, because it doesn't take into account that money that came in yesterday hasn't had a year to grow.",
                  <br />,
                  <br />,
                )}
              </>
            }
          >
            <div
              className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 text-[13px] transition-opacity"
              style={{ opacity: pending ? 0.35 : 1 }}
            >
              <span className="num" style={{ color: stat.gain_eur >= 0 ? "var(--text-gain)" : "var(--text-loss)" }}>
                {trueMinus(fmtEuro(stat.gain_eur, { plus: true }))}
              </span>
              <Pct value={stat.simple_pct} />
              {Math.abs(stat.contrib_eur) >= 0.005 && (
                <span className="num text-xs text-ink-muted">
                  {trx("deposits {0} in this period", trueMinus(fmtEuro(stat.contrib_eur, { plus: true })))}
                </span>
              )}
            </div>
          </Section>
        </>
      ) : null}

      {indexed && (
        <Section
          label={tr("Your portfolio next to the market")}
          info={
            <>
              {tr(
                "Everything starts at 100 on the first day of the period, so you compare the shape of the lines rather than their level. If your line ends above an index, you did better over this period.",
              )}
            </>
          }
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
            <span className="text-ink-muted">{tr("Compare with:")}</span>
            {benchmarks.map((b) => {
              const on = !hidden.has(b.label);
              return (
                <button
                  key={b.label}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(b.label)}
                  className="inline-flex items-center gap-1.5 rounded-sm px-0.5 py-0.5 text-ink-muted hover:text-text"
                  style={{ opacity: on ? 1 : 0.45, textDecoration: on ? undefined : "line-through" }}
                >
                  <span
                    className="h-0 w-3.5 flex-none"
                    style={{ borderTop: `2px ${b.dash === "dashed" ? "dashed" : "solid"} ${on ? b.colour : "var(--border-strong)"}` }}
                  />
                  {b.label}
                </button>
              );
            })}
            <label className="ml-auto flex items-center gap-2">
              <Checkbox checked={excludeBonds} onChange={setExcludeBonds} label={tr("Leave bonds out")} />
              <InfoPopover label={tr("Explanation excluding bonds")}>
                {tr(
                  "Bond ETF’s behave like savings. Leaving them out shows how your shares are doing, which compares more fairly with an equity index.",
                )}
              </InfoPopover>
            </label>
          </div>
          <Latest chart={indexed} format={index100} hidden={hidden} />
          <LineChart
            series={shown(toLineSeries(indexed, { fillPortfolio: true }))}
            baseline={100}
            format={index100}
            ariaLabel={tr("Portfolio against benchmarks, indexed to 100")}
            dateAxis
            onSelect={setZoom}
          />
          {gaps.length > 0 && (
            <p className="max-w-measure text-xs leading-relaxed text-ink-muted">
              {trx(
                "{0} in this chart in which your portfolio was empty ({1}). The line runs flat there. {2}",
                gaps.length === 1 ? tr("Note: there is a period") : tr("Note: there are periods"),
                gaps.map((g, i) => (
                  <span key={g.from}>
                    {i > 0 && ", "}
                    <span className="num">
                      {fmtDayMonthYear(g.from)} – {fmtDayMonthYear(g.to)}
                    </span>
                  </span>
                )),
                <InfoPopover label={tr("Explanation empty periods in the chart")}>
                  {tr(
                    "Time-weighted return glues together the pieces in which you were invested. You earned or lost nothing in those months, and the chart doesn't count them as a loss either.",
                  )}
                </InfoPopover>,
              )}
            </p>
          )}
        </Section>
      )}

      {rolling && rolling.series.some((x) => x.points.length >= 2) && (
        <Section
          label={tr("Return over the last 3 months")}
          infoLabel={tr("Explanation rolling return")}
          info={
            <>
              {trx(
                "Each point asks the same question: {0}{1}{2}The window of {3} days moves along day by day. So the line shows how your recent form changed, not the gain since one fixed starting point. Above 0% the last quarter was positive.",
                <i>{tr("if I had held this for the 3 months up to that day, what would my return have been?")}</i>,
                <br />,
                <br />,
                <span className="num">{bench!.rolling_window_days}</span>,
              )}
            </>
          }
        >
          <Latest chart={rolling} format={pct} hidden={hidden} />
          <LineChart
            series={shown(toLineSeries(rolling))}
            baseline={bench!.rolling.baseline ?? undefined}
            format={pct}
            ariaLabel={tr("Rolling return over 3 months")}
            dateAxis
            onSelect={setZoom}
          />
        </Section>
      )}
    </div>
  );
}
