// The explanation that appears in more than one place, written once.
//
// How to get an export from your bank is in the Update panel next to the box you
// drop it in, and in Help → Money; how to export from DeGiro is in Update, in
// Help → Portfolio and in the tour (components/OnboardingTutorial.tsx). Whoever
// changes something here changes it everywhere at once — and that is the point:
// two versions of the same explanation drift apart after a while.

import { tr, trx } from "@/lib/i18n";

export type Bank = "ing" | "bunq";

// Per bank which files, and what each file delivers. The app recognises by itself
// which file is which; the choice is only for the explanation.
export const BANKS: { id: Bank; name: string; steps: React.ReactNode[]; note: string }[] = [
  {
    id: "ing",
    name: "ING",
    steps: [
      <>
        {trx(
          "{0}: in Mijn ING download your debits and credits as CSV with {1}. That variant has the balance after each booking, and with it your balance per day. (With commas works too, but without balance.)",
          <b className="text-text">{tr("Current account")}</b>,
          <b className="text-text">{tr("semicolons")}</b>,
        )}
      </>,
      <>
        {trx(
          "{0}: the same download for all your savings accounts together. Interest counts as income; transfers from and to your current account count nowhere.",
          <b className="text-text">{tr("Savings accounts")}</b>,
        )}
      </>,
      <>
        {trx(
          "{0}: one balance per day per savings account. Once is enough: after that your savings account follows the transfers from your current account.",
          <b className="text-text">{tr("Balance overview savings accounts")}</b>,
        )}
      </>,
    ],
    note: tr("Menu names sometimes differ per version of the site or app; what matters is the CSV. Uploading all three at once is fine."),
  },
  {
    id: "bunq",
    name: "bunq",
    steps: [
      <>
        {trx("{0}: open the account in the app and export the account statement as CSV.", <b className="text-text">{tr("Per account")}</b>)}
      </>,
    ],
    note: tr(
      "bunq puts no balance in the export. So enter the balance of your bunq account yourself once at Accounts; after that the app calculates it on from your transactions.",
    ),
  },
];

/** The steps of one bank, as a numbered list with the note below it. */
export function BankSteps({ bank }: { bank: Bank }) {
  const b = BANKS.find((x) => x.id === bank) ?? BANKS[0];
  return (
    <>
      <ol className="mb-2 flex list-decimal flex-col gap-1.5 pl-4 text-xs text-ink-muted">
        {b.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <p className="text-xs text-ink-muted">{b.note}</p>
    </>
  );
}
