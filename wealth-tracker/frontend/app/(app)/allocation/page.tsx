"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AllocationSlice } from "@/lib/dashboard";
import { fmtEu, fmtEuro } from "@/lib/format";
import { localName, topSlices } from "@/lib/slices";
import HBars, { type HBar } from "@/components/charts/HBars";
import WorldMap from "@/components/charts/WorldMap";
import { Button, Section } from "@/components/ds";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import Disclosure from "@/components/etf/Disclosure";
import ExposureSearch from "@/components/etf/ExposureSearch";
import HoldingsTable from "@/components/etf/HoldingsTable";
import SliceTable from "@/components/etf/SliceTable";
import DownloadCsv from "@/components/etf/DownloadCsv";
import { csvNumber } from "@/lib/csv";
import QualityStrip, {
  DIVERSIFICATION_LABELS,
  EXPOSURE_LABELS,
  type QualityBucket,
} from "@/components/QualityStrip";
import { intlLocale, tr, trx } from "@/lib/i18n";

// Allocation — what your money is really in, looked through into the funds.
//
// It was called ETF analysis, which named the tool instead of the question: the
// tab looks through funds, but single shares run through it just as well (they
// are 100% exposure to themselves), and someone holding only single shares got a
// fully usable page under a name that suggested the opposite. The API prefix
// stays /api/etf-analysis: nobody sees it, and changing it along would, during a
// deploy, put an old frontend on a new backend for a name that does not exist.
//
// A port of the old Streamlit app.py:874-1112. Every percentage comes from the
// backend, which calculates it with app.py's own code: the bar for this tab is
// numeric parity, and deriving the quality ranking again in TypeScript is exactly
// how the two would start to drift apart.
//
// The four Plotly figures are gone. Sector and region are distribution bars:
// Meridian deliberately replaces the donut with a horizontal bar, because ratios
// along one axis are much easier to compare than along a circumference — and
// because it costs a fraction of the height. Countries and companies are
// horizontal bars, because those are dozens of categories with a long tail.

type Coverage = {
  name: string;
  ticker: string;
  weight_pct: number;
  dominant_region: string;
  region_data: string | boolean;
  sector_data: string | boolean;
};

type Breakdown = {
  sector: AllocationSlice[];
  continent: AllocationSlice[];
  region: AllocationSlice[];
  /**
   * The same countries without the backend's "Other" roll-up: everything under
   *  0.5% is in there by name. Optional because a backend from before this change
   *  does not send it.
   */
  region_all?: AllocationSlice[];
  coverage: Coverage[];
  excluded_pct: number;
  quality: { buckets: QualityBucket[] };
};

type EtfSource = {
  name: string;
  ticker: string;
  source: string;
  num_holdings: number;
  weight_pct: number;
  value: number;
};

type Stock = { symbol: string; name: string; value: number; sources: string[] };

type Exposure = {
  stock_list: Stock[];
  stock_coverage: number;
  etf_sources: EtfSource[];
  quality: { buckets: QualityBucket[] };
};

// What the bars show before you expand. Enough to see the shape, few enough not
// to have to scroll; the rest is behind Disclosure.
//
// Countries are not listed, and that is on purpose: that list has already been
// cut off by the backend (everything under 0.5% goes into "Other" there), and
// putting another limit of fifteen on top gave two kinds of omitted countries —
// five that were not drawn and a handful that were in "Other" — of which only one
// kind could be found anywhere.
const STOCKS_SHOWN = 20;

// app.py:973-974. region_data and sector_data contain strings *and* booleans,
// and every column spells the same source differently.
const REGION_LABELS = new Map<string | boolean, string>([
  ["exact", tr("issuer (exact)")],
  ["proxy", "index-proxy"],
  ["stock", tr("share (exact)")],
  [true, tr("justetf (estimate)")],
  [false, tr("derived from name")],
  ["manual", "manual"],
  ["excluded", "excluded"],
]);
const SECTOR_LABELS = new Map<string | boolean, string>([
  ["exact", tr("issuer (exact)")],
  ["proxy", "index-proxy"],
  ["stock", tr("share (exact)")],
  [true, tr("yfinance (estimate)")],
  [false, tr("no data")],
  ["manual", "manual"],
  ["excluded", "excluded"],
]);

// app.py:1045-1052 colours the source column by how reliable it is.
function sourceColour(source: string): string {
  if (
    source.includes("(issuer)") ||
    ["position itself", "Individual stock"].includes(source)
  )
    return "text-pos";
  if (source.startsWith("Index proxy")) return "text-proxy";
  if (source === "Yahoo top 10") return "text-approx";
  return "text-neg";
}

/**
 * A distribution bar — the same shape as the Allocation section on Today, so the
 *  same figures look the same.
 *
 *  Below it expands what is in "Other". Only that: the bar rolls everything below
 *  the top five into that one segment, and until now that was a dead end — you
 *  saw how much it was, never what it consisted of. What is already shown does
 *  not need to be below it again.
 */
function SliceSection({
  title,
  slices,
  meta,
  colour,
  noun,
  stem,
  analysedValue,
}: {
  title: string;
  slices: AllocationSlice[];
  /** Quiet context on the right of the header row — "9 sectors". */
  meta: string;
  /** The colour of the bars. Every distribution its own colour from the palette. */
  colour: string;
  /** Plural for the button text, for example "sectors". */
  noun: string;
  /** File name for the download. */
  stem: string;
  analysedValue: number;
}) {
  const data = topSlices(slices);
  if (data.length === 0) return null;
  // topSlices adds an "Other" segment if anything is left; the number that got its
  // own segment is therefore the length minus that segment.
  const misc = data[data.length - 1].name === localName("Other") ? data[data.length - 1] : null;
  const ownSlices = misc ? data.length - 1 : data.length;
  // What is in that segment: the list sorted the same way as topSlices cut it off,
  // minus the heads that got their own bar.
  const folded = [...slices].sort((a, b) => b.pct - a.pct).slice(ownSlices);
  return (
    <Section
      label={title}
      action={
        <span className="flex items-baseline gap-4">
          <span className="ds-section__meta">{meta}</span>
          {/* The full list, not what the bar shows: whoever takes the figures along doesn't want to
              find them back with "Other" in them. */}
          <DownloadCsv
            stem={stem}
            // From the title and not from `noun`: "werelddelen" minus "en" is "werelddel",
            // and a column header with a spelling mistake is a column header someone copies
            // over.
            headers={[
              title.replace(/^Naar /, "").replace(/^./, (c) => c.toUpperCase()),
              tr("Share (%)"),
              tr("Value (EUR)"),
            ]}
            rows={() =>
              [...slices]
                .sort((a, b) => b.pct - a.pct)
                .map((sl) => [
                  localName(sl.name),
                  csvNumber(sl.pct, 1),
                  csvNumber((sl.pct / 100) * analysedValue),
                ])
            }
          />
        </span>
      }
    >
      {/* One row per category, name next to its own bar: no legend to match, and the percentages
          form a column you can read separately from the bars. Scaled against the whole and not
          against the largest item — this is a distribution, so half a bar really should be half
          your portfolio. */}
      <HBars
        rows={data.map((sl) => ({ label: sl.name, value: sl.pct }))}
        colour={colour}
        scale="total"
      />
      {misc && folded.length > 0 && (
        // "the 7 sectors in Other" and not "all 12 sectors": the other five are above,
        // and a button that promises to show them all delivered them all *once more*.
        <Disclosure label={tr("Show the {0} {1} in \"Other\"", folded.length, noun)}>
          <SliceTable slices={folded} foldedPct={misc.pct} colour="var(--n-400)" />
        </Disclosure>
      )}
    </Section>
  );
}

export default function EtfAnalysisPage() {
  const queryClient = useQueryClient();
  // Which country you point at, in the backend's spelling — the map and the bars
  // share this, and that is the whole point of the two side by side. It lives here
  // and not in one of the two, because both can set it.
  const [pointed, setPointed] = useState<string | null>(null);
  const breakdown = useQuery({
    queryKey: ["etf-breakdown"],
    queryFn: () => api.get<Breakdown>("/api/etf-analysis/breakdown"),
  });

  const exposure = useQuery({
    queryKey: ["etf-exposure"],
    queryFn: () => api.get<Exposure>("/api/etf-analysis/exposure"),
  });

  const refresh = useMutation({
    mutationFn: () => api.post("/api/etf-analysis/refresh"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (breakdown.isLoading || !breakdown.data) {
    return (
      <div className="space-y-4">
        <div className="h-24 animate-pulse rounded border border-border bg-surface-2" />
        <div className="h-56 animate-pulse rounded border border-border bg-surface-2" />
      </div>
    );
  }

  const { sector, continent, region, region_all, coverage, excluded_pct, quality } =
    breakdown.data;

  // The "Other" row of the country bar, and the countries in it. The backend rolls
  // everything under 0.5% into it; without these two that segment is a number
  // without content.
  const countryOther = region.find((r) => r.name === "Other");
  const namedCountries = new Set(region.filter((r) => r.name !== "Other").map((r) => r.name));
  const foldedCountries = (region_all ?? []).filter((r) => !namedCountries.has(r.name));

  // What every percentage on this tab is measured against: your equity value after
  // taking off the bond funds. Already in the payload as the sum of what each
  // position contributes to the look-through — no extra request for a number that
  // is already there.
  const analysedValue =
    exposure.data?.etf_sources.reduce((sum, s) => sum + s.value, 0) ?? 0;

  const countryRows: HBar[] = region.map((r) => ({
    label: localName(r.name),
    // The untranslated name, because the map calculates in that.
    id: r.name,
    value: r.pct,
    // Percentage first, because this map is about distribution; the amount quietly
    // next to it, for whoever wants to know how much that is.
    secondary: analysedValue > 0 ? fmtEuro((r.pct / 100) * analysedValue) : undefined,
  }));

  // ——— The knot between the map and the bars ———
  //
  // The two do not show the same: the bar has fourteen countries plus "Other", the
  // map has all forty-five separately. If you point at a country on the map that is
  // in "Other", *that* is the bar that lights up — otherwise half the map would
  // point nowhere. The other way round, pointing at "Other" lights up that whole
  // tail at once, which shows straight away where it is.
  const foldedNames = new Set(foldedCountries.map((c) => c.name));
  const activeBarId =
    pointed === null
      ? null
      : namedCountries.has(pointed)
        ? pointed
        : pointed === "Other" || foldedNames.has(pointed)
          ? "Other"
          : null;
  const activeCountries =
    pointed === "Other" ? foldedNames : new Set(pointed ? [pointed] : []);

  // What the map draws: all countries, so also the tail that disappears into
  // "Other" in the bar. But *where* a country has a bar of its own, the map takes
  // over that bar's percentage. The backend delivers the bar list to one decimal
  // and the full list to two, and that difference put €6,213.30 in the tooltip
  // next to a bar that said €6,209.30 — the same country, two amounts.
  const barPct = new Map(region.map((r) => [r.name, r.pct]));
  const mapSlices = (region_all ?? region.filter((r) => r.name !== "Other")).map((r) => ({
    name: r.name,
    pct: barPct.get(r.name) ?? r.pct,
  }));

  const stockRows: HBar[] =
    exposure.data?.stock_list.map((s) => ({
      label: s.name || s.symbol,
      value: s.value,
      // The other way round from country: here the amount is the question and the
      // share the context.
      display: fmtEuro(s.value),
      secondary:
        analysedValue > 0
          ? fmtEu((s.value / analysedValue) * 100, { decimals: 2, suffix: "%" })
          : undefined,
      meta: s.sources.length > 0 ? `via ${s.sources.join(", ")}` : undefined,
    })) ?? [];

  return (
    <div className="flex flex-col gap-11">
      {/* What remains of the top paragraph: the only part that is about your portfolio, and that
          qualifies every percentage below. The reason bonds drop out is behind the "?" in the top
          bar; the number you need to see without clicking. */}
      {excluded_pct > 0 && (
        <p className="max-w-measure text-sm leading-relaxed text-ink-muted">{trx("{0} of your portfolio doesn't count below: those are your bond funds. So the percentages are about your equity part.", <span className="num">{fmtEu(excluded_pct, { decimals: 1, suffix: "%" })}</span>)}</p>
      )}

      {/* ——— THE INSIGHTS (app.py:881-1102) ———
          At the top, because this is what you open the tab for. Where the figures come from is
          important enough to show and not important enough to be here; that is at the bottom, under
          "How solid are these figures?". */}
      <SliceSection
        title={tr("By sector")}
        slices={sector}
        meta={`${sector.length} ${sector.length === 1 ? "sector" : "sectoren"}`}
        colour="var(--chart-1)"
        noun={tr("sectors")}
        stem="allocation-sectors"
        analysedValue={analysedValue}
      />
      <SliceSection
        title={tr("By continent")}
        slices={continent}
        meta={tr("{0} regions", continent.length)}
        colour="var(--chart-4)"
        noun={tr("continents")}
        stem="allocation-continents"
        analysedValue={analysedValue}
      />

      <Section
        label={tr("By country")}
        info={
          <>{trx("The country where each company is listed, added up over all your funds. Bar length is a share of the whole, as above.{0}{1}Country of listing, not where the revenue comes from: a Dutch company that earns nearly everything in Asia is shown here under the Netherlands.", <br />, <br />)}</>
        }
        action={
          <span className="flex items-baseline gap-4">
            {/* The number of countries you are in, not the number of bars: the two diverged as soon
                as something disappeared into "Other". */}
            <span className="ds-section__meta">{trx("{0} countries", (region_all ?? region).length)}</span>
            <DownloadCsv
              stem="allocation-countries"
              headers={[tr("Country"), tr("Share (%)"), tr("Value (EUR)")]}
              rows={() =>
                [...(region_all ?? region)]
                  .sort((a, b) => b.pct - a.pct)
                  .map((r) => [localName(r.name), csvNumber(r.pct, 2), csvNumber((r.pct / 100) * analysedValue)])
              }
            />
          </span>
        }
      >
        {/* What stays is not an explanation but an instruction: the link between map and list can't
            be seen unless you trigger it by accident. The definition of "country" is behind the "i"
            above. */}
        <p className="max-w-measure text-xs leading-relaxed text-ink-muted">{tr("Point at a country on the map or in the list and the other lights up too.")}</p>
        {/* Map on the left and wider, list on the right. The map is the overview and the list the
            answer, so in reading order the map comes first.

            A map is wide and low and a list of fifteen countries is narrow and tall, so side by
            side a gap was left under the map. That is where the expandable list with the tail goes:
            those are exactly the countries the map draws and the bars don't, so they belong next to
            each other.

            On a phone everything falls below each other in DOM order — map, then bars, then the
            expandable list — and there that list really belongs at the bottom, because it belongs
            to the "Other" bar right above it. Hence the explicit placement on lg instead of a
            different order. */}
        <div className="grid items-start gap-x-7 gap-y-5 lg:grid-cols-[1.25fr_1fr]">
          <WorldMap
            slices={mapSlices}
            analysedValue={analysedValue}
            active={activeCountries}
            onActive={setPointed}
          />
          <div className="lg:col-start-2 lg:row-start-1 lg:row-span-2">
            <HBars
              rows={countryRows}
              colour="var(--chart-5)"
              scale="total"
              activeId={activeBarId}
              onActive={setPointed}
            />
          </div>
          {countryOther && foldedCountries.length > 0 && (
            <div className="lg:col-start-1 lg:row-start-2">
              <Disclosure label={tr("Show the {0} countries in \"Other\"", foldedCountries.length)}>
                <SliceTable
                  slices={foldedCountries}
                  foldedPct={countryOther.pct}
                  colour="var(--chart-5)"
                  // Tenths of percents, so two decimals: at one decimal half the list is "0.0%".
                  decimals={2}
                />
              </Disclosure>
            </div>
          )}
        </div>
      </Section>

      {exposure.isLoading || !exposure.data ? (
        <div className="h-56 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />
      ) : (
        <Section
          label={tr("Your companies")}
          info={
            <>{trx("What you actually own per company: the value of each fund times that company's weight in it, added up over all your funds.{0}{1}A company that is in three of your ETF’s therefore appears here once, with the three pieces added together.", <br />, <br />)}</>
          }
          action={
            <DownloadCsv
              stem="allocation-companies"
              headers={[tr("Company"), "Ticker", tr("Value (EUR)"), tr("Share (%)"), "Via"]}
              rows={() =>
                [...exposure.data!.stock_list]
                  .sort((a, b) => b.value - a.value)
                  .map((h) => [
                    h.name || h.symbol,
                    h.symbol,
                    csvNumber(h.value),
                    analysedValue > 0 ? csvNumber((h.value / analysedValue) * 100) : "",
                    h.sources.join(", "),
                  ])
              }
            />
          }
        >
          {/* The search field belongs here and not at the top: the question it answers — "is this
              company in it, and for how much?" — is about this list. At the top of the page it
              stood apart from what it was about. */}
          <ExposureSearch
            sectors={sector}
            // The full country list, not the bar: here you ask a targeted question about one
            // country, and the small countries are exactly the ones you do not know whether
            // you hold.
            countries={region_all ?? region}
            holdings={exposure.data.stock_list}
            analysedValue={analysedValue}
          />

          <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--border-hairline)" }}>
            {/* The coverage is an outcome about your portfolio, not an explanation: it says how
                complete the list below is, and that changes how you read it. So it stays; the
                arithmetic behind it is behind the "i" on the heading. */}
            <p className="mb-3 text-xs text-ink-muted">{trx("About {0} of your equity value is in this list.", <strong className="num text-text">
                {fmtEu(exposure.data.stock_coverage, { decimals: 1, suffix: "%" })}
              </strong>)}</p>
            {/* Against the analysed equity value, not against the largest item and not against the
                sum of this list: the percentage next to each bar counts against that same whole,
                and the bar should draw that percentage. Apple at 5% is therefore a twentieth of the
                width, exactly like a 5% sector above. */}
            <HBars
              rows={stockRows}
              max={STOCKS_SHOWN}
              colour="var(--chart-1)"
              total={analysedValue}
            />
            {exposure.data.stock_list.length > STOCKS_SHOWN && (
              <Disclosure
                label={tr("Show all {0} companies", exposure.data.stock_list.length.toLocaleString(intlLocale))}
              >
                <HoldingsTable holdings={exposure.data.stock_list} total={analysedValue} />
              </Disclosure>
            )}
          </div>
        </Section>
      )}

      {/* ——— THE SOURCES ———
          One card at the bottom instead of three spread over the page. The two strips are the
          answer to "can I trust this" and stay visible; the two tables are the answer to "why
          exactly", and that is noise as long as you don't ask that question. */}
      <Section
        tone="quiet"
        label={tr("How solid are these figures?")}
        infoLabel={tr("Explanation of where the figures come from")}
        info={
          <>{trx("All figures on this page come from the complete holdings of each fund: the files the providers publish themselves (iShares, SPDR, Vanguard), with a sector and country label for each position.{0}{1}Funds that don't publish that in a machine-readable form fall back to an index proxy or to an estimate from Yahoo or justetf. The strips below show which part of your portfolio falls in which category.{2}{3}Holdings are kept locally for 7 days.", <br />, <br />, <br />, <br />)}</>
        }
      >
        <div className="flex flex-col gap-4">
          <div>
            <p className="ds-eyebrow mb-2 block">{tr("Sector and country breakdown")}</p>
            <QualityStrip buckets={quality.buckets} labels={DIVERSIFICATION_LABELS} />
          </div>
          {exposure.data && (
            <div>
              <p className="ds-eyebrow mb-2 block">{tr("Look-through to companies")}</p>
              <QualityStrip buckets={exposure.data.quality.buckets} labels={EXPOSURE_LABELS} />
            </div>
          )}
        </div>

        <div>
          <Button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            title={tr("Empties the local 7-day cache and fetches all holdings again.")}
          >
            {refresh.isPending ? tr("Fetching…") : tr("Fetch holdings again")}
          </Button>
        </div>

        <Disclosure label={tr("Advanced: broken down per fund")}>
          <div className="flex flex-col gap-5">
            {exposure.data && exposure.data.etf_sources.length > 0 && (
              <div>
                {/* The legend for the "Source" column hung as a paragraph under the table, where
                    you only read it after you had already not understood the words. It belongs with
                    the heading. */}
                <span className="mb-2 flex items-center gap-1">
                  <span className="ds-eyebrow">{tr("Where the holdings per fund come from")}</span>
                  <InfoPopover label={tr("Explain the sources in this table")}>{trx("{0}: the complete holdings file the fund provider publishes itself. Exact.{1}{2}{3}: the holdings of another fully replicating fund on the same index. Nearly exact: it differs only in cash buffer and rebalancing moment. Used when the provider itself publishes nothing machine-readable.{4}{5}{6}: only the ten largest positions are known. An approximation.", <b>(issuer)</b>, <br />, <br />, <b>Index proxy</b>, <br />, <br />, <b>Yahoo top 10</b>)}</InfoPopover>
                </span>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th>Ticker</th>
                        <th>{tr("Source")}</th>
                        <th className="num">Holdings</th>
                        <th className="num">{tr("Fund coverage")}</th>
                        <th className="num">{tr("Value (€)")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exposure.data.etf_sources.map((s) => (
                        <tr key={s.ticker + s.name}>
                          <td>{s.name}</td>
                          <td>{s.ticker}</td>
                          <td className={`font-semibold ${sourceColour(s.source)}`}>{s.source}</td>
                          <td className="num">{s.num_holdings}</td>
                          <td className="num">
                            {fmtEu(s.weight_pct, { decimals: 1, suffix: "%" })}
                          </td>
                          <td className="num">{fmtEuro(s.value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div>
              <p className="ds-eyebrow mb-2 block">{tr("Coverage per position")}</p>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Ticker</th>
                      <th className="num">{tr("Weight")}</th>
                      <th>{tr("Largest region")}</th>
                      <th>{tr("Country data")}</th>
                      <th>{tr("Sector data")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coverage.map((c) => (
                      <tr key={c.ticker + c.name}>
                        <td>{c.name}</td>
                        <td>{c.ticker}</td>
                        <td className="num">{fmtEu(c.weight_pct, { decimals: 2, suffix: "%" })}</td>
                        <td>{localName(c.dominant_region)}</td>
                        <td>{REGION_LABELS.get(c.region_data) ?? String(c.region_data)}</td>
                        <td>{SECTOR_LABELS.get(c.sector_data) ?? String(c.sector_data)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </Disclosure>
      </Section>
    </div>
  );
}
