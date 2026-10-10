"use client";

// The aligned section — the signature element of this design, and the reason the
// app will soon have almost no cards any more.
//
// A section is: an 11px small-caps label above a full-width rule, with the
// content below. No box. An ink rule (--n-800) for what is primary, a hairline
// for what is secondary, and once per screen a 2px brand-coloured rule for the block
// that asks for your attention.
//
// This replaces components/Card.tsx in the forty places where the card was only
// drawing a border. A real card (ds-card) stays for what really floats: dialogs
// and menus.

import InfoPopover from "../components/InfoPopover";
import { useTr } from "../i18n";

type Props = {
  /** The small-caps label above the rule. */
  label?: React.ReactNode;
  /**
   * One or two sentences about what this section shows, behind an "i" next to the
   * header. The middle of the three help levels: the "?" in the top bar is about
   * the whole screen, this "i" about this list or chart, and the "i" next to a
   * single number about that number.
   *
   * **Explanation only.** What is about *your* figures — "12 positions", "3
   * countries dropped out" — is not an explanation but an outcome, and so belongs
   * in `meta` or in the content, where you see it without clicking.
   */
  info?: React.ReactNode;
  /**
   * What the "i" announces to a screen reader, if the header is not plain text.
   * Otherwise it is derived from `label`.
   */
  infoLabel?: string;
  /**
   * Quiet context on the right of the same line — "12 positions", "3 hours ago".
   *
   * **Keep it short.** The header wraps if it does not fit next to it, and then
   * something sits *between* the header and its rule — exactly what makes the rule
   * useless as "a new subject starts here". A whole sentence is not meta but an
   * introduction, and so belongs in the content.
   */
  meta?: React.ReactNode;
  /**
   * A small control on the right of the header row — a switch of two or three
   * buttons, a download link. Goes before `meta`.
   *
   * If the control does not fit next to it (the seven-button period picker on a
   * phone), put it as the first child *in* the section: below the rule, right
   * above the thing it controls. That is where it belongs anyway — a quiet switch
   * sits next to what it filters, not in the chrome.
   */
  action?: React.ReactNode;
  /** quiet = hairline instead of ink rule, for a section in a side column. */
  tone?: "ink" | "quiet" | "brand";
  className?: string;
  children: React.ReactNode;
};

export default function Section({
  label,
  info,
  infoLabel,
  meta,
  action,
  tone = "ink",
  className = "",
  children,
}: Props) {
  const tr = useTr();
  // The header with its "i" as one block, so the button stays on the left by the
  // text and does not drift to the middle of the header row. items-center and not
  // baseline: a button without text has its baseline at the bottom, and then the
  // glyph hangs a few pixels below the small caps.
  const heading = (style?: React.CSSProperties) =>
    label && (
      <span className="ds-section__label inline-flex items-center gap-1" style={style}>
        {label}
        {info && (
          <InfoPopover
            label={infoLabel ?? (typeof label === "string" ? tr("Explanation {0}", label) : tr("Explanation"))}
          >
            {info}
          </InfoPopover>
        )}
      </span>
    );

  if (tone === "brand") {
    // The advice block: one per screen, and the only brand-coloured moment on it.
    //
    // The same shape as every other section — header above, rule below — and only
    // the rule is different: 2px brand colour instead of 1px ink. The reference screen
    // puts it *above* the header, and that works there because it sits in a side
    // column of its own. In one column stacked that gives a rule that hangs above a
    // header one time and below it the next, and then you no longer know where a
    // subject starts.
    return (
      <section className={`ds-section ${className}`}>
        <div
          className="ds-section__head"
          style={{ borderBottomWidth: 2, borderBottomColor: "var(--brand)" }}
        >
          {heading({ color: "var(--text-brand)" })}
          {meta && <span className="ds-section__meta">{meta}</span>}
        </div>
        {children}
      </section>
    );
  }

  return (
    <section className={`ds-section ${tone === "quiet" ? "ds-section--quiet" : ""} ${className}`}>
      {(label || meta || action) && (
        <div className="ds-section__head">
          {heading()}
          {action ?? (meta && <span className="ds-section__meta">{meta}</span>)}
        </div>
      )}
      {children}
    </section>
  );
}

/** The small small-caps label above a number. */
export function Eyebrow({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`ds-eyebrow ${className}`}>{children}</span>;
}

/**
 * The hero number: exactly one per screen, at 68px in the display face.
 *
 * Everything that supports it is at 21px or less. Never give a supporting number
 * a box to make it look important — scale and space do that work.
 */
export function Hero({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`ds-hero ${className}`}>{children}</span>;
}

/**
 * A supporting number: label above, value in the display face at 21px,
 * optionally a line of context below.
 *
 * Three to four of them in a left-heavy row under the ink rule, with the right
 * side of that rule deliberately empty — that is the asymmetry the design asks
 * for.
 */
export function Figure({
  label,
  value,
  note,
  info,
  tone,
  className = "",
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  note?: React.ReactNode;
  /**
   * What exactly this number measures, behind an "i" next to the label. The
   *  smallest of the three help levels — one or two sentences, no more.
   */
  info?: React.ReactNode;
  tone?: "gain" | "loss";
  className?: string;
}) {
  const tr = useTr();
  return (
    <div className={`flex flex-col gap-[5px] ${className}`}>
      <span className="flex items-center gap-1">
        <Eyebrow>{label}</Eyebrow>
        {info && (
          <InfoPopover label={typeof label === "string" ? tr("Explanation {0}", label) : tr("Explanation")}>
            {info}
          </InfoPopover>
        )}
      </span>
      <span
        className="num font-display text-[21px] leading-tight tracking-[-0.02em]"
        style={{ color: tone === "gain" ? "var(--text-gain)" : tone === "loss" ? "var(--text-loss)" : undefined }}
      >
        {value}
      </span>
      {note && <span className="text-xs text-ink-muted">{note}</span>}
    </div>
  );
}

/** A bare hairline, for where space alone turns out not to be enough. */
export function Rule({ className = "" }: { className?: string }) {
  return <hr className={`ds-rule ${className}`} />;
}
