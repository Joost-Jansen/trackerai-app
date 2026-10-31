"use client";

// Broker accounts: their cash, entering a movement by hand, and what is on them.
//
// For a broker without an export the app reads (or before the first export),
// e.g. a Trade Republic savings plan: a buy with a fractional number of units,
// the monthly deposit, interest, a dividend. Everything entered here counts in
// the portfolio (positions, returns, allocation) and the broker's cash counts in
// net worth, exactly as an import does. Importing Trade Republic's CSV is in the
// Update panel, next to DeGiro's files.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  KIND_ORDER,
  kindLabel,
  needsIsin,
  readQuantity,
  type BrokerAccount,
  type BrokerKind,
  type BrokersOverview,
  type LedgerEntry,
} from "@/lib/brokers";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { readAmount, today } from "@/lib/money";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Input, Section, Select } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";

function NewBrokerAccount({ overview, onDone }: { overview: BrokersOverview; onDone: () => void }) {
  const missing = overview.brokers.filter((b) => !overview.accounts.some((a) => a.broker === b.code));
  const [broker, setBroker] = useState(missing.find((b) => b.code !== "degiro")?.code ?? missing[0]?.code ?? "");
  const create = useMutation({
    mutationFn: () => api.post("/api/brokers/accounts", { broker }),
    onSuccess: onDone,
  });
  if (missing.length === 0) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Select
        label={tr("Broker")}
        value={broker}
        onChange={(e) => setBroker(e.target.value)}
        error={create.isError ? (create.error as ApiError).message : undefined}
      >
        {missing.map((b) => (
          <option key={b.code} value={b.code}>
            {b.label}
          </option>
        ))}
      </Select>
      <Button type="submit" variant="secondary" disabled={create.isPending || !broker}>
        {tr("Add broker account")}
      </Button>
    </form>
  );
}

function NewMovement({ account, onDone }: { account: BrokerAccount; onDone: () => void }) {
  const [kind, setKind] = useState<BrokerKind>("buy");
  const [date, setDate] = useState(today());
  const [isin, setIsin] = useState("");
  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [fee, setFee] = useState("");
  const [tax, setTax] = useState("");
  const [description, setDescription] = useState("");
  const trade = kind === "buy" || kind === "sell";

  const save = useMutation({
    mutationFn: () => {
      const optional = (text: string) => (text.trim() ? readAmount(text) : undefined);
      const body: Record<string, unknown> = { account_id: account.id, kind, date };
      if (needsIsin(kind)) {
        body.isin = isin.trim().toUpperCase();
        if (name.trim()) body.name = name.trim();
      }
      if (trade) {
        const units = readQuantity(quantity);
        if (units === null) return Promise.reject(new ApiError(400, tr("Enter the quantity as 2,8901: fractions are fine.")));
        body.quantity = units;
        if (price.trim()) body.price = readAmount(price);
      }
      if (!trade || !price.trim()) body.amount = optional(amount);
      const numbers = [body.price, body.amount, optional(fee), optional(tax)];
      if (numbers.some((n) => n === null)) {
        return Promise.reject(new ApiError(400, tr("That is not an amount. For example: 2.000 or 1.234,56")));
      }
      if (fee.trim()) body.fee = optional(fee);
      if (tax.trim()) body.tax = optional(tax);
      if (!needsIsin(kind) && description.trim()) body.description = description.trim();
      return api.post("/api/brokers/transactions", body);
    },
    onSuccess: () => {
      setQuantity("");
      setPrice("");
      setAmount("");
      setFee("");
      setTax("");
      setDescription("");
      onDone();
    },
  });

  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded p-3"
      style={{ background: "var(--surface-inset)" }}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Select label={tr("Kind")} value={kind} onChange={(e) => setKind(e.target.value as BrokerKind)}>
        {KIND_ORDER.map((k) => (
          <option key={k} value={k}>
            {kindLabel(k)}
          </option>
        ))}
      </Select>
      <Input label={tr("Date")} type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required />
      {needsIsin(kind) && (
        <>
          <Input label="ISIN" placeholder="IE00BK5BQT80" value={isin} onChange={(e) => setIsin(e.target.value)} required />
          <Input label={tr("Name")} hint={tr("Optional")} placeholder="VWCE" value={name} onChange={(e) => setName(e.target.value)} />
        </>
      )}
      {trade && (
        <>
          <Input
            label={tr("Quantity")}
            inputMode="decimal"
            placeholder="2,8901"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
          <Input
            label={tr("Price per unit")}
            hint={tr("Or leave empty and give the amount")}
            inputMode="decimal"
            placeholder="138,40"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </>
      )}
      <Input
        label={trade ? tr("Amount (without costs)") : kind === "dividend" ? tr("Gross amount") : tr("Amount")}
        inputMode="decimal"
        placeholder="400,00"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        required={!trade}
        disabled={trade && price.trim() !== ""}
      />
      {(trade || kind === "dividend") && (
        <Input label={tr("Costs")} inputMode="decimal" placeholder="1,00" value={fee} onChange={(e) => setFee(e.target.value)} />
      )}
      {(kind === "sell" || kind === "dividend") && (
        <Input label={tr("Tax withheld")} inputMode="decimal" placeholder="0,00" value={tax} onChange={(e) => setTax(e.target.value)} />
      )}
      {!needsIsin(kind) && (
        <Input label={tr("Description")} hint={tr("Optional")} value={description} onChange={(e) => setDescription(e.target.value)} />
      )}
      <Button type="submit" variant="primary" size="sm" disabled={save.isPending}>
        {tr("Save")}
      </Button>
      {save.isError && (
        <p className="w-full text-xs" style={{ color: "var(--text-loss)" }}>
          {(save.error as ApiError).message}
        </p>
      )}
    </form>
  );
}

function Ledger({ account, onDone }: { account: BrokerAccount; onDone: () => void }) {
  const ledger = useQuery({
    queryKey: ["broker-ledger", account.id],
    queryFn: () => api.get<{ entries: LedgerEntry[] }>(`/api/brokers/accounts/${account.id}/ledger`),
  });
  const remove = useMutation({
    mutationFn: (ref: { table: string; id: number }) => api.del(`/api/brokers/transactions/${ref.table}/${ref.id}`),
    onSuccess: onDone,
  });
  const entries = ledger.data?.entries ?? [];
  if (ledger.isLoading) return <p className="py-2 text-xs text-ink-muted">{tr("Loading…")}</p>;
  if (entries.length === 0) return <p className="py-2 text-xs text-ink-muted">{tr("Nothing on this account yet.")}</p>;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>{tr("Date")}</th>
            <th>{tr("Kind")}</th>
            <th>{tr("Description")}</th>
            <th className="num">{tr("Cash (€)")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td>{fmtDayMonthYear(e.date)}</td>
              <td>{kindLabel(e.kind)}</td>
              <td>{e.description ?? "–"}</td>
              <td className="num">{trueMinus(fmtEuro(e.amount))}</td>
              <td className="text-right">
                {e.ref ? (
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => e.ref && remove.mutate(e.ref)}>
                    {tr("Delete")}
                  </Button>
                ) : (
                  <span className="text-xs text-ink-muted">{tr("from an import")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BrokerAccounts() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState<number | null>(null);
  const [showing, setShowing] = useState<number | null>(null);
  const overview = useQuery({ queryKey: ["brokers"], queryFn: () => api.get<BrokersOverview>("/api/brokers") });
  // A movement changes positions, cash, net worth and every chart: refresh it all.
  const refresh = () => qc.invalidateQueries();

  if (!overview.data) return null;
  const accounts = overview.data.accounts;

  return (
    <Section
      label={tr("Broker accounts")}
      meta={<span className="num">{trx("{0} accounts", accounts.length)}</span>}
      info={tr(
        "The cash at each broker and what you entered there by hand. For a broker whose export the app doesn't read, such as a monthly savings plan: a buy (fractions are fine), a deposit, interest, a dividend, costs or tax. It counts in your positions, returns and allocation, and the cash in your net worth. Trade Republic's transaction export can also be uploaded via Update.",
      )}
    >
      {accounts.length === 0 && (
        <p className="mb-3 text-xs text-ink-muted">{tr("No broker accounts yet. Add one to enter its transactions by hand.")}</p>
      )}
      <ul className="flex flex-col gap-3">
        {accounts.map((a) => (
          <li key={a.id} className="row-rule pt-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span>
                <span className="font-medium">{a.name}</span>
                <span className="ml-2 text-xs text-ink-muted">{a.broker_label}</span>
              </span>
              <span className="num text-sm">
                {a.balance === null ? (
                  <span className="text-ink-muted">–</span>
                ) : (
                  <>
                    {trueMinus(fmtEuro(a.balance))}
                    <span className="ml-1 text-xs text-ink-muted">{trx("cash on {0}", fmtDayMonthYear(a.balance_date ?? ""))}</span>
                  </>
                )}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <Button size="sm" variant={adding === a.id ? "primary" : "ghost"} onClick={() => setAdding(adding === a.id ? null : a.id)}>
                {adding === a.id ? tr("Close") : tr("Add transaction")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowing(showing === a.id ? null : a.id)}>
                {showing === a.id ? tr("Hide movements") : tr("Movements")}
              </Button>
            </div>
            {adding === a.id && (
              <div className="mt-2">
                <NewMovement account={a} onDone={refresh} />
              </div>
            )}
            {showing === a.id && (
              <div className="mt-2">
                <Ledger account={a} onDone={refresh} />
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="pt-4">
        <NewBrokerAccount overview={overview.data} onDone={refresh} />
      </div>
    </Section>
  );
}
