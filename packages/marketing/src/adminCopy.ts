// The admin page's text (Admin.tsx), in English and Dutch.

import type { Locale } from "./brands";

type AdminCopy = {
  title: string;
  back: string;
  allTrackers: (where: string) => string;
  loading: string;
  loginFirst: string;
  adminsOnly: string;
  done: string;
  on: string;
  off: string;
  days: (n: number) => string;
  modes: Record<"open" | "invite" | "closed", string>;
  policies: Record<string, string>;
  settings: { signup: string; policy: string; mail: string; stay: string; mailOff: string };
  tiles: {
    accounts: string;
    newIn30: (n: number) => string;
    users: string;
    active: string;
    last7: string;
    used7: (in30: number) => string;
    twoStep: string;
    twoStepSplit: (app: number, email: number) => string;
    attention: string;
    attentionSplit: (suspended: number, unconfirmed: number) => string;
    disk: string;
  };
  accounts: {
    title: string;
    search: string;
    who: string;
    email: string;
    trackers: string;
    twoStep: string;
    lastActive: string;
    actions: string;
    admin: string;
    suspended: string;
    unconfirmed: string;
    appAdmin: string;
    manage: string;
    manageFor: (u: string) => string;
    since: (date: string) => string;
    also: (trackers: string) => string;
  };
  bulk: {
    label: string;
    selected: (n: number) => string;
    working: (done: number, of: number) => string;
    actions: string;
    clear: string;
    pick: (u: string) => string;
    pickAll: string;
    suspend: string;
    delete: string;
    summary: (ok: number, of: number, failed: string[]) => string;
    selfSkipped: string;
    onlySelf: string;
    selfNote: string;
    notIn: (t: string) => string;
    confirmTitle: string;
    suspendText: (n: number) => string;
    takeText: (n: number, t: string) => string;
    twoStepText: (n: number) => string;
    deleteText: (n: number) => string;
    typeToDelete: (n: number) => string;
    deleteGo: (n: number) => string;
    nothing: string;
    go: string;
    cancel: string;
    betaTitle: (n: number) => string;
    tracker: string;
    feature: string;
    turnOn: string;
    turnOff: string;
  };
  twoStep: { app: string; email: string; both: string; off: string };
  menu: {
    makeAdmin: string;
    removeAdmin: string;
    suspend: string;
    unsuspend: string;
    suspendConfirm: (u: string) => string;
    give: (t: string) => string;
    take: (t: string) => string;
    takeConfirm: (u: string, t: string) => string;
    reset: string;
    resetConfirm: (u: string) => string;
    resetDone: (u: string, pw: string) => string;
    twoStepOff: string;
    twoStepConfirm: (u: string) => string;
    delete: string;
    deletePrompt: (u: string) => string;
  };
  signup: {
    title: string;
    modeText: Record<"open" | "invite" | "closed", string>;
    invites: string;
    valid: string;
    make: string;
    made: string;
    copy: string;
    revoke: string;
    none: string;
    until: (date: string) => string;
    noEnd: string;
  };
  activity: { title: string; none: string; actions: Record<string, string> };
  tabs: { overview: string; accounts: string; feedback: string; signup: string; activity: string };
  charts: { accounts: string; newTip: (n: number) => string; visits: string; users: string; feedback: string; none: string };
  hub: { notConnected: (t: string) => string; failed: (t: string) => string };
  betas: {
    menu: string;
    title: (u: string) => string;
    none: (t: string) => string;
    noUser: (t: string) => string;
    noTrackers: string;
    close: string;
  };
  feedback: {
    title: string;
    allTrackers: string;
    filter: { open: string; all: string };
    status: Record<FeedbackStatus, string>;
    statusLabel: string;
    kind: Record<"bug" | "idea", string>;
    from: (u: string) => string;
    details: string;
    version: string;
    browser: string;
    screen: string;
    errors: string;
    screenshot: string;
    replyLabel: string;
    replyPh: string;
    save: string;
    saved: string;
    none: string;
    close: string;
  };
};

export type FeedbackStatus = "new" | "planned" | "fixed" | "wontfix";

/** "1 account", "3 accounts" (the same in Dutch). */
const accounts = (n: number) => (n === 1 ? "1 account" : `${n} accounts`);

const en: AdminCopy = {
  title: "Admin",
  back: "← trackerai.nl",
  allTrackers: (w) => `All trackers: ${w}`,
  loading: "Loading…",
  loginFirst: "Log in with an admin account.",
  adminsOnly: "This page is for admins only.",
  done: "Done.",
  on: "on",
  off: "off",
  days: (n) => (n === 1 ? "1 day" : `${n} days`),
  modes: { open: "Open", invite: "Invitation only", closed: "Closed" },
  policies: {
    shared: "required for admins and for accounts with more than one tracker",
    all: "required for everyone",
    admins: "required for admins",
    off: "optional",
  },
  settings: {
    signup: "Sign-up",
    policy: "Two-step login",
    mail: "Sending mail",
    stay: "Stay logged in",
    mailOff:
      "Without mail, sign-up can't confirm an address and nobody gets codes by email: set RESEND_API_KEY and MAIL_FROM on each tracker.",
  },
  tiles: {
    accounts: "Accounts",
    newIn30: (n) => `${n} new in the last 30 days`,
    users: "accounts use it",
    active: "Active",
    last7: "logged in in the last 7 days",
    used7: (n) => `used a tracker in the last 7 days · ${n} in 30`,
    twoStep: "Two-step login",
    twoStepSplit: (app, email) => `app ${app} · email ${email}`,
    attention: "Needs attention",
    attentionSplit: (s, u) => `${s} suspended · ${u} email unconfirmed`,
    disk: "Disk use",
  },
  accounts: {
    title: "Accounts",
    search: "Search name, username or email",
    who: "Account",
    email: "Email",
    trackers: "Trackers",
    twoStep: "Two-step",
    lastActive: "Last active",
    actions: "Actions",
    admin: "admin",
    suspended: "suspended",
    unconfirmed: "not confirmed",
    appAdmin: "admin",
    manage: "Manage",
    manageFor: (u) => `Manage ${u}`,
    since: (d) => `since ${d}`,
    also: (t) => `also ${t}`,
  },
  bulk: {
    label: "Selected accounts",
    selected: (n) => `${n} selected`,
    working: (d, o) => `Working… ${d} of ${o}`,
    actions: "Actions",
    clear: "Clear",
    pick: (u) => `Select ${u}`,
    pickAll: "Select all shown",
    suspend: "Suspend…",
    delete: "Delete accounts…",
    summary: (ok, of, failed) => `Done for ${ok} of ${of}${failed.length ? `; failed: ${failed.join(", ")}` : ""}.`,
    selfSkipped: "Your own account was left out.",
    onlySelf: "Nothing done: not for your own account.",
    selfNote: "Your own account is left out.",
    notIn: (t) => `no user in ${t}`,
    confirmTitle: "Are you sure?",
    suspendText: (n) => `Suspend ${accounts(n)}? They are logged out of every tracker and can't log in until you lift it.`,
    takeText: (n, t) => `Take ${t} away from ${accounts(n)}? Their data in ${t} is deleted. This can't be undone.`,
    twoStepText: (n) => `Turn off two-step login for ${accounts(n)}? Where it is required, they set it up again at their next login.`,
    deleteText: (n) => `Deletes ${accounts(n)} and all their data in every tracker. This can't be undone.`,
    typeToDelete: (n) => `Type ${n} to delete ${accounts(n)} and all their data`,
    deleteGo: (n) => `Delete ${accounts(n)}`,
    nothing: "Nothing to change for these accounts.",
    go: "Go ahead",
    cancel: "Cancel",
    betaTitle: (n) => `Beta feature for ${accounts(n)}`,
    tracker: "Tracker",
    feature: "Feature",
    turnOn: "Turn on",
    turnOff: "Turn off",
  },
  twoStep: { app: "App", email: "Email", both: "App + email", off: "Off" },
  menu: {
    makeAdmin: "Make admin",
    removeAdmin: "Remove admin",
    suspend: "Suspend",
    unsuspend: "Lift suspension",
    suspendConfirm: (u) => `Suspend ${u}? They are logged out of every tracker and can't log in until you lift it.`,
    give: (t) => `Give ${t}`,
    take: (t) => `Take ${t} away…`,
    takeConfirm: (u, t) => `Take ${t} away from ${u}? Their data in ${t} is deleted. This can't be undone.`,
    reset: "Reset password…",
    resetConfirm: (u) => `Give ${u} a temporary password? They are logged out everywhere.`,
    resetDone: (u, pw) => `Temporary password for ${u}: ${pw}\n\nPass it on privately; they change it after logging in.`,
    twoStepOff: "Turn off two-step login…",
    twoStepConfirm: (u) =>
      `Turn off two-step login for ${u} (app and email codes)? For someone who lost their phone or mailbox; where it is required they set it up again at their next login.`,
    delete: "Delete account…",
    deletePrompt: (u) => `Deletes ${u}'s account and all its data in every tracker. Type the username to confirm:`,
  },
  signup: {
    title: "Sign-up",
    modeText: {
      open: "Anyone can create an account.",
      invite: "Only with an invitation link below. The link chooses the trackers.",
      closed: "Nobody can sign up. Existing accounts keep working.",
    },
    invites: "Invitations",
    valid: "valid for",
    make: "Make a link",
    made: "New link:",
    copy: "Copy",
    revoke: "Revoke",
    none: "No open invitations.",
    until: (d) => `until ${d}`,
    noEnd: "no end date",
  },
  activity: {
    title: "What admins did",
    none: "Nothing yet.",
    actions: {
      make_admin: "made admin",
      remove_admin: "removed admin from",
      block: "suspended",
      unblock: "lifted the suspension of",
      give_app: "gave a tracker to",
      take_app: "took a tracker from",
      app_admin: "changed the tracker admin of",
      reset_password: "reset the password of",
      reset_totp: "turned off two-step login of",
      delete_account: "deleted",
      invite: "made an invitation",
      revoke_invite: "revoked an invitation",
      registration: "set sign-up to",
    },
  },
  tabs: { overview: "Overview", accounts: "Accounts", feedback: "Feedback", signup: "Sign-up", activity: "Activity" },
  charts: {
    accounts: "Accounts",
    newTip: (n) => `${n} new that week`,
    visits: "Page visits per week",
    users: "Active users per week",
    feedback: "Feedback per week",
    none: "Nothing in the last 12 weeks.",
  },
  hub: { notConnected: (t) => `${t} isn't connected to this page.`, failed: (t) => `${t} couldn't be reached.` },
  betas: {
    menu: "Beta features…",
    title: (u) => `Beta features for ${u}`,
    none: (t) => `${t} has no beta features yet.`,
    noUser: (t) => `No user in ${t} yet.`,
    noTrackers: "This account uses no tracker.",
    close: "Close",
  },
  feedback: {
    title: "Feedback",
    allTrackers: "All",
    filter: { open: "Open", all: "All" },
    status: { new: "New", planned: "Planned", fixed: "Fixed", wontfix: "Won't do" },
    statusLabel: "Status",
    kind: { bug: "Broken", idea: "Idea" },
    from: (u) => `from ${u}`,
    details: "Details",
    version: "Version",
    browser: "Browser",
    screen: "Screen",
    errors: "Recent errors",
    screenshot: "Screenshot",
    replyLabel: "Reply to the user",
    replyPh: "Short, in their language. They see it with their feedback.",
    save: "Save",
    saved: "Saved.",
    none: "No feedback here.",
    close: "Close",
  },
};

const nl: AdminCopy = {
  title: "Beheer",
  back: "← trackerai.nl",
  allTrackers: (w) => `Alle trackers: ${w}`,
  loading: "Laden…",
  loginFirst: "Log in met een beheerdersaccount.",
  adminsOnly: "Deze pagina is alleen voor beheerders.",
  done: "Gedaan.",
  on: "aan",
  off: "uit",
  days: (n) => (n === 1 ? "1 dag" : `${n} dagen`),
  modes: { open: "Open", invite: "Alleen met uitnodiging", closed: "Dicht" },
  policies: {
    shared: "verplicht voor beheerders en accounts met meer dan één tracker",
    all: "verplicht voor iedereen",
    admins: "verplicht voor beheerders",
    off: "vrijwillig",
  },
  settings: {
    signup: "Aanmelden",
    policy: "Inloggen in twee stappen",
    mail: "Mail versturen",
    stay: "Ingelogd blijven",
    mailOff:
      "Zonder mail kan aanmelden geen adres bevestigen en krijgt niemand codes per e-mail: zet RESEND_API_KEY en MAIL_FROM op elke tracker.",
  },
  tiles: {
    accounts: "Accounts",
    newIn30: (n) => `${n} nieuw in de laatste 30 dagen`,
    users: "accounts gebruiken hem",
    active: "Actief",
    last7: "ingelogd in de laatste 7 dagen",
    used7: (n) => `gebruikten een tracker in de laatste 7 dagen · ${n} in 30`,
    twoStep: "Inloggen in twee stappen",
    twoStepSplit: (app, email) => `app ${app} · e-mail ${email}`,
    attention: "Vraagt aandacht",
    attentionSplit: (s, u) => `${s} geblokkeerd · ${u} e-mail niet bevestigd`,
    disk: "Schijfgebruik",
  },
  accounts: {
    title: "Accounts",
    search: "Zoek op naam, gebruikersnaam of e-mail",
    who: "Account",
    email: "E-mail",
    trackers: "Trackers",
    twoStep: "Twee stappen",
    lastActive: "Laatst actief",
    actions: "Acties",
    admin: "beheerder",
    suspended: "geblokkeerd",
    unconfirmed: "niet bevestigd",
    appAdmin: "beheerder",
    manage: "Beheren",
    manageFor: (u) => `${u} beheren`,
    since: (d) => `sinds ${d}`,
    also: (t) => `ook ${t}`,
  },
  bulk: {
    label: "Gekozen accounts",
    selected: (n) => `${n} gekozen`,
    working: (d, o) => `Bezig… ${d} van ${o}`,
    actions: "Acties",
    clear: "Wissen",
    pick: (u) => `${u} kiezen`,
    pickAll: "Alle getoonde kiezen",
    suspend: "Blokkeren…",
    delete: "Accounts verwijderen…",
    summary: (ok, of, failed) => `Gedaan voor ${ok} van ${of}${failed.length ? `; mislukt: ${failed.join(", ")}` : ""}.`,
    selfSkipped: "Je eigen account is overgeslagen.",
    onlySelf: "Niets gedaan: niet voor je eigen account.",
    selfNote: "Je eigen account wordt overgeslagen.",
    notIn: (t) => `geen gebruiker in ${t}`,
    confirmTitle: "Weet je het zeker?",
    suspendText: (n) => `${accounts(n)} blokkeren? Ze worden in elke tracker uitgelogd en kunnen niet inloggen tot je het opheft.`,
    takeText: (n, t) => `${t} afnemen van ${accounts(n)}? Hun gegevens in ${t} worden verwijderd. Dit kan niet ongedaan worden.`,
    twoStepText: (n) =>
      `Inloggen in twee stappen uitzetten voor ${accounts(n)}? Waar het verplicht is, stellen ze het bij de volgende keer inloggen opnieuw in.`,
    deleteText: (n) => `Verwijdert ${accounts(n)} en al hun gegevens in elke tracker. Dit kan niet ongedaan worden.`,
    typeToDelete: (n) => `Typ ${n} om ${accounts(n)} en al hun gegevens te verwijderen`,
    deleteGo: (n) => `${accounts(n)} verwijderen`,
    nothing: "Voor deze accounts valt niets te veranderen.",
    go: "Doorgaan",
    cancel: "Annuleren",
    betaTitle: (n) => `Bètafunctie voor ${accounts(n)}`,
    tracker: "Tracker",
    feature: "Functie",
    turnOn: "Aanzetten",
    turnOff: "Uitzetten",
  },
  twoStep: { app: "App", email: "E-mail", both: "App + e-mail", off: "Uit" },
  menu: {
    makeAdmin: "Beheerder maken",
    removeAdmin: "Geen beheerder meer",
    suspend: "Blokkeren",
    unsuspend: "Blokkade opheffen",
    suspendConfirm: (u) => `${u} blokkeren? Diegene wordt in elke tracker uitgelogd en kan niet inloggen tot je het opheft.`,
    give: (t) => `${t} geven`,
    take: (t) => `${t} afnemen…`,
    takeConfirm: (u, t) => `${t} afnemen van ${u}? De gegevens in ${t} worden verwijderd. Dit kan niet ongedaan worden.`,
    reset: "Wachtwoord resetten…",
    resetConfirm: (u) => `${u} een tijdelijk wachtwoord geven? Diegene wordt overal uitgelogd.`,
    resetDone: (u, pw) => `Tijdelijk wachtwoord voor ${u}: ${pw}\n\nGeef het privé door; na het inloggen kiest diegene een nieuw.`,
    twoStepOff: "Inloggen in twee stappen uitzetten…",
    twoStepConfirm: (u) =>
      `Inloggen in twee stappen uitzetten voor ${u} (app en codes per e-mail)? Voor wie telefoon of mailbox kwijt is; waar het verplicht is, stelt diegene het bij de volgende keer inloggen opnieuw in.`,
    delete: "Account verwijderen…",
    deletePrompt: (u) => `Verwijdert het account van ${u} en al zijn gegevens in elke tracker. Typ de gebruikersnaam ter bevestiging:`,
  },
  signup: {
    title: "Aanmelden",
    modeText: {
      open: "Iedereen kan een account maken.",
      invite: "Alleen met een uitnodigingslink hieronder. De link bepaalt de trackers.",
      closed: "Niemand kan zich aanmelden. Bestaande accounts blijven werken.",
    },
    invites: "Uitnodigingen",
    valid: "geldig",
    make: "Maak een link",
    made: "Nieuwe link:",
    copy: "Kopiëren",
    revoke: "Intrekken",
    none: "Geen open uitnodigingen.",
    until: (d) => `tot ${d}`,
    noEnd: "zonder einddatum",
  },
  activity: {
    title: "Wat beheerders deden",
    none: "Nog niets.",
    actions: {
      make_admin: "maakte beheerder:",
      remove_admin: "nam beheer af van",
      block: "blokkeerde",
      unblock: "hief de blokkade op van",
      give_app: "gaf een tracker aan",
      take_app: "nam een tracker af van",
      app_admin: "wijzigde trackerbeheer van",
      reset_password: "resette het wachtwoord van",
      reset_totp: "zette inloggen in twee stappen uit van",
      delete_account: "verwijderde",
      invite: "maakte een uitnodiging",
      revoke_invite: "trok een uitnodiging in",
      registration: "zette aanmelden op",
    },
  },
  tabs: { overview: "Overzicht", accounts: "Accounts", feedback: "Feedback", signup: "Aanmelden", activity: "Activiteit" },
  charts: {
    accounts: "Accounts",
    newTip: (n) => `${n} nieuw die week`,
    visits: "Paginabezoeken per week",
    users: "Actieve gebruikers per week",
    feedback: "Feedback per week",
    none: "Niets in de laatste 12 weken.",
  },
  hub: { notConnected: (t) => `${t} is niet aan deze pagina gekoppeld.`, failed: (t) => `${t} is niet bereikbaar.` },
  betas: {
    menu: "Bètafuncties…",
    title: (u) => `Bètafuncties voor ${u}`,
    none: (t) => `${t} heeft nog geen bètafuncties.`,
    noUser: (t) => `Nog geen gebruiker in ${t}.`,
    noTrackers: "Dit account gebruikt geen tracker.",
    close: "Sluiten",
  },
  feedback: {
    title: "Feedback",
    allTrackers: "Alle",
    filter: { open: "Open", all: "Alles" },
    status: { new: "Nieuw", planned: "Gepland", fixed: "Opgelost", wontfix: "Doen we niet" },
    statusLabel: "Status",
    kind: { bug: "Kapot", idea: "Idee" },
    from: (u) => `van ${u}`,
    details: "Details",
    version: "Versie",
    browser: "Browser",
    screen: "Scherm",
    errors: "Recente fouten",
    screenshot: "Screenshot",
    replyLabel: "Antwoord aan de gebruiker",
    replyPh: "Kort, in hun taal. Ze zien het bij hun feedback.",
    save: "Opslaan",
    saved: "Opgeslagen.",
    none: "Geen feedback hier.",
    close: "Sluiten",
  },
};

export const ADMIN_COPY: Record<Locale, AdminCopy> = { en, nl };
