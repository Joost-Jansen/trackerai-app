"use client";

// One position, behind a click on a row of the Portfolio tab.
//
// Three questions, in this order, because that is the order you ask them in:
//
//   1. *What* is this? — name, kind, exchange, ticker, ISIN, currency.
//   2. What does it do? — the price of the product itself, over a period of
//      choice. Explicitly without your own purchases in it: this is the only
//      chart in the app where nothing is multiplied by a number of units, and
//      that is exactly what you look it up for.
//   3. What does it do *for you*? — quantity, value, average cost, and the
//      result split into a sum that adds up.
//
// The figures come verbatim from the same row the table shows
// (holdings_service.position_detail passes on the row from /overview), so this
// page cannot possibly show a different average cost or a different result than
// the row you clicked.
//
// The URL is /portfolio/<isin>?exchange=<code>. The exchange is in it because at
// DeGiro a position exists per product *and* exchange, each with its own average
// purchase price; it is optional because hardly anyone holds the same fund on
// two exchanges, and without it the largest position of that ISIN opens.

import { Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { type Range, availableRanges, sliceByRange } from "@/lib/dashboard";
import { type PositionDetail, type PriceHistory, type PriceIntraday, type PricePoint, type PriceProbe, priceChange } from "@/lib/holdings";
import { fmtDayMonth, fmtDayMonthYear, fmtEu, fmtEuro, fmtIntradayLabel, fmtPercent, fmtRelative, fmtShares } from "@/lib/format";
import BreakdownList from "@/components/BreakdownList";
import ChartHeadline from "@trackerai/ui/charts/ChartHeadline";
import FundBreakdown from "@/components/etf/FundBreakdown";
import PriceChart from "@/components/charts/PriceChart";
import TradegateQuote from "@/components/TradegateQuote";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { EmptyState, Figure, Section, Tabs, Tag, ValueChange } from "@/components/ds";
import { periodLabel, periodTabs } from "@/lib/timeline";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { tr, trx } from "@/lib/i18n";
import ZoomChip, { sliceByZoom, type ZoomWindow } from "@/components/charts/ZoomChip";

function Skeleton() {
  const bar = { background: "var(--surface-inset)" };
  return (
    <div className="flex flex-col gap-6">
      <div className="h-16 animate-pulse rounded" style={bar} />
      <div className="h-72 animate-pulse rounded" style={bar} />
      <div className="h-56 animate-pulse rounded" style={bar} />
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/portfolio" className="ds-btn ds-btn--ghost ds-btn--sm -ml-3">
      {tr("← Portfolio")}
    </Link>
  );
}

// useSearchParams makes Next handle a page on the client at build time; without
// this boundary that is a build error instead of a choice.
export default function PositionPage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <Position />
    </Suspense>
  );
}

/** The page of the same fund's other line: another exchange, or another broker. */
function otherHref(isin: string, v: { exchange: string | null; broker: string }): string {
  const query = new URLSearchParams();
  if (v.exchange) query.set("exchange", v.exchange);
  if (v.broker && v.broker !== "degiro") query.set("broker", v.broker);
  const q = query.toString();
  return `/portfolio/${isin}${q ? `?${q}` : ""}`;
}

function Position() {
  const { isin } = useParams<{ isin: string }>();
  const params = useSearchParams();
  const exchange = params.get("exchange") ?? params.get("beurs"); // beurs: links from before the English rename
  const [range, setRange] = useState<Range>("1Y");
  // A stretch dragged out on the chart: overrides the period buttons until cleared.
  const [zoom, setZoom] = useState<ZoomWindow | null>(null);
  // What the chart has under the finger right now. Lives here and not in the
  // chart, so the card header shows it in the space it takes up anyway — a tooltip
  // would cover the line you are reading.
  const [probe, setProbe] = useState<PriceProbe | null>(null);

  const broker = params.get("broker");
  const query = new URLSearchParams();
  if (exchange) query.set("exchange", exchange);
  if (broker) query.set("broker", broker);
  const suffix = query.toString() ? `?${query}` : "";

  const detailQ = useQuery({
    queryKey: ["position", isin, exchange, broker],
    queryFn: () => api.get<PositionDetail>(`/api/holdings/${isin}${suffix}`),
    retry: false,
  });
  const historyQ = useQuery({
    queryKey: ["position-history", isin],
    queryFn: () => api.get<PriceHistory>(`/api/holdings/${isin}/history`),
  });
  // The same array until the query changes: the memos below depend on it.
  const daily = useMemo(() => historyQ.data?.points ?? [], [historyQ.data]);

  // Which buttons this price history can live up to, and the choice set back onto
  // them. A fund you bought last month has prices from long before, but 5Y and All
  // then draw the same line.
  const ranges = useMemo(() => availableRanges(daily), [daily]);
  const activeRange = ranges.includes(range) ? range : "All";

  // 1D has exactly two points of daily closes — yesterday and today — so the one
  // period where the *shape* is the whole question would be a straight line. The
  // five-minute bars therefore come from their own endpoint, only while 1D is on,
  // and refresh at the same cadence as the bars themselves.
  const intradayQ = useQuery({
    // With the exchange: the line ends on the price of *this* position.
    queryKey: ["position-intraday", isin, exchange],
    queryFn: () => api.get<PriceIntraday>(`/api/holdings/${isin}/intraday${suffix}`),
    enabled: activeRange === "1D" && !zoom,
    refetchInterval: 5 * 60 * 1000,
  });

  const intraday = activeRange === "1D" && !zoom ? intradayQ.data : undefined;
  // Fall back on the daily series as soon as there is nothing intraday to draw: a
  // holiday, a product without minute data, a failed download. A flat 1D is better
  // than an empty card.
  const useIntraday = Boolean(intraday && intraday.points.length >= 2);
  const points: PricePoint[] = useMemo(
    () => (useIntraday ? intraday!.points : daily.length < 2 ? [] : zoom ? sliceByZoom(daily, zoom) : sliceByRange(daily, activeRange)),
    [useIntraday, intraday, daily, activeRange, zoom],
  );

  if (detailQ.isLoading) return <Skeleton />;

  if (detailQ.isError || !detailQ.data) {
    const gone = detailQ.error instanceof ApiError && detailQ.error.status === 404;
    return (
      <div>
        <BackLink />
        <EmptyState
          title={gone ? tr("You don't have this position (any more)") : tr("This position could not be loaded")}
          body={gone ? tr("Maybe it was sold, or the link is outdated. Portfolio shows what you have now.") : tr("Try again in a moment.")}
        />
      </div>
    );
  }

  const d = detailQ.data;
  const p = d.position;
  const currency = d.currency ?? "EUR";
  // The price is in the listing's currency, all amounts below it in euros — the
  // backend only calculates a position through as long as those two are the same,
  // so in practice the same sign is always shown here. Keeping visible what is in
  // what costs nothing here and keeps it from becoming an assumption.
  const price = (v: number | null | undefined, decimals = 2) =>
    currency === "EUR" ? fmtEuro(v, { decimals }) : fmtEu(v, { decimals, suffix: ` ${currency}` });
  // The price and the chart are in the currency the product trades in — TSMC in
  // dollars, as DeGiro shows it too — and the amounts below in euros. Otherwise a
  // dollar line carried a euro sign.
  const quoteCcy = d.quote_currency ?? currency;
  const quote = (v: number | null | undefined, decimals = 2) =>
    quoteCcy === "EUR" ? fmtEuro(v, { decimals }) : fmtEu(v, { decimals, suffix: ` ${quoteCcy}` });
  const quoteSign = quoteCcy === "EUR" ? "€" : "";
  const quotePrice = d.quote_price !== undefined ? d.quote_price : p.current_price;

  const last = points.length > 0 ? points[points.length - 1] : null;
  const first = points.length > 0 ? points[0] : null;
  const move = first && last ? priceChange(first, last) : null;

  // Within one day the labels are clock times, otherwise dates; the first point of
  // an intraday line is yesterday's close and is labelled as such. From a year on
  // the year is added: without it an axis of twelve months reads as "4 Aug — 2 Feb
  // — 4 Aug", with the same day twice.
  const xLabel = useIntraday
    ? (iso: string) => fmtIntradayLabel(iso, points[points.length - 1].d)
    : zoom || ["1Y", "3Y", "5Y", "All"].includes(activeRange)
      ? fmtDayMonthYear
      : fmtDayMonth;
  const probeLabel = useIntraday ? (iso: string) => fmtIntradayLabel(iso, points[points.length - 1].d) : fmtDayMonthYear;

  const headline =
    probe?.kind === "span"
      ? {
          big: quote(probe.b.c),
          primary: (
            <>
              {fmtEu(probe.delta, { plus: true, prefix: quoteSign, suffix: quoteSign ? "" : ` ${quoteCcy}` })}
              {probe.pct !== null && <> ({fmtPercent(probe.pct, { decimals: 2, plus: true })})</>}
            </>
          ),
          primaryTone: probe.delta >= 0 ? "text-pos" : "text-neg",
          secondary: (
            <>
              {probeLabel(probe.a.d)} – {probeLabel(probe.b.d)}
            </>
          ),
        }
      : probe?.kind === "point"
        ? {
            big: quote(probe.point.c),
            primary: <>{tr("price")}</>,
            secondary: probeLabel(probe.point.d),
          }
        : {
            big: quote(last?.c ?? quotePrice),
            primary: move ? (
              <>
                {fmtEu(move.delta, { plus: true, prefix: quoteSign, suffix: quoteSign ? "" : ` ${quoteCcy}` })}
                {move.pct !== null && <> ({fmtPercent(move.pct, { decimals: 2, plus: true })})</>}
              </>
            ) : (
              <>–</>
            ),
            primaryTone: (move?.delta ?? 0) >= 0 ? "text-pos" : "text-neg",
            secondary: `· ${zoom ? `${fmtDayMonthYear(zoom.from)} – ${fmtDayMonthYear(zoom.to)}` : periodLabel(activeRange)}`,
          };

  const noChart = !historyQ.isLoading && daily.length < 2;

  return (
    <div>
      <BackLink />

      {/* ═══ WHAT IS THIS ═════════════════════════════════════════════════════
          The design's two-number header: the name on the left, the price on the right. On a phone
          they fall below each other. */}
      <div className="mt-5 flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
        <div className="flex min-w-0 flex-col gap-2.5">
          {/* De identiteitsregel, in de volgorde waarin je hem voorleest: wat
              voor product, waar verhandeld, onder welk symbool, met welk nummer,
              in welke valuta. */}
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
            <Tag>{p.asset_type === "tracker" ? "Tracker" : tr("Share")}</Tag>
            {p.broker_label && <span>{p.broker_label}</span>}
            {p.exchange && <span>{trx("Exchange {0}", p.exchange)}</span>}
            {d.ticker && (
              <>
                <span aria-hidden>·</span>
                <span className="ds-table__ticker">{d.ticker}</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span className="ds-table__ticker">{p.isin}</span>
            <span aria-hidden>·</span>
            <span>{quoteCcy}</span>
          </span>
          <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{p.name}</h1>
        </div>

        <div className="flex flex-col items-start gap-1.5 sm:items-end">
          <span className="num font-display text-[34px] font-light leading-none tracking-[-0.03em]">{quote(quotePrice)}</span>
          <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            {p.day_pct !== null && <ValueChange value={p.day_pct} percent size="sm" />}
            <span className="text-xs text-ink-muted">
              {p.day_eur !== null && (d.market_closed ? <>{tr("today · market closed")}</> : <>{tr("today")}</>)}
              {d.price_fetched_at && <> {trx("· updated {0}", fmtRelative(d.price_fetched_at))}</>}
            </span>
          </span>
          {/* Where this price comes from. A price from another exchange than the position's —
              always for Tradegate, because Yahoo doesn't have it — is labelled with its name, so it
              isn't taken for the TDG price. */}
          {d.price_source && (
            <span className={`text-xs ${d.price_source.venue_fallback ? "text-approx" : "text-ink-muted"}`}>
              {d.price_source.provider === "Tradegate" ? (
                <>{tr("Tradegate · last trade")}</>
              ) : (
                <>
                  {d.price_source.provider}
                  {d.price_source.listing_venue && <> · {d.price_source.listing_venue}</>}
                  {d.price_source.venue_fallback && p.exchange && <> {trx("(not the price on exchange {0})", p.exchange)}</>}
                </>
              )}
            </span>
          )}
        </div>
      </div>

      {/* The ink line with the period picker below it — exactly as the reference screen of a single
          position has it. */}
      <div
        className="mt-7 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 pt-3.5"
        style={{ borderTop: "1px solid var(--border-hairline)" }}
      >
        <span className="flex flex-wrap items-center gap-3">
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
        <span className="text-xs text-ink-muted">
          {trx(
            "{0} · {1} transactions",
            d.first_buy && <>{trx("held since {0}", fmtDayMonthYear(d.first_buy))}</>,
            <span className="num">{d.num_transactions}</span>,
          )}
        </span>
      </div>

      {/* The same ISIN on a second exchange is a second position, with its own average cost. Only
          visible when there is one — otherwise it explains a case you don't have. */}
      {d.other_venues.length > 0 && (
        <p className="mt-5 max-w-measure text-[12.5px] leading-relaxed text-ink-muted">
          {trx(
            "You also hold this product on {0}.",
            d.other_venues.map((v, i) => (
              <span key={`${v.broker}-${v.exchange ?? i}`}>
                {trx(
                  "{0}{1} ({2} units)",
                  i > 0 && ", ",
                  <Link href={otherHref(p.isin, v)} className="ds-link">
                    {v.broker !== p.broker
                      ? [v.broker_label, v.exchange].filter(Boolean).join(" ")
                      : (v.exchange ?? tr("another exchange"))}
                  </Link>,
                  <span className="num">{fmtShares(v.shares_held)}</span>,
                )}
              </span>
            )),
          )}
        </p>
      )}

      {/* ═══ WHAT DOES IT DO ═══ The chart across the full width. ════════════ */}
      <div className="mt-8">
        {historyQ.isLoading ? (
          <div className="h-[208px] animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />
        ) : noChart ? (
          <p className="py-10 text-center text-sm text-ink-muted">
            {d.ticker
              ? tr("No price history is available for this product.")
              : tr("No price has been fetched for this product yet, so there's no line to draw yet.")}
          </p>
        ) : points.length < 2 ? (
          <p className="py-10 text-center text-sm text-ink-muted">{tr("There are no prices for this period.")}</p>
        ) : (
          <>
            <ChartHeadline {...headline} />
            <PriceChart
              points={points}
              baseline={useIntraday ? (intraday?.prev_close ?? null) : null}
              onProbe={setProbe}
              xLabel={xLabel}
              dateAxis={!useIntraday}
              onSelect={useIntraday ? undefined : setZoom}
              onReset={zoom ? () => setZoom(null) : undefined}
            />
            {/* Tradegate provides no price history: the line is from Yahoo, and its last point may
                differ a fraction from the price at the top. That should be stated, not come as a
                surprise. */}
            {d.price_source?.provider === "Tradegate" && d.ticker && (
              <p className="mt-2 text-xs text-ink-muted">
                {trx("Price history via Yahoo Finance ({0}); Tradegate provides no price history.", d.ticker)}
              </p>
            )}
          </>
        )}
      </div>

      {/* Tradegate's own price, for a position held there. A request of its own with a cache of its
          own — see TradegateQuote. */}
      {d.tradegate_quote && (
        <div className="mt-14">
          <TradegateQuote isin={p.isin} exchange={p.exchange} usedForValue={d.price_source?.provider === "Tradegate"} />
        </div>
      )}

      {/* ═══ WHAT DOES IT DO FOR YOU ═════════════════════════════════════════ */}
      <div className="mt-14 flex flex-col gap-11 lg:grid lg:grid-cols-[minmax(0,1fr)_264px] lg:items-start lg:gap-14">
        <Section label={tr("Your position")}>
          <div className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3">
            <Figure label={tr("Quantity")} value={fmtShares(p.shares_held)} />
            <Figure
              label={tr("Value")}
              value={fmtEuro(p.current_value)}
              note={p.current_price !== null ? tr("at {0}", price(p.current_price)) : undefined}
            />
            <Figure
              label={tr("Avg cost")}
              value={price(p.avg_cost_ex_costs)}
              note={tr("avg. purchase price")}
              info={
                <>
                  {trx(
                    "Your average purchase price per unit, {0} transaction costs, so it can be put directly next to the price above.",
                    <i>{tr("excluding")}</i>,
                  )}
                </>
              }
            />
            <Figure
              label={tr("Deposited")}
              value={fmtEuro(p.invested_gross)}
              note={tr("including costs")}
              info={
                <>
                  {trx(
                    "What this position cost you, {0} transaction costs. That's what really left your account, and so a different amount than your average cost times your quantity.",
                    <i>{tr("including")}</i>,
                  )}
                </>
              }
            />
            <Figure
              label={tr("Unrealised")}
              value={trueMinus(fmtEuro(p.unrealized_eur, { plus: true }))}
              tone={(p.unrealized_eur ?? 0) >= 0 ? "gain" : "loss"}
              info={
                <>
                  {tr(
                    "Gain on paper: the current price measured against your average cost, over the units you own now. If you sell nothing, this number only changes with the price.",
                  )}
                </>
              }
              note={
                p.unrealized_pct !== null
                  ? tr("{0} on {1}", trueMinus(fmtPercent(p.unrealized_pct, { decimals: 2, plus: true })), fmtEuro(p.invested_ex_costs))
                  : undefined
              }
            />
            <Figure
              label={tr("Total P/L")}
              value={trueMinus(fmtEuro(p.total_eur, { plus: true }))}
              tone={(p.total_eur ?? 0) >= 0 ? "gain" : "loss"}
              info={
                <>
                  {trx(
                    "Everything this position ever yielded you: the unrealised result, plus earlier realised gain and received dividend, minus all transaction costs.{0}{1}The breakdown next to it shows which parts this amount consists of.",
                    <br />,
                    <br />,
                  )}
                </>
              }
              note={
                p.total_pct !== null
                  ? tr("{0} on your total deposits", trueMinus(fmtPercent(p.total_pct, { decimals: 2, plus: true })))
                  : undefined
              }
            />
          </div>
          {/* With the year: the last trade may be years ago, and "last 26 Sep" then leaves open
              which 26 September that was. */}
          {d.last_trade && <p className="text-xs text-ink-muted">{trx("Last trade {0}.", fmtDayMonthYear(d.last_trade))}</p>}
        </Section>

        {/* The sum that connects the two result numbers. The same shape as the breakdown on Today,
            here for one position. */}
        <aside className="lg:border-l lg:pl-10" style={{ borderColor: "var(--border-hairline)" }}>
          <Section tone="quiet" label={tr("How that result is built up")}>
            <BreakdownList
              rows={[
                { label: tr("Unrealised"), value: p.unrealized_eur },
                {
                  label: tr("Realised"),
                  value: p.realized_eur,
                  info: (
                    <InfoPopover label={tr("Explanation realised result")}>
                      {tr(
                        "What earlier (partial) sales of this position yielded, measured against the average purchase price at that moment. Zero as long as you haven't sold anything.",
                      )}
                    </InfoPopover>
                  ),
                },
                { label: "Dividend", value: p.dividends_eur },
                { label: tr("Costs"), value: -p.costs_eur },
              ]}
              total={{ label: tr("Total P/L"), value: p.total_eur }}
            />
          </Section>
        </aside>
      </div>

      {/* ═══ WHAT'S IN IT ══════════════════════════════════════════════════
          Only for a tracker: a share is one company, and there is nothing to break down. The
          section fetches its own data — see the header of FundBreakdown for why that is a separate
          request. */}
      {p.asset_type === "tracker" && <FundBreakdown isin={p.isin} exchange={p.exchange} />}
    </div>
  );
}
