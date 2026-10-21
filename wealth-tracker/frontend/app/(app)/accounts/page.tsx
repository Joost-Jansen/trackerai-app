"use client";

// Accounts — all money that is not a security.
//
// The portfolio knows what your holdings are worth. What is on your current
// account, on your savings account or in cash in a drawer, it does not know — and
// without that last part "net worth" is just "investments".
//
// Two things this screen deliberately shows prominently:
//
//   * **A balance has a date.** You look at your account now and then, and in
//     between you do not know. "€1,000, measured on 31 January" is a more honest
//     answer than "€1,000", certainly if you have not looked for half a year.
//     That is why the date is always next to the amount.
//   * **Unknown is not zero.** An account without a measurement does not count in
//     the total and shows a dash, not €0.00. Zero would say it is empty.
//
// Importing happens in the Update panel (components/UpdateSheet.tsx), next to the
// DeGiro files: everything that brings data in is in one place. Here is what came
// in, and what you enter by hand.

import { accountGroups } from "@/lib/account-groups";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonth, fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Input, Section, Select, Tag } from "@/components/ds";
import DeviationRule, { type Deviation } from "@/components/money/DeviationRule";
import { EmptyState } from "@/components/ds";
import { KINDS, readAmount, showIban, today, type Account, type Balance, type Kind, type Stack } from "@/lib/money";
import { intlLocale, tr, trx } from "@/lib/i18n";

type List = { accounts: Account[] };
type BalanceCheck = {
  without_balance?: string[];
  deviating_balances?: Deviation[];
  /** In the last balance, not yet in the transactions: a payment that is pending. */
  pending_in_last?: { account: string; account_id: number; date: string; amount: number; direction: "debits" | "credits" }[];
};

// The stacks on which an account counts in your net worth, in the order of the
// net worth page. One sum over everything would mix up bank, investments and
// debt: with a student debt included, out comes a number that is neither a
// balance nor a net worth.
const STACKS: { stack: Stack; label: string }[] = [
  { stack: "bank", label: tr("Bank & cash") },
  { stack: "investments", label: tr("Investments outside the portfolio") },
  { stack: "debt", label: tr("Debt") },
];

function BalanceRule({ account, onDone }: { account: Account; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(today());
  const [balance, setBalance] = useState("");

  const set = useMutation({
    mutationFn: () => {
      const amount = readAmount(balance);
      if (amount === null) {
        return Promise.reject(new ApiError(400, tr("That is not an amount. For example: 2.000 or 1.234,56")));
      }
      return api.put(`/api/accounts/${account.id}/balance`, { date, balance: amount });
    },
    onSuccess: () => {
      setOpen(false);
      setBalance("");
      onDone();
    },
  });

  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        {tr("Update balance")}
      </Button>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        set.mutate();
      }}
    >
      <Input label={tr("Date")} type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required />
      <Input
        label={tr("Balance")}
        inputMode="decimal"
        placeholder="2.000,00"
        value={balance}
        onChange={(e) => setBalance(e.target.value)}
        required
        error={set.isError ? (set.error as ApiError).message : undefined}
      />
      <Button type="submit" variant="primary" size="sm" disabled={set.isPending}>
        {tr("Save")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {tr("Cancel")}
      </Button>
    </form>
  );
}

/**
 * The measurements of one account, newest first. Correcting is a new measurement
 * on the same date; deleting is for a measurement that should never have been
 * there. A measurement from an import (DeGiro cash) comes back with the next
 * import, and that is stated.
 */
function Measurements({ account, onDone }: { account: Account; onDone: () => void }) {
  const qc = useQueryClient();
  const balances = useQuery({
    queryKey: ["balances", account.id],
    queryFn: () => api.get<{ balances: Balance[]; calculated?: Balance[] }>(`/api/accounts/${account.id}/balances`),
  });
  const away = useMutation({
    mutationFn: (date: string) => api.del(`/api/accounts/${account.id}/balance/${date}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["balances", account.id] });
      onDone();
    },
  });

  if (balances.isLoading) return <p className="py-2 text-xs text-ink-muted">{tr("Loading…")}</p>;
  const own = balances.data?.balances ?? [];
  const calculated = balances.data?.calculated ?? [];
  // Newest first; a calculated month in between the measurements, on its date.
  const items = [...own, ...calculated].sort((a, b) => b.date.localeCompare(a.date));
  if (own.length === 0) {
    return (
      <p className="py-2 text-xs text-ink-muted">
        {tr("No measurements yet. Use “Update balance” to enter an amount with the date on which it was right.")}
      </p>
    );
  }
  return (
    <div className="rounded p-3" style={{ background: "var(--surface-inset)" }}>
      <p className="pb-2 text-xs text-ink-muted">
        {trx(
          "{0} {1}{2}. A new measurement on a date that already exists replaces it: that's how you fix a typo.",
          own.length,
          own.length === 1 ? tr("measurement") : tr("measurements"),
          calculated.length > 0 && (
            <>
              {trx(
                ", {0} {1} calculated with interest and repayment",
                calculated.length,
                calculated.length === 1 ? tr("month") : tr("months"),
              )}
            </>
          ),
        )}
      </p>
      <table className="w-full text-[12px]">
        <tbody>
          {items.map((m) => (
            <tr key={`${m.source}-${m.date}`} style={{ borderTop: "1px solid var(--rule)" }}>
              <td className="num py-1">{fmtDayMonthYear(m.date)}</td>
              <td className="num py-1 text-right">{trueMinus(fmtEuro(m.balance))}</td>
              <td className="py-1 pl-4 text-ink-muted">
                {m.source === "schedule" ? (
                  <>{trx("calculated: +{0} interest, −{1} repayment", fmtEuro(m.interest ?? 0), fmtEuro(m.repayment ?? 0))}</>
                ) : m.source === "sync" ? (
                  tr("from an import")
                ) : (
                  tr("by hand")
                )}
              </td>
              <td className="py-1 text-right">
                {m.source !== "schedule" && (
                  <Button size="sm" variant="ghost" disabled={away.isPending} onClick={() => away.mutate(m.date)}>
                    {tr("Delete")}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Interest and required repayment of a debt. At every reference point the app
 * calculates a month on from the last balance; a balance of your own always
 * wins, so an extra repayment is simply entering a new balance.
 */
function DebtScheduleForm({ account, onDone }: { account: Account; onDone: () => void }) {
  const ifText = (n: number | undefined) => (n === undefined ? "" : String(n).replace(".", ","));
  const [interest, setInterest] = useState(ifText(account.schedule?.interest));
  const [repayment, setRepayment] = useState(ifText(account.schedule?.repayment));
  const [from_date, setFrom] = useState(account.schedule?.from_date ?? today());

  const store = useMutation({
    mutationFn: (discard: boolean) => {
      if (discard) return api.put(`/api/accounts/${account.id}/schedule`, { interest: null, repayment: null });
      // A percentage has no thousands: "2,56" and "2.56" are both 2.56.
      const r = interest.trim() ? Number(interest.trim().replace(",", ".")) : 0;
      const a = repayment.trim() ? readAmount(repayment) : 0;
      if (Number.isNaN(r) || a === null) {
        return Promise.reject(new ApiError(400, tr("Enter the interest as 2,56 and the repayment as 120,00.")));
      }
      return api.put(`/api/accounts/${account.id}/schedule`, { interest: r, repayment: a, from_date });
    },
    onSuccess: onDone,
  });

  return (
    <div className="rounded p-3" style={{ background: "var(--surface-inset)" }}>
      <p className="pb-2 text-xs text-ink-muted">
        {tr(
          "On each reference day, the 1st or the day your salary comes in, a month of interest is added (yearly interest divided by twelve) and the required repayment is taken off, calculated from your last balance. If you repay extra once, enter the new balance with “Update balance”: the app calculates on from there.",
        )}
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          store.mutate(false);
        }}
      >
        <Input
          label={tr("Interest per year (%)")}
          inputMode="decimal"
          placeholder="2,56"
          value={interest}
          onChange={(e) => setInterest(e.target.value)}
        />
        <Input
          label={tr("Required repayment per month")}
          inputMode="decimal"
          placeholder="120,00"
          value={repayment}
          onChange={(e) => setRepayment(e.target.value)}
          error={store.isError ? (store.error as ApiError).message : undefined}
        />
        <Input label={tr("From")} type="date" value={from_date} onChange={(e) => setFrom(e.target.value)} required />
        <Button type="submit" variant="primary" size="sm" disabled={store.isPending}>
          {tr("Save")}
        </Button>
        {account.schedule && (
          <Button type="button" size="sm" variant="ghost" disabled={store.isPending} onClick={() => store.mutate(true)}>
            {tr("Remove")}
          </Button>
        )}
      </form>
    </div>
  );
}

function NewAccount({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("cash");
  const [iban, setIban] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post("/api/accounts", {
        kind,
        // A manual account has no provider; a bank account you add yourself only gets
        // one once an export belongs to it.
        provider: "manual",
        name,
        iban: iban.trim() || null,
      }),
    onSuccess: () => {
      setOpen(false);
      setName("");
      setIban("");
      onDone();
    },
  });

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {tr("Add account")}
      </Button>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Input
        label={tr("Name")}
        placeholder={tr("e.g. Bunq, Coinbase, Cash")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
      />
      <Select label={tr("Kind")} value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
        {KINDS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </Select>
      <Input
        label="IBAN"
        hint={tr("Leave empty for cash")}
        placeholder="NL00BANK0000000000"
        value={iban}
        onChange={(e) => setIban(e.target.value)}
        error={create.isError ? (create.error as ApiError).message : undefined}
      />
      <Button type="submit" variant="primary" disabled={create.isPending}>
        {tr("Add")}
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        {tr("Cancel")}
      </Button>
    </form>
  );
}

export default function AccountsPage() {
  const [expandedBanks, setExpandedBanks] = useState<string[]>([]);
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState<number | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["balances"] });
    qc.invalidateQueries({ queryKey: ["net_worth"] });
    qc.invalidateQueries({ queryKey: ["accounts-total"] });
    qc.invalidateQueries({ queryKey: ["bank_transactions"] });
  };

  const items = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<List>("/api/accounts"),
  });
  const check = useQuery({
    queryKey: ["net_worth"],
    queryFn: () => api.get<BalanceCheck>("/api/net-worth"),
  });

  const removal = useMutation({
    mutationFn: (id: number) => api.del(`/api/accounts/${id}`),
    onSuccess: refresh,
  });

  if (items.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (items.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("Accounts could not load. Try again.")}
      </p>
    );
  }

  const accounts = items.data?.accounts ?? [];
  const deviations = check.data?.deviating_balances ?? [];
  const missing = check.data?.without_balance ?? [];
  const pending = check.data?.pending_in_last ?? [];
  const openAccount = (name: string) => {
    const account = accounts.find((r) => r.name === name);
    if (!account) return;
    const bank = accountGroups(accounts.filter((r) => r.stack === account.stack)).find((group_name) =>
      group_name.accounts.some((r) => r.id === account.id),
    );
    if (bank && bank.accounts.length > 1) setExpandedBanks((old) => (old.includes(bank.id) ? old : [...old, bank.id]));
    setOpen(account.id);
    window.setTimeout(() => document.getElementById(`rekening-${account.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
  };

  // Per stack, with a subtotal of what was measured. Closed accounts and accounts
  // without a measurement are listed but do not count.
  const grouped = STACKS.map((s) => {
    const items = accounts.filter((r) => r.stack === s.stack);
    const subtotaal = items.filter((r) => r.active && r.balance !== null).reduce((summed, r) => summed + (r.balance ?? 0), 0);
    return { ...s, items, subtotaal };
  }).filter((g) => g.items.length > 0);

  return (
    <div className="flex flex-col gap-8">
      {(deviations.length > 0 || missing.length > 0 || pending.length > 0) && (
        <Section
          label="Gegevenscontrole"
          className="scroll-mt-24"
          info={tr("Here you fix balance problems that can distort the net worth chart.")}
        >
          <div
            id="data-check"
            className="rounded-md border p-4 text-sm"
            style={{
              borderColor: deviations.length > 0 || missing.length > 0 ? "var(--text-loss)" : "var(--rule)",
              background: "var(--surface-inset)",
            }}
          >
            {pending.map((o) => (
              <p key={o.account_id} className="mb-3 max-w-[80ch]">
                {trx(
                  "{0} your latest balance ({1}) includes {2} of {3} that haven't come in as transactions yet: a payment on its way. It comes in by itself once it is booked. Until then every earlier balance differs by exactly that amount; that is already accounted for below, you don't need to do anything.",
                  <strong>{o.account}:</strong>,
                  fmtDayMonthYear(o.date),
                  <span className="num">{fmtEuro(o.amount)}</span>,
                  o.direction === "debits" ? tr("debits") : tr("credits"),
                )}
              </p>
            ))}
            {deviations.length > 0 && (
              <>
                <p className="font-semibold" style={{ color: "var(--text-loss)" }}>
                  {trx(
                    "{0} with your transactions",
                    deviations.length === 1 ? tr("One balance doesn't match") : tr("{0} balances don't match", deviations.length),
                  )}
                </p>
                <p className="mt-1 max-w-[80ch] text-ink-muted">
                  {tr(
                    "The app calculates your balance back from the latest balance you have, with everything that came in and went out since. An earlier balance should come out exactly on that. Below, per balance, is the likely cause, with the button that fixes it. Your net worth always follows your latest balance; a difference here usually points to payments still on their way, a wrong date, or missing transactions.",
                  )}
                </p>
                <ul className="mt-2">
                  {deviations.map((a) => (
                    <DeviationRule key={`${a.account_id}-${a.date}`} a={a} onDone={refresh} onOpen={() => openAccount(a.account)} />
                  ))}
                </ul>
              </>
            )}
            {missing.length > 0 && (
              <p className="mt-3 text-ink-muted">
                {trx(
                  "{0} {1}. Enter one current balance; the app calculates back with the transactions it has.",
                  <strong>{tr("Without a balance:")}</strong>,
                  missing.join(", "),
                )}
              </p>
            )}
          </div>
        </Section>
      )}
      <Section
        label={tr("Accounts")}
        meta={<span className="num">{trx("{0} accounts", accounts.length)}</span>}
        info={
          <>
            {tr(
              "Grouped as they count in your net worth. Your DeGiro portfolio isn't here: it counts via the Portfolio tab. The cash balance at DeGiro is here: it comes from the account statement you upload via Update. You upload bank exports there too, including your savings accounts and their balance overview. An account without a measurement doesn't count in the subtotal: unknown is not empty.",
            )}
          </>
        }
      >
        {accounts.length === 0 ? (
          <EmptyState title={tr("No accounts yet")} body={tr("Import a bank export via Update, top right, or add an account by hand.")} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-[12.5px]">
              <thead>
                <tr className="text-left text-ink-muted">
                  <th className="py-1.5 font-normal">{tr("Account")}</th>
                  <th className="py-1.5 font-normal">IBAN</th>
                  <th className="py-1.5 text-right font-normal">{tr("Balance")}</th>
                  <th className="py-1.5 pl-4 font-normal">{tr("Measured")}</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {grouped.flatMap((group_name) => [
                  <tr key={`kop-${group_name.stack}`}>
                    <td colSpan={2} className="pb-1 pt-4 text-xs uppercase tracking-wide text-ink-muted">
                      {group_name.label}
                    </td>
                    <td className="num pb-1 pt-4 text-right text-xs font-semibold">{trueMinus(fmtEuro(group_name.subtotaal))}</td>
                    <td colSpan={2} />
                  </tr>,
                  ...accountGroups(group_name.items).flatMap((bank) => [
                    ...(bank.accounts.length > 1
                      ? [
                          <tr key={`bank-${bank.id}`} style={{ borderTop: "1px solid var(--rule)" }}>
                            <td colSpan={2} className="py-3">
                              <button
                                type="button"
                                className="text-left font-semibold"
                                aria-expanded={expandedBanks.includes(bank.id)}
                                onClick={() =>
                                  setExpandedBanks((old) =>
                                    old.includes(bank.id) ? old.filter((id) => id !== bank.id) : [...old, bank.id],
                                  )
                                }
                              >
                                {expandedBanks.includes(bank.id) ? "▾" : "▸"} {bank.name}
                                <span className="ml-2 text-xs font-normal text-ink-muted">{trx("{0} accounts", bank.accounts.length)}</span>
                              </button>
                              <p className="text-xs text-ink-muted">{tr("Latest known balances; measurement dates may differ.")}</p>
                            </td>
                            <td className="num text-right font-semibold">
                              {bank.accounts.some((r) => r.active && r.balance !== null)
                                ? new Intl.NumberFormat(intlLocale, { style: "currency", currency: bank.accounts[0].currency }).format(
                                    bank.accounts.filter((r) => r.active).reduce((sum, r) => sum + (r.balance ?? 0), 0),
                                  )
                                : "–"}
                            </td>
                            <td colSpan={2} className="pl-4 text-xs text-ink-muted">
                              {bank.accounts.filter((r) => r.active && r.balance === null).length > 0
                                ? tr("Incomplete: balance missing")
                                : ""}
                            </td>
                          </tr>,
                        ]
                      : []),
                    ...(bank.accounts.length === 1 || expandedBanks.includes(bank.id) ? bank.accounts : []).flatMap((r) => [
                      <tr
                        key={r.id}
                        id={`account-${r.id}`}
                        className="scroll-mt-32 align-top"
                        style={{ borderTop: "1px solid var(--rule)" }}
                      >
                        <td className="py-2">
                          <span className="flex items-center gap-2">
                            {r.name}
                            {!r.active && <Tag tone="neutral">{tr("closed")}</Tag>}
                          </span>
                          <span className="text-xs text-ink-muted">{r.kind}</span>
                          {r.schedule && (
                            <span className="block text-xs text-ink-muted">
                              {trx(
                                "{0}% interest · {1} repayment per month",
                                String(r.schedule.interest).replace(".", ","),
                                fmtEuro(r.schedule.repayment),
                              )}
                            </span>
                          )}
                        </td>
                        <td className="num py-2 text-ink-muted">{showIban(r.iban)}</td>
                        <td className="num py-2 text-right">
                          {/* A dash and not €0,00: unknown is not empty. */}
                          {r.balance === null ? <span className="text-ink-muted">–</span> : trueMinus(fmtEuro(r.balance))}
                          {r.since_period_start !== null && r.since_period_start !== 0 && (
                            <span
                              className="block text-xs"
                              style={{ color: r.since_period_start > 0 ? "var(--text-gain)" : "var(--text-loss)" }}
                              title={tr("Change since the start of this month")}
                            >
                              {trx(
                                "{0}{1} since {2}",
                                r.since_period_start > 0 ? "+" : "",
                                trueMinus(fmtEuro(r.since_period_start)),
                                fmtDayMonth(r.period_start),
                              )}
                            </span>
                          )}
                        </td>
                        <td className="num py-2 pl-4 text-ink-muted">
                          {r.balance_date ?? "–"}
                          {r.balance_source === "schedule" && <span className="block text-xs">{tr("calculated")}</span>}
                          {r.balance_source === "transfer" && (
                            <span
                              className="block text-xs"
                              title={tr(
                                "Updated with the transfers your other accounts made with it, since the last export or the last balance",
                              )}
                            >
                              {tr("via transfers")}
                            </span>
                          )}
                        </td>
                        <td className="py-2">
                          <div className="flex flex-col items-end gap-1">
                            <Button size="sm" variant="ghost" onClick={() => setOpen(open === r.id ? null : r.id)}>
                              {open === r.id ? tr("Hide measurements") : tr("Measurements")}
                            </Button>
                            <BalanceRule account={r} onDone={refresh} />
                            {r.kind === "debt" && (
                              <Button size="sm" variant="ghost" onClick={() => setScheduleOpen(scheduleOpen === r.id ? null : r.id)}>
                                {scheduleOpen === r.id ? tr("Close") : tr("Interest & repayment")}
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                if (window.confirm(tr('Delete "{0}"? The transactions and balances of this account go with it.', r.name))) {
                                  removal.mutate(r.id);
                                }
                              }}
                            >
                              {tr("Delete")}
                            </Button>
                          </div>
                        </td>
                      </tr>,
                      open === r.id && (
                        <tr key={`metingen-${r.id}`}>
                          <td colSpan={5} className="pb-3">
                            <Measurements account={r} onDone={refresh} />
                          </td>
                        </tr>
                      ),
                      scheduleOpen === r.id && (
                        <tr key={`schedule-${r.id}`}>
                          <td colSpan={5} className="pb-3">
                            <DebtScheduleForm
                              key={JSON.stringify(r.schedule)}
                              account={r}
                              onDone={() => {
                                setScheduleOpen(null);
                                refresh();
                              }}
                            />
                          </td>
                        </tr>
                      ),
                    ]),
                  ]),
                ])}
              </tbody>
            </table>
          </div>
        )}

        <div className="pt-4">
          <NewAccount onDone={refresh} />
        </div>
      </Section>
    </div>
  );
}
