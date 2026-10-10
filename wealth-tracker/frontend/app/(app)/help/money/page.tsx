"use client";

// How Money works — the manual.
//
// For someone just starting, and for someone who later wants to know why
// something is where it is. At the top what you still have to do yourself (from
// your own data, not from a fixed list), then per subject: bringing data in,
// balances and net worth, labelling, the categories. The list of categories
// comes from your own taxonomy, so nothing is ever shown here that you do not
// have (any more).

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Section, Tag } from "@/components/ds";
import { StepContent, StepPlan } from "@/components/steps/StepPlan";
import { CONNECT_BANK, EXPORT_ROUTES, LABELLING, ENTER_BALANCE } from "@/components/steps/money";
import type { Category, CategoryType, ConnectionStatus, Rule, Account } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";

const CONTENT: [string, string][] = [
  ["beginnen", tr("Getting started")],
  ["binnenhalen", tr("Getting your data in")],
  ["balances", tr("Balances and net worth")],
  ["labelling", tr("How labelling works")],
  ["bijzonder", tr("Categories that count differently")],
  ["categories", tr("All your categories")],
  ["months", tr("Months, budget and debts")],
  ["privacy", tr("Privacy and security")],
];

const TYPE_EXPLANATION: Record<CategoryType, string> = {
  EXPENSE: tr("counts as an expense"),
  INCOME: tr("counts as income"),
  INTERNAL: tr("doesn't count as income or expense"),
};

function A({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="underline underline-offset-4">{children}</Link>;
}

function TextBlock({ children }: { children: React.ReactNode }) {
  return <div className="flex max-w-[46rem] flex-col gap-3 text-[13.5px] leading-relaxed">{children}</div>;
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="pt-2 text-[13.5px] font-semibold">{children}</h3>;
}

function Step({ done, title, children }: { done: boolean | null; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 py-3" style={{ borderTop: "1px solid var(--rule)" }}>
      <span aria-hidden className="num flex h-6 w-6 flex-none items-center justify-center rounded-full text-xs font-semibold"
        style={{ background: done ? "var(--text-gain)" : "var(--surface-inset)", color: done ? "var(--surface-page)" : undefined }}>
        {done ? "✓" : "·"}
      </span>
      <div className="flex min-w-0 flex-col gap-1 text-[13px] leading-relaxed">
        <p className="font-semibold">
          {title}{" "}
          {done !== null && <Tag tone={done ? "gain" : "neutral"}>{done ? "completed" : tr("to do")}</Tag>}
        </p>
        {children}
      </div>
    </li>
  );
}

/** What you have already done, from your own data. */
function GettingStarted() {
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<{ accounts: Account[] }>("/api/accounts") });
  // A period in the far future: no transactions back, but the total.
  const date_range = useQuery({
    queryKey: ["bank_transactions", "date_range"],
    queryFn: () => api.get<{ total: number }>("/api/bank-transactions?start=9999-12-31"),
  });
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionStatus>("/api/connections") });

  const items = (accounts.data?.accounts ?? []).filter((r) => r.active);
  const hasAccount = accounts.data ? items.length > 0 : null;
  const hasTransactions = date_range.data ? date_range.data.total > 0 : null;
  const withoutBalance = items.filter((r) => r.balance === null);
  const linked = connections.data ? connections.data.consents.some((t) => t.status === "active") : null;

  return (
    <ol className="flex flex-col">
      <Step done={hasTransactions === null ? null : hasTransactions || !!linked} title={tr("1. Bring in your transactions")}>
        <p>{trx("Connect your bank at {0}, or upload an export via {1}, top right. The app creates the accounts itself.{2}", <A href="/accounts/connect">{tr("Accounts → Bank connection")}</A>, <b>{tr("Update")}</b>, hasTransactions && <>{" "}{trx("There {0} already {1} transactions.", date_range.data!.total === 1 ? tr("is") : tr("are"), <span className="num">{date_range.data!.total}</span>)}</>)}</p>
      </Step>
      <Step done={hasAccount === null ? null : hasAccount && withoutBalance.length === 0}
        title={tr("2. Give each account one balance")}>
        <p>{trx("One balance per account is enough: today's, at {0} → Update balance. The app calculates the rest back from your transactions. A connected bank and an ING export with semicolons provide the balance themselves.{1}", <A href="/accounts">{tr("Accounts")}</A>, withoutBalance.length > 0 && <>{" "}{trx("Still without a balance: {0}.", withoutBalance.map((r) => r.name).join(", "))}</>)}</p>
      </Step>
      <Step done={null} title={tr("3. Label what the app doesn't recognise")}>
        <p>{trx("Most transactions get a category by themselves. What remains is at {0}: choose a category, and it applies to that counterparty from then on. See {1}.", <A href="/spending/labelling">{tr("Spending → To label")}</A>, <a href="#labelen" className="underline underline-offset-4">{tr("how labelling works")}</a>)}</p>
      </Step>
      <Step done={null} title={tr("4. Look at your figures")}>
        <p>{trx("{0} shows what you have and how it grows, {1} where your money goes. There you also choose whether a month runs from the 1st, or from salary to salary.", <A href="/net-worth">{tr("Net worth")}</A>, <A href="/spending">{tr("Spending")}</A>)}</p>
      </Step>
    </ol>
  );
}

/** The categories as you have them, per group, with their type and how many rules fill them. */
function AllCategories() {
  const q = useQuery({ queryKey: ["categories"], queryFn: () => api.get<{ categories: Category[]; rules: Rule[] }>("/api/categories") });
  if (!q.data) return <p className="text-xs text-ink-muted">{tr("Loading…")}</p>;
  const perRule = q.data.rules.reduce<Record<string, number>>((acc, r) => {
    acc[r.category] = (acc[r.category] ?? 0) + 1;
    return acc;
  }, {});
  const onGroup = q.data.categories.reduce<Record<string, Category[]>>((acc, c) => {
    (acc[c.group_name] ??= []).push(c);
    return acc;
  }, {});
  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {Object.entries(onGroup).map(([group_name, items]) => (
        <div key={group_name}>
          <h4 className="pb-1 text-xs uppercase tracking-wide text-ink-muted">{group_name}</h4>
          <ul className="flex flex-col">
            {items.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 py-1 text-[12.5px]"
                style={{ borderTop: "1px solid var(--rule)" }}>
                <span>{c.name}</span>
                <span className="flex items-center gap-2">
                  <span className="num text-xs text-ink-muted">{trx("{0} rules", perRule[c.name] ?? 0)}</span>
                  <Tag tone={c.type === "INCOME" ? "gain" : "neutral"}>{TYPE_EXPLANATION[c.type]}</Tag>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

const SPECIAL: { name: string; when: React.ReactNode; totals: string; net_worth: string }[] = [
  {
    name: "Eigen rekeningen",
    when: tr("Money between two of your own accounts. Happens by itself once the app knows the IBAN of both."),
    totals: tr("Doesn't count."),
    net_worth: tr("Only moves from one account to the other."),
  },
  {
    name: "Naar spaarrekening",
    when: tr("Saving and moving back. Recognised by your bank's description."),
    totals: tr("Doesn't count."),
    net_worth: tr("Stays the same; your savings account follows along (see Balances)."),
  },
  {
    name: "Naar beleggen",
    when: tr("Deposits to and withdrawals from your broker, such as DeGiro. With the DeGiro account statement also recognised by amount and date."),
    totals: tr("Doesn't count."),
    net_worth: tr("Moves from bank to investments."),
  },
  {
    name: "Creditcard aflossing en Contant opnemen",
    when: tr("The repayment of your own credit card, money from the cash machine."),
    totals: tr("Doesn't count. Your card's purchases aren't in the app: move Creditcard aflossing to “Saved, as spending” under Categories, and the monthly bill counts as spending."),
    net_worth: tr("Cash counts if you have a Cash account with a balance."),
  },
  {
    name: "Niet meetellen",
    when: <>{tr("Other people's money that passes through your hands: friends pay you their share of a holiday you book, or you hold money for someone.")}</>,
    totals: tr("Doesn't count."),
    net_worth: tr("What you received and haven't paid on yet doesn't count as your net worth. If you paid more than you received, that difference is your own share: an ordinary expense."),
  },
  {
    name: "Giften & schenkingen",
    when: tr("A gift, a tax-free gift from your parents, an inheritance. Recognised by words such as schenking, belastingvrij or erfenis."),
    totals: tr("Doesn't count as income, so your savings rate is about what you earn yourself."),
    net_worth: tr("Simply counts: it's yours."),
  },
  {
    name: "Ontvangen van en Betaald aan vrienden",
    when: tr("Tikkies and payments from and to people."),
    totals: tr("Count as income and expense. If they are really other people's money or your own account, label them differently."),
    net_worth: tr("Simply counts."),
  },
  {
    name: "Onbekend",
    when: tr("No rule recognises it yet."),
    totals: tr("Counts as an expense or income, by the direction of the money."),
    net_worth: tr("Simply counts."),
  },
];

export default function ExplanationPage() {
  return (
    <div className="flex flex-col gap-8">
      <Section label={tr("How Money works")}>
        <TextBlock>
          <p>{trx("Money is all your money that isn't shares: your bank and savings accounts, cash, debts and brokers outside this app. Together with your portfolio that becomes your {0}; your transactions tell at {1} where it went.", <A href="/net-worth">{tr("net worth")}</A>, <A href="/spending">{tr("Spending")}</A>)}</p>
          <nav aria-label={tr("Contents")} className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {CONTENT.map(([id, title]) => (
              <a key={id} href={`#${id}`} className="underline underline-offset-4">{title}</a>
            ))}
          </nav>
        </TextBlock>
      </Section>

      <section id="getting-started" className="scroll-mt-20">
        <Section label={tr("Getting started")} info={tr("The ticks come from your own data: what's already done is marked.")}>
          <GettingStarted />
        </Section>
      </section>

      <section id="importing" className="scroll-mt-20">
        <Section label={tr("Getting your data in")}>
          <TextBlock>
            <H>{tr("Connect your bank")}</H>
            <p>{trx("Via Enable Banking, a licensed party under the European payment services directive (PSD2); the connection can only read. After that new transactions and your balance come in by themselves when you open the app. The step-by-step plan below, with the addresses to copy, is also at {0}.", <A href="/accounts/connect">{tr("Accounts → Bank connection")}</A>)}</p>
            <div className="max-w-[440px]"><StepPlan routes={[{ id: "connect", label: tr("Connect"), steps: CONNECT_BANK }]} /></div>

            <H>{tr("Upload an export")}</H>
            <p>{tr("For a savings account you can't connect, for a bank without a connection, or to go further back in time. The same step-by-step plan is behind “How do I export this?” in Update.")}</p>
            <div className="max-w-[440px]"><StepPlan routes={EXPORT_ROUTES} chooseLabel="Mijn bank:" /></div>
            <p>{trx("{0} is in {1}. {2}: add an account at {3} and enter the balance now and then.", <b>DeGiro</b>, <A href="/help/portfolio#importing">{tr("Help → Portfolio")}</A>, <b>{tr("Another bank")}</b>, <A href="/accounts">{tr("Accounts")}</A>)}</p>
            <p>{trx("{0} Uploading again is safe, also next to a connection: a booking that's already there (even with a different description) is recognised by account, date and amount and skipped. Two identical coffees on one day stay two.", <b>{tr("Nothing twice.")}</b>)}</p>

            <H>{tr("Accounts by hand")}</H>
            <p>{trx("Cash, a broker outside this app (Coinbase), a loan or student debt: add them at {0} with the matching kind, and enter a balance. A debt is always shown as minus, even if you type it as positive.", <A href="/accounts">{tr("Accounts")}</A>)}</p>
          </TextBlock>
        </Section>
      </section>

      <section id="balances" className="scroll-mt-20">
        <Section label={tr("Balances and net worth")}>
          <TextBlock>
            <p>{trx("{0} With transactions the app calculates back and forward from your latest balance, day by day. Without transactions it draws a straight line between your measurements. An account without a single balance doesn't count in your net worth (unknown is not zero) and Net worth says which ones those are.", <b>{tr("One balance is enough.")}</b>)}</p>
            <p>{trx("{0} After your last upload the balance of a savings account follows the transfers on your current account that mention it, via its IBAN or account number. Interest the bank credits doesn't show that way; a new upload or an entered balance puts it exactly right again.", <b>{tr("Savings accounts follow along.")}</b>)}</p>
            <p>{trx("{0} An earlier balance should come out exactly on what the app calculates back from your latest balance. If it doesn't, it's shown at the top of Accounts, with the likely cause and a button that fixes it. Usually it's a card payment still on its way: your bank takes it off your balance immediately, but it only shows in your transactions once it's booked. The app corrects a balance from the bank connection itself; a balance you entered yourself it leaves to you.", <b>{tr("A balance that doesn't match.")}</b>)}</p>
            <p>{trx("{0} is investments plus bank and cash, minus your debts. Investments is your portfolio from this app plus the cash balance at DeGiro and other brokers.", <b>{tr("Net worth")}</b>)}</p>
          <div className="max-w-[440px]"><StepContent step={ENTER_BALANCE} /></div>
          </TextBlock>
        </Section>
      </section>

      <section id="labelling" className="scroll-mt-20">
        <Section label={tr("How labelling works")}>
          <TextBlock>
            <p>{tr("Each transaction gets a category, in this order; the first that matches wins:")}</p>
            <ol className="list-decimal pl-5">
              <li>{trx("{0} A category you set by hand always wins and is never overwritten.", <b>{tr("Your own choice.")}</b>)}</li>
              <li>{trx("{0} If the counter account is one of your accounts, it's Eigen rekeningen.", <b>{tr("Your own accounts.")}</b>)}</li>
              <li>{trx("{0} A deposit that shows up in your DeGiro account statement is Naar beleggen.", <b>{tr("Your broker.")}</b>)}</li>
              <li>{trx("{0}, by priority (lower wins). A rule looks for a pattern in the counterparty's name, in the description, or in both, optionally only for money coming in or going out. The app has about sixty by default (supermarkets, transport companies, insurers) and you add your own.", <b>{tr("The rules")}</b>)}</li>
              <li>{trx("{0} If the name looks like a person's, it's received from or paid to friends.", <b>{tr("A person.")}</b>)}</li>
              <li>{trx("{0}, if nothing matches.", <b>Onbekend</b>)}</li>
            </ol>

            <div className="max-w-[440px]"><StepContent step={LABELLING} /></div>

            <H>{tr("Labelling yourself")}</H>
            <ul className="list-disc pl-5">
              <li>{trx("{0}: at {1} under “No category yet”: choose a category and a rule is made for that name, for your whole history. Click the name to see the individual transactions.", <b>{tr("Per counterparty")}</b>, <A href="/spending/labelling">{tr("To label")}</A>)}</li>
              <li>{trx("{0}: at {1}: filter by period, account, category, direction or name, tick and label in one go. For one-off things, such as a holiday with friends. Don't make a rule of it: a rule on a name also labels everything that name does later.", <b>{tr("A selection")}</b>, <A href="/spending/transactions">{tr("Transactions")}</A>)}</li>
              <li>{trx("{0}: at {1}, with the menu per row.", <b>{tr("One transaction")}</b>, <A href="/spending/transactions">{tr("Transactions")}</A>)}</li>
              <li>{trx("{0}: at {1} under “Is this right?”: transactions the rules gave a category while the money probably went between your own accounts.", <b>{tr("What looks wrong")}</b>, <A href="/spending/labelling">{tr("To label")}</A>)}</li>
            </ul>
            <p>{trx("{0} Behind Mollie, Adyen or Stripe are different shops; the real one is in the description, and that's where the rules look for such names too. A rule on the name “Mollie” itself labels all those shops the same: the app warns about that.", <b>{tr("Payment processors.")}</b>)}</p>
          </TextBlock>
        </Section>
      </section>

      <section id="special-cases" className="scroll-mt-20">
        <Section label={tr("Categories that count differently")}
          info={tr("A category's type decides whether it counts as an expense, as income, or nowhere. These deserve an explanation.")}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[12.5px]">
              <thead>
                <tr className="text-left text-ink-muted">
                  <th className="py-1.5 pr-3 font-normal">{tr("Category")}</th>
                  <th className="py-1.5 pr-3 font-normal">{tr("What for")}</th>
                  <th className="py-1.5 pr-3 font-normal">{tr("Income and spending")}</th>
                  <th className="py-1.5 font-normal">{tr("Net worth")}</th>
                </tr>
              </thead>
              <tbody>
                {SPECIAL.map((b) => (
                  <tr key={b.name} className="align-top" style={{ borderTop: "1px solid var(--rule)" }}>
                    <td className="py-2 pr-3 font-semibold">{b.name}</td>
                    <td className="py-2 pr-3">{b.when}</td>
                    <td className="py-2 pr-3 text-ink-muted">{b.totals}</td>
                    <td className="py-2 text-ink-muted">{b.net_worth}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </section>

      <section id="categories" className="scroll-mt-20">
        <Section label={tr("All your categories")}
          info={tr("From your own taxonomy. You add or delete a category at Categories.")}>
          <AllCategories />
          <p className="pt-3 text-xs text-ink-muted">{trx("You make your own category at {0}: choose a group, a name and the type. Choose {1} for money you don't want to count as income or expense.", <A href="/categories">{tr("Categories")}</A>, <b>{tr("internal")}</b>)}</p>
        </Section>
      </section>

      <section id="months" className="scroll-mt-20">
        <Section label={tr("Months, budget and debts")}>
          <TextBlock>
            <p>{trx("{0} On Spending, Net worth and Accounts you choose whether a month runs from the 1st, or from the day your salary comes in. The app recognises your salary day from the Salaris category, even if your employer pays earlier because of a weekend or public holiday. Monthly totals, averages, your budget and net worth per month follow that choice.", <b>{tr("From salary to salary.")}</b>)}</p>
            <p>{trx("{0} you set per group at Spending → Budget. As a suggestion it shows what you spent in a normal month.", <b>Budget</b>)}</p>
            <p>{trx("{0} the app recognises itself: what comes back in at least three months, roughly monthly and roughly the same size. At Transactions every expense shows whether it's a fixed cost and you turn it on or off; the overview is at Categories. That's how you say where it's wrong: the pub every month isn't a fixed cost, an energy bill with a varying amount is. In Budget this month fixed costs count on the day they usually go out: paid rent is then not “faster than planned”.", <b>{tr("Fixed costs")}</b>)}</p>
            <p>{trx("{0} For a debt account you enter the yearly interest and the required monthly repayment under “Interest & repayment”. At the start of each month the app calculates it on. If you repay extra once, enter the new balance: it calculates on from there.", <b>{tr("Debts.")}</b>)}</p>
          </TextBlock>
        </Section>
      </section>

      <section id="privacy" className="scroll-mt-20">
        <Section label={tr("Privacy and security")}>
          <TextBlock>
            <p>{trx("Everyone has their own database; no one else sees your accounts. Your bank connection's key is stored encrypted and never returned by any screen, and the connection can only read. More in the {0}.", <A href="/privacy">{tr("privacy statement")}</A>)}</p>
          </TextBlock>
        </Section>
      </section>
    </div>
  );
}
