import type { NewsItem, NewsLabel } from "@/lib/dashboard";
import { fmtRelative } from "@/lib/format";
import { tr } from "@/lib/i18n";

// The editorial rhythm of this design: kind and time on a quiet line above the
// headline, the headline below it, the summary below that, separated by one
// hairline per article.
//
// What is gone: six coloured chips (Earnings blue, Dividend green, M&A red…).
// Colour is not a surface treatment in this system, and six categories each
// claiming their own colour made the taxonomy louder than the headlines
// themselves. One calm small-caps label does the same work: it says *what* kind
// of item it is, and lets the item itself hold the attention.

/** The kind of item, in the words the rest of the app uses. */
const LABEL_NL: Record<NewsLabel, string> = {
  Earnings: tr("Quarterly results"),
  Dividend: "Dividend",
  Analyst: tr("Analyst"),
  "M&A": tr("Takeover"),
  World: "World",
  Macro: "Macro",
};

export function NewsTag({ label }: { label: NewsLabel }) {
  return <span className="ds-eyebrow">{LABEL_NL[label] ?? label}</span>;
}

// Alpha Vantage gives a sentiment score in [-1, 1]; only show it when it is there
// and really not neutral, as a small direction hint on the meta line.
//
// A plain function and not a component: as <SentimentHint score={0.02}/> this
// returned null for a neutral score, but the *element* was still truthy, so the
// `sentiment && …` guard below drew the separator with nothing after it — every
// almost-neutral article ended on a stray "·".
function sentimentHint(score: number): React.ReactNode {
  if (score >= 0.15)
    return <span style={{ color: "var(--text-gain)" }}>{tr("↑ positive")}</span>;
  if (score <= -0.15)
    return <span style={{ color: "var(--text-loss)" }}>{tr("↓ negative")}</span>;
  return null;
}

export default function NewsList({
  items,
  showSummary = false,
}: {
  items: NewsItem[];
  showSummary?: boolean;
}) {
  return (
    <div className="grid xl:grid-cols-2 xl:gap-x-12">
      {items.map((item, i) => {
        const sentiment =
          typeof item.sentiment === "number" ? sentimentHint(item.sentiment) : null;
        const subject = item.holding ?? item.ticker;
        // Some feeds put the headline once more in the summary field. The same sentence
        // twice one below the other is not a summary but noise, so we leave it out —
        // normalising on letters, because the repeat often only differs in punctuation
        // and the publisher's suffix.
        const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9]+/g, "");
        const summary =
          item.summary && !norm(item.summary).startsWith(norm(item.title).slice(0, 60))
            ? item.summary
            : null;
        return (
          <article
            key={item.id}
            className={`row-rule flex flex-col gap-1.5 py-5 first:pt-0 xl:[&:nth-child(2)]:border-t-0 xl:[&:nth-child(2)]:pt-0 ${i === 0 ? "row-rule--none" : ""}`}
          >
            <div className="flex flex-wrap items-baseline gap-x-3 text-[11.5px] text-ink-muted">
              <NewsTag label={item.label} />
              {item.published && <span>{fmtRelative(item.published)}</span>}
            </div>

            <h3 className="font-display text-[19px] font-normal leading-snug tracking-[-0.02em]">
              {item.link ? (
                <a href={item.link} target="_blank" rel="noopener noreferrer" className="hover:underline">
                  {item.title}
                </a>
              ) : (
                item.title
              )}
            </h3>

            {showSummary && summary && (
              <p className="line-clamp-3 max-w-measure text-[14px] leading-relaxed text-ink-muted">
                {summary}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-x-1.5 text-[11.5px] text-ink-muted">
              {subject && <span className="text-text">{subject}</span>}
              {subject && item.publisher && <span>·</span>}
              {item.publisher && <span>{item.publisher}</span>}
              {sentiment && (
                <>
                  <span>·</span>
                  {sentiment}
                </>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
