"use client";

// Managing fixed costs: what comes back every month, and what you think of it.
// The app recognises them from the pattern (fixed_costs.py); here you say where
// that is not right. The pub every month is not a fixed cost, an energy bill with
// a varying amount is. Your choice wins and applies everywhere: the budget mark,
// fixed versus variable, the lists on Overview. Lives under Categories: like a
// category it is a classification you set up. Per transaction you set it under
// Transactions.

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { Button, Section, Tag } from "@/components/ds";
import { dayNumber, isoDay } from "@/lib/timeline";
import { toTransactions } from "@/lib/spending-filters";
import { today } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";

type Last = {
  key: string;
  name: string;
  category: string | null;
  group_name: string | null;
  amount: number;
  count: number;
  months: number;
  first: string | null;
  last: string | null;
  is_new: boolean;
  stopped: boolean;
  manual?: boolean;
};
export type FixedCost = Last;
type Admin = { is_fixed: Last[]; candidates: Last[]; excluded: Last[] };

function Row({ v, button, busy, onChoose }: { v: Last; button: string; busy: boolean; onChoose: () => void }) {
  const yearAgo = isoDay(dayNumber(today()) - 365);
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-3 py-2 text-[12.5px]"
      style={{ borderTop: "1px solid var(--rule)", opacity: v.stopped && v.count > 0 ? 0.6 : 1 }}
    >
      <Link href={toTransactions({ search: v.name, start: yearAgo, end: today() })} className="flex min-w-0 flex-col hover:underline">
        <span className="flex flex-wrap items-center gap-2">
          {v.name}
          {v.manual && <Tag tone="neutral">{tr("added yourself")}</Tag>}
          {v.is_new && !v.stopped && <Tag tone="brand">{tr("new")}</Tag>}
          {v.stopped && v.count > 0 && <Tag tone="neutral">{tr("stopped?")}</Tag>}
        </span>
        {v.count > 0 && (
          <span className="text-xs text-ink-muted">
            {trx(
              "{0} · in {1} {2} · {3}×{4}",
              v.category ?? "Onbekend",
              v.months,
              v.months === 1 ? tr("month") : tr("months"),
              v.count,
              v.last ? tr(" · last {0}", fmtDayMonthYear(v.last)) : "",
            )}
          </span>
        )}
      </Link>
      <span className="flex items-center gap-3">
        {v.count > 0 && (
          <span className="num">
            {fmtEuro(v.amount)}
            <span className="text-ink-muted"> {tr("/mo")}</span>
          </span>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={onChoose}>
          {button}
        </Button>
      </span>
    </li>
  );
}

/**
 * A counterparty as a fixed cost (true), not (false) or back to the detection
 *  (null). Refreshes everything where fixed costs count.
 */
export function useChooseFixedCost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, is_fixed }: { name: string; is_fixed: boolean | null }) =>
      api.put<Admin>("/api/spending/fixed-costs/choice", { name, is_fixed }),
    onSuccess: (data) => {
      qc.setQueryData(["fixed-costs-admin"], data);
      qc.invalidateQueries({ queryKey: ["fixed-costs"] });
      qc.invalidateQueries({ queryKey: ["budget"] });
    },
  });
}

export default function FixedCostsAdmin() {
  const q = useQuery({ queryKey: ["fixed-costs-admin"], queryFn: () => api.get<Admin>("/api/spending/fixed-costs/manage") });
  const choose = useChooseFixedCost();

  const data = q.data;
  const running = (data?.is_fixed ?? []).filter((v) => !v.stopped);
  const perMonth = running.reduce((a, v) => a + v.amount, 0);
  const error = choose.isError ? (choose.error as ApiError).message : null;

  return (
    <div id="fixed-costs" className="flex scroll-mt-24 flex-col gap-8">
      <Section
        label={tr("Fixed costs")}
        meta={data ? <span className="num">{trx("{0} per month", fmtEuro(perMonth))}</span> : undefined}
        info={
          <>
            {tr(
              "Debits that come back every month. The app recognises them itself: in at least three months, roughly monthly, roughly the same amount. If that's wrong somewhere, say so here: what you choose wins over the recognition and counts everywhere: the marker in Budget this month, fixed versus variable and the lists on Overview. A choice applies to the name without numbers, so also to later months. You can also set it per transaction at Transactions.",
            )}
          </>
        }
      >
        {q.isLoading ? (
          <p className="text-sm text-ink-muted">{tr("Loading…")}</p>
        ) : q.isError ? (
          <p className="text-sm text-ink-muted">{tr("Fixed costs could not load. Refresh the page.")}</p>
        ) : data!.is_fixed.length === 0 ? (
          <p className="py-2 text-sm text-ink-muted">{tr("No fixed costs yet. Below you can mark them yourself.")}</p>
        ) : (
          <ul className="flex flex-col">
            {data!.is_fixed.map((v) => (
              <Row
                key={v.key}
                v={v}
                busy={choose.isPending}
                button={v.manual ? tr("Remove") : tr("Not a fixed cost")}
                onChoose={() => choose.mutate({ name: v.name, is_fixed: v.manual ? null : false })}
              />
            ))}
          </ul>
        )}
        {error && (
          <p className="pt-2 text-xs" style={{ color: "var(--text-loss)" }}>
            {error}
          </p>
        )}
      </Section>

      {data && data.candidates.length > 0 && (
        <Section
          label={tr("Maybe also fixed")}
          info={
            <>
              {tr(
                "Comes back in several months, but doesn't quite fit the pattern: a varying amount, another day, only two months so far. If it is a fixed cost after all, add it.",
              )}
            </>
          }
        >
          <ul className="flex flex-col">
            {data.candidates.map((v) => (
              <Row
                key={v.key}
                v={v}
                busy={choose.isPending}
                button={tr("Is a fixed cost")}
                onChoose={() => choose.mutate({ name: v.name, is_fixed: true })}
              />
            ))}
          </ul>
        </Section>
      )}

      {data && data.excluded.length > 0 && (
        <Section
          label={tr("Not a fixed cost")}
          info={tr("What you turned off yourself. It counts as an ordinary expense, even if it comes back every month.")}
        >
          <ul className="flex flex-col">
            {data.excluded.map((v) => (
              <Row
                key={v.key}
                v={v}
                busy={choose.isPending}
                button={tr("Recognise after all")}
                onChoose={() => choose.mutate({ name: v.name, is_fixed: null })}
              />
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
