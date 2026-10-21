"use client";

// Sending feedback: something broken or an idea, from any page (the sidebar, the account menu, Settings › Feedback).
// The page, the site, the language, the browser, the screen and this tab's last errors (lib/recentErrors) go along, so a report
// can be acted on without back-and-forth. A screenshot is scaled down in the browser before it is sent (the API takes
// at most 3 MB). The app sends it (`send`): both post it to their own /api/feedback.

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "../ds/Button";
import { Dialog } from "../ds/Feedback";
import { useTr, useUiLocale } from "../i18n";
import { recentErrors } from "../lib/recentErrors";
import { captureViewport } from "../lib/screenshot";

type Kind = "bug" | "idea";

/** What goes to the API. */
export type FeedbackPayload = {
  kind: Kind;
  message: string;
  page: string;
  context: ReturnType<typeof context>;
  screenshot?: string;
};
const MAX_SIDE = 1600;

async function shrink(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

function context(language: string) {
  return {
    language,
    site: location.host,
    browser: navigator.userAgent.slice(0, 300),
    screen: `${window.innerWidth}x${window.innerHeight}`,
    theme:
      document.documentElement.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark (system)" : "light (system)"),
    errors: recentErrors(),
  };
}

export default function FeedbackDialog({
  open,
  onClose,
  send: post,
  errorText,
}: {
  open: boolean;
  onClose: () => void;
  /** Posts the report; throws when that fails. */
  send: (payload: FeedbackPayload) => Promise<unknown>;
  /** The message for a failed send; the generic one when it returns nothing. */
  errorText?: (error: unknown) => string | undefined;
}) {
  const tr = useTr();
  const locale = useUiLocale();
  const KIND: Record<Kind, string> = { bug: tr("Something is broken"), idea: tr("Idea") };
  const pathname = usePathname();
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<Kind>("bug");
  const [message, setMessage] = useState("");
  const [shot, setShot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);

  // A picture of the page as it was when Feedback was clicked: the dialog is left out of it (@trackerai/ui/screenshot).
  useEffect(() => {
    if (!open || done) return;
    let cancelled = false;
    setCapturing(true);
    captureViewport().then((img) => {
      if (!cancelled && img) setShot(img);
      if (!cancelled) setCapturing(false);
    });
    return () => {
      cancelled = true;
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function close() {
    if (busy) return;
    onClose();
    setShot(null);
    if (done) {
      setDone(false);
      setMessage("");
      setKind("bug");
    }
  }

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await post({ kind, message, page: pathname, context: context(locale), screenshot: shot ?? undefined });
      setDone(true);
      qc.invalidateQueries({ queryKey: ["feedback"] });
    } catch (e) {
      setError(errorText?.(e) || tr("Sending failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={tr("Send feedback")}
      description={done ? undefined : tr("Something broken, or an idea? The admin reads everything.")}
      actions={
        done ? (
          <Button variant="primary" onClick={close}>
            {tr("Close")}
          </Button>
        ) : (
          <>
            <Button variant="ghost" disabled={busy} onClick={close}>
              {tr("Cancel")}
            </Button>
            <Button variant="primary" disabled={busy || !message.trim()} onClick={send}>
              {busy ? tr("Sending…") : tr("Send")}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <p className="text-[13.5px]">{tr("Thank you! Under Settings › Feedback you can see what happens with it.")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex gap-1.5" role="radiogroup" aria-label={tr("Kind of feedback")}>
            {(["bug", "idea"] as Kind[]).map((k) => (
              <Button
                key={k}
                size="sm"
                variant={kind === k ? "primary" : "ghost"}
                role="radio"
                aria-checked={kind === k}
                onClick={() => setKind(k)}
              >
                {KIND[k]}
              </Button>
            ))}
          </div>
          <label className="flex flex-col gap-1.5 text-[12px] font-medium text-ink-muted">
            {tr("Your message")}
            <textarea
              className="ds-input h-32 py-2 text-[13px] font-normal text-ink"
              placeholder={
                kind === "bug"
                  ? tr("What did you do, what did you expect, and what happened instead?")
                  : tr("What would you like to be able to do, and why?")
              }
              value={message}
              maxLength={5000}
              onChange={(e) => setMessage(e.target.value)}
              autoFocus
            />
          </label>
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) setShot(await shrink(f).catch(() => null));
            }}
          />
          {capturing ? (
            <p className="text-[12px] text-ink-muted">{tr("Taking a screenshot of the page…")}</p>
          ) : shot ? (
            <div className="flex items-start gap-3">
              {/* A data URL of the screenshot just taken: next/image has nothing to optimise. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={shot} alt={tr("Screenshot")} className="h-24 max-w-[45%] rounded border border-border object-cover object-top" />
              <div className="flex flex-col items-start gap-1.5">
                <p className="text-[12px] text-ink-muted">
                  {tr("A screenshot of this page is included. Remove it if there's something on it you'd rather not share.")}
                </p>
                <Button size="sm" variant="ghost" onClick={() => setShot(null)}>
                  {tr("Remove screenshot")}
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <Button size="sm" variant="ghost" onClick={() => file.current?.click()}>
                {tr("Add screenshot")}
              </Button>
            </div>
          )}
          <p className="text-[12px] text-ink-muted">
            {tr("The page, your browser, screen size and recent error messages are included. That makes it easier to fix.")}
          </p>
          {error && (
            <p className="text-[12.5px]" style={{ color: "var(--text-loss)" }}>
              {error}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}
