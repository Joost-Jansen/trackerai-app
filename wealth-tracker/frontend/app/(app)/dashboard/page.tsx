"use client";

// Today — the reference screen of this redesign.
//
// One question: "how is my portfolio doing today, and what deserves my
// attention?" What changed compared to the cockpit design:
//
//   · One hero. The total value is at 68px; everything that supports it is at
//     21px or less, and gets no box to look important.
//   · No more cards. Every section is a small-caps label above a rule; a frame
//     only draws something where there really is a boundary.
//   · Asymmetry: a main column and a narrow side column of 264px, separated by
//     one hairline, with the right side of the rule deliberately empty.
//   · One accent moment. "What deserves your attention" sits under a 2px
//     terracotta rule, and is thereby the only terracotta on this screen.
//
// The content rule that counts hardest here: **every short-term number gets a
// long-term companion**. The day move therefore never stands alone at the top,
// but next to the total value and the return since the start.

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  type Allocation,
  type DividendForecastItem,
  type DividendStats,
  type Intraday,
  type Movers,
  type NewsItem,
  type Probe,
  type Range,
  type SinceVisit,
  type SparklinePoint,
  type Summary,
  type ValueHistory,
  availableRanges,
  intradayAsValuePoints,
  rangeBreakdown,
  sliceByRange,
} from "@/lib/dashboard";
import { fmtDayMonth, fmtDayMonthYear, fmtEuro, fmtIntradayLabel, fmtMonth, fmtPercent, fmtRelative, parseTimestamp } from "@/lib/format";
import { periodLabel, periodTabs } from "@/lib/timeline";
import ZoomChip, { sliceByZoom, type ZoomWindow } from "@/components/charts/ZoomChip";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { topSlices } from "@/lib/slices";
import { Eyebrow, Figure, Hero, Section, SignedValue, Tabs, ValueChange } from "@/components/ds";
import BreakdownList from "@/components/BreakdownList";
import ChartHeadline from "@trackerai/ui/charts/ChartHeadline";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import ValueChart from "@/components/dashboard/ValueChart";
import Sparkline from "@/components/dashboard/Sparkline";
import HBars from "@/components/charts/HBars";
import { NewsTag } from "@/components/news/NewsList";
import { cadenceLabel, partLabel } from "@/lib/dashboard";
import { tr, trx } from "@/lib/i18n";

function Skeleton({ className = "h-40" }: { className?: string }) {
  return <div className={`animate-pulse rounded ${className}`} style={{ background: "var(--surface-inset)" }} />;
}

export default function DashboardPage() {
  const summaryQ = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api.get<Summary>("/api/dashboard/summary"),
  });
  const sparklineQ = useQuery({
    queryKey: ["dashboard-sparkline"],
    queryFn: () => api.get<{ points: SparklinePoint[] }>("/api/dashboard/sparkline"),
  });
  const valueHistoryQ = useQuery({
    queryKey: ["dashboard-value-history"],
    queryFn: () => api.get<ValueHistory>("/api/dashboard/value-history"),
  });
  const allocationQ = useQuery({
    queryKey: ["dashboard-allocation"],
    queryFn: () => api.get<Allocation>("/api/dashboard/allocation"),
  });
  const dividendsQ = useQuery({
    queryKey: ["dashboard-dividends"],
    queryFn: () => api.get<DividendStats>("/api/dashboard/dividends"),
  });
  const moversQ = useQuery({
    queryKey: ["dashboard-movers"],
    queryFn: () => api.get<Movers>("/api/dashboard/movers"),
  });
  const newsQ = useQuery({
    queryKey: ["dashboard-news"],
    queryFn: () => api.get<{ items: NewsItem[] }>("/api/dashboard/news"),
  });
  // POST on purpose: it records the visit. One call per load; a repeat within the
  // same session only touches the session row.
  const visitQ = useQuery({
    queryKey: ["dashboard-visit"],
    queryFn: () => api.post<{ since: SinceVisit }>("/api/dashboard/visit"),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });

  // "All" and not "1M": the card is called Value development, and that is the
  // question about the whole ride. A month is the exception you click, not the
  // first thing you should see — at 1M a five-year portfolio reads as a flat dash
  // with a lot of noise.
  const [range, setRange] = useState<Range>("All");
  // A stretch dragged out on the chart: overrides the period buttons until cleared.
  const [zoom, setZoom] = useState<ZoomWindow | null>(null);
  const [allocMode, setAllocMode] = useState<"sector" | "region">("sector");
  // What the chart has under the finger right now. Lives here and not in the chart
  // itself, so the section header can show it in the space it takes up anyway — a
  // tooltip would cover the line you are reading.
  const [probe, setProbe] = useState<Probe | null>(null);

  const dailyPoints = valueHistoryQ.data?.points ?? [];
  const lastDaily = dailyPoints.length > 0 ? dailyPoints[dailyPoints.length - 1] : null;

  // Which buttons this history can live up to, and the chosen period set back
  // onto them: a portfolio of half a year has no 1Y, and a button that stays on it
  // anyway draws a line called "All".
  const ranges = useMemo(() => availableRanges(dailyPoints), [dailyPoints]);
  const chosenRange = ranges.includes(range) ? range : "All";
  // While zoomed nothing is "1D": no intraday bars and no day figures from the chip.
  const activeRange: Range = zoom ? "All" : chosenRange;

  // 1D has exactly two points of daily closes — yesterday's close and today's — so
  // the one period whose *shape* is the whole question drew a straight line. The
  // five-minute bars come from their own endpoint, only while 1D is on, and
  // refresh at the same cadence as the bars.
  const intradayQ = useQuery({
    queryKey: ["dashboard-intraday"],
    queryFn: () => api.get<Intraday>("/api/dashboard/intraday"),
    enabled: activeRange === "1D",
    refetchInterval: 5 * 60 * 1000,
  });

  // Fall back on the daily series as soon as there is nothing intraday to draw — a
  // holiday, a portfolio without minute data, a failed download. A flat 1D is
  // better than an empty spot.
  const intradayPoints = useMemo(
    () =>
      activeRange === "1D" && intradayQ.data?.anchored && intradayQ.data.points.length >= 2
        ? intradayAsValuePoints(intradayQ.data.points, lastDaily)
        : null,
    [activeRange, intradayQ.data, lastDaily],
  );

  const dailySlice = useMemo(
    () => (dailyPoints.length < 2 ? [] : zoom ? sliceByZoom(dailyPoints, zoom) : sliceByRange(dailyPoints, activeRange)),
    [dailyPoints, activeRange, zoom],
  );

  const valuePoints = intradayPoints ?? dailySlice;
  // On 1D the points are clock times, otherwise dates. The first point of an
  // intraday line is yesterday's close and is labelled as such.
  const probeLabel = intradayPoints !== null ? (d: string) => fmtIntradayLabel(d, valuePoints[valuePoints.length - 1].d) : fmtDayMonthYear;

  // The value change over the period split into return (prices + dividend) and
  // money you put in yourself. value_divs rises both from a deposit and from
  // performance; invested rises only from a deposit — so Δvalue_divs − Δinvested
  // is the return in euros with the deposits taken out.
  //
  // Always on the daily series, never on `valuePoints`: on 1D those are the
  // intraday bars, and rangeBreakdown reasons in days.
  const valueBreakdown = useMemo(() => rangeBreakdown(dailyPoints, dailySlice), [dailyPoints, dailySlice]);

  if (summaryQ.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("The dashboard could not load. Try again.")}
      </p>
    );
  }

  const s = summaryQ.data.summary;
  const day = summaryQ.data.day;

  // "Today" had three sources that none of the three agreed with each other: the
  // chip above reads the price cache, the daily series reads yfinance's daily
  // close and the intraday line its 5-minute feed, which runs a quarter of an hour
  // behind. On 1D the chip wins — one answer to one question — and the chart
  // anchors its start and end point to those same two prices (see _day_anchors).
  const cardFigures =
    valueBreakdown && activeRange === "1D" && day
      ? {
          ...valueBreakdown,
          end: s.prices_available ? s.total_value : valueBreakdown.end,
          gain: day.delta_eur,
          pct: day.pct,
          contrib: 0,
        }
      : valueBreakdown;

  const shownPeriod = zoom ? `${fmtDayMonthYear(zoom.from)} – ${fmtDayMonthYear(zoom.to)}` : periodLabel(activeRange);
  // What the header of the chart section shows: at rest the period, with one
  // finger the point under it, with two fingers the measured stretch.
  const headline = !cardFigures
    ? null
    : probe?.kind === "span"
      ? {
          big: trueMinus(fmtEuro(probe.delta, { plus: true })),
          primary: (
            <>
              {trx(
                "market {0}{1}",
                trueMinus(fmtEuro(probe.market, { plus: true })),
                probe.pct !== null && <> ({trueMinus(fmtPercent(probe.pct, { decimals: 2, plus: true }))})</>,
              )}
            </>
          ),
          primaryTone: probe.market >= 0 ? "text-pos" : "text-neg",
          secondary: (
            <>
              {probe.split && tr("deposits {0} · ", trueMinus(fmtEuro(probe.contrib, { plus: true })))}
              {probeLabel(probe.a.d)} – {probeLabel(probe.b.d)}
            </>
          ),
        }
      : probe?.kind === "point"
        ? {
            big: fmtEuro(probe.point.value),
            primary: <>{trx("deposited {0}", fmtEuro(probe.point.invested))}</>,
            secondary: probeLabel(probe.point.d),
          }
        : {
            big: fmtEuro(cardFigures.end),
            primary: (
              <>
                {trx(
                  "return {0}{1}",
                  trueMinus(fmtEuro(cardFigures.gain, { plus: true })),
                  cardFigures.pct !== null && <> ({trueMinus(fmtPercent(cardFigures.pct, { decimals: 1, plus: true }))})</>,
                )}
              </>
            ),
            primaryTone: cardFigures.gain >= 0 ? "text-pos" : "text-neg",
            secondary:
              Math.abs(cardFigures.contrib) >= 0.005
                ? tr("deposits {0} · {1}", trueMinus(fmtEuro(cardFigures.contrib, { plus: true })), shownPeriod)
                : `· ${shownPeriod}`,
          };

  // Gain is price result *plus* dividend: total_gain only covers unrealised +
  // realised, so without dividend the header here was about €269 too low. Without
  // a price for every position nothing is shown: the dividend alone used to show
  // here as "the whole result", with a percentage, and read as a real number.
  const totalProfit = s.total_gain + s.total_dividends;
  const profitPct = s.net_investment > 0 ? (totalProfit / s.net_investment) * 100 : null;

  const news = newsQ.data?.items ?? [];
  const since = visitQ.data?.since ?? null;
  const lastSeen = since ? parseTimestamp(since.last_seen_at) : null;
  const articlesSince = lastSeen
    ? news.filter((n) => {
        const p = n.published ? parseTimestamp(n.published) : null;
        return p !== null && p > lastSeen;
      }).length
    : 0;
  const showSince = since !== null && (Math.abs(since.value_delta) >= 0.005 || since.dividends.count > 0 || articlesSince > 0);

  const movers = moversQ.data;
  const divStats = dividendsQ.data;
  // The list of expectations: official ex-dividend dates where there are any
  // (rare), the estimate from your own history for the rest.
  const upcoming = divStats?.outlook?.upcoming ?? [];
  const nextDiv = upcoming[0] ?? null;
  const notable = news.find((n) => n.label === "M&A" || n.label === "Earnings") ?? null;
  const hasAttention = Boolean(movers?.top || movers?.bottom || nextDiv || notable);

  const alloc = allocationQ.data;
  const allocList = allocMode === "sector" ? alloc?.sector : alloc?.region;
  const slices = allocList && allocList.length > 0 ? topSlices(allocList) : [];

  // A position without a price takes the total value away ("—"). That must not
  // stay a riddle: here it says which one it is and what you can do about it.
  // `?? []` for an older API that does not send the field yet.
  const unpriced = summaryQ.data.unpriced ?? [];

  return (
    <div>
      {unpriced.length > 0 && (
        <div
          role="alert"
          className="mb-6 rounded-md px-4 py-3 text-[13px] leading-relaxed"
          style={{ background: "var(--warn-tint)", borderLeft: "3px solid var(--warn)" }}
        >
          <p className="font-medium text-warn">
            {trx("⚠ {0} without a price", unpriced.length === 1 ? tr("1 position") : tr("{0} positions", unpriced.length))}
          </p>
          <p className="mt-1">
            {trx(
              "{0}. As long as {1}, the app can't calculate your total value and return. Refresh the prices via {2} in the bar above.",
              unpriced.map((p, i) => (
                <span key={p.isin}>
                  {i > 0 && ", "}
                  <Link href={`/portfolio/${p.isin}`} className="ds-link">
                    {p.name}
                  </Link>
                </span>
              )),
              unpriced.length === 1 ? tr("it has no price") : tr("they have no price"),
              <strong>{tr("Update")}</strong>,
            )}
          </p>
        </div>
      )}

      {/* ═══ MASTHEAD — één held, en zijn drie steunfiguren ═══════════════ */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <Eyebrow>{tr("Total value")}</Eyebrow>
        <span className="text-xs text-ink-muted">
          {trx(
            "{0} positions{1}",
            <span className="num">{s.num_positions}</span>,
            summaryQ.data.oldest_price_fetch && <> {trx("· prices updated {0}", fmtRelative(summaryQ.data.oldest_price_fetch))}</>,
          )}
        </span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-end gap-x-7 gap-y-2">
        <Hero>{s.prices_available ? fmtEuro(s.total_value) : "–"}</Hero>
        {day && (
          <span className="inline-flex items-baseline gap-2.5 pb-2">
            {/* A day over part of the positions is not a day: then nothing. */}
            {day.complete ? <ValueChange value={day.delta_eur} size="md" /> : <span className="num text-ink-muted">–</span>}
            {/* "today" is a statement about when, and it was made unconditionally on a cache that
                can be days old. If the prices behind it missed a close, the label says which day it
                is really about.

                At the weekend, on a public holiday and before the open it shows €0,00: the exchange
                hasn't traded, so nothing moved today. That is not a fault and so gets no warning
                colour — only the reason behind it. */}
            <span className={`text-[13px] ${day.stale ? "text-warn" : "text-ink-muted"}`}>
              {day.market_closed
                ? tr("today · market closed")
                : day.stale && day.as_of
                  ? tr("since {0} · not current", fmtRelative(day.as_of))
                  : "today"}
            </span>
          </span>
        )}
      </div>

      {/* The ink line with the supporting figures below it. Heavy on the left, empty on the right —
          that is the asymmetry the design asks for, and not a gap. */}
      <div
        className="mt-7 grid grid-cols-2 gap-x-10 gap-y-6 pt-3.5 sm:grid-cols-3 sm:gap-x-12"
        style={{ borderTop: "1px solid var(--border-hairline)" }}
      >
        <Figure label={tr("Deposited")} value={fmtEuro(s.net_investment)} note={tr("net, after sales")} />
        <Figure
          label={tr("Total return")}
          value={s.prices_available ? trueMinus(fmtEuro(totalProfit, { plus: true })) : "–"}
          tone={s.prices_available ? (totalProfit >= 0 ? "gain" : "loss") : undefined}
          note={
            s.prices_available && profitPct !== null
              ? tr("{0} since start", trueMinus(fmtPercent(profitPct, { decimals: 1, plus: true })))
              : undefined
          }
        />
        {divStats && (
          <Figure
            label={`Dividend ${new Date().getFullYear()}`}
            value={fmtEuro(divStats.this_year)}
            note={
              divStats.outlook.rest_of_year_eur > 0
                ? tr("± {0} more expected", fmtEuro(divStats.outlook.rest_of_year_eur))
                : tr("received this year")
            }
          />
        )}
      </div>

      {/* ═══ BODY — main column and side column, one hairline between them ═════════
          Below lg the column wrappers are `display: contents`, so the sections mix into one column
          in the order a phone wants: attention first, then the chart. */}
      <div className="mt-11 flex flex-col gap-11 lg:grid lg:grid-cols-[minmax(0,1fr)_264px] lg:items-start lg:gap-14">
        {/* ── HOOFDKOLOM ─────────────────────────────────────────────── */}
        <div className="contents lg:flex lg:flex-col lg:gap-11">
          <div className="order-2 lg:order-none">
            {valueHistoryQ.isLoading ? (
              <Skeleton className="h-72" />
            ) : !s.prices_available && (valueHistoryQ.data?.points.length ?? 0) > 0 ? (
              // Without a price for every position the line drew that one position at its
              // purchase price: an estimate that looked like a measurement. Rather nothing —
              // the warning at the top says which one it is.
              <Section label={tr("Value over time")}>
                <p className="max-w-measure text-sm leading-relaxed text-ink-muted">
                  {tr("This chart comes back as soon as every position has a price.")}
                </p>
              </Section>
            ) : valuePoints.length >= 2 && cardFigures && headline ? (
              <Section
                label={tr("Value over time")}
                info={
                  <>
                    {trx(
                      "What all your positions were worth together, per day, at their closing price.{0}{1}Your deposits are included. So a rising line can also be deposits rather than return. To see what the investments themselves did, look at Returns.",
                      <br />,
                      <br />,
                    )}
                  </>
                }
                action={
                  <Link href="/returns" className="ds-link text-xs">
                    {tr("compare with indices")}
                  </Link>
                }
              >
                {/* The period picker is below the line, right above the chart it filters. Next to
                    the heading it didn't fit on a phone: the buttons fell to a second line and then
                    sat between the heading and its line.

                    `ranges` and not RANGES: a window older than your first day draws the same line
                    as "All", and three buttons that do the same read as a broken button. */}
                <span className="-mt-1 flex flex-wrap items-center gap-3">
                  <Tabs
                    variant="quiet"
                    items={periodTabs(ranges)}
                    value={zoom ? "" : activeRange}
                    onChange={(r) => {
                      setZoom(null);
                      setRange(r as Range);
                    }}
                    ariaLabel={tr("Period")}
                  />
                  {zoom && <ZoomChip zoom={zoom} onClear={() => setZoom(null)} />}
                </span>
                <ChartHeadline {...headline} />
                <ValueChart
                  points={valuePoints}
                  range={activeRange}
                  intraday={intradayPoints !== null}
                  baseline={intradayPoints !== null ? (intradayQ.data?.prev_close ?? null) : null}
                  onProbe={setProbe}
                  onSelect={setZoom}
                />
                {/* Which part of the line is filled in. Often empty, and often harmless when it
                    isn't — a fund from last month has no history from 2019 — but a replaced
                    position draws a flat stretch that can't be told apart from a real one, so it
                    has to be said somewhere. */}
                {(valueHistoryQ.data?.estimated?.length ?? 0) > 0 && (
                  <p className="text-[11.5px] text-ink-muted">
                    {trx(
                      "Without price history, estimated at {0}: {1}",
                      valueHistoryQ.data!.estimated[0].base,
                      valueHistoryQ.data!.estimated.map((e) => e.name).join(", "),
                    )}
                  </p>
                )}
              </Section>
            ) : valueHistoryQ.data?.unavailable ? (
              // Said out loud instead of left empty. The alternative was worse than an empty
              // spot: with the closes unreachable the series priced every day in the past at
              // today's price, and so drew a dead straight line that looks exactly like a
              // portfolio that stood still.
              <Section label={tr("Value over time")}>
                <p className="max-w-measure text-sm leading-relaxed text-ink-muted">
                  {tr(
                    "The price history could not be fetched from Yahoo Finance. Your positions and amounts are fine; only this chart is missing. Try again in a few minutes.",
                  )}
                </p>
              </Section>
            ) : null}
          </div>

          {/* Allocation: in the main column and not in the side column, because a horizontal bar
              gets better the wider it is. */}
          <div className="order-4 lg:order-none">
            {allocationQ.isLoading ? (
              <Skeleton className="h-32" />
            ) : slices.length > 0 && alloc ? (
              <Section
                label={tr("Allocation")}
                info={
                  <>
                    {trx(
                      "Where your money is, looked through into your funds: each company within an ETF counts for the part you own of it.{0}{1}Bond funds don't count, because sector and country data only say something about shares.",
                      <br />,
                      <br />,
                    )}
                  </>
                }
                action={
                  <Tabs
                    variant="quiet"
                    items={[
                      { id: "sector", label: "Sector" },
                      { id: "region", label: tr("Region") },
                    ]}
                    value={allocMode}
                    onChange={(m) => setAllocMode(m as "sector" | "region")}
                    ariaLabel={tr("Breakdown by")}
                  />
                }
              >
                <HBars rows={slices.map((sl) => ({ label: sl.name, value: sl.pct }))} colour="var(--chart-1)" scale="total" />
                {/* What is shown is an outcome, not an explanation: how many positions this is
                    about, and where to find the rest. How the look-through works is behind the "i"
                    on the heading. */}
                <p className="text-xs text-ink-muted">
                  {trx(
                    "Across {0} positions · {1}",
                    <span className="num">{alloc.num_positions}</span>,
                    <Link href="/allocation" className="ds-link">
                      {tr("see everything")}
                    </Link>,
                  )}
                </p>
              </Section>
            ) : null}
          </div>

          <div className="order-7 lg:order-none">
            {news.length > 0 && (
              <Section label={tr("Latest news")} meta={tr("{0} articles", news.length)}>
                <div className="flex flex-col">
                  {news.map((item, i) => (
                    <article key={item.id} className={`row-rule flex flex-col gap-1 py-3.5 ${i === 0 ? "row-rule--none pt-0" : ""}`}>
                      <div className="text-[15px] font-medium leading-snug">
                        {item.link ? (
                          <a href={item.link} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {item.title}
                          </a>
                        ) : (
                          item.title
                        )}
                      </div>
                      {/* Six coloured chips are gone: colour in this design is not a surface
                          treatment, and with six of them side by side the taxonomy was louder than
                          the headings. One quiet small-caps label does the same work. */}
                      <div className="flex flex-wrap items-baseline gap-x-2 text-[11.5px] text-ink-muted">
                        <NewsTag label={item.label} />
                        <span>{item.holding ?? item.ticker}</span>
                        {item.published && <span>· {fmtRelative(item.published)}</span>}
                        {item.publisher && <span>· {item.publisher}</span>}
                      </div>
                    </article>
                  ))}
                </div>
              </Section>
            )}
          </div>
        </div>

        {/* ── ZIJKOLOM — gescheiden door één haarlijn, niet door muren ── */}
        <aside className="contents lg:flex lg:flex-col lg:gap-10 lg:border-l lg:pl-10" style={{ borderColor: "var(--border-hairline)" }}>
          {/* The only terracotta moment on this screen. */}
          <div className="order-1 lg:order-none">
            <Section
              tone="brand"
              label={hasAttention ? tr("What deserves your attention") : tr("Nothing that needs your attention")}
              infoLabel={tr("Explanation of what deserves your attention")}
              info={
                <>
                  {trx(
                    "Four things can appear here: your biggest riser and faller of today, an upcoming dividend, and news about a takeover or quarterly results at a company you own.{0}{1}Nothing else. Nothing is ever put here to make you come back, and an empty block simply means nothing is going on.",
                    <br />,
                    <br />,
                  )}
                </>
              }
            >
              {hasAttention ? (
                <div className="flex flex-col">
                  {movers?.top && (
                    <AttentionRow
                      title={tr("Biggest riser: {0}", movers.top.name)}
                      subtitle="today"
                      value={<ValueChange value={movers.top.day_pct} percent size="sm" />}
                    />
                  )}
                  {movers?.bottom && (
                    <AttentionRow
                      title={tr("Biggest faller: {0}", movers.bottom.name)}
                      subtitle="today"
                      value={<ValueChange value={movers.bottom.day_pct} percent size="sm" />}
                    />
                  )}
                  {nextDiv && (
                    <AttentionRow
                      title={
                        nextDiv.source === "official"
                          ? tr("Ex-dividend soon: {0}", nextDiv.name ?? nextDiv.isin)
                          : tr("Dividend expected: {0}", nextDiv.name ?? nextDiv.isin)
                      }
                      subtitle={
                        nextDiv.source === "official"
                          ? fmtDayMonth(nextDiv.date)
                          : // Only to the month: the estimate knows the rhythm,
                            // not the day.
                            tr("estimate · {0} {1}", partLabel(nextDiv.part), fmtMonth(nextDiv.month))
                      }
                      value={
                        nextDiv.expected_eur !== null ? (
                          <span className="num text-[13px] text-ink-muted">± {fmtEuro(nextDiv.expected_eur)}</span>
                        ) : undefined
                      }
                    />
                  )}
                  {notable && (
                    <AttentionRow
                      title={tr("Notable news: {0}", notable.holding ?? notable.ticker)}
                      subtitle={notable.label === "M&A" ? tr("takeover or merger") : tr("quarterly results")}
                      value={
                        notable.link ? (
                          <a href={notable.link} target="_blank" rel="noopener noreferrer" className="ds-link text-xs">
                            {tr("read")}
                          </a>
                        ) : undefined
                      }
                    />
                  )}
                </div>
              ) : (
                <p className="text-[13px] leading-relaxed text-ink-muted">
                  {tr("Nothing special happened in your portfolio today. We'll tell you as soon as something changes that matters.")}
                </p>
              )}
            </Section>
          </div>

          {showSince && since && (
            <div className="order-3 lg:order-none">
              <Section tone="quiet" label={tr("Since your last visit")}>
                <dl className="flex flex-col gap-2 text-[13px]">
                  <Line label={tr("You were here")}>
                    <span className="text-ink-muted">{fmtRelative(since.last_seen_at)}</span>
                  </Line>
                  {Math.abs(since.value_delta) >= 0.005 && (
                    <Line label={tr("Portfolio")}>
                      <SignedValue value={since.value_delta} />
                    </Line>
                  )}
                  {since.dividends.count > 0 && (
                    <Line label={since.dividends.count === 1 ? tr("1 dividend paid") : tr("{0} dividends paid", since.dividends.count)}>
                      <span className="num">{fmtEuro(since.dividends.total_eur)}</span>
                    </Line>
                  )}
                  {articlesSince > 0 && (
                    <Line label={articlesSince === 1 ? tr("New article") : tr("New articles")}>
                      <span className="num">{articlesSince}</span>
                    </Line>
                  )}
                </dl>
              </Section>
            </div>
          )}

          {/* Waar het totaalrendement uit bestaat — de som achter de steunfiguur
              in de kop. */}
          <div className="order-5 lg:order-none">
            <Section
              tone="quiet"
              label={tr("Where your return comes from")}
              info={
                <>
                  {trx(
                    "The four parts your total return is made of. Added together they are the amount shown at the top under {0}.{1}{2}{3} is gain on paper: the current price against your average purchase price. {4} is gain you locked in by selling.",
                    <b>{tr("Total return")}</b>,
                    <br />,
                    <br />,
                    <b>{tr("Unrealised")}</b>,
                    <b>{tr("Realised")}</b>,
                  )}
                </>
              }
            >
              {/* The direction line above the sum, across the full column width: stuck next to the
                  label it didn't fit in 264px. */}
              {sparklineQ.data && sparklineQ.data.points.length >= 2 && <Sparkline points={sparklineQ.data.points} className="-mb-1" />}
              {s.prices_available ? (
                <BreakdownList
                  rows={[
                    { label: tr("Unrealised"), value: s.unrealized_gain_ex_costs },
                    { label: tr("Realised"), value: s.realized_gain_ex_costs },
                    { label: "Dividend", value: s.total_dividends },
                    {
                      label: tr("Transaction costs"),
                      // Made negative: the summary reports costs as a positive amount, and this is the
                      // only place where they come off.
                      value: -s.total_costs,
                      info: (
                        <InfoPopover label={tr("Explanation transaction costs")}>
                          {trx(
                            "All costs DeGiro ever charged you, over all your transactions, so also on positions you have since sold completely.{0}{1}Portfolio shows a lower amount: that only counts the positions you still have.",
                            <br />,
                            <br />,
                          )}
                        </InfoPopover>
                      ),
                    },
                  ]}
                />
              ) : (
                <p className="text-[13px] leading-relaxed text-ink-muted">
                  {trx("{0} dividend received so far: refresh the prices for the full breakdown.", fmtEuro(s.total_dividends))}
                </p>
              )}
            </Section>
          </div>

          {divStats && (
            <div className="order-6 lg:order-none">
              <Section
                tone="quiet"
                label={tr("Dividend coming up")}
                info={
                  <>
                    {trx(
                      "An amount with {0} is an estimate from your own payout history: the rhythm and the usual amount, extended. Not an official announcement.{1}{2}That's why there is a month and a part of the month and no date: the rhythm is known, the day isn't.",
                      <b>±</b>,
                      <br />,
                      <br />,
                    )}
                  </>
                }
              >
                {nextDiv ? (
                  <div className="flex flex-col gap-3">
                    <NextDividend item={nextDiv} />
                    {upcoming.length > 1 && (
                      <div className="flex flex-col">
                        {upcoming.slice(1, 4).map((it, i) => (
                          <div
                            key={`${it.isin}-${it.date}`}
                            className={`row-rule flex items-baseline gap-2.5 py-2 text-[12.5px] ${i === 0 ? "row-rule--none" : ""}`}
                          >
                            <span className="num w-[62px] flex-none text-ink-muted">
                              {it.source === "official" ? fmtDayMonth(it.date) : `${partLabel(it.part)} ${fmtMonth(it.month)}`}
                            </span>
                            <span className="min-w-0 flex-1 truncate">{it.name ?? it.isin}</span>
                            <span className="num flex-none">± {fmtEuro(it.expected_eur)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <p className="text-xs text-ink-muted">
                      {trx(
                        "{0} received this month · {1}",
                        fmtEuro(divStats.this_month),
                        <Link href="/dividend" className="ds-link">
                          {tr("all about dividend")}
                        </Link>,
                      )}
                    </p>
                  </div>
                ) : (
                  <p className="text-[13px] leading-relaxed text-ink-muted">
                    {tr("No expected payments. Here that doesn't mean nothing is coming, but that there is nothing to say.")}
                  </p>
                )}
              </Section>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/** One row in the side column: name on the left, number on the right. */
function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="min-w-0 truncate text-ink-muted">{label}</dt>
      <dd className="flex-none">{children}</dd>
    </div>
  );
}

/**
 * One thing that deserves your attention. No more coloured icon square — the
 *  number on the right carries the colour, and one per row is enough.
 */
function AttentionRow({ title, subtitle, value }: { title: string; subtitle: string; value?: React.ReactNode }) {
  return (
    <div className="row-rule flex items-baseline gap-3 py-2.5 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        {/* Two lines instead of one truncated one: on a phone the single line cut every row off at
            "Biggest faller — ISHARES MSCI E…", hiding exactly what the row is about. */}
        <div className="line-clamp-2 text-[13px] leading-snug">{title}</div>
        <div className="text-[11.5px] text-ink-muted">{subtitle}</div>
      </div>
      {value && <div className="flex-none whitespace-nowrap">{value}</div>}
    </div>
  );
}

function NextDividend({ item }: { item: DividendForecastItem }) {
  const official = item.source === "official";
  return (
    <div className="flex flex-col gap-1">
      <div className="text-[13px] font-medium leading-snug">{item.name ?? item.isin}</div>
      <div className="text-xs text-ink-muted">
        {official ? (
          <>{trx("Ex-dividend {0}", fmtDayMonth(item.date))}</>
        ) : (
          <>
            {trx("Estimate: {0} {1}{2}", partLabel(item.part), fmtMonth(item.month), item.cadence && <> · {cadenceLabel(item.cadence)}</>)}
          </>
        )}
        {item.expected_eur !== null && <> {trx("· expected {0}", <b className="num text-text">± {fmtEuro(item.expected_eur)}</b>)}</>}
      </div>
    </div>
  );
}
