"use client";

// Portfolio — every open position on one screen, and how each one is doing.
//
// Two layouts of the same rows, not two feature sets: from `md` a full table
// with the whole cost breakdown, below it a list with what really matters on a
// phone (the result in euros and percent, the price, the size and the average
// cost). A table that scrolls sideways technically "works" on a phone, but the
// two columns you came for are exactly the columns out of view.
//
// `md` and not `sm`: the full table needs ~690px of the 718px a 768px screen
// leaves inside the layout, and nothing below that.
//
// The Today/All time switch changes *what* the result column measures — the
// identity columns (name, quantity, price, value, average cost) stay, so
// switching does not feel like another page. Both states come from one server
// response.
//
// Prices are at two decimals here, where Details uses four: this is the tab you
// scan, that is the tab you reconcile with DeGiro. Price and average cost share
// their precision, so the pair can be compared at a glance.

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtEuro, fmtPercent, fmtRelative, fmtShares } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { type Holding, type HoldingsOverview, type Mode, groupHoldings, resultFor } from "@/lib/holdings";
import { Eyebrow, EmptyState, Hero, Section, SignedValue, Tabs, ValueChange } from "@/components/ds";
import { ListIcon } from "@trackerai/ui/icons";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { tr, trx } from "@/lib/i18n";

type SortKey = "name" | "shares" | "price" | "value" | "avg_cost" | "result";

/**
 * Where a row points to: the position page of this product on this exchange.
 *
 *  The exchange is in the query and not in the path, because it may be missing —
 *  at DeGiro it *is* what keeps two rows of the same fund apart, but it is not
 *  always known, and a path with an empty segment is not a path.
 */
function positionHref(h: Holding): string {
  const params = new URLSearchParams();
  if (h.exchange) params.set("exchange", h.exchange);
  // The broker too, for a fund held at two brokers: each is its own line with its own average cost.
  if (h.broker && h.broker !== "degiro") params.set("broker", h.broker);
  const query = params.toString();
  return `/portfolio/${encodeURIComponent(h.isin)}${query ? `?${query}` : ""}`;
}

/** The key of a row: the same fund can be held on two exchanges and at two brokers. */
const rowKey = (h: Holding) => `${h.isin}-${h.broker ?? ""}-${h.exchange ?? ""}`;

// Empty values sort last in both directions: a position without a price is
// missing data, not the worst performer, and should not lead the table when you
// sort by return.
function compare(a: number | string | null, b: number | string | null, dir: 1 | -1): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "string" || typeof b === "string") {
    return String(a).localeCompare(String(b)) * dir;
  }
  return (a - b) * dir;
}

function sortValue(h: Holding, key: SortKey, mode: Mode): number | string | null {
  switch (key) {
    case "name":
      return h.name;
    case "shares":
      return h.shares_held;
    case "price":
      return h.current_price;
    case "value":
      return h.current_value;
    case "avg_cost":
      return h.avg_cost_ex_costs;
    case "result":
      return resultFor(h, mode)[0];
  }
}

/**
 * A result cell: the amount with the percentage below it.
 *
 *  One column instead of two. Four separate euro/percent columns pushed the
 *  unrealised pair off the right edge at every width below ~1500px — exactly the
 *  figures this tab exists for — while the stacked pair keeps the table within a
 *  laptop screen and still reads as one number.
 */
function ResultCell({ eur, pct }: { eur: number | null; pct: number | null }) {
  return (
    <td className="num whitespace-nowrap">
      <SignedValue value={eur} />
      <div className="text-[12px]">
        <SignedValue value={pct} prefix="" suffix="%" />
      </div>
    </td>
  );
}

/** A sortable column header. Number columns keep their right alignment. */
function Th({
  label,
  sortKey,
  active,
  dir,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: SortKey;
  active: boolean;
  dir: 1 | -1;
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  return (
    <th className={`sortable ${className}`} aria-sort={active ? (dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(sortKey)} className="inline-flex items-center gap-1">
        {label}
        {/* The arrow only marks the active column — a fixed marker on all eight headings reads as
            noise. */}
        {active && <span className="text-[11px]">{dir === 1 ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}

export default function PortfolioPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("all");
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [dir, setDir] = useState<1 | -1>(-1);

  const q = useQuery({
    queryKey: ["holdings-overview"],
    queryFn: () => api.get<HoldingsOverview>("/api/holdings/overview"),
  });

  const rows = useMemo(() => {
    const list = [...(q.data?.positions ?? [])];
    list.sort((a, b) => compare(sortValue(a, sortKey, mode), sortValue(b, sortKey, mode), dir));
    return list;
  }, [q.data, sortKey, dir, mode]);

  // Sorting applies *within* each group, not across — the grouping is the outer
  // ordering, so sorting by value ranks the funds against the funds.
  const groups = useMemo(() => groupHoldings(rows), [rows]);

  function onSort(key: SortKey) {
    if (key === sortKey) {
      setDir((d) => (d === 1 ? -1 : 1));
      return;
    }
    setSortKey(key);
    // Names read naturally from A to Z; every number is more interesting largest first.
    setDir(key === "name" ? 1 : -1);
  }

  if (q.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <div className="h-24 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />
        <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />
      </div>
    );
  }

  if (q.isError || !q.data) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("The portfolio could not be loaded.")}
      </p>
    );
  }

  // The oldest, not the newest: see holdings_service.oldest_price_fetch.
  const { totals, oldest_price_fetch: fetchedAt } = q.data;

  if (totals.num_positions === 0) {
    return (
      <EmptyState
        icon={<ListIcon className="h-[22px] w-[22px]" />}
        title={tr("No positions yet")}
        body={
          <>
            {trx(
              "Upload your DeGiro transactions via {0} in the bar above; after that every position is here with its result.",
              <b>{tr("Update")}</b>,
            )}
          </>
        }
      />
    );
  }

  const day = totals.day;
  // With more than one broker every row says where it is held, and the masthead splits the value per broker.
  const byBroker = totals.by_broker ?? [];
  const manyBrokers = byBroker.length > 1;
  const incomplete = mode === "day" ? day !== null && !day.complete : !totals.total.complete;

  return (
    <div>
      {/* ═══ MASTHEAD ══════════════════════════════════════════════════════
          What these positions are worth together and how they moved today, and nothing else. The
          result breakdown that used to be here (unrealised, realised, dividend, costs) is Today's
          job; repeating it here only raised the question why the two cost amounts differed, because
          this tab counts open positions and Today everything. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <Eyebrow>{tr("Value of your positions")}</Eyebrow>
        <span className="text-xs text-ink-muted">
          {trx(
            "{0} positions{1}{2}",
            <span className="num">{totals.num_positions}</span>,
            fetchedAt && <> {trx("· updated {0}", fmtRelative(fetchedAt))}</>,
            incomplete && <span className="text-warn"> {tr("· not all positions counted")}</span>,
          )}
        </span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-end gap-x-7 gap-y-2">
        <Hero>{totals.prices_available ? fmtEuro(totals.value) : "–"}</Hero>
        {day && (
          <span className="inline-flex items-baseline gap-2.5 pb-2">
            {/* A day over part of the positions is not a day: then nothing. */}
            {day.complete ? (
              <>
                <ValueChange value={day.delta_eur} size="md" />
                <span className="num text-[13px] text-ink-muted">{trueMinus(fmtPercent(day.pct, { decimals: 2, plus: true }))}</span>
              </>
            ) : (
              <span className="num text-ink-muted">–</span>
            )}
            {/* The same wording as the chip on Today — including what it says when the prices
                behind it aren't today's, and what it says when the exchange didn't open at all
                today, so the two can't possibly claim a different day. */}
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

      {manyBrokers && (
        <p className="mt-2 text-xs text-ink-muted">
          {byBroker.map((b, i) => (
            <span key={b.broker}>
              {i > 0 && " · "}
              {trx(
                "{0} {1} ({2} costs)",
                b.label,
                <span className="num">{b.prices_available ? fmtEuro(b.value) : "–"}</span>,
                <span className="num">{fmtEuro(b.costs_eur)}</span>,
              )}
            </span>
          ))}
        </p>
      )}

      {/* ═══ POSITIONS ══════════════════════════════════════════════════════
          The quiet switch sits right above the list it changes, and not as chrome at the top of the
          page — it only decides what the result column measures. */}
      <div className="mt-9 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <span className="flex items-center gap-1">
          <Eyebrow>{tr("Result measured over")}</Eyebrow>
          <InfoPopover label={tr("Explanation result measured over")}>
            {trx(
              "This switch only decides what the result column measures, not which positions are shown.{0}{1}{2} puts the current price against the previous close. {3} puts it against everything you ever put in, including earlier sales, received dividend and transaction costs.",
              <br />,
              <br />,
              <b>{tr("Today")}</b>,
              <b>{tr("All time")}</b>,
            )}
          </InfoPopover>
        </span>
        <Tabs
          variant="quiet"
          items={[
            { id: "day", label: tr("Today") },
            { id: "all", label: tr("All time") },
          ]}
          value={mode}
          onChange={(m) => setMode(m as Mode)}
          ariaLabel={tr("Which result")}
        />
      </div>

      <div className="mt-9 flex flex-col gap-10">
        {groups.map((group) => (
          <Section key={group.label} label={group.label} meta={tr("{0} positions", group.rows.length)}>
            {/* ── TELEFOON: gelijnde rijen ───────────────────────────────── */}
            {/* The table headings sort by themselves, but on a phone there are none. This one
                button reverses the order — the list always ranks by position value, largest first. */}
            <button
              type="button"
              onClick={() => onSort("value")}
              className="-mt-1 inline-flex items-center gap-1 self-start text-[11.5px] text-ink-muted hover:text-text md:hidden"
            >
              {trx("By value {0}", dir === -1 ? "↓" : "↑")}
            </button>
            <ul className="md:hidden">
              {group.rows.map((h, i) => {
                const [eur, pct] = resultFor(h, mode);
                return (
                  <li key={rowKey(h)} className={`row-rule ${i === 0 ? "row-rule--none" : ""}`}>
                    {/* The whole row is the link, not just the name: on a phone the name is a touch
                        target of two lines of text in a row that otherwise looks fully tappable. */}
                    <Link href={positionHref(h)} className="block py-3 active:opacity-60">
                      <div className="flex items-baseline justify-between gap-3">
                        <h3 className="min-w-0 text-[14px] font-medium leading-snug">{h.name}</h3>
                        <span className="num flex-none text-[14px]">{fmtEuro(h.current_value)}</span>
                      </div>
                      <div className="mt-1 flex items-baseline justify-between gap-3 text-[11.5px] text-ink-muted">
                        <span className="leading-snug">
                          {manyBrokers && <span className="mr-1.5">{h.broker_label}</span>}
                          {h.exchange && <span className="mr-1.5">{h.exchange}</span>}
                          <span className="num">{fmtEuro(h.current_price, { decimals: 2 })}</span> ×{" "}
                          <span className="num">{fmtShares(h.shares_held)}</span>
                          {" · "}
                          <span className="whitespace-nowrap">
                            {trx("Avg cost {0}", <span className="num">{fmtEuro(h.avg_cost_ex_costs, { decimals: 2 })}</span>)}
                          </span>
                        </span>
                        <span className="flex flex-none flex-col items-end whitespace-nowrap leading-snug">
                          <ValueChange value={eur} size="sm" />
                          <SignedValue value={pct} prefix="" suffix="%" className="text-[11.5px]" />
                        </span>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>

            {/* ── BREED: de volledige tabel ──────────────────────────────── */}
            <div className="table-scroll hidden md:block">
              <table className="data-table">
                <thead>
                  <tr>
                    <Th label={tr("Name")} sortKey="name" active={sortKey === "name"} dir={dir} onSort={onSort} />
                    {/* ISIN is reconciliation detail, not something you scan; it only earns its
                        width on the widest screens. */}
                    <th className="hidden xl:table-cell">ISIN</th>
                    <Th label={tr("Quantity")} sortKey="shares" active={sortKey === "shares"} dir={dir} onSort={onSort} className="num" />
                    <Th label={tr("Price")} sortKey="price" active={sortKey === "price"} dir={dir} onSort={onSort} className="num" />
                    {mode === "day" && <th className="num hidden lg:table-cell">{tr("Previous close")}</th>}
                    <Th label={tr("Value")} sortKey="value" active={sortKey === "value"} dir={dir} onSort={onSort} className="num" />
                    <Th
                      label={tr("Avg cost")}
                      sortKey="avg_cost"
                      active={sortKey === "avg_cost"}
                      dir={dir}
                      onSort={onSort}
                      className="num"
                    />
                    <Th
                      label={mode === "day" ? tr("Today") : tr("Total P/L")}
                      sortKey="result"
                      active={sortKey === "result"}
                      dir={dir}
                      onSort={onSort}
                      className="num"
                    />
                    {mode === "all" && <th className="num">{tr("Unreal.")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((h) => {
                    const [eur, pct] = resultFor(h, mode);
                    return (
                      <tr
                        key={rowKey(h)}
                        // The whole row opens the position, as in DeGiro. The name is a real link as
                        // well: that is what the keyboard and the middle mouse button need, and what a
                        // row with only an onClick never gives.
                        onClick={() => router.push(positionHref(h))}
                        className="cursor-pointer"
                      >
                        {/* The only column that may wrap: fund names run past 45 characters and
                            nowrap would push the rest away. The min-width keeps the browser from
                            solving the overflow by squeezing this column into a ribbon of six lines
                            — it takes its space first, and the table only scrolls when it has to. */}
                        <td className="min-w-[11rem] max-w-[19rem] whitespace-normal leading-snug">
                          <Link href={positionHref(h)} className="ds-table__name hover:underline">
                            {h.name}
                          </Link>
                          {/* The exchange is what makes two rows of the same product different
                              rows, so it can't live in the ISIN column — that disappears below xl,
                              and the pair would read as a duplicate row. */}
                          {h.exchange && <span className="ds-table__ticker ml-1.5 whitespace-nowrap">{h.exchange}</span>}
                          {manyBrokers && <span className="ds-table__ticker ml-1.5 whitespace-nowrap">{h.broker_label}</span>}
                        </td>
                        <td className="ds-table__ticker hidden xl:table-cell">{h.isin}</td>
                        <td className="num">{fmtShares(h.shares_held)}</td>
                        <td className="num">{fmtEuro(h.current_price, { decimals: 2 })}</td>
                        {mode === "day" && (
                          <td className="num hidden text-ink-muted lg:table-cell">{fmtEuro(h.previous_close, { decimals: 2 })}</td>
                        )}
                        <td className="num font-medium">{fmtEuro(h.current_value)}</td>
                        <td className="num text-ink-muted">{fmtEuro(h.avg_cost_ex_costs, { decimals: 2 })}</td>
                        <ResultCell eur={eur} pct={pct} />
                        {mode === "all" && <ResultCell eur={h.unrealized_eur} pct={h.unrealized_pct} />}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        ))}
      </div>
    </div>
  );
}
