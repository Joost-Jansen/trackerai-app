"use client";

// The single transactions behind one counterparty: date, account, description and
// amount. Label them one by one, or tick a few and label those together — needed
// for a payment processor, where every payment is a different shop.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Checkbox, Select } from "@/components/ds";
import { CategoryOptions } from "@/components/money/TransactionActions";
import { showAmount, type Category, type Account, type Transaction } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";

export default function SingleTransactions({ ids, categories, onDone }: {
  ids: number[]; categories: Category[]; onDone: () => void;
}) {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState("");
  const transactions = useQuery({
    queryKey: ["bank_transactions", "overview"],
    queryFn: () => api.get<{ transactions: Transaction[] }>("/api/bank-transactions"),
  });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<{ accounts: Account[] }>("/api/accounts") });
  const nameOf = new Map((accounts.data?.accounts ?? []).map((r) => [r.id, r.name]));
  const labelling = useMutation({
    mutationFn: ({ ids: chosenIds, category }: { ids: number[]; category: string }) =>
      api.put("/api/bank-transactions/category", { ids: chosenIds, category }),
    onSuccess: () => {
      setChosen(new Set());
      qc.invalidateQueries();
      onDone();
    },
  });

  if (transactions.isLoading) return <p className="py-2 text-xs text-ink-muted">{tr("Loading…")}</p>;
  const belongs = new Set(ids);
  const separate = (transactions.data?.transactions ?? [])
    .filter((t) => belongs.has(t.id))
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  const selection = separate.filter((t) => chosen.has(t.id));
  const summed = selection.reduce((s, t) => s + showAmount(t.amount), 0);
  const toggle = (items: number[], on: boolean) =>
    setChosen((old) => {
      const next = new Set(old);
      for (const id of items) (on ? next.add(id) : next.delete(id));
      return next;
    });

  return (
    <div className="mt-2 flex flex-col gap-2 rounded p-3" style={{ background: "var(--surface-inset)" }}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <span className="text-xs text-ink-muted">
          {selection.length > 0
            ? <>{trx("{0} chosen · together {1}", <b className="num">{selection.length}</b>, <span className="num">{trueMinus(fmtEuro(summed))}</span>)}</>
            : tr("Tick what belongs together, or choose a category per row.")}
        </span>
        <span className="flex flex-wrap items-end gap-2">
          <Select aria-label={tr("Category for the chosen transactions")} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{tr("Choose a category…")}</option>
            <CategoryOptions categories={categories} />
          </Select>
          <Button size="sm" variant="secondary" disabled={!target || selection.length === 0 || labelling.isPending}
            onClick={() => labelling.mutate({ ids: selection.map((t) => t.id), category: target })}>
            {selection.length > 0 ? tr("Label {0}", selection.length) : tr("Label")}
          </Button>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[12px]">
          <thead>
            <tr className="text-left text-ink-muted">
              <th className="w-8 py-1">
                <Checkbox checked={separate.length > 0 && selection.length === separate.length}
                  aria-label={tr("Choose all")} onChange={(on) => toggle(separate.map((t) => t.id), on)} />
              </th>
              <th className="py-1 font-normal">{tr("Date")}</th>
              <th className="py-1 font-normal">{tr("Account")}</th>
              <th className="py-1 font-normal">{tr("Description")}</th>
              <th className="py-1 text-right font-normal">{tr("Amount")}</th>
              <th className="py-1 pl-3 font-normal">{tr("Category")}</th>
            </tr>
          </thead>
          <tbody>
            {separate.map((t) => {
              const amount = showAmount(t.amount);
              return (
                <tr key={t.id} className="align-top" style={{ borderTop: "1px solid var(--rule)" }}>
                  <td className="py-1.5">
                    <Checkbox checked={chosen.has(t.id)} aria-label={tr("Choose {0}", t.date)} onChange={(on) => toggle([t.id], on)} />
                  </td>
                  <td className="num whitespace-nowrap py-1.5 text-ink-muted">{fmtDayMonthYear(t.date)}</td>
                  <td className="py-1.5 text-ink-muted">{nameOf.get(t.account_id) ?? "–"}</td>
                  <td className="max-w-[28rem] break-words py-1.5">{t.description || <span className="text-ink-muted">–</span>}</td>
                  <td className="num whitespace-nowrap py-1.5 text-right" style={amount > 0 ? { color: "var(--text-gain)" } : undefined}>
                    {trueMinus(fmtEuro(amount))}
                  </td>
                  <td className="py-1.5 pl-3">
                    <Select aria-label={tr("Category for {0}", t.date)} value="" disabled={labelling.isPending}
                      onChange={(e) => e.target.value && labelling.mutate({ ids: [t.id], category: e.target.value })}>
                      <option value="">{tr("Choose…")}</option>
                      <CategoryOptions categories={categories} />
                    </Select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {labelling.isError && <p className="text-xs" style={{ color: "var(--text-loss)" }}>{(labelling.error as ApiError).message}</p>}
    </div>
  );
}
