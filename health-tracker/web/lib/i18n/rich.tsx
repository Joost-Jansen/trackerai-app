// Sentences with a link or bold word in them, translated as one sentence: "Koppel bij <link>Koppelingen</link>."
// rich(text, { link: (c) => <A href="...">{c}</A> }) turns each <tag>…</tag> into that element. No nesting.

import { Fragment, type ReactNode } from "react";

export function rich(text: string, tags: Record<string, (children: string) => ReactNode>): ReactNode {
  const out: ReactNode[] = [];
  const re = /<(\w+)>([\s\S]*?)<\/\1>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const render = tags[m[1]];
    out.push(<Fragment key={out.length}>{render ? render(m[2]) : m[2]}</Fragment>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

export const bold = (c: string) => <b>{c}</b>;
