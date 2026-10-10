"use client";

// One balance that does not match the transactions: what is going on, in plain
// words, and the button that fixes it. The cause comes from the backend
// (accounts.explain_deviation); this tells it and offers the matching fix as the
// first button. Lives in the Data check on Accounts.

import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonth, fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, ButtonLink } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";

/** Why a balance is probably not right; see accounts.explain_deviation. */
export type Explanation =
  | { kind: "pending"; end: string; count: number; summed: number; whole: boolean }
  | { kind: "other_day"; day: string; occupied: boolean }
  | { kind: "duplicate"; date: string; name: string; amount: number; count: number }
  | { kind: "missing"; direction: "credits" | "debits"; amount: number };

export type Deviation = {
  account: string;
  account_id: number;
  date: string;
  measured: number;
  calculated: number;
  source: "sync" | "manual";
  /** The last balance, from which the app calculates back. */
  anchor: string;
  explanation: Explanation;
};

export default function DeviationRule({ a, onDone, onOpen }: { a: Deviation; onDone: () => void; onOpen: () => void }) {
  const pad = `/api/accounts/${a.account_id}/balance`;
  const action = useMutation({
    mutationFn: (what: { kind: "calculated" } | { kind: "away" } | { kind: "move"; dest: string }) =>
      what.kind === "calculated" ? api.put(pad, { date: a.date, balance: a.calculated, source: a.source })
        : what.kind === "away" ? api.del(`${pad}/${a.date}`)
          : api.post(`${pad}/${a.date}/move`, { dest: what.dest }),
    onSuccess: onDone,
  });
  const busy = action.isPending;
  const fetched = a.source === "sync";
  const u = a.explanation;
  const away = (
    <Button size="sm" variant="ghost" disabled={busy} onClick={() => action.mutate({ kind: "away" })}>{tr("Delete this balance")}</Button>
  );
  const measurements = <Button size="sm" variant="ghost" onClick={onOpen}>{tr("All balances of this account")}</Button>;

  let cause: React.ReactNode;
  let buttons: React.ReactNode;
  if (u.kind === "pending") {
    const one = u.count === 1;
    cause = (
      <>
        {one
          ? u.whole ? tr("Probably 1 payment of {0} was still on the way.", fmtEuro(u.summed)) : tr("Probably, among others, 1 payment of {0} was still on the way.", fmtEuro(u.summed))
          : u.whole ? tr("Probably {0} payments totalling {1} were still on the way.", u.count, fmtEuro(u.summed)) : tr("Probably, among others, {0} payments totalling {1} were still on the way.", u.count, fmtEuro(u.summed))}{" "}
        {one
          ? tr("Your bank already took it off your balance, but only booked it on {0}, and only then does it appear in your transactions. The booked balance of {1} was {2}.", fmtDayMonth(u.end), fmtDayMonth(a.date), fmtEuro(a.calculated))
          : tr("Your bank already took them off your balance, but only booked them on {0}, and only then do they appear in your transactions. The booked balance of {1} was {2}.", fmtDayMonth(u.end), fmtDayMonth(a.date), fmtEuro(a.calculated))}
        {fetched && u.whole && <>{" "}{tr("The app now corrects a balance from the bank connection itself, as soon as those payments are in.")}</>}
      </>
    );
    buttons = (
      <>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => action.mutate({ kind: "calculated" })}>{trx("Set to {0}", fmtEuro(a.calculated))}</Button>
        {away}
      </>
    );
  } else if (u.kind === "other_day") {
    cause = (
      <>{trx("This amount is exactly right on {0}. Probably the balance was looked at that day, or entered on the wrong date.{1}", fmtDayMonth(u.day), u.occupied && <>{" "}{trx("There is already a balance on {0}, so this one can go.", fmtDayMonth(u.day))}</>)}</>
    );
    buttons = u.occupied ? (
      <Button size="sm" variant="primary" disabled={busy} onClick={() => action.mutate({ kind: "away" })}>{tr("Delete this balance")}</Button>
    ) : (
      <>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => action.mutate({ kind: "move", dest: u.day })}>{trx("Set to {0}", fmtDayMonth(u.day))}</Button>
        {away}
      </>
    );
  } else if (u.kind === "duplicate") {
    cause = (
      <>{trx("{0} on {1} ({2}) is in your transactions {3} times, and that's exactly the difference. If it's in there once too often, this balance is right.", u.name, fmtDayMonth(u.date), fmtEuro(u.amount), u.count)}</>
    );
    buttons = (
      <>
        <ButtonLink size="sm" variant="primary" href="/spending/transactions">{tr("To Transactions")}</ButtonLink>
        {measurements}
      </>
    );
  } else {
    cause = (
      <>{trx("Between {0} and your latest balance ({1}) {2} of {3} is missing from your transactions, or this balance is wrong. If a period is missing, fetch it via the bank connection or upload an export via {4}, top right. If this balance is wrong, set it to what your transactions say, or delete it.", fmtDayMonth(a.date), fmtDayMonth(a.anchor), fmtEuro(u.amount), u.direction, <strong>{tr("Update")}</strong>)}</>
    );
    buttons = (
      <>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => action.mutate({ kind: "calculated" })}>{trx("Set to {0}", fmtEuro(a.calculated))}</Button>
        {away}
        {measurements}
      </>
    );
  }

  return (
    <li className="py-3" style={{ borderTop: "1px solid var(--rule)" }}>
      <p>{trx("{0} · balance of {1} {2}", <strong>{a.account}</strong>, fmtDayMonthYear(a.date), <span className="text-xs text-ink-muted">({fetched ? tr("from the bank connection or an import") : tr("entered by hand")})</span>)}</p>
      <p className="num mt-0.5 text-xs text-ink-muted">{trx("{0} {1} · according to your transactions {2} · difference {3}", fetched ? tr("Fetched") : tr("Entered"), fmtEuro(a.measured), fmtEuro(a.calculated), trueMinus(fmtEuro(a.measured - a.calculated)))}</p>
      <p className="mt-2 max-w-[72ch] text-[13px] leading-relaxed">{cause}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">{buttons}</div>
      {action.isError && (
        <p className="mt-1 text-xs" style={{ color: "var(--text-loss)" }}>{(action.error as ApiError).message}</p>
      )}
    </li>
  );
}
