"use client";

// The filter block of Spending: period, account, categories and — on
// Transactions — direction and search term. The values are in the address bar;
// see lib/spending-filters.ts.

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Input, Select, Tabs } from "@/components/ds";
import TimelineControls from "@/components/money/TimelineControls";
import { periodLabel, periodTabs, PERIODS } from "@/lib/timeline";
import AccountFilter from "@/components/money/AccountFilter";
import CategoryFilter from "@/components/money/CategoryFilter";
import CountsFilter, { countsLabel } from "@/components/money/CountsFilter";
import type { Category, Account } from "@/lib/money";
import Link from "next/link";
import { fmtDayMonthYear } from "@/lib/format";
import { DEFAULT_PERIOD, type Direction, type SpendingFilters } from "@/lib/spending-filters";
import { monthName, type Month } from "@/components/money/charts/base";
import { tr } from "@/lib/i18n";

/**
 * The month of the month cards, in the bar next to the periods: ‹ This month ›.
 * A month other than the current one is marked, with a × back to this month.
 */
export function MonthPicker({
  choices,
  value,
  monthWord,
  onChange,
}: {
  /** Ascending; the last is the current month. */
  choices: Month[];
  value: string;
  monthWord: string;
  onChange: (key: string) => void;
}) {
  const current = choices[choices.length - 1]?.key ?? "";
  const found = choices.findIndex((m) => m.key === value);
  const k = found >= 0 ? found : choices.length - 1;
  const picked = choices[k]?.key !== current;
  const go = (key: string) => onChange(key === current ? "" : key);
  const step = "month-picker__step shrink-0 rounded px-1.5 py-1 text-xs text-ink-muted disabled:opacity-30";
  return (
    <span className="month-picker flex shrink-0 items-center gap-0.5 rounded-full py-0.5 pl-2.5 pr-1" data-picked={picked}>
      <span className="mr-1 text-[11px] text-ink-muted">{tr("Month")}</span>
      <button
        type="button"
        className={step}
        disabled={k <= 0}
        onClick={() => go(choices[k - 1].key)}
        aria-label={tr("Previous {0}", monthWord)}
        title={tr("Previous {0}", monthWord)}
      >
        ‹
      </button>
      <select
        aria-label={tr("Month of the month cards")}
        value={choices[k]?.key ?? ""}
        onChange={(e) => go(e.target.value)}
        title={choices[k] ? `${fmtDayMonthYear(choices[k].start)} – ${fmtDayMonthYear(choices[k].end)}` : undefined}
        className="month-picker__select cursor-pointer appearance-none bg-transparent px-0.5 text-center text-xs font-medium"
      >
        {[...choices].reverse().map((m) => (
          <option key={m.key} value={m.key}>
            {m.key === current ? tr("This {0}", monthWord) : monthName(m.key)}
          </option>
        ))}
      </select>
      <button
        type="button"
        className={step}
        disabled={!picked}
        onClick={() => go(choices[k + 1].key)}
        aria-label={tr("Next {0}", monthWord)}
        title={tr("Next {0}", monthWord)}
      >
        ›
      </button>
      {picked && (
        <button
          type="button"
          className={step}
          onClick={() => go(current)}
          aria-label={tr("Back to this {0}", monthWord)}
          title={tr("Back to this {0}", monthWord)}
        >
          ×
        </button>
      )}
    </span>
  );
}

/** The period stays visible; other filters are reachable within the same fixed bar. */
export function PeriodsBar({
  f,
  accounts,
  children,
  onClear,
  month,
}: {
  f: SpendingFilters;
  accounts: Account[];
  children: ReactNode;
  onClear?: () => void;
  /** Next to the periods: the month of the month cards (MonthPicker). */
  month?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const pointer = useRef<string | null>(null);
  const count =
    Number(Boolean(f.account)) + f.categories.length + f.counts.length + Number(f.direction !== "all") + Number(Boolean(f.search));
  const accountName = f.account.startsWith("bank:")
    ? tr("All {0} accounts", f.account.slice(5).toUpperCase())
    : (accounts.find((r) => String(r.id) === f.account)?.name ?? tr("Account"));
  const selection = [
    ...(f.timeline.period === "Custom"
      ? [
          {
            label: `${fmtDayMonthYear(f.timeline.window.from)} – ${fmtDayMonthYear(f.timeline.window.to)}`,
            away: () => f.fetchAway("period"),
          },
        ]
      : []),
    ...(f.account ? [{ label: accountName, away: () => f.fetchAway("account") }] : []),
    ...f.categories.map((c) => ({ label: c === "Onbekend" ? tr("Still to categorise") : c, away: () => f.fetchAway("category", c) })),
    ...f.counts.map((c) => ({ label: tr("Counts as: {0}", countsLabel(c)), away: () => f.fetchAway("counts", c) })),
    ...(f.direction !== "all"
      ? [{ label: f.direction === "in" ? tr("Received") : tr("Spending"), away: () => f.fetchAway("direction") }]
      : []),
    ...(f.search ? [{ label: tr("Search: {0}", f.search), away: () => f.fetchAway("search") }] : []),
  ];
  useEffect(() => {
    if (!open) return;
    const closeOutside = (e: PointerEvent) => {
      if (e.target instanceof Node && !bar.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  return (
    <div
      ref={bar}
      className="time-filterbar sticky top-[60px] z-20 min-w-0"
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") setOpen(true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") setOpen(false);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") pointer.current = null;
        if (e.key === "Escape") {
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <div className="flex min-w-0 items-center justify-between gap-3" style={{ borderBottom: "1px solid var(--rule)" }}>
        <div className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar py-2">
          <Tabs
            items={periodTabs(PERIODS)}
            value={f.timeline.period}
            onChange={f.timeline.choose}
            variant="quiet"
            ariaLabel={tr("Period of Spending")}
            className="shrink-0 whitespace-nowrap"
          />
          {month && (
            <>
              <span className="mx-1 h-5 shrink-0 border-l" style={{ borderColor: "var(--rule)" }} aria-hidden />
              {month}
            </>
          )}
          {selection.length > 0 && <span className="mx-1 h-5 shrink-0 border-l" style={{ borderColor: "var(--rule)" }} aria-hidden />}
          {selection.map((item, i) => (
            <button
              key={`${item.label}-${i}`}
              type="button"
              onClick={item.away}
              title={tr("Remove filter {0}", item.label)}
              aria-label={tr("Remove filter {0}", item.label)}
              className="time-filterbar__chip max-w-48 shrink-0 rounded-full border px-2.5 py-1 text-xs"
            >
              <span className="truncate">{item.label}</span>
              <span aria-hidden className="shrink-0">
                ×
              </span>
            </button>
          ))}
        </div>
        <button
          ref={button}
          type="button"
          aria-controls={panelId}
          aria-expanded={open}
          onPointerDown={(e) => {
            pointer.current = e.pointerType;
          }}
          onClick={() => setOpen((v) => (pointer.current === "mouse" ? true : !v))}
          className="time-filterbar__button shrink-0 rounded-md px-3 py-2 text-xs font-medium text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-2"
          data-open={open}
        >
          Filters{count > 0 ? ` · ${count}` : ""} <span aria-hidden>{open ? "▴" : "▾"}</span>
        </button>
      </div>
      <div
        id={panelId}
        inert={!open}
        data-open={open}
        className="time-filterbar__panel"
        role="region"
        aria-label={tr("Filters for Spending")}
      >
        <div className="mb-3 flex items-center justify-between gap-3 border-b pb-2" style={{ borderColor: "var(--rule)" }}>
          <span className="text-xs font-semibold uppercase tracking-wide">Filters</span>
          {f.active && (
            <button type="button" onClick={onClear ?? f.clear} className="text-xs text-ink-muted underline underline-offset-4">
              {tr("Clear filters")}
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

export default function FilterBlock({
  f,
  first,
  last,
  accounts,
  categories,
  lookup = false,
  periods = true,
}: {
  f: SpendingFilters;
  first: string;
  last: string;
  accounts: Account[];
  categories: Category[];
  /** Also direction and search term: for the transaction list. */
  lookup?: boolean;
  periods?: boolean;
}) {
  // The search field types locally and only writes to the address bar after a
  // short pause: a new URL on every keystroke makes the cursor jump.
  const [text, setText] = useState(f.search);
  useEffect(() => {
    setText(f.search);
  }, [f.search]);
  useEffect(() => {
    if (text === f.search) return;
    const t = setTimeout(() => f.setSearch(text), 250);
    return () => clearTimeout(t);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col">
      <TimelineControls timeline={f.timeline} first={first} last={last} showPeriods={periods} />
      {accounts.length > 1 && <AccountFilter accounts={accounts} value={f.account} onChange={f.setAccount} />}
      <CategoryFilter categories={categories} value={f.categories} onChange={f.setCategories} />
      {lookup && <CountsFilter value={f.counts} onChange={f.setCounts} />}
      {lookup && (
        <div className="flex flex-wrap items-end gap-3 pb-3">
          <Input
            label={tr("Search")}
            placeholder={tr("Name, description or category")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-w-[14rem]"
          />
          <Select label={tr("Direction")} value={f.direction} onChange={(e) => f.setDirection(e.target.value as Direction)}>
            <option value="all">{tr("In and out")}</option>
            <option value="out">{tr("Only out (spending)")}</option>
            <option value="in">{tr("Only in (received)")}</option>
          </Select>
        </div>
      )}
    </div>
  );
}

/**
 * The filters that apply now, as a row with a ✕ per filter. That way you see on
 * Transactions straight away why the list is what it is — certainly after
 * clicking through from Overview — and you remove one without losing the rest.
 */
export function ActiveFilters({ f, accounts }: { f: SpendingFilters; accounts: Account[] }) {
  const name = (id: string) => {
    if (id.startsWith("bank:")) return tr("all accounts of {0}", id.split(":")[1]?.toUpperCase() ?? "de bank");
    return accounts.find((r) => String(r.id) === id)?.name ?? tr("one account");
  };
  const chips: { label: string; away: () => void }[] = [];
  if (f.timeline.period !== DEFAULT_PERIOD) {
    chips.push({
      label:
        f.timeline.period === "Custom"
          ? `${fmtDayMonthYear(f.timeline.window.from)} – ${fmtDayMonthYear(f.timeline.window.to)}`
          : tr("period {0}", f.timeline.period),
      away: () => f.fetchAway("period"),
    });
  }
  if (f.account) chips.push({ label: name(f.account), away: () => f.fetchAway("account") });
  f.categories.forEach((c) =>
    chips.push({ label: c === "Onbekend" ? tr("still to categorise") : c, away: () => f.fetchAway("category", c) }),
  );
  f.counts.forEach((c) => chips.push({ label: tr("Counts as: {0}", countsLabel(c)), away: () => f.fetchAway("counts", c) }));
  if (f.direction !== "all")
    chips.push({ label: f.direction === "in" ? tr("only in") : tr("only out"), away: () => f.fetchAway("direction") });
  if (f.search) chips.push({ label: `“${f.search}”`, away: () => f.fetchAway("search") });
  if (chips.length === 0 && !f.via) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-xs" style={{ background: "var(--surface-inset)" }}>
      {f.via === "overview" && (
        <Link href="/spending" className="mr-1 font-semibold underline underline-offset-4">
          {tr("← Back to Overview")}
        </Link>
      )}
      <span className="text-ink-muted">{f.via === "overview" ? tr("From Overview:") : tr("Filtered on:")}</span>
      {chips.map((c) => (
        <button
          key={c.label}
          type="button"
          onClick={c.away}
          aria-label={tr("Clear filter {0}", c.label)}
          className="rounded-full border px-2.5 py-1 transition-colors hover:bg-surface-2"
          style={{ borderColor: "var(--rule)", background: "var(--surface-card)" }}
        >
          {c.label}{" "}
          <span aria-hidden className="text-ink-muted">
            ✕
          </span>
        </button>
      ))}
      {chips.length > 1 && (
        <button type="button" onClick={f.clear} className="text-ink-muted underline underline-offset-4">
          {tr("Clear all")}
        </button>
      )}
    </div>
  );
}
