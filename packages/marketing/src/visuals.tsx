// Stylised illustrations of the two apps: not screenshots, so they never show
// anyone's data. Colours come from the brand palette (--mk-*), motion from
// marketing.css (drawn lines, growing bars, floating chips; all off under
// prefers-reduced-motion).

import type { Locale } from "./brands";

const CHIPS = {
  en: { run: "Easy run", km: "8.2 km", zone: "Zone 2", recovery: "Recovery", worth: "Net worth", month: "this month", saved: "Saved", market: "Market" },
  nl: { run: "Rustige duurloop", km: "8,2 km", zone: "Zone 2", recovery: "Herstel", worth: "Vermogen", month: "deze maand", saved: "Gespaard", market: "Markt" },
};

function Window({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <svg viewBox="0 0 520 330" className="mk-visual-svg" role="img" aria-label={label}>
      <rect x="1" y="1" width="518" height="328" rx="18" fill="rgba(255,255,255,0.035)" stroke="rgba(255,255,255,0.10)" />
      {[0, 1, 2].map((i) => <circle key={i} cx={22 + i * 13} cy={22} r={4} fill="rgba(255,255,255,0.22)" />)}
      <line x1="1" x2="519" y1="42" y2="42" stroke="rgba(255,255,255,0.08)" />
      {children}
    </svg>
  );
}

export function HealthVisual({ locale, label }: { locale: Locale; label: string }) {
  const t = CHIPS[locale];
  const circumference = 2 * Math.PI * 46;
  const zones = [38, 86, 54, 26, 12];
  return (
    <div className="mk-visual">
      <Window label={label}>
        {/* Recovery ring */}
        <circle cx="96" cy="128" r="46" fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="10" />
        <circle cx="96" cy="128" r="46" fill="none" stroke="var(--mk-accent)" strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${circumference * 0.82} ${circumference}`} transform="rotate(-90 96 128)" className="mk-fade-up" />
        <text x="96" y="134" textAnchor="middle" fontSize="26" fontWeight="600" fill="var(--mk-on-ink)">82</text>
        <text x="96" y="196" textAnchor="middle" fontSize="12" fill="var(--mk-on-ink-muted)">{t.recovery}</text>

        {/* Zones this week */}
        {zones.map((h, i) => (
          <rect key={i} x={196 + i * 30} y={170 - h} width="20" height={h} rx="5"
            fill={i === 1 ? "var(--mk-accent)" : "rgba(255,255,255,0.18)"}
            className="mk-grow" style={{ animationDelay: `${200 + i * 90}ms` }} />
        ))}
        <line x1="190" x2="350" y1="172" y2="172" stroke="rgba(255,255,255,0.12)" />
        {["1", "2", "3", "4", "5"].map((z, i) => (
          <text key={z} x={206 + i * 30} y="190" textAnchor="middle" fontSize="11" fill="var(--mk-on-ink-muted)">Z{z}</text>
        ))}

        {/* A loop on the map */}
        <rect x="372" y="62" width="128" height="128" rx="14" fill="rgba(255,255,255,0.04)" />
        <path d="M398 160c-14-30 4-74 38-80s54 20 44 46-36 30-54 24-30 12-28 10z" fill="none"
          stroke="var(--mk-accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="mk-draw" />
        <circle cx="398" cy="160" r="5" fill="var(--mk-accent)" className="mk-pulse" />

        {/* Heart rate over a session */}
        <path d="M24 290 L70 284 L100 262 L130 270 L160 240 L190 252 L220 226 L250 236 L280 214 L310 228 L340 206 L370 220 L400 198 L430 212 L460 190 L496 200"
          fill="none" stroke="var(--mk-accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="mk-draw" />
        <path d="M24 300 L496 300" stroke="rgba(255,255,255,0.10)" />
      </Window>
      <div className="mk-chip mk-float" style={{ top: "6%", right: "-4%" }}>
        <span className="mk-chip-dot" />
        <span><b>{t.run}</b> · {t.km}</span>
      </div>
      <div className="mk-chip mk-float mk-float--late" style={{ bottom: "8%", left: "-5%" }}>
        <b>{t.zone}</b> · 74%
      </div>
    </div>
  );
}

export function WealthVisual({ locale, label }: { locale: Locale; label: string }) {
  const t = CHIPS[locale];
  const euro = (v: string) => (locale === "nl" ? `€ ${v}` : `€${v}`);
  // A made-up net worth that rises with some wobble, as stacked areas.
  const xs = Array.from({ length: 13 }, (_, i) => 30 + i * 38);
  const invest = [60, 64, 62, 70, 74, 72, 80, 86, 84, 92, 98, 104, 112];
  const bank = [48, 50, 54, 52, 56, 60, 58, 62, 66, 64, 68, 70, 72];
  const base = 250;
  const y = (v: number) => base - v;
  const areaI = `M${xs[0]} ${base} ` + xs.map((x, i) => `L${x} ${y(invest[i])}`).join(" ") + ` L${xs[12]} ${base} Z`;
  const areaB = xs.map((x, i) => `${i ? "L" : "M"}${x} ${y(invest[i] + bank[i])}`).join(" ")
    + " " + [...xs].reverse().map((x, j) => `L${x} ${y(invest[12 - j])}`).join(" ") + " Z";
  const net = xs.map((x, i) => `${i ? "L" : "M"}${x} ${y(invest[i] + bank[i] - 22)}`).join(" ");
  return (
    <div className="mk-visual">
      <Window label={label}>
        <text x="30" y="80" fontSize="12" fill="var(--mk-on-ink-muted)">{t.worth}</text>
        <text x="30" y="108" fontSize="26" fontWeight="600" fill="var(--mk-on-ink)">{euro(locale === "nl" ? "48.210" : "48,210")}</text>
        <text x="200" y="108" fontSize="13" fill="var(--mk-accent)">+{euro(locale === "nl" ? "1.240" : "1,240")} {t.month}</text>
        {[150, 200, 250].map((g) => <line key={g} x1="30" x2="490" y1={g} y2={g} stroke="rgba(255,255,255,0.07)" strokeDasharray="3 5" />)}
        <path d={areaB} fill="rgba(255,255,255,0.12)" className="mk-fade-up" />
        <path d={areaI} fill="color-mix(in srgb, var(--mk-accent) 45%, transparent)" className="mk-fade-up" style={{ animationDelay: "150ms" }} />
        <path d={net} fill="none" stroke="var(--mk-on-ink)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="mk-draw" />
        <rect x="30" y="268" width="460" height="22" rx="6" fill="rgba(255,255,255,0.05)" />
        <rect x="30" y="268" width="250" height="22" rx="6" fill="var(--mk-accent)" className="mk-grow-x" />
        <text x="40" y="283" fontSize="11" fontWeight="600" fill="var(--mk-ink-deep)">{t.saved}</text>
        <text x="300" y="283" fontSize="11" fill="var(--mk-on-ink-muted)">{t.market}</text>
      </Window>
      <div className="mk-chip mk-float" style={{ top: "4%", right: "-4%" }}>
        <span className="mk-chip-dot" />
        <span><b>{t.saved}</b> +{euro("860")}</span>
      </div>
      <div className="mk-chip mk-float mk-float--late" style={{ bottom: "10%", left: "-5%" }}>
        <b>{t.market}</b> +{euro("380")}
      </div>
    </div>
  );
}
