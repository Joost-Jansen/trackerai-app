// The step-by-step plans of Money: connecting your bank, making an export,
// entering a balance and labelling. The same shape as the DeGiro steps
// (degiro.tsx): a redrawing per step, marking where you need to be.
//
// Redrawings of the screens of Enable Banking, ING and bunq with fixed colours;
// menu names sometimes differ per version of their site or app, so the text says
// what it is about and not only where you click.

import type { Route, Step } from "./StepPlan";
import { Mark, MockBrowser, MockButton, MockPhone, MockField } from "./StepPlan";
import { tr, trx } from "@/lib/i18n";

const ING = "#ff6200";
const BUNQ = "#1b1b1b";
const APP = "#2f2a24";

// ---------------------------------------------------------------- connecting

function EnableBankingRegister() {
  return (
    <MockBrowser url="enablebanking.com/cp/applications">
      <p className="mb-2 font-semibold">Add a new application</p>
      <div className="grid grid-cols-2 gap-2">
        <MockField label="Environment" value="Production" mark />
        <MockField label="Application name" value={tr("My money")} />
      </div>
      <div className="mt-2 flex flex-col gap-2">
        <MockField label="Redirect URLs" value=".../api/connections/enablebanking/callback" mark />
        <MockField label="Privacy URL · Terms URL" value=".../privacy · .../terms" />
        <MockField label="Private key" value="Generate in the browser and export" />
      </div>
      <div className="mt-2.5 flex items-center justify-between">
        <span className="text-[10px] text-black/45">download: <b>5bec30d8-….pem</b></span>
        <MockButton mark colour="#0a5bd7">Register</MockButton>
      </div>
    </MockBrowser>
  );
}

function EnableBankingActivate() {
  return (
    <MockBrowser url="enablebanking.com/cp/applications">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{tr("My money")}</span>
        <span className="rounded bg-black/5 px-1.5 py-0.5 text-[9.5px]">Inactive</span>
      </div>
      <p className="mt-2 text-black/55">{tr("Not active yet: first link your own accounts.")}</p>
      <div className="mt-2"><MockButton mark colour="#0a5bd7">Activate by linking accounts</MockButton></div>
      <div className="mt-2 flex gap-2 text-[10px]">
        <span className="rounded border border-black/15 px-2 py-0.5">ING ✓</span>
        <span className="rounded border border-black/15 px-2 py-0.5">bunq ✓</span>
      </div>
    </MockBrowser>
  );
}

function AppKey() {
  return (
    <MockBrowser url={tr("this app · Accounts → Bank connection")}>
      <p className="mb-2 font-semibold">{tr("Put your app ID and key in the app")}</p>
      <div className="flex flex-col gap-2">
        <MockField label="App-ID" value="5bec30d8-ce0d-40a9-…" mark />
        <MockField label="Private key (.pem)" value="📄 5bec30d8-….pem" mark />
      </div>
      <div className="mt-2.5 text-right"><MockButton colour={APP}>{tr("Save")}</MockButton></div>
    </MockBrowser>
  );
}

function AppPickBanks() {
  return (
    <MockBrowser url={tr("this app · Accounts → Bank connection")}>
      <p className="mb-2 font-semibold">{tr("Add banks")}</p>
      <div className="flex flex-col gap-1">
        {[["ING", true], ["bunq", true], ["ABN AMRO", false]].map(([name, on]) => (
          <span key={String(name)} className="flex items-center gap-2 rounded border border-black/10 px-2 py-1">
            <span className={`grid h-3 w-3 place-items-center rounded-sm border ${on ? "border-[#2f2a24] bg-[#2f2a24] text-white" : "border-black/30"}`}>
              {on ? "✓" : ""}
            </span>
            {name}
          </span>
        ))}
      </div>
      <div className="mt-2.5 text-right"><Mark><MockButton colour={APP}>{tr("Connect 2 banks")}</MockButton></Mark></div>
    </MockBrowser>
  );
}

function BankConsent() {
  return (
    <MockPhone title="ING" colour={ING}>
      <p className="font-semibold">{tr("Give consent")}</p>
      <p className="text-black/55">{tr("“My money” wants to read your balance and transactions.")}</p>
      <span className="rounded border border-black/15 px-2 py-1">{tr("☑ Current account ···1234")}</span>
      <span className="rounded border border-black/15 px-2 py-1">{tr("☑ Savings account")}</span>
      <span className="mt-1"><MockButton mark colour={ING}>{tr("Confirm")}</MockButton></span>
    </MockPhone>
  );
}

export const CONNECT_BANK: Step[] = [
  {
    title: tr("Step 1: Create an app at Enable Banking"),
    intro: <>{tr("Create a free account at enablebanking.com and register an application of your own in the Control Panel. The addresses you need are ready to copy on the Bank connection page.")}</>,
    bullets: [
      tr("Environment: Production. Sandbox only works with test banks"),
      tr("Redirect, Privacy and Terms URL: copy them from the Bank connection page"),
      tr("After Register your browser downloads a .pem file: that's your key. Its name is your app ID"),
    ],
    visual: <EnableBankingRegister />,
  },
  {
    title: tr("Step 2: Activate with your own accounts"),
    intro: <>{tr("Your application starts as “Inactive”. Link your own accounts to it; after that it can only reach your accounts.")}</>,
    bullets: [
      tr("Click Activate by linking accounts and approve in your bank app"),
      tr("Do that for each bank you want to connect"),
      tr("After that it says Restricted and Active. That's how it should be"),
    ],
    visual: <EnableBankingActivate />,
  },
  {
    title: tr("Step 3: Put your app ID and key in the app"),
    intro: <>{tr("At Accounts → Bank connection you enter your app ID and upload the .pem file.")}</>,
    bullets: [
      tr("The key is stored encrypted and never returned by any screen"),
      tr("Share the .pem file with no one"),
    ],
    visual: <AppKey />,
  },
  {
    title: tr("Step 4: Choose your banks"),
    intro: <>{tr("Tick one or more banks. You go through them one after another, and briefly come back to the app in between.")}</>,
    bullets: [tr("Banks from other countries too"), tr("After each bank we fetch your transactions and balance right away")],
    visual: <AppPickBanks />,
  },
  {
    title: tr("Step 5: Approve in your bank app"),
    intro: <>{tr("Your bank asks whether the app may read your balance and transactions. Choose the accounts you want to see and confirm.")}</>,
    bullets: [
      tr("Read only: the connection can never pay"),
      tr("The consent lasts about 180 days; after that you click Connect again"),
      tr("New transactions then come in by themselves when you open the app"),
    ],
    visual: <BankConsent />,
  },
];

// ---------------------------------------------------------------- exports

function IngDownload({ balances = false }: { balances?: boolean }) {
  return (
    <MockBrowser url="mijn.ing.nl">
      <div className="mb-2 flex items-center gap-2">
        <span className="h-3 w-3 rounded-full" style={{ background: ING }} />
        <span className="font-semibold">{balances ? tr("Balance overview savings accounts") : tr("Download debits and credits")}</span>
      </div>
      <div className="flex flex-col gap-2">
        <MockField label={tr("Account")} value={balances ? tr("All savings accounts") : tr("Current account ···1234")} />
        <MockField label={tr("Period")} value={tr("01-01-2020 to today")} mark={!balances} />
        <MockField label={tr("File format")} value={tr("Comma-separated CSV (semicolon)")} mark />
      </div>
      <div className="mt-2.5 text-right"><MockButton colour={ING}>{tr("Download")}</MockButton></div>
    </MockBrowser>
  );
}

function BunqExport() {
  return (
    <MockPhone title={tr("bunq · Account")} colour={BUNQ}>
      <span className="rounded border border-black/15 px-2 py-1">{tr("Statement")}</span>
      <MockField label={tr("Period")} value={tr("Past 12 months")} mark />
      <MockField label={tr("Format")} value="CSV" mark />
      <span className="mt-1"><MockButton colour="#2b9a3d">{tr("Export")}</MockButton></span>
    </MockPhone>
  );
}

function UpdateBank({ bank }: { bank: string }) {
  return (
    <MockBrowser url={tr("this app · Update")}>
      <p className="mb-2 font-semibold">{tr("Import from your bank")}</p>
      <div className="mb-2 flex gap-1 text-[10px]">
        {["ING", "bunq"].map((b) => (
          <span key={b} className={`rounded px-2 py-0.5 ${b === bank ? "bg-[#2f2a24] text-white" : "border border-black/15"}`}>{b}</span>
        ))}
      </div>
      <div className="rounded-md border-2 border-dashed border-[#e0b400] bg-[#fce97a]/25 px-3 py-3 text-center">
        <b>{trx("{0} export", bank)}</b>
        <span className="block text-[10px] text-black/50">{tr(".csv · drag here or click to choose")}</span>
      </div>
    </MockBrowser>
  );
}

const UPLOAD: Step = {
  title: tr("Upload them at Update"),
  intro: <>{tr("Click Update at the top right and drag your CSV files into the box. The app sees by itself which bank and which kind of file it is.")}</>,
  bullets: [
    tr("Several files at once is fine"),
    tr("Uploading again is safe, also next to a connection: what's already there isn't added again"),
  ],
};

export const EXPORT_ROUTES: Route[] = [
  {
    id: "ing",
    label: "ING",
    steps: [
      {
        title: tr("Step 1: Download your current account"),
        intro: <>{trx("In Mijn ING: download your debits and credits as CSV with {0}. That variant has the balance after each booking.", <b>{tr("semicolons")}</b>)}</>,
        bullets: [
          tr("Choose a long period the first time, so your history comes along"),
          tr("With commas works too, but then without balance"),
        ],
        visual: <IngDownload />,
      },
      {
        title: tr("Step 2: And your savings accounts"),
        intro: <>{tr("The same download for your savings accounts, plus the balance overview: one balance per day per savings account.")}</>,
        bullets: [
          tr("Once is enough: after that your savings account follows the transfers from your current account"),
          tr("Interest counts as income; transfers to your current account count nowhere"),
        ],
        visual: <IngDownload balances />,
      },
      { ...UPLOAD, title: tr("Step 3: Upload them at Update"), visual: <UpdateBank bank="ING" /> },
    ],
  },
  {
    id: "bunq",
    label: "bunq",
    steps: [
      {
        title: tr("Step 1: Export per account"),
        intro: <>{tr("In the bunq app: open the account, choose the account statement and export as CSV. Do that for each account.")}</>,
        bullets: [
          tr("Choose a wide period the first time"),
          tr("bunq puts no balance in the export: enter the balance yourself once at Accounts"),
        ],
        visual: <BunqExport />,
      },
      { ...UPLOAD, title: tr("Step 2: Upload them at Update"), visual: <UpdateBank bank="bunq" /> },
    ],
  },
];

// ---------------------------------------------------------------- balance and labelling

function EnterBalance() {
  return (
    <MockBrowser url={tr("this app · Accounts")}>
      <div className="flex items-center justify-between border-b border-black/10 pb-1.5">
        <span><b>bunq ···7092</b> <span className="text-black/45">bank</span></span>
        <span className="text-black/40">–</span>
      </div>
      <div className="mt-2 grid grid-cols-[1fr_1fr_auto] items-end gap-2">
        <MockField label={tr("Date")} value="today" />
        <MockField label={tr("Balance")} value="2.345,67" mark />
        <MockButton colour={APP}>{tr("Save")}</MockButton>
      </div>
    </MockBrowser>
  );
}

function Labelling() {
  return (
    <MockBrowser url={tr("this app · Spending → To label")}>
      <p className="mb-2 font-semibold">{tr("Without a category yet")}</p>
      {[["STICHTING MOLLIE PAYMENTS", "7× · €818,79"], ["KAPSALON DE SCHAAR", "5× · €125,00"]].map(([name, meta], i) => (
        <div key={name} className="flex items-center justify-between gap-2 border-t border-black/10 py-1.5">
          <span className="min-w-0 truncate">▸ {name} <span className="text-black/45">{meta}</span></span>
          {i === 1 ? <Mark>{tr("Personal care ▾")}</Mark> : <span className="rounded border border-black/15 px-1.5">{tr("Choose… ▾")}</span>}
        </div>
      ))}
      <div className="mt-1.5 text-right"><MockButton colour={APP}>{tr("Make rule")}</MockButton></div>
    </MockBrowser>
  );
}

export const ENTER_BALANCE: Step = {
  title: tr("Set a balance for each account"),
  intro: <>{tr("Under Accounts → Update balance, today's balance is all you need. The app works out the rest from your transactions.")}</>,
  bullets: [
    tr("A connected bank, or an ING export with semicolons, fills in the balance for you"),
    tr("An account without a balance isn't counted in your net worth: unknown isn't the same as zero"),
  ],
  visual: <EnterBalance />,
};

export const LABELLING: Step = {
  title: tr("Label anything the app doesn't recognise"),
  intro: <>{tr("Most transactions are categorised automatically. The rest wait under Spending → To label, grouped by counterparty: pick a category and a rule applies it to your whole history.")}</>,
  bullets: [
    tr("Click a name to see its transactions and label them one by one"),
    tr("For one-offs, like a holiday with friends or a gift, select the transactions under Transactions and label them together"),
  ],
  visual: <Labelling />,
};
