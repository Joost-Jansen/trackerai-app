"use client";

// "Price on Tradegate" — the price of the exchange where the position really
// sits, on the detail screen of a position on exchange TDG.
//
// The last traded price in here *is* the position's price: value and result
// calculate with it, as at DeGiro. This block puts bid, ask, close and day range
// next to it. If the Tradegate price is not there or not current, the position
// stands at the Yahoo price (XETRA) and the block says so.
//
// A fresh price this block fetches is stored by the backend straight away as the
// price of the position; that is why the figures above are reloaded after it.
//
// A request of its own, like the chart and the look-through: Tradegate is an
// external website, and a slow or unreachable Tradegate must not hold up the
// figures above it. The backend caches per ISIN, so refreshing here does not
// cost a request to Tradegate every time.
//
// Three things are explicitly *not* done:
//   * showing bid, ask or their middle as the last traded price;
//   * presenting the fetch time as the time of the price — Tradegate does not
//     provide that time, and that is stated;
//   * hiding an error behind an old price without saying it is old.

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TradegateQuote as Quote, TradegateQuoteOk } from "@/lib/holdings";
import { fmtEu, fmtEuro, fmtNumber, fmtPercent, fmtRelative, parseTimestamp } from "@/lib/format";
import { Figure, Section } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";

/**
 * This often the page asks again. Within its cache TTL the backend returns the
 *  same answer without contacting Tradegate.
 */
const REFETCH_MS = 2 * 60 * 1000;

const LABEL = tr("Price on Tradegate");

/** Tradegate sometimes quotes to three decimals (55,028); do not round the third away. */
function decimalsFor(v: number | null): number {
  if (v === null) return 2;
  return Math.abs(v * 100 - Math.round(v * 100)) > 1e-6 ? 3 : 2;
}

function clock(ts: string): string {
  const d = parseTimestamp(ts);
  if (!d) return ts;
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getHours()}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

export default function TradegateQuote({
  isin,
  exchange,
  usedForValue,
}: {
  isin: string;
  exchange: string | null;
  /** Whether the price at the top of the page is this Tradegate price. */
  usedForValue: boolean;
}) {
  const q = useQuery({
    queryKey: ["tradegate", isin, exchange],
    queryFn: () => api.get<Quote>(`/api/holdings/${isin}/tradegate${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`),
    refetchInterval: REFETCH_MS,
    staleTime: 60 * 1000,
    retry: false,
  });

  // A new fetch time is a new price for the position: reload the figures above, so
  // value and result use the same price as this block.
  const queryClient = useQueryClient();
  const fetchedAt = q.data?.status === "ok" ? q.data.fetched_at : null;
  useEffect(() => {
    if (fetchedAt) queryClient.invalidateQueries({ queryKey: ["position", isin] });
  }, [fetchedAt, isin, queryClient]);

  if (q.isLoading) {
    return (
      <Section label={LABEL}>
        <div className="h-24 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />
      </Section>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Section label={LABEL}>
        <p className="text-sm text-ink-muted">{tr("The Tradegate price could not be loaded. Try again in a moment.")}</p>
      </Section>
    );
  }

  const d = q.data;
  // Turned off, or not applicable: then there is nothing to keep quiet about.
  if (d.status === "disabled" || d.status === "not_applicable") return null;

  if (d.status !== "ok") {
    return (
      <Section label={LABEL}>
        <p className="max-w-measure text-sm text-ink-muted">
          {trx("{0} So no Tradegate price is shown; the price at the top comes from Yahoo Finance.", d.message)}
        </p>
      </Section>
    );
  }

  return <QuoteBody d={d} usedForValue={usedForValue} />;
}

function QuoteBody({ d, usedForValue }: { d: TradegateQuoteOk; usedForValue: boolean }) {
  const price = (v: number | null) =>
    d.currency === "EUR" ? fmtEuro(v, { decimals: decimalsFor(v) }) : fmtEu(v, { decimals: decimalsFor(v), suffix: ` ${d.currency}` });

  const warnings: string[] = [];
  if (d.stale) {
    warnings.push(
      tr("Outdated: Tradegate couldn't be reached at the last attempt. This is the price from {0}.", fmtRelative(d.fetched_at)),
    );
  }
  if (!d.session_open) {
    warnings.push(tr("Tradegate was closed when fetching (trading on weekdays 7:30–22:00). The prices are from the last trading session."));
  } else if (d.traded_today === false) {
    warnings.push(tr("No trades on Tradegate today yet; the last trade price may be from an earlier trading day."));
  }
  if (d.halted || d.trading_state !== "A") {
    warnings.push(tr("Tradegate reports that trading in this product isn't running normally; bid and ask may not be current."));
  }

  return (
    <Section label={LABEL}>
      <div className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-4">
        <Figure
          label={tr("Last trade")}
          value={price(d.last)}
          note={
            d.last === null
              ? tr("no trade price provided")
              : d.change_pct !== null
                ? tr("{0} vs. close", fmtPercent(d.change_pct, { decimals: 2, plus: true }))
                : undefined
          }
          info={
            <>
              {tr(
                "The price of the last trade on Tradegate. Not the bid, not the ask and not the middle between them. Tradegate doesn't say when that trade was.",
              )}
            </>
          }
        />
        <Figure label={tr("Bid")} value={price(d.bid)} note={tr("highest buying price")} />
        <Figure label={tr("Ask")} value={price(d.ask)} note={tr("lowest selling price")} />
        <Figure label={tr("Previous day's close")} value={price(d.previous_close)} note={tr("on Tradegate")} />
      </div>

      <p className="text-xs text-ink-muted">
        {trx(
          "Day range {0} – {1}{2}{3}",
          price(d.low),
          price(d.high),
          d.volume !== null && <> {trx("· {0} units", <span className="num">{fmtNumber(d.volume, { decimals: 0 })}</span>)}</>,
          d.executions !== null && <> {trx("in {0} trades", <span className="num">{fmtNumber(d.executions, { decimals: 0 })}</span>)}</>,
        )}
      </p>

      {warnings.length > 0 && (
        <ul className="flex flex-col gap-1 text-[12.5px] text-approx">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <dl className="grid max-w-measure grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-ink-muted">
        <dt>{tr("Source")}</dt>
        <dd>{d.source}</dd>
        <dt>{tr("Currency")}</dt>
        <dd>{d.currency}</dd>
        <dt>{tr("Fetched")}</dt>
        <dd>
          {clock(d.fetched_at)} ({fmtRelative(d.fetched_at)})
        </dd>
        <dt>{tr("Price time")}</dt>
        <dd>{tr("not provided by Tradegate; the last trade may be earlier than the fetch")}</dd>
        <dt>{tr("Used for")}</dt>
        <dd>
          {usedForValue
            ? tr("the last trade is this position's price; your value and result use it")
            : tr("not used for your value now: the price at the top comes from Yahoo Finance")}
        </dd>
      </dl>
    </Section>
  );
}
