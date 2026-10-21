"use client";

// "What is in it" — the look-through of one fund, at the bottom of a position's
// detail screen.
//
// The fourth question of that page, after what is this / what does it do / what
// does it do for you. It is at the bottom because that is the order you ask in,
// and because it is the only one of the four that needs a file from the issuer:
// a request of its own, so a cold cache does not hold up the price above it.
//
// Three blocks, all three scaled against the whole fund (scale="total",
// total={100}). That is the same agreement as on Allocation, and it matters more
// here than there: half a bar for the companies then means half the fund, and
// not "half of the largest item". In a fund of 500 companies the largest item is
// a dash — exactly what "how spread is this" deserves as an answer, and the
// difference with a sector fund (where one name fills a fifth of the bar) is
// visible at once.

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FundBreakdown as Breakdown } from "@/lib/holdings";
import { fmtEuro, fmtPercent } from "@/lib/format";
import HBars, { type HBar } from "@/components/charts/HBars";
import Disclosure from "@/components/etf/Disclosure";
import { Section } from "@/components/ds";
import { localName } from "@/lib/slices";
import { tr, trx } from "@/lib/i18n";

/**
 * How many companies are shown directly; the rest of the twenty is behind the
 *  expand. Ten is what fits on a phone without pushing the sectors below it out
 *  of view.
 */
const SHOWN = 10;

/**
 * How many countries the bars draw. Above eight the tail becomes tenths of
 *  percents, and those are already counted below the list.
 */
const COUNTRIES_SHOWN = 8;

/**
 * The source in plain words. The backend spells it as the Allocation tab needs
 *  it in its source column ("Vanguard (issuer)"), and that is a word that adds
 *  nothing on this page.
 */
function sourceLine(b: Breakdown): string {
  if (b.quality === "proxy") return tr("via a fund on the same index");
  return tr("according to {0}", (b.source ?? "").replace(" (issuer)", ""));
}

/** A company row: the weight in the fund, and your money behind it. */
function holdingRows(rows: Breakdown["holdings"]): HBar[] {
  return rows.map((h) => ({
    label: h.name,
    value: h.pct,
    // Two decimals: below the top ten the difference between 0.7% and 0.6% is the
    // whole order, and at one decimal there are four bars of 0.5% one below the other
    // that are not the same length.
    display: fmtPercent(h.pct, { decimals: 2 }),
    secondary: h.value !== null ? fmtEuro(h.value, { decimals: 0 }) : undefined,
  }));
}

function sliceRows(rows: { name: string; pct: number }[]): HBar[] {
  return rows.map((s) => ({ label: localName(s.name), value: s.pct }));
}

export default function FundBreakdown({ isin, exchange }: { isin: string; exchange: string | null }) {
  const suffix = exchange ? `?exchange=${encodeURIComponent(exchange)}` : "";
  const q = useQuery({
    queryKey: ["fund-breakdown", isin, exchange],
    queryFn: () => api.get<Breakdown>(`/api/holdings/${isin}/breakdown${suffix}`),
    // A fund file changes at most once per trading day and the backend keeps it for
    // a week; fetching again because the tab gets focus is then pure traffic.
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  if (q.isLoading) {
    return <div className="mt-14 h-64 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }

  // A failed request leaves the whole section out. There is a complete screen
  // around it otherwise, and a red bar below your position suggests something is
  // wrong with your position.
  if (q.isError || !q.data) return null;

  const b = q.data;

  if (b.source === null) {
    return (
      <Section label={tr("What's in it")} className="mt-14">
        <p className="max-w-measure text-[13px] leading-relaxed text-ink-muted">
          {tr("The issuer of this fund doesn't publish a position list the app can read, so what's in it can't be shown here.")}
        </p>
      </Section>
    );
  }

  const shown = b.holdings.slice(0, SHOWN);
  const rest = b.holdings.slice(SHOWN);
  const countries = b.countries.slice(0, COUNTRIES_SHOWN);
  const foldedCountries = b.num_countries - countries.length;

  return (
    <Section
      label={tr("What's in it")}
      meta={<>{trx("{0} positions · {1}", <span className="num">{b.num_holdings}</span>, sourceLine(b))}</>}
      info={
        <>
          {trx(
            "The weights come from the file the fund provider publishes itself, the same source the Allocation tab is made from.{0}{1}The percentages are the fund's. The amount next to it is your part: the value of this position times that weight.",
            <br />,
            <br />,
          )}
        </>
      }
      className="mt-14"
    >
      <div className="flex flex-col gap-9 lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-12 lg:gap-y-10">
        {/* On a wide screen the companies fill the left column over two rows: that list is twice as
            tall as either of the two next to it. */}
        <div className="lg:row-span-2">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 className="text-[13px] font-medium">{tr("Largest positions")}</h3>
            {b.top10_pct !== null && (
              <span className="text-xs text-ink-muted">
                top 10 = <span className="num">{fmtPercent(b.top10_pct, { decimals: 1 })}</span>
              </span>
            )}
          </div>
          <HBars rows={holdingRows(shown)} colour="var(--chart-1)" scale="total" total={100} />
          {rest.length > 0 && (
            <Disclosure label={tr("Show the next {0} of {1}", rest.length, b.num_holdings)} labelOpen={tr("Hide those ten")}>
              <HBars rows={holdingRows(rest)} colour="var(--chart-1)" scale="total" total={100} />
            </Disclosure>
          )}
        </div>

        <div>
          <h3 className="mb-3 text-[13px] font-medium">{tr("Sectors")}</h3>
          <HBars rows={sliceRows(b.sectors)} colour="var(--chart-3)" scale="total" total={100} />
        </div>

        <div>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 className="text-[13px] font-medium">{tr("Countries")}</h3>
            <span className="text-xs text-ink-muted">
              <span className="num">{b.num_countries}</span> {b.num_countries === 1 ? tr("country") : tr("countries")}
            </span>
          </div>
          <HBars rows={sliceRows(countries)} colour="var(--chart-5)" scale="total" total={100} />
          {foldedCountries > 0 && (
            // Never cut off silently — the same rule HBars itself applies. It cannot say it
            // here, because those countries are not in the rows it got.
            <p className="mt-2.5 border-t border-border pt-2 text-[11px] text-ink-muted">
              {trx("{0} smaller countries not shown", <span className="num">{foldedCountries}</span>)}
            </p>
          )}
        </div>
      </div>
    </Section>
  );
}
