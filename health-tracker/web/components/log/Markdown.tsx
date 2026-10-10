"use client";

// Markdown from the log, the analyses, the goals and plans. Raw HTML in the text is shown as text, not
// executed: agents write here too, and an agent can be talked into writing anything. Everything that ends up in
// the HTML goes through `escape` (quotes included, so nothing breaks out of an attribute); a link's text is
// rendered from its tokens (the raw `text` would carry HTML as is); images are only shown from this site.

import { useMemo } from "react";
import { Marked } from "marked";

const escape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const md = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    html({ text }) {
      return escape(text);
    },
    link({ href, tokens }) {
      const safe = /^(https?:\/\/|\/(?!\/)|#)/i.test(href) ? href : "#";
      const external = /^https?:/i.test(safe);
      return `<a href="${escape(safe)}"${external ? ' target="_blank"' : ""} rel="noreferrer noopener">${this.parser.parseInline(tokens)}</a>`;
    },
    image({ href, text }) {
      // remote images would leak who reads the page (and the CSP blocks them anyway): show the alt text instead
      return /^\/(?!\/)/.test(href) ? `<img src="${escape(href)}" alt="${escape(text)}">` : escape(text);
    },
  },
});

export default function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const html = useMemo(() => md.parse(text ?? "") as string, [text]);
  return (
    <div
      className={[
        "text-[13.5px] leading-relaxed",
        "[&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:font-display [&_h1]:text-[21px] [&_h1]:font-light",
        "[&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-[15px] [&_h2]:font-semibold",
        "[&_h3]:mb-1.5 [&_h3]:mt-4 [&_h3]:text-[13.5px] [&_h3]:font-semibold",
        "[&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5",
        "[&_a]:underline [&_a]:underline-offset-2 [&_strong]:font-semibold",
        "[&_code]:rounded [&_code]:bg-[var(--surface-inset)] [&_code]:px-1 [&_code]:font-mono [&_code]:text-[12px]",
        "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-[var(--surface-sunken)] [&_pre]:p-3",
        "[&_table]:my-3 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_table]:text-[12.5px] [&_table]:tabular-nums",
        "[&_th]:border-b [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-normal [&_th]:text-ink-muted",
        "[&_td]:border-b [&_td]:border-border [&_td]:px-2 [&_td]:py-1",
        "[&>*:first-child]:mt-0",
        className,
      ].join(" ")}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
