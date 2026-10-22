"use client";

// Net worth shows assets, debts and how they develop.
// Income and spending are under Spending.

import Link from "next/link";
import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtEuro, fmtDayMonth, fmtDayMonthYear, fmtMonth, fmtPercent } from "@/lib/format";
import { granularityTabs } from "@/lib/timeline";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { AllocationBar, Explained, Eyebrow, Section } from "@/components/ds";
import { TERMS } from "@/lib/net-worth-terms";
import { EmptyState } from "@/components/ds";
import NetWorthChart, { type NetWorthPoint } from "@/components/charts/NetWorthChart";
import TimelineControls, { useTimeline } from "@/components/money/TimelineControls";
import Timeline from "@/components/money/Timeline";
import { boundariesOf, monthStart, monthKey, useMonthPeriods } from "@/lib/month-periods";
import { tr, trx } from "@/lib/i18n";
import { bridge, type Flow } from "@/lib/net-worth-bridge";
import type { Category } from "@/lib/money";
import { UNKNOWN } from "@/components/money/CategoryFilter";
import BankCorrections from "@/components/money/BankCorrections";

// How many completed months the average and the table cover: a year.
const MONTHS_IN_VIEW = 12;

type Overview = {
  points: NetWorthPoint[];
  from_date: string | null;
  measurements: number;
  without_balance?: string[];
  deviating_balances?: { account: string; date: string; measured: number; calculated: number }[];
  now: NetWorthPoint | null;
  change: { absolute: number; percent: number | null; since: string } | null;
  prices_unknown: boolean;
  estimated: { isin: string; name: string; base?: string }[];
  flows?: Flow[];
  /** Where your own share of shared costs counts as spending, or null. */
  shared_costs_category?: string | null;
};

// Rounded to cents first: a remainder of a fraction of a cent is zero, not "−€0.00".
const cents = (v: number) => Math.round(v * 100) / 100 || 0;
const SIGNED = (v: number) => `${cents(v) > 0 ? "+" : ""}${trueMinus(fmtEuro(cents(v)))}`;
const TONE = (v: number | null) => (v === null || cents(v) === 0 ? undefined : { color: v > 0 ? "var(--text-gain)" : "var(--text-loss)" });

function Digit({ label, value, sub, show }: { label: string; value: string; sub?: React.ReactNode; show?: "gain" | "loss" }) {
  return (
    <div className="flex flex-col gap-[5px]">
      <Eyebrow>{label}</Eyebrow>
      <span
        className="num font-display text-[21px] leading-tight tracking-[-0.02em]"
        style={show ? { color: `var(--text-${show})` } : undefined}
      >
        {trueMinus(value)}
      </span>
      <span className="num min-h-[16px] text-xs leading-[16px] text-ink-muted">{sub ?? ""}</span>
    </div>
  );
}

// One line in a month's Bank & cash: what it is, a short note on what goes in
// it, an optional action and the amount.
function Part({ label, hint, value, action }: { label: string; hint?: string; value: number; action?: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <div className="min-w-0">
        <span>{label}</span>
        {action && <span className="ml-2 text-xs">{action}</span>}
        {hint && <span className="block max-w-prose text-xs leading-snug text-ink-muted">{hint}</span>}
      </div>
      <span className="num shrink-0 whitespace-nowrap" style={TONE(value)}>
        {SIGNED(value)}
      </span>
    </div>
  );
}

export default function NetWorthPage() {
  const q = useQuery({
    queryKey: ["net_worth"],
    queryFn: () => api.get<Overview>("/api/net-worth"),
  });
  const layout = useMonthPeriods();
  const boundaries = boundariesOf(layout.data);
  const points = q.data?.points ?? [];
  const firstDay = points[0]?.d ?? new Date().toISOString().slice(0, 10);
  const lastDay = points.at(-1)?.d ?? firstDay;
  const timeline = useTimeline(firstDay, lastDay, "1Y", boundaries);
  const [granularity, setGranularity] = useState("day");
  const [openMonth, setOpenMonth] = useState<string | null>(null);
  const [openCorrections, setOpenCorrections] = useState<string | null>(null);
  const [allMonths, setAllMonths] = useState(false);
  // Which categories make up Saved and Bank & cash, for the links to Transactions.
  const categoriesQ = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<{ categories: Category[] }>("/api/categories"),
  });

  if (q.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (q.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("Net worth could not load. Try again.")}
      </p>
    );
  }

  const data = q.data!;
  const now = data.now;

  if (!now) {
    return (
      <EmptyState
        title={tr("No net worth to show yet")}
        body={tr(
          "Enter a balance on the Accounts screen, or import a DeGiro export. As soon as there is one measurement, the line starts.",
        )}
      />
    );
  }

  const assets = now.investments + now.bank;
  // Money of others you hold is in the debt stack, so net is right; the Debt card
  // shows your own debts and says it separately.
  const held = Math.abs(Math.min(0, now.held ?? 0));
  const realDebt = now.debt + held;
  const distribution = [
    { label: tr("Portfolio"), value: now.portfolio, colour: "var(--chart-3)", display: fmtEuro(now.portfolio) },
    {
      label: tr("DeGiro cash & other"),
      value: now.investments_external,
      colour: "var(--chart-6)",
      display: fmtEuro(now.investments_external),
    },
    { label: tr("Bank & cash"), value: now.bank, colour: "var(--chart-5)", display: fmtEuro(now.bank) },
  ].filter((s) => s.value > 0);

  const measurements = data.points.filter((p) => p.measured);

  // The state at the end of every month — with the salary month the day before
  // your next salary — and how much it changed. The last month is still running.
  //
  // It follows the period above: the months that fall in it, with the month
  // before the period as the base for the first change. A month the period cuts
  // off is shown up to that day and does not count in the average.
  const { from: viewFrom, to: viewTo } = timeline.window;
  const lastOfMonth = new Map<string, string>();
  for (const p of data.points) lastOfMonth.set(monthKey(p.d, boundaries), p.d);
  const final_state = new Map<string, NetWorthPoint>();
  for (const p of data.points) if (p.d <= viewTo) final_state.set(monthKey(p.d, boundaries), p);
  const flows = data.flows ?? [];
  const sharedCategory = data.shared_costs_category ?? null;
  const monthRows = [...final_state.entries()]
    .map(([month, p], i, allRows) => ({
      month,
      p,
      begin: monthStart(p.d, boundaries),
      // The day of the balance this month starts from: the last day of the month before.
      from: i > 0 ? allRows[i - 1][1].d : null,
      // Cut off by the period, or the month that is still running.
      partial: p.d !== lastOfMonth.get(month) || p.d === data.points[data.points.length - 1].d,
      difference: i > 0 ? p.net - allRows[i - 1][1].net : null,
      split: i > 0 ? bridge(allRows[i - 1][1], p, flows, sharedCategory !== null) : null,
    }))
    .filter((r) => r.p.d >= viewFrom);
  const finished = monthRows.filter((r) => !r.partial && r.difference !== null);
  const average = finished.length > 0 ? finished.reduce((s, r) => s + r.difference!, 0) / finished.length : null;
  const newestFirst = [...monthRows].reverse();
  // A year at a time: more only when the period holds more and you ask for it.
  const inView = allMonths ? newestFirst : newestFirst.slice(0, MONTHS_IN_VIEW);
  const hasSplit = inView.some((r) => r.split !== null && r.split.saved !== null);
  // The months in view added up: what the change and each of its parts came to over them (the running month included).
  const sum = (pick: (r: (typeof inView)[number]) => number | null | undefined) => {
    const values = inView.map(pick).filter((v): v is number => v != null);
    return values.length > 0 ? values.reduce((s, v) => s + v, 0) : null;
  };
  const totals = {
    months: inView.filter((r) => r.difference !== null).length,
    change: sum((r) => r.difference),
    parts: [sum((r) => r.split?.saved), sum((r) => r.split?.market), sum((r) => r.split?.bank), sum((r) => r.split?.debt)],
  };
  // The transactions behind a number: that month, those categories. Market and
  // Debt have none (holdings and debt balances), so they get no link. Bank & cash
  // leaves out the internal categories whose other side is elsewhere in net worth
  // (the broker, a repayment, your own accounts): they add up to about nothing.
  const categories = categoriesQ.data?.categories ?? [];
  const namesOf = (types: string[]) => categories.filter((c) => types.includes(c.type)).map((c) => c.name);
  const bankNames = categories.filter((c) => c.role === "bank" || (c.role === "others" && sharedCategory === null)).map((c) => c.name);
  const COLUMN_NAMES: (string[] | null)[] = [namesOf(["EXPENSE", "INCOME"]), null, bankNames, null];
  const transactionsHref = (begin: string, end: string, names: string[], extra = "") =>
    // via=net-worth: this filter is for this one look at Transactions and must not
    // stick to Overview or the other Spending tabs (lib/spending-filters.ts).
    `/spending/transactions?start=${begin}&end=${end}&${names.map((n) => `category=${encodeURIComponent(n)}`).join("&")}${extra}&via=net-worth`;
  // Bank & cash also moves with balances that are no transaction; Transactions
  // shows the difference when you arrive through the link.
  // The filter's "Onbekend" also matches a category of that name, so only when
  // that month really has transactions without a category.
  // Nothing to list: the number is then all balance corrections and money whose
  // other half isn't a bank transaction, and a link would open an empty list.
  const nothingListed = (r: (typeof monthRows)[number]) => r.split?.detail?.listed != null && Math.abs(r.split.detail.listed) < 0.005;
  const bankHref = (r: (typeof monthRows)[number]) =>
    transactionsHref(
      r.begin,
      r.p.d,
      Math.abs(r.split!.detail!.unlabelled) >= 0.005 ? [...bankNames, UNKNOWN] : bankNames,
      `&nw_bank=${r.split!.bank!.toFixed(2)}&nw_corrections=${r.split!.detail!.corrections.toFixed(2)}`,
    );

  return (
    <div className="flex flex-col gap-8">
      <Timeline
        period={timeline.period}
        onPeriod={timeline.choose}
        chips={[
          ...(timeline.period === "Custom"
            ? [{ label: `${fmtDayMonthYear(timeline.window.from)} – ${fmtDayMonthYear(timeline.window.to)}` }]
            : []),
          { label: tr("Detail: {0}", granularityTabs().find((g) => g.id === granularity)?.label ?? granularity) },
        ]}
        label={tr("Time and detail")}
      >
        <TimelineControls
          timeline={timeline}
          first={firstDay}
          last={lastDay}
          granularity={granularity}
          onGranularity={setGranularity}
          showPeriods={false}
        />
      </Timeline>
      {((data.without_balance?.length ?? 0) > 0 || (data.deviating_balances?.length ?? 0) > 0 || data.prices_unknown) && (
        <aside
          className="rounded-md border p-4 text-sm"
          style={{ borderColor: "var(--text-loss)", background: "var(--surface-inset)" }}
          aria-label="Gegevenscontrole"
        >
          <p className="font-semibold" style={{ color: "var(--text-loss)" }}>
            {tr("Data needs attention")}
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-muted">
            {(data.deviating_balances?.length ?? 0) > 0 && (
              <li>
                {trx(
                  "{0} balance measurement{1} the transactions.",
                  data.deviating_balances!.length,
                  data.deviating_balances!.length === 1 ? tr(" doesn't match") : tr("s don't match"),
                )}
              </li>
            )}
            {(data.without_balance?.length ?? 0) > 0 && (
              <li>
                {trx(
                  "{0} account{1} no balance yet; not counted.",
                  data.without_balance!.length,
                  data.without_balance!.length === 1 ? tr(" has") : tr("s have"),
                )}
              </li>
            )}
            {data.prices_unknown && <li>{tr("Part of the price history could not be fetched.")}</li>}
          </ul>
          <div className="mt-3 flex flex-wrap gap-4">
            {((data.without_balance?.length ?? 0) > 0 || (data.deviating_balances?.length ?? 0) > 0) && (
              <Link href="/accounts#data-check" className="font-semibold underline underline-offset-4">
                {tr("Check at Accounts →")}
              </Link>
            )}
            {data.prices_unknown && (
              <Link href="/details" className="font-semibold underline underline-offset-4">
                {tr("Check prices at Details →")}
              </Link>
            )}
          </div>
        </aside>
      )}
      <Section
        label={tr("Net worth")}
        meta={
          <span className="num">
            {trx("{0} measurements since {1}", data.measurements, data.from_date ? fmtDayMonthYear(data.from_date) : "–")}
          </span>
        }
        info={
          <>
            {tr(
              "Investments plus bank and cash, minus your debts. Investments is your portfolio from this app plus what's outside it: the cash balance at DeGiro and brokers such as Coinbase. The portfolio counts at market value; paid dividend is on your DeGiro cash and counts there, not again on top of the units. Transactions in “Niet meetellen” are other people's money: what you still hold of it doesn't count as your net worth. If you paid more than you received, that difference is your own expense.",
            )}{" "}
            {tr(
              "With transactions we reconstruct balances from the latest balance measurement. That's only right if all transactions are present. Without transactions we connect manual measurements with a straight line. Before the first data an account counts as zero; that can affect the growth shown.",
            )}
          </>
        }
      >
        <div className="grid grid-cols-2 gap-6 py-2 md:grid-cols-4">
          <Digit
            label={tr("Net assets")}
            value={fmtEuro(now.net)}
            sub={
              data.change
                ? `${data.change.absolute >= 0 ? "+" : ""}${trueMinus(fmtEuro(data.change.absolute))}` +
                  (data.change.percent !== null ? ` (${trueMinus(fmtPercent(data.change.percent))})` : "") +
                  tr(" since {0}", fmtDayMonthYear(data.change.since))
                : tr("one measurement")
            }
          />
          <Digit
            label={tr("Investments")}
            value={fmtEuro(now.investments)}
            sub={
              now.investments_external !== 0
                ? tr("portfolio {0} · other {1}", trueMinus(fmtEuro(now.portfolio)), trueMinus(fmtEuro(now.investments_external)))
                : now.portfolio !== 0
                  ? tr("everything in the portfolio")
                  : tr("no portfolio yet")
            }
          />
          <Digit label={tr("Bank & cash")} value={fmtEuro(now.bank)} />
          <Digit
            label={tr("Debt")}
            value={fmtEuro(realDebt)}
            show={realDebt < 0 ? "loss" : undefined}
            sub={realDebt === 0 ? tr("none") : undefined}
          />
        </div>

        {held > 0 && (
          <p className="py-2 text-sm">
            <strong>{trx("Other people's money: {0}.", fmtEuro(held))}</strong>{" "}
            <span className="text-ink-muted">
              {trx(
                "In “Niet meetellen” you received {0} more than you paid on: money that still goes to others. It's in your account, but it isn't yours, so your net worth doesn't count it. {1}",
                fmtEuro(held),
                <Link href="/spending/transactions?period=All&category=Niet%20meetellen" className="underline underline-offset-4">
                  {tr("See what's in it")}
                </Link>,
              )}
            </span>
          </p>
        )}

        {data.estimated.length > 0 && (
          <p className="py-1 text-xs text-ink-muted">
            {trx(
              "{0} position{1} without own price history: they draw a flat line that looks the same as a real one.",
              data.estimated.length,
              data.estimated.length === 1 ? "" : "s",
            )}
          </p>
        )}

        {data.points.length > 1 ? (
          <NetWorthChart
            points={data.points}
            flows={flows}
            sharedAsSpending={sharedCategory !== null}
            boundaries={boundaries}
            timeline={timeline}
            granularity={granularity}
            format={fmtEuro}
            ariaLabel={tr("Net worth over time, split into investments, bank and debt")}
          />
        ) : (
          <p className="py-6 text-sm text-ink-muted">
            {tr("One measurement isn't a trend yet. Enter a second balance on another date and the line starts.")}
          </p>
        )}

        {/* The chart as a table. A chart you can't see should still be readable — and the measured
            values are useful on their own, because those are the days you really looked. */}
        {measurements.length > 0 && (
          <details className="pt-3">
            <summary className="cursor-pointer text-xs text-ink-muted">
              {trx("The {0} measurements as a table", measurements.length)}
            </summary>
            <div className="overflow-x-auto pt-2">
              <table className="w-full min-w-[420px] text-[12.5px]">
                <thead>
                  <tr className="text-left text-ink-muted">
                    <th className="py-1.5 font-normal">{tr("Date")}</th>
                    <th className="py-1.5 text-right font-normal">{tr("Investments")}</th>
                    <th className="py-1.5 text-right font-normal">{tr("Bank & cash")}</th>
                    <th className="py-1.5 text-right font-normal">{tr("Debt")}</th>
                    <th className="py-1.5 text-right font-normal">{tr("Net")}</th>
                  </tr>
                </thead>
                <tbody>
                  {measurements.map((p) => (
                    <tr key={p.d} style={{ borderTop: "1px solid var(--rule)" }}>
                      <td className="num py-1.5 text-ink-muted">{fmtDayMonthYear(p.d)}</td>
                      <td className="num py-1.5 text-right">{trueMinus(fmtEuro(p.investments))}</td>
                      <td className="num py-1.5 text-right">{trueMinus(fmtEuro(p.bank))}</td>
                      <td className="num py-1.5 text-right">{trueMinus(fmtEuro(p.debt))}</td>
                      <td className="num py-1.5 text-right font-semibold">{trueMinus(fmtEuro(p.net))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Section>

      {distribution.length > 0 && (
        <Section
          label={tr("Where it is now")}
          meta={<span className="num">{trx("{0} in assets", fmtEuro(assets))}</span>}
          info={
            <>
              {tr(
                "Only what you have. The debt isn't in it: a breakdown of your assets with a debt running through it adds up to something meaningless.",
              )}
            </>
          }
        >
          <div className="py-2">
            <AllocationBar segments={distribution} />
          </div>
          <div className="grid gap-4 py-4 sm:grid-cols-3">
            <Digit
              label={tr("Portfolio in your assets")}
              value={assets > 0 ? fmtPercent((now.portfolio / assets) * 100) : "–"}
              sub={tr("Market value; counts in net worth")}
            />
            <Digit label={tr("Bank & cash available")} value={fmtEuro(now.bank)} sub={tr("Excluding investments and broker balances")} />
            <Digit
              label={tr("Debt against assets")}
              value={assets > 0 ? fmtPercent((Math.abs(Math.min(0, realDebt)) / assets) * 100) : "–"}
              sub={tr("Debt divided by your assets")}
            />
          </div>
          {realDebt < 0 && (
            <p className="pt-2 text-xs text-ink-muted">
              {trx("Against that is {0} of debt, which comes to {1} net.", fmtEuro(Math.abs(realDebt)), fmtEuro(now.net))}
            </p>
          )}
        </Section>
      )}

      {monthRows.length > 0 && (
        <Section
          label={boundaries ? tr("Per salary month") : tr("Per month")}
          meta={
            average !== null && (
              <span className="num">
                {trx(
                  "average {0}{1} per month over {2} {3}",
                  average >= 0 ? "+" : "",
                  trueMinus(fmtEuro(average)),
                  finished.length,
                  finished.length === 1 ? tr("month") : tr("months"),
                )}
              </span>
            )
          }
          info={
            <>
              {trx(
                "Your net worth at the end of each month{0}, and how much it changed. The average only counts completed months; the current month is shown separately. Including price movements, interest and repayment; it's not a savings amount.",
                boundaries ? tr(": the day before your next salary") : "",
              )}{" "}
              {tr(
                "The change is split into four parts that add up to it. Saved: income minus spending. Market: what your holdings did, so price changes and dividend; buying and selling doesn't count, and neither does moving money to or from your broker. Bank & cash: what moved on your bank accounts and your broker's cash apart from saving and investing, such as a repayment, a transfer to an account outside your net worth or a balance that doesn't match the transactions. Debt: your own debts; a repayment makes it positive, interest negative. Click a month for the details.",
              )}
            </>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-[12.5px]">
              <thead>
                <tr className="text-left text-ink-muted">
                  <th className="py-1.5 font-normal">{tr("Month")}</th>
                  <th className="py-1.5 text-right font-normal">
                    <Explained text={TERMS.netAtEnd()} align="right">
                      {tr("Net at the end")}
                    </Explained>
                  </th>
                  <th className="py-1.5 text-right font-normal">
                    <Explained text={TERMS.change()} align="right">
                      {tr("Change")}
                    </Explained>
                  </th>
                  {hasSplit ? (
                    <>
                      <th className="py-1.5 text-right font-normal">
                        <Explained text={TERMS.saved()} align="right">
                          {tr("Saved")}
                        </Explained>
                      </th>
                      <th className="py-1.5 text-right font-normal">
                        <Explained text={TERMS.market()} align="right">
                          {tr("Market")}
                        </Explained>
                      </th>
                      <th className="py-1.5 text-right font-normal">
                        <Explained text={TERMS.bank()} align="right">
                          {tr("Bank & cash")}
                        </Explained>
                      </th>
                      <th className="py-1.5 text-right font-normal">
                        <Explained text={TERMS.debt()} align="right">
                          {tr("Debt")}
                        </Explained>
                      </th>
                    </>
                  ) : (
                    <>
                      <th className="py-1.5 text-right font-normal">{tr("Bank & cash")}</th>
                      <th className="py-1.5 text-right font-normal">{tr("Debt")}</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {inView.map((r) => (
                  <Fragment key={r.month}>
                    <tr
                      style={{ borderTop: "1px solid var(--rule)", cursor: hasSplit ? "pointer" : undefined }}
                      onClick={hasSplit ? () => setOpenMonth(openMonth === r.month ? null : r.month) : undefined}
                      aria-expanded={hasSplit ? openMonth === r.month : undefined}
                    >
                      <td className="py-1.5">
                        <span className="flex items-start gap-1.5">
                          {hasSplit && (
                            <span
                              aria-hidden
                              className="mt-[3px] inline-block text-[9px] text-ink-muted transition-transform"
                              style={openMonth === r.month ? { transform: "rotate(90deg)" } : undefined}
                            >
                              ▶
                            </span>
                          )}
                          <span>
                            {fmtMonth(r.month)} {r.month.slice(0, 4)}
                            <span className="block text-xs text-ink-muted">
                              {r.partial
                                ? r.p.d === lastDay
                                  ? tr("still running · as of {0}", fmtDayMonth(r.p.d))
                                  : tr("up to {0}", fmtDayMonth(r.p.d))
                                : boundaries
                                  ? tr("starting {0}", fmtDayMonth(r.begin))
                                  : ""}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td className="num py-1.5 text-right font-semibold">{trueMinus(fmtEuro(r.p.net))}</td>
                      <td
                        className="num whitespace-nowrap py-1.5 text-right"
                        style={r.difference !== null ? { color: r.difference >= 0 ? "var(--text-gain)" : "var(--text-loss)" } : undefined}
                      >
                        {r.difference === null ? "–" : `${r.difference >= 0 ? "+" : ""}${trueMinus(fmtEuro(r.difference))}`}
                      </td>
                      {hasSplit ? (
                        ([r.split?.saved ?? null, r.split?.market ?? null, r.split?.bank ?? null, r.split?.debt ?? null] as const).map(
                          (v, k) => (
                            <td key={k} className="num whitespace-nowrap py-1.5 text-right" style={TONE(v)}>
                              {v === null ? (
                                "–"
                              ) : k === 2 && nothingListed(r) ? (
                                <span title={tr("No transactions behind it: open the month for the details.")}>{SIGNED(v)}</span>
                              ) : COLUMN_NAMES[k] && categoriesQ.data ? (
                                <Link
                                  href={k === 2 && r.split?.detail ? bankHref(r) : transactionsHref(r.begin, r.p.d, COLUMN_NAMES[k]!)}
                                  className="underline-offset-4 hover:underline"
                                  title={tr("Show the transactions behind this number")}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {SIGNED(v)}
                                </Link>
                              ) : (
                                SIGNED(v)
                              )}
                            </td>
                          ),
                        )
                      ) : (
                        <>
                          <td className="num py-1.5 text-right">{trueMinus(fmtEuro(r.p.bank))}</td>
                          <td className="num py-1.5 text-right">{trueMinus(fmtEuro(r.p.debt))}</td>
                        </>
                      )}
                    </tr>
                    {openMonth === r.month && (
                      <tr>
                        <td colSpan={7} className="pb-4 pt-1">
                          {/* Sticky and no wider than the screen: on a phone the table scrolls sideways,
                            the explanation stays in view. */}
                          <div
                            className="sticky left-0 grid max-w-[calc(100vw-2rem)] gap-x-10 gap-y-5 rounded-md px-4 py-3 md:grid-cols-[minmax(0,1fr)_220px]"
                            style={{ background: "var(--surface-sunken)" }}
                          >
                            {r.split?.detail && r.split.bank !== null ? (
                              <div>
                                <Eyebrow>{tr("Bank & cash this month")}</Eyebrow>
                                <div className="pt-1">
                                  {(r.split.detail.listed === null
                                    ? [
                                        {
                                          key: "transfers",
                                          label: tr("Repayments and transfers to accounts outside your net worth"),
                                          value: r.split.detail.transfers,
                                        },
                                        { key: "corrections", label: tr("Balance corrections"), value: r.split.detail.corrections },
                                        { key: "friends", label: tr("Money advanced for friends"), value: r.split.detail.friends },
                                        {
                                          key: "unlabelled",
                                          label: tr("Transactions without a category"),
                                          value: r.split.detail.unlabelled,
                                        },
                                      ]
                                    : ([
                                        {
                                          key: "listed",
                                          label: tr("Transactions"),
                                          value: r.split.detail.listed,
                                          hint: tr("Bank transactions that count here instead of under Saved."),
                                          action: nothingListed(r) ? null : (
                                            <Link href={bankHref(r)} className="text-ink-muted underline underline-offset-4 hover:text-ink">
                                              {tr("Show")}
                                            </Link>
                                          ),
                                        },
                                        {
                                          key: "corrections",
                                          label: tr("Balance corrections"),
                                          value: r.split.detail.corrections,
                                          hint: tr(
                                            "A balance that changed without a transaction of its own, such as savings topped up from your current account. Usually fine; check it per account.",
                                          ),
                                          action: r.from ? (
                                            <button
                                              type="button"
                                              className="text-ink-muted underline underline-offset-4 hover:text-ink"
                                              aria-expanded={openCorrections === r.month}
                                              onClick={() => setOpenCorrections(openCorrections === r.month ? null : r.month)}
                                            >
                                              {openCorrections === r.month ? tr("Hide") : tr("Per account")}
                                            </button>
                                          ) : null,
                                        },
                                        {
                                          key: "other_half",
                                          label: tr("No bank transaction on the other side"),
                                          value: r.split.bank - r.split.detail.listed - r.split.detail.corrections,
                                          hint: tr(
                                            "Such as a credit card bill, a debt repayment or an account entered for the first time.",
                                          ),
                                        },
                                      ] as { key: string; label: string; value: number; hint?: string; action?: React.ReactNode }[])
                                  )
                                    .filter((part) => Math.abs(part.value) >= 0.005)
                                    .map((part) => (
                                      <Fragment key={part.key}>
                                        <Part label={part.label} hint={part.hint} value={part.value} action={part.action} />
                                        {part.key === "corrections" && openCorrections === r.month && r.from && (
                                          <BankCorrections start={r.from} end={r.p.d} />
                                        )}
                                      </Fragment>
                                    ))}
                                  {Math.abs(r.split.bank) < 0.005 && (
                                    <p className="py-1 text-ink-muted">{tr("Nothing moved apart from saving and investing.")}</p>
                                  )}
                                  <div
                                    className="mt-1 flex items-baseline justify-between gap-4 pt-1.5 font-semibold"
                                    style={{ borderTop: "1px solid var(--rule)" }}
                                  >
                                    <span>{tr("Bank & cash")}</span>
                                    <span className="num" style={TONE(r.split.bank)}>
                                      {SIGNED(r.split.bank)}
                                    </span>
                                  </div>
                                </div>
                                {sharedCategory && Math.abs(r.split.shared) >= 0.005 && (
                                  <p className="pt-3 text-xs text-ink-muted">
                                    {trx(
                                      "Saved includes {0} for your own share of shared costs, counted as {1}.",
                                      SIGNED(r.split.shared),
                                      sharedCategory,
                                    )}
                                  </p>
                                )}
                              </div>
                            ) : (
                              <div />
                            )}
                            <div>
                              <Eyebrow>{tr("At the end of the month")}</Eyebrow>
                              <dl className="pt-1">
                                {(
                                  [
                                    [tr("Investments"), r.p.investments],
                                    [tr("Bank & cash"), r.p.bank],
                                    [tr("Debt"), r.p.debt],
                                  ] as const
                                ).map(([label, v]) => (
                                  <div key={label} className="flex items-baseline justify-between gap-4 py-1">
                                    <dt className="text-ink-muted">{label}</dt>
                                    <dd className="num">{trueMinus(fmtEuro(v))}</dd>
                                  </div>
                                ))}
                                <div
                                  className="mt-1 flex items-baseline justify-between gap-4 pt-1.5 font-semibold"
                                  style={{ borderTop: "1px solid var(--rule)" }}
                                >
                                  <dt>{tr("Net")}</dt>
                                  <dd className="num">{trueMinus(fmtEuro(r.p.net))}</dd>
                                </div>
                              </dl>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
              {totals.months > 1 && totals.change !== null && (
                <tfoot>
                  <tr style={{ borderTop: "1px solid var(--border-strong)" }}>
                    <td className="py-1.5 font-semibold">
                      {tr("Total")}
                      <span className="block text-xs font-normal text-ink-muted">{trx("over these {0} months", totals.months)}</span>
                    </td>
                    <td />
                    <td className="num whitespace-nowrap py-1.5 text-right font-semibold" style={TONE(totals.change)}>
                      {SIGNED(totals.change)}
                    </td>
                    {hasSplit ? (
                      totals.parts.map((v, k) => (
                        <td key={k} className="num whitespace-nowrap py-1.5 text-right font-semibold" style={TONE(v)}>
                          {v === null ? "–" : SIGNED(v)}
                        </td>
                      ))
                    ) : (
                      <>
                        <td />
                        <td />
                      </>
                    )}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          {newestFirst.length > MONTHS_IN_VIEW && (
            <button
              type="button"
              className="pt-3 text-xs text-ink-muted underline underline-offset-4"
              onClick={() => setAllMonths(!allMonths)}
            >
              {allMonths ? trx("Show the last {0} months", MONTHS_IN_VIEW) : trx("Show all {0} months in this period", newestFirst.length)}
            </button>
          )}
        </Section>
      )}
    </div>
  );
}
