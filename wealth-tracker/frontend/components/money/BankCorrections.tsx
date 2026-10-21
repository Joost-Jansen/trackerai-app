"use client";

// The balance corrections in Bank & cash per account: what the balances did that
// the transactions on those accounts don't explain. Opened from the month detail
// on Net worth; the arithmetic is net_worth.bank_corrections in the backend.

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtEuro, fmtDayMonth } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { tr, trx } from "@/lib/i18n";

type Event = {
  date: string;
  kind: "start" | "transfer" | "measurement" | "line" | "derived";
  source: string;
  balance: number;
  amount: number;
};
type Row = {
  account_id: number;
  account: string;
  kind: string;
  start_balance: number;
  end_balance: number;
  transactions: number;
  correction: number;
  events: Event[];
};
type Corrections = { start: string; end: string; total: number; accounts: Row[] };

const cents = (v: number) => Math.round(v * 100) / 100 || 0;
const SIGNED = (v: number) => `${cents(v) > 0 ? "+" : ""}${trueMinus(fmtEuro(cents(v)))}`;

function what(e: Event): string {
  switch (e.kind) {
    case "start":
      return tr("first data of this account (before it, it counts as zero)");
    case "transfer":
      return tr("a transfer from your other accounts");
    case "measurement":
      return e.source === "manual" ? tr("a balance entered by hand") : tr("a balance from the bank");
    case "line":
      return tr("the line between two balances entered by hand");
    default:
      return tr("a step the transactions don't explain");
  }
}

export default function BankCorrections({ start, end }: { start: string; end: string }) {
  const q = useQuery({
    queryKey: ["net-worth-corrections", start, end],
    queryFn: () => api.get<Corrections>(`/api/net-worth/corrections?start=${start}&end=${end}`),
  });
  if (q.isLoading) return <p className="py-1 pl-3 text-xs text-ink-muted">{tr("Loading…")}</p>;
  if (q.isError || !q.data) return <p className="py-1 pl-3 text-xs text-ink-muted">{tr("Could not load the corrections.")}</p>;
  if (q.data.accounts.length === 0)
    return <p className="py-1 pl-3 text-xs text-ink-muted">{tr("No account has a correction in this month.")}</p>;
  return (
    <div className="mb-1 ml-3 border-l pl-3 text-xs" style={{ borderColor: "var(--rule)" }}>
      {q.data.accounts.map((a) => (
        <div key={a.account_id} className="py-1">
          <div className="flex items-baseline justify-between gap-4">
            <span className="font-medium">{a.account}</span>
            <span className="num shrink-0 whitespace-nowrap">{SIGNED(a.correction)}</span>
          </div>
          <div className="num text-ink-muted">
            {trx(
              "{0} → {1} · own transactions {2}",
              trueMinus(fmtEuro(a.start_balance)),
              trueMinus(fmtEuro(a.end_balance)),
              SIGNED(a.transactions),
            )}
          </div>
          {a.events.map((e) => (
            <div key={`${e.kind}-${e.date}`} className="flex items-baseline justify-between gap-4 text-ink-muted">
              <span>
                <span className="num">{fmtDayMonth(e.date)}</span>
                {" · "}
                {what(e)}
                {e.kind !== "transfer" && <> {trx("(balance {0})", trueMinus(fmtEuro(e.balance)))}</>}
              </span>
              <span className="num shrink-0 whitespace-nowrap">{SIGNED(e.amount)}</span>
            </div>
          ))}
        </div>
      ))}
      <p className="pt-1 text-ink-muted">
        {tr("Change or delete a wrong balance (wrong date, wrong amount, a double) on")}{" "}
        <Link href="/accounts" className="underline underline-offset-4 hover:text-ink">
          {tr("Accounts")}
        </Link>
        .
      </p>
    </div>
  );
}
