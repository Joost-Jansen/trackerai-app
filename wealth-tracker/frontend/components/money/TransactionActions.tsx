"use client";

// What you can do with a transaction besides labelling itself: make a rule from
// it, and add a transaction that is in no export.

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Select } from "@/components/ds";
import {
  readAmount,
  RULE_PRIORITY_COUNTERPARTY,
  rulePattern,
  today,
  type Category,
  type RelabelReport,
  type Account,
  type Transaction,
} from "@/lib/money";
import { countsAs } from "@/components/money/CategoryColumns";
import { tr } from "@/lib/i18n";

/**
 * "And from now on everything from this shop like this." Makes a rule from this
 * transaction and then relabels the whole history.
 *
 * The pattern is the counterparty's name, literally, with the regex characters
 * taken out. Deliberately not smarter: a guessed pattern that is too broad
 * silently labels things you did not mean along with it.
 */
export function MakeRule({ transaction, category, onDone }: { transaction: Transaction; category: string; onDone: () => void }) {
  const pattern = useMemo(() => rulePattern(transaction.name), [transaction.name]);
  const create = useMutation({
    mutationFn: async () => {
      await api.post("/api/categories/rules", {
        priority: RULE_PRIORITY_COUNTERPARTY,
        field: "N",
        pattern,
        direction: "",
        category,
      });
      return api.post<RelabelReport>("/api/categories/relabel?everything=true");
    },
    onSuccess: onDone,
  });
  return (
    <Button
      size="sm"
      variant="ghost"
      disabled={create.isPending}
      title={tr('From now on everything from "{0}" as {1}', transaction.name, category)}
      onClick={() => create.mutate()}
    >
      {create.isPending ? tr("Working…") : tr("Make rule")}
    </Button>
  );
}

/** Categories as a select list, per group. */
export function CategoryOptions({ categories }: { categories: Category[] }) {
  const onGroup = categories.reduce<Record<string, Category[]>>((acc, c) => {
    (acc[c.group_name] ??= []).push(c);
    return acc;
  }, {});
  return (
    <>
      {Object.entries(onGroup).map(([group_name, items]) => (
        <optgroup key={group_name} label={group_name}>
          {items.map((c) => (
            <option key={c.id} value={c.name} title={tr("Counts as: {0}", countsAs(c))}>
              {c.name}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/**
 * An expense or income that is in no export: cash, a market, a refund that came
 * by nowhere else. The amount is always positive; whether it came in or went out
 * you choose separately.
 */
export function AddManually({ accounts, categories, onDone }: { accounts: Account[]; categories: Category[]; onDone: () => void }) {
  const [accountId, setAccountId] = useState<string>(accounts[0] ? String(accounts[0].id) : "");
  const [date, setDate] = useState(today());
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState<"expense" | "income">("expense");
  const [category, setCategory] = useState("");

  const adding = useMutation({
    mutationFn: () => {
      const value = readAmount(amount);
      if (value === null || value <= 0) {
        return Promise.reject(new ApiError(400, tr("Enter an amount greater than zero, for example 12,50.")));
      }
      return api.post("/api/bank-transactions", {
        account_id: Number(accountId),
        date,
        amount: value,
        direction,
        name,
        category: category || null,
      });
    },
    onSuccess: () => {
      setName("");
      setAmount("");
      setCategory("");
      onDone();
    },
  });

  if (accounts.length === 0) {
    return (
      <p className="py-2 text-sm text-ink-muted">
        {tr("A manual transaction belongs to an account. First add one at Accounts, for example “Cash”.")}
      </p>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        adding.mutate();
      }}
    >
      <Select label={tr("Account")} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
        {accounts.map((r) => (
          <option key={r.id} value={String(r.id)}>
            {r.name}
          </option>
        ))}
      </Select>
      <Input label={tr("Date")} type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required />
      <Input label={tr("Spent on")} placeholder={tr("e.g. Market")} value={name} onChange={(e) => setName(e.target.value)} required />
      <Select label={tr("Kind")} value={direction} onChange={(e) => setDirection(e.target.value as "expense" | "income")}>
        <option value="expense">{tr("Money out")}</option>
        <option value="income">{tr("Money in")}</option>
      </Select>
      <Input
        label={tr("Amount")}
        inputMode="decimal"
        placeholder="12,50"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        required
        error={adding.isError ? (adding.error as ApiError).message : undefined}
      />
      <Select label={tr("Category")} value={category} onChange={(e) => setCategory(e.target.value)}>
        <option value="">{tr("(the rules decide)")}</option>
        <CategoryOptions categories={categories} />
      </Select>
      <Button type="submit" variant="primary" disabled={adding.isPending}>
        {tr("Add")}
      </Button>
    </form>
  );
}
