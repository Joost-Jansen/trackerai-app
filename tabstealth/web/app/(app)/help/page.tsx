"use client";

import Card from "@trackerai/ui/components/Card";
import { useT } from "@/lib/i18n";

export default function HelpPage() {
  const t = useT();
  const parts = [
    [t.help.how, t.help.howText],
    [t.help.sync, t.help.syncText],
    [t.help.edit, t.help.editText],
    [t.help.practice, t.help.practiceText],
    [t.help.review, t.help.reviewText],
    [t.help.private, t.help.privateText],
  ];
  return (
    <div className="mx-auto flex max-w-[68ch] flex-col gap-3">
      {parts.map(([title, text]) => (
        <Card key={title} title={title}>
          <p className="text-sm leading-relaxed text-ink-muted">{text}</p>
        </Card>
      ))}
      <Card title={t.help.keys}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {t.song.keyList.map(([k, what]) => (
            <div key={k} className="contents">
              <dt className="font-mono">{k}</dt>
              <dd className="text-ink-muted">{what}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
