"use client";

// Help — Portfolio. The same structure as Help → Money: getting started,
// bringing data in, how the figures work, where to find what. The DeGiro steps
// are the same as in Update and in the tour.

import Link from "next/link";
import { Section } from "@/components/ds";
import { DegiroSteps } from "@/components/OnboardingTutorial";
import { useOnboarding } from "@/lib/onboarding";
import { tr, trx } from "@/lib/i18n";

const CONTENT: [string, string][] = [
  ["beginnen", tr("Getting started")],
  ["binnenhalen", tr("Getting your data in")],
  ["digits", tr("How the figures work")],
  ["where", tr("Where to find what")],
];

function A({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="underline underline-offset-4">{children}</Link>;
}

function TextBlock({ children }: { children: React.ReactNode }) {
  return <div className="flex max-w-[46rem] flex-col gap-3 text-[13.5px] leading-relaxed">{children}</div>;
}

export default function HelpPortfolio() {
  const q = useOnboarding();
  const p = q.data?.status.portfolio;

  return (
    <div className="flex flex-col gap-8">
      <Section label={tr("How Portfolio works")}>
        <TextBlock>
          <p>{tr("Portfolio is your investments at DeGiro: what you own, what it's worth, what it yielded. The app fetches nothing from DeGiro automatically. You provide two exports, after that everything fills in by itself and the prices follow along.")}</p>
          <nav aria-label={tr("Contents")} className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {CONTENT.map(([id, title]) => <a key={id} href={`#${id}`} className="underline underline-offset-4">{title}</a>)}
          </nav>
        </TextBlock>
      </Section>

      <section id="getting-started" className="scroll-mt-20">
        <Section label={tr("Getting started")}>
          <TextBlock>
            <ol className="list-decimal pl-5">
              <li>{trx("Export {0} from DeGiro and upload them at {1}, top right. That sets your positions, purchase prices and result.{2}", <b>{tr("Transactions")}</b>, <b>{tr("Update")}</b>, p && p.transactions > 0 && <span className="text-ink-muted">{" "}{trx("Done: {0} rows.", p.transactions)}</span>)}</li>
              <li>{trx("{0} from DeGiro, also at Update. That sets your dividend, and the cash balance at DeGiro in your net worth.{1}", <b>{tr("Account statement")}</b>, p && p.dividends > 0 && <span className="text-ink-muted">{" "}{trx("Done: {0} payouts.", p.dividends)}</span>)}</li>
              <li>{tr("After that again now and then, with the newest period. What's already there is skipped.")}</li>
            </ol>
          </TextBlock>
        </Section>
      </section>

      <section id="importing" className="scroll-mt-20">
        <Section label={tr("Getting your data in")}
          info={tr("The same steps as behind “Where do I find these files?” in Update.")}>
          <div className="max-w-[440px]">
            <DegiroSteps />
          </div>
          <p className="pt-3 text-xs text-ink-muted">{tr("Both as .xlsx or .csv. The first time choose a start date before your very first purchase, so your whole history comes along. Uploading again is always safe.")}</p>
        </Section>
      </section>

      <section id="figures" className="scroll-mt-20">
        <Section label={tr("How the figures work")}>
          <TextBlock>
            <p>{trx("{0} The value is the sum of your positions at their last fetched price. Prices come from Yahoo Finance and run about a quarter of an hour behind the exchange; they are refreshed when you come in and with “Refresh prices” in Update.", <b>{tr("Value and prices.")}</b>)}</p>
            <p>{trx("{0} is your average purchase price per unit, without transaction costs. {1} is the current price against that average cost: gain on paper. {2} is what a position yielded in total: unrealised plus earlier realised gain and received dividend, minus all costs.", <b>{tr("Avg cost")}</b>, <b>{tr("Unrealised")}</b>, <b>{tr("Total P/L")}</b>)}</p>
            <p>{trx("{0} put your portfolio next to an index over time, with your deposits and withdrawals taken out. {1} shows where your money is, also within your ETF's.", <b>{tr("Returns and benchmarks")}</b>, <b>{tr("Allocation")}</b>)}</p>
            <p>{trx("{0} your portfolio counts at market value; dividend is on your DeGiro cash and counts there, not again on top of your units. See {1}.", <b>{tr("In your net worth")}</b>, <A href="/help/money#balances">{tr("Balances and net worth")}</A>)}</p>
          </TextBlock>
        </Section>
      </section>

      <section id="where-to-find" className="scroll-mt-20">
        <Section label={tr("Where to find what")}>
          <TextBlock>
            <ul className="list-disc pl-5">
              <li>{trx("{0}: what your portfolio is worth now, and what happened today.", <A href="/dashboard">{tr("Today")}</A>)}</li>
              <li>{trx("{0}: every position, with its result; click one for the details.", <A href="/portfolio">{tr("Portfolio")}</A>)}</li>
              <li>{trx("{0}: your return over time, next to an index.", <A href="/returns">{tr("Returns")}</A>)}</li>
              <li>{trx("{0}: breakdown over regions, sectors and funds.", <A href="/allocation">{tr("Allocation")}</A>)}</li>
              <li>{tr("If a screen isn't in your sidebar, it's a beta feature that is still off for your account.")}</li>
            </ul>
            <p className="text-xs text-ink-muted">{trx("Every screen has a {0} next to the title with what exactly is there.", <b>?</b>)}</p>
          </TextBlock>
        </Section>
      </section>
    </div>
  );
}
