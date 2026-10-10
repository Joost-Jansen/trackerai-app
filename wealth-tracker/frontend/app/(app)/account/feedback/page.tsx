"use client";

// Feedback: what you sent and what happened with it. The inbox of everyone's
// feedback, with status and reply, is on the admin page (Settings › Admin).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import FeedbackDialog from "@/components/feedback/FeedbackDialog";
import { Button, Tag } from "@/components/ds";
import { api } from "@/lib/api";
import { intlLocale, tr } from "@/lib/i18n";

type Status = "new" | "planned" | "fixed" | "wontfix";
type Item = {
  id: number;
  username: string;
  app: "wealth" | "stock" | "money" | null;
  kind: "bug" | "idea";
  message: string;
  page: string | null;
  status: Status;
  reply: string | null;
  has_screenshot: boolean;
  created_at: string;
};

const STATUS: Record<Status, string> = { new: tr("New"), planned: tr("Planned"), fixed: tr("Fixed"), wontfix: tr("Won't do") };
const KIND = { bug: tr("Broken"), idea: tr("Idea") };
// The API reports "wealth"; older answers said "stock" or "money" (lib/app.ts).
const SITE = { wealth: "wealth-tracker", stock: "wealth-tracker", money: "wealth-tracker" };
const when = (iso: string) => new Date(iso).toLocaleString(intlLocale, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function Header({ f }: { f: Item }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-muted">
      <Tag>{KIND[f.kind]}</Tag>
      <Tag>{STATUS[f.status]}</Tag>
      <span>{when(f.created_at)}</span>
      <span>{SITE[f.app ?? "wealth"]}</span>
      {f.page && <span className="font-mono">{f.page}</span>}
    </div>
  );
}

function ScreenshotLink({ id }: { id: number }) {
  return (
    <a className="self-start text-[12.5px] underline underline-offset-2" href={`/api/feedback/${id}/screenshot`} target="_blank" rel="noreferrer">{tr("Screenshot")}</a>
  );
}

function My() {
  const q = useQuery({ queryKey: ["feedback", "my"], queryFn: () => api.get<{ feedback: Item[] }>("/api/feedback") });
  const [open, setOpen] = useState(false);
  const items = q.data?.feedback;
  return (
    <Card title={tr("Your feedback")} action={<Button size="sm" variant="primary" onClick={() => setOpen(true)}>{tr("New feedback")}</Button>}>
      {!items ? (
        <p className="text-sm text-ink-muted">{tr("Loading…")}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-ink-muted">{tr("You haven't sent any feedback yet.")}</p>
      ) : (
        <ul className="flex flex-col">
          {items.map((f) => (
            <li key={f.id} className="flex flex-col gap-1.5 border-t border-border py-3 first:border-t-0 first:pt-0">
              <Header f={f} />
              <p className="whitespace-pre-wrap text-[13.5px]">{f.message}</p>
              {f.has_screenshot && <ScreenshotLink id={f.id} />}
              {f.reply && (
                <p className="whitespace-pre-wrap rounded px-3 py-2 text-[13px]" style={{ background: "var(--surface-sunken)" }}>
                  <span className="font-medium">{tr("Reply:")}{" "}</span>
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
      <My />
    </div>
  );
}
