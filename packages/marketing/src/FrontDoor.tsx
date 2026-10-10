// trackerai.nl: the front door of both trackers. It carries all the
// explaining, so each tracker's own subdomain can simply be its login page.
//
// A server component: anchors scroll, links leave, everything that moves is CSS. The one client part is the account
// (Account.tsx): logging in here, with the account every tracker shares.

import { AccountPanel, NavAccount } from "./Account";
import { BRANDS, type BrandId, type Locale } from "./brands";
import { COPY } from "./copy";
import { Icon } from "./icons";
import { HealthMark, TrackerAIMark, WealthMark } from "./marks";
import { HealthVisual, WealthVisual } from "./visuals";

export type FrontDoorProps = {
  locale: Locale;
  /** Where each tracker lives, e.g. https://health.trackerai.nl, from the environment. A tracker without an address
   *  is still described, just without its buttons. */
  urls: Partial<Record<BrandId, string>>;
  privacyHref?: string;
  /** How long "stay logged in" lasts (SESSION_DAYS). */
  days?: number;
};

const MARK = { health: HealthMark, wealth: WealthMark };
const VISUAL = { health: HealthVisual, wealth: WealthVisual };
const ORDER: BrandId[] = ["health", "wealth"];
const LANGUAGES: { id: Locale; name: string }[] = [{ id: "en", name: "English" }, { id: "nl", name: "Nederlands" }];

export default function FrontDoor({ locale, urls, privacyHref, days }: FrontDoorProps) {
  const c = COPY[locale];
  const open = (id: BrandId) => c.open.replace("{name}", BRANDS[id].name);

  return (
    <div className="mk-root">
      <header className="mk-nav">
        <a href="#top" className="mk-brand" aria-label="trackerai">
          <TrackerAIMark size={22} />
          <span>trackerai</span>
        </a>
        <nav className="mk-nav-links" aria-label="trackerai">
          <a href="#health">{c.nav.health}</a>
          <a href="#wealth">{c.nav.wealth}</a>
          <NavAccount locale={locale} />
        </nav>
      </header>

      <main id="top">
        {/* Hero: both brands' glows behind one headline. */}
        <section className="mk-band mk-duo mk-hero">
          <div className="mk-grid-lines" aria-hidden />
          <div className="mk-wrap">
            <p className="mk-eyebrow mk-fade-up">{c.hero.eyebrow}</p>
            <h1 className="mk-h1 mk-fade-up" style={{ animationDelay: "80ms" }}>{c.hero.title}</h1>
            <p className="mk-lead mk-fade-up" style={{ animationDelay: "160ms" }}>{c.hero.lead}</p>
            <div className="mk-actions mk-fade-up" style={{ animationDelay: "240ms" }}>
              <a href="#health" className="mk-btn mk-btn--accent mk-health">{c.hero.health}</a>
              <a href="#wealth" className="mk-btn mk-btn--accent mk-wealth">{c.hero.wealth}</a>
            </div>
          </div>

          <div className="mk-wrap mk-cards">
            {ORDER.map((id, i) => {
              const b = c.brands[id];
              const Mark = MARK[id];
              return (
                <article key={id} className={`mk-card ${BRANDS[id].className} mk-fade-up`} style={{ animationDelay: `${320 + i * 120}ms` }}>
                  <div className="mk-card-head">
                    <Mark size={24} />
                    <span className="mk-card-name">{BRANDS[id].name}</span>
                  </div>
                  <h2 className="mk-h3">{b.title}</h2>
                  <ul className="mk-points">
                    {b.points.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                  <div className="mk-actions">
                    {urls[id] && <a href={`${urls[id]}/`} className="mk-btn mk-btn--accent">{open(id)}</a>}
                    <a href={`#${id}`} className="mk-btn mk-btn--ghost">{c.more}</a>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        {/* One band per tracker, in its own colours. */}
        {ORDER.map((id) => {
          const b = c.brands[id];
          const Visual = VISUAL[id];
          const Mark = MARK[id];
          return (
            <section key={id} id={id} className={`mk-band ${BRANDS[id].className} mk-section`}>
              <div className="mk-grid-lines" aria-hidden />
              <div className="mk-wrap mk-split">
                <div className="mk-split-text">
                  <p className="mk-eyebrow mk-kicker"><Mark size={18} /> {b.kicker}</p>
                  <h2 className="mk-h2">{b.title}</h2>
                  <p className="mk-lead">{b.lead}</p>
                  <ul className="mk-checks">
                    {b.privacy.map((p) => <li key={p}><Icon name="lock" size={16} />{p}</li>)}
                  </ul>
                  {urls[id] && (
                    <div className="mk-actions">
                      <a href={`${urls[id]}/`} className="mk-btn mk-btn--accent">{open(id)}</a>
                      <a href="#signup" className="mk-btn mk-btn--ghost">{c.createAccount}</a>
                    </div>
                  )}
                </div>
                <Visual locale={locale} label={c.visual[id]} />
              </div>
              <div className="mk-wrap mk-features">
                {b.features.map((f) => (
                  <div key={f.title} className="mk-glass">
                    <span className="mk-icon"><Icon name={f.icon} /></span>
                    <h3 className="mk-h4">{f.title}</h3>
                    <p>{f.text}</p>
                  </div>
                ))}
              </div>
            </section>
          );
        })}

        {/* What both share. */}
        <section className="mk-section mk-light">
          <div className="mk-wrap">
            <p className="mk-eyebrow">{c.shared.eyebrow}</p>
            <h2 className="mk-h2">{c.shared.title}</h2>
            <div className="mk-features mk-features--light">
              {c.shared.items.map((f) => (
                <div key={f.title} className="mk-tile">
                  <span className="mk-icon mk-icon--duo"><Icon name={f.icon} /></span>
                  <h3 className="mk-h4">{f.title}</h3>
                  <p>{f.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mk-section mk-light mk-start">
          <div className="mk-wrap">
            <p className="mk-eyebrow">{c.start.eyebrow}</p>
            <h2 className="mk-h2">{c.start.title}</h2>
            <ol className="mk-steps">
              {c.start.steps.map((s, i) => (
                <li key={s.title}>
                  <span className="mk-step-n">{i + 1}</span>
                  <h3 className="mk-h4">{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="login" className="mk-band mk-duo mk-section mk-closing">
          <div className="mk-grid-lines" aria-hidden />
          <div className="mk-wrap mk-center">
            <TrackerAIMark size={34} />
            <h2 className="mk-h2">{c.closing.title}</h2>
            <p className="mk-lead">{c.closing.lead}</p>
            <span id="signup" aria-hidden />
            <AccountPanel locale={locale} urls={urls} days={days} />
          </div>
        </section>
      </main>

      <footer className="mk-footer">
        <div className="mk-wrap mk-footer-row">
          <span className="mk-brand"><TrackerAIMark size={18} /><span>{c.footer.made}</span></span>
          <span className="mk-footer-links">
            {privacyHref && <a href={privacyHref}>{c.footer.privacy}</a>}
            {/* English until someone picks Nederlands; the host keeps the choice (`?lang=`, see LOCALE_COOKIE). Each
                language is named in itself, so the way back is readable whichever is shown. */}
            <span className="mk-lang" role="group" aria-label={c.footer.language}>
              {LANGUAGES.map(({ id, name }) => (id === locale
                ? <span key={id} aria-current="true" lang={id}>{name}</span>
                : <a key={id} href={`?lang=${id}`} lang={id} hrefLang={id} rel="nofollow">{name}</a>))}
            </span>
          </span>
        </div>
      </footer>
    </div>
  );
}
