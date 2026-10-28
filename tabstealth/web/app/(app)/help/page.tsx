"use client";

import Card from "@trackerai/ui/components/Card";
import { useT } from "@/lib/i18n";

export default function HelpPage() {
  const t = useT();
  const parts = [
    [t.help.how, t.help.howText],
    [t.help.sync, t.help.syncText],
    [t.help.edit, t.help.editText],
    [t.help.private, t.help.privateText],
  ];
  return (
    <div className="mx-auto flex max-w-[68ch] flex-col gap-3">
      {parts.map(([title, text]) => (
        <Card key={title} title={title}>
          <p className="text-sm leading-relaxed text-ink-muted">{text}</p>
        </Card>
      ))}
    </div>
  );
}
