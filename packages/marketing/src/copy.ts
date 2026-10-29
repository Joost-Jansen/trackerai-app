// Everything the front door says, in English and Dutch. Only what the apps
// really do: check a claim against the code before adding it here.

import type { BrandId, Locale } from "./brands";

export type Feature = { icon: IconName; title: string; text: string };
export type IconName =
  | "sync"
  | "heart"
  | "trend"
  | "route"
  | "plan"
  | "chat"
  | "networth"
  | "spending"
  | "tag"
  | "bank"
  | "portfolio"
  | "calendar"
  | "lock"
  | "key"
  | "download"
  | "code";

type BrandCopy = {
  kicker: string;
  title: string;
  lead: string;
  points: string[];
  features: Feature[];
  privacy: string[];
};

type Copy = {
  nav: { health: string; wealth: string; login: string };
  hero: { eyebrow: string; title: string; lead: string; health: string; wealth: string };
  brands: Record<BrandId, BrandCopy>;
  open: string;
  more: string;
  createAccount: string;
  shared: { eyebrow: string; title: string; items: Feature[] };
  start: { eyebrow: string; title: string; steps: { title: string; text: string }[] };
  closing: { title: string; lead: string };
  account: {
    username: string;
    password: string;
    code: string;
    codeHint: string;
    remember: string;
    submit: string;
    working: string;
    failed: string;
    noAccount: string;
    twoStep: string;
    loggedIn: string;
    start: string;
    logout: string;
    emailCode: string;
    emailHint: string;
    emailInstead: string;
    emailAgain: string;
    signup: string;
    haveAccount: string;
    name: string;
    email: string;
    emailNote: string;
    choose: string;
    chooseHint: string;
    consentBefore: string;
    consentLink: string;
    consentAfter: string;
    invite: string;
    create: string;
    closed: string;
    admin: string;
    confirmTitle: string;
    confirmText: string;
    confirm: string;
    sendAgain: string;
    wrongAddress: string;
    sendHere: string;
    sent: string;
    forgot: string;
    forgotIntro: string;
    forgotLogin: string;
    forgotSend: string;
    forgotSent: string;
    forgotAgain: string;
    forgotResent: string;
    newPassword: string;
    newPasswordHint: string;
    resetSubmit: string;
    resetDone: string;
    resetInvalid: string;
    backToLogin: string;
  };
  footer: { made: string; privacy: string; language: string };
  visual: { health: string; wealth: string };
};

const en: Copy = {
  nav: { health: "Health", wealth: "Wealth", login: "Log in" },
  hero: {
    eyebrow: "trackerai",
    title: "Your health and your wealth. Measured, understood, yours.",
    lead: "Two calm, private trackers that do the bookkeeping of your life for you: one for training, sleep and recovery, one for your money and net worth. Bring in your data once, and ask your own agent about it whenever you like.",
    health: "Explore health-tracker",
    wealth: "Explore wealth-tracker",
  },
  brands: {
    health: {
      kicker: "health-tracker",
      title: "Train with your own numbers.",
      lead: "Your sessions, sleep and recovery come in by themselves, and everything is worked out with your own heart-rate zones, not a generic formula.",
      points: [
        "Garmin and Wahoo sync every morning; Apple Watch by upload",
        "Every session with map, heart rate and splits",
        "A plan that shows what you did and missed",
      ],
      features: [
        {
          icon: "sync",
          title: "In by itself",
          text: "Garmin, and Wahoo for rides, sync every morning; the first time it fetches the past year. Apple Watch: upload your Apple Health export.",
        },
        {
          icon: "heart",
          title: "Your own zones",
          text: "Set your max heart rate per sport, and every session, trend and plan uses your five zones. A run straight after a swim or ride counts as one multisport session.",
        },
        {
          icon: "trend",
          title: "Trends that mean something",
          text: "Recovery and readiness today; form, volume, pace at a low heart rate and your records over weeks and months.",
        },
        { icon: "route", title: "Loops", text: "Your regular routes, and a fresh loop for any distance you want to run or ride." },
        {
          icon: "plan",
          title: "A plan next to reality",
          text: "A training plan per day, with what you did, what you missed and whether you were in the right zone.",
        },
        {
          icon: "chat",
          title: "Your agent as coach",
          text: "Connect your own AI agent: it reads your training, writes analyses and plans, and keeps your log. No premium subscription needed to talk to your own data.",
        },
      ],
      privacy: [
        "Your Garmin password goes only to Garmin; the site keeps an encrypted session",
        "Two-step login, and export or delete your account yourself",
      ],
    },
    wealth: {
      kicker: "wealth-tracker",
      title: "See where your money goes, and what it becomes.",
      lead: "Your bank accounts, spending, debts and investments together, so your net worth is one number you understand: what you saved, what the market did, and what you paid off.",
      points: ["Net worth, month by month, explained", "Spending per category, with budgets", "Your DeGiro portfolio counted in"],
      features: [
        {
          icon: "bank",
          title: "Your bank, in by itself",
          text: "A read-only bank connection keeps your transactions and balances up to date; it can never pay. Or upload exports from ING or bunq.",
        },
        {
          icon: "portfolio",
          title: "Investments included",
          text: "Upload your DeGiro export: what you own, its return next to the market, dividends, allocation and a rebalancing helper.",
        },
        {
          icon: "networth",
          title: "Net worth, explained",
          text: "Every month's change split into saved, market, bank and cash, and debt.",
        },
        {
          icon: "spending",
          title: "Spending and budgets",
          text: "Where your money goes per category, with budgets you can hold yourself to and fixed costs. Most transactions are categorised automatically; label the rest once and a rule remembers it.",
        },
        {
          icon: "calendar",
          title: "Months that fit your life",
          text: "Count months from salary to salary, so a month is the money you actually had. Pay for friends or a partner, and only your own share counts as spending.",
        },
        {
          icon: "chat",
          title: "Your agent as bookkeeper",
          text: "Connect your own AI agent: it reads your overview, spending and portfolio, and when you allow it, labels transactions and sets budgets.",
        },
      ],
      privacy: [
        "The bank connection can only read, never pay",
        "Keys stored encrypted; two-step login; export or delete your account yourself",
      ],
    },
  },
  open: "Open {name}",
  more: "Learn more",
  createAccount: "Create an account",
  shared: {
    eyebrow: "Both trackers",
    title: "Built the same careful way.",
    items: [
      {
        icon: "chat",
        title: "Your own agent",
        text: "Connect any AI agent that supports MCP, such as Claude, with a token you control: read-only, or allowed to write too.",
      },
      {
        icon: "download",
        title: "No lock-in",
        text: "Your dashboards live here, not inside a chat app. Switch agents, or use none at all: your pages and history stay.",
      },
      {
        icon: "sync",
        title: "Little to maintain",
        text: "Data comes in by itself where it can, a simple upload where it can't, and the apps tell you when something needs a hand.",
      },
      {
        icon: "key",
        title: "One secure sign-in",
        text: "One account for every tracker. Two-step login by app or email code; stay logged in for 30 days on your own devices.",
      },
      {
        icon: "lock",
        title: "Private by design",
        text: "Your data lives in your own account, apart from everyone else's. It is never sold, only shared with services you connect yourself, and you can export or delete it any time.",
      },
      {
        icon: "code",
        title: "Open code, run it yourself",
        text: "Both trackers are open source, so anyone can check exactly what they do with your data. Or host them yourself, on your own server or a mini PC at home.",
      },
    ],
  },
  start: {
    eyebrow: "Getting started",
    title: "Up and running in minutes.",
    steps: [
      { title: "Create your account", text: "Here on trackerai.nl, and choose health, wealth or both. You can add the other later." },
      {
        title: "Bring in your data",
        text: "Connect Garmin, Wahoo or your bank; upload your Apple Health or DeGiro export. A short tour walks you through it, with example data so you can look around first.",
      },
      { title: "See and ask", text: "Your pages fill themselves. Ask your own agent about them whenever you like." },
    ],
  },
  closing: { title: "Ready when you are.", lead: "Log in once: your trackerai account opens every tracker you use." },
  account: {
    username: "Username",
    password: "Password",
    code: "Code from your authenticator app",
    codeHint: "Or one of your backup codes.",
    remember: "Stay logged in for {days} days",
    submit: "Log in",
    working: "Working…",
    failed: "That didn't work. Try again.",
    noAccount: "No account yet?",
    twoStep: "How does two-step login work?",
    loggedIn: "Logged in as {name}",
    start: "Start with {name}",
    logout: "Log out",
    emailCode: "Code from the email",
    emailHint: "We sent it to {to}. It works for 10 minutes.",
    emailInstead: "Email me a code instead",
    emailAgain: "Send a new code",
    signup: "Create a trackerai account",
    haveAccount: "Already have an account? Log in",
    name: "Your name",
    email: "Email address",
    emailNote: "We send a code to confirm it; it also becomes your two-step login.",
    choose: "Which trackers do you want to use?",
    chooseHint: "Pick one or both. You can add the other later.",
    consentBefore:
      "I consent to the processing of my health data (workouts, heart rate, sleep and recovery) to show me my own overview, as described in the ",
    consentLink: "privacy statement",
    consentAfter: ". I can withdraw it at any time by deleting my account.",
    invite: "Invitation code",
    create: "Create account",
    closed: "Signing up is closed right now.",
    confirmTitle: "Confirm your email",
    confirmText:
      "We sent a code to {to}. Enter it to continue. From then on, logging in mails you a code too: that is your two-step login.",
    admin: "Admin",
    confirm: "Confirm",
    sendAgain: "Send the code again",
    wrongAddress: "Wrong address?",
    sendHere: "Send the code here",
    sent: "Sent to {to}.",
    forgot: "Forgot password?",
    forgotIntro: "Enter your username or email address: we email a code to that account's confirmed address.",
    forgotLogin: "Username or email address",
    forgotSend: "Send code",
    forgotSent: "If an account with that name or address has a confirmed email, a code is on its way. It works for 10 minutes.",
    forgotAgain: "Send a new code",
    forgotResent: "A new code is on its way, if the account has a confirmed email. Only the newest one works.",
    newPassword: "New password",
    newPasswordHint: "At least 10 characters.",
    resetSubmit: "Set new password",
    resetDone: "Your password is changed, and every device is logged out. Log in with your new password.",
    resetInvalid: "That code is not correct or no longer works. Ask for a new one.",
    backToLogin: "Back to log in",
  },
  footer: { made: "trackerai: health-tracker and wealth-tracker", privacy: "Privacy", language: "Language" },
  visual: { health: "Illustration of the health-tracker Today page", wealth: "Illustration of the wealth-tracker net worth page" },
};

const nl: Copy = {
  nav: { health: "Gezondheid", wealth: "Vermogen", login: "Inloggen" },
  hero: {
    eyebrow: "trackerai",
    title: "Je gezondheid en je vermogen. Gemeten, begrepen, van jou.",
    lead: "Twee rustige, privé trackers die de boekhouding van je leven voor je doen: één voor training, slaap en herstel, één voor je geld en vermogen. Zet je gegevens er één keer in, en vraag je eigen agent erover wanneer je wilt.",
    health: "Bekijk health-tracker",
    wealth: "Bekijk wealth-tracker",
  },
  brands: {
    health: {
      kicker: "health-tracker",
      title: "Train met je eigen cijfers.",
      lead: "Je trainingen, slaap en herstel komen vanzelf binnen, en alles wordt berekend met je eigen hartslagzones, niet met een algemene formule.",
      points: [
        "Garmin en Wahoo synchroniseren elke ochtend; Apple Watch via upload",
        "Elke training met kaart, hartslag en splits",
        "Een schema dat laat zien wat je deed en miste",
      ],
      features: [
        {
          icon: "sync",
          title: "Komt vanzelf binnen",
          text: "Garmin, en Wahoo voor ritten, synchroniseren elke ochtend; de eerste keer haalt hij het afgelopen jaar op. Apple Watch: upload je Apple Health-export.",
        },
        {
          icon: "heart",
          title: "Je eigen zones",
          text: "Stel je maximale hartslag per sport in, en elke training, trend en planning gebruikt jouw vijf zones. Een run direct na zwemmen of fietsen telt als één multisporttraining.",
        },
        {
          icon: "trend",
          title: "Trends die iets zeggen",
          text: "Herstel en paraatheid vandaag; vorm, volume, tempo bij lage hartslag en je records over weken en maanden.",
        },
        { icon: "route", title: "Rondjes", text: "Je vaste routes, en een nieuw rondje voor elke afstand die je wilt lopen of fietsen." },
        {
          icon: "plan",
          title: "Een schema naast de werkelijkheid",
          text: "Een trainingsschema per dag, met wat je deed, wat je miste en of je in de juiste zone zat.",
        },
        {
          icon: "chat",
          title: "Je agent als coach",
          text: "Koppel je eigen AI-agent: hij leest je trainingen, schrijft analyses en schema's en houdt je logboek bij. Geen premium-abonnement nodig om met je eigen data te praten.",
        },
      ],
      privacy: [
        "Je Garmin-wachtwoord gaat alleen naar Garmin; de site bewaart een versleutelde sessie",
        "Inloggen in twee stappen, en je account zelf exporteren of verwijderen",
      ],
    },
    wealth: {
      kicker: "wealth-tracker",
      title: "Zie waar je geld heen gaat, en wat het wordt.",
      lead: "Je rekeningen, uitgaven, schulden en beleggingen bij elkaar, zodat je vermogen één getal is dat je begrijpt: wat je spaarde, wat de markt deed en wat je afloste.",
      points: ["Vermogen per maand, uitgelegd", "Uitgaven per categorie, met budgetten", "Je DeGiro-portefeuille telt mee"],
      features: [
        {
          icon: "bank",
          title: "Je bank, vanzelf",
          text: "Een bankkoppeling die alleen kan lezen houdt je transacties en saldi bij; betalen kan hij nooit. Of upload exports van ING of bunq.",
        },
        {
          icon: "portfolio",
          title: "Beleggingen erbij",
          text: "Upload je DeGiro-export: wat je bezit, je rendement naast de markt, dividend, spreiding en een hulp bij herbalanceren.",
        },
        {
          icon: "networth",
          title: "Vermogen, uitgelegd",
          text: "De verandering van elke maand gesplitst in gespaard, markt, bank en contant, en schuld.",
        },
        {
          icon: "spending",
          title: "Uitgaven en budgetten",
          text: "Waar je geld heen gaat per categorie, met budgetten waar je je aan kunt houden en vaste lasten. De meeste transacties krijgen vanzelf een categorie; label de rest één keer en een regel onthoudt het.",
        },
        {
          icon: "calendar",
          title: "Maanden die bij je leven passen",
          text: "Tel maanden van salaris tot salaris, zodat een maand het geld is dat je echt had. Betaal je voor vrienden of een partner, dan telt alleen je eigen deel als uitgave.",
        },
        {
          icon: "chat",
          title: "Je agent als boekhouder",
          text: "Koppel je eigen AI-agent: hij leest je overzicht, uitgaven en portefeuille, en als je het toestaat labelt hij transacties en stelt hij budgetten in.",
        },
      ],
      privacy: [
        "De bankkoppeling kan alleen lezen, nooit betalen",
        "Sleutels versleuteld opgeslagen; inloggen in twee stappen; je account zelf exporteren of verwijderen",
      ],
    },
  },
  open: "Open {name}",
  more: "Meer weten",
  createAccount: "Account aanmaken",
  shared: {
    eyebrow: "Beide trackers",
    title: "Op dezelfde zorgvuldige manier gebouwd.",
    items: [
      {
        icon: "chat",
        title: "Je eigen agent",
        text: "Koppel elke AI-agent die MCP ondersteunt, zoals Claude, met een token dat jij beheert: alleen lezen, of ook schrijven.",
      },
      {
        icon: "download",
        title: "Niet vast aan één aanbieder",
        text: "Je dashboards staan hier, niet in een chat-app. Wissel van agent of gebruik er geen: je pagina's en geschiedenis blijven.",
      },
      {
        icon: "sync",
        title: "Weinig onderhoud",
        text: "Gegevens komen waar het kan vanzelf binnen, met een eenvoudige upload waar dat niet kan, en de apps zeggen het als iets je hulp nodig heeft.",
      },
      {
        icon: "key",
        title: "Eén veilige inlog",
        text: "Eén account voor elke tracker. Inloggen in twee stappen met een app of een code per e-mail; 30 dagen ingelogd blijven op je eigen apparaten.",
      },
      {
        icon: "lock",
        title: "Privé vanaf de basis",
        text: "Je gegevens staan in je eigen account, los van die van anderen. Ze worden nooit verkocht, alleen gedeeld met diensten die je zelf koppelt, en je kunt ze altijd exporteren of verwijderen.",
      },
      {
        icon: "code",
        title: "Open code, zelf te draaien",
        text: "Beide trackers zijn open source, dus iedereen kan nagaan wat ze precies met je gegevens doen. Of draai ze zelf, op je eigen server of een mini-pc thuis.",
      },
    ],
  },
  start: {
    eyebrow: "Aan de slag",
    title: "In een paar minuten op weg.",
    steps: [
      { title: "Maak je account", text: "Hier op trackerai.nl, en kies health, wealth of allebei. De andere kun je later toevoegen." },
      {
        title: "Haal je data binnen",
        text: "Koppel Garmin, Wahoo of je bank; upload je Apple Health- of DeGiro-export. Een korte rondleiding helpt je op weg, met voorbeeldgegevens zodat je eerst kunt rondkijken.",
      },
      { title: "Bekijk en vraag", text: "Je pagina's vullen zichzelf. Vraag je eigen agent erover wanneer je wilt." },
    ],
  },
  closing: { title: "Klaar wanneer jij het bent.", lead: "Log één keer in: je trackerai-account opent elke tracker die je gebruikt." },
  account: {
    username: "Gebruikersnaam",
    password: "Wachtwoord",
    code: "Code uit je authenticator-app",
    codeHint: "Of een van je reservecodes.",
    remember: "{days} dagen ingelogd blijven",
    submit: "Inloggen",
    working: "Bezig…",
    failed: "Dat lukte niet. Probeer het opnieuw.",
    noAccount: "Nog geen account?",
    twoStep: "Hoe werkt inloggen in twee stappen?",
    loggedIn: "Ingelogd als {name}",
    start: "Begin met {name}",
    logout: "Uitloggen",
    emailCode: "Code uit de e-mail",
    emailHint: "We hebben hem gestuurd naar {to}. Hij werkt 10 minuten.",
    emailInstead: "Stuur me liever een code per e-mail",
    emailAgain: "Stuur een nieuwe code",
    signup: "Maak een trackerai-account",
    haveAccount: "Heb je al een account? Log in",
    name: "Je naam",
    email: "E-mailadres",
    emailNote: "We sturen een code om het te bevestigen; het wordt ook je inloggen in twee stappen.",
    choose: "Welke trackers wil je gebruiken?",
    chooseHint: "Kies er een of allebei. De andere kun je later toevoegen.",
    consentBefore:
      "Ik geef toestemming voor het verwerken van mijn gezondheidsgegevens (trainingen, hartslag, slaap en herstel) om mijn eigen overzicht te tonen, zoals beschreven in de ",
    consentLink: "privacyverklaring",
    consentAfter: ". Intrekken kan altijd door je account te verwijderen.",
    invite: "Uitnodigingscode",
    create: "Account aanmaken",
    closed: "Aanmelden staat op dit moment dicht.",
    confirmTitle: "Bevestig je e-mailadres",
    confirmText:
      "We hebben een code gestuurd naar {to}. Vul die in om verder te gaan. Daarna mailt het inloggen je ook een code: dat is je inloggen in twee stappen.",
    admin: "Beheer",
    confirm: "Bevestigen",
    sendAgain: "Stuur de code opnieuw",
    wrongAddress: "Verkeerd adres?",
    sendHere: "Stuur de code hierheen",
    sent: "Verstuurd naar {to}.",
    forgot: "Wachtwoord vergeten?",
    forgotIntro: "Vul je gebruikersnaam of e-mailadres in: we mailen een code naar het bevestigde adres van dat account.",
    forgotLogin: "Gebruikersnaam of e-mailadres",
    forgotSend: "Stuur code",
    forgotSent:
      "Als er een account met die naam of dat adres is met een bevestigd e-mailadres, is er een code onderweg. Hij werkt 10 minuten.",
    forgotAgain: "Stuur een nieuwe code",
    forgotResent: "Er is een nieuwe code onderweg, als het account een bevestigd e-mailadres heeft. Alleen de nieuwste werkt.",
    newPassword: "Nieuw wachtwoord",
    newPasswordHint: "Minstens 10 tekens.",
    resetSubmit: "Nieuw wachtwoord instellen",
    resetDone: "Je wachtwoord is gewijzigd en elk apparaat is uitgelogd. Log in met je nieuwe wachtwoord.",
    resetInvalid: "Die code klopt niet of werkt niet meer. Vraag een nieuwe aan.",
    backToLogin: "Terug naar inloggen",
  },
  footer: { made: "trackerai: health-tracker en wealth-tracker", privacy: "Privacy", language: "Taal" },
  visual: {
    health: "Illustratie van de Vandaag-pagina van health-tracker",
    wealth: "Illustratie van de vermogenspagina van wealth-tracker",
  },
};

export const COPY: Record<Locale, Copy> = { en, nl };
