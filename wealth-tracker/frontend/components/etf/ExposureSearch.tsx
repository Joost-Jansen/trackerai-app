"use client";

// "Is Novo Nordisk in it, and for how much?"
//
// The rest of the tab is built for browsing: largest sectors, largest countries,
// largest companies. This is the reverse question — you have a name in your head
// and want to know whether you own it. Without this that question can only be
// answered by going through a list of fifteen hundred items.
//
// Searches across all three dimensions at once, because the asker does not know
// beforehand whether "Germany" is a country and "Real estate" a sector — and does
// not need to. Names match both in Dutch and in the issuer's English, so both
// "duitsland" and "germany" find Germany.
//
// No result is *also* an answer, and is worded as such: "you own nothing of this"
// is what the reader wanted to know, "0 results" is not.

import { useMemo, useState } from "react";
import type { AllocationSlice } from "@/lib/dashboard";
import { fmtEu, fmtEuro } from "@/lib/format";
import { localName } from "@/lib/slices";
import { SearchIcon, CloseIcon } from "@trackerai/ui/icons";
import type { Holding } from "./HoldingsTable";
import { intlLocale, tr, trx } from "@/lib/i18n";

/**
 * Lowercase without accents: "Nestlé" must be findable as "nestle", and "ASML" as
 *  "asml".
 */
function norm(text: string): string {
  // ̀-ͯ are the separate accent characters NFD leaves behind. Written as
  // an escape and not as the characters themselves: those are invisible in an
  // editor and do not survive a copy.
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

const MIN_QUERY = 2;
const PER_GROUP = 8;

function Group({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div>
      <div className="ds-eyebrow mb-1.5 block">
        {title} <span className="num">({count})</span>
      </div>
      <div className="flex flex-col">{children}</div>
      {count > PER_GROUP && (
        <p className="mt-1 text-[11px] text-ink-muted">{trx("{0} smaller {1} not shown: type something more specific.", <span className="num">{count - PER_GROUP}</span>, count - PER_GROUP === 1 ? tr("match") : tr("matches"))}</p>
      )}
    </div>
  );
}

function Row({
  name,
  sub,
  amount,
  share,
}: {
  name: string;
  sub?: string;
  amount: string;
  share?: string;
}) {
  return (
    <div className="row-rule flex items-baseline justify-between gap-3 py-1.5 text-[12.5px]">
      <span className="min-w-0">
        <span className="block truncate">{name}</span>
        {sub && <span className="block truncate text-[11px] text-ink-muted">{sub}</span>}
      </span>
      <span className="flex flex-none items-baseline gap-2">
        {share && <span className="num text-[11px] text-ink-muted">{share}</span>}
        <span className="num font-semibold">{amount}</span>
      </span>
    </div>
  );
}

export default function ExposureSearch({
  sectors,
  countries,
  holdings,
  analysedValue,
  holdingsLoading = false,
}: {
  sectors: AllocationSlice[];
  countries: AllocationSlice[];
  holdings: Holding[];
  /** The analysed equity value: the denominator under every percentage on this tab. */
  analysedValue: number;
  /**
   * The list of companies comes from a second, slower request. Without this the
   *  search field briefly reports that you have zero companies, which reads as
   *  broken.
   */
  holdingsLoading?: boolean;
}) {
  const [query, setQuery] = useState("");
  const needle = norm(query.trim());
  const active = needle.length >= MIN_QUERY;

  const results = useMemo(() => {
    if (!active) return null;
    const matchSlice = (s: AllocationSlice) =>
      norm(s.name).includes(needle) || norm(localName(s.name)).includes(needle);
    return {
      sectors: sectors.filter(matchSlice).sort((a, b) => b.pct - a.pct),
      countries: countries.filter(matchSlice).sort((a, b) => b.pct - a.pct),
      holdings: holdings
        .filter((h) => norm(h.name).includes(needle) || norm(h.symbol).includes(needle))
        .sort((a, b) => b.value - a.value),
    };
  }, [active, needle, sectors, countries, holdings]);

  const found =
    results !== null &&
    results.sectors.length + results.countries.length + results.holdings.length > 0;

  return (
    <div>
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={tr("Search for a company, country or sector…")}
          aria-label={tr("Search your looked-through positions")}
          className="ds-input !h-11 !pl-9 !pr-9"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label={tr("Clear search")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-ink-muted hover:text-text"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        )}
      </div>

      {!active && (
        <p className="mt-2.5 text-xs text-ink-muted">{trx("Type at least {0} letters. Searches your {1}, your {2} countries and your {3} sectors at once, also by English name.", MIN_QUERY, holdingsLoading ? (
            tr("looked-through companies (still loading)")
          ) : (
            <>{trx("{0} looked-through companies", <span className="num">{holdings.length.toLocaleString(intlLocale)}</span>)}</>
          ), <span className="num">{countries.length}</span>, <span className="num">{sectors.length}</span>)}</p>
      )}

      {active && holdingsLoading && (
        <p className="mt-3 text-xs text-ink-muted">{tr("Companies are still loading…")}</p>
      )}

      {active && !holdingsLoading && !found && (
        <p className="mt-3 text-sm text-ink-muted">{trx("Nothing found for {0}. As far as this analysis reaches you don't own any of it, but mind the coverage below: for funds of which only the ten largest positions are known, a smaller position may be missing.", <span className="font-semibold text-text">{query.trim()}</span>)}</p>
      )}

      {active && found && results && (
        <div className="mt-3.5 flex flex-col gap-4">
          <Group title={tr("Sectors")} count={results.sectors.length}>
            {results.sectors.slice(0, PER_GROUP).map((s) => (
              <Row
                key={s.name}
                name={localName(s.name)}
                amount={fmtEu(s.pct, { decimals: 1, suffix: "%" })}
                share={fmtEuro((s.pct / 100) * analysedValue)}
              />
            ))}
          </Group>

          <Group title={tr("Countries")} count={results.countries.length}>
            {results.countries.slice(0, PER_GROUP).map((c) => (
              <Row
                key={c.name}
                name={localName(c.name)}
                // The tail of the country list is tenths of percents: at one decimal "am I in
                // Switzerland?" answers "0.0%", which reads as no while the answer is yes.
                amount={fmtEu(c.pct, { decimals: c.pct < 1 ? 2 : 1, suffix: "%" })}
                share={fmtEuro((c.pct / 100) * analysedValue)}
              />
            ))}
          </Group>

          <Group title={tr("Companies")} count={results.holdings.length}>
            {results.holdings.slice(0, PER_GROUP).map((h) => (
              <Row
                key={`${h.symbol}-${h.name}`}
                name={h.name || h.symbol}
                sub={h.sources.length > 0 ? `via ${h.sources.join(", ")}` : undefined}
                amount={fmtEuro(h.value)}
                share={
                  analysedValue > 0
                    ? fmtEu((h.value / analysedValue) * 100, { decimals: 2, suffix: "%" })
                    : undefined
                }
              />
            ))}
          </Group>
        </div>
      )}
    </div>
  );
}
