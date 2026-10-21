// The DeGiro exports as a step-by-step plan: DeGiro's screens redrawn (fixed
// light colours, no theme — they are images of DeGiro, not of this app), and the
// steps for computer and phone. Those two routes barely resemble each other: on
// the computer the menu is on the left, in the app at the bottom, and on a phone
// you then still have to find the file back in Downloads.
//
// Used by Help → Portfolio, the tour and Update; see StepPlan.tsx.

import { CalendarIcon, ChevronRightIcon, DownloadIcon, FolderIcon, InboxIcon, UploadIcon } from "@trackerai/ui/icons";
import type { Route } from "./StepPlan";
import { tr } from "@/lib/i18n";

// A tiny "browser window" chrome around each mock screen — fixed light
// colours throughout, since it is illustrating DeGiro's own (light-only) UI
// rather than this app's themed surface.
function MockWindow({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-black/10 bg-white text-[#1a1a1a] shadow-sm">
      <div className="flex items-center gap-1.5 border-b border-black/10 bg-[#f5f6f8] px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-[#ff5f57]" />
        <span className="h-2 w-2 rounded-full bg-[#febc2e]" />
        <span className="h-2 w-2 rounded-full bg-[#28c840]" />
        <span className="ml-2 truncate text-[10px] text-black/40">trader.degiro.nl</span>
      </div>
      {children}
    </div>
  );
}

function Highlight({ children, active = true }: { children: React.ReactNode; active?: boolean }) {
  return <span className={`rounded-[4px] px-1.5 py-0.5 ${active ? "bg-[#fce97a]/70 ring-1 ring-[#e0b400]" : ""}`}>{children}</span>;
}

function MockSidebar({ activeInbox }: { activeInbox: boolean }) {
  const items = ["Markt", "Favorieten", "Portefeuille", "Inbox", "Producten"];
  return (
    <div className="flex w-[74px] flex-none flex-col items-center gap-3 bg-[#0b1830] py-3">
      {items.map((label) => (
        <div key={label} className="flex flex-col items-center gap-1">
          {label === "Inbox" ? (
            <span
              className={`grid h-6 w-6 place-items-center rounded-md ${
                activeInbox ? "bg-[#fce97a] text-[#0b1830] ring-2 ring-[#e0b400]" : "text-white/50"
              }`}
            >
              <InboxIcon className="h-3.5 w-3.5" />
            </span>
          ) : (
            <span className="h-2 w-2 rounded-full bg-white/25" />
          )}
          <span className={`text-[7px] leading-none ${label === "Inbox" && activeInbox ? "font-bold text-[#fce97a]" : "text-white/40"}`}>
            {label}
          </span>
        </div>
      ))}
    </div>
  );
}

function MockTabBar({ active }: { active: "Transacties" | "Rekeningoverzicht" }) {
  const tabs = ["Berichten", "Orders", "Transacties", "Rekeningoverzicht", "Documenten"];
  return (
    <div className="flex gap-3 border-b border-black/10 px-3 pt-2 text-[9px]">
      {tabs.map((tab) => (
        <span
          key={tab}
          className={`whitespace-nowrap pb-1.5 ${
            tab === active ? "border-b-2 border-[#0057ff] font-bold text-[#0057ff]" : "text-black/40"
          }`}
        >
          {tab}
        </span>
      ))}
    </div>
  );
}

function MockExportScreen({ tab }: { tab: "Transacties" | "Rekeningoverzicht" }) {
  return (
    <MockWindow>
      <div className="flex">
        <MockSidebar activeInbox />
        <div className="min-w-0 flex-1">
          <MockTabBar active={tab} />
          <div className="flex items-center justify-between gap-2 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 rounded border border-black/15 px-1.5 py-1 text-[8.5px] text-black/70">
                <CalendarIcon className="h-2.5 w-2.5" />
                <Highlight>Begindatum</Highlight>
              </span>
              <span className="flex items-center gap-1 rounded border border-black/15 px-1.5 py-1 text-[8.5px] text-black/70">
                <CalendarIcon className="h-2.5 w-2.5" />
                Einddatum
              </span>
            </div>
            <span className="grid h-5 w-5 flex-none place-items-center rounded-full ring-2 ring-[#e0b400]">
              <DownloadIcon className="h-3 w-3 text-[#0057ff]" />
            </span>
          </div>
          <div className="space-y-1 px-3 pb-3">
            <div className="h-2 w-full rounded-sm bg-black/5" />
            <div className="h-2 w-5/6 rounded-sm bg-black/5" />
            <div className="h-2 w-4/6 rounded-sm bg-black/5" />
          </div>
        </div>
      </div>
    </MockWindow>
  );
}

function MockInboxMenu() {
  const items = ["Berichten", "Orders", "Transacties", "Rekeningoverzicht", "Waardedaling Portefeuille", "Documenten"];
  return (
    <MockWindow>
      <div className="flex">
        <MockSidebar activeInbox />
        <div className="min-w-0 flex-1 px-3 py-2.5">
          <div className="mb-2 text-[10px] font-bold">Inbox</div>
          <div className="flex flex-col gap-1.5">
            {items.map((item) => (
              <span
                key={item}
                className={`text-[8.5px] ${
                  item === "Transacties" || item === "Rekeningoverzicht" ? "font-bold text-[#0057ff]" : "text-black/60"
                }`}
              >
                {item === "Transacties" || item === "Rekeningoverzicht" ? <Highlight>{item}</Highlight> : item}
              </span>
            ))}
          </div>
        </div>
      </div>
    </MockWindow>
  );
}

// ---------------------------------------------------------------- phone ---
// The DeGiro app, not the website: a blue bar on top, the section tabs under
// it, and the app's own navigation along the bottom.

function MockPhone({ children, bottomBar = true }: { children: React.ReactNode; bottomBar?: boolean }) {
  const tabs = ["Markt", "Favorieten", "Portefeuille", "Inbox"];
  return (
    <div className="mx-auto w-[190px] overflow-hidden rounded-[16px] border border-black/15 bg-white text-[#1a1a1a] shadow-sm">
      <div className="flex items-center justify-between bg-[#0a95d9] px-2.5 py-1.5">
        <span className="flex flex-col gap-[2px]">
          {[0, 1, 2].map((i) => (
            <span key={i} className="h-[1.5px] w-2.5 rounded-full bg-white/90" />
          ))}
        </span>
        <span className="text-[7px] text-white/90">0 Openstaand, 0 Uitgevoerd</span>
      </div>
      {children}
      {bottomBar && (
        <div className="flex items-end justify-between bg-[#1e2a38] px-2 py-1.5">
          {tabs.map((label) => (
            <span key={label} className="flex flex-col items-center gap-0.5">
              <span
                className={`grid h-3.5 w-3.5 place-items-center rounded ${
                  label === "Inbox" ? "bg-[#fce97a] text-[#1e2a38] ring-2 ring-[#e0b400]" : "text-white/40"
                }`}
              >
                {label === "Inbox" ? <InboxIcon className="h-2.5 w-2.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-white/25" />}
              </span>
              <span className={`text-[6px] leading-none ${label === "Inbox" ? "font-bold text-[#fce97a]" : "text-white/40"}`}>{label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function MockMobileTabBar({ active }: { active: "Transacties" | "Rekeningoverzicht" }) {
  // The app's tab strip scrolls, and it scrolls the tab you picked into view —
  // so the two screens genuinely show different neighbours. Mirroring that
  // also keeps the highlighted tab off the clipped right edge.
  const tabs =
    active === "Transacties"
      ? ["Berichten", "Orders", "Transacties", "Rekeningoverzicht"]
      : ["Rekeningoverzicht", "Waardedaling", "Documenten"];
  return (
    <div className="flex gap-2 overflow-hidden border-b border-black/10 px-2 pt-1.5 text-[7px]">
      {tabs.map((tab) => (
        <span
          key={tab}
          className={`whitespace-nowrap pb-1 ${tab === active ? "border-b-2 border-[#0057ff] font-bold text-[#0057ff]" : "text-black/40"}`}
        >
          {tab === active ? <Highlight>{tab}</Highlight> : tab}
        </span>
      ))}
    </div>
  );
}

/** Step 1 on a phone: the whole point is the Inbox button in the bottom bar. */
function MockMobileInbox() {
  return (
    <MockPhone>
      <div className="space-y-1.5 px-2.5 py-2.5">
        <div className="h-2.5 w-full rounded-sm bg-black/[0.06]" />
        {[45, 32, 40, 28].map((w, i) => (
          <div key={i} className="flex items-center justify-between gap-2">
            <div className="h-2 rounded-sm bg-black/5" style={{ width: `${w}%` }} />
            <div className="h-2 w-8 rounded-sm bg-black/5" />
          </div>
        ))}
      </div>
    </MockPhone>
  );
}

function MockMobileExport({ tab }: { tab: "Transacties" | "Rekeningoverzicht" }) {
  return (
    <MockPhone>
      <MockMobileTabBar active={tab} />
      <div className="px-2.5 py-2">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="truncate text-[9px] font-bold">{tab}</span>
          <span className="grid h-4 w-4 flex-none place-items-center rounded-full ring-2 ring-[#e0b400]">
            <DownloadIcon className="h-2.5 w-2.5 text-[#0057ff]" />
          </span>
        </div>
        <div className="flex gap-1.5">
          {["Begindatum", "Einddatum"].map((label, i) => (
            <span
              key={label}
              className="flex flex-1 items-center gap-1 rounded-full border border-black/15 px-1.5 py-1 text-[6.5px] text-black/70"
            >
              <CalendarIcon className="h-2 w-2 flex-none" />
              {i === 0 ? <Highlight>{label}</Highlight> : label}
            </span>
          ))}
        </div>
        <div className="mt-1.5 flex gap-1 rounded bg-[#1e2a38] px-1.5 py-1 text-[6px] text-white/50">
          <span>7 dagen</span>
          <span className="font-bold text-white">Maand</span>
          <span>3 maanden</span>
        </div>
        <div className="mt-1.5 space-y-1">
          <div className="h-2 w-full rounded-sm bg-black/5" />
          <div className="h-2 w-4/6 rounded-sm bg-black/5" />
        </div>
      </div>
    </MockPhone>
  );
}

/** The step the desktop route has no equivalent for: where the file went. */
function MockFilesApp() {
  const files = [
    { name: "Transactions.xlsx", highlight: true },
    { name: "Account.xlsx", highlight: true },
    { name: "Schermafbeelding", highlight: false },
  ];
  return (
    <div className="mx-auto w-[190px] overflow-hidden rounded-[16px] border border-black/15 bg-[#f2f2f7] text-[#1a1a1a] shadow-sm">
      <div className="flex items-center justify-center gap-1 border-b border-black/10 bg-white px-2.5 py-2">
        <FolderIcon className="h-3 w-3 text-[#0a84ff]" />
        <span className="text-[9px] font-bold">Downloads</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 p-2.5">
        {files.map((f) => (
          <span key={f.name} className="flex flex-col items-center gap-1">
            <span
              className={`h-8 w-7 rounded-[3px] border bg-white ${
                f.highlight ? "border-[#e0b400] ring-2 ring-[#e0b400]" : "border-black/15"
              }`}
            />
            <span className="w-full truncate text-center text-[5.5px] text-black/60">{f.name}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function MockUploadStep() {
  return (
    <div className="space-y-2 rounded-lg border border-black/10 bg-white p-3 text-[#1a1a1a] shadow-sm">
      <div className="text-[10px] font-semibold">{tr("Update data")}</div>
      {(["Transacties", "Rekeningoverzicht"] as const).map((label) => (
        <div key={label} className="flex items-center gap-2 rounded-md border-[1.5px] border-dashed border-[#e0b400] bg-[#fce97a]/25 p-2">
          <span className="grid h-6 w-6 flex-none place-items-center rounded-md bg-black/5 text-black/50">
            <UploadIcon className="h-3.5 w-3.5" />
          </span>
          <span className="text-[9px] font-semibold">{label}</span>
        </div>
      ))}
    </div>
  );
}

type Step = {
  title: string;
  intro: string;
  bullets: string[];
  visual: React.ReactNode;
};

export const MOBILE_STEPS: Step[] = [
  {
    title: tr("Step 1: Open your Inbox in the DeGiro app"),
    intro: tr("Tap Inbox in the bar at the bottom. That's the same place where your messages are."),
    bullets: [tr("Then tap the Transacties (Transactions) tab at the top"), tr("You'll need that tab first")],
    visual: <MockMobileInbox />,
  },
  {
    title: tr("Step 2: Export your Transactions"),
    intro: tr("Set the dates wide enough and tap the download icon at the top right."),
    bullets: [
      tr("Start date: the day of your very first purchase (or earlier), so that the first time you get your whole history"),
      tr("End date: today"),
      tr("The shortcut buttons for the last month and the last 3 months are handy, but get too little the first time"),
    ],
    visual: <MockMobileExport tab="Transacties" />,
  },
  {
    title: tr("Step 3: Export your Account statement"),
    intro: tr("Same route, other tab: Inbox → Rekeningoverzicht (Account statement)."),
    bullets: [tr("Same start and end date as for Transactions"), tr("Download this file too with the download icon")],
    visual: <MockMobileExport tab="Rekeningoverzicht" />,
  },
  {
    title: tr("Step 4: The files are now in Downloads"),
    intro: tr("Your phone keeps them in the Downloads folder, in the Files app. That's where you get them again in a moment."),
    bullets: [
      tr(
        'Had you downloaded the same file before? Then your phone adds a number, such as "Transactions.xlsx 2". The highest is the newest',
      ),
      tr("You don't need to open it. If you do, it opens read-only; that's normal and not broken"),
    ],
    visual: <MockFilesApp />,
  },
  {
    title: tr("Step 5: Upload both files here"),
    intro: tr('Go back to this app and tap "Update" at the top right.'),
    bullets: [
      tr("Tap the Transactions box and your phone opens the Files app right away"),
      tr("Go to Browse → Downloads and tap the Transactions file"),
      tr("Repeat that for the Account statement"),
      tr("Uploading again later is always fine: rows already saved are skipped"),
    ],
    visual: <MockUploadStep />,
  },
];

export const DESKTOP_STEPS: Step[] = [
  {
    title: tr("Step 1: Open your Inbox at DeGiro"),
    intro: tr("Log in at trader.degiro.nl and click Inbox in the menu on the left."),
    bullets: [tr("Then click the Transacties (Transactions) tab"), tr("You'll need that tab first")],
    visual: <MockInboxMenu />,
  },
  {
    title: tr("Step 2: Export your Transactions"),
    intro: tr("Set the dates wide enough and download the file."),
    bullets: [
      tr("Start date: the day of your very first purchase (or earlier), so that the first time you get your whole history"),
      tr("End date: today"),
      tr("Click the download icon at the top right for the .xlsx file"),
    ],
    visual: <MockExportScreen tab="Transacties" />,
  },
  {
    title: tr("Step 3: Export your Account statement"),
    intro: tr("Same route, other tab: Inbox → Rekeningoverzicht (Account statement)."),
    bullets: [tr("Same start and end date as for Transactions"), tr("Download this file as .xlsx too")],
    visual: <MockExportScreen tab="Rekeningoverzicht" />,
  },
  {
    title: tr("Step 4: Upload both files here"),
    intro: tr('Go back to this app and click "Update" at the top right.'),
    bullets: [
      tr("Drag the Transactions file to the Transactions box"),
      tr("Drag the Account statement file to the Account statement box"),
      tr("Uploading again later is always fine: rows already saved are skipped"),
    ],
    visual: <MockUploadStep />,
  },
];

export const DEGIRO_ROUTES: Route[] = [
  { id: "desktop", label: "Computer", steps: DESKTOP_STEPS },
  { id: "mobile", label: tr("Phone"), steps: MOBILE_STEPS },
];
