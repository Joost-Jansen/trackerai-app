// Two-step login, explained: the help page both trackers show (health-tracker's Help and wealth-tracker's Help). It is
// one setting of the shared trackerai account, so one explanation, in Dutch and English, with its own texts: the apps'
// translation systems differ until the shared i18n package (docs/PLAN.md step 7).

type Locale = "nl" | "en";

type Section = { id: string; title: string; body: React.ReactNode };

const APPS = ["Google Authenticator", "Microsoft Authenticator", "1Password", "Bitwarden", "Aegis (Android)", "Apple Passwords (iPhone)"];

function sections(locale: Locale, days: number): { title: string; lead: string; sections: Section[] } {
  if (locale === "nl") {
    return {
      title: "Inloggen in twee stappen",
      lead: `Naast je wachtwoord vraagt het inloggen een code van zes cijfers: uit een app op je telefoon, of per e-mail. Iemand die je wachtwoord kent, komt er dan nog niet in. Het is één instelling van je trackerai-account: je stelt het één keer in en het geldt voor health-tracker, wealth-tracker en stock-tracker.`,
      sections: [
        {
          id: "why",
          title: "Waarom het soms verplicht is",
          body: (
            <p>
              Gebruik je meer dan één tracker, dan opent één wachtwoord zowel je gezondheids- als je geldgegevens. Daarom is inloggen in twee stappen dan verplicht, en ook voor beheerders. Gebruik je één tracker, dan kies je het zelf; het wordt sterk aangeraden.
            </p>
          ),
        },
        {
          id: "app",
          title: "1. Neem een authenticator-app",
          body: (
            <>
              <p>Elke app die codes maakt volgens de standaard (TOTP) werkt, bijvoorbeeld:</p>
              <ul className="ml-5 list-disc">{APPS.map((a) => <li key={a}>{a}</li>)}</ul>
              <p>Een wachtwoordmanager die ook codes bewaart is handig: die gaat mee naar een nieuwe telefoon.</p>
            </>
          ),
        },
        {
          id: "setup",
          title: "2. Instellen",
          body: (
            <ol className="ml-5 list-decimal">
              <li>Ga naar Instellingen › Account › Inloggen in twee stappen en kies Aanzetten (of volg het scherm dat erom vraagt).</li>
              <li>Scan de QR-code met je app. Lukt scannen niet, typ dan de sleutel eronder over.</li>
              <li>Vul de code van zes cijfers in die de app nu toont en bevestig.</li>
              <li>Je krijgt tien reservecodes. Bewaar ze apart van je telefoon: in een wachtwoordmanager of op papier. Ze worden maar één keer getoond.</li>
            </ol>
          ),
        },
        {
          id: "login",
          title: "3. Inloggen",
          body: (
            <>
              <p>Na je wachtwoord vraagt de site om de code die de app op dat moment toont. Elke code is 30 seconden geldig en werkt maar één keer.</p>
              <p>
                Staat <b>Ingelogd blijven</b> aan, dan blijf je {days} dagen ingelogd op dat apparaat, en vraagt het daar ook {days} dagen niet om de code: alleen om je wachtwoord als je uitlogt. Op een gedeelde of andere computer zet je het uit; dan eindigt de sessie als je de browser sluit.
              </p>
            </>
          ),
        },
        {
          id: "backup",
          title: "Reservecodes",
          body: (
            <p>
              Heb je je telefoon niet bij de hand, vul dan een reservecode in waar om de code wordt gevraagd. Elke reservecode werkt één keer. Bij Instellingen › Account zie je hoeveel je er nog hebt; daar maak je ook een nieuwe set (de oude werken dan niet meer).
            </p>
          ),
        },
        {
          id: "email",
          title: "Codes per e-mail",
          body: (
            <p>
              Heb je je aangemeld met je e-mailadres en het bevestigd met de code uit de welkomstmail, dan staat dit al aan. Anders zet je bij Instellingen › Account <b>codes per e-mail</b> aan: je vult je adres in en bevestigt het met de code die we sturen. Daarna mailt het inloggen je een code van zes cijfers; die werkt één keer, 10 minuten lang. Dat is eenvoudiger, en iets minder sterk: wie je mail kan lezen en je wachtwoord kent, komt binnen. Geef je mailbox dus een eigen sterk wachtwoord en inloggen in twee stappen. Je kunt ook allebei gebruiken: kies bij het inloggen dan &quot;Stuur me liever een code per e-mail&quot;.
            </p>
          ),
        },
        {
          id: "phone",
          title: "Een nieuwe telefoon",
          body: (
            <p>
              Zet de codes over met de app zelf (de meeste kunnen dat, of bewaren ze in je account bij die app). Lukt dat niet: log in met een reservecode, zet inloggen in twee stappen uit en meteen weer aan, en scan de nieuwe QR-code met je nieuwe telefoon. Is het verplicht voor je account, dan vraagt het scherm je na het uitzetten meteen om het opnieuw in te stellen.
            </p>
          ),
        },
        {
          id: "wrong",
          title: "De code klopt niet",
          body: (
            <ul className="ml-5 list-disc">
              <li>Neem de nieuwste code: een code verloopt na 30 seconden, en een code die al gebruikt is werkt niet nog eens.</li>
              <li>Controleer de tijd op je telefoon: die moet automatisch worden ingesteld. Een paar minuten verschil is genoeg om elke code fout te maken.</li>
              <li>Heb je meer dan één trackerai-regel in je app (bijvoorbeeld een oude van health-tracker of stock-tracker), gebruik dan die met &quot;trackerai&quot; erin; de oude kun je verwijderen.</li>
            </ul>
          ),
        },
        {
          id: "lost",
          title: "Telefoon én reservecodes kwijt",
          body: (
            <p>
              Neem contact op met de beheerder (zie Privacy voor het adres). Die kan inloggen in twee stappen voor je account uitzetten, waarna je het opnieuw instelt. De beheerder kan je wachtwoord of je gegevens niet zien.
            </p>
          ),
        },
      ],
    };
  }
  return {
    title: "Two-step login",
    lead: "Besides your password, logging in asks for a six-digit code: from an app on your phone, or by email. Someone who knows your password still can't get in. It is one setting of your trackerai account: you set it up once, and it holds for health-tracker, wealth-tracker and stock-tracker.",
    sections: [
      {
        id: "why",
        title: "Why it is sometimes required",
        body: (
          <p>
            When you use more than one tracker, one password opens both your health data and your money. So two-step login is required then, and for admins too. With one tracker it is your choice; it is strongly recommended.
          </p>
        ),
      },
      {
        id: "app",
        title: "1. Get an authenticator app",
        body: (
          <>
            <p>Any app that makes codes by the standard (TOTP) works, for example:</p>
            <ul className="ml-5 list-disc">{APPS.map((a) => <li key={a}>{a}</li>)}</ul>
            <p>A password manager that keeps codes too is handy: they move with you to a new phone.</p>
          </>
        ),
      },
      {
        id: "setup",
        title: "2. Set it up",
        body: (
          <ol className="ml-5 list-decimal">
            <li>Go to Settings › Account › Two-step login and choose Turn on (or follow the screen that asks for it).</li>
            <li>Scan the QR code with your app. If scanning doesn't work, type in the key below it.</li>
            <li>Enter the six-digit code the app shows now and confirm.</li>
            <li>You get ten backup codes. Keep them apart from your phone: in a password manager or on paper. They are shown only once.</li>
          </ol>
        ),
      },
      {
        id: "login",
        title: "3. Logging in",
        body: (
          <>
            <p>After your password, the site asks for the code the app shows at that moment. Each code lasts 30 seconds and works once.</p>
            <p>
              With <b>Stay logged in</b> on, you stay logged in on that device for {days} days, and it doesn&apos;t ask that device for the code for {days} days either: only for your password when you log out. On a shared or someone else&apos;s computer, turn it off; the session then ends when the browser closes.
            </p>
          </>
        ),
      },
      {
        id: "backup",
        title: "Backup codes",
        body: (
          <p>
            Without your phone at hand, enter a backup code where the code is asked. Each backup code works once. Settings › Account shows how many you have left; you can make a new set there too (the old ones stop working).
          </p>
        ),
      },
      {
        id: "email",
        title: "Codes by email",
        body: (
          <p>
            If you signed up with your email address and confirmed it with the code from the welcome mail, this is on already. Otherwise turn on <b>codes by email</b> at Settings › Account: enter your address and confirm it with the code we send. From then on, logging in mails you a six-digit code; it works once, for 10 minutes. It is simpler, and a little less strong: whoever can read your mail and knows your password gets in. So give your mailbox its own strong password and two-step login. You can use both: at login, choose &quot;Email me a code instead&quot;.
          </p>
        ),
      },
      {
        id: "phone",
        title: "A new phone",
        body: (
          <p>
            Move the codes over with the app itself (most can, or keep them in your account with that app). If that doesn&apos;t work: log in with a backup code, turn two-step login off and straight on again, and scan the new QR code with your new phone. When it is required for your account, the screen asks you to set it up again right after you turn it off.
          </p>
        ),
      },
      {
        id: "wrong",
        title: "The code is not accepted",
        body: (
          <ul className="ml-5 list-disc">
            <li>Use the newest code: a code expires after 30 seconds, and one that was used already doesn&apos;t work again.</li>
            <li>Check the time on your phone: it must be set automatically. A few minutes off is enough to make every code wrong.</li>
            <li>With more than one entry for the trackers in your app (an old one from health-tracker or stock-tracker, say), use the one that says &quot;trackerai&quot;; the old ones can go.</li>
          </ul>
        ),
      },
      {
        id: "lost",
        title: "Lost both the phone and the backup codes",
        body: (
          <p>
            Contact the admin (Privacy has the address). They can turn two-step login off for your account, and you set it up again. The admin can't see your password or your data.
          </p>
        ),
      },
    ],
  };
}

/** The help page's content. `days`: how long "stay logged in" lasts (SESSION_DAYS, from the API). */
export default function TwoStepHelp({ locale, days = 30 }: { locale: Locale; days?: number }) {
  const t = sections(locale, days);
  return (
    <article className="flex max-w-prose flex-col gap-6 text-[14px] leading-relaxed">
      <header className="flex flex-col gap-2">
        <h1 className="font-display text-[28px] font-light tracking-[-0.02em]">{t.title}</h1>
        <p className="text-ink-muted">{t.lead}</p>
      </header>
      {t.sections.map((s) => (
        <section key={s.id} id={s.id} className="flex flex-col gap-2 [&_li]:mt-1">
          <h2 className="text-[16px] font-semibold">{s.title}</h2>
          {s.body}
        </section>
      ))}
    </article>
  );
}
