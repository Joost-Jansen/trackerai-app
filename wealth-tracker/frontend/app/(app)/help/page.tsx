"use client";

// Help — Getting started.
//
// Both parts of the app side by side, with what you have already done and what
// is still possible, from your own data. Here you also choose what you track,
// and restart the tour. The manuals are in the tabs next to it, with the same
// structure: getting started, bringing data in, how the figures work.

import Link from "next/link";
import { Button, ButtonLink, Section, Tabs } from "@/components/ds";
import { isIncluded, CHOICES, useOnboarding, useSaveOnboarding, type Choice } from "@/lib/onboarding";
import { tr, trx } from "@/lib/i18n";

function Tick({ done, title, children }: { done: boolean; title: string; children?: React.ReactNode }) {
  return (
    <li className="flex gap-3 py-2.5" style={{ borderTop: "1px solid var(--rule)" }}>
      <span
        aria-hidden
        className="flex h-5 w-5 flex-none items-center justify-center rounded-full text-[11px] font-semibold"
        style={{
          background: done ? "var(--text-gain)" : "var(--surface-inset)",
          color: done ? "var(--surface-page)" : "var(--text-faint)",
        }}
      >
        {done ? "✓" : "·"}
      </span>
      <div className="flex min-w-0 flex-col gap-0.5 text-[13px]">
        <span className={done ? "" : "font-semibold"}>{title}</span>
        {children && <span className="text-xs text-ink-muted">{children}</span>}
      </div>
    </li>
  );
}

export default function HelpStart() {
  const q = useOnboarding();
  const put = useSaveOnboarding();
  if (!q.data) return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  const { choice, status } = q.data;
  const p = status.portfolio;
  const g = status.money;

  return (
    <div className="flex flex-col gap-8">
      <Section
        label={tr("Getting started")}
        info={
          q.data.money ? (
            <>
              {tr(
                "This app has two parts. Portfolio is about your investments at DeGiro; Money about all other money: bank, savings, debts. Together they make up your net worth.",
              )}
            </>
          ) : (
            <>{tr("Portfolio is about your investments at DeGiro: what you own, what it's worth and what it yielded.")}</>
          )
        }
      >
        <div className="flex flex-wrap items-center gap-3 pb-2">
          {q.data.money && (
            <>
              <span className="text-xs text-ink-muted">{tr("I keep track of:")}</span>
              <Tabs
                variant="segmented"
                ariaLabel={tr("What you keep track of")}
                items={CHOICES.map((k) => ({ id: k.id, label: k.title }))}
                value={choice ?? "both"}
                onChange={(v) => put.mutate({ choice: v as Choice })}
              />
            </>
          )}
          <Button
            size="sm"
            variant="ghost"
            disabled={put.isPending}
            onClick={() => {
              try {
                sessionStorage.removeItem("tour-paused");
              } catch {
                /* geen opslag */
              }
              put.mutate({ done: false, step: 0 });
            }}
          >
            {tr("Tour again")}
          </Button>
        </div>
        <p className="text-xs text-ink-muted">
          {trx(
            "Explanations are in three places: the {0} next to each page title (what this screen is), the {1} on a block (what that block shows), and here, the guides.",
            <b>?</b>,
            <b>i</b>,
          )}
        </p>
      </Section>

      <div className={`grid gap-8 ${choice === "both" || !choice ? "md:grid-cols-2" : ""}`}>
        {isIncluded(choice, "investments") && (
          <Section
            label={tr("Portfolio")}
            action={
              <ButtonLink href="/help/portfolio" size="sm" variant="secondary">
                {tr("Guide")}
              </ButtonLink>
            }
          >
            <ul className="flex flex-col">
              <Tick done={p.transactions > 0} title={tr("Transactions from DeGiro")}>
                {p.transactions > 0 ? (
                  <>{trx("{0} rows imported: your positions and return.", p.transactions)}</>
                ) : (
                  <>
                    {trx(
                      "Export them from DeGiro and upload them at Update. {0}",
                      <Link href="/help/portfolio#importing" className="underline underline-offset-4">
                        {tr("How it works")}
                      </Link>,
                    )}
                  </>
                )}
              </Tick>
              <Tick done={p.dividends > 0} title={tr("Account statement from DeGiro")}>
                {p.dividends > 0 ? (
                  <>{trx("{0} dividend payouts, and your DeGiro cash in your net worth.", p.dividends)}</>
                ) : (
                  <>{tr("For your dividend and the cash balance at DeGiro.")}</>
                )}
              </Tick>
              <Tick done={p.transactions > 0} title={tr("Prices")}>
                {tr("Refreshes by itself when you come in, and with “Refresh prices” in Update.")}
              </Tick>
            </ul>
          </Section>
        )}

        {isIncluded(choice, "money") && (
          <Section
            label={tr("Money")}
            action={
              <ButtonLink href="/help/money" size="sm" variant="secondary">
                {tr("Guide")}
              </ButtonLink>
            }
          >
            <ul className="flex flex-col">
              <Tick done={g.linked || g.bank_transactions > 0} title={tr("Your bank connected or an export uploaded")}>
                {g.linked ? (
                  <>{tr("Connected; new transactions come in by themselves.")}</>
                ) : g.bank_transactions > 0 ? (
                  <>
                    {trx(
                      "{0} transactions. You can also connect: {1}.",
                      g.bank_transactions,
                      <Link href="/accounts/connect" className="underline underline-offset-4">
                        {tr("Bank connection")}
                      </Link>,
                    )}
                  </>
                ) : (
                  <>
                    {trx(
                      "{0} or upload an export at Update.",
                      <Link href="/accounts/connect" className="underline underline-offset-4">
                        {tr("Link your bank")}
                      </Link>,
                    )}
                  </>
                )}
              </Tick>
              <Tick done={g.accounts > 0 && g.without_balance.length === 0} title={tr("One balance per account")}>
                {g.accounts === 0 ? (
                  <>{tr("Accounts come by themselves with your first export or connection.")}</>
                ) : g.without_balance.length > 0 ? (
                  <>
                    {trx(
                      "Still without: {0}. {1}",
                      g.without_balance.join(", "),
                      <Link href="/accounts" className="underline underline-offset-4">
                        {tr("To Accounts")}
                      </Link>,
                    )}
                  </>
                ) : (
                  <>{trx("All {0} accounts count in your net worth.", g.accounts)}</>
                )}
              </Tick>
              <Tick done={g.bank_transactions > 0 && g.unlabelled === 0} title={tr("Everything labelled")}>
                {g.unlabelled > 0 ? (
                  <>
                    {trx(
                      "{0} transactions without a category. {1}",
                      g.unlabelled,
                      <Link href="/spending/labelling" className="underline underline-offset-4">
                        {tr("To To label")}
                      </Link>,
                    )}
                  </>
                ) : (
                  <>{tr("What the rules don't recognise comes to Spending → To label by itself.")}</>
                )}
              </Tick>
            </ul>
          </Section>
        )}
      </div>
    </div>
  );
}
