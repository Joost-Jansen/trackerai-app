"use client";

// Feedback: what you sent and what came of it. The inbox of everyone's reports, with status and reply, is on the admin
// page (Settings › Admin).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import FeedbackDialog from "@/components/feedback/FeedbackDialog";
import { Button, Tag } from "@/components/ds";
import { api } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";
import type { FeedbackItem } from "@/lib/training";

function Head({ f }: { f: FeedbackItem }) {
  const t = useT();
  const fmt = useFormat();
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-muted">
      <Tag>{t.feedback.kindShort[f.kind]}</Tag>
      <Tag>{t.feedback.status[f.status]}</Tag>
      <span>{fmt.dateTime(f.created_at)}</span>
      {f.page && <span className="font-mono">{f.page}</span>}
    </div>
  );
}

function ScreenshotLink({ id }: { id: number }) {
  const t = useT();
  return (
    <a
      className="self-start text-[12.5px] underline underline-offset-2"
      href={`/api/feedback/${id}/screenshot`}
      target="_blank"
      rel="noreferrer"
    >
      {t.feedback.screenshot}
    </a>
  );
}

function Mine() {
  const t = useT();
  const q = useQuery({ queryKey: ["feedback", "mine"], queryFn: () => api.get<FeedbackItem[]>("/api/feedback") });
  const [open, setOpen] = useState(false);
  return (
    <Card
      title={t.feedback.mine}
      action={
        <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
          {t.feedback.newOne}
        </Button>
      }
    >
      {!q.data ? (
        <p className="text-sm text-ink-muted">{t.common.loading}</p>
      ) : q.data.length === 0 ? (
        <p className="text-sm text-ink-muted">{t.feedback.mineNone}</p>
      ) : (
        <ul className="flex flex-col">
          {q.data.map((f) => (
            <li key={f.id} className="flex flex-col gap-1.5 border-t border-border py-3 first:border-t-0 first:pt-0">
              <Head f={f} />
              <p className="whitespace-pre-wrap text-[13.5px]">{f.message}</p>
              {f.has_screenshot && <ScreenshotLink id={f.id} />}
              {f.reply && (
                <p className="whitespace-pre-wrap rounded bg-[var(--surface-sunken)] px-3 py-2 text-[13px]">
                  <span className="font-medium">{t.feedback.reply}: </span>
                  {f.reply}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      <FeedbackDialog open={open} onClose={() => setOpen(false)} />
    </Card>
  );
}

export default function FeedbackPage() {
  return (
    <div className="flex max-w-[760px] flex-col gap-4">
      <Mine />
    </div>
  );
}
